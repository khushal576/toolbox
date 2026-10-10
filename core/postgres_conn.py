"""
core/postgres_conn.py

The one place that knows how to open a Postgres connection safely —
build a conninfo string, pre-validate credentials with a one-off connect
before anything pooled is built on top, and scrub passwords out of error
messages. Extracted out of sql-studio/db_engine.py and
schema-map/db_engine.py, which each had their own byte-identical copy of
this logic; both now call this module instead of re-deriving it.
core/pooled_postgres.py builds the pool+reaper lifecycle on top of these
primitives; orchestrator/connectors/postgres.py (a one-shot, unpooled
connector) uses scrub_password() directly for the same error-message
shape, without going through the pool machinery at all.

SSH tunnel support: open_ssh_tunnel() below opens the tunnel; the CALLER
(core.pooled_postgres or orchestrator's one-shot connector) then calls
build_conninfo(host="localhost", port=tunnel.local_bind_port, ...)
unchanged — build_conninfo() itself needs no tunnel-specific parameter.
Shared here so sql-studio, schema-map, and the orchestrator all get it
from one implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg
from psycopg.conninfo import make_conninfo
from sshtunnel import SSHTunnelForwarder

_PASSWORD_RE = re.compile(r"password\s*=\s*\S+", re.IGNORECASE)


@dataclass
class SSHTunnelConfig:
    ssh_host: str
    ssh_port: int
    ssh_username: str
    ssh_password: str | None = None
    ssh_private_key: str | None = None  # pasted PEM text, not a file path


def ssh_tunnel_from_dict(raw: dict | None) -> SSHTunnelConfig | None:
    """Shared conversion from a plain dict (a parsed request body, a
    vault-saved connection's ssh_tunnel field, etc.) to SSHTunnelConfig —
    sql-studio/server.py and schema-map/server.py both call this instead
    of each hand-rolling the same field-by-field conversion from their
    own SSHTunnelRequest pydantic model (via `.model_dump()`)."""
    if not raw:
        return None
    return SSHTunnelConfig(
        ssh_host=raw["ssh_host"], ssh_port=raw.get("ssh_port", 22),
        ssh_username=raw["ssh_username"], ssh_password=raw.get("ssh_password"),
        ssh_private_key=raw.get("ssh_private_key"),
    )


def scrub_password(message: str) -> str:
    """Defense-in-depth: strip anything shaped like 'password=...' from an
    error message before it's logged or returned to a browser/caller.
    Verified (see sql-studio/CLAUDE.md) that libpq/psycopg don't embed the
    cleartext password in their own exception text today — this stays in
    place for a future version or a differently-shaped error string, not
    because today's version was found to leak anything."""
    return _PASSWORD_RE.sub("password=***", message)


def build_conninfo(
    host: str, port: int, database: str, username: str, password: str,
    *, statement_timeout_ms: int | None = None,
) -> str:
    """Build a psycopg conninfo string. statement_timeout_ms, if given,
    sets a session-level default (libpq's "options" conninfo param passes
    "-c NAME=VALUE" to the backend at connection start) applying to every
    statement on every connection built from this conninfo — see
    sql-studio/CLAUDE.md's "500-row cap is a LIMIT-wrap, not a cost
    limiter" for why this exists there. Omitted (None) for tools that
    don't need it (e.g. schema-map, which only ever runs its own fixed,
    cheap introspection queries)."""
    options = f"-c statement_timeout={statement_timeout_ms}" if statement_timeout_ms else None
    return make_conninfo(
        host=host, port=port, dbname=database, user=username, password=password,
        **({"options": options} if options else {}),
    )


def verify_connection(conninfo: str, connect_timeout: int = 10) -> None:
    """Validate credentials with a direct, UNPOOLED connection — NOT by
    opening a pool and hoping a bad host/port/db/password surfaces on its
    own. Two real bugs were found this way (not assumed from the
    psycopg_pool docs), both independently rediscovered in sql-studio and
    schema-map before this was shared: (1) with min_size=0, pool.open()
    doesn't eagerly create any real connection, so a bad password wasn't
    caught until the first query ran; (2) even forcing a pool checkout,
    ConnectionPool retries failed attempts in the background and a
    timed-out checkout raises a generic "couldn't get a connection after
    N sec" instead of the real error, taking the full timeout to fail.
    This raises the actual OperationalError (e.g. "password authentication
    failed for user ...") immediately. Raises on failure; callers build
    their pool only after this succeeds."""
    with psycopg.connect(conninfo, connect_timeout=connect_timeout) as conn:
        conn.execute("SELECT 1")


def _parse_private_key(pem_text: str):
    """Pasted PEM text, not a file path. Tries the common key types in
    turn (paramiko has no single auto-detecting loader across the
    versions this repo might run) — RSA/Ed25519/ECDSA cover the
    overwhelming majority of real-world keys; raises the last error if
    none parse."""
    import io

    from paramiko import ECDSAKey, Ed25519Key, RSAKey

    last_exc: Exception | None = None
    for key_cls in (RSAKey, Ed25519Key, ECDSAKey):
        try:
            return key_cls.from_private_key(io.StringIO(pem_text))
        except Exception as exc:  # noqa: BLE001 - trying multiple key types by design
            last_exc = exc
    raise ValueError(f"Could not parse SSH private key: {last_exc}")


def open_ssh_tunnel(config: SSHTunnelConfig, *, remote_host: str, remote_port: int) -> SSHTunnelForwarder:
    """Open an SSH tunnel to config.ssh_host and forward a local port to
    *remote_host*:*remote_port* as seen from the SSH server. Returns the
    started, live forwarder — the caller keeps it alive (it's a real
    background thread holding an open SSH connection) and MUST call
    .stop() on it when the DB connection it's carrying is done, or it
    leaks a connection against the SSH server forever. The forwarded
    local port is `tunnel.local_bind_port`.

    Exactly one of ssh_password/ssh_private_key should be set on
    *config* — a private key (PEM text, not a file path — pasted into
    the vault/UI, nothing here ever touches the local filesystem for it)
    takes precedence if both are somehow provided.
    """
    pkey = _parse_private_key(config.ssh_private_key) if config.ssh_private_key else None

    tunnel = SSHTunnelForwarder(
        (config.ssh_host, config.ssh_port),
        ssh_username=config.ssh_username,
        ssh_password=None if pkey else config.ssh_password,
        ssh_pkey=pkey,
        remote_bind_address=(remote_host, remote_port),
    )
    tunnel.start()
    return tunnel

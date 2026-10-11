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
    ssh_private_key_passphrase: str | None = None  # only for an encrypted private key


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
        ssh_private_key_passphrase=raw.get("ssh_private_key_passphrase") or None,
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


def _parse_private_key(pem_text: str, passphrase: str | None = None):
    """Pasted PEM/OpenSSH text, not a file path. Decoded with
    `cryptography`'s universal loaders, NOT by trying each paramiko key
    class's own from_private_key() in turn: those only recognise their
    own PEM header, so a PKCS#8 key ('BEGIN PRIVATE KEY', a very common
    shape) matched none of them and surfaced a misleading error naming
    the wrong algorithm. The real algorithm is read off the decoded key
    object, then wrapped in the matching paramiko class. The passphrase
    (if the key is encrypted) is used only here, in memory."""
    import paramiko
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa

    key_bytes = pem_text.strip().encode()
    password = passphrase.encode() if passphrase else None
    is_openssh = b"OPENSSH PRIVATE KEY" in key_bytes
    try:
        if is_openssh:
            crypto_key = serialization.load_ssh_private_key(key_bytes, password=password)
        else:
            crypto_key = serialization.load_pem_private_key(key_bytes, password=password)
    except Exception as exc:  # noqa: BLE001 - cryptography raises TypeError/ValueError/UnsupportedAlgorithm
        if password is None and ("password" in str(exc).lower() or "encrypted" in str(exc).lower()):
            raise ValueError("The SSH private key is encrypted — enter its passphrase.") from exc
        if password is not None:
            raise ValueError("Couldn't decrypt the SSH private key — wrong passphrase?") from exc
        raise ValueError(f"Couldn't parse the SSH private key: {exc}") from exc
    if isinstance(crypto_key, ed25519.Ed25519PrivateKey):
        # paramiko's Ed25519Key can't take a decoded key object — hand it
        # the same key re-serialized, unencrypted, in memory only.
        import io

        text = crypto_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption(),
        ).decode()
        return paramiko.Ed25519Key.from_private_key(io.StringIO(text))
    for crypto_type, paramiko_type in (
        (rsa.RSAPrivateKey, paramiko.RSAKey),
        (ec.EllipticCurvePrivateKey, paramiko.ECDSAKey),
        (dsa.DSAPrivateKey, paramiko.DSSKey),
    ):
        if isinstance(crypto_key, crypto_type):
            return paramiko_type(key=crypto_key)
    raise ValueError(f"Unsupported SSH private key algorithm: {type(crypto_key).__name__}")


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
    pkey = (
        _parse_private_key(config.ssh_private_key, config.ssh_private_key_passphrase)
        if config.ssh_private_key else None
    )

    tunnel = SSHTunnelForwarder(
        (config.ssh_host, config.ssh_port),
        ssh_username=config.ssh_username,
        ssh_password=None if pkey else config.ssh_password,
        ssh_pkey=pkey,
        remote_bind_address=(remote_host, remote_port),
    )
    tunnel.start()
    return tunnel

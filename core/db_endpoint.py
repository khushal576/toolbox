"""
core/db_endpoint.py

Turns a Vault entry into a live, long-lived database connection. Shared by
Data Syncer and Schema Copy (moved here from data-syncer/connections.py when
the second consumer appeared — see ../CLAUDE.md "Shared connectors"). These
tools have NO manual connection form on purpose (owner's choice: every
connection is saved once in the Vault and reused everywhere) — a project
stores only the Vault entry's id (+ its name, for display and as a
fallback if the entry is deleted and recreated), never a copy of the
credentials, so rotating a password in the Vault just works.

`Endpoint` is deliberately NOT pooled (unlike sql-studio/schema-map): a
run holds exactly one connection per side for the whole run, and
needs to be able to drop and re-open it after a network failure
(`reconnect()`), keeping the SSH tunnel (if the Vault entry has one) alive
across reconnects. Built on the same shared primitives the pooled tools
use (core.postgres_conn), so SSH tunnelling and error scrubbing behave
identically. After open(), `.host`/`.port` are where a client (psycopg, or a
`pg_dump`/`psql` subprocess) must connect — the local tunnel end if a tunnel
is in use — so non-psycopg callers get tunnelling for free.
"""

from __future__ import annotations

from typing import Any, Optional

import psycopg
from psycopg.conninfo import make_conninfo

from core import vault
from core.postgres_conn import (
    SSHTunnelForwarder, build_conninfo, open_ssh_tunnel, scrub_password, ssh_tunnel_from_dict,
)

CONNECTION_KIND = "postgres_connection"  # the one kind the Vault's "Add connection" form saves
# Library scope (roadmap B7): whoever calls this module can only ever read database connections through it.
_VAULT = vault.ScopedVault(vault.Scope("db-endpoint", read=[CONNECTION_KIND]))


class ConnectionError_(RuntimeError):
    """Raised with an already-scrubbed message — safe to show in a log/UI."""


def list_vault_connections() -> list[dict[str, Any]]:
    """Metadata only (id/name/kind/timestamps) — never decrypted data. The
    syncer UI picks from this list; there is no 'type a host' fallback."""
    return [s for s in _VAULT.list_secrets(CONNECTION_KIND)]


def resolve(conn_id: str, conn_name: Optional[str] = None) -> dict[str, Any]:
    """Decrypt the Vault entry for *conn_id*. If it no longer exists, fall
    back to looking it up by *conn_name* (covers delete-and-recreate under
    the same name). Raises ConnectionError_ if neither resolves."""
    try:
        return _VAULT.get_secret(conn_id)
    except (vault.SecretNotFound, vault.ScopeError):
        pass
    if conn_name:
        try:
            return _VAULT.get_secret_by_name(conn_name, CONNECTION_KIND)
        except vault.SecretNotFound:
            pass
    raise ConnectionError_(
        f"Vault connection '{conn_name or conn_id}' not found — it was deleted or renamed. "
        "Re-save it in the Vault and re-select it on this project."
    )


def describe(data: dict[str, Any]) -> str:
    """Human-readable target for confirm dialogs/logs. Never the password."""
    via = f" via SSH {data['ssh_tunnel']['ssh_host']}" if data.get("ssh_tunnel") else ""
    return f"{data.get('username')}@{data.get('host')}:{data.get('port')}/{data.get('database')}{via}"


class Endpoint:
    """One side (source or target) of a sync: a single psycopg connection,
    optionally through an SSH tunnel, that can be re-opened in place."""

    def __init__(self, data: dict[str, Any], *, read_only: bool, label: str):
        db_type = (data.get("db_type") or "postgres").lower()
        if db_type != "postgres":
            raise ConnectionError_(
                f"{label}: database type '{db_type}' is not supported by the syncer yet (Postgres only)."
            )
        self.data = data
        self.read_only = read_only
        self.label = label
        self.conn: Optional[psycopg.Connection] = None
        self.host: Optional[str] = None  # where clients connect (tunnel-aware); set by open()
        self.port: Optional[int] = None
        self._tunnel: Optional[SSHTunnelForwarder] = None

    def open(self) -> psycopg.Connection:
        d = self.data
        host, port = d["host"], int(d.get("port") or 5432)
        try:
            tunnel_cfg = ssh_tunnel_from_dict(d.get("ssh_tunnel"))
            if tunnel_cfg is not None and self._tunnel is None:
                self._tunnel = open_ssh_tunnel(tunnel_cfg, remote_host=host, remote_port=port)
            if self._tunnel is not None:
                host, port = "127.0.0.1", self._tunnel.local_bind_port
            self.host, self.port = host, port
            conninfo = build_conninfo(host, port, d["database"], d["username"], d["password"])
            # client_encoding pinned on BOTH sides: COPY streams raw bytes in each
            # connection's client encoding, so a mismatch would corrupt text silently.
            # TCP keepalives: a sync can sit on one connection for hours; keep NAT/firewalls honest.
            conninfo = make_conninfo(
                conninfo, client_encoding="UTF8", application_name="toolbox-data-syncer",
                keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
            )
            self.conn = psycopg.connect(conninfo, connect_timeout=15)
            if self.read_only:
                self.conn.read_only = True  # source is never written to — enforced by the server
            return self.conn
        except Exception as exc:  # noqa: BLE001 — scrub then re-raise as one clean type
            self.close()
            raise ConnectionError_(f"{self.label}: {scrub_password(str(exc))}") from exc

    def reconnect(self) -> psycopg.Connection:
        """Drop the current connection (it may be half-dead) and open a new
        one. The SSH tunnel, if any, is kept unless it died."""
        self._close_conn()
        if self._tunnel is not None and not self._tunnel.is_active:
            try:
                self._tunnel.stop()
            except Exception:  # noqa: BLE001
                pass
            self._tunnel = None
        return self.open()

    def _close_conn(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
            self.conn = None

    def close(self) -> None:
        self._close_conn()
        if self._tunnel is not None:
            try:
                self._tunnel.stop()
            except Exception:  # noqa: BLE001
                pass
            self._tunnel = None

    def __enter__(self) -> "Endpoint":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

"""
core/pooled_postgres.py

The shared pool+reaper lifecycle, extracted out of sql-studio/db_engine.py
and schema-map/db_engine.py, which each had their own ~150-line copy of
this (ConnectionState dataclass, STATE/_reaper_task globals, the idle
reaper, status/connect/disconnect, a generic run()). Each tool still
builds its OWN instance of PooledPostgresConnection — this is deliberately
NOT a single shared pool/STATE; sql-studio and schema-map may legitimately
point at two different databases at once (see schema-map/CLAUDE.md). Only
the lifecycle *mechanics* are shared now, not the connection itself.

Built on core/postgres_conn.py's connect/verify/scrub primitives.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from psycopg_pool import ConnectionPool
from sshtunnel import SSHTunnelForwarder

from core.postgres_conn import SSHTunnelConfig, build_conninfo, open_ssh_tunnel, scrub_password, verify_connection

REAPER_INTERVAL_SECONDS = 60


@dataclass
class ConnectionState:
    host: str
    port: int
    database: str
    username: str
    pool: ConnectionPool
    connected_at: float
    last_used_at: float
    ssh_tunnel: Optional[SSHTunnelForwarder] = None


class PooledPostgresConnection:
    """One tool's live Postgres connection: credential pre-validation,
    a small connection pool, and an idle reaper that closes it if a
    browser tab is forgotten. Instantiate one per tool (not shared).
    """

    def __init__(
        self,
        *,
        pool_max_size: int,
        idle_timeout_seconds: int = 20 * 60,
        statement_timeout_ms: int | None = None,
        connect_error_cls: type[Exception] = Exception,
    ) -> None:
        self._pool_max_size = pool_max_size
        self._idle_timeout_seconds = idle_timeout_seconds
        self._statement_timeout_ms = statement_timeout_ms
        self._connect_error_cls = connect_error_cls
        self.state: Optional[ConnectionState] = None
        self._reaper_task: Optional[asyncio.Task] = None

    def _touch(self) -> None:
        if self.state is not None:
            self.state.last_used_at = time.monotonic()

    async def _reaper_loop(self) -> None:
        """Closes an idle pool so a forgotten browser tab doesn't hold live
        connections open against the target database indefinitely. Runs
        for the lifetime of the process once started."""
        while True:
            await asyncio.sleep(REAPER_INTERVAL_SECONDS)
            if self.state is not None and (time.monotonic() - self.state.last_used_at) > self._idle_timeout_seconds:
                self.disconnect()

    def _ensure_reaper_started(self) -> None:
        # Started lazily on first successful connect, not via a FastAPI
        # lifespan hook — main.py mounts each tool's app via app.mount(...),
        # and Starlette does not forward lifespan events into mounted
        # sub-apps, so a lifespan handler would silently never fire.
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.get_event_loop().create_task(self._reaper_loop())

    def status(self) -> dict[str, Any]:
        if self.state is None:
            return {"connected": False}
        return {
            "connected": True,
            "host": self.state.host,
            "port": self.state.port,
            "database": self.state.database,
            "username": self.state.username,
            "connected_at": self.state.connected_at,
            "last_used_at": self.state.last_used_at,
            "via_ssh_tunnel": self.state.ssh_tunnel is not None,
        }

    def _connect_sync(
        self, host: str, port: int, database: str, username: str, password: str,
        ssh_tunnel: Optional[SSHTunnelConfig],
    ) -> tuple[ConnectionPool, Optional[SSHTunnelForwarder]]:
        tunnel: Optional[SSHTunnelForwarder] = None
        connect_host, connect_port = host, port
        if ssh_tunnel is not None:
            # Open the tunnel first, then connect through its local
            # forwarded port instead of the real host/port — the one
            # thing build_conninfo() itself needs to know nothing about.
            tunnel = open_ssh_tunnel(ssh_tunnel, remote_host=host, remote_port=port)
            connect_host, connect_port = "127.0.0.1", tunnel.local_bind_port
        try:
            conninfo = build_conninfo(
                connect_host, connect_port, database, username, password,
                statement_timeout_ms=self._statement_timeout_ms,
            )
            verify_connection(conninfo, connect_timeout=10)
            pool = ConnectionPool(
                conninfo, min_size=0, max_size=self._pool_max_size,
                max_idle=300, max_lifetime=1800, timeout=10, open=False,
            )
            pool.open(wait=True, timeout=10)
        except Exception:
            if tunnel is not None:
                tunnel.stop()  # don't leak the tunnel if the DB connection itself fails
            raise
        return pool, tunnel

    async def connect(
        self, host: str, port: int, database: str, username: str, password: str,
        *, ssh_tunnel: Optional[SSHTunnelConfig] = None,
    ) -> dict[str, Any]:
        self.disconnect()  # only one live connection at a time — replacing an existing one closes it first
        try:
            pool, tunnel = await asyncio.to_thread(
                self._connect_sync, host, port, database, username, password, ssh_tunnel,
            )
        except Exception as exc:  # noqa: BLE001 - psycopg/libpq/sshtunnel raise several distinct exception types here
            raise self._connect_error_cls(scrub_password(str(exc))) from exc
        now = time.monotonic()
        self.state = ConnectionState(
            host=host, port=port, database=database, username=username,
            pool=pool, connected_at=now, last_used_at=now, ssh_tunnel=tunnel,
        )
        self._ensure_reaper_started()
        return self.status()

    def disconnect(self) -> dict[str, Any]:
        if self.state is not None:
            try:
                self.state.pool.close(timeout=5)
            except Exception:  # noqa: BLE001 - best-effort close; must not block clearing state
                pass
            if self.state.ssh_tunnel is not None:
                try:
                    self.state.ssh_tunnel.stop()
                except Exception:  # noqa: BLE001 - best-effort close; must not block clearing state
                    pass
            self.state = None
        return {"connected": False}

    async def run(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Runs fn(conn, *args) against a pooled connection in a worker
        thread. fn is a plain sync function taking a psycopg connection
        first — this handles the pool checkout, the to_thread wrapping
        (blocking psycopg calls directly inside `async def` would freeze
        the whole process under --workers 1), and turning any failure
        into this tool's own connect_error_cls, scrubbed."""
        if self.state is None:
            raise self._connect_error_cls("Not connected — connect to a database first.")

        def _sync() -> Any:
            with self.state.pool.connection() as conn:
                return fn(conn, *args)

        try:
            result = await asyncio.to_thread(_sync)
        except Exception as exc:  # noqa: BLE001
            raise self._connect_error_cls(scrub_password(str(exc))) from exc
        self._touch()
        return result

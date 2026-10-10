"""
core/pooled_db.py

The shared pool+reaper lifecycle, generalized over core/db/dialect.py's
Dialect interface so the same mechanics (idle reaper, credential
pre-validation before building a pool, a generic run()) work for
Postgres, SQL Server, and Oracle alike — not just Postgres.

This is core/pooled_postgres.py's PooledPostgresConnection with every
psycopg-specific call (building the pool, checking out a connection,
closing the pool) replaced by a call into a Dialect instance.
core/pooled_postgres.py now just subclasses this with PostgresDialect
baked in as the default, so schema-map's existing
`PooledPostgresConnection(...)` construction and `_POOL.run(...)`/
`.connect(...)`/`.disconnect(...)`/`.status()` calls keep working
unchanged — it never needs to know this generalization happened.

A tool whose live connection can be any one of several database types
at different times (SQL Studio) constructs `PooledDbConnection` with NO
default dialect and passes `dialect=...` explicitly to each connect()
call instead — see sql-studio/db_engine.py. A tool that only ever
talks to one kind of database (schema-map) gets a fixed default dialect
baked in via a subclass, same as PooledPostgresConnection.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from sshtunnel import SSHTunnelForwarder

from core.db.dialect import Dialect
from core.postgres_conn import SSHTunnelConfig, open_ssh_tunnel, scrub_password

REAPER_INTERVAL_SECONDS = 60


@dataclass
class ConnectionState:
    host: str
    port: int
    database: str
    username: str
    pool: Any
    dialect: Dialect
    connected_at: float
    last_used_at: float
    ssh_tunnel: Optional[SSHTunnelForwarder] = None


class PooledDbConnection:
    """One tool's live database connection: credential pre-validation, a
    small connection pool, and an idle reaper that closes it if a
    browser tab is forgotten. Instantiate one per tool (not shared).
    """

    def __init__(
        self,
        dialect: Optional[Dialect] = None,
        *,
        pool_max_size: int,
        idle_timeout_seconds: int = 20 * 60,
        statement_timeout_ms: Optional[int] = None,
        connect_error_cls: type[Exception] = Exception,
    ) -> None:
        self._default_dialect = dialect
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
            "db_type": self.state.dialect.name,
            "host": self.state.host,
            "port": self.state.port,
            "database": self.state.database,
            "username": self.state.username,
            "connected_at": self.state.connected_at,
            "last_used_at": self.state.last_used_at,
            "via_ssh_tunnel": self.state.ssh_tunnel is not None,
        }

    def current_dialect(self) -> Optional[Dialect]:
        return self.state.dialect if self.state is not None else None

    def _connect_sync(
        self, dialect: Dialect, host: str, port: int, database: str, username: str, password: str,
        ssh_tunnel: Optional[SSHTunnelConfig],
    ) -> tuple[Any, Optional[SSHTunnelForwarder]]:
        tunnel: Optional[SSHTunnelForwarder] = None
        connect_host, connect_port = host, port
        if ssh_tunnel is not None:
            # Open the tunnel first, then connect through its local
            # forwarded port instead of the real host/port — generic
            # across every dialect, same as before this generalization.
            tunnel = open_ssh_tunnel(ssh_tunnel, remote_host=host, remote_port=port)
            connect_host, connect_port = "127.0.0.1", tunnel.local_bind_port
        try:
            conninfo = dialect.build_conninfo(
                connect_host, connect_port, database, username, password,
                statement_timeout_ms=self._statement_timeout_ms,
            )
            dialect.verify_connection(conninfo, connect_timeout=10)
            pool = dialect.open_pool(conninfo, max_size=self._pool_max_size, timeout=10)
        except Exception:
            if tunnel is not None:
                tunnel.stop()  # don't leak the tunnel if the DB connection itself fails
            raise
        return pool, tunnel

    async def connect(
        self, host: str, port: int, database: str, username: str, password: str,
        *, dialect: Optional[Dialect] = None, ssh_tunnel: Optional[SSHTunnelConfig] = None,
    ) -> dict[str, Any]:
        self.disconnect()  # only one live connection at a time — replacing an existing one closes it first
        resolved_dialect = dialect or self._default_dialect
        if resolved_dialect is None:
            raise self._connect_error_cls("No database dialect specified.")
        try:
            pool, tunnel = await asyncio.to_thread(
                self._connect_sync, resolved_dialect, host, port, database, username, password, ssh_tunnel,
            )
        except Exception as exc:  # noqa: BLE001 - each driver raises its own distinct exception types here
            raise self._connect_error_cls(scrub_password(str(exc))) from exc
        now = time.monotonic()
        self.state = ConnectionState(
            host=host, port=port, database=database, username=username,
            pool=pool, dialect=resolved_dialect, connected_at=now, last_used_at=now, ssh_tunnel=tunnel,
        )
        self._ensure_reaper_started()
        return self.status()

    def disconnect(self) -> dict[str, Any]:
        if self.state is not None:
            try:
                self.state.dialect.close_pool(self.state.pool, timeout=5)
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
        thread. fn is a plain sync function taking a raw driver connection
        first — this handles the pool checkout, the to_thread wrapping
        (blocking driver calls directly inside `async def` would freeze
        the whole process under --workers 1), and turning any failure
        into this tool's own connect_error_cls, scrubbed."""
        if self.state is None:
            raise self._connect_error_cls("Not connected — connect to a database first.")
        state = self.state

        def _sync() -> Any:
            with state.dialect.checkout(state.pool) as conn:
                return fn(conn, *args)

        try:
            result = await asyncio.to_thread(_sync)
        except Exception as exc:  # noqa: BLE001
            raise self._connect_error_cls(scrub_password(str(exc))) from exc
        self._touch()
        return result

"""
Postgres for Toolbox's own durable records (roadmap B1; tools migrate in B6/B7).

One pool per process, created on first use (min_size=0: no idle connections held). Each tool keeps its tables in
its own schema (`ensure_schema("data_syncer")`), never in `public`, so tools can't collide.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from typing import Iterator

from core.state.config import load, require

_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_lock = threading.Lock()
_pool = None


def pool():
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                cfg = load()
                url = require(cfg.database_url, "TOOLBOX_DATABASE_URL")  # clear error before importing the driver
                from psycopg_pool import ConnectionPool

                _pool = ConnectionPool(url, min_size=0,
                                       max_size=cfg.db_pool_max, max_idle=300, timeout=10, open=True,
                                       kwargs={"autocommit": True}, name="toolbox-state")
    return _pool


@contextmanager
def connection() -> Iterator:
    """Autocommit connection from the pool. Use `with conn.transaction():` for multi-statement work."""
    with pool().connection() as conn:
        yield conn


def ensure_schema(name: str) -> str:
    """Create the tool's schema if missing and return its name (lowercase letters, digits, '_')."""
    if not _SCHEMA_RE.match(name):
        raise ValueError(f"invalid schema name {name!r}")
    with connection() as conn:
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{name}"')
    return name


def health() -> dict:
    with connection() as conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        db = conn.execute("SELECT current_database(), current_user").fetchone()
    return {"version": version, "database": db[0], "user": db[1]}


def close() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None

"""
core/pooled_postgres.py

PooledPostgresConnection is now a thin subclass of core/pooled_db.py's
PooledDbConnection with PostgresDialect baked in as the fixed default —
this file exists purely for backward compatibility so schema-map/db_engine.py
(which only ever talks to Postgres and has no reason to think about
"which dialect") keeps constructing and calling this exact class with
zero changes. See core/pooled_db.py's module docstring for the
generalization and core/db/dialect_postgres.py for what moved where.

ConnectionState/REAPER_INTERVAL_SECONDS are re-exported here too, in
case anything imports them from this module path directly.
"""

from __future__ import annotations

from core.db.dialect_postgres import PostgresDialect
from core.pooled_db import ConnectionState, PooledDbConnection, REAPER_INTERVAL_SECONDS  # noqa: F401


class PooledPostgresConnection(PooledDbConnection):
    def __init__(self, **kwargs) -> None:
        super().__init__(PostgresDialect(), **kwargs)

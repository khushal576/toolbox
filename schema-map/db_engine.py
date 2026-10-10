"""
schema-map/db_engine.py

Live Postgres connection for Schema Map — same idiom as
sql-studio/db_engine.py (own pool, credential pre-validation before
opening it, idle reaper, password never persisted), but a genuinely
separate instance, not shared with SQL Studio's own connection. Schema
Map and SQL Studio might reasonably be pointed at two different
databases at the same time — see the plan this was built from for the
full reasoning.

Pool is smaller (max_size=2) than SQL Studio's (3): this tool only ever
runs a handful of introspection queries per fetch, never sustained query
traffic.

The pool+reaper lifecycle itself is shared with sql-studio/db_engine.py
via core.pooled_postgres.PooledPostgresConnection — each tool builds its
own instance below; only the mechanics are shared, not the connection.

Unlike sql-studio/db_engine.py, there's no query_guard here and no
concept of running arbitrary user-typed SQL — Schema Map only ever runs
its own fixed introspection queries (schema-map/introspection_postgres.py),
so the one thing this module needs beyond connect/disconnect/status is
`run()`, a generic "execute this plain function against a pooled
connection" helper — now PooledPostgresConnection's own `run()`, exposed
here under the same name for server.py's call sites.
"""

from __future__ import annotations

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core.pooled_postgres import PooledPostgresConnection
except ImportError:  # standalone dev run from inside this folder: core/ is ../../core
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from core.pooled_postgres import PooledPostgresConnection


class ConnectError(Exception):
    pass


_POOL = PooledPostgresConnection(
    pool_max_size=2, idle_timeout_seconds=20 * 60, connect_error_cls=ConnectError,
)

connect = _POOL.connect
disconnect = _POOL.disconnect
status = _POOL.status
run = _POOL.run

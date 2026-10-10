"""
sql-studio/db_engine.py

Live Postgres connection state for SQL Studio's Run feature. See
sql-studio/CLAUDE.md for the full design writeup — the short version:

**One global connection, not a per-cookie session dict.** Every other
stateful tool in this repo (df-studio) keys its state per browser-tab
cookie because each tab legitimately owns independent data — Tab A's
uploaded CSV has nothing to do with Tab B's. SQL Studio's live connection
is different: the owner's own framing was "connect to a single database
at a time" with "a pool of 3 connections" — a global toggle, not N
independent per-tab resources. Keying this the df-studio way would let
every open tab silently open its own 3-connection pool (3 tabs = up to 9
live connections against the target database), which breaks the "pool of
3" requirement outright. One module-level pool is also one thing to
bound and clean up instead of N independently-leakable ones. GET /status
naturally reports the same answer to every tab — that's the correct
behavior for "a single database at a time," not a bug.

The pool+reaper lifecycle itself (ConnectionState, idle reaper,
credential pre-validation before opening the pool) is shared with
schema-map/db_engine.py via core.pooled_postgres.PooledPostgresConnection
— each tool still builds its OWN instance (_POOL below), genuinely
separate state, not a shared connection. Only the mechanics are shared.

Every psycopg call is synchronous (psycopg's sync API, not
AsyncConnectionPool) and run via asyncio.to_thread — same idiom
df-studio/server.py already uses (and documents) for the same reason: with
--workers 1, a blocking call made directly inside `async def` freezes the
whole process's event loop for its entire duration.
"""

from __future__ import annotations

import csv
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:  # package import when mounted inside the toolbox (sql_studio.*)
    from sql_studio import query_guard
except ImportError:  # flat import when run standalone from within this folder
    import query_guard

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core.db.dialect import Dialect
    from core.db.registry import get_dialect
    from core.pooled_db import PooledDbConnection
except ImportError:  # standalone dev run from inside this folder: core/ is ../../core
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from core.db.dialect import Dialect
    from core.db.registry import get_dialect
    from core.pooled_db import PooledDbConnection

ROW_CAP = query_guard.ROW_CAP

STATEMENT_TIMEOUT_MS = 15_000
# Every connection this pool ever opens gets this session-level default —
# closes the real gap the LIMIT-wrap alone leaves open: LIMIT 500 bounds
# ROWS RETURNED, not query COST. A GROUP BY/window query over a huge table
# can still take a long time computing the aggregation before the outer
# LIMIT ever trims the output (see sql-studio/CLAUDE.md's "500-row cap is
# a LIMIT-wrap, not a cost limiter"). Without this, that query just hangs
# the connection — with only 3 in the pool, three such queries exhausts it
# entirely. Postgres raises QueryCanceled ("canceling statement due to
# statement timeout") when it fires, surfaced to the UI like any other
# query error.


class ConnectError(Exception):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]


_POOL = PooledDbConnection(
    pool_max_size=3, idle_timeout_seconds=20 * 60,
    statement_timeout_ms=STATEMENT_TIMEOUT_MS, connect_error_cls=ConnectError,
)
# No default dialect (unlike schema-map's PooledPostgresConnection) —
# this tool can connect to any ONE of Postgres/SQL Server/Oracle at a
# time, chosen per connect() call, not fixed for the tool's lifetime.

status = _POOL.status
current_dialect = _POOL.current_dialect


async def connect(
    host: str, port: int, database: str, username: str, password: str,
    *, db_type: str = "postgres", ssh_tunnel=None,
) -> dict[str, Any]:
    try:
        dialect = get_dialect(db_type)
    except ValueError as exc:
        raise ConnectError(str(exc)) from exc
    return await _POOL.connect(host, port, database, username, password, dialect=dialect, ssh_tunnel=ssh_tunnel)

# last_result is SQL Studio's own concern (what /export/csv and
# /export/json read), not part of the shared pool lifecycle — cleared
# explicitly on disconnect below so a stale cached result can never
# outlive the connection it came from.
_last_result: Optional[QueryResult] = None


def disconnect() -> dict[str, Any]:
    global _last_result
    _last_result = None
    return _POOL.disconnect()


def _decode_lob_cell(value: Any) -> Any:
    """Oracle's driver hands back a CLOB/BLOB column as an `oracledb.LOB`
    object (confirmed directly — JSON_OBJECTAGG's output in
    dialect_oracle.py's schema_fetch_query is one real example), which
    FastAPI's JSONResponse can't serialize at all (it isn't a str/int/
    dict/list) — every row-returning query, not just that one, needs
    this or Run breaks outright the first time it touches a LOB column.
    Detected generically via a `.read` attribute (any DB-API LOB-like
    object), not by importing oracledb here — Postgres/SQL Server rows
    never have this attribute, so this is a no-op for them."""
    if hasattr(value, "read"):
        read = value.read()
        return read.decode("utf-8", errors="replace") if isinstance(read, bytes) else read
    return value


def _execute_sync(conn, classification: "query_guard.Classification") -> dict[str, Any]:
    global _last_result
    with conn.cursor() as cur:
        cur.execute(classification.executable_sql)
        if cur.description is not None:
            # Index 0, not `.name` — portable across DB-API cursors.
            # psycopg's description entries support `.name` as a
            # convenience, but pytds's are plain tuples and don't
            # (confirmed against a real SQL Server) — `[0]` is the one
            # access pattern the DB-API spec actually guarantees.
            columns = [d[0] for d in cur.description]
            rows = [[_decode_lob_cell(v) for v in r] for r in cur.fetchall()]
            conn.commit()
            _last_result = QueryResult(columns=columns, rows=rows)
            return {
                "kind": "rows",
                "columns": columns,
                "rows": rows,
                "row_count_returned": len(rows),
                # A heuristic, not an exact "more rows exist" signal: if
                # Postgres handed back exactly ROW_CAP rows, the outer
                # LIMIT most likely trimmed a larger result. The rare
                # case where the true result is exactly ROW_CAP rows
                # looks identical and is harmlessly mislabeled capped.
                "capped": len(rows) >= ROW_CAP,
            }
        rowcount = cur.rowcount
        conn.commit()
        _last_result = None
        if rowcount is not None and rowcount >= 0 and classification.keyword in ("INSERT", "UPDATE", "DELETE"):
            noun = "row" if rowcount == 1 else "rows"
            message = f"{classification.keyword} OK — {rowcount} {noun} affected."
        else:
            message = f"{classification.keyword} OK."
        return {"kind": "status", "message": message}


async def execute(classification: "query_guard.Classification") -> dict[str, Any]:
    start = time.monotonic()
    result = await _POOL.run(_execute_sync, classification)
    result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
    return result


def last_result() -> Optional[QueryResult]:
    return _last_result


EXPORT_BATCH_SIZE = 5_000
# "Export full result to Vault" deliberately does NOT go through
# query_guard's executable_sql (which wraps every row-returning statement
# in `LIMIT 500` for ordinary Run) — the entire point of this action is
# the real, untruncated result. It still re-validates the statement
# itself (single statement, not destructive, returns rows) before
# running anything. Streams via a server-side (named) cursor + fetchmany
# in batches instead of cur.fetchall() — bounded memory regardless of
# how many rows the query returns, same reasoning as duck-lab's own
# "never materialize the whole thing in Python" design.


def _export_sync(conn, dialect: Dialect, statement: str, dest_path: Path) -> dict[str, Any]:
    cur = dialect.open_export_cursor(conn, f"export_{uuid.uuid4().hex}", batch_size=EXPORT_BATCH_SIZE)
    with cur:
        cur.execute(statement)
        columns = [d[0] for d in cur.description]
        row_count = 0
        with dest_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            while True:
                batch = cur.fetchmany(EXPORT_BATCH_SIZE)
                if not batch:
                    break
                batch = [[_decode_lob_cell(v) for v in row] for row in batch]
                writer.writerows(batch)
                row_count += len(batch)
    conn.commit()
    return {"columns": columns, "row_count": row_count}


async def export_to_file(sql: str, dest_path: Path) -> dict[str, Any]:
    """Validate *sql* is exactly one, non-destructive, rows-returning
    statement, then stream its REAL full result (no row cap) to
    dest_path as CSV. Raises ConnectError for anything that fails
    validation or the export itself."""
    dialect = current_dialect()
    if dialect is None:
        raise ConnectError("Not connected — connect to a database first.")
    statements = query_guard.split_statements(sql)
    if not statements:
        raise ConnectError("Nothing to export — the query is empty.")
    if len(statements) > 1:
        raise ConnectError("Export works on exactly one statement at a time.")
    statement = statements[0]
    classification = query_guard.classify(statement, dialect)
    if classification.is_destructive:
        raise ConnectError(
            f"Refusing to export a {classification.keyword} statement — export only supports read queries."
        )
    if not classification.returns_rows:
        raise ConnectError("This statement doesn't return rows — nothing to export.")
    return await _POOL.run(_export_sync, dialect, statement, dest_path)

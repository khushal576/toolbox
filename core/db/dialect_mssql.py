"""
core/db/dialect_mssql.py

SQL Server's Dialect implementation, using python-tds (import name
`pytds`) — a pure-Python TDS protocol implementation with no
ODBC/FreeTDS native install needed, chosen specifically to avoid
repeating this repo's documented duckdb-wheel pain (see
../../CLAUDE.md's "Shared connectors" / sql-studio/CLAUDE.md). Confirmed
against a real throwaway mssql/server container before writing any of
this: connect+query, a bad-password failure (fails in ~0.01s, no hang),
fetchmany() streaming 7000 rows in 500-row batches with no named cursor
needed, pytds's own `timeout=` kwarg as a REAL working per-statement
timeout (cut a deliberate 5s WAITFOR DELAY off at ~1s) — so, unlike the
plan's open question, no pyodbc fallback is needed here.

pytds has no built-in connection pool (unlike psycopg_pool/oracledb) —
_MssqlPool below is a small hand-rolled one, entirely contained in this
file, so core/pooled_db.py never needs to know the underlying driver
lacks native pooling.
"""

from __future__ import annotations

import queue
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Union

import pytds


def _literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# Same list ui/index.html's SCHEMA_LIST_QUERIES.mssql uses — every
# built-in schema that exists by default in any SQL Server database,
# none of which are ever a real user's own objects.
_MSSQL_SYSTEM_SCHEMAS = (
    "sys", "INFORMATION_SCHEMA", "guest", "db_accessadmin", "db_backupoperator",
    "db_datareader", "db_datawriter", "db_ddladmin", "db_denydatareader",
    "db_denydatawriter", "db_owner", "db_securityadmin",
)
_MSSQL_SYSTEM_SCHEMA_FILTER = "s.name NOT IN (" + ", ".join(_literal(s) for s in _MSSQL_SYSTEM_SCHEMAS) + ")"


class _MssqlPool:
    """Lazily-created connections up to max_size, released back to an
    internal queue on checkout release. A cheap `SELECT 1` health check
    on checkout replaces a dead connection instead of handing out one
    that will fail the caller's real query."""

    def __init__(self, conninfo: dict, max_size: int, login_timeout: int) -> None:
        self._conninfo = conninfo
        self._max_size = max_size
        self._login_timeout = login_timeout
        self._idle: "queue.Queue[Any]" = queue.Queue()
        self._lock = threading.Lock()
        self._created = 0

    def _new_connection(self) -> Any:
        return pytds.connect(login_timeout=self._login_timeout, **self._conninfo)

    def acquire(self) -> Any:
        try:
            conn = self._idle.get_nowait()
            try:
                conn.cursor().execute("SELECT 1")
                return conn
            except Exception:  # noqa: BLE001 - dead connection, replace it
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
        except queue.Empty:
            pass
        with self._lock:
            if self._created < self._max_size:
                self._created += 1
                return self._new_connection()
        # Pool exhausted and nothing idle — block for one to free up
        # rather than exceeding max_size (matches psycopg_pool's own
        # bounded-size contract).
        return self._idle.get(timeout=self._login_timeout)

    def release(self, conn: Any) -> None:
        self._idle.put(conn)

    def close_all(self) -> None:
        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                break
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass


def _has_trailing_order_by(statement: str) -> bool:
    """True if `statement` has a top-level (depth-0, outside strings/
    comments) trailing `ORDER BY` clause.

    This answers a narrower question than it looks like it should: an
    EARLIER version of wrap_row_cap() wrapped the statement in an outer
    `SELECT TOP {n} * FROM (<statement>) AS _sq` derived table, which
    needed this to detect-and-relocate a trailing ORDER BY (T-SQL
    forbids a bare one inside a derived table unless TOP/OFFSET/FOR XML
    is present in THAT inner query too). That whole approach turned out
    to be the wrong design, found by actually testing it: SQL Server
    also rejects a `WITH ...` (CTE) statement wrapped the same way —
    confirmed against a real engine ("Incorrect syntax near the keyword
    'WITH'") — which `core/db/dialect_mssql.py`'s own `schema_fetch_query()`
    ALWAYS produces, so the old wrap broke Fetch Schema outright for
    this dialect. wrap_row_cap() now appends a trailing `OFFSET 0 ROWS
    FETCH NEXT {n} ROWS ONLY` instead (needs this function only to know
    whether a dummy `ORDER BY (SELECT NULL)` must be added first, since
    T-SQL's FETCH clause requires an ORDER BY to be legal at all) — no
    wrapping, no CTE problem, confirmed working for a plain SELECT, a
    SELECT with its own ORDER BY, AND a multi-CTE chain, all against a
    real SQL Server.

    Deliberately a small, scoped scanner — not a reuse of
    sql-studio/query_guard.py's tokenizer (core/ doesn't import from a
    tool folder) and not a full parser, same "best-effort, not a real
    parser" spirit that tokenizer itself documents. Tracks single-quote
    strings ('' escaping), --/line comments, /* */ block comments, and
    paren depth — good enough for the well-formed queries this feature
    targets; an ORDER BY keyword inside a string very close to the
    statement's end is the one known edge case this doesn't handle."""
    depth = 0
    i = 0
    n = len(statement)
    while i < n:
        ch = statement[i]
        two = statement[i:i + 2]
        if ch == "'":
            j = i + 1
            while j < n:
                if statement[j] == "'" and j + 1 < n and statement[j + 1] == "'":
                    j += 2
                    continue
                if statement[j] == "'":
                    j += 1
                    break
                j += 1
            i = j
            continue
        if two == "--":
            j = statement.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if two == "/*":
            j = statement.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if depth == 0 and statement[i:i + 8].upper() == "ORDER BY" and (i == 0 or not statement[i - 1].isalnum()):
            return True
        i += 1
    return False


class MssqlDialect:
    name = "mssql"
    default_port = 1433
    returning_pattern = re.compile(r"\bOUTPUT\b", re.IGNORECASE)

    def build_conninfo(
        self, host: str, port: int, database: str, username: str, password: str,
        *, statement_timeout_ms: Optional[int] = None,
    ) -> dict:
        conninfo: dict = {
            "server": host, "port": port, "database": database,
            "user": username, "password": password,
        }
        if statement_timeout_ms:
            conninfo["timeout"] = max(1, statement_timeout_ms // 1000)
        return conninfo

    def verify_connection(self, conninfo: dict, connect_timeout: int = 10) -> None:
        with pytds.connect(login_timeout=connect_timeout, **conninfo) as conn:
            conn.cursor().execute("SELECT 1")

    def open_pool(self, conninfo: dict, *, max_size: int, timeout: int = 10) -> _MssqlPool:
        return _MssqlPool(conninfo, max_size, login_timeout=timeout)

    @contextmanager
    def checkout(self, pool: _MssqlPool) -> Iterator[Any]:
        conn = pool.acquire()
        try:
            yield conn
        finally:
            pool.release(conn)

    def close_pool(self, pool: _MssqlPool, timeout: int = 5) -> None:
        pool.close_all()

    def wrap_row_cap(self, statement: str, n: int) -> str:
        if _has_trailing_order_by(statement):
            return f"{statement} OFFSET 0 ROWS FETCH NEXT {n} ROWS ONLY"
        # FETCH requires an ORDER BY to be present at all — `(SELECT
        # NULL)` is a real, commonly-used T-SQL idiom for "order by
        # nothing in particular, I just need FETCH to be legal."
        return f"{statement} ORDER BY (SELECT NULL) OFFSET 0 ROWS FETCH NEXT {n} ROWS ONLY"

    def wrap_dml_returning_cap(self, statement: str, n: int) -> Optional[str]:
        # Confirmed against a real SQL Server: wrapping an OUTPUT-bearing
        # DML statement inside the SELECT-cap pattern fails outright
        # ("Incorrect syntax near 'OUTPUT'") — no clean cap exists here,
        # same category of gap as Oracle's RETURNING INTO.
        return None

    def open_export_cursor(self, conn: Any, name_hint: str, batch_size: int = 5000) -> Any:
        cur = conn.cursor()
        cur.arraysize = batch_size
        return cur

    def schema_fetch_query(self, schemas: Union[str, list[str]]) -> str:
        # Uses sys.columns/sys.tables/sys.schemas/sys.types (real
        # catalogs, not INFORMATION_SCHEMA) for full type-name fidelity,
        # matching the Postgres dialect's own pg_catalog-based choice.
        # Manual STRING_AGG + JSON-string construction because this
        # image's SQL Server has no built-in "aggregate into one JSON
        # object" function (STRING_AGG is 2017+; JSON_OBJECTAGG isn't
        # available until SQL Server 2025) — produces a single TEXT
        # column containing JSON, not a native JSON type (unlike
        # Postgres's json_object_agg), so the consumer must JSON.parse
        # it. Verify against a real SQL Server with real tables before
        # trusting this blindly — same discipline this repo already
        # applies to every Postgres SHOW_COMMANDS/schema-fetch query.
        if schemas == "all":
            filter_sql = _MSSQL_SYSTEM_SCHEMA_FILTER
        else:
            names = ", ".join(f"'{s}'" for s in schemas)
            filter_sql = f"s.name IN ({names})"
        return f"""
WITH cols AS (
  SELECT s.name AS schema_name, tb.name AS table_name, c.name AS column_name,
         ty.name AS data_type, c.column_id
  FROM sys.columns c
  JOIN sys.tables tb ON tb.object_id = c.object_id
  JOIN sys.schemas s ON s.schema_id = tb.schema_id
  JOIN sys.types ty ON ty.user_type_id = c.user_type_id
  WHERE {filter_sql}
),
per_table AS (
  SELECT schema_name, table_name,
    '{{' + STRING_AGG(
      '"' + REPLACE(column_name, '"', '\\"') + '":"' + REPLACE(data_type, '"', '\\"') + '"', ','
    ) WITHIN GROUP (ORDER BY column_id) + '}}' AS columns_json
  FROM cols
  GROUP BY schema_name, table_name
),
disambiguated AS (
  SELECT
    CASE WHEN COUNT(*) OVER (PARTITION BY table_name) > 1
      THEN schema_name + '.' + table_name ELSE table_name END AS display_name,
    columns_json
  FROM per_table
)
SELECT '{{' + STRING_AGG(
  '"' + REPLACE(display_name, '"', '\\"') + '":' + columns_json, ','
) + '}}' AS schema_json
FROM disambiguated
"""

    # ------------------------------------------------------------------
    # Introspection SQL — ported verbatim from ui/index.html's
    # SHOW_COMMANDS mssql entries, already verified against a real
    # throwaway mssql/server container before shipping there (see
    # sql-studio/CLAUDE.md's multi-database section) — not re-derived
    # here, just given a second, headless-callable home.
    # ------------------------------------------------------------------

    def list_tables_sql(self) -> str:
        return f"""SELECT s.name AS schema_name, t.name AS table_name, c.name AS column_name, ty.name AS column_datatype
FROM sys.columns c
JOIN sys.tables t ON t.object_id = c.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE {_MSSQL_SYSTEM_SCHEMA_FILTER}
ORDER BY s.name, t.name, c.column_id"""

    def table_columns_sql(self, table_name: str) -> str:
        return f"""SELECT c.name AS column_name, ty.name AS data_type, c.is_nullable AS is_nullable
FROM sys.columns c
JOIN sys.tables t ON t.object_id = c.object_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE t.name = {_literal(table_name)}
ORDER BY c.column_id"""

    def table_definition_sql(self, table_name: str) -> str:
        return f"""SELECT 'CREATE TABLE ' + s.name + '.' + t.name + ' (' + CHAR(13) + CHAR(10) +
  STRING_AGG(
    '  ' + c.name + ' ' + ty.name +
    CASE WHEN ty.name IN ('varchar','nvarchar','char','nchar') AND c.max_length > 0
         THEN '(' + CAST(CASE WHEN ty.name IN ('nvarchar','nchar') THEN c.max_length/2 ELSE c.max_length END AS VARCHAR) + ')'
         ELSE '' END +
    CASE WHEN c.is_nullable = 0 THEN ' NOT NULL' ELSE '' END,
    ',' + CHAR(13) + CHAR(10)
  ) WITHIN GROUP (ORDER BY c.column_id) + CHAR(13) + CHAR(10) + ');' AS table_definition
FROM sys.columns c
JOIN sys.tables t ON t.object_id = c.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE t.name = {_literal(table_name)}
GROUP BY s.name, t.name"""

    def list_functions_sql(self) -> str:
        return f"""SELECT s.name AS schema_name, o.name AS function_name, o.type_desc AS function_type
FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.type IN ('FN','IF','TF') AND {_MSSQL_SYSTEM_SCHEMA_FILTER}
ORDER BY s.name, o.name"""

    def list_triggers_sql(self) -> str:
        return f"""SELECT s.name AS schema_name, t.name AS table_name, tr.name AS trigger_name, tr.is_disabled
FROM sys.triggers tr
JOIN sys.tables t ON t.object_id = tr.parent_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE {_MSSQL_SYSTEM_SCHEMA_FILTER}
ORDER BY s.name, t.name, tr.name"""

    def list_indexes_sql(self) -> str:
        return f"""SELECT s.name AS schema_name, t.name AS table_name, i.name AS index_name, i.is_unique, i.type_desc
FROM sys.indexes i
JOIN sys.tables t ON t.object_id = i.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
WHERE i.name IS NOT NULL AND {_MSSQL_SYSTEM_SCHEMA_FILTER}
ORDER BY s.name, t.name, i.name"""

    def list_foreign_keys_sql(self) -> str:
        return f"""SELECT fk.name AS fk_name, s1.name AS from_schema, t1.name AS from_table, c1.name AS from_column,
       s2.name AS to_schema, t2.name AS to_table, c2.name AS to_column
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables t1 ON t1.object_id = fk.parent_object_id
JOIN sys.schemas s1 ON s1.schema_id = t1.schema_id
JOIN sys.columns c1 ON c1.object_id = t1.object_id AND c1.column_id = fkc.parent_column_id
JOIN sys.tables t2 ON t2.object_id = fk.referenced_object_id
JOIN sys.schemas s2 ON s2.schema_id = t2.schema_id
JOIN sys.columns c2 ON c2.object_id = t2.object_id AND c2.column_id = fkc.referenced_column_id
WHERE {_MSSQL_SYSTEM_SCHEMA_FILTER.replace("s.name", "s1.name")}
ORDER BY s1.name, t1.name"""

    def list_views_sql(self) -> str:
        return f"""SELECT s.name AS schema_name, v.name AS view_name
FROM sys.views v JOIN sys.schemas s ON s.schema_id = v.schema_id
WHERE {_MSSQL_SYSTEM_SCHEMA_FILTER}
ORDER BY s.name, v.name"""

    def activity_sql(self) -> str:
        return """SELECT session_id, login_name, host_name, program_name, status
FROM sys.dm_exec_sessions WHERE is_user_process = 1
ORDER BY session_id"""

    def grants_sql(self, table_name: Optional[str] = None) -> str:
        base = """SELECT pr.name AS grantee, pe.permission_name, pe.state_desc, o.name AS object_name
FROM sys.database_permissions pe
JOIN sys.database_principals pr ON pr.principal_id = pe.grantee_principal_id
LEFT JOIN sys.objects o ON o.object_id = pe.major_id"""
        if table_name is not None:
            base += f"\nWHERE o.name = {_literal(table_name)}"
        return base + "\nORDER BY pr.name"

    def version_sql(self) -> str:
        return "SELECT @@VERSION AS version"

"""
core/db/dialect_postgres.py

Postgres's Dialect implementation — a thin wrapper around
core/postgres_conn.py's existing build_conninfo/verify_connection
primitives (unchanged, still used directly by the orchestrator's
one-shot connector too) plus the row-cap/export logic lifted verbatim
from sql-studio/query_guard.py and sql-studio/db_engine.py so this
dialect behaves identically to what SQL Studio already shipped.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Union

from psycopg_pool import ConnectionPool

from core.postgres_conn import build_conninfo, verify_connection

# Matches ui/index.html's SYS_SCHEMA_FILTER — every introspection query
# below excludes these same non-user schemas.
_SYS_SCHEMA_FILTER = (
    "n.nspname NOT IN ('pg_catalog', 'information_schema') "
    "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%'"
)


def _literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


class PostgresDialect:
    name = "postgres"
    default_port = 5432
    returning_pattern = re.compile(r"\bRETURNING\b", re.IGNORECASE)

    def build_conninfo(
        self, host: str, port: int, database: str, username: str, password: str,
        *, statement_timeout_ms: Optional[int] = None,
    ) -> str:
        return build_conninfo(
            host, port, database, username, password,
            statement_timeout_ms=statement_timeout_ms,
        )

    def verify_connection(self, conninfo: str, connect_timeout: int = 10) -> None:
        verify_connection(conninfo, connect_timeout=connect_timeout)

    def open_pool(self, conninfo: str, *, max_size: int, timeout: int = 10) -> ConnectionPool:
        pool = ConnectionPool(
            conninfo, min_size=0, max_size=max_size,
            max_idle=300, max_lifetime=1800, timeout=timeout, open=False,
        )
        pool.open(wait=True, timeout=timeout)
        return pool

    @contextmanager
    def checkout(self, pool: ConnectionPool) -> Iterator[Any]:
        with pool.connection() as conn:
            yield conn

    def close_pool(self, pool: ConnectionPool, timeout: int = 5) -> None:
        pool.close(timeout=timeout)

    def wrap_row_cap(self, statement: str, n: int) -> str:
        return f"SELECT * FROM ({statement}) AS _sq LIMIT {n}"

    def wrap_dml_returning_cap(self, statement: str, n: int) -> Optional[str]:
        return f"WITH _dml AS ({statement}) SELECT * FROM _dml LIMIT {n}"

    def open_export_cursor(self, conn: Any, name_hint: str, batch_size: int = 5000) -> Any:
        return conn.cursor(name=name_hint)

    def schema_fetch_query(self, schemas: Union[str, list[str]]) -> str:
        # Ported from ui/index.html's buildSchemaFetchQuery() — see that
        # function and sql-studio/CLAUDE.md for the json_object_agg (not
        # jsonb) / cross-schema-collision-disambiguation reasoning, both
        # verified against a real Postgres before shipping there. Kept
        # here too so this dialect's schema_fetch_query is independently
        # callable (e.g. by a future headless consumer), even though
        # SQL Studio's own UI still keeps its JS copy for the "copy
        # query for pgAdmin" helper — two copies, kept in sync by hand,
        # same convention this tool already documents for its tokenizer.
        if schemas == "all":
            filter_sql = (
                "n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp%'"
            )
        else:
            names = ", ".join(f"'{s}'" for s in schemas)
            filter_sql = f"n.nspname IN ({names})"
        return f"""
WITH per_table AS (
  SELECT n.nspname AS schema_name, c.relname AS table_name,
    json_object_agg(a.attname, format_type(a.atttypid, a.atttypmod) ORDER BY a.attnum) AS columns
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE {filter_sql}
    AND c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
  GROUP BY n.nspname, c.relname
),
disambiguated AS (
  SELECT
    CASE WHEN count(*) OVER (PARTITION BY table_name) > 1
      THEN schema_name || '.' || table_name ELSE table_name END AS display_name,
    columns
  FROM per_table
)
SELECT json_object_agg(display_name, columns) FROM disambiguated
"""

    # ------------------------------------------------------------------
    # Introspection SQL — ported verbatim from ui/index.html's
    # SHOW_COMMANDS (the Postgres entries), already verified against a
    # real seeded Postgres before shipping there (see sql-studio/CLAUDE.md's
    # "Show commands" section) — not re-derived here, just given a
    # second, headless-callable home.
    # ------------------------------------------------------------------

    def list_tables_sql(self) -> str:
        return f"""SELECT n.nspname AS schema_name, c.relname AS table_name, a.attname AS column_name,
  format_type(a.atttypid, a.atttypmod) AS column_datatype
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped AND {_SYS_SCHEMA_FILTER}
ORDER BY n.nspname, c.relname, a.attnum"""

    def table_columns_sql(self, table_name: str) -> str:
        return f"""SELECT a.attname AS column_name, format_type(a.atttypid, a.atttypmod) AS data_type,
  NOT a.attnotnull AS is_nullable, pg_get_expr(d.adbin, d.adrelid) AS default_value, a.attnum AS ordinal_position
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
WHERE c.relname = {_literal(table_name)} AND a.attnum > 0 AND NOT a.attisdropped AND {_SYS_SCHEMA_FILTER}
ORDER BY a.attnum"""

    def table_definition_sql(self, table_name: str) -> str:
        lit = _literal(table_name)
        return f"""WITH tbl AS (
  SELECT c.oid, n.nspname, c.relname
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE c.relname = {lit} AND c.relkind IN ('r', 'p') AND {_SYS_SCHEMA_FILTER}
  ORDER BY n.nspname LIMIT 1
),
cols AS (
  SELECT '  ' || a.attname || ' ' || format_type(a.atttypid, a.atttypmod) ||
    CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END ||
    CASE WHEN d.adbin IS NOT NULL THEN ' DEFAULT ' || pg_get_expr(d.adbin, d.adrelid) ELSE '' END AS line,
    a.attnum AS ord
  FROM tbl
  JOIN pg_attribute a ON a.attrelid = tbl.oid
  LEFT JOIN pg_attrdef d ON d.adrelid = tbl.oid AND d.adnum = a.attnum
  WHERE a.attnum > 0 AND NOT a.attisdropped
),
cons AS (
  SELECT '  CONSTRAINT ' || con.conname || ' ' || pg_get_constraintdef(con.oid) AS line, 1000 AS ord
  FROM pg_constraint con, tbl WHERE con.conrelid = tbl.oid
),
body AS (SELECT line, ord FROM cols UNION ALL SELECT line, ord FROM cons),
table_sql AS (
  SELECT (SELECT 'CREATE TABLE ' || nspname || '.' || relname || ' (' FROM tbl) || E'\\n' ||
    string_agg(line, ',' || E'\\n' ORDER BY ord) || E'\\n);' AS stmt
  FROM body
),
extra_indexes AS (
  SELECT string_agg(pg_get_indexdef(ix.indexrelid) || ';', E'\\n') AS stmt
  FROM pg_index ix, tbl
  WHERE ix.indrelid = tbl.oid AND NOT ix.indisprimary
    AND ix.indexrelid NOT IN (SELECT conindid FROM pg_constraint WHERE conrelid = tbl.oid AND conindid != 0)
)
SELECT table_sql.stmt || COALESCE(E'\\n\\n' || extra_indexes.stmt, '') AS table_definition
FROM table_sql, extra_indexes"""

    def list_functions_sql(self) -> str:
        return f"""SELECT n.nspname AS schema_name, p.proname AS function_name,
  pg_get_function_result(p.oid) AS return_type, pg_get_function_arguments(p.oid) AS argument_types
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.prokind = 'f' AND {_SYS_SCHEMA_FILTER}
ORDER BY n.nspname, p.proname"""

    def list_triggers_sql(self) -> str:
        return f"""SELECT t.relname AS table_name, tg.tgname AS trigger_name,
  CASE WHEN tg.tgtype & 2 > 0 THEN 'BEFORE' WHEN tg.tgtype & 64 > 0 THEN 'INSTEAD OF' ELSE 'AFTER' END AS timing,
  CASE WHEN tg.tgtype & 4 > 0 THEN 'INSERT' WHEN tg.tgtype & 8 > 0 THEN 'DELETE' WHEN tg.tgtype & 16 > 0 THEN 'UPDATE' ELSE 'TRUNCATE' END AS event,
  p.proname AS function_name
FROM pg_trigger tg
JOIN pg_class t ON t.oid = tg.tgrelid
JOIN pg_proc p ON p.oid = tg.tgfoid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE NOT tg.tgisinternal AND {_SYS_SCHEMA_FILTER}
ORDER BY t.relname, tg.tgname"""

    def list_indexes_sql(self) -> str:
        return f"""SELECT n.nspname AS schema_name, t.relname AS table_name, i.relname AS index_name,
  pg_get_indexdef(ix.indexrelid) AS index_def, ix.indisunique AS is_unique
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE {_SYS_SCHEMA_FILTER}
ORDER BY t.relname, i.relname"""

    def list_foreign_keys_sql(self) -> str:
        return """SELECT n.nspname AS schema_name, t.relname AS table_name, a.attname AS column_name,
  ft.relname AS references_table, fa.attname AS references_column
FROM pg_constraint c
JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_class ft ON ft.oid = c.confrelid
JOIN unnest(c.conkey) WITH ORDINALITY AS ck(attnum, ord) ON true
JOIN unnest(c.confkey) WITH ORDINALITY AS fck(attnum, ord) ON fck.ord = ck.ord
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
JOIN pg_attribute fa ON fa.attrelid = ft.oid AND fa.attnum = fck.attnum
WHERE c.contype = 'f'
ORDER BY t.relname"""

    def list_views_sql(self) -> str:
        return f"""SELECT n.nspname AS schema_name, c.relname AS view_name,
  (SELECT count(*) FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS column_count
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'v' AND {_SYS_SCHEMA_FILTER}
ORDER BY n.nspname, c.relname"""

    def activity_sql(self) -> str:
        return """SELECT pid, state, now() - query_start AS duration, query
FROM pg_stat_activity
WHERE datname = current_database() AND pid != pg_backend_pid()
ORDER BY query_start"""

    def grants_sql(self, table_name: Optional[str] = None) -> str:
        if table_name is None:
            return "SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants"
        return f"SELECT grantee, privilege_type FROM information_schema.role_table_grants WHERE table_name = {_literal(table_name)}"

    def version_sql(self) -> str:
        return "SELECT version() AS version"

"""
core/db/dialect_oracle.py

Oracle's Dialect implementation, using python-oracledb in its default
THIN mode — pure-Python, no Oracle Instant Client install needed in the
Docker image, confirmed by `oracledb.is_thin_mode()` against a real
throwaway gvenzl/oracle-free container before writing any of this.
Also confirmed there: connect+query (needs `FROM DUAL`, unlike
Postgres/SQL Server's bare `SELECT 1`), a bad-password failure
(ORA-01017, ~1s), `conn.call_timeout` as a real working per-statement
timeout (cut a deliberately slow query off at ~0.5s for a 500ms
budget), fetchmany() streaming 7000 rows in 500-row batches with no
named cursor needed, `FETCH FIRST n ROWS ONLY` as a valid 12c+ row-cap
wrap, and that wrapping a `RETURNING ... INTO` statement in that same
SELECT-cap pattern fails outright (`ORA-00903: invalid table name` —
RETURNING INTO is bind-variable-based, never a result set the normal
way, so it can't sit inside a FROM clause at all).
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Union

import oracledb


def _literal(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# Oracle's own default install ships several more built-in schemas than
# the obvious SYS/SYSTEM — confirmed directly against a real
# gvenzl/oracle-free container (these specific names actually own
# tables in a fresh 23ai install, found by running the unfiltered query
# and seeing them show up, not guessed from documentation).
_ORACLE_SYSTEM_SCHEMAS = (
    "SYS", "SYSTEM", "OUTLN", "XDB", "ORDS_METADATA", "ORDS_PUBLIC_USER",
    "APPQOSSYS", "AUDSYS", "DBSFWUSER", "DBSNMP", "DVSYS", "GSMADMIN_INTERNAL",
    "LBACSYS", "VECSYS",
)
_ORACLE_SYSTEM_SCHEMA_FILTER = "owner NOT IN (" + ", ".join(_literal(s) for s in _ORACLE_SYSTEM_SCHEMAS) + ")"


class OracleDialect:
    name = "oracle"
    default_port = 1521
    returning_pattern = re.compile(r"\bRETURNING\b", re.IGNORECASE)

    def build_conninfo(
        self, host: str, port: int, database: str, username: str, password: str,
        *, statement_timeout_ms: Optional[int] = None,
    ) -> dict:
        # `database` doubles as Oracle's service_name — same generic
        # field across all three dialects, just a different real-world
        # meaning (and UI label) per dialect, by design.
        dsn = oracledb.makedsn(host, port, service_name=database)
        conninfo: dict = {"user": username, "password": password, "dsn": dsn}
        if statement_timeout_ms:
            # Not a real driver kwarg — stashed here and applied to each
            # checked-out connection's own `call_timeout` attribute
            # instead (see checkout() below), since that's a per-
            # connection property, not a connect-time/pool-time option.
            conninfo["_call_timeout_ms"] = statement_timeout_ms
        return conninfo

    @staticmethod
    def _strip_private(conninfo: dict) -> dict:
        return {k: v for k, v in conninfo.items() if not k.startswith("_")}

    def verify_connection(self, conninfo: dict, connect_timeout: int = 10) -> None:
        clean = self._strip_private(conninfo)
        with oracledb.connect(tcp_connect_timeout=connect_timeout, **clean) as conn:
            conn.cursor().execute("SELECT 1 FROM DUAL")

    def open_pool(self, conninfo: dict, *, max_size: int, timeout: int = 10) -> Any:
        clean = self._strip_private(conninfo)
        pool = oracledb.create_pool(min=0, max=max_size, increment=1, **clean)
        pool._call_timeout_ms = conninfo.get("_call_timeout_ms")  # read back in checkout()
        return pool

    @contextmanager
    def checkout(self, pool: Any) -> Iterator[Any]:
        conn = pool.acquire()
        try:
            timeout_ms = getattr(pool, "_call_timeout_ms", None)
            if timeout_ms:
                conn.call_timeout = timeout_ms
            yield conn
        finally:
            pool.release(conn)

    def close_pool(self, pool: Any, timeout: int = 5) -> None:
        pool.close(force=True)

    def wrap_row_cap(self, statement: str, n: int) -> str:
        return f"SELECT * FROM ({statement}) FETCH FIRST {n} ROWS ONLY"

    def wrap_dml_returning_cap(self, statement: str, n: int) -> Optional[str]:
        # Confirmed against a real Oracle: wrapping a RETURNING-INTO
        # statement this way fails outright (ORA-00903) — RETURNING
        # INTO is bind-variable-based, not a result set, so there's no
        # clean cap here, same category of gap as SQL Server's OUTPUT.
        return None

    def open_export_cursor(self, conn: Any, name_hint: str, batch_size: int = 5000) -> Any:
        cur = conn.cursor()
        cur.arraysize = batch_size
        return cur

    def schema_fetch_query(self, schemas: Union[str, list[str]]) -> str:
        # ALL_TAB_COLUMNS + JSON_OBJECTAGG (native since Oracle 12.2,
        # well before this 23ai image) — unlike SQL Server, Oracle CAN
        # aggregate straight into a real JSON object, so this returns
        # one row/one column of actual JSON text, same two-level
        # nesting shape as Postgres's json_object_agg version.
        #
        # Two real things found only by running this against a real
        # Oracle, not by reading the SQL: (1) JSON_OBJECTAGG defaults to
        # VARCHAR2(4000) output and raises ORA-40478 ("output value too
        # large") the moment a real schema's JSON exceeds that — both
        # the inner (per-table) and outer (whole-schema) aggregation
        # need `RETURNING CLOB` explicitly, not just the outer one,
        # since a single wide table's own column list can exceed 4000
        # chars on its own. (2) oracledb's thin-mode driver hands the
        # CLOB back as an `oracledb.LOB` object, not a plain Python str
        # — the caller MUST check for a `.read` attribute and call it
        # before `json.loads()`, the same way it would for any other
        # LOB column from this driver.
        if schemas == "all":
            filter_sql = _ORACLE_SYSTEM_SCHEMA_FILTER
        else:
            names = ", ".join(f"'{s.upper()}'" for s in schemas)
            filter_sql = f"owner IN ({names})"
        return f"""
WITH per_table AS (
  SELECT owner, table_name,
    JSON_OBJECTAGG(column_name VALUE data_type RETURNING CLOB) AS columns_json
  FROM all_tab_columns
  WHERE {filter_sql}
  GROUP BY owner, table_name
),
disambiguated AS (
  SELECT
    CASE WHEN COUNT(*) OVER (PARTITION BY table_name) > 1
      THEN owner || '.' || table_name ELSE table_name END AS display_name,
    columns_json
  FROM per_table
)
SELECT JSON_OBJECTAGG(display_name VALUE columns_json FORMAT JSON RETURNING CLOB) AS schema_json
FROM disambiguated
"""

    # ------------------------------------------------------------------
    # Introspection SQL — ported verbatim from ui/index.html's
    # SHOW_COMMANDS oracle entries, already verified against a real
    # throwaway gvenzl/oracle-free container before shipping there (see
    # sql-studio/CLAUDE.md's multi-database section) — not re-derived
    # here, just given a second, headless-callable home.
    # ------------------------------------------------------------------

    def list_tables_sql(self) -> str:
        return f"SELECT owner AS schema_name, table_name, column_name, data_type AS column_datatype FROM all_tab_columns WHERE {_ORACLE_SYSTEM_SCHEMA_FILTER} ORDER BY owner, table_name, column_id"

    def table_columns_sql(self, table_name: str) -> str:
        return f"SELECT column_name, data_type, nullable FROM all_tab_columns WHERE table_name = {_literal(table_name.upper())} ORDER BY column_id"

    def table_definition_sql(self, table_name: str) -> str:
        lit = _literal(table_name.upper())
        return f"""SELECT 'CREATE TABLE ' || owner || '.' || table_name || ' (' || CHR(10) ||
  LISTAGG('  ' || column_name || ' ' || data_type ||
    CASE WHEN nullable = 'N' THEN ' NOT NULL' ELSE '' END, ',' || CHR(10))
  WITHIN GROUP (ORDER BY column_id) || CHR(10) || ');' AS table_definition
FROM all_tab_columns
WHERE table_name = {lit}
GROUP BY owner, table_name"""

    def list_functions_sql(self) -> str:
        return f"SELECT owner, object_name, object_type FROM all_objects WHERE object_type IN ('FUNCTION','PROCEDURE') AND {_ORACLE_SYSTEM_SCHEMA_FILTER} ORDER BY owner, object_name"

    def list_triggers_sql(self) -> str:
        return f"SELECT owner, trigger_name, table_name, triggering_event, status FROM all_triggers WHERE {_ORACLE_SYSTEM_SCHEMA_FILTER} ORDER BY owner, table_name, trigger_name"

    def list_indexes_sql(self) -> str:
        return f"SELECT owner, index_name, table_name, uniqueness FROM all_indexes WHERE {_ORACLE_SYSTEM_SCHEMA_FILTER} ORDER BY owner, table_name, index_name"

    def list_foreign_keys_sql(self) -> str:
        return f"""SELECT a.owner AS from_schema, a.table_name AS from_table, acc.column_name AS from_column,
       r.owner AS to_schema, r.table_name AS to_table, rcc.column_name AS to_column
FROM all_constraints a
JOIN all_cons_columns acc ON acc.constraint_name = a.constraint_name AND acc.owner = a.owner
JOIN all_constraints r ON r.constraint_name = a.r_constraint_name AND r.owner = a.r_owner
JOIN all_cons_columns rcc ON rcc.constraint_name = r.constraint_name AND rcc.owner = r.owner AND rcc.position = acc.position
WHERE a.constraint_type = 'R' AND {_ORACLE_SYSTEM_SCHEMA_FILTER.replace("owner", "a.owner")}
ORDER BY a.owner, a.table_name"""

    def list_views_sql(self) -> str:
        return f"SELECT owner, view_name FROM all_views WHERE {_ORACLE_SYSTEM_SCHEMA_FILTER} ORDER BY owner, view_name"

    def activity_sql(self) -> str:
        return "SELECT sid, serial#, username, status, machine, program FROM v$session WHERE username IS NOT NULL ORDER BY sid"

    def grants_sql(self, table_name: Optional[str] = None) -> str:
        base = "SELECT grantee, table_schema AS owner, table_name, privilege FROM all_tab_privs"
        if table_name is not None:
            base += f" WHERE table_name = {_literal(table_name.upper())}"
        return base + " ORDER BY grantee"

    def version_sql(self) -> str:
        return "SELECT banner AS version FROM v$version WHERE banner LIKE 'Oracle%'"

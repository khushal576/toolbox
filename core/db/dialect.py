"""
core/db/dialect.py

The `Dialect` interface — one implementation per database
(PostgresDialect / MssqlDialect / OracleDialect) — is what lets
core/pooled_db.py's PooledDbConnection, sql-studio/query_guard.py, and
sql-studio/db_engine.py stay database-agnostic. Everything that differs
between Postgres/SQL Server/Oracle (how to build a conninfo, how to open
a pool, how to cap a row-returning statement to N rows, how to stream an
uncapped export) lives behind this one interface instead of being
hand-rolled per call site.

This is meant to be the reusable base for any FUTURE tool that needs to
connect to more than one kind of database too — see ../../CLAUDE.md's
"Shared connectors" section. A new tool should implement against this
Protocol (or just construct a PooledDbConnection with an existing
Dialect instance) rather than hand-rolling a fourth connector.

Row-cap wrapping strategy (same shape, different template per dialect):
every dialect wraps a row-returning SELECT as an outer subquery —
Postgres: `SELECT * FROM (<sql>) AS _sq LIMIT {n}`; SQL Server:
`SELECT TOP {n} * FROM (<sql>) AS _sq` (T-SQL forbids a bare trailing
ORDER BY inside a derived table unless TOP/OFFSET/FOR XML is present in
THAT inner query too — wrap_row_cap() must strip the statement's own
top-level trailing ORDER BY and re-append it after the TOP-wrapped
outer SELECT instead, confirmed against a real SQL Server); Oracle
(12c+): `SELECT * FROM (<sql>) FETCH FIRST {n} ROWS ONLY`.

Row-returning DML (INSERT/UPDATE/DELETE ... RETURNING, or SQL Server's
OUTPUT, or Oracle's RETURNING ... INTO) has no clean cap: rewriting
risks changing which rows get written, and Oracle's RETURNING INTO is
bind-variable-based, not a result set at all — wrap_dml_returning_cap()
returns None when no safe cap exists, and callers (query_guard.py) must
reject that case with a clear error rather than run it uncapped or
mis-cap it. Confirmed empirically, not assumed: wrapping either
dialect's row-returning DML in the SELECT-cap pattern fails outright
(SQL Server: "Incorrect syntax near 'OUTPUT'"; Oracle: "ORA-00903:
invalid table name") — rejecting before attempting avoids surfacing
either native error to the user.
"""

from __future__ import annotations

import re
from typing import Any, ContextManager, Optional, Protocol, Union


class Dialect(Protocol):
    name: str
    default_port: int
    # RETURNING for Postgres/Oracle, OUTPUT for SQL Server — query_guard.py
    # scans statement text with its OWN tokenizer (string/comment-aware
    # already, dialect-agnostic) and searches each 'code' segment against
    # this pattern, rather than each Dialect re-implementing tokenizing.
    returning_pattern: re.Pattern[str]

    def build_conninfo(
        self, host: str, port: int, database: str, username: str, password: str,
        *, statement_timeout_ms: Optional[int] = None,
    ) -> Any:
        """Build whatever connection-info value this dialect's driver
        needs (a conninfo string for psycopg, a kwargs dict for
        pytds/oracledb). Opaque to every caller except this dialect's
        own verify_connection/open_pool."""
        ...

    def verify_connection(self, conninfo: Any, connect_timeout: int = 10) -> None:
        """Validate credentials with a direct, UNPOOLED connection before
        any pool is built — see core/postgres_conn.py's verify_connection
        docstring for why this matters (a bad password must surface
        immediately, not after a pool's own retry/timeout behavior).
        Raises on failure."""
        ...

    def open_pool(self, conninfo: Any, *, max_size: int, timeout: int = 10) -> Any:
        """Open and return a ready-to-use pool object (opaque — only this
        dialect's own checkout/close_pool touch it)."""
        ...

    def checkout(self, pool: Any) -> ContextManager[Any]:
        """Context manager yielding one raw connection from the pool."""
        ...

    def close_pool(self, pool: Any, timeout: int = 5) -> None:
        ...

    def wrap_row_cap(self, statement: str, n: int) -> str:
        """Wrap a row-returning statement so the database itself never
        returns more than n rows."""
        ...

    def wrap_dml_returning_cap(self, statement: str, n: int) -> Optional[str]:
        """Wrap a row-returning DML statement (RETURNING/OUTPUT) the same
        way, or return None if this dialect has no clean way to do that
        — see the module docstring."""
        ...

    def open_export_cursor(self, conn: Any, name_hint: str, batch_size: int = 5000) -> Any:
        """A cursor suitable for streaming an uncapped export via
        fetchmany() batching — a server-side NAMED cursor for Postgres,
        a plain cursor with `arraysize` set for SQL Server/Oracle, whose
        drivers stream over fetchmany() without needing a named server
        cursor (confirmed against real containers — a >5000-row table
        streamed correctly in bounded fetchmany(500) batches for both,
        same as Postgres's named-cursor path). Not yet `execute()`'d —
        the caller runs the statement and loops fetchmany()."""
        ...

    def schema_fetch_query(self, schemas: Union[str, list[str]]) -> str:
        """The canonical `{table: {column: type}}`-shape introspection
        query for this dialect, given `"all"` or a list of schema/owner
        names."""
        ...

    # ------------------------------------------------------------------
    # Introspection SQL — the ~11 highest-value "show X" categories,
    # symmetric across all three dialects on purpose: this is what makes
    # core/db/ a genuine reusable base rather than just something SQL
    # Studio happens to also work for three databases. Each returns SQL
    # TEXT (same shape as schema_fetch_query above), not structured
    # data — a caller runs it through its own connection/pool exactly
    # like any other query. sql-studio/ui/index.html's SHOW_COMMANDS
    # keeps its OWN hand-written copy of equivalent SQL (same "two
    # independent copies, kept in sync by hand" convention already used
    # for schema_fetch_query and the tokenizer) — these Python methods
    # exist so a HEADLESS caller (the orchestrator, a future tool) can
    # get the same introspection without a browser involved at all.
    # ------------------------------------------------------------------

    def list_tables_sql(self) -> str:
        """Every table's columns — schema/owner, table, column, type."""
        ...

    def table_columns_sql(self, table_name: str) -> str:
        """One table's columns — name, type, nullability, position."""
        ...

    def table_definition_sql(self, table_name: str) -> str:
        """Reconstructed CREATE TABLE for one table."""
        ...

    def list_functions_sql(self) -> str:
        """Every function (and, where the dialect distinguishes them,
        procedure) — schema/owner, name, kind."""
        ...

    def list_triggers_sql(self) -> str:
        """Every trigger — table, name, status/timing."""
        ...

    def list_indexes_sql(self) -> str:
        """Every index — table, name, unique?, type."""
        ...

    def list_foreign_keys_sql(self) -> str:
        """Every foreign key — source table/column, target table/column."""
        ...

    def list_views_sql(self) -> str:
        """Every view — schema/owner, name."""
        ...

    def activity_sql(self) -> str:
        """Currently active sessions/queries."""
        ...

    def grants_sql(self, table_name: Optional[str] = None) -> str:
        """Privilege grants — scoped to one table if given, else every
        grant this dialect's catalogs can cheaply list."""
        ...

    def version_sql(self) -> str:
        """The connected server's version string."""
        ...

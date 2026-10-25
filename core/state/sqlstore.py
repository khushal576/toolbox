"""
core.state.sqlstore — a tool's small relational store: Postgres in the Toolbox, SQLite standalone (roadmap B6).

The tools' stores were written for sqlite3 (`?` placeholders, `row["col"]`, one transaction per `with _connect()`).
This keeps that exact shape so their SQL barely changes, while the data moves to Toolbox's Postgres:

    STORE = SqlStore("data_syncer", sqlite_path=DB_PATH, ddl=_SCHEMA,
                     add_columns={"projects": {"fix_sequences": "INTEGER NOT NULL DEFAULT 1"}})
    STORE.init()                         # create schema/tables/columns; first time: copy the old SQLite file in
    with STORE.connect() as con:         # ONE transaction (commit on exit, rollback on error)
        con.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()["name"]

- Postgres (TOOLBOX_DATABASE_URL set): tables live in the tool's own schema (`SET LOCAL search_path`, so pooled
  connections never keep it). The DDL is written once in SQLite's dialect; INTEGER becomes BIGINT (row counts and
  byte sizes pass 2^31), REAL → DOUBLE PRECISION, BLOB → BYTEA. Timestamps stay ISO text and booleans 0/1 integers,
  exactly as the tools already read and write them.
- One-time migration: on the first `init()` against Postgres, if the old SQLite file exists its rows are copied
  (columns matched by name, existing ids skipped) under an advisory lock, and `<schema>._meta` records it — it never
  runs twice, and the SQLite file is left untouched as a backup.
- SQLite (no TOOLBOX_DATABASE_URL): the old behavior — WAL, foreign keys on, 30 s busy timeout.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

logger = logging.getLogger(__name__)
_CREATE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", re.I)


class Row(dict):
    """dict with sqlite3.Row's positional access too (`row[0]`)."""

    def __getitem__(self, k: Any) -> Any:
        if isinstance(k, int):
            return list(self.values())[k]
        return super().__getitem__(k)


def _value(v: Any) -> Any:
    # SUM() over BIGINT is NUMERIC in Postgres; the tools expect ints (as SQLite returns)
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, memoryview):
        return bytes(v)
    return v


def _pg_rows(cursor: Any):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, (_value(v) for v in values)))


def _sqlite_row(cursor: sqlite3.Cursor, values: tuple) -> Row:
    return Row(zip([c[0] for c in cursor.description], values))


def to_pg_sql(sql: str) -> str:
    """sqlite3 placeholders → psycopg ('?' → '%s'; a literal '%' must be doubled)."""
    return sql.replace("%", "%%").replace("?", "%s")


def to_pg_ddl(ddl: str) -> str:
    ddl = re.sub(r"\bINTEGER\b", "BIGINT", ddl)
    ddl = re.sub(r"\bREAL\b", "DOUBLE PRECISION", ddl)
    return re.sub(r"\bBLOB\b", "BYTEA", ddl)


class _PgConn:
    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self._conn.cursor(row_factory=_pg_rows)
        # prepare=False: tools share SQL text ("SELECT * FROM projects WHERE id = %s") but resolve it through a
        # different search_path; a statement psycopg auto-prepared for one tool's table on this pooled connection
        # would be reused for another's → "cached plan must not change result type" (found live in B6).
        cur.execute(to_pg_sql(sql), tuple(params), prepare=False)
        return cur


def _use_postgres() -> bool:
    try:
        from core.state import config
    except ImportError:
        return False
    return bool(config.load().database_url)


class SqlStore:
    def __init__(self, schema: str, *, sqlite_path: Path, ddl: str,
                 add_columns: Optional[dict[str, dict[str, str]]] = None, backend: Optional[str] = None):
        self.schema, self.sqlite_path, self.ddl = schema, Path(sqlite_path), ddl
        self.add_columns = add_columns or {}
        self.backend = backend or ("postgres" if _use_postgres() else "sqlite")
        self.tables = _CREATE_TABLE_RE.findall(ddl)  # creation order = parents first (used by the migration)

    # ---- connections -------------------------------------------------------------------------------------
    @contextmanager
    def connect(self) -> Iterator[Any]:
        """One transaction. `con.execute(sql, params)` returns a cursor with fetchone/fetchall/iteration/rowcount."""
        if self.backend == "postgres":
            from core.state import db

            with db.connection() as conn, conn.transaction():
                conn.execute(f'SET LOCAL search_path TO "{self.schema}"')
                yield _PgConn(conn)
            return
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.sqlite_path, timeout=30)
        con.row_factory = _sqlite_row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ---- setup -------------------------------------------------------------------------------------------
    def init(self) -> None:
        if self.backend == "postgres":
            self._init_postgres()
            return
        with self.connect() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(self.ddl)
            for table, cols in self.add_columns.items():
                have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                for name, decl in cols.items():
                    if name not in have:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def _init_postgres(self) -> None:
        from core.state import db

        db.ensure_schema(self.schema)
        with db.connection() as conn, conn.transaction():
            # web and worker may start together: one of them creates/migrates, the other waits
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"toolbox-sqlstore-{self.schema}",))
            conn.execute(f'SET LOCAL search_path TO "{self.schema}"')
            conn.execute(to_pg_ddl(self.ddl))
            for table, cols in self.add_columns.items():
                for name, decl in cols.items():
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {to_pg_ddl(decl)}")
            conn.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            if conn.execute("SELECT 1 FROM _meta WHERE key = 'sqlite_migration'").fetchone() is None:
                note = self._migrate_sqlite(conn)
                conn.execute("INSERT INTO _meta (key, value) VALUES ('sqlite_migration', %s)", (note,))

    def _migrate_sqlite(self, conn: Any) -> str:
        """Copy every row of the old SQLite file (if any) into the Postgres tables. Returns a note for _meta."""
        now = datetime.now(timezone.utc).isoformat()
        if not self.sqlite_path.exists():
            return f"{now}: no SQLite file at {self.sqlite_path} — nothing to copy"
        src = sqlite3.connect(f"file:{self.sqlite_path}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        counts = []
        try:
            have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table in self.tables:
                if table not in have:
                    continue
                pg_cols = {r[0] for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
                    (self.schema, table))}
                cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})") if r[1] in pg_cols]
                rows = [tuple(r) for r in src.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()]
                insert = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                          f"ON CONFLICT DO NOTHING")
                skipped = 0
                if rows:
                    try:
                        with conn.transaction(), conn.cursor() as cur:  # savepoint
                            cur.executemany(insert, rows)
                    except Exception:  # noqa: BLE001 - e.g. an orphan row (SQLite didn't enforce its FK): go row by row
                        for r in rows:
                            try:
                                with conn.transaction():
                                    conn.execute(insert, r)
                            except Exception as exc:  # noqa: BLE001
                                skipped += 1
                                logger.warning("%s.%s: skipped a row during migration: %s", self.schema, table, exc)
                counts.append(f"{table}={len(rows) - skipped}" + (f" ({skipped} skipped)" if skipped else ""))
        finally:
            src.close()
        note = f"{now}: copied from {self.sqlite_path}: {', '.join(counts) or 'no tables'}"
        logger.warning("%s: %s", self.schema, note)
        return note

    def migration_note(self) -> Optional[str]:
        if self.backend != "postgres":
            return None
        with self.connect() as con:
            row = con.execute("SELECT value FROM _meta WHERE key = 'sqlite_migration'").fetchone()
        return row["value"] if row else None

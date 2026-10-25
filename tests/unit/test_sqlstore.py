"""core.state.sqlstore (roadmap B6). SQLite mode runs anywhere; the Postgres tests (incl. the one-time SQLite →
Postgres migration) need TOOLBOX_DATABASE_URL — run them inside the container:
    docker cp tests toolbox-toolbox-1:/tmp/tests && docker exec -w /tmp toolbox-toolbox-1 python -m pytest /tmp/tests/unit/test_sqlstore.py -q
"""

import os
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.state.sqlstore import Row, SqlStore, to_pg_ddl, to_pg_sql  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS parents (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL DEFAULT 0, ratio REAL, blob BLOB,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS children (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    n INTEGER NOT NULL
);
"""
OLD_DDL = DDL.replace(" size INTEGER NOT NULL DEFAULT 0,", "")  # a pre-"size" database


def test_translation():
    assert to_pg_sql("SELECT * FROM t WHERE a = ? AND b LIKE '50%'") == "SELECT * FROM t WHERE a = %s AND b LIKE '50%%'"
    assert to_pg_ddl("x INTEGER, y REAL, z BLOB, w INTEGERS") == "x BIGINT, y DOUBLE PRECISION, z BYTEA, w INTEGERS"


def test_row_supports_keys_and_positions():
    r = Row(a=1, b="x")
    assert r["b"] == "x" and r[0] == 1 and r[1] == "x" and dict(r) == {"a": 1, "b": "x"}


def _exercise(store):
    store.init()
    store.init()  # idempotent
    with store.connect() as con:
        con.execute("INSERT INTO parents (id, name, size, ratio, blob, created_at) VALUES (?,?,?,?,?,?)",
                    ("p1", "one", 3_000_000_000, 0.5, b"\x00\x01", "2026-01-01T00:00:00+00:00"))
        con.execute("INSERT INTO children (id, parent_id, n) VALUES (?,?,?)", ("c1", "p1", 5))
        con.execute("INSERT INTO children (id, parent_id, n) VALUES (?,?,?)", ("c2", "p1", 7))
    with store.connect() as con:
        p = con.execute("SELECT * FROM parents WHERE id = ?", ("p1",)).fetchone()
        total = con.execute("SELECT COALESCE(SUM(n), 0) AS s FROM children").fetchone()
        rows = [dict(r) for r in con.execute("SELECT id FROM children ORDER BY id")]
    assert p["size"] == 3_000_000_000 and p["blob"] == b"\x00\x01" and p["ratio"] == 0.5
    assert total["s"] == 12 and type(total[0]) is int  # Postgres SUM → NUMERIC → back to int
    assert rows == [{"id": "c1"}, {"id": "c2"}]
    with pytest.raises(RuntimeError):  # an error rolls the whole block back
        with store.connect() as con:
            con.execute("UPDATE parents SET name = ? WHERE id = ?", ("changed", "p1"))
            raise RuntimeError("boom")
    with store.connect() as con:
        assert con.execute("SELECT name FROM parents").fetchone()["name"] == "one"
        assert con.execute("DELETE FROM parents WHERE id = ?", ("p1",)).rowcount == 1
        assert con.execute("SELECT COUNT(*) FROM children").fetchone()[0] == 0  # cascade (FKs on in both)


def test_sqlite_backend(tmp_path):
    _exercise(SqlStore("t_unit", sqlite_path=tmp_path / "x.db", ddl=DDL, backend="sqlite"))


def test_sqlite_adds_missing_columns(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as con:
        con.executescript(OLD_DDL)
        con.execute("INSERT INTO parents (id, name, created_at) VALUES ('p', 'n', 't')")
    s = SqlStore("t_unit", sqlite_path=path, ddl=OLD_DDL, backend="sqlite",
                 add_columns={"parents": {"size": "INTEGER NOT NULL DEFAULT 7"}})
    s.init()
    with s.connect() as con:
        assert con.execute("SELECT size FROM parents").fetchone()["size"] == 7


# ---- Postgres (inside the container) -------------------------------------------------------------------------

needs_pg = pytest.mark.skipif(not os.environ.get("TOOLBOX_DATABASE_URL"), reason="needs TOOLBOX_DATABASE_URL")


@pytest.fixture
def pg_schema():
    from core.state import db

    name = f"t_unit_{uuid.uuid4().hex[:8]}"
    yield name
    with db.connection() as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


@needs_pg
def test_postgres_backend(tmp_path, pg_schema):
    _exercise(SqlStore(pg_schema, sqlite_path=tmp_path / "none.db", ddl=DDL, backend="postgres"))


@needs_pg
def test_postgres_migrates_the_old_sqlite_file_once(tmp_path, pg_schema):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as con:  # an old database: no "size" column, and an orphan child (FKs were off)
        con.executescript(OLD_DDL)
        con.execute("INSERT INTO parents (id, name, ratio, blob, created_at) VALUES ('p1', 'one', 1.5, x'ff', 't')")
        con.execute("INSERT INTO children (id, parent_id, n) VALUES ('c1', 'p1', 1)")
        con.execute("INSERT INTO children (id, parent_id, n) VALUES ('c9', 'gone', 2)")
    s = SqlStore(pg_schema, sqlite_path=path, ddl=DDL, backend="postgres")
    s.init()
    with s.connect() as con:
        p = con.execute("SELECT * FROM parents").fetchone()
        kids = [r["id"] for r in con.execute("SELECT id FROM children")]
    assert (p["name"], p["size"], p["ratio"], p["blob"]) == ("one", 0, 1.5, b"\xff") and kids == ["c1"]
    note = s.migration_note()
    assert "parents=1" in note and "children=1 (1 skipped)" in note
    with sqlite3.connect(path) as con:  # rows added to SQLite later are NOT copied again
        con.execute("INSERT INTO parents (id, name, created_at) VALUES ('p2', 'late', 't')")
    s.init()
    with s.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM parents").fetchone()[0] == 1
    assert path.exists()  # the SQLite file stays as a backup


@needs_pg
def test_postgres_without_sqlite_file_records_nothing_to_copy(tmp_path, pg_schema):
    s = SqlStore(pg_schema, sqlite_path=tmp_path / "missing.db", ddl=DDL, backend="postgres")
    s.init()
    assert "nothing to copy" in s.migration_note()


@needs_pg
def test_same_sql_in_two_schemas_never_shares_a_prepared_plan(tmp_path, pg_schema):
    """Regression (B6): psycopg auto-prepares after 5 runs per connection; the same text in another tool's schema
    then failed with "cached plan must not change result type"."""
    from core.state import db

    other = pg_schema + "_b"
    a = SqlStore(pg_schema, sqlite_path=tmp_path / "a.db", backend="postgres",
                 ddl="CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT);")
    b = SqlStore(other, sqlite_path=tmp_path / "b.db", backend="postgres",
                 ddl="CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, size INTEGER, flag INTEGER);")
    try:
        a.init()
        b.init()
        with a.connect() as con:
            con.execute("INSERT INTO projects VALUES (?, ?)", ("x", "a-name"))
        with b.connect() as con:
            con.execute("INSERT INTO projects VALUES (?, ?, ?)", ("x", 5, 1))
        for _ in range(12):
            with a.connect() as con:
                assert con.execute("SELECT * FROM projects WHERE id = ?", ("x",)).fetchone()["name"] == "a-name"
            with b.connect() as con:
                assert con.execute("SELECT * FROM projects WHERE id = ?", ("x",)).fetchone()["size"] == 5
    finally:
        with db.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{other}" CASCADE')

"""Roadmap L4: moving Vault Data in and out of tools (core.lake export_table / import_file) and staging database
tables (data-lake/staging.py). Needs DuckDB + pyarrow — run inside the container:
    docker cp tests toolbox-rt-data-1:/tmp/tests && docker exec -w /tmp toolbox-rt-data-1 python -m pytest /tmp/tests/unit/test_lake_l4.py -q
"""

import contextlib
import datetime as dt
import sqlite3
import sys
import threading
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "data-lake"))

duckdb = pytest.importorskip("duckdb", reason="L4 tests run inside the container")
pytest.importorskip("pyarrow")

from core import lake  # noqa: E402
from core.state.filecache import FileCache  # noqa: E402
from core.state.sqlstore import SqlStore  # noqa: E402


def _tool(module):
    import importlib

    try:
        return importlib.import_module(f"data_lake.{module}")
    except ImportError:
        return importlib.import_module(module)


@pytest.fixture
def L(tmp_path, monkeypatch):
    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    store = SqlStore("lake", sqlite_path=tmp_path / "lake.db", ddl=lake._SCHEMA, backend="sqlite")
    monkeypatch.setattr(lake, "STORE", store)
    monkeypatch.setattr(lake, "_connect", store.connect)
    monkeypatch.setattr(lake, "FILES", FileCache("lake", tmp_path / "files"))
    monkeypatch.setattr(lake, "_ready", False)
    monkeypatch.setattr(lake, "scoped", lambda plugin: lake.ScopedLake(plugin, "write"))
    return lake


def test_import_file_and_export_round_trip(L, tmp_path):
    csv = tmp_path / "in.csv"
    csv.write_text("id,name,amount\n1,a,1.5\n2,b,2.5\n3,c,\n")
    t = L.import_file("staging", "people", csv, source={"kind": "test"})
    assert (t["full_name"], t["row_count"]) == ("staging.people", 3)
    assert [c["type"] for c in t["columns"]] == ["BIGINT", "VARCHAR", "DOUBLE"]
    with pytest.raises(L.LakeError, match="already exists"):
        L.import_file("staging", "people", csv)
    out = L.export_table("staging", "people", tmp_path / "out" / "p.parquet")
    assert out["rows"] == 3 and duckdb.sql(f"SELECT sum(id) FROM '{out['path']}'").fetchone()[0] == 6
    out = L.export_table("staging", "people", tmp_path / "p.csv", "csv", limit=2)
    assert out["rows"] == 2 and out["path"].read_text().splitlines() == ["id,name,amount", "1,a,1.5", "2,b,2.5"]
    assert [w["name"] for w in L.catalog()] == ["staging"] and L.catalog()[0]["tables"][0]["row_count"] == 3
    with pytest.raises(L.ScopeError):
        L.ScopedLake("t", "read").import_file("staging", "x", csv)
    assert L.ScopedLake("t", "read").export_table("staging", "people", tmp_path / "r.parquet")["rows"] == 3


def test_staging_helpers(tmp_path):
    st = _tool("staging")
    assert st.target_names(["public.orders", "sales.orders", "public.Customers"]) == {
        "public.orders": "public_orders", "sales.orders": "sales_orders", "public.Customers": "customers"}
    assert st._check_select("  with x as (select 1) select * from x; ") == "with x as (select 1) select * from x"
    for bad in ("DELETE FROM t", "select 1; drop table t", "-- hi\nupdate t set a=1"):
        with pytest.raises(st.StageError):
            st._check_select(bad)
    assert st._check_select("select ';' as semi") == "select ';' as semi"
    # odd values become text instead of failing the batch; a NULL-only first batch still gets the real type later
    import uuid

    st._batch_to_parquet([(1, uuid.UUID(int=1), Decimal("1.50"), dt.date(2026, 1, 2), None)],
                         ["id", "u", "d", "day", "later"], tmp_path / "b0.parquet")
    st._batch_to_parquet([(2, uuid.UUID(int=2), Decimal("2.25"), dt.date(2026, 1, 3), 7)],
                         ["id", "u", "d", "day", "later"], tmp_path / "b1.parquet")
    parts = st._merge([tmp_path / "b0.parquet", tmp_path / "b1.parquet"], [], tmp_path / "parts", tmp_path)
    rel = duckdb.sql(f"SELECT * FROM read_parquet({[str(p) for p in parts]}) ORDER BY id")
    assert dict(zip(rel.columns, rel.types))["later"] in ("BIGINT", "INTEGER")
    assert rel.fetchall()[1][1:] == ("00000000-0000-0000-0000-000000000002", Decimal("2.25"), dt.date(2026, 1, 3), 7)
    st._batch_to_parquet([({"lang": "en"},), ({"lang": "de", "x": [1]},), (None,)], ["prefs"], tmp_path / "j.parquet")
    assert duckdb.sql(f"SELECT prefs->>'lang' FROM '{tmp_path / 'j.parquet'}'").fetchall() == [("en",), ("de",), (None,)]
    empty = st._merge([], ["a", "b"], tmp_path / "empty", tmp_path)
    assert duckdb.sql(f"SELECT * FROM '{empty[0]}'").columns == ["a", "b"]


class _Ctx:
    def __init__(self):
        self.cancel, self.progress, self.lines = threading.Event(), {}, []

    def log(self, level, msg, *_):
        self.lines.append((level, msg))


class _Cursor(sqlite3.Cursor):  # sqlite's cursor isn't a context manager; the real drivers' are
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_run_stage_tables_and_query(L, monkeypatch):
    st = _tool("staging")
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute('CREATE TABLE "orders" (id INTEGER, amount REAL, note TEXT)')
    db.executemany("INSERT INTO orders VALUES (?,?,?)", [(i, i * 1.5, None if i % 2 else "x") for i in range(1, 1201)])
    db.execute('CREATE TABLE "empty_one" (a TEXT)')

    @contextlib.contextmanager
    def fake_connect(cid):
        class D:  # the one Dialect method staging uses
            def open_export_cursor(self, conn, name_hint, batch_size=5000):
                return conn.cursor(_Cursor)
        yield db, D(), {"name": "test db", "db_type": "sqlite"}

    monkeypatch.setattr(st, "connect", fake_connect)
    monkeypatch.setattr(st, "BATCH_ROWS", 500)                 # 1200 rows → 3 batches
    ctx = _Ctx()
    st.run_stage(ctx, {"connection_id": "x", "workspace": "mig", "tables": ["orders", "empty_one"]})
    assert ctx.progress["phase"] == "done", ctx.lines
    t = L.get_table("mig", "orders")
    assert t["row_count"] == 1200 and t["source"]["table"] == "orders" and t["source"]["connection"] == "test db"
    assert L.get_table("mig", "empty_one")["row_count"] == 0
    ctx = _Ctx()
    st.run_stage(ctx, {"connection_id": "x", "workspace": "mig", "sql": "SELECT id FROM orders WHERE id <= 10",
                       "table": "first_ten"})
    assert ctx.progress["phase"] == "done" and L.get_table("mig", "first_ten")["row_count"] == 10
    ctx = _Ctx()
    st.run_stage(ctx, {"connection_id": "x", "workspace": "mig", "tables": ["orders"]})   # create again → refused
    assert ctx.progress["phase"] == "failed" and "already exists" in ctx.progress["error"]
    ctx = _Ctx()
    ctx.cancel.set()
    st.run_stage(ctx, {"connection_id": "x", "workspace": "mig", "tables": ["orders"], "mode": "overwrite"})
    assert ctx.progress["error"] == "Stopped." and L.get_table("mig", "orders")["version"] == 1   # untouched

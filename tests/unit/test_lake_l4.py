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


# ---- roadmap L5: profiles, suggested joins, S3 locations --------------------------------------------------------

def _t(L, tmp_path, ws, name, sql):
    out = tmp_path / f"{ws}_{name}.parquet"
    duckdb.sql(f"COPY ({sql}) TO '{out}' (FORMAT PARQUET)")
    return L.write_table(ws, name, [out], create_workspace_if_missing=True)


def test_profile_is_exact_and_cached_per_version(L, tmp_path, monkeypatch):
    _t(L, tmp_path, "s", "orders", "SELECT i AS id, i % 3 AS k, CASE WHEN i % 4 = 0 THEN NULL ELSE 'x' || (i % 2) END AS tag "
                                  "FROM range(1000) t(i)")
    p = L.profile("s", "orders")
    cols = {c["name"]: c for c in p["columns"]}
    assert p["rows"] == 1000 and not p["cached"] and p["top_from_sample"] is None
    assert (cols["id"]["min"], cols["id"]["max"], cols["id"]["mean"]) == ("0", "999", 499.5)
    assert cols["tag"]["null_pct"] == 25.0 and cols["tag"]["top"][0]["count"] == 500 and "mean" not in cols["tag"]
    assert [t["value"] for t in cols["k"]["top"]] == ["0", "1", "2"]
    assert L.profile("s", "orders")["cached"] is True
    _t(L, tmp_path, "x", "o2", "SELECT 1 AS id")  # unrelated write leaves the cache alone
    L.write_table("s", "orders", [tmp_path / "x_o2.parquet"], mode="overwrite")
    assert L.profile("s", "orders")["rows"] == 1 and not L.profile("s", "orders", refresh=True)["cached"]
    monkeypatch.setattr(L, "PROFILE_SAMPLE", 10)
    big = L.profile("s", "orders", refresh=True)
    assert big["top_from_sample"] is None  # 1 row is under the sample size


def test_suggested_joins_are_checked_on_the_data(L, tmp_path):
    _t(L, tmp_path, "sales", "orders", "SELECT i AS id, 1 + i % 50 AS customer_id, i % 7 AS status FROM range(500) t(i)")
    _t(L, tmp_path, "crm", "customers", "SELECT i AS id, 'c' || i AS name FROM range(1, 51) t(i)")
    _t(L, tmp_path, "crm", "ghosts", "SELECT i + 100000 AS customer_id FROM range(10) t(i)")   # name matches, no data
    j = L.suggest_joins("sales", "orders")
    assert j[0]["table"] == "crm.customers" and (j[0]["column"], j[0]["other_column"]) == ("customer_id", "id")
    assert j[0]["overlap_pct"] == 100.0 and j[0]["join"] == 'JOIN crm.customers ON orders."customer_id" = customers."id"'
    assert not any(x["table"] == "crm.ghosts" for x in j)          # 0 % overlap → not suggested
    assert any(x["table"] == "sales.orders" for x in L.suggest_joins("crm", "customers"))   # and the other way round


def test_s3_secret_and_names(L):
    sql = L.s3_secret_sql({"access_key_id": "AK", "secret_access_key": "s'c", "region": "eu-west-1"}, "s3_x", "s3://b")
    assert "KEY_ID 'AK'" in sql and "SECRET 's''c'" in sql and "SCOPE 's3://b'" in sql and "ENDPOINT" not in sql
    sql = L.s3_secret_sql({"access_key_id": "a", "secret_access_key": "b", "endpoint": "http://minio:9000"}, "s3_y")
    assert "ENDPOINT 'minio:9000'" in sql and "USE_SSL false" in sql and "URL_STYLE 'path'" in sql
    assert L.s3_bucket("s3://my-bucket/a/*.parquet") == "my-bucket"
    with pytest.raises(L.LakeError):
        L.s3_bucket("/data/x.csv")
    with pytest.raises(L.LakeError, match="S3 location"):
        L.register_external("w", "t", "s3://b/x.parquet", "parquet", create_workspace_if_missing=True)
    loader = _tool("loader")
    assert [loader.format_from_name(n) for n in ("s3://b/a.csv.gz", "s3://b/x.PARQUET", "s3://b/l.jsonl", "s3://b/dir/x")] \
        == ["csv", "parquet", "json", "auto"]


def test_sql_style_type_names():
    assert [lake.sql_type(t) for t in ("VARCHAR", "DECIMAL(12,2)", "BIGINT", "TIMESTAMP WITH TIME ZONE", "DOUBLE")] == \
        ["varchar", "numeric(12,2)", "bigint", "timestamptz", "double precision"]
    assert lake.sql_type("VARCHAR", "character varying(100)") == "varchar(100)"     # the source DB's declared type wins
    assert lake.sql_type("DECIMAL(6,2)", "numeric(12,2)") == "numeric(12,2)"


def test_staged_tables_keep_declared_types(L, tmp_path):
    out = tmp_path / "x.parquet"
    duckdb.sql(f"COPY (SELECT 'a' AS name, 1.5::DECIMAL(6,2) AS amount, 1 AS n) TO '{out}' (FORMAT PARQUET)")
    L.write_table("w", "t", [out], create_workspace_if_missing=True,
                  source={"kind": "database", "column_types": {"name": "character varying(100)", "amount": "numeric(12,2)"}})
    cols = {c["name"]: c["sql_type"] for c in L.catalog()[0]["tables"][0]["columns"]}
    assert cols == {"name": "varchar(100)", "amount": "numeric(12,2)", "n": "integer"}


def test_df_studio_join_step_and_named_tables():
    import pandas as pd

    sys.path.insert(0, str(REPO / "df-studio"))
    try:
        steps = importlib_tool("df_studio", "steps")
    finally:
        pass
    orders = pd.DataFrame({"id": [1, 2, 3], "customer_id": [10, 20, 99]})
    customers = pd.DataFrame({"id": [10, 20], "name": ["ann", "bob"]})
    token = steps.FRAMES.set({"customers": lambda: customers})
    try:
        out, code = steps.join_table(orders, {"table": "customers", "how": "left", "left_on": "customer_id", "right_on": "id"})
        assert list(out.columns) == ["id", "customer_id", "id_customers", "name"] and out["name"].tolist()[:2] == ["ann", "bob"]
        assert code == "df = df.merge(customers, how='left', left_on='customer_id', right_on='id', suffixes=('', '_customers'))"
        out, _ = steps.custom_code(orders, {"code": "def transform(df):\n    return df.merge(customers, left_on='customer_id', right_on='id')"})
        assert len(out) == 2
        with pytest.raises(ValueError, match="No table named 'nope'"):
            steps.join_table(orders, {"table": "nope", "left_on": "id", "right_on": "id"})
    finally:
        steps.FRAMES.reset(token)


def importlib_tool(package, module):
    import importlib

    try:
        return importlib.import_module(f"{package}.{module}")
    except ImportError:
        return importlib.import_module(module)


def test_df_studio_column_stats_and_types():
    import datetime as dt
    from decimal import Decimal

    import pandas as pd

    sys.path.insert(0, str(REPO / "df-studio"))
    engine = importlib_tool("df_studio", "engine")
    df = pd.DataFrame({"n": [1, 2, None, 4], "s": ["a", "b", "b", None], "d": [dt.date(2026, 1, i) for i in range(1, 5)],
                       "m": [Decimal("1.50")] * 4, "f": [True, False, True, True]})
    assert {c: engine.sql_type(df[c]) for c in df} == {"n": "double", "s": "varchar", "d": "date", "m": "numeric", "f": "boolean"}
    st = engine.column_stats(df)
    assert (st["n"]["nulls"], st["n"]["distinct"], st["n"]["min"], st["n"]["max"]) == (1, 3, 1.0, 4.0)
    assert st["s"] == {"rows": 4, "nulls": 1, "null_pct": 25.0, "distinct": 2} and "mean" not in st["f"]

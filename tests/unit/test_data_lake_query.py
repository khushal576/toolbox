"""Roadmap L3: SQL over Vault Data (data-lake/query.py). Needs DuckDB — run inside the container:
    docker cp tests toolbox-rt-data-1:/tmp/tests && docker exec -w /tmp toolbox-rt-data-1 python -m pytest /tmp/tests/unit/test_data_lake_query.py -q
"""

import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "data-lake"))

duckdb = pytest.importorskip("duckdb", reason="query tests run inside the container")

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
def Q(tmp_path, monkeypatch):
    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    store = SqlStore("lake", sqlite_path=tmp_path / "lake.db", ddl=lake._SCHEMA, backend="sqlite")
    monkeypatch.setattr(lake, "STORE", store)
    monkeypatch.setattr(lake, "_connect", store.connect)
    monkeypatch.setattr(lake, "FILES", FileCache("lake", tmp_path / "lakefiles"))
    monkeypatch.setattr(lake, "_ready", False)
    monkeypatch.setattr(lake, "scoped", lambda plugin: lake.ScopedLake(plugin, "write"))
    q = _tool("query")
    monkeypatch.setattr(q, "STORE", SqlStore("data_lake", sqlite_path=tmp_path / "q.db", ddl=q._SCHEMA, backend="sqlite"))
    monkeypatch.setattr(q, "RESULTS", FileCache("data-lake-results", tmp_path / "results"))
    monkeypatch.setattr(q, "_ready", False)

    def table(ws, name, sql):
        out = tmp_path / f"{ws}_{name}.parquet"
        con = duckdb.connect()
        con.execute(f"COPY ({sql}) TO '{out}' (FORMAT PARQUET)")
        con.close()
        lake.write_table(ws, name, [out], create_workspace_if_missing=True)

    table("sales", "orders", "SELECT i AS order_id, i % 3 AS customer_id, i * 10 AS amount FROM range(30) t(i)")
    table("crm", "customers", "SELECT * FROM (VALUES (0, 'ann'), (1, 'bob'), (2, 'cy')) v(customer_id, name)")
    table("other", "customers", "SELECT 1 AS x")
    return q


def run(q, sql, **kw):
    return q.execute(q.new_id(), q.analyse(sql), **kw)


def test_join_across_workspaces_pages_and_csv(Q, tmp_path):
    r = run(Q, "SELECT c.name, sum(o.amount) AS total FROM sales.orders o JOIN crm.customers c USING (customer_id) "
               "GROUP BY 1 ORDER BY 1;")
    assert (r["state"], r["row_count"], [c["name"] for c in r["columns"]]) == ("done", 3, ["name", "total"])
    assert r["tables"] == ["crm.customers", "sales.orders"]
    assert Q.page(r["id"], 0, 10)["rows"] == [["ann", 1350], ["bob", 1450], ["cy", 1550]]
    assert Q.page(r["id"], 2, 10)["rows"] == [["cy", 1550]]
    assert Q.export_csv(r["id"], tmp_path / "x.csv").read_text().splitlines()[:2] == ["name,total", "ann,1350"]
    assert Q.history()[0]["id"] == r["id"]


def test_decimals_reach_the_page_as_numbers_when_exact(Q):
    r = run(Q, "SELECT 31320.41::DECIMAL(38,2) AS money, 12345678901234567.25::DECIMAL(38,2) AS huge, "
               "sum(order_id) AS whole FROM sales.orders")
    assert Q.page(r["id"])["rows"] == [[31320.41, "12345678901234567.25", 435]]


def test_unqualified_ctes_and_generators(Q):
    assert Q.page(run(Q, "SELECT count(*) FROM orders")["id"])["rows"] == [[30]]   # only one workspace has it
    with pytest.raises(Q.QueryError, match="several workspaces"):
        Q.analyse("SELECT * FROM customers")
    r = run(Q, "WITH big AS (SELECT * FROM sales.orders WHERE amount > 250) SELECT count(*) FROM big, range(2)")
    assert Q.page(r["id"])["rows"] == [[8]]


@pytest.mark.parametrize("sql,msg", [
    ("DELETE FROM sales.orders", "Only SELECT"),
    ("SELECT 1; SELECT 2", "one statement"),
    ("SELECT * FROM read_csv('/etc/passwd')", "read_csv"),
    ("SELECT * FROM '/etc/passwd'", "files can't be read"),
    ("SELECT * FROM (SELECT * FROM read_text('/proc/self/environ'))", "read_text"),
    ("SELECT * FROM sales.nope", "doesn't exist"),
    ("ATTACH '/tmp/x.db'", "Only SELECT"),
    ("SELECT * FROM memory.sales.orders", "three parts"),
    ("CREATE TABLE Bad-Name.x AS SELECT 1", "syntax error"),
])
def test_refused(Q, sql, msg):
    with pytest.raises(Q.QueryError, match=msg):
        Q.analyse(sql)


def test_create_table_as_and_save_result(Q):
    r = run(Q, "CREATE TABLE marts.big_orders AS SELECT * FROM sales.orders WHERE amount >= 200")
    t = lake.get_table("marts", "big_orders")
    assert r["saved_as"] == "marts.big_orders" and t["row_count"] == 10 and t["source"]["kind"] == "query"
    with pytest.raises(Q.QueryError, match="already exists"):
        run(Q, "CREATE TABLE marts.big_orders AS SELECT 1 AS x")
    run(Q, "CREATE OR REPLACE TABLE marts.big_orders AS SELECT 1 AS x")
    assert lake.get_table("marts", "big_orders")["row_count"] == 1
    r = run(Q, "SELECT * FROM crm.customers")
    assert Q.save_as_table(r["id"], "marts", "cust")["row_count"] == 3 and Q.get(r["id"])["saved_as"] == "marts.cust"


def test_explain_failure_timeout_and_stop(Q):
    r = run(Q, "EXPLAIN SELECT * FROM sales.orders")
    assert [c["name"] for c in r["columns"]] == ["explain_key", "explain_value"]
    qid = Q.new_id()
    with pytest.raises(Q.QueryError, match="not_a_col"):
        Q.execute(qid, Q.analyse("SELECT not_a_col FROM sales.orders"))
    assert Q.get(qid)["state"] == "failed"
    slow = "SELECT count(*) FROM range(1000000000) a, range(1000) b WHERE a.range + b.range = -1"
    with pytest.raises(Q.QueryError, match="longer than"):
        run(Q, slow, timeout=1)
    stop = threading.Event()
    threading.Timer(0.5, stop.set).start()
    with pytest.raises(Q.QueryError, match="Stopped"):
        run(Q, slow, cancel=stop)


def test_saved_queries(Q):
    a = Q.save_query("top customers", "SELECT 1;")
    b = Q.save_query("top customers", "SELECT 2")  # same name = update
    assert a["id"] == b["id"] and [s["sql"] for s in Q.list_saved()] == ["SELECT 2"]
    Q.delete_saved(a["id"])
    assert Q.list_saved() == []

"""Roadmap L1: the lake catalog (core/lake.py) on SQLite + local files. Needs DuckDB — run inside the container:
    docker cp tests toolbox-rt-data-1:/tmp/tests && docker exec -w /tmp toolbox-rt-data-1 python -m pytest /tmp/tests/unit/test_lake.py -q
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

duckdb = pytest.importorskip("duckdb")

from core import lake  # noqa: E402
from core.state.filecache import FileCache  # noqa: E402
from core.state.sqlstore import SqlStore  # noqa: E402


@pytest.fixture
def L(tmp_path, monkeypatch):
    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    store = SqlStore("lake", sqlite_path=tmp_path / "lake.db", ddl=lake._SCHEMA, backend="sqlite")
    monkeypatch.setattr(lake, "STORE", store)
    monkeypatch.setattr(lake, "_connect", store.connect)
    monkeypatch.setattr(lake, "FILES", FileCache("lake", tmp_path / "files"))
    monkeypatch.setattr(lake, "_ready", False)
    return lake


def parquet(tmp_path, name, sql):
    out = tmp_path / f"{name}.parquet"
    con = duckdb.connect()
    con.execute(f"COPY ({sql}) TO '{out}' (FORMAT PARQUET)")
    con.close()
    return out


def test_create_describe_preview(L, tmp_path):
    L.create_workspace("sales", "Q3 numbers")
    f = parquet(tmp_path, "o", "SELECT i AS id, 'n' || i AS name FROM range(1000) t(i)")
    t = L.write_table("sales", "orders", [f], source={"kind": "upload", "file": "orders.csv"})
    assert (t["full_name"], t["row_count"], t["version"], t["parts"]) == ("sales.orders", 1000, 1, 1)
    assert [c["name"] for c in t["columns"]] == ["id", "name"] and t["source"]["file"] == "orders.csv"
    p = L.preview("sales", "orders", 3)
    assert p["columns"] == ["id", "name"] and p["rows"] == [[0, "n0"], [1, "n1"], [2, "n2"]]
    w = L.list_workspaces()[0]
    assert (w["name"], w["tables"], w["row_count"]) == ("sales", 1, 1000)


def test_create_refuses_existing_append_adds_overwrite_replaces(L, tmp_path):
    a = parquet(tmp_path, "a", "SELECT i AS id FROM range(10) t(i)")
    b = parquet(tmp_path, "b", "SELECT i AS id, 'x' AS extra FROM range(5) t(i)")
    L.write_table("ws", "t", [a], create_workspace_if_missing=True)
    with pytest.raises(L.LakeError, match="already exists"):
        L.write_table("ws", "t", [a])
    t = L.write_table("ws", "t", [b], mode="append")
    assert (t["row_count"], t["parts"], [c["name"] for c in t["columns"]]) == (15, 2, ["id", "extra"])
    assert len(L.local_files("ws", "t")) == 2 and L.preview("ws", "t", 100)["rows"][0] == [0, None]
    t = L.write_table("ws", "t", [a], mode="overwrite")
    assert (t["row_count"], t["version"], t["parts"]) == (10, 2, 1)
    names = sorted(p.name for p in L.FILES.local_dir.iterdir())
    assert all(".v2." in n for n in names), names  # version 1's files are gone
    assert [h["action"] for h in L.table_history("ws", "t")] == ["overwrite", "append", "create"]


def test_append_with_different_types_is_refused(L, tmp_path):
    L.write_table("ws", "t", [parquet(tmp_path, "a", "SELECT 1 AS id")], create_workspace_if_missing=True)
    with pytest.raises(L.LakeError, match="column types differ"):
        L.write_table("ws", "t", [parquet(tmp_path, "b", "SELECT 'x' AS id")], mode="append")


def test_new_workspace_created_concurrently_is_fine(L, tmp_path, monkeypatch):
    real = L.create_workspace

    def racing(name, description=""):  # another worker process got there first
        real(name, description)
        raise RuntimeError('duplicate key value violates unique constraint "workspaces_name_key"')

    monkeypatch.setattr(L, "create_workspace", racing)
    t = L.write_table("new_ws", "t", [parquet(tmp_path, "x", "SELECT 1 AS v")], create_workspace_if_missing=True)
    assert t["full_name"] == "new_ws.t"
    monkeypatch.setattr(L, "create_workspace", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError, match="db down"):
        L.write_table("other_ws", "t", [parquet(tmp_path, "y", "SELECT 1 AS v")], create_workspace_if_missing=True)


def test_names_rename_move_drop(L, tmp_path):
    for bad in ("Sales", "1abc", "a-b", "", "x" * 64):
        with pytest.raises(L.LakeError):
            L.create_workspace(bad)
    assert L.safe_name("Orders 2026 (final).CSV") == "orders_2026_final_csv" and L.safe_name("2026") == "t_2026"
    L.create_workspace("a")
    L.create_workspace("b")
    f = parquet(tmp_path, "x", "SELECT 1 AS v")
    L.write_table("a", "t", [f])
    t = L.rename_table("a", "t", new_name="t2", new_workspace="b")
    assert t["full_name"] == "b.t2" and L.preview("b", "t2")["rows"] == [[1]]  # files didn't move
    with pytest.raises(L.NotFound):
        L.get_table("a", "t")
    L.drop_table("b", "t2")
    assert L.list_tables("b") == [] and not any(L.FILES.local_dir.iterdir())


def test_workspace_with_tables_is_protected(L, tmp_path):
    L.write_table("w", "t", [parquet(tmp_path, "x", "SELECT 1 AS v")], create_workspace_if_missing=True)
    with pytest.raises(L.LakeError, match="still has 1 table"):
        L.delete_workspace("w")
    assert L.delete_workspace("w", drop_tables=True) == 1 and L.list_workspaces() == []
    L.update_workspace  # noqa: B018 - exists
    L.create_workspace("old")
    assert L.update_workspace("old", new_name="new", description="d")["name"] == "new"


def test_scopes(L, tmp_path):
    L.create_workspace("w")
    reader, writer, none = L.ScopedLake("t", "read"), L.ScopedLake("t", "write"), L.ScopedLake("t", "none")
    assert reader.list_workspaces()[0]["name"] == "w"
    with pytest.raises(L.ScopeError, match="data: write"):
        reader.create_workspace("x")
    with pytest.raises(L.ScopeError):
        none.list_workspaces()
    writer.write_table("w", "t", [parquet(tmp_path, "x", "SELECT 1 AS v")])
    assert reader.preview("w", "t")["rows"] == [[1]]


def test_vault_datasets_are_imported_once(L, tmp_path, monkeypatch):
    from core import vault

    csv = tmp_path / "ds.csv"
    csv.write_text("a,b\n1,x\n2,y\n")
    monkeypatch.setattr(vault, "list_secrets", lambda kind=None: [
        {"id": "d1", "name": "Sales Export 2026", "kind": "duckdb_result", "has_data": True},
        {"id": "c1", "name": "a connection", "kind": "postgres_connection", "has_data": False}])

    def load(sid):
        p = tmp_path / f"copy_{sid}.csv"
        p.write_bytes(csv.read_bytes())
        return p

    monkeypatch.setattr(vault, "load_dataset_file", load)
    r = L.import_vault_datasets()
    assert r["imported"] == [{"dataset": "Sales Export 2026", "table": "datasets.sales_export_2026"}] and not r["failed"]
    t = L.get_table("datasets", "sales_export_2026")
    assert t["row_count"] == 2 and t["source"]["dataset_id"] == "d1"
    assert L.import_vault_datasets() == r                      # automatic import happens once
    assert L.import_vault_datasets(again=True)["imported"] == []  # already imported → skipped

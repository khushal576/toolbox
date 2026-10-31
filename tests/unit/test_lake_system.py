"""Roadmap L6: the built-in `system` workspace (core/lake.py SYSTEM_WORKSPACE). Needs DuckDB — run inside the container:
    docker cp tests toolbox-rt-data-1:/tmp/tests && docker exec -w /tmp toolbox-rt-data-1 python -m pytest /tmp/tests/unit/test_lake_system.py -q
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

duckdb = pytest.importorskip("duckdb", reason="L6 tests run inside the container")
pytest.importorskip("pyarrow")

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


def _parquet(tmp_path, name="t"):
    out = tmp_path / f"{name}.parquet"
    con = duckdb.connect()
    con.execute(f"COPY (SELECT i AS id FROM range(5) t(i)) TO '{out}' (FORMAT PARQUET)")
    con.close()
    return out


def test_system_exists_without_creating_it(L):
    assert [w["name"] for w in L.list_workspaces()] == ["system"]
    assert [w["name"] for w in L.list_workspaces()] == ["system"]      # listing twice doesn't duplicate or fail
    assert [w["name"] for w in L.catalog()] == ["system"]


def test_system_cannot_be_renamed_or_deleted(L):
    L.list_workspaces()
    with pytest.raises(L.LakeError, match="can't be renamed"):
        L.update_workspace("system", new_name="other")
    assert L.update_workspace("system", description="the default")["description"] == "the default"   # description is fine
    with pytest.raises(L.LakeError, match="can't be deleted"):
        L.delete_workspace("system")
    with pytest.raises(L.LakeError, match="can't be deleted"):
        L.delete_workspace("system", drop_tables=True)


def test_empty_workspace_defaults_to_system(L, tmp_path):
    t = L.write_table("", "from_parquet", [_parquet(tmp_path)])
    assert t["full_name"] == "system.from_parquet" and t["row_count"] == 5
    csv = tmp_path / "in.csv"
    csv.write_text("a,b\n1,x\n2,y\n")
    t = L.import_file("", "from_csv", csv)
    assert t["full_name"] == "system.from_csv" and t["row_count"] == 2
    assert sorted(x["name"] for x in L.list_tables("system")) == ["from_csv", "from_parquet"]


def test_explicit_system_creates_nothing_else_and_other_workspaces_still_need_to_exist(L, tmp_path):
    L.write_table("system", "t1", [_parquet(tmp_path)])
    with pytest.raises(L.NotFound):
        L.write_table("nope", "t2", [_parquet(tmp_path, "t2")])
    assert [w["name"] for w in L.list_workspaces()] == ["system"]


def test_tables_of_system_can_be_dropped_and_workspace_stays(L, tmp_path):
    L.write_table("system", "t1", [_parquet(tmp_path)])
    L.drop_table("system", "t1")
    assert L.list_tables("system") == []
    assert [w["name"] for w in L.list_workspaces()] == ["system"]

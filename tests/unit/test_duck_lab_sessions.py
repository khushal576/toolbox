"""Duck Lab session persistence (roadmap B3) against the in-memory backend. "Another worker" is simulated by
dropping this process's local working copies, which forces a rebuild from the stored session.

Needs duckdb (in the Toolbox image, not necessarily on the host): skipped when it isn't installed. Run in the
container with:  docker cp tests toolbox-toolbox-1:/tmp/tests && \
                 docker compose exec toolbox python -m pytest /tmp/tests/unit/test_duck_lab_sessions.py -q
"""

import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("duckdb")

REPO = Path(__file__).resolve().parents[2]
DUCK_DIR = REPO / "duck-lab" if (REPO / "duck-lab").is_dir() else Path("/app/duck_lab")


@pytest.fixture
def eng(tmp_path, monkeypatch):
    for v in ("TOOLBOX_REDIS_URL", "TOOLBOX_S3_ENDPOINT"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("DUCK_LAB_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.syspath_prepend(str(REPO if (REPO / "core").is_dir() else Path("/app")))
    monkeypatch.syspath_prepend(str(DUCK_DIR))
    for m in ("engine", "session_store"):
        sys.modules.pop(m, None)
    engine = importlib.import_module("engine")
    engine.BACKEND.root = tmp_path / "store"
    assert engine.BACKEND.name == "memory"
    yield engine
    for local in list(engine._locals.values()):
        local.close()
    for m in ("engine", "session_store"):
        sys.modules.pop(m, None)


def other_worker(engine):
    """Forget every local working copy, like a different process seeing the session for the first time."""
    for sid in list(engine._locals):
        engine._drop_local(sid)


def upload(engine, sid, name, text):
    s = engine.get_or_create_session(sid)
    path = s.data_dir / f"tmp_{name}"
    path.write_text(text, encoding="utf-8")
    return engine.load_file(s, path, name)


def test_tables_survive_a_new_worker(eng):
    upload(eng, "s1", "people.csv", "id,name\n1,ann\n2,bob\n3,cy\n")
    other_worker(eng)
    s = eng.get_or_create_session("s1")
    assert list(s.tables) == ["people"] and s.tables["people"].row_count == 3
    assert eng.preview_table(s, "people")["rows"][0] == [1, "ann"]


def test_result_pages_and_exports_from_another_worker(eng):
    upload(eng, "s1", "people.csv", "id,name\n1,ann\n2,bob\n3,cy\n")
    out = eng.run_query(eng.get_or_create_session("s1"), "SELECT * FROM people WHERE id > 1 ORDER BY id")
    assert out["total_rows"] == 2
    other_worker(eng)
    s = eng.get_or_create_session("s1")
    assert eng.fetch_page(s, 1, 10)["rows"] == [[3, "cy"]]
    exported = eng.export_result(s, "csv")
    assert exported.read_text().splitlines() == ["id,name", "2,bob", "3,cy"]


def test_new_result_replaces_old_one(eng):
    upload(eng, "s1", "t.csv", "a\n1\n2\n")
    s = eng.get_or_create_session("s1")
    eng.run_query(s, "SELECT a FROM t")
    first = s.result["object_key"]
    eng.run_query(eng.get_or_create_session("s1"), "SELECT a * 10 AS b FROM t")
    assert not Path(first).exists()  # old result deleted from the store
    other_worker(eng)
    assert eng.fetch_page(eng.get_or_create_session("s1"), 0, 5)["rows"] == [[10], [20]]


def test_remove_table_and_reset_persist(eng):
    upload(eng, "s1", "a.csv", "x\n1\n")
    upload(eng, "s1", "b.csv", "y\n2\n")
    eng.remove_table(eng.get_or_create_session("s1"), "a")
    other_worker(eng)
    s = eng.get_or_create_session("s1")
    assert list(s.tables) == ["b"]
    import duckdb
    with pytest.raises(duckdb.CatalogException):  # the removed table's view is gone on the new worker too
        s.con.execute("SELECT * FROM a").fetchall()
    eng.reset_session(s)
    assert eng.get_or_create_session("s1").tables == {}


def test_xml_is_stored_as_parquet_and_rebuilds(eng):
    s = eng.get_or_create_session("s1")
    eng.load_xml(s, "<rows><r><id>1</id><v>a</v></r><r><id>2</id><v>b</v></r></rows>", "data.xml")
    other_worker(eng)
    s = eng.get_or_create_session("s1")
    assert s.tables["data"].format == "xml" and s.tables["data"].local_name.endswith(".parquet")
    assert eng.run_query(s, "SELECT count(*) AS n FROM data")["rows"] == [[2]]


def test_sessions_are_isolated(eng):
    upload(eng, "s1", "only_s1.csv", "a\n1\n")
    assert eng.get_or_create_session("s2").tables == {}

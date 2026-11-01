"""DataFrame Studio HTTP layer (roadmap DF1/DF2): every step endpoint exists and answers the way the page expects.
A route silently dropped from server.py only shows up as a 404 in the browser, so this walks them all once with
FastAPI's TestClient against the in-memory session backend (no Redis / S3 / Postgres)."""

import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MODS = ("server", "engine", "session_store", "steps", "clean_steps", "formula", "templates_store")
CSV = "age,city,score\n20,Delhi,\"1,200\"\n,mumbai,$30\n40,,x\n1000,DELHI,45\n30,pune,\n25,Mumbai,10\n22,,11\n28,pune,12\n31,Delhi,13\n29,goa,14\n"


@pytest.fixture
def client(monkeypatch, tmp_path):
    for v in ("TOOLBOX_REDIS_URL", "TOOLBOX_S3_ENDPOINT", "TOOLBOX_DATABASE_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.syspath_prepend(str(REPO))
    monkeypatch.syspath_prepend(str(REPO / "df-studio"))
    for x in MODS:
        sys.modules.pop(x, None)
    try:
        server = importlib.import_module("server")
    except ImportError as exc:  # e.g. the vault's crypto library isn't installed on this machine
        pytest.skip(f"df-studio server needs the container's libraries: {exc}")
    monkeypatch.setattr(sys.modules["templates_store"], "_STORE_PATH", tmp_path / "templates.json", raising=False)
    c = TestClient(server.app)
    assert c.post("/load", files={"file": ("t.csv", CSV)}).status_code == 200
    yield c
    for x in MODS:
        sys.modules.pop(x, None)


def test_step_check_returns_code_and_warnings_without_adding(client):
    r = client.post("/step/check", json={"type": "cast_type", "params": {"columns": ["score"], "to": "float", "ignore_symbols": True}})
    assert r.status_code == 200
    j = r.json()
    assert j["committed"] is False and "pd.to_numeric" in j["code"] and any("score" in w for w in j["warnings"])
    assert client.get("/session").json()["steps"] == []


def test_add_toggle_move_remove_and_script(client):
    add = client.post("/step", json={"type": "fill_nulls", "params": {"columns": ["age"], "method": "zero"}})
    assert add.status_code == 200 and add.json()["warnings"] and add.json()["steps"][0]["enabled"] is True
    assert client.post("/step", json={"type": "expression", "params": {"text": "age2 = age * 2"}}).status_code == 200
    t = client.post("/step/toggle", json={"index": 1, "enabled": False})
    assert t.status_code == 200 and t.json()["steps"][1]["enabled"] is False
    assert "age2" not in [c["name"] for c in t.json()["columns"]]
    assert "age2" not in client.get("/script").json()["script"]
    assert client.post("/step/toggle", json={"index": 1, "enabled": True}).status_code == 200
    m = client.post("/step/move", json={"index": 1, "direction": "up"})
    assert m.status_code == 200 and [s["type"] for s in m.json()["steps"]] == ["expression", "fill_nulls"]
    assert client.post("/step/move", json={"index": 0, "direction": "up"}).status_code == 400
    rm = client.post("/step/remove", json={"index": 0})
    assert rm.status_code == 200 and len(rm.json()["steps"]) == 1
    assert client.post("/step/remove", json={"index": 9}).status_code == 400
    assert client.post("/step/reset").json()["steps"] == []


def test_refused_toggle_leaves_the_pipeline_alone(client):
    client.post("/step", json={"type": "cast_type", "params": {"columns": ["score"], "to": "float", "ignore_symbols": True}})
    client.post("/step", json={"type": "fill_nulls", "params": {"columns": ["score"], "method": "median"}})
    r = client.post("/step/toggle", json={"index": 0, "enabled": False})
    assert r.status_code == 400 and "Step 2" in r.json()["error"]
    assert [s["enabled"] for s in client.get("/session").json()["steps"]] == [True, True]
    r = client.post("/step/remove", json={"index": 0})
    assert r.status_code == 400 and len(client.get("/session").json()["steps"]) == 2


def test_column_stats_single_column_with_suggestions(client):
    r = client.get("/column-stats", params={"column": "age"})
    j = r.json()
    assert r.status_code == 200 and set(j["stats"]) == {"age"} and j["stats"]["age"]["null_pct"] == 10.0
    assert {s["action"] for s in j["suggest"]} >= {"fill_nulls", "clip_outliers"}
    assert client.get("/column-stats", params={"column": "nope"}).status_code == 400
    assert set(client.get("/column-stats").json()["stats"]) == {"age", "city", "score"}


def test_formula_help_and_errors(client):
    names = {f["name"] for f in client.get("/formula/help").json()["functions"]}
    assert {"where", "coalesce", "round"} <= names
    r = client.post("/step", json={"type": "expression", "params": {"text": "t = __import__('os')"}})
    assert r.status_code == 400 and "error" in r.json()
    assert client.get("/session").json()["steps"] == []


def test_templates_keep_only_turned_on_steps(client):
    client.post("/step", json={"type": "fill_nulls", "params": {"columns": ["age"], "method": "zero"}})
    client.post("/step", json={"type": "expression", "params": {"text": "age2 = age * 2"}})
    client.post("/step/toggle", json={"index": 1, "enabled": False})
    assert client.post("/template/save", json={"name": "t1"}).status_code == 200
    applied = client.post("/template/apply", json={"name": "t1"}).json()
    assert [s["type"] for s in applied["steps"]] == ["fill_nulls"]


# ---- extra tables next to df: read-only view (frame/preview + frame stats) ------------------------------------

@pytest.fixture
def with_frame(client, monkeypatch):
    import pandas as pd

    eng = sys.modules["engine"]
    cust = pd.DataFrame({"customer_id": [1, 2, 3, 4], "name": ["a", "b", None, "d"], "spend": [10.5, 20.0, 30.25, 40.0]})
    monkeypatch.setattr(eng, "lake_frame", lambda ref, limit=None: cust)
    r = client.post("/frames/add", json={"workspace": "crm", "table": "customers"})
    assert r.status_code == 200 and r.json()["added"] == "customers"
    return client


def test_frame_preview_shows_the_added_table_read_only(with_frame):
    r = with_frame.get("/frame/preview", params={"name": "customers"})
    j = r.json()
    assert r.status_code == 200 and j["frame"] == "customers" and j["ref"] == "crm.customers" and j["read_only"] is True
    assert j["row_count"] == 4 and [c["name"] for c in j["columns"]] == ["customer_id", "name", "spend"]
    assert j["columns"][0]["sql_type"] == "bigint" and j["rows"][0]["customer_id"] == 1
    # df is untouched: still the uploaded CSV, no steps added
    s = with_frame.get("/session").json()
    assert [c["name"] for c in s["columns"]] == ["age", "city", "score"] and s["steps"] == []


def test_frame_preview_follows_head_sample_mode(with_frame):
    with_frame.post("/preview-mode", json={"mode": "sample"})
    j = with_frame.get("/frame/preview", params={"name": "customers"}).json()
    assert j["preview_mode"] == "sample" and j["row_count"] == 4


def test_frame_preview_refuses_names_that_are_not_loaded(with_frame):
    for bad in ("nope", "df", "../etc/passwd", "crm.customers"):
        r = with_frame.get("/frame/preview", params={"name": bad})
        assert r.status_code == 400 and "isn't one of the loaded tables" in r.json()["error"]
    assert with_frame.get("/frame/preview", params={"name": "x"}).status_code == 400   # also with no frames at all


def test_column_stats_for_a_frame_uses_that_frame(with_frame):
    j = with_frame.get("/column-stats", params={"frame": "customers"}).json()
    assert set(j["stats"]) == {"customer_id", "name", "spend"} and j["rows"] == 4
    assert j["stats"]["name"]["nulls"] == 1 and j["stats"]["spend"]["max"] == 40.0
    one = with_frame.get("/column-stats", params={"frame": "customers", "column": "spend"}).json()
    assert set(one["stats"]) == {"spend"} and one["suggest"] is not None
    assert with_frame.get("/column-stats", params={"frame": "nope"}).status_code == 400
    # without ?frame= it is still df's own stats
    assert set(with_frame.get("/column-stats").json()["stats"]) == {"age", "city", "score"}

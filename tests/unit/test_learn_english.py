"""Speak English (learn-english): content serving, progress saved in a REAL temporary SQLite-backed SqlStore, merge rules, guards, page rules."""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "learn-english"
sys.path.insert(0, str(REPO))
from core.state.sqlstore import SqlStore  # noqa: E402

H = {"X-Speak-English": "1"}


def _load():
    spec = importlib.util.spec_from_file_location("learn_english_server_t", TOOL / "server.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


srv = _load()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("TOOLBOX_DATABASE_URL", raising=False)
    monkeypatch.setattr(srv, "STORE", SqlStore("learn_english", sqlite_path=tmp_path / "p.db", ddl=srv._SCHEMA))
    monkeypatch.setattr(srv, "_ready", False)
    return TestClient(srv.app)


def test_page_health_and_content_files(client):
    assert client.get("/").status_code == 200 and "Speak English" in client.get("/").text
    assert client.get("/health").json() == {"ok": True, "tool": "learn-english"}
    for path in ["/modules/manifest.js", "/modules/m001.js", "/practice/h001.js", "/cheat/c001.js"]:
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript"), path


def test_only_content_files_are_reachable(client):
    for path in ["/modules/m1.js", "/modules/x.js", "/modules/m999.js", "/ui/index.html", "/modules/..%2Fserver.py",
                 "/practice/m001.js", "/cheat/h001.js", "/tools/validate.js", "/data/progress.db"]:
        assert client.get(path).status_code == 404, path


def test_progress_needs_the_header(client):
    assert client.get("/progress").status_code == 403
    assert client.put("/progress", json={"state": {}}).status_code == 403
    assert client.get("/progress/summary").status_code == 403


def test_empty_then_round_trip(client):
    r = client.get("/progress", headers=H).json()
    assert r["updated_at"] is None and r["state"]["passed"] == {}
    st = {"passed": {"1": True, "2": True}, "scores": {"1": 0.9, "2": 0.85}, "pos": {"3": 7}, "last": 1700000000000,
          "tough": {"2:abc12": {"s": 1, "n": 2}}}
    out = client.put("/progress", headers=H, json={"state": st}).json()
    assert out["state"] == st and out["updated_at"]
    assert client.get("/progress", headers=H).json()["state"] == st


def test_merge_never_loses_a_pass_or_a_better_score(client):
    client.put("/progress", headers=H, json={"state": {"passed": {"1": True, "2": True}, "scores": {"1": 0.95}, "tough": {"1:aa": {"s": 0, "n": 1}}}})
    # an old tab that never saw module 2 and has a worse score, and the learner removed the tough sentence
    out = client.put("/progress", headers=H, json={"state": {"passed": {"1": True}, "scores": {"1": 0.8}, "pos": {"3": 2}, "tough": {}}}).json()["state"]
    assert out["passed"] == {"1": True, "2": True} and out["scores"]["1"] == 0.95
    assert out["tough"] == {} and out["pos"] == {"3": 2}


def test_junk_is_dropped(client):
    st = {"passed": {"1": True, "x": True, "2": "yes", "3": False}, "scores": {"1": 2, "2": True, "3": 0.5, "y": 0.1},
          "pos": {"1": -1, "2": 3, "3": True}, "last": "now", "tough": {"bad id": {"s": 0, "n": 1}, "4:ok1": {"s": "1", "n": 1}, "5:ok2": {"s": 0, "n": 1}},
          "evil": "<script>"}
    out = client.put("/progress", headers=H, json={"state": st}).json()["state"]
    assert out == {"passed": {"1": True}, "scores": {"3": 0.5}, "pos": {"2": 3}, "last": 0, "tough": {"5:ok2": {"s": 0, "n": 1}}}


def test_bad_bodies(client):
    assert client.put("/progress", headers=H, content=b"not json").status_code == 400
    assert client.put("/progress", headers=H, json={"passed": {}}).status_code == 400
    assert client.put("/progress", headers=H, content=b"x" * (srv.MAX_BODY + 1)).status_code == 413


def test_summary_names_the_next_module(client):
    built = sorted(int(p.stem[1:]) for p in (TOOL / "modules").glob("m[0-9][0-9][0-9].js"))
    s = client.get("/progress/summary", headers=H).json()
    assert s["built"] == built and s["next"] == built[0] and s["all_built_passed"] is False
    client.put("/progress", headers=H, json={"state": {"passed": {str(i): True for i in built[:3]}, "scores": {"1": 0.8}}})
    s = client.get("/progress/summary", headers=H).json()
    assert s["passed"] == built[:3] and s["next"] == built[3]
    client.put("/progress", headers=H, json={"state": {"passed": {str(i): True for i in built}}})
    assert client.get("/progress/summary", headers=H).json()["all_built_passed"] is True


def test_page_rules():
    page = (TOOL / "ui" / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"fetch\(\s*[\"'`]/", page)                               # relative paths only (mounted under /tools/learn-english/)
    assert page.count('fetch("progress"') == 2 and "X-Speak-English" in page        # every progress call carries the header
    assert not re.search(r"""(?:src|href)=["']https?://""", page)                 # no outside scripts or styles
    assert "dist/speak-english.html" not in page                                  # the offline download copy is gone (progress lives in Toolbox)
    assert "Start Module" not in page or "id=\"go\"" in page


def test_course_content_is_valid():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    r = subprocess.run(["node", str(TOOL / "tools" / "validate.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "All good" in r.stdout, r.stdout + r.stderr


def test_docker_image_carries_the_content():
    d = (REPO / "Dockerfile").read_text()
    for folder in ("ui", "modules", "practice", "cheat"):
        assert f"COPY learn-english/{folder}/ ./learn_english/{folder}/" in d

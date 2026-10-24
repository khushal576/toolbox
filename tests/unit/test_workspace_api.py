"""The workspace API in main.py: live on/off switches (roadmap A4). No tool code is imported here."""

import importlib
import sys
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    ws_file = tmp_path / "workspace.yaml"
    monkeypatch.setenv("TOOLBOX_WORKSPACE_FILE", str(ws_file))
    monkeypatch.syspath_prepend(str(REPO))
    sys.modules.pop("main", None)
    main = importlib.import_module("main")  # fresh import picks up the temp workspace file
    yield TestClient(main.app), ws_file
    sys.modules.pop("main", None)


def status(c):
    return {p["name"]: p for p in c.get("/api/workspace/status").json()["plugins"]}


def test_home_is_the_workspace_and_lists_tools(app_client):
    c, _ = app_client
    r = c.get("/")
    assert r.status_code == 200 and 'id="ws-data"' in r.text and 'href="/tools/datadiff-pro/"' in r.text
    # rendering home imports nothing (custom-app samples in plugins/ ship disabled)
    assert all(p["state"] == "not_loaded" for p in status(c).values() if p["kind"] == "python")


def test_toggle_off_and_on_is_live_and_saved(app_client):
    c, ws_file = app_client
    r = c.post("/api/workspace/plugins/encode-decode", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False and "uses no memory" in r.json()["message"]
    assert yaml.safe_load(ws_file.read_text())["enabled"] == {"encode-decode": False}
    assert status(c)["encode-decode"]["state"] == "disabled"
    off = c.get("/tools/encode-decode/")
    assert off.status_code == 404 and "turned off" in off.text  # no restart needed
    assert 'href="/tools/encode-decode/"' not in c.get("/").text

    r = c.post("/api/workspace/plugins/encode-decode", json={"enabled": True})
    assert r.status_code == 200 and r.json()["plugin"]["name"] == "encode-decode"
    assert status(c)["encode-decode"]["state"] == "not_loaded"  # back on, still lazy
    assert yaml.safe_load(ws_file.read_text())["enabled"] == {"encode-decode": True}


def test_toggle_rejects_unknown_tool_and_bad_body(app_client):
    c, _ = app_client
    assert c.post("/api/workspace/plugins/no-such-tool", json={"enabled": False}).status_code == 404
    assert c.post("/api/workspace/plugins/encode-decode", json={"enabled": "maybe"}).status_code == 422

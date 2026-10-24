"""Workspace status endpoint and lazy loading (roadmap A3)."""

from conftest import mounted_tools, request


def status():
    r = request("GET", "/api/workspace/status")
    assert r.status == 200 and r.ctype == "application/json"
    return r.json()


def test_status_lists_every_tool_and_nothing_failed():
    s = status()
    by_name = {p["name"]: p for p in s["plugins"]}
    assert set(mounted_tools()) <= set(by_name)
    assert not [n for n, p in by_name.items() if p["state"] == "failed"], s
    assert s["manifest_errors"] == [] and s["workspace_errors"] == []


def test_tool_is_loaded_after_its_first_request():
    tool = "encode-decode"
    assert request("GET", f"/tools/{tool}/").status == 200
    p = {p["name"]: p for p in status()["plugins"]}[tool]
    assert p["state"] == "loaded" and p["enabled"] is True

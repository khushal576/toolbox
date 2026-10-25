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


def test_overview_has_every_section():
    """Roadmap E1: the Status page's data."""
    r = request("GET", "/api/workspace/overview")
    assert r.status == 200
    o = r.json()
    names = {c["service"] for c in o["containers"]["containers"]}
    assert {"toolbox", "rt-data", "postgres", "redis", "worker"} <= names, names
    assert o["state"].get("ok") is True and "per_tool" in o["jobs"] and "postgres" in o["storage"]
    assert isinstance(o["attention"], list)


def test_traffic_counters_errors_logs_and_alerts():
    """Roadmap E2/E3: the gateway counts tool traffic (flushed to Redis every 5 s), keeps recent errors, shows logs."""
    import time

    for _ in range(3):
        assert request("GET", "/tools/subnet-calc/").status == 200
    time.sleep(6)  # the request may have landed on another gateway worker: wait for its flush
    m = request("GET", "/api/workspace/metrics").json()
    assert m["tools"]["subnet-calc"]["hour"]["req"] >= 3 and len(m["tools"]["subnet-calc"]["series"]) == 60
    assert "errors" in request("GET", "/api/workspace/errors").json()
    names = [c["name"] for c in request("GET", "/api/workspace/overview").json()["containers"]["containers"]]
    gw = next(n for n in names if n.endswith("-toolbox-1"))
    log = request("GET", f"/api/workspace/logs/{gw}?lines=20")
    assert log.status == 200 and log.body.strip()
    assert request("GET", "/api/workspace/logs/not-a-toolbox-container").status == 404
    a = request("GET", "/api/workspace/alerts").json()
    assert {"items", "errors", "warnings"} <= set(a)

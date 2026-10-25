"""State services are reachable from Toolbox (roadmap B1)."""

from conftest import request


def test_state_health_all_ok():
    r = request("GET", "/api/state/health", timeout=30)
    assert r.status == 200
    h = r.json()
    assert h["ok"] is True, h
    assert h["redis"]["aof_enabled"] is True, "Redis must persist (AOF) so restarts keep queued jobs"


def test_a_job_worker_is_listening():
    h = request("GET", "/api/state/health", timeout=30).json()
    assert h["jobs"]["ok"] is True, h["jobs"]
    assert h["jobs"]["workers"] >= 1

"""Roadmap E1: the Status page's 'attention' rules (pure function) and job-id → tool mapping."""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins.overview import _tool_of, attention  # noqa: E402


def c(name, service, state="running", health="healthy", **kw):
    return {"name": name, "service": service, "state": state, "health": health, "restarts": 0, **kw}


def test_all_fine_means_nothing_to_look_at():
    o = {"containers": {"containers": [c("x-rt-light-1", "rt-light")]}, "tools": {"plugins": []},
         "state": {"postgres": {"ok": True}, "vault": {"ok": True}}, "jobs": {"waiting": 0}}
    assert attention(o) == []


def test_sleeping_and_scaled_down_containers_are_normal_but_stopped_ones_are_not():
    o = {"on_demand_services": ["rt-latex"], "pool_services": ["rt-datadiff"],
         "containers": {"containers": [c("x-rt-latex-1", "rt-latex", "exited"), c("x-rt-datadiff-4", "rt-datadiff", "exited"),
                                       c("x-rt-light-1", "rt-light", "exited", exit_code=137)]}}
    assert [a["text"] for a in attention(o)] == ["x-rt-light-1 is stopped (exit code 137)"]


def test_problems_are_listed():
    now = datetime.now(timezone.utc).isoformat()
    o = {"containers": {"containers": [c("a", "a", health="unhealthy"), c("b", "b", restarts=9),
                                       c("m", "m", mem=900, mem_limit=1000)]},
         "tools": {"plugins": [{"title": "LaTeX", "state": "failed", "error": "ImportError"}]},
         "state": {"redis": {"ok": False, "error": "down"}, "vault": {"ok": True, "warning": "key on volume"}},
         "jobs": {"waiting": 7, "recent_failures": [{"ended_at": now}, {"ended_at": "2020-01-01T00:00:00"}, {"ended_at": None}]}}
    texts = [a["text"] for a in attention(o)]
    assert "a is unhealthy" in texts and "b keeps restarting (9 restarts)" in texts
    assert "m uses 90% of its memory limit" in texts and "LaTeX failed to load: ImportError" in texts
    assert "redis: down" in texts and "vault: key on volume" in texts
    assert "7 background jobs are waiting for a worker" in texts
    assert "1 background job(s) crashed in the last 24 h" in texts  # old/undated crashes don't nag


def test_job_ids_map_to_tools():
    assert _tool_of("data-syncer-abc123-1f2e3d4c") == "data-syncer"
    assert _tool_of("ssh-sftp-0123456789abcdef-deadbeef") == "ssh-sftp"
    assert _tool_of("datadiff-xyz-00ff00ff") == "datadiff"

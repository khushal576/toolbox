"""core.jobs pieces that need no Redis (roadmap B4), and data-syncer's thread fallback. The queue path is verified
live (sync in the worker surviving a web restart, stop, worker crash + resume) — see the B4 handoff."""

import importlib
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core import jobs  # noqa: E402


class FakeChannel:
    def __init__(self):
        self.calls, self.flag = 0, False

    def stop_requested(self):
        self.calls += 1
        return self.flag


def test_stop_flag_caches_redis_checks_and_latches():
    ch = FakeChannel()
    f = jobs.StopFlag(ch)
    assert f.is_set() is False and all(f.is_set() is False for _ in range(100))
    assert ch.calls == 1  # 101 checks within a second → one Redis call
    ch.flag = True
    f._checked = 0.0
    assert f.is_set() is True
    ch.flag = False
    assert f.is_set() is True  # once stopped, stays stopped


def test_stop_flag_wait_returns_early_when_set():
    ch = FakeChannel()
    f = jobs.StopFlag(ch)
    threading.Timer(0.3, lambda: setattr(ch, "flag", True)).start()
    t0 = time.monotonic()
    assert f.wait(5) is True and time.monotonic() - t0 < 2.5


def test_jobs_unavailable_without_redis_url(monkeypatch):
    monkeypatch.delenv("TOOLBOX_REDIS_URL", raising=False)
    assert jobs.available() is False


def test_data_syncer_falls_back_to_threads_without_redis(monkeypatch, tmp_path):
    monkeypatch.delenv("TOOLBOX_REDIS_URL", raising=False)
    monkeypatch.syspath_prepend(str(REPO / "data-syncer"))
    for m in ("runner", "engine", "state_store", "connections", "sync_ops"):
        sys.modules.pop(m, None)
    try:
        runner = importlib.import_module("runner")
    except ImportError as exc:  # psycopg etc. missing on this host
        pytest.skip(f"data-syncer deps not installed here: {exc}")
    assert runner.MODE == "thread"
    v = runner.view("nope")
    assert v.running is False and v.logs == []

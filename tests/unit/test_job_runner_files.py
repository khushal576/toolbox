"""core.jobs.runner (thread mode + progress mirroring) and core.state.filecache (roadmap B5). The queue mode and
S3 storage are verified live (dump/restore in the worker across a web restart) — see the B5 handoff."""

import os
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core.jobs.runner import AlreadyRunning, JobRunner, _RedisProgress  # noqa: E402
from core.state.filecache import RECENT_SECONDS, FileCache  # noqa: E402


# ---- JobRunner (thread mode) ------------------------------------------------------------------------------

def _body(ctx, gate, out):
    ctx.log("info", "working")
    ctx.progress.update(done=0, total=3)
    for i in range(3):
        ctx.progress["done"] = i + 1
    gate.wait(5)
    out["cancelled"] = ctx.cancel.is_set()


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_thread_mode_runs_logs_progress_and_rejects_a_second_start():
    r = JobRunner("t-tool", log_size=5, mode="thread")
    gate, out = threading.Event(), {}
    r.start("k1", "dump", _body, gate, out)
    assert _wait(lambda: r.view("k1")["progress"].get("done") == 3)
    v = r.view("k1")
    assert v["running"] and v["kind"] == "dump" and [x["msg"] for x in v["logs"]] == ["dump started", "working"]
    with pytest.raises(AlreadyRunning):
        r.start("k1", "dump", _body, gate, out)
    assert r.stop("k1") is True
    assert r.view("k1")["stopping"] is True
    gate.set()
    assert _wait(lambda: not r.is_running("k1"))
    assert out["cancelled"] is True and r.view("k1")["finished_at"]
    assert r.stop("k1") is False  # nothing running


def test_thread_mode_reports_an_unexpected_failure_and_an_empty_key():
    r = JobRunner("t-tool", mode="thread")
    assert r.view("nope") == {"running": False, "queued": False, "stopping": False, "kind": None, "logs": [],
                              "progress": {}, "error": None, "started_at": None, "finished_at": None}

    def boom(ctx):
        raise RuntimeError("bad")

    r.start("k2", "restore", boom)
    assert _wait(lambda: not r.is_running("k2"))
    assert r.view("k2")["error"] == "bad" and "unexpected failure: bad" in r.view("k2")["logs"][-1]["msg"]


def test_runner_is_thread_mode_without_redis(monkeypatch):
    monkeypatch.delenv("TOOLBOX_REDIS_URL", raising=False)
    assert JobRunner("t-tool").mode == "thread"


def test_redis_progress_is_throttled_and_flushed():
    class Ch:
        def __init__(self):
            self.writes = []

        def update_meta(self, **kw):
            self.writes.append(kw["progress"])

    ch = Ch()
    p = _RedisProgress(ch, every=60)
    p.update(done=0, total=100)
    for i in range(100):
        p["done"] = i + 1
    assert len(ch.writes) == 1  # 101 changes within the window → one write
    p.flush()
    assert ch.writes[-1] == {"done": 100, "total": 100} and dict(p) == {"done": 100, "total": 100}


# ---- FileCache ----------------------------------------------------------------------------------------------

class FakeObjects:
    def __init__(self):
        self.data = {}

    def key(self, tool, *parts):
        return "/".join([tool, *parts])

    def put_file(self, k, fh):
        self.data[k] = fh.read()

    def get_to(self, k, fh):
        if k not in self.data:
            return False
        fh.write(self.data[k])
        return True

    def exists(self, k):
        return k in self.data

    def delete(self, k):
        self.data.pop(k, None)

    def delete_prefix(self, prefix):
        gone = [k for k in self.data if k.startswith(prefix)]
        for k in gone:
            del self.data[k]
        return len(gone)


def _cache(tmp_path, budget_mb=1):
    fc = FileCache("t-tool", tmp_path / "files", budget_mb=budget_mb)
    fc._objects = FakeObjects()
    fc.local_dir.mkdir(parents=True)
    return fc


def test_local_only_without_s3(monkeypatch, tmp_path):
    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    fc = FileCache("t-tool", tmp_path, budget_mb=1)
    assert not fc.remote
    (tmp_path / "a1.dump").write_bytes(b"x")
    fc.publish("a1", tmp_path / "a1.dump")  # no-op
    assert fc.fetch("a1", "a1.dump") == tmp_path / "a1.dump" and fc.exists("a1", "a1.dump")
    assert fc.fetch("a1", "missing.dump") is None
    fc.remove_all("a1")
    assert not (tmp_path / "a1.dump").exists()


def test_publish_then_fetch_on_another_machine(tmp_path):
    fc = _cache(tmp_path)
    p = fc.local("d1.dump")
    p.write_bytes(b"PGDMP-data")
    fc.publish("d1", p)
    p.unlink()  # e.g. another process/node with an empty cache
    assert fc.exists("d1", "d1.dump")
    got = fc.fetch("d1", "d1.dump")
    assert got == p and got.read_bytes() == b"PGDMP-data"
    assert not list(fc.local_dir.glob("*.fetch"))
    assert fc.fetch("d1", "d1.toc.json") is None


def test_fetch_uploads_a_local_file_that_was_never_stored(tmp_path):
    fc = _cache(tmp_path)
    fc.local("old.sql").write_bytes(b"pre-B5 file")
    assert fc.fetch("old", "old.sql") is not None
    assert fc._objects.data["t-tool/old/old.sql"] == b"pre-B5 file"


def test_remove_all_clears_storage_and_local(tmp_path):
    fc = _cache(tmp_path)
    for name in ("d2.dump", "d2.toc.json"):
        fc.local(name).write_bytes(b"x")
        fc.publish("d2", fc.local(name))
    fc.remove_all("d2")
    assert not fc._objects.data and not list(fc.local_dir.iterdir())


def test_trim_evicts_only_stored_and_not_recent_files(tmp_path):
    fc = _cache(tmp_path, budget_mb=1)
    old = time.time() - RECENT_SECONDS - 60
    big = b"x" * (700 * 1024)
    for name in ("a.dump", "b.dump", "c.dump"):
        fc.local(name).write_bytes(big)
        os.utime(fc.local(name), (old, old))
    fc._objects.data["t-tool/a/a.dump"] = big  # a is stored; b exists only here; c is stored but recently used
    fc._objects.data["t-tool/c/c.dump"] = big
    os.utime(fc.local("c.dump"))
    assert fc.trim() == 1
    assert not fc.local("a.dump").exists() and fc.local("b.dump").exists() and fc.local("c.dump").exists()

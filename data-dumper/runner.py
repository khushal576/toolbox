"""
data-dumper/runner.py

Runs a dump or a restore per dump id as a job, with a log tail and a small progress dict the UI polls.

Since roadmap B5 this is the shared `core/jobs/runner.JobRunner`: with Redis configured the run is a job on the
queue executed by the `worker` container (a web restart doesn't kill it; log + progress are in Redis, visible to
every web process); standalone it is a background thread as before. Durable facts (the dump catalogue and the run
history) are in SQLite, the dump files in S3 storage (state_store.FILES).

A dump/run left 'running' by a job that died is marked failed by `recover_orphans()` (web start) and `heal()`
(every status read) — only when NO live job exists for it, so restarting the web container while the worker is
still dumping doesn't break a live run.
"""

from __future__ import annotations

from typing import Any

try:
    from data_dumper import engine, state_store as store
except ImportError:
    import engine
    import state_store as store

try:
    from core.jobs.runner import AlreadyRunning, JobRunner
except ImportError:  # standalone (cd data-dumper && uvicorn server:app) without the repo root on the path
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.jobs.runner import AlreadyRunning, JobRunner

LOG_LINES = 300
_RUNNER = JobRunner("data-dumper", log_size=LOG_LINES)
MODE = _RUNNER.mode

__all__ = ["AlreadyRunning", "start_dump", "start_restore", "stop", "view", "is_running", "recover_orphans", "heal", "MODE"]


def do_dump(ctx: Any, dump_id: str) -> None:
    """Job body (worker or thread)."""
    engine.run_dump(dump_id, ctx.cancel, ctx.log, ctx.progress)


def do_restore(ctx: Any, dump_id: str, opts: dict[str, Any]) -> None:
    """Job body (worker or thread)."""
    engine.run_restore(dump_id, opts, ctx.cancel, ctx.log, ctx.progress)


def start_dump(dump_id: str) -> None:
    _RUNNER.start(dump_id, "dump", do_dump, dump_id, description=f"data-dumper: dump {dump_id}")


def start_restore(dump_id: str, opts: dict[str, Any]) -> None:
    _RUNNER.start(dump_id, "restore", do_restore, dump_id, opts, description=f"data-dumper: restore {dump_id}")


def stop(dump_id: str) -> bool:
    v = _RUNNER.view(dump_id)
    ok = _RUNNER.stop(dump_id)
    if ok and v["queued"] and v["kind"] == "dump":  # cancelled before a worker picked it up: no engine ran
        d = store.get_dump(dump_id)
        if d and d["status"] == "running":
            store.update_dump(dump_id, status="failed", error="Stopped by you before it started.", finished_at=store._now())
    return ok


def view(dump_id: str) -> dict[str, Any]:
    return _RUNNER.view(dump_id)


def is_running(dump_id: str) -> bool:
    return _RUNNER.is_running(dump_id)


def recover_orphans() -> int:
    return store.fail_orphans(is_running)


def heal(dump_id: str) -> None:
    store.fail_orphans(is_running, only=dump_id)

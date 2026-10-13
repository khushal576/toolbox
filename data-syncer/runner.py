"""
data-syncer/runner.py

Runs engine.run_project() on a background thread and keeps the last N log
lines in memory for the UI. In-process on purpose: the container already
runs ONE uvicorn worker (see ../CLAUDE.md "Standing rule: stateful tools
and --workers"), and this is one more instance of that constraint — the
job registry below lives in this process's memory, so with >1 worker a
Start on one worker would be invisible to the status poll on another.
The DURABLE state (positions, statuses) is in SQLite; only "is a run
alive right now" and the log ring buffer are process-local, and both are
safely rebuilt after a restart (recover_interrupted() flips orphaned
'running' tables to 'interrupted').

Logs are a bounded deque per project (`log_size`, default 100): a huge
table producing millions of chunk lines can never grow memory, and the UI
only ever shows the tail — by design (owner: "only need the last 100 or n
logs").
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from data_syncer import engine, state_store as store
except ImportError:
    import engine
    import state_store as store


class AlreadyRunning(RuntimeError):
    pass


class Job:
    def __init__(self, project_id: str, log_size: int):
        self.project_id = project_id
        self.stop = threading.Event()
        self.logs: deque[dict[str, Any]] = deque(maxlen=log_size)
        self.seq = 0
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: Optional[str] = None
        self.summary: Optional[dict[str, int]] = None
        self.error: Optional[str] = None
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def log(self, level: str, message: str, table: Optional[str] = None) -> None:
        with self._lock:
            self.seq += 1
            self.logs.append({
                "seq": self.seq, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "level": level, "table": table, "msg": message,
            })

    def snapshot_logs(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.logs)


_JOBS: dict[str, Job] = {}
_REGISTRY_LOCK = threading.Lock()


def _target(job: Job) -> None:
    try:
        job.summary = engine.run_project(job.project_id, job.stop, job.log)
    except Exception as exc:  # noqa: BLE001 — a run that cannot even start (bad connection, missing project)
        job.error = str(exc)
        job.log("error", f"run could not start/continue: {exc}")
    finally:
        # A table left 'running' here would look alive forever; whatever ended the run, make it resumable.
        store.mark_running_interrupted(job.project_id)
        job.finished_at = datetime.now(timezone.utc).isoformat()


def start(project_id: str) -> Job:
    project = store.get_project(project_id)
    if project is None:
        raise KeyError(project_id)
    with _REGISTRY_LOCK:
        existing = _JOBS.get(project_id)
        if existing is not None and existing.running:
            raise AlreadyRunning("This project is already running.")
        job = Job(project_id, log_size=project["log_size"])
        job.thread = threading.Thread(target=_target, args=(job,), name=f"syncer-{project_id[:8]}", daemon=True)
        _JOBS[project_id] = job
        job.log("info", "run started")
        job.thread.start()
    return job


def stop(project_id: str) -> bool:
    """Ask a running job to stop. Graceful: the current chunk is aborted (its
    target transaction rolled back), the position saved, then the thread
    exits. Returns False if nothing was running."""
    job = _JOBS.get(project_id)
    if job is None or not job.running:
        return False
    job.stop.set()
    job.log("warn", "stop requested — aborting the current chunk, saving position…")
    return True


def get(project_id: str) -> Optional[Job]:
    return _JOBS.get(project_id)


def is_running(project_id: str) -> bool:
    job = _JOBS.get(project_id)
    return job is not None and job.running

"""
schema-copy/runner.py

One background thread per run (preflight / preview / apply / verify) with a
bounded in-memory log tail, exactly the shape of data-syncer/runner.py. The
job registry lives in this process's memory, so this tool is one more reason
the container stays at `--workers 1` (see ../CLAUDE.md). The durable result
of the last run is stored by engine.run() in SQLite (state_store.set_last_run).
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from schema_copy import engine, state_store as store
except ImportError:
    import engine
    import state_store as store

LOG_LINES = 200
ACTIONS = ("preflight", "preview", "apply", "verify")


class AlreadyRunning(RuntimeError):
    pass


class Job:
    def __init__(self, project_id: str, action: str):
        self.project_id, self.action = project_id, action
        self.cancel = threading.Event()
        self.logs: deque[dict[str, Any]] = deque(maxlen=LOG_LINES)
        self.seq = 0
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: Optional[str] = None
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def log(self, level: str, message: str) -> None:
        with self._lock:
            self.seq += 1
            self.logs.append({"seq": self.seq, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "level": level, "msg": message})

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.logs)


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def _target(job: Job) -> None:
    try:
        engine.run(job.project_id, job.action, job.cancel, job.log)
    except Exception as exc:  # noqa: BLE001 — run() handles expected problems; this is the last resort
        job.log("error", f"unexpected failure: {exc}")
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()


def start(project_id: str, action: str) -> Job:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    if store.get_project(project_id) is None:
        raise KeyError(project_id)
    with _LOCK:
        existing = _JOBS.get(project_id)
        if existing is not None and existing.running:
            raise AlreadyRunning("This project already has a run in progress.")
        job = Job(project_id, action)
        job.thread = threading.Thread(target=_target, args=(job,), name=f"schemacopy-{project_id[:8]}", daemon=True)
        _JOBS[project_id] = job
        job.log("info", f"{action} started")
        job.thread.start()
    return job


def stop(project_id: str) -> bool:
    job = _JOBS.get(project_id)
    if job is None or not job.running:
        return False
    job.cancel.set()
    job.log("warn", "stop requested…")
    return True


def get(project_id: str) -> Optional[Job]:
    return _JOBS.get(project_id)


def is_running(project_id: str) -> bool:
    job = _JOBS.get(project_id)
    return job is not None and job.running

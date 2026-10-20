"""
data-dumper/runner.py

One background thread per dump/restore, with a bounded in-memory log tail and a small
progress dict the UI polls. Same shape as data-syncer/runner.py and schema-copy/runner.py:
the registry lives in this process's memory, so this tool is one more reason the container
stays at `--workers 1` (see ../CLAUDE.md). Durable facts (the dump catalogue and the run
history) are in SQLite.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    from data_dumper import engine, state_store as store
except ImportError:
    import engine
    import state_store as store

LOG_LINES = 300


class AlreadyRunning(RuntimeError):
    pass


class Job:
    def __init__(self, dump_id: str, kind: str):
        self.dump_id, self.kind = dump_id, kind
        self.cancel = threading.Event()
        self.logs: deque[dict[str, Any]] = deque(maxlen=LOG_LINES)
        self.progress: dict[str, Any] = {}
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
            self.logs.append({"seq": self.seq, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "level": level, "msg": message})

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.logs)


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def _start(dump_id: str, kind: str, target: Callable[[Job], None]) -> Job:
    with _LOCK:
        existing = _JOBS.get(dump_id)
        if existing is not None and existing.running:
            raise AlreadyRunning("This dump already has a run in progress.")
        job = Job(dump_id, kind)
        job.thread = threading.Thread(target=lambda: _wrap(job, target), name=f"dumper-{dump_id[:8]}", daemon=True)
        _JOBS[dump_id] = job
        job.log("info", f"{kind} started")
        job.thread.start()
    return job


def _wrap(job: Job, target: Callable[[Job], None]) -> None:
    try:
        target(job)
    except Exception as exc:  # noqa: BLE001 — the engine reports expected problems; this is the last resort
        job.log("error", f"unexpected failure: {exc}")
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()


def start_dump(dump_id: str) -> Job:
    return _start(dump_id, "dump", lambda j: engine.run_dump(dump_id, j.cancel, j.log, j.progress))


def start_restore(dump_id: str, opts: dict[str, Any]) -> Job:
    return _start(dump_id, "restore", lambda j: engine.run_restore(dump_id, opts, j.cancel, j.log, j.progress))


def stop(dump_id: str) -> bool:
    job = _JOBS.get(dump_id)
    if job is None or not job.running:
        return False
    job.cancel.set()
    job.log("warn", "stop requested…")
    return True


def get(dump_id: str) -> Optional[Job]:
    return _JOBS.get(dump_id)


def is_running(dump_id: str) -> bool:
    job = _JOBS.get(dump_id)
    return job is not None and job.running

"""
ssh-sftp/runner.py

One background thread per upload / command, with a bounded in-memory log and a small progress dict the UI
polls. Same shape as the other tools' runners; the registry lives in this process's memory (one more reason
for --workers 1, see ../CLAUDE.md). Durable facts (transfer status, command history) are in SQLite.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

try:
    from ssh_sftp import engine
except ImportError:
    import engine

LOG_LINES = 2000
KEEP_JOBS = 100


class AlreadyRunning(RuntimeError):
    pass


class Job:
    def __init__(self, job_id: str, kind: str):
        self.id, self.kind = job_id, kind
        self.cancel = threading.Event()
        self.logs: deque[dict[str, Any]] = deque(maxlen=LOG_LINES)
        self.progress: dict[str, Any] = {}
        self.seq = 0
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def log(self, level: str, message: str) -> None:
        with self._lock:
            self.seq += 1
            self.logs.append({"seq": self.seq, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "level": level, "msg": message})

    def snapshot(self, since: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [l for l in self.logs if l["seq"] > since]


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def _start(job_id: str, kind: str, target: Callable[[Job], None]) -> Job:
    with _LOCK:
        old = _JOBS.get(job_id)
        if old is not None and old.running:
            raise AlreadyRunning("This is already running.")
        job = Job(job_id, kind)
        job.thread = threading.Thread(target=lambda: _wrap(job, target), name=f"sshsftp-{job_id[:8]}", daemon=True)
        _JOBS[job_id] = job
        if len(_JOBS) > KEEP_JOBS:  # forget the oldest FINISHED jobs; never a running one
            for jid in [j for j, x in list(_JOBS.items()) if not x.running][: len(_JOBS) - KEEP_JOBS]:
                _JOBS.pop(jid, None)
        job.thread.start()
    return job


def _wrap(job: Job, target: Callable[[Job], None]) -> None:
    try:
        target(job)
    except Exception as exc:  # noqa: BLE001 — the engine records expected failures; this is the last resort
        job.log("error", f"unexpected failure: {exc}")


def start_upload(tid: str) -> Job:
    return _start(tid, "upload", lambda j: engine.run_upload(tid, j.cancel, j.log, j.progress))


def start_command(cid: str, server_id: str, command: str, timeout: int) -> Job:
    return _start(cid, "command", lambda j: engine.run_command(cid, server_id, command, timeout, j.cancel, j.log, j.progress))


def stop(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if job is None or not job.running:
        return False
    job.cancel.set()
    return True


def get(job_id: str) -> Optional[Job]:
    return _JOBS.get(job_id)


def is_running(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    return job is not None and job.running

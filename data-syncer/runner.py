"""
data-syncer/runner.py

Runs engine.run_project() for a project and exposes its live state (running?, stopping?, last N log lines,
summary) to the UI.

Since roadmap B4 a run is a JOB on the shared Redis queue (core/jobs) executed by the separate `worker`
container — a web restart/deploy no longer kills a sync, and any web process sees the same state:
- "is it running" = the job slot's heartbeat key (expires ~30 s after a worker dies),
- the log tail = a Redis list trimmed to the project's `log_size` (owner: "only need the last 100 or n logs"),
- Stop = a Redis flag the engine polls between data blocks (graceful: chunk rolled back, position saved).

Without Redis (standalone dev: `cd data-syncer && uvicorn server:app`) the old in-process background thread is
used (`_LocalRunner`), same behavior as before B4.

The DURABLE state (positions, statuses) is in the state store. A table left 'running' by a run that died is
flipped to 'interrupted' by `recover_orphans()` — only for projects with NO live job, so restarting the web
container while the worker is still syncing doesn't corrupt a live run.
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from data_syncer import engine, state_store as store
except ImportError:
    import engine
    import state_store as store

try:
    from core import jobs
except ImportError:  # standalone without core on the path
    jobs = None

TOOL = "data-syncer"


class AlreadyRunning(RuntimeError):
    pass


@dataclass
class RunView:
    """What the UI needs about the latest run of a project (same shape from both runners)."""
    running: bool = False
    stopping: bool = False
    queued: bool = False
    logs: list[dict[str, Any]] = field(default_factory=list)
    summary: Optional[dict[str, int]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


# ------------------------------------------------------------------ queue runner (Redis + worker container)

def run_job(project_id: str) -> None:
    """Executed by the worker (core.jobs.worker) — never call from a web request."""
    project = store.get_project(project_id)
    ch = jobs.Channel(TOOL, project_id, log_size=(project or {}).get("log_size", 100))
    with ch.running():
        ch.log("info", "run started in worker")
        try:
            summary = engine.run_project(project_id, ch.stop_flag(), ch.log)
            ch.update_meta(summary=summary)
        except Exception as exc:  # noqa: BLE001 — a run that cannot even start (bad connection, missing project)
            ch.update_meta(error=str(exc))
            ch.log("error", f"run could not start/continue: {exc}")
        finally:
            # A table left 'running' here would look alive forever; whatever ended the run, make it resumable.
            store.mark_running_interrupted(project_id)


class _QueueRunner:
    def _ch(self, project_id: str, log_size: int = 100):
        return jobs.Channel(TOOL, project_id, log_size=log_size)

    def start(self, project_id: str) -> None:
        project = store.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        ch = self._ch(project_id, project["log_size"])
        rq_id = f"{TOOL}-{project_id}-{uuid.uuid4().hex[:8]}"
        if not ch.claim(rq_job_id=rq_id):
            raise AlreadyRunning("This project is already running.")
        try:
            ch.log("info", "run queued — waiting for a worker")
            jobs.enqueue("data_syncer.runner.run_job", project_id, job_id=rq_id,
                         description=f"data-syncer: {project.get('name', project_id)}")
        except Exception:
            ch.release()
            raise

    def stop(self, project_id: str) -> bool:
        ch = self._ch(project_id)
        if not ch.request_stop():
            return False
        ch.log("warn", "stop requested — aborting the current chunk, saving position…")
        return True

    def view(self, project_id: str) -> RunView:
        ch = self._ch(project_id)
        alive, meta = ch.alive(), ch.meta()
        if alive is None and not meta:
            return RunView()
        running = alive is not None
        return RunView(running=running, queued=bool(alive and alive.get("state") == "queued"),
                       stopping=running and ch.stop_requested(), logs=ch.logs(),
                       summary=meta.get("summary"), error=meta.get("error"),
                       started_at=meta.get("started_at") or meta.get("queued_at"),
                       finished_at=meta.get("finished_at"))

    def is_running(self, project_id: str) -> bool:
        return self._ch(project_id).alive() is not None


# ------------------------------------------------------------------ local runner (standalone dev, pre-B4 behavior)

class _Job:
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
            self.logs.append({"seq": self.seq, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "level": level, "table": table, "msg": message})


class _LocalRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def _target(self, job: _Job) -> None:
        try:
            job.summary = engine.run_project(job.project_id, job.stop, job.log)
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)
            job.log("error", f"run could not start/continue: {exc}")
        finally:
            store.mark_running_interrupted(job.project_id)
            job.finished_at = datetime.now(timezone.utc).isoformat()

    def start(self, project_id: str) -> None:
        project = store.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        with self._lock:
            existing = self._jobs.get(project_id)
            if existing is not None and existing.running:
                raise AlreadyRunning("This project is already running.")
            job = _Job(project_id, log_size=project["log_size"])
            job.thread = threading.Thread(target=self._target, args=(job,), name=f"syncer-{project_id[:8]}",
                                          daemon=True)
            self._jobs[project_id] = job
            job.log("info", "run started")
            job.thread.start()

    def stop(self, project_id: str) -> bool:
        job = self._jobs.get(project_id)
        if job is None or not job.running:
            return False
        job.stop.set()
        job.log("warn", "stop requested — aborting the current chunk, saving position…")
        return True

    def view(self, project_id: str) -> RunView:
        job = self._jobs.get(project_id)
        if job is None:
            return RunView()
        with job._lock:
            logs = list(job.logs)
        return RunView(running=job.running, stopping=job.running and job.stop.is_set(), logs=logs,
                       summary=job.summary, error=job.error, started_at=job.started_at, finished_at=job.finished_at)

    def is_running(self, project_id: str) -> bool:
        job = self._jobs.get(project_id)
        return job is not None and job.running


_RUNNER = _QueueRunner() if (jobs is not None and jobs.available()) else _LocalRunner()
MODE = "queue" if isinstance(_RUNNER, _QueueRunner) else "thread"


def start(project_id: str) -> None:
    _RUNNER.start(project_id)


def stop(project_id: str) -> bool:
    return _RUNNER.stop(project_id)


def view(project_id: str) -> RunView:
    return _RUNNER.view(project_id)


def is_running(project_id: str) -> bool:
    return _RUNNER.is_running(project_id)


def recover_orphans() -> int:
    """Flip 'running' tables to 'interrupted' for every project WITHOUT a live job (crash/restart leftovers).
    Safe to call any time; with the queue runner a sync still running in the worker is left alone."""
    if isinstance(_RUNNER, _LocalRunner):
        return store.recover_interrupted()  # a new process has no live threads at all
    n = 0
    for p in store.list_projects():
        if not _RUNNER.is_running(p["id"]) and any(t["status"] == "running" for t in store.list_tables(p["id"])):
            store.mark_running_interrupted(p["id"])
            n += 1
    return n


def heal(project_id: str) -> None:
    """If no job is alive but tables still say 'running' (e.g. the worker container died mid-run), mark them
    'interrupted' so the UI never shows a ghost run and Start can resume. Called on every status read."""
    if not _RUNNER.is_running(project_id) and any(t["status"] == "running" for t in store.list_tables(project_id)):
        store.mark_running_interrupted(project_id)

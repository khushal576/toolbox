"""
core.jobs.runner — one runner for "start a long job per key, show its log/progress, stop it" (roadmap B5).

Used by schema-copy and data-dumper (data-syncer has its own, older copy of the same idea from B4). A tool writes
its job as a plain function and gets the same behavior in both modes:

    def do_dump(ctx, dump_id): engine.run_dump(dump_id, ctx.cancel, ctx.log, ctx.progress)
    RUNNER = JobRunner("data-dumper", log_size=300)
    RUNNER.start(dump_id, "dump", do_dump, dump_id)   # the worker imports it as data_dumper.runner.do_dump
    RUNNER.view(dump_id)  →  {running, queued, stopping, kind, logs, progress, error, started_at, finished_at}

- queue mode (Redis configured): the job runs in the `worker` container; live state is a `Channel` in Redis, so any
  web process sees it and a web restart doesn't kill it. `ctx.progress` is a dict that writes itself to Redis
  (at most once a second, plus a final flush).
- thread mode (standalone dev / unit tests): a daemon thread in this process, state in memory — pre-B5 behavior.

`ctx.cancel` has `is_set()` and `wait(timeout)` in both modes (threading.Event / jobs.StopFlag).
"""

from __future__ import annotations

import importlib
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional


class AlreadyRunning(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve(func_path: str) -> Callable[..., Any]:
    module, _, name = func_path.rpartition(".")
    return getattr(importlib.import_module(module), name)


class _Ctx:
    def __init__(self, cancel: Any, log: Callable[..., None], progress: dict):
        self.cancel, self.log, self.progress = cancel, log, progress


class _RedisProgress(dict):
    """A dict whose content is mirrored to the channel's meta (throttled: engines bump counters per line)."""

    def __init__(self, channel: Any, every: float = 1.0):
        super().__init__()
        self._ch, self._every, self._last = channel, every, 0.0

    def _sync(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last >= self._every:
            self._last = now
            try:
                self._ch.update_meta(progress=dict(self))
            except Exception:  # noqa: BLE001 - progress is cosmetic; never break the job over it
                pass

    def __setitem__(self, k: Any, v: Any) -> None:
        super().__setitem__(k, v)
        self._sync()

    def update(self, *a: Any, **kw: Any) -> None:
        super().update(*a, **kw)
        self._sync()

    def flush(self) -> None:
        self._sync(force=True)


def execute(tool: str, key: str, log_size: int, kind: str, func_path: str, *args: Any) -> None:
    """Executed by the worker (core.jobs.worker) — never call from a web request."""
    from core import jobs

    ch = jobs.Channel(tool, key, log_size=log_size)
    progress = _RedisProgress(ch)
    with ch.running():
        ch.update_meta(kind=kind)
        ch.log("info", f"{kind} started in worker")
        try:
            _resolve(func_path)(_Ctx(ch.stop_flag(), lambda level, msg, *_: ch.log(level, msg), progress), *args)
        except Exception as exc:  # noqa: BLE001 — the engines report expected problems; this is the last resort
            ch.update_meta(error=str(exc))
            ch.log("error", f"unexpected failure: {exc}")
        finally:
            progress.flush()


class _ThreadJob:
    def __init__(self, kind: str, log_size: int):
        self.kind = kind
        self.cancel = threading.Event()
        self.logs: deque[dict[str, Any]] = deque(maxlen=log_size)
        self.progress: dict[str, Any] = {}
        self.seq = 0
        self.started_at = _now()
        self.finished_at: Optional[str] = None
        self.error: Optional[str] = None
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def log(self, level: str, message: str, *_: Any) -> None:
        with self._lock:
            self.seq += 1
            self.logs.append({"seq": self.seq, "ts": _now(), "level": level, "msg": message})


def _empty_view() -> dict[str, Any]:
    return {"running": False, "queued": False, "stopping": False, "kind": None, "logs": [], "progress": {},
            "error": None, "started_at": None, "finished_at": None}


class JobRunner:
    def __init__(self, tool: str, log_size: int = 200, mode: Optional[str] = None):
        try:
            from core import jobs
        except ImportError:  # standalone without core on the path
            jobs = None
        self.tool, self.log_size = tool, log_size
        self.mode = mode or ("queue" if (jobs is not None and jobs.available()) else "thread")
        self._jobs_mod = jobs
        self._threads: dict[str, _ThreadJob] = {}
        self._lock = threading.Lock()

    def _ch(self, key: str):
        return self._jobs_mod.Channel(self.tool, key, log_size=self.log_size)

    def start(self, key: str, kind: str, func: Callable[..., Any], *args: Any, description: str = "") -> None:
        """Run `func(ctx, *args)` as the job of `key` (a module-level function: the worker imports it by name;
        args must be JSON/pickle-able). Raises AlreadyRunning if one is queued/running."""
        if self.mode == "queue":
            func_path = f"{func.__module__}.{func.__qualname__}"
            ch = self._ch(key)
            rq_id = f"{self.tool}-{key}-{uuid.uuid4().hex[:8]}"
            if not ch.claim(rq_job_id=rq_id):
                raise AlreadyRunning("A run is already in progress.")
            try:
                ch.update_meta(kind=kind, progress={})
                ch.log("info", f"{kind} queued — waiting for a worker")
                self._jobs_mod.enqueue("core.jobs.runner.execute", self.tool, key, self.log_size, kind, func_path,
                                       *args, job_id=rq_id, description=description or f"{self.tool}: {kind} {key}")
            except Exception:
                ch.release()
                raise
            return
        with self._lock:
            existing = self._threads.get(key)
            if existing is not None and existing.running:
                raise AlreadyRunning("A run is already in progress.")
            job = _ThreadJob(kind, self.log_size)

            def target() -> None:
                try:
                    func(_Ctx(job.cancel, job.log, job.progress), *args)
                except Exception as exc:  # noqa: BLE001
                    job.error = str(exc)
                    job.log("error", f"unexpected failure: {exc}")
                finally:
                    job.finished_at = _now()

            job.thread = threading.Thread(target=target, name=f"{self.tool}-{key[:8]}", daemon=True)
            self._threads[key] = job
            job.log("info", f"{kind} started")
            job.thread.start()

    def stop(self, key: str) -> bool:
        if self.mode == "queue":
            ch = self._ch(key)
            if not ch.request_stop():
                return False
            ch.log("warn", "stop requested…")
            return True
        job = self._threads.get(key)
        if job is None or not job.running:
            return False
        job.cancel.set()
        job.log("warn", "stop requested…")
        return True

    def is_running(self, key: str) -> bool:
        if self.mode == "queue":
            return self._ch(key).alive() is not None
        job = self._threads.get(key)
        return job is not None and job.running

    def view(self, key: str) -> dict[str, Any]:
        if self.mode == "queue":
            ch = self._ch(key)
            alive, meta = ch.alive(), ch.meta()
            if alive is None and not meta:
                return _empty_view()
            running = alive is not None
            return {"running": running, "queued": bool(alive and alive.get("state") == "queued"),
                    "stopping": running and ch.stop_requested(), "kind": meta.get("kind"), "logs": ch.logs(),
                    "progress": meta.get("progress") or {}, "error": meta.get("error"),
                    "started_at": meta.get("started_at") or meta.get("queued_at"),
                    "finished_at": meta.get("finished_at")}
        job = self._threads.get(key)
        if job is None:
            return _empty_view()
        with job._lock:
            logs = list(job.logs)
        return {"running": job.running, "queued": False, "stopping": job.running and job.cancel.is_set(),
                "kind": job.kind, "logs": logs, "progress": dict(job.progress), "error": job.error,
                "started_at": job.started_at, "finished_at": job.finished_at}

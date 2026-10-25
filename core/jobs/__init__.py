"""
core.jobs — background jobs on a Redis queue (roadmap B4, ADR-001). Long work (syncs, dumps, transfers) runs in
the separate `worker` container, not in a web process, so a web restart never kills it and several workers can
run jobs in parallel later (`docker compose up --scale worker=N`).

    from core import jobs
    ch = jobs.Channel("data-syncer", project_id, log_size=100)
    ch.claim(rq_job_id=...)          # atomic "not already running" check (False if a live job exists)
    jobs.enqueue("data_syncer.runner.run_job", project_id, job_id=...)
    # in the worker, inside the job:  with ch.running(): ... ch.log("info", "…"); if ch.stop_flag().is_set(): …
    ch.alive(); ch.state(); ch.logs(); ch.request_stop()   # from ANY web process

Redis keys: toolbox:jobs:<tool>:<key>:{alive,log,seq,stop,meta}. "Alive" is a heartbeat with a short TTL while a
job runs (a crashed worker shows as stopped within seconds) and a long TTL while it waits in the queue.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

QUEUE_NAME = "toolbox"
HEARTBEAT_TTL = 30          # seconds a running job stays "alive" without a heartbeat
HEARTBEAT_EVERY = 10
QUEUED_TTL = 24 * 3600      # a job waiting for a free worker
_lock = threading.Lock()
_rq_conn = None


def available() -> bool:
    """True when a Redis URL is configured (otherwise tools fall back to in-process threads)."""
    try:
        from core.state import config
    except ImportError:
        return False
    return bool(config.load().redis_url)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rq_connection():
    """Redis client for RQ (binary: RQ stores pickled payloads, so no decode_responses)."""
    global _rq_conn
    if _rq_conn is None:
        with _lock:
            if _rq_conn is None:
                import redis

                from core.state.config import load, require
                _rq_conn = redis.Redis.from_url(require(load().redis_url, "TOOLBOX_REDIS_URL"),
                                                socket_timeout=10, socket_connect_timeout=5)
    return _rq_conn


def queue(name: str = QUEUE_NAME):
    from rq import Queue

    return Queue(name, connection=rq_connection())


def enqueue(func_path: str, *args: Any, job_id: str, description: str = "") -> str:
    """Queue `module.function(*args)` for the worker. No time limit (syncs can run for hours); results are kept
    1 h, failures 7 days (visible to `rq info`)."""
    job = queue().enqueue(func_path, *args, job_id=job_id, job_timeout=-1, result_ttl=3600,
                          failure_ttl=7 * 24 * 3600, description=description or func_path)
    return job.id


def cancel(rq_job_id: str) -> None:
    from rq.job import Job

    try:
        Job.fetch(rq_job_id, connection=rq_connection()).cancel()
    except Exception:  # noqa: BLE001 - already finished/gone is fine
        pass


class StopFlag:
    """threading.Event look-alike backed by Redis: `is_set()` (cached ~1 s, it's called per data block) and
    `wait(timeout)`. Lets code written for threads stop gracefully when ANY web process asks."""

    def __init__(self, channel: "Channel"):
        self._ch, self._cached, self._checked = channel, False, 0.0

    def is_set(self) -> bool:
        if self._cached:
            return True
        now = time.monotonic()
        if now - self._checked >= 1.0:
            self._checked = now
            self._cached = self._ch.stop_requested()
        return self._cached

    def wait(self, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.is_set():
                return True
            time.sleep(min(0.5, max(0.0, end - time.monotonic())))
        return self.is_set()


class Channel:
    """Shared status + log tail + stop flag of one job slot (one per tool+key, e.g. one per sync project)."""

    def __init__(self, tool: str, key: str, log_size: int = 100):
        from core.state import sessions

        self._r = sessions.client  # text-mode client (JSON values)
        self.prefix = f"toolbox:jobs:{tool}:{key}"
        self.log_size = max(1, int(log_size))
        self._token: str | None = None

    def _k(self, part: str) -> str:
        return f"{self.prefix}:{part}"

    # ---- lifecycle -------------------------------------------------------------------------------------
    def claim(self, rq_job_id: str = "") -> bool:
        """Mark the slot as queued unless a job is already queued/running. Clears the previous run's log/stop."""
        token = secrets.token_hex(8)
        ok = self._r().set(self._k("alive"), json.dumps({"state": "queued", "token": token, "rq_id": rq_job_id}),
                           nx=True, ex=QUEUED_TTL)
        if not ok:
            return False
        self._token = token
        r = self._r()
        pipe = r.pipeline()
        pipe.delete(self._k("log"), self._k("stop"), self._k("seq"))
        pipe.set(self._k("meta"), json.dumps({"queued_at": _now(), "started_at": None, "finished_at": None,
                                              "summary": None, "error": None}))
        pipe.execute()
        return True

    def set_rq_id(self, rq_job_id: str) -> None:
        raw = self._r().get(self._k("alive"))
        if raw:
            a = json.loads(raw)
            a["rq_id"] = rq_job_id
            self._r().set(self._k("alive"), json.dumps(a), keepttl=True)

    def release(self) -> None:
        self._r().delete(self._k("alive"))

    @contextmanager
    def running(self) -> Iterator["Channel"]:
        """Inside the worker: heartbeat while the block runs; always releases the slot afterwards."""
        stop_beat = threading.Event()
        self._r().set(self._k("alive"), json.dumps({"state": "running", "since": _now()}), ex=HEARTBEAT_TTL)
        self.update_meta(started_at=_now())

        def beat() -> None:
            while not stop_beat.wait(HEARTBEAT_EVERY):
                try:
                    self._r().set(self._k("alive"), json.dumps({"state": "running"}), ex=HEARTBEAT_TTL)
                except Exception:  # noqa: BLE001 - a missed beat is tolerated (TTL is 3 beats)
                    pass

        t = threading.Thread(target=beat, daemon=True, name="job-heartbeat")
        t.start()
        try:
            yield self
        finally:
            stop_beat.set()
            t.join(timeout=2)
            self.update_meta(finished_at=_now())
            self.release()

    # ---- reads (any process) ---------------------------------------------------------------------------
    def alive(self) -> dict[str, Any] | None:
        raw = self._r().get(self._k("alive"))
        return json.loads(raw) if raw else None

    def stop_requested(self) -> bool:
        return bool(self._r().exists(self._k("stop")))

    def stop_flag(self) -> StopFlag:
        return StopFlag(self)

    def request_stop(self) -> bool:
        a = self.alive()
        if a is None:
            return False
        self._r().set(self._k("stop"), "1", ex=QUEUED_TTL)
        if a.get("state") == "queued" and a.get("rq_id"):
            cancel(a["rq_id"])  # never started: drop it from the queue
            self.release()
        return True

    def meta(self) -> dict[str, Any]:
        raw = self._r().get(self._k("meta"))
        return json.loads(raw) if raw else {}

    def update_meta(self, **fields: Any) -> None:
        m = self.meta()
        m.update(fields)
        self._r().set(self._k("meta"), json.dumps(m, default=str))

    # ---- log tail --------------------------------------------------------------------------------------
    def log(self, level: str, message: str, table: str | None = None) -> None:
        r = self._r()
        seq = r.incr(self._k("seq"))
        entry = json.dumps({"seq": seq, "ts": _now(), "level": level, "table": table, "msg": message})
        pipe = r.pipeline()
        pipe.rpush(self._k("log"), entry)
        pipe.ltrim(self._k("log"), -self.log_size, -1)
        pipe.execute()

    def logs(self) -> list[dict[str, Any]]:
        return [json.loads(x) for x in self._r().lrange(self._k("log"), 0, -1)]


def health() -> dict[str, Any]:
    """Workers listening on the queue + jobs waiting. Raises (→ reported as not ok) when no worker is running."""
    from rq import Worker

    workers = Worker.all(connection=rq_connection())
    waiting = len(queue())
    if not workers:
        raise RuntimeError(f"no job worker is running ({waiting} job(s) waiting) — start the `worker` service")
    return {"workers": len(workers), "waiting": waiting}

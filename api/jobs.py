"""
api/jobs.py — DataDiff compares as background jobs (roadmap D2).

A big compare doesn't run inside the web request any more: the API stores the INPUT in S3 storage, queues a job on
the shared Redis queue, and answers 202 with a job id at once. The `worker` container (it has the engine) loads the
input, parses + diffs it, and stores the RESULT (gzipped JSON) in S3 storage. Status lives in the job's Redis
channel (core/jobs), so ANY DataDiff replica can report it and return the result — nothing is kept in a process.

    submit("compare", {...text request...}) | submit("compare_structured", {...})  → job id
    status(job_id)  → {job_id, status: queued|running|done|failed|cancelled, phase, summary, error, …}
    result_path(job_id) → local copy of result.json.gz (fetched from storage if this replica has none)
    cancel(job_id)  → stops a queued job (a running diff can't be interrupted: its result is discarded)

Storage keys: datadiff/<job_id>/<job_id>.input.json.gz and .result.json.gz; inputs are deleted when the job ends,
results after RESULT_DAYS (swept opportunistically on submit). Redis job metadata expires after 7 days too
(core.jobs.KEEP_TTL). Standalone (no Redis/S3) it runs in a thread with local files — same API.
"""

from __future__ import annotations

import gzip
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from core.jobs.runner import AlreadyRunning, JobRunner  # noqa: F401 - re-exported for callers
from core.state.filecache import FileCache

RESULT_DAYS = 7
KINDS = ("compare", "compare_structured")
_DIR = Path(os.environ.get("DATADIFF_JOB_DIR", "/tmp/datadiff-jobs"))
FILES = FileCache("datadiff", _DIR, budget_mb=int(os.environ.get("DATADIFF_JOB_CACHE_MB", "512")))
JOBS = JobRunner("datadiff", log_size=50)
_last_sweep = 0.0


class JobNotFound(KeyError):
    pass


def _name(job_id: str, part: str) -> str:
    return f"{job_id}.{part}.json.gz"


def _write_gz(path: Path, obj: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=5) as f:
        json.dump(obj, f, separators=(",", ":"))
    return path.stat().st_size


def _sweep() -> None:
    global _last_sweep
    if time.monotonic() - _last_sweep < 3600:
        return
    _last_sweep = time.monotonic()
    try:
        FILES.sweep(None, RESULT_DAYS * 86400)
    except Exception:  # noqa: BLE001 - cleanup never blocks a submit
        pass


# ---- API side (DataDiff replicas) ------------------------------------------------------------------------------

def submit(kind: str, request: dict[str, Any]) -> str:
    """Store the input and queue the job. `request` is the JSON body of the matching sync endpoint."""
    if kind not in KINDS:
        raise ValueError(f"type must be one of {KINDS}")
    _sweep()
    job_id = uuid.uuid4().hex
    path = FILES.local(_name(job_id, "input"))
    _write_gz(path, request)
    FILES.publish(job_id, path)
    JOBS.start(job_id, kind, run_job, job_id, kind, description=f"datadiff: {kind} {job_id}")
    return job_id


def status(job_id: str) -> dict[str, Any]:
    v = JOBS.view(job_id)
    if not v["started_at"] and not v["queued"] and not v["running"]:
        raise JobNotFound(job_id)
    p = v["progress"] or {}
    phase = p.get("phase")
    if v["queued"]:
        state = "queued"
    elif v["running"]:
        state = "running"
    elif phase in ("done", "cancelled"):
        state = phase
    else:  # "failed" from the job itself, or the worker died without finishing
        state = "failed"
    error = p.get("error") or v["error"]
    if state == "failed" and not error:
        error = "The job stopped without a result (worker restarted or crashed) — submit it again."
    return {"job_id": job_id, "status": state, "type": v["kind"], "phase": phase, "summary": p.get("summary"),
            "result_bytes": p.get("result_bytes"), "seconds": p.get("seconds"), "error": error,
            "queued_or_started_at": v["started_at"], "finished_at": v["finished_at"]}


def result_path(job_id: str) -> Path | None:
    return FILES.fetch(job_id, _name(job_id, "result"))


def cancel(job_id: str) -> bool:
    """Stop a queued/running job, or forget a finished one (its stored result is deleted)."""
    v = JOBS.view(job_id)
    if JOBS.stop(job_id):
        if v["queued"] and JOBS.mode == "queue":  # never started: no job body will record it, so do it here
            JOBS._ch(job_id).update_meta(progress={"phase": "cancelled"})
            FILES.remove_all(job_id)
        return True
    FILES.remove_all(job_id)
    return False


# ---- worker side -----------------------------------------------------------------------------------------------

def run_job(ctx: Any, job_id: str, kind: str) -> None:
    """The job body (worker container, or a thread standalone). Never raises for bad input: the error is the result."""
    from core.clients.datadiff import decode_value, to_json_safe
    from core.normalizer import normalize
    from core.pipeline import PipelineError, run_compare

    t0 = time.monotonic()
    p = ctx.progress
    try:
        p["phase"] = "loading"
        src = FILES.fetch(job_id, _name(job_id, "input"))
        if src is None:
            raise ValueError("The job's input is gone (expired or deleted).")
        with gzip.open(src, "rt", encoding="utf-8") as f:
            req = json.load(f)
        opts = {k: req.get(k) for k in ("mapper_csv", "mapper_direction", "strict_mode", "multi_match_rule",
                                         "deep_mode", "environment_yaml", "null_missing_equivalent") if k in req}
        if ctx.cancel.is_set():
            raise InterruptedError
        formats = (req.get("left_format"), req.get("right_format"))
        if kind == "compare":
            p["phase"] = "parsing"
            left, err = normalize(req["left_data"], req["left_format"])
            if err:
                raise ValueError(f"Left side — {err}")
            right, err = normalize(req["right_data"], req["right_format"])
            if err:
                raise ValueError(f"Right side — {err}")
        else:
            left, right = decode_value(req["left"]), decode_value(req["right"])
        del req
        p["phase"] = "comparing"
        ctx.log("info", "comparing…")
        result = run_compare(left, right, **opts)
        if kind == "compare":
            result["meta"]["left_format"], result["meta"]["right_format"] = formats
        if ctx.cancel.is_set():
            raise InterruptedError
        p["phase"] = "saving"
        result = {"ok": True, **to_json_safe(result)}
        out = FILES.local(_name(job_id, "result"))
        size = _write_gz(out, result)
        FILES.publish(job_id, out)
        p.update(phase="done", summary=result.get("summary"), result_bytes=size,
                 seconds=round(time.monotonic() - t0, 2))
        ctx.log("ok", f"done in {p['seconds']}s — result {size:,} bytes (gzip)")
    except InterruptedError:
        p.update(phase="cancelled", seconds=round(time.monotonic() - t0, 2))
        ctx.log("warn", "cancelled — no result stored")
    except (PipelineError, ValueError, KeyError, TypeError) as exc:
        p.update(phase="failed", error=str(exc), seconds=round(time.monotonic() - t0, 2))
        ctx.log("error", str(exc))
    finally:
        FILES.remove(job_id, _name(job_id, "input"))

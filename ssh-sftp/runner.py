"""
ssh-sftp/runner.py

Runs an upload or a command as a job, with a log tail and a small progress dict the UI polls.

Since roadmap B8 this is the shared `core/jobs/runner.JobRunner`: with Redis configured the job runs in the
`worker` container (a web restart doesn't stop an upload; log + progress are in Redis, visible to every web
process); standalone it is a background thread as before. Durable facts (transfer status, command history) are in
Postgres, staged uploads in S3 storage (state_store.STAGE). `quiet`: no "queued/started" lines, because a command's
log IS its output pane.
"""

from __future__ import annotations

from typing import Any

try:
    from ssh_sftp import engine, state_store as store
except ImportError:
    import engine
    import state_store as store

try:
    from core.jobs.runner import AlreadyRunning, JobRunner
except ImportError:  # standalone (cd ssh-sftp && uvicorn server:app) without the repo root on the path
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.jobs.runner import AlreadyRunning, JobRunner

LOG_LINES = 2000
_RUNNER = JobRunner("ssh-sftp", log_size=LOG_LINES, quiet=True)
MODE = _RUNNER.mode

__all__ = ["AlreadyRunning", "start_upload", "start_command", "stop", "view", "is_running", "recover_orphans", "MODE"]


def do_upload(ctx: Any, tid: str) -> None:
    """Job body (worker or thread)."""
    engine.run_upload(tid, ctx.cancel, ctx.log, ctx.progress)


def do_command(ctx: Any, cid: str, server_id: str, command: str, timeout: int) -> None:
    """Job body (worker or thread)."""
    engine.run_command(cid, server_id, command, timeout, ctx.cancel, ctx.log, ctx.progress)


def start_upload(tid: str) -> None:
    _RUNNER.start(tid, "upload", do_upload, tid, description=f"ssh-sftp: upload {tid}")


def start_command(cid: str, server_id: str, command: str, timeout: int) -> None:
    _RUNNER.start(cid, "command", do_command, cid, server_id, command, timeout, description=f"ssh-sftp: command {cid}")


def stop(job_id: str) -> bool:
    return _RUNNER.stop(job_id)


def view(job_id: str, since: int = 0) -> dict[str, Any]:
    v = _RUNNER.view(job_id)
    if since:
        v["logs"] = [line for line in v["logs"] if line["seq"] > since]
    return v


def is_running(job_id: str) -> bool:
    return _RUNNER.is_running(job_id)


def recover_orphans() -> int:
    """Mark transfers/commands left 'running' by a dead job as failed (only those with no live job)."""
    return store.fail_orphans(is_running)

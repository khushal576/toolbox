"""
schema-copy/runner.py

Runs one action (preflight / preview / apply / verify) per project as a job and exposes its live state.

Since roadmap B5 this is the shared `core/jobs/runner.JobRunner`: with Redis configured the run is a job on the
queue executed by the `worker` container (a web restart doesn't kill it, any web process sees its log); standalone
it is a background thread as before. The durable result of the last run is stored by engine.run() in SQLite
(state_store.set_last_run); the generated script lives in S3 storage (state_store.SCRIPTS).
"""

from __future__ import annotations

from typing import Any

try:
    from schema_copy import engine, state_store as store
except ImportError:
    import engine
    import state_store as store

try:
    from core.jobs.runner import AlreadyRunning, JobRunner
except ImportError:  # standalone (cd schema-copy && uvicorn server:app) without the repo root on the path
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.jobs.runner import AlreadyRunning, JobRunner

LOG_LINES = 200
ACTIONS = ("preflight", "preview", "apply", "verify")
_RUNNER = JobRunner("schema-copy", log_size=LOG_LINES)
MODE = _RUNNER.mode

__all__ = ["AlreadyRunning", "ACTIONS", "start", "stop", "view", "is_running", "MODE"]


def run_action(ctx: Any, project_id: str, action: str) -> None:
    """The job body (worker or thread)."""
    engine.run(project_id, action, ctx.cancel, ctx.log)


def start(project_id: str, action: str) -> None:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    project = store.get_project(project_id)
    if project is None:
        raise KeyError(project_id)
    _RUNNER.start(project_id, action, run_action, project_id, action,
                  description=f"schema-copy: {action} {project.get('name', project_id)}")


def stop(project_id: str) -> bool:
    return _RUNNER.stop(project_id)


def view(project_id: str) -> dict[str, Any]:
    return _RUNNER.view(project_id)


def is_running(project_id: str) -> bool:
    return _RUNNER.is_running(project_id)

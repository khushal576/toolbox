"""
core.state — shared clients for state that must live OUTSIDE the web process (roadmap phase B, ADR-001).

    from core.state import db, sessions, objects
    with db.connection() as conn: ...                 # Postgres: durable records (one schema per tool)
    sessions.SessionStore("df-studio").set(sid, {...}) # Redis: short-lived sessions (TTL), later queues
    objects.put_bytes(objects.key("df-studio", sid, "frame.parquet"), data)   # S3 API: files

Everything is configured by env vars only (core/state/config.py) and connects lazily on first use, so a tool
that never touches state pays nothing. Heavy client libraries (psycopg_pool, redis, boto3) are imported inside
the submodules, not here. `health()` never raises: it reports each service.
"""

from __future__ import annotations

import time
from typing import Any, Callable


def _probe(fn: Callable[[], dict]) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        detail = fn()
        return {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), **detail}
    except Exception as exc:  # noqa: BLE001 - health must report, never crash the caller
        return {"ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "error": f"{type(exc).__name__}: {exc}"}


def health() -> dict[str, Any]:
    """Status of every state service: {"postgres": {...}, "redis": {...}, "objects": {...}, "ok": bool}."""
    from core.state import db, objects, sessions

    out = {"postgres": _probe(db.health), "redis": _probe(sessions.health), "objects": _probe(objects.health)}

    def _jobs() -> dict:
        from core import jobs
        return jobs.health()

    out["jobs"] = _probe(_jobs)  # roadmap B4: at least one worker must be listening

    def _vault() -> dict:
        from core import vault
        return vault.health()

    out["vault"] = _probe(_vault)  # roadmap B7: storage reachable + the key matches the stored secrets
    out["ok"] = all(v["ok"] for v in out.values())
    return out

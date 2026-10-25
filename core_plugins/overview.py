"""
Data for the workspace Status page (roadmap E1). Two halves, so the gateway stays lean:

- `containers()` — runs IN THE GATEWAY (needs only httpx): every container of this compose project through the
  docker-proxy (list + inspect + stats, all read-only): state, health, uptime, restarts, CPU %, memory vs limit.
- `jobs_summary()` / `storage_summary()` — run in `rt-data` (they need rq / boto3 / psycopg, which a gateway worker
  would otherwise keep in memory for good); the gateway fetches them with the state health in one call
  (`/api/state/overview`, see main.py).

Nothing here stores anything: the page asks, this answers from live sources, results are cached a few seconds so
several open tabs don't multiply the work.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from typing import Any

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float):
    hit = _cache.get(key)
    return hit[1] if hit and time.monotonic() - hit[0] < ttl else None


def _store(key: str, value: Any) -> Any:
    _cache[key] = (time.monotonic(), value)
    return value


# ---- containers (gateway) ----------------------------------------------------------------------------------------

def _cpu(s: dict[str, Any]) -> float | None:
    try:
        cpu = s["cpu_stats"]["cpu_usage"]["total_usage"] - s["precpu_stats"]["cpu_usage"]["total_usage"]
        system = s["cpu_stats"]["system_cpu_usage"] - s["precpu_stats"]["system_cpu_usage"]
        n = s["cpu_stats"].get("online_cpus") or 1
        return round(cpu / system * n * 100.0, 1) if system > 0 and cpu >= 0 else 0.0
    except (KeyError, TypeError):
        return None


def _mem(s: dict[str, Any]) -> int | None:
    m = s.get("memory_stats") or {}
    if "usage" not in m:
        return None
    st = m.get("stats") or {}
    return int(m["usage"] - st.get("inactive_file", st.get("total_inactive_file", 0)))  # what `docker stats` shows


def _health(status: str) -> str | None:
    for word in ("healthy", "unhealthy", "health: starting"):
        if f"({word})" in status:
            return "starting" if word == "health: starting" else word
    return None


async def containers(docker_url: str) -> dict[str, Any]:
    """Every container of this compose project. Cached 4 s."""
    hit = _cached("containers", 4.0)
    if hit is not None:
        return hit
    import httpx

    async with httpx.AsyncClient(base_url=docker_url, timeout=httpx.Timeout(10.0, read=20.0)) as client:
        me = await client.get(f"/containers/{socket.gethostname()}/json")  # the gateway's own container
        project = me.json()["Config"]["Labels"].get("com.docker.compose.project") if me.status_code == 200 else None
        filters = json.dumps({"label": [f"com.docker.compose.project={project}"]}) if project else None
        lst = (await client.get("/containers/json", params={"all": "1", **({"filters": filters} if filters else {})})).json()

        async def one(c: dict[str, Any]) -> dict[str, Any]:
            name = c["Names"][0].lstrip("/")
            row = {"name": name, "service": c["Labels"].get("com.docker.compose.service", name),
                   "replica": int(c["Labels"].get("com.docker.compose.container-number", "1")),
                   "image": c.get("Image"), "state": c["State"], "status": c.get("Status", ""),
                   "health": _health(c.get("Status", "")), "cpu": None, "mem": None, "mem_limit": None,
                   "restarts": None, "started_at": None}
            insp = await client.get(f"/containers/{name}/json")
            if insp.status_code == 200:
                j = insp.json()
                row["restarts"] = j.get("RestartCount")
                row["started_at"] = (j.get("State") or {}).get("StartedAt")
                row["mem_limit"] = (j.get("HostConfig") or {}).get("Memory") or None  # 0 = no limit
                row["exit_code"] = (j.get("State") or {}).get("ExitCode")
            if c["State"] == "running":
                st = await client.get(f"/containers/{name}/stats", params={"stream": "false"})
                if st.status_code == 200:
                    s = st.json()
                    row["cpu"], row["mem"] = _cpu(s), _mem(s)
            return row

        rows = await asyncio.gather(*(one(c) for c in lst), return_exceptions=True)
    out = [r for r in rows if isinstance(r, dict)]
    out.sort(key=lambda r: (r["service"], r["replica"]))
    return _store("containers", {"project": project, "containers": out})


async def _project_names(client) -> set[str]:
    me = await client.get(f"/containers/{socket.gethostname()}/json")
    project = me.json()["Config"]["Labels"].get("com.docker.compose.project") if me.status_code == 200 else None
    if not project:
        return set()
    filters = json.dumps({"label": [f"com.docker.compose.project={project}"]})
    return {c["Names"][0].lstrip("/") for c in (await client.get("/containers/json",
                                                                 params={"all": "1", "filters": filters})).json()}


def _demux(raw: bytes) -> str:
    """Docker's log stream without a TTY: frames of [stream, 0, 0, 0, size(4 bytes, big endian)] + payload."""
    out, i = [], 0
    while i + 8 <= len(raw) and raw[i] in (0, 1, 2) and raw[i + 1:i + 4] == b"\x00\x00\x00":
        size = int.from_bytes(raw[i + 4:i + 8], "big")
        out.append(raw[i + 8:i + 8 + size])
        i += 8 + size
    if i == 0:  # a TTY container: plain text
        return raw.decode("utf-8", "replace")
    return b"".join(out).decode("utf-8", "replace")


async def logs(docker_url: str, name: str, lines: int = 200) -> str:
    """The last `lines` log lines of one container of THIS project (roadmap E3). Read-only, nothing kept."""
    import httpx

    async with httpx.AsyncClient(base_url=docker_url, timeout=httpx.Timeout(10.0, read=20.0)) as client:
        if name not in await _project_names(client):
            raise KeyError(name)
        r = await client.get(f"/containers/{name}/logs", params={"stdout": "1", "stderr": "1", "timestamps": "1",
                                                                 "tail": str(max(1, min(lines, 2000)))})
        r.raise_for_status()
        return _demux(r.content)


async def container_states(docker_url: str) -> dict[str, Any]:
    """Cheap version of containers() for the alert badge: list only (no inspect, no stats)."""
    import httpx

    async with httpx.AsyncClient(base_url=docker_url, timeout=10.0) as client:
        names = await _project_names(client)
        lst = (await client.get("/containers/json", params={"all": "1"})).json()
    return {"containers": [{"name": c["Names"][0].lstrip("/"), "service": c["Labels"].get("com.docker.compose.service", ""),
                            "state": c["State"], "health": _health(c.get("Status", "")), "restarts": None}
                           for c in lst if c["Names"][0].lstrip("/") in names]}


# ---- jobs + storage (rt-data) ------------------------------------------------------------------------------------

def _tool_of(job_id: str) -> str:
    """RQ job ids are '<tool>-<key>-<suffix>' (core/jobs/runner.py); tool names contain '-' themselves."""
    parts = job_id.split("-")
    return "-".join(parts[:-2]) if len(parts) >= 3 else job_id


def jobs_summary() -> dict[str, Any]:
    """Queue, workers, and per-tool counts of running / failed (kept 7 days) / finished (kept 1 h) jobs. Cached 5 s."""
    hit = _cached("jobs", 5.0)
    if hit is not None:
        return hit
    from rq import Worker
    from rq.job import Job
    from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry

    from core import jobs

    conn, q = jobs.rq_connection(), jobs.queue()
    per_tool: dict[str, dict[str, int]] = {}

    def bump(ids, field):
        for jid in ids:
            per_tool.setdefault(_tool_of(jid), {"waiting": 0, "running": 0, "failed": 0, "finished": 0})[field] += 1

    bump(q.get_job_ids(), "waiting")
    bump(StartedJobRegistry(queue=q).get_job_ids(), "running")
    failed_ids = FailedJobRegistry(queue=q).get_job_ids()
    bump(failed_ids, "failed")
    bump(FinishedJobRegistry(queue=q).get_job_ids(), "finished")
    recent = []
    for job in Job.fetch_many(failed_ids[-8:], connection=conn):
        if job is None:
            continue
        exc = (job.latest_result().exc_string if job.latest_result() else "") or ""
        recent.append({"id": job.id, "tool": _tool_of(job.id), "description": job.description,
                       "ended_at": job.ended_at.isoformat() if job.ended_at else None,
                       "error": (exc.strip().splitlines() or [""])[-1][:300]})
    workers = Worker.all(connection=conn)
    return _store("jobs", {
        "waiting": len(q), "workers": len(workers),
        "busy": sum(1 for w in workers if w.get_state() == "busy"),
        "per_tool": dict(sorted(per_tool.items())), "recent_failures": list(reversed(recent)),
    })


def storage_summary() -> dict[str, Any]:
    """S3 storage per tool prefix + Postgres size per tool schema. Cached 60 s (listing every object isn't free)."""
    hit = _cached("storage", 60.0)
    if hit is not None:
        return hit
    out: dict[str, Any] = {"objects": None, "postgres": None}
    try:
        from core.state import objects

        per: dict[str, dict[str, int]] = {}
        for o in objects.list_objects(""):
            p = per.setdefault(o["key"].split("/", 1)[0], {"files": 0, "bytes": 0})
            p["files"] += 1
            p["bytes"] += int(o["size"])
        out["objects"] = dict(sorted(per.items(), key=lambda kv: -kv[1]["bytes"]))
    except Exception as exc:  # noqa: BLE001 - the page shows the problem instead
        out["objects_error"] = str(exc)[:200]
    try:
        from core.state import db

        with db.connection() as conn:
            rows = conn.execute(
                "SELECT n.nspname, COALESCE(SUM(pg_total_relation_size(c.oid)), 0) "
                "FROM pg_namespace n LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relkind IN ('r', 'm') "
                "WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema' "
                "GROUP BY 1 ORDER BY 2 DESC").fetchall()
            total = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        out["postgres"] = {"schemas": {r[0]: int(r[1]) for r in rows}, "database_bytes": int(total)}
    except Exception as exc:  # noqa: BLE001
        out["postgres_error"] = str(exc)[:200]
    return _store("storage", out)


def attention(overview: dict[str, Any]) -> list[dict[str, str]]:
    """Plain-language list of what needs a look (shown at the top of the page). Pure function of the overview."""
    items: list[dict[str, str]] = []
    on_demand = set(overview.get("on_demand_services") or [])
    pools = set(overview.get("pool_services") or [])
    for c in (overview.get("containers") or {}).get("containers", []):
        if c["health"] == "unhealthy":
            items.append({"level": "error", "text": f"{c['name']} is unhealthy"})
        if c["state"] in ("exited", "dead") and c["service"] not in on_demand and c["service"] not in pools:
            items.append({"level": "error", "text": f"{c['name']} is stopped (exit code {c.get('exit_code')})"})
        if c["state"] == "restarting" or (c.get("restarts") or 0) > 3:
            items.append({"level": "warn", "text": f"{c['name']} keeps restarting ({c.get('restarts')} restarts)"})
        if c.get("mem") and c.get("mem_limit") and c["mem"] > 0.85 * c["mem_limit"]:
            items.append({"level": "warn", "text": f"{c['name']} uses {c['mem'] * 100 // c['mem_limit']}% of its memory limit"})
    for p in (overview.get("tools") or {}).get("plugins", []):
        if p.get("state") == "failed":
            items.append({"level": "error", "text": f"{p['title']} failed to load: {p.get('error') or 'see logs'}"})
    state = overview.get("state") or {}
    for svc in ("postgres", "redis", "objects", "jobs", "vault"):
        v = state.get(svc)
        if isinstance(v, dict) and not v.get("ok"):
            items.append({"level": "error", "text": f"{svc}: {v.get('error') or 'not ok'}"})
        elif isinstance(v, dict) and v.get("warning"):
            items.append({"level": "warn", "text": f"{svc}: {v['warning']}"})
    if state.get("error"):
        items.append({"level": "error", "text": state["error"]})
    jobs = overview.get("jobs") or {}
    if jobs.get("waiting", 0) >= 5:
        items.append({"level": "warn", "text": f"{jobs['waiting']} background jobs are waiting for a worker"})
    hour_ago = time.time() - 3600
    by_tool: dict[str, int] = {}
    for e in overview.get("errors") or []:
        if e.get("ts", 0) > hour_ago:
            by_tool[e["tool"]] = by_tool.get(e["tool"], 0) + 1
    for tool, n in sorted(by_tool.items(), key=lambda kv: -kv[1]):
        items.append({"level": "warn", "text": f"{tool}: {n} server error(s) in the last hour — see Recent errors"})
    day_ago = time.time() - 86400
    fresh = [f for f in jobs.get("recent_failures") or []
             if f.get("ended_at") and _ts(f["ended_at"]) > day_ago]
    if fresh:
        items.append({"level": "warn", "text": f"{len(fresh)} background job(s) crashed in the last 24 h"})
    return items


def _ts(iso: str) -> float:
    from datetime import datetime, timezone

    d = datetime.fromisoformat(iso)
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()

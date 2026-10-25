"""
Replica autoscaling on one machine (roadmap D3) — part of the gateway's supervisor.

Compose creates a POOL of `max` containers for a scalable service (`deploy.replicas`); the autoscaler keeps between
`min` and `max` of them RUNNING by starting/stopping pool members — it never creates or removes containers, so the
docker-proxy still allows only start/stop (+ read-only list/stats).

Two kinds of services:
  cpu    a runtime whose plugin has `scaling.max > 1` (today rt-datadiff, manifest min 2 / max 4): average CPU of
         its running replicas (Docker stats, % of one core) > UP_CPU → one more; < DOWN_CPU for DOWN_AFTER s → one
         fewer. Requests are spread over the running+healthy ones by core_plugins/balancer.py.
  queue  the `worker` service (TOOLBOX_WORKER_SCALING="min:max", e.g. 1:3): jobs WAITING in the Redis queue → one
         more; queue empty for DOWN_AFTER s → stop one IDLE worker (RQ says idle; a busy worker is never stopped,
         and it gets 120 s for a warm shutdown).
After any change the service waits COOLDOWN s, so one burst doesn't add every replica at once.
Runs only in the supervisor leader (one gateway process), every TICK s.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger("toolbox.autoscale")

TICK = 5.0
COOLDOWN = 20.0
UP_CPU = 60.0
DOWN_CPU = 15.0
DOWN_AFTER = 45.0


def _cpu_percent(s: dict[str, Any]) -> float:
    try:
        cpu = s["cpu_stats"]["cpu_usage"]["total_usage"] - s["precpu_stats"]["cpu_usage"]["total_usage"]
        system = s["cpu_stats"]["system_cpu_usage"] - s["precpu_stats"]["system_cpu_usage"]
        ncpu = s["cpu_stats"].get("online_cpus") or len(s["cpu_stats"]["cpu_usage"].get("percpu_usage") or [1])
        return cpu / system * ncpu * 100.0 if system > 0 and cpu >= 0 else 0.0
    except (KeyError, TypeError):
        return 0.0


class ScaledService:
    def __init__(self, service: str, kind: str, min_n: int, max_n: int, docker_url: str):
        self.service, self.kind, self.min, self.max, self.docker_url = service, kind, min_n, max_n, docker_url
        self.last_change = float("-inf")  # not 0.0: monotonic time can be smaller than COOLDOWN on a fresh boot
        self.low_since: float | None = None
        self.last: dict[str, Any] = {}      # what the last tick saw (for /api/workspace/runtimes)
        self._prev: str | None = None

    def _client(self):
        import httpx

        return httpx.AsyncClient(base_url=self.docker_url, timeout=httpx.Timeout(10.0, read=30.0))

    async def containers(self, client) -> list[dict[str, Any]]:
        filters = json.dumps({"label": [f"com.docker.compose.service={self.service}"]})
        r = await client.get("/containers/json", params={"all": "1", "filters": filters})
        r.raise_for_status()
        out = [{"name": c["Names"][0].lstrip("/"), "id": c["Id"], "running": c["State"] == "running",
                "n": int(c["Labels"].get("com.docker.compose.container-number", "0"))} for c in r.json()]
        return sorted(out, key=lambda c: c["n"])

    # ---- metrics ------------------------------------------------------------------------------------------------
    async def _cpu(self, client, running: list[dict[str, Any]]) -> float:
        async def one(c):
            r = await client.get(f"/containers/{c['name']}/stats", params={"stream": "false"})
            return _cpu_percent(r.json()) if r.status_code == 200 else 0.0
        vals = await asyncio.gather(*(one(c) for c in running), return_exceptions=True)
        nums = [v for v in vals if isinstance(v, float)]
        return sum(nums) / len(nums) if nums else 0.0

    @staticmethod
    def _queue() -> tuple[int, dict[str, str]]:
        """(jobs waiting, {container hostname: rq state}) — RQ worker names carry the container hostname."""
        from rq import Worker

        from core import jobs

        workers = Worker.all(connection=jobs.rq_connection())
        states = {}
        for w in workers:
            parts = w.name.split("-")  # toolbox-worker-<hostname>-<pid>-<suffix>
            if len(parts) >= 5:
                states[parts[2]] = w.get_state()
        return len(jobs.queue()), states

    # ---- shared view (only the leader ticks; any gateway process answers /api/workspace/runtimes) ---------------
    STATE_KEY = "toolbox:scale:{}"

    def publish(self, did: str | None) -> None:
        try:
            from core_plugins.supervisor import _redis

            r = _redis()
            if r is not None:
                r.set(self.STATE_KEY.format(self.service), json.dumps({**self.last, "last_action": did or self._prev,
                                                                        "at": time.time()}), ex=60)
        except Exception:  # noqa: BLE001 - status only
            pass
        if did:
            self._prev = did

    def shared_state(self) -> dict[str, Any]:
        try:
            from core_plugins.supervisor import _redis

            r = _redis()
            raw = r.get(self.STATE_KEY.format(self.service)) if r is not None else None
            return json.loads(raw) if raw else dict(self.last)
        except Exception:  # noqa: BLE001
            return dict(self.last)

    # ---- one decision -------------------------------------------------------------------------------------------
    async def tick(self) -> str | None:
        did = await self._decide()
        await asyncio.to_thread(self.publish, did)
        return did

    async def _decide(self) -> str | None:
        """Look, maybe start/stop one container. Returns what it did (for logs/tests) or None."""
        now = time.monotonic()
        async with self._client() as client:
            pool = await self.containers(client)
            running = [c for c in pool if c["running"]]
            stopped = [c for c in pool if not c["running"]]
            if self.kind == "cpu":
                load = await self._cpu(client, running) if running else 0.0
                want_up, low = load > UP_CPU, load < DOWN_CPU
                self.last = {"running": len(running), "pool": len(pool), "cpu_avg": round(load, 1)}
                idle_ids: set[str] | None = None
            else:
                waiting, states = await asyncio.to_thread(self._queue)
                want_up, low = waiting > 0, waiting == 0
                idle_ids = {h for h, st in states.items() if st == "idle"}
                self.last = {"running": len(running), "pool": len(pool), "waiting": waiting,
                             "busy": sum(1 for s in states.values() if s == "busy")}

            # below min (e.g. after a manual stop) or above max: fix first, no cooldown
            if len(running) < self.min and stopped:
                return await self._start(client, stopped[0], "below min")
            if now - self.last_change < COOLDOWN:
                return None
            if want_up:
                self.low_since = None
                if len(running) < self.max and stopped:
                    return await self._start(client, stopped[0], self._why())
                return None
            if not low:
                self.low_since = None
                return None
            self.low_since = self.low_since or now
            if now - self.low_since < DOWN_AFTER or len(running) <= self.min:
                return None
            candidates = list(reversed(running))  # highest number first
            if idle_ids is not None:  # workers: only one RQ reports idle
                candidates = [c for c in candidates if c["id"][:12] in idle_ids]
            if not candidates:
                return None
            return await self._stop(client, candidates[0])

    def _why(self) -> str:
        return f"cpu {self.last.get('cpu_avg')}%" if self.kind == "cpu" else f"{self.last.get('waiting')} job(s) waiting"

    async def _start(self, client, c: dict[str, Any], why: str) -> str:
        r = await client.post(f"/containers/{c['name']}/start")
        if r.status_code not in (204, 304):
            logger.error("%s: start %s refused (%s)", self.service, c["name"], r.status_code)
            return f"start refused {c['name']}"
        self.last_change, self.low_since = time.monotonic(), None
        logger.warning("%s: scaled UP — started %s (%s)", self.service, c["name"], why)
        return f"up {c['name']}"

    async def _stop(self, client, c: dict[str, Any]) -> str:
        t = "120" if self.kind == "queue" else "15"  # RQ warm shutdown / uvicorn graceful shutdown
        r = await client.post(f"/containers/{c['name']}/stop", params={"t": t})
        if r.status_code not in (204, 304):
            logger.error("%s: stop %s refused (%s)", self.service, c["name"], r.status_code)
            return f"stop refused {c['name']}"
        self.last_change, self.low_since = time.monotonic(), None
        logger.warning("%s: scaled DOWN — stopped %s", self.service, c["name"])
        return f"down {c['name']}"


def scaled_runtimes(manifests) -> dict[str, tuple[int, int]]:
    """{runtime: (min, max)} for runtimes with a plugin that may run several replicas (scaling.max > 1)."""
    out: dict[str, tuple[int, int]] = {}
    for m in manifests:
        if m.kind == "python" and not m.singleton and m.runtime and m.scaling.max > 1:
            lo, hi = out.get(m.runtime, (0, 1))
            out[m.runtime] = (max(lo, m.scaling.min, 1), max(hi, m.scaling.max))
    return out

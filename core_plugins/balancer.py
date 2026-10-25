"""
Health-aware round-robin over a runtime's replicas (roadmap D3) — part of the gateway.

For runtimes that can have several replicas (any plugin with `scaling.max > 1`, today: datadiff) the gateway asks
Docker (through docker-proxy) every few seconds which of the service's containers are running AND healthy, and
sends each request to the next one in turn. Docker's own DNS answer (one name → all IPs) spreads CONNECTIONS, not
requests, and keeps sending to a stopped/unhealthy replica until the connection breaks; this doesn't.

A replica that refuses a connection is skipped for COOLDOWN seconds and the request goes to the next one (only on
connect errors — nothing has been sent yet, so it is safe to retry any request). With no Docker access or no healthy
replica known, the plain service name is used (Docker DNS), exactly as before D3.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from typing import Any

logger = logging.getLogger("toolbox.balancer")

REFRESH_EVERY = 3.0
COOLDOWN = 10.0


class Balancer:
    def __init__(self, service: str, fallback_url: str, docker_url: str, port: int = 8080):
        self.service, self.fallback_url, self.docker_url, self.port = service, fallback_url.rstrip("/"), docker_url, port
        self.targets: list[dict[str, Any]] = []      # [{name, ip, healthy}] of running containers
        self._bad: dict[str, float] = {}             # ip → monotonic time it may be used again
        self._rr = itertools.count()
        self._refreshed = 0.0

    async def refresh(self) -> None:
        import httpx

        filters = json.dumps({"label": [f"com.docker.compose.service={self.service}"]})
        try:
            async with httpx.AsyncClient(base_url=self.docker_url, timeout=5.0) as client:
                r = await client.get("/containers/json", params={"filters": filters})  # running only
                r.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - keep the last known list; fall back to DNS if empty
            logger.debug("%s: cannot list replicas: %s", self.service, exc)
            return
        out = []
        for c in r.json():
            nets = (c.get("NetworkSettings") or {}).get("Networks") or {}
            ip = next((n.get("IPAddress") for n in nets.values() if n.get("IPAddress")), None)
            if ip:
                status = c.get("Status", "")
                # healthy, or no healthcheck at all; "(health: starting)" / "(unhealthy)" get no traffic
                out.append({"name": c["Names"][0].lstrip("/"), "ip": ip,
                            "healthy": "(healthy)" in status or "health" not in status})
        self.targets = sorted(out, key=lambda t: t["name"])
        self._refreshed = time.monotonic()

    def healthy(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        return [t for t in self.targets if t["healthy"] and self._bad.get(t["ip"], 0) <= now]

    def pick(self) -> str:
        """Base URL for the next request."""
        ok = self.healthy()
        if not ok:
            return self.fallback_url
        t = ok[next(self._rr) % len(ok)]
        return f"http://{t['ip']}:{self.port}"

    def mark_failed(self, base_url: str) -> None:
        ip = base_url.split("//", 1)[-1].split(":", 1)[0]
        self._bad[ip] = time.monotonic() + COOLDOWN
        logger.warning("%s: replica %s refused a connection — skipped for %ss", self.service, ip, COOLDOWN)

    async def run(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(REFRESH_EVERY)

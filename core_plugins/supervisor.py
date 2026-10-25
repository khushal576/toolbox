"""
On-demand runtime containers (roadmap C3) — part of the gateway.

A runtime is ON-DEMAND when every python plugin it serves is tier 4 with `scaling.min: 0` (today: latex, pgtools,
ssh). Its container is started on the first request after it went to sleep and stopped again after
`scaling.idle_timeout_s` (the largest of its plugins; TOOLBOX_IDLE_TIMEOUT_S overrides it, e.g. for tests) without
traffic. `light` and `data` stay always on.

Docker is reached ONLY through the `docker-proxy` service (docker-socket-proxy with a custom rule set: list/inspect
containers, start/stop containers named `*-rt-<runtime>-<n>` — nothing else; see docker-compose.yml). The gateway
never sees the Docker socket itself.

Shared between gateway workers through Redis:
  toolbox:sup:last:<runtime>   last request time (refreshed at most every 5 s per process, and while a response
                               body is still streaming), so a long download never counts as idle
  toolbox:sup:leader           which gateway process runs the idle sweep (SET NX, 45 s TTL, renewed every 15 s)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("toolbox.supervisor")

LAST_KEY = "toolbox:sup:last:{}"
LEADER_KEY = "toolbox:sup:leader"
TOUCH_EVERY = 5.0
SWEEP_EVERY = 15.0
START_TIMEOUT = 60.0


def _redis():
    try:
        from core.state import config, sessions
    except ImportError:
        return None
    return sessions.client() if config.load().redis_url else None


class RuntimeSupervisor:
    """Start/stop one runtime's container. `state()` → running | starting | asleep | missing | unknown."""

    def __init__(self, runtime: str, base_url: str, docker_url: str, idle_s: int):
        self.runtime, self.base_url, self.docker_url, self.idle_s = runtime, base_url.rstrip("/"), docker_url, idle_s
        self.service = f"rt-{runtime}"
        self._container: str | None = None
        self._state: str = "unknown"
        self._state_at = 0.0
        self._touched = 0.0
        self._start_lock: asyncio.Lock | None = None
        self._starting = False

    # ---- docker (through the socket proxy) ------------------------------------------------------------------
    def _client(self):
        import httpx

        return httpx.AsyncClient(base_url=self.docker_url, timeout=httpx.Timeout(10.0, read=30.0))

    async def _find(self, client) -> dict[str, Any] | None:
        filters = json.dumps({"label": [f"com.docker.compose.service={self.service}"]})
        r = await client.get("/containers/json", params={"all": "1", "filters": filters})
        r.raise_for_status()
        found = r.json()
        if len(found) > 1:
            logger.warning("%s: %d containers carry this service label; using the first", self.service, len(found))
        if not found:
            return None
        self._container = found[0]["Names"][0].lstrip("/")
        return found[0]

    async def refresh(self) -> str:
        """Ask Docker (cached 2 s)."""
        if self._starting:
            return "starting"
        if time.monotonic() - self._state_at < 2.0:
            return self._state
        try:
            async with self._client() as client:
                c = await self._find(client)
            self._state = "missing" if c is None else ("running" if c["State"] == "running" else "asleep")
        except Exception as exc:  # noqa: BLE001 - docker-proxy down: report, don't break routing
            logger.warning("%s: cannot ask Docker: %s", self.service, exc)
            self._state = "unknown"
        self._state_at = time.monotonic()
        return self._state

    def state(self) -> str:
        return "starting" if self._starting else self._state

    async def _healthy(self) -> bool:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                return (await client.get(f"{self.base_url}/healthz")).status_code == 200
        except httpx.HTTPError:
            return False

    async def ensure_running(self) -> bool:
        """Start the container if it sleeps and wait until it answers /healthz. True when it is ready."""
        if await self.refresh() in ("running", "unknown"):  # unknown: try the request anyway
            return True
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        async with self._start_lock:  # concurrent first requests in this process start it once
            if await self.refresh() == "running" and await self._healthy():
                return True
            self._starting = True
            try:
                async with self._client() as client:
                    if self._container is None:
                        await self._find(client)
                    if self._container is None:
                        return False
                    r = await client.post(f"/containers/{self._container}/start")
                    if r.status_code not in (204, 304):  # 304 = already started (another gateway worker)
                        logger.error("%s: start refused (%s): %s", self.service, r.status_code, r.text[:200])
                        return False
                logger.info("%s: started on demand", self.service)
                self.touch(force=True)
                deadline = time.monotonic() + START_TIMEOUT
                while time.monotonic() < deadline:
                    if await self._healthy():
                        self._state, self._state_at = "running", time.monotonic()
                        return True
                    await asyncio.sleep(0.5)
                logger.error("%s: started but not healthy after %ss", self.service, START_TIMEOUT)
                return False
            finally:
                self._starting = False

    def start_in_background(self) -> None:
        if not self._starting:
            asyncio.get_running_loop().create_task(self.ensure_running())

    async def stop(self) -> None:
        async with self._client() as client:
            if self._container is None:
                await self._find(client)
            if self._container is None:
                return
            r = await client.post(f"/containers/{self._container}/stop", params={"t": "10"})
            if r.status_code not in (204, 304):
                logger.error("%s: stop refused (%s): %s", self.service, r.status_code, r.text[:200])
                return
        self._state, self._state_at = "asleep", time.monotonic()
        logger.info("%s: stopped after %ss without requests", self.service, self.idle_s)

    # ---- activity (shared through Redis) ---------------------------------------------------------------------
    def touch(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._touched < TOUCH_EVERY:
            return
        self._touched = now
        try:
            r = _redis()
            if r is not None:
                r.set(LAST_KEY.format(self.runtime), str(time.time()), ex=7 * 86400)
        except Exception:  # noqa: BLE001 - activity tracking must never fail a request
            pass

    def idle_for(self) -> float | None:
        r = _redis()
        if r is None:
            return None
        raw = r.get(LAST_KEY.format(self.runtime))
        if raw is None:  # never used since Redis started: count from now, so it gets one full idle period
            r.set(LAST_KEY.format(self.runtime), str(time.time()), ex=7 * 86400)
            return 0.0
        return time.time() - float(raw)


class Supervisor:
    """All on-demand runtimes + the idle sweep (one leader among the gateway's worker processes)."""

    def __init__(self, runtimes: dict[str, RuntimeSupervisor]):
        self.runtimes = runtimes
        self._me = f"{os.uname().nodename}:{os.getpid()}"

    def _lead(self) -> bool:
        r = _redis()
        if r is None:
            return False
        if r.set(LEADER_KEY, self._me, nx=True, ex=45):
            return True
        if r.get(LEADER_KEY) == self._me:
            r.expire(LEADER_KEY, 45)
            return True
        return False

    async def sweep_once(self) -> None:
        if not await asyncio.to_thread(self._lead):
            return
        for sup in self.runtimes.values():
            if await sup.refresh() != "running":
                continue
            idle = await asyncio.to_thread(sup.idle_for)
            if idle is not None and idle > sup.idle_s:
                await sup.stop()

    async def run(self) -> None:
        while True:
            try:
                await self.sweep_once()
            except Exception:  # noqa: BLE001 - keep sweeping
                logger.exception("idle sweep failed")
            await asyncio.sleep(SWEEP_EVERY)


def on_demand_runtimes(manifests) -> dict[str, int]:
    """{runtime: idle_timeout_s} for runtimes whose python (non-singleton) plugins are ALL tier 4 + scaling.min 0."""
    by_rt: dict[str, list] = {}
    for m in manifests:
        if m.kind == "python" and not m.singleton and m.runtime:
            by_rt.setdefault(m.runtime, []).append(m)
    out = {}
    override = os.environ.get("TOOLBOX_IDLE_TIMEOUT_S")
    for rt, ms in by_rt.items():
        if all(m.tier == 4 and m.scaling.min == 0 for m in ms):
            out[rt] = int(override) if override else max(m.scaling.idle_timeout_s for m in ms)
    return out

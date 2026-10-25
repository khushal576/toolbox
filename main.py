"""
main.py

Single entrypoint for the whole toolbox website — one process, one
container, one Dockerfile. Serves the home page at "/" and mounts every
tool's own FastAPI app under /tools/<name>/ in the same process (no network
hop, no reverse proxy — just an in-process ASGI mount).

Adding a tool
-------------
Tools are plugins described by a `manifest.yaml` in their folder (spec:
docs/architecture/plugin-manifest.md, roadmap A1/A2). At startup this file
calls `core_plugins.discover()` once; every valid manifest becomes a home-page
card (ordered by `order`, then title).

Lazy loading (roadmap A3): every enabled `kind: python` plugin is mounted as a
`LazyApp` — its module is imported on the tool's FIRST request, not at
startup, so unused tools cost no memory. A failed import still only breaks
that one tool (503 page + "Unavailable" card). Tools turned off in
`workspace.yaml` (core_plugins/workspace.py) are mounted as `DisabledApp`:
never imported, hidden from the home page. Never add a top-level
`from <tool> import app` here. A broken manifest is skipped and logged.

Workspace UI (roadmap A4): "/" serves core_plugins/ui/workspace.html (sidebar,
tools in tabs, settings). Each tool is mounted through a `Slot`, so
POST /api/workspace/plugins/<name> {"enabled": bool} turns a tool on/off
immediately (and saves workspace.yaml) without a restart.
State per tool: GET /api/workspace/status.

Several worker processes (roadmap B9): the web role runs with N uvicorn workers. Every worker re-reads
workspace.yaml when its mtime changes (`_sync_workspace`), so a switch flipped on one worker reaches all.
`singleton: true` plugins (sql-studio, schema-map: one live DB pool, password never stored) run in ONE dedicated
process — the same image started with TOOLBOX_ROLE=singletons, which mounts only them — and every web worker
forwards their traffic there with a `ProxyApp` when TOOLBOX_SINGLETON_URL is set.

Gateway (roadmap C2): with TOOLBOX_RUNTIME_URLS set, the web role imports NO tool at all — every python plugin is
proxied to the runtime image of its manifest `runtime:` (TOOLBOX_ROLE=runtime there, roadmap C1). Static/external
plugins are still served here. Without that variable (a
standalone dev run) they are mounted in-process as before, and the app must then run with one worker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from pydantic import BaseModel

from core_plugins import (DisabledApp, ExternalApp, LazyApp, ProxyApp, Slot, StaticApp, default_path, discover,
                          load_workspace)
from core_plugins import metrics
from core_plugins.autoscale import ScaledService, scaled_runtimes
from core_plugins.balancer import Balancer
from core_plugins.supervisor import RuntimeSupervisor, Supervisor, on_demand_runtimes

logger = logging.getLogger("toolbox")

app = FastAPI(title="Toolbox", description="One-stop access to internal tools.")

_REPO = Path(__file__).resolve().parent
# "web" (default): every tool, singletons proxied when TOOLBOX_SINGLETON_URL is set.
# "singletons": only the singleton plugins, in this one process (the `singletons` compose service).
# "runtime": only the python plugins whose manifest `runtime:` is TOOLBOX_RUNTIME, singletons excluded (roadmap C1:
#            one image per runtime — light / data / pgtools / ssh / latex; the gateway routes to them from C2).
ROLE = os.environ.get("TOOLBOX_ROLE", "web")
RUNTIME = (os.environ.get("TOOLBOX_RUNTIME") or "").strip()
SINGLETON_URL = (os.environ.get("TOOLBOX_SINGLETON_URL") or "").strip()
# Gateway mode (roadmap C2): "light=http://rt-light:8080,data=http://rt-data:8080,…" — in the web role every python
# plugin whose runtime has a URL here is proxied there instead of imported in this process.
RUNTIME_URLS = {k.strip(): v.strip() for k, v in
                (p.split("=", 1) for p in (os.environ.get("TOOLBOX_RUNTIME_URLS") or "").split(",") if "=" in p)}
if ROLE not in ("web", "singletons", "runtime"):
    raise SystemExit(f"TOOLBOX_ROLE must be 'web', 'singletons' or 'runtime', not {ROLE!r}")
if ROLE == "runtime" and RUNTIME not in ("light", "data", "pgtools", "latex", "ssh", "datadiff"):
    raise SystemExit(f"TOOLBOX_ROLE=runtime needs TOOLBOX_RUNTIME=light|data|pgtools|latex|ssh|datadiff, not {RUNTIME!r}")

# Discovered once at startup: mounting happens at startup too, so a manifest
# change needs a restart either way. Errors/warnings are logged, never raised.
# Custom apps (roadmap A5): folders with a manifest.yaml of kind static/external, bind-mounted in compose so a new
# app needs no image rebuild. Python plugins are refused there (see core_plugins/loader.py EXTRA_DIR_KINDS).
_PLUGINS_DIR = Path(os.environ.get("TOOLBOX_PLUGINS_DIR") or _REPO / "plugins")
_registry = discover(_REPO, extra_dirs=[_PLUGINS_DIR] if _PLUGINS_DIR.is_dir() else [])
for _err in _registry.errors:
    logger.error("Plugin manifest problem — plugin skipped: %s", _err)
for _warn in _registry.warnings:
    logger.warning("Plugin manifest warning: %s", _warn)

# On-demand runtimes (roadmap C3): only in gateway mode, and only with the docker-proxy configured.
DOCKER_URL = (os.environ.get("TOOLBOX_DOCKER_URL") or "").strip()
_supervisors: dict[str, RuntimeSupervisor] = {}
# Replicas (roadmap D3): runtimes whose plugins allow scaling.max > 1 get a health-aware balancer + autoscaler; the
# worker pool is scaled by queue length when TOOLBOX_WORKER_SCALING="min:max" is set.
_balancers: dict[str, Balancer] = {}
_scalers: list[ScaledService] = []
if ROLE == "web" and DOCKER_URL and RUNTIME_URLS:
    for _rt, _idle in on_demand_runtimes(_registry.ordered()).items():
        if _rt in RUNTIME_URLS:
            _supervisors[_rt] = RuntimeSupervisor(_rt, RUNTIME_URLS[_rt], DOCKER_URL, _idle)
    for _rt, (_lo, _hi) in scaled_runtimes(_registry.ordered()).items():
        if _rt in RUNTIME_URLS and _rt not in _supervisors:
            _balancers[_rt] = Balancer(f"rt-{_rt}", RUNTIME_URLS[_rt], DOCKER_URL)
            _scalers.append(ScaledService(f"rt-{_rt}", "cpu", _lo, _hi, DOCKER_URL))
    _ws = (os.environ.get("TOOLBOX_WORKER_SCALING") or "").strip()
    if _ws:
        _lo, _hi = (int(x) for x in _ws.split(":", 1))
        _scalers.append(ScaledService("worker", "queue", _lo, _hi, DOCKER_URL))

_workspace = load_workspace(default_path(_REPO), known=set(_registry.plugins))
for _err in _workspace.errors:
    logger.error("Workspace settings problem: %s", _err)
for _warn in _workspace.warnings:
    logger.warning("Workspace settings warning: %s", _warn)

# Populated by _record_failure() (a LazyApp whose first-request import failed) — name -> error, for any tool whose
# import/mount failed. Read by the home page to show those cards as
# "temporarily unavailable" instead of pretending they don't exist.
_failed_tools: dict[str, str] = {}


def _record_failure(name: str, error: str) -> None:
    """Called by a LazyApp whose import failed, so the home page shows its card as unavailable."""
    _failed_tools[name] = error
    _publish_soon()


# ---------------------------------------------------------------------------
# Load state shared between processes (roadmap B9)
# ---------------------------------------------------------------------------
# With several workers (+ the singletons process) "is this tool loaded?" differs per process. Each process
# publishes its own loaded/failed tools to Redis under toolbox:procs:<host>:<pid> (TTL 60 s, refreshed every 20 s
# and right after each load), and /api/workspace/status combines every live process. Without Redis: this process only.

_PROC_KEY = f"toolbox:procs:{os.uname().nodename}:{os.getpid()}"
_PROC_TTL = 60


def _redis():
    try:
        from core.state import config, sessions
    except ImportError:
        return None
    return sessions.client() if config.load().redis_url else None


def _publish_now() -> None:
    try:
        r = _redis()
        if r is None:
            return
        state = {"role": ROLE, "loaded": {n: round(l.load_seconds or 0, 3) for n, l in _lazy.items() if l.state == "loaded"},
                 "failed": dict(_failed_tools)}
        r.set(_PROC_KEY, json.dumps(state), ex=_PROC_TTL)
    except Exception:  # noqa: BLE001 - status sharing is cosmetic; never break a request over it
        logger.debug("could not publish process state", exc_info=True)


def _publish_soon(*_: Any) -> None:
    """Off the event loop: a slow or missing Redis must never delay the request that loaded a tool."""
    import threading

    threading.Thread(target=_publish_now, daemon=True, name="proc-state").start()


def _heartbeat() -> None:
    import time

    while True:
        _publish_now()
        time.sleep(20)


def _all_processes() -> list[dict[str, Any]]:
    try:
        r = _redis()
        if r is None:
            return []
        keys = list(r.scan_iter("toolbox:procs:*", count=200))
        return [json.loads(v) for v in r.mget(keys) if v] if keys else []
    except Exception:  # noqa: BLE001
        return []


# name -> Slot (holding a LazyApp or DisabledApp), filled by the mount loop at the bottom.
_slots: dict[str, Slot] = {}
# name -> LazyApp, kept even while a tool is off so turning it back on reuses an already-imported module.
_lazy: dict[str, LazyApp] = {}
_proxies: dict[str, ProxyApp] = {}


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict[str, Any]]:
    """Home-page card data for every discovered plugin, in display order."""
    return [
        {"name": m.name, "title": m.title, "description": m.description, "icon": m.icon, "category": m.category}
        for m in _registry.ordered()
        if _workspace.is_enabled(m)
    ]


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_card(tool: dict[str, Any]) -> str:
    icon = tool.get("icon", "🧰")
    title = _esc(tool.get("title", tool.get("name", "")))
    desc = _esc(tool.get("description", ""))
    name = tool.get("name")
    category = tool.get("category", "tool")  # missing category = "tool", the more common case
    search_text = _esc(f"{title} {desc}".lower())

    if name in _failed_tools:
        return f"""
    <div class="card card-unavailable" data-name="{name}" data-category="{category}" data-search="{search_text}">
      <div class="icon">{icon}</div>
      <div class="title">{title}<span class="badge badge-error">Unavailable</span></div>
      <div class="desc">Failed to load — check the container logs (docker-compose logs toolbox).</div>
    </div>"""

    badge = '<span class="badge">Learn</span>' if category == "learn" else ""
    href = f"/tools/{name}/"
    return f"""
    <a class="card" href="{href}" target="_blank" rel="noopener noreferrer" data-name="{name}" data-category="{category}" data-search="{search_text}">
      <div class="icon">{icon}</div>
      <div class="title">{title}{badge}</div>
      <div class="desc">{desc}</div>
    </a>"""


_WORKSPACE_HTML = (_REPO / "core_plugins" / "ui" / "workspace.html").read_text(encoding="utf-8")


def _card_data(m) -> dict[str, Any]:
    return {"name": m.name, "title": m.title, "description": m.description, "icon": m.icon,
            "category": m.category, "order": m.order}


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    tools = _load_registry()
    cards = "".join(_render_card(t) for t in tools) or (
        '<p class="empty">No tools registered yet — add a plugin folder with a manifest.yaml.</p>'
    )
    data = {"plugins": [_card_data(m) for m in _registry.ordered() if _workspace.is_enabled(m)]}
    # "</" must not appear raw inside <script>; JSON stays valid with the escaped slash.
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return HTMLResponse(_WORKSPACE_HTML.replace("{{CARDS}}", cards).replace("{{DATA}}", payload))


@app.get("/api/state/health")
async def state_health() -> dict[str, Any]:
    """Postgres / Redis / object storage / jobs / Vault status (roadmap B1). Imported lazily so idle memory stays low.
    In gateway mode (roadmap C2) the `data` runtime answers it: the probes import psycopg/boto3/rq/cryptography
    (~25 MB per process), which every gateway worker would otherwise keep for good."""
    data_url = RUNTIME_URLS.get("data") if ROLE == "web" else None
    if data_url:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{data_url}/api/state/health")
            return {**r.json(), "answered_by": "rt-data"}
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "error": f"the data runtime did not answer the health check: {exc}"}
    from starlette.concurrency import run_in_threadpool

    from core.state import health

    return await run_in_threadpool(health)


@app.get("/api/state/overview")
async def state_overview() -> dict[str, Any]:
    """Status-page data that needs the state libraries (roadmap E1): state health + job queue + storage use.
    In gateway mode answered by rt-data, like /api/state/health."""
    data_url = RUNTIME_URLS.get("data") if ROLE == "web" else None
    if data_url:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(f"{data_url}/api/state/overview")
            return {**r.json(), "answered_by": "rt-data"}
        except (httpx.HTTPError, ValueError) as exc:
            return {"state": {"ok": False, "error": f"the data runtime did not answer: {exc}"}}
    from starlette.concurrency import run_in_threadpool

    from core.state import health
    from core_plugins import overview

    async def safe(fn):
        try:
            return await run_in_threadpool(fn)
        except Exception as exc:  # noqa: BLE001 - one broken section must not blank the page
            return {"error": f"{type(exc).__name__}: {exc}"[:300]}

    state, jobs, storage = await asyncio.gather(safe(health), safe(overview.jobs_summary), safe(overview.storage_summary))
    return {"state": state, "jobs": jobs, "storage": storage}


@app.get("/api/workspace/metrics")
async def workspace_metrics() -> dict[str, Any]:
    """Per-tool requests / 5xx errors / slow answers: last hour (+ 60-minute series) and last 24 h (roadmap E2)."""
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(metrics.read)


@app.get("/api/workspace/errors")
async def workspace_errors(limit: int = 50) -> dict[str, Any]:
    """The last 5xx answers of any tool, newest first (roadmap E3)."""
    from starlette.concurrency import run_in_threadpool

    return {"errors": await run_in_threadpool(metrics.recent_errors, max(1, min(limit, metrics.MAX_ERRORS)))}


@app.get("/api/workspace/logs/{name}")
async def container_logs(name: str, lines: int = 200):
    """Last log lines of one container of this project, for the Status page's "logs" button (roadmap E3)."""
    from fastapi.responses import PlainTextResponse

    from core_plugins import overview

    if not DOCKER_URL:
        raise HTTPException(404, "No Docker access configured (TOOLBOX_DOCKER_URL).")
    try:
        return PlainTextResponse(await overview.logs(DOCKER_URL, name, lines))
    except KeyError:
        raise HTTPException(404, f"'{name}' is not a container of this Toolbox.") from None


@app.get("/api/workspace/alerts")
async def workspace_alerts() -> dict[str, Any]:
    """Cheap attention list for the sidebar badge (roadmap E3): container states (no stats), tools, state health,
    recent errors. Polled every 60 s by every open workspace."""
    from starlette.concurrency import run_in_threadpool

    from core_plugins import overview

    async def conts():
        try:
            return await overview.container_states(DOCKER_URL) if DOCKER_URL else {}
        except Exception:  # noqa: BLE001
            return {}

    cont, tools, st, errs = await asyncio.gather(conts(), workspace_status(), state_health(),
                                                 run_in_threadpool(metrics.recent_errors, 50))
    items = overview.attention({"containers": cont, "tools": tools, "state": st, "errors": errs,
                                "on_demand_services": [f"rt-{r}" for r in _supervisors],
                                "pool_services": [s.service for s in _scalers]})
    return {"items": items, "errors": sum(1 for i in items if i["level"] == "error"),
            "warnings": sum(1 for i in items if i["level"] == "warn")}


@app.get("/api/workspace/overview")
async def workspace_overview() -> dict[str, Any]:
    """Everything the Status tab shows (roadmap E1): containers (Docker, read-only), tools, scaling, jobs, storage,
    state services, and an 'attention' list. Nothing is stored; sections that fail say so instead."""
    from core_plugins import overview

    async def containers():
        if not DOCKER_URL:
            return {"error": "no Docker access configured (TOOLBOX_DOCKER_URL)"}
        try:
            return await overview.containers(DOCKER_URL)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"[:300]}

    from starlette.concurrency import run_in_threadpool

    cont, tools, rts, st, traffic, errs = await asyncio.gather(
        containers(), workspace_status(), runtimes_status(), state_overview(),
        run_in_threadpool(metrics.read), run_in_threadpool(metrics.recent_errors, 50))
    out = {"generated_at": time.time(), "containers": cont, "tools": tools, "runtimes": rts,
           "state": st.get("state") or {}, "jobs": st.get("jobs") or {}, "storage": st.get("storage") or {},
           "traffic": traffic, "errors": errs,
           "on_demand_services": [f"rt-{r}" for r in _supervisors],
           "pool_services": [s.service for s in _scalers]}
    out["attention"] = overview.attention(out)
    return out


@app.get("/api/workspace/status")
async def workspace_status() -> dict[str, Any]:
    """Per-plugin state for the workspace UI (A4) and status page (E2). Never imports a tool. With several
    processes, a tool counts as loaded/failed if it is in ANY live process (see "Load state shared")."""
    from starlette.concurrency import run_in_threadpool

    procs = await run_in_threadpool(_all_processes)
    rt_state = {rt: await sup.refresh() for rt, sup in _supervisors.items()}  # roadmap C3: asleep | starting | running
    loaded_anywhere = {n: s for p in procs for n, s in p.get("loaded", {}).items()}
    failed_anywhere = {n: e for p in procs for n, e in p.get("failed", {}).items()}
    plugins = []
    for m in _registry.ordered():
        slot = _slots.get(m.name)
        mount = slot.app if slot else None
        lazy = _lazy.get(m.name)
        if isinstance(mount, DisabledApp):
            state = "disabled"
        elif isinstance(mount, LazyApp):
            state = mount.state
            if state == "not_loaded" and m.name in failed_anywhere:
                state = "failed"
            elif state == "not_loaded" and m.name in loaded_anywhere:
                state = "loaded"
        elif isinstance(mount, (StaticApp, ExternalApp)):
            state = "ready"  # no server code to load
        elif isinstance(mount, ProxyApp):  # another container: runtime (C2) or the singletons process (B9)
            state = ("failed" if m.name in failed_anywhere else "loaded" if m.name in loaded_anywhere
                     else "not_loaded" if procs else "remote")
            if rt_state.get(m.runtime or "") in ("asleep", "starting") and not m.singleton:
                state = rt_state[m.runtime]  # its container is stopped (starts on first use) or starting
        else:
            state = "not_mounted"  # kind: service — routed by the gateway from roadmap C2/D1
        plugins.append({
            "name": m.name, "title": m.title, "kind": m.kind, "runtime": m.runtime, "tier": m.tier,
            "enabled": _workspace.is_enabled(m), "state": state,
            "load_seconds": round(lazy.load_seconds, 3) if lazy and lazy.load_seconds else loaded_anywhere.get(m.name),
            # turned off after it was already imported: memory is only freed by a restart
            "restart_to_free_memory": state == "disabled" and bool((lazy and lazy.state == "loaded")
                                                                   or m.name in loaded_anywhere),
            "error": _failed_tools.get(m.name) or failed_anywhere.get(m.name),
            "on_demand": (m.runtime in _supervisors) and not m.singleton,
        })
    counts: dict[str, int] = {}
    for p in plugins:
        counts[p["state"]] = counts.get(p["state"], 0) + 1
    return {"plugins": plugins, "counts": counts, "workspace_file": str(_workspace.path),
            "manifest_errors": _registry.errors, "workspace_errors": _workspace.errors}


class _ToggleBody(BaseModel):
    enabled: bool


def _app_for(m, enabled: bool):
    """The ASGI app to put in a tool's Slot for its kind and on/off state (None = not mountable here)."""
    if m.kind == "service":
        return None  # separately running service: routed by the gateway (roadmap C2/D1)
    # which plugins this process hosts at all — decided before on/off, so it never mounts another role's tools
    if ROLE == "runtime" and (m.kind != "python" or m.runtime != RUNTIME or m.singleton):
        return None  # a runtime image serves only its own python plugins; the rest live elsewhere
    if ROLE == "singletons" and not m.singleton:
        return None  # the singleton process hosts only the singletons
    if not enabled:
        return DisabledApp(m.name, m.title)
    if m.kind == "static":
        return StaticApp(m.name, Path(m.source).parent, m.entry)
    if m.kind == "external":
        return ExternalApp(m.name, m.entry)
    target = (SINGLETON_URL if m.singleton else RUNTIME_URLS.get(m.runtime or "")) if ROLE == "web" else ""
    if target:
        if m.name not in _proxies:
            _proxies[m.name] = ProxyApp(m.name, m.title, target,
                                        supervisor=None if m.singleton else _supervisors.get(m.runtime or ""),
                                        balancer=None if m.singleton else _balancers.get(m.runtime or ""))
        return _proxies[m.name]
    if m.name not in _lazy:
        _lazy[m.name] = LazyApp(m.name, m.module, on_failure=_record_failure, on_loaded=_publish_soon)
    return _lazy[m.name]


@app.post("/api/workspace/plugins/{name}")
async def set_plugin_enabled(name: str, body: _ToggleBody) -> dict[str, Any]:
    """Turn a tool on/off right now (no restart) and save the choice to workspace.yaml."""
    m = _registry.plugins.get(name)
    if m is None:
        raise HTTPException(404, f"unknown tool '{name}'")
    if name not in _slots:
        raise HTTPException(400, f"'{name}' (kind {m.kind}) has no switchable mount yet")
    previous = _workspace.enabled.get(name)
    _workspace.set_enabled(name, body.enabled)
    try:
        _workspace.save()
    except OSError as exc:
        if previous is None:
            _workspace.enabled.pop(name, None)
        else:
            _workspace.enabled[name] = previous
        raise HTTPException(500, f"could not save {_workspace.path}: {exc}") from exc
    _slots[name].app = _app_for(m, body.enabled)
    _remember_mtime()
    lazy = _lazy.get(name)
    if body.enabled:
        message = f"{m.title} is on." + ("" if lazy and lazy.state == "loaded" else " It loads when you first open it.")
    elif lazy and lazy.state == "loaded":
        message = f"{m.title} is off. It was already loaded, so its memory is freed after the next restart."
    else:
        message = f"{m.title} is off and uses no memory."
    logger.info("Workspace: %s turned %s", name, "on" if body.enabled else "off")
    return {"name": name, "enabled": body.enabled, "message": message, "plugin": _card_data(m)}


@app.get("/api/workspace/runtimes")
async def runtimes_status() -> dict[str, Any]:
    """On-demand runtime containers (roadmap C3): state, idle timeout, seconds since the last request."""
    from starlette.concurrency import run_in_threadpool

    out = {}
    for rt, sup in _supervisors.items():
        idle = await run_in_threadpool(sup.idle_for)
        out[rt] = {"state": await sup.refresh(), "idle_timeout_s": sup.idle_s,
                   "idle_s": round(idle, 1) if idle is not None else None}
    scaled = {s.service: {"min": s.min, "max": s.max, "metric": s.kind, **await run_in_threadpool(s.shared_state)}
              for s in _scalers}
    for rt, b in _balancers.items():
        scaled.setdefault(f"rt-{rt}", {})["routing"] = [
            {"replica": t["name"], "healthy": t["healthy"]} for t in b.targets]
    return {"on_demand": out, "always_on": sorted(set(RUNTIME_URLS) - set(_supervisors)), "scaled": scaled}


_sweeper_started = False


def _start_supervisor() -> None:
    """Start this process's background tasks on its event loop (first request — no deprecated startup hook):
    the idle sweep/autoscaler, the replica lists, and the request-counter flusher (roadmap E2)."""
    global _sweeper_started
    if _sweeper_started:
        return
    _sweeper_started = True
    loop = asyncio.get_running_loop()
    if ROLE == "web":
        loop.create_task(metrics.run_flusher())
    if _supervisors or _scalers:
        loop.create_task(Supervisor(_supervisors, _scalers).run())
    for b in _balancers.values():  # every gateway process routes, so every process keeps its replica list
        loop.create_task(b.run())
        logger.info("On-demand runtimes: %s", {rt: s.idle_s for rt, s in _supervisors.items()})


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    """Liveness of THIS process (compose healthchecks). Cheap: touches no state service."""
    return {"ok": True, "role": ROLE, "pid": os.getpid()}


# ---------------------------------------------------------------------------
# Workspace sync between worker processes (roadmap B9)
# ---------------------------------------------------------------------------

_ws_mtime: float | None = None
_ws_checked = 0.0


def _file_mtime() -> float | None:
    try:
        return _workspace.path.stat().st_mtime
    except OSError:
        return None


def _remember_mtime() -> None:
    global _ws_mtime
    _ws_mtime = _file_mtime()


def _sync_workspace() -> None:
    """At most once a second: if workspace.yaml changed (another worker flipped a switch), reload it and re-point
    every tool's Slot. Cheap — one stat() per second per process."""
    global _workspace, _ws_checked
    import time

    now = time.monotonic()
    if now - _ws_checked < 1.0:
        return
    _ws_checked = now
    mtime = _file_mtime()
    if mtime == _ws_mtime:
        return
    fresh = load_workspace(default_path(_REPO), known=set(_registry.plugins))
    if fresh.errors:
        logger.error("Workspace settings changed but could not be read — keeping the current ones: %s", fresh.errors)
        _remember_mtime()
        return
    _workspace = fresh
    _remember_mtime()
    for m in _registry.ordered():
        if m.name in _slots:
            new = _app_for(m, _workspace.is_enabled(m))
            if new is not None:
                _slots[m.name].app = new


class _WorkspaceSync:
    """Pure ASGI (not @app.middleware, which wraps every streaming response): check workspace.yaml, pass through."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            _sync_workspace()
            _start_supervisor()
        await self.app(scope, receive, send)


app.add_middleware(_WorkspaceSync)


for _plugin in _registry.ordered():
    _initial = _app_for(_plugin, _workspace.is_enabled(_plugin))
    if _initial is None:
        continue
    _slots[_plugin.name] = Slot(_initial)
    # roadmap E2: the web role (gateway) counts requests/errors/slow answers per tool; runtimes don't (no double count)
    app.mount(_plugin.mount_path, metrics.Metered(_slots[_plugin.name], _plugin.name) if ROLE == "web"
              else _slots[_plugin.name])
_remember_mtime()
if _redis_configured := bool(os.environ.get("TOOLBOX_REDIS_URL")):
    import threading as _threading

    _threading.Thread(target=_heartbeat, daemon=True, name="proc-heartbeat").start()
logger.info("Toolbox role=%s%s, singletons %s, runtimes %s", ROLE, f" runtime={RUNTIME}" if ROLE == "runtime" else "",
            f"proxied to {SINGLETON_URL}" if (ROLE == "web" and SINGLETON_URL) else "in this process",
            RUNTIME_URLS or "in this process")

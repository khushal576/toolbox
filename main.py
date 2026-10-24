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
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from pydantic import BaseModel

from core_plugins import (DisabledApp, ExternalApp, LazyApp, Slot, StaticApp, default_path, discover,
                          load_workspace)

logger = logging.getLogger("toolbox")

app = FastAPI(title="Toolbox", description="One-stop access to internal tools.")

_REPO = Path(__file__).resolve().parent

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


# name -> Slot (holding a LazyApp or DisabledApp), filled by the mount loop at the bottom.
_slots: dict[str, Slot] = {}
# name -> LazyApp, kept even while a tool is off so turning it back on reuses an already-imported module.
_lazy: dict[str, LazyApp] = {}


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


@app.get("/api/workspace/status")
async def workspace_status() -> dict[str, Any]:
    """Per-plugin state for the workspace UI (A4) and status page (E2). Never imports a tool."""
    plugins = []
    for m in _registry.ordered():
        slot = _slots.get(m.name)
        mount = slot.app if slot else None
        lazy = _lazy.get(m.name)
        if isinstance(mount, DisabledApp):
            state = "disabled"
        elif isinstance(mount, LazyApp):
            state = mount.state
        elif isinstance(mount, (StaticApp, ExternalApp)):
            state = "ready"  # no server code to load
        else:
            state = "not_mounted"  # kind: service — routed by the gateway from roadmap C2/D1
        plugins.append({
            "name": m.name, "title": m.title, "kind": m.kind, "runtime": m.runtime, "tier": m.tier,
            "enabled": _workspace.is_enabled(m), "state": state,
            "load_seconds": round(lazy.load_seconds, 3) if lazy and lazy.load_seconds else None,
            # turned off after it was already imported: memory is only freed by a restart
            "restart_to_free_memory": state == "disabled" and bool(lazy and lazy.state == "loaded"),
            "error": _failed_tools.get(m.name),
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
    if not enabled:
        return DisabledApp(m.name, m.title)
    if m.kind == "static":
        return StaticApp(m.name, Path(m.source).parent, m.entry)
    if m.kind == "external":
        return ExternalApp(m.name, m.entry)
    if m.name not in _lazy:
        _lazy[m.name] = LazyApp(m.name, m.module, on_failure=_record_failure)
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
    lazy = _lazy.get(name)
    if body.enabled:
        message = f"{m.title} is on." + ("" if lazy and lazy.state == "loaded" else " It loads when you first open it.")
    elif lazy and lazy.state == "loaded":
        message = f"{m.title} is off. It was already loaded, so its memory is freed after the next restart."
    else:
        message = f"{m.title} is off and uses no memory."
    logger.info("Workspace: %s turned %s", name, "on" if body.enabled else "off")
    return {"name": name, "enabled": body.enabled, "message": message, "plugin": _card_data(m)}


for _plugin in _registry.ordered():
    _initial = _app_for(_plugin, _workspace.is_enabled(_plugin))
    if _initial is None:
        continue
    _slots[_plugin.name] = Slot(_initial)
    app.mount(_plugin.mount_path, _slots[_plugin.name])

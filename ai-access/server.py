"""
ai-access/server.py — the owner's control panel for AI access (roadmap K4, docs/architecture/ADR-MCP.md D12).

Open to anyone who can open Toolbox (like every route — single-owner tool):  GET status / calls,  POST kill,  POST grants/{id}/revoke.
Needs the owner's PIN:  create a grant, resume after a stop, change the PIN.
The same operations exist as the CLI (`python -m mcp_server …`); the MCP tools the AI can call contain neither — a unit test scans for it.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

try:  # real image: /app/mcp_server, /app/core
    from core import lake as lake_store
    from core import vault as vault_store
    from mcp_server import access, audit, control
    from mcp_server.safety import environment_of
except ImportError:  # standalone dev run from inside this folder
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import lake as lake_store
    from core import vault as vault_store
    from mcp_server import access, audit, control
    from mcp_server.safety import environment_of

PLUGIN = "ai-access"
UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"
app = FastAPI(title="AI Access")


def _err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


async def _run(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


def _targets() -> dict:
    """Names (and environment labels) of what a grant can be for. Nothing else from the Vault leaves this function."""
    v = vault_store.scoped(PLUGIN)
    out = {"connection": [], "ssh_server": [], "workspace": []}
    for kind, secret_kind in (("connection", "postgres_connection"), ("ssh_server", "ssh_server")):
        for item in v.list_secrets(secret_kind):
            try:
                env = environment_of(v.get_secret(item["id"]))
            except Exception:  # noqa: BLE001
                env = "unknown"
            out[kind].append({"name": item["name"], "environment": env})
    try:
        out["workspace"] = [{"name": w["name"], "environment": "non-prod"} for w in lake_store.scoped(PLUGIN).list_workspaces()]
    except Exception:  # noqa: BLE001
        pass
    return out


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))


@app.get("/status")
async def status() -> JSONResponse:
    try:
        st = await _run(control.status)
        targets = await _run(_targets)
    except Exception:  # noqa: BLE001
        return _err("The Toolbox database is not reachable, so AI access is treated as stopped.", 503)
    return JSONResponse({"ok": True, **st, "actions": control.ACTIONS, "max_minutes": control.MAX_MINUTES,
                         "default_minutes": control.DEFAULT_MINUTES, "targets": targets})


@app.get("/calls")
async def calls(limit: int = 100, tool: str = "", outcome: str = "", session: str = "") -> JSONResponse:
    try:
        rows = await _run(audit.recent, limit, tool=tool, outcome=outcome, session=session)
    except Exception:  # noqa: BLE001
        return _err("The audit log is not reachable.", 503)
    return JSONResponse({"ok": True, "calls": rows})


@app.post("/kill")
async def kill() -> JSONResponse:
    """The brake: no PIN, anyone may stop. Revokes every grant and refuses every AI call from now on."""
    try:
        n = await _run(control.kill, "stopped from the AI Access page")
    except Exception:  # noqa: BLE001
        return _err("Could not reach the database to stop AI access — stop the worker containers or Claude's connection instead.", 503)
    return JSONResponse({"ok": True, "revoked": n})


class PinBody(BaseModel):
    pin: str = ""


@app.post("/resume")
async def resume(body: PinBody) -> JSONResponse:
    try:
        await _run(control.resume, body.pin)
    except control.ControlError as exc:
        return _err(str(exc))
    return JSONResponse({"ok": True})


class SetPinBody(BaseModel):
    new: str
    old: str = ""


@app.post("/pin")
async def set_pin(body: SetPinBody) -> JSONResponse:
    try:
        await _run(control.set_pin, body.new, body.old or None)
    except control.ControlError as exc:
        return _err(str(exc))
    return JSONResponse({"ok": True})


class GrantBody(BaseModel):
    target_kind: str
    target: str
    actions: list[str]
    minutes: int = control.DEFAULT_MINUTES
    row_limit: int | None = None
    note: str = ""
    pin: str = ""
    confirm_prod: bool = False


@app.post("/grants")
async def create_grant(body: GrantBody) -> JSONResponse:
    def make():
        known = _targets()
        if body.target_kind in ("connection", "ssh_server"):
            names = {t["name"]: t["environment"] for t in known.get(body.target_kind, [])}
            if body.target not in names:
                raise control.ControlError(f"There is no saved {body.target_kind.replace('_', ' ')} named '{body.target}'.")
            env = names[body.target]            # the REAL label from the Vault, never trusted from the browser
        elif body.target_kind == "workspace":
            try:
                lake_store.check_name(body.target, "workspace name")
            except lake_store.LakeError as exc:
                raise control.ControlError(str(exc)) from None
            env = "non-prod"
        else:
            raise control.ControlError("Unknown target kind.")
        return control.create_grant(body.target_kind, body.target, body.actions, minutes=body.minutes, pin=body.pin,
                                    row_limit=body.row_limit, note=body.note, via="ui", environment=env, confirm_prod=body.confirm_prod)

    try:
        g = await _run(make)
    except control.ControlError as exc:
        return _err(str(exc))
    except Exception:  # noqa: BLE001
        return _err("The Toolbox database is not reachable.", 503)
    return JSONResponse({"ok": True, "grant": g})


@app.post("/grants/{grant_id}/revoke")
async def revoke(grant_id: str) -> JSONResponse:
    if not re.fullmatch(r"[0-9a-f]{12}", grant_id):
        return _err("No such grant.", 404)
    done = await _run(control.revoke, grant_id)
    return JSONResponse({"ok": True, "revoked": done})

"""
ssh-sftp/server.py

Serves the SSH & SFTP page and API: browse a server's files, upload/download, make folders, rename, delete
(files and empty folders only), and run commands — over servers saved in the Vault (kind "ssh_server").
Nothing here ever accepts or returns a credential: a server is chosen by its Vault id, and the API only
shows the non-secret fields.

Endpoints
---------
GET  /                          — the single-page UI
GET  /servers                   — saved servers (name, host, user, auth type, read-only, pinned?) — no secrets
POST /servers/{id}/check        — log in; answers ok | needs_trust {fingerprint} | host-key mismatch | error
POST /servers/{id}/trust        — pin the server's host key (only if it is STILL the fingerprint the user confirmed)
GET  /servers/{id}/ls?path=     — list a folder
POST /servers/{id}/mkdir        — {path}
POST /servers/{id}/rename       — {src, dst}   (never overwrites)
POST /servers/{id}/delete       — {path}       (a file or an EMPTY folder)
GET  /servers/{id}/download?path= — stream a file
POST /servers/{id}/upload?dir=&overwrite= — multipart file -> staged -> sent (resumable); returns {transfer_id}
GET  /transfers                 — recent transfers
GET  /transfers/{id}            — one transfer + live progress/log
POST /transfers/{id}/retry|stop — resume a failed/stopped transfer / stop a running one
DELETE /transfers/{id}          — discard (removes the staged copy)
POST /servers/{id}/exec         — {command, timeout, confirm_danger} -> {command_id}
GET  /commands, GET /commands/{id}, POST /commands/{id}/stop
"""

from __future__ import annotations

import asyncio
import errno
import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

try:  # package import when mounted inside the toolbox (ssh_sftp.*)
    from ssh_sftp import engine, runner, sessions, state_store as store
except ImportError:  # flat import when run standalone from within this folder
    import engine
    import runner
    import sessions
    import state_store as store

try:
    from core import ssh_client, vault as vault_store
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import ssh_client, vault as vault_store

vault = vault_store.scoped("ssh-sftp")  # Vault scope from manifest.yaml `vault:` (roadmap B7)

store.init_db()
runner.recover_orphans()
try:
    store.sweep_stage()
except Exception:  # noqa: BLE001 - cleanup must never stop the tool from loading
    pass

app = FastAPI(title="SSH & SFTP", description="Browse, upload and run commands on servers saved in the Vault.")
_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"
STAGE_MARGIN = 500 * 1024 * 1024  # always leave this much disk free when staging an upload


class PathBody(BaseModel):
    path: str = Field(max_length=4096)


class RenameBody(BaseModel):
    src: str = Field(max_length=4096)
    dst: str = Field(max_length=4096)


class TrustBody(BaseModel):
    fingerprint: str


class ExecBody(BaseModel):
    command: str = Field(min_length=1, max_length=8000)
    timeout: int = 60
    confirm_danger: bool = False


def _server(server_id: str) -> dict[str, Any]:
    try:
        return sessions.resolve(server_id)
    except sessions.UnknownServer:
        raise HTTPException(404, "Unknown server — pick one saved in the Vault.") from None


def _fail(exc: BaseException) -> HTTPException:
    """Map an engine/SSH exception to an HTTP answer with a plain message and no secrets."""
    if isinstance(exc, ssh_client.HostKeyUnverified):
        return HTTPException(412, {"code": "host_key_unverified", "message": str(exc), "fingerprint": exc.fingerprint, "key_type": exc.key_type})
    if isinstance(exc, ssh_client.HostKeyMismatch):
        return HTTPException(409, {"code": "host_key_changed", "message": str(exc)})
    if isinstance(exc, engine.ReadOnlyServer):
        return HTTPException(403, str(exc))
    if isinstance(exc, ssh_client.SSHError):
        return HTTPException(502, str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(404, "Not found on the server.")
    if isinstance(exc, FileExistsError):
        return HTTPException(409, str(exc))
    if isinstance(exc, (ValueError, IsADirectoryError, NotADirectoryError)):
        return HTTPException(400, str(exc))
    if isinstance(exc, PermissionError) or (isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM)):
        return HTTPException(403, "Permission denied on the server.")
    if isinstance(exc, OSError) and exc.errno == errno.ENOTEMPTY:
        return HTTPException(409, "The folder is not empty. Only empty folders can be deleted here.")
    return HTTPException(502, engine._plain(exc))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse("<h1>SSH &amp; SFTP UI not built yet</h1>", status_code=503)
    return HTMLResponse(_UI_PATH.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/servers")
def servers() -> dict[str, Any]:
    return {"servers": sessions.list_servers()}


@app.post("/servers/{server_id}/check")
def check(server_id: str) -> dict[str, Any]:
    data = _server(server_id)
    client = None
    try:
        client = ssh_client.open_client(data)
        banner = client.get_transport().remote_version
        return {"ok": True, "banner": banner, "target": ssh_client.describe(data), "read_only": bool(data.get("read_only"))}
    except ssh_client.HostKeyUnverified as exc:
        return {"ok": False, "needs_trust": {"fingerprint": exc.fingerprint, "key_type": exc.key_type}, "target": ssh_client.describe(data)}
    except ssh_client.HostKeyMismatch as exc:
        return {"ok": False, "mismatch": True, "error": str(exc)}
    except ssh_client.SSHError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if client is not None:
            client.close()


@app.post("/servers/{server_id}/trust")
def trust(server_id: str, body: TrustBody) -> dict[str, Any]:
    """Pin the host key the user just confirmed. Re-fetches the key NOW and pins it only if it is still exactly
    the fingerprint that was shown — so a key swapped between "show" and "confirm" is refused. An already
    pinned server can never be re-pinned here: a changed key must be resolved in the Vault, deliberately."""
    _server(server_id)
    raw = vault.get_secret(server_id)
    if (raw.get("host_key") or {}).get("fingerprint"):
        raise HTTPException(409, "This server already has a trusted key. If it changed, delete the server in the Vault and add it again after verifying it.")
    try:
        pin = ssh_client.probe_host_key(raw["host"], int(raw.get("port") or 22))
    except ssh_client.SSHError as exc:
        raise HTTPException(502, str(exc)) from exc
    if pin["fingerprint"] != body.fingerprint:
        raise HTTPException(409, f"The server now presents {pin['fingerprint']}, not the {body.fingerprint} you confirmed. Nothing was trusted — check again.")
    raw["host_key"] = pin
    vault.update_secret(server_id, raw)
    sessions.drop(server_id)
    return {"ok": True, "fingerprint": pin["fingerprint"]}


@app.get("/servers/{server_id}/ls")
def ls(server_id: str, path: Optional[str] = None) -> dict[str, Any]:
    _server(server_id)
    try:
        return engine.list_dir(server_id, path)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@app.post("/servers/{server_id}/mkdir")
def mkdir(server_id: str, body: PathBody) -> dict[str, Any]:
    _server(server_id)
    try:
        engine.make_dir(server_id, body.path)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return {"ok": True}


@app.post("/servers/{server_id}/rename")
def rename(server_id: str, body: RenameBody) -> dict[str, Any]:
    _server(server_id)
    try:
        engine.rename(server_id, body.src, body.dst)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc
    return {"ok": True}


@app.post("/servers/{server_id}/delete")
def delete(server_id: str, body: PathBody) -> dict[str, Any]:
    _server(server_id)
    try:
        return {"ok": True, "deleted": engine.delete(server_id, body.path)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc


@app.get("/servers/{server_id}/download")
def download(server_id: str, path: str):
    _server(server_id)
    try:
        info = engine.file_info(server_id, path)
        # open the connection BEFORE sending headers, so a login/host-key problem is a clean error, not a broken download
        gen = engine.stream_download(server_id, path)
        first = next(gen, b"")
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from exc

    def body():
        try:
            if first:
                yield first
            yield from gen
        finally:
            gen.close()
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in info["name"]) or "download"
    return StreamingResponse(body(), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{safe}"', "Content-Length": str(info["size"])})


def _stage(file: UploadFile, dest: Path) -> tuple[int, str]:
    h, n = hashlib.sha256(), 0
    with dest.open("wb") as out:
        while True:
            chunk = file.file.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


@app.post("/servers/{server_id}/upload")
async def upload(server_id: str, request: Request, file: UploadFile, dir: str, overwrite: bool = False) -> dict[str, Any]:
    """Receive the file into the stage directory (streamed — never held in memory), then send it from there."""
    data = _server(server_id)
    if data.get("read_only"):
        raise HTTPException(403, "This server is saved as READ-ONLY in the Vault.")
    try:
        engine.check_path(dir)
        name = engine.check_name(Path(file.filename or "").name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    declared = int(request.headers.get("content-length") or 0)
    if declared and declared + STAGE_MARGIN > shutil.disk_usage(store.STAGE_DIR).free:
        raise HTTPException(413, "Not enough free disk space on the toolbox to stage this upload.")
    tid = store.new_id()
    tmp = store.stage_path(tid).with_suffix(".stage.part")
    try:
        size, sha = await asyncio.to_thread(_stage, file, tmp)
        tmp.replace(store.stage_path(tid))
        await asyncio.to_thread(store.publish_stage, tid)  # into S3 storage: the worker may run on another disk
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        store.delete_stage(tid)
        raise HTTPException(400, f"Could not receive the file: {exc}") from exc
    store.create_transfer(tid=tid, server_id=server_id, server_name=data["_name"], remote_dir=dir, name=name, size=size, sha256=sha, overwrite=overwrite)
    runner.start_upload(tid)
    return {"transfer_id": tid, "size": size}


def _transfer_view(t: dict[str, Any], v: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    v = v if v is not None else runner.view(t["id"])
    live = v["progress"] if v["running"] else {}
    done = live.get("done", t["bytes_done"]) if t["status"] == "running" else t["bytes_done"]
    return {**t, "bytes_done": done, "running": v["running"]}


@app.get("/transfers")
def transfers() -> dict[str, Any]:
    runner.recover_orphans()  # a job whose worker died → 'failed' (Retry resumes), not 'running' forever
    return {"transfers": [_transfer_view(t) for t in store.list_transfers()]}


@app.get("/transfers/{tid}")
def transfer(tid: str, since: int = 0) -> dict[str, Any]:
    runner.recover_orphans()
    t = store.get_transfer(tid)
    if t is None:
        raise HTTPException(404, "Unknown transfer.")
    v = runner.view(tid, since)
    return {"transfer": _transfer_view(t, v), "logs": v["logs"]}


@app.post("/transfers/{tid}/retry")
def retry(tid: str, overwrite: bool = False) -> dict[str, Any]:
    """Resume a failed/stopped transfer. overwrite=true additionally allows replacing an existing remote file
    (the "already exists" refusal's way out) — an explicit, per-retry decision."""
    t = store.get_transfer(tid)
    if t is None:
        raise HTTPException(404, "Unknown transfer.")
    if t["status"] not in ("failed", "cancelled", "staged"):
        raise HTTPException(409, "Only a failed, stopped or waiting transfer can be retried.")
    if not store.has_stage(tid):
        raise HTTPException(410, "The staged copy is gone — upload the file again.")
    if overwrite:
        store.update_transfer(tid, overwrite=1)
    try:
        runner.start_upload(tid)
    except runner.AlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@app.post("/transfers/{tid}/stop")
def stop_transfer(tid: str) -> dict[str, Any]:
    return {"stopping": runner.stop(tid)}


@app.delete("/transfers/{tid}")
def discard(tid: str) -> dict[str, Any]:
    if runner.is_running(tid):
        raise HTTPException(409, "Stop it first.")
    store.delete_transfer(tid)
    return {"ok": True}


@app.post("/servers/{server_id}/exec")
def exec_command(server_id: str, body: ExecBody) -> dict[str, Any]:
    data = _server(server_id)
    if data.get("read_only"):
        raise HTTPException(403, "This server is saved as READ-ONLY in the Vault — commands are disabled.")
    why = engine.danger_reason(body.command)
    if why and not body.confirm_danger:
        raise HTTPException(428, {"code": "confirm_danger", "message": f"This command looks dangerous: it {why}. Run it only if you are sure.", "reason": why})
    cid = store.add_command(server_id, data["_name"], body.command)
    runner.start_command(cid, server_id, body.command, body.timeout)
    return {"command_id": cid}


@app.get("/commands")
def commands() -> dict[str, Any]:
    runner.recover_orphans()
    return {"commands": [{**c, "running": runner.is_running(c["id"])} for c in store.list_commands()]}


@app.get("/commands/{cid}")
def command(cid: str, since: int = 0) -> dict[str, Any]:
    v = runner.view(cid, since)
    row = next((c for c in store.list_commands(200) if c["id"] == cid), None)
    if row is None:
        raise HTTPException(404, "Unknown command.")
    return {"command": {**row, "running": v["running"]}, "logs": v["logs"], "progress": v["progress"]}


@app.post("/commands/{cid}/stop")
def stop_command(cid: str) -> dict[str, Any]:
    return {"stopping": runner.stop(cid)}

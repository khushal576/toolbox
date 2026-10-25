"""
data-dumper/server.py

Serves Data Dumper's page and API: take a Postgres dump (downloadable), and restore a dump
into any database — whole, or selectively (structure/data/phases/schemas/tables/objects).
Connections are Vault entries, never typed here.

Endpoints
---------
GET    /                          — the single-page UI
GET    /connections               — Vault connections to pick from (id/name only)
GET    /tools                     — are the bundled pg_dump/pg_restore/psql present? (versions)
GET    /dumps                     — the catalogue + disk usage
POST   /dumps                     — take a new dump ({source_conn_id, label?, fmt, scope, keep_owner})
POST   /dumps/upload              — upload a dump file (.dump / .sql / .sql.gz) as a new catalogue entry
POST   /dumps/{id}/again          — take a new dump with this dump's settings (what a scheduler will do)
GET    /dumps/{id}                — one dump + its run history
GET    /dumps/{id}/status         — poll: live job state, log tail, progress
POST   /dumps/{id}/stop           — stop the active dump/restore (a stopped restore is rolled back)
DELETE /dumps/{id}                — delete the dump file and record (409 while running)
GET    /dumps/{id}/file           — DOWNLOAD the dump file
GET    /dumps/{id}/contents       — schemas / tables / every object of a custom-format dump (for selective restore)
POST   /dumps/{id}/restore/preflight — read-only checks + what would be restored
POST   /dumps/{id}/restore        — start the restore
"""

from __future__ import annotations

import asyncio
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

try:  # package import when mounted inside the toolbox (data_dumper.*)
    from data_dumper import engine, runner, state_store as store
except ImportError:  # flat import when run standalone from within this folder
    import engine
    import runner
    import state_store as store

try:
    from core import db_endpoint as connections, pgclient
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import db_endpoint as connections, pgclient
from core.postgres_conn import scrub_password

store.init_db()
runner.recover_orphans()

app = FastAPI(title="Data Dumper", description="Take, download and restore Postgres dumps.")
_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


class DumpBody(BaseModel):
    source_conn_id: str
    label: Optional[str] = Field(None, max_length=160)
    fmt: str = "custom"
    scope: str = "all"
    keep_owner: bool = False


class Selection(BaseModel):
    mode: str = "all"
    schemas: list[str] = []
    tables: list[str] = []
    object_ids: list[int] = []
    structure: bool = True
    data: bool = True
    shared: bool = True
    foreign_keys: bool = True


class RestoreBody(BaseModel):
    target_conn_id: str
    selection: Selection = Selection()
    single_transaction: bool = True
    replace_existing: bool = False
    keep_owner: bool = False


def _conn_name(conn_id: str) -> str:
    for c in connections.list_vault_connections():
        if c["id"] == conn_id:
            return c["name"]
    raise HTTPException(400, f"Vault connection '{conn_id}' not found — pick one from the list.")


def _require(dump_id: str) -> dict[str, Any]:
    d = store.get_dump(dump_id)
    if d is None:
        raise HTTPException(404, "Dump not found.")
    return d


def _job_state(dump_id: str) -> dict[str, Any]:
    v = runner.view(dump_id)
    return {k: v[k] for k in ("running", "queued", "kind", "logs", "progress", "started_at", "finished_at", "stopping")}


def _default_label(db: str) -> str:
    from datetime import datetime
    return f"{db} · {datetime.now().strftime('%Y-%m-%d %H:%M')}"


def _view(d: dict[str, Any]) -> dict[str, Any]:
    return {**d, "running": runner.is_running(d["id"])}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse("<h1>Data Dumper UI not built yet</h1>", status_code=503)
    return HTMLResponse(_UI_PATH.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/connections")
def list_connections() -> dict[str, Any]:
    return {"connections": [{"id": c["id"], "name": c["name"]} for c in connections.list_vault_connections()]}


@app.get("/tools")
def tools() -> dict[str, Any]:
    try:
        return {"ok": True, **{n: pgclient.client_major(n) for n in ("pg_dump", "pg_restore", "psql")}}
    except pgclient.PgToolError as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/dumps")
def list_dumps() -> dict[str, Any]:
    return {"dumps": [_view(d) for d in store.list_dumps()], "disk": store.disk_usage()}


@app.post("/dumps")
def create_dump(body: DumpBody) -> dict[str, Any]:
    if body.fmt not in ("custom", "plain") or body.scope not in ("all", "schema", "data"):
        raise HTTPException(400, "fmt must be custom|plain and scope all|schema|data.")
    name = _conn_name(body.source_conn_id)
    did = store.create_dump(
        label=body.label or _default_label(name), fmt=body.fmt, scope=body.scope, keep_owner=body.keep_owner,
        source_conn_id=body.source_conn_id, source_conn_name=name,
    )
    runner.start_dump(did)
    return {"id": did}


@app.post("/dumps/{dump_id}/again")
def dump_again(dump_id: str) -> dict[str, Any]:
    d = _require(dump_id)
    if d["origin"] != "dump" or not d["source_conn_id"]:
        raise HTTPException(400, "Only dumps taken here can be repeated (uploads have no source connection).")
    return create_dump(DumpBody(source_conn_id=d["source_conn_id"], fmt=d["fmt"], scope=d["scope"], keep_owner=d["keep_owner"]))


@app.post("/dumps/upload")
async def upload_dump(file: UploadFile, label: Optional[str] = None) -> dict[str, Any]:
    """Stream the upload straight to disk (a dump can be many GB — never held in memory)."""
    name = (file.filename or "uploaded dump")
    did = store.create_dump(label=label or name, origin="upload", status="running", fmt="custom", source_desc=f"uploaded: {name}")
    tmp = store.FILES_DIR / f"{did}.upload.part"
    try:
        with tmp.open("wb") as out:
            await asyncio.to_thread(shutil.copyfileobj, file.file, out, 1 << 20)
        await asyncio.to_thread(engine.finalize_upload, did, tmp)
    except pgclient.PgToolError as exc:
        tmp.unlink(missing_ok=True)
        store.delete_dump(did)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        store.delete_dump(did)
        raise HTTPException(400, scrub_password(str(exc))) from exc
    return {"id": did}


@app.get("/dumps/{dump_id}")
def get_dump(dump_id: str) -> dict[str, Any]:
    runner.heal(dump_id)
    d = _require(dump_id)
    return {"dump": _view(d), "runs": store.list_runs(dump_id), "run": _job_state(dump_id)}


@app.get("/dumps/{dump_id}/status")
def status(dump_id: str) -> dict[str, Any]:
    runner.heal(dump_id)  # a job whose worker died → the dump shows failed, not "running" forever
    d = _require(dump_id)
    return {"dump": _view(d), "run": _job_state(dump_id), "runs": store.list_runs(dump_id, 5)}


@app.post("/dumps/{dump_id}/stop")
def stop(dump_id: str) -> dict[str, Any]:
    _require(dump_id)
    return {"stopping": runner.stop(dump_id)}


@app.delete("/dumps/{dump_id}")
def delete_dump(dump_id: str) -> dict[str, Any]:
    _require(dump_id)
    if runner.is_running(dump_id):
        raise HTTPException(409, "A run is active — stop it first.")
    store.delete_dump(dump_id)
    return {"ok": True}


@app.get("/dumps/{dump_id}/file")
def download(dump_id: str):
    d = _require(dump_id)
    path = store.fetch_file(d) if d["status"] == "ready" else None
    if path is None:
        raise HTTPException(404, "This dump has no file to download.")
    ext = "".join(path.suffixes[-2:]) if path.name.endswith(".sql.gz") else path.suffix
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{d.get('source_db') or 'dump'}-{(d['created_at'] or '')[:19].replace(':', '').replace('T', '-')}")
    return FileResponse(path, media_type="application/octet-stream", filename=f"{base}{ext}")


@app.get("/dumps/{dump_id}/contents")
def contents(dump_id: str) -> dict[str, Any]:
    d = _require(dump_id)
    if d["status"] != "ready":
        raise HTTPException(409, "This dump is not ready.")
    try:
        return engine.contents(dump_id)
    except pgclient.PgToolError as exc:
        raise HTTPException(400, str(exc)) from exc


def _opts(dump_id: str, body: RestoreBody) -> dict[str, Any]:
    d = _require(dump_id)
    return {
        "target_conn_id": body.target_conn_id, "target_conn_name": _conn_name(body.target_conn_id),
        "selection": body.selection.model_dump(), "single_transaction": body.single_transaction,
        "replace_existing": body.replace_existing, "keep_owner": body.keep_owner,
    }


@app.post("/dumps/{dump_id}/restore/preflight")
def preflight(dump_id: str, body: RestoreBody) -> dict[str, Any]:
    opts = _opts(dump_id, body)
    return engine.preflight_restore(dump_id, opts)


@app.post("/dumps/{dump_id}/restore")
def restore(dump_id: str, body: RestoreBody) -> dict[str, Any]:
    opts = _opts(dump_id, body)
    if runner.is_running(dump_id):
        raise HTTPException(409, "This dump already has a run in progress.")
    try:
        runner.start_restore(dump_id, opts)
    except runner.AlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}

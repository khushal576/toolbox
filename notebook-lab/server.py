"""
notebook-lab/server.py

The Notebook tool: Colab/Jupyter-style workspaces with files, .ipynb notebooks, Python kernels and per-workspace
pip installs. Runs ONLY in the `notebook` runtime (rt-notebook): that container executes user code, so it holds no
Postgres/S3/Vault credentials (see docker-compose.yml).

Endpoints (all under /workspaces/{ws} unless noted)
---------------------------------------------------
GET  /                                  — the single-page UI
GET  /workspaces                        — [{name, kernel, files, files_bytes, env_bytes}]
POST /workspaces                        — {name}              DELETE /workspaces/{ws}
POST /workspaces/{ws}/reset-env         — forget pip-installed packages (stops the kernel first)
Files
GET  /files?path=                       — folder listing         GET /files/content?path=   PUT /files/content
POST /files/mkdir | /files/rename | /files/delete
POST /files/upload?path=&extract=0|1   — RAW request body = the file (streamed to disk); extract=1 unpacks a .zip
GET  /files/download?path=              — one file               GET /files/download-zip?path=  — a folder as .zip
Notebooks (.ipynb, nbformat 4)
GET  /notebook?path=    PUT /notebook?path=    POST /notebook/new {path}
Kernel
GET  /kernel            — state + the latest execution of every cell (so a reloaded page re-attaches)
POST /kernel/start | /kernel/restart | /kernel/interrupt | /kernel/shutdown
POST /kernel/execute    — {code, cell_id, batch?} -> {id}   (queued; cells run one at a time)
GET  /executions/{id}?v=  — status + outputs (body omitted when `v` is still current)
Packages
GET  /packages          — what this workspace installed (+ the running/last install)
POST /packages/install  — {spec: "tensorflow scikit-learn==1.5.2"}      POST /packages/cancel
GET  /installs/{id}?v=  — pip output
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

try:  # package import when mounted inside the toolbox (notebook_lab.*)
    from notebook_lab import kernels, workspaces
    from notebook_lab.workspaces import WorkspaceError
except ImportError:  # flat import when run standalone from within this folder
    import kernels
    import workspaces
    from workspaces import WorkspaceError

app = FastAPI(title="Notebook")
UI = Path(__file__).parent / "ui" / "index.html"


@app.exception_handler(WorkspaceError)
async def _workspace_error(_: Request, e: WorkspaceError) -> JSONResponse:
    return JSONResponse({"detail": str(e)}, status_code=e.status)


@app.get("/", response_class=HTMLResponse)
async def page() -> HTMLResponse:
    return HTMLResponse(UI.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


# ---- workspaces ---------------------------------------------------------------------------------------------------

class NameBody(BaseModel):
    name: str


def _ws_view(name: str) -> dict:
    s = kernels.peek(name)
    return {"name": name, "kernel": s.state if s else "stopped", "env_ready": workspaces.env_ready(name),
            **workspaces.usage(name)}


@app.get("/workspaces")
async def list_workspaces() -> list[dict]:
    return [await asyncio.to_thread(_ws_view, n) for n in workspaces.list_workspaces()]


@app.post("/workspaces")
async def create_workspace(b: NameBody) -> dict:
    workspaces.create(b.name.strip())
    return _ws_view(b.name.strip())


@app.delete("/workspaces/{ws}")
async def delete_workspace(ws: str) -> dict:
    s = kernels.peek(ws)
    if s:
        await s.stop()
        kernels.forget(ws)
    await kernels.cancel_install(ws)
    await asyncio.to_thread(workspaces.delete, ws)
    return {"ok": True}


@app.post("/workspaces/{ws}/reset-env")
async def reset_env(ws: str) -> dict:
    workspaces.existing(ws)
    cur = kernels.last_install(ws)
    if cur and cur.status == "running":
        raise WorkspaceError("Wait for (or cancel) the running install first.", 409)
    s = kernels.peek(ws)
    if s:
        await s.stop("Packages were reset — start the kernel again.")
    await asyncio.to_thread(workspaces.reset_env, ws)
    return {"ok": True}


# ---- files --------------------------------------------------------------------------------------------------------

class PathBody(BaseModel):
    path: str


class RenameBody(BaseModel):
    src: str
    dst: str


class ContentBody(BaseModel):
    content: str


@app.get("/workspaces/{ws}/files")
async def files(ws: str, path: str = "") -> dict:
    return await asyncio.to_thread(workspaces.listing, ws, path)


@app.post("/workspaces/{ws}/files/mkdir")
async def mkdir(ws: str, b: PathBody) -> dict:
    await asyncio.to_thread(workspaces.mkdir, ws, b.path)
    return {"ok": True}


@app.post("/workspaces/{ws}/files/rename")
async def rename(ws: str, b: RenameBody) -> dict:
    await asyncio.to_thread(workspaces.rename, ws, b.src, b.dst)
    return {"ok": True}


@app.post("/workspaces/{ws}/files/delete")
async def delete_file(ws: str, b: PathBody) -> dict:
    await asyncio.to_thread(workspaces.remove, ws, b.path)
    return {"ok": True}


@app.get("/workspaces/{ws}/files/content")
async def file_content(ws: str, path: str) -> dict:
    return await asyncio.to_thread(workspaces.read_text, ws, path)


@app.put("/workspaces/{ws}/files/content")
async def put_file_content(ws: str, path: str, b: ContentBody) -> dict:
    return {"size": await asyncio.to_thread(workspaces.write_text, ws, path, b.content)}


async def _body(request: Request):
    async for chunk in request.stream():
        yield chunk


@app.post("/workspaces/{ws}/files/upload")
async def upload(ws: str, request: Request, path: str, extract: int = 0) -> dict:
    """The request BODY is the file (no multipart): it streams to disk in chunks, so a multi-GB archive never sits in
    memory. `path` is the target file path inside the workspace (folders are created). extract=1: `path` must be a
    .zip — it is unpacked next to itself and then removed."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > workspaces.MAX_UPLOAD_BYTES:
        raise WorkspaceError(f"Over the {workspaces.MAX_UPLOAD_BYTES // 1024 // 1024} MB upload limit.", 413)
    size = await workspaces.save_upload(ws, path, _body(request))
    out: dict[str, Any] = {"path": path, "size": size}
    if extract:
        dest = str(Path(path).parent) if str(Path(path).parent) != "." else ""
        out["extracted"] = await asyncio.to_thread(workspaces.extract_zip, ws, path, dest, delete_zip=True)
    return out


@app.get("/workspaces/{ws}/files/download")
async def download(ws: str, path: str) -> FileResponse:
    p = workspaces.safe(ws, path, allow_root=False)
    if not p.is_file():
        raise WorkspaceError("Not a file.", 404)
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@app.get("/workspaces/{ws}/files/download-zip")
async def download_zip(ws: str, path: str = "") -> FileResponse:
    z, name = await asyncio.to_thread(workspaces.make_zip, ws, path)
    return FileResponse(z, filename=name, media_type="application/zip",
                        background=BackgroundTask(lambda: z.unlink(missing_ok=True)))


# ---- notebooks ----------------------------------------------------------------------------------------------------

class Cell(BaseModel):
    id: str = ""
    cell_type: str = "code"
    source: str = ""
    outputs: list[dict] = Field(default_factory=list)
    execution_count: Optional[int] = None


class NotebookBody(BaseModel):
    cells: list[Cell]
    metadata: dict = Field(default_factory=dict)


def _text(v: Any) -> str:
    return "".join(v) if isinstance(v, list) else (v or "")


def _from_ipynb(raw: dict) -> dict:
    cells = []
    for c in raw.get("cells", []):
        t = c.get("cell_type", "code")
        if t not in ("code", "markdown", "raw"):
            continue
        outs = []
        for o in c.get("outputs", []) if t == "code" else []:
            if o.get("output_type") == "stream":
                o = {**o, "text": _text(o.get("text"))}
            elif "data" in o:
                o = {**o, "data": {k: (_text(v) if k.startswith(("text/", "application/json")) and isinstance(v, list)
                                       else v) for k, v in o["data"].items()}}
            outs.append(o)
        cells.append({"id": c.get("id") or uuid.uuid4().hex[:8], "cell_type": t, "source": _text(c.get("source")),
                      "outputs": outs, "execution_count": c.get("execution_count")})
    return {"cells": cells, "metadata": raw.get("metadata", {})}


def _to_ipynb(b: NotebookBody) -> dict:
    cells = []
    for c in b.cells:
        lines = c.source.splitlines(keepends=True)
        cell: dict[str, Any] = {"id": c.id or uuid.uuid4().hex[:8], "cell_type": c.cell_type, "metadata": {},
                                "source": lines}
        if c.cell_type == "code":
            cell["execution_count"] = c.execution_count
            cell["outputs"] = c.outputs
        cells.append(cell)
    meta = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"}, **b.metadata}
    return {"cells": cells, "metadata": meta, "nbformat": 4, "nbformat_minor": 5}


def _nb_path(ws: str, path: str) -> Path:
    if not path.endswith(".ipynb"):
        raise WorkspaceError("Notebook files end in .ipynb.")
    return workspaces.safe(ws, path, allow_root=False)


@app.get("/workspaces/{ws}/notebook")
async def get_notebook(ws: str, path: str) -> dict:
    p = _nb_path(ws, path)
    if not p.is_file():
        raise WorkspaceError("No such notebook.", 404)
    if p.stat().st_size > 64 * 1024 * 1024:
        raise WorkspaceError("This notebook is over 64 MB (huge saved outputs) — clear its outputs elsewhere first.", 413)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        raise WorkspaceError("That file is not valid notebook JSON.", 415)
    return {"path": path, "mtime": p.stat().st_mtime, **_from_ipynb(raw)}


@app.put("/workspaces/{ws}/notebook")
async def put_notebook(ws: str, path: str, b: NotebookBody) -> dict:
    p = _nb_path(ws, path)
    data = json.dumps(_to_ipynb(b), indent=1, ensure_ascii=False).encode("utf-8")
    await asyncio.to_thread(workspaces.write_bytes_atomic, p, data)
    return {"mtime": p.stat().st_mtime}


@app.post("/workspaces/{ws}/notebook/new")
async def new_notebook(ws: str, b: PathBody) -> dict:
    p = _nb_path(ws, b.path)
    if p.exists():
        raise WorkspaceError("That name is already taken.", 409)
    nb = NotebookBody(cells=[
        Cell(id=uuid.uuid4().hex[:8], cell_type="markdown", source="# New notebook\nShift+Enter runs a cell."),
        Cell(id=uuid.uuid4().hex[:8], cell_type="code", source="import pandas as pd\nprint('hello from', pd.__name__)")])
    await asyncio.to_thread(workspaces.write_bytes_atomic, p, json.dumps(_to_ipynb(nb), indent=1).encode())
    return {"path": b.path}


# ---- kernel -------------------------------------------------------------------------------------------------------

class ExecuteBody(BaseModel):
    code: str = Field(max_length=2_000_000)
    cell_id: str = Field(min_length=1, max_length=64)
    batch: Optional[str] = Field(default=None, max_length=64)


@app.get("/workspaces/{ws}/kernel")
async def kernel_state(ws: str) -> dict:
    workspaces.existing(ws)
    s = kernels.peek(ws)
    base = s.view() if s else {"state": "stopped", "message": "", "started_at": None, "running_cell": None,
                               "queued": 0, "executions": []}
    return {**base, "env_ready": workspaces.env_ready(ws)}


@app.post("/workspaces/{ws}/kernel/start")
async def kernel_start(ws: str) -> dict:
    s = kernels.session(ws)
    await s.start()
    return s.view()


@app.post("/workspaces/{ws}/kernel/restart")
async def kernel_restart(ws: str) -> dict:
    s = kernels.session(ws)
    await s.restart()
    return s.view()


@app.post("/workspaces/{ws}/kernel/interrupt")
async def kernel_interrupt(ws: str) -> dict:
    s = kernels.session(ws)
    await s.interrupt()
    return s.view()


@app.post("/workspaces/{ws}/kernel/shutdown")
async def kernel_shutdown(ws: str) -> dict:
    s = kernels.session(ws)
    await s.stop()
    return s.view()


@app.post("/workspaces/{ws}/kernel/execute")
async def kernel_execute(ws: str, b: ExecuteBody) -> dict:
    s = kernels.session(ws)
    ex = await s.submit(b.code, b.cell_id, b.batch)
    return {"id": ex.id}


@app.get("/workspaces/{ws}/executions/{eid}")
async def execution(ws: str, eid: str, v: Optional[int] = None) -> dict:
    s = kernels.peek(ws)
    ex = s.execs.get(eid) if s else None
    if ex is None:
        raise WorkspaceError("Unknown or expired execution.", 404)
    return ex.view(v)


# ---- packages -----------------------------------------------------------------------------------------------------

class InstallBody(BaseModel):
    spec: str = Field(max_length=1000)


@app.get("/workspaces/{ws}/packages")
async def packages(ws: str) -> dict:
    workspaces.existing(ws)
    pk = await asyncio.to_thread(kernels.installed, ws)
    cur = kernels.last_install(ws)
    return {"packages": [p for p in pk if p["name"].lower() not in ("pip", "setuptools", "wheel")],
            "install": cur.view() if cur else None}


@app.post("/workspaces/{ws}/packages/install")
async def install(ws: str, b: InstallBody) -> dict:
    ins = await kernels.start_install(ws, workspaces.pip_args(b.spec))
    return ins.view()


@app.post("/workspaces/{ws}/packages/cancel")
async def cancel_install(ws: str) -> dict:
    await kernels.cancel_install(ws)
    return {"ok": True}


@app.get("/workspaces/{ws}/installs/{iid}")
async def install_state(ws: str, iid: str, v: Optional[int] = None) -> dict:
    cur = kernels.last_install(ws)
    if cur is None or cur.id != iid:
        raise WorkspaceError("Unknown install.", 404)
    return cur.view(v)

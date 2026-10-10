"""
df-studio/server.py

FastAPI app for DataFrame Studio — load a CSV/JSON/XML/Parquet file, apply
pandas transformations through a UI (rename/drop/add column, filter, sort),
inspect it (describe/info/nunique/value_counts), export the result.

Session model: one uuid4 cookie per browser tab, held in engine.SESSIONS
(in-memory — see engine.py's docstring for why that's an accepted
tradeoff). Every mutating endpoint re-derives the current DataFrame by
replaying the session's step list over the original upload; nothing here
mutates a DataFrame in place.

Every endpoint that calls into pandas (load/step/insight/export/template)
runs that call via asyncio.to_thread — with --workers 1 (pinned, see
../Dockerfile), a synchronous pandas call directly inside an async def
blocks the ONE process's entire event loop for its whole duration, which
on a large file looks exactly like the app hanging (no response, no other
request served, not even a healthcheck) until it finishes. to_thread runs
it on a worker thread instead so the event loop stays free.

Endpoints
---------
GET  /              — the single-page UI
GET  /session       — restore the current session's preview on page load (survives a browser refresh)
POST /load          — upload a file, start a new session
POST /step          — append a transformation step, return new preview
POST /step/check    — run a step WITHOUT committing it (query box "Check" mode)
POST /step/remove   — remove a step by index, return recomputed preview
POST /step/reset    — clear all steps, back to the original upload
POST /preview-mode  — switch the preview grid between head/sample (see engine.Session)
GET  /insight       — describe / info / nunique / value_counts (read-only)
GET  /export        — download the current result as csv/json/parquet
"""

from __future__ import annotations

import asyncio
import io
from typing import Any, Optional

from fastapi import FastAPI, Form, Request, Response, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from pydantic import BaseModel

try:  # package import when mounted inside the toolbox (df_studio.*)
    from df_studio import engine, templates_store
except ImportError:  # flat import when run standalone from within this folder
    import engine
    import templates_store

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core import vault
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import vault

app = FastAPI(
    title="DataFrame Studio",
    description="Click-driven pandas: load, transform, and export CSV/JSON/XML/Parquet.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"
_COOKIE = "df_studio_sid"


class StepRequest(BaseModel):
    type: str
    params: dict[str, Any] = {}


class RemoveRequest(BaseModel):
    index: int


class TemplateNameRequest(BaseModel):
    name: str


class PreviewModeRequest(BaseModel):
    mode: str
    resample: bool = False


class LoadFromVaultRequest(BaseModel):
    id: str
    name: str


def _session_id(request: Request) -> Optional[str]:
    return request.cookies.get(_COOKIE)


def _error(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": str(exc)})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))


@app.get("/session")
async def get_current_session(request: Request):
    """Restore the current session's preview on page load, if one exists —
    what lets a browser refresh survive instead of losing everything. A
    missing/unknown cookie is the normal "nothing loaded yet" case, not an
    error, so this returns 200 with active=False rather than a banner."""
    session_id = _session_id(request)
    if not session_id or session_id not in engine.SESSIONS:
        return {"active": False}
    session = engine.SESSIONS[session_id]
    df = engine.recompute(session)
    preview = engine.build_preview(session, df)
    preview["active"] = True
    return preview


@app.post("/preview-mode")
async def set_preview_mode(body: PreviewModeRequest, request: Request):
    try:
        session = engine.get_session(_session_id(request))
        return engine.set_preview_mode(session, body.mode, resample=body.resample)
    except engine.StepError as exc:
        return _error(exc)


@app.post("/load")
async def load(
    response: Response,
    file: UploadFile = File(...),
    # CSV/TSV/TXT
    sep: str = Form(""),
    encoding: str = Form("utf-8"),
    header: bool = Form(True),
    nrows: int = Form(0),
    # JSON
    orient: str = Form(""),
    lines: str = Form(""),  # "" = auto-detect, "true"/"false" = explicit
    # XML
    xpath: str = Form(""),
    # Parquet — comma-separated column names, empty = all columns
    columns: str = Form(""),
):
    try:
        content = await file.read()  # Starlette streams this from the network asynchronously already
        df = await asyncio.to_thread(
            engine.load_dataframe,
            file.filename or "upload",
            content,
            sep=sep or None,
            encoding=encoding or "utf-8",
            header=header,
            nrows=nrows if nrows and nrows > 0 else None,
            orient=orient or None,
            lines={"true": True, "false": False}.get(lines),
            xpath=xpath or None,
            columns=[c.strip() for c in columns.split(",") if c.strip()] or None,
        )
        session_id = engine.create_session(file.filename or "upload", df)
        session = engine.get_session(session_id)
        preview = engine.build_preview(session, df)
    except engine.StepError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001 - surface parser errors (bad csv/xml/etc) to the UI
        return _error(exc)
    response = JSONResponse(content=preview)
    response.set_cookie(_COOKIE, session_id, httponly=True, samesite="lax")
    return response


@app.post("/load/vault")
async def load_from_vault(response: Response, body: LoadFromVaultRequest):
    """Load a dataset saved in core.vault (e.g. by duck-lab's or
    sql-studio's "Save/Export to Vault") as a new session, the same way
    /load does for an uploaded file. df-studio already reads every
    upload fully into memory as its own accepted, documented design
    (unlike duck-lab) — this reuses that exact path, just sourcing
    `content` from a decrypted vault blob instead of an HTTP upload."""
    try:
        tmp_path = await asyncio.to_thread(vault.load_dataset_file, body.id)
    except vault.SecretNotFound as exc:
        return _error(exc, status=404)
    try:
        filename = f"{body.name}{tmp_path.suffix}"
        content = await asyncio.to_thread(tmp_path.read_bytes)
    finally:
        tmp_path.unlink(missing_ok=True)
    try:
        df = await asyncio.to_thread(engine.load_dataframe, filename, content)
        session_id = engine.create_session(filename, df)
        session = engine.get_session(session_id)
        preview = engine.build_preview(session, df)
    except engine.StepError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001 - surface parser errors to the UI
        return _error(exc)
    response = JSONResponse(content=preview)
    response.set_cookie(_COOKIE, session_id, httponly=True, samesite="lax")
    return response


@app.post("/step")
async def add_step(body: StepRequest, request: Request):
    try:
        session = engine.get_session(_session_id(request))
        df = await asyncio.to_thread(engine.apply_step, session, body.type, body.params)
        return engine.build_preview(session, df)
    except engine.StepError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@app.post("/step/check")
async def check_step(body: StepRequest, request: Request):
    """Run a step and return what it WOULD produce, without adding it to the
    pipeline — lets the query box's Check mode iterate before committing."""
    try:
        session = engine.get_session(_session_id(request))
        df = await asyncio.to_thread(engine.preview_step, session, body.type, body.params)
        preview = engine.build_preview(session, df)
    except engine.StepError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)
    preview["committed"] = False
    return preview


@app.post("/step/remove")
async def remove_step(body: RemoveRequest, request: Request):
    try:
        session = engine.get_session(_session_id(request))
        df = await asyncio.to_thread(engine.remove_step, session, body.index)
        return engine.build_preview(session, df)
    except engine.StepError as exc:
        return _error(exc)


@app.post("/step/reset")
async def reset_steps(request: Request):
    try:
        session = engine.get_session(_session_id(request))
        df = engine.reset_steps(session)  # trivial (clears a list) — no thread needed
        return engine.build_preview(session, df)
    except engine.StepError as exc:
        return _error(exc)


@app.get("/insight")
async def insight(request: Request, kind: str, column: Optional[str] = None):
    try:
        session = engine.get_session(_session_id(request))
        df = await asyncio.to_thread(engine.recompute, session)
        return await asyncio.to_thread(engine.compute_insight, df, kind, column)
    except engine.StepError as exc:
        return _error(exc)


@app.get("/script")
async def script(request: Request):
    try:
        session = engine.get_session(_session_id(request))
    except engine.StepError as exc:
        return _error(exc)
    return {"script": engine.generate_script(session)}


@app.get("/template/list")
async def list_templates():
    return {"templates": templates_store.list_templates()}


@app.post("/template/save")
async def save_template(body: TemplateNameRequest, request: Request):
    try:
        session = engine.get_session(_session_id(request))
        if not session.steps:
            return _error(ValueError("Pipeline is empty — nothing to save."))
        templates_store.save_template(body.name, session.steps)
    except (engine.StepError, ValueError) as exc:
        return _error(exc)
    return {"templates": templates_store.list_templates()}


@app.post("/template/apply")
async def apply_template(body: TemplateNameRequest, request: Request):
    try:
        session = engine.get_session(_session_id(request))
        template_steps = templates_store.get_template(body.name)
        df, errors = await asyncio.to_thread(engine.apply_template, session, template_steps)
        preview = engine.build_preview(session, df)
    except (engine.StepError, ValueError) as exc:
        return _error(exc)
    preview["template_errors"] = errors
    return preview


@app.post("/template/delete")
async def delete_template(body: TemplateNameRequest):
    templates_store.delete_template(body.name)
    return {"templates": templates_store.list_templates()}


_EXPORT_MEDIA_TYPES = {"csv": "text/csv", "json": "application/json", "parquet": "application/octet-stream"}
_VALID_JSON_ORIENTS = {"split", "records", "index", "columns", "values", "table"}


@app.get("/export")
async def export(
    request: Request,
    format: str = "csv",
    # CSV
    sep: str = ",",
    index: bool = False,
    # JSON
    orient: str = "records",
    date_format: str = "iso",
    indent: int = 0,
    # Parquet
    compression: str = "snappy",
):
    if format not in _EXPORT_MEDIA_TYPES:
        return _error(ValueError(f"Unsupported export format '{format}'."))
    if format == "json" and orient not in _VALID_JSON_ORIENTS:
        return _error(ValueError(f"Unsupported JSON orient '{orient}'."))
    try:
        session = engine.get_session(_session_id(request))
        df = await asyncio.to_thread(engine.recompute, session)
    except engine.StepError as exc:
        return _error(exc)

    buf = io.BytesIO()
    try:
        if format == "csv":
            await asyncio.to_thread(df.to_csv, buf, index=index, sep=sep or ",")
        elif format == "json":
            await asyncio.to_thread(
                df.to_json, buf, orient=orient, date_format=date_format or "iso", indent=(indent or None)
            )
        else:  # parquet
            comp = None if compression in ("", "none") else compression
            await asyncio.to_thread(df.to_parquet, buf, index=index, compression=comp)
    except Exception as exc:  # noqa: BLE001 - e.g. a multi-character CSV separator, bad compression codec
        return _error(exc)
    media_type = _EXPORT_MEDIA_TYPES[format]
    buf.seek(0)
    stem = session.filename.rsplit(".", 1)[0] if "." in session.filename else session.filename
    filename = f"{stem}.{format}"
    return Response(
        content=buf.read(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

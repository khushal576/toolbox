"""
duck-lab/server.py

FastAPI app for Duck Lab: upload several CSV/JSON/XML sources, join/analyze
them with SQL (DuckDB), paginated results. See engine.py for why DuckDB and
for the materialize-once-paginate-many model. See ../CLAUDE.md for the
repo-wide architecture this tool is mounted into.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

try:  # package import when mounted inside the toolbox (duck_lab.*)
    from duck_lab import engine
except ImportError:  # flat import when run standalone from within this folder
    import engine

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core import vault
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import vault

app = FastAPI(title="Duck Lab")

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"
_COOKIE_NAME = "duck_lab_sid"


def _get_session(request: Request) -> tuple[str, "engine.Session"]:
    sid = request.cookies.get(_COOKIE_NAME) or uuid.uuid4().hex
    return sid, engine.get_or_create_session(sid)


def _with_cookie(response: JSONResponse, sid: str) -> JSONResponse:
    response.set_cookie(_COOKIE_NAME, sid, httponly=True, samesite="lax")
    return response


def _table_meta_json(meta: "engine.TableMeta") -> dict:
    return {
        "name": meta.name,
        "format": meta.format,
        "columns": meta.columns,
        "row_count": meta.row_count,
        "source_file": meta.source_file,
    }


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(_UI_PATH.read_text())


@app.get("/tables")
async def list_tables(request: Request) -> JSONResponse:
    sid, session = _get_session(request)
    tables = [_table_meta_json(m) for m in session.tables.values()]
    return _with_cookie(JSONResponse({"ok": True, "tables": tables}), sid)


@app.post("/upload")
async def upload(request: Request, file: UploadFile) -> JSONResponse:
    sid, session = _get_session(request)
    filename = file.filename or "upload"

    try:
        if filename.lower().endswith(".xml"):  # fully read once, see engine.load_xml's docstring
            raw = (await file.read()).decode("utf-8", errors="replace")
            meta = engine.load_xml(session, raw, filename)
        else:
            # Stream straight to disk — never buffer the whole file in
            # Python memory, DuckDB scans the saved file itself.
            # engine.load_file (via core.file_source) detects csv/json/
            # parquet from the extension and raises ValueError for
            # anything else.
            saved_path = session.data_dir / f"{uuid.uuid4().hex}_{filename}"
            with saved_path.open("wb") as out:
                shutil.copyfileobj(file.file, out)
            meta = engine.load_file(session, saved_path, filename)
    except (engine.QueryError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    return _with_cookie(JSONResponse({"ok": True, "table": _table_meta_json(meta)}), sid)


class LoadFromVaultRequest(BaseModel):
    id: str
    name: str


@app.post("/load/vault")
async def load_from_vault(request: Request, body: LoadFromVaultRequest) -> JSONResponse:
    """Load a dataset saved in core.vault (e.g. by this tool's own
    "Save to Vault" or sql-studio's "Export FULL result to Vault") as a
    new table — the consumer-side counterpart to /export/vault. The
    decrypted file is moved into this session's own data_dir (not left
    as an ephemeral tempfile) because engine.load_file() creates a LAZY
    DuckDB view backed by that path — it has to keep existing for as
    long as the view might be queried, same as an uploaded file already
    does."""
    sid, session = _get_session(request)
    try:
        tmp_path = vault.load_dataset_file(body.id)
    except vault.SecretNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        dest_path = session.data_dir / f"{uuid.uuid4().hex}_{body.name}{tmp_path.suffix}"
        shutil.move(str(tmp_path), str(dest_path))
        meta = engine.load_file(session, dest_path, dest_path.name)
    except (engine.QueryError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return _with_cookie(JSONResponse({"ok": True, "table": _table_meta_json(meta)}), sid)


@app.get("/preview/{name}")
async def preview_table(request: Request, name: str) -> JSONResponse:
    sid, session = _get_session(request)
    try:
        result = engine.preview_table(session, name)
    except engine.QueryError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _with_cookie(JSONResponse({"ok": True, **result}), sid)


@app.post("/table/remove")
async def remove_table(request: Request) -> JSONResponse:
    sid, session = _get_session(request)
    body = await request.json()
    name = body.get("name", "")
    try:
        engine.remove_table(session, name)
    except engine.QueryError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _with_cookie(JSONResponse({"ok": True}), sid)


@app.post("/query")
async def query(request: Request) -> JSONResponse:
    sid, session = _get_session(request)
    body = await request.json()
    sql = body.get("sql", "")
    try:
        result = engine.run_query(session, sql)
    except engine.QueryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _with_cookie(JSONResponse({"ok": True, **result}), sid)


@app.get("/page")
async def page(request: Request, offset: int = 0, limit: int = engine.DEFAULT_PAGE_SIZE) -> JSONResponse:
    sid, session = _get_session(request)
    try:
        result = engine.fetch_page(session, offset, limit)
    except engine.QueryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _with_cookie(JSONResponse({"ok": True, **result}), sid)


@app.get("/export")
async def export(request: Request, format: str = "csv") -> FileResponse:
    _sid, session = _get_session(request)
    try:
        path = engine.export_result(session, format)
    except engine.QueryError as exc:
        raise HTTPException(400, str(exc)) from exc
    return FileResponse(path, filename=f"duck_lab_result.{format}")


class SaveToVaultRequest(BaseModel):
    name: str


@app.post("/export/vault")
async def export_to_vault(request: Request, body: SaveToVaultRequest) -> JSONResponse:
    """Save the current query result into the shared vault (core.vault)
    as a dataset — e.g. so the orchestrator can feed it into DataDiff
    Pro later. Uses Parquet (via engine.export_result, DuckDB's own
    streaming COPY TO) rather than CSV/JSON — preserves types and is
    what the orchestrator's vault_dataset source reads back fastest.
    The temp export file is deleted immediately after being
    chunk-encrypted into the vault; it never lingers beyond this call.
    """
    _sid, session = _get_session(request)
    try:
        tmp_path = engine.export_result(session, "parquet")
    except engine.QueryError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        meta = {
            "format": "parquet",
            "columns": session.result_columns,
            "row_count": session.result_total_rows,
        }
        secret_id = vault.save_dataset(body.name, "duckdb_result", meta, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return JSONResponse({"ok": True, "id": secret_id})


@app.post("/session/reset")
async def session_reset(request: Request) -> JSONResponse:
    sid, session = _get_session(request)
    engine.reset_session(session)
    return _with_cookie(JSONResponse({"ok": True}), sid)

"""
mini-sheet/server.py

FastAPI app for Mini Sheet — a small spreadsheet for editing data by hand (roadmap M1). The sheet itself lives in the
browser (ui/index.html); the server only opens data, saves it and converts files:

GET  /              the page
GET  /formula.js    the formula language (also run by node in the unit tests)
GET  /wrap.js       the wrap-text line counter (also run by node in the unit tests)
GET  /catalog-lite  workspaces → tables (name, rows, columns) for the "Open from Vault Data" picker
GET  /table         ?ws=&name=&limit=  one Vault Data table as {columns, rows}; 413 + row_count when it is too big
POST /save          {workspace, table, mode, columns, rows, origin}  → Vault Data table (typed, every cell checked)
POST /save-all      {workspace, on_exists, items:[{sheet, table, columns, rows, origin}]}  → every sheet of the workbook, all-or-nothing checks
GET/PUT/DELETE /draft   the browser's unsaved workbook (autosave; cookie `mini_sheet_sid`; gzip JSON in Redis+S3 storage — roadmap M2)
POST /parse         {text, header, limit}  pasted text → {columns, rows}
POST /import        multipart file (csv/tsv/json/xlsx), header, sheet, limit, all_sheets → {columns, rows} | {sheets:[…], skipped:[…]}
POST /export        {format: csv|xlsx, columns, rows}  or  {format: xlsx, sheets:[{name, columns, rows}]}  → a download

No sheet is kept in this process's memory: the only thing remembered between requests is the draft (above), and that lives in
Redis + S3 storage, so any worker answers. Every call that touches pandas/DuckDB/pyarrow/openpyxl runs via asyncio.to_thread so a
big table never freezes the event loop.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import secrets
import shutil
import sys
import zlib
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

try:  # package import when mounted inside the toolbox (mini_sheet.*)
    from mini_sheet import draftstore, sheetio
except ImportError:  # flat import when run standalone from within this folder
    import draftstore
    import sheetio

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core import lake as lake_store
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import lake as lake_store

lake = lake_store.scoped("mini-sheet")  # Vault Data scope from manifest.yaml `vault: {data: write}`

app = FastAPI(title="Mini Sheet", description="A small spreadsheet for editing data by hand.")

_UI = Path(__file__).resolve().parent / "ui"


class SaveBody(BaseModel):
    workspace: str = ""
    table: str
    mode: str = "create"                    # create | overwrite | replace_keep (rename the old table to a backup, then create)
    columns: list[dict[str, Any]]
    rows: list[list[Any]]
    origin: Optional[dict[str, Any]] = None  # {workspace, table, partial} — what the sheet was opened from


class SaveItem(BaseModel):
    sheet: str = ""                         # the tab's name (only used in messages)
    table: str
    columns: list[dict[str, Any]]
    rows: list[list[Any]]
    origin: Optional[dict[str, Any]] = None


class SaveAllBody(BaseModel):
    workspace: str = ""
    on_exists: str = "ask"                  # ask (409 listing the tables that exist) | replace_keep | overwrite
    items: list[SaveItem]


class ParseBody(BaseModel):
    text: str
    header: bool = True
    limit: Optional[int] = None


class ExportSheet(BaseModel):
    name: str
    columns: list[dict[str, Any]]
    rows: list[list[Any]]


class ExportBody(BaseModel):
    format: str = "csv"
    name: str = "sheet"
    columns: list[dict[str, Any]] = []
    rows: list[list[Any]] = []
    sheets: Optional[list[ExportSheet]] = None   # several sheets → one .xlsx with a worksheet each


def _err(exc: Exception, status: int = 400, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": str(exc), **extra})


def _lake_status(exc: Exception) -> int:
    if isinstance(exc, lake_store.NotFound):
        return 404
    if isinstance(exc, lake_store.ScopeError):
        return 403
    return 409 if "already exists" in str(exc) else 400


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    return HTMLResponse((_UI / "index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/formula.js", include_in_schema=False)
def formula_js() -> FileResponse:
    return FileResponse(_UI / "formula.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/wrap.js", include_in_schema=False)
def wrap_js() -> FileResponse:
    return FileResponse(_UI / "wrap.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/limits")
def limits() -> dict[str, Any]:
    return {"max_rows": sheetio.MAX_ROWS, "max_cols": sheetio.MAX_COLS, "max_cells": sheetio.MAX_CELLS,
            "max_upload_mb": sheetio.MAX_UPLOAD_BYTES // 2**20, "max_sheets": sheetio.MAX_SHEETS,
            "sheet_name_max": sheetio.SHEET_NAME_MAX, "draft_max_mb": _DRAFT_MAX_GZ // 2**20}


@app.get("/catalog-lite")
async def catalog_lite() -> JSONResponse:
    def build() -> list[dict[str, Any]]:
        out = []
        for w in lake.list_workspaces():
            tables = [{"name": t["name"], "rows": t["row_count"], "columns": len(t["columns"]), "kind": t["kind"]}
                      for t in lake.list_tables(w["name"])]
            out.append({"name": w["name"], "tables": tables})
        return out

    try:
        return JSONResponse({"workspaces": await asyncio.to_thread(build)})
    except (lake_store.LakeError, lake_store.ScopeError) as exc:
        return _err(exc, _lake_status(exc))


@app.get("/table")
async def get_table(ws: str, name: str, limit: Optional[int] = None) -> JSONResponse:
    """One table for editing. Refuses (413) a table bigger than the limits unless `limit` asks for its first N rows."""
    if limit is not None and limit < 1:
        return _err(sheetio.SheetError("limit must be 1 or more"))
    try:
        t = await asyncio.to_thread(lake.get_table, ws, name)
        ncols = len(t["columns"])
        if ncols > sheetio.MAX_COLS:
            return _err(sheetio.SheetError(f"{ws}.{name} has {ncols} columns — Mini Sheet handles up to {sheetio.MAX_COLS}."),
                        413, max_cols=sheetio.MAX_COLS)
        allowed = min(sheetio.MAX_ROWS, sheetio.MAX_CELLS // max(1, ncols))
        total = int(t["row_count"])
        if total > allowed and not limit:
            return _err(sheetio.SheetError(f"{ws}.{name} has {total:,} rows — Mini Sheet handles up to {allowed:,}. "
                                           f"You can open its first {allowed:,} rows."),
                        413, row_count=total, max_rows=allowed)
        use = min(int(limit), allowed) if limit else None
        tmp = Path(tempfile.mkdtemp(prefix="msheet_"))
        try:
            await asyncio.to_thread(lake.export_table, ws, name, tmp / "t.parquet", "parquet", use)
            data = await asyncio.to_thread(sheetio.table_to_json, tmp / "t.parquet", t["columns"], use)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except (lake_store.LakeError, lake_store.ScopeError) as exc:
        return _err(exc, _lake_status(exc))
    except sheetio.SheetError as exc:
        return _err(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. an unreadable Parquet part
        return _err(exc, 500)
    return JSONResponse({"workspace": ws, "table": name, "row_count": total, "loaded_rows": len(data["rows"]),
                         "partial": len(data["rows"]) < total, **data})


def _split(workspace: str, table: str) -> tuple[str, str]:
    """`orders` → (workspace from the form or `system`, orders); `sales.orders` → (sales, orders). Names are validated."""
    table = (table or "").strip()
    ws = (workspace or "").strip()
    if "." in table:
        ws, table = (p.strip() for p in table.split(".", 1))
    ws = ws or lake_store.SYSTEM_WORKSPACE
    return lake_store.check_name(ws, "workspace name"), lake_store.check_name(table, "table name")


def _backup_name(table: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"{table[:63 - len(stamp) - 8]}_backup_{stamp}"


def _partial_guard(o: dict[str, Any], ws: str, name: str, mode: str) -> None:
    if o.get("partial") and mode != "create" and (o.get("workspace"), o.get("table")) == (ws, name):
        raise sheetio.SheetError(
            f"This sheet holds only the first rows of {ws}.{name}. Saving over it would delete the rest — "
            "save it under a new name instead.")


async def _write_sheet(ws: str, name: str, arrow: Any, mode: str, o: dict[str, Any]) -> tuple[dict[str, Any], Optional[str]]:
    """Parquet-write an already checked sheet and store it. mode: create | overwrite | replace_keep (old table renamed to a backup)."""
    import pyarrow.parquet as pq

    tmp = Path(tempfile.mkdtemp(prefix="msheet_"))
    try:
        out = tmp / "sheet.parquet"
        await asyncio.to_thread(pq.write_table, arrow, out)
        source = {"kind": "mini-sheet", "rows": arrow.num_rows,
                  **({"opened_from": f"{o.get('workspace')}.{o.get('table')}"} if o.get("table") else {})}
        backup = None
        if mode == "replace_keep":
            try:
                await asyncio.to_thread(lake.get_table, ws, name)
                backup = _backup_name(name)
                await asyncio.to_thread(lake.rename_table, ws, name, new_name=backup)
            except lake_store.NotFound:
                backup = None
        try:
            t = await asyncio.to_thread(lambda: lake.write_table(
                ws, name, [out], mode="overwrite" if mode == "overwrite" else "create",
                source=source, create_workspace_if_missing=True))
        except Exception:
            if backup:   # put the old table back — a failed save must not leave the name missing
                await asyncio.to_thread(lake.rename_table, ws, backup, new_name=name)
            raise
        return t, (f"{ws}.{backup}" if backup else None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.post("/save")
async def save(body: SaveBody) -> JSONResponse:
    """Check every cell against its column's type, then store the sheet as a Parquet-backed Vault Data table.
    422 = some cells don't fit their column (listed); 409 = the table exists and mode is create (the page asks)."""
    if body.mode not in ("create", "overwrite", "replace_keep"):
        return _err(sheetio.SheetError("mode must be create, overwrite or replace_keep"))
    try:
        ws, name = _split(body.workspace, body.table)
        o = body.origin or {}
        _partial_guard(o, ws, name, body.mode)
        arrow, errors, total = await asyncio.to_thread(sheetio.coerce_table, body.columns, body.rows)
        if total:
            return JSONResponse(status_code=422, content={
                "error": f"{total:,} cell(s) don't fit their column's type — nothing was saved.",
                "cell_errors": errors, "total_errors": total})
        t, backup = await _write_sheet(ws, name, arrow, body.mode, o)
    except (lake_store.LakeError, lake_store.ScopeError) as exc:
        return _err(exc, _lake_status(exc))
    except sheetio.TooBig as exc:
        return _err(exc, 413, **exc.info)
    except sheetio.SheetError as exc:
        return _err(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. a value pyarrow can't store
        return _err(exc)
    return JSONResponse({"ok": True, "table": t, "backup": backup})


@app.post("/save-all")
async def save_all(body: SaveAllBody) -> JSONResponse:
    """Every sheet of the workbook → its own Vault Data table. Everything is CHECKED before anything is written: a bad cell in any
    sheet (422, listed per sheet), a name clash between sheets (400) or an existing table when on_exists is `ask` (409, listed)
    stops the whole save. Only then are the sheets written one after the other (a failure during the writes is reported per sheet)."""
    if body.on_exists not in ("ask", "replace_keep", "overwrite"):
        return _err(sheetio.SheetError("on_exists must be ask, replace_keep or overwrite"))
    if not body.items:
        return _err(sheetio.SheetError("There is nothing to save."))
    try:
        if len(body.items) > sheetio.MAX_SHEETS:
            raise sheetio.TooBig(f"A workbook can have at most {sheetio.MAX_SHEETS} sheets.", max_sheets=sheetio.MAX_SHEETS)
        sheetio.check_workbook_size([{"name": it.sheet, "columns": it.columns, "rows": it.rows} for it in body.items])
        targets: list[tuple[str, str]] = []
        for it in body.items:
            try:
                targets.append(_split(body.workspace, it.table))
            except lake_store.LakeError as exc:
                raise sheetio.SheetError(f"Sheet “{it.sheet or it.table}”: {exc}") from None
        seen: dict[tuple[str, str], str] = {}
        for it, tg in zip(body.items, targets):
            if tg in seen:
                raise sheetio.SheetError(f"Sheets “{seen[tg]}” and “{it.sheet or it.table}” would both be saved as {tg[0]}.{tg[1]} — give them different table names.")
            seen[tg] = it.sheet or it.table
        arrows, bad = [], []
        for it, (ws, name) in zip(body.items, targets):
            _partial_guard(it.origin or {}, ws, name, "create" if body.on_exists == "ask" else body.on_exists)
            arrow, errors, total = await asyncio.to_thread(sheetio.coerce_table, it.columns, it.rows)
            arrows.append(arrow)
            if total:
                bad.append({"sheet": it.sheet or it.table, "cell_errors": errors, "total_errors": total})
        if bad:
            n = sum(b["total_errors"] for b in bad)
            return JSONResponse(status_code=422, content={
                "error": f"{n:,} cell(s) in {len(bad)} sheet(s) don't fit their column's type — nothing was saved.",
                "sheets": bad, "total_errors": n})
        existing = []
        for ws, name in targets:
            try:
                await asyncio.to_thread(lake.get_table, ws, name)
                existing.append(f"{ws}.{name}")
            except lake_store.NotFound:
                pass
        if existing and body.on_exists == "ask":
            return JSONResponse(status_code=409, content={
                "error": f"{len(existing)} table(s) already exist: " + ", ".join(existing) + " — nothing was saved.", "existing": existing})
        results = []
        for it, (ws, name), arrow in zip(body.items, targets, arrows):
            label = it.sheet or it.table
            mode = body.on_exists if f"{ws}.{name}" in existing else "create"
            try:
                t, backup = await _write_sheet(ws, name, arrow, mode, it.origin or {})
                results.append({"sheet": label, "ok": True, "table": t, "backup": backup})
            except Exception as exc:  # noqa: BLE001 - reported for this sheet; the others still get their chance
                results.append({"sheet": label, "ok": False, "error": str(exc)})
    except (lake_store.LakeError, lake_store.ScopeError) as exc:
        return _err(exc, _lake_status(exc))
    except sheetio.TooBig as exc:
        return _err(exc, 413, **exc.info)
    except sheetio.SheetError as exc:
        return _err(exc)
    return JSONResponse({"ok": all(r["ok"] for r in results), "results": results})


# ---- the draft: the browser's unsaved workbook (roadmap M2) ------------------------------------------------------------------

_COOKIE = "mini_sheet_sid"
_DRAFT_MAX_GZ = int(os.environ.get("MINI_SHEET_DRAFT_MAX_MB") or 40) * 2**20          # the stored (gzip) size
_DRAFT_MAX_RAW = int(os.environ.get("MINI_SHEET_DRAFT_MAX_RAW_MB") or 400) * 2**20    # what it may expand to (zip-bomb guard)
_drafts: Any = None


def _backend() -> Any:
    global _drafts
    if _drafts is None:
        _drafts = draftstore.make_backend()
    return _drafts


def _sid(request: Request) -> Optional[str]:
    sid = request.cookies.get(_COOKIE)
    return sid if draftstore.valid_sid(sid) else None


class _Refused(Exception):
    def __init__(self, status: int, msg: str, **extra: Any):
        super().__init__(msg)
        self.status, self.extra = status, extra


async def _read_body(request: Request, limit: int) -> bytes:
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > limit:
        raise _Refused(413, f"The draft is bigger than {limit // 2**20} MB.")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _Refused(413, f"The draft is bigger than {limit // 2**20} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def _gunzip(data: bytes) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        raw = d.decompress(data, _DRAFT_MAX_RAW)
        if d.unconsumed_tail or not d.eof and len(raw) >= _DRAFT_MAX_RAW:
            raise _Refused(413, "The draft is too big once unpacked.")
        return raw
    except zlib.error:
        raise _Refused(400, "The draft is not valid gzip data.") from None


def _check_draft(raw: bytes) -> dict[str, Any]:
    """The draft must be a workbook we could open again: sheets with valid unique names inside the size limits."""
    try:
        d = json.loads(raw)
    except ValueError:
        raise _Refused(400, "The draft is not valid JSON.") from None
    wb = d.get("wb") if isinstance(d, dict) else None
    sheets = wb.get("sheets") if isinstance(wb, dict) else None
    if not isinstance(sheets, list) or not sheets:
        raise _Refused(400, "The draft has no sheets.")
    try:
        sheetio.check_sheet_names([sh.get("name") if isinstance(sh, dict) else None for sh in sheets])
        sheetio.check_workbook_size([{"name": sh.get("name"), "columns": sh.get("cols") or [], "rows": sh.get("rows") or []} for sh in sheets])
    except sheetio.TooBig as exc:
        raise _Refused(413, str(exc), **exc.info) from None
    except sheetio.SheetError as exc:
        raise _Refused(400, str(exc)) from None
    return {"sheets": len(sheets), "name": str(wb.get("name") or "")[:120], "changed": bool(d.get("changed"))}


@app.get("/draft")
async def get_draft(request: Request) -> Response:
    """The browser's unsaved workbook, or {"draft": null}. Reading it slides its expiry."""
    headers = {"Cache-Control": "no-store"}
    sid = _sid(request)
    got = await asyncio.to_thread(_backend().get, sid) if sid else None
    if not got:
        return JSONResponse({"draft": None}, headers=headers)
    meta, gz = got
    try:
        raw = await asyncio.to_thread(_gunzip, gz)
    except _Refused:
        return JSONResponse({"draft": None}, headers=headers)
    head = json.dumps({"rev": meta.get("rev"), "saved_at": meta.get("saved_at"), "size": meta.get("size")})[:-1]
    return Response(head.encode() + b',"draft":' + raw + b"}", media_type="application/json", headers=headers)


@app.put("/draft")
async def put_draft(request: Request) -> JSONResponse:
    """Store the browser's workbook. The body is the draft JSON, gzip-compressed (header X-Draft-Encoding: gzip) or plain.
    X-Draft-Rev = the revision this tab last saw ("" first time, "force" to take over): another tab's newer write → 409."""
    try:
        sid, fresh = _sid(request), False
        if not sid:
            sid, fresh = secrets.token_urlsafe(24), True
        enc = (request.headers.get("x-draft-encoding") or "identity").lower()
        body = await _read_body(request, _DRAFT_MAX_GZ if enc == "gzip" else _DRAFT_MAX_RAW)
        if enc == "gzip":
            gz, raw = body, await asyncio.to_thread(_gunzip, body)
        elif enc == "identity":
            raw = body
            gz = await asyncio.to_thread(gzip.compress, raw, 6)
        else:
            raise _Refused(400, "X-Draft-Encoding must be gzip or identity.")
        if len(gz) > _DRAFT_MAX_GZ:
            raise _Refused(413, f"The draft is bigger than {_DRAFT_MAX_GZ // 2**20} MB even when compressed — it was not saved.")
        info = await asyncio.to_thread(_check_draft, raw)
        rev_h = (request.headers.get("x-draft-rev") or "").strip().lower()
        expect = None if rev_h in ("force", "") else (int(rev_h) if rev_h.isdigit() else None)
        info["saved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            meta = await asyncio.to_thread(_backend().put, sid, gz, info, expect)
        except draftstore.RevConflict as exc:
            return JSONResponse(status_code=409, content={"error": "This workbook was changed in another tab.", "rev": exc.current})
        await asyncio.to_thread(_backend().sweep)
    except _Refused as exc:
        return JSONResponse(status_code=exc.status, content={"error": str(exc), **exc.extra})
    resp = JSONResponse({"ok": True, "rev": meta["rev"], "saved_at": meta["saved_at"], "size": meta["size"]})
    resp.set_cookie(_COOKIE, sid, httponly=True, samesite="lax", max_age=draftstore.TTL_SECONDS)
    return resp


@app.delete("/draft")
async def delete_draft(request: Request) -> JSONResponse:
    sid = _sid(request)
    if sid:
        await asyncio.to_thread(_backend().delete, sid)
    return JSONResponse({"ok": True})


@app.post("/parse")
async def parse(body: ParseBody) -> JSONResponse:
    try:
        if len(body.text) > sheetio.MAX_UPLOAD_BYTES:
            raise sheetio.TooBig("The pasted text is too big for Mini Sheet.", max_mb=sheetio.MAX_UPLOAD_BYTES // 2**20)
        data = await asyncio.to_thread(sheetio.parse_text, body.text, body.header, body.limit)
    except sheetio.TooBig as exc:
        return _err(exc, 413, **exc.info)
    except sheetio.SheetError as exc:
        return _err(exc)
    return JSONResponse(data)


@app.post("/import")
async def import_file(file: UploadFile = File(...), header: bool = Form(True), sheet: Optional[str] = Form(None),
                      limit: Optional[int] = Form(None), all_sheets: bool = Form(False)) -> JSONResponse:
    try:
        raw = await file.read(sheetio.MAX_UPLOAD_BYTES + 1)
        fname = (file.filename or "")
        is_xlsx = fname.lower().endswith((".xlsx", ".xlsm")) or raw[:2] == b"PK"
        if all_sheets and is_xlsx and not sheet:     # a whole workbook: every sheet becomes a sheet
            if len(raw) > sheetio.MAX_UPLOAD_BYTES:
                raise sheetio.TooBig(f"“{fname}” is {len(raw) / 2**20:,.1f} MB — Mini Sheet is for small data (up to {sheetio.MAX_UPLOAD_BYTES // 2**20} MB). "
                                     "Load big files with Vault Data → Load files instead.", max_mb=sheetio.MAX_UPLOAD_BYTES // 2**20)
            data = await asyncio.to_thread(sheetio.parse_xlsx_all, raw, header, limit, f"“{fname}”")
        else:
            data = await asyncio.to_thread(sheetio.parse_file, fname, raw, header, sheet or None, limit)
    except sheetio.TooBig as exc:
        return _err(exc, 413, **exc.info)
    except sheetio.SheetError as exc:
        return _err(exc)
    return JSONResponse(data)


@app.post("/export")
async def export(body: ExportBody) -> Response:
    try:
        if body.sheets is not None:
            data, media, ext = await asyncio.to_thread(
                sheetio.build_export_workbook, body.format,
                [{"name": sh.name, "columns": sh.columns, "rows": sh.rows} for sh in body.sheets])
        else:
            data, media, ext = await asyncio.to_thread(sheetio.build_export, body.format, body.columns, body.rows)
    except sheetio.TooBig as exc:
        return _err(exc, 413, **exc.info)
    except sheetio.SheetError as exc:
        return _err(exc)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in body.name)[:60] or "sheet"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe}.{ext}"'})

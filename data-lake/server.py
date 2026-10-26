"""
data-lake/server.py — the Data Lake tool (roadmap phase L): load files into Vault Data tables (L2), query them with
SQL (L3, Athena style — query.py).

Endpoints
---------
GET  /                       the page
GET  /workspaces             workspaces (Vault Data) to load into
GET  /folder?path=           list a folder of the shared data folder (read-only mount)
GET  /folder/match?pattern=  which files a pattern matches (count, size, formats, first 20)
POST /upload                 stage browser files (multipart, several) → {upload_id, files}
POST /load                   start a load job → {job_id}   (body: see loader.run_load's spec)
GET  /loads/{job_id}         job state: running/queued, phase, percent, log, result
POST /loads/{job_id}/stop    stop it
GET  /recent                 latest table changes in Vault Data

SQL (L3)
GET  /catalog                every workspace → tables → columns (the editor's tree + autocomplete)
POST /query                  {sql, background} → instant: the result's first page (30 s limit); background: {query_id}
GET  /queries/{id}           state + record (+ first page when done)       POST /queries/{id}/stop
GET  /queries/{id}/rows      ?offset=&limit= (≤ 1000) — pages of the stored result
GET  /queries/{id}/download  ?format=csv|parquet
POST /queries/{id}/save      {workspace, table, mode} → the result becomes a Vault Data table
GET  /history                DELETE /history/{id}

Staging from a database (L4)
GET  /connections            saved Vault database connections (names only)
GET  /connections/{id}/tables  the connection's user tables
POST /stage                  {connection_id, workspace, mode, tables:[schema.table…] | sql + table} → {job_id}
GET  /stages/{job_id}        state, phase, rows, tables done, log      POST /stages/{job_id}/stop
GET  /saved   POST /saved {name, sql, description}   DELETE /saved/{id}

Loads run in the `worker` (core/jobs/runner.JobRunner) so a big file never ties up this process. Tables are written
through core.lake with this tool's scope (`vault: {data: write}` in manifest.yaml).
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field

try:
    from data_lake import loader, query, sources, staging
except ImportError:  # standalone: cd data-lake && uvicorn server:app
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import loader
    import query
    import sources
    import staging

from core import lake as lake_store
from core.jobs.runner import AlreadyRunning, JobRunner

app = FastAPI(title="Data Lake", description="Load files into Vault Data tables (Parquet) and query them with SQL.")
_UI = Path(__file__).resolve().parent / "ui" / "index.html"
JOBS = JobRunner("data-lake", log_size=200)
lake = lake_store.scoped("data-lake")


def _err(exc: Exception) -> HTTPException:
    if isinstance(exc, lake_store.NotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, lake_store.ScopeError):
        return HTTPException(403, str(exc))
    return HTTPException(400, str(exc))


class Source(BaseModel):
    kind: str
    upload_id: Optional[str] = None
    files: list[str] = Field(default_factory=list)
    pattern: Optional[str] = None
    url: Optional[str] = None


class LoadBody(BaseModel):
    source: Source
    workspace: str
    table: str
    mode: str = "create"
    format: str = "auto"
    header: Optional[bool] = None
    delimiter: Optional[str] = None
    add_filename: bool = False
    sheet: Optional[str] = None
    external: bool = False


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(_UI.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/workspaces")
def workspaces() -> dict[str, Any]:
    return {"workspaces": lake.list_workspaces(), "data_folder": sources.available()}


@app.get("/folder")
def folder(path: str = "") -> dict[str, Any]:
    try:
        return sources.browse(path)
    except sources.SourceError as exc:
        raise _err(exc) from exc


@app.get("/folder/match")
def folder_match(pattern: str) -> dict[str, Any]:
    try:
        return sources.summary(pattern)
    except sources.SourceError as exc:
        raise _err(exc) from exc


@app.post("/upload")
async def upload(files: list[UploadFile]) -> dict[str, Any]:
    """Stream each file to the staging area (S3 storage) — never held in memory."""
    await asyncio.to_thread(sources.sweep_uploads)
    uid = sources.new_upload_id()
    out = []
    sources.STAGE.local_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files):
        name = sources.stage_name(uid, i, f.filename or "file")
        dest = sources.STAGE.local(name)
        with dest.open("wb") as fh:
            await asyncio.to_thread(shutil.copyfileobj, f.file, fh, 1 << 20)
        await asyncio.to_thread(sources.STAGE.publish, uid, dest)
        out.append({"name": name, "filename": f.filename, "size": dest.stat().st_size,
                    "suggested_table": loader.default_table_name(f.filename or "file")})
    return {"upload_id": uid, "files": out}


@app.post("/load")
def load(body: LoadBody) -> dict[str, Any]:
    try:
        lake_store.check_name(body.workspace, "workspace name")
        lake_store.check_name(body.table, "table name")
    except lake_store.LakeError as exc:
        raise _err(exc) from exc
    if body.mode not in ("create", "append", "overwrite"):
        raise HTTPException(400, "mode must be create, append or overwrite")
    if body.mode == "create":
        try:
            lake.get_table(body.workspace, body.table)
            raise HTTPException(409, f"'{body.workspace}.{body.table}' already exists — choose append or overwrite.")
        except lake_store.NotFound:
            pass
    spec = body.model_dump()
    if body.source.kind == "upload" and body.source.files:
        spec["file"] = body.source.files[0].split(".", 2)[-1]
    job_id = sources.new_upload_id()
    try:
        JOBS.start(job_id, "load", loader.run_load, spec,
                   description=f"data-lake: load {body.workspace}.{body.table}")
    except AlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job_id}


@app.get("/loads/{job_id}")
def load_status(job_id: str) -> dict[str, Any]:
    v = JOBS.view(job_id)
    if not v["started_at"] and not v["queued"] and not v["running"]:
        raise HTTPException(404, "Unknown load.")
    p = v["progress"] or {}
    state = "queued" if v["queued"] else "running" if v["running"] else p.get("phase") if p.get("phase") in (
        "done", "failed") else "failed"
    return {"job_id": job_id, "state": state, "phase": p.get("phase"), "percent": p.get("percent"),
            "rows": p.get("rows"), "table": p.get("table"), "seconds": p.get("seconds"),
            "error": p.get("error") or v["error"], "logs": v["logs"]}


@app.post("/loads/{job_id}/stop")
def load_stop(job_id: str) -> dict[str, Any]:
    return {"stopping": JOBS.stop(job_id)}


@app.get("/recent")
def recent() -> dict[str, Any]:
    return {"recent": lake.recent_history(15)}


# ---- SQL (roadmap L3) ------------------------------------------------------------------------------------------

class QueryBody(BaseModel):
    sql: str
    background: bool = False


class SaveResultBody(BaseModel):
    workspace: str
    table: str
    mode: str = "create"


class SavedBody(BaseModel):
    name: str
    sql: str
    description: str = ""


@app.get("/catalog")
def catalog() -> dict[str, Any]:
    out = []
    for w in lake.list_workspaces():
        out.append({"name": w["name"], "description": w.get("description") or "",
                    "tables": [{"name": t["name"], "kind": t["kind"], "row_count": t["row_count"],
                                "description": t.get("description") or "",
                                "columns": [{"name": c["name"], "type": c.get("type")} for c in t["columns"]]}
                               for t in lake.list_tables(w["name"])]})
    return {"workspaces": out}


def _with_page(rec: dict[str, Any]) -> dict[str, Any]:
    if rec["state"] == "done":
        try:
            rec["page"] = query.page(rec["id"], 0, 100)
        except query.QueryError as exc:
            rec["page"], rec["result_error"] = None, str(exc)
    return rec


@app.post("/query")
def run_query(body: QueryBody) -> dict[str, Any]:
    qid = query.new_id()
    if body.background:
        query.start_record(qid, body.sql, "background", "queued")
        try:
            JOBS.start("q-" + qid, "query", query.run_query_job, qid, body.sql,
                       description=f"data-lake: query {qid}")
        except AlreadyRunning as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"query_id": qid, "state": "queued"}
    try:
        plan = query.analyse(body.sql)
    except query.QueryError as exc:
        raise HTTPException(400, str(exc)) from exc
    query.start_record(qid, body.sql, "instant", "running")
    try:
        rec = query.execute(qid, plan, mode="instant", timeout=query.INSTANT_SECONDS)
    except query.QueryError as exc:
        raise HTTPException(400, {"message": str(exc), "query_id": qid}) from exc
    return _with_page(rec)


@app.get("/queries/{qid}")
def query_status(qid: str) -> dict[str, Any]:
    try:
        rec = query.get(qid)
    except lake_store.NotFound as exc:
        raise _err(exc) from exc
    if rec["mode"] == "background" and rec["state"] in ("queued", "running"):
        v = JOBS.view("q-" + qid)
        if v["queued"]:
            rec["state"] = "queued"
        elif v["running"]:
            rec["state"], rec["phase"] = "running", (v["progress"] or {}).get("phase")
        elif v["started_at"] or v["finished_at"]:  # the job ended without recording (worker killed): say so
            rec = query.get(qid)
            if rec["state"] in ("queued", "running"):
                rec["state"], rec["error"] = "failed", v["error"] or "The worker stopped before the query finished."
        rec["logs"] = v["logs"]
    return _with_page(rec)


@app.post("/queries/{qid}/stop")
def query_stop(qid: str) -> dict[str, Any]:
    return {"stopping": JOBS.stop("q-" + qid)}


@app.get("/queries/{qid}/rows")
def query_rows(qid: str, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    try:
        return query.page(qid, offset, limit)
    except (query.QueryError, lake_store.LakeError) as exc:
        raise _err(exc) from exc


@app.get("/queries/{qid}/download")
def query_download(qid: str, format: str = "csv") -> FileResponse:  # noqa: A002 - query parameter name
    try:
        if format == "parquet":
            return FileResponse(query.result_file(qid), media_type="application/vnd.apache.parquet",
                                filename=f"query_{qid}.parquet")
        if format != "csv":
            raise HTTPException(400, "format must be csv or parquet")
        tmp = Path(tempfile.mkdtemp(prefix="lake_csv_"))
        out = query.export_csv(qid, tmp / f"query_{qid}.csv")
    except (query.QueryError, lake_store.LakeError) as exc:
        raise _err(exc) from exc
    return FileResponse(out, media_type="text/csv", filename=out.name,
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@app.post("/queries/{qid}/save")
def query_save(qid: str, body: SaveResultBody) -> dict[str, Any]:
    if body.mode not in ("create", "overwrite", "append"):
        raise HTTPException(400, "mode must be create, append or overwrite")
    try:
        return {"table": query.save_as_table(qid, body.workspace, body.table, body.mode)}
    except (query.QueryError, lake_store.LakeError, lake_store.ScopeError) as exc:
        raise _err(exc) from exc


@app.get("/history")
def query_history(limit: int = 50) -> dict[str, Any]:
    return {"history": query.history(limit)}


@app.delete("/history/{qid}")
def query_forget(qid: str) -> dict[str, Any]:
    query.forget(qid)
    return {"ok": True}


@app.get("/saved")
def saved_list() -> dict[str, Any]:
    return {"saved": query.list_saved()}


@app.post("/saved")
def saved_add(body: SavedBody) -> dict[str, Any]:
    try:
        return {"saved": query.save_query(body.name, body.sql, body.description)}
    except query.QueryError as exc:
        raise _err(exc) from exc


@app.delete("/saved/{sid}")
def saved_delete(sid: str) -> dict[str, Any]:
    query.delete_saved(sid)
    return {"ok": True}


# ---- staging database tables (roadmap L4) ----------------------------------------------------------------------

class StageBody(BaseModel):
    connection_id: str
    workspace: str
    mode: str = "create"
    tables: list[str] = Field(default_factory=list)
    sql: Optional[str] = None
    table: Optional[str] = None


@app.get("/connections")
def connections() -> dict[str, Any]:
    return {"connections": staging.list_connections()}


@app.get("/connections/{connection_id}/tables")
def connection_tables(connection_id: str) -> dict[str, Any]:
    try:
        return {"tables": staging.list_tables(connection_id)}
    except staging.StageError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/stage")
def stage(body: StageBody) -> dict[str, Any]:
    try:
        lake_store.check_name(body.workspace, "workspace name")
        if body.sql:
            lake_store.check_name(body.table or "", "table name")
    except lake_store.LakeError as exc:
        raise _err(exc) from exc
    if body.mode not in ("create", "append", "overwrite"):
        raise HTTPException(400, "mode must be create, append or overwrite")
    if not body.sql and not body.tables:
        raise HTTPException(400, "Choose at least one table (or write a query).")
    if body.mode == "create":
        targets = [body.table] if body.sql else list(staging.target_names(body.tables).values())
        existing = []
        for t in targets:
            try:
                lake.get_table(body.workspace, t)
                existing.append(f"{body.workspace}.{t}")
            except lake_store.NotFound:
                pass
        if existing:
            raise HTTPException(409, f"Already in Vault Data: {', '.join(existing)} — choose append or overwrite.")
    job_id = sources.new_upload_id()
    try:
        JOBS.start("s-" + job_id, "stage", staging.run_stage, body.model_dump(),
                   description=f"data-lake: stage into {body.workspace}")
    except AlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job_id}


@app.get("/stages/{job_id}")
def stage_status(job_id: str) -> dict[str, Any]:
    v = JOBS.view("s-" + job_id)
    if not v["started_at"] and not v["queued"] and not v["running"]:
        raise HTTPException(404, "Unknown staging run.")
    p = v["progress"] or {}
    state = "queued" if v["queued"] else "running" if v["running"] else p.get("phase") if p.get("phase") in (
        "done", "failed") else "failed"
    return {"job_id": job_id, "state": state, "phase": p.get("phase"), "rows": p.get("rows"),
            "tables_done": p.get("tables_done"), "tables_total": p.get("tables_total"), "tables": p.get("tables") or [],
            "seconds": p.get("seconds"), "error": p.get("error") or v["error"], "logs": v["logs"]}


@app.post("/stages/{job_id}/stop")
def stage_stop(job_id: str) -> dict[str, Any]:
    return {"stopping": JOBS.stop("s-" + job_id)}

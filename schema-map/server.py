"""
schema-map/server.py

Serves Schema Map's single-page frontend and its backend: connect to a
Postgres database, then fetch its table/foreign-key structure for the
progressive-disclosure graph view. See the plan this tool was built from
(schema-map/CLAUDE.md has the durable version) for the full design — the
short version: a read-only explorer for large, poorly-documented schemas,
built around "never render more than what's currently expanded" instead
of one big unreadable graph of every table at once.

Endpoints
---------
GET  /              — the single-page UI
POST /connect        — open a pool against one Postgres database (host/port/database/username/password)
POST /disconnect      — close the pool, idempotent
GET  /status          — current connection state (never the password)
GET  /paste-query       — the three self-contained SQL texts (tables, foreign keys, columns) for the paste-and-load Project origin (needs no connection)
GET  /schemas          — every non-system schema, with its table count
GET  /graph             — tables + foreign keys for one schema (or all) — no column data, see introspection_postgres.py
GET  /table/{schema}/{table} — one table's columns, fetched only when that table is clicked
GET  /columns            — EVERY table's columns in one call, across every non-system schema — the one deliberate exception to "never bulk-fetch columns for a live connection," used only by "Save as Version" to fill in any table nobody has clicked yet, so a saved snapshot is never silently incomplete

Projects/Versions (see project_store.py for the storage design — a
Project is the top-level container everything else will be scoped
under; a Version is a complete, independent schema snapshot, never a
diff — deleting one is always safe regardless of order):
POST   /projects                        — create a project ({name, origin})
GET    /projects                        — list all projects
GET    /projects/{project_id}           — one project's metadata
DELETE /projects/{project_id}           — permanently delete a project AND all its versions
POST   /projects/{project_id}/versions  — save a version ({snapshot, label?})
GET    /projects/{project_id}/versions  — list a project's versions (metadata only, no snapshot data)
GET    /versions/{version_id}           — load one version's full snapshot
DELETE /versions/{version_id}           — permanently delete one version
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

try:  # package import when mounted inside the toolbox (schema_map.*)
    from schema_map import db_engine, introspection_postgres, project_store
except ImportError:  # flat import when run standalone from within this folder
    import db_engine
    import introspection_postgres
    import project_store

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core.postgres_conn import ssh_tunnel_from_dict
except ImportError:  # standalone dev run from inside this folder: core/ is ../../core
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.postgres_conn import ssh_tunnel_from_dict

project_store.init_db()

app = FastAPI(
    title="Schema Map",
    description="Visual, progressive-disclosure table/relationship explorer for Postgres.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


class SSHTunnelRequest(BaseModel):
    ssh_host: str
    ssh_port: int = 22
    ssh_username: str
    ssh_password: Optional[str] = None
    ssh_private_key: Optional[str] = None


class ConnectRequest(BaseModel):
    host: str
    port: int = 5432
    database: str
    username: str
    password: str
    ssh_tunnel: Optional[SSHTunnelRequest] = None


class CreateProjectRequest(BaseModel):
    name: str
    origin: str  # "database" | "scratch" | "paste"


class SaveVersionRequest(BaseModel):
    snapshot: dict[str, Any]
    label: Optional[str] = None


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))


@app.post("/connect")
async def connect(body: ConnectRequest):
    tunnel_cfg = ssh_tunnel_from_dict(body.ssh_tunnel.model_dump() if body.ssh_tunnel else None)
    try:
        return await db_engine.connect(
            body.host, body.port, body.database, body.username, body.password,
            ssh_tunnel=tunnel_cfg,
        )
    except db_engine.ConnectError as exc:
        return _error(str(exc))


@app.post("/disconnect")
async def disconnect():
    return db_engine.disconnect()


@app.get("/status")
async def status():
    return db_engine.status()


@app.get("/paste-query")
async def paste_query():
    """No connection needed at all — the three query texts themselves,
    for the paste-and-load Project origin (run each yourself wherever
    you do have DB access, paste each JSON result back). Separate
    queries, not one combined one, per the owner's explicit ask for a
    simpler staged flow over one query mixing several aggregates
    together. Columns is the one query the live-fetch path deliberately
    never runs in bulk (see COLUMNS_QUERY_SQL's own comment) — but a
    paste-imported project has no live connection to lazily fetch a
    table's columns from later on click, so bulk is the only option
    here, not a scale mistake."""
    return {
        "tables_sql": introspection_postgres.TABLES_QUERY_SQL,
        "foreign_keys_sql": introspection_postgres.FOREIGN_KEYS_QUERY_SQL,
        "columns_sql": introspection_postgres.COLUMNS_QUERY_SQL,
    }


@app.get("/schemas")
async def schemas():
    try:
        return {"schemas": await db_engine.run(introspection_postgres.get_schemas)}
    except db_engine.ConnectError as exc:
        return _error(str(exc))


@app.get("/graph")
async def graph(schema: Optional[str] = None):
    # schema=None (the query param omitted) means "all schemas" —
    # introspection_postgres.get_graph() already treats None that way.
    try:
        return await db_engine.run(introspection_postgres.get_graph, schema)
    except db_engine.ConnectError as exc:
        return _error(str(exc))


@app.get("/table/{schema}/{table}")
async def table_columns(schema: str, table: str):
    try:
        columns = await db_engine.run(introspection_postgres.get_table_columns, schema, table)
        return {"schema": schema, "table": table, "columns": columns}
    except db_engine.ConnectError as exc:
        return _error(str(exc))


@app.get("/columns")
async def all_columns():
    """See introspection_postgres.get_all_columns()'s own docstring for
    why this bulk-fetch exists at all despite the usual per-table-on-
    click rule — it's a "Save as Version" safety net, not a general
    Explore/Editor data source."""
    try:
        return {"columns": await db_engine.run(introspection_postgres.get_all_columns)}
    except db_engine.ConnectError as exc:
        return _error(str(exc))


# ---------------------------------------------------------------------
# Projects/Versions — SQLite-backed (project_store.py), independent of
# any live database connection. `asyncio.to_thread` here for the same
# reason db_engine.run() offloads Postgres work: this whole toolbox runs
# as a single process with --workers 1 (see ../CLAUDE.md's "stateful
# tools and --workers" section) — a blocking sqlite3 call on the event
# loop would stall every other request across every tool sharing this
# process, not just Schema Map's own.
# ---------------------------------------------------------------------
@app.post("/projects")
async def create_project(body: CreateProjectRequest):
    try:
        return await asyncio.to_thread(project_store.create_project, body.name, body.origin)
    except ValueError as exc:
        return _error(str(exc))


@app.get("/projects")
async def list_projects():
    return {"projects": await asyncio.to_thread(project_store.list_projects)}


@app.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = await asyncio.to_thread(project_store.get_project, project_id)
    if project is None:
        return _error("No such project.", status=404)
    return project


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    if await asyncio.to_thread(project_store.get_project, project_id) is None:
        return _error("No such project.", status=404)
    await asyncio.to_thread(project_store.delete_project, project_id)
    return {"deleted": True}


@app.post("/projects/{project_id}/versions")
async def save_version(project_id: str, body: SaveVersionRequest):
    try:
        return await asyncio.to_thread(project_store.save_version, project_id, body.snapshot, body.label)
    except ValueError as exc:
        return _error(str(exc), status=404)


@app.get("/projects/{project_id}/versions")
async def list_versions(project_id: str):
    if await asyncio.to_thread(project_store.get_project, project_id) is None:
        return _error("No such project.", status=404)
    return {"versions": await asyncio.to_thread(project_store.list_versions, project_id)}


@app.get("/versions/{version_id}")
async def load_version(version_id: str):
    snapshot = await asyncio.to_thread(project_store.load_version, version_id)
    if snapshot is None:
        return _error("No such version.", status=404)
    return snapshot


@app.delete("/versions/{version_id}")
async def delete_version(version_id: str):
    await asyncio.to_thread(project_store.delete_version, version_id)
    return {"deleted": True}

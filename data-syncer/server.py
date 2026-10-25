"""
data-syncer/server.py

Serves Data Syncer's page and API: copy or upsert whole tables from one
database to another in resumable, key-ranged chunks, with progress saved
after every chunk. The page never shows table data — only status, counts,
positions and a short log tail.

Connections are NEVER typed here: every source/target is a saved Vault
entry (kind "postgres_connection"), chosen from a list. A project stores
only the entry's id/name.

Endpoints
---------
GET    /                          — the single-page UI
GET    /connections               — Vault connections to pick from (id/name only)
POST   /discover                  — {conn_id} -> that database's tables with primary keys (short-lived connection)
GET    /projects                  — all projects + a per-status table summary
POST   /projects                  — create ({name, source_conn_id, target_conn_id, mode, tables, ...})
GET    /projects/{id}             — project settings + tables + run state + log tail
PUT    /projects/{id}             — edit settings/tables (409 while running; 409 if connections/mode change after progress)
DELETE /projects/{id}             — delete project + its saved progress (409 while running)
POST   /projects/{id}/preflight   — read-only checks of every table (moves no data)
POST   /projects/{id}/start       — start/resume the run
POST   /projects/{id}/stop        — graceful stop (position saved)
GET    /projects/{id}/status      — the poll endpoint: running?, table progress, log tail
POST   /projects/{id}/fix-sequences — raise auto-increment sequences of finished tables to their max id (raise-only)
POST   /projects/{id}/reset       — every table back to position zero
POST   /tables/{table_id}/reset   — one table back to position zero
POST   /tables/{table_id}/position — {key_values: [...] | null} move the resume point
POST   /tables/{table_id}/status  — {status: "skipped" | "pending" | "done"} manual override
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

try:  # package import when mounted inside the toolbox (data_syncer.*)
    from data_syncer import connections, engine, runner, state_store as store
    from data_syncer.sync_ops import get_ops
except ImportError:  # flat import when run standalone from within this folder
    import connections
    import engine
    import runner
    import state_store as store
    from sync_ops import get_ops

try:
    from core.postgres_conn import scrub_password
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.postgres_conn import scrub_password

store.init_db()
# Tables left 'running' by a run that died → 'interrupted'. Only projects with NO live job: since roadmap B4 runs
# happen in the worker container, so a web restart must not touch a sync that is still running there.
runner.recover_orphans()

app = FastAPI(title="Data Syncer", description="Resumable table copy/upsert between databases saved in the Vault.")
_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


# ---------------------------------------------------------------- models

class TableSpec(BaseModel):
    schema_: str = Field(alias="schema")
    table: str
    key_columns: list[str] = []
    target_schema: Optional[str] = None
    target_table: Optional[str] = None
    approx_rows: Optional[int] = None

    model_config = {"populate_by_name": True}


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_conn_id: str
    target_conn_id: str
    mode: str = "upsert"
    batch_size: int = Field(50_000, ge=100, le=5_000_000)
    truncate_target: bool = False
    stop_on_failure: bool = False
    fix_sequences: bool = True
    max_retries: int = Field(3, ge=0, le=20)
    log_size: int = Field(100, ge=10, le=2000)
    tables: list[TableSpec] = []


class DiscoverBody(BaseModel):
    conn_id: str


class PositionBody(BaseModel):
    key_values: Optional[list[str]] = None


class StatusBody(BaseModel):
    status: str


# ---------------------------------------------------------------- helpers

def _conn_name(conn_id: str) -> str:
    for c in connections.list_vault_connections():
        if c["id"] == conn_id:
            return c["name"]
    raise HTTPException(400, f"Vault connection '{conn_id}' not found — pick one from the list.")


def _require_project(project_id: str) -> dict[str, Any]:
    p = store.get_project(project_id)
    if p is None:
        raise HTTPException(404, "Project not found.")
    return p


def _require_idle(project_id: str) -> None:
    if runner.is_running(project_id):
        raise HTTPException(409, "The project is running — stop it first.")


def _validate_tables(mode: str, tables: list[TableSpec]) -> None:
    if mode not in store.MODES:
        raise HTTPException(400, f"mode must be one of {list(store.MODES)}")
    seen = set()
    for t in tables:
        ident = (t.schema_, t.table)
        if ident in seen:
            raise HTTPException(400, f"{t.schema_}.{t.table} is listed twice.")
        seen.add(ident)
        if mode == "upsert" and not t.key_columns:
            raise HTTPException(400, f"{t.schema_}.{t.table}: upsert mode needs a key (one or more columns).")


def _table_rows(tables: list[TableSpec]) -> list[dict[str, Any]]:
    return [
        {
            "source_schema": t.schema_, "source_table": t.table, "key_columns": t.key_columns,
            "target_schema": t.target_schema, "target_table": t.target_table, "approx_total": t.approx_rows,
        }
        for t in tables
    ]


def _describe(conn_id: str, conn_name: Optional[str]) -> str:
    try:
        return connections.describe(connections.resolve(conn_id, conn_name))
    except Exception as exc:  # noqa: BLE001 — a missing entry must not break the project page
        return f"(unavailable: {exc})"


def _has_progress(project_id: str) -> bool:
    return any(t["status"] != "pending" or t["rows_done"] or t["last_key"] for t in store.list_tables(project_id))


def _view_tables(project_id: str) -> list[dict[str, Any]]:
    out = []
    for t in store.list_tables(project_id):
        out.append({
            "id": t["id"], "source": f"{t['source_schema']}.{t['source_table']}",
            "target": f"{t['target_schema']}.{t['target_table']}",
            "key_columns": t["key_columns"], "status": t["status"], "rows_done": t["rows_done"],
            "approx_total": t["approx_total"], "last_key": t["last_key"], "error": t["error"],
            "started_at": t["started_at"], "finished_at": t["finished_at"],
        })
    return out


def _run_state(project_id: str) -> dict[str, Any]:
    v = runner.view(project_id)
    if not v.running:
        runner.heal(project_id)
    return {
        "running": v.running, "stopping": v.stopping, "queued": v.queued,
        "logs": v.logs, "summary": v.summary, "error": v.error,
        "started_at": v.started_at, "finished_at": v.finished_at,
    }


def _progress(tables: list[dict[str, Any]]) -> dict[str, Any]:
    done = sum(1 for t in tables if t["status"] in ("done", "skipped"))
    return {
        "tables_total": len(tables), "tables_done": done,
        "rows_done": sum(t["rows_done"] for t in tables),
        "failed": sum(1 for t in tables if t["status"] == "failed"),
    }


# ---------------------------------------------------------------- routes

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse("<h1>Data Syncer UI not built yet</h1>", status_code=503)
    return HTMLResponse(_UI_PATH.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/connections")
def list_connections() -> dict[str, Any]:
    return {"connections": [{"id": c["id"], "name": c["name"]} for c in connections.list_vault_connections()]}


@app.post("/discover")
def discover(body: DiscoverBody) -> dict[str, Any]:
    try:
        data = connections.resolve(body.conn_id)
        ops = get_ops(data.get("db_type"))
        with connections.Endpoint(data, read_only=True, label="source") as ep:
            tables = ops.list_tables(ep.conn)
    except (connections.ConnectionError_, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, scrub_password(str(exc))) from exc
    return {"connection": connections.describe(data), "tables": tables}


@app.get("/projects")
def list_projects() -> dict[str, Any]:
    items = []
    for p in store.list_projects():
        items.append({**p, "running": runner.is_running(p["id"])})
    return {"projects": items}


@app.post("/projects")
def create_project(body: ProjectBody) -> dict[str, Any]:
    if body.source_conn_id == body.target_conn_id:
        raise HTTPException(400, "Source and target are the same connection — that would copy a database onto itself.")
    _validate_tables(body.mode, body.tables)
    pid = store.create_project(
        name=body.name, source_conn_id=body.source_conn_id, source_conn_name=_conn_name(body.source_conn_id),
        target_conn_id=body.target_conn_id, target_conn_name=_conn_name(body.target_conn_id), mode=body.mode,
        batch_size=body.batch_size, truncate_target=body.truncate_target, stop_on_failure=body.stop_on_failure, fix_sequences=body.fix_sequences,
        max_retries=body.max_retries, log_size=body.log_size,
    )
    store.set_tables(pid, _table_rows(body.tables))
    return {"id": pid}


@app.get("/projects/{project_id}")
def get_project(project_id: str) -> dict[str, Any]:
    p = _require_project(project_id)
    run = _run_state(project_id)  # heals first (see status)
    tables = _view_tables(project_id)
    return {
        "project": p,
        "source": _describe(p["source_conn_id"], p["source_conn_name"]),
        "target": _describe(p["target_conn_id"], p["target_conn_name"]),
        "tables": tables, "progress": _progress(tables), "run": run,
        "has_progress": _has_progress(project_id),
    }


@app.put("/projects/{project_id}")
def update_project(project_id: str, body: ProjectBody) -> dict[str, Any]:
    p = _require_project(project_id)
    _require_idle(project_id)
    _validate_tables(body.mode, body.tables)
    if body.source_conn_id == body.target_conn_id:
        raise HTTPException(400, "Source and target are the same connection.")
    changed_identity = (
        body.source_conn_id != p["source_conn_id"] or body.target_conn_id != p["target_conn_id"] or body.mode != p["mode"]
    )
    if changed_identity and _has_progress(project_id):
        raise HTTPException(409, "Source, target and mode can't change once tables have progress — reset the project first.")
    store.update_project(
        project_id, name=body.name, source_conn_id=body.source_conn_id, source_conn_name=_conn_name(body.source_conn_id),
        target_conn_id=body.target_conn_id, target_conn_name=_conn_name(body.target_conn_id), mode=body.mode,
        batch_size=body.batch_size, truncate_target=body.truncate_target, stop_on_failure=body.stop_on_failure, fix_sequences=body.fix_sequences,
        max_retries=body.max_retries, log_size=body.log_size,
    )
    store.set_tables(project_id, _table_rows(body.tables))
    return {"ok": True}


@app.delete("/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, Any]:
    _require_project(project_id)
    _require_idle(project_id)
    store.delete_project(project_id)
    return {"ok": True}


@app.post("/projects/{project_id}/preflight")
def preflight(project_id: str) -> dict[str, Any]:
    _require_project(project_id)
    try:
        return engine.preflight_project(project_id)
    except (connections.ConnectionError_, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, scrub_password(str(exc))) from exc


@app.post("/projects/{project_id}/start")
def start(project_id: str) -> dict[str, Any]:
    p = _require_project(project_id)
    if not store.list_tables(project_id):
        raise HTTPException(400, "No tables selected.")
    try:
        runner.start(project_id)
    except runner.AlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "mode": p["mode"]}


@app.post("/projects/{project_id}/stop")
def stop(project_id: str) -> dict[str, Any]:
    _require_project(project_id)
    return {"stopping": runner.stop(project_id)}


@app.get("/projects/{project_id}/status")
def status(project_id: str) -> dict[str, Any]:
    _require_project(project_id)
    run = _run_state(project_id)  # first: it heals a dead run, so the tables below already say 'interrupted'
    tables = _view_tables(project_id)
    return {"tables": tables, "progress": _progress(tables), "run": run}


@app.post("/projects/{project_id}/fix-sequences")
def fix_sequences(project_id: str) -> dict[str, Any]:
    """Raise every auto-increment sequence of the finished tables' TARGET tables to the
    table's max id (never lowers one, never touches data). Synchronous: a handful of
    cheap queries per table."""
    _require_project(project_id)
    _require_idle(project_id)
    try:
        tables = engine.fix_sequences_project(project_id, lambda level, msg, table=None: None)
    except (connections.ConnectionError_, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, scrub_password(str(exc))) from exc
    return {"tables": tables, "advanced": sum(1 for t in tables for r in t["sequences"] if r["action"] == "advanced")}


@app.post("/projects/{project_id}/reset")
def reset_project(project_id: str) -> dict[str, Any]:
    _require_project(project_id)
    _require_idle(project_id)
    store.reset_project(project_id)
    return {"ok": True}


def _require_table_idle(table_id: str) -> dict[str, Any]:
    t = store.get_table(table_id)
    if t is None:
        raise HTTPException(404, "Table not found.")
    _require_idle(t["project_id"])
    return t


@app.post("/tables/{table_id}/reset")
def reset_table(table_id: str) -> dict[str, Any]:
    _require_table_idle(table_id)
    store.reset_table(table_id)
    return {"ok": True}


@app.post("/tables/{table_id}/position")
def set_position(table_id: str, body: PositionBody) -> dict[str, Any]:
    t = _require_table_idle(table_id)
    if body.key_values is not None and len(body.key_values) != len(t["key_columns"]):
        raise HTTPException(400, f"This table's key has {len(t['key_columns'])} column(s) ({', '.join(t['key_columns'])}); "
                                 f"got {len(body.key_values)} value(s).")
    store.set_position(table_id, body.key_values)
    return {"ok": True}


@app.post("/tables/{table_id}/status")
def set_status(table_id: str, body: StatusBody) -> dict[str, Any]:
    _require_table_idle(table_id)
    if body.status not in ("skipped", "pending", "done"):
        raise HTTPException(400, "status must be skipped, pending or done.")
    store.update_table(table_id, status=body.status, error=None)
    return {"ok": True}

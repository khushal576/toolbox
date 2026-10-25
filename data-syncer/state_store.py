"""
data-syncer/state_store.py

The syncer's durable memory: Projects and, per project, one row per table
holding exactly how far that table got. This is what makes a run
stoppable/restartable at any time — the engine writes the position after
EVERY chunk, and a fresh process just reads it back.

Storage (roadmap B6): Toolbox's own Postgres, schema `data_syncer`, through core/state/sqlstore.py — shared by
the web app and the worker (which runs the syncs) and by every node later. The old SQLite file
(/app/data/data-syncer/syncer.db on the `data_syncer_data` volume) is copied in once on first start and then
left as a backup; standalone (no TOOLBOX_DATABASE_URL) it is still the store. Deliberately NOT stored in the
target database: the syncer never writes anything to a target except the synced data itself.

Position model (per table):
  last_key  JSON list of the key values (as TEXT, see sync_ops.py) of the
            last chunk that was fully committed to the target; null = not
            started. "Resume" == "continue after last_key".
  inflight  JSON {lower, upper} of the chunk currently being written, set
            BEFORE the target write and cleared after the state advance. If
            it is still set when a table starts, the previous run died
            mid-chunk (copy mode then deletes that range before re-copying).
Status: pending | running | done | failed | interrupted | skipped | stopped
  'running' rows left behind by a process death are flipped to
  'interrupted' on startup (recover_interrupted).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from core.state.sqlstore import SqlStore
except ImportError:  # standalone without the repo root on the path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.state.sqlstore import SqlStore

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "data-syncer" / "syncer.db"

RUNNABLE = ("pending", "failed", "interrupted", "stopped")
MODES = ("upsert", "copy")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_conn_id TEXT NOT NULL, source_conn_name TEXT,
    target_conn_id TEXT NOT NULL, target_conn_name TEXT,
    mode TEXT NOT NULL,
    batch_size INTEGER NOT NULL,
    truncate_target INTEGER NOT NULL DEFAULT 0,
    stop_on_failure INTEGER NOT NULL DEFAULT 0,
    fix_sequences INTEGER NOT NULL DEFAULT 1,
    max_retries INTEGER NOT NULL DEFAULT 3,
    log_size INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_tables (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    source_schema TEXT NOT NULL, source_table TEXT NOT NULL,
    target_schema TEXT NOT NULL, target_table TEXT NOT NULL,
    key_columns TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    last_key TEXT, inflight TEXT,
    rows_done INTEGER NOT NULL DEFAULT 0,
    approx_total INTEGER,
    error TEXT,
    started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL,
    UNIQUE (project_id, source_schema, source_table)
);
CREATE INDEX IF NOT EXISTS idx_pt_project ON project_tables(project_id, ord);
"""

_PROJECT_FIELDS = {
    "name", "source_conn_id", "source_conn_name", "target_conn_id", "target_conn_name", "mode",
    "batch_size", "truncate_target", "stop_on_failure", "fix_sequences", "max_retries", "log_size",
}
_TABLE_FIELDS = {
    "ord", "target_schema", "target_table", "key_columns", "status", "last_key", "inflight",
    "rows_done", "approx_total", "error", "started_at", "finished_at",
}
_JSON_FIELDS = {"key_columns", "last_key", "inflight"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# add_columns: databases created before fix_sequences existed get it ON (the default)
STORE = SqlStore("data_syncer", sqlite_path=DB_PATH, ddl=_SCHEMA,
                 add_columns={"projects": {"fix_sequences": "INTEGER NOT NULL DEFAULT 1"}})
_connect = STORE.connect


def init_db() -> None:
    STORE.init()


def recover_interrupted() -> int:
    """Call once at process start: no run can be alive in a new process, so any
    table still marked 'running' was cut off by a crash/restart."""
    with _connect() as con:
        cur = con.execute(
            "UPDATE project_tables SET status = 'interrupted', updated_at = ? WHERE status = 'running'", (_now(),)
        )
        return cur.rowcount


def mark_running_interrupted(project_id: str) -> None:
    """Safety net for a run thread that ended without finishing its table."""
    with _connect() as con:
        con.execute(
            "UPDATE project_tables SET status = 'interrupted', updated_at = ? WHERE project_id = ? AND status = 'running'",
            (_now(), project_id),
        )


def _project(row: dict) -> dict[str, Any]:
    d = dict(row)
    for f in ("truncate_target", "stop_on_failure", "fix_sequences"):
        d[f] = bool(d[f])
    return d


def _table(row: dict) -> dict[str, Any]:
    d = dict(row)
    for f in _JSON_FIELDS:
        d[f] = json.loads(d[f]) if d[f] is not None else None
    if d["key_columns"] is None:
        d["key_columns"] = []
    return d


# ---------------------------------------------------------------- projects

def create_project(
    *, name: str, source_conn_id: str, source_conn_name: Optional[str], target_conn_id: str,
    target_conn_name: Optional[str], mode: str, batch_size: int = 50_000, truncate_target: bool = False,
    stop_on_failure: bool = False, max_retries: int = 3, log_size: int = 100, fix_sequences: bool = True,
) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    pid, now = uuid.uuid4().hex, _now()
    with _connect() as con:
        con.execute(
            "INSERT INTO projects (id, name, source_conn_id, source_conn_name, target_conn_id, target_conn_name, "
            "mode, batch_size, truncate_target, stop_on_failure, max_retries, log_size, fix_sequences, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, name, source_conn_id, source_conn_name, target_conn_id, target_conn_name, mode, batch_size,
             int(truncate_target), int(stop_on_failure), max_retries, log_size, int(fix_sequences), now, now),
        )
    return pid


def update_project(project_id: str, **fields: Any) -> None:
    bad = set(fields) - _PROJECT_FIELDS
    if bad:
        raise ValueError(f"unknown project field(s): {sorted(bad)}")
    if "mode" in fields and fields["mode"] not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    for f in ("truncate_target", "stop_on_failure", "fix_sequences"):
        if f in fields:
            fields[f] = int(bool(fields[f]))
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as con:
        con.execute(f"UPDATE projects SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), _now(), project_id))


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    with _connect() as con:
        row = con.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project(row) if row else None


def list_projects() -> list[dict[str, Any]]:
    """Each project plus a status-count summary of its tables."""
    with _connect() as con:
        projects = [_project(r) for r in con.execute("SELECT * FROM projects ORDER BY created_at DESC")]
        counts = con.execute(
            "SELECT project_id, status, COUNT(*) AS n, COALESCE(SUM(rows_done), 0) AS rows "
            "FROM project_tables GROUP BY project_id, status"
        ).fetchall()
    by_project: dict[str, dict[str, Any]] = {}
    for c in counts:
        s = by_project.setdefault(c["project_id"], {"tables": 0, "rows_done": 0, "by_status": {}})
        s["tables"] += c["n"]
        s["rows_done"] += c["rows"]
        s["by_status"][c["status"]] = c["n"]
    for p in projects:
        p["summary"] = by_project.get(p["id"], {"tables": 0, "rows_done": 0, "by_status": {}})
    return projects


def delete_project(project_id: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM projects WHERE id = ?", (project_id,))  # tables cascade


# ---------------------------------------------------------------- tables

def set_tables(project_id: str, tables: list[dict[str, Any]]) -> None:
    """Replace the project's table selection with *tables* (dicts with
    source_schema, source_table, key_columns, optional target_schema/
    target_table/approx_total). A table already present keeps its progress
    — UNLESS its key changed, since a position in the old key means nothing
    in the new one — and tables no longer listed are dropped."""
    now = _now()
    with _connect() as con:
        existing = {
            (r["source_schema"], r["source_table"]): r
            for r in con.execute("SELECT * FROM project_tables WHERE project_id = ?", (project_id,))
        }
        wanted = set()
        for i, t in enumerate(tables):
            ident = (t["source_schema"], t["source_table"])
            wanted.add(ident)
            keys = json.dumps(list(t.get("key_columns") or []))
            tschema = t.get("target_schema") or t["source_schema"]
            ttable = t.get("target_table") or t["source_table"]
            old = existing.get(ident)
            if old is None:
                con.execute(
                    "INSERT INTO project_tables (id, project_id, ord, source_schema, source_table, target_schema, "
                    "target_table, key_columns, approx_total, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, project_id, i, ident[0], ident[1], tschema, ttable, keys,
                     t.get("approx_total"), now),
                )
            else:
                reset = old["key_columns"] != keys
                con.execute(
                    "UPDATE project_tables SET ord = ?, target_schema = ?, target_table = ?, key_columns = ?, "
                    "updated_at = ? WHERE id = ?",
                    (i, tschema, ttable, keys, now, old["id"]),
                )
                if reset:
                    _reset_row(con, old["id"])
        for ident, old in existing.items():
            if ident not in wanted:
                con.execute("DELETE FROM project_tables WHERE id = ?", (old["id"],))


def list_tables(project_id: str) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM project_tables WHERE project_id = ? ORDER BY ord", (project_id,)).fetchall()
    return [_table(r) for r in rows]


def get_table(table_id: str) -> Optional[dict[str, Any]]:
    with _connect() as con:
        row = con.execute("SELECT * FROM project_tables WHERE id = ?", (table_id,)).fetchone()
    return _table(row) if row else None


def update_table(table_id: str, **fields: Any) -> None:
    bad = set(fields) - _TABLE_FIELDS
    if bad:
        raise ValueError(f"unknown table field(s): {sorted(bad)}")
    for f in _JSON_FIELDS & set(fields):
        fields[f] = json.dumps(fields[f]) if fields[f] is not None else None
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as con:
        con.execute(f"UPDATE project_tables SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), _now(), table_id))


def advance(table_id: str, *, last_key: Optional[list], rows_added: int) -> None:
    """The one write that makes progress durable: new position, rows counted,
    inflight cleared — in a single transaction."""
    with _connect() as con:
        con.execute(
            "UPDATE project_tables SET last_key = ?, rows_done = rows_done + ?, inflight = NULL, updated_at = ? "
            "WHERE id = ?",
            (json.dumps(last_key) if last_key is not None else None, rows_added, _now(), table_id),
        )


def _reset_row(con: Any, table_id: str) -> None:
    con.execute(
        "UPDATE project_tables SET status = 'pending', last_key = NULL, inflight = NULL, rows_done = 0, "
        "error = NULL, started_at = NULL, finished_at = NULL, updated_at = ? WHERE id = ?",
        (_now(), table_id),
    )


def reset_table(table_id: str) -> None:
    """Back to position zero. Does NOT touch the target — copy mode will
    refuse a non-empty target (or truncate it, if the project says so)."""
    with _connect() as con:
        _reset_row(con, table_id)


def reset_project(project_id: str) -> None:
    with _connect() as con:
        for r in con.execute("SELECT id FROM project_tables WHERE project_id = ?", (project_id,)).fetchall():
            _reset_row(con, r["id"])


def set_position(table_id: str, key_values: Optional[list[str]]) -> None:
    """Manually move a table's resume point ("this table is really at key X").
    Clears any inflight marker; the next Start continues after *key_values*."""
    with _connect() as con:
        con.execute(
            "UPDATE project_tables SET last_key = ?, inflight = NULL, status = CASE WHEN status IN "
            "('done','running') THEN 'pending' ELSE status END, error = NULL, finished_at = NULL, updated_at = ? "
            "WHERE id = ?",
            (json.dumps(key_values) if key_values is not None else None, _now(), table_id),
        )

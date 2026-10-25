"""
schema-copy/state_store.py

Projects (what to copy from where to where) and each project's LAST run
result. Since roadmap B6 in Toolbox's Postgres, schema `schema_copy` (core/state/sqlstore.py; the old SQLite
file /app/data/schema-copy/schemacopy.db is copied in once, then kept as a backup; standalone it is still the
store). Generated DDL scripts are files next to it
(`scripts/<project_id>.sql`), not rows: a script can be many MB. Since roadmap B5 a script's home is S3
storage (`SCRIPTS`, core/state/filecache.py) and `scripts/` is only a local cache, so the worker that generates
it and the web process that serves it don't need to share a disk.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "schema-copy"
DB_PATH = DATA_DIR / "schemacopy.db"
SCRIPTS_DIR = DATA_DIR / "scripts"

try:
    from core.state.filecache import FileCache
    from core.state.sqlstore import SqlStore
except ImportError:  # standalone without the repo root on the path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.state.filecache import FileCache
    from core.state.sqlstore import SqlStore

SCRIPTS = FileCache("schema-copy", SCRIPTS_DIR, budget_mb=int(os.environ.get("SCHEMA_COPY_CACHE_MB", "256")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_conn_id TEXT NOT NULL, source_conn_name TEXT,
    target_conn_id TEXT NOT NULL, target_conn_name TEXT,
    schemas TEXT,                          -- JSON list of schema names, NULL = every user schema
    keep_owner INTEGER NOT NULL DEFAULT 0, -- keep OWNER TO / GRANT (roles must exist on the target)
    copy_sequences INTEGER NOT NULL DEFAULT 0, -- also set each sequence to its current value
    last_run TEXT,                         -- JSON of the most recent run's result
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

_FIELDS = {
    "name", "source_conn_id", "source_conn_name", "target_conn_id", "target_conn_name", "schemas",
    "keep_owner", "copy_sequences",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


STORE = SqlStore("schema_copy", sqlite_path=DB_PATH, ddl=_SCHEMA)
_connect = STORE.connect


def init_db() -> None:
    STORE.init()
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def _project(row: dict) -> dict[str, Any]:
    d = dict(row)
    d["schemas"] = json.loads(d["schemas"]) if d["schemas"] else None
    d["last_run"] = json.loads(d["last_run"]) if d["last_run"] else None
    d["keep_owner"] = bool(d["keep_owner"])
    d["copy_sequences"] = bool(d["copy_sequences"])
    return d


def create_project(**f: Any) -> str:
    pid, now = uuid.uuid4().hex, _now()
    with _connect() as con:
        con.execute(
            "INSERT INTO projects (id, name, source_conn_id, source_conn_name, target_conn_id, target_conn_name, "
            "schemas, keep_owner, copy_sequences, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, f["name"], f["source_conn_id"], f.get("source_conn_name"), f["target_conn_id"],
             f.get("target_conn_name"), json.dumps(f["schemas"]) if f.get("schemas") else None,
             int(bool(f.get("keep_owner"))), int(bool(f.get("copy_sequences"))), now, now),
        )
    return pid


def update_project(project_id: str, **fields: Any) -> None:
    bad = set(fields) - _FIELDS
    if bad:
        raise ValueError(f"unknown field(s): {sorted(bad)}")
    if "schemas" in fields:
        fields["schemas"] = json.dumps(fields["schemas"]) if fields["schemas"] else None
    for k in ("keep_owner", "copy_sequences"):
        if k in fields:
            fields[k] = int(bool(fields[k]))
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as con:
        con.execute(f"UPDATE projects SET {sets}, updated_at = ? WHERE id = ?", (*fields.values(), _now(), project_id))


def set_last_run(project_id: str, result: dict[str, Any]) -> None:
    with _connect() as con:
        con.execute("UPDATE projects SET last_run = ? WHERE id = ?", (json.dumps(result), project_id))


def get_project(project_id: str) -> Optional[dict[str, Any]]:
    with _connect() as con:
        row = con.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project(row) if row else None


def list_projects() -> list[dict[str, Any]]:
    with _connect() as con:
        return [_project(r) for r in con.execute("SELECT * FROM projects ORDER BY created_at DESC")]


def delete_project(project_id: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    SCRIPTS.remove_all(project_id)


def script_path(project_id: str) -> Path:
    return SCRIPTS_DIR / f"{project_id}.sql"


def publish_script(project_id: str) -> None:
    """The local script is complete: store it (the worker writes it, any web process may serve it)."""
    SCRIPTS.publish(project_id, script_path(project_id))


def fetch_script(project_id: str) -> Optional[Path]:
    """Local path of the project's script (downloaded from storage if needed), or None if there is none."""
    return SCRIPTS.fetch(project_id, script_path(project_id).name)


def has_script(project_id: str) -> bool:
    return SCRIPTS.exists(project_id, script_path(project_id).name)

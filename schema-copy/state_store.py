"""
schema-copy/state_store.py

Projects (what to copy from where to where) and each project's LAST run
result. SQLite at /app/data/schema-copy/schemacopy.db on the
`schema_copy_data` Docker volume — same pattern as data-syncer/state_store.py
and schema-map/project_store.py. Generated DDL scripts are files next to it
(`scripts/<project_id>.sql`), not rows: a script can be many MB.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "schema-copy"
DB_PATH = DATA_DIR / "schemacopy.db"
SCRIPTS_DIR = DATA_DIR / "scripts"

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


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _connect() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(_SCHEMA)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def _project(row: sqlite3.Row) -> dict[str, Any]:
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
    script_path(project_id).unlink(missing_ok=True)


def script_path(project_id: str) -> Path:
    return SCRIPTS_DIR / f"{project_id}.sql"

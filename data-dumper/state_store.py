"""
data-dumper/state_store.py

The dump catalogue: one row per dump (taken here or uploaded), plus a history of
runs (dumps and restores). SQLite at /app/data/data-dumper/dumper.db and the dump
FILES themselves in /app/data/data-dumper/files/, both on the `data_dumper_data`
Docker volume — same pattern as the other stateful tools; without the volume a
rebuild would delete every dump.

A dump row also remembers HOW it was taken (source connection, format, scope,
owner option). That is deliberate groundwork for the planned scheduler: a cron job
is just "take a dump with these settings again" (see POST /dumps/{id}/again).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "data-dumper"
DB_PATH = DATA_DIR / "dumper.db"
FILES_DIR = DATA_DIR / "files"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dumps (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    origin TEXT NOT NULL,                 -- 'dump' (taken here) | 'upload'
    status TEXT NOT NULL,                 -- 'running' | 'ready' | 'failed'
    error TEXT,
    fmt TEXT NOT NULL,                    -- 'custom' | 'plain'
    scope TEXT NOT NULL DEFAULT 'all',    -- 'all' | 'schema' | 'data'
    keep_owner INTEGER NOT NULL DEFAULT 0,
    source_conn_id TEXT, source_conn_name TEXT, source_desc TEXT, source_db TEXT,
    server_version TEXT, client_version TEXT,
    file_name TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                   -- 'dump' | 'restore'
    dump_id TEXT NOT NULL,
    status TEXT NOT NULL,                 -- 'running' | 'ok' | 'failed' | 'cancelled'
    started_at TEXT NOT NULL, finished_at TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_dump ON runs(dump_id, started_at);
"""

_DUMP_FIELDS = {
    "label", "status", "error", "fmt", "scope", "keep_owner", "source_conn_id", "source_conn_name", "source_desc",
    "source_db", "server_version", "client_version", "file_name", "size_bytes", "finished_at",
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
    FILES_DIR.mkdir(parents=True, exist_ok=True)


def recover_interrupted() -> int:
    """A new process has no live run: dumps still 'running' were cut off (their half-written
    .part file is useless) and runs still 'running' never finished."""
    n = 0
    with _connect() as con:
        for r in con.execute("SELECT id FROM dumps WHERE status = 'running'").fetchall():
            for p in FILES_DIR.glob(f"{r['id']}.*"):
                if p.suffix == ".part" or p.name.endswith(".part"):
                    p.unlink(missing_ok=True)
            con.execute("UPDATE dumps SET status='failed', error='Interrupted by a restart', finished_at=? WHERE id=?", (_now(), r["id"]))
            n += 1
        con.execute("UPDATE runs SET status='failed', finished_at=? WHERE status='running'", (_now(),))
    return n


def _dump(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["keep_owner"] = bool(d["keep_owner"])
    return d


def create_dump(**f: Any) -> str:
    did = uuid.uuid4().hex
    with _connect() as con:
        con.execute(
            "INSERT INTO dumps (id, label, origin, status, fmt, scope, keep_owner, source_conn_id, source_conn_name, "
            "source_desc, source_db, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (did, f["label"], f.get("origin", "dump"), f.get("status", "running"), f["fmt"], f.get("scope", "all"),
             int(bool(f.get("keep_owner"))), f.get("source_conn_id"), f.get("source_conn_name"), f.get("source_desc"),
             f.get("source_db"), _now()),
        )
    return did


def update_dump(dump_id: str, **fields: Any) -> None:
    bad = set(fields) - _DUMP_FIELDS
    if bad:
        raise ValueError(f"unknown field(s): {sorted(bad)}")
    if "keep_owner" in fields:
        fields["keep_owner"] = int(bool(fields["keep_owner"]))
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as con:
        con.execute(f"UPDATE dumps SET {sets} WHERE id = ?", (*fields.values(), dump_id))


def get_dump(dump_id: str) -> Optional[dict[str, Any]]:
    with _connect() as con:
        row = con.execute("SELECT * FROM dumps WHERE id = ?", (dump_id,)).fetchone()
    return _dump(row) if row else None


def list_dumps() -> list[dict[str, Any]]:
    with _connect() as con:
        return [_dump(r) for r in con.execute("SELECT * FROM dumps ORDER BY created_at DESC")]


def delete_dump(dump_id: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM dumps WHERE id = ?", (dump_id,))
        con.execute("DELETE FROM runs WHERE dump_id = ?", (dump_id,))
    for p in FILES_DIR.glob(f"{dump_id}.*"):
        p.unlink(missing_ok=True)


def file_path(dump: dict[str, Any]) -> Optional[Path]:
    return FILES_DIR / dump["file_name"] if dump.get("file_name") else None


def part_path(dump_id: str, ext: str) -> Path:
    return FILES_DIR / f"{dump_id}.{ext}.part"


def final_path(dump_id: str, ext: str) -> Path:
    return FILES_DIR / f"{dump_id}.{ext}"


def toc_cache_path(dump_id: str) -> Path:
    return FILES_DIR / f"{dump_id}.toc.json"


def add_run(kind: str, dump_id: str) -> str:
    rid = uuid.uuid4().hex
    with _connect() as con:
        con.execute("INSERT INTO runs (id, kind, dump_id, status, started_at) VALUES (?,?,?,?,?)",
                    (rid, kind, dump_id, "running", _now()))
    return rid


def finish_run(run_id: str, status: str, result: dict[str, Any]) -> None:
    with _connect() as con:
        con.execute("UPDATE runs SET status = ?, finished_at = ?, result = ? WHERE id = ?",
                    (status, _now(), json.dumps(result), run_id))


def list_runs(dump_id: str, limit: int = 15) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM runs WHERE dump_id = ? ORDER BY started_at DESC LIMIT ?", (dump_id, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["result"] = json.loads(d["result"]) if d["result"] else None
        out.append(d)
    return out


def disk_usage() -> dict[str, int]:
    import shutil
    total = sum(p.stat().st_size for p in FILES_DIR.glob("*") if p.is_file())
    free = shutil.disk_usage(FILES_DIR).free
    return {"dumps_bytes": total, "free_bytes": free}

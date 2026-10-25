"""
data-dumper/state_store.py

The dump catalogue: one row per dump (taken here or uploaded), plus a history of
runs (dumps and restores). Since roadmap B6 in Toolbox's Postgres, schema `data_dumper`
(core/state/sqlstore.py); the old SQLite file /app/data/data-dumper/dumper.db is copied in once and kept as a
backup (standalone it is still the store).

A dump row also remembers HOW it was taken (source connection, format, scope,
owner option). That is deliberate groundwork for the planned scheduler: a cron job
is just "take a dump with these settings again" (see POST /dumps/{id}/again).

Since roadmap B5 a dump file's home is S3 storage (`FILES`, core/state/filecache.py): `files/` is a local cache
(trimmed to DATA_DUMPER_CACHE_MB, default 2048) — the worker that takes a dump and the web process that serves or
restores it don't need to share a disk. Without S3 configured it is the only copy, as before.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "data-dumper"
DB_PATH = DATA_DIR / "dumper.db"
FILES_DIR = DATA_DIR / "files"

try:
    from core.state.filecache import FileCache
    from core.state.sqlstore import SqlStore
except ImportError:  # standalone without the repo root on the path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.state.filecache import FileCache
    from core.state.sqlstore import SqlStore

FILES = FileCache("data-dumper", FILES_DIR, budget_mb=int(os.environ.get("DATA_DUMPER_CACHE_MB", "2048")))
ORPHAN_GRACE_SECONDS = 20  # a dump row is created just before its job is claimed; don't call that an orphan

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


STORE = SqlStore("data_dumper", sqlite_path=DB_PATH, ddl=_SCHEMA)
_connect = STORE.connect


def init_db() -> None:
    STORE.init()
    FILES_DIR.mkdir(parents=True, exist_ok=True)


def fail_orphans(is_live: Callable[[str], bool], only: Optional[str] = None) -> int:
    """Dumps/runs still 'running' whose job is NOT live were cut off (restart, worker killed): mark them failed.
    `is_live(dump_id)` asks the runner (with the queue runner a dump still running in the worker is left alone)."""
    n = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ORPHAN_GRACE_SECONDS)).isoformat()
    where, args = ("AND id = ?", (only,)) if only else ("", ())
    with _connect() as con:
        for r in con.execute(f"SELECT id, created_at FROM dumps WHERE status = 'running' {where}", args).fetchall():
            if r["created_at"] > cutoff or is_live(r["id"]):
                continue
            for p in FILES_DIR.glob(f"{r['id']}.*.part"):
                p.unlink(missing_ok=True)
            con.execute("UPDATE dumps SET status='failed', error='Interrupted (restart or worker stopped)', finished_at=? "
                        "WHERE id=?", (_now(), r["id"]))
            n += 1
        where = "AND dump_id = ?" if only else ""
        for r in con.execute(f"SELECT id, dump_id FROM runs WHERE status = 'running' {where}", args).fetchall():
            if not is_live(r["dump_id"]):
                con.execute("UPDATE runs SET status='failed', finished_at=? WHERE id=?", (_now(), r["id"]))
    return n


def _dump(row: dict) -> dict[str, Any]:
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
    FILES.remove_all(dump_id)


def file_path(dump: dict[str, Any]) -> Optional[Path]:
    """Where the local copy lives (may not exist in this process — use fetch_file to read it)."""
    return FILES_DIR / dump["file_name"] if dump.get("file_name") else None


def fetch_file(dump: dict[str, Any]) -> Optional[Path]:
    """Local path of the dump file, downloaded from storage first if needed; None if it exists nowhere."""
    return FILES.fetch(dump["id"], dump["file_name"]) if dump.get("file_name") else None


def publish_file(dump_id: str, path: Path) -> None:
    FILES.publish(dump_id, path)


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
    """dumps_bytes = all ready dumps (in storage); free_bytes = this machine's disk where dumps are written."""
    import shutil
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        total = con.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM dumps WHERE status = 'ready'").fetchone()[0]
    free = shutil.disk_usage(FILES_DIR).free
    return {"dumps_bytes": total, "free_bytes": free}

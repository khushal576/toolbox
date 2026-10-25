"""
ssh-sftp/state_store.py

History only — never credentials (those stay in the Vault). Since roadmap B6 the history is in Toolbox's
Postgres, schema `ssh_sftp` (core/state/sqlstore.py; the old SQLite file /app/data/ssh-sftp/sshsftp.db is copied
in once and kept as a backup; standalone it is still the store). STAGED UPLOADS live in S3 storage since roadmap B8
(`STAGE`, core/state/filecache.py, keys `ssh-sftp/<transfer id>/<id>.stage`); /app/data/ssh-sftp/stage/ is a local
cache, so the worker that sends a file and the web process that received it don't need to share a disk.

An upload is first received into the stage directory, then sent to the server from there. That is what
makes it stable: if the connection drops, or the server is briefly unreachable, the transfer retries
and RESUMES from the staged file — the browser is not involved again. A failed transfer keeps its
staged file so "Retry" costs nothing; it is deleted when the transfer succeeds (or is discarded), and
anything older than a week is removed at startup.

Commands are stored (text only, truncated) so past runs can be re-used. Their OUTPUT is not stored.
Do not put passwords inside a command line: it would be saved here and visible in the remote process list.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from core.state.filecache import FileCache
    from core.state.sqlstore import SqlStore
except ImportError:  # standalone without the repo root on the path
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.state.filecache import FileCache
    from core.state.sqlstore import SqlStore

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ssh-sftp"
DB_PATH = DATA_DIR / "sshsftp.db"
STAGE_DIR = DATA_DIR / "stage"
STAGE_MAX_AGE_DAYS = 7
ORPHAN_GRACE_SECONDS = 20  # a command row is created just before its job is claimed; don't call that an orphan
STAGE = FileCache("ssh-sftp", STAGE_DIR, budget_mb=int(os.environ.get("SSH_SFTP_STAGE_CACHE_MB", "2048")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transfers (
    id TEXT PRIMARY KEY, server_id TEXT NOT NULL, server_name TEXT,
    remote_dir TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
    overwrite INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,                  -- staged | running | done | failed | cancelled
    error TEXT, note TEXT, bytes_done INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS commands (
    id TEXT PRIMARY KEY, server_id TEXT NOT NULL, server_name TEXT, command TEXT NOT NULL,
    status TEXT NOT NULL,                  -- running | ok | failed | timeout | stopped
    exit_code INTEGER, started_at TEXT NOT NULL, finished_at TEXT, seconds REAL
);
"""
_TRANSFER_FIELDS = {"status", "error", "note", "bytes_done", "attempts", "finished_at", "overwrite"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


STORE = SqlStore("ssh_sftp", sqlite_path=DB_PATH, ddl=_SCHEMA)
_connect = STORE.connect


def init_db() -> None:
    STORE.init()
    STAGE_DIR.mkdir(parents=True, exist_ok=True)


def fail_orphans(is_live: Callable[[str], bool]) -> int:
    """Transfers/commands still 'running' whose job is NOT live were cut off (restart, worker killed): mark them
    failed. Transfers keep their staged file (Retry resumes). With the queue runner a job still running in the
    worker is left alone."""
    n = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ORPHAN_GRACE_SECONDS)).isoformat()
    with _connect() as con:
        for r in con.execute("SELECT id FROM transfers WHERE status = 'running'").fetchall():
            if not is_live(r["id"]):
                con.execute("UPDATE transfers SET status='failed', error='Interrupted (restart or worker stopped) — "
                            "press Retry to resume', finished_at=? WHERE id=?", (_now(), r["id"]))
                n += 1
        for r in con.execute("SELECT id, started_at FROM commands WHERE status = 'running'").fetchall():
            if r["started_at"] < cutoff and not is_live(r["id"]):
                con.execute("UPDATE commands SET status='failed', finished_at=? WHERE id=?", (_now(), r["id"]))
                n += 1
    return n


def sweep_stage() -> int:
    """Staged files of finished transfers, and anything older than a week, are removed (storage + local)."""
    with _connect() as con:
        keep = {r["id"] for r in con.execute(
            "SELECT id FROM transfers WHERE status IN ('staged','running','failed','cancelled')")}
    return STAGE.sweep(keep, STAGE_MAX_AGE_DAYS * 86400)


def stage_path(transfer_id: str) -> Path:
    """The LOCAL copy's path (may not exist in this process — use fetch_stage to read it)."""
    return STAGE_DIR / f"{transfer_id}.stage"


def publish_stage(transfer_id: str) -> None:
    STAGE.publish(transfer_id, stage_path(transfer_id))


def fetch_stage(transfer_id: str) -> Optional[Path]:
    return STAGE.fetch(transfer_id, stage_path(transfer_id).name)


def has_stage(transfer_id: str) -> bool:
    return STAGE.exists(transfer_id, stage_path(transfer_id).name)


def delete_stage(transfer_id: str) -> None:
    STAGE.remove_all(transfer_id)


def new_id() -> str:
    return uuid.uuid4().hex


def create_transfer(*, tid: str, server_id: str, server_name: str, remote_dir: str, name: str, size: int, sha256: str, overwrite: bool) -> None:
    with _connect() as con:
        con.execute(
            "INSERT INTO transfers (id, server_id, server_name, remote_dir, name, size, sha256, overwrite, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tid, server_id, server_name, remote_dir, name, size, sha256, int(overwrite), "staged", _now()),
        )


def update_transfer(tid: str, **fields: Any) -> None:
    bad = set(fields) - _TRANSFER_FIELDS
    if bad:
        raise ValueError(f"unknown field(s): {sorted(bad)}")
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as con:
        con.execute(f"UPDATE transfers SET {sets} WHERE id = ?", (*fields.values(), tid))


def get_transfer(tid: str) -> Optional[dict[str, Any]]:
    with _connect() as con:
        r = con.execute("SELECT * FROM transfers WHERE id = ?", (tid,)).fetchone()
    return dict(r) if r else None


def list_transfers(limit: int = 40) -> list[dict[str, Any]]:
    with _connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM transfers ORDER BY created_at DESC LIMIT ?", (limit,))]


def delete_transfer(tid: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM transfers WHERE id = ?", (tid,))
    delete_stage(tid)


def add_command(server_id: str, server_name: str, command: str) -> str:
    cid = new_id()
    with _connect() as con:
        con.execute("INSERT INTO commands (id, server_id, server_name, command, status, started_at) VALUES (?,?,?,?,?,?)",
                    (cid, server_id, server_name, command[:500], "running", _now()))
    return cid


def finish_command(cid: str, status: str, exit_code: Optional[int], seconds: float) -> None:
    with _connect() as con:
        con.execute("UPDATE commands SET status=?, exit_code=?, finished_at=?, seconds=? WHERE id=?", (status, exit_code, _now(), round(seconds, 1), cid))


def list_commands(limit: int = 30) -> list[dict[str, Any]]:
    with _connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM commands ORDER BY started_at DESC LIMIT ?", (limit,))]

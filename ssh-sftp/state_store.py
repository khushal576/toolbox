"""
ssh-sftp/state_store.py

History only — never credentials (those stay in the Vault). Since roadmap B6 the history is in Toolbox's
Postgres, schema `ssh_sftp` (core/state/sqlstore.py; the old SQLite file /app/data/ssh-sftp/sshsftp.db is copied
in once and kept as a backup; standalone it is still the store). STAGED UPLOADS stay in /app/data/ssh-sftp/stage/
on the `ssh_sftp_data` Docker volume (roadmap B8 moves them).

An upload is first received into the stage directory, then sent to the server from there. That is what
makes it stable: if the connection drops, or the server is briefly unreachable, the transfer retries
and RESUMES from the staged file — the browser is not involved again. A failed transfer keeps its
staged file so "Retry" costs nothing; it is deleted when the transfer succeeds (or is discarded), and
anything older than a week is removed at startup.

Commands are stored (text only, truncated) so past runs can be re-used. Their OUTPUT is not stored.
Do not put passwords inside a command line: it would be saved here and visible in the remote process list.
"""

from __future__ import annotations

import time
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

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "ssh-sftp"
DB_PATH = DATA_DIR / "sshsftp.db"
STAGE_DIR = DATA_DIR / "stage"
STAGE_MAX_AGE_DAYS = 7

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


def recover_interrupted() -> None:
    """A new process has no live run: anything 'running' was cut off. Transfers keep their staged file
    (Retry resumes); stale staged files of finished transfers are removed."""
    with _connect() as con:
        con.execute("UPDATE transfers SET status='failed', error='Interrupted by a restart — press Retry to resume', finished_at=? WHERE status='running'", (_now(),))
        con.execute("UPDATE commands SET status='failed', finished_at=? WHERE status='running'", (_now(),))
        keep = {r["id"] for r in con.execute("SELECT id FROM transfers WHERE status IN ('staged','running','failed','cancelled')")}
    cutoff = time.time() - STAGE_MAX_AGE_DAYS * 86400
    for p in STAGE_DIR.glob("*"):
        tid = p.name.split(".")[0]
        if p.is_file() and (tid not in keep or p.stat().st_mtime < cutoff):
            p.unlink(missing_ok=True)


def stage_path(transfer_id: str) -> Path:
    return STAGE_DIR / f"{transfer_id}.stage"


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
    stage_path(tid).unlink(missing_ok=True)


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

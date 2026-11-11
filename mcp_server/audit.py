"""
mcp_server/audit.py — the audit log (docs/architecture/ADR-MCP.md D9).

Every tool call — reads too — is one row in Toolbox's Postgres (schema `mcp_server`, table `calls`): when, which tool, which
connection and its environment, the (scrubbed) arguments, the outcome, row/byte counts and duration. NEVER result data and
never a secret: arguments pass through the redactor first. If the log cannot be written the call is REFUSED (fail closed):
an AI action nobody can trace must not happen.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from core.state.sqlstore import SqlStore

from .safety import REDACTOR

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "mcp_server"   # standalone SQLite only
KEEP_DAYS = 365

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    session TEXT NOT NULL,              -- one id per MCP connection (one AI session)
    client TEXT,                        -- clientInfo name/version if the client sent it
    tool TEXT NOT NULL,
    connection TEXT,                    -- Vault connection name, if any
    environment TEXT,                   -- prod | non-prod | unknown
    args TEXT,                          -- JSON, scrubbed
    outcome TEXT NOT NULL,              -- started | ok | error | refused
    detail TEXT,                        -- error / refusal text, scrubbed
    rows INTEGER,
    bytes INTEGER,
    truncated INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS calls_ts ON calls (ts);

-- roadmap K4 (control.py): the kill switch / PIN, and the owner's time-limited write grants
CREATE TABLE IF NOT EXISTS control (
    key TEXT PRIMARY KEY,               -- killed | killed_at | pin_hash | pin_fails | pin_locked_until
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS confirmations (   -- roadmap K6: single-use tokens that bind a write to the exact plan the AI was shown (ADR D7)
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    digest TEXT NOT NULL,               -- sha256 of the canonical plan (source table + version, steps, target, mode)
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS approvals (       -- roadmap H4: a write the AI asked for, shown to the owner as a card (approvals.py)
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    action TEXT NOT NULL,
    plan TEXT NOT NULL,                 -- JSON, scrubbed: what / where / rows / columns / source / environment
    digest TEXT NOT NULL,
    status TEXT NOT NULL,               -- pending | approved | rejected | used
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    grant_id TEXT                       -- the single-use grant the owner's click created
);
CREATE TABLE IF NOT EXISTS recipes (         -- roadmap H5: a pipeline that worked once, replayed by the owner with NO AI (recipes.py)
    name TEXT PRIMARY KEY,
    description TEXT,
    steps TEXT NOT NULL,                -- JSON list of {tool, args, expects?}
    created_at TEXT NOT NULL,
    last_run_at TEXT,
    last_status TEXT
);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL,          -- connection | ssh_server | workspace
    target TEXT NOT NULL,               -- the connection / server / workspace NAME
    actions TEXT NOT NULL,              -- JSON list, from control.ACTIONS (never delete / drop)
    row_limit INTEGER,
    note TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_via TEXT NOT NULL,          -- ui | cli
    environment TEXT,                   -- of the target when granted (prod needs explicit confirmation)
    revoked_at TEXT,
    revoked_reason TEXT
);
"""

ADD_COLUMNS = {"calls": {"grant_id": "TEXT"}}   # added in K4; tests build their own stores with the same definition
STORE = SqlStore("mcp_server", sqlite_path=DATA_DIR / "mcp_server.db", ddl=_SCHEMA, add_columns=ADD_COLUMNS)
_ready = False
_lock = threading.Lock()

SESSION_ID = uuid.uuid4().hex[:12]
CLIENT = {"name": ""}


class AuditUnavailable(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _connect():
    global _ready
    if not _ready:
        with _lock:
            if not _ready:
                STORE.init()
                _ready = True
    return STORE.connect()


def begin(tool: str, args: dict, connection: Optional[str] = None, environment: Optional[str] = None) -> str:
    """Write the 'started' row BEFORE doing anything. Raises AuditUnavailable (→ the call is refused) if it cannot."""
    call_id = uuid.uuid4().hex
    try:
        with _connect() as con:
            con.execute(
                "INSERT INTO calls (id, ts, session, client, tool, connection, environment, args, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'started')",
                (call_id, _now(), SESSION_ID, CLIENT["name"], tool, connection, environment,
                 json.dumps(REDACTOR.any(args), default=str)[:8000]))
    except Exception as exc:  # noqa: BLE001
        raise AuditUnavailable("the audit log is not available, so nothing was run") from exc
    return call_id


def end(call_id: str, *, outcome: str, detail: str = "", rows: Optional[int] = None, size: Optional[int] = None,
        truncated: bool = False, started: float = 0.0, connection: Optional[str] = None,
        environment: Optional[str] = None, grant_id: Optional[str] = None) -> None:
    try:
        with _connect() as con:
            con.execute(
                "UPDATE calls SET outcome = ?, detail = ?, rows = ?, bytes = ?, truncated = ?, duration_ms = ?, "
                "connection = COALESCE(?, connection), environment = COALESCE(?, environment), "
                "grant_id = COALESCE(?, grant_id) WHERE id = ?",
                (outcome, REDACTOR.message(detail)[:2000], rows, size, int(bool(truncated)),
                 int((time.monotonic() - started) * 1000) if started else None, connection, environment, grant_id, call_id))
    except Exception:  # noqa: BLE001 - the 'started' row already exists; never turn a finished call into a crash
        pass


def recent(limit: int = 50, *, tool: str = "", outcome: str = "", session: str = "") -> list[dict[str, Any]]:
    """Newest first. Optional filters; never returns result data (it is not stored)."""
    where, params = [], []
    for col, val in (("tool", tool), ("outcome", outcome), ("session", session)):
        if val:
            where.append(f"{col} = ?")
            params.append(val)
    sql = "SELECT * FROM calls" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY ts DESC LIMIT ?"
    with _connect() as con:
        rows = con.execute(sql, (*params, max(1, min(int(limit), 500)))).fetchall()
    return [dict(r) for r in rows]


def sweep() -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    try:
        with _connect() as con:
            con.execute("DELETE FROM calls WHERE ts < ?", (cutoff,))
    except Exception:  # noqa: BLE001
        pass

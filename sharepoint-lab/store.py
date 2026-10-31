"""
sharepoint-lab/store.py

The tool's durable memory (Postgres schema `sharepoint_lab` in the Toolbox, SQLite when run standalone):

  staged  edits waiting for approval — one row per SharePoint item being changed (op "update") or per new item (op
          "create"), holding {field: {old, new}}. Nothing here has touched SharePoint yet. UI edits and Python
          (`sp.stage`) edits land in the same rows, so the review screen shows both.
  audit   one line per field that WAS written (or refused/conflicted/failed) when someone approved a batch.

Connections and their secrets are NOT here — they live in the Vault (kind `sharepoint_connection`).
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

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sharepoint-lab" / "sharepoint.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS staged (
    id TEXT PRIMARY KEY,
    conn_id TEXT NOT NULL, site_id TEXT NOT NULL, list_id TEXT NOT NULL,
    op TEXT NOT NULL,
    item_id TEXT,
    changes TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'ui',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    conn_id TEXT NOT NULL, conn_name TEXT, site_id TEXT NOT NULL, list_id TEXT NOT NULL, list_name TEXT,
    op TEXT NOT NULL, item_id TEXT, field TEXT,
    old TEXT, new TEXT, stored TEXT,
    source TEXT, outcome TEXT NOT NULL, detail TEXT
);
"""

STORE = SqlStore("sharepoint_lab", sqlite_path=DB_PATH, ddl=_SCHEMA)
MAX_STAGED_PER_LIST = 5000


def init_db() -> None:
    STORE.init()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _row(r: Any) -> dict[str, Any]:
    return {"id": r["id"], "conn_id": r["conn_id"], "site_id": r["site_id"], "list_id": r["list_id"], "op": r["op"],
            "item_id": r["item_id"], "changes": json.loads(r["changes"]), "source": r["source"],
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def staged_rows(conn_id: str, site_id: str, list_id: str) -> list[dict[str, Any]]:
    with STORE.connect() as con:
        rows = con.execute("SELECT * FROM staged WHERE conn_id = ? AND site_id = ? AND list_id = ? ORDER BY created_at, id",
                           (conn_id, site_id, list_id)).fetchall()
    return [_row(r) for r in rows]


def staged_counts(conn_id: str) -> dict[tuple[str, str], int]:
    with STORE.connect() as con:
        rows = con.execute("SELECT site_id, list_id, COUNT(*) AS n FROM staged WHERE conn_id = ? GROUP BY site_id, list_id",
                           (conn_id,)).fetchall()
    return {(r["site_id"], r["list_id"]): int(r["n"]) for r in rows}


def get_row(row_id: str) -> Optional[dict[str, Any]]:
    with STORE.connect() as con:
        r = con.execute("SELECT * FROM staged WHERE id = ?", (row_id,)).fetchone()
    return _row(r) if r else None


def find_update_row(conn_id: str, site_id: str, list_id: str, item_id: str) -> Optional[dict[str, Any]]:
    with STORE.connect() as con:
        r = con.execute("SELECT * FROM staged WHERE conn_id = ? AND site_id = ? AND list_id = ? AND op = 'update' AND item_id = ?",
                        (conn_id, site_id, list_id, item_id)).fetchone()
    return _row(r) if r else None


def count_for_list(conn_id: str, site_id: str, list_id: str) -> int:
    with STORE.connect() as con:
        return int(con.execute("SELECT COUNT(*) AS n FROM staged WHERE conn_id = ? AND site_id = ? AND list_id = ?",
                               (conn_id, site_id, list_id)).fetchone()["n"])


def save_row(row: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace one staged row (`id` empty → a new one). A row with no changes is dropped instead."""
    now = _now()
    if not row["changes"]:
        if row.get("id"):
            delete_rows([row["id"]])
        return {**row, "changes": {}}
    with STORE.connect() as con:
        if row.get("id") and con.execute("SELECT 1 FROM staged WHERE id = ?", (row["id"],)).fetchone():
            con.execute("UPDATE staged SET changes = ?, updated_at = ? WHERE id = ?", (json.dumps(row["changes"]), now, row["id"]))
        else:
            row = {**row, "id": row.get("id") or uuid.uuid4().hex, "created_at": now, "updated_at": now}
            con.execute("INSERT INTO staged (id, conn_id, site_id, list_id, op, item_id, changes, source, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (row["id"], row["conn_id"], row["site_id"], row["list_id"], row["op"], row.get("item_id"),
                         json.dumps(row["changes"]), row.get("source", "ui"), now, now))
    return row


def delete_rows(ids: list[str]) -> None:
    """Remove STAGED rows (an edit that was never sent). This is not, and cannot become, a SharePoint delete."""
    if not ids:
        return
    with STORE.connect() as con:
        for i in ids:
            con.execute("DELETE FROM staged WHERE id = ?", (i,))


def discard_list(conn_id: str, site_id: str, list_id: str) -> int:
    with STORE.connect() as con:
        n = con.execute("DELETE FROM staged WHERE conn_id = ? AND site_id = ? AND list_id = ?", (conn_id, site_id, list_id)).rowcount
    return int(n or 0)


def write_audit(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    now = _now()
    with STORE.connect() as con:
        for e in entries:
            con.execute(
                "INSERT INTO audit (id, ts, conn_id, conn_name, site_id, list_id, list_name, op, item_id, field, old, new, stored, source, outcome, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, now, e["conn_id"], e.get("conn_name"), e["site_id"], e["list_id"], e.get("list_name"), e["op"],
                 e.get("item_id"), e.get("field"), _j(e.get("old")), _j(e.get("new")), _j(e.get("stored")), e.get("source"),
                 e["outcome"], (e.get("detail") or "")[:500]))


def _j(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v)


def read_audit(conn_id: str, list_id: Optional[str] = None, limit: int = 200) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM audit WHERE conn_id = ?", [conn_id]
    if list_id:
        sql, args = sql + " AND list_id = ?", args + [list_id]
    with STORE.connect() as con:
        rows = con.execute(sql + " ORDER BY ts DESC, id DESC LIMIT ?", (*args, max(1, min(limit, 1000)))).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("old", "new", "stored"):
            d[k] = json.loads(d[k]) if d.get(k) is not None else None
        out.append(d)
    return out

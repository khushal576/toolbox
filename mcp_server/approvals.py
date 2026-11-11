"""
mcp_server/approvals.py — plan cards: the owner approves ONE write with a click (roadmap H4, ADR-AI-HELPER D7).

Flow:  the AI asks to save something -> no live grant -> `ask_owner` stores a PENDING card (what / where / rows / environment) and the refusal
       tells the AI to wait for the owner  ->  the panel shows the card  ->  the owner clicks Approve (+ PIN) or Reject  ->  Approve creates a
       SHORT, SINGLE-ACTION grant (10 minutes, that one target + action, row limit = the plan's rows, via="card")  ->  the AI repeats its call
       and goes through the normal path (dry-run, confirm code, write, read-back)  ->  after the write the grant is spent (revoked).

What the AI can do here: only `ask_owner` (store a request — it grants nothing) and `spend` (end a card grant after use). `approve` / `reject` are
reachable only from the owner's AI Access endpoints, and approving needs the PIN (control.create_grant). A test scans tools.py for the owner-side names.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import audit, control

CARD_MINUTES = 10          # how long an approved card's grant lives
REQUEST_MINUTES = 30       # how long a card waits for the owner
MAX_PENDING = 10           # an AI cannot flood the panel
VIA = "card"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds")


def _row(r: Any) -> dict[str, Any]:
    d = dict(r)
    d["plan"] = json.loads(d["plan"])
    return d


def ask_owner(tool: str, target_kind: str, target: str, action: str, plan: dict, digest: str) -> Optional[dict[str, Any]]:
    """Called by a write tool right after control.require refused for lack of a grant. Stores (or finds) the pending card. Grants nothing.
    Returns the card, or None when nothing should be shown (AI access is stopped, or a grant exists after all)."""
    if control.is_killed() or control.active_grant(target_kind, target, action):
        return None
    now = _iso(_now())
    clean = json.loads(json.dumps(plan, default=str))   # names and numbers only
    with audit._connect() as con:
        old = con.execute("SELECT * FROM approvals WHERE digest = ? AND tool = ? AND status IN ('pending', 'rejected') AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
                          (digest, tool, now)).fetchone()
        if old is not None:
            return _row(old)
        n = con.execute("SELECT COUNT(*) AS n FROM approvals WHERE status = 'pending' AND expires_at > ?", (now,)).fetchone()["n"]
        if n >= MAX_PENDING:
            return None
        aid = uuid.uuid4().hex[:12]
        con.execute("INSERT INTO approvals (id, tool, target_kind, target, action, plan, digest, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (aid, tool, target_kind, target, action, json.dumps(clean), digest, now, _iso(_now() + timedelta(minutes=REQUEST_MINUTES))))
        row = con.execute("SELECT * FROM approvals WHERE id = ?", (aid,)).fetchone()
    return _row(row)


def list_cards(include_decided_minutes: int = 10) -> list[dict[str, Any]]:
    """Pending cards plus recently decided ones (so the panel can show the outcome). Owner side."""
    now = _now()
    with audit._connect() as con:
        rows = con.execute("SELECT * FROM approvals ORDER BY created_at DESC LIMIT 50").fetchall()
    out = []
    for r in rows:
        d = _row(r)
        if d["status"] == "pending":
            if d["expires_at"] > _iso(now):
                out.append(d)
        elif d.get("decided_at") and d["decided_at"] > _iso(now - timedelta(minutes=include_decided_minutes)):
            out.append(d)
    return out


def _get_pending(aid: str) -> dict[str, Any]:
    with audit._connect() as con:
        row = con.execute("SELECT * FROM approvals WHERE id = ?", (aid or "",)).fetchone()
    if row is None:
        raise control.ControlError("There is no such request.")
    d = _row(row)
    if d["status"] != "pending":
        raise control.ControlError(f"This request was already {d['status']}.")
    if d["expires_at"] <= _iso(_now()):
        raise control.ControlError("This request has expired. Ask the AI to try again.")
    return d


def approve(aid: str, pin: str, confirm_prod: bool = False) -> dict[str, Any]:
    """OWNER ONLY (needs the PIN). Creates the single-action grant for exactly what the card shows. A PROD / unlabelled target also needs confirm_prod (the owner's tick on the card)."""
    d = _get_pending(aid)
    rows = d["plan"].get("rows")
    g = control.create_grant(d["target_kind"], d["target"], [d["action"]], minutes=CARD_MINUTES, pin=pin, row_limit=int(rows) if isinstance(rows, int) and rows > 0 else None,
                             note=f"approved card {aid}", via=VIA, environment=d["plan"].get("environment") or "unknown", confirm_prod=bool(confirm_prod))
    with audit._connect() as con:
        cur = con.execute("UPDATE approvals SET status = 'approved', decided_at = ?, grant_id = ? WHERE id = ? AND status = 'pending'", (_iso(_now()), g["id"], aid))
        if not cur.rowcount:
            control.revoke(g["id"], "card was decided twice")
            raise control.ControlError("This request was just decided elsewhere.")
    return {"approval": aid, "grant": g}


def reject(aid: str) -> bool:
    """OWNER ONLY. No PIN needed (saying no is always safe)."""
    _get_pending(aid)
    with audit._connect() as con:
        cur = con.execute("UPDATE approvals SET status = 'rejected', decided_at = ? WHERE id = ? AND status = 'pending'", (_iso(_now()), aid))
        return bool(cur.rowcount)


def spend(grant: dict[str, Any]) -> bool:
    """After a write: a grant that came from a card is single-use, so end it now. Other grants are untouched."""
    if (grant or {}).get("created_via") != VIA:
        return False
    with audit._connect() as con:
        con.execute("UPDATE approvals SET status = 'used' WHERE grant_id = ? AND status = 'approved'", (grant["id"],))
    return control.revoke(grant["id"], "single-use approval spent")

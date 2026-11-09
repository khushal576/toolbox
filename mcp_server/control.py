"""
mcp_server/control.py — who may do what, and the brakes (docs/architecture/ADR-MCP.md D12, roadmap K4).

  * KILL SWITCH   — one flag in the database, checked before EVERY tool call. Set = every call is refused (reads too) and every
                    grant is revoked. Anyone can stop; resuming needs the PIN. Fails closed: if the flag cannot be read, nothing runs.
  * PIN           — a secret only the owner knows (scrypt hash in the database). Creating a grant and resuming after a stop need it,
                    so an AI client that also has a shell (it could call the CLI or the web endpoints) still cannot give itself
                    permission. 5 wrong tries lock it for 15 minutes. Stopping and revoking never need it.
  * GRANTS        — "this connection / server / workspace may do THESE actions until THIS time". Created only through the owner's
                    channels (the AI Access page, the CLI) — there is NO MCP tool that creates, widens or extends one (a test scans for it).
                    There is no delete / drop / truncate action in the vocabulary, ever.

Write tools (SSH commands, saving tables …) call `require(...)`; without a live grant they are refused with a hint for the owner.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import audit
from .safety import ToolError, is_protected

# The ONLY actions a grant can contain. Deliberately no delete / drop / truncate / grant-style action (a test asserts it).
ACTIONS: dict[str, dict[str, str]] = {
    "workspace": {
        "create_table": "Create a NEW Vault Data table",
        "append_rows": "Add rows to an existing table",
        "replace_table": "Replace a table (the old data is kept as a backup table)",
    },
    "connection": {
        "insert_rows": "Insert rows into this database",
        "update_rows": "Update rows in this database",
    },
    "ssh_server": {
        "run_read_commands": "Run read-only diagnostic commands (ls, cat, tail, grep, ps, df, journalctl, docker logs …) — every command is logged",
        # run_write_commands is NOT built (it needs the dry-run + confirm-token flow of ADR D7) and is refused outright.
    },
}
TARGET_KINDS = tuple(ACTIONS)
MAX_MINUTES = 480            # 8 hours
DEFAULT_MINUTES = 30
PIN_MIN_LENGTH = 6
PIN_MAX_FAILS = 5
PIN_LOCK_MINUTES = 15


class ControlError(ValueError):
    """A message for the owner (wrong PIN, bad input …)."""


class ControlUnavailable(RuntimeError):
    """The control tables cannot be read — callers must fail closed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _parse(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


# ---- key/value control table -------------------------------------------------------------------------------------------

def _get(key: str, default: str = "") -> str:
    with audit._connect() as con:
        row = con.execute("SELECT value FROM control WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _set(con: Any, key: str, value: str) -> None:
    con.execute("INSERT INTO control (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value, _iso(_now())))


# ---- the kill switch -----------------------------------------------------------------------------------------------------

def is_killed() -> bool:
    """True when the owner stopped AI access. Raises ControlUnavailable if the flag cannot be read (callers fail closed)."""
    try:
        return _get("killed", "0") == "1"
    except Exception as exc:  # noqa: BLE001
        raise ControlUnavailable("the control flag cannot be read, so nothing was run") from exc


def kill(reason: str = "stopped by the owner") -> int:
    """Stop all AI access NOW: set the flag and revoke every grant. No PIN needed — anyone may hit the brakes. Returns grants revoked."""
    now = _iso(_now())
    with audit._connect() as con:
        _set(con, "killed", "1")
        _set(con, "killed_at", now)
        cur = con.execute("UPDATE grants SET revoked_at = ?, revoked_reason = ? WHERE revoked_at IS NULL AND expires_at > ?",
                          (now, reason[:200], now))
        return cur.rowcount or 0


def resume(pin: str) -> None:
    """Allow AI access again (read-only; grants must be created again). Needs the PIN."""
    verify_pin(pin)
    with audit._connect() as con:
        _set(con, "killed", "0")


# ---- the PIN ---------------------------------------------------------------------------------------------------------------

def _scrypt(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def pin_is_set() -> bool:
    return bool(_get("pin_hash"))


def set_pin(new: str, old: Optional[str] = None) -> None:
    """First time: no old PIN. Afterwards the old PIN is required (so a shell-capable AI cannot replace it)."""
    if not isinstance(new, str) or len(new) < PIN_MIN_LENGTH or len(set(new)) < 3:
        raise ControlError(f"Choose a PIN of at least {PIN_MIN_LENGTH} characters that is not just one or two repeated characters.")
    if pin_is_set():
        verify_pin(old or "")
    salt = secrets.token_bytes(16)
    with audit._connect() as con:
        _set(con, "pin_hash", f"scrypt${salt.hex()}${_scrypt(new, salt).hex()}")
        _set(con, "pin_fails", "0")
        _set(con, "pin_locked_until", "")


def verify_pin(pin: str) -> None:
    """Raises ControlError unless *pin* is right. Counts failures and locks after PIN_MAX_FAILS for PIN_LOCK_MINUTES."""
    stored = _get("pin_hash")
    if not stored:
        raise ControlError("No PIN is set yet. Set one first (it protects write access for the AI).")
    locked = _parse(_get("pin_locked_until") or None)
    if locked and locked > _now():
        mins = int((locked - _now()).total_seconds() // 60) + 1
        raise ControlError(f"Too many wrong PINs. Try again in about {mins} minute(s).")
    try:
        _, salt_hex, hash_hex = stored.split("$")
        ok = hmac.compare_digest(_scrypt(pin or "", bytes.fromhex(salt_hex)), bytes.fromhex(hash_hex))
    except ValueError:
        ok = False
    with audit._connect() as con:
        if ok:
            _set(con, "pin_fails", "0")
            _set(con, "pin_locked_until", "")
            return
        fails = int(_get("pin_fails", "0") or 0) + 1
        if fails >= PIN_MAX_FAILS:
            _set(con, "pin_fails", "0")
            _set(con, "pin_locked_until", _iso(_now() + timedelta(minutes=PIN_LOCK_MINUTES)))
            msg = f"Wrong PIN. Locked for {PIN_LOCK_MINUTES} minutes."
        else:
            _set(con, "pin_fails", str(fails))
            msg = f"Wrong PIN ({PIN_MAX_FAILS - fails} tries left)."
    raise ControlError(msg)


# ---- grants ----------------------------------------------------------------------------------------------------------------

def create_grant(target_kind: str, target: str, actions: list[str], *, minutes: int = DEFAULT_MINUTES, pin: str,
                 row_limit: Optional[int] = None, note: str = "", via: str = "ui", environment: Optional[str] = None,
                 confirm_prod: bool = False) -> dict[str, Any]:
    """Owner-only. Needs the PIN. Refused while AI access is stopped. Prod / unlabelled targets need confirm_prod=True."""
    if target_kind not in TARGET_KINDS:
        raise ControlError(f"target_kind must be one of {', '.join(TARGET_KINDS)}.")
    target = (target or "").strip()
    if not target:
        raise ControlError("Choose what the grant is for (a connection, server or workspace name).")
    acts = sorted({a for a in (actions or [])})
    if not acts:
        raise ControlError("Choose at least one action.")
    bad = [a for a in acts if a not in ACTIONS[target_kind]]
    if bad:
        raise ControlError(f"'{', '.join(bad)}' is not an allowed action for a {target_kind}. Allowed: {', '.join(ACTIONS[target_kind])}.")
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise ControlError("minutes must be a whole number.") from None
    if not 1 <= minutes <= MAX_MINUTES:
        raise ControlError(f"A grant lasts between 1 and {MAX_MINUTES} minutes.")
    if row_limit is not None:
        try:
            row_limit = int(row_limit)
        except (TypeError, ValueError):
            raise ControlError("row_limit must be a whole number.") from None
        if not 1 <= row_limit <= 10_000_000:
            raise ControlError("row_limit must be between 1 and 10,000,000.")
    if target_kind in ("connection", "ssh_server") and is_protected(environment or "unknown") and not confirm_prod:
        raise ControlError(f"'{target}' is {'PROD' if environment == 'prod' else 'not labelled (treated as PROD)'}. "
                           "Confirm it explicitly (tick the box on the AI Access page, or pass --prod-ok on the command line), or label it non-prod in the Vault first.")
    if is_killed():
        raise ControlError("AI access is stopped. Resume it first.")
    verify_pin(pin)
    now = _now()
    gid = uuid.uuid4().hex[:12]
    with audit._connect() as con:
        con.execute("INSERT INTO grants (id, target_kind, target, actions, row_limit, note, created_at, expires_at, created_via, environment) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (gid, target_kind, target, json.dumps(acts), row_limit, (note or "")[:200], _iso(now),
                     _iso(now + timedelta(minutes=minutes)), via, environment))
    return get_grant(gid)


def _row_to_grant(r: Any) -> dict[str, Any]:
    d = dict(r)
    d["actions"] = json.loads(d["actions"])
    exp, rev = _parse(d["expires_at"]), d.get("revoked_at")
    left = (exp - _now()).total_seconds() if exp else 0
    d["seconds_left"] = max(0, int(left))
    d["active"] = (not rev) and left > 0
    return d


def get_grant(gid: str) -> dict[str, Any]:
    with audit._connect() as con:
        row = con.execute("SELECT * FROM grants WHERE id = ?", (gid,)).fetchone()
    if row is None:
        raise ControlError("No such grant.")
    return _row_to_grant(row)


def list_grants(active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
    with audit._connect() as con:
        rows = con.execute("SELECT * FROM grants ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
    out = [_row_to_grant(r) for r in rows]
    return [g for g in out if g["active"]] if active_only else out


def revoke(gid: str, reason: str = "revoked by the owner") -> bool:
    """Stop one grant now. No PIN needed."""
    with audit._connect() as con:
        cur = con.execute("UPDATE grants SET revoked_at = ?, revoked_reason = ? WHERE id = ? AND revoked_at IS NULL",
                          (_iso(_now()), reason[:200], gid))
        return bool(cur.rowcount)


def active_grant(target_kind: str, target: str, action: str) -> Optional[dict[str, Any]]:
    for g in list_grants(active_only=True, limit=500):
        if g["target_kind"] == target_kind and g["target"] == target and action in g["actions"]:
            return g
    return None


def require(target_kind: str, target: str, action: str, *, rows: Optional[int] = None) -> dict[str, Any]:
    """What every write-capable tool calls FIRST. Returns the grant that allows it, or raises a refusal with a hint for the owner."""
    if action not in ACTIONS.get(target_kind, {}):
        raise ToolError(f"'{action}' is not a known action for a {target_kind}.", refused=True)
    try:
        if is_killed():
            raise ToolError("AI access is stopped by the owner.", hint="The owner can resume it in Toolbox → AI Access (needs the PIN).", refused=True)
        g = active_grant(target_kind, target, action)
    except ControlUnavailable as exc:
        raise ToolError(str(exc), refused=True) from None
    if g is None:
        raise ToolError(f"Changes are off for {target_kind} '{target}' ({action}).",
                        hint=f"Reading is fine. To allow '{action}' for a limited time the owner opens Toolbox → AI Access and creates a grant "
                             f"(needs the owner's PIN). Ask the owner; you cannot grant this yourself.", refused=True)
    if rows is not None and g.get("row_limit") and rows > g["row_limit"]:
        raise ToolError(f"The grant allows at most {g['row_limit']:,} rows; this would touch {rows:,}.",
                        hint="Ask for fewer rows or a larger grant.", refused=True)
    return g


# ---- confirmation tokens (ADR D7): a dry-run issues one, the real call consumes it ---------------------------------------------

CONFIRM_MINUTES = 10


def issue_confirmation(tool: str, digest: str) -> dict[str, Any]:
    """Called by a write tool's DRY-RUN after it has shown the plan. The token only works for this tool + exactly this plan digest."""
    now = _now()
    token = secrets.token_hex(8)
    with audit._connect() as con:
        con.execute("INSERT INTO confirmations (id, tool, digest, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                    (token, tool, digest, _iso(now), _iso(now + timedelta(minutes=CONFIRM_MINUTES))))
    return {"confirm_code": token, "expires_in_minutes": CONFIRM_MINUTES}


def consume_confirmation(token: str, tool: str, digest: str) -> None:
    """Single use: marks the token used atomically. Raises ToolError (refused) if it is unknown, expired, used, for another tool, or the plan changed."""
    now = _iso(_now())
    with audit._connect() as con:
        row = con.execute("SELECT * FROM confirmations WHERE id = ?", (token or "",)).fetchone()
        if row is None or row["tool"] != tool:
            raise ToolError("That confirm_code is not valid.", hint="Run the same call WITHOUT confirm_code first (the dry-run shows the plan and gives you a token).", refused=True)
        if row["used_at"]:
            raise ToolError("That confirm_code was already used.", hint="Do the dry-run again to get a new one.", refused=True)
        if row["expires_at"] <= now:
            raise ToolError("That confirm_code has expired.", hint="Do the dry-run again to get a new one.", refused=True)
        if row["digest"] != digest:
            raise ToolError("The plan changed since the dry-run (different arguments, or the source table changed), so the token no longer applies.",
                            hint="Do the dry-run again and confirm the new plan.", refused=True)
        cur = con.execute("UPDATE confirmations SET used_at = ? WHERE id = ? AND used_at IS NULL", (now, token))
        if not cur.rowcount:
            raise ToolError("That confirm_code was already used.", refused=True)


def status() -> dict[str, Any]:
    """Safe to show to the AI and the owner alike: no PIN material."""
    killed = is_killed()
    return {"stopped": killed, "pin_set": pin_is_set(),
            "grants": [{"id": g["id"], "target_kind": g["target_kind"], "target": g["target"], "actions": g["actions"],
                        "seconds_left": g["seconds_left"], "row_limit": g["row_limit"]} for g in list_grants(True)]}

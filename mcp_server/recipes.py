"""
mcp_server/recipes.py — recipes: do it once with the AI, repeat it without (roadmap H5, ADR-AI-HELPER D8).

A recipe is a saved list of steps {tool, args}. The AI can SAVE one (`keep_recipe`, which only stores text); only the OWNER can RUN one (AI Access endpoint /recipes/{name}/run,
a button in the panel) — a run uses no AI and no tokens. A run goes through `protocol.call_tool`, i.e. the SAME safety path as the AI: kill switch, audit rows, grants, plan cards, dry-run +
confirm code, read-back. A write step without a grant stops the run ("waiting for approval"), the owner approves the card, and the run continues from that step.

Rules: only these tools may be in a recipe; a recipe never holds a confirm_code; a saving step must use mode "replace" (a re-run must not fail on "already exists" — the old table is kept
as a backup); the Vault Data tables a recipe READS are remembered with their version, and a run refuses to start when one changed (the owner can say "run anyway").
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from . import audit, control, frame
from .safety import ToolError

ALLOWED_TOOLS = ("run_query", "compare", "table_transform", "stage_query", "load_table", "generate_insert_script")
WRITE_TOOLS = ("table_transform", "stage_query", "load_table")
MAX_STEPS = 12
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def is_write(tool: str, args: dict) -> bool:
    return tool in ("stage_query", "load_table") or (tool == "table_transform" and bool(args.get("save_as")))


def _reads(tool: str, args: dict) -> list[str]:
    out = []
    if args.get("table"):
        out.append(str(args["table"]))
    for side in ("left", "right"):
        if isinstance(args.get(side), dict) and args[side].get("table"):
            out.append(str(args[side]["table"]))
    return out


def _table_version(ref: str) -> Optional[dict]:
    from core import lake as lake_store

    ws, name = frame.split_table(ref)
    try:
        t = lake_store.scoped("mcp-server").get_table(ws, name)
    except lake_store.NotFound:
        return None
    return {"version": t.get("version"), "rows": t.get("row_count")}


def _produced(tool: str, args: dict) -> Optional[str]:
    if tool in ("table_transform", "stage_query") and args.get("save_as"):
        ws, name = frame.split_table(args["save_as"])
        return f"{ws}.{name}"
    return None


def save(name: str, description: str, steps: Any) -> dict:
    """What the AI's keep_recipe calls. Stores text only; grants nothing."""
    name = (name or "").strip().lower()
    if not NAME_RE.match(name):
        raise ToolError("The recipe name must be 2-40 characters: lowercase letters, digits, '-' or '_' (for example daily-orders-load).")
    if not isinstance(steps, list) or not steps or len(steps) > MAX_STEPS:
        raise ToolError(f"A recipe needs 1-{MAX_STEPS} steps, each {{\"tool\": ..., \"args\": {{...}}}}.")
    made: set[str] = set()
    clean = []
    for i, st in enumerate(steps, 1):
        if not isinstance(st, dict) or st.get("tool") not in ALLOWED_TOOLS or not isinstance(st.get("args", {}), dict):
            raise ToolError(f"Step {i}: 'tool' must be one of {', '.join(ALLOWED_TOOLS)} and 'args' an object.")
        tool, args = st["tool"], dict(st.get("args") or {})
        if "confirm_code" in args:
            raise ToolError(f"Step {i}: a recipe never contains a confirm_code (every run asks the database for its own).")
        if is_write(tool, args) and tool != "load_table" and str(args.get("mode") or "create").lower() != "replace":
            raise ToolError(f"Step {i}: a saving step in a recipe must use \"mode\": \"replace\", so running it again works (the old table is kept as a backup).")
        step: dict = {"tool": tool, "args": args}
        exp = {}
        for ref in _reads(tool, args):
            ws, nm = frame.split_table(ref)
            if f"{ws}.{nm}" in made:
                continue                                   # produced by an earlier step of this recipe: always new, nothing to compare
            v = _table_version(ref)
            if v is None:
                raise ToolError(f"Step {i}: the table '{ref}' does not exist, so the recipe cannot remember its version.")
            exp[f"{ws}.{nm}"] = v
        if exp:
            step["expects"] = exp
        made_name = _produced(tool, args)
        if made_name:
            made.add(made_name)
        clean.append(step)
    now = _now()
    with audit._connect() as con:
        con.execute("DELETE FROM recipes WHERE name = ?", (name,))
        con.execute("INSERT INTO recipes (name, description, steps, created_at) VALUES (?, ?, ?, ?)", (name, (description or "")[:300], json.dumps(clean), now))
    return {"name": name, "steps": len(clean), "description": (description or "")[:300]}


def _row(r: Any) -> dict:
    d = dict(r)
    d["steps"] = json.loads(d["steps"])
    return d


def list_all() -> list[dict]:
    with audit._connect() as con:
        rows = con.execute("SELECT * FROM recipes ORDER BY name").fetchall()
    return [{"name": r["name"], "description": r["description"], "steps": [{"tool": s["tool"], "writes": is_write(s["tool"], s["args"]), "summary": _summary(s)} for s in json.loads(r["steps"])],
             "created_at": r["created_at"], "last_run_at": r["last_run_at"], "last_status": r["last_status"]} for r in rows]


def _summary(step: dict) -> str:
    a = step["args"]
    if step["tool"] == "run_query":
        return (a.get("sql") or "")[:80]
    if step["tool"] == "load_table":
        return f"{a.get('table')} → {a.get('target_table')} on {a.get('connection')}"
    if step["tool"] == "stage_query":
        return f"query → {a.get('save_as')}"
    return f"{a.get('table') or ''} → {a.get('save_as') or '(preview)'}"


def delete(name: str) -> bool:
    with audit._connect() as con:
        return bool(con.execute("DELETE FROM recipes WHERE name = ?", ((name or "").strip().lower(),)).rowcount)


def _brief(tool: str, data: Any) -> str:
    if not isinstance(data, dict):
        return "ok"
    if data.get("saved") and data.get("table"):
        return f"saved {data['table']} ({data.get('rows')} rows)"
    if data.get("saved") and data.get("inserted") is not None:
        return f"inserted {data['inserted']} rows into {data.get('target')}"
    if data.get("returned") is not None:
        return f"{data['returned']} rows"
    return "ok"


def run(name: str, *, from_step: int = 0, accept_changes: bool = False) -> dict:
    """OWNER ONLY (no AI, no tokens). Runs the steps through protocol.call_tool. Returns {status, steps[], …}."""
    from . import protocol

    name = (name or "").strip().lower()
    with audit._connect() as con:
        row = con.execute("SELECT * FROM recipes WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise control.ControlError(f"There is no recipe '{name}'.")
    rec = _row(row)
    steps = rec["steps"]
    from_step = max(0, int(from_step or 0))
    if from_step == 0 and not accept_changes:
        changed = []
        for i, st in enumerate(steps, 1):
            for ref, was in (st.get("expects") or {}).items():
                now = _table_version(ref)
                if now is None or now != was:
                    changed.append({"step": i, "table": ref, "was": was, "now": now})
        if changed:
            _status(name, "not started: source changed")
            return {"status": "source_changed", "changed": changed, "message": "A table this recipe reads has changed since it was saved. Nothing was run. "
                                                                              "Run anyway only if that is expected."}
    done: list[dict] = []
    for i in range(from_step, len(steps)):
        st = steps[i]
        tool, args = st["tool"], dict(st["args"])
        r = protocol.call_tool(tool, args)
        if r.get("ok") and is_write(tool, args) and (r.get("data") or {}).get("dry_run"):
            r = protocol.call_tool(tool, {**args, "confirm_code": r["data"]["confirm_code"]})
        if r.get("ok"):
            done.append({"step": i + 1, "tool": tool, "ok": True, "summary": _brief(tool, r.get("data"))})
            continue
        if r.get("refused") and is_write(tool, args) and "Changes are off" in str(r.get("error", "")):
            _status(name, f"waiting for approval at step {i + 1}")
            return {"status": "waiting_for_approval", "step": i + 1, "next_from_step": i, "steps": done,
                    "message": f"Step {i + 1} wants to write. An approval card is waiting in the panel — approve it (PIN), then press Continue."}
        done.append({"step": i + 1, "tool": tool, "ok": False, "summary": str(r.get("error") or "failed")[:300]})
        _status(name, f"failed at step {i + 1}")
        return {"status": "failed", "step": i + 1, "steps": done, "message": done[-1]["summary"]}
    _status(name, "done")
    return {"status": "done", "steps": done, "message": f"Recipe '{name}' finished ({len(done)} step(s))."}


def _status(name: str, status: str) -> None:
    with audit._connect() as con:
        con.execute("UPDATE recipes SET last_run_at = ?, last_status = ? WHERE name = ?", (_now(), status[:120], name))

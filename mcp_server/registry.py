"""
mcp_server/registry.py — the capability registry behind find_actions / describe_action / run_action (roadmap H3, ADR-AI-HELPER D6).

Why it exists: with 1,000 tools the AI must not be shown 1,000 tool descriptions. It SEARCHES instead — find_actions returns the best few
matches, describe_action gives the detail of the one it picked, run_action runs it. What it costs does not grow with the number of tools.

Two kinds of action, one list:
  * manifest actions  — a tool declares them in its manifest.yaml `ai:` section. Read-only GETs on the tool's own API, run through the
    gateway. A manifest can never declare a write: anything that changes data lives in this MCP server's code (grant, dry-run,
    confirm code, read-back — ADR-MCP D7).
  * "mcp" actions     — the MCP tools that already exist (vault_list, run_query, table_transform …), so the AI finds everything in one place.
    They run through the very same function as before, so every guard in them still applies.

run_action never decides WHAT is allowed by itself: the kill switch and the audit row come from protocol.call_tool; manifest actions are
checked against the manifest (inputs validated, path built only from the declared template, never another tool's address, no redirects,
no cookies, size-capped); mcp actions keep their own checks (control.require …).
"""

from __future__ import annotations

import difflib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from core_plugins import discover
from core_plugins.ai import AiInputError, build_request, validate_inputs

from .safety import Limits, ToolError

REPO = Path(__file__).resolve().parent.parent
VERBS = {"find_actions", "describe_action", "run_action"}      # never listed as actions themselves (no recursion)
CACHE_SECONDS = 30
DEFAULT_LIMIT, MAX_LIMIT = 5, 10
_STOP = {"the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "my", "me", "i", "it", "is", "with", "from", "this", "that", "do", "can", "you", "please"}


@dataclass
class Action:
    id: str
    tool: str                      # manifest name, or "mcp"
    name: str
    summary: str
    effect: str                    # "read" | "write (needs the owner's approval)"
    source: str                    # "manifest" | "mcp"
    tool_title: str = ""
    tool_about: str = ""
    method: str = "GET"
    path: str = ""
    inputs: dict[str, dict] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    returns: str = ""
    note: str = ""
    _tok: Optional[tuple] = field(default=None, repr=False, compare=False)   # word sets, computed once per index (searching 3,000 actions must stay instant)


# ---- building the list ---------------------------------------------------------------------------------------------------------------

def _first_sentence(text: str) -> str:
    text = " ".join((text or "").split())
    m = re.match(r"(.{20,220}?[.!?])(\s|$)", text)
    return m.group(1) if m else text[:200]


def _mcp_actions() -> list[Action]:
    from .tools import REGISTRY  # late import: tools.py imports this module

    out = []
    for t in REGISTRY.values():
        if t.name in VERBS:
            continue
        ro = (t.annotations or {"readOnlyHint": True}).get("readOnlyHint", True)
        gated = t.name in ("ssh_run",)
        out.append(Action(id=f"mcp.{t.name}", tool="mcp", name=t.name, summary=_first_sentence(t.description), effect="read" if ro else "write (needs the owner's approval)",
                          source="mcp", tool_title="Toolbox MCP tools", tool_about="Vault Data, database queries, compare, scripts, SSH, DataFrame Studio steps",
                          inputs=dict(t.schema.get("properties", {})), required=list(t.schema.get("required", [])),
                          note="needs an owner permission for that server (see access_status)" if gated else ""))
    return out


def _manifest_actions(repo: Path) -> list[Action]:
    out = []
    for m in discover(repo).ordered():
        if m.ai is None:
            continue
        for a in m.ai.actions:
            out.append(Action(id=f"{m.name}.{a.name}", tool=m.name, name=a.name, summary=a.summary, effect="read", source="manifest", tool_title=m.title,
                              tool_about=m.description[:160], method=a.method, path=a.path,
                              inputs={k: v.model_dump(exclude_none=True) for k, v in a.inputs.items()}, required=list(a.required), returns=a.returns))
    return out


_cache: dict[str, Any] = {"at": 0.0, "repo": None, "actions": []}


def invalidate() -> None:
    _cache["at"] = 0.0


def load(repo: Optional[Path] = None) -> list[Action]:
    repo = Path(repo or REPO)
    if _cache["repo"] == str(repo) and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["actions"]
    actions = _manifest_actions(repo) + _mcp_actions()
    _cache.update(at=time.monotonic(), repo=str(repo), actions=actions)
    return actions


# ---- search --------------------------------------------------------------------------------------------------------------------------

def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP]


def _score(a: Action, q_words: list[str], q_norm: str) -> float:
    if not q_words:
        return 0.0
    if q_norm in (a.id.lower(), a.name.lower()):
        return 100.0
    if a._tok is None:
        a._tok = (set(_words(a.name.replace("_", " "))), set(_words(a.id.replace(".", " ").replace("_", " "))), set(_words(a.summary)),
                  set(_words(a.tool_title + " " + a.tool_about)), set(_words(" ".join(a.inputs) + " " + a.returns)))
    name_w, id_w, sum_w, tool_w, in_w = a._tok
    total = 0.0
    for q in q_words:
        for weight, pool in ((6, name_w), (4, id_w), (3, sum_w), (1.5, tool_w), (1, in_w)):
            if q in pool:
                total += weight
                break
            if len(q) >= 3 and any(w.startswith(q) or (len(w) >= 4 and q.startswith(w)) for w in pool):
                total += weight * 0.6
                break
    return total


def find(query: str, limit: int = DEFAULT_LIMIT, tool: str = "", repo: Optional[Path] = None) -> dict[str, Any]:
    q_words = _words(query)
    if not q_words:
        raise ToolError("Say what you want to do, in a few words (for example: \"flatten json\" or \"compare two tables\").")
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    actions = load(repo)
    pool = [a for a in actions if not tool or a.tool == tool]
    q_norm = (query or "").strip().lower()
    ranked = sorted(((s, a) for a in pool if (s := _score(a, q_words, q_norm)) > 0), key=lambda t: (-t[0], t[1].id))[:limit]
    tools_with = len({a.tool for a in actions})
    out: dict[str, Any] = {
        "matches": [{"id": a.id, "tool": a.tool, "summary": a.summary, "effect": a.effect,
                     "inputs": [f"{k}{'*' if k in a.required else ''}" for k in a.inputs]} for _, a in ranked],
        "searched": {"actions": len(actions), "tools": tools_with},
        "next": "describe_action(id) shows the inputs of one; run_action(id, inputs) runs it. An input marked * is required.",
    }
    if not ranked:
        out["hint"] = "Nothing matched. Try other words, or one of the tools listed by toolbox_guide."
    return out


# ---- describe ------------------------------------------------------------------------------------------------------------------------

def _get(action_id: str, repo: Optional[Path] = None) -> Action:
    action_id = (action_id or "").strip()
    actions = load(repo)
    for a in actions:
        if a.id == action_id:
            return a
    close = difflib.get_close_matches(action_id, [a.id for a in actions], n=5, cutoff=0.5)
    raise ToolError(f"There is no action '{action_id}'.", hint=("Did you mean: " + ", ".join(close) + "?") if close else "Use find_actions to search.")


def describe(action_id: str, repo: Optional[Path] = None) -> dict[str, Any]:
    a = _get(action_id, repo)
    if a.source == "manifest":
        how = f"GET /tools/{a.tool}/{a.path} through the Toolbox gateway (read only)"
        schema = {"type": "object", "properties": a.inputs, "required": a.required, "additionalProperties": False}
    else:
        from .tools import REGISTRY

        t = REGISTRY[a.name]
        how, schema = f"the Toolbox MCP tool '{a.name}' (same checks as calling it directly)", t.schema
    example_inputs = {k: (v.get("default") if isinstance(v, dict) and "default" in v else f"<{k}>") for k, v in a.inputs.items() if k in a.required}
    out = {"id": a.id, "tool": a.tool, "title": a.tool_title, "summary": a.summary, "effect": a.effect, "how_it_runs": how,
           "input_schema": schema, "returns": a.returns or "see the summary",
           "example": {"tool": "run_action", "arguments": {"id": a.id, "inputs": example_inputs}}}
    if a.source == "mcp":
        out["full_description"] = REGISTRY[a.name].description
    if a.note:
        out["note"] = a.note
    return out


# ---- run -----------------------------------------------------------------------------------------------------------------------------

def gateway_base() -> str:
    base = (os.environ.get("TOOLBOX_GATEWAY_URL") or "http://toolbox:8080").strip().rstrip("/")
    u = urlsplit(base)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ToolError("TOOLBOX_GATEWAY_URL is not a plain http(s) address.")
    return base


def http_get(url: str, params: dict[str, str], timeout: float, max_bytes: int) -> tuple[int, str, bytes]:
    """One GET: no redirects, no cookies kept, no environment proxies, body read only up to max_bytes+1. (Tests replace this function.)"""
    import httpx

    with httpx.Client(follow_redirects=False, trust_env=False, timeout=timeout, headers={"Accept": "application/json", "User-Agent": "toolbox-mcp-action"}) as c:
        with c.stream("GET", url, params=params) as r:
            body = bytearray()
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    break
            return r.status_code, r.headers.get("content-type", ""), bytes(body)


def run_manifest_action(a: Action, inputs: Any, repo: Optional[Path] = None) -> dict[str, Any]:
    from core_plugins.manifest import AiAction

    m = discover(Path(repo or REPO)).plugins.get(a.tool)
    spec: Optional[AiAction] = next((x for x in (m.ai.actions if m and m.ai else []) if x.name == a.name), None)
    if spec is None:
        raise ToolError(f"The action '{a.id}' is no longer declared by its tool.", hint="Use find_actions again.")
    try:
        clean = validate_inputs(spec, inputs)
        path, query = build_request(a.tool, spec, clean)
    except AiInputError as exc:
        raise ToolError(f"{a.id}: {exc}", hint="describe_action shows the inputs.") from None
    lim = Limits.for_environment("non-prod")
    seconds = float(os.environ.get("MCP_ACTION_SECONDS", "20"))
    base = gateway_base()
    try:
        status, ctype, body = http_get(base + path, query, seconds, lim.bytes)
    except Exception as exc:  # noqa: BLE001 - httpx errors, DNS, refused connection …
        raise ToolError(f"Could not reach Toolbox to run {a.id} ({type(exc).__name__}).", hint="Is the stack running? (docker compose ps)") from None
    if len(body) > lim.bytes:
        raise ToolError(f"The answer of {a.id} is larger than {lim.bytes:,} bytes.", hint="Use an input that narrows it, if the action has one.")
    if status == 404 and "html" in ctype.lower():
        raise ToolError(f"The tool '{a.tool}' is switched off.", hint="The owner can switch it on in Toolbox → Settings.")
    if status == 503:
        raise ToolError(f"The tool '{a.tool}' is starting or unavailable.", hint="Try again in a few seconds.")
    if status >= 300:
        snippet = body[:200].decode("utf-8", "replace").strip()
        raise ToolError(f"{a.id} answered HTTP {status}: {snippet}")
    if "json" in ctype.lower():
        try:
            result: Any = json.loads(body.decode("utf-8"))
        except ValueError:
            raise ToolError(f"{a.id} sent invalid JSON.") from None
    else:
        result = {"text": body.decode("utf-8", "replace")}
    return {"action": a.id, "status": status, "result": result}

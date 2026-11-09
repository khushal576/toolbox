"""
mcp_server/safety.py — the output side of the rules in docs/architecture/ADR-MCP.md (D4, D5, D6, D14).

Nothing leaves the MCP server except through `finish()`, which
  1. redacts: dict keys that look like secrets are replaced, and every secret VALUE the process decrypted during the call
     (passwords, keys, tokens, S3 secrets …) is replaced wherever it appears in any string — also inside driver error texts;
  2. makes values JSON-safe WITHOUT losing exactness (Decimal / big ints travel as text, never as a float);
  3. enforces the row / byte limits and says so (`truncated`), never silently dropping rows.

Keep this file small and boring: it is the thing the canary-secret tests (tests/unit/test_mcp_server.py) hammer on.
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

REDACTED = "[redacted]"

# Dict keys whose VALUE must never be returned, whatever the nesting. (Column names inside `columns` lists are values, not
# keys, so a user column called "password" is still listed — its cell values are data the owner asked to see.)
SECRET_KEY_RE = re.compile(
    r"(password|passwd|passphrase|secret|token|private[_-]?key|ciphertext|authorization|api[_-]?key|access[_-]?key|"
    r"credential|bearer|cookie)", re.I)

ENVIRONMENTS = ("prod", "non-prod")


def environment_of(data: Optional[dict]) -> str:
    """'prod' | 'non-prod' | 'unknown'. MUST match core.vault.environment_of (a unit test compares them).
    Unknown is treated like prod everywhere (ADR D5)."""
    v = str((data or {}).get("environment") or "").strip().lower()
    return v if v in ENVIRONMENTS else "unknown"


def is_protected(environment: str) -> bool:
    return environment != "non-prod"  # prod and unknown


# ---- limits ----------------------------------------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Limits:
    rows: int
    max_rows: int
    bytes: int
    seconds: int
    compare_rows: int
    script_rows: int

    @staticmethod
    def for_environment(environment: str = "non-prod") -> "Limits":
        protected = is_protected(environment)
        return Limits(
            rows=_env_int("MCP_PROD_ROWS", 100) if protected else _env_int("MCP_ROWS", 200),
            max_rows=_env_int("MCP_PROD_MAX_ROWS", 500) if protected else _env_int("MCP_MAX_ROWS", 5000),
            bytes=_env_int("MCP_MAX_BYTES", 1_000_000),
            seconds=_env_int("MCP_PROD_SECONDS", 15) if protected else _env_int("MCP_SECONDS", 30),
            compare_rows=_env_int("MCP_PROD_COMPARE_MAX_ROWS", 5_000) if protected else _env_int("MCP_COMPARE_MAX_ROWS", 50_000),
            script_rows=_env_int("MCP_PROD_SCRIPT_MAX_ROWS", 500) if protected else _env_int("MCP_SCRIPT_MAX_ROWS", 5_000),
        )

    def describe(self) -> dict:
        return {"default_rows": self.rows, "max_rows": self.max_rows, "max_response_bytes": self.bytes,
                "seconds": self.seconds, "compare_max_rows_per_side": self.compare_rows, "script_max_rows": self.script_rows}


class ToolError(Exception):
    """An error meant for the AI/user: plain sentence + optional hint. Never carries a secret (finish() scrubs it anyway)."""

    def __init__(self, message: str, hint: str = "", refused: bool = False):
        super().__init__(message)
        self.hint, self.refused = hint, refused
        self.connections: list = []  # set when the failure happened on a labelled connection (so the label is still shown)


# ---- redaction -------------------------------------------------------------------------------------------------------

class Redactor:
    """Collects the secret values seen in this process (from decrypted Vault entries) and scrubs them out of any output."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._identities: set[str] = set()  # usernames etc.: scrubbed from messages, NOT from result data (a table may hold "postgres")

    def learn(self, data: Any) -> None:
        """Register every string under a secret-looking key (recursively) — and, for multi-line values (private keys),
        each long line too, so a partial echo is caught as well."""
        def walk(node: Any, secret: bool) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, secret or bool(SECRET_KEY_RE.search(str(k))))
            elif isinstance(node, (list, tuple)):
                for v in node:
                    walk(v, secret)
            elif isinstance(node, str) and secret and node.strip():
                self._secrets.add(node)
                self._secrets.add(node.strip())
                for line in node.splitlines():
                    if len(line.strip()) >= 12:
                        self._secrets.add(line.strip())
            elif isinstance(node, (int, float)) and not isinstance(node, bool) and secret:
                self._secrets.add(str(node))
        walk(data, False)

    def learn_identity(self, *values: Any) -> None:
        for v in values:
            if isinstance(v, str) and len(v.strip()) >= 2:
                self._identities.add(v.strip())

    def message(self, s: str) -> str:
        """For error / hint / warning / log / audit text: secrets AND identities (usernames) are removed."""
        s = self.text(s)
        for ident in sorted(self._identities, key=len, reverse=True):
            s = re.sub(rf"(?<![\w]){re.escape(ident)}(?![\w])", REDACTED, s)
        return s

    def text(self, s: str) -> str:
        for sec in sorted(self._secrets, key=len, reverse=True):  # longest first: a key before the passphrase inside it
            if len(sec) >= 4:
                s = s.replace(sec, REDACTED)
            elif sec:
                s = re.sub(rf"(?<![\w]){re.escape(sec)}(?![\w])", REDACTED, s)
        return _scrub_conninfo(s)

    def any(self, node: Any) -> Any:
        if isinstance(node, dict):
            return {k: (REDACTED if SECRET_KEY_RE.search(str(k)) and v not in (None, "", False) else self.any(v))
                    for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [self.any(v) for v in node]
        if isinstance(node, str):
            return self.text(node)
        return node


_CONNINFO_PW = re.compile(r"(password\s*=\s*)('[^']*'|\S+)", re.I)
_URL_PW = re.compile(r"(\w+://[^:/\s@]+:)([^@/\s]+)(@)")


def _scrub_conninfo(s: str) -> str:
    """Backstop for texts a driver built itself (libpq conninfo, URLs with user:pass@)."""
    s = _CONNINFO_PW.sub(lambda m: m.group(1) + REDACTED, s)
    return _URL_PW.sub(lambda m: m.group(1) + REDACTED + m.group(3), s)


REDACTOR = Redactor()  # one per process: the MCP server handles one request at a time


# ---- JSON-safe values (exact) ----------------------------------------------------------------------------------------

def jsonable(v: Any) -> Any:
    """Exact, loss-free JSON form: Decimal / huge ints / UUID / datetimes become TEXT (the result's `types` say which),
    bytes become a short marker (we never ship raw binary), NaN/inf become text."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return v if abs(v) < 2**53 else str(v)
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else str(v)
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        return f"<{len(b)} bytes: {base64.b16encode(b[:16]).decode().lower()}{'…' if len(b) > 16 else ''}>"
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    return str(v)


def clip_rows(columns: list, rows: list[list], *, max_rows: int, max_bytes: int) -> tuple[list[list], bool, Optional[str]]:
    """Apply the row and byte caps. Returns (rows, truncated, why)."""
    why = None
    truncated = False
    if len(rows) > max_rows:
        rows, truncated, why = rows[:max_rows], True, f"row limit {max_rows}"
    out = [[jsonable(c) for c in r] for r in rows]
    size = len(json.dumps(out, default=str))
    if size > max_bytes and out:
        # drop rows from the end until it fits (bisect on count — rows can differ in width)
        lo, hi = 0, len(out)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if len(json.dumps(out[:mid], default=str)) <= max_bytes:
                lo = mid
            else:
                hi = mid - 1
        out, truncated, why = out[:lo], True, f"response size limit {max_bytes} bytes"
    return out, truncated, why


# ---- the envelope every tool returns ---------------------------------------------------------------------------------

def finish(*, ok: bool, data: Any = None, error: str = "", hint: str = "", connections: Optional[list] = None,
           truncated: bool = False, limits_hit: Optional[str] = None, warnings: Iterable[str] = (),
           refused: bool = False) -> dict:
    """Build the one JSON envelope (ADR D3) and run it through the redactor. This is the only exit of the server."""
    env: dict[str, Any] = {"ok": ok}
    if ok:
        env["data"] = data
    else:
        env["error"] = error
        env["refused"] = bool(refused)
    if hint:
        env["hint"] = hint
    conns = [c for c in (connections or []) if c]
    if conns:
        env["connections"] = [{"name": c.get("name"), "environment": c.get("environment", "unknown")} for c in conns]
    env["truncated"] = bool(truncated)
    if limits_hit:
        env["limits_hit"] = limits_hit
    warn = list(warnings)
    for c in reversed(conns):
        if is_protected(c.get("environment", "unknown")):
            label = "PROD" if c.get("environment") == "prod" else "environment NOT SET (treated as PROD)"
            warn.insert(0, f"{c.get('name')}: {label} — tighter limits apply; nothing here writes to it.")
    if warn:
        env["warnings"] = warn
    out = REDACTOR.any(env)
    for key in ("error", "hint"):
        if isinstance(out.get(key), str):
            out[key] = REDACTOR.message(out[key])
    if "warnings" in out:
        out["warnings"] = [REDACTOR.message(w) if isinstance(w, str) else w for w in out["warnings"]]
    return out

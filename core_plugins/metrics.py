"""
Per-tool request counters and the recent-errors list (roadmap E2/E3) — part of the gateway.

`Metered` wraps a tool's mount: for every request it notes the status and the time to the first response byte
(so a long download isn't "slow"). Counts are added up in this process and flushed to Redis every FLUSH_EVERY s in
one pipeline — a request never waits for Redis.

    toolbox:m:<tool>:m:<epoch minute>   hash req / err / slow / ms   (kept 2 h — last hour + sparklines)
    toolbox:m:<tool>:h:<epoch hour>     same, per hour               (kept 26 h — last 24 h)
    toolbox:m:tools                     set of tools that had traffic
    toolbox:errors                      list of the last MAX_ERRORS 5xx answers {ts, tool, method, path, status, message}

err = HTTP 5xx (including the gateway's own 503 "unavailable" page); slow = first byte after SLOW_MS
(TOOLBOX_SLOW_MS, default 2000). Nothing else is stored; all keys expire by themselves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Any

logger = logging.getLogger("toolbox.metrics")

SLOW_MS = int(os.environ.get("TOOLBOX_SLOW_MS") or 2000)
FLUSH_EVERY = 5.0
MAX_ERRORS = 50
P = "toolbox:m:"
ERRORS_KEY = "toolbox:errors"

_lock = threading.Lock()
_pending: dict[tuple[str, int], dict[str, int]] = {}
_errors: list[dict[str, Any]] = []


def _redis():
    try:
        from core.state import config, sessions
    except ImportError:
        return None
    return sessions.client() if config.load().redis_url else None


def record(tool: str, status: int, ms: float, error: dict[str, Any] | None = None) -> None:
    minute = int(time.time() // 60)
    with _lock:
        c = _pending.setdefault((tool, minute), {"req": 0, "err": 0, "slow": 0, "ms": 0})
        c["req"] += 1
        c["ms"] += int(ms)
        if status >= 500:
            c["err"] += 1
        if ms > SLOW_MS:
            c["slow"] += 1
        if error is not None:
            _errors.append(error)


def flush() -> None:
    with _lock:
        pending, errors = dict(_pending), list(_errors)
        _pending.clear()
        _errors.clear()
    if not pending and not errors:
        return
    r = _redis()
    if r is None:
        return
    try:
        pipe = r.pipeline(transaction=False)
        for (tool, minute), c in pending.items():
            for key, ttl in ((f"{P}{tool}:m:{minute}", 7200), (f"{P}{tool}:h:{minute // 60}", 26 * 3600)):
                for field, n in c.items():
                    if n:
                        pipe.hincrby(key, field, n)
                pipe.expire(key, ttl)
            pipe.sadd(f"{P}tools", tool)
        pipe.expire(f"{P}tools", 26 * 3600)
        for e in errors:
            pipe.lpush(ERRORS_KEY, json.dumps(e))
        if errors:
            pipe.ltrim(ERRORS_KEY, 0, MAX_ERRORS - 1)
            pipe.expire(ERRORS_KEY, 7 * 86400)
        pipe.execute()
    except Exception:  # noqa: BLE001 - counters are cosmetic; never let them hurt
        logger.debug("metrics flush failed", exc_info=True)


async def run_flusher() -> None:
    while True:
        await asyncio.sleep(FLUSH_EVERY)
        await asyncio.to_thread(flush)


def _message(body: bytes, content_type: str) -> str:
    """A short human message out of an error body: JSON error/detail, or the text of an HTML page."""
    text = body[:4000].decode("utf-8", "replace")
    if "json" in content_type:
        try:
            j = json.loads(text)
            if isinstance(j, dict):
                return str(j.get("error") or j.get("detail") or j)[:300]
        except ValueError:
            pass
    if "html" in content_type:
        text = re.sub(r"<style.*?</style>|<script.*?</script>|<title>.*?</title>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:300]


class Metered:
    """ASGI wrapper that counts what passes through one tool's mount."""

    def __init__(self, app: Any, tool: str):
        self.app, self.tool = app, tool

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        seen = {"status": 0, "ms": None, "ctype": "", "body": b""}

        async def watch(msg):
            if msg["type"] == "http.response.start":
                seen["status"] = msg["status"]
                seen["ms"] = (time.perf_counter() - t0) * 1000
                seen["ctype"] = dict(msg.get("headers") or []).get(b"content-type", b"").decode("latin-1")
            elif msg["type"] == "http.response.body" and seen["status"] >= 500 and len(seen["body"]) < 4000:
                seen["body"] += msg.get("body", b"")
            await send(msg)

        try:
            await self.app(scope, receive, watch)
        except Exception as exc:  # noqa: BLE001 - count it, then let the server report it as usual
            seen["status"], seen["body"], seen["ctype"] = 500, f"{type(exc).__name__}: {exc}".encode(), "text/plain"
            raise
        finally:
            status = seen["status"] or 500
            err = None
            if status >= 500:
                err = {"ts": time.time(), "tool": self.tool, "method": scope.get("method"),
                       "path": (scope.get("raw_path") or scope.get("path", "").encode()).decode("latin-1")[:200],
                       "status": status, "message": _message(seen["body"], seen["ctype"])}
            record(self.tool, status, seen["ms"] if seen["ms"] is not None else (time.perf_counter() - t0) * 1000, err)


# ---- reading (Status page) ----------------------------------------------------------------------------------------

def read() -> dict[str, Any]:
    """Per tool: last hour + last 24 h totals and a 60-minute series. Unflushed counts of THIS process included."""
    r = _redis()
    out: dict[str, Any] = {"slow_ms": SLOW_MS, "tools": {}}
    if r is None:
        return out
    flush()
    tools = sorted(r.smembers(f"{P}tools") or [])
    now_m, now_h = int(time.time() // 60), int(time.time() // 3600)
    pipe = r.pipeline(transaction=False)
    for t in tools:
        for m in range(now_m - 59, now_m + 1):
            pipe.hgetall(f"{P}{t}:m:{m}")
        for h in range(now_h - 23, now_h + 1):
            pipe.hgetall(f"{P}{t}:h:{h}")
    res = pipe.execute() if tools else []
    per = 60 + 24
    for i, t in enumerate(tools):
        mins, hours = res[i * per:i * per + 60], res[i * per + 60:(i + 1) * per]

        def tot(rows):
            s = {k: sum(int(x.get(k, 0)) for x in rows) for k in ("req", "err", "slow", "ms")}
            s["avg_ms"] = round(s.pop("ms") / s["req"]) if s["req"] else None
            return s

        out["tools"][t] = {"hour": tot(mins), "day": tot(hours),
                           "series": [int(x.get("req", 0)) for x in mins],
                           "err_series": [int(x.get("err", 0)) for x in mins]}
    return out


def recent_errors(limit: int = MAX_ERRORS) -> list[dict[str, Any]]:
    r = _redis()
    if r is None:
        return []
    flush()
    return [json.loads(x) for x in r.lrange(ERRORS_KEY, 0, limit - 1)]

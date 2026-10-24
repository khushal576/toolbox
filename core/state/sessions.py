"""
Redis-backed sessions for tools that keep per-user state between requests (roadmap B1; used from B2/B3/B8).

    store = SessionStore("df-studio", ttl_seconds=4 * 3600)
    sid = store.new_id(); store.set(sid, {"steps": []}); store.get(sid)  # get() also refreshes the TTL

Values are JSON (small metadata only — big data such as DataFrames goes to object storage, see objects.py).
Keys: `toolbox:session:<namespace>:<id>`.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from typing import Any

from core.state.config import load, require

_NS_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_lock = threading.Lock()
_client = None


def client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                url = require(load().redis_url, "TOOLBOX_REDIS_URL")  # clear error before importing the driver
                import redis

                _client = redis.Redis.from_url(url, decode_responses=True,
                                               socket_timeout=5, socket_connect_timeout=5, health_check_interval=30)
    return _client


class SessionStore:
    def __init__(self, namespace: str, ttl_seconds: int = 3600):
        if not _NS_RE.match(namespace):
            raise ValueError(f"invalid session namespace {namespace!r}")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be >= 1")
        self.namespace, self.ttl = namespace, ttl_seconds

    def key(self, sid: str) -> str:
        if not sid or len(sid) > 128 or ":" in sid:
            raise ValueError("invalid session id")
        return f"toolbox:session:{self.namespace}:{sid}"

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(24)

    def get(self, sid: str) -> dict[str, Any] | None:
        k = self.key(sid)
        pipe = client().pipeline()
        pipe.get(k)
        pipe.expire(k, self.ttl)
        raw, _ = pipe.execute()
        return json.loads(raw) if raw else None

    def set(self, sid: str, data: dict[str, Any]) -> None:
        client().set(self.key(sid), json.dumps(data, separators=(",", ":")), ex=self.ttl)

    def update(self, sid: str, **fields: Any) -> dict[str, Any]:
        data = self.get(sid) or {}
        data.update(fields)
        self.set(sid, data)
        return data

    def delete(self, sid: str) -> None:
        client().delete(self.key(sid))


def health() -> dict:
    c = client()
    c.ping()
    info = c.info(section="server")
    mem = c.info(section="memory")
    pers = c.info(section="persistence")
    return {"version": info.get("redis_version"), "used_memory": mem.get("used_memory_human"),
            "aof_enabled": bool(pers.get("aof_enabled"))}


def close() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None

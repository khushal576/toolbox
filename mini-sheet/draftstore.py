"""
mini-sheet/draftstore.py

Where Mini Sheet keeps a browser's unsaved workbook between page loads (roadmap M2 — "it should not lose my work on reload").

One DRAFT per browser: the whole workbook as gzip-compressed JSON, keyed by the `mini_sheet_sid` cookie.

- StateBackend (normal, inside the Toolbox): a small record (rev, saved_at, size, sheets) in Redis via core.state.sessions with a
  sliding TTL, and the gzip bytes in S3 storage via core.state.objects (`mini-sheet/<sid>/draft.json.gz`). Any worker process sees the
  same draft — this tool stays stateless in memory, as the repo's "stateful tools" rule requires.
- MemoryBackend (standalone dev / unit tests): the same API in a dict with expiry. Chosen automatically when the state env vars
  are not set, with a warning.

`rev` counts successful writes. A tab sends the rev it last saw; if another tab has written since, the write is refused (409) so
two tabs of the same browser can't silently overwrite each other — the page then pauses autosave until the user decides.
(The check is get-then-set, not atomic: two writes in the same millisecond can both pass. That is acceptable for one person.)
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("toolbox.mini_sheet")

NAMESPACE = "mini-sheet"
TTL_SECONDS = int(os.environ.get("MINI_SHEET_DRAFT_TTL") or 7 * 86400)
SWEEP_EVERY_SECONDS = 600
SID_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


class RevConflict(Exception):
    """Another tab wrote a newer draft since this tab last read/wrote it."""

    def __init__(self, current: int):
        super().__init__("the draft was changed from another tab")
        self.current = current


def valid_sid(sid: Optional[str]) -> bool:
    return bool(sid) and bool(SID_RE.match(sid))


class MemoryBackend:
    name = "memory"

    def __init__(self) -> None:
        self.items: dict[str, tuple[dict[str, Any], bytes, float]] = {}

    def _live(self, sid: str):
        it = self.items.get(sid)
        if it and it[2] < time.time():
            self.items.pop(sid, None)
            return None
        return it

    def get(self, sid: str) -> Optional[tuple[dict[str, Any], bytes]]:
        it = self._live(sid)
        if not it:
            return None
        self.items[sid] = (it[0], it[1], time.time() + TTL_SECONDS)       # sliding TTL
        return dict(it[0]), it[1]

    def meta(self, sid: str) -> Optional[dict[str, Any]]:
        it = self._live(sid)
        return dict(it[0]) if it else None

    def put(self, sid: str, gz: bytes, info: dict[str, Any], expect_rev: Optional[int]) -> dict[str, Any]:
        cur = self.meta(sid)
        cur_rev = int(cur["rev"]) if cur else 0
        if expect_rev is not None and cur and expect_rev != cur_rev:
            raise RevConflict(cur_rev)
        meta = {**info, "rev": cur_rev + 1, "size": len(gz)}
        self.items[sid] = (meta, gz, time.time() + TTL_SECONDS)
        return meta

    def delete(self, sid: str) -> None:
        self.items.pop(sid, None)

    def sweep(self) -> int:
        now = time.time()
        gone = [k for k, v in self.items.items() if v[2] < now]
        for k in gone:
            self.items.pop(k, None)
        return len(gone)


class StateBackend:
    name = "redis+s3"

    def __init__(self) -> None:
        from core.state import objects, sessions

        self._objects = objects
        self._redis = sessions.client
        self._store = sessions.SessionStore(NAMESPACE, ttl_seconds=TTL_SECONDS)
        self._last_sweep = 0.0

    def _key(self, sid: str) -> str:
        return self._objects.key(NAMESPACE, sid, "draft.json.gz")

    def get(self, sid: str) -> Optional[tuple[dict[str, Any], bytes]]:
        meta = self._store.get(sid)                                       # also slides the TTL
        if meta is None:
            return None
        data = self._objects.get_bytes(self._key(sid))
        if data is None:
            return None
        return meta, data

    def meta(self, sid: str) -> Optional[dict[str, Any]]:
        return self._store.get(sid)

    def put(self, sid: str, gz: bytes, info: dict[str, Any], expect_rev: Optional[int]) -> dict[str, Any]:
        cur = self._store.get(sid)
        cur_rev = int(cur["rev"]) if cur else 0
        if expect_rev is not None and cur and expect_rev != cur_rev:
            raise RevConflict(cur_rev)
        self._objects.put_bytes(self._key(sid), gz, "application/gzip")
        meta = {**info, "rev": cur_rev + 1, "size": len(gz)}
        self._store.set(sid, meta)
        return meta

    def delete(self, sid: str) -> None:
        self._store.delete(sid)
        self._objects.delete_prefix(f"{NAMESPACE}/{sid}/")

    def sweep(self) -> int:
        """Delete stored drafts whose Redis record expired. At most once per SWEEP_EVERY_SECONDS per process."""
        now = time.monotonic()
        if now - self._last_sweep < SWEEP_EVERY_SECONDS:
            return 0
        self._last_sweep = now
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=TTL_SECONDS)
        removed = 0
        seen: set[str] = set()
        for obj in self._objects.list_objects(f"{NAMESPACE}/"):
            parts = obj["key"].split("/")
            if len(parts) < 3 or parts[1] in seen:
                continue
            sid = parts[1]
            if obj["last_modified"] < cutoff and not self._redis().exists(self._store.key(sid)):   # exists(): must not slide the TTL
                seen.add(sid)
                removed += self._objects.delete_prefix(f"{NAMESPACE}/{sid}/")
        if removed:
            logger.info("mini-sheet sweep removed %d draft object(s) of expired sessions", removed)
        return removed


def make_backend():
    try:
        from core.state import config

        cfg = config.load()
        if cfg.redis_url and cfg.s3_endpoint:
            return StateBackend()
    except ImportError:
        pass
    logger.warning("mini-sheet: TOOLBOX_REDIS_URL / TOOLBOX_S3_ENDPOINT not set — keeping drafts in memory "
                   "(lost on restart, single process only)")
    return MemoryBackend()

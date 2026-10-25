"""
duck-lab/session_store.py

Where Duck Lab keeps a session between requests (roadmap B3). Two backends with the same interface:

- StateBackend (inside the Toolbox): metadata (table list, current result, version) in Redis via
  core.state.sessions with a sliding TTL; uploaded files and result Parquet files in S3 storage via
  core.state.objects under `duck-lab/<sid>/`. Any worker or node can rebuild a session from these.
- MemoryBackend (standalone dev / unit tests): metadata in a dict, files copied into a local folder outside the
  per-session cache (so evicting a working copy never loses data). Chosen when the state env vars are missing.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("toolbox.duck_lab")

NAMESPACE = "duck-lab"
TTL_SECONDS = int(os.environ.get("DUCK_LAB_SESSION_TTL") or 12 * 3600)
SWEEP_EVERY_SECONDS = 600


class MemoryBackend:
    name = "memory"

    def __init__(self, root: Path | None = None) -> None:
        self.meta: dict[str, dict[str, Any]] = {}
        self.root = root or Path(tempfile.gettempdir()) / "duck-lab-memory-store"

    def save_meta(self, sid: str, meta: dict[str, Any]) -> None:
        self.meta[sid] = meta

    def load_meta(self, sid: str) -> dict[str, Any] | None:
        return self.meta.get(sid)

    def put_file(self, sid: str, rel: str, path: Path) -> str:
        dest = self.root / sid / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        return str(dest)

    def get_file(self, key: str, dest: Path) -> bool:
        if not key or not Path(key).exists():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(key, dest)
        return True

    def delete_file(self, key: str) -> None:
        if key:
            Path(key).unlink(missing_ok=True)

    def delete(self, sid: str) -> None:
        self.meta.pop(sid, None)
        shutil.rmtree(self.root / sid, ignore_errors=True)

    def sweep(self) -> int:
        return 0


class StateBackend:
    name = "redis+s3"

    def __init__(self) -> None:
        from core.state import objects, sessions

        self._objects = objects
        self._redis = sessions.client
        self._store = sessions.SessionStore(NAMESPACE, ttl_seconds=TTL_SECONDS)
        self._last_sweep = 0.0

    def save_meta(self, sid: str, meta: dict[str, Any]) -> None:
        self._store.set(sid, meta)
        self._maybe_sweep()

    def load_meta(self, sid: str) -> dict[str, Any] | None:
        return self._store.get(sid)  # also slides the TTL

    def put_file(self, sid: str, rel: str, path: Path) -> str:
        key = self._objects.key(NAMESPACE, sid, *rel.split("/"))
        with path.open("rb") as fh:
            self._objects.put_file(key, fh)
        return key

    def get_file(self, key: str, dest: Path) -> bool:
        if not key:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as fh:
            found = self._objects.get_to(key, fh)
        if not found:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dest)  # never leave a half-downloaded file under the real name
        return True

    def delete_file(self, key: str) -> None:
        if key:
            self._objects.delete(key)

    def delete(self, sid: str) -> None:
        self._store.delete(sid)
        self._objects.delete_prefix(f"{NAMESPACE}/{sid}/")

    def _maybe_sweep(self) -> None:
        now = time.monotonic()
        if now - self._last_sweep < SWEEP_EVERY_SECONDS:
            return
        self._last_sweep = now
        try:
            self.sweep()
        except Exception:  # noqa: BLE001 - cleanup must never break a request
            logger.exception("duck-lab sweep failed")

    def sweep(self) -> int:
        """Delete stored files of sessions whose Redis key expired (files older than the TTL)."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=TTL_SECONDS)
        removed, done = 0, set()
        for obj in self._objects.list_objects(f"{NAMESPACE}/"):
            parts = obj["key"].split("/")
            if len(parts) < 3 or parts[1] in done:
                continue
            sid = parts[1]
            if obj["last_modified"] < cutoff and not self._redis().exists(self._store.key(sid)):
                done.add(sid)
                removed += self._objects.delete_prefix(f"{NAMESPACE}/{sid}/")
        if removed:
            logger.info("duck-lab sweep removed %d object(s) of expired sessions", removed)
        return removed


def make_backend():
    try:
        from core.state import config

        cfg = config.load()
        if cfg.redis_url and cfg.s3_endpoint:
            return StateBackend()
    except ImportError:
        pass
    logger.warning("duck-lab: TOOLBOX_REDIS_URL / TOOLBOX_S3_ENDPOINT not set — using in-memory sessions "
                   "(lost on restart, single process only)")
    return MemoryBackend()

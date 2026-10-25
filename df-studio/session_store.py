"""
df-studio/session_store.py

Where DataFrame Studio keeps a session between requests (roadmap B2).

- StateBackend (normal, inside the Toolbox): small metadata (filename, steps, preview mode, seed) in Redis via
  core.state.sessions with a sliding TTL; the ORIGINAL DataFrame in S3 storage via core.state.objects as Parquet
  (falls back to pickle for frames Parquet can't hold, e.g. int column names from header=False). Any worker
  process — or any node later — sees the same session.
- MemoryBackend (standalone dev / unit tests): the old in-process dicts. Chosen automatically when the state
  env vars are not set, with a warning, so `cd df-studio && uvicorn server:app` still works.

Pickle is only ever read back from Toolbox's own internal bucket (not reachable from outside the compose
network) and only from objects this module wrote.
"""

from __future__ import annotations

import io
import logging
import os
import pickle
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

logger = logging.getLogger("toolbox.df_studio")

NAMESPACE = "df-studio"
TTL_SECONDS = int(os.environ.get("DF_STUDIO_SESSION_TTL") or 12 * 3600)
SWEEP_EVERY_SECONDS = 600


def serialize_frame(df: pd.DataFrame) -> tuple[str, bytes]:
    """Parquet when the frame round-trips through it, else pickle. Returns (format, bytes)."""
    buf = io.BytesIO()
    try:
        df.to_parquet(buf, engine="pyarrow", index=True)
        return "parquet", buf.getvalue()
    except Exception as exc:  # noqa: BLE001 - pyarrow raises several types (ArrowTypeError, ValueError, ...)
        logger.info("DataFrame not Parquet-compatible (%s: %s) — storing as pickle", type(exc).__name__, exc)
        return "pickle", pickle.dumps(df, protocol=pickle.HIGHEST_PROTOCOL)


def deserialize_frame(fmt: str, data: bytes) -> pd.DataFrame:
    if fmt == "parquet":
        return pd.read_parquet(io.BytesIO(data), engine="pyarrow")
    if fmt == "pickle":
        return pickle.loads(data)  # noqa: S301 - our own objects from the internal bucket only (see module doc)
    raise ValueError(f"unknown frame format {fmt!r}")


class MemoryBackend:
    name = "memory"

    def __init__(self) -> None:
        self.meta: dict[str, dict[str, Any]] = {}
        self.frames: dict[str, pd.DataFrame] = {}

    def save_frame(self, sid: str, df: pd.DataFrame) -> str:
        self.frames[sid] = df
        return "memory"

    def load_frame(self, sid: str, fmt: str) -> pd.DataFrame | None:
        return self.frames.get(sid)

    def save_meta(self, sid: str, meta: dict[str, Any]) -> None:
        self.meta[sid] = dict(meta)

    def load_meta(self, sid: str) -> dict[str, Any] | None:
        m = self.meta.get(sid)
        return dict(m) if m is not None else None

    def delete(self, sid: str) -> None:
        self.meta.pop(sid, None)
        self.frames.pop(sid, None)

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

    def _key(self, sid: str, fmt: str) -> str:
        return self._objects.key(NAMESPACE, sid, "original." + ("parquet" if fmt == "parquet" else "pkl"))

    def save_frame(self, sid: str, df: pd.DataFrame) -> str:
        fmt, data = serialize_frame(df)
        self._objects.put_file(self._key(sid, fmt), io.BytesIO(data))
        return fmt

    def load_frame(self, sid: str, fmt: str) -> pd.DataFrame | None:
        buf = io.BytesIO()
        if not self._objects.get_to(self._key(sid, fmt), buf):
            return None
        return deserialize_frame(fmt, buf.getvalue())

    def save_meta(self, sid: str, meta: dict[str, Any]) -> None:
        self._store.set(sid, meta)

    def load_meta(self, sid: str) -> dict[str, Any] | None:
        return self._store.get(sid)  # also slides the TTL

    def delete(self, sid: str) -> None:
        self._store.delete(sid)
        self._objects.delete_prefix(f"{NAMESPACE}/{sid}/")

    def sweep(self) -> int:
        """Delete stored frames whose session expired in Redis. At most once per SWEEP_EVERY_SECONDS."""
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
            # exists(), not get(): checking must not slide the session's TTL
            if obj["last_modified"] < cutoff and not self._redis().exists(self._store.key(sid)):
                seen.add(sid)
                removed += self._objects.delete_prefix(f"{NAMESPACE}/{sid}/")
        if removed:
            logger.info("df-studio sweep removed %d object(s) of expired sessions", removed)
        return removed


def make_backend():
    try:
        from core.state import config

        cfg = config.load()
        if cfg.redis_url and cfg.s3_endpoint:
            return StateBackend()
    except ImportError:
        pass
    logger.warning("df-studio: TOOLBOX_REDIS_URL / TOOLBOX_S3_ENDPOINT not set — using in-memory sessions "
                   "(lost on restart, single process only)")
    return MemoryBackend()

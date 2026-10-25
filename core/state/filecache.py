"""
core.state.filecache — S3 storage as the home of a tool's files, a local folder as a per-process cache (roadmap B5).

Tools whose engines work on local paths (pg_dump writes a file, psql reads one) keep doing so; around that:

    files = FileCache("data-dumper", FILES_DIR, budget_mb=2048)
    files.publish(owner_id, path)          # after a file is created: upload it (the local copy stays as cache)
    path = files.fetch(owner_id, name)     # before a file is used: the local copy, downloaded first if missing
    files.exists(owner_id, name)           # here or in storage
    files.remove_all(owner_id)             # on delete: storage AND the local copies

Keys: `<tool>/<owner_id>/<name>`; local copies keep their plain name in `local_dir` (`<name>` must start with the
owner id, which is how the tools name their files already). Without S3 configured (standalone dev, unit tests)
every call works on the local folder alone — the pre-B5 behavior.

The cache is trimmed to `budget_mb` (oldest-used first), and only files that are safely in storage are ever
evicted, so a file that exists nowhere else is never removed by the trim; neither is one used in the last 15 min.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)
RECENT_SECONDS = 15 * 60  # a file used this recently may be about to be opened again (pg_restore after its preflight)


class FileCache:
    def __init__(self, tool: str, local_dir: Path, budget_mb: int = 2048):
        self.tool, self.local_dir, self.budget = tool, Path(local_dir), max(0, budget_mb) * 1024 * 1024
        self._lock = threading.Lock()
        self._objects = None
        try:
            from core.state import config

            cfg = config.load()
            if cfg.s3_endpoint:
                from core.state import objects

                self._objects = objects
        except ImportError:
            pass

    @property
    def remote(self) -> bool:
        return self._objects is not None

    def _key(self, owner_id: str, name: str) -> str:
        return self._objects.key(self.tool, owner_id, name)

    def local(self, name: str) -> Path:
        return self.local_dir / name

    # ---- write side --------------------------------------------------------------------------------------
    def publish(self, owner_id: str, path: Path) -> None:
        """Upload a finished local file. Raises if storage fails (the caller decides whether that's fatal)."""
        if self._objects is None:
            return
        with path.open("rb") as fh:
            self._objects.put_file(self._key(owner_id, path.name), fh)
        self.trim(keep=path.name)

    def remove(self, owner_id: str, name: str) -> None:
        self.local(name).unlink(missing_ok=True)
        if self._objects is not None:
            self._objects.delete(self._key(owner_id, name))

    def remove_all(self, owner_id: str) -> None:
        for p in self.local_dir.glob(f"{owner_id}.*"):
            p.unlink(missing_ok=True)
        if self._objects is not None:
            self._objects.delete_prefix(f"{self.tool}/{owner_id}/")

    # ---- read side ---------------------------------------------------------------------------------------
    def exists(self, owner_id: str, name: str) -> bool:
        if self.local(name).exists():
            return True
        return self._objects is not None and self._objects.exists(self._key(owner_id, name))

    def fetch(self, owner_id: str, name: str) -> Path | None:
        """Local path of the file, downloading it from storage first if this process has no copy. A local file
        that was never uploaded (made before B5, or by a failed upload) is uploaded now, so it gets a home."""
        dest = self.local(name)
        if dest.exists():
            try:
                os.utime(dest)  # mark as recently used for the trim
            except OSError:
                pass
            if self._objects is not None and not self._objects.exists(self._key(owner_id, name)):
                try:
                    self.publish(owner_id, dest)
                except Exception:  # noqa: BLE001 - still usable locally; retried on the next fetch
                    logger.exception("%s: could not upload %s to storage", self.tool, name)
            return dest
        if self._objects is None:
            return None
        self.local_dir.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{dest.name}.{threading.get_ident()}.fetch")
        with tmp.open("wb") as fh:
            found = self._objects.get_to(self._key(owner_id, name), fh)
        if not found:
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(dest)  # never a half-downloaded file under the real name
        self.trim(keep=name)
        return dest

    # ---- cache budget ------------------------------------------------------------------------------------
    def trim(self, keep: str = "") -> int:
        """Evict least-recently-used local copies above the budget — only ones that are in storage."""
        if self._objects is None or not self.local_dir.exists():
            return 0
        with self._lock:
            files = [p for p in self.local_dir.iterdir() if p.is_file() and not p.name.endswith((".part", ".fetch"))]
            total = sum(p.stat().st_size for p in files)
            removed, recent = 0, time.time() - RECENT_SECONDS
            for p in sorted(files, key=lambda f: f.stat().st_mtime):
                if total <= self.budget:
                    break
                owner = p.name.split(".", 1)[0]
                if p.name == keep or p.stat().st_mtime > recent or not self._objects.exists(self._key(owner, p.name)):
                    continue
                size = p.stat().st_size
                p.unlink(missing_ok=True)
                total -= size
                removed += 1
            return removed

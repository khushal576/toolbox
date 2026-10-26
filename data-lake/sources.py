"""
data-lake/sources.py — where files to load come from (roadmap L2).

- The shared **data folder**: a folder on the owner's machine (`TOOLBOX_DATA_DIR`, default `~/toolbox-data`) mounted
  READ-ONLY at /data in the data runtime and the worker. `browse()` lists it, `match()` resolves a pattern
  (`sales/2026-*.csv`, `logs/**/*.json.gz`). Every path is confined to the folder — `..`, absolute paths and links
  leading outside are refused.
- **Uploads** from the browser: staged in S3 storage (`STAGE`, `data-lake/<upload id>/…`) so the worker can read them;
  removed after a successful load, anything older than a day is swept.
- **Links**: downloaded (streamed, never held in memory) into the job's temp folder.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.state.filecache import FileCache

ROOT = Path(os.environ.get("TOOLBOX_DATA_MOUNT", "/data"))
STAGE = FileCache("data-lake", Path(os.environ.get("DATA_LAKE_STAGE_DIR", "/tmp/data-lake-stage")),
                  budget_mb=int(os.environ.get("DATA_LAKE_STAGE_CACHE_MB", "2048")))
STAGE_DAYS = 1
MAX_MATCHES = 10000


class SourceError(ValueError):
    pass


def _inside(p: Path) -> Path:
    real, root = p.resolve(), ROOT.resolve()
    if real != root and root not in real.parents:
        raise SourceError("That path is outside the data folder.")
    return real


def _rel(path: str) -> str:
    path = (path or "").strip().lstrip("/")
    if any(part == ".." for part in Path(path).parts):
        raise SourceError("'..' is not allowed — paths are relative to the data folder.")
    return path


def available() -> bool:
    return ROOT.is_dir()


def browse(path: str = "") -> dict[str, Any]:
    """Folders and files directly inside data-folder `path`."""
    if not available():
        raise SourceError(f"The data folder isn't mounted ({ROOT}). See docs/runbook.md (TOOLBOX_DATA_DIR).")
    d = _inside(ROOT / _rel(path))
    if not d.is_dir():
        raise SourceError(f"'{path}' is not a folder.")
    dirs, files = [], []
    for e in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        if e.name.startswith("."):
            continue
        try:
            e = e if e.resolve().is_relative_to(ROOT.resolve()) else None
        except OSError:
            e = None
        if e is None:
            continue
        rel = str(e.relative_to(ROOT))
        st = e.stat()
        (dirs if e.is_dir() else files).append({"name": e.name, "path": rel, "size": None if e.is_dir() else st.st_size,
                                                "mtime": st.st_mtime})
    return {"path": str(d.relative_to(ROOT.resolve())) if d != ROOT.resolve() else "", "dirs": dirs, "files": files}


def match(pattern: str) -> list[Path]:
    """Files matching a pattern relative to the data folder (glob: * ? [..] and ** for any depth). A plain path
    to a folder means every file in it."""
    if not available():
        raise SourceError(f"The data folder isn't mounted ({ROOT}).")
    pat = _rel(pattern)
    if not pat:
        raise SourceError("Give a file, a folder or a pattern (e.g. sales/2026-*.csv).")
    direct = ROOT / pat
    if direct.is_file():
        return [_inside(direct)]
    if direct.is_dir():
        pat = pat.rstrip("/") + "/*"
    out = []
    for f in sorted(ROOT.glob(pat)):
        if f.is_file() and not any(part.startswith(".") for part in f.relative_to(ROOT).parts):
            try:
                out.append(_inside(f))
            except SourceError:
                continue  # a link pointing outside the data folder: skipped (naming it directly is refused)
            if len(out) > MAX_MATCHES:
                raise SourceError(f"More than {MAX_MATCHES} files match — narrow the pattern.")
    return out


def summary(pattern: str) -> dict[str, Any]:
    from core.file_source import detect_any

    files = match(pattern)
    formats = {}
    for f in files[:200]:
        try:
            fmt = detect_any(str(f))
        except ValueError:
            fmt = "unknown"
        formats[fmt] = formats.get(fmt, 0) + 1
    return {"count": len(files), "bytes": sum(f.stat().st_size for f in files),
            "sample": [str(f.relative_to(ROOT.resolve())) for f in files[:20]], "formats": formats}


# ---- uploads -----------------------------------------------------------------------------------------------------

def new_upload_id() -> str:
    return uuid.uuid4().hex


def stage_name(upload_id: str, index: int, filename: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)[:120] or "file"
    return f"{upload_id}.{index:03d}.{base}"


def sweep_uploads() -> int:
    try:
        return STAGE.sweep(None, STAGE_DAYS * 86400)
    except Exception:  # noqa: BLE001
        return 0


# ---- links -------------------------------------------------------------------------------------------------------

def download(url: str, work: Path, log) -> Path:
    import httpx

    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise SourceError("Only http:// and https:// links can be loaded.")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(u.path).name) or "download"
    dest = work / name
    n = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=300.0)) as r:
        if r.status_code != 200:
            raise SourceError(f"The link answered HTTP {r.status_code}.")
        with dest.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
                n += len(chunk)
    log("info", f"downloaded {name} ({n / 2**20:,.1f} MB)")
    return dest

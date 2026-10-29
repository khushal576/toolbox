"""
notebook-lab/workspaces.py

Workspaces = folders on the notebook_data volume (like Colab's /content): files, notebooks, a per-workspace Python
venv and a private HOME. Everything here is plain filesystem work; nothing imports jupyter, so it is unit-testable
without a kernel.

    <DATA_DIR>/ws/<name>/            the workspace root — what the file browser shows and the kernel's cwd
        .venv/                       pip installs land here (venv --system-site-packages) — "temporary" packages
        .home/                       HOME of the kernel (matplotlib/keras/pip caches, IPython history)
        .kernels/                    generated kernelspec pointing at .venv
        .tmp/                        TMPDIR of the kernel + zip downloads in progress

The dot-folders above are RESERVED at the workspace root: hidden from listings and refused by every file API and by
zip extraction, so an uploaded archive cannot overwrite the venv or the kernelspec.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterator

DATA_DIR = Path(os.environ.get("TOOLBOX_NOTEBOOK_DIR") or "/app/data/notebook")
RESERVED = {".venv", ".home", ".kernels", ".tmp"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
MAX_TEXT_BYTES = 2 * 1024 * 1024                 # the in-browser text editor
MAX_UPLOAD_BYTES = int(os.environ.get("TOOLBOX_NOTEBOOK_MAX_UPLOAD_MB", "4096")) * 1024 * 1024
MAX_ZIP_FILES = 200_000
MAX_ZIP_BYTES = MAX_UPLOAD_BYTES                  # total uncompressed size of one archive
CHUNK = 1024 * 1024


class WorkspaceError(Exception):
    """A request the user can fix; `status` is the HTTP code the API answers."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---- workspaces ---------------------------------------------------------------------------------------------------

def _ws_root() -> Path:
    return DATA_DIR / "ws"


def root(name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise WorkspaceError("Workspace names use letters, digits, '-', '_' and '.' (max 63, no leading symbol).")
    return _ws_root() / name


def existing(name: str) -> Path:
    r = root(name)
    if not r.is_dir():
        raise WorkspaceError(f"Workspace '{name}' does not exist.", 404)
    return r


def list_workspaces() -> list[str]:
    base = _ws_root()
    return sorted(p.name for p in base.iterdir() if p.is_dir() and NAME_RE.match(p.name)) if base.is_dir() else []


def create(name: str) -> Path:
    r = root(name)
    if r.exists():
        raise WorkspaceError(f"Workspace '{name}' already exists.", 409)
    r.mkdir(parents=True)
    return r


def delete(name: str) -> None:
    shutil.rmtree(existing(name))


def usage(name: str) -> dict:
    """{files_bytes, env_bytes, files} — packages are counted apart so the user sees what 'reset' frees."""
    r = existing(name)
    files = 0
    size = {"files_bytes": 0, "env_bytes": 0}
    for dirpath, dirnames, filenames in os.walk(r):
        rel = Path(dirpath).relative_to(r)
        top = rel.parts[0] if rel.parts else ""
        key = "env_bytes" if top in (".venv", ".home") else "files_bytes"
        if top == ".kernels" or top == ".tmp":
            dirnames[:] = []
            continue
        for f in filenames:
            try:
                size[key] += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                continue
            if key == "files_bytes":
                files += 1
    return {**size, "files": files}


# ---- paths --------------------------------------------------------------------------------------------------------

def safe(ws: str, rel: str = "", *, allow_root: bool = True) -> Path:
    """Resolve `rel` inside the workspace. Rejects absolute paths, '..', reserved names and symlinks that leave it."""
    r = existing(ws)
    rel = (rel or "").replace("\\", "/")
    if rel.startswith("/"):
        raise WorkspaceError("Use paths relative to the workspace (no leading '/').")
    rel = rel.strip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise WorkspaceError("'..' is not allowed in paths.")
    if parts and parts[0] in RESERVED:
        raise WorkspaceError(f"'{parts[0]}' is reserved for the workspace environment.")
    if not parts and not allow_root:
        raise WorkspaceError("A file or folder name is required.")
    target = r.joinpath(*parts)
    real_root = r.resolve()
    real = target.resolve()
    if real != real_root and real_root not in real.parents:
        raise WorkspaceError("That path leaves the workspace.", 403)
    return target


def rel_of(ws: str, p: Path) -> str:
    return p.relative_to(existing(ws)).as_posix()


# ---- files --------------------------------------------------------------------------------------------------------

def listing(ws: str, rel: str = "") -> dict:
    d = safe(ws, rel)
    if not d.is_dir():
        raise WorkspaceError("Not a folder.", 404)
    entries = []
    at_root = d == existing(ws)
    for e in os.scandir(d):
        if at_root and e.name in RESERVED:
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        is_dir = stat.S_ISDIR(st.st_mode)
        entries.append({"name": e.name, "type": "dir" if is_dir else "file",
                        "size": None if is_dir else st.st_size, "mtime": int(st.st_mtime)})
    entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    return {"path": rel_of(ws, d) if not at_root else "", "entries": entries}


def mkdir(ws: str, rel: str) -> None:
    p = safe(ws, rel, allow_root=False)
    if p.exists():
        raise WorkspaceError("That name is already taken.", 409)
    p.mkdir(parents=True)


def rename(ws: str, src: str, dst: str) -> None:
    a, b = safe(ws, src, allow_root=False), safe(ws, dst, allow_root=False)
    if not a.exists():
        raise WorkspaceError("Source does not exist.", 404)
    if b.exists():
        raise WorkspaceError("Destination already exists — nothing was overwritten.", 409)
    b.parent.mkdir(parents=True, exist_ok=True)
    a.rename(b)


def remove(ws: str, rel: str) -> None:
    p = safe(ws, rel, allow_root=False)
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)
    else:
        raise WorkspaceError("Nothing to delete there.", 404)


def read_text(ws: str, rel: str) -> dict:
    p = safe(ws, rel, allow_root=False)
    if not p.is_file():
        raise WorkspaceError("Not a file.", 404)
    size = p.stat().st_size
    if size > MAX_TEXT_BYTES:
        raise WorkspaceError(f"Too large to edit here ({size:,} bytes; limit {MAX_TEXT_BYTES:,}). Download it instead.", 413)
    raw = p.read_bytes()
    if b"\x00" in raw[:8192]:
        raise WorkspaceError("This looks like a binary file — download it instead.", 415)
    return {"path": rel_of(ws, p), "content": raw.decode("utf-8", errors="replace"), "size": size,
            "mtime": int(p.stat().st_mtime)}


def write_text(ws: str, rel: str, content: str) -> int:
    p = safe(ws, rel, allow_root=False)
    if p.is_dir():
        raise WorkspaceError("That is a folder.", 409)
    data = content.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise WorkspaceError("Too large for the in-browser editor.", 413)
    write_bytes_atomic(p, data)
    return len(data)


def write_bytes_atomic(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


async def save_upload(ws: str, rel: str, chunks) -> int:
    """Stream an async iterator of byte chunks to <rel> (atomic: a part file, renamed when complete)."""
    p = safe(ws, rel, allow_root=False)
    if p.is_dir():
        raise WorkspaceError("A folder with that name exists.", 409)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".part-")
    total = 0
    try:
        with os.fdopen(fd, "wb") as f:
            async for c in chunks:
                total += len(c)
                if total > MAX_UPLOAD_BYTES:
                    raise WorkspaceError(f"Over the {MAX_UPLOAD_BYTES // 1024 // 1024} MB upload limit.", 413)
                f.write(c)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return total


# ---- zip ----------------------------------------------------------------------------------------------------------

def extract_zip(ws: str, zip_rel: str, dest_rel: str = "", *, delete_zip: bool = False) -> dict:
    """Unpack an archive into the workspace. Members are written by hand (never ZipFile.extract) so that absolute
    paths, '..', reserved top-level names and symlink members are skipped, and the archive is refused up front if it
    claims too many files or too many uncompressed bytes."""
    src = safe(ws, zip_rel, allow_root=False)
    dest = safe(ws, dest_rel)
    if not zipfile.is_zipfile(src):
        raise WorkspaceError("That is not a valid .zip file.", 415)
    dest.mkdir(parents=True, exist_ok=True)
    real_dest = dest.resolve()
    written = skipped = 0
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        if len(infos) > MAX_ZIP_FILES:
            raise WorkspaceError(f"The archive has {len(infos):,} entries (limit {MAX_ZIP_FILES:,}).", 413)
        if sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
            raise WorkspaceError("The archive expands past the size limit.", 413)
        at_ws_root = dest == existing(ws)
        for i in infos:
            name = i.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            mode = (i.external_attr >> 16) & 0xFFFF
            bad = (not parts or name.startswith("/") or ".." in parts or (at_ws_root and parts[0] in RESERVED)
                   or (mode and stat.S_ISLNK(mode)) or re.match(r"^[A-Za-z]:", parts[0]))
            if bad:
                skipped += 1
                continue
            out = real_dest.joinpath(*parts)
            if real_dest not in out.resolve().parents and out.resolve() != real_dest:
                skipped += 1
                continue
            if i.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as s, open(out, "wb") as d:
                shutil.copyfileobj(s, d, CHUNK)
            written += 1
    if delete_zip:
        src.unlink(missing_ok=True)
    return {"files": written, "skipped": skipped}


def make_zip(ws: str, rel: str = "") -> tuple[Path, str]:
    """Zip a folder (or the whole workspace) into .tmp and return (zip path, download name). Reserved folders are
    left out; the caller deletes the file after sending it."""
    base = safe(ws, rel)
    if not base.exists():
        raise WorkspaceError("Nothing there.", 404)
    tmpdir = existing(ws) / ".tmp"
    tmpdir.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=tmpdir, prefix="dl-", suffix=".zip")
    os.close(fd)
    at_root = base == existing(ws)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        if base.is_file():
            z.write(base, base.name)
        else:
            for dirpath, dirnames, filenames in os.walk(base):
                if Path(dirpath) == base and at_root:
                    dirnames[:] = [d for d in dirnames if d not in RESERVED]
                for f in filenames:
                    full = Path(dirpath) / f
                    if full.is_symlink() or not full.is_file() or f.startswith(".part-"):
                        continue
                    z.write(full, full.relative_to(base).as_posix())
                if not filenames and not dirnames:
                    z.writestr(Path(dirpath).relative_to(base).as_posix() + "/", "")
    return Path(tmp), f"{ws if at_root else base.name}.zip"


def iter_file(p: Path) -> Iterator[bytes]:
    with open(p, "rb") as f:
        while chunk := f.read(CHUNK):
            yield chunk


# ---- environment (venv) ------------------------------------------------------------------------------------------

def venv_dir(ws: str) -> Path:
    return existing(ws) / ".venv"


def venv_python(ws: str) -> Path:
    return venv_dir(ws) / "bin" / "python"


def env_ready(ws: str) -> bool:
    return venv_python(ws).exists()


def ensure_env(ws: str) -> Path:
    """Create the workspace venv on first use. --system-site-packages: the base image's pandas/numpy/ipykernel are
    visible and count as 'already installed' for pip, so `pip install tensorflow` adds only what is missing and never
    re-installs (or shadows) numpy for the whole stack."""
    r = existing(ws)
    py = venv_python(ws)
    if not py.exists():
        (r / ".tmp").mkdir(exist_ok=True)
        (r / ".home").mkdir(exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir(ws))], check=True,
                       capture_output=True, timeout=180)
    write_kernelspec(ws)
    return py


def write_kernelspec(ws: str) -> Path:
    import json

    d = existing(ws) / ".kernels" / "python3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "kernel.json").write_text(json.dumps({
        "argv": [str(venv_python(ws)), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "Python 3", "language": "python"}))
    return d.parent


def reset_env(ws: str) -> None:
    """Forget every pip-installed package (and caches). The caller shuts the kernel down first."""
    r = existing(ws)
    for n in (".venv", ".home", ".kernels", ".tmp"):
        shutil.rmtree(r / n, ignore_errors=True)


def kernel_env(ws: str) -> dict[str, str]:
    """The ONLY environment user code gets: nothing from this server's environ (no TOOLBOX_*, no Redis URL)."""
    r = existing(ws)
    vbin = str(venv_dir(ws) / "bin")
    return {
        "PATH": f"{vbin}:/usr/local/bin:/usr/bin:/bin",
        "VIRTUAL_ENV": str(venv_dir(ws)),
        "HOME": str(r / ".home"),
        "TMPDIR": str(r / ".tmp"),
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "TF_CPP_MIN_LOG_LEVEL": "2",
    }


PIP_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*(\[[A-Za-z0-9_,.\-]+\])?([<>=!~]=?[A-Za-z0-9_.*+!\-]+(,[<>=!~]=?[A-Za-z0-9_.*+!\-]+)*)?$")


def pip_args(spec: str) -> list[str]:
    """Turn 'tensorflow==2.17.0 scikit-learn' (or '-r requirements.txt', '--upgrade') into pip arguments. This
    guards typos and accidental flags; it is not a security boundary — a cell can run any code anyway."""
    toks = spec.split()
    if not toks:
        raise WorkspaceError("Enter at least one package, e.g. tensorflow or scikit-learn==1.5.2.")
    out: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("--upgrade", "-U", "--pre"):
            out.append(t)
        elif t == "-r" and i + 1 < len(toks):
            f = toks[i + 1]
            if f.startswith(("/", "-")) or ".." in f.split("/"):
                raise WorkspaceError("-r takes a requirements file inside the workspace, e.g. -r requirements.txt.")
            out += ["-r", f]  # pip runs with the workspace root as its cwd
            i += 1
        elif PIP_TOKEN.match(t):
            out.append(t)
        else:
            raise WorkspaceError(f"'{t}' is not a package name or version spec.")
        i += 1
    return out

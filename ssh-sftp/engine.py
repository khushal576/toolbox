"""
ssh-sftp/engine.py

File operations, uploads/downloads and commands over SSH/SFTP, built for being SAFE and STABLE:

UPLOAD (run_upload) — received into a stage directory first (see state_store.py), then sent from there:
  1. refuses to start if the target exists and "overwrite" was not ticked, or if it is a directory;
  2. writes to a HIDDEN temporary name next to the target — `.<name>.<sha256-prefix>.part` — never to the
     real name, so a half-sent file can never be mistaken for the real one (the hash in the name also means a
     different file with the same name never resumes onto the wrong bytes);
  3. on a dropped connection / timeout it reconnects and RESUMES from the size already on the server
     (up to MAX_ATTEMPTS, with back-off); permission / path / disk errors are not retried — they would repeat;
  4. verifies the result: size, then SHA-256 (the server's `sha256sum`, else a read-back for files up to
     READBACK_MAX; if neither is possible it says "size verified only" instead of claiming more);
  5. only then renames into place — atomic overwrite (`posix_rename`) when overwriting;
  6. a failure or Stop keeps the staged file and the remote `.part`, so Retry continues instead of restarting.

COMMANDS (run_command) — one non-interactive command on its own connection, output streamed line by line,
with a hard timeout and Stop. A short list of obviously destructive patterns needs an explicit confirm.

Everything that changes a server is refused for a server saved as read-only.
"""

from __future__ import annotations

import errno
import hashlib
import posixpath
import re
import shlex
import stat as pystat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import paramiko

try:  # package import when mounted inside the toolbox (ssh_sftp.*)
    from ssh_sftp import sessions, state_store as store
except ImportError:  # flat import when run standalone from within this folder
    import sessions
    import state_store as store

try:
    from core import ssh_client
except ImportError:
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import ssh_client

LogFn = Callable[[str, str], None]
CHUNK = 256 * 1024
MAX_ATTEMPTS = 6
READBACK_MAX = 256 * 1024 * 1024
LIST_LIMIT = 5000
MAX_COMMAND_SECONDS = 1800
DANGEROUS = [
    (re.compile(r"\brm\s+(-\w*[rR]\w*\s+(-\w+\s+)*|--recursive\s+)(-\w+\s+)*(/|/\*|~|\$HOME)(\s|$)"), "recursive delete of / or your home"),
    (re.compile(r"\bmkfs(\.\w+)?\b"), "formats a filesystem"),
    (re.compile(r"\bdd\b[^|;]*\bof=/dev/"), "writes straight to a disk device"),
    (re.compile(r">\s*/dev/(sd|nvme|vd|xvd)\w*"), "overwrites a disk device"),
    (re.compile(r"\b(shutdown|reboot|poweroff|halt)\b|\binit\s+[06]\b"), "shuts down or reboots the server"),
    (re.compile(r":\(\)\s*\{"), "fork bomb"),
    (re.compile(r"\bchmod\s+-R\s+\S+\s+/(\s|$)"), "recursive chmod on /"),
    (re.compile(r"\bchown\s+-R\s+\S+\s+/(\s|$)"), "recursive chown on /"),
]


class ReadOnlyServer(PermissionError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _writable(server_id: str) -> dict[str, Any]:
    data = sessions.resolve(server_id)
    if data.get("read_only"):
        raise ReadOnlyServer("This server is saved as READ-ONLY in the Vault — uploads, changes and commands are disabled.")
    return data


def check_path(path: str) -> str:
    if not path or "\x00" in path or len(path) > 4096:
        raise ValueError("Invalid path.")
    return path


def check_name(name: str) -> str:
    if not name or name in (".", "..") or "/" in name or "\x00" in name or len(name) > 255:
        raise ValueError("Invalid file name (no slashes, not empty, not '.' or '..').")
    return name


def danger_reason(command: str) -> Optional[str]:
    for rx, why in DANGEROUS:
        if rx.search(command):
            return why
    return None


# ====================================================================== browsing / small operations

def list_dir(server_id: str, path: Optional[str]) -> dict[str, Any]:
    def fn(sftp: paramiko.SFTPClient) -> dict[str, Any]:
        real = sftp.normalize(check_path(path) if path else ".")
        attrs = sftp.listdir_attr(real)
        entries = []
        for a in attrs[:LIST_LIMIT]:
            mode = a.st_mode or 0
            is_link = pystat.S_ISLNK(mode)
            is_dir = pystat.S_ISDIR(mode)
            if is_link:
                try:
                    is_dir = pystat.S_ISDIR(sftp.stat(posixpath.join(real, a.filename)).st_mode or 0)
                except OSError:
                    pass  # a dangling link: shown as a file
            entries.append({
                "name": a.filename, "is_dir": is_dir, "is_link": is_link, "size": a.st_size or 0,
                "mtime": a.st_mtime, "mode": pystat.filemode(mode) if mode else "",
            })
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return {"path": real, "parent": None if real == "/" else posixpath.dirname(real) or "/", "entries": entries,
                "truncated": len(attrs) > LIST_LIMIT}
    return sessions.with_sftp(server_id, fn)


def make_dir(server_id: str, path: str) -> None:
    _writable(server_id)
    check_path(path)

    def fn(s: paramiko.SFTPClient) -> None:
        try:
            s.stat(path)
        except FileNotFoundError:
            s.mkdir(path)  # SFTP reports most failures as a bare "Failure"; the checks around it give real reasons
            return
        raise FileExistsError(f"'{path}' already exists.")
    sessions.with_sftp(server_id, fn)


def rename(server_id: str, src: str, dst: str) -> None:
    _writable(server_id)
    check_path(src), check_path(dst)

    def fn(s: paramiko.SFTPClient) -> None:
        try:
            s.stat(dst)
        except FileNotFoundError:
            s.rename(src, dst)
            return
        raise FileExistsError(f"'{dst}' already exists — rename never overwrites.")
    sessions.with_sftp(server_id, fn)


def delete(server_id: str, path: str) -> str:
    """Delete ONE file or ONE EMPTY folder. There is deliberately no recursive delete."""
    _writable(server_id)

    def fn(s: paramiko.SFTPClient) -> str:
        st = s.lstat(check_path(path))
        if pystat.S_ISDIR(st.st_mode or 0):
            if s.listdir(path):
                raise OSError(errno.ENOTEMPTY, "The folder is not empty. Only empty folders can be deleted here.")
            s.rmdir(path)
            return "folder"
        s.remove(path)
        return "file"
    return sessions.with_sftp(server_id, fn)


def file_info(server_id: str, path: str) -> dict[str, Any]:
    def fn(s: paramiko.SFTPClient) -> dict[str, Any]:
        st = s.stat(check_path(path))
        if pystat.S_ISDIR(st.st_mode or 0):
            raise IsADirectoryError("That is a folder — only files can be downloaded.")
        return {"size": st.st_size or 0, "name": posixpath.basename(path)}
    return sessions.with_sftp(server_id, fn)


def stream_download(server_id: str, path: str) -> Iterator[bytes]:
    """Yield a remote file in chunks on its OWN connection (a slow download never blocks browsing)."""
    client = ssh_client.open_client(sessions.resolve(server_id))
    try:
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(60)
        with sftp.open(check_path(path), "rb") as f:
            f.prefetch()
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                yield chunk
    finally:
        client.close()


# ====================================================================== upload

def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (ssh_client.HostKeyUnverified, ssh_client.HostKeyMismatch)):
        return False
    if isinstance(exc, ssh_client.SSHError):
        return exc.retryable
    if isinstance(exc, (PermissionError, FileExistsError, ValueError, IsADirectoryError, NotADirectoryError, FileNotFoundError)):
        return False
    if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT, errno.EACCES, errno.EPERM, errno.ENOENT, errno.EROFS):
        return False
    return sessions.is_dead(exc) or isinstance(exc, (OSError, EOFError))


def _plain(exc: BaseException) -> str:
    if isinstance(exc, (ssh_client.SSHError, ValueError, FileExistsError, ReadOnlyServer)):
        return str(exc)
    if isinstance(exc, PermissionError) or (isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM)):
        return "Permission denied on the server — the login cannot write there."
    if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return "The server is out of disk space (or the account is over its quota)."
    if isinstance(exc, FileNotFoundError):
        return "The remote folder does not exist."
    return (str(exc) or exc.__class__.__name__)[:300]


def _remote_sha256(client: paramiko.SSHClient, sftp: paramiko.SFTPClient, path: str, size: int, cancel: threading.Event) -> Optional[str]:
    """SHA-256 of a remote file: the server's own sha256sum if it has one (no data crosses the network),
    else a read-back for files up to READBACK_MAX. None = could not verify beyond size."""
    try:
        _, out, _ = client.exec_command("sha256sum -- " + shlex.quote(path), timeout=600)
        text = out.read().decode("utf-8", "replace").strip()
        if out.channel.recv_exit_status() == 0 and text:
            return text.split()[0].lower()
    except Exception:  # noqa: BLE001 — fall through to the read-back
        pass
    if size > READBACK_MAX:
        return None
    h = hashlib.sha256()
    with sftp.open(path, "rb") as f:
        f.prefetch()
        while True:
            if cancel.is_set():
                raise InterruptedError()
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def run_upload(
    tid: str, cancel: threading.Event, log: LogFn, progress: dict, on_chunk: Optional[Callable[[int], None]] = None,
) -> None:
    """Send staged transfer *tid* to its server. *on_chunk(bytes_sent_so_far)* is called after every chunk
    (the test hook for dropping connections mid-transfer; unused in production)."""
    t = store.get_transfer(tid)
    staged = store.stage_path(tid)
    store.update_transfer(tid, status="running", error=None, note=None, finished_at=None)
    size, sha = t["size"], t["sha256"]
    final = posixpath.join(t["remote_dir"], t["name"])
    part = posixpath.join(t["remote_dir"], f".{t['name']}.{sha[:12]}.part")
    attempts = t["attempts"]
    fresh = False
    last = 0.0
    try:
        if not staged.exists():
            raise ValueError("The staged copy of this file is gone (it was cleaned up) — upload it again.")
        data = _writable(t["server_id"])
        log("info", f"{t['name']} → {ssh_client.describe(data)}:{t['remote_dir']}  ({size:,} bytes)")
        while True:
            client = None
            try:
                client = ssh_client.open_client(data)
                sftp = client.open_sftp()
                sftp.get_channel().settimeout(60)
                try:
                    if not pystat.S_ISDIR(sftp.stat(t["remote_dir"]).st_mode or 0):
                        raise NotADirectoryError(f"'{t['remote_dir']}' is not a folder.")
                except FileNotFoundError:
                    raise FileNotFoundError(f"The remote folder '{t['remote_dir']}' does not exist.") from None
                try:
                    existing = sftp.stat(final)
                    if pystat.S_ISDIR(existing.st_mode or 0):
                        raise ValueError(f"'{final}' is a folder — choose another name.")
                    if not t["overwrite"]:
                        raise FileExistsError(f"'{t['name']}' already exists there. Tick “overwrite” to replace it.")
                except FileNotFoundError:
                    pass
                offset = 0
                if not fresh:
                    try:
                        offset = sftp.stat(part).st_size or 0
                    except FileNotFoundError:
                        offset = 0
                if fresh or offset > size:
                    try:
                        sftp.remove(part)
                    except FileNotFoundError:
                        pass
                    offset = 0
                if offset:
                    log("info", f"resuming from {offset:,} of {size:,} bytes")
                progress.update(total=size, done=offset)
                with open(staged, "rb") as src:
                    src.seek(offset)
                    f = sftp.open(part, "r+" if offset else "wb")
                    try:
                        f.set_pipelined(True)
                        if offset:
                            f.seek(offset)
                        sent = offset
                        while sent < size:
                            if cancel.is_set():
                                raise InterruptedError()
                            chunk = src.read(CHUNK)
                            if not chunk:
                                break
                            f.write(chunk)
                            sent += len(chunk)
                            progress["done"] = sent
                            if on_chunk:
                                on_chunk(sent)
                            if time.monotonic() - last > 1.0:
                                last = time.monotonic()
                                store.update_transfer(tid, bytes_done=sent)
                    finally:
                        f.close()
                got = sftp.stat(part).st_size or 0
                if got != size:
                    raise OSError(f"The server has {got:,} bytes after the transfer, expected {size:,}.")
                log("info", "sent — verifying…")
                remote = _remote_sha256(client, sftp, part, size, cancel)
                if remote is not None and remote != sha:
                    # the resumed prefix (or the transfer) is not what we sent: start over from zero, once
                    fresh = True
                    raise OSError("Checksum mismatch after upload — retrying from the beginning.")
                note = "checksum (SHA-256) verified" if remote else "size verified only (no sha256sum on the server and the file is large)"
                if t["overwrite"]:
                    try:
                        sftp.posix_rename(part, final)  # atomic replace (OpenSSH extension)
                    except (IOError, OSError, AttributeError):
                        try:
                            sftp.remove(final)
                        except FileNotFoundError:
                            pass
                        sftp.rename(part, final)
                        note += "; replaced non-atomically (server lacks atomic rename)"
                else:
                    sftp.rename(part, final)
                store.update_transfer(tid, status="done", bytes_done=size, error=None, note=note, attempts=attempts, finished_at=_now())
                staged.unlink(missing_ok=True)
                log("ok", f"done — {final} ({note})")
                return
            except InterruptedError:
                raise
            except Exception as exc:  # noqa: BLE001 — classified below: retry the transient, fail the rest
                if not _retryable(exc) or attempts + 1 >= MAX_ATTEMPTS:
                    raise
                attempts += 1
                delay = min(2 ** attempts, 30)
                store.update_transfer(tid, attempts=attempts)
                log("warn", f"{_plain(exc)} — reconnecting in {delay}s (attempt {attempts + 1}/{MAX_ATTEMPTS}); it will resume")
                if cancel.wait(delay):
                    raise InterruptedError() from None
            finally:
                if client is not None:
                    client.close()
    except InterruptedError:
        store.update_transfer(tid, status="cancelled", error="Stopped. The partial upload is kept — Retry resumes it.", attempts=attempts, finished_at=_now())
        log("warn", "stopped — partial upload kept, Retry resumes")
    except ssh_client.HostKeyUnverified as exc:
        store.update_transfer(tid, status="failed", error=f"Host key not trusted yet ({exc.fingerprint}) — open the server in the Files tab and trust it.", attempts=attempts, finished_at=_now())
        log("error", "host key not trusted yet")
    except Exception as exc:  # noqa: BLE001
        msg = _plain(exc)
        retries = f" (gave up after {attempts + 1} attempts; the staged file is kept — press Retry)" if _retryable(exc) else ""
        store.update_transfer(tid, status="failed", error=msg + retries, attempts=attempts, finished_at=_now())
        log("error", msg + retries)


# ====================================================================== commands

def run_command(
    cid: str, server_id: str, command: str, timeout: int, cancel: threading.Event, log: LogFn, progress: dict,
) -> None:
    t0 = time.monotonic()
    status, code = "failed", None
    client = None
    try:
        data = _writable(server_id)
        timeout = max(1, min(int(timeout), MAX_COMMAND_SECONDS))
        log("info", f"$ {command}")
        client = ssh_client.open_client(data)
        chan = client.get_transport().open_session(timeout=15)
        chan.exec_command(command)
        deadline = t0 + timeout
        partial = {"out": b"", "err": b""}
        lines = 0

        def feed(kind: str, raw: bytes) -> None:
            nonlocal lines
            partial[kind] += raw
            while b"\n" in partial[kind]:
                line, partial[kind] = partial[kind].split(b"\n", 1)
                log("warn" if kind == "err" else "info", line.decode("utf-8", "replace").rstrip("\r")[:4000])
                lines += 1
                progress["lines"] = lines

        while True:
            if cancel.is_set():
                chan.close()
                status = "stopped"
                break
            if time.monotonic() > deadline:
                chan.close()
                status = "timeout"
                log("error", f"timed out after {timeout}s — the command was cut off")
                break
            got = False
            if chan.recv_ready():
                feed("out", chan.recv(32768))
                got = True
            if chan.recv_stderr_ready():
                feed("err", chan.recv_stderr(32768))
                got = True
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            if not got:
                time.sleep(0.05)
        for kind in ("out", "err"):
            if partial[kind]:
                log("warn" if kind == "err" else "info", partial[kind].decode("utf-8", "replace")[:4000])
        if status == "failed":
            code = chan.recv_exit_status()
            status = "ok" if code == 0 else "failed"
            log("ok" if code == 0 else "error", f"exit code {code}")
        elif status == "stopped":
            log("warn", "stopped")
    except Exception as exc:  # noqa: BLE001
        log("error", _plain(exc))
    finally:
        if client is not None:
            client.close()
        store.finish_command(cid, status, code, time.monotonic() - t0)

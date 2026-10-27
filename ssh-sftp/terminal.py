"""
ssh-sftp/terminal.py — live terminal sessions (owner request 2026-10-28: "run commands without logging in again and
again").

One `Term` = one SSH connection (core.ssh_client.open_client: the Vault credential, host key pinned) + one
interactive shell channel with a PTY (`xterm-256color`). A reader thread appends everything the shell prints to a
byte buffer with ABSOLUTE offsets (the last MAX_BUFFER bytes are kept), so a browser can attach — or re-attach after a
reload — and continue from any offset it has seen. Keystrokes are written to the channel as they arrive.

Sessions live in THIS process's memory (an SSH channel can't be shared between processes): the `rt-ssh` container
runs one web process (compose pins TOOLBOX_WEB_WORKERS=1 for it). A session ends when the shell exits, on Close, after
IDLE_SECONDS without input and without an attached page, after MAX_AGE_SECONDS, or when the container restarts or
goes to sleep (an open page keeps it awake: its output stream is traffic).
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Optional

try:
    from core import ssh_client
except ImportError:  # standalone
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import ssh_client

MAX_TERMS = int(os.environ.get("SSH_TERM_MAX", "8"))
MAX_BUFFER = int(os.environ.get("SSH_TERM_BUFFER", str(512 * 1024)))   # bytes of scrollback kept for re-attach
IDLE_SECONDS = int(os.environ.get("SSH_TERM_IDLE", str(30 * 60)))      # no page attached and no input
MAX_AGE_SECONDS = int(os.environ.get("SSH_TERM_MAX_AGE", str(12 * 3600)))


class TermError(RuntimeError):
    pass


class Term:
    def __init__(self, server_id: str, name: str, client: Any, chan: Any):
        self.id = uuid.uuid4().hex
        self.server_id, self.name = server_id, name
        self.client, self.chan = client, chan
        self.buf = bytearray()
        self.base = 0                      # absolute offset of buf[0]
        self.lock = threading.Lock()
        self.closed = False
        self.exit_status: Optional[int] = None
        self.started = self.last_input = self.last_seen = time.time()
        self.viewers = 0
        threading.Thread(target=self._read, name=f"term-{self.id[:6]}", daemon=True).start()

    def _read(self) -> None:
        try:
            while True:
                data = self.chan.recv(32768)
                if not data:
                    break
                with self.lock:
                    self.buf += data
                    if len(self.buf) > MAX_BUFFER:
                        drop = len(self.buf) - MAX_BUFFER
                        del self.buf[:drop]
                        self.base += drop
        except Exception:  # noqa: BLE001 — a dead connection just ends the session
            pass
        finally:
            try:
                if self.chan.exit_status_ready():
                    self.exit_status = self.chan.recv_exit_status()
            except Exception:  # noqa: BLE001
                pass
            self.closed = True
            self._close_client()

    def read(self, since: int) -> tuple[bytes, int, bool]:
        """(bytes after `since`, the new offset, True when part of what was asked for is no longer kept)."""
        with self.lock:
            end = self.base + len(self.buf)
            start = max(since, self.base)
            return bytes(self.buf[start - self.base:]), end, since < self.base

    def write(self, data: str) -> None:
        if self.closed:
            raise TermError("This terminal has ended.")
        self.last_input = time.time()
        self.chan.sendall(data.encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        if not self.closed:
            self.chan.resize_pty(width=max(10, min(cols, 500)), height=max(3, min(rows, 300)))

    def close(self) -> None:
        self.closed = True
        try:
            self.chan.close()
        except Exception:  # noqa: BLE001
            pass
        self._close_client()

    def _close_client(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass

    def info(self) -> dict[str, Any]:
        return {"id": self.id, "server_id": self.server_id, "name": self.name, "started": self.started,
                "last_input": self.last_input, "closed": self.closed, "exit_status": self.exit_status,
                "viewers": self.viewers, "offset": self.base + len(self.buf)}


_terms: dict[str, Term] = {}
_lock = threading.Lock()


def open_term(server: dict[str, Any], cols: int = 120, rows: int = 32) -> Term:
    """Log in with the saved server (host key must be pinned) and start a login shell with a PTY."""
    _reap()
    with _lock:
        if sum(not t.closed for t in _terms.values()) >= MAX_TERMS:
            raise TermError(f"{MAX_TERMS} terminals are already open — close one first.")
    if server.get("read_only"):
        raise TermError("This server is saved as read-only — a terminal could change things, so it is not offered.")
    client = ssh_client.open_client(server)          # raises HostKeyUnverified / HostKeyMismatch / SSHError
    try:
        chan = client.get_transport().open_session()
        chan.get_pty(term="xterm-256color", width=max(10, cols), height=max(3, rows))
        chan.invoke_shell()
    except Exception as exc:  # noqa: BLE001
        client.close()
        raise TermError(f"The server did not start a shell: {exc}") from None
    t = Term(server["_id"], server.get("_name") or server.get("host", "server"), client, chan)
    with _lock:
        _terms[t.id] = t
    return t


def get(term_id: str) -> Term:
    t = _terms.get(term_id)
    if t is None:
        raise KeyError(term_id)
    return t


def close(term_id: str) -> None:
    with _lock:
        t = _terms.pop(term_id, None)
    if t is not None:
        t.close()


def list_terms() -> list[dict[str, Any]]:
    _reap()
    return [t.info() for t in sorted(_terms.values(), key=lambda x: x.started)]


def _reap() -> None:
    """Forget ended sessions after a while; close idle (no page, no typing) and very old ones."""
    now = time.time()
    with _lock:
        for tid, t in list(_terms.items()):
            idle = t.viewers == 0 and now - max(t.last_input, t.last_seen) > IDLE_SECONDS
            if not t.closed and (idle or now - t.started > MAX_AGE_SECONDS):
                t.close()
            if t.closed and now - t.last_seen > 300:
                _terms.pop(tid, None)


def _reaper_loop() -> None:
    while True:
        time.sleep(60)
        try:
            _reap()
        except Exception:  # noqa: BLE001
            pass


threading.Thread(target=_reaper_loop, name="term-reaper", daemon=True).start()

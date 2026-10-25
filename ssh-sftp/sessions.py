"""
ssh-sftp/sessions.py

Saved servers (Vault, kind "ssh_server") and ONE cached, health-checked connection per server for quick
interactive work (browsing, mkdir, rename, delete). Browsing a folder must not pay a full SSH handshake
every click, but a cached connection can go stale (NAT drop, server restart) — so every use is wrapped:
a dead connection is dropped and the call retried once on a fresh one, and idle sessions are closed after
two minutes. Long jobs (uploads, downloads, commands) do NOT use the cache: they open their own connection
so a slow transfer never blocks browsing and a failure on one can't poison the other.

Lives in this process's memory — one more reason the container stays at --workers 1 (see ../CLAUDE.md).
"""

from __future__ import annotations

import errno
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import paramiko

try:
    from core import ssh_client, vault as vault_store
except ImportError:  # standalone dev run from inside this folder
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import ssh_client, vault as vault_store

vault = vault_store.scoped("ssh-sftp")  # Vault scope from manifest.yaml `vault:` (roadmap B7)

T = TypeVar("T")
IDLE_SECONDS = 120


class UnknownServer(KeyError):
    pass


def list_servers() -> list[dict[str, Any]]:
    out = []
    for meta in vault.list_secrets(ssh_client.KIND):
        try:
            out.append(ssh_client.public_view(meta["id"], meta["name"], vault.get_secret(meta["id"])))
        except Exception:  # noqa: BLE001 — one undecryptable entry must not hide the others
            continue
    return out


def resolve(server_id: str) -> dict[str, Any]:
    """The full saved entry (WITH secrets — never send it to a browser). Only ids of ssh_server entries are
    accepted, so another secret's id (a database password!) can never be coaxed into an SSH login."""
    if server_id not in {m["id"] for m in vault.list_secrets(ssh_client.KIND)}:
        raise UnknownServer(server_id)
    data = vault.get_secret(server_id)
    data["_name"] = next(m["name"] for m in vault.list_secrets(ssh_client.KIND) if m["id"] == server_id)
    return data


def is_dead(exc: BaseException) -> bool:
    """Did the CONNECTION die (as opposed to the server answering 'no such file')? SFTP answers raise
    OSError WITH an errno; a dead socket raises EOFError / SSHException / OSError without one."""
    if isinstance(exc, (EOFError, paramiko.SSHException, ConnectionError, socket.timeout, BrokenPipeError)):
        return True
    return isinstance(exc, OSError) and exc.errno in (None, errno.EPIPE, errno.ECONNRESET, errno.ETIMEDOUT)


class _Session:
    def __init__(self, client: paramiko.SSHClient):
        self.client = client
        self.sftp = client.open_sftp()
        self.sftp.get_channel().settimeout(30)
        self.last_used = time.monotonic()
        self.lock = threading.RLock()

    def alive(self) -> bool:
        t = self.client.get_transport()
        return t is not None and t.is_active()

    def close(self) -> None:
        for c in (self.sftp, self.client):
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass


_SESSIONS: dict[str, _Session] = {}
_LOCK = threading.Lock()


def _reaper() -> None:
    while True:
        time.sleep(30)
        with _LOCK:
            for sid in [s for s, x in _SESSIONS.items() if time.monotonic() - x.last_used > IDLE_SECONDS or not x.alive()]:
                _SESSIONS.pop(sid).close()


threading.Thread(target=_reaper, daemon=True, name="ssh-sftp-reaper").start()


def drop(server_id: str) -> None:
    with _LOCK:
        s = _SESSIONS.pop(server_id, None)
    if s:
        s.close()


def _get(server_id: str) -> _Session:
    with _LOCK:
        s = _SESSIONS.get(server_id)
        if s is not None and s.alive():
            s.last_used = time.monotonic()
            return s
        if s is not None:
            _SESSIONS.pop(server_id).close()
    data = resolve(server_id)
    client = ssh_client.open_client(data)          # HostKeyUnverified / HostKeyMismatch / SSHError propagate
    s = _Session(client)
    with _LOCK:
        old = _SESSIONS.get(server_id)
        _SESSIONS[server_id] = s
    if old:
        old.close()
    return s


def with_sftp(server_id: str, fn: Callable[[paramiko.SFTPClient], T]) -> T:
    """Run fn(sftp) on the cached session; if the connection turns out to be dead, reconnect and try once more."""
    for attempt in (1, 2):
        s = _get(server_id)
        try:
            with s.lock:
                s.last_used = time.monotonic()
                return fn(s.sftp)
        except Exception as exc:  # noqa: BLE001
            if attempt == 1 and is_dead(exc):
                drop(server_id)
                continue
            raise
    raise RuntimeError("unreachable")

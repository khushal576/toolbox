"""
core/ssh_client.py

Safe SSH/SFTP connections from a Vault entry of kind "ssh_server". Shared by the SSH & SFTP tool and
the Vault page's "Add SSH server" form. Built on paramiko (already a dependency, used for the DB SSH
tunnels) — but with the defaults tightened, because this one is used to run commands and move files:

 * HOST KEYS ARE PINNED. A paramiko client by default either refuses unknown hosts or (AutoAddPolicy)
   trusts anything — both wrong here. The Vault entry stores the server's key fingerprint once the user
   has confirmed it; every later connection must present exactly that key. No pin -> HostKeyUnverified
   (the caller shows the fingerprint and asks); a different key -> HostKeyMismatch (blocked, loudly).
   A man-in-the-middle cannot silently take over a saved server.
 * ONLY the Vault credential is tried: no ssh-agent, no ~/.ssh keys.
 * Timeouts everywhere + TCP/SSH keepalives, so a dead network fails fast instead of hanging a request
   forever and an idle-looking session isn't dropped by a NAT.
 * Secrets never leave this module in a message: errors are mapped to plain sentences and scrubbed.

Vault entry shape (kind "ssh_server"):
  {host, port, username, auth: "password"|"key", password?, private_key?, passphrase?, read_only?: bool,
   host_key?: {type, fingerprint, key_b64}}
"""

from __future__ import annotations

import base64
import hashlib
import socket
from typing import Any, Optional

import paramiko

from core.postgres_conn import _parse_private_key, scrub_password

KIND = "ssh_server"
CONNECT_TIMEOUT = 15
KEEPALIVE_SECONDS = 20


class SSHError(RuntimeError):
    """A connection/login problem; the message is plain, user-facing and free of secrets.
    `retryable` is True for network-type failures (timeout, refused, dropped) that a retry can fix, and
    False for ones it cannot (wrong login, bad key, unreadable configuration)."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class HostKeyUnverified(SSHError):
    """The server's key is not pinned yet. Carries what the user must confirm."""

    def __init__(self, key_type: str, fingerprint: str, key_b64: str):
        super().__init__(f"This server's host key is not trusted yet ({key_type} {fingerprint}).")
        self.key_type, self.fingerprint, self.key_b64 = key_type, fingerprint, key_b64


class HostKeyMismatch(SSHError):
    """The server presented a DIFFERENT key than the pinned one."""

    def __init__(self, expected: str, got: str):
        super().__init__(
            f"HOST KEY CHANGED — the server now presents {got} but {expected} was trusted. Either the server was "
            "rebuilt, or something is intercepting the connection. Do NOT continue until you have verified it with "
            "whoever runs the server; then delete the saved server in the Vault and add it again."
        )
        self.expected, self.got = expected, got


def fingerprint_sha256(key: paramiko.PKey) -> str:
    """OpenSSH-style `SHA256:...` fingerprint (what `ssh-keygen -lf` prints)."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def pin_of(key: paramiko.PKey) -> dict[str, str]:
    return {"type": key.get_name(), "fingerprint": fingerprint_sha256(key), "key_b64": key.get_base64()}


def describe(data: dict[str, Any]) -> str:
    """user@host:port — never a secret."""
    return f"{data.get('username')}@{data.get('host')}:{data.get('port') or 22}"


class _PinPolicy(paramiko.MissingHostKeyPolicy):
    """Called for every host (there is no known_hosts): accept only the pinned key."""

    def __init__(self, pinned: Optional[dict[str, str]]):
        self.pinned = pinned

    def missing_host_key(self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey) -> None:
        got = fingerprint_sha256(key)
        if not self.pinned or not self.pinned.get("fingerprint"):
            raise HostKeyUnverified(key.get_name(), got, key.get_base64())
        if got != self.pinned["fingerprint"]:
            raise HostKeyMismatch(self.pinned["fingerprint"], got)


def _map_error(exc: BaseException, data: dict[str, Any]) -> SSHError:
    where = describe(data)
    if isinstance(exc, paramiko.AuthenticationException):
        how = "key" if data.get("auth") == "key" else "password"
        return SSHError(f"Login to {where} failed — the username or the {how} was refused.")
    if isinstance(exc, paramiko.BadAuthenticationType):
        return SSHError(f"{where} does not accept this kind of login ({data.get('auth', 'password')}).")
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return SSHError(f"Timed out connecting to {where} — check the host, the port and any firewall.", True)
    if isinstance(exc, socket.gaierror):
        return SSHError(f"Could not resolve the host name '{data.get('host')}'.", True)
    if isinstance(exc, (ConnectionRefusedError, paramiko.ssh_exception.NoValidConnectionsError)):
        return SSHError(f"{where} refused the connection — is SSH running on that port?", True)
    if isinstance(exc, paramiko.SSHException):
        return SSHError(f"SSH error talking to {where}: {scrub_password(str(exc))[:200]}", True)
    if isinstance(exc, OSError):
        return SSHError(f"Network error talking to {where}: {scrub_password(str(exc))[:200]}", True)
    return SSHError(scrub_password(str(exc))[:300] or exc.__class__.__name__)


def _load_pkey(data: dict[str, Any]) -> Optional[paramiko.PKey]:
    if data.get("auth") != "key":
        return None
    try:
        return _parse_private_key(data.get("private_key") or "", data.get("passphrase") or None)
    except ValueError as exc:
        raise SSHError(str(exc)) from exc


def open_client(data: dict[str, Any], *, timeout: int = CONNECT_TIMEOUT) -> paramiko.SSHClient:
    """A connected, authenticated, host-key-verified SSHClient. Raises HostKeyUnverified /
    HostKeyMismatch / SSHError. The caller must .close() it."""
    if not data.get("host") or not data.get("username"):
        raise SSHError("The saved server is missing its host or username.")
    pkey = _load_pkey(data)
    if pkey is None and not data.get("password"):
        raise SSHError("The saved server has no password or key to log in with.")
    client = paramiko.SSHClient()
    pinned = data.get("host_key") or None
    if pinned and pinned.get("key_b64"):
        # Load the pinned key as a KNOWN host key: paramiko then (a) asks the server for exactly that key
        # TYPE — so a server offering several types can't trigger a false alarm — and (b) refuses any other
        # key itself (BadHostKeyException, mapped below). `[host]:port` is how it names non-22 ports.
        try:
            key = paramiko.PKey.from_type_string(pinned["type"], base64.b64decode(pinned["key_b64"]))
        except Exception as exc:  # noqa: BLE001
            client.close()
            raise SSHError("The pinned host key stored for this server is unreadable — delete the server in the Vault and add it again.") from exc
        name = data["host"] if int(data.get("port") or 22) == 22 else f"[{data['host']}]:{int(data.get('port') or 22)}"
        client.get_host_keys().add(name, pinned["type"], key)
    client.set_missing_host_key_policy(_PinPolicy(pinned))
    try:
        client.connect(
            hostname=data["host"], port=int(data.get("port") or 22), username=data["username"],
            password=None if pkey else data.get("password"), pkey=pkey, timeout=timeout, banner_timeout=timeout,
            auth_timeout=timeout, allow_agent=False, look_for_keys=False, compress=False,
        )
    except (HostKeyUnverified, HostKeyMismatch):
        client.close()
        raise
    except paramiko.BadHostKeyException as exc:
        client.close()
        raise HostKeyMismatch(fingerprint_sha256(exc.expected_key), fingerprint_sha256(exc.key)) from exc
    except Exception as exc:  # noqa: BLE001 — paramiko/socket raise many types; map to one clean one
        client.close()
        raise _map_error(exc, data) from exc
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(KEEPALIVE_SECONDS)
    return client


def probe_host_key(host: str, port: int = 22, *, timeout: int = CONNECT_TIMEOUT) -> dict[str, str]:
    """Fetch the server's host key WITHOUT logging in (the SSH handshake reveals it first). This is
    what the user is asked to confirm before anything secret is ever sent."""
    sock = None
    transport = None
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.start_client(timeout=timeout)
        return pin_of(transport.get_remote_server_key())
    except Exception as exc:  # noqa: BLE001
        raise _map_error(exc, {"host": host, "port": port, "username": "?"}) from exc
    finally:
        try:
            if transport is not None:
                transport.close()
            elif sock is not None:
                sock.close()
        except Exception:  # noqa: BLE001
            pass


def public_view(secret_id: str, name: str, data: dict[str, Any]) -> dict[str, Any]:
    """What a UI may see about a saved server: everything EXCEPT the secrets."""
    hk = data.get("host_key") or {}
    return {
        "id": secret_id, "name": name, "host": data.get("host"), "port": int(data.get("port") or 22),
        "username": data.get("username"), "auth": data.get("auth", "password"), "read_only": bool(data.get("read_only")),
        "pinned": bool(hk.get("fingerprint")), "fingerprint": hk.get("fingerprint"), "key_type": hk.get("type"),
    }

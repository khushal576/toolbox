"""
mcp_server/ssh_run.py — run ONE already-validated, read-only command on a saved SSH server (ADR D13, roadmap K5).

Uses the shared core.ssh_client (Vault entry → host-key-PINNED connection, no agent, timeouts, scrubbed errors) — the same
path the SSH & SFTP tool uses. No pty, no shell session, no interactive terminal: one `exec` of the command that sshcmd.validate()
rebuilt, with a time limit and an output cap. Nothing here decides WHAT may run (sshcmd + the owner's grant do); it only runs it.
"""

from __future__ import annotations

import time
from typing import Any

from .safety import ToolError


def run_command(data: dict, command: str, *, seconds: int, max_bytes: int) -> dict[str, Any]:
    """{exit_code, stdout, stderr, truncated, timed_out, duration_ms}. `data` is the decrypted Vault entry (stays here)."""
    from core import ssh_client

    t0 = time.monotonic()
    try:
        client = ssh_client.open_client(data, timeout=10)
    except ssh_client.HostKeyUnverified:
        raise ToolError("This server's host key has not been confirmed yet.",
                        hint="The owner must add/confirm the server in the Vault (SSH & SFTP) so its key is pinned before an AI can connect.", refused=True) from None
    except ssh_client.HostKeyMismatch:
        raise ToolError("HOST KEY CHANGED: the server presented a different key than the one pinned in the Vault. Nothing was run.",
                        hint="Do not continue. Tell the owner — this can mean a rebuilt server or a man-in-the-middle.", refused=True) from None
    except ssh_client.SSHError as exc:
        raise ToolError(f"Could not connect: {exc}") from None
    out, err = bytearray(), bytearray()
    truncated = timed_out = False
    exit_code = None
    try:
        transport = client.get_transport()
        chan = transport.open_session(timeout=10)
        # A pseudo-terminal is what makes "stop" real: closing the channel hangs the terminal up and the server's kernel sends SIGHUP to the whole
        # command group. Without it a runaway command keeps running on the server after we give up (observed against a real OpenSSH server).
        # Costs: stdout and stderr arrive merged, lines end in CRLF (normalised below), pagers would wait for a key (sshcmd adds --no-pager).
        chan.get_pty(term="dumb", width=1000, height=50)
        chan.exec_command(command)
        while True:
            got = False
            if chan.recv_ready():
                out += chan.recv(32768)
                got = True
            if chan.recv_stderr_ready():
                err += chan.recv_stderr(32768)
                got = True
            if len(out) + len(err) > max_bytes:
                truncated = True
                break
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
            if time.monotonic() - t0 > seconds:
                timed_out = True
                break
            if not got:
                time.sleep(0.05)
        if chan.exit_status_ready():
            exit_code = chan.recv_exit_status()
        chan.close()
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"The command could not be run: {type(exc).__name__}") from None
    finally:
        client.close()
    cut = lambda b: bytes(b[:max_bytes]).decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "")  # noqa: E731
    return {"exit_code": exit_code, "stdout": cut(out), "stderr": cut(err), "truncated": truncated, "timed_out": timed_out,
            "duration_ms": int((time.monotonic() - t0) * 1000)}

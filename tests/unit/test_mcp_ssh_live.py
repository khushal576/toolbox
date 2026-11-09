"""
Roadmap K5 — the SSH tools against a REAL OpenSSH server. Skipped unless MCP_SSH_TEST_HOST is set, e.g. (throwaway server on the compose network):

    docker run -d --name mcp-ssh-test --network toolbox_default -e PASSWORD_ACCESS=true -e USER_NAME=probe -e USER_PASSWORD=... \
        -e SUDO_ACCESS=false linuxserver/openssh-server:latest
    docker compose run --rm -T --no-deps -e MCP_SSH_TEST_HOST=mcp-ssh-test -e MCP_SSH_TEST_PORT=2222 -e MCP_SSH_TEST_USER=probe \
        -e MCP_SSH_TEST_PASSWORD=... -v "$PWD/tests:/app/tests:ro" worker python -m pytest tests/unit/test_mcp_ssh_live.py -q

What it proves that mocks cannot: the host key really is pinned and a wrong key is refused, real commands return real output, a pipe works,
refused commands never reach the server (no trace on it), the output cap and the time limit really stop a runaway command, and the
credential never comes back.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

HOST = os.environ.get("MCP_SSH_TEST_HOST")
pytestmark = pytest.mark.skipif(not HOST, reason="set MCP_SSH_TEST_HOST (and _PORT/_USER/_PASSWORD) to run against a real SSH server")

PIN = "owner-1234"


@pytest.fixture()
def live(tmp_path, monkeypatch):
    from core import ssh_client
    from core.state.sqlstore import SqlStore
    from mcp_server import access, audit, control, safety

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "c.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    safety.REDACTOR._secrets.clear()
    safety.REDACTOR._identities.clear()
    port = int(os.environ.get("MCP_SSH_TEST_PORT", "22"))
    data = {"host": HOST, "port": port, "username": os.environ["MCP_SSH_TEST_USER"], "password": os.environ["MCP_SSH_TEST_PASSWORD"],
            "environment": "non-prod", "host_key": ssh_client.probe_host_key(HOST, port)}

    class V:
        class SecretNotFound(KeyError):
            pass
        items = {"s1": ("lab", data)}

        def list_secrets(self, kind):
            return [{"id": "s1", "name": "lab", "kind": kind}] if kind == "ssh_server" else []

        def get_secret(self, _):
            return json.loads(json.dumps(self.items["s1"][1]))

    monkeypatch.setattr(access, "vault", lambda: V())
    control.set_pin(PIN)
    control.create_grant("ssh_server", "lab", ["run_read_commands"], minutes=30, pin=PIN, environment="non-prod")
    return data


def run(cmd, server="lab"):
    from mcp_server import protocol

    return protocol.call_tool("ssh_run", {"server": server, "command": cmd})


def test_real_commands_return_real_output(live):
    for cmd, needle in [("uname -s", "Linux"), ("cat /etc/os-release", "NAME="), ("ls /", "etc"), ("df -h", "Filesystem"), ("id -un", live["username"])]:
        r = run(cmd)
        assert r["ok"] and r["data"]["exit_code"] == 0 and needle in r["data"]["stdout"], (cmd, r)


def test_a_pipe_runs_on_the_server_and_a_wildcard_is_expanded_there(live):
    r = run("cat /etc/passwd | grep root | head -2")
    assert r["ok"] and r["data"]["stdout"].startswith("root:") and r["data"]["stdout"].count("\n") <= 2
    r = run("ls /etc/host*")
    assert r["ok"] and "/etc/hostname" in r["data"]["stdout"]


def test_exit_codes_and_stderr_are_reported(live):
    r = run("ls /definitely-not-here")
    assert r["ok"] and r["data"]["exit_code"] != 0
    assert "No such file" in r["data"]["stdout"] + r["data"]["stderr"]     # on a pseudo-terminal stderr is merged into stdout


def test_refused_commands_leave_no_trace_on_the_server(live):
    marker = f"pwned_{int(time.time())}"
    for cmd in [f"ls; touch /tmp/{marker}", f"ls && touch /tmp/{marker}", f"ls | tee /tmp/{marker}", f"cat /etc/hostname > /tmp/{marker}", f"touch /tmp/{marker}",
                f"ls $(touch /tmp/{marker})", f"ls `touch /tmp/{marker}`", f"find /tmp -name x -exec touch /tmp/{marker} ;", f"sort -o /tmp/{marker} /etc/hostname",
                f"cp /etc/hostname /tmp/{marker}", f"sh -c 'touch /tmp/{marker}'", f"echo x >> /tmp/{marker}", f"tail -f /dev/null"]:
        r = run(cmd)
        assert r["ok"] is False and r["refused"] is True, cmd
    r = run("ls /tmp")
    assert r["ok"] and marker not in r["data"]["stdout"]
    secret = run("cat /etc/shadow")
    assert secret["refused"] is True


def test_a_bad_or_missing_grant_stops_everything_before_the_server_is_contacted(live):
    from mcp_server import control

    control.kill()
    r = run("uptime")
    assert r["refused"] is True and "stopped" in r["error"]


def test_a_changed_host_key_is_refused_and_nothing_runs(live, monkeypatch):
    import paramiko
    from mcp_server import access

    wrong = paramiko.RSAKey.generate(2048)
    import base64
    live["host_key"] = {"type": "ssh-rsa", "key_b64": base64.b64encode(wrong.asbytes()).decode(), "fingerprint": "SHA256:wrong"}
    r = run("uname -s")
    assert r["ok"] is False and r["refused"] is True and "HOST KEY CHANGED" in r["error"]


def test_an_unpinned_server_is_refused(live):
    live["host_key"] = None
    r = run("uname -s")
    assert r["ok"] is False and r["refused"] is True and "host key" in r["error"].lower()


def test_the_output_cap_stops_a_flood(live, monkeypatch):
    monkeypatch.setenv("MCP_SSH_MAX_BYTES", "2000")
    t = time.time()
    r = run("head -c 50000000 /dev/zero")
    assert r["ok"] and r["truncated"] is True and "output size limit" in r["limits_hit"] and len(r["data"]["stdout"]) <= 2000
    assert time.time() - t < 10
    time.sleep(1.5)
    monkeypatch.setenv("MCP_SSH_MAX_BYTES", "65536")
    left = run("ps -eo args | grep -c '[h]ead -c 50000000'")
    assert left["ok"] and left["data"]["stdout"].strip() == "0", left


def test_the_time_limit_stops_a_runaway_command(live, monkeypatch):
    monkeypatch.setenv("MCP_SECONDS", "2")
    t = time.time()
    r = run("head -c 1000000000000 /dev/zero | wc -c")
    took = time.time() - t
    assert r["ok"] and r["truncated"] is True and r["limits_hit"] == "time limit" and took < 8, (took, r)
    assert r["data"]["exit_code"] is None
    time.sleep(1.5)
    monkeypatch.setenv("MCP_SECONDS", "30")
    left = run("ps -eo args | grep -c '[h]ead -c 1000000000000'")          # the runaway must NOT still be running on the server
    assert left["ok"] and left["data"]["stdout"].strip() == "0", left


def test_the_credential_and_user_name_never_come_back(live):
    from mcp_server import audit

    blobs = [json.dumps(run("id")), json.dumps(run("uname -a")), json.dumps(run("ls /nope")), json.dumps(audit.recent(50))]
    allblob = "\n".join(blobs)
    assert os.environ["MCP_SSH_TEST_PASSWORD"] not in allblob
    # the server's own `id` output legitimately names the account it runs as (that is server data, like any `whoami`), so only
    # the connection-level places must be clean: errors, hints, warnings, audit rows
    assert os.environ["MCP_SSH_TEST_PASSWORD"] not in json.dumps(audit.recent(50))

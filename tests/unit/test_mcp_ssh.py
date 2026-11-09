"""
Roadmap K5 — the SSH tools (ssh_servers, ssh_run). The connection itself is replaced by a recording fake here; the real thing
(a real OpenSSH server, host-key pinning, real attacks) is tested by test_mcp_ssh_live.py (set MCP_SSH_TEST_HOST to run it).

Defended: no command reaches a server unless (1) the allow-list accepts it AND (2) the owner granted THAT server; the credential
and user name never leave the process; prod / unlabelled servers get tighter limits; output is scrubbed; everything is audited.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from mcp_server import access, audit, control, protocol, ssh_run, tools  # noqa: E402
from mcp_server.safety import ToolError  # noqa: E402

PIN = "owner-1234"
SECRET = "Canary-ssh-pw-777"
KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHI\n-----END OPENSSH PRIVATE KEY-----"


class FakeVault:
    class SecretNotFound(KeyError):
        pass

    def __init__(self):
        base = {"host": "10.0.0.5", "port": 22, "username": "deploy_user", "password": SECRET, "private_key": KEY,
                "host_key": {"type": "ssh-ed25519", "key_b64": "AAAA", "fingerprint": "SHA256:x"}}
        self.items = {"s1": ("web-1", {**base, "environment": "non-prod"}), "s2": ("db-prod", {**base, "environment": "prod"}),
                      "s3": ("legacy", dict(base)), "s4": ("fresh", {**base, "host_key": None, "environment": "non-prod"})}

    def list_secrets(self, kind):
        return [{"id": i, "name": n, "kind": kind} for i, (n, _) in self.items.items()] if kind == "ssh_server" else []

    def get_secret(self, secret_id):
        return json.loads(json.dumps(self.items[secret_id][1]))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "c.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    monkeypatch.setattr(access, "vault", lambda: FakeVault())
    from mcp_server import safety
    safety.REDACTOR._secrets.clear()
    safety.REDACTOR._identities.clear()
    control.set_pin(PIN)
    calls = []

    def fake_run(data, command, *, seconds, max_bytes):
        calls.append({"command": command, "seconds": seconds, "max_bytes": max_bytes, "host": data["host"]})
        return {"exit_code": 0, "stdout": "line1\nDB_PASSWORD=hunter2\nline3\n", "stderr": "", "truncated": False, "timed_out": False, "duration_ms": 12}

    monkeypatch.setattr(ssh_run, "run_command", fake_run)
    return calls


def allow(server="web-1", **kw):
    return control.create_grant("ssh_server", server, ["run_read_commands"], minutes=30, pin=PIN,
                                environment=kw.pop("environment", "non-prod"), confirm_prod=kw.pop("confirm_prod", False))


def run(server, command):
    return protocol.call_tool("ssh_run", {"server": server, "command": command})


# ------------------------------------------------------------------------------------------------------------ the gates

def test_nothing_runs_without_the_owners_grant(env):
    r = run("web-1", "ls /var/log")
    assert r["ok"] is False and r["refused"] is True and not env
    assert "AI Access" in r["hint"] and "cannot grant this yourself" in r["hint"]


def test_a_grant_for_one_server_does_not_open_another(env):
    allow("web-1")
    assert run("web-1", "uptime")["ok"] is True
    other = run("legacy", "uptime")
    assert other["ok"] is False and other["refused"] and len(env) == 1


def test_a_forbidden_command_is_refused_before_anything_else_even_with_a_grant(env):
    allow("web-1")
    for cmd in ["rm -rf /", "ls; id", "cat /etc/shadow", "tail -f /var/log/x", "sudo ls", "ls > /tmp/x", "docker exec c sh"]:
        r = run("web-1", cmd)
        assert r["ok"] is False and r["refused"] is True and "Command not allowed" in r["error"], cmd
    assert env == []                                                              # the fake connection was never used


def test_the_command_is_checked_even_when_the_server_is_unknown_or_ungranted(env):
    r = run("nope", "rm -rf /")
    assert "Command not allowed" in r["error"]                                    # checked first: cheap and stateless
    r = run("nope", "ls")
    assert "no saved SSH server" in r["error"] and "web-1" in r["hint"] and "deploy_user" not in json.dumps(r)


def test_revoking_or_stopping_takes_effect_on_the_next_call(env):
    g = allow("web-1")
    assert run("web-1", "df -h")["ok"]
    control.revoke(g["id"])
    assert run("web-1", "df -h")["refused"] is True
    allow("web-1")
    control.kill()
    assert "stopped" in run("web-1", "df -h")["error"]


def test_only_read_commands_exist_in_the_grant_vocabulary():
    assert set(control.ACTIONS["ssh_server"]) == {"run_read_commands"}            # no write commands over SSH in this version
    with pytest.raises(control.ControlError):
        control.create_grant("ssh_server", "web-1", ["run_write_commands"], minutes=5, pin=PIN, environment="non-prod")


# ------------------------------------------------------------------------------------------------------------ what is run / returned

def test_the_rebuilt_command_is_what_reaches_the_server(env):
    allow("web-1")
    r = run("web-1", "grep   -i 'a b'  /var/log/x|head -5")
    assert r["ok"] and env[0]["command"] == "grep -i 'a b' /var/log/x | head -5" and r["data"]["command"] == env[0]["command"]


def test_output_is_scrubbed_and_the_credential_never_appears(env):
    allow("web-1")
    r = run("web-1", "cat /var/log/app.log")
    blob = json.dumps(r)
    assert "hunter2" not in blob and "DB_PASSWORD=[redacted]" in r["data"]["stdout"] and any("replaced" in w for w in r["warnings"])
    for secret in (SECRET, "deploy_user", "b3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHI", "10.0.0.5:22"):
        assert secret not in blob.replace("10.0.0.5", "") or secret == "10.0.0.5:22"


def test_server_listing_shows_labels_and_grant_state_without_credentials(env):
    allow("web-1")
    r = protocol.call_tool("ssh_servers", {})
    servers = {s["name"]: s for s in r["data"]["servers"]}
    assert servers["web-1"]["environment"] == "non-prod" and servers["web-1"]["ai_commands"].startswith("ON")
    assert servers["db-prod"]["environment"] == "prod" and servers["db-prod"]["ai_commands"].startswith("OFF")
    assert servers["legacy"]["environment"] == "unknown" and servers["fresh"]["host_key_pinned"] is False
    blob = json.dumps(r)
    for secret in (SECRET, "deploy_user", "b3BlbnNz", "key_b64", "AAAA", "password", "private_key"):
        assert secret not in blob, secret


def test_prod_and_unlabelled_servers_get_tighter_limits_and_a_warning(env):
    allow("web-1")
    control.create_grant("ssh_server", "db-prod", ["run_read_commands"], minutes=30, pin=PIN, environment="prod", confirm_prod=True)
    control.create_grant("ssh_server", "legacy", ["run_read_commands"], minutes=30, pin=PIN, environment="unknown", confirm_prod=True)
    for name in ("web-1", "db-prod", "legacy"):
        run(name, "uptime")
    assert [(c["seconds"], c["max_bytes"]) for c in env] == [(30, 65536), (15, 32768), (15, 32768)]
    r = run("db-prod", "uptime")
    assert r["connections"][0]["environment"] == "prod" and any("PROD" in w for w in r["warnings"])
    assert "NOT SET" in " ".join(run("legacy", "uptime")["warnings"])


def test_a_grant_for_a_prod_server_needs_the_explicit_confirmation(env):
    with pytest.raises(control.ControlError):
        control.create_grant("ssh_server", "db-prod", ["run_read_commands"], minutes=5, pin=PIN, environment="prod")


def test_timeouts_and_truncation_are_announced(env, monkeypatch):
    allow("web-1")
    monkeypatch.setattr(ssh_run, "run_command", lambda *a, **k: {"exit_code": None, "stdout": "partial", "stderr": "", "truncated": True, "timed_out": True, "duration_ms": 30000})
    r = run("web-1", "cat /var/log/huge")
    assert r["ok"] and r["truncated"] is True and r["limits_hit"] == "time limit"
    assert any("stopped after" in w for w in r["warnings"]) and any("cut at" in w for w in r["warnings"])


def test_connection_failures_are_refusals_or_plain_errors_with_the_label(env, monkeypatch):
    allow("web-1")

    def deny(*a, **k):
        raise ToolError("HOST KEY CHANGED: the server presented a different key than the one pinned in the Vault. Nothing was run.", refused=True)

    monkeypatch.setattr(ssh_run, "run_command", deny)
    r = run("web-1", "uptime")
    assert r["refused"] is True and "HOST KEY CHANGED" in r["error"] and r["connections"][0]["name"] == "web-1"


# ------------------------------------------------------------------------------------------------------------ audit + AI's side

def test_every_attempt_is_audited_with_the_exact_command_and_the_grant(env):
    g = allow("web-1")
    run("web-1", "ps aux | grep nginx")
    run("web-1", "rm -rf /")
    rows = audit.recent(10)
    ok = next(r for r in rows if r["outcome"] == "ok")
    refused = next(r for r in rows if r["outcome"] == "refused")
    assert ok["tool"] == "ssh_run" and ok["connection"] == "web-1" and ok["environment"] == "non-prod" and ok["grant_id"] == g["id"]
    assert "ps aux" in ok["args"] and "rm -rf /" in refused["args"] and refused["grant_id"] is None
    assert SECRET not in json.dumps(rows) and "deploy_user" not in json.dumps(rows)


def test_the_ai_cannot_widen_its_own_rights_through_ssh_run():
    src = (REPO / "mcp_server" / "tools.py").read_text()
    seg = src[src.index("def ssh_run("):src.index("# ----------------------------------------------------------------------------------------------------", src.index("def ssh_run("))]
    for forbidden in ("create_grant", "set_pin", "control.kill", "control.resume", "revoke"):
        assert forbidden not in seg
    assert "control.require(" in seg and seg.index("sshcmd.validate") < seg.index("control.require") < seg.index("runner.run_command")


def test_ssh_run_schema_accepts_only_server_and_command():
    t = tools.REGISTRY["ssh_run"]
    assert set(t.schema["properties"]) == {"server", "command"} and t.schema["additionalProperties"] is False

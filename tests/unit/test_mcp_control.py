"""
Roadmap K4 — owner grants, PIN, kill switch (docs/architecture/ADR-MCP.md D12).

The promise defended here: the AI changes nothing unless the OWNER allowed that exact thing, for a limited time, with a PIN only the
owner knows — and the owner can stop everything instantly, without a PIN.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from mcp_server import audit, control, protocol, tools  # noqa: E402
from mcp_server.control import ControlError  # noqa: E402
from mcp_server.safety import ToolError  # noqa: E402

PIN = "owner-1234"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "c.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    return store


@pytest.fixture()
def pinned(db):
    control.set_pin(PIN)
    return PIN


def grant(**kw):
    base = dict(target_kind="workspace", target="scratch", actions=["create_table"], minutes=30, pin=PIN, environment="non-prod")
    base.update(kw)
    return control.create_grant(base.pop("target_kind"), base.pop("target"), base.pop("actions"), **base)


# ------------------------------------------------------------------------------------------------------------ vocabulary

def test_no_action_can_delete_drop_or_truncate():
    words = " ".join(a + " " + d for acts in control.ACTIONS.values() for a, d in acts.items()).lower()
    for bad in ("delete", "drop", "truncate", "destroy", "remove", "grant", "admin", "owner"):
        assert bad not in words.replace("replace a table (the old data is kept as a backup table)", "")


# ------------------------------------------------------------------------------------------------------------ PIN

def test_pin_rules(db):
    assert not control.pin_is_set()
    with pytest.raises(ControlError):
        control.resume("anything")                                   # nothing to verify against
    for weak in ("", "123", "aaaaaa", "ababab", None):
        with pytest.raises(ControlError):
            control.set_pin(weak)
    control.set_pin(PIN)
    assert control.pin_is_set()
    stored = control._get("pin_hash")
    assert PIN not in stored and stored.startswith("scrypt$")        # only a salted hash is kept


def test_changing_the_pin_needs_the_old_one(pinned):
    with pytest.raises(ControlError):
        control.set_pin("new-pin-99")
    with pytest.raises(ControlError):
        control.set_pin("new-pin-99", old="wrong-guess")
    control.set_pin("new-pin-99", old=PIN)
    control.verify_pin("new-pin-99")
    with pytest.raises(ControlError):
        control.verify_pin(PIN)


def test_five_wrong_pins_lock_it_and_the_right_one_is_then_refused(pinned):
    for i in range(4):
        with pytest.raises(ControlError) as e:
            control.verify_pin("nope-nope")
        assert f"{4 - i} tries left" in str(e.value)
    with pytest.raises(ControlError) as e:
        control.verify_pin("nope-nope")
    assert "Locked" in str(e.value)
    with pytest.raises(ControlError) as e:
        control.verify_pin(PIN)                                      # even the right PIN waits
    assert "Too many wrong PINs" in str(e.value)


def test_a_right_pin_resets_the_failure_count(pinned):
    for _ in range(3):
        with pytest.raises(ControlError):
            control.verify_pin("nope-nope")
    control.verify_pin(PIN)
    for _ in range(4):
        with pytest.raises(ControlError):
            control.verify_pin("nope-nope")
    control.verify_pin(PIN)                                          # not locked: the counter restarted


def test_lock_expires(pinned, monkeypatch):
    for _ in range(5):
        with pytest.raises(ControlError):
            control.verify_pin("nope-nope")
    later = datetime.now(timezone.utc) + timedelta(minutes=control.PIN_LOCK_MINUTES + 1)
    monkeypatch.setattr(control, "_now", lambda: later)
    control.verify_pin(PIN)


# ------------------------------------------------------------------------------------------------------------ grants

def test_a_grant_needs_the_pin_and_valid_input(pinned):
    with pytest.raises(ControlError):
        grant(pin="wrong-pin")
    for kw in [dict(target_kind="database"), dict(target=""), dict(actions=[]), dict(actions=["delete_rows"]),
               dict(actions=["insert_rows"]),                         # a connection action on a workspace
               dict(minutes=0), dict(minutes=control.MAX_MINUTES + 1), dict(minutes="soon"), dict(row_limit=0), dict(row_limit="many")]:
        with pytest.raises(ControlError):
            grant(**kw)
    assert control.list_grants() == []                               # nothing was created by any failed attempt


def test_no_pin_set_means_no_grants(db):
    with pytest.raises(ControlError) as e:
        grant()
    assert "No PIN" in str(e.value)


def test_grant_is_stored_with_an_expiry_and_found_only_for_its_exact_target_and_action(pinned):
    g = grant(actions=["create_table", "append_rows"], row_limit=1000, note="load test data")
    assert g["active"] and 29 * 60 <= g["seconds_left"] <= 30 * 60 and g["created_via"] == "ui" and g["row_limit"] == 1000
    assert control.active_grant("workspace", "scratch", "create_table")["id"] == g["id"]
    assert control.active_grant("workspace", "scratch", "append_rows")
    assert control.active_grant("workspace", "scratch", "replace_table") is None     # not granted
    assert control.active_grant("workspace", "other", "create_table") is None        # other target
    assert control.active_grant("connection", "scratch", "insert_rows") is None      # other kind


def test_grants_expire(pinned, monkeypatch):
    grant(minutes=5)
    assert control.active_grant("workspace", "scratch", "create_table")
    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    monkeypatch.setattr(control, "_now", lambda: later)
    assert control.active_grant("workspace", "scratch", "create_table") is None
    assert control.list_grants() == [] and len(control.list_grants(active_only=False)) == 1


def test_revoking_needs_no_pin_and_is_immediate(pinned):
    g = grant()
    assert control.revoke(g["id"]) is True
    assert control.active_grant("workspace", "scratch", "create_table") is None
    assert control.revoke(g["id"]) is False                                          # already ended


def test_prod_and_unlabelled_targets_need_an_explicit_confirmation(pinned):
    for env in ("prod", "unknown", None):
        with pytest.raises(ControlError) as e:
            grant(target_kind="connection", target="shop", actions=["insert_rows"], environment=env)
        assert "PROD" in str(e.value)
    assert grant(target_kind="connection", target="dev", actions=["insert_rows"], environment="non-prod")["active"]
    assert grant(target_kind="connection", target="shop", actions=["insert_rows"], environment="prod", confirm_prod=True)["active"]


# ------------------------------------------------------------------------------------------------------------ kill switch

def test_kill_blocks_everything_revokes_grants_and_needs_the_pin_to_undo(pinned):
    grant(), grant(target="scratch2")
    assert control.is_killed() is False
    assert control.kill() == 2                                       # no PIN asked: anyone may stop
    assert control.is_killed() is True and control.list_grants() == []
    with pytest.raises(ControlError):
        grant()                                                      # no new grants while stopped
    with pytest.raises(ControlError):
        control.resume("wrong-pin")
    assert control.is_killed() is True
    control.resume(PIN)
    assert control.is_killed() is False and control.list_grants() == []   # resumed READ-ONLY: the old grants stay revoked


def test_unreadable_control_state_fails_closed(db, monkeypatch):
    monkeypatch.setattr(control, "_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(control.ControlUnavailable):
        control.is_killed()
    with pytest.raises(ToolError) as e:
        control.require("workspace", "scratch", "create_table")
    assert e.value.refused


# ------------------------------------------------------------------------------------------------------------ require()

def test_require_is_the_gate_for_every_write_tool(pinned):
    with pytest.raises(ToolError) as e:
        control.require("workspace", "scratch", "create_table")
    err = e.value
    assert err.refused and "AI Access" in err.hint and "cannot grant this yourself" in err.hint
    g = grant(row_limit=100)
    assert control.require("workspace", "scratch", "create_table", rows=100)["id"] == g["id"]
    with pytest.raises(ToolError) as e:
        control.require("workspace", "scratch", "create_table", rows=101)
    assert "at most 100" in str(e.value)
    with pytest.raises(ToolError):
        control.require("workspace", "scratch", "drop_table")                       # unknown action
    control.kill()
    with pytest.raises(ToolError) as e:
        control.require("workspace", "scratch", "create_table")
    assert "stopped" in str(e.value)


# ------------------------------------------------------------------------------------------------------------ through the protocol

def test_kill_switch_blocks_even_reads_and_the_attempt_is_logged(pinned, monkeypatch):
    monkeypatch.setitem(tools.REGISTRY, "vault_list", tools.Tool("vault_list", "t", "d", {"type": "object"}, lambda a: tools.Result({"ok": 1})))
    assert protocol.call_tool("vault_list", {})["ok"] is True
    control.kill()
    env = protocol.call_tool("vault_list", {})
    assert env["ok"] is False and env["refused"] is True and "stopped by the owner" in env["error"]
    last = audit.recent(1)[0]
    assert last["outcome"] == "refused" and "stopped" in last["detail"]
    control.resume(PIN)
    assert protocol.call_tool("vault_list", {})["ok"] is True


def test_tool_never_runs_when_the_kill_flag_cannot_be_read(db, monkeypatch):
    ran = []
    monkeypatch.setitem(tools.REGISTRY, "vault_list", tools.Tool("vault_list", "t", "d", {"type": "object"}, lambda a: ran.append(1) or tools.Result({})))
    monkeypatch.setattr(control, "is_killed", lambda: (_ for _ in ()).throw(control.ControlUnavailable("the control flag cannot be read, so nothing was run")))
    env = protocol.call_tool("vault_list", {})
    assert env["ok"] is False and env["refused"] and not ran


def test_a_write_tool_is_gated_by_the_grant_end_to_end(pinned, monkeypatch):
    """A stand-in write tool that calls control.require like K5/K6 will."""
    done = []

    def fake_write(args):
        control.require("workspace", args["workspace"], "create_table", rows=args.get("rows"))
        done.append(args["workspace"])
        return tools.Result({"created": True})

    monkeypatch.setitem(tools.REGISTRY, "vault_list", tools.Tool("vault_list", "t", "d", {"type": "object"}, fake_write))
    assert protocol.call_tool("vault_list", {"workspace": "scratch"})["refused"] is True and not done
    grant()
    assert protocol.call_tool("vault_list", {"workspace": "scratch"})["ok"] is True and done == ["scratch"]
    assert protocol.call_tool("vault_list", {"workspace": "elsewhere"})["refused"] is True       # grant is for ONE target
    control.revoke(control.list_grants()[0]["id"])
    assert protocol.call_tool("vault_list", {"workspace": "scratch"})["refused"] is True


# ------------------------------------------------------------------------------------------------------------ the AI's side

def test_the_ai_has_no_path_to_create_or_widen_a_grant():
    src = (REPO / "mcp_server" / "tools.py").read_text()
    for forbidden in ("create_grant", "set_pin", "verify_pin", "control.resume", "control.kill", "control.revoke", "_set(", "pin_hash"):
        assert forbidden not in src, forbidden
    names = [t["name"] for t in protocol.rpc_tools()] if hasattr(protocol, "rpc_tools") else list(tools.REGISTRY)
    assert not any(re.search(r"grant|pin|kill|resume|revoke|owner", n) for n in names), names
    for t in tools.REGISTRY.values():                                   # nothing in a schema accepts a pin / grant either
        assert not re.search(r"pin|grant|expires|minutes", json.dumps(t.schema), re.I), t.name


def test_access_status_tells_the_ai_the_truth_without_secrets(pinned):
    env = protocol.call_tool("access_status", {})
    assert env["ok"] and env["data"]["mode"] == "read-only" and env["data"]["active_grants"] == []
    grant(actions=["append_rows"])
    env = protocol.call_tool("access_status", {})
    assert env["data"]["mode"] == "read-only + owner grants"
    g = env["data"]["active_grants"][0]
    assert g["target"] == "scratch" and g["actions"] == ["append_rows"] and g["seconds_left"] > 0
    blob = json.dumps(env)
    assert "pin_hash" not in blob and "scrypt" not in blob and PIN not in blob
    control.kill()
    assert protocol.call_tool("access_status", {})["refused"] is True      # while stopped even this is refused


def test_status_has_no_pin_material(pinned):
    assert set(control.status()) == {"stopped", "pin_set", "grants"}

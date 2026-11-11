"""Plan cards (roadmap H4, mcp_server/approvals.py): the AI's refused save becomes a card; only the owner's click + PIN turns it into a
SINGLE-USE grant; the AI cannot approve; Reject writes nothing. Host-level: table loading and writing are stubbed."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from mcp_server import approvals, audit, control, frame, protocol, tools  # noqa: E402

PIN = "owner-1234"
TBL = {"full_name": "system.src", "version": 1, "row_count": 4}
ARGS = {"table": "system.src", "steps": [{"op": "dedupe"}], "save_as": "scratch.out"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from core import lake as real_lake
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "c.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    control.set_pin(PIN)
    df = pd.DataFrame({"id": [1, 2, 3, 3], "name": ["a", "b", "c", "c"]})
    monkeypatch.setattr(frame, "load", lambda ref: (df, TBL))
    wrote = []
    monkeypatch.setattr(frame, "write_result", lambda *a, **k: wrote.append(a[1:3]) or {"backup": None, "read_back": {"ok": True, "rows": 3, "rows_match": True, "columns_match": True}})

    class FakeLake:
        def get_table(self, ws, name):
            raise real_lake.NotFound("no")

    monkeypatch.setattr(real_lake, "scoped", lambda p: FakeLake())
    return wrote


def call(**extra):
    return protocol.call_tool("table_transform", {**ARGS, **extra})


def test_a_refused_save_becomes_one_pending_card_with_the_facts(env):
    r = call()
    assert r["ok"] is False and r["refused"] is True and "cannot grant this yourself" in r["hint"] and "approval card" in r["hint"]
    call(); call()                                                          # asking again does not pile up cards
    cards = approvals.list_cards()
    assert len(cards) == 1 and cards[0]["status"] == "pending"
    p = cards[0]["plan"]
    assert p["target"] == "scratch.out" and p["rows"] == 3 and p["environment"] == "non-prod" and p["source"] == "system.src" and p["columns"] == ["id", "name"]
    assert cards[0]["action"] == "create_table" and not env


def test_nothing_is_granted_by_the_request_itself(env):
    call()
    assert control.list_grants(True) == [] and not env


def test_approve_needs_the_pin_and_makes_a_short_single_action_grant(env):
    call()
    cid = approvals.list_cards()[0]["id"]
    with pytest.raises(control.ControlError):
        approvals.approve(cid, "wrong-pin-1")
    assert control.list_grants(True) == []
    out = approvals.approve(cid, PIN)
    g = out["grant"]
    assert g["created_via"] == "card" and g["actions"] == ["create_table"] and g["target"] == "scratch" and g["row_limit"] == 3 and g["seconds_left"] <= 600
    with pytest.raises(control.ControlError):                              # a card cannot be approved twice
        approvals.approve(cid, PIN)


def test_after_approval_the_same_call_saves_once_and_the_grant_is_spent(env):
    call()
    approvals.approve(approvals.list_cards()[0]["id"], PIN)
    dry = call()
    assert dry["ok"] and dry["data"]["dry_run"] is True and not env
    done = call(confirm_code=dry["data"]["confirm_code"])
    assert done["ok"] and done["data"]["saved"] is True and env == [("scratch", "out")]
    assert control.list_grants(True) == []                                  # single use: the grant ended with the write
    assert approvals.list_cards()[0]["status"] == "used"
    again = call()                                                          # a second save needs a new card
    assert again["ok"] is False and again["refused"] is True


def test_reject_writes_nothing_and_tells_the_ai_not_to_ask_again(env):
    call()
    cid = approvals.list_cards()[0]["id"]
    assert approvals.reject(cid) is True
    r = call()
    assert r["ok"] is False and "said no" in r["error"] and not env and control.list_grants(True) == []
    with pytest.raises(control.ControlError):
        approvals.approve(cid, PIN)


def test_a_card_grant_does_not_cover_anything_else(env):
    call()
    approvals.approve(approvals.list_cards()[0]["id"], PIN)
    assert control.active_grant("workspace", "scratch", "replace_table") is None
    assert control.active_grant("workspace", "other", "create_table") is None
    r = call(save_as="other.out")                                           # a different target is refused (and gets its own card)
    assert r["ok"] is False and r["refused"] is True


def test_row_limit_of_the_card_is_enforced(env):
    call()
    approvals.approve(approvals.list_cards()[0]["id"], PIN)
    r = call(steps=[{"op": "clean_text", "columns": ["name"], "ops": ["strip"]}])      # a different plan with 4 rows: more than the 3 that were approved
    assert r["ok"] is False and "at most 3" in r["error"] and not env


def test_stopped_ai_access_creates_no_card(env):
    control.kill("test")
    r = call()
    assert r["ok"] is False and approvals.list_cards() == []


def test_expired_cards_cannot_be_approved(env, monkeypatch):
    call()
    cid = approvals.list_cards()[0]["id"]
    with audit._connect() as con:
        con.execute("UPDATE approvals SET expires_at = '2000-01-01T00:00:00.000+00:00' WHERE id = ?", (cid,))
    assert approvals.list_cards() == []
    with pytest.raises(control.ControlError):
        approvals.approve(cid, PIN)


def test_pending_cards_are_capped(env):
    for i in range(approvals.MAX_PENDING + 3):
        approvals.ask_owner("table_transform", "workspace", f"w{i}", "create_table", {"rows": 1}, f"digest{i}")
    assert len(approvals.list_cards()) == approvals.MAX_PENDING


def test_the_ai_side_can_only_ask_and_spend():
    src = (REPO / "mcp_server" / "tools.py").read_text()
    for forbidden in ("approvals.approve", "approvals.reject", "approvals.list_cards", "create_grant"):
        assert forbidden not in src, forbidden
    assert set(re.findall(r"approvals\.(\w+)", src)) == {"ask_owner", "spend"}
    for t in tools.REGISTRY.values():
        assert not re.search(r"approv", t.name + " " + str(t.schema), re.I), t.name


def test_a_grant_from_the_owners_pages_is_not_spent_by_a_write():
    g = {"id": "abc", "created_via": "ui"}
    assert approvals.spend(g) is False

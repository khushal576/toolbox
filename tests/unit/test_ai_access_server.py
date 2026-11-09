"""
Roadmap K4, part 2 — the AI Access page's HTTP layer (ai-access/server.py).

Defended: stopping and revoking need no PIN; granting, resuming and changing the PIN do; the environment of a target comes from the
Vault (never from the browser); no secret and no PIN material is ever returned; prod / unlabelled targets need an explicit tick;
a database outage reads as "stopped", not as "allowed".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from mcp_server import audit, control, protocol, tools  # noqa: E402

PIN = "owner-1234"
SECRET = "Canary-pw-5555"


class FakeVault:
    def __init__(self):
        base = {"host": "h", "port": 5432, "database": "d", "username": "svc", "password": SECRET}
        self.items = {"c1": ("dev-db", "postgres_connection", {**base, "environment": "non-prod"}),
                      "c2": ("shop", "postgres_connection", {**base, "environment": "prod"}),
                      "c3": ("legacy", "postgres_connection", dict(base)),
                      "s1": ("web-1", "ssh_server", {"host": "x", "password": SECRET})}

    def list_secrets(self, kind):
        return [{"id": i, "name": n, "kind": k} for i, (n, k, _) in self.items.items() if k == kind]

    def get_secret(self, secret_id):
        return dict(self.items[secret_id][2])


class FakeLake:
    def list_workspaces(self):
        return [{"name": "system"}, {"name": "scratch"}]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from core import lake as lake_store
    from core import vault as vault_store
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "c.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    monkeypatch.setattr(vault_store, "scoped", lambda plugin: FakeVault())
    monkeypatch.setattr(lake_store, "scoped", lambda plugin: FakeLake())
    folder = REPO / "ai-access" if (REPO / "ai-access").exists() else REPO / "ai_access"      # the image names the folder ai_access
    spec = importlib.util.spec_from_file_location("ai_access_server_under_test", folder / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return TestClient(mod.app)


def post(c, path, **body):
    return c.post(path, json=body)


@pytest.fixture()
def ready(client):
    assert post(client, "/pin", new=PIN).json()["ok"]
    return client


def grant(c, **kw):
    body = dict(target_kind="workspace", target="scratch", actions=["create_table"], minutes=30, pin=PIN)
    body.update(kw)
    return post(c, "/grants", **body)


# ------------------------------------------------------------------------------------------------------------ status

def test_the_page_is_served():
    spec = ((REPO / "ai-access") if (REPO / "ai-access").exists() else (REPO / "ai_access")).joinpath("ui", "index.html").read_text()
    assert "<title>AI Access</title>" in spec and "Stop AI access now" in spec


def test_status_lists_names_and_labels_only(client):
    r = client.get("/status").json()
    assert r["ok"] and r["stopped"] is False and r["pin_set"] is False and r["grants"] == []
    assert {t["name"]: t["environment"] for t in r["targets"]["connection"]} == {"dev-db": "non-prod", "shop": "prod", "legacy": "unknown"}
    assert [t["name"] for t in r["targets"]["workspace"]] == ["system", "scratch"] and r["targets"]["ssh_server"][0]["name"] == "web-1"
    blob = json.dumps(r)
    assert SECRET not in blob and "svc" not in blob and "scrypt" not in blob and "pin_hash" not in blob
    assert "delete" not in json.dumps(r["actions"]).lower()


# ------------------------------------------------------------------------------------------------------------ PIN + grants

def test_no_grant_without_a_pin_or_with_a_wrong_one(client):
    r = grant(client)
    assert r.status_code == 400 and "No PIN" in r.json()["error"]
    assert post(client, "/pin", new="abc").status_code == 400
    assert post(client, "/pin", new=PIN).json()["ok"]
    assert post(client, "/pin", new="another-pin-1").status_code == 400            # replacing needs the old PIN
    r = grant(client, pin="not-it")
    assert r.status_code == 400 and "Wrong PIN" in r.json()["error"] and client.get("/status").json()["grants"] == []


def test_a_grant_round_trip_and_revoke_without_pin(ready):
    g = grant(ready, actions=["create_table", "append_rows"], row_limit=500, note="load").json()["grant"]
    st = ready.get("/status").json()
    assert [x["id"] for x in st["grants"]] == [g["id"]] and st["grants"][0]["row_limit"] == 500
    assert ready.post(f"/grants/{g['id']}/revoke").json() == {"ok": True, "revoked": True}   # no PIN in that call
    assert ready.get("/status").json()["grants"] == []
    assert ready.post("/grants/not-a-grant/revoke").status_code == 404


def test_environment_comes_from_the_vault_not_from_the_browser(ready):
    # the browser cannot claim a target is non-prod: the field is not even read
    r = grant(ready, target_kind="connection", target="shop", actions=["insert_rows"], environment="non-prod")
    assert r.status_code == 400 and "PROD" in r.json()["error"]
    r = grant(ready, target_kind="connection", target="legacy", actions=["insert_rows"])
    assert r.status_code == 400 and "not labelled" in r.json()["error"]
    assert grant(ready, target_kind="connection", target="dev-db", actions=["insert_rows"]).json()["ok"]
    g = grant(ready, target_kind="connection", target="shop", actions=["insert_rows"], confirm_prod=True).json()["grant"]
    assert g["environment"] == "prod"


def test_unknown_targets_and_bad_names_are_refused(ready):
    assert "no saved connection" in grant(ready, target_kind="connection", target="typo", actions=["insert_rows"]).json()["error"].lower()
    assert grant(ready, target_kind="workspace", target="Bad Name!", actions=["create_table"]).status_code == 400
    assert grant(ready, target_kind="nonsense", target="x", actions=["create_table"]).status_code == 400
    assert grant(ready, actions=["delete_everything"]).status_code == 400


# ------------------------------------------------------------------------------------------------------------ kill switch

def test_stop_needs_no_pin_and_resume_needs_it(ready):
    grant(ready)
    r = ready.post("/kill").json()
    assert r == {"ok": True, "revoked": 1}
    st = ready.get("/status").json()
    assert st["stopped"] is True and st["grants"] == []
    assert "stopped" in grant(ready).json()["error"].lower()                        # no new grants while stopped
    assert post(ready, "/resume", pin="wrong").status_code == 400
    assert ready.get("/status").json()["stopped"] is True
    assert post(ready, "/resume", pin=PIN).json()["ok"]
    assert ready.get("/status").json()["stopped"] is False


def test_stop_works_even_before_a_pin_exists(client):
    assert client.post("/kill").json()["ok"] is True and client.get("/status").json()["stopped"] is True


def test_a_database_outage_reads_as_stopped_never_as_allowed(client, monkeypatch):
    monkeypatch.setattr(control, "status", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    r = client.get("/status")
    assert r.status_code == 503 and "stopped" in r.json()["error"]


# ------------------------------------------------------------------------------------------------------------ timeline

def test_calls_show_what_the_ai_did_without_results_or_secrets(ready, monkeypatch):
    monkeypatch.setitem(tools.REGISTRY, "vault_list", tools.Tool("vault_list", "t", "d", {"type": "object"},
                                                                 lambda a: tools.Result({"secret_rows": [[SECRET]]}, rows=4)))
    protocol.call_tool("vault_list", {"what": "tables", "password": SECRET})
    protocol.call_tool("nonexistent_tool", {})
    control.kill()
    protocol.call_tool("vault_list", {})
    allc = ready.get("/calls").json()["calls"]
    assert [c["outcome"] for c in allc] == ["refused", "ok"] and allc[0]["detail"].startswith("AI access is stopped")
    assert SECRET not in json.dumps(allc)                                          # args were scrubbed, results never stored
    assert [c["tool"] for c in ready.get("/calls?outcome=ok").json()["calls"]] == ["vault_list"]
    assert ready.get("/calls?tool=nope").json()["calls"] == []
    assert ready.get("/calls?limit=999999").status_code == 200


def test_a_script_tag_in_a_query_is_data_not_markup(ready, monkeypatch):
    monkeypatch.setitem(tools.REGISTRY, "vault_list", tools.Tool("vault_list", "t", "d", {"type": "object"}, lambda a: tools.Result({})))
    protocol.call_tool("vault_list", {"sql": "<img src=x onerror=alert(1)>"})
    body = ready.get("/calls").json()["calls"][0]["args"]
    assert "<img" in body        # stored and returned as plain text; the PAGE escapes it (proved in a real browser: see the K4 handoff note)

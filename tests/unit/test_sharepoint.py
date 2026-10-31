"""
SharePoint Lists (sharepoint-lab) — runs against an in-memory fake of Microsoft sign-in + Graph (tests/unit/fake_graph.py).
Needs the data runtime's packages (fastapi, httpx, pydantic): run inside the image, e.g.
  docker run --rm -v $PWD/tests:/tests:ro -v $PWD/sharepoint-lab:/app/sharepoint_lab:ro -w /app toolbox-rt-data \
      sh -c "pip install -q pytest; python -m pytest /tests/unit/test_sharepoint.py -q"
The promises tested here: nothing reaches SharePoint before an approved review, what you approved is what is written, other
people's changes are never overwritten, secrets never leave the server, and there is no delete.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
fastapi_testclient = pytest.importorskip("fastapi.testclient")

from fake_graph import CLIENT, CONTACTS, GOOD_SECRET, HOST, SITE2_ID, SITE_ID, TASKS, TENANT, FakeGraph  # noqa: E402

from sharepoint_lab import auth, columns, graph as graph_mod, service, store  # noqa: E402
from sharepoint_lab.server import app  # noqa: E402
from core.state.sqlstore import SqlStore  # noqa: E402


class FakeVault:
    class SecretNotFound(Exception):
        pass

    class ScopeError(PermissionError):
        pass

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, str, dict]] = {}
        self.n = 0

    def list_secrets(self, kind):
        return [{"id": i, "name": n, "kind": k} for i, (n, k, _) in self.rows.items() if k == kind]

    def get_secret(self, sid):
        if sid not in self.rows:
            raise self.SecretNotFound(sid)
        import copy
        return copy.deepcopy(self.rows[sid][2])

    def save_secret(self, name, kind, data):
        self.n += 1
        sid = f"s{self.n}"
        self.rows[sid] = (name, kind, dict(data))
        return sid

    def update_secret(self, sid, data):
        n, k, _ = self.rows[sid]
        self.rows[sid] = (n, k, dict(data))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("TOOLBOX_DATABASE_URL", raising=False)
    fake, vault = FakeGraph(), FakeVault()
    monkeypatch.setattr(store, "STORE", SqlStore("sharepoint_lab", sqlite_path=tmp_path / "sp.db", ddl=store._SCHEMA))
    store.init_db()
    monkeypatch.setattr(service, "TRANSPORT", httpx.MockTransport(fake.handle))
    monkeypatch.setattr(service, "_VAULT", vault)
    slept: list[float] = []

    async def no_sleep(s):
        slept.append(s)
    monkeypatch.setattr(graph_mod, "SLEEP", no_sleep)
    auth._TOKENS.clear(), service._LISTS.clear(), service._SCHEMAS.clear()
    from fastapi.testclient import TestClient
    client = TestClient(app)

    class E:
        pass
    e = E()
    e.fake, e.vault, e.client, e.slept = fake, vault, client, slept
    e.site, e.list = SITE_ID, TASKS

    def add(read_only=False, **kw):
        body = {"name": "Team", "auth": "client_secret", "tenant_id": TENANT, "client_id": CLIENT, "client_secret": GOOD_SECRET,
                "sites": [f"https://{HOST}/sites/Team"], "read_only": read_only, **kw}
        r = client.post("/connections", json=body)
        assert r.status_code == 200, r.text
        return r.json()["id"]
    e.add = add
    e.q = lambda cid: {"conn": cid, "site": SITE_ID, "list": TASKS}
    e.stage = lambda cid, item, field, old, new, **kw: client.put("/staged", json={"conn": cid, "site": SITE_ID, "list": TASKS, "item_id": item,
                                                                                    "field": field, "old": old, "new": new, **kw})
    e.review = lambda cid: client.get("/staged", params=e.q(cid)).json()
    e.apply = lambda cid, digest: client.post("/apply", json={**e.q(cid), "digest": digest})
    return e


# ---------------------------------------------------------------- columns (pure)
def test_describe_kinds_and_editability():
    d = {x["name"]: x for x in columns.describe_all(__import__("fake_graph").tasks_columns())}
    assert d["Title"]["kind"] == "text" and d["Title"]["required"] and d["Title"]["editable"] and d["Title"]["max_length"] == 40
    assert d["Notes"]["kind"] == "note" and d["Priority"]["kind"] == "number" and d["Done"]["kind"] == "boolean"
    assert d["DueDate"]["kind"] == "date" and d["Created"]["kind"] == "datetime"
    assert d["Status"]["kind"] == "choice" and not d["Status"]["multi"] and d["Tags"]["multi"]
    assert d["Owner"]["kind"] == "person" and d["Owner"]["key"] == "OwnerLookupId" and not d["Owner"]["editable"]
    assert d["Project"]["kind"] == "lookup" and d["Project"]["key"] == "ProjectLookupId" and not d["Project"]["editable"]
    assert not d["Total"]["editable"] and d["Total"]["why"] == "calculated column"
    assert not d["ID"]["editable"] and d["ID"]["system"] and not d["Modified"]["editable"]
    assert d["_UIVersionString"]["hidden"] and d["_UIVersionString"]["system"]
    order = [x["name"] for x in columns.describe_all(__import__("fake_graph").tasks_columns())]
    assert order[0] == "Title" and order.index("Status") < order.index("Created")   # real columns first, system last


@pytest.mark.parametrize("name,value,expected", [
    ("Title", "hello", "hello"), ("Priority", "3", 3), ("Priority", 2.5, 2.5), ("Done", "yes", True), ("Done", "0", False),
    ("DueDate", "2026-10-30", "2026-10-30T00:00:00Z"), ("DueDate", "2026-10-30T10:00:00+02:00", "2026-10-30T08:00:00Z"),
    ("Status", "Done", "Done"), ("Tags", ["a", "c"], ["a", "c"]), ("Tags", "b", ["b"]), ("Notes", "x\ny", "x\ny"), ("Notes", "", None),
])
def test_coerce_accepts(name, value, expected):
    d = {x["name"]: x for x in columns.describe_all(__import__("fake_graph").tasks_columns())}
    assert columns.coerce(d[name], value) == expected


@pytest.mark.parametrize("name,value,fragment", [
    ("Title", "x" * 41, "Too long"), ("Title", "", "required"), ("Title", None, "required"), ("Priority", "9", "maximum"),
    ("Priority", "0", "minimum"), ("Priority", "abc", "not a number"), ("Done", "maybe", "true or false"),
    ("DueDate", "tomorrow", "not a date"), ("Status", "Nope", "not one of the choices"), ("Tags", ["a", "z"], "not one of the choices"),
    ("Owner", "x", "can't be edited"), ("Total", 5, "can't be edited"), ("ID", 5, "can't be edited"),
])
def test_coerce_refuses(name, value, fragment):
    d = {x["name"]: x for x in columns.describe_all(__import__("fake_graph").tasks_columns())}
    with pytest.raises(ValueError, match=fragment):
        columns.coerce(d[name], value)


def test_same_and_payload():
    d = {x["name"]: x for x in columns.describe_all(__import__("fake_graph").tasks_columns())}
    assert columns.same(d["Priority"], 1, 1.0) and columns.same(d["Priority"], "2", 2)
    assert columns.same(d["Tags"], ["a", "b"], ["b", "a"]) and columns.same(d["Tags"], [], None)
    assert columns.same(d["Notes"], None, "") and not columns.same(d["Title"], "a", "A")
    assert columns.same(d["DueDate"], "2026-11-01T00:00:00Z", "2026-11-01T02:00:00+02:00")
    assert columns.payload(d["Tags"], ["a"]) == {"Tags": ["a"], "Tags@odata.type": "Collection(Edm.String)"}
    assert columns.payload(d["Status"], "Done") == {"Status": "Done"}


# ---------------------------------------------------------------- Graph client: the safety belt
@pytest.mark.parametrize("method,path,ok", [
    ("GET", "/sites/x/lists", True), ("PATCH", "/sites/s,1,2/lists/L/items/5/fields", True), ("POST", "/sites/s/lists/L/items", True),
    ("POST", "/$batch", True), ("DELETE", "/sites/s/lists/L/items/5", False), ("PUT", "/sites/s/lists/L/items/5/fields", False),
    ("PATCH", "/sites/s/lists/L/items/5", False), ("PATCH", "/sites/s/lists/L", False), ("POST", "/sites/s/lists", False),
    ("POST", "/sites/s/lists/L/columns", False), ("PATCH", "/sites/s/lists/L/columns/c", False), ("POST", "/sites/s/lists/L/items/5/fields", False),
])
def test_only_three_write_shapes_are_allowed(method, path, ok):
    if ok:
        graph_mod._check_write(method, path)
    else:
        with pytest.raises(graph_mod.GraphError):
            graph_mod._check_write(method, path)


def test_batch_refuses_a_delete_sub_request(env):
    cid = env.add()
    conn = service.open_conn(cid)
    with pytest.raises(graph_mod.GraphError):
        asyncio.run(conn.graph.batch([{"id": "1", "method": "DELETE", "url": "/sites/s/lists/L/items/5"}]))
    assert env.fake.sent("DELETE") == []


def test_foreign_next_link_is_not_followed(env):
    conn = service.open_conn(env.add())
    with pytest.raises(graph_mod.GraphError, match="not on the Microsoft Graph host"):
        asyncio.run(conn.graph.items(SITE_ID, TASKS, top=5, cursor="https://evil.example/v1.0/sites/x/items?token=1"))
    assert not any("evil" in p for _, p in env.fake.calls)


def test_throttling_is_retried_and_401_refreshes_the_token(env):
    cid = env.add()
    env.fake.throttle = 2
    r = env.client.get("/schema", params=env.q(cid))
    assert r.status_code == 200 and len(env.slept) == 2           # waited the Retry-After twice, then got through
    env.fake.expired_tokens = True
    service._SCHEMAS.clear()
    assert env.client.get("/schema", params=env.q(cid)).status_code == 200
    assert sum(1 for m, p in env.fake.calls if p.endswith("/oauth2/v2.0/token")) >= 2   # the 401 made it fetch a new token


# ---------------------------------------------------------------- sign-in
def test_client_secret_wrong_is_a_plain_error_without_the_secret(env):
    cid = env.add(client_secret="wrong-secret-value")
    r = env.client.get(f"/connections/{cid}/lists", params={"refresh": 1})
    site = r.json()["sites"][0]["site"]
    assert "rejected the client id or secret" in site["error"] and "wrong-secret-value" not in r.text


def test_device_code_flow_saves_the_refresh_token_and_rotates_it(env):
    cid = env.add(auth="device_code", client_secret=None)
    assert env.client.get("/connections").json()["connections"][0]["signed_in"] is False
    r = env.client.get(f"/connections/{cid}/lists", params={"refresh": 1}).json()["sites"][0]["site"]
    assert r["needs_signin"] is True                                   # not signed in yet
    start = env.client.post(f"/connections/{cid}/signin").json()
    assert start["user_code"] == "ABCD-1234" and "devicelogin" in start["verification_uri"]
    assert env.client.get(f"/signin/{start['flow']}").json() == {"status": "pending"}
    assert env.client.get(f"/signin/{start['flow']}").json() == {"status": "done"}
    assert env.vault.rows[cid][2]["refresh_token"] == "rt-dev"
    assert env.client.get("/connections").json()["connections"][0]["signed_in"] is True
    auth._TOKENS.clear()                                               # next use refreshes with the saved token and stores the new one
    assert env.client.get(f"/connections/{cid}/lists", params={"refresh": 1}).json()["sites"][0]["lists"]
    assert env.vault.rows[cid][2]["refresh_token"] == "rt-1"


def test_read_only_device_connection_asks_for_the_read_scope():
    d = {"auth": "device_code", "tenant_id": TENANT, "client_id": CLIENT, "read_only": True}
    assert "Sites.Read.All" in auth._scope(d) and "ReadWrite" not in auth._scope(d)
    d["read_only"] = False
    assert "Sites.ReadWrite.All" in auth._scope(d)


def test_connection_validation(env):
    bad = env.client.post("/connections", json={"name": "x", "auth": "client_secret", "tenant_id": TENANT, "client_id": "nope", "client_secret": "s"})
    assert bad.status_code == 422 and "Client id" in bad.json()["detail"]
    bad = env.client.post("/connections", json={"name": "x", "auth": "client_secret", "tenant_id": TENANT, "client_id": CLIENT})
    assert bad.status_code == 422 and "client secret" in bad.json()["detail"]
    bad = env.client.post("/connections", json={"name": "x", "auth": "device_code", "tenant_id": TENANT, "client_id": CLIENT, "sites": ["http://x/sites/a"]})
    assert bad.status_code == 422 and "https://" in bad.json()["detail"]


def test_sign_in_as_me_needs_no_app_registration(env):
    r = env.client.post("/connections", json={"name": "Me", "auth": "device_code", "sites": [f"https://{HOST}/sites/Team"]})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["client_id"] == auth.PUBLIC_CLIENT_ID and v["tenant_id"] == "organizations" and v["signed_in"] is False
    # an app secret still needs its own registration
    bad = env.client.post("/connections", json={"name": "App", "auth": "client_secret", "client_secret": "s"})
    assert bad.status_code == 422 and "Tenant id" in bad.json()["detail"]
    start = env.client.post(f"/connections/{v['id']}/signin")
    assert start.status_code == 200
    assert any("/organizations/oauth2/v2.0/devicecode" in p for _, p in env.fake.calls)


def test_secrets_never_leave_the_server(env):
    cid = env.add()
    env.vault.rows[cid][2]["refresh_token"] = "rt-secret-token"
    texts = [env.client.get("/connections").text, env.client.get(f"/connections/{cid}/lists").text, env.client.get("/schema", params=env.q(cid)).text,
             env.client.get("/items", params=env.q(cid)).text, env.client.get("/export.csv", params=env.q(cid)).text]
    assert all(GOOD_SECRET not in t and "rt-secret-token" not in t and "at-good" not in t for t in texts)
    assert env.client.get("/connections").json()["connections"][0]["has_secret"] is True
    assert env.client.get("/schema", params={**env.q(cid), "conn": "no-such"}).status_code == 404


# ---------------------------------------------------------------- browsing
def test_lists_overview_resolves_several_sites_and_hides_hidden_lists(env):
    cid = env.add(sites=[f"https://{HOST}/sites/Team", f"https://{HOST}/sites/Ops/SitePages/Home.aspx", f"https://{HOST}/sites/Missing"])
    sites = env.client.get(f"/connections/{cid}/lists").json()["sites"]
    assert [s["site"].get("name") for s in sites[:2]] == ["Team Site", "Operations"]
    assert [l["name"] for l in sites[0]["lists"]] == ["Contacts", "Tasks"]          # sorted; the hidden list is gone
    assert "Not found" in sites[2]["site"]["error"] and sites[2]["lists"] == []      # one bad site doesn't hide the rest


def test_schema_items_paging_and_export(env):
    cid = env.add()
    cols = env.client.get("/schema", params=env.q(cid)).json()["columns"]
    assert {c["name"] for c in cols} >= {"Title", "Status", "Owner", "Total", "ID"}
    p1 = env.client.get("/items", params={**env.q(cid), "top": 10}).json()
    assert len(p1["items"]) == 10 and p1["next"]
    seen = {i["id"] for i in p1["items"]}
    nxt = p1["next"]
    while nxt:
        page = env.client.get("/items", params={**env.q(cid), "cursor": nxt}).json()
        seen |= {i["id"] for i in page["items"]}
        nxt = page["next"]
    assert len(seen) == 25
    csv_text = env.client.get("/export.csv", params=env.q(cid)).text
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("ID,Title,") and "Due date" in lines[0] and "Total" in lines[0] and "Version" not in lines[0]
    assert len(csv_text.strip().split("\r\n")) >= 26
    assert "Task 25" in csv_text


# ---------------------------------------------------------------- staging → review → apply
def test_staging_writes_nothing_to_sharepoint(env):
    cid = env.add()
    r = env.stage(cid, "3", "Title", "Task 3", "Renamed")
    assert r.status_code == 200 and r.json()["row"]["changes"] == {"Title": {"old": "Task 3", "new": "Renamed"}}
    assert not env.fake.sent("PATCH") and not [p for p in env.fake.sent("POST") if p.startswith("/v1.0")]   # not even a batch (the token POST is sign-in)
    rv = env.review(cid)
    assert rv["counts"] == {"rows": 1, "fields": 1, "invalid_rows": 0, "creates": 0}
    assert rv["rows"][0]["fields"][0]["display"] == "Title" and rv["rows"][0]["fields"][0]["new"] == "Renamed"
    assert env.fake.tasks["3"]["Title"] == "Task 3"


def test_editing_back_to_the_original_unstages(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "X")
    env.stage(cid, "3", "Priority", 4, "5")
    r = env.stage(cid, "3", "Title", "Task 3", "Task 3")
    assert list(r.json()["row"]["changes"]) == ["Priority"]
    env.stage(cid, "3", "Priority", 4, 4)
    assert env.review(cid)["rows"] == []


def test_bad_values_are_refused_at_staging(env):
    cid = env.add()
    assert env.stage(cid, "3", "Status", "Open", "Nope").status_code == 422
    assert env.stage(cid, "3", "Owner", "11", "12").status_code == 422        # person columns are not editable here
    assert env.stage(cid, "3", "Nope", 1, 2).status_code == 422
    assert env.review(cid)["rows"] == []


def test_read_only_connection_cannot_stage_or_apply(env):
    cid = env.add(read_only=True)
    assert env.stage(cid, "3", "Title", "Task 3", "X").status_code == 403
    assert env.apply(cid, "x").status_code == 403
    assert env.fake.sent("PATCH") == []


def test_apply_requires_the_digest_that_was_reviewed(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "A")
    digest = env.review(cid)["digest"]
    env.stage(cid, "4", "Title", "Task 4", "B")                                # something else is staged after the review
    r = env.apply(cid, digest)
    assert r.status_code == 409 and "reviewed" in r.json()["detail"]
    assert env.apply(cid, "bogus").status_code == 409
    assert env.fake.sent("PATCH") == [] and env.fake.tasks["3"]["Title"] == "Task 3"


def test_apply_writes_only_the_approved_fields_and_audits_them(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "Renamed")
    env.stage(cid, "3", "Status", "Open", "Done")
    env.stage(cid, "5", "Tags", [], ["a", "c"])
    env.stage(cid, "5", "DueDate", "2026-11-06T00:00:00Z", "2026-12-24")
    out = env.apply(cid, env.review(cid)["digest"]).json()
    assert out["applied"] == 2 and out["fields_written"] == 4 and out["conflict"] == out["failed"] == 0
    assert env.fake.tasks["3"]["Title"] == "Renamed" and env.fake.tasks["3"]["Status"] == "Done"
    assert env.fake.tasks["5"]["Tags"] == ["a", "c"] and env.fake.tasks["5"]["DueDate"] == "2026-12-24T00:00:00Z"
    assert env.fake.tasks["4"]["Title"] == "Task 4"                             # untouched items stay untouched
    assert env.fake.sent("DELETE") == []
    assert env.review(cid)["rows"] == []                                        # applied rows are no longer staged
    audit = env.client.get("/audit", params={"conn": cid}).json()["entries"]
    assert {(a["item_id"], a["field"], a["outcome"]) for a in audit} == {("3", "Title", "applied"), ("3", "Status", "applied"),
                                                                         ("5", "Tags", "applied"), ("5", "DueDate", "applied")}
    title = next(a for a in audit if a["field"] == "Title")
    assert title["old"] == "Task 3" and title["new"] == "Renamed" and title["stored"] == "Renamed" and title["list_name"]


def test_other_peoples_changes_are_never_overwritten(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "Mine")
    env.stage(cid, "6", "Title", "Task 6", "Also mine")
    env.fake.mutate("3", Title="Theirs")                                       # someone edits item 3 in SharePoint meanwhile
    out = env.apply(cid, env.review(cid)["digest"]).json()
    by = {r["item_id"]: r for r in out["results"]}
    assert by["3"]["outcome"] == "conflict" and "Title" in by["3"]["message"] and by["3"]["fields"][0]["live"] == "Theirs"
    assert by["6"]["outcome"] == "applied"
    assert env.fake.tasks["3"]["Title"] == "Theirs" and env.fake.tasks["6"]["Title"] == "Also mine"
    assert [r["item_id"] for r in env.review(cid)["rows"]] == ["3"]             # the conflict stays staged for a decision
    assert env.client.post("/staged/rebase", json=env.q(cid)).json()["refreshed"] == 1
    out = env.apply(cid, env.review(cid)["digest"]).json()                      # after "take SharePoint's value as the old side"
    assert out["applied"] == 1 and env.fake.tasks["3"]["Title"] == "Mine"


def test_a_value_sharepoint_already_has_is_not_rewritten(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "Same now")
    env.fake.mutate("3", Title="Same now")
    out = env.apply(cid, env.review(cid)["digest"]).json()
    assert out["unchanged"] == 1 and out["applied"] == 0 and not env.fake.sent("PATCH")


def test_one_failing_row_does_not_stop_the_others(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "A")
    env.stage(cid, "4", "Title", "Task 4", "B")
    env.fake.fail_patch_for.add("3")
    out = env.apply(cid, env.review(cid)["digest"]).json()
    by = {r["item_id"]: r for r in out["results"]}
    assert by["3"]["outcome"] == "failed" and "locked" in by["3"]["message"] and by["4"]["outcome"] == "applied"
    assert [r["item_id"] for r in env.review(cid)["rows"]] == ["3"]
    failed = [a for a in env.client.get("/audit", params={"conn": cid}).json()["entries"] if a["outcome"] == "failed"]
    assert len(failed) == 1


def test_throttled_sub_requests_are_retried(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "A")
    env.fake.batch_throttle = 1
    out = env.apply(cid, env.review(cid)["digest"]).json()
    assert out["applied"] == 1 and env.slept                                    # waited, then the same request went through


def test_new_items_need_their_required_columns(env):
    cid = env.add()
    r = env.stage(cid, None, "Status", None, "Open")
    row_id = r.json()["row"]["id"]
    assert r.json()["row"]["op"] == "create"
    rv = env.review(cid)
    assert rv["counts"]["invalid_rows"] == 1 and "required" in rv["rows"][0]["errors"][0]
    out = env.apply(cid, rv["digest"]).json()
    assert out["invalid"] == 1 and out["applied"] == 0 and len(env.fake.tasks) == 25
    env.stage(cid, None, "Title", None, "Brand new", row_id=row_id)
    out = env.apply(cid, env.review(cid)["digest"]).json()
    assert out["applied"] == 1 and len(env.fake.tasks) == 26
    new = env.fake.tasks["26"]
    assert new["Title"] == "Brand new" and new["Status"] == "Open" and out["results"][0]["item_id"] == "26"
    assert env.review(cid)["rows"] == []


def test_discard_never_touches_sharepoint(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "A")
    env.stage(cid, "3", "Priority", 4, 5)
    env.stage(cid, "4", "Title", "Task 4", "B")
    row3 = next(r["id"] for r in env.review(cid)["rows"] if r["item_id"] == "3")
    q = env.q(cid)
    env.client.post("/staged/discard", json={**q, "row_id": row3, "field": "Title"})
    assert [f["field"] for r in env.review(cid)["rows"] if r["item_id"] == "3" for f in r["fields"]] == ["Priority"]
    env.client.post("/staged/discard", json=q)
    assert env.review(cid)["rows"] == []
    assert not env.fake.sent("PATCH") and not env.fake.sent("DELETE")


def test_python_bulk_staging_reads_old_values_from_sharepoint(env):
    cid = env.add()
    r = env.client.post("/staged/bulk", json={**env.q(cid), "rows": [
        {"item_id": "3", "fields": {"Title": "New 3", "Priority": 1 + 3 % 5}},                  # Priority unchanged → not staged
        {"item_id": "4", "fields": {"Title": "New 4"}, "old": {"Title": "Task 4"}},
        {"item_id": "5", "fields": {"Status": "Bogus"}},
        {"item_id": "999", "fields": {"Title": "ghost"}}]}).json()
    assert r["staged"] == 2 and r["unchanged"] == 1 and r["problem_count"] == 2
    assert {p["item_id"] for p in r["problems"]} == {"5", "999"}
    rv = env.review(cid)
    assert {x["item_id"] for x in rv["rows"]} == {"3", "4"} and all(x["source"] == "python" for x in rv["rows"])
    assert env.apply(cid, rv["digest"]).json()["applied"] == 2


def test_the_tool_has_no_delete_anywhere(env):
    assert all("DELETE" not in (getattr(r, "methods", None) or set()) for r in app.routes)
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "A")
    env.apply(cid, env.review(cid)["digest"])
    env.client.get("/export.csv", params=env.q(cid))
    assert env.fake.sent("DELETE") == [] and env.fake.sent("PUT") == []
    src = (Path(service.__file__).parent / "graph.py").read_text()
    assert "def delete" not in src.lower() and "\"DELETE\"" not in src.replace('("DELETE"', "")


def test_staged_counts_show_per_connection_and_list(env):
    cid = env.add()
    env.stage(cid, "3", "Title", "Task 3", "A")
    env.stage(cid, "4", "Title", "Task 4", "B")
    assert env.client.get("/connections").json()["connections"][0]["staged"] == 2
    sites = env.client.get(f"/connections/{cid}/lists").json()["sites"]
    assert next(l for l in sites[0]["lists"] if l["id"] == TASKS)["staged"] == 2


def test_the_manifest_grants_only_the_sharepoint_kind():
    from core_plugins import discover
    m = discover(Path(__file__).resolve().parents[2]).plugins.get("sharepoint")
    if m is None:
        pytest.skip("manifest not discoverable from this layout")
    assert m.runtime == "data" and m.vault.read == ["sharepoint_connection"] and m.vault.write == ["sharepoint_connection"]


# ---------------------------------------------------------------- the notebook helper (notebook-lab/lib/toolbox_sharepoint.py)
def _helper(monkeypatch, env):
    pytest.importorskip("pandas")
    root = Path(__file__).resolve().parents[2]
    lib = next((p for p in (root / "notebook-lab" / "lib", root / "notebook_lab" / "lib") if p.exists()), None)
    if lib is None:
        pytest.skip("notebook helper not mounted")
    monkeypatch.syspath_prepend(str(lib))
    import importlib
    sp = importlib.import_module("toolbox_sharepoint")
    monkeypatch.setattr(sp, "BASE", "http://bridge")

    def call(method, path, body=None, params=None):
        r = env.client.request(method, "/" + path, json=body, params={k: v for k, v in (params or {}).items() if v is not None})
        if r.status_code >= 400:
            raise sp.SharePointError(r.json()["detail"])
        return r.json()
    monkeypatch.setattr(sp, "_call", call)
    return sp


def test_notebook_helper_reads_edits_and_only_stages(env, monkeypatch, capsys):
    sp = _helper(monkeypatch, env)
    cid = env.add()
    assert list(sp.connections()["name"]) == ["Team"]
    assert {"Tasks", "Contacts"} <= set(sp.lists("team")["list"])
    df = sp.read("team", "team site", "tasks")
    assert len(df) == 25 and df.index[0] == "1" and "Title" in df.columns and "Total" in df.columns and "Version" not in df.columns
    df.loc["3", "Status"] = "Done"
    df.loc["4", "Priority"] = 2                      # a numpy value
    df.loc["5", "Title"] = "set from python"
    df.loc["6", "Done"] = not df.loc["6", "Done"]
    df.loc["7", "OwnerLookupId"] = "99"              # a person column: not editable, silently left out
    df.loc["8", "Total"] = 99                        # calculated: same
    out = sp.stage(df)
    assert out["staged"] == 4 and out["rows"] == 4 and out["problem_count"] == 0
    assert "Nothing is written yet" in capsys.readouterr().out
    assert not env.fake.sent("PATCH")
    assert env.fake.tasks["5"]["Title"] == "Task 5"                               # SharePoint is still untouched
    pend = sp.pending("team", "team site", "tasks")
    assert set(pend["item"]) == {"3", "4", "5", "6"} and set(pend["source"]) == {"python"}
    assert env.apply(cid, env.review(cid)["digest"]).json()["applied"] == 4        # the human step
    assert env.fake.tasks["3"]["Status"] == "Done" and env.fake.tasks["4"]["Priority"] == 2 and env.fake.tasks["5"]["Title"] == "set from python"
    assert env.fake.tasks["7"]["OwnerLookupId"] == "11" and env.fake.tasks["8"]["Total"] == 8   # the read-only columns were never sent


def test_notebook_helper_refuses_a_foreign_frame_and_can_discard(env, monkeypatch):
    sp = _helper(monkeypatch, env)
    env.add()
    import pandas as pd
    with pytest.raises(sp.SharePointError, match="did not come from sp.read"):
        sp.stage(pd.DataFrame({"a": [1]}))
    df = sp.read("team", "team site", "tasks")
    df.loc["3", "Title"] = "x"
    sp.stage(df)
    assert len(sp.pending("team", "team site", "tasks")) == 1
    assert sp.discard("team", "team site", "tasks") == 1 and sp.pending("team", "team site", "tasks").empty
    with pytest.raises(sp.SharePointError, match="No list matches"):
        sp.read("team", "team site", "nonexistent")
    # removing rows from the frame never deletes anything
    df2 = sp.read("team", "team site", "tasks").iloc[:5]
    sp.stage(df2)
    assert env.fake.sent("DELETE") == [] and len(env.fake.tasks) == 25


def test_kernel_env_gives_only_the_bridge_url(monkeypatch):
    from notebook_lab import workspaces
    monkeypatch.setenv("SP_BRIDGE_URL", "http://toolbox:8080/tools/sharepoint")
    monkeypatch.setenv("TOOLBOX_VAULT_KEY", "secret")
    monkeypatch.setattr(workspaces, "existing", lambda ws: Path("/tmp/ws-x"))
    monkeypatch.setattr(workspaces, "venv_dir", lambda ws: Path("/tmp/ws-x/.venv"))
    env = workspaces.kernel_env("x")
    assert env["SP_BRIDGE_URL"].endswith("/tools/sharepoint") and env["PYTHONPATH"].endswith("lib")
    assert not [k for k in env if k.startswith("TOOLBOX")] and "secret" not in "".join(env.values())

"""Key Store (roadmap KS2): the entries, against a REAL (temporary, SQLite-backed) Vault: what is encrypted, the scope rules,
search and ranking, the trash, and the HTTP layer. Needs `cryptography` (skips without it)."""

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "key-store"
sys.path.insert(0, str(REPO))

pytest.importorskip("cryptography")
from cryptography.fernet import Fernet  # noqa: E402

from core import vault  # noqa: E402
from core.state.filecache import FileCache  # noqa: E402
from core.state.sqlstore import SqlStore  # noqa: E402


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, TOOL / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


store = _load("key_store_store", "store.py")


@pytest.fixture
def v(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLBOX_VAULT_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("TOOLBOX_VAULT_KEY_FILE", raising=False)
    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    data = tmp_path / "vault"
    monkeypatch.setattr(vault, "DATA_DIR", data)
    monkeypatch.setattr(vault, "DB_PATH", data / "vault.db")
    monkeypatch.setattr(vault, "KEY_PATH", data / "vault.key")
    monkeypatch.setattr(vault, "BLOBS_DIR", data / "blobs")
    st = SqlStore("vault", sqlite_path=data / "vault.db", ddl=vault._SCHEMA, backend="sqlite")
    monkeypatch.setattr(vault, "STORE", st)
    monkeypatch.setattr(vault, "_connect", st.connect)
    monkeypatch.setattr(vault, "BLOBS", FileCache("vault", data / "blobs"))
    vault.invalidate_key_cache()
    vault._scope_cache.clear()
    yield vault
    vault.invalidate_key_cache()


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def days(self, n):
        self.t += timedelta(days=n)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ks(v, clock):
    return store.KeyStore(v.scoped("key-store"), now=clock)


def add(ks, name="prod db", value="s3cret-Value!", **kw):
    return ks.create({"name": name, "value": value, **kw})


# ---- what is stored, and how --------------------------------------------------------------------------------------

def test_value_name_and_note_are_encrypted_at_rest(ks, v):
    add(ks, "billing-prod-password", "hunter2-very-secret", note="ask Priya", tags=["billing"])
    with v._connect() as con:
        rows = con.execute("SELECT name, kind, ciphertext FROM secrets").fetchall()
    assert len(rows) == 1 and rows[0]["kind"] == "key_store"
    raw = bytes(rows[0]["ciphertext"])
    for secret in (b"hunter2", b"billing-prod", b"Priya", b"billing"):
        assert secret not in raw
    assert rows[0]["name"].startswith("ks-") and "billing" not in rows[0]["name"]   # the plaintext name column leaks nothing


def test_lists_never_contain_a_value(ks):
    add(ks, "k", "TOP-SECRET-VALUE-123")
    res = ks.search()
    assert "TOP-SECRET-VALUE-123" not in json.dumps(res)
    assert res["entries"][0]["value_length"] == len("TOP-SECRET-VALUE-123")
    assert "value" not in res["entries"][0]
    assert ks.get(res["entries"][0]["id"])["value"] == "TOP-SECRET-VALUE-123"


def test_create_get_update_roundtrip(ks):
    sid = add(ks, "api", "abc", type="api_key", tags=["Billing", "prod"], note="n", environment="prod")
    e = ks.get(sid)
    assert (e["name"], e["type"], e["tags"], e["note"], e["environment"]) == ("api", "api_key", ["Billing", "prod"], "n", "prod")
    ks.update(sid, {"name": "api renamed", "value": "xyz", "tags": ["x"], "environment": ""})
    e = ks.get(sid)
    assert e["name"] == "api renamed" and e["value"] == "xyz" and e["tags"] == ["x"] and e["environment"] == ""
    ks.update(sid, {"note": "only the note"})                                   # a partial update leaves the value alone
    assert ks.get(sid)["value"] == "xyz" and ks.get(sid)["note"] == "only the note"


def test_validation(ks):
    for bad in ({"name": "", "value": "x"}, {"name": "a", "value": "  "}, {"name": "a" * 121, "value": "x"},
                {"name": "a", "value": "x", "type": "nope"}, {"name": "a", "value": "x", "environment": "staging"},
                {"name": "a", "value": "x" * 20001}, {"name": "a", "value": "x", "note": "n" * 2001},
                {"name": "a", "value": "x", "tags": [str(i) for i in range(21)]}, {"name": "a", "value": "x", "tags": ["t" * 41]},
                {"name": "a\x00b", "value": "x"}, {"name": "a", "value": "x\x00"}):
        with pytest.raises(store.Invalid):
            ks.create(bad)
    sid = add(ks, "ok", "v")
    with pytest.raises(store.Invalid):
        ks.update(sid, {"value": ""})
    assert ks.get(sid)["value"] == "v"                                          # a refused update changes nothing


def test_tags_are_cleaned(ks):
    sid = add(ks, tags=["  Prod  ", "prod", "a,b", "", "x  y"])
    assert ks.get(sid)["tags"] == ["Prod", "a b", "x y"]


def test_names_must_be_unique_ignoring_case(ks):
    sid = add(ks, "Prod DB")
    with pytest.raises(store.Conflict):
        add(ks, "prod db")
    with pytest.raises(store.Conflict):
        other = add(ks, "other")
        ks.update(other, {"name": "PROD db"})
    ks.update(sid, {"name": "PROD DB", "note": "same entry may change its own case"})


# ---- search ---------------------------------------------------------------------------------------------------------

def test_search_by_name_tag_note_and_type(ks):
    add(ks, "Postgres prod", "p1", type="connection_string", tags=["db", "billing"], note="main cluster")
    add(ks, "Stripe key", "s1", type="api_key", tags=["billing"], note="webhook secret")
    add(ks, "Wifi", "w1", type="password", tags=["home"])
    names = lambda **kw: [e["name"] for e in ks.search(**kw)["entries"]]  # noqa: E731
    assert names(q="postgres") == ["Postgres prod"]
    assert names(q="billing") == ["Postgres prod", "Stripe key"]
    assert names(q="cluster") == ["Postgres prod"]
    assert names(q="api key") == ["Stripe key"]                                 # the type label is searchable
    assert names(q="billing webhook") == ["Stripe key"]                          # every word must match (AND)
    assert names(q="nothing like this") == []
    assert names(type_="password") == ["Wifi"] and names(tag="home") == ["Wifi"] and names(tag="HOME") == ["Wifi"]


def test_search_ranks_name_matches_first(ks):
    add(ks, "Backup tool", "1", tags=["db"])
    add(ks, "db", "2")
    add(ks, "DB admin", "3")
    add(ks, "Other", "4", note="uses the db")
    assert [e["name"] for e in ks.search(q="db")["entries"]] == ["db", "DB admin", "Backup tool", "Other"]


def test_values_are_searched_only_when_asked_and_never_returned(ks):
    add(ks, "one", "token-ABC123")
    assert ks.search(q="abc123")["entries"] == []
    res = ks.search(q="abc123", in_values=True)
    assert [e["name"] for e in res["entries"]] == ["one"] and "ABC123" not in json.dumps(res)


def test_environment_filter_and_counts(ks):
    add(ks, "a", "1", environment="prod", tags=["x"])
    add(ks, "b", "2", environment="non-prod", tags=["x", "y"])
    add(ks, "c", "3", tags=["y"])
    assert [e["name"] for e in ks.search(env="prod")["entries"]] == ["a"]
    assert [e["name"] for e in ks.search(env="non-prod")["entries"]] == ["b"]
    assert [e["name"] for e in ks.search(env="unset")["entries"]] == ["c"]
    c = ks.search()["counts"]
    assert c["total"] == 3 and c["environments"] == {"prod": 1, "non-prod": 1, "unset": 1}
    assert c["types"] == {"password": 3} and c["tags"] == [["x", 2], ["y", 2]]


def test_pinned_first_and_sorts(ks, clock):
    add(ks, "alpha", "1")
    clock.days(1)
    b = add(ks, "bravo", "2")
    clock.days(1)
    add(ks, "charlie", "3")
    assert [e["name"] for e in ks.search()["entries"]] == ["alpha", "bravo", "charlie"]
    ks.update(b, {"pinned": True})
    assert [e["name"] for e in ks.search()["entries"]][0] == "bravo"
    alpha = ks.search(q="alpha")["entries"][0]["id"]
    clock.days(1)
    ks.copy(alpha)
    assert [e["name"] for e in ks.search(sort="recent")["entries"]][:2] == ["bravo", "alpha"]   # pinned, then most recently used


def test_copy_returns_the_value_and_records_use(ks):
    sid = add(ks, "k", "the-value")
    assert ks.get(sid)["last_used"] is None
    assert ks.copy(sid) == "the-value"
    assert ks.get(sid)["last_used"].startswith("2026-11-22")


# ---- previews: a row shows a value only when it is clearly not a secret ----------------------------------------------

@pytest.mark.parametrize("type_,value,shown", [
    ("host", "db.internal.example.com", True), ("host", "10.0.0.5:5432", True), ("host", "user@host", False),
    ("url", "https://example.com/docs/page", True), ("url", "https://user:pw@example.com/", False),
    ("url", "https://example.com/?token=abc", False), ("url", "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXXXXXXXXXX", False),
    ("url", "not a url", False), ("password", "hunter2", False), ("connection_string", "postgres://u:p@h/db", False),
    ("api_key", "sk_live_abc", False), ("url", "https://example.com/a\nb", False)])
def test_safe_previews(type_, value, shown):
    assert (store.safe_preview(type_, value) is not None) is shown


def test_preview_only_in_lists_for_safe_values(ks):
    add(ks, "docs", "https://example.com/docs", type="url")
    add(ks, "webhook", "https://hooks.slack.com/services/T0/B0/AAAAAAAAAAAAAAAAAAAAAAAA", type="url")
    prev = {e["name"]: e["preview"] for e in ks.search()["entries"]}
    assert prev["docs"] == "https://example.com/docs" and prev["webhook"] is None


# ---- trash ----------------------------------------------------------------------------------------------------------

def test_trash_restore_and_delete_forever(ks, clock, v):
    sid = add(ks, "gone", "v", pinned=True)
    ks.trash(sid)
    assert ks.search()["entries"] == [] and ks.search()["counts"]["total"] == 0 and ks.search()["counts"]["trash"] == 1
    t = ks.search(trash=True)["entries"][0]
    assert t["name"] == "gone" and t["days_left"] == 30 and t["pinned"] is False
    with pytest.raises(store.Conflict):
        ks.copy(sid)
    with pytest.raises(store.Conflict):
        ks.update(sid, {"note": "x"})
    ks.restore(sid)
    assert [e["name"] for e in ks.search()["entries"]] == ["gone"]
    with pytest.raises(store.Conflict):
        ks.delete_forever(sid)                                                  # only from the trash
    ks.trash(sid)
    ks.delete_forever(sid)
    assert v.list_secrets("key_store") == []                                    # really gone from the Vault
    with pytest.raises(store.Missing):
        ks.get(sid)


def test_trash_expires_after_30_days(ks, clock, v):
    a, b = add(ks, "old"), add(ks, "recent")
    ks.trash(a)
    clock.days(20)
    ks.trash(b)
    clock.days(11)                                                              # old: 31 days in the trash, recent: 11
    names = [e["name"] for e in ks.search(trash=True)["entries"]]
    assert names == ["recent"]
    assert len(v.list_secrets("key_store")) == 1


def test_restore_renames_when_the_name_was_reused(ks):
    a = add(ks, "name")
    ks.trash(a)
    add(ks, "name")
    assert ks.restore(a) == "name (restored)"


def test_empty_trash_and_duplicate(ks):
    a, b, c = add(ks, "a"), add(ks, "b"), add(ks, "c", tags=["t"], pinned=True)
    ks.trash(a)
    ks.trash(b)
    assert ks.empty_trash() == 2 and ks.search(trash=True)["entries"] == [] and ks.search()["counts"]["total"] == 1
    d = ks.duplicate(c)
    e = ks.get(d)
    assert e["name"] == "c (copy)" and e["tags"] == ["t"] and e["pinned"] is False and e["value"] == "s3cret-Value!"
    assert ks.get(ks.duplicate(c))["name"] == "c (copy) 2"


# ---- scopes: who can and cannot reach these entries ------------------------------------------------------------------

def test_other_tools_and_the_ai_cannot_read_key_store_entries(ks, v):
    sid = add(ks, "x", "y")
    for plugin in ("mcp-server", "data-syncer", "ssh-sftp", "sql-studio", "encode-decode", "vault-nonexistent"):
        scoped = v.scoped(plugin)
        with pytest.raises(v.ScopeError):
            scoped.get_secret(sid)
        with pytest.raises(v.ScopeError):
            scoped.list_secrets("key_store")
        with pytest.raises(v.ScopeError):
            scoped.delete_secret(sid)


def test_key_store_cannot_touch_other_kinds(v):
    db = v.save_secret("db", "postgres_connection", {"password": "pw"})
    ssh = v.scoped("key-store")
    with pytest.raises(v.ScopeError):
        ssh.get_secret(db)
    with pytest.raises(v.ScopeError):
        ssh.list_secrets("postgres_connection")
    with pytest.raises(v.ScopeError):
        ssh.save_secret("x", "postgres_connection", {})
    with pytest.raises(v.ScopeError):
        ssh.delete_secret(db)
    assert v.get_secret(db) == {"password": "pw"}                               # still there


def test_scoped_delete_refuses_datasets(v, tmp_path):
    src = tmp_path / "d.csv"
    src.write_text("a\n1\n")
    ds = v.scoped("duck-lab").save_dataset("d", "duckdb_result", {"format": "csv"}, src)
    with pytest.raises(v.ScopeError):
        v.scoped("duck-lab").delete_secret(ds)
    with pytest.raises(v.ScopeError):
        v.scoped("key-store").delete_secret(ds)


def test_the_vault_page_list_shows_no_real_names(ks, v):
    add(ks, "super-sensitive-name", "x")
    assert [s["name"] for s in v.list_secrets("key_store")][0].startswith("ks-")


# ---- the manifest -----------------------------------------------------------------------------------------------------

def test_manifest_scope_and_no_ai_access():
    from core_plugins import discover

    m = discover(REPO).plugins["key-store"]
    assert m.runtime == "data" and m.vault.read == ["key_store"] and m.vault.write == ["key_store"]
    assert m.vault.datasets == "none" and m.vault.data == "none"
    assert not getattr(m, "ai", None), "Key Store must never expose actions to the AI helper"
    assert "key_store" not in (REPO / "mcp_server" / "vault_scope.yaml").read_text()


# ---- the HTTP layer -----------------------------------------------------------------------------------------------------

@pytest.fixture
def api(v, clock, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    server = _load("key_store_server_ks2", "server.py")
    monkeypatch.setattr(server, "get_store", lambda: server.store.KeyStore(v.scoped("key-store"), now=clock))   # the server's own copy of store.py (same exception classes)
    return TestClient(server.app)


def test_http_full_cycle_and_no_value_in_lists(api):
    SECRET = "Zx9-very-secret-VALUE"
    r = api.post("/entries", json={"name": "prod db", "value": SECRET, "type": "password", "tags": ["db"], "environment": "prod"})
    assert r.status_code == 200 and r.json()["ok"]
    sid = r.json()["id"]
    lst = api.get("/entries", params={"q": "db"})
    assert lst.status_code == 200 and SECRET not in lst.text and lst.json()["entries"][0]["environment"] == "prod"
    assert SECRET not in api.get("/entries", params={"q": "zx9", "in_values": "true"}).text
    assert api.get("/entries", params={"q": "zx9", "in_values": "true"}).json()["entries"][0]["id"] == sid
    assert api.get(f"/entries/{sid}").json()["entry"]["value"] == SECRET
    assert api.post(f"/entries/{sid}/copy").json()["value"] == SECRET
    assert api.put(f"/entries/{sid}", json={"note": "hello"}).status_code == 200
    assert api.get(f"/entries/{sid}").json()["entry"]["note"] == "hello" and api.get(f"/entries/{sid}").json()["entry"]["value"] == SECRET
    assert api.delete(f"/entries/{sid}").status_code == 200
    assert api.get("/entries").json()["entries"] == [] and api.get("/entries", params={"trash": "true"}).json()["entries"][0]["id"] == sid
    assert api.post(f"/entries/{sid}/copy").status_code == 409
    assert api.post(f"/entries/{sid}/restore").json()["name"] == "prod db"
    assert api.delete(f"/entries/{sid}/forever").status_code == 409
    api.delete(f"/entries/{sid}")
    assert api.delete(f"/entries/{sid}/forever").status_code == 200
    assert api.get(f"/entries/{sid}").status_code == 404


def test_http_errors_are_plain_messages(api):
    assert api.post("/entries", json={"name": "", "value": "x"}).status_code == 400
    assert "name" in api.post("/entries", json={"name": "", "value": "x"}).json()["detail"].lower()
    api.post("/entries", json={"name": "dup", "value": "x"})
    r = api.post("/entries", json={"name": "DUP", "value": "y"})
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    assert api.get("/entries/nope").status_code == 404
    assert api.post("/entries", json={"name": "a"}).status_code == 422            # missing value: FastAPI validation


def test_http_everything_is_no_store_and_meta_lists_types(api):
    for path in ("/entries", "/meta", "/health", "/"):
        assert api.get(path).headers["cache-control"] == "no-store", path
    m = api.get("/meta").json()
    assert {t["key"] for t in m["types"]} >= {"password", "api_key", "connection_string", "url", "host"} and m["trash_days"] == 30


def test_http_only_the_known_scripts_are_served(api):
    for name in ("keygen.js", "words.js", "generator.js", "store.js"):
        assert api.get("/" + name).status_code == 200, name
    for name in ("server.py", "store.py", "manifest.yaml", "index.html", "../server.py"):
        assert api.get("/" + name).status_code in (404, 405), name


def test_http_scope_failure_is_a_clean_403(v, clock, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    server = _load("key_store_server_ks2b", "server.py")
    monkeypatch.setattr(server, "get_store", lambda: server.store.KeyStore(v.scoped("encode-decode"), now=clock))   # a plugin with no access
    r = TestClient(server.app).get("/entries")
    assert r.status_code == 403 and "not allowed" in r.json()["detail"]

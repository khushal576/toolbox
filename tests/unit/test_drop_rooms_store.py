"""Drop Rooms (roadmap DR1): rooms, keys, devices and text items, against a REAL temporary database (SQLite-backed SqlStore) and a
REAL temporary Vault. Then the HTTP layer with two separate "devices" (two cookie jars). Needs `cryptography` (skips without it)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "drop-rooms"
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


store = _load("drop_rooms_store_under_test", "store.py")


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeLimiter:
    def __init__(self, fail=False):
        self.n, self.fail = {}, fail

    def hit(self, key, limit, window):
        if self.fail:
            raise RuntimeError("redis down")
        self.n[key] = self.n.get(key, 0) + 1
        return self.n[key] <= limit


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLBOX_VAULT_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("TOOLBOX_VAULT_KEY_FILE", raising=False)
    monkeypatch.delenv("TOOLBOX_S3_ENDPOINT", raising=False)
    data = tmp_path / "vault"
    monkeypatch.setattr(vault, "DATA_DIR", data)
    monkeypatch.setattr(vault, "DB_PATH", data / "vault.db")
    monkeypatch.setattr(vault, "KEY_PATH", data / "vault.key")
    monkeypatch.setattr(vault, "BLOBS_DIR", data / "blobs")
    vst = SqlStore("vault", sqlite_path=data / "vault.db", ddl=vault._SCHEMA, backend="sqlite")
    monkeypatch.setattr(vault, "STORE", vst)
    monkeypatch.setattr(vault, "_connect", vst.connect)
    monkeypatch.setattr(vault, "BLOBS", FileCache("vault", data / "blobs"))
    vault.invalidate_key_cache()
    vault._scope_cache.clear()
    db = SqlStore("drop_rooms", sqlite_path=tmp_path / "dr.db", ddl=store.SCHEMA, backend="sqlite")
    db.init()
    yield vault, db
    vault.invalidate_key_cache()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def dr(env, clock):
    v, db = env
    return store.DropRooms(db, v.scoped("drop-rooms"), clock=clock)


def device(dr):
    return dr.new_device()[0]


def room_with(dr, name="Team", nick="Owner", retention=None):
    owner = device(dr)
    room = dr.create_room(owner, name, nick, retention)
    return owner, room


def joined(dr, room, nick="Guest"):
    d = device(dr)
    dr.join(d, room["key"], nick)
    return d


# ---- keys -------------------------------------------------------------------------------------------------------

def test_keys_are_long_random_and_forgiving_to_type():
    k = store.new_key()
    assert len(k) == 29 and k.count("-") == 4 and all(c in store.KEY_ALPHABET + "-" for c in k)
    assert len({store.new_key() for _ in range(500)}) == 500
    assert store.normalize_key(k.lower().replace("-", "  ")) == k.replace("-", "")
    assert store.normalize_key("0O0O0-1I1L1-ABCDE-FGHJK-MNPQR".replace("O", "0")) == store.normalize_key("00000-11111-ABCDE-FGHJK-MNPQR")
    for bad in ("", "short", k + "A", "U" * 25, None):
        with pytest.raises(store.BadRequest):
            store.normalize_key(bad)
    assert store.key_hash(k) == store.key_hash(k.lower()) and store.key_hash(k) != store.key_hash(store.new_key())


# ---- creating and joining ------------------------------------------------------------------------------------------

def test_the_key_is_stored_hashed_in_the_database_and_in_the_vault(dr, env):
    v, db = env
    owner, room = room_with(dr)
    with db.connect() as con:
        rows = con.execute("SELECT * FROM rooms").fetchall()
        dump = json.dumps([dict(r) for r in rows]) + json.dumps([dict(r) for r in con.execute("SELECT * FROM members").fetchall()])
    assert room["key"].replace("-", "") not in dump.replace("-", "") and rows[0]["key_hash"] == store.key_hash(room["key"])
    secrets_ = v.list_secrets("drop_room_key")
    assert len(secrets_) == 1 and secrets_[0]["name"] == "dr-" + room["id"]
    assert dr.invite_key(owner, room["id"]) == room["key"]


def test_create_validation_and_limits(dr, monkeypatch):
    d = device(dr)
    for name, nick in (("", "x"), ("r", ""), ("n" * 61, "x"), ("r", "n" * 31), ("r\x00", "x")):
        with pytest.raises(store.BadRequest):
            dr.create_room(d, name, nick)
    assert dr.create_room(d, "  My   room  ", " Me ")["name"] == "My room"
    monkeypatch.setattr(store, "MAX_ROOMS_PER_DEVICE", 2)
    dr.create_room(d, "two", "me")
    with pytest.raises(store.BadRequest, match="at most 2"):
        dr.create_room(d, "three", "me")


def test_failed_creation_leaves_no_key_behind(dr, env, monkeypatch):
    v, _ = env
    d = device(dr)
    monkeypatch.setattr(store, "key_hash", lambda k: (_ for _ in ()).throw(RuntimeError("the database insert failed")))   # breaks the save itself
    with pytest.raises(RuntimeError):
        dr.create_room(d, "x", "y")
    assert v.list_secrets("drop_room_key") == []
    with dr.db.connect() as con:
        assert con.execute("SELECT COUNT(*) AS n FROM rooms").fetchone()["n"] == 0


def test_join_with_the_key_and_wrong_keys(dr):
    owner, room = room_with(dr)
    g = device(dr)
    with pytest.raises(store.NotFound, match="does not match"):
        dr.join(g, store.new_key(), "Guest")
    with pytest.raises(store.BadRequest):
        dr.join(g, "nonsense", "Guest")
    joined_room = dr.join(g, room["key"].lower(), "Guest")
    assert joined_room["id"] == room["id"] and joined_room["role"] == "member" and "key" not in joined_room
    assert [r["id"] for r in dr.rooms(g)] == [room["id"]]
    assert dr.join(g, room["key"], "Renamed")["nickname"] == "Renamed"            # joining twice just updates the nickname
    assert len(dr.room(owner, room["id"])["members"]) == 2


def test_member_cap(dr, monkeypatch):
    monkeypatch.setattr(store, "MAX_MEMBERS", 2)
    _, room = room_with(dr)
    joined(dr, room)
    with pytest.raises(store.BadRequest, match="full"):
        joined(dr, room)


def test_strangers_all_get_the_same_not_found(dr):
    owner, room = room_with(dr)
    stranger = device(dr)
    msgs = set()
    for call in (lambda: dr.room(stranger, room["id"]), lambda: dr.items(stranger, room["id"]), lambda: dr.add_text(stranger, room["id"], "hi"),
                 lambda: dr.invite_key(stranger, room["id"]), lambda: dr.room(stranger, "no-such-room"), lambda: dr.items("", room["id"])):
        with pytest.raises(store.NotFound) as e:
            call()
        msgs.add(str(e.value))
    assert len(msgs) == 1, "a wrong id must never reveal whether a room exists"


# ---- text, sync, retention ---------------------------------------------------------------------------------------------

def test_two_devices_see_each_others_text_and_sync_by_rev(dr):
    owner, room = room_with(dr, retention=3600)
    guest = joined(dr, room, "Phone")
    a = dr.add_text(owner, room["id"], "hello from the laptop")
    first = dr.items(guest, room["id"])
    assert first["changed"] and [i["text"] for i in first["items"]] == ["hello from the laptop"]
    assert first["items"][0]["nickname"] == "Owner" and first["items"][0]["mine"] is False
    assert dr.items(owner, room["id"])["items"][0]["mine"] is True
    assert dr.items(guest, room["id"], first["rev"]) == {"changed": False, "rev": first["rev"], "now": dr.now()}
    dr.add_text(guest, room["id"], "reply from the phone")
    again = dr.items(owner, room["id"], first["rev"])
    assert again["changed"] and [i["text"] for i in again["items"]] == ["hello from the laptop", "reply from the phone"]
    assert a["version"] == 1 and a["expires_at"] == dr.now() + 3600


def test_text_validation(dr, monkeypatch):
    owner, room = room_with(dr)
    for bad in ("", "   ", "x" * 20001, "a\x00b"):
        with pytest.raises(store.BadRequest):
            dr.add_text(owner, room["id"], bad)
    dr.add_text(owner, room["id"], "x" * 20000)
    monkeypatch.setattr(store, "MAX_ITEMS_PER_ROOM", 1)
    with pytest.raises(store.BadRequest, match="too many"):
        dr.add_text(owner, room["id"], "one more")


def test_retention_default_presets_and_the_30_day_cap(dr, clock):
    owner, room = room_with(dr, retention=store.DEFAULT_RETENTION)
    assert dr.add_text(owner, room["id"], "default")["expires_at"] == dr.now() + 21600
    assert dr.add_text(owner, room["id"], "1h", 3600)["expires_at"] == dr.now() + 3600
    assert dr.add_text(owner, room["id"], "forever?", 10 ** 9)["expires_at"] == dr.now() + 30 * 86400
    for bad in (0, 1, -5, "abc"):
        with pytest.raises(store.BadRequest):
            dr.add_text(owner, room["id"], "bad", bad)
    assert store.PRESETS == (3600, 10800, 21600, 43200, 86400, 259200, 604800, 2592000)
    dr.rename_room(owner, room["id"], default_retention=7200)
    assert dr.add_text(owner, room["id"], "new default")["expires_at"] == dr.now() + 7200


def test_expired_items_are_invisible_at_once_and_erased_later(dr, clock, env):
    _, db = env
    owner, room = room_with(dr)
    guest = joined(dr, room)
    dr.add_text(owner, room["id"], "short", 60)
    dr.add_text(owner, room["id"], "long", 3600)
    clock.advance(61)
    assert [i["text"] for i in dr.items(guest, room["id"])["items"]] == ["long"]
    assert dr.rooms(owner)[0]["items"] == 1
    clock.advance(3600)
    assert dr.items(owner, room["id"])["items"] == []
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"] == 0        # the read above erased them


def test_change_one_items_retention(dr, clock):
    owner, room = room_with(dr)
    guest = joined(dr, room)
    it = dr.add_text(owner, room["id"], "x", 60)
    clock.advance(30)
    assert dr.set_retention(guest, room["id"], it["id"], 3600)["expires_at"] == dr.now() + 3600       # anyone in the room may change it
    clock.advance(120)
    assert len(dr.items(owner, room["id"])["items"]) == 1
    with pytest.raises(store.BadRequest):
        dr.set_retention(owner, room["id"], it["id"], 1)


# ---- edit, delete, undo ------------------------------------------------------------------------------------------------

def test_anyone_can_edit_and_a_stale_edit_is_refused(dr):
    owner, room = room_with(dr)
    guest = joined(dr, room, "Phone")
    it = dr.add_text(owner, room["id"], "draft")
    e = dr.edit_text(guest, room["id"], it["id"], "better draft", it["version"])
    assert e["text"] == "better draft" and e["version"] == 2 and e["edited_by"] == "Phone" and e["edited_at"] == dr.now()
    with pytest.raises(store.Conflict) as c:
        dr.edit_text(owner, room["id"], it["id"], "my older edit", it["version"])          # still version 1
    assert c.value.current["text"] == "better draft" and "Phone" in str(c.value)
    assert dr.edit_text(owner, room["id"], it["id"], "merged", c.value.current["version"])["version"] == 3
    with pytest.raises(store.BadRequest):
        dr.edit_text(owner, room["id"], it["id"], "  ", 3)


def test_edit_keeps_the_expiry_unless_asked_to_restart(dr, clock):
    owner, room = room_with(dr)
    it = dr.add_text(owner, room["id"], "x", 3600)
    clock.advance(1800)
    e1 = dr.edit_text(owner, room["id"], it["id"], "y", 1)
    assert e1["expires_at"] == it["expires_at"]
    e2 = dr.edit_text(owner, room["id"], it["id"], "z", 2, restart_retention=7200)
    assert e2["expires_at"] == dr.now() + 7200


def test_delete_is_immediate_for_everyone_with_a_short_undo(dr, clock, env):
    _, db = env
    owner, room = room_with(dr)
    guest = joined(dr, room)
    it = dr.add_text(owner, room["id"], "oops")
    assert dr.delete_item(guest, room["id"], it["id"])["undo_seconds"] == 10                  # anyone may delete anything
    assert dr.items(owner, room["id"])["items"] == [] and dr.items(guest, room["id"])["items"] == []
    with pytest.raises(store.NotFound):
        dr.undo_delete(owner, room["id"], it["id"])                                            # only the deleting device may undo
    clock.advance(5)
    restored = dr.undo_delete(guest, room["id"], it["id"])
    assert restored["text"] == "oops" and len(dr.items(owner, room["id"])["items"]) == 1
    dr.delete_item(owner, room["id"], it["id"])
    clock.advance(11)
    with pytest.raises(store.NotFound):
        dr.undo_delete(owner, room["id"], it["id"])                                            # too late
    clock.advance(10)
    assert dr.items(owner, room["id"])["items"] == []
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"] == 0            # really erased, not just hidden
    with pytest.raises(store.NotFound):
        dr.delete_item(owner, room["id"], it["id"])


def test_an_expired_item_cannot_be_edited_deleted_or_undone(dr, clock):
    owner, room = room_with(dr)
    it = dr.add_text(owner, room["id"], "x", 60)
    clock.advance(61)
    for call in (lambda: dr.edit_text(owner, room["id"], it["id"], "y", 1), lambda: dr.delete_item(owner, room["id"], it["id"]),
                 lambda: dr.set_retention(owner, room["id"], it["id"], 3600)):
        with pytest.raises(store.NotFound):
            call()


# ---- owner powers, key reset, leaving ----------------------------------------------------------------------------------

def test_only_the_owner_can_manage_the_room(dr):
    owner, room = room_with(dr)
    guest = joined(dr, room)
    for call in (lambda: dr.rename_room(guest, room["id"], name="Mine now"), lambda: dr.reset_key(guest, room["id"]),
                 lambda: dr.delete_room(guest, room["id"]), lambda: dr.remove_member(guest, room["id"], owner)):
        with pytest.raises(store.Forbidden):
            call()
    assert dr.rename_room(owner, room["id"], name="Renamed")["name"] == "Renamed"
    assert dr.rooms(guest)[0]["name"] == "Renamed"
    assert dr.set_nickname(guest, room["id"], "Tablet")["nickname"] == "Tablet"
    assert dr.invite_key(guest, room["id"]) == room["key"]                                     # members can re-share the invite


def test_resetting_the_key_removes_everyone_else(dr):
    owner, room = room_with(dr)
    guest = joined(dr, room)
    dr.add_text(owner, room["id"], "kept")
    new = dr.reset_key(owner, room["id"])
    assert new != room["key"]
    with pytest.raises(store.NotFound):
        dr.items(guest, room["id"])                                                            # the old member is out immediately
    assert dr.rooms(guest) == []
    with pytest.raises(store.NotFound):
        dr.join(device(dr), room["key"], "Late")                                               # the old key is dead
    assert [i["text"] for i in dr.items(owner, room["id"])["items"]] == ["kept"]               # the owner and the content stay
    assert dr.invite_key(owner, room["id"]) == new
    dr.join(guest, new, "Back")
    assert len(dr.items(guest, room["id"])["items"]) == 1


def test_owner_removes_a_member_and_members_can_leave(dr):
    owner, room = room_with(dr)
    a, b = joined(dr, room, "A"), joined(dr, room, "B")
    dr.remove_member(owner, room["id"], a)
    with pytest.raises(store.NotFound):
        dr.items(a, room["id"])
    dr.leave(b, room["id"])
    assert dr.rooms(b) == []
    with pytest.raises(store.BadRequest, match="cannot be removed"):
        dr.remove_member(owner, room["id"], owner)
    with pytest.raises(store.BadRequest, match="cannot leave"):
        dr.leave(owner, room["id"])


def test_deleting_a_room_erases_everything(dr, env):
    v, db = env
    owner, room = room_with(dr)
    guest = joined(dr, room)
    dr.add_text(guest, room["id"], "secret plans")
    dr.delete_room(owner, room["id"])
    with db.connect() as con:
        for table in ("rooms", "members", "items"):
            assert con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0, table
    assert v.list_secrets("drop_room_key") == []
    with pytest.raises(store.NotFound):
        dr.items(guest, room["id"])
    with pytest.raises(store.NotFound):
        dr.join(device(dr), room["key"], "x")


def test_file_erase_hook_is_called_for_every_erased_file(dr, env, clock):
    class Files:
        deleted = []

        def delete(self, k):
            self.deleted.append(k)

    _, db = env
    f = Files()
    dr.files = f
    owner, room = room_with(dr)
    with db.connect() as con:                                                                  # DR2 will insert real file items; fake two here
        for i, ttl in enumerate((60, 10 ** 6)):
            con.execute("INSERT INTO items (id, room_id, seq, kind, device_id, nickname, created_at, version, expires_at, s3_key) VALUES (?, ?, ?, 'file', ?, 'x', ?, 1, ?, ?)",
                        (f"f{i}", room["id"], 50 + i, owner, dr.now(), dr.now() + ttl, f"k{i}"))
    clock.advance(120)
    dr.purge()
    assert f.deleted == ["k0"]
    dr.delete_room(owner, room["id"])
    assert f.deleted == ["k0", "k1"]


# ---- devices -----------------------------------------------------------------------------------------------------------

def test_device_tokens_are_stored_hashed_and_idle_devices_are_forgotten(dr, env, clock):
    _, db = env
    did, token = dr.new_device()
    with db.connect() as con:
        assert token not in json.dumps([dict(r) for r in con.execute("SELECT * FROM devices").fetchall()])
    assert dr.device_for_token(token) == did and dr.device_for_token("wrong") is None and dr.device_for_token("") is None and dr.device_for_token("x" * 500) is None
    owner, room = room_with(dr)
    clock.advance(31 * 86400)
    dr.purge()
    assert dr.device_for_token(token) is None
    with pytest.raises(store.NotFound):
        dr.items(owner, room["id"])


def test_presence_marks_recent_devices_online(dr, clock):
    owner, room = room_with(dr)
    guest = joined(dr, room)
    clock.advance(60)
    dr.items(owner, room["id"])
    members = {m["nickname"]: m for m in dr.room(owner, room["id"])["members"]}
    assert members["Owner"]["online"] and members["Owner"]["you"] and not members["Guest"]["online"]


# ---- who can reach the keys --------------------------------------------------------------------------------------------

def test_scopes_the_ai_and_other_tools_cannot_read_room_keys(dr, env):
    v, _ = env
    owner, room = room_with(dr)
    sid = v.list_secrets("drop_room_key")[0]["id"]
    for plugin in ("mcp-server", "key-store", "data-syncer", "ssh-sftp", "encode-decode"):
        with pytest.raises(v.ScopeError):
            v.scoped(plugin).get_secret(sid)
        with pytest.raises(v.ScopeError):
            v.scoped(plugin).list_secrets("drop_room_key")
        with pytest.raises(v.ScopeError):
            v.scoped(plugin).delete_secret(sid)
    db_id = v.save_secret("db", "postgres_connection", {"password": "pw"})
    with pytest.raises(v.ScopeError):
        v.scoped("drop-rooms").get_secret(db_id)                                                # and it cannot read anyone else's secrets


def test_manifest_scope_and_no_ai_access():
    from core_plugins import discover

    m = discover(REPO).plugins["drop-rooms"]
    assert m.runtime == "data" and m.vault.read == ["drop_room_key"] and m.vault.write == ["drop_room_key"]
    assert m.vault.datasets == "none" and m.vault.data == "none"
    assert not getattr(m, "ai", None), "Drop Rooms must never expose actions to the AI helper"
    assert "drop_room_key" not in (REPO / "mcp_server" / "vault_scope.yaml").read_text()


# ---- the HTTP layer, with two separate devices ---------------------------------------------------------------------------

H = {"X-Drop-Rooms": "1"}


@pytest.fixture
def web(env, clock, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    v, db = env
    server = _load("drop_rooms_server_under_test", "server.py")
    monkeypatch.setattr(server, "STORE", db)
    monkeypatch.setattr(server, "_initialised", True)
    lim = FakeLimiter()
    monkeypatch.setattr(server, "get_limiter", lambda: lim)
    real = server.store.DropRooms                       # the server's own copy of store.py, so its exception classes are the ones its handlers catch
    monkeypatch.setattr(server.store, "DropRooms", lambda s, vlt: real(s, vlt, clock=clock))

    def client():
        return TestClient(server.app)

    return server, client, lim, clock


def test_http_two_devices_chat_edit_and_delete(web):
    server, client, lim, clock = web
    a, b = client(), client()
    r = a.post("/rooms", json={"name": "Team", "nickname": "Laptop"}, headers=H)
    assert r.status_code == 200 and "dr_device" in a.cookies
    room, key = r.json()["room"]["id"], r.json()["room"]["key"]
    assert b.post("/join", json={"key": key, "nickname": "Phone"}, headers=H).json()["room"]["role"] == "member"
    it = a.post(f"/rooms/{room}/items", json={"text": "hi", "retention": 3600}, headers=H).json()["item"]
    seen = b.get(f"/rooms/{room}/items").json()
    assert seen["items"][0]["text"] == "hi" and seen["items"][0]["mine"] is False
    assert b.get(f"/rooms/{room}/items", params={"rev": seen["rev"]}).json()["changed"] is False
    assert b.put(f"/rooms/{room}/items/{it['id']}", json={"text": "hi there", "version": 1}, headers=H).json()["item"]["edited_by"] == "Phone"
    stale = a.put(f"/rooms/{room}/items/{it['id']}", json={"text": "mine", "version": 1}, headers=H)
    assert stale.status_code == 409 and stale.json()["current"]["text"] == "hi there"
    assert a.delete(f"/rooms/{room}/items/{it['id']}", headers=H).json()["undo_seconds"] == 10
    assert b.get(f"/rooms/{room}/items").json()["items"] == []
    assert a.post(f"/rooms/{room}/items/{it['id']}/undo", headers=H).json()["item"]["text"] == "hi there"
    assert b.get(f"/rooms/{room}/key").json()["key"] == key
    assert b.post(f"/rooms/{room}/reset-key", headers=H).status_code == 403
    new = a.post(f"/rooms/{room}/reset-key", headers=H).json()["key"]
    assert b.get(f"/rooms/{room}/items").status_code == 404 and b.get("/rooms").json()["rooms"] == []
    assert b.post("/join", json={"key": new, "nickname": "Phone"}, headers=H).status_code == 200


def test_http_requests_without_the_header_are_refused(web):
    server, client, lim, clock = web
    a = client()
    assert a.post("/rooms", json={"name": "x", "nickname": "y"}).status_code == 403
    assert a.post("/rooms", json={"name": "x", "nickname": "y"}, headers={"X-Drop-Rooms": "0"}).status_code == 403
    assert a.get("/rooms").status_code == 200 and a.get("/health").status_code == 200


def test_http_cookie_flags_and_no_cache_headers(web):
    server, client, lim, clock = web
    a = client()
    r = a.get("/rooms")
    c = r.headers["set-cookie"].lower()
    assert "httponly" in c and "samesite=lax" in c and "secure" not in c and "max-age=" in c
    c2 = client().get("/rooms", headers={"x-forwarded-proto": "https"}).headers["set-cookie"].lower()
    assert "secure" in c2
    for path in ("/", "/rooms", "/meta", "/health", "/app.js"):
        resp = a.get(path)
        assert resp.headers["cache-control"] == "no-store", path
        assert resp.headers["x-content-type-options"] == "nosniff"
    assert "connect-src 'self'" in a.get("/").headers["content-security-policy"]


def test_http_unknown_devices_and_rooms_look_identical(web):
    server, client, lim, clock = web
    a, stranger = client(), client()
    room = a.post("/rooms", json={"name": "x", "nickname": "y"}, headers=H).json()["room"]["id"]
    bodies = {stranger.get(f"/rooms/{room}/items").text, stranger.get("/rooms/not-a-room/items").text, client().get(f"/rooms/{room}/items").text}
    assert len(bodies) == 1


def test_http_joining_is_rate_limited_and_fails_closed(web):
    server, client, lim, clock = web
    a, g = client(), client()
    key = a.post("/rooms", json={"name": "x", "nickname": "y"}, headers=H).json()["room"]["key"]
    wrong = store.new_key()
    codes = [g.post("/join", json={"key": wrong, "nickname": "z"}, headers=H).status_code for _ in range(10)]
    assert codes[:8] == [404] * 8 and codes[8:] == [429, 429], codes
    lim.fail = True
    assert client().post("/join", json={"key": key, "nickname": "z"}, headers=H).status_code == 429       # limiter down: refuse, do not allow


def test_http_validation_errors_are_plain_messages(web):
    server, client, lim, clock = web
    a = client()
    assert a.post("/rooms", json={"name": "", "nickname": "y"}, headers=H).json()["detail"].startswith("Please give a room name")
    assert a.post("/join", json={"key": "nope", "nickname": "y"}, headers=H).status_code == 400
    room = a.post("/rooms", json={"name": "x", "nickname": "y"}, headers=H).json()["room"]["id"]
    assert a.post(f"/rooms/{room}/items", json={"text": ""}, headers=H).status_code == 400
    assert a.post(f"/rooms/{room}/items", json={"text": "ok", "retention": 1}, headers=H).status_code == 400
    assert a.post(f"/rooms/{room}/items", json={}, headers=H).status_code == 422


def test_http_the_wire_never_carries_secrets_it_should_not(web):
    server, client, lim, clock = web
    a, b = client(), client()
    created = a.post("/rooms", json={"name": "x", "nickname": "y"}, headers=H).json()["room"]
    key = created["key"]
    token = a.cookies.get("dr_device")
    joined_ = b.post("/join", json={"key": key, "nickname": "z"}, headers=H)
    a.post(f"/rooms/{created['id']}/items", json={"text": "hello"}, headers=H)
    for text in (joined_.text, b.get("/rooms").text, b.get(f"/rooms/{created['id']}").text, b.get(f"/rooms/{created['id']}/items").text):
        assert key not in text and token not in text            # the key only ever travels on create, reset and the explicit invite call


def test_http_only_the_app_script_is_served(web):
    server, client, lim, clock = web
    a = client()
    assert a.get("/app.js").status_code in (200, 404)
    for name in ("server.py", "store.py", "manifest.yaml", "../server.py", "index.html"):
        assert a.get("/" + name).status_code in (404, 405), name


# =====================================================================================================================================
# DR2: files and folders
# =====================================================================================================================================

import io  # noqa: E402
import zipfile  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


class FakeFiles:
    """What S3Files does, in a dict: put / delete / head / stream. Records every call so a test can see exactly what was stored and erased."""

    def __init__(self):
        self.data, self.puts, self.deletes = {}, [], []

    def put(self, key, fileobj, content_type):
        self.data[key] = fileobj.read()
        self.puts.append((key, content_type))

    def delete(self, key):
        self.data.pop(key, None)
        self.deletes.append(key)

    def head(self, key, n):
        return self.data[key][:n]

    def stream(self, key):
        data = self.data[key]
        for i in range(0, len(data), 7):
            yield data[i:i + 7]


def _zip(names, body=b"x"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, body)
    buf.seek(0)
    return buf


@pytest.fixture
def drf(dr):
    dr.files = FakeFiles()
    return dr


def put(dr, device, room, name, data, **kw):
    f = io.BytesIO(data)
    return dr.add_file(device, room["id"], name, f, len(data), **kw)


def test_add_file_stores_the_bytes_under_the_room_and_returns_a_file_item(drf):
    owner, room = room_with(drf, retention=3600)
    it = put(drf, owner, room, "notes.txt", b"hello files")
    assert it["kind"] == "file" and it["file_name"] == "notes.txt" and it["size"] == 11 and it["image"] is False and it["text_preview"] is True
    assert it["expires_at"] == drf.now() + 3600 and it["text"] is None and it["mine"] is True
    (key, ctype), = drf.files.puts
    assert key.startswith(f"drop-rooms/{room['id']}/") and drf.files.data[key] == b"hello files" and ctype == "application/octet-stream"
    with pytest.raises(store.BadRequest, match="Only text"):
        drf.edit_text(owner, room["id"], it["id"], "x", 1)


def test_the_type_comes_from_the_bytes_never_from_the_name(drf):
    owner, room = room_with(drf)
    assert put(drf, owner, room, "photo.png", PNG)["image"] is True
    for name, data in (("evil.png", b"<html><script>alert(1)</script>"), ("logo.svg", SVG), ("page.html", b"<h1>x</h1>"), ("a.jpg", b"not a jpeg")):
        it = put(drf, owner, room, name, data)
        assert it["image"] is False, name
    assert {c for _, c in drf.files.puts} == {"image/png", "application/octet-stream"}


def test_file_names_are_cleaned(drf):
    owner, room = room_with(drf)
    for given, expected in (("../../etc/pass wd?.txt", "pass wd_.txt"), ("C:\\Users\\me\\a.png", "a.png"), ("...", "file"), ("", "file"), ("a\x00b\x1f.txt", "ab.txt"),
                            ("CON:<>.txt", "CON___.txt")):
        assert put(drf, owner, room, given, b"x")["file_name"] == expected, given
    long = put(drf, owner, room, "x" * 300 + ".pdf", b"x")["file_name"]
    assert len(long) == store.MAX_NAME_LEN and long.endswith(".pdf")


def test_size_limits(drf, monkeypatch):
    owner, room = room_with(drf)
    with pytest.raises(store.BadRequest, match="empty"):
        put(drf, owner, room, "e.txt", b"")
    monkeypatch.setattr(store, "MAX_FILE", 10)
    put(drf, owner, room, "ok.bin", b"x" * 10)
    with pytest.raises(store.TooLarge, match="limit is 10 bytes"):
        put(drf, owner, room, "big.bin", b"x" * 11)
    assert len(drf.files.data) == 1


def test_room_and_total_quotas_and_expiry_frees_space(drf, monkeypatch, clock):
    monkeypatch.setattr(store, "ROOM_QUOTA", 100)
    owner, room = room_with(drf)
    put(drf, owner, room, "a", b"x" * 60, retention=60)
    with pytest.raises(store.TooLarge, match="40 bytes left"):
        put(drf, owner, room, "b", b"x" * 50)
    assert drf.items(owner, room["id"])["usage"] == {"room_bytes": 60, "room_quota": 100}
    clock.advance(61)
    put(drf, owner, room, "b", b"x" * 50)                                            # the expired file's space is back
    other_owner, other = room_with(drf, name="Other")
    monkeypatch.setattr(store, "TOTAL_QUOTA", 80)                                     # 50 bytes are already stored in the first room
    with pytest.raises(store.TooLarge, match="storage on this Toolbox is full"):
        put(drf, other_owner, other, "c", b"x" * 40)


def test_upload_ticket_checks_membership_and_space_before_the_body_is_read(drf, monkeypatch):
    owner, room = room_with(drf)
    assert drf.upload_ticket(owner, room["id"]) == {"max_bytes": store.MAX_FILE, "default_retention": 21600}
    with pytest.raises(store.NotFound):
        drf.upload_ticket(device(drf), room["id"])
    monkeypatch.setattr(store, "ROOM_QUOTA", 100)
    put(drf, owner, room, "a", b"x" * 70)
    assert drf.upload_ticket(owner, room["id"])["max_bytes"] == 30
    put(drf, owner, room, "b", b"x" * 30)
    with pytest.raises(store.TooLarge, match="room is full"):
        drf.upload_ticket(owner, room["id"])


def test_a_failed_save_never_leaves_bytes_behind(drf, monkeypatch):
    owner, room = room_with(drf)
    monkeypatch.setattr(drf, "_bump", lambda con, rid: (_ for _ in ()).throw(RuntimeError("database went away")))
    with pytest.raises(RuntimeError):
        put(drf, owner, room, "a.bin", b"data")
    assert drf.files.data == {} and len(drf.files.deletes) == 1                        # stored, then removed again


def test_removed_during_a_long_upload_means_nothing_is_kept(drf):
    owner, room = room_with(drf)
    guest = joined(drf, room)
    real_put = drf.files.put

    def put_then_remove(key, f, ct):
        real_put(key, f, ct)
        drf.remove_member(owner, room["id"], guest)                                    # the owner removes the guest while the bytes are in flight

    drf.files.put = put_then_remove
    with pytest.raises(store.NotFound):
        put(drf, guest, room, "late.bin", b"data")
    assert drf.files.data == {}


def test_folders_are_zips_that_are_checked(drf):
    owner, room = room_with(drf)
    good = _zip(["Photos/a.jpg", "Photos/sub/b.jpg", "Photos/sub/"])
    it = drf.add_file(owner, room["id"], "Photos", good, len(good.getvalue()), kind="folder")
    assert it["kind"] == "folder" and it["file_name"] == "Photos.zip" and it["text"] == "2 files" and it["image"] is False
    assert drf.files.puts[-1][1] == "application/zip"
    puts_before = len(drf.files.puts)
    for bad in (_zip(["../evil.txt"]), _zip(["/abs/x"]), io.BytesIO(b"not a zip")):
        with pytest.raises(store.BadRequest):
            drf.add_file(owner, room["id"], "x.zip", bad, len(bad.getvalue()), kind="folder")
    assert len(drf.files.puts) == puts_before                                          # refused BEFORE anything was stored
    with pytest.raises(store.BadRequest, match="Unknown upload type"):
        drf.add_file(owner, room["id"], "x", io.BytesIO(b"x"), 1, kind="weird")


def test_who_may_download_and_preview(drf, clock):
    owner, room = room_with(drf)
    guest = joined(drf, room)
    stranger = device(drf)
    f = put(drf, owner, room, "n.txt", b"text")
    img = put(drf, owner, room, "p.png", PNG)
    info = drf.file_for_download(guest, room["id"], f["id"])
    assert info["name"] == "n.txt" and info["size"] == 4 and drf.files.data[info["key"]] == b"text"
    assert drf.file_for_download(guest, room["id"], img["id"], preview=True)["mime"] == "image/png"
    with pytest.raises(store.NotFound):
        drf.file_for_download(guest, room["id"], f["id"], preview=True)                # a text file has no inline preview
    for bad in (lambda: drf.file_for_download(stranger, room["id"], f["id"]), lambda: drf.file_for_download("", room["id"], f["id"]),
                lambda: drf.file_for_download(guest, "no-room", f["id"]), lambda: drf.file_for_download(guest, room["id"], "no-item")):
        with pytest.raises(store.NotFound):
            bad()
    t = drf.add_text(owner, room["id"], "just text")
    with pytest.raises(store.NotFound, match="no file"):
        drf.file_for_download(owner, room["id"], t["id"])
    drf.delete_item(owner, room["id"], f["id"])
    with pytest.raises(store.NotFound):
        drf.file_for_download(guest, room["id"], f["id"])                              # deleted: gone for everyone at once
    drf.undo_delete(owner, room["id"], f["id"])
    assert drf.file_for_download(guest, room["id"], f["id"])["name"] == "n.txt"
    clock.advance(10 ** 6)
    with pytest.raises(store.NotFound):
        drf.file_for_download(guest, room["id"], f["id"])                              # expired: no access, even before the erase


def test_text_preview(drf):
    owner, room = room_with(drf)
    ok = put(drf, owner, room, "log.txt", "héllo\n".encode() * 5)
    assert drf.text_preview(owner, room["id"], ok["id"]) == {"name": "log.txt", "text": "héllo\n" * 5, "truncated": False}
    big = put(drf, owner, room, "big.log", b"a" * (store.TEXT_PREVIEW_BYTES + 5))
    t = drf.text_preview(owner, room["id"], big["id"])
    assert t["truncated"] is True and len(t["text"]) == store.TEXT_PREVIEW_BYTES
    for name, data in (("data.bin", b"abc"), ("fake.txt", b"abc\x00def"), ("pic.png", PNG)):
        it = put(drf, owner, room, name, data)
        with pytest.raises(store.BadRequest):
            drf.text_preview(owner, room["id"], it["id"])
    z = _zip(["a.txt"])
    folder = drf.add_file(owner, room["id"], "notes.txt", z, len(z.getvalue()), kind="folder")
    with pytest.raises(store.BadRequest):
        drf.text_preview(owner, room["id"], folder["id"])                              # a folder named like a text file is still a ZIP


def test_files_are_really_erased_when_deleted_expired_or_the_room_goes(drf, clock):
    owner, room = room_with(drf)
    keep = put(drf, owner, room, "keep.bin", b"1")
    gone = put(drf, owner, room, "gone.bin", b"2")
    short = put(drf, owner, room, "short.bin", b"3", retention=60)
    assert len(drf.files.data) == 3
    drf.delete_item(owner, room["id"], gone["id"])
    clock.advance(5)
    drf.items(owner, room["id"])
    assert len(drf.files.data) == 3                                                     # inside the undo window nothing is erased
    drf.undo_delete(owner, room["id"], gone["id"])
    drf.delete_item(owner, room["id"], gone["id"])
    clock.advance(21)                                                                    # past the erase delay of the deleted file (26 s in total)
    drf.items(owner, room["id"])
    assert set(drf.files.data.values()) == {b"1", b"3"}                                  # the 60 s file has not expired yet
    clock.advance(40)
    drf.items(owner, room["id"])
    assert set(drf.files.data.values()) == {b"1"}                                        # now it has: erased from storage, not just hidden
    drf.add_text(owner, room["id"], "stays")
    drf.reset_key(owner, room["id"])
    assert set(drf.files.data.values()) == {b"1"}                                       # a key reset keeps the room's content
    drf.delete_room(owner, room["id"])
    assert drf.files.data == {}


def test_deleted_files_still_count_until_erased_so_disk_use_is_honest(drf, monkeypatch, clock):
    monkeypatch.setattr(store, "ROOM_QUOTA", 100)
    owner, room = room_with(drf)
    f = put(drf, owner, room, "a", b"x" * 100)
    drf.delete_item(owner, room["id"], f["id"])
    with pytest.raises(store.TooLarge):
        put(drf, owner, room, "b", b"x" * 10)                                           # the bytes are still on disk
    clock.advance(21)
    put(drf, owner, room, "b", b"x" * 10)


def test_file_items_appear_in_the_sync_with_everything_the_page_needs(drf):
    owner, room = room_with(drf)
    guest = joined(drf, room, "Phone")
    put(drf, owner, room, "pic.png", PNG)
    items = drf.items(guest, room["id"])["items"]
    assert [(i["kind"], i["file_name"], i["image"], i["mine"]) for i in items] == [("file", "pic.png", True, False)]
    assert "s3_key" not in items[0] and "drop-rooms/" not in json.dumps(items)           # the storage path is never sent to a browser


# ---- the HTTP layer for files ---------------------------------------------------------------------------------------------------------

@pytest.fixture
def webf(web, monkeypatch):
    server, client, lim, clock = web
    files = FakeFiles()
    monkeypatch.setattr(server, "get_files", lambda: files)
    return server, client, files, clock


def _room_pair(client):
    a, b = client(), client()
    room = a.post("/rooms", json={"name": "Files", "nickname": "A"}, headers=H).json()["room"]
    b.post("/join", json={"key": room["key"], "nickname": "B"}, headers=H)
    return a, b, room["id"]


def test_http_upload_then_the_other_device_downloads_exactly_the_bytes(webf):
    server, client, files, clock = webf
    a, b, rid = _room_pair(client)
    data = bytes(range(256)) * 40
    r = a.put(f"/rooms/{rid}/files", params={"name": "résumé \"final\".bin", "retention": 3600}, content=data, headers=H)
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["file_name"] == "résumé _final_.bin" and item["size"] == len(data)
    listed = b.get(f"/rooms/{rid}/items").text
    assert item["id"] in listed and "drop-rooms/" not in listed and base64_free(listed, data)
    d = b.get(f"/rooms/{rid}/files/{item['id']}")
    assert d.status_code == 200 and d.content == data
    h = d.headers
    assert h["content-type"] == "application/octet-stream" and h["x-content-type-options"] == "nosniff" and h["cache-control"] == "no-store"
    assert h["content-disposition"].startswith("attachment;") and "filename*=UTF-8''r%C3%A9sum%C3%A9%20_final_.bin" in h["content-disposition"]
    assert 'filename="r_sum_ _final_.bin"' in h["content-disposition"] and h["content-length"] == str(len(data))
    assert "sandbox" in h["content-security-policy"] and h["cross-origin-resource-policy"] == "same-origin"


def base64_free(text, data):
    return data[:20].hex() not in text


def test_http_only_real_images_are_shown_inline_everything_else_is_a_download(webf):
    server, client, files, clock = webf
    a, b, rid = _room_pair(client)
    png = a.put(f"/rooms/{rid}/files", params={"name": "p.png"}, content=PNG, headers=H).json()["item"]
    svg = a.put(f"/rooms/{rid}/files", params={"name": "x.svg"}, content=SVG, headers=H).json()["item"]
    txt = a.put(f"/rooms/{rid}/files", params={"name": "n.txt"}, content=b"hi", headers=H).json()["item"]
    p = b.get(f"/rooms/{rid}/files/{png['id']}/preview")
    assert p.status_code == 200 and p.headers["content-type"] == "image/png" and p.headers["content-disposition"].startswith("inline;") and "sandbox" in p.headers["content-security-policy"]
    for it in (svg, txt):
        assert b.get(f"/rooms/{rid}/files/{it['id']}/preview").status_code == 404
        assert b.get(f"/rooms/{rid}/files/{it['id']}").headers["content-type"] == "application/octet-stream"
    assert b.get(f"/rooms/{rid}/files/{svg['id']}").headers["content-disposition"].startswith("attachment;")           # the SVG is saved, never rendered
    assert b.get(f"/rooms/{rid}/files/{txt['id']}/text").json()["text"] == "hi"
    assert b.get(f"/rooms/{rid}/files/{svg['id']}/text").status_code == 400


def test_http_strangers_get_nothing_and_writes_need_the_header(webf):
    server, client, files, clock = webf
    a, b, rid = _room_pair(client)
    it = a.put(f"/rooms/{rid}/files", params={"name": "s.txt"}, content=b"secret plans", headers=H).json()["item"]
    stranger = client()
    for path in (f"/rooms/{rid}/files/{it['id']}", f"/rooms/{rid}/files/{it['id']}/preview", f"/rooms/{rid}/files/{it['id']}/text"):
        r = stranger.get(path)
        assert r.status_code == 404 and b"secret" not in r.content
    assert stranger.put(f"/rooms/{rid}/files", params={"name": "x"}, content=b"x", headers=H).status_code == 404       # not a member: refused before the body is used
    assert a.put(f"/rooms/{rid}/files", params={"name": "x"}, content=b"x").status_code == 403                          # no request header
    assert len(files.data) == 1


def test_http_too_big_is_refused_without_storing_anything(webf, monkeypatch):
    server, client, files, clock = webf
    a, b, rid = _room_pair(client)
    monkeypatch.setattr(server.store, "MAX_FILE", 1000)
    r = a.put(f"/rooms/{rid}/files", params={"name": "big.bin"}, content=b"x" * 1500, headers=H)          # Content-Length says it is too big
    assert r.status_code == 413 and "most that can be uploaded here is 1000 bytes" in r.json()["detail"]
    r = a.put(f"/rooms/{rid}/files", params={"name": "big.bin"}, content=iter([b"x" * 600, b"x" * 600]), headers=H)   # chunked: no Content-Length, counted as it arrives
    assert r.status_code == 413 and "bigger than" in r.json()["detail"]
    assert files.data == {}
    assert a.put(f"/rooms/{rid}/files", params={"name": "e.bin"}, content=b"", headers=H).status_code == 400
    ok = a.put(f"/rooms/{rid}/files", params={"name": "fits.bin"}, content=b"x" * 1000, headers=H)
    assert ok.status_code == 200 and len(files.data) == 1


def test_http_folder_upload_and_unsafe_zip(webf):
    server, client, files, clock = webf
    a, b, rid = _room_pair(client)
    good = _zip(["Folder/a.txt", "Folder/b.txt"]).getvalue()
    r = a.put(f"/rooms/{rid}/files", params={"name": "Folder", "kind": "folder"}, content=good, headers=H)
    assert r.status_code == 200 and r.json()["item"]["kind"] == "folder" and r.json()["item"]["text"] == "2 files"
    assert zipfile.ZipFile(io.BytesIO(b.get(f"/rooms/{rid}/files/{r.json()['item']['id']}").content)).namelist() == ["Folder/a.txt", "Folder/b.txt"]
    bad = a.put(f"/rooms/{rid}/files", params={"name": "Evil", "kind": "folder"}, content=_zip(["../../x"]).getvalue(), headers=H)
    assert bad.status_code == 400 and "unsafe" in bad.json()["detail"] and len(files.data) == 1


def test_http_delete_hides_the_download_and_erases_after_the_window(webf):
    server, client, files, clock = webf
    a, b, rid = _room_pair(client)
    it = a.put(f"/rooms/{rid}/files", params={"name": "d.bin"}, content=b"bytes", headers=H).json()["item"]
    a.delete(f"/rooms/{rid}/items/{it['id']}", headers=H)
    assert b.get(f"/rooms/{rid}/files/{it['id']}").status_code == 404 and len(files.data) == 1
    clock.advance(25)
    b.get(f"/rooms/{rid}/items")
    assert files.data == {}


def test_http_the_app_serves_only_its_two_scripts(webf):
    server, client, files, clock = webf
    a = client()
    for name in ("app.js", "zip.js"):
        assert a.get("/" + name).status_code == 200, name
    for name in ("server.py", "store.py", "ui/zip.js", "zip.py"):
        assert a.get("/" + name).status_code in (404, 405), name

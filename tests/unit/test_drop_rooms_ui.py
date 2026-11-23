"""Drop Rooms (roadmap DR1): TWO real browsers ("devices", each with its own cookies) in one room, against the REAL server, on a TEMPORARY
database and Vault (your own are never touched). Device A creates a room; device B joins with the key; they chat, edit each other's text,
delete and undo, the owner resets the key (B is thrown out and rejoins), then deletes the room. Skips without chromium / uvicorn / cryptography."""

import importlib.util
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "drop-rooms"
DRIVER = (REPO / "tests" / "unit" / "drop_rooms_ui_driver.js").read_text(encoding="utf-8")
sys.path.insert(0, str(REPO))

pytest.importorskip("cryptography")
uvicorn = pytest.importorskip("uvicorn")
from cryptography.fernet import Fernet  # noqa: E402

from core import vault  # noqa: E402
from core.state.filecache import FileCache  # noqa: E402
from core.state.sqlstore import SqlStore  # noqa: E402

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


class _Harness:
    """ASGI wrapper: injects the driver into the page, hosts a tiny key/value mailbox for the two browsers, receives their results."""

    def __init__(self, app, results, kv):
        self.app, self.results, self.kv = app, results, kv

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == "/__driver.js":
            return await self._reply(send, DRIVER.encode(), b"application/javascript")
        if path.startswith("/__kv/"):
            name = path[len("/__kv/"):]
            if scope["method"] == "POST":
                self.kv[name] = (await self._body(receive)).decode()
                return await self._reply(send, b"ok", b"text/plain")
            return await self._reply(send, self.kv.get(name, "").encode(), b"text/plain")
        if path == "/__result":
            role = dict(p.split("=") for p in scope["query_string"].decode().split("&"))["role"]
            self.results[role] = json.loads(await self._body(receive) or b"{}")
            return await self._reply(send, b"ok", b"text/plain")
        if path != "/":
            return await self.app(scope, receive, send)
        start, chunks = {}, []

        async def grab(message):
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    body = b"".join(chunks).replace(b"</body>", b'<script src="__driver.js"></script></body>')
                    headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
                    await send({**start, "headers": headers})
                    await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, grab)

    @staticmethod
    async def _body(receive):
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                return body

    @staticmethod
    async def _reply(send, body, ctype):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", ctype), (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})


class _Limiter:
    def hit(self, key, limit, window):
        return True


class _MemFiles:
    """File storage for the test: bytes in a dict (what S3Files does against Toolbox's storage)."""

    def __init__(self):
        self.data = {}

    def put(self, key, fileobj, content_type):
        self.data[key] = fileobj.read()

    def delete(self, key):
        self.data.pop(key, None)

    def head(self, key, n):
        return self.data[key][:n]

    def stream(self, key):
        d = self.data[key]
        for i in range(0, len(d), 4096):
            yield d[i:i + 4096]


@pytest.mark.skipif(not CHROMIUM, reason="chromium is not installed")
def test_two_devices_in_one_room_end_to_end(tmp_path, monkeypatch):
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

    spec = importlib.util.spec_from_file_location("drop_rooms_server_ui", TOOL / "server.py")
    server_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = server_mod
    spec.loader.exec_module(server_mod)
    db = SqlStore("drop_rooms", sqlite_path=tmp_path / "dr.db", ddl=server_mod.store.SCHEMA, backend="sqlite")
    monkeypatch.setattr(server_mod, "STORE", db)
    monkeypatch.setattr(server_mod, "_initialised", False)
    monkeypatch.setattr(server_mod, "get_limiter", lambda: _Limiter())
    files = _MemFiles()
    monkeypatch.setattr(server_mod, "get_files", lambda: files)

    results, kv = {}, {}
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(_Harness(server_mod.app, results, kv), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started, "the test server did not start"
    procs, profiles = [], []
    try:
        for role in ("A", "B"):                                   # two browsers = two devices: separate profiles, separate cookies
            prof = tempfile.mkdtemp(prefix=f"dr-ui-{role}-")
            profiles.append(prof)
            procs.append(subprocess.Popen([CHROMIUM, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}", "--window-size=1100,1000",
                                           f"http://127.0.0.1:{port}/?role={role}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        deadline = time.time() + 150
        while time.time() < deadline and len(results) < 2:
            time.sleep(0.5)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        srv.should_exit = True
        t.join(timeout=10)
        for prof in profiles:
            shutil.rmtree(prof, ignore_errors=True)
    assert set(results) == {"A", "B"}, f"only {sorted(results)} reported; mailbox: {kv}"
    for role, res in results.items():
        failed = {k: v for k, v in res.items() if v is not True and not k.endswith("[detail]")}
        details = {k: v for k, v in res.items() if k.endswith("[detail]")}
        assert not failed, f"device {role} failed: {sorted(failed)} details: {details}"
    assert len(results["A"]) >= 32 and len(results["B"]) >= 26, (len(results["A"]), len(results["B"]))
    # the folder B downloaded is a real, safe ZIP with A's two files in it
    import base64
    import io
    import zipfile

    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(kv["zipdata"])))
    assert z.testzip() is None and sorted(z.namelist()) == ["Docs/a.txt", "Docs/sub/b.txt"]
    assert z.read("Docs/a.txt") == b"folder file A" and z.read("Docs/sub/b.txt") == b"folder file B"
    assert files.data == {}, "after the owner deleted the room, no file bytes may remain in storage"

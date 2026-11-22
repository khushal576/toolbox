"""Key Store (roadmap KS2): the REAL page in a REAL browser, against the REAL server on a TEMPORARY vault (your own Vault is never touched).

Starts key-store/server.py with uvicorn on a free port, injects tests/unit/key_store_ui_driver.js into the page, opens it in headless
Chromium and waits for the driver to post {check: true/false}. Skips when chromium, uvicorn or cryptography is missing."""

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
TOOL = REPO / "key-store"
DRIVER = (REPO / "tests" / "unit" / "key_store_ui_driver.js").read_text(encoding="utf-8")
sys.path.insert(0, str(REPO))

pytest.importorskip("cryptography")
uvicorn = pytest.importorskip("uvicorn")
from cryptography.fernet import Fernet  # noqa: E402

from core import vault  # noqa: E402
from core.state.filecache import FileCache  # noqa: E402
from core.state.sqlstore import SqlStore  # noqa: E402

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


class _Inject:
    """ASGI wrapper: adds the driver script to the page, serves it, and receives the results."""

    def __init__(self, app, on_result):
        self.app, self.on_result = app, on_result

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == "/__driver.js":
            return await self._reply(send, DRIVER.encode(), b"application/javascript")
        if path == "/__result":
            body = b""
            while True:
                msg = await receive()
                body += msg.get("body", b"")
                if not msg.get("more_body"):
                    break
            self.on_result(json.loads(body or b"{}"))
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
    async def _reply(send, body, ctype):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", ctype), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


@pytest.fixture
def temp_vault(tmp_path, monkeypatch):
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


@pytest.mark.skipif(not CHROMIUM, reason="chromium is not installed")
def test_the_store_page_end_to_end(temp_vault):
    spec = importlib.util.spec_from_file_location("key_store_server_ui", TOOL / "server.py")
    server_mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = server_mod
    spec.loader.exec_module(server_mod)

    got, done = {}, threading.Event()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(_Inject(server_mod.app, lambda r: (got.update(r), done.set())), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started, "the test server did not start"
    prof = tempfile.mkdtemp(prefix="ks-ui-")
    proc = subprocess.Popen([CHROMIUM, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}", "--window-size=1100,1500",
                             f"http://127.0.0.1:{port}/"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        finished = done.wait(timeout=120)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv.should_exit = True
        t.join(timeout=10)
        shutil.rmtree(prof, ignore_errors=True)
    assert finished, "the page driver never reported (did the page fail to load?)"
    failed = {k: v for k, v in got.items() if v is not True and not k.endswith("[detail]")}
    details = {k: v for k, v in got.items() if k.endswith("[detail]")}
    assert not failed, f"UI checks failed: {sorted(failed)}  details: {details}"
    assert len(got) >= 35, f"only {len(got)} checks ran"
    # nothing the test saved is left in the real tool's Vault: it was a temporary one
    assert all(s["kind"] == "key_store" for s in temp_vault.list_secrets())

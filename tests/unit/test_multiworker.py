"""Roadmap B9: several web workers — workspace switches reach every worker, singleton plugins are proxied to their
one process, the proxy streams and degrades cleanly. No tool code is imported here."""

import asyncio
import importlib
import os
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]


def _fresh_main(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("TOOLBOX_WORKSPACE_FILE", str(tmp_path / "workspace.yaml"))
    for k in ("TOOLBOX_ROLE", "TOOLBOX_SINGLETON_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.syspath_prepend(str(REPO))
    sys.modules.pop("main", None)
    return importlib.import_module("main")


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    sys.modules.pop("main", None)


def test_healthz_reports_role(monkeypatch, tmp_path):
    main = _fresh_main(monkeypatch, tmp_path)
    r = TestClient(main.app).get("/healthz")
    assert r.status_code == 200 and r.json()["role"] == "web"


def test_a_switch_flipped_by_another_worker_reaches_this_one(monkeypatch, tmp_path):
    main = _fresh_main(monkeypatch, tmp_path)
    c = TestClient(main.app)
    assert c.get("/tools/encode-decode/").status_code != 404
    # another worker process saves workspace.yaml (we only share the file)
    ws = tmp_path / "workspace.yaml"
    ws.write_text(yaml.safe_dump({"enabled": {"encode-decode": False}}))
    os.utime(ws, (time.time() + 5, time.time() + 5))  # make sure the mtime differs even on coarse filesystems
    main._ws_checked = 0.0  # skip the once-a-second throttle
    r = c.get("/tools/encode-decode/")
    assert r.status_code == 404 and "turned off" in r.text.lower()


def test_web_role_proxies_singletons_and_mounts_the_rest(monkeypatch, tmp_path):
    main = _fresh_main(monkeypatch, tmp_path, TOOLBOX_SINGLETON_URL="http://singletons:8080")
    st = {p["name"]: p["state"] for p in TestClient(main.app).get("/api/workspace/status").json()["plugins"]}
    assert st["sql-studio"] == "remote" and st["schema-map"] == "remote" and st["df-studio"] == "not_loaded"


def test_singletons_role_mounts_only_singletons(monkeypatch, tmp_path):
    main = _fresh_main(monkeypatch, tmp_path, TOOLBOX_ROLE="singletons")
    assert set(main._slots) >= {"sql-studio", "schema-map"} and "df-studio" not in main._slots
    assert TestClient(main.app).get("/tools/df-studio/").status_code == 404


def test_without_singleton_url_everything_is_in_process(monkeypatch, tmp_path):
    main = _fresh_main(monkeypatch, tmp_path)
    assert type(main._slots["sql-studio"].app).__name__ == "LazyApp"


# ---- ProxyApp ---------------------------------------------------------------------------------------------------

@pytest.fixture
def upstream():
    """A real HTTP server (uvicorn in a thread) standing in for the singletons process."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response, StreamingResponse
    from starlette.routing import Route

    async def echo(request: Request):
        body = await request.body()
        return JSONResponse({"path": request.url.path, "query": request.url.query, "len": len(body),
                             "cookie": request.headers.get("cookie"), "xff": request.headers.get("x-forwarded-for"),
                             "host": request.headers.get("host")},
                            headers={"set-cookie": "sid=abc; Path=/"})

    async def big(request: Request):
        async def gen():
            for _ in range(64):
                yield b"x" * 65536
        return StreamingResponse(gen(), media_type="application/octet-stream")

    async def redirect(request: Request):
        return Response(status_code=307, headers={"location": "/tools/sql-studio/elsewhere"})

    app = Starlette(routes=[Route("/tools/sql-studio/echo", echo, methods=["GET", "POST"]),
                            Route("/tools/sql-studio/big", big), Route("/tools/sql-studio/go", redirect)])
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


def _proxy_client(base):
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from core_plugins import proxy as proxy_mod
    from core_plugins.proxy import ProxyApp

    proxy_mod._client = None  # a fresh httpx client bound to this test's event loop
    return TestClient(Starlette(routes=[Mount("/tools/sql-studio", ProxyApp("sql-studio", "SQL Studio", base))]))


def test_proxy_forwards_path_query_body_cookies_and_headers(upstream):
    c = _proxy_client(upstream)
    r = c.post("/tools/sql-studio/echo?a=1&b=two", content=b"y" * 300_000, cookies={"sid": "s1"})
    j = r.json()
    assert r.status_code == 200 and j["path"] == "/tools/sql-studio/echo" and j["query"] == "a=1&b=two"
    assert j["len"] == 300_000 and j["cookie"] == "sid=s1" and j["xff"]
    assert j["host"] == "testserver"  # the browser's Host, not the upstream's address (C2)
    assert r.headers["set-cookie"].startswith("sid=abc")


def test_proxy_streams_large_responses_and_passes_redirects(upstream):
    c = _proxy_client(upstream)
    assert len(c.get("/tools/sql-studio/big").content) == 64 * 65536
    r = c.get("/tools/sql-studio/go", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/tools/sql-studio/elsewhere"


def test_proxy_shows_a_clear_page_when_the_singleton_process_is_down():
    c = _proxy_client("http://127.0.0.1:9")  # nothing listens there
    r = c.get("/tools/sql-studio/")
    assert r.status_code == 503 and "docker compose logs 127.0.0.1" in r.text


def test_gateway_mode_proxies_every_python_tool_and_imports_none(monkeypatch, tmp_path):
    """Roadmap C2: with TOOLBOX_RUNTIME_URLS the web role is a pure gateway."""
    urls = ",".join(f"{r}=http://rt-{r}:8080" for r in ("light", "data", "pgtools", "ssh", "latex", "datadiff"))
    main = _fresh_main(monkeypatch, tmp_path, TOOLBOX_RUNTIME_URLS=urls, TOOLBOX_SINGLETON_URL="http://singletons:8080")
    for m in main._registry.ordered():
        app = main._slots[m.name].app if m.name in main._slots else None
        if m.kind == "python" and main._workspace.is_enabled(m):
            assert type(app).__name__ == "ProxyApp", m.name
            assert app.base_url == ("http://singletons:8080" if m.singleton else f"http://rt-{m.runtime}:8080")
    assert main._lazy == {}  # nothing importable is even prepared in the gateway

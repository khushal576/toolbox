"""Custom apps from plugins/ (roadmap A5): loader rules, static serving + sandbox, external redirect, main.py wiring."""

import importlib
import sys
from pathlib import Path

import pytest
import yaml
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import ExternalApp, StaticApp, discover  # noqa: E402
from core_plugins.lazy import STATIC_CSP  # noqa: E402


def plugin(dirpath: Path, folder: str, manifest: dict, files: dict | None = None) -> Path:
    d = dirpath / folder
    d.mkdir(parents=True)
    (d / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    for rel, body in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(body, encoding="utf-8")
    return d


def test_python_plugins_are_refused_from_custom_app_folders(tmp_path):
    plugins = tmp_path / "plugins"
    plugin(plugins, "sneaky", {"name": "sneaky", "title": "S", "kind": "python", "entry": "x.y:app", "runtime": "light"})
    plugin(plugins, "page", {"name": "page", "title": "P", "kind": "static"}, {"ui/index.html": "<p>hi</p>"})
    reg = discover(tmp_path, extra_dirs=[plugins])
    assert list(reg.plugins) == ["page"]
    assert any("not allowed in a custom-app folder" in e for e in reg.errors)


@pytest.fixture
def static_client(tmp_path):
    d = plugin(tmp_path, "app", {"name": "app", "title": "A", "kind": "static", "entry": "index.html"}, {
        "index.html": "<h1>home</h1>", "css/site.css": "body{}", ".secret": "no", "sub/index.html": "<p>sub</p>"})
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    return TestClient(Starlette(routes=[Mount("/tools/app", StaticApp("app", d, "index.html"))]))


def test_static_serves_entry_and_files_with_sandbox(static_client):
    r = static_client.get("/tools/app/")
    assert r.status_code == 200 and r.text == "<h1>home</h1>" and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == STATIC_CSP and "allow-same-origin" not in STATIC_CSP
    assert static_client.get("/tools/app/css/site.css").headers["content-type"].startswith("text/css")
    assert static_client.get("/tools/app/sub/").text == "<p>sub</p>"


@pytest.mark.parametrize("path", ["/tools/app/.secret", "/tools/app/manifest.yaml", "/tools/app/../outside.txt",
                                  "/tools/app/%2e%2e/outside.txt", "/tools/app/missing.js"])
def test_static_never_serves_hidden_manifest_or_outside_files(static_client, path):
    assert static_client.get(path).status_code == 404


def test_static_is_read_only(static_client):
    assert static_client.post("/tools/app/").status_code == 405


def test_external_redirects():
    c = TestClient(Starlette(routes=[Mount("/tools/ext", ExternalApp("ext", "https://example.com/"))]))
    r = c.get("/tools/ext/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "https://example.com/"


def test_main_lists_samples_off_and_switches_them_on(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLBOX_WORKSPACE_FILE", str(tmp_path / "workspace.yaml"))
    monkeypatch.setenv("TOOLBOX_PLUGINS_DIR", str(REPO / "plugins"))
    monkeypatch.syspath_prepend(str(REPO))
    sys.modules.pop("main", None)
    main = importlib.import_module("main")
    try:
        c = TestClient(main.app)
        st = {p["name"]: p for p in c.get("/api/workspace/status").json()["plugins"]}
        assert st["hello-static"]["state"] == "disabled" and st["example-link"]["state"] == "disabled"
        assert c.get("/tools/hello-static/").status_code == 404
        assert c.post("/api/workspace/plugins/hello-static", json={"enabled": True}).status_code == 200
        r = c.get("/tools/hello-static/")
        assert r.status_code == 200 and "custom app" in r.text and r.headers["content-security-policy"] == STATIC_CSP
        assert c.post("/api/workspace/plugins/example-link", json={"enabled": True}).status_code == 200
        assert c.get("/tools/example-link/", follow_redirects=False).headers["location"] == "https://example.com/"
        st = {p["name"]: p for p in c.get("/api/workspace/status").json()["plugins"]}
        assert st["hello-static"]["state"] == "ready" and st["example-link"]["state"] == "ready"
    finally:
        sys.modules.pop("main", None)

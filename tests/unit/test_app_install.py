"""Roadmap G1: Toolbox is installable as an app (web app manifest + icons + favicon)."""

import importlib
import io
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOLBOX_WORKSPACE_FILE", str(tmp_path / "workspace.yaml"))
    monkeypatch.syspath_prepend(str(REPO))
    sys.modules.pop("main", None)
    yield TestClient(importlib.import_module("main").app)
    sys.modules.pop("main", None)


def test_manifest_meets_chromium_install_criteria(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["name"] and m["short_name"] and m["start_url"] == "/" and m["display"] == "standalone"
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes


def test_every_icon_is_served_at_its_declared_size(client):
    pil = pytest.importorskip("PIL.Image")
    m = client.get("/manifest.webmanifest").json()
    for icon in m["icons"]:
        r = client.get(icon["src"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        w, h = pil.open(io.BytesIO(r.content)).size
        assert f"{w}x{h}" == icon["sizes"], icon["src"]
    assert client.get("/favicon.ico").headers["content-type"] == "image/png"
    assert client.get("/icons/../main.py").status_code == 404 and client.get("/icons/nope.png").status_code == 404


def test_workspace_page_links_the_manifest(client):
    html = client.get("/").text
    assert '<link rel="manifest" href="/manifest.webmanifest"' in html and 'name="theme-color"' in html

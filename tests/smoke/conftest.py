"""
Smoke tests for the running Toolbox (roadmap session S0.3).

They talk to a LIVE server over HTTP (default http://localhost:8000, override with TOOLBOX_URL) and
need nothing external: no real database, SSH server or internet. Run them with `scripts/smoke.sh`.

The list of tools comes from the plugin manifests (core_plugins.discover, same as main.py) so a new
tool is picked up automatically; test_api.py then fails until the new tool is classified.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("TOOLBOX_URL", "http://localhost:8000").rstrip("/")


sys.path.insert(0, str(REPO))
from core_plugins import discover  # noqa: E402


def mounted_tools() -> list[str]:
    """Names of the plugins main.py mounts (kind: python), in display order."""
    return [m.name for m in discover(REPO).ordered() if m.kind == "python"]


class Response:
    def __init__(self, status: int, headers, body: bytes):
        self.status, self.headers, self.body = status, headers, body

    @property
    def ctype(self) -> str:
        return (self.headers.get("Content-Type") or "").split(";")[0].strip()

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.body)


def request(method: str, path: str, body: dict | None = None, timeout: float = 60) -> Response:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return Response(r.status, r.headers, r.read())
    except urllib.error.HTTPError as e:
        return Response(e.code, e.headers, e.read())


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: needs headless Chromium + chromedriver")


@pytest.fixture(scope="session", autouse=True)
def server_up():
    try:
        r = request("GET", "/", timeout=5)
    except Exception as e:  # pragma: no cover - environment problem, not a test failure
        pytest.exit(f"Toolbox is not reachable at {BASE_URL}: {e}. Start it with `docker compose up -d`.", 2)
    if r.status != 200:
        pytest.exit(f"Toolbox home page returned {r.status} at {BASE_URL}", 2)

"""Key Store (roadmap KS1): the password generator and the tool's serving layer.

* the generator logic is browser code (key-store/ui/keygen.js) executed by node (needs `node`, skips without it);
* the server tests load key-store/server.py straight from the checkout (inside the container it is the package key_store);
* guard rails: the generator must never use Math.random, and the page must never load anything from another site.
"""

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "key-store"
UI = TOOL / "ui"


def test_generator_logic_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(REPO / "tests" / "unit" / "key_store_keygen_cases.js")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("OK ")


def _strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", code)


JS_FILES = ("keygen.js", "generator.js", "store.js")


def test_no_weak_randomness_in_the_page_code():
    # Math.random is predictable: passwords must come from crypto.getRandomValues only.
    for name in (*JS_FILES, "index.html"):
        assert "Math.random" not in _strip_comments((UI / name).read_text(encoding="utf-8")), f"{name} uses Math.random"
    assert "getRandomValues" in (UI / "keygen.js").read_text(encoding="utf-8")


def test_the_generator_code_makes_no_network_calls():
    for name in ("keygen.js", "generator.js"):
        code = _strip_comments((UI / name).read_text(encoding="utf-8"))
        assert not re.search(r"fetch\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource|https?://", code), f"{name} must not send anything anywhere"


def test_the_store_page_talks_only_to_this_site_through_one_helper():
    code = _strip_comments((UI / "store.js").read_text(encoding="utf-8"))
    assert len(re.findall(r"fetch\(", code)) == 1, "all requests must go through the single api() helper"
    assert not re.search(r"XMLHttpRequest|sendBeacon|WebSocket|EventSource|https?://", code)
    calls = re.findall(r"api\(\s*([^,)]+)", code)
    assert calls and all(not c.strip().startswith(('"/', "'/", "`/")) for c in calls), "api() paths must be relative"
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"(src|href)\s*=\s*[\"']https?://", html) and "fetch(" not in html


def test_secrets_never_go_to_storage_or_the_ai_panel_or_html():
    for name in (*JS_FILES, "index.html"):
        code = _strip_comments((UI / name).read_text(encoding="utf-8"))
        assert "innerHTML" not in code and "insertAdjacentHTML" not in code and "document.write" not in code, f"{name} builds HTML from strings"
        assert "postMessage" not in code and "toolbox-context" not in code, f"{name} must never hand page content to the AI helper panel"
        assert "console.log" not in code and "console.debug" not in code, f"{name} logs"
        assert "sessionStorage" not in code and "indexedDB" not in code
        for key in re.findall(r"localStorage\.(?:setItem|getItem)\(\s*[\"']([^\"']+)", code):
            assert key in ("keystore.genopts", "keystore.tab"), f"{name} stores {key!r} in localStorage"
    store_js = (UI / "store.js").read_text(encoding="utf-8")
    assert "localStorage.setItem" not in store_js, "store.js must not write to localStorage"


def test_page_uses_relative_paths():
    html = (UI / "index.html").read_text(encoding="utf-8")
    for src in re.findall(r"<script[^>]+src=[\"']([^\"']+)", html):
        assert not src.startswith("/") and "://" not in src, src


@pytest.fixture(scope="module")
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    pytest.importorskip("cryptography")                 # server.py imports core.vault
    import sys

    sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("key_store_server_under_test", TOOL / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return TestClient(mod.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True, "tool": "key-store"}


def test_page_is_served_with_a_locked_down_policy(client):
    r = client.get("/")
    assert r.status_code == 200 and "Key Store" in r.text
    csp = r.headers["content-security-policy"]
    assert "connect-src 'self'" in csp and "default-src 'self'" in csp and "object-src 'none'" in csp
    assert r.headers["cache-control"] == "no-store"


def test_scripts_are_served_as_javascript(client):
    for name in ("keygen.js", "words.js", "generator.js", "store.js"):
        r = client.get("/" + name)
        assert r.status_code == 200 and "javascript" in r.headers["content-type"], name
    assert "KeyGen" in client.get("/keygen.js").text
    assert "KEYSTORE_WORDS" in client.get("/words.js").text


def test_unknown_paths_do_not_leak_files(client):
    for p in ("/server.py", "/../server.py", "/manifest.yaml", "/%2e%2e/server.py"):
        assert client.get(p).status_code in (404, 405, 422), p


def test_the_wordlist_credit_is_kept():
    head = (UI / "words.js").read_text(encoding="utf-8")[:400]
    assert "EFF" in head and "Creative Commons" in head

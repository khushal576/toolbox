"""Drop Rooms (roadmap DR1): static guard rails on the page code. No browser needed."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI = REPO / "drop-rooms" / "ui"


def _code(name: str) -> str:   # also scans zip.js below
    code = (UI / name).read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", code)


def test_the_page_talks_only_to_this_site_through_one_helper():
    js = _code("app.js")
    assert len(re.findall(r"fetch\(", js)) == 1, "all requests must go through the single api() helper"
    assert not re.search(r"sendBeacon|WebSocket|EventSource|https?://", js), "no absolute URLs or other transports"
    assert len(re.findall(r"new XMLHttpRequest", js)) == 1 and "function upload(path, body, onProgress)" in js, "uploads go through the single upload() helper"
    assert 'xhr.open("PUT", path)' in js and 'xhr.setRequestHeader("X-Drop-Rooms", "1")' in js
    calls = re.findall(r"\bapi\(\s*([^,)]+)", js) + re.findall(r"\bupload\(\s*([^,)]+)", js)
    assert calls and all(not c.strip().startswith(('"/', "'/", "`/")) for c in calls), "api()/upload() paths must be relative"
    assert "X-Drop-Rooms" in js, "the request-forgery header must be sent"
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"(src|href)\s*=\s*[\"']https?://", html) and "fetch(" not in html
    for src in re.findall(r"<script[^>]+src=[\"']([^\"']+)", html):
        assert not src.startswith("/") and "://" not in src, src


def test_messages_and_keys_are_never_built_as_html():
    for name in ("app.js", "index.html"):
        code = _code(name)
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function", code), f"{name} builds HTML or code from strings"
        assert "console.log" not in code and "console.debug" not in code, f"{name} logs"
        assert "postMessage" not in code and "toolbox-context" not in code, f"{name} must never hand page content to the AI helper panel"
        assert "sessionStorage" not in code and "indexedDB" not in code and "document.cookie" not in code


def test_only_harmless_things_are_kept_in_the_browser():
    js = _code("app.js")
    keys = set(re.findall(r"ls(?:Get|Set)\(\s*[\"']([^\"']+)", js)) | set(re.findall(r"localStorage\.(?:setItem|getItem)\(\s*[\"']([^\"']+)", js))
    assert keys == {"droprooms.nick", "droprooms.last"}, keys
    for call in re.findall(r"lsSet\(([^;]+)\)", js):
        assert "key" not in call.lower().replace("droprooms", "").replace("lskey", ""), f"a key must never be stored: lsSet({call})"


def test_links_in_messages_are_http_only_and_safe():
    js = _code("app.js")
    assert 'u.protocol === "http:" || u.protocol === "https:"' in js and 'a.rel = "noopener noreferrer"' in js


def test_the_room_key_is_cleared_from_the_page_when_its_dialog_closes():
    js = _code("app.js")
    assert re.search(r'\$\("keyDlg"\)\.addEventListener\("close"[^;]*kBox[^;]*textContent = ""', js)


def test_the_zip_builder_has_no_network_and_no_html():
    js = _code("zip.js")
    assert not re.search(r"fetch\(|XMLHttpRequest|sendBeacon|WebSocket|https?://|innerHTML|eval\(|document\.", js)
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'src="zip.js"' in html and html.index('src="zip.js"') < html.index('src="app.js"')


def test_downloads_are_plain_links_to_this_tool_and_never_blob_urls():
    js = _code("app.js")
    assert "createObjectURL" not in js and "srcdoc" not in js and "iframe" not in js.lower()
    assert 'dl.setAttribute("download"' in js and "const fileUrl = " in js

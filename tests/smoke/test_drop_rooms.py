"""Smoke tests for Drop Rooms (DR1). They run against the LIVE stack: scripts/smoke.sh. They need no outside system and create no rooms.
(GET /rooms with no cookie creates one tiny device row, by design; it is forgotten after 30 idle days.) A tool switched off in Settings is skipped."""

import pytest

from conftest import request


@pytest.mark.parametrize("tool", ["drop-rooms"])
def test_health(tool):
    r = request("GET", f"/tools/{tool}/health")
    assert r.status == 200 and r.json() == {"ok": True, "tool": tool}


@pytest.mark.parametrize("tool", ["drop-rooms"])
def test_page_and_script(tool):
    page = request("GET", f"/tools/{tool}/")
    assert page.status == 200 and "Drop Rooms" in page.text
    js = request("GET", f"/tools/{tool}/app.js")
    assert js.status == 200 and "X-Drop-Rooms" in js.text


@pytest.mark.parametrize("tool", ["drop-rooms"])
def test_meta_and_rooms_api(tool):
    meta = request("GET", f"/tools/{tool}/meta")
    assert meta.status == 200 and meta.json()["max_retention"] == 2592000 and 3600 in meta.json()["presets"]
    rooms = request("GET", f"/tools/{tool}/rooms")
    assert rooms.status == 200 and rooms.json() == {"ok": True, "rooms": []}            # a brand-new device is in no room
    assert rooms.headers.get("Cache-Control") == "no-store"


@pytest.mark.parametrize("tool", ["drop-rooms"])
def test_writes_need_the_request_header(tool):
    r = request("POST", f"/tools/{tool}/join", {"key": "AAAAA-AAAAA-AAAAA-AAAAA-AAAAA", "nickname": "x"})
    assert r.status == 403


@pytest.mark.parametrize("tool", ["drop-rooms"])
def test_zip_script_and_file_routes_need_a_room(tool):
    js = request("GET", f"/tools/{tool}/zip.js")
    assert js.status == 200 and "DropZip" in js.text
    assert request("GET", f"/tools/{tool}/rooms/nope/files/nope").status == 404           # a stranger gets nothing, and the same answer as an unknown room
    assert request("PUT", f"/tools/{tool}/rooms/nope/files?name=x", None).status == 403   # writes need the request header

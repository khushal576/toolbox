"""DataFrame Studio keeps its session outside the process (roadmap B2): load → step → /session restores it.
Creates one throwaway session (a 3-row CSV); the tool's sweep removes it after the session TTL."""

import http.cookiejar
import json
import urllib.request
import uuid

from conftest import BASE_URL

BASE = BASE_URL + "/tools/df-studio"


def _opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _post_file(op, path, filename, content: bytes):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: text/csv\r\n\r\n").encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + path, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(op.open(req, timeout=60).read())


def _post_json(op, path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    return json.loads(op.open(req, timeout=60).read())


def test_session_round_trip_through_shared_state():
    op = _opener()
    loaded = _post_file(op, "/load", "smoke.csv", b"a,b\n3,x\n1,y\n2,z\n")
    assert loaded["row_count"] == 3, loaded
    after = _post_json(op, "/step", {"type": "filter_rows", "params": {"expr": "a > 1"}})
    assert after["row_count"] == 2 and len(after["steps"]) == 1, after
    restored = json.loads(op.open(BASE + "/session", timeout=60).read())
    assert restored["active"] is True and restored["row_count"] == 2 and len(restored["steps"]) == 1

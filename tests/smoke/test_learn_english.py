"""Smoke tests for Speak English. They run against the LIVE stack (scripts/smoke.sh). READ-ONLY: they never write the owner's progress."""

from conftest import request


def test_health():
    r = request("GET", "/tools/learn-english/health")
    assert r.status == 200 and r.json() == {"ok": True, "tool": "learn-english"}


def test_page_and_content():
    assert request("GET", "/tools/learn-english/").status == 200
    assert request("GET", "/tools/learn-english/modules/manifest.js").status == 200
    assert request("GET", "/tools/learn-english/modules/m001.js").status == 200


def test_progress_is_guarded():
    assert request("GET", "/tools/learn-english/progress").status == 403

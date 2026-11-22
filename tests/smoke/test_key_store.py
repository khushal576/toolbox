"""Smoke tests for Key Store (KS1). They run against the LIVE stack: scripts/smoke.sh.
They need no outside system. A tool switched off in Settings is skipped, not failed (tests/smoke/conftest.py)."""

import pytest

from conftest import request


@pytest.mark.parametrize("tool", ["key-store"])
def test_health(tool):
    r = request("GET", f"/tools/{tool}/health")
    assert r.status == 200 and r.json() == {"ok": True, "tool": tool}


@pytest.mark.parametrize("tool", ["key-store"])
def test_page_and_scripts(tool):
    page = request("GET", f"/tools/{tool}/")
    assert page.status == 200 and "Key Store" in page.text
    for name, marker in (("keygen.js", "KeyGen"), ("words.js", "KEYSTORE_WORDS")):
        r = request("GET", f"/tools/{tool}/{name}")
        assert r.status == 200 and marker in r.text, name


@pytest.mark.parametrize("tool", ["key-store"])
def test_entries_api_is_up_and_returns_no_values(tool):
    """Read-only: lists whatever is saved in the Vault. A value must never appear in a list."""
    meta = request("GET", f"/tools/{tool}/meta")
    assert meta.status == 200 and any(t["key"] == "connection_string" for t in meta.json()["types"])
    lst = request("GET", f"/tools/{tool}/entries")
    assert lst.status == 200 and lst.json()["ok"] and "counts" in lst.json()
    assert all("value" not in e for e in lst.json()["entries"])
    assert lst.headers.get("Cache-Control") == "no-store"

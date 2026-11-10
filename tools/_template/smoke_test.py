"""Smoke tests for __TOOL_TITLE__ (created from tools/_template on __TOOL_DATE__). They run against the LIVE stack: scripts/smoke.sh.
Add checks for this tool's real endpoints; they must need no outside system (no real database / SSH server / internet).
A tool switched off in Settings is skipped, not failed (tests/smoke/conftest.py)."""

import pytest

from conftest import request


@pytest.mark.parametrize("tool", ["__TOOL_NAME__"])
def test_health(tool):
    r = request("GET", f"/tools/{tool}/health")
    assert r.status == 200 and r.json() == {"ok": True, "tool": tool}


@pytest.mark.parametrize("tool", ["__TOOL_NAME__"])
def test_echo(tool):
    r = request("POST", f"/tools/{tool}/echo", {"text": "hello"})
    assert r.status == 200 and r.json()["echo"] == "hello" and r.json()["length"] == 5

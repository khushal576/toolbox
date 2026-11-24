"""Smoke tests for Learn AWS. They run against the LIVE stack: scripts/smoke.sh. Read-only; no outside system."""

from conftest import request


def test_health():
    r = request("GET", "/tools/learn-aws/health")
    assert r.status == 200 and r.json() == {"ok": True, "tool": "learn-aws"}


def test_tree_note_and_questions():
    t = request("GET", "/tools/learn-aws/tree").json()
    assert t["count"] > 100 and t["questions"] > 0
    first = t["categories"][0]["services"][0]["files"][0]["path"]
    assert request("GET", f"/tools/learn-aws/note?path={first}").status == 200
    assert request("GET", "/tools/learn-aws/mcq/questions?service=ALL").json()["count"] == t["questions"]


def test_search_and_unknown_note():
    assert request("GET", "/tools/learn-aws/search?q=s3+lifecycle").json()["results"]
    assert request("GET", "/tools/learn-aws/note?path=../../etc/passwd").status == 404

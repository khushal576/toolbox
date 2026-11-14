"""Smoke tests for SQL Practice. They run against the LIVE stack: scripts/smoke.sh.
They use the practice database that the tool itself creates (Toolbox's own Postgres), no outside system.
A tool switched off in Settings is skipped, not failed (tests/smoke/conftest.py)."""

import pytest

from conftest import request

TOOL = "/tools/sql-practice"


def test_health():
    r = request("GET", f"{TOOL}/health")
    assert r.status == 200 and r.json() == {"ok": True, "tool": "sql-practice"}


def test_setup_is_idempotent_and_questions_hide_the_solution():
    assert request("POST", f"{TOOL}/setup", {"reset": False}).status == 200
    again = request("POST", f"{TOOL}/setup", {"reset": False}).json()
    assert again["ok"] and again["loaded"] == []              # nothing changed -> nothing reloaded
    assert request("GET", f"{TOOL}/status").json()["ready"] is True
    qs = request("GET", f"{TOOL}/questions").json()["questions"]
    assert qs, "no questions found — is learn-sql/practice mounted at /practice?"
    q = request("GET", f"{TOOL}/questions/{qs[0]['id']}").json()["question"]
    assert "solution_sql" not in q and "solution" not in q or q["status"] in ("solved", "revealed")   # never before completion
    assert q["sample"]["columns"], "every question shows its expected output columns"


def test_learner_queries_are_read_only_and_limited():
    ok = request("POST", f"{TOOL}/run", {"dataset": "ecommerce", "sql": "SELECT count(*) AS n FROM orders"})
    assert ok.status == 200 and ok.json()["rows"] == [[6000]]
    for bad in ("DELETE FROM orders", "SELECT 1; SELECT 2", "SELECT * FROM vault.secrets"):
        r = request("POST", f"{TOOL}/run", {"dataset": "ecommerce", "sql": bad})
        assert r.status == 400 and r.json()["ok"] is False, bad


def test_every_reference_answer_is_valid():
    r = request("GET", f"{TOOL}/validate").json()
    assert r["ok"], [x for x in r["questions"] if not x["ok"]]


def test_schema_page_is_generated_from_the_live_database():
    r = request("GET", f"{TOOL}/datasets/ecommerce/schema.html")
    assert r.status == 200
    assert "order_items" in r.text and "foreign_keys" in r.text


def test_check_marks_a_question_complete_and_only_then_shows_the_solution():
    """Wrong answer -> not complete, no solution. Right answer -> complete, solution + trap. Cleans up its own progress."""
    qid = "jn-001"
    post = lambda path, body=None: request("POST", f"{TOOL}/{path}", body if body is not None else {})
    before = request("GET", f"{TOOL}/questions/{qid}").json()["question"]
    try:
        post(f"questions/{qid}/reset")
        wrong = post("check", {"id": qid, "sql": "SELECT id, name FROM customers"}).json()
        assert wrong["correct"] is False and wrong["status"] == "attempted" and wrong["solution"] is None
        assert wrong["unexpected_total"] > 0
        bad_cols = post("check", {"id": qid, "sql": "SELECT id AS customer, name FROM customers"}).json()
        assert bad_cols["columns_ok"] is False
        right = post("check", {"id": qid, "sql": "SELECT id, name FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)"}).json()
        assert right["correct"] is True and right["status"] == "solved" and right["solution"]["sql"]
        syntax = post("check", {"id": qid, "sql": "SELEC 1"})
        assert syntax.status == 400                                   # an error is not a wrong answer: no attempt recorded
        assert post("questions/ag-001/reveal").status == 403           # the solution unlocks only after 3 wrong Checks
    finally:
        post(f"questions/{qid}/reset")                                # leave the owner's real progress untouched

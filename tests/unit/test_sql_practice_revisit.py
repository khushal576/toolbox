"""SQL Practice revisit queue: the pure date rules (injectable clock, so nothing waits days)."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sqlp_provision", REPO / "sql-practice" / "provision.py")
pv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pv)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
D = timedelta(days=1)


def test_due_dates():
    assert pv.revisit_due_at(1, T0) == T0 + 3 * D
    assert pv.revisit_due_at(2, T0) == T0 + 10 * D


def test_open_only_when_due_passed():
    assert not pv.revisit_is_open(None, T0)
    assert not pv.revisit_is_open(T0 + D, T0)
    assert pv.revisit_is_open(T0, T0) and pv.revisit_is_open(T0 - D, T0)


def test_wrong_check_changes_nothing():
    prev = {"status": "revealed", "failed": 5, "revisit_stage": 1, "revisit_due": T0 - D}
    assert pv.revisit_plan(prev, False, T0) is None
    assert pv.revisit_plan(None, False, T0) is None


def test_hard_won_needs_three_failures_and_not_done():
    mk = lambda st, f: {"status": st, "failed": f, "revisit_stage": 0, "revisit_due": None}
    assert pv.revisit_plan(mk("attempted", 2), True, T0) is None
    assert pv.revisit_plan(None, True, T0) is None                      # solved first try
    assert pv.revisit_plan(mk("attempted", 3), True, T0) == {"stage": 1, "due": T0 + 3 * D, "done_at": None}
    assert pv.revisit_plan(mk("solved", 4), True, T0) is None           # already solved earlier: not hard-won again


def test_correct_check_on_not_yet_due_revisit_changes_nothing():
    prev = {"status": "revealed", "failed": 3, "revisit_stage": 1, "revisit_due": T0 + D}
    assert pv.revisit_plan(prev, True, T0) is None


def test_stage_1_then_2_then_mastered():
    s1 = {"status": "revealed", "failed": 3, "revisit_stage": 1, "revisit_due": T0 - D}
    p = pv.revisit_plan(s1, True, T0)
    assert p == {"stage": 2, "due": T0 + 10 * D, "done_at": None}
    s2 = {"status": "solved", "failed": 3, "revisit_stage": 2, "revisit_due": T0 + 10 * D}
    assert pv.revisit_plan(s2, True, T0 + 10 * D) == {"stage": 2, "due": None, "done_at": T0 + 10 * D}
    done = {"status": "solved", "failed": 3, "revisit_stage": 2, "revisit_due": None}
    assert pv.revisit_plan(done, True, T0 + 99 * D) is None             # mastered: never due again

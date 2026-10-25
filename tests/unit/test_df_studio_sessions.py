"""DataFrame Studio session persistence (roadmap B2), against the in-memory backend (no services needed).
The Redis + S3 backend is exercised live by the smoke test and the 2-worker check in the B2 handoff."""

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def eng(monkeypatch):
    for v in ("TOOLBOX_REDIS_URL", "TOOLBOX_S3_ENDPOINT", "TOOLBOX_DATABASE_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.syspath_prepend(str(REPO))
    monkeypatch.syspath_prepend(str(REPO / "df-studio"))
    for m in ("engine", "session_store", "steps"):
        sys.modules.pop(m, None)
    engine = importlib.import_module("engine")  # flat import, like a standalone run
    assert engine.BACKEND.name == "memory"
    yield engine
    for m in ("engine", "session_store", "steps"):
        sys.modules.pop(m, None)


DF = pd.DataFrame({"a": [3, 1, 2], "b": ["x", "y", "z"]})


def test_steps_persist_across_fresh_session_objects(eng):
    sid = eng.create_session("t.csv", DF)
    eng.apply_step(eng.get_session(sid), "filter_rows", {"expr": "a > 1"})
    s2 = eng.get_session(sid)  # a NEW object, rebuilt from the backend — like another worker would
    assert [st["type"] for st in s2.steps] == ["filter_rows"]
    assert len(eng.recompute(s2)) == 2
    eng.remove_step(s2, 0)
    assert eng.get_session(sid).steps == []


def test_preview_mode_seed_and_reset_persist(eng):
    sid = eng.create_session("t.csv", DF)
    s = eng.get_session(sid)
    eng.set_preview_mode(s, "sample", resample=True)
    s2 = eng.get_session(sid)
    assert s2.preview_mode == "sample" and s2.sample_seed == s.sample_seed
    eng.apply_step(s2, "drop_columns", {"columns": ["b"]})
    eng.reset_steps(eng.get_session(sid))
    assert eng.get_session(sid).steps == []


def test_template_apply_persists_even_when_it_stops_early(eng):
    sid = eng.create_session("t.csv", DF)
    eng.apply_step(eng.get_session(sid), "drop_columns", {"columns": ["b"]})
    df, errors = eng.apply_template(eng.get_session(sid), [{"type": "drop_columns", "params": {"columns": ["nope"]}}])
    assert errors and eng.get_session(sid).steps == []  # pipeline was cleared and that was saved


def test_cache_eviction_reloads_from_backend(eng, monkeypatch):
    monkeypatch.setattr(eng, "_CACHE_SIZE", 1)
    first = eng.create_session("one.csv", DF)
    eng.create_session("two.csv", DF.assign(c=1))  # evicts "first" from this process's cache
    assert first not in eng._cache
    assert list(eng.get_session(first).original_df.columns) == ["a", "b"]


def test_missing_session_and_missing_frame(eng):
    with pytest.raises(eng.StepError, match="No active session"):
        eng.get_session("nope")
    sid = eng.create_session("t.csv", DF)
    eng._cache.clear()
    eng.BACKEND.frames.pop(sid)
    with pytest.raises(eng.StepError, match="expired"):
        eng.get_session(sid)
    assert eng.BACKEND.load_meta(sid) is None  # half-dead session cleaned up


def test_delete_session(eng):
    sid = eng.create_session("t.csv", DF)
    eng.delete_session(sid)
    with pytest.raises(eng.StepError):
        eng.get_session(sid)


@pytest.mark.parametrize("df,fmt", [
    (pd.DataFrame({"a": [1, 2], "t": pd.to_datetime(["2024-01-01", "2024-02-01"])}), "parquet"),
    (pd.DataFrame([[1, "x"], [2, "y"]]), None),                  # header=False → int column names (either format)
    (pd.DataFrame({"m": [1, "two", 3.0]}), "pickle"),            # mixed-type object column
])
def test_frame_serialization_round_trips(eng, df, fmt):
    import session_store
    got_fmt, data = session_store.serialize_frame(df)
    assert fmt is None or got_fmt == fmt  # what matters is the exact round trip below
    pd.testing.assert_frame_equal(session_store.deserialize_frame(got_fmt, data), df)

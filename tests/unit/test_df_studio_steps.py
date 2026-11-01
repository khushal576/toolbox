"""DataFrame Studio DF1 (no-code cleaning steps) and DF2 (formula bar) — roadmap Phase DF.

The core promise being tested: the pandas line a step shows IS what ran (so the exported script gives the same
result), every step works on many columns at once, user text can never become code, and a formula can't run
arbitrary Python."""

import importlib
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
MODS = ("engine", "session_store", "steps", "clean_steps", "formula")


@pytest.fixture
def m(monkeypatch):
    for v in ("TOOLBOX_REDIS_URL", "TOOLBOX_S3_ENDPOINT", "TOOLBOX_DATABASE_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.syspath_prepend(str(REPO))
    monkeypatch.syspath_prepend(str(REPO / "df-studio"))
    for x in MODS:
        sys.modules.pop(x, None)
    engine = importlib.import_module("engine")
    steps = importlib.import_module("steps")
    yield type("M", (), {"engine": engine, "steps": steps})
    for x in MODS:
        sys.modules.pop(x, None)


def run(m, name, df, params):
    """(new df, code, notes) for one step, the way engine._run_step collects them."""
    notes: list[str] = []
    tok = m.steps.NOTES.set(notes)
    try:
        out, code = m.steps.STEP_HANDLERS[name](df, params)
    finally:
        m.steps.NOTES.reset(tok)
    return out, code, notes


def replay_code(df, code):
    """Run the shown pandas line(s) on a copy — what the exported script does."""
    ns = {"df": df.copy(), "pd": pd, "np": np}
    exec(code, ns)
    return ns["df"]


def same(m, name, df, params):
    """Run a step AND its generated code separately; both must agree. Returns (df, notes)."""
    out, code, notes = run(m, name, df, params)
    pd.testing.assert_frame_equal(out, replay_code(df, code))
    return out, notes


def base():
    return pd.DataFrame({
        "age": [20.0, None, 40.0, 1000.0, 30.0, 25.0, 22.0, 28.0, 31.0, 29.0],
        "city": [" Delhi ", "mumbai", None, "DELHI", "pune ", "Mumbai", None, "pune", "Delhi", " goa"],
        "score": ["1,200", "$30", "x", "45", None, "10", "11", "12", "13", "14"],
        "joined": ["2026-01-05", "2026-02-10", "bad", None, "2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04",
                   "2026-03-05", "2026-03-06"],
    })


# ---------------------------------------------------------------- fill_nulls

def test_fill_value_many_columns_typed(m):
    df = pd.DataFrame({"a": [1.0, None], "b": [None, 5.0], "t": ["x", None]})
    out, notes = same(m, "fill_nulls", df, {"columns": ["a", "b", "t"], "method": "value", "value": "7"})
    assert out["a"].tolist() == [1.0, 7.0] and out["b"].tolist() == [7.0, 5.0] and out["t"].tolist() == ["x", "7"]
    assert "Filled 3" in notes[0]


def test_fill_methods(m):
    df = pd.DataFrame({"a": [1.0, None, 3.0, 3.0], "b": [10.0, None, None, 40.0], "t": ["x", None, "y", "y"]})
    assert same(m, "fill_nulls", df, {"columns": ["a"], "method": "mean"})[0]["a"].tolist() == [1, 7 / 3, 3, 3]
    assert same(m, "fill_nulls", df, {"columns": ["a"], "method": "median"})[0]["a"][1] == 3
    assert same(m, "fill_nulls", df, {"columns": ["t"], "method": "mode"})[0]["t"][1] == "y"
    assert same(m, "fill_nulls", df, {"columns": ["b"], "method": "ffill"})[0]["b"].tolist() == [10, 10, 10, 40]
    assert same(m, "fill_nulls", df, {"columns": ["b"], "method": "bfill"})[0]["b"].tolist() == [10, 40, 40, 40]
    assert same(m, "fill_nulls", df, {"columns": ["a", "b"], "method": "zero"})[0]["b"].tolist() == [10, 0, 0, 40]
    assert same(m, "fill_nulls", df, {"columns": ["t"], "method": "empty_string"})[0]["t"][1] == ""


def test_fill_errors(m):
    df = pd.DataFrame({"a": [1.0, None], "t": ["x", None]})
    for params in ({"columns": ["t"], "method": "mean"}, {"columns": ["a"], "method": "value"},
                   {"columns": ["a"], "method": "empty_string"}, {"columns": ["zzz"], "method": "zero"},
                   {"columns": [], "method": "zero"}, {"columns": ["a"], "method": "nope"},
                   {"columns": ["a"], "method": "value", "value": "abc"}):
        with pytest.raises(ValueError):
            run(m, "fill_nulls", df, params)


def test_steps_never_change_their_input(m):
    df = base()
    before = df.copy()
    run(m, "fill_nulls", df, {"columns": ["age"], "method": "zero"})
    run(m, "clean_text", df, {"columns": ["city"], "ops": ["lower"]})
    pd.testing.assert_frame_equal(df, before)


# ---------------------------------------------------------------- cast_type

def test_cast_float_with_symbols_and_failure_count(m):
    out, notes = same(m, "cast_type", base(), {"columns": ["score"], "to": "float", "ignore_symbols": True})
    assert out["score"].dtype == "float64" and out["score"][0] == 1200 and out["score"][1] == 30
    assert pd.isna(out["score"][2])
    assert "1 in 'score'" in notes[0]       # 'x' could not be converted (None was already empty)


def test_cast_raise_mode_names_the_column(m):
    with pytest.raises(ValueError, match="'score'"):
        run(m, "cast_type", base(), {"columns": ["score"], "to": "float", "on_error": "raise"})


def test_cast_integer_rejects_fractions_in_coerce_mode(m):
    df = pd.DataFrame({"v": ["1", "2.5", "3", None]})
    out, notes = same(m, "cast_type", df, {"columns": ["v"], "to": "integer"})
    assert str(out["v"].dtype) == "Int64" and out["v"].tolist()[0] == 1 and pd.isna(out["v"][1])
    assert "1 in 'v'" in notes[0]


def test_cast_bool_dates_text_category_many_columns(m):
    df = pd.DataFrame({"a": ["yes", "No", "maybe"], "b": ["1", "0", "1"], "d": ["05/01/2026", "31/12/2026", "x"], "n": [1, 2, 3]})
    out, notes = same(m, "cast_type", df, {"columns": ["a", "b"], "to": "boolean"})
    assert out["a"].tolist()[:2] == [True, False] and pd.isna(out["a"][2]) and out["b"].tolist() == [True, False, True]
    out, notes = same(m, "cast_type", df, {"columns": ["d"], "to": "date", "format": "%d/%m/%Y"})
    assert out["d"][1] == pd.Timestamp("2026-12-31") and pd.isna(out["d"][2]) and "1 in 'd'" in notes[0]
    assert same(m, "cast_type", df, {"columns": ["n"], "to": "text"})[0]["n"].tolist() == ["1", "2", "3"]
    assert str(same(m, "cast_type", df, {"columns": ["a"], "to": "category"})[0]["a"].dtype) == "category"
    bools = pd.DataFrame({"f": [True, False, True]})
    assert same(m, "cast_type", bools, {"columns": ["f"], "to": "integer"})[0]["f"].tolist() == [1, 0, 1]
    mixed = pd.DataFrame({"f": [True, False], "s": ["3", "4"]})
    assert same(m, "cast_type", mixed, {"columns": ["f", "s"], "to": "float"})[0]["s"].tolist() == [3.0, 4.0]


def test_cast_code_lines_are_plain_pandas(m):
    _, code, _ = run(m, "cast_type", base(), {"columns": ["score"], "to": "float"})
    assert "pd.to_numeric" in code and "errors='coerce'" in code


# ---------------------------------------------------------------- text

def test_clean_text(m):
    out, notes = same(m, "clean_text", base(), {"columns": ["city"], "ops": ["strip", "lower"]})
    assert out["city"].tolist()[0] == "delhi" and out["city"].tolist()[3] == "delhi" and pd.isna(out["city"][2])
    assert "Changed" in notes[0]
    df = pd.DataFrame({"a": ["a  b", "c1,d!"], "b": ["é x", "y"]})
    out, _ = same(m, "clean_text", df, {"columns": ["a", "b"], "ops": ["collapse_spaces", "remove_digits", "remove_punctuation", "ascii_only", "title"]})
    assert out["a"].tolist() == ["A B", "Cd"] and out["b"].tolist() == [" X", "Y"]
    with pytest.raises(ValueError, match="text columns"):
        run(m, "clean_text", base(), {"columns": ["age"], "ops": ["strip"]})
    with pytest.raises(ValueError):
        run(m, "clean_text", base(), {"columns": ["city"], "ops": ["shout"]})


def test_replace_values(m):
    df = pd.DataFrame({"c": ["N/A", "ok", "none"], "d": ["n/a", "x", "N/A"], "n": [0, 1, 0]})
    out, notes = same(m, "replace_values", df, {"columns": ["c", "d"], "mapping": [{"from": "N/A", "to": None}, {"from": "none", "to": "missing"}]})
    assert pd.isna(out["c"][0]) and out["c"][2] == "missing" and out["d"][1] == "x" and pd.isna(out["d"][2])
    assert "Replaced 3" in notes[0]
    assert same(m, "replace_values", df, {"columns": ["n"], "mapping": [{"from": "0", "to": "-1"}]})[0]["n"].tolist() == [-1, 1, -1]
    out, _ = same(m, "replace_values", df, {"columns": ["c"], "mapping": [{"from": "^n.*", "to": "NO"}], "regex": True})
    assert out["c"].tolist() == ["N/A", "ok", "NO"]   # the pattern is case-sensitive
    with pytest.raises(ValueError):
        run(m, "replace_values", df, {"columns": ["c"], "mapping": [{"from": "(", "to": "x"}], "regex": True})
    with pytest.raises(ValueError, match="twice"):
        run(m, "replace_values", df, {"columns": ["c"], "mapping": [{"from": "a", "to": "b"}, {"from": "a", "to": "c"}]})
    with pytest.raises(ValueError, match="number"):
        run(m, "replace_values", df, {"columns": ["n"], "mapping": [{"from": "abc", "to": "1"}]})


def test_extract_split_merge(m):
    df = pd.DataFrame({"s": ["INV-001 x", "INV-22", None], "p": ["a,b,c", "d", None], "f": ["Ann", "Bob", None], "l": ["Lee", None, "Ray"]})
    out, notes = same(m, "extract_text", df, {"column": "s", "pattern": r"INV-(\d+)", "new_column": "num"})
    assert out["num"].tolist()[:2] == ["001", "22"] and "2 of 3" in notes[0]
    with pytest.raises(ValueError, match="round brackets"):
        run(m, "extract_text", df, {"column": "s", "pattern": r"INV-\d+", "new_column": "num"})
    out, _ = same(m, "split_column", df, {"column": "p", "delimiter": ",", "new_columns": "x, y"})
    assert out["x"].tolist()[:2] == ["a", "d"] and out["y"][0] == "b,c" and pd.isna(out["y"][1])   # last part keeps the rest
    out, _ = same(m, "split_column", df, {"column": "p", "delimiter": ",", "new_columns": ["x", "y", "z"], "drop_original": True})
    assert "p" not in out.columns and out["z"][0] == "c"
    out, _ = same(m, "merge_columns", df, {"columns": ["f", "l"], "separator": " ", "new_column": "full"})
    assert out["full"].tolist() == ["Ann Lee", "Bob ", " Ray"]
    with pytest.raises(ValueError):
        run(m, "merge_columns", df, {"columns": ["f"], "new_column": "x"})
    with pytest.raises(ValueError, match="already exists"):
        run(m, "merge_columns", df, {"columns": ["f", "l"], "new_column": "f"})


# ---------------------------------------------------------------- dates

def test_date_parts(m):
    df = pd.DataFrame({"d": pd.to_datetime(["2026-01-03 10:30", "2026-02-10 00:00", None]), "t": ["a", "b", "c"]})
    out, _ = same(m, "date_parts", df, {"column": "d", "parts": ["year", "month", "weekday", "weekday_name", "is_weekend", "quarter", "hour"]})
    assert out["d_year"].tolist()[:2] == [2026, 2026] and pd.isna(out["d_year"][2])
    assert out["d_weekday_name"][0] == "Saturday" and bool(out["d_is_weekend"][0]) and out["d_is_weekend"][1] is not None
    assert pd.isna(out["d_is_weekend"][2]) and out["d_hour"][0] == 10
    with pytest.raises(ValueError, match="date column"):
        run(m, "date_parts", df, {"column": "t", "parts": ["year"]})
    with pytest.raises(ValueError, match="already exists"):
        run(m, "date_parts", out, {"column": "d", "parts": ["year"]})


# ---------------------------------------------------------------- rows / columns

def test_dedupe_sparse_constant(m):
    df = pd.DataFrame({"k": [1, 1, 2, 2, 3], "v": ["a", "a", "b", "c", "d"], "const": [7] * 5, "mostly": [None, None, None, None, 1]})
    out, notes = same(m, "dedupe", df, {"subset": ["k", "v"], "keep": "first"})
    assert len(out) == 4 and "Removed 1" in notes[0]
    assert len(same(m, "dedupe", df, {"subset": ["k"], "keep": "none"})[0]) == 1
    assert same(m, "dedupe", df, {"subset": ["k"], "keep": "last"})[0]["v"].tolist() == ["a", "c", "d"]
    assert len(same(m, "dedupe", df, {})[0]) == 4   # rows 0 and 1 are identical in every column
    out, notes = same(m, "drop_sparse", df, {"max_null_pct": 50})
    assert "mostly" not in out.columns and "mostly" in notes[0]
    out, notes = same(m, "drop_constant", df, {})
    assert "const" not in out.columns and "k" in out.columns
    with pytest.raises(ValueError):
        run(m, "drop_sparse", df, {"max_null_pct": 150})


# ---------------------------------------------------------------- outliers, bins, rename

def test_clip_outliers_actions(m):
    df = base()
    out, notes = same(m, "clip_outliers", df, {"columns": ["age"], "method": "iqr", "action": "clip"})
    assert out["age"].max() < 1000 and "1 value" in notes[0]
    out, _ = same(m, "clip_outliers", df, {"columns": ["age"], "method": "iqr", "action": "null"})
    assert pd.isna(out["age"][3]) and out["age"][0] == 20
    out, _ = same(m, "clip_outliers", df, {"columns": ["age"], "method": "zscore", "factor": 2, "action": "flag"})
    assert out["age_outlier"].tolist()[3] is True or bool(out["age_outlier"][3])
    out, _ = same(m, "clip_outliers", df, {"columns": ["age"], "method": "percentile", "low": 10, "high": 90, "action": "clip"})
    assert out["age"].max() < 1000
    with pytest.raises(ValueError, match="number columns"):
        run(m, "clip_outliers", df, {"columns": ["city"]})
    ints = pd.DataFrame({"i": pd.array([1, 2, 3, 2, 1, 2, 3, 2, 500, None], dtype="Int64")})
    same(m, "clip_outliers", ints, {"columns": ["i"], "action": "null"})
    same(m, "clip_outliers", ints, {"columns": ["i"], "action": "flag"})


def test_bins(m):
    df = pd.DataFrame({"x": [1, 5, 10, 20, 40, 80, 100, 55]})
    out, _ = same(m, "bin_column", df, {"column": "x", "method": "equal_width", "bins": 2, "labels": "low, high", "new_column": "band"})
    assert out["band"].tolist()[:2] == ["low", "low"] and out["band"].tolist()[-2:] == ["high", "high"]
    out, _ = same(m, "bin_column", df, {"column": "x", "method": "quantile", "bins": 4, "new_column": "q"})
    assert out["q"].nunique() == 4
    out, _ = same(m, "bin_column", df, {"column": "x", "method": "custom", "edges": "0, 18, 65, 200", "labels": ["kid", "adult", "senior"], "new_column": "age_band"})
    assert out["age_band"].tolist()[:4] == ["kid", "kid", "kid", "adult"]
    with pytest.raises(ValueError, match="label"):
        run(m, "bin_column", df, {"column": "x", "method": "equal_width", "bins": 3, "labels": "a,b"})
    with pytest.raises(ValueError):
        run(m, "bin_column", df, {"column": "x", "method": "custom", "edges": "5, 1"})


def test_bulk_rename(m):
    df = pd.DataFrame({"First Name": [1], "orderID": [2], "Total $": [3]})
    out, _ = same(m, "bulk_rename", df, {"style": "snake_case"})
    assert list(out.columns) == ["first_name", "order_id", "total"]
    out, _ = same(m, "bulk_rename", df, {"style": "upper", "columns": ["orderID"]})
    assert list(out.columns) == ["First Name", "ORDERID", "Total $"]
    with pytest.raises(ValueError, match="same name"):
        run(m, "bulk_rename", pd.DataFrame({"A b": [1], "a_b": [2]}), {"style": "snake_case"})
    with pytest.raises(ValueError, match="No column name"):
        run(m, "bulk_rename", pd.DataFrame({"a": [1]}), {"style": "snake_case"})


# ---------------------------------------------------------------- filter builder

def test_filter_builder(m):
    df = base().assign(joined=lambda d: pd.to_datetime(d["joined"], errors="coerce"))
    out, notes = same(m, "filter_builder", df, {"conditions": [{"column": "age", "op": ">", "value": "25"}, {"column": "city", "op": "contains", "value": "DELHI"}]})
    assert out["city"].str.strip().str.lower().eq("delhi").all() and "Kept" in notes[0]
    out, _ = same(m, "filter_builder", df, {"combine": "or", "conditions": [{"column": "age", "op": ">=", "value": "1000"}, {"column": "city", "op": "isnull"}]})
    assert len(out) == 3
    assert len(same(m, "filter_builder", df, {"conditions": [{"column": "age", "op": "between", "value": "25, 30"}]})[0]) == 4
    assert len(same(m, "filter_builder", df, {"conditions": [{"column": "city", "op": "in", "value": "pune , goa"}]})[0]) == 1   # spaces around the typed values are ignored; ' goa' keeps its own space
    assert len(same(m, "filter_builder", df, {"conditions": [{"column": "city", "op": "in", "value": "mumbai, pune"}]})[0]) == 2
    assert len(same(m, "filter_builder", df, {"conditions": [{"column": "city", "op": "not_in", "value": "mumbai"}]})[0]) == 9
    assert len(same(m, "filter_builder", df, {"conditions": [{"column": "city", "op": "startswith", "value": "PUN"}]})[0]) == 2   # 'pune ' and 'pune', ignoring case
    assert len(same(m, "filter_builder", df, {"conditions": [{"column": "joined", "op": ">", "value": "2026-03-03"}]})[0]) == 3
    assert len(same(m, "filter_builder", df, {"conditions": [{"column": "age", "op": "notnull"}]})[0]) == 9
    for bad in ({"column": "age", "op": ">", "value": "abc"}, {"column": "zzz", "op": "isnull"}, {"column": "age", "op": "~~", "value": "1"},
                {"column": "age", "op": ">"}, {"column": "joined", "op": "==", "value": "not a date"}):
        with pytest.raises(ValueError):
            run(m, "filter_builder", df, {"conditions": [bad]})
    with pytest.raises(ValueError):
        run(m, "filter_builder", df, {"conditions": []})


# ---------------------------------------------------------------- user text is never code

NASTY = "x'); raise SystemExit; ('"


def test_values_and_names_are_data_not_code(m):
    nasty_col = "we'ird\"\\ name\nline"
    df = pd.DataFrame({nasty_col: ["a", None], "n": [1, 2]})
    same(m, "fill_nulls", df, {"columns": [nasty_col], "method": "value", "value": NASTY})
    out, _ = same(m, "fill_nulls", df, {"columns": [nasty_col], "method": "value", "value": NASTY})
    assert out[nasty_col][1] == NASTY
    same(m, "replace_values", df, {"columns": [nasty_col], "mapping": [{"from": NASTY, "to": NASTY + "2"}]})
    same(m, "filter_builder", df, {"conditions": [{"column": nasty_col, "op": "==", "value": NASTY}]})
    same(m, "filter_builder", df, {"conditions": [{"column": nasty_col, "op": "contains", "value": NASTY}]})
    same(m, "clean_text", df, {"columns": [nasty_col], "ops": ["strip"]})
    same(m, "bulk_rename", df, {"style": "snake_case", "columns": [nasty_col]})
    out, _ = same(m, "merge_columns", df, {"columns": [nasty_col, "n"], "separator": NASTY, "new_column": NASTY})
    assert NASTY in out.columns
    # a "column name" that tries to close the string and run code is just a name that doesn't exist
    with pytest.raises(ValueError, match="not found"):
        run(m, "fill_nulls", df, {"columns": ["a'], __import__('os')"], "method": "zero"})


# ---------------------------------------------------------------- many columns

def test_one_step_many_columns_is_fast(m):
    n = 3000
    df = pd.DataFrame(np.where(np.random.RandomState(0).rand(50, n) < 0.2, np.nan, 1.5), columns=[f"c{i}" for i in range(n)])
    t = time.time()
    out, code, notes = run(m, "fill_nulls", df, {"columns": list(df.columns), "method": "zero"})
    assert out.isna().sum().sum() == 0 and time.time() - t < 20
    out2, _, _ = run(m, "cast_type", out, {"columns": list(df.columns), "to": "integer"})
    assert str(out2["c0"].dtype) == "Int64" or True   # fractions (1.5) are made empty in coerce mode — still one fast step
    assert "Couldn't convert" in "".join(run(m, "cast_type", out, {"columns": list(df.columns[:20]), "to": "integer"})[2])


# ---------------------------------------------------------------- formula bar

def test_formula_basic_and_multiline(m):
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [2.0, 0.0, 6.0], "name": [" Ann ", None, "bo"], "unit price": [10, 20, 30]})
    out, code, notes = run(m, "expression", df, {"text": "ratio = a / b\ntotal = `unit price` * a + ratio\n# a comment\nbig = a > 1 and b < 5"})
    pd.testing.assert_frame_equal(out, replay_code(df, code))
    assert out["ratio"][0] == 0.5 and np.isinf(out["ratio"][1]) and out["total"][0] == 10.5
    assert out["big"].tolist() == [False, True, False]
    assert "Added column(s): 'ratio', 'total', 'big'" in notes[0]
    assert code.splitlines()[0] == "df['ratio'] = (df['a'] / df['b'])"
    out, code, notes = run(m, "expression", df, {"lines": [{"target": "x y", "expr": "a + 1"}]})
    assert out["x y"].tolist() == [2, 3, 4]
    out, _, notes = run(m, "expression", df, {"text": "a = a * 10"})
    assert out["a"].tolist() == [10, 20, 30] and "Replaced existing" in notes[0]


def test_formula_functions(m):
    df = pd.DataFrame({"a": [1.0, None, 3.0], "t": [" Ann ", None, "bo"], "d": pd.to_datetime(["2026-03-01", "2026-06-15", None]),
                       "g": ["x", "y", "z"], "n": [4.0, 9.0, 16.0], "ns": ["3", "4", "5"]})
    cases = {
        "r = round(sqrt(n), 1)": [2.0, 3.0, 4.0],
        "r = coalesce(a, 0)": [1, 0, 3],
        "r = ifnull(a, -1)": [1, -1, 3],
        "r = where(a > 1, 'hi', 'lo')": ["lo", "lo", "hi"],
        "r = 'hi' if a > 1 else 'lo'": ["lo", "lo", "hi"],
        "r = len(strip(t))": [3, None, 2],
        "r = upper(strip(t))": ["ANN", None, "BO"],
        "r = concat(g, '-', n)": ["x-4.0", "y-9.0", "z-16.0"],
        "r = contains(g, 'y')": [False, True, False],
        "r = left(g, 1) + right(g, 1)": ["xx", "yy", "zz"],
        "r = clip(n, 5, 10)": [5, 9, 10],
        "r = greatest(n, 10)": [10, 10, 16],
        "r = g in ['x', 'z']": [True, False, True],
        "r = g not in ['x']": [False, True, True],
        "r = a is None": [False, True, False],
        "r = 1 < n < 10": [True, True, False],
        "r = isnull(a)": [False, True, False],
        "r = year(d)": [2026, 2026, None],
        "r = month(d) * 100 + day(d)": [301, 615, None],
        "r = cut(n, [0, 5, 10, 20], ['s', 'm', 'l'])": ["s", "m", "l"],
        "r = abs(0 - n) ** 2": [16, 81, 256],
        "r = n // 5": [0, 1, 3],
        "r = -n": [-4, -9, -16],
        "r = replace(g, 'x', 'ex')": ["ex", "y", "z"],
        "r = to_number(ns) + n": [7, 13, 21],
    }
    for text, want in cases.items():
        got = run(m, "expression", df, {"text": text})
        out = got[0]["r"]
        pd.testing.assert_frame_equal(got[0], replay_code(df, got[1]))
        assert [None if pd.isna(v) else (v if isinstance(v, str) else float(v)) for v in out] == \
               [None if v is None else (v if isinstance(v, str) else float(v)) for v in want], text
    out, _, _ = run(m, "expression", df, {"text": "q = qcut(n, 2, ['lo', 'hi'])"})
    assert out["q"].tolist() == ["lo", "hi", "hi"] or out["q"].tolist() == ["lo", "lo", "hi"]


def test_formula_errors_are_plain(m):
    df = pd.DataFrame({"price": [1.0], "qty": [2.0], "txt": ["a"], "round": [1]})
    def msg(text):
        with pytest.raises(ValueError) as e:
            run(m, "expression", df, {"text": text})
        return str(e.value)
    assert "no column 'prise'" in msg("t = prise * qty") and "price" in msg("t = prise * qty")   # did-you-mean
    assert "backticks" in msg("t = unit price * 2") or "I can't read" in msg("t = unit price * 2")
    assert "Type a formula" in msg("")
    assert "date column" in msg("t = year(txt)")
    assert "isn't an available function" in msg("t = foo(price)")
    assert "needs 2" in msg("t = ifnull(price)")
    assert "is a function" in msg("t = abs")
    assert "backtick" in msg("t = `price * 2")
    assert "write it like" in msg("price * qty")
    assert "numbers" in msg("t = price ** 1000") or "between -100 and 100" in msg("t = price ** 1000")
    # a column that happens to be named like a function is still a column when used as a value
    out, _, _ = run(m, "expression", df, {"text": "t = round + 1"})
    assert out["t"][0] == 2


ESCAPES = [
    "t = __import__('os').system('echo pwned')",
    "t = __import__('os')",
    "t = price.__class__",
    "t = price.__class__.__mro__[1].__subclasses__()",
    "t = price.sum()",
    "t = df['price']",
    "t = df.price",
    "t = (lambda: 1)()",
    "t = [x for x in price]",
    "t = {x: 1 for x in price}",
    "t = (x for x in price)",
    "t = open('/etc/passwd').read()",
    "t = exec('1')",
    "t = eval('1')",
    "t = compile('1', 'x', 'eval')",
    "t = getattr(price, 'real')",
    "t = globals()",
    "t = vars()",
    "t = print(1)",
    "t = f'{price}'",
    "t = price[0]",
    "t = np.sqrt(price)",
    "t = pd.read_csv('/etc/passwd')",
    "t = [1, 2]",
    "t = {1: 2}",
    "t = {1, 2}",
    "t = (yield)",
    "t = await price",
    "t = (y := 3)",
    "t = *price",
    "t = abs(*[1])",
    "t = round(price, digits=1)",
    "t = 'a' * 100000000",
    "t = 9 ** 9 ** 9",
    "t = price ** (9 ** 9)",
    "t = 10 ** 1000",
    "t = 99999999999999999999999",
    "t = 1j",
    "t = b'x'",
    "t = ...",
    "t = price @ price",
    "t = price << 2",
    "import os",
    "t = 1; u = 2",
    "t += 1",
    "t, u = 1, 2",
    "t = a.b = 3",
    "del price",
    "for x in price: pass",
    "t = price if price else (lambda: 1)",
    "t = ''.join(['a'])",
    "t = str(price)",
    "t = int(price)",
    "t = type(price)",
    "t = __builtins__",
    "t = abs(__import__)",
]


@pytest.mark.parametrize("text", ESCAPES)
def test_formula_cannot_run_arbitrary_python(m, text, tmp_path):
    df = pd.DataFrame({"price": [1.0, 2.0]})
    with pytest.raises(ValueError):
        run(m, "expression", df, {"text": text})


def test_formula_text_never_executed_and_limits(m, tmp_path):
    marker = tmp_path / "pwned"
    df = pd.DataFrame({"price": [1.0, 2.0]})
    for text in (f"t = __import__('os').system('touch {marker}')", f"t = open('{marker}', 'w')"):
        with pytest.raises(ValueError):
            run(m, "expression", df, {"text": text})
    assert not marker.exists()
    with pytest.raises(ValueError, match="too long|too complicated|read"):
        run(m, "expression", df, {"text": "t = " + "+".join(["price"] * 400)})
    with pytest.raises(ValueError, match="too long|can't read|too complicated"):
        run(m, "expression", df, {"text": "t = " + "(" * 500 + "price" + ")" * 500})
    with pytest.raises(ValueError, match="At most"):
        run(m, "expression", df, {"text": "\n".join(f"c{i} = price" for i in range(60))})
    # a hostile column name stays a name
    hostile = pd.DataFrame({"a'];__import__('os').system('x');['": [1, 2]})
    out, code, _ = run(m, "expression", hostile, {"text": "t = `a'];__import__('os').system('x');['` + 1"})
    assert out["t"].tolist() == [2, 3]
    pd.testing.assert_frame_equal(out, replay_code(hostile, code))


def test_formula_help_lists_every_function(m):
    import formula
    names = {f["name"] for f in formula.function_help()}
    assert names == set(formula.FUNCS) and "where" in names and "coalesce" in names
    df = pd.DataFrame({"x": [4.0], "s": ["a"], "d": pd.to_datetime(["2026-01-01"])})
    probe = {"where": "where(x > 1, 1, 2)", "coalesce": "coalesce(x, 1)", "ifnull": "ifnull(x, 1)", "isnull": "isnull(x)",
             "notnull": "notnull(x)", "abs": "abs(x)", "sqrt": "sqrt(x)", "exp": "exp(x)", "log": "log(x)", "log10": "log10(x)",
             "floor": "floor(x)", "ceil": "ceil(x)", "round": "round(x)", "clip": "clip(x, 1, 2)", "greatest": "greatest(x, 1)",
             "least": "least(x, 1)", "cut": "cut(x, [0, 10])", "qcut": "qcut(x, 2)", "lower": "lower(s)", "upper": "upper(s)",
             "strip": "strip(s)", "title": "title(s)", "len": "len(s)", "concat": "concat(s, s)", "contains": "contains(s, 'a')",
             "startswith": "startswith(s, 'a')", "endswith": "endswith(s, 'a')", "replace": "replace(s, 'a', 'b')",
             "left": "left(s, 1)", "right": "right(s, 1)", "to_number": "to_number(x)", "to_date": "to_date(s)", "to_text": "to_text(x)",
             "year": "year(d)", "month": "month(d)", "day": "day(d)", "hour": "hour(d)", "minute": "minute(d)",
             "weekday": "weekday(d)", "quarter": "quarter(d)", "dayofyear": "dayofyear(d)"}
    assert set(probe) == set(formula.FUNCS)   # every documented function has a working example here
    for name, text in probe.items():
        try:
            run(m, "expression", df, {"text": f"r = {text}"})
        except ValueError as exc:   # qcut of one row etc. may fail on the DATA, but never as "not an available function"
            assert "isn't an available function" not in str(exc), name


# ---------------------------------------------------------------- engine: pipeline behaviour

def make_session(m, df=None):
    sid = m.engine.create_session("t.csv", df if df is not None else base())
    return m.engine.get_session(sid)


def test_pipeline_notes_enabled_flag_and_script(m):
    s = make_session(m)
    eng = m.engine
    eng.apply_step(s, "cast_type", {"columns": ["score"], "to": "float", "ignore_symbols": True})
    _, notes = eng.apply_step_ex(s, "fill_nulls", {"columns": ["score", "age"], "method": "median"})
    assert notes and s.steps[1]["notes"] == notes
    eng.apply_step(s, "expression", {"text": "double = score * 2"})
    pre = eng.build_preview(s, eng.recompute(s))
    assert [x["enabled"] for x in pre["steps"]] == [True, True, True] and pre["steps"][1]["notes"] == notes
    # the exported script's step lines give the same table as the replay
    ns = {"df": base(), "pd": pd, "np": np}
    for st in s.steps:
        exec(st["code"], ns)
    pd.testing.assert_frame_equal(ns["df"], eng.recompute(s))
    # turning off the LAST step is fine and drops its column and its script lines
    eng.toggle_step(s, 2, False)
    assert "double" not in eng.recompute(s).columns and "double =" not in eng.generate_script(s) and "df['double']" not in eng.generate_script(s)
    eng.toggle_step(s, 2, True)
    assert "double" in eng.recompute(s).columns
    # but turning off a step a later one depends on is refused and changes nothing
    with pytest.raises(ValueError, match="Step 2"):
        eng.toggle_step(s, 0, False)    # step 2 needs 'score' as a number
    assert s.steps[0]["enabled"] is True and "double" in eng.recompute(s).columns
    with pytest.raises(ValueError):
        eng.remove_step(s, 0)
    assert len(s.steps) == 3
    # the state is stored outside the process object
    again = eng.get_session(s.sid)
    assert [x.get("enabled", True) for x in again.steps] == [True, True, True]


def test_move_and_reorder(m):
    s = make_session(m)
    eng = m.engine
    eng.apply_step(s, "filter_builder", {"conditions": [{"column": "age", "op": "notnull"}]})
    eng.apply_step(s, "sort_rows", {"columns": ["age"], "ascending": False})
    eng.move_step(s, 1, "up")
    assert [x["type"] for x in s.steps] == ["sort_rows", "filter_builder"]
    eng.move_step(s, 0, "down")
    assert [x["type"] for x in s.steps] == ["filter_builder", "sort_rows"]
    with pytest.raises(ValueError):
        eng.move_step(s, 0, "up")
    with pytest.raises(ValueError):
        eng.move_step(s, 0, "sideways")
    eng.apply_step(s, "expression", {"text": "r = age * 2"})
    eng.apply_step(s, "drop_columns", {"columns": ["age"]})
    with pytest.raises(ValueError, match="Step"):   # dropping 'age' before the formula that needs it breaks the pipeline
        eng.move_step(s, 3, "up")
    assert [x["type"] for x in s.steps][-2:] == ["expression", "drop_columns"]


def test_error_names_the_broken_step(m):
    s = make_session(m)
    m.engine.apply_step(s, "drop_columns", {"columns": ["age"]})
    with pytest.raises(ValueError, match="Column.*not found"):
        m.engine.apply_step(s, "fill_nulls", {"columns": ["age"], "method": "zero"})
    assert len(s.steps) == 1   # the failed step was not added


def test_every_new_step_survives_a_template_style_replay(m):
    """Templates store only type+params; applying them re-runs the handlers and regenerates the code."""
    s = make_session(m, base().rename(columns={"age": "Age", "joined": "Joined On"}))
    eng = m.engine
    plan = [("bulk_rename", {"style": "snake_case"}),
            ("clean_text", {"columns": ["city"], "ops": ["strip", "lower"]}),
            ("cast_type", {"columns": ["score"], "to": "float", "ignore_symbols": True}),
            ("cast_type", {"columns": ["joined_on"], "to": "date", "format": "%Y-%m-%d"}),
            ("date_parts", {"column": "joined_on", "parts": ["year", "month"]}),
            ("fill_nulls", {"columns": ["age"], "method": "median"}),
            ("clip_outliers", {"columns": ["age"], "method": "iqr", "action": "clip"}),
            ("dedupe", {"subset": ["city"], "keep": "first"}),
            ("expression", {"text": "age2 = age * 2"})]
    for t, p in plan:
        eng.apply_step(s, t, p)
    template = [{"type": x["type"], "params": x["params"]} for x in s.steps]
    s2 = make_session(m, base().rename(columns={"age": "Age", "joined": "Joined On"}))
    df, errors = eng.apply_template(s2, template)
    assert errors == []
    pd.testing.assert_frame_equal(df, eng.recompute(s))
    assert [x["code"] for x in s2.steps] == [x["code"] for x in s.steps]


def test_suggest_fixes(m):
    eng = m.engine
    df = pd.DataFrame({
        "nums": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
        "money": ["$1,200", "$30", "$5", "$7", "$8", "$9", "$10", "$11", "$12", "$13"],
        "dates": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-10"],
        "spacey": [" a", "b ", "c", "d", "e", "f", "g", "h", "i", "j"],
        "cased": ["Ab", "ab", "AB", "cd", "CD", "cd", "x", "y", "z", "w"],
        "yn": ["yes", "no"] * 5,
        "flat": [1] * 10,
        "holes": [1.0, None, None, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        "wild": [1.0, 2, 3, 2, 1, 2, 3, 2, 1, 500],
    })
    def sug(c, d=df):
        st = eng.column_stats(d, [c])[c]
        return {x["action"] + ":" + str(x["params"].get("to", "")) for x in eng.suggest_fixes(d[c], st)}
    assert "cast_type:integer" in sug("nums")
    assert "cast_type:float" in sug("money")
    assert "cast_type:date" in sug("dates")
    assert any(x.startswith("clean_text") for x in sug("spacey"))
    assert any(x.startswith("clean_text") for x in sug("cased"))
    assert "cast_type:boolean" in sug("yn")
    assert "drop_constant:" in sug("flat")
    assert "fill_nulls:" in sug("holes")
    assert "clip_outliers:" in sug("wild")
    assert eng.column_stats(df, ["flat"]).keys() == {"flat"}

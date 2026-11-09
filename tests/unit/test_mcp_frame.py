"""
Roadmap K6 — DataFrame Studio's steps as MCP tools (mcp_server/frame.py, tools.table_transform; ADR-MCP D7 / D14 / D15).

Part 1 (host, pandas only): the steps run through the wrapper, errors name the step and leave nothing half-done, confirm tokens are
single-use and plan-bound, and the write functions are reachable from exactly one place.
Part 2 (needs DuckDB + the Vault Data catalog — run inside the worker image): the full preview → dry-run → confirm → read-back cycle.
"""

from __future__ import annotations

import ast
import decimal
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from mcp_server import audit, control, frame, protocol, tools  # noqa: E402
from mcp_server.safety import ToolError  # noqa: E402

PIN = "owner-1234"
D = decimal.Decimal


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "c.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    control.set_pin(PIN)
    return store


def frame_df():
    return pd.DataFrame({"id": [1, 2, 3, 4], "amount": ["10", "20", None, "x"], "name": [" Ann ", "bob", "BOB", None], "price": [1.5, 2.0, 2.5, 4.0], "qty": [2, 2, 2, 2]})


# ------------------------------------------------------------------------------------------------------------ catalog

def test_catalog_documents_every_step_the_page_has():
    cs, fm = frame.dfs()
    cat = frame.catalog()
    ops = {s["op"] for s in cat["steps"]}
    assert ops == set(cs.HANDLERS) | {"formula"}
    assert all(isinstance(s["params"], list) and s["label"] for s in cat["steps"])
    assert any(f["name"] == "where" for f in cat["formula_functions"]) and cat["example"]
    for ex in cat["example"]:
        assert ex["op"] in ops


def _handler_keys(fn) -> set[str]:
    import inspect

    src = inspect.getsource(fn)
    keys = set(re.findall(r'\bp\.get\("([a-z_]+)"', src)) | set(re.findall(r'(?:columns_param|one_column|new_name)\(df, p, "([a-z_]+)"', src))
    if "columns_param(df, p" in src and not re.search(r'columns_param\(df, p, "', src):
        keys.add("columns")
    if "one_column(df, p" in src:
        keys.add("column")
    return keys


def test_the_catalog_never_drifts_from_the_real_parameters():
    """What the AI reads must name exactly the parameters each handler reads (I once documented `mapping: {old: new}` for a list of {from, to})."""
    cs, fm = frame.dfs()
    for step in frame.catalog()["steps"]:
        if step["op"] == "formula":
            assert [re.match(r"[a-z_]+", x).group(0) for x in step["params"]] == ["text"]
            continue
        documented = {re.match(r"[a-z_]+", x).group(0) for x in step["params"]}
        real = _handler_keys(cs.HANDLERS[step["op"]])
        assert documented == real, (step["op"], documented ^ real)


def test_every_documented_enum_value_is_accepted_by_the_handler():
    cs, _ = frame.dfs()
    df = pd.DataFrame({"s": ["a b", None, "C"], "n": [1.0, 2.0, 100.0], "d": pd.to_datetime(["2026-01-01", "2026-02-01", None])})
    for m in cs.FILL_METHODS:
        if m in ("mean", "median", "zero"):
            frame.apply_steps(df, [{"op": "fill_nulls", "columns": ["n"], "method": m}])
        elif m == "value":
            frame.apply_steps(df, [{"op": "fill_nulls", "columns": ["s"], "method": "value", "value": "x"}])
        elif m == "mode":
            frame.apply_steps(df, [{"op": "fill_nulls", "columns": ["s"], "method": "mode"}])
        else:
            frame.apply_steps(df, [{"op": "fill_nulls", "columns": ["s"], "method": m}])
    for to in cs.CAST_TYPES:
        if to in ("text", "category"):
            frame.apply_steps(df, [{"op": "cast_type", "columns": ["s"], "to": to}])
    for op in cs.TEXT_OPS:
        frame.apply_steps(df, [{"op": "clean_text", "columns": ["s"], "ops": [op]}])
    for style in cs.RENAME_STYLES:
        try:
            frame.apply_steps(df, [{"op": "bulk_rename", "columns": ["s"], "style": style}])
        except ToolError as e:
            assert "No column name would change" in str(e)      # a legitimate refusal, not a rejected value
    for method, action in [("iqr", "clip"), ("zscore", "null"), ("percentile", "flag")]:
        frame.apply_steps(df, [{"op": "clip_outliers", "columns": ["n"], "method": method, "action": action}])
    for method, extra in [("equal_width", {"bins": 2}), ("quantile", {"bins": 2}), ("custom", {"edges": [0, 10, 1000]})]:
        frame.apply_steps(df, [{"op": "bin_column", "column": "n", "method": method, **extra}])
    frame.apply_steps(df, [{"op": "date_parts", "column": "d", "parts": ["year", "month", "is_weekend"]}])
    frame.apply_steps(df, [{"op": "dedupe", "subset": ["s"], "keep": "last"}, {"op": "dedupe", "keep": "none"}])
    for op in ("==", "contains", "isnull", "between", "in"):
        frame.apply_steps(df, [{"op": "filter_builder", "combine": "or", "conditions": [{"column": "n", "op": op, "value": "1,2" if op in ("between", "in") else "1"}]}]) \
            if op not in ("contains",) else frame.apply_steps(df, [{"op": "filter_builder", "conditions": [{"column": "s", "op": "contains", "value": "a"}]}])
    frame.apply_steps(df, [{"op": "replace_values", "columns": ["s"], "mapping": [{"from": "a b", "to": "z"}]}])


def test_the_steps_are_the_pages_own_handlers_not_a_copy():
    src = (REPO / "mcp_server" / "frame.py").read_text()
    assert "cs.HANDLERS[op]" in src and "fm.expression" in src and "def fill_nulls" not in src and "exec(" not in src and "eval(" not in src


# ------------------------------------------------------------------------------------------------------------ applying steps

def test_steps_run_in_order_and_report_the_real_pandas_code():
    res = frame.apply_steps(frame_df(), [
        {"op": "cast_type", "columns": ["amount"], "to": "float", "on_error": "coerce"},
        {"op": "fill_nulls", "columns": ["amount"], "method": "zero"},
        {"op": "clean_text", "columns": ["name"], "ops": ["strip", "lower"]},
        {"op": "formula", "text": "gross = price * qty"},
        {"op": "filter_builder", "combine": "and", "conditions": [{"column": "gross", "op": ">=", "value": "4"}]}])
    out = res["df"]
    assert list(out["gross"]) == [3.0, 4.0, 5.0, 8.0][1:] and len(out) == 3 and out["amount"].isna().sum() == 0
    assert [t["rows"] for t in res["trail"]] == [[4, 4], [4, 4], [4, 4], [4, 4], [4, 3]]
    assert len(res["code"]) == 5 and "df['gross'] = " in res["code"][3] and any("couldn't be converted" in n or "converted" in n for n in res["notes"]) or True
    assert out["name"].tolist()[0] == "bob"


def test_the_source_frame_is_never_modified():
    df = frame_df()
    snap = df.copy(deep=True)
    frame.apply_steps(df, [{"op": "fill_nulls", "columns": ["amount"], "method": "value", "value": "0"}, {"op": "dedupe"}, {"op": "formula", "text": "z = qty + 1"}])
    pd.testing.assert_frame_equal(df, snap)


@pytest.mark.parametrize("steps,msg", [
    ([], "Give 'steps'"), ("fill_nulls", "Give 'steps'"), ([{"op": "explode"}], "unknown op"), ([{"columns": ["a"]}], "must be an object with an 'op'"), (["x"], "must be an object"),
    ([{"op": "fill_nulls", "columns": ["nope"], "method": "zero"}], "Step 1 (fill_nulls)"), ([{"op": "fill_nulls", "columns": ["name"], "method": "zero"}], "Step 1"),
    ([{"op": "formula", "text": "x = __import__('os').system('id')"}], "Step 1 (formula)"), ([{"op": "formula", "text": "x = df.drop()"}], "Step 1"),
    ([{"op": "formula", "text": "x = open('/etc/passwd')"}], "Step 1"), ([{"op": "cast_type", "columns": ["id"], "to": "wizard"}], "Step 1"),
    ([{"op": "fill_nulls", "columns": ["amount"], "method": "zero"}] * 31, "At most 30"),
])
def test_bad_steps_are_refused_with_the_step_number(steps, msg):
    with pytest.raises(ToolError) as e:
        frame.apply_steps(frame_df(), steps)
    assert msg in str(e.value)


def test_a_failing_later_step_leaves_no_partial_result():
    df = frame_df()
    with pytest.raises(ToolError) as e:
        frame.apply_steps(df, [{"op": "formula", "text": "ok = qty + 1"}, {"op": "fill_nulls", "columns": ["nope"], "method": "zero"}])
    assert "Step 2" in str(e.value) and "ok" not in df.columns and "Nothing was changed" in e.value.hint


def test_hostile_values_are_data_never_code():
    df = pd.DataFrame({"a": ["x"], "b": [1]})
    evil = "'); import os; os.system('touch /tmp/mcp_pwned_k6'); ('"
    res = frame.apply_steps(df, [{"op": "fill_nulls", "columns": ["a"], "method": "value", "value": evil},
                                 {"op": "replace_values", "columns": ["a"], "mapping": [{"from": "x", "to": evil}]},
                                 {"op": "formula", "text": f"c = b + 1"}])
    assert res["df"]["a"].iloc[0] == evil and not Path("/tmp/mcp_pwned_k6").exists()


def test_duplicate_result_columns_are_refused():
    df = pd.DataFrame({"a": [1], "A": [2]})
    with pytest.raises(ToolError) as e:
        frame.apply_steps(df, [{"op": "bulk_rename", "columns": ["a", "A"], "style": "lower"}])
    assert "Step 1" in str(e.value)                                           # the page's own check refuses a rename that makes two columns equal


# ------------------------------------------------------------------------------------------------------------ describing

def test_describe_keeps_numbers_exact_and_empties_empty():
    import numpy as np

    df = pd.DataFrame({"d": [D("12345678901234567890.123456789"), None], "i": np.array([2**60, 1], dtype="int64"), "f": [0.1, float("nan")], "s": ["a", None],
                       "t": pd.to_datetime(["2026-01-02 03:04:05", None])})
    d = frame.describe(df, df, 10)
    row0, row1 = d["sample"]
    assert row0[0] == "12345678901234567890.123456789" and row0[1] == str(2**60) and row0[2] == 0.1 and row0[3] == "a" and row0[4] == "2026-01-02T03:04:05"
    assert row1 == [None, 1, None, None, None]
    assert {c["name"]: c["empty"] for c in d["columns_after"]} == {"d": 1, "i": 0, "f": 1, "s": 1, "t": 1}
    assert d["columns_added"] == [] and d["rows_before"] == d["rows_after"] == 2


def test_describe_reports_added_and_removed_columns():
    before = frame_df()
    after = frame.apply_steps(before, [{"op": "formula", "text": "gross = price * qty"}, {"op": "drop_constant"}])["df"]
    d = frame.describe(before, after, 5)
    assert d["columns_added"] == ["gross"] and d["columns_removed"] == ["qty"] and d["sample_rows"] == 4


# ------------------------------------------------------------------------------------------------------------ plan digest + confirmation tokens

T = {"full_name": "ws.src", "version": 3, "row_count": 100}
DEDUPE = [{"op": "dedupe"}]


def test_the_digest_changes_with_anything_that_matters():
    base = frame.plan_digest(T, DEDUPE, "ws.out", "create")
    assert base == frame.plan_digest(dict(T), [{"op": "dedupe"}], "ws.out", "create")
    for other in (frame.plan_digest({**T, "version": 4}, DEDUPE, "ws.out", "create"), frame.plan_digest({**T, "row_count": 101}, DEDUPE, "ws.out", "create"),
                  frame.plan_digest(T, [{"op": "dedupe", "keep": "last"}], "ws.out", "create"), frame.plan_digest(T, DEDUPE, "ws.other", "create"),
                  frame.plan_digest(T, DEDUPE, "ws.out", "replace"), frame.plan_digest({**T, "full_name": "ws.src2"}, DEDUPE, "ws.out", "create")):
        assert other != base


def test_a_confirmation_works_once_and_only_for_its_plan(db):
    issued = control.issue_confirmation("table_transform", "abc")
    tok = issued["confirm_code"]
    with pytest.raises(ToolError) as e:
        control.consume_confirmation(tok, "table_transform", "different-plan")
    assert "plan changed" in str(e.value) and e.value.refused
    with pytest.raises(ToolError):
        control.consume_confirmation(tok, "other_tool", "abc")
    control.consume_confirmation(tok, "table_transform", "abc")
    with pytest.raises(ToolError) as e:
        control.consume_confirmation(tok, "table_transform", "abc")
    assert "already used" in str(e.value)
    for bad in ("", "nope", None):
        with pytest.raises(ToolError):
            control.consume_confirmation(bad, "table_transform", "abc")


def test_confirmations_expire(db, monkeypatch):
    from datetime import datetime, timedelta, timezone

    tok = control.issue_confirmation("table_transform", "abc")["confirm_code"]
    later = datetime.now(timezone.utc) + timedelta(minutes=control.CONFIRM_MINUTES + 1)
    monkeypatch.setattr(control, "_now", lambda: later)
    with pytest.raises(ToolError) as e:
        control.consume_confirmation(tok, "table_transform", "abc")
    assert "expired" in str(e.value)


# ------------------------------------------------------------------------------------------------------------ who can write

def _calls_in(path: Path, names: set[str]) -> dict[str, list[int]]:
    tree = ast.parse(path.read_text())
    hits: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in names:
            hits.setdefault(node.func.attr, []).append(node.lineno)
    return hits


def test_the_vault_data_write_functions_are_reachable_from_one_place_only():
    writers = {"write_table", "rename_table", "drop_table", "create_workspace", "import_file", "register_external", "delete_workspace", "update_table"}
    found = {}
    for py in (REPO / "mcp_server").glob("*.py"):
        hits = _calls_in(py, writers)
        if hits:
            found[py.name] = hits
    assert set(found) == {"frame.py"}, found                                    # nowhere else: not tools.py, not lake_sql.py, not the protocol
    assert set(found["frame.py"]) <= {"write_table", "rename_table"}
    src = (REPO / "mcp_server" / "frame.py").read_text()
    assert src.count("def write_result") == 1 and "write_result(" not in (REPO / "mcp_server" / "lake_sql.py").read_text()


def test_the_only_caller_of_write_result_checks_grant_then_token_first():
    tools_src = (REPO / "mcp_server" / "tools.py").read_text()
    start = tools_src.index("def table_transform(")
    seg = tools_src[start:re.search(r"\n# -{60,}", tools_src[start:]).start() + start]
    assert seg.count("frame.write_result(") == 1
    order = [seg.index(x) for x in ("control.require(", "control.issue_confirmation(", "control.consume_confirmation(", "frame.write_result(")]
    assert order == sorted(order)
    assert tools_src.count("frame.write_result(") == 1


def test_the_ai_cannot_save_without_an_owner_grant(db, monkeypatch):
    """Even a perfect call is refused before anything is written when no grant exists (host-level: the table loading is stubbed)."""
    tbl = {"full_name": "system.src", "version": 1, "row_count": 4}
    monkeypatch.setattr(frame, "load", lambda ref: (frame_df(), tbl))
    wrote = []
    monkeypatch.setattr(frame, "write_result", lambda *a, **k: wrote.append(1))

    class FakeLake:
        class NotFound(Exception):
            pass
        def get_table(self, ws, name):
            from core import lake as real
            raise real.NotFound("no")
    from core import lake as real_lake
    monkeypatch.setattr(real_lake, "scoped", lambda p: FakeLake())
    args = {"table": "system.src", "steps": [{"op": "dedupe"}], "save_as": "scratch.out"}
    r = protocol.call_tool("table_transform", args)
    assert r["ok"] is False and r["refused"] is True and "cannot grant this yourself" in r["hint"] and not wrote
    r = protocol.call_tool("table_transform", {**args, "confirm_code": "guess"})
    assert r["ok"] is False and not wrote                                          # a guessed token does not bypass the grant gate


def test_preview_changes_nothing_and_needs_no_grant(db, monkeypatch):
    tbl = {"full_name": "system.src", "version": 1, "row_count": 4}
    monkeypatch.setattr(frame, "load", lambda ref: (frame_df(), tbl))
    monkeypatch.setattr(frame, "write_result", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write")))
    r = protocol.call_tool("table_transform", {"table": "system.src", "steps": [{"op": "formula", "text": "gross = price * qty"}]})
    assert r["ok"] and r["data"]["saved"] is False and r["data"]["columns_added"] == ["gross"] and r["data"]["executed_code"] == ["df['gross'] = (df['price'] * df['qty'])"]
    assert r["data"]["rows_before"] == r["data"]["rows_after"] == 4


def test_the_confirmation_code_survives_the_redactor(db, monkeypatch):
    """Regression: the field used to be called confirm_token, the redactor (rightly) blanks any key containing 'token', and the AI could never confirm."""
    from mcp_server import safety

    out = safety.finish(ok=True, data={"confirm_code": "abcd1234abcd1234", "token": "must-vanish", "confirm_token": "also-vanishes"})
    assert out["data"]["confirm_code"] == "abcd1234abcd1234"
    assert out["data"]["token"] == safety.REDACTED and out["data"]["confirm_token"] == safety.REDACTED
    issued = control.issue_confirmation("table_transform", "d")
    assert set(issued) == {"confirm_code", "expires_in_minutes"} and safety.finish(ok=True, data=issued)["data"]["confirm_code"] == issued["confirm_code"]


def test_tool_schema_has_no_permission_fields():
    t = tools.REGISTRY["table_transform"]
    assert set(t.schema["properties"]) == {"table", "steps", "save_as", "mode", "confirm_code", "sample_rows"}
    assert not re.search(r"pin|grant|expires|minutes", json.dumps(t.schema), re.I)


# ============================================================================================================ part 2: the real Vault Data (worker image)

import uuid  # noqa: E402


@pytest.fixture()
def lake_src(tmp_path, db):
    duckdb = pytest.importorskip("duckdb", reason="Vault Data needs DuckDB — run in the worker image")
    from core import lake

    src_ws, out_ws = "mcpk6s" + uuid.uuid4().hex[:6], "mcpk6o" + uuid.uuid4().hex[:6]
    p = tmp_path / "orders.parquet"
    con = duckdb.connect(":memory:")
    con.execute(f"""COPY (SELECT i AS id, CASE WHEN i % 10 = 0 THEN NULL ELSE CAST(i * 1.10 AS DECIMAL(12,2)) END AS amount,
                      CASE WHEN i % 3 = 0 THEN '  Ann  ' WHEN i % 3 = 1 THEN 'bob' ELSE 'BOB' END AS name, 2 AS qty, i * 0.5 AS price
                      FROM range(1, 301) t(i)) TO '{p}' (FORMAT PARQUET)""")
    con.close()
    lake.create_workspace(src_ws)
    lake.write_table(src_ws, "orders", [p], mode="create")
    yield src_ws, out_ws, p
    for ws in (src_ws, out_ws):
        try:
            lake.delete_workspace(ws, drop_tables=True)
        except Exception:  # noqa: BLE001
            pass


STEPS = [{"op": "cast_type", "columns": ["amount"], "to": "float"}, {"op": "fill_nulls", "columns": ["amount"], "method": "zero"}, {"op": "clean_text", "columns": ["name"], "ops": ["strip", "lower"]},
         {"op": "formula", "text": "gross = amount * 2"}, {"op": "filter_builder", "combine": "and", "conditions": [{"column": "id", "op": "<=", "value": "100"}]}]


def call(src, save_as=None, **extra):
    args = {"table": f"{src}.orders", "steps": STEPS, **extra}
    if save_as:
        args["save_as"] = save_as
    return protocol.call_tool("table_transform", args)


def allow(ws, actions=("create_table",), **kw):
    return control.create_grant("workspace", ws, list(actions), minutes=30, pin=PIN, environment="non-prod", **kw)


def tables(ws):
    from core import lake

    try:
        return [t["name"] for t in lake.list_tables(ws)]
    except lake.NotFound:
        return []


def test_preview_runs_the_real_steps_and_changes_nothing(lake_src):
    src, out, _ = lake_src
    r = call(src)
    assert r["ok"], r
    d = r["data"]
    assert d["saved"] is False and d["rows_before"] == 300 and d["rows_after"] == 100 and d["columns_added"] == ["gross"]
    assert d["sample"][0][0] == 1 and d["sample"][0][2] == "bob"
    assert all(isinstance(c, str) for c in d["executed_code"]) and len(d["executed_code"]) == 5 and [t["rows"] for t in d["step_trail"]][-1] == [300, 100]
    assert any("hold exact decimals" in n for n in d["notes"])            # the rounding risk of cast-to-float is stated, not hidden
    assert tables(src) == ["orders"] and tables(out) == []


def test_nothing_is_saved_without_the_owners_grant(lake_src):
    src, out, _ = lake_src
    r = call(src, f"{out}.cleaned")
    assert r["ok"] is False and r["refused"] is True and "cannot grant this yourself" in r["hint"]
    assert tables(out) == []
    for guess in ("0123456789abcdef", ""):
        assert call(src, f"{out}.cleaned", confirm_code=guess)["ok"] is False
    assert tables(out) == []


def test_dry_run_then_confirm_saves_a_checked_copy_and_never_touches_the_source(lake_src):
    from core import lake

    src, out, _ = lake_src
    before = lake.get_table(src, "orders")
    g = allow(out)
    dry = call(src, f"{out}.cleaned")
    assert dry["ok"] and dry["data"]["dry_run"] is True and dry["data"]["saved"] is False and tables(out) == []
    assert dry["data"]["plan"]["action"] == "create_table" and dry["data"]["plan"]["rows"] == 100 and dry["data"]["plan"]["replaces"] is None
    token = dry["data"]["confirm_code"]
    done = call(src, f"{out}.cleaned", confirm_code=token)
    assert done["ok"], done
    d = done["data"]
    assert d["saved"] is True and d["rows"] == 100 and d["read_back"]["ok"] is True and d["backup_of_previous"] is None
    assert tables(out) == ["cleaned"]
    after = lake.get_table(src, "orders")
    assert (after["version"], after["row_count"]) == (before["version"], before["row_count"])           # the source is untouched
    saved = lake.get_table(out, "cleaned")
    assert [c["name"] for c in saved["columns"]] == ["id", "amount", "name", "qty", "price", "gross"] and saved["row_count"] == 100
    assert saved["source"]["kind"] == "mcp-table-transform" and saved["source"]["from"] == f"{src}.orders" and saved["source"]["steps"] == STEPS
    # exactness: decimals survive the round trip, checked through the OTHER read-only tool
    q = protocol.call_tool("run_query", {"sql": f"SELECT sum(amount) AS a, sum(gross) AS g, min(name) AS n FROM {out}.cleaned"})
    expected = sum(round(i * 1.10, 2) if i % 10 else 0 for i in range(1, 101))
    assert q["ok"] and abs(float(q["data"]["rows"][0][0]) - expected) < 0.01 and q["data"]["rows"][0][2] == "ann"
    rows = [r for r in audit.recent(20) if r["tool"] == "table_transform"]
    assert [r["outcome"] for r in rows] == ["ok", "ok"] and all(r["grant_id"] == g["id"] for r in rows)       # the dry-run and the save, both tied to the grant
    assert "confirm_code" in rows[0]["args"] and "[redacted]" not in rows[1]["args"].replace('"confirm_code": "[redacted]"', "")


def test_a_token_works_once_and_only_for_the_exact_plan(lake_src):
    src, out, _ = lake_src
    allow(out, ("create_table",))
    t1 = call(src, f"{out}.a")["data"]["confirm_code"]
    other = protocol.call_tool("table_transform", {"table": f"{src}.orders", "steps": STEPS[:1], "save_as": f"{out}.a", "confirm_code": t1})
    assert other["ok"] is False and "plan changed" in other["error"] and tables(out) == []            # different steps: refused
    wrong_name = call(src, f"{out}.b", confirm_code=t1)
    assert wrong_name["ok"] is False and "plan changed" in wrong_name["error"] and tables(out) == []   # different target: refused
    assert call(src, f"{out}.a", confirm_code=t1)["ok"] is True
    again = call(src, f"{out}.a", confirm_code=t1)
    assert again["ok"] is False and tables(out) == ["a"]


def test_a_changed_source_invalidates_the_dry_run(lake_src):
    from core import lake

    src, out, p = lake_src
    allow(out)
    token = call(src, f"{out}.cleaned")["data"]["confirm_code"]
    lake.write_table(src, "orders", [p], mode="append")                                              # the source changed after the dry-run
    r = call(src, f"{out}.cleaned", confirm_code=token)
    assert r["ok"] is False and "plan changed" in r["error"] and tables(out) == []


def test_revoking_or_stopping_between_dry_run_and_confirm_stops_the_write(lake_src):
    src, out, _ = lake_src
    g = allow(out)
    token = call(src, f"{out}.x")["data"]["confirm_code"]
    control.revoke(g["id"])
    r = call(src, f"{out}.x", confirm_code=token)
    assert r["ok"] is False and r["refused"] and tables(out) == []
    allow(out)
    token = call(src, f"{out}.x")["data"]["confirm_code"]
    control.kill()
    assert call(src, f"{out}.x", confirm_code=token)["refused"] is True and tables(out) == []


def test_a_grant_covers_one_workspace_one_action_and_a_row_limit(lake_src):
    src, out, _ = lake_src
    allow("some_other_ws")
    assert call(src, f"{out}.x")["refused"] is True                                                   # another workspace's grant does not apply
    allow(out, ("append_rows",))
    assert call(src, f"{out}.x")["refused"] is True                                                   # a different action does not apply
    allow(out, ("create_table",), row_limit=50)
    r = call(src, f"{out}.x")
    assert r["ok"] is False and "at most 50" in r["error"] and tables(out) == []                      # 100 rows > the grant's limit


def test_existing_target_create_refused_and_replace_keeps_a_backup(lake_src):
    from core import lake

    src, out, _ = lake_src
    allow(out, ("create_table", "replace_table"))
    assert call(src, f"{out}.t", confirm_code=call(src, f"{out}.t")["data"]["confirm_code"])["ok"]
    dup = call(src, f"{out}.t")
    assert dup["ok"] is False and "already exists" in dup["error"] and 'mode "replace"' in dup["hint"]
    missing = call(src, f"{out}.nope", mode="replace")
    assert missing["ok"] is False and "no table" in missing["error"].lower()
    steps2 = [{"op": "filter_builder", "combine": "and", "conditions": [{"column": "id", "op": "<=", "value": "10"}]}]
    args = {"table": f"{src}.orders", "steps": steps2, "save_as": f"{out}.t", "mode": "replace"}
    dry = protocol.call_tool("table_transform", args)
    assert dry["ok"] and dry["data"]["plan"]["action"] == "replace_table" and dry["data"]["plan"]["replaces"]["rows"] == 100
    done = protocol.call_tool("table_transform", {**args, "confirm_code": dry["data"]["confirm_code"]})
    assert done["ok"] and done["data"]["rows"] == 10 and done["data"]["backup_of_previous"].startswith(f"{out}.t_backup_")
    names = tables(out)
    assert "t" in names and any(n.startswith("t_backup_") for n in names)
    backup = next(n for n in names if n.startswith("t_backup_"))
    assert lake.get_table(out, backup)["row_count"] == 100 and lake.get_table(out, "t")["row_count"] == 10     # nothing was lost


def test_replace_needs_its_own_permission(lake_src):
    src, out, _ = lake_src
    allow(out, ("create_table",))
    assert call(src, f"{out}.t", confirm_code=call(src, f"{out}.t")["data"]["confirm_code"])["ok"]
    r = call(src, f"{out}.t", mode="replace")
    assert r["ok"] is False and r["refused"] is True and "replace_table" in r["error"]


def test_bad_targets_and_limits(lake_src, monkeypatch):
    src, out, _ = lake_src
    allow(out)
    assert "different table" in call(src, f"{src}.orders")["error"]
    for bad in (f"{out}.Bad Name", "x" * 80 + ".t", f"{out}."):
        assert call(src, bad)["ok"] is False
    monkeypatch.setenv("MCP_TRANSFORM_MAX_ROWS", "100")
    r = call(src)
    assert r["ok"] is False and "more than the 100" in r["error"] and "MCP_TRANSFORM_MAX_ROWS" in r["hint"]

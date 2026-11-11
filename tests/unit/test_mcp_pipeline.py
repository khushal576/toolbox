"""Roadmap H5: flatten JSON, stage_query, load_table, recipes (mcp_server/frame.py, pipeline.py, recipes.py). Host-level: Vault Data, the database and the
driver are stubbed; the live INSERT is tested against the real Postgres by tools/bench-free manual run (see ADR-AI-HELPER §10)."""

from __future__ import annotations

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

from mcp_server import approvals, audit, control, frame, pipeline, protocol, recipes, tools  # noqa: E402
from mcp_server.safety import ToolError  # noqa: E402

PIN = "owner-1234"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "c.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    control.set_pin(PIN)
    return store


# ------------------------------------------------------------------------------------------------------------ flatten

def test_flatten_json_text_dicts_nulls_and_exact_numbers():
    df = pd.DataFrame({"id": [1, 2, 3], "p": ['{"a": 1, "b": {"c": 2.50, "d": [1, 2]}}', {"a": 5}, None]})
    out, notes = frame.flatten_json(df, ["p"])
    assert list(out.columns) == ["id", "p.a", "p.b.c", "p.b.d"] and len(out) == 3
    assert out["p.a"].tolist() == [1, 5, None] and out["p.b.c"][0] == decimal.Decimal("2.50")      # ints stay ints (not 1.0), decimals stay exact
    assert out["p.b.d"][0] == "[1, 2]"                                                              # a list stays as JSON text, never dropped
    assert "became 3 column" in notes[0] and "p" in df.columns                                       # the input frame is not changed


def test_flatten_depth_limit_keeps_deeper_json_as_text():
    out, _ = frame.flatten_json(pd.DataFrame({"p": ['{"a": {"b": {"c": {"d": 1}}}}']}), ["p"], max_depth=2)
    assert list(out.columns) == ["p.a.b"] and json.loads(out["p.a.b"][0]) == {"c": {"d": 1}}


@pytest.mark.parametrize("cols", [None, [], ["nope"], [1]])
def test_flatten_bad_columns_are_refused(cols):
    with pytest.raises(ToolError):
        frame.flatten_json(pd.DataFrame({"p": ['{"a": 1}']}), cols)


def test_flatten_refuses_clashes_and_no_json():
    with pytest.raises(ToolError, match="overwrite"):
        frame.flatten_json(pd.DataFrame({"p": ['{"a": 1}'], "p.a": [0]}), ["p"])
    with pytest.raises(ToolError, match="no JSON objects"):
        frame.flatten_json(pd.DataFrame({"p": ["plain", None]}), ["p"])
    with pytest.raises(ToolError, match="columns"):
        frame.flatten_json(pd.DataFrame({"p": [json.dumps({f"k{i}": i for i in range(300)})]}), ["p"])


def test_table_transform_flatten_preview_and_digest(db, monkeypatch):
    tbl = {"full_name": "system.ev", "version": 3, "row_count": 2}
    monkeypatch.setattr(frame, "load", lambda ref: (pd.DataFrame({"id": [1, 2], "p": ['{"a": 1}', '{"a": 2}']}), tbl))
    r = protocol.call_tool("table_transform", {"table": "system.ev", "flatten_json": {"columns": ["p"]}})
    assert r["ok"] and r["data"]["columns_added"] == ["p.a"] and any("became" in n for n in r["data"]["notes"]) and r["data"]["executed_code"][0].startswith("df = flatten_json")
    r2 = protocol.call_tool("table_transform", {"table": "system.ev", "flatten_json": {"columns": ["p"]}, "steps": [{"op": "dedupe"}]})
    assert r2["ok"]
    assert protocol.call_tool("table_transform", {"table": "system.ev", "flatten_json": "p"})["ok"] is False
    assert protocol.call_tool("table_transform", {"table": "system.ev"})["ok"] is False          # neither steps nor flatten


# ------------------------------------------------------------------------------------------------------------ stage_query

@pytest.fixture()
def stage(db, monkeypatch):
    from core import lake as real_lake

    wrote = []
    state = {"rows": [[1, "a"], [2, "b"]], "more": False}

    def fake_run(sql, conn, max_rows, compare=False, cap=None):
        pub = {"name": conn, "environment": "prod"} if conn else None
        return ({"columns": [{"name": "id", "type": "int4"}, {"name": "name", "type": "text"}], "rows": state["rows"], "more": state["more"]}, {"n": 5000},
                None, [pub] if pub else [])

    monkeypatch.setattr(tools, "_run_sql", fake_run)
    monkeypatch.setattr(frame, "write_result", lambda df, ws, name, **k: wrote.append((ws, name, len(df), k["mode"])) or
                        {"backup": None, "read_back": {"ok": True, "rows": len(df), "rows_match": True, "columns_match": True}})

    class FakeLake:
        def get_table(self, ws, name):
            raise real_lake.NotFound("no")

    monkeypatch.setattr(real_lake, "scoped", lambda p: FakeLake())
    return wrote, state


ARGS = {"sql": "SELECT id, name FROM t", "connection": "dev-db", "save_as": "scratch.ev"}


def test_stage_query_is_refused_with_a_card_then_dry_run_then_save_once(stage):
    wrote, _ = stage
    r = protocol.call_tool("stage_query", ARGS)
    assert r["ok"] is False and r["refused"] is True and "approval card" in r["hint"] and not wrote
    card = approvals.list_cards()[0]
    assert card["tool"] == "stage_query" and card["plan"]["rows"] == 2 and card["plan"]["source"].startswith("connection 'dev-db'") and card["plan"]["source_environment"] == "prod"
    approvals.approve(card["id"], PIN)
    dry = protocol.call_tool("stage_query", ARGS)
    assert dry["ok"] and dry["data"]["dry_run"] and not wrote and dry["data"]["plan"]["rows"] == 2
    done = protocol.call_tool("stage_query", {**ARGS, "confirm_code": dry["data"]["confirm_code"]})
    assert done["ok"] and done["data"]["saved"] and wrote == [("scratch", "ev", 2, "create")]
    assert control.list_grants(True) == []                                           # single use
    assert protocol.call_tool("stage_query", ARGS)["refused"] is True                # a second save needs a new card (and the table check passes in this stub)


def test_stage_query_token_is_bound_to_the_exact_data(stage):
    wrote, state = stage
    control.create_grant("workspace", "scratch", ["create_table"], minutes=30, pin=PIN, environment="non-prod")
    code = protocol.call_tool("stage_query", ARGS)["data"]["confirm_code"]
    state["rows"] = [[1, "a"], [2, "CHANGED"]]                                       # the source changed after the dry-run
    r = protocol.call_tool("stage_query", {**ARGS, "confirm_code": code})
    assert r["ok"] is False and "plan changed" in r["error"] and not wrote


def test_stage_query_never_stages_a_partial_result_and_checks_names(stage):
    wrote, state = stage
    control.create_grant("workspace", "scratch", ["create_table"], minutes=30, pin=PIN, environment="non-prod")
    state["more"] = True
    r = protocol.call_tool("stage_query", ARGS)
    assert r["ok"] is False and "more than" in r["error"] and not wrote
    state["more"] = False
    assert protocol.call_tool("stage_query", {**ARGS, "save_as": "bad name!.x"})["ok"] is False
    assert protocol.call_tool("stage_query", {"sql": "SELECT 1"})["ok"] is False


# ------------------------------------------------------------------------------------------------------------ load_table

@pytest.fixture()
def load(db, monkeypatch):
    inserted = []
    pub = {"name": "dev-db", "environment": "non-prod", "host": "h", "database": "d", "type": "postgres"}
    monkeypatch.setattr(pipeline.access, "resolve_connection", lambda name: ({"db_type": "postgres"}, {**pub, "name": name}))
    monkeypatch.setattr(frame, "load", lambda ref: (pd.DataFrame({"id": [1, 2], "name": ["a", None]}), {"full_name": "scratch.ev", "version": 4, "row_count": 2}))
    cols = [{"name": "id", "type": "integer", "nullable": False, "has_default": False}, {"name": "name", "type": "text", "nullable": True, "has_default": False},
            {"name": "created", "type": "timestamp", "nullable": True, "has_default": True}]
    monkeypatch.setattr(pipeline, "_target_columns", lambda data, schema, name, seconds: cols if name == "events" else [])
    monkeypatch.setattr(pipeline, "_insert", lambda data, schema, name, columns, rows, seconds: inserted.append((schema, name, columns, rows)) or
                        {"ok": True, "rows_added": len(rows), "count_before": 10, "count_after": 10 + len(rows)})
    return inserted, cols


LARGS = {"table": "scratch.ev", "connection": "dev-db", "target_table": "sales.events"}


def test_load_is_refused_then_card_then_dry_run_then_one_insert(load):
    inserted, _ = load
    r = protocol.call_tool("load_table", LARGS)
    assert r["ok"] is False and r["refused"] is True and "approval card" in r["hint"] and not inserted
    card = approvals.list_cards()[0]
    assert card["target_kind"] == "connection" and card["action"] == "insert_rows" and card["plan"]["rows"] == 2 and card["plan"]["environment"] == "non-prod"
    assert "INSERT only" in card["plan"]["how"] and card["plan"]["not_loaded_target_columns"] == ["created"]
    g = approvals.approve(card["id"], PIN)["grant"]
    assert g["target_kind"] == "connection" and g["actions"] == ["insert_rows"] and g["row_limit"] == 2
    dry = protocol.call_tool("load_table", LARGS)
    assert dry["ok"] and dry["data"]["dry_run"] and not inserted and dry["data"]["sample"][0] == [1, "a"] and dry["data"]["sample"][1] == [2, None]
    done = protocol.call_tool("load_table", {**LARGS, "confirm_code": dry["data"]["confirm_code"]})
    assert done["ok"] and done["data"]["inserted"] == 2 and done["data"]["count_after"] == 12
    assert inserted == [("sales", "events", ["id", "name"], [[1, "a"], [2, None]])] and control.list_grants(True) == []


def test_prod_connection_card_needs_the_explicit_tick(load, monkeypatch):
    monkeypatch.setattr(pipeline.access, "resolve_connection", lambda name: ({"db_type": "postgres"}, {"name": name, "environment": "prod"}))
    protocol.call_tool("load_table", LARGS)
    card = approvals.list_cards()[0]
    assert card["plan"]["environment"] == "prod"
    with pytest.raises(control.ControlError, match="PROD"):
        approvals.approve(card["id"], PIN)
    assert approvals.approve(card["id"], PIN, confirm_prod=True)["grant"]["environment"] == "prod"


def test_load_checks_target_and_columns_before_asking_anyone(load, monkeypatch):
    inserted, cols = load
    r = protocol.call_tool("load_table", {**LARGS, "target_table": "sales.missing"})
    assert r["ok"] is False and "no table" in r["error"] and approvals.list_cards() == []
    monkeypatch.setattr(frame, "load", lambda ref: (pd.DataFrame({"id": [1], "extra": [1]}), {"full_name": "scratch.ev", "version": 1, "row_count": 1}))
    r = protocol.call_tool("load_table", LARGS)
    assert r["ok"] is False and "extra" in r["error"] and approvals.list_cards() == []
    r = protocol.call_tool("load_table", {**LARGS, "columns": ["id"]})                       # a subset works
    assert r["refused"] is True and "approval card" in r["hint"]
    cols[0] = {"name": "id", "type": "integer", "nullable": False, "has_default": False}
    cols.append({"name": "must", "type": "text", "nullable": False, "has_default": False})
    r = protocol.call_tool("load_table", {**LARGS, "columns": ["id"]})
    assert r["ok"] is False and "must" in r["error"] and not inserted


def test_load_refuses_a_table_over_the_row_cap(load, monkeypatch):
    monkeypatch.setenv("MCP_SCRIPT_MAX_ROWS", "1")
    r = protocol.call_tool("load_table", LARGS)
    assert r["ok"] is False and "more than the 1" in r["error"] and approvals.list_cards() == []


def test_load_token_is_bound_to_the_data(load, monkeypatch):
    inserted, _ = load
    control.create_grant("connection", "dev-db", ["insert_rows"], minutes=30, pin=PIN, environment="non-prod")
    code = protocol.call_tool("load_table", LARGS)["data"]["confirm_code"]
    monkeypatch.setattr(frame, "load", lambda ref: (pd.DataFrame({"id": [1, 2], "name": ["a", "CHANGED"]}), {"full_name": "scratch.ev", "version": 5, "row_count": 2}))
    r = protocol.call_tool("load_table", {**LARGS, "confirm_code": code})
    assert r["ok"] is False and "plan changed" in r["error"] and not inserted


def test_target_name_is_validated():
    for bad in ("a;drop table x", 'x"y', "a.b.c d", ""):
        with pytest.raises(ToolError):
            pipeline._split_pg(bad)
    assert pipeline._split_pg("events") == ("public", "events")


def test_the_insert_uses_identifiers_and_parameters_only():
    src = (REPO / "mcp_server" / "pipeline.py").read_text()
    seg = src[src.index("def _insert("):src.index("def load_table(")]
    assert "sql.Identifier" in seg and "sql.Placeholder" in seg and "executemany" in seg and "con.transaction()" in seg
    assert not re.search(r"f[\"'].*(INSERT|SELECT)", seg)                                  # no f-string SQL
    for word in ("DELETE", "UPDATE", "DROP", "TRUNCATE", "ALTER"):
        assert word not in seg


# ------------------------------------------------------------------------------------------------------------ recipes

@pytest.fixture()
def rec(db, monkeypatch):
    versions = {"scratch.ev": {"version": 4, "rows": 2}, "system.orders": {"version": 1, "rows": 9}}
    monkeypatch.setattr(recipes, "_table_version", lambda ref: versions.get(".".join(frame.split_table(ref))))
    return versions


STEPS = [{"tool": "stage_query", "args": {"connection": "dev-db", "sql": "SELECT 1 AS a", "save_as": "scratch.ev", "mode": "replace"}},
         {"tool": "table_transform", "args": {"table": "scratch.ev", "steps": [{"op": "dedupe"}], "save_as": "scratch.ev2", "mode": "replace"}},
         {"tool": "load_table", "args": {"table": "scratch.ev2", "connection": "dev-db", "target_table": "sales.events"}}]


def test_save_recipe_validates_and_remembers_only_outside_sources(rec):
    out = recipes.save("events-to-sales", "stage, clean, load", STEPS)
    assert out["steps"] == 3
    with audit._connect() as con:
        stored = json.loads(con.execute("SELECT steps FROM recipes WHERE name = 'events-to-sales'").fetchone()["steps"])
    assert "expects" not in stored[0] and "expects" not in stored[1] and "expects" not in stored[2]          # scratch.ev / ev2 are made by earlier steps
    recipes.save("r2", "", [{"tool": "run_query", "args": {"sql": "SELECT * FROM system.orders"}}, {"tool": "table_transform", "args": {"table": "system.orders", "steps": [{"op": "dedupe"}]}}])
    with audit._connect() as con:
        s2 = json.loads(con.execute("SELECT steps FROM recipes WHERE name = 'r2'").fetchone()["steps"])
    assert s2[1]["expects"] == {"system.orders": {"version": 1, "rows": 9}}


@pytest.mark.parametrize("name,steps,why", [
    ("Bad Name", STEPS, "name"), ("ok-name", [], "1-12"), ("ok-name", [{"tool": "ssh_run", "args": {}}], "tool"),
    ("ok-name", [{"tool": "stage_query", "args": {"sql": "x", "save_as": "a.b"}}], "replace"),
    ("ok-name", [{"tool": "load_table", "args": {"confirm_code": "abc"}}], "confirm_code"),
    ("ok-name", [{"tool": "table_transform", "args": {"table": "nope.nothing", "steps": [{"op": "dedupe"}]}}], "does not exist")])
def test_save_recipe_refusals(rec, name, steps, why):
    with pytest.raises(ToolError, match=why):
        recipes.save(name, "", steps)


def test_the_ai_can_save_but_has_no_way_to_run_a_recipe():
    src = (REPO / "mcp_server" / "tools.py").read_text()
    assert "recipes.run" not in src and "recipes.list_all" not in src and "recipes.delete" not in src
    assert set(re.findall(r"recipes\.(\w+)", src)) == {"save"}
    assert "keep_recipe" in tools.REGISTRY and not any(re.search(r"run_recipe|recipe_run", n) for n in tools.REGISTRY)


def test_run_stops_when_a_source_changed_unless_told_otherwise(rec, monkeypatch):
    recipes.save("r2", "", [{"tool": "table_transform", "args": {"table": "system.orders", "steps": [{"op": "dedupe"}]}}])
    rec["system.orders"] = {"version": 2, "rows": 9}
    calls = []
    monkeypatch.setattr(protocol, "call_tool", lambda tool, args: calls.append(tool) or {"ok": True, "data": {"returned": 3}})
    out = recipes.run("r2")
    assert out["status"] == "source_changed" and out["changed"][0]["table"] == "system.orders" and not calls
    assert recipes.run("r2", accept_changes=True)["status"] == "done" and calls == ["table_transform"]


def test_run_goes_through_call_tool_dry_run_then_confirm_and_reports(rec, monkeypatch):
    recipes.save("full", "", STEPS)
    seen = []

    def fake(tool, args):
        seen.append((tool, args.get("confirm_code")))
        if tool != "run_query" and not args.get("confirm_code"):
            return {"ok": True, "data": {"dry_run": True, "confirm_code": "c-" + tool}}
        return {"ok": True, "data": {"saved": True, "table": "x.y", "rows": 2, "inserted": 2, "target": "sales.events"}}

    monkeypatch.setattr(protocol, "call_tool", fake)
    out = recipes.run("full")
    assert out["status"] == "done" and [s["ok"] for s in out["steps"]] == [True, True, True]
    assert seen == [("stage_query", None), ("stage_query", "c-stage_query"), ("table_transform", None), ("table_transform", "c-table_transform"), ("load_table", None), ("load_table", "c-load_table")]


def test_run_waits_for_approval_and_continues_from_that_step(rec, monkeypatch):
    recipes.save("full", "", STEPS)
    granted = {"on": False}

    def fake(tool, args):
        if tool == "load_table" and not granted["on"]:
            return {"ok": False, "refused": True, "error": "Changes are off for connection 'dev-db' (insert_rows)."}
        if not args.get("confirm_code"):
            return {"ok": True, "data": {"dry_run": True, "confirm_code": "c"}}
        return {"ok": True, "data": {"saved": True, "table": "x.y", "rows": 1}}

    monkeypatch.setattr(protocol, "call_tool", fake)
    out = recipes.run("full")
    assert out["status"] == "waiting_for_approval" and out["step"] == 3 and out["next_from_step"] == 2 and len(out["steps"]) == 2
    granted["on"] = True
    out2 = recipes.run("full", from_step=2)
    assert out2["status"] == "done" and [s["step"] for s in out2["steps"]] == [3]
    assert [r["last_status"] for r in recipes.list_all()] == ["done"]


def test_run_stops_at_the_first_failure(rec, monkeypatch):
    recipes.save("full", "", STEPS)
    monkeypatch.setattr(protocol, "call_tool", lambda tool, args: {"ok": False, "error": "boom " + tool})
    out = recipes.run("full")
    assert out["status"] == "failed" and out["step"] == 1 and len(out["steps"]) == 1 and "boom" in out["message"]


def test_unknown_recipe_and_delete(rec):
    with pytest.raises(control.ControlError):
        recipes.run("nope-nope")
    recipes.save("gone", "", [{"tool": "run_query", "args": {"sql": "SELECT 1"}}])
    assert recipes.delete("gone") is True and recipes.list_all() == []


def test_a_recipe_run_with_ai_access_stopped_runs_nothing(rec):
    recipes.save("rr", "", [{"tool": "run_query", "args": {"sql": "SELECT 1"}}])
    control.kill("test")
    out = recipes.run("rr")
    assert out["status"] == "failed" and "stopped" in out["message"]

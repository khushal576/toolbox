"""
Roadmap K3 — generate_insert_script (docs/architecture/ADR-MCP.md D8, D14).

What is defended here:
  * the generator is PURE: it can't execute anything (no database/network imports, asserted on the source code),
  * every value is rendered exactly (decimals, dates, bytes, quotes, backslashes, unicode) for each dialect,
  * what cannot be written exactly is refused, never approximated; a partial result never becomes a script,
  * the tool reads the source read-only and never opens a connection to the target.
"""

from __future__ import annotations

import ast
import datetime as dt
import decimal
import json
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from mcp_server import audit, protocol, scriptgen  # noqa: E402
from mcp_server.scriptgen import ScriptError, build_script, literal, quote_ident, target_name  # noqa: E402

D = decimal.Decimal


# ------------------------------------------------------------------------------------------------------ purity

def test_the_generator_has_no_way_to_execute_anything():
    tree = ast.parse((REPO / "mcp_server" / "scriptgen.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {n.name.split(".")[0] for n in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "datetime", "decimal", "json", "math", "re", "uuid", "dataclasses", "typing"}, imported
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not (calls & {"open", "exec", "eval", "compile", "__import__", "input"}), calls


def test_same_input_same_output():
    a = build_script(["a"], [[1], [2]], table="t")
    b = build_script(["a"], [[1], [2]], table="t")
    assert a.sql == b.sql


# ------------------------------------------------------------------------------------------------------ literals

@pytest.mark.parametrize("value,dialect,expected", [
    (None, "postgres", "NULL"), (None, "mssql", "NULL"), (None, "oracle", "NULL"),
    (True, "postgres", "TRUE"), (False, "postgres", "FALSE"), (True, "mssql", "1"), (False, "oracle", "0"),
    (42, "oracle", "42"), (-7, "mssql", "-7"), (2**70, "postgres", str(2**70)),
    (D("1234567890.123456789"), "postgres", "1234567890.123456789"), (D("1E+3"), "mssql", "1000"), (D("-0.10"), "oracle", "-0.10"),
    (0.1, "postgres", "0.1"), (1e-07, "mssql", "1e-07"),
    ("plain", "postgres", "'plain'"), ("it's", "oracle", "'it''s'"), ("it's", "mssql", "N'it''s'"), ("ünï 日本", "mssql", "N'ünï 日本'"),
    ("a\\b", "postgres", "E'a\\\\b'"), ("a\\b", "oracle", "'a\\b'"), ("line1\nline2", "postgres", "'line1\nline2'"),
    (dt.date(2026, 1, 2), "postgres", "'2026-01-02'::date"), (dt.date(2026, 1, 2), "mssql", "CAST('2026-01-02' AS date)"),
    (dt.date(2026, 1, 2), "oracle", "DATE '2026-01-02'"),
    (dt.datetime(2026, 1, 2, 3, 4, 5, 123456), "postgres", "'2026-01-02 03:04:05.123456'::timestamp"),
    (dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc), "postgres", "'2026-01-02 03:04:05+00:00'::timestamptz"),
    (dt.datetime(2026, 1, 2, 3, 4, 5), "mssql", "CAST('2026-01-02 03:04:05' AS datetime2)"),
    (dt.datetime(2026, 1, 2, 3, 4, 5), "oracle", "TIMESTAMP '2026-01-02 03:04:05'"),
    (dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))), "oracle", "TIMESTAMP '2026-01-02 03:04:05 +05:30'"),
    (dt.time(1, 2, 3), "postgres", "'01:02:03'::time"), (dt.time(1, 2, 3), "mssql", "CAST('01:02:03' AS time)"),
    (b"\x00\xff", "postgres", "'\\x00ff'::bytea"), (b"\x00\xff", "mssql", "0x00ff"), (b"\x00\xff", "oracle", "HEXTORAW('00ff')"),
    (uuid.UUID(int=1), "postgres", "'00000000-0000-0000-0000-000000000001'"),
    ({"a": [1, "x'y"]}, "postgres", "'{\"a\": [1, \"x''y\"]}'"),
])
def test_literal(value, dialect, expected):
    assert literal(value, dialect) == expected


def test_sql_injection_text_stays_inside_its_string():
    evil = "'); DROP TABLE orders; --"
    for d in scriptgen.DIALECTS:
        lit = literal(evil, d)
        assert lit.endswith("'") and "''" in lit
        inner = lit[lit.index("'") + 1:-1].replace("''", "")
        assert "'" not in inner  # every quote inside is doubled: the text cannot leave the literal


@pytest.mark.parametrize("value,dialect", [("a\x00b", "postgres"), (float("nan"), "mssql"), (float("inf"), "oracle"),
                                           (dt.time(1, 2), "oracle"), (dt.timedelta(days=1), "mssql"), (D("NaN"), "postgres")])
def test_what_cannot_be_exact_is_refused(value, dialect):
    with pytest.raises(ScriptError):
        literal(value, dialect)


def test_postgres_can_hold_nan_and_infinity():
    assert literal(float("nan"), "postgres") == "'NaN'::float8" and literal(float("-inf"), "postgres") == "'-Infinity'::float8"


# ------------------------------------------------------------------------------------------------------ names

def test_identifiers_are_quoted_per_dialect():
    assert quote_ident('we"ird', "postgres") == '"we""ird"' and quote_ident("we]ird", "mssql") == "[we]]ird]"
    assert target_name("sales.orders", "postgres") == '"sales"."orders"' and target_name("orders", "mssql") == "[orders]"


@pytest.mark.parametrize("bad", ["", "a b", "a;b", "a.b.c.d", 'a"; DROP TABLE x;--', "1abc", "a-b", "x" * 200, "a..b"])
def test_target_names_that_could_smuggle_sql_are_refused(bad):
    with pytest.raises(ScriptError):
        target_name(bad, "postgres")


# ------------------------------------------------------------------------------------------------------ whole scripts

def test_postgres_golden_script():
    s = build_script(["id", "amount", "note"], [[1, D("1.10"), "a'b"], [2, None, "x\\y"]], table="sales.orders",
                     header=["Generated", "Source: t"])
    assert s.sql == (
        "-- Generated\n-- Source: t\nBEGIN;\n"
        'INSERT INTO "sales"."orders" ("id", "amount", "note") VALUES\n'
        "  (1, 1.10, 'a''b'),\n  (2, NULL, E'x\\\\y');\n"
        "COMMIT;\n")
    assert s.rows == 2 and s.statements == 1


def test_mssql_and_oracle_golden_scripts():
    m = build_script(["id", "name"], [[1, "ö"]], table="dbo.t", dialect="mssql")
    assert m.sql == "BEGIN TRANSACTION;\nINSERT INTO [dbo].[t] ([id], [name]) VALUES\n  (1, N'ö');\nCOMMIT TRANSACTION;\n"
    o = build_script(["id", "name"], [[1, "a"], [2, "b"]], table="t", dialect="oracle")
    assert o.sql == ('INSERT INTO "t" ("id", "name") VALUES\n  (1, \'a\');\nINSERT INTO "t" ("id", "name") VALUES\n  (2, \'b\');\nCOMMIT;\n')
    assert o.statements == 2


def test_batches_and_no_transaction_option():
    s = build_script(["n"], [[i] for i in range(1200)], table="t", transaction=False)
    assert s.statements == 3 and not s.sql.startswith("BEGIN") and "COMMIT" not in s.sql
    assert s.sql.count("(") - s.sql.count('("n")') == 1200


def test_oracle_empty_string_becomes_null_is_warned():
    assert any("empty string" in w for w in build_script(["a"], [[""]], table="t", dialect="oracle").warnings)
    assert not build_script(["a"], [[""]], table="t", dialect="postgres").warnings


def test_structural_errors():
    for kwargs in [dict(columns=[], rows=[], table="t"), dict(columns=["a", "a"], rows=[[1, 2]], table="t"),
                   dict(columns=["a", "b"], rows=[[1]], table="t"), dict(columns=["a"], rows=[[1]], table="t", dialect="mysql")]:
        with pytest.raises(ScriptError):
            build_script(**kwargs)


# ------------------------------------------------------------------------------------------------------ the tool

@pytest.fixture()
def audit_db(tmp_path, monkeypatch):
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "audit.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)


class FakeVault:
    class SecretNotFound(KeyError):
        pass

    def __init__(self, env=None):
        self.data = {"host": "h", "port": 5432, "database": "d", "username": "svc", "password": "Canary-pw-1234", "db_type": "postgres",
                     **({"environment": env} if env else {})}

    def list_secrets(self, kind):
        return [{"id": "1", "name": "src", "kind": kind}] if kind == "postgres_connection" else []

    def get_secret(self, _):
        return dict(self.data)


def _tool(monkeypatch, rows, columns=("id", "amount"), more=False, env="non-prod"):
    from mcp_server import access, pg_readonly

    seen = {}
    monkeypatch.setattr(access, "vault", lambda: FakeVault(env))

    def source(data, sql, *, max_rows, seconds):
        seen.update(sql=sql, max_rows=max_rows)
        return {"columns": [{"name": c, "type": "x"} for c in columns], "rows": [list(r) for r in rows], "more": more}

    monkeypatch.setattr(pg_readonly, "run_select", source)
    return seen


def test_tool_returns_text_only_and_says_so(audit_db, monkeypatch):
    seen = _tool(monkeypatch, [[1, D("1.10")], [2, D("2.20")]])
    env = protocol.call_tool("generate_insert_script", {"query": "SELECT id, amount FROM o", "connection": "src", "target_table": "copy_of_o"})
    assert env["ok"], env
    d = env["data"]
    assert d["executed"] is False and d["rows"] == 2 and d["dialect"] == "postgres"
    assert 'INSERT INTO "copy_of_o" ("id", "amount") VALUES' in d["script"] and "(2, 2.20)" in d["script"]
    assert "NOT EXECUTED" in d["script"] and "environment: non-prod" in d["script"]
    assert seen["sql"] == "SELECT id, amount FROM o"                     # only the source was ever queried
    assert "Canary-pw-1234" not in json.dumps(env) and "svc" not in json.dumps(env)


def test_only_the_source_is_ever_connected_to(audit_db, monkeypatch):
    """No code path in the tool can open a second connection: the only DB entry point is pg_readonly.run_select, called once."""
    from mcp_server import pg_readonly

    calls = []
    _tool(monkeypatch, [[1, D("1")]])
    real = pg_readonly.run_select
    monkeypatch.setattr(pg_readonly, "run_select", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    protocol.call_tool("generate_insert_script", {"query": "SELECT 1", "connection": "src", "target_table": "t"})
    assert calls == ["SELECT 1"]
    import mcp_server.tools as tools_mod
    src = Path(tools_mod.__file__).read_text()
    assert "psycopg" not in src and "duckdb" not in src                  # the tools module itself holds no driver


def test_prod_and_unknown_sources_are_flagged_and_capped(audit_db, monkeypatch):
    seen = _tool(monkeypatch, [[1, D("1")]], env="prod")
    env = protocol.call_tool("generate_insert_script", {"query": "SELECT 1", "connection": "src", "target_table": "t"})
    assert seen["max_rows"] == 500 and "WARNING: the source is PROD" in env["data"]["script"]
    assert env["connections"][0]["environment"] == "prod" and any("PROD" in w for w in env["warnings"])
    seen = _tool(monkeypatch, [[1, D("1")]], env=None)
    env = protocol.call_tool("generate_insert_script", {"query": "SELECT 1", "connection": "src", "target_table": "t"})
    assert seen["max_rows"] == 500 and "no environment label" in env["data"]["script"]
    seen = _tool(monkeypatch, [[1, D("1")]], env="non-prod")
    protocol.call_tool("generate_insert_script", {"query": "SELECT 1", "connection": "src", "target_table": "t"})
    assert seen["max_rows"] == 5000


def test_a_partial_result_never_becomes_a_script(audit_db, monkeypatch):
    _tool(monkeypatch, [[1, D("1")]], more=True)
    env = protocol.call_tool("generate_insert_script", {"query": "SELECT * FROM big", "connection": "src", "target_table": "t"})
    assert env["ok"] is False and "more than" in env["error"] and "script" not in json.dumps(env.get("data") or {})


def test_bad_input_is_refused_with_a_hint(audit_db, monkeypatch):
    _tool(monkeypatch, [[1, D("1")]])
    for args in [{"query": "SELECT 1", "connection": "src"},                                  # no target
                 {"target_table": "t"},                                                          # no source
                 {"query": "SELECT 1", "connection": "src", "target_table": "t; DROP TABLE x"},  # smuggled name
                 {"query": "SELECT 1", "connection": "src", "target_table": "t", "dialect": "mysql"},
                 {"table": "system.t", "connection": "src", "target_table": "t"}]:
        env = protocol.call_tool("generate_insert_script", args)
        assert env["ok"] is False and env.get("error"), args


def test_unrepresentable_values_stop_the_script(audit_db, monkeypatch):
    _tool(monkeypatch, [[1, "bad\x00text"]], columns=("id", "note"))
    env = protocol.call_tool("generate_insert_script", {"query": "SELECT 1", "connection": "src", "target_table": "t"})
    assert env["ok"] is False and "NUL" in env["error"]


def test_oversized_script_is_refused_not_cut(audit_db, monkeypatch):
    monkeypatch.setenv("MCP_MAX_BYTES", "2000")
    _tool(monkeypatch, [[i, D("1.5")] for i in range(500)])
    env = protocol.call_tool("generate_insert_script", {"query": "SELECT 1", "connection": "src", "target_table": "t"})
    assert env["ok"] is False and "over the" in env["error"]

"""
Roadmap K2 — the MCP server (docs/architecture/ADR-MCP.md). The rules these tests defend:

  * a credential never appears in ANY response, audit row or log (canary secret test),
  * only a single SELECT ever runs; everything else is refused before it touches a database,
  * prod and unlabelled ("unknown") connections are labelled and get tighter limits,
  * numbers survive exactly, limits are announced (`truncated`), never silent,
  * every call is audited first; if the audit log is down nothing runs,
  * the MCP identity can read connections but has no write scope at all.

Runs on the host (no DuckDB / Postgres needed) except the class marked `needs_duckdb`, which runs in the worker image:
    docker compose run --rm -T --no-deps worker python -m pytest tests/unit/test_mcp_server.py -q
"""

from __future__ import annotations

import decimal
import json
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from mcp_server import access, audit, protocol, safety  # noqa: E402
from mcp_server.safety import Limits, ToolError, finish, jsonable, clip_rows  # noqa: E402

CANARY_PW = "Canary-pw-9f3c1d7a"
CANARY_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHIAAAAGYmNyeXB0\n-----END OPENSSH PRIVATE KEY-----"
CANARY_SSH_PW = "ssh-Canary-7721"


class FakeVault:
    """Stands in for ScopedVault: three connections (prod, non-prod, unlabelled) with secrets in them."""

    class SecretNotFound(KeyError):
        pass

    def __init__(self):
        base = {"host": "db.internal", "port": 5432, "database": "shop", "username": "svc_reader", "password": CANARY_PW,
                "db_type": "postgres",
                "ssh_tunnel": {"ssh_host": "jump", "ssh_username": "me", "ssh_password": CANARY_SSH_PW, "ssh_private_key": CANARY_KEY}}
        self.items = {"id-prod": ("prod-replica", {**base, "environment": "prod"}),
                      "id-dev": ("dev-db", {**base, "environment": "non-prod", "host": "dev.internal"}),
                      "id-unk": ("legacy-db", dict(base))}

    def list_secrets(self, kind):
        if kind == "postgres_connection":
            return [{"id": i, "name": n, "kind": kind} for i, (n, _) in self.items.items()]
        return [{"id": "s3-1", "name": "my-bucket", "kind": kind}] if kind == "s3_location" else []

    def get_secret(self, secret_id):
        return json.loads(json.dumps(self.items[secret_id][1]))


@pytest.fixture()
def vault(monkeypatch):
    fake = FakeVault()
    monkeypatch.setattr(access, "vault", lambda: fake)
    safety.REDACTOR._secrets.clear()
    yield fake
    safety.REDACTOR._secrets.clear()


@pytest.fixture(autouse=True)
def _never_touch_the_real_audit_db(tmp_path, monkeypatch):
    """Tests that call the protocol without asking for audit_db used to create data/mcp_server/ inside the repo. Every test gets its own."""
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "auto_audit.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)


@pytest.fixture()
def audit_db(tmp_path, monkeypatch):
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "audit.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    return store


# ------------------------------------------------------------------------------------------------------------ safety

def test_environment_label_matches_the_vault_helper():
    from core import vault as v

    for data in [{}, {"environment": "prod"}, {"environment": "Non-Prod"}, {"environment": "staging"}, {"environment": None}]:
        assert safety.environment_of(data) == v.environment_of(data)
    assert safety.environment_of({}) == "unknown" and safety.is_protected("unknown") and safety.is_protected("prod")
    assert not safety.is_protected("non-prod")


def test_limits_are_tighter_for_prod_and_unknown():
    dev, prod, unk = (Limits.for_environment(e) for e in ("non-prod", "prod", "unknown"))
    assert dev.rows == 200 and dev.max_rows == 5000 and dev.seconds == 30 and dev.bytes == 1_000_000
    assert prod == unk and prod.rows == 100 and prod.max_rows == 500 and prod.seconds == 15
    assert prod.compare_rows < dev.compare_rows


def test_redactor_removes_secret_values_and_secret_keys():
    r = safety.Redactor()
    r.learn({"host": "h", "password": CANARY_PW, "ssh_tunnel": {"ssh_private_key": CANARY_KEY}})
    out = r.any({"error": f"could not connect with {CANARY_PW} to h", "password": "whatever", "nested": [{"api_key": "x1"}],
                 "echo": "line: b3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHIAAAAGYmNyeXB0"})
    blob = json.dumps(out)
    assert CANARY_PW not in blob and "b3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHIAAAAGYmNyeXB0" not in blob
    assert out["password"] == safety.REDACTED and out["nested"][0]["api_key"] == safety.REDACTED
    assert "h" == "h"  # non-secret strings are left alone


def test_redactor_backstop_scrubs_conninfo_and_urls_it_never_saw():
    r = safety.Redactor()
    t = r.text("connection to \"host=db user=u password='my pass' dbname=x\" failed; also postgresql://bob:hunter22@db:5432/x")
    assert "my pass" not in t and "hunter22" not in t


def test_short_secret_only_replaced_as_a_whole_word():
    r = safety.Redactor()
    r.learn({"password": "abc"})
    assert r.text("abc and abcdef") == f"{safety.REDACTED} and abcdef"


def test_secret_looking_keys_do_not_catch_innocent_ones():
    r = safety.Redactor()
    out = r.any({"passed": True, "bypass": "x", "compass": "y", "max_rows": 5, "token": "t0k", "hint": "ok"})
    assert out["passed"] is True and out["bypass"] == "x" and out["compass"] == "y" and out["max_rows"] == 5
    assert out["token"] == safety.REDACTED


def test_values_keep_their_exact_form():
    assert jsonable(decimal.Decimal("12345678901234567890.123456789")) == "12345678901234567890.123456789"
    assert jsonable(2**60) == str(2**60) and jsonable(41) == 41
    assert jsonable(float("nan")) == "nan"
    assert jsonable(uuid.UUID(int=1)) == "00000000-0000-0000-0000-000000000001"
    assert jsonable(b"\x00\x01\x02") .startswith("<3 bytes") and "\x00" not in jsonable(b"\x00\x01\x02")
    import datetime as dt
    assert jsonable(dt.datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05"


def test_row_and_byte_caps_say_so():
    rows, trunc, why = clip_rows(["a"], [[i] for i in range(10)], max_rows=3, max_bytes=10_000)
    assert len(rows) == 3 and trunc and "row limit" in why
    big = [["x" * 1000] for _ in range(50)]
    rows, trunc, why = clip_rows(["a"], big, max_rows=100, max_bytes=5000)
    assert 0 < len(rows) < 50 and trunc and "size limit" in why
    rows, trunc, why = clip_rows(["a"], [[1]], max_rows=10, max_bytes=5000)
    assert not trunc and why is None


def test_envelope_labels_prod_and_unknown():
    env = finish(ok=True, data={"x": 1}, connections=[{"name": "p", "environment": "prod"}, {"name": "u", "environment": "unknown"},
                                                      {"name": "d", "environment": "non-prod"}])
    assert [c["environment"] for c in env["connections"]] == ["prod", "unknown", "non-prod"]
    w = " ".join(env["warnings"])
    assert "p: PROD" in w and "u: environment NOT SET" in w and "d:" not in w


# ------------------------------------------------------------------------------------------------------------ scope

def test_mcp_identity_can_read_connections_but_write_nothing():
    from core import vault as v

    scope = v.scope_for("mcp-server")
    # secrets: never writable. Vault Data: write since K6, used ONLY by frame.write_result behind grant + confirm code
    # (tests/unit/test_mcp_frame.py::test_the_vault_data_write_functions_are_reachable_from_one_place_only)
    assert scope.write == frozenset() and scope.datasets == "read" and scope.data == "write"
    assert {"postgres_connection", "s3_location"} <= scope.read
    with pytest.raises(v.ScopeError):
        v.scoped("mcp-server").save_secret("x", "postgres_connection", {})


def test_a_broken_scope_file_never_widens_access(tmp_path):
    from core import vault as v

    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "vault_scope.yaml").write_text("name: mcp-server\nvault: {read: [not valid yaml")
    assert v._scope_from_file(tmp_path, "mcp-server") is None


# ------------------------------------------------------------------------------------------------------------ connections

def test_connection_listing_shows_only_allow_listed_fields(vault):
    conns, warn = access.list_connections()
    assert {c["name"]: c["environment"] for c in conns} == {"prod-replica": "prod", "dev-db": "non-prod", "legacy-db": "unknown"}
    blob = json.dumps(conns)
    for forbidden in (CANARY_PW, CANARY_SSH_PW, "svc_reader", "b3BlbnNz", "ssh_password", "username"):
        assert forbidden not in blob
    assert all(set(c) == {"name", "id", "db_type", "host", "port", "database", "via_ssh_tunnel", "environment"} for c in conns)


def test_unknown_connection_name_lists_names_only(vault):
    with pytest.raises(ToolError) as e:
        access.resolve_connection("nope")
    assert "prod-replica" in e.value.hint and CANARY_PW not in e.value.hint


# ------------------------------------------------------------------------------------------------------------ protocol

def rpc(method, params=None, mid=1):
    return protocol.handle({"jsonrpc": "2.0", "id": mid, "method": method, **({"params": params} if params is not None else {})})


def test_initialize_negotiates_and_describes_itself():
    r = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "claude", "version": "1"}})
    assert r["result"]["protocolVersion"] == "2025-06-18" and "tools" in r["result"]["capabilities"]
    assert "read-only" in r["result"]["instructions"].lower()
    r = rpc("initialize", {"protocolVersion": "1999-01-01"})
    assert r["result"]["protocolVersion"] == protocol.SUPPORTED_VERSIONS[0]


def test_every_tool_is_listed_as_read_only_with_a_manual():
    tools = rpc("tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == ["toolbox_guide", "find_actions", "describe_action", "run_action", "vault_list", "vault_dataset_preview", "run_query", "compare",
                                          "access_status", "ssh_servers", "ssh_run", "transform_steps", "table_transform", "stage_query", "load_table", "keep_recipe", "generate_insert_script"]
    for t in tools:
        # every tool is read-only EXCEPT table_transform (saves a NEW table, only with an owner grant + confirm code) and run_action (it can run
        # table_transform through the registry, with the very same guards) — both say so
        assert t["annotations"]["readOnlyHint"] is (t["name"] not in ("table_transform", "run_action", "stage_query", "load_table", "keep_recipe")), t["name"]
        assert t["annotations"]["destructiveHint"] is False
        assert len(t["description"]) > 80 and t["inputSchema"]["type"] == "object"
        assert "Example" in t["description"] or t["name"] == "toolbox_guide"


def test_no_tool_can_write_or_grant():
    # generate_insert_script is the one name that sounds like a write: it only returns text (tests/unit/test_mcp_scriptgen.py)
    names = " ".join(t["name"] for t in rpc("tools/list")["result"]["tools"] if t["name"] != "generate_insert_script").lower()
    # (ssh_servers / ssh_run are read-only diagnostics, gated by an owner grant — tests/unit/test_mcp_ssh.py)
    names = names.replace("ssh_servers", "").replace("ssh_run", "").replace("table_transform", "").replace("transform_steps", "")
    names = names.replace("stage_query", "").replace("load_table", "").replace("keep_recipe", "")      # H5: gated writes (grant + card + dry-run + confirm code) and a text-only store
    names = names.replace("find_actions", "").replace("describe_action", "").replace("run_action", "")     # the registry verbs (roadmap H3)
    for bad in ("write", "save", "delete", "drop", "grant", "execute", "insert", "update", "ssh", "password", "secret"):
        assert bad not in names


def test_notifications_get_no_answer_and_unknown_methods_error():
    assert protocol.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc("resources/list")["error"]["code"] == -32601
    assert rpc("ping")["result"] == {}


def test_serve_loop_handles_batches_garbage_and_keeps_stdout_clean(tmp_path):
    import io

    inp = io.StringIO("not json\n" + json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                                  {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]) + "\n\n"
                      + json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}) + "\n")
    out = io.StringIO()
    protocol.serve(inp, out)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == -32700
    assert [r["id"] for r in lines[1]] == [1, 2] and lines[2]["id"] == 3


# ------------------------------------------------------------------------------------------------------------ audit + dispatch

def test_unknown_tool_and_bad_arguments_are_refused_cleanly():
    e = protocol.call_tool("format_disk", {})
    assert e["ok"] is False and e["refused"] is True
    assert protocol.call_tool("vault_list", "not an object")["ok"] is False


def test_every_call_is_audited_before_and_after(vault, audit_db, monkeypatch):
    from mcp_server import tools

    monkeypatch.setitem(tools.REGISTRY, "vault_list", tools.Tool(
        "vault_list", "t", "d", {"type": "object"}, lambda a: tools.Result({"hello": 1}, rows=7)))
    env = protocol.call_tool("vault_list", {"what": "tables", "password": CANARY_PW})
    assert env["ok"] is True
    rows = audit.recent(5)
    assert len(rows) == 1 and rows[0]["outcome"] == "ok" and rows[0]["rows"] == 7 and rows[0]["duration_ms"] is not None
    assert CANARY_PW not in json.dumps(rows) and rows[0]["session"] == audit.SESSION_ID


def test_if_the_audit_log_is_down_nothing_runs(vault, monkeypatch):
    from mcp_server import tools

    ran = []
    monkeypatch.setitem(tools.REGISTRY, "vault_list", tools.Tool("vault_list", "t", "d", {"type": "object"},
                                                                 lambda a: ran.append(1) or tools.Result({})))
    def boom(*a, **k):
        raise audit.AuditUnavailable("the audit log is not available, so nothing was run")
    monkeypatch.setattr(audit, "begin", boom)
    env = protocol.call_tool("vault_list", {})
    assert env["ok"] is False and env["refused"] is True and not ran


def test_unexpected_errors_do_not_leak_tracebacks_or_secrets(vault, audit_db, monkeypatch, capsys):
    from mcp_server import tools

    def explode(a):
        access.list_connections()  # learns the canaries
        raise RuntimeError(f"driver said: bad password {CANARY_PW} for svc_reader")

    monkeypatch.setitem(tools.REGISTRY, "run_query", tools.Tool("run_query", "t", "d", {"type": "object"}, explode))
    env = protocol.call_tool("run_query", {"sql": "select 1"})
    assert env["ok"] is False and "Traceback" not in json.dumps(env) and CANARY_PW not in json.dumps(env)
    assert CANARY_PW not in capsys.readouterr().err                      # the server log is scrubbed too
    assert CANARY_PW not in json.dumps(audit.recent(5))


# ------------------------------------------------------------------------------------------------------------ the canary test

def test_canary_credentials_never_reach_the_ai(vault, audit_db, monkeypatch):
    """Every tool, good and bad input, with a driver that echoes the password in its errors: the secrets appear NOWHERE."""
    from mcp_server import pg_readonly, tools

    def echoing_driver(data, sql, *, max_rows, seconds):
        if "boom" in sql:
            raise ToolError(f"FATAL: password authentication failed for user svc_reader (password={data['password']}) "
                            f"{data['ssh_tunnel']['ssh_private_key']}")
        return {"columns": [{"name": "n", "type": "int4"}], "rows": [[1], [2], [3]], "more": False}

    monkeypatch.setattr(pg_readonly, "run_select", echoing_driver)
    calls = [("toolbox_guide", {}), ("vault_list", {"what": "connections"}), ("vault_list", {}),
             ("run_query", {"sql": "select 1", "connection": "prod-replica"}),
             ("run_query", {"sql": "boom", "connection": "dev-db"}),
             ("run_query", {"sql": "boom", "connection": "legacy-db"}),
             ("run_query", {"sql": "select 1", "connection": "does-not-exist"}),
             ("compare", {"left": {"query": "select 1", "connection": "prod-replica"}, "right": {"query": "boom", "connection": "dev-db"}})]
    # the Vault Data side needs the lake/DuckDB; the guide and list tools tolerate it being unavailable on a bare host
    seen = []
    for name, args in calls:
        env = protocol.call_tool(name, args)
        seen.append(json.dumps(env))
    everything = "\n".join(seen) + json.dumps(audit.recent(100))
    for secret in (CANARY_PW, CANARY_SSH_PW, "svc_reader", "b3BlbnNzaC1rZXktdjEAAAAACmFlczI1Ni1jdHIAAAAGYmNyeXB0",
                   "BEGIN OPENSSH PRIVATE KEY"):
        assert secret not in everything, f"{secret!r} leaked"
    assert "[redacted]" in everything                                        # the echo was scrubbed, not dropped
    assert '"environment": "prod"' in seen[3] and '"environment": "unknown"' in seen[5]


def test_prod_connection_gets_the_tighter_row_cap(vault, audit_db, monkeypatch):
    from mcp_server import pg_readonly

    got = {}

    def spy(data, sql, *, max_rows, seconds):
        got[data["host"] + str(len(got))] = (max_rows, seconds)
        return {"columns": [{"name": "n", "type": "int4"}], "rows": [[1]], "more": False}

    monkeypatch.setattr(pg_readonly, "run_select", spy)
    protocol.call_tool("run_query", {"sql": "select 1", "connection": "prod-replica", "max_rows": 100000})
    protocol.call_tool("run_query", {"sql": "select 1", "connection": "dev-db", "max_rows": 100000})
    protocol.call_tool("run_query", {"sql": "select 1", "connection": "legacy-db"})
    assert list(got.values()) == [(500, 15), (5000, 30), (100, 15)]


# ------------------------------------------------------------------------------------------------------------ SQL guards

def _guard():
    try:
        from mcp_server import pg_readonly
        pg_readonly.guard_module()
        from core.db.registry import get_dialect
        get_dialect("postgres")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"SQL guard needs the DB libraries: {exc}")
    return pg_readonly


@pytest.mark.parametrize("sql", ["SELECT 1", "select * from t where a = 'x;y'", "WITH c AS (SELECT 1) SELECT * FROM c",
                                 "VALUES (1),(2)", "TABLE t", "-- note\nSELECT 1;"])
def test_postgres_guard_allows_reads(sql):
    assert _guard().check_select(sql)


@pytest.mark.parametrize("sql", ["DROP TABLE t", "DELETE FROM t", "UPDATE t SET a=1", "INSERT INTO t VALUES (1)", "TRUNCATE t",
                                 "ALTER TABLE t ADD c int", "COPY t TO '/tmp/x'", "CREATE TABLE x AS SELECT 1", "GRANT ALL ON t TO u",
                                 "SELECT 1; DROP TABLE t", "SET ROLE postgres", "CALL p()", "DO $$ BEGIN END $$", "EXPLAIN ANALYZE DELETE FROM t",
                                 "VACUUM", ""])
def test_postgres_guard_refuses_everything_else(sql):
    with pytest.raises(ToolError):
        _guard().check_select(sql)


def test_non_postgres_connections_are_declined_honestly():
    pg = _guard()
    with pytest.raises(ToolError) as e:
        pg.run_select({"db_type": "oracle", "host": "h", "database": "d", "username": "u", "password": "p"}, "select 1", max_rows=5, seconds=5)
    assert "PostgreSQL" in str(e.value)


# ------------------------------------------------------------------------------------------------------------ Vault Data (needs DuckDB)

@pytest.fixture()
def lake_table(tmp_path):
    """A real Vault Data table `mcptest<id>.orders` (cleaned up afterwards). Skips where DuckDB is not installed."""
    duckdb = pytest.importorskip("duckdb", reason="Vault Data queries need DuckDB (run in the worker image)")
    from core import lake

    ws = "mcptest" + uuid.uuid4().hex[:6]
    p = tmp_path / "orders.parquet"
    con = duckdb.connect(":memory:")
    con.execute(f"COPY (SELECT i AS id, CAST(i * 1.10 AS DECIMAL(12,2)) AS amount, 'o' || i AS label FROM range(1, 301) t(i)) TO '{p}' (FORMAT PARQUET)")
    con.close()
    lake.create_workspace(ws)
    lake.write_table(ws, "orders", [p], mode="create")
    yield ws
    try:
        lake.delete_workspace(ws, drop_tables=True)
    except Exception:  # noqa: BLE001
        pass


def test_run_query_reads_vault_data_exactly(lake_table, audit_db):
    env = protocol.call_tool("run_query", {"sql": f"SELECT id, amount FROM {lake_table}.orders WHERE id IN (1, 7) ORDER BY id"})
    assert env["ok"], env
    assert env["data"]["rows"] == [[1, "1.10"], [7, "7.70"]]          # decimals stay exact text
    assert env["data"]["columns"][1]["type"].startswith("DECIMAL(12,2)") and env["truncated"] is False
    assert f"{lake_table}.orders" in env["data"]["tables_used"]


def test_run_query_announces_truncation(lake_table, audit_db):
    env = protocol.call_tool("run_query", {"sql": f"SELECT * FROM {lake_table}.orders ORDER BY id", "max_rows": 50})
    assert env["ok"] and env["data"]["returned"] == 50 and env["truncated"] is True and "row limit 50" in env["limits_hit"]
    env = protocol.call_tool("run_query", {"sql": f"SELECT * FROM {lake_table}.orders"})
    assert env["data"]["returned"] == 200 and env["truncated"] is True            # default cap, 300 rows exist


@pytest.mark.parametrize("sql", ["DROP TABLE {ws}.orders", "DELETE FROM {ws}.orders", "INSERT INTO {ws}.orders VALUES (1,1,'x')",
                                 "UPDATE {ws}.orders SET id = 0", "CREATE TABLE {ws}.copy AS SELECT * FROM {ws}.orders",
                                 "CREATE OR REPLACE TABLE {ws}.orders AS SELECT 1", "COPY {ws}.orders TO '/tmp/x.csv'",
                                 "SELECT * FROM read_csv('/etc/passwd')", "SELECT * FROM '/etc/passwd'",
                                 "SELECT * FROM read_text('/proc/self/environ')", "ATTACH '/tmp/x.db'", "INSTALL httpfs",
                                 "SELECT 1; SELECT 2", "PRAGMA database_list", "SELECT * FROM glob('/*')"])
def test_run_query_refuses_everything_but_one_select(lake_table, audit_db, sql):
    env = protocol.call_tool("run_query", {"sql": sql.format(ws=lake_table)})
    assert env["ok"] is False and env["refused"] is True, env
    # and the table is still intact
    again = protocol.call_tool("run_query", {"sql": f"SELECT count(*) FROM {lake_table}.orders"})
    assert again["data"]["rows"] == [[300]]


def test_run_query_stops_slow_queries(lake_table, audit_db, monkeypatch):
    monkeypatch.setenv("MCP_SECONDS", "1")
    env = protocol.call_tool("run_query", {"sql": "SELECT count(*) FROM range(100000000000) a, range(1000) b"})
    assert env["ok"] is False and "longer than 1 s" in env["error"]


def test_preview_and_list_show_the_table(lake_table, audit_db):
    env = protocol.call_tool("vault_dataset_preview", {"table": f"{lake_table}.orders", "rows": 3})
    assert env["ok"] and env["data"]["total_rows"] == 300 and len(env["data"]["rows"]) == 3
    assert [c["name"] for c in env["data"]["columns"]] == ["id", "amount", "label"]
    lst = protocol.call_tool("vault_list", {"what": "tables", "workspace": lake_table})
    assert lst["ok"] and lst["data"]["workspaces"][0]["tables"][0]["table"] == f"{lake_table}.orders"
    assert protocol.call_tool("vault_dataset_preview", {"table": f"{lake_table}.missing"})["ok"] is False


def test_compare_two_vault_tables(lake_table, audit_db):
    pytest.importorskip("core.clients.datadiff")
    left = {"query": f"SELECT id, amount FROM {lake_table}.orders WHERE id <= 5 ORDER BY id"}
    right = {"query": f"SELECT id, CASE WHEN id = 3 THEN amount + 1 ELSE amount END AS amount FROM {lake_table}.orders WHERE id <= 5 ORDER BY id"}
    env = protocol.call_tool("compare", {"left": left, "right": right})
    assert env["ok"], env
    assert env["data"]["left"]["rows"] == 5 and env["data"]["right"]["rows"] == 5
    assert env["data"]["differences_total"] == 1 and env["data"]["records_compared"] > 1
    assert all(d["status"] != "MATCH" for d in env["data"]["differences"])
    assert "3" in env["data"]["differences"][0]["path"]
    assert env["data"]["summary"]["MISMATCH"] == 1


def test_compare_refuses_to_compare_only_part_of_the_data(lake_table, audit_db, monkeypatch):
    monkeypatch.setenv("MCP_COMPARE_MAX_ROWS", "100")
    env = protocol.call_tool("compare", {"left": {"table": f"{lake_table}.orders"}, "right": {"table": f"{lake_table}.orders"}})
    assert env["ok"] is False and "more than 100 rows" in env["error"]

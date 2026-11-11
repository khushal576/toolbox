"""
Roadmap H3 — find_actions / describe_action / run_action (mcp_server/registry.py, ADR-AI-HELPER D6).

Defended: the AI SEARCHES instead of being shown everything (what a question costs does not grow with the number of tools);
a manifest action runs only as the read-only GET its manifest declared, against that tool only; the existing MCP tools run through
the registry with exactly the guards they always had; the kill switch and the audit log still wrap every call.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from mcp_server import access, audit, control, protocol, registry, tools  # noqa: E402
from mcp_server.safety import ToolError  # noqa: E402

PIN = "owner-1234"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    from core.state.sqlstore import SqlStore

    store = SqlStore("mcp_server", sqlite_path=tmp_path / "audit.db", ddl=audit._SCHEMA, add_columns=audit.ADD_COLUMNS, backend="sqlite")
    monkeypatch.setattr(audit, "STORE", store)
    monkeypatch.setattr(audit, "_ready", False)
    monkeypatch.delenv("TOOLBOX_GATEWAY_URL", raising=False)
    registry.invalidate()
    yield
    registry.invalidate()


def fake_repo(root: Path, n_tools: int, actions_per_tool: int = 3) -> Path:
    for i in range(n_tools):
        d = root / f"tool-{i:04d}"
        d.mkdir()
        acts = [{"name": f"act_{j}", "summary": f"Does job {j} number {i} on widgets, gadgets and thingamajigs",
                 "path": f"jobs/{j}", "inputs": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "returns": "a list of widgets"}
                for j in range(actions_per_tool)]
        (d / "manifest.yaml").write_text(yaml.safe_dump({"name": f"tool-{i:04d}", "title": f"Tool number {i}", "description": f"Tool {i} handles widgets.",
                                                         "kind": "python", "entry": f"tool_{i:04d}.server:app", "runtime": "light", "ai": {"actions": acts}}))
    return root


class Http:
    """Replaces registry.http_get and records what would have been sent."""

    def __init__(self, status=200, ctype="application/json", body=b'{"ok": true}', exc=None):
        self.calls, self.status, self.ctype, self.body, self.exc = [], status, ctype, body, exc

    def __call__(self, url, params, timeout, max_bytes):
        self.calls.append((url, dict(params), timeout, max_bytes))
        if self.exc:
            raise self.exc
        return self.status, self.ctype, self.body


@pytest.fixture()
def http(monkeypatch):
    h = Http(body=json.dumps({"functions": [{"name": "abs", "help": "abs(x)"}]}).encode())
    monkeypatch.setattr(registry, "http_get", h)
    return h


# ------------------------------------------------------------------------------------------------------------ what is in the registry

def test_every_existing_mcp_tool_is_an_action_and_the_verbs_are_not():
    ids = {a.id for a in registry.load()}
    for name in tools.REGISTRY:
        assert (f"mcp.{name}" in ids) is (name not in registry.VERBS), name
    assert {"df-studio.formula_help", "df-studio.list_templates", "data-lake.list_column_maps"} <= ids


def test_effects_are_honest():
    by = {a.id: a for a in registry.load()}
    assert by["df-studio.formula_help"].effect == "read" and by["mcp.run_query"].effect == "read"
    assert by["mcp.table_transform"].effect.startswith("write")                                  # the one tool that can save is labelled
    assert all(a.effect == "read" for a in by.values() if a.source == "manifest")


# ------------------------------------------------------------------------------------------------------------ find_actions

def test_find_ranks_the_obvious_match_first():
    top = lambda q: [m["id"] for m in registry.find(q, limit=3)["matches"]]  # noqa: E731
    assert top("formula functions")[0] == "df-studio.formula_help"
    assert top("saved cleaning templates")[0] == "df-studio.list_templates"
    assert top("column map")[0] == "data-lake.list_column_maps"
    assert top("compare two tables")[0] == "mcp.compare"
    assert top("run read only commands on a server")[0] == "mcp.ssh_run"
    assert top("mcp.compare")[0] == "mcp.compare" and top("compare")[0] == "mcp.compare"       # an exact name wins outright


def test_find_is_deterministic_bounded_and_filterable():
    a, b = registry.find("table"), registry.find("table")
    assert a == b
    assert len(registry.find("table", limit=2)["matches"]) == 2 and len(registry.find("table", limit=999)["matches"]) <= registry.MAX_LIMIT
    only = registry.find("formula templates", tool="df-studio")["matches"]
    assert only and all(m["tool"] == "df-studio" for m in only)
    r = registry.find("table")
    assert set(r["matches"][0]) == {"id", "tool", "summary", "effect", "inputs"} and r["searched"]["actions"] >= 12 and "describe_action" in r["next"]


def test_find_says_so_when_nothing_matches_or_nothing_was_asked():
    r = registry.find("zzzqqqxxx")
    assert r["matches"] == [] and "Nothing matched" in r["hint"]
    for q in ("", "   ", "the of a", None):
        with pytest.raises(ToolError):
            registry.find(q or "")


def test_required_inputs_are_marked_in_matches():
    m = next(x for x in registry.find("compare two tables")["matches"] if x["id"] == "mcp.compare")
    assert "left*" in m["inputs"] and "right*" in m["inputs"]


# ------------------------------------------------------------------------------------------------------------ describe_action

def test_describe_a_manifest_action_and_an_mcp_action():
    d = registry.describe("df-studio.formula_help")
    assert d["effect"] == "read" and d["how_it_runs"].startswith("GET /tools/df-studio/formula/help") and d["input_schema"]["additionalProperties"] is False
    assert d["example"] == {"tool": "run_action", "arguments": {"id": "df-studio.formula_help", "inputs": {}}}
    c = registry.describe("mcp.compare")
    assert "same checks" in c["how_it_runs"] and c["input_schema"]["required"] == ["left", "right"] and c["example"]["arguments"]["inputs"].keys() == {"left", "right"}
    assert "full_description" in c


def test_describe_an_unknown_action_suggests_close_ones():
    with pytest.raises(ToolError) as e:
        registry.describe("df-studio.formula_hlp")
    assert "df-studio.formula_help" in e.value.hint
    with pytest.raises(ToolError):
        registry.describe("")


# ------------------------------------------------------------------------------------------------------------ run_action: manifest actions

def run(id_, inputs=None):
    return protocol.call_tool("run_action", {"id": id_, **({} if inputs is None else {"inputs": inputs})})


def test_a_manifest_action_is_one_read_only_get_through_the_gateway(http):
    r = run("df-studio.formula_help")
    assert r["ok"] and r["data"]["status"] == 200 and r["data"]["result"]["functions"][0]["name"] == "abs" and r["data"]["action"] == "df-studio.formula_help"
    (url, params, timeout, cap), = http.calls
    assert url == "http://toolbox:8080/tools/df-studio/formula/help" and params == {} and timeout == 20 and cap == 1_000_000


def test_the_gateway_address_comes_from_the_environment_and_must_be_plain(http, monkeypatch):
    monkeypatch.setenv("TOOLBOX_GATEWAY_URL", "http://localhost:8000/")
    run("df-studio.formula_help")
    assert http.calls[-1][0] == "http://localhost:8000/tools/df-studio/formula/help"
    for bad in ("ftp://x", "http://user:pw@host:1", "toolbox:8080", "javascript:alert(1)"):
        monkeypatch.setenv("TOOLBOX_GATEWAY_URL", bad)
        n = len(http.calls)
        r = run("df-studio.formula_help")
        assert r["ok"] is False and len(http.calls) == n                                         # nothing is sent to a strange address


def test_bad_inputs_never_reach_the_network(http):
    r = run("df-studio.formula_help", {"anything": 1})
    assert r["ok"] is False and "unknown input" in r["error"] and http.calls == []
    assert run("df-studio.formula_help", "not an object")["ok"] is False and http.calls == []


def test_a_switched_off_tool_says_so_in_plain_words(http):
    http.status, http.ctype, http.body = 404, "text/html; charset=utf-8", b"<!doctype html><title>Mini Sheet is off</title>"
    r = run("df-studio.formula_help")
    assert r["ok"] is False and "switched off" in r["error"] and "Settings" in r["hint"]


@pytest.mark.parametrize("status,body,expect", [(503, b"x", "starting or unavailable"), (500, b"boom happened", "HTTP 500: boom happened"), (404, b'{"detail":"Not Found"}', "HTTP 404")])
def test_other_answers_are_reported_honestly(http, status, body, expect):
    http.status, http.body = status, body
    r = run("df-studio.formula_help")
    assert r["ok"] is False and expect in r["error"]


def test_odd_responses(http):
    http.body = b"{not json"
    assert "invalid JSON" in run("df-studio.formula_help")["error"]
    http.ctype, http.body = "text/plain", b"hello"
    assert run("df-studio.formula_help")["data"]["result"] == {"text": "hello"}
    http.ctype, http.body = "application/json", b"x" * 1_000_001
    r = run("df-studio.formula_help")
    assert r["ok"] is False and "larger than" in r["error"]
    http.exc = ConnectionError("nope")
    r = run("df-studio.formula_help")
    assert r["ok"] is False and "Could not reach Toolbox" in r["error"] and "docker compose ps" in r["hint"]


def test_secrets_in_a_tools_answer_are_still_redacted(http):
    http.body = json.dumps({"templates": [{"name": "a", "password": "hunter2", "api_key": "abc"}]}).encode()
    blob = json.dumps(run("data-lake.list_column_maps"))
    assert "hunter2" not in blob and "abc" not in blob.replace("api_key", "") and "[redacted]" in blob


def test_an_action_that_vanished_from_its_manifest_is_reported(http, monkeypatch):
    a = registry._get("df-studio.formula_help")
    monkeypatch.setattr(registry, "discover", lambda repo: type("R", (), {"plugins": {}})())
    with pytest.raises(ToolError) as e:
        registry.run_manifest_action(a, {})
    assert "no longer declared" in str(e.value)


def test_the_http_function_never_follows_redirects_or_keeps_cookies(monkeypatch):
    import httpx

    seen = {}

    class Client:
        def __init__(self, **kw):
            seen.update(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, params=None):
            seen.update(method=method, url=url)

            class R:
                status_code, headers = 200, {"content-type": "application/json"}
                def iter_bytes(self_): return iter([b"{}"])
                def __enter__(self_): return self_
                def __exit__(self_, *a): return False
            return R()

    monkeypatch.setattr(httpx, "Client", Client)
    assert registry.http_get("http://toolbox:8080/tools/x/y", {}, 5.0, 100) == (200, "application/json", b"{}")
    assert seen["follow_redirects"] is False and seen["trust_env"] is False and seen["method"] == "GET" and "cookies" not in seen


# ------------------------------------------------------------------------------------------------------------ run_action: mcp actions keep their guards

def test_an_mcp_action_runs_the_same_function_as_calling_the_tool_directly():
    direct = protocol.call_tool("access_status", {})
    via = run("mcp.access_status", {})
    assert via["ok"] and via["data"]["mode"] == direct["data"]["mode"] == "read-only"


def test_a_write_gated_tool_is_still_gated_when_called_through_the_registry(monkeypatch):
    control.set_pin(PIN)
    done = []

    def gated(args):
        control.require("workspace", "scratch", "create_table")        # what table_transform does first
        done.append(1)
        return tools.Result({"saved": True})

    monkeypatch.setitem(tools.REGISTRY, "table_transform", tools.Tool("table_transform", "t", "Saves a table. Example.", {"type": "object"}, gated,
                                                                       annotations={"readOnlyHint": False}))
    registry.invalidate()
    r = run("mcp.table_transform", {})
    assert r["ok"] is False and r["refused"] is True and "cannot grant this yourself" in r["hint"] and not done
    control.create_grant("workspace", "scratch", ["create_table"], minutes=5, pin=PIN, environment="non-prod")
    assert run("mcp.table_transform", {})["ok"] is True and done == [1]
    r = run("mcp.table_transform", "nope")
    assert r["ok"] is False


def test_the_verbs_cannot_call_themselves_and_unknown_ids_are_refused():
    for bad in ("mcp.run_action", "mcp.find_actions", "mcp.describe_action", "nope.nothing", "", "mcp."):
        r = run(bad)
        assert r["ok"] is False and r.get("error"), bad


# ------------------------------------------------------------------------------------------------------------ the wrapper around every call

def test_the_kill_switch_and_the_audit_log_wrap_run_action(http):
    control.set_pin(PIN)
    assert run("df-studio.formula_help")["ok"]
    control.kill()
    r = run("df-studio.formula_help")
    assert r["ok"] is False and "stopped by the owner" in r["error"] and len(http.calls) == 1            # not sent while stopped
    rows = audit.recent(5)
    assert [x["tool"] for x in rows] == ["run_action", "run_action"] and [x["outcome"] for x in rows] == ["refused", "ok"]
    assert "df-studio.formula_help" in rows[1]["args"]


def test_annotations_say_what_each_verb_can_do():
    by = {t["name"]: t for t in protocol._tool_listing()}
    assert by["find_actions"]["annotations"]["readOnlyHint"] is True and by["describe_action"]["annotations"]["readOnlyHint"] is True
    assert by["run_action"]["annotations"]["readOnlyHint"] is False and by["run_action"]["annotations"]["destructiveHint"] is False


# ------------------------------------------------------------------------------------------------------------ removing and scaling

def test_a_removed_tool_disappears_from_the_search(tmp_path):
    repo = fake_repo(tmp_path, 5)
    assert any(m["tool"] == "tool-0003" for m in registry.find("widgets job 3", repo=repo, limit=10)["matches"])
    import shutil

    shutil.rmtree(repo / "tool-0003")
    registry.invalidate()
    assert not any(m["tool"] == "tool-0003" for m in registry.find("widgets job 3", repo=repo, limit=10)["matches"])
    assert registry.find("widgets", repo=repo)["searched"]["tools"] == 5                                   # 4 fake tools + the mcp group


def test_what_a_question_costs_does_not_grow_with_the_number_of_tools(tmp_path):
    sizes = {}
    for n in (5, 50, 300):
        d = tmp_path / f"r{n}"
        d.mkdir()
        repo = fake_repo(d, n)
        registry.invalidate()
        r = registry.find("job 2 widgets", repo=repo)
        sizes[n] = len(json.dumps(r))
        assert len(r["matches"]) == registry.DEFAULT_LIMIT
    assert max(sizes.values()) < 2500, sizes
    assert sizes[300] < sizes[5] * 1.3, sizes                                                              # the answer stays the same size


def test_toolbox_guide_stays_small_with_many_tools(tmp_path, monkeypatch):
    class V:
        def list_secrets(self, kind):
            return []

    monkeypatch.setattr(access, "vault", lambda: V())
    repo = fake_repo(tmp_path, 400)
    monkeypatch.setattr(tools, "REPO", repo)
    out = tools.toolbox_guide({}).data
    assert len(out["web_tools"]) == tools.MAX_LISTED and out["more_web_tools"] == 400 - tools.MAX_LISTED and "find_actions" in out["more_hint"]
    assert all(set(t) == {"name", "title"} for t in out["web_tools"])                                      # names only: no descriptions
    assert len(json.dumps(out)) < 12_000


def test_a_thousand_tools_index_quickly_and_search_stays_tiny(tmp_path):
    repo = fake_repo(tmp_path, 1000)
    t0 = time.monotonic()
    registry.invalidate()
    r = registry.find("job 7 widgets", repo=repo)
    built = time.monotonic() - t0
    mcp_count = len([n for n in tools.REGISTRY if n not in registry.VERBS])
    assert r["searched"] == {"actions": 3000 + mcp_count, "tools": 1001} and len(json.dumps(r)) < 2500 and built < 30
    t1 = time.monotonic()
    for q in ("job 1 widgets", "gadgets number 500", "thingamajigs"):
        registry.find(q, repo=repo)
    assert (time.monotonic() - t1) / 3 < 0.25, "a question over 3,000 actions must stay fast once the index exists"

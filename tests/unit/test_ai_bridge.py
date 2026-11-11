"""AI helper bridge (roadmap H1): engine safety flags, event parsing, failure messages, the HTTP bridge and the gateway pass-through.
A fake `claude` script stands in for the real one, so no Pro usage is spent. Host-runnable (standard library + httpx/fastapi when present)."""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ai-bridge"))
import bridge as bridge_mod  # noqa: E402
import engine as eng  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import json, os, sys, time
log = os.environ["FAKE_LOG"]
argv = sys.argv[1:]
if argv[:2] == ["auth", "status"]:
    mode = open(log + ".auth").read() if os.path.exists(log + ".auth") else "ok"
    print(json.dumps({"loggedIn": mode != "out", "authMethod": "claude.ai" if mode != "api" else "api_key", "subscriptionType": "pro"}))
    sys.exit(0)
msg = sys.stdin.read()
open(log, "a").write(json.dumps({"argv": argv, "env": {k: v for k, v in os.environ.items() if k.startswith(("ANTHROPIC", "CLAUDE", "ENABLE", "AWS"))}, "stdin": msg, "cwd": os.getcwd()}) + "\n")
def out(o): print(json.dumps(o), flush=True)
sid = argv[argv.index("--session-id") + 1] if "--session-id" in argv else argv[argv.index("--resume") + 1]
out({"type": "system", "subtype": "init", "tools": ["mcp__toolbox__find_actions"], "mcp_servers": [{"name": "toolbox", "status": "connected"}], "model": "fake", "session_id": sid})
if "CRASH" in msg:
    sys.stderr.write("boom Not logged in · Please run /login" if "LOGIN" in msg else "segfault"); sys.exit(1)
if "LIMIT" in msg:
    out({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": 1794414600, "rateLimitType": "five_hour"}})
    out({"type": "result", "subtype": "success", "is_error": True, "result": "usage limit reached"}); sys.exit(1)
if "HANG" in msg:
    time.sleep(60)
if "NOSESSION" in msg:
    out({"type": "result", "subtype": "error", "is_error": True, "result": "No conversation found with session ID"}); sys.exit(1)
out({"type": "stream_event", "event": {"type": "message_start"}})
out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}}})
out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}}})
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}, {"type": "tool_use", "id": "t1", "name": "mcp__toolbox__find_actions", "input": {"query": "x", "password": "hunter2hunter2"}}]}})
content = [{"type": "text", "text": json.dumps({"ok": True, "data": {"saved": True, "table": "scratch.out", "rows": 3}})}] if "SAVE" in msg else "abc"
out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": content}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": "Hello", "num_turns": 2, "duration_ms": 5, "usage": {"input_tokens": 3, "output_tokens": 2}})
'''


@pytest.fixture()
def env(tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-reach-child")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    token = tmp_path / "token"
    token.write_text("t" * 40)
    cfg = eng.Config(claude_bin=str(fake), work_dir=tmp_path / "work", mcp_config=tmp_path / "mcp.json", token_file=token, port=0, timeout_s=3, bind_docker_bridge=False)
    return cfg, log, tmp_path


def calls(log: Path) -> list[dict]:
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


def run(engine, msg, **kw):
    return list(engine.ask(msg, **kw))


# ---- engine: safety flags ------------------------------------------------------------------------------------------------------------------

def test_command_has_every_safety_flag(env):
    cfg, log, _ = env
    e = eng.ClaudeCodeEngine(cfg)
    cmd = e.command(thread_id=str(uuid.uuid4()), resume=False)
    assert cmd[cmd.index("--tools") + 1] == ""                       # no built-in tools: no Bash / Edit / Write / Read
    assert "--strict-mcp-config" in cmd and "--mcp-config" in cmd    # only the Toolbox server, no cloud connectors
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__toolbox"
    for bad in ("--bare", "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "bypassPermissions"):
        assert bad not in cmd
    assert "--no-session-persistence" not in cmd                      # threads need the session kept
    assert "--session-id" in cmd and "--resume" not in cmd
    assert "--resume" in e.command(thread_id=str(uuid.uuid4()), resume=True)


def test_child_environment_is_stripped_and_question_goes_on_stdin(env):
    cfg, log, _ = env
    e = eng.ClaudeCodeEngine(cfg)
    evs = run(e, "-p --dangerously-skip-permissions hello")          # a message that looks like flags stays plain text
    assert evs[-1]["type"] == "done"
    c = calls(log)[0]
    assert "ANTHROPIC_API_KEY" not in c["env"] and "CLAUDE_CODE_USE_BEDROCK" not in c["env"]
    assert c["env"]["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert "--dangerously-skip-permissions" not in c["argv"] and "--dangerously-skip-permissions hello" in c["stdin"]
    assert Path(c["cwd"]).resolve() == cfg.work_dir.resolve()


def test_context_is_wrapped_and_capped(env):
    cfg, log, _ = env
    run(eng.ClaudeCodeEngine(cfg), "q", context="x" * 9000)
    stdin = calls(log)[0]["stdin"]
    assert stdin.startswith("<context>\n") and stdin.count("x") - 2 == cfg.max_context_chars and stdin.rstrip().endswith("q")


# ---- engine: events ------------------------------------------------------------------------------------------------------------------------

def test_events_in_order_and_text_not_doubled(env):
    cfg, _, _ = env
    evs = run(eng.ClaudeCodeEngine(cfg), "hi")
    assert [e["type"] for e in evs] == ["start", "text", "text", "tool", "tool", "done"]
    assert "".join(e["text"] for e in evs if e["type"] == "text") == "Hello"       # streamed pieces only, the full message is not repeated
    tool_run, tool_done = evs[3], evs[4]
    assert tool_run["name"] == "find_actions" and tool_run["status"] == "running" and "hunter2hunter2" not in tool_run["input"]
    assert tool_done["status"] == "done" and tool_done["name"] == "find_actions"
    assert evs[-1]["text"] == "Hello" and evs[-1]["turns"] == 2 and evs[0]["thread_id"] == evs[-1]["thread_id"]


def test_new_thread_gets_uuid_and_resume_uses_it(env):
    cfg, log, _ = env
    e = eng.ClaudeCodeEngine(cfg)
    tid = run(e, "one")[0]["thread_id"]
    assert eng.is_uuid(tid)
    run(e, "two", thread_id=tid)
    first, second = calls(log)
    assert first["argv"][first["argv"].index("--session-id") + 1] == tid
    assert second["argv"][second["argv"].index("--resume") + 1] == tid


@pytest.mark.parametrize("tid", ["../../etc/passwd", "--tools", "not-a-uuid", "", 5])
def test_bad_thread_id_is_refused_before_anything_runs(env, tid):
    cfg, log, _ = env
    evs = run(eng.ClaudeCodeEngine(cfg), "hi", thread_id=tid)
    assert evs[0]["code"] == "bad_request" and not calls(log)


def test_empty_and_long_messages_refused(env):
    cfg, log, _ = env
    e = eng.ClaudeCodeEngine(cfg)
    assert run(e, "   ")[0]["code"] == "bad_request"
    assert run(e, "x" * (cfg.max_message_chars + 1))[0]["code"] == "bad_request"
    assert not calls(log)


# ---- engine: plain-words failures ----------------------------------------------------------------------------------------------------------

def test_logged_out_is_reported_without_starting_a_question(env):
    cfg, log, tmp = env
    (tmp / "calls.log.auth").write_text("out")
    evs = run(eng.ClaudeCodeEngine(cfg), "hi")
    assert evs == [eng.error_event("not_logged_in", evs[0]["message"])] and "/login" in evs[0]["message"] and not calls(log)


def test_logged_out_mid_run_is_detected_from_the_error_text(env):
    cfg, _, _ = env
    evs = run(eng.ClaudeCodeEngine(cfg), "CRASH LOGIN")
    assert evs[-1]["code"] == "not_logged_in"


def test_limit_reached_names_the_reset_time_and_is_remembered(env):
    cfg, _, _ = env
    e = eng.ClaudeCodeEngine(cfg)
    evs = run(e, "LIMIT")
    assert evs[-1]["code"] == "limit_reached" and "resets" in evs[-1]["message"]
    assert e.last_limit["status"] == "rejected"


def test_crash_is_engine_failed_and_does_not_leak_secrets(env):
    cfg, _, _ = env
    evs = run(eng.ClaudeCodeEngine(cfg), "CRASH")
    assert evs[-1]["code"] == "engine_failed"
    assert "sk-ant-abc123456789" not in eng.scrub("key sk-ant-abc123456789 and password=hunter2")
    assert "hunter2" not in eng.scrub("password=hunter2")


def test_unknown_thread_message(env):
    cfg, _, _ = env
    evs = run(eng.ClaudeCodeEngine(cfg), "NOSESSION", thread_id=str(uuid.uuid4()))
    assert evs[-1]["code"] == "thread_not_found"


def test_timeout_kills_the_process_group(env):
    cfg, log, _ = env
    t0 = time.time()
    evs = run(eng.ClaudeCodeEngine(cfg), "HANG")
    assert evs[-1]["code"] == "timeout" and time.time() - t0 < 12


def test_cancel_stops_the_child(env):
    cfg, _, _ = env
    cancel = threading.Event()
    threading.Timer(0.8, cancel.set).start()
    t0 = time.time()
    evs = run(eng.ClaudeCodeEngine(cfg), "HANG", cancel=cancel)
    assert evs[-1]["code"] == "cancelled" and time.time() - t0 < 8


def test_status_states(env):
    cfg, _, tmp = env
    assert eng.ClaudeCodeEngine(cfg).status()["state"] == "ready"
    (tmp / "calls.log.auth").write_text("api")
    s = eng.ClaudeCodeEngine(cfg).status()
    assert s["state"] == "ready" and s["billing"] == "other" and "subscription" in s["message"]
    (tmp / "calls.log.auth").write_text("out")
    assert eng.ClaudeCodeEngine(cfg).status()["state"] == "not_logged_in"
    cfg.claude_bin = str(tmp / "missing")
    assert eng.ClaudeCodeEngine(cfg).status()["state"] == "not_installed"


def test_parser_ignores_garbage_lines():
    p = eng.StreamParser("tid")
    assert list(p.feed("not json")) == [] and list(p.feed("[1,2]")) == [] and list(p.feed("")) == []


def test_toolbox_server_down_gives_a_warning():
    p = eng.StreamParser("tid")
    evs = list(p.feed(json.dumps({"type": "system", "subtype": "init", "tools": [], "mcp_servers": [{"name": "toolbox", "status": "failed"}]})))
    assert [e["type"] for e in evs] == ["start", "warning"]


# ---- the HTTP bridge -----------------------------------------------------------------------------------------------------------------------

@pytest.fixture()
def server(env):
    cfg, log, tmp = env
    servers = bridge_mod.serve(cfg)
    port = servers[0].server_address[1]
    yield f"http://127.0.0.1:{port}", cfg, log
    for s in servers:
        s.shutdown()
        s.server_close()


def http(method, url, body=None, token="t" * 40):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"X-Helper-Token": token} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def events(text):
    return [json.loads(l[6:]) for l in text.split("\n\n") if l.startswith("data: ")]


def test_bridge_requires_the_token(server):
    base, _, log = server
    assert http("GET", base + "/status", token=None)[0] == 401
    assert http("GET", base + "/status", token="wrong" * 8)[0] == 401
    assert http("POST", base + "/ask", {"message": "hi"}, token=None)[0] == 401
    assert not calls(log)
    assert http("GET", base + "/status")[0] == 200


def test_bridge_streams_sse_answer(server):
    base, _, _ = server
    code, text = http("POST", base + "/ask", {"message": "hi"})
    evs = events(text)
    assert code == 200 and [e["type"] for e in evs][0] == "start" and evs[-1]["type"] == "done" and evs[-1]["text"] == "Hello"


def test_bridge_rejects_bad_requests(server):
    base, _, _ = server
    assert http("POST", base + "/ask", {"nope": 1})[0] == 400
    assert http("POST", base + "/ask", {"message": 5})[0] == 400
    assert http("POST", base + "/ask", {"message": "x" * 70000})[0] == 413
    assert http("GET", base + "/other")[0] == 404
    code, text = http("POST", base + "/ask", {"message": "hi", "thread_id": "--tools"})
    assert events(text)[-1]["code"] == "bad_request"


def test_bridge_one_question_at_a_time(server):
    base, _, _ = server
    res = {}
    t = threading.Thread(target=lambda: res.setdefault("a", http("POST", base + "/ask", {"message": "HANG"})))
    t.start()
    time.sleep(1.0)
    code, text = http("POST", base + "/ask", {"message": "hi"})
    assert code == 409 and json.loads(text)["code"] == "busy"
    t.join(15)
    assert events(res["a"][1])[-1]["code"] == "timeout"


def test_bridge_refuses_short_token_file(env):
    cfg, _, _ = env
    cfg.token_file.write_text("short")
    with pytest.raises(SystemExit):
        bridge_mod.serve(cfg)


def test_bridge_binds_only_requested_addresses(env):
    cfg, _, _ = env
    servers = bridge_mod.serve(cfg)
    try:
        assert {s.server_address[0] for s in servers} == {"127.0.0.1"}
    finally:
        for s in servers:
            s.shutdown(); s.server_close()


# ---- installer -----------------------------------------------------------------------------------------------------------------------------

def test_installer_plan_uses_absolute_paths_and_private_token(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ai-bridge"))
    import install

    plan = install.build(tmp_path, "/x/claude", "/usr/bin/docker", "/usr/bin/python3")
    cfg = plan["config"]
    assert cfg["bind"] == ["127.0.0.1"] and cfg["claude_bin"].startswith("/") and cfg["port"] == 8787
    assert plan["mcp"]["mcpServers"]["toolbox"]["command"] == "/usr/bin/docker"
    assert "Restart=on-failure" in plan["unit"] and "WantedBy=default.target" in plan["unit"] and "/usr/bin/python3 " in plan["unit"]
    p = tmp_path / "tok"
    install.write_private(p, "secret")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_write_env_keeps_other_lines_and_makes_a_backup(tmp_path):
    import install

    env = tmp_path / ".env"
    env.write_text("A=1\nTOOLBOX_HELPER_TOKEN=old\nB=2\n")
    install.write_env(env, "newtoken")
    lines = env.read_text().splitlines()
    assert lines[:2] == ["A=1", "B=2"] and "TOOLBOX_HELPER_TOKEN=newtoken" in lines and "TOOLBOX_HELPER_TOKEN=old" not in lines
    assert any(f.name.startswith(".env.bak-helper-") for f in tmp_path.iterdir())


# ---- gateway pass-through ------------------------------------------------------------------------------------------------------------------

def _gateway_client():
    pytest.importorskip("httpx")
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from core_plugins import helper

    app = fastapi.FastAPI()
    app.include_router(helper.router)
    return TestClient(app)


def test_gateway_not_set_up(monkeypatch):
    monkeypatch.delenv("TOOLBOX_HELPER_URL", raising=False)
    monkeypatch.delenv("TOOLBOX_HELPER_TOKEN", raising=False)
    c = _gateway_client()
    assert c.get("/api/helper/status").json()["state"] == "not_set_up"
    ev = events(c.post("/api/helper/ask", json={"message": "hi"}).text)
    assert ev[0]["code"] == "not_set_up"


def test_gateway_bridge_down(monkeypatch):
    monkeypatch.setenv("TOOLBOX_HELPER_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("TOOLBOX_HELPER_TOKEN", "t" * 40)
    c = _gateway_client()
    assert c.get("/api/helper/status").json()["state"] == "bridge_down"
    assert events(c.post("/api/helper/ask", json={"message": "hi"}).text)[0]["code"] == "bridge_down"


def test_gateway_streams_through_and_keeps_the_token_server_side(server, monkeypatch):
    base, _, log = server
    monkeypatch.setenv("TOOLBOX_HELPER_URL", base)
    monkeypatch.setenv("TOOLBOX_HELPER_TOKEN", "t" * 40)
    c = _gateway_client()
    st = c.get("/api/helper/status")
    assert st.json()["state"] == "ready" and "t" * 40 not in st.text
    r = c.post("/api/helper/ask", json={"message": "hi", "evil": "--bare", "context": "ctx"})
    evs = events(r.text)
    assert evs[-1]["type"] == "done" and evs[-1]["text"] == "Hello" and "t" * 40 not in r.text
    assert "ctx" in calls(log)[-1]["stdin"]
    assert c.post("/api/helper/ask", content=b"not json").status_code == 400
    assert c.post("/api/helper/ask", json={"nomessage": 1}).status_code == 400


def test_gateway_wrong_token_is_explained(server, monkeypatch):
    base, _, _ = server
    monkeypatch.setenv("TOOLBOX_HELPER_URL", base)
    monkeypatch.setenv("TOOLBOX_HELPER_TOKEN", "x" * 40)
    c = _gateway_client()
    assert c.get("/api/helper/status").json()["state"] == "token_mismatch"


# ---- chat log, paging, policy, action-first prompt (follow-up to H2) -------------------------------------------------------------------

def test_system_prompt_is_action_first_and_policy_is_appended(env):
    cfg, log, _ = env
    e = eng.ClaudeCodeEngine(cfg)
    base = e.system_prompt()
    assert "ready to copy" in base and "write ONLY the new step" in base and "do NOT paste data rows" in base and "do NOT save, stage or load anything unless" in base and "def transform(df)" in base and "Mode: COMMAND" in base and "Mode: RUN" in base and "approval card" in base and "cannot approve for them" in base
    cfg.policy_file.write_text("- Always answer in French.\n")
    p = e.system_prompt()
    assert p.startswith(eng.SYSTEM_CARD) and "Always answer in French" in p and "cannot override" in p
    cfg.policy_file.write_text("x" * 9000)
    assert len(e.system_prompt()) < len(eng.SYSTEM_CARD) + eng.POLICY_MAX + 200                      # capped
    cfg.policy_file.unlink()
    assert e.system_prompt() == eng.SYSTEM_CARD                                                      # no file = no policy
    run(e, "hi")
    argv = calls(log)[0]["argv"]
    assert argv[argv.index("--system-prompt") + 1] == eng.SYSTEM_CARD


def test_default_policy_cannot_be_read_as_relaxing_safety():
    assert "NEVER relax safety" in eng.DEFAULT_POLICY and len(eng.DEFAULT_POLICY) < eng.POLICY_MAX


def test_saved_flag_only_for_a_real_write(env):
    cfg, _, _ = env
    e = eng.ClaudeCodeEngine(cfg)
    evs = run(e, "SAVE it")
    done = [x for x in evs if x["type"] == "tool" and x["status"] == "done"][0]
    assert done["saved"] is True and done["what"] == "scratch.out"
    assert "saved" not in [x for x in run(e, "plain") if x["type"] == "tool" and x["status"] == "done"][0]


def test_chat_log_keeps_the_conversation_in_order_and_survives_a_new_server(server):
    base, cfg, _ = server
    code, text = http("POST", base + "/ask", {"message": "first question", "tool": "df-studio"})
    tid = events(text)[0]["thread_id"]
    http("POST", base + "/ask", {"message": "SAVE second", "thread_id": tid, "tool": "df-studio"})
    chats = json.loads(http("GET", base + "/chats")[1])["chats"]
    assert chats[0]["id"] == tid and chats[0]["title"] == "first question" and chats[0]["tool"] == "df-studio" and chats[0]["n"] == 4
    msgs = json.loads(http("GET", base + f"/chats/{tid}/messages")[1])["messages"]
    roles = [m["role"] for m in msgs]
    assert roles[0] == "user" and msgs[0]["text"] == "first question" and "assistant" in roles and "tool" in roles
    saved = [m for m in msgs if m["role"] == "tool" and m["meta"] and m["meta"]["saved"]]
    assert saved and saved[0]["meta"]["what"] == "scratch.out"
    assert [m["text"] for m in msgs if m["role"] == "user"] == ["first question", "SAVE second"]


def test_chat_log_pages_from_the_newest_and_loads_older_on_request(server):
    base, cfg, _ = server
    from store import ChatStore

    st = ChatStore(cfg.chat_db)
    cid = str(uuid.uuid4())
    st.ensure_chat(cid, "long chat", "home")
    for i in range(75):
        st.add(cid, "user" if i % 2 == 0 else "assistant", f"m{i}")
    first = json.loads(http("GET", base + f"/chats/{cid}/messages?limit=30")[1])
    assert [m["text"] for m in first["messages"]][0] == "m45" and first["messages"][-1]["text"] == "m74" and first["has_more"] is True
    older = json.loads(http("GET", base + f"/chats/{cid}/messages?limit=30&before={first['messages'][0]['id']}")[1])
    assert older["messages"][-1]["text"] == "m44" and older["messages"][0]["text"] == "m15" and older["has_more"] is True
    last = json.loads(http("GET", base + f"/chats/{cid}/messages?limit=60&before={older['messages'][0]['id']}")[1])
    assert len(last["messages"]) == 15 and last["has_more"] is False
    assert len(json.loads(http("GET", base + f"/chats/{cid}/messages?limit=9999")[1])["messages"]) == 60       # page size is capped


def test_an_answer_cut_off_by_a_closed_browser_is_still_logged(server):
    base, cfg, _ = server
    import socket

    tid = str(uuid.uuid4())
    s = socket.create_connection((base.split("//")[1].split(":")[0], int(base.rsplit(":", 1)[1])))
    body = json.dumps({"message": "HANG please", "thread_id": tid}).encode()
    s.sendall(b"POST /ask HTTP/1.1\r\nHost: x\r\nX-Helper-Token: " + b"t" * 40 + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    time.sleep(1.0)
    s.close()
    time.sleep(1.5)
    msgs = json.loads(http("GET", base + f"/chats/{tid}/messages")[1])["messages"]
    assert [m["text"] for m in msgs][:1] == ["HANG please"]


def test_chat_endpoints_need_the_token_and_validate_ids(server):
    base, _, _ = server
    assert http("GET", base + "/chats", token=None)[0] == 401
    assert http("GET", base + "/policy", token=None)[0] == 401
    assert http("DELETE", base + f"/chats/{uuid.uuid4()}", token=None)[0] == 401
    assert http("GET", base + "/chats/not-a-uuid/messages")[0] == 404
    assert http("GET", base + f"/chats/{uuid.uuid4()}/messages?before=abc")[0] == 400


def test_delete_a_chat_log(server):
    base, _, _ = server
    tid = events(http("POST", base + "/ask", {"message": "to delete"})[1])[0]["thread_id"]
    assert json.loads(http("DELETE", base + f"/chats/{tid}")[1])["deleted"] is True
    assert json.loads(http("GET", base + "/chats")[1])["chats"] == []


def test_policy_read_write_reset_and_limits(server):
    base, cfg, _ = server
    got = json.loads(http("GET", base + "/policy")[1])
    assert "Style" in got["policy"] and got["max_chars"] == eng.POLICY_MAX
    req = urllib.request.Request(base + "/policy", data=json.dumps({"policy": "- Be brief."}).encode(), method="PUT", headers={"X-Helper-Token": "t" * 40})
    assert json.loads(urllib.request.urlopen(req).read())["policy"] == "- Be brief." and cfg.policy_file.read_text() == "- Be brief."
    assert "Be brief" in eng.ClaudeCodeEngine(cfg).system_prompt()
    for bad in ({"policy": "x" * (eng.POLICY_MAX + 1)}, {"policy": 5}, {}):
        r = urllib.request.Request(base + "/policy", data=json.dumps(bad).encode(), method="PUT", headers={"X-Helper-Token": "t" * 40})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(r)
        assert e.value.code == 400
    r = urllib.request.Request(base + "/policy", data=json.dumps({"reset": True}).encode(), method="PUT", headers={"X-Helper-Token": "t" * 40})
    assert "Style" in json.loads(urllib.request.urlopen(r).read())["policy"]


def test_chat_store_prunes_old_chats_and_caps_text(tmp_path):
    from store import ChatStore, MAX_CHATS, MAX_TEXT

    st = ChatStore(tmp_path / "x.db")
    for i in range(MAX_CHATS + 5):
        st.ensure_chat(str(uuid.uuid4()), f"c{i}", "t")
    assert len(st.chats(100)) <= 100
    with st._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == MAX_CHATS
    cid = str(uuid.uuid4()); st.ensure_chat(cid, "t", "t"); st.add(cid, "assistant", "y" * (MAX_TEXT + 500))
    assert len(st.messages(cid)["messages"][0]["text"]) == MAX_TEXT
    assert stat.S_IMODE(st.path.stat().st_mode) == 0o600


def test_gateway_passes_chats_and_policy_and_tool_field_through(server, monkeypatch):
    base, cfg, log = server
    monkeypatch.setenv("TOOLBOX_HELPER_URL", base)
    monkeypatch.setenv("TOOLBOX_HELPER_TOKEN", "t" * 40)
    c = _gateway_client()
    tid = events(c.post("/api/helper/ask", json={"message": "hello log", "tool": "sql-studio"}).text)[0]["thread_id"]
    chats = c.get("/api/helper/chats").json()["chats"]
    assert chats[0]["id"] == tid and chats[0]["tool"] == "sql-studio"
    assert c.get(f"/api/helper/chats/{tid}/messages?limit=5").json()["messages"][0]["text"] == "hello log"
    assert c.get("/api/helper/chats/zzz/messages").status_code in (400, 404)
    assert c.put("/api/helper/policy", json={"policy": "- ok"}).json()["policy"] == "- ok"
    assert "Style" in c.get("/api/helper/policy").json()["default"]
    assert c.delete(f"/api/helper/chats/{tid}").json()["deleted"] is True
    assert "t" * 40 not in c.get("/api/helper/policy").text


def test_gateway_chat_routes_say_so_when_not_set_up(monkeypatch):
    monkeypatch.delenv("TOOLBOX_HELPER_URL", raising=False)
    monkeypatch.delenv("TOOLBOX_HELPER_TOKEN", raising=False)
    c = _gateway_client()
    assert c.get("/api/helper/chats").json()["state"] == "not_set_up" and c.get("/api/helper/policy").status_code == 503


# ---- per-tool policies and the owner's reviews ------------------------------------------------------------------------------------------

def test_tool_policy_is_added_for_that_tool_only_and_names_are_validated(env):
    cfg, log, _ = env
    e = eng.ClaudeCodeEngine(cfg)
    cfg.policies_dir.mkdir(parents=True, exist_ok=True)
    cfg.tool_policy_file("df-studio").write_text("- Give code ready to copy.\n")
    cfg.policy_file.write_text("- Be brief.\n")
    p = e.system_prompt("df-studio")
    assert "Be brief" in p and "Give code ready to copy" in p and "df-studio" in p and "cannot override the rules above" in p
    assert p.index("Be brief") < p.index("Give code ready to copy")                       # general first, the tool's own after it (it wins where they differ)
    assert "Give code ready" not in e.system_prompt("sql-studio") and "Give code ready" not in e.system_prompt("")
    for bad in ("../x", "A B", "x" * 80, "a/b", ""):
        assert e.system_prompt(bad) == e.system_prompt("")
    with pytest.raises(ValueError):
        cfg.tool_policy_file("../../etc/passwd")
    run(e, "hi", tool="df-studio")
    argv = calls(log)[0]["argv"]
    assert "Give code ready to copy" in argv[argv.index("--system-prompt") + 1]


def test_policy_endpoints_per_tool_seed_save_reset_and_reject_bad_names(server):
    base, cfg, _ = server
    got = json.loads(http("GET", base + "/policy?tool=df-studio")[1])
    assert "def transform(df)" in got["policy"] and got["tool"] == "df-studio" and got["tools"] == []          # the starting text is shown before anything is saved
    assert "What this tool is for" in json.loads(http("GET", base + "/policy?tool=some-tool")[1])["policy"]
    put = lambda body: urllib.request.urlopen(urllib.request.Request(base + "/policy", data=json.dumps(body).encode(), method="PUT", headers={"X-Helper-Token": "t" * 40}))
    out = json.loads(put({"tool": "df-studio", "policy": "- mine"}).read())
    assert out["policy"] == "- mine" and out["tools"] == ["df-studio"] and cfg.tool_policy_file("df-studio").read_text() == "- mine"
    assert "Be brief" not in cfg.policy_file.read_text() or True and "mine" not in cfg.policy_file.read_text()   # the general policy is a different file
    assert "def transform(df)" in json.loads(put({"tool": "df-studio", "reset": True}).read())["policy"]
    for body in ({"tool": "../x", "policy": "a"}, {"tool": 5, "policy": "a"}, {"tool": "ok", "policy": "x" * (eng.POLICY_MAX + 1)}):
        with pytest.raises(urllib.error.HTTPError) as exc:
            put(body)
        assert exc.value.code == 400
    assert http("GET", base + "/policy?tool=../x")[0] == 400


def test_done_event_carries_the_answer_id_and_reviews_are_stored_and_summarised(server):
    base, cfg, _ = server
    code, text = http("POST", base + "/ask", {"message": "hi", "tool": "df-studio"})
    done = [e for e in events(text) if e["type"] == "done"][0]
    tid, mid = done["thread_id"], done["message_id"]
    assert isinstance(mid, int)
    msgs = json.loads(http("GET", base + f"/chats/{tid}/messages")[1])["messages"]
    assert [m for m in msgs if m["id"] == mid][0]["role"] == "assistant"
    ok = json.loads(http("POST", base + "/reviews", {"chat": tid, "message_id": mid, "tool": "df-studio", "rating": "down", "note": "Do not paste rows"})[1])
    assert ok["ok"] is True
    again = json.loads(http("POST", base + "/reviews", {"chat": tid, "message_id": mid, "tool": "df-studio", "rating": "down", "note": "Just the count please"})[1])
    revs = json.loads(http("GET", base + "/reviews?tool=df-studio")[1])["reviews"]
    assert [r["note"] for r in revs] == ["Just the count please"]                                              # one review per answer: the latest wins
    http("POST", base + "/reviews", {"chat": tid, "message_id": None, "tool": "df-studio", "rating": "up", "note": ""})
    s = json.loads(http("GET", base + "/reviews/summary?tool=df-studio")[1])
    assert s["tools"]["df-studio"] == {"up": 1, "down": 1}
    assert json.loads(http("POST", base + f"/reviews/{revs[0]['id']}/status", {"status": "used"})[1])["ok"] is True
    assert json.loads(http("GET", base + "/reviews?tool=df-studio")[1])["reviews"] == []
    assert len(json.loads(http("GET", base + "/reviews?tool=df-studio&status=used")[1])["reviews"]) == 1


def test_review_inputs_are_validated_and_need_the_token(server):
    base, _, _ = server
    tid = str(uuid.uuid4())
    assert http("POST", base + "/reviews", {"chat": tid, "tool": "x", "rating": "up"}, token=None)[0] == 401
    assert http("GET", base + "/reviews", token=None)[0] == 401
    for bad in ({"chat": "nope", "tool": "x", "rating": "up"}, {"chat": tid, "tool": "../x", "rating": "up"}, {"chat": tid, "tool": "x", "rating": "meh"}, {"chat": tid, "tool": "x", "rating": "up", "note": 5}):
        assert http("POST", base + "/reviews", bad)[0] == 400
    assert http("GET", base + "/reviews?tool=../x")[0] == 400
    assert http("POST", base + "/reviews/1/status", {"status": "weird"})[0] == 400


def test_gateway_passes_tool_policy_and_reviews(server, monkeypatch):
    base, _, _ = server
    monkeypatch.setenv("TOOLBOX_HELPER_URL", base)
    monkeypatch.setenv("TOOLBOX_HELPER_TOKEN", "t" * 40)
    c = _gateway_client()
    assert "def transform(df)" in c.get("/api/helper/policy?tool=df-studio").json()["policy"]
    assert c.put("/api/helper/policy", json={"tool": "df-studio", "policy": "- x"}).json()["tools"] == ["df-studio"]
    assert c.get("/api/helper/policy?tool=..%2Fx").status_code == 400
    tid = events(c.post("/api/helper/ask", json={"message": "q", "tool": "df-studio"}).text)[0]["thread_id"]
    assert c.post("/api/helper/reviews", json={"chat": tid, "tool": "df-studio", "rating": "down", "note": "n"}).json()["ok"] is True
    assert c.get("/api/helper/reviews?tool=df-studio").json()["reviews"][0]["note"] == "n"
    assert c.get("/api/helper/reviews/summary?tool=df-studio").json()["tools"]["df-studio"]["down"] == 1
    assert c.get("/api/helper/reviews?status=weird").status_code == 400

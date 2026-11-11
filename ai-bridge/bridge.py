"""
ai-bridge/bridge.py — the AI helper bridge: a tiny local web service on the HOST (roadmap H1, ADR-AI-HELPER D2).

    GET  /status   -> {"state": "ready|not_logged_in|limit_reached|not_installed|engine_failed", "message", ...}
    POST /ask      -> Server-Sent Events: one `data: {json}` per engine event (see engine.py), ends after `done` or `error`
                      body: {"message": "...", "thread_id": "<uuid>|null", "context": "..."}

Only the Toolbox gateway talks to it, with a shared secret in the header X-Helper-Token (file chosen at install time).
Listens on 127.0.0.1 and on the docker bridge address (so the gateway container can reach `host.docker.internal`) — never on the LAN.
One question at a time (a second one is told "busy"). The child process is killed when the caller disconnects.
Standard library only. Run: python3 bridge.py --config ~/.config/toolbox-helper/config.json
"""

from __future__ import annotations

import argparse
import hmac
import json
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import DEFAULT_POLICY, POLICY_MAX, TOOL_NAME_RE, ClaudeCodeEngine, Config, Engine, default_tool_policy, error_event, is_uuid  # noqa: E402
from store import ChatStore  # noqa: E402

MAX_BODY = 64 * 1024


def docker_bridge_ip() -> Optional[str]:
    """Address of the `docker0` bridge (what host.docker.internal points to), or None when Docker is not up."""
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "docker0"], capture_output=True, text=True, timeout=5).stdout
        for part in out.split():
            if "/" in part and part.count(".") == 3:
                return part.split("/")[0]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


class Bridge:
    def __init__(self, engine: Engine, token: str, store: Optional[ChatStore] = None, policy_file: Optional[Path] = None, cfg: Optional[Config] = None):
        self.engine = engine
        self.cfg = cfg
        self.token = token
        self.store = store
        self.policy_file = policy_file
        self.busy = threading.Lock()

    def authorised(self, header: Optional[str]) -> bool:
        return bool(self.token) and bool(header) and hmac.compare_digest(header.encode(), self.token.encode())

    def _file(self, tool: str = "") -> Optional[Path]:
        if not tool:
            return self.policy_file
        if self.cfg is None or not TOOL_NAME_RE.match(tool):
            raise ValueError("bad tool name")
        return self.cfg.tool_policy_file(tool)

    def policy(self, tool: str = "") -> str:
        default = default_tool_policy(tool) if tool else DEFAULT_POLICY
        try:
            f = self._file(tool)
            return f.read_text(encoding="utf-8") if f is not None and f.exists() else default
        except OSError:
            return default

    def tools_with_policy(self) -> list[str]:
        try:
            return sorted(p.stem for p in self.cfg.policies_dir.glob("*.md") if TOOL_NAME_RE.match(p.stem)) if self.cfg else []
        except OSError:
            return []

    def set_policy(self, text: str, tool: str = "") -> None:
        f = self._file(tool)
        if f is None:
            raise ValueError("no policy file")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        try:
            f.chmod(0o600)
        except OSError:
            pass


class Recorder:
    """Writes what streams past into the chat log: the question, each piece of answer text (split where a tool ran), tool chips, errors. Display only."""

    def __init__(self, store: Optional[ChatStore], message: str, thread_id: Optional[str], tool: str):
        self.store, self.message, self.tool = store, message, tool
        self.chat = thread_id if is_uuid(thread_id) else None
        self.text = ""
        self.any_text = False           # any answer text was recorded for this question
        self.last_id = None             # id of the last answer text row (for reviews)
        self.have_user = False
        if self.chat:
            self._user()

    def _safe(self, fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as exc:  # noqa: BLE001 - the log must never break an answer
            sys.stderr.write(f"chat log: {type(exc).__name__}\n")

    def _user(self) -> None:
        if self.store and self.chat and not self.have_user:
            self._safe(self.store.ensure_chat, self.chat, self.message, self.tool)
            self._safe(self.store.add, self.chat, "user", self.message)
            self.have_user = True

    def flush(self) -> None:
        if self.store and self.chat and self.text.strip():
            self.any_text = True
            self.last_id = self._safe(self.store.add, self.chat, "assistant", self.text)
        self.text = ""

    def event(self, ev: dict) -> None:
        if not self.store:
            return
        t = ev.get("type")
        if t == "start" and not self.chat and is_uuid(ev.get("thread_id")):
            self.chat = ev["thread_id"]
            self._user()
        elif t == "text":
            self.text += ev.get("text", "")
        elif t == "tool" and ev.get("status") == "running":
            self.flush()
        elif t == "tool" and self.chat:
            self._safe(self.store.add, self.chat, "tool", ev.get("name", "?"), {"status": ev.get("status"), "saved": bool(ev.get("saved")), "what": ev.get("what", "")})
        elif t == "done":
            if not self.text.strip() and not self.any_text and ev.get("text"):
                self.text = ev["text"]
            self.flush()
            if self.last_id:
                ev["message_id"] = self.last_id          # the panel attaches 👍 / 👎 to this answer
        elif t in ("error", "warning") and self.chat:
            self.flush()
            self._safe(self.store.add, self.chat, "system", ev.get("message", ""), {"error": t == "error", "code": ev.get("code")})

    def close(self) -> None:
        self.flush()                    # an answer cut off by a closed browser is still kept (what was written so far)

    def authorised(self, header: Optional[str]) -> bool:
        return bool(self.token) and bool(header) and hmac.compare_digest(header.encode(), self.token.encode())


def make_handler(bridge: Bridge, cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "toolbox-helper"

        def log_message(self, fmt, *args):  # no request bodies / questions in logs
            sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

        def _send_json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _check(self) -> bool:
            if not bridge.authorised(self.headers.get("X-Helper-Token")):
                self._send_json(401, error_event("unauthorised", "The helper did not accept this request."))
                return False
            return True

        def do_GET(self):
            path, _, qs = self.path.partition("?")
            if path not in ("/status", "/chats", "/policy", "/reviews", "/reviews/summary") and not path.startswith("/chats/"):
                return self._send_json(404, error_event("bad_request", "Not found."))
            if not self._check():
                return
            q = urllib.parse.parse_qs(qs)
            if path == "/status":
                return self._send_json(200, {**bridge.engine.status(), "busy": bridge.busy.locked()})
            if path == "/policy":
                tool = (q.get("tool") or [""])[0]
                if tool and not TOOL_NAME_RE.match(tool):
                    return self._send_json(400, error_event("bad_request", "That tool name is not valid."))
                return self._send_json(200, {"policy": bridge.policy(tool), "max_chars": POLICY_MAX, "tool": tool, "tools": bridge.tools_with_policy(),
                                             "default": default_tool_policy(tool) if tool else DEFAULT_POLICY})
            if bridge.store is None:
                return self._send_json(200, {"chats": [], "messages": [], "has_more": False})
            if path in ("/reviews", "/reviews/summary"):
                tool = (q.get("tool") or [""])[0]
                if tool and not TOOL_NAME_RE.match(tool):
                    return self._send_json(400, error_event("bad_request", "That tool name is not valid."))
                if path == "/reviews/summary":
                    return self._send_json(200, bridge.store.review_summary(tool))
                return self._send_json(200, {"reviews": bridge.store.reviews(tool, (q.get("status") or ["new"])[0])})
            if path == "/chats":
                return self._send_json(200, {"chats": bridge.store.chats(int((q.get("limit") or ["40"])[0] or 40))})
            m = re.fullmatch(r"/chats/([0-9a-fA-F-]{36})/messages", path)
            if not m:
                return self._send_json(404, error_event("bad_request", "Not found."))
            try:
                before = int(q["before"][0]) if q.get("before") else None
                limit = int((q.get("limit") or ["30"])[0])
            except ValueError:
                return self._send_json(400, error_event("bad_request", "Bad paging."))
            self._send_json(200, bridge.store.messages(m.group(1), before, limit))

        def do_DELETE(self):
            m = re.fullmatch(r"/chats/([0-9a-fA-F-]{36})", self.path.split("?")[0])
            if not m:
                return self._send_json(404, error_event("bad_request", "Not found."))
            if not self._check():
                return
            self._send_json(200, {"deleted": bool(bridge.store and bridge.store.delete(m.group(1)))})

        def do_PUT(self):
            if self.path.split("?")[0] != "/policy":
                return self._send_json(404, error_event("bad_request", "Not found."))
            if not self._check():
                return
            try:
                n = int(self.headers.get("Content-Length") or "0")
                req = json.loads(self.rfile.read(n).decode("utf-8")) if 0 < n <= MAX_BODY else None
                assert isinstance(req, dict)
            except (ValueError, AssertionError, UnicodeDecodeError):
                return self._send_json(400, error_event("bad_request", "The request could not be read."))
            tool = req.get("tool") or ""
            if not isinstance(tool, str) or (tool and not TOOL_NAME_RE.match(tool)):
                return self._send_json(400, error_event("bad_request", "That tool name is not valid."))
            text = (default_tool_policy(tool) if tool else DEFAULT_POLICY) if req.get("reset") else req.get("policy")
            if not isinstance(text, str) or len(text) > POLICY_MAX:
                return self._send_json(400, error_event("bad_request", f"The policy must be text of at most {POLICY_MAX} characters."))
            try:
                bridge.set_policy(text, tool)
            except (OSError, ValueError):
                return self._send_json(500, error_event("engine_failed", "The policy could not be saved."))
            self._send_json(200, {"policy": bridge.policy(tool), "tool": tool, "tools": bridge.tools_with_policy()})

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length") or "0")
                req = json.loads(self.rfile.read(n).decode("utf-8")) if 0 < n <= MAX_BODY else None
                return req if isinstance(req, dict) else None
            except (ValueError, UnicodeDecodeError):
                return None

        def _reviews_post(self, path: str) -> None:
            if bridge.store is None:
                return self._send_json(503, error_event("engine_failed", "The chat log is not available."))
            req = self._body()
            if req is None:
                return self._send_json(400, error_event("bad_request", "The request could not be read."))
            m = re.fullmatch(r"/reviews/(\d+)/status", path)
            try:
                if m:
                    return self._send_json(200, {"ok": bridge.store.set_review_status(int(m.group(1)), str(req.get("status")))})
                chat, tool = str(req.get("chat") or ""), str(req.get("tool") or "home")
                if not is_uuid(chat) or not TOOL_NAME_RE.match(tool) or not isinstance(req.get("note", ""), str):
                    raise ValueError("bad review")
                msg = req.get("message_id")
                rid = bridge.store.add_review(chat, int(msg) if msg is not None else None, tool, str(req.get("rating")), req.get("note", ""))
            except (ValueError, TypeError):
                return self._send_json(400, error_event("bad_request", "That review is not valid."))
            self._send_json(200, {"ok": True, "id": rid})

        def do_POST(self):
            path0 = self.path.split("?")[0]
            if path0 == "/reviews" or re.fullmatch(r"/reviews/\d+/status", path0):
                if not self._check():
                    return
                return self._reviews_post(path0)
            if path0 != "/ask":
                return self._send_json(404, error_event("bad_request", "Not found."))
            if not self._check():
                return
            try:
                n = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                n = -1
            if n <= 0 or n > MAX_BODY:
                return self._send_json(413 if n > MAX_BODY else 400, error_event("bad_request", "The request is empty or too large."))
            try:
                req = json.loads(self.rfile.read(n).decode("utf-8"))
                assert isinstance(req, dict)
                message, thread_id, context = req.get("message"), req.get("thread_id"), req.get("context") or ""
                tool = req.get("tool") if isinstance(req.get("tool"), str) else "home"
                assert isinstance(message, str) and isinstance(context, str) and (thread_id is None or isinstance(thread_id, str))
            except (ValueError, AssertionError, UnicodeDecodeError):
                return self._send_json(400, error_event("bad_request", "The request could not be read."))
            if not bridge.busy.acquire(blocking=False):
                return self._send_json(409, error_event("busy", "The helper is still answering the previous question. Wait for it to finish."))
            cancel = threading.Event()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                rec = Recorder(bridge.store, message, thread_id, tool)
                try:
                    for ev in bridge.engine.ask(message, thread_id=thread_id, context=context, cancel=cancel, tool=tool if TOOL_NAME_RE.match(tool) else ""):
                        rec.event(ev)
                        self.wfile.write(b"data: " + json.dumps(ev, ensure_ascii=False).encode() + b"\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    cancel.set()                      # browser closed -> the engine's generator is closed -> the child is killed
                except Exception as exc:  # noqa: BLE001
                    cancel.set()
                    try:
                        self.wfile.write(b"data: " + json.dumps(error_event("engine_failed", f"The helper failed ({type(exc).__name__}).")).encode() + b"\n\n")
                    except OSError:
                        pass
            finally:
                try:
                    rec.close()
                except Exception:  # noqa: BLE001
                    pass
                bridge.busy.release()

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(cfg: Config, engine: Optional[Engine] = None) -> list[_Server]:
    token = Path(cfg.token_file).read_text().strip()
    if len(token) < 24:
        raise SystemExit("The helper token file is missing or too short. Run: python3 ai-bridge/install.py install")
    store = None
    try:
        store = ChatStore(cfg.chat_db)
    except (OSError, sqlite3.Error) as exc:
        sys.stderr.write(f"chat log unavailable ({type(exc).__name__}); answers still work\n")
    pf = cfg.policy_file
    if not pf.exists():
        try:
            pf.parent.mkdir(parents=True, exist_ok=True)
            pf.write_text(DEFAULT_POLICY, encoding="utf-8")
            pf.chmod(0o600)
        except OSError:
            pass
    bridge = Bridge(engine or ClaudeCodeEngine(cfg), token, store, pf, cfg)
    handler = make_handler(bridge, cfg)
    servers: list[_Server] = []
    for host in cfg.bind:
        servers.append(_Server((host, cfg.port), handler))
    if cfg.bind_docker_bridge:
        threading.Thread(target=_bind_docker, args=(cfg, handler, servers), daemon=True).start()
    for s in list(servers):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    return servers


def _bind_docker(cfg: Config, handler, servers: list) -> None:
    """The docker bridge only exists once Docker is up; keep trying quietly (login can come before Docker)."""
    while True:
        ip = docker_bridge_ip()
        if ip:
            try:
                s = _Server((ip, cfg.port), handler)
            except OSError:
                time.sleep(10)
                continue
            servers.append(s)
            sys.stderr.write(f"also listening on docker bridge {ip}:{cfg.port}\n")
            s.serve_forever()
            return
        time.sleep(10)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--config", default=str(Path("~/.config/toolbox-helper/config.json").expanduser()))
    cfg = Config.load(Path(ap.parse_args().config))
    servers = serve(cfg)
    sys.stderr.write(f"toolbox-helper listening on {', '.join(cfg.bind)}:{cfg.port}\n")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        for s in servers:
            s.shutdown()


if __name__ == "__main__":
    main()

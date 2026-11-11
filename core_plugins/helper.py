"""
core_plugins/helper.py — the gateway's side of the AI helper (roadmap H1, ADR-AI-HELPER D2).

    GET  /api/helper/status   plain-words state of the helper
    POST /api/helper/ask      the question; the answer streams back as Server-Sent Events

The gateway only PASSES the request to the bridge that runs on the host (which holds the owner's Claude login). The shared secret
(TOOLBOX_HELPER_TOKEN) stays in the gateway's environment: the browser never sees it, and nothing of the Claude login is in any container.
When the bridge is not set up or not running the answer says so in plain words — never a stack trace, never a silent retry.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(prefix="/api/helper", tags=["helper"])

MAX_BODY = 64 * 1024
CONNECT_SECONDS = 3.0
ASK_SECONDS = 260.0                                  # a little above the bridge's own 240 s limit


def _settings() -> tuple[str, str]:
    return (os.environ.get("TOOLBOX_HELPER_URL") or "").strip().rstrip("/"), (os.environ.get("TOOLBOX_HELPER_TOKEN") or "").strip()


def _state(state: str, message: str, **extra: Any) -> dict:
    return {"state": state, "message": message, **extra}


NOT_SET_UP = _state("not_set_up", "The helper is not set up on this computer yet. In a terminal, in the Toolbox folder, run: python3 ai-bridge/install.py install --write-env  — then: docker compose up -d --no-deps toolbox")
BRIDGE_DOWN = _state("bridge_down", "The helper service is not running. Start it with: systemctl --user start toolbox-helper  (see the runbook, \"Set up the AI helper\").")


def _client(timeout: float) -> httpx.AsyncClient:
    # no cookies, no redirects, no environment proxies: this client only ever talks to the bridge
    return httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=httpx.Timeout(timeout, connect=CONNECT_SECONDS))


@router.get("/status", response_model=None)
async def status() -> JSONResponse:
    url, token = _settings()
    if not url or not token:
        return JSONResponse(NOT_SET_UP)
    try:
        async with _client(20.0) as c:
            r = await c.get(url + "/status", headers={"X-Helper-Token": token})
    except httpx.HTTPError:
        return JSONResponse(BRIDGE_DOWN)
    if r.status_code == 401:
        return JSONResponse(_state("token_mismatch", "The helper does not accept this Toolbox's key. Run the install command again with --write-env, then restart Toolbox."))
    try:
        return JSONResponse(r.json())
    except ValueError:
        return JSONResponse(BRIDGE_DOWN)


def _sse(obj: dict) -> bytes:
    return b"data: " + json.dumps(obj, ensure_ascii=False).encode() + b"\n\n"


@router.post("/ask", response_model=None)
async def ask(request: Request) -> StreamingResponse | JSONResponse:
    url, token = _settings()
    if not url or not token:
        return StreamingResponse(iter([_sse({"type": "error", "code": "not_set_up", "message": NOT_SET_UP["message"]})]), media_type="text/event-stream")
    body = await request.body()
    if not body or len(body) > MAX_BODY:
        return JSONResponse({"type": "error", "code": "bad_request", "message": "The request is empty or too large."}, status_code=400)
    try:
        req = json.loads(body)
        payload = {"message": req["message"], "thread_id": req.get("thread_id"), "context": req.get("context") or "", "tool": req.get("tool") if isinstance(req.get("tool"), str) else "home"}   # only these fields are forwarded
    except (ValueError, KeyError, TypeError, AttributeError):
        return JSONResponse({"type": "error", "code": "bad_request", "message": "The request could not be read."}, status_code=400)

    async def stream() -> AsyncIterator[bytes]:
        try:
            async with _client(ASK_SECONDS) as c:
                async with c.stream("POST", url + "/ask", json=payload, headers={"X-Helper-Token": token}) as r:
                    if r.status_code != 200:
                        raw = await r.aread()
                        try:
                            yield _sse(json.loads(raw))
                        except ValueError:
                            yield _sse({"type": "error", "code": "engine_failed", "message": f"The helper answered with an error (HTTP {r.status_code})."})
                        return
                    async for chunk in r.aiter_raw():          # passed through untouched, so the answer appears as it is written
                        yield chunk
        except httpx.ConnectError:
            yield _sse({"type": "error", "code": "bridge_down", "message": BRIDGE_DOWN["message"]})
        except httpx.HTTPError:
            yield _sse({"type": "error", "code": "engine_failed", "message": "The connection to the helper broke before the answer was finished."})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ---- the chat log and the policy live on the host with the bridge; these routes only pass them through --------------------------------

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


async def _forward(method: str, path: str, params: dict | None = None, body: bytes | None = None) -> JSONResponse:
    url, token = _settings()
    if not url or not token:
        return JSONResponse(NOT_SET_UP, status_code=503)
    try:
        async with _client(20.0) as c:
            r = await c.request(method, url + path, params=params, content=body, headers={"X-Helper-Token": token, "Content-Type": "application/json"})
        return JSONResponse(r.json(), status_code=r.status_code)
    except (httpx.HTTPError, ValueError):
        return JSONResponse(BRIDGE_DOWN, status_code=503)


@router.get("/chats", response_model=None)
async def chats(limit: int = 40) -> JSONResponse:
    return await _forward("GET", "/chats", {"limit": max(1, min(limit, 100))})


@router.get("/chats/{chat_id}/messages", response_model=None)
async def chat_messages(chat_id: str, before: int | None = None, limit: int = 30) -> JSONResponse:
    if not re.fullmatch(_UUID, chat_id):
        return JSONResponse({"type": "error", "code": "bad_request", "message": "That chat id is not valid."}, status_code=400)
    params: dict = {"limit": max(1, min(limit, 60))}
    if before:
        params["before"] = before
    return await _forward("GET", f"/chats/{chat_id}/messages", params)


@router.delete("/chats/{chat_id}", response_model=None)
async def delete_chat(chat_id: str) -> JSONResponse:
    if not re.fullmatch(_UUID, chat_id):
        return JSONResponse({"type": "error", "code": "bad_request", "message": "That chat id is not valid."}, status_code=400)
    return await _forward("DELETE", f"/chats/{chat_id}")


_TOOL = r"[a-z0-9][a-z0-9_-]{0,40}"


@router.get("/policy", response_model=None)
async def get_policy(tool: str = "") -> JSONResponse:
    if tool and not re.fullmatch(_TOOL, tool):
        return JSONResponse({"type": "error", "code": "bad_request", "message": "That tool name is not valid."}, status_code=400)
    return await _forward("GET", "/policy", {"tool": tool} if tool else None)


@router.put("/policy", response_model=None)
async def put_policy(request: Request) -> JSONResponse:
    body = await request.body()
    if not body or len(body) > 16 * 1024:
        return JSONResponse({"type": "error", "code": "bad_request", "message": "The policy is empty or too large."}, status_code=400)
    return await _forward("PUT", "/policy", body=body)


@router.post("/reviews", response_model=None)
async def post_review(request: Request) -> JSONResponse:
    body = await request.body()
    if not body or len(body) > 8 * 1024:
        return JSONResponse({"type": "error", "code": "bad_request", "message": "The review is empty or too large."}, status_code=400)
    return await _forward("POST", "/reviews", body=body)


@router.get("/reviews", response_model=None)
async def get_reviews(tool: str = "", status: str = "new") -> JSONResponse:
    if (tool and not re.fullmatch(_TOOL, tool)) or status not in ("new", "used", "dismissed", ""):
        return JSONResponse({"type": "error", "code": "bad_request", "message": "Bad filter."}, status_code=400)
    return await _forward("GET", "/reviews", {"tool": tool, "status": status})


@router.get("/reviews/summary", response_model=None)
async def reviews_summary(tool: str = "") -> JSONResponse:
    if tool and not re.fullmatch(_TOOL, tool):
        return JSONResponse({"type": "error", "code": "bad_request", "message": "That tool name is not valid."}, status_code=400)
    return await _forward("GET", "/reviews/summary", {"tool": tool} if tool else None)


@router.post("/reviews/{rid}/status", response_model=None)
async def review_status(rid: int, request: Request) -> JSONResponse:
    body = await request.body()
    return await _forward("POST", f"/reviews/{int(rid)}/status", body=body or b"{}")


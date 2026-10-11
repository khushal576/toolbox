"""
curl-builder/server.py

Serves the cURL Builder tool's single-page frontend AND, as of the
Run/Vault pass, one real backend route: `/execute`, which actually
issues the built HTTP request. See curl-builder/CLAUDE.md for why this
tool's original "no backend processing, intentionally" decision was
deliberately reversed (owner's explicit ask, not a silent addition) and
exactly what's bounded about it. Everything else — building/escaping the
copyable curl command string for bash/zsh, cmd.exe, PowerShell — still
runs entirely client-side; this route is the one and only place this
tool's backend ever touches the request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core.http_exec import DEFAULT_MAX_RESPONSE_BYTES, DEFAULT_TIMEOUT_S, execute_request
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.http_exec import DEFAULT_MAX_RESPONSE_BYTES, DEFAULT_TIMEOUT_S, execute_request

app = FastAPI(
    title="cURL Builder",
    description="Curl command generator — build it, copy it, or run it and see the real result.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


class HeaderPair(BaseModel):
    key: str
    value: str


class ExecuteRequest(BaseModel):
    method: str
    url: str
    headers: list[HeaderPair] = []
    body: Optional[str] = None  # already-encoded text body; None for no body
    timeout_s: float = DEFAULT_TIMEOUT_S


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))


@app.post("/execute")
async def execute(body: ExecuteRequest) -> JSONResponse:
    """Issue exactly one HTTP request and return the real result —
    status, headers, body, timing. Bounded by core.http_exec (timeout,
    response-size cap) — see that module's docstring for the full
    reasoning. Never raises on a target-side failure (connection error,
    timeout); those come back as a clean `error` field, not a 500."""
    body_bytes = body.body.encode("utf-8") if body.body is not None else None
    result = await execute_request(
        body.method,
        body.url,
        [(h.key, h.value) for h in body.headers],
        body_bytes,
        timeout_s=body.timeout_s,
        max_response_bytes=DEFAULT_MAX_RESPONSE_BYTES,
    )
    return JSONResponse({
        "status_code": result.status_code,
        "headers": result.headers,
        "body": result.body,
        "is_base64": result.is_base64,
        "truncated": result.truncated,
        "elapsed_ms": result.elapsed_ms,
        "error": result.error,
    })

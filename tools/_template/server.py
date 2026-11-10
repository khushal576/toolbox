"""
__TOOL_TITLE__ — server (created from tools/_template on __TOOL_DATE__).

Rules that keep a Toolbox tool correct (root CLAUDE.md has the full list):
  * expose an ASGI object called `app` — manifest `entry: __TOOL_PACKAGE__.server:app` points at it;
  * the page calls this API with RELATIVE paths (fetch('health'), never fetch('/health')) so it works under /tools/__TOOL_NAME__/;
  * no request may depend on something an earlier request left in this process's memory — use core/state/ for anything that must persist;
  * secrets only through `vault_store.scoped("__TOOL_NAME__")` and the `vault:` kinds the manifest declares.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="__TOOL_TITLE__")

UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> JSONResponse:
    """The smoke test calls this (tests/smoke/test___TOOL_PACKAGE__.py). Keep it cheap and free of outside systems."""
    return JSONResponse({"ok": True, "tool": "__TOOL_NAME__"})


class EchoRequest(BaseModel):
    text: str = ""


@app.post("/echo")
async def echo(body: EchoRequest) -> JSONResponse:
    """Example endpoint (delete it): validates the body with pydantic, answers JSON."""
    return JSONResponse({"ok": True, "echo": body.text, "length": len(body.text)})

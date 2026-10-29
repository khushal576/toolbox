"""
text-editor/server.py

Serves the Text Editor's single page and its one local JavaScript bundle (CodeMirror 6 + languages + lint +
merge view + js-beautify + sql-formatter + the ruff wasm loader, built by esbuild — see CLAUDE.md for the rebuild recipe). Everything else — editing,
regex search, validation, formatting, sorting, comparing — runs in the browser; no text is ever sent here.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

app = FastAPI(title="Text Editor", description="Client-side text editor: regex, multi-cursor, validate/format, compare.")

_UI = Path(__file__).resolve().parent / "ui"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    return HTMLResponse((_UI / "index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


@app.get("/vendor/editor-bundle.js", include_in_schema=False)
async def serve_bundle() -> FileResponse:
    """The one fixed bundle (not a static-files mount). The page asks for it with ?v=<version>, so it can be cached
    for a long time and a rebuilt bundle is fetched as soon as the page names a new version."""
    return FileResponse(_UI / "vendor" / "editor-bundle.js", media_type="text/javascript",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/vendor/ruff_fmt_bg.wasm", include_in_schema=False)
async def serve_ruff_wasm() -> FileResponse:
    """The Python formatter (ruff compiled to WebAssembly), fetched only when someone formats Python. Served as
    application/wasm so the browser can compile it while it downloads; the page asks for it with ?v=<version>."""
    return FileResponse(_UI / "vendor" / "ruff_fmt_bg.wasm", media_type="application/wasm",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

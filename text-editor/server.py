"""
text-editor/server.py

Serves the Text Editor's single page and its one local JavaScript bundle (CodeMirror 6 + languages + lint +
merge view + js-beautify + sql-formatter + the ruff wasm loader, built by esbuild — see CLAUDE.md for the rebuild recipe). Everything else — editing,
regex search, validation, formatting, sorting, comparing — runs in the browser; no text is ever sent here.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

app = FastAPI(title="Text Editor", description="Client-side text editor: regex, multi-cursor, validate/format, compare.")

_UI = Path(__file__).resolve().parent / "ui"
# the optional name-finding model for Mask → "Find names (AI)": downloaded by scripts/get-ner-model.sh into ./models/ner,
# mounted read-only at /models in rt-light. Served from here so the page never has to reach the internet.
_NER = Path(os.environ.get("TOOLBOX_MODELS_DIR", "/models")) / "ner"
_NER_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm", ".json": "application/json"}


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


@app.get("/ner/{path:path}", include_in_schema=False)
async def serve_ner(path: str) -> FileResponse:
    """transformers.js, its WebAssembly runtime and the name model (static files; the page loads them on demand)."""
    base = _NER.resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, "The name model is not installed — run scripts/get-ner-model.sh, then restart rt-light.")
    return FileResponse(f, media_type=_NER_TYPES.get(f.suffix.lower(), "application/octet-stream"),
                        headers={"Cache-Control": "public, max-age=86400"})

"""
vault/server.py

Management page for core/vault.py's shared encrypted secret store.
Deliberately minimal: list/delete/clear only. No add-new-secret form
here — this page doesn't know the shape of a "postgres_connection" vs.
an "ssh_credential," so creating a secret always happens from the tool
that uses it (sql-studio's "Save this connection" button, etc.) via
POST /secrets directly. See vault/CLAUDE.md for the full picture.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

try:  # core/ is a sibling top-level package in the real image (/app/core)
    from core import vault
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import vault

app = FastAPI(title="Vault")

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


class SaveSecretRequest(BaseModel):
    name: str
    kind: str
    data: dict


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(_UI_PATH.read_text())


@app.get("/secrets")
async def list_secrets(kind: str | None = None) -> JSONResponse:
    # Every call here goes through asyncio.to_thread — this whole
    # toolbox runs --workers 1 (one shared process for every tool), so a
    # blocking sqlite3 call directly on the event loop would stall every
    # other tool's requests too, not just this one (same reasoning
    # schema-map/project_store.py already documents).
    secrets = await asyncio.to_thread(vault.list_secrets, kind)
    return JSONResponse({"ok": True, "secrets": secrets})


@app.post("/secrets")
async def save_secret(body: SaveSecretRequest) -> JSONResponse:
    secret_id = await asyncio.to_thread(vault.save_secret, body.name, body.kind, body.data)
    return JSONResponse({"ok": True, "id": secret_id})


@app.get("/secrets/{secret_id}/reveal")
async def reveal_secret(secret_id: str) -> JSONResponse:
    """Decrypts and returns the real data — only ever called by a
    consuming tool's "load saved connection" action, never by this
    page's own list view."""
    try:
        data = await asyncio.to_thread(vault.get_secret, secret_id)
    except vault.SecretNotFound as exc:
        raise HTTPException(404, "No such saved secret") from exc
    return JSONResponse({"ok": True, "data": data})


DEFAULT_PREVIEW_MAX_ROWS = 2000


@app.get("/datasets/{secret_id}/preview")
async def preview_dataset(secret_id: str, max_rows: int = DEFAULT_PREVIEW_MAX_ROWS) -> JSONResponse:
    """For DataDiff Pro's "Load from Vault" button — the ONE place a
    vault dataset is allowed to flow into a browser textarea, and only
    up to max_rows. Anything bigger is refused outright (400), not
    truncated silently — see core.vault.preview_dataset_as_csv's own
    docstring for why the row-count check always runs before any row
    data is read."""
    try:
        csv_text, row_count = await asyncio.to_thread(vault.preview_dataset_as_csv, secret_id, max_rows)
    except vault.SecretNotFound as exc:
        raise HTTPException(404, "No such saved dataset") from exc
    except vault.DatasetTooLargeForPreview as exc:
        raise HTTPException(400, str(exc)) from exc
    return JSONResponse({"ok": True, "csv": csv_text, "row_count": row_count})


@app.delete("/secrets/{secret_id}")
async def delete_secret(secret_id: str) -> JSONResponse:
    await asyncio.to_thread(vault.delete_secret, secret_id)
    return JSONResponse({"ok": True})


@app.post("/clear")
async def clear_all() -> JSONResponse:
    await asyncio.to_thread(vault.clear_all)
    return JSONResponse({"ok": True})

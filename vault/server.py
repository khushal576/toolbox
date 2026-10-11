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
    from core.db.registry import get_dialect
    from core.postgres_conn import open_ssh_tunnel, scrub_password, ssh_tunnel_from_dict
except ImportError:  # standalone dev run from inside this folder: core/ is ../core
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import vault
    from core.db.registry import get_dialect
    from core.postgres_conn import open_ssh_tunnel, scrub_password, ssh_tunnel_from_dict

app = FastAPI(title="Vault")

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


class SaveSecretRequest(BaseModel):
    name: str
    kind: str
    data: dict


class TestConnectionRequest(BaseModel):
    host: str
    port: int
    database: str
    username: str
    password: str
    db_type: str = "postgres"
    ssh_tunnel: dict | None = None


def _test_connection_sync(body: TestConnectionRequest) -> None:
    """One-off, UNPOOLED connect + trivial query, through the SSH tunnel
    if one is configured, then everything is closed again. Nothing is
    stored. Same verify path SQL Studio's Connect uses (dialect.
    verify_connection), so "passes here" means "will connect there"."""
    dialect = get_dialect(body.db_type)
    tunnel = None
    host, port = body.host, body.port
    try:
        cfg = ssh_tunnel_from_dict(body.ssh_tunnel)
        if cfg is not None:
            tunnel = open_ssh_tunnel(cfg, remote_host=body.host, remote_port=body.port)
            host, port = "127.0.0.1", tunnel.local_bind_port
        conninfo = dialect.build_conninfo(host, port, body.database, body.username, body.password)
        dialect.verify_connection(conninfo, connect_timeout=10)
    finally:
        if tunnel is not None:
            try:
                tunnel.stop()
            except Exception:  # noqa: BLE001 - best-effort close
                pass


@app.post("/test-connection")
async def test_connection(body: TestConnectionRequest) -> JSONResponse:
    """Used by this page's "Add connection" form to check a connection
    BEFORE saving it. Always answers 200 with {ok: bool, error?} — a
    failed test is a normal result, not a server error."""
    try:
        await asyncio.to_thread(_test_connection_sync, body)
    except Exception as exc:  # noqa: BLE001 - each driver / ssh lib raises its own types
        return JSONResponse({"ok": False, "error": scrub_password(str(exc)) or exc.__class__.__name__})
    return JSONResponse({"ok": True})


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

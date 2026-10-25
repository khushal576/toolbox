"""
vault/server.py

Management page for core/vault.py's shared encrypted secret store.
Deliberately minimal: list/delete/clear, backup/restore, and (roadmap B7)
a token-guarded, scoped read API under /api/v1 for plugin code outside this process. No add-new-secret form
here — this page doesn't know the shape of a "postgres_connection" vs.
an "ssh_credential," so creating a secret always happens from the tool
that uses it (sql-studio's "Save this connection" button, etc.) via
POST /secrets directly. See vault/CLAUDE.md for the full picture.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

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


class TestSshRequest(BaseModel):
    host: str
    port: int = 22
    username: str
    auth: str = "password"
    password: str | None = None
    private_key: str | None = None
    passphrase: str | None = None
    host_key: dict | None = None


def _test_ssh_sync(body: TestSshRequest) -> dict:
    """Two steps, so no credential is ever sent to an unverified host: (1) with no host_key, fetch the
    server's key WITHOUT logging in and hand its fingerprint back for the user to confirm; (2) with the
    confirmed host_key, do a real login using that pinned key. Nothing is stored here."""
    from core import ssh_client

    if not body.host_key:
        return {"ok": False, "stage": "confirm", "host_key": ssh_client.probe_host_key(body.host, body.port)}
    data = body.model_dump()
    client = ssh_client.open_client(data)
    try:
        return {"ok": True, "banner": client.get_transport().remote_version}
    finally:
        client.close()


@app.post("/test-ssh-server")
async def test_ssh_server(body: TestSshRequest) -> JSONResponse:
    """Used by the "Add SSH server" form. Always answers 200: a failed test is a normal result."""
    try:
        return JSONResponse(await asyncio.to_thread(_test_ssh_sync, body))
    except Exception as exc:  # noqa: BLE001 — ssh_client maps its failures to plain messages
        return JSONResponse({"ok": False, "error": scrub_password(str(exc)) or exc.__class__.__name__})


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(_UI_PATH.read_text(), headers={"Cache-Control": "no-cache"})


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


# ---------------------------------------------------------------------
# Backup & restore — a real, portable, off-volume safety net. The
# vault_data Docker volume already survives an ordinary rebuild/restart
# (confirmed directly — see vault/CLAUDE.md), but not an explicit
# `docker-compose down -v` or a manual volume deletion. This is the
# answer to "is my data actually safe" beyond just trusting the volume.
# ---------------------------------------------------------------------

def _build_backup_zip_sync(dest_path: Path) -> None:
    """Every secret (still encrypted) + the key + every dataset blob in one zip — core.vault.export_backup."""
    vault.export_backup(dest_path)


@app.get("/backup")
async def backup() -> FileResponse:
    tmp_path = Path(tempfile.mkstemp(suffix=".zip")[1])
    await asyncio.to_thread(_build_backup_zip_sync, tmp_path)
    return FileResponse(
        tmp_path, filename="vault-backup.zip", media_type="application/zip",
        background=BackgroundTask(tmp_path.unlink, missing_ok=True),
    )


def _restore_backup_sync(zip_path: Path) -> dict:
    """Replace the whole vault with a backup (new format, or a pre-B7 vault.db zip). Since roadmap B7 the key
    comes from the environment, so secrets from a backup made with another key are RE-ENCRYPTED with the current
    one instead of swapping key files; a damaged backup is refused before anything is replaced."""
    return vault.import_backup(zip_path)


@app.post("/restore")
async def restore(file: UploadFile) -> JSONResponse:
    """Replaces the ENTIRE vault (every secret and dataset) with the
    contents of an uploaded backup zip. Streams the upload straight to a
    temp file (never buffers the whole thing in Python memory, same
    convention as duck-lab's own file uploads) before extracting."""
    tmp_path = Path(tempfile.mkstemp(suffix=".zip")[1])
    try:
        with tmp_path.open("wb") as out:
            await asyncio.to_thread(shutil.copyfileobj, file.file, out)
        result = await asyncio.to_thread(_restore_backup_sync, tmp_path)
    except (zipfile.BadZipFile, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return JSONResponse({"ok": True, **result})


# ---------------------------------------------------------------------
# Scoped read API (roadmap B7) — for plugin code running OUTSIDE this
# process (phase C runtimes). Each call names the plugin and carries its
# token (`python -m core.vault token <plugin>`, an HMAC of the Vault key);
# only the kinds the plugin's manifest `vault:` grants are visible. In-process
# tools use core.vault.scoped(<name>) with the same rules.
# ---------------------------------------------------------------------

def _scoped_from_headers(request: Request):
    plugin = request.headers.get("x-toolbox-plugin", "")
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if not vault.verify_token(plugin, token):
        raise HTTPException(401, "Unknown plugin or wrong token.")
    return vault.scoped(plugin)


@app.get("/api/v1/scope")
async def api_scope(request: Request) -> JSONResponse:
    sv = _scoped_from_headers(request)
    return JSONResponse(sv.scope.as_dict())


@app.get("/api/v1/secrets")
async def api_list(request: Request, kind: str) -> JSONResponse:
    sv = _scoped_from_headers(request)
    try:
        return JSONResponse({"secrets": await asyncio.to_thread(sv.list_secrets, kind)})
    except vault.ScopeError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.get("/api/v1/secrets/{secret_id}")
async def api_get(request: Request, secret_id: str) -> JSONResponse:
    sv = _scoped_from_headers(request)
    try:
        return JSONResponse({"data": await asyncio.to_thread(sv.get_secret, secret_id)})
    except vault.ScopeError as exc:
        raise HTTPException(403, str(exc)) from exc
    except vault.SecretNotFound as exc:
        raise HTTPException(404, "No such secret.") from exc


@app.get("/api/v1/health")
async def api_health() -> JSONResponse:
    """Key source + secret count (no secrets). Also reported in /api/state/health."""
    return JSONResponse(await asyncio.to_thread(vault.health))

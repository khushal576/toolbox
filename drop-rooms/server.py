"""
Drop Rooms: server (scaffolded from tools/_template on 2026-11-22; roadmap DR1).

Rooms with a key, devices that join with it, and text, files and folders that expire. The logic is in store.py; this file maps HTTP to it and
owns the three things that must live at the edge:
  * the DEVICE COOKIE (`dr_device`, HttpOnly, SameSite=Lax; only its SHA-256 is stored);
  * request-forgery protection: every non-GET request must carry the header `X-Drop-Rooms: 1` (a custom header cannot be sent
    cross-site without a CORS pre-flight, which this app never allows);
  * rate limits on joining (Redis, so every web worker shares them).
Rules that keep a Toolbox tool correct (root CLAUDE.md has the full list):
  * expose an ASGI object called `app`; the page uses RELATIVE paths; no request depends on this process's memory (rooms live in
    Postgres, limits in Redis); secrets only through `vault_store.scoped("drop-rooms")` (the room keys, kind `drop_room_key`).
Nothing here is logged except errors, and no response is ever cacheable.
"""

import asyncio
import importlib.util
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from core import vault as vault_store
from core.state.sqlstore import SqlStore

try:
    from drop_rooms import store
except ImportError:  # run from a checkout, where the folder is `drop-rooms/` (not an importable name): load the neighbour by path
    _spec = importlib.util.spec_from_file_location("drop_rooms_store", Path(__file__).with_name("store.py"))
    store = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = store
    _spec.loader.exec_module(store)

app = FastAPI(title="Drop Rooms")

UI_DIR = Path(__file__).resolve().parent / "ui"
UI_PATH = UI_DIR / "index.html"
SCRIPTS = ("app.js", "zip.js")                          # the only files under ui/ that are served
COOKIE = "dr_device"
CSRF_HEADER = "x-drop-rooms"

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "drop-rooms" / "drop_rooms.db"      # standalone SQLite only
STORE = SqlStore("drop_rooms", sqlite_path=DB_PATH, ddl=store.SCHEMA)
_vault = vault_store.scoped("drop-rooms")              # the Vault as this tool may see it: room keys only (manifest `vault:`)

# The page may only talk to this same site: a script that tried to send a message somewhere else would be blocked by the browser.
_CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
_NO_STORE = {"Cache-Control": "no-store"}


# ------------------------------------------------------------------------------------------------ plumbing

_init_lock = threading.Lock()
_initialised = False


def service() -> "store.DropRooms":
    """A service bound to the shared database. The tables are created once per process (idempotent), nothing else is kept."""
    global _initialised
    if not _initialised:
        with _init_lock:
            if not _initialised:
                STORE.init()
                _initialised = True
    return store.DropRooms(STORE, _vault)


class RedisLimiter:
    """hit(key, limit, window_s) -> True while under the limit. Shared by every web worker through Redis. Fails CLOSED: if the
    limiter cannot be reached, joining is refused rather than left unlimited."""

    def hit(self, key: str, limit: int, window: int) -> bool:
        from core.state import sessions

        r = sessions.client()
        k = "toolbox:drop_rooms:rl:" + key
        n = r.incr(k)
        if n == 1:
            r.expire(k, window)
        return n <= limit


def get_limiter() -> Any:
    return RedisLimiter()


class S3Files:
    """The file bytes live in Toolbox's S3 storage (core/state/objects, bucket prefix `drop-rooms/`, excluded from backups). Downloads stream
    THROUGH this tool (the S3 endpoint is internal), so every download is checked against the room, the expiry and the deletion state."""

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        from core.state import objects
        objects.put_file(key, fileobj, content_type)

    def delete(self, key: str) -> None:
        from core.state import objects
        objects.delete(key)

    def head(self, key: str, n: int) -> bytes:
        from core.state import objects
        return objects.client().get_object(Bucket=objects.ensure_bucket(), Key=key, Range=f"bytes=0-{n - 1}")["Body"].read()

    def stream(self, key: str):
        from core.state import objects
        body = objects.client().get_object(Bucket=objects.ensure_bucket(), Key=key)["Body"]
        try:
            yield from body.iter_chunks(1 << 20)
        finally:
            body.close()


def get_files() -> Any:
    return S3Files()


def _error(exc: Exception) -> JSONResponse:
    if isinstance(exc, store.DropError):
        body = {"ok": False, "detail": str(exc)}
        if isinstance(exc, store.Conflict) and exc.current is not None:
            body["current"] = exc.current
        return JSONResponse(body, status_code=exc.status)
    if isinstance(exc, _vault.ScopeError):
        return JSONResponse({"ok": False, "detail": "Drop Rooms is not allowed to do that in the Vault."}, status_code=403)
    if isinstance(exc, _vault.VaultKeyMismatch):
        return JSONResponse({"ok": False, "detail": "The Vault key does not match this data. Check TOOLBOX_VAULT_KEY in your .env (see the runbook)."}, status_code=503)
    raise exc


@app.middleware("http")
async def _guard(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != "1":
        return JSONResponse({"ok": False, "detail": "Missing the Drop Rooms request header."}, status_code=403, headers=_NO_STORE)
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


async def _api(request: Request, fn: Callable[["store.DropRooms", str], Any], create: bool = False):
    """Resolve the calling device from its cookie (creating one when `create`), run `fn(service, device_id)` off the event loop,
    and turn the answer or a DropError into JSON. A request with no known device is simply 'not a member of anything'."""
    token = request.cookies.get(COOKIE)
    fresh: dict[str, str] = {}

    def work():
        svc = service()
        svc.files = get_files()
        device = svc.device_for_token(token)
        if device is None and create:
            device, new_token = svc.new_device()
            fresh["token"] = new_token
        return fn(svc, device or "")

    try:
        result = await asyncio.to_thread(work)
        resp = JSONResponse({"ok": True, **(result or {})})
    except (store.DropError, _vault.ScopeError, _vault.VaultKeyMismatch) as exc:
        resp = _error(exc)
    if fresh:
        resp.set_cookie(COOKIE, fresh["token"], max_age=365 * 86400, httponly=True, samesite="lax", secure=_secure(request),
                        path=request.scope.get("root_path") or "/")
    return resp


def _limit(key: str, limit: int, window: int) -> None:
    try:
        ok = get_limiter().hit(key, limit, window)
    except Exception:                                   # noqa: BLE001 - fail closed
        raise store.TooMany("Joining is paused for a moment. Try again shortly.")
    if not ok:
        raise store.TooMany("Too many tries. Wait a few minutes and try again.")


# ------------------------------------------------------------------------------------------------ pages and scripts

@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    if not UI_PATH.exists():
        return HTMLResponse("<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"), headers={**_NO_STORE, "Content-Security-Policy": _CSP})


@app.get("/app.js", include_in_schema=False)
async def app_js() -> Response:
    path = UI_DIR / "app.js"
    if "app.js" not in SCRIPTS or not path.exists():
        return Response("not found", status_code=404)
    return FileResponse(path, media_type="application/javascript", headers=_NO_STORE)


@app.get("/zip.js", include_in_schema=False)
async def zip_js() -> Response:
    path = UI_DIR / "zip.js"
    if "zip.js" not in SCRIPTS or not path.exists():
        return Response("not found", status_code=404)
    return FileResponse(path, media_type="application/javascript", headers=_NO_STORE)


@app.get("/health")
async def health() -> JSONResponse:
    """The smoke test calls this (tests/smoke/test_drop_rooms.py). Keep it cheap and free of outside systems."""
    return JSONResponse({"ok": True, "tool": "drop-rooms"})


@app.get("/meta")
async def meta() -> JSONResponse:
    return JSONResponse({"ok": True, **store.meta()})


# ------------------------------------------------------------------------------------------------ bodies

class CreateRoom(BaseModel):
    name: str
    nickname: str
    default_retention: Optional[int] = None


class JoinBody(BaseModel):
    key: str
    nickname: str


class RoomPatch(BaseModel):
    name: Optional[str] = None
    default_retention: Optional[int] = None


class NickBody(BaseModel):
    nickname: str


class TextBody(BaseModel):
    text: str
    retention: Optional[int] = None


class EditBody(BaseModel):
    text: str
    version: int
    restart_retention: Optional[int] = None


class RetentionBody(BaseModel):
    seconds: int


# ------------------------------------------------------------------------------------------------ rooms

@app.get("/rooms")
async def list_rooms(request: Request):
    return await _api(request, lambda s, d: {"rooms": s.rooms(d)} if d else {"rooms": []}, create=True)


@app.post("/rooms")
async def create_room(request: Request, body: CreateRoom):
    def fn(s, d):
        _limit("create:" + d, 10, 3600)
        return {"room": s.create_room(d, body.name, body.nickname, body.default_retention)}
    return await _api(request, fn, create=True)


@app.post("/join")
async def join(request: Request, body: JoinBody):
    def fn(s, d):
        _limit("join:dev:" + d, 8, 600)                   # per device ...
        _limit("join:all", 300, 600)                      # ... and overall, so new cookies cannot be used to guess faster
        return {"room": s.join(d, body.key, body.nickname)}
    return await _api(request, fn, create=True)


@app.get("/rooms/{room_id}")
async def get_room(request: Request, room_id: str):
    return await _api(request, lambda s, d: {"room": s.room(d, room_id)})


@app.get("/rooms/{room_id}/key")
async def get_key(request: Request, room_id: str):
    return await _api(request, lambda s, d: {"key": s.invite_key(d, room_id)})


@app.put("/rooms/{room_id}")
async def patch_room(request: Request, room_id: str, body: RoomPatch):
    return await _api(request, lambda s, d: {"room": s.rename_room(d, room_id, body.name, body.default_retention)})


@app.put("/rooms/{room_id}/nickname")
async def set_nickname(request: Request, room_id: str, body: NickBody):
    return await _api(request, lambda s, d: {"room": s.set_nickname(d, room_id, body.nickname)})


@app.post("/rooms/{room_id}/reset-key")
async def reset_key(request: Request, room_id: str):
    return await _api(request, lambda s, d: {"key": s.reset_key(d, room_id)})


@app.post("/rooms/{room_id}/leave")
async def leave(request: Request, room_id: str):
    return await _api(request, lambda s, d: s.leave(d, room_id))


@app.delete("/rooms/{room_id}")
async def delete_room(request: Request, room_id: str):
    return await _api(request, lambda s, d: s.delete_room(d, room_id))


@app.delete("/rooms/{room_id}/members/{member_id}")
async def remove_member(request: Request, room_id: str, member_id: str):
    return await _api(request, lambda s, d: s.remove_member(d, room_id, member_id))


# ------------------------------------------------------------------------------------------------ items

@app.get("/rooms/{room_id}/items")
async def list_items(request: Request, room_id: str, rev: Optional[str] = None):
    return await _api(request, lambda s, d: s.items(d, room_id, rev))


@app.post("/rooms/{room_id}/items")
async def add_item(request: Request, room_id: str, body: TextBody):
    return await _api(request, lambda s, d: {"item": s.add_text(d, room_id, body.text, body.retention)})


@app.put("/rooms/{room_id}/items/{item_id}")
async def edit_item(request: Request, room_id: str, item_id: str, body: EditBody):
    return await _api(request, lambda s, d: {"item": s.edit_text(d, room_id, item_id, body.text, body.version, body.restart_retention)})


@app.post("/rooms/{room_id}/items/{item_id}/retention")
async def item_retention(request: Request, room_id: str, item_id: str, body: RetentionBody):
    return await _api(request, lambda s, d: {"item": s.set_retention(d, room_id, item_id, body.seconds)})


@app.delete("/rooms/{room_id}/items/{item_id}")
async def delete_item(request: Request, room_id: str, item_id: str):
    return await _api(request, lambda s, d: s.delete_item(d, room_id, item_id))


@app.post("/rooms/{room_id}/items/{item_id}/undo")
async def undo_item(request: Request, room_id: str, item_id: str):
    return await _api(request, lambda s, d: {"item": s.undo_delete(d, room_id, item_id)})


# ------------------------------------------------------------------------------------------------ files and folders (DR2)

def _in_thread(request: Request, fn: Callable[["store.DropRooms", str], Any]) -> Callable[[], Any]:
    token = request.cookies.get(COOKIE)

    def work():
        svc = service()
        svc.files = get_files()
        return fn(svc, svc.device_for_token(token) or "")
    return work


@app.put("/rooms/{room_id}/files")
async def upload_file(request: Request, room_id: str, name: str, kind: str = "file", retention: Optional[int] = None):
    """The request body IS the file (not multipart), so it can be counted and refused while it arrives. Membership and free space are checked
    BEFORE the body is read; the body goes to a temporary file, is checked again, and only then stored."""
    try:
        ticket = await asyncio.to_thread(_in_thread(request, lambda s, d: (d, s.upload_ticket(d, room_id))))
        device, info = ticket
        limit = info["max_bytes"]
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise store.TooLarge(f"That file is {store.human_size(int(declared))}; the most that can be uploaded here is {store.human_size(limit)}.")
        size = 0
        with tempfile.TemporaryFile() as tmp:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise store.TooLarge(f"That file is bigger than the {store.human_size(limit)} allowed here.")
                tmp.write(chunk)
            item = await asyncio.to_thread(_in_thread(request, lambda s, d: s.add_file(d, room_id, name, tmp, size, kind, retention)))
        return JSONResponse({"ok": True, "item": item})
    except (store.DropError, _vault.ScopeError, _vault.VaultKeyMismatch) as exc:
        return _error(exc)


_ASCII_BAD = re.compile(r"[^A-Za-z0-9._ -]")


def _file_headers(name: str, size: int, inline: bool) -> dict:
    ascii_name = _ASCII_BAD.sub("_", name) or "file"
    disp = f"{'inline' if inline else 'attachment'}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"
    return {"Content-Disposition": disp, "Content-Length": str(size), "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'", "Cross-Origin-Resource-Policy": "same-origin"}


async def _serve(request: Request, room_id: str, item_id: str, preview: bool):
    try:
        info = await asyncio.to_thread(_in_thread(request, lambda s, d: s.file_for_download(d, room_id, item_id, preview=preview)))
    except (store.DropError, _vault.ScopeError, _vault.VaultKeyMismatch) as exc:
        return _error(exc)
    # Downloads are ALWAYS opaque bytes the browser saves, never something it renders. Only a real image (checked by its first bytes when it was
    # uploaded) is shown inline, and even then inside a CSP sandbox.
    return StreamingResponse(iterate_in_threadpool(get_files().stream(info["key"])), media_type=info["mime"] if preview else "application/octet-stream",
                             headers=_file_headers(info["name"], info["size"], inline=preview))


@app.get("/rooms/{room_id}/files/{item_id}")
async def download_file(request: Request, room_id: str, item_id: str):
    return await _serve(request, room_id, item_id, preview=False)


@app.get("/rooms/{room_id}/files/{item_id}/preview")
async def preview_file(request: Request, room_id: str, item_id: str):
    return await _serve(request, room_id, item_id, preview=True)


@app.get("/rooms/{room_id}/files/{item_id}/text")
async def text_preview(request: Request, room_id: str, item_id: str):
    return await _api(request, lambda s, d: s.text_preview(d, room_id, item_id))

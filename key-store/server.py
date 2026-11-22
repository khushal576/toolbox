"""
Key Store: server (scaffolded from tools/_template on 2026-11-22).

KS1: serves the page and the password generator's scripts (the generator runs in the browser; nothing it makes reaches here).
KS2: the entries API. Entries are stored in the Vault through `vault_store.scoped("key-store")`, which this tool's manifest
limits to its own kind (`key_store`). The logic is in store.py; this file only maps HTTP to it.

Rules that keep a Toolbox tool correct (root CLAUDE.md has the full list):
  * expose an ASGI object called `app` — manifest `entry: key_store.server:app` points at it;
  * the page calls this API with RELATIVE paths (fetch('entries'), never fetch('/entries')) so it works under /tools/key-store/;
  * no request may depend on something an earlier request left in this process's memory — entries live in the Vault;
  * secrets only through `vault_store.scoped("key-store")` and the `vault:` kinds the manifest declares.
Values are never logged and never put in a URL; every response is `Cache-Control: no-store`.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from core import vault as vault_store

try:
    from key_store import store
except ImportError:  # run from a checkout, where the folder is `key-store/` (not an importable name): load the neighbour by path
    _spec = importlib.util.spec_from_file_location("key_store_store", Path(__file__).with_name("store.py"))
    store = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = store
    _spec.loader.exec_module(store)

app = FastAPI(title="Key Store")

UI_DIR = Path(__file__).resolve().parent / "ui"
UI_PATH = UI_DIR / "index.html"
SCRIPTS = ("keygen.js", "words.js", "generator.js", "store.js")     # the only files under ui/ that are served

# The page may only talk to this same site: a script that tried to send a password somewhere else would be blocked by the browser.
_CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'"
_NO_STORE = {"Cache-Control": "no-store"}


@app.middleware("http")
async def _never_cache(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


_vault = vault_store.scoped("key-store")     # the Vault as this tool may see it: its own kind only (manifest `vault:`)


def get_store() -> "store.KeyStore":
    return store.KeyStore(_vault)


async def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Vault calls block (database + decryption), so they run off the event loop; errors become plain messages."""
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except store.KeyStoreError as exc:
        return JSONResponse({"ok": False, "detail": str(exc)}, status_code=exc.status)
    except _vault.ScopeError:
        return JSONResponse({"ok": False, "detail": "Key Store is not allowed to do that in the Vault."}, status_code=403)
    except _vault.VaultKeyMismatch:
        return JSONResponse({"ok": False, "detail": "The Vault key does not match this data. Check TOOLBOX_VAULT_KEY in your .env (see the runbook)."},
                            status_code=503)


def _ok(**extra: Any) -> JSONResponse:
    return JSONResponse({"ok": True, **extra})


# ------------------------------------------------------------------------------------------------ pages and scripts

@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    if not UI_PATH.exists():
        return HTMLResponse("<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"), headers={**_NO_STORE, "Content-Security-Policy": _CSP})


def _script(name: str) -> Response:
    path = UI_DIR / name
    if name not in SCRIPTS or not path.exists():
        return Response("not found", status_code=404)
    return FileResponse(path, media_type="application/javascript", headers=_NO_STORE)


@app.get("/keygen.js", include_in_schema=False)
async def keygen_js() -> Response:
    return _script("keygen.js")


@app.get("/words.js", include_in_schema=False)
async def words_js() -> Response:
    return _script("words.js")


@app.get("/generator.js", include_in_schema=False)
async def generator_js() -> Response:
    return _script("generator.js")


@app.get("/store.js", include_in_schema=False)
async def store_js() -> Response:
    return _script("store.js")


@app.get("/health")
async def health() -> JSONResponse:
    """The smoke test calls this (tests/smoke/test_key_store.py). Keep it cheap and free of outside systems."""
    return JSONResponse({"ok": True, "tool": "key-store"})


# ------------------------------------------------------------------------------------------------ the entries API

class EntryIn(BaseModel):
    name: str
    value: str
    type: str = "password"
    tags: list[str] = []
    note: str = ""
    environment: str = ""
    pinned: bool = False


class EntryPatch(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None
    type: Optional[str] = None
    tags: Optional[list[str]] = None
    note: Optional[str] = None
    environment: Optional[str] = None
    pinned: Optional[bool] = None


@app.get("/meta")
async def meta() -> JSONResponse:
    return _ok(**store.meta())


@app.get("/entries")
async def list_entries(q: str = "", type: str = "", env: str = "", tag: str = "", in_values: bool = False,
                       trash: bool = False, sort: str = "name"):
    """Never returns a value. `in_values` lets the search match inside them (decrypted on the server, never sent)."""
    res = await _run(lambda: get_store().search(q, type, env, tag, in_values, trash, sort))
    return res if isinstance(res, JSONResponse) else _ok(**res)


@app.post("/entries")
async def create_entry(body: EntryIn):
    res = await _run(lambda: get_store().create(body.model_dump()))
    return res if isinstance(res, JSONResponse) else _ok(id=res)


@app.get("/entries/{entry_id}")
async def get_entry(entry_id: str):
    """One entry WITH its value: the edit form and the eye button."""
    res = await _run(lambda: get_store().get(entry_id))
    return res if isinstance(res, JSONResponse) else _ok(entry=res)


@app.put("/entries/{entry_id}")
async def update_entry(entry_id: str, body: EntryPatch):
    res = await _run(lambda: get_store().update(entry_id, body.model_dump(exclude_unset=True)))
    return res if isinstance(res, JSONResponse) else _ok()


@app.post("/entries/{entry_id}/copy")
async def copy_entry(entry_id: str):
    """The value for the clipboard (POST, so it is never prefetched or cached). Records "last used"."""
    res = await _run(lambda: get_store().copy(entry_id))
    return res if isinstance(res, JSONResponse) else _ok(value=res)


@app.post("/entries/{entry_id}/duplicate")
async def duplicate_entry(entry_id: str):
    res = await _run(lambda: get_store().duplicate(entry_id))
    return res if isinstance(res, JSONResponse) else _ok(id=res)


@app.delete("/entries/{entry_id}")
async def trash_entry(entry_id: str):
    """Moves to the trash (kept 30 days). Nothing is deleted for good here."""
    res = await _run(lambda: get_store().trash(entry_id))
    return res if isinstance(res, JSONResponse) else _ok()


@app.post("/entries/{entry_id}/restore")
async def restore_entry(entry_id: str):
    res = await _run(lambda: get_store().restore(entry_id))
    return res if isinstance(res, JSONResponse) else _ok(name=res)


@app.delete("/entries/{entry_id}/forever")
async def delete_forever(entry_id: str):
    res = await _run(lambda: get_store().delete_forever(entry_id))
    return res if isinstance(res, JSONResponse) else _ok()


@app.post("/trash/empty")
async def empty_trash():
    res = await _run(lambda: get_store().empty_trash())
    return res if isinstance(res, JSONResponse) else _ok(deleted=res)

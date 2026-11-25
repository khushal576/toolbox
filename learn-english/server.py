"""
Speak English — the owner's English fluency course (moved from the learn-english-fluency repo, 2026-11-24).

The course is a small engine page (`ui/index.html`) plus content files that the page loads on demand with <script> tags:
`modules/mNNN.js` (+ `modules/manifest.js`), `practice/hNNN.js` (Hindi sentences), `cheat/cNNN.js` (cheat sheets).
Progress (passed modules, boss scores, positions, the Tough list) is saved HERE, in Toolbox's database, so it survives
clearing the browser and Claude can check it with one request instead of reading Chrome's files.

Endpoints (the page uses relative paths):
  GET  /                       the page
  GET  /modules|practice|cheat/<file>.js   content files (names are checked; nothing else on disk is reachable)
  GET  /progress               {"state": {...}, "updated_at": ...}          header X-Speak-English: 1 required
  PUT  /progress               {"state": {...}} → merged state               header X-Speak-English: 1 required
  GET  /progress/summary       passed modules, next module, built modules     header required
  GET  /health
Merge rule (never lose progress, even from an old browser tab): passed = union, scores = max, last = max;
pos and the Tough list come from the newest save (the Tough list must allow removals).
The custom header makes every progress call a CORS "non-simple" request, so another website open in the browser cannot
read or overwrite it (Toolbox sends no CORS headers).
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from core.state.sqlstore import SqlStore

app = FastAPI(title="Speak English")

HERE = Path(__file__).resolve().parent
UI_PATH = HERE / "ui" / "index.html"
CONTENT = {"modules": re.compile(r"^(m\d{3}|manifest)\.js$"), "practice": re.compile(r"^h\d{3}\.js$"), "cheat": re.compile(r"^c\d{3}\.js$"),
           "daily": re.compile(r"^(d\d{3}|manifest)\.js$")}
HEADER = "x-speak-english"
MAX_BODY = 512 * 1024
TOUGH_ID = re.compile(r"^\d{1,4}:[a-z0-9]{1,13}$")
OWNER = "me"                                     # one learner: the Toolbox owner (Toolbox is bound to this computer)

DB_PATH = HERE.parent / "data" / "learn-english" / "progress.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS progress (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
STORE = SqlStore("learn_english", sqlite_path=DB_PATH, ddl=_SCHEMA)
_init_lock = threading.Lock()
_ready = False


def _store() -> SqlStore:
    """Create the table on first use (not at import: a database that is still starting must not break the page)."""
    global _ready
    if not _ready:
        with _init_lock:
            if not _ready:
                STORE.init()
                _ready = True
    return STORE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- state cleaning and merging
def clean(raw: object) -> dict:
    """Keep only the fields the course uses, with sane types. Anything else is dropped."""
    s = raw if isinstance(raw, dict) else {}
    out: dict = {"passed": {}, "scores": {}, "pos": {}, "last": 0, "tough": {}}
    for k, v in (s.get("passed") or {}).items() if isinstance(s.get("passed"), dict) else []:
        if str(k).isdigit() and v is True:
            out["passed"][str(int(k))] = True
    for k, v in (s.get("scores") or {}).items() if isinstance(s.get("scores"), dict) else []:
        if str(k).isdigit() and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1:
            out["scores"][str(int(k))] = float(v)
    for k, v in (s.get("pos") or {}).items() if isinstance(s.get("pos"), dict) else []:
        if str(k).isdigit() and isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 10_000:
            out["pos"][str(int(k))] = v
    last = s.get("last")
    if isinstance(last, (int, float)) and not isinstance(last, bool) and last >= 0:
        out["last"] = int(last)
    for k, v in (s.get("tough") or {}).items() if isinstance(s.get("tough"), dict) else []:
        if isinstance(k, str) and TOUGH_ID.match(k) and isinstance(v, dict):
            sv, nv = v.get("s", 0), v.get("n", 0)
            if all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 100_000 for x in (sv, nv)):
                out["tough"][k] = {"s": sv, "n": nv}
    return out


def merge(old: dict, new: dict) -> dict:
    """Never lose a pass or a better score; take positions and the Tough list from the newest save."""
    out = clean(new)
    old = clean(old)
    out["passed"] = {**old["passed"], **out["passed"]}
    for k, v in old["scores"].items():
        out["scores"][k] = max(v, out["scores"].get(k, 0.0))
    out["last"] = max(old["last"], out["last"])
    return out


def _read() -> tuple[dict, str | None]:
    with _store().connect() as con:
        row = con.execute("SELECT data, updated_at FROM progress WHERE id = ?", (OWNER,)).fetchone()
    if not row:
        return clean({}), None
    try:
        return clean(json.loads(row["data"])), row["updated_at"]
    except ValueError:
        return clean({}), row["updated_at"]


def _write(state: dict) -> str:
    now = _now()
    with _store().connect() as con:
        row = con.execute("SELECT data FROM progress WHERE id = ?", (OWNER,)).fetchone()
        merged = merge(json.loads(row["data"]) if row else {}, state)
        data = json.dumps(merged, separators=(",", ":"))
        if row:
            con.execute("UPDATE progress SET data = ?, updated_at = ? WHERE id = ?", (data, now, OWNER))
        else:
            con.execute("INSERT INTO progress (id, data, updated_at) VALUES (?, ?, ?)", (OWNER, data, now))
    return now


def _guard(request: Request) -> None:
    if request.headers.get(HEADER) != "1":
        raise HTTPException(403, "Missing X-Speak-English header.")


# ---------------------------------------------------------------- routes
@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(UI_PATH, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "tool": "learn-english"})


@app.get("/progress")
def get_progress(request: Request) -> JSONResponse:
    _guard(request)
    state, updated = _read()
    return JSONResponse({"state": state, "updated_at": updated}, headers={"Cache-Control": "no-store"})


@app.put("/progress")
async def put_progress(request: Request) -> JSONResponse:
    _guard(request)
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(413, "Progress data is too large.")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(400, "Body must be JSON.")
    if not isinstance(payload, dict) or not isinstance(payload.get("state"), dict):
        raise HTTPException(400, 'Body must be {"state": {...}}.')
    updated = _write(payload["state"])
    state, _ = _read()
    return JSONResponse({"state": state, "updated_at": updated}, headers={"Cache-Control": "no-store"})


@app.get("/progress/summary")
def progress_summary(request: Request) -> JSONResponse:
    """For Claude's progress check (see CLAUDE.md): which modules are passed and which is next."""
    _guard(request)
    state, updated = _read()
    built = _built_modules()
    passed = sorted(int(k) for k in state["passed"])
    nxt = next((m for m in built if m not in set(passed)), None)
    return JSONResponse({"passed": passed, "built": built, "next": nxt, "all_built_passed": nxt is None and bool(built),
                         "scores": {k: round(v, 2) for k, v in sorted(state["scores"].items(), key=lambda kv: int(kv[0]))},
                         "tough": len(state["tough"]), "updated_at": updated}, headers={"Cache-Control": "no-store"})


def _built_modules() -> list[int]:
    return sorted(int(p.stem[1:]) for p in (HERE / "modules").glob("m[0-9][0-9][0-9].js"))


# Declared LAST on purpose: this catch-all would otherwise capture /progress/summary.
@app.get("/{folder}/{name}", include_in_schema=False)
async def content(folder: str, name: str) -> FileResponse:
    rule = CONTENT.get(folder)
    if not rule or not rule.match(name) or not (HERE / folder / name).is_file():
        raise HTTPException(404, "Not found.")
    return FileResponse(HERE / folder / name, media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "no-cache"})

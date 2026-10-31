"""
sharepoint-lab/server.py

Serves the SharePoint Lists page and its API. Connections are Vault entries (kind `sharepoint_connection`); every other
identifier travels as a query parameter (`conn`, `site`, `list`) because SharePoint site ids contain commas.

Endpoints
---------
GET    /                          — the single-page UI
GET    /connections               — saved connections (no secrets) + staged-change counts
POST   /connections               — save one ({name, auth: client_secret|device_code, tenant_id, client_id, client_secret?, sites[], read_only, cloud})
PUT    /connections/{id}          — change its sites / read-only flag / client secret
POST   /connections/{id}/signin   — start a device-code sign-in → {flow, user_code, verification_uri, interval}
GET    /signin/{flow}             — poll it → {status: pending|slow_down|done|expired|declined}
GET    /connections/{id}/lists    — every saved site with its lists (?refresh=1 re-checks; per-site errors are reported, not raised)
GET    /schema?conn&site&list     — every column: type, internal vs display name, required/read-only/hidden/system, choices, editable + why not
GET    /items?conn&site&list&top&cursor — one page of items (cursor = the `next` of the previous page)
GET    /export.csv?conn&site&list — the whole list as CSV, streamed (header=display|internal)
GET    /staged?conn&site&list     — the REVIEW: every staged change with old → new, problems, and the digest to approve
PUT    /staged                    — stage / un-stage one cell {conn, site, list, item_id|row_id, field, old, new}
POST   /staged/bulk               — stage many (the Python helper) {conn, site, list, rows: [{item_id, fields, old?}]}
POST   /staged/discard            — throw away staged edits (a field, a row, or the whole list). Never touches SharePoint.
POST   /staged/rebase             — after a conflict: take SharePoint's current values as the "old" side
POST   /apply                     — write the reviewed changes {conn, site, list, digest} — refused when the digest is stale
GET    /audit?conn&list           — what was written, by whom/how, with the value SharePoint stored
There is no DELETE endpoint for SharePoint data, by design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

try:  # package import when mounted inside the toolbox (sharepoint_lab.*)
    from sharepoint_lab import auth, service, store
    from sharepoint_lab.graph import GraphError
except ImportError:  # flat import when run standalone from within this folder
    import auth
    import service
    import store
    from graph import GraphError

app = FastAPI(title="SharePoint Lists", description="Browse and edit SharePoint lists through Microsoft Graph, with a reviewed approval before anything is written.")
_UI = Path(__file__).resolve().parent / "ui"

store.init_db()


def _fail(exc: Exception) -> HTTPException:
    """Turn a service exception into an HTTP error with a plain-sentence detail."""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, service.StaleReview):
        return HTTPException(409, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(403, str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(404, str(exc.args[0]) if exc.args else "Not found.")
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    if isinstance(exc, auth.AuthError):
        return HTTPException(401, {"message": str(exc), "needs_signin": exc.needs_signin})
    if isinstance(exc, GraphError):
        code = {404: 404, 401: 403, 403: 403, 429: 429}.get(exc.status, 502)
        return HTTPException(code, str(exc))
    raise exc


@app.exception_handler(HTTPException)
async def _http_error(_request, exc: HTTPException) -> JSONResponse:
    d = exc.detail
    body = {"detail": d["message"], "needs_signin": d.get("needs_signin", False)} if isinstance(d, dict) else {"detail": d}
    return JSONResponse(body, status_code=exc.status_code)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    return HTMLResponse((_UI / "index.html").read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- connections
class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    auth: str
    tenant_id: str = ""      # optional for "sign in as me": then Microsoft's public sign-in app is used
    client_id: str = ""
    client_secret: Optional[str] = None
    cloud: str = "global"
    read_only: bool = False
    sites: list[str] = []
    authority_base: Optional[str] = None   # dev-only (TOOLBOX_SP_DEV=1)
    graph_base: Optional[str] = None


class ConnectionPatch(BaseModel):
    sites: Optional[list[str]] = None
    read_only: Optional[bool] = None
    client_secret: Optional[str] = None


@app.get("/connections")
async def connections() -> dict[str, Any]:
    try:
        conns = service.list_connections()
        for c in conns:
            n = store.staged_counts(c["id"])
            c["staged"] = sum(n.values())
        return {"connections": conns}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.post("/connections")
async def add_connection(body: ConnectionIn) -> dict[str, Any]:
    try:
        return service.create_connection(body.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.put("/connections/{conn_id}")
async def edit_connection(conn_id: str, body: ConnectionPatch) -> dict[str, Any]:
    try:
        return service.update_connection(conn_id, body.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.post("/connections/{conn_id}/signin")
async def signin(conn_id: str) -> dict[str, Any]:
    try:
        return await service.signin_start(conn_id)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.get("/signin/{flow}")
async def signin_status(flow: str) -> dict[str, Any]:
    try:
        return await service.signin_poll(flow)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.get("/connections/{conn_id}/lists")
async def lists(conn_id: str, refresh: bool = False) -> dict[str, Any]:
    try:
        sites = await service.lists_overview(conn_id, refresh=refresh)
        counts = store.staged_counts(conn_id)
        for o in sites:
            for l in o["lists"]:
                l["staged"] = counts.get((o["site"].get("id", ""), l["id"]), 0)
        return {"sites": sites}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


# ---------------------------------------------------------------- list data
@app.get("/schema")
async def schema(conn: str, site: str, list: str, refresh: bool = False) -> dict[str, Any]:
    try:
        c = service.open_conn(conn)
        return {"columns": await service.get_schema(c, site, list, refresh=refresh), "read_only": c.read_only}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.get("/items")
async def items(conn: str, site: str, list: str, top: int = Query(200, ge=1, le=999), cursor: Optional[str] = None) -> dict[str, Any]:
    try:
        return await service.get_items(service.open_conn(conn), site, list, top=top, cursor=cursor)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.get("/export.csv")
async def export(conn: str, site: str, list: str, header: str = "display") -> StreamingResponse:
    try:
        c = service.open_conn(conn)
        gen = service.export_csv(c, site, list, header="internal" if header == "internal" else "display")
        first = await gen.__anext__()   # surface auth/permission errors as a proper HTTP error, not a broken download
    except StopAsyncIteration:
        first, gen = "", None
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)

    async def body():
        yield first
        if gen is not None:
            async for chunk in gen:
                yield chunk

    return StreamingResponse(body(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="sharepoint-list.csv"'})


# ---------------------------------------------------------------- staging, review, apply
class CellIn(BaseModel):
    conn: str
    site: str
    list: str
    item_id: Optional[str] = None
    row_id: Optional[str] = None
    field: str
    old: Any = None
    new: Any = None


class BulkRow(BaseModel):
    item_id: str
    fields: dict[str, Any]
    old: Optional[dict[str, Any]] = None


class BulkIn(BaseModel):
    conn: str
    site: str
    list: str
    rows: list[BulkRow] = Field(max_length=5000)


class ListRef(BaseModel):
    conn: str
    site: str
    list: str


class DiscardIn(ListRef):
    row_id: Optional[str] = None
    field: Optional[str] = None


class ApplyIn(ListRef):
    digest: str


@app.get("/staged")
async def staged(conn: str, site: str, list: str) -> dict[str, Any]:
    try:
        return await service.review(conn, site, list)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.put("/staged")
async def stage(body: CellIn) -> dict[str, Any]:
    try:
        row = await service.stage_cell(body.conn, body.site, body.list, item_id=body.item_id, row_id=body.row_id,
                                       field=body.field, old=body.old, new=body.new)
        return {"row": row}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.post("/staged/bulk")
async def stage_many(body: BulkIn) -> dict[str, Any]:
    try:
        return await service.stage_bulk(body.conn, body.site, body.list, [r.model_dump() for r in body.rows])
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.post("/staged/discard")
async def discard(body: DiscardIn) -> dict[str, Any]:
    try:
        service.open_conn(body.conn)
        return {"discarded": service.discard(body.conn, body.site, body.list, row_id=body.row_id, field=body.field)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.post("/staged/rebase")
async def rebase(body: ListRef) -> dict[str, Any]:
    try:
        return await service.rebase(body.conn, body.site, body.list)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.post("/apply")
async def apply(body: ApplyIn) -> dict[str, Any]:
    try:
        return await service.apply(body.conn, body.site, body.list, body.digest)
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)


@app.get("/audit")
async def audit(conn: str, list: Optional[str] = None, limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    try:
        service.open_conn(conn)
        return {"entries": store.read_audit(conn, list, limit)}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc)

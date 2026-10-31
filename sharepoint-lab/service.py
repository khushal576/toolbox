"""
sharepoint-lab/service.py

The tool's logic, between the API (server.py) and Graph (graph.py). Everything that decides what may reach SharePoint is here:

  Connections    Vault entries of kind `sharepoint_connection` (secrets never leave this module — `public_view` is the only
                 shape the API returns).
  Browsing       sites → lists → columns → items, straight from Graph, schema cached for a couple of minutes.
  Staging        an edit (from the grid or from Python) is only WRITTEN TO OUR OWN DATABASE (`store.staged`): old and new
                 value per field. SharePoint is untouched.
  Review/apply   `review()` re-validates every staged change and returns a digest of exactly what it shows.
                 `apply()` refuses unless the caller sends that digest (what you approved is what is written), refuses on a
                 read-only connection, re-reads each item right before writing and SKIPS any row someone else changed since
                 it was staged (conflict), writes in batches, reads back what SharePoint stored, and audits every field.
                 It can update existing items and create new ones — there is no delete code path anywhere (graph.py also
                 blocks it).
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import time
import uuid
from typing import Any, AsyncIterator, Optional

import httpx

try:
    from sharepoint_lab import auth, columns, store
    from sharepoint_lab.graph import Graph, GraphError
except ImportError:  # flat import when run from this folder
    import auth
    import columns
    import store
    from graph import Graph, GraphError

try:
    from core import vault as vault_store
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core import vault as vault_store

KIND = auth.KIND
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None   # tests plug a fake Graph in here
_VAULT: Any = None
MAX_APPLY_ROWS = 500
SCHEMA_TTL = 120.0
LISTS_TTL = 120.0
EXPORT_MAX_ROWS = 500_000
_SCHEMAS: dict[tuple[str, str, str], tuple[float, list[dict[str, Any]]]] = {}
_LISTS: dict[str, tuple[float, list[dict[str, Any]]]] = {}


class StaleReview(RuntimeError):
    """The staged changes are not what the caller reviewed."""


def vault() -> Any:
    global _VAULT
    if _VAULT is None:
        _VAULT = vault_store.scoped("sharepoint")   # manifest.yaml `vault:` — only the sharepoint_connection kind
    return _VAULT


# ---------------------------------------------------------------- connections (Vault)
def public_view(secret_id: str, name: str, data: dict[str, Any]) -> dict[str, Any]:
    """The only shape of a connection that leaves the server: no secret, no refresh token."""
    return {"id": secret_id, "name": name, "auth": data.get("auth"), "tenant_id": data.get("tenant_id"),
            "client_id": data.get("client_id"), "cloud": data.get("cloud") or "global", "read_only": bool(data.get("read_only")),
            "sites": [{"url": s} for s in data.get("sites", [])],
            "signed_in": bool(data.get("refresh_token")) if data.get("auth") == "device_code" else True,
            "has_secret": bool(data.get("client_secret"))}


def list_connections() -> list[dict[str, Any]]:
    v, out = vault(), []
    for entry in v.list_secrets(KIND):
        try:
            out.append(public_view(entry["id"], entry["name"], v.get_secret(entry["id"])))
        except Exception as exc:  # noqa: BLE001 - one unreadable entry must not hide the others
            out.append({"id": entry["id"], "name": entry["name"], "error": type(exc).__name__})
    return out


def _sites_clean(sites: Any) -> list[str]:
    out = []
    for s in sites or []:
        u = (s.get("url") if isinstance(s, dict) else str(s)).strip()
        if u and u not in out:
            if not u.lower().startswith("https://"):
                raise ValueError(f"Site URLs must start with https:// — “{u[:60]}”.")
            out.append(u)
    return out


def create_connection(body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name", "")).strip()
    if not name:
        raise ValueError("Give the connection a name.")
    data = {"auth": body.get("auth"), "tenant_id": str(body.get("tenant_id", "")).strip(), "client_id": str(body.get("client_id", "")).strip(),
            "cloud": body.get("cloud") or "global", "read_only": bool(body.get("read_only")),
            "sites": _sites_clean(body.get("sites"))}
    if data["auth"] == "client_secret":
        data["client_secret"] = str(body.get("client_secret", "")).strip()
    elif data["auth"] == "device_code":   # no app registration needed: Microsoft's public sign-in app, any work/school tenant
        data["tenant_id"] = data["tenant_id"] or auth.PUBLIC_TENANT
        data["client_id"] = data["client_id"] or auth.PUBLIC_CLIENT_ID
    try:
        auth.validate(data)
    except auth.AuthError as exc:
        raise ValueError(str(exc)) from None
    for k in ("authority_base", "graph_base"):   # dev-only overrides (honoured only with TOOLBOX_SP_DEV=1)
        if body.get(k):
            data[k] = str(body[k])
    sid = vault().save_secret(name, KIND, data)
    return public_view(sid, name, data)


def update_connection(conn_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Change the site list or the read-only flag (and, if given, replace the client secret). The sign-in method, tenant
    and client id are fixed — add a new connection for those."""
    v = vault()
    data = v.get_secret(conn_id)
    if "sites" in body:
        data["sites"] = _sites_clean(body["sites"])
    if "read_only" in body:
        flipped = bool(body["read_only"]) != bool(data.get("read_only"))
        data["read_only"] = bool(body["read_only"])
        if flipped and data.get("auth") == "device_code":
            data["refresh_token"] = ""          # a different permission scope: sign in again
    if body.get("client_secret") and data.get("auth") == "client_secret":
        data["client_secret"] = str(body["client_secret"]).strip()
    v.update_secret(conn_id, data)
    auth.forget(conn_id)
    _LISTS.pop(conn_id, None)
    name = next((e["name"] for e in v.list_secrets(KIND) if e["id"] == conn_id), conn_id)
    return public_view(conn_id, name, data)


class Conn:
    def __init__(self, conn_id: str, data: dict[str, Any]):
        if "auth" not in data:
            raise KeyError("Not a SharePoint connection.")
        self.id, self.data = conn_id, data
        self.name = next((e["name"] for e in vault().list_secrets(KIND) if e["id"] == conn_id), conn_id)
        self.read_only = bool(data.get("read_only"))
        self.provider = auth.TokenProvider(conn_id, data, transport=TRANSPORT, save=lambda d: vault().update_secret(conn_id, d))

    @property
    def graph(self) -> Graph:
        return Graph(self.provider, auth.graph_base(self.data), transport=TRANSPORT)


def open_conn(conn_id: str) -> Conn:
    v = vault()
    try:
        return Conn(conn_id, v.get_secret(conn_id))
    except (v.SecretNotFound, v.ScopeError) as exc:   # unknown id, or an entry of another kind
        raise KeyError("No such SharePoint connection.") from exc


# ---------------------------------------------------------------- sign-in (device code)
class _Flows:
    """Pending device-code sign-ins. Redis when the Toolbox has it (any worker can answer the poll), else memory."""

    def __init__(self) -> None:
        self._mem: dict[str, dict[str, Any]] = {}
        self._redis = None

    def _store(self) -> Any:
        if self._redis is None:
            try:
                from core.state.sessions import SessionStore
                import os
                self._redis = SessionStore("sharepoint-signin", ttl_seconds=900) if os.environ.get("TOOLBOX_REDIS_URL") else False
            except Exception:  # noqa: BLE001
                self._redis = False
        return self._redis

    def set(self, flow: str, data: dict[str, Any]) -> None:
        s = self._store()
        s.set(flow, data) if s else self._mem.__setitem__(flow, data)

    def get(self, flow: str) -> Optional[dict[str, Any]]:
        s = self._store()
        return s.get(flow) if s else self._mem.get(flow)

    def delete(self, flow: str) -> None:
        s = self._store()
        s.delete(flow) if s else self._mem.pop(flow, None)


FLOWS = _Flows()


async def signin_start(conn_id: str) -> dict[str, Any]:
    conn = open_conn(conn_id)
    try:
        info = await auth.device_start(conn.data, transport=TRANSPORT)
    except auth.AuthError as exc:
        raise ValueError(str(exc)) from None
    flow = uuid.uuid4().hex
    FLOWS.set(flow, {"conn_id": conn_id, "device_code": info["device_code"], "expires_at": time.time() + info["expires_in"]})
    return {"flow": flow, "user_code": info["user_code"], "verification_uri": info["verification_uri"],
            "interval": info["interval"], "expires_in": info["expires_in"]}


async def signin_poll(flow: str) -> dict[str, Any]:
    f = FLOWS.get(flow)
    if not f:
        return {"status": "expired"}
    conn = open_conn(f["conn_id"])
    try:
        res = await auth.device_poll(conn.data, f["device_code"], transport=TRANSPORT)
    except auth.AuthError as exc:
        raise ValueError(str(exc)) from None
    if res["status"] == "done":
        data = dict(conn.data)
        data["refresh_token"] = res["refresh_token"]
        vault().update_secret(conn.id, data)
        auth.remember_access(conn.id, res["access_token"], res["expires_in"])
        FLOWS.delete(flow)
        return {"status": "done"}
    if res["status"] in ("expired", "declined"):
        FLOWS.delete(flow)
    return {"status": res["status"]}


# ---------------------------------------------------------------- browsing
async def lists_overview(conn_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
    """[{site: {url, id?, name?, error?}, lists: [...]}] for every site saved on the connection."""
    hit = _LISTS.get(conn_id)
    if hit and not refresh and hit[0] > time.time():
        return hit[1]
    conn = open_conn(conn_id)
    g = conn.graph

    async def one(url: str) -> dict[str, Any]:
        try:
            site = await g.resolve_site(url)
            return {"site": site, "lists": await g.lists(site["id"])}
        except (GraphError, auth.AuthError) as exc:
            return {"site": {"url": url, "error": str(exc), "needs_signin": bool(getattr(exc, "needs_signin", False))}, "lists": []}

    out = await asyncio.gather(*(one(u) for u in conn.data.get("sites", [])))
    if all("error" not in o["site"] for o in out):
        _LISTS[conn_id] = (time.time() + LISTS_TTL, list(out))
    return list(out)


async def get_schema(conn: Conn, site_id: str, list_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
    key = (conn.id, site_id, list_id)
    hit = _SCHEMAS.get(key)
    if hit and not refresh and hit[0] > time.time():
        return hit[1]
    descs = columns.describe_all(await conn.graph.columns(site_id, list_id))
    _SCHEMAS[key] = (time.time() + SCHEMA_TTL, descs)
    return descs


async def get_items(conn: Conn, site_id: str, list_id: str, *, top: int, cursor: Optional[str]) -> dict[str, Any]:
    return await conn.graph.items(site_id, list_id, top=top, cursor=cursor)


async def export_csv(conn: Conn, site_id: str, list_id: str, *, header: str = "display") -> AsyncIterator[str]:
    descs = [d for d in await get_schema(conn, site_id, list_id) if not d["hidden"] and not d["system"] or d["name"] in ("ID", "Created", "Modified")]
    cols = [{"name": "id", "display": "ID", "key": "id"}] + [{"name": d["name"], "display": d["display"], "key": d["key"]} for d in descs if d["name"] not in ("ID", "Id")]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c["name"] if header == "internal" else c["display"] for c in cols])
    yield buf.getvalue()
    n, cursor = 0, None
    while n < EXPORT_MAX_ROWS:
        page = await conn.graph.items(site_id, list_id, top=500, cursor=cursor)
        buf.seek(0), buf.truncate()
        for it in page["items"]:
            w.writerow([it["id"] if c["key"] == "id" else _cell(it["fields"].get(c["key"])) for c in cols])
            n += 1
        yield buf.getvalue()
        cursor = page["next"]
        if not cursor:
            return


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "; ".join(_cell(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


# ---------------------------------------------------------------- staging (our database only)
def _by_name(descs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d["name"]: d for d in descs}


def _clean(d: dict[str, Any], value: Any) -> Any:
    return columns.normalize_current(d, value)


async def stage_cell(conn_id: str, site_id: str, list_id: str, *, item_id: Optional[str], row_id: Optional[str], field: str,
                     old: Any, new: Any, source: str = "ui") -> dict[str, Any]:
    """Stage (or un-stage) ONE cell. Returns the staged row afterwards ({"id": …, "changes": {}} once nothing is left)."""
    conn = open_conn(conn_id)
    if conn.read_only:
        raise PermissionError("This connection is read-only.")
    descs = _by_name(await get_schema(conn, site_id, list_id))
    d = descs.get(field)
    if d is None:
        raise ValueError(f"The list has no column “{field}”.")
    value = columns.coerce(d, new)            # ValueError → the grid shows the sentence under the cell
    if row_id:
        row = store.get_row(row_id)
        if not row or (row["conn_id"], row["site_id"], row["list_id"]) != (conn_id, site_id, list_id):
            raise KeyError("That staged row no longer exists.")
    elif item_id:
        row = store.find_update_row(conn_id, site_id, list_id, str(item_id))
    else:
        row = None
    if row is None:
        row = {"id": "", "conn_id": conn_id, "site_id": site_id, "list_id": list_id, "op": "update" if item_id else "create",
               "item_id": str(item_id) if item_id else None, "changes": {}, "source": source}
        if store.count_for_list(conn_id, site_id, list_id) >= store.MAX_STAGED_PER_LIST:
            raise ValueError(f"Too many staged rows for this list (limit {store.MAX_STAGED_PER_LIST}) — apply or discard some first.")
    is_create = row["op"] == "create"
    before = None if is_create else _clean(d, old)
    if not is_create and columns.same(d, before, value):
        row["changes"].pop(field, None)       # edited back to the original: nothing to send
    else:
        row["changes"][field] = {"old": before, "new": value}
    return store.save_row(row)


async def stage_bulk(conn_id: str, site_id: str, list_id: str, rows: list[dict[str, Any]], source: str = "python") -> dict[str, Any]:
    """Stage many items at once (the Python helper). rows: [{"item_id": "12", "fields": {col: new}, "old": {col: old}?}].
    A column without an `old` is read from SharePoint now. Returns counts and per-row problems; one bad cell never
    blocks the rest."""
    conn = open_conn(conn_id)
    if conn.read_only:
        raise PermissionError("This connection is read-only.")
    descs = _by_name(await get_schema(conn, site_id, list_id))
    need = [r for r in rows if r.get("item_id") and any(f not in (r.get("old") or {}) for f in r["fields"])]
    live = await _fetch_live(conn, site_id, list_id, need, descs) if need else {}
    staged = skipped = 0
    problems: list[dict[str, Any]] = []
    for r in rows:
        item_id = str(r["item_id"]) if r.get("item_id") else None
        for field, new in r["fields"].items():
            d = descs.get(field)
            try:
                if d is None:
                    raise ValueError(f"The list has no column “{field}”.")
                if item_id is None:
                    raise ValueError("New rows are staged one cell at a time from the page.")
                cur = live.get(item_id, {})
                if cur is None:
                    raise ValueError("The item does not exist.")
                old = (r.get("old") or {}).get(field, cur.get(d["key"]))
                res = await stage_cell(conn_id, site_id, list_id, item_id=item_id, row_id=None, field=field, old=old, new=new, source=source)
                if field in res["changes"]:
                    staged += 1
                else:
                    skipped += 1
            except (ValueError, PermissionError) as exc:
                problems.append({"item_id": item_id, "field": field, "error": str(exc)})
    return {"staged": staged, "unchanged": skipped, "problems": problems[:200], "problem_count": len(problems)}


def discard(conn_id: str, site_id: str, list_id: str, *, row_id: Optional[str] = None, field: Optional[str] = None) -> int:
    """Throw away staged edits (never sent). A field, a row, or — with neither — everything staged for the list."""
    if row_id:
        row = store.get_row(row_id)
        if not row or (row["conn_id"], row["site_id"], row["list_id"]) != (conn_id, site_id, list_id):
            return 0
        if field:
            row["changes"].pop(field, None)
            store.save_row(row)
        else:
            store.delete_rows([row_id])
        return 1
    return store.discard_list(conn_id, site_id, list_id)


# ---------------------------------------------------------------- review
def _digest(rows: list[dict[str, Any]]) -> str:
    canon = [[r["id"], r["op"], r["item_id"], sorted([f["field"], f["old"], f["new"]] for f in r["fields"])] for r in rows]
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:24]


def _review_rows(conn_id: str, site_id: str, list_id: str, descs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in store.staged_rows(conn_id, site_id, list_id):
        fields, errors = [], []
        for name, ch in r["changes"].items():
            d = descs.get(name)
            err = None
            if d is None:
                err = "The column no longer exists."
            else:
                try:
                    columns.coerce(d, ch["new"])
                except ValueError as exc:
                    err = str(exc)
            fields.append({"field": name, "display": d["display"] if d else name, "kind": d["kind"] if d else "?",
                           "old": ch["old"], "new": ch["new"], "error": err})
        if r["op"] == "create":
            have = set(r["changes"])
            for d in descs.values():
                if d["required"] and d["editable"] and d["name"] not in have and d["default"] is None:
                    errors.append(f"“{d['display']}” is required for a new item.")
                elif d["required"] and not d["editable"] and not d["system"] and d["name"] not in have and d["default"] is None:
                    errors.append(f"“{d['display']}” is required but can't be set from here.")
        out.append({"id": r["id"], "op": r["op"], "item_id": r["item_id"], "source": r["source"], "fields": fields, "errors": errors,
                    "created_at": r["created_at"]})
    return out


async def review(conn_id: str, site_id: str, list_id: str) -> dict[str, Any]:
    conn = open_conn(conn_id)
    descs = _by_name(await get_schema(conn, site_id, list_id))
    rows = _review_rows(conn_id, site_id, list_id, descs)
    n_fields = sum(len(r["fields"]) for r in rows)
    bad = sum(1 for r in rows if r["errors"] or any(f["error"] for f in r["fields"]))
    return {"rows": rows, "digest": _digest(rows), "counts": {"rows": len(rows), "fields": n_fields, "invalid_rows": bad,
                                                              "creates": sum(1 for r in rows if r["op"] == "create")},
            "read_only": conn.read_only, "connection": conn.name}


async def _fetch_live(conn: Conn, site_id: str, list_id: str, rows: list[dict[str, Any]], descs: dict[str, dict[str, Any]]) -> dict[str, Optional[dict[str, Any]]]:
    """item id → its current fields (only the touched columns), None if the item is gone."""
    reqs = []
    for r in rows:
        names = list(r["fields"]) if isinstance(r["fields"], dict) else [f["field"] for f in r["fields"]]
        keys = sorted({descs[n]["key"] for n in names if n in descs})
        reqs.append({"id": str(r["item_id"]), "method": "GET",
                     "url": conn.graph.item_path(site_id, list_id, str(r["item_id"])) + "?$expand=fields($select=" + ",".join(["id"] + keys) + ")"})
    res = await conn.graph.batch(reqs) if reqs else {}
    out: dict[str, Optional[dict[str, Any]]] = {}
    for r in reqs:
        x = res.get(r["id"])
        if x and x["status"] == 200 and x["body"]:
            out[r["id"]] = x["body"].get("fields") or {}
        else:
            out[r["id"]] = None
    return out


async def apply(conn_id: str, site_id: str, list_id: str, digest: str) -> dict[str, Any]:
    conn = open_conn(conn_id)
    if conn.read_only:
        raise PermissionError("This connection is read-only — nothing was written.")
    descs = _by_name(await get_schema(conn, site_id, list_id))
    rows = _review_rows(conn_id, site_id, list_id, descs)
    if digest != _digest(rows):
        raise StaleReview("The staged changes are not what you reviewed (something changed) — open the review again.")
    list_name = next((l["name"] for o in (_LISTS.get(conn_id, (0, []))[1]) for l in o["lists"] if l["id"] == list_id), list_id)
    results: dict[str, dict[str, Any]] = {}
    todo: list[dict[str, Any]] = []
    for r in rows:
        problems = r["errors"] + [f"{f['display']}: {f['error']}" for f in r["fields"] if f["error"]]
        if problems:
            results[r["id"]] = {"row_id": r["id"], "op": r["op"], "item_id": r["item_id"], "outcome": "invalid", "message": " ".join(problems), "fields": r["fields"]}
        else:
            todo.append(r)
    if len(todo) > MAX_APPLY_ROWS:
        raise ValueError(f"Apply at most {MAX_APPLY_ROWS} rows at a time — discard or apply some first.")

    # 1. look at the items as they are NOW; skip rows somebody else changed since staging
    updates = [r for r in todo if r["op"] == "update"]
    live = await _fetch_live(conn, site_id, list_id, updates, descs) if updates else {}
    writes: list[dict[str, Any]] = []
    for r in todo:
        if r["op"] == "create":
            body = {}
            for f in r["fields"]:
                body.update(columns.payload(descs[f["field"]], columns.coerce(descs[f["field"]], f["new"])))
            writes.append({"id": r["id"], "method": "POST", "url": conn.graph.item_path(site_id, list_id), "body": {"fields": body}, "row": r})
            continue
        cur = live.get(str(r["item_id"]))
        if cur is None:
            results[r["id"]] = {"row_id": r["id"], "op": "update", "item_id": r["item_id"], "outcome": "failed",
                                "message": "The item no longer exists in SharePoint.", "fields": r["fields"]}
            continue
        conflict, body, noop = [], {}, 0
        for f in r["fields"]:
            d = descs[f["field"]]
            now = columns.normalize_current(d, cur.get(d["key"]))
            f["live"] = now
            if columns.same(d, now, f["new"]):
                noop += 1
            elif not columns.same(d, now, f["old"]):
                conflict.append(f["display"])
            else:
                body.update(columns.payload(d, columns.coerce(d, f["new"])))
        if conflict:
            results[r["id"]] = {"row_id": r["id"], "op": "update", "item_id": r["item_id"], "outcome": "conflict", "fields": r["fields"],
                                "message": "Changed in SharePoint since you edited it: " + ", ".join(conflict) + "."}
        elif not body:
            results[r["id"]] = {"row_id": r["id"], "op": "update", "item_id": r["item_id"], "outcome": "unchanged", "fields": r["fields"],
                                "message": "SharePoint already has these values."}
        else:
            writes.append({"id": r["id"], "method": "PATCH", "url": conn.graph.item_path(site_id, list_id, str(r["item_id"])) + "/fields",
                           "body": body, "row": r})

    # 2. write (≤ 20 per round trip), read back what SharePoint stored
    sent = await conn.graph.batch([{k: v for k, v in w.items() if k != "row"} for w in writes]) if writes else {}
    for w in writes:
        r, x = w["row"], sent.get(w["id"], {"status": 0, "body": None})
        if 200 <= x["status"] < 300:
            body = x["body"] or {}
            stored = body.get("fields") if r["op"] == "create" else body
            stored = stored or {}
            note = []
            for f in r["fields"]:
                d = descs[f["field"]]
                f["stored"] = columns.normalize_current(d, stored.get(d["key"]))
                if f["stored"] is not None and not columns.same(d, f["stored"], f["new"]):
                    note.append(f["display"])
            results[r["id"]] = {"row_id": r["id"], "op": r["op"], "item_id": str(body.get("id") or r["item_id"] or ""), "outcome": "applied",
                                "fields": r["fields"], "message": ("SharePoint stored a different value for: " + ", ".join(note) + ".") if note else ""}
        else:
            msg = ((x["body"] or {}).get("error") or {}).get("message", "") if isinstance(x["body"], dict) else ""
            results[r["id"]] = {"row_id": r["id"], "op": r["op"], "item_id": r["item_id"], "outcome": "failed", "fields": r["fields"],
                                "message": (msg.split("\n")[0] or f"SharePoint answered {x['status']}.")[:300]}

    # 3. audit every field, and un-stage what is finished (conflicts and failures stay for another look)
    audit, done = [], []
    for r in rows:
        res = results.get(r["id"])
        if not res:
            continue
        for f in res["fields"]:
            audit.append({"conn_id": conn_id, "conn_name": conn.name, "site_id": site_id, "list_id": list_id, "list_name": list_name,
                          "op": r["op"], "item_id": res["item_id"], "field": f["field"], "old": f["old"], "new": f["new"],
                          "stored": f.get("stored"), "source": r["source"], "outcome": res["outcome"], "detail": res["message"]})
        if res["outcome"] in ("applied", "unchanged"):
            done.append(r["id"])
    store.write_audit(audit)
    store.delete_rows(done)
    ordered = [results[r["id"]] for r in rows if r["id"] in results]
    tally = {k: sum(1 for x in ordered if x["outcome"] == k) for k in ("applied", "conflict", "failed", "unchanged", "invalid")}
    return {"results": ordered, **tally, "fields_written": sum(len(x["fields"]) for x in ordered if x["outcome"] == "applied")}


async def rebase(conn_id: str, site_id: str, list_id: str) -> dict[str, Any]:
    """After a conflict: re-read the items and take SharePoint's current value as the 'old' side of each staged change (the
    new values stay). A change SharePoint already matches is dropped."""
    conn = open_conn(conn_id)
    descs = _by_name(await get_schema(conn, site_id, list_id))
    rows = [r for r in store.staged_rows(conn_id, site_id, list_id) if r["op"] == "update"]
    live = await _fetch_live(conn, site_id, list_id, [{"item_id": r["item_id"], "fields": r["changes"]} for r in rows], descs) if rows else {}
    updated = dropped = 0
    for r in rows:
        cur = live.get(str(r["item_id"]))
        if cur is None:
            continue
        for name, ch in list(r["changes"].items()):
            d = descs.get(name)
            if not d:
                continue
            now = columns.normalize_current(d, cur.get(d["key"]))
            if columns.same(d, now, ch["new"]):
                del r["changes"][name]
                dropped += 1
            elif not columns.same(d, now, ch["old"]):
                ch["old"] = now
                updated += 1
        store.save_row(r)
    return {"refreshed": updated, "dropped": dropped}

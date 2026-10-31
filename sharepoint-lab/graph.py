"""
sharepoint-lab/graph.py

A small Microsoft Graph client for SharePoint lists — only what this tool needs, and deliberately less than Graph can do.

    graph = Graph(provider, graph_base)
    site  = await graph.resolve_site("https://contoso.sharepoint.com/sites/Team")
    for lst in await graph.lists(site["id"]): ...
    page  = await graph.items(site_id, list_id, top=200)          # {"items": [...], "next": cursor|None}
    res   = await graph.batch([...])                              # ≤ 20 sub-requests per round trip

Safety by construction (owner decision: NO destructive operations):
  * the client has no delete method, and `_check_write` refuses every request that is not
      GET · PATCH …/items/{id}/fields · POST …/items · POST /$batch (whose sub-requests are checked the same way)
    so a bug or a crafted payload cannot delete an item, a list or a column;
  * a paging cursor (`@odata.nextLink`) is only followed when it points at the same Graph host;
  * errors become plain sentences (`GraphError`) — never a token, never a raw response body;
  * 429/503/504 are retried with Retry-After (bounded), a 401 refreshes the token once.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator, Optional
from urllib.parse import quote, urlparse

import httpx

try:
    from sharepoint_lab.auth import AuthError, TokenProvider
except ImportError:  # flat import when run from this folder
    from auth import AuthError, TokenProvider

TIMEOUT = httpx.Timeout(60.0, connect=10.0)
MAX_ATTEMPTS = 4
MAX_WAIT = 30.0
BATCH_MAX = 20
SLEEP = asyncio.sleep   # replaced in tests

_ITEM_FIELDS = re.compile(r"^/sites/[^/?#]+/lists/[^/?#]+/items/[^/?#]+/fields$")
_ITEMS = re.compile(r"^/sites/[^/?#]+/lists/[^/?#]+/items$")


class GraphError(RuntimeError):
    """A Graph call failed. `status` is the HTTP status (0 = could not reach Graph), `code` Graph's error code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _plain(resp: httpx.Response) -> GraphError:
    try:
        err = resp.json().get("error", {})
    except (ValueError, AttributeError):
        err = {}
    code = str(err.get("code") or resp.status_code)
    msg = str(err.get("message") or "").split("\n")[0].strip()
    hint = {401: "Microsoft refused the sign-in token.",
            403: "Not allowed — the account/app has no access to this site or list (for an app: grant it the site with Sites.Selected).",
            404: "Not found — check the site URL and the list; it may also be hidden from this account.",
            423: "The item is locked.", 429: "Microsoft is throttling requests — try again in a moment."}.get(resp.status_code, "")
    text = msg or hint or f"Microsoft Graph returned {resp.status_code}."
    if hint and msg and resp.status_code in (401, 403, 404):
        text = f"{hint} ({msg})"
    return GraphError(resp.status_code, code, text)


def _check_write(method: str, path: str) -> None:
    """Raise unless this is one of the three write shapes the tool is allowed to send. `path` is relative to the base."""
    p = path.split("?", 1)[0]
    if method == "GET":
        return
    if method == "PATCH" and _ITEM_FIELDS.match(p):
        return
    if method == "POST" and (p == "/$batch" or _ITEMS.match(p)):
        return
    raise GraphError(0, "blocked", f"This tool never sends {method} {p.split('/')[-1] or '/'} to SharePoint.")


def _seg(value: str) -> str:
    return quote(str(value), safe=",")


class Graph:
    def __init__(self, provider: TokenProvider, base: str, *, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.provider, self.base, self.transport = provider, base.rstrip("/"), transport
        self._origin = "{0.scheme}://{0.netloc}".format(urlparse(self.base))

    # ---------------------------------------------------------------- plumbing
    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("/"):
            return self.base + path_or_url
        if path_or_url.startswith(self._origin + "/"):
            return path_or_url
        raise GraphError(0, "blocked", "Refusing to follow a link that is not on the Microsoft Graph host.")

    def _rel(self, url: str) -> str:
        return url[len(self.base):] if url.startswith(self.base) else "/" + url.split("/", 3)[-1]

    async def request(self, method: str, path_or_url: str, *, params: Optional[dict] = None, json: Any = None,
                      headers: Optional[dict] = None) -> Any:
        url = self._url(path_or_url)
        _check_write(method, self._rel(url))
        refreshed = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            token = await self.provider.token()
            hdrs = {"Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {})}
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT, transport=self.transport) as client:
                    resp = await client.request(method, url, params=params, json=json, headers=hdrs)
            except httpx.HTTPError as exc:
                if attempt < MAX_ATTEMPTS:
                    await SLEEP(min(2 ** attempt, MAX_WAIT))
                    continue
                raise GraphError(0, "unreachable", f"Could not reach Microsoft Graph ({type(exc).__name__}).") from exc
            if resp.status_code == 401 and not refreshed:
                refreshed = True
                await self.provider.token(force=True)
                continue
            if resp.status_code in (429, 503, 504) and attempt < MAX_ATTEMPTS:
                await SLEEP(_retry_after(resp, attempt))
                continue
            if resp.status_code >= 400:
                raise _plain(resp)
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()
        raise GraphError(0, "unreachable", "Microsoft Graph did not answer.")  # pragma: no cover

    async def pages(self, path: str, params: Optional[dict] = None, *, max_pages: int = 1000) -> AsyncIterator[list[dict]]:
        """Every page of a collection, following @odata.nextLink (same host only)."""
        data = await self.request("GET", path, params=params)
        for _ in range(max_pages):
            yield data.get("value", [])
            nxt = data.get("@odata.nextLink")
            if not nxt:
                return
            data = await self.request("GET", nxt)

    async def batch(self, requests: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Run sub-requests ([{id, method, url, body?}], url relative like "/sites/…") in batches of 20.
        Returns {id: {"status": int, "body": dict|None, "retry_after": float}}. Throttled sub-requests (429/503) are
        retried a few times after the longest Retry-After."""
        for r in requests:
            _check_write(r["method"], r["url"])
        out: dict[str, dict[str, Any]] = {}
        pending = list(requests)
        for round_ in range(MAX_ATTEMPTS):
            retry: list[dict[str, Any]] = []
            wait = 0.0
            for i in range(0, len(pending), BATCH_MAX):
                chunk = pending[i:i + BATCH_MAX]
                payload = {"requests": [{"id": r["id"], "method": r["method"], "url": r["url"],
                                         **({"body": r["body"], "headers": {"Content-Type": "application/json"}} if "body" in r else {})}
                                        for r in chunk]}
                data = await self.request("POST", "/$batch", json=payload)
                by_id = {x["id"]: x for x in (data or {}).get("responses", [])}
                for r in chunk:
                    x = by_id.get(r["id"])
                    if x is None:
                        out[r["id"]] = {"status": 0, "body": None, "retry_after": 0.0}
                        continue
                    ra = float((x.get("headers") or {}).get("Retry-After", 0) or 0)
                    if x["status"] in (429, 503, 504) and round_ < MAX_ATTEMPTS - 1:
                        retry.append(r)
                        wait = max(wait, ra or 2.0)
                    else:
                        out[r["id"]] = {"status": int(x["status"]), "body": x.get("body"), "retry_after": ra}
            if not retry:
                break
            await SLEEP(min(wait, MAX_WAIT))
            pending = retry
        return out

    # ---------------------------------------------------------------- sites / lists / columns / items
    async def resolve_site(self, url: str) -> dict[str, Any]:
        u = urlparse(url.strip())
        if u.scheme != "https" or not u.hostname:
            raise GraphError(0, "bad_url", "A site URL looks like https://contoso.sharepoint.com/sites/Team")
        parts = [p for p in u.path.split("/") if p]
        # only the site part: /sites/<name>[/<subsite>…] or /teams/<name>; anything after (SitePages, Lists, …) is dropped
        if parts and parts[0].lower() in ("sites", "teams"):
            keep = parts[:2]
            for p in parts[2:]:
                if p.lower() in ("lists", "sitepages", "shared%20documents", "shared documents", "_layouts", "forms", "_api"):
                    break
                keep.append(p)
            parts = keep
        else:
            parts = []
        path = "/" + "/".join(parts) if parts else ""
        site = await self.request("GET", f"/sites/{u.hostname}:{quote(path, safe='/')}" if path else f"/sites/{u.hostname}",
                                  params={"$select": "id,displayName,name,webUrl"})
        return {"id": site["id"], "name": site.get("displayName") or site.get("name") or u.hostname, "url": site.get("webUrl", url)}

    async def lists(self, site_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        params = {"$select": "id,name,displayName,description,webUrl,createdDateTime,lastModifiedDateTime,list"}
        async for page in self.pages(f"/sites/{_seg(site_id)}/lists", params):
            for x in page:
                facet = x.get("list") or {}
                if facet.get("hidden"):
                    continue
                out.append({"id": x["id"], "name": x.get("displayName") or x.get("name"), "internal": x.get("name"),
                            "description": x.get("description") or "", "url": x.get("webUrl"),
                            "template": facet.get("template") or "", "modified": x.get("lastModifiedDateTime")})
        out.sort(key=lambda v: (v["name"] or "").lower())
        return out

    async def columns(self, site_id: str, list_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async for page in self.pages(f"/sites/{_seg(site_id)}/lists/{_seg(list_id)}/columns", {"$top": "200"}):
            out.extend(page)
        return out

    async def items(self, site_id: str, list_id: str, *, top: int = 200, cursor: Optional[str] = None) -> dict[str, Any]:
        """One page of items with their fields. `cursor` is the opaque `next` of the previous page."""
        if cursor:
            data = await self.request("GET", cursor)
        else:
            data = await self.request("GET", f"/sites/{_seg(site_id)}/lists/{_seg(list_id)}/items",
                                      params={"$expand": "fields", "$top": str(max(1, min(top, 999)))})
        items = [{"id": str(x["id"]), "etag": x.get("eTag"), "url": x.get("webUrl"), "fields": x.get("fields") or {},
                  "created_by": ((x.get("createdBy") or {}).get("user") or {}).get("displayName"),
                  "modified_by": ((x.get("lastModifiedBy") or {}).get("user") or {}).get("displayName")}
                 for x in data.get("value", [])]
        return {"items": items, "next": data.get("@odata.nextLink")}

    def item_path(self, site_id: str, list_id: str, item_id: Optional[str] = None) -> str:
        base = f"/sites/{_seg(site_id)}/lists/{_seg(list_id)}/items"
        return f"{base}/{_seg(item_id)}" if item_id is not None else base


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    try:
        return min(float(resp.headers.get("Retry-After", "")), MAX_WAIT)
    except ValueError:
        return min(2.0 ** attempt, MAX_WAIT)

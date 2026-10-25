"""
ProxyApp — forward a mounted tool's HTTP traffic to another process (roadmap B9; the first small piece of the
phase-C gateway).

Used for `singleton: true` plugins (sql-studio, schema-map): the web app runs several worker processes, but those
tools hold ONE live database pool each (and never store the password), so they run in one dedicated process — the
`singletons` compose service — and every web worker forwards `/tools/<name>/...` there unchanged (same path, same
query, same cookies). Request and response bodies are streamed, never buffered (uploads, exports and downloads
can be large). Websockets are refused (no tool uses one).
"""

from __future__ import annotations

import logging
from typing import Any

from core_plugins.lazy import _reject

logger = logging.getLogger("toolbox.plugins")

# Hop-by-hop headers (RFC 9110 §7.6.1) are for one connection only and must not be forwarded.
_HOP = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization", b"te", b"trailer",
        b"transfer-encoding", b"upgrade", b"host"}
_client = None
_client_loop = None


def _http():
    """One pooled client per event loop (uvicorn: one loop per worker process for its whole life)."""
    global _client, _client_loop
    import asyncio

    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        import httpx

        # read=900 s: a long SQL statement or export can take minutes; the tool enforces its own limits.
        _client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=900.0, write=900.0),
                                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                                    follow_redirects=False)
        _client_loop = loop
    return _client


class ProxyApp:
    def __init__(self, name: str, title: str, base_url: str):
        self.name, self.title, self.base_url = name, title, base_url.rstrip("/")
        self.state = "remote"

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await _reject(scope, send, 503, "Not supported", "")
            return
        import httpx

        path = scope.get("raw_path") or scope["path"].encode()  # the ORIGINAL path, incl. /tools/<name>
        url = self.base_url + path.decode("latin-1")
        if scope.get("query_string"):
            url += "?" + scope["query_string"].decode("latin-1")
        headers = [(k, v) for k, v in scope["headers"] if k.lower() not in _HOP]
        client = scope.get("client")
        if client:
            headers.append((b"x-forwarded-for", client[0].encode()))
        host = dict(scope["headers"]).get(b"host")
        if host:
            headers.append((b"x-forwarded-host", host))

        async def body():
            while True:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    return
                chunk = msg.get("body", b"")
                if chunk:
                    yield chunk
                if not msg.get("more_body"):
                    return

        has_body = scope["method"] not in ("GET", "HEAD", "OPTIONS", "DELETE") or any(
            k.lower() in (b"content-length", b"transfer-encoding") for k, _ in scope["headers"])
        http = _http()
        req = http.build_request(scope["method"], url, headers=headers, content=body() if has_body else None)
        try:
            resp = await http.send(req, stream=True)
        except httpx.HTTPError as exc:
            logger.warning("proxy %s → %s failed: %s", self.name, self.base_url, exc)
            await _reject(scope, send, 503, f"{self.title} is starting or unavailable",
                          f"<p>{self.title} runs in its own process (the <code>singletons</code> service) and did "
                          "not answer. If you just started the toolbox, wait a few seconds and reload. Otherwise check "
                          "<code>docker compose logs singletons</code>.</p>")
            return
        try:
            out_headers = [(k.lower(), v) for k, v in resp.headers.raw if k.lower() not in _HOP]
            await send({"type": "http.response.start", "status": resp.status_code, "headers": out_headers})
            async for chunk in resp.aiter_raw():  # raw: keep the upstream encoding + content-length as they are
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            await resp.aclose()

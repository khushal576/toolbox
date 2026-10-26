"""
ProxyApp — forward a mounted tool's HTTP traffic to another process (roadmap B9; the first small piece of the
phase-C gateway).

Since roadmap C2 the `toolbox` service is a gateway: every python tool is forwarded to the runtime image its
manifest names (`rt-light`, `rt-data`, … — TOOLBOX_RUNTIME_URLS), and the `singleton: true` plugins (sql-studio,
schema-map: ONE live DB pool each, password never stored) to the one-process `singletons` service
(TOOLBOX_SINGLETON_URL). Path, query, cookies and Host are forwarded unchanged. Request and response bodies are streamed, never buffered (uploads, exports and downloads
can be large). Websockets are refused (no tool uses one).
"""

from __future__ import annotations

import logging
from typing import Any

from core_plugins.lazy import _reject

logger = logging.getLogger("toolbox.plugins")

# Hop-by-hop headers (RFC 9110 §7.6.1) are for one connection only and must not be forwarded.
# Host is NOT dropped: tools see the browser's Host (cookie-lab / header-reference show it; cookies stay right),
# the usual reverse-proxy behaviour (nginx: proxy_set_header Host $host).
_HOP = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization", b"te", b"trailer",
        b"transfer-encoding", b"upgrade"}
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
                                    cookies=_no_cookie_jar(),
                                    # keepalive 2 s < uvicorn's 5 s: never reuse a connection the tool is closing
                                    # (that race showed up as a rare 503 under load in D3)
                                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20,
                                                        keepalive_expiry=2.0),
                                    follow_redirects=False)
        _client_loop = loop
    return _client


def _no_cookie_jar():
    """The proxy must never remember cookies. httpx's client keeps a jar by default: it stored every tool's
    Set-Cookie and added it to the next request WITHOUT its own Cookie header — so a new browser was handed the last
    visitor's duck_lab_sid / df-studio session (found in roadmap L4). Browser cookies still pass through as headers."""
    from http.cookiejar import CookieJar, DefaultCookiePolicy

    return CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))


class ProxyApp:
    def __init__(self, name: str, title: str, base_url: str, supervisor: Any = None, balancer: Any = None):
        self.name, self.title, self.base_url = name, title, base_url.rstrip("/")
        self.state = "remote"
        # roadmap D3: several replicas → each request to the next healthy one (core_plugins/balancer.py)
        self.balancer = balancer
        # roadmap C3: an on-demand runtime's container is started here if it sleeps (the request waits for it)
        self.supervisor = supervisor

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await _reject(scope, send, 503, "Not supported", "")
            return
        import httpx

        sup = self.supervisor
        if sup is not None:
            sup.touch()
            if not await sup.ensure_running():
                await _reject(scope, send, 503, f"{self.title} could not be started",
                              f"<p>Its container (<code>{sup.service}</code>) did not start. Check "
                              f"<code>docker compose ps</code> and <code>docker compose logs {sup.service} docker-proxy</code>.</p>")
                return

        path = scope.get("raw_path") or scope["path"].encode()  # the ORIGINAL path, incl. /tools/<name>
        tail = path.decode("latin-1")
        if scope.get("query_string"):
            tail += "?" + scope["query_string"].decode("latin-1")
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
        content = body() if has_body else None
        bal = self.balancer
        tries = max(2, len(bal.healthy())) if bal is not None else 2
        resp = None
        base = self.base_url
        try:
            for attempt in range(tries):
                base = bal.pick() if bal is not None else self.base_url
                req = http.build_request(scope["method"], base + tail, headers=headers, content=content)
                try:
                    resp = await http.send(req, stream=True)
                    break
                except httpx.ConnectError:
                    # nothing was sent yet (no connection), so another replica may take the same request
                    if attempt == tries - 1:
                        raise
                    if bal is not None:
                        bal.mark_failed(base)
                except (httpx.RemoteProtocolError, httpx.ReadError):
                    # the upstream dropped a reused connection: safe to repeat only if there was no body to resend
                    if content is not None or attempt == tries - 1:
                        raise
        except httpx.HTTPError as exc:
            logger.warning("proxy %s → %s failed: %s %s", self.name, base, type(exc).__name__, exc)
            import html
            from urllib.parse import urlsplit

            service = html.escape(urlsplit(self.base_url).hostname or self.base_url)
            await _reject(scope, send, 503, f"{self.title} is starting or unavailable",
                          f"<p>{html.escape(self.title)} runs in its own container (<code>{service}</code>) and did "
                          "not answer. If you just started the toolbox, wait a few seconds and reload. Otherwise check "
                          f"<code>docker compose ps</code> and <code>docker compose logs {service}</code>.</p>")
            return
        try:
            out_headers = [(k.lower(), v) for k, v in resp.headers.raw if k.lower() not in _HOP]
            await send({"type": "http.response.start", "status": resp.status_code, "headers": out_headers})
            async for chunk in resp.aiter_raw():  # raw: keep the upstream encoding + content-length as they are
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
                if sup is not None:
                    sup.touch()  # a long download is activity, not idleness (throttled to every 5 s)
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            await resp.aclose()

"""Roadmap L4 finding: the gateway's proxy client must never remember cookies (core_plugins/proxy.py).

httpx keeps a cookie jar per client by default; the proxy's client is shared by every browser, so a stored
`duck_lab_sid` was sent on for the next visitor who had no cookie yet — two people in one session."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
httpx = pytest.importorskip("httpx")

from core_plugins import proxy  # noqa: E402


def test_proxy_client_does_not_carry_cookies_between_visitors():
    seen = []

    def handler(request):
        seen.append(request.headers.get("cookie"))
        return httpx.Response(200, headers={"set-cookie": "duck_lab_sid=visitor1; Path=/; HttpOnly"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), cookies=proxy._no_cookie_jar()) as c:
            await c.get("http://rt-data:8080/tools/duck-lab/tables")                       # visitor 1 gets a sid
            await c.get("http://rt-data:8080/tools/duck-lab/tables")                       # visitor 2: no cookie
            await c.get("http://rt-data:8080/tools/duck-lab/tables", headers={"cookie": "duck_lab_sid=mine"})

    asyncio.run(go())
    assert seen == [None, None, "duck_lab_sid=mine"]


def test_the_real_proxy_client_stores_nothing():
    async def go():
        return proxy._http()

    client = asyncio.run(go())
    req = httpx.Request("GET", "http://rt-data:8080/tools/df-studio/session")
    client.cookies.extract_cookies(httpx.Response(200, headers={"set-cookie": "dfs=abc; Path=/"}, request=req))
    assert len(client.cookies.jar) == 0

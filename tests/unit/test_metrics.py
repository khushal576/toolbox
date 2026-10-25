"""Roadmap E2/E3: per-tool counters, the recent-errors list, error messages, Docker log demuxing."""

import json
import sys
from collections import defaultdict
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import metrics  # noqa: E402
from core_plugins.overview import _demux  # noqa: E402


class FakeRedis:
    """Just enough of redis for metrics.py (text mode)."""

    def __init__(self):
        self.h, self.sets, self.lists = defaultdict(dict), defaultdict(set), defaultdict(list)

    def pipeline(self, transaction=False):
        return self

    def hincrby(self, k, f, n):
        self.h[k][f] = str(int(self.h[k].get(f, 0)) + n)

    def expire(self, *a):
        pass

    def sadd(self, k, v):
        self.sets[k].add(v)

    def lpush(self, k, v):
        self.lists[k].insert(0, v)

    def ltrim(self, k, a, b):
        self.lists[k] = self.lists[k][a:b + 1]

    def execute(self):  # writes need no results; read() swaps in a version returning the hgetall results
        return []

    def smembers(self, k):
        return self.sets[k]

    def hgetall(self, k):  # used inside a pipeline in read(): collect results instead
        self._q.append(dict(self.h.get(k, {})))

    def lrange(self, k, a, b):
        return self.lists[k][a:b + 1]


@pytest.fixture
def fake(monkeypatch):
    r = FakeRedis()
    r._q = []
    monkeypatch.setattr(metrics, "_redis", lambda: r)
    metrics._pending.clear()
    metrics._errors.clear()

    def execute():  # the read() pipeline returns the queued hgetall results
        out, r._q = r._q, []
        return out

    r.execute = execute
    return r


def _app():
    async def ok(request):
        return PlainTextResponse("fine")

    async def boom(request):
        return JSONResponse({"ok": False, "error": "database exploded"}, status_code=500)

    async def down(request):
        return HTMLResponse("<html><head><title>X is unavailable</title><style>p{}</style></head>"
                            "<body><h1>X is unavailable</h1><p>Check logs.</p></body></html>", status_code=503)

    async def slow(request):
        import asyncio

        await asyncio.sleep(0.05)
        return PlainTextResponse("late")

    inner = Starlette(routes=[Route("/ok", ok), Route("/boom", boom), Route("/down", down), Route("/slow", slow)])
    return TestClient(Starlette(routes=[Mount("/tools/x", metrics.Metered(inner, "x"))]))


def test_requests_errors_and_slow_answers_are_counted(fake, monkeypatch):
    monkeypatch.setattr(metrics, "SLOW_MS", 30)
    c = _app()
    for path in ("/ok", "/ok", "/boom", "/down", "/slow"):
        c.get("/tools/x" + path)
    out = metrics.read()
    h = out["tools"]["x"]["hour"]
    assert (h["req"], h["err"], h["slow"]) == (5, 2, 1) and out["tools"]["x"]["series"][-1] == 5
    assert out["tools"]["x"]["day"]["req"] == 5


def test_errors_keep_a_readable_message(fake):
    c = _app()
    c.get("/tools/x/boom")
    c.get("/tools/x/down")
    errs = metrics.recent_errors()
    assert [e["status"] for e in errs] == [503, 500]  # newest first
    assert errs[0]["message"] == "X is unavailable Check logs." and errs[1]["message"] == "database exploded"
    assert errs[1]["path"] == "/tools/x/boom" and errs[1]["tool"] == "x"


def test_error_list_is_capped(fake, monkeypatch):
    monkeypatch.setattr(metrics, "MAX_ERRORS", 3)
    for i in range(5):
        metrics.record("x", 500, 1, {"ts": i, "tool": "x", "status": 500, "message": str(i)})
    metrics.flush()
    assert [json.loads(e)["message"] for e in fake.lists[metrics.ERRORS_KEY]] == ["4", "3", "2"]


def test_docker_log_frames_are_demultiplexed():
    def frame(stream, text):
        b = text.encode()
        return bytes([stream, 0, 0, 0]) + len(b).to_bytes(4, "big") + b
    assert _demux(frame(1, "out line\n") + frame(2, "err line\n")) == "out line\nerr line\n"
    assert _demux(b"plain tty output\n") == "plain tty output\n"

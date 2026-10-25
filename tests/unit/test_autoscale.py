"""Roadmap D3: health-aware balancing + replica autoscaling (fake Docker API). The live load test is in the handoff."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import autoscale  # noqa: E402
from core_plugins.autoscale import ScaledService, scaled_runtimes  # noqa: E402
from core_plugins.balancer import Balancer  # noqa: E402
from core_plugins import discover  # noqa: E402


def test_datadiff_is_the_scaled_runtime():
    assert scaled_runtimes(discover(REPO).ordered()) == {"datadiff": (2, 4)}


# ---- balancer ----------------------------------------------------------------------------------------------------

def _listing(*specs):
    return [{"Names": [f"/toolbox-rt-x-{n}"], "Status": status, "State": "running",
             "NetworkSettings": {"Networks": {"net": {"IPAddress": f"10.0.0.{n}"}}}} for n, status in specs]


def _balancer(listing):
    b = Balancer("rt-x", "http://rt-x:8080", "http://docker")

    def docker(request):
        return httpx.Response(200, json=listing)

    orig = httpx.AsyncClient

    class Patched(orig):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(docker)
            super().__init__(*a, **kw)

    return b, Patched


def test_balancer_round_robins_over_healthy_replicas_only(monkeypatch):
    b, patched = _balancer(_listing((1, "Up 1 minute (healthy)"), (2, "Up 3 seconds (health: starting)"),
                                    (3, "Up 2 minutes (healthy)"), (4, "Up 1 minute (unhealthy)")))
    monkeypatch.setattr(httpx, "AsyncClient", patched)
    asyncio.run(b.refresh())
    picks = [b.pick() for _ in range(4)]
    assert picks == ["http://10.0.0.1:8080", "http://10.0.0.3:8080"] * 2
    b.mark_failed("http://10.0.0.1:8080")
    assert {b.pick() for _ in range(3)} == {"http://10.0.0.3:8080"}
    b.mark_failed("http://10.0.0.3:8080")
    assert b.pick() == "http://rt-x:8080"  # nothing healthy left → plain service name (Docker DNS)


# ---- autoscaler --------------------------------------------------------------------------------------------------

class FakeDocker:
    def __init__(self, n, running, cpu=0.0):
        self.pool = {f"toolbox-rt-dd-{i}": i <= running for i in range(1, n + 1)}
        self.cpu, self.calls = cpu, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/containers/json":
            return httpx.Response(200, json=[{"Names": [f"/{name}"], "Id": f"{i:012d}abcdef", "State": "running" if up else "exited",
                                              "Labels": {"com.docker.compose.container-number": str(i)}}
                                             for i, (name, up) in enumerate(self.pool.items(), 1)])
        if path.endswith("/stats"):
            total = 1000 + self.cpu * 10  # cpu% of one core = delta_cpu / delta_system * ncpu * 100
            return httpx.Response(200, json={"cpu_stats": {"cpu_usage": {"total_usage": total}, "system_cpu_usage": 2000,
                                                           "online_cpus": 1},
                                             "precpu_stats": {"cpu_usage": {"total_usage": 1000}, "system_cpu_usage": 1000}})
        name = path.split("/")[2]
        self.calls.append((path.rsplit("/", 1)[1], name))
        self.pool[name] = path.endswith("/start")
        return httpx.Response(204)


def _scaler(fake, kind="cpu", lo=2, hi=4):
    s = ScaledService("rt-dd", kind, lo, hi, "http://docker")
    s._client = lambda: httpx.AsyncClient(base_url="http://docker", transport=httpx.MockTransport(fake))
    return s


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(autoscale, "COOLDOWN", 0.0)
    monkeypatch.setattr(autoscale, "DOWN_AFTER", 0.0)


def test_cpu_load_scales_up_to_max_then_down_to_min():
    fake = FakeDocker(4, running=2, cpu=90.0)
    s = _scaler(fake)
    assert asyncio.run(s.tick()) == "up toolbox-rt-dd-3"
    assert asyncio.run(s.tick()) == "up toolbox-rt-dd-4"
    assert asyncio.run(s.tick()) is None and s.last["running"] == 4  # at max
    fake.cpu = 2.0  # DOWN_AFTER is 0 here, so each low tick may stop one
    assert asyncio.run(s.tick()) == "down toolbox-rt-dd-4"  # highest number first
    assert asyncio.run(s.tick()) == "down toolbox-rt-dd-3"
    for _ in range(3):
        assert asyncio.run(s.tick()) is None
    assert sum(fake.pool.values()) == 2  # never below min


def test_low_load_must_last_down_after_seconds(monkeypatch):
    monkeypatch.setattr(autoscale, "DOWN_AFTER", 3600.0)
    s = _scaler(FakeDocker(4, running=4, cpu=1.0))
    assert asyncio.run(s.tick()) is None and asyncio.run(s.tick()) is None  # low, but not for long enough


def test_cooldown_spaces_out_changes(monkeypatch):
    monkeypatch.setattr(autoscale, "COOLDOWN", 3600.0)
    fake = FakeDocker(4, running=2, cpu=95.0)
    s = _scaler(fake)
    assert asyncio.run(s.tick()) == "up toolbox-rt-dd-3"
    assert asyncio.run(s.tick()) is None  # still cooling down


def test_below_min_is_fixed_at_once(monkeypatch):
    monkeypatch.setattr(autoscale, "COOLDOWN", 3600.0)
    s = _scaler(FakeDocker(4, running=0))
    s.last_change = 10**12  # even inside a cooldown
    assert asyncio.run(s.tick()) == "up toolbox-rt-dd-1"


def test_workers_scale_by_queue_and_only_idle_ones_stop(monkeypatch):
    fake = FakeDocker(3, running=1)
    s = _scaler(fake, kind="queue", lo=1, hi=3)
    queue = {"waiting": 4, "states": {}}
    monkeypatch.setattr(ScaledService, "_queue", staticmethod(lambda: (queue["waiting"], queue["states"])))
    assert asyncio.run(s.tick()) == "up toolbox-rt-dd-2"
    assert asyncio.run(s.tick()) == "up toolbox-rt-dd-3"
    queue.update(waiting=0, states={"000000000003": "busy", "000000000002": "idle", "000000000001": "idle"})
    assert asyncio.run(s.tick()) == "down toolbox-rt-dd-2"  # #3 is busy → skipped; the highest idle one goes
    queue["states"] = {"000000000003": "busy", "000000000001": "idle"}
    assert asyncio.run(s.tick()) == "down toolbox-rt-dd-1"  # still ≥ min 1 afterwards; #3 keeps its job
    queue["states"] = {"000000000003": "busy"}
    assert asyncio.run(s.tick()) is None  # at min, and the last one is busy anyway
    assert fake.pool["toolbox-rt-dd-3"] is True


# ---- proxy retries another replica on a refused connection ---------------------------------------------------------

def test_proxy_skips_a_dead_replica(monkeypatch):
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Mount, Route
    from starlette.testclient import TestClient

    from core_plugins import proxy as proxy_mod
    from core_plugins.proxy import ProxyApp

    sent = []

    class Upstream(httpx.AsyncBaseTransport):
        """Like the network: a refused connection fails BEFORE the body is read (MockTransport reads it first)."""

        async def handle_async_request(self, request):
            sent.append(request.url.host)
            if request.url.host == "10.0.0.1":
                raise httpx.ConnectError("refused", request=request)
            await request.aread()
            body = ("ok from " + request.url.host).encode()

            class Stream(httpx.AsyncByteStream):  # a streamed body, like a real upstream (text= counts as read)
                async def __aiter__(self):
                    yield body

            return httpx.Response(200, stream=Stream())

    class FakeBalancer:
        def __init__(self):
            self.order, self.failed = ["http://10.0.0.1:8080", "http://10.0.0.2:8080"], []

        def healthy(self):
            return [1, 2]

        def pick(self):
            return self.order.pop(0)

        def mark_failed(self, base):
            self.failed.append(base)

    bal = FakeBalancer()
    proxy_mod._client = httpx.AsyncClient(transport=Upstream())
    proxy_mod._client_loop = None
    monkeypatch.setattr(proxy_mod, "_http", lambda: proxy_mod._client)
    c = TestClient(Starlette(routes=[Mount("/tools/x", ProxyApp("x", "X", "http://rt-x:8080", balancer=bal))]))
    r = c.post("/tools/x/compare", content=b"payload")
    assert r.status_code == 200 and r.text == "ok from 10.0.0.2"
    assert bal.failed == ["http://10.0.0.1:8080"] and sent == ["10.0.0.1", "10.0.0.2"]

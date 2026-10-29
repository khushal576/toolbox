"""Roadmap C1: one image per manifest `runtime:`. Keeps requirements/<runtime>.txt, the Dockerfile targets and the
compose rt-* services in step with the manifests. Whether each image really loads its plugins is checked live
(docker compose --profile runtimes up -d, then GET /tools/<name>/ on ports 8101-8105 — see the C1 handoff)."""

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from core_plugins import discover  # noqa: E402

RUNTIMES = ("light", "data", "pgtools", "ssh", "latex", "datadiff", "notebook")


def _pins(path: Path, seen: set | None = None) -> dict[str, str]:
    """{package: full pin line} of a requirements file, following -r includes."""
    seen = seen or set()
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            inc = (path.parent / line[3:].strip()).resolve()
            assert inc not in seen, f"include loop at {inc}"
            out.update(_pins(inc, seen | {inc}))
        else:
            out[re.split(r"[=<>\[]", line, maxsplit=1)[0].lower()] = line
    return out


FULL = _pins(REPO / "requirements.txt")


def test_every_runtime_file_pins_exactly_what_requirements_txt_pins():
    for f in (REPO / "requirements").glob("*.txt"):
        for pkg, line in _pins(f).items():
            assert FULL.get(pkg) == line, f"{f.name}: '{line}' differs from requirements.txt ('{FULL.get(pkg)}')"


def test_every_package_is_used_by_some_runtime():
    used = set().union(*(_pins(REPO / "requirements" / f"{r}.txt") for r in RUNTIMES))
    assert set(FULL) - used == set(), "in requirements.txt but in no runtime image"


def test_every_python_plugin_has_an_image_and_a_service():
    dockerfile = (REPO / "Dockerfile").read_text()
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())["services"]
    for m in discover(REPO).ordered():
        if m.kind != "python":
            continue
        assert m.runtime in RUNTIMES, m.name
        assert (REPO / "requirements" / f"{m.runtime}.txt").is_file(), m.name
        assert re.search(rf"^FROM \S+ AS {m.runtime}$", dockerfile, re.M), f"no Dockerfile target '{m.runtime}'"
        svc = compose.get(f"rt-{m.runtime}")
        assert svc and svc["build"]["target"] == m.runtime and "profiles" not in svc, m.runtime


def test_gateway_routes_every_runtime_and_full_stays_the_default_target():
    """Roadmap C2: toolbox = gateway image, with a URL for every runtime; worker = worker image (C4)."""
    dockerfile = (REPO / "Dockerfile").read_text()
    assert re.findall(r"^FROM \S+ AS (\S+)$", dockerfile, re.M)[-1] == "full"  # last stage = `docker build .`
    services = yaml.safe_load((REPO / "docker-compose.yml").read_text())["services"]
    gw = services["toolbox"]
    assert gw["build"]["target"] == "gateway" and services["worker"]["build"]["target"] == "worker"
    urls = dict(p.split("=", 1) for p in gw["environment"]["TOOLBOX_RUNTIME_URLS"].split(","))
    assert set(urls) == set(RUNTIMES) and all(urls[r] == f"http://rt-{r}:8080" for r in RUNTIMES)
    assert gw["environment"]["TOOLBOX_SINGLETON_URL"] == "http://singletons:8080"
    assert list(gw["ports"]) == ["${TOOLBOX_HOST_PORT:-8000}:8080"] and all("ports" not in services[f"rt-{r}"] for r in RUNTIMES)


# ---- roadmap C3: on-demand runtimes ------------------------------------------------------------------------------

def test_on_demand_runtimes_are_the_all_tier_4_ones(monkeypatch):
    from core_plugins.supervisor import on_demand_runtimes

    monkeypatch.delenv("TOOLBOX_IDLE_TIMEOUT_S", raising=False)
    od = on_demand_runtimes(discover(REPO).ordered())
    assert set(od) == {"latex", "pgtools", "ssh", "notebook"}
    assert od["notebook"] == 1800 and all(v == 900 for k, v in od.items() if k != "notebook")  # notebook: cells outlive the tab
    monkeypatch.setenv("TOOLBOX_IDLE_TIMEOUT_S", "60")
    assert set(on_demand_runtimes(discover(REPO).ordered()).values()) == {60}


def test_compose_limits_equal_the_sum_of_manifest_resources():
    services = yaml.safe_load((REPO / "docker-compose.yml").read_text())["services"]
    for rt in RUNTIMES:
        ms = [m for m in discover(REPO).ordered() if m.kind == "python" and m.runtime == rt and not m.singleton]
        mem = sum(m.resources.memory_mb or 0 for m in ms)
        cpu = sum(m.resources.cpu or 0 for m in ms)
        svc = services[f"rt-{rt}"]
        if mem:
            assert svc.get("mem_limit") == f"{mem}m", f"rt-{rt}: mem_limit should be {mem}m (sum of manifests)"
        else:
            assert "mem_limit" not in svc, f"rt-{rt}: no manifest declares memory, so no limit"
        if cpu:
            assert float(svc.get("cpus", 0)) == cpu, f"rt-{rt}: cpus should be {cpu}"


def test_docker_proxy_allows_only_list_inspect_and_rt_start_stop():
    cfg = yaml.safe_load((REPO / "docker-compose.yml").read_text())["configs"]["docker_proxy_rules"]["content"]
    rules = [line.strip() for line in cfg.splitlines() if line.strip().startswith("http-request")]
    assert rules[-1] == "http-request deny"
    assert all("METH_GET" in r or "-rt-[a-z]+-[0-9]+/(start|stop)" in r or "-worker-[0-9]+/(start|stop)" in r
               for r in rules[:-1]), rules
    assert not any(w in cfg for w in ("exec", "create", "update", "/images", "/volumes")), "keep the proxy minimal"


def test_supervisor_starts_a_sleeping_container_once_and_stops_it():
    import asyncio
    import json as _json

    import httpx

    from core_plugins.supervisor import RuntimeSupervisor

    calls, state = [], {"running": False}

    def docker(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/containers/json":
            labels = _json.loads(request.url.params["filters"])["label"]
            assert "com.docker.compose.service=rt-latex" in labels and "com.docker.compose.oneoff=False" in labels
            return httpx.Response(200, json=[{"Names": ["/toolbox-rt-latex-1"],
                                              "State": "running" if state["running"] else "exited"}])
        if request.url.path.endswith("/start"):
            state["running"] = True
            return httpx.Response(204)
        if request.url.path.endswith("/stop"):
            state["running"] = False
            return httpx.Response(204)
        return httpx.Response(404)

    sup = RuntimeSupervisor("latex", "http://rt-latex:8080", "http://docker-proxy:2375", 60)
    sup._client = lambda: httpx.AsyncClient(base_url="http://docker-proxy:2375", transport=httpx.MockTransport(docker))
    sup.touch = lambda force=False: None

    async def healthy():
        return state["running"]

    sup._healthy = healthy

    async def scenario():
        assert await sup.refresh() == "asleep"
        results = await asyncio.gather(*(sup.ensure_running() for _ in range(5)))  # 5 concurrent first requests
        assert all(results) and sup.state() == "running"
        await sup.stop()
        assert sup.state() == "asleep"

    asyncio.run(scenario())
    starts = [c for c in calls if c[1].endswith("/start")]
    assert starts == [("POST", "/containers/toolbox-rt-latex-1/start")]  # started exactly once
    assert ("POST", "/containers/toolbox-rt-latex-1/stop") in calls


def test_only_the_latex_image_that_compose_runs_carries_tex_live():
    """Roadmap C4 done-when: no image except `latex` (and the never-composed `full`) inherits the TeX Live stage."""
    dockerfile = (REPO / "Dockerfile").read_text()
    parent = dict((name, base) for base, name in re.findall(r"^FROM (\S+) AS (\S+)$", dockerfile, re.M))

    def has_tex(stage: str) -> bool:
        while stage in parent:
            if stage == "tex":
                return True
            stage = parent[stage]
        return False

    assert "texlive" in dockerfile.split("FROM python:3.11-slim AS tex", 1)[1].split("\nFROM ", 1)[0]
    services = yaml.safe_load((REPO / "docker-compose.yml").read_text())["services"]
    built = {name: svc["build"]["target"] for name, svc in services.items() if isinstance(svc.get("build"), dict)}
    assert {n for n, t in built.items() if has_tex(t)} == {"rt-latex"}, built
    assert "full" not in built.values()

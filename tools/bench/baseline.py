"""
tools/bench/baseline.py

Roadmap session S0.2: measure the running Toolbox so later phases can prove (or disprove) savings.
Run from the HOST with the container up (no extra Python packages needed):

    python3 tools/bench/baseline.py                 # measure, write docs/roadmap/baseline.{md,json}
    python3 tools/bench/baseline.py --restart       # also measure cold-start time (restarts the container)
    python3 tools/bench/baseline.py --out /tmp/x    # write somewhere else (e.g. to compare a branch)

What it measures:
  1. Image size and container memory/CPU/PIDs at idle (docker stats).
  2. RSS of the server process(es) inside the container.
  3. Per-tool import cost: for every `kind: python` plugin manifest (what main.py mounts), a FRESH Python
     process inside the container imports only that module; we record extra RSS and import time
     relative to a bare `import fastapi`. Also the cost of importing all of them (= today's startup).
  4. (optional) Cold start: container restart until GET / returns 200.
  5. Latency p50/p95 for a few representative requests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Runs inside the container, once per module, in a fresh interpreter.
IMPORT_PROBE = r"""
import importlib, json, sys, time
def rss_kb():
    with open('/proc/self/status') as f:
        for line in f:
            if line.startswith('VmRSS:'):
                return int(line.split()[1])
import fastapi  # every tool needs it; it is the floor, not the tool's cost
base = rss_kb()
mods = sys.argv[1:]
t0 = time.perf_counter()
err = None
try:
    for m in mods:
        importlib.import_module(m)
except Exception as e:  # report, don't crash the whole benchmark
    err = f"{type(e).__name__}: {e}"
print(json.dumps({"base_kb": base, "after_kb": rss_kb(), "seconds": time.perf_counter() - t0, "error": err}))
"""


def sh(cmd: list[str], check: bool = True, input_text: str | None = None) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_text)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def mounted_tools() -> list[tuple[str, str]]:
    """(name, module) of every plugin main.py mounts, from the manifests."""
    sys.path.insert(0, str(REPO))
    from core_plugins import discover
    return [(m.name, m.module) for m in discover(REPO).ordered() if m.kind == "python"]


def http(method: str, url: str, body: bytes | None = None, ctype: str = "application/json",
         timeout: float = 120) -> tuple[int, float, int]:
    req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": ctype} if body else {})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            n = len(r.read())
            code = r.status
    except urllib.error.HTTPError as e:
        n, code = len(e.read()), e.code
    return code, time.perf_counter() - t0, n


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


def datadiff_payload(n: int) -> bytes:
    left = [{"id": i, "name": f"user{i}", "city": "Ahmedabad", "score": i % 97} for i in range(n)]
    right = [dict(r, score=(r["score"] + 1) if r["id"] % 10 == 0 else r["score"]) for r in left]
    return json.dumps({"left_data": json.dumps(left), "right_data": json.dumps(right),
                       "left_format": "json", "right_format": "json"}).encode()


LATEX_DOC = r"""\documentclass{article}
\usepackage[margin=1in]{geometry}
\begin{document}
\section*{Benchmark}
Hello from the Toolbox baseline. \textbf{Bold}, \textit{italic}, and a list:
\begin{itemize}\item one \item two \item three\end{itemize}
\end{document}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--container", default="toolbox-toolbox-1")
    ap.add_argument("--runs", type=int, default=30, help="requests per light endpoint")
    ap.add_argument("--heavy-runs", type=int, default=5, help="requests per heavy endpoint (LaTeX, big diff)")
    ap.add_argument("--restart", action="store_true", help="measure cold start (restarts the container)")
    ap.add_argument("--out", default=str(REPO / "docs/roadmap/baseline"), help="output path without extension")
    a = ap.parse_args()

    res: dict = {"when": dt.datetime.now().isoformat(timespec="seconds")}
    res["git_sha"] = sh(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], check=False)
    res["host"] = {"cpus": os.cpu_count(),
                   "mem_total_gb": round(int(open("/proc/meminfo").read().split()[1]) / 1024 / 1024, 1)}

    # 4. cold start first, so the idle numbers below are measured on a fresh container
    if a.restart:
        print("restarting container for cold-start timing ...")
        sh(["docker", "restart", a.container])
        t0, code = time.perf_counter(), 0
        while time.perf_counter() - t0 < 180:
            try:
                code = http("GET", a.base_url + "/", timeout=2)[0]
                if code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.25)
        res["cold_start_seconds"] = round(time.perf_counter() - t0, 2) if code == 200 else None
        time.sleep(5)  # let it settle before idle measurements

    # 1. image + container stats
    image = sh(["docker", "inspect", "-f", "{{.Image}}", a.container])
    res["image_size_gb"] = round(int(sh(["docker", "image", "inspect", "-f", "{{.Size}}", image])) / 1e9, 2)
    mem, cpu, pids = sh(["docker", "stats", "--no-stream", "--format",
                         "{{.MemUsage}}|{{.CPUPerc}}|{{.PIDs}}", a.container]).split("|")
    res["idle"] = {"docker_mem": mem.strip(), "cpu": cpu.strip(), "pids": int(pids)}

    # 2. RSS of python processes in the container
    ps = sh(["docker", "exec", a.container, "sh", "-c",
             "for p in /proc/[0-9]*; do n=$(cat $p/comm 2>/dev/null); "
             "case $n in python*|uvicorn*|gunicorn*) grep VmRSS $p/status | awk -v n=$n '{print n\" \"$2}';; esac; done"],
            check=False)
    rss = [int(line.split()[1]) for line in ps.splitlines() if line.strip()]
    res["idle"]["server_rss_mb"] = round(sum(rss) / 1024, 1)
    res["idle"]["server_processes"] = len(rss)

    # 3. per-tool import cost
    tools = mounted_tools()
    print(f"measuring import cost of {len(tools)} tools ...")

    def probe(mods: list[str]) -> dict:
        out = sh(["docker", "exec", "-i", "-w", "/app", a.container, "python", "-", *mods], input_text=IMPORT_PROBE,
                 check=False)
        return json.loads(out.splitlines()[-1]) if out else {"error": "no output"}

    per_tool = []
    for name, mod in tools:
        r = probe([mod])
        per_tool.append({"tool": name, "module": mod,
                         "extra_mb": round((r.get("after_kb", 0) - r.get("base_kb", 0)) / 1024, 1),
                         "import_s": round(r.get("seconds", 0), 2), "error": r.get("error")})
    per_tool.sort(key=lambda x: -x["extra_mb"])
    allr = probe([m for _, m in tools])
    res["imports"] = {"fastapi_floor_mb": round(allr.get("base_kb", 0) / 1024, 1),
                      "all_tools_extra_mb": round((allr.get("after_kb", 0) - allr.get("base_kb", 0)) / 1024, 1),
                      "all_tools_import_s": round(allr.get("seconds", 0), 2),
                      "all_error": allr.get("error"), "per_tool": per_tool}

    # 5. latency
    cases = [
        ("GET /  (home page)", "GET", "/", None, "", a.runs),
        ("GET /tools/encode-decode/  (static page)", "GET", "/tools/encode-decode/", None, "", a.runs),
        ("POST datadiff /compare  (100 records)", "POST", "/tools/datadiff-pro/compare",
         datadiff_payload(100), "application/json", a.runs),
        ("POST datadiff /compare  (5,000 records)", "POST", "/tools/datadiff-pro/compare",
         datadiff_payload(5000), "application/json", a.heavy_runs),
        ("POST latex-pdf /compile  (1 page)", "POST", "/tools/latex-pdf/compile",
         json.dumps({"source": LATEX_DOC}).encode(), "application/json", a.heavy_runs),
    ]
    lat = []
    for label, method, path, body, ctype, n in cases:
        print(f"latency: {label} x{n}")
        try:
            http(method, a.base_url + path, body, ctype)  # warm-up
            times, codes = [], set()
            for _ in range(n):
                code, secs, _size = http(method, a.base_url + path, body, ctype)
                times.append(secs * 1000)
                codes.add(code)
            lat.append({"case": label, "n": n, "codes": sorted(codes),
                        "p50_ms": round(pct(times, 50), 1), "p95_ms": round(pct(times, 95), 1),
                        "mean_ms": round(statistics.mean(times), 1)})
        except Exception as e:
            lat.append({"case": label, "n": n, "error": str(e)})
    res["latency"] = lat

    write(res, Path(a.out))
    return 0


def write(res: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    im, idle = res["imports"], res["idle"]
    L = [
        "# Toolbox baseline (roadmap S0.2)",
        "",
        f"Measured {res['when']} on commit `{res['git_sha']}` — host {res['host']['cpus']} CPUs, "
        f"{res['host']['mem_total_gb']} GB RAM. Regenerate with `python3 tools/bench/baseline.py --restart`.",
        "Raw numbers: `baseline.json` next to this file. Later phases compare against these.",
        "",
        "## Summary",
        "| Metric | Value |",
        "|---|---|",
        f"| Image size | {res['image_size_gb']} GB |",
        f"| Container memory at idle (docker stats) | {idle['docker_mem']} |",
        f"| Server process RSS at idle | {idle['server_rss_mb']} MB in {idle['server_processes']} process(es) |",
        f"| CPU at idle / PIDs | {idle['cpu']} / {idle['pids']} |",
        f"| Cold start (restart → home page 200) | "
        f"{str(res['cold_start_seconds']) + ' s' if res.get('cold_start_seconds') else 'not measured'} |",
        f"| `import fastapi` floor | {im['fastapi_floor_mb']} MB |",
        f"| All tools imported (today's startup) | +{im['all_tools_extra_mb']} MB, {im['all_tools_import_s']} s |",
        "",
        "## Import cost per tool (fresh process each, on top of the fastapi floor)",
        "Shared libraries are counted for every tool that imports them, so the rows add up to more than",
        "the all-tools total. This is the RAM a tool would cost if it were the only one loaded (lazy loading, A3).",
        "",
        "| Tool | Module | Extra RSS | Import time | Note |",
        "|---|---|---|---|---|",
    ]
    for t in im["per_tool"]:
        L.append(f"| {t['tool']} | `{t['module']}` | {t['extra_mb']} MB | {t['import_s']} s | {t['error'] or ''} |")
    L += ["", "## Latency", "| Request | Runs | p50 | p95 | Mean | HTTP |", "|---|---|---|---|---|---|"]
    for l in res["latency"]:
        if "error" in l:
            L.append(f"| {l['case']} | {l['n']} | – | – | – | error: {l['error']} |")
        else:
            L.append(f"| {l['case']} | {l['n']} | {l['p50_ms']} ms | {l['p95_ms']} ms | {l['mean_ms']} ms | "
                     f"{', '.join(map(str, l['codes']))} |")
    L += ["", "Single-user, sequential requests on a laptop: use these numbers for before/after comparison,",
          "not as capacity figures. Load testing comes in D3.", ""]
    out.with_suffix(".md").write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out.with_suffix('.md')} and {out.with_suffix('.json')}")


if __name__ == "__main__":
    sys.exit(main())

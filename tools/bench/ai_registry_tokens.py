#!/usr/bin/env python3
"""
tools/bench/ai_registry_tokens.py — roadmap H3: what does the start of an AI question cost as the number of tools grows?

Builds N fake tools (3 read actions each) and measures, for the REGISTRY design (what is built) and the NAIVE design (one MCP tool per action):
  * what the AI is shown up front (the tool list + toolbox_guide) and what one search / describe costs,
  * how long the first search (index build) and later searches take.
Token counts are ESTIMATES: characters / 4 (JSON and English average ~3.5-4 characters per token; Claude's own tokenizer differs a little).
Run from the repo root:  python3 tools/bench/ai_registry_tokens.py [--out docs/roadmap/measure-H3.md]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from mcp_server import access, protocol, registry, tools  # noqa: E402

SIZES = (25, 100, 300, 1000)
QUERIES = ("job 7 widgets", "gadgets number 12", "compare two tables", "formula functions", "thingamajigs on tool 40")


def fake_repo(root: Path, n: int, per_tool: int = 3) -> None:
    for i in range(n):
        d = root / f"tool-{i:04d}"
        d.mkdir()
        acts = [{"name": f"act_{j}", "summary": f"Does job {j} number {i} on widgets, gadgets and thingamajigs",
                 "path": f"jobs/{j}", "inputs": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "how many rows at most"}},
                 "returns": "a list of widgets"} for j in range(per_tool)]
        (d / "manifest.yaml").write_text(yaml.safe_dump({"name": f"tool-{i:04d}", "title": f"Tool number {i}", "description": f"Tool {i} handles widgets, gadgets and thingamajigs.",
                                                         "kind": "python", "entry": f"tool_{i:04d}.server:app", "runtime": "light", "ai": {"actions": acts}}))


def tok(text: str) -> int:
    return round(len(text) / 4)


def naive_tool_list(actions) -> str:
    """What 'one MCP tool per action' would put in tools/list for the AI to read up front."""
    return json.dumps([{"name": a.id.replace(".", "__"), "description": a.summary + (" " + a.returns if a.returns else ""),
                        "inputSchema": {"type": "object", "properties": a.inputs, "required": a.required}} for a in actions], separators=(",", ":"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    class V:
        def list_secrets(self, kind):
            return []
    access.vault = lambda: V()                                    # no Vault needed to measure the guide
    rows = []
    for n in SIZES:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            fake_repo(repo, n)
            tools.REPO = repo
            registry.invalidate()
            t0 = time.monotonic()
            first = registry.find(QUERIES[0], repo=repo)
            build = time.monotonic() - t0
            warm = []
            for q in QUERIES * 3:
                t = time.monotonic()
                registry.find(q, repo=repo)
                warm.append(time.monotonic() - t)
            actions = registry.load(repo)
            listing = json.dumps(protocol._tool_listing(), separators=(",", ":"))
            guide = json.dumps(tools.toolbox_guide({}).data, separators=(",", ":"))
            find_r = json.dumps(first, separators=(",", ":"))
            hit = first["matches"][0]["id"] if first["matches"] else actions[0].id
            describe_r = json.dumps(registry.describe(hit, repo=repo), separators=(",", ":"))
            naive = naive_tool_list(actions)
            rows.append({"tools": n, "actions": len(actions), "registry_up_front": tok(listing) + tok(guide), "tools_list": tok(listing), "guide": tok(guide),
                         "one_search": tok(find_r), "one_describe": tok(describe_r), "naive_up_front": tok(naive) + tok(listing),
                         "first_search_s": round(build, 2), "warm_search_ms": round(statistics.median(warm) * 1000, 1)})
    lines = ["| Tools | Actions | **Registry**: shown up front | + one search | + one describe | **Naive** (a tool per action): shown up front | First search | Later searches |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['tools']:,} | {r['actions']:,} | **~{r['registry_up_front']:,}** tokens | ~{r['one_search']:,} | ~{r['one_describe']:,} | ~{r['naive_up_front']:,} tokens | {r['first_search_s']} s | {r['warm_search_ms']} ms |")
    table = "\n".join(lines)
    print(table)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=2))
        Path(a.out).with_suffix(".table.md").write_text(table + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

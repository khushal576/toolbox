"""
main.py

Single entrypoint for the whole toolbox website — one process, one
container, one Dockerfile. Serves the home page at "/" and mounts every
tool's own FastAPI app under /tools/<name>/ in the same process (no network
hop, no reverse proxy — just an in-process ASGI mount).

Adding a tool
-------------
1. Add one `_try_mount("<name>", "<module_path>")` call in the mounting
   section at the bottom — module_path is what you'd write after `from` in
   `from <module_path> import app`. This is a deferred import (see
   `_try_mount`'s docstring for why): don't add a top-level
   `from X import Y` for a new tool, it defeats the fault isolation.
2. Add one entry to registry.yaml so it gets a card on the home page,
   including `category: tool` or `category: learn` (see registry.yaml's own
   header comment for which one — this decides whether the card is shown by
   default or only after the home page's "Show learning tools" toggle).
That's it — no Dockerfile, no docker-compose, no network changes needed;
it's all baked into this one image.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

logger = logging.getLogger("toolbox")

app = FastAPI(title="Toolbox", description="One-stop access to internal tools.")

_REGISTRY_PATH = Path(__file__).resolve().parent / "registry.yaml"

# Populated by _try_mount() below — name -> error message, for any tool whose
# import/mount failed. Read by the home page to show those cards as
# "temporarily unavailable" instead of pretending they don't exist.
_failed_tools: dict[str, str] = {}


def _try_mount(name: str, module_path: str) -> None:
    """Import one tool's module and mount its `app`, in isolation.

    The import happens HERE, inside the try, not as a top-level `from X
    import Y` — that's the whole point. A top-level import failing would
    crash main.py itself before the FastAPI app object even exists, taking
    every other tool down with it (this is a real single-process risk: one
    tool's bad code shouldn't be able to break tools that have nothing to
    do with it). If this tool fails, it's recorded in _failed_tools and
    simply isn't mounted — the rest of the site comes up normally.
    """
    try:
        module = importlib.import_module(module_path)
        tool_app = module.app
    except Exception as exc:  # noqa: BLE001 - deliberately broad: ANY failure in one tool must not crash the rest
        logger.exception("Tool '%s' (%s) failed to load — mounting skipped", name, module_path)
        _failed_tools[name] = str(exc)
        return
    app.mount(f"/tools/{name}", tool_app)


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict[str, Any]]:
    if not _REGISTRY_PATH.exists():
        return []
    data = yaml.safe_load(_REGISTRY_PATH.read_text()) or {}
    return data.get("tools", []) or []


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_card(tool: dict[str, Any]) -> str:
    icon = tool.get("icon", "🧰")
    title = _esc(tool.get("title", tool.get("name", "")))
    desc = _esc(tool.get("description", ""))
    name = tool.get("name")
    category = tool.get("category", "tool")  # missing category = "tool", the more common case
    search_text = _esc(f"{title} {desc}".lower())

    if name in _failed_tools:
        return f"""
    <div class="card card-unavailable" data-category="{category}" data-search="{search_text}">
      <div class="icon">{icon}</div>
      <div class="title">{title}<span class="badge badge-error">Unavailable</span></div>
      <div class="desc">Failed to load — check the container logs (docker-compose logs toolbox).</div>
    </div>"""

    badge = '<span class="badge">Learn</span>' if category == "learn" else ""
    href = f"/tools/{name}/"
    return f"""
    <a class="card" href="{href}" target="_blank" rel="noopener noreferrer" data-category="{category}" data-search="{search_text}">
      <div class="icon">{icon}</div>
      <div class="title">{title}{badge}</div>
      <div class="desc">{desc}</div>
    </a>"""


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    tools = _load_registry()
    cards = "".join(_render_card(t) for t in tools) or (
        '<p class="empty">No tools registered yet — add one to registry.yaml.</p>'
    )
    return HTMLResponse(_HOME_TEMPLATE.replace("{{CARDS}}", cards))


_HOME_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Toolbox</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #f4f6fb; --surface: #ffffff; --border: #dde1ef;
      --text: #1c2035; --muted: #6b7180; --accent: #4f5ef0;
    }
    body {
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: var(--bg); color: var(--text);
      min-height: 100vh; padding: 40px 20px;
    }
    header { max-width: 900px; margin: 0 auto 20px; }
    header h1 { font-size: 1.8rem; font-weight: 700; letter-spacing: -0.5px; }
    header h1 span { color: var(--accent); }
    header p { color: var(--muted); font-size: 0.9rem; margin-top: 4px; }

    .controls {
      max-width: 900px; margin: 0 auto 20px;
      display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    }
    .controls input[type="search"] {
      flex: 1; min-width: 200px; background: var(--surface); color: var(--text);
      border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px;
      font-size: 0.9rem; font-family: inherit;
    }
    .controls input[type="search"]:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
    .toggle-label {
      display: flex; align-items: center; gap: 6px; font-size: 0.85rem;
      color: var(--muted); white-space: nowrap; cursor: pointer;
    }
    .toggle-label input { width: auto; cursor: pointer; }

    .grid {
      max-width: 900px; margin: 0 auto;
      display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 16px;
    }
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 20px; text-decoration: none; color: inherit;
      display: flex; flex-direction: column; gap: 6px;
      transition: border-color 0.15s, transform 0.1s;
    }
    .card:hover { border-color: var(--accent); transform: translateY(-2px); }
    .card.hidden { display: none; }
    .card .icon { font-size: 1.8rem; }
    .card .title { font-weight: 700; font-size: 1.05rem; display: flex; align-items: center; gap: 8px; }
    .card .badge {
      background: var(--bg); color: var(--muted); border: 1px solid var(--border);
      border-radius: 5px; padding: 1px 7px; font-size: 0.68rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.4px;
    }
    .card .desc { font-size: 0.82rem; color: var(--muted); line-height: 1.5; }
    .card-unavailable { opacity: 0.6; cursor: not-allowed; }
    .card-unavailable:hover { border-color: var(--border); transform: none; }
    .badge-error {
      background: rgba(220,38,38,0.08); color: #b91c1c;
      border: 1px solid rgba(220,38,38,0.3); border-radius: 5px;
      padding: 1px 7px; font-size: 0.68rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.4px;
    }
    .empty { color: var(--muted); font-size: 0.9rem; max-width: 900px; margin: 0 auto; }
  </style>
</head>
<body>
  <header>
    <h1>Tool<span>box</span></h1>
    <p>One-stop access to internal tools</p>
  </header>
  <div class="controls">
    <input type="search" id="toolSearch" placeholder="Search tools by name or word…" />
    <label class="toggle-label">
      <input type="checkbox" id="showLearning" /> Show learning tools too
    </label>
  </div>
  <div class="grid" id="toolGrid">{{CARDS}}</div>
  <script>
  (function () {
    "use strict";
    var search = document.getElementById("toolSearch");
    var showLearning = document.getElementById("showLearning");
    var cards = Array.prototype.slice.call(document.querySelectorAll("#toolGrid .card"));
    if (!search || !showLearning || !cards.length) return;

    var STORAGE_KEY = "toolbox_show_learning";
    try {
      showLearning.checked = localStorage.getItem(STORAGE_KEY) === "true";
    } catch (e) {
      // private browsing / blocked storage — default (unchecked) is fine
    }

    function applyFilter() {
      var query = search.value.trim().toLowerCase();
      var includeLearning = showLearning.checked;
      cards.forEach(function (card) {
        var matchesSearch = !query || card.dataset.search.indexOf(query) !== -1;
        var matchesCategory = includeLearning || card.dataset.category !== "learn";
        card.classList.toggle("hidden", !(matchesSearch && matchesCategory));
      });
    }

    search.addEventListener("input", applyFilter);
    showLearning.addEventListener("change", function () {
      try {
        localStorage.setItem(STORAGE_KEY, showLearning.checked ? "true" : "false");
      } catch (e) {
        // ignore — filtering still works for this page view either way
      }
      applyFilter();
    });

    applyFilter();
  })();
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Mount every tool's own app under /tools/<name> — each in isolation, via
# _try_mount() above, so one tool's broken import can't take the rest down.
# ---------------------------------------------------------------------------

_try_mount("datadiff-pro", "api.app")
_try_mount("encode-decode", "encode_decode.server")
_try_mount("subnet-calc", "subnet_calc.server")
_try_mount("dns-lookup", "dns_lookup.server")
_try_mount("vlan-designer", "vlan_designer.server")
_try_mount("packet-journey", "packet_journey.server")
_try_mount("curl-builder", "curl_builder.server")
_try_mount("header-reference", "header_reference.server")
_try_mount("http-methods-status", "http_methods_status.server")
_try_mount("cookie-lab", "cookie_lab.server")
_try_mount("df-studio", "df_studio.server")
_try_mount("sql-studio", "sql_studio.server")
_try_mount("schema-map", "schema_map.server")
_try_mount("duck-lab", "duck_lab.server")
_try_mount("vault", "vault.server")

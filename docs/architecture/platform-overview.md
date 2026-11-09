# Platform overview — how the site is put together

> Moved **verbatim** from the root `CLAUDE.md` by roadmap session O3 (2026-11-10). The root keeps only the rules and an index;
> nothing was reworded. Paths in the text are repo-root relative.

# Repo direction: single-repo, single-container multi-tool website

This repo started as one tool (DataDiff Pro). The owner wants it to grow into
a **one-stop collection of internal tools** reachable through one shared home
page — potentially many tools over time, all served as **one bundled website
from one Dockerfile / one container**. This file exists so that as the repo
grows, future work stays consistent instead of drifting tool-by-tool.

**Direction changed 2026-10-24 — read `docs/roadmap/ROADMAP.md` and
`docs/architecture/ADR-001-workspace-plugins.md` first.** The owner asked for
Toolbox to become a **plugin workspace** for 1000+ tools: tools described by
manifests and loaded lazily, state moved out of process (Redis/Postgres/MinIO),
heavy tools in runtime images started on demand behind a gateway, shared tools
(DataDiff) scaled as APIs, multiple nodes later. Work happens in small numbered
sessions ("Roadmap: do session `<ID>`"); do only the named session and update
its status + handoff log.

**Since roadmap C2:** one repo, one Dockerfile, several images (build
targets). Compose runs `toolbox` = the **gateway** (workspace UI + proxy, no
tool code, the only host port), one container per runtime (`rt-light`,
`rt-data`, `rt-pgtools`, `rt-ssh`, `rt-notebook`, `rt-latex`, `rt-datadiff` ×2 — each
serving only the tools of its manifest `runtime:`), `singletons` (sql-studio
+ schema-map, one process, data image), `worker` (jobs, worker image),
`docker-proxy` (C3) and the state services. (An earlier per-tool-container idea was rejected by
the owner; the roadmap's runtime pools are deliberately different — a few
shared runtime images, not one container per tool.) Do not introduce
containers/gateway pieces outside the roadmap session that owns them.

## How it actually works

- `main.py` at the repo root is the **one entrypoint**. It defines the home
  page (`GET /`) and mounts every tool's own FastAPI `app` object under
  `/tools/<name>` using Starlette's `app.mount(...)` — an in-process ASGI
  mount, not a network call. No httpx, no proxy, no separate port per tool —
  except the `singleton: true` tools, which the web workers forward to the
  `singletons` process (`core_plugins/proxy.py`, roadmap B9).
- Each tool still lives in its own folder (`core/`, `api/`, `ui/` today for
  DataDiff) and keeps its own FastAPI `app` object fully self-contained and
  functional on its own — `main.py` just imports and mounts it.
- Each tool folder has a **`manifest.yaml`** (spec:
  `docs/architecture/plugin-manifest.md`). `main.py` calls
  `core_plugins.discover()` at startup: every valid manifest becomes a home
  card (ordered by `order`, then title) and every `kind: python` plugin is
  mounted from its `entry` (`module:app`). There is no hand-written mount
  list and no `registry.yaml` any more (removed in roadmap A2). A broken
  manifest is logged and skipped, never fatal.
- **Lazy loading (roadmap A3):** each tool is mounted as a `LazyApp`
  (`core_plugins/lazy.py`) and its module is imported on the tool's **first
  request**, not at startup — idle memory went from ~174 MB to ~32 MB
  (`docs/roadmap/measure-A3.md`). A failed import still breaks only that tool
  (503 page + "Unavailable" card). Consequence: anything a tool does at
  import time (e.g. `recover_interrupted()` in data-syncer/data-dumper/
  ssh-sftp, the ssh-sftp reaper thread) now runs on its first request — never
  put work in a tool's import that must happen before anyone opens it.
- **On/off switches:** `workspace.yaml` on the `workspace_data` volume
  (`/app/data/workspace/`, override with `TOOLBOX_WORKSPACE_FILE`;
  `core_plugins/workspace.py`). A tool set to `false` is never imported,
  hidden from the home page and answers a 404 "turned off" page. Missing file
  = every tool at its manifest's `enabled_by_default`; a broken file is
  logged and ignored.

- `GET /api/workspace/status` — per-tool state (`not_loaded`, `loaded`,
  `failed`, `disabled`), load time, errors. Never imports a tool.
- One `Dockerfile` copies every tool's code (including its `manifest.yaml`),
  `core_plugins/` and `main.py` into one image. One `docker-compose.yml`, one service,
  one port (`8000` on the host — deliberately not `8080`, which is commonly
  taken locally by other tools such as Jenkins).
- Each tool's frontend still calls its own API with **relative paths**
  (`fetch('compare', ...)`, not `fetch('/compare', ...)`). This is what
  lets the same page work whether it's mounted under `/tools/<name>/` or
  (if a tool is ever run standalone for dev/testing) at its own root — same
  reasoning as before, just no longer load-bearing for isolation, only for
  correctness of relative links.

## Current structure

```
datadiff-pro/                (repo root)
├── core/  api/  ui/          DataDiff Pro's own code — core/ is now also a
│                               shared library every tool imports from (pipeline,
│                               postgres_conn, pooled_postgres, file_source,
│                               vault); ui/'s own "Load from Vault" buttons are
│                               the one place a vault dataset is allowed into a
│                               browser, size-capped — see vault/CLAUDE.md
├── environments/  notebook/
├── main.py                    THE entrypoint — home page + mounts every tool
├── theme-tokens.css             canonical color palette — COPY-SOURCE only,
│                                  never served/linked, see its own header
├── Dockerfile                  build targets: full (default, what compose runs) + one per runtime (C1)
├── docker-compose.yml          one service, host port 8000
├── requirements.txt             full dependency set (the `full` image)
├── requirements/                per-runtime subsets: light, state, data, pgtools, ssh, latex, notebook (C1, N1)
├── README.md
├── CLAUDE.md                   (this file)
├── GITHUB_AUTH.md
├── tools/bench/baseline.py     roadmap benchmark (host-side): writes docs/roadmap/baseline.{md,json}
├── core_plugins/               plugin manifest model + discovery (spec: docs/architecture/plugin-manifest.md)
├── plugins/                    custom apps (static/external only), bind-mounted — see plugins/README.md
├── tests/unit/                 unit tests (no server needed) — `python3 -m pytest tests/unit -q`
├── tests/smoke/                smoke tests against the live server — run `scripts/smoke.sh`
│                                 (add every new tool to tests/smoke/test_api.py: API check or PAGE_ONLY)
├── scripts/smoke.sh            runner (`--no-browser` for the fast HTTP-only subset)
└── docs/
    ├── roadmap/ROADMAP.md      workspace roadmap: sessions, status, handoff log
    └── architecture/           decision records (ADR-001) and specs
```

Runtime: `docker-compose up --build -d` from the repo root. Open
**http://localhost:8000** for the home page; click a tool card to open it in
a new tab at `/tools/<name>/`.

## Finding your way around

`KNOWLEDGE_MAP.md` is the "I need to change X, where do I go" lookup table —
per-tool, symptom-to-file, plus the known non-obvious behaviors worth
knowing before touching certain code. Read it before exploring a tool's
files from scratch. Every tool added must get its own section there in the
same shape as DataDiff Pro's — this is what keeps navigation sane once the
repo has 10+ tools instead of 1. If you change what a file is responsible
for, update its row in that file in the same commit — a stale map actively
misleads, which is worse than no map.

# Toolbox — rules and index (read this first)

Toolbox is a **plugin workspace**: many small tools (each a folder with a `manifest.yaml`) behind one gateway on `http://localhost:8000`,
run with Docker Compose on one machine. This file is deliberately short: **rules + where to look**. Detail lives in the files named
below (moved there verbatim by roadmap session O3, 2026-11-10) — open the one that matches your task before editing anything.

## 1. Read order (do this before changing code)
1. This file. 2. `docs/roadmap/ROADMAP.md` — status table, fixed decisions, **Handoff log** (what was done last, what is left, gotchas).
3. If you work inside a tool: that tool's `CLAUDE.md` (rules, gotchas, history) and `KNOWLEDGE_MAP.md` (where each piece of logic lives).
4. The architecture doc for your topic (table in §3). 5. Only then open code.
Work happens in numbered sessions ("Roadmap: do session `<ID>`"): do **only** the named session, then tick its status and add 2–5 lines to the Handoff log.

## 2. Hard rules (each one comes from a past bug or an owner decision — do not "improve" them away)
**Process**
- **Never commit or push unless the owner says so.** Never run destructive commands (volume delete, `down -v`, prune, force-push) without asking.
- The owner is not a developer: explain in plain words, keep `docs/runbook.md` current when operations change.
- If a rule here does not fit a real situation, **stop and ask**, then record the answer in the right doc. Do not silently deviate.
- Do not add containers, gateway pieces or new services outside the roadmap session that owns them.
- Keep docs in sync in the same change: tool's `KNOWLEDGE_MAP.md` row, `CLAUDE.md`, `docs/runbook.md`, ROADMAP status + Handoff log.

**Code layout**
- Never edit `main.py` to add a tool: a tool is a folder with `manifest.yaml` (spec `docs/architecture/plugin-manifest.md`), mounted automatically.
- A tool's Python package name must be **unique** — never reuse `core` or `api`. Its frontend calls its own API with **relative paths** (`fetch('compare')`).
- Plugins talk over HTTP, never by importing each other (DataDiff is reached via `core/clients/datadiff.py`, never `core.pipeline`).
- Do not write a 4th DB connector, file loader, HTTP executor or secret store: reuse `core/` (see `docs/architecture/shared-connectors.md`).
- Do not do work at a tool's import time that must happen before anyone opens it: tools are imported lazily on first request.

**State and security**
- **No request may depend on this process's memory.** State goes to `core/state/` (Redis sessions, Postgres via `SqlStore`, S3 via `objects`/`FileCache`);
  long work goes to the `worker` (`core/jobs/runner.JobRunner`). Only `singleton: true` tools (sql-studio, schema-map) are single-process. (§5)
- Secrets only through `vault_store.scoped("<tool>")` and the kinds the manifest declares under `vault:` — a unit test fails on unscoped `core.vault` use.
  **Never generate a new `TOOLBOX_VAULT_KEY`** while secrets exist; `.env` must be backed up.
- Notebook runtime (`rt-notebook`) runs user code: it gets **no** Postgres/S3/Vault credentials. Keep it that way.
- SharePoint Lists has **no delete path** (owner decision, `graph._check_write`). Edits are staged and written only after a reviewed approval.
- The gateway's proxy client must **never keep cookies** (`core_plugins/proxy.py` `_no_cookie_jar`) — it once shared one visitor's session with the next.
- There is no auth on any route (local single-owner tool). Do not expose the port beyond localhost without adding it.

**Build**
- Every new Python dependency goes into `requirements.txt` **and** `requirements/<runtime>.txt`, then re-run `./download-wheels.sh` (offline builds).
- Classic Docker builder (no buildx): do not change how the `tex` stage starts (`FROM python:3.11-slim`, `WORKDIR`, TeX) or the 600 MB TeX layer is rebuilt.
- Recreating only the gateway with plain `up -d toolbox` starts every pool member; use `--no-deps`. Changing `docker_proxy_rules`
  needs `docker compose up -d --force-recreate docker-proxy`. Details: `docs/architecture/gateway-and-runtimes.md`.

## 3. Where to look (task → file)
| If you are… | Read |
|---|---|
| Adding or removing a tool | §4 below (`scripts/new_tool.py`, `scripts/remove_tool.py`); full checklist `docs/architecture/adding-a-tool.md`; the template `tools/_template/` |
| Changing how the site is wired: `main.py`, manifests, lazy loading, on/off switches, structure | `docs/architecture/platform-overview.md` |
| Touching the gateway, runtimes/images, on-demand start/stop, autoscaling, Status page, workspace UI, custom apps, installable app | `docs/architecture/gateway-and-runtimes.md` |
| Touching Redis/Postgres/S3, the Vault, `SqlStore`, background jobs, backups | `docs/architecture/state-jobs-vault.md` |
| Needing a DB / file / HTTP / SSH / secret helper | `docs/architecture/shared-connectors.md` |
| Making a tool stateful, or asking "why `--workers`/`singleton`?" | `docs/architecture/stateful-tools-and-workers.md` |
| Writing a manifest | `docs/architecture/plugin-manifest.md`; decisions: `docs/architecture/ADR-001-workspace-plugins.md` |
| Running/operating the stack (start, update, backup, restore, `.env`) | `docs/runbook.md` |
| Finding which file owns a behaviour (repo-wide) | `KNOWLEDGE_MAP.md`; per tool: `<tool>/KNOWLEDGE_MAP.md` |
| Working on one tool | `<tool>/CLAUDE.md` — DataDiff: `api/`; Vault Data loader: `data-lake/` (+ `vault/`); Notebook: `notebook-lab/`; SharePoint: `sharepoint-lab/` |
| Letting an AI client (Claude) use Toolbox: tools, safety rules, prod/non-prod labels, audit | `mcp_server/CLAUDE.md` and `docs/architecture/ADR-MCP.md` (rules are tested — do not weaken them) |
| Calling engines without a browser | `orchestrator/CLAUDE.md` (`docker compose exec worker python -m orchestrator.cli …`) |
| Measuring memory/speed | `tools/bench/baseline.py`, `docs/roadmap/measure-*.md` |
| Colors for a new page | `theme-tokens.css` (copy the six `:root` variables; never linked) |

## 4. Add a tool in 5 steps (full checklist and the reasons: `docs/architecture/adding-a-tool.md`)
1. **Scaffold it:** `python3 scripts/new_tool.py my-tool "My Tool" --icon 🧩 --description "What it does"` (add `--dry-run` first if unsure; `--runtime data` only for pandas / DuckDB / DB drivers).
   It copies `tools/_template/`, fills in the names, and makes the edits people forget: the Dockerfile `COPY` lines + package `__init__`, the smoke `API_CHECKS` line, `tests/smoke/test_my_tool.py`, the `KNOWLEDGE_MAP.md` index row. It is all-or-nothing and refuses names that collide with Toolbox / stdlib packages.
2. **Build it:** edit `my-tool/server.py` and `ui/index.html` — relative `fetch` paths, state outside the process (`core/state/`), secrets only through `vault_store.scoped` with the kinds declared in `manifest.yaml`. Prefer tier 1 (browser-only) designs. Never edit `main.py`; never reuse the names `core` / `api`.
3. **Packages:** a new Python package goes into `requirements.txt` AND `requirements/<runtime>.txt`, then `./download-wheels.sh`.
4. **Document it:** fill in the stubs `my-tool/CLAUDE.md` and `my-tool/KNOWLEDGE_MAP.md` so a future session can work from them alone.
5. **Verify:** `docker compose up -d --build`, `python3 -m pytest tests/unit -q`, `scripts/smoke.sh`; tick the roadmap session and add a Handoff line.
**Removing a tool:** `python3 scripts/remove_tool.py my-tool` is a **dry run** (prints what it would delete, what blocks it, what data it leaves). `--apply` does it (plus `--confirm my-tool` when the tool is enabled / unknown / has data;
`--remove-volumes` also deletes its Docker volume). It undoes exactly what `new_tool.py` adds, refuses while other code still uses the tool, and never touches Postgres / Vault / S3 data.
(A tool that is only a static page or a link needs no code at all: drop it in `plugins/`, see `plugins/README.md`. Your own Python plugin without rebuilding: P1, `TOOLBOX_TRUSTED_PLUGINS=1`.)

## 5. Stateful tools and workers — short form (full text and history: `docs/architecture/stateful-tools-and-workers.md`)
- The gateway runs `TOOLBOX_WEB_WORKERS` processes (1 on this machine since O1; image default 1, compose default 4); every stateful tool already keeps its state outside the process.
- A per-process *cache* is fine only if it can be rebuilt from shared state. `singleton: true` tools run in the single-process `singletons` service, reached through `core_plugins/proxy.py`.
- On/off switches and "is this tool loaded" are per-process by nature and handled in `main.py` (workspace.yaml mtime, Redis `toolbox:procs:*`).

## 6. Before you finish (verification)
- Unit tests (no server): `python3 -m pytest tests/unit -q` — on the host add `--ignore=tests/unit/test_sharepoint.py` (container-only).
- Live smoke tests: `scripts/smoke.sh` (`--no-browser` = fast HTTP-only). Tools switched off in Settings are **skipped**, not failed.
  Measure memory **before** running smoke (it loads every tool in every runtime).
- Rebuild/restart: `docker compose up -d --build`; logs: `docker compose logs rt-<runtime>`; a tool says "starting or unavailable" when its runtime container is down.
- Update ROADMAP status + Handoff log. Leave changes uncommitted unless told otherwise.

## 7. Architecture in one screen (details in §3 docs)
`toolbox` = **gateway** (workspace UI + reverse proxy, no tool code, the only host port 8000) → one container per runtime (`rt-light`, `rt-data`,
`rt-pgtools`, `rt-ssh`, `rt-notebook`, `rt-latex`, `rt-datadiff` pool) serving only the tools whose manifest `runtime:` matches; `singletons`
(sql-studio + schema-map); `worker` (RQ jobs); `docker-proxy` (limited Docker access); state: `redis`, `postgres`, `seaweedfs` (S3). Tiers: 1 browser-only,
2 light Python, 3 data-heavy, 4 special images (on-demand, sleep when idle). Direction and phases: `docs/roadmap/ROADMAP.md`, `ADR-001`.

## Operating notes (the owner is not a developer)

- **The owner's how-to is `docs/runbook.md`** (start/stop/update, backups,
  restore, troubleshooting, `.env` settings) — keep it current when operations
  change.

- One thing to start/stop: `docker-compose up --build -d` / `docker-compose
  down` from the repo root. No network setup, no per-tool containers (one
  container per runtime, a few in total). The start/stop commands stay the
  same. A tool shows "… is starting or unavailable" when its runtime
  container is down: `docker compose ps`, `docker compose logs rt-<runtime>`.
- Only commit when explicitly asked. Only push when explicitly asked. This
  has been the working agreement all along — it does not change as the repo
  grows.
- GitHub auth for this device is `gh` CLI over HTTPS with a daily forced
  logout (see `GITHUB_AUTH.md`) — that setup is device-level, unrelated to
  this repo's internal structure.
- If a decision here doesn't fit a real situation that comes up, stop and
  ask the owner rather than silently deviating — then update this file with
  the answer so the next session has it.

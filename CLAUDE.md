# Repo direction: single-repo, single-container multi-tool website

This repo started as one tool (DataDiff Pro). The owner wants it to grow into
a **one-stop collection of internal tools** reachable through one shared home
page — potentially many tools over time, all served as **one bundled website
from one Dockerfile / one container**. This file exists so that as the repo
grows, future work stays consistent instead of drifting tool-by-tool.

**Decision: one repo, one Dockerfile, one container.** No separate repo per
tool, no separate container per tool, no reverse proxy, no inter-container
network. An earlier iteration of this plan used separate containers per tool
behind a proxying gateway — the owner explicitly rejected that in favor of
one bundled process. Do not reintroduce multi-container/gateway architecture
without the owner asking for it again.

## How it actually works

- `main.py` at the repo root is the **one entrypoint**. It defines the home
  page (`GET /`) and mounts every tool's own FastAPI `app` object under
  `/tools/<name>` using Starlette's `app.mount(...)` — an in-process ASGI
  mount, not a network call. No httpx, no proxy, no separate port per tool.
- Each tool still lives in its own folder (`core/`, `api/`, `ui/` today for
  DataDiff) and keeps its own FastAPI `app` object fully self-contained and
  functional on its own — `main.py` just imports and mounts it.
- `registry.yaml` is display-only metadata for the home page cards (name,
  title, description, icon). It does **not** wire up routing — adding a
  tool still requires one `app.mount(...)` line in `main.py`. Don't confuse
  "registered in registry.yaml" with "actually wired up."
- One `Dockerfile` copies every tool's code plus `main.py` and
  `registry.yaml` into one image. One `docker-compose.yml`, one service,
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
├── registry.yaml               home-page card metadata (display only)
├── theme-tokens.css             canonical color palette — COPY-SOURCE only,
│                                  never served/linked, see its own header
├── Dockerfile                  builds the one image (copies every tool)
├── docker-compose.yml          one service, host port 8000
├── requirements.txt             shared dependency set for the whole image
├── README.md
├── CLAUDE.md                   (this file)
└── GITHUB_AUTH.md
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

## Headless recipes vs. a new tool

Not everything that calls into a tool's engine needs a web UI. `orchestrator/`
(see `orchestrator/CLAUDE.md`) is a plain Python package + CLI — no
`server.py`, no `ui/`, no `registry.yaml` entry, no `main.py` mount — for
composing existing engines (`core.pipeline`, duck-lab-style DuckDB reads, a
one-shot Postgres connector) directly, invoked as `docker compose exec
toolbox python -m orchestrator.cli ...`. Use it when the real need is "call
this logic without a browser" (e.g. diffing data that lives in a database,
not pasted text) — not a workflow engine, not a plugin system, just direct
function calls between modules that already run in the same process. If a
headless need later grows an actual UI requirement, that's when it becomes
a new tool under the checklist below, not before.

## Shared connectors — one Postgres connector, one file loader, one vault

Postgres-connecting logic (conninfo building, credential pre-validation,
SSH tunneling, password scrubbing) lives in exactly two places:
`core/postgres_conn.py` (the low-level primitives, including
`open_ssh_tunnel()`) and `core/pooled_postgres.py` (the pool+reaper
lifecycle built on top, used by sql-studio and schema-map — each still
builds its own separate instance, genuinely different connections, just
shared mechanics). The orchestrator's one-shot connector uses the
low-level primitives directly, skipping the pool (wrong shape for a
script that connects once and exits). File-extension-to-DuckDB-function
mapping lives in `core/file_source.py`, shared by duck-lab and the
orchestrator's file connector. **Don't add a fourth independent
implementation of either** — if a new tool needs to connect to Postgres
or read a CSV/JSON/Parquet file, it calls into these, the same way
duck-lab/sql-studio/schema-map/orchestrator already do.

`core/vault.py` is the shared, generic encrypted secret store (Fernet,
no master password by deliberate owner choice — see `vault/CLAUDE.md`
for the full trust-model writeup) behind the "Vault" tool's management
page. sql-studio and schema-map's Connection panels both have "Save this
connection"/"Load saved connection" controls calling `/tools/vault/...`
directly (same-origin, no proxy — see `schema-map/CLAUDE.md` Phase D for
the precedent), and the orchestrator's `--left-vault <name>` loads one
without an HTTP round-trip. Any future tool that wants to remember a
credential (or any other secret) should save it here under its own
`kind` tag, not invent a second store.

## Adding a new tool

(Followed twice already — Encode/Decode and Subnet Calculator — this is the
tested checklist, not a guess.)

1. New top-level folder for the tool's own code (its own `core`/`api`/`ui`
   equivalent — organize however fits that tool, doesn't need to mirror
   DataDiff's shape, doesn't need to be FastAPI, but it must expose an ASGI
   `app` object if it's Python/FastAPI-based so `main.py` can mount it the
   same way).
2. Its frontend calls its own API with relative paths (see above) — this is
   the one hard requirement for a page to work correctly when mounted under
   a path prefix.
3. Copy the six `:root` color variables from `theme-tokens.css` into the
   tool's own `<style>` block verbatim — this is the one thing every tool's
   palette should agree on. Everything else (status colors, tool-specific
   accents) is that tool's own call; see `theme-tokens.css`'s header for why
   this stays a copy, not a shared/served stylesheet.
4. **Give it a uniquely-named top-level Python package** — never reuse
   `core` or `api` (DataDiff Pro already owns those, grandfathered as-is).
   Namespace the tool's own code under its own folder name instead (see
   `encode-decode/` → copied into the image as `encode_decode/`, imported
   as `from encode_decode.server import app`). This is the one thing that
   actually breaks silently if skipped — two tools both exposing a top-level
   `core` package means whichever gets imported second in `main.py` wins,
   and the other tool's real code never runs.
5. In `main.py`: `from <tool_package>.<module> import app as <name>_app`,
   then `app.mount("/tools/<name>", <name>_app)`.
6. One entry in `registry.yaml` so it gets a home-page card, including
   `category: tool` or `category: learn` (see `registry.yaml`'s own header
   comment — decides whether the card is shown by default on the home page
   or only after the "Show learning tools" toggle).
7. Add its dependencies to the root `requirements.txt` (watch for version
   conflicts with existing tools' dependencies — since everything now
   shares one Python environment, this is the real cost of the "one
   container" tradeoff; a genuine conflict is the signal to reconsider, not
   something to route around silently). If a tool needs no Python packages
   beyond what's already there (e.g. a pure client-side tool like
   Encode/Decode), this step is a no-op — nothing to add.
8. Update `KNOWLEDGE_MAP.md` with this tool's section.
9. **Add a `CLAUDE.md` inside the tool's own folder** — short, scoped to
   just that tool (what it does, where each piece of logic lives, its own
   gotchas), pointing back to this file and `KNOWLEDGE_MAP.md` for anything
   repo-wide. This is what lets a future session opened directly inside
   `<tool>/` get oriented without pulling in every other tool's context
   first. See `encode-decode/CLAUDE.md` or `subnet-calc/CLAUDE.md` for the
   shape to copy.
10. Rebuild the one image: `docker-compose up --build -d`.

## Standing rule: stateful tools and `--workers`

The container runs uvicorn with **`--workers 1`**, pinned in `Dockerfile`.
This is because DataFrame Studio keeps its session state (the uploaded
DataFrame, the pipeline of steps) in a plain in-memory Python dict —
`engine.SESSIONS` in `df-studio/engine.py`. With more than one worker,
uvicorn runs separate OS processes that don't share memory, so a session
created by one request can be invisible to the next request if it lands on
a different worker — this happened for real once (see `df-studio/CLAUDE.md`)
and looked like random, unexplained "session not found" errors.

SQL Studio's live database connection (`sql-studio/db_engine.py`,
`STATE`) is a second, independent instance of the same constraint — a
single module-level global holding the active Postgres connection pool,
not a per-cookie dict (see `sql-studio/CLAUDE.md` for why it deliberately
does NOT copy df-studio's per-cookie shape). The failure mode here is
worse than a lost DataFrame: with >1 worker, "Connect" landing on one
worker would be invisible to "Run" landing on another, and an orphaned
pool means real, live connections held open against a real external
database (visible in that database's own `pg_stat_activity`, consuming
its connection-limit budget) until something notices and kills it — not
just an inert lost value in memory.

Duck Lab's loaded files + DuckDB connection (`duck-lab/engine.py`,
`SESSIONS`) are a **third** instance of this — it deliberately copies
df-studio's per-cookie-dict shape (not SQL Studio's single global), because
each browser tab legitimately wants its own independent set of loaded
files, the same reasoning df-studio uses. See `duck-lab/CLAUDE.md`.

**Decided now, before it comes up again:** any future tool that needs
multi-step or multi-request state (not just "read a form, compute an
answer, done" — something closer to df-studio's upload-then-edit model)
must NOT just add another in-memory dict and assume `--workers 1` covers
it forever. Either it reuses/extends `engine.SESSIONS`'s pattern
consciously, or — if `--workers` genuinely needs to go up for performance
reasons someday — that tool needs a real shared session store (Redis,
SQLite, a session-scoped temp file, anything actually shared across
processes) first. Don't raise `--workers` without checking this against
every stateful tool that exists at the time, not just the one you're
adding.

## Operating notes (the owner is not a developer)

- One thing to start/stop: `docker-compose up --build -d` / `docker-compose
  down` from the repo root. No network setup, no per-tool containers.
- Only commit when explicitly asked. Only push when explicitly asked. This
  has been the working agreement all along — it does not change as the repo
  grows.
- GitHub auth for this device is `gh` CLI over HTTPS with a daily forced
  logout (see `GITHUB_AUTH.md`) — that setup is device-level, unrelated to
  this repo's internal structure.
- If a decision here doesn't fit a real situation that comes up, stop and
  ask the owner rather than silently deviating — then update this file with
  the answer so the next session has it.

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

**Until phase C of the roadmap lands, the old rule still describes the running
system:** one repo, one Dockerfile, one container, no reverse proxy, no
inter-container network. (An earlier per-tool-container idea was rejected by
the owner; the roadmap's runtime pools are deliberately different — a few
shared runtime images, not one container per tool.) Do not introduce
containers/gateway pieces outside the roadmap session that owns them.

## How it actually works

- `main.py` at the repo root is the **one entrypoint**. It defines the home
  page (`GET /`) and mounts every tool's own FastAPI `app` object under
  `/tools/<name>` using Starlette's `app.mount(...)` — an in-process ASGI
  mount, not a network call. No httpx, no proxy, no separate port per tool.
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
- **Workspace UI (roadmap A4):** `/` serves `core_plugins/ui/workspace.html`
  — sidebar (search, Ctrl+K, Tools/Learning groups, load-state dots), tools
  open in **tabs** (iframes of `/tools/<name>/`, kept alive while open,
  restored from localStorage, deep links `/#/tool/<name>`), Home tab = the
  card grid, Settings tab = on/off switches. Each tool is mounted through a
  `Slot` (`core_plugins/lazy.py`), so `POST /api/workspace/plugins/<name>`
  `{"enabled": bool}` turns it on/off **immediately** and saves
  `workspace.yaml` — no restart. Only freeing the memory of a tool that was
  already loaded needs a restart (Python can't unload modules); the UI says
  so. These endpoints have no auth, like every other Toolbox route (local,
  single-owner tool).
- **Custom apps (roadmap A5):** `plugins/` (bind-mounted read-only at
  `/app/plugins`, `TOOLBOX_PLUGINS_DIR`) holds `kind: static` / `kind:
  external` plugins — added with a restart, no rebuild (`plugins/README.md`).
  Python plugins are **refused** there by the loader. Static apps are served
  sandboxed (CSP `sandbox` without `allow-same-origin`): their JS runs but
  cannot call Toolbox APIs/Vault. The two samples ship `enabled_by_default:
  false`.
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
├── Dockerfile                  builds the one image (copies every tool)
├── docker-compose.yml          one service, host port 8000
├── requirements.txt             shared dependency set for the whole image
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

## Headless recipes vs. a new tool

Not everything that calls into a tool's engine needs a web UI. `orchestrator/`
(see `orchestrator/CLAUDE.md`) is a plain Python package + CLI — no
`server.py`, no `ui/`, no `manifest.yaml`, no `main.py` mount — for
composing existing engines (`core.pipeline`, duck-lab-style DuckDB reads, a
one-shot Postgres connector) directly, invoked as `docker compose exec
toolbox python -m orchestrator.cli ...`. Use it when the real need is "call
this logic without a browser" (e.g. diffing data that lives in a database,
not pasted text) — not a workflow engine, not a plugin system, just direct
function calls between modules that already run in the same process. If a
headless need later grows an actual UI requirement, that's when it becomes
a new tool under the checklist below, not before.

## Shared connectors — one multi-database connector, one file loader, one vault

**Multi-database support (Postgres/SQL Server/Oracle)** lives behind
`core/db/dialect.py`'s `Dialect` protocol — one concrete class per
database (`core/db/dialect_postgres.py`, `dialect_mssql.py`,
`dialect_oracle.py`) implementing conninfo-building, pool open/checkout/
close, the row-cap SQL template, and introspection (`schema_fetch_query()`
plus 11 SQL-text-returning methods — `list_tables_sql()`,
`list_functions_sql()`, `list_foreign_keys_sql()`, etc. — symmetric
across all three databases, not just Postgres). `core/db/registry.py`'s
`get_dialect(db_type)` is the one lookup point from a `"postgres"`/
`"mssql"`/`"oracle"` string to a `Dialect` instance. `core/pooled_db.py`'s
`PooledDbConnection` is the generalized pool+reaper lifecycle built on
top — dialect-agnostic, parametrized by whichever `Dialect` a given
`connect()` call passes in. **This is the precedent any future tool
needing more than one database type should extend** — SQL Studio
(`sql-studio/db_engine.py`/`query_guard.py`) is the first and so far
only consumer that lets the dialect vary per connection; don't hand-roll
a fourth connector or a second dialect-dispatch mechanism.

`core/postgres_conn.py` (conninfo/verify primitives) and
`core/pooled_postgres.py` (now a thin subclass of `PooledDbConnection`
with `PostgresDialect` fixed as its default — see that file's own
docstring) still exist exactly as before, backward-compatible: schema-map
and the orchestrator's one-shot connector only ever talk to Postgres, so
they keep using these directly, unaware anything underneath changed.
File-extension-to-DuckDB-function mapping lives in `core/file_source.py`,
shared by duck-lab and the orchestrator's file connector. A bounded,
streaming, async outbound HTTP executor (timeout + response-size cap,
never buffers an unbounded response) lives in `core/http_exec.py`,
built for cURL Builder's "Run" feature but kept generic/reusable there
rather than tool-local, same reasoning as everything else in this
section. **Don't add a fourth independent implementation of any of
these** — if a new tool needs to connect to a database, read a
CSV/JSON/Parquet file, or make an outbound HTTP request, it calls into
these, the same way duck-lab/sql-studio/schema-map/orchestrator/
curl-builder already do.

Data Syncer (`data-syncer/`) is a **consumer of these, not a new
connector**: it resolves Vault entries via `core.vault`, opens (optionally
SSH-tunnelled) connections with `core.postgres_conn`'s primitives, and puts
its own write-side database operations (COPY/upsert, key-range chunking —
things `Dialect` has no notion of) behind a small per-database class in
`data-syncer/sync_ops.py`. A new database engine means a new class there.

`core/db_endpoint.py` is the shared **Vault entry → live connection**
helper (SSH tunnel aware, reconnectable, exposes the tunnel-aware host/port
for subprocess clients like `pg_dump`) used by Data Syncer and Schema Copy —
it was extracted from `data-syncer/connections.py` (now a thin re-export)
when the second consumer appeared, per this section's "don't add another
independent implementation" rule.

`core/pgclient.py` runs the **bundled `pg_dump`/`pg_restore`/`psql`** (Dockerfile stage `pgclient`)
as subprocesses — cancel-aware, streaming stderr, credentials via `PGPASSWORD` only — and
`core/pg_inspect.py` holds the small shared catalog helpers (server version, empty-target check,
available extensions). Both were extracted from Schema Copy when Data Dumper became the second
consumer (`schema-copy/pgtools.py` is a thin re-export), per this section's rule.

`core/ssh_client.py` opens **host-key-pinned SSH/SFTP connections from a Vault `ssh_server` entry** (no agent,
no ~/.ssh, timeouts + keepalives, plain scrubbed errors) for the SSH & SFTP tool and the Vault's "Add SSH
server" form. The DB tools' SSH *tunnels* (`core/postgres_conn.py`) are a different, older path and are
deliberately untouched.

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

> Updated in roadmap **A2**: tools are plugins with a `manifest.yaml`; there is
> no mount list in `main.py` and no `registry.yaml`. Prefer **client-side
> (tier 1)** designs when a tool can run in the browser — they cost the server
> nothing.

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
5. Add **`<tool>/manifest.yaml`** (spec: `docs/architecture/plugin-manifest.md`):
   `name`, `title`, `description`, `icon`, `category` (`tool` or `learn` —
   `learn` cards are hidden until the home page's "Show learning tools"
   toggle), `kind: python`, `entry: <tool_package>.server:app`, `runtime`,
   `tier`, `state`, `depends_on`, `requires`, `order`. `main.py` mounts it
   automatically — **do not edit `main.py`**. If the Dockerfile copies the tool
   file-by-file, also `COPY <tool>/manifest.yaml ./<tool_package>/manifest.yaml`
   (`tests/unit` checks this).
6. Add it to `tests/smoke/test_api.py` — an `API_CHECKS` entry (read-only, no
   outside systems) or `PAGE_ONLY` — then run `python3 -m pytest tests/unit -q`
   and `scripts/smoke.sh`.
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

Data Syncer (`data-syncer/runner.py`) is a **fourth** instance: each sync
runs on a background thread, and the job registry plus the log ring buffer
live in that one process's memory. Its durable progress (per-table resume
positions) is in SQLite and survives anything, but "is a run alive right
now" and the log tail do not — with >1 worker a Start on one process would be
invisible to the status poll on another. See `data-syncer/CLAUDE.md`.

Schema Copy (`schema-copy/runner.py`) is a **fifth**, same shape as Data
Syncer: a background thread plus an in-process job registry/log tail; the last
run's result is durable in SQLite. See `schema-copy/CLAUDE.md`.

Data Dumper (`data-dumper/runner.py`) is a **sixth**, same shape: a background thread plus an
in-process job registry/log tail; the dump catalogue and run history are durable in SQLite and the
dump files on a volume. See `data-dumper/CLAUDE.md`.

SSH & SFTP (`ssh-sftp/sessions.py`, `runner.py`) is a **seventh**: a per-server connection cache and an
upload/command job registry live in memory; transfer/command history is in SQLite and staged uploads on a
volume. See `ssh-sftp/CLAUDE.md`.

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

**Roadmap:** phase B moves all seven stateful tools' state out of process
(B2–B8: Redis sessions, Postgres records, MinIO files, RQ jobs) and **B9** lifts
the `--workers 1` pin. Until B9 is ticked in `docs/roadmap/ROADMAP.md`, keep
`--workers 1`. New stateful tools added after B1 must use `core/state/`
(Redis/Postgres/MinIO), not a new in-memory dict.

## Operating notes (the owner is not a developer)

- One thing to start/stop: `docker-compose up --build -d` / `docker-compose
  down` from the repo root. No network setup, no per-tool containers.
  (Phase B adds Redis/Postgres/MinIO services to the same compose file and
  phase C adds runtimes; the start/stop commands stay the same.)
- Only commit when explicitly asked. Only push when explicitly asked. This
  has been the working agreement all along — it does not change as the repo
  grows.
- GitHub auth for this device is `gh` CLI over HTTPS with a daily forced
  logout (see `GITHUB_AUTH.md`) — that setup is device-level, unrelated to
  this repo's internal structure.
- If a decision here doesn't fit a real situation that comes up, stop and
  ask the owner rather than silently deviating — then update this file with
  the answer so the next session has it.

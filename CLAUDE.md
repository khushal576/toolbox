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
- **Workspace UI (roadmap A4):** (since L5, owner: inside a tool the tab bar is the navigation — the sidebar is
  off-canvas, ☰ / Ctrl+K opens it, Esc closes; `body.in-tool`) `/` serves `core_plugins/ui/workspace.html`
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
- **State services (roadmap B1):** compose also runs `redis`, `postgres`
  (Toolbox's OWN records, db/user `toolbox`) and `seaweedfs` (S3-compatible
  files) with named volumes, not published on host ports. Code reaches them
  only through `core/state/` (`db`, `sessions`, `objects`, `health()`) and the
  `TOOLBOX_*` env vars in `core/state/config.py` — to use an existing Postgres,
  set `TOOLBOX_DATABASE_URL` in a `.env` file (dedicated `toolbox` database).
  Check with `GET /api/state/health` or
  `docker compose exec toolbox python -m core.state.selftest`. Defaults are
  local-only passwords; override `TOOLBOX_DB_PASSWORD`,
  `TOOLBOX_S3_ACCESS_KEY`, `TOOLBOX_S3_SECRET_KEY` in `.env`.
- **Gateway (roadmap C2):** `toolbox` runs the `gateway` image (241 MB, no
  tool libraries) in the web role with `TOOLBOX_RUNTIME_URLS`; every python
  tool is a `ProxyApp` to `rt-<runtime>` (singletons → `singletons`).
  Static/external custom apps are still served by the gateway. Host header,
  cookies, path and query pass through; bodies stream both ways (verified: a
  144 MB upload and a 150 MB export through it). `/api/state/health` is
  answered by `rt-data` (the probes' libraries would cost every gateway
  worker ~25 MB). No tool uses WebSockets; the proxy refuses them. The
  headless CLI now runs in the worker: `docker compose exec worker python -m
  orchestrator.cli …`.
- **DataDiff as a shared service (roadmap D1):** runtime `datadiff` (own
  188 MB image, `rt-datadiff` with 2 replicas behind the gateway — one can be
  stopped or killed and every request still succeeds). Versioned API
  `/api/v1/compare`, `/api/v1/compare/structured`, `/api/v1/health` (names
  the replica), OpenAPI at `/tools/datadiff-pro/docs`; `/compare` stays as an
  alias. Other code calls it through `core/clients/datadiff.py` — never
  `core.pipeline` directly (unit test). The worker's orchestrator uses it via
  `TOOLBOX_DATADIFF_URL`. **Background compares (roadmap D2):** `POST
  /api/v1/jobs` stores the input in S3 storage and queues `api.jobs.run_job`
  for the `worker`; status in the job's Redis channel, gzipped result in S3
  (`datadiff/<id>/…`, kept 7 days) — any replica answers `GET
  /api/v1/jobs/{id}` and `/result`; `DELETE` cancels (a running diff can't be
  interrupted, its result is discarded). The page uses it automatically for
  > 2 MB of input; client `submit_*`/`wait`; CLI `--background`.
- **Vault Data / lake catalog (roadmap L1):** `core/lake.py` — workspaces →
  tables (Glue-Catalog-like), catalog in Postgres (schema `lake`), managed
  tables as Parquet in S3 storage (`lake/<table id>/<id>.v<n>.<part>.parquet`,
  by id: renames never move files; a new version is switched to only after its
  files are stored). The Vault page's **📦 Data** tab is the front door
  (Secrets stay encrypted, data is plain Parquet — owner decision). Tools use
  `lake.scoped("<tool>")` with manifest `vault: {data: none|read|write}`. Old
  Vault datasets are imported once into workspace `datasets`. Phase L plan
  (load files L2, SQL L3, every tool L4): `docs/roadmap/ROADMAP.md`. **L2:**
  new tool **Data Lake** (`data-lake/`, runtime data) loads uploads, the
  shared **data folder** (`~/toolbox-data` → `/data` read-only in rt-data +
  worker, `TOOLBOX_DATA_DIR`), links and patterns into tables — worker job,
  DuckDB streams to Parquet with a memory cap (1.5 GB CSV → 530 MiB peak);
  external tables read in place. `core/file_source.py` gained the multi-file
  reader + content sniffing; Excel via `openpyxl` (data/worker images). **L3:**
  Data Lake's **🔎 SQL** tab (`data-lake/query.py`) — Athena style: only the
  tables a query names are mounted as `workspace.table` views in a fresh DuckDB;
  read-only checked on DuckDB's parse tree (no file-reading functions — the
  container's files incl. `/proc` stay out of reach); Run = 30 s in rt-data,
  Run in background = worker job; every result stored as Parquet in S3 (7 days)
  for paging/download/"save as table"; `CREATE TABLE ws.t AS SELECT`; history +
  saved queries in Postgres schema `data_lake`. **L4:** every data tool lists
  tables (Vault `GET /data/catalog`) and saves to `workspace.table`
  (`lake.export_table` / `import_file`; Duck Lab, DataFrame Studio ≤ 1 M rows,
  SQL Studio full result + import into a DB, DataDiff ≤ 2000 rows); Data Lake →
  🗄 Database stages tables from a Vault connection (`data-lake/staging.py`,
  worker job, read-only source). **Gotcha fixed in L4:** the gateway's proxy
  client must never keep cookies (`core_plugins/proxy.py` `_no_cookie_jar`) —
  it used to hand one visitor's tool session cookie to the next. **L5:**
  column profiles (`lake.profile`, cached per version), suggested joins checked
  on the data (`lake.suggest_joins`), charts in Data Lake SQL, **S3 locations**
  (Vault kind `s3_location` → temporary bucket-scoped DuckDB secret,
  `lake.prepare(con, table)` before reading; httpfs baked into data + worker
  images), SQL-style column types everywhere (`lake.sql_type`, staged tables keep
  the source DB's declared types). Owner decisions in L5: inside a tool the
  workspace sidebar slides away (☰/Ctrl+K); Duck Lab and DataFrame Studio take
  data ONLY from Vault Data (Athena-style Tables bar; files come in through Data
  Lake) — DataFrame Studio joins other tables by name.
- **Notebook (roadmap N1):** `notebook-lab/` — Colab-style workspaces + Jupyter kernels in its OWN runtime `rt-notebook`
  (on-demand, one uvicorn worker, volume `notebook_data`). It executes user code, so that container has **no
  Postgres/S3/Vault credentials** (compose gives it only `TOOLBOX_REDIS_URL` and a bridge URL) — keep it that way; see `notebook-lab/CLAUDE.md`.
- **SharePoint Lists (roadmap S1):** `sharepoint-lab/` (runtime `data`) — many SharePoint sites via Microsoft Graph, connections in the
  Vault (kind `sharepoint_connection`), edits are STAGED (Postgres schema `sharepoint_lab`) and written only after a reviewed approval
  (digest-checked, conflict-checked, audited); **no delete anywhere** (owner decision — `graph._check_write`). Python staging from a
  notebook through `notebook-lab/lib/toolbox_sharepoint.py`; `rt-notebook` still has no credential (it gets a URL, `SP_BRIDGE_URL`).
  See `sharepoint-lab/CLAUDE.md`.
- **Installable app (roadmap G1):** the gateway serves `/manifest.webmanifest`
  (standalone display, Status/Settings shortcuts), `/icons/<file>` (four
  known PNGs from `core_plugins/ui/icons/`, drawn by
  `tools/icons/make_icons.py`) and `/favicon.ico`; `workspace.html` links them.
  Chromium offers "Install Toolbox" (verified: no installability errors) —
  an app window onto the running stack, nothing else (no Electron, G2
  deferred). How to install: `docs/runbook.md` §1.
- **Backups (Ops session):** `scripts/backup.sh` → one dated archive in
  `backups/` (git-ignored, mode 600): Postgres dump (pg_dump in a one-off
  `docker compose run` of the worker), every S3 object (`core/state/backup.py`
  streams a tar), `.env` (Vault key!), `workspace.yaml`; keeps the last 7.
  `scripts/restore.sh <file>` stops the tool containers, `pg_restore --clean
  --single-transaction`, replaces the bucket, puts `.env`/settings back,
  starts everything. Tested by restoring into a second compose project
  (`COMPOSE_PROJECT_NAME=toolbox-restoretest TOOLBOX_HOST_PORT=8001`). The
  Status page shows the last backup (Redis `toolbox:backup:last`) and nags
  after 7 days. Owner how-to: **`docs/runbook.md`**. Two copies of the stack can
  run side by side: supervisor/autoscaler/balancer filter Docker by THIS
  project and ignore `docker compose run` one-offs (`core_plugins/dockerapi.py`).
- **Status page (roadmap E1):** workspace tab **📊 Status** (`#/status`) —
  containers (state, health, CPU, memory vs limit, uptime, restarts), state
  services, scaling/on-demand, tools, background jobs per tool (+ recent
  crashes), storage (S3 per tool, Postgres per schema) and an "attention"
  list. Data: `GET /api/workspace/overview` (gateway: Docker part via
  docker-proxy, read-only; `/api/state/overview` = jobs/storage/state answered
  by rt-data, `core_plugins/overview.py`). Polls every 5 s only while the tab
  is visible; nothing stored; no new containers (owner chose this over
  Prometheus/Grafana — revised phase E in the roadmap). **E2:** the gateway
  wraps every tool mount in `metrics.Metered` (`core_plugins/metrics.py`):
  requests / 5xx / slow (first byte > `TOOLBOX_SLOW_MS`, 2 s) per tool, summed
  in-process and flushed to Redis every 5 s (`toolbox:m:*`, minute buckets 2 h,
  hour buckets 26 h) → "Traffic per tool" with 60-minute sparklines. **E3:**
  the same wrapper keeps the last 50 5xx answers (`toolbox:errors`, 7 days) →
  "Recent errors"; a "logs" button per container shows its last 200 lines
  (`/api/workspace/logs/<name>`, project containers only, docker-proxy
  read-only `/logs` rule); `/api/workspace/alerts` (cheap: no stats) feeds a
  red/amber count on the sidebar's Status item every 60 s.
- **Autoscaling + balancing (roadmap D3):** compose creates a POOL
  (`deploy.replicas` = max: rt-datadiff 4, worker 3); the supervisor leader
  keeps between min and max running by starting/stopping pool members
  (`core_plugins/autoscale.py`): rt-datadiff by CPU (Docker stats; > 60 % →
  +1, < 15 % for 45 s → −1; manifest `scaling: {min: 2, max: 4}`), workers by
  queue length (`TOOLBOX_WORKER_SCALING=1:3`; only IDLE workers are stopped).
  20 s cooldown after each change. The gateway round-robins each request over
  running + healthy replicas (`core_plugins/balancer.py`, refreshed every 3 s)
  and retries another replica on a refused connection. State in
  `/api/workspace/runtimes` → `scaled`. **Gotchas:** compose does NOT recreate
  `docker-proxy` when only its inline `docker_proxy_rules` change — run
  `docker compose up -d --force-recreate docker-proxy`; recreating the gateway
  with plain `up -d toolbox` starts every pool member again (depends_on) —
  use `--no-deps`, or let the autoscaler bring them back down; a recreated
  gateway waits up to 45 s for the old leader lock to expire.
- **On-demand runtimes (roadmap C3):** `rt-latex`, `rt-pgtools`, `rt-ssh`, `rt-notebook`
  (all-tier-4 runtimes) sleep when idle: the gateway's supervisor
  (`core_plugins/supervisor.py`) stops a container after its manifests'
  `scaling.idle_timeout_s` (900 s) without traffic and starts it again on the
  next request, which waits for `/healthz` (~1–2 s). Activity is shared in
  Redis (`toolbox:sup:last:*`, touched while downloads stream); one gateway
  worker leads the sweep (`toolbox:sup:leader`). Docker only via the
  `docker-proxy` service with our own HAProxy rules: list/inspect + start/stop
  of `*-rt-<runtime>-<n>` containers, everything else 403 (verified). Limits:
  compose `mem_limit`/`cpus` = sum of manifest `resources`. UI: grey ring =
  asleep, pulsing amber = starting; `GET /api/workspace/runtimes`. `docker
  compose up -d` starts everything; idle runtimes go back to sleep.
- **Runtime images (roadmap C1):** the Dockerfile has a target per manifest
  `runtime:` — `light` (187 MB), `data` (629 MB, also hosts the Vault),
  `pgtools` (267 MB, bundled pg_dump), `ssh` (249 MB), `latex` (746 MB) —
  each installs only `requirements/<runtime>.txt` and runs `main.py` with
  `TOOLBOX_ROLE=runtime` + `TOOLBOX_RUNTIME`, mounting only its own plugins
  (singletons never). `full` (1.2 GB, all of it) stays the default target and
  is no longer run by compose (C4): the `worker` has its own `worker` target
  (all packages + pg_dump, no TeX, 647 MB). Only `rt-latex` carries TeX Live
  (`tests/unit/test_runtimes.py` enforces it). Since C2 the rt-* services run
  by default behind the gateway (no host ports). Memory/disk per container:
  `docs/roadmap/measure-C4.md`. Classic builder (no buildx here):
  packages install in throw-away `deps-*` stages with `pip --prefix`, and the
  `tex` stage must start exactly like before (`FROM python:3.11-slim`,
  `WORKDIR`, TeX) or the ~600 MB TeX Live layer is downloaded again.
- **Vault (roadmap B7):** secrets in Postgres (schema `vault`), dataset
  blobs in S3 storage, key from `TOOLBOX_VAULT_KEY` in the git-ignored
  `.env` (back that file up — without it the Vault can't be decrypted).
  Tool code reaches secrets only via `vault_store.scoped("<tool>")`, limited
  to the kinds its manifest declares under `vault:`; a unit test fails if a
  tool imports `core.vault` unscoped. See `vault/CLAUDE.md`.
- **Tool records in Postgres (roadmap B6):** schema-map, data-syncer,
  schema-copy, data-dumper and ssh-sftp keep their tables in Toolbox's
  Postgres, one schema each (`schema_map`, `data_syncer`, …), through
  `core/state/sqlstore.py` (`SqlStore`: sqlite3-shaped API — `?`
  placeholders, `row["col"]`, one transaction per `with connect()`; SQLite
  when run standalone). On first start each tool copies its old SQLite file in
  once (`<schema>._meta` records it; the file stays as a backup). New tools
  with small relational state use `SqlStore` too. Gotcha: store queries run
  with `prepare=False` — the same SQL text in two tools' schemas must never
  share a prepared plan on a pooled connection.
- **Background jobs (roadmap B4):** the `worker` service (same image,
  `python -m core.jobs.worker`) runs long jobs from the Redis queue via
  `core/jobs/` (`Channel` = heartbeat "alive" key + log tail + stop flag +
  meta, `enqueue`, `StopFlag`). A web restart never kills a job; scale with
  `docker compose up -d --scale worker=N`. `/api/state/health` reports
  `jobs` (workers listening, jobs waiting) — no worker = not ok. Jobs run the
  same tool code, so the worker mounts the same data volumes. New job-running
  tools use `core/jobs/runner.py` (`JobRunner`: queue mode + thread fallback,
  log tail, progress, stop — B5) and keep files in S3 storage with
  `core/state/filecache.py` (`FileCache`: publish / fetch / remove_all, local
  cache trimmed to a budget). The worker clears its own stale Redis
  registration on start (a killed worker used to crash-loop on restart).
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

## Headless recipes vs. a new tool

Not everything that calls into a tool's engine needs a web UI. `orchestrator/`
(see `orchestrator/CLAUDE.md`) is a plain Python package + CLI — no
`server.py`, no `ui/`, no `manifest.yaml`, no `main.py` mount — for
composing existing engines (DataDiff through its client since D1,
duck-lab-style DuckDB reads, a one-shot Postgres connector), invoked as
`docker compose exec worker python -m orchestrator.cli ...` (since C2). Use it when the real need is "call
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
   Encode/Decode), this step is a no-op — nothing to add. **Since roadmap
   C1** also add the same pin line to `requirements/<runtime>.txt` for the
   tool's manifest `runtime:` (`tests/unit/test_runtimes.py` checks the pins
   match and that every package is used by some runtime), then rebuild the
   wheelhouse (`./download-wheels.sh`) if the package is new.
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

**Since roadmap B9 the web app runs several worker processes** (`TOOLBOX_WEB_WORKERS`, default 4 in compose;
the image's own default is 1 for a bare `docker run`). That is safe ONLY because every stateful tool keeps its
state outside the process — and it must stay that way:

- **Rule for every tool, existing or new:** no request may depend on something an earlier request left in
  this process's memory. Multi-request state goes to `core/state/` (Redis sessions, Postgres via `SqlStore`,
  S3 via `objects`/`FileCache`), long work goes to the `worker` service (`core/jobs/runner.JobRunner`),
  secrets to the Vault (`vault_store.scoped(...)`). Per-process *caches* are fine if they can be rebuilt from
  the shared state (df-studio's LRU, duck-lab's local DuckDB copies, ssh-sftp's browse connections).
- **Exception: `singleton: true` plugins** (sql-studio, schema-map — one live DB pool, password never stored,
  owner decision in B3) run in the separate `singletons` service (same image, `TOOLBOX_ROLE=singletons`, one
  process, never scaled); every web worker forwards their `/tools/<name>/` traffic there through
  `core_plugins/proxy.py` (`ProxyApp`, streams both ways, 503 page if that process is down). A new tool that truly
  needs one process gets `singleton: true` — it doesn't pin the whole app to one worker.
- **Things that are per process by nature, handled in `main.py`:** the on/off switches (every worker re-reads
  `workspace.yaml` when its mtime changes — at most 1 s behind) and "is this tool loaded" (each process
  publishes its loaded/failed tools to Redis, `toolbox:procs:*`, TTL 60 s; `/api/workspace/status` combines
  them). A load-state from a process that just died can show for up to 60 s.
- Cost: each web worker has its own ~40 MB floor and imports a tool on its own first use (idle container
  32 → ~170 MiB with 4 workers; `docs/roadmap/measure-B9.md`). Lower `TOOLBOX_WEB_WORKERS` in `.env` on a
  small machine.

History (why the pin existed, B2–B8 resolved each case):

The container runs uvicorn with **`--workers 1`**, pinned in `Dockerfile`.
This is because DataFrame Studio keeps its session state (the uploaded
DataFrame, the pipeline of steps) in a plain in-memory Python dict —
`engine.SESSIONS` in `df-studio/engine.py`. With more than one worker,
uvicorn runs separate OS processes that don't share memory, so a session
created by one request can be invisible to the next request if it lands on
a different worker — this happened for real once (see `df-studio/CLAUDE.md`)
and looked like random, unexplained "session not found" errors.
**Resolved for DataFrame Studio in roadmap B2** (sessions in Redis + S3
storage); the instances below still apply until their B-sessions land.

SQL Studio's live database connection (`sql-studio/db_engine.py`,
`STATE`) — **kept single-process by owner decision in roadmap B3**
(`singleton: true`; same for schema-map's pool) — is a second, independent instance of the same constraint — a
single module-level global holding the active Postgres connection pool,
not a per-cookie dict (see `sql-studio/CLAUDE.md` for why it deliberately
does NOT copy df-studio's per-cookie shape). The failure mode here is
worse than a lost DataFrame: with >1 worker, "Connect" landing on one
worker would be invisible to "Run" landing on another, and an orphaned
pool means real, live connections held open against a real external
database (visible in that database's own `pg_stat_activity`, consuming
its connection-limit budget) until something notices and kills it — not
just an inert lost value in memory.

Duck Lab's loaded files + DuckDB connection (**resolved in roadmap B3**:
table list/result in Redis, files in S3 storage, local DuckDB copies rebuilt
per worker — the rest of this paragraph is history) were a **third** instance of this — it deliberately copies
df-studio's per-cookie-dict shape (not SQL Studio's single global), because
each browser tab legitimately wants its own independent set of loaded
files, the same reasoning df-studio uses. See `duck-lab/CLAUDE.md`.

Data Syncer (`data-syncer/runner.py`) was a **fourth** instance — **resolved in
roadmap B4**: syncs are jobs on the Redis queue run by the `worker` container
(`core/jobs/`), live state in Redis. History: each sync
ran on a background thread, and the job registry plus the log ring buffer
lived in that one process's memory. Its durable progress (per-table resume
positions) is in Postgres since B6 and survives anything, but "is a run alive right
now" and the log tail do not — with >1 worker a Start on one process would be
invisible to the status poll on another. See `data-syncer/CLAUDE.md`.

Schema Copy (`schema-copy/runner.py`) was a **fifth** and Data Dumper
(`data-dumper/runner.py`) a **sixth** — both **resolved in roadmap B5**: runs are
jobs in the `worker` container through the shared `core/jobs/runner.py`
(`JobRunner`), and generated scripts / dump files live in S3 storage with the
local folders as per-process caches (`core/state/filecache.py`). Their
catalogues/last-run results are in Postgres since B6. See their `CLAUDE.md`s.

SSH & SFTP (`ssh-sftp/sessions.py`, `runner.py`) was a **seventh** — **resolved in
roadmap B8**: uploads/commands are worker jobs (`core/jobs/runner.py`), staged uploads
live in S3 storage, history in Postgres (B6). Its browsing connection cache stays per
process by design (recreated on demand). See `ssh-sftp/CLAUDE.md`.

**Roadmap:** B2–B8 moved all seven stateful tools' state out of process; **B9 lifted the `--workers 1`
pin** (ticked in `docs/roadmap/ROADMAP.md`). The rule at the top of this section replaces the old "decided
now" paragraph.

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

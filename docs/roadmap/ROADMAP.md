# Toolbox → Workspace roadmap

Goal: turn Toolbox into a **workspace** where tools are **plugins**, only the tools you use consume
resources, heavy shared tools (DataDiff) **scale automatically**, and the same design can later run on
**multiple nodes**. Built in small sessions. Each session is one sitting and leaves the app working.

## How to run a session (read this first, every time)
1. Start a new Claude Code session in `toolbox/` and say: **"Roadmap: do session `<ID>`."**
2. The session reads **this file**, the root `CLAUDE.md`, and only the files listed for that session.
3. Before finishing: run the smoke tests (from S0.3 on), rebuild/restart the container, tick the
   session's status below, and add 2–5 lines to **Handoff log** at the bottom.
4. Commit/push only when the owner says so (repo rule in `CLAUDE.md`).
5. **Parallel sessions**: only sessions marked ⚡ with the same "after" can run at the same time. Use a
   separate git branch or worktree per session and merge one at a time.
6. If a session grows too big, stop at a working point, log what is left, and split it.

Size: **S** = small session, **M** = medium session. No session should be large; split instead.

## Fixed decisions (do not re-debate in each session)
- **Architecture direction (approved by owner 2026-10-24, when asking for this full A–F plan):** the
  "one container, no gateway" rule in `CLAUDE.md` is replaced by this roadmap from phase C on.
  Phases 0–B keep one container. S0.1 rewrites `CLAUDE.md` to match.
- **Tool tiers**: 1 static/client-side · 2 light stateless Python · 3 data-heavy · 4 special/heavy
  image (LaTeX, SSH, Postgres client tools). Many tools share one **runtime image**; 1000 tools ≠
  1000 containers.
- **Plugins talk over HTTP, never by importing each other** (DataDiff becomes an API).
- **State**: sessions/queues → **Redis**; durable records → **Postgres**; files/uploads/dumps →
  **S3-compatible storage** — bundled **SeaweedFS** (decided in B1: S3 storage's community Docker images were
  discontinued in 2025), reached only through the S3 API (boto3) so Garage or AWS S3 is a config swap.
  No important state in process memory or on local disk.
- **Where the state services run (owner, 2026-10-24):** every service is reached only through env URLs
  (`TOOLBOX_DATABASE_URL`, `TOOLBOX_REDIS_URL`, `TOOLBOX_S3_ENDPOINT` + keys), never hard-coded.
  **Redis and S3 storage (SeaweedFS) are bundled** in `docker-compose.yml` with named volumes (Redis with AOF persistence so
  restarts keep queued jobs). **Postgres: bundled by default, but may point at an existing server** (e.g. the
  owner's `postgres_lab` via `host.docker.internal:5432`) — then Toolbox uses its **own `toolbox` database and
  user** there, never the lab databases, and that server must be backed up because Toolbox records and (after
  B7) Vault secrets live in it. Owner to confirm the Postgres choice at the start of B1.
- **Queue**: **RQ** on Redis (fork-per-job suits CPU-heavy pandas work). Confirm at B4.
- **Gateway**: Python (FastAPI + `httpx`, already a dependency). **Supervisor** for on-demand
  containers: Docker SDK through a **docker-socket-proxy** (limits what the socket allows).
- **Metrics**: `prometheus-client` + Prometheus + Grafana.
- **Multi-node later**: k3s + KEDA (own machines) or ECS Fargate (cloud). Not before phase F.
- **Not used**: ZooKeeper, Kafka, service mesh, one container per tool, Kubernetes before phase F.
- **Offline builds stay**: every new Python dependency goes into `requirements.txt` and
  `./download-wheels.sh` is re-run (wheelhouse is gitignored).
- **Security**: custom Python plugins are trusted code. Plugins never read the Vault directly after
  B7 (scoped API only). Static/external plugins are the safe default for custom apps.

## Status
| ID | Session | Size | After | Status |
|---|---|---|---|---|
| S0.1 | Decision record + `CLAUDE.md` update | S | – | ☑ |
| S0.2 | Baseline measurements | S | – ⚡ | ☑ |
| S0.3 | Smoke test suite | M | – ⚡ | ☑ |
| A1 | Plugin manifest spec + loader | M | S0.1 | ☑ |
| A2 | Manifests for all 20 tools | S | A1 | ☑ |
| A3 | Lazy loading + enable/disable | M | A2 ⚡ | ☑ |
| A4 | Workspace UI shell | M | A2 ⚡ | ☑ |
| A5 | Custom apps: static + external plugins | S | A3 | ☑ |
| B1 | Redis, Postgres, S3 storage + shared clients | M | A3 | ☑ |
| B2 | DataFrame Studio state out of memory | M | B1 ⚡ | ☑ |
| B3 | DuckLab + SQL Studio state out of memory | M | B1 ⚡ | ☑ |
| B4 | Job queue (RQ) + Data Syncer on it | M | B1 | ☑ |
| B5 | Schema Copy + Data Dumper on the queue, files to S3 storage | M | B4 | ☑ |
| B6 | SQLite → Postgres for durable stores | M | B1 ⚡ | ☑ |
| B7 | Vault as a service with scoped API | M | B6 | ☑ |
| B8 | SSH & SFTP state out of memory | M | B1 ⚡ | ☑ |
| B9 | Multiple workers + full regression | S | B2–B8 | ☑ |
| C1 | Split into runtime images | M | B9 | ☑ |
| C2 | Gateway service + routing from manifests | M | C1 | ☑ |
| C3 | On-demand supervisor (start/stop, idle, limits) | M | C2 | ☑ |
| C4 | Move tier-4 tools to on-demand containers | S | C3 | ☑ |
| D1 | DataDiff as a shared API + client | M | C2 ⚡ | ☑ |
| D2 | Generic job API + results in S3 storage | M | D1 | ☑ |
| D3 | Replica autoscaling on one node | M | C3, D2 | ☑ |
| E1 | Status page (containers, tools, scaling, jobs, storage, state) — no new services | M | D3 | ☑ |
| E2 | Per-tool request/error/slow counters (1 h / 24 h, Redis) | S | E1 | ☑ |
| E3 | Recent errors + log peek + in-page alerts | S | E1 | ☑ |
| E4 | (later, optional) `/metrics` export → Prometheus/Grafana, stored logs | M | E2 | ☐ |
| O1 | Ops: backup/restore scripts, tested restore, runbook, last backup on Status | S | E1 | ☑ |
| L1 | Lake catalog + Vault "Data" section (workspaces → tables), shared client, datasets imported | M | B7 | ☑ |
| L2 | Load files into tables as Parquet (upload, data folder, links, patterns; auto-detect; append/overwrite) | M | L1 | ☑ |
| L3 | SQL over the lake (Athena-like: instant + background queries, CREATE TABLE AS, history) | M | L2 | ☑ |
| L4 | Load from / Save to Vault Data in every tool; stage database tables via Vault connections | M | L3 | ☑ |
| L5 | Extras: profiles, suggested joins, charts, AWS S3 locations, notebook (later) | M | L4 | ☑ (notebook deferred) |
| F1 | Image versioning, registry, k8s manifests from plugin manifests | M | D3, E1 | ⏸ deferred |
| F2 | k3s single-node deploy (lab) | M | F1 | ⏸ deferred |
| F3 | KEDA scale-to-zero + queue scaling | M | F2 | ⏸ deferred |
| F4 | Second node, failover test, runbook | M | F3 | ⏸ deferred |
| G1 | Desktop: PWA install + app-mode shortcut (optional) | S | A4 | ☐ |
| G2 | Desktop: Electron wrapper (optional) | M | G1 | ☐ |

About 32 sessions. Phases 0–B are the most valuable. Re-measure after B9 before committing to C–F.

---

## Phase 0 – Foundation

### S0.1 Decision record + `CLAUDE.md` update (S)
- Write `docs/architecture/ADR-001-workspace-plugins.md`: context, tiers, state rules, phases, what
  is rejected (ZooKeeper etc.) and why.
- Rewrite the "Repo direction" and "Adding a new tool" sections of root `CLAUDE.md` to point at this
  roadmap; keep the `--workers 1` rule until B9 says otherwise.
- **Done when**: ADR exists, `CLAUDE.md` no longer contradicts this file.

### S0.2 Baseline measurements ⚡ (S)
- Script `tools/bench/baseline.py`: container RSS at idle, RSS after importing each tool, startup
  time, image size, p50/p95 latency for a few endpoints (DataDiff compare, LaTeX compile).
- Save numbers in `docs/roadmap/baseline.md`. Every later phase compares against it.
- **Done when**: baseline table committed-ready.

### S0.3 Smoke test suite ⚡ (M)
- `tests/smoke/`: pytest that hits every tool's page (200) and one key API per tool; a headless
  Chromium (Selenium is installed) check that each page loads without JS errors.
- One command: `make smoke` (or `scripts/smoke.sh`) against `localhost:8000`.
- **Done when**: suite passes on current `main`. Every later session runs it before finishing.

## Phase A – Plugins and workspace (still one container)

### A1 Plugin manifest spec + loader (M)
- Spec `docs/architecture/plugin-manifest.md` and `core_plugins/manifest.py` (pydantic): `name,
  title, icon, category (tool|learn), kind (static|python|external|service), entry, runtime
  (light|data|pgtools|latex|ssh), tier, state (none|session|durable|jobs), resources (cpu, memory),
  scaling (min, max, idle_timeout), depends_on, requires (system packages)`.
- Loader discovers `*/manifest.yaml`; falls back to `registry.yaml` so nothing breaks.
- Unit tests for validation. **No behavior change.**
- **Done when**: loader returns the same 20 entries as `registry.yaml`; tests pass.

### A2 Manifests for all 20 tools (S)
- Add `manifest.yaml` in every tool folder (tier, runtime, state filled in from the tables in
  `CLAUDE.md`/Dockerfile). Home page reads manifests; `registry.yaml` kept as generated/legacy.
- **Done when**: home page identical; smoke tests pass.

### A3 Lazy loading + enable/disable ⚡ (M)
- `workspace.yaml` (on a volume): enabled tools. Disabled tools are never imported.
- Replace eager `_try_mount` with an ASGI dispatcher that imports a tool **on first request** (keep
  per-tool fault isolation).
- Measure RAM vs S0.2 baseline and record it.
- **Done when**: idle container imports no tool code; first request to a tool works; disabled tool
  returns a clear "disabled" page.

### A4 Workspace UI shell ⚡ (M)
- New home: sidebar (search, categories), tools open in **tabs** (iframes), settings page to
  enable/disable tools (writes `workspace.yaml`, shows "restart needed" if required).
- Copy `theme-tokens.css` variables; no external CDN (offline).
- **Done when**: can open several tools in tabs and toggle a tool from settings.

### A5 Custom apps: static + external plugins (S)
- Mounted `plugins/` volume: a folder with `manifest.yaml` + `index.html` (kind `static`) or a URL
  (kind `external`) appears in the workspace **without rebuilding the image**.
- Document the trust model (static/external safe; python plugins = trusted code).
- **Done when**: a sample static app and a sample external link show up after restart.

## Phase B – State out of process (multi-node ready)

### B1 Redis, Postgres, S3 storage + shared clients (M)
- Add the three services to `docker-compose.yml` with volumes and health checks.
- `core/state/`: `sessions.py` (Redis session store with TTL), `db.py` (Postgres engine/pool),
  `objects.py` (S3 storage/S3 client). Config only from env vars. Add deps + wheelhouse.
- **Done when**: services healthy; a tiny test writes/reads each; no tool migrated yet.

### B2 DataFrame Studio state out of memory ⚡ (M)
- Today: `df-studio/engine.py` `SESSIONS` dict holds the DataFrame + step pipeline.
- New: pipeline/metadata in Redis; the DataFrame snapshot as Parquet in S3 storage (reload on demand,
  small LRU cache per worker).
- **Done when**: session survives a container restart and works with 2 workers; smoke passes.

### B3 DuckLab + SQL Studio state out of memory ⚡ (M)
- DuckLab `duck-lab/engine.py` `SESSIONS`: loaded-file list in Redis, files in S3 storage, DuckDB
  connection re-created per worker lazily.
- SQL Studio `sql-studio/db_engine.py` `STATE`: store connection **settings** (Vault ref) per
  session in Redis; each worker opens its own pool lazily; idle pools closed (reaper).
- **Done when**: both work with 2 workers; no orphaned DB connections after idle.

### B4 Job queue (RQ) + Data Syncer on it (M)
- Add RQ worker service. Generic job helpers in `core/jobs/` (enqueue, status, log tail in Redis,
  cancel).
- Move `data-syncer/runner.py` background thread → RQ job; keep resume positions durable.
- **Done when**: a sync runs in the worker container; status/log visible from any web worker.

### B5 Schema Copy + Data Dumper on the queue, files to S3 storage (M)
- Same pattern for `schema-copy/runner.py` and `data-dumper/runner.py`; dump files and generated
  `.sql` scripts stored in S3 storage (download via presigned URL or streamed through the API).
- **Done when**: both run as jobs; files no longer depend on `data_dumper_data`/`schema_copy_data`.

### B6 SQLite → Postgres for durable stores ⚡ (M)
- Stores: `schema-map/project_store.py`, `data-syncer/state_store.py`,
  `schema-copy/state_store.py`, `data-dumper/state_store.py`, `ssh-sftp/state_store.py`.
- One schema per tool; migration script that copies existing SQLite data once.
- **Done when**: all five use Postgres; old volumes only needed for the one-time migration.

### B7 Vault as a service with scoped API (M)
- `core/vault.py` storage → Postgres (still Fernet-encrypted); key from a secret (env/secret file),
  **not** a shared volume. Read API for other tools with per-tool scopes (`kind` filters).
- Update callers (sql-studio, schema-map, orchestrator, data-syncer, schema-copy, data-dumper,
  ssh-sftp, vault UI). Migration of existing secrets + key.
- **Done when**: no tool reads Vault files directly; existing secrets still decrypt.

### B8 SSH & SFTP state out of memory ⚡ (M)
- `ssh-sftp/sessions.py` connection cache stays per worker (recreated on demand); upload/command
  jobs via RQ; staged uploads in S3 storage (resume still works).
- **Done when**: works with 2 workers; resumable upload survives restart.

### B9 Multiple workers + full regression (S→M)
- Remove the `--workers 1` pin (gunicorn/uvicorn with N workers); update `CLAUDE.md` "Standing
  rule" section; full smoke + manual check of each stateful tool. Re-measure vs baseline.
- **Singleton plugins (`singleton: true` — sql-studio, schema-map, owner decision in B3)** must keep running
  in exactly ONE process: run them in one dedicated single-worker process and have the main app route their
  `/tools/<name>/` traffic there (in-process proxy, the first small piece of the phase-C gateway). Never give
  them a pool per worker or store their passwords.
- **Done when**: everything passes with 4 workers. **Checkpoint**: decide whether C–F are needed now.

## Phase C – Runtime pools and on-demand containers

### C1 Split into runtime images (M)
- Images: `base`, `light`, `data` (pandas/duckdb/pyarrow), `pgtools` (pg_dump stage), `latex`
  (TeX Live + fontawesome), `ssh`. Each image runs the same plugin loader with only its plugins.
- **Done when**: compose builds all images; each serves its plugins on its own port.

### C2 Gateway service + routing from manifests (M)
- Gateway = workspace UI + reverse proxy: `/tools/<name>` → runtime from the manifest. Streaming,
  large uploads, and WebSockets (check which tools need them) supported.
- **Done when**: all tools reachable through the gateway on :8000; smoke passes.

### C3 On-demand supervisor (M)
- In the gateway: start a stopped runtime on first request, wait for health, then proxy; stop after
  `idle_timeout`; apply CPU/memory limits from manifests. "Starting…" state shown in the UI.
- Docker access only through **docker-socket-proxy** (start/stop/inspect only).
- **Done when**: an idle tier-4 runtime is stopped and auto-starts on the next request.

### C4 Move tier-4 tools to on-demand containers (S)
- LaTeX first (biggest), then SSH & SFTP and Postgres tools. Measure idle RAM vs baseline.
- **Done when**: base image no longer contains TeX Live; idle RAM drop recorded.

## Phase D – Shared services and scaling

### D1 DataDiff as a shared API + client ⚡ (M)
- Versioned API (`/api/v1/...`) with OpenAPI; `core/clients/datadiff.py` for other plugins; the
  DataDiff UI and orchestrator use the client instead of importing `core.pipeline` directly.
- **Done when**: DataDiff runs as its own stateless service; two replicas behind the gateway work.

### D2 Generic job API + results in S3 storage (M)
- `POST /jobs`, `GET /jobs/{id}`, cancel; large compares run as RQ jobs; results stored in S3 storage.
- **Done when**: a large DataDiff compare runs async and any replica can return the result.

### D3 Replica autoscaling on one node (M)
- Supervisor scales replicas between manifest `min`/`max` by queue length and CPU; gateway
  load-balances (round robin, health-aware).
- **Done when**: a load test (many compares) adds replicas, then scales back down.

## Phase L – Lakehouse: Vault Data (Glue-Catalog-like catalog, Redshift-style loading, Athena-style SQL)

Owner request (2026-10-27): work with many files — join, analyse, stage data for migrations — in **workspaces**
that every tool can use, organised like the AWS Glue Data Catalog, loaded like Redshift (files → **Parquet**), queried
like Athena (SQL), with pandas through the existing tools (a Jupyter-like notebook later). Decisions:
- **The Vault is the front door**: the Vault page gets two sections — 🔑 **Secrets** (unchanged, encrypted) and
  📦 **Data** (workspaces → tables). Every tool's "Load from / Save to Vault" will offer Data tables (L4).
  Names are `workspace.table` everywhere. Today's Vault *datasets* are imported as tables (L1).
- **Data tables are plain Parquet** in Toolbox's S3 storage (owner went with recommendation A): queryable and fast;
  Secrets stay encrypted. Same single-user trust model as the rest of Toolbox.
- **Managed tables** (loaded into the lake, the default) and **external tables** (read in place, e.g. from the shared
  data folder `~/toolbox-data` → `/data`, read-only; `TOOLBOX_DATA_DIR`).
- **Catalog in Postgres** (schema `lake`, `SqlStore`), files under `lake/<table id>/<table id>.v<n>.<part>.parquet` (ids, so a
  rename never moves files). A shared service `core/lake` + permissions in the manifest's `vault:` section
  (`data: none|read|write`), like secrets. Backups cover both (Postgres + S3).

### L1 Catalog + Vault Data (M)
- `core/lake`: workspaces + tables (columns, rows, size, source, versions, history), create/rename/drop, write a
  table from Parquet files, preview; scoped access (`lake.scoped(tool)` from the manifest). Vault page: 📦 Data
  section (browse, describe, preview, rename, delete, new workspace). One-time import of existing Vault datasets.
- **Done when**: workspaces/tables are listed, described and previewed in the Vault; a dataset becomes a table.

### L2 Load (Redshift COPY style) (M)
- Load into a table from an upload, the data folder, a link or a file pattern; worker job converts to Parquet
  (streamed); auto-detect type/delimiter/header/types (CSV/TSV, JSON/JSONL, Parquet, XML, Excel, .gz); create /
  append / overwrite; schema-change warning; external tables. UI: new **Data Lake** tool (loading + later SQL).
- **Done when**: a multi-GB CSV and a folder of files become Parquet tables without filling memory.

### L3 SQL (Athena style) (M)
- Query editor over every workspace; small queries instant, big ones as background jobs with stored results; save a
  result as a table (CREATE TABLE AS); history + saved queries.
- **Done** (2026-10-27): Data Lake → 🔎 SQL tab (`data-lake/query.py`). Read-only checked on DuckDB's parse tree;
  only the named tables are mounted; results stored as Parquet (7 days) for paging / download / save as table.

### L4 Every tool (M)
- "Load from / Save to Vault" shows Data tables (DataFrame Studio, Duck Lab, DataDiff, SQL Studio export); stage a
  database table into a workspace via a Vault connection (migration staging).
- **Done** (2026-10-27): Duck Lab, DataFrame Studio, SQL Studio, DataDiff list tables (📦 per workspace) next to the
  old datasets and save to `workspace.table`; Data Lake → 🗄 Database stages tables or a query (worker job).

### L5 Extras (M)
- Column profiles, suggested joins, charts, AWS S3 locations, Jupyter-like notebook.
- **Done** (2026-10-28) except the notebook (owner: later). Also from owner feedback in this session: tools hide the
  workspace sidebar, Duck Lab / DataFrame Studio load only from Vault Data (Athena-style Tables bar with SQL types;
  DataFrame Studio joins other tables by name).

## Phase E – Observability (revised 2026-10-25: lightweight, no new containers)

Owner decision: Prometheus + Grafana (two always-on containers, ~150–250 MiB, own storage) are too heavy for one
user on one machine now. Phase E reuses what Toolbox already knows (Docker via docker-proxy, Redis, the job queue,
the workspace status) and shows it on ONE page in the workspace. Nothing runs or is stored unless the page is open
(except E2's few-KB counters). History/stored logs stay possible later (E4) without redoing E1–E3.

### E1 Status page (M)
- Workspace "Status" tab, polling every few seconds only while visible: every container (up / asleep / starting /
  stopped, health, CPU %, memory vs limit, uptime), tools (loaded / asleep / failed), scaling (replicas, last
  action), background jobs (waiting / running / failed per tool, recent failures), storage (S3 per tool, Postgres
  per schema), state services + Vault key source, and an "attention" list for anything wrong.
- Gateway does the Docker part (httpx only); the job/storage/state part is answered by `rt-data` (its libraries
  would cost every gateway worker memory). Docker access stays read-only list/inspect/stats.
- **Done when**: the page shows the whole stack; stopping a runtime / failing a job shows up within one refresh.

### E2 Per-tool counters (S)
- Gateway counts requests, errors (5xx) and slow requests per tool in Redis buckets (1-minute, kept 24 h);
  Status page shows last hour / 24 h with tiny sparklines. No per-request overhead worth measuring.
- **Done when**: traffic to a tool shows up in its counters; Redis keys expire by themselves.

### E3 Recent errors + log peek + in-page alerts (S)
- Last ~50 errors (time, tool, message) in a Redis list; "last 200 log lines" per container through docker-proxy
  (one more read-only rule, nothing stored); red banners for failed tool, unhealthy container, job backlog,
  memory near limit — computed when the page loads.
- **Done when**: a forced error appears in the list; a container's log tail opens from the page.

### E4 (later, optional) History
- Expose E2 counters as `/metrics` (Prometheus text format) and, if wanted then, add Prometheus/Grafana and stored
  logs as a profile that is off by default.

## Phase F – Multiple nodes (only when needed)

> **Deferred by owner decision (2026-10-25):** skipped for now, definitely planned for later — when a second
> machine, other users, or "keeps running if a machine dies" becomes a real need. The plan below stays as written;
> everything from phases A–E (per-runtime images, state outside processes, health checks, manifest-driven
> scaling/limits) was built so it can be picked up without redesign. Start with F1. Until then: Docker Compose on
> one machine is the supported setup.

### F1 Image versioning + manifests to k8s (M)
- Tag images by git SHA; push to a registry; generate Kubernetes manifests (or a Helm chart) from
  plugin manifests (resources, replicas, health checks). Secrets via k8s Secrets.

### F2 k3s single-node deploy (M)
- k3s on one machine: ingress, Postgres/Redis/S3 storage (in-cluster or external), gateway, runtimes.
  Same smoke suite passes against the cluster.

### F3 KEDA scale-to-zero + queue scaling (M)
- KEDA scalers: HTTP/queue length for runtimes and DataDiff; supervisor disabled in k8s mode
  (still used in Compose mode).

### F4 Second node, failover, runbook (M)
- Join a second node; kill a node during load; confirm recovery. Write `docs/runbook.md`
  (backup/restore Postgres/S3 storage, upgrades, scaling knobs).
- Cloud alternative: replace F2–F4 with an **ECS Fargate** track (same images and state services).

## Phase G – Desktop app (optional, any time after A4)
- **G1 (S)** ☑ (2026-10-26): web app manifest + icons so Chromium "Install app" works; `chromium --app=` shortcut.
- **G2 (M)** (not planned — owner chose G1 only): Electron wrapper that starts/stops the Docker stack and opens the workspace window.

---

## Handoff log
<!-- Newest first. 2–5 lines per session: what changed, what is left, gotchas. -->
- 2026-10-28 – **SSH & SFTP: live Terminal tab (owner request).** `ssh-sftp/terminal.py`: one login per terminal (Vault
  credential, pinned host key) + a shell with a PTY held in rt-ssh's process (compose now pins rt-ssh to ONE web
  worker); output = SSE from a byte offset (re-attach after reload/drop without gaps), keystrokes = small ordered
  POSTs; xterm.js 5.5 as a local bundle. Read-only servers refused; 8 sessions max; 30 min idle close. Verified on a
  real OpenSSH server in headless Chromium.
- 2026-10-28 – **New tool: Text Editor (owner request, outside the phases).** `text-editor/` — client-side (tier 1,
  runtime light) Notepad++-style editor on a local CodeMirror 6 bundle (+ json/xml/html, lint, merge, js-beautify;
  715 KB, served immutable with `?v=`): tabs (kept in localStorage up to 4 MB), regex find/replace, multi-cursor
  (Ctrl/Shift+Alt+↑/↓, Alt+drag, Ctrl+D), validation with every problem's line (own JSON scanner incl. JSON Lines,
  DOMParser XML, CSV field counts), Format/Minify that never parses numbers, line tools, regex keep/remove/extract,
  split compare (MergeView). Verified in headless Chromium: 200k-line / 9.7 MB file opens in 0.6 s, validates in
  0.27 s (both bad lines found), sorts in 0.57 s; 20-digit ids exact after format; 50k-vs-50k compare 0.2 s.
- 2026-10-28 – **L5 done (notebook deferred, owner).** `core/lake.py`: **profiles** (`profile()`: DuckDB SUMMARIZE —
  exact count/nulls/approx distinct/min/max/mean/std/quartiles — plus top-5 values from a 200k-row sample on big
  tables; cached per table version in `lake.profiles`; 30 M rows in 12.7 s, then 0.04 s); **suggested joins**
  (`suggest_joins()`: `x_id`↔`id` / same-name non-generic columns of a compatible type, then checked on the data —
  share of ≤ 2000 sampled distinct values found, < 5 % dropped; `id`=`id` and dates ignored); **S3 locations**
  (Vault kind `s3_location`; `use_s3()` = TEMPORARY DuckDB secret scoped to the bucket on every connection that
  reads it, `prepare(con, table)` before `read_expr`; httpfs installed at image build in data + worker;
  `s3_match()`; Vault `POST /test-s3`; Data Lake ☁ S3 source: copy in or read in place; errors in plain words);
  **sql_type()** (`varchar(100)`, `numeric(12,2)`… — the source DB's declared types are kept by staging in
  `source.column_types` via `staging.declared_types`, else the DuckDB type in SQL words; every catalog column has
  `sql_type`). Vault table page: Profile + Suggest joins; Data Lake SQL: 📊 Chart (bars/line/points, SVG, first
  1000 rows) and 🔗 joins per table in the tree (click inserts the JOIN). **L4 gap closed:** staging verified on real
  SQL Server 2022 (120k rows, nvarchar/bit/uniqueidentifier/datetime2, 7.7 s) and Oracle 23 free (50k rows, CLOB,
  `NUMBER(12,2)` now exact via an output type handler on that connection). **Owner feedback in-session:** (1) inside a
  tool the workspace sidebar slides away (☰ / Ctrl+K / Esc; `body.in-tool`); (2) Duck Lab and DataFrame Studio no
  longer upload files (backend `/upload`, `/load` kept, unused) — an Athena-style **Tables** bar (workspaces → tables
  → columns + SQL types, Load); DataFrame Studio "+ Join" adds tables by name (`Session.frames`, `steps.FRAMES`
  context, variables in the Query box; after owner feedback: one Load button for every table — first = `df`, others
  = variables, loaded rows green, no join UI; grid header with SQL types + toggleable column stats from
  `GET /column-stats`). Fixed: Data Lake page didn't follow `#sql` changes.
  Verified live (SeaweedFS as the S3 endpoint, throwaway mssql/oracle containers), 40 container tests, 165 host,
  smoke 107. Test data removed (`l3test` kept). **Next:** phase F when the owner wants it, or the notebook.
- 2026-10-27 – **L4 done.** Shared: `lake.catalog()`, `lake.export_table(ws, t, dest, csv|parquet, limit)`,
  `lake.import_file(ws, t, path)` (+ scoped versions); Vault `GET /data/catalog` (every tool's table picker) and
  `GET /data/tables/{ws}/{t}/csv` (DataDiff, ≤ 2000 rows, bigger refused like datasets). Tools (manifests `data:
  write`): **Duck Lab** `/load/lake` (table → lazy view) + `/export/lake` (full result); **DataFrame Studio**
  `/load/lake` (> 1 M rows → 413, page offers "first 1 M") + `/export/lake` (transformed df → Parquet); **SQL
  Studio** `/export/lake` (full uncapped result) + `/import/lake` (table → DB table, confirm like import/vault);
  **DataDiff** dropdowns. Save = prompt `workspace.table`, 409 → confirm → overwrite. Old datasets stay listed
  (🔒). **Staging** (`data-lake/staging.py`, Data Lake → 🗄 Database, manifest `read: [postgres_connection]`):
  Vault connection (postgres/mssql/oracle, SSH tunnel) → tables (or one SELECT) streamed in 50k-row batches
  (Postgres read-only session) → pyarrow batch Parquet (json/arrays → JSON text, untypeable → text) → DuckDB merge
  `union_by_name` → `write_table`; two schemas with the same table name → `schema_table`. **Bugs found on the way:**
  (1) **the gateway's httpx proxy client kept a cookie jar** and gave the last visitor's tool cookie to every new
  visitor without one — Duck Lab / DataFrame Studio sessions were shared between browsers since C2
  (`proxy._no_cookie_jar`, unit + smoke test); (2) Duck Lab 500'd on any DECIMAL/UUID/INTERVAL value
  (`_row_to_jsonable`); (3) Data Lake query pages sent non-whole decimals as text (now numbers when ≤ 15 digits).
  Verified live against a throwaway Postgres (300k orders + jsonb/uuid/numeric/timestamptz, NULL-only first
  batches): 3 tables / 305k rows staged in 3.2 s, create-again 409, overwrite → v2, query mode, DELETE refused,
  source untouched; each tool's load + save via API and in headless Chromium; 34 container tests, 165 host tests,
  smoke 106. SQL Server/Oracle staging written on the shared dialects but not run against real engines. Test data
  removed (`l3test` kept). **Next:** L5 extras.
- 2026-10-27 – **L3 done.** Data Lake gained a **🔎 SQL** tab (`#sql`): `data-lake/query.py` + endpoints `/catalog`,
  `/query` (instant, 30 s, rt-data, DuckDB 384MB / 2 threads) or `background: true` (worker job, 1GB, Stop works),
  `/queries/{id}` (+ `/rows` paging ≤ 1000, `/download` csv|parquet, `/save` → table, `/stop`), `/history`, `/saved`.
  Each query: fresh DuckDB, only the tables it names mounted as views `workspace.table` (unqualified name OK if
  unique). Read-only by DuckDB's own parse tree (`json_serialize_sql`): one SELECT/EXPLAIN; table functions other
  than range/generate_series/unnest and `FROM 'file'` refused (no reading `/etc` or `/proc` through SQL);
  `CREATE [OR REPLACE] TABLE ws.t AS SELECT` → `lake.write_table`. Results = Parquet in S3 (`data-lake-results/`,
  7 days; HUGEINT → DECIMAL(38,0) so sums stay exact); history (last 500) + saved queries in Postgres schema
  `data_lake`. Editor: catalog tree (click inserts, double-click previews), autocomplete (workspaces, `ws.` → tables,
  columns of the tables in the query, keywords). **Fixed on the way:** concurrent loads into a NEW workspace from two
  workers failed (`_ensure_workspace`); preview after an append that added columns lost them (NULL-filled now);
  DuckDB 1.2's Python API has no `query_progress` — the L2 percent never worked, removed (pages show elapsed time).
  Verified: 30 M-row table made by background CTAS (28 s), group-by over it 3 s, count(distinct) 9 s, rt-data anon
  peak ~570 MiB; 30 s timeout and Stop; page in headless Chromium; 30 container tests + smoke 103. Test workspace
  `l3test` left for the owner to try (delete in Vault → Data). **Next:** L4 every tool.
- 2026-10-27 – **L2 done.** New tool **Data Lake** (`data-lake/`: `server.py`, `loader.py`, `sources.py`, page; runtime
  data, `vault: {data: write}`, order 155 next to the Vault). Sources: upload (multi-file, staged in S3
  `data-lake/<upload id>/`), shared data folder `~/toolbox-data` → `/data:ro` in rt-data + worker (browse, patterns
  incl. `**`, confined: `..`/absolute/outside links refused, hidden skipped), links (streamed download). Load =
  worker job: detect (extension, else sniff; `.gz`), XML → JSON lines, Excel → Parquet (openpyxl added to data/worker
  + wheelhouse), DuckDB `COPY … TO dir (FORMAT PARQUET, FILE_SIZE_BYTES 256MB)` with `memory_limit` 1GB + spill dir +
  `query_progress` → `lake.write_table` (create/append/overwrite, column-change warning); external tables
  (`lake.register_external`, read in place). `core/file_source.py`: `detect_any`, `build_multi_read_expr`
  (union_by_name, filename). `lake.preview` reads only the first part (20 M-row table: 0.4 s). Plugin-order test now
  checks relative order (new tools may sit anywhere). Verified: 1.5 GB/20 M-row CSV → 341 MB Parquet in 16 s,
  worker peak 530 MiB; 500 files → one table + `_source_file`; `.csv.gz` with `;`; link; external; 409 on create
  again; page in headless Chromium; 15 container tests + host tests + smoke. Test data removed. **Next:** L3 SQL.
- 2026-10-27 – **L1 done (phase L planned with the owner first).** `core/lake.py`: catalog (SqlStore schema `lake`:
  workspaces, tables with columns/rows/size/parts/version/source, history, `_lake_meta`), managed tables = Parquet in
  S3 (`FileCache("lake")`, keys `lake/<table id>/<id>.v<n>.<part>.parquet`); `write_table` create / overwrite (new
  version, old files deleted after the catalog switch) / append (type-clash check, column union); rename/move (catalog
  only), drop, delete workspace (protected unless confirmed), preview (DuckDB, ≤ 500 rows), `local_files`, one-time
  `import_vault_datasets` (+ manual "again", skips imported ids), `ScopedLake` + manifest `vault.data`. Vault page:
  🔑 Secrets | 📦 Data tabs (workspaces, tables, table detail with columns/preview/history, rename/move, delete,
  import). Verified live (Postgres + S3) + screenshot; 7 lake tests in the container (DuckDB), smoke for the API.
  Owner decisions recorded above (Vault = front door, plain Parquet, data folder `~/toolbox-data` for L2).
  **Next:** L2 — loading files (upload / data folder / link / pattern → Parquet in the worker; new Data Lake tool).
- 2026-10-26 – **G1 done** (owner: G1 only, no start/stop shortcut, no Electron). Gateway serves
  `/manifest.webmanifest` (id/start_url/scope "/", standalone, theme #4f5ef0, icons 192/512 "any" + 512 "maskable",
  shortcuts Status/Settings), `/icons/<file>` (whitelist of 4 files, cached 1 day) and `/favicon.ico` (fixes the
  console 404 every browser test had to ignore); `workspace.html` links manifest, theme-color, icon. Icons drawn by
  `tools/icons/make_icons.py` (Pillow, host-side; white toolbox on the accent blue). Verified in Chromium via CDP:
  `Page.getInstallabilityErrors` → none, manifest parsed without errors, console clean. Unit tests (manifest
  criteria, icon sizes, path whitelist) + smoke. Runbook §1: how to install / uninstall.
- 2026-10-25 – **O1 (Ops session) done.** `scripts/backup.sh` (pg_dump via a one-off `docker compose run --no-deps
  worker`, S3 → tar via `python -m core.state.backup objects-export`, .env, workspace.yaml, manifest.json → one
  `backups/toolbox-<stamp>.tar.gz`, mode 600, keep 7, records Redis `toolbox:backup:last`); `scripts/restore.sh`
  (asks "restore" unless `--yes`; .env first (old one kept if different), state services up, tool containers
  stopped, `pg_restore --clean --if-exists --single-transaction`, bucket replaced, workspace.yaml via a one-off of
  the gateway, `up -d`). Status page: Backups card + attention after 7 days / none. `docs/runbook.md` for the owner.
  Hardening found on the way: Docker filters now include THIS compose project and exclude one-off containers
  (`core_plugins/dockerapi.py`) — otherwise a second stack's / a `compose run`'s containers would be started,
  stopped or routed to. `TOOLBOX_HOST_PORT`. Bug caught by the restore test: tarfile stream members have no
  `seekable()` → boto3 crashed → `_Unseekable` wrapper. Verified: real stack backup (32 s, 80 MB, 63 objects) →
  fresh second project on :8001 restored in 14 s → vault/schema-map/files/all 19 tables' row counts/workspace.yaml
  identical, a marker secret decrypted with the restored key, one file's sha256 identical; test project + volumes
  removed, marker secret deleted, a clean backup left in `backups/`. 157 unit tests.
- 2026-10-25 – **Phase F deferred** (owner: skip now, do in future). F1–F4 marked "⏸ deferred" in the status
  table; plan unchanged. Suggested meanwhile (not started, owner to confirm): a small Ops session — backup/restore
  scripts (Postgres dump + S3 files + .env + workspace.yaml), tested restore, `docs/runbook.md`, "last backup" on
  the Status page.
- 2026-10-25 – **E2 + E3 done — phase E complete (E4 stays optional).** `core_plugins/metrics.py`: `Metered` wraps
  each tool mount in the web role (outside the Slot, so state checks still see LazyApp/ProxyApp) — status + time to
  first byte per request, summed in-process, flushed every 5 s in one Redis pipeline (`toolbox:m:<tool>:m:<min>` 2 h,
  `:h:<hour>` 26 h, `toolbox:m:tools`); `/api/workspace/metrics` (hour + day totals, 60-min series; flushes this
  process first). Status page "Traffic per tool" with SVG sparklines (errors in red). E3: 5xx answers (incl. the
  gateway's own 503 page) go to `toolbox:errors` (last 50, 7 days) with a readable message (JSON error/detail, or the
  text of an HTML page minus title/style) → "Recent errors"; attention adds "N server errors in the last hour";
  `/api/workspace/logs/<name>` (project containers only — others 404; Docker log frames demultiplexed; proxy rule
  GET /logs; remember `--force-recreate docker-proxy`); log window per container; `/api/workspace/alerts` (container
  list without stats + tools + state health + errors) → badge on the Status nav item, polled every 60 s while the
  page is visible. Verified: counts per tool after browsing; rt-light stopped → 503 recorded with message → badge 1;
  log window showed 82 lines of rt-data; screenshots checked; unit tests (fake Redis) + smoke for every endpoint.
  Cost: 83 small Redis keys, error list 504 bytes; gateway ~250 MiB (was ~210) across 4 workers. 154 unit + 94 smoke.
- 2026-10-25 – **E1 done (phase E revised first).** Owner: no Prometheus/Grafana now — phase E rewritten as a
  lightweight E1–E3 + optional E4. Status tab in the workspace (`#/status`): attention list, services (Postgres,
  Redis, S3, job queue, Vault key source), every container of the compose project (state incl. "asleep (on demand)"
  / "standby (scaled down)", health, CPU %, memory vs limit with bar, up since, restarts), scaling + on-demand
  cards, tools, background jobs per tool (waiting/running/finished 1 h/crashed 7 days + recent crashes), storage (S3
  per prefix, Postgres per schema + total). `core_plugins/overview.py`; `/api/workspace/overview` (gateway: Docker
  list + inspect + stats concurrently, cached 4 s, ~2.5 s per call because stats samples CPU twice) +
  `/api/state/overview` (rt-data: health + rq registries + storage, cached 5/60 s). Polls every 5 s only while the
  tab is visible. Verified: 18 containers listed; stopping rt-light → "is stopped" in the attention list on the next
  call; screenshot checked; unit tests for the attention rules; smoke (API + browser). It already surfaced 218 MB
  of Duck Lab files from the C2 upload test (they expire with the session). **Found:** the D1–D3 commit 471e5b3
  contained a stray `yes` line in core_plugins/autoscale.py (typed into the open file) — fixed in the working
  tree, goes into the next commit. 150 unit + 93 smoke.
- 2026-10-25 – **D3 done — phase D complete.** Scaling without "create" rights: compose makes a POOL of `max`
  containers and the supervisor leader starts/stops pool members (`core_plugins/autoscale.py`, `ScaledService`,
  tick 5 s, cooldown 20 s): rt-datadiff by average CPU from Docker stats (> 60 % up, < 15 % for 45 s down; manifest
  `scaling: {min: 2, max: 4}`, pool 4), worker by RQ queue (`TOOLBOX_WORKER_SCALING=1:3`, pool 3; stops only workers
  RQ reports idle, matched by container hostname, 120 s warm shutdown). Leader publishes state to Redis
  (`toolbox:scale:*`) so any gateway process shows it. `core_plugins/balancer.py`: per-process replica list from
  Docker (running + "(healthy)"), round robin, refused replica skipped 10 s, fallback = service DNS name; ProxyApp
  retries the next replica on ConnectError, and on a dropped reused connection when there's no body. Proxy keep-alive
  now 2 s (< uvicorn's 5 s) — the keep-alive race gave 1–3 × 503 per load run before (found by logging the error
  type). docker-proxy: + GET stats, + start/stop `*-worker-<n>`. Load test (12 clients × 20k-record compares):
  2 → 3 → 4 replicas within ~40 s, back to 2 about 3 min after the load (45 s low per step); 282 compares, 0 errors
  after the keep-alive fix; requests spread 88/84/61/49 (3 and 4 joined later). 6 background jobs: workers 1 → 2,
  back to 1. Gotchas (in CLAUDE.md): inline config change doesn't recreate docker-proxy; `up -d toolbox` restarts
  pool members (use `--no-deps`); new gateway waits ≤ 45 s for the old leader lock. 146 unit + 91 smoke.
  **Checkpoint (owner):** E (status page/metrics) and F (multi-node) remain; both optional.
- 2026-10-25 – **D2 done.** `api/jobs.py`: compares as jobs on the shared queue (`JobRunner("datadiff")`, body
  `run_job` runs in the `worker`, which has the engine), input + gzipped result in S3 via `FileCache("datadiff")`
  (input deleted at the end, results swept after 7 days on submit — `FileCache.sweep(None, age)` now means "age
  only"), status from the job channel (phase loading/parsing/comparing/saving/done in progress → Redis meta).
  API `POST /api/v1/jobs` (202, `{"type": "compare"|"compare_structured", …}`, cheap checks first), `GET
  /jobs/{id}` (queued/running/done/failed/cancelled + summary/error), `GET /jobs/{id}/result` (FileResponse of the
  .gz with `Content-Encoding: gzip`; 409 not done, 410 gone), `DELETE` (cancel queued → recorded as cancelled;
  running → result discarded; finished → result deleted). datadiff image + rq/boto3. Client `submit_text`,
  `submit_data`, `job`, `result`, `wait`, `cancel` (local mode via api.jobs); CLI `--background`; page switches to
  a job above 2 MB of input (`#bg-status` shows the phase). Verified live: a 15 MB / 100k-records-per-side compare
  answered 202 in 1 s, ran 17 s in the worker, 250/250 mismatches; status + full result (400k records) returned
  by EACH replica directly; queued and running jobs cancelled; browser smoke test of the > 2 MB path (it leaves a
  small result per run — expires in 7 days). 138 unit + 91 smoke. Note: the CLI's `--background` waits on the
  queue — fine from `docker compose exec`, but a JOB that waited on another job with one worker would deadlock.
- 2026-10-25 – **D1 done.** DataDiff Pro = shared stateless service: new runtime `datadiff` (manifest Runtime literal,
  Dockerfile target, `requirements/datadiff.txt` = light + xmltodict → 188 MB image), compose `rt-datadiff` with
  `deploy.replicas: 2`, gateway URL. `api/app.py`: `APIRouter` `/api/v1` — `compare` (text), `compare/structured`
  (parsed values), `health` (replica = hostname; pid is 1 in every container), shared `CompareOptions` model,
  results passed through `to_json_safe`; `/compare` kept as a hidden alias; OpenAPI under the mount works through
  the gateway (`/tools/datadiff-pro/docs`). `core/clients/datadiff.py`: `DataDiffClient` (`compare_text`,
  `compare_data`, `health`; HTTP with `TOOLBOX_DATADIFF_URL`, in-process fallback), `DataDiffError`, value codec
  tagging Decimal/datetime/date/time/timedelta/UUID/bytes so HTTP compares see the same Python values. UI →
  `api/v1/compare`; orchestrator → client (worker env `TOOLBOX_DATADIFF_URL`). Unit test: only DataDiff imports
  `core.pipeline`. Verified: 40 health calls through the gateway hit both replicas (30/10 — Docker DNS spreads
  connections); 60 compares while one replica was stopped → 60 × 200, and again while one was `docker kill`ed →
  60 × 200; orchestrator CLI in the worker → `POST …/compare/structured` on a replica, mismatch found; smoke 90 × 2
  (new v1 check). 134 unit. **Next:** D2 (async compares as jobs, results in S3) — the client is where it plugs in.
- 2026-10-25 – **C4 done — phase C complete.** The tier-4 tools (LaTeX, SSH & SFTP, Schema Copy, Data Dumper) were
  already on-demand since C3; what was left: the `worker` ran the 1.2 GB `full` image with TeX Live it never uses →
  new Dockerfile target `worker` (all packages + pg_dump, no TeX, 647 MB); `full` is no longer run by compose (kept
  for a single-container `docker run`). Test: among compose-built targets only `rt-latex` inherits the `tex` stage.
  Verified on the new worker: dump, restore (200k rows) and an upsert sync all completed; no pdflatex inside.
  Measured (`measure-C4.md`): stack idle 643 MiB awake → 548 MiB with the on-demand runtimes asleep; after use
  those three held 168 MiB, freed on sleep. Honest note in the file: the whole stack is bigger than the original
  single container (state services ~150 MiB + a Python floor per container) — what dropped is the idle cost of
  unused heavy tools. Unused images `toolbox-full` / `toolbox-toolbox` (1.2 GB each) can be removed.
  **Checkpoint (owner):** phase D (DataDiff as shared API, autoscaling) / E (metrics, status page) / F (multi-node)
  are optional for one user on one machine.
- 2026-10-25 – **C3 done.** `core_plugins/supervisor.py` in the gateway: on-demand = runtimes whose python plugins
  are all tier 4 + `scaling.min: 0` (latex, pgtools, ssh; light/data always on); idle = max `idle_timeout_s`
  (`TOOLBOX_IDLE_TIMEOUT_S` overrides, empty = manifests). `ProxyApp` calls `ensure_running()` (cached Docker state
  2 s, start + wait for `/healthz` ≤ 60 s, asyncio lock per process) and touches Redis activity (also while
  streaming); one leader per gateway sweeps every 15 s. Docker via new `docker-proxy` service
  (tecnativa/docker-socket-proxy:0.3.0) with OUR haproxy rules — its env switches can't allow start/stop without
  allowing every container POST (create/exec/update); ours: GET _ping/version/containers(json), POST start/stop of
  `*-rt-<runtime>-<n>` only. Limits: tier-4 manifests got `resources`, compose `mem_limit`/`cpus` = sum (test).
  Status shows `asleep`/`starting` (UI dots + pills), `GET /api/workspace/runtimes`. Startup hook avoided
  (`on_event` deprecated / gone in Starlette 1.x): the sweep starts on a worker's first request. Verified with
  idle 45 s: all three stopped after ~50 s; cold latex page 200 in 1.2 s; 6 concurrent cold pgtools requests all 200
  (4 start calls = one per gateway worker, Docker answers 304 — harmless); denied: stop postgres/worker, create,
  kill, exec, update, delete, images, volumes, info (403); limits visible in `docker inspect`; smoke 89 × 3 (one run
  with runtimes asleep). 126 unit. Asleep saves ~40 MiB idle per runtime (more after use: latex/pandas pages).
  **Next:** C4 (drop TeX Live from images that don't need it — `full` still carries it for the worker) or stop here.
- 2026-10-25 – **C2 done.** `toolbox` = gateway: new Dockerfile target `gateway` (241 MB: light + state clients, no
  tool libs), web role with `TOOLBOX_RUNTIME_URLS` → every python plugin is a `ProxyApp` to `rt-<runtime>` (singletons
  → `singletons`), static/external served locally, `_lazy` stays empty. rt-* run by default (no host ports, profile
  removed; rt-data 2 workers), `singletons` now on the data image, `worker` on `toolbox-full`; compose uses
  `x-state-env` / `x-tool-service` anchors (`depends_on` is REPLACED by a merge, not combined — services that need
  their own list restate it). Proxy now forwards the browser's Host. `/api/state/health` is answered by rt-data (its
  probes made each gateway worker +25 MB: 288 → 211 MiB after 12 calls). 503 page names the container
  (`docker compose logs rt-latex`). No tool needs WebSockets (checked). Orchestrator CLI → `docker compose exec
  worker`. Verified: smoke 89 × 5 through the gateway; 144 MB duck-lab upload + 150 MB CSV export streamed;
  status shows tools loaded in other containers; stopping rt-latex → only LaTeX shows the 503 page, back on start.
  **Idle memory went UP**: ~260 MiB (B9) → ~500 MiB for all tool containers (gateway 177 + six Python floors of
  ~38 MB + rt-data 104 + worker 21) — the price of separate containers; C3 (stop idle runtimes) wins it back.
  The old `toolbox-toolbox` image (1.2 GB) is unused now (can be removed). 122 unit. **Next:** C3.
- 2026-10-25 – **C1 done.** Dockerfile = stages `pgclient → pyslim → code → wheels → deps-*/runtime …→ tex → latex →
  full`; targets `light` 187 MB, `ssh` 249 MB, `pgtools` 267 MB, `data` 629 MB, `latex` 746 MB, `full` 1.2 GB (was
  1.35 GB: the wheelhouse no longer sits in a layer — packages install in `deps-*` stages with `pip --prefix=/install`,
  only /install is copied). `requirements/{light,state,data,pgtools,ssh,latex}.txt` (pins identical to
  requirements.txt, `tests/unit/test_runtimes.py`). `main.py` role `runtime` (+`TOOLBOX_RUNTIME`): only its own python
  plugins, singletons never; role filters now run BEFORE the on/off check (a turned-off tool of another role was
  getting a "turned off" mount). Vault moved to runtime `data` (needs DB drivers, DuckDB, paramiko). Compose: `toolbox`
  builds `target: full`; `rt-light/data/pgtools/ssh/latex` under profile `runtimes` (127.0.0.1:8101–8105, not started
  by default). Gotchas: no buildx here → classic builder: no `RUN --mount`, and it runs every stage before the target
  (stages ordered cheapest-first); the `tex` stage must begin exactly like the old image or the ~600 MB TeX Live
  layer re-downloads (it did once, and failed on a flaky mirror). ssh-sftp needed `sshtunnel` (core/ssh_client →
  core/postgres_conn). Verified: every runtime loads all its plugins (pages 200, state loaded) and 404s other tools;
  vault decrypt + duck-lab session (data), pg_dump/psql 18 + dump catalogue (pgtools), PDF compile (latex) against the
  shared state; main stack on the new `full` image: smoke 89 × 2. 121 unit. **Next:** C2 (gateway routes
  /tools/<name> to its runtime service; then `toolbox` can shrink to the gateway).
- 2026-10-25 – **B9 done — phase B complete.** Web runs `TOOLBOX_WEB_WORKERS` uvicorn workers (compose default 4;
  image default 1). New `singletons` service (same image, `TOOLBOX_ROLE=singletons`, one process, healthcheck
  `/healthz`) hosts sql-studio + schema-map; web workers forward to it with `core_plugins/proxy.py` (`ProxyApp`:
  httpx streaming both ways, raw path/query/cookies, hop-by-hop headers dropped, X-Forwarded-*, no redirect
  following, 503 page when down, one client per event loop). Found + fixed for multi-worker: on/off switches only
  reached the worker that got the POST → every worker re-reads `workspace.yaml` on mtime change (pure ASGI
  middleware, ≤1 s); "loaded" state was per worker (smoke `test_tool_is_loaded_after_its_first_request` flaked
  2/3 runs) → each process publishes loaded/failed tools to Redis `toolbox:procs:*` (TTL 60 s, refresh 20 s + on
  load) and status combines them. Starlette 0.37 (image) passes middleware `app=` by keyword, 1.x (host)
  positionally — name it `app`. Verified with 4 workers: smoke 89 × 19 runs (incl. 3 cold restarts) green after
  the fix; sql-studio Connect once + 40 queries over 4 workers → 1 backend; switches (incl. proxied sql-studio)
  apply on every worker; duck-lab session queries across workers; data-dumper status consistent while polling.
  Measure (`measure-B9.md` vs `measure-A3.md`): idle web container 32 → 169 MiB (4 workers × ~40 MB floor), +
  singletons ~70 MiB; 8 parallel 5k-record DataDiff compares 2.89 s (1 worker) → 1.78 s (4). 117 unit + 89 smoke.
  **Checkpoint (owner):** C–F (runtime pools, on-demand containers, autoscaling, multi-node) are not needed for
  one user on one machine today; next useful sessions are probably C1/E (status page) or features. Owner decides.
- 2026-10-25 – **B8 done.** SSH & SFTP: uploads + commands are worker jobs (`ssh-sftp/runner.py` → `JobRunner(quiet=True)`);
  staged uploads in S3 (`state_store.STAGE`, publish on receive, `fetch_stage` before send, deleted on success,
  `sweep_stage` for finished/7-day-old); heartbeat-aware `fail_orphans` replaces the blanket `recover_interrupted`;
  browse connection cache stays per process (by design). Shared improvements: `Channel.log_many` + `_BufferedLog`
  (batched Redis log writes, 0.3 s / 200 lines), `KEEP_TTL` 7 days on job log/meta/seq keys (one slot per
  upload/command/dump — Redis would only grow), thread-mode registry capped at 100 finished jobs, `FileCache.sweep`.
  `execute()` now takes an opts dict (`log_size`, `kind`, `quiet`). Verified live with a real OpenSSH server:
  trust flow via scoped `update_secret`, 3000-line command + exit code + `since` paging; 300 MB upload, worker
  killed at 83 MB → failed → local stage deleted → Retry resumed from 93.7 MB using the stored stage, SHA-256 ok;
  `--scale worker=2`: two uploads ran on both workers in parallel through a web restart, checksums identical.
  109 unit + 36 in-container + 89 smoke. **Next:** B9 (lift `--workers 1`; route singletons sql-studio/schema-map).
- 2026-10-25 – **B7 done.** `core/vault.py`: rows → Postgres (schema `vault`, `SqlStore`; old `vault.db` copied once),
  dataset blobs → S3 (`FileCache`, legacy blobs uploaded on start); key from `TOOLBOX_VAULT_KEY` (env) /
  `TOOLBOX_VAULT_KEY_FILE`, legacy volume file only as fallback (health warns); `_vault_meta.key_check` →
  `VaultKeyMismatch` on a wrong key. The existing key was moved into a new git-ignored `.env` (0600; compose passes
  it to web + worker). **Scopes**: manifest field `vault: {read, write, datasets}`; tools use
  `vault_store.scoped(name)` (`ScopedVault`); db_endpoint/orchestrator have explicit scopes; a unit test forbids
  unscoped use in tool folders. **HTTP scoped read API** `/tools/vault/api/v1/{scope,secrets,secrets/{id}}` with
  per-plugin HMAC tokens (`python -m core.vault token <name>`) for phase C runtimes. Backup format 2 (json + key +
  blobs); restore reads format 1 too and **re-encrypts** other-key backups. Verified live: worker decrypts a
  connection and dumps, scoped API 200/403/401, ssh-sftp lists only `ssh_server`, dataset round trip through S3,
  backup contents. A live wipe+restore of the owner's vault was blocked as destructive — covered by unit tests on an
  isolated vault. 105 unit (host) + 36 in-container + 89 smoke. `/api/state/health` has `vault`.
  **Next:** B8.
- 2026-10-25 – **B6 done.** `core/state/sqlstore.py` (`SqlStore`): sqlite3-shaped API over Toolbox's Postgres (one
  schema per tool, `SET LOCAL search_path` per transaction, `?`→`%s`, `Row` = dict + positional, NUMERIC→int,
  INTEGER→BIGINT/REAL→DOUBLE/BLOB→BYTEA in DDL, `add_columns`), SQLite fallback standalone. The five stores
  (schema-map, data-syncer, schema-copy, data-dumper, ssh-sftp) now use it with almost unchanged SQL. **Migration is
  automatic**: first `init()` copies the old SQLite file (columns by name, existing ids skipped, orphan rows skipped
  one by one) under an advisory lock and records it in `<schema>._meta`; never repeats; the SQLite file stays as a
  backup (owner's "temp" Schema Map project came across). **Bug found live:** psycopg auto-prepares after 5 runs per
  connection, and tools share SQL text in different schemas → "cached plan must not change result type" — fixed
  with `prepare=False` + regression test. Also: data-syncer status now heals before reading tables. Verified: 2M-row
  copy sync with worker kill → resume from Postgres position (count/sum/distinct match), dump → restore, schema-copy
  apply, schema-map versions, 240 alternating API calls with no errors. 92 unit (+8 Postgres tests in the container,
  see `tests/unit/test_sqlstore.py` header) + 89 smoke. Volumes still mounted: SQLite backups, file caches, ssh-sftp
  stage (B8), Vault (B7). **Next:** B7 (Vault) or B8 (SSH & SFTP).
- 2026-10-25 – **B5 done.** Shared `core/jobs/runner.py` (`JobRunner`: queue mode via `Channel`/`enqueue` with the
  job body run by `core.jobs.runner.execute` in the worker, thread fallback; progress dict mirrored to Redis ≤1/s) and
  `core/state/filecache.py` (`FileCache`: S3 = home, local folder = cache; publish/fetch/exists/remove_all; trim to a
  budget, never evicting unstored or recently used files; fetch uploads a never-stored local file). Schema Copy and
  Data Dumper runners are thin wrappers; scripts/dump files/TOC caches go to S3 (`schema-copy/<id>/…`,
  `data-dumper/<id>/…`); `state_store.fail_orphans` + `runner.recover_orphans/heal` replace the blanket
  `recover_interrupted`. Verified live on a 3M-row DB: dump survived a web restart; contents/download/restore all
  worked with the local copy deleted (restore count + sum match); 409 on double start; worker killed mid-dump →
  dump failed after 27 s, `.part` gone; Stop while queued → "Stopped by you before it started"; schema-copy apply in
  the worker + script served from storage. **Bug fixed from B4:** a killed worker crash-looped on restart ("active
  worker named … already") for ~7 min — `core/jobs/worker.py` now clears stale registrations of its own hostname and
  adds a random suffix. 88 unit + 89 smoke. Data Syncer still has its own B4 runner (could move to `JobRunner` later).
  **Next:** B6 (SQLite → Postgres; volumes for these two tools then only hold caches + SQLite until migrated).
- 2026-10-24 – **B4 done.** `core/jobs/` (RQ 2.1 on Redis: `Channel` = atomic claim (`SET NX`), heartbeat "alive"
  key (30 s TTL running / 24 h queued), log tail list trimmed to N, stop flag, meta; `StopFlag` with `is_set()`
  (1 s cache) + `wait()`; `enqueue(job_timeout=-1)`; `health()`), `core/jobs/worker.py`, compose `worker` service
  (same image, same data volumes + env). `data-syncer/runner.py`: queue runner (`run_job` in the worker) + old
  thread runner as standalone fallback; `recover_orphans()` replaces the blanket `recover_interrupted()` (would have
  broken live worker runs on a web restart), `heal()` on status reads. Verified live with a 2M-row upsert: survived
  a web restart mid-run, double start → 409, graceful Stop at 650k, worker `kill` → stopped after 26 s → resumed
  "after key 1250000" → count + sum match. Test DBs/Vault entries/project removed. `/api/state/health` has `jobs`.
  79 unit + 89 smoke. One unexplained smoke failure right after the first rebuild — not reproduced in 4 runs; watch it.
  **For B5:** reuse `core/jobs` the same way for schema-copy/data-dumper; dump files → S3 (`core.state.objects`).
- 2026-10-24 – **B3 done.** **DuckLab**: `duck-lab/session_store.py` (Redis meta + S3 files / memory fallback);
  `engine.py` rewritten around per-worker `_Local` copies (DuckDB conn + cache dir, LRU 8, rebuilt when the stored
  `version` changes, `RLock` per session), uploads + XML (now Parquet) + query results (Parquet) stored in S3;
  `server.py` runs every engine call via `asyncio.to_thread`; exports deleted after sending. Verified: 6 unit tests
  (run **inside the container** — host has no duckdb; they skip on the host), two separate processes sharing a
  session end to end, session rebuilt after `--force-recreate` with an empty local cache; 76 unit + 88 smoke pass.
  **SQL Studio / Schema Map: owner chose to keep them single-process** (pool of 3, password never stored) → new
  manifest field `singleton: true` on both; B9 text updated to route them to one dedicated process. No code change
  to either tool.
- 2026-10-24 – **B2 done.** `df-studio/session_store.py`: `StateBackend` (Redis metadata, sliding 12 h TTL; original
  DataFrame in S3 as Parquet with pickle fallback; sweep of expired sessions' files) / `MemoryBackend` (standalone +
  unit tests). `engine.py`: `SESSIONS` dict removed → `get_session`/`create_session`/`save_session`/`delete_session` +
  per-process LRU cache (3); every mutator saves. `server.py`: session loads via `asyncio.to_thread`, new load deletes
  the browser's previous session. Templates → Postgres `df_studio.templates` (the old JSON file was being wiped by
  every rebuild — none existed to migrate). `core/state/objects.py` gained `put_file`/`get_to` (multipart),
  `list_objects`, `delete_prefix`. Verified: two separate processes share one session end to end; session + template
  survive a container restart; 74 unit + 88 smoke pass. **For B3:** reuse `session_store.py`'s backend pattern
  (DuckLab: files in S3; SQL Studio: connection settings only, pools stay per process).
- 2026-10-24 – **B1 done.** Compose: `redis:7.4-alpine` (AOF, noeviction, 256 MB cap), `postgres:18-bookworm`
  (db/user `toolbox`), `chrislusf/seaweedfs:4.48` (S3 on :8333, creds via inline compose `configs:`) — all with
  named volumes + health checks, none published on host ports. **MinIO dropped** (`minio/minio` no longer
  pullable). `core/state/`: `config.py` (env only), `db.py` (psycopg pool, min 0, `ensure_schema`), `sessions.py`
  (`SessionStore` JSON+TTL), `objects.py` (boto3, path-style, `key()` validation), `selftest.py`
  (`docker compose exec toolbox python -m core.state.selftest`), `health()`; `GET /api/state/health`.
  Verified: round trips ok; markers survive `docker compose down` + `up`; 65 unit + 87 smoke pass. Idle memory:
  toolbox 33 / postgres 30 / redis 5 / seaweedfs 144 MiB. Gotchas: SeaweedFS needs ~20 s after start and binds the
  container IP (health check uses `hostname -i`); presigned URLs point at the internal endpoint → stream downloads
  through tool APIs. Postgres is still the bundled one — switch with `TOOLBOX_DATABASE_URL` in `.env`.
  **Next:** B2, B3, B6, B8 can run in parallel; B4 then B5.
- 2026-10-24 – **A5 done → Phase A complete.** `plugins/` (bind-mounted ro at `/app/plugins`, `TOOLBOX_PLUGINS_DIR`)
  for custom apps: loader accepts only `static`/`external` there (python refused). `StaticApp` serves folder files
  (no `..`/hidden/manifest, GET/HEAD) with CSP `sandbox` (no `allow-same-origin` → can't reach Toolbox APIs —
  verified live: sample reports "blocked"); `ExternalApp` = 307 redirect. All kinds get a `Slot` + switch (service
  later). Samples `hello-static`, `example-link` ship off. 53 unit + 86 smoke pass. Note: `Slot` mounts strip the
  prefix via `scope["root_path"]` (Starlette keeps the full path in `scope["path"]`).
  **Phase A result:** tools = plugins with manifests, lazy-loaded (idle 174 → 32 MiB), live on/off, VS-Code-like
  workspace UI, custom apps without rebuild. **Next: B1** (Redis/Postgres/S3 storage). Optional any time: G1 (desktop app).
- 2026-10-24 – **A4 done.** `/` is now the workspace: `core_plugins/ui/workspace.html` (sidebar with search/Ctrl+K,
  Tools/Learning groups, load-state dots; tools in tabs as kept-alive iframes, restored from localStorage, deep links
  `#/tool/<name>`; Home tab = old card grid; Settings tab = table + switches). Tools mounted via `Slot` →
  `POST /api/workspace/plugins/<name>` toggles **live** (no restart), saves `workspace.yaml`; status gained
  `restart_to_free_memory`. Old `_HOME_TEMPLATE` removed from `main.py`. 43 unit (incl. `test_workspace_api.py` on the
  real app) + 86 smoke (new browser test: sidebar → tab → settings → search) pass; screenshots checked; live toggle
  verified on the container. Gotcha: sidebar re-renders on each status refresh — browser tests click via JS.
  **For A5:** static/external plugins need a mount type in the `Slot` loop (today only `kind: python` gets a slot;
  the settings switch is disabled for other kinds) and cards/tabs for external URLs should open the URL.
- 2026-10-24 – **A3 done.** `core_plugins/lazy.py` (`LazyApp`: import on first request under an asyncio lock,
  failure → 503 + "Unavailable" card, no retry storm; `DisabledApp`: 404 "turned off" page) and
  `core_plugins/workspace.py` (`workspace.yaml` `enabled: {name: bool}`, atomic `save()` ready for A4; broken file
  → defaults). `main.py` mounts lazily, hides disabled tools, new `GET /api/workspace/status`. Compose volume
  `workspace_data`. **Measured (`docs/roadmap/measure-A3.md`): idle 174 → 32 MiB, RSS 186 → 49 MB, cold start
  2.6 → 0.77 s, home 15 → 1.3 ms**; first-use cost ≤ 0.5 s per tool (df-studio). 40 unit + 85 smoke pass; on/off
  verified live. Gotcha: import-time work (`recover_interrupted()` in 3 tools, ssh-sftp reaper) now runs on the
  tool's first request — documented in CLAUDE.md. **For A4:** settings page should call `Workspace.set_enabled`
  + `save()` and tell the user a restart is needed (mounts are built at startup).
- 2026-10-24 – **A2 done.** `manifest.yaml` in all 20 tool folders (DataDiff's is `api/manifest.yaml`) with
  real tier/runtime/state/depends_on/requires and `order` 10…200 (old registry order). New manifest field
  `order` (default 1000). `main.py` now: `discover()` once at startup → home cards + loop `_try_mount(name,
  module)` for `kind: python`; hand-written mount list and **`registry.yaml` deleted** (legacy fallback removed
  from the loader). Dockerfile copies `core_plugins/` + the 10 file-by-file manifests. Smoke tests and bench read
  manifests. Verified: home page byte-identical to before, 30 unit + 83 smoke pass, bench measures 20 tools.
  CLAUDE.md "How it works" + "Adding a new tool" (steps 5–6), README, KNOWLEDGE_MAP, orchestrator/CLAUDE.md
  updated. **For A3:** mounting is still eager (all 20 imported at startup); classification: 10 tools tier 1
  (client-side, still `kind: python` serving their page — A5 may turn them `static`), 9 stateful.
- 2026-10-24 – **A1 done.** Spec `docs/architecture/plugin-manifest.md`; package `core_plugins/`
  (`manifest.py` pydantic model with per-kind rules, `extra=forbid`; `loader.py` `discover(repo, extra_dirs,
  legacy=True)` → `Registry(plugins, errors, warnings)`, never raises for a bad plugin). Legacy fallback builds
  the 20 entries from `registry.yaml` + `main.py` `_try_mount` lines (every legacy entry is `runtime: light,
  tier: 2` — A2 must set real values). 29 unit tests: `python3 -m pytest tests/unit -q`. Verified in the
  container (pydantic 2.14): 20 plugins, 0 errors. App untouched (smoke 62/62).
  **For A2:** `core_plugins/` is NOT in the Docker image yet — add `COPY core_plugins/ ./core_plugins/` to the
  Dockerfile before `main.py` uses it; delete `_legacy_entries` once all 20 manifests exist.
- 2026-10-24 – **S0.3 done.** `scripts/smoke.sh` (all, ~21 s) / `scripts/smoke.sh --no-browser` (~1 s) runs
  `tests/smoke/`: home page + every tool page (200, HTML, no failed-mount card), 17 read-only API checks
  (no external systems; curl-builder is page-only because /execute calls out), headless-Chromium check for JS
  errors on every page. 83 passed on `9811175`. Tool list is parsed from `main.py` `_try_mount` lines —
  **A2 must switch `mounted_tools()` in `tests/smoke/conftest.py` (and `tools/bench/baseline.py`) to the
  manifests.** `test_every_tool_is_classified` fails until a new tool gets an API check or a PAGE_ONLY entry.
- 2026-10-24 – **S0.2 done.** `tools/bench/baseline.py` (host-side, stdlib only) → `docs/roadmap/baseline.{md,json}`.
  Baseline: image 1.31 GB, idle RSS 186 MB (1 process), cold start 2.6 s, all tools import +130 MB / 1.2 s,
  DataDiff 5k-record compare p50 271 ms, LaTeX compile p50 967 ms.
  **Findings for later phases:** RAM cost is concentrated in 9 data/DB tools (duck-lab 102 MB, df-studio 87 MB,
  sql-studio 44 MB, the rest ~23–30 MB, largely shared pandas/duckdb/psycopg); the 10 tier-1 tools cost ~0 MB;
  LaTeX costs ~0 MB RAM but most of the image size. So A3 lazy loading saves up to ~130 MB idle, C4 (LaTeX
  on demand) mainly saves disk/image size, and D (DataDiff scaling) is about CPU, not memory. Re-run with
  `--restart` after A3, B9, C4, D3 and compare the JSON.
- 2026-10-24 – **S0.1 done.** Added `docs/architecture/ADR-001-workspace-plugins.md`. `CLAUDE.md`:
  top "Repo direction" now points here (old one-container rule kept as "current state until phase C"),
  roadmap notes added to "Adding a new tool" (manifests from A2) and the `--workers` standing rule
  (lifted only at B9), `docs/` added to the structure map. Docs only, no rebuild needed.
  Next: S0.2 and S0.3 (can run in parallel).
- 2026-10-24 – Roadmap written (no code changes yet). Next: S0.1, then S0.2 and S0.3 in parallel.

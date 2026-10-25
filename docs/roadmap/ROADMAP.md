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
| B7 | Vault as a service with scoped API | M | B6 | ☐ |
| B8 | SSH & SFTP state out of memory | M | B1 ⚡ | ☐ |
| B9 | Multiple workers + full regression | S | B2–B8 | ☐ |
| C1 | Split into runtime images | M | B9 | ☐ |
| C2 | Gateway service + routing from manifests | M | C1 | ☐ |
| C3 | On-demand supervisor (start/stop, idle, limits) | M | C2 | ☐ |
| C4 | Move tier-4 tools to on-demand containers | S | C3 | ☐ |
| D1 | DataDiff as a shared API + client | M | C2 ⚡ | ☐ |
| D2 | Generic job API + results in S3 storage | M | D1 | ☐ |
| D3 | Replica autoscaling on one node | M | C3, D2 | ☐ |
| E1 | Metrics + Grafana dashboards + JSON logs | M | C2 ⚡ | ☐ |
| E2 | Health/status page + alerts | S | E1 | ☐ |
| F1 | Image versioning, registry, k8s manifests from plugin manifests | M | D3, E1 | ☐ |
| F2 | k3s single-node deploy (lab) | M | F1 | ☐ |
| F3 | KEDA scale-to-zero + queue scaling | M | F2 | ☐ |
| F4 | Second node, failover test, runbook | M | F3 | ☐ |
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

## Phase E – Observability

### E1 Metrics + dashboards + JSON logs ⚡ (M)
- `/metrics` on gateway and runtimes (requests, latency, errors, queue length, container state);
  Prometheus + Grafana in compose with a saved dashboard; JSON logs with request IDs.
- **Done when**: dashboard shows per-tool traffic and queue depth.

### E2 Health/status page + alerts (S)
- Workspace "Status" page: each tool up/stopped/starting, resource use; basic alert rules (tool
  down, queue backlog, memory high).
- **Done when**: stopping a runtime shows on the page and fires an alert.

## Phase F – Multiple nodes (only when needed)

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
- **G1 (S)**: web app manifest + icons so Chromium "Install app" works; `chromium --app=` shortcut.
- **G2 (M)**: Electron wrapper that starts/stops the Docker stack and opens the workspace window.

---

## Handoff log
<!-- Newest first. 2–5 lines per session: what changed, what is left, gotchas. -->
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

# Gateway, runtimes, scaling, Status page, workspace UI

> Moved **verbatim** from the root `CLAUDE.md` by roadmap session O3 (2026-11-10). The root keeps only the rules and an index;
> nothing was reworded. Paths in the text are repo-root relative.

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

- **Installable app (roadmap G1):** the gateway serves `/manifest.webmanifest`
  (standalone display, Status/Settings shortcuts), `/icons/<file>` (four
  known PNGs from `core_plugins/ui/icons/`, drawn by
  `tools/icons/make_icons.py`) and `/favicon.ico`; `workspace.html` links them.
  Chromium offers "Install Toolbox" (verified: no installability errors) —
  an app window onto the running stack, nothing else (no Electron, G2
  deferred). How to install: `docs/runbook.md` §1.

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

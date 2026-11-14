# Knowledge Map

Purpose: a lookup table from "I need to change X" straight to the file that
owns it — so opening this repo with 10+ tools doesn't mean re-reading
everything to find where something lives. `CLAUDE.md` has the *rules*; this
file has the *floor plan*.

**Layout since roadmap O3 (2026-11-10):** this root file holds the **repo-wide** map (the shell: gateway, state, images,
shared libraries) and an index. **Each tool's own map lives in its folder as `<folder>/KNOWLEDGE_MAP.md`** (text unchanged from the
old single file), next to that tool's `CLAUDE.md` (rules, gotchas, history).

**Rule for every future tool**: when a tool is added, it gets its own `<folder>/KNOWLEDGE_MAP.md` in the same shape as DataDiff
Pro's (`api/KNOWLEDGE_MAP.md`) and one row in the index below. Keep these files in sync with reality — a stale map is worse than no
map, because it actively misleads. If a file's job changes, update its row in the same commit.

## Tool index (open the tool's own map before touching its code)

| Tool | Mounted at | Code map ("where is X") | Rules and gotchas |
|---|---|---|---|
| AI Access | `/tools/ai-access/` | [`ai-access/KNOWLEDGE_MAP.md`](ai-access/KNOWLEDGE_MAP.md) | [`ai-access/CLAUDE.md`](ai-access/CLAUDE.md) |
| Packet Journey | `/tools/packet-journey/` | [`packet-journey/KNOWLEDGE_MAP.md`](packet-journey/KNOWLEDGE_MAP.md) | [`packet-journey/CLAUDE.md`](packet-journey/CLAUDE.md) |
| VLAN Designer | `/tools/vlan-designer/` | [`vlan-designer/KNOWLEDGE_MAP.md`](vlan-designer/KNOWLEDGE_MAP.md) | [`vlan-designer/CLAUDE.md`](vlan-designer/CLAUDE.md) |
| DNS Lookup | `/tools/dns-lookup/` | [`dns-lookup/KNOWLEDGE_MAP.md`](dns-lookup/KNOWLEDGE_MAP.md) | [`dns-lookup/CLAUDE.md`](dns-lookup/CLAUDE.md) |
| Subnet Calculator | `/tools/subnet-calc/` | [`subnet-calc/KNOWLEDGE_MAP.md`](subnet-calc/KNOWLEDGE_MAP.md) | [`subnet-calc/CLAUDE.md`](subnet-calc/CLAUDE.md) |
| Encode/Decode | `/tools/encode-decode/` | [`encode-decode/KNOWLEDGE_MAP.md`](encode-decode/KNOWLEDGE_MAP.md) | [`encode-decode/CLAUDE.md`](encode-decode/CLAUDE.md) |
| cURL Builder | `/tools/curl-builder/` | [`curl-builder/KNOWLEDGE_MAP.md`](curl-builder/KNOWLEDGE_MAP.md) | [`curl-builder/CLAUDE.md`](curl-builder/CLAUDE.md) |
| HTTP Header Reference | `/tools/header-reference/` | [`header-reference/KNOWLEDGE_MAP.md`](header-reference/KNOWLEDGE_MAP.md) | [`header-reference/CLAUDE.md`](header-reference/CLAUDE.md) |
| HTTP Methods & Status Codes | `/tools/http-methods-status/` | [`http-methods-status/KNOWLEDGE_MAP.md`](http-methods-status/KNOWLEDGE_MAP.md) | [`http-methods-status/CLAUDE.md`](http-methods-status/CLAUDE.md) |
| Cookie Lab | `/tools/cookie-lab/` | [`cookie-lab/KNOWLEDGE_MAP.md`](cookie-lab/KNOWLEDGE_MAP.md) | [`cookie-lab/CLAUDE.md`](cookie-lab/CLAUDE.md) |
| DataDiff Pro | `/tools/datadiff-pro/` | [`api/KNOWLEDGE_MAP.md`](api/KNOWLEDGE_MAP.md) | [`api/CLAUDE.md`](api/CLAUDE.md) |
| DataFrame Studio | `/tools/df-studio/` | [`df-studio/KNOWLEDGE_MAP.md`](df-studio/KNOWLEDGE_MAP.md) | [`df-studio/CLAUDE.md`](df-studio/CLAUDE.md) |
| SQL Studio | `/tools/sql-studio/` | [`sql-studio/KNOWLEDGE_MAP.md`](sql-studio/KNOWLEDGE_MAP.md) | [`sql-studio/CLAUDE.md`](sql-studio/CLAUDE.md) |
| Schema Map | `/tools/schema-map/` | [`schema-map/KNOWLEDGE_MAP.md`](schema-map/KNOWLEDGE_MAP.md) | [`schema-map/CLAUDE.md`](schema-map/CLAUDE.md) |
| Duck Lab | `/tools/duck-lab/` | [`duck-lab/KNOWLEDGE_MAP.md`](duck-lab/KNOWLEDGE_MAP.md) | [`duck-lab/CLAUDE.md`](duck-lab/CLAUDE.md) |
| Text Editor | `/tools/text-editor/` | [`text-editor/KNOWLEDGE_MAP.md`](text-editor/KNOWLEDGE_MAP.md) | [`text-editor/CLAUDE.md`](text-editor/CLAUDE.md) |
| Vault Data loader (the former Data Lake tool) | `/tools/data-lake/` | [`data-lake/KNOWLEDGE_MAP.md`](data-lake/KNOWLEDGE_MAP.md) | [`data-lake/CLAUDE.md`](data-lake/CLAUDE.md) |
| Vault | `/tools/vault/` | [`vault/KNOWLEDGE_MAP.md`](vault/KNOWLEDGE_MAP.md) | [`vault/CLAUDE.md`](vault/CLAUDE.md) |
| Data Syncer | `/tools/data-syncer/` | [`data-syncer/KNOWLEDGE_MAP.md`](data-syncer/KNOWLEDGE_MAP.md) | [`data-syncer/CLAUDE.md`](data-syncer/CLAUDE.md) |
| Schema Copy | `/tools/schema-copy/` | [`schema-copy/KNOWLEDGE_MAP.md`](schema-copy/KNOWLEDGE_MAP.md) | [`schema-copy/CLAUDE.md`](schema-copy/CLAUDE.md) |
| Data Dumper | `/tools/data-dumper/` | [`data-dumper/KNOWLEDGE_MAP.md`](data-dumper/KNOWLEDGE_MAP.md) | [`data-dumper/CLAUDE.md`](data-dumper/CLAUDE.md) |
| SSH & SFTP | `/tools/ssh-sftp/` | [`ssh-sftp/KNOWLEDGE_MAP.md`](ssh-sftp/KNOWLEDGE_MAP.md) | [`ssh-sftp/CLAUDE.md`](ssh-sftp/CLAUDE.md) |
| LaTeX to PDF | `/tools/latex-pdf/` | [`latex-pdf/KNOWLEDGE_MAP.md`](latex-pdf/KNOWLEDGE_MAP.md) | [`latex-pdf/CLAUDE.md`](latex-pdf/CLAUDE.md) |
| SharePoint Lists | `/tools/sharepoint/` | [`sharepoint-lab/KNOWLEDGE_MAP.md`](sharepoint-lab/KNOWLEDGE_MAP.md) | [`sharepoint-lab/CLAUDE.md`](sharepoint-lab/CLAUDE.md) |
| Notebook | `/tools/notebook/` | [`notebook-lab/KNOWLEDGE_MAP.md`](notebook-lab/KNOWLEDGE_MAP.md) | [`notebook-lab/CLAUDE.md`](notebook-lab/CLAUDE.md) |
| Mini Sheet | `/tools/mini-sheet/` | [`mini-sheet/KNOWLEDGE_MAP.md`](mini-sheet/KNOWLEDGE_MAP.md) | [`mini-sheet/CLAUDE.md`](mini-sheet/CLAUDE.md) |
| SQL Practice | `/tools/sql-practice/` | [`sql-practice/KNOWLEDGE_MAP.md`](sql-practice/KNOWLEDGE_MAP.md) | [`sql-practice/CLAUDE.md`](sql-practice/CLAUDE.md) |

Not tools: `mcp_server/` (stdio MCP server for AI clients — [`mcp_server/KNOWLEDGE_MAP.md`](mcp_server/KNOWLEDGE_MAP.md), [`mcp_server/CLAUDE.md`](mcp_server/CLAUDE.md), design `docs/architecture/ADR-MCP.md`), `orchestrator/` (headless CLI — `orchestrator/CLAUDE.md`), `core/` (shared libraries — see the repo-wide section below and
`docs/architecture/shared-connectors.md`), `core_plugins/` (manifest loader, gateway, supervisor, autoscaler, Status page).

---

## Repo-wide (the Toolbox shell — not any one tool's code)

| If you need to change...                                    | Go to |
|---------------------------------------------------------------|-------|
| The home page layout / card styling                           | `main.py` (`_HOME_TEMPLATE`, `_render_card`) |
| Which tools show up as cards, their title/description/icon/order, and how they are mounted | each tool's `manifest.yaml` (spec `docs/architecture/plugin-manifest.md`), loaded by `core_plugins/loader.py` in `main.py` |
| Whether a tool defaults to shown or hidden (Tool vs Learn), the search box, the "Show learning tools" toggle | `category:` in each tool's `manifest.yaml` + `main.py`'s home page `<script>` block |
| Turning a tool on/off, seeing which tools are loaded             | Settings tab of the workspace UI → `POST /api/workspace/plugins/<name>` in `main.py` (live swap via `Slot`); saved in `workspace.yaml` (volume `workspace_data`, `core_plugins/workspace.py`); `GET /api/workspace/status`; lazy import in `core_plugins/lazy.py` |
| Where Toolbox keeps state outside the web process (Postgres, Redis, S3 files), checking it is up | `core/state/` (`config.py` env vars, `db.py`, `sessions.py`, `objects.py`, `selftest.py`); `GET /api/state/health` in `main.py`; services in `docker-compose.yml` |
| Which image a tool runs in (incl. the worker's own `worker` target, C4), its Python packages, building the images, sizes/memory (`docs/roadmap/measure-C4.md`) | manifest `runtime:` → Dockerfile target of the same name + `requirements/<runtime>.txt`; `TOOLBOX_ROLE=runtime`/`TOOLBOX_RUNTIME` in `main.py` `_app_for`; compose `rt-*` services (behind the gateway since C2); `tests/unit/test_runtimes.py` (roadmap C1) |
| Which container answers /tools/<name>, the gateway proxy, a "starting or unavailable" page | `TOOLBOX_RUNTIME_URLS` + `_app_for` in `main.py` (gateway = web role in the `gateway` image); `core_plugins/proxy.py`; `toolbox` + `rt-*` services in `docker-compose.yml` (roadmap C2) |
| A tool "asleep"/slow first open, idle timeout, which runtimes are on-demand, container limits, what the gateway may do to Docker | `core_plugins/supervisor.py` (`on_demand_runtimes`, `RuntimeSupervisor`, `Supervisor` sweep); `_supervisors` + `/api/workspace/runtimes` in `main.py`; manifest `tier`/`scaling`/`resources`; compose `docker-proxy` + `configs.docker_proxy_rules`, `mem_limit`/`cpus` on rt-* (roadmap C3) |
| Replicas: how many run, why it scaled up/down, which replica got a request, worker pool size | `core_plugins/autoscale.py` (`ScaledService.tick`, thresholds `UP_CPU`/`DOWN_CPU`/`DOWN_AFTER`/`COOLDOWN`), `core_plugins/balancer.py` (`Balancer.pick`, `mark_failed`), wiring + `scaled` in `/api/workspace/runtimes` in `main.py`, retry loop in `core_plugins/proxy.py`; compose `deploy.replicas` + `TOOLBOX_WORKER_SCALING` (roadmap D3) |
| The Status tab: what it shows, the attention rules, where each number comes from | `core_plugins/overview.py` (`containers`, `jobs_summary`, `storage_summary`, `attention`), `/api/workspace/overview` + `/api/state/overview` in `main.py`, `renderStatus` in `core_plugins/ui/workspace.html` (roadmap E1) |
| Per-tool request/error/slow counters, the recent-errors list, the log window, the sidebar alert badge | `core_plugins/metrics.py` (`Metered`, `record`, `flush`, `read`, `recent_errors`), `core_plugins/overview.py` (`logs`, `_demux`, `container_states`, `attention`), `/api/workspace/{metrics,errors,logs/<name>,alerts}` in `main.py`, `loadAlerts`/`showLog`/`spark` in `core_plugins/ui/workspace.html` (roadmap E2/E3) |
| The built-in `system` workspace (always exists; no rename/delete; default for saves without a workspace) | `core/lake.py` (`SYSTEM_WORKSPACE`, `list_workspaces`, `update_workspace`, `delete_workspace`, `write_table`/`import_file`/`register_external` defaults); Vault page `#wsList` (built-in pill, rename/delete hidden) |
| A tool with no card/sidebar entry (API only) | manifest `hidden: true` → `main.py` `_load_registry`/`home`, `core_plugins/ui/workspace.html` Settings (`vis`) |
| Vault Data: workspaces/tables, where a table's files are, versions/history, importing old datasets, which tool may read/write Data | `core/lake.py` (`create_workspace`, `write_table`, `rename_table`, `drop_table`, `preview`, `local_files`, `import_vault_datasets`, `scoped`), `/data*` endpoints in `vault/server.py`, Data tab in `vault/ui/index.html`, manifest `vault: {data: …}` (roadmap L1) |
| Installing Toolbox as an app, its name/colors/shortcuts, the icons, the favicon | `_WEBMANIFEST`, `/manifest.webmanifest`, `/icons/{name}`, `/favicon.ico` in `main.py`; icons in `core_plugins/ui/icons/` (regenerate: `python3 tools/icons/make_icons.py`); `<link rel="manifest">` in `core_plugins/ui/workspace.html` (roadmap G1) |
| Backups / restore, what's in an archive, the "last backup" line | `scripts/backup.sh`, `scripts/restore.sh`, `core/state/backup.py` (`objects_export`, `objects_import`, `mark`, `last`), `backup` in `/api/state/overview` (main.py) + `attention` (overview.py); owner how-to `docs/runbook.md` (Ops session) |
| Docker filters per compose project (two stacks side by side), one-off containers ignored | `core_plugins/dockerapi.py` (`own_project`, `service_filter`) |
| Several web workers: worker count, singleton routing, switches/load state shared between processes | `TOOLBOX_WEB_WORKERS` (compose `toolbox.command`, Dockerfile `CMD`); `TOOLBOX_ROLE` / `TOOLBOX_SINGLETON_URL` + `_app_for` in `main.py`; `core_plugins/proxy.py` (`ProxyApp`); `_sync_workspace` / `_WorkspaceSync` and `_publish_now` / `_all_processes` in `main.py`; `singletons` service in `docker-compose.yml` (roadmap B9) |
| What an AI can do with a tool: the manifest `ai:` section, the capability registry, `find_actions` / `run_action`, its token cost | `core_plugins/manifest.py` (`AiAction`), `core_plugins/ai.py`, `mcp_server/registry.py`, `docs/architecture/plugin-manifest.md` ("AI actions"), `docs/roadmap/measure-H3.md`, `tools/bench/ai_registry_tokens.py` |
| The AI helper engine on the host (runs `claude -p` with the owner's login; start/stop, safety flags), and the gateway pass-through | `ai-bridge/engine.py`, `ai-bridge/bridge.py`, `ai-bridge/install.py`, `ai-bridge/CLAUDE.md`, `core_plugins/helper.py`, the panel in `core_plugins/ui/workspace.html` (search `hlp`/`helper`), `tests/unit/test_ai_bridge.py`, `tests/smoke/test_helper_panel.py`, plan cards: `mcp_server/approvals.py`, `tests/unit/test_mcp_approvals.py`; gap actions + recipes: `mcp_server/pipeline.py`, `mcp_server/recipes.py`, `frame.flatten_json`, `tests/unit/test_mcp_pipeline.py`, runbook "Set up the AI helper" |
| Removing a tool cleanly (plan / blockers / data left in place, the edits it reverses, volumes, confirmation rules) | `scripts/remove_tool.py` (`make_plan`, `apply`, `edit_dockerfile`, `edit_smoke_api`, `edit_compose`); tests `tests/unit/test_remove_tool.py` |
| Creating a new tool (the template, the placeholders, the files the scaffold edits, the Dockerfile marker) | `tools/_template/` (+ its `README.md`), `scripts/new_tool.py`, tests `tests/unit/test_new_tool_template.py`; Dockerfile marker `# >>> scripts/new_tool.py` |
| Allowing a custom PYTHON plugin in `plugins/` (the `TOOLBOX_TRUSTED_PLUGINS` flag, import-name / runtime rules, sample) | `core_plugins/loader.py` (`trusted_plugins_enabled`, `_check_trusted_python`), `main.py` (sys.path), compose (`./plugins` mounted into rt-light / rt-data only), `plugins/README.md`, `plugins/examples/hello_python/` |
| Adding a custom app without rebuilding (own HTML page or external link), its sandbox | `plugins/<name>/manifest.yaml` (+ files) — `plugins/README.md`; served by `StaticApp` / `ExternalApp` in `core_plugins/lazy.py`; only static/external allowed (`EXTRA_DIR_KINDS` in `core_plugins/loader.py`) |
| The workspace page itself: sidebar, tabs, settings, search, keyboard shortcuts | `core_plugins/ui/workspace.html` (self-contained; `main.py` injects `{{CARDS}}` and `{{DATA}}`) |
| Actually wiring a tool's app into the site (routing)           | automatic: `main.py` loops over `kind: python` manifests and mounts each as a lazy `LazyApp` (bottom of file) — set `entry:` in the tool's `manifest.yaml`, don't edit `main.py` |
| The Docker image / what gets copied into the container         | `Dockerfile` |
| Ports, restart policy, env vars for the whole site              | `docker-compose.yml` |
| Why the container runs `--workers 1` (not more)                 | `Dockerfile` (CMD comment) + `CLAUDE.md`'s "Standing rule: stateful tools and --workers" — check every stateful tool, not just df-studio, before ever raising this |
| The canonical color palette every new tool's `:root` should start from | `theme-tokens.css` — copy-source only, never served; see its own header for why |
| Architecture decisions, conventions, "why is it built this way" | `CLAUDE.md` |
| GitHub auth setup for this device                               | `GITHUB_AUTH.md` |
| Calling a tool's engine directly without a browser (headless), chaining two tools together | `orchestrator/` — see its own `CLAUDE.md`; not a mounted tool, no entry here and no `manifest.yaml` |
| DataDiff Pro's mapping/equivalence/diff logic shared between the web UI and the orchestrator | `core/pipeline.py` (`run_compare`) |
| Connecting to Postgres safely (conninfo, credential pre-validation, SSH tunneling, password scrubbing) — shared by schema-map and the orchestrator's Postgres connector (Postgres-only consumers) | `core/postgres_conn.py` (`build_conninfo`, `verify_connection`, `open_ssh_tunnel`, `scrub_password`) |
| Connecting to Postgres **or** SQL Server **or** Oracle — the `Dialect` abstraction SQL Studio uses to pick a database type per connection | `core/db/dialect.py` (the `Dialect` protocol), `core/db/dialect_postgres.py`/`dialect_mssql.py`/`dialect_oracle.py` (the three implementations), `core/db/registry.py` (`get_dialect(db_type)`) |
| The pool+reaper lifecycle, generalized over any `Dialect` — SQL Studio passes a dialect per `connect()` call; schema-map's own separate `_POOL` instance keeps using the Postgres-only subclass, unaware anything changed underneath | `core/pooled_db.py` (`PooledDbConnection`), `core/pooled_postgres.py` (`PooledPostgresConnection`, now a 3-line backward-compatible subclass) |
| Mapping a file extension to a DuckDB read function (csv/json/parquet) — shared by duck-lab and the orchestrator's file connector | `core/file_source.py` (`build_read_expr`, `detect_format`) |
| The shared encrypted secret store (saved DB connections, SSH credentials, anything else) — behind the Vault tool and sql-studio/schema-map's "Save/Load connection" controls | `core/vault.py` — see its own module docstring and `vault/CLAUDE.md` for the trust model |

---

---

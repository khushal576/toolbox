# Plugin manifest spec (v1)

Every tool (plugin) is described by a `manifest.yaml` in its folder. The workspace discovers manifests,
shows them on the home page, decides **how** to load each one (kind), **where** it runs (runtime/tier)
and what state/resources it needs. Code: `core_plugins/manifest.py` (model) and
`core_plugins/loader.py` (discovery). Decision context: `ADR-001-workspace-plugins.md`.

Status: introduced in roadmap **A1**; since **A2** every tool has one and `main.py` builds the home page
and mounts from them (`registry.yaml` and the hand-written mount list are gone).

## Example
```yaml
schema_version: 1
name: datadiff-pro            # unique slug; URL is /tools/<name>/
title: DataDiff Pro
description: Deep smart diff for JSON, XML & CSV
icon: "🔍"
category: tool                # tool | learn
kind: python                  # static | python | external | service
entry: api.app:app            # python → "module:attribute" (an ASGI app)
runtime: data                 # light | data | pgtools | latex | ssh | notebook
tier: 3                       # 1 static/client-side · 2 light · 3 data-heavy · 4 special image
state: []                     # any of: session, durable, jobs   (empty = stateless)
resources: {cpu: 1.0, memory_mb: 512}
scaling: {min: 0, max: 4, idle_timeout_s: 900}
depends_on: []                # other plugin names this one calls over HTTP (e.g. vault)
requires: []                  # system capabilities the runtime must provide (e.g. texlive, pg_client)
enabled_by_default: true
order: 10                     # display order: lower first, ties by title
```

## Fields
| Field | Required | Type / values | Meaning |
|---|---|---|---|
| `schema_version` | no (default 1) | `1` | Manifest format version. Bump only with a migration. |
| `name` | yes | slug `^[a-z0-9][a-z0-9-]{1,62}$` | Unique id, folder-independent. Mounted at `/tools/<name>/`. |
| `title` | yes | text | Card/tab title. |
| `description` | no | text | One line on the card. |
| `icon` | no | short text/emoji | Card icon. |
| `category` | no (default `tool`) | `tool` \| `learn` | `learn` = educational/reference (hidden by default on the home page). |
| `kind` | yes | `static` \| `python` \| `external` \| `service` | How the workspace loads it (below). |
| `entry` | depends on kind | text | See kinds. |
| `runtime` | python/service: yes | `light` \| `data` \| `pgtools` \| `latex` \| `ssh` \| `datadiff` \| `notebook` | Which runtime image hosts it: Dockerfile target + `requirements/<runtime>.txt` (roadmap C1); the gateway routes there from C2. Until then the `full` image serves every tool. |
| `tier` | no (default 2) | 1–4 | Cost class from ADR-001. |
| `state` | no (default `[]`) | list of `session`, `durable`, `jobs` | What state it keeps; drives phase B work and replica rules. |
| `resources.cpu` / `resources.memory_mb` | no | number / int | Since roadmap C3 the runtime container's compose `cpus`/`mem_limit` = the SUM over its plugins (`tests/unit/test_runtimes.py` keeps them equal). No value anywhere in a runtime = no limit. |
| `scaling.min` / `.max` / `.idle_timeout_s` | no (0 / 1 / 900) | ints | C3: a runtime whose plugins are ALL `tier: 4` with `min: 0` is on-demand — the gateway starts its container on the first request and stops it after the largest `idle_timeout_s` (env `TOOLBOX_IDLE_TIMEOUT_S` overrides). `min: 1` keeps it warm. `max` > 1 (D3): the runtime becomes a pool of `max` containers (compose `deploy.replicas`) autoscaled by CPU between `min` and `max`, balanced by the gateway. |
| `depends_on` | no | list of plugin names | Other plugins it calls. Must exist. |
| `requires` | no | list of capability names | e.g. `texlive`, `fontawesome`, `pg_client`, `duckdb`. |
| `enabled_by_default` | no (true) | bool | Default for `workspace.yaml` (A3). |
| `hidden` | no (false) | bool | Mounted and working, but no home card, sidebar entry or Settings switch — for a tool whose API other pages use and whose UI lives elsewhere (Data Lake → Vault Data). |
| `order` | no (1000) | int ≥ 0 | Display order (lower first); ties sorted by title. |
| `vault` | no (none) | `{read: [kinds], write: [kinds], datasets: none\|read\|write, data: none\|read\|write}` (`data` = Vault Data / lake tables, roadmap L1) | What the plugin's server code may do in the Vault (roadmap B7), enforced by `core.vault.scoped(<name>)` and the Vault's `/api/v1` API. `write` implies read. Not allowed on `static`/`external`. No entry = no access. |
| `singleton` | no (false) | bool | Must run in exactly one process (requires `scaling.max: 1`). Set for sql-studio and schema-map (roadmap B3: one live DB pool, password never stored); since B9 they run in the `singletons` service and every web worker forwards their traffic there (`core_plugins/proxy.py`). |

Unknown keys are **rejected** (typos must not pass silently).

## Kinds
| Kind | `entry` | `runtime` | Example |
|---|---|---|---|
| `static` | path to the HTML file, relative to the manifest folder (default `ui/index.html`) | must be empty | client-side tools, custom HTML apps (A5) |
| `python` | `module.path:attribute` naming an ASGI app | required | today's FastAPI tools |
| `external` | `http://` or `https://` URL | must be empty | link to another app/container (A5) |
| `service` | `http://` or `https://` base URL of a separately running service | required | shared APIs such as DataDiff (D1) |

Rules checked by the model:
- `static`/`external` have **no state** and **no runtime**; they cost no server memory.
- `stateful` plugins (`state` not empty) must keep `scaling.max: 1` **until roadmap B9** unless the state
  is already external — the loader reports a warning, not an error, so B-phase work can proceed.
- `scaling.min <= scaling.max`.

## Discovery
- The loader scans `<repo>/*/manifest.yaml` (one level deep) and any extra plugin folders it is given
  (`plugins/` in A5). Folder names don't matter; `name` does.
- A broken manifest **never stops the others**: errors are collected (`Registry.errors`) like
  `main.py`'s per-tool fault isolation.
- Duplicate `name` → the second one is rejected with an error.
- `depends_on` naming an unknown plugin → error on that plugin.
- Order: by `order`, then title. The 20 original tools use 10, 20, … 200 (their old `registry.yaml`
  order); new tools default to 1000.

## Custom apps (`plugins/`, roadmap A5)
- `main.py` also scans `$TOOLBOX_PLUGINS_DIR` (compose: `./plugins` bind-mounted read-only at `/app/plugins`).
  New apps there need a restart, not an image rebuild. How-to: `plugins/README.md`.
- Only `kind: static` and `kind: external` are accepted there **by default** (`core_plugins/loader.py` `EXTRA_DIR_KINDS`); a
  `python` manifest in a custom-app folder is rejected with an error that says how to enable it, and a `service` manifest is
  always rejected, because it would run with full access inside the container (database, Redis, S3 and the Vault key).
- **Trusted Python plugins (roadmap P1).** With `TOOLBOX_TRUSTED_PLUGINS=1` (set in `.env`, then `docker compose up -d`; **default off**;
  only `1/true/yes/on` count) a `kind: python` plugin may live in `plugins/`. It is trusted code — it can read everything the runtime can,
  including the Vault key — so the loader adds rules: (1) the **folder name is the import name**: a plain lowercase identifier, not starting with
  `_`, and not the name of a Toolbox or standard-library package; (2) `entry` must start with the folder name (`my_tool.server:app` in
  `plugins/my_tool/`); (3) `runtime` must be `light` (or `data` if it needs pandas/DuckDB) — the only runtimes that mount `plugins/`
  (compose mounts it read-only into `toolbox`, `rt-light` and `rt-data` only); (4) no `singleton`. `main.py` appends `plugins/` to `sys.path`
  (appended, so Toolbox's own packages always win) only when the flag is on. Each accepted plugin logs a "trusted code" warning at start,
  and `GET /api/workspace/status` shows `trusted_plugins`. A starter lives in `plugins/examples/hello_python/` (copy it up one level).
  Built-in tools are not subject to these rules. Tests: `tests/unit/test_trusted_plugins.py`.
- `static` → `StaticApp` (`core_plugins/lazy.py`): serves the entry for `/` and other files inside the folder only
  (no `..`, no hidden files, never `manifest.yaml`, GET/HEAD only), with
  `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads` — no
  `allow-same-origin`, so the page runs in an opaque origin and cannot read Toolbox APIs or storage.
- `external` → `ExternalApp`: `/tools/<name>/` answers `307` to `entry`. Showing it inside a tab depends on the
  target site's frame policy; "New window" always works.
- Static/external plugins report state `ready` in `/api/workspace/status` and have the same on/off switch.

## AI actions (`ai:`, roadmap H3)
A `kind: python` tool may describe what an AI can do with it, in an optional `ai:` section. The AI helper does not read every tool's description — it **searches** these actions
(`find_actions` → `describe_action` → `run_action`, ADR-AI-HELPER D6), so a new tool teaches the helper about itself and a removed tool disappears from it.

```yaml
ai:
  actions:
    - name: list_templates              # lowercase letters, digits, _ (2-41 chars); unique within the tool
      summary: List the saved pipeline templates   # 3-200 chars, in the user's words — this is what find_actions searches
      path: template/list               # GET /tools/<name>/template/list ; relative, no '..', no query string; {id} placeholders allowed
      inputs:                           # optional; flat: string | integer | number | boolean, each may have description, enum, max_length, minimum, maximum, default
        limit: {type: integer, minimum: 1, maximum: 100, default: 20}
      required: []                      # names from inputs; every {placeholder} in the path must be listed here, and be an integer or a string with max_length/enum
      returns: templates - a list       # one line (optional)
```
Rules (enforced by `core_plugins/manifest.py`; the checks on a call by `core_plugins/ai.py`):
- **Only stateless READ actions can be declared**: `effect` can only be `read`, `method` only `GET`. A manifest can never expose a write; anything that changes data is an MCP tool in `mcp_server/`
  with the owner's grant, dry-run, confirm code and read-back (ADR-MCP D7).
- The AI's inputs are validated against the declared types and limits, unknown inputs are refused, and a value placed in the path may only contain letters, digits and `_ . @ : + = , -` — an action can
  never reach another tool or another endpoint than the declared one. No redirects are followed, no cookies kept, answers over 1 MB are refused.
- Do not declare actions that depend on a browser session (cookies) or on a connected database — the AI has neither. Static / external tools have no API and cannot declare actions.
- A test (`tests/unit/test_ai_manifest.py`) fails if a declared path is not a `GET` route in the tool's own code. At most 20 actions per tool; keep summaries unique.
Where it runs: the MCP server (worker container) calls `$TOOLBOX_GATEWAY_URL` (compose: `http://toolbox:8080`), so a switched-off tool answers "switched off", an on-demand runtime is started as usual.


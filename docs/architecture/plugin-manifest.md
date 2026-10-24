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
runtime: data                 # light | data | pgtools | latex | ssh
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
| `runtime` | python/service: yes | `light` \| `data` \| `pgtools` \| `latex` \| `ssh` | Which runtime image hosts it (phase C). |
| `tier` | no (default 2) | 1–4 | Cost class from ADR-001. |
| `state` | no (default `[]`) | list of `session`, `durable`, `jobs` | What state it keeps; drives phase B work and replica rules. |
| `resources.cpu` / `resources.memory_mb` | no | number / int | Limits applied by the supervisor (phase C). |
| `scaling.min` / `.max` / `.idle_timeout_s` | no (0 / 1 / 900) | ints | Replicas and scale-to-zero (phases C–D). |
| `depends_on` | no | list of plugin names | Other plugins it calls. Must exist. |
| `requires` | no | list of capability names | e.g. `texlive`, `fontawesome`, `pg_client`, `duckdb`. |
| `enabled_by_default` | no (true) | bool | Default for `workspace.yaml` (A3). |
| `order` | no (1000) | int ≥ 0 | Display order (lower first); ties sorted by title. |

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
- Only `kind: static` and `kind: external` are accepted there (`core_plugins/loader.py` `EXTRA_DIR_KINDS`); a
  `python`/`service` manifest in a custom-app folder is rejected with an error, because it would run with full
  access inside the container (Vault included).
- `static` → `StaticApp` (`core_plugins/lazy.py`): serves the entry for `/` and other files inside the folder only
  (no `..`, no hidden files, never `manifest.yaml`, GET/HEAD only), with
  `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads` — no
  `allow-same-origin`, so the page runs in an opaque origin and cannot read Toolbox APIs or storage.
- `external` → `ExternalApp`: `/tools/<name>/` answers `307` to `entry`. Showing it inside a tab depends on the
  target site's frame policy; "New window" always works.
- Static/external plugins report state `ready` in `/api/workspace/status` and have the same on/off switch.


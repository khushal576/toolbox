# Custom apps (`plugins/`)

Drop a folder here with a `manifest.yaml` and it appears in the workspace after a restart — **no image rebuild**
(this folder is bind-mounted read-only into the container at `/app/plugins`). Roadmap session A5.

By default only two kinds are allowed here, because they run **no code on the server**:

| Kind | What you put in the folder | What happens |
|---|---|---|
| `static` | `manifest.yaml` + your HTML/CSS/JS files | Served at `/tools/<name>/`, opens in a workspace tab |
| `external` | just `manifest.yaml` with `entry: https://…` | `/tools/<name>/` redirects to the URL (tab or new window) |

Python plugins are **refused by default**: they would run with full access inside Toolbox (the database, Redis, S3 and the Vault key).
Either add them to the image like the built-in tools (root `CLAUDE.md`, "Adding a new tool"), or switch on **trusted Python plugins** below.

## Minimal static app
```yaml
# plugins/my-notes/manifest.yaml
name: my-notes            # unique, lowercase, letters/digits/-
title: My Notes
description: A tiny page of my own
icon: "🗒️"
kind: static
entry: index.html         # default ui/index.html
tier: 1
order: 900                # display order (built-in tools use 10–200)
enabled_by_default: true  # false = listed in Settings but off until you switch it on
```
Then `docker compose restart toolbox`. Full field list: `docs/architecture/plugin-manifest.md`.

## Security: static apps are sandboxed
Static apps are served with `Content-Security-Policy: sandbox allow-scripts allow-forms allow-popups allow-modals
allow-downloads`. Your JavaScript runs, but the page gets an **isolated origin**: it cannot read Toolbox APIs
(Vault, workspace settings) or the workspace's localStorage. Consequences for your app:
- `localStorage`/cookies are not available — wrap storage in `try/catch` or keep state in the page/URL.
- Calls to Toolbox's own APIs fail (by design). Calls to other sites follow their CORS rules.
- Use relative paths for your own files (`style.css`, `img/logo.png`); hidden files and `..` are never served.

## Samples (both start **off** — switch them on in Settings)
- `hello-static/` — a static page that also shows the sandbox blocking a Toolbox API call.
- `example-link/` — an external link.

## Trusted Python plugins (optional, off by default — roadmap P1)
Use this only for code **you wrote or fully trust**: a Python plugin can read the database and every saved secret, exactly like Toolbox itself.
1. Set `TOOLBOX_TRUSTED_PLUGINS=1` in `.env`.
2. Copy the starter: `cp -r plugins/examples/hello_python plugins/hello_python` (then edit it).
3. `docker compose up -d` (this recreates the gateway and the `light`/`data` runtimes with the flag and the mount).
4. Open Settings and switch the plugin on. Its page is `/tools/<name>/`.

Rules the loader enforces (an error in the start-up log tells you which one you broke):
- The **folder name is the import name**: lowercase letters, digits, `_`; not starting with `_` or a digit; not the name of a Toolbox or standard-library package.
- `entry` starts with the folder name: `entry: hello_python.server:app` in `plugins/hello_python/`.
- `runtime: light` (or `data` if you need pandas / DuckDB). Other runtimes never mount this folder.
- No `singleton: true`. Keep the frontend's calls **relative** (`fetch('info')`), like every tool.
Python code changes need `docker compose restart rt-light` (or `rt-data`). Remove a plugin by deleting its folder; turn the whole feature off by removing the `.env` line.


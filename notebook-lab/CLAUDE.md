# Notebook — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and `../KNOWLEDGE_MAP.md` (section
"Tool: Notebook") for the symptom→file map.

## What this tool is

A Colab-like notebook in the workspace: named **workspaces** (folders, like Colab's `/content`), a file browser with
upload (files, folders, `.zip` auto-unpacked) and download (file or folder as `.zip`), `.ipynb` notebooks with code +
markdown cells, one Jupyter **kernel per workspace**, and **per-workspace pip installs** (a venv, so TensorFlow etc.
are temporary: Reset / deleting the workspace removes them).

## Where things live

| Concern | File |
|---|---|
| Workspace dirs, path safety, files, zip in/out, venv, kernel env, pip spec parsing | `workspaces.py` |
| Kernels (jupyter_client), run queue, `Execution` outputs, idle reaper, pip install jobs | `kernels.py` |
| API + `.ipynb` conversion | `server.py` |
| Page (no framework, no build step) | `ui/index.html` |
| Manifest (runtime `notebook`, tier 4, 2 GB / 2 CPU, idle 30 min) | `manifest.yaml` |

## Rules that must hold

- **Runs user code → no credentials.** `rt-notebook` gets only `TOOLBOX_REDIS_URL` (compose) and `kernel_env()` is an
  allow-list; never add `vault:` to the manifest, never import `core.vault`/`core.state` here, never pass
  `os.environ` to a kernel. `tests/unit/test_notebook.py` checks that a kernel sees no `TOOLBOX_*`.
- **One uvicorn worker** (Dockerfile `notebook` target) — kernels are in this process's memory.
- Dot-folders `.venv .home .kernels .tmp` at a workspace root are reserved: hidden, refused by every file API and
  skipped by zip extraction.
- Zip extraction writes members by hand (no `ZipFile.extract`): absolute/`..`/reserved/symlink members are skipped
  and counted; entry-count and uncompressed-size limits are checked up front.
- HTML outputs render in an iframe `sandbox="allow-same-origin"` (NO `allow-scripts`) — a notebook from elsewhere
  can't run script in the Toolbox origin.

## UI notes (ui/index.html)

- Icon-only controls (inline SVG set `IC`, tooltips in `title`); no explanatory paragraphs — keep it that way. Layout =
  icon rail → collapsible/resizable side panel (Files, Packages) → document tabs → one toolbar → cells. The sidebar
  hides with the rail icon, the tab-bar panel icon (hides the rail too) or Ctrl+B; layout + open tabs persist in
  localStorage (`nb.ui`, `nb.open.<workspace>`).
- Several documents can be open (`S.docs`); the server cell id is `<doc.key>:<cell id>` so two notebooks never share a
  run record. Jupyter keys: Esc = command mode; a/b insert, dd delete, m/y type, ↑↓/j/k move, Enter edit,
  Shift/Ctrl/Alt+Enter run.
- Code colouring = a `<pre>` overlay under a transparent `<textarea>` (`hl()`); both must keep identical font, padding
  and wrapping or the colours drift off the caret.
- `[hidden]` needs the global `!important` rule: component display rules (`textarea.plain`) otherwise beat it.

## SharePoint bridge (S1)

`lib/toolbox_sharepoint.py` is on every kernel's `PYTHONPATH` (`kernel_env`) and talks to the SharePoint tool through the
gateway at `SP_BRIDGE_URL` (compose sets it; a URL only, never a token — this container must keep holding no credentials).
`sp.read` → DataFrame, `sp.stage(df)` records changed cells; approval happens in the SharePoint tool. See `../sharepoint-lab/CLAUDE.md`.

## Testing

`tests/unit/test_notebook.py` — safety tests run anywhere; the real-kernel tests need the runtime image:
`docker run --rm -v $PWD/tests:/tests:ro -w /app toolbox-rt-notebook sh -c "pip install -q pytest; python -m pytest /tests/unit/test_notebook.py -q"`

## Not done yet (ideas, not promises)

- Vault Data tables as DataFrames inside a cell (needs a credential-free bridge, e.g. a server-side export endpoint).
- GPU runtimes, autocomplete/inspection, `input()` support, multiple kernels per workspace, outputs of widgets/JS.

## Notebook runtime (roadmap N1) — platform view

> Moved **verbatim** from the root `CLAUDE.md` by roadmap session O3 (2026-11-10). The root keeps only the rules and an index;
> nothing was reworded. Paths in the text are repo-root relative.

- **Notebook (roadmap N1):** `notebook-lab/` — Colab-style workspaces + Jupyter kernels in its OWN runtime `rt-notebook`
  (on-demand, one uvicorn worker, volume `notebook_data`). It executes user code, so that container has **no
  Postgres/S3/Vault credentials** (compose gives it only `TOOLBOX_REDIS_URL` and a bridge URL) — keep it that way; see `notebook-lab/CLAUDE.md`.

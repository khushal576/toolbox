<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Notebook — mounted at `/tools/notebook/`

Colab/Jupyter-style workspaces: upload files, folders or a whole project `.zip`, open/create `.ipynb` notebooks, run
Python cells in a real Jupyter kernel (pandas, matplotlib, `df.to_csv(...)` writes into the workspace), pip-install
packages like TensorFlow per workspace (temporary — Reset forgets them) and download any file or folder as `.zip`.
Runs in its own on-demand runtime `rt-notebook` that holds **no Postgres/S3/Vault credentials** (it executes user
code). See `notebook-lab/CLAUDE.md`.

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| Workspace folders, path safety (`..`, reserved `.venv/.home/.kernels/.tmp`, symlinks), zip extract/zip download limits | `notebook-lab/workspaces.py` (`safe`, `extract_zip`, `make_zip`, `MAX_*`) |
| What env user code gets (nothing from the server), venv creation, kernelspec | `notebook-lab/workspaces.py` (`kernel_env`, `ensure_env`, `write_kernelspec`) |
| Kernel start/stop/restart/interrupt, the run queue, "Run all stops at first error", output shaping + caps | `notebook-lab/kernels.py` (`KernelSession`, `Execution`) |
| pip installs (accepted specs, streamed log, `--local` package list) | `notebook-lab/workspaces.py` (`pip_args`), `notebook-lab/kernels.py` (`start_install`, `installed`) |
| Idle kernel reaping (30 min), container sleep (manifest `scaling.idle_timeout_s`) | `kernels.py` (`KERNEL_IDLE_S`, `_reap`), `notebook-lab/manifest.yaml` |
| API, `.ipynb` read/write (nbformat 4.5) | `notebook-lab/server.py` |
| The page (file browser, uploads incl. folders/zip, cells, outputs, markdown) | `notebook-lab/ui/index.html` |
| Image / dependencies / memory limit | `Dockerfile` (`notebook` target), `requirements/notebook.txt`, `docker-compose.yml` (`rt-notebook`, `notebook_data`) |

### Known non-obvious behavior (read before touching these areas)

- **Single web process on purpose** (`--workers 1` in the `notebook` target): kernels are child processes held in
  this process's memory — the same standing exception as the SSH terminal. Nothing else may rely on that.
- **Cells are polled, not streamed** (`GET /executions/{id}?v=`): survives reloads and the gateway's no-websocket rule.
  A page that was closed while a cell ran adopts the finished outputs on open (`reattach`).
- **Packages live in `<workspace>/.venv`** (`--system-site-packages`): pip sees the base image's numpy/pandas as
  installed, so `pip install tensorflow` adds only what is missing instead of shadowing numpy for the whole stack.
- **No credentials in the container**: kernels get an explicit env (`kernel_env`), and compose gives `rt-notebook`
  only `TOOLBOX_REDIS_URL`. A cell can still reach other containers on the compose network (single-owner trust model).
- The container sleeps after `idle_timeout_s` (30 min) without gateway traffic; kernels die with it. A long cell with
  the tab closed can therefore be cut off after 30 min.
- Dashboard: the `rt-notebook` memory cap (2 GB) is the real limit for TensorFlow work; a killed kernel shows
  "The kernel died" in the cell.

<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: SharePoint Lists — mounted at `/tools/sharepoint/`

Connect many SharePoint sites (Vault connections, Microsoft Graph), browse every list with all its columns, edit cells / add
items in a grid or stage edits from a notebook with Python, and write to SharePoint only after a review of the exact
old → new changes is approved. No delete, by owner decision. Runs in runtime `data`. See `sharepoint-lab/CLAUDE.md`.

| If you need to change... | Go to |
|---|---|
| Getting a Graph token (client secret / device-code sign-in, refresh-token persistence, clouds) | `sharepoint-lab/auth.py` (`TokenProvider`, `device_start/poll`) |
| Graph calls: paging, retry on 429, `$batch`, the "no delete" write guard, same-host link guard | `sharepoint-lab/graph.py` (`_check_write`, `Graph`) |
| Which column types are editable, value validation, "same value?", multi-choice payload | `sharepoint-lab/columns.py` (`describe`, `coerce`, `same`, `payload`) |
| Staging, review digest, apply (conflict check, batches, read-back, audit), rebase, CSV export | `sharepoint-lab/service.py` (`stage_cell`, `review`, `apply`, `rebase`, `export_csv`) |
| Staged edits + audit trail tables | `sharepoint-lab/store.py` (Postgres schema `sharepoint_lab`) |
| Saving/listing connections (Vault kind `sharepoint_connection`, no secret leaves the server) | `sharepoint-lab/service.py` (`public_view`, `create_connection`), manifest `vault:` |
| API endpoints / error mapping | `sharepoint-lab/server.py` |
| The page (connection tree, grid, cell editors, review/approve/result dialogs, schema, audit) | `sharepoint-lab/ui/index.html` |
| Python in a notebook (`import toolbox_sharepoint as sp`), what the kernel gets (`SP_BRIDGE_URL` only) | `notebook-lab/lib/toolbox_sharepoint.py`, `notebook-lab/workspaces.py` (`kernel_env`), `docker-compose.yml` (`rt-notebook`) |
| Trying it without a tenant | `tests/unit/fake_graph.py`, `tests/unit/sp_dev_server.py` |

### Known non-obvious behavior

- Built against a **fake** Graph; not yet run on a real tenant (see the tool's CLAUDE.md for what is most likely to differ).
- Approval is a UI/digest convention, not authentication (the Toolbox has no login) — see the tool's CLAUDE.md.

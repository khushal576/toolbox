# AI Access (`ai-access/`, package `ai_access`) — the owner's control panel for AI access

> **Start here:** repo rules `../CLAUDE.md` · the rules this page enforces: `../docs/architecture/ADR-MCP.md` D12 and `../mcp_server/CLAUDE.md` · where things live: `./KNOWLEDGE_MAP.md`.

## What it is
A Toolbox tool (runtime `data`, 🤖 in the sidebar) where the OWNER controls what an AI assistant (via `mcp_server/`) may do: a big **Stop AI access now** button, the **owner PIN**, time-limited
**permissions to change things** (grants), and a live **timeline of everything the AI did** (the MCP audit log). The logic is in `../mcp_server/control.py` and `audit.py`; this folder is only the HTTP + page layer.

## Rules (tested in `tests/unit/test_ai_access_server.py` and `test_mcp_control.py`)
- **Stop and Revoke need no PIN** (anyone may hit the brakes). **Granting, resuming and changing the PIN need the PIN.** 5 wrong PINs lock it for 15 minutes.
- The target's **environment comes from the Vault** (`access.target_environment` / the scoped vault here), never from the browser's request. Prod and unlabelled targets need an explicit confirmation tick.
- Nothing secret is returned: only connection / server / workspace NAMES and their labels. A database outage reads as "stopped" (503), never as "allowed".
- The AI can reach none of this: no MCP tool creates, extends or revokes a grant, sets the PIN or resumes (a test scans `mcp_server/tools.py`).
- **Known limit (ADR-MCP §6):** every Toolbox route is unauthenticated and the CLI is a local command, so an AI client that ALSO has a shell on this machine could call them. The PIN is what stops it from
  granting itself rights; it could still press "Stop" (harmless) or read this page. Keep shell commands on manual approval in such a client, or use a client without a shell.

## Where things are
`server.py` (endpoints: `GET /status`, `GET /calls`, `POST /kill`, `/resume`, `/pin`, `/grants`, `/grants/{id}/revoke`), `ui/index.html` (single page, all dynamic text escaped — a hostile `<img onerror>` row was verified inert in headless Chromium),
`manifest.yaml` (`vault: {read: [postgres_connection, ssh_server], data: read}` only to list NAMES for the target dropdowns).

## Gotchas
- The page and the CLI share the same tables (Postgres schema `mcp_server`: `calls`, `control`, `grants`). The kill flag is read on EVERY MCP call, so a stop takes effect on the AI's next call (a query already running ends within its time limit: 30 s, 15 s on prod).
- Resuming is read-only: all grants were revoked when it was stopped; create new ones.
- Workspace grants may name a workspace that does not exist yet (for "create table in a new workspace").
- Tests need no server: `python3 -m pytest tests/unit/test_ai_access_server.py tests/unit/test_mcp_control.py -q`.

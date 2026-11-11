# ai-bridge — the AI helper bridge (host service)

> Design: `../docs/architecture/ADR-AI-HELPER.md` (D1–D4, "As built in H1"). Owner how-to: `../docs/runbook.md` → "Set up the AI helper". Gateway side: `../core_plugins/helper.py`.

Runs on the **host**, not in Docker (it uses the owner's `claude` Pro login; the login is never copied into a container). Standard library only.
- `engine.py` — `Engine` interface + `ClaudeCodeEngine` (runs `claude -p … stream-json`, turns it into events start/text/tool/warning/done/error with plain-words messages). Add other AIs here (H6).
- `bridge.py` — tiny HTTP service: `GET /status`, `POST /ask` (SSE), `GET /chats`, `GET /chats/{id}/messages?before=&limit=`, `DELETE /chats/{id}`, `GET|PUT /policy`. Header `X-Helper-Token`; one question at a time; binds 127.0.0.1 + the docker0 address (retries until Docker is up).
- `store.py` — the helper's own **chat log** (SQLite `~/.config/toolbox-helper/chats.db`, 0600): chats + messages (user / assistant / tool / system), paged (newest 30, older on request), pruned at 300 chats, text capped. For DISPLAY only — Claude's memory is its own session. The bridge records while streaming (`Recorder`), even if the browser disconnects.
- `policies/<tool>.md` — one policy PER TOOL (starting texts for df-studio / sql-studio, a template for the rest), appended after the general policy only when that tool is open; names validated (`[a-z0-9_-]`, ≤ 41). `reviews` table in `chats.db`: the owner's 👍 / 👎 + note per answer (latest wins); a 👎 note becomes a rule in the tool's policy only by the owner's click (**the AI never writes a policy**).
- `policy.md` (same folder) — the owner's editable preferences, read at EVERY question (≤ 4,000 chars) and appended under the fixed `SYSTEM_CARD`. Style/habits only; safety is enforced in code, so a policy cannot relax it. Endpoints `GET/PUT /policy`; panel ⚙️.
- `install.py` — `install [--write-env]` / `status` / `uninstall [--purge]`; systemd **user** unit `toolbox-helper.service`; config in `~/.config/toolbox-helper/`.

## Rules (tested in `../tests/unit/test_ai_bridge.py` — do not weaken)
1. The child gets `--tools ""` (no Bash / Edit / Write / Read / web), `--strict-mcp-config` (only the Toolbox MCP server; the account's cloud connectors stay out), `--allowedTools mcp__toolbox`. Never `--bare` (needs an API key), never any skip-permissions flag.
2. `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Bedrock/Vertex switches are REMOVED from the child's environment: it can only use the subscription (never an API bill). `status` warns if the login is not claude.ai.
3. The question goes on **stdin**, never as an argument. Thread ids must be UUIDs. Message ≤ 8,000 chars, context ≤ 4,000.
4. Neutral working directory (`~/.config/toolbox-helper/workdir`): no project `CLAUDE.md` is read; own short system prompt (`SYSTEM_CARD`).
5. Child runs in its own process group and is killed on timeout (240 s), cancel or browser disconnect.
6. Error text goes through `scrub()`; the chat log holds the question and the answer text only (never tool inputs or results), on this computer, private file. The bridge's stderr never prints questions.
7. Never listen on the LAN. Toolbox must stay on localhost (no login; the subscription is the owner's alone).

## Gotchas
- A host firewall (ufw) blocks containers from reaching the host: one rule is needed (`sudo ufw allow from 172.16.0.0/12 to any port 8787 proto tcp`) — printed by `install.py`.
- Helper conversations appear in Claude Code's resume list for the neutral folder.
- "Not logged in" / "limit" detection from error text is pattern-based (tested with fakes; the limit also uses Claude Code's `rate_limit_event`).
- Don't `pkill -f bridge.py` from a shell whose own command line contains that text.

<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ./CLAUDE.md and ../docs/architecture/ADR-MCP.md -->

## Tool: AI Access — mounted at `/tools/ai-access/`

| If you need to change... | Go to |
|---|---|
| The page (banner, stop button, PIN card, grant form, countdowns, timeline, filters) | `ui/index.html` (one file; every dynamic value goes through `esc()`) |
| What the page can ask the server (status, calls, kill, resume, pin, grants, revoke) | `server.py` |
| The rules: kill switch, PIN hashing + lockout, grant vocabulary (`ACTIONS`), max minutes, what `require()` refuses | `../mcp_server/control.py` |
| What is logged about each AI call | `../mcp_server/audit.py` (table `calls`) |
| Which targets appear in the dropdowns | `server.py` `_targets()` (Vault connection / SSH server names + labels; Vault Data workspaces) |
| Owner commands without the page | `../mcp_server/__main__.py` (`status`, `kill`, `resume`, `set-pin`, `grants`, `revoke`, `grant`) |
| Tests | `tests/unit/test_ai_access_server.py`, `tests/unit/test_mcp_control.py` |

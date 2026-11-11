<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ./CLAUDE.md and ../docs/architecture/ADR-MCP.md -->

## Package: mcp_server — started with `python -m mcp_server` (stdio MCP server for AI clients; not mounted on the web)

| If you need to change... | Go to |
|---|---|
| What the AI can call, a tool's description / arguments / result | `tools.py` (`REGISTRY`, one function per tool) |
| The protocol: handshake, tools/list, tools/call, batches, the audit-before-run order, "never crash" handling | `protocol.py` (`handle`, `call_tool`, `serve`) |
| What may be shown to the AI: redaction, secret keys, exact JSON values, row/byte caps, limits per environment, the response envelope | `safety.py` (`Redactor`, `jsonable`, `clip_rows`, `Limits`, `finish`) |
| Using a Vault connection by name, which fields are visible | `access.py` (`resolve_connection`, `public_connection`, `PUBLIC_CONNECTION_FIELDS`) |
| SELECT over Vault Data (guard, mounting, timeout) | `lake_sql.py` (uses `data-lake/query.py` `analyse`) |
| SELECT over a Postgres connection (guard + read-only session + cap) | `pg_readonly.py` (uses `sql-studio/query_guard.py`) |
| How rows become an INSERT script (literals per dialect, quoting, batching, what is refused) | `scriptgen.py` (pure: `literal`, `build_script`, `target_name`); the tool wrapper is `tools.py` `generate_insert_script` |
| Which SSH commands the AI may run, the flag allow-lists, secret-file refusal, output scrubbing | `sshcmd.py` (`validate`, `SPECS`, `scrub_output`) |
| Running the validated command on a server (pinned key, pty, limits) | `ssh_run.py`; the tools are `tools.py` `ssh_servers` / `ssh_run`; server lookup `access.py` `resolve_ssh_server` |
| The DataFrame Studio tools: loading a table, applying the page's steps, the catalog, describing results, the plan digest, the ONLY Vault Data write | `frame.py` (`load`, `apply_steps`, `catalog`, `describe`, `plan_digest`, `write_result`); tools `tools.py` `transform_steps` / `table_transform`; confirm codes `control.py` `issue_confirmation` / `consume_confirmation` |
| Searching and running "what Toolbox can do" (index, ranking, describe, manifest actions over HTTP, `mcp.*` actions) | `registry.py` (`load`, `find`, `describe`, `run_manifest_action`, `http_get`); the verbs are in `tools.py`; manifest side `core_plugins/manifest.py` (`AiAction`) + `core_plugins/ai.py` (input checks, address building) |
| Kill switch, owner PIN, grants, what `require()` refuses, the action vocabulary | `control.py` (`kill`, `resume`, `set_pin`, `create_grant`, `require`, `ACTIONS`) — page: `../ai-access/` |
| Owner commands (stop / resume / PIN / grant / revoke) | `__main__.py` `_owner_command` |
| The audit log table, retention, the owner's view | `audit.py`, `__main__.py recent` |
| What the MCP identity may do in the Vault | `vault_scope.yaml` → `core/vault.py` `scope_for` / `_scope_from_file` |
| prod / non-prod label (storage, UI, endpoints) | `core/vault.py` (`environment_of`, `environments`, `set_environment`), `vault/server.py` (`/environments`, `/secrets/{id}/environment`), `vault/ui/index.html` |
| Limits (env vars) | `safety.Limits` — `MCP_ROWS`, `MCP_MAX_ROWS`, `MCP_PROD_ROWS`, `MCP_PROD_MAX_ROWS`, `MCP_MAX_BYTES`, `MCP_SECONDS`, `MCP_PROD_SECONDS`, `MCP_COMPARE_MAX_ROWS`, `MCP_PROD_COMPARE_MAX_ROWS`, `MCP_SCRIPT_MAX_ROWS`, `MCP_PROD_SCRIPT_MAX_ROWS` |
| Tests | `tests/unit/test_mcp_server.py` (canary-secret, SELECT-only, limits, protocol, audit), `tests/unit/test_mcp_scriptgen.py` (script golden tests, purity, partial-result refusal), `test_mcp_sshcmd.py` (command allow-list + stress), `test_mcp_ssh.py` (tool gates), `test_mcp_ssh_live.py` (real OpenSSH; set `MCP_SSH_TEST_HOST`), `test_mcp_registry.py` + `test_ai_manifest.py` (registry, manifest `ai:` rules, 1,000-tool scale), `test_mcp_frame.py` (steps, catalog drift guard, write-path scan; the second half needs DuckDB + the catalog → run in the image) |
| How to connect Claude | `docs/runbook.md` → "Connect Claude to Toolbox" |

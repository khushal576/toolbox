# mcp_server — Toolbox for AI clients (MCP over stdio)

> **Start here:** repo rules `../CLAUDE.md` · design and ALL the rules this package must keep: `../docs/architecture/ADR-MCP.md` (read it before
> changing anything here) · where things live: `./KNOWLEDGE_MAP.md` · status/gotchas: `../docs/roadmap/ROADMAP.md` Handoff log (sessions K2–K6).

## What it is
A small stdio server (newline-delimited JSON-RPC, hand-written — the official `mcp` package needs `uvicorn>=0.31`, the project pins 0.29) that lets an
AI client such as Claude call Toolbox instead of writing scripts. **Not a web tool** (no manifest, no mount, no port). Started by the client with
`docker compose -f <repo>/docker-compose.yml run --rm -T --no-deps worker python -m mcp_server` (0.9 s). Other commands: `python -m mcp_server recent [N]`
(the owner's audit view), `python -m mcp_server tools`.

## The rules (each one is tested in `tests/unit/test_mcp_server.py` — do not weaken a test to make a change pass)
1. **Read-only unless the owner grants otherwise.** Eleven tools. All are `readOnlyHint` EXCEPT `table_transform` (it can save a NEW table — only with an owner grant + a single-use confirm code, see rule 9). `generate_insert_script` only RETURNS text; `access_status` / `ssh_servers` / `transform_steps` only report; `ssh_run` runs read-only diagnostics, only inside an owner grant. No tool writes, deletes, grants, or reaches the Vault's write side (`vault_scope.yaml` has no `write:`).
2. **Credentials never leave the process.** The AI names a connection; `access.py` decrypts it server-side. Output goes through `safety.finish()`:
   secret-looking keys are replaced, every decrypted secret VALUE is scrubbed everywhere (also inside driver errors), usernames are scrubbed from
   messages (not from result data — a table may contain "postgres"). The canary test calls every tool with a driver that echoes the password.
3. **prod / non-prod labels.** `environment` lives inside the Vault entry; missing = `unknown` = treated as prod (tighter limits, warning in every result).
   Errors from a labelled connection carry the label too (`ToolError.connections`).
4. **SELECT only, twice.** Vault Data: `data-lake/query.analyse` (parse tree; only workspace tables; no file functions; CTAS refused). Postgres:
   `sql-studio/query_guard` classifies AND the session is read-only (`default_transaction_read_only`, `con.read_only`, statement timeout, server-side cursor).
   Verified against a Postgres user WITH write rights: `SELECT … INTO`, data-modifying CTEs, `nextval`, flipping read-write, `pg_sleep` all stopped.
5. **Exact numbers.** Decimal / big ints / dates are returned as TEXT with their SQL type; nothing is turned into a float.
6. **Limits are announced.** `truncated` + `limits_hit`; `compare` refuses a side over the cap instead of comparing part of it.
7. **Owner grants + brakes (K4, `control.py`).** Changing anything needs a GRANT: one target, listed actions (never delete/drop), expiry (default 30 min, max 8 h), created ONLY by the owner
   (AI Access page or CLI) with the owner PIN (scrypt-hashed; 5 wrong tries lock 15 min). The kill switch is checked on EVERY call, reads included, and fails closed. No MCP tool can create / extend a grant,
   set the PIN, resume or revoke — `tests/unit/test_mcp_control.py` scans for it. Any write-capable tool (K5/K6) MUST start with `control.require(kind, target, action, rows=…)`.
8. **SSH (K5, `sshcmd.py` + `ssh_run.py`).** `ssh_run` needs an owner grant `run_read_commands` for THAT server (off by default, expiring). Order is fixed and tested: allow-list check → grant → pinned-host-key connection →
   run with limits → scrub output. The allow-list is flag-by-flag per program (unknown flag = refused); quoted flags are judged by their text; the command SENT is REBUILT from validated tokens (`shlex.quote`), so
   the server's shell parses exactly what was checked; `git` gets `-c core.fsmonitor=false`, `journalctl/systemctl` get `--no-pager`. **Runs on a pseudo-terminal on purpose**: closing the channel then hangs the
   terminal up and the server kills the command (observed: without it a timed-out `head … | wc` kept running on the server). Cost: stdout+stderr merged. Write commands over SSH do NOT exist (refused outright).
   Secret files are refused by name (best effort) and output is scrubbed (PEM keys, `password=…`, bearer tokens, AWS keys, URL passwords) on top of the Redactor. Real-server test: `tests/unit/test_mcp_ssh_live.py`.
9. **DataFrame Studio tools (K6, `frame.py`).** `transform_steps` (catalog generated from the live handlers — a test fails if a documented parameter name drifts from the real one) and `table_transform`:
   the page's OWN steps (`df-studio/clean_steps.HANDLERS`, `formula.expression`) on a Vault Data table, loaded the way the page loads it (Parquet → pandas, decimals stay exact). **Preview by default** (the pandas code that
   ran, before/after counts, per-step trail, notes, sample). `save_as` = **dry-run** (needs the owner's grant on the target workspace; returns the plan + a single-use `confirm_code` bound to a digest of source table + VERSION + steps + target + mode,
   10 min) → the same call again with the code **writes** (grant re-checked, code consumed, source never touched, `replace` keeps the old table as `<name>_backup_<time>`, Parquet round-trip + catalog READ-BACK checked; a failed read-back is an error, never a success).
   `frame.write_result` is the ONLY code that writes Vault Data and `tools.table_transform` its only caller (an AST test enforces both, and the order require → issue → consume → write). The field is `confirm_code`, NOT `…token`: the redactor blanks any key containing "token"
   (this bug was found by the end-to-end test: the AI got `[redacted]`). Decimals: the page's own steps need numbers, so cast first — the tool warns when a cast to float/integer could round exact decimals.
10. **Audit first.** `audit.begin()` writes the row BEFORE the tool runs; if the log is down nothing runs. Postgres schema `mcp_server.calls`; no result data, no secrets.

## Tools (`tools.py`, `REGISTRY`)
`toolbox_guide` (map for the model) · `vault_list` (connections: name/type/host/database/environment; Vault Data tables) · `vault_dataset_preview` (≤ 500 rows) ·
`run_query` (Vault Data, or a saved PostgreSQL connection by name; SQL Server / Oracle are declined honestly) · `compare` (DataDiff via `core/clients/datadiff.py`; only
differing records unless `include_matches`) · `access_status` (what may I do right now; read-only) · `ssh_servers` / `ssh_run` (K5) · `transform_steps` / `table_transform` (K6) · `generate_insert_script` (K3: rows → INSERT script text for postgres / mssql / oracle; NEVER executes — `scriptgen.py` is pure, a test asserts it imports no driver and
`tools.py` holds none; a partial or inexact result is refused, never approximated). Descriptions are the AI's manual — keep them truthful and include an example.

## Gotchas
- Scope: `core.vault.scope_for("mcp-server")` reads `vault_scope.yaml` (no manifest exists); a broken file means NO access. `tests/unit/test_plugins.py::test_tools_never_use_the_unscoped_vault`
  scans this package: only `vault_store.scoped / ScopedVault / Scope` may be used (that is why `access.py` uses `v.SecretNotFound`, and `environment_of` is duplicated in `safety.py` —
  a test compares it with `core.vault.environment_of`).
- stdout is the protocol channel: `serve()` points `sys.stdout` at stderr; never `print()` to stdout elsewhere.
- Host unit tests skip the DuckDB / DB-library cases; run the full file in the image:
  `docker compose run --rm -T --no-deps -v "$PWD/mcp_server:/app/mcp_server:ro" -v "$PWD/tests:/app/tests:ro" worker sh -c "pip install -q pytest && cd /app && python -m pytest tests/unit/test_mcp_server.py -q"`.
- `data_lake.query` / `sql_studio.query_guard` are the image names of `data-lake/` and `sql-studio/`; the modules fall back to loading the files directly on the host.
- The audit table is created on first use (`SqlStore`). `AuditUnavailable` → the call is refused, not silently run.

## Not built yet (ADR): write commands over SSH (must use `control.require` and the D7 dry-run + confirm-code flow), `load_file` into Vault Data, writes to databases (`insert_rows` / `update_rows` exist in the grant vocabulary but no tool uses them).
## Owner CLI (never through MCP): `python -m mcp_server status | kill | resume | set-pin | grants [--all] | revoke <id> | grant <kind> <target> --actions a,b [--minutes N] [--rows N]` (PIN asked on the terminal).

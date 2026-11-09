# ADR-MCP — an MCP server so an AI can call Toolbox instead of writing scripts

- **Status:** **APPROVED by the owner on 2026-11-10**, with the amendments in D12–D15 (credentials, owner-only write grants, SSH for debugging,
  accuracy, priorities). Questions 1–3 of §4 are answered "yes"; question 4 (first write tool) is still open. **K2 built 2026-11-10** (see "As built in K2" at the end).
- **Owner's goal (2026-11-10):** "AI should not have to write conversion scripts etc. — it just calls our tool and the tool maintains
  everything; AI only thinks and decides." Today an AI session has to learn the codebase and improvise glue code each time.
- **Not in scope:** any code. This file only fixes the rules and the design that K2/K3 (and later sessions) must follow.

## 1. What it is

A small Python package **`mcp_server/`** that speaks the Model Context Protocol and exposes a **short list of task-level tools**
(load, preview, query, compare, convert, generate script …). Each tool calls code Toolbox already has: `core/lake.py` (Vault Data),
`core/vault.py` scoped access, `data-lake/` (loader, query guard), `orchestrator/` + `core/clients/datadiff.py` (compare),
`sql-studio/query_guard.py` (SQL classification). It adds **no new engine** — only a safe, well-described front door.
(Rule from root `CLAUDE.md`: do not write a 4th connector; reuse `core/`.)

## 2. Decisions

### D1 — Where it runs: a stdio process in a one-off worker container (recommended)
`docker compose run --rm -T worker python -m mcp_server` — the MCP client (Claude) starts it and talks over stdin/stdout.
- **Why:** no new always-on container (roadmap rule), **no network port**, no gateway route, nothing to authenticate over a network.
  The worker image already has every library and the same Postgres/Redis/S3/Vault-key settings as the jobs.
- **Why `run --rm` and not `exec`:** the autoscaler stops idle workers; an `exec` session is not a job and could be cut off. A one-off
  container is ignored by the autoscaler (`core_plugins/dockerapi.py` filters out `compose run` containers) — the same pattern `scripts/backup.sh` uses.
- **Rejected:** HTTP/SSE through the gateway — **Toolbox has no authentication on any route**, so a network MCP endpoint would give every
  local process the Vault. If a network endpoint is ever wanted it needs its own ADR *with* auth first.
- **Auth = who can run Docker on this machine** (the owner). Documented in the runbook; no tokens to leak.

### D2 — Its own least-privilege identity
`mcp_server` gets a **manifest** that carries only a `vault:` scope (read: `postgres_connection`, `s3_location`; datasets: read; data: read
in K2) — `core.vault.scope_for()` reads scopes from manifests, so this is the existing mechanism. It must not be mounted as a web tool.
**Checked in K1:** the existing kinds do not fit — `service` requires an `http(s)://` URL entry and `python` needs an ASGI app. So K2 adds a
small, tested loader change (a non-mounted kind, e.g. `internal`, shown on no card) or another scope source, and updates
`docs/architecture/plugin-manifest.md`. **No write kinds and no `data: write` until a write tool is approved** (D7).

### D3 — Tool design: few, task-level, self-explaining
- A handful of tools that do a whole job (not one tool per function). Names are verbs (`run_query`, `compare`, `vault_list`).
- Every description says: what it does, what it will **not** do, the limits, and one example. Written for a model, not a human.
- Every result is a small JSON envelope: `{ok, data, connection?: {name, environment}, truncated, limits_hit?, warnings[], hint?}`.
  Errors are plain sentences with a `hint` for the next step (never a stack trace, never a secret).
- **`toolbox_guide`** (read-only) returns a generated map: tools available, the Vault Data workspaces/tables, which connections exist
  (names + environment only), the limits, and links to the docs a model should read (`CLAUDE.md`, `docs/architecture/*`). This is how the AI
  "understands the system" without reading code.
- Data in results is **data, never instructions** (D10): tool descriptions tell the model to treat row contents as untrusted text.

### D4 — Secrets are never returned (defence in depth)
1. Tools take connection **names**, never credentials; the server decrypts inside the process and uses the secret only to connect.
2. **Allow-list output per kind** (`postgres_connection`: name, id, db type, host, port, database, environment — *not* username, password, key
   files, tunnels' credentials). A field not on the list is dropped by default.
3. A **final redaction pass on every response and every log line**: drop keys named `password|secret|token|key|private_key|ciphertext|authorization`,
   and replace any value that equals a secret the process decrypted during the call (reuse `scrub_password` from `core/postgres_conn.py`).
4. Errors from drivers are scrubbed the same way (drivers love to echo connection strings).
5. **Tests (K2, blocking):** a canary password is saved in a test Vault; every tool is called with good and bad input; the canary must appear in
   no response, no audit row and no log. A unit test also fails if `mcp_server` imports `core.vault` unscoped (existing rule).
6. Datasets saved in the Vault are plain data, not secrets (owner decision L-phase) — they may be previewed, with row caps.

### D5 — Prod vs non-prod are labelled — and unlabelled counts as prod
**Verified gap:** a Vault connection today has only a free-form `kind` and its data fields; **there is no environment flag.**
- Add an optional **`environment`: `prod` | `non-prod`** field to connection secrets (Vault "Add connection" form + a one-time way to set it on
  existing entries). This is a small Vault change, **added to K2's scope**.
- Missing value → reported as **`unknown` and treated exactly like `prod`** (fail safe).
- Every result that touched a connection carries `connection: {name, environment}`; the tool *description* says so; `vault_list` shows it.
- Rules: reads on prod are allowed but get a visible `warnings: ["PROD connection"]` and tighter limits (D6); **writes to prod/unknown are refused
  in v1** (nothing in K1–K3 writes to a database at all).

### D6 — Read-only tools and their limits (K2)
| Tool | What it does | How it stays read-only |
|---|---|---|
| `toolbox_guide` | the map described in D3 | reads manifests + catalog names only |
| `vault_list` | connections (allow-listed fields + environment), Vault Data workspaces/tables (columns, rows, size), datasets | scoped list; no decrypt returned |
| `vault_dataset_preview` | first N rows of a Vault Data table or dataset, with column types | `core/lake.preview` / `preview_dataset_as_csv`; row + byte caps |
| `run_query` | `SELECT` over **Vault Data tables** (DuckDB) **or** over a **Vault connection** (Postgres/SQL Server/Oracle) | tables: reuse `data-lake/query.analyse` (parse-tree check, only the named tables mounted, no file functions). Database: `sql-studio/query_guard.classify` must say SELECT-only **and** the session is opened read-only (Postgres `default_transaction_read_only`) — both, not either |
| `compare` | two sources (table, dataset, query on a connection, file) → DataDiff result summary + first differences | `orchestrator/recipes/compare.py` via `core/clients/datadiff.py`; read-only sources only |

**Default limits** (tunable by env, shown in every tool description): 200 rows per call (max 5,000), 1 MB of response text, 30 s per call,
5 concurrent calls; on a `prod`/`unknown` connection: 100 rows, 15 s. Anything cut off sets `truncated: true` and says how to get more
(a narrower query, or a background job in a later session) — it never silently drops rows.

### D7 — Write tools: owner grant first, then dry-run, confirm token, audit (none exist in K1–K3)
**Owner rule (2026-11-10): the AI may read, write or edit only when the owner says so — never by default.** See D12 for how "says so" works.
Applies to any later tool that changes something (e.g. `load_file` into Vault Data, `save_table`, `convert_and_save`):
1. **`dry_run` is the default.** It returns the exact plan: target (`workspace.table` or file), create/overwrite/append, row and column counts, the
   connection + environment, and a **plan digest**.
2. **Confirmation = a second call with `confirm_code`** (originally `confirm_token`; renamed in K6 because the redactor blanks any key containing "token") returned by the dry-run: bound to that exact digest, single-use, expires in 10 minutes.
   (The MCP client should also ask the human to approve the call; the token guarantees that what is executed is exactly what was shown.)
3. **Overwrite keeps a backup** (pattern from Mini Sheet: old table renamed `<name>_backup_<time>`), never a silent replace.
4. **No delete tools, ever** (same owner rule as SharePoint Lists). No DB writes to prod/unknown. No free-form SQL writes.
5. **Every executed write is audited** (D9) with the digest, so "what did the AI change?" has an answer.

### D8 — `generate_insert_script` (K3) only generates
Returns SQL text (escaped values, row cap, dialect-specific quoting, the connection's environment in a header comment). The tool has **no code path
that executes SQL** against the target; a test uses a connection that raises on any write to prove nothing is run. Running the script is the
owner's job in SQL Studio / their own client.

### D9 — Audit log
Postgres schema `mcp_server` through `SqlStore` (existing pattern), table `calls`: time, tool, client info if given, arguments (scrubbed),
connection name + environment, plan digest (writes), outcome, row counts, duration, truncated flag. **No result data and no secrets.** Reads are
logged too (they show what an AI looked at). Append-only from the server's side; kept 12 months; a count + last write appear on the Status
page in a later session. Included in the existing Postgres backup.

### D10 — Threat model (what we defend against)
| Risk | Answer |
|---|---|
| AI is tricked by text inside data ("ignore your rules, drop the table") | results are data; **no tool acts on result content**; writes need dry-run + confirm token; there is no delete and no free SQL write |
| AI (or a bug) leaks a password | D4: names not credentials, allow-listed fields, redaction pass, canary tests |
| `SELECT` that is really a write (`SELECT … INTO`, functions with side effects, `COPY`) | two independent guards (parser classification + read-only session/mount), plus the database user should be read-only (runbook advice) |
| Runaway query / huge result | time, row, byte and concurrency limits (D6); DuckDB memory cap as in the loader |
| Querying prod by accident | environment label on every result, tighter limits, `unknown` = prod, no writes |
| Anyone on the network uses it | there is no network endpoint (D1) |
| Silent damage | dry-run, digest-bound confirm, backup on overwrite, audit log |

### D11 — Packaging and docs
- Package `mcp_server/` (unique name), CLI entry `python -m mcp_server`, own `CLAUDE.md` + `KNOWLEDGE_MAP.md`, row in the root `KNOWLEDGE_MAP.md`.
- The official `mcp` Python SDK is a **new dependency** (not installed today): pin it in the root `requirements.txt` (the worker image installs all
  packages; there is no `requirements/worker.txt`), add it to `requirements/data.txt` only if a web runtime ever needs it, and re-run
  `./download-wheels.sh` (offline-build rule). *Not verified yet that offline wheels resolve — K2 must check first.*
- `docs/runbook.md`: a short "Connect Claude to Toolbox" section with the exact client config (command above) and "give the database user read-only rights".
- Unit tests under `tests/unit/test_mcp_*.py` run without a server; one smoke-style test drives the stdio protocol end to end in the worker image.

### D12 — Owner grants: write/edit is OFF until the owner turns it on (owner decision, 2026-11-10)
- Default for **every** connection, SSH server and Vault Data workspace is **read-only for the AI**. Write/edit/execute tools do not run — they answer
  "writes are off for `<name>`; the owner can turn them on in Toolbox → AI access".
- A **grant** is created only by the owner, **outside the AI channel**: a panel in Toolbox (K4) or a CLI the owner runs
  (`docker compose run --rm worker python -m mcp_server grant …`). **The MCP server has no tool that creates, widens or extends a grant** — an AI
  cannot give itself permission, and a prompt-injected AI cannot either.
- A grant names the target (one connection / server / workspace), the allowed actions (e.g. `insert`, `update`, `create_table`; never `delete`),
  an **expiry** (default 30 minutes, max 8 hours) and optionally a row limit. Grants live in Postgres (`mcp_server.grants`), are checked on every call,
  and show in the audit log. A **"Stop AI access" kill switch** (Redis flag + UI button) cancels all grants and blocks every MCP call immediately.
- A grant never overrides the other rules: prod/unknown connections stay write-protected unless the owner names that connection explicitly in the grant,
  and dry-run + confirm token (D7) still apply inside a grant.
- **The AI can never read, list in full, create, edit or delete Vault secrets.** `mcp_server`'s scope has no `write:` kinds, ever; a connection can
  only be *used by name* (D4). Same for SSH keys and passwords.

### D13 — SSH for debugging (session K5): off by default, read-only commands, everything tracked
Builds on `ssh-sftp` (Vault `ssh_server`, **pinned host keys**, `core/ssh_client.open_client`, `read_only` flag, `engine.DANGEROUS`).
- **Per-server AI switch**, default **off**. The owner turns it on per server (K4 panel), choosing `read-only commands` or, with a grant (D12), `read+write`.
  Servers get an `environment` label like connections (D5); unlabelled = prod.
- `ssh_run(server, command)` runs **one non-interactive command** (never the live terminal) with its own connection, 30 s timeout, 64 KB output cap.
  **Read-only mode = a command allow-list**, parsed with `shlex` (not regex on a string): reading files and logs (`ls cat head tail grep stat wc du df find`
  without `-exec/-delete`), processes and resources (`ps top -b -n1 free uptime uname ss ip`), logs and services (`journalctl dmesg`, `systemctl status|is-active|list-units`),
  containers (`docker ps|logs|inspect|stats --no-stream`), `git status|log|diff|show`. Pipes only between allow-listed commands and only into `grep head tail wc sort uniq`.
  **No** redirects, `;`, `&&`, `||`, backticks, `$(…)`, `sudo`, editors, package managers, `rm`, `mv`, `cp`, `chmod`, `kill`, `docker exec/rm/run`, `systemctl start|stop|restart`.
  Anything else is **not executed** and the reply says why and what the owner can grant.
- Write commands only inside an owner grant (D12), one command at a time, with dry-run showing the exact command and the server's environment, plus the confirm token.
  `DANGEROUS` patterns stay blocked even with a grant.
- **Tracking ("what is happening, clearly")** — every call is an audit row: time, server + environment, exact command, exit code, duration, bytes, and a
  **scrubbed 2 KB output excerpt** (the owner can set it to 0). Calls are grouped into an **AI session** with a start/end and a readable timeline.
  The K4 "AI activity" page shows the live timeline (auto-refresh), filters by tool/connection/server, and has the kill switch.
- Credentials: the AI never sees the key/password; it only names a server. Output is scrubbed for secrets before it is returned or stored (D4.3).

### D14 — Accuracy first (the purpose is speed *with* high accuracy)
- **Do the work in the tool, not in the model's head.** Counting, comparing, converting, type handling and SQL execution are done by deterministic Toolbox
  code; the AI only chooses tools and reads evidence. No tool asks the model to compute a number it could have been given.
- **Every result carries evidence:** row counts (in/out), column names + SQL types, a content digest where useful, `truncated`, and for writes a
  **read-back check** (the server re-reads what it wrote and compares counts/digest to the plan; a mismatch is reported as failure, never as success).
- **Types survive:** values travel tagged (as DataDiff already does for Decimal/date/UUID/bytes) so a number is never silently turned into text or a float.
- **Fail loudly, not partially:** errors are explicit; limits set `truncated: true`; a half-finished action is reported with exactly what happened.
- Each tool ships with **golden-data tests** (known input → exact expected output) and, for anything that changes data, a before/after `compare` in the test.

### D15 — Priority follows what the owner actually uses (2026-11-10)
The owner uses **SQL Studio, DataFrame Studio and DataDiff** most, and wants **SSH-based server debugging** with full tracking; every non-"learn" tool has
a reason to exist. Learn tools (cookie-lab, header-reference, http-methods-status, packet-journey, vlan-designer, subnet-calc, dns-lookup) are **not exposed**.
Order: **K2** read tools built on SQL Studio's guards and DataDiff (`run_query`, `compare`, previews) → **K3** `generate_insert_script` → **K4** grants + AI
activity page + kill switch → **K5** SSH debugging tools → **K6** DataFrame Studio tools (apply cleaning steps/formulas to a table with a dry-run
preview, save the result as a table with lineage) → then the owner's next pick (§4 q4: `load_file` recommended).

## 3. Consequences for the roadmap sessions
- **K2 (M)** gains: the `environment` field in the Vault, the non-mounted manifest kind for the scope (D2), the SDK pin + wheels, the `mcp_server` audit table, and the canary test. Its tools are exactly D6.
- **K3 (S)** = D8 only.
- **New sessions from the amendments:** **K4** grants + AI activity page + kill switch (D12/D13 tracking), **K5** SSH debugging tools (D13),
  **K6** DataFrame Studio tools (D15). Added to the roadmap.
- **After K3 (not yet planned — owner to prioritise, see the list below):** `load_file` (Vault Data loader with column map + mask), `convert_and_save`,
  `stage_db_table` (read-only source → Vault Data), `clean` steps from DataFrame Studio. All must follow D7.

## 4. What the owner needs to decide (recommendation first)
1. ~~Approve D1~~ — **approved 2026-11-10.**
2. ~~Approve D5~~ — **approved 2026-11-10.**
3. ~~Limits in D6~~ — **approved 2026-11-10** (tunable later).
4. **Which write tool comes first after K3?** *(still open)* *Recommended: `load_file` into Vault Data (it replaces the most "write a conversion script" work and is
   the safest write: it only adds a Vault Data table, with dry-run + backup).*
5. ~~The jobs you repeat most~~ — **answered:** SQL Studio, DataFrame Studio, DataDiff, and SSH debugging (D15). More jobs can still be added any time.

## 5. Not verified in K1 (to be checked in K2)
- Which loader change is smallest for a non-mounted, scope-only manifest (see D2) and that `scope_for()` then finds it.
- That the `mcp` SDK installs offline from the wheelhouse and runs on the worker's Python (3.11).
- That `docker compose run --rm -T worker …` starts fast enough (a few seconds) for an MCP client's connect timeout.

## 6. As built in K2 (2026-11-10) — where the code differs from the plan above

- **No `mcp` SDK dependency (D11 changed).** Both `mcp` 1.x and 2.x require `uvicorn>=0.31`; the project pins `uvicorn==0.29.0` for every image, so installing it
  fails (`pip` `ResolutionImpossible`, checked). `mcp_server/protocol.py` implements the small stdio JSON-RPC surface by hand (initialize, ping, tools/list, tools/call).
  It was checked against the **official client** (mcp 2.3.0, in a scratch venv only): handshake negotiates 2025-11-25, tools and read-only annotations listed, calls and errors
  returned correctly — including through the real `docker compose run` command. If the uvicorn pin is ever raised, switching to the SDK is possible; the tools do not change.
- **Scope without a new manifest kind (D2 changed).** `mcp_server/vault_scope.yaml` (same schema as a manifest's `vault:`), read by `core.vault.scope_for` when no manifest has that
  name; an invalid file grants nothing. No loader/UI change. Identity: `read: [postgres_connection, s3_location]`, `datasets: read`, `data: read`, no `write:`.
- **Verified (was "not verified" in §5):** startup of the exact client command takes **0.9 s** from any directory (`docker compose -f <repo>/docker-compose.yml run --rm -T --no-deps worker python -m mcp_server`).
- **Environment label (D5) is built:** stored inside the entry, Vault page dropdown + badge/selector, `GET /environments`, `POST /secrets/{id}/environment`; unlabelled = `unknown` = prod rules.
- **Usernames** are scrubbed from messages (a real Postgres error echoes them) but not from result data (a table may contain "postgres") — found by the canary test.
- **Postgres only** for `run_query` on connections in K2 (SQL Server / Oracle answer "supported in SQL Studio; stage into Vault Data"). The shared dialect layer is async-pool based; a one-shot read-only
  path for those engines is future work (not verified against real SQL Server/Oracle).
- **Result:** 68 tests (`tests/unit/test_mcp_server.py`), the nastiest read-looking statements run against a Postgres user WITH write rights (all stopped, database unchanged), and a canary
  password/username/private-key that appears in no response, audit row or log.
- **Still true / not yet built:** D7 owner grants (K4), SSH (K5), DataFrame Studio tools (K6), `generate_insert_script` (K3).

### K3 as built (2026-11-10) — D8
`generate_insert_script` (`scriptgen.py` + a thin tool). **Structural, not promised:** `scriptgen` imports only the standard library (asserted by AST in a test) and the tool module holds no driver;
the only database call is the read-only source read. Postgres / SQL Server / Oracle literals per type, injection text stays inside its string, NUL / NaN (non-Postgres) / intervals (non-Postgres) /
TIME (Oracle) are refused rather than approximated, partial sources and oversized scripts are refused, prod / unlabelled sources get a WARNING header and the smaller row cap.
**Verified end to end on PostgreSQL:** 600 rows with awkward values (20-digit decimal, bigint extremes, backslash vs newline, µs timestamps with zones, bytea, uuid, jsonb, emoji, empty strings, NULLs, an injection string)
generated through the real driver, run into an empty copy, `EXCEPT` both ways = 0 rows. **Not verified against real SQL Server / Oracle.**

### K4 as built (2026-11-10) — D12, D9
- **Kill switch** (`control.kill`): one flag in `mcp_server.control`, checked before EVERY call (reads included), fail-closed if unreadable; revokes all grants; no PIN to stop. Takes effect on the AI's next call
  (verified live: a connected session was refused on its very next request); a query already running ends within its time limit.
- **Grants** (`mcp_server.grants`): target (connection | ssh_server | workspace) + actions from a fixed vocabulary (`create_table`, `append_rows`, `replace_table`, `insert_rows`, `update_rows`, `run_write_commands` —
  no delete/drop, asserted) + expiry (≤ 8 h) + optional row limit. Prod / unlabelled targets need an explicit confirmation; the label is read from the Vault, not from the request. Write tools must call `control.require`.
- **PIN (added beyond the first draft of D12):** without it, an AI client that also has a shell could run the CLI or `curl` the page and grant itself rights. scrypt hash, 5 tries then 15 min lock, needed for grant / resume /
  PIN change; never for stop or revoke. Set it yourself right after setup — whoever sets it first owns it.
- **Page** `ai-access/` (🤖 AI Access): stop button, PIN, grant form with countdowns, live timeline (filters, expandable exact query/command, session colours, prod badges). Verified in headless Chromium incl. a hostile
  `<img onerror>` audit row (rendered as text, nothing injected). **CLI:** `python -m mcp_server status|kill|resume|set-pin|grants|revoke|grant`.
- **AI-facing:** `access_status` (what am I allowed to do) — read-only; the AI is told to ask the owner for a grant and cannot create one (a test scans `tools.py`; no tool name or schema mentions pin/grant/expiry).
- **Known limit (be honest with yourself):** Toolbox has no login, so anything running as you on this machine can open the page or run the CLI. The PIN stops an AI from granting itself rights, but a shell-capable AI client
  could still read the audit page, press Stop, or try PIN guesses (5 tries, then 15 min lock). If you use such a client, keep its shell on manual approval for `docker`/`curl`, or use a client without a shell.

### K5 as built (2026-11-10) — D13
- **Per-server switch = a time-limited grant** (`run_read_commands`, ≤ 8 h): SSH is powerful even read-only (logs hold secrets), so "off by default" is the K4 grant, with the same page, PIN, expiry and kill switch.
  **Write commands over SSH are NOT built** (D7 needs the dry-run + confirm-token flow) and are refused outright; the vocabulary has no write action.
- **Allow-list per program and per flag** (`sshcmd.py`), own tokenizer, command REBUILT from validated tokens; `git`/`journalctl`/`systemctl` hardened as above. Verified: 265 allow/deny/stress tests (25 000 random commands: nothing
  a shell could misread was ever accepted), 14 tool-gate tests, and **10 live tests against a real OpenSSH server** (real output, pipes + wildcards on the server, host key pinned and a changed key refused, unpinned refused,
  attacks left no file on the server, output cap, time limit, no credential in any response or audit row).
- **Found by the live test:** closing an SSH `exec` channel does NOT stop the command on the server. Fix: run on a pseudo-terminal so the hangup kills it; the live tests now assert nothing is left running. (Merged stdout/stderr is the price.)
- **Limits you should know:** secret-file refusal is by name and best effort (a recursive `grep -r` can still reach a file whose name gives it away only by content) — hence the output scrubber, which is also best effort.
  `docker logs` and application logs can contain secrets nobody planned for. The grant is the real protection: only enable a server for the time you need it. Not tested on non-Linux servers or against non-OpenSSH daemons.

### K6 as built (2026-11-10) — D7, D14, D15
- **Tools:** `transform_steps` (catalog) and `table_transform`. The steps are DataFrame Studio's own (`clean_steps.HANDLERS`, `formula.expression`) — no second implementation (asserted: `frame.py` has no `exec`/`eval` and no copy of a handler).
- **First tool that WRITES, so the full D7 protocol is real:** preview (default, no grant) → dry-run (`save_as`; needs the owner's grant on the workspace; shows the plan; returns a single-use `confirm_code` bound to a digest of source table + version + steps + target + mode;
  10 min) → confirm (same call + code: grant re-checked, code consumed, write, `replace` keeps the old table as a backup, Parquet round-trip and catalog read-back verified). The source table is never touched. Kill switch / revoke between dry-run and confirm stop the write (tested).
- **Scope:** `vault_scope.yaml` now has `data: write` — used only by `frame.write_result`; an AST test asserts no other mcp_server code calls a Vault Data write function, and that `table_transform` orders require → issue → consume → write.
- **Found by the end-to-end test (not by unit tests):** (1) the response key `confirm_token` was blanked by the redactor, so the AI could never confirm → renamed `confirm_code`, regression test added; (2) the page's own `fill_nulls zero` refuses exact-decimal columns (they load as `Decimal` objects) —
  the AI must `cast_type` first, and the tool now warns when that cast could round exact values; (3) my catalog documented `replace_values.mapping` and `cast_type.on_error` wrongly — a drift-guard test now fails whenever a documented parameter differs from what the handler reads.
- **Limits:** 200 000 rows (`MCP_TRANSFORM_MAX_ROWS`), 30 steps, workspace grants only. Not built: appending to an existing table (`append_rows` is in the vocabulary, unused), `load_file`, writes to databases.


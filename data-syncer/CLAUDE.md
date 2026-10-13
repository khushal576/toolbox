# Data Syncer — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the symptom→file map across every tool. This is
the fast-orientation version scoped to this folder.

## What this tool is

Copy or upsert whole tables from one database to another, in resumable
key-ranged chunks, with progress saved after every chunk so a run can be
stopped or killed at any time and continue from where it was. The page
**never shows table data** — only per-table status/counts/position and the
last N log lines (default 100, set per project; older lines are dropped).

Two modes per project:

- **upsert** — new rows inserted, changed rows updated, identical rows left
  alone. Needs a key (one or more columns) and a unique index on exactly
  those columns in the target (checked in preflight; the syncer never
  creates indexes/tables).
- **copy** — raw bulk load, no row handling, no transformation. Target
  table must be empty (or the project's "truncate target first" is on). A
  key is optional and only buys resumability; without one the table is one
  all-or-nothing transaction that restarts from zero.

Connections are **never typed here** — every source/target is a Vault entry
(`kind: "postgres_connection"`, incl. its SSH tunnel). A project stores only
the Vault id (+ name, as a fallback if the entry is deleted and re-saved).

## The one idea that everything rests on

A *chunk* is a key range `(lower, upper]`, moved as raw bytes:
`COPY (SELECT … WHERE key in range) TO STDOUT` → `COPY … FROM STDIN`
(copy: into the real table; upsert: into a TEMP staging table, then one
`INSERT … ON CONFLICT DO UPDATE … WHERE … IS DISTINCT FROM`). Postgres's text
COPY round-trips every type exactly, Python never parses a value, memory per
chunk is a stream buffer regardless of batch size. The chunk's upper bound
comes from one cheap query (`… ORDER BY key OFFSET batch-1 LIMIT 1`).
**Ranges, not `LIMIT n`**, so rows sharing a key value can't be split across
batches and lost, and any chunk can be re-run exactly. Keys are stored and
compared as **text** and cast back (`%s::<column type>`), so int/uuid/
timestamp/text/composite keys all survive SQLite with no per-type code.

## Where things live

| Concern | File |
|---|---|
| Vault entry → live connection (SSH tunnel, reconnect, UTF8/keepalives pinned) | `connections.py` (`Endpoint`, `resolve`) |
| Everything database-specific (discovery, preflight, chunk bounds, COPY/upsert SQL) | `sync_ops.py` (`PostgresSyncOps`, `get_ops`) — add a class here for MSSQL/Oracle later; the engine doesn't change |
| The resumable loop, retries, stop, FK ordering, crash cleanup | `engine.py` (`run_project`, `sync_table`, `preflight_project`, `order_tables`) |
| Durable state: projects + per-table position/status (SQLite, `data_syncer_data` volume) | `state_store.py` |
| Background thread + in-memory log ring buffer | `runner.py` |
| API + page | `server.py`, `ui/index.html` |

## Things that will bite you if you don't know them

- **Steps "write chunk to target" and "save position" are in two different
  databases and cannot be atomic.** A crash between them leaves a chunk written
  but not recorded. Upsert doesn't care (rewrites the same rows). Copy would hit
  duplicate keys, so copy mode records `inflight {lower, upper}` BEFORE writing
  and, if it's still set on the next start (or after a failed attempt), deletes
  that **recorded** range from the target first — the recorded one, not a
  recomputed one (batch size or source may have changed). Don't "simplify" this
  into a plain re-copy. Verified by killing between commit and save.
- **`ORDER BY "id"` over `SELECT "id"::text`** sorts by the text OUTPUT column
  ('10' < '9'), giving chunks of arbitrary size. The boundary queries therefore
  alias their output columns (`AS _k0`). Found by a test, not by thought.
- **NULL keys are invisible to `key > x`** — those rows would be skipped
  silently. Preflight refuses a nullable key column that actually contains
  NULLs (a NOT NULL constraint skips the scan). It runs at table start/resume,
  so NULLs inserted into the source mid-run aren't caught.
- **Stop aborts the chunk mid-stream** (the target transaction rolls back) via
  a per-block stop check, so Stop is fast even with a 5M-row batch.
- **Retries are for transient failures only** (`RETRYABLE` in `engine.py`:
  connection/operational errors, deadlocks, timeouts). Constraint/data errors
  fail the table immediately; retrying repeats them. Retry reconnects both
  sides (the SSH tunnel is reused) and, in upsert mode, recreates the staging table.
- **Source is opened read-only** (`conn.read_only = True`) and never left in an
  open transaction between chunks.
- **Foreign keys / load order**: tables are loaded parents-first using the TARGET's
  FK graph (`engine.order_tables`, stable: your order is kept wherever there's no
  dependency). Verified: a 4-table chain + diamond listed child-first loads
  a → b → c → d in both modes. Only dependencies BETWEEN SELECTED tables are
  ordered — a parent that is not selected must already be populated in the
  target. A table referencing ITSELF works only if each parent arrives in the same
  or an earlier chunk (FK checks run at the end of each COPY statement, so within
  a chunk any order is fine); a forward reference across chunks, and a true cycle
  between tables, FAIL with the database's FK message (that table is marked failed,
  the others continue) — they need the target's constraints added AFTER the load
  (the two-phase split listed under "Not built" in `../schema-copy/CLAUDE.md`) or
  deferrable constraints. `TRUNCATE` is never `CASCADE`.
- **Auto-increment sequences are raised to the table's max id when a table
  finishes** (project option `fix_sequences`, default ON; `sync_ops.fix_sequences`).
  Covers serial/bigserial, identity (always/by default) and plain
  `DEFAULT nextval(...)` columns (found via `pg_depend`, so sequences with odd
  names, spaces in names, and several sequence columns per table work). The max is
  the TARGET table's max (target-only rows count). **Raise-only**: a sequence
  already at/above the max is left alone (lowering could reuse deleted ids); an
  empty table is untouched; non-integer columns are skipped; one bad sequence (e.g.
  no UPDATE privilege) is a warning, never a failed table. "Fix sequences now"
  (`POST /projects/{id}/fix-sequences`) applies the same rule to every finished
  table (for older syncs); it is idempotent. Databases created before the option
  existed get it ON via the migration in `state_store.init_db`.
- **A finished table is not re-run** by Start (status `done`); use Reset (the
  target isn't touched, so copy mode then needs an empty/truncated target).
  New source rows with keys *below* a saved position are never seen — it's a
  full pass, not change-tracking. Deletes in the source are not propagated.
- **Column and table names are never trimmed — they can contain spaces** (`"id "`,
  `" name"`, even `"spaced table "`). The UI keeps names exactly (key box, saved
  keys, displays show such names in quotes) and every identifier is quoted with
  `psycopg.sql.Identifier`. Because a name typed or pasted by hand easily loses
  its spaces (the original bug: the UI trimmed `"id "` to `id` and preflight said
  "Key column(s) not in source table: id"), `sync_ops.resolve_name()` matches the
  EXACT name first and otherwise the single column that differs only by
  leading/trailing spaces — so projects saved before the fix keep working with no
  edit. `plan_columns()` also maps SOURCE→TARGET columns the same way (a target
  built with trimmed names still works) and the engine reads with source names
  but writes/merges/cleans-up with target names (`plan["tkey"]`, `tcols`). Every
  loose match is a visible warning; several candidates = an error, never a guess.
  Names containing a comma can't be typed in the key box (comma-separated).
- **Generated columns are skipped**; identity columns are written
  (`OVERRIDING SYSTEM VALUE` for upsert; COPY accepts explicit values).
- **Source/target/mode can't change once a table has progress** (the saved
  positions would be meaningless) — Reset first. Editing the key of a table
  resets that table's progress.
- **In-process state, `--workers 1`**: the job registry + log buffer live in
  this process (`runner.py`), a fourth stateful tool in `../CLAUDE.md`'s
  standing rule. Durable state is SQLite; on process start,
  `recover_interrupted()` flips orphaned `running` tables to `interrupted`
  (Start resumes them — runs never auto-resume by design).

## Not built (decided, not forgotten)

Postgres → Postgres only (other engines: add a `sync_ops` class, `MERGE` for
upsert, a native bulk loader for copy); no table creation; no deletes; no
incremental/watermark sync; tables run one at a time; no data transformation —
a future Pandas Studio template step would sit between read and write, which
today are one byte stream, so that hook needs real design (decode the chunk
→ transform → re-encode), not a stub.

## Verified (real Postgres 16, throwaway containers)

200k/150k/50k-row tables incl. composite and uuid keys, jsonb, arrays, numeric,
bytea, identity + generated columns, no-key table; copy and upsert checksums
equal to source; crash between commit and state-save; graceful and mid-chunk
Stop; server-side killed connections (`pg_terminate_backend`) with retry;
misconfigured tables (missing column, NULL key, no unique index, duplicate
source keys, non-empty copy target, TRUNCATE blocked by FK); FK ordering; a
full `docker restart` mid-run then resume; the UI driven in headless Chrome.
Whitespace names: source columns `"id "`, `" name"`, `"val  "` and a table `"spaced table "` with a composite spaced key, in both modes, against a target with the same names and one with trimmed names, with the key given exact or trimmed (8 combinations), copy-mode crash recovery with differing names, an ambiguous name, and the UI in headless Chrome. Sequences: serial, bigserial, both identity kinds, a non-owned `nextval` default, a spaced column name, two serial columns in one table, target-only rows above the source max, an already-advanced sequence (not lowered), an empty table, a uuid table, option off, the manual button (idempotent), a plain INSERT afterwards in every table, the old-SQLite-file migration, and the UI. Load order: chain+diamond (both modes), self-reference both ways, a real cycle. Not tested: SSH-tunnelled connections, SQL Server/Oracle (unsupported).
Rough speed on a laptop container: copy ≈ 95k rows/s, upsert ≈ 60k rows/s.

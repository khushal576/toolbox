<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Duck Lab — mounted at `/tools/duck-lab/`

Load several CSV/JSON/Parquet/XML files, join/analyze them with SQL via
embedded DuckDB. The gap this fills: DataFrame Studio loads one file fully
into pandas memory; SQL Studio queries a live *Postgres* database, not
local files. CSV/JSON/Parquet are scanned straight off disk by DuckDB
(never read into Python); a query's result is materialized once inside
DuckDB and the UI pages through it with `LIMIT`/`OFFSET` — only one page
of rows is ever sent to the browser. Schema-aware SQL autocomplete (built
from the loaded tables) and a per-table row preview round out the editing
experience. See `duck-lab/CLAUDE.md` for the full picture.

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| Session state, DuckDB connection setup (memory/spill config), CSV/JSON/Parquet/XML loading, query materialization, pagination, export, table preview | `duck-lab/engine.py` |
| API endpoints (`/upload`, `/load/vault`, `/load/lake`, `/tables`, `/table/remove`, `/preview/{name}`, `/query`, `/page`, `/export`, `/export/vault`, `/export/lake`, `/session/reset`) | `duck-lab/server.py` |
| The frontend: upload/table list, "load from Vault" picker, preview panel, CodeMirror SQL editor + schema autocomplete, results table + pagination, query time | `duck-lab/ui/index.html` |
| Loading a saved Vault dataset in as a new table (the consumer side of `/export/vault`) | `duck-lab/server.py`'s `/load/vault` — decrypts via `core.vault.load_dataset_file()`, moves the result into the session's own `data_dir` (not a tempfile) since `engine.load_file()` builds a LAZY view backed by that path, then loads it exactly like an upload |

### Known non-obvious behavior (read before touching these areas)

- **Sessions are stored outside the process since roadmap B3**
  (`duck-lab/session_store.py`: table list + result in Redis, files and
  result Parquet in S3 storage; each worker rebuilds a local DuckDB copy on
  demand) — they survive restarts and work across worker processes.
- **CSV/JSON/Parquet never touch Python memory** — `read_csv_auto()`/
  `read_json_auto()`/`read_parquet()` point DuckDB directly at the saved
  file path. **XML is the one exception**: parsed once via
  `core.normalizer.normalize()` (same code DataDiff Pro uses) into a
  `pandas.DataFrame`, then `con.register()`ed into DuckDB — fully in
  Python memory, same ceiling DataDiff Pro's XML handling already has.
- **Schema autocomplete is reconfigured, not rebuilt, on every table
  change** — `ui/index.html`'s `sqlCompartment` (a CodeMirror
  `Compartment`, same technique as sql-studio's pasted-schema box) gets a
  fresh `sql({schema: ...})` via `refreshSchemaAutocomplete()` inside
  `refreshTables()`. A code path that mutates `STATE.tables` without going
  through `refreshTables()` will leave autocomplete stale.
- **`/preview/<name>` is unrelated to `/query`'s `_result`** — it reads
  the named source directly, independent of whatever query was last run.
- **`/load/vault` reuses `engine.load_file()` as-is** — the decrypted
  file gets a fresh UUID-prefixed name under the session's `data_dir`
  (same naming scheme `/upload` already uses), so the resulting table
  name is sanitized/de-duplicated the same way an upload's would be; it
  doesn't come back out named exactly what you typed in the "load from
  Vault" picker. Check `/tables`'s `name` field (not `source_file`) for
  what to actually type in SQL, same caveat as any upload.
- **A query result is a session-scoped DuckDB TEMP TABLE
  (`_result`), not a Python value.** `/query` materializes it once;
  `/page` just re-slices it with `LIMIT`/`OFFSET` — no recomputation of
  the join per page. `CREATE OR REPLACE` means only one `_result` exists
  per session at a time.
- **`PRAGMA memory_limit='512MB'` + a session-scoped `temp_directory`**
  are set on every connection at creation (`engine._new_connection()`) —
  this is what lets DuckDB spill a big materialized result to disk
  instead of the container OOMing, not just the pagination on top of it.
- **This is a THIRD stateful tool under `--workers 1`** (alongside
  df-studio and sql-studio) — see `../Dockerfile`'s CMD comment and
  `../CLAUDE.md`'s "Standing rule: stateful tools and `--workers`".
- **Copied as a whole folder in `../Dockerfile`**
  (`COPY duck-lab/ ./duck_lab/`), same reason as df-studio/sql-studio —
  extra backend module (`engine.py`) beyond `server.py`. Imports
  `core.normalizer` directly for XML, so it must be copied after `core/`.

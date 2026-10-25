# Duck Lab — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

Load several CSV/JSON/Parquet/XML files, then join and analyze them with
SQL (DuckDB, embedded — no separate database process). Built to cover a gap
neither existing data tool covers: DataFrame Studio loads one file fully
into a pandas DataFrame in memory; SQL Studio runs SQL against a live
*Postgres* database, not local files. This tool is SQL-first (like SQL
Studio) rather than a UI step-builder (like DataFrame Studio) — the
simplest way to support arbitrary joins/analysis across N loaded sources.

**The actual point of this tool**: never load a full result into
memory/the page. CSV/JSON sources are queried straight off disk by DuckDB
itself (no pandas, no full-file Python read); a query's result is
materialized once *inside DuckDB* and the UI pages through it — only one
page's worth of rows (default 100) is ever turned into JSON and sent to
the browser, no matter how big the result is.

**Second pass.** Shipped after actually using the v1 (SQL-first, upload,
join, paginate, export): (1) Parquet as a fourth load format — trivial,
DuckDB reads it natively the same way as CSV/JSON; (2) a table preview
(`/preview/<name>`, click a loaded source's name in the sidebar) so you're
not guessing column names/types before writing a join; (3) schema-aware
SQL autocomplete, built from the currently loaded tables rather than a
pasted schema (sql-studio's own flavor of this feature); (4) query elapsed
time plus one targeted error-message improvement (a "table does not
exist" error now lists what's actually loaded).

## How it's built

- `server.py` — FastAPI app: serves `ui/index.html`, plus `/upload`,
  `/load/vault`, `/tables`, `/table/remove`, `/preview/{name}`, `/query`,
  `/page`, `/export`, `/export/vault`, `/session/reset`. Thin — parses the
  request, delegates to `engine.py`, turns `engine.QueryError` into a
  clean 400. `/export/vault` and `/load/vault` are the two endpoints that
  talk to `core.vault` instead of just reading/writing `engine.py` state:
  `/export/vault` calls `core.vault.save_dataset()` directly (via
  `engine.export_result(session, "parquet")`, DuckDB's own streaming
  `COPY _result TO ... PARQUET`, deleted immediately after being
  encrypted into the vault) — see `vault/CLAUDE.md`'s "datasets" section
  for why this exists (feeding a query result into another tool, e.g.
  DataDiff Pro via the orchestrator, without ever holding the whole
  result in memory). `/load/vault` is the reverse — the consumer side:
  it decrypts a saved dataset via `vault.load_dataset_file()` to a
  tempfile, `shutil.move()`s it into the session's own `data_dir` (it
  can't stay an ephemeral tempfile — `engine.load_file()` builds a LAZY
  DuckDB view backed by that exact path, which has to keep existing for
  as long as the view might be queried, same as an uploaded file
  already requires), then calls `engine.load_file()` on it exactly like
  `/upload` does. Since roadmap B3 the vault call and every engine call
  run via `asyncio.to_thread` (sessions can now hit Redis/S3 storage, so a
  blocking call inside `async def` would stall every other request).
- `engine.py` — sessions keyed by a `duck_lab_sid` cookie (each browser tab
  owns its own set of loaded files), **stored outside the process since
  roadmap B3** via `session_store.py`: the table list + current result +
  a `version` counter in Redis, every uploaded file and every query result
  (Parquet) in S3 storage under `duck-lab/<sid>/`. Each worker keeps a
  disposable LOCAL working copy per session (`_Local`: one DuckDB connection
  with `memory_limit` + `temp_directory`, plus a cache dir under
  `$DUCK_LAB_CACHE_DIR`, default `/tmp/duck-lab-cache/<sid>/`), LRU-capped at
  `DUCK_LAB_LOCAL_SESSIONS` (8). `get_or_create_session()` rebuilds the local
  views whenever the stored version is newer, downloading files on demand.
  Every engine call holds the session's local `RLock` (one request at a time
  per session per process — a DuckDB connection isn't safe for concurrent
  use) and `server.py` runs them all via `asyncio.to_thread`.
- `session_store.py` — `StateBackend` (Redis + S3, sliding TTL
  `DUCK_LAB_SESSION_TTL` default 12 h, sweep of expired sessions' files) or
  `MemoryBackend` (standalone dev / unit tests; files kept in a local store
  dir outside the per-session cache).
- `ui/index.html` — single file, no build step. A small CodeMirror 6 setup
  (`basicSetup` + `@codemirror/lang-sql`'s `sql()` for highlighting **and**
  schema-aware autocomplete — no PL/pgSQL formatter, no Templates panel;
  this tool doesn't need SQL Studio's full stack) reusing SQL Studio's
  already-verified esm.sh version-dedup import recipe as-is (see
  `sql-studio/CLAUDE.md`'s CodeMirror gotcha before touching these import
  lines or bumping a version). **The schema feeding autocomplete is live,
  not pasted** — `buildSchemaNamespace()` reads straight from `STATE.tables`
  (itself from `/tables`), and `sqlCompartment` (a `Compartment`, same
  technique sql-studio's own schema box uses) gets reconfigured via
  `refreshSchemaAutocomplete()` every time `refreshTables()` runs — after
  every upload, remove, and session reset. If you add another place that
  changes `STATE.tables` without going through `refreshTables()`, the
  editor's autocomplete will silently go stale.

## How loading each format actually works

- **CSV/JSON/Parquet**: never read into Python memory at all. The
  uploaded file is streamed straight to disk (`shutil.copyfileobj` in
  `server.py`'s `/upload`, not `await file.read()`), then
  `engine.load_file()` points DuckDB directly at the saved file path as a
  `VIEW` using whichever read function `core.file_source.build_read_expr()`
  picks for the extension (`read_csv_auto`/`read_json_auto`/
  `read_parquet` — this mapping is shared with
  `orchestrator/connectors/file.py`, not re-derived here). DuckDB scans
  the file itself, vectorized, in its own engine — this is the actual
  reason this tool can handle files DataFrame Studio's pandas-based
  `/load` can't. (A single `load_file()` replaced three near-identical
  `load_csv()`/`load_json()`/`load_parquet()` functions once the format-
  detection logic moved to the shared module — one function with the
  format already known beats three copies of the same view-creation
  code.)
- **XML**: DuckDB has no native XML reader. `engine.load_xml()` reuses
  `core/normalizer.py`'s existing `normalize(raw, "xml")` — the same
  parsing DataDiff Pro already uses — to parse the document into a Python
  object once, builds a `pandas.DataFrame` via `pd.json_normalize()`, then
  **writes it to Parquet once** (`COPY ... (FORMAT PARQUET)`) and registers
  that file like any other table (format label stays `xml`). **This is the
  one format that fully loads into Python memory**, once, at upload — an
  accepted ceiling matching DataDiff Pro's own XML scope (single root
  element). Since B3 the DataFrame is not kept alive afterwards (the old
  `Session.frames` dict is gone), and other workers just read the Parquet.

## The materialize-once, paginate-many model (the core design)

`POST /query` does not return "the result" — it materializes
`<user_sql>` once inside the session's DuckDB connection, writes it ONCE to
a Parquet file (local cache + S3 storage, roadmap B3) and returns page 1.
`GET /page?offset=&limit=` re-slices that Parquet file (temp view
`_result`) with `LIMIT`/`OFFSET` — no recomputation per page turn, and any
worker can serve it (it downloads the result file if it doesn't have it).
One result per session: a new Run deletes the previous result's file
everywhere.

- **Pagination correctness caveat, stated plainly**: `LIMIT`/`OFFSET` over
  a table with no explicit `ORDER BY` isn't guaranteed stable by the SQL
  standard, though in practice a static materialized DuckDB table scans in
  a consistent order across repeated calls. If a query's row order matters
  to the person running it, the fix is for *them* to add `ORDER BY` to
  their SQL — this tool doesn't inject one.
- `/export` reads from the same result Parquet (full result, not just the
  visible page) via `COPY (SELECT * FROM _result) TO <file> (FORMAT ...)` —
  DuckDB writes the file directly, it's never pulled into one big Python
  object first. The temp export file is deleted after the response is sent
  (it used to accumulate in the session folder).

## Memory safety (why a big join doesn't crash the container)

Every session's DuckDB connection gets `PRAGMA memory_limit='512MB'`
(`engine.MEMORY_LIMIT`) and `SET temp_directory='<session dir>/spill'` at
creation (`engine._new_connection()`). This lets DuckDB's own buffer
manager spill the materialized `_result` (or any large intermediate join
state) to disk once it exceeds that budget, instead of growing the
process's memory until the container OOMs. This is the actual mechanism
behind "fast backend that never crashes the UI" — not just the pagination
on top of it.

## Multiple workers (roadmap B3)

Sessions are no longer per-process: verified with two separate uvicorn
processes sharing one cookie (upload on A, XML upload on B, join query on B,
page + export on A, remove on A seen by B) and with a full container
recreate (local cache wiped, session rebuilt from Redis + S3). The container
still runs `--workers 1` until roadmap B9 finishes the other tools.

## Things that will bite you if you don't know them

- **Sessions survive restarts (roadmap B3)** — 12 h sliding TTL; files of
  expired sessions are swept from storage. **Every upload is also copied to
  S3 storage** and every Run writes its result to Parquet + S3 — a real
  extra cost on big files/results, the price of any worker being able to
  serve the session. Changing a session means `engine._save()` (bumps the
  version); a new mutating function that forgets it leaves other workers
  on the old table list.
- **Only one statement per Run.** `engine._validate_single_statement()` is
  a best-effort quote-aware semicolon counter (tracks `'...'`/`"..."` so a
  semicolon inside a string literal isn't miscounted), not a full
  tokenizer like `sql-studio/query_guard.py`'s. It catches the obvious
  "pasted two statements" case; anything subtler just surfaces as a
  DuckDB parse error from inside the wrapping `CREATE TABLE AS` statement.
  There's no destructive-statement confirmation gate here (unlike SQL
  Studio) — this is the user's own sandboxed local DuckDB instance, not a
  shared production database, so there's nothing external a query here can
  damage.
- **Uploaded-file table names are sanitized and de-duplicated**
  (`engine._sanitize_name()`) — non-alphanumeric characters become `_`, a
  leading digit gets a `t_` prefix, and a name collision appends `_2`,
  `_3`, etc. The *displayed* table name (used in SQL) can therefore differ
  from the uploaded filename — `/tables` returns both `name` (what to
  query) and `source_file` (what was uploaded) so the UI can show both.
- **`DESCRIBE "<name>"` is how columns are listed** (`engine._columns_of()`)
  rather than tracking schema separately — if DuckDB's `DESCRIBE` output
  shape ever changes, this is the one place that needs updating.
- **`/preview/<name>` queries the loaded source directly — it has nothing
  to do with `_result`.** It's independent of whatever Run last produced;
  previewing a table doesn't touch or clear the current query result, and
  running a query doesn't touch the preview panel either. They're two
  separate, unrelated reads.
- **`engine._friendly_error()` only special-cases one thing**: a "table
  does not exist" error gets the actual list of loaded tables appended.
  Every other DuckDB error (parser errors, type errors, etc.) passes
  through verbatim — DuckDB's own messages are already specific (a Parser
  Error includes a caret at the exact position), so this deliberately
  isn't a general-purpose error-rewriting layer. Add a new special case
  here only for a confusion that's actually been hit, not preemptively.
- **`PREVIEW_ROWS` (20) is independent of `DEFAULT_PAGE_SIZE` (100)** —
  deliberately smaller, since a preview is "what does this look like," not
  a result you page through. There's no pagination on the preview panel.
- Mounted at `/tools/duck-lab/` by `main.py` in the repo root — this folder
  never needs to know that; it's a fully self-contained ASGI app either way
  (verify with `cd duck-lab && uvicorn server:app --reload`).

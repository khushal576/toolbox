# Data Lake — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and `../KNOWLEDGE_MAP.md` for the
symptom→file map. Plan and decisions: `../docs/roadmap/ROADMAP.md`, phase L.

## What this tool is

The power-user page of **Vault Data** (the lake catalog, `../core/lake.py`): **load files into tables** (L2) —
"Redshift COPY" style — and query them with SQL (Athena style, L3). Browsing, previewing, renaming and deleting
tables happens in the Vault page's 📦 Data tab; this tool is about getting data IN and querying it (🔎 SQL tab, L3).

Sources: a **browser upload** (several files → one table), the shared **data folder** (`~/toolbox-data` on the
owner's machine → `/data` read-only in rt-data + worker; `TOOLBOX_DATA_DIR`), a **link** (http/https), or a
**pattern** (`sales/2026-*.csv`, `logs/**/*.json.gz`). Formats are detected (extension, else content): CSV/TSV/text
(delimiter + header + types by DuckDB), JSON / JSON Lines, Parquet, XML (via core.normalizer → JSON lines), Excel
(.xlsx via pandas/openpyxl, one sheet), and `.gz` of the text formats. Modes: create (refused if it exists),
append (type clash refused), overwrite (new version; column changes logged). "Read in place" registers an
**external** table on a data-folder pattern instead (csv/json/parquet; nothing copied; changes show up).

## Where things live

| Concern | File |
|---|---|
| Endpoints (folder browse/match, upload staging, start/stop/poll a load, recent changes) | `server.py` |
| The load job (gather files → detect → convert XML/Excel → DuckDB COPY to Parquet → `lake.write_table`) | `loader.py` (`run_load`) |
| Data folder (confinement, patterns), upload staging (`STAGE`, S3 `data-lake/<upload id>/…`), link download | `sources.py` |
| Multi-file DuckDB reader + format detection (shared) | `../core/file_source.py` (`detect_any`, `build_multi_read_expr`) |
| Catalog, managed/external tables, preview | `../core/lake.py` |
| SQL: read-only check, mounting tables, instant/background runs, stored results, history, saved queries | `query.py` |
| Staging from a database (L4): Vault connection → tables or one SELECT → workspace | `staging.py` (`run_stage`) |
| The page (⬆ Load files / 🔎 SQL views, `#sql` opens SQL; 🗄 Database source = staging) | `ui/index.html` |

## Things that will bite you

- **Loads run in the `worker`** (`JobRunner("data-lake")`), so the worker must mount the data folder too (compose
  does) and has the same tool code. The web side only stages uploads and polls.
- **Memory is bounded by DuckDB**: `SET memory_limit` (`DATA_LAKE_MEMORY_LIMIT`, 1GB) + a spill directory; Parquet is
  written in ~256 MB files (`DATA_LAKE_PART_SIZE`). Verified: a 1.5 GB / 20 M-row CSV → 341 MB Parquet (2 files) in
  16 s with the worker peaking at 530 MiB. Excel and XML are the exceptions (read into memory to convert) — fine for
  normal spreadsheets, not for gigantic XML.
- **Data-folder paths are confined** (`sources._inside`): `..`, absolute paths and links pointing outside are refused
  when named directly and skipped inside a pattern; hidden files are ignored.
- **Uploads are staged in S3 storage** and removed after a successful load; failed loads keep them for 1 day (Retry
  later = load again with the same `upload_id`); `sweep_uploads()` runs on every upload.
- **Two loads into a NEW workspace at once** (two workers) used to fail on the unique name; `lake._ensure_workspace`
  now treats "someone else just created it" as fine.
- **Preview of a managed table reads only its first Parquet part** (`lake.preview`) — previewing a 20 M-row table
  takes ~0.4 s instead of downloading every part.
- **Different formats in one load are refused** (load them separately); different columns across files of one
  format are merged by name (`union_by_name`), missing values are NULL; tick "Add `_source_file`" to know which
  file a row came from.

## SQL (L3) — how it works and what bites

- **One fresh DuckDB per query**, only the tables the query names are mounted (views in a schema per workspace →
  `workspace.table`; a bare table name is mounted in `main` when exactly one workspace has it). A managed table's parts
  are downloaded once per process (lake FileCache), so the first query on a big table is slower.
- **Read-only is checked on DuckDB's parse tree** (`json_serialize_sql` in `analyse`): exactly one statement, a
  SELECT (EXPLAIN in front OK). Table functions other than `ALLOWED_FUNCTIONS` and `FROM 'some/file'` are refused —
  otherwise SQL could read any file the container can (`/proc/self/environ` holds the Vault key!). Extensions can't be
  auto-installed/loaded and the configuration is locked before the query runs. `CREATE [OR REPLACE] TABLE ws.t AS
  SELECT …` is recognised by regex first; its SELECT gets the same check.
- **Run** = in the web process (rt-data), `DATA_LAKE_INSTANT_SECONDS` (30) then interrupted, `DATA_LAKE_QUERY_MEMORY`
  (384MB, spills) and 2 threads. **Run in background** = worker job (`JobRunner` key `q-<id>`), 1GB, Stop = interrupt.
  DuckDB's memory limit is soft: a 30 M-row count(distinct) peaked at ~570 MiB anon in rt-data.
- **Every result is a Parquet file** in S3 (`data-lake-results/<id>/<id>.parquet`, `DATA_LAKE_RESULT_DAYS` 7) — paging,
  CSV/Parquet download and "Save as table" read it; nothing is re-run. Parquet has no 128-bit ints: HUGEINT columns
  (sum of BIGINT) are cast to DECIMAL(38,0); the JSON pages send whole decimals < 2^53 as numbers, others as text.
- History (last 500) and saved queries: Postgres schema `data_lake` (`queries`, `saved`).
- DuckDB 1.2's Python API has **no progress reporting** — loads and queries show elapsed time, not a percentage.

## Staging database tables (L4) — what bites

- Connections are the Vault's `postgres_connection` entries (any `db_type`: postgres / mssql / oracle, SSH tunnel
  aware) — manifest `vault: {read: [postgres_connection]}`; listing them shows names only. One pooled connection
  (`max_size=1`) via the shared `core.db` dialects; Postgres sessions are set read-only; a query must be one SELECT /
  WITH (`_check_select`). **SQL Server/Oracle staging is written on the shared dialects but not yet run against
  real engines.**
- Rows stream with the dialect's export cursor in `DATA_LAKE_STAGE_BATCH` (50 000) batches → one pyarrow Parquet
  file per batch. Types come from the values: a column pyarrow can't type (mixed values, UUIDs) becomes text,
  json/jsonb/arrays become JSON text (`->>`/`json_extract` work), NUMERIC precision is what the data needs
  (numeric(12,2) holding ≤ 1000.00 → DECIMAL(6,2)). DuckDB merges the batches with `union_by_name`, so a column
  that is NULL in the first batches still gets its real type. Zero rows → an empty table with the columns (text).
- Target names: `public.orders` → `orders`; if two chosen schemas share a table name both become `schema_table`.
  Create refuses (409) up front when any target exists. Stop = checked between batches; nothing is written then.

## L5 — S3, charts, joins, declared types

- **☁ S3 source:** a Vault `s3_location` (credentials; endpoint for non-AWS) + `s3://bucket/path` or pattern (a
  folder = everything under it). Copy in (DuckDB COPY straight from S3 → Parquet, nothing staged) or **read in place**
  (external table; its options record the location id, `lake.prepare` gives every reading connection a temporary
  secret scoped to the bucket — queries, previews, exports, profiles). Format from the extension (`format_from_name`;
  csv/json/parquet, .gz ok). httpfs is installed at build time; queries still switch autoloading off.
- **SQL tab:** 📊 Chart on a result (bars / line / points of the first 1000 rows, plain SVG), 🔗 per table in the tree
  = suggested joins (click inserts the JOIN; an empty editor gets a full SELECT).
- **Staging keeps declared types** (`declared_types`: varchar(100), numeric(12,2), NVARCHAR(MAX), NUMBER(12,2)…) in
  `source.column_types` → shown as each column's `sql_type`. Oracle NUMBER with decimals is fetched as Decimal
  (`_oracle_decimals`, that connection only). **Verified on real SQL Server 2022 and Oracle 23 free.**

## Verified (live, Postgres + S3 + worker)

1.5 GB CSV (above); a folder of 500 CSV files → one 50,000-row table with `_source_file` (1.2 s); an uploaded
`.csv.gz` with `;` delimiter detected; a link (JSON); an external table read in place; create-again refused (409);
the page driven in headless Chromium (data folder → pattern → new workspace → load → done). Unit tests: format
detection, folder confinement (host) + 15 loader/lake tests in the container (append/overwrite/column change,
Excel, XML, external, mixed-format and no-match errors).

L3: joins across workspaces, CREATE TABLE AS (a 30 M-row table in 28 s as a background job), group-by over 30 M rows
3 s instant, the 30 s timeout, Stop, paging, CSV/Parquet download, save as table (409-style refusal when it exists),
`read_csv('/etc/passwd')` / DELETE refused, the SQL tab in headless Chromium. 14 query tests in the container
(`tests/unit/test_data_lake_query.py`) + smoke `test_data_lake_sql`.

L4: a throwaway Postgres (300k orders with numeric/timestamptz and a column NULL for the first 200k rows, customers
with jsonb/uuid/date/bool): 3 tables / 305k rows staged in 3.2 s, create-again 409, overwrite → version 2, query
mode, DELETE refused, source untouched; the 🗄 Database tab in headless Chromium. Tests: `tests/unit/test_lake_l4.py`.

L5: SeaweedFS as the S3 endpoint — test-before-save (and a clear 403 message for bad keys), 3 Parquet files copied
(6000 rows), a CSV read in place, a join of both in SQL (instant and in the worker); profile of 30 M rows 12.7 s then
cached; suggested joins; chart + tree joins in headless Chromium.

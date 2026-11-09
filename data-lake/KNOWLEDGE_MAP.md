<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Backend: Vault Data loader (the former Data Lake tool) — mounted at `/tools/data-lake/`, hidden; page = Vault → Vault Data

Loads files into **Vault Data** tables as Parquet (roadmap L2), with an optional **column map** (L7: keep / rename / cast / fill / mask / hash / shuffle). Its Athena-style SQL backend (L3, `query.py`) stays but the SQL tab was dropped from the UI — SQL is Duck Lab's job. Read `data-lake/CLAUDE.md` first.

| If you need to change... | Go to |
|---|---|
| What can be loaded from where (upload / data folder / link / pattern), path safety | `data-lake/sources.py` (`browse`, `match`, `summary`, `STAGE`, `download`) |
| How a load works (detection, XML/Excel conversion, DuckDB COPY → Parquet, modes, column-change warning) | `data-lake/loader.py` (`run_load`) |
| Format detection / reading many files as one table (shared) | `core/file_source.py` (`detect_any`, `build_multi_read_expr`) |
| Endpoints, starting/stopping/polling a load | `data-lake/server.py` |
| The page (moved in L6: Vault → Vault Data → ⬆ Load files; `data-lake/ui/index.html` is only a redirect) | `vault/ui/index.html` (`#paneLoad`, the second `<script>` IIFE; ids prefixed `dl_`, CSS under `.dl`) |
| **Column map (L7)**: what a map may contain, how it becomes one DuckDB SELECT (cast → fill empty → protect), identifier/literal quoting, type allow-list | `data-lake/colmap.py` (`normalize_entries`, `compile_select`, `qi`, `ql`, `typed_literal`, `TYPES`) |
| Mask / hash / redact / empty / shuffle (what each does to NULLs and short values; shuffle = row_number join on a random or seeded key) | `data-lake/colmap.py` (`compile_select`: protect branches, `sh{k}` CTEs) |
| Guessing sensitive columns (email, Aadhaar, PAN, card, phone, SSN, names, address…) | `data-lake/colmap.py` (`suggest_protection`) |
| Counting values that don't convert (warn / strict stop), typed CSV columns read as raw text first | `data-lake/loader.py` (`_check_casts`, `_copy_to_parquet`), `core/file_source.py` (`varchar_columns`) |
| Preview columns before loading (DESCRIBE + 5 sample rows of the first files; link = first 8 MB) | `data-lake/loader.py` (`inspect_source`), `POST /inspect` in `server.py` |
| Saved column maps (templates, no salts/seeds), Postgres schema `data_lake`, table `colmaps` | `data-lake/colmap.py` (`save_template`, `template_columns`), `query.py` (`_SCHEMA`), `/colmaps` in `server.py` |
| Salts / seeds travel to the worker through a short-lived Redis key, never the job args or the catalog | `data-lake/colmap.py` (`split_secrets`, `merge_secrets`), `loader.py` (`stash_secrets`, `take_columns`, `drop_secrets`) |
| Masked / reshaped copy of an existing table (worker job) | `data-lake/loader.py` (`run_copy`), `POST /copy-table` in `server.py`; UI: Tables → "Copy with column map…" → `vaultDl.copyFrom` |
| The column-map grid, templates bar, job notes (cast warnings, protected columns) | `vault/ui/index.html` (`#dl_colCard`, `renderGrid`, `toMap`, `mapBody`, `buildMap`) |
| Where tables end up, external tables, preview | `core/lake.py` (`write_table`, `register_external`, `read_expr`, `preview`) |
| The shared data folder location | `TOOLBOX_DATA_DIR` (compose: rt-data + worker, `/data`, read-only) |
| What SQL is allowed (read-only check, which tables get mounted, unqualified names) | `data-lake/query.py` (`analyse`, `ALLOWED_FUNCTIONS`) |
| Running a query (instant 30 s vs background job, memory, timeout/stop), CREATE TABLE AS | `data-lake/query.py` (`execute`, `run_query_job`), env `DATA_LAKE_INSTANT_SECONDS` / `DATA_LAKE_QUERY_MEMORY` |
| Stored results (paging, CSV/Parquet download, save as table, 7-day expiry), history + saved queries | `data-lake/query.py` (`RESULTS`, `page`, `export_csv`, `save_as_table`, `STORE` schema `data_lake`) |
| (SQL editor: removed from the page — only the backend above remains) | – |
| Staging database tables (Vault connection → tables / one SELECT → workspace), batch typing, read-only source | `data-lake/staging.py` (`connect`, `run_stage`, `_batch_to_parquet`, `_merge`); page: `#src-db` |

### Vault Data in every tool (roadmap L4) — symptom → file

| If you need to change... | Go to |
|---|---|
| The table list every tool shows ("📦 workspace" groups) | Vault `GET /data/catalog` (`vault/server.py`) → `core/lake.py` `catalog()` |
| Table → file for a tool (Parquet/CSV, optional first N rows) / file → table | `core/lake.py` `export_table`, `import_file` (scoped: `ScopedLake`) |
| Duck Lab load / save | `duck-lab/server.py` `/load/lake`, `/export/lake`; page `refreshVaultSelect`, `btnSaveToLake` |
| DataFrame Studio load (1 M-row limit, `DF_STUDIO_LAKE_MAX_ROWS`) / save | `df-studio/server.py` `/load/lake`, `/export/lake`; page `loadLakeTable`, `saveLakeBtn` |
| SQL Studio full result → table / table → database | `sql-studio/server.py` `/export/lake`, `/import/lake`; page `btnExportLake`, import dialog |
| DataDiff "Load from Vault" with tables (2000-row limit, bigger refused) | `ui/index.html` `refreshVaultDatasetSelects` → Vault `GET /data/tables/{ws}/{t}/csv` |
| A new visitor sees someone else's tool session | `core_plugins/proxy.py` `_no_cookie_jar` (the proxy client must never store cookies) |

### Vault Data extras (roadmap L5) — symptom → file

| If you need to change... | Go to |
|---|---|
| Column profile (what's computed, sample size, cache) | `core/lake.py` `profile`, `PROFILE_SAMPLE`, table `lake.profiles`; Vault `GET /data/tables/{ws}/{t}/profile`; page `showProfile` |
| Suggested joins (name rules, overlap check, minimum %) | `core/lake.py` `suggest_joins`, `_GENERIC`, `MIN_OVERLAP`; Vault `/joins`; Data Lake tree `showJoins` |
| S3 credentials / reading s3:// tables / error wording | `core/lake.py` `use_s3`, `s3_secret_sql`, `prepare`, `s3_match`, `s3_error_text`; Vault `POST /test-s3` |
| Loading from S3 (copy or read in place) | `data-lake/loader.py` (`s3` branch, `format_from_name`); page `#dl_src-s3` |
| Column types shown as varchar(100) / numeric(12,2) | `core/lake.py` `sql_type` (+ `_table_dict`); staging `declared_types` → `source.column_types` |
| Charts on a query result | `vault/ui/index.html` `drawChart` (SVG, first `CHART_ROWS` rows) |
| DataFrame Studio Tables bar (green = loaded; first = `df`, others = variables by name) | `df-studio/ui/index.html` `renderCatalog`, `renderFrames`; `engine.add_frame`/`lake_frame`/`recompute`, `steps.FRAMES`; `/frames/add`, `/frames/remove`, `/session/clear` |
| DataFrame Studio: seeing a loaded table other than `df` (view chips above the grid, click a green Tables row, read-only, own stats) | `engine.frame_df` (refuses names not in `session.frames`) / `build_frame_preview` / `_capped_rows`; `server.py` `GET /frame/preview?name=`, `GET /column-stats?frame=`; page `renderViewBar`, `showView`, `viewFrame`/`dfPreview` |
| DataFrame Studio column stats in the grid header, SQL-style types | `engine.column_stats` (`GET /column-stats`), `engine.sql_type`; page `headerHtml`, `#statsBtn` |
| Duck Lab Tables bar (green = loaded, ✕ unloads) | `duck-lab/ui/index.html` `renderCatalog` → `/load/lake`, `/table/remove` |
| The workspace sidebar hiding inside a tool | `core_plugins/ui/workspace.html` (`body.in-tool`, `open()`, Ctrl+K / Esc handler) |

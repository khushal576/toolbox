# Athena – 2. Tables, formats, partitioning and performance

Short notes. Each point is a fact you can be asked about.

## A. File formats and compression
- Athena cost and speed depend mostly on **bytes scanned**. Reduce bytes → cheaper and faster.
- **Columnar (Parquet, ORC)**:
  - Read only the columns in the query.
  - Store min/max per page/row group, so Athena can **skip** data (works best when data is **sorted** on the filter column).
  - Compress well.
  - Default row group size: Parquet **128 MB**, ORC stripe **64 MB**. Do not go smaller. With many columns, bigger can help.
- **Row formats (CSV, JSON, Avro, text)**: read everything in the row. Good for landing data, bad for repeated analytics.
- Convert with **CTAS**, **Glue ETL** (or `UNLOAD`).
- Compression: you pay for bytes **before decompression**, so compression lowers cost.
  - **gzip**: good ratio, wide support. **zstd**: good ratio and speed balance. **snappy** common for Parquet.
  - Compressed **text** files (gzip) are **not splittable**: one worker per file. Too few big gzip files → low parallelism.
  - Uncompressed big text files can be split across workers.
- Parquet is the safe default. ORC is also fine (strong in Hive/EMR worlds).
- Parquet issues:
  - Schema mismatch (`array` declared as `string`) → `GroupColumnIO cannot be cast to PrimitiveColumnIO`.
  - Corrupt stats errors (`HIVE_CANNOT_OPEN_SPLIT: Index x out of bounds`, `HIVE_CURSOR_ERROR`) → set `parquet.ignore.statistics = true`.
- Column names in Parquet/ORC must match table columns (by name for Parquet by default; `parquet.column.index.access` changes this) (verify).
- Avoid very **wide** rows: a row or column cap of **32 MB**. A relation descriptor too big gives `GENERIC_INTERNAL_ERROR: ... CompilationException`; select fewer columns.

## B. Small files and S3 layout
- **Many small files** are the #1 performance problem. Each file costs listing, a request, and worker overhead. Target roughly **128 MB+ per file** (verify exact AWS guidance number; docs say "avoid too many small files, combine them").
- Fix at the source: buffer longer before writing (Firehose buffer size/time), compact with Glue/CTAS/Iceberg `OPTIMIZE`, reduce partition keys.
- S3 supports about **5,500 GET/HEAD requests per second per prefix partition**. Thousands of files + many concurrent queries → `SlowDown: Please reduce your request rate` (HTTP 503). Athena shows it in the query status.
  - Fix: larger files, fewer partition keys, stagger queries (queue/retry), spread data across prefixes.
- Keep a **flat layout** inside a partition (no extra folder hierarchy). Each directory level means more `LIST` calls.
- S3 `LIST` returns 1,000 keys per call. More than 1,000 files in one partition = several sequential lists.
- Don't replace or delete S3 files **while a query runs**. Errors: `HIVE_FILESYSTEM_ERROR: Incorrect fileSize`, `HIVE_CURSOR_ERROR: ... key does not exist`. Write new files or new partitions instead of overwriting in place.
- **SymlinkTextInputFormat** can stitch scattered files into a table, but adds extra S3 round trips. Use only if you cannot reorganize.
- **Glacier**: objects in Glacier Flexible Retrieval / Deep Archive are skipped or fail unless restored. Setting `read_restored_glacier_objects` works for Hive tables only (not Iceberg/Delta, which give an error).
- **Requester Pays** buckets need the workgroup option "Enable queries on Requester Pays buckets".
- Cross-Region: Athena can read S3 data in another Region (adds latency and data transfer cost). Results bucket must be in the query's Region. CSE-KMS data is **not** supported cross-Region.

## C. Partitioning (Hive style)
- **Partition** = a key (like `dt=2026-10-25`) mapped to an S3 prefix `.../dt=2026-10-25/`. A `WHERE` on the key reads only matching prefixes.
- Partition keys are **virtual columns** (not stored in the file). Declare them in `PARTITIONED BY`, not in the column list.
- Good keys: what most queries filter on (date, region, tenant). Optimize for **common** queries, not rare ones.
  - Do **not** partition by hour if most queries use days. Keep rows **sorted by timestamp** inside the file instead.
- Too many keys / too fine → tiny files, slow planning. Too few → big scans.
- **Always declare partition keys as `STRING`**. Only string lets Athena push the filter to Glue ("metastore-level pruning"). Other types are pruned on the Athena side, slow with many thousands of partitions and can time out. `BIGINT` partition columns also fail in some cases. Cast in the query if needed.
- Query with **equality on all partition keys** for fastest metadata lookup. Ranges/missing keys force Athena to list and filter all partitions.
- Use `EXPLAIN` to see which partition values will be scanned (look at `Fragment ... [SOURCE]` and `PARTITION_KEY`).
- **Adding partitions to the catalog** (choose one):
  - `ALTER TABLE ADD IF NOT EXISTS PARTITION (...) LOCATION '...'` (scriptable; use `IF NOT EXISTS` to avoid `_$folder$` junk).
  - `MSCK REPAIR TABLE` – scans S3 for **Hive-style** `key=value` folders. Slow, **only adds** new partitions (never removes stale), can fail with ~100,000+ partitions (memory), needs `glue:BatchCreatePartition`, and path case matters (lowercase). Not recommended for big tables.
  - **Glue crawler** on a schedule.
  - **Partition projection** (no catalog entries at all). 
  - Glue API `BatchCreatePartition` from your pipeline (e.g., Lambda after a load).
- **Remove stale partitions**: `ALTER TABLE DROP PARTITION`. Old/empty partitions still get listed on S3 and slow planning. After S3 lifecycle deletes data, also delete the catalog partitions.
- **Glue partition indexes**: speed up `GetPartitions` for tables with huge partition counts. Support `=`, `>`, `>=`, `<` combined with `AND`. Create in Glue.
- Athena can read tables with **10 million** partitions, but **not more than 1 million partitions in one scan**.
- `HIVE_PARTITION_SCHEMA_MISMATCH`: a partition's column types differ from the table's. Fix: drop the partition and recrawl, or drop and re-create it with the table schema (`MSCK REPAIR`).
- Zero rows from a partitioned table: partitions not registered, wrong LOCATION, non-Hive-style folder names, or case mismatch.
- `PARTITIONED BY` with partition data in directories **outside** the table location cannot be registered with Lake Formation (must be sub-folders of the table location).
- **Partition filtering on a view** works like on the base table (the filter is pushed down) but projection settings must be on the base table.

## D. Partition projection
- Athena **computes** partition values and S3 paths **in memory** from table properties, instead of calling `GetPartitions` in Glue.
- Benefits: faster planning on highly partitioned tables, **no partition maintenance** (new dates just work), good for logs (ALB, CloudTrail, Firehose output).
- Turn on with table property `projection.enabled = true`, then describe each key. When projection is on, Athena **ignores** partitions stored in the catalog for that table.
- Types and key properties (`projection.<col>.…`):
  - **`enum`**: `values` = comma list (keep to a few dozen; Glue table metadata limit ≈ **1 MB** gzip).
  - **`integer`**: `range` = `min,max` (comma, **not** hyphen), optional `interval`, `digits` (leading zeros).
  - **`date`**: `range` (can use `NOW`, `NOW-3YEARS`, `NOW+1MONTH`), `format` (Java date pattern, e.g. `yyyy-MM-dd` or `yyyy-MM-dd HH:00:00`), `interval`, `interval.unit` (YEARS…MILLIS). Dates are in **UTC**.
  - **`injected`**: values are not guessable; the query **must** give exactly one value per injected column in `WHERE` (strings only; `IN` list max **1,000** values).
- `storage.location.template` sets a custom S3 path pattern when folders are not `key=value` Hive style, e.g. `s3://bucket/logs/${year}/${month}/${day}/`.
- Traps:
  - Projection only works through **Athena**. Redshift Spectrum, EMR, Glue and Athena Spark read the normal catalog partitions (so those would see none).
  - Athena Spark (PySpark engine v3) does not support projection tables.
  - `SHOW PARTITIONS` does not list projected-only partitions.
  - Non-existent projected partitions return **zero rows, no error**, but cost S3 `LIST` calls. If **more than half** of projected partitions are empty (sparse table), regular partitions are faster.
  - Out-of-range values return zero rows, no error.
  - Missing predicate on a projected key → Athena enumerates the **whole range** (e.g., 1 million values = 1 million S3 lists). Keep ranges realistic: start at the dataset's first date, end with `NOW`.
  - Date format `dd-MM-yyyy-HH-mm-ss` / ranges with wrong interval unit fail; unit must match folder granularity.
- Compare: partition projection (no catalog calls, auto) vs partition indexes (still catalog-based, faster lookups) vs crawler/ADD PARTITION (manual maintenance).

## E. Bucketing
- **Bucketing** distributes rows into a fixed number of files by hash of a column (CTAS `bucketed_by`, `bucket_count`).
- Good for **high-cardinality** key with **single-value lookups** (e.g., user_id = X): only the matching bucket file is read.
- Bad when queries search many values (all files get read).
- Counts toward the **100 writers** limit in CTAS (partitions × buckets).
- Iceberg has its own `bucket(N, col)` transform (hidden partitioning).

## F. Open table formats (ACID tables on S3)
- Athena supports **Apache Iceberg** (full read/write), **Apache Hudi** (read, plus metadata table use), and **Delta Lake** (read) in Glue Data Catalog. Use Iceberg when you need updates in Athena.

### Iceberg on Athena
- Athena creates **Iceberg format v2** tables only. Supports Iceberg **1.4.2** (verify latest). Catalog = **Glue Data Catalog** only, with Glue **optimistic locking**.
- Create: `CREATE TABLE ... LOCATION 's3://...' TBLPROPERTIES ('table_type'='ICEBERG', ...)`. `CREATE EXTERNAL TABLE` fails ("External keyword not supported for table type ICEBERG"). Or CTAS with `table_type='ICEBERG'`, or a Glue crawler.
- File formats: **Parquet** (default), **ORC**, **Avro**.
- **Hidden partitioning** with transforms: `year`, `month`, `day`, `hour`, `bucket(N,col)`, `truncate(L,col)`. Queries filter on the source column; no partition column in `WHERE`. **Partition evolution** is allowed without rewriting data. Partitioning on nested fields is **not** supported.
- Operations: `INSERT INTO`, `UPDATE`, `DELETE FROM`, `MERGE INTO` (upsert). Each commit = a new **snapshot**.
  - Athena always uses **merge-on-read with position deletes** (copy-on-write table settings are ignored, no error).
  - Snapshot isolation; concurrent writers use optimistic commit and may need retry.
- **Time travel**: `FOR TIMESTAMP AS OF <ts>` and `FOR VERSION AS OF <snapshot_id>` (engine v3 syntax; older `FOR SYSTEM_TIME AS OF` was engine v2). Time without zone is read as **UTC**.
- Metadata tables: `"tbl$snapshots"`, `$history`, `$files`, `$manifests`, `$partitions`. Hidden column `$path`.
- Schema evolution: add/drop/rename columns, type widening via `ALTER TABLE` (no rewrite).
- **Maintenance** (you must schedule it):
  - `OPTIMIZE tbl REWRITE DATA USING BIN_PACK [WHERE ...]` – compacts small files and applies delete files.
    - `optimize_rewrite_data_file_threshold` (default 5, must be <50): fewer files than this → skip.
    - `optimize_rewrite_delete_file_threshold` (default 2, <50).
  - `VACUUM tbl` – expires snapshots and removes orphan files.
    - `vacuum_max_snapshot_age_seconds` default **432,000 (5 days)**.
    - `vacuum_min_snapshots_to_keep` default **1** (wins over max age).
    - `vacuum_max_metadata_files_to_keep` default **100**.
  - Glue can also run **automatic compaction** and snapshot/orphan cleanup for Iceberg (verify current options).
  - Vacuumed snapshots **cannot** be time-travelled to.
- Table statistics: with Glue column stats Athena uses a **cost-based optimizer** (`use_iceberg_statistics` property; on by default for S3 Tables). **Parquet column indexes** (`use_iceberg_parquet_column_index`) give page-level pruning.
- Limits:
  - Timestamp precision is **milliseconds** in Athena (Iceberg supports microseconds).
  - `ALTER TABLE SET LOCATION` unsupported.
  - DDL on Iceberg tables whose location is **registered with Lake Formation** is not supported (needs direct S3 access).
  - Lake Formation cannot manage permissions for `VACUUM`, `MERGE`, `UPDATE`, `OPTIMIZE` (only read permissions).
  - Metadata tables (`$files` etc.) fail with `AccessDeniedException` if the base table has LF row/cell filters or limited columns.
  - Modifying an Iceberg table with a non-Glue lock implementation can **lose data**.
  - CSE-KMS encrypted OTF tables registered with Lake Formation cannot be queried.
- Iceberg helps the "update/delete (GDPR)" and "avoid orphan files from failed CTAS" cases, because commits are atomic.
- **S3 Tables** (managed Iceberg in table buckets): Athena can query them; statistics and Parquet column indexes are on by default (verify the Region/catalog setup).

### Hudi and Delta Lake
- **Hudi**: CoW (copy on write, read heavy) and MoR (merge on read, write heavy). Query types: **snapshot**, **incremental**, **read optimized** (MoR only). Athena reads Hudi; writes are done by Spark/Glue/EMR. Use Hudi metadata table for faster listing.
- **Delta Lake**: Athena queries Delta tables registered in Glue. `INVALID_GLUE_SCHEMA` means the Glue schema is out of date vs. the Delta log: re-crawl, drop/re-create, or `ALTER TABLE ADD COLUMNS`.
- For all three, `UPDATE/MERGE/DELETE` from Athena work **only on Iceberg**.

## G. Query tuning (SQL side)
- **Select only needed columns.** Avoid `SELECT *` on columnar data.
- **Filter early** on partition and sorted columns.
- **Joins** (distributed hash join): put the **large table on the left, small on the right** (right = build side, held in memory). Athena reorders only if it has stats. If the right side is too big → split the build table into subsets and run several queries.
- Complex joins (`LIKE`, `>` conditions) compare every pair and can time out. Use `EXPLAIN` first.
- **Window functions** keep all rows of a window in memory. Add `PARTITION BY`, narrow the window, or replace:
  - top N → `ORDER BY ... LIMIT N`
  - latest per key → `max_by(col, ts)` and `arbitrary(col)` with `GROUP BY`
- **Aggregations**: group by fewer, numeric columns. Use `arbitrary()` instead of adding redundant columns to `GROUP BY`.
- **Approximations**: `approx_distinct` instead of `COUNT(DISTINCT)`; `approx_percentile`; `numeric_histogram` instead of `histogram`.
- **ORDER BY** is expensive (distributed sort). Skip it if not needed. `ORDER BY + LIMIT` is optimized as top-N.
- **LIKE** on long strings is slow. Prefer `regexp_like`, and anchor patterns (`'abc%'` over `'%abc%'`).
- **UNION ALL** over `UNION` unless you need de-duplication.
- Materialize repeated joins/aggregates with **CTAS** (or Glue ETL), then query the result.
- **Query result reuse** for repeated identical queries (file 1).
- Use `UNLOAD` for large exports.
- `EXPLAIN` shows the plan and partitions; `EXPLAIN ANALYZE` runs it and shows real stats.
- `GENERIC_INTERNAL_ERROR` family: null/schema mismatch, `OpenCSVSerDe` with `array`, INT overflow, TINYINT overflow, partition count mismatch.
- "Query exhausted resources at this scale factor" → fix joins/windows/distinct counts, retry, split query.
- Functions have a max of 127 arguments (`TOO_MANY_ARGUMENTS`).

## H. Performance at the service level
- Athena shares **account-level quotas** across all workloads. A burst from one team can queue or throttle another. Isolate with **capacity reservations** (file 4), not just more workgroups.
- Other services can throttle you: Glue (`Rate exceeded`), S3 (`SlowDown`), KMS (`exceeded the rate`), Lambda (`TooManyRequestsException`) for federated queries. Read the error to see which service complained. Athena retries recoverable errors, but not forever.
- KMS throttling with SSE-KMS and millions of small objects → enable **S3 Bucket Keys**, or raise KMS quotas.
- Query timeouts can hide Glue/Lake Formation throttling. Check CloudTrail.
- Tables with thousands of partitions of non-string type → timeouts. Switch key to string.

## I. Scenarios: If X → Y, because Z
- If a daily query on 5 TB of JSON is slow and expensive → convert to partitioned Parquet (CTAS or Glue), because columnar reads fewer bytes.
- If new `dt=` folders arrive every hour and someone runs `MSCK REPAIR TABLE` all the time → switch to partition projection (date type), because there is nothing to maintain and planning is faster.
- If a table has 500,000 partitions and queries are slow → partition projection or partition indexes, because `GetPartitions` becomes the bottleneck.
- If Redshift Spectrum also reads the same table that uses partition projection → keep real partitions too (or register them), because Spectrum ignores projection.
- If only 10% of projected partitions have data → use normal partitions, because empty projected partitions still cost S3 lists.
- If queries fail with `SlowDown` → make fewer, larger files and stagger queries, because S3 request limits per prefix are exceeded.
- If queries look up one `user_id` among billions → bucket by `user_id` (or Iceberg bucket partition), because only one file is read.
- If you must delete a user's records (GDPR) from the lake via SQL → Iceberg `DELETE` + `OPTIMIZE` + `VACUUM`, because plain Parquet files cannot be edited.
- If an Iceberg table gets slower after many small inserts → `OPTIMIZE ... REWRITE DATA USING BIN_PACK`, because small files and delete files pile up.
- If you need to see a table as it was yesterday → Iceberg `FOR TIMESTAMP AS OF`, because snapshots are kept until `VACUUM`.
- If `GROUP BY` fails with out of memory → group by fewer numeric columns, use `arbitrary`, use `approx_distinct`, because memory per node is the limit.
- If a join fails with out of memory → put the smaller table on the right, or split the build side, because the right table is hashed in memory.
- If a partition filter on an integer key is slow → store the key as string, because only string filters are pushed to Glue.
- If Athena returns zero rows after you added new folders → add partitions (`ADD PARTITION`, crawler, or projection), because the catalog does not know them.

## Verified from AWS docs on 2026-10-25
Read from current Athena User Guide pages: Optimize Athena performance (service, query, data, S3 throttling), partition projection and supported types, Iceberg (considerations, create tables, update data, time travel, optimize), Hudi, CTAS/INSERT INTO 100-partition workaround, troubleshooting, Lake Formation limitations.
Not confirmed (verify): ideal file size number (128 MB is common guidance, docs say "avoid small files"), parquet column-name matching defaults, latest Iceberg version supported, Glue automatic compaction options for Athena-created tables, S3 Tables setup details, Delta Lake write support, exact S3 request-rate figure (5,500 GET/s per prefix partition comes from the docs page).

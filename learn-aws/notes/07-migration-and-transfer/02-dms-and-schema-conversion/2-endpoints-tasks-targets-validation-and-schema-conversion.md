# DMS – 2. Sources and targets, task settings, table mapping, LOBs, S3/Kinesis/Redshift targets, validation, Schema Conversion

Short notes. Each point is a fact you can be asked about.

## A. Sources and targets (verified list + notes)
- **Sources** (self-managed on EC2/on-premises, RDS/Aurora, other clouds): Oracle, SQL Server, Azure SQL / Managed Instance / Azure DB for PostgreSQL and MySQL, Google Cloud for MySQL/PostgreSQL, OCI MySQL HeatWave, PostgreSQL, MySQL-compatible (MariaDB, Aurora MySQL), SAP ASE, **MongoDB**, **Amazon DocumentDB**, **Amazon S3**, IBM Db2 LUW, IBM Db2 for z/OS.
- **Targets** (common): RDS/Aurora (all engines), Oracle, SQL Server, PostgreSQL, MySQL, **Redshift** (and Serverless), **S3**, **DynamoDB**, **Kinesis Data Streams**, **MSK / Apache Kafka**, **OpenSearch**, **DocumentDB**, **Neptune**, Redis-compatible (verify), SAP ASE, Db2.
- You can migrate from **any supported source to any supported target**, including different engines.
- S3 as a **source** reads files (CSV/Parquet) written in DMS format for loading into databases.
- Endpoint settings: engine, server, port, database, user/password (or **Secrets Manager**), **SSL mode** (`none`, `require`, `verify-ca`, `verify-full`), extra connection attributes, KMS key.
- For **Kinesis** and **DynamoDB** targets, "SSL mode" doesn't apply (always HTTPS).
- Test an endpoint with **test connection** before creating the task.

## B. Table mappings (verified)
- A task's **table mappings** are JSON **rules** applied in order:
  - **Selection rules**: `include` / `exclude` schemas and tables (wildcards `%`). Choose what to migrate.
  - **Transformation rules**: rename schema/table/column, add or remove column, change data type, add prefix/suffix, `add-before-image-columns`, masking transformations, convert case, etc.
  - **Table-settings rules**: **parallel-load**, **lob-settings** per table, **mapping-parameters** for non-relational targets.
  - **Object-mapping rules** for Kinesis/Kafka/DynamoDB/OpenSearch targets (`map-record-to-record`, `map-record-to-document`, attribute-mappings, partition key).
  - **Validation rules** (override-validation-function).
- **Source filters** (selection rule `filters`): limit rows by column conditions (`eq`, `gte`, `lte`, `between`, …). Use to split a huge table into several tasks by key ranges.
- Schema/table names are **case sensitive** in rules for some engines; get them right (Oracle upper, PostgreSQL lower).
- To change the Oracle target schema from the endpoint user's schema, use a **schema rename** transformation. Tablespace transformations exist for Oracle targets (`table-tablespace`, `index-tablespace`).
- **Data masking transformations** exist (verify types): columns masked in migration; validation skips masked columns.

## C. Task settings that matter (verified)
- **Target table preparation mode**: `DO_NOTHING`, `DROP_AND_CREATE` (default), `TRUNCATE_BEFORE_LOAD`. Pick `DO_NOTHING` or truncate if you created the schema with Schema Conversion.
- **Include LOB columns**: LOB handling modes below.
- **MaxFullLoadSubTasks**: tables loaded in parallel (default **8**, max **49**). Higher helps on big instances; lower on small ones.
- **CommitRateDuringFullLoad** (default 10,000 records) and **bulk array size** affect memory.
- **Batch-optimized apply** (`BatchApplyEnabled`): groups changes and applies in batches for speed on the target. **Breaks referential integrity** during apply; disable FKs; not supported for **Kinesis** targets (causes failure and data loss).
- **Transactional apply** (default): keeps transaction order and integrity; slower.
- **Parallel load** for full load: split a table by `partitions-auto`, `subpartitions-auto`, `partitions-list`, or `ranges` (and `none`). Works from Oracle, SQL Server, MySQL, Sybase, Db2 LUW. Speeds large partitioned tables.
- **ParallelApply*** settings (threads/queues/buffer) speed CDC to streaming targets (Kinesis, Kafka): `ParallelApplyThreads` max 32, `ParallelApplyBufferSize` default 100 (max 1,000), `ParallelApplyQueuesPerThread` up to 512. With ParallelApply the default Kinesis partition key becomes the table **primary key**.
- **Error handling** policies: what to do on data errors, table errors, apply conflicts; `TableErrorPolicy`; stop task after N errors.
- **Control table** settings: schema for `awsdms_*` tables.
- **Logging**: enable CloudWatch logs; component severity (SOURCE_UNLOAD, TARGET_LOAD, SOURCE_CAPTURE, TARGET_APPLY, TASK_MANAGER…). Debug logging grows fast and can fill replication storage (`storage-full`).
- **StopTaskCachedChangesApplied/NotApplied**: stop task after full load and cached changes handling (cutover pattern: pause to create indexes/constraints).
- **Time Travel** (v3.4.6+): save raw/transformed data logs to S3 (KMS-encrypted) for debugging; turn on only for tasks that need it (extra memory); PostgreSQL source and PostgreSQL/MySQL targets.
- **Context logging** (v3.5.0+): connection IDs, SQL statements (no data), stream positions in task logs.
- **Task statuses**: Creating, Ready, Starting, Running, Stopping, Stopped, Failed, Error, Running with errors, Modifying, Moving, Failed-move, Testing, Deleting.
- **Table states**: Table does not exist, Before load, Full load, Table completed, Table cancelled, Table error.
- **Reload tables** during a task, **move a task** to another replication instance while stopped, **modify** a stopped task.

## D. LOB handling (verified)
- LOB = large objects (BLOB, CLOB, NCLOB, JSON treated as LOB on some engines). DMS loads a row **without** the LOB then **updates** it with the LOB data → **LOB columns on the target must be nullable** (unless Oracle→Oracle limited mode).
- **Limited LOB mode** (default): migrates LOBs **up to Max LOB size** (default **32 KB**); larger values are **truncated**. Fastest. Set the size to the largest LOB in scope.
- **Full LOB mode**: migrates every LOB regardless of size; **much slower**; LOB chunk size setting; memory heavy.
- **Inline LOB mode**: small LOBs (≤ `InlineLobMaxSize`, 1–102,400 KB; default 0) go inline during full load; larger ones use full LOB lookup. Needs `FullLobMode=true`. Values above 32 KB can cause memory pressure. CDC uses lookups.
- **Per-table LOB settings** (`lob-settings` in table-settings rule): override mode and `bulk-max-size` for specific tables.
- Full LOB support: Oracle, SQL Server, ODBC sources; Oracle and SQL Server targets. **Redshift and S3 targets have limited LOB support only** (no unlimited size). **Kinesis**: no full LOB; max LOB **1 MB**.
- Split tasks by LOB profile: frequently updated vs rarely updated, large vs small, hot vs cold tables.
- PostgreSQL JSON is treated like a LOB: Limited LOB with too small a Max can truncate JSON.

## E. Full load and CDC best practices (verified)
- **Full load**: drop or delay **primary key indexes, secondary indexes, foreign keys and triggers** on the target; recreate after full load. Turn off referential constraints and DML triggers. If data is small you can keep primary keys.
- **Full load + CDC**: **pause before CDC** (use the stop-after-full-load setting) to build **secondary indexes** (CDC needs them to avoid table scans) and constraints; **enable triggers right before cutover**.
- Turn off **backups, Multi-AZ and logging on the target** during migration (RDS), turn back on at cutover.
- **Multiple tasks**: split table sets that don't share transactions; each task reads the log separately, so don't overload the source. Consolidate tasks to reduce source load.
- **Large tables**: split with row filters (ranges) or parallel load by partition; one full-load task per static partition + one full-load + CDC task for the active partition.
- **Reduce source load**: fewer tasks/tables per task; full load does a **full table scan per table** in parallel.
- **Source log retention**: keep redo/binlog/WAL long enough for CDC to catch up after a stop.
- **Primary keys**: CDC and validation need PK/unique index; tables without PK cause problems (verify behavior per target).
- DDL: DMS replicates only a **limited set** of DDL; it doesn't propagate indexes, users, privileges, stored procedures.
- **Unsupported data types** must be mapped or excluded; run a **premigration assessment** to find them.

## F. Premigration assessments (verified)
- Evaluate a task **before it runs**: unsupported data types, mismatched indexes/primary keys, conflicting task settings, missing source prerequisites (such as supplemental logging).
- Run via console or `StartReplicationTaskAssessmentRun`; results saved as report in **S3**.
- Task status shows **Testing** during an assessment.
- Run diagnostic **support scripts** (per engine) to find issues early.

## G. Amazon S3 as a target (verified)
- Default file format **CSV**; option **Parquet** (columnar, smaller, faster queries) via `DataFormat=parquet`; Parquet encodings (`rle-dictionary`, `plain`, `plain-dictionary`) and `ParquetVersion`.
- Layout: `bucketFolder/schema_name/table_name/LOAD00000001.csv` for full load (hex counter); CDC files named by timestamp, e.g. `20141029-1134010000.csv`.
- **CDC output**: first column **`Op`** = `I` (insert), `U` (update), `D` (delete). Files hold the row after change (deletes show the deleted row).
- Option **`IncludeOpForFullLoad`** adds the `I` column to full-load files too, so full load and CDC files have the same layout.
- By default CDC stores changes **per table without transaction order**. To keep order across tables use **`PreserveTransactions`** with **`CdcPath`** (not combinable with `DatePartitionEnabled` or `AddColumnName`).
- **`CdcInsertsOnly`** writes only inserts; **`CdcInsertsAndUpdates`** writes inserts+updates.
- **Date partitioning** (`DatePartitionEnabled`): folders by commit date (`DatePartitionSequence` YYYYMMDD etc., delimiter SLASH/DASH/UNDERSCORE/NONE, timezone). Good for Athena partition pruning.
- **`CdcMaxBatchInterval`** (default 60 s) and **`CdcMinFileSize`** control how often CDC files are written (bigger files, fewer small files).
- **`MaxFileSize`** for full-load CSV default 1,048,576 KB (1 GB).
- **Encryption**: `EncryptionMode` `SSE_S3` or `SSE_KMS` with `ServerSideEncryptionKmsKeyId`; the DMS IAM role needs S3 permissions (and KMS permissions). Canned ACLs supported.
- Supported DDL in CDC: truncate, drop, create, rename table, add/drop/rename column, change column type.
- Typical use: **data lake landing**: DB → DMS → S3 (Parquet, partitioned) → Glue Catalog → Athena/Redshift Spectrum; or S3 → Glue/EMR upserts to Iceberg.
- Data validation for S3 targets has its own limitations.

## H. Kinesis Data Streams and Kafka as targets (verified)
- Records are **JSON**; formats `JSON` or **`JSON_UNFORMATTED`** (single-line, newline delimited; good for **Firehose → S3 → Athena**).
- Reserved fields: **RecordType** (data or control), **Operation** (`load`, `insert`, `update`, `delete`; control ops like `create-table`, `drop-table`, `add-column`…), **SchemaName**, **TableName**, **Timestamp**.
- **Control records** mark events such as task restarts and DDL changes (`IncludeControlDetails`, `IncludeTableAlterOperations`).
- Optional details: `IncludeTransactionDetails`, `IncludePartitionValue`, `IncludeNullAndEmpty` (v3.4.1+), `PartitionIncludeSchemaTable` (spreads keys across shards).
- **Partition key** options (object mapping): `schema-table`, `primary-key`, `transaction-id`, `constant`, `attribute-name`. `constant` forces **one shard / total order** (low throughput). `transaction-id` keeps a transaction together.
- **Object mapping** rules: `map-record-to-record` (one attribute per column) or `map-record-to-document` (`_doc`), `exclude-columns`, attribute-mappings for reshaping/combining fields.
- **Before images** of updates (`BeforeImageSettings` or `add-before-image-columns`): PostgreSQL gives only PK columns unless `REPLICA_IDENTITY FULL`; Oracle gives changed columns; MySQL gives all except LOBs. S3 targets use the transformation rule only.
- **Limitations**: no deduplication (consumers must handle duplicates); **no full LOB** (max 1 MB); **BatchApply not supported** (task failure + data loss); Kinesis stream must be in the **same account and Region** as the replication instance; `BigInt` over 16 digits needs conversion to string; embedded `\0` characters truncate data; multiple DML on a LOB in one transaction keeps only the last LOB value.
- Needs **IAM role** with `kinesis:DescribeStream`, `PutRecord`, `PutRecords`; since v3.4.7 reach Kinesis via **VPC endpoint** or public routes.
- Multi-threaded **full load** to Kinesis: `ParallelLoadThreads` (max 32), `ParallelLoadBufferSize` (default 50, max 1,000), `ParallelLoadQueuesPerThread` (5–512).

## I. Redshift, DynamoDB, OpenSearch targets (notes)
- **Redshift**: DMS stages data as files in **S3**, then runs **COPY** into Redshift (needs an S3 bucket and IAM role). Limited LOB. Enhanced full-load throughput for Oracle→Redshift/S3 with specific settings. Redshift Serverless is a supported target (not eligible for enhanced throughput).
- **DynamoDB**: uses **object mapping** (partition key/sort key, attribute mappings); good for relational → NoSQL redesign; throttle by DynamoDB capacity; consider on-demand during load. (details: verify)
- **OpenSearch**: loads documents into indexes; one index per table; use for search copies; Serverless supported through VPC endpoints.
- **DocumentDB / Neptune**: target document/graph models via mapping (verify specifics).
- **Zero-ETL** (Aurora/RDS/DynamoDB → Redshift) is a separate feature and often replaces DMS for that pair.

## J. Data validation (verified)
- Task option that **compares source and target rows** after full load and continues for **CDC changes**. Reports mismatches. Uses extra queries on **both** DBs (extra load, extra time).
- Supported source/target engines for validation: Oracle, PostgreSQL-compatible, MySQL-compatible (incl. MariaDB, Aurora), SQL Server, Db2 LUW, **Redshift** (target), **S3** (target; special rules).
- **Needs a primary key or unique index.** PK limits: not CLOB/BLOB/BINARY/BYTE; VARCHAR/CHAR PK length < 1,024; Oracle `NOVALIDATE` keys don't count; Oracle unique keys must also be `NOT NULL`.
- Table **ValidationState**: Not enabled, Pending records, **Mismatched records**, **Suspended records** (continuously changing rows), **No primary key**, Table error, Validated, Error, Pending validation, Preparing table, Pending revalidation.
- Counters: `ValidationPending`, `ValidationSuspended`, `ValidationFailed`. CloudWatch metrics: `ValidationSucceededRecordCount`, `ValidationAttemptedRecordCount`, `ValidationFailedOverallCount`, `ValidationSuspendedOverallCount`, `ValidationPendingOverallCount`, bulk/item query latencies.
- **Failure table** on the target: `awsdms_control.awsdms_validation_failures_v1` (task name, table, key, `FAILURE_TYPE` = `RECORD_DIFF`, `MISSING_SOURCE`, `MISSING_TARGET`, `TABLE_WARNING`, details JSON). v3.6.1+ adds `awsdms_validation_failures_v2` with **data resync** columns.
- **Revalidate** up to 10 tables while a task runs.
- **Validation-only tasks** (`EnableValidation` + `ValidationOnly`): full-load validation quickly compares all rows once and stops (changes are reported as failures); CDC validation-only delays re-checks and retries to avoid false positives. Use to control timing, isolate load, or get a quick mismatch count before cutover.
- **Enhanced validation** (engine 3.5.4): faster for Oracle→PostgreSQL, SQL Server→PostgreSQL, Oracle→Oracle, SQL Server→SQL Server; needs Secrets Manager credentials and `DBMS_CRYPTO` (Oracle) / `pgcrypto` (PostgreSQL).
- Limits: stops if > **10,000** failed/suspended records; not for **views**; not when several DBs are consolidated into one; ignores masked columns; not with character-substitution settings; not for Oracle LONG; **Aurora PostgreSQL Limitless** shows "No primary key".
- **Redshift validation** is heavy: reduce `PartitionSize`/`ThreadCount`; keep primary key aligned with sort key.
- **Data resync** (v3.6.1+): can automatically fix certain mismatches (upsert/delete) recorded in the failures table. (verify availability)

## K. DMS Schema Conversion and SCT (verified)
- **DMS Schema Conversion** converts the **schema and code objects** (tables, views, stored procedures, functions, data types, synonyms…) to the target engine and can **apply** them to the target or **export SQL scripts** to S3. It converts **schema, not data** (data is moved by DMS).
- Fully managed web feature built on the **AWS SCT** conversion engine; rules-based (repeatable) plus optional **generative AI** conversion for objects rules can't fully convert.
- Workflow: **instance profile** + **source/target data providers** (+ **Secrets Manager** secrets) → **migration project** → **assessment report** (what converts automatically vs manual) → convert → review/edit → apply or export. A **virtual target** lets you work before a real target exists.
- Supported paths (doc table): Oracle → Aurora/RDS PostgreSQL (AI ✓), Oracle → Aurora/RDS MySQL, Oracle → **Redshift**, SQL Server → PostgreSQL (AI ✓), SQL Server → MySQL, PostgreSQL → MySQL, MySQL → PostgreSQL, **Db2 LUW → PostgreSQL** (AI ✓), Db2 z/OS → PostgreSQL (AI ✓; API/CLI only) and → RDS for Db2, SAP ASE → PostgreSQL (AI ✓).
- **Transformation rules** change names/data types; **conversion settings** per path; **extension packs** emulate source features missing in the target (like Oracle functions).
- Generative AI conversion uses **cross-Region inference** in supported Regions only (many US/EU/AP Regions).
- Data providers need network access; for unsupported Regions create the project elsewhere and set up cross-Region connectivity.
- **AWS SCT** (downloadable desktop app) does the same job locally; docs say DMS Schema Conversion is the managed alternative. The exam guide v1.1 **removed SCT** from the in-scope list, but the concept still appears with DMS.
- Same engine moves: use native tools (Oracle SQL Developer, MySQL Workbench, pgAdmin) for schema; **no need** for Schema Conversion.

## Scenarios (if → then, because)
- **If** you want a **data lake** copy of an operational database that keeps up with changes, **then** run a DMS **full load + change data capture (CDC)** task to an **Amazon S3** target, using **Parquet** (a smaller, faster columnar format) and **date partitioning** (`DatePartitionEnabled`, folders by commit date). **This works because** the S3 target writes full-load files and **timestamped CDC files**, with a first column **`Op`** (`I` insert, `U` update, `D` delete) so you know what changed. Date folders let **Athena** skip data it does not need. By default CDC files are per table without transaction order; use `PreserveTransactions` to keep order.
- **If** downstream systems want every row change as an event, **then** use DMS with an **Amazon Kinesis Data Streams** target; if you also want the data in S3 for **Athena**, use the **`JSON_UNFORMATTED`** format and send it through **Amazon Data Firehose** to S3. **This works because** DMS writes each change as a **JSON** record with fields like **Operation** (`insert`, `update`, `delete`), and single-line JSON suits Firehose → S3 → Athena. Kinesis does not remove duplicates, so consumers must handle them.
- **If** consumers need all rows of one transaction together, **then** set the **Kinesis** partition key to **`transaction-id`** in the object mapping. **This works because** the partition key decides the shard, and `transaction-id` keeps one transaction's records together.
- **If** you need one global order across all tables in **Kinesis**, **then** use the **`constant`** partition key and accept low throughput. **This works because** a constant key sends everything to **one shard**, which gives total order but limits speed.
- **If** most **large object (LOB)** values are small but a few are huge, **then** use **inline LOB mode** (small LOBs up to `InlineLobMaxSize` go inline, big ones are looked up; needs `FullLobMode=true`), or put the huge-LOB tables in their own task. **This works because** **Limited LOB mode** truncates values above Max LOB size (default **32 KB**), while **Full LOB mode** is much slower; mixing both keeps speed without losing data.
- **If** a full load of a **2 TB** table is slow, **then** use **parallel load** (split the table by partitions or ranges) or run several tasks, each with **source filters** on key ranges. **This works because** splitting a big table lets several parts load **at the same time**, which speeds up large tables. Each extra task reads the source separately, so don't overload the source.
- **If** **change data capture (CDC)** is slow and the **`CDCLatencyTarget`** metric is high, **then** check for **missing indexes or primary keys** on the target, or a target **IOPS** (disk speed) bottleneck. **This works because** high target latency means DMS is slow at **applying** changes, and without indexes each change causes a table scan on the target.
- **If** a **Kinesis** target task loses data after you enable **batch-optimized apply** (`BatchApplyEnabled`), **then** turn batch apply off. **This works because** batch apply is **not supported** for Kinesis targets and causes task failure and data loss.
- **If** you must prove the target data is identical to the source, **then** enable **DMS data validation** or run a **validation-only task** before cutover. **This works because** validation compares source and target rows after full load and keeps checking CDC changes, recording mismatches in `awsdms_validation_failures_v1`. It adds query load on both databases and stops after **10,000** failed records.
- **If** validation shows **"No primary key"**, **then** add a primary key or unique index to the table, or prove the data another way. **This works because** DMS data validation **needs a primary key or unique index** to match rows between source and target.
- **If** the database engine changes and you need views and stored procedures converted, **then** start with a **DMS Schema Conversion** **assessment report**. **This works because** the report shows what converts automatically and what needs manual work, before you convert, review and apply the code.
- **If** you only need the converted schema scripts, **then** have **DMS Schema Conversion** **export** the converted code as **SQL scripts to Amazon S3** instead of applying it. **This works because** Schema Conversion can either apply objects to the target or export them as SQL.
- **If** source and target use the **same engine** and you want only dump/restore speed, **then** use **DMS homogeneous data migrations**. **This works because** it runs **native tools** (like pg_dump/pg_restore) with less setup, and no schema conversion is needed.
- **If** **Amazon Redshift** is the target, the source is **Amazon Aurora**, and data must stay continuously fresh, **then** consider **zero-ETL** integration instead of DMS. **This works because** zero-ETL (Aurora/RDS/DynamoDB → Redshift) is a separate built-in feature that often replaces DMS for that pair.

## Verified from AWS docs on 2026-10-09
Read: best practices page, tasks page, Serverless pages, S3 target page (saved output), Kinesis target page, data validation page, homogeneous migrations page, Schema Conversion page, monitoring page, pricing summary. Not confirmed (verify): DynamoDB/OpenSearch/DocumentDB/Neptune target mapping details, Redshift staging and COPY mechanics, masking transformation types, exact list of reserved PK limits across engines, data resync availability, Redis target support, Time Travel engine support.

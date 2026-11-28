# Glue – 3. ETL patterns, formats, streaming and performance

Short notes. Each point is a fact you can be asked about.

## A. Reading and writing data
- Two ways to read in a script:
  - `from_catalog`: use a Catalog table (gets schema and **partition columns**, supports pushdown predicates, bookmarks work well).
  - `from_options`: give the connection type and options directly (`connection_type="s3"`, `"redshift"`, `"mysql"`, and so on). No Catalog needed.
- **S3** sources and sinks: CSV, JSON, Parquet, ORC, Avro, XML, Ion, grok log formats. Compression is automatic for common codecs on read.
- Always use **`s3://`** URIs in Glue. Reading or writing with **`s3a://`** can fail with "Failed to parse XML document" when listing hundreds of files.
- **JDBC** (MySQL, PostgreSQL, Oracle, SQL Server, Redshift via JDBC): needs a **connection**. Credentials from Secrets Manager.
  - Parallel JDBC reads: set partitioning options so Spark runs several queries at once. Without them, JDBC read is **one task** (slow). Options: `hashfield` / `hashexpression` and `hashpartitions` for DynamicFrames; `partitionColumn`, `lowerBound`, `upperBound`, `numPartitions` for Spark DataFrames **(verify names)**.
  - A pushdown query (`sampleQuery` / `query` option) lets the database do the filtering **(verify option names)**.
- **Redshift**: Glue reads and writes through **S3 using a temp path** (`--TempDir`): it runs `UNLOAD` to read and `COPY` to write. So the job role and Redshift need access to that S3 path. Long jobs can fail with **"S3 service token expired"** (temporary credentials expire after **1 hour**).
- **DynamoDB**: read by scan (uses table read capacity; Glue can limit the percentage it uses) or from an **S3 export** (no read capacity used, point-in-time). Writes use table write capacity **(verify option names)**. `simplify_ddb_json` / `unnest_ddb_json` flatten DynamoDB JSON shapes.
- **Kinesis** and **Kafka/MSK**: streaming sources (section E). Kinesis needs no connection. Kafka does.
- Other connectors: OpenSearch, MongoDB/DocumentDB, Snowflake, BigQuery and SaaS apps through Glue connectors **(verify current list)**.
- **Reading S3 objects in archive classes**: if a table has partitions in **Glacier / Deep Archive** you get *"The operation is not valid for the object's storage class"*. Fix: **exclude storage classes** (`excludeStorageClasses`) in the read options.
- **Writing partitioned output**: `partitionKeys=["year","month"]` in the sink options writes `year=…/month=…/` folders. A DynamicFrame is **not** partitioned by default.
- A write to **Microsoft SQL Server** with a **Boolean** column needs the table created first (or map the Boolean to number/string). **Oracle** object names are limited (30 or 128 bytes depending on version). Use `ApplyMapping` / `RenameField` to fit.

## B. File formats and compression (exam: pick the right format)
- **Parquet** = columnar, compressed, splittable, carries schema. Best default for analytics (Athena, Redshift Spectrum, Glue). Reads only the columns used.
- **ORC** = columnar, similar benefits, popular with Hive/EMR.
- **Avro** = row-based, carries schema, good for **streaming** and schema evolution (works with Schema Registry).
- **JSON / CSV** = text, easy to produce, large and slow to scan, no real types. Use for raw landing only.
- **Convert early**: land raw CSV/JSON, then Glue converts to **Parquet (snappy)**, partitioned by a column that queries filter on (usually date).
- **Glue Parquet writer** (`useGlueParquetWriter`): Glue's optimized writer for DynamicFrames. Can update the Catalog schema while writing **(verify details)**.
- Compression: **snappy** (fast, default for Parquet/ORC), **gzip** (smaller, not splittable for CSV/JSON), **zstd/lz4** (newer options). Gzip text files cannot be split, so one task reads the whole file.
- **Target file size**: aim for roughly **128 MB to 1 GB** per file (rule of thumb, **verify** for your engine). Too small = slow listing and many tasks. Too big = poor parallelism.
- **Small-files problem** causes: streaming jobs (many tiny batches), over-partitioning, many tiny source files. Fixes: **group files** on read, **repartition/coalesce** before write, **compaction** (Iceberg optimization, Athena `OPTIMIZE`, a Glue compaction job), larger streaming windows.
- Partition design: partition on columns used in filters, with **moderate cardinality** (date, region). **Do not** partition on a high-cardinality column (user id). Too many partitions = metadata cost + small files.
- Use **Hive-style** `key=value` folders so crawlers and engines recognize partitions.

## C. Reading many files and partitions efficiently
- **Group small files** with `groupFiles: "inPartition"` and `groupSize` (bytes). Glue **turns grouping on automatically** when there are more than **50,000** input files.
  - `groupFiles` works for **CSV, Ion, grokLog, JSON, XML**. It is **not** supported for **Avro, Parquet, ORC**.
  - `groupSize` is optional. If missing, Glue picks a size that uses all cores and reduces tasks. Give it as a number of bytes (for 1 MB: 1048576).
  - `recurse: True` reads subfolders when you give an array of paths (not needed for Parquet/ORC or key lists).
- **Pushdown predicate** (`push_down_predicate`):
  - Filters **partitions** using Catalog partition metadata, so Glue **lists and reads only needed partitions**. Works with `from_catalog`.
  - Any Spark SQL `WHERE`-style boolean expression, e.g. `"year=='2017' and month=='04'"`.
  - It is applied **after** listing all partitions from the Catalog. Fine for thousands, slower for millions.
- **Catalog partition predicate** (`catalogPartitionPredicate` in `additional_options`):
  - **Server-side** pruning using **partition indexes**. Much faster for tables with millions of partitions.
  - Different syntax from `push_down_predicate` (JSQL parser vs Spark SQL). You can use both at once.
- **Filtering after the read** (`.filter()`) reads everything first. It does not save S3 reads.
- **Bounded execution** (`boundedSize` / `boundedFiles` in read options): limits how much one run processes (for backfills or huge first runs), used with bookmarks **(verify option names)**.
- **S3 file lister** options reduce driver memory when listing very many files **(verify)**.
- A table with **Lake Formation cell-level filters** loses bookmarks, bounded execution, pushdown predicates and catalog partition predicates.

## D. Open table formats in Glue (Iceberg, Hudi, Delta)
- Enable with job parameter **`--datalake-formats`** = `iceberg`, `hudi` or `delta`.
- **Iceberg** setup (Glue 3.0+): set `--conf` Spark properties:
  - `spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions`
  - `spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog`
  - `...glue_catalog.warehouse=s3://<warehouse>/`
  - `...glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog`
  - `...glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO`
- The Glue Data Catalog is the **Iceberg catalog** (`glue_catalog`). Tables are `glue_catalog.<database>.<table>`.
- Create with Spark SQL (`CREATE TABLE ... USING iceberg`) or `df.writeTo("glue_catalog.db.table").create()`; append with `.append()`; read with `spark.read.format("iceberg").load(...)`.
- Glue creates **Iceberg v2** tables by default. Glue **6.0** supports **v2 and v3**. Upgrading v2 → v3 is **one way** (cannot downgrade). Keep v2 if another service you use cannot read v3.
- The Glue docs say **update is not supported** for Iceberg tables through the Glue read/write methods, while inserts and Spark reads/writes work. Check Spark SQL `MERGE`/`UPDATE` support for your Glue version **(verify)**.
- Glue 3.0 + Iceberg 0.13.1 needs a **DynamoDB lock manager** for safe commits. 4.0+ uses **optimistic locking** by default.
- A different Iceberg version → supply JARs with `--extra-jars` and do **not** set `--datalake-formats` (Glue 5.0+: also `--user-jars-first true`).
- **Encryption**: Iceberg tables have their own S3 SSE settings. Turn that on **in addition to** a Glue security configuration.
- Lake Formation-governed Iceberg tables: job role needs `SELECT` to read and `SUPER`-level permission to write (Glue 4.0 example). Glue 5.0+ uses the newer Lake Formation fine-grained integration.
- **Why use them**: ACID transactions, **upserts/merge**, deletes, **time travel**, schema evolution, safer concurrent writers. Plain Parquet on S3 gives none of that.
- Iceberg basics (exam): metadata/manifest files track data files; snapshots enable time travel; **compaction** fixes small files; **snapshot expiration** and **orphan file cleanup** control storage. Glue Catalog can run these as **managed table optimization** (file 2).
- Hudi and Delta Lake also give merge-on-read/copy-on-write and transaction logs. Pick by ecosystem: Iceberg is the most broadly supported by AWS analytics services.

## E. Streaming ETL
- A **streaming job** runs **continuously** and reads from **Kinesis Data Streams, Apache Kafka, or Amazon MSK**. It writes to **S3** (data lake) or **JDBC** stores. It can also write to Kinesis from scripts.
- It is Spark **Structured Streaming** under the hood, processed in **micro-batches**.
- Default **window size = 100 seconds**. A smaller window = fresher data but more small files. A larger window = fewer files and better late-data aggregation.
- Streaming jobs use **checkpoints**, **not** bookmarks. A restarted job continues from the last checkpoint. To **reprocess**, delete the checkpoint folder.
- Setup steps:
  1. For **Kafka/MSK**: create a Glue **connection** (TLS bootstrap URLs only, no plaintext). Client auth options: SASL/GSSAPI (Kerberos), SASL/SCRAM-SHA-512, SASL/PLAIN, SSL client auth, **IAM** (MSK only).
  2. **Manually create a Catalog table** for the stream (type Kinesis or Kafka; stream name/ARN or topic + connection). **Crawlers cannot create these**. You must use the Glue console/API, **not** the Lake Formation console.
  3. Create the job: type **Spark streaming**; pick the table; choose **auto-detect schema** or **define the output schema** (ApplyMapping).
- Kinesis in **another account**: provide stream ARN, an **assumed role ARN** and optional session name.
- If a streaming job has a **connection** and reads Kinesis, you need a **VPC interface endpoint** for Kinesis.
- **Schema detection** is handy, but with it on you **cannot join streaming data**.
- **Avro** streaming notes: with detection on, the payload must include the schema; off → payload has data only. Enum → string, Fixed → binary, Union → struct. Schema Registry source supports **Avro only** with inference set to false, and **Union is not supported**.
- **Grok** patterns can parse log lines into structured data in the table definition.
- **Auto decompression** for several codecs depends on the input format (for example GZIP not for Avro files, ZSTD only for Avro files).
- **Job timeout** for streaming: blank = job **restarts after 7 days** (or in the **maintenance window** if set). A value must be under 7 days. The maintenance window lets Glue restart the job at a time you choose.
- **Billing**: a streaming job is billed for **as long as it runs**, even when the stream is quiet (the AWS docs say Glue "bills hourly for streaming ETL jobs while they are running" **(verify exact granularity)**). Use **G.025X** and **Auto Scaling** to cut cost.
- Auto Scaling for streaming scales **between micro-batches** by default. A static DataFrame created **outside** `forEachBatch` and joined to a stream is not supported with auto scaling.
- Kinesis **enhanced fan-out** is supported for the job (dedicated throughput) **(verify setup)**.
- **Schema Registry change**: stop job → update Catalog table schema → restart.
- Exam angle: "continuous ETL from Kinesis/MSK to S3 with schema evolution and no servers" → **Glue streaming + Schema Registry**. "Sub-second, stateful, windowed analytics" → **Managed Service for Apache Flink**, not Glue.

## F. Zero-ETL
- **Zero-ETL integrations** are managed replication into the **SageMaker lakehouse / S3 / S3 Tables / Redshift** with **no pipeline code**.
- Sources in Glue zero-ETL: **DynamoDB**, **Oracle at AWS**, **SaaS apps** (Salesforce, SAP OData, ServiceNow, Zendesk, Zoho CRM, Facebook/Instagram Ads, Salesforce Marketing Cloud Account Engagement) and self-managed **Oracle, SQL Server, MySQL, PostgreSQL** (for self-managed databases, the **target is Amazon Redshift only**).
- Targets: general-purpose S3 bucket, **S3 Tables**, Redshift managed storage (via lakehouse), Amazon Redshift data warehouse.
- **Billing**: no integration fee. You pay **ingestion by data volume** (1 MB per request unit **(verify)**) and the compute at Redshift or Glue DPU rates. Standard S3 or Redshift storage is billed separately.
- Zero-ETL ≠ Aurora-to-Redshift zero-ETL (that is RDS/Aurora's own integration). Quotas: **40 integrations** per Region (default).
- Use zero-ETL when you only need a **fresh copy** with little transformation. Use Glue jobs when you must clean, join, mask or reshape.

## G. Performance tuning (exam skill: optimize ETL)
- Find the bottleneck first: **Spark UI**, job run **metrics**, **observability metrics** (skew, worker utilization, memory) in file 5.
- **Data skew**: one key is much bigger than the rest, so one task runs long. Check `glue.driver.skewness.job` / `.stage` (a value above 0 means max task time is over 5× the median by default). Fixes: salt the key, filter hot keys, **Spark Adaptive Query Execution** with skew join settings, repartition.
- **Too few partitions** = idle workers. **Too many tiny partitions** = scheduling overhead. Tune `spark.sql.shuffle.partitions`; with Auto Scaling Glue sets it from the maximum DPUs (override with `--conf`).
- **Shuffles** (joins, groupBy, distinct) are the costly step. Reduce data **before** the shuffle (filter, select needed columns). **Broadcast** the small side of a join.
- Prefer **built-in Spark/DataFrame functions** over Python **UDFs** (UDFs are slow, row-by-row through Python).
- Use **Parquet/ORC** and **column pruning**. Read only needed columns.
- **Executor out of memory** ("Container killed by YARN for exceeding memory limits"): bigger worker (G.2X/G.4X), **R** memory-optimized worker, more partitions (smaller tasks), reduce skew.
- **Driver out of memory**: too many files/partitions listed (use grouping, file lister, bookmarks tuning), `collect()`/`toPandas()` on big data, huge broadcast.
- **Disk full** ("No space left on device"): large shuffle spills. Bigger worker (more disk), fewer/larger partitions, or reduce shuffle volume.
- **Capacity planning**: Glue shows `numberMaxNeededExecutors` in CloudWatch to estimate how many executors the job could use. Do not buy more workers than that.
- **Cache** (`df.cache()`) only for data reused several times.
- **Startup time**: Glue 3.0+ starts in about a minute or less for G.1X/G.2X **(verify)**. The big types (G.12X, G.16X, R) start slower. Flex starts slower still.
- **Write performance**: avoid `repartition(1)` on big data (one writer). Control file count with `coalesce` / `repartition` and partition columns.
- **JDBC reads/writes** are limited by the database. Parallel reads and batch writes help, but too many connections can overload RDS. Throttle workers or use **RDS Proxy** **(verify)**.
- **Cost-performance**: bigger worker ≠ faster if the job is skew- or IO-bound. Measure with **DPU-hours** (DPUSeconds) not just run time.
- Prefer **incremental** processing (bookmarks, partitions, Iceberg incremental reads) over full reprocessing every run.

## H. Handling bad data and schema drift
- **Choice types** appear when a field has mixed types. Resolve with `resolveChoice` (`cast`, `make_cols`, `make_struct`, `project`, `match_catalog`).
- **Error records**: the `errorsAsDynamicFrame()` method returns records that failed a transform, so you can route them to a quarantine S3 prefix **(verify method name)**.
- **Schema evolution**: crawlers handle simple column adds. For safe evolution use **Iceberg** (add/rename/drop columns) and **Schema Registry** for streams.
- Add **Data Quality** rules to stop bad data before it enters the lake (file 4).
- Use `DropNullFields`, `Filter` and `ApplyMapping` to clean. Remember `ApplyMapping` drops unlisted columns.
- **Mask / detect PII** with the Detect Sensitive Data transform (file 4) before writing to a shared zone.

## I. Patterns you should recognize
- **Raw → curated** lake: land raw files in S3 (bronze) → Glue job cleans, converts to Parquet, partitions (silver) → aggregates/joins to serving tables (gold) → Athena/Redshift/QuickSight.
- **Database to lake**: DMS (full load + CDC) to S3 → Glue merges changes into **Iceberg** tables (upsert/delete). Or **zero-ETL** for supported sources.
- **Lake to warehouse**: Glue job or Redshift `COPY`/Spectrum loads curated data into Redshift. Glue reads/writes Redshift via the S3 temp path.
- **Stream to lake**: Kinesis/MSK → Glue streaming job → S3 (Parquet) → Catalog table for Athena.
- **Orchestration**: EventBridge/S3 event → Glue workflow or Step Functions → job → crawler or catalog update → notify (file 4).
- **Small, simple transforms** may be cheaper in **Lambda** or **Athena CTAS**. Choose Glue when Spark scale or Catalog integration matters.

## J. Scenarios (if → then, because)
- **If** a job reads millions of small CSV files and is slow, **then** set **`groupFiles: "inPartition"`** with **`groupSize`** (in bytes), or compact the files. **This works because** with many tiny files, task and listing overhead is bigger than the real work, and grouping reads many files in one task. Glue turns grouping on by itself above **50,000** files. It works for CSV, JSON, XML, Ion and grokLog, but not for Parquet, ORC or Avro.
- **If** a table has **5 million** partitions and listing is slow, **then** use **`catalogPartitionPredicate`** with **partition indexes**. **This works because** it prunes partitions on the server using the indexes, while **`push_down_predicate`** first lists all partitions from the Catalog and then filters. You can use both at once, but they use different syntax.
- **If** you need only last week's data from a date-partitioned table, **then** read with `from_catalog` and a **pushdown predicate** (`push_down_predicate`) on the date partitions. **This works because** Glue then lists and reads only the matching folders. A `.filter()` after the read would read everything first.
- **If** Parquet files are tiny after a streaming job, **then** increase the **window size** (default **100 seconds**) or add a **compaction** step (for example Apache Iceberg table optimization). **This works because** each micro-batch writes files, so a small window makes many small files, which slow queries. Compaction merges them into bigger files.
- **If** one task runs **10×** longer than the rest, **then** you have data **skew**: check the skewness metrics (`glue.driver.skewness.stage` / `.job`), **salt** the hot key, or enable Spark Adaptive Query Execution (AQE) skew-join settings. **This works because** one key is much bigger than the others, and the whole stage waits for the slowest task. A skewness value above 0 means the max task time is over 5× the median.
- **If** executors die with "Container killed by YARN for exceeding memory limits", **then** use larger (G.2X/G.4X) or **R** (memory-optimized) workers, or more partitions. **This works because** each task holds too much data in memory: a bigger worker gives more memory, and more partitions make each task smaller. Fixing skew also helps.
- **If** the **driver** runs out of memory while listing Amazon S3, **then** group files, reduce files per partition, and use bookmarks with well-designed partitions. **This works because** the driver holds the whole file list, so fewer, bigger files and fewer listed partitions shrink it.
- **If** a job must upsert database changes into the lake, **then** use **Apache Iceberg** tables on the Glue Data Catalog with Spark SQL `MERGE INTO` **(verify)**. A common pattern: AWS Database Migration Service (DMS) lands full load + change data capture (CDC) in S3, then Glue merges it. **This works because** plain Parquet on S3 has no row-level updates, while Iceberg gives ACID transactions, upserts and deletes. Catch: the Glue docs say update is not supported through Glue's own read/write methods, so check `MERGE` support for your Glue version.
- **If** you need point-in-time queries on a lake table, **then** use Apache Iceberg **time travel**. **This works because** Iceberg keeps **snapshots** of the table, so you can query an older one. Snapshot expiration controls how much history, and storage, you keep.
- **If** you must copy Salesforce or SAP data into the lakehouse with no code, **then** use a **Glue zero-ETL integration** (or Amazon AppFlow). **This works because** zero-ETL is managed replication with no pipeline code and no integration fee; you pay ingestion by data volume plus target compute. Use Glue jobs instead if the data must be cleaned, joined or masked.
- **If** an Amazon Redshift read/write job fails after about **1 hour** with a token error ("S3 service token expired"), **then** split the work into shorter jobs or re-establish credentials. **This works because** Glue moves Redshift data through an Amazon S3 temp path (`UNLOAD` to read, `COPY` to write), and the temporary S3 credentials expire after **1 hour**.
- **If** a job fails while reading partitions stored in **S3 Glacier / Deep Archive**, **then** exclude those storage classes with **`excludeStorageClasses`** in the read options. **This works because** Glue cannot read archived objects and fails with "The operation is not valid for the object's storage class".
- **If** queries on JSON/CSV data are slow and costly, **then** convert the data with a Glue job to **Parquet** (snappy) partitioned by date. **This works because** Parquet is columnar, so engines read only the needed columns, and date partitions let them skip folders. Both cut the data scanned.
- **If** the streaming source is Apache Kafka on Amazon Managed Streaming for Apache Kafka (MSK) with IAM auth, **then** create a Glue **Kafka connection** with **IAM** client authentication. **This works because** Kafka sources always need a Glue connection with TLS bootstrap URLs (plaintext is not supported), and IAM is one of its client auth options, for MSK only.
- **If** a streaming table must follow a producer's schema changes, **then** base the table on the **Glue Schema Registry**, and for each new version **stop** the job, **update** the Catalog table schema, and **restart** it. **This works because** the job reads the table schema when it starts. A Schema Registry source supports **Avro only**, with schema inference set to false.
- **If** a streaming job has work for only a few minutes a day, **then** use a **batch** job with bookmarks instead, or Firehose to Amazon S3. **This works because** a streaming job is billed for as long as it runs, even when the stream is quiet.
- **If** ETL needs sub-second, stateful, windowed analytics, **then** use **Amazon Managed Service for Apache Flink**, not Glue. **This works because** Glue streaming is Spark Structured Streaming in **micro-batches** (default window 100 seconds), so it cannot give sub-second results.
- **If** Glue is too heavy for a **2-minute** task, **then** use **AWS Lambda**. **This works because** Lambda starts faster and costs less for small work, while Glue has Spark startup time and data processing unit (DPU) billing. Athena `CREATE TABLE AS SELECT` (CTAS) can also be cheaper for small SQL transforms.

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: partition management and pushdown/catalog predicates, grouping input files, streaming ETL (sources, window, checkpoints, restrictions), Iceberg in Glue (versions, config, v3), auto scaling, zero-ETL sources and targets, troubleshooting errors (S3 storage class, s3a, token expiry, bookmarks), observability metrics (skewness).
Not confirmed (verify): JDBC parallel-read option names, DynamoDB read options, `useGlueParquetWriter` details, target file size guidance, bounded execution option names, S3 file lister option names, error-record method name, streaming billing wording, enhanced fan-out setup, startup-time numbers, connector list, RDS Proxy advice, Iceberg `MERGE` support specifics in each Glue version.

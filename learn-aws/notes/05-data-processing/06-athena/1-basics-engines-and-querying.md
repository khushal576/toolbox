# Athena – 1. Basics, engines and querying

Short notes. Each point is a fact you can be asked about.

## A. What Athena is, when to pick it
- **Athena** = serverless, interactive SQL on data in **S3** (and, with connectors, other sources). No cluster, no load step. You define a table over S3 files and query it.
- You pay for the work done (bytes scanned, or DPU-hours). Nothing to pay when idle.
- Two engines in one service:
  - **Athena SQL** (Trino-based; **engine version 3** is the current one).
  - **Athena for Apache Spark** (notebooks / sessions, Python). Different workgroup type.
- Pick Athena when:
  - Ad hoc or occasional SQL on S3 (logs, CSV/JSON/Parquet exports, data lake exploration).
  - You want "least operational overhead" for queries.
  - You need a quick check of data quality or a one-off join across S3 and another source (federated query).
- Avoid / pick something else when:
  - Many concurrent BI users with sub-second SLAs and heavy joins across big tables → **Redshift** (data warehouse, tuned storage and caching).
  - Custom code, ML, streaming, Hadoop tools, long jobs → **EMR** or **Glue**.
  - Scheduled ETL with job bookmarks, many transforms → **Glue**.
  - Row-level OLTP lookups → DynamoDB / RDS, not Athena.
- **Athena vs Redshift Spectrum**: both query S3 with SQL. Spectrum needs a Redshift cluster/workgroup and can join S3 with local warehouse tables. Athena needs no cluster.
- **Athena vs S3 Select**: S3 Select is **closed to new customers**. Use Athena (or Parquet + Athena) instead. Athena reads whole tables or partitions; S3 Select filtered one object.
- **Athena vs EMR**: EMR = full control of frameworks and code. Athena = SQL only (plus Spark notebooks), fully managed.
- Athena can query data that EMR or Glue wrote. Its catalog is **Hive-metastore compatible**, so Hive DDL mostly works.
- Integrations: Glue Data Catalog (metadata), Lake Formation (permissions), QuickSight / Amazon Quick (BI), JDBC/ODBC (SQL clients), Step Functions, EventBridge, CloudWatch, SageMaker Unified Studio, EMR Studio.

## B. How a query runs (the model)
- You submit SQL → Athena plans it → reads **metadata** from the catalog (Glue Data Catalog by default) → reads **data** from S3 in parallel → writes **results** to an S3 results location (CSV) → you fetch results.
- Athena does **not store your data**. It reads S3 each time. Data and metadata are separate (table = schema + pointer to S3 prefix).
- **Schema-on-read**: dropping an **external** table drops only the metadata. The S3 files stay.
- A query can be **queued** before it runs. Queued + running queries count against the account quota.
- Athena **scales out**, not up. A query that needs too much memory per node fails with "Query exhausted resources at this scale factor". Rewriting the query is the fix, not a bigger size.
- Query execution is **not deterministic**: the same query can fail once and succeed later (data skew, timing).
- Athena **may retry** failed queries internally for transient errors. The query still ends as `SUCCEEDED`, but partial output from the failed try may be left in S3.
- Query states: `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`.
- Statement types: **DDL** (CREATE TABLE, ALTER TABLE ADD PARTITION), **DML** (SELECT, CTAS, INSERT INTO), **UTILITY** (SHOW, DESCRIBE).
- CTAS is technically DDL + DML, but counts as **DML** for quotas.

## C. Workgroups (the control unit)
- **Workgroup** = a named set of settings for queries. Every account has a **`primary`** workgroup (cannot be deleted).
- What a workgroup holds:
  - Query **results location** and encryption.
  - **Engine version** (SQL) or Spark config.
  - **Data usage controls** (per-query limit, per-workgroup alerts).
  - **CloudWatch metrics** switch.
  - **Query history** and saved queries (kept per workgroup).
  - Tags (for cost allocation, IAM conditions).
- Workgroups are **IAM resources**. You can allow a team to use only its workgroup.
- Up to **1,000 workgroups per Region** per account. Up to **1,000 prepared statements** per workgroup. Up to 50 tags per workgroup.
- **Override client-side settings**: when on, workgroup settings (results location, encryption, expected bucket owner) win over whatever the client or JDBC driver sends. The query still runs, but with the workgroup's settings.
- A workgroup can be **disabled**, which blocks queries in it. Use it as a kill switch.
- Engine version is set **per workgroup**. Default is **auto upgrade**. You can pin a version, but Athena still upgrades you when a version is retired. Test queries first in a test workgroup on the new version.
- Athena for Spark needs a **Spark-enabled workgroup**. Spark workgroups use the notebook editor, not the SQL query editor.
- A workgroup can be attached to a **capacity reservation** (provisioned DPUs). See file 4.
- Workgroup quotas are **shared** at the account level. Workgroups do not give extra concurrency by themselves.

## D. Data catalogs and names
- Default catalog: **`awsdatacatalog`** = the **Glue Data Catalog**. Reserved names you cannot use for your own data source: `awsdatacatalog`, `hive`, `jmx`, `system`.
- Full name form: `"catalog"."database"."table"`. Default catalog can be left out.
- Other catalog types: external **Apache Hive metastore** (via Lambda connector), and **federated** catalogs (file 3).
- Table names, column names: lowercase letters, numbers, underscore are safe. Glue is **case-insensitive and stores lowercase**. Reserved words must be escaped (backticks in DDL, double quotes in SELECT).
- **Hidden files**: files starting with `_` or `.` are ignored by Athena. Rename them if they hold data.
- **Zero-byte `_$folder$` objects** are created by some tools and can confuse listings. Remove them.
- Glue **crawlers** are the usual way to create tables automatically. Athena does not understand a crawler's **exclude patterns** (it still reads the excluded files). Put files you do not want queried in another prefix.
- Crawler with a **custom JSON classifier** creates tables Athena cannot query. Use a normal table or CTAS.
- Tables made with the Glue `CreateTable` API or CloudFormation need `TableType` (`EXTERNAL_TABLE` or `VIRTUAL_VIEW`), or DDL like `SHOW CREATE TABLE` fails with "NullPointerException Name is null".

## E. DDL basics
- `CREATE EXTERNAL TABLE ... LOCATION 's3://bucket/prefix/'` points to a **prefix**, not a file. All files under it (recursively) are read, except hidden ones.
- The `LOCATION` should end with `/`. Mix of file formats or schemas under one prefix causes errors or garbage.
- **`ROW FORMAT SERDE`** tells Athena how to parse text. Pick correctly:
  - **LazySimpleSerDe** → CSV/TSV/custom delimiter, no quoted fields.
  - **OpenCSVSerde** → CSV with quoted values. It treats **every column as string** in practice (cast in queries). Does not support `array`.
  - **OpenX JSON SerDe** / **Hive JSON SerDe** → JSON, **one record per line**, not pretty-printed.
  - **Regex SerDe**, **Grok SerDe** → log files (Apache, Logstash).
  - **Parquet / ORC / Avro SerDes** → columnar and row formats (use `STORED AS PARQUET`).
  - **Ion SerDe** → Amazon Ion.
- JSON traps:
  - Pretty-printed JSON → `HIVE_CURSOR_ERROR: Row is not a valid JSON Object`.
  - `SELECT COUNT(*)` returns 1 when records are not newline separated.
  - `ignore.malformed.json = true` returns bad lines as NULL (good for finding them).
  - Column declared `map`/`struct` but data is a primitive → `HIVE_BAD_DATA` class cast error.
- CSV traps:
  - Header row is **read as data** unless you set `skip.header.line.count` = 1 in `TBLPROPERTIES`.
  - UTF-8 **BOM** in a CSV crawled by Glue produces a column name with `?` and "Column cannot be resolved".
  - Integer column with empty values → `HIVE_BAD_DATA`. Declare as string, then `CAST` with a default.
- **TIMESTAMP** columns need Java timestamp format (`yyyy-MM-dd HH:mm:ss[.fff]`). The OpenCSV SerDe accepts UNIX numeric timestamps. Wrong format → empty results.
- `INT` is 32-bit. A bigger number → "Value exceeds MAX_INT". Use `BIGINT`.
- Partition column types: use **string** (file 2).
- `ALTER TABLE ADD COLUMNS`, `ALTER TABLE SET TBLPROPERTIES`, `DROP TABLE` (external: metadata only), `SHOW CREATE TABLE`, `DESCRIBE`, `SHOW PARTITIONS` exist. **No** stored procedures, no `CREATE TABLE LIKE`, no `DESCRIBE INPUT/OUTPUT`.
- `UPDATE` and `DELETE FROM` do **not** work on plain Hive tables. They work only on **Iceberg** (and `MERGE` only on transactional formats). See file 2.
- Limits to remember: one row/column value max **32 MB**; one line in a text file max **200 MB**; functions max **127** arguments; array literal max **254** items; `ORDER BY ... LIMIT` max 2,147,483,647 rows.

## F. Views, prepared statements, UDFs
- **Views** are saved queries stored in the Glue catalog (Athena-specific). They store **no data**.
  - A view becomes **stale** if the table underneath changes or is dropped ("view is stale; it must be re-created").
  - Views made in the **Hive shell** do not work in Athena (and the other way). Re-create them in Athena.
  - Views cannot use **partition projection** from their own properties. Set projection on the base table.
  - Views on **federated** sources are supported (stored in Glue, not in the source). See file 3.
- **Prepared statements** (`PREPARE`, `EXECUTE ... USING`) keep parameterized SQL in the workgroup. Good against SQL injection from apps. Access can be restricted with IAM. Max 1,000 per workgroup.
- **UDFs**: write a **Lambda** function and call it from SQL (`USING EXTERNAL FUNCTION`). Needs permission to invoke the Lambda. Runs row batches, so it is slower than built-in functions.
- **ML in queries**: call a SageMaker endpoint from SQL (`USING EXTERNAL FUNCTION ... SAGEMAKER`) (verify current status).
- Built-in functions come from the Trino library (`approx_distinct`, `max_by`, `regexp_extract`, `UNNEST`, window functions, `date_parse`, etc.).

## G. Getting results out
- Every query writes its result to the **query results location** (an S3 prefix) as **one uncompressed CSV file** plus a `.metadata` file. The write is **not parallel**.
- Results location is set per workgroup (or per client). The bucket must be in the **same Region** as the query or you get "The S3 location provided to save your query results is invalid".
- Results files are **not deleted** by Athena. Add an S3 lifecycle rule (also abort incomplete multipart uploads).
- **Managed query results**: pick "Athena managed" on the workgroup and you need no results bucket.
  - Results are kept **24 hours** and deleted automatically. No extra cost.
  - Encrypted with an AWS owned key by default, or your customer managed key (key policy must allow service principal `encryption.athena.amazonaws.com` with `kms:Decrypt`, `kms:GenerateDataKey`, `kms:DescribeKey`).
  - Access is per workgroup via `GetQueryResults` and `GetQueryResultsStream`.
  - Console download limit is **200 MB**. Use `UNLOAD` for bigger.
  - **Not compatible with query result reuse.**
- **UNLOAD**: writes a SELECT result to S3 in `PARQUET`, `ORC`, `AVRO`, `JSON` or `TEXTFILE`, **in parallel**, without creating a table.
  - Best for large result sets, or when a downstream app needs non-CSV.
  - Options: `format` (required), `compression`, `compression_level` (ZSTD only), `field_delimiter`, `partitioned_by`.
  - The target prefix must be **empty** (it will not overwrite). With `partitioned_by` it can be re-run into existing partitions.
  - Max **100** partitions. Partition columns must be **last** in the SELECT list.
  - Files are not sorted globally. A manifest and metadata file are written to the results location.
  - Counts as a DML query. The "expected bucket owner" setting does **not** apply to the UNLOAD target.
  - Failure leaves **orphan files**; Athena does not clean them.
- **CTAS** (`CREATE TABLE AS SELECT`): creates a new table and writes the data files to S3.
  - Default format **Parquet**. Choices: PARQUET, ORC, AVRO, JSON, TEXTFILE.
  - Compression: Parquet `GZIP`(default)/`SNAPPY`/`ZSTD`; ORC `ZLIB`(default)/`SNAPPY`/`LZ4`/`ZSTD`; JSON/TEXTFILE `GZIP`.
  - Can set `partitioned_by`, `bucketed_by` + `bucket_count`, `external_location`, `format`, `write_compression`.
  - `external_location` must be an **empty** prefix. If the workgroup overrides settings, the table lands in `<results-location>/tables/<query-id>/`.
  - Limit: **100 partitions** per CTAS. Error: `HIVE_TOO_MANY_OPEN_PARTITIONS: Exceeded limit of 100 open writers`.
  - Workaround: CTAS the first 100 partitions with a `WHERE`, then `INSERT INTO` in batches of ≤100 partitions with **non-overlapping** filters.
  - `ORDER BY` in the SELECT part of a CTAS is **ignored**.
  - Column types are preserved from the SELECT.
  - A failed CTAS/INSERT can leave **orphaned files** that later queries read as data. Use the query's data manifest to find them. Concurrent CTAS to the same location duplicates data (no locking).
  - Use CTAS to convert CSV/JSON → Parquet/ORC (the cheapest ETL), to materialize repeated aggregations, or to migrate to Iceberg.
- **INSERT INTO** appends rows to an existing table. Max **100 partitions** written per statement. Not supported on federated sources.
- Failed or cancelled queries can leave partial multipart uploads. Add an S3 lifecycle rule to abort incomplete multipart uploads.

## H. Query result reuse
- Per-query switch "reuse query results" with a **max age**. Default **60 minutes**, max **7 days**.
- Athena returns a previous identical query result instead of scanning again: no bytes scanned, no cost, faster.
- Conditions for reuse (all must hold):
  - Same workgroup.
  - Query string matches (comments/whitespace ignored for strings under 100 KB), same catalog and database.
  - Previous result not older than max age; same result configuration.
  - You can read the tables and the previous result file in S3.
- **Not** reused when:
  - Query uses **federated** catalogs or an external Hive metastore, or more than one data catalog.
  - Table has **Lake Formation** fine-grained controls, or its location is registered in Lake Formation.
  - Query has more than **20 tables**.
  - Non-deterministic functions (`rand()`, `shuffle()`); `LIMIT` without `ORDER BY`.
  - The workgroup uses **managed query results**, or overrides the result config at query level.
  - Statement is not `SELECT` / `EXECUTE`.
- Catch: results can be **stale**. Athena does not check source changes until max age ends.
- Needs JDBC driver ≥ 2.0.34.1000 / ODBC ≥ 1.1.19.1002.
- Great for dashboards where many users open the same query.

## I. Athena for Apache Spark
- Run **Spark (PySpark)** interactively without clusters. Use **notebooks** (Athena console, or SageMaker Unified Studio) or Spark Connect clients.
- Release versions:
  - **PySpark engine version 3**: Athena console notebooks, Calculation APIs.
  - **Apache Spark 3.5**: only through SageMaker Unified Studio notebooks / Spark Connect clients; **no** console notebooks, **no** Calculation APIs. A workgroup cannot be upgraded from engine v3 to Spark 3.5.
- Used for: Spark DataFrame work on S3 data, Iceberg/Hudi/Delta via Spark, ETL-like exploration, Python libraries for data cleaning, and the exam item "Athena notebooks with Spark".
- Billed in **DPU-hours** (about **$0.35 per DPU-hour**, worker + driver), not bytes scanned.
- Limits worth knowing:
  - PySpark engine v3: **no Lake Formation**, **no partition projection tables**, no MLlib, no `pip install`, one active session per notebook.
  - Spark 3.5: on-demand DPUs per account default **4** (adjustable); total Spark DPU concurrency **160** per Region.
  - Views are **not** shared between Athena SQL and Athena Spark (different implementations).
- Capacity reservations do **not** support Spark workgroups.
- Spark workgroups are separate from SQL workgroups; they cannot use the SQL query editor.
- Encryption, VPC endpoint for Spark sessions and Lake Formation integration are separate settings for Spark (verify the per-version support).

## J. Scenarios: If X → Y, because Z
- **If** a team needs a quick SQL check on **50 GB** of CSV logs already in **Amazon Simple Storage Service (S3)**, **then** use **Amazon Athena**, the serverless SQL service that queries files in S3 directly. You define a table over the S3 prefix and run SQL; there is no cluster to build and no load step. **This works because** Athena reads S3 on each query and you pay only for the work done (**bytes scanned**), with nothing to pay when idle.
- **If** the same CSV data is queried every day and the bill is high, **then** use **CREATE TABLE AS SELECT (CTAS)** to rewrite it once as **Parquet** (or **ORC**) files with **partitions**. Parquet and ORC are columnar formats: a query reads only the columns it needs, data compresses well, and min/max stats let Athena skip data. Partitions (for example by date) let a `WHERE` read only the matching S3 prefixes. **This works because** Athena charges by **bytes scanned**, and columnar files plus compression plus partitions cut those bytes. CTAS is the cheapest way to do this conversion inside Athena.
- **If** a dashboard runs the same SQL every minute, **then** turn on **query result reuse** with a **max age** (default **60 minutes**, max **7 days**). **This works because** Athena returns the earlier result of an identical query in the same workgroup instead of scanning again, so a repeat costs nothing and returns fast. The catch: results can be **stale**, since Athena does not check the source for changes until the max age ends.
- **If** one app needs the full result of a huge query as **Parquet**, **then** use **`UNLOAD`**, which writes a SELECT result to S3 in Parquet, ORC, Avro, JSON or text, **in parallel**, without creating a table. **This works because** the normal query result is **one uncompressed CSV file** written by one writer (not in parallel), which is slow for big results and the wrong format. The target prefix must be **empty**, and a failed UNLOAD leaves orphan files that Athena does not clean up.
- **If** a CTAS fails with `HIVE_TOO_MANY_OPEN_PARTITIONS` ("Exceeded limit of **100** open writers"), **then** split the work: run the CTAS with a `WHERE` that covers the first **100** partitions, then run several **`INSERT INTO`** statements, each covering **≤100** partitions with **non-overlapping** filters. **This works because** **100 partitions per statement** is a hard limit for both CTAS and INSERT INTO, while many statements in a row can together write any number of partitions. Non-overlapping filters stop rows from being written twice.
- **If** a user cannot see another user's queries, **then** check the **workgroup** (a named set of query settings) and the **catalog**. **Query history and saved queries are kept per workgroup**, so a user in a different workgroup will not see them. Tables are different: they live in the shared **AWS Glue Data Catalog**, so a missing table usually means a different catalog or database, or missing permissions. **This works because** workgroups separate history, while the catalog is shared by the account.
- **If** you want to avoid creating and cleaning up a query results bucket, **then** choose **managed query results** ("Athena managed") on the workgroup. **This works because** Athena keeps the results for **24 hours** and deletes them automatically, at **no extra cost**. The catch: the console download limit is **200 MB** (use `UNLOAD` for bigger), and it does not work with query result reuse.
- **If** a view stopped working after its table changed or was dropped, **then** **re-create the view**. **This works because** an Athena view is only a saved query stored in the Glue catalog, holding no data, so it goes **stale** ("view is stale; it must be re-created") when the table under it changes.
- **If** you need to update or delete single rows of data in S3, **then** use an **Apache Iceberg** table (file 2), an open table format that Athena can fully read and write. **This works because** `UPDATE` and `DELETE FROM` do **not** work on plain Hive tables; there you can only add rows (`INSERT INTO`). On Iceberg they work, and `MERGE` works only on transactional formats like it.
- **If** a data scientist wants **PySpark** on the data lake without running a cluster, **then** create a **Spark-enabled workgroup** and use **Athena for Apache Spark** notebooks. **This works because** Athena runs Spark serverlessly: you get interactive sessions without managing clusters, billed in **DPU-hours** (Data Processing Unit hours, about **$0.35 per DPU-hour** (verify)) instead of bytes scanned. Spark workgroups are separate from SQL workgroups and use the notebook editor, not the SQL query editor.
- **If** a team runs heavy joins on many terabytes (TB), with many users and strict response times, **then** use **Amazon Redshift**, the data warehouse (or **Amazon EMR** for custom code and long jobs). **This works because** Redshift has tuned storage and caching built for many concurrent business intelligence (BI) users and sub-second results, while Athena reads S3 fresh each time and, on demand, shares account-level quotas, so it suits ad hoc queries rather than heavy, repeated warehouse work.

## Verified from AWS docs on 2026-10-25
Read from current Athena User Guide pages: What is Athena, When should I use Athena, Service Quotas (+ General Reference quotas table), workgroups, override settings, data usage controls, managed query results, query result reuse, CTAS considerations, UNLOAD, supported SerDes, other notable limitations, engine versioning, Spark considerations, troubleshooting.
Not confirmed (verify): SageMaker ML-in-SQL status, exact Spark workgroup encryption/VPC support per version, whether engine version 2 is fully retired, Athena Spark price in all Regions ($0.35 is the us-east-1-style page value), crawler exclude-pattern behaviour on newer versions.

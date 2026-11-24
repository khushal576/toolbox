# Redshift – 3. Getting data in and out: COPY, auto-copy, UNLOAD, Spectrum, federated queries, streaming, zero-ETL, data sharing, Data API

Short notes. Each point is a fact you can be asked about.

## A. Ways to load data (verified overview)
| Method | Use it when |
|---|---|
| **COPY** from S3 | Bulk batch loads; the main and most efficient way |
| **Auto-copy (COPY JOB)** | New files land in S3 and should load automatically |
| **INSERT … SELECT from external (Spectrum) tables** | Load from Glue Catalog / Iceberg / Hudi / Delta; need partial rows, column picks, light transforms |
| **Streaming ingestion** | Kinesis Data Streams or MSK data straight into Redshift (no S3 landing) |
| **Zero-ETL integration** | Continuous replication from Aurora, RDS, DynamoDB, apps |
| **Federated query + INSERT** | Pull from RDS/Aurora live without a pipeline |
| **Query editor v2 load** | Visual loading, or upload a local file |
| **INSERT/UPDATE row by row** | Avoid for bulk (much slower than COPY) |
| **AWS DMS / Glue / third-party ETL** | Migration or complex ETL (verify details) |
- Rule: **COPY is the most efficient**; INSERT is much less efficient.
- After large loads run **VACUUM** (if needed) and **ANALYZE**.

## B. COPY command (verified + best practices)
- `COPY table FROM 's3://bucket/prefix' IAM_ROLE '...' FORMAT ...` loads **in parallel across all slices**.
- Sources: **S3** (main), also EMR, DynamoDB, remote hosts via SSH (older). Cross-service access uses an **IAM role** attached to the cluster/namespace (up to **50 roles** per cluster).
- Formats: CSV/delimited text, fixed-width, **JSON**, **Avro**, **Parquet**, **ORC**, plus compressed files (gzip, bzip2, lzop, zstd).
- Best practices:
  - **Split into many files** (a multiple of the number of slices; roughly equal size, about 1 MB–1 GB compressed) so every slice has work. One huge file = one slice working.
  - **Compress** files.
  - Use **one COPY for many files** (a prefix or a **manifest** file) instead of many COPYs.
  - Use a **manifest** to load an exact list of files and to fail if one is missing.
  - Use **columnar formats** (Parquet/ORC) when possible.
  - Load in **sort key order** to reduce VACUUM.
  - Use a **staging table** then merge into the target.
  - Keep the bucket in the **same Region** as the cluster, or specify `REGION`.
- Single row max when loading by COPY: **64 MB** (a SUPER object inside a row max 16 MB).
- Errors: `STL_LOAD_ERRORS` / `SYS_LOAD_ERROR_DETAIL`; history in `SYS_LOAD_HISTORY`; `STL_LOAD_COMMITS`. Use `MAXERROR` to tolerate bad rows.
- `COMPUPDATE`/`STATUPDATE` options control automatic compression analysis and statistics on load.
- Encrypted source data: SSE-S3 and SSE-KMS work; client-side encryption supported with keys; (SSE-C support – verify).
- `NOLOAD` validates files without loading.
- Redshift tracks nothing for a plain COPY: running it twice **loads duplicates** (auto-copy tracks files; plain COPY does not).

## C. Auto-copy from S3 (COPY JOB) (verified)
- `COPY … JOB CREATE job_name AUTO ON;` — Redshift detects **new files** under the S3 path and runs COPY **automatically**, tracking loaded files to **avoid duplicates**.
- Needs an **S3 event integration** (source bucket → target cluster/namespace) created first.
- Requirements:
  - S3 **bucket policy** allowing `redshift.amazonaws.com` (`s3:GetBucketNotification`, `PutBucketNotification`, `GetBucketLocation`) with `aws:SourceArn`/`SourceAccount` conditions.
  - Cluster IAM role with `s3:GetObject` and `s3:ListBucket`.
  - Redshift **resource policy** allowing the integration (`AuthorizeInboundIntegration`, `CreateInboundIntegration`).
  - Bucket and Redshift in the **same Region**; bucket name **without a period**.
- Limits: **200** COPY JOBs per cluster/workgroup; **50** S3 event integrations per target; **one** integration per bucket–target pair; no existing `S3_OBJECT_CREATED` notifications on the bucket (narrow prefixes allowed later).
- Monitor: `SYS_COPY_JOB`, `SYS_COPY_JOB_DETAIL`, `SYS_COPY_JOB_INFO`, `SVV_COPY_JOB_INTEGRATIONS`.
- Deleting the integration sets the job inactive but does **not drop** the job.
- Serverless restore to the same namespace keeps integrations and re-ingests missed files.
- Use auto-copy instead of building S3 → Lambda → COPY pipelines.

## D. UNLOAD (export)
- `UNLOAD ('select …') TO 's3://…' IAM_ROLE '…'` writes query results to S3, **in parallel**, one or more files.
- Formats: text/CSV, **Parquet** (columnar; good for lake), JSON (verify). Options: `PARTITION BY` (Hive-style folders), `MANIFEST`, `GZIP`, `PARALLEL`, `ENCRYPTED`, `MAXFILESIZE`.
- Use cases: archive cold data to S3 then query with Spectrum/Athena; feed ML/other systems; copy data between clusters or Regions.
- **Data lifecycle pattern**: keep recent "hot" data in Redshift, **UNLOAD old data to S3 (Parquet, partitioned)**, query both with **Spectrum**.

## E. Redshift Spectrum / data lake queries (verified)
- Query **files in S3 without loading** them, using **external schemas/tables**. Heavy scanning happens in the Spectrum layer (on RA3; RG has an integrated data lake engine).
- Metadata comes from **AWS Glue Data Catalog** (or Athena catalog, or Hive metastore). Create `CREATE EXTERNAL SCHEMA … FROM DATA CATALOG` then external tables.
- Supported formats: Parquet, ORC, JSON, Avro, CSV/text, Ion, Hudi, Delta (read), **Apache Iceberg** tables, and **Amazon S3 Tables**.
- Several clusters can query the **same S3 data** at once with no copies.
- **Read-only**: you cannot COPY or INSERT into an external table (but you can `INSERT INTO local SELECT FROM external` and `UNLOAD` to write files).
- Billing: **per bytes scanned**, rounded up to the next MB, **10 MB minimum per query** (like Athena). Use **usage limits** to cap Spectrum scanning.
- Requirements/limits:
  - S3 data must be in the **same Region** as the cluster.
  - Needs an **IAM role** (S3 + Glue/Lake Formation access).
  - You must filter on the **partition column** to avoid scanning all partitions (`WHERE ship_yyyymm = '201804'`, not a function on another column).
  - Max **100 partitions** added per single `ALTER TABLE` statement.
  - Columns per external table: up to 1,600 (1,597 with pseudocolumns).
  - **No external compression for ORC**.
  - ION/JSON timestamps must be ISO8601.
  - Concurrency scaling does not cover queries that need restricted network resources.
- Performance tips: **Parquet/ORC**, **partition** by common filters (date), **compress**, use large files (about 128 MB+), push filters, keep statistics (`numRows` table property), join small local tables to large external ones.
- **Redshift Spectrum + Lake Formation**: Lake Formation permissions can govern external tables (fine-grained, column/row, tag-based). Spectrum respects them.
- **Materialized views on external tables** can speed up Spectrum queries.
- Spectrum vs Athena: both read S3 via Glue Catalog and charge per TB scanned. Use Spectrum when you want to **join lake data with warehouse tables** in one SQL statement.

## F. Federated queries (verified)
- Query **live data in operational databases** from Redshift: **RDS/Aurora PostgreSQL** and **RDS/Aurora MySQL**.
- Redshift connects from the **leader node** to read metadata, then compute nodes send **subqueries with predicate pushdown** and fetch result rows; computation is partly pushed to the remote DB to cut data movement.
- Setup: **Secrets Manager** secret with DB credentials + **IAM role** for the cluster + `CREATE EXTERNAL SCHEMA … FROM POSTGRES/MYSQL …`.
- Uses: blend live operational data with warehouse/S3 data; **load without ETL** (`INSERT INTO local SELECT FROM remote`); transform on the fly.
- Logged in `SVL_FEDERATED_QUERY` (PostgreSQL).
- Limits: data-type differences, performance depends on the source DB; heavy use can load the OLTP database (consider a **read replica**). Network path between Redshift and DB needed (same VPC/peering).
- Federated query vs **zero-ETL**: federated = query live when asked (source pays the load); zero-ETL = data replicated into Redshift continuously (fast analytics, no load on queries).

## G. Streaming ingestion (verified)
- **Kinesis Data Streams** and **Amazon MSK** (also MSK Serverless, Confluent Cloud, Apache Kafka) feed a Redshift **materialized view** directly. Provisioned and Serverless both supported. **Low-latency, no S3 staging**; each refresh can pull **hundreds of MB/s** (doc statement).
- Steps (concept): create an **external schema** pointing at Kinesis/MSK with an IAM role → create a **materialized view** on the stream/topic → **refresh** (manual or **AUTO REFRESH**).
- First refresh starts at **TRIM_HORIZON** (Kinesis) or **offset 0** (Kafka).
- **Exactly-once** processing guarantee for Kinesis (stream/shard/sequence) and Kafka (topic/partition/offset).
- Best practices:
  - Land raw payload as **`VARBYTE`/SUPER** with `JSON_PARSE`, then extract with PartiQL (not many `JSON_EXTRACT_PATH_TEXT` calls).
  - **One MV per stream/topic** (each MV creates a consumer per shard/partition; extra MVs cause throttling and extra cost).
  - Join/transform by creating a **second MV** on top of the streaming MV (joins directly in the streaming MV are not supported).
- Limits: record max **16 MiB** (VARBYTE); Kinesis max record 10 MiB (patch 203+); no decompression of compressed records; KPL-aggregated records stay binary; **no Amazon MSK multi-VPC private connectivity** (use VPC peering/Transit Gateway); Kafka topic name ≤ 128 chars; bad records are skipped and logged in `SYS_STREAM_SCAN_ERRORS`; `enable_case_sensitive_identifier` needed for non-lowercase names with auto refresh.
- `TRUNCATE`, `DELETE`, `ALTER TABLE APPEND` on streaming MVs hold **exclusive locks**.
- Keep an MSK broker in the **same AZ** as Redshift to avoid cross-AZ cost.
- Streaming ingestion vs **Firehose → Redshift**: Firehose lands in S3 then runs COPY (minute-level latency, extra S3 hop, buffer settings). Streaming ingestion is lower latency and simpler, but ties compute to the stream. Choose Firehose when you also want the S3 copy / transformation with Lambda.

## H. Zero-ETL integrations (verified)
- **Fully managed continuous replication** from a source into Redshift with **no pipeline to build**. After an initial load, changes replicate (seconds latency). Source stays fully usable.
- Supported sources (doc list): **Aurora MySQL, Aurora PostgreSQL, RDS for MySQL, RDS for PostgreSQL, RDS for Oracle, DynamoDB**, Oracle Database@AWS, **applications** (Salesforce, Salesforce Marketing Cloud Account Engagement, SAP, ServiceNow, Instagram ads, Meta ads, Zendesk, via AWS Glue), and **self-managed** MySQL/PostgreSQL/SQL Server/Oracle.
- Target: provisioned cluster or Serverless workgroup. In the target you create a **destination database** from the integration.
- You can combine **many sources of the same type** into one warehouse.
- Setup needs: resource policy / authorized integration, case-sensitivity enabled (`enable_case_sensitive_identifier`), correct parameters on the source (for example enhanced binlog for MySQL).
- Extras: **history mode** (keep history of changes), **data filtering** (include/exclude tables), CloudWatch metrics, **EventBridge/SNS notifications**, monitoring via system views.
- Combine with **materialized views, data sharing, Redshift ML** for analytics on fresh data.
- Pricing: no extra charge for zero-ETL itself; you pay source and Redshift costs (and Glue for app sources) (verify).
- Zero-ETL vs DMS/Glue ETL: zero-ETL = no code, near-real-time, limited transformations. DMS/Glue = more control and other sources.

## I. Data sharing (verified)
- Share **live** data between Redshift **clusters, Serverless workgroups, AWS accounts, and Regions** without copying or moving data.
- Roles: **producer** (owns data, creates a **datashare**), **consumer** (creates a database from the datashare).
- Granularity: databases, schemas, tables, views (regular, late-binding, materialized), SQL UDFs.
- **Reads** and **writes** are supported (grant SELECT, INSERT, UPDATE on tables; USAGE and CREATE on schemas). Writes work across clusters/workgroups and Regions.
- **Strong transactional consistency**: a consumer query sees the producer's data as of the start of its transaction; committed changes are visible to new transactions immediately.
- Works between provisioned and Serverless. Requires RA3/RG or Serverless (not DC2) (verify).
- Use cases: **workload isolation** (central ETL cluster shares to separate BI clusters), chargeback per consumer, dev/test copies without duplication, cross-team/cross-account sharing, **AWS Data Exchange** listings for monetizing data, sharing via **Lake Formation**.
- Consumer pays for its own compute; producer pays storage.
- Cross-Region sharing: data transfer charges apply; `CROSS_REGION_DATASHARING` usage limit available.
- Auto sort operations track scans from consumers too.

## J. Redshift ML, notebooks and AI (awareness)
- **Redshift ML**: `CREATE MODEL … FROM table FUNCTION fn …` trains a model using **SageMaker Autopilot** and exposes it as a SQL function for predictions. Use for churn, forecast, classification with plain SQL. You can also bring your own SageMaker model or call Bedrock models via remote models (verify).
- Zero-ETL + ML lets you score fresh operational data without pipelines.

## K. Data API and connections (verified)
- **Data API**: run SQL via **HTTPS/AWS SDK** with **no JDBC/ODBC drivers or persistent connections**; calls are **asynchronous**. Works for provisioned and Serverless. Ideal for **Lambda, Step Functions, SageMaker notebooks**.
- Auth: **Secrets Manager** (secret ARN), **temporary credentials (IAM)**, or **IAM Identity Center** (trusted identity propagation).
- Operations: `ExecuteStatement`, `BatchExecuteStatement` (multiple statements; `TRANSACTION` or `AUTO_COMMIT` mode), `DescribeStatement`, `GetStatementResult` (JSON) / `GetStatementResultV2` (CSV), `CancelStatement`, `ListStatements`, etc.
- Limits: query max **24 hours**; **500** active queries per cluster; **500 MB** result (gzip) ; results kept **24 hours**; statement size **200 KB**; session reuse up to **24 hours** with `SessionKeepAliveSeconds`, **500 sessions** max; `ClientToken` idempotency valid **8 hours**.
- Throttle limits (TPS): ExecuteStatement **30**, BatchExecuteStatement **20**, DescribeStatement **100**, GetStatementResult **20**, others **3**. Retry with backoff on `ThrottlingException`.
- Named **parameters** prevent SQL injection (values only, not column/table names; cannot pass NULL as SQL NULL).
- Completion events can go to **EventBridge** (verify) so Step Functions/Lambda react without polling.
- Other connections: **JDBC/ODBC** drivers (IAM auth, SAML), **Python connector**, **Query Editor v2** (web), **psql**.
- **Redshift-managed VPC endpoints** let other VPCs/accounts connect privately (limits: 30 endpoints per cluster).

## L. Other integrations to remember
- **AWS Glue**: ETL jobs read/write Redshift (JDBC/connector); Glue Data Catalog for Spectrum; Glue for zero-ETL app sources.
- **AWS Database Migration Service**: Redshift as a target (uses S3 staging with COPY).
- **Amazon Data Firehose**: Redshift as a destination (via S3 + COPY).
- **AppFlow**: SaaS data into Redshift (verify).
- **QuickSight/Amazon Quick**: BI on Redshift (SPICE or direct query).
- **Lake Formation**: governance for Spectrum/data-lake tables and for datashares.
- **Step Functions / EventBridge scheduler / MWAA**: orchestrate loads and SQL.
- **Lambda**: UDFs and Data API callers.
- **SageMaker**: Redshift ML.
- **S3 Tables / Iceberg**: query and write Iceberg tables from Redshift (verify write capabilities).

## Scenarios (if → then, because)
- If nightly files land in S3 and you want them loaded automatically without Lambda → auto-copy (S3 event integration + COPY JOB), because Redshift tracks loaded files.
- If a COPY of one 50 GB file is slow → split into many compressed files (multiple of slice count), because COPY parallelism is per file.
- If a COPY is run twice by mistake → duplicates, because plain COPY doesn't remember files.
- If a few rows in a CSV are bad → `MAXERROR` and inspect `SYS_LOAD_ERROR_DETAIL`.
- If data older than 2 years is rarely queried but must remain queryable → UNLOAD to S3 as partitioned Parquet and use Spectrum, because S3 is cheaper than warehouse storage.
- If you need to join S3 data and warehouse tables in one query → Spectrum external schema, because it reads S3 via the Glue Catalog.
- If a Spectrum query scans too much and costs more → partition by date, use Parquet, and filter on partition columns.
- If you want live operational data in a report without moving it → federated query to Aurora/RDS (consider a read replica to protect the OLTP DB).
- If operational data should be available for analytics within seconds with no pipeline → zero-ETL from Aurora/RDS/DynamoDB.
- If you need clickstream from Kinesis in Redshift with low latency → streaming ingestion to a materialized view, one MV per stream.
- If you also want the raw stream archived in S3 → Firehose (to S3, then Redshift) or Kinesis consumer, because streaming ingestion doesn't land in S3.
- If many teams need the same data without copies → data sharing; give each team its own consumer cluster/workgroup for isolation and chargeback.
- If consumer needs to write back approvals to the producer's table → data sharing write access (SELECT/INSERT/UPDATE grants).
- If a Lambda must run SQL without managing connections → Data API with Secrets Manager or IAM temporary credentials.
- If a long-running Data API query result is needed after 2 days → results expire at 24 hours; UNLOAD to S3 instead.
- If a SaaS source (Salesforce, SAP) must land in Redshift with no code → zero-ETL integration for applications (via Glue/AppFlow).
- If a sales team wants predictions in SQL → Redshift ML `CREATE MODEL`.

## Verified from AWS docs on 2026-10-02
Read: loading data page, auto-copy page, Spectrum overview and quotas, federated query overview, streaming ingestion page, zero-ETL overview, data sharing overview, Data API page, pricing summary, quotas page. Not confirmed (verify): COPY file-size/count guidance and SSE-C support, UNLOAD JSON/format list, Spectrum file size guideline, Iceberg write support, Redshift ML remote model details, Data API EventBridge events, AppFlow integration, zero-ETL pricing, DC2 data sharing support, source parameter requirements for each zero-ETL source.

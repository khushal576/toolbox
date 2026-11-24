# Athena – 5. Operations, log analysis and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Ways to run Athena
- **Console** query editor (tabs per workgroup).
- **API / CLI / SDK**: `StartQueryExecution` → poll `GetQueryExecution` (or use EventBridge) → `GetQueryResults` (paged) or read the CSV from S3.
  - Async by design: the call returns a `QueryExecutionId`, not rows.
  - `BatchGetQueryExecution` checks many IDs in one call (saves API quota).
  - `GetQueryResultStream`/driver streaming is used by JDBC/ODBC.
  - Pass `ClientRequestToken` for **idempotency** (same token → same query, not duplicated).
- **JDBC / ODBC drivers**: BI tools (Tableau, DBeaver, Power BI, QuickSight/Amazon Quick). Drivers need `athena:*` rights and an S3 results location. IAM role credentials via the driver last at most **12 hours**.
- **AWS SDK for pandas** (awswrangler) and `boto3`: `wr.athena.read_sql_query`, CTAS-based reads, `to_iceberg`. Good in Lambda for small jobs.
- **Step Functions**: native Athena integration `startQueryExecution.sync` waits for the query. **Airflow/MWAA**: `AthenaOperator`. **Glue workflows** can call Athena via Python shell/Lambda.
- **Lambda**: start a query on S3 events; use EventBridge (Query State Change) to continue the chain, not a Lambda that sleeps.
- **EMR Studio** and **SageMaker Unified Studio** have an Athena SQL editor (needed for Identity Center–enabled workgroups).
- **Amazon Quick (QuickSight)** uses Athena as a data source (direct query or SPICE import).
- **dbt-athena** adapter exists for dbt models on Athena/Iceberg (community/AWS-supported; verify).

## B. Monitoring
- **CloudWatch query metrics** (namespace `AWS/Athena`, must be **enabled per workgroup**): `ProcessedBytes`, `TotalExecutionTime`, `EngineExecutionTime`, `QueryPlanningTime`, `QueryQueueTime`, `ServicePreProcessingTime`, `ServiceProcessingTime`, plus `DPUAllocated`, `DPUConsumed`, `DPUCount` (capacity reservations only).
  - Dimensions: `WorkGroup`, `QueryState` (SUCCEEDED/FAILED/CANCELED), `QueryType` (DML/DDL/UTILITY), `CapacityReservation`.
  - `TotalExecutionTime` = queue + planning + engine + service processing.
  - `QueryPlanningTime` is part of `EngineExecutionTime` (includes partition lookup time).
  - `ProcessedBytes` is not reported for DDL. For canceled queries it includes bytes before cancel.
  - Spark metric: `DPUCount` in namespace `AmazonAthenaForApacheSpark` with `SessionId`, `WorkGroup`.
- **Usage metrics** (service quota usage) in CloudWatch: alarm when active queries approach the quota (e.g., "ActiveDMLQueries" style usage metrics) (verify exact names).
- **EventBridge**: event `source = aws.athena`, `detail-type = Athena Query State Change`.
  - Fields: `currentState`, `previousState`, `statementType`, `queryExecutionId`, `workgroupName`, `sequenceNumber` (dedupe/order).
  - `athenaError` block (category, type, message, retryable) appears only on `FAILED`.
  - Best-effort delivery. Use it to trigger Lambda/SNS/Step Functions when a query finishes or fails.
  - **AWS User Notifications** can send email/chat for these events.
- **CloudTrail**: API calls and query text.
- **Per-query stats** in `GetQueryExecution`: data scanned, engine/total time, queue time, planning time, `DataManifestLocation` (list of files written by CTAS/INSERT/UNLOAD).
- **Error catalog**: Athena has an error reference with `errorCategory` (1 system, 2 user, 3 other) and `errorType`, plus a `retryable` flag. Retry only retryable ones.
- **Spark**: Spark UI, driver/executor logs to CloudWatch/S3, cost attribution via tags.

## C. Troubleshooting table (symptom → cause → fix)
- `HIVE_BAD_DATA: Error parsing field value` → column type differs from data, or NULL/empty in an int column → change column to string and `CAST`, or fix the data.
- `HIVE_CANNOT_OPEN_SPLIT` / `HIVE_CURSOR_ERROR: ... key does not exist` → file deleted or replaced during the query, malformed file, or S3 throttling → rerun, stop overwriting files in place, check the file named in the error.
- `HIVE_FILESYSTEM_ERROR: Incorrect fileSize` → object replaced in place between planning and reading → write new files/partitions only.
- `HIVE_CURSOR_ERROR: Unexpected end of input stream` → corrupt or empty file.
- `HIVE_PARTITION_SCHEMA_MISMATCH` → partition schema differs from table schema → drop and re-create the partition.
- `HIVE_TOO_MANY_OPEN_PARTITIONS` → more than 100 partitions in CTAS/INSERT → split with `INSERT INTO` batches.
- `HIVE_UNKNOWN_ERROR: Unable to create input format` → crawler could not classify, empty table properties, unsupported format, or partitions in different formats.
- `GENERIC_INTERNAL_ERROR: Null` → schema mismatch or bad CTAS syntax. `Parent builder is null` → `array` column with OpenCSVSerDe. `Value exceeds MAX_INT` → use BIGINT.
- `Query exhausted resources at this scale factor` → too much memory (big join, window, distinct) → rewrite (file 2), retry.
- `TooManyRequestsException` (Athena) → active query quota exceeded → queue/retry with backoff, use capacity reservation, raise quota.
- `ThrottlingException: Rate exceeded` on an API call → API rate quota → backoff, use `BatchGet*`.
- `SlowDown` / "reduce your request rate" → S3 throttling → bigger files, fewer concurrent queries.
- `AWSGlueException: Rate exceeded` → Glue API throttled → fewer partitions, partition projection, stagger queries.
- KMS "exceeded the rate" → enable S3 Bucket Keys.
- Zero rows → partitions missing, wrong location, hidden files (`_` or `.` prefix), wrong header setting, or projection out of range.
- `SYNTAX_ERROR: Column cannot be resolved` → BOM in CSV, mixed case in nested JSON, wrong column name.
- `FAILED: NullPointerException Name is null` → Glue table without `TableType`.
- `Access Denied (403)` → check S3 (data and results), KMS, Glue, Lake Formation, bucket owner of objects, SSE bucket policy conflicts.
- "Unable to verify/create output bucket" → results location missing, wrong Region, or no permission.
- "The S3 location provided to save your query results is invalid" → results bucket in another Region or wrong path.
- Empty `TIMESTAMP` → wrong timestamp format. Use string + `date_parse`.
- "View is stale" → re-create the view.
- `INVALID_GLUE_SCHEMA` (Delta) → Glue schema out of date.
- Query "timeout" with no clear error → look at CloudTrail for Glue/Lake Formation throttling.
- Duplicated rows after CTAS/INSERT → concurrent CTAS to the same location or leftover orphan files from a failed run.
- `NOT_SUPPORTED: ... ORDER BY LIMIT > 2147483647` → LIMIT too large with ORDER BY.
- Query string too long → split the query (hard 262,144-byte limit).
- Federated query problems → file 3.

## D. Analyzing logs with Athena (exam favourite)
- Athena is the standard tool for **ad hoc SQL on logs stored in S3**. Pattern: log source → S3 → table (Glue/DDL) → Athena.
- **Service logs and the format to use**:
  - **ALB / CLB / NLB access logs** → S3. Use the documented table DDL with **Regex SerDe**. Partition projection by date. (Per ELB logs in S3 with Athena.)
  - **CloudTrail logs** → S3 (trail) or CloudTrail Lake. Use `CloudTrailInputFormat` DDL / Hive JSON SerDe. Partition projection by region/date. Can also create the table from the CloudTrail console.
  - **VPC Flow Logs** → S3 in text or Parquet. Hive-compatible folder layout option exists. Query to find rejected traffic, top talkers.
  - **S3 server access logs** → Regex SerDe table.
  - **CloudFront standard logs** → TSV (LazySimpleSerDe, skip 2 header lines).
  - **AWS WAF logs** → JSON to S3 (via Firehose).
  - **Route 53 resolver query logs**, **Network Firewall**, **Config** snapshots, **Cost and Usage Reports** (CUR as Parquet with Athena integration) — all use the same S3 + table pattern.
  - **Application logs** (JSON lines) via Firehose → S3 → JSON SerDe/Parquet conversion.
  - **EMR logs** (step/application logs in S3) → Regex/Grok table to search failures.
  - **CloudWatch Logs** → export to S3, subscribe with Firehose to S3, or use the CloudWatch connector (federated; slower).
- Best practices for logs:
  - Land logs with a **date-based prefix** and use **partition projection**.
  - Convert to **Parquet** with Firehose record format conversion or a scheduled CTAS to cut scan cost for repeated analysis.
  - Use a **lifecycle policy** on the log bucket.
  - Keep logs and results in separate buckets/prefixes.
- **CloudWatch Logs Insights** vs Athena: Logs Insights = quick queries on recent data inside CloudWatch (billed per GB scanned, 30-day style retention in CloudWatch); Athena = long retention in S3, joins with other datasets, cheaper at scale.
- **OpenSearch** vs Athena: OpenSearch = search, dashboards, near-real-time; Athena = occasional SQL, cheap long-term.
- **EMR for very large logs** = Spark jobs on big log volumes with custom parsing; Athena is enough for SQL-style log questions.
- Sample query ideas to remember: top 10 client IPs from ALB logs; 5xx rate per minute; CloudTrail `eventName = 'DeleteBucket'` by user; rejected flows by dest port; most expensive services from CUR.

## E. Integration patterns
- **Athena + Glue crawler + Data Catalog**: crawler discovers S3 data, writes tables/partitions, Athena queries.
- **Athena + Lake Formation**: governed lake (file 4).
- **Athena + Step Functions**: orchestrated CTAS/INSERT steps, wait for completion (`.sync`).
- **Athena + EventBridge**: react to query completion.
- **Athena + QuickSight (Amazon Quick)**: dashboards. Use SPICE for speed, direct query for freshness. QuickSight's role needs S3 + Athena + LF rights.
- **Athena + Redshift**: Redshift Spectrum for in-warehouse joins with S3; Athena for ad hoc S3. Athena can also query Redshift via the Redshift connector.
- **Athena + Iceberg + Glue/Spark/EMR**: multiple engines on one Iceberg table through the Glue catalog.
- **Athena + SageMaker Unified Studio / Lakehouse**: SQL on lakehouse tables, notebooks.
- **Athena + EMR**: Athena can reuse an EMR/Hive metastore (via Hive metastore connector) or read data EMR wrote.
- **Athena + Firehose**: Firehose writes partitioned Parquet; Athena reads with projection (dynamic partitioning needs the `injected`/date template with care).
- **Athena + DMS**: DMS writes full load + CDC to S3 (Parquet); Athena queries it (CDC rows have `Op` columns; merge into Iceberg for current state).
- **CTAS-based ETL**: raw → CTAS to curated Parquet → CTAS/INSERT to aggregates; orchestrate with Step Functions or Airflow; add Glue Data Quality or Deequ for checks (verify).
- **Data quality checks in Athena**: `COUNT`, null checks, duplicates (`GROUP BY HAVING COUNT>1`), range checks via SQL; write failed rows to a quarantine table.

## F. Operating tips
- Name queries by purpose (`NamedQuery`) and keep them in a workgroup. Use tags for cost.
- **Workgroup per environment/team**: separate results, limits, encryption, alerts.
- **Idempotency**: use `ClientRequestToken`; for CTAS write to a unique prefix each run (the location must be empty) and clean orphan files from failed runs.
- **Retry with backoff** on `TooManyRequestsException` and `ThrottlingException`.
- Don't poll `GetQueryExecution` at high rate. Use EventBridge or Step Functions `.sync`.
- Clean up results and spill buckets with lifecycle rules, and abort incomplete multipart uploads.
- Test new engine versions in a test workgroup before upgrade.
- Maintain Iceberg tables on a schedule (`OPTIMIZE`, `VACUUM`).
- Keep partitions tidy: drop stale ones, prefer projection.
- Keep Glue catalog clean (unused tables, crawlers that overwrite schema).
- Watch `ProcessedBytes` per workgroup; alert on spikes.

## G. Scenarios: If X → Y, because Z
- If you must find who deleted an S3 bucket last week → Athena on CloudTrail logs (`eventName='DeleteBucket'`), because CloudTrail stores API calls in S3 and Athena queries them with SQL.
- If a security team investigates rejected traffic in a VPC → Athena on VPC Flow Logs (Parquet, partitioned), because it handles TBs cheaply.
- If ALB 5xx errors spike and you need a per-target breakdown for the last 30 days → Athena on ALB logs with partition projection, because the logs are already in S3 and no cluster is needed.
- If logs are queried constantly and the scan bill grows → Firehose converts to Parquet (or scheduled CTAS) + partitions, because Parquet reduces bytes scanned.
- If logs must be searched in near real time with dashboards → OpenSearch or CloudWatch Logs Insights, not Athena, because Athena is batch-style and S3-delivery-delayed.
- If a pipeline must wait for an Athena query then continue → Step Functions `startQueryExecution.sync` (or EventBridge on `SUCCEEDED`), because polling in Lambda wastes money.
- If an alert must fire on failed queries → EventBridge rule on `FAILED` with `athenaError` → SNS/Lambda, because events carry the error.
- If a scheduled report must run at 9am and always finish fast → workgroup with a capacity reservation, because on-demand queries can queue behind other work.
- If a big SQL export must go to a data science team as Parquet → `UNLOAD`, because it writes in parallel in the right format.
- If you need to sample bad lines from JSON → table with `ignore.malformed.json = true` and filter NULL rows, because malformed lines become NULL.
- If a query slowly degrades as new small files land every minute → compaction (Glue/CTAS/Iceberg `OPTIMIZE`) and larger Firehose buffers, because small files dominate runtime.
- If a developer's SDK loop gets `ThrottlingException` → exponential backoff + `BatchGetQueryExecution` + EventBridge, because API rate quotas are per account.
- If you need CUR cost analysis → the CUR Athena integration (Parquet + CloudFormation template) and queries by tag/service, because CUR is delivered to S3.
- If you must test an engine upgrade safely → create a test workgroup on the new engine and rerun key queries, because engine version is per workgroup.
- If a team needs SQL on Kafka topics without ingesting → MSK/Kafka federated connector for quick checks; for real analytics land data in S3 via Firehose/MSK Connect, because the connector is slow at scale.

## Verified from AWS docs on 2026-10-25
Read from current Athena User Guide pages: CloudWatch query metrics, EventBridge query state events, troubleshooting, error catalog index, service quotas, performance tuning, engine versioning, workgroups.
Not confirmed (verify): usage-metric names for the quota alarms, query history retention, dbt-athena support status, CloudFront/ALB/CloudTrail DDL specifics (taken from general Athena knowledge; check the Athena "Query AWS service logs" pages before relying on column lists), Step Functions `.sync` Athena integration name, QuickSight/Amazon Quick connection options, awswrangler function names, whether Firehose dynamic partitioning is compatible with each projection type.

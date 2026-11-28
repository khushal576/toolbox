# Redshift – 6. Cost, monitoring, troubleshooting, limits, traps, decision lines and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Pricing model (verified)
- **Provisioned**:
  - **On-demand node hours** by node type (billed per hour). Leader node is free in multi-node clusters.
  - **Reserved nodes** (1 or 3 years; no, partial or all upfront) = large discount for steady workloads. Quota **200** reserved nodes.
  - **Managed storage** (RA3/RG): billed **per GB-month** for data actually stored, same price whether it sits on SSD or in S3.
  - **DC2**: storage included in the node price.
  - **Pause**: stops compute billing; storage and backups still billed. **Resume** restarts hourly billing.
- **Serverless**:
  - **RPU-hours**, billed **per second**, **60-second minimum** per charge. **No charge while idle.**
  - Managed storage billed per GB-month.
  - Cost caps: **max RPU** (workgroup) and **usage limits** (RPU-hours per day/week/month with alert/log/disable actions).
- **Spectrum**: per **TB scanned**, rounded up to the next MB, **10 MB minimum** per query.
- **Concurrency scaling**: **1 free hour per day** of credit accrual; then **per-second** on-demand rate while scaling clusters run queries.
- **Snapshots**: automated backup storage free up to the size of your storage; manual snapshots and extra storage billed **per GB-month**; cross-Region copy adds transfer.
- **Data transfer**: free within same AZ/service paths; cross-Region and internet egress charged. Cross-Region data sharing and COPY from another Region cost transfer.
- **Zero-ETL, streaming, federated**: no extra Redshift fee for the feature itself, but you pay Redshift compute, source database load, Kinesis/MSK, and (for app sources) Glue (verify).
- **Redshift ML**: SageMaker training costs; predictions in SQL are free of extra charge (verify).
- **Free trial / credits** exist for new Serverless users (verify current terms).
- Usage types by feature are visible in Cost Explorer: node hours, RPU, managed storage, Spectrum bytes, concurrency scaling seconds.

## B. Cost optimization (what to do)
- **Right-size**: choose node count based on daily data processed; use **elastic resize** to adjust.
- **Steady load → reserved nodes**; **spiky or intermittent → Serverless** (or pause/resume on a schedule).
- **Pause dev/test** clusters nights/weekends (scheduled pause/resume).
- **Serverless cost control**: set **max RPU**, usage limits, avoid leaving big base capacity.
- **Archive cold data**: `UNLOAD` to S3 as **partitioned Parquet** and query with **Spectrum** (or Athena) instead of keeping everything in the warehouse.
- **Reduce Spectrum bytes**: Parquet/ORC, partitions, compression, select only needed columns.
- **Use materialized views** and result caching so dashboards don't rescan big tables.
- **Concurrency scaling**: rely on free credits; set `max_concurrency_scaling_clusters` and usage limits to cap spend.
- **Use data sharing** instead of duplicate clusters/copies.
- **Drop unused tables, old snapshots**; set sensible snapshot retention; remove unused manual snapshots.
- **Choose RA3/RG** so storage doesn't force you to buy compute.
- **Efficient tables**: good encodings, AUTO keys, avoid over-wide VARCHAR, keep temp tables small.
- **Tag** resources for chargeback; separate warehouses per team via data sharing for clear bills.
- Use **Cost Explorer / Budgets / Trusted Advisor** (idle clusters check) for visibility.
- Compare against **Athena** for rare ad-hoc queries on S3: per-TB scanned may be cheaper than a 24×7 cluster.

## C. Monitoring tools (verified)
- **CloudWatch metrics (AWS/Redshift, 1-minute unless stated)**:
  - Health: `HealthStatus` (1/0), `MaintenanceMode`.
  - Compute: `CPUUtilization` (cluster = aggregate of leader+compute; node-level via `NodeID`).
  - Storage: `PercentageDiskSpaceUsed`, `RedshiftManagedStorageTotalCapacity`, `TotalTableCount`.
  - Connections: `DatabaseConnections`.
  - Disk I/O: `ReadIOPS`, `WriteIOPS`, `ReadLatency`, `WriteLatency`, `ReadThroughput`, `WriteThroughput`.
  - Network: `NetworkReceiveThroughput`, `NetworkTransmitThroughput`.
  - Queries (5-minute): `QueriesCompletedPerSecond`, `QueryDuration`, `QueryRuntimeBreakdown` (by stage: planning, waiting, read, insert, delete, update, CTAS, unload, copy, commit).
  - WLM: `WLMQueueLength`, `WLMQueueWaitTime`, `WLMRunningQueries`, `WLMQueriesCompletedPerSecond`, `WLMQueryDuration`.
  - Commit: `CommitQueueLength`.
  - Concurrency scaling: `ConcurrencyScalingActiveClusters`, `ConcurrencyScalingSeconds`, `MaxConfiguredConcurrencyScalingClusters`.
  - Usage limits: `UsageLimitAvailable`, `UsageLimitConsumed` (feature types `CONCURRENCY_SCALING`, `SPECTRUM`, `CROSS_REGION_DATASHARING`, etc.).
  - Schema quotas: `SchemaQuota`, `StorageUsed`, `PercentageQuotaUsed`, `NumExceededSchemaQuotas`.
- **Serverless metrics** (namespace `AWS/Redshift-Serverless`): `ComputeCapacity` (RPUs), `ComputeSeconds` (RPU-seconds billed), `DataStorage`, plus query/connection metrics (verify names).
- **Latency dimension**: short (< 10 s), medium (10 s–10 min), long (> 10 min).
- **Console tabs**: Query monitoring (query/load summary and detail, with cluster metrics alongside), Cluster performance, Workload.
- **Disk space alarm**: default alarm at cluster creation → SNS.
- **System views/tables**: `SYS_*` (preferred), `SVV_*`, `SVL_*`, `STL_*`, `STV_*`. STL logs keep only a few days.
- **Audit logs** to S3/CloudWatch for long retention (file 5).
- **EventBridge/SNS event subscriptions** (limit **20** per account) for cluster, snapshot, maintenance, resize, security events.
- **Zero-ETL** monitoring: `SVV_INTEGRATION`, `SYS_INTEGRATION_*` views and integration metrics.
- **Redshift Advisor**: recommendations on table/cluster design.
- **Query Editor v2** history and scheduled queries; **CloudWatch Logs Insights** on exported logs.

## D. Recommended alarms (typical)
- `HealthStatus` = 0 (unhealthy).
- `PercentageDiskSpaceUsed` ≥ 80% (then act; around 90% queries fail/spill).
- `CPUUtilization` sustained ≥ 80–90%.
- `DatabaseConnections` near the limit.
- `WLMQueueLength` / `WLMQueueWaitTime` high for the dashboard queue.
- `CommitQueueLength` high.
- Concurrency scaling or Spectrum `UsageLimitConsumed` near cap.
- `MaintenanceMode` = 1 (informational).
- Snapshot failures / cross-Region copy lag via events.
- Serverless `ComputeCapacity` at max RPU for long periods.

## E. Troubleshooting map (symptom → cause → fix)
- **Slow queries** → bad distribution/skew, stale stats, unsorted table, nested loops, disk spill, queue wait → see file 4 checklist.
- **Queries waiting** → WLM queue full → priorities, SQA, concurrency scaling, bigger cluster, separate warehouse.
- **Disk full / `storage-full` status** → too much data on DC2, large temp spill, many deleted rows → VACUUM, drop/archive data, resize, move to RA3 (managed storage).
- **COPY fails** → wrong IAM role/permissions, wrong Region, bad format, delimiter, nulls, too-long VARCHAR, row > 64 MB → check `SYS_LOAD_ERROR_DETAIL`.
- **COPY slow** → one big file, uncompressed, too many tiny files → split and compress.
- **Duplicate rows** → plain COPY run twice, no enforced unique key → dedupe in ELT, use auto-copy or staging merge.
- **Can't connect** → security group port 5439, public access setting, route/VPN, MTU (hangs), wrong credentials, SSL required.
- **Serializable isolation violation (1023)** → overlapping writes on same table → retry/serialize.
- **DDL hangs** → blocked by open transaction/lock → `STV_LOCKS`, terminate blocker.
- **Spectrum query slow/expensive** → no partition filter, CSV not Parquet, many small files → fix layout.
- **Spectrum "access denied"** → IAM role lacks S3/Glue/Lake Formation permissions; bucket in another Region.
- **Federated query fails** → secret/role/network missing, unsupported type.
- **Streaming MV not refreshing** → IAM role, external schema misconfig, case-sensitive identifiers, throttled stream, aggregated KPL records.
- **Zero-ETL integration in a bad state** → case sensitivity off, resource policy missing, source parameter group; check integration status views.
- **Data Task throttled (Data API)** → `ThrottlingException`: back off, reduce TPS.
- **Serverless unexpected cost** → base RPU too high, long idle sessions, runaway queries, many tiny frequent queries → set max RPU/usage limits.
- **Cluster cost high** → idle 24×7 dev clusters, over-provisioned nodes → pause, resize, Serverless, reserved nodes.
- **Python UDF failures after mid-2026** → Python UDF support ended; migrate to SQL or Lambda UDFs.

## F. Limits and numbers to remember (verified)
- Nodes per Region: **200** (adjustable). Nodes per cluster: RA3/RG up to **128**, DC2 up to **128**.
- Clusters: parameter groups **20**; subnet groups **50** (20 subnets each); security groups **20**; event subscriptions **20**; snapshots **700**; reserved nodes **200**.
- IAM roles per cluster: **50**.
- Databases per cluster: **60**. Schemas per database: **9,900**. Roles: **1,000**. Stored procedures per database: **10,000**.
- Tables per cluster by node: ra3.large / single-node: **9,900**; ra3.xlplus multi-node: **20,000**; ra3.4xlarge / 16xlarge, dc2.8xlarge: **200,000**. (Includes permanent, temp, datashare tables, MVs; external tables count as temp; views excluded.)
- Serverless: **100** databases, **9,900** schemas, **200,000** tables per namespace; **25** namespaces and **25** workgroups; **2,000** connections; query timeout **24 hours**; idle session **1 hour**; **32 TB** storage at 4 RPU, **128 TB** at 8–24 RPU.
- Connections: RA3/RG **2,000**; dc2.large **500**; dc2.8xlarge **2,000**.
- WLM: manual user queues **8**; total slots **50**; default queue 5 slots.
- Concurrency scaling clusters: **10** quota; default max **1**; needs ≤ 32 nodes.
- COPY single row max: **64 MB** (SUPER value 16 MB). Streaming record max **16 MiB**.
- Idle session timeout: **4 hours** (cluster), idle transaction **6 hours**.
- Snapshots: automated retention **0–35 days** (default 1); share to **20** accounts/snapshot.
- Auto-copy: **200** jobs, **50** integrations.
- Data API: result **500 MB**, retention **24 h**, statement **200 KB**, **500** active queries, TPS limits (ExecuteStatement 30).
- Spectrum: 100 partitions per ALTER TABLE statement; same-Region S3; 10 MB minimum billing.
- Query Editor v2: 100 MB data fetched per query.
- Port **5439**.
- SLA: **99.9%** single-AZ, **99.99%** Multi-AZ.
- Admin password 8–64 chars; cluster identifier lowercase, 1–63 chars.
- Python UDF support ends **after 30 June 2026**.

## G. Common traps
- Using Redshift as an OLTP database (many single-row writes/lookups).
- Row-by-row `INSERT` loads instead of `COPY`.
- One giant file for COPY (no parallelism).
- Assuming PK/UNIQUE constraints are enforced.
- Picking a skewed DISTKEY; distributing small tables with KEY instead of ALL/AUTO.
- Forgetting ANALYZE after massive loads (rare now with auto analyze) and ignoring unsorted data.
- Filtering with a function on the sort key (kills block skipping).
- Large `VARCHAR(65535)` columns everywhere.
- Treating Multi-AZ as a backup, or forgetting cross-Region copy needs a **snapshot copy grant** for encrypted data.
- Leaving a cluster **publicly accessible**; forgetting security groups on port 5439.
- Believing the user activity log is on by default (also needs the parameter) or that Serverless can send logs to S3.
- Using concurrency scaling with temp tables / interleaved sort keys / Python UDFs and expecting offload.
- Letting Serverless scale without a **max RPU** cap.
- Running Spectrum on CSV without partitions.
- Using Python UDFs for new work (retiring).
- Expecting data sharing to work from DC2 clusters (needs RA3/RG/Serverless; verify).
- Putting audit logs in an S3 bucket with Object Lock or SSE-KMS (only SSE-S3 is supported for audit logs).
- Deleting/disabling the KMS key of an encrypted cluster.

## H. Decision lines (exam style)
- "Columnar, petabyte-scale data warehouse, SQL, BI" → **Redshift**.
- "Unpredictable analytics, no capacity planning" → **Redshift Serverless**.
- "Steady 24×7 warehouse, lowest cost" → **provisioned + reserved nodes**.
- "Scale compute and storage separately" → **RA3/RG managed storage**.
- "Query S3 data without loading, join with warehouse" → **Spectrum**.
- "Ad-hoc queries on S3, no cluster" → **Athena**.
- "Load files from S3 fast" → **COPY** (split, compressed, parallel).
- "Auto-load new S3 files" → **auto-copy (COPY JOB)**.
- "Near-real-time stream into warehouse" → **streaming ingestion (Kinesis/MSK → MV)**.
- "Aurora/RDS/DynamoDB → warehouse, no ETL code" → **zero-ETL**.
- "Query operational DB live from Redshift" → **federated query**.
- "Share live data across teams/accounts without copies" → **data sharing**.
- "Many concurrent dashboards" → **concurrency scaling + SQA**.
- "Protect short queries from long ETL" → **WLM queues/priorities + QMR**.
- "Speed up repeated heavy dashboard SQL" → **materialized views (auto refresh, auto rewrite)**.
- "Mask PII per role" → **dynamic data masking**; "restrict rows" → **RLS**; "restrict columns" → **column-level grants**.
- "Run SQL from Lambda without drivers" → **Data API**.
- "AZ-failure-proof warehouse" → **Multi-AZ (RG/RA3)**.
- "Cross-Region DR" → **cross-Region snapshot copy (+ copy grant)** or Region-pair data sharing.
- "Recover one table" → **table-level restore from snapshot**.
- "Predict with SQL" → **Redshift ML**.

## Scenarios (if → then, because)
- **If** a dev cluster sits idle at night, **then** set a **scheduled pause/resume**, or move it to **Redshift Serverless**. **This works because** a paused cluster stops **compute billing** (you still pay for storage and backups), and Serverless charges **nothing while idle**.
- **If** the finance team wants a predictable monthly cost for a steady warehouse, **then** buy **reserved nodes** for a provisioned cluster (**1 or 3 years**, with no, partial or all upfront payment). **This works because** reserved nodes give a **large discount** for steady use compared with on-demand node hours.
- **If** analytics bills spike because of random, unpredictable users, **then** use **Redshift Serverless** with a **max RPU** (Redshift Processing Unit) cap and **usage limits**. **This works because** max RPU caps how much compute the workgroup can scale to, and usage limits cap RPU-hours per day, week or month with alert, log or disable actions (verify action list).
- **If** storage grows faster than compute needs, **then** use **RA3** or **RG** nodes. **This works because** their data lives in **managed storage**, billed **per GB-month** for data actually stored, so growing data does not force you to buy more compute nodes (on DC2, storage is tied to the node).
- **If** **80%** of data is cold and rarely queried, **then** **UNLOAD** it to **Amazon S3** as **partitioned Parquet** and query it with **Redshift Spectrum** (or **Amazon Athena**). **This works because** S3 storage is cheaper than warehouse storage, and Spectrum can still query the files when needed, paying only per data scanned.
- **If** Spectrum costs rise, **then** check the **bytes scanned**, add **partitions**, convert files to **Parquet**, and set a **Spectrum usage limit**. **This works because** Spectrum bills **per TB scanned** (10 MB minimum per query), and partitions plus columnar files cut how much is read, while the usage limit caps spend.
- **If** `PercentageDiskSpaceUsed` hits **85%** on a **DC2** cluster, **then** resize, move to **RA3** (managed storage), or purge old data, and run **`VACUUM DELETE`** to reclaim space from deleted rows. Alarm at about **80%**, since near 90% queries fail or spill (typical thresholds; verify).
- **If** a cluster shows as unhealthy, **then** check the **`HealthStatus`** metric (0 means unhealthy) and recent **events**. If a **single-node** cluster failed, **restore from a snapshot**, because single-node clusters have no mirror and Redshift cannot replace the node in place.
- **If** you need Slack or e-mail alerts for failed snapshots and maintenance, **then** create an **event subscription** to an **Amazon Simple Notification Service (SNS)** topic. **This works because** Redshift publishes cluster, snapshot, maintenance and resize events, and SNS forwards them to subscribers (limit **20** subscriptions per account).
- **If** you must keep an audit trail for **7 years**, **then** send **audit logs** to **Amazon S3** (encrypted with **SSE-S3**, the only supported option) with a **lifecycle rule** to **Amazon S3 Glacier**, and keep **AWS CloudTrail** for API calls. **This works because** system tables keep logs only a few days, while S3 keeps exported logs cheaply for years.
- **If** an **AWS Lambda** function hits **Data API** throttles (`ThrottlingException`), **then** **back off and retry**, and combine statements with **`BatchExecuteStatement`**. **This works because** the Data API limits calls per second (for example **30** for ExecuteStatement), so fewer, batched calls stay under the limit.
- **If** regulators demand encryption with your own key and a disaster-recovery copy in another Region, **then** use a **customer managed AWS Key Management Service (KMS) key** and **cross-Region snapshot copy** with a **snapshot copy grant**. **This works because** the copy grant lets Redshift use a **KMS key in the destination Region** to encrypt the copied snapshots.
- **If** BI users complain of slowness only at peak times, **then** use **concurrency scaling** (temporary extra clusters for bursts) and **short query acceleration (SQA)**. If it is still slow, use a bigger cluster, or isolate teams on separate warehouses with **data sharing**. **This works because** peak-only slowness means queries are **waiting in queues**, not that the cluster is too small all day.
- **If** a new **zero-ETL** feed shows no data, **then** check that **case sensitivity** is on (`enable_case_sensitive_identifier`), the **resource policy** authorizes the integration, the source parameters are right, and the **integration status** views (`SVV_INTEGRATION`) show no errors. **This works because** these are the common setup gaps that leave an integration in a bad state.
- **If** you need an exam one-liner, **then** remember: **Redshift** is a columnar, massively parallel (MPP) SQL warehouse; **Spectrum** queries S3; **Serverless** is paid per RPU-second; **RA3** separates compute and storage; **data sharing** shares live data with no copies.

## Verified from AWS docs on 2026-10-02
Read: pricing summary, CloudWatch metrics page, quotas page, concurrency scaling page, WLM page, Multi-AZ page, Data API page, clusters page. Not confirmed (verify): Serverless CloudWatch namespace and metric names, free trial terms, Redshift ML pricing details, alarm thresholds (typical practice), usage-limit actions list, data sharing support on DC2, Trusted Advisor check names, STL retention days.

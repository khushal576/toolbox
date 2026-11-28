# DMS – 3. Security, networking, monitoring, troubleshooting, cost, limits, and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Security (verified + notes)
- **IAM**: control who can create/modify/start DMS resources. Resource-level permissions are supported (for example allow `dms:StartReplicationTask` on one task ARN).
- **Required service roles** for the console/API (created once per account):
  - **`dms-vpc-role`** – lets DMS manage VPC resources (network interfaces) for the replication instance; managed policy `AmazonDMSVPCManagementRole`. Trust principal `dms.amazonaws.com`.
  - **`dms-cloudwatch-logs-role`** – lets DMS publish task logs to CloudWatch Logs; managed policy `AmazonDMSCloudWatchLogsRole`.
  - A role for **target access** (S3 bucket, Kinesis stream, Redshift staging bucket) with a trust policy for DMS and only the needed actions.
  - **`dms-access-for-endpoint`** is used for Redshift targets (verify).
  - A **Secrets Manager access role** when endpoints read credentials from Secrets Manager.
  - A **service-linked role** for DMS Serverless (AWS creates it).
- **Encryption at rest**: choose a **KMS key** when you create the replication instance or Serverless config (default `aws/dms`). It encrypts replication storage and connection info.
- **Encryption in transit**: set **SSL mode** on each endpoint (`none`, `require`, `verify-ca`, `verify-full`). Prefer `verify-ca` / `verify-full`; import the CA certificate into DMS. Kinesis/DynamoDB/S3 calls are always over HTTPS.
- **Network isolation**: replication instance runs in **your VPC**; use **private** (not publicly accessible) instances; reach on-premises via VPN/Direct Connect; control with **security groups** and NACLs; use **VPC endpoints** for S3, Kinesis, DynamoDB, Secrets Manager, Redshift, OpenSearch when needed (**required for DMS Serverless**; required for Kinesis since engine 3.4.7 unless public routes).
- **Credentials**: store endpoint passwords in **Secrets Manager** (not plain text). Rotate secrets; DMS reads them through an access role.
- **Least privilege on databases**: create a dedicated DMS user with only the grants DMS needs (read on source, logs/replication privileges for CDC; write on target).
- **Auditing**: **CloudTrail** logs all DMS API calls (CreateReplicationInstance, StartReplicationTask, TestConnection…). CloudWatch logs hold task logs.
- **Data masking**: transformation rules can mask columns during migration (verify types) → keeps sensitive data out of non-prod targets. Validation skips masked columns.
- Treat **task logs** and **Time Travel logs** as sensitive; Time Travel logs go to S3 encrypted with your key.
- Database-side security: encrypt target (RDS/Aurora/Redshift/S3 encryption), restrict target access, **S3 bucket policy** for DMS role.
- Compliance programs apply to DMS (check the services-in-scope page).

## B. Networking patterns (exam favorites)
- **Both in the same VPC**: simplest; security groups only.
- **On-premises source → AWS target**: VPN or Direct Connect to the VPC; replication instance in a private subnet; on-prem firewall allows the instance IPs; DNS via Route 53 Resolver if names must resolve on-prem.
- **Source and target in different VPCs**: VPC peering or Transit Gateway; instance in either VPC.
- **Different accounts**: peering/TGW + cross-account IAM or share endpoints; S3 targets in other accounts need bucket policies.
- **Source in another cloud**: reach over internet/VPN; use public replication instance only if necessary.
- **Replication instance without internet** + AWS service targets → **interface/gateway VPC endpoints**.
- Open the **database port** only to the replication instance's security group.
- IP allow-listing: the replication instance's **private/public IPs** (or Serverless ENIs) must be allowed by the source firewall (also relevant to exam skill "IP allowlists for data sources").

## C. Monitoring (verified)
- **Task status** and **table state** in console; **Table statistics** tab: rows loaded, inserts/updates/deletes/DDLs per table, validation state.
- **CloudWatch metrics** by category:
  - **Replication instance (host)**: `CPUUtilization`, `FreeableMemory`, `FreeMemory`, `AvailableMemory`, `SwapUsage`, `FreeStorageSpace`, `ReadIOPS/WriteIOPS`, `ReadLatency/WriteLatency`, throughput, `DiskQueueDepth`, network throughput. FreeableMemory near zero **plus** rising SwapUsage = instance too small or too many tasks.
  - **Task metrics**: `CDCLatencySource`, `CDCLatencyTarget`, `CDCIncomingChanges`, `CDCChangesMemorySource/Target`, `CDCChangesDiskSource/Target`, `CDCThroughputRowsSource/Target`, `CDCThroughputBandwidthTarget`, `FullLoadThroughputRowsTarget`, `FullLoadThroughputBandwidthTarget`, task `CPUUtilization`, `MemoryUsage`, `SwapUsage`.
  - **Validation metrics** (see file 2) and **Serverless** `CapacityUtilization`.
- **Latency diagnosis**: compare `CDCLatencySource` and `CDCLatencyTarget`:
  - Both high → look at **source** first (log reading, source load, large transactions, network).
  - Target high, source low → target side: **missing PK/indexes** on target, resource bottleneck, network, or batch settings.
  - `CDCLatencySource` keeps growing during an open uncommitted transaction.
  - Latency spikes during batch jobs are normal.
- **CDCIncomingChanges** high = DMS can't apply fast enough (target latency). **CDCChangesDiskTarget** > 0 = changes spilling to disk (memory pressure).
- **Task logs** in CloudWatch: truncation warnings and FK violations appear only in the log. View with `describe-replication-instance-task-logs`; delete with `DeleteTaskLogs`; logs older than **10 days** are deleted per replication instance.
- **Events and notifications** via **SNS** event subscriptions (instance, task, migration events).
- **CloudTrail** for API audit; **EventBridge** for event routing (verify).
- **Enhanced monitoring dashboard** in the console.
- **Diagnostic support scripts** per engine, run before migration.
- **Time Travel** logs for deep debugging.
- Database-side logs (source/target) via their own services.

## D. Performance tuning checklist (verified)
- Right-size the **replication instance** (CPU for heterogeneous, memory for CDC/LOBs); watch CPU, memory, IOPS, swap.
- Add **storage** if cached changes or logs are large; avoid debug logging in steady state.
- Tune `MaxFullLoadSubTasks`; use **parallel load** and **row-filter splits** for large tables.
- Drop **indexes, FKs, triggers** on target during full load; add secondary indexes before CDC; enable triggers at cutover.
- Turn off **target backups/Multi-AZ/logging** during load (RDS).
- Use **batch-optimized apply** for heavy CDC (not for Kinesis); disable FKs.
- Use **multiple tasks** for independent table groups; avoid overloading the source.
- Choose **limited LOB** with correct size; inline mode for mixed sizes.
- Network bandwidth and latency between source, instance, and target must be adequate; place the instance near the **target** or **source** depending on bottleneck, test with a POC.
- Large transactions on source (bulk updates) generate many changes → plan windows.
- Use **Parquet** and **date partitioning** for S3 targets; bigger CDC files with `CdcMinFileSize`.
- Run a **proof of concept** with realistic data volumes to measure throughput, LOBs, data type conversions.
- **Upgrade the replication engine** version carefully; test first.
- Large Oracle→Redshift/S3 full loads: use enhanced throughput settings on Serverless.

## E. Troubleshooting map (symptom → cause → fix)
- **Task fails at start** → endpoint connectivity (SG, NACL, route, DNS), wrong credentials, missing source logging (supplemental logging/binlog), missing privileges → test endpoint, check task log.
- **"Table error" for some tables** → unsupported data type, no permissions, missing PK, LOB too large, target constraint violation → assessment report and task log.
- **Data truncated** → Limited LOB size too small; VARCHAR length mismatch → raise Max LOB size or change target column.
- **FK violations during full load** → constraints enabled on target → disable until after load.
- **High target latency** → missing indexes on target, slow target IOPS, tiny instance, batch apply off → fix target, tune.
- **Replication instance `storage-full`** → verbose logs or cached changes → delete task logs, increase storage, lower log level.
- **Out-of-memory / task killed** → too many tables in parallel, large LOBs, small instance → reduce parallelism, bigger instance, split tasks.
- **CDC stuck / "log not available"** → source logs purged before DMS read them → extend retention; restart from full load or a new CDC start point.
- **Validation mismatches** → ongoing changes, collation differences, data type rounding (floats), trailing spaces → inspect `awsdms_validation_failures_v1`, adjust validation rules.
- **Duplicate records on target** → task restarted with `DO_NOTHING` prep and no PK → use TRUNCATE_BEFORE_LOAD or define PK.
- **Kinesis target loses data** → BatchApply enabled → turn off; consumers need dedupe.
- **Serverless fails with OOM** → Min/Max DCU too low → raise Min, resume.
- **Connection from on-premises DNS fails** → use Route 53 Resolver forwarding.
- **Cannot move to a lower DB version** (homogeneous) → not supported.

## F. Cost (verified)
- **Provisioned**: **hourly** by replication instance class (T2/T3, C4/C5/C6i, R4/R5/R6i), Single-AZ or Multi-AZ (Multi-AZ costs about twice). **Storage**: included amount (50 GB T-class, 100 GB C/R-class); extra GP2 storage billed.
- **T3** CPU-credit charges if you exceed the baseline average over 24 hours.
- **Serverless**: billed hourly for **DCUs** used (1 DCU = 2 GB RAM) — pay for actual capacity; max DCU only caps spend. Check each replication.
- **Homogeneous data migrations**: billed hourly **only while the migration runs**; no instance or storage fees.
- **Schema Conversion**: free; pay S3 storage it uses.
- **Database Savings Plans**: 1-year commitment ($/hour) for lower rates.
- **Data transfer**: inbound into DMS free; same-AZ transfer with RDS/EC2 free; other transfers at standard rates (cross-AZ, cross-Region, internet egress, VPN, Direct Connect).
- **Free tier**: accounts created before 15 July 2025 get 750 hours/month single-AZ `dms.t3.micro` for 1 year + 50 GB storage; newer accounts use credits and Free/Paid plans.
- **Other costs**: CloudWatch Logs, S3 (staging, S3 target), Kinesis/Redshift, NAT gateways, Secrets Manager, KMS.
- **Cost tips**: stop/delete replication instances after cutover (they bill while they exist); use Serverless for intermittent work; use smallest instance that passes the POC; avoid Multi-AZ for one-time full loads; delete old task logs; avoid unnecessary validation/Time Travel; right-size T3.
- Zero-ETL for self-managed sources into Redshift has separate charges (export, resync, change transfer) — compare to DMS.

## G. Limits and numbers to remember (verified where noted)
- Default **parallel tables in full load: 8** (max **49**).
- Default **Limited LOB max size: 32 KB**; **InlineLobMaxSize** 1–102,400 KB.
- Default replication storage **50 GB** (T) / **100 GB** (C/R); Serverless initial storage **100 GB**, scales at **90%** use.
- Serverless: **DCU = 2 GB**; stopped/failed replications deprovision after **48 hours**; default min **1 DCU**.
- Validation stops after **10,000** failures; revalidate up to **10** tables at once; PK varchar < **1,024**.
- Task log retention per replication instance: **10 days**.
- Kinesis target max LOB: **1 MB**; ParallelApply threads max **32**.
- S3 target full-load file max default **1 GB**; CDC batch interval default **60 s**.
- Commit rate during full load default **10,000**; bulk array size default **1,000**.
- Replication instance **maintenance window**: 30 minutes, weekly (random default).
- Resource quotas (instances, endpoints, tasks, subnet groups) are per Region and adjustable in Service Quotas (verify numbers).

## H. Common traps
- Assuming DMS converts schema/code objects automatically (it creates tables and PKs only).
- Leaving FK constraints/triggers on during full load.
- Believing CDC is real-time or has an SLA.
- Using full LOB mode everywhere (very slow) or Limited LOB with too small a size (truncation).
- Forgetting target LOB columns must be nullable.
- Using batch apply with Kinesis; assuming Kinesis dedupes.
- Forgetting the replication instance keeps costing after the migration.
- Not keeping source logs long enough for CDC.
- Choosing the wrong instance family (T3 for production CDC; R when CPU is the bottleneck).
- Running validation on tables without a primary key.
- Public replication instance exposed to the internet.
- Believing Serverless supports every endpoint, views, or custom CDC start points.
- Assuming homogeneous migrations include validation or can go to a lower version.
- Using an on-prem hostname without DNS forwarding.
- Not stopping tasks before upgrading source/target databases.

## I. Decision lines (exam style)
- "Migrate DB with minimal downtime" → **DMS full load + CDC**.
- "Different engine, convert stored procedures and views" → **DMS Schema Conversion** (or SCT) + DMS.
- "Same engine, native tool, serverless" → **homogeneous data migration**.
- "Unpredictable migration workload, no sizing" → **DMS Serverless**.
- "Keep replication instance highly available" → **Multi-AZ**.
- "Land DB changes in a data lake" → **DMS to S3 (Parquet, date partition)**.
- "Stream DB changes to consumers" → **DMS to Kinesis/MSK**.
- "Prove migrated data is correct" → **DMS data validation** / validation-only task.
- "Find problems before running the task" → **premigration assessment**.
- "Heavy CPU heterogeneous migration" → **C-class** instance.
- "Large table, slow full load" → **parallel load / split tasks with filters**.
- "Credentials not stored in endpoint" → **Secrets Manager**.
- "Offline petabytes" → Snow Family (see snow-family) or Data Transfer Terminal; "files" → DataSync.

## Scenarios (if → then, because)
- **If** the **`CDCLatencyTarget`** metric is high but **`CDCLatencySource`** is low, **then** check the target: **missing primary keys or indexes**, slow **IOPS** (disk speed), and the replication instance size. **This works because** low source latency means DMS reads changes fine; the delay is in **applying** them to the target.
- **If** both **`CDCLatencySource`** and **`CDCLatencyTarget`** are high, **then** investigate the **source** first (log reading, source load, long or large transactions) and the network. **This works because** a slow source delays everything after it, so target latency rises too.
- **If** an Oracle migration with **large objects (LOBs)** truncates data, **then** raise the **Max LOB size** or use **inline LOB mode**. **This works because** **Limited LOB mode** (default **32 KB**) cuts off larger values, and truncation warnings appear only in the task log.
- **If** the replication instance runs out of disk (`storage-full`), **then** lower the log level, delete old task logs, and add storage. **This works because** verbose (debug) logs and cached changes fill the instance's storage.
- **If** a partner needs only the **changes** as files, **then** run a **CDC-only** DMS task to an **Amazon S3** target. **This works because** every CDC file has a first column **`Op`** (`I`, `U`, `D`) showing the change type. If you also send a full load, add **`IncludeOpForFullLoad`** so full-load files get the same `Op` layout as CDC files.
- **If** the project must stay inside private networks, **then** use a **private** replication instance (no public IP), **VPC endpoints** for AWS services like S3 and Kinesis, an **AWS Key Management Service (KMS)** key for data at rest, **SSL mode `verify-full`** on endpoints for data in transit, and **AWS Secrets Manager** for database passwords. **This works because** traffic never needs the internet, stored data and connection info are encrypted, connections are checked against the imported CA certificate, and no passwords sit in plain text.
- **If** sensitive columns must arrive **masked** for a QA copy, **then** use **masking transformation rules** in the task's table mappings (verify types). **This works because** columns are masked during migration, so real data never reaches the non-prod target. Validation skips masked columns.
- **If** DMS needs access to an **Amazon S3** bucket in the same account, **then** create an **Identity and Access Management (IAM)** role that trusts DMS and grants only the needed S3 actions, and add **AWS Key Management Service (KMS)** permissions if the bucket uses **SSE-KMS** encryption. **This works because** DMS writes to S3 by taking on this role, and it can't encrypt with a KMS key without permission on it.
- **If** you want an audit of who started a task, **then** use **AWS CloudTrail**. **This works because** CloudTrail logs every DMS API call, such as `StartReplicationTask`.
- **If** it is **cutover day**, **then** stop writes on the source, let **change data capture (CDC)** drain until latency is near zero, run **validation**, enable triggers and constraints on the target, switch the application to the target, stop the task, and **delete the replication instance**. **This works because** draining and validating make sure the target has every change before apps use it,; triggers and constraints stay off during the load and are enabled just before cutover. The instance bills while it exists, so delete it afterwards.

## Verified from AWS docs on 2026-10-09
Read: security page (summary), monitoring page, best practices page, pricing summary, Serverless pages. Not confirmed (verify): `dms-access-for-endpoint` role details, masking transformation types, resource quota numbers, EventBridge integration, T3 credit rules, data resync availability, CloudWatch/CloudTrail minor details.

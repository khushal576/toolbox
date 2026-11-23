# Glue – 5. Security, cost, monitoring, troubleshooting, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Identity and access (IAM)
- Glue uses **IAM roles** for jobs, crawlers, interactive sessions, workflows and Data Quality runs. The role's **trust policy** must allow **`glue.amazonaws.com`** to assume it.
- The managed policy **`AWSGlueServiceRole`** gives the base Glue permissions (Catalog, logs, ENI/VPC calls, and S3 on `aws-glue-*` buckets). You still add **your own S3, KMS, Secrets Manager and database permissions**.
- The **user or role that creates a job** needs **`iam:PassRole`** on the job role (and `glue:CreateJob`). Without it you get the error about the role needing assume-role permission for the Glue service.
- A **job role** needs: read on sources, write on targets, read/write on the **temp path**, scripts and libraries in S3, **CloudWatch Logs** write, **Catalog** access, and **KMS** use if encrypted.
- Interactive sessions need `glue:CreateSession`, `glue:RunStatement`, `glue:GetSession` plus `iam:PassRole` **(verify exact list)**.
- Use **least privilege**: one role per job group, scoped to the S3 prefixes and Catalog databases it needs. Avoid `s3:*` on `*`.
- **Identity-based policies** control who can call Glue APIs. **Resource-based policies** (Data Catalog resource policy) control **cross-account** Catalog access.
- **Tags**: tag jobs, crawlers and databases. Use tags in IAM conditions (ABAC) and for cost allocation **(verify condition keys)**.
- Glue API actions use the prefix `glue:`. Crawler and job actions are separate from Catalog actions (`glue:GetTable`, `glue:GetPartitions`, `glue:BatchCreatePartition`).
- Secrets: store DB passwords in **Secrets Manager** and reference them in the connection. The job role needs `secretsmanager:GetSecretValue`.

## B. Lake Formation and fine-grained access
- **AWS Lake Formation** adds database/table/**column/row/cell-level** permissions on top of IAM for Catalog data. You **register S3 locations** with Lake Formation.
- If a table is governed by Lake Formation, a Glue **job or crawler role needs Lake Formation grants** (for example `SELECT`, and `ALTER`/`INSERT` for writes), not only S3 permission.
- **Crawlers** can use **Lake Formation credentials** to read an S3 location in the same or another account.
- **Glue 5.0+** has a built-in integration for **fine-grained access control** in Spark jobs. In Glue 4.0 you set a catalog configuration flag for Lake Formation.
- **Cell-level filters** limit Glue features: **no job bookmarks, no bounded execution, no pushdown predicates, no catalog partition predicates, no `enableUpdateCatalog`** for those tables.
- **Cross-account**: Lake Formation grants (or a Catalog resource policy + AWS RAM) let another account read your Catalog tables. Prefer Lake Formation for governance.
- **Tag-based access control (LF-TBAC)** grants by tag (for example `pii=false`) so you do not grant table by table.
- Lake Formation also gives **audit** of data access through CloudTrail.

## C. Encryption
- **Security configuration** = a reusable Glue object that sets **encryption** for what Glue **writes**. You attach it to **jobs**, **crawlers**, **dev endpoints** and interactive sessions.
- It can encrypt:
  - **S3 data written by jobs/crawlers**: **SSE-S3**, **SSE-KMS** or **CSE-KMS** (client-side).
  - **CloudWatch Logs** (KMS key).
  - **Job bookmarks** written to S3 (**CSE-KMS**).
- A security configuration **overrides** the job-level "server-side encryption (SSE-S3)" parameter. If both exist, the parameter is **ignored**.
- Using KMS: the **job role** needs `kms:Decrypt`, `kms:Encrypt`, `kms:GenerateDataKey` on the key. For **CloudWatch Logs** encryption the **KMS key policy** must allow `logs.<region>.amazonaws.com` and the roles passed to crawlers and jobs. The key must be **ENABLED**.
- Jobs or crawlers in a VPC that use a security configuration need a **route to KMS**: a **NAT gateway** or a **KMS interface VPC endpoint**. Without it: **"kms timeout"** errors for jobs and **"internal service exception"** for crawlers.
- **Data Catalog encryption**: **metadata encryption** (KMS) and **connection password encryption** (KMS). New metadata only. Existing metadata stays unencrypted until rewritten.
- **Encryption in transit**: Glue uses TLS for AWS APIs. Enable **SSL** on JDBC connections. **Kafka** connections require **TLS** bootstrap URLs (no plaintext). Self-managed Kafka needs a custom CA certificate path in S3.
- **Iceberg** tables need **their own S3 SSE** settings **in addition to** the Glue security configuration.
- **Temp bucket**: Glue may create a temp bucket if none exists. It might allow public access, so apply **S3 Block Public Access** or delete it after use.
- **Amazon S3 encryption of targets** is the data owner's job: use bucket default encryption too.

## D. Network security (VPC)
- Glue jobs and crawlers normally run in an **AWS-managed network**. To reach **private resources** (RDS, Redshift, private S3 endpoints, on-premises over VPN/Direct Connect) attach a **connection** with **VPC, subnet and security group**. Glue creates **elastic network interfaces (ENIs)** in your subnet.
- **Required settings** (and the error you get if missing):
  - A **security group** with a **self-referencing rule**: **inbound all TCP from itself** (workers talk to each other) and **outbound** all. Errors: *"Inbound rule in security group required"* / *"Outbound rule in security group required"*.
  - A **route to S3**: an **S3 gateway VPC endpoint** (or NAT). Error: *"Could not find S3 endpoint or NAT gateway for subnetId in VPC"*.
  - A **route to other AWS services** Glue calls (Glue API, CloudWatch Logs, STS, KMS, Secrets Manager): **NAT gateway** or **interface endpoints**.
  - VPC **DNS**: `enableDnsHostnames = true` when using Amazon DNS. Error: *"No private DNS for network interface found"*.
  - **Subnet IP addresses**: each worker uses an IP. Too few IPs → startup fails or queues. Use larger subnets or secondary CIDRs.
  - **IAM permissions for ec2 calls**: `ec2:DescribeVpcEndpoints`, `DescribeRouteTables`, `DescribeSubnets`, `DescribeSecurityGroups` (plus ENI create/delete). Missing ones produce named "unauthorized" errors.
- A **gateway S3 endpoint** only reaches buckets **in the same Region**. Cross-Region S3 access from a private subnet → **timeouts**. Use a NAT gateway.
- **AZ failover**: Glue checks each connection in the order listed (valid VPC/subnet, **NAT or endpoint exists**, subnet has free IPs, AZ healthy). The first healthy one is used. **All drivers and executors run in that one AZ.** Retries use the **same** connection. Error *"Could not find subnet for AZ"* → create a subnet in another AZ.
- A job can have multiple connections for failover. The first healthy one decides placement.
- To call the **Glue API privately**, create an **interface VPC endpoint** for Glue.
- **JDBC target security group** must allow inbound from the Glue security group on the DB port.
- **Interactive sessions and notebooks** use the same network model.
- Use **VPC endpoint policies** to restrict what the endpoint can reach.

## E. Audit, compliance and privacy
- **CloudTrail** records Glue API calls (create/delete jobs, start runs, Catalog changes). Send to S3/CloudWatch and alarm on risky actions.
- **Lake Formation** logs data access and grants. **CloudWatch Logs** keep job and crawler output.
- **Config** can track Glue resource changes **(verify supported types)**.
- **PII**: Macie discovers it in S3. Glue **Detect Sensitive Data** and DataBrew can mask it. Lake Formation column/cell filters hide it from users.
- Use **Data Quality** results and **tags** as evidence for governance.
- Keep **script and library buckets** private, versioned and encrypted. The script is code that runs with the job role.
- Do not hard-code secrets in scripts or job parameters. Job parameters are visible to anyone who can describe the job.

## F. Cost: what you pay for
- **ETL jobs**: **DPU-hours**. **$0.44 per DPU-hour** standard, **$0.29** for **Flex** (US pricing page; varies by Region). Billing is **per second** with a **1-minute minimum** for modern Glue versions **(verify)**.
- **Python shell**: charged by DPU too (0.0625 or 1 DPU). A tiny job is very cheap **(verify price)**.
- **Interactive sessions**: **$0.44 per DPU-hour**, default **5 DPUs**, billed per second while the session is active.
- **Streaming jobs**: billed for as long as they run.
- **Crawlers**: **$0.44 per DPU-hour**, per second (verify minimum).
- **Data Catalog**: first **1,000,000** objects and **1,000,000** requests per month **free**. Above that about **$1.00 per 100,000 objects** and **$1.00 per additional million requests**. Partitions and **partition-index items** count as objects.
- **Catalog table optimization** (Iceberg compaction, snapshot retention, orphan file deletion), **column statistics**, **materialized view refresh**: **$0.44 per DPU-hour**, per second, **1-minute minimum**.
- **Data Quality**: Catalog runs **$0.44/DPU-hour** (2 DPU, 1-minute minimum). **In ETL jobs** it is part of the job's DPU time (no extra fee).
- **DataBrew**: about **$1.00 per 30-minute interactive session**; jobs about **$0.48 per node-hour** (billed per minute).
- **Schema Registry**: **free**. **Zero-ETL**: no integration fee, pay ingestion volume + target compute.
- **Not charged by Glue**: data stored in S3 or Redshift (billed by those services). Workflows and triggers themselves **(verify)**.
- **Data transfer and other services** used by the job (S3 requests, NAT gateway processing, KMS requests, CloudWatch Logs) are billed separately. NAT data charges can surprise you.

## G. Cost: how to cut it
- **Right-size**: start with **G.1X**; move to G.2X only if memory-bound. Do not over-provision workers.
- Turn on **Auto Scaling** with a sensible maximum. Check **`glue.driver.workerUtilization`** and DPUSeconds.
- Use **Flex** for non-urgent runs (tests, backfills). Needs Glue 3.0+ and G.1X/G.2X.
- Use **G.025X + Auto Scaling** for small streams.
- **Process less data**: partition pruning, pushdown predicates, **bookmarks**, incremental processing, column pruning, Parquet.
- Use **incremental crawls** or **S3 event mode** instead of full recrawls. Do not crawl the same unchanged prefix hourly.
- Set a **timeout** that matches expected runtime (default is 8 h for 5.0+ or 48 h for 4.0 and older). A stuck job bills until it stops. Use **delay notification** for early warning.
- **Stop idle interactive sessions** and lower `%idle_timeout`. Default idle timeout is long **(verify)**.
- **Upgrade the Glue version** (newer runtimes are often faster and cheaper per job).
- Avoid **too many small partitions and indexes** (Catalog object cost). Clean up old tables and table versions.
- Use **Lambda or Athena CTAS** for tiny jobs.
- For steady heavy workloads consider **EMR/EMR Serverless** with Spot/Graviton.
- **Tag** jobs for **cost allocation** and use **Budgets**/Cost Explorer.
- Avoid retries on logic errors (retry count up to 10 re-bills each attempt).
- Compress and compact output so downstream **Athena** scans (and costs) shrink.

## H. Monitoring: where to look
- **Job run status** (console Runs tab, Studio Monitoring page, `get-job-runs`): STARTING, RUNNING, STOPPING, STOPPED, SUCCEEDED, FAILED, TIMEOUT, ERROR, WAITING.
- **CloudWatch job metrics** (enable with **`--enable-metrics`** / "Job metrics"): **driver and executor** metrics under names like `glue.driver.*` and `glue.ALL.*` (executors, memory, disk, CPU, bytes read/written). Also needed for **profiling** views.
- **Job observability metrics** (**Glue 4.0+**, enable `--enable-observability-metrics`, on by default in the Studio console). Sent every **30 seconds** to CloudWatch namespace **Glue**. Four groups:
  1. **Reliability (error classes)**: `glue.error.ALL`, `glue.succeed.ALL`, and one metric per **error category** (about **28**: OUT_OF_MEMORY_ERROR, PERMISSION_ERROR, THROTTLING_ERROR, SYNTAX_ERROR, CONNECTION_ERROR, DISK_NO_SPACE_ERROR, S3_ERROR, REDSHIFT_ERROR, LAKEFORMATION_ERROR, LAUNCH_ERROR, TIMEOUT_ERROR, GLUE_JOB_BOOKMARK_VERSION_MISMATCH_ERROR, and more).
  2. **Performance (skewness)**: `glue.driver.skewness.stage`, `glue.driver.skewness.job`. A value over 0 means the slowest task is more than **5×** the median (default factor 5). Tune with AQE skew-join settings.
  3. **Throughput (per source/sink)**: `bytesRead`, `recordsRead`, `filesRead`, `partitionsRead`, and the written counterparts. Some are **not available for JDBC and Iceberg** writes. Metrics can be missing if the job runs about a minute.
  4. **Resource utilization**: **`glue.driver.workerUtilization`** (percent of allocated workers really used; low → use Auto Scaling), driver/executor **memory** (heap, non-heap, total), and **disk** used.
- `glueContext` must be initialized for observability metrics to publish. Dimensions: `JobName`, `JobRunId` (or `ALL`), `Type`, `ObservabilityGroup`.
- **CloudWatch Logs groups**: `/aws-glue/jobs/output` (stdout), `/aws-glue/jobs/error` (stderr), `/aws-glue/jobs/logs-v2` (continuous logging), `/aws-glue/crawlers`, `/aws-glue/python-jobs/output` and `/aws-glue/python-jobs/error` (Python shell). **(verify group names)**
- **Continuous logging** (`--enable-continuous-cloudwatch-log`): logs appear **while** the job runs. Without it, full logs show **after** the job ends.
- **Spark UI** (`--enable-spark-ui true`, `--spark-event-logs-path` to S3): event logs for the **Spark history server**. Shows stages, tasks, skew, shuffles, executor adds/removes. The Spark UI logging mode can be **Standard** (run ID file names), **Legacy**, or both.
- **Job run insights** in Glue Studio highlight failure causes and suggest fixes **(verify)**.
- **Amazon EventBridge** events for **job state change** and crawler state change. Route to **SNS** or Lambda for alerts.
- **CloudWatch alarms** on `glue.error.*`, `glue.driver.workerUtilization`, run duration, and failed run counts. Use **delay notification threshold** for stuck runs.
- **CloudTrail** for who changed what.
- For capacity planning: executor metrics such as `numberMaxNeededExecutors` and `numberAllExecutors` (auto scaling).
- The Glue Studio **Monitoring page** shows run counts, status trends, DPU hours and a job-run table with links to logs/Spark UI **(verify page layout)**.

## I. Troubleshooting (symptom → cause → fix)
- **Job fails at start with "Resource unavailable"** → out of **ENIs** or subnet **IPs** → free ENIs, larger subnet, check quotas.
- **"Could not find S3 endpoint or NAT gateway for subnetId"** → no S3 route from the subnet → add **S3 gateway endpoint** or NAT.
- **"Inbound/Outbound rule in security group required"** → missing **self-referencing** rule → add it.
- **"Job run failed because the role passed should be given assume role permissions for the Glue service"** → user lacks **`iam:PassRole`** or role trust is wrong → fix both.
- **`ec2:Describe*` unauthorized errors** → job role missing those EC2 read actions → add.
- **"Could not find subnet for AZ"** → AZ not available to Glue → use a subnet in another AZ.
- **S3 "Access Denied"** → role lacks S3 permission, bucket policy blocks, or **Lake Formation** blocks → fix policy/grants.
- **S3 "connect timed out"** → bucket in **another Region** and only an S3 gateway endpoint → add **NAT**.
- **"The operation is not valid for the object's storage class"** → reading Glacier/archive partitions → **exclude storage classes**.
- **Run fails with `s3a://` listing/XML parse error** → switch to **`s3://`**.
- **Redshift job fails after ~1 hour** → temporary S3 credentials expired → restructure the long job.
- **"No private DNS for network interface found"** → VPC `enableDnsHostnames` off → enable.
- **`kms timeout` (job) / internal service exception (crawler)** in VPC with a security configuration → no route to KMS → **KMS endpoint** or NAT.
- **Executor OOM** ("Container killed by YARN for exceeding memory limits") → bigger/R workers, more partitions, fix skew.
- **Driver OOM** → too many files/partitions listed or `collect()` on large data → group files, tune bookmarks, avoid collect.
- **"No space left on device"** → shuffle spill or temp data → bigger worker, fewer shuffles.
- **Bookmarks reprocess data** → `job.commit()` missing, no `transformation_ctx`, max concurrency >1, source rewritten, non-sequential JDBC keys.
- **"Continuation update failed due to version mismatch"** → concurrent runs of a bookmarked job → set concurrency to 1.
- **Partitions not added to the Catalog from a job** → `enableUpdateCatalog` missing or schema mismatch and `updateBehavior` not `UPDATE_IN_DATABASE` → set options.
- **Crawler failed** → read **`/aws-glue/crawlers`** logs, check the role, network, and classifier. The console shows an exclamation icon with the message.
- **Athena shows no rows after crawl** → crawler made multiple tables from one prefix → separate include paths.
- **Throttling errors (`ThrottlingException`, rate exceeded)** → too many API calls or concurrent runs → add retries/backoff, **job run queuing**, or request higher quotas.
- **Writing to SQL Server with Boolean column fails** → pre-create table or map Boolean to number/string.
- **Oracle target fails on long names** → shorten with `RenameField`.
- **Interactive session or notebook fails to start (dev endpoint era)** → role/trust, instance profile, or JAVA_HOME problems **(legacy)**.
- **Job stuck / very long** → missing timeout, data skew, waiting on a locked database. Set a timeout and look at the Spark UI.
- **Observability error metric with an error category** → use that category to triage (PERMISSION_ERROR → IAM/LF; THROTTLING_ERROR → quotas).
- **Slow first run after idle** → Spark startup, large dependency install (`--additional-python-modules`), or **Flex** queue. Prefer pre-built wheels.

## J. Limits and numbers
- **Job timeout**: max **7 days (10,080 min)**. Default **2,880 min** (≤4.0) or **480 min** (≥5.0). **Retries 0–10**. **Maximum concurrency** default **1**.
- **Jobs per account**: **2,000**. **Concurrent job runs per account**: **2,000**. **Concurrent runs per job**: up to **4,000** (adjustable). **Queued job runs**: **1,000**.
- **Concurrent task DPUs per account**: **500** (some Regions **1,000** in us-east-1, us-east-2, us-west-2, ap-northeast-1, ap-southeast-2, eu-west-1). **Max spare compute capacity**: **4,000 DPUs** (spare-capacity quota **(verify what uses it)**).
- **Triggers**: **1,000** per account, **50 jobs** per trigger, **2 crawlers** per trigger. **Workflows**: **1,000**; keep **≤100 nodes** each.
- **Crawlers**: **1,000** per account, **150** running at once.
- **Catalog**: databases **10,000**; tables **200,000** per database and **1,000,000** per account; partitions **10,000,000** per table and **20,000,000** per account; table versions **100,000** per table; connections **1,000**; functions **100**; security configurations **250**; **3 partition indexes** per table.
- **Data Quality**: ruleset **2,000 rules** and **65 KB**; **100,000 statistics**, kept 2 years; concurrent runs **50** evaluation, **25** recommendation, **10** observation.
- **Schema Registry**: **100 registries**, **10,000 schema versions**, payload **170 KB**, **10 metadata pairs** per version.
- **Dev endpoints**: **25** per account, max **50 DPUs** each (legacy).
- **Zero-ETL integrations**: **40** per Region. **ML transforms**: **100**. **Ray**: **50 M-DPUs** (not adjustable).
- **Streaming**: default window **100 s**. Blank timeout = restart after **7 days**.
- **Streaming Kafka**: TLS only. **Python shell**: **0.0625 or 1 DPU**, **20 GB** local disk (about 14 GiB free `/tmp`), Python 3.9, no bookmarks.
- **Worker types**: G.025X (streaming only), G.1X, G.2X, G.4X, G.8X, G.12X, G.16X; memory-optimized R.1X–R.8X. **Flex**: G.1X/G.2X only.
- **Generative AI completions**: **10** in-flight per account (adjustable).
- Many of these are **adjustable** with Service Quotas. Check the console for your Region.

## K. Exam cheat sheet: which Glue piece for which need
- Find and catalog data automatically → **crawler**. Hand-made or Athena DDL for known tables.
- Add new partitions → crawler (incremental), `ADD PARTITION`, `MSCK REPAIR`, `enableUpdateCatalog`, or **partition projection** (Athena).
- Faster partition lookups at scale → **partition indexes** + `catalogPartitionPredicate`.
- Convert CSV/JSON to Parquet → **Glue Spark job** (or Athena CTAS).
- Process only new data → **job bookmarks** (or Iceberg incremental).
- Many small files → **groupFiles/groupSize**, compaction.
- Messy types → **DynamicFrame + resolveChoice**.
- Flatten nested JSON → **Relationalize / Unnest**.
- Continuous ETL from Kinesis/MSK → **Glue streaming job**.
- Enforce stream schemas → **Schema Registry (BACKWARD/FULL)**.
- Chain Glue jobs and crawlers → **workflow/triggers**; multi-service → **Step Functions**; Airflow → **MWAA**.
- Rules on data quality → **Glue Data Quality (DQDL)**; row-level failures → in an **ETL job**.
- No-code cleaning and profiling → **DataBrew**.
- No-code ETL authoring → **Glue Studio visual ETL**.
- Mask PII inside a job → **Detect Sensitive Data**; discover PII in S3 → **Macie**.
- Fine-grained table/column/row access → **Lake Formation** (job role needs grants).
- Encrypt job output, logs, bookmarks → **security configuration** (KMS). Encrypt metadata → **Catalog encryption**.
- Reach private DB or S3 endpoint → **connection (VPC/subnet/SG)** + S3 endpoint/NAT + self-referencing SG.
- Reduce cost → **Auto Scaling, Flex, right-size, incremental, Parquet, timeouts**.
- Copy SaaS/DynamoDB data to the lakehouse without code → **Glue zero-ETL**.

## L. Final scenarios (if → then, because)
- If a job in a private subnet reads S3 and hangs → check the **S3 gateway endpoint / NAT** and **self-referencing SG**, because workers cannot reach S3 or each other.
- If a job with a security configuration times out in a VPC → add a **KMS VPC endpoint** or NAT, because it must call KMS.
- If the person creating jobs gets an assume-role error → grant **`iam:PassRole`** and fix the role trust to `glue.amazonaws.com`.
- If another account's job must read your Catalog tables with column limits → **Lake Formation cross-account grants**, because it controls columns and rows.
- If a job reads a Lake Formation table with cell filters and bookmarks stop working → expected, because those tables do not support bookmarks or pushdown.
- If you need to prove who started and changed Glue jobs → **CloudTrail**, because it logs API calls.
- If job logs must be encrypted → security configuration with a KMS key whose policy allows **CloudWatch Logs**, because logs are encrypted via the key policy.
- If S3 output and bookmarks must be encrypted with a customer key → security configuration (**SSE-KMS** for S3, **CSE-KMS** for bookmarks).
- If monthly Glue cost jumps → check run duration, worker count, retries, streaming jobs left running, crawler schedules, interactive sessions with long idle timeouts, and NAT data charges.
- If many jobs are idle at 20% worker use → **Auto Scaling** and smaller maximum.
- If a failed job needs to page someone → **EventBridge job state change** → **SNS**, or a CloudWatch alarm on `glue.error.ALL`.
- If you need to know why jobs fail across the account → **observability error-category metrics** on a CloudWatch dashboard.
- If one stage is slow with one long task → **skewness** metric high → salt keys / AQE skew join.
- If the Spark UI is empty → enable `--enable-spark-ui` and set the **S3 event log path**, because history needs logs.
- If you hit the concurrent run quota in peaks → **job run queuing** (and request a quota raise), because runs wait instead of failing.
- If catalog costs rise with many partitions → drop unused partitions/indexes, or use **partition projection**, because each object is billed.
- If exam asks for "least operational overhead" ETL on S3 → **Glue** (serverless) over EMR; for tiny tasks **Lambda**.
- If exam asks "no-code" and "analysts" → **DataBrew** or **Glue Studio visual**; "rules for data quality" → **Glue Data Quality**.

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: Spark/Python shell job properties, pricing page, quotas page, security configurations and encryption, Data Catalog encryption note, observability metrics and error categories, troubleshooting common errors, VPC failover behavior, auto scaling, partition indexes, Data Quality (cost, limits), workflows and triggers.
Not confirmed (verify): 1-minute per-second billing minimum for jobs and crawlers, Python shell price, interactive-session IAM action list and idle default, tag-based IAM condition keys, Config support, CloudWatch log group names, Studio Monitoring page layout and job run insights, Lake Formation 4.0 vs 5.0+ flags, "workflows and triggers are free" statement, Glue Studio generative AI quota use, DataBrew prices by Region.

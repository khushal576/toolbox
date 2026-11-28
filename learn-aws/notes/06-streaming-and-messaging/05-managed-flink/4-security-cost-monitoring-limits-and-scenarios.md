# Managed Service for Apache Flink – 4. Security, cost, monitoring, troubleshooting, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. IAM: two kinds of permissions
- Application permissions = what the running Flink app can touch (Kinesis, MSK, S3, DynamoDB, Glue, CloudWatch Logs). Given by the service execution role.
- Management permissions = who can call `CreateApplication`, `StartApplication`, `UpdateApplication`, etc. Given by identity-based policies on users/roles.
- IAM action prefix is `kinesisanalytics:` (for example `kinesisanalytics:StartApplication`). API/SDK name is Kinesis Analytics V2.
- Resource ARN: `arn:aws:kinesisanalytics:<region>:<account>:application/<name>`. Wildcards allow prefix-based control (for example `application/team-a-*`).
- ABAC is supported for management actions: `aws:ResourceTag`, `aws:RequestTag`, `aws:TagKeys`. Up to 50 tags per app.
- Resource-based policies on MSF applications are not supported. You cannot name an MSF app as a principal in another resource's policy.
- Do not put lifecycle permissions (`kinesisanalytics:*`) in the execution role. That role is not used for management calls.
- Users who create or update an app need `iam:PassRole` for the execution role.

## B. Service execution role
- Required. Set with `ServiceExecutionRole` on `CreateApplication`.
- Trust policy principal: `kinesisanalytics.amazonaws.com` with `sts:AssumeRole`.
- Confused deputy protection: add `aws:SourceArn` (the app ARN) and `aws:SourceAccount` conditions to the trust policy, especially when one role is reused by many apps.
- Minimum always needed: `s3:GetObject`/`s3:GetObjectVersion` on the code object, `logs:DescribeLogGroups`, `logs:DescribeLogStreams`, `logs:PutLogEvents` on the app log stream.
- Removing S3 code or log permissions breaks start/restart and logging. AWS warns about this.
- Add per source/sink: KDS (`kinesis:GetRecords`, `GetShardIterator`, `DescribeStream`/`DescribeStreamSummary`, `ListShards`; EFO adds `RegisterStreamConsumer`, `SubscribeToShard`, `DescribeStreamConsumer`, `DeregisterStreamConsumer`), KDS sink `PutRecords`, Firehose `PutRecordBatch`, DynamoDB `BatchWriteItem`, S3 write, Glue catalog actions.
- EFO `SELF_MANAGED` lifecycle lets you drop register/deregister permissions from the role (least privilege).
- VPC apps need EC2 permissions: `DescribeVpcs`, `DescribeSubnets`, `DescribeSecurityGroups`, `DescribeDhcpOptions`, `CreateNetworkInterface`, `CreateNetworkInterfacePermission`, `DescribeNetworkInterfaces`, `DeleteNetworkInterface`.
- The console can create/update the role with the needed S3, logs and VPC permissions. With CLI/IaC you add them yourself.
- MSK IAM auth: role needs `kafka-cluster:Connect`, `DescribeTopic`, `ReadData`, `WriteData`, `DescribeGroup`, `AlterGroup` as needed.
- Cross-account access: assume a role in the other account from connector config (`aws.credentials.provider` = ASSUME_ROLE), or use the target's resource policy (KDS, S3, KMS).
- Non-IAM secrets (database passwords, SCRAM credentials): Secrets Manager, fetched at startup by code; role needs `secretsmanager:GetSecretValue`.
- Never put access keys in the JAR or runtime properties. Runtime properties are visible to anyone with `DescribeApplication`.

## C. Network: VPC configuration
- Without a VPC config, the app runs in the service network and reaches public AWS endpoints and the internet.
- With a VPC config, MSF creates ENIs in your subnets. The app can reach private resources (MSK, RDS, ElastiCache, private OpenSearch).
- The number of ENIs depends on Parallelism and ParallelismPerKPU. Subnets need enough free IPs for scale-out.
- Pick subnets in multiple AZs for resilience **(verify recommendation)**.
- Once VPC-attached, the app has no internet access unless the VPC gives it. Use private subnets + NAT gateway, or VPC endpoints.
- Trap: putting the app in a public subnet does not give internet access (ENIs get no public IP). Use private subnets with a NAT gateway.
- VPC endpoints to add for a private app: S3 gateway endpoint, Kinesis interface endpoint, CloudWatch Logs/Monitoring, KMS, Glue, DynamoDB gateway, STS, Secrets Manager, as used.
- Checkpoints and snapshots are still managed by the service for VPC apps. You do not need an endpoint for durable state.
- Security groups on the app ENIs must allow outbound to targets; target security groups must allow inbound from the app's security group.
- VPC configuration was never supported for KDA for SQL apps (only Flink apps).
- Studio deploy-as-application with durable state needs internet access from the VPC (documented workaround exists for no-internet VPCs).
- Kafka in another Region over long links → high latency; tune `receive.buffer.bytes`.

## D. Encryption
- In transit: always TLS, cannot be disabled (KDS → MSF, between internal components, MSF → Firehose).
- At rest: application code, running application storage and durable application storage (checkpoints/snapshots) are encrypted by default with AWS owned keys.
- Customer managed KMS keys (CMK): optional. Encrypt checkpoint and snapshot data in running and durable storage with your key.
- CMK supports symmetric KMS keys only.
- Key permissions needed: `kms:DescribeKey`, `kms:Decrypt`, `kms:GenerateDataKey`, `kms:GenerateDataKeyWithoutPlaintext`, `kms:CreateGrant`.
- Encryption context: `aws:kinesisanalytics:arn` = app ARN. Use it in key policy conditions to limit the key to one app.
- The operator (API caller for create/start/update) also needs key permissions; CMK validation runs as the caller.
- Not covered by CMK: sources and sinks (encrypt them on their side, for example KDS SSE-KMS, S3 SSE-KMS), application logs (no CMK for logs from your code), data in transit, old snapshots (no retroactive encryption).
- Key rotation is your job. After rotation, stop and start the app so running storage uses the new key material; otherwise only durable storage gets it.
- Change the key ARN with `UpdateApplication`; the app restarts with the new key.
- An app can start from a snapshot encrypted with an AWS owned key or an older CMK, if the caller can use both keys.
- If you pass an alias, MSF stores the resolved key ARN.
- Disabled or deleted CMK → app cannot read its state; restarts fail **(verify exact behavior)**.
- CloudTrail logs every KMS call made for the app (including dry-run `Decrypt` checks at create).

## E. Audit and logging
- CloudTrail records all MSF management API calls (`kinesisanalytics` events) as management events.
- CloudTrail does not record per-record data processing. Use app logs for that.
- CloudWatch logging option: attach a log stream ARN. Console creates `/aws/kinesis-analytics/<app>` and stream `kinesis-analytics-log-stream` plus role permissions.
- With CLI/API you must create the log group and stream and add permissions yourself.
- Monitoring log levels: `ERROR`, `WARN`, `INFO`, `DEBUG`.
- AWS recommends `INFO`. Many Flink errors are logged at INFO, not ERROR. With ERROR level you can miss them.
- `DEBUG` only temporarily. It significantly slows the application.
- Never log every record. It causes bottlenecks and backpressure.
- Metrics levels: `APPLICATION`, `TASK`, `OPERATOR`, `PARALLELISM`. More detailed = more CloudWatch metrics = more cost.
- `PARALLELISM` level can be set only with the API (`MonitoringConfigurationUpdate`), not the console.
- Logs Insights queries can find state changes to `RESTARTING`/`FAILED`, exceptions and task failures.
- If logs do not appear: check role permissions on the log stream and that the app is running.
- Do not log sensitive data. Logs cannot be CMK-encrypted by MSF (you can set encryption on the log group in CloudWatch Logs **(verify)**).

## F. Pricing (US East N. Virginia, from the pricing page)
- KPU-hour: $0.11. Billed per second.
- Orchestration: 1 extra KPU per streaming application, same rate. About $79.20 per month alone (30 × 24 × $0.11).
- Running application storage: $0.10 per GB-month; 50 GB per KPU.
- Durable application backups (snapshots): per GB-month (example on page uses $0.023) **(verify rate)**. Optional.
- Studio notebook: 2 extra KPUs per notebook (orchestration + interactive environment) plus KPUs for queries plus running storage. No durable backups in interactive mode.
- Billed on allocated KPUs, not on CPU used. Billing follows the maximum KPUs while running.
- No free tier specific to MSF.
- Example: Parallelism 8, ParallelismPerKPU 2 → 4 KPUs + 1 = 5 KPU-hours each hour = $0.55/hour ≈ $396/month, plus 200 GB storage ≈ $20/month.
- Smallest streaming app: 1 KPU + 1 orchestration = $0.22/hour ≈ $158/month + 50 GB storage ($5).
- Batch-style app running 10 minutes a day costs about $1 a month in the AWS example. Stop apps between runs.
- `READY` (stopped) apps do not bill KPUs. Snapshots still bill storage.
- Other costs not in the MSF bill: KDS shards/EFO, MSK brokers, CloudWatch logs and custom metrics, NAT gateway data, S3 requests, KMS requests.

## G. Cost optimization
- Right-size Parallelism and ParallelismPerKPU. Over-provisioned KPUs bill every hour.
- I/O-bound jobs: raise ParallelismPerKPU to fit more subtasks per KPU.
- Watch autoscaling: a short CPU spike doubles KPUs and scale-down waits 6 hours. Consider custom or scheduled scaling.
- Set the base `Parallelism` to the normal load, not the peak. Autoscaling cannot go below it.
- Stop Studio notebooks after use; each costs at least 3 KPUs while running.
- Delete old snapshots; MSF never deletes them.
- Use `INFO` logs and `APPLICATION` metric level unless debugging.
- Use incremental aggregation and state TTL to cut state, checkpoint time and storage.
- Use VPC endpoints instead of NAT for AWS service traffic from VPC apps (NAT charges per GB).
- Use EFO only when needed; polling is free beyond shard cost.
- Combine small related pipelines into one job only if they share scaling needs (each app pays its own orchestration KPU).

## H. Key CloudWatch metrics (namespace AWS/KinesisAnalytics)
| Metric | Meaning | Watch for |
|---|---|---|
| `KPUs` | KPUs in use including orchestration; 1 sample per hour | Cost; scaling events |
| `downtime` | ms the job is failing/recovering; 0 when running, -1 completed | Alarm on > 0 |
| `uptime` | ms running without interruption | Resets = restarts |
| `fullRestarts` / `numRestarts` | Count of job restarts | Rising = restart loop |
| `numberOfFailedCheckpoints` | Checkpoint failures since start | Alarm on RATE > 0 |
| `lastCheckpointDuration` | ms of last checkpoint | Steady growth = state or backpressure |
| `lastCheckpointSize` | bytes of last checkpoint | Steady growth = state leak |
| `cpuUtilization` | TaskManager JVM CPU % | > 80% → scale |
| `containerCPUUtilization` | Whole container CPU %; autoscaling input | ≥ 75% 15 min → scale up |
| `heapMemoryUtilization` | TaskManager JVM heap % | > 90% → scale or fix |
| `containerMemoryUtilization` | Whole container memory incl. RocksDB | Near 100% → OOM kill |
| `containerDiskUtilization` | Local disk % | Near 100% → more KPUs/less state |
| `oldGenerationGCTime` / `oldGenerationGCCount` | Old-gen GC | Rising = memory leak/pressure |
| `threadsCount` | Live threads | Rising = thread leak |
| `millisBehindLatest` | KDS source lag (ms) | Rising = falling behind |
| `records_lag_max` | Kafka source lag (records) | Rising = falling behind |
| `backPressuredTimeMsPerSecond` | ms per second an operator is backpressured | High = downstream slow |
| `busyTimeMsPerSecond` / `idleTimeMsPerSecond` | Busy vs idle per operator | Busy ~1000 = bottleneck |
| `numRecordsInPerSecond` / `numRecordsOutPerSecond` | Throughput | Drop below normal |
| `numLateRecordsDropped` | Late events dropped by windows | Rising = watermark too tight |
| `currentInputWatermark` / `currentOutputWatermark` | Event-time progress | Gap growing = stuck watermark |
| `managedMemoryUtilization` | RocksDB managed memory % | High = state pressure |
- Flink 2.2+: `fullRestarts` removed (use `numRestarts`); `uptime` → `runningTime`; `downtime` → `restartingTime`, `cancellingTime`, `failingTime`. Update alarms before upgrading.
- `numRecordsIn/Out` SUM over a period must be divided by 4, because MSF takes 4 metric snapshots per minute.
- `cpuUtilization` counts only the TaskManager JVM. `containerCPUUtilization` counts everything in the container.
- `heapMemoryUtilization` misses RocksDB native memory. `containerMemoryUtilization` is the better OOM predictor.
- Studio adds Zeppelin metrics: `zeppelinCpuUtilization`, `zeppelinHeapMemoryUtilization`, `zeppelinWaitingJobs`, `zeppelinServerUptime`.
- MSK source metrics also include `commitsFailed`, `commitsSucceeded`, `currentoffsets`, `committedoffsets`, `bytes_consumed_rate`.
- Some operator-level metrics (busy/idle/backpressure, managed memory) appear only at TASK/OPERATOR/PARALLELISM metric levels.

## I. Recommended alarms (from AWS)
- `downtime > 0` (Average) for every app. Means the app is failed and processing nothing.
- `RATE(numberOfFailedCheckpoints) > 0`. Alarm on the rate, not the absolute count.
- `Operator.numRecordsOutPerSecond < normal minimum`. App not making progress.
- `millisBehindLatest` (KDS) or `records_lag_max` (Kafka) above normal maximum. App falling behind.
- `lastCheckpointDuration` and `lastCheckpointSize` above normal; also watch their RATE.
- `heapMemoryUtilization` > about 90% and `cpuUtilization` > about 80% (Maximum). Time to scale.
- `threadsCount` above normal. Thread leak.
- Old GC time as a percent of a minute rising; `RATE(oldGarbageCollectionCount)` rising. Memory leak.
- `currentOutputWatermark - currentInputWatermark` growing. Old events or a stuck upstream watermark.
- Send alarms to SNS; EventBridge can also react to MSF events.

## J. Troubleshooting: symptom → cause → fix
| Symptom | Likely cause | Fix |
|---|---|---|
| `downtime` > 0, `numRestarts` rising, logs show RUNNING→FAILED | Unhandled exception (often a poison record) | Catch exceptions, side-output bad records |
| Restart loop right after an update | Incompatible state or operator ID mismatch | Set UIDs; `AllowNonRestoredState`; or `SKIP_RESTORE_FROM_SNAPSHOT`; or roll back |
| `TimeoutException: heartbeat of JobManager timed out`, "slot removed", "connection closed by remote task manager" | TaskManagers crashing from CPU/memory pressure | Scale up KPUs, lower ParallelismPerKPU, fix leaks |
| `numberOfFailedCheckpoints` rising, checkpoints time out | Too few KPUs, huge state, key skew, backpressure, GC pressure | Scale, add TTL, fix skew, fix slow operator |
| `lastCheckpointSize`/`Duration` grow forever | State never expires (no TTL, long windows, unbounded joins) | State TTL, incremental aggregates, interval joins |
| High checkpoint start delay | Backpressure slows barriers | Fix the slow downstream operator/sink |
| High checkpoint async duration | Large state upload | Reduce state, use native state types |
| Operators backpressured, last backpressured one before sink | Slow sink or slow operator after it | Scale sink target, Async I/O, raise parallelism |
| One subtask busy, others idle | Data skew / hot key | Better key, salting, two-stage aggregation |
| `millisBehindLatest` grows steadily, CPU high | Under-provisioned app | Scale up (autoscaling or manual) |
| `millisBehindLatest` grows, CPU low | I/O-bound or source throttling | Raise ParallelismPerKPU, Async I/O, EFO, more shards |
| `millisBehindLatest` spikes then recovers | App restarts | Fix restart cause |
| `ReadProvisionedThroughputExceeded`, `LimitExceededException` from KDS | Too many polling consumers or aggressive fetch settings | EFO, lower records per fetch, longer interval |
| `WriteProvisionedThroughputExceeded` on output stream | Too few shards or hot partition key | More shards/on-demand, better partition key |
| OOM, `containerMemoryUtilization` ~100% | Big state in heap, RocksDB memory, too many subtasks per KPU | Lower ParallelismPerKPU, more KPUs, smaller state |
| `Insufficient number of network buffers` | Too much parallelism/complex graph per memory | Lower ParallelismPerKPU, chain operators, support ticket |
| Event-time windows never emit | Idle shard/partition holds watermark | `withIdleness`, uniform shard assigner |
| Many late records dropped | Watermark bound too small or early watermarks at startup | Larger bound, allowed lateness, side output |
| App will not start, "unsupported connector" | Old Kinesis connector bundled (Flink 1.15+) | Use connector ≥ supported version |
| App fails to start after a JAR rebuild | JAR > 512 MiB, missing connector class, SPI clash | Slim JAR, bundle connectors, ServicesResourceTransformer |
| Cannot reach MSK/RDS | No VPC config or security group rule | VPC-configure app, allow SG inbound from app SG |
| VPC app cannot call AWS APIs | No NAT/VPC endpoint | NAT gateway in public subnet, or interface/gateway endpoints |
| Logs missing | Role lacks logs permissions or app not running | Add `logs:PutLogEvents` etc., check status |
| App stuck `UPDATING`/`STOPPING` | Snapshot restore fault or unhealthy job | Force stop, fix, restart without snapshot if needed |
| Stuck with no processing, EFO + KDS sink under backpressure | Known connector deadlock (FLINK-34071) | Force stop then start; upgrade connector when fixed |
| Upgrade succeeded but app on old runtime | System rollback happened | Read operation failure in `ListApplicationOperations`/logs |
| Throughput low with few shards and heavy parsing | Source parallelism capped by shards | Pass bytes, `rebalance()`, parse downstream |
- Debug tools: Flink dashboard (backpressure, checkpoint details, flame graphs, thread dumps), CloudWatch metrics and alarms, Logs Insights, `ListApplicationOperations`.
- Throughput testing: replace sinks with a DiscardingSink and feed generated data to find the job's max rate per parallelism.
- Backpressure reading rule: the slow operator is just downstream of the last highly backpressured operator.

## K. Limits and numbers
| Item | Value |
|---|---|
| Applications per Region per account | 100 (increase via support) |
| KPUs per application | 64 default (soft) |
| KPU size | 1 vCPU, 4 GB memory, 50 GB running storage |
| Parallelism | default 1, default max 256 |
| ParallelismPerKPU | default 1, max 8 |
| Default maxParallelism (parallelism ≤ 128) | 128 |
| Snapshots per application | 1,000 |
| Tags per application | 50 |
| Application JAR size | 512 MiB |
| Application name | 1–128 chars `[a-zA-Z0-9_.-]` |
| Checkpoint defaults | on, 60,000 ms interval, 5,000 ms min pause |
| Autoscale up | containerCPU ≥ 75% for 15 min → ×2 |
| Autoscale down | containerCPU < 10% for 6 h → ÷2 |
| Maintenance window | 8 h per Region; 10–30 s downtime |
| Studio note size / notes | 5 MiB / 1,000 |
| Studio UDFs / dependency JARs | 100 MiB / 300 MiB cumulative |
| Dashboard URL | console 12 h; CLI pre-signed must be used within 3 min |
| Orchestration | +1 KPU per app; Studio +2 KPUs |
- Most numbers above are soft limits (raise through Service Quotas or support). JAR size and ParallelismPerKPU max are hard.
- A KPU increase request must name the application (prefix) it applies to.
- Parallelism can never exceed ParallelismPerKPU × KPU limit, and scaling while keeping state can never exceed maxParallelism.

## L. Operations cheat sheet
- Health check order: status `RUNNING`? → `downtime`/restarts → checkpoints failing? → lag (`millisBehindLatest`/`records_lag_max`) → CPU/memory → backpressure in dashboard.
- Lag rising + restarts → fix the crash first; scaling a crashing app does not help.
- Lag rising + no restarts + high CPU → scale out.
- Lag rising + no restarts + low CPU → I/O bound, throttled source, or skew; scaling by CPU will not trigger.
- Checkpoint failing + backpressure → fix throughput first; barriers are stuck behind buffered data.
- Checkpoint size growing + no traffic growth → state leak; add TTL.
- Before any risky update: take a named snapshot, enable system rollback, set UIDs.
- After any update: watch `numRestarts` (should stay 0), `runningTime`/`uptime` (should grow), checkpoint metrics (should match the baseline).
- Use EventBridge Scheduler or a Lambda to create regular named snapshots for point-in-time restore.
- Use `ListApplicationOperations` to see what the service did (autoscale, maintenance, rollback) and when.
- Tag apps by team, environment and cost center for ABAC and Cost Explorer.
- Infrastructure as Code: CloudFormation resource `AWS::KinesisAnalyticsV2::Application` (plus logging option and output resources); CDK constructs exist **(verify current CDK module status)**.
- CI/CD: build JAR → upload to S3 with a new key/version → `UpdateApplication` with new code location → snapshot restore.
- Pass `ObjectVersion` for the code object so a deploy is pinned to an exact S3 version.

## M. Exam decision shortcuts
- "Stateful", "windows", "joins", "event time", "watermarks", "exactly-once", "sub-second", "complex event processing" → Managed Service for Apache Flink.
- "Interactive SQL on streams", "notebook", "ad hoc exploration of a stream" → MSF Studio.
- "No code delivery to S3/Redshift/OpenSearch with buffering" → Amazon Data Firehose.
- "Lightweight per-record processing", "pay per invocation" → Lambda event source mapping.
- "Spark team", "micro-batch", "Glue catalog ETL from Kafka/Kinesis" → Glue streaming ETL.
- "Full control of Flink config, many jobs, custom cluster" → Flink on EMR.
- "Kinesis Data Analytics for SQL" in a modern scenario → not available; replace with MSF or Studio.
- "Least operational overhead for stateful streaming" → MSF over EMR Flink or self-managed KCL apps.

## Scenarios: "If X → Y, because Z"
- **If** an IoT stream needs real-time **anomaly alerts per device**, **then** use **Managed Service for Apache Flink (MSF)** with **keyed state** holding running stats (mean/stddev) per device, or **Async I/O** calls to an **Amazon SageMaker** endpoint. Send alerts to a **Kinesis Data Streams (KDS)** stream, where **AWS Lambda** publishes them to **Amazon Simple Notification Service (SNS)**. **This works because** Flink keeps per-device state between records and can flag values far from normal, while Lambda handles the notification step.
- **If** clickstream data must be grouped into user sessions that end after **30 minutes of inactivity**, **then** use **Managed Service for Apache Flink (MSF)** with **event-time session windows** (30-minute gap per user), and write session length and page count to **Amazon S3** or **Apache Iceberg** tables. **This works because** session windows close after a gap with no events, so their length varies per user, and event time keeps results correct when events arrive late.
- **If** each order event needs customer data from **Amazon DynamoDB**, **then** use **Async I/O** in Managed Service for Apache Flink (MSF), or a SQL **lookup join** with the cache on. **This works because** Async I/O calls the table without blocking the operator thread; blocking calls slow the operator and cause **backpressure** upstream. The lookup cache cuts calls to the table.
- **If** streaming ETL must land **Parquet** in **Amazon S3** partitioned by hour for **Amazon Athena**, **then** use the Managed Service for Apache Flink (MSF) **FileSink** with a **bucket assigner** (for example `dt=YYYY-MM-DD/hour=HH`); if there is no stateful logic, **Amazon Data Firehose** can do it without code. **This works because** FileSink finishes files on each checkpoint, giving **exactly-once** file output, and hourly partitions let Athena prune data. The catch: Parquet files roll on every checkpoint, so short intervals make small files.
- **If** change data capture (CDC) must **upsert** into a data lake table with **exactly-once**, **then** send it from Managed Service for Apache Flink (MSF) to **Apache Iceberg v2** tables in the **AWS Glue Data Catalog** or **Amazon S3 Tables**, plus regular **compaction**. **This works because** the Iceberg sink commits on each checkpoint (exactly-once) and v2 tables support upserts. Each commit adds a table snapshot and small files, so compaction and snapshot expiry are needed.
- **If** a security team needs app state encrypted with **their own key**, **then** set a **symmetric** customer managed key (CMK) from **AWS Key Management Service (KMS)** on the app. **This works because** by default the service encrypts code, running storage and durable storage (checkpoints and snapshots) with **AWS owned keys**. The catch: the CMK covers checkpoint and snapshot data only, not sources, sinks, app logs or old snapshots, so encrypt sources and sinks on their own side.
- **If** one **AWS Key Management Service (KMS)** key must be limited to **one app**, **then** add a key policy condition on `kms:EncryptionContext:aws:kinesisanalytics:arn` equal to that app's ARN. **This works because** Managed Service for Apache Flink (MSF) sends the app ARN as the **encryption context** on its KMS calls.
- **If** the customer managed key (CMK) was **rotated**, **then** **stop and start** the app. **This works because** running storage keeps the old key material until a restart; without it, only durable storage gets the new material. Key rotation is your job.
- **If** app logs contain personal data (PII), **then** remove it from the logs in your code. **This works because** Managed Service for Apache Flink (MSF) **cannot** encrypt application logs with a customer managed key (CMK), so sensitive data should not be logged.
- **If** the app must read an **Amazon Managed Streaming for Apache Kafka (MSK)** cluster in private subnets, **then** add a **VPC configuration** with **private subnets** and **security groups**: the app's group allows outbound to the brokers, and the brokers' group allows inbound from the app's group. **This works because** MSK has no public endpoint by default; with a VPC config, the service creates network interfaces (ENIs) in your subnets. Leave enough free IPs, since the ENI count grows with parallelism.
- **If** a VPC-attached app suddenly cannot call **Amazon DynamoDB**, **then** add a **DynamoDB gateway endpoint**, or a **NAT gateway** for private subnets. **This works because** once attached to a VPC, the app has no internet access unless the VPC gives it. A public subnet alone does not help, because the app's ENIs get no public IP. Endpoints also avoid NAT per-GB charges.
- **If** many teams share one AWS account, **then** use **attribute-based access control (ABAC)** with `aws:ResourceTag` conditions and **name-prefix ARNs** (for example `application/team-a-*`) in **Identity and Access Management (IAM)** policies. **This works because** Managed Service for Apache Flink (MSF) supports tags (up to **50** per app) and resource-level permissions for management actions. Resource-based policies on MSF apps are not supported.
- **If** one **service execution role** is reused by many apps, **then** add `aws:SourceArn` (the app ARN) and `aws:SourceAccount` conditions to the role's **trust policy**. **This works because** these conditions prevent **confused deputy** access, where the service could be used to act with the role for an app or account it should not serve.
- **If** a user gets **AccessDenied** on `CreateApplication` with a role, **then** grant them `iam:PassRole` on the **service execution role**. **This works because** the caller passes the role to the service, and passing a role needs that permission.
- **If** auditors ask who **stopped** the app, **then** look for the `StopApplication` event in **AWS CloudTrail**. **This works because** CloudTrail records all management API calls as management events; it does not record per-record processing.
- **If** you alarm on `numberOfFailedCheckpoints > 0` and the alarm fires forever, **then** alarm on `RATE(numberOfFailedCheckpoints) > 0` instead. **This works because** the metric is **cumulative since the app started**, so after one failure it stays above 0.
- **If** the monthly bill **doubled** after a traffic spike, **then** autoscaling most likely doubled the Kinesis Processing Units (KPUs) and has not scaled down yet. **This works because** a CPU spike (≥ 75% for 15 minutes) doubles parallelism, but scale-down needs **under 10% CPU for 6 hours**. Consider custom or scheduled scaling, and set base Parallelism to normal load, not peak.
- **If** a nightly **10-minute** batch job runs on Managed Service for Apache Flink (MSF), **then** **stop** the app between runs. **This works because** apps in **READY** status bill no Kinesis Processing Units (KPUs); AWS's example of such a job costs about **$1 a month**. Snapshots still bill storage.
- **If** a **Managed Service for Apache Flink (MSF) Studio** notebook was left running all weekend, **then** it billed at least **3 Kinesis Processing Units (KPUs)** every hour. **This works because** each notebook adds **2 extra KPUs** (orchestration plus the interactive environment) on top of the KPUs running queries. Stop notebooks after use.
- **If** the Kinesis Processing Unit (KPU) count looks **1 higher** than Parallelism ÷ ParallelismPerKPU, **then** the extra one is the **orchestration KPU**. **This works because** every streaming app pays one extra KPU for orchestration (about **$79.20 a month** alone at $0.11 per KPU-hour), and it shows in the `KPUs` metric.
- **If** Flink errors are missing from logs at **ERROR** level, **then** switch the log level to **INFO**, as AWS recommends. **This works because** Flink logs many errors at INFO, not ERROR.
- **If** the app slows down after you enabled **DEBUG** logging, **then** return to **INFO**. **This works because** DEBUG significantly slows the application and should be used only for a short time.
- **If** `millisBehindLatest` (the Kinesis source lag) rises while CPU is low and the stream is shared with other readers, **then** switch the source to **Enhanced Fan-Out (EFO)**. **This works because** polling consumers share each shard's read limits (**2 MB/s** and **5 reads/s**), so the app is throttled, not short of CPU. EFO gives the app its own 2 MB/s per shard, at extra cost.
- **If** `heapMemoryUtilization` looks fine but TaskManagers are killed for out-of-memory (OOM), **then** watch `containerMemoryUtilization` instead. **This works because** **RocksDB** state uses native memory outside the Java heap; the container metric includes it, so it is the better OOM predictor. Fixes: lower ParallelismPerKPU, add KPUs or reduce state.
- **If** one subtask shows `busyTimeMsPerSecond` near **1000** while the others are idle, **then** fix the **key skew** (a better key, salting, or two-stage aggregation). **This works because** a hot key always goes to the same subtask, so adding subtasks does not spread its load.
- **If** you are upgrading to **Flink 2.2**, **then** first move alarms from `fullRestarts`, `uptime` and `downtime` to `numRestarts`, `runningTime`, and `restartingTime`/`cancellingTime`/`failingTime`. **This works because** in Flink 2.2 `fullRestarts` is removed and `uptime`/`downtime` are deprecated, so old alarms would stop working.
- **If** a question asks for **exactly-once** processing from **Kinesis Data Streams (KDS)** to **Amazon S3**, **then** use **Managed Service for Apache Flink (MSF)** with **checkpoints** plus a **FileSink** or **Apache Iceberg** sink. **This works because** end-to-end exactly-once needs a replayable source (KDS), checkpointed state and a transactional sink, and both sinks commit on checkpoint. **AWS Lambda** and **Amazon Data Firehose** are only at-least-once.
- **If** the requirement today is "**real-time SQL on a stream without managing servers**", **then** use **Managed Service for Apache Flink (MSF) Studio** or a **Flink SQL** MSF app. **This works because** **Kinesis Data Analytics (KDA) for SQL** is gone (apps deleted from 27 January 2026), and MSF needs no servers or clusters.
- **If** a team must **reprocess the last 7 days** after a bug fix, **then** start the fixed app **without a snapshot**, with the Kinesis start position at `AT_TIMESTAMP`, and make sure **Kinesis Data Streams (KDS)** retention is **≥ 7 days**. **This works because** replay depends on source retention: KDS keeps **24 hours** by default and up to **365 days**. Records are reprocessed, so sinks must handle duplicates.
- **If** an account needs more than **100 applications** in a Region, or an app needs more than **64 Kinesis Processing Units (KPUs)**, **then** request **quota increases**. **This works because** both are default soft limits (100 apps per Region per account, 64 KPUs per app). A KPU increase request must name the application.
- **If** a **Flink Dashboard** link created from the CLI does not open, **then** generate a new one with `CreateApplicationPresignedUrl` and open it within **3 minutes**. **This works because** CLI pre-signed URLs expire fast, while the console link lasts 12 hours.

Verified from AWS docs on 2026-11-02 (MSF IAM pages: how MSF works with IAM, application role permissions; VPC pages and VPC permissions; data protection and key management (CMK); CloudWatch logging and monitoring levels; metrics and dimensions incl. Flink 2.2 changes; recommended alarms; troubleshooting pages: restarts, throughput, state growth, checkpoints, checkpoint timeouts, backpressure, source throttling; quotas; resilience; pricing page).
Unconfirmed (verify): CDK module status for MSF; durable backup rate ($0.023/GB-month from the page example); multi-AZ subnet recommendation for VPC apps; behavior when the CMK is disabled or deleted; CloudWatch Logs log-group KMS encryption with MSF; exact KDS/EFO IAM action list for the connector version.

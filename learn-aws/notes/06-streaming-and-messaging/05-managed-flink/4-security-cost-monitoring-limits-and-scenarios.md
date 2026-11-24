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
- If an IoT stream needs real-time anomaly alerts per device → MSF with keyed state (running stats) or Async I/O to a SageMaker endpoint, sink to KDS → Lambda → SNS, because Flink keeps per-device state and Lambda handles notification.
- If clickstream must be grouped into user sessions with 30-minute inactivity → MSF event-time session windows, written to S3/Iceberg, because sessions are variable length per user.
- If each order event needs customer data from DynamoDB → MSF Async I/O (or lookup join with cache), because blocking calls cause backpressure.
- If streaming ETL must land Parquet in S3 partitioned by hour for Athena → MSF FileSink with bucket assigner (or Firehose if no stateful logic), because FileSink commits exactly-once on checkpoint.
- If CDC must upsert into a data lake table with exactly-once → MSF → Iceberg v2 in Glue catalog or S3 Tables, plus compaction, because Iceberg commits on checkpoint and supports upserts.
- If a security team needs app state encrypted with their own key → set a symmetric CMK on the app, because default encryption uses AWS owned keys.
- If one key must be limited to one app → key policy condition on `kms:EncryptionContext:aws:kinesisanalytics:arn`, because MSF sends the app ARN as encryption context.
- If the key was rotated → stop and start the app, because running storage keeps the old key material until restart.
- If logs contain PII → remove it from logs, because MSF cannot encrypt app logs with a CMK.
- If the app must read an MSK cluster in private subnets → VPC config with private subnets and SGs, because MSK has no public endpoint by default.
- If a VPC app suddenly cannot call DynamoDB → add a DynamoDB gateway endpoint or NAT, because VPC-attached apps lose default internet access.
- If many teams share one AWS account → ABAC on `aws:ResourceTag` and name-prefix ARNs in IAM policies, because MSF supports tags and resource-level permissions.
- If one execution role is reused by many apps → add `aws:SourceArn`/`aws:SourceAccount` to the trust policy, because that prevents confused deputy access.
- If a user gets AccessDenied on `CreateApplication` with a role → grant `iam:PassRole` on the execution role, because the caller passes the role to the service.
- If auditors ask who stopped the app → CloudTrail `StopApplication` event, because management calls are logged.
- If you only alarm on `numberOfFailedCheckpoints > 0` and it fires forever → alarm on RATE, because the metric is cumulative since start.
- If the monthly bill doubled after a traffic spike → autoscaling doubled KPUs and has not scaled down yet, because scale-down needs 6 hours under 10% CPU.
- If a nightly 10-minute batch job runs on MSF → stop the app between runs, because READY apps bill no KPUs.
- If a Studio notebook was left running all weekend → it billed at least 3 KPUs per hour, because Studio adds 2 KPUs plus query KPUs.
- If the KPU count seems 1 higher than Parallelism ÷ ParallelismPerKPU → that is the orchestration KPU, because every app pays one.
- If Flink errors are missing at ERROR log level → switch to INFO, because Flink logs many errors at INFO.
- If the app slows after enabling DEBUG logging → return to INFO, because DEBUG significantly hurts performance.
- If `millisBehindLatest` rises with low CPU and the source is shared → switch the source to EFO, because polling consumers share shard read limits.
- If `heapMemoryUtilization` is fine but TaskManagers are OOM-killed → watch `containerMemoryUtilization`, because RocksDB native memory is outside the heap.
- If one subtask is at busyTime 1000 ms/s and others idle → fix key skew, because scaling adds subtasks the hot key cannot use.
- If upgrading to Flink 2.2 → move alarms from `fullRestarts`/`uptime`/`downtime` to new metrics, because those are removed or deprecated.
- If a question asks for exactly-once processing from KDS to S3 → MSF with checkpoints + FileSink/Iceberg, because Lambda and Firehose are at-least-once.
- If the requirement is "real-time SQL on a stream without managing servers" today → MSF Studio or Flink SQL app, because KDA for SQL is gone.
- If a team must reprocess the last 7 days after a bug fix → start the fixed app without snapshot at `AT_TIMESTAMP`, with KDS retention ≥ 7 days, because replay depends on source retention.
- If an app needs more than 100 apps or 64 KPUs → request quota increases, because both are default limits.
- If the dashboard link from the CLI does not open → generate a new one and open within 3 minutes, because pre-signed URLs expire fast.

Verified from AWS docs on 2026-11-02 (MSF IAM pages: how MSF works with IAM, application role permissions; VPC pages and VPC permissions; data protection and key management (CMK); CloudWatch logging and monitoring levels; metrics and dimensions incl. Flink 2.2 changes; recommended alarms; troubleshooting pages: restarts, throughput, state growth, checkpoints, checkpoint timeouts, backpressure, source throttling; quotas; resilience; pricing page).
Unconfirmed (verify): CDK module status for MSF; durable backup rate ($0.023/GB-month from the page example); multi-AZ subnet recommendation for VPC apps; behavior when the CMK is disabled or deleted; CloudWatch Logs log-group KMS encryption with MSF; exact KDS/EFO IAM action list for the connector version.

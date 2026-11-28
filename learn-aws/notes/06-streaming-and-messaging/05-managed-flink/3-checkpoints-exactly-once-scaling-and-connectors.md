# Managed Service for Apache Flink – 3. Checkpoints, snapshots, exactly-once, scaling and connectors

Short notes. Each point is a fact you can be asked about.

## A. Checkpoints
- Checkpoint = automatic, periodic, consistent copy of all operator state plus source positions (Kinesis sequence numbers, Kafka offsets).
- Used for automatic recovery after failures (task crash, instance failure, unhandled exception, maintenance).
- Flink inserts checkpoint barriers into the stream. Each operator snapshots its state when the barrier passes (aligned checkpoint).
- MSF stores checkpoints in service-managed durable storage (S3). You never see the bucket.
- Defaults (`ConfigurationType=DEFAULT`): `CheckpointingEnabled` true, `CheckpointInterval` 60,000 ms (1 minute), `MinPauseBetweenCheckpoints` 5,000 ms.
- Trap: with `ConfigurationType=DEFAULT`, the defaults win even if your code or CLI sets other values. Set `CUSTOM` to change them.
- `MinPauseBetweenCheckpoints` stops back-to-back checkpoints when one takes longer than the interval.
- Shorter interval → less data reprocessed after failure, and sinks that commit on checkpoint (Kafka transactions, FileSink, Iceberg) publish sooner.
- Shorter interval catch → more overhead, more S3 traffic, and more small files for file/Iceberg sinks.
- Longer interval → less overhead but more reprocessing after failure and higher end-to-end latency for transactional sinks.
- Checkpoints are owned by the service. You cannot list or restore a specific checkpoint by name. You restore from snapshots.
- Keep checkpointing on in production. Turning it off means restarts lose state and position.
- Checkpoint stages (Flink dashboard): start delay (barrier waiting), alignment, sync duration (snapshot), async duration (upload to S3), acknowledge (and sink commits).
- High start delay → backpressure or a busy operator slows the barrier.
- High async duration → large state or many state files to upload.
- High sync duration → slow user `snapshotState()` code.
- Unaligned checkpoints let barriers overtake buffered data under backpressure **(verify MSF support/config)**.
- Flink 2.3 on MSF: "checkpoint during recovery" is opt-in via a support case.

## B. Snapshots (savepoints)
- Snapshot = MSF's name for a Flink savepoint. A user- or service-triggered full copy of state.
- Create manually with `CreateApplicationSnapshot`. Also `ListApplicationSnapshots`, `DescribeApplicationSnapshot`, `DeleteApplicationSnapshot`.
- Automatic snapshots: with `ApplicationSnapshotConfiguration.SnapshotsEnabled = true`, MSF takes a snapshot on every update, scale and stop.
- From Flink 1.15, automatic snapshots use stop-with-savepoint. Intermediate savepoints do not commit side effects (no partial transactional commits).
- `SnapshotsEnabled=false` causes data (state) loss on updates. AWS docs say this directly.
- AWS advice: turn snapshots off while developing/troubleshooting an unhealthy app (stop would try to snapshot), then on in production.
- AWS advice: create snapshots several times a day for production apps (schedule with EventBridge Scheduler + API call).
- Limit: 1,000 snapshots per application. Automatic snapshots count toward it.
- At the limit, manual `CreateApplicationSnapshot` fails with `LimitExceededException`. Automatic snapshots on update/scale/stop still succeed.
- MSF never deletes snapshots. You delete old ones yourself (cost and limit).
- Snapshots are billed as durable application backups (per GB-month).
- Snapshot status must be `READY` before you rely on it.
- For two-phase-commit sinks, AWS recommends system snapshots (stop/update) over manual `CreateApplicationSnapshot`.
- Snapshots taken with AWS owned keys can be restored after switching the app to a customer managed key (caller needs access to both keys).

## C. Restoring state
- `ApplicationRestoreConfiguration` on `StartApplication` or `UpdateApplication`:
  - `RESTORE_FROM_LATEST_SNAPSHOT`: continue from the newest snapshot (the usual default when snapshots are on) **(verify)**.
  - `RESTORE_FROM_CUSTOM_SNAPSHOT` + `SnapshotName`: start from a chosen snapshot (rewind).
  - `SKIP_RESTORE_FROM_SNAPSHOT`: start with empty state (sources start from their configured initial position).
- Restore matches state to operators by operator ID. Set `.uid()` on every stateful operator.
- Operator added: no state for it, restore works without changes.
- Operator removed: snapshot has state with no operator → fault, unless `AllowNonRestoredState=true` in `FlinkRunConfiguration`.
- Operator changed compatibly (compatible schema evolution): restore works.
- Incompatible state → app faults and can be stuck in `STOPPING` or `UPDATING`. Use `SKIP_RESTORE_FROM_SNAPSHOT` or fix code.
- Changing maxParallelism or key types breaks restore of keyed state.
- Restoring a snapshot also restores source positions. Records after the snapshot are reprocessed. Sinks must tolerate this (idempotent or transactional).
- To reprocess history: start without snapshot and set the source initial position to `TRIM_HORIZON`/`AT_TIMESTAMP` (Kinesis) or earliest/timestamp offsets (Kafka).
- Replay limit = source retention (KDS 24 h default, up to 365 days; Kafka topic retention).

## D. Exactly-once vs at-least-once
- Inside Flink, checkpoints give exactly-once state: after recovery, each record affects state exactly once.
- End-to-end exactly-once needs three things: a replayable source, checkpointed state, and a transactional or idempotent sink.
- Replayable sources: Kinesis Data Streams, Kafka/MSK, files in S3. They can be re-read from a saved position.
- Not replayable: a plain socket or a non-durable HTTP push. Data in flight is lost on failure.
- Transactional sink (two-phase commit): writes go to a pending transaction, committed only when the checkpoint completes.
- Kafka sink with `DeliveryGuarantee.EXACTLY_ONCE` uses Kafka transactions. Needs a `transactionalIdPrefix`.
- Kafka exactly-once trap: consumers downstream must use `isolation.level=read_committed`, or they see uncommitted/aborted data.
- Kafka exactly-once trap: transaction timeout must be larger than checkpoint interval + max restart time, and not above the broker `transaction.max.timeout.ms` (15 minutes default).
- Kafka exactly-once catch: data is visible only after each checkpoint → latency equals checkpoint interval.
- FileSink (S3): files move in-progress → pending → finished; finished on checkpoint. Exactly-once file output.
- FileSink with bulk formats (Parquet, ORC, Avro) rolls files only on checkpoint. Checkpoint interval sets file size and freshness.
- Iceberg sink: commits a snapshot of the table on each checkpoint. Exactly-once into Iceberg tables.
- Idempotent sink = writing the same record twice gives the same result. Upserts by primary key into DynamoDB, JDBC (with upsert), OpenSearch (with fixed document ID).
- At-least-once sinks: Kinesis Data Streams sink, Firehose sink, DynamoDB sink (append), SQS sink. Duplicates are possible after a restart.
- KDS sink also does not guarantee order (`PutRecords` batches can reorder).
- To make at-least-once sinks safe: include a unique event ID and dedupe downstream (DynamoDB conditional write, Iceberg MERGE, Redshift MERGE).
- Lambda, Firehose and KCL consumers are at-least-once. Exam answer for "exactly-once stream processing" usually = Flink checkpoints + transactional/idempotent sink.

## E. Fault tolerance and availability
- MSF restarts failed tasks automatically from the latest checkpoint.
- The job restarts as a whole (or region of the job graph) on failure. Records since the last checkpoint are reprocessed.
- Unhandled exception in an operator → job fails over and restarts → can loop forever if the bad record is always there (poison pill).
- Fix for poison pills: catch exceptions in operators, send bad records to a side output/DLQ, keep going.
- Each app runs in its own single-tenant Flink cluster on Amazon EKS. The JobManager runs in high-availability mode (ZooKeeper) across multiple AZs.
- Host or AZ problems are handled by automatic migration. MSF first tries to recover inside the running cluster from the latest checkpoint.
- Durable state (checkpoints/snapshots) is stored in S3 across AZs. Running state is rebuilt from it.
- Cross-Region DR is your job: run a second app in another Region, replicate the source (MSK Replicator, KDS cross-Region via consumers), restore from your own exported data. Snapshots cannot be copied across Regions **(verify)**.

## F. Autoscaling
- Autoscaling is on by default (`AutoScalingEnabled` true).
- Trigger metric: `containerCPUUtilization` (maximum per minute).
- Scale up: CPU ≥ 75% for 15 consecutive 1-minute datapoints (15 minutes). Parallelism doubles. KPUs double.
- Scale down: CPU < 10% for 360 consecutive 1-minute datapoints (6 hours). Parallelism halves (rounded up).
- ParallelismPerKPU is not changed by autoscaling. Only Parallelism changes.
- Autoscaling never goes below the configured `Parallelism`. Your setting is the floor.
- Autoscaling never goes above the KPU limit (64 default) or the job's maxParallelism.
- During scaling the app is in `AUTOSCALING` status and has downtime (stop with snapshot, restart with new parallelism).
- Only CPU triggers built-in autoscaling. Memory, lag, backpressure do not.
- Trap: an I/O-bound job (low CPU, waiting on a slow sink) will never autoscale even with huge lag.
- Trap: a memory-bound job can crash with OOM without ever reaching 75% CPU.
- Trap: CPU spikes cause doubling (cost doubles); scale down waits 6 hours, so you pay for the bigger size a long time.
- Custom autoscaling: AWS sample using CloudWatch alarms (for example `millisBehindLatest`, MSK lag) + Step Functions/Lambda calling `UpdateApplication` with new parallelism.
- Scheduled scaling: AWS sample using EventBridge Scheduler to set parallelism at fixed times (for predictable daily peaks).
- Custom and scheduled scaling must also stay within maxParallelism.
- Studio notebooks do not autoscale; apps deployed from them do.

## G. Manual scaling
- Set `AutoScalingEnabled=false`, then set `Parallelism` and `ParallelismPerKPU` with `UpdateApplication`.
- Every parallelism change restarts the job from a snapshot. Plan it outside peak hours.
- Choose manual when you need no surprise downtime or cost changes.
- Scale-out rule of thumb: source parallelism up to the number of shards/partitions; heavier operators can be wider than the source.
- Scaling MSF does not scale the source. A KDS stream with too few shards or a sink with low throughput still limits throughput.
- When you reshard KDS, consider passing the new shard count as a runtime property for source parallelism.
- `Insufficient number of network buffers` error: lower ParallelismPerKPU (more memory per subtask, more KPUs) or simplify/chain the job graph.

## H. Kinesis Data Streams source
- Current source: `KinesisStreamsSource` (FLIP-27, connector 5.x for Flink 1.19/1.20, `flink-connector-aws-kinesis-streams` 6.x for Flink 2.x).
- Legacy source: `FlinkKinesisConsumer` (`SourceFunction`). Removed in Flink 2.x.
- Default start position: `LATEST`. Set `TRIM_HORIZON` or `AT_TIMESTAMP` to read older data.
- Trap: a new app with `LATEST` and no snapshot skips everything written before it started.
- Reader types: polling (shared throughput, `GetRecords`) or EFO (`READER_TYPE=EFO`, `SubscribeToShard`).
- Polling shares the shard's 2 MB/s read and 5 reads/s with all other polling consumers.
- EFO gives this app its own 2 MB/s per shard and ~70 ms push latency. Costs extra per consumer-shard-hour and per GB.
- EFO consumer name (`EFO_CONSUMER_NAME`) must be unique per stream. Reusing a name kicks out the other consumer.
- EFO lifecycle: `JOB_MANAGED` (default; the job registers and deregisters the consumer) or `SELF_MANAGED` (you register it and pass the ARN, for least-privilege roles).
- KDS limits registered EFO consumers per stream (20 for provisioned / On-demand Standard; 50 for On-demand Advantage).
- Shard discovery runs every 10 seconds by default. New shards after resharding are picked up automatically.
- Parent shards are read to the end before children, so per-key order is kept across resharding.
- `uniformShardAssigner` (default) spreads shards evenly over source subtasks by hash key range.
- Older connector trap: defaults fetch 10,000 records per `GetRecords` every 200 ms, but a shard returns at most 10,000 records / 2 MB per call and 5 calls/s. Many consumers → `ReadProvisionedThroughputExceeded`/`LimitExceededException`.
- Fix for read throttling: fewer records per call, longer interval, adaptive reads (legacy consumer), or EFO.
- Known issue (connector 5.0/6.0 EFO): failures on resharding (FLINK-37648) and possible deadlock with `KinesisStreamsSink` under backpressure (force stop + start to recover).
- Kinesis records can be up to 10 MiB in KDS now; check connector support for large records.
- Default record timestamp = approximate arrival time. Assign event-time timestamps from the payload if you need true event time.
- Metric: `millisBehindLatest` per stream/shard. 0 = caught up; growing = falling behind; -1 = not reported yet.
- Flink 2.x KDS connector 6.x removed `bytesRequestedPerFetch`. `millisBehindLatest` is the only KDS source metric.
- Cross-account KDS read: assume a role in the other account in the connector config, or use a KDS resource-based policy.

## I. Kinesis Data Streams sink
- `KinesisStreamsSink` (async sink framework). Batches `PutRecords` calls.
- At-least-once. Duplicates possible after restart; order not guaranteed.
- Partition key from a `PartitionKeyGenerator`. A constant key sends all data to one shard (hot shard, throttling).
- Write throttling (`WriteProvisionedThroughputExceeded`) → backpressure into the Flink job. Add shards or use on-demand mode.
- Do not use the sink connector for records over 1 MiB **(verify current limit)**.
- Legacy `FlinkKinesisProducer` (KPL-based) is removed in Flink 2.x.

## J. Kafka / Amazon MSK
- `KafkaSource` (FLIP-27). Set bootstrap servers, topics or topic pattern, group ID, starting offsets (earliest, latest, committed, timestamp).
- Offsets are stored in Flink checkpoints. Committing offsets back to Kafka is only for monitoring (`commitsSucceeded`, `commitsFailed`, `committedoffsets`).
- A failed offset commit to Kafka does not affect Flink's correctness.
- `KafkaSink` delivery guarantees: `NONE`, `AT_LEAST_ONCE`, `EXACTLY_ONCE` (transactions).
- MSK auth: IAM access control (use `aws-msk-iam-auth` library and the app's role), SASL/SCRAM (secrets in Secrets Manager), or mTLS.
- MSK in a VPC → the MSF app must be VPC-configured into subnets that can reach the brokers, with a security group allowed on broker ports.
- MSK Serverless supports IAM auth only.
- Metric: `records_lag_max` (max records behind for any partition). Rising = falling behind.
- Kafka in another Region with high latency and idle consumers → raise `receive.buffer.bytes` (for example 2 MB).
- `upsert-kafka` SQL connector: reads/writes a changelog keyed by primary key (latest value per key). Used for temporal joins and updating results.
- Topic partitions cap source parallelism, like shards in Kinesis.
- Known issue: the Kafka connector in Flink 1.15 has an open-source bug fixed in later versions; upgrade.

## K. S3, files, Iceberg
- FileSource reads files (one-time or continuous directory monitoring). FileSink writes to S3 (bundled with Flink, always available).
- S3 access works with the app's IAM role out of the box. No keys.
- FileSink row formats (JSON, CSV) roll by size, time or inactivity. Bulk formats (Parquet, ORC) roll on every checkpoint.
- Partition output with a bucket assigner (for example `dt=YYYY-MM-DD/hour=HH`) so Athena and Glue can prune.
- Small-file trap: high parallelism × short checkpoint interval × many partitions = many small files. Lengthen the interval, lower sink parallelism, or compact later.
- In-progress and pending files are not "finished". Readers should only read finished files (hidden by prefix naming).
- Iceberg sink (Iceberg Flink runtime JAR): writes to Iceberg tables in S3 cataloged in the Glue Data Catalog or in S3 Tables.
- Iceberg commits on checkpoint: exactly-once, but one commit per checkpoint → snapshot and small-file growth. Run compaction and snapshot expiry (Glue table optimizers or S3 Tables maintenance).
- Iceberg v2 tables support upserts (equality deletes) from Flink for CDC streams.
- Iceberg sink needs IAM for S3 and Glue (create/alter table, get database). The Glue database must exist.
- Dynamic Iceberg sink (newer Iceberg versions) routes records to many tables and evolves schema at runtime.
- Exam pattern: "streaming ETL into a transactional data lake with exactly-once" → MSF → Iceberg (Glue catalog or S3 Tables).

## L. Other connectors
- Amazon Data Firehose sink: at-least-once; Firehose then buffers and delivers to S3, Redshift, OpenSearch, Splunk, Iceberg, HTTP endpoints.
- Firehose catch: max record size and buffering add latency (seconds to minutes); throughput quotas per Firehose stream.
- DynamoDB sink (async sink): batches `BatchWriteItem`. Overwrites by key → idempotent for upserts. Can dedupe in-batch by key.
- DynamoDB sink catch: throttling on hot partitions or under-provisioned capacity → backpressure. Use on-demand or more WCU.
- DynamoDB Streams source connector exists in newer AWS connector releases **(verify availability on your Flink version)**.
- OpenSearch sink: bulk index requests; set a document ID for idempotent upserts. No Flink 2.x release yet at time of writing.
- JDBC sink: batched inserts; upsert mode when a primary key is defined (PostgreSQL, MySQL). Exactly-once XA mode exists for databases that support XA **(verify)**.
- JDBC as lookup source: lookup join with cache.
- Amazon SQS sink, Amazon Managed Service for Prometheus sink: niche AWS connectors.
- Custom sinks: build with the Async Sink base (batching, retries, backpressure built in).
- MSF supports over 40 prebuilt connectors in total.
- Connector versions are tied to the Flink version (for example `5.0.0-1.20`). Using the wrong one breaks start or snapshots.
- From Flink 1.15, MSF blocks start/update if the JAR bundles an unsupported (old) Kinesis connector version.

## M. Glue Data Catalog and Glue Schema Registry
- Glue Data Catalog as Flink catalog: shared table definitions; required for Studio; used by Iceberg sinks; Athena can query the same tables.
- Glue Schema Registry (GSR): central Avro, JSON Schema or Protobuf schemas with versions and compatibility rules.
- Flink apps use the GSR serializer/deserializer libraries with Kinesis or Kafka connectors.
- Producers register or look up schemas; records carry a schema version ID; the Flink consumer fetches the right schema.
- Compatibility modes (BACKWARD default, FORWARD, FULL, NONE, and _ALL variants) stop breaking changes at write time.
- GSR handles format changes in records. Flink state schema evolution is a separate concern (state serializers).
- IAM: the app role needs `glue:GetSchemaVersion` (and register permissions for producers) **(verify action list)**.

## Scenarios: "If X → Y, because Z"
- **If** a job must survive task failures without losing counts, **then** keep **checkpointing** on (the default: every **60 seconds**). A checkpoint is an automatic, periodic copy of all operator state plus source positions, stored in service-managed Amazon S3. **This works because** on failure, Managed Service for Apache Flink (MSF) restarts the job from the latest checkpoint, restoring state and replaying records since then. With checkpointing off, restarts lose both state and position.
- **If** you changed the checkpoint interval in code but nothing changed, **then** set `ConfigurationType=CUSTOM` in the checkpoint configuration. **This works because** with `ConfigurationType=DEFAULT`, the service defaults (on, 60,000 ms interval, 5,000 ms minimum pause) win even if your code or CLI sets other values.
- **If** an app must be updated without losing state, **then** keep `SnapshotsEnabled=true`. A **snapshot** is the Managed Service for Apache Flink (MSF) name for a Flink savepoint, a full copy of state. **This works because** with snapshots on, MSF takes an automatic snapshot on every update, scale and stop, and restores from it. AWS docs say directly that `SnapshotsEnabled=false` causes state loss on updates.
- **If** a bug corrupted results after **10:00**, **then** restart with `RESTORE_FROM_CUSTOM_SNAPSHOT` and the name of a snapshot taken before 10:00. **This works because** snapshots are named restore points you can rewind to (checkpoints are service-owned and cannot be picked by name). Source positions are restored too, so records after the snapshot are reprocessed; sinks must be idempotent or transactional. AWS advises taking snapshots several times a day, for example with Amazon EventBridge Scheduler.
- **If** you deleted a stateful operator and the app will not start, **then** set `AllowNonRestoredState=true` in `FlinkRunConfiguration`. **This works because** the snapshot still holds state for an operator that no longer exists (orphan state), and restore faults unless told to ignore it.
- **If** new code is not state-compatible and the old state is not needed, **then** start with `SKIP_RESTORE_FROM_SNAPSHOT`, which starts with empty state. **This works because** restoring incompatible state would make the app fault (it can even get stuck in `STOPPING` or `UPDATING`). Sources then start from their configured initial position.
- **If** manual snapshots fail with `LimitExceededException`, **then** delete old snapshots. **This works because** the limit is **1,000 snapshots per application** (automatic ones count too) and Managed Service for Apache Flink (MSF) **never** deletes snapshots itself. Automatic snapshots on update, scale and stop still succeed at the limit, and old snapshots also cost storage.
- **If** downstream readers see **duplicates** from a **Kinesis Data Streams (KDS)** sink, **then** add a unique event ID to each record and **dedupe downstream** (for example a DynamoDB conditional write, Iceberg MERGE or Redshift MERGE). **This works because** the KDS sink is **at-least-once**: after a restart, records since the last checkpoint are written again. It also does not guarantee order.
- **If** end-to-end **exactly-once** delivery to **Kafka** is required, **then** use `KafkaSink` with `DeliveryGuarantee.EXACTLY_ONCE` (and a `transactionalIdPrefix`), and make downstream consumers use `isolation.level=read_committed`. **This works because** the sink writes into Kafka **transactions** that commit only when a checkpoint completes; consumers without `read_committed` would see uncommitted or aborted data. The catch: data becomes visible only after each checkpoint, so latency equals the checkpoint interval.
- **If** **Kafka** exactly-once jobs fail with **transaction timeouts** after restarts, **then** set the producer transaction timeout **larger than the checkpoint interval plus the maximum restart time**, but **not above** the broker's `transaction.max.timeout.ms` (**15 minutes** by default). **This works because** an open transaction must stay alive until a checkpoint after recovery commits it; if it times out first, it is aborted.
- **If** Parquet files written to **Amazon S3** are tiny, **then** lengthen the **checkpoint interval** or reduce the sink's parallelism. **This works because** FileSink rolls **bulk formats** (Parquet, ORC, Avro) on **every checkpoint**, so high parallelism × short interval × many partitions = many small files. The catch: a longer interval makes data less fresh.
- **If** **Apache Iceberg** tables collect thousands of snapshots a day, **then** turn on **compaction** and **snapshot expiry** (AWS Glue table optimizers or Amazon S3 Tables maintenance). **This works because** the Iceberg sink makes one commit per checkpoint, which gives exactly-once writes but adds a table snapshot and small files each time.
- **If** CPU sits at **90% for 20 minutes**, **then** expect **autoscaling** to **double** the parallelism (and the Kinesis Processing Units (KPUs)). **This works because** the built-in rule scales up when `containerCPUUtilization` is **≥ 75%** for **15** consecutive 1-minute datapoints. During scaling the app is in `AUTOSCALING` status and restarts from a snapshot, so there is a short downtime.
- **If** load dropped but Kinesis Processing Units (KPUs) stay high for hours, **then** this is **expected**. **This works because** scale-down needs CPU **under 10%** for **6 hours** (360 one-minute datapoints) before it halves parallelism, so you pay for the bigger size until then.
- **If** lag grows but CPU is only **30%**, **then** build **custom autoscaling** on a lag metric such as `millisBehindLatest` (an Amazon CloudWatch alarm plus Step Functions or Lambda calling `UpdateApplication`), or raise **ParallelismPerKPU**. **This works because** built-in autoscaling watches **only CPU**; an I/O-bound job waiting on a slow sink never reaches 75% CPU, so it never scales, even with huge lag.
- **If** a predictable **9:00** traffic peak hurts latency, **then** use **scheduled scaling** (an AWS sample using **Amazon EventBridge Scheduler**) to raise parallelism **before 9:00**. **This works because** reactive autoscaling waits for **15 minutes** of high CPU and then restarts the job, so it reacts too late for a known peak. Scheduled scaling must still stay within maxParallelism.
- **If** autoscaling stops at **parallelism 128**, **then** raise **maxParallelism**, which needs a fresh start without the old state. **This works because** scaling can never pass the lowest maxParallelism of any operator (128 by default when started at ≤ 128), and changing maxParallelism breaks restore of keyed state.
- **If** any scaling pause is unacceptable, **then** **disable autoscaling** (`AutoScalingEnabled=false`) and set Parallelism and ParallelismPerKPU yourself. **This works because** every scale, automatic or manual, restarts the job from a snapshot. Manual sizing avoids surprise downtime and cost changes; plan changes outside peak hours.
- **If** two apps read the same **Kinesis Data Streams (KDS)** stream and throttle each other, **then** switch one or both to **Enhanced Fan-Out (EFO)**. **This works because** polling consumers share each shard's **2 MB/s** and **5 reads/s**, while EFO gives each app its own **2 MB/s** per shard with about **70 ms** push latency. The catch: EFO costs extra per consumer-shard-hour and per GB, and each EFO consumer name must be unique per stream.
- **If** a new app must process the **3 days** of data already in the stream, **then** start it **without a snapshot** and with the start position **`TRIM_HORIZON`** (or `AT_TIMESTAMP`). **This works because** the Kinesis source defaults to **`LATEST`**, which skips everything written before the app started. Replay is limited by the stream's retention (24 hours by default, up to 365 days).
- **If** a constant partition key makes the output **Kinesis** stream throttle, **then** use a real key with many values from the `PartitionKeyGenerator`. **This works because** a constant key sends all records to **one shard** (a hot shard), which hits `WriteProvisionedThroughputExceeded` and pushes backpressure into the Flink job.
- **If** the app must read an **Amazon Managed Streaming for Apache Kafka (MSK)** cluster in private subnets, **then** give the app a **VPC configuration** with subnets that can reach the brokers and a **security group** the brokers allow on their ports. **This works because** MSK has no public path by default, and without a VPC config the app runs in the service network and cannot reach the brokers.
- **If** change data capture (CDC) rows must be kept as the **latest value per key**, **then** use the `upsert-kafka` connector or **Apache Iceberg v2** upserts. **This works because** both treat the stream as a changelog keyed by primary key and keep the latest value per key, while append-only sinks keep every change as a new row.
- **If** producers change the record format often, **then** use **AWS Glue Schema Registry (GSR)** with **compatibility rules** (BACKWARD by default). **This works because** producers register schemas, each record carries a schema version ID, and the Flink consumer fetches the right schema, so every version decodes safely; compatibility rules stop breaking changes at write time. GSR covers record formats only, not Flink state schema evolution.
- **If** an operator throws on one malformed record and the app keeps restarting, **then** catch the exception in the operator and route the bad record to a **side output** (a dead-letter path). **This works because** after each restart the job replays from the last checkpoint, so the same "poison pill" record fails it again in an endless loop.

Verified from AWS docs on 2026-11-02 (MSF fault tolerance page: checkpoint defaults, stop-with-savepoint; snapshots page; scaling and autoscaling pages; maxParallelism; connectors overview and Flink 2.2 connector table; sources/sinks pages; source throttling; restart and network buffer troubleshooting; best practices). KinesisStreamsSink at-least-once, EFO lifecycle, LATEST default and 10 s shard discovery from Apache Flink Kinesis connector docs.
Unconfirmed (verify): default ApplicationRestoreType; unaligned checkpoint support on MSF; cross-Region snapshot copy; KDS sink 1 MiB record guidance; DynamoDB Streams source availability; JDBC XA exactly-once on MSF; GSR IAM action list.

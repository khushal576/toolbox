# Kinesis Data Streams – 3. Consumers, KCL, EFO, Lambda and processing patterns

Short notes. Each point is a fact you can be asked about.

## A. Consumer types
- Shared-throughput (classic) consumer: polls each shard with `GetRecords`. All such consumers share 2 MB/s and 5 calls/s per shard.
- Enhanced fan-out (EFO) consumer: registered on the stream; KDS pushes records over HTTP/2 with `SubscribeToShard`; own 2 MB/s per shard.
- Managed consumers: Lambda event source mapping, Firehose, Managed Service for Apache Flink, Glue streaming, EMR Spark, Redshift streaming ingestion, KDS data delivery, EventBridge Pipes.
- Custom consumers: KCL apps on EC2, ECS, EKS, Fargate.
- Every consumer tracks its own position. KDS does not track who read what (except EFO subscriptions and KCL tables you own).

## B. GetRecords and shard iterators
- Flow: `ListShards` → `GetShardIterator` per shard → loop `GetRecords` with `NextShardIterator`.
- Iterator types:
  - `TRIM_HORIZON`: oldest record still in retention.
  - `LATEST`: only records written after the iterator is created.
  - `AT_SEQUENCE_NUMBER` / `AFTER_SEQUENCE_NUMBER`: resume from a checkpoint.
  - `AT_TIMESTAMP`: first record at or after a time (replay from a point in time).
- A shard iterator expires 5 minutes after it is returned (`ExpiredIteratorException`). Get a new one from your last sequence number.
- `GetShardIterator` is limited to 5 TPS per shard.
- `GetRecords`: 5 TPS per shard, up to 10 MB or 10,000 records per call, 2 MB/s per shard total.
- After a 10 MB response, calls in the next 5 seconds throw `ProvisionedThroughputExceededException`.
- `MillisBehindLatest` in the response shows how far behind the tip the reader is.
- With `LATEST`, a consumer that restarts without a checkpoint skips data written while it was down. Trap.
- Closed shard read to the end: `NextShardIterator` is null; move to child shards.
- Long-term retention reads (data older than 7 days) via `GetRecords` cost extra per GB; via EFO they are free.

## C. Enhanced fan-out (EFO)
- Register with `RegisterStreamConsumer` (consumer name + stream ARN). Status CREATING → ACTIVE.
- Limit: 20 consumers per stream (On-demand Standard, provisioned), 50 with On-demand Advantage in listed Regions.
- Max 5 consumers in CREATING at once. A consumer belongs to one stream.
- `SubscribeToShard`: KDS pushes `SubscribeToShardEvent`s on an HTTP/2 connection.
- A subscription lasts at most 5 minutes; then the client re-subscribes (KCL does it).
- Max 1 `SubscribeToShard` call per second per consumer per shard. Re-subscribe within 5 seconds of a successful call → `ResourceInUseException`.
- Latency about 70 ms average whether 1 or 5 consumers; polling is about 200 ms with 1 consumer, about 1,000 ms with 5.
- Cost: provisioned and On-demand Standard pay consumer-shard-hours + per GB retrieved; On-demand Advantage has no EFO premium.
- Use EFO when: more than 2 consumers, low latency needed, one consumer must not slow others.
- Skip EFO when: one or two consumers and latency of ~1 s is fine (save cost).
- KCL 2.x+ uses EFO by default; set polling mode explicitly if you want shared throughput.
- Deregister unused consumers (`DeregisterStreamConsumer`) to stop charges.
- Metrics: `SubscribeToShardEvent.MillisBehindLatest`, `SubscribeToShard.RateExceeded`.

## D. KCL basics
- KCL = Kinesis Client Library. Java library that builds distributed, fault-tolerant consumers.
- Handles: load balancing across workers, failover, checkpointing, resharding (parents before children), de-aggregation, CloudWatch metrics.
- Delivers at-least-once. Duplicates happen after failover or retries; make processing idempotent.
- Non-Java languages (Python, Node.js, .NET, Ruby) use the MultiLangDaemon, a Java process that talks to your code over STDIN/STDOUT.
- Versions: KCL 1.x reached end of support 2026-01-30; KCL 2.x (2018) and 3.x (2024-11) are GA.
- AWS advises KCL 2.6.1 or later at minimum (a bug in ≤2.6.0 could block shard processing after capacity changes).
- KCL 3.x needs JDK 8+ and AWS SDK for Java 2.x. Avoid SDK 2.27.19–2.27.23 with KCL 3.x (use 2.28.0+).
- KCL 2.x and later support large records up to 10 MiB.
- Application name must be unique per account and Region. It names the lease table and the CloudWatch metrics namespace.

## E. KCL building blocks
- Worker: one running instance of your consumer (one process/host). Many workers form the app.
- Scheduler: the class each worker starts; syncs shard info, tracks leases, starts record processors.
- Record processor: your code; one instance per leased shard. Methods: initialize, processRecords, leaseLost, shardEnded, shutdownRequested.
- Lease: binds one shard to one worker at a time. A worker can hold many leases.
- Lease table: DynamoDB table with one row per shard lease.
- Checkpoint: the last processed sequence number, saved in the lease row.
- Max useful workers = number of shards. Extra workers sit idle (one lease per shard).

## F. KCL DynamoDB tables
- KCL 2.x: one lease table per application.
- KCL 3.x: three tables by default: lease table (`<AppName>`), worker metrics table (`<AppName>-WorkerMetricStats`), coordinator state table (`<AppName>-CoordinatorState`).
- KCL 3.5+: single table format puts all metadata in the lease table (`entityType` attribute). Default for new 2.x → 3.5 migrations; existing 3.0–3.4 apps migrate in two phases with `migrateAllEntitiesToLeaseTable`.
- Why single table: fewer tables, avoids DynamoDB account table limits.
- Tables are created in DynamoDB on-demand capacity mode by default. AWS strongly advises keeping on-demand.
- If you switch them to provisioned and they throttle (`ProvisionedThroughputExceededException`), KCL stalls; raise capacity or use auto scaling.
- KCL 3.x adds a GSI on the lease table keyed by `leaseOwner` for faster lease discovery.
- KCL does not delete these tables when you retire the app. Delete them to stop costs.
- Lease table fields: `leaseKey` (shard ID; multi-stream `account:stream:creationTime:shardId`), `checkpoint`, `checkpointSubSequenceNumber`, `leaseCounter`, `leaseOwner`, `ownerSwitchesSinceCheckpoint`, `parentShardId`, `childShardIds`, `startingHashKey`, `endingHashKey`.
- `leaseCounter` goes up as the owner renews the lease (heartbeat). A stalled counter means a dead owner.
- High `ownerSwitchesSinceCheckpoint` = leases bouncing between workers (unstable fleet or slow checkpoints).
- Reset a consumer to reprocess: change checkpoints in the lease table, or use a new application name (new table) with `TRIM_HORIZON`/`AT_TIMESTAMP`.

## G. KCL lease balancing and failover
- KCL 2.x: workers balance by lease count (each worker aims for an equal number of shards).
- KCL 3.x: balances by worker CPU use (stored in the worker metrics table), so busy workers give leases away.
- 3.x falls back to throughput-per-worker balancing if it cannot read CPU metrics.
- CPU metrics need: Linux EC2 with IMDSv2; ECS on EC2 with task metadata endpoint v4 and agent 1.39.0+; Fargate platform 1.4.0+ (ECS) or 1.3.0+ (EKS); EKS on EC2 Linux.
- Benefit of 3.x: fewer workers for the same load (right-size fleet), lower DynamoDB read cost **(verify cost claim)**.
- Failover: if a lease is not renewed within `failoverTimeMillis` (default 10,000 ms), another worker takes it **(verify default)**.
- New owner resumes from the last checkpoint → records after it are processed again (duplicates).
- Graceful lease handoff (3.x): before moving a lease, KCL calls `shutdownRequested` so the old owner checkpoints, reducing reprocessing.
- You must call the checkpointer inside `shutdownRequested`. Finish async work first.
- Handoff lowers but does not remove duplicates. Stay idempotent.

## H. KCL checkpointing and shutdown
- You choose when to checkpoint (after each batch, every N records, or every N seconds).
- Checkpoint often → fewer duplicates after failure, more DynamoDB writes.
- Checkpoint rarely → cheaper, more reprocessing after failure.
- Never checkpoint before the data is safely written downstream, or you lose records on crash.
- `shardEnded`: shard is closed and fully read. You must checkpoint here, or child shards are never processed. Trap.
- `leaseLost`: another worker took the lease. You cannot checkpoint; just clean up.
- `shutdownRequested`: graceful shutdown or handoff; checkpoint here.
- Graceful app shutdown: `Scheduler.startGracefulShutdown()` lets processors checkpoint before exit.

## I. KCL multi-stream and migration
- One KCL app can read many streams (multi-stream mode with a `MultiStreamTracker` / stream tracker).
- Lease keys include account, stream name, and stream creation time, so leases do not collide.
- You set how leases of removed streams are cleaned up (deletion strategy).
- Migrate 2.x → 3.x in place, rolling. No record processor code changes.
- Step 1: deploy 3.x with `CLIENT_VERSION_CONFIG_COMPATIBLE_WITH_2X` (phase 1 setting) to all workers; the app keeps the 2.x algorithm.
- When all workers run 3.x, KCL switches to the 3.x algorithm itself (takes at least 10 minutes). Watch `CurrentState:3xWorker`.
- Add IAM permissions for 3.x: `UpdateTable`, `Query` on the index, and full item access on the extra tables.
- Rollback to 2.x-compatible mode is possible with the KCL Migration Tool.

## J. KCL IAM permissions
- Kinesis: `DescribeStreamSummary`, `ListShards`, `GetShardIterator`, `GetRecords`, plus `RegisterStreamConsumer`, `DescribeStreamConsumer`, `SubscribeToShard` for EFO.
- DynamoDB: `CreateTable`, `DescribeTable`, `UpdateTable`, `Scan`, `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query` on the KCL tables and index.
- CloudWatch: `PutMetricData`.
- KMS: `Decrypt` on the stream key (and on the DynamoDB tables' key if customer managed).
- In a VPC, KCL also needs reachable DynamoDB and CloudWatch endpoints (interface or gateway endpoint for DynamoDB).

## K. Lambda event source mapping (ESM) basics
- Lambda polls the stream for you (or uses an EFO consumer if you map to a consumer ARN) and invokes your function synchronously with batches.
- Standard iterator: polls each shard about once per second; shares read throughput with other polling consumers.
- Each batch comes from one shard. By default one batch per shard at a time, processed in order.
- Lambda processes each record at least once. Duplicates can happen; make the function idempotent.
- Starting position: `TRIM_HORIZON`, `LATEST`, or `AT_TIMESTAMP` (with `StartingPositionTimestamp`).
- Batch size default 100, max 10,000.
- Batching window (`MaximumBatchingWindowInSeconds`) default 0, up to 300 s (5 minutes). Lambda waits until full batch, window ends, or 6 MB payload.
- Invoke payload limit 6 MB (base64 data + metadata). Records over that go to the on-failure destination.
- Concurrency ≈ shards × parallelization factor. Brief spikes above this can show in metrics.
- Cross-account streams need a resource-based policy on the stream (and on the consumer for EFO).
- Key metric: `IteratorAge` (age of the last record in the batch when processed).

## L. Parallelization factor
- `ParallelizationFactor` 1 (default) to 10: concurrent batches per shard.
- Order is still kept per partition key (Lambda splits by key hash within the shard).
- Use it when `IteratorAge` is high and you cannot add shards (or to avoid reshard cost).
- Catch: downstream systems get up to 10× more parallel calls per shard.
- With KPL aggregation and no EFO, user records in one aggregate must share its partition key to keep per-key order.

## M. Lambda error handling
- Default: a failed batch is retried until it succeeds or the records expire from the stream. The shard is blocked meanwhile (poison pill).
- With defaults, one bad record can block a shard for up to the retention period (one week in Lambda docs' example).
- `MaximumRetryAttempts` default -1 (infinite), range up to 10,000.
- `MaximumRecordAgeInSeconds` default -1 (infinite), max 604,800 (7 days).
- `BisectBatchOnFunctionError` default false: splits a failed batch in two and retries halves to isolate the bad record. Splitting does not use retry quota.
- On-failure destination: SQS queue, SNS topic, S3 bucket, or Kafka topic.
- SQS/SNS get only metadata (shard ID, start/end sequence numbers, stream ARN). Read the real records from the stream before they expire.
- S3 destination gets metadata plus the full invocation payload. Key: `aws/lambda/<ESM-UUID>/<shardID>/YYYY/MM/DD/...`.
- S3 destination role needs `s3:PutObject` and `s3:ListBucket`; limit with `s3:ResourceAccount` to avoid writing to a re-created bucket in another account.
- Errors before invoke (throttling) retry until records expire or pass max age; errors during invoke also respect max retries.
- After retries are exhausted, Lambda discards the batch and moves on (after sending to the destination).
- Best practice: set max retries, max record age, bisect, and an on-failure destination on every Kinesis ESM.

## N. Partial batch response
- Turn on `FunctionResponseTypes = ReportBatchItemFailures`. Without it, Lambda ignores the response body.
- Return `{"batchItemFailures": [{"itemIdentifier": "<sequenceNumber>"}]}` with the first failed record.
- Lambda checkpoints before that record and retries from it. With several IDs, it uses the lowest sequence number.
- Success: empty or null `batchItemFailures`, or empty/null response.
- Whole batch failure: empty-string or null `itemIdentifier`, or a bad key name.
- With bisect on as well, the batch is bisected at the returned sequence number.
- It reduces reprocessing of good records but does not remove all retries.

## O. Tumbling windows and filtering
- `TumblingWindowInSeconds` 0–900 (15 minutes). Fixed, non-overlapping windows by record arrival time.
- Lambda passes `state` between invokes in a window; the function must return `state` or the invoke counts as failed.
- State max 1 MB per shard; above that the window ends early (`isWindowTerminatedEarly`).
- Final invoke has `isFinalInvokeForWindow = true`; write the aggregate there.
- Windows do not span resharding: a shard end closes the window; children start fresh.
- Lambda waits up to 2 minutes with no new records before treating a window as over.
- Use tumbling windows for simple per-shard counts and sums; use Flink for complex windows, joins, event time.
- Event filtering: up to 5 filters per ESM (quota up to 10), ORed. Filter on the `data` key (JSON payload) and metadata.
- Records that do not match are skipped and the iterator moves past them; no invoke cost for them.
- Filtering only works on data Lambda can parse as JSON **(verify behavior for non-JSON)**.
- Filter criteria can be encrypted with your KMS key.

## P. Other managed consumers
- Amazon Data Firehose: KDS as source, delivers to S3, Redshift, OpenSearch, Splunk, Iceberg, HTTP, Snowflake; transforms, format conversion, dynamic partitioning. One Firehose stream reads one KDS stream; it de-aggregates KPL records.
- Managed Service for Apache Flink: Kinesis source connector (polling or EFO), stateful processing, event-time windows, exactly-once state with checkpoints. Flink source handles records up to 10 MiB; do not use the sink connector for records over 1 MiB.
- AWS Glue streaming ETL: Spark Structured Streaming on Glue; reads KDS, checkpoints in S3, micro-batches (`windowSize`), writes to S3/Iceberg/Catalog tables.
- Amazon EMR / Spark Structured Streaming: Kinesis connector; EMR supports large records with `readStream`.
- Redshift streaming ingestion: `CREATE EXTERNAL SCHEMA ... FROM KINESIS` + materialized view; `AUTO REFRESH YES`; data in `kinesis_data` VARBYTE; parse with `JSON_PARSE`. Records over Redshift's size limit are skipped and logged.
- Redshift catch: if the view is not refreshed before records leave retention, those records are missed.
- EventBridge Pipes: KDS source with batching, filtering, enrichment, to many targets.

## Q. KDS data delivery (S3 and Iceberg streaming tables)
- Managed delivery inside KDS: no consumer code, no compute. Create with `CreateChannel` on the stream.
- Needs On-demand Standard or On-demand Advantage. Not for provisioned.
- Does not use read throughput or EFO slots; no impact on other consumers.
- Max 2 deliveries per stream: one to streaming tables and one to a general purpose S3 bucket (not adjustable).
- Data freshness (buffer time) 300–900 s, default 300 s. Only freshness and logging can be changed later.
- Delivers only records written after the delivery is ACTIVE. No backfill.
- Exactly-once per shard to the destination. Append only.
- No transformations. No schema evolution (change = delete and re-create).
- Streaming tables: creates a new Iceberg table in an S3 table bucket (cannot use an existing table); Parquet files with inline compaction; hourly partitioning on a `timestamptz` column.
- Streaming tables need a schema in Glue Schema Registry (`JSON` with schema ARN, or `GSR_JSON`); invalid records go to the required S3 dead-letter queue (IDs and errors, not payloads).
- Streaming tables: same account and same Region only.
- S3 delivery: original format (JSON, STRING, BYTE_ARRAY); compression GZIP, ZSTD or NONE (required choice); storage class STANDARD (default), INTELLIGENT_TIERING, GLACIER_IR; output key template.
- S3 delivery: DLQ optional (default writes errors to the destination with an error prefix); cross-account bucket allowed, same Region only.
- Encryption: destination needs a customer managed KMS key for SSE-KMS (not `aws/kinesis`). A source stream encrypted with `aws/kinesis` cannot use delivery.
- Choose Firehose instead when you need Lambda transforms, Parquet conversion to plain S3, dynamic partitioning, or other destinations.

## R. Kinesis Data Streams for DynamoDB vs DynamoDB Streams
| | KDS for DynamoDB | DynamoDB Streams |
|---|---|---|
| Retention | up to 1 year | 24 hours |
| Consumers | 5 polling per shard or 20 with EFO (50 on Advantage) | 2 per shard |
| Throughput | KDS capacity (you pay KDS) | DynamoDB quotas |
| Order | use the record timestamp to rebuild order | exact item-level order |
| Duplicates | can occur | none |
| Processing | Lambda, Flink, Firehose, Glue streaming, KCL 1–3 | Lambda, Streams Kinesis adapter (KCL 1–2) |
- You can turn on both for the same table.
- Pick DynamoDB Streams for exact per-item order, no duplicates, simple Lambda triggers.
- Pick KDS for DynamoDB for long retention, many consumers, Firehose/Flink delivery.

## S. Ordering, duplicates and exactly-once
- Order is guaranteed only per shard (per partition key). Never across shards.
- Duplicates come from producer retries (network timeout after a successful write) and consumer retries (failover, Lambda retries).
- KDS has no built-in deduplication or exactly-once delivery to custom consumers.
- Idempotency patterns: put a unique event ID in the payload; upsert by key; DynamoDB conditional writes; idempotency table with TTL; Powertools idempotency.
- Exactly-once outcome patterns: Flink checkpoints with transactional or idempotent sinks; Iceberg MERGE by event ID; KDS data delivery (exactly-once per shard).
- Retried records can arrive out of order; carry an event time or version in the payload and keep the latest.

## T. Cross-Region patterns
- No native stream replication between Regions.
- Pattern 1: consumer (Lambda, KCL, Flink) in Region A writes to a stream in Region B.
- Pattern 2: producers write to both Regions (active-active), or switch Region on failure (DNS or config).
- Pattern 3: land data in S3 and use S3 Cross-Region Replication for the archive copy.
- Cross-Region reads in on-demand modes pay data transfer; data delivery and streaming tables do not support cross-Region.
- Sequence numbers differ between the copies; dedupe by event ID, not sequence number.

## U. Scenarios
- **If** **four apps** read one stream by polling and all of them lag, **then** give each an **enhanced fan-out (EFO)** consumer, which gets records pushed over its own pipe. **This works because** polling consumers **share** a shard's **2 MB/s** and **5 calls/s**, while each EFO consumer gets its **own 2 MB/s per shard** and about **70 ms** latency. EFO costs extra per consumer-shard-hour and GB in provisioned and On-demand Standard modes.
- **If** a consumer restarted with **`LATEST`** and missed data, **then** restart from its last **checkpoint** (`AFTER_SEQUENCE_NUMBER`) or from **`AT_TIMESTAMP`**. **This works because** `LATEST` only returns records written after the iterator is created, so it skips anything written while the consumer was down.
- **If** you must **reprocess the last 6 hours** after a bug, **then** get a new iterator with **`AT_TIMESTAMP`** (or reset the Kinesis Client Library (KCL) checkpoints in its lease table). **This works because** records stay readable for the whole retention period and reading never deletes them.
- **If** a Kinesis Client Library (KCL) app has **8 shards** and **12 workers**, **then** **4 workers sit idle**. **This works because** each shard has one lease held by one worker at a time, so useful workers can never exceed the shard count.
- **If** Kinesis Client Library (KCL) stalls with **Amazon DynamoDB throttling**, **then** keep the KCL tables in **on-demand** capacity mode (or raise provisioned capacity). **This works because** KCL writes leases and checkpoints to these tables; when the writes are throttled, it cannot make progress.
- **If** child shards are never processed after a reshard, **then** **checkpoint in `shardEnded`**. **This works because** the Kinesis Client Library (KCL) starts children only after the parent is marked finished, and that mark is the checkpoint at shard end.
- **If** Kinesis Client Library (KCL) workers have **uneven CPU** use, **then** upgrade to **KCL 3.x**. **This works because** KCL 3.x balances leases by worker **CPU** use, so busy workers give leases away; KCL 2.x only balances by lease count.
- **If** **KCL 3.x** workers on **Amazon EC2** still balance by throughput, **then** enable **IMDSv2** (Instance Metadata Service v2) on the Linux hosts. **This works because** KCL 3.x needs IMDSv2 to read CPU metrics and falls back to throughput-per-worker balancing without them.
- **If** a retired Kinesis Client Library (KCL) app still costs money, **then** delete its **Amazon DynamoDB tables** and deregister its **enhanced fan-out (EFO) consumer**. **This works because** KCL does not remove its tables when you retire the app, and an EFO consumer is billed while it stays registered.
- **If** AWS Lambda's **`IteratorAge`** (how old the last processed record is) keeps rising, **then** raise the **parallelization factor** (up to **10** batches per shard), add shards, use bigger batches, or speed up the code. **This works because** by default Lambda processes one batch per shard at a time, so each shard has limited concurrency. A higher factor still keeps order per partition key but sends more parallel calls downstream.
- **If** **one bad record** blocks a shard for days, **then** set **`BisectBatchOnFunctionError`**, **`MaximumRetryAttempts`**, **`MaximumRecordAgeInSeconds`** and an **on-failure destination** on the AWS Lambda event source mapping. **This works because** by default retries are **infinite** (-1), so a failed batch is retried until its records expire and blocks the shard meanwhile. Bisect splits the batch to isolate the bad record; after retries run out, Lambda sends the batch details to the destination and moves on.
- **If** failed-batch information in **Amazon SQS** is not enough to debug, **then** use an **Amazon S3** on-failure destination. **This works because** SQS and SNS get only metadata (shard ID and sequence numbers), while S3 gets the metadata **plus the full invocation payload**.
- **If** only **one record** in a **500-record batch** fails, **then** use **partial batch response** (`ReportBatchItemFailures`) and return that record's sequence number. **This works because** AWS Lambda checkpoints **before** that record and retries **from it onward**, so the records before it are not processed again. It reduces reprocessing but does not remove all retries.
- **If** AWS Lambda must compute **per-minute totals per shard**, **then** use a **tumbling window** of **60 seconds** (`TumblingWindowInSeconds`, up to 900). **This works because** Lambda passes **state** between invokes inside a window, and the final invoke (`isFinalInvokeForWindow`) is where you write the total.
- **If** only `type = "order"` events should invoke AWS Lambda, **then** add an **event filter** on `data.type` to the event source mapping. **This works because** records that do not match are skipped with **no invoke cost**. Filtering works only on data Lambda can parse as JSON **(verify behavior for non-JSON)**.
- **If** a **7 MiB** record arrives at AWS Lambda, **then** it goes to the **on-failure destination** instead of your function. **This works because** the Lambda invoke payload limit is **6 MB** (base64 data plus metadata).
- **If** analysts want stream data as **Apache Iceberg tables** with no code, **then** use **KDS streaming tables delivery**, managed delivery built into Kinesis Data Streams (KDS), on an **on-demand** stream. **This works because** it creates a new Iceberg table in an S3 table bucket and handles Parquet conversion and compaction. It needs a schema in AWS Glue Schema Registry and delivers only records written after it is active.
- **If** records must land in **Amazon S3** as **Parquet** with **dynamic partitions**, **then** use **Amazon Data Firehose**. **This works because** KDS S3 delivery keeps the **original format** and has no transformations, while Firehose offers format conversion and dynamic partitioning.
- **If** an Amazon DynamoDB change feed needs **10 consumers** and **7-day replay**, **then** use **Kinesis Data Streams for DynamoDB**. **This works because** it keeps changes up to **1 year** and allows many consumers (20 with enhanced fan-out), while **DynamoDB Streams** keeps only **24 hours** and allows **2** readers per shard.
- **If** **exact per-item order** and **no duplicates** matter most, **then** use **DynamoDB Streams**. **This works because** DynamoDB Streams gives exact item-level order and no duplicates, while Kinesis Data Streams for DynamoDB can duplicate and needs the record timestamp to rebuild order.
- **If** a payment must **not be charged twice**, **then** make the consumer **idempotent**, keyed by the **payment ID** (for example a DynamoDB conditional write). **This works because** Kinesis Data Streams (KDS) delivery is **at-least-once**: producer and consumer retries can create duplicates, and KDS has no built-in deduplication.
- **If** a disaster-recovery (DR) copy of a stream is needed in **another Region**, **then** run a consumer (AWS Lambda, KCL or Flink) that writes to a stream in the second Region. **This works because** Kinesis Data Streams (KDS) has **no built-in cross-Region replication**. Sequence numbers differ between copies, so dedupe by event ID.
- **If** **Amazon Redshift** dashboards need sub-minute data from Kinesis Data Streams (KDS), **then** use **Redshift streaming ingestion** with **`AUTO REFRESH YES`**. **This works because** Redshift reads the stream directly into a materialized view, with no staging in S3. The catch: records not refreshed before they leave retention are missed.
- **If** **stateful joins** and **event-time windows** are needed, **then** use **Amazon Managed Service for Apache Flink**. **This works because** Flink supports stateful processing, event-time windows and exactly-once state with checkpoints, while AWS Lambda tumbling windows are simple and **per shard** only.

Verified from AWS docs on 2026-11-01 (KDS quotas, enhanced fan-out, KCL concepts, KCL DynamoDB tables, KCL 2→3 migration, KCL single table format, KCL lifecycle, Lambda Kinesis ESM pages incl. parameters, on-failure destinations, partial batch response, tumbling windows, event filtering, KDS data delivery pages, DynamoDB CDC comparison, large records).
Unconfirmed (verify): KCL `failoverTimeMillis` default; KCL 3.x DynamoDB cost claim; Lambda filtering on non-JSON Kinesis data.

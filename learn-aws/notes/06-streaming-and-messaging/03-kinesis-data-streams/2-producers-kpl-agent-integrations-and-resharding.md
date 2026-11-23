# Kinesis Data Streams – 2. Producers, KPL, Kinesis Agent, integrations and resharding

Short notes. Each point is a fact you can be asked about.

## A. Ways to write to a stream
- AWS SDK `PutRecord` / `PutRecords`: full control, lowest latency, you write batching and retries yourself.
- Kinesis Producer Library (KPL): high throughput library with batching, aggregation, retries, metrics. Adds buffering delay.
- Kinesis Agent: Java service that tails log files on Linux and sends lines.
- AWS services that write for you: CloudWatch Logs subscription filters, AWS IoT Core rules, DynamoDB (Kinesis Data Streams for DynamoDB), AWS DMS target, EventBridge Pipes and rules, API Gateway proxy, Kafka Connect / MSK Connect, Amazon Connect, Fluent Bit/Fluentd plugins.
- Every write needs a stream name or ARN, a partition key, and data.

## B. PutRecord
- Writes one record. Returns `ShardId` and `SequenceNumber`.
- Limit: 1,000 records/s and 1 MB/s per shard (writes from all producers combined).
- Optional `ExplicitHashKey` (choose the shard) and `SequenceNumberForOrdering` (strict order per key).
- One HTTP request per record → many small records cost many requests and hit limits sooner.
- Use for low volume or when each event needs an immediate confirmation.

## C. PutRecords (batch)
- Up to 500 records per request.
- Each record up to the stream max record size (up to 10 MiB); the whole request up to 10 MiB including partition keys.
- Records in one request can go to different shards.
- The call can partly succeed. HTTP 200 does not mean all records were written.
- Check `FailedRecordCount` in the response. Each entry in `Records` lines up with the request by position.
- Failed entries carry `ErrorCode`: `ProvisionedThroughputExceededException` or `InternalFailure`, plus `ErrorMessage`.
- Retry only the failed entries, with exponential backoff and jitter.
- Catch: retrying the whole batch creates duplicates of the records that already succeeded.
- Catch: retries break order. A retried record lands after newer records with the same key.
- `PutRecords.FailedRecords` metric = internal failures; `PutRecords.ThrottledRecords` = throttled records.
- `PutRecords.Success` counts calls where at least one record succeeded, so it can look healthy while records fail.

## D. Producer errors to know
- `ProvisionedThroughputExceededException`: shard over 1 MB/s or 1,000 records/s (or on-demand ramp limits). Retry with backoff; fix keys or capacity.
- `KMSThrottlingException`: KMS request limit hit on an encrypted stream. Retry; raise KMS quota.
- `KMSAccessDeniedException`, `KMSDisabledException`, `KMSNotFoundException`, `KMSInvalidStateException`: key problem; writes fail until fixed.
- `ResourceNotFoundException`: wrong name, wrong Region, or stream not ACTIVE yet.
- `InvalidArgumentException`: for example record over max size or key over 256 characters.
- `AccessDeniedException`: missing `kinesis:PutRecord(s)` or KMS `GenerateDataKey`.
- `LimitExceededException` is a control-plane error (too many API calls or streams), not a data-write error.

## E. KPL basics
- KPL = Amazon Kinesis Producer Library. Core in C++, used through a Java wrapper (a native child process).
- KPL 1.x is current (released 2024-12, uses AWS SDK for Java 2.x). KPL 0.x reached end of support on 2026-01-30.
- KPL 1.0.5+ supports large records up to 10 MiB.
- Runs on Linux, macOS and Windows (supported platforms list) **(verify Windows support level)**.
- `addUserRecord` returns at once with a `ListenableFuture`. The record is sent later in the background (asynchronous).
- You check the future for success/failure. If you ignore futures, you never see failed records.
- Writes to one or many streams with automatic, configurable retries.
- Emits CloudWatch metrics (namespace `KinesisProducerLibrary`) at stream, shard, or global level.
- Configuration is fixed at start. Changing `KinesisProducerConfiguration` later has no effect.
- KPL integrates with the AWS Glue Schema Registry (serialize with a schema).

## F. KPL user records vs KDS records
- User record = your event (for example one JSON click).
- KDS record = what the service stores (partition key, sequence number, blob).
- With aggregation, one KDS record holds many user records.
- Batching has two independent kinds: aggregation and collection. Both are on by default.

## G. KPL aggregation (the key exam idea)
- Aggregation packs many small user records into one KDS record.
- Why: the 1,000 records/s per shard limit binds when records are small (under ~1 KB).
- Example from docs: 1,000 records/s of 512 bytes on one shard → about 10 KDS records/s of 50 KB each.
- Also cuts cost in provisioned mode: fewer, fuller 25 KB PUT payload units.
- Format: KPL aggregated record = magic number (4 bytes `0xF3 0x89 0x9A 0xC2`) + Protocol Buffers message + MD5 checksum (16 bytes) **(verify byte details)**.
- The protobuf holds a partition key table, an optional explicit hash key table, and the list of user records.
- One aggregated record goes to one shard. KPL groups user records by the shard their keys map to.
- `AggregationMaxSize` default 51,200 bytes (50 KB); range 64 bytes to 10 MiB.
- `AggregationMaxCount` default 4,294,967,295 (effectively no count limit).
- `AggregationEnabled` default true.
- Consumers must de-aggregate. KCL does it automatically (checkpoint uses sequence + subsequence number).
- Non-KCL consumers use the de-aggregation libraries (kinesis-aggregation on GitHub; KPL Java `UserRecord.deaggregate`).
- Lambda: use the deaggregation module in code. Lambda docs say with EFO the ESM decodes aggregated records itself, and user records whose key does not match the aggregate's key are dropped **(verify)**.
- Lambda without EFO: user records inside one aggregate must share the aggregate's partition key, or per-key order is not guaranteed with parallelization factor > 1.
- Firehose with a KDS source de-aggregates KPL records before delivery.
- Trap: a consumer that does not de-aggregate sees "garbage" binary data (magic bytes + protobuf).
- Trap: aggregation adds latency (records wait to fill the aggregate).

## H. KPL collection
- Collection = sending many KDS records in one `PutRecords` HTTP request.
- `CollectionMaxCount` default 500 (max 500, the API limit).
- `CollectionMaxSize` default 5,242,880 bytes (5 MiB).
- Collection reduces HTTP overhead; aggregation reduces record count. Use both for best throughput.

## I. KPL timing, TTL and rate limiting
- `RecordMaxBufferedTime` default 100 ms: max time a record waits in the buffer before sending.
- Higher buffered time = better packing and fewer requests, but more latency.
- If your app cannot accept extra delay, use the SDK directly instead of KPL.
- `RecordTtl` default 30,000 ms (30 s), min 100 ms: a record not written within this time is failed back to you.
- Expired records show up as failed futures with "Expired" attempts. You decide to retry, drop, or save them.
- Raise `RecordTtl` if throttling bursts are expected and you prefer delay over loss.
- `RateLimit` default 150 = percent of the shard backend limit that KPL lets one producer send per shard.
- Rate limiting stops one KPL instance from hammering a shard with retries. Lower it (for example 100) when many producers write to the same shards.
- `MaxConnections` default 24 (1–256); `RequestTimeout` default 6,000 ms; `ConnectTimeout` 6,000 ms.
- `FailIfThrottled` default false: when true, throttled records fail at once instead of retrying.
- `ThreadingModel` PER_REQUEST (default) or POOLED; POOLED with `ThreadPoolSize` limits threads.
- `MetricsLevel` default detailed; `MetricsGranularity` default shard. Detailed shard metrics cost CloudWatch money.

## J. KPL backpressure
- KPL buffers in memory. If you add records faster than it can send, the buffer grows without bound.
- Watch `getOutstandingRecordsCount()` and pause or slow `addUserRecord` when it passes a threshold.
- Without backpressure: memory grows, records exceed `RecordTtl` and expire, the process can crash and lose all buffered records.
- Buffered records are lost if the process dies. Call `flushSync()` before shutdown.
- KPL throughput depends on CPU and network of the host; it is not free capacity.

## K. KPL vs SDK – choose
| Need | Choose |
|---|---|
| Very high volume of small records | KPL (aggregation) |
| Lowest possible latency per record | SDK `PutRecord(s)` |
| Simple app, few records | SDK |
| Language without KPL (Python, Node.js) | SDK, or aggregation library for that language |
| Consumers that cannot de-aggregate | SDK or KPL with aggregation off |
| Built-in metrics and retries | KPL |
| Synchronous confirmation before reply to user | SDK |
- KPL with aggregation off still gives collection, retries and metrics.

## L. Kinesis Agent
- Stand-alone Java app. Watches files, sends new lines to KDS (or to Firehose).
- Handles file rotation, checkpointing (resume after restart) and retries.
- Supported OS: Amazon Linux (2015.09+) and Red Hat Enterprise Linux 7+. Can run in a container.
- Windows needs a different product: Kinesis Agent for Windows.
- Config file: `/etc/aws-kinesis/agent.json`. Restart the agent after changes. Log: `/var/log/aws-kinesis-agent/aws-kinesis-agent.log`.
- Required settings per flow: `filePattern` and `kinesisStream` (or `deliveryStream` for Firehose).
- Credentials: EC2 instance role (best), access keys, or `assumeRoleARN` for cross-account.
- Needs `kinesis:PutRecords` (and `cloudwatch:PutMetricData` if metrics on).
- Defaults: `initialPosition` END_OF_FILE; `maxBufferAgeMillis` 60,000 (1–900 s); `maxBufferSizeBytes` 4 MB; `maxBufferSizeRecords` 500.
- `partitionKeyOption`: RANDOM (default) or DETERMINISTIC (hash of the data).
- Default record = one line. `multiLineStartPattern` (regex) joins multi-line records like stack traces.
- Pre-processing (`dataProcessingOptions`): SINGLELINE, CSVTOJSON, LOGTOJSON (Apache common/combined/error, syslog RFC3164), ADDMETADATA.
- Rotate or create files no faster than once per second, or the agent cannot tell files apart.
- Duplicate records usually mean a `filePattern` matching several files, or `copytruncate` logrotate mode.
- Slow agent + `RecordSendErrors` → usually stream throttling (`WriteProvisionedThroughputExceeded`).

## M. CloudWatch Logs subscription filters
- A subscription filter sends log events from a log group to KDS in near real time.
- Data arrives gzip-compressed and base64-encoded (JSON with `logEvents` array). Consumers must decompress.
- Control messages (`messageType: CONTROL_MESSAGE`) are sent to test reachability; skip them.
- Up to 2 subscription filters per log group.
- Needs an IAM role that CloudWatch Logs (`logs.amazonaws.com`) assumes, with `kinesis:PutRecord` on the stream.
- Cross-account: create a CloudWatch Logs destination in the receiving account that points to the stream, with a destination policy.
- Account-level subscription filters can send all log groups in an account **(verify)**.
- Throttled stream → CloudWatch Logs retries for up to 24 hours, then drops **(verify)**.

## N. AWS IoT Core rules
- An IoT rule (SQL on MQTT topics) can use the Kinesis action to put messages into a stream.
- You set the stream name and the partition key (can use substitution templates like `${topic()}` or `${newuuid()}`).
- The rule needs an IAM role with `kinesis:PutRecord`.
- Use an error action (for example to S3 or SQS) to catch failed puts.

## O. AWS DMS as a producer (CDC)
- DMS can use KDS as a target for full load and ongoing CDC from databases.
- DMS writes JSON records with data plus metadata (operation, table, timestamps).
- Default partition key is the table primary key, keeping per-row order. Option to partition by schema and table.
- Task settings include `IncludeTransactionDetails`, `IncludeControlDetails`, `PartitionIncludeSchemaTable` **(verify names)**.
- DMS needs a service access role with put permissions on the stream.
- Use with KDS when many consumers need the same CDC feed; else DMS to S3 directly may be simpler.

## P. EventBridge, Pipes and API Gateway
- EventBridge rules can target a KDS stream; set a partition key path from the event (default is the event ID, random).
- EventBridge Pipes can use KDS as a source (batch, starting position, filtering, enrichment) or as a target.
- Pipes as a target needs a partition key (static or from the event).
- Pipes is a point-to-point integration; it replaces simple glue Lambda functions.
- API Gateway REST API AWS service integration can call `PutRecord` directly (no Lambda), for HTTP producers like mobile apps.

## Q. Other producers
- Kinesis Data Streams for DynamoDB: DynamoDB pushes item-level changes to your stream (see file 3 for the comparison with DynamoDB Streams).
- Kafka Connect: the open-source Kinesis sink connector (or MSK Connect) moves Kafka topics into KDS.
- Fluent Bit / Fluentd: `kinesis_streams` output plugin, common for containers (ECS, EKS).
- Firehose cannot write into KDS. Firehose reads from KDS, not the other way.

## R. Glue Schema Registry with KDS
- AWS Glue Schema Registry (GSR) stores schemas for streaming data. No extra cost.
- Formats: Apache Avro, JSON Schema, Protocol Buffers.
- Producer uses the GSR serializer (KPL or SDK with the GSR library). It embeds a schema version ID in each record.
- Consumer uses the GSR deserializer (KCL, Lambda, Flink, Glue streaming) to read the right schema version.
- Compatibility modes: NONE, DISABLED, BACKWARD (default), BACKWARD_ALL, FORWARD, FORWARD_ALL, FULL, FULL_ALL.
- BACKWARD = new readers can read old data (safe to add optional fields, delete fields).
- A breaking change under BACKWARD is rejected when registering, which protects consumers.
- Benefits: smaller payloads (schema not in each record), data quality, safe schema evolution.
- KDS streaming tables delivery needs a schema in GSR (`JSON` with `GSRSchemaARN`, or `GSR_JSON` with embedded ID).
- Glue streaming ETL and Managed Flink read GSR schemas for KDS sources.

## S. Resharding basics (provisioned mode)
- Resharding = change the shard count of a provisioned stream. On-demand does it for you.
- Two operations: split (one shard → two) and merge (two shards → one).
- Always pairwise: no split into three, no merge of three in one call.
- The shard(s) acted on are parents; the result shards are children.
- Split increases capacity and cost. Merge decreases both.
- Resharding is usually done by an admin process, not by producers or consumers (least privilege).
- Stream status is UPDATING during a reshard. Wait for ACTIVE before the next operation on that stream.
- `SplitShard` and `MergeShards` are limited to 5 TPS per stream and are only for provisioned streams.

## T. Split and merge mechanics
- `SplitShard` needs the shard ID and `NewStartingHashKey`. The parent's range is cut at that value.
- Use the midpoint for an even split, or a chosen value to isolate a hot range.
- After split: one parent, two children. Each child records the parent ID.
- `MergeShards` needs `ShardToMerge` and `AdjacentShardToMerge`.
- Shards are adjacent when their hash ranges touch (one ends at N, the other starts at N+1).
- You cannot merge non-adjacent shards. Trap answer in exams.
- After merge: one child with two parents (`ParentShardId` and `AdjacentParentShardId`).
- Merge cold shards (low traffic) to save cost. Split hot shards to add capacity.

## U. Shard states after resharding
- OPEN: accepts writes and reads.
- CLOSED: parent after reshard; no new writes; still readable until retention ends.
- EXPIRED: all records past retention; shard no longer listed.
- New writes for a key route to the child that owns its hash.
- Records already in the parent stay there. No data moves or is lost.
- Closed parent shows an `EndingSequenceNumber` in its sequence range.
- Reading a closed shard to the end: `GetRecords` returns `NextShardIterator` = null, plus `ChildShards` in the response.
- To keep order per key, read the parent to the end before reading its children. KCL, Lambda and Flink do this for you.
- Reading children first can give out-of-order records for a key.
- Billing is for open shards; closed shards are not billed as shard-hours **(verify)**.

## V. UpdateShardCount rules
- `UpdateShardCount` = uniform scaling (`UNIFORM_SCALING`) to a target count. Only for provisioned streams.
- KDS runs the splits and merges for you. It can create short-lived shards that count toward your shard quota.
- Default limits per stream:
  - Max 10 scaling operations per rolling 24 hours.
  - Cannot scale up to more than double the current count in one call.
  - Cannot scale down below half the current count in one call.
  - Cannot exceed 10,000 shards per stream (default) or the account shard quota.
  - A stream above 10,000 shards can only scale down to below 10,000.
  - Max 10 TPS on the API (over that → `LimitExceededException`).
- AWS advises targets that are multiples of 25% of current (25%, 50%, 75%, 100%) for faster completion.
- It can take minutes on large streams. Reads and writes keep working.
- To go from 4 to 20 shards: 4 → 8 → 16 → 20 (three calls), because each call can at most double.
- `UpdateShardCount` resets hot-key fixes: uniform splitting ignores your custom hash ranges.

## W. Reshard strategy
- Use enhanced shard-level metrics (`IncomingBytes`, `IncomingRecords`, `WriteProvisionedThroughputExceeded` per shard) to find hot shards.
- Hot hash range → `SplitShard` at a chosen hash key.
- Whole stream busy → `UpdateShardCount`.
- Many cold shards → merge adjacent cold pairs or scale down by up to half per call.
- Consumers: more shards = more parallel consumers (KCL workers, Lambda concurrency).
- Lambda and KCL resume on child shards automatically after the parent is finished.

## X. Scenarios
- If a producer gets HTTP 200 from `PutRecords` but data is missing → check `FailedRecordCount` and retry failed entries, because the call can partly fail.
- If retrying `PutRecords` creates duplicates → retry only failed records and make consumers idempotent, because successful records were already stored.
- If 20,000 small events/s throttle a 10-shard stream at 2 MB/s → KPL aggregation, because records/s is the limit, not bytes.
- If a Python producer needs aggregation → use the kinesis-aggregation library for Python with the SDK, because KPL is Java/C++.
- If an API must confirm each write in under 50 ms → SDK `PutRecord`, because KPL buffers records (default 100 ms).
- If KPL memory keeps growing and records expire → add backpressure on outstanding records, because KPL buffers without limit.
- If many KPL hosts throttle the same shards → lower `RateLimit`, because the default 150% lets retries overload shards.
- If a KCL consumer reads KPL data fine but a custom GetRecords app shows binary junk → de-aggregate in the custom app, because KPL packs user records.
- If web servers on Amazon Linux must ship log files → Kinesis Agent, because it tails, rotates, checkpoints and retries.
- If Apache logs must arrive as JSON → Kinesis Agent LOGTOJSON, because it converts before sending.
- If CloudWatch Logs must feed a central stream in another account → CloudWatch Logs destination + subscription filter, because the destination allows cross-account delivery.
- If the consumer of a log subscription cannot parse data → gunzip after base64 decode, because subscription data is compressed.
- If database changes must reach five consumers → DMS CDC to KDS, because KDS allows many readers and replay.
- If a mobile app must write to KDS with no servers → API Gateway service integration to `PutRecord`, because no Lambda is needed.
- If producers keep breaking consumers with schema changes → Glue Schema Registry with BACKWARD compatibility, because incompatible versions are rejected.
- If one shard is hot in provisioned mode → `SplitShard` at a hash key inside the hot range, because you can target that range.
- If two cold shards are not adjacent → merge each with its adjacent neighbor instead, because only adjacent shards can merge.
- If you need 4 → 20 shards now → multiple `UpdateShardCount` calls (8, 16, 20), because each call can at most double.
- If you hit the 10-per-day `UpdateShardCount` limit → use `SplitShard`/`MergeShards` or switch to on-demand, because the limit is per stream per 24 hours.
- If after a split some keys come out of order → read the parent to the end first (use KCL/Lambda), because children hold only newer records.
- If a reshard fails with shard quota error → raise the shard quota, because temporary shards count toward it.

Verified from AWS docs on 2026-11-01 (PutRecords, KPL concepts, KPL configuration defaults file, KPL lifecycle policy, Kinesis Agent, resharding pages, UpdateShardCount API, Lambda Kinesis aggregation notes).
Unconfirmed (verify): KPL aggregated record byte layout; KPL Windows support; Lambda EFO de-aggregation behavior; CloudWatch Logs account-level filters and 24-hour retry; DMS setting names; closed-shard billing.

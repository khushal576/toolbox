# Amazon MSK – 2. Topics, partitions, replication, producers, consumers and integrations

Short notes. Each point is a fact you can be asked about.

## A. Durable topic settings
- Replication factor (RF) is set per topic at creation. Production standard on MSK: RF = 3 across 3 AZs.
- `min.insync.replicas` (minISR) = how many in-sync copies must have a write before an `acks=all` producer gets success.
- Standard production triple: RF=3, minISR=2, producer `acks=all`. Survives one broker down with no data loss and no write outage.
- With RF=3, minISR=2: one broker down → writes continue. Two brokers down → `acks=all` writes fail with `NotEnoughReplicas`, reads still work from the leader.
- minISR only matters for `acks=all`. With `acks=1` or `acks=0` the broker ignores it.
- Trap: minISR = RF (for example 3/3) means any rolling restart blocks writes.
- Trap: minISR = 1 with acks=all is no better than acks=1 when the ISR shrinks to the leader alone.
- `acks=0`: producer does not wait. Fastest, can lose data silently.
- `acks=1`: only the leader wrote it. Data lost if the leader dies before followers copy it.
- `acks=all` (`-1`): all current ISR members have it (at least minISR). Strongest durability, a little more latency.
- `unclean.leader.election.enable=false` = never let an out-of-sync replica lead. Prevents silent data loss; partition may stay offline until an ISR member returns.
- MSK default is `true` on non-tiered Standard clusters. Set it to false for durable topics. Express fixes it at false.
- `UnderMinIsrPartitionCount` > 0 means some partitions can't take `acks=all` writes right now.
- You can change RF later only by partition reassignment (`kafka-reassign-partitions.sh`), not with a simple config flag.
- You can add partitions to a topic, but you can never reduce partition count. To reduce, create a new topic and copy.
- Topic names: up to 249 characters, letters, digits, `.`, `_`, `-`. Avoid mixing `.` and `_` (they collide in metric names).
- Brokers need READ and DESCRIBE on topics to replicate. Restrictive ACLs that forget the brokers make `UnderReplicatedPartitions` stay above 0.

## B. Producers: partitioning and batching
- Default partitioner: records with a key go to `hash(key) % partitions`. Same key → same partition → ordered.
- Records with no key: newer clients use a "sticky" partitioner that fills a batch for one partition, then switches. Spreads load in batches.
- Adding partitions changes `hash(key) % partitions`, so existing keys can move to a new partition. Ordering per key breaks across the change.
- Custom partitioners are possible when key hashing gives a bad spread.
- Producers batch records per partition. `batch.size` (bytes) and `linger.ms` (wait time) control batching.
- AWS client guidance: `linger.ms` at least 5 ms (25 ms for most cases), never 0; `batch.size` 64–128 KB; `buffer.memory` 64 MB.
- Bigger batches = higher throughput and less broker CPU; small batches = more requests and more CPU.
- `compression.type`: `gzip`, `snappy`, `lz4`, `zstd`. AWS suggests lz4 or zstd. Compression is per batch, so batching makes it work better.
- Topic `compression.type=producer` (default) keeps whatever the producer used. Setting a different topic value makes brokers recompress (CPU cost).
- `retries`: AWS recommends a very high value (integer max). Without retries a broker failover becomes data loss.
- `delivery.timeout.ms`: total time allowed for send + retries. AWS suggests 60 s or more so retries can outlast a leader change.
- `request.timeout.ms` 10 s or more; `retry.backoff.ms` at least 200 ms to avoid retry storms.
- `NotLeaderForPartitionException` is usually transient during leader moves. Fix with more retries, not code changes.
- Max record size is controlled by broker `message.max.bytes` / topic `max.message.bytes` (Kafka default ≈ 1 MB) and producer `max.request.size`.
- To send larger records, raise topic/broker limits and consumer `max.partition.fetch.bytes` / `fetch.max.bytes` together.
- Large payload pattern: store the object in S3 and send a pointer in Kafka (claim-check pattern).

## C. Idempotent and transactional producers (exactly-once)
- Idempotent producer: `enable.idempotence=true`. Broker drops duplicates created by producer retries.
- How: each producer gets a producer ID (PID) and numbers each batch per partition. The broker rejects repeats.
- Idempotence requires `acks=all`, retries > 0, and `max.in.flight.requests.per.connection` ≤ 5. Order stays correct even with 5 in flight.
- Kafka 3.x clients enable idempotence and `acks=all` by default.
- Idempotence is per producer session and per partition. A restarted producer without a transactional ID gets a new PID.
- On MSK with IAM auth, the client also needs `kafka-cluster:WriteDataIdempotently` on the cluster.
- Transactions: set `transactional.id`. The producer writes to many partitions and commits or aborts them all together.
- Read-process-write exactly-once: consume, process, produce output, and commit the consumer offsets inside the same transaction (`sendOffsetsToTransaction`).
- Consumers must use `isolation.level=read_committed` to skip aborted and open transactions. Default is `read_uncommitted`.
- `read_committed` consumers can't read past the last stable offset, so a long open transaction delays them.
- `transaction.max.timeout.ms` (broker) caps how long a transaction can stay open.
- With IAM auth, transactions need `kafka-cluster:DescribeTransactionalId` and `AlterTransactionalId` on the transactional-id resource.
- Kafka 3.8+ on MSK supports `WriteTxnMarkers` with IAM, so hanging transactions can be ended with IAM. Earlier versions need SCRAM/mTLS + ACLs for that.
- Exactly-once in Kafka means within Kafka (Kafka in → Kafka out). Writing to an outside system (S3, a database) still needs idempotent writes or a transactional sink.
- Kafka Streams turns this on with `processing.guarantee=exactly_once_v2`.
- Managed Service for Apache Flink reaches exactly-once to Kafka with checkpoints plus Kafka transactions.
- Trap: idempotence alone does not stop duplicates from the application calling `send` twice. It only removes retry duplicates.

## D. Delivery and ordering semantics
- At-most-once: commit offsets before processing. A crash loses records.
- At-least-once (most common): process, then commit. A crash causes re-processing, so make processing idempotent.
- Exactly-once: transactions + `read_committed`, or idempotent sinks keyed by a unique ID.
- Ordering is guaranteed only inside one partition. There is no total order across partitions of a topic.
- To keep order for an entity (customer, order, device), use that entity's ID as the key.
- Global order for a whole topic needs one partition, which caps throughput to one partition's limit.
- With idempotence off and `max.in.flight.requests.per.connection` > 1, retries can reorder records. Idempotence fixes this.
- A consumer processes one partition in order, but if it hands records to a thread pool, order is lost unless you shard work by key.
- Lambda keeps order per partition: it processes one batch per partition at a time.

## E. Consumers and consumer groups
- Each partition is assigned to exactly one consumer in a group. One consumer may own many partitions.
- Max useful consumers in a group = number of partitions. Extra consumers sit idle.
- AWS guidance: at least as many consumers as partitions for parallelism (fewer is fine for low-throughput topics).
- Consumers commit offsets to `__consumer_offsets`. On restart they continue from the last committed offset.
- `enable.auto.commit=true` commits every `auto.commit.interval.ms` (AWS: at least 5 s). Simple, but can lose or duplicate on crash.
- Manual commit after processing gives at-least-once control.
- `auto.offset.reset` applies only when the group has no committed offset (or it expired): `earliest`, `latest` (default), or `none`.
- AWS suggests `latest` for new groups to avoid reading the whole topic and loading the cluster; use `earliest` when you need all history.
- Empty groups keep offsets until `offsets.retention.minutes` expires (Kafka default 7 days). After that they restart from `auto.offset.reset`.
- You can reset a group's offsets (to earliest, a timestamp, or an offset) with `kafka-consumer-groups.sh` while the group is inactive. This is how you replay.
- Rebalance = moving partitions between consumers when one joins, leaves, crashes or misses heartbeats.
- Old "eager" rebalancing stops all consumers in the group. Cooperative rebalancing moves only the affected partitions.
- AWS suggests `StickyAssignor` or `CooperativeStickyAssignor` to reduce movement.
- Static membership: set `group.instance.id` per consumer. A quick restart keeps its partitions without a rebalance.
- `session.timeout.ms`: AWS suggests ~60 s. `heartbeat.interval.ms`: ~10 s.
- `max.poll.interval.ms`: if processing between polls takes longer, the consumer is kicked out and a rebalance starts.
- Fix slow processing rebalances by lowering `max.poll.records`, speeding up processing, or raising `max.poll.interval.ms`.
- `group.initial.rebalance.delay.ms` near your deploy time avoids repeated rebalances during rolling deploys.
- Close consumers cleanly on shutdown so they leave the group at once instead of waiting for session timeout.
- New consumer group protocol (KIP-848, GA in Kafka 4.0, used in 4.2 on MSK) moves assignment to the broker for faster, smoother rebalances.
- Rack awareness: set consumer `client.rack` to the AZ ID and broker `replica.selector.class` to `RackAwareReplicaSelector`. Consumers read from a same-AZ follower.
- Rack-aware reads cut cross-AZ data transfer cost and latency. MSK already sets `broker.rack` to the AZ ID.
- `fetch.min.bytes` and `fetch.max.wait.ms` (AWS: ~1,000 ms) trade latency for fewer fetch requests.
- Consumer lag = latest offset minus committed offset, per partition. Growing lag means consumers are too slow.
- Lag metrics on MSK: `MaxOffsetLag`, `SumOffsetLag`, `EstimatedMaxTimeLag` (seconds) at topic level; `OffsetLag`, `EstimatedTimeLag` per partition.
- Lag metrics appear only for STABLE or EMPTY groups with committed offsets and ASCII names without `:`.
- Fix growing lag: add consumers up to partition count, add partitions (if keys allow), speed up processing, or scale the sink.
- Kafka 4.1+ "Queues for Kafka" (share groups, KIP-932) lets many consumers share one partition. Preview, and not on Express yet.

## F. Partition count sizing and hot partitions
- Partitions give parallelism for both producers and consumers. More partitions = more possible throughput.
- Rough sizing: partitions ≥ max(target write MB/s ÷ per-partition write MB/s, target read MB/s ÷ per-consumer read MB/s).
- Plan for growth: you can add partitions later, but that breaks key-to-partition mapping for existing keys.
- Too many partitions cost: more open files and memory per broker, longer leader elections, slower recovery, more metadata.
- Stay under the per-broker partition guidance (Standard 1,000–4,000 recommended; Express up to 20,000 on 16xlarge).
- Count replicas: a topic with 100 partitions and RF 3 adds 300 partition replicas spread across brokers.
- Hot partition = one partition gets far more traffic than others, usually because of a skewed key (one big customer, a null-like default key).
- Symptoms: one broker with high CPU/BytesIn, high lag on one partition, Serverless throttling on one partition (5 MBps in).
- Fixes: better key (add a suffix/salt for heavy keys), a custom partitioner, or more partitions if ordering per key allows.
- Salting a key spreads load but loses strict ordering for that key. Consumers must re-group if they need it.
- Uneven leaders across brokers also cause hot brokers. `auto.leader.rebalance.enable=true` (MSK default) moves leadership back to preferred replicas.
- Uneven partition placement after adding brokers needs reassignment (Cruise Control, `kafka-reassign-partitions.sh`, or Express intelligent rebalancing).

## G. Message size and formats
- Kafka stores bytes. The format (JSON, Avro, Protobuf, CSV) is the producer's and consumer's choice.
- Avro or Protobuf with a schema registry gives smaller messages and safe schema changes (see file 3 for Glue Schema Registry).
- Headers carry metadata (trace IDs, source cluster) without changing the value.
- Timestamps: `CreateTime` (set by producer, default) or `LogAppendTime` (set by broker). Time-based retention and offset lookup use them.
- Bad producer clocks with `CreateTime` can break time-based retention; `log.message.timestamp.before/after.max.ms` can reject such records.

## H. AWS Lambda event source mapping (ESM) for MSK
- Lambda polls MSK through an event source mapping and invokes the function with batches. You do not write a consumer.
- The ESM is a Kafka consumer group. `ConsumerGroupId` defaults to a unique value; set your own only at create time.
- Batch size default 100, max 10,000. Batching window default 500 ms.
- Starting position: `LATEST`, `TRIM_HORIZON` (oldest), or `AT_TIMESTAMP`. Set only at create time.
- Trap: polling starts a few minutes after creation, so `LATEST` can miss records. Use `TRIM_HORIZON` or `AT_TIMESTAMP` if nothing may be missed.
- One batch can contain records from several partitions. Lambda processes partitions in order, one batch per partition at a time.
- So max concurrency for the topic ≈ number of partitions. More partitions = more parallel Lambda invocations.
- Offsets are committed after the batch succeeds. An error retries the whole batch until success or the record expires (default retries and age: infinite).
- A poison record can therefore block a partition forever. Set `MaximumRetryAttempts`, `MaximumRecordAgeInSeconds`, `BisectBatchOnFunctionError`, or partial batch responses.
- On-failure destinations: SQS, SNS, S3 (with full payload), or a Kafka topic.
- Function timeout for MSK ESM is max 14 minutes (not 15).
- Event payload: records grouped by `topic-partition`; key and value are base64-encoded.
- Auth from Lambda: IAM, SASL/SCRAM (secret in Secrets Manager), mTLS (client cert in Secrets Manager), or unauthenticated.
- Networking: Lambda creates a hyperplane ENI in the cluster's subnets using the cluster's security groups.
- On-demand mode (default) with the cluster in private subnets needs a NAT gateway or VPC endpoints for Lambda and STS (and Secrets Manager if used).
- Provisioned mode: you set min (1–200) and max (1–2,000) event pollers. Each poller handles up to 5 MB/s or 5 concurrent invokes.
- Provisioned mode needs no NAT or VPC endpoints, scales faster, and unlocks the advanced retry options and Kafka on-failure destinations.
- Provisioned mode is billed in Event Poller Units (EPU-hours). Several ESMs in one VPC can share EPUs with a poller group.
- Lambda caps max pollers at the number of partitions to keep per-partition order.
- Security group rules: inbound from itself on the auth port (9098 IAM, 9096 SCRAM, 9094 TLS), outbound 443 for AWS APIs.
- Lambda supports event filtering on Kafka records (filter on value fields) so unwanted records never invoke the function.
- Cross-account ESMs are supported using multi-VPC private connectivity and a cluster policy.
- Lambda can decode Avro/Protobuf/JSON with a schema registry (Glue or Confluent) in provisioned mode **(verify)**.

## I. Amazon Data Firehose with an MSK source
- Firehose can read one MSK topic and deliver to destinations such as S3, with buffering, format conversion and compression.
- Works with MSK Provisioned and Serverless. The cluster must have IAM access control on.
- Private connectivity needs multi-VPC private connectivity on for IAM, plus a cluster policy letting Firehose call `CreateVpcConnection`.
- Public connectivity (Provisioned only) needs public access on and IAM auth.
- One topic per Firehose stream, and the topic can't be changed after creation.
- Cross-account MSK sources are supported.
- Firehose decompresses Kafka messages automatically.
- Pick Firehose when you just need "topic → S3/data lake" with no code. Pick MSK Connect S3 sink for more control (partitioning, formats, many topics).

## J. MSK data delivery (Express only, new)
- MSK data delivery uses "Channels" on Express clusters to write a topic straight to S3 Tables (Apache Iceberg) or a general purpose S3 bucket.
- No connectors or compute to run, and no broker egress capacity used.
- Freshness 5–15 minutes. Scales to 10 GB/s per Channel.
- Iceberg target: records in JSON need a schema in Glue Schema Registry; output is Parquet (ZSTD or Snappy); tables register in the Glue Data Catalog.
- Inline compaction keeps file counts low for Athena, Redshift, EMR Spark and Flink queries.
- Failed records go to a required dead-letter S3 bucket.
- No backfill: only data produced after the Channel starts is delivered. Each Iceberg Channel creates a new table.
- Same account and Region only. Schema evolution not supported. Max 50 Channels per cluster, 10 per topic (default).
- Price: about $10 per TB to S3 Tables and $8 per TB to S3 buckets, plus S3 charges.

## K. Other AWS integrations
- Managed Service for Apache Flink (formerly Kinesis Data Analytics) reads and writes MSK with the Flink Kafka connector; good for windows, joins and stateful logic.
- AWS Glue streaming ETL reads Kafka/MSK as a source in micro-batches, with checkpoints in S3, and can use Glue Schema Registry.
- Amazon Redshift streaming ingestion reads MSK (Provisioned or Serverless) straight into a materialized view; no S3 staging.
- Redshift streaming: `CREATE EXTERNAL SCHEMA ... FROM KAFKA ... AUTHENTICATION none | iam | mtls`, then `CREATE MATERIALIZED VIEW ... AUTO REFRESH YES`.
- Redshift streaming does not support SASL/SCRAM. IAM needs Kafka 2.7.1+. It needs enhanced VPC routing and security group access to the brokers.
- One streaming materialized view reads one topic. Columns include `kafka_partition`, `kafka_offset`, `kafka_key`, `kafka_value` (VARBYTE) and `kafka_timestamp`.
- EventBridge Pipes can use an MSK topic as a source, with optional filtering and enrichment, and send to targets like Step Functions, SQS or API destinations.
- AWS DMS can use MSK as a CDC target. It writes JSON (`JSON` or `JSON_UNFORMATTED`), default max message 1,000,000 bytes.
- DMS → MSK traps: no IAM auth (use none, TLS, or SASL-SSL with SCRAM), no MSK Serverless, needs `auto.create.topics.enable=true` unless topics exist.
- DMS partition key options: primary key (full load default), `schema.table` (CDC default without parallel apply), attribute, transaction ID, or constant.
- DMS supports SASL to Kafka only up to version 3.8. With Kafka 4.0+, DMS can only connect without SASL.
- Debezium on MSK Connect is the other common CDC path into MSK (see file 3).
- Amazon OpenSearch Ingestion can also read Kafka/MSK as a pipeline source **(verify)**.

## L. Troubleshooting: symptom → cause → fix
| Symptom | Likely cause | Fix |
|---|---|---|
| `NotEnoughReplicasException` on produce | ISR below minISR (brokers down, or minISR = RF) | Restore brokers; set minISR = RF − 1 |
| Duplicates in the output | At-least-once with retries and no idempotence, or app re-sends | Enable idempotence; make sinks idempotent; use transactions |
| Records out of order for one customer | No key, or key changed, or partitions added | Key by customer ID; avoid adding partitions on ordered topics |
| One consumer pegged, others idle | Hot partition from skewed key | Salt heavy keys, custom partitioner, more partitions |
| Extra consumers do nothing | More consumers than partitions | Add partitions or accept idle standbys |
| Constant rebalances | Slow processing beyond `max.poll.interval.ms`, crashes, rolling deploys | Smaller polls, static membership, cooperative sticky assignor |
| Consumer group restarts from wrong place | Offsets expired (`offsets.retention.minutes`) and `auto.offset.reset` used | Keep groups active; reset offsets deliberately |
| Lag metrics missing in CloudWatch | Group unstable, no committed offsets, non-ASCII or `:` in group name | Fix group naming; ensure commits |
| Lambda stuck on one partition | Poison record retried forever | Max retries/age, bisect, on-failure destination |
| Lambda ESM can't invoke function (on-demand) | Private subnets with no NAT/VPC endpoints | Add NAT or Lambda/STS endpoints, or use provisioned mode |
| `LATEST` ESM missed first records | Polling starts minutes after creation | Use `TRIM_HORIZON` or `AT_TIMESTAMP` |
| Redshift streaming can't connect with username/password | SCRAM not supported | Use IAM or mTLS |
| DMS task can't write to MSK | IAM-only cluster or Serverless target | Enable SCRAM/TLS on Provisioned, or use another path |
| `RecordTooLargeException` | Record over `max.message.bytes`/`max.request.size` | Raise limits end to end, or use S3 pointer |
| `read_committed` consumer stalls | Long-open transaction holds last stable offset | Shorter transactions, lower `transaction.max.timeout.ms` |

## Scenarios: "If X → Y, because Z"
- **If** no acknowledged write may be lost when one broker fails, **then** use replication factor (**RF**) **3**, `min.insync.replicas` (**minISR**) **2**, producer `acks=all`, and `unclean.leader.election.enable=false`. **This works because** a write only succeeds once at least two in-sync copies have it, and an out-of-sync replica can never become leader. With one broker down writes continue; with two down, `acks=all` writes fail with `NotEnoughReplicas` but reads still work.
- **If** producers must not create duplicates during broker failover, **then** set `enable.idempotence=true` (the default in Kafka 3.x clients). **This works because** each producer gets a producer ID and numbers each batch per partition, so the broker drops batches repeated by retries. With IAM auth the client also needs `kafka-cluster:WriteDataIdempotently`. The catch: it does not stop duplicates when the application itself calls `send` twice.
- **If** a job reads a topic, transforms the data and writes another topic **exactly once**, **then** use a **transactional producer** (`transactional.id`) that commits the consumer offsets inside the same transaction (`sendOffsetsToTransaction`), with readers set to `isolation.level=read_committed`. **This works because** the output records and the offsets commit or abort together, and `read_committed` consumers skip aborted and open transactions. Exactly-once covers only Kafka in → Kafka out; outside systems still need idempotent writes.
- **If** events for each order must stay in order, **then** use the **order ID as the record key**. **This works because** the default partitioner sends the same key to the same partition, and ordering is guaranteed inside one partition. Avoid adding partitions later, because that remaps keys.
- **If** a topic needs strict **global order**, **then** give it **one partition** and accept the throughput cap. **This works because** order exists only within a partition; there is no total order across partitions, so one partition caps throughput to one partition's limit.
- **If** a topic has **12 partitions** and the team runs **20 consumers** in one consumer group, **then** **8 consumers sit idle**. **This works because** each partition is read by only one consumer in a group, so the useful maximum is the partition count.
- **If** consumers can't keep up and order per key matters, **then** first **add consumers up to the partition count** (and speed up processing). **This works because** extra consumers share the existing partitions without changing anything, while adding partitions changes `hash(key) % partitions` and moves existing keys, breaking per-key order across the change.
- **If** one partition gets **80%** of the traffic from one large tenant, **then** **salt** that tenant's key (add a suffix) or use a **custom partitioner**. **This works because** the default partitioner hashes the key, so every record of one key goes to one partition (a hot partition). The catch: salting loses strict ordering for that key, so consumers must re-group records if they need it.
- **If** consumers rebalance every time a pod restarts, **then** use **static membership** (`group.instance.id` per consumer) and the `CooperativeStickyAssignor`. **This works because** a quick restart then keeps its partitions without a rebalance, and cooperative rebalancing moves only the affected partitions instead of stopping the whole group.
- **If** processing a batch sometimes takes **10 minutes**, **then** lower `max.poll.records`, speed up processing, or raise `max.poll.interval.ms`. **This works because** if the time between polls is longer than `max.poll.interval.ms`, the consumer is removed from the group and a rebalance starts.
- **If** a new consumer group must process all history, **then** set `auto.offset.reset=earliest` (or reset the group's offsets). **This works because** the default is `latest`, and this setting is used only when the group has no committed offset.
- **If** a bug corrupted output for the last **6 hours**, **then** stop the group, **reset its offsets** with `kafka-consumer-groups.sh` to a timestamp 6 hours back, and reprocess. **This works because** reading does not delete data in Kafka; records stay until retention removes them, so you can replay. Offsets can only be reset while the group is inactive.
- **If** consumers in three **Availability Zones (AZs)** cause high cross-AZ data transfer cost, **then** use **rack-aware reads**: set consumer `client.rack` to the AZ ID and broker `replica.selector.class` to `RackAwareReplicaSelector`. **This works because** consumers then fetch from a follower in their own AZ. MSK already sets `broker.rack` to the AZ ID.
- **If** an **AWS Lambda** function must process MSK records in order per partition and failed records must be kept, **then** use the Lambda **event source mapping (ESM)** with `MaximumRetryAttempts` (or `MaximumRecordAgeInSeconds`) and an **on-failure destination** (Amazon SQS, Amazon SNS, Amazon S3 or a Kafka topic). **This works because** by default a failed batch is retried forever, so one poison record can block a partition. The advanced retry options and Kafka destinations need **provisioned mode**.
- **If** a Lambda ESM must handle sudden spikes with low latency, **then** use **provisioned mode** with a higher minimum number of **event pollers**. **This works because** pollers are pre-provisioned (each handles up to **5 MB/s**), so it scales faster than on-demand mode. It is billed in Event Poller Unit hours, and Lambda caps pollers at the partition count.
- **If** the MSK cluster is in private subnets and the Lambda ESM uses on-demand mode, **then** add a **NAT gateway** or **VPC endpoints** for Lambda and AWS Security Token Service (STS), plus Secrets Manager if used. **This works because** in on-demand mode the invoke path goes through your VPC. Provisioned mode needs no NAT or endpoints.
- **If** raw MSK events must land in Amazon S3 with no code, **then** use **Amazon Data Firehose** with an MSK source, or **MSK data delivery** on Express clusters. **This works because** both are managed delivery with no consumers to run. Firehose needs IAM access control on the cluster and reads **one topic** per stream, which can't be changed later.
- **If** Kafka events must become **Apache Iceberg** tables within minutes with no connectors on an Express cluster, **then** use **MSK data delivery** to **Amazon S3 Tables**. **This works because** its Channels write Parquet with **5–15 minute** freshness, compact files inline and register tables in the AWS Glue Data Catalog, using no broker egress. The catch: no backfill (only data after the Channel starts), same account and Region only, and no schema evolution.
- **If** analysts want MSK data in **Amazon Redshift** within seconds, **then** use **Redshift streaming ingestion** into a materialized view with `AUTO REFRESH YES`. **This works because** Redshift reads the topic directly with no Amazon S3 staging. One streaming materialized view reads one topic, and Redshift needs enhanced VPC routing and security group access to the brokers.
- **If** Redshift must authenticate to MSK with **SASL/SCRAM**, **then** it is **not supported**; use **IAM** or **mutual TLS (mTLS)** instead. **This works because** Redshift streaming ingestion accepts only `none`, `iam` or `mtls` authentication (IAM needs Kafka 2.7.1+).
- **If** database changes must stream into an **MSK Serverless** cluster with **AWS Database Migration Service (DMS)**, **then** it is **not supported**; use MSK Provisioned or **Debezium on MSK Connect**. **This works because** DMS can't target MSK Serverless, and Serverless is IAM-only, which DMS doesn't support.
- **If** DMS must write to an MSK cluster that only allows IAM, **then** also enable **SASL/SCRAM** or **TLS** on the cluster. **This works because** DMS Kafka endpoints don't support IAM auth (they use none, TLS, or SASL-SSL with SCRAM). DMS supports SASL only up to Kafka **3.8**.
- **If** stateful **windowed aggregations** on MSK data are needed, **then** use **Amazon Managed Service for Apache Flink**. **This works because** Flink keeps state for windows and joins and reaches exactly-once to Kafka with checkpoints plus Kafka transactions.
- **If** MSK events must trigger an **AWS Step Functions** workflow after filtering, **then** use **Amazon EventBridge Pipes** with the MSK topic as source. **This works because** Pipes can filter and enrich records and send them to targets like Step Functions without a custom consumer.
- **If** a **5 MB** image must go through Kafka, **then** store it in **Amazon S3** and send its key in Kafka (the claim-check pattern). **This works because** the Kafka default max record is about **1 MB**, and larger records need limit changes on topics, brokers, producers and consumers together.

Verified from AWS docs on 2026-11-02 (MSK default configuration, best practices for Kafka clients, version upgrade best practices, IAM action semantics, consumer lag, troubleshooting, Lambda MSK ESM pages: configure, network, parameters, starting positions, scaling modes, on-failure, auth; Firehose MSK source; Redshift streaming ingestion from Kafka; DMS Kafka target; MSK data delivery / streaming tables; MSK quotas).
Unconfirmed (verify): Lambda schema registry decoding mode requirement; OpenSearch Ingestion Kafka/MSK source; Kafka default `offsets.retention.minutes` on MSK; topic name 249-char limit on MSK (Kafka rule); EventBridge Pipes MSK auth options; Glue streaming auth options for MSK.

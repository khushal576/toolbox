# Kinesis Data Streams – 1. Concepts, records, shards and capacity modes

Short notes. Each point is a fact you can be asked about.

## A. What KDS is
- Kinesis Data Streams (KDS) = managed, durable, real-time stream. Producers write records; consumers read them.
- Records are ordered inside a shard. Different shards have no shared order.
- Records stay for the retention period (24 hours default, up to 365 days). Consumers can re-read (replay) any time inside that window.
- Reading does not delete a record. Many consumer apps read the same data on their own, each at its own position.
- Data is copied across 3 Availability Zones in the Region. You do not manage servers or disks.
- KDS is a Regional service. There is no built-in cross-Region replication (see file 3 for patterns).
- Typical latency from write to read: about 200 ms with polling, about 70 ms with enhanced fan-out (EFO).
- Pick KDS for: clickstreams, IoT telemetry, app and log events, change data capture (CDC) fan-out, real-time dashboards, feeding Flink, Lambda, Firehose, Spark.
- Pick KDS when you need replay, many independent consumers, per-key ordering, and sub-second latency.
- Avoid KDS when you only need to land data in S3/Redshift/OpenSearch with no custom reads → Amazon Data Firehose is simpler.
- Avoid KDS for one-consumer work queues where each message is deleted after processing → SQS.
- Avoid KDS when you need Kafka APIs, Kafka tools, or very long retention by default → Amazon MSK.
- Avoid KDS for routing events by content to many targets with rules → EventBridge.
- Kinesis family today: Kinesis Data Streams, Amazon Data Firehose (renamed from Kinesis Data Firehose), Kinesis Video Streams. Kinesis Data Analytics was renamed Amazon Managed Service for Apache Flink; Kinesis Data Analytics for SQL is shut down.

## B. Core terms
- Stream = an ordered set of shards. A stream name is up to 128 characters, unique per account and Region.
- Shard = the unit of capacity and of ordering. Each shard owns a range of hash keys.
- Shard ID looks like `shardId-000000000000`.
- Record (data record) = partition key + sequence number + data blob + approximate arrival timestamp.
- Data blob = bytes. KDS never reads, changes, or validates it. The payload is immutable once written.
- Producer = any app that writes (SDK, KPL, Kinesis Agent, AWS service).
- Consumer = any app that reads (Lambda, KCL app, Flink, Firehose, Spark, Redshift).
- "Kinesis Data Streams application" = a consumer, usually built with KCL.
- Shared-throughput consumer = polls with `GetRecords` and shares the shard's 2 MB/s read.
- Enhanced fan-out consumer = registered consumer that gets its own 2 MB/s per shard, pushed with `SubscribeToShard`.
- Stream ARN format: `arn:aws:kinesis:<region>:<account>:stream/<name>`. Consumer ARN adds `/consumer/<name>:<timestamp>`.
- Stream status values: CREATING, ACTIVE, UPDATING, DELETING. Reads and writes keep working while UPDATING.

## C. Records and record size
- Max data payload is up to 10 MiB per record, before base64 encoding.
- The default max record size for new and existing streams is still 1 MiB. You must raise it on purpose.
- Raise it with `UpdateMaxRecordSize` (1024–10240 KiB) or `MaxRecordSizeInKiB` on `CreateStream`. `DescribeStreamSummary` shows the value.
- The API reference says `UpdateMaxRecordSize` works only on provisioned streams; the large-records guide says on-demand handles large records too **(verify)**.
- Large records (1–10 MiB) use burst capacity. Shard limits stay the same: 1 MB/s write, 2 MB/s read.
- Burst capacity works like a tank that refills. After a big record, small writes may throttle until it refills.
- AWS advice: keep large records under about 2% of traffic. For steady large payloads, store the object in S3 and send only a pointer (claim-check pattern).
- Catch: check every consumer before raising the limit. Lambda takes up to 6 MiB per invoke payload (after base64); larger records go to the on-failure destination.
- Catch: Firehose cannot deliver large records to HTTP, Snowflake, or Redshift destinations, or with dynamic partitioning.
- Catch: Redshift streaming ingestion skips records above its max size and logs them in `SYS_STREAM_SCAN_ERRORS`.
- Large records are available only in listed Regions (most commercial Regions, GovCloud).
- Partition key = Unicode string, up to 256 characters. It counts toward the request size.
- Approximate arrival timestamp is set by KDS when the record is accepted. `AT_TIMESTAMP` iterators use it.

## D. Partition keys and hashing
- KDS runs MD5 on the partition key to get a 128-bit number (0 to 2^128 − 1).
- Each shard owns a contiguous hash key range (`StartingHashKey`, `EndingHashKey`). The record goes to the shard whose range holds the hash.
- Same partition key → same hash → same shard → ordered for that key.
- `ExplicitHashKey` lets a producer pick the hash value directly. Use it to target a shard on purpose (rare).
- High-cardinality keys (user ID, device ID, order ID) spread load evenly. Low-cardinality keys (country, status) make hot shards.
- Hot shard = one shard gets more than 1 MB/s or 1,000 records/s while others are idle. Writes to it throttle.
- Fix a hot key by salting: add a suffix (for example `deviceId#0..9`). Catch: you lose ordering across the salted pieces.
- A random partition key spreads load best but gives no per-entity order.
- A single partition key can never exceed one shard's 1 MB/s and 1,000 records/s, in any mode. More shards do not help one key.
- In provisioned mode you can split exactly the hot shard's hash range. On-demand splits shards evenly and cannot isolate one hot key.
- Do not put secrets or PII in partition keys. Keys show in logs, metrics tools and consumer events.

## E. Sequence numbers and ordering
- KDS gives each record a sequence number when the write succeeds. You do not set it.
- Sequence numbers are unique per partition key within a shard. They usually grow over time.
- The longer the gap between writes, the bigger the jump in sequence number. They are not a dense counter or an index.
- Do not compare sequence numbers across shards or streams to decide order.
- `PutRecord` has `SequenceNumberForOrdering`: pass the previous record's sequence number to force strict order for the same key from one producer.
- Without it, records from one producer are grouped by key but can be reordered when retried.
- `PutRecords` does not keep order on retry. If record 3 fails and you resend it, it lands after record 4.
- A subsequence number exists for KPL-aggregated records (one sequence number, many user records inside).
- Consumers checkpoint by sequence number (plus subsequence for KPL aggregation).

## F. Shard throughput limits (per shard)
- Write: 1 MB/s or 1,000 records/s, whichever comes first.
- Read (shared): 2 MB/s total across all polling consumers, and 5 `GetRecords` calls per second.
- Read (EFO): 2 MB/s per registered consumer per shard, not shared.
- One `GetRecords` call returns up to 10 MB or 10,000 records.
- If a `GetRecords` call returns 10 MB, calls in the next 5 seconds throw `ProvisionedThroughputExceededException`.
- The quota page also lists "2,000 records/s" for read per shard **(verify)**.
- Many small records hit the 1,000 records/s limit before 1 MB/s. Fix with KPL aggregation (file 2).
- The 5 reads/s limit is why AWS advises at most about 2 polling consumers per shard, or EFO for more.

## G. Retention
- Default 24 hours. Minimum 24 hours. Maximum 8,760 hours (365 days).
- Change with `IncreaseStreamRetentionPeriod` and `DecreaseStreamRetentionPeriod` (5 TPS per stream).
- Extended retention = 24 hours to 7 days (168 hours). Long-term retention = beyond 7 days up to 365 days. Both cost extra.
- Decreasing retention makes older records unreadable right away. Data is gone; plan before you shrink.
- Retention starts at the record's arrival time. Resharding does not reset or lose data inside retention.
- Records expire by age only. You cannot delete one record. For "right to be forgotten", keep PII out of the stream or encrypt per subject and drop the key.
- If a consumer falls behind by more than the retention period, unread records are lost for that consumer.
- Retention is not a backup of past streams. Deleting a stream deletes all its data at once.
- For long archive, copy the stream to S3 (Firehose or KDS S3 delivery), then use S3 lifecycle.

## H. Capacity modes overview
| | On-demand Standard | On-demand Advantage | Provisioned |
|---|---|---|---|
| Scope | per stream | account-level setting per Region, applies to all on-demand streams | per stream |
| Sizing | automatic | automatic + optional warm throughput | you set shard count |
| Default new stream | 4 MB/s write, 8 MB/s read | same | shard count you choose |
| Max (default) | 10 GB/s write / 20 GB/s read in us-east-1, us-west-2, eu-west-1; 200 MB/s / 400 MB/s elsewhere (raise by ticket) | same | no upper limit; shard quota |
| Price shape | stream-hour + GB in + GB out | GB in + GB out only, lower rates, 25 MiB/s minimum | shard-hour + PUT payload units |
| EFO consumers | 20 | 50 (listed Regions) | 20 |
| Warm throughput | no | yes | not needed (you set shards) |
- All three modes use the same APIs: `PutRecord(s)`, `GetRecords`, `SubscribeToShard`.
- Encryption, retention, metrics, durability work the same in all modes.

## I. On-demand Standard
- No capacity planning. KDS adds and removes shards for you.
- You pay per GB written and read plus a per-stream hourly fee.
- Scales to handle up to double the peak write throughput seen in the previous 30 days.
- Example: traffic between 10 and 40 MB/s → it can burst to 80 MB/s. A new sustained peak of 50 MB/s → room for 100 MB/s.
- Catch: if traffic more than doubles the previous peak within 15 minutes, writes can throttle for about 15 minutes. Producers must retry.
- KDS splits a shard when its incoming traffic exceeds about 500 KB/s, within about 15 minutes.
- Splits are even. It does not detect one hot hash key. A single key over 1 MB/s still throttles.
- Read capacity grows with write capacity. You get at least twice the write throughput for `GetRecords` reads.
- AWS advises one polling consumer per on-demand stream; use EFO for more consumers.
- Default quota: 50 on-demand streams per account per Region (raise by support ticket).
- FAQ also states a new on-demand stream allows about 4,000 records/s write at start **(verify)**.
- Best for: new streams, unknown traffic, spiky traffic, teams that do not want to watch shards.

## J. On-demand Advantage
- An account-level setting per Region, turned on with `UpdateAccountSettings`. It changes all on-demand streams in that Region.
- No per-stream hourly charge. Data in, data out, and extended retention are at least 60% cheaper than On-demand Standard.
- EFO reads cost the same as normal reads (no EFO premium).
- Up to 50 EFO consumers per stream (only in listed Regions).
- Commitment: at least 25 MiB/s data ingest and 25 MiB/s data retrieval across all on-demand streams in the Region.
- If usage is below the minimum, you pay the shortfall at the discounted rate.
- After you turn it on, you must wait at least 24 hours before turning it off.
- Before you switch back to On-demand Standard, you must remove warm throughput from all on-demand streams.
- Warm throughput: pre-scale a stream's write capacity before a known event (for example set 200 MB/s before a launch). No extra cost.
- Set it with `UpdateStreamWarmThroughput`. The max is the account's on-demand stream throughput limit for the Region.
- Scale down after a burst: set warm throughput to the same or lower value. Capacity drops to that value or to last hour's peak need, whichever is higher.
- Best for: steady volume near or above 25 MiB/s, many consumers, or hundreds of streams (stream-hour fees add up).
- Catch: small accounts pay for the 25 MiB/s minimum. Check the console's fit check first.

## K. Provisioned mode
- You choose the number of shards. Capacity = sum of the shards.
- You pay per shard-hour whether you use it or not, plus PUT payload units.
- Scale with `UpdateShardCount`, `SplitShard`, `MergeShards` (file 2). Reads and writes continue during scaling.
- Default shard quota: 20,000 per account in us-east-1, us-west-2, eu-west-1; 1,000 or 6,000 in other Regions. Adjustable in Service Quotas.
- Best for: steady, predictable traffic; tight cost control; need for precise splits of hot hash ranges.
- Catch: you must watch metrics and scale before peaks. Under-sized streams throttle.
- No automatic scaling. You can build it with CloudWatch alarms + Lambda calling `UpdateShardCount` (or Application Auto Scaling custom resource) **(verify)**.

## L. Sizing math for provisioned mode
- Inputs: average record size (KB, rounded up), records per second, number of polling consumers.
- Incoming write KB/s = average record KB × records/s.
- Outgoing read KB/s = incoming write KB/s × number of shared-throughput consumers.
- Shards = ceiling(max(write KiB/s ÷ 1024, read KiB/s ÷ 2048)).
- Also check records: shards ≥ records/s ÷ 1,000.
- Example: 2,000 records/s × 3 KB = 6,000 KB/s write → 6 shards for write. Two polling consumers → 12,000 KB/s read ÷ 2,048 → 6 shards. Answer 6, plus headroom.
- Example: 5,000 records/s × 0.2 KB = 1,000 KB/s → 1 shard by bytes, but 5 shards by record count. Answer 5 (or 1–2 with KPL aggregation).
- With EFO consumers, reads do not add to the shared 2 MB/s, so size by write only.
- Add 20–30% headroom and plan for the busiest minute, not the daily average.
- Hot keys break the math. Size for the busiest shard, not the average.

## M. Switching modes
- Switch between on-demand and provisioned twice per rolling 24 hours per stream (`UpdateStreamMode`).
- No downtime. The stream status becomes UPDATING, then ACTIVE. Wait for ACTIVE before other changes.
- The stream keeps its current shard count at the switch. After that, either KDS (on-demand) or you (provisioned) manage it.
- Moving to provisioned after a quiet period can leave you with too few shards. Check shard count right after.
- Switching On-demand Standard ↔ Advantage is the account setting, not `UpdateStreamMode`.
- KDS data delivery (S3 and Iceberg streaming tables) needs an on-demand mode. A provisioned stream cannot use it.

## N. Creating and deleting streams
- `CreateStream` takes a name, mode, and shard count (provisioned). Status CREATING, then ACTIVE.
- Max 5 streams in CREATING state at once per account (`LimitExceededException`).
- `CreateStream` and `DeleteStream` are each limited to 5 TPS per account.
- `DeleteStream` with registered EFO consumers needs `EnforceConsumerDeletion=true`, or deregister them first.
- Deleting a stream deletes all records. It cannot be undone.
- Up to 50 tags per stream. Tags work for cost allocation and ABAC.
- `DescribeStreamSummary` (20 TPS per account) is preferred over `DescribeStream` (10 TPS per account) to avoid throttling.
- `ListShards` allows 1,000 TPS per stream. Use it instead of `DescribeStream` to list shards.

## O. Scenarios
- If several teams must read the same events independently and replay last week → KDS with 7-day retention, because records stay and each consumer tracks its own position.
- If one app just needs events in S3 as files with no custom code → Firehose or KDS S3 delivery, because no consumer code is needed.
- If a new stream has unknown traffic → On-demand Standard, because it scales with no shard planning.
- If traffic is steady at 40 MiB/s across 30 streams with 5 consumers → On-demand Advantage, because per-GB prices are lower, no stream-hour fees, and EFO is free.
- If an account only sends 2 MB/s total → not On-demand Advantage, because you pay for the 25 MiB/s minimum.
- If a flash sale will jump traffic 10× in one minute → set warm throughput (Advantage) or pre-scale shards, because on-demand only absorbs 2× the prior peak instantly.
- If traffic is flat at 8 MB/s all day → provisioned with about 10 shards, because shard-hours are cheap at steady load.
- If one device ID sends 3 MB/s → split its data with a salted key or pre-aggregate, because one key is capped at 1 MB/s.
- If writes throttle on one shard only in on-demand → better partition keys or provisioned with a targeted split, because on-demand splits evenly.
- If 5,000 tiny records per second land on one shard → KPL aggregation, because 1,000 records/s is hit before 1 MB/s.
- If an IoT device sometimes sends 4 MiB images → raise max record size to 5 MiB and use random keys, because large records ride burst capacity.
- If payloads are always 5 MiB → put the payload in S3 and send the S3 key, because large records are for intermittent use.
- If a record must stay ordered with the next record from the same producer → same partition key plus `SequenceNumberForOrdering`, because order is only per key per shard.
- If a consumer was down for 30 hours on a 24-hour stream → data older than 24 hours is lost, because retention expired; raise retention before outages matter.
- If the team shrinks retention from 7 days to 1 day → records older than 1 day vanish at once, because decrease takes effect immediately.
- If a stream must be switched to provisioned three times today → not possible, because only two mode switches are allowed per 24 hours.
- If KDS S3 delivery is needed on a provisioned stream → switch to on-demand, because data delivery needs on-demand.
- If someone needs strict global order across all events → one shard (1 MB/s cap) or order by key only, because KDS orders per shard.
- If a job lists shards often and gets throttled → use `ListShards`, because `DescribeStream` has a low account-wide TPS.
- If an exam option says "delete one bad record from the stream" → wrong, because records are immutable and expire only by retention.

Verified from AWS docs on 2026-11-01 (KDS quotas and limits, choose the right mode, large records, UpdateShardCount API, key concepts, pricing page).
Unconfirmed (verify): whether `UpdateMaxRecordSize` works on on-demand streams; 2,000 records/s read figure; 4,000 records/s on-demand start figure; auto scaling of provisioned streams via Application Auto Scaling.

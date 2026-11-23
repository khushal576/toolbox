# Kinesis Data Streams – 4. Security, monitoring, cost, limits, comparisons and scenarios

Short notes. Each point is a fact you can be asked about.

## A. IAM (identity-based access)
- All access is through IAM. There are no stream users or passwords.
- Producer actions: `kinesis:PutRecord`, `kinesis:PutRecords` (plus `DescribeStreamSummary`/`ListShards` for some libraries).
- Polling consumer actions: `GetShardIterator`, `GetRecords`, `ListShards`, `DescribeStreamSummary`.
- EFO consumer actions: `RegisterStreamConsumer`, `DescribeStreamConsumer`, `SubscribeToShard` (scoped to the consumer ARN).
- Admin actions: `CreateStream`, `DeleteStream`, `UpdateShardCount`, `SplitShard`, `MergeShards`, `UpdateStreamMode`, retention and encryption calls.
- Scope policies to stream ARNs and consumer ARNs. Do not give `kinesis:*` on `*` to apps.
- Separate roles: producers write only, consumers read only, admins reshard. Least privilege.
- Tags on streams support ABAC conditions (`aws:ResourceTag/...`) **(verify KDS ABAC coverage)**.
- AWS managed policies exist (for example `AmazonKinesisFullAccess`, `AmazonKinesisReadOnlyAccess`); too broad for production apps.
- Services that read or write for you need a role: Firehose delivery role, Lambda execution role, Flink app role, CloudWatch Logs role, IoT rule role, DMS role, delivery service role.
- Lambda ESM permissions come from the function's execution role (for example `AWSLambdaKinesisExecutionRole`).

## B. Resource-based policies (cross-account)
- Attach with `PutResourcePolicy` to a stream or to a registered EFO consumer.
- Lets principals in other accounts produce or consume without assuming a role in your account.
- Sharable actions: `DescribeStreamSummary`, `DescribeStreamConsumer`, `GetRecords`, `GetShardIterator`, `ListShards`, `PutRecord`, `PutRecords`, `SubscribeToShard` (include `DescribeStream` when sharing).
- The other account's principal also needs an identity policy allowing the action.
- EFO sharing needs a policy on both the stream ARN and the consumer ARN.
- Limits: no wildcard principals, no service or federated principals, no canonical user IDs, policy max 20 KB.
- A stream encrypted with the AWS managed key `aws/kinesis` cannot be shared this way; switch to a customer managed key and allow the other account in the key policy.
- Lambda in account B can map to a stream in account A through the stream's resource policy.
- `PutResourcePolicy`, `GetResourcePolicy`, `DeleteResourcePolicy`: 5 TPS per account.
- Alternative for older designs: a role in the stream account that the other account assumes.

## C. Encryption at rest (SSE-KMS)
- Server-side encryption uses AWS KMS. Data is encrypted before it is written to storage and decrypted on read.
- Key choices: AWS managed key `aws/kinesis` (free key, limited sharing) or a customer managed key (key policy control, cross-account, rotation control).
- Turn on with `StartStreamEncryption`, off with `StopStreamEncryption`. Each can succeed 25 times per rolling 24 hours per stream.
- Turning on encryption is not retroactive for records already stored **(verify)**.
- Producers need `kms:GenerateDataKey`; consumers need `kms:Decrypt` on the key.
- KDS caches data keys, so KMS calls are fewer than records, but heavy loads can still cause `KMSThrottlingException`.
- KMS request charges apply for customer managed keys and data key calls.
- If the key is disabled or deleted, writes and reads fail (`KMSDisabledException`, `KMSNotFoundException`). Deleted key = unreadable data.
- KDS data delivery cannot use a source stream encrypted with `aws/kinesis`; destination must use a customer managed key for SSE-KMS.
- Client-side encryption (encrypt payload before `PutRecord`) protects data from anyone with stream read access; consumers must decrypt.

## D. Encryption in transit and network
- All API calls use HTTPS (TLS). FIPS 140 endpoints exist in US Regions.
- Interface VPC endpoint (AWS PrivateLink) for KDS keeps traffic on the AWS network; no internet gateway or NAT needed.
- FIPS-enabled interface endpoints exist for US Regions.
- There is no gateway endpoint for KDS (gateway endpoints are only S3 and DynamoDB).
- Endpoint policies can limit which streams and actions are reachable through the endpoint.
- IAM condition `aws:SourceVpce` (in a Deny with `StringNotEquals`) forces access only through one endpoint.
- KPL and KCL also call CloudWatch and DynamoDB; in private subnets add those endpoints (DynamoDB gateway endpoint, CloudWatch interface endpoint).
- Data delivery, Firehose and Lambda pollers run in AWS-managed networks; they reach the stream without your VPC.

## E. Auditing with CloudTrail
- Control-plane calls (CreateStream, DeleteStream, UpdateShardCount, StartStreamEncryption, PutResourcePolicy, etc.) are logged as management events by default.
- Data-plane calls (`PutRecord`, `PutRecords`, `GetRecords`, `GetShardIterator`, `SubscribeToShard`) can be logged as CloudTrail data events; you opt in and pay **(verify)**.
- Data events are high volume. Use advanced event selectors to log only chosen streams.
- CloudTrail shows who called, from which IP, when, with what parameters. Payloads are not logged.
- Use AWS Config to track stream configuration (encryption on/off, retention) and alert on drift.

## F. Data protection patterns
- Keep PII out of partition keys (keys appear in tools and metrics).
- Tokenize or mask PII before writing, or encrypt fields client-side.
- Records cannot be deleted one by one; "delete my data" requests are met by short retention or crypto-shredding.
- Govern the S3/Iceberg output with Lake Formation and Macie, not the stream itself.
- Limit who can call `GetRecords`: any reader sees all records in the stream.

## G. Monitoring basics
- CloudWatch namespace `AWS/Kinesis`. Metrics every minute, kept per CloudWatch retention (KDS docs say metrics are archived two weeks) **(verify vs CloudWatch 15-month retention)**.
- Basic stream-level metrics: free, automatic, dimension `StreamName`.
- Enhanced shard-level metrics: turn on with `EnableEnhancedMonitoring`; billed as custom metrics per shard per metric.
- Use shard-level metrics to find hot shards and uneven keys.
- KPL emits its own metrics; KCL emits metrics in a namespace equal to the application name.

## H. Key stream metrics
- `IncomingBytes`, `IncomingRecords`: successful writes. Compare with shard count × 1 MB/s and 1,000 records/s.
- `PutRecord.Success`, `PutRecords.Success` (Average) for producer health. With KPL use `PutRecords.Success`.
- `PutRecords.TotalRecords`, `PutRecords.SuccessfulRecords`, `PutRecords.FailedRecords` (internal), `PutRecords.ThrottledRecords`.
- `WriteProvisionedThroughputExceeded`: records throttled on write. Any sustained value > 0 means hot shard or too little capacity.
- `ReadProvisionedThroughputExceeded`: `GetRecords` calls throttled. Too many polling consumers or too frequent polls.
- `GetRecords.IteratorAgeMilliseconds`: age of the last record read; how far consumers lag. The most important alarm.
- `GetRecords.Bytes`, `GetRecords.Records`, `GetRecords.Latency`, `GetRecords.Success`.
- `SubscribeToShardEvent.MillisBehindLatest`: lag for each EFO consumer (dimension `ConsumerName`).
- `SubscribeToShard.Success` and `SubscribeToShard.RateExceeded` for EFO subscriptions.
- Enhanced shard metrics: `IncomingBytes`, `IncomingRecords`, `OutgoingBytes`, `OutgoingRecords`, `IteratorAgeMilliseconds`, `ReadProvisionedThroughputExceeded`, `WriteProvisionedThroughputExceeded` per `ShardId`.
- Note: `GetRecords.IteratorAgeMilliseconds` covers polling consumers; EFO lag uses `MillisBehindLatest`.

## I. Alarms to set
- Iterator age (Maximum) > 50% of retention → risk of data loss. AWS recommends alarming on Maximum.
- Iterator age rising for 15+ minutes → consumers too slow; act before 50%.
- `WriteProvisionedThroughputExceeded` (Average) > 0 for several minutes → producer throttling.
- `ReadProvisionedThroughputExceeded` > 0 → read contention; consider EFO.
- `PutRecords.FailedRecords` or `ThrottledRecords` > 0 → producers must retry; check capacity.
- Lambda `IteratorAge`, `Errors`, `Throttles`, `ConcurrentExecutions` for Lambda consumers.
- KCL `MillisBehindLatest`, `RecordsProcessed`, `LeasesHeld`, `LeaseTakeover` style metrics; DynamoDB `ThrottledRequests` on KCL tables.
- Send alarms to SNS; use EventBridge for automated actions (for example scale shards).

## J. Data delivery monitoring
- Delivery metrics: bytes and records delivered, data freshness, failures (`AWS/Kinesis` delivery metrics) **(verify metric names)**.
- Turn on delivery logging to CloudWatch Logs for batch details and error context.
- Check the S3 dead-letter queue for invalid records (IDs and error context).
- Failed deliveries routed to the DLQ are not billed.

## K. Cost: provisioned mode (US East example prices)
- Shard-hour: $0.015 per shard-hour (about $0.36 per day, ~$11 per month per shard).
- PUT payload units: $0.014 per million. Each record is counted in 25 KB chunks: a 5 KB record = 1 unit; a 1 MB record = 40 units.
- A 1 KB record still uses a full 25 KB unit. Small records waste units → aggregate with KPL.
- Extended retention (up to 7 days): $0.020 per shard-hour.
- Long-term retention (8–365 days): $0.023 per GB-month stored; $0.021 per GB retrieved with `GetRecords`. Long-term reads with EFO are free.
- EFO: $0.015 per consumer-shard-hour + $0.013 per GB retrieved.
- Example from pricing page: 4 shards, 100 records/s × 35 KB → $44.64 shards + $7.50 PUT units = $52.14/month; with 7-day retention about $111.66.
- Cross-Region reads: no extra data transfer in provisioned mode (per pricing page).

## L. Cost: on-demand modes (US East example prices)
- On-demand Standard: $0.04 per stream-hour + $0.08 per GB in + $0.04 per GB out.
- Data in is rounded up to the nearest 1 KB per record; data out is not rounded.
- Example: 1,000 records/s × 3 KB, 1 consumer → about $918/month ($593 in + $297 out + $29 stream-hours).
- On-demand Standard EFO and extended retention prices are extra per GB **(verify rates)**.
- On-demand Advantage: $0.032 per GB in + $0.016 per GB out, no stream-hour fee, EFO at the normal out rate, warm throughput free.
- Advantage minimum: 25 MiB/s in and 25 MiB/s out across all on-demand streams in the Region; shortfall billed at the discounted rate.
- Example: 3,000 records/s × 10 KB on Advantage → about $3,560/month; 1,000 records/s × 10 KB → about $3,038 including shortfall.
- Cross-Region reads in on-demand modes pay normal data transfer.
- Data delivery add-on (per GB, us-east-2 example): S3 delivery $0.011 (Advantage) / $0.0275 (Standard); streaming tables $0.014 / $0.035 on uncompressed data.

## M. Other costs and cost levers
- Other costs: KMS requests, KCL DynamoDB tables, CloudWatch enhanced metrics and logs, CloudTrail data events, consumer compute, cross-Region transfer.
- KDS is not in the AWS Free Tier. Same-Region transfer between KDS and your EC2/Lambda is free.
- Lever: KPL aggregation and compression → fewer PUT units and fewer bytes.
- Lever: pick the right mode (on-demand for spiky, provisioned for steady, Advantage for large steady volume or many streams).
- Lever: merge cold shards / scale down at night with `UpdateShardCount` (max 10 per day).
- Lever: remove unused EFO consumers and enhanced metrics.
- Lever: keep retention only as long as replay needs; archive to S3 instead of long-term retention.
- Lever: delete idle on-demand Standard streams (stream-hour fee even with no traffic).
- Lever: use Firehose or KDS data delivery instead of always-on custom consumers when only landing data.

## N. Limits and numbers to remember
| Item | Value |
|---|---|
| Shard write | 1 MB/s or 1,000 records/s |
| Shard read (shared) | 2 MB/s, 5 GetRecords/s |
| Shard read (EFO) | 2 MB/s per consumer |
| GetRecords per call | 10 MB or 10,000 records; 5 s penalty after 10 MB |
| Record payload | up to 10 MiB (default stream max 1 MiB) |
| PutRecords | 500 records, 10 MiB per request |
| Partition key | 256 characters |
| Retention | 24 h default, 24 h min, 8,760 h (365 days) max |
| Shard iterator life | 5 minutes |
| EFO consumers | 20 per stream (50 on Advantage); 5 in CREATING at once |
| SubscribeToShard | 5-minute subscription; 1 call/s per consumer per shard |
| On-demand streams | 50 per account per Region (default) |
| On-demand default/max | 4 MB/s write at start; 10 GB/s (3 big Regions) or 200 MB/s elsewhere |
| Provisioned shard quota | 20,000 (us-east-1, us-west-2, eu-west-1); 1,000 or 6,000 elsewhere |
| UpdateShardCount | 10 per 24 h, 2× up, 50% down, 10,000 shards per stream |
| Mode switches | 2 per 24 h per stream |
| SSE start/stop | 25 per rolling 24 h each |
| Tags | 50 per stream |
| Streams in CREATING | 5 at once |
| Data deliveries per stream | 2 (one S3, one streaming table) |
| Resource policy size | 20 KB |
- Control-plane TPS (per account unless noted): `CreateStream` 5, `DeleteStream` 5, `DescribeStream` 10, `DescribeStreamSummary` 20, `ListStreams` 5, `ListShards` 1,000 per stream, `DescribeLimits` 1, `RegisterStreamConsumer` 5 per stream, `UpdateStreamWarmThroughput` 5.

## O. Troubleshooting: producers
| Symptom | Cause | Fix |
|---|---|---|
| `ProvisionedThroughputExceededException` on put | shard over 1 MB/s or 1,000 rec/s; hot key; on-demand ramp > 2× | backoff + retry; better keys; more shards; warm throughput; KPL aggregation |
| Some records missing after `PutRecords` | partial failure ignored | check `FailedRecordCount`, retry failed entries |
| Duplicates downstream | producer retry after timeout | event IDs and idempotent consumers |
| `KMSThrottlingException` | KMS quota reached | retry; request higher KMS quota |
| `AccessDeniedException` with SSE | missing `kms:GenerateDataKey` | add key policy/IAM permission |
| `InvalidArgumentException` record too large | record above stream max size | `UpdateMaxRecordSize` or S3 pointer |
| Throttle only on one shard | skewed partition key | salt key, split that shard (provisioned) |
| KPL memory grows, records expire | no backpressure, `RecordTtl` hit | limit outstanding records; raise TTL; add capacity |

## P. Troubleshooting: consumers
| Symptom | Cause | Fix |
|---|---|---|
| Iterator age rising | slow processing, too few workers, Lambda errors/throttles | scale workers (≤ shards), raise parallelization factor, optimize code, EFO |
| `ReadProvisionedThroughputExceeded` | too many polling consumers or polls | EFO, fewer consumers, poll less often |
| `ExpiredIteratorException` | iterator older than 5 minutes | get a new iterator from last sequence number |
| Data lost | lag exceeded retention | longer retention, alarms at 50%, faster consumers |
| Lambda stuck on one batch | poison record, infinite retries | bisect, max retries, max age, on-failure destination, partial batch response |
| KCL not processing children | no checkpoint in `shardEnded` | checkpoint at shard end |
| KCL stalls | DynamoDB lease table throttled | on-demand tables or higher capacity |
| Leases bounce between workers | long GC pauses, overloaded hosts, short failover time | bigger hosts, tune failover, KCL 3.x |
| Garbled data | KPL aggregation not de-aggregated, or gzip from CloudWatch Logs | de-aggregate; decompress |
| `ResourceInUseException` on SubscribeToShard | re-subscribe within 5 s | wait, let KCL manage |
| Cannot register EFO consumer | 20/50 limit or 5 in CREATING | deregister unused; wait |
| Out-of-order records | across keys (normal) or children read before parent | rely on per-key order; use KCL/Lambda |
| Unexpected on-demand bill | idle streams, EFO GB, high volume | Advantage, provisioned, delete idle streams |

## Q. Availability, durability and operations
- KDS stores records synchronously across 3 AZs in a Region; an AZ failure does not lose acknowledged records.
- A Region outage stops the stream; plan cross-Region copies yourself (consumer that writes to another Region).
- A write is durable once `PutRecord(s)` returns success for that record.
- KPL and KCL write their own logs (application logs); ship them to CloudWatch Logs with the CloudWatch agent for troubleshooting.
- Use infrastructure as code (CloudFormation `AWS::Kinesis::Stream`, `AWS::Kinesis::StreamConsumer`, `AWS::Kinesis::ResourcePolicy`) for repeatable setups.
- `DescribeLimits` (1 TPS) shows the account's shard limit and open shard count.
- Service Quotas shows shard quota usage; request increases there (or support ticket for on-demand stream count and throughput).
- Tag streams for cost allocation; costs show under Kinesis in Cost Explorer.
- Test producers and consumers against throttling: retries with jitter, idempotent writes, dead-letter paths.
- Run consumers in at least 2 AZs (KCL workers in an Auto Scaling group or ECS service), so one AZ loss only moves leases.

## R. Kinesis Video Streams (short)
- Separate service for video, audio, and time-encoded data (cameras, radar, LIDAR), not general events.
- Producers use the KVS Producer SDK (C, C++, Java, Android); data is split into fragments.
- Consumers: HLS and MPEG-DASH playback, `GetMedia`, `GetClip` (MP4 download), image extraction, Amazon Rekognition Video.
- Retention from 0 (no storage, live only) up to 10 years **(verify max)**.
- WebRTC signaling channels support two-way, low-latency live media (for example video calls, IoT cameras).
- Encrypted at rest with KMS; pay per GB ingested, stored and consumed.
- Pick KVS for video. Pick KDS for JSON/binary event records.

## S. Comparison: KDS vs SQS vs SNS vs MSK vs Firehose vs EventBridge
| | KDS | SQS | SNS | MSK | Firehose | EventBridge |
|---|---|---|---|---|---|---|
| Model | ordered log, pull/push | queue, pull | pub/sub push | Kafka log | managed delivery | event bus, rules |
| Replay | yes, within retention | no (deleted after processing) | no (archive option) | yes, retention/tiered storage | no | archive and replay |
| Consumers | many independent | one per message | many subscribers | many consumer groups | one destination per stream | many targets per rule |
| Ordering | per shard/key | FIFO queues only | FIFO topics only | per partition | n/a | no |
| Retention | 24 h – 365 days | up to 14 days | none | configurable, unlimited with tiered storage | none (buffer only) | archive optional |
| Scaling | shards or on-demand | automatic | automatic | brokers / serverless | automatic | automatic |
| Latency | ~70–200 ms | ms | ms | ms | seconds to minutes (buffer) | ~sub-second |
| Max message | 10 MiB | 1 MiB **(verify)** | 256 KB | configurable (default 1 MB) | 1 MiB (10 MiB from KDS to S3) | 256 KB |
| Best for | real-time analytics, fan-out, replay | decoupled work queues | notifications, fan-out | Kafka apps, ecosystem | land data in S3/Redshift/OpenSearch | SaaS/AWS event routing |
- KDS vs MSK: KDS is serverless-like and AWS-native; MSK gives Kafka APIs, Connect, longer default retention, more tuning work.
- KDS vs Firehose: Firehose is a delivery pipe (no replay, no custom readers); often used together (KDS → Firehose → S3).
- KDS vs SQS: SQS deletes after processing and scales without shards; KDS keeps data for many readers.
- SNS + SQS fan-out works for notifications; KDS fan-out works for high-volume ordered streams.

## T. Scenarios
- If compliance requires encryption with a key the company controls → SSE with a customer managed KMS key, because key policy and CloudTrail give control and audit.
- If a stream must be shared with a partner account for reads → stream resource policy (and consumer policy for EFO) with a customer managed key, because `aws/kinesis` cannot be shared.
- If producers in private subnets must not use the internet → interface VPC endpoint for KDS, because there is no gateway endpoint for Kinesis.
- If only one VPC endpoint may access the stream → IAM Deny with `aws:SourceVpce` condition, because it blocks other network paths.
- If KCL workers in a private subnet hang → add DynamoDB and CloudWatch endpoints, because KCL calls both.
- If auditors ask who deleted a stream → CloudTrail management events, because control-plane calls are logged by default.
- If auditors ask who read records → turn on CloudTrail data events for the stream, because data-plane calls are not in default trails.
- If writes fail with KMS errors after a key change → check key state and policy, because disabled keys block reads and writes.
- If you need warning before data loss → alarm on `GetRecords.IteratorAgeMilliseconds` Maximum at 50% of retention, because lag past retention drops data.
- If you need to find which shard is hot → enable enhanced shard-level metrics, because stream metrics hide per-shard skew.
- If `ReadProvisionedThroughputExceeded` grows after adding a third consumer app → EFO, because polling apps share 5 calls/s per shard.
- If a provisioned stream costs too much at night → scale down with `UpdateShardCount` (≤ 50% per call, 10 per day), because shard-hours are billed while open.
- If millions of 500-byte records make PUT unit cost high → KPL aggregation, because each record uses at least one 25 KB unit.
- If 40 dev on-demand streams sit idle → delete them or move to Advantage, because Standard charges per stream-hour.
- If traffic is 1 MB/s total in the account → stay on Standard or provisioned, because Advantage bills a 25 MiB/s minimum.
- If 30 consumer apps need the same stream → On-demand Advantage (50 EFO consumers, no EFO premium), because the normal limit is 20.
- If you need 1-year replay → long-term retention (365 days) or archive to S3, because S3 is cheaper for rarely read history.
- If a video doorbell must stream live and store clips → Kinesis Video Streams, because KDS is for records, not media fragments.
- If a decoupled worker pool must process each job once → SQS, because KDS keeps records for all readers.
- If an existing Kafka app must move to AWS with no code change → MSK, because KDS does not speak the Kafka protocol.
- If data only needs to reach S3 every few minutes → Firehose (or KDS S3 delivery), because no custom consumer is needed.
- If SaaS events must route to Lambda and Step Functions by content → EventBridge, because rules match event patterns.
- If a stream in us-east-1 may reach 5 GB/s → on-demand (up to 10 GB/s there) or provisioned with raised shard quota, because other Regions default to 200 MB/s.
- If a stream in another Region needs 1 GB/s on-demand → support ticket to raise to 10 GB/s, because the default ceiling is 200 MB/s there.
- If one AZ fails → acknowledged records are safe and KCL leases move to workers in other AZs, because KDS replicates across 3 AZs.
- If enhanced shard metrics add noticeable CloudWatch cost → turn them on only while troubleshooting, because each shard × metric is billed.
- If a KCL consumer and a Lambda consumer both poll a stream and Lambda lags → give one of them EFO, because they share read limits.
- If an exam asks how to stop paying for an unused EFO consumer → `DeregisterStreamConsumer`, because consumer-shard-hours run while registered.
- If a security team wants to block writes from outside the corporate VPC → endpoint policy + `aws:SourceVpce` Deny, because IAM alone allows any network path.
- If teams want least privilege → separate producer, consumer and admin roles scoped to stream ARNs, because one wide role can reshard or delete streams.

Verified from AWS docs on 2026-11-01 (KDS quotas, resource-based policy sharing, VPC endpoints, CloudTrail logging, CloudWatch monitoring, pricing page examples, data delivery pages, enhanced fan-out page).
Unconfirmed (verify): KDS ABAC coverage; SSE not retroactive; CloudTrail data events opt-in details; metric archive period wording; data delivery metric names; On-demand Standard EFO/extended retention rates; KVS max retention; SQS max message size in the comparison table.

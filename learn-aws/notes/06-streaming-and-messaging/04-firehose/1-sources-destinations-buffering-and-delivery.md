# Amazon Data Firehose – 1. Sources, destinations, buffering and delivery

Short notes. Each point is a fact you can be asked about.

## A. What Firehose is (and is not)
- Amazon Data Firehose = fully managed service that **delivers** streaming data to a destination. You configure it; there is no code, no servers, no shards.
- Old name: Amazon Kinesis Data Firehose (renamed to Amazon Data Firehose in 2024). Exam questions may use either name.
- The old name lives on in APIs and resources: API operations say `DeliveryStream`, IAM prefix is `firehose:`, the VPC endpoint service is `com.amazonaws.<region>.kinesis-firehose`, CloudFormation still has `AWS::KinesisFirehose::DeliveryStream`.
- Firehose stream (old name: delivery stream) = the main resource. Producers send records to it; it buffers, optionally transforms, then writes to one destination.
- It scales automatically. You never pick capacity, shards or partitions.
- Near real time, not real time: data waits in a buffer (seconds to 15 minutes) before delivery. Zero buffering cuts this to a few seconds for most destinations.
- It is a pipe, not a store. No replay, no custom readers, no consumer API. Once delivered, the data lives only at the destination.
- One Firehose stream has one destination (plus an optional S3 backup bucket). Need two destinations → two Firehose streams.
- Pick Firehose when: you just need to land streaming data in S3, a data lake table, Redshift, OpenSearch, Splunk, Snowflake or an observability tool with no code.
- Pick Firehose when you need batching, compression, JSON → Parquet/ORC, dynamic S3 partitioning, Lambda transforms, or Iceberg upserts, all managed.
- Avoid Firehose when: consumers need sub-second latency, replay, ordering guarantees, or many independent readers → Kinesis Data Streams (KDS) or Amazon MSK.
- Avoid Firehose for complex stateful stream processing (joins, windows, aggregations over time) → Managed Service for Apache Flink or Glue streaming.
- Common pattern: producers → KDS (replay, fan-out) → Firehose (delivery to S3) → Athena/Glue/Redshift.

## B. Core ideas
- Record = one blob of data your producer sends. Max **1,000 KiB** before base64 encoding.
- Firehose does not look inside a record unless you turn on a feature that parses it (decompression, Lambda, format conversion, dynamic partitioning, Iceberg routing).
- Buffer = Firehose collects records in memory until a size hint or a time hint is reached, whichever comes first, then delivers one batch.
- Buffering hints are **hints**: Firehose may deliver earlier or later when it judges that better (for example it raises the buffer size when delivery falls behind).
- Stream version: starts at 1 and goes up by 1 on every configuration change. It appears in S3 object names.
- You can change destination settings any time with the console or `UpdateDestination`. The stream stays `ACTIVE` and keeps taking data; changes apply within a few minutes.
- Some choices are fixed at creation: the source type, the MSK topic, and turning on dynamic partitioning.

## C. Sources: Direct PUT
- Direct PUT = producers call the Firehose API themselves: `PutRecord` (one record) or `PutRecordBatch` (many).
- `PutRecordBatch` limit: **500 records or 4 MiB per call**, whichever is smaller. This is a hard limit.
- `PutRecordBatch` can partly fail. Always check `FailedPutCount` in the response and retry only the failed entries.
- Retry throttling with exponential backoff and jitter. Throttled calls return `ServiceUnavailableException` **(verify exception name)**.
- Default Direct PUT quota per stream in US East (N. Virginia), US West (Oregon), Europe (Ireland): **500,000 records/s, 2,000 requests/s, 5 MiB/s**.
- Default in other Regions: **100,000 records/s, 1,000 requests/s, 1 MiB/s**.
- The three numbers scale together. Raising throughput to 10 MiB/s in a big Region also raises requests to 4,000/s and records to 1,000,000/s.
- Firehose auto-increases a Direct PUT stream's limit when it sees throttling, but it can take time. Keep retrying; request an increase ahead of known bursts.
- Catch: a limit far above real traffic makes Firehose send many small batches, which costs more at the destination. Raise only to match traffic.
- Direct PUT keeps data up to **24 hours** if the destination is down. After 24 hours of failed delivery, data is lost.
- Many AWS services write to Firehose as Direct PUT: CloudWatch Logs subscription filters, EventBridge (CloudWatch Events) rules, AWS IoT rules, CloudWatch Metric Streams, SNS, SES, Pinpoint, Lambda code, and vended logs.
- Vended log sources include AWS WAF web ACL logs, VPC Flow Logs, Route 53 Resolver query logs, API Gateway access logs, Network Firewall logs, MSK broker logs, ElastiCache (Redis OSS) slow logs.
- WAF logging needs the Firehose stream name to start with `aws-waf-logs-`.
- Agents and tools: Kinesis Agent (Linux), Kinesis Tap (Windows), Fluent Bit, Fluentd, Apache NiFi.
- CloudWatch Logs, EventBridge and IoT can only send to a Firehose stream in the **same Region**. If the stream is not offered as a target, check the Region.

## D. Sources: Kinesis Data Streams (KDS)
- Firehose can read an existing KDS stream. One Firehose stream reads one KDS stream; several Firehose streams can read the same KDS stream.
- With a KDS source, Firehose `PutRecord`/`PutRecordBatch` are disabled. Producers write to KDS with `PutRecord`/`PutRecords`.
- Firehose starts reading at the **LATEST** position. Data already in the KDS stream when you create the Firehose stream is not delivered.
- Firehose calls `GetRecords` once per second per shard (twice per second when full S3 backup is on).
- These reads count against the shard's shared read limit (5 calls/s, 2 MB/s) with every other polling consumer. Too many readers → throttling.
- With a KDS source, the Direct PUT throughput quota does not apply. Firehose scales with the shards.
- Firehose de-aggregates KPL-aggregated records before delivery and before calling Lambda.
- If the destination is down, data is kept per the **KDS retention** (24 h up to 365 days), not 24 hours. Firehose retries `GetRecords` and related calls indefinitely.
- Add `kinesis:ListShards` to the source role; without it you can see `ThrottledDescribeStream`.
- KDS server-side encryption is handled by KDS: KDS decrypts on read, Firehose buffers in memory and delivers. You cannot turn on Firehose SSE for a KDS-source stream.
- Buffer hints apply **per shard** for KDS sources. Many shards with low traffic each → many small S3 files.
- Large KDS records (above 1 MiB, up to 10 MiB) can go to S3 but not to HTTP, Snowflake or Redshift destinations, or with dynamic partitioning **(verify)**.
- Cross-account KDS source (stream in another account) needs a KDS resource policy plus role permissions **(verify)**.

## E. Sources: Amazon MSK
- Source can be MSK provisioned or MSK Serverless. Firehose reads one Kafka topic. The topic **cannot be changed** after creation.
- Private bootstrap brokers (recommended): cluster must be active, use IAM access control, have multi-VPC private connectivity on for IAM, and a cluster policy that lets the Firehose service principal call `CreateVpcConnection`.
- Public bootstrap brokers (provisioned only): cluster active, IAM access control, public access on.
- MSK source needs a separate source role that Firehose assumes to read the topic.
- Start position: by default the time the stream became `ACTIVE`. Set `ReadFromTimestamp` to a past time; set it to epoch (1970-01-01T00:00:00Z) for "earliest".
- Firehose automatically decompresses Kafka messages.
- Default read throughput: **10 MB/s per partition**. `DataReadFromSource.Backpressured` = 1 means that limit is hit or delivery is slow.
- Max record: **10 MB** without Lambda, **6 MB** with Lambda. Bigger records go to the S3 error bucket.
- Lambda output field for MSK is `kafkaRecordValue`, not `data`.
- S3 backup settings (source record backup) are supported only for Direct PUT and KDS sources, not MSK.
- MSK Serverless cannot be the source for Apache Iceberg Tables destinations.
- If the topic is deleted and re-created, delete and re-create the Firehose stream too.
- Stream shows `SUSPENDED` when the cluster is not active or the topic is gone.
- Set the Kafka topic to `message.timestamp.type=LogAppendTime` so data freshness is measured correctly.
- Cross-account MSK: the cluster account turns on multi-VPC connectivity and adds a cluster policy naming the Firehose account; the Firehose account role gets read access to the topic.
- Database as a source (CDC into Iceberg, public preview from Nov 2024) was **removed in September 2025**. Do not pick it for current designs.

## F. Processing order inside a stream
- Order: KPL (protobuf) de-aggregation → JSON or delimiter de-aggregation → Lambda transform → dynamic partitioning → format conversion → S3 delivery.
- CloudWatch Logs decompression happens before Lambda and partitioning **(verify exact position)**.
- Each step is optional. Plain Direct PUT to S3 with none of them is the cheapest setup.

## G. Destinations
- AWS: Amazon S3, Apache Iceberg Tables (self-managed in S3 or Amazon S3 Tables), Amazon Redshift (provisioned or Serverless), OpenSearch Service, OpenSearch Serverless.
- Third party: Splunk, Splunk Observability Cloud, Snowflake, any custom HTTP endpoint.
- Partner HTTP endpoints: Coralogix, Datadog, Dynatrace, Elastic, Grafana Cloud, Honeycomb, LogicMonitor, Logz.io, MongoDB Atlas, New Relic, Sumo Logic.
- Every destination except S3 itself needs an S3 bucket for backup of failed (or all) data.
- Iceberg destination is not in China, GovCloud, Taipei, Malaysia, New Zealand, or Mexico (Central) Regions.
- Snowflake destination is only in listed Regions (most large commercial Regions).

## H. Buffering hints per destination
| Destination | Size MB (default) | Interval s (default) |
|---|---|---|
| Amazon S3 | 1–128 (5) | 0–900 (300) |
| Apache Iceberg Tables | 1–128 (5) | 0–900 (300) |
| Amazon Redshift | 1–128 (5) | 0–900 (300) |
| OpenSearch Service / Serverless | 1–100 (5) | 0–900 (300) |
| Splunk | 1–5 (5) | 0–60 (60) |
| HTTP endpoint | 1–64 (5) | 0–900 (60) |
| Datadog | 1–4 (4) | 0–900 (60) |
| Coralogix | 1–64 (6) | 0–900 (60) |
| Honeycomb | 1–64 (15) | 0–900 (60) |
| Dynatrace, LogicMonitor, Logz.io, New Relic | 1–64 (5) | 0–900 (60) |
| MongoDB | 1–16 (5) | 0–900 (60) |
| Sumo Logic, Splunk Observability Cloud | 1–64 (1) | 0–900 (60) |
| Elastic | 1 | 0–900 (60) |
| Snowflake | 1–128 (1; API says 128) **(verify)** | 0–900 (0) |
| S3 backup bucket | 1–128 | 60–900 |
- Delivery happens when the first of the two hints is met.
- If you set one hint in the API, you must set the other.
- Zero buffering = interval 0. Firehose delivers within a few seconds. Good for low-latency use cases.
- Zero buffering is not available for the S3 backup bucket or with dynamic partitioning.
- S3 with an interval under 60 s uses multipart upload → more S3 PUT requests → higher S3 cost.
- Quotas page still says intervals are 60–900 s; the destination table above (0–900) is the newer behavior **(verify which applies to your Region)**.
- Buffer hints apply per shard (KDS) or per partition (MSK). Dynamic partitioning hints apply at stream or topic level.
- With format conversion on, the S3 buffer size minimum is **64 MiB** and default becomes **128 MiB**.
- Bigger buffers → fewer, larger files, fewer S3 requests, better Athena speed, higher latency.
- Smaller buffers → lower latency, more small files, more PUT requests, more compaction work later.
- For HTTP destinations, HTTP 413 (payload too large) → lower the buffer size.

## I. Amazon S3 destination
- Firehose concatenates the buffered records into one S3 object per delivery.
- By default there is **no delimiter** between records. Turn on the newline delimiter (or add `\n` in the producer) so Athena and Glue can read one record per line.
- Object key = `<evaluated prefix><suffix>`.
- Suffix = `<stream name>-<stream version>-<yyyy>-<MM>-<dd>-<HH>-<mm>-<ss>-<uuid><file extension>`. Only the file extension part can be changed.
- Default prefix = `YYYY/MM/dd/HH/` in UTC, based on arrival time.
- Custom prefix expressions use `!{namespace:value}`. Namespaces: `timestamp`, `firehose`, `partitionKeyFromQuery`, `partitionKeyFromLambda`.
- `!{timestamp:yyyy}` uses Java DateTimeFormatter patterns. Text in single quotes is literal.
- The timestamp is the **approximate arrival time of the oldest record** in the object, not an event time inside the data.
- If your prefix has no timestamp expression, Firehose appends `!{timestamp:yyyy/MM/dd/HH/}` to it.
- `!{firehose:random-string}` = 11 random characters; put it early in the prefix to spread very high request rates.
- `!{firehose:error-output-type}` is allowed only in `ErrorOutputPrefix`. It becomes `processing-failed`, `AmazonOpenSearchService-failed`, `splunk-failed`, `format-conversion-failed`, `http-endpoint-failed`, and so on.
- If `Prefix` has expressions, `ErrorOutputPrefix` is required and must contain `!{firehose:error-output-type}`.
- `Prefix` and `ErrorOutputPrefix` must each be 512 characters or less after evaluation.
- Time zone: UTC by default; set `CustomTimeZone` (for example `Asia/Tokyo`) for prefixes and suffix.
- Compression: `UNCOMPRESSED` (default), `GZIP`, `ZIP`, `Snappy`, `HADOOP_SNAPPY`. Files get `.gz`, `.zip`, `.snappy`, `.hsnappy`.
- Catch: Athena reads GZIP and Hadoop-Snappy well; plain framed Snappy and ZIP are not good for Athena **(verify)**.
- Encryption: use the bucket default, or SSE-KMS with `aws/s3` or a customer managed key.
- If the bucket belongs to another account, the role needs `s3:PutObjectAcl`; Firehose sets `bucket-owner-full-control`.
- S3 delivery failures (missing bucket, access denied, KMS problems) are retried: up to 24 h for Direct PUT, up to the stream retention for KDS/MSK sources.
- S3 destination writes to the error prefix only for processing failures (Lambda, format conversion, partitioning, decompression). Plain S3 write failures just keep retrying.

## J. Amazon Redshift destination
- Firehose writes batches to an intermediate S3 bucket, then runs `COPY` into your table.
- Works with provisioned clusters and Redshift Serverless workgroups.
- Settings: cluster or workgroup, database, table, optional column list, COPY options, user/password or Secrets Manager secret.
- The Redshift user needs `INSERT` on the table.
- COPY options examples: `GZIP` if S3 compression is on, `REGION` if the bucket is in another Region, `JSON 'auto'` for JSON data.
- Only GZIP compression is allowed for the intermediate bucket. Snappy, ZIP and Hadoop-Snappy are blocked because COPY cannot read them.
- Prefix must not contain expressions and `ErrorOutputPrefix` must be empty for Redshift.
- Firehose does not delete the intermediate S3 files. Add an S3 Lifecycle rule to expire them.
- Retry duration 0–7,200 s (default 3,600 s). Firehose retries the COPY every 5 minutes.
- After retries run out, Firehose skips that batch and writes a **manifest file** to the `errors/` prefix. Use it to backfill with a manual `COPY ... MANIFEST`.
- Network: the cluster or workgroup must be **publicly accessible** and allow the Firehose CIDR block for the Region (for example US East (N. Virginia) `52.70.63.192/27`).
- Firehose cannot write to clusters that use **enhanced VPC routing**.
- Private-only Redshift? Use Redshift streaming ingestion from KDS/MSK, or land in S3 and load with COPY/auto-copy instead.
- Check `STL_CONNECTION_LOG` (did Firehose connect?) and `STL_LOAD_ERRORS` (why did COPY fail?).

## K. OpenSearch Service and OpenSearch Serverless
- Firehose sends bulk index requests. Records must be UTF-8, single-line JSON objects.
- Index rotation options: `NoRotation`, `OneHour`, `OneDay`, `OneWeek`, `OneMonth`. Firehose adds the UTC arrival timestamp to the index name (for example `myindex-2016-02-25`).
- Why rotate: old indexes are easy to delete and searches touch less data.
- Document ID: Firehose-generated (default) or OpenSearch-generated (recommended for write-heavy logs, uses less domain CPU).
- Retry duration 0–7,200 s, default 300 s, exponential backoff. AWS Support can raise it above 7,200 s.
- After retries, failed documents go to S3 under `AmazonOpenSearchService-failed/`; you redrive them yourself.
- Backup mode: `FailedDocumentsOnly` or `AllDocuments`.
- VPC domains: give subnets and security groups. Firehose creates ENIs in your subnets; keep free IP addresses or delivery degrades.
- Security group must allow HTTPS (443) from the Firehose ENIs to the domain.
- The role needs EC2 network interface permissions (`ec2:CreateNetworkInterface`, `ec2:DeleteNetworkInterface`, describe calls). Do not remove them after creation.
- OpenSearch Serverless also needs a data access policy that lets the Firehose role write to the collection.
- CloudWatch Logs subscription data cannot go through Firehose to OpenSearch (many log events in one record). Use a CloudWatch Logs subscription to OpenSearch instead.
- Cross-account OpenSearch: domain policy in the other account + `ClusterEndpoint` instead of `DomainARN`, set up with CLI/API only, not the console.

## L. Splunk destination
- Firehose posts to the Splunk HTTP Event Collector (HEC). It uses the HEC token, not IAM.
- Endpoint type: `Raw` (most cases) or `Event` (when Lambda already formatted events, for example to route to indexes).
- HEC acknowledgment timeout: 180–600 s. No ack in time = failure → retry or back up.
- After an ack timeout the data may still have been indexed → **duplicates** are possible on retry.
- Retry duration 0–7,200 s. The retry clock does not count time spent waiting for acks.
- Backup mode: `FailedEventsOnly` (default) or `AllEvents`. You can change Failed → All but not back.
- Failed events go to S3 with `splunk-failed`; redrive per Splunk docs.
- Load balancer in front of Splunk must be a Classic or Application Load Balancer with sticky sessions (needed for acks).
- Firehose sends bytes as-is. Add your own newline or delimiters and configure Splunk to parse them.
- CloudWatch Logs to Splunk: turn on decompression **and** message extraction.

## M. HTTP endpoint and partner destinations
- URL must be HTTPS on **port 443**. Firehose does not follow redirects.
- Firehose sends JSON: `requestId`, `timestamp`, and a `records` array of base64 `data` (up to 10,000 records per request).
- Request body up to **64 MiB** before compression. Optional GZIP content encoding.
- Headers include `X-Amz-Firehose-Request-Id` (same across retries, use it to de-duplicate), `X-Amz-Firehose-Access-Key`, `X-Amz-Firehose-Common-Attributes`.
- The endpoint has **3 minutes** to answer.
- Only HTTP 200 with a JSON body echoing `requestId` and a numeric `timestamp` counts as success. Content type must be `application/json`, body ≤ 1 MiB, not compressed.
- A 200 with a bad body is still a failure (`HttpEndpoint.InvalidResponseFromDestination`).
- HTTP 413 is a **permanent failure** and that batch is not sent to the error bucket. Fix by lowering the buffer size.
- Other errors retry with exponential backoff (start 1 s, ×2, cap 2 minutes, ±15% jitter) until the retry duration (0–7,200 s) ends, then go to S3.
- 401/403 = wrong key; 429 = endpoint overloaded (raise buffering to send fewer, larger requests); 5xx = endpoint problem.
- Delivery can cross accounts, Regions, and even reach on-premises servers; extra data transfer charges apply.
- Firehose cannot deliver to an HTTP endpoint inside a VPC (private endpoint). It must be public.
- There is no Firehose-only IP range for HTTP/Snowflake public endpoints; allowlist all AWS IP ranges for all Regions.
- Backup mode: `FailedDataOnly` or `AllData`.

## N. Snowflake destination
- Uses **Snowpipe Streaming** APIs. Rows are committed about every second.
- Auth: Snowflake user + key pair (PKCS8 private key without header/footer or line breaks, optional passphrase), or a Secrets Manager secret.
- Role: default user role or a custom Snowflake role.
- Connectivity: public, or private through AWS PrivateLink (VPCE ID); use an `AwsVpceIds` network rule, not an IP policy.
- Target: database, schema, table.
- Loading options: JSON keys as column names (`JSON_MAPPING`), raw record into a VARIANT content column, or VARIANT content plus a metadata column.
- One JSON object per record. JSON arrays and badly escaped JSON fail.
- Retry duration 0–7,200 s, **default 60 s**, only for Snowflake service or network issues.
- Non-retriable errors (extra columns, missing non-null columns, wrong types, bad role or table) go straight to S3 `snowflake-failed/`.
- Snowflake column names are case-sensitive; mismatched case → `Snowflake.ExtraColumns`.

## O. Backup and failure handling summary
| Destination | Retry setting | What happens after retries | S3 location |
|---|---|---|---|
| S3 | none (keeps retrying) | retries until 24 h (Direct PUT) or source retention; then data lost | error prefix only for processing failures |
| Redshift | 0–7,200 s (default 3,600), every 5 min | batch skipped, manifest written | `errors/` manifest |
| OpenSearch | 0–7,200 s (default 300) | documents backed up | `AmazonOpenSearchService-failed/` |
| Splunk | 0–7,200 s + ack timeout 180–600 s | events backed up | `splunk-failed` |
| HTTP / partners | 0–7,200 s | batch backed up (not for 413) | `http-endpoint-failed` |
| Snowflake | 0–7,200 s (default 60) | records backed up | `snowflake-failed/` |
| Iceberg | 0–7,200 s (default 300) | records or file keys backed up | configured error prefix |
- If Firehose cannot deliver to the destination **and** cannot write to the backup bucket, the stream stops moving (back-pressure) until one works. With Direct PUT the 24-hour clock still runs.
- S3 backup for S3/Redshift destinations = "source record backup" (on/off). For other destinations = failed-only or all data.
- Source record backup cannot be turned off once on.
- Backup settings apply to Direct PUT and KDS sources only.

## P. Delivery semantics
- Firehose is **at-least-once**. Timeouts plus retries can create duplicates.
- AWS states duplicates do not apply to S3, Apache Iceberg Tables, and Snowflake destinations. Other destinations (Redshift, OpenSearch, Splunk, HTTP) can see duplicates.
- Design for duplicates: idempotent IDs, OpenSearch document IDs, Redshift MERGE/dedup jobs, HTTP request ID checks.
- Ordering is not guaranteed across records; do not rely on file order for event order. Iceberg docs say records are not kept in order.
- On partial S3 failures, Firehose retries and updates the same S3 object with the successful records.

## Q. Pause, resume and changes
- No pause button. To pause: deny `s3:PutObject` on the backup bucket and stop or block the destination. Firehose then holds data.
- Before pausing, make sure the source keeps data long enough (Direct PUT: 24 h; KDS/MSK: their retention).
- To resume: restore destination access, then remove the deny on the backup bucket. A few records may land in the error bucket after resume.

## R. Troubleshooting: delivery
| Symptom | Cause | Fix |
|---|---|---|
| Nothing in S3, `IncomingRecords` = 0 | producers not sending, wrong Region, KDS source not read | check producer errors; check `DataReadFromKinesisStream.*` |
| Records in S3 run together on one line | no delimiter | turn on newline delimiter or add `\n` in producer |
| Thousands of tiny S3 files | small buffer, many shards, zero buffering, dynamic partitions | raise buffer hints; fewer partitions; compact later |
| `ThrottledRecords` > 0 (Direct PUT) | over per-stream quota | retry with backoff; batch; request increase; use KDS source |
| Partial `PutRecordBatch` loss | `FailedPutCount` ignored | retry failed entries |
| Redshift table empty, S3 has data | cluster not public, CIDR blocked, wrong COPY options, enhanced VPC routing | open access; fix COPY; check `STL_LOAD_ERRORS` |
| Redshift COPY fails on compressed files | Snappy/ZIP or missing `GZIP` option | GZIP only; add `GZIP` to COPY options |
| OpenSearch delivery degraded | no free IPs in subnets, SG blocks 443, ENI permissions removed | free IPs; fix SG; restore EC2 permissions |
| Duplicate events in Splunk | ack timeout then retry | longer ack timeout; dedupe in Splunk |
| HTTP 413 errors | batch too big for endpoint | lower buffer size |
| HTTP 200 still counted as failure | response missing `requestId`/`timestamp` or wrong content type | fix endpoint response format |
| Snowflake `ExtraColumns` | JSON key not in table or wrong case | match column names exactly |
| CloudWatch Logs not offered as source in console | Firehose stream in another Region | create the stream in the same Region |
| Data lost after outage | Direct PUT kept only 24 h | KDS source with longer retention; alarm on freshness |
| MSK stream `SUSPENDED` | cluster not active or topic deleted | fix cluster; re-create stream if topic re-created |

## Scenarios: "If X → Y, because Z"
- If app logs must land in S3 every few minutes with no code → Firehose Direct PUT to S3, because it buffers, batches and writes files for you.
- If the same events need S3 and OpenSearch → two Firehose streams reading one KDS stream, because one Firehose stream has one destination.
- If consumers must replay last week's events → KDS (or MSK) in front of Firehose, because Firehose keeps nothing after delivery.
- If S3 delivery must survive a 2-day destination outage → use a KDS source with 3+ days retention, because Direct PUT keeps data only 24 hours.
- If a dashboard needs data in under 10 seconds → zero buffering (interval 0) to OpenSearch or HTTP, because the default 300 s buffer adds minutes.
- If Athena queries need `year=/month=/day=` folders by arrival time → custom prefix with `!{timestamp:...}` in Hive style, because the default `YYYY/MM/dd/HH` is not Hive-style.
- If partitions must use event time from inside the record → dynamic partitioning or Lambda keys, because `timestamp` namespace uses arrival time.
- If a prefix uses expressions and creation fails → add an `ErrorOutputPrefix` with `!{firehose:error-output-type}`, because it is required then.
- If a Redshift cluster is private with enhanced VPC routing → do not use Firehose to Redshift; use Redshift streaming ingestion or S3 + COPY, because Firehose needs a public cluster without enhanced VPC routing.
- If Redshift loads fail for 2 hours → find manifests in `errors/` and run a manual COPY, because Firehose skips batches after the retry duration.
- If intermediate S3 storage for Redshift keeps growing → add a lifecycle rule, because Firehose never deletes those files.
- If an OpenSearch domain is in a private VPC → configure VPC delivery with subnets and SGs, because Firehose creates ENIs there.
- If CloudWatch Logs must reach OpenSearch → use a CloudWatch Logs subscription to OpenSearch, because Firehose cannot send CloudWatch Logs records to OpenSearch.
- If Splunk sees duplicates after slow acks → expect at-least-once and raise the HEC ack timeout, because data may be indexed even when the ack times out.
- If a custom HTTP endpoint returns 413 → lower the buffer size, because 413 is permanent and not backed up.
- If an HTTP endpoint must not process the same batch twice → de-duplicate on `X-Amz-Firehose-Request-Id`, because it stays the same across retries.
- If events must stream into Snowflake tables in seconds → Firehose to Snowflake (Snowpipe Streaming), because it commits about every second without staging files.
- If Snowflake rejects rows for an extra field → fix the table or JSON keys; no retry happens, because schema errors are non-retriable and go to `snowflake-failed/`.
- If an MSK topic must be landed in S3 from the beginning → set `ReadFromTimestamp` to epoch, because the default starts when the stream becomes active.
- If a KDS stream with 3 other polling apps throttles after adding Firehose → add shards or move other apps to EFO, because Firehose shares the 5 reads/s per shard.
- If exam asks "least operational overhead to load streaming data into S3/Redshift/OpenSearch" → Firehose, because it is fully managed with no consumers to run.

Verified from AWS docs on 2026-11-02 (Amazon Data Firehose Developer Guide PDF: concepts, sources, MSK and KDS source settings, destination settings, backup settings, buffering hints table, data delivery, delivery failures, S3 object names and custom prefixes, OpenSearch index rotation, pause/resume, HTTP request/response spec, quotas, document history; API Reference: Splunk, HTTP endpoint, Redshift, OpenSearch, Snowflake, ExtendedS3, MSKSourceConfiguration).
Unconfirmed (verify): `ServiceUnavailableException` as the throttling exception; KDS large records (1–10 MiB) support through Firehose; cross-account KDS source setup; exact position of CloudWatch Logs decompression in the processing order; which interval range (0–900 or 60–900) the quotas page means; Snowflake default buffer size (1 MB vs 128 MB); Athena support for framed Snappy/ZIP output.

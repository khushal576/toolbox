# Amazon Data Firehose – 3. Security, cost, monitoring, limits, comparisons and scenarios

Short notes. Each point is a fact you can be asked about.

## A. IAM: who can send and manage
- All Firehose API access is through IAM. There are no stream users or passwords.
- Producer actions: `firehose:PutRecord`, `firehose:PutRecordBatch`, scoped to the stream ARN (`arn:aws:firehose:<region>:<account>:deliverystream/<name>`).
- Admin actions: `CreateDeliveryStream`, `UpdateDestination`, `DeleteDeliveryStream`, `StartDeliveryStreamEncryption`, `StopDeliveryStreamEncryption`, tagging calls.
- Producers on EC2, Lambda or containers should use IAM roles, never stored access keys.
- Tags in `CreateDeliveryStream` need `firehose:TagDeliveryStream` too, or creation fails with `AccessDeniedException`.
- ABAC: `aws:RequestTag` on create, `aws:TagKeys` on tag/untag, `firehose:ResourceTag` on other operations. `ListDeliveryStreams` cannot use tag conditions.
- AWS managed policies exist (for example `AmazonDataFirehoseReadOnlyAccess`, full access); too broad for production apps **(verify exact names)**.

## B. IAM: the Firehose service role
- Every Firehose stream needs an **IAM role** that Firehose assumes (trust policy principal `firehose.amazonaws.com`).
- The role grants what Firehose does for you: read KDS, write S3, invoke Lambda, read Glue tables, use KMS keys, write CloudWatch Logs, call OpenSearch, get Secrets Manager secrets.
- KDS source permissions: `kinesis:DescribeStream`, `GetShardIterator`, `GetRecords`, `ListShards`.
- MSK source uses a **separate source role** with read access to the cluster and topic.
- S3 permissions: `s3:PutObject`, `GetObject`, `ListBucket`, `GetBucketLocation`, `AbortMultipartUpload`, `ListBucketMultipartUploads`.
- Lambda permissions: `lambda:InvokeFunction`, `lambda:GetFunctionConfiguration`.
- Format conversion permissions: Glue table read (`glue:GetTable`, `GetTableVersion(s)`) in the same account as the stream.
- Iceberg permissions: Glue catalog read/update on the tables plus S3 read/write; S3 Tables need S3 Tables permissions (IAM mode) or Lake Formation grants (Lake Formation mode).
- Error logging needs `logs:PutLogEvents` on the log group and stream.
- VPC delivery (OpenSearch in VPC) needs EC2 ENI permissions: `ec2:CreateNetworkInterface`, `CreateNetworkInterfacePermission`, `DeleteNetworkInterface`, and describe calls.
- Splunk, Snowflake and HTTP/partner destinations do not use IAM; they use tokens, keys or key pairs.
- Console can create and manage the role. It manages any role whose ARN contains `service-role`; pick a role without that string if you do not want the console to edit it.
- Do not share one console-managed role across many streams; it grows too broad.
- If you change source or destination, update a self-made role yourself.

## C. Encryption at rest
- Firehose encrypts data it holds in interim storage with KMS and checks integrity with checksums.
- **Direct PUT** (and services that write as Direct PUT: IoT, CloudWatch Logs, EventBridge): turn on SSE with `StartDeliveryStreamEncryption` or at create time.
- Turn it off with `StopDeliveryStreamEncryption`.
- Key types: `AWS_OWNED_CMK` (default, AWS-owned key) or `CUSTOMER_MANAGED_CMK` (your key ARN).
- Only **symmetric** KMS keys are supported.
- With a customer managed key, Firehose creates a **KMS grant** (needs `kms:CreateGrant` at create/start).
- Callers of `PutRecord`/`PutRecordBatch` and the key policy must allow `kms:GenerateDataKey` and `kms:Decrypt` for a customer managed key.
- Changing the key with `StartDeliveryStreamEncryption` retires the grant on the old key.
- One customer managed key can encrypt up to **500 Firehose streams**; above that → `LimitExceededException`.
- If the key becomes unusable (`KMSNotFound`, `InvalidState`, `Disabled`, `AccessDenied`), Firehose waits up to **24 hours**, then **discards** records it cannot decrypt.
- Alarm on `KMSKeyAccessDenied`, `KMSKeyDisabled`, `KMSKeyInvalidState`, `KMSKeyNotFound` metrics.
- **KDS source**: you cannot use Firehose SSE. Encrypt the KDS stream instead; KDS decrypts on read and Firehose delivers without storing plaintext at rest.
- Firehose key use is visible in CloudTrail (KMS events with a Firehose encryption context).
- Destination encryption is separate: S3 SSE-KMS with `aws/s3` or your key, or the bucket default.
- S3 Tables destination: configure KMS on the table bucket, not in Firehose.
- OpenSearch, Redshift, Splunk, Snowflake encryption at rest is configured in those services.

## D. Encryption in transit and network
- All Firehose API calls and deliveries use **TLS** (TLS 1.2 required, 1.3 recommended). FIPS endpoints exist.
- S3, Redshift, OpenSearch, Splunk, HTTP and Snowflake deliveries are HTTPS.
- **Interface VPC endpoint** (AWS PrivateLink, service `com.amazonaws.<region>.kinesis-firehose`) lets producers in private subnets call Firehose with no internet gateway or NAT.
- No gateway endpoint exists for Firehose (gateway endpoints are only S3 and DynamoDB).
- Endpoint policies limit which streams and actions are reachable through the endpoint.
- Use `aws:SourceVpce` in a Deny to force producers through one endpoint.
- **VPC delivery** (destination in your VPC): Firehose puts ENIs in your subnets to reach OpenSearch Service/Serverless; billed per GB and per AZ-hour.
- Keep free IPs in those subnets and allow HTTPS (443) in security groups.
- Redshift and Splunk in a VPC must be **publicly reachable** and allow the Firehose CIDR block for the Region.
- Firehose CIDRs are per Region (for example `52.70.63.192/27` for Redshift in us-east-1); Splunk uses its own list.
- Snowflake private delivery uses PrivateLink VPCE IDs; Snowflake network rules allow those `AwsVpceIds`.
- HTTP endpoints and public Snowflake: no Firehose-only IP range; allowlist all AWS IP ranges.
- Private HTTP endpoints in a VPC are **not supported**.
- MSK private connectivity uses multi-VPC private connectivity (PrivateLink) created by Firehose.

## E. Secrets Manager
- Destinations with credentials (Redshift, Splunk, Snowflake, HTTP endpoint, Coralogix, Datadog, Dynatrace, Elastic, Honeycomb, LogicMonitor, Logz.io, MongoDB, New Relic) can read them from **AWS Secrets Manager**.
- Why: no plaintext secrets in console or API, and rotation without changing the stream.
- Each destination expects a specific JSON format in the secret (for HTTP: `{"api_key": "..."}`).
- Firehose caches the secret encrypted and refreshes every **10 minutes**.
- Role needs `secretsmanager:GetSecretValue`; plus `kms:Decrypt` if the secret uses a customer managed key.
- A secret in another account must use a customer managed key; secrets with `aws/secretsmanager` cannot be shared cross-account.
- No Firehose charge for this; Secrets Manager charges apply.

## F. Cross-account patterns
- **S3 in another account**: role in the Firehose account + bucket policy in the bucket account + `s3:PutObjectAcl` (Firehose sets `bucket-owner-full-control`). CLI/API setup.
- **OpenSearch in another account**: domain access policy allowing the Firehose role + `ClusterEndpoint` in the config. CLI/API only, not console.
- **MSK in another account**: cluster policy naming the Firehose account and service principal, multi-VPC connectivity on.
- **HTTP endpoint** can be in another account, Region, or on premises (data transfer charges apply).
- **Glue catalog for Iceberg** can be cross-account and cross-Region.
- Format conversion Glue role must be in the same account (no cross-account role).
- Central logging pattern: CloudWatch Logs subscription → (cross-account log destination) → Firehose in the log account → S3 **(verify setup)**.

## G. Audit, compliance and resilience
- CloudTrail logs Firehose control-plane calls as management events: `CreateDeliveryStream`, `DeleteDeliveryStream`, `DescribeDeliveryStream`, `ListDeliveryStreams`, `ListTagsForDeliveryStream`, `TagDeliveryStream`, `UntagDeliveryStream`, `StartDeliveryStreamEncryption`, `StopDeliveryStreamEncryption`, `UpdateDestination`.
- `PutRecord`/`PutRecordBatch` are not in that list; data-event logging for them **(verify)**.
- CloudTrail shows who, when, from which IP and with which parameters. Record payloads are never logged.
- In scope for SOC, PCI, FedRAMP, HIPAA and other programs (reports in AWS Artifact).
- AWS Config tracks stream configuration changes **(verify resource type support)**.
- Firehose is Regional and serverless; AWS moves streams across hosts and AZs without data loss.
- A Region outage stops the stream. For multi-Region, run streams in each Region or replicate the destination (for example S3 replication).
- Govern the landed data (Lake Formation, Macie for PII, S3 Block Public Access); Firehose itself has no data catalog or masking.

## H. Monitoring: CloudWatch metrics
- Namespace `AWS/Firehose`, dimension `DeliveryStreamName`. Metrics every minute, **free**.
- Short bursts under a minute may not show clearly in 1-minute metrics.
- Ingest (Direct PUT): `IncomingBytes`, `IncomingRecords`, `IncomingPutRequests`, `ThrottledRecords`, `BytesPerSecondLimit`, `RecordsPerSecondLimit`, `PutRequestsPerSecondLimit`.
- Throttled data is not counted in `IncomingBytes`/`IncomingRecords`.
- API metrics: `PutRecord.Bytes/Latency/Requests`, `PutRecordBatch.Bytes/Latency/Records/Requests`.
- KDS source: `DataReadFromKinesisStream.Bytes/Records`, `KinesisMillisBehindLatest`, `ThrottledGetRecords`, `ThrottledGetShardIterator`, `ThrottledDescribeStream`.
- MSK source: `DataReadFromSource.Records/Bytes`, `KafkaOffsetLag`, `SourceThrottled.Delay`, `BytesPerSecondLimit` (per partition), `FailedValidation.Records/Bytes`, `DataReadFromSource.Backpressured`.
- Delivery: `DeliveryTo<Dest>.Bytes`, `.Records`, `.Success`, `.DataFreshness` for S3, Redshift, AmazonOpenSearchService, AmazonOpenSearchServerless, Splunk, HttpEndpoint, Snowflake, Iceberg.
- **DataFreshness** = age of the oldest record not yet delivered. The key health metric: rising = delivery falling behind.
- If freshness is not emitted at all, delivery is fully blocked or there is no data.
- `DeliveryToS3.Success` = successful S3 PUTs; for Redshift also watch `DeliveryToRedshift.Success` (successful COPYs).
- Small dips in `.Success` averages are not data loss; Firehose retries until delivered or backed up.
- Backup: `BackupToS3.Bytes`, `.Records`, `.Success`, `.DataFreshness` (when backup is on).
- OpenSearch: `DeliveryToAmazonOpenSearchService.AuthFailure` and `.DeliveryRejected` (1 = problem).
- Splunk: `DeliveryToSplunk.DataAckLatency`. Snowflake: `DeliveryToSnowflake.DataCommitLatency`.
- HTTP: `DeliveryToHttpEndpoint.Success` per attempt (use Minimum to catch failures), `ProcessedBytes/Records` include retries.
- Lambda: `ExecuteProcessing.Duration`, `ExecuteProcessing.Success`, `SucceedProcessing.Records/Bytes`.
- Format conversion: `SucceedConversion.*`, `FailedConversion.*`.
- Dynamic partitioning: `PartitionCount`, `PartitionCountExceeded`, `ActivePartitionsLimit`, `PerPartitionThroughput`, `JQProcessing.Duration`, `DeliveryToS3.ObjectCount`.
- Decompression: `OutputDecompressedBytes/Records.Success/Failed`.
- KMS: `KMSKeyAccessDenied`, `KMSKeyDisabled`, `KMSKeyInvalidState`, `KMSKeyNotFound`.
- Usage: `AWS/Usage` `ResourceCount` (stream count vs quota) every 3 minutes.

## I. Alarms AWS recommends
- `DeliveryTo<Dest>.DataFreshness` above the buffering limit (max 15 minutes) for S3, Iceberg, Splunk, OpenSearch, HTTP.
- Metric math: `IncomingBytes` (Sum per 5 min) / 300 approaching `BytesPerSecondLimit`.
- Same for `IncomingRecords` vs `RecordsPerSecondLimit` and `IncomingPutRequests` vs `PutRequestsPerSecondLimit`.
- `ThrottledRecords` > 0.
- Also alarm on destination-specific failures: `FailedConversion.Records`, `PartitionCountExceeded`, `ExecuteProcessing.Success` < 1, KMS metrics.
- With full backup on, watch two freshness metrics (destination and backup).
- Send alarms to SNS; use EventBridge or Lambda for automatic actions.

## J. Error logging (CloudWatch Logs)
- Turn on error logging at creation; AWS strongly recommends it.
- Console creates log group `/aws/kinesisfirehose/<stream-name>` with log streams `DestinationDelivery` and `BackupDelivery`.
- `DestinationDelivery` = errors delivering to the main destination (and intermediate S3 for Redshift).
- `BackupDelivery` = backup errors when backup mode is all data (or `Enabled` for Redshift).
- With `FailedDataOnly` backup, backup errors are logged in `DestinationDelivery`.
- Under high failure rates, Firehose **samples** error logs; not every error is logged.
- Logs only appear when there are errors. Small CloudWatch Logs charges apply.
- Common codes: `S3.AccessDenied`, `S3.NoSuchBucket`, `S3.KMS.NotFoundException`, `S3.KMS.RequestLimitExceeded`, `HttpEndpoint.DestinationException`, `HttpEndpoint.RequestTimeout`, `Splunk.AckTimeout`, `Snowflake.InvalidColumns`, `Iceberg.NoSuchTable`.

## K. Quotas and numbers
| Item | Value |
|---|---|
| Record size | 1,000 KiB before base64 |
| PutRecordBatch | 500 records or 4 MiB per call (hard) |
| Direct PUT per stream (N. Virginia, Oregon, Ireland) | 500,000 records/s, 2,000 requests/s, 5 MiB/s |
| Direct PUT per stream (other Regions) | 100,000 records/s, 1,000 requests/s, 1 MiB/s |
| KDS source throughput | no Firehose limit (scales with shards) |
| Data kept when destination down | 24 h (Direct PUT); KDS/MSK retention otherwise |
| Streams per Region | 5,000 / 2,000 / 500 / 100 by Region tier |
| Control-plane APIs | 5 TPS each (hard) |
| Customer managed key | up to 500 streams per key |
| Buffer size | 1–128 MiB (S3/Redshift/Iceberg), 1–100 (OpenSearch), 1–5 (Splunk), 1–64 (HTTP) |
| Buffer interval | 0–900 s (60–900 s per quotas page) |
| Retry duration | 0–7,200 s (Redshift, OpenSearch, Splunk, HTTP, Snowflake, Iceberg) |
| Lambda payload / time | 6 MB request and response / 5 minutes |
| Lambda buffer | 0.2–3 MB, 0–900 s |
| Lambda concurrency | 5 outstanding per shard (S3, Redshift, OpenSearch), 10 (Splunk) |
| MSK source | 10 MB/s read per partition; 10 MB max record (6 MB with Lambda) |
| Dynamic partitioning | 500 active partitions (up to 2,500 on request); 1 GB/s per partition; 50 keys |
| De-aggregation | 500 sub-records per record |
| Format conversion buffer | ≥ 64 MiB (default 128 MiB) |
| HTTP request | 64 MiB body, 10,000 records, 3 min response, 1 MiB response |
| Iceberg Direct PUT | 5 MiB/s (3 big Regions), 1 MiB/s elsewhere |
| Prefix length | 512 characters after evaluation |
- Streams per Region: 5,000 in N. Virginia, Ohio, Oregon, Ireland, Tokyo; 2,000 in Frankfurt, London, Singapore, Sydney, Seoul, Mumbai and others; 500 or 100 in smaller Regions.
- Over the stream count → `CreateDeliveryStream` returns `LimitExceededException`; raise in Service Quotas.
- Control-plane 5 TPS hard limit covers Create, Delete, Describe, List, UpdateDestination, Tag, Untag, ListTags, Start/Stop encryption.
- Do not use resource limits to control spend; use budgets and alarms.

## L. Pricing (US East, first tier examples)
- No upfront cost, no minimum, no hourly stream fee. Pay per GB ingested plus optional features.
- **Direct PUT and KDS source: $0.029 per GB**, each record **rounded up to 5 KB** (5,120 bytes).
- Ingestion tiers drop with volume (first 500 TB/month, then lower rates) **(verify tier boundaries)**.
- **MSK source: $0.055 per GB**, no 5 KB rounding, billed on the higher of ingested or delivered bytes.
- **Vended logs source: $0.13 per GB**, no rounding.
- **Format conversion: $0.018 per GB** ingested (5 KB increments).
- **Dynamic partitioning: $0.020 per GB** processed + **$0.005 per 1,000 S3 objects** delivered + **$0.07 per JQ processing hour** if JQ is used.
- **VPC delivery: $0.01 per GB** + **$0.01 per AZ-hour** (partial hours bill as full).
- **Iceberg destination: $0.045 per GB**, no rounding; extra bytes added by Lambda billed too.
- **Snowflake destination: $0.071 per GB**, no rounding, higher of ingested or delivered bytes.
- **CloudWatch Logs decompression: $0.00325 per GB** decompressed.
- Example: 100 records/s of 3 KB billed as 5 KB = 1,235.96 GB/month ≈ **$35.84**.
- Example: VPC delivery of 1,235.96 GB across 3 AZs for 30 days ≈ $33.95 ($12.35 data + $21.60 AZ-hours).
- Other costs: S3 requests and storage, Lambda invocations, KMS requests, CloudWatch Logs, Glue catalog requests, destination costs, cross-Region or internet data transfer.
- Delivery to an HTTP endpoint in another Region or outside AWS adds data transfer charges.
- Not in the AWS Free Tier **(verify)**.

## M. Cost levers
- Records under 5 KB waste money: 1,000 records of 1 KB bill as 5 MB. **Batch several events into one record** (newline-separated) before sending.
- Same 5 MiB sent as 1,000 records costs less than as 5,000 records.
- After batching, use multi-record de-aggregation only if you need per-event partitioning.
- Prefer larger buffers: fewer S3 objects, fewer PUT requests, lower dynamic partitioning object fees, less compaction.
- Avoid S3 intervals below 60 s unless needed; multipart uploads add PUT requests.
- Use dynamic partitioning only with low-cardinality keys; each object costs $0.005 per 1,000 plus small-file query penalties.
- Prefer inline JQ only when needed; Lambda keys move cost to Lambda; pick the cheaper one for your volume.
- Turn on format conversion when Athena/Spectrum scans dominate cost; it pays for itself on query savings.
- Compress (GZIP) when not converting, to cut S3 storage and transfer.
- Expire intermediate Redshift files and backup data with S3 Lifecycle.
- Do not raise Direct PUT quotas far above traffic; tiny batches raise destination cost.
- Use `Dropped` in Lambda to filter noise before it reaches paid destinations (ingest is still billed).
- VPC delivery adds AZ-hour fees; pick only needed subnets/AZs.
- Prefer Firehose (pay per GB) over always-on custom consumers when the job is only landing data.

## N. Comparison: Firehose vs nearby options
| | Firehose | KDS | MSK | KDS data delivery | Glue streaming ETL | Lambda consumer | Redshift streaming ingestion |
|---|---|---|---|---|---|---|---|
| Job | managed delivery | stream storage | Kafka cluster | built-in KDS → S3/tables | Spark streaming jobs | custom code per batch | materialized view reads stream |
| Code | none (optional Lambda) | producers + consumers | producers + consumers | none | PySpark/Scala | function code | SQL |
| Replay | no | yes, 24 h–365 days | yes, retention | no | from source | from source | from source |
| Latency | seconds–15 min (buffer) | ~70–200 ms | ms | buffered | seconds (micro-batch) | sub-second–seconds | seconds |
| Transform | Lambda, conversion, partitioning | none | none (use Connect/Flink) | none (original format) | full Spark | anything | SQL in MV |
| Destinations | S3, Iceberg, Redshift, OpenSearch, Splunk, Snowflake, HTTP | consumers read | consumers read | S3, streaming tables | S3, Glue tables, JDBC, more | anywhere code can reach | Redshift only |
| Scaling | automatic | shards or on-demand | brokers or serverless | automatic | DPUs/workers | concurrency | Redshift capacity |
| Billing | per GB | shard-hour or per GB | broker-hour / cluster | per GB add-on | DPU-hour | requests + duration | Redshift compute |
- Firehose vs KDS: KDS stores and lets many apps read with replay; Firehose only delivers. Use both together often.
- Firehose vs MSK: MSK for Kafka APIs and ecosystem; Firehose can read from MSK and land data without Kafka Connect.
- Firehose vs KDS data delivery: KDS delivery keeps the original format with no transform; Firehose adds Lambda, Parquet, dynamic partitioning, more destinations.
- Firehose vs Glue streaming: Glue for joins, complex Spark logic, custom sinks; Firehose for no-code delivery.
- Firehose vs Lambda consumer: Lambda gives full control and low latency but you handle batching, file sizes, retries and S3 writes.
- Firehose vs Redshift streaming ingestion: streaming ingestion is lower latency and works with private clusters; Firehose stages in S3 and needs a public cluster.
- Firehose vs Managed Service for Apache Flink: Flink for stateful, windowed, exactly-once processing.

## O. Troubleshooting: security, cost, operations
| Symptom | Cause | Fix |
|---|---|---|
| `S3.AccessDenied` in logs | role lacks S3 permission, wrong trust, bucket policy deny | fix role, trust `firehose.amazonaws.com`, bucket policy |
| Cross-account bucket owner cannot read objects | missing `s3:PutObjectAcl` | add it; Firehose sets bucket-owner-full-control |
| `S3.KMS.RequestLimitExceeded` | KMS request quota | raise KMS quota; S3 Bucket Keys **(verify)** |
| Data discarded after key change | key disabled/deleted > 24 h | re-enable key; alarm on `KMSKey*` metrics |
| `PutRecord` AccessDenied with SSE | caller lacks `kms:GenerateDataKey`/`Decrypt` | add to IAM and key policy |
| Cannot enable SSE on stream | source is KDS | encrypt the KDS stream instead |
| Create stream with tags fails | no `firehose:TagDeliveryStream` | add permission |
| Producers in private subnet time out | no route to Firehose | interface VPC endpoint |
| OpenSearch VPC delivery stops | ENI permissions removed, no free IPs | restore EC2 permissions, free IPs |
| Redshift connection refused | cluster private or CIDR not allowed | public access + Firehose CIDR |
| Splunk/HTTP auth errors (401/403) | wrong token/key or secret format | fix secret JSON, token enabled |
| Bill higher than data volume suggests | tiny records rounded to 5 KB | batch records ≥ 5 KB |
| Dynamic partitioning bill high | many tiny objects | coarser keys, larger buffers |
| `LimitExceededException` on create | stream count or 500-per-key limit | Service Quotas increase; another key |
| `ThrottlingException` on Describe/List | 5 TPS control-plane limit | cache results, back off |
| Freshness rising, destination healthy | Lambda slow, low buffers, KDS read throttling | tune Lambda, raise buffers, add shards |
| Missing error details | logging off or sampled | enable error logging |

## Scenarios: "If X → Y, because Z"
- **If** **Direct PUT** data must be encrypted at rest with a key the company controls, **then** turn on server-side encryption (SSE) with **`CUSTOMER_MANAGED_CMK`**, using a **symmetric** **AWS Key Management Service (KMS)** key. **This works because** your own key gives you key policy control, and its use shows up in **AWS CloudTrail** with a Firehose encryption context. Firehose creates a **KMS grant** on the key, and callers of `PutRecord`/`PutRecordBatch` need `kms:GenerateDataKey` and `kms:Decrypt`.
- **If** the source is **Amazon Kinesis Data Streams (KDS)** and auditors want encryption at rest, **then** turn on **SSE on the KDS stream** itself. **This works because** Firehose SSE cannot be used with a KDS source: KDS decrypts on read and Firehose delivers without storing plaintext at rest.
- **If** delivered S3 objects must use a specific KMS key, **then** set **SSE-KMS** with that key in the **S3 destination settings**. **This works because** stream SSE (data Firehose holds in the middle) and destination encryption are **separate** settings.
- **If** a KMS key used by the stream was **disabled for two days**, **then** expect records older than **24 hours** to be lost; re-enable the key and alarm on the `KMSKey*` metrics. **This works because** when the key is unusable, Firehose waits up to **24 hours** and then **discards** records it cannot decrypt.
- **If** producers run in private subnets with no NAT gateway, **then** create an **interface VPC endpoint** (AWS PrivateLink) for Firehose. **This works because** it lets producers call Firehose without an internet gateway or NAT, and Firehose has **no gateway endpoint** (those exist only for S3 and DynamoDB).
- **If** only one VPC endpoint may be used to send data, **then** add a **Deny** policy with the **`aws:SourceVpce`** condition. **This works because** an IAM allow on its own does not limit the network path; the Deny forces producers through that one endpoint.
- **If** an **Amazon OpenSearch Service** domain is reachable only inside a **Virtual Private Cloud (VPC)**, **then** use **Firehose VPC delivery** with your subnets and security groups. **This works because** Firehose puts **elastic network interfaces (ENIs)** in your subnets to reach the domain. Keep free IPs and allow **HTTPS (443)**. VPC delivery costs extra: **$0.01 per GB** plus **$0.01 per AZ-hour**.
- **If** a security team will not make **Amazon Redshift** public, **then** use **Redshift streaming ingestion** from KDS or **Amazon MSK** instead of Firehose. **This works because** Firehose to Redshift needs the cluster to be **publicly reachable** and to allow the Firehose CIDR block for the Region, while streaming ingestion works with private clusters.
- **If** **Splunk HTTP Event Collector (HEC)** tokens must rotate without changing the stream, **then** store the token in **AWS Secrets Manager** and point the stream at the secret. **This works because** Firehose caches the secret and refreshes it every **10 minutes**, so a rotated value is picked up by itself. The role needs `secretsmanager:GetSecretValue`.
- **If** the Secrets Manager secret lives in **another account**, **then** encrypt it with a **customer managed KMS key**. **This works because** secrets encrypted with the default `aws/secretsmanager` key cannot be shared across accounts.
- **If** logs from **50 accounts** must land in one S3 bucket, **then** either run Firehose in each account writing cross-account (bucket policy in the bucket account plus `s3:PutObjectAcl` on the role), or use a central CloudWatch Logs destination feeding Firehose in the log account **(verify setup)**. **This works because** cross-account S3 delivery is supported: Firehose sets `bucket-owner-full-control` so the bucket owner can read the objects.
- **If** a stream in account A must index into OpenSearch in account B, **then** add a **domain access policy** allowing the Firehose role and use **`ClusterEndpoint`** (not `DomainARN`), set up with the **CLI or API**. **This works because** cross-account OpenSearch delivery cannot be set up in the console.
- **If** auditors ask who changed a stream's destination, **then** look for **`UpdateDestination`** events in **CloudTrail**. **This works because** CloudTrail logs Firehose control-plane calls as management events, showing who, when, from which IP and with which parameters (never the record payloads).
- **If** you need an early warning that S3 delivery is stuck, **then** alarm on **`DeliveryToS3.DataFreshness`** above your buffering limit. **This works because** DataFreshness is the **age of the oldest record not yet delivered**, so a rising value means delivery is falling behind. If it stops being emitted, delivery is fully blocked or there is no data.
- **If** Direct PUT traffic is getting close to the stream's limit, **then** use **CloudWatch metric math**: `IncomingBytes` (Sum per 5 minutes) ÷ 300, compared with `BytesPerSecondLimit`. **This works because** Firehose publishes its current limits as metrics, so the alarm can fire before throttling starts. Do the same for records and put requests.
- **If** **`ThrottledRecords`** keeps growing on a Direct PUT stream, **then** request a **limit increase** or move to a **KDS source**. **This works because** Direct PUT has a per-stream quota (for example **5 MiB/s** in the big Regions, **1 MiB/s** elsewhere), while a KDS-source stream has no Firehose throughput quota and scales with the shards.
- **If** errors are happening but some are missing from the logs, **then** this is expected under heavy failure. **This works because** at high failure rates Firehose **samples** error logs, so not every error is logged.
- **If** a workload of **1 KB events** costs about **5× more** than expected, **then** batch several events into records of **about 5 KB or more** (newline-separated) before sending. **This works because** Direct PUT and KDS-source ingestion bills each record **rounded up to 5 KB**, so 1,000 records of 1 KB are billed as 5 MB.
- **If** **MSK** is the source and records are tiny, **then** no 5 KB rounding applies. **This works because** MSK-source pricing (**$0.055 per GB**) bills the real bytes, using the higher of ingested or delivered bytes.
- **If** S3 request costs jump after setting a **10-second** buffer interval, **then** raise the interval to **60 seconds or more**. **This works because** S3 intervals under 60 s use **multipart upload**, which means more S3 PUT requests and a higher S3 bill.
- **If** dynamic partitioning by **minute** creates millions of objects, **then** partition by **hour** instead and use longer buffers. **This works because** every S3 object costs **$0.005 per 1,000** delivered, and many small files also slow queries and need compaction later.
- **If** a team needs **replay**, many consumers and **sub-second** reads, **then** use **KDS**, not Firehose. **This works because** Firehose only delivers data (latency of seconds to 15 minutes, no replay), while KDS stores it for 24 hours to 365 days and lets many apps read it.
- **If** Kafka producers already exist and the data must land in S3, **then** use **MSK as the Firehose source**. **This works because** Firehose reads the Kafka topic directly, so you do not need to run Kafka Connect.
- **If** raw KDS data must reach S3 in its original format at the lowest cost, **then** use **KDS data delivery** (the built-in KDS → S3 feature). **This works because** no transform features are needed, and KDS data delivery keeps the original format.
- **If** streaming **joins** and **windowed aggregates** are needed, **then** use **Amazon Managed Service for Apache Flink** or **AWS Glue streaming**. **This works because** Firehose cannot keep state; it only delivers data with simple per-record transforms.
- **If** you need **sub-minute** queries in Redshift on data from KDS, **then** use **Redshift streaming ingestion**. **This works because** Firehose first stages data in S3 and then runs `COPY` after each buffer, which adds delay, while streaming ingestion reads the stream with a materialized view in seconds.
- **If** a **CloudWatch Logs** subscription must produce **Parquet** files partitioned by date, **then** use Firehose with **decompression**, **dynamic partitioning** and **format conversion**. **This works because** all three are built in. Decompression must be on, since subscription data arrives gzip-compressed and partitioning and conversion need plain JSON.
- **If** stream creation fails with **`LimitExceededException`** while one KMS key is used for many streams, **then** use **another key**. **This works because** one customer managed key can encrypt at most **500 Firehose streams**.
- **If** management scripts hit throttling on **`DescribeDeliveryStream`**, **then** back off and cache the results. **This works because** control-plane APIs (create, describe, list, update and others) have a hard limit of **5 transactions per second (TPS)**.
- **If** an exam asks for the most cost-effective, least-ops way to land **IoT data** in S3 as **Parquet**, **then** use an **AWS IoT rule** sending to Firehose with **format conversion** on. **This works because** IoT rules write to Firehose as Direct PUT, and conversion is built in, so no servers or code are needed.

Verified from AWS docs on 2026-11-02 (Firehose Developer Guide PDF: data protection, SSE for Direct PUT and KDS, controlling access, S3/Redshift/OpenSearch/Splunk/Snowflake/HTTP access, cross-account delivery, tags, Secrets Manager, console-managed roles, compliance, resilience, infrastructure security, PrivateLink, CloudWatch alarms and metrics, CloudWatch Logs error logging, CloudTrail, troubleshooting, quotas; API Reference: DeliveryStreamEncryptionConfigurationInput; Firehose pricing page).
Unconfirmed (verify): exact AWS managed policy names; cross-account CloudWatch Logs destination setup; CloudTrail data-event support for PutRecord/PutRecordBatch; AWS Config resource type support; ingestion tier boundaries; Free Tier status; S3 Bucket Keys as fix for KMS throttling.

# Amazon CloudWatch – 3. Logs, Logs Insights, filters, subscriptions and data protection

Short notes. Each point is a fact you can be asked about.

## A. CloudWatch Logs basics
- **Log event**: one record (timestamp + message). Max event size **1 MB** (1,024 KB) per quota page; batch (`PutLogEvents`) max **1 MB** and 10,000 events; events must be within a time window of 24 hours in a batch **(verify)**.
- **Log stream**: sequence of events from one source (for example one Lambda container, one instance).
- **Log group**: collection of streams sharing retention, access, encryption and settings. Up to **1,000,000 log groups** per Region.
- **Retention**: default **never expire**; set per log group from **1 day to 10 years** (or never). Always set retention to control cost.
- **Log classes**: **Standard** (full features) and **Infrequent Access** (about half the ingestion price; limited features: no subscription filters, no metric filters, no export, Logs Insights supported; cannot change class after creation) **(verify)**.
- **Ingestion price**: about **$0.50/GB** standard (IA about **$0.25/GB**); storage about **$0.03/GB-month** (archive); Logs Insights about **$0.005/GB scanned**; **5 GB free** ingestion/storage/scan per month **(verify)**.
- **Encryption**: encrypted at rest by default; optional **KMS customer managed key** per log group (key policy must allow `logs.<region>.amazonaws.com`).
- **Resource policies** (10 per Region) for services writing logs (Route 53, Step Functions, API Gateway…); keep policy size < 5,120 characters; use `/aws/vendedlogs/` prefix to avoid limits.
- **Tags**, **log group deletion** deletes data.
- **Delivery**: SDK `PutLogEvents`, **CloudWatch agent**, **Fluent Bit/Fluentd** (EKS/ECS firelens), **Lambda automatic logging**, **vended logs** (VPC Flow Logs, Route 53, API Gateway, WAF, Step Functions, Glue continuous logging, EMR via agent).

## B. Where data-engineering services log
| Service | Log destination / notes |
|---|---|
| **Lambda** | `/aws/lambda/<function>`; needs `logs:CreateLogGroup/CreateLogStream/PutLogEvents`; set retention; JSON structured logging option |
| **Glue** | `/aws-glue/jobs/output`, `/aws-glue/jobs/error`, `/aws-glue/jobs/logs-v2` (continuous logging); enable job metrics and Spark UI |
| **EMR** | Logs to S3 (log URI); CloudWatch agent for node logs; step logs in S3 |
| **EMR Serverless / EKS** | S3 and/or CloudWatch via configuration |
| **Step Functions** | `/aws/vendedlogs/states/…` (Express required); levels ALL/ERROR/FATAL |
| **MWAA** | `airflow-<env>-Scheduler/Worker/Task/WebServer/DAGProcessing` |
| **Firehose** | `/aws/kinesisfirehose/<stream>` error logs for delivery failures |
| **Kinesis Data Analytics / Managed Flink** | application log stream |
| **API Gateway** | execution and access logs |
| **Athena** | no query logs in CloudWatch; use CloudTrail, workgroup metrics, query history |
| **Redshift** | audit logs to S3 or CloudWatch (connection, user, user activity); system tables |
| **RDS/Aurora** | slow query, error, general, audit logs exported to CloudWatch Logs |
| **OpenSearch** | slow logs, error logs, audit logs |
| **MSK** | broker logs to CloudWatch/S3/Firehose |
| **DMS** | task logs in CloudWatch |
| **Route 53 Resolver, VPC Flow Logs, WAF, CloudTrail** | optionally to CloudWatch Logs |
- **Always control cost**: set retention on every group; avoid DEBUG logging in production; sample logs.

## C. Logs Insights (querying)
- **CloudWatch Logs Insights** queries one or more log groups with a purpose-built **query language** (and since 2023–2024 also **OpenSearch PPL and SQL**) **(verify)**.
- **Core commands**: `fields`, `filter`, `stats` (count, sum, avg, min, max, pct), `sort`, `limit`, `parse` (regex/glob to extract fields), `display`, `dedup`, `bin()` for time buckets, `filterIndex` (indexed fields) **(verify)**.
- **Auto-discovered fields** for JSON logs and Lambda/VPC Flow/Route 53/CloudTrail formats (`@timestamp`, `@message`, `@logStream`, `@ingestionTime`).
- **Queries**: up to **50 log groups** per query; **concurrent queries** default 30 (Standard) **(verify)**; query timeout 60 minutes; result limit 10,000 rows (default 1,000) **(verify)**.
- **Scan cost** per GB scanned; narrow **time range** and log groups to cut cost; field indexes (index policies) reduce scan **(verify)**.
- **Saved queries**, **query history**, **dashboards widgets**, **scheduled queries** **(verify)**.
- **Log patterns & anomaly detection**: Logs Insights `pattern` command finds common patterns; **log anomaly detectors** (500 per Region) flag unusual patterns.
- **Live Tail**: real-time streaming view (up to 15 concurrent sessions); about $0.01/min after 1,800 free minutes.
- **Cross-account queries** via OAM.
- **Typical queries**:
  - Lambda errors: `fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 50`
  - Glue failures: `filter @message like /Exception/ | stats count() by bin(1h)`
  - Slowest invocations: `filter @type = "REPORT" | stats max(@duration), avg(@duration) by bin(5m)`
  - Memory usage: `filter @type="REPORT" | stats max(@maxMemoryUsed/1000/1000) as MB by bin(1h)`

## D. Metric filters
- **Metric filters** extract numeric metrics from log events using **filter patterns** (term matching, JSON `{ $.statusCode = 500 }`, space-delimited `[ip, user, ..., status=4*]`).
- Define metric name, namespace, **value** (1 per match or a numeric field), **default value**, unit, dimensions (up to 3 from JSON/space-delimited).
- **Up to 100 metric filters per log group**; filters apply only to **new** events after creation (not historical).
- Metrics from filters are standard CloudWatch metrics → alarms/dashboards.
- Not available for Infrequent Access class.
- Use for: counting errors, parsing pipeline "records processed" lines, security events (CIS CloudTrail alarms).
- **EMF** is preferred for new code (richer, no filter management).

## E. Subscription filters and delivery
- **Subscription filters** stream matching log events in near real time to: **Lambda**, **Kinesis Data Streams**, **Amazon Data Firehose**, or a **cross-account/cross-Region destination**. Up to **5 per log group** (quota page) **(older docs say 2)**.
- Payload is **base64 + gzip** JSON for Kinesis/Lambda targets; Firehose can decompress and convert.
- Patterns: logs → Kinesis → Lambda/Flink for processing; logs → Firehose → S3/OpenSearch/Splunk; centralized logging account using **destinations**.
- **Account-level subscription filter policies** apply a filter to many log groups at once (with selection criteria) **(verify)**.
- **Export to S3**: `CreateExportTask` (batch, up to 12 hours delay; **1 active export task** per account); not for streaming.
- **Firehose-based** pipeline is common for **long-term archive to S3** (cheaper than storing in CloudWatch).
- **Zero-ETL/S3 Tables integration** for logs is emerging (`AssociateSourceToS3TableIntegration`) **(verify)**.
- **Transformers** (log transformers) can parse/normalize logs at ingestion **(verify)**.

## F. Data protection and compliance for logs
- **Data protection policies** detect and **mask sensitive data** (PII, credentials, financial) with managed data identifiers or custom regex; findings can go to CloudWatch Logs, S3 or Firehose; scanning about **$0.12/GB** **(verify)**.
- **Masking** hides values from users without `logs:Unmask` permission.
- **Restrict access** with IAM to specific log groups; deny `logs:GetLogEvents` for sensitive groups.
- **Retention policies** support GDPR/right-to-delete (short retention for PII logs).
- **Avoid logging secrets**; use EMF/structured logs excluding PII.
- **Audit**: CloudTrail logs CloudWatch API calls (`DeleteLogGroup`, `PutRetentionPolicy`).
- **Cross-account**: resource policy/destination policy to allow delivery.

## G. Contributor Insights
- **Contributor Insights** analyzes **log data** (or DynamoDB) to show **top-N contributors** (for example top IPs, top error sources, hot partition keys) in near real time, using **rules** on JSON/CLF logs.
- Pricing: first rule free; about $0.50 per rule per month + $0.02 per million matched events after 1 million **(verify)**.
- Built-in rules for DynamoDB (most accessed/throttled keys).

## H. Cost and operations
- **Cost drivers**: ingestion (largest), storage, Insights scans, Live Tail, data protection, exports.
- **Levers**: set retention; use **Infrequent Access** for rarely queried logs; reduce verbosity; filter before ingest (agent filters, Firehose to S3 for bulk logs); compress/aggregate; avoid duplicate logging; exclude health checks; archive to S3 with lifecycle.
- **Troubleshooting**:
  - No logs from Lambda → execution role lacks permissions, log group deleted, VPC/endpoint issue.
  - Missing events from agent → agent config/permissions, time sync, rate throttling (`PutLogEvents` 5,000 TPS per account).
  - Insights returns nothing → wrong time range or group, field name mismatch, query on IA class unsupported features.
  - Subscription delivery failures → destination permissions, Lambda throttling, Kinesis limits.
  - Metric filter shows no data → pattern syntax, case sensitivity, events before filter creation.
  - `ThrottlingException`/`ServiceUnavailable` → exceed API TPS.
  - High cost → check top log groups by ingestion (`IncomingBytes` metric).

## I. Limits (selected, from quota page)
| Item | Value |
|---|---|
| Log groups per Region | **1,000,000** |
| Event size | **1 MB** |
| PutLogEvents batch | **1 MB** |
| PutLogEvents rate | **5,000 TPS** per account/Region (adjustable) |
| Metric filters per group | **100** |
| Subscription filters per group | **5** |
| Resource policies | **10** per Region |
| Export tasks active | **1** |
| Live Tail sessions | **15** |
| Log anomaly detectors | **500** |
| Data archiving free | **5 GB** |

## J. Exam skills mapping
- **3.3.7 CloudWatch Logs for application data**: CloudWatch Logs for application data.
- **3.3.8 Analyze logs (Athena, EMR, OpenSearch, Logs Insights)**: Logs Insights.
- **4.4.2 CloudWatch Logs for application logs**: application logs.
- **4.4.4 Analyze logs (Athena, Logs Insights, OpenSearch)**: analyze logs.

## K. Scenarios: "If X → Y, because Z"
- **If** you must find which **AWS Lambda** invocations took longer than 3 seconds, **then** run a **CloudWatch Logs Insights** query on the **`REPORT`** lines (`filter @type = "REPORT"`, then filter or sort on `@duration`). Logs Insights searches log groups with its own query language. **This works because** Lambda writes a `REPORT` line per invocation with its **duration** and memory used, so the query finds the slow ones directly.
- **If** logs must be searchable for **14 days** but archived for **7 years**, **then** set **CloudWatch Logs retention to 14 days** and add a **subscription filter → Amazon Data Firehose → Amazon S3**, with an **S3 Lifecycle** rule for the long-term copy. A subscription filter streams matching log events in near real time. **This works because** keeping logs long-term in **S3 is cheaper** than in CloudWatch. `CreateExportTask` is not a good fit: it is a batch job with up to **12 hours** delay and only **1 active task** per account.
- **If** a central security account needs all logs, **then** use **subscription filters to a cross-account destination**, or **CloudWatch cross-account observability (Observability Access Manager, OAM)**. Subscription filters in each source account stream log events to a **destination** in the central account; OAM lets the central account view linked accounts' logs. **This works because** both route logs automatically, with **no manual copying**. The destination needs a **destination policy** that allows the delivery.
- **If** personally identifiable information (PII) appears in logs, **then** add a **data protection policy** that **masks** it, and limit who has **`logs:Unmask`**. The policy detects PII, credentials and financial data using managed data identifiers or custom regex. **This works because** masked values stay hidden from anyone **without `logs:Unmask`**, so the data is not exposed. Scanning costs about **$0.12/GB** **(verify)**.
- **If** error counts need an alarm, **then** create a **metric filter → metric → alarm** (or use **Embedded Metric Format (EMF)** in new code). A metric filter matches a pattern in log events, such as `{ $.statusCode = 500 }`, and turns matches into a CloudWatch metric. **This works because** filters **convert log lines to metrics**, and metrics can drive alarms. Filters only see **new** events after creation and are not available on the Infrequent Access class.
- **If** log costs are too high, **then** **set retention** on every log group, **lower verbosity** (no DEBUG in production), and use the **Infrequent Access (IA)** log class for rarely queried groups. **This works because** **ingestion** (about **$0.50/GB**, IA about **$0.25/GB**) and **storage** dominate log costs, and the default retention is **never expire**. The catch: IA has fewer features (no subscription or metric filters, no export) and the class cannot be changed after creation **(verify)**.
- **If** you need near-real-time log processing, **then** add a **subscription filter** that sends to **Amazon Kinesis Data Streams** or **AWS Lambda**. **This works because** a subscription filter **streams matching events** as they arrive. The payload is **base64 + gzip** JSON, so the consumer must decode it. A log group can have up to **5** subscription filters (older docs say 2).
- **If** you need the top talkers or hot keys, **then** use **CloudWatch Contributor Insights**, which applies **rules** to JSON or Common Log Format (CLF) logs. **This works because** it **ranks the top-N contributors** (such as top IP addresses or top error sources) from logs in near real time.
- **If** an **Amazon DynamoDB** table is throttled because of hot keys, **then** turn on **Contributor Insights for DynamoDB**. **This works because** its built-in rules show the **most accessed and most throttled keys**, so you can see which partition key is hot.

Verified from AWS docs on 2026-11-09 (CloudWatch Logs quotas, CloudWatch pricing).
Unconfirmed (verify): batch time window; subscription filter count (quota page 5 vs older 2); IA class feature limits; PPL/SQL support; field indexes; scheduled queries; data protection price; Logs Insights concurrency; export delay; log transformer features.

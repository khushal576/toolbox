# Amazon CloudWatch – 1. Metrics, namespaces, custom metrics, metric math and streams

Short notes. Each point is a fact you can be asked about.

## A. What CloudWatch is
- **Amazon CloudWatch** is the monitoring and observability service: **metrics**, **logs**, **alarms**, **dashboards**, **events/EventBridge** link, **Synthetics**, **RUM**, **Application Signals**, **Container/Lambda Insights**, **Contributor Insights**, **Logs Insights**, and **cross-account observability**.
- It is **Regional**: metrics and logs live in the Region where they are created (dashboards can show several Regions).
- Pick it when: you need **operational monitoring** of pipelines (Glue, EMR, Lambda, Kinesis, MSK, Redshift, Step Functions, MWAA), alarms, log search, and dashboards.
- DEA-C01: **3.x Operations and Support**: monitor data pipelines (CloudWatch metrics/alarms/logs), troubleshoot, and **4.4** logging (CloudWatch Logs).

## B. Metric basics
- A **metric** is a time-ordered set of **data points** identified by **namespace + metric name + dimensions**.
- **Namespace**: container for metrics (AWS services use `AWS/<Service>`, for example `AWS/Lambda`, `AWS/Glue`, `AWS/Kinesis`, `AWS/ElasticMapReduce`, `AWS/Redshift`, `AWS/Firehose`, `AWS/Kafka`, `AWS/States`, `AWS/S3`; custom namespaces cannot start with `AWS/`).
- **Dimension**: name/value pair that is part of a metric's identity (for example `FunctionName`, `StreamName`, `JobName`). **Each unique combination is a separate metric** (and billed separately). **Up to 30 dimensions** per metric.
- **Statistics**: Sum, Average, Minimum, Maximum, SampleCount, percentiles (p50, p90, p99), `TM`/`WM`/`PR` and others (trimmed mean etc.).
- **Period**: aggregation window (multiple of 60 s; high-resolution 1, 5, 10, 30 s).
- **Unit**: Seconds, Bytes, Count, Percent… (informational but used for sorting/aggregation).
- **Timestamps**: up to **2 weeks in the past** and **2 hours in the future** accepted for custom metrics.
- **Resolution**:
  - **Standard resolution**: 1-minute granularity.
  - **High resolution**: down to 1 second (`StorageResolution=1`), custom metrics only.
- **Retention (automatic rollup)**:
  - Data points < 60 s: kept **3 hours**.
  - 1-minute points: **15 days**.
  - 5-minute points: **63 days**.
  - 1-hour points: **455 days (15 months)**.
- Metrics **cannot be deleted**; they expire after 15 months with no new data.
- **AWS service metrics** are free and delivered by default (EC2 basic monitoring every 5 min; **detailed monitoring** 1 min costs extra; most newer services publish at 1 min).
- **Missing data**: services publish only when there is activity for some metrics (for example Lambda `Errors` only when there are invocations) → alarms need the right **missing-data treatment**.

## C. Key metrics for data pipelines (cheat sheet)
| Service | Namespace | Important metrics |
|---|---|---|
| **Lambda** | `AWS/Lambda` | `Invocations`, `Errors`, `Throttles`, `Duration`, `ConcurrentExecutions`, `IteratorAge` (stream/ESM lag), `DeadLetterErrors`, `AsyncEventAge` |
| **Kinesis Data Streams** | `AWS/Kinesis` | `GetRecords.IteratorAgeMilliseconds`, `WriteProvisionedThroughputExceeded`, `ReadProvisionedThroughputExceeded`, `IncomingBytes/Records`, `PutRecord.Success` |
| **Firehose** | `AWS/Firehose` | `DeliveryToS3.Success`, `DeliveryToS3.DataFreshness`, `IncomingBytes`, `ThrottledGetRecords`, `ExecuteProcessing.Success` |
| **MSK** | `AWS/Kafka` | `KafkaDataLogsDiskUsed`, `CpuUser`, `MaxOffsetLag`, `UnderReplicatedPartitions`, `OfflinePartitionsCount` |
| **Glue** | `Glue` (job metrics) | `glue.driver.aggregate.numFailedTasks`, `glue.ALL.system.cpuSystemLoad`, `glue.driver.jvm.heap.usage`, `glue.driver.BlockManager.disk.diskSpaceUsed_MB` (must enable job metrics) |
| **EMR** | `AWS/ElasticMapReduce` | `YARNMemoryAvailablePercentage`, `HDFSUtilization`, `AppsPending`, `ContainerPending`, `IsIdle`, `CoreNodesRunning` |
| **Redshift** | `AWS/Redshift` | `CPUUtilization`, `PercentageDiskSpaceUsed`, `DatabaseConnections`, `QueryDuration`, `WLMQueueLength`, `ConcurrencyScalingActiveClusters` |
| **Step Functions** | `AWS/States` | `ExecutionsFailed`, `ExecutionsTimedOut`, `ExecutionThrottled`, `ExecutionTime` |
| **MWAA** | `AmazonMWAA` | `SchedulerHeartbeat`, `QueuedTasks`, `ImportErrors`, `TaskInstanceFailures` |
| **S3** | `AWS/S3` | Request metrics (opt-in), replication metrics, storage metrics daily (`BucketSizeBytes`, `NumberOfObjects`) |
| **DynamoDB** | `AWS/DynamoDB` | `ConsumedReadCapacityUnits`, `ThrottledRequests`, `SystemErrors`, `ReplicationLatency` |
| **Athena** | `AWS/Athena` | `ProcessedBytes`, `TotalExecutionTime`, `EngineExecutionTime`, per-workgroup metrics |
| **OpenSearch** | `AWS/ES` | `ClusterStatus.red`, `FreeStorageSpace`, `JVMMemoryPressure` |
| **RDS/Aurora** | `AWS/RDS` | `CPUUtilization`, `DatabaseConnections`, `FreeableMemory`, `ReplicaLag`, `ReadIOPS` |
- **Metric-based "lag" alarms** are the main pipeline health signals: **IteratorAge** (Lambda/Kinesis), **MaxOffsetLag** (MSK), **DataFreshness** (Firehose), **queue age** (SQS `ApproximateAgeOfOldestMessage`).

## D. Publishing custom metrics
- **`PutMetricData`**: send values or **statistic sets** (min, max, sum, count); up to **1,000 metrics** per request and **1 MB** payload (150 KB uncompressed in older docs) **(verify)**; each unique dimension set creates a new metric.
- **CloudWatch agent**: collects OS-level metrics (memory, disk) and logs from EC2/on-prem; config in JSON or SSM Parameter Store; supports StatsD and collectd.
- **Embedded Metric Format (EMF)**: write structured JSON log lines containing a `_aws.CloudWatchMetrics` section; CloudWatch **extracts metrics automatically** from logs (best for Lambda/containers, no PutMetricData call, high-cardinality context preserved in logs).
- **Metric filters** turn log patterns into metrics (file 3).
- **Lambda**: publish custom metrics with EMF or Powertools metrics.
- **Glue**: enable **job metrics** and **continuous logging**; use custom metrics via boto3 in scripts.
- **Cost warning**: each unique metric (name + dimension set) is billed; avoid high-cardinality dimensions like request IDs or user IDs.
- **Quotas**: PutMetricData TPS limits (default 500 TPS per Region, adjustable) **(verify)**.

## E. Querying and metric math
- **GetMetricData**: fetch up to 500 metrics per call; supports **metric math**, cross-account, cross-Region (via OAM); billed per metric requested. **GetMetricStatistics** is older/simpler (one metric).
- **Metric math**: expressions across metrics (`m1/m2*100`, `RATE(m1)`, `SUM(METRICS())`, `FILL(m1,0)`, `IF`, `ANOMALY_DETECTION_BAND`), usable in graphs and **alarms**.
- **Search expressions**: `SEARCH('{AWS/Lambda,FunctionName} MetricName="Errors"', 'Sum', 300)` to graph many resources dynamically.
- **Metrics Insights**: SQL-like queries across metrics at scale (`SELECT AVG(CPUUtilization) FROM SCHEMA("AWS/EC2", InstanceId) GROUP BY InstanceId`), also in alarms (Metrics Insights alarms) **(verify limits)**.
- **Percentiles** require enough datapoints; alarm with `evaluate low sample count percentiles` options.
- **Math for rates**: error rate = `Errors / Invocations * 100`; success ratio, freshness, saturation.

## F. Metric streams and export
- **Metric streams** continuously push metrics (near real time, ~2–3 min latency) to **Firehose** → S3 / Datadog / Splunk / New Relic / etc. Formats: **JSON, OpenTelemetry 0.7/1.0**, **Parquet** via Firehose **(verify)**.
- Choose all metrics or include/exclude namespaces; can include statistics (percentiles).
- Cost: about **$0.003 per 1,000 metric updates** plus Firehose and destination costs.
- **Use for**: data lake of metrics (S3 + Athena), third-party observability platforms, cross-account aggregation.
- **Alternative**: `GetMetricData` scheduled export (Lambda) – cheaper for small sets but delayed.
- **CloudWatch metrics are not in S3 by default**; use streams for retention beyond 15 months.

## G. Cross-account and cross-Region
- **CloudWatch cross-account observability (OAM, Observability Access Manager)**: designate a **monitoring account** that links **source accounts** (individual or organization) to view metrics, logs, traces, Application Signals, Internet monitors in one place; supports Organizations. Sink + link resources. Replaces older cross-account dashboards sharing.
- **Cross-Region dashboards**: a dashboard can display widgets from multiple Regions.
- **Centralized logging**: subscription filters/destinations or OAM.
- **Dashboards sharing**: share with IAM, public link, or SSO.

## H. Quotas (selected)
| Item | Value |
|---|---|
| Metric retention | 3 h (<60 s), 15 d (1 min), 63 d (5 min), 455 d (1 h) |
| Dimensions per metric | **30** |
| Alarms per Region | **5,000** (adjustable) **(verify)** |
| Composite alarms | 500 **(verify)** |
| Dashboards | 500 per account **(verify)** |
| `GetMetricData` metrics per call | **500** |
| Metric streams | 20 per Region **(verify)** |
| High-resolution | 1, 5, 10, 30 s |

## I. Exam skills mapping
- **3.3.2 Logging and monitoring for auditing and traceability**: metrics for monitoring.
- **3.3.4 Troubleshoot performance**: pipeline performance metrics.
- **3.1.9 Events and schedulers (EventBridge)**: metrics for event/scheduler monitoring.

## J. Scenarios: "If X → Y, because Z"
- **If** a consumer reading from **Amazon Kinesis Data Streams** falls behind, **then** create a **CloudWatch alarm** on the stream metric **`GetRecords.IteratorAgeMilliseconds`** (namespace `AWS/Kinesis`). An alarm watches a metric and changes state (OK, ALARM) when it crosses a threshold. **This works because** iterator age measures **stream lag**: how old the records being read are. A growing value means the consumer cannot keep up. Lag alarms like this are the main health signal for a streaming pipeline.
- **If** an **AWS Lambda** function reading a stream is backing up, **then** alarm on two Lambda metrics: **`IteratorAge`** and **`Throttles`** (namespace `AWS/Lambda`). **This works because** `IteratorAge` shows how far behind the function is (stream lag), and `Throttles` shows the function is hitting its **concurrency limits**, a common reason it falls behind. Together they show both the lag and one likely cause.
- **If** you need **memory** usage from **Amazon Elastic Compute Cloud (EC2)** or **Amazon EMR** hosts, **then** install the **CloudWatch agent**. The agent collects OS-level metrics such as **memory** and **disk**, plus logs, from EC2 or on-premises servers; its config is JSON or lives in **AWS Systems Manager (SSM) Parameter Store**. **This works because** memory is **not a default EC2 metric**, so it must be collected from inside the operating system.
- **If** you need custom metrics with rich context from **AWS Lambda**, **then** use the **Embedded Metric Format (EMF)**: write structured JSON log lines that contain a `_aws.CloudWatchMetrics` section. **This works because** CloudWatch **extracts the metrics automatically** from those logs, so there is no `PutMetricData` call, and high-cardinality context stays in the logs instead of becoming costly metric dimensions.
- **If** **Amazon Data Firehose** delivery to Amazon S3 looks late, **then** alarm on **`DeliveryToS3.DataFreshness`** (namespace `AWS/Firehose`). **This works because** this metric tracks the **age of the oldest record** not yet delivered, so a rising value means data in S3 is going stale. A typical threshold is the buffer time plus a margin.
- **If** you want CloudWatch metrics in **Amazon S3** for long-term analysis, **then** build **metric stream → Amazon Data Firehose → S3 (Parquet) (verify) → Amazon Athena**. A **metric stream** continuously pushes metrics in near real time (about **2–3 minutes**) to Firehose, which writes them to S3, where Athena can query them. **This works because** metrics are **not in S3 by default** and CloudWatch keeps metric history only **15 months** (455 days). The catch: you pay about **$0.003 per 1,000 metric updates** plus Firehose and destination costs.
- **If** custom metric costs explode, **then** **remove high-cardinality dimensions** such as request IDs or user IDs. A **dimension** is a name/value pair that is part of a metric's identity. **This works because** **each unique dimension combination is a separate metric** and is billed separately (about **$0.30** per metric per month for the first 10,000), so one dimension with many values creates many billed metrics. Keep that detail in logs (for example with EMF) instead.
- **If** one place must show metrics from all accounts, **then** set up a **monitoring account** with **CloudWatch cross-account observability (Observability Access Manager, OAM)**. Source accounts (single ones or a whole AWS Organizations organization) **link** to a **sink** in the monitoring account, which can then view their metrics, logs and traces. **This works because** the monitoring account reads the linked accounts' data, so it **centralizes without copying data**.
- **If** you need an error rate the service does not publish, **then** use **metric math**: `Errors / Invocations * 100`. Metric math builds expressions across metrics. **This works because** the expression creates a new **derived series** you can graph and also use in **alarms**.

Verified from AWS docs on 2026-11-09 (CloudWatch quotas and CloudWatch Logs quotas pages, CloudWatch pricing page).
Unconfirmed (verify): PutMetricData payload/TPS; alarm/composite/dashboard/metric-stream counts; Metrics Insights alarm limits; metric stream output formats; EC2 detailed monitoring price; Glue metric names; MSK metric names.

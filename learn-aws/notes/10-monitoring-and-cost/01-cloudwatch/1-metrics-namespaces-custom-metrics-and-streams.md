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
- If a Kinesis consumer falls behind → **alarm on `GetRecords.IteratorAgeMilliseconds`**, because it measures stream lag.
- If a Lambda reading a stream is backing up → **alarm on `IteratorAge` and `Throttles`**, because they show lag and concurrency limits.
- If you need memory usage from EC2/EMR hosts → **CloudWatch agent**, because memory isn't a default EC2 metric.
- If you need metrics with rich context from Lambda → **Embedded Metric Format**, because logs become metrics automatically.
- If Firehose delivery looks late → **`DeliveryToS3.DataFreshness` alarm**, because it tracks the age of the oldest record.
- If you want metrics in S3 for long-term analysis → **metric stream → Firehose → S3 (Parquet) → Athena**, because metric history is only 15 months.
- If custom metric costs explode → **remove high-cardinality dimensions**, because each unique dimension set is billed as a metric.
- If one place must show all account metrics → **OAM monitoring account**, because it centralizes without copying data.
- If you need an error rate not published by the service → **metric math `Errors/Invocations*100`**, because math creates derived series.

Verified from AWS docs on 2026-11-09 (CloudWatch quotas and CloudWatch Logs quotas pages, CloudWatch pricing page).
Unconfirmed (verify): PutMetricData payload/TPS; alarm/composite/dashboard/metric-stream counts; Metrics Insights alarm limits; metric stream output formats; EC2 detailed monitoring price; Glue metric names; MSK metric names.

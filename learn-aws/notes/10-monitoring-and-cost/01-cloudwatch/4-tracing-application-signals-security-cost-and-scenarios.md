# Amazon CloudWatch – 4. X-Ray tracing, Application Signals, other insights, security, cost and scenarios

Short notes. Each point is a fact you can be asked about.

## A. AWS X-Ray (distributed tracing)
- **X-Ray** traces requests as they travel through services, showing a **service map**, **traces**, **segments/subsegments**, latency, errors, faults, throttles.
- **Segment**: work done by one service; **subsegment**: downstream calls (DynamoDB, S3, HTTP) inside a segment; **annotations** (indexed key-values for filtering) and **metadata** (not indexed).
- **Trace ID** passes through `X-Amzn-Trace-Id` header; **sampling rules** control how many requests are traced (default 1 request/second + 5% extra).
- **Instrumentation**: X-Ray SDK, **AWS Distro for OpenTelemetry (ADOT)**, or **active tracing** switch for **Lambda, API Gateway, Step Functions, App Runner, AppSync, SNS/SQS** (trace propagation).
- **X-Ray daemon / collector** receives UDP segments and sends batches (required on EC2/ECS/EKS; built into Lambda).
- **Groups and filter expressions** (for example `responsetime > 5 AND service("glue")`), **trace analytics**, **insights** (anomaly detection of fault rates).
- **Retention**: traces kept **30 days**.
- **Pricing**: per trace recorded and retrieved/scanned; first 100,000 traces recorded and 1 million retrieved per month free **(verify)**.
- **Transaction Search** (newer) indexes spans as **CloudWatch Logs** (`aws/spans`) for flexible search and Application Signals **(verify)**.
- **Data pipeline relevance**: Step Functions active tracing shows latency per state; Lambda → DynamoDB/S3 call timings; API Gateway data APIs; not for Spark jobs or streaming throughput.
- **Limits**: segment document size 64 KB; 50 annotations per segment (10 per key limits) **(verify)**.

## B. CloudWatch Application Signals
- **Application Signals** gives out-of-the-box **application performance monitoring (APM)**: auto-discovers services, shows **SLIs/SLOs** (latency, availability, faults), service map, dependencies, and correlates with traces and logs.
- Works with **ADOT/auto-instrumentation** on **EKS, ECS, EC2, Lambda** (Java, Python, Node.js, .NET) **(verify language support)**.
- **SLOs**: define objective and error budget; alarms on burn rate.
- **Service Level Objectives for data APIs** (availability and latency) are common use cases.
- Priced by application signals and spans ingested **(verify)**.
- **Exam note**: know it as CloudWatch's APM feature; it builds on X-Ray/OpenTelemetry.

## C. Other CloudWatch insights features
- **Container Insights**: metrics and logs for **ECS, EKS, Kubernetes** (CPU, memory, network, storage per pod/task); enhanced observability for EKS; deployed via CloudWatch agent / Fluent Bit.
- **Lambda Insights**: enhanced Lambda metrics (memory, CPU, init duration, network, tmp space) via a Lambda extension layer; extra cost.
- **Application Insights**: automatic dashboards/alarms for .NET/SQL Server, Java and other app stacks on EC2/ECS **(verify)**.
- **Database Insights** / **RDS Performance Insights**: DB load analysis (Performance Insights for RDS/Aurora is separate but related; Database Insights is the newer expanded offering) **(verify)**.
- **Network Insights**: VPC Flow Logs-based tools (Network Flow Monitor).
- **CloudWatch investigations (AI operations)**: generative AI-assisted troubleshooting that analyzes telemetry and suggests root causes **(verify availability)**.
- **Observability Admin / telemetry configuration**: enable telemetry auto-discovery and centralization across accounts **(verify)**.
- **Metrics Insights**, **Contributor Insights**, **Live Tail** (covered earlier).

## D. Security and access control
- **IAM actions**: `cloudwatch:PutMetricData`, `GetMetricData`, `PutMetricAlarm`, `DescribeAlarms`, `logs:PutLogEvents`, `logs:StartQuery`, `logs:GetQueryResults`, `logs:PutSubscriptionFilter`, `xray:PutTraceSegments`, `xray:GetTraceSummaries`, `oam:*`.
- **Managed policies**: `CloudWatchReadOnlyAccess`, `CloudWatchFullAccess` (v2 split), `CloudWatchLogsFullAccess`, `CloudWatchAgentServerPolicy`, `AWSXRayDaemonWriteAccess`, `AWSXrayReadOnlyAccess` **(verify exact names)**.
- **Least privilege**: workloads only need `logs:CreateLogStream/PutLogEvents` on their log group and `cloudwatch:PutMetricData` (condition `cloudwatch:namespace` to limit namespaces).
- **Resource-level**: log group ARNs, alarm ARNs; tag-based access for alarms/dashboards.
- **Encryption**: KMS for log groups; CloudWatch metrics/alarms encrypted at rest by AWS.
- **VPC endpoints**: interface endpoints for `monitoring` (metrics), `logs`, `events`, `xray`, `synthetics`? (check) to keep traffic private.
- **Cross-account observability**: OAM sink policy controls which accounts can link; link scope (metrics/logs/traces).
- **Audit**: CloudTrail logs CloudWatch/Logs API calls; alarm state changes are events.
- **Prevent tampering**: SCP/IAM deny `cloudwatch:DeleteAlarms`, `logs:DeleteLogGroup`, `logs:PutRetentionPolicy` shortening in prod; alarms on those API calls.

## E. Cost (summary, indicative US East)
| Item | Price |
|---|---|
| Custom metrics | **$0.30** each for first 10,000 per month, **$0.10** next 240,000, **$0.05** beyond |
| Standard alarm | **$0.10** per alarm metric per month |
| High-resolution alarm | about **$0.30** |
| Composite alarm | about **$0.50** |
| Dashboards | 3 free, then about $3/month each **(verify)** |
| Logs ingestion (Standard) | about **$0.50/GB**; IA about **$0.25/GB** |
| Logs storage | about **$0.03/GB-month** |
| Logs Insights | about **$0.005/GB scanned** |
| Live Tail | **$0.01/min** after 1,800 free |
| Data protection | about **$0.12/GB** scanned |
| Metric streams | **$0.003 / 1,000 updates** |
| Contributor Insights | first rule free; $0.50/rule; $0.02/M events |
| Synthetics | first 100 runs free; then per run |
| `GetMetricData` | per 1,000 metrics requested (always charged) |
| Free tier | 10 metrics, 10 alarms, 3 dashboards, 5 GB logs, 1M API requests, 100 canary runs |
- **Biggest bills are almost always logs ingestion and custom metrics cardinality.**
- **Cost levers**: set retention; reduce log verbosity; avoid per-request dimensions; use EMF with few dimensions; aggregate before publishing; delete unused alarms/dashboards; use metric streams to S3 only when needed; use Infrequent Access for audit-type logs; sample X-Ray traces.

## F. Monitoring strategy for a data platform
1. **Golden signals per pipeline**: freshness (data age), volume (rows/files/bytes), failures, latency, cost.
2. **Metrics**: service built-ins + custom "business" metrics (rows processed, DQ failures) via EMF.
3. **Logs**: structured JSON logs with correlation IDs (job run ID, execution ARN), retention by tier.
4. **Events**: EventBridge for Glue/EMR/Step Functions/DMS/Batch state changes.
5. **Alarms**: symptom-based, composite to reduce noise; heartbeat alarms for schedule misses.
6. **Dashboards**: one per domain (ingestion, transformation, serving), plus an exec summary.
7. **Tracing**: Step Functions/Lambda/API Gateway active tracing for service flows.
8. **Response**: SNS → chat/Incident Manager; runbooks (SSM Automation); DLQ replay tools.
9. **Retention/audit**: metric streams/log exports to S3 for long-term; CloudTrail for changes.
10. **Cost monitoring**: Budgets/Cost Anomaly Detection on CloudWatch spend.

## G. Troubleshooting CloudWatch itself
- **Alarm stuck in INSUFFICIENT_DATA** → metric not published (no activity), wrong dimensions/namespace/Region, period shorter than publish interval → fix dimensions or missing-data treatment.
- **Alarm didn't notify** → SNS topic policy, subscription not confirmed, action disabled, alarm state not changing.
- **Metrics missing** → detailed monitoring not on, agent not running, IAM, service doesn't publish when idle.
- **Dashboard blank** → wrong Region, time range, deleted resources.
- **Logs delayed or missing** → agent buffering, throttling, permission issues.
- **Throttled API calls** → reduce polling, use metric streams, batch `GetMetricData`.
- **Unexpected bill** → check `Metrics` and `Logs` usage types in Cost Explorer; find top groups by `IncomingBytes`.

## H. Exam skills mapping
- **3.3.4 Troubleshoot performance**: tracing and troubleshooting.
- **3.3.2 Logging and monitoring for auditing and traceability**: monitoring strategy.
- **4.4.2 CloudWatch Logs for application logs**: log security and cost.

## I. Scenarios: "If X → Y, because Z"
- **If** you must see where latency happens across **AWS Lambda**, **Amazon DynamoDB** and **Amazon API Gateway**, **then** turn on **AWS X-Ray active tracing** and use the **service map**. X-Ray follows each request through services with a **trace ID**; each service records a **segment**, and downstream calls like DynamoDB become **subsegments**. **This works because** the trace breaks down **latency per hop**, so you see which call is slow. **Sampling rules** limit how many requests are traced.
- **If** leadership wants **service level objective (SLO)** tracking for a data API, **then** use **CloudWatch Application Signals SLOs**. Application Signals is CloudWatch's **application performance monitoring (APM)** feature, built on X-Ray and OpenTelemetry. **This works because** it computes **service level indicators (SLIs)** such as latency and availability, tracks the **error budget**, and can alarm on burn rate.
- **If** **Amazon Elastic Kubernetes Service (EKS)** or **Amazon Elastic Container Service (ECS)** workloads need CPU and memory metrics per pod or task, **then** use **CloudWatch Container Insights**, deployed with the CloudWatch agent or Fluent Bit. **This works because** it collects and **aggregates container metrics** (CPU, memory, network, storage) per pod or task.
- **If** you need to tune **AWS Lambda** memory or init time, **then** enable **CloudWatch Lambda Insights**, added as a Lambda **extension layer**. **This works because** it exposes **enhanced metrics** (memory, CPU, init duration, network, tmp space) that the standard Lambda metrics do not. It costs extra.
- **If** a job produces **no data and no errors**, **then** use a **heartbeat alarm** with treat missing data = **`breaching`**: the job publishes a success metric after each run, and the alarm fires when that metric is missing. **This works because** the failure is the **absence** of data, and `breaching` makes silence count as bad.
- **If** you need compliance-grade long-term metric and log history, **then** send metrics to **Amazon S3** with **metric streams**, and logs with **log export or subscription filters**. **This works because** CloudWatch keeps metrics only **15 months**, so long-term copies must live outside it. Use **AWS CloudTrail** for the record of changes.
- **If** your CloudWatch bill is high, **then** check **log ingestion** and **custom metric cardinality** first: in **AWS Cost Explorer** look at the `Metrics` and `Logs` usage types, and find top log groups by `IncomingBytes`. **This works because** these are almost always the biggest bills: logs cost about **$0.50/GB** to ingest, and every unique dimension set is a separately billed metric.
- **If** different teams need their own isolated dashboards but there must also be central monitoring, **then** create an **OAM sink in a monitoring account** (CloudWatch cross-account observability, Observability Access Manager). **This works because** each team account keeps its own data and **links** to the sink; the **sink policy** controls which accounts can link, and the **link scope** sets what is shared (metrics, logs, traces).
- **If** an **AWS Step Functions** workflow is slow, **then** enable **AWS X-Ray active tracing** and review the **duration of each state**. **This works because** tracing shows **time per state and per integration**, so you find the slow step.

Verified from AWS docs on 2026-11-09 (CloudWatch pricing and quotas pages).
Unconfirmed (verify): X-Ray sampling defaults, retention, free tier, Transaction Search; Application Signals languages/pricing; Container/Lambda/Application/Database Insights details; CloudWatch investigations availability; managed policy names; VPC endpoint list; Observability Admin features.

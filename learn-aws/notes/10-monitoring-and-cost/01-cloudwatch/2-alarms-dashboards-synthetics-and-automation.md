# Amazon CloudWatch – 2. Alarms, anomaly detection, dashboards, Synthetics and automation

Short notes. Each point is a fact you can be asked about.

## A. Alarms
- A **metric alarm** watches one metric (or a metric math expression) and changes **state**: **OK**, **ALARM**, **INSUFFICIENT_DATA**.
- **Settings**: statistic, period, **evaluation periods (N)**, **datapoints to alarm (M out of N)**, threshold + comparison operator, **treat missing data**.
- **Treat missing data** options: `missing` (default; alarm keeps state / may go INSUFFICIENT_DATA), `notBreaching` (good), `breaching` (bad), `ignore` (keep current state). Choose based on whether silence is bad (heartbeat) or normal (no traffic).
- **Evaluate range**: alarms evaluate the **most recent N periods**; high-resolution alarms can use 10 or 30 s periods.
- **Actions** per state change: **SNS** topic, **EC2** actions (stop, terminate, reboot, recover), **Auto Scaling** policy, **Systems Manager** (OpsItem, Incident Manager response plan), **Lambda** (via SNS/EventBridge).
- **Alarm actions run on state transitions** (ALARM, OK, INSUFFICIENT_DATA), not repeatedly (re-notify with additional logic or Incident Manager).
- **Composite alarms**: combine alarms with `AND/OR/NOT` rules (`ALARM(a) AND NOT ALARM(b)`) to **reduce noise**; actions can be **suppressed** with an actions-suppressor alarm (for example during maintenance).
- **Anomaly detection alarms**: ML builds an **expected-value band** from history (accounts for daily/weekly seasonality); alarm when metric goes above/below/outside the band; train on 2 weeks of data; excluded time ranges possible.
- **Metrics Insights alarms** and **metric math alarms**: alarm on `Errors/Invocations`, or aggregated queries across many resources.
- **Alarm on logs**: metric filter → metric → alarm; or Logs Insights **scheduled queries/alarms** **(verify)**.
- **Cross-account alarms**: alarms in a monitoring account can reference metrics from linked source accounts (OAM).
- **Alarm history**: kept 2 weeks.
- **Pricing**: standard-resolution alarm about **$0.10 per alarm metric per month**; high-resolution **$0.30**; composite about **$0.50**; anomaly detection alarms cost per metric analyzed **(verify)**; **first 10 alarm metrics free**.
- **Limits**: **5,000 alarms per Region** (adjustable), composite alarms up to 100 children **(verify)**.
- **Alarm names** are unique per Region; use naming convention `<env>-<service>-<symptom>`.
- **Alarm best practices for pipelines**: alarm on **symptoms users feel** (data freshness, backlog age, failure counts), not just causes (CPU).

## B. Alarm patterns for data pipelines
| Pipeline risk | Metric/alarm |
|---|---|
| Glue job failed | EventBridge on job state `FAILED` (preferred) or `glue.driver.aggregate.numFailedTasks` > 0 |
| Glue job too slow | Job run duration anomaly / custom metric |
| Lambda erroring | `Errors` Sum > 0 over 2 of 3 periods; error rate math |
| Lambda throttled | `Throttles` > 0 |
| Stream consumer lag | `IteratorAge` / `GetRecords.IteratorAgeMilliseconds` > threshold |
| Firehose stale | `DeliveryToS3.DataFreshness` > buffer + margin |
| SQS backlog | `ApproximateAgeOfOldestMessage` > N, `ApproximateNumberOfMessagesVisible` |
| DLQ not empty | `ApproximateNumberOfMessagesVisible` > 0 on DLQ |
| MSK disk filling | `KafkaDataLogsDiskUsed` > 80% |
| Redshift disk | `PercentageDiskSpaceUsed` > 80% |
| Step Functions failure | `ExecutionsFailed`, `ExecutionsTimedOut` > 0 |
| MWAA scheduler dead | `SchedulerHeartbeat` missing (`breaching` on missing data) |
| EMR idle | `IsIdle` = 1 for 30 min → terminate |
| S3 replication lag | `ReplicationLatency` / `OperationsPendingReplication` |
| Missing nightly load | Heartbeat custom metric with `breaching` missing-data policy |
- **Heartbeat/dead-man pattern**: pipeline publishes a "success" metric after each run; alarm when `Sum < 1` per expected window with `treatMissingData=breaching`.
- **Event-based** failures (Glue, Step Functions, EMR, Batch, DMS) are best caught by **EventBridge rules** on state changes (no polling).

## C. EventBridge and CloudWatch
- **Amazon EventBridge** (formerly CloudWatch Events) routes **AWS service events** (state-change events, CloudTrail API calls, scheduled rules) to targets (Lambda, SNS, SQS, Step Functions, SSM).
- **Alarm state-change events** (`CloudWatch Alarm State Change`) are emitted to EventBridge → trigger remediation.
- **Use alarms for threshold conditions over time; use EventBridge for discrete events.**
- Scheduled monitoring: EventBridge Scheduler/rules invoke Lambda canaries.

## D. Dashboards
- **Dashboards** are customizable pages of widgets (line, stacked, number, gauge, bar, pie, text, logs table, alarm status, explorer) combining metrics and logs.
- **Cross-account, cross-Region** widgets (OAM).
- **Automatic dashboards** for services (free), **custom dashboards**: first 3 (≤50 metrics each) free; then about **$3 per dashboard per month** **(verify)**.
- **Dashboard as code**: JSON dashboard body via CloudFormation/CDK.
- **Sharing**: with specific IAM users, via link with SSO, or public share (careful).
- **Variables** (property/pattern) let one dashboard serve many resources.
- Use **annotations** for thresholds and deploy markers.

## E. Synthetics (canaries)
- **CloudWatch Synthetics** runs **canaries** (Node.js or Python scripts on a schedule) to test **endpoints, APIs, UI flows, broken links, visual changes**.
- Canary results: success/failure metrics (`SuccessPercent`, `Duration`), screenshots, HAR files, logs → stored in S3; alarms on failure.
- Blueprints: heartbeat monitor, API canary, broken link checker, GUI workflow, visual monitoring, canary recorder.
- Runs inside Lambda; can run **in a VPC** to test private endpoints (data APIs behind ALB/API Gateway private).
- Pricing: per canary run (first 100 runs/month free) **(verify rate)**.
- Use for **data API and dashboard availability**, SLA checks.

## F. RUM, Internet Monitor, Network monitors (context)
- **CloudWatch RUM**: client-side performance and errors for web apps.
- **Internet Monitor**: internet-path performance/availability for your app users.
- **Network Flow Monitor / Network Synthetic Monitor**: network performance between workloads and AWS or on-prem.
- Not core for DEA-C01 but part of CloudWatch's observability family.

## G. Incident response integration
- **Systems Manager Incident Manager**: alarms start incidents with runbooks, escalation plans, on-call.
- **AWS Chatbot / Amazon Q Developer in chat**: send alarms to Slack/Teams/Chime and run CLI commands.
- **SNS** to email/SMS/HTTP/Lambda/SQS; **PagerDuty/Opsgenie** via SNS or EventBridge.
- **OpsItems** (Systems Manager OpsCenter) from alarms.
- **Auto Scaling** actions for EMR (managed scaling is preferred), ECS, DynamoDB.
- **Self-healing**: alarm → SNS → Lambda → restart job/replay DLQ/scale shards.

## H. Cost levers for alarms and dashboards
- Combine many alarms with **composite alarms** and fewer notifications.
- Delete unused alarms/dashboards; avoid alarms on per-resource basis when a Metrics Insights alarm covers a fleet.
- Prefer EventBridge for discrete failures (free for AWS events).
- Avoid high-resolution alarms unless needed.

## I. Exam skills mapping
- **3.3.3 Notifications for alerts**: alerts and alarms.
- **3.3.4 Troubleshoot performance**: troubleshoot performance.
- **3.1.9 Events and schedulers (EventBridge)**: EventBridge.

## J. Scenarios: "If X → Y, because Z"
- **If** a nightly ETL (extract, transform, load) job silently does not run, **then** use the **heartbeat pattern**: the pipeline publishes a "success" custom metric after each run, and a **CloudWatch alarm** fires when `Sum < 1` in the expected window, with **treat missing data = `breaching`**. **This works because** a job that never starts sends **no errors and no data**; `breaching` tells the alarm to treat that silence as bad, so the **absence of data** itself becomes the failure signal.
- **If** alarms are too noisy, **then** use a **composite alarm** or **M-out-of-N datapoints**. A composite alarm combines other alarms with `AND/OR/NOT` rules, for example the symptom AND its cause. M of N means the alarm fires only when, say, **2 of the last 3** periods breach. **This works because** both stop one short spike from flipping the alarm back and forth (flapping), so you get fewer false notifications.
- **If** traffic follows daily or weekly patterns, **then** use an **anomaly detection alarm**. Machine learning (ML) builds an **expected-value band** from about **2 weeks** of history, including daily and weekly seasonality, and the alarm fires when the metric goes outside the band. **This works because** a **static threshold** cannot fit a value that is normal at one time of day but abnormal at another, so it fires falsely.
- **If** an **AWS Glue** job fails, **then** create an **Amazon EventBridge** rule on the **Glue Job State Change** event with state **`FAILED`**, sending to **Amazon Simple Notification Service (SNS)** or **AWS Lambda**. EventBridge routes AWS service events to targets. **This works because** a failure is a **discrete event**, so the rule reacts **immediately** with no polling, and AWS service events are free. Use alarms for threshold conditions over time instead.
- **If** a **dead-letter queue (DLQ)** gets any message, **then** alarm on the DLQ's **`ApproximateNumberOfMessagesVisible` > 0**. **This works because** a healthy DLQ is empty, so **any** message there means something failed and needs attention.
- **If** you want to test whether a **private** data API is available, **then** run a **CloudWatch Synthetics canary in a VPC**. A canary is a Node.js or Python script that runs on a schedule to test endpoints and reports `SuccessPercent` and `Duration`. **This works because** the canary runs inside **AWS Lambda** attached to your **Virtual Private Cloud (VPC)**, so it can reach private endpoints, such as an API behind an Application Load Balancer (ALB) or a private Amazon API Gateway.
- **If** operations need on-call handling, **then** connect the alarm to an **AWS Systems Manager Incident Manager response plan**. **This works because** Incident Manager turns the alarm into an **incident** with **runbooks**, **escalation plans** and **on-call** contacts, instead of just sending a message.
- **If** you want a single pane for many accounts, **then** build **dashboards in an OAM monitoring account** (CloudWatch cross-account observability, Observability Access Manager). **This works because** the monitoring account reads the **linked source accounts'** data, and its dashboards can show **cross-account and cross-Region** widgets in one place.

Verified from AWS docs on 2026-11-09 (CloudWatch pricing and quotas pages).
Unconfirmed (verify): composite alarm child limit; anomaly detection pricing; dashboard price; Synthetics per-run price; Logs-based alarms; alarm history retention; EC2 action list.

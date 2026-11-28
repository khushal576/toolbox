# AWS Config – 1. Recorder, configuration items, history, snapshots and queries

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS Config** records the **configuration of your AWS resources** over time, keeps the **relationships** between them, and lets you **evaluate** them against rules.
- It answers: **"What does this resource look like now, what did it look like before, and is it compliant?"**
- It is **not** an audit of API calls. **CloudTrail** answers "who called what API"; **Config** answers "what changed in the resource and when".
- Regional service: you turn it on **per Region per account** (or via Organizations / Control Tower).
- Pick it when: you need **change history**, **compliance rules**, **drift detection**, **configuration-based remediation**, evidence for auditors, or a base for **Security Hub** controls.
- Avoid / combine: for real-time threat detection use GuardDuty; for API audit use CloudTrail; for metrics use CloudWatch.
- DEA-C01: **4.5.4 view configuration changes (Config)**, **4.4 audit**, **4.1/4.5 compliance** of data stores (S3, Redshift, RDS, Glue, KMS encryption rules).

## B. Core concepts
- **Configuration item (CI)**: a point-in-time JSON record of a resource: type, ID, ARN, Region, AZ, creation time, tags, **configuration** (the resource's own attributes), **relationships** (for example EC2 → security group, volume, VPC), and **related CloudTrail event IDs**.
- **Configuration recorder**: the component that detects changes and creates CIs. **One recorder per Region per account**.
- **Recording frequency**:
  - **Continuous**: a CI is created every time a change is detected (billed per CI).
  - **Daily (periodic)**: at most one CI per resource per day (cheaper for noisy resources).
- **Recording strategy** (what to record):
  - **All current and future supported resource types** (default for new setups).
  - **Specific resource types** (inclusion list).
  - **All except selected types** (exclusion list).
- **Global resource types** (for example IAM users, roles, policies) are recorded in each Region where supported, or only in the **home Region** to avoid duplicates **(verify current behaviour; newer recorder records IAM in all Regions where chosen)**.
- **Delivery channel**: where Config delivers data. Needs an **S3 bucket** (history and snapshots) and optionally an **SNS topic** (change notifications). One delivery channel per Region.
- **Configuration history**: a file of CIs per resource, delivered to S3 about **every 6 hours**, per resource type and day.
- **Configuration snapshot**: a complete picture of all recorded resources at a point in time, delivered **on demand** (`DeliverConfigSnapshot`) or on a schedule (1, 3, 6, 12 or 24 hours).
- **Configuration stream**: change notifications as they occur through **SNS** (and EventBridge).
- **Resource timeline**: console view of configuration and **compliance** changes for one resource, linked to CloudTrail events.
- **Relationships**: Config shows direct dependencies (and the console shows a map). Useful for **impact analysis** before changing a security group or role.
- **Retention**: configuration items are kept **7 years by default**; you can set **30 days to 7 years** (2,557 days) in the retention configuration.
- **Resource coverage**: hundreds of resource types across compute, storage, database, networking, analytics (S3, Glue, Redshift, RDS, DynamoDB, Kinesis, Lambda, KMS, IAM, CloudFormation, EMR, SageMaker…). Check **Supported Resource Types**; new services are added regularly.
- **Third-party and custom resources**: record **custom resource types** (for example on-prem servers, GitHub repos) with the `PutResourceConfig` API (custom CIs; billed per custom CI).

## C. Setting up (what you must provide)
- **Prerequisites**: an **S3 bucket** (bucket policy lets `config.amazonaws.com` put objects with `bucket-owner-full-control`), optional **SNS topic** (policy lets Config publish), and an **IAM role** (service-linked role `AWSServiceRoleForConfig` is the default; or a custom role with read access to resources and write access to S3/SNS).
- **Recommended**: **KMS** encryption for the bucket (the Config role needs `kms:GenerateDataKey/Decrypt`), bucket versioning and **Object Lock** / lifecycle rules for retention, **cross-account** delivery to a central **log archive** bucket.
- **Organization setup**: Control Tower or a delegated administrator with **organization-wide recorder settings** (central configuration via Config **configuration recorders in organizations** or StackSets) **(verify current methods)**.
- **Turning off** the recorder stops new CIs; existing data stays per retention; rule evaluations stop for lack of new changes.
- **IAM permissions** to manage: `config:PutConfigurationRecorder`, `StartConfigurationRecorder`, `PutDeliveryChannel`, `DescribeConfigurationRecorders`, `GetResourceConfigHistory`, `SelectResourceConfig`, etc.
- **Config is eventually consistent**: a change may take minutes to appear.

## D. Reading history and doing audits
- **Console**: Resources → resource → **Configuration timeline** (diffs between CIs, compliance flags, related CloudTrail events).
- **API**: `GetResourceConfigHistory` (per resource, time-bound), `ListDiscoveredResources`, `BatchGetResourceConfig`, `GetDiscoveredResourceCounts`.
- **S3**: history/snapshot files are JSON (`.json.gz`) in a prefix like `AWSLogs/<acct>/Config/<region>/<yyyy>/<mm>/<dd>/ConfigHistory/…`. Query them with **Athena** (partition by date) for long-range analysis.
- **Last known good configuration**: retrieve the CI from before the problem for troubleshooting or rollback planning.
- **Who changed it?**: the CI lists the **CloudTrail event ID**; use CloudTrail (or CloudTrail Lake) for the actor.
- **Drift**: Config shows differences between CIs; **CloudFormation drift detection** is separate (but Config can record drift status as a resource).
- **Change management evidence**: Config timeline + CloudTrail + approvals = audit trail for SOC/PCI/HIPAA.

## E. Advanced queries
- **Advanced queries** use a **SQL-like syntax** (`SELECT ... WHERE ...`) over the **current** configuration state of recorded resources, using the **configuration schema** (JSON properties).
- Run in the **console**, CLI (`select-resource-config`) or API (`SelectResourceConfig`). Results are JSON.
- **Aggregator queries** (`SelectAggregateResourceConfig`) run across **accounts and Regions** from an aggregator.
- Examples: unencrypted EBS volumes, RDS instances without Multi-AZ, S3 buckets with public ACLs, Lambda functions on deprecated runtimes, security groups open to 0.0.0.0/0, resources by tag.
- **Saved queries**: store and share common queries (`PutStoredQuery`).
- Only supports a **subset of SQL** (no joins, limited functions, `GROUP BY` and aggregate functions supported) **(verify)**.
- **Not historical**: advanced queries show **current** state; for history use timeline/API/S3+Athena.
- Query result limits and pagination apply (limit up to 100 per page).
- **Integration**: use query results in **Systems Manager inventory**-like reports or export to dashboards.

## F. Events and notifications
- **EventBridge events** from Config: **Configuration Item Change**, **Config Rules Compliance Change**, **Config Rules Re-evaluation Status**, **Configuration Snapshot Delivery Completed**, **Config Configuration History Delivery Completed** **(verify names)**.
- **SNS** configuration stream: notifications for CI changes, compliance changes, delivery status.
- Typical wiring: EventBridge rule on **NON_COMPLIANT** change → Lambda / SNS / Security Hub / ticketing, or SSM Automation remediation.
- **CloudWatch metrics**: Config exposes few metrics; use EventBridge counts or CloudTrail metrics; evaluate with the **Config dashboard** **(verify)**.

## G. Data-engineering view (what to record and watch)
- **S3**: bucket policy, public access block, encryption, versioning, logging, lifecycle.
- **Glue/Athena/EMR/Redshift/RDS/DynamoDB/Kinesis/MSK/OpenSearch**: encryption at rest, public accessibility, logging, backups, VPC placement.
- **KMS keys**: rotation enabled, pending deletion, key policy changes.
- **IAM**: roles and policies (admin policies, unused roles).
- **Lambda**: runtime versions, VPC settings, public URLs.
- **CloudFormation stacks**: drift, termination protection.
- These drive the Config rules used by Security Hub and Control Tower detective controls.

## H. Exam skills mapping
- **4.5.4 View configuration changes (Config)**: view configuration changes.
- **3.3.2 Logging and monitoring for auditing and traceability**: configuration history for traceability.

## I. Scenarios: "If X → Y, because Z"
- **If** an auditor asks what a security group allowed on a given past date, **then** open the **AWS Config** **configuration timeline** for it in the console, or call the **`GetResourceConfigHistory`** API for that resource and time range. **This works because** the Config recorder saves a **configuration item (CI)**, a point-in-time JSON record of the resource, each time it changes. CIs are kept **7 years by default** (you can set 30 days to 7 years), so you can read the exact rules that were in place on that date.
- **If** you need to know who opened a port on a security group, **then** open the **AWS Config** configuration item (CI) for that change, take its **related AWS CloudTrail event ID**, and look the event up in **CloudTrail** (or CloudTrail Lake). **This works because** Config records **what** changed in the resource and when, while CloudTrail, the log of API calls, records **who** made the call. Config alone does not name the actor.
- **If** you want to find all unencrypted Amazon Elastic Block Store (EBS) volumes across many accounts, **then** create an **AWS Config aggregator** and run an **advanced query** on it (`SelectAggregateResourceConfig`). An aggregator collects configuration and compliance data from **many accounts and Regions** into one account and Region. **This works because** advanced queries use a **SQL-like** syntax over the recorded configuration, and aggregator queries cover all sources at once. The catch: advanced queries show only the **current** state, not history.
- **If** AWS Config costs are high because some resources change very often, **then** switch those high-churn resource types to **daily (periodic) recording**, or **exclude** them in the recording strategy. **This works because** **continuous** recording creates and bills a **configuration item (CI)** (about **$0.003** each) for every change, while daily recording creates **at most one CI per resource per day** (about **$0.012** each). Remember that Config rules cannot evaluate a type that is not recorded.
- **If** you need configuration data for several years and want to query it with SQL, **then** keep the **configuration history files** that AWS Config delivers to **Amazon S3**, add **S3 lifecycle** rules for old files, and create an **Amazon Athena** table over them, partitioned by date. Athena runs SQL directly on files in S3. **This works because** Config delivers history files (`.json.gz`) of configuration items to S3 about **every 6 hours (verify)**, so S3 holds the full change stream. Advanced queries cannot do this, as they show only current state.
- **If** a developer says "it worked yesterday", **then** compare yesterday's and today's **configuration items (CIs)** in the **AWS Config configuration timeline**. **This works because** the timeline shows the **differences** between CIs, plus related CloudTrail events, so you see exactly what changed.
- **If** on-premises servers or SaaS resources (for example GitHub repos) must be tracked, **then** record them as **custom resource types** with the **`PutResourceConfig`** API. **This works because** AWS Config accepts **custom configuration items (CIs)** that you send yourself. Each custom CI is billed.
- **If** you must be notified of every configuration change, **then** use the AWS Config **configuration stream** through **Amazon Simple Notification Service (SNS)**, or an **Amazon EventBridge** rule on **Configuration Item Change** events **(verify names)**. **This works because** Config publishes a notification each time it records a change. With EventBridge you can route the event on to AWS Lambda, SNS or a ticketing tool.
- **If** AWS Config is enabled but no data shows, **then** check that the **configuration recorder** is started, that the **recording strategy** includes the resource types you expect, and that the **delivery channel** (the S3 bucket and optional SNS topic) and the **Identity and Access Management (IAM)** role are set up correctly. **This works because** a stopped recorder creates no configuration items, and a bucket policy that does not let `config.amazonaws.com` write objects blocks delivery. Changes can also take minutes to appear, as Config is eventually consistent.

Verified from AWS docs on 2026-11-09 (What is AWS Config, Config pricing, service quota summary).
Unconfirmed (verify): global resource recording behaviour; exact EventBridge event names; advanced query SQL subset; CI delivery interval (6 h); organization recorder setup method; metrics availability; query page limit.

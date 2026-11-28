# Amazon AppFlow – 1. Basics, flows, sources, destinations and transformations

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **Amazon AppFlow** is a fully managed, **no-code** service that moves data between **SaaS applications** (Salesforce, ServiceNow, Zendesk, Slack, Google Analytics, SAP…) and **AWS services** (S3, Redshift, EventBridge…) or other targets (Snowflake).
- It is a **point-to-point copy** service with light transformation, not an ETL engine and not a CDC tool for databases.
- Fully managed, serverless; you pay **per flow run + per GB processed**.
- Pick it when:
  - You need to **ingest SaaS data into S3/Redshift** on a schedule or on demand without writing connector code.
  - You need **event-driven** capture of **Salesforce** change events/platform events.
  - You want **private** SaaS transfer over **PrivateLink** (supported SaaS only).
  - You want the output **cataloged in the Glue Data Catalog** and partitioned for Athena.
- Avoid it when:
  - Source/target is a **database needing CDC** → **DMS**.
  - You need heavy joins/transformations → **Glue/EMR/Redshift** after landing the data.
  - A needed SaaS app has no connector and no custom connector is worth building → write a Lambda/Glue custom job or use a Glue marketplace connector.
  - You need **sub-minute streaming** → Kinesis/MSK/EventBridge.
  - You need a very large one-time transfer (> 100 GB per run) → DataSync/Glue/Snow family.
- DEA-C01: **1.1.2 Read data from batch sources (…AppFlow)**; also touches 1.1.5 (schedules) and 4.x security.

## B. Core concepts
- **Connector**: the integration for one app (Salesforce, S3…).
- **Connection (connector profile)**: stored credentials/endpoint for an app; reused by many flows.
- **Flow**: source + destination + **trigger** + **field mappings/tasks** + optional filters/validations/masking. A **flow run** is one execution.
- **Source / destination**: each connector may be source-only, destination-only or both.
- **Trigger types**: **on demand**, **on event**, **on schedule**.
- **Task**: a transform step (map, filter, mask, validate, truncate…).
- **Private flow**: transfer over **AWS PrivateLink** instead of the internet (supported apps only).
- **Custom connector**: built with the **AppFlow Custom Connector SDK** (Python/Java) to reach private APIs, on-prem or other clouds.
- **Intermediate S3 bucket**: AppFlow stages data temporarily in an AWS-managed bucket (deleted after 7 days by lifecycle policy) during a run.
- Manage flows via console, API/CLI, **CloudFormation** (`AWS::AppFlow::Flow`, `AWS::AppFlow::ConnectorProfile`), and view runs in the **run history**.

## C. Supported connectors (know the shape, not the full list)
- **AWS and data services**: **Amazon S3**, **Amazon Redshift**, **Amazon RDS for PostgreSQL**, **Amazon EventBridge**, **Amazon Connect Customer**, Lookout for Metrics (legacy; Lookout for Metrics has been discontinued **(verify)**), **Snowflake**, **Google BigQuery**, **JDBC**, **Upsolver**, **SAP OData**.
- **CRM/support/ITSM**: **Salesforce**, Salesforce Pardot, Salesforce Marketing Cloud, **ServiceNow**, **Zendesk** (+ Chat, Sell, Sunshine), Freshdesk, Freshsales, HubSpot, Microsoft Dynamics 365, Zoho CRM, Pipedrive, Veeva, Kustomer, Intercom.
- **Collaboration/productivity**: **Slack**, Microsoft Teams, SharePoint Online, Jira Cloud, Asana, Smartsheet, Google Sheets/Calendar, Zoom, DocuSign Monitor.
- **Marketing/analytics**: Google Analytics (and GA4), Google Ads, Google Search Console, Marketo, Mailchimp, Facebook/Instagram/LinkedIn/Snapchat Ads, Amplitude, Mixpanel, Adobe Analytics, Singular.
- **Observability/dev**: Datadog, Dynatrace, GitHub, GitLab, CircleCI, Okta, Trend Micro.
- **Finance/commerce**: Stripe, PayPal, Braintree, QuickBooks Online, Coupa, WooCommerce, Infor Nexus.
- **Typical directions**:
  - Most SaaS apps are **source only**.
  - **S3, Redshift, Snowflake, EventBridge, Upsolver, Lookout** are common **destinations**.
  - **Salesforce, ServiceNow, Zendesk, Slack, SAP OData, Marketo, Zoho, HubSpot** (several) can also be **destinations** for write-back **(verify per connector)**.
  - **S3** can be a **source** too (S3 → Salesforce/Snowflake).
- The list changes often. Always check the connector page for **direction**, **auth type** and **limits**.

## D. Triggers
- **Run on demand**: manual (console/API `StartFlow`). Good for one-off or backfills with a custom **date filter**.
- **Run on schedule**: recurring. The **minimum frequency depends on the source** (many sources allow 1 minute; some, such as Marketo, Singular, TrendMicro, are hourly/daily — see limits).
  - **Full transfer**: copies a **snapshot of all records** each run.
  - **Incremental transfer**: copies only **new/changed records since the last successful run**, using a **timestamp field** you choose (created date vs last modified).
  - **First incremental run pulls the last 30 days** of data. For a different history window, run **on demand with a filter** first, then edit the flow to a schedule.
  - **Offset option**: shifts the window back by up to **< 10 hours** (default 0) to catch late-stamped records.
- **Run on event**: starts when the source emits a **change event**; available only for apps that send events (mainly **Salesforce Change Data Capture and Platform Events**, also Zendesk/Marketo/Slack/ServiceNow where supported **(verify)**).
- Event data can also be sent to an **EventBridge partner event bus** (Salesforce) so rules can route events to Lambda/Step Functions/SQS.
- Flows have a state: **active / draft / suspended / deleted**; scheduled and event flows must be **activated**.
- A schedule needs a **start time**, optional **end time** and a **time zone**.
- Failed runs can be **retried by the schedule** next time; the incremental cursor only advances after a **successful** run.

## E. Destination options (S3 focus)
- **File format**: **CSV**, **JSON** (or JSON lines), **Parquet** (best for Athena/Redshift Spectrum).
- **Aggregation**: none (one file per record batch), **single file per run**, or by **file size**.
- **Folder structure**: bucket prefix plus a **path hierarchy** (execution ID, schema version) and **date partitions** (`DAY`, `HOUR`, `MONTH`, `YEAR`, `MINUTE`) so Athena can prune.
- **Filename prefix** options keep different flows apart.
- **Glue Data Catalog**: AppFlow can **create/update a table** for the S3 data (with a table prefix) so Athena can query it. Needs a Glue database and an IAM role for AppFlow.
- **Encryption**: S3 objects use **SSE-KMS** with an AWS managed or customer managed key (your choice in the flow).
- **Redshift destination**: loads through **S3 + COPY** (AppFlow uses an intermediate S3 bucket and an IAM role that Redshift can assume). Works with **provisioned and Serverless**.
- **EventBridge destination**: sends each record as an event to a **partner event bus**.
- **Snowflake**: needs an S3 stage and storage integration.
- **Error handling**: choose **stop the flow** on the first destination error, or **continue and write failed records to an S3 error prefix**.
- Schema is **flattened to columns**; complex nested SaaS objects map to flattened fields.

## F. Transformations in the flow (tasks)
- **Field mapping**: map all fields directly, or **map selected fields** and rename them.
- **Filters**: keep/drop records by field value (equals, not equals, greater/less than, contains…). Multiple filters combine with **AND** **(verify)**.
- **Validations**: check a field is not null, numeric, positive, etc.; on failure, the record is dropped/treated per **error handling**.
- **Masking**: hide field values (full or first/last N characters) so PII is not stored in plain form.
- **Truncate** and **concatenate** fields; **add a computed value** such as a source-data timestamp.
- **Arithmetic** on numeric fields (add, subtract, multiply, divide) **(verify)**.
- No joins across sources, no aggregation, no lookups. Heavy transformation happens **after** landing in S3 (Glue, Athena CTAS, Redshift).
- **Partitions/aggregation** settings are about **file layout** to speed up queries, not transformation.
- **PII**: mask early; also consider **Macie** scans on the landing bucket.

## G. AppFlow versus nearby tools
| Need | AppFlow | DMS | Glue | Transfer Family / DataSync | Kinesis / MSK |
|---|---|---|---|---|---|
| Source type | **SaaS apps** | Databases | Databases, files, many | Files | Streams |
| Coding | **None** | None | Spark/Python | None | Producers |
| CDC | Limited (SaaS change events) | **Yes (DB CDC)** | Via zero-ETL/streaming | No | n/a |
| Transform | Light (map, filter, mask) | Table mapping | **Full** | None | Stream processors |
| Schedule | Built-in | Tasks | Triggers | Tasks | Continuous |
| Best for | Salesforce/ServiceNow → S3/Redshift | RDS/Oracle → S3/Redshift | Complex ETL | File moves | Real-time |
- **AppFlow vs Glue custom connectors**: AppFlow is **no-code and SaaS-focused**; Glue connectors (JDBC, marketplace) run inside **Glue jobs** and allow arbitrary transforms.
- **AppFlow vs Lambda + API**: Lambda gives total control but you write paging, auth refresh, retries and rate-limit handling. AppFlow handles OAuth refresh, paging and limits.
- **AppFlow vs DMS**: use **DMS** for **databases**; use **AppFlow** for **SaaS objects**.
- **AppFlow vs EventBridge API destinations**: API destinations push events **to** HTTP endpoints; AppFlow **pulls/pushes bulk records** between apps and AWS.
- **AppFlow vs Transfer Family**: SFTP/FTPS/FTP file transfer vs SaaS API data movement.
- **AppFlow vs zero-ETL integrations**: zero-ETL covers **AWS database → Redshift/Lakehouse** (and some SaaS apps via Glue zero-ETL); AppFlow covers broader SaaS connectors **(verify current Glue SaaS zero-ETL overlap)**.

## H. Typical architectures
- **Salesforce → S3 (Parquet, daily partitions, Glue catalog) → Athena/QuickSight**: scheduled incremental flow, `LastModifiedDate` as the cursor.
- **ServiceNow incidents → Redshift**: scheduled flow to Redshift staging table, then SQL for dimensional model.
- **Salesforce change events → EventBridge → Lambda/Step Functions**: event-triggered flow publishing to a partner bus for real-time reactions.
- **Slack channel history → S3** for compliance or analytics, then **Comprehend/Bedrock** for text insights.
- **S3 → Salesforce** write-back of scored leads (file up to **125 MB per CSV**, **500 MB** per run for Salesforce import).
- **Orchestration**: start a flow from **Step Functions** (`appflow:startFlow`, SDK integration) or **EventBridge Scheduler**; react to **flow-run completion events** on EventBridge (`AppFlow End Flow Run Report`) to start Glue/Athena **(verify event names)**.
- **Data lake**: land raw → Glue crawler/catalog → transform with Glue/dbt → publish.

## I. Exam skills mapping
- **1.1.2 Read data from batch sources (S3, Glue, EMR, DMS, Redshift, Lambda, AppFlow)**: SaaS batch sources.
- **1.1.5 Set up schedulers (EventBridge, Airflow, time-based) for jobs and crawlers**: schedule vs event vs on-demand; full vs incremental.
- **1.2.3 Integrate data from multiple sources**: integrating SaaS data.
- **2.2.3 Glue crawlers and schema discovery**: Glue Data Catalog integration.

## J. Scenarios: "If X → Y, because Z"
- **If** the business wants Salesforce opportunities copied into Amazon S3 every hour, **then** use a **scheduled, incremental Amazon AppFlow flow** to S3. Amazon AppFlow is a no-code service that moves data from SaaS apps into AWS. The flow runs **every hour** and writes **Parquet** files into **date partitions** (folders per day or hour). **This works because** an **incremental transfer** copies only records that are new or changed since the last successful run, using a timestamp field such as `LastModifiedDate`, and you write no connector code.
- **If** the first load must include Salesforce history older than **30 days**, **then** first **run the flow on demand with a date filter** that covers the full history, and afterwards edit the flow to **run on a schedule**. **This works because** the **first incremental run only pulls the last 30 days**; an on-demand run with your own filter sets any history window you need.
- **If** records whose timestamps are stamped late are being missed, **then** add a **time offset** of **less than 10 hours** (the default is 0) to the incremental flow. **This works because** the offset shifts each run's time window back, so records with lagging timestamps still fall inside it. The catch: overlapping windows can create **duplicate rows**, so dedupe downstream.
- **If** you need a near-real-time reaction to Salesforce changes, **then** use an **event-triggered flow** (run on event) or send the events to an **Amazon EventBridge partner event bus**, where rules route them to AWS Lambda, AWS Step Functions or Amazon Simple Queue Service (SQS). **This works because** an event flow starts as soon as Salesforce emits a **Change Data Capture** or **Platform Event**, while schedules only run in batches.
- **If** data must not cross the public internet, **then** use a **private flow** built on **AWS PrivateLink**, which connects to the SaaS app over the AWS network. **This works because** the traffic stays on the **AWS network** instead of the internet. The limit: it works only for **supported SaaS apps** that expose a PrivateLink-compatible endpoint.
- **If** personally identifiable information (PII) fields must not land in S3 in clear text, **then** add a **masking task** to the flow, which hides the full value or the first/last N characters. **This works because** masking runs inside the flow, **before** the data is written to the destination.
- **If** Amazon Athena (SQL queries on S3) must query the data right away, **then** write **Parquet** files with **date partitions** and let AppFlow **create/update a table in the AWS Glue Data Catalog**. **This works because** AppFlow builds the catalog table itself, and Athena can **prune** (skip) partitions it does not need. AppFlow needs a Glue database and an Identity and Access Management (IAM) role for this.
- **If** the source is an Oracle or PostgreSQL database that needs change data capture (CDC), **then** use **AWS Database Migration Service (DMS)**. **This works because** AppFlow is built for **SaaS objects**, with only limited **JDBC** and **Amazon RDS for PostgreSQL** connectors and no database CDC, while DMS does database CDC.
- **If** you need to join Salesforce data with Zendesk data, **then** **land both in S3** with two flows and do the join later in **Athena**, **AWS Glue** or **Amazon Redshift**. **This works because** each AppFlow flow has **one source and one destination** and does no joins, aggregation or lookups; heavy transformation happens after landing.
- **If** a SaaS app has no AppFlow connector, **then** **build a custom connector** with the **AppFlow Custom Connector SDK** (Python/Java, run on AWS Lambda), or write an AWS Glue job instead. **This works because** AppFlow can only call APIs it has a connector for, and the SDK lets you add one for private APIs, on-premises systems or other clouds.
- **If** a flow run would move more than **100 GB**, **then** **split the flow** using filters or time ranges, or use another tool such as AWS DataSync or AWS Glue. **This works because** **100 GB per run** is a **hard limit** that cannot be raised.
- **If** a flow must be started by a workflow instead of by its own schedule, **then** make it an **on-demand flow** and start it from **AWS Step Functions** with the `appflow:startFlow` SDK integration (or from Amazon EventBridge Scheduler). **This works because** on-demand flows can be started at any time through the **API** (`StartFlow`).

Verified from AWS docs on 2026-11-03 (what is AppFlow, flow triggers, service quotas, supported connectors list, data protection, pricing).
Unconfirmed (verify): which connectors can be destinations; event-trigger support per app; AND-combination of filters; arithmetic/concatenate task availability; Lookout for Metrics retirement status; Glue SaaS zero-ETL overlap; AppFlow EventBridge run-report event names; JSON vs JSON-lines output option; Redshift Serverless support details.

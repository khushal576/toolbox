# Amazon AppFlow – 2. Security, private connectivity, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Identity and access (IAM)
- AppFlow uses **IAM** for who can create/run flows and connections.
- Managed policies: **AmazonAppFlowFullAccess** (create/manage flows, connections; includes the Secrets Manager permissions AppFlow needs) and **AmazonAppFlowReadOnlyAccess**.
- Typical IAM actions: `appflow:CreateFlow`, `UpdateFlow`, `DeleteFlow`, `StartFlow`, `StopFlow`, `DescribeFlow`, `ListFlows`, `CreateConnectorProfile`, `UseConnectorProfile`, `DescribeConnectors`.
- **`appflow:UseConnectorProfile`** is the permission to **use a stored connection** in a flow; restrict it so teams only use their own connections.
- **Tag-based access** works on flows and connector profiles (ABAC) **(verify exact condition keys)**.
- Creating a connection needs **Secrets Manager** permissions limited by condition (`secretsmanager:CreateSecret` with name `appflow!*`, called via `appflow.amazonaws.com`; `PutResourcePolicy` only for secrets owned by AppFlow).
- **AppFlow writes to your S3/Redshift/Glue using its own service access**:
  - **S3 destination**: you must add an **S3 bucket policy** that allows the **AppFlow service principal** (`appflow.amazonaws.com`) to `PutObject`, `GetBucketAcl`, `ListBucket`, `AbortMultipartUpload` etc. (the console can add it).
  - **Glue Data Catalog**: AppFlow needs permission to create/update tables (role or service access).
  - **Redshift**: IAM role for the cluster to read from the intermediate S3 bucket, and a database user/IAM role to run COPY.
- You cannot use **IP allow-listing on the S3 bucket policy** to restrict to AppFlow IPs, because AppFlow reaches S3 through a **VPC endpoint**.
- **Service-linked role**: AppFlow uses a service-linked role for some actions **(verify)**.

## B. Credentials and connections
- A **connection** stores OAuth tokens, API keys, passwords. AppFlow **encrypts them with KMS** and stores them in **Secrets Manager** in **your account** (secret names start `appflow!`).
- AppFlow **refreshes OAuth tokens** automatically for supported apps.
- **Deleting a connection deletes its metadata permanently.** Flows using it will fail.
- Rotating a SaaS secret requires **updating the connection** (edit connection) so the flow keeps working.
- Do **not** put secrets in flow names, tags or free-text fields; those can show up in logs and billing records.
- OAuth connections need the SaaS-side **connected app** and **callback URL** (the console shows the AppFlow redirect URL).
- Some apps need **IP allow-listing on the SaaS side**; use the AWS-published IP ranges for AppFlow in your Region **(verify)** or use **PrivateLink** where supported.

## C. Encryption
- **In transit**: TLS **1.2** (1.3 recommended) for all transfers.
- **At rest**:
  - Connection data: **KMS + Secrets Manager**.
  - Data in the **intermediate S3 bucket** (staging during a run) is encrypted with the key you pick for the flow; the bucket **deletes objects after 7 days** (lifecycle).
  - S3 destination: **SSE-KMS** with AWS managed or **customer managed key**.
- **Customer managed key (CMK)** is recommended: you control rotation and can disable the key. When you pick a CMK, **AppFlow attaches a resource policy/grant** so it can use the key.
- If the CMK is **disabled or deleted**, flows fail.
- Scan landing buckets with **Macie** for sensitive data; use **masking** in the flow for known PII fields.

## D. Private connectivity
- **Private flows**: for supported SaaS (for example Salesforce, ServiceNow, Zendesk, Slack, Marketo, Snowflake, SAP via PrivateLink) the traffic uses **AWS PrivateLink** and does not traverse the public internet. You create the connection as **private** and AppFlow sets up the VPC endpoint service (partner side) **(verify supported list)**.
- Private flows need the SaaS to expose a **PrivateLink-compatible endpoint** (for example Salesforce Private Connect, Snowflake PrivateLink).
- **Salesforce event/Change Data Capture + EventBridge** can also use the private option.
- **JDBC / RDS PostgreSQL connectors** run in your VPC: AppFlow connects through a **VPC endpoint service/connector in your VPC**, so the database does not need to be public. Needs security groups and subnet routes **(verify exact mechanism)**.
- **Custom connectors** can run in your VPC via Lambda with VPC config to reach on-prem or private APIs.
- **AppFlow itself is a regional service** with public and FIPS endpoints (`appflow.<region>.amazonaws.com`, `appflow-fips.<region>…` in US Regions). You can use a **VPC interface endpoint** for the AppFlow API **(verify)**.

## E. Audit and governance
- **CloudTrail** logs AppFlow API calls (create/update/delete/start flow, create connection).
- **Flow run history** in the console/API (`DescribeFlowExecutionRecords`): status, records processed, bytes, error messages, start and end time.
- **EventBridge** receives AppFlow **flow-run events** (start/end report) so you can alert or chain steps **(verify event names)**.
- **CloudWatch metrics** for flows: runs started/succeeded/failed, records processed, run duration **(verify metric names)** under `AWS/AppFlow`.
- **Lake Formation / Glue** permissions control who queries the cataloged tables in S3.
- **Tagging** flows and connections helps cost allocation and ABAC.

## F. Cost
- **Flow runs**: about **$0.001 per successful flow run** (us-east-1 list). Runs that only check for new data **still count**.
- **Data processed**: about **$0.02 per GB** (as used in the pricing examples) **(verify rate by Region)**.
- **Extra concurrent processes** (SAP connectors can use multiple) are billed as **additional flows**.
- **No upfront fees or minimums**. No free tier is advertised on the pricing page.
- Other charges: **S3** requests/storage, **KMS** requests, **Glue Data Catalog**, **Secrets Manager** (the stored connection secrets), **PrivateLink** (endpoint hours and data processing), downstream Glue/Athena/Redshift.
- Example: 1,000 small transfers/day ≈ **$1/day** in flow runs → about **$30/month**; 10 GB twice a week ≈ **$1.61/month**.
- **Ways to cut cost**:
  - **Lower schedule frequency**; each scheduled run costs even if no new data.
  - Use **incremental** (not full) transfers.
  - **Filter** rows and **map only needed fields**.
  - Use **Parquet** and **aggregation** to cut S3 request/query cost.
  - Avoid many tiny flows when one flow with filters would do.
  - Delete unused flows/connections (secrets cost).

## G. Limits and numbers
| Item | Value |
|---|---|
| Flow run size | **100 GB** per run (hard) |
| Flows per Region | **1,000** (adjustable) |
| Concurrent flow runs | **1,000** (adjustable) |
| Monthly flow runs | **10,000,000** (adjustable) |
| Connector profiles | **100** (adjustable) |
| Scheduled flow start rate (per account/Region) | **1 run per minute** overall (hard) |
| Marketo flow run size | **20 MB** per run |
| Amplitude flow run size | **25 MB** per run |
| ServiceNow records per run | **100,000** |
| Salesforce import size per run | **15 GB** |
| Salesforce export (write to Salesforce) | **500 MB** per run; S3 source CSV **≤ 125 MB each** |
| Salesforce event size | **1 MB** |
| EventBridge event size | **256 KB** (larger → summary event with S3 pointer) |
| Google Analytics | **9 dimensions**, **10 metrics** per run |
| Schedule frequency by source | Many 1 min; **Marketo, Singular, Trend Micro hourly; Amplitude, Google Analytics daily** (per quota page) |
| Incremental first run | pulls **30 days** |
| Incremental offset | **< 10 hours** |
| Intermediate bucket retention | **7 days** |
| TLS | **1.2** required |
| Regions | 16 listed incl. us-east-1/2, us-west-1/2, af-south-1, ap-south-1, ap-northeast-1/2, ap-southeast-1/2, ca-central-1, eu-central-1, eu-west-1/2/3, sa-east-1 |
- Per-source rate limits mean a **flow can be throttled** or the schedule rejected if too frequent.

## H. Monitoring and troubleshooting (symptom → cause → fix)
- **Flow run failed: authentication error** → expired/rotated credentials or revoked OAuth → edit the connection, re-authorize.
- **AccessDenied writing to S3** → bucket policy lacks AppFlow principal, wrong KMS key policy → fix bucket/key policy.
- **No new data in incremental runs** → timestamp field choice, late-stamped records, clock lag → change cursor field or add offset.
- **Duplicate rows in S3** → full transfers or overlapping offset windows → use incremental, dedupe downstream (`MERGE`, Glue job, or Athena view on latest).
- **Run exceeded size/time** → > 100 GB or source-specific cap (Marketo 20 MB, ServiceNow 100k records) → add filters, split flows by time range.
- **Schedule rejected** → frequency lower than source minimum → use a coarser schedule.
- **Throttled by SaaS API** → API rate limits at the source → lower frequency, stagger flows.
- **Validation dropped records** → validation rules or masks mismatch → check error output prefix in S3; choose "continue and write failures".
- **Glue table not created/updated** → missing Glue permissions or database → grant AppFlow role Glue actions.
- **Redshift COPY failure** → IAM role not attached to Redshift, schema mismatch → fix role and column types.
- **Private flow cannot connect** → PrivateLink endpoint not accepted/approved on SaaS side or wrong DNS → fix connection settings with the SaaS admin.
- **Flow stopped itself** → source disabled the event/subscription, or connection deleted → re-activate flow, recreate connection.
- **Cost jump** → very frequent schedules, many flows → reduce frequency and consolidate.

## I. Exam skills mapping
- **1.1.2 Read data from batch sources (S3, Glue, EMR, DMS, Redshift, Lambda, AppFlow)**: SaaS ingestion.
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: PrivateLink and bucket policy for the AppFlow principal.
- **4.2.2 Store credentials (Secrets Manager, Parameter Store)**: connection credentials in Secrets Manager.
- **4.3.2 Encryption keys (KMS)**: KMS keys.

## J. Scenarios: "If X → Y, because Z"
- **If** compliance requires encryption keys under your own control, **then** use an **AWS Key Management Service (KMS) customer managed key (CMK)** for the flow and the S3 destination. **This works because** with a CMK you control **rotation** and can **disable** the key, and AppFlow **attaches a grant** (resource policy) so it can use the key. The catch: if the CMK is disabled or deleted, **flows fail**.
- **If** the SaaS provider offers PrivateLink and traffic must stay private, **then** create the connection as **private** and use a **private flow** over **AWS PrivateLink**. **This works because** the traffic stays on the **AWS network** and never crosses the public internet. The limit: the SaaS must expose a PrivateLink-compatible endpoint, such as Salesforce Private Connect **(verify supported list)**.
- **If** the flow cannot write to Amazon S3 (AccessDenied), **then** add an **S3 bucket policy** that lets the **AppFlow service principal** (`appflow.amazonaws.com`) call `PutObject`, `ListBucket` and similar actions, and give it access in the **KMS key policy**. **This works because** AppFlow writes to your bucket with **its own service access**, not your user's permissions. You cannot restrict this by IP address, because AppFlow reaches S3 through a VPC endpoint.
- **If** teams must not use each other's Salesforce connection, **then** restrict **`appflow:UseConnectorProfile`** in Identity and Access Management (IAM) to each team's own connection Amazon Resource Name (ARN), and optionally by tags **(verify exact condition keys)**. **This works because** `UseConnectorProfile` is the permission to **use a stored connection** (its credentials) in a flow.
- **If** a scheduled flow costs too much, **then** **lower the schedule frequency** and use **incremental** instead of full transfers. **This works because** AppFlow bills about **$0.001 per flow run**, and runs that only check for new data **still count**; incremental runs also process fewer GB (about **$0.02 per GB** **(verify rate by Region)**).
- **If** you must move **300 GB** from a SaaS app, **then** **split it into several flows by date filters**, each under **100 GB**. **This works because** a single flow run is limited to **100 GB**, and this limit is **hard** (cannot be raised).
- **If** data should be queryable right after it lands, **then** write **Parquet** files with **date partitions** and let AppFlow create the table in the **AWS Glue Data Catalog**. **This works because** Amazon Athena can **prune** (skip) partitions it does not need, and AppFlow creates/updates the table itself, so **no Glue crawler** is needed.
- **If** a downstream job must run after every successful flow, **then** catch the AppFlow **flow-run completion event** in **Amazon EventBridge** and use a rule to start **AWS Step Functions** or an **AWS Glue** job **(verify event names)**. **This works because** AppFlow sends flow-run events (start/end report) to EventBridge, so steps chain **without polling**.
- **If** records contain emails and phone numbers, **then** **mask** those fields in the flow and scan the landing bucket with **Amazon Macie**, a service that finds sensitive data in S3. **This works because** masking stops known personally identifiable information (PII) from landing in clear text, and Macie catches sensitive values you did not know about.
- **If** a SaaS credential is rotated, **then** **edit the connection** in AppFlow with the new secret. **This works because** flows use the credentials stored in the connection (kept in AWS Secrets Manager); otherwise runs fail with an **authentication error**.
- **If** incremental runs miss rows that were updated late, **then** increase the **offset** (to **less than 10 hours**). **This works because** the offset shifts the run's time window back so late-stamped rows fall inside it.
- **If** you need a one-off backfill of **2 years** of data, **then** **run the flow on demand with a date filter** for those 2 years, then switch it to an **incremental schedule**. **This works because** the **first incremental run only fetches 30 days**, while an on-demand run with a filter can cover any window.

Verified from AWS docs on 2026-11-03 (what is AppFlow, flow triggers, endpoints and quotas, data protection, pricing, supported connectors).
Unconfirmed (verify): ABAC condition keys; AppFlow service-linked role; supported list for private flows; JDBC/RDS private connection mechanism; VPC interface endpoint for the AppFlow API; CloudWatch metric names and EventBridge flow-run event names; per-Region data processing price; whether the 1-run-per-minute quota is per account or per source; AWS published IP ranges usage.

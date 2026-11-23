# AWS CloudTrail – 2. CloudTrail Lake, event data stores, queries and Insights

Short notes. Each point is a fact you can be asked about.

## A. What CloudTrail Lake is
- **CloudTrail Lake** is a managed **event data store** for CloudTrail (and other) events with **SQL queries**. You don't manage S3, Athena tables or partitioning.
- Events are stored in an **immutable** columnar format (queryable with SQL, based on a **Trino/Presto-like** engine) for the retention you choose.
- Use it for **fast ad-hoc investigations** across many accounts/Regions and **long retention** without building an Athena pipeline.
- DEA-C01: **4.4.3 CloudTrail Lake**, **4.4.4 analyze logs**.
- Compared to trails + Athena: Lake is simpler and managed but **costs more per GB ingested**; trails + S3 + Athena are cheaper at scale but need setup.

## B. Event data stores (EDS)
- An **event data store** holds events chosen by **advanced event selectors**; you pick the **event category**:
  - **CloudTrail events**: management, data, network activity, Insights.
  - **Events from outside AWS / other AWS sources** via **channels** (audit events from integrations like Okta, Datadog partner events, custom apps using `PutAuditEvents`, up to **100 events or 1 MB per request**).
  - **AWS Config configuration items** (config items EDS) **(verify)**.
- **Scope**: single-Region or **multi-Region**; account-level or **organization-level** (events from all accounts).
- **Quota**: **10 event data stores per Region** (includes all lifecycle stages); **25 channels**; **10 concurrent queries**; **100 dashboards per Region**, **10 widgets per dashboard**.
- **Retention options (pricing tiers)**:
  - **One-year extendable retention**: ingest priced per GB, retention **extendable up to 10 years** (extra cost after year one). Good for < 25 TB/month.
  - **Seven-year retention**: fixed 7 years, tiered ingestion pricing. Good for high volume.
  - Retention can be **7 days to 3,653 days (10 years)** for the extendable class; seven-year class is fixed **(verify)**.
- **Termination protection** is on by default; deleting goes through a **pending deletion** state (7–30 days recoverable) **(verify)**.
- **Encryption**: AWS-owned key by default; optional **customer managed KMS key** (cannot change later).
- **Ingest options**: start ingesting from now, or **copy trail events** from an S3 trail into the EDS (import) for historical analysis.
- **Federation**: **Lake query federation** registers an EDS in the **Glue Data Catalog** + **Lake Formation**, so you can query it from **Athena** and join with other data.
- **Stop ingestion** to pause costs; query existing data still allowed.
- **Lake dashboards**: prebuilt/custom dashboards (management activity, S3 data events, errors, top users, Insights) with SQL widgets; refresh limits.
- **Event aggregation/enrichment** options can filter before ingest to reduce cost via advanced selectors.

## C. Queries
- **SQL SELECT** over the EDS ID as the table name: `SELECT eventName, userIdentity.arn FROM <eds-id> WHERE eventTime > '2026-01-01 00:00:00' AND eventName = 'DeleteBucket'`.
- **Always filter by `eventTime`** (and partition-like fields) to limit scanned data and cost.
- Supports nested fields with dot notation, `GROUP BY`, `ORDER BY`, functions, `LIMIT`; no DDL.
- Query run **asynchronously** (`StartQuery`, `DescribeQuery`, `GetQueryResults`); **save results to S3** (up to a large size) and **download**.
- **Concurrent queries**: 10; a query has a time limit (up to about an hour) **(verify)**.
- **Sample queries** in the console: failed console logins, IAM policy changes, S3 deletes, root activity, access denied per user, top API callers.
- **AI-assisted query generation** (natural language to SQL) is available in the console **(verify)**.
- **Result retention**: query history kept for a limited time (e.g., 7 days) **(verify)**.
- **Cost**: **about $0.005 per GB scanned** per query.

## D. Lake cost model (indicative)
- **Ingestion** (CloudTrail management/data/network events): **$0.75/GB** for one-year extendable; **$2.50/GB** for the first 5 TB/month, **$1.00/GB** next 20 TB, **$0.50/GB** above 25 TB for seven-year retention.
- **Ingestion of other auditable sources**: **$0.50/GB** (one-year extendable).
- **Extended retention** after year one: **about $0.023/GB/month** (up to 10 years); included in seven-year class.
- **Queries**: **$0.005/GB scanned**.
- **Free trial**: 30 days, 5 GB ingestion and 5 GB scanned for new customers **(verify)**.
- **Recommendation**: use one-year extendable if monthly ingest is under about 25 TB; seven-year for larger volume.
- **Cost levers**: ingest **only needed event categories**; use advanced selectors to exclude noisy events; filter by time in queries; use one organization EDS; stop unused EDS; keep high-volume data events in S3 trails instead and use Athena.

## E. Lake vs trails + Athena (exam comparison)
| Aspect | CloudTrail Lake | Trail → S3 → Athena |
|---|---|---|
| Setup | **Managed**, SQL immediately | Create table, partition projection, Glue/CTAS |
| Storage | Managed EDS (immutable) | Your S3 bucket |
| Retention | up to 10 years (extendable) / 7 years | Unlimited (S3 lifecycle) |
| Cost | Ingestion + query per GB | S3 storage + Athena per TB scanned (cheaper at scale) |
| Multi-account | Organization EDS | Organization trail |
| Non-AWS events | **Yes (channels)** | No |
| Integrity | Immutable store | Digest files + Object Lock |
| Real-time alerts | Via EventBridge/Insights | Via CloudWatch Logs / EventBridge |
| Best for | Investigations, quick analytics | Cheap long-term archive, big data scans |
- **Use both**: a trail to S3 (cheap archive, compliance copy) and Lake for fast investigations of recent months.

## F. CloudTrail Insights
- **Insights** detects **unusual write-API call volume** (**ApiCallRateInsight**) and **unusual error rates** (**ApiErrorRateInsight**) in management events (and data events for some types).
- It builds a **baseline over the previous 7 days** and generates an Insights event when activity deviates, with start/end and statistics.
- Insights events are delivered to the **same trail's S3 bucket** (`CloudTrail-Insight/` prefix) and to Lake/CloudWatch Logs/EventBridge.
- **Billing**: per events analyzed per insight type (about $0.35 per 100,000 management events).
- **Delay**: Insights events may take several minutes after the anomaly starts.
- **Use cases**: detect a runaway automation, credential misuse bursts, sudden `RunInstances` or `DeleteObject` spikes, throttling storms.
- **Requires** at least one trail with management events enabled.

## G. Network activity events and other new sources
- **Network activity events** (for **VPC endpoints**): record all API calls made through the endpoint, including **denied by endpoint policy/`aws:SourceVpce`** - aids data-perimeter troubleshooting.
- **AWS service activity events** and **agent/AI events** are added over time **(verify)**.
- **Config items in Lake** link configuration state with events.
- **Audit events from partners** are integrated using **channels** and ARNs; ingest priced as "other auditable sources".

## H. Operations and troubleshooting
- **No results** → time range outside retention/ingest start, EDS not ingesting the event type, wrong event category, case/field mismatches.
- **Query too slow/expensive** → missing `eventTime` filter; narrow with `eventSource`/`eventName`.
- **Concurrent query limit** → queue; wait or cancel.
- **Missing accounts in organization EDS** → org integration not enabled, delegated admin not registered, event selector excludes accounts.
- **Cannot query from Athena** → federation not enabled, Lake Formation permissions missing.
- **Trail copy import stuck** → S3 permissions, wrong Region, KMS.
- **EDS deletion blocked** → termination protection on; disable first.
- **Cost surprise** → big data-event ingestion; switch noisy data events to S3 trail.
- **Monitoring**: CloudWatch metrics for Lake ingestion (bytes) **(verify)**, billing by usage type.

## I. Limits (summary)
| Item | Value |
|---|---|
| Event data stores per Region | **10** |
| Channels | **25** |
| Concurrent queries | **10** |
| Dashboards / widgets | **100 / 10** |
| `PutAuditEvents` | **100 events or 1 MB** per call |
| Advanced selector conditions | **500** |
| Retention (extendable class) | up to **10 years** |
| Seven-year class | **7 years** fixed |
| Query price | **$0.005 / GB scanned** |

## J. Exam skills mapping
- **4.4.3 CloudTrail Lake**: CloudTrail Lake.
- **4.4.4 Analyze logs (Athena, Logs Insights, OpenSearch)**: analyze logs.
- **3.3.8 Analyze logs (Athena, EMR, OpenSearch, Logs Insights)**: SQL over audit data.

## K. Scenarios: "If X → Y, because Z"
- If security wants to run SQL on 12 months of org-wide API activity with no pipeline → **CloudTrail Lake organization event data store**, because it is managed and queryable immediately.
- If data volume is huge and cost matters → **trail to S3 + Athena (Parquet, partition projection)**, because S3 + Athena is cheaper per TB.
- If you also need non-AWS audit events in the same store → **Lake channels (integration)**, because trails can't ingest external events.
- If you want to join CloudTrail data with other lake tables → **Lake federation via Glue/Lake Formation + Athena**, because it exposes the EDS in the catalog.
- If a sudden API burst might indicate compromise → **enable Insights**, because it flags unusual call or error rates.
- If a query scans too much → **add `eventTime` range and `eventSource` filter**, because scan cost is per GB.
- If compliance requires 7 years of logs with high volume → **seven-year retention EDS (or S3 trail with lifecycle)**, because tiered pricing/lifecycle fit large volumes.
- If you need immutable evidence → **Lake (immutable) or S3 Object Lock + digests**, because both resist tampering.

Verified from AWS docs on 2026-11-09 (CloudTrail quotas, CloudTrail pricing, CloudTrail concepts).
Unconfirmed (verify): retention bounds per class; deletion recovery window; AI-assisted query generation; config-item event data stores; query time limit; free trial amounts; Lake CloudWatch metrics; query history retention; Insights baseline window and data-event Insights.

# AWS Data Exchange – Third-party data sharing, subscriptions and delivery

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS Data Exchange (ADX)** lets you **find, subscribe to and use third-party data**, and lets providers **publish and share data** without building delivery and entitlement systems.
- Two main flows:
  - **Data grants** (direct sharing): a **sender** creates a **data grant** for a **receiver's AWS account ID**; the receiver **accepts** and gets access for a set duration. Any AWS account can send grants (no Marketplace seller registration).
  - **AWS Marketplace data products**: a **provider** (registered AWS Marketplace seller) lists a **product** with **offers** (public or private, price, duration, subscription agreement); a **subscriber** subscribes and gets **entitlements**.
- Also supports **Open Data on AWS** data sets (public; usable with or without an AWS account).
- Data sets, revisions and assets are **Regional** resources. Products appear in one global Marketplace catalog.
- **Supported Regions** (11): us-east-1, us-east-2, us-west-1, us-west-2, eu-west-1, eu-west-2, eu-central-1, ap-southeast-1, ap-southeast-2, ap-northeast-1, ap-northeast-2.
- Pick it when: you need **licensed external data** (market, weather, geospatial, healthcare, demographics) or want to **share data with other AWS accounts** with controlled entitlement and automated updates.
- Avoid it when: sharing **inside your own organization** (use Lake Formation + RAM, S3 policies, Redshift data sharing), or you need real-time streaming delivery.
- DEA-C01: **1.1 ingestion from external sources**, **4.5.7 governance and data sharing patterns** (ADX vs Lake Formation vs Redshift datashare vs Clean Rooms).

## B. Core concepts
- **Data set**: a curated collection of assets owned by the provider. **Five data set types**:
  - **Files**: S3 objects imported as assets; subscribers **export to S3** or download.
  - **API**: provider's REST API via **API Gateway**; subscribers call it through ADX (SigV4) or download the OpenAPI spec.
  - **Amazon Redshift**: provider's **datashare**; subscribers get **read-only query access** without ETL.
  - **Amazon S3**: subscribers read data **in place** from the provider's S3 buckets through ADX-managed access (no copy).
  - **AWS Lake Formation data permission** (**Preview**): subscribers get access to tables in the provider's data lake.
- **Revision**: a versioned container of assets (a point-in-time update). A **finalized** revision is immutable. Providers publish new revisions over time.
- **Asset**: a file, API, datashare, S3 location or Lake Formation resource in a revision.
- **Data grant**: the unit of exchange for direct sharing (data set + details + recipient account + duration).
- **Product**: the unit of exchange in Marketplace; contains product details, **offers**, and one or more data sets.
- **Offer**: terms the subscriber agrees to: price, duration, **Data Subscription Agreement**, refund policy. Types: **public**, **private** (custom for one buyer), **BYOS** (bring your own subscription).
- **Auto-export**: when a new revision is published, ADX **automatically exports** assets to your S3 bucket using a key pattern. Good for pipelines.
- **Events**: ADX emits **EventBridge** events (for example new revision published, auto-export job completed/failed) **(verify exact names)**.
- Providers can require **subscription approval**.

## C. How data lands in your platform (subscriber)
- **Files**: auto-export to a **raw zone** in S3 → Glue crawler/catalog → Athena, Redshift Spectrum, Glue ETL.
- **S3 data access**: read directly from the provider's data using the ADX-created access point; no storage duplication; permissions managed through the subscription.
- **Redshift datashare**: appears as a database from a datashare in your Redshift (provisioned or Serverless); you pay compute, the provider pays storage.
- **API**: call from Lambda/Glue/Step Functions using SigV4 against the subscription's API endpoint.
- **Orchestration**: EventBridge "revision published" → Step Functions → Glue job → data quality check → promote to curated.
- **Governance**: land licensed data in a **dedicated bucket/account**, tag with license terms, restrict redistribution (Lake Formation LF-Tags, SCP/RCP), keep CloudTrail auditing.
- **Schema drift** between revisions: use Glue Data Quality and crawler schema-change settings.
- As a provider, **scan with Macie** for PII before publishing.

## D. Provider side
- Steps: create **data set** → create **revision** → import **assets** (from S3, signed URL, API Gateway, Redshift datashare, S3 data access) → **finalize** → publish **product** or send **data grant**.
- To **sell** products, register as an **AWS Marketplace seller** and follow **publishing guidelines** (permitted data types; AWS reviews products). Data grants need only an AWS account.
- Billing and disbursement run through **AWS Marketplace** (seller fees apply).
- **S3 data access** providers keep data in their own bucket; KMS-encrypted data needs key grants for ADX access.
- **Redshift** providers share via a datashare configured for ADX.
- **API** providers set throttling/quotas on their API Gateway stage.
- APIs: **AWS Data Exchange API** (data sets, revisions, assets, jobs) and **AWS Marketplace Catalog API** (products/offers).

## E. Security and access control
- IAM actions: `dataexchange:*` (for example `GetDataSet`, `CreateRevision`, `CreateJob`, `StartJob`, `SendApiAsset`) and `aws-marketplace:Subscribe`, `Unsubscribe`, `ViewSubscriptions`.
- AWS managed policies exist for full, subscriber, provider and read-only access **(verify names)**.
- **Encryption**: TLS in transit; exports can use **SSE-S3 or SSE-KMS** on your bucket.
- **Cross-account** entitlement is handled by ADX, not by manual bucket policies.
- **Audit**: CloudTrail records subscription, job and export actions; S3 data events/access logs for S3 data access.
- **Control who can subscribe**: IAM permission on `aws-marketplace:Subscribe`, plus Marketplace **private marketplace** allow-lists.
- Respect license terms: subscribers must follow the Data Subscription Agreement (no unauthorized redistribution).

## F. Cost
- **Subscribers** pay the **provider's subscription fee** through the AWS bill, plus normal AWS costs: S3 storage/requests for exports, Redshift compute, Athena/Glue, data transfer.
- **Data grants**: no ADX fee for the grant itself; you pay for storage/compute you use.
- **Providers** pay Marketplace seller fees and costs for storage/requests/transfer **(verify)**.
- **Cost levers**: export only needed revisions/assets; lifecycle old revisions to colder storage; prefer **S3 data access** or **Redshift datashares** over copying big data; use private offers; cancel unused subscriptions.

## G. Limits
- Quotas (data sets per account, revisions per data set, assets per revision, grants, auto-export jobs) are in the **Service Quotas** console under `dataexchange` **(verify values; not confirmed)**.
- Object size follows S3 limits (up to 5 TB per object) **(verify)**.

## H. Data Exchange vs other sharing options
| Need | ADX | Lake Formation + RAM | Redshift data sharing | S3 sharing (policy / access point / Access Grants) | AWS Clean Rooms |
|---|---|---|---|---|---|
| Share with **external parties** | **Yes** | Yes (cross-account) | Yes (cross-account) | Yes | Yes (no raw data exposed) |
| Monetization / licensing | **Yes** | No | No | No | No |
| Fine-grained table/column control | Via source | **Yes** | Schema/table level | Prefix level | Query rules |
| Entitlement lifecycle (expiry, renewal) | **Yes** | Manual | Manual | Manual | Collaboration-based |
| Updates | **Revisions + auto-export** | Live | Live | Live | Live |
- **Clean Rooms** lets parties analyze combined data **without sharing raw data**; ADX **delivers** data.
- **Inside one organization**: Lake Formation, Redshift datashares or S3 policies.
- **Buy/sell external data**: ADX.

## I. Troubleshooting
- **Auto-export fails** → bucket policy or KMS key does not allow ADX; wrong Region.
- **Cannot call API product** → missing IAM permission or SigV4, wrong endpoint, provider throttling.
- **Redshift datashare missing** → wrong Region/namespace type, provider has not authorized the datashare.
- **S3 data access denied** → access point/KMS issue, your IAM lacks S3 permissions.
- **No new revisions** → provider has not published, subscription expired, or no auto-export rule.
- **Cost questions** → check the Marketplace bill separately from S3/Redshift usage.

## J. Exam skills mapping
- **1.1.2 Read data from batch sources (S3, Glue, EMR, DMS, Redshift, Lambda, AppFlow)**: external batch sources.
- **4.5.1 Data sharing permissions (Redshift data sharing)**: data sharing permissions.
- **4.5.7 Governance framework and data sharing patterns**: sharing patterns.

## K. Scenarios: "If X → Y, because Z"
- If analysts need licensed weather data in the lake daily → **ADX Files data set with auto-export to S3 + EventBridge-triggered ETL**, because new revisions export automatically.
- If a partner account needs your dataset for 90 days → **ADX data grant with a duration**, because no Marketplace listing is needed.
- If you want vendor data without copying it → **Redshift datashare or S3 data access data set**, because both avoid ETL and duplicate storage.
- If data is shared inside your organization → **Lake Formation/RAM or Redshift datashare**, because Marketplace adds needless overhead.
- If two companies want joint analytics without exposing raw data → **AWS Clean Rooms**, because ADX delivers data, it does not hide it.
- If you want to sell a dataset → **register as a Marketplace seller and publish an ADX product**, because Marketplace handles billing and entitlement.
- If an auto-export keeps failing → **fix the S3 bucket policy and KMS grants for ADX**, because it writes into your bucket.
- If a pipeline must start on a new revision → **EventBridge rule → Step Functions**, because ADX emits events.
- If you publish personal data by mistake risk → **scan with Macie first**, because publishing guidelines and privacy laws apply.

Verified from AWS docs on 2026-11-04 (What is AWS Data Exchange: data grants, products, five data set types, Regions, related services).
Unconfirmed (verify): service quota values; EventBridge event names; managed policy names; provider cost model; S3 data access mechanics; Lake Formation data set status; Redshift datashare prerequisites; VPC endpoint support.

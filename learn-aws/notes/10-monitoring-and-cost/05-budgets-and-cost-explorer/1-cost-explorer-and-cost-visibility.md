# Cost Explorer and cost visibility – 1. Cost Explorer, tags, categories, anomaly detection and exports

Short notes. Each point is a fact you can be asked about.

## A. The cost tools map (what to use when)
- **Billing and Cost Management** is the home console for all of these. All the cost APIs (Cost Explorer, Budgets, Data Exports, Cost Optimization Hub) live in **us-east-1** (global control plane).
- **Cost Explorer**: look at and analyze **past** and **forecast** cost and usage. Interactive graphs, filters, reports.
- **AWS Budgets**: set a **target** and get **alerts/actions** when you cross it (file 2).
- **Cost Anomaly Detection**: ML finds **unusual** spend and alerts you (no target needed).
- **Cost allocation tags + Cost Categories**: label spend by team/project/environment so the other tools can split it.
- **Data Exports (CUR 2.0)**: the **most detailed** raw billing data in S3 for Athena/QuickSight/Redshift.
- **Cost Optimization Hub / Compute Optimizer / Trusted Advisor**: **recommendations** to save money.
- **Billing Conductor**: custom **pro forma** pricing and chargeback views (does not change the real bill).
- **Savings Plans / Reserved Instances**: discount commitments. Cost Explorer shows their **utilization and coverage**.
- **CloudWatch billing alarm** (legacy): alarm on the `EstimatedCharges` metric. Only in **us-east-1**, needs "Receive billing alerts" turned on, whole-account total only. Budgets is the better, richer tool.
- **Pricing Calculator**: estimate **future** cost before you build. **Price List API**: raw public prices.
- Simple rule: **see it → Cost Explorer; cap it → Budgets; spot surprises → Anomaly Detection; split it → tags/categories; query everything → CUR 2.0; shrink it → Optimization Hub.**

## B. What Cost Explorer is
- A **free UI** (no charge) to view and analyze cost and usage with graphs, tables and saved reports.
- Uses the **same dataset** as the Cost and Usage Report (CUR), so numbers match billing.
- **Enable it once** (cannot be turned off afterwards). It is turned on automatically when you create your first budget. Needs permissions such as `ce:*`, `ce:GetCostAndUsage`.
- After enabling: **current month in about 24 hours**, the other months take a few days. Data refreshes **at least once every 24 hours** (some may arrive later).
- Default view: up to **13 months of history** + current month + **forecast up to 18 months** (**12 months** is the older number; the current docs say 18).
- **Granularity**:
  - **Monthly** and **daily** by default (13 months).
  - **Multi-year data** (monthly, up to **38 months**) is an **opt-in** setting.
  - **Hourly** and **resource-level** data cover only the **last 14 days** and are **opt-in**.
- **Main controls**: time range, granularity, **Group by** (service, linked account, region, usage type, instance type, tag, cost category, API operation, purchase option, platform, database engine, billing entity, and more), **filters** (include/exclude dimensions), and the **cost view**.
- **Cost types (metrics)**:
  - **Unblended**: the cost when it is used (default view for many people). Includes upfront fees on the day charged.
  - **Blended**: an **average rate** across the organization's accounts for the same usage (hides who got RI/Savings Plans benefit).
  - **Amortized**: **spreads** upfront and recurring reservation/Savings Plan fees over the term. Best to see the **true daily cost** of commitments.
  - **Net unblended / net amortized**: after **discounts** (EDP, private pricing, credits as configured).
  - **Normalized usage**: instance hours normalized to the same size (for RI planning).
  - **Usage quantity**: the amount of usage instead of dollars.
- **Charge-type filters**: you can include or exclude **credits, refunds, taxes, support fees, upfront reservation fees, recurring fees**. A common trap: "Why is my cost lower?" → credits applied, or a different cost type selected.
- **Saved reports**: save a configured view. Up to **300 saved reports** per account. **Preconfigured reports** exist (monthly by service, daily costs, RI and Savings Plans reports).
- **Compare time periods** and **explain a change** (cost comparison / Amazon Q Developer can analyse drivers).
- **Export**: download as **CSV**. For full detail use **Data Exports** (section H).
- **Cost Explorer API** (`ce`): programmatic access (`GetCostAndUsage`, `GetCostForecast`, `GetDimensionValues`, `GetTags`, `GetReservationUtilization`, `GetSavingsPlansUtilization`, rightsizing recommendations...).
  - **Each paginated API request costs $0.01**. A script that polls every minute adds up.
  - Use CUR/Data Exports or cache results for dashboards instead of calling the API heavily.
- **Who sees what** (AWS Organizations):
  - **Management (payer) account**: sees **all** accounts' cost.
  - **Member account**: sees **its own** cost only (unless the management account allows broader access with **billing views**).
  - Management account can turn **"Cost Explorer linked account access"** off/on for members (IAM and account settings control this).
  - **Billing views** (custom views) let you share cost data of selected accounts/tags with others.
- **Forecast**: predicts future cost from historical usage patterns. Needs **enough history** (**a few months**; Budgets forecast alerts need about **5 weeks**). It is an estimate, not a promise; it changes with usage.
- **Reservation / Savings Plans reports**:
  - **Utilization**: how much of what you bought you actually used (low = wasting).
  - **Coverage**: how much of your eligible usage is covered by commitments (low = paying on-demand).
  - **Recommendations**: Cost Explorer suggests **RIs** and **Savings Plans** to buy (based on a lookback of 7/30/60 days, 1- or 3-year term, payment option). A refresh limit of **3 per 24 hours** applies to Savings Plans recommendations per consolidated billing family.

## C. Granular data and multi-year data (opt-in)
- Configure in **Cost Management preferences** (**management account**; member accounts if allowed).
- **Resource-level data at daily granularity**: cost per resource (for example per EC2 instance or per S3 bucket), last **14 days**, **free**.
- **Hourly data for all services** (no resource detail), last **14 days**: **paid** (see below).
- **EC2 resource-level data at hourly granularity**, last **14 days**: **paid**.
- **Multi-year data**: monthly granularity, up to **38 months**. Opt-in. Some sources say it turns off after a period without access **(verify)**.
- **Hourly cost** is billed about **$0.01 per 1,000 usage records per month** (a usage record is one line item for a resource and usage type) **(verify current page)**. Daily resource-level and multi-year are not charged this way.
- Not available when an account is in a **Billing Conductor** billing group (pro forma view) or a billing-transfer group.
- Data from before you opt in is **not backfilled** for hourly data; it starts from enabling.

## D. Cost allocation tags
- **Cost allocation tags** let you break costs down by your own labels (team, project, env) in Cost Explorer, Budgets, CUR/Data Exports.
- **Two kinds**:
  - **User-defined** tags (`Project=Phoenix`).
  - **AWS-generated** tags with the **`aws:`** prefix (for example `aws:createdBy`, `aws:cloudformation:stack-name`). You cannot create `aws:` tags yourself.
- **A tag does nothing for billing until you ACTIVATE it** as a cost allocation tag (Billing console → Cost allocation tags, or `aws ce update-cost-allocation-tags-status`). Only the **management account** can activate in an Organization.
- **Delay**: after activation it can take **up to 24 hours** to appear.
- **Not retroactive by default**: untagged past usage stays untagged. A **backfill** feature applies your **current active/inactive tag status to past months, up to 12 months**.
  - Only the **management account** can request it.
  - **One request per 24 hours** and not while another backfill is running.
  - It only shows tag values that were **really on the resource** in those months. It cannot invent tags that did not exist.
- **Limits**: up to **500 active cost allocation tag keys** per payer account (adjustable). Tag keys/values are **case-sensitive** (inconsistent `Env` vs `env` = two keys). Keys up to 128 characters, values up to 256 **(verify)**.
- **Not all costs are taggable**: untaggable resources, shared services (support, data transfer, taxes, some Marketplace) show as "no tag". Use **Cost Categories split charges** to allocate them.
- **Best practices**: define a **tagging standard**, enforce with **AWS Organizations tag policies**, **SCPs/IAM conditions** (`aws:RequestTag`, `aws:TagKeys`), **AWS Config** rule `required-tags`, **Tag Editor**, IaC (CloudFormation/CDK propagate tags), and **tag Lambda/Glue/EMR/EKS resources** (EKS needs split cost allocation data for pod-level).
- **Budgets** can filter on an active tag, so tags give **per-team budgets**.
- Tags on **budgets themselves** (for IAM access control) are different and **do not appear in cost data**.

## E. Cost Categories
- **Cost Categories** map cost and usage into **custom groups** (for example "Team A", "Production", "Shared services") using **rules**, without changing tags or account structure.
- **Rule dimensions**: linked **account**, **service**, **region**, **usage type**, **charge type**, **cost allocation tag**, and **another cost category**. Operators: equals, starts with, ends with, contains, absent.
- **Rule order matters**: the **first matching rule** wins. Unmatched cost goes to a **default value** (for example "Unallocated").
- **Inherited values**: take the category value **dynamically from a tag value** or an **account name** (not account ID) instead of writing one rule per team.
- **Split charge rules**: **allocate shared costs** (source value) to target values with **proportional**, **fixed** or **even** split.
  - A value can be a **source only once** and cannot be both source and target.
  - **Up to 10 split rules** per category.
  - **Split results appear only on the cost category details page**; they do **not** flow into Cost Explorer, CUR or Budgets **(verify)**.
- **Where used**: group/filter in **Cost Explorer**, filter **Budgets**, **Cost Anomaly Detection** monitors, **CUR/Data Exports** columns.
- **Retroactive**: when you create or edit a category it is applied to the **current month and up to 12 months back** (rules are re-evaluated on past data) **(verify)**.
- **Quotas**: up to **50 Cost Categories** per payer account; **100 rules** in the UI, **500** through API/JSON.
- Created in the **management account** (Organizations).
- **Tags vs Cost Categories**: tags label the resource going forward (needs discipline, not retroactive except backfill); categories **regroup existing data** and fix messy or missing tags with rules.

## F. Cost Anomaly Detection
- **ML-based** service that learns normal spend and flags **unusual** spend (considers weekly/monthly **seasonality** and **natural growth**). **Free** to use **(verify)**.
- **Monitors** decide **what** is evaluated:
  - **AWS services** (AWS-managed, one per account: each service on its own).
  - **Linked account**.
  - **Cost allocation tag**.
  - **Cost category**.
  - Quotas: **500 customer-managed monitors**; AWS-managed monitors **1** per type; **100 alert subscriptions**.
- **Alert subscriptions** decide **who/how**:
  - **Threshold**: a **dollar impact** (absolute) or **percentage** (above expected) to alert on.
  - **Frequency**: **individual alerts** (sent via **SNS**), **daily summary** or **weekly summary** (**email**).
  - **Channels**: **email**, **SNS topic** (then **Amazon Q Developer in chat applications** for Slack/Chime/Teams), and **EventBridge** events for automation (Lambda ticketing).
- **Root cause**: ranked by dollar impact across **service, account, Region, usage type**.
- **Timing**: runs about **3 times a day** on **net unblended** data from Cost Explorer, so detection can lag **up to 24 hours**. A **new monitor** needs about **24 hours**; a **new service** needs about **10 days** of history before anomalies show.
- **Does not monitor** most **AWS Marketplace** charges (except third-party Bedrock models). Use **Budgets** (billing entity filter) for those.
- Not available for accounts using **billing transfer** views.
- Anomaly Detection **finds** problems; **Budgets** enforces **limits**. Use both.

## G. Recommendation tools (cost optimization side)
- **Cost Explorer rightsizing recommendations**: EC2 (idle/underused) using **Compute Optimizer**'s engine; shows **only savings-positive** suggestions (savings ≥ $0). Needs opt-in at the management account for Organization-wide.
- **AWS Compute Optimizer**: EC2, Auto Scaling groups, EBS, Lambda, ECS on Fargate, RDS, and idle resources. Shows all options, including ones that **cost more** (for performance). Uses **CloudWatch metrics** (optional enhanced infrastructure metrics).
- **Cost Optimization Hub**: **one place** for recommendations across accounts/Regions (rightsizing, idle resources, Savings Plans/RIs, Graviton, storage tiers). **De-duplicates savings** (no double counting) and imports Compute Optimizer. AWS recommends it over Cost Explorer for rightsizing in new setups.
- **Trusted Advisor**: cost optimization checks (idle load balancers, underused EBS, unassociated Elastic IPs); full checks need **Business/Enterprise** support.
- **Savings Plans vs Reserved Instances**:
  - **Compute Savings Plans** (flexible across EC2, Fargate, Lambda).
  - **EC2 Instance Savings Plans** (family in a Region).
  - **SageMaker Savings Plans**.
  - **Reserved Instances** for EC2/RDS/Redshift/OpenSearch/ElastiCache (no Savings Plan for these data stores except via RIs/Database Savings Plans where available **(verify)**).
  - 1-year or 3-year, **No/Partial/All upfront**. Commitment is a **$/hour**; unused commitment is **wasted**.
  - **Redshift RIs, RDS RIs, OpenSearch RIs, ElastiCache reserved nodes, DynamoDB reserved capacity** are the data-engineering favourites.

## H. Data Exports and the Cost and Usage Report (CUR)
- **AWS Data Exports** creates recurring exports to **S3**. Types (**current docs**):
  - **Standard export tables**: **CUR 2.0**, **Cost optimization recommendations**, **FOCUS 1.2/1.0 with AWS columns**, **Carbon emissions**.
  - **Cost and usage dashboard** (pre-built **QuickSight** dashboard).
  - **Legacy CUR** (the older Cost and Usage Reports, separate API).
- **CUR 2.0** is the **recommended** way to get detailed cost data. It supports **SQL-like column selection and row filtering** (CLI/SDK), a consistent schema, **nested columns**, and fewer columns than legacy. Can remove sensitive accounts/columns.
- **CUR** = the **most granular** billing data: one line per usage, hourly or daily or monthly granularity, optional **resource IDs**, tags, and **cost category** columns. Updated **at least once a day** (up to three times).
- **Formats**: **Parquet** (recommended) and CSV (gzip/zip). Parquet is best for **Athena**. Files land in your **S3 bucket** with a bucket policy allowing `billingreports.amazonaws.com`/`bcm-data-exports.amazonaws.com`.
- **Integration**: **Athena** (the Glue crawler/CloudFormation template AWS provides), **Redshift**, **QuickSight/Quick**. The AWS **CUDOS / Cloud Intelligence Dashboards** use CUR.
- **Split cost allocation data** (opt-in): allocates ECS/EKS **shared compute** cost to tasks and pods in CUR (**resource-level for containers**).
- **FOCUS** = the open **FinOps Open Cost and Usage Specification** (standard cross-cloud columns).
- **Choose**:
  - Quick view or one-off → **Cost Explorer**.
  - Automated, huge, joined with other data, or chargeback at line level → **CUR 2.0 + Athena**.
  - Recurring dashboards on a budget → CUR 2.0 (Parquet) + Athena/Quick, **not** the paid Cost Explorer API in a loop.
- **Costs**: S3 storage + Athena scans + Glue; CUR itself has **no charge**.
- **Legacy CUR** still works; **migrate** to CUR 2.0 (schemas differ).
- **S3 Lifecycle** old CUR files and **partition** by month for cheap Athena queries.

## I. Governance and multi-account cost management
- **Consolidated billing** (Organizations): one bill for all accounts. **Volume discounts** and **Reserved Instance / Savings Plans sharing** across accounts (can be disabled per account).
- **Management account** controls Cost Explorer settings, tag activation, Cost Categories, Budgets for others, and Savings Plans/RI sharing.
- **Billing views / Billing Conductor**: share filtered cost data and show **custom pricing** (pro forma) for chargeback/reseller. Billing Conductor changes the **view, not the real bill**. Free for billing-transfer with AWS managed pricing; otherwise per-account pricing **(verify)**.
- **IAM**: Cost Explorer and Budgets need explicit permissions. Since the 2023 IAM change, old `aws-portal:*` actions are replaced by fine-grained **`ce:*`, `budgets:*`, `billing:*`, `cur:*`, `account:*`** actions. Use **IAM Identity Center** groups for finance users and an **SCP** to protect billing settings.
- **Free Tier** tracking: Billing console Free Tier page + **Free Tier alerts** (usage nearing limits). Budgets can alert on free tier usage.
- **Cost allocation for data platforms**: tag **Glue jobs, EMR clusters, Redshift clusters, Athena workgroups** (per-workgroup cost and query limits), **Lambda**, **Kinesis**, **S3 buckets** (with S3 Storage Lens/prefix tags), **MSK**, **OpenSearch**. Athena **workgroup tags** are a classic data-cost-by-team answer.

## J. Scenarios: "If X → Y, because Z"
- If finance asks "which service grew most last month?" → **Cost Explorer, group by service, compare periods**, because it is free and interactive.
- If a tag was added to resources but cost reports show no tag → **activate it as a cost allocation tag (management account)**, then wait up to 24 hours, because tags are not used until activated.
- If you need old months to show a tag that is now active → **tag backfill (up to 12 months)**, because activation is not retroactive by default; it only helps where the tag really existed.
- If tagging is messy and cannot be fixed fast → **Cost Categories with rules**, because they regroup existing cost by account/service/tag patterns.
- If a shared cost (support, networking, shared Redshift) must be split among teams → **Cost Category split charge rule** (proportional/fixed/even), because tags cannot label shared items.
- If you need to know why Lambda cost doubled yesterday → **Cost Anomaly Detection** with a service monitor and **individual alerts to SNS**, because it spots unusual spend and gives root cause.
- If daily/weekly summary emails are enough → alert subscription with **daily/weekly** frequency; if you want real-time → **individual alerts via SNS/EventBridge**, because only SNS supports individual alerts.
- If you need line-item cost joined with your own data → **Data Exports (CUR 2.0) in Parquet + Athena**, because Cost Explorer cannot be joined and the API charges per request.
- If a script polls the Cost Explorer API every minute for a dashboard → **move to CUR 2.0/Athena or cache**, because each paginated request costs $0.01.
- If you need hourly cost for the last 2 weeks → **enable hourly granularity (paid) in preferences**, because the default is daily.
- If you need cost per EC2 instance → **resource-level data (daily free / hourly paid)**, because the default hides resource IDs.
- If amortized cost differs from unblended cost → reservation/Savings Plan **upfront fees**, because unblended shows the fee on the purchase day and amortized spreads it.
- If a member account cannot see Cost Explorer data → **management account has it disabled for members**, because linked-account access is a payer setting.
- If you need to know whether Savings Plans are wasted → **Savings Plans utilization report**, because utilization below 100% means unused commitment.
- If a team wants a rightsizing list → **Cost Optimization Hub / Compute Optimizer**, because they use CloudWatch metrics and do not double count.
- If you want a hard stop on spend → **not Cost Explorer or Anomaly Detection**; use **Budgets actions/SCPs** (file 2), because those two only report.

Verified from AWS docs on 2026-11-01 (Cost Explorer overview, granular data, Anomaly Detection, Data Exports, quotas, Budgets pages used for Cost Explorer interaction).
Unconfirmed (verify): current Cost Explorer forecast horizon wording (docs say 18 months); hourly granularity price (about $0.01 per 1,000 usage records per month); multi-year data auto-disable behavior; Cost Category retroactive window (12 months) and split-charge visibility (only on the details page); Cost Anomaly Detection being free of charge; tag key/value length limits; whether Billing Conductor pricing is per account; Savings Plans/RI coverage for data stores; the exact reservation recommendation lookback options.

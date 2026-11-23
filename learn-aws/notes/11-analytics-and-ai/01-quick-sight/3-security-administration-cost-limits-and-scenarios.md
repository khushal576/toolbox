# Amazon Quick Sight – 3. Security, administration, cost, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Identity options
- The **identity method is chosen when the account is created**; changing it later generally means **unsubscribing and re-creating** the account **(verify)**.
- **IAM Identity Center** (recommended): SSO with users and **groups** from Identity Center (synced from Okta, Entra ID, etc.); group membership drives roles and sharing.
- **IAM federation / SAML 2.0** (Okta, Entra ID, ADFS, Ping): user assumes an IAM role, and Quick creates the user on **first sign-in** (**just-in-time provisioning**).
- **JIT permissions**: the federated role needs `quicksight:CreateReader`, `quicksight:CreateUser` (author) or `quicksight:CreateAdmin` to self-provision at that role level **(verify action names)**.
- **IAM users/roles** can also be registered as Quick users (`RegisterUser` with `IdentityType=IAM`).
- **Active Directory** (AWS Managed Microsoft AD or **AD Connector** to on-prem AD): **Enterprise**; you map **AD groups** to admin/author/reader roles.
- **Quick-native users** ("email users"): invited by email, password managed by Quick; simplest, no SSO.
- **Groups** (Enterprise): use for sharing, RLS rules (`GroupName`), folder permissions; manage with `CreateGroup`, `CreateGroupMembership`.
- **Catch**: RLS group rules work only with **Quick groups or Microsoft AD groups** (docs).
- **Trusted identity propagation** via Identity Center can pass the user's identity to **Redshift/Lake Formation** so source-side permissions apply per user **(verify)**.

## B. Roles and editions
- **Roles**: **Reader**, **Reader Pro**, **Author**, **Author Pro**, **Admin**, **Admin Pro**.
- **Reader**: view and interact with dashboards, subscribe to reports/alerts.
- **Author**: connect data, build datasets, analyses, dashboards, topics.
- **Admin**: author rights + manage users, SPICE, security settings, subscriptions.
- **Pro roles** add **generative BI** (build by asking, executive summaries, data stories, Q&A) and **Quick suite** capabilities in Quick Regions.
- **Enterprise-only security**: RLS, CLS, AD, groups, namespaces, VPC connections, embedding, customer managed KMS keys (see file 1 table).
- **Assume Enterprise** in exam questions about security, embedding, hourly refresh or ML.

## C. Account-level access to AWS resources
- **Manage Quick → Security & permissions**: choose which AWS services Quick may use (**Athena, S3 buckets, Redshift, RDS, IoT, Timestream**...).
- Quick uses a **service role** (`aws-quicksight-service-role-v0`) plus attached policies to reach those services.
- **Least privilege**: select **specific S3 buckets**, not "all buckets"; allow **write** only for the Athena results bucket.
- **Custom IAM role**: you can tell Quick to use **your own IAM role** instead of the default service role for AWS resource access **(verify)**.
- **Per-data-source role** (e.g. Athena with a role ARN) to separate access by team **(verify)**.
- **IAM policies on people/apps** control who can call Quick APIs (`quicksight:*`), e.g. restrict `RegisterUser`, `GenerateEmbedUrlFor*`, `CreateIngestion`, `DeleteDataSet`.
- **IAM policy can restrict Quick sign-up/subscription** to admins (`quicksight:Subscribe`) **(verify)**.
- **Asset permissions** (inside Quick) are separate from IAM: data sources, datasets, analyses, dashboards, topics, themes, folders each have **owner/viewer** permissions.
- **Trap**: an IAM admin is **not automatically** able to see a dashboard; asset permissions still apply (except API calls that change permissions) **(verify)**.

## D. Row-level security (RLS)
- **RLS (Enterprise)** limits **which rows** each user/group sees in a dataset.
- **User-based rules**: a **permissions (rules) dataset** with a **UserName** or **GroupName** column (or **UserARN/GroupARN**) plus one column per restricted field (e.g. `region`, `segment`).
- **Only one identity column is used at a time**; the identity column can have **any name** you choose; field names and values are **case-sensitive** (docs).
- **Default deny**: a user/group with **no rule** sees **no rows** (docs).
- **NULL or empty in a restricted column** = **all values** for that field (docs).
- **Empty rules are skipped**: a row where **every column is empty** (including the user column) is ignored, so it can't grant everyone access (docs).
- **Comma in a value** splits it into several values; wrap in **double quotes** to keep a literal comma (docs).
- **Dataset owners still see all data**; **readers** see only their allowed rows (docs).
- **Changes apply immediately** to existing users once you "Apply and activate" (docs).
- **Only one active rules dataset per dataset**; adding a second overwrites the first (docs).
- **Limits** (docs): max **999 rule records per user** (direct + via groups); for SPICE datasets max **192,000 filter values per user per restricted field**.
- **Catch**: going over the filter-value limit can make **visuals fail**; add a coarser grouping column to shorten the list (docs).
- **RLS works only on text fields** (string/char/varchar), **not dates or numbers** (docs) → cast to string if needed.
- **Rows with NULL/empty in the restricted field** in the main dataset are **ignored** when rules apply (not shown to restricted users) (docs).
- **Rules dataset flag** (since 2025): create rules datasets as **"New rules dataset"** or `UseAs: RLS_RULES`; the flag **can't be changed later**; rules datasets need **string-only columns** and **fail ingestion** on invalid rows instead of skipping them (docs).
- **Rules source**: SPICE/file (update by **overwriting** rules) or **direct query** table (updates as the cache refreshes) (docs).
- **Catch**: deleting a **file-based** rules dataset before removing it locks restricted users out; you must pick new rules in **Permissions** (docs).
- **Child datasets** inherit parent RLS; you can **add** rules but **not remove** inherited ones; such children must be **direct query** (docs).
- **Anomaly detection is not supported** on RLS datasets (docs).
- **Tag-based RLS**: for **anonymous embedding**; map **session tag keys** to columns; values come from `SessionTags` in the embed call (file 2).
- **Permissions policy**: "Grant access to dataset" is the standard mode; a deny-style policy may exist **(verify)**.
- **Performance**: RLS adds a filter to every query; keep rules small and use group rules instead of thousands of user rows.

## E. Column-level security (CLS) and other restrictions
- **CLS (Enterprise)** restricts **which columns** users/groups can see in a dataset; default = **everyone sees all columns** (docs).
- **Restricted datasets/analyses** show a **lock icon** (docs).
- **Effect on visuals** (docs): most visuals that use a restricted column are **hidden** for users without access; they **can't create or edit** visuals with those fields.
- **Tables/pivot tables** (docs): restricted column in **Rows/Columns** → visual hidden; in **Values** → the table shows, with **"Not Authorized"** in those cells.
- **Enabling CLS on an analysis/dashboard needs administrator access** (docs).
- **RLS + CLS together** = row and column filtering on the same dataset.
- **Data masking**: no built-in dynamic masking → mask with **calculated fields** in the dataset or at the **source** (Redshift dynamic data masking, Lake Formation cell filters, Athena views).
- **Object-level security** (hide whole sheets/visuals per user) is **not a separate feature** **(verify)** → split dashboards and share by group, or use CLS.
- **Restricting to source-side security**: with **direct query**, Lake Formation/Redshift RLS applies per query; with SPICE, it applies only to the identity used at import.

## F. Custom permissions and governance settings
- **Custom permissions profiles**: admins create a profile that **turns off capabilities** and assign it to users/roles (`CreateCustomPermissions` / user `CustomPermissionsName`) **(verify API names)**.
- **Typical restrictions**: **export to CSV/Excel/PDF**, **sharing dashboards/datasets**, **creating/editing data sources or datasets**, **creating folders**, **subscribing to email reports**, **using generative/Q features**, **printing** **(verify exact list)**.
- **Why**: stop data exfiltration and limit who can connect new sources.
- **Publish options** also turn off export or ad hoc filtering per dashboard.
- **Account settings**: disable **public sharing**, restrict **allowed embedding domains**, set **account termination protection** **(verify)**.
- **Shared folders** with group permissions keep team assets organized and controlled.
- **Tags** on assets and users support **cost allocation** and **tag-based IAM** (ABAC on API calls) **(verify ABAC)**.

## G. Encryption and network security
- **SPICE data is encrypted at rest** (AWS-managed keys by default).
- **Customer managed KMS keys (Enterprise)**: set a CMK for SPICE datasets in account settings; **revoking the key** makes SPICE data unreadable (dashboards fail) and key use is logged in **CloudTrail** **(verify scope and key rotation behavior)**.
- **Catch**: changing the default key applies to **new or refreshed** datasets, not instantly to all existing data **(verify)**.
- **In transit**: TLS between users and Quick, and **SSL** to sources when enabled.
- **Credentials**: stored data source passwords are encrypted; prefer **IAM auth** (Redshift/Athena) or **Secrets Manager** secrets for data source credentials **(verify Secrets Manager support)**.
- **VPC connections** keep DB traffic private (file 1); **interface VPC endpoints (PrivateLink)** for the Quick **API/console** from your network exist **(verify)**.
- **IP-based restrictions**: limit which IP ranges can sign in to Quick **(verify feature)**.

## H. Monitoring, auditing and usage
- **CloudTrail** records Quick **API calls** and many **console events** (e.g. dashboard creation, user sign-in, sharing) for audit **(verify which reader events)**.
- **Usage analytics pattern**: CloudTrail → S3 → Athena → Quick Sight **admin usage dashboard** to find unused dashboards and inactive readers.
- **CloudWatch metrics** (namespace `AWS/QuickSight`): **dashboard view count/load time**, **visual load time**, **ingestion invocation/error count, latency, row count**, **SPICE capacity used/limit** **(verify exact metric names)**.
- **Alarms**: alarm on **ingestion error count > 0** and on **SPICE capacity used %** to act before failures.
- **Refresh history** per dataset shows status, duration, rows ingested/skipped.
- **Failure emails** go to dataset owners on refresh failure.
- **EventBridge events** for asset changes or ingestion status **(verify)**.

## I. Dev → prod, IaC and API
- **Asset bundles**: `StartAssetBundleExportJob` exports dashboards/analyses/datasets/data sources/themes **with dependencies** as **Quick JSON** or **CloudFormation JSON**; `StartAssetBundleImportJob` imports into another account/Region with **override parameters** (data source endpoints, IDs, permissions).
- **Templates**: older pattern; `CreateTemplate` from an analysis in dev, grant the prod account permission, `CreateDashboard` in prod from the template with prod datasets.
- **Definitions API**: `DescribeDashboardDefinition` / `CreateDashboard` with a JSON **definition** lets you keep dashboards as code in Git.
- **CloudFormation**: `AWS::QuickSight::DataSource`, `DataSet`, `Analysis`, `Dashboard`, `Template`, `Theme`, `RefreshSchedule`, `VPCConnection` **(verify full list)**; Terraform also supports Quick resources.
- **Promotion pattern**: dev account → export bundle → CI/CD pipeline swaps endpoints/IDs → import to test → prod.
- **Catch**: datasets in prod must have the **same column names/types** as the template expects, or visuals break.
- **Backups**: no native backup service for Quick assets → keep **asset bundles/definitions in Git**; the data's source of truth is the lake/warehouse.
- **Regions**: SPICE and asset metadata are **Regional**; a dataset in one Region can't be used by an analysis in another → copy assets with bundles or replicate the data.
- **Cross-Region data**: direct query to a source in another Region works but adds **latency** and data transfer cost; prefer one Quick Region close to the data and audience.
- **Migration from other BI tools** (Tableau/Power BI): no automatic converter → rebuild datasets and visuals **(verify)**.
- **User automation**: `RegisterUser`, `DeleteUser`, `UpdateUser` (role change), `CreateGroupMembership` from an IdP sync job.

## J. Pricing (pricing page, 2026-11-02)
| Item | Price |
|---|---|
| Reader | $3 / user / month |
| Reader Pro | $20 / user / month |
| Author | $24 / user / month (10 GB SPICE included) |
| Author Pro | $40 / user / month (10 GB SPICE credit) |
| Admin / Admin Pro | same as Author / Author Pro |
| Account infrastructure fee | $250 / month when any Pro user, topic Q&A or Dashboard Q&A is on |
| SPICE | $0.38 / GB-month beyond included |
| Reader sessions (monthly) | 500 sessions $250, $0.50 extra |
| Pixel-perfect (monthly) | 500 units $500, $1.00 extra |
| Alerts / anomaly | $0.50 → $0.05 per 1,000 metrics (tiered) |
- **Reader session** = a **30-minute** window of reader activity.
- **Annual session tiers**: 50,000/yr **$20,000** ($0.40 extra); 200,000 **$57,600** ($0.28); 400,000 **$96,000** ($0.24); 800,000 **$162,000** ($0.20); 1.6 M **$258,000** ($0.16); 3 M+ contact sales.
- **Q question capacity**: 500/month **$250** ($0.50 extra); annual 60,000 **$18,000** ($0.30), 600,000 **$120,000** ($0.20).
- **Pixel-perfect annual**: **4,000 units/month for $24,000/yr** ($0.50 extra).
- **Authors**: limited-time promo gives Authors Quick Enterprise capabilities **through 31 Dec 2026** (pricing page).
- **Pro roles in Quick Regions** include Quick (suite) capabilities at no extra cost (pricing page).
- **Free trial**: the page offers "Try Quick for free" but states no length → **(verify trial terms)**.
- **Old exam pricing** (legacy): Enterprise Author ~$18–24/month, Reader **$0.30 per 30-min session capped at $5/month**, Standard Author $9–12 **(verify; old model)**.

## K. Cost optimization math
- **Per-user vs session break-even (monthly plan)**: Reader $3 ÷ $0.50 per session = **6 sessions**. A reader using **more than ~6 sessions/month** is cheaper as a per-user Reader.
- **But the session plan has a $250 floor** (500 sessions): fewer than ~84 Readers' worth ($250 ÷ $3) → per-user is cheaper unless readers are external/anonymous.
- **Example**: 2,000 external customers × 1 session/month = 2,000 sessions → $250 + 1,500 × $0.50 = **$1,000** vs 2,000 × $3 = **$6,000** per-user → sessions win.
- **Example**: 100 staff × 20 sessions/month = 2,000 sessions = **$1,000** vs 100 × $3 = **$300** → per-user wins.
- **Anonymous embedding always needs session capacity**, regardless of the math.
- **Pro roles only for people who use generative features**: Reader Pro is ~7× Reader; one Pro user also triggers the **$250 account fee**.
- **SPICE math**: 500 GB needed, 10 Authors → 100 GB included → **400 GB × $0.38 = $152/month**.
- **Shrink SPICE**: drop columns, filter history, convert strings, aggregate upstream, delete orphaned datasets, **release unused capacity**.
- **Refresh smart**: **incremental** instead of full; refresh only as often as people look at the data.
- **Athena-backed dashboards**: SPICE avoids per-visual scans; upstream use **Parquet + partitions** to cut refresh scan cost.
- **Alerts/anomaly**: limit metrics × dimensions × frequency (billed per 1,000 metrics evaluated).
- **Pixel-perfect**: schedule only needed reports; unit = 100 pages/100 MB.
- **Clean users**: remove departed users (billed per registered user per month); review inactive readers via usage data.

## L. Quotas and numbers to remember
- **SPICE per dataset**: Standard **25 M rows / 25 GB**; Enterprise **2 B rows / 2 TB** (docs).
- **SPICE columns/fields**: **2,000 columns**, **127-char column names**, **2,047-char fields** (65,534 new prep), **1,000 files per manifest** (docs).
- **Direct query**: **2-minute** visual timeout, **2,000 columns** per result (docs).
- **Refresh**: hourly = Enterprise; **5 schedules per dataset**; starts within **10 minutes**; incremental down to **15 minutes** (docs).
- **SPICE logical size**: numbers/dates **12 bytes**, text **UTF-8 length + 24** (docs).
- **RLS**: **999 rules per user**, **192,000 filter values per user per field** (SPICE), **text fields only** (docs).
- **Embedding**: URL valid **5 min**, session **15–600 min (default 600)**, **3 runtime allowed domains** (docs).
- **Namespaces** ~100 per account; **tags for tag-based RLS** ~50 per dataset; dashboards/datasets per account in the thousands **(verify all three)**.
- **API throttles**: Quick APIs have per-account TPS limits; batch automation should **retry with backoff** **(verify numbers)**.

## M. Troubleshooting (symptom → cause → fix)
- **Users see all rows** → RLS not applied to that dataset, user is a **dataset owner**, or rule row has NULLs = all values → check permissions and rules.
- **Users see no rows** → no rule for them (**default deny**), name case mismatch, or all rules empty (skipped) → add exact-case rules.
- **Group rules don't work with Identity Center/Okta groups** → only Quick or AD groups are supported in rules → use Quick group names synced into Quick.
- **RLS on a date/number column has no effect** → RLS supports text fields only → cast to string.
- **Visual disappears for some users** → it uses a **CLS-restricted column** → remove column or grant access.
- **Table shows "Not Authorized"** → CLS-restricted column in Values → expected; grant access if needed.
- **Rules dataset ingestion fails** → rules datasets use strict ingestion → fix invalid/too-long rows.
- **Restricted users suddenly locked out** → file-based rules dataset deleted → choose new rules in Permissions.
- **Federated user can't sign in** → role lacks `quicksight:Create*` or SAML relay/trust wrong → fix role policy and IdP config.
- **User sees "not authorized" on a dashboard** → not shared with them/their group → share or add to folder.
- **Embedded dashboard blank / "domain not allowed"** → host domain missing from allow-list → add domain or pass AllowedDomains.
- **Embed fails after refresh** → URL reused or older than 5 minutes → generate a new URL per load.
- **`UnsupportedPricingPlanException`** → anonymous embedding without session capacity → buy sessions.
- **Tenant sees another tenant's data** → session tags not set server-side or tag column wrong → set tags in backend, verify tag mapping.
- **Dashboards fail after a KMS change** → CMK disabled/revoked or key policy lacks Quick → re-enable key / fix policy.
- **Readers can export sensitive data** → export allowed → disable in publish options or custom permissions.
- **Surprise $250/month line** → a Pro user or Q&A was enabled → remove Pro/Q&A if not needed.
- **High bill** → many Pro roles, large SPICE, frequent alerts/reports → audit roles and usage.
- **Import into prod breaks visuals** → dataset schema differs → align column names/types or use override parameters.

## Scenarios: "If X → Y, because Z"
- If each regional manager must see only their region → **RLS rules dataset (GroupName → region)**, because users see only matching rows and others see none.
- If a VP must see every region → **rule row with the VP's name and NULL region**, because NULL means all values.
- If salary columns must be hidden from analysts → **CLS on the salary column**, because restricted users can't see or use it.
- If 200 SaaS tenants share one dashboard → **anonymous embedding + tag-based RLS**, because session tags filter per tenant without accounts.
- If tenant users need their own logins and assets fully separated → **namespaces**, because users in one namespace can't see another's.
- If 5,000 occasional external viewers use dashboards once a month → **session capacity**, because per-user Readers would cost far more.
- If 50 internal analysts use dashboards daily → **per-user Reader**, because >6 sessions/month makes $3 cheaper than sessions.
- If only two executives want AI summaries → **Reader Pro for those two**, accepting the **$250 account fee**, because Pro is per person.
- If auditors ask who changed or shared dashboards → **CloudTrail (with Athena for analysis)**, because Quick API and console actions are logged.
- If refresh failures must page on-call → **CloudWatch alarm on ingestion errors** (or EventBridge), because metrics capture ingestion failures.
- If the company IdP is Okta → **IAM Identity Center or SAML federation with JIT**, because users are created on first sign-in with group mapping.
- If dashboards must move dev → prod across accounts → **asset bundle export/import with override parameters**, because they carry dependencies and swap endpoints.
- If security requires customer control of the SPICE key → **Enterprise with a customer managed KMS key**, because revoking it cuts access to SPICE data.
- If readers must not download data → **custom permissions profile disabling export**, because it removes export from those users.
- If a source already enforces Lake Formation row filters per user → **direct query with identity propagation**, because SPICE applies source security only at import time.

Verified from AWS docs on 2026-11-02 (pages used): RLS with user-based rules, column-level security, embedding for anonymous users, data source quotas, refreshing SPICE data, Amazon Quick Sight pricing page. The custom permissions page rendered empty.
Unconfirmed (verify): changing identity method after sign-up; JIT action names; trusted identity propagation to Redshift/LF; custom IAM role and per-data-source roles; Subscribe restriction; IAM admin vs asset permissions; deny-style RLS policy; object-level security not existing; custom permissions API names and capability list; account termination protection; ABAC on tags; CMK scope, rotation and when key changes apply; Secrets Manager credentials; PrivateLink for API/console; IP sign-in restriction; CloudTrail reader events; CloudWatch metric names; EventBridge events; CloudFormation resource list; free-trial terms; legacy session pricing; namespace, tag and asset-count quotas; API throttle numbers.

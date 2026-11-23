# Amazon Quick Sight – 1. Concepts, data sources, datasets and SPICE

Short notes. Each point is a fact you can be asked about.

## A. What it is and the names
- **Amazon Quick Sight** = AWS's **serverless, cloud BI service**: connect to data, prepare datasets, build **interactive dashboards**, share or embed them, add **ML insights** and **natural-language Q&A**.
- **No servers to manage**: AWS scales the query and render layer; you pay **per user** (roles) or **per reader session**, plus usage add-ons.
- **Old spelling: "QuickSight"** (one word). Old exam questions, old API names (`quicksight:*`), CloudWatch namespace `AWS/QuickSight` and CloudFormation `AWS::QuickSight::*` keep the old spelling.
- **Amazon Quick (Quick Suite)** = the newer umbrella product (AI assistant chat, Spaces, Research, Flows, Automate, integrations). **Quick Sight is the BI capability inside Amazon Quick.**
- **"Amazon Q in QuickSight"** = the old name for the **generative BI** features (Q topics, building visuals by asking, executive summaries, data stories). These now belong to Pro roles in Quick.
- The user guide now lives under **docs.aws.amazon.com/quick/** ("Amazon Quick User Guide"); the API reference is still the **QuickSight API**.
- **Exam mapping (DEA-C01)**: Task **3.2.1 "visualize data"** (pick Quick Sight for business dashboards) and **3.2.2 "verify and clean data"** (use Quick Sight data prep, filters and calculated fields to check and fix data).
- **Pick Quick Sight when**: business users need **dashboards** on Athena, Redshift, RDS/Aurora, S3 or SaaS data, with **per-reader pricing**, **RLS**, **embedding** or **ML insights**.
- **Pick something else when**: ops/infrastructure metrics → **CloudWatch dashboards** or **Amazon Managed Grafana**; ad-hoc SQL only → **Athena / Redshift query editor**; notebooks → **SageMaker Studio / EMR Studio**.
- **Quick Sight is not a data store**: SPICE is a cached copy; the **source of truth stays in the lake/warehouse**.

## B. Account, Region and edition basics
- A **Quick account (subscription)** is created **per AWS account** and has one **home Region** (where identity and the default SPICE live).
- **Account name** is unique across Quick and is typed at sign-in for some identity types.
- Assets (data sources, datasets, analyses, dashboards) are **Regional**; you can switch Regions in the console and use **SPICE capacity bought for that Region**.
- **Two editions historically**: **Standard** and **Enterprise**. Docs mark features with **"Applies to: Enterprise Edition"**.
- **Standard → Enterprise upgrade is one-way**; you cannot downgrade **(verify current downgrade rule)**.
- New Quick accounts are effectively **Enterprise** with role-based pricing; Standard mostly appears in older questions **(verify whether Standard is still sold)**.

| Feature | Standard | Enterprise |
|---|---|---|
| SPICE rows/size per dataset | 25 M rows / 25 GB | 2 B rows / 2 TB |
| Hourly (and 15/30-min incremental) refresh | No | Yes |
| Incremental refresh | No | Yes |
| Row-level and column-level security | No | Yes |
| Active Directory, groups, namespaces | No | Yes |
| Private VPC connections | No | Yes (verify) |
| Embedding (registered/anonymous) | No | Yes |
| ML insights, alerts, Q, pixel-perfect | No | Yes |
| SPICE encryption with customer KMS key | No | Yes (verify) |

## C. Core objects (hierarchy)
- **Data source** = a stored **connection** (endpoint, credentials or IAM role, VPC connection) to one source.
- **Dataset** = a **prepared table** built from one or more data sources: selected columns, joins, renames, type changes, calculated fields, filters, security rules, and a **SPICE or direct query** choice.
- **Analysis** = the **authoring workspace** where authors build sheets, visuals, filters, parameters and controls.
- **Dashboard** = the **published, read-only version** of an analysis that readers interact with. Each publish creates a **version**.
- **Topic** = curated metadata on datasets for **natural-language Q&A** (see file 2).
- **Template / theme / folder / namespace** = reuse, branding, organization and multi-tenancy objects.
- **One dataset can feed many analyses**; refreshing the dataset once updates every analysis and dashboard that uses it.
- **Datasets can be built from other datasets** ("child" datasets); the parent's logic and RLS carry down.
- **Catch**: deleting a dataset breaks every analysis/dashboard that uses it; replace the dataset in the analysis first.

## D. Data sources – AWS
- **Amazon Athena**: the standard way to query **S3 data lakes** (Parquet/ORC/JSON/CSV) catalogued in **Glue**. Choose an **Athena workgroup** on the data source.
- **Athena workgroup** controls the **query result location**, encryption, engine version and data-scanned limits; Quick queries count toward the workgroup's limits and cost.
- **Athena permissions**: Quick runs Athena queries using the **Quick service role** (or a custom IAM role you assign to the Athena data source **(verify per-source role)**).
- **S3 access for Athena**: in **Manage Quick → Security & permissions**, tick **Athena** and the **S3 buckets** holding the data **and** the **Athena query results bucket** (Quick needs write access there).
- **Lake Formation**: when tables are governed by Lake Formation, grant LF permissions (SELECT on tables/columns) to the principal Quick uses: the **service role**, or **Quick user/group ARNs** directly **(verify exact principal options)**.
- **Catch**: S3 bucket permission ticked but LF grant missing → "insufficient Lake Formation permissions" errors.
- **Amazon Redshift**: **provisioned clusters** and **Redshift Serverless**; auto-discovery lists clusters in the account; connect by endpoint or by **IAM authentication** (temporary credentials instead of a stored password) **(verify IAM-auth setup details)**.
- **Redshift Spectrum** tables appear like normal tables through the Redshift connection.
- **RDS / Aurora**: MySQL, PostgreSQL, MariaDB, SQL Server, Oracle engines; auto-discovery for instances in the account.
- **Amazon S3 (direct)**: reads **CSV, TSV, CLF, ELF, JSON** (and XLSX) files described by a **manifest file**; **no Parquet/ORC through the S3 connector** → use **Athena** for those **(verify XLSX/compressed support)**.
- **S3 data from the S3 connector is always imported into SPICE** (no direct query on raw S3 files).
- **Amazon OpenSearch Service**: direct query or SPICE over indexes **(verify SPICE support)**.
- **Amazon Timestream**: time-series source, usually **direct query** for near-real-time dashboards.
- **Others on AWS**: Aurora/Redshift via VPC, **EMR Presto/Spark** (JDBC-style connectors), **AWS IoT Analytics** (older) **(verify)**, **Amazon S3 Tables / Glue catalog via Athena**.

## E. Data sources – external, SaaS and files
- **Databases/warehouses**: **Snowflake**, **Databricks**, **Teradata**, **Oracle**, **SAP HANA**, **Google BigQuery**, **Starburst/Presto/Trino**, **Exasol**, **MySQL/PostgreSQL/SQL Server** on EC2 or on-premises.
- **SaaS connectors**: **Salesforce**, **ServiceNow**, **Jira**, **Adobe Analytics**, **GitHub** and others; SaaS data is generally **imported into SPICE** **(verify per connector)**.
- **File upload**: CSV, TSV, XLSX, ELF/CLF, JSON from your computer; files are **always imported into SPICE**; upload limit is about **1 GB per file** **(verify)**.
- **Excel uploads**: you choose a **sheet** (one sheet = one dataset); merged cells and multiple header rows cause bad imports.
- **Snowflake/Databricks** can use **SPICE or direct query**; network path is public endpoint (with IP allow-list) or **PrivateLink via VPC connection** **(verify)**.
- **On-premises DB**: reach it through a **VPC connection** + **Direct Connect/VPN**, or expose a public endpoint with the Quick IP range allowed.

## F. Networking and cross-account access
- **Public endpoint sources**: allow inbound traffic from the **Quick Sight IP address range for that Region** (published per Region in the docs) on the DB security group / firewall.
- **Catch**: using the IP range of a **different Region** than the Quick Region → connection timeouts.
- **Private sources (VPC connection)**: Quick creates **elastic network interfaces (ENIs)** in subnets you choose, so it can reach **private IPs** in your VPC.
- **VPC connection pieces**: VPC, **subnets** (pick at least two AZs for resilience **(verify minimum)**), **security groups**, optional **DNS resolver endpoints**, and an **IAM execution role** that lets Quick create/manage the ENIs **(verify role requirement)**.
- **Security groups**: the **DB security group** must allow the DB port **from the Quick ENI security group**; the **Quick security group** must allow return traffic from the DB **(verify exact rule set)**.
- **VPC connections are Enterprise** and **Regional**; one VPC connection can serve many data sources.
- **Private DNS names**: use **Route 53 Resolver outbound/inbound endpoints** with the VPC connection to resolve private hostnames **(verify)**.
- **Cross-account S3**: the bucket owner adds a **bucket policy** for the Quick service role; if objects use **SSE-KMS**, the **KMS key policy** must also allow that role.
- **Cross-account Athena/Glue**: share catalog/tables with **Lake Formation cross-account grants** or a **Glue resource policy**, then query through Athena in the Quick account.
- **Cross-account Redshift**: connect by endpoint (public with IP allow-list, or private via VPC peering/Transit Gateway + VPC connection), or use **Redshift data sharing** into a local cluster **(verify)**.
- **Encryption in transit**: connections use **SSL/TLS**; enable SSL on the data source for RDS/Redshift.

## G. Datasets – building and joining
- **Import modes**: each dataset is **SPICE** or **direct query** (chosen per dataset, switchable later).
- **Select tables or write custom SQL**: **custom SQL** lets you pre-join, pre-aggregate or filter at the source; it is passed to the engine as a subquery.
- **Catch with custom SQL**: Quick wraps it as a subquery, so engine-specific syntax that cannot be nested (for example some `WITH`/`ORDER BY` cases) can fail **(verify)**.
- **Join types**: **inner, left outer, right outer, full outer** **(verify whether full outer is allowed for every source)**.
- **Join keys**: equality joins on one or more columns; key columns must have **compatible data types** (cast first).
- **Cross-source joins** (for example an S3 file + a Redshift table): supported, but the result must be stored in **SPICE** **(verify)**.
- **Join limit**: up to about **32 tables** in one dataset **(verify)**.
- **Joining datasets** (logical datasets on top of other datasets) is supported in the newer data prep **(verify)**.
- **Unions / append**: newer data prep supports appending tables **(verify)**.
- **Catch**: a bad join (many-to-many) multiplies rows and **inflates sums**; check row counts before and after the join.
- **Data preparation actions**: rename fields, change **data types**, exclude fields, add **calculated fields**, add **filters** (dataset-level, apply to every analysis), set **field folders** and descriptions, mark **geospatial roles**.
- **New data preparation experience** (2025): step-based flow (append, join, pivot/unpivot, aggregate) and longer text fields (65,534 chars) **(verify step list)**.
- **Dataset-level filters** reduce rows **before** SPICE import → smaller SPICE footprint and faster visuals.
- **Field-level changes made in the dataset** are reused everywhere; changes in an analysis apply only to that analysis.

## H. Calculated fields, parameters, geospatial
- **Calculated fields** use Quick's expression language; add them in the **dataset** (reusable, computed at ingestion for SPICE) or in an **analysis** (only that analysis).
- **Function families**: **aggregate** (`sum`, `avg`, `count`, `distinct_count`, `min`, `max`, `median`, `percentile`), **conditional** (`ifelse`, `coalesce`, `isNull`, `isNotNull`, `nullIf`), **date** (`addDateTime`, `dateDiff`, `truncDate`, `extract`, `now`, `parseDate`, `formatDate`), **numeric** (`round`, `ceil`, `floor`, `log`), **string** (`concat`, `substring`, `split`, `trim`, `toUpper`, `replace`, `parseInt`, `toString`, `locate`), **table calculations** (`runningSum`, `percentOfTotal`, `rank`, `difference`, `periodOverPeriodDifference`, `windowSum`).
- **LAC-A (level-aware calculation – aggregate)**: an aggregate with a partition list, e.g. `sum(sales, [region])`; computes at a level **different from the visual's dimensions** and can be used as a measure.
- **LAC-W (level-aware calculation – window)**: window functions like `sumOver(sales, [region], PRE_AGG)`; the level argument **PRE_FILTER** or **PRE_AGG** decides whether it runs **before filters** or **before visual aggregation**.
- **Why LAC**: "percent of region total", "customer's first order date", "average of per-customer totals" need a level other than the visual's grouping.
- **Catch**: mixing aggregated and non-aggregated fields in one expression gives an error; aggregate both or use LAC.
- **Parameters**: named variables (**string, integer, decimal, datetime**), single or **multi-value**, with a **static or dynamic default** (dynamic default = value looked up per user/group from a dataset).
- **Parameter uses**: drive **filters**, **calculated fields**, visual titles, **URL actions**, navigation between sheets, and embedding (set from the host app).
- **Controls** = UI for parameters/filters: **dropdown, list, text box, slider, date picker, date range**; can be **cascading** (one control limits another's values).
- **Geospatial data**: mark fields with roles **country, state/region, county, city, postcode, latitude, longitude**; build **geospatial hierarchies** (country → state → city) for maps.
- **Catch**: ambiguous names (e.g. "Springfield") geocode wrongly → add a country/state hierarchy or use **latitude/longitude**.
- **Data types**: string, integer, decimal, date (datetime), plus geospatial roles; wrong types (numbers stored as text) block math and **waste SPICE**.

## I. SPICE – the engine
- **SPICE** = **Super-fast, Parallel, In-memory Calculation Engine**: Quick's **columnar, in-memory store** that holds an **imported copy** of the dataset.
- **Why SPICE**: fast, consistent visuals; **no load on the source** after import; **no per-query cost** on pay-per-scan sources like **Athena**; dashboards still work if the **source is down**.
- **Catch**: SPICE data is **only as fresh as the last refresh**.
- **Capacity is per Region** and **shared by every user in the account** in that Region (a pool, not per author).
- **Home Region** gets the included capacity; **other Regions start with 0** until you buy capacity there.
- **Included capacity**: **10 GB per Author** (Author and Author Pro) added to the pool; extra capacity costs **$0.38 per GB-month**.
- Admins **purchase or release** capacity in **Manage Quick → SPICE capacity**; there is an **auto-purchase** option so ingestions don't fail on full capacity **(verify)**.
- **Logical size formula**: **numeric and date cells = 12 bytes** each (8 bytes + 4 overhead); **text cells = UTF-8 length + 24 bytes**.
- **Example**: 10 M rows × (5 numeric + 3 text of avg 10 chars) = 10 M × (5×12 + 3×34) = 10 M × 162 B ≈ **1.62 GB**.
- **Size is measured after data prep** (type changes, calculated fields, excluded columns), not on the raw source size.
- **Save SPICE**: exclude unused columns, filter out old rows, **convert text to numbers/dates**, pre-aggregate at the source, delete unused datasets.
- **Per-dataset limits** (docs): **Standard 25 million rows or 25 GB**; **Enterprise 2 billion rows or 2 TB** per dataset.
- **Other SPICE quotas** (docs): **2,000 columns per file**, **127 Unicode characters per column name**, **2,047 characters per field** (**65,534** with the new data prep), **1,000 files per S3 manifest**.
- **Catch**: text longer than the field limit is **truncated** at ingestion; very wide rows can hit the GB limit before the row limit.
- **SPICE limits also apply to datasets with RLS**.
- **SPICE encryption at rest**: always encrypted; **Enterprise** can use a **customer managed KMS key** (see file 3).

## J. Refreshing SPICE
- **Full refresh** = re-imports the whole dataset; **the old data stays visible until the new import succeeds**.
- **Refresh failure keeps the previous data**; owners get a **failure email**, and the dataset shows the last successful refresh time.
- **Schedules** (docs): **Daily, Weekly, Monthly** in Standard and Enterprise; **Hourly** is **Enterprise only**.
- **Monthly on the 29th–31st** → choose **"Last day of month"**.
- **Up to 5 schedules per dataset** in the console.
- **Hourly (or 15/30-minute) schedule is exclusive**: you must remove other schedules before adding it, and vice versa.
- **Scheduled ingestions start within 10 minutes** of the scheduled time (not to the second).
- **Incremental refresh** (**Enterprise**, **SQL sources** like Redshift, Athena, PostgreSQL, Snowflake): you pick a **date column** and a **look-back window** (hours, days or weeks).
- **How incremental works**: Quick queries only rows in the window, **deletes the SPICE rows in that window**, and **inserts the fresh rows** → captures inserts, updates and deletes inside the window.
- **Catch**: changes to rows **older than the window** are **not** picked up; run a periodic full refresh or widen the window.
- **Incremental schedules** can run **every 15 minutes, 30 minutes, hourly, daily, weekly or monthly**; 15/30-minute/hourly schedules are again exclusive.
- **Deleting the incremental configuration triggers a full refresh**.
- **S3 / file datasets** cannot use incremental refresh (no SQL look-back) → full refresh only **(verify)**.
- **API refresh**: `CreateIngestion` starts a refresh (full or incremental); `DescribeIngestion` / `ListIngestions` check status; `CancelIngestion` stops it.
- **Event-driven refresh pattern**: ETL finishes (Glue job / Step Functions / EventBridge) → **Lambda calls `CreateIngestion`** → dashboards update right after the data lands.
- **Refresh schedules via API**: `CreateRefreshSchedule`, `PutDataSetRefreshProperties` (incremental config) **(verify names)**.
- **Schema changes** at the source are **not auto-detected** → ingestion fails until you **edit and save the dataset**.
- **Ingestion summary** shows **rows ingested and rows skipped**; download the **error rows** to see why (type mismatch, too-long field).
- **Concurrent ingestions** per account are limited **(verify the number)**; very frequent refreshes on many datasets can queue.
- **Direct query datasets don't refresh**; they query live (with a short cache) each time a visual loads.

## K. SPICE vs direct query
| Point | SPICE | Direct query |
|---|---|---|
| Speed | Fast, in-memory | Depends on source engine |
| Freshness | As of last refresh (hourly or 15-min incremental at best) | Live (short cache) |
| Source load / cost | One import per refresh | Every visual load hits the source |
| Athena cost | Pay scan only at refresh | Pay scan on every interaction |
| Limits | 2 B rows / 2 TB per dataset (Ent.) | 2-minute visual timeout |
| Source down | Dashboards still work | Visuals fail |
| Source-side security (LF, Redshift RLS) | Applied at import as the import identity | Applied per query |
- **Direct query timeout**: Quick stops waiting after **2 minutes** for visual generation or a dataset sample (docs).
- **Catch**: some drivers (e.g. **Redshift**) ignore the 2-minute timeout, so the **query keeps running on the database**; cancel it there and use WLM.
- **Direct query quotas**: **2,000 columns** per result set, **127 characters** per column name, plus the source engine's own timeouts.
- **Choose direct query** when data must be **near real time**, cannot be copied (residency/compliance), or is **too big for SPICE**, and the source is fast (Redshift, Timestream).
- **Choose SPICE** for most BI, for **Athena** sources (avoid repeated scans), and for **many concurrent readers**.
- **Trap**: "dashboards on Athena are slow and the Athena bill is high" → **SPICE**, not bigger Athena workgroups.
- **Trap**: "users must see the last 5 minutes of data" → **direct query** (SPICE's fastest schedule is 15-minute incremental).

## L. Verify and clean data (exam skill 3.2.2)
- **Profile in data prep**: preview rows, check data types, spot nulls and odd values before publishing.
- **Ingestion report**: "rows skipped" tells you about bad types or truncation; fix at the source or change the field type.
- **Clean with calculated fields**: `coalesce` to fill nulls, `ifelse` to bucket/fix values, `trim`/`toUpper` to normalize text, `parseDate`/`parseInt` to fix types.
- **Filter bad rows** with dataset-level filters (e.g. exclude negative quantities or test accounts).
- **Check join quality**: compare totals before and after a join; duplicates on the join key inflate measures.
- **Reconcile**: build a quick table/KPI of row counts and sums and compare with the source query (Athena/Redshift) results.
- **Where heavy cleaning belongs**: Glue / Glue DataBrew / Athena CTAS / Redshift SQL upstream; Quick Sight prep is for **light, last-mile** fixes.
- **Catch**: fixes made only in one analysis don't help other analyses → put shared fixes in the **dataset**.

## M. Troubleshooting (symptom → cause → fix)
- **"Insufficient SPICE capacity" on import/refresh** → Region pool full → delete/trim datasets, release unused space elsewhere, or **buy capacity in that Region**.
- **SPICE capacity available in us-east-1 but import fails in eu-west-1** → capacity is per Region → buy SPICE in eu-west-1.
- **Athena dataset: "access denied" on S3** → bucket not allowed in **Security & permissions** or results bucket not writable → tick the data and results buckets.
- **Athena dataset: Lake Formation permission error** → no LF grant for the Quick principal → grant SELECT in Lake Formation.
- **Athena dataset fails on encrypted bucket** → Quick role not in the **KMS key policy** → allow `kms:Decrypt` for the role.
- **RDS/Redshift connection timeout (public endpoint)** → security group lacks the **Quick IP range for that Region** → add the range on the DB port.
- **Private DB connection timeout** → no VPC connection, wrong subnets, or SG rules missing between Quick ENIs and DB → fix VPC connection and SG rules.
- **Hostname won't resolve over VPC connection** → private DNS not reachable → add Resolver endpoints / use IP.
- **Refresh fails after a column was added/renamed** → schema change not detected → **edit and save the dataset**.
- **Refresh fails after password rotation** → stale data source credentials → update the data source (or use IAM auth / Secrets Manager **(verify)**).
- **Rows skipped during import** → type mismatch or too-long text → change field type, clean source, download error rows.
- **Totals too high after a join** → many-to-many join duplicates rows → fix keys or pre-aggregate.
- **Direct query visuals time out** → query > 2 minutes → simplify SQL, add materialized views, or move to **SPICE**.
- **Redshift still busy after visual timed out** → driver ignores timeout → cancel the query, tune WLM.
- **Hourly schedule option missing** → Standard edition or other schedules exist → upgrade/remove other schedules.
- **Incremental option missing** → file/S3 source or Standard edition → use SQL source on Enterprise.
- **Updates to old rows not showing after incremental refresh** → change is outside the look-back window → widen the window or run a full refresh.
- **Parquet files in S3 can't be loaded** → S3 connector doesn't read Parquet → query through **Athena**.
- **Map shows wrong city** → ambiguous geocoding → add a geospatial hierarchy or lat/long.
- **Calculated field error "mixing aggregated and non-aggregated"** → expression level mismatch → aggregate both parts or use LAC-A/LAC-W.

## Scenarios: "If X → Y, because Z"
- If dashboards on Athena are slow and the scan bill is high → **import into SPICE with a schedule**, because SPICE serves repeated queries without re-scanning S3.
- If data must be fresh within minutes → **direct query** (or **incremental SPICE every 15 min** on Enterprise), because a full SPICE copy is only as fresh as its last refresh.
- If the ETL finishes at random times → **EventBridge/Step Functions → Lambda → `CreateIngestion`**, because API refresh runs right after the data lands.
- If a 3-billion-row fact table must be in one SPICE dataset → **aggregate upstream or split it**, because Enterprise caps a SPICE dataset at 2 B rows / 2 TB.
- If the team is on Standard edition and needs hourly refresh → **upgrade to Enterprise**, because hourly is Enterprise only.
- If yesterday's late-arriving updates must be reflected without a full reload → **incremental refresh with a look-back window covering them**, because only rows in the window are replaced.
- If the database is in a private subnet → **VPC connection (ENIs + security groups)**, because Quick must reach private IPs from inside the VPC.
- If the DB has a public endpoint → **allow the Quick IP range for that Region**, because traffic comes from Quick's published addresses.
- If data is Parquet in S3 → **Athena data source**, because the S3 connector only reads text/JSON formats via a manifest.
- If S3 data lives in another account → **bucket policy (and KMS key policy) for the Quick role**, because cross-account access needs both sides to allow it.
- If tables are governed by Lake Formation → **grant LF permissions to the Quick principal**, because S3 access alone is not enough.
- If SPICE keeps running out → **trim columns/rows, convert text to numbers, buy capacity**, because capacity is a shared per-Region pool.
- If a refresh fails at night → **readers still see yesterday's data**; fix credentials/network/schema and re-run, because a failed refresh keeps old data.
- If the same cleaning logic is needed in five analyses → **put it in the dataset**, because dataset changes are reused everywhere.
- If revenue looks doubled after adding a table → **check for a many-to-many join**, because duplicated keys multiply rows.

Verified from AWS docs on 2026-11-02 (pages used): Data source quotas (SPICE and direct query quotas), Refreshing SPICE data (schedules, incremental refresh), Amazon Quick Sight pricing page; SPICE size formula carried from the earlier SPICE page check.
Unconfirmed (verify): whether Standard edition is still sold and the downgrade rule; VPC connection subnet/SG/IAM role details and DNS resolver use; Lake Formation principal options; Redshift IAM-auth setup; file upload size (1 GB); XLSX/compressed support in S3 manifests; OpenSearch SPICE support; SaaS import-only behavior; join type and 32-table limits; cross-source joins needing SPICE; new data prep step list; SPICE auto-purchase; concurrent ingestion limit; refresh API names other than CreateIngestion; incremental refresh for S3/file sources; Secrets Manager credentials.

# Athena – 4. Security, governance, cost and limits

Short notes. Each point is a fact you can be asked about.

## A. Who needs which permissions (IAM basics)
- A query touches **four** permission areas. Missing any one gives AccessDenied:
  1. **Athena API** actions (`athena:StartQueryExecution`, `GetQueryExecution`, `GetQueryResults`, `GetWorkGroup`, …).
  2. **Glue Data Catalog** (`glue:GetDatabase`, `GetTable`, `GetPartitions`, `CreateTable`, `BatchCreatePartition`, …).
  3. **S3**: read on the data, **read/write on the query results location**.
  4. **KMS** (if encrypted) and **Lake Formation** (if the data is registered).
- Managed policies: **`AmazonAthenaFullAccess`** (Athena + scoped Glue/S3 dependencies) and **`AWSQuicksightAthenaAccess`** (for BI). Use custom policies for least privilege.
- **Workgroup-level IAM**: restrict users to specific workgroup ARNs (`arn:aws:athena:region:acct:workgroup/name`). Use tags on workgroups for attribute-based control.
- Athena runs the query **as the calling principal** (with IAM). The S3 data access uses that principal's permissions, unless Lake Formation vends credentials.
- **Cross-account S3**: bucket policy in the data account must allow the querying role; if the objects were written by another account without bucket-owner-full-control, `403` errors appear for the bucket owner. Use S3 Object Ownership "bucket owner enforced" or ACL fix.
- Athena cannot read S3 paths with a **Region endpoint** in the URI (like `us-east-1.amazonaws.com`) → access denied.
- DDL on a bucket whose policy forces `s3:x-amz-server-side-encryption` headers can fail with 403 (partitions DDL writes small marker objects). Fix: remove the extra deny when default bucket encryption is already set.
- **Cross-account Glue catalog**: share via Glue resource policy or Lake Formation (resource links). Linked resources need `DESCRIBE` on the original and `SELECT` on the link.
- `Required table storage descriptor is not populated` → no Lake Formation `DESCRIBE`/`SELECT` on the table.
- **Data perimeters / VPC endpoints**: use **Interface VPC endpoints (PrivateLink)** for Athena (and Glue, S3 gateway endpoint) so queries never go through the internet. Endpoint policies and `aws:SourceVpce` conditions can restrict use.
- **`aws:CalledVia`** condition key: allow S3/Glue access **only when called via Athena** (`athena.amazonaws.com`) so users can't read the data directly. Not compatible with IAM Identity Center–enabled workgroups.
- Prepared statements, UDFs (Lambda), federated catalogs and ML each need their own IAM actions (`athena:GetPreparedStatement`, `lambda:InvokeFunction`, `athena:GetDataCatalog`…).
- Access to **query results** is S3-based: anyone who can read the results bucket can read results. Give each workgroup its own results prefix/bucket and restrict with IAM.

## B. Lake Formation with Athena
- **Lake Formation** adds database/table/**column/row/cell**-level permissions and tag-based control (LF-TBAC) for Glue tables in registered S3 locations.
- How it works: user queries → Athena checks LF → LF gives Athena **temporary credentials** scoped to allowed data → Athena reads S3 with those. Users need **no direct S3 permission** on the registered location.
- Applies to **reads** (SELECT). **Not** applied to writes, to **query results**, or to **query history**.
- Data not registered in Lake Formation is controlled by IAM + Glue only. Both models can exist side by side.
- Key limits and traps:
  - Query **results location cannot be registered** with Lake Formation. Protect it with IAM and workgroups.
  - Use **workgroups** to separate **query history** (it shows query text, column names, filters).
  - Users in the **same workgroup** share query history; align workgroup membership with LF grants.
  - `DESCRIBE` on the `default` database is required.
  - **CTAS** needs S3 **write** permission on the target location via IAM (LF doesn't grant writes).
  - **Iceberg DDL** is not supported on LF-registered locations; `OPTIMIZE`, `VACUUM`, `MERGE`, `UPDATE` can't be governed by LF.
  - Views: user needs LF rights on the underlying tables/columns to create it. LF **cell filters on a table don't apply to its views**. No column-level permissions on a view itself. Keep view and table permissions aligned.
  - Avro/custom SerDe tables keep the schema in table properties, which can **leak column names** to users without column permissions.
  - **CSE-KMS** encrypted data in LF-registered locations cannot be queried for open table formats.
  - Partition folders must be **sub-directories of the table location** to be registered.
  - **Query result reuse** does not work with LF fine-grained tables.
  - Athena for Spark (PySpark engine v3) does **not** support Lake Formation; Spark 3.5 on SageMaker Unified Studio does (verify).
  - Federated sources need to be registered as Glue catalogs to use LF (file 3).

## C. IAM Identity Center and trusted identity propagation
- **Trusted identity propagation (TIP)** passes the **corporate user identity** (from IAM Identity Center) through Athena to Lake Formation and S3 (via **S3 Access Grants**), so audit logs show the real person and permissions follow the person/group.
- Use an **IAM Identity Center–enabled workgroup** (choose authentication "IAM Identity Center" at creation).
  - The authentication method **cannot be changed** after creation. Existing workgroups cannot be converted.
  - Users/groups must be **assigned** to the workgroup's `IdentityCenterApplicationArn`.
  - Needs **Lake Formation** configured for Identity Center and **S3 Access Grants** for result locations.
  - Optional **user-identity S3 prefix**: results go to `<location>/<user_id>/`, isolating users (this forces override client-side settings).
  - Queries cannot run from the Athena console; run them from **EMR Studio** (with Identity Center) or **SageMaker Unified Studio**.
  - Default query timeout **30 minutes**, max **1 hour** for TIP workgroups.
  - Entitlement changes can take up to **1 hour** to apply.
  - Not compatible with: `aws:CalledVia`, Spark workgroups, federated API access (SAML), Lake Formation + JDBC/ODBC federated access.
  - Available in a defined list of Regions (verify for your Region).
- Federated SAML/IdP access to Athena (JDBC/ODBC with AD FS, Okta, etc.) is the older method; it does not propagate identity to Lake Formation the way TIP does.

## D. Encryption
- **At rest – source data in S3**: SSE-S3, **SSE-KMS** (recommended), CSE-KMS. Not supported: SSE-C, client-side keys not from KMS, asymmetric KMS keys.
  - SSE-S3: no extra Athena permission.
  - SSE-KMS: users need **`kms:Decrypt`** (reading); for results **`kms:GenerateDataKey` + `kms:Decrypt`**. Key policy must also allow them.
  - **CSE-KMS**: table needs `TBLPROPERTIES ('has_encrypted_data'='true')` (or `encryption_option`). Works with the **S3 encryption client** only (not the AWS Encryption SDK). No cross-Region. AWS recommends moving to SSE-KMS (fewer KMS calls, no client infra).
- **Query results**: encryption set per workgroup (or client). SSE-S3, SSE-KMS, CSE-KMS. Workgroup **Override client-side settings** enforces it. **Minimum encryption** setting in a workgroup can require a minimum level (e.g., KMS).
- When Athena **reads** an encrypted table it uses the **table's** encryption setting. When it **writes** (INSERT/CTAS), it uses the **result encryption** setting for the new files.
- **Glue Data Catalog encryption**: if catalog metadata is encrypted with KMS, Athena users need `kms:GenerateDataKey`, `kms:Decrypt`, `kms:Encrypt`.
- **Managed query results**: AWS owned key or customer managed key; key policy for `encryption.athena.amazonaws.com`, with conditions `aws:SourceArn`, `aws:SourceAccount`, and encryption context = workgroup ARN.
- Many small KMS-encrypted objects → **KMS throttling** → use **S3 Bucket Keys** or request higher KMS quotas.
- **In transit**: Athena API, JDBC/ODBC and S3 use **TLS**. Federated sources need TLS configured in the connector/DB.
- Spark on Athena has its own encryption settings (verify).

## E. Audit, monitoring and compliance
- **CloudTrail**: logs Athena API calls (`StartQueryExecution` with the query text, `GetQueryResults`, workgroup changes). Also use it to find Glue/Lake Formation throttling behind "timeouts". CloudTrail **data events** for S3 show object reads.
- **Query history** per workgroup (45 days in console) (verify retention); store it long-term yourself via CloudTrail/EventBridge.
- **EventBridge**: "Athena Query State Change" events (file 5).
- **CloudWatch**: query metrics per workgroup (file 5).
- **AWS Config**, **Macie** (find PII in S3 data and results buckets), **Lake Formation audit**.
- Athena is in scope for common compliance programs (SOC, PCI, HIPAA, etc.) (verify current list in AWS Artifact).
- Data **residency**: data stays in S3 of your Region; results go to your Region's bucket.

## F. Governance tools around Athena
- **Workgroups** isolate teams, results, encryption, cost and history.
- **Data usage controls**:
  - **Per-query limit**: cancels the query when scanned data passes the limit. Min **10 MB**, max 7 EB. Action cannot be changed (cancel). Canceled query is still **billed** for bytes read so far.
  - **Per-workgroup limits**: alerts (hourly/daily totals) via **CloudWatch alarm → SNS**. They do **not** cancel queries by themselves. Add actions: Lambda via SNS, or **disable the workgroup**.
  - One per-query limit per workgroup; multiple workgroup-level alerts.
- **Cost allocation tags** on workgroups → Cost Explorer / CUR by team.
- **Capacity reservations** for isolation and predictable cost.
- Glue Data Catalog permissions + LF tags for classification (PII).
- S3 bucket policies: results bucket with default encryption, block public access, versioning off, lifecycle.
- **Service control policies** can restrict who can create unencrypted workgroups (use minimum encryption).

## G. Pricing and cost control
- **SQL on-demand**: **$5 per TB scanned** (us-east-1 price; varies by Region). Billed on bytes read **before decompression**.
  - **Minimum 10 MB per query** (rounded up to the nearest MB).
  - **DDL** (CREATE/ALTER/DROP, SHOW) is free. **Failed queries** are not charged for scan (verify). **Canceled** queries are charged for data scanned before cancel. 
  - Unrelated but billed separately: **S3** requests/storage (data and results), **Glue** Data Catalog/crawlers, **KMS** calls, **Lambda** (federated/UDF), data transfer.
- **Provisioned capacity (capacity reservations)**: **$0.30 per DPU-hour** (page value), billed while the reservation is active; **minimum 4 DPUs**. No per-TB charge for queries in assigned workgroups.
  - Capacity is measured in **DPUs** (1 DPU ≈ 4 vCPU, 16 GB memory).
  - Each reservation can have workgroups assigned (max **20** per reservation). A workgroup belongs to **one** reservation.
  - Reservation requests take up to **30 minutes** to be ready. Capacity is not transferable across reservations, accounts, or Regions.
  - Queries on reserved capacity do **not** count toward on-demand DML/DDL quotas.
  - Athena gives each DML query **4–124 DPUs** automatically; each DDL query uses 4 DPUs.
  - If capacity is busy, queries **queue** (up to **10 hours**).
  - You can run reserved and on-demand workgroups in the same account.
  - Quotas: up to **100 reservations** and **1,000 DPUs** per account/Region by default (more on request). Not available in a few Regions (e.g., Tel Aviv, UAE, Bahrain, New Zealand) (verify).
  - Not for Spark workgroups.
  - Use **auto-adjust / scheduled** changes through APIs to scale capacity up for business hours and down after (verify the options).
  - Best when scan costs are high and steady, or you need guaranteed concurrency.
- **Spark**: about **$0.35 per DPU-hour** (workers + driver), billed per second after session start (verify billing granularity). Not by data scanned.
- **Federated**: scan charge (10 MB minimum) + Lambda.
- Ways to cut cost:
  - Parquet/ORC + compression.
  - Partitions + projection; filter on partition keys.
  - Avoid `SELECT *`.
  - Fewer, larger files.
  - CTAS to precompute; **result reuse**.
  - Per-query data limits and workgroup alerts.
  - Iceberg compaction so sorted/min-max skipping works.
  - Use `LIMIT` carefully: it doesn't reduce scan for non-columnar or when ordering.
  - Lifecycle rules on results and spill buckets.
- Example from the pricing page: 3 TB uncompressed text = $15/query; gzip at 3:1 = $5; Parquet at 3:1 + reading 1 of 4 columns = **$1.25**.

## H. Limits and numbers (cheat sheet)
- **Active DML queries** (running + queued): us-east-1 **200**; us-east-2, us-west-2, ap-northeast-1, eu-central-1, eu-west-1 **150**; several large Regions **100**; other Regions **20**. Adjustable. Over the quota → `TooManyRequestsException`.
- **Active DDL queries**: **20** per Region (adjustable).
- **DML timeout** default **30 min** (adjustable up to **240 min**). **DDL timeout 600 min**, not adjustable.
- **Query string length**: **262,144 bytes** (UTF-8), fixed.
- **StartQueryExecution** API: about **20/s** in small Regions, **100/s** in big ones, with burst multipliers (4–5×). Throttling → `ThrottlingException: Rate exceeded`.
- **GetQueryExecution**: 100–500/s. **GetQueryResults**: 100/s. Use `BatchGetQueryExecution` for many IDs.
- **Workgroups**: 1,000 per Region. **Prepared statements**: 1,000 per workgroup. **Tags**: 50 per workgroup.
- Console query tabs: 10 per workgroup; tabs persist for 3 workgroups.
- **Partitions**: 100 per CTAS/INSERT write; read up to 1,000,000 in one scan; Glue stores up to 10 million per table.
- **UNLOAD partitions**: 100.
- **Row/column size**: 32 MB. **Text line**: 200 MB.
- **Function args**: 127. **Array literal**: 254.
- **Capacity reservations**: 100 per account, 1,000 DPUs total, 4 DPU minimum, 20 workgroups per reservation, queue up to 10 hours.
- **Result reuse**: default 60 min, max 7 days, up to 20 tables.
- **Managed results**: 24 hours retention; 200 MB console download.
- **Spark**: concurrent DPU limit 160 per Region (Spark 3.5), on-demand DPUs 4 default (adjustable).
- **S3 buckets** default 10,000 per account (Athena needs a separate results bucket).
- **Engine**: Athena engine version 3 (Trino). Engine v2 (Presto-based) is retired/auto-upgraded (verify).
- **JDBC temporary credentials** max 12 hours when using role credentials.

## I. Scenarios: If X → Y, because Z
- If analysts must only see columns without PII → register the S3 location in Lake Formation and grant column-level SELECT, because Athena uses LF vended credentials.
- If a user must not read S3 directly but may query via Athena → LF-registered location (no direct S3 grants), or `aws:CalledVia` condition, because both force access through Athena.
- If the auditors need the real corporate identity in logs → IAM Identity Center–enabled workgroup + TIP + LF + S3 Access Grants, because identity is propagated end to end.
- If data is encrypted with a customer KMS key and queries fail → grant `kms:Decrypt` (and `GenerateDataKey` for results) in IAM and the key policy, because KMS has its own authorization.
- If every query must write to one encrypted bucket → workgroup with fixed results location, encryption, and Override client-side settings, because client settings get ignored.
- If one team's heavy queries starve others → capacity reservation for the critical workgroup, because it gets dedicated DPUs and bypasses account quotas.
- If a report workload scans 100 TB steadily every day → compare provisioned capacity ($/DPU-hour) with $5/TB, because reserved can be cheaper at steady high volume.
- If someone's runaway query scans 50 TB → per-query data limit (cancel) + workgroup alert, because limits cancel and alerts only notify.
- If costs must be charged back to teams → one workgroup per team with cost allocation tags, because the cost appears per tag.
- If query history exposes sensitive column names to other users → separate workgroups per audience, because history is workgroup-scoped.
- If auditors ask "who ran which SQL" → CloudTrail `StartQueryExecution` events (query text), because Athena does not keep long-term history for you.
- If Athena must not use the internet → interface VPC endpoints for Athena and Glue + S3 gateway endpoint, because traffic stays in the AWS network.
- If you need no results bucket to manage → managed query results (24 h), because Athena stores and deletes them for free.
- If millions of small SSE-KMS objects throttle KMS → S3 Bucket Keys, because they reduce KMS calls.
- If a Spark notebook needs LF permissions → use Spark 3.5 with SageMaker Unified Studio, not PySpark engine v3, because engine v3 doesn't support LF.

## Verified from AWS docs on 2026-10-25
Read from current AWS pages: Athena security overview, IAM topics list, encryption at rest, managed query results, Lake Formation + Athena (overview and limitations), IAM Identity Center–enabled workgroups, workgroup cost controls and data usage controls, capacity management, Service Quotas page and General Reference quotas table, Athena pricing page.
Not confirmed (verify): whether failed queries are free of scan charge, Spark billing granularity, query history retention (45 days), capacity auto-adjust options, exact Regions for capacity reservations and TIP, PCI/HIPAA compliance listing, engine v2 retirement date, `AWSQuicksightAthenaAccess` current name, Spark 3.5 Lake Formation support level, S3 Access Grants setup specifics.

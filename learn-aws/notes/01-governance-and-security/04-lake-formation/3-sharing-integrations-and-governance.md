# Lake Formation – 3. Sharing, integrations and governance

Short notes. Each point is a fact you can be asked about.

## A. Cross-account sharing: the idea
- Lake Formation lets one account (the **producer / owner**) share **Data Catalog databases and tables** with **other accounts, organizations, OUs, or IAM principals in another account**, with fine-grained control (table, column, row, cell).
- Users and Glue ETL jobs in the **consumer** account can **query and join** shared tables with other tables and still get Lake Formation protection.
- Under the hood Lake Formation uses **AWS Resource Access Manager (AWS RAM)** to share the catalog resource (named resource method). For LF-TBAC grants it uses **Data Catalog resource policies** at the lower versions and **RAM** at version 3+ (see section C).
- **No data is copied.** The consumer reads the **producer's S3 data** through Lake Formation credential vending (the **producer's registered location**).
- If the consumer account is in the **same AWS Organization** as the producer, the share is **available immediately**. If not, **AWS RAM sends an invitation** that the consumer's **data lake admin must accept** (RAM console or CLI).
- Two methods to share:
  1. **Named resource method**: `GRANT ... WITH GRANT OPTION` on a database, a table (optionally with column filtering), a few tables, or **All tables** in a database (wildcard).
  2. **LF-TBAC method** (**recommended**): share by LF-tag expression. Supports **organizations and OUs** (needs cross-account version 3 or above).
- **Direct cross-account share**: grant to **an IAM principal in the other account** (not just the account). The principal's permissions = **union** of direct grants and account-level grants cascaded to it. **Only the recipient** sees the direct grant. The recipient **cannot re-share** it.
- A grant to an **organization or OU counts as one grant** (best use of RAM capacity) and needs **no invitation** acceptance.
- Use the **All tables** wildcard instead of many table grants. It counts as one grant.

## B. Steps and what each side must do
- **Producer (owner) side**:
  1. The data lake admin needs the IAM policy **`AWSLakeFormationCrossAccountManager`** (a prerequisite for all versions), or equivalent RAM/Glue permissions.
  2. **Revoke `IAMAllowedPrincipals`** on the resource. Otherwise the share fails with *"Illegal combination"*.
  3. Register the S3 location and grant data permissions with **grant option** to the target account.
  4. For **organizations**: enable **RAM sharing with AWS Organizations** (the management account admin needs `ram:EnableSharingWithAwsOrganization`).
  5. If the account uses a **Glue Data Catalog resource policy**, add the special statement that lets **AWS RAM** share on your behalf (`glue:ShareResource`).
- **Consumer side**:
  1. The consumer's **data lake administrator** is the first person who can see the shared resource.
  2. If outside the organization, **accept the RAM invitation**.
  3. The admin **grants Lake Formation permissions on the shared resource to principals in their own account**. Only to **users in that account**. Not to other accounts, not to organizations, not to `IAMAllowedPrincipals`.
  4. Create **resource links** (section D) so Athena/Redshift Spectrum can query.
  5. Principals need **IAM permissions** (Glue read, `lakeformation:GetDataAccess`) and access to the underlying data through Lake Formation.
- **Rules**:
  - You **cannot grant DROP or Super on a database** to an external account.
  - A consumer admin who receives `CREATE_TABLE` on the owner's database can create tables in it. The consumer's user and admin hold all permissions on those tables but **cannot grant to principals in the owner account or other accounts**. Owner-account admins can grant on them within the owner account.
  - **Revoke cross-account permissions before deleting** a database or table. Otherwise you must clean up **orphan resource shares** in RAM.
  - The **crawler** in another account can crawl shared S3 data using **Lake Formation credentials** (cross-account crawling).
- **Data lake admin permissions** to grant cross-account include `glue:PutResourcePolicy` (used when the consumer accepts a share; error *"Association failed because the caller was not authorized"* if missing).

## C. Cross-account version settings (important)
- **Cross account version settings** (Data Catalog settings, or `CROSS_ACCOUNT_VERSION` in `put-data-lake-settings`) control **how RAM is used**. Accepted values 1 to 5.
- **Version 1**: named resource → **one RAM resource share per grant**. LF-TBAC → **no RAM**, uses Catalog **resource policy** (`glue:PutResourcePolicy`).
- **Version 2**: named resource → **many grants per RAM share** (saves RAM capacity). LF-TBAC → still resource policy. Grantor needs `AWSLakeFormationCrossAccountManager` (or `ram:AssociateResourceShare`, `ram:DisassociateResourceShare`, `ram:GetResourceShares` on `LakeFormation*` shares).
- **Version 3**: named resource same as v2. **LF-TBAC uses RAM** (add `glue:ShareResource` statement to Catalog resource policies; recipient accepts invitations). **New with v3**: share **directly with an IAM principal** in another account; LF-TBAC grants to **Organizations / OUs**; less Glue policy upkeep.
- **Version 4**: needed to share in **hybrid access mode** or share **federated catalog** objects.
- **Version 5**: **unlimited tables** per share through **wildcard patterns** instead of one association per resource. Share hundreds of thousands of tables. **No downgrade** after upgrading to 5.
- Version mismatch rule for LF-TBAC: if the **grantor is below v3 and the recipient is v3 or higher**, the grant fails (*"Invalid cross account grant request. Consumer account has opt-in to cross account version: v3"*). A v3 grantor can share to v1/v2 recipients.
- **Named resource** grants are **compatible across versions**. To share **directly with an IAM principal**, only the **grantor** needs v3.
- Changing the version **does not change** recipients' existing permissions. After choosing v2 or higher, all **new** named-resource grants use the new mode. To use RAM capacity well for old shares, **revoke and re-grant** them.
- RAM **managed permission versions**: older shares may lack `glue:GetUserDefinedFunctions` (EMR/Spark error). Update the RAM managed permissions to **version 3** or revoke and re-grant.

## D. Resource links
- A **resource link** = a Catalog object that **points to** a local or shared **database or table**. Use the link's name like a normal database/table name.
- Why you need them:
  - **Athena and Redshift Spectrum** must query **shared** resources through links in your account (queries use the **link name**).
  - **Rename** a shared table when two accounts use the same name.
  - Access a database/table from **another Region** by creating a link in that Region (query with Athena, EMR, Glue without copying data or metadata).
- Glue ETL scripts can use shared tables **without** a link, but use a link or the **catalog ID** to avoid name clashes.
- **Permissions**: creating a link needs **`CREATE_TABLE`** (table link) or **`CREATE_DATABASE`** (database link) plus `glue:CreateTable`/`CreateDatabase`. Only the **creator** sees the link (when IAM-only defaults are off). Grant **`DESCRIBE`** to let others see it, **`DROP`** to let others delete it.
- **A grant on a link is not a grant on the target.** You must grant permissions on the **target** separately.
- Creating a link does **not check** that the target exists. Deleting a link does **not** drop the target. Dropping the target does **not** delete links (they dangle).
- Links to links are possible but pointless (APIs follow only the first link).
- **Placeholder database trick**: when sharing directly with principals, the admin can create a **placeholder database** and grant `CREATE_TABLE` to **`ALLIAMPrincipals`**, so every principal can create its own links there.
- Querying one **database link** gives access to **all tables** shared with the **All tables** wildcard.

## E. Troubleshooting cross-account access (symptom → cause → fix)
- **Recipient cannot see the shared resource**:
  - Is the viewer a **data lake admin**? Only admins see it first.
  - Outside the organization, named-resource share? The admin must **accept the RAM invitation**.
  - Using Glue **Catalog resource policies**? Add the **RAM statement** (`glue:ShareResource`) for named resources.
  - Missing IAM permissions to grant cross-account.
  - **`IAMAllowedPrincipals`** still has permissions on the resource.
  - A **deny** statement in the Catalog resource policy.
- **Recipients see the table but cannot read the data** → missing **IAM** permissions for underlying data access (`lakeformation:GetDataAccess`) or no data permission granted.
- **"Association failed because the caller was not authorized"** accepting a RAM invitation → allow **`glue:PutResourcePolicy`** for the producer's role.
- **"Not authorized to grant permissions for the resource"** → you tried to grant on a resource shared **with** you to another account. Only to users in your account.
- **"Access denied to retrieve AWS Organization information"** → management account lacks Organizations read permissions.
- **"Organization <id> not found"** → sharing with organizations not enabled in RAM.
- **"Insufficient Lake Formation permissions: Illegal combination"** → `IAMAllowedPrincipals` still holds permissions on the resource you share.
- **ConcurrentModificationException** on grants → retry; use **batch** grant/revoke.
- **EMR error `glue:GetUserDefinedFunctions` not authorized** on a shared table → RAM managed permission **version 1/2** → update to **version 3**.
- **"Caller is temporarily not authorized ... resource"** when querying through a redirected link → use the **QuerySessionContext** protocol or wait about 24 hours.

## F. Integrations with analytics services
| Service | Table-level | Column-level | Row / cell-level |
|---|---|---|---|
| **Athena SQL** | read/write | read | read |
| **Athena Spark** | not supported | not supported | not supported |
| **Redshift Spectrum** (provisioned or Serverless) | read/write | read | read |
| **Spark on EMR (EC2)** | read/write | read | read |
| **Hive on EMR (EC2)** | read/write | read | not supported |
| **Spark on EMR Serverless** | read/write | read | read |
| **Hive on EMR Serverless** | not supported | not supported | not supported |
| **EMR on EKS** | not supported | not supported | not supported |
| **Glue ETL** | read/write | **Glue 5.0+**: read | **Glue 5.0+**: read |
- Each of these is a **trusted caller**: Lake Formation hands it **temporary credentials** for registered S3 data. **The service itself applies column/row filtering.**
- **Athena**: needs `lakeformation:GetDataAccess` on the **user**. **SAML** users can read Lake Formation-secured data with SAML federation (and insert into Parquet tables). Queries that use **manifests** are **not supported**.
- **Redshift Spectrum**: reads Catalog external tables with Lake Formation permissions. **Redshift data sharing** can be governed by Lake Formation (database, table, column, row access on datashares).
- **EMR**: register locations with a **custom role** (not the service-linked role). Roles need `lakeformation:GetDataAccess`. EMR Serverless Spark does **not** query Data Catalog **views**.
- **Glue**:
  - Job roles need Lake Formation permissions on the tables and `lakeformation:GetDataAccess`.
  - **Glue 5.0+** supports **fine-grained access control** (table, row, column, cell) for **read** on **Iceberg and Hive** tables backed by S3. In Glue 4.0 you set Spark catalog flags (`glue.lakeformation-enabled`, `glue.id`).
  - Tables with **cell-level filters** lose **bookmarks, bounded execution, pushdown predicates, catalog partition predicates, `enableUpdateCatalog`** in Glue jobs.
  - **Crawlers** can use Lake Formation credentials (same or cross-account).
- **Amazon Quick (QuickSight)**: grant to Quick users/groups (principal ARN with namespace `default`). Lake Formation permissions apply to datasets from Athena.
- **Transactional table formats** (support differs by engine):
  - **Iceberg**: Athena reads with table/column/row/cell permissions (writes need **full table access**); Redshift Spectrum read only; EMR Spark read, writes need full access; Glue 5.0+ read with fine-grained access.
  - **Hudi**: Athena read/create (no write); Redshift Spectrum read; EMR Spark read (writes need full access); Glue read/write with **table-level** permissions.
  - **Delta Lake**: Athena v3 read (native and symlink), no write; Redshift Spectrum reads symlink tables; EMR reads; Glue read/write with table-level permissions.
- **SageMaker** and **SageMaker lakehouse** use the same permissions.
- **CloudTrail Lake** integration exists for audit analysis.
- **Third-party engines**: you must **opt in** in **Application integration settings** ("Allow external engines to filter data in Amazon S3 locations registered with Lake Formation"), enter **session tag values** and the **AWS account IDs** allowed. Lake Formation hands the engine **unfiltered table metadata**, so **the engine's admin must filter correctly**. There is also **full-table credential vending** for engines without session tags.

## G. Federated catalogs, open table formats and lakehouse (governance angle)
- **Federated catalogs** let you set Lake Formation permissions on **Redshift, S3 Tables, DynamoDB and other external data** without migrating data or metadata. Use **LF-tags** across them.
- **Amazon Redshift federated catalogs do not generate `GetDataAccess`** events. Track access with **`GetTable` and `BatchGetTable`** in CloudTrail.
- **S3 Tables** buckets: catalog them and register the catalog as a Lake Formation data location.
- **Governed tables** (older Lake Formation table type with ACID transactions, automatic compaction by the "storage optimizer") exist in the docs and pricing page (metadata, API calls, optimizer bytes). Check current availability **(verify)**. **Iceberg on the Glue Catalog** is the common modern choice.
- **Table optimization** (compaction, snapshot expiry) for Iceberg is managed in the **Glue Data Catalog** (see the Glue guide).
- **Data Catalog views** (Athena/Glue views) can be shared with Lake Formation permissions **(verify)**.

## H. Audit and traceability
- **Every Lake Formation API call** is a **CloudTrail management event**: `PutDataLakeSettings`, `GrantPermissions`, `RevokePermissions`, `RegisterResource`, and more. You see who, from where, when, and success or error.
- **`GetDataAccess`**: logged whenever a principal or service requests **temporary credentials** for a **registered** location. The event shows **`requesterService`** (for example `GLUE_JOB`, ATHENA), the **`lakeFormationPrincipal`** (the role) and the **session name**. Principals do **not** call it directly.
- **Trace a read end to end**: each `s3:GetObject` data event corresponds to a `GetDataAccess` call. Link them with the **IAM role unique identifier** (AROA...) when **source identity tracking** is on:
  1. Set `"SET_SOURCE_IDENTITY": "TRUE"` in the data lake settings `Parameters` (via `put-data-lake-settings`).
  2. Add **`sts:SetSourceIdentity`** to the trust policy of the **registration role**.
  3. Enable **S3 data events** in CloudTrail (**extra cost**).
- Since **February 2026**, `s3:GetObject` logs for Lake Formation reads also carry the **initiating role's identifier**. Before, they showed only the **registration role**.
- **Cross-account logging**: both accounts get events for their own side. See the cross-account CloudTrail topic. Direct grants are visible **only to the recipient**.
- **IAM Identity Center** user context appears in logs when the registration role trust policy has `sts:SetContext`.
- **Lake Formation + CloudWatch**: registration with a custom role can publish **logs and metrics** to `/aws-lakeformation-acceleration/*` (charged).
- Use **CloudTrail Lake or Athena over CloudTrail logs** to answer "who read table X last week".
- **Read-only administrators** can view permissions and CloudTrail lookups.

## I. Governance patterns (exam skill: governance framework and sharing patterns)
- **Hub-and-spoke (central catalog)**: one **producer/governance account** owns the catalog and registered locations. **Consumer accounts** get shares (by tag, by org/OU) and create resource links.
- **Data mesh**: each domain account owns its data, publishes **data products** with Lake Formation shares. Central team owns **LF-tag taxonomy** and standards. **SageMaker Catalog** adds discovery and subscription workflows.
- **Tag taxonomy**: choose a few stable keys (`domain`, `classification`, `pii`, `environment`). Assign at **database** level, override at table/column. Grant by expressions to **roles/groups**, not individuals.
- **Separation of duties**: keep the **data lake admin** list small. Use **LF-tag creators** for tag management. Use **read-only admin** for auditors.
- **Least privilege**: avoid `Super` and `IAMAllowedPrincipals`. Grant **without grant option** unless delegating on purpose.
- **PII handling**: **Macie** finds sensitive data → tag resources (for example `pii=true`) → grant PII tags only to approved roles → use **column/cell filters** to hide fields.
- **Sharing outside the org**: named resource grant to an **account** (RAM invitation) with **column/row filters**, or **AWS Data Exchange** to license data.
- **Migration path**: start **hybrid access mode**, opt in a use case, then expand. Finally remove `IAMAllowedPrincipals`.
- **Multi-Region**: use **resource links** across Regions and **cross-Region** S3/replication for the data **(verify limits)**.
- **Prevent leakage**: block direct S3 access for analysts (IAM/bucket policy), enforce **VPC endpoints**, encrypt with KMS, log with CloudTrail.

## J. Scenarios (if → then, because)
- **If** another account in your **AWS Organization** needs read access to many tables, **then** grant by **LF-tag expression** to its **organizational unit (OU)**, which needs **cross-account version 3** or higher. **This works because** a grant to an organization or OU counts as **one grant** in **AWS Resource Access Manager (RAM)** and needs **no invitation**; inside the same Organization the share is available immediately.
- **If** an external partner account needs only some columns and only EU rows, **then** make a **named-resource grant with a data filter** (column list plus row filter) to that **account**. **This works because** the partner reads the producer's S3 data through Lake Formation **without any copy**, and the filter limits both columns and rows. Outside the Organization, the partner's admin must **accept the AWS Resource Access Manager (RAM) invitation**.
- **If** a consumer cannot query a shared table in **Amazon Athena**, **then** create a **resource link** in the consumer account and query the **link name**. **This works because** Athena and Redshift Spectrum query shared resources through local links. A grant on the link is **not** a grant on the target, so grant on the target too.
- **If** a table share fails or seems stuck, **then** **revoke `IAMAllowedPrincipals`** on it. **This works because** you cannot share a resource cross-account while that group still has permissions on it; the error is *"Insufficient Lake Formation permissions: Illegal combination"*.
- **If** many tables are shared and **AWS Resource Access Manager (RAM)** limits are near, **then** use **cross-account version 2** or higher (many grants per RAM share), grant to an **OU or organization**, use the **All tables** wildcard, or move to **version 5**. **This works because** each of these packs more access into fewer RAM shares, and version 5 allows **unlimited tables** per share through wildcard patterns. You **cannot downgrade** from version 5, and old shares only benefit after you **revoke and re-grant** them.
- **If** a consumer account must give its analysts access to a shared table, **then** the consumer's **data lake administrator** grants Lake Formation permissions on it to **principals in their own account**. **This works because** a consumer can grant a shared resource only inside its own account, never to other accounts or organizations.
- **If** a recipient account wants to give shared data to a third account, **then** it **cannot**; the **owner (producer)** account must grant it directly. **This works because** recipients may grant only to users in their own account; trying otherwise gives *"Not authorized to grant permissions for the resource"*.
- **If** an **AWS Glue** ETL job in the consumer account needs a shared table, **then** refer to it by the owner's **catalog ID** or through a **resource link**, and give the job role Lake Formation **`SELECT`** plus `lakeformation:GetDataAccess`. **This works because** Glue can read shared tables without a link, but the same table name may exist in both accounts, and the job role still needs both permission gates.
- **If** a **Glue 4.0** job needs column-level security, **then** upgrade to **Glue 5.0** or later (or use **Amazon Athena** or **Amazon EMR**). **This works because** Glue 5.0+ supports **fine-grained read** access (table, column, row, cell) on Iceberg and Hive tables in S3.
- **If** **Athena Spark** must respect Lake Formation permissions, **then** it cannot; use **Athena SQL**, **Spark on Amazon EMR** or **AWS Glue** instead. **This works because** Lake Formation does **not support** Athena Spark at any level (table, column or row).
- **If** a third-party Spark engine must read the lake, **then** turn on external engine access in **Application integration settings** and enter the **session tag values** and allowed **AWS account IDs**. **This works because** Lake Formation then vends credentials to that engine. The engine receives **unfiltered table metadata**, so you must **trust its admin** to apply the filters correctly.
- **If** you must answer "who read this table", **then** look at **AWS CloudTrail** `GetDataAccess` events, and for the exact S3 reads add **S3 data events** with **source identity** tracking. **This works because** `GetDataAccess` is logged whenever a service asks for credentials (showing the service and role), and source identity links each `s3:GetObject` back to that call. S3 data events **cost extra**.
- **If** an auditor needs to view permissions without change rights, **then** make them a **read-only administrator**. **This works because** this role can **view** principals, catalog resources, permissions and **AWS CloudTrail** logs but **cannot change** anything.
- **If** you need to **license** your data to others, **then** use the **AWS Data Exchange** integration. **This works because** Lake Formation data can be licensed to subscribers through Data Exchange.
- **If** **Amazon Redshift** tables in the catalog must be governed with LF-tags, **then** use a **federated Redshift catalog** governed by Lake Formation, and audit with **`GetTable`** / `BatchGetTable` events. **This works because** federated catalogs put Redshift data under Lake Formation **without moving** it. Redshift federated catalogs produce **no `GetDataAccess`** events.
- **If** a cross-account **Amazon EMR** or Spark job fails with "not authorized to perform `glue:GetUserDefinedFunctions`", **then** update the share's **AWS Resource Access Manager (RAM) managed permissions to version 3** (or revoke and re-grant). **This works because** older shares (managed permission version 1 or 2) lack that Glue action.

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: cross-account overview, version settings (1–5), cross-account best practices, troubleshooting (cross-account and general), resource links, working with other AWS services (support matrices), CloudTrail logging (including GetDataAccess and the Feb 2026 source-identity change), personas and managed policies, application integration for external engines (from the setup page).
Not confirmed (verify): current availability of governed tables, Data Catalog view sharing rules, cross-Region data access limits, exact RAM share count limits, full-table credential vending details, Quick/QuickSight dataset behavior, Redshift datashare governance details, exact Regions for features.

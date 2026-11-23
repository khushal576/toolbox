# Lake Formation – 1. Basics, how access works and setup

Short notes. Each point is a fact you can be asked about.

## A. What Lake Formation is
- **AWS Lake Formation** = a service to **centrally govern, secure and share** data lake data. It manages **who can see which data** in S3 and in the Glue Data Catalog.
- It **does not store data**. Data stays in **S3** (or in connected stores). **Metadata** lives in the **AWS Glue Data Catalog**. Lake Formation adds a **permission layer** on top.
- It has its **own permission model** that **augments IAM**. You manage access with simple **GRANT / REVOKE**, like a relational database.
- It enforces access at **database, table, column, row and cell** level across **Athena, Redshift Spectrum, EMR, Glue and QuickSight (Amazon Quick)**.
- Main features:
  - **Fine-grained access control** (named resources, **LF-tags**, **data filters**).
  - **Cross-account and organization sharing**.
  - **Hybrid access mode** (move from IAM-only to Lake Formation step by step).
  - **Audit** through CloudTrail.
  - **Federated catalogs** (Redshift, S3 Tables, external sources) managed in one place.
  - Older ingestion helpers: **blueprints and workflows** (Glue crawlers/jobs) to import from databases **(verify how current)**.
- Lake Formation is **free to use for permissions**. You pay for the services and storage underneath (file 4).
- It uses the **Glue Data Catalog** as its catalog. A "Lake Formation table" is a Glue table. Lake Formation is the **governance layer**, Glue is the **catalog and ETL layer**.

## B. Pick it when / avoid it when / alternatives
- Pick Lake Formation when:
  - Many people and teams need **different slices** of the same data (columns, rows).
  - You need **column-, row- or cell-level** security without copying data.
  - You manage **hundreds of tables** and want **tag-based** access (LF-tags).
  - You must **share data across accounts or an AWS Organization** with control.
  - You want **one place** to grant, revoke and audit for Athena, Redshift Spectrum, EMR and Glue.
- Avoid or reconsider when:
  - One team, few tables, simple "read this bucket" needs → **IAM + S3 bucket policies** are enough.
  - Access to **objects by prefix** for apps, not analytics → **S3 Access Grants / access points** **(verify)**.
  - You need a **business glossary and data discovery** for analysts → **SageMaker Catalog** (DataZone-based). Lake Formation is the technical control plane.
  - Finding PII in S3 → **Macie**. Lake Formation then **enforces** who sees it.
  - Restricting rows **inside Redshift tables** → Redshift's own row-level security and masking.
- Lake Formation vs **IAM-only**: IAM controls broad actions and S3 paths (coarse). Lake Formation controls **table/column/row** (fine). They **work together**: **both must allow**.
- Lake Formation vs **S3 bucket policy**: a bucket policy cannot say "this user sees only these columns".
- Lake Formation vs **Glue Data Catalog resource policy**: resource policies can share catalog metadata across accounts, but Lake Formation gives fine-grained data permissions and tag-based control.

## C. Key terms
- **Principal**: who gets permissions. IAM user or role, SAML user or group, **IAM Identity Center** user or group, Amazon Quick user or group, **AWS account**, **organization**, **OU**.
- **Resource**: what is protected. **Catalog, database, table, view, column, S3 data location, LF-tag, data cells filter, resource link.**
- **Data lake administrator**: a principal who can grant Lake Formation permissions on **any** resource and register locations. The first people able to grant permissions.
- **Registered location**: an S3 path (bucket or prefix) that you **register** so Lake Formation controls access to the data under it.
- **Credential vending**: Lake Formation gives **temporary, scoped-down credentials** to an integrated service so it can read the data. Users do not use their own S3 permissions for that data.
- **Integrated (trusted) service**: Athena, Redshift Spectrum, EMR, Glue, Amazon Quick. They ask Lake Formation for permission and credentials.
- **LF-tag**: a key-value label (for example `classification=restricted`) used for tag-based access.
- **Data filter (data cells filter)**: a saved column + row rule on a table.
- **Resource link**: a Catalog object that points to a database or table (often in another account).
- **IAMAllowedPrincipals**: a special group that keeps the **old IAM-only behavior** on a resource (details in section F).

## D. How a query is authorized (the flow)
1. A user runs a query in **Athena** (or Spark, Redshift Spectrum...). Athena calls the **Glue Data Catalog** for the table.
2. **IAM** must allow the Glue read calls (for example `glue:GetTable`, `glue:GetDatabase`, `glue:GetPartitions`). Lake Formation permission is checked too. The catalog returns **only the columns the user may see**.
3. The service asks Lake Formation for data access (**`lakeformation:GetDataAccess`**). Lake Formation checks the user's **Lake Formation permission** (for example `SELECT`) on the table.
4. If allowed, Lake Formation **assumes the registered location's IAM role** and returns **temporary credentials** limited to that data.
5. The service reads S3 with those credentials. **Column and row filtering is applied by the integrated service** when it processes the query.
6. CloudTrail records `GetDataAccess` (who, which service, which role).
- Two gates, always: **IAM permission** + **Lake Formation permission**. A grant in one does not replace the other.
- A principal needs the IAM action **`lakeformation:GetDataAccess`** (resource `*`). Athena needs it on the **user**. Other services need it on their **execution role** (Glue job role, EMR role, and so on).
- Lake Formation does **not** block someone who can reach S3 **directly** through IAM or bucket policy. To enforce Lake Formation fully, **remove direct S3 access** for those principals (deny or do not grant it).

## E. First-time setup (the order)
1. **Create a data lake administrator.**
   - Admins are, at first, the **only** principals who can grant Lake Formation permissions (to anyone, including themselves).
   - Default limit: **30** data lake administrators. Create them with the console or `PutDataLakeSettings`. IAM permissions needed: `lakeformation:PutDataLakeSettings` and `GetDataLakeSettings`.
   - AWS advises **not** using a user with `AdministratorAccess` as the data lake admin.
   - Attach **`AWSLakeFormationDataAdmin`** (mandatory). It **explicitly denies `PutDataLakeSettings`**, so a user with only this policy **cannot create new admins**.
   - Optional policies: `AWSLakeFormationCrossAccountManager` (cross-account grants), `AWSGlueConsoleFullAccess` + `CloudWatchLogsReadOnlyAccess` (troubleshoot workflows), `AmazonAthenaFullAccess` (run queries).
   - Inline policy to allow creating the **service-linked role** (`iam:CreateServiceLinkedRole` for `lakeformation.amazonaws.com` + `iam:PutRolePolicy` on `AWSServiceRoleForLakeFormationDataAccess`).
   - For cross-account work add RAM actions (`ram:AcceptResourceShareInvitation`, `ram:RejectResourceShareInvitation`, `ec2:DescribeAvailabilityZones`, and `ram:EnableSharingWithAwsOrganization` in the Organizations management account).
2. **Change the default permission model** (or use **hybrid access mode**).
3. **Register an S3 location** (section G).
4. **Assign permissions** to users (Lake Formation grants + IAM).
5. (Optional) **IAM Identity Center** integration (trusted identity propagation) **(verify details)**.
6. (Optional) **Application integration / external data filtering** for third-party engines (section I).
7. (Optional) Give principals IAM access to the **Data Catalog encryption KMS key** if the catalog is encrypted. Without it you get *"Insufficient encryption key permissions for Glue API"* when granting.
8. (Optional) Create a **workflow role** for blueprints/workflows.
- A **CloudFormation template** can do most of these steps, except changing default settings and IAM Identity Center.

## F. The two permission models and `IAMAllowedPrincipals`
- Lake Formation starts with **"Use only IAM access control"** turned **on** for compatibility with existing Glue behavior. New databases and tables get **`Super` permission for the `IAMAllowedPrincipals` group**. Result: access is decided by **IAM and S3 policies only**.
- **`IAMAllowedPrincipals`** = a built-in group of **all IAM users and roles allowed by their IAM policies** to reach the resource. If it holds `Super` on a database or table, **Lake Formation permissions are not enforced** there.
- Two settings in **Data Catalog settings** (both **on by default**):
  - "Use only IAM access control for **new databases**".
  - "Use only IAM access control for **new tables in new databases**" (only sets the default tick box in the create-database dialog).
- To make Lake Formation permissions **really apply** you must either:
  - **Revoke `IAMAllowedPrincipals`** from the database/table (and from the **database creators** list), or
  - Use **hybrid access mode** (opt in principals and resources).
- Warning: switching defaults can **break automation and ETL jobs** that create tables, because the creator now needs explicit Lake Formation permissions. Grant them first.
- **Sharing blocker**: you cannot share a resource cross-account while `IAMAllowedPrincipals` still has permissions on it. Error: *"Insufficient Lake Formation permissions: Illegal combination"*. Revoke first.
- **`ALLIAMPrincipals`** (`<account-id>:IAMPrincipals`): a different group. Granting to it gives **every IAM principal in the account** access **through Lake Formation plus IAM** (still both checks).
- **Upgrading existing Glue data permissions** (existing databases and tables): do not just flip the default settings. Follow the upgrade steps: register locations, **re-create the access you had as Lake Formation grants**, then **revoke `IAMAllowedPrincipals`** per resource **(verify steps)**.

## G. Registering an S3 location
- **Why**: only **registered** locations get Lake Formation credential vending and permission enforcement for the data underneath. Registering a path also covers **all folders under it**.
- You register a **bucket or prefix**, never a single object.
- At registration you choose an **IAM role** that Lake Formation assumes to read/write the data and vend credentials:
  - **Service-linked role** `AWSServiceRoleForLakeFormationDataAccess` (default, simplest). Policy `LakeFormationDataAccessServiceRolePolicy`.
  - **Custom (user-defined) role** when you need more.
- **Use a custom role** when:
  - The bucket is in **another account**.
  - Data is encrypted with the **AWS managed key `aws/s3`** (and for customer-managed keys the role needs KMS permissions) **(verify details)**.
  - You will use **Amazon EMR** on the location (if registered with the SLR, deregister and re-register with a custom role).
  - You want Lake Formation to publish **CloudWatch Logs/metrics** (log group `/aws-lakeformation-acceleration/*`, which **incurs a charge**).
  - You want to **edit** the registration later. You **cannot edit** a location registered with the SLR. You must **deregister and register again**.
- **Custom role requirements**:
  - Trust policy allows **`lakeformation.amazonaws.com`** for `sts:AssumeRole` and `sts:SetContext` (SetContext adds IAM Identity Center user context to logs).
  - Inline policy: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on `bucket/*` and `s3:ListBucket` on the bucket.
  - The data lake admin who registers needs **`iam:PassRole`** on that role.
- Registration options in the console: **Review location permissions** (shows existing resources and their permissions at that path, because registering may expose data already there), **Hybrid access mode**, **Enable Data Catalog federation**, and **Register S3 path with owner account** (verify access of the role and vend credentials; flag `--expected-resource-owner-account`).
- Do **not** register a bucket with **Requester Pays** enabled. The registration role counts as the requester, so the bucket owner can end up paying.
- After registration, a Glue table at that path (or child path) shows **`IsRegisteredWithLakeFormation = true`** in **`GetTable`**. `GetTables` and `SearchTables` may still show `false` (known limit). Use `GetTable`.
- CLI: `aws lakeformation register-resource --resource-arn arn:aws:s3:::<path> --use-service-linked-role` (or `--role-arn`). Update with `update-resource` (custom role only).
- **Data location permission** (`DATA_LOCATION_ACCESS`) is different: it only controls who may **create or alter catalog entries that point to** a registered location (file 2).
- Registered locations should not **overlap in confusing ways** (a child path of a registered path is already covered). Nested registration rules **(verify)**.

## H. Hybrid access mode
- **Hybrid access mode** = two paths to the **same** Catalog objects:
  1. **Opted-in principals** use **Lake Formation permissions** (and still need IAM permissions).
  2. **All other principals** keep using **IAM policies** for S3 and Glue.
- It lets you **adopt Lake Formation one use case at a time** without breaking existing users. AWS recommends it for migration.
- You turn it on per **S3 location** (register with `--hybrid-access-enabled`) and then **opt in principals** to specific **databases/tables** (`CreateLakeFormationOptIn`).
- In hybrid mode, Lake Formation enforces by default only **`CREATE_TABLE`, `CREATE_PARTITION`, `UPDATE_TABLE`** style permissions. Data access is enforced **only for opted-in principals**.
- Resource types in this model:
  - **Lake Formation resource**: registered, users need LF permissions.
  - **AWS Glue resource**: not registered, `IAMAllowedPrincipals` has `Super`, only IAM applies.
  - **Hybrid resource**: switches by **who** is accessing.
- Limits and rules:
  - Only **data lake administrators** (and read-only admins to view) can use hybrid mode and **opt in** principals.
  - You **cannot edit** a location registered with the **service-linked role** (re-register).
  - Updating an **already registered** location to hybrid is **not recommended** (but possible). Opt in current principals first, grant `Super` to `IAMAllowedPrincipals`.
  - For **cross-account** sharing in hybrid mode you need **cross-account version 4** (file 3). When opting in all tables of a database cross-account, **opt in the database too**.
  - Create/update table or database on a location registered in hybrid mode still **requires data location permission**.
- Exam angle: "migrate to Lake Formation without disrupting existing users" → **hybrid access mode**.

## I. Personas (who does what)
- **IAM administrator**: creates IAM users and roles, adds data lake admins. Has all permissions but **cannot grant Lake Formation permissions unless also a data lake admin**.
- **Data lake administrator**: registers locations, creates databases, grants permissions, creates and runs workflows, views CloudTrail. **Cannot add other admins** (with the managed policy). Needs `iam:PassRole` for workflow roles.
- **Read-only administrator**: can **view** principals, catalog resources, permissions and CloudTrail logs, **no changes**. Policy denies `PutDataLakeSettings`.
- **Data engineer**: creates databases (as a **database creator**), crawlers and workflows, grants permissions on tables they create. Needs `lakeformation:GetDataAccess`, `GrantPermissions`, `RevokePermissions`, LF-tag actions.
- **Data analyst**: runs queries (for example Athena). Needs `lakeformation:GetDataAccess` and Glue read actions plus Lake Formation `SELECT` grants.
- **Workflow role**: role a Lake Formation workflow runs as. Needs `AWSGlueServiceRole`, `lakeformation:GetDataAccess` and `GrantPermissions`, and `iam:PassRole` for itself.
- **Admins added after a database exists** can grant permissions but **do not automatically get data access** (`SELECT`, `DESCRIBE`) on it. They must grant themselves. An admin who **creates** a database gets `Super` on it.
- **Database creator**: a principal with `CREATE_DATABASE` on the catalog. Creators become owners of what they create (metadata permissions, **no data permissions** by default).
- **Analyst minimum IAM policy** (examples): `lakeformation:GetDataAccess`, `glue:GetTable`, `GetTables`, `SearchTables`, `GetDatabase`, `GetDatabases`, `GetPartitions`, and LF-tag read actions (`lakeformation:GetResourceLFTags`, `ListLFTags`, `GetLFTag`, `SearchTablesByLFTags`, `SearchDatabasesByLFTags`).
- **Managed policies** to know: `AWSLakeFormationDataAdmin`, `AWSLakeFormationCrossAccountManager`, `AWSGlueConsoleFullAccess`, `LakeFormationDataAccessServiceRolePolicy` (service-linked role only, cannot attach to users).

## J. Bringing data into the Catalog (federation and ingestion)
- You can bring **external data** under Lake Formation governance **without moving it**:
  - **Amazon Redshift** namespaces/clusters → a **multi-level federated catalog**; query with Iceberg REST-compatible engines (for example Athena, EMR Serverless).
  - **External sources** through Glue connections (for example DynamoDB, SQL Server, Snowflake) → **federated catalogs** with permissions in Lake Formation. Register the same S3 location **with federation** when needed.
  - **Amazon S3 Tables** → catalog them and register the catalog as a data location.
  - **Redshift managed catalog** (`glue:CreateCatalog`, type Managed, source Redshift).
  - **Redshift data sharing** governed by Lake Formation (database, table, column, row permissions on datashares).
  - **External Hive metastores** (permissions on S3 data with metastore metadata).
  - **AWS Data Exchange** licensing of Lake Formation data.
- **Blueprints and workflows** can import from **RDS/EC2-hosted MySQL, PostgreSQL, SQL Server, MariaDB, Oracle**, and JDBC sources (bulk and incremental) **(verify if still offered for new work)**. Many teams now use **Glue ETL, DMS or zero-ETL** instead.
- **LF-tag support** covers federated catalogs (S3 Tables, Redshift, DynamoDB, SQL Server, Snowflake) **(verify per source)**.

## K. Scenarios (if → then, because)
- If analysts need different columns of one table → **Lake Formation column filtering** (or a data filter), because one copy of data serves everyone.
- If only IAM and S3 policies exist and you want table/column control → register the location, move to Lake Formation permissions, **revoke `IAMAllowedPrincipals`** or use hybrid mode.
- If you cannot disrupt existing jobs while you adopt Lake Formation → **hybrid access mode**, because only opted-in principals are enforced.
- If a user has a Lake Formation `SELECT` grant but Athena says access denied → check **IAM** (`lakeformation:GetDataAccess`, Glue read actions) and that the **location is registered**, because both gates apply.
- If a user can still read the data in S3 directly → fix IAM/bucket policy, because Lake Formation does not block direct S3 access.
- If Lake Formation grants seem ignored on a table → `IAMAllowedPrincipals` still has `Super`, so IAM alone decides. Revoke it.
- If a new admin cannot see existing databases → admins do not get automatic data permissions on older resources. Grant them.
- If a bucket uses the AWS managed key `aws/s3` → register it with a **custom role**, because the service-linked role does not cover it.
- If you will use **EMR** on a location → register with a **custom role** (re-register if the SLR was used).
- If you need to change a registered location's role → SLR: deregister and register again. Custom role: `update-resource`.
- If a catalog is encrypted and granting fails with an encryption key error → give the granter KMS permissions on the **Data Catalog key**.
- If an ETL job's automation breaks after turning off the IAM-only defaults → grant the job role the needed Lake Formation permissions (`CREATE_TABLE`, data location) first.
- If you must stop someone from sharing data they do not own → keep the **admin list small** and avoid `AdministratorAccess` as the admin.
- If you need to unify Redshift data with the S3 lake and govern both → **federated Redshift catalog** governed by Lake Formation.
- If a team wants a business glossary and request/approval workflow for datasets → **SageMaker Catalog**, with Lake Formation enforcing the technical permissions underneath.

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: what Lake Formation is and features, setup steps and admin policies, personas and managed policies, registering an S3 location and role requirements, underlying data access control, hybrid access mode and its considerations, permissions reference (IAMAllowedPrincipals, defaults), working with services.
Not confirmed (verify): current state of blueprints/workflows for new customers, S3 Access Grants comparison, IAM Identity Center integration details, upgrade-from-Glue steps, nested registered-location rules, KMS role requirements for customer-managed keys, LF-tag support per federated source, exact Region availability of features.

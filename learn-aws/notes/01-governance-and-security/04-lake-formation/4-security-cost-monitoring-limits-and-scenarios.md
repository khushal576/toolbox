# Lake Formation – 4. Security, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Securing Lake Formation itself
- **Who controls Lake Formation**: the **data lake administrators**. Keep the list **small** (default max **30**). Review it often.
- **Do not** make a user with **`AdministratorAccess`** the data lake admin (AWS advice). Use a dedicated admin role with **`AWSLakeFormationDataAdmin`**.
- `AWSLakeFormationDataAdmin` **denies `lakeformation:PutDataLakeSettings`**, so holders **cannot create new admins**. Only an IAM admin (or someone with that action) can.
- **Restrict who can change settings**: use **IAM policies or SCPs** to limit powerful actions: `PutDataLakeSettings`, `RegisterResource`, `GrantPermissions`, `RevokePermissions`, `CreateLFTag`, `CreateLakeFormationOptIn` **(verify action list)**.
- **LF-tag creators** let you delegate tag management without full admin rights.
- **Use groups/roles** (IAM roles, Identity Center groups) as principals. Avoid granting to many individual users.
- **Grant without grant option** unless you mean to delegate.
- Avoid **`Super`** and avoid leaving **`IAMAllowedPrincipals`** on resources you want governed.
- Do not grant to **`ALLIAMPrincipals`** unless you really want "everyone in the account" (they still need IAM).
- **Block direct S3 access**: Lake Formation does not stop someone who has S3 permission through **IAM or a bucket policy**. Remove those permissions (or deny them) for analysts. Allow S3 access only to **admins, the registration role and pipelines**.
- **Separate roles** for pipelines (ETL write) and analysts (read). Give each Lake Formation permissions to match.
- **Catalog is shared infrastructure**: Lake Formation permissions apply to **Glue Data Catalog** objects. Make sure **Glue IAM actions** (such as `glue:UpdateTable`) are also controlled, because Glue API calls can change metadata.
- Use **tags/naming** to separate dev, test and prod catalogs (or separate accounts).

## B. Encryption
- **S3 data**: use **SSE-S3 or SSE-KMS** on the bucket. Lake Formation works with encrypted locations. For **KMS**, the **registration role** (and any role that reads the data) needs the key permissions (`kms:Decrypt`, `kms:GenerateDataKey`, and so on).
- A bucket encrypted with the **AWS managed key `aws/s3`** must be registered with a **custom role** (not the service-linked role). For **cross-account encrypted** locations, use a **customer managed key** with a policy that allows the other account's role. (`aws/s3` keys **cannot be shared** across accounts.) **(verify details)**
- **Data Catalog encryption** (Glue setting): metadata encrypted with KMS. Principals who **grant** Lake Formation permissions on an **encrypted catalog** need **KMS permissions** on the catalog key. Otherwise: *"Insufficient encryption key permissions for Glue API"*.
- **Partition indexes** cannot be created on **encrypted partitions** (Glue limit).
- **In transit**: TLS for all AWS API calls and for credential vending to services.
- **Iceberg** tables have their own S3 SSE settings. Set them in addition to bucket defaults.
- **Cross-account**: both the **producer's KMS key policy** and the **consumer's roles** must allow decrypt.

## C. Network and private access
- Lake Formation supports **interface VPC endpoints (AWS PrivateLink)** so API calls stay on the AWS network **(verify service name and endpoint policy support)**.
- Glue jobs and Athena run with their own network rules. If a Glue job in a VPC reads Lake Formation-governed data, it still needs a route to **S3, Glue, Lake Formation and KMS** (endpoints or NAT).
- Use **S3 gateway endpoints** and **bucket policies** with `aws:SourceVpce` to keep S3 access private.
- Use **endpoint policies** to limit which buckets and actions a VPC endpoint allows.

## D. Service-linked role and registration role security
- The **service-linked role** `AWSServiceRoleForLakeFormationDataAccess` is simple and AWS-managed. It cannot be edited and has limits (for example no cross-account, no `aws/s3` key, no edit of registration, not for EMR).
- A **custom registration role** is yours to scope tightly: only the S3 prefix it must serve, plus KMS and (optional) CloudWatch Logs permissions.
- **Anyone who can pass or change** the registration role can influence data access. Protect it with IAM (limit `iam:PassRole`, who can edit the role policy).
- **Trust policy** must trust `lakeformation.amazonaws.com` (`sts:AssumeRole`, `sts:SetContext`, and optionally `sts:SetSourceIdentity`).
- **Requester Pays** buckets: avoid registering them (the role becomes the requester).

## E. Cost
- **Lake Formation permissions and cross-account sharing are free** ("at no charge"). Using permissions through integrated services is also free of Lake Formation fees.
- You still pay for the **underlying services**:
  - **Glue Data Catalog**: free first **1 million** objects and **1 million** requests a month, then per-object and per-request charges (see the Glue guide).
  - **S3** storage and requests, **Athena** scans, **Redshift** compute, **EMR**, **Glue ETL**, **QuickSight**.
- **Storage API (data filtering)**: billed **per byte scanned**, **rounded up to the next MB**, **10 MB minimum per scan**. It applies only when data is read **through Lake Formation's own API** and **no other AWS analytics service** processes it (for example custom or third-party engines). Use **Parquet/ORC** and **partition pruning** to scan less.
- **Governed tables** (if used): billed for the **number of files tracked (metadata)**, **API calls** that read or change metadata, and **bytes processed by the storage optimizer** (rounded to the next MB). The optimizer compacts small files. Other table types use the **Glue Data Catalog pricing** for optimization **(verify current state)**.
- **CloudTrail**: management events are in the default event history. **S3 data events** (needed to trace reads) and extra trails **cost extra**.
- **CloudWatch Logs**: a custom registration role that writes to `/aws-lakeformation-acceleration/*` **incurs charges**.
- **AWS RAM** itself is free. **KMS** requests (SSE-KMS) cost per request. **NAT** data processing can add up for VPC jobs.
- **Save cost**: avoid copying data per team (use filters/tags), use **columnar formats**, **partition**, **compact files**, share by **OU/All tables** (fewer shares to manage), and delete unused links/shares.
- **Hidden cost of copying**: copying data for security means extra storage and stale data. Lake Formation filters avoid that.

## F. Monitoring and finding out what a principal can do
- **Console "Data permissions" page**: list grants by **principal or resource**. Also **Administrative roles and tasks**, **Data lake locations**, **LF-Tags and permissions**, **Hybrid access mode** opt-ins.
- **CLI**: `list-permissions` (who has what on a resource), `get-effective-permissions-for-path` (what applies to an S3 path), `list-lake-formation-opt-ins` (hybrid mode), `get-data-lake-settings`, `list-resources` (registered locations).
- **CloudTrail**: `GrantPermissions`, `RevokePermissions`, `PutDataLakeSettings`, `RegisterResource`, and **`GetDataAccess`** (reads). Send logs to S3/CloudWatch Logs and alert on high-risk events.
- **EventBridge/CloudWatch alarms** on CloudTrail events (for example someone granting `Super` or removing admins) **(verify built-in Lake Formation events)**.
- **Athena over CloudTrail logs** or **CloudTrail Lake** to answer "who accessed table X" using `GetDataAccess` and (with source identity) `s3:GetObject`.
- **Amazon Redshift federated catalogs** produce **no `GetDataAccess`** events. Watch **`GetTable`/`BatchGetTable`**.
- **AWS Config** can track IAM and S3 policy drift that bypasses Lake Formation **(verify supported resource types)**.
- Review **IAMAllowedPrincipals** and **ALLIAMPrincipals** grants regularly. Review the **admin list**.

## G. Troubleshooting (symptom → cause → fix)
- **Athena: "Access denied" or "Insufficient Lake Formation permission(s)"** although you granted `SELECT` → missing IAM (`lakeformation:GetDataAccess`, Glue read actions), location **not registered**, wrong principal (role vs user), or Glue resource policy deny.
- **User sees no tables** → no `DESCRIBE`/any permission on the database/table, IAM Glue read actions missing, or the table is a **resource link** the user cannot describe.
- **User sees tables but queries return zero rows** → **row filter** excludes everything, or data in a different partition/location, or the filter expression is case-sensitive and does not match.
- **Query fails on a column** → column is **excluded** by the column filter. Query only included columns.
- **Lake Formation grants seem ignored** → **`IAMAllowedPrincipals` has `Super`** on the resource. Revoke it (or use hybrid mode and opt in).
- **User can read S3 directly** → IAM/bucket policy allows it. Remove it.
- **"Insufficient Lake Formation permissions on <S3 location>"** → missing **`DATA_LOCATION_ACCESS`** (needed with `CREATE_TABLE`/`ALTER` on registered locations). For cross-account, use the **grant option** and the **owner's catalog ID**.
- **"Insufficient encryption key permissions for Glue API"** → catalog is encrypted and the granter lacks **KMS** access to the key.
- **"Required create tag on catalog"** → only **data lake admins** (or LF-tag creators with the permission) can create tags.
- **Query with manifests fails** (Athena/Redshift) → **manifests are not supported**.
- **Error deleting invalid data lake admins** (deleted IAM roles) → delete **all invalid admins together** in one operation.
- **"Caller is temporarily not authorized" through a resource link** → use **QuerySessionContext** or wait about 24 hours.
- **Crawler in a workflow fails "Resource does not exist or requester is not authorized"** → role lacks **`CREATE_TABLE`** on the target database.
- **Crawler `AccessDeniedException` on CreateTable** → role lacks **data location permission** on the target location.
- **Workflow or blueprint fails `iam:PassRole`** → the user (blueprint) or the **role itself** (workflow) needs the pass-role permission.
- **Registering a location fails** → missing `iam:PassRole`, `lakeformation:RegisterResource`, or the SLR creation permissions, or a role trust problem.
- **EMR cannot read a location** → it was registered with the **service-linked role**. **Re-register with a custom role**.
- **`GetTables` shows `IsRegisteredWithLakeFormation=false`** → known limit. Use **`GetTable`**.
- **A newly added admin cannot read old databases** → admins do not automatically hold data permissions on existing resources. Grant them.
- **External engine cannot read** → not opted in under **Application integration settings**, wrong session tag, or account not allowed.
- **Glue job loses bookmarks/pushdown** → the table uses **cell-level filters** (known restrictions).
- **Grant failures with `ConcurrentModificationException`** → retry or use batch APIs.
- **Cross-account symptoms** → see file 3 section E.

## H. Limits and numbers
- **Data lake administrators**: default **30**.
- **LF-tags**: up to **10,000** per account and **1,000 values** per tag (soft). **50 LF-tags** per resource. Key/value max **50 characters**. Stored in **lower case**. **One value per key** per resource.
- **LF-tag expressions**: **1,000** saved per account. **50** expressions per grant to a principal. Inline expression max **900 bytes**.
- **Data filters**: no limit per table, but **100 per principal per table**. Row filter expression **under 2,048 characters**. Nested column filtering up to **5 levels**.
- **Cross-account**: RAM shares and associations are limited per account (**version 5** removes the per-table association limit via wildcards). Request RAM quota increases if needed **(verify numbers)**.
- **Hybrid mode**: only **data lake admins** can opt in.
- **Registered locations**: buckets or prefixes only, not objects. Quotas on count **(verify)**.
- **Permissions you cannot grant**: `DROP` and `Super` on a database to an **external account**; `DESCRIBE` to a principal with **partial SELECT**; column-filtered `SELECT` **with grant option using an exclusion list**.
- **Not supported**: Athena Spark, Hive on EMR Serverless, EMR on EKS, manifest queries, cell-level security on nested columns/views/resource links, `SELECT INTO` with filters, row filter on array/map types.
- Many quotas are **adjustable** with **Service Quotas** (check the console for `lakeformation`).

## I. Exam cheat sheet: which Lake Formation feature for which need
- Hide some columns → **column filtering** (include list). Hide some rows → **row filter**. Both → **cell-level filter**.
- Scale access control across many tables → **LF-tags (LF-TBAC)**.
- Match principal attributes to access → **ABAC (IAM/session tags)**.
- Migrate from IAM-only without breaking users → **hybrid access mode**.
- Enforce Lake Formation on a table → **revoke `IAMAllowedPrincipals`**.
- Let Lake Formation vend credentials for S3 data → **register the S3 location**.
- Allow creating tables that point at a registered path → **`DATA_LOCATION_ACCESS`** (+ `CREATE_TABLE`).
- Query shared tables in Athena/Spectrum → **resource links**.
- Share with an Organization/OU → **LF-TBAC (cross-account v3+)** or named resource grant to the org/OU.
- Share directly with one role in another account → **direct share (cross-account v3)**.
- Many tables, limited RAM capacity → **All tables wildcard, OU grants, v2+ / v5**.
- Share Redshift or other external data under the same governance → **federated catalogs**.
- Know who read the data → **CloudTrail `GetDataAccess`** (+ S3 data events, source identity).
- Fine-grained access in Glue jobs → **Glue 5.0+** (Iceberg/Hive reads).
- PII governance → **Macie finds, tags in Lake Formation, filters hide**.
- Least privilege admin → **`AWSLakeFormationDataAdmin`**, small admin list, **LF-tag creators**, **read-only admin** for auditors.
- Two gates → **IAM + Lake Formation** (both must allow).

## J. Final scenarios (if → then, because)
- If auditors need to see who has access to a table but must not change anything → **read-only administrator** and CloudTrail, because it gives view without edit.
- If a data engineer's new table is invisible to analysts → grant `SELECT` (or tag-based access) to the analysts' role, because creators get table permissions, not others.
- If analysts must be blocked from S3 but able to query → remove their S3 permissions and keep Lake Formation + `GetDataAccess`, because queries use vended credentials.
- If someone changes data lake settings unexpectedly → add an **SCP/IAM deny** on `PutDataLakeSettings` for non-admins and **alarm** on the CloudTrail event.
- If the same dataset needs EU rows for EU staff and all rows for HQ → two **data filters** and two `SELECT` grants, because filters avoid copies.
- If new tables from a team should auto-inherit access → tag the team's **database**, grant the tag to the team, because tables inherit database tags.
- If a Glue job writes to a governed table and fails → give the job role `INSERT` (and `DATA_LOCATION_ACCESS` if it creates tables) plus `lakeformation:GetDataAccess`, because writes need both.
- If costs rise from filtering with a non-AWS engine → data filtering via the **Storage API** bills per byte scanned. Use columnar formats and partitions, or use an integrated engine.
- If a team wants to adopt Lake Formation for one dataset only → **hybrid access mode**, opt in that team and database.
- If a share to an external account fails with "Illegal combination" → revoke **`IAMAllowedPrincipals`** first.
- If a table has partition keys you need to hide → you cannot column-filter partition keys. Restructure or use a row/view approach.
- If you need to share and also keep the producer's KMS-encrypted data readable → use a **customer managed key** with a cross-account key policy, because `aws/s3` cannot be shared.
- If "least operational overhead" governance across accounts is asked → **Lake Formation with LF-tags and OU sharing**, over hand-written bucket policies.
- If an ETL role should create tables only under `s3://lake/curated/` → grant `CREATE_TABLE` on the database and `DATA_LOCATION_ACCESS` on that prefix only.

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: setup and administrator policies, personas and managed policies, registration role requirements, data filtering limits, LF-tag considerations, cross-account notes and versions, troubleshooting, CloudTrail logging, pricing page, hybrid access mode notes.
Not confirmed (verify): the exact SCP/IAM actions to restrict, interface VPC endpoint details, service-linked role limitation list, KMS and cross-account `aws/s3` wording, governed table availability and optimizer pricing text, EventBridge events for Lake Formation, Config resource support, registered-location quotas, RAM quota numbers, Lake Formation Service Quotas defaults not on the quotas page (the quotas page returned no table).

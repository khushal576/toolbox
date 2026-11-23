# Redshift – 5. High availability, snapshots and restore, network, authentication, authorization, encryption, masking, auditing, governance

Short notes. Each point is a fact you can be asked about.

## A. Availability and durability (verified + notes)
- **Single-AZ cluster** (default): all nodes in one AZ. Multi-node data is **mirrored** across nodes and continuously backed up to S3. SLA **99.9%**.
- **Multi-AZ** (RG/RA3 provisioned): compute in **two AZs**, **one endpoint**, **zero RPO**, faster recovery (lower RTO), SLA **99.99%**. If one AZ fails the other keeps serving. Same node price; storage shared. Needs a subnet group covering enough AZs.
- **Serverless**: compute is managed by AWS across AZs in the Region; use **recovery points** and snapshots for protection. Subnets in at least 3 AZs recommended (verify).
- **Node failure**: Redshift detects, replaces the node automatically, and re-mirrors data. **Single-node cluster**: hardware failure means **restore from snapshot** (cluster status `hardware-failure`).
- **Disaster recovery across Regions**: enable **cross-Region snapshot copy** and restore in the target Region; or use **data sharing** across Regions; or build a second cluster fed by the same pipelines.
- **Relocation**: cluster relocation to another AZ can be enabled to recover from AZ capacity issues (verify specifics for RA3).
- **Multi-AZ is not a backup.** Snapshots are the backup.

## B. Snapshots and restore (verified)
- **Automated snapshots**: taken about **every 8 hours or every 5 GB of data change per node** (whichever first). Free (stored in S3 up to cluster storage size). **Default retention 1 day; range 0–35 days** (0 disables). Deleted when retention ends or the cluster is deleted.
- **Manual snapshots**: you create them; **kept until you delete them** (no expiry). Billed as unique blocks retained.
- **Snapshot schedules**: automate manual snapshots on a custom cadence (cron-like).
- **Restore** always creates a **new cluster** (new endpoint). You can change node type/number (with limits). Then update apps and reattach parameter groups, IAM roles, security groups, logging.
- **Table-level restore**: restore a **single table** from a snapshot into the same or another cluster with a new name (cluster stays online) – no full restore.
- **Cross-Region snapshot copy**: automatic copy of automated and manual snapshots to another Region (set retention there). For encrypted clusters you need a **snapshot copy grant** with a **KMS key in the destination Region**.
- **Cross-account sharing**: authorize AWS accounts to restore a snapshot. Limits: **20 accounts per snapshot**, **100 accounts per KMS key** (aggregate). Encrypted snapshots require KMS key sharing with the target account (customer managed key).
- **Quotas**: up to **700 user snapshots** per account per Region (adjustable).
- **Serverless**: **recovery points** (automatic, kept about 24 hours; restore to any), and manual snapshots; restore into a namespace. Snapshot/recovery can **keep S3 event integrations** when restored to the same namespace.
- **Snapshot restore for RA3/Serverless is fast** because data is in managed storage; cluster is usable while blocks stream in (verify).
- Snapshot costs: backup storage free up to **100% of provisioned/used storage** for automated; manual beyond; cross-Region data transfer.
- Pausing a cluster still bills backup storage.
- Final snapshot is offered when deleting a cluster (`final-snapshot` status).
- Snapshot of **no-backup tables** (`BACKUP NO`) skips those tables (used for temporary staging; they aren't restored).
- Deleting a cluster deletes automated snapshots, keeps manual ones.
- Test restores regularly and document your restore time (RTO).

## C. Network security (verified)
- Provisioned clusters and Serverless workgroups run **inside a VPC**. Control connectivity with **VPC security groups** (inbound on the Redshift port, default **5439**) and a **cluster subnet group**.
- **Publicly accessible** option puts an internet endpoint; avoid for production; keep private and connect via VPN, Direct Connect, peering, bastion, or Client VPN.
- **Enhanced VPC routing**: forces COPY/UNLOAD/Spectrum traffic between Redshift and S3 to flow **through your VPC** (so VPC endpoints, security groups, NACLs, flow logs, endpoint policies apply) instead of the public internet.
  - Use with an **S3 gateway endpoint** (and NAT/VPC endpoints for other services like Glue, KMS).
  - Needed when policy says S3 traffic must not leave AWS private network.
- **Redshift-managed VPC endpoints** (PrivateLink): other VPCs/accounts connect privately; up to **30** per cluster, **10** grantees (adjustable).
- **Interface VPC endpoints** for the Redshift API, Data API, Secrets Manager, etc.
- TLS: you can **require SSL** with the `require_ssl` parameter in the parameter group.
- Avoid MTU/jumbo-frame issues between clients and the cluster (set MTU 1500 or allow packet-size negotiation) – connections can "hang".

## D. Authentication (who are you) (verified + notes)
Access is controlled at four levels: **cluster management (IAM)**, **cluster connectivity (security groups)**, **database access (database users/roles)**, and **temporary credentials/SSO**.
- **Database users and passwords**: created with `CREATE USER`. Admin (superuser) created at cluster creation.
- **IAM-based authentication** (preferred): applications get **temporary database credentials**.
  - `GetClusterCredentials` (database user) / `GetClusterCredentialsWithIAM` (IAM identity maps to user `IAM:name`) / `redshift-serverless:GetCredentials`.
  - JDBC/ODBC drivers can do this for you (auto-create users, join groups).
- **Federated SSO**: SAML 2.0 identity providers (Okta, Azure AD, ADFS, Ping), **IAM Identity Center** (including **trusted identity propagation**) → temporary credentials.
- **Secrets Manager**: store DB credentials (Data API, federated queries, Lambda); **Redshift can manage the admin password in Secrets Manager** with automatic rotation.
- **IAM roles on the cluster/namespace**: let Redshift access S3, Glue, KMS, Lambda, SageMaker, Secrets Manager for COPY/UNLOAD/Spectrum/UDF/ML. Up to **50 roles** per cluster. Use least privilege and `aws:SourceArn` conditions (confused deputy).
- **Cross-account**: role chaining so a cluster role assumes a role in another account to read its S3 bucket.
- **Idle timeouts**: sessions end after **4 hours** idle on clusters (1 hour on Serverless); idle transactions after **6 hours**.
- Best practice: no long-lived passwords in code; IAM/SSO/temporary credentials or Secrets Manager.

## E. Authorization inside the database
- **GRANT/REVOKE** on databases, schemas, tables, views, columns, functions, procedures, datashares, COPY JOBs, etc. Default privileges for new objects (`ALTER DEFAULT PRIVILEGES`).
- **Groups** (older) and **Roles (RBAC)** (preferred): create roles (`CREATE ROLE`), grant privileges to roles, grant roles to users or other roles (role hierarchy). Up to **1,000 roles**. System roles (for example `sys:operator`, `sys:dba`, `sys:superuser`, `sys:secadmin`) delegate admin tasks without full superuser.
- **Column-level access control**: `GRANT SELECT (col1, col2) ON table TO …` – users see only listed columns.
- **Row-level security (RLS)** (verified): policies decide which **rows** a user/role can read (and write). `CREATE RLS POLICY … USING (predicate)`, `ATTACH RLS POLICY … ON table TO role/user`, `ALTER TABLE … ROW LEVEL SECURITY ON`. Keep policies **simple**; policies referencing lookup tables add scanning cost. Works with column-level security.
- **Dynamic data masking (DDM)**: `CREATE MASKING POLICY` (expression, for example partial mask of a credit card), `ATTACH MASKING POLICY` to columns for roles with **priority**; data stays unchanged, query results are masked per user. Good for PII (SSN, email, phone). Different users can see different masking levels.
- **Schema quota**: limit storage per schema; metrics `SchemaQuota`, `StorageUsed`, `PercentageQuotaUsed`, `NumExceededSchemaQuotas`.
- **Lake Formation integration**: centrally govern Spectrum/Glue Catalog tables (database, table, column, row, cell-level, tag-based). Also governs **datashares** via Lake Formation.
- **Data sharing permissions**: producers grant USAGE on datashares to specific namespaces/accounts; consumers grant access inside their warehouses.
- **IAM policy examples**: allow `redshift:GetClusterCredentials` with `redshift:DbUser`/`DbName`/`DbGroups` conditions to limit which DB users a principal can impersonate.
- **Tag-based IAM** (ABAC) for cluster management actions.
- **Separation of duties**: security admin (`sys:secadmin`) manages RLS/DDM/roles; ELT role loads data; BI role reads marts.

## F. Encryption (verified)
- **At rest**: optional **AES-256** for data on disks and **all backups (snapshots) in S3**. Managed with **AWS KMS** (AWS managed key or **customer managed key**) – key hierarchy (cluster key, database key). Can also use **HSM** (CloudHSM, provisioned only; verify).
- Choose encryption at **cluster creation**; for an existing **unencrypted** cluster you can **modify the cluster to enable encryption** (a background re-encryption; verify), or **unload/reload** / restore into an encrypted cluster.
- Key rotation: rotate encryption keys from the console/API (`rotating-keys` status). KMS key policy must allow Redshift.
- **Snapshot copy to another Region** for an encrypted cluster → **snapshot copy grant** in the destination Region.
- **Serverless**: encrypted by default with AWS-owned/managed key or your KMS key at namespace creation.
- **In transit**: SSL/TLS between client and cluster (enable `require_ssl` to force). Data between nodes is on a private network. COPY/UNLOAD to S3 over TLS; **UNLOAD can write encrypted files** (SSE-S3/SSE-KMS or client-side with `ENCRYPTED`).
- **Query editor v2** stores saved queries and connection info encrypted (KMS key you choose or service key).
- Admin password in **Secrets Manager** can use an extra KMS key.
- If the KMS key is disabled/deleted, the cluster becomes inaccessible – protect keys.

## G. Auditing and logging (verified)
- **Audit logging** (off by default): **connection log**, **user log**, **user activity log**.
  - **Connection log**: authentication attempts, connects, disconnects.
  - **User log**: changes to database users (create, drop, alter, rename).
  - **User activity log**: **every query text before it runs** (needs the `enable_user_activity_logging` parameter = `true` in the parameter group, in addition to enabling logging).
- Destinations: **Amazon S3** (SSE-S3 only; bucket needs a policy for `redshift.amazonaws.com` with `s3:PutObject` and `s3:GetBucketAcl`; **Object Lock must be off**; bucket owner must not change) or **CloudWatch Logs** (log groups like `/aws/redshift/cluster/<name>/connectionlog`). **Serverless can export only to CloudWatch**.
- S3 key structure: `AWSLogs/<account>/redshift/<region>/<yyyy>/<mm>/<dd>/…`.
- Log files lag the system tables slightly. System tables (`STL_CONNECTION_LOG`, `STL_USERLOG`, `SYS_CONNECTION_LOG`, `SYS_USERLOG`) always exist; system-table retention is short (days), so export logs for long-term audit.
- **CloudTrail** records **API calls** (cluster management, Data API calls, GetClusterCredentials with the IAM auth GUID that links to the connection log). Use it with audit logging for a full trail.
- **EventBridge/SNS events**: cluster events (maintenance, failures, resize, snapshot), zero-ETL notifications.
- **Redshift system views** show running queries (`SYS_QUERY_HISTORY`), sessions, load history.
- **Config / Security Hub / GuardDuty**: Config rules check encryption, public access, logging, etc.; Macie finds sensitive data in S3 sources.

## H. Governance patterns
- **Zones**: raw (S3) → staging schema → curated/mart schema → shared views. Grant BI roles only on mart schemas.
- Mask PII with **DDM**; restrict rows by tenant/region with **RLS**; restrict columns with **column-level grants**.
- Use **Lake Formation** to govern data-lake tables and datashares from one place.
- Share via **data sharing** instead of copying data (copies escape governance).
- Tag clusters/resources; use **SCPs** to block public clusters or unencrypted creation.
- Keep **audit logs** in a locked-down S3 bucket (lifecycle to Glacier) or CloudWatch with retention.
- Rotate credentials; use Secrets Manager rotation for admin and app users.
- Review `sys:` role grants and superusers regularly.

## I. Compliance and limits recap
- Redshift is in scope for major programs (HIPAA, PCI DSS, SOC, ISO, FedRAMP – check the services-in-scope page).
- Quotas to remember: IAM roles per cluster **50**; snapshot sharing **20 accounts/snapshot**, **100/KMS key**; user snapshots **700**; roles **1,000**; managed VPC endpoints **30**; parameter groups **20** (not adjustable); subnet groups **50**; security groups **20**; event subscriptions **20**.
- Naming: cluster identifier lowercase 1–63 chars; admin password 8–64 chars with upper, lower, digit, no `' " \ / @`.

## Scenarios (if → then, because)
- If an AZ failure must not stop BI → Multi-AZ RG/RA3 cluster (99.99%, zero RPO), because compute exists in two AZs behind one endpoint.
- If compliance needs backups in another Region → enable cross-Region snapshot copy (with a snapshot copy grant for encrypted clusters).
- If someone dropped one table yesterday → table-level restore from the latest snapshot, because the cluster stays online and only one table is recovered.
- If you need a 3-month-old copy → manual snapshot (automated max 35 days), or a schedule creating manual snapshots.
- If a shared snapshot must be restored in another account → authorize the account and share the KMS key if encrypted.
- If S3 traffic from Redshift must stay inside the VPC → turn on enhanced VPC routing and add a gateway endpoint for S3.
- If apps must not store DB passwords → IAM authentication with temporary credentials (GetClusterCredentials), SSO, or Secrets Manager.
- If corporate users must sign in with Okta/AD → SAML federation or IAM Identity Center.
- If auditors need to know who ran which query → enable audit logging + `enable_user_activity_logging`, export to S3/CloudWatch, and keep CloudTrail.
- If a Serverless workgroup needs audit logs → CloudWatch Logs only.
- If support reps should see only the last 4 digits of a card number → dynamic data masking policy attached to their role.
- If each regional manager may see only their region's rows → row-level security policy.
- If analysts may see all columns except salary → column-level GRANT (or masking).
- If data lake tables need column/row-level control used by Athena and Redshift → Lake Formation.
- If an unencrypted production cluster must be encrypted → modify to enable encryption (or restore into an encrypted cluster), choose a KMS key.
- If the KMS key is deleted → data is unrecoverable; protect keys and use key policies/deletion windows.
- If connections should be forced to TLS → `require_ssl=true` in the parameter group.
- If another VPC (or account) needs private access → Redshift-managed VPC endpoint or PrivateLink.

## Verified from AWS docs on 2026-10-02
Read: security overview, RLS page, encryption-at-rest page, audit logging page, Multi-AZ page, snapshots summary page, quotas page. Not confirmed (verify): exact automated snapshot trigger numbers (8 h / 5 GB) and retention range (taken from a summary page), relocation details, Serverless AZ requirements, HSM availability, in-place encryption enablement behavior, DDM policy syntax details, system role names, restore streaming behavior on RA3, Config/Security Hub rule names.

# DocumentDB – 2. High availability, global clusters, backup, security, auditing, parameters, maintenance

Short notes. Each point is a fact you can be asked about.

## A. High availability inside a Region (verified)
- Storage is durable by design: 6 copies over 3 AZs. High availability for **compute** comes from replicas.
- Deploy at least **two instances in two AZs** (HA). For production use **three or more in three AZs** (the Service Level Agreement expects this).
- DocumentDB spreads instances across the AZs in your subnet group automatically. Subnet group must have at least two AZs.
- If the primary fails, a replica is promoted. Brief interruption: reads/writes to the old primary fail with an exception, then the cluster endpoint points to the new primary. Typical failover about 30 seconds (verify) or less.
- **Failover priority tiers 0–15**: you choose which replica should be promoted first. Lower tier first; same tier → larger instance first (verify tie-break).
- If no replica exists, DocumentDB creates a new primary automatically. That is much **slower** than promoting a replica.
- After failover the recovered instance stays in its original AZ but may become a replica. This prevents all instances ending up in one AZ.
- Use replicas of the **same instance class** as the primary so failover doesn't reduce performance.
- Apps must reconnect and retry (use the cluster endpoint, replica set mode, driver retry logic, exponential backoff). Retryable writes only on 8.0.2+.
- Test failover yourself (`failover-db-cluster`) to measure your own recovery time.
- Replication lag is typically 50 ms or less (usually well under 100 ms). Causes of lag: heavy writes, long queries on replicas, many concurrent reads. Alarm on `DBClusterReplicaLagMaximum` (alert above ~10 seconds too).
- To reduce lag: scale up instances, move long queries to other instances, add replicas, check `WriteThroughput`/`WriteIOPS`.
- Scale up before scale out when possible (bigger buffer cache per instance).
- **Multi-AZ is not a backup**; replicas copy mistakes too.

## B. Global clusters (verified)
- One **primary Region** (read/write) + up to **10 read-only secondary Regions**. Replication uses storage-level dedicated infrastructure; lag typically **under 1 second**.
- Uses: Region-level disaster recovery (promote a secondary within minutes; RTO typically under a minute, RPO in seconds), low-latency local reads in other Regions, scale reads (secondary cluster up to **16** replicas), change streams can be read from secondary clusters to offload the primary.
- Writes go only to the primary cluster's endpoint. Clients in other Regions can read locally.
- Limitations (verified): not supported on engine **3.6**; not on instance classes **db.t3, db.t4g, db.r4**; not available in some Regions (São Paulo, Milan, China Beijing/Ningxia in the doc); **switchover and global failover need identical engine versions** (manual failover works when versions differ); secondary cluster cannot be stopped, and a primary with secondaries cannot be stopped; replicas in secondary Regions can restart if the primary Region's instance restarts or fails over.
- Operations: **switchover** (planned, no data loss) vs **failover** (unplanned, after outage). 
- Global cluster is separate from elastic clusters (elastic clusters don't use it; verify).
- Add a replica in a faraway Region for DR, not for write scaling.

## C. Backups and recovery (verified)
- **Automated continuous backups** to Amazon S3 (service-managed buckets you can't see). Incremental. **No performance impact.**
- Retention **1–35 days** (default 1 day). Pick it to match your recovery point objective.
- **Point-in-time recovery (PITR)**: restore to any second in the window, up to about the last **5 minutes**. Restore always creates a **new cluster** (then add instances). It does not overwrite the old one.
- **Manual snapshots**: kept until you delete them. Quota: 100 manual cluster snapshots per Region (instance-based), 20 for elastic clusters.
- Snapshots can be copied to other Regions and shared with other accounts. Encrypted snapshots follow KMS rules (see section E).
- Restore from snapshot or PITR → new cluster with new endpoints; reattach parameter groups, security groups, KMS settings, and re-add instances; update app connection strings.
- Backup storage billing: automated backup storage within retention (up to cluster size is free; more is billed – verify), plus snapshots beyond retention. Metrics: `BackupRetentionPeriodStorageUsed`, `SnapshotStorageUsed`, `TotalBackupStorageBilled`.
- Final snapshot recommended before deleting a cluster. Enable **deletion protection** on production clusters (verified best practice).
- Logical backups: `mongodump` / `mongorestore` and export to S3 for portability and cross-engine moves (they don't include the admin DB or users).
- Can use AWS Backup for DocumentDB for central policies, cross-Region/account copies (verify exact support).
- Test restores regularly and measure restore time.
- Restoring to remove a bad update: PITR to before the mistake into a new cluster, then copy the documents back or switch the app.
- There is **no Backtrack-style rewind** in DocumentDB.

## D. Deleting data and retention
- Delete by `deleteMany` or TTL index (best effort; counts as I/O). Old data also remains in PITR window and snapshots until they expire/deleted.
- Rolling collections: drop an old collection for fast, cheap deletion without per-document I/O (verified recommendation).
- Change stream log keeps changes for the retention duration (3 hours default up to 7 days) – sensitive data may linger there.
- For legal erasure: delete documents, expire backups (set retention), delete manual snapshots, remove copies in other Regions/lake exports.

## E. Security (verified)
- **Network isolation**: runs only in a VPC. Control with security groups (port 27017) and NACLs. Instances have no public IP.
- **Interface VPC endpoints (PrivateLink)** exist for the DocumentDB management API (not for data access).
- **Encryption in transit**: TLS (enabled by default). Parameter `tls` can be disabled but shouldn't be. Use the current CA bundle; rotate TLS certificates when AWS announces (CA rotation).
- **Encryption at rest**: AWS KMS (AWS managed key or customer managed key). Choose when **creating the cluster** (cannot change later; verify) – encrypts storage, automated backups, snapshots, and replicas in the cluster. To encrypt an unencrypted cluster, snapshot → copy with encryption → restore.
- **Authentication**:
  - **Username/password** with SCRAM-SHA-256 (primary user + database users).
  - **AWS Secrets Manager** integration to manage and rotate the primary password.
  - **IAM identity authentication** (password-less): only on **instance-based engine 5.0**; uses the `MONGODB-AWS` mechanism with the `$external` database; users are IAM user or role ARNs; not available for the primary user; not for elastic clusters (verify); needs a driver supporting `MONGODB-AWS` (Node.js driver 6.13.1+; Python `pymongo[aws]`). Temporary credentials are only used to connect; the connection stays open after they expire. IAM auth depends on AWS STS (throttling possible; lower connection rate). Metric `StsGetCallerIdentityCalls`.
- **Authorisation – Role-Based Access Control (RBAC)** (verified):
  - Users are stored in the `admin` database. User/role operations always happen in `admin`.
  - **Built-in roles**: `read`, `readWrite` (database level); `readAnyDatabase`, `readWriteAnyDatabase`, `userAdminAnyDatabase`, `dbAdminAnyDatabase` (cluster-wide); `dbAdmin`, `dbOwner`; `clusterAdmin`, `clusterManager`, `clusterMonitor`, `hostManager`; `backup`, `restore`; `root` (superuser).
  - **User-defined roles**: custom privileges on specific databases/collections with listed actions (for example `find`, `insert`, `update`, `remove`).
  - Limits: **1,000 users per cluster** (100 on elastic), up to 1,000 roles per user, **100 user-defined roles**, 100 resources per privilege.
  - Users created before 26 March 2020 had broad roles (`dbAdminAnyDatabase`, `readWriteAnyDatabase`, `clusterAdmin`); reevaluate for least privilege.
  - If you omit `db` when creating a role binding, it binds to the database of your current connection context.
  - Authenticating succeeds against `admin`, but commands run in your connection's database context; you can get `Authorization failure` if the user lacks rights on that database.
  - Use separate users per application with only the needed database/collection rights. Do not use the primary user in apps.
- **Auditing** (verified):
  - Off by default. Needs **two steps**: set the cluster parameter `audit_logs` and enable **CloudWatch Logs export** for `audit`; if you skip either, nothing is delivered.
  - `audit_logs` values: `ddl`, `dml_read`, `dml_write`, `all`, `none` (default), comma lists allowed; legacy `enabled` = `ddl`, `disabled` = `none`.
  - Logs go to CloudWatch Logs group `/aws/docdb/<cluster>/audit`.
  - Events: authentication, authorization (`authCheck`), DDL (create/drop database, collection, index), user/role management, DML reads/writes. TTL deletes are **not** audited. Parameter values over 1 KB are truncated.
  - DML audit filters (`setAuditConfig`) can limit events by command, user, namespace (`param.ns`), `atype`; needs `auditConfigure` privilege (in `clusterAdmin`, `hostManager`, `root`, or a custom role). DDL events are not filtered. No extra DocumentDB charge, but CloudWatch Logs cost.
- **CloudTrail** logs management API calls (create/modify/delete cluster, snapshots, parameter groups). It does not log MongoDB queries.
- **Profiler**: logs slow operations (parameter `profiler`, `profiler_threshold_ms`, `profiler_sampling_rate`) to CloudWatch Logs (verify names).
- **Compliance**: FedRAMP (Moderate in US East/West, High in GovCloud), HIPAA eligible and others (see AWS compliance programs).
- Confused-deputy protection for service roles is documented.
- Masking/PII: no built-in masking. Use views/projections in the app layer, field-level encryption (client-side), or limit access by roles.

## F. Parameter groups (verified)
- **Cluster parameter groups** configure engine behavior for all instances. Default groups (`default.docdb5.0` etc.) cannot be edited or deleted; create a custom group.
- Wait about 5 minutes after creating a parameter group before using it.
- Important parameters: `tls` (enable/disable TLS), `audit_logs`, `ttl_monitor` (enable/disable TTL deletes), `change_stream_log_retention_duration`, `profiler`, `profiler_threshold_ms`.
- Parameters are **dynamic** (apply immediately) or **static** (need `pending-reboot`).
- Test parameter changes on a test cluster first.
- `change_stream_log_retention_duration`: range 1 hour to 7 days (docs text; console parameter shows seconds; verify allowed range).

## G. Maintenance and upgrades (verified)
- Weekly maintenance window; AWS applies engine patches. Patches can cause brief interruption/failover.
- **Minor version upgrades**: patch updates within the same engine version.
- **Major version upgrades**: in-place major version upgrade (for example 4.0 → 5.0) or migration using **AWS DMS**; test first. Use new engine features after upgrade (IAM auth and vector search need 5.0+).
- **Engine version support dates** and **Extended Support** exist for older versions (a paid option after end of standard support; verify the dates).
- Always set `--engine-version` explicitly when creating clusters/automation: the default is 5.0.0 today; 8.0 must be requested explicitly (verified best practice).
- A **long-term support (LTS) release** option exists for engine versions (verify).
- Scale instance class: takes a few minutes; plan the failover for the primary.
- Stop/start cluster: dev/test cost saving; a stopped cluster restarts automatically after a period (verify 7 days); not available for clusters in a global cluster with secondaries.

## H. Scenarios (if → then, because)
- If production must survive an AZ failure → at least 3 instances in 3 AZs, replica in different AZs, cluster endpoint with replica set mode.
- If you want a specific replica promoted first → set its failover priority tier lower than others.
- If a cluster has only one instance and it fails → DocumentDB recreates it (slow); add a replica for fast failover.
- If a DR requirement says RPO seconds / RTO under a minute across Regions → global cluster.
- If a developer drops a collection by mistake → PITR to a new cluster before the mistake and copy data back.
- If you need monthly archives for 1 year → manual snapshots or mongodump to S3 with lifecycle; PITR window max is 35 days.
- If compliance requires encryption with customer keys → CMK at cluster creation.
- If an existing unencrypted cluster must be encrypted → snapshot, copy with encryption, restore.
- If apps must not store passwords → IAM authentication (5.0 instance-based) with an IAM role.
- If analysts need read-only access to one database → create a user with `read` on that database only.
- If you need a custom role for a single collection → user-defined role with specific actions.
- If auditors need to see who dropped collections → enable `audit_logs=ddl` and CloudWatch Logs export.
- If DML auditing is too noisy → use `setAuditConfig` filters by user/command/namespace.
- If audit logs don't appear → one of the two steps (parameter or log export) was missed.
- If TLS errors occur after CA rotation → update the CA bundle in clients.
- If replication lag spikes → check long replica queries, write bursts, instance size; scale up/out.
- If a global cluster failover is blocked → engine versions differ; use manual failover or align versions.
- If a connection from a laptop fails → cluster is VPC-only; use a bastion, VPN or Direct Connect.

## Verified from AWS docs on 2026-10-02
Replication and HA page, backup index page, security index page, global clusters, RBAC, IAM authentication, auditing, parameter groups, best practices, migration index were read. Not confirmed (verify): failover seconds, default KMS/creation-time behavior details, AWS Backup support, PITR free-storage allowance, profiler parameter names, stop duration, LTS/Extended Support dates, change-stream retention allowed range.

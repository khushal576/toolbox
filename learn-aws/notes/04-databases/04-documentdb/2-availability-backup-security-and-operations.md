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
- **If** production must survive the loss of an Availability Zone (AZ), **then** run at least **3 instances in 3 AZs** (one primary and two replicas, each replica in a different AZ) and connect through the **cluster endpoint** in replica set mode. **This works because** storage already keeps **6 copies across 3 AZs**, but compute availability comes from replicas: if the primary fails, a replica is promoted and the cluster endpoint points to it. Failover takes about **30 seconds** (verify) or less, so apps must reconnect and retry.
- **If** you want a specific replica promoted first when the primary fails, **then** give it a **lower failover priority tier** (tiers **0–15**) than the others. **This works because** DocumentDB promotes the lowest tier first; within the same tier the larger instance goes first (verify tie-break).
- **If** a cluster has only one instance and it fails, **then** add at least one replica in another AZ so the next failure is fast. **This works because** with no replica, DocumentDB must create a new primary automatically, which is much **slower** than promoting an existing replica.
- **If** a disaster recovery (DR) rule needs a Recovery Point Objective (RPO) of seconds and a Recovery Time Objective (RTO) under a minute across Regions, **then** use a **global cluster**. **This works because** storage-level replication to up to **10** secondary Regions has lag typically **under 1 second**, and a secondary can be promoted quickly (RTO typically under a minute). Global clusters do not support engine **3.6** or **db.t3, db.t4g, db.r4** instances.
- **If** a developer drops a collection by mistake, **then** use **point-in-time recovery (PITR)** to restore to a moment just before the mistake, then copy the documents back or switch the app. **This works because** continuous backups let you restore to any second in the retention window, up to about the last **5 minutes**. The restore always creates a **new cluster**; it never overwrites the old one, and there is no Backtrack-style rewind.
- **If** you need monthly archives kept for **1 year**, **then** take **manual snapshots** (kept until you delete them) or run `mongodump` to **Amazon Simple Storage Service (S3)** with a lifecycle rule. **This works because** automated backups and PITR keep at most **35 days**, which is too short. Note that `mongodump` does not include the admin database or users.
- **If** compliance requires encryption with your own keys, **then** choose a **customer managed key** in **AWS Key Management Service (KMS)** when you **create the cluster**. **This works because** that key encrypts the storage, automated backups, snapshots and replicas of the cluster, and the choice cannot be changed later (verify).
- **If** an existing unencrypted cluster must be encrypted, **then** take a **snapshot**, **copy** it with encryption turned on, and **restore** the copy to a new cluster. **This works because** encryption is chosen at cluster creation and cannot be switched on in place (verify). The restored cluster has new endpoints, so update the app's connection strings.
- **If** apps must not store passwords, **then** use **Identity and Access Management (IAM) authentication** with an **IAM role**. **This works because** the app connects with the `MONGODB-AWS` mechanism using temporary credentials, and the DocumentDB user is the role's ARN, so no password exists. It works only on **instance-based engine 5.0**, needs a driver that supports `MONGODB-AWS`, and is not available for the primary user.
- **If** analysts need read-only access to one database, **then** create a user with the built-in **`read`** role on that database only. **This works because** Role-Based Access Control (RBAC) roles can be scoped to one database, giving least privilege. Do not let them use the primary user.
- **If** you need a role that covers a single collection, **then** create a **user-defined role** listing that collection and only the needed actions (for example `find`, `insert`). **This works because** user-defined roles grant custom privileges on specific databases or collections. A cluster can have up to **100** user-defined roles.
- **If** auditors need to see who dropped collections, **then** set the cluster parameter **`audit_logs=ddl`** and enable **Amazon CloudWatch Logs export** for `audit`. **This works because** DDL events (create/drop of databases, collections and indexes) are then written to the log group `/aws/docdb/<cluster>/audit`. Auditing is off by default, and both steps are needed.
- **If** DML (data read/write) auditing creates too many events, **then** use **`setAuditConfig`** filters to keep only certain users, commands or namespaces. **This works because** the filters limit which DML events are logged, which also lowers CloudWatch Logs cost. You need the `auditConfigure` privilege, and DDL events cannot be filtered.
- **If** audit logs do not appear, **then** check that **both** steps were done: the `audit_logs` parameter is set and the CloudWatch Logs export for `audit` is enabled. **This works because** if either step is missing, nothing is delivered.
- **If** TLS errors start after AWS rotates its certificate authority (CA), **then** update the **CA bundle** (`global-bundle.pem`) in your clients. **This works because** TLS is on by default and clients trust the server through the Amazon CA bundle they hold, so an old bundle stops matching after the rotation.
- **If** replication lag spikes, **then** look for long queries on replicas, write bursts (`WriteThroughput`, `WriteIOPS`) and undersized instances, then **scale up**, move long queries elsewhere or **add replicas**. **This works because** these are the main causes of lag, which is normally **50 ms** or less. Alarm on `DBClusterReplicaLagMaximum`, also above about **10 seconds**.
- **If** a global cluster failover is blocked, **then** align the engine versions or use **manual failover**. **This works because** switchover and global failover need **identical engine versions** in the primary and secondary clusters, while manual failover still works when versions differ.
- **If** a connection from a laptop fails, **then** connect through a **bastion host** (an EC2 instance with an SSH tunnel), a **VPN** or **AWS Direct Connect**. **This works because** DocumentDB runs only inside your Virtual Private Cloud (VPC) and has no public endpoint or public IP.

## Verified from AWS docs on 2026-10-02
Replication and HA page, backup index page, security index page, global clusters, RBAC, IAM authentication, auditing, parameter groups, best practices, migration index were read. Not confirmed (verify): failover seconds, default KMS/creation-time behavior details, AWS Backup support, PITR free-storage allowance, profiler parameter names, stop duration, LTS/Extended Support dates, change-stream retention allowed range.

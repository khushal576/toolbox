# RDS and Aurora – 3. High availability, replication, backups, restore, Backtrack, cloning, DR

Short notes. Each point is a fact you can be asked about.

## A. The three different things people mix up
- **High availability (HA)** = survive a failure fast. Tools: Multi-AZ, Aurora replicas/failover.
- **Read scaling** = more read capacity. Tools: read replicas, Aurora readers.
- **Backup/recovery** = get data back after a mistake or disaster. Tools: automated backups, PITR, snapshots, Backtrack, AWS Backup.
- **DR (disaster recovery)** = survive a Region failure. Tools: cross-Region replicas, Aurora Global Database, cross-Region snapshot copy.
- Multi-AZ is not a backup and not a read-scaling tool (for the instance deployment). Replicas are not a backup either (a bad DELETE replicates).

## B. RDS Multi-AZ – two kinds (verified)
- **Multi-AZ DB instance deployment**: one primary + **one standby** in another AZ. Replication is **synchronous**. The standby **does not serve reads**. Used for HA/failover only.
- **Multi-AZ DB cluster deployment** (RDS for MySQL and PostgreSQL): one writer + **two readable standbys** in three AZs. **Semisynchronous** replication (commit needs acknowledgment from at least one reader). Standbys serve reads. Lower write latency than Multi-AZ instance. Faster failover (about 35 seconds claimed in AWS material; verify). Only on specific instance classes (db.c6gd, m5d, m6gd, m6id, m6idn, m8gd, r5d, r6gd, r6id, r6idn, r8gd, x2iedn) (verified).
- Multi-AZ clusters aren't the same as Aurora clusters (verified).
- In Multi-AZ clusters, failover picks the reader with the most recent change record; failover time depends on replica lag. For MySQL both readers must apply pending transactions first; for PostgreSQL the reader with lowest lag is promoted (verified).
- Flow control (MySQL parameter `rpl_semi_sync_master_target_apply_lag`, default 120 s; PostgreSQL extension `flow_control.target_standby_apply_lag`) throttles writes to limit replica lag (verified).
- All tables in MySQL Multi-AZ clusters should have a primary key (verified).
- Multi-AZ instance failover: RDS flips the endpoint DNS to the standby. Typical 60–120 seconds (verify). Reasons: primary failure, AZ outage, instance class change, OS patching, reboot with failover.
- Same endpoint after failover. Apps must reconnect and cache DNS carefully.
- Enable Multi-AZ for any production database. Single-AZ gives no automatic failover; recovery means restore from backup (minutes to hours).
- Converting Single-AZ → Multi-AZ takes a snapshot-based build of the standby (no downtime but I/O impact).
- Backups on Multi-AZ run from the standby so the primary has no I/O suspension (single-AZ may see brief I/O freeze).
- Multi-AZ instance deployments also exist for Oracle and SQL Server (using their own mechanisms) and MariaDB, MySQL, PostgreSQL, Db2.
- Multi-AZ doubles compute and storage cost (you pay for the standby).

## C. Aurora HA (verified)
- Storage is always spread over 3 AZs (6 copies). Data is durable even with one instance.
- Compute HA: add an Aurora Replica in another AZ. On writer failure Aurora promotes a replica (by promotion tier); typical failover about 30 seconds or less, faster with a replica; if no replica exists Aurora creates a new writer (slower, several minutes).
- Up to **15** Aurora Replicas in a cluster. Failover priority is the promotion tier 0–15 (0 first). Same tier → larger instance first.
- Reader endpoint load balances connections (DNS-based, so a client that holds a connection stays on one reader).
- Aurora Auto Scaling can add/remove readers based on CPU or connections (target tracking via Application Auto Scaling). RDS (non-Aurora) read replicas have no auto scaling (verified).
- Cluster endpoint (writer) auto-points to the new writer after failover.
- RDS Proxy shortens failover impact for apps.
- Serverless v2 readers in tier 0–1 stay big enough to take over (verified).
- Cluster cache management (Aurora PostgreSQL) keeps the designated failover replica's cache warm (verify).

## D. RDS read replicas (verified)
- Read-only copies made with the engine's own **asynchronous** replication: MySQL, MariaDB, PostgreSQL, Oracle, SQL Server, Db2 (behavior differs by engine).
- Create from a snapshot of the source, then stream changes. Billed as normal instances; same-Region replication data transfer is free; cross-Region has transfer charges.
- Up to **15** replicas per source (default quota); for Oracle 15 allowed but 5 recommended (verified).
- Use cases: scale reads, reporting/BI, serve reads while the primary is busy with backups/maintenance, DR (promote), cross-Region proximity.
- Replicas can be in a different AZ, different Region (secure channel set up automatically), and even different account via snapshot-sharing patterns (verify).
- Replicas can have a different storage type and instance class from the source.
- Must create manually; **no auto scaling for RDS read replicas** (verified).
- Promotion: converts the replica into a standalone writable DB (breaks replication, irreversible). Used for DR or migration cut-over.
- Deleting a source without deleting same-Region replicas promotes each replica to standalone (verified).
- Replica of a replica: allowed for MySQL, MariaDB and some PostgreSQL versions; not for Oracle, SQL Server, Db2. No circular replication (verified).
- Oracle and Db2 replicas can be standby/mounted (for cross-Region DR only, can't serve reads) (verified).
- Encryption rules (verified): an encrypted source must have encrypted replicas; same KMS key in the same Region; cross-Region replicas use a KMS key of the destination Region; no mixing encrypted and unencrypted.
- Source needs automated backups enabled (MySQL/MariaDB binlog retained) for replicas.
- Replica lag: metric `ReplicaLag`. Causes: heavy writes, long transactions, small replica, I/O limits, big single transactions, DDL.
- Replica can also be Multi-AZ itself (for faster failover after promotion).
- Multi-AZ DB cluster read replicas also exist (replicas of a Multi-AZ cluster).
- Replication to/from outside AWS: MySQL/MariaDB external replication (binlog) and PostgreSQL logical replication (pglogical/native) and DMS (CDC). Use for migration cut-overs.

## E. Aurora replication variants
- **Aurora Replicas**: same cluster volume, lag usually tens of milliseconds; no replay needed.
- **Aurora cross-Region read replica (MySQL binlog)**: older approach; async via binlog.
- **Aurora Global Database (verified)**: one primary Region (writes) + up to **10** read-only secondary Regions; storage-based replication using dedicated infrastructure; lag typically **under 1 second**; each secondary can have up to 16 readers; secondary promoted on failover.
  - **Switchover** (planned, no data loss) for rotation; **failover** (unplanned) for outages; managed or manual; typical recovery about a minute (verify).
  - **Write forwarding**: secondary clusters can forward writes to the primary.
  - Same major/minor version needed for managed operations (verified); patch levels sometimes must match.
  - Limitations (verified): no Backtrack; Aurora Auto Scaling not supported on secondary clusters; Secrets Manager integration must be off when adding a Region; automatic minor upgrade doesn't apply; can't stop/start clusters individually; can't rename a cluster in a global database; a PostgreSQL primary built from an RDS replica can't get secondaries.
  - Can use Serverless v2 in secondaries to save cost.
  - Aurora PostgreSQL RPO feature (`rds.global_db_rpo`) can limit data loss.
  - Typical RPO about 1 second, RTO about 1 minute for failover.
- Aurora also supports binlog replication to other MySQL systems, and logical replication in PostgreSQL.

## F. RDS automated backups and PITR (verified)
- Automated backups: daily storage-volume snapshot (during your backup window) + transaction logs shipped to S3 every ~5 minutes (verify). Stored in S3.
- Retention: 0–35 days (0 turns them off; console default 7). Aurora: 1–35 days; default 1 day; cannot be disabled (verified).
- Instance must be `available` for backups to run. No automated backup while a snapshot copy is running in the same Region for the same DB (verified).
- **PITR** restores to any second in the retention window; latest restorable time is typically within 5 minutes of now. **Restore always creates a new DB** (new endpoint, new instance); it never overwrites the original.
- After restore, you must re-attach things not restored by default (parameter group, option group, security groups, monitoring settings, IAM roles) – check; cut apps over to the new endpoint.
- First snapshot is full; later snapshots are incremental (verified).
- Backups cover the whole instance (all databases), not single databases. To restore one table, restore a new DB then export/import that table.
- Automated backups are deleted when the instance is deleted unless you choose **retain automated backups** (kept for the retention period) (verified). Manual snapshots and the final snapshot are independent and kept.
- Backup storage: free up to the size of your provisioned storage in the Region; above that billed per GB-month (verify). Backups are Regional.
- Backup window: choose a low-traffic time. Single-AZ: brief I/O suspension; Multi-AZ: from standby.
- Cross-Region automated backups replication: continuously copy snapshots and logs to another Region for DR PITR (default quota 20 per account) (verified quota; verify engines).
- AWS Backup can manage RDS/Aurora snapshots and PITR with central policies, cross-Region/account copy and vault lock. Backups made by AWS Backup count as manual snapshots but don't count toward the 100-snapshot quota (verified).

## G. Manual snapshots, copy and sharing
- Manual snapshot: you create it; kept until you delete it. Up to **100 manual snapshots per Region** per account (verified).
- Final snapshot: optional when deleting a DB.
- Copy snapshot: within Region or to another Region (needs KMS key in destination Region if encrypted). Copy can change encryption key (verified).
- Share snapshot with other accounts (add account ID) or make public (only unencrypted).
- Encrypted snapshot sharing: only if encrypted with a **customer managed key** and the key is shared with the target account; snapshots encrypted with the AWS managed key cannot be shared (verified).
- To encrypt an unencrypted DB: snapshot → copy with encryption on → restore (verified).
- Restore from snapshot: choose new identifier, instance class, storage, Multi-AZ, subnet group, etc. You cannot restore an unencrypted snapshot to an encrypted DB directly (copy encrypted first) (verified).
- Snapshot storage cost continues after deleting the DB. Delete old snapshots or use lifecycle policies in AWS Backup.
- Magnetic snapshot restores must choose a modern storage type from 1 July 2026 (verified).

## H. Export snapshot to Amazon S3 (verified)
- Exports snapshot data (all or selected databases/schemas/tables) to S3 as compressed **Apache Parquet**. Runs in the background; no impact on the live DB (it restores the snapshot to extract).
- Works for manual, automated system, and AWS Backup snapshots. S3 bucket must be in the same Region. Needs an IAM role (service `export.rds.amazonaws.com`) and a KMS key; the KMS key policy needs `kms:CreateGrant` and `kms:DescribeKey`.
- Query with Athena or Redshift Spectrum. **You cannot restore or import exported data back into RDS** (verified); use DMS/Glue to move it.
- Limits: 5 concurrent export tasks per account; no views/materialized views; very large LOBs (~500 MB+) fail; rows near 2 GB are skipped; some characters in names are not supported; one export task per snapshot at a time.
- Good for: cheap long-term archive, analytics without touching production, compliance retention.

## I. Aurora backups and recovery (verified)
- Continuous, incremental backups to S3; no performance impact; retention 1–35 days; PITR to any second; latest restorable time within about 5 minutes. Restore creates a **new cluster** (then add instances).
- Backup window is used for a daily system backup; no impact on the database.
- Manual cluster snapshots kept until deleted; cross-Region copy and sharing like RDS.
- Backup storage: free up to the cluster volume size; extra is billed.
- **Backtrack (Aurora MySQL only)**: rewind the cluster in place (minutes) without restoring from backup. Verified facts:
  - Must be enabled when you **create or restore** the cluster; cannot be enabled on an existing cluster.
  - Window up to **72 hours** (target window; actual can be shorter on heavy workloads). You pay for stored change records.
  - Affects the whole cluster, not one table. Causes a brief disruption: connections closed, uncommitted work dropped.
  - Not supported with Aurora Global Database; no cross-Region replica from a backtrack-enabled cluster; blocked/forced issues with binlog; cannot go to before a clone existed; after in-place major upgrades you can't backtrack before the upgrade.
  - Not available for Aurora PostgreSQL.
  - Good for undoing a bad DELETE/DROP quickly; PITR is slower (new cluster).
- **Fast database cloning (verified)**: copy-on-write at the storage layer; a new cluster shares pages with the source and stores only changes. Minutes to create, tiny extra storage at first. Up to **15 copy-on-write clones**; the next is a full copy. Same Region only; can clone to another VPC (same AZ mapping) or share cross-account with AWS RAM. Source must have at least one instance. Clones can use different instance classes. Use for dev/test with prod data, schema change trials, heavy exports. Deleting the source redistributes page ownership and storage charges among clones.
- **Snapshot export** (section H) works for Aurora too (Aurora also supports `SELECT INTO OUTFILE S3` / `aws_s3` export functions – verify).

## J. Disaster recovery patterns
- **Backup & restore** (RPO minutes to hours, RTO hours): automated backups + cross-Region copy. Cheapest.
- **Pilot light**: cross-Region read replica (RDS) or Aurora secondary with a small instance; scale up and promote on disaster.
- **Warm standby / active-passive**: Aurora Global Database with full-size secondary; failover in about a minute; RPO ~1 second.
- **Multi-Region active-active**: Aurora Global with write forwarding is not true multi-master; for global multi-writer use DynamoDB global tables or Aurora DSQL (awareness).
- RDS cross-Region replica promotion: manual, RPO = replica lag (seconds to minutes), RTO minutes.
- Test failover regularly; measure RTO. Document DNS/connection changes.
- Protect against mistakes with PITR/Backtrack, not replicas.
- Cross-account backup copies and AWS Backup vault lock protect against account compromise.
- Align KMS: copies in another Region need a destination KMS key.

## K. Deletion protection and retention/privacy
- **Deletion protection** setting prevents accidental delete of an instance/cluster until turned off (default on in console for Aurora; verify).
- Deleting a DB: choose final snapshot and whether to retain automated backups (verified).
- Data deletion for legal reasons: delete rows, but also backups, snapshots, replicas, exports, logs and downstream copies. PITR window keeps old data until it expires; manual snapshots keep it forever until deleted.
- Data sovereignty: control cross-Region replicas/snapshot copies with IAM/SCP (deny `rds:CopyDBSnapshot`, `CreateDBInstanceReadReplica` across Regions) and Region restrictions.

## L. Scenarios (if → then, because)
- **If** a production database must survive an **Availability Zone (AZ)** failure automatically, **then** use **RDS Multi-AZ** (instance or cluster deployment) or **Amazon Aurora** with a **reader in another AZ**. **This works because** Multi-AZ keeps a standby in another AZ and moves the endpoint to it on failure, and Aurora promotes a reader. The catch: single-AZ gives no automatic failover, only a restore from backup.
- **If** you want **readable standbys** with **fast failover** on **RDS for MySQL or PostgreSQL**, **then** use a **Multi-AZ DB cluster**. **This works because** it has one writer and **two standbys in three AZs** that **serve reads**, with **semisynchronous** replication (a commit waits for at least one standby). It only runs on specific instance classes.
- **If** reporting slows the primary, **then** add a **read replica** (RDS) or use the **Aurora reader endpoint**. **This works because** replicas give extra read capacity. The standby in a **Multi-AZ DB instance** deployment does **not serve reads**, so it cannot take this load.
- **If** read traffic spikes unpredictably, **then** on Aurora use **Aurora Auto Scaling** for replicas; on RDS add read replicas **by hand**. **This works because** Aurora Auto Scaling adds and removes readers based on CPU or connections, while RDS read replicas have **no auto scaling**.
- **If** you need **disaster recovery (DR)** in another Region at **minimal cost**, **then** use a **cross-Region read replica** (RDS) or a **cross-Region snapshot copy**. **This works because** backup copies are the cheapest DR (hours to recover), and a small replica can be promoted to a writable database in minutes. Promotion is manual and you lose the replica lag.
- **If** you need DR with a **Recovery Point Objective (RPO)** of about **1 second** and a **Recovery Time Objective (RTO)** of about **1 minute** (verify), **then** use **Aurora Global Database**. **This works because** it copies storage to up to **10** read-only secondary Regions on dedicated infrastructure with lag usually **under 1 second**, and a secondary can be promoted on failover.
- **If** a bad **UPDATE** ran **10 minutes ago** on **Aurora MySQL** with **Backtrack** turned on, **then** **Backtrack** the cluster to just before it. **This works because** Backtrack rewinds the cluster **in place** in minutes, without a restore, within a window of up to **72 hours**. The catch: it rewinds the **whole cluster** and briefly closes connections.
- **If** a bad **DELETE** ran on **RDS** or **Aurora PostgreSQL**, **then** use **point-in-time recovery (PITR)** to restore a **new database** to just before it, then copy the rows back (or switch the app to it). **This works because** PITR restores to any second in the retention window but **always creates a new database**; Backtrack does not exist for these engines.
- **If** you need a copy of production for testing **quickly and cheaply**, **then** use an **Aurora clone**. **This works because** cloning is **copy-on-write**: the clone shares storage pages with the source and stores only changes, so it is ready in minutes with little extra storage. Up to **15** clones share pages this way.
- **If** you must keep **monthly backups for 7 years**, **then** use **manual snapshots** or **AWS Backup** with **lifecycle policies**, or **export snapshots to Amazon S3** as **Parquet** files. **This works because** automated backups keep at most **35 days**, while manual snapshots stay until you delete them and exports are cheap long-term archives.
- **If** data must be queryable in the data lake without touching the database, **then** use **snapshot export to Amazon S3** and query it with **Amazon Athena**, or use **zero-ETL**. **This works because** the export restores the snapshot in the background to extract **Parquet** files, so the live database sees no load.
- **If** a snapshot **cannot be shared** with another account, **then** copy it with a **customer managed key (CMK)** in **AWS Key Management Service (KMS)** and share both the snapshot and the key. **This works because** snapshots encrypted with the **AWS managed key** can never be shared.
- **If** an **encrypted snapshot** must go to another Region, **then** **copy** it and pick a **KMS key in the destination Region**. **This works because** KMS keys belong to one Region, so the copy must be encrypted with a key that exists where it lands.
- **If** you try to create an **unencrypted replica** of an **encrypted** database, **then** it is **not possible**: the replica must be encrypted too. **This works because** encryption must match between source and replica (same KMS key in the same Region, a destination key across Regions).
- **If** you delete a source database and its replicas **keep running**, **then** they were **promoted to standalone** databases. **This works because** deleting a source without deleting its same-Region replicas promotes each replica to its own writable database.
- **If** automated backups **vanished** after deleting the database, **then** you did not choose **"retain automated backups"**; next time take a **final** or **manual snapshot**. **This works because** automated backups are deleted with the instance unless retained, while manual and final snapshots are independent and stay.
- **If** failover took longer than expected on a **Multi-AZ DB cluster**, **then** reduce write load and fix **replica lag**. **This works because** failover picks the reader with the newest changes, and its time depends on lag; for MySQL both readers must apply pending transactions first.
- **If** the app shows **errors during failover**, **then** add **reconnect and retry** logic, connect through the **cluster endpoint**, and use **RDS Proxy**. **This works because** the endpoint's DNS moves to the new writer, and RDS Proxy keeps client connections open while it connects to the new primary.
- **If** an **Aurora Global Database** cannot add a Region, **then** check the **engine, version and instance class** requirements and turn off the **Secrets Manager** integration. **This works because** managed operations need matching versions, and the managed master password in **AWS Secrets Manager** must be off when adding a Region.
- **If** you accidentally turn off automated backups (**retention 0**) on RDS, **then** set retention back to at least **1–7 days**. **This works because** with retention 0 there are no automated backups, so **point-in-time recovery (PITR)** is impossible.
- **If** compliance requires **immutable backups**, **then** use **AWS Backup** with **vault lock** and **cross-account copies**. **This works because** vault lock stops backups from being deleted, and a copy in another account survives even if the main account is compromised.

## Verified from AWS docs on 2026-10-02
Multi-AZ overview and Multi-AZ DB cluster concepts, read replicas overview, RDS backups intro, Aurora overview, Aurora Global Database, Backtrack, cloning, Aurora backups, snapshot export, encryption pages, quotas page were read. Not confirmed (verify): failover time numbers, transaction log shipping interval, Backup storage free allowance details, deletion protection defaults, cross-Region automated backup engine support, Aurora Auto Scaling specifics, Aurora S3 export functions.

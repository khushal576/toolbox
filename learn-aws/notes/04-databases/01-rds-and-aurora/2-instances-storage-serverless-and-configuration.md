# RDS and Aurora – 2. Instance classes, storage, Serverless v2, configuration, upgrades

Short notes. Each point is a fact you can be asked about.

## A. Instance classes
- Classes: general purpose (m), memory optimized (r, x), burstable (t), compute-heavy (c, limited), plus Graviton variants (g suffix, for example db.r6g, db.m7g). Graviton is cheaper per unit of performance for MySQL, MariaDB, PostgreSQL.
- Choose memory first for databases: more RAM = bigger buffer pool/cache = fewer disk reads.
- Burstable (db.t3/t4g): baseline CPU with credits; good for dev/test and small workloads. Credits run out → CPU throttled (watch `CPUCreditBalance`). Unlimited mode lets bursting at extra cost.
- Instance class limits network bandwidth, EBS bandwidth and max IOPS. A small class cannot use huge provisioned IOPS (verified: instance-level IOPS cap applies).
- Changing instance class causes downtime on a single-AZ instance (minutes). With Multi-AZ, RDS updates the standby first and fails over (short interruption).
- Aurora: you scale compute by changing the instance class of writer/readers (failover of writer needed) or by using Serverless v2.
- Max connections depend on memory. Verified default formulas:
  - MySQL: `DBInstanceClassMemory/12582880` (about MB/12).
  - MariaDB 10.5+: `LEAST(DBInstanceClassMemory/25165760, 12000)`.
  - PostgreSQL: `LEAST(DBInstanceClassMemory/9531392, 5000)`.
  - Oracle `processes`: `LEAST(DBInstanceClassMemory/9868951, 20000)`.
  - SQL Server `user connections`: 0 = unlimited.
  - Db2: limit 64,000.
- A db.t3.micro MySQL has only about 60 connections. Do not assume large numbers on small classes.

## B. RDS storage (verified)
- RDS storage is EBS-based. Types (current):
  - **gp3 (General Purpose SSD, recommended default)**: baseline 3,000 IOPS and 125 MiB/s. For MySQL/MariaDB/PostgreSQL/Db2 at 400 GiB and above (Oracle at 200 GiB+) storage is striped over 4 volumes and the baseline becomes 12,000 IOPS and 500 MiB/s; you can provision up to 64,000 IOPS and 4,000 MiB/s (SQL Server: up to 80,000 IOPS / 2,000 MiB/s).
  - **gp2 (older)**: 3 IOPS per GiB, minimum 100, burst to 3,000 for small volumes via credits; large volumes (4,000+ GiB) get 12,000+ IOPS baseline.
  - **io2 Block Express (Provisioned IOPS, recommended for critical)**: up to 256,000 IOPS, sub-millisecond latency, up to 4,000 MiB/s (verified); IOPS-to-GiB ratio 0.5–1,000 on Nitro instances.
  - **io1 (older Provisioned IOPS)**: up to 256,000 IOPS on larger volumes (SQL Server up to 64,000), ratio up to 50:1.
  - **Magnetic (standard)**: deprecated. Existing volumes were migrated to gp3. From 1 July 2026 you cannot restore a snapshot to magnetic storage (verified).
- Max storage: 64 TiB for MySQL, MariaDB, PostgreSQL, Db2 (smaller on small/burstable classes: for example db.t3.micro 6 TiB, db.t3.small 16 TiB). Oracle and SQL Server can reach 256 TiB total by attaching up to 3 additional storage volumes (verified).
- Additional storage volumes (Oracle: `rdsdbdata2-4`; SQL Server: H:, I:, J:): can be added and removed to grow or shrink total capacity; mix gp3 and io2.
- Dedicated Log Volume (DLV): moves PostgreSQL WAL / MySQL-MariaDB redo and binary logs to a separate volume (1,024 GiB, 3,000 IOPS). Only with Provisioned IOPS storage (io1/io2). Needs a reboot to change. Good for large, write-heavy, latency-sensitive databases.
- Storage autoscaling: set a maximum storage threshold; RDS grows storage when free space is low (rule of thumb: under 10% free for several minutes, and at least 6 hours since the last change – verify). Never shrinks. Magnetic storage doesn't support it.
- You can increase storage but not decrease it. To shrink, restore/migrate to a smaller new instance (dump/restore or DMS).
- Changing storage type or size runs through `optimizing` states; performance is between old and new settings. Going from 1 volume to 4 volumes (striping) copies data and can take many hours and consume IOPS – do it off-peak.
- Storage modifications have a cool-down (about 6 hours before another change; verify).
- Read replicas can use different storage types from the source (verified table).
- When you increase allocated storage of a replica, it must be by at least 10%.
- Pick: general work → gp3; latency-critical OLTP → io2 Block Express; dev/test → gp3.

## C. Aurora storage (verified)
- Cluster volume with 6 copies in 3 AZs; auto-grows; pay for used space only; freed space when data is removed.
- Two storage configurations:
  - **Aurora Standard**: pay for storage plus per-million I/O requests. Best when I/O is under about 25% of your total Aurora bill.
  - **Aurora I/O-Optimized**: no per-I/O charges (higher instance and storage price). Best when I/O is 25% or more of the bill.
- Switching Standard → I/O-Optimized is allowed once every 30 days; switching back to Standard is allowed any time. No downtime for non-NVMe instances (including Serverless v2); NVMe-based instances need an engine restart (verified).
- Local storage on the instance holds temporary tables/sort files; its size depends on the instance class and can run out for big sorts.
- Monitor `VolumeBytesUsed`, `AuroraVolumeBytesLeftTotal`, `FreeLocalStorage`.
- Aurora I/O counts the same on writer and readers.

## D. Aurora Serverless v2 (verified)
- Auto-scaling compute for Aurora. Unit = **ACU** (about 2 GiB memory plus CPU and network).
- You set minimum and maximum ACUs per cluster. Each writer/reader scales within that range, in steps as small as 0.5 ACU, while connections and transactions continue (no waiting for a quiet moment).
- Capacity range support: 0.5–128 ACU on older versions, 0.5–256 on newer, and **0–256 ACU** on the newest versions (0 enables auto-pause).
- **Auto-pause (scale to 0 ACU)**: instance pauses when idle for the time you set; resumes on connection (takes a few seconds; verify). Billing stops for compute while paused; storage still billed.
- Billing is per second for ACUs actually used. Cluster uses at least `instances × minimum ACU` when idle (if min > 0).
- Serverless v2 supports readers, Multi-AZ, Global Database, RDS Proxy, IAM auth, Performance Insights, Backtrack (MySQL) etc.
- Mixed clusters: serverless and provisioned instances can live in the same cluster (for example big provisioned writer + serverless readers, or serverless writer + provisioned readers).
- Promotion tiers: readers in tier 0–1 keep minimum capacity at least equal to the writer's current capacity (ready for failover). Tiers 2–15 scale independently (cheaper, may need to scale up after promotion).
- Instance class is `db.serverless`.
- Best for: variable or spiky workloads, multi-tenant fleets, dev/test, new apps with unknown size, secondary Regions in a Global Database.
- Not ideal for: steady heavy load 24/7 (provisioned + Reserved Instances is cheaper), or when you need predictable cost.
- Set minimum ACU high enough to keep the buffer pool warm (low minimum → cache loss and slow cold queries).
- Max connections follow the max ACU setting (does not shrink when scaled down).
- Aurora Serverless v1 is deprecated (different architecture). Use v2.
- Metrics: `ServerlessDatabaseCapacity`, `ACUUtilization`.
- Platform versions (1–4) improve performance/scale; upgrade by maintenance or restart.

## E. Parameter groups, option groups, networking
- Parameter group = engine configuration. **Cluster parameter group** (Aurora and Multi-AZ DB clusters) applies cluster-wide; **DB parameter group** applies per instance.
- Default groups are read-only; create custom groups to change values.
- Parameter types: dynamic (apply immediately) and static (apply after reboot). Status `pending-reboot` appears when a reboot is needed.
- A parameter group change for a proxy requires an instance reboot (verified).
- Option groups: for MySQL, MariaDB, Oracle, SQL Server (for example Oracle S3 integration, SQL Server native backup `SQLSERVER_BACKUP_RESTORE`, TDE). PostgreSQL uses extensions.
- Subnet group: at least two subnets in two AZs. Choose private subnets; decide public accessibility explicitly.
- Security group: allow DB port only from app security groups (3306 MySQL/MariaDB, 5432 PostgreSQL, 1521 Oracle, 1433 SQL Server, 50000 Db2).
- IPv4 only or dual-stack options exist for endpoints.
- Multi-AZ requires subnets in multiple AZs.

## F. Maintenance and upgrades
- Maintenance window: weekly. Applies OS and engine patches. Some need downtime (reboot).
- Minor version upgrades: can be automatic (`Auto minor version upgrade`). Usually short downtime; Multi-AZ shortens it; RDS Proxy cuts downtime for Multi-AZ clusters to about a second (verified claim).
- Major version upgrades: manual, may need downtime, test first. Use **Blue/Green Deployments** to upgrade with little downtime.
- **Blue/Green Deployments** (RDS for MariaDB, MySQL, PostgreSQL; Aurora also supports it): copies production (blue) into a synchronized staging environment (green). Make changes in green (engine upgrade, parameter changes, schema changes), test, then **switch over** – downtime typically under one minute (verified). Rolls back by keeping the old blue. Blue/green on Aurora Global Database is supported with limits.
- Before switchover for zero-ETL sources: delete the integration, switch, recreate (verified limitation).
- **RDS Extended Support**: lets you stay on a major version past its end of standard support, for an extra per-vCPU-hour fee, up to 3 years. RDS auto-enrolls instances created with it enabled. If you disable it on an out-of-support instance, RDS upgrades it to the next supported major version. Applies to MySQL 5.7, PostgreSQL 11/12 examples and Aurora (verified overview).
- Deprecated or end-of-life engines are auto-upgraded eventually. Always track version support calendars.
- OS/hardware maintenance is scheduled by AWS; you can defer some.
- Stop/start: RDS instances can be stopped up to 7 days (then auto-started); not available for some configurations (for example instances with read replicas). Aurora clusters can be stopped up to 7 days (verify).
- Reboot with failover forces a Multi-AZ failover test.
- Multi-AZ DB clusters (RDS MySQL/PostgreSQL) are supported only on specific instance classes (db.c6gd, m5d, m6gd, m6id, m6idn, m8gd, r5d, r6gd, r6id, r6idn, r8gd, x2iedn) (verified).

## G. Pricing models for instances
- On-demand: per second (1-minute minimum for most engines).
- Reserved Instances (1 or 3 years): up to large discounts for steady use; size-flexible within a family for some engines; RDS reserved for Multi-AZ clusters available; Aurora RIs apply to Aurora instances (Serverless v2 isn't covered by RIs; verify).
- Savings Plans do not cover RDS by default (database savings plans exist for some services; verify).
- Storage billed per GB-month; Provisioned IOPS billed per IOPS-month.
- More cost details in file 5.

## H. Engine-specific notes (high yield)
- **MySQL/MariaDB**: binlog needed for replication and CDC (`binlog_format=ROW`, `binlog retention` via `mysql.rds_set_configuration`). Replicas use binlog. Max file size limits for tables apply (verify). Upgrade MySQL 5.7 soon (Extended Support).
- **PostgreSQL**: extensions via `CREATE EXTENSION`; allow list `rds.allowed_extensions`/`shared_preload_libraries`; logical replication needs `rds.logical_replication=1`; vacuum/autovacuum tuning matters; transaction ID wraparound is a known risk – monitor `MaximumUsedTransactionIDs`. pg_cron for scheduling.
- **Oracle**: license-included only for Standard Edition Two; BYOL otherwise; option groups for S3 integration, OEM, TDE, APEX; Oracle read replicas can be mounted replicas (cross-Region DR only) or open read-only (Active Data Guard needs license) (verify); `rdsadmin` package for admin tasks; Multitenant (CDB/PDB) configurations.
- **SQL Server**: DB mirroring or Always On AGs for Multi-AZ; native backup/restore to S3 (`.bak`); no sysadmin role (use `rdsadmin` procedures); Windows authentication with AWS Managed AD; collation chosen at creation; SQL Server Agent supported; max DBs per instance limits (verify).
- **Db2**: BYOL/marketplace; no gp2; replicas in standby mode for DR.
- **Aurora MySQL**: supports Backtrack, Parallel Query, binlog-based CDC, zero-ETL to Redshift; MySQL 8.4 compatible versions exist.
- **Aurora PostgreSQL**: pgvector, optimized reads (NVMe), cluster cache management, Babelfish (SQL Server compatibility layer, verify), zero-ETL.

## I. Scenarios (if → then, because)
- If you need predictable high IOPS for a business-critical OLTP → io2 Block Express (RDS) or Aurora with I/O-Optimized.
- If storage fills up unexpectedly → enable storage autoscaling with a max threshold (RDS); Aurora grows automatically.
- If you need to shrink storage → create a smaller new instance and migrate (no in-place shrink).
- If gp2 volume performance drops after bursts → move to gp3 or larger gp2/provisioned IOPS.
- If the instance hits connection limits → RDS Proxy, bigger instance class, tune `max_connections`.
- If traffic is spiky and nobody wants to pre-size → Aurora Serverless v2.
- If dev databases sit idle overnight → Serverless v2 with auto-pause (0 ACU), or stop the RDS instance (7-day limit).
- If a big Oracle database needs more than 64 TiB → additional storage volumes (up to 256 TiB total).
- If you need to upgrade a major version with minimal downtime → Blue/Green Deployment, then switch over.
- If an old MySQL 5.7 can't be upgraded yet → RDS Extended Support (paid) as a bridge.
- If you need OS-level access for a legacy Oracle/SQL Server app → RDS Custom.
- If a parameter change "does nothing" → it's static; reboot to apply (check `pending-reboot`).
- If I/O costs on Aurora exceed a quarter of the bill → switch to Aurora I/O-Optimized.
- If a transaction log or WAL fills storage → find long-running transactions or stuck replication slots; add DLV or storage; fix the cause.
- If a burstable instance slows after hours of load → CPU credits exhausted; move to a non-burstable class.

## Verified from AWS docs on 2026-10-02
RDS storage page, Aurora storage and Serverless v2 pages, quotas page, Blue/Green overview, Extended Support overview, Multi-AZ cluster instance classes were read. Not confirmed (verify): storage autoscaling trigger numbers, modification cool-down, stop duration, Reserved Instance coverage of Serverless v2, Oracle replica modes licensing, SQL Server HA details, Babelfish.

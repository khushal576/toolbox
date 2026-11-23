# RDS and Aurora – 5. Cost, performance tuning, monitoring, troubleshooting, limits, mixed scenarios

Short notes. Each point is a fact you can be asked about.

## A. What you pay for
- **Instance hours**: by class, per second (on-demand), or discounted with Reserved Instances (1 or 3 years).
- **Storage**: per GB-month (RDS gp3/io2/gp2); Aurora per GB-month used (auto-grows and shrinks as data is removed).
- **Provisioned IOPS / throughput**: extra for gp3 above baseline; io2/io1 IOPS per IOPS-month.
- **Aurora I/O**: Standard configuration charges per million I/O requests; I/O-Optimized has no I/O charge but higher instance and storage price. Pick I/O-Optimized when I/O is 25% or more of your Aurora bill (verified).
- **Aurora Serverless v2**: ACU-hours used (per second); idle cost = instances × minimum ACU (zero at 0 ACU with auto-pause).
- **Multi-AZ**: you pay for the standby instance and its storage (double). Multi-AZ clusters pay for three instances.
- **Read replicas**: billed as normal instances. Same-Region replication traffic is free; cross-Region replication has transfer charges (verified).
- **Backups**: backup storage is free up to your provisioned database size per Region, extra billed per GB-month (verify). Manual snapshots and retained automated backups keep costing until deleted; snapshots of deleted DBs still cost.
- **Snapshot export to S3**: export charge per GB of snapshot data plus S3 storage (verify).
- **RDS Proxy**: per vCPU-hour of the target DB (verify). **Data API**: per request (verify).
- **Backtrack**: change record storage per hour.
- **Performance Insights / Database Insights**: free short retention; longer retention paid. **Enhanced Monitoring**: CloudWatch Logs ingestion cost.
- **Extended Support**: extra per-vCPU-hour fee for engines past end of standard support (verified concept).
- **Data transfer**: out to internet and cross-Region cost; cross-AZ traffic costs between app and DB if in different AZs; same-AZ private traffic free.
- **Zero-ETL**: Aurora/Redshift/Glue-side charges (see pricing pages).
- **License**: Oracle/SQL Server license-included prices include licenses; BYOL for Oracle/Db2 does not.

## B. Cutting cost
- Right-size: check CPU, memory, connections; use Performance Insights and Compute Optimizer recommendations.
- Use Graviton instance classes where supported.
- Reserved Instances for steady 24/7 databases (1 or 3 years).
- Use Aurora Serverless v2 for spiky/dev workloads; auto-pause (0 ACU) for idle dev/test databases.
- Stop RDS dev instances when not needed (up to 7 days at a time; verify) or schedule stop/start.
- gp3 instead of gp2 and io1; provision only the IOPS you need; use io2 only when required.
- Storage: drop unused data/indexes; archive old partitions to S3 (export or partition detach).
- Aurora: choose Standard vs I/O-Optimized by I/O share of the bill; delete unused clones and snapshots.
- Remove unneeded read replicas; use Aurora Auto Scaling for readers instead of leaving many running.
- Use one Multi-AZ production DB and single-AZ for non-prod.
- Delete old snapshots; set backup retention to what you really need; use AWS Backup lifecycle.
- Avoid cross-Region replicas unless needed; place app and DB in the same AZ where HA allows (cross-AZ transfer cost).
- Consolidate small databases into one instance/cluster (schemas) when isolation allows.
- Tag resources for cost allocation; use Cost Explorer and Budgets.
- Move analytics to Redshift/Athena instead of oversizing the OLTP database.
- Cache hot reads (ElastiCache) to cut read replica count.

## C. Performance – how to think
- Most DB problems are: missing/wrong indexes, bad queries, too many connections, locks, memory too small, I/O limits, or a bad schema.
- **DB load** (Performance Insights): measured as Average Active Sessions (AAS). If AAS is above the number of vCPUs, queries are waiting. Check the wait types (CPU, I/O, lock, latch, IPC, network).
- Order to investigate: top SQL → wait events → CPU/memory/IO metrics → connection counts → locks → replication lag → storage.

## D. Query and schema tuning
- Add indexes for columns used in WHERE, JOIN, ORDER BY, GROUP BY. Composite indexes follow left-to-right use. Cover frequent queries (covering index).
- Remove unused and duplicate indexes (they slow writes and use memory).
- Use `EXPLAIN`/`EXPLAIN ANALYZE` to see plans (seq scan vs index scan, nested loop vs hash join). Look for full table scans on big tables.
- Avoid `SELECT *`, functions on indexed columns in WHERE (`WHERE DATE(col)=...`), leading wildcards `LIKE '%x'`, `OR` across different columns, implicit type conversions that disable indexes, N+1 query patterns.
- Keep statistics fresh: PostgreSQL `ANALYZE`; MySQL `ANALYZE TABLE`.
- PostgreSQL: autovacuum must keep up (bloat); tune `autovacuum_*`; watch transaction ID wraparound (`MaximumUsedTransactionIDs`); long transactions and unused replication slots block cleanup and grow WAL.
- MySQL InnoDB: buffer pool should hold the working set (`innodb_buffer_pool_size`, default about 75% of memory on RDS); check `History list length` for purge lag.
- Partition large tables (by date) for faster pruning and cheap archival.
- Batch writes in transactions; use multi-row inserts; avoid one-row-at-a-time loops.
- Use connection pooling (RDS Proxy, app pools). Set pool sizes sensibly: too many connections hurt throughput.
- Use read replicas/readers for reporting; keep long analytic queries off the primary.
- Cache hot, repeated reads outside the DB (ElastiCache/MemoryDB); use DAX-style caching only for DynamoDB.
- Use prepared statements; keep transactions short.
- Choose the right data types; avoid very wide rows; store large blobs in S3.
- Time zone and collation choices affect index use; keep them consistent.
- Schema changes: use online DDL tools or Blue/Green to avoid long locks.

## E. Infrastructure tuning
- Scale up instance class when CPU is consistently high or memory is short (watch `FreeableMemory`, `SwapUsage`).
- Scale out reads with replicas (async lag!).
- Storage performance: if `DiskQueueDepth` is high or latency is high and IOPS are at the limit, raise provisioned IOPS/throughput, switch gp2→gp3→io2, or choose a larger instance (instance EBS caps apply).
- Instance-level IOPS cap: provisioning IOPS above the instance class limit doesn't help (verified).
- Burstable instance credit exhaustion → CPU or EBS burst bucket (`EBSByteBalance%`, `EBSIOBalance%`) drops; move to a bigger/non-burstable class (verified metric mention).
- Aurora-specific: optimized reads on NVMe instances (r6gd/r6id), Parallel Query for analytic scans on Aurora MySQL, cluster cache management for fast failover warm-up (PostgreSQL), reader endpoint for spreading reads, avoid hot single-row contention on the writer.
- Aurora temp space is local to the instance; big sorts can run out of local storage (watch `FreeLocalStorage`).
- Parameter tuning examples: `max_connections`, `work_mem` (PostgreSQL), `shared_buffers` (default ~25% RAM), `effective_cache_size`, `innodb_buffer_pool_size`, `innodb_flush_log_at_trx_commit`, `binlog` settings. Change in a custom parameter group; static ones need reboot.
- Use enhanced instance metrics: Enhanced Monitoring for OS processes; Performance Insights for DB.

## F. Monitoring – metrics to know
- Instance health: `CPUUtilization`, `FreeableMemory`, `SwapUsage`, `FreeStorageSpace`, `DatabaseConnections`.
- I/O: `ReadIOPS`, `WriteIOPS`, `ReadLatency`, `WriteLatency`, `ReadThroughput`, `WriteThroughput`, `DiskQueueDepth` (queued I/O waiting), `EBSByteBalance%` (burst throughput left) (verified).
- Replication: `ReplicaLag` (RDS), `AuroraReplicaLag`, `AuroraGlobalDBReplicationLag`, `AuroraGlobalDBRPOLag`, `OldestReplicationSlotLag` (PostgreSQL), `BinLogDiskUsage` (MySQL).
- PostgreSQL: `MaximumUsedTransactionIDs`, `TransactionLogsDiskUsage`, `CheckpointLag`.
- Aurora: `VolumeBytesUsed`, `AuroraVolumeBytesLeftTotal`, `BufferCacheHitRatio`, `Deadlocks`, `AuroraBinlogReplicaLag`, `FreeLocalStorage`.
- Serverless v2: `ServerlessDatabaseCapacity`, `ACUUtilization`.
- Backtrack: `BacktrackWindowActual` vs `BacktrackWindowAlert` (actual window smaller than target triggers notification).
- Alarms: CPU > 80% sustained, FreeStorageSpace low, FreeableMemory low, connections near max, ReplicaLag high, DiskQueueDepth high, failover events, backup failures.
- Tools: Performance Insights/Database Insights (DB load, top SQL, waits), Enhanced Monitoring (OS), CloudWatch Logs (slow query, error), RDS events (SNS), CloudTrail (API), Trusted Advisor, AWS Config.
- Enable slow query log (`slow_query_log`, `long_query_time` for MySQL; `log_min_duration_statement` for PostgreSQL) and publish to CloudWatch Logs.

## G. Troubleshooting (symptom → cause → fix)
- High CPU → bad queries/missing indexes, too many connections, undersized instance → find top SQL, add indexes, pool connections, scale up.
- High memory/swap → buffer settings too big for class, too many connections (each uses memory), big sorts → reduce `work_mem`/connections, scale up.
- Storage full (`storage-full`) → data growth, WAL/binlog buildup, temp files, replication slot → autoscaling, clean slots/binlogs, add storage; instance stops accepting writes.
- Connection errors "too many connections" → `max_connections` reached → RDS Proxy, fix leaks, increase memory/parameter.
- Slow queries after a restore/failover/cold start → cache is cold → warm up, keep Aurora readers warm (cluster cache management), set Serverless v2 min ACU higher.
- Replica lag growing → heavy writes, long transactions, replica too small, network/cross-Region distance → bigger replica, reduce write bursts, split big transactions.
- Failover took long → big replica lag (Multi-AZ cluster) or crash recovery → monitor lag; use Aurora for faster failover.
- Deadlocks/lock waits → long transactions, missing indexes, inconsistent lock order → shorten transactions, add indexes, retry (file 1).
- `inaccessible-encryption-credentials` → KMS key disabled/revoked → re-enable key and start within 7 days or restore snapshot.
- `incompatible-parameters` → parameter value too large for memory (for example connections) → fix parameter group, reboot.
- `incompatible-restore`/restore errors → engine/parameter/option group mismatches → check restore settings.
- Can't connect → SG/NACL/route, wrong endpoint, public accessibility off, DNS, SSL mismatch, IAM token expired (15 min), user host mismatch (MySQL `user@host`).
- Application errors during failover → no retry/reconnect, long DNS caching → use cluster endpoint, retries, RDS Proxy.
- Backups failing → instance not `available` (for example storage-full), snapshot copy running → fix state.
- Snapshot restore slow → data loaded lazily from S3 on first access (performance "warming"); run queries to warm; use Aurora clone instead.
- Aurora storage unexpectedly large → many clones, long-running transactions holding old versions, large temp or binlog → check `VolumeBytesUsed`, drop clones/data.
- Zero-ETL stuck or table in failed state → no PK (PostgreSQL), unsupported types/DDL, filters; check integration status and resync.
- IAM auth fails → token expired, SSL missing, wrong DB user/role (`rds_iam` for PostgreSQL), policy resource ID wrong.
- RDS Proxy errors → too many connections to DB, pinning, Secrets Manager permission, wrong port, proxy target unhealthy.
- Data API timeouts/limits → result over 1 MB or request over 4 MB; use pagination or a native connection.
- Global database lag high → heavy write, cross-Region network, secondary under-provisioned.
- Upgrade/patch failed → incompatible extensions/parameters; test with Blue/Green or a restored copy.
- Big sort or index build fails → local storage full on Aurora instance; use larger class or `work_mem` limits.

## H. Limits and numbers (verified unless marked)
- DB instances per account per Region: 40 default (20 in ap-south-1). Includes RDS, Aurora, Neptune, DocumentDB. SQL Server editions: 10 each (license-included); Oracle license-included: 10; Oracle BYOL: 40; Db2 BYOL: 40.
- Aurora clusters: 40 per account per Region.
- Read replicas per source: 15 (RDS). Aurora: up to 15 Aurora Replicas; Global Database secondary cluster up to 16 readers.
- Manual snapshots: 100 per Region (instances) and 100 (clusters), adjustable. AWS Backup snapshots don't count.
- Cross-Region automated backup quota: 20 per account; concurrent snapshot copies 20 per Region; concurrent cross-Region read replica creation 20 per Region.
- Concurrent snapshot export tasks: 5.
- Subnets per DB subnet group: 20 (fixed). DB subnet groups: 50 (20 in ap-south-1). Parameter groups: 50. Option groups: 20. Event subscriptions: 20. Custom endpoints per Aurora cluster: 5. IAM roles per instance/cluster: 5.
- Total RDS storage for all instances: 100,000 GB per Region (default; not for Aurora).
- RDS storage max: 64 TiB (MySQL, MariaDB, PostgreSQL, Db2); 256 TiB for Oracle/SQL Server with additional volumes. Aurora cluster volume: 128 TiB (up to 256 TiB on newer versions – verify).
- gp3 baseline 3,000 IOPS/125 MiB/s (12,000/500 on striped volumes); io2 Block Express up to 256,000 IOPS and 4,000 MiB/s.
- Backup retention: RDS 0–35 days (default 7 via console); Aurora 1–35 days (default 1), cannot be disabled.
- PITR latest restorable time about 5 minutes ago.
- Backtrack window max 72 hours (Aurora MySQL only).
- Aurora Global Database: up to 10 secondary Regions; lag typically under 1 second.
- Aurora clones: 15 copy-on-write clones.
- Serverless v2: 0–256 ACU (version dependent); 1 ACU ≈ 2 GiB; step 0.5 ACU.
- Aurora Standard ↔ I/O-Optimized switch: Standard→I/O-Optimized once per 30 days.
- RDS Proxy: 20 proxies per account; 200 secrets per proxy; 20 extra endpoints per proxy.
- IAM DB auth token lifetime: 15 minutes.
- Data API: 4 MB request, 1 MB result set, 10 MB JSON response.
- Zero-ETL: 100 per account; 50 per target; 5 per source cluster; catalog name 19 characters (lakehouse).
- Naming: DB instance identifier 1–63 chars, letter first, no trailing/double hyphen; master password lengths: Db2 8–255, MariaDB/MySQL 8–41, Oracle 8–30, SQL Server/PostgreSQL 8–128.
- Max connections defaults: formulas in file 2.
- Extended Support: up to 3 years past end of standard support (verified).
- Multi-AZ DB cluster: semisynchronous, 3 instances in 3 AZs.

## I. Mixed scenarios (if → then, because)
1. If a web app on MySQL needs HA with automatic failover → Multi-AZ instance (or Aurora MySQL with a replica in another AZ).
2. If the app also needs to scale reads and wants readable standbys → Multi-AZ DB cluster or Aurora.
3. If reporting needs a stable copy and 15 readers → Aurora Replicas + custom endpoint for analytics.
4. If a DR plan needs RPO ~1 s and RTO ~1 min across Regions → Aurora Global Database.
5. If a DR plan allows hours of RTO and wants minimum cost → cross-Region snapshot copies (or cross-Region automated backups).
6. If a table was dropped by mistake on Aurora MySQL 20 minutes ago and Backtrack is on → Backtrack; otherwise PITR to a new cluster.
7. If a nightly job needs a fast prod-like copy → Aurora clone.
8. If an Oracle app needs custom OS packages → RDS Custom for Oracle.
9. If a team wants SQL Server backups in S3 → native backup/restore with the `SQLSERVER_BACKUP_RESTORE` option group.
10. If a startup's traffic is unpredictable and cost must follow usage → Aurora Serverless v2.
11. If a dev DB is used 8 hours a day → Serverless v2 with auto-pause or scheduled stop.
12. If many Lambda functions open connections → RDS Proxy (and IAM auth to proxy).
13. If a data lake needs OLTP data hourly without custom pipelines → zero-ETL to Redshift, or snapshot export to S3 for batch.
14. If a CDC feed with deletes must reach S3/Kinesis → DMS with CDC (set binlog ROW / logical replication).
15. If PII must be encrypted at rest with customer-controlled keys → CMK at creation.
16. If a security team wants who-changed-what at the AWS level → CloudTrail; SQL-level → audit plugin/DAS.
17. If upgrade from MySQL 5.7 to 8.0 must be low-downtime → Blue/Green Deployment.
18. If a cost review shows Aurora I/O at 40% of the bill → switch to I/O-Optimized.
19. If storage grows 5% a week unexpectedly on Aurora → check clones, long transactions, binlog, temp usage.
20. If CPU is high only during a daily report → read replica or Aurora reader for the report; schedule off-peak.
21. If connection count is at max → RDS Proxy and fix connection leaks before upsizing.
22. If failover time matters most → Aurora with a reader in tier 0 (and RDS Proxy).
23. If a PostgreSQL DB's disk fills because of WAL → find the lagging/unused replication slot and drop it.
24. If PostgreSQL slows over weeks → bloat/autovacuum lag/stale statistics → tune autovacuum, run ANALYZE.
25. If a vector search must combine similarity with SQL filters and transactions → pgvector on Aurora/RDS PostgreSQL with HNSW.
26. If a vector index build runs out of memory → raise `maintenance_work_mem`, lower `m`/`ef_construction`, or use IVFFlat.
27. If an app needs wide global reads with local latency → Aurora Global Database readers in each Region.
28. If you need point-in-time recovery across Regions → cross-Region automated backups replication or cross-Region copy of snapshots plus logs.
29. If you need to prove backups are protected from deletion → AWS Backup vault lock with cross-account copies.
30. If a team wants a no-ops, globally distributed, strongly consistent SQL database → look at Aurora DSQL (awareness); for key-value use DynamoDB global tables.
31. If a legacy app can't handle failover DNS changes → RDS Proxy or retry-aware drivers (AWS JDBC wrapper).
32. If you need to move data from RDS to another account/Region → snapshot share/copy (CMK), or DMS for continuous.
33. If Oracle licensing cost is a problem → migrate to Aurora PostgreSQL with SCT/DMS Schema Conversion.
34. If only a few tables of a huge DB are needed in the lake → partial snapshot export (selected tables) or DMS with table mappings.
35. If you want per-tenant isolation with minimal cost → schema-per-tenant or RLS in PostgreSQL; separate clusters for strict isolation.

## Verified from AWS docs on 2026-10-02
RDS quotas, storage, Aurora storage/I-O-Optimized, Serverless v2, Global Database, Backtrack, cloning, RDS Proxy, IAM database authentication, Data API index, zero-ETL, Extended Support, Performance Insights/Database Insights overview pages were read. Not confirmed (verify): backup storage free allowance, RDS Proxy and Data API pricing basis, Reserved Instance coverage details, Aurora max volume size per version, stop/start duration, exact CloudWatch metric set for every engine, rule-of-thumb parameter defaults (shared_buffers, buffer pool %).

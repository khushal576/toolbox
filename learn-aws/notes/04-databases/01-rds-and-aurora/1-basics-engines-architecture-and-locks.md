# RDS and Aurora – 1. Basics, engines, architecture, locks

Short notes. Each point is a fact you can be asked about.

## A. What RDS is
- Amazon RDS = managed relational databases. AWS runs the hardware, OS, install, patching, backups, failover. You manage schema, queries, users, tuning.
- You get no OS access (except RDS Custom) and no SSH. You connect with normal database clients over the engine port.
- Engines: MySQL, MariaDB, PostgreSQL, Oracle, SQL Server, Db2. Plus **Aurora** (MySQL-compatible and PostgreSQL-compatible), which is a different architecture built by AWS.
- Pick RDS/Aurora for: OLTP apps, transactions, joins, SQL, existing apps, lift-and-shift of databases, reporting on replicas.
- Avoid it for: unlimited key-value scale with millisecond lookups (DynamoDB), heavy analytics on huge data (Redshift/Athena), full-text search at scale (OpenSearch), graph (Neptune), caching (ElastiCache/MemoryDB).
- RDS is regional and runs in your VPC (instances live in subnets you choose).
- Shared responsibility: AWS = infrastructure, patching, backups, failover mechanics. You = data, schema, indexes, queries, parameter tuning, access, encryption choices, and choosing Multi-AZ/backup settings.

## B. RDS vs similar choices
- RDS vs self-managed on EC2: RDS removes patching, backups, HA work; EC2 gives OS control, unsupported engines/plugins, full custom config.
- RDS vs RDS Custom: Custom (Oracle, SQL Server) gives OS and database admin access for legacy apps needing custom patches/agents. You take on more responsibility; RDS Proxy is not supported with Custom for SQL Server (verified).
- RDS vs Aurora: Aurora has faster failover, up to 15 low-lag replicas, shared storage that auto-grows, Global Database, Serverless v2, Backtrack (MySQL), fast cloning. RDS has more engines (Oracle, SQL Server, Db2, MariaDB) and is often cheaper for small steady loads.
- RDS/Aurora vs DynamoDB: SQL, joins, ACID across tables vs key-based, massive horizontal scale, no joins.
- RDS vs Redshift: OLTP row store vs OLAP columnar warehouse. Use zero-ETL or exports to move data for analytics.
- RDS vs DocumentDB/Neptune/Keyspaces: those are special models (MongoDB-like, graph, Cassandra-like).

## C. Engine choice – what each is for
- **MySQL / MariaDB**: popular open source, InnoDB, simple, wide tool support, binlog-based replication. Good for web apps.
- **PostgreSQL**: advanced SQL, JSON, extensions (PostGIS, pgvector, pg_cron, pglogical, aws_s3, aws_lambda), logical replication. Good for complex queries and vector search.
- **Oracle**: for existing Oracle apps. Licensing: license-included (Standard Edition Two) or bring your own license (BYOL). Features like TDE, Data Guard-style replicas (mounted/active replicas), options (S3 integration, OEM). Supports up to 256 TiB with additional storage volumes (verified).
- **SQL Server**: editions Express, Web, Standard, Enterprise; license-included. Native backup/restore using `.bak` files in S3; Always On (Enterprise) or mirroring for Multi-AZ (verify); AD authentication; additional storage volumes up to 256 TiB total (verified).
- **Db2**: IBM Db2 (BYOL or marketplace); fewer features (no gp2).
- **Aurora MySQL / Aurora PostgreSQL**: cloud-native versions with the shared cluster volume.
- Same engine in RDS and Aurora behaves similarly at the SQL level; operations differ (storage, replicas, backup).
- Choose the engine your app already uses to avoid rewrites. Use SCT/DMS Schema Conversion + DMS when changing engines (heterogeneous migration).
- Oracle/SQL Server license-included instance quotas are lower (10 per edition) than open source (40) by default (verified).

## D. Core RDS building blocks
- **DB instance**: one managed database server (class + storage + engine).
- **DB instance class**: CPU and memory. Families: general purpose (m), memory optimized (r, x), compute-intensive in some (c), burstable (t – credits). Graviton (g) is cheaper per performance for MySQL/MariaDB/PostgreSQL.
- **Storage**: EBS-backed (gp3, io1, io2). Details in file 2.
- **DB subnet group**: set of subnets (at least 2 AZs) where RDS can place instances. Up to 20 subnets per group (verified).
- **Security group**: controls network access to the DB port.
- **Parameter group**: engine settings (like `max_connections`, `innodb_buffer_pool_size`). Static params need a reboot; dynamic apply at once.
- **Option group**: extra features for Oracle, SQL Server, MySQL, MariaDB (not PostgreSQL – it uses extensions).
- **Endpoint**: DNS name for connecting. For Multi-AZ, the same endpoint points to the current primary (DNS changes on failover).
- **Automated backups, snapshots**: see file 3.
- **Events and notifications**: RDS events to SNS/EventBridge.
- **Maintenance window**: weekly slot for patching/upgrades.
- **Master user**: created at launch; manage with Secrets Manager (RDS can manage and rotate the password).

## E. Aurora architecture (verified)
- An Aurora **DB cluster** = one or more DB instances + a **cluster volume**.
- Cluster volume: single logical SSD-based volume spanning **3 AZs with 6 copies** of data; the number of copies does not depend on how many instances you have.
- Storage grows automatically (10 GiB up; max 128 TiB, and newer versions up to 256 TiB – verify per engine version). You pay only for used space; space is freed when you drop or truncate data.
- Compute and storage are separate. Adding a reader doesn't copy data; it attaches to the same volume.
- **Writer (primary) instance**: one per cluster, does all writes.
- **Aurora Replicas (readers)**: up to **15**, read-only, share the same volume, replica lag typically tens of milliseconds. They are failover targets with a priority (promotion tier 0–15).
- Quorum model: writes need 4 of 6 copies; reads need 3 of 6. Survives loss of an AZ without losing write ability, and AZ+1 copy without losing read ability (verify wording).
- Self-healing storage: segments are repaired from other copies automatically.
- Temporary files (sort, index builds) use local instance storage, not the cluster volume.
- Aurora does not need Multi-AZ to be configured for storage durability. For compute HA add a reader in another AZ.
- Endpoints:
  - **Cluster (writer) endpoint**: always the current writer.
  - **Reader endpoint**: load-balances across readers.
  - **Custom endpoints**: groups of chosen instances (for example analytics readers).
  - **Instance endpoints**: a specific instance (avoid for app use).
- Aurora MySQL-compatible and Aurora PostgreSQL-compatible versions follow specific community versions with AWS changes.
- Variants: Provisioned, Serverless v2, Global Database, Parallel Query (MySQL), Aurora Limitless Database (sharded horizontal write scale, awareness), Aurora DSQL (serverless distributed SQL, separate product, awareness).
- Aurora I/O-Optimized vs Standard storage configurations (file 5 for cost).

## F. When to pick Aurora over RDS
- Need fast failover (tens of seconds) and many read replicas.
- Need a global read layer or cross-Region DR with ~1 second lag (Global Database).
- Variable/spiky load → Serverless v2.
- Large databases that grow unpredictably (auto-growing storage).
- Need fast clones for test environments, Backtrack (MySQL).
- High write/read performance for MySQL/PostgreSQL compatible apps.
- Pick plain RDS when: engine is Oracle/SQL Server/Db2/MariaDB, tiny/steady workloads where cost matters, or you want standard community behavior without Aurora differences.

## G. OLTP basics you need
- ACID: Atomicity (all or nothing), Consistency (valid state), Isolation (concurrent transactions don't see each other's partial work), Durability (committed = saved).
- Row store, indexes (B-tree), foreign keys, constraints are enforced (unlike Redshift).
- Normalized schemas; joins are cheap on indexed keys.
- Connection model: persistent TCP connections; each uses memory. Many short connections (Lambda) → use RDS Proxy.
- Scale read: replicas. Scale write: bigger instance, or shard in the app (or Aurora Limitless). Writes go to one primary.

## H. Locks and isolation (exam skill 2.1.6)
- Isolation levels (strongest to weakest): SERIALIZABLE, REPEATABLE READ, READ COMMITTED, READ UNCOMMITTED. Defaults: MySQL/MariaDB InnoDB = REPEATABLE READ; PostgreSQL = READ COMMITTED; SQL Server = READ COMMITTED (optionally snapshot).
- MVCC (multi-version concurrency control): PostgreSQL and InnoDB let readers not block writers. Old row versions are cleaned up (VACUUM in PostgreSQL, purge in InnoDB).
- Lock types: row locks, table locks, metadata (DDL) locks, advisory locks (PostgreSQL), gap/next-key locks (InnoDB), lock escalation (SQL Server).
- Deadlock: two transactions wait for each other. The engine kills one (victim). Apps must retry.
- Blocking: a long or idle open transaction holds locks and blocks others. Typical cause of "everything is slow".
- Find blockers:
  - MySQL/MariaDB: `SHOW ENGINE INNODB STATUS`, `information_schema.innodb_trx`, `performance_schema.data_lock_waits`, `SHOW PROCESSLIST`; end with `CALL mysql.rds_kill(thread_id)` (RDS) or `KILL`.
  - PostgreSQL: `pg_stat_activity` (state, wait_event), `pg_locks`, `pg_blocking_pids()`; end with `SELECT pg_terminate_backend(pid)` or `rds_superuser` helpers.
  - SQL Server: `sys.dm_tran_locks`, `sys.dm_exec_requests` (blocking_session_id), `KILL spid`.
  - Oracle: `V$LOCK`, `V$SESSION`, `DBA_BLOCKERS`; kill via `rdsadmin.rdsadmin_util.kill`.
- Performance Insights shows lock wait events (like `lock:transactionid`, `Lock:relation`, `row lock`) by SQL and session.
- Prevent: keep transactions short, commit/rollback always, set timeouts (`lock_timeout`, `statement_timeout`, `idle_in_transaction_session_timeout` in PostgreSQL; `innodb_lock_wait_timeout` in MySQL), add proper indexes (missing indexes widen row locks), avoid DDL during peak, use `SELECT ... FOR UPDATE SKIP LOCKED` for queues, consistent lock ordering.
- DDL on a big table can take a metadata lock and queue everything behind it – run in low traffic or use online schema change tools.
- Long-running transactions also prevent cleanup (PostgreSQL VACUUM, MySQL undo growth) → bloat and `HistoryListLength` growth.
- Replication adds its own lock-like waits: replica lag when long transactions are replayed.
- Redshift locks are different (see Redshift); DynamoDB uses conditional writes instead of locks.

## I. Connecting
- Use the instance/cluster endpoint DNS name, never an IP (IP changes on failover).
- Applications should reconnect and retry on failover (DNS TTL ~5 seconds for Aurora endpoint, verify).
- JDBC/ODBC drivers: AWS advanced JDBC and Python drivers support failover awareness and IAM auth plugins.
- Use SSL/TLS; download the RDS CA bundle.
- Public accessibility is a setting; keep it off for production and use private subnets.
- Use RDS Proxy for Lambda or connection storms (file 4).
- Use Data API (Aurora) for HTTP-based SQL without connections (file 4).

## J. Scenarios (if → then, because)
- **If** you are lifting an existing PostgreSQL or MySQL app to AWS, **then** use **Amazon Relational Database Service (RDS)** or **Amazon Aurora** with the **same engine**. **This works because** the same engine behaves the same at the SQL level, so the app needs **no code change**; only operations (storage, replicas, backup) differ.
- **If** an app needs **Oracle** features and you want AWS to run the operations, **then** use **RDS for Oracle**. If the app also needs **operating system (OS) and database admin access** (custom patches or agents), use **RDS Custom for Oracle**. **This works because** plain RDS gives no OS access or SSH, while RDS Custom opens it up. The catch: with Custom you take on more of the responsibility yourself.
- **If** a team wants **fast failover** and **many read replicas**, **then** use **Amazon Aurora**. **This works because** Aurora fails over in **tens of seconds** and supports up to **15 Aurora Replicas** (read-only copies) that share one storage volume with the writer, so their lag is only tens of milliseconds.
- **If** traffic is unpredictable, **then** use **Aurora Serverless v2**. **This works because** it scales compute up and down automatically in small steps, measured in **Aurora Capacity Units (ACU)**, so you do not have to pre-size the instance.
- **If** cost matters and the workload is **small and steady**, **then** use plain **Amazon RDS** with **gp3** storage (General Purpose SSD), **Graviton** instance classes and **Reserved Instances** (1- or 3-year commitment). **This works because** RDS is often cheaper than Aurora for small steady loads, Graviton is cheaper per unit of performance, and Reserved Instances discount 24/7 use.
- **If** you need **MongoDB-like documents**, **then** use **Amazon DocumentDB**, not RDS. **This works because** RDS is a relational (tables and SQL) service, while DocumentDB is built for the document model.
- **If** a query is **blocked for minutes**, **then** find the blocking transaction (`pg_blocking_pids()` in PostgreSQL, `information_schema.innodb_trx` in MySQL), **end it** (`pg_terminate_backend` or `mysql.rds_kill`), and fix how the app handles transactions. **This works because** a long or idle open transaction holds **locks** and blocks everyone behind it, which is a typical cause of "everything is slow". Keep transactions short and set timeouts so it does not come back.
- **If** **deadlocks** appear (two transactions waiting for each other), **then** add **retry logic** in the app, take locks in a **consistent order**, and keep transactions **short**. **This works because** the engine kills one transaction (the victim) to break a deadlock, so the app must retry it, and consistent ordering plus short transactions make deadlocks rarer.
- **If** an app opens **thousands of connections from AWS Lambda**, **then** put **RDS Proxy** in front of the database. **This works because** RDS Proxy is a managed connection pooler: many short client connections share a **smaller pool** of database connections, and each database connection uses memory.
- **If** you must migrate **Oracle to Aurora PostgreSQL**, **then** use the **AWS Schema Conversion Tool (SCT)** or **DMS Schema Conversion** for the schema and code, and **AWS Database Migration Service (DMS)** for the data with a **full load plus change data capture (CDC)**. **This works because** changing engines (a heterogeneous migration) needs the schema converted first, and CDC keeps copying new changes until you cut over.
- **If** reporting queries slow down the primary, **then** send them to a **read replica** (RDS) or the **Aurora reader endpoint**. **This works because** writes go to one primary, while replicas give extra **read capacity** so long reports no longer compete with the app.
- **If** global users need **low-latency reads in other Regions**, **then** use **Aurora Global Database** (or **cross-Region read replicas** on RDS). **This works because** Global Database copies data to read-only secondary Regions with about **1 second** of lag, so users read from a nearby Region.
- **If** you want to avoid managing a cluster at all, **then** look at **Aurora DSQL** (serverless distributed SQL) or **Amazon DynamoDB**, depending on the data model (awareness only). **This works because** both are serverless, so there are no instances to size or patch.
- **If** you need **vector similarity search** together with SQL, **then** use **PostgreSQL with the pgvector extension** on **RDS or Aurora** (details in file 4). **This works because** pgvector stores embeddings (lists of numbers) in a normal table, so you can mix similarity search with ordinary SQL filters and joins.
- **If** you need analytics on OLTP (transactional) data without slowing the database, **then** use a **zero-ETL integration** to **Amazon Redshift** or a **snapshot export to Amazon S3**. **This works because** zero-ETL copies data in near real time with no pipeline to build, and snapshot export reads a snapshot in the background, so the live database is not touched.

## Verified from AWS docs on 2026-10-02
Aurora cluster overview and storage pages, Multi-AZ overview, RDS quotas page, storage page, Global Database page were read. Not confirmed (verify): Aurora max volume size per version (128 vs 256 TiB), failover DNS TTL, SQL Server HA details, exact lock-kill procedure names, DSQL/Limitless specifics.

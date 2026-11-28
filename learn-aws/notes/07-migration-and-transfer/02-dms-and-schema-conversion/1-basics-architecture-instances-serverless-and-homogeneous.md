# DMS – 1. What it is, how it works, replication instances, Serverless, homogeneous migrations

Short notes. Each point is a fact you can be asked about.

## A. What it is (verified)
- **AWS Database Migration Service (DMS)** migrates **relational databases, data warehouses, NoSQL databases and other data stores** into AWS, between AWS services, or between cloud and on-premises.
- It does the **data** part: one-time copy (**full load**) and/or ongoing copy of changes (**CDC = change data capture**).
- It can keep source and target **in sync** during a migration so cutover is short (minutes).
- At its core, DMS is **a server (replication instance) in AWS that runs replication software**. You give it a **source endpoint** and a **target endpoint**, then run a **task**.
- DMS can create the target **tables and primary keys** if missing. It does **not** automatically create secondary indexes, foreign keys, triggers, users or most code objects → use **DMS Schema Conversion** (or native tools) for those.
- Supports **homogeneous** (same engine, e.g. Oracle → Oracle) and **heterogeneous** (different engine, e.g. Oracle → PostgreSQL) migrations.
- Pay-as-you-go: you pay for replication capacity and extra log storage. **Inbound data transfer into DMS is free.**
- Data at rest on the replication instance is encrypted with **KMS**; data in flight can use **SSL/TLS** per endpoint.

## B. Typical migration flow (exam story)
1. **Assess / discover** the source (Fleet Advisor inventory, assessment reports; see below).
2. **Convert the schema** if the engine changes (DMS Schema Conversion or SCT) and apply it to the target.
3. Prepare network (VPC, subnet group, security groups, VPN/Direct Connect to on-premises).
4. Create **replication instance** (or Serverless replication), **endpoints**, and a **task**.
5. Run **premigration assessment**, then **full load + CDC**.
6. **Validate** data (DMS data validation).
7. Add indexes/constraints/triggers on target, then **cut over** apps; stop the task.
- Other nearby services: **DataSync** (files), **Snow Family** (offline bulk), **MGN** (servers), **Transfer Family** (SFTP).

## C. Core components (verified)
- **Replication instance**: EC2-based server that connects to source, reads, formats, and loads to the target. Lives in a **VPC** (via a **replication subnet group**). Most work happens in **memory**; large transactions buffer on **disk**.
- **Endpoint**: connection info for source or target (engine, host, port, credentials, SSL mode, extra connection attributes). Credentials can come from **Secrets Manager**.
- **Task (replication task)**: what to migrate and how: migration type, table mappings, task settings. Runs on a replication instance.
- **Table mappings**: JSON **selection rules**, **transformation rules**, **table-settings rules** (see file 2).
- **Replication subnet group**: subnets (at least two AZs) where the instance can be placed.
- **Events / event subscriptions**: SNS notifications for DMS events.
- **Certificates**: import CA certs for SSL verification.
- **Control tables**: DMS can write bookkeeping tables (like `awsdms_apply_exceptions`, `awsdms_status`) on the target. Validation failures go to `awsdms_control.awsdms_validation_failures_v1`.
- **Assessment runs**: premigration checks.
- **Instance profile, data provider, migration project**: used by **Schema Conversion** and **homogeneous data migrations** (serverless features).

## D. Migration types (task types) (verified)
- **Full load**: copy existing data once. Task stops when done.
- **CDC only**: replicate changes from a chosen start point (e.g., after you loaded data with native tools).
- **Full load + CDC**: load existing data, apply the changes that happened meanwhile (**cached changes**), then keep replicating.
- A task has up to **three phases**: **full load** → **application of cached changes** → **ongoing replication (CDC)**.
- CDC reads the source **transaction log** (redo/binlog/WAL). The source must have logging configured (examples): Oracle **supplemental logging**, MySQL **binary logging in ROW format**, PostgreSQL **logical replication / wal_level=logical**, SQL Server **MS-Replication or MS-CDC**. (details: verify per engine docs)
- **CDC is not real-time and has no SLA.** Latency depends on source load, transaction size, network, instance class, target ingest speed, LOBs, and number of tasks. Spikes of minutes during batch jobs are normal. Don't use DMS CDC for sub-second guarantees.
- You can stop and **resume** tasks; CDC resumes from where it stopped (using checkpoints) as long as the source logs are still available.
- If the source is upgraded, **stop DMS tasks first**, then resume after.

## E. Replication instance classes and sizing (verified)
- Families on the pricing page: **T2/T3** (burstable, test/small), **C4/C5/C6i** (compute-optimized), **R4/R5/R6i** (memory-optimized).
- **C** class: CPU-heavy work such as **heterogeneous** migrations (for example Oracle → PostgreSQL) because conversions use CPU.
- **R** class: memory-heavy work: ongoing CDC on high-throughput systems, many tasks, many LOBs.
- **T3**: tests and small migrations; T3 CPU-credit charges apply if usage exceeds baseline.
- **Storage** is GP2 SSD: **50 GB** default on T-class, **100 GB** on C/R classes. Used for logs and cached changes. Increase if the source is busy, transactions are large, or you run many tasks. Check `ReadIOPS` + `WriteIOPS` against the GP2 baseline (3 IOPS/GB, burst 3,000).
- Rough memory estimate (LOBs): Full LOB mode ≈ LOB columns × parallel tables × LOB chunk size × commit rate; Limited LOB mode ≈ LOB columns × parallel tables × max LOB size × bulk array size.
- **Multi-AZ**: synchronous standby replica in another AZ → **automatic failover**, no I/O freeze. Recommended for **ongoing replication**; costs more and can slow applying changes slightly. A **full load** task that fails over **fails** and must be restarted for tables not completed.
- **Public vs private** replication instance: private (no public IP) is the secure default; public needed only to reach internet endpoints.
- **IP addressing**: IPv4 or dual-stack supported.
- **Engine versions**: AWS releases new replication-engine versions; test before upgrading production; `auto minor version upgrade` and a **maintenance window** apply.
- **Network setups** for on-premises sources: **VPN** or **Direct Connect** from the VPC; replication instance in a private subnet; route and security group rules allow DB ports. Source/target in same VPC is simplest.
- Use **Route 53 Resolver** (inbound/outbound endpoints and forwarding rules) if endpoints are resolved by your **on-premises DNS**.
- Replication instance needs access to dependencies (S3, Kinesis, DynamoDB, Secrets Manager, Redshift, OpenSearch) either through **public routes** or **VPC endpoints** (required for several targets since engine 3.4.7).

## F. DMS Serverless (verified)
- **No replication instance to size or patch.** DMS **provisions, scales and deprovisions** capacity automatically. You pay for capacity used.
- You create a **replication configuration** (source endpoint, target endpoint, replication type, table mappings, settings, compute config) instead of instance + task.
- **DCU (DMS Capacity Unit) = 2 GB RAM.** You set **MinCapacityUnits** (default 1) and **MaxCapacityUnits** (for example 16). Capacity range up to 384 DCUs (verify).
- **Scaling**: scales **up** after exceeding an upper utilization threshold for some time; scales **down** after low utilization for longer. **Cannot scale down during a full load.** Storage starts at **100 GB** and auto-scales when 90% used.
- Set **Max** high (you pay only for what is used) and **Min** high enough to handle sudden spikes (provisioning takes time). If memory runs out the replication may fail; raise Min and resume.
- Replication states: Initializing → Preparing metadata → Testing connection → Fetching metadata → Calculating capacity → Provisioning capacity → Replication starting → **Running** (full load, initial CDC, ongoing CDC). Stopped/failed replications **resume** with `resume-processing`.
- **Deprovisioned if not resumed within 48 hours** (stopped/failed) → table metadata and statistics are lost.
- **Multi-AZ** option available (recommended for CDC).
- Engine version managed by AWS (3.5.4 at doc time).
- Supported **sources**: MongoDB, DocumentDB, SQL Server, PostgreSQL-compatible, MySQL-compatible, MariaDB, Oracle, S3, Db2.
- Supported **targets**: SQL Server, PostgreSQL, MySQL-compatible, Oracle, S3, Redshift, DynamoDB, Kinesis Data Streams, MSK, OpenSearch, DocumentDB, Neptune.
- **Limitations**: no views; no custom CDC start point; no SSL for Db2 endpoints; must reach S3/Kinesis/Secrets Manager/DynamoDB/Redshift/OpenSearch through **VPC endpoints**; modify only in CREATED/STOPPED/FAILED states; delete only when STOPPED/FAILED; no public IP for management.
- Enhanced throughput available for **full load Oracle → Redshift/S3** under specific settings (no parallel-load rules, no transformation/filter rules, MaxFileSize/WriteBufferSize 64 MB, LOB mode inline, `MaxFullLoadSubTasks` 49).
- Metrics: `CapacityUtilization`, plus the CDC and full-load throughput/latency metrics.
- Logs go to a dedicated CloudWatch group `dms-serverless-replication-<id>`; enable `Logging.EnableLogging` for task-level logs.
- Needs a **service-linked role**.
- Use Serverless when workload is **unpredictable, intermittent**, or you don't want to manage instances. Use standard (provisioned) when you want fixed cost/control, need unsupported endpoints, or need features like custom CDC start points and views.

## G. Homogeneous data migrations (verified)
- For **same-engine** moves from self-managed / on-premises / EC2 / RDS sources to **RDS or Aurora**, using **native database tools** under the hood (for example **pg_dump/pg_restore**, MySQL dump/binlog replication, MongoDB tools).
- **Serverless**: DMS creates the environment automatically when you start the migration.
- Moves data **and secondary objects** (partitions, functions, stored procedures, and so on).
- Modes: **full load**, **ongoing replication (CDC)**, **full load + ongoing replication**.
- Supported families: PostgreSQL, MySQL (incl. MariaDB-compatible), MongoDB / DocumentDB (targets Aurora PostgreSQL/MySQL, RDS, DocumentDB).
- Built from an **instance profile** (network/security), **data providers** (source and target connection info), and a **migration project**.
- **Limitations**: selection rules depend on engine and migration type (MySQL sources only for full load); **no built-in data validation**; PostgreSQL views migrate as **tables**; schema-level changes captured during CDC only for MySQL; **cannot migrate from higher to lower version**; no VPC secondary CIDR; port 8081 not allowed; encrypted MySQL tables arrive unencrypted on RDS MySQL.
- Target table preparation mode: supported for PostgreSQL, MongoDB, DocumentDB migrations.
- Choose homogeneous data migration when **same engine** and you want native-tool speed with less setup; choose standard DMS for **heterogeneous** moves, non-database targets (S3, Kinesis, Redshift), validation, or transformations.

## H. DMS Fleet Advisor and discovery (awareness)
- **DMS Fleet Advisor** collects data from on-premises **database and analytics servers**, builds an **inventory** of servers, databases and schemas, and recommends target engines. It works with the **Application Discovery Service Agentless Collector** (database and analytics data-collection module). (verify: Fleet Advisor availability and retirement notices; check current docs)

## I. DMS compared with neighbors
| Need | Pick |
|---|---|
| Migrate a database with minimal downtime | **DMS** (full load + CDC) |
| Change engine and convert schema/code | **DMS Schema Conversion** (or SCT) + DMS |
| Same engine, native tools, serverless | **DMS homogeneous data migrations** |
| Continuous replication into Redshift from Aurora/RDS/DynamoDB | **Zero-ETL** (no DMS) |
| Replicate files/objects | **DataSync** |
| Move a whole server | **Application Migration Service (MGN)** |
| Ongoing application-level streaming | **Kinesis/MSK** (DMS can feed them) |
| Aurora/RDS read-only copy in AWS | **Read replica / backups** (native) |

## Scenarios (if → then, because)
- **If** you must move an Oracle database to **Amazon Aurora PostgreSQL** with very little downtime, **then** first use **DMS Schema Conversion** to convert the schema and code objects (tables, views, procedures) to PostgreSQL and apply them to the target. Next, run an **AWS Database Migration Service (DMS)** task of type **full load + change data capture (CDC)**: it copies the existing rows once, then keeps copying new changes. **This works because** CDC reads the Oracle transaction log and keeps the target **in sync** until you switch the apps, so the cutover takes only minutes. DMS alone does not convert code objects; it only creates tables and primary keys.
- **If** the migration is **heterogeneous** (different engines, for example Oracle → PostgreSQL) and heavy on CPU, **then** pick a **C-class** (compute-optimized) **replication instance**, the DMS server that reads, converts and loads the data. **This works because** converting data between engines uses a lot of **CPU**, and C-class instances give the most CPU.
- **If** **change data capture (CDC)** runs for weeks on a busy source, **then** use an **R-class** (memory-optimized) replication instance, turn on **Multi-AZ** (Multi-Availability Zone), and give it enough storage. **This works because** busy, long-running CDC needs **memory**, and cached changes and logs build up on the instance's **disk** (default **100 GB** on C/R classes). Multi-AZ keeps a synchronous standby in another AZ with **automatic failover**, so replication is not interrupted. Multi-AZ costs more and can slow applying changes slightly.
- **If** a **full load** task fails because the Multi-AZ replication instance **failed over** to its standby, **then** restart the task for the tables that were not completed. **This works because** the notes say a full load task that fails over **fails** and must be restarted for the unfinished tables; failover protects **ongoing replication**, not a running full load.
- **If** the migration workload is **unpredictable** or comes and goes, **then** use **DMS Serverless**, which **provisions, scales and deprovisions** capacity for you, with a high **MaxCapacityUnits** and a sensible **MinCapacityUnits**. One **DMS Capacity Unit (DCU)** = **2 GB RAM**. **This works because** you pay only for capacity actually used, so a high Max costs nothing extra, while Min must cover sudden spikes because new capacity takes time. Serverless cannot scale down during a full load.
- **If** both source and target are **PostgreSQL** and you want a simple lift, **then** use **DMS homogeneous data migrations**. **This works because** it uses native tools (like **pg_dump/pg_restore**) under the hood, sets up its serverless environment for you, and also moves secondary objects such as functions and procedures. It has no built-in data validation.
- **If** a stopped or failed **DMS Serverless** replication is not resumed within **48 hours**, **then** AWS **deprovisions** its resources and the table **metadata and statistics are lost**. **This works because** Serverless frees idle capacity; resume within 48 hours with `resume-processing` to keep the state.
- **If** you need exact, guaranteed low-latency replication (for example sub-second), **then** do not use **DMS change data capture (CDC)**; use native database replication or streaming instead. **This works because** DMS CDC is **not real-time and has no SLA**: latency depends on source load, transaction size, network, instance size and target speed, and spikes of minutes during batch jobs are normal.
- **If** the source database is being **upgraded**, **then** **stop the DMS tasks first** and resume them after the upgrade. **This works because** CDC resumes from its checkpoint, as long as the source logs are still available.

## Verified from AWS docs on 2026-10-09
Read: DMS Welcome page, replication instance page (index), Serverless pages (overview, components, limitations), tasks page, best practices page, homogeneous data migrations page, monitoring page, pricing summary, Schema Conversion page. Not confirmed (verify): DCU range (1–384), engine-specific CDC prerequisites (general knowledge), Fleet Advisor status, exact instance storage per class, Route 53 Resolver design details, replication-engine version numbers.

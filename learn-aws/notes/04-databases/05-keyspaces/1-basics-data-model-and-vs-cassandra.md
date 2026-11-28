# Keyspaces – 1. What it is, data model, CQL support, consistency, and Keyspaces vs Cassandra

Short notes. Each point is a fact you can be asked about.

## A. What it is (verified)
- **Amazon Keyspaces (for Apache Cassandra)** is a **serverless, managed, Cassandra-compatible** wide-column database.
- You keep using **CQL** (Cassandra Query Language) and **Cassandra drivers**. No servers, no patching, no cluster to size.
- It scales tables up and down automatically with traffic. Storage is **virtually unlimited**.
- Data is stored **3 times across 3 Availability Zones** in one Region. You don't manage replication inside the Region.
- Two capacity modes: **on-demand (default)** and **provisioned**. You pay per request or per provisioned unit.
- Encryption at rest is on by default. All client connections need TLS.
- Compatible with **CQL 3.11 API** (backward compatible with 2.x).
- Availability SLA up to **99.999%** (with multi-Region replication, per the migration page).
- Endpoint: `cassandra.<region>.amazonaws.com`, port **9142** (TLS). SDK/CLI use 443 (HTTPS).
- It is a **table store, not a graph, document or relational database**. Think "huge key-based tables with known queries".

## B. When to use / not use
- Use it when you **already run Apache Cassandra** and want to stop managing nodes, repair, compaction and upgrades.
- Use it for **massive scale with single-digit millisecond** reads/writes by known keys: IoT/time series, user activity, device state, messaging history, ad tech, order tracking.
- Use it when load is spiky/unknown → **on-demand** mode.
- Use it when you want **multi-Region active-active** without running cross-datacenter Cassandra.
- Do not use it for: joins, ad-hoc queries, full-text search, analytics, strong multi-row ACID transactions, or relational data → RDS/Aurora, Redshift, OpenSearch.
- Do not choose it if your app needs a Cassandra feature that is **not supported** (see section F).
- If you want a serverless key-value/document store and have no Cassandra code → **DynamoDB** is usually the simpler AWS-native choice.
- If you need Redis-like in-memory speed → MemoryDB/ElastiCache.

## C. How it is built (verified)
- **Keyspace** = a namespace for tables (like a schema). **Table** = rows with columns.
- In Cassandra you run a **cluster of nodes** and must add/remove nodes, tune compaction, run repairs. In Keyspaces **all of that is hidden**.
- Replication factor is fixed: 3 AZ copies. You do not set replication factor like in Cassandra (single-Region keyspaces use a managed strategy; multi-Region keyspaces list their Regions – verify exact CQL syntax).
- Data is stored in **partitions**. The **partition key** decides which partition holds a row.
- **Logical partitions** can span several storage partitions and are virtually unbounded in size.
- **Storage partition limits**: about **1,000 WCU/WRU per second** and **3,000 RCU/RRU per second** per storage partition. A hot key can still throttle.
- Schema is enforced on write (**schema validation**). Columns have types.
- Table design is **query first**: no JOINs, denormalize, one table per access pattern.
- System tables live in `system_schema_mcs` (table properties, capacity mode).
- Keyspaces and tables are created in minutes. DDL is **asynchronous** (a table is `CREATING` until ready; check status before using).

## D. Data model: primary key
- **Primary key** = **partition key** (required) + **clustering columns** (optional).
- **Partition key**: can be one column or **compound** (several columns). It decides distribution. Pick a **high-cardinality** key so traffic spreads evenly.
- **Clustering columns**: decide the **sort order inside a partition** and allow range queries on them.
- Order of clustering columns matters: sort is left to right.
- Queries must give the **full partition key** with equality for efficient reads. Range queries work on clustering columns.
- A poor partition key (few values, one hot value, or "month" for all data) causes **hot partitions** and throttling (`StoragePartitionThroughputCapacityExceeded`).
- To avoid hot partitions: add a bucket/salt (date + id), use compound keys, spread writes.
- **Static columns** are supported: one value per partition shared by all rows in it (limit **1 MB** of static data per logical partition).
- **Counter** type is supported (verify counter use in multi-Region tables).
- No secondary indexes (`CREATE INDEX` not supported) → make another table with a different key for a different query.
- `ALLOW FILTERING` full scans work but are slow and costly (you pay for rows read). Avoid them.
- Key size limits: partition key up to **2,048 bytes**, clustering key up to **850 bytes** combined (plus small metadata).
- Row size max **1 MB** (excluding static column data).

## E. Supported operations (verified)
- Supported: `CREATE/ALTER/DROP KEYSPACE`, `CREATE/ALTER/DROP TABLE`, `USE`, `SELECT`, `INSERT`, `UPDATE`, `DELETE`, **LOGGED and UNLOGGED BATCH**, `CREATE TYPE`, `DROP TYPE`.
- **JSON** support in `SELECT` and `INSERT`. **Static columns**. **TTL**. **Lightweight transactions** (`IF NOT EXISTS`, `IF` conditions). **Counters**.
- Functions supported: blob conversion, `CAST`, date/time, `TIMEUUID`, `TOKEN`, `UUID`.
- **Not supported**:
  - `CREATE INDEX` / `DROP INDEX` (secondary indexes)
  - `CREATE MATERIALIZED VIEW` and its alter/drop
  - `CREATE TRIGGER`
  - `CREATE FUNCTION` (user-defined functions) and `CREATE AGGREGATE`
  - **Aggregate functions** (like `COUNT` over scans, `SUM`; verify exact behavior of `COUNT(*)`)
  - `ALTER TYPE`
  - **`TRUNCATE`** → delete the table or use TTL; recreate if needed
- **Not applicable** because it is managed: durable-writes toggle, read repair, GC grace seconds, bloom filter, compaction, compression, caching settings, security settings (replaced by IAM).
- Batch limits: logged batch up to **100 statements** and **4 MB** (50 statements with static columns). Unlogged batch up to **30 statements**.
- `IN` clause: up to **100 subqueries** per SELECT.
- Insert/update column limit: **225 columns** (166 when TTL is used).
- Nested frozen collections: up to **8** levels.

## F. Data types (verified list)
- Strings: `ascii`, `text`, `varchar`. Numbers: `tinyint`, `smallint`, `int`, `bigint`, `varint`, `float`, `double`, `decimal`, `counter`.
- Time: `date`, `time`, `timestamp`, `timeuuid`. IDs: `uuid`. Others: `boolean`, `blob`, `inet`.
- Collections: `list`, `map`, `set`, `tuple`, `frozen`. **User-defined types (UDTs)** are supported (limits below).
- UDT limits: 256 per Region, 50 per table, nesting 8, name 48 chars, schema 25 KB.

## G. Consistency levels (verified)
- **Writes**: always replicated to 3 AZs and acknowledged at **LOCAL_QUORUM** (durable before ack). Cost: 1 WRU/WCU per 1 KB.
- **Reads supported**: `ONE`, `LOCAL_ONE`, `LOCAL_QUORUM`.
- `LOCAL_QUORUM` read = latest data (strongly consistent). Cost: 1 RRU/RCU per 4 KB.
- `ONE` / `LOCAL_ONE` = may be slightly stale (eventually consistent). Cost: **0.5** RRU/RCU per 4 KB. Faster and cheaper.
- **Not supported**: `EACH_QUORUM`, `QUORUM`, `ALL`, `TWO`, `THREE`, `ANY`, `SERIAL`, `LOCAL_SERIAL` → using them causes errors.
- Set the level in the driver config (for example `basic.request.consistency = LOCAL_QUORUM`) or in `cqlsh` (`CONSISTENCY LOCAL_QUORUM;`).
- Exam shortcut: "need most recent data" → LOCAL_QUORUM. "Cheapest reads, can tolerate stale" → LOCAL_ONE.

## H. Keyspaces vs Apache Cassandra
| Topic | Apache Cassandra | Amazon Keyspaces |
|---|---|---|
| Servers | You run nodes (EC2/on-prem) | **Serverless**, no nodes |
| Scaling | Add/remove nodes, rebalance | **Automatic** (on-demand) or auto scaling (provisioned) |
| Ops work | Patching, repair, compaction, upgrades, backups | **None** |
| Replication | You set replication factor and datacenters | Fixed **3 copies in 3 AZs**; multi-Region via a setting |
| Consistency | ANY, ONE, TWO, THREE, QUORUM, LOCAL_*, EACH_QUORUM, ALL, SERIAL | Writes: LOCAL_QUORUM; reads: ONE, LOCAL_ONE, LOCAL_QUORUM only |
| Secondary indexes | Yes | **No** |
| Materialized views | Yes | **No** |
| UDFs, aggregates, triggers | Yes | **No** |
| TRUNCATE | Yes | **No** |
| Tuning | Compaction, bloom filters, caches, GC grace | **Not applicable** |
| Auth | Cassandra roles/passwords | **IAM** (SigV4 plugin) or service-specific credentials |
| Network | Your own network | TLS only, port 9142, VPC endpoints |
| Backup | Snapshots/tools | **PITR** (35 days) |
| Billing | Pay for servers | Pay per request/provisioned units + storage |
| Multi-datacenter | Cross-DC replication you manage | **Multi-Region replication** managed, active-active, last writer wins |
| CQL version | Any | **3.11 compatible** |
| Capacity planning | Required | On-demand: none |
| Data access | Driver, cqlsh | Same drivers; change endpoint/port/TLS/auth |
- **Similar**: same CQL, same data model (keyspace, partition key, clustering columns), same drivers, wide-column NoSQL, query-first design, tunable (limited) consistency, TTL, static columns, LWT, batches, UDTs.
- **Different mindset**: no node tuning, no repair/tombstone issues to manage, but some Cassandra features are missing.
- To move an app: change contact point to the Keyspaces endpoint, port to 9142, add TLS (Amazon Root CAs), change auth to SigV4/service credentials, check unsupported features.
- Local data center name in drivers is the **Region name**; set the driver's local datacenter to the Region (verify wording).

## I. Keyspaces vs DynamoDB (quick)
| Topic | Keyspaces | DynamoDB |
|---|---|---|
| API | CQL / Cassandra drivers | DynamoDB API / PartiQL |
| Best for | Cassandra apps | New serverless apps |
| Secondary indexes | None | GSI/LSI |
| Transactions | LWT, logged batch (limited) | ACID transactions |
| Streams | CDC (24 h) | Streams (24 h) |
| Global | Multi-Region active-active | Global tables |
| Auth | IAM / service credentials | IAM |
- If the question says "existing Cassandra code, wants managed" → Keyspaces. "New, no Cassandra" → DynamoDB.

## J. Keyspaces vs other stores (decision lines)
- Wide-column, Cassandra drivers → Keyspaces.
- Key-value / document, AWS API, secondary indexes → DynamoDB.
- Documents with MongoDB API → DocumentDB.
- Graph relationships → Neptune.
- In-memory with durability → MemoryDB.
- Relational → RDS/Aurora.
- Search → OpenSearch.

## Scenarios (if → then, because)
- **If** a company runs **Apache Cassandra** on **Amazon Elastic Compute Cloud (EC2)** servers and wants less operations work, **then** move to **Amazon Keyspaces (for Apache Cassandra)**, a serverless, managed, Cassandra-compatible database. The app keeps using **Cassandra Query Language (CQL)** and the same **Cassandra drivers**; you only change the endpoint, port **9142**, Transport Layer Security (TLS) and authentication. **This works because** Keyspaces hides the nodes, patching, repair, compaction and upgrades, and keeps **3 copies across 3 Availability Zones (AZs)** for you. Check first that the app uses no unsupported Cassandra features.
- **If** the app uses **materialized views** or **user-defined functions (UDFs)**, **then** redesign it before moving: create **extra tables** (one per query) and move the function logic into the **application code**. **This works because** Keyspaces does **not support** materialized views, UDFs, user-defined aggregates or triggers, so these statements will fail.
- **If** the app uses **QUORUM** or **ALL** consistency, **then** change it to **LOCAL_QUORUM** in the driver config or in `cqlsh`. **This works because** Keyspaces only accepts **ONE**, **LOCAL_ONE** and **LOCAL_QUORUM** for reads; other levels (QUORUM, ALL, EACH_QUORUM, SERIAL and others) cause **errors**. Writes are always **LOCAL_QUORUM** anyway.
- **If** a query often filters on a column that is **not in the key**, **then** create **another table** with that column in its **primary key**, and write the data to both tables. **This works because** Keyspaces has **no secondary indexes** (`CREATE INDEX` is not supported). `ALLOW FILTERING` works but scans many rows, so it is slow and you pay for every row read.
- **If** one **partition key** value gets almost all the traffic (a **hot partition**), **then** change the key design: add a **bucket or salt** (for example date + id) or use a **compound partition key**, so writes spread across many partitions. **This works because** each storage partition handles only about **1,000 write units** and **3,000 read units per second**. A hot key throttles even when total traffic is low, and CloudWatch shows `StoragePartitionThroughputCapacityExceeded`. Pick a **high-cardinality** key from the start.
- **If** you must read the **latest value** right after a write, **then** read with **LOCAL_QUORUM** consistency. **This works because** a LOCAL_QUORUM read is **strongly consistent** (returns the most recent data), while **ONE** or **LOCAL_ONE** reads may be slightly **stale**. The catch: LOCAL_QUORUM costs **1 read unit per 4 KB**, twice the price of LOCAL_ONE.
- **If** reads can be slightly **stale** and you want **lower cost**, **then** read with **LOCAL_ONE** consistency. **This works because** LOCAL_ONE reads are eventually consistent and cost only **0.5 read unit per 4 KB**, half of a LOCAL_QUORUM read, and they are faster.
- **If** you need to **delete all rows** of a table quickly, **then** **drop and recreate** the table, or set a **Time to Live (TTL)** so rows expire on their own. **This works because** Keyspaces does **not support** `TRUNCATE`.
- **If** an exam question says "**serverless Cassandra**", **then** the answer is **Amazon Keyspaces (for Apache Cassandra)**, because it is the serverless, Cassandra-compatible database on AWS.
- **If** an exam question says "**Apache Cassandra on EC2 is too much to maintain**", **then** the answer is **Amazon Keyspaces**, because it removes node management, patching, repair and compaction while keeping CQL and the drivers.
- **If** an app must often run `COUNT(*)` or **sums** over huge tables, **then** do not run them in Keyspaces. Send the data to an analytics store such as **Amazon Redshift** (for example with **change data capture (CDC) streams**), or keep running totals yourself in a **counter** column. **This works because** Keyspaces does **not support aggregate functions** (exact `COUNT(*)` behavior: verify) and is built for key-based queries, not analytics.

## Verified from AWS docs on 2026-10-02
Read: what-is page, how-it-works page, supported APIs/functions/data types page, consistency page, quotas page, endpoints page, on-demand and provisioned pages. Not confirmed (verify): exact CQL syntax for replication strategy in single/multi-Region keyspaces, COUNT behavior, counter support in multi-Region tables, wording of the local-datacenter driver setting, 99.999% SLA conditions.

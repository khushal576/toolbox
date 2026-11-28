# MemoryDB – 1. What it is, architecture, durability, data tiering, vector search, vs Redis and ElastiCache

Short notes. Each point is a fact you can be asked about.

## A. What it is (verified)
- Amazon MemoryDB is a **durable, in-memory database**. It is compatible with **Valkey and Redis OSS** (same data structures, APIs and commands).
- All data lives in memory → **microsecond reads, single-digit millisecond writes**.
- Data is also stored **durably in a Multi-AZ transaction log** → no data loss on failover or node restart.
- Because it is durable, you can use it as a **primary database**. You do not need a separate cache + database pair.
- Up to **160 million transactions per second per cluster** (doc number).
- Fully managed: patching, failure detection, replacement, snapshots, scaling.
- It is **VPC-only**. There is no public endpoint. Reach it from inside the VPC, VPN, Direct Connect or peering.
- Default port is **6379**.
- MemoryDB is a **database service**, not a cache service. That one sentence answers most "MemoryDB vs ElastiCache" questions.

## B. When to use / not use
- Use MemoryDB when you need **Redis-style speed AND durability**: session stores, leaderboards, shopping carts, gaming state, real-time inventory, rate limits, feature stores.
- Use it when the in-memory data **is the source of truth** and loss is not acceptable.
- Use it for **vector search** with ultra-low latency (RAG, semantic cache, recommendations, anomaly detection).
- Use it for microservices that need a fast data store with Redis APIs and want to drop the "cache + database" pair.
- Do not use it as a cache in front of another database. **ElastiCache** is cheaper for that (no durable log cost).
- Do not use it for large cold datasets. Memory is expensive. Use DynamoDB, Aurora or S3 (or data tiering for a partly cold set).
- Do not use it for relational queries, joins, or heavy analytics.
- Do not use it for full ad-hoc search over huge data. Use OpenSearch.

## C. How the durability works (verified)
- Every write on the primary is first written to the **Multi-AZ transaction log**. Only after it is durably stored does the client get the acknowledgment.
- That is why writes take **single-digit milliseconds** (not microseconds). The durable log write is the price of durability.
- Replicas are updated **asynchronously** from the log.
- A failed or new node **recovers from the transaction log** (plus the latest snapshot). No data is lost.
- Open-source Redis OSS replicates **asynchronously** and can lose recent writes on failover. MemoryDB cannot lose acknowledged writes.
- Snapshots are separate from the log. The log gives durability; snapshots give point-in-time copies and faster recovery.

## D. Consistency (verified)
- **Primary node**: strongly consistent. A read on the primary always returns the effect of all earlier successful writes (read-after-write).
- Strong consistency is **kept across failover**.
- **Replica nodes**: eventually consistent. You read from a replica with the `READONLY` command. It may lag. Lag metrics go to CloudWatch.
- Reads from one replica are **sequentially consistent**. Writes are applied in the same order as on the primary.
- If a question needs "read your own write" → read from the primary.
- If a question accepts stale reads for more read throughput → read from replicas.

## E. Architecture: cluster, shard, node
- **Cluster** → one or more **shards** → each shard has **1 primary + 0 to 5 replicas** (nodes).
- Always use **at least 1 replica** for high availability (the doc recommends this).
- Data is split across shards by **hash slot** (16,384 slots, Redis-cluster style). Each shard owns a slot range.
- More **shards** = more write throughput and more memory. More **replicas** = more read throughput and more availability.
- Up to **500 nodes per cluster**. More than **100 TB** per cluster with 1 replica per shard.
- When you add shards, new shards get the **same number of nodes** as the smallest existing shard.
- Each node has its own DNS name and port.
- **Cluster endpoint** (`clustercfg...memorydb...amazonaws.com:6379`) is what cluster-aware clients use. They discover shards from it.
- MemoryDB behaves as a Redis **cluster-mode** deployment (cluster-aware client needed). (verify: single-shard cluster-mode-disabled style is not offered)
- Multi-AZ is **automatic** when each shard has more than one node. You cannot turn it off.
- Node placement: primary and replicas are spread across AZs in your **subnet group** (needs subnets in at least 2 AZs, 3 recommended).

## F. Components you configure
- **Subnet group**: which subnets (and AZs) the nodes use.
- **Security group**: controls network access to port 6379 (acts as the firewall).
- **Parameter group**: engine settings (memory policy, etc.).
- **ACL** + **users**: authentication and authorization (see file 2).
- **Node type**: memory/CPU size. **Number of shards** and **replicas per shard**.
- **Snapshot** settings: retention and window.
- **Maintenance window**: when patches apply.
- **Engine and version**: Valkey or Redis OSS. Versions 6.2 and later are shown in the node type table (min engine 6.2). (verify the full current version list)

## G. Node types (verified)
- **Memory optimized**: `db.r7g` (large to 16xlarge) and `db.r6g` (large to 16xlarge). Graviton processors.
- **Memory optimized with data tiering**: `db.r6gd` (xlarge to 8xlarge). Has local SSD.
- **General purpose (burstable)**: `db.t4g.small`, `db.t4g.medium`. For dev/test.
- All node types run **inside a VPC**.
- Larger nodes (2xlarge and above for r7g/r6g) get **Enhanced I/O Multiplexing** for higher throughput on Valkey 7.2 / Redis OSS 7.0.4+.
- Node bandwidth grows with size. Small nodes burst; large ones (8xlarge+) have no burst.
- Use **t4g** only for test. Do not use it for production.

## H. Data tiering (verified)
- Uses **r6gd** nodes. Data is tiered between **memory (DRAM)** and **local SSD**.
- Best when you regularly access only **about 20% or less** of the dataset, and you can tolerate more latency for the rest.
- MemoryDB tracks last-access time. When memory is full, **LRU** moves cold **values** to SSD. When touched again, they move back to memory.
- **Keys always stay in memory**. So keep keys smaller than values.
- Typical extra latency for SSD reads: about **450 microseconds** (500-byte values example).
- DRAM reserved for non-data use: **19%** per node.
- Max with data tiering: about **500 TB** in a 500-node cluster with no replica (250 TB with 1 replica) using db.r6gd.8xlarge.
- Tiered data is still in the multi-AZ log. SSD data is **always encrypted**.
- Can save **over 60%** cost for suitable workloads (pricing page claim).
- No client changes needed. All commands and data structures work.
- **You cannot scale between a data tiering cluster and a non-tiering cluster** (r6gd ↔ r6g/r7g).
- Metrics: `BytesReadFromDisk`, `BytesWrittenToDisk`, `NumItemsReadFromDisk`, `NumItemsWrittenToDisk`, `BytesUsedForMemoryDB` with `Tier` dimension.

## I. Vector search (verified)
- Adds vector similarity search on top of MemoryDB data (HASH or JSON). Uses Valkey/Redis search style commands (`FT.CREATE`, `FT.SEARCH`, `FT.AGGREGATE`).
- Algorithms: **FLAT** (exact) and **HNSW** (approximate, faster for large sets). Distance metrics: L2, inner product, cosine. (verify the exact list in the docs)
- Limits: up to **32,768 dimensions**, **10 indexes**, **50 fields per index**, search timeout max **10,000 ms**.
- HNSW parameters limits: **M up to 512**, **EF_CONSTRUCTION up to 4096**, **EF_RUNTIME up to 4096**. Default **M = 16**.
- Higher **M** = better recall for high dimensions, but **more memory**.
- Supported on **r6g, r7g, t4g** nodes.
- **Limited to a single shard.** No horizontal scaling. You can scale **vertically** (bigger node) and with **replicas**.
- **You cannot turn on search for an existing cluster.** You can restore a snapshot of a non-search cluster into a search-enabled cluster.
- Indexes are rebuilt (backfill) after restart. The node may serve before backfill is done → search can be rejected for a while. Check backfill is complete on primary and all replicas.
- `FT.CREATE` / `FT.DROPINDEX` / alias commands **cannot run inside MULTI/EXEC or Lua/Function scripts**.
- Memory use = vectors × dimensions + index (M). Console has a **vector calculator**. Example: 10M vectors × 1,536 dims ≈ **105 GB** → db.r7g.4xlarge.
- Vector indexes in an RDB file can only be read by another MemoryDB vector-enabled cluster (limits export to other Redis).
- ACL: search commands are in the **@search** category (also in @read/@write/@fast/@slow).
- Exam link: MemoryDB is a valid vector store with **key/value access + vector search** (skill 2.1.3). It is the **fastest** option, but memory-bound and single-shard.
- Compare with: Aurora PostgreSQL pgvector (relational + HNSW/IVFFlat), OpenSearch (large-scale search + vectors), DocumentDB (vector search on documents).

## J. MemoryDB vs open-source Redis / Valkey (what changes)
| Topic | Self-managed Redis / Valkey | MemoryDB |
|---|---|---|
| Durability | Optional (RDB/AOF), replication is async → can lose writes on failover | **Multi-AZ transaction log**; acknowledged writes are never lost |
| Primary database use | Risky; usually a cache | **Designed as primary database** |
| Write latency | Microseconds | **Single-digit milliseconds** (log write) |
| Read latency | Microseconds | Microseconds |
| Failover | Replica may be behind; data loss possible | Replica promoted **only if consistent**; no loss; typically a few seconds |
| Operations | You patch, back up, fail over, scale | **Managed** |
| Security | You build it | VPC, TLS 1.2+, KMS at rest, ACLs, IAM auth |
| Scaling | Manual/own tooling | **Online** resharding and vertical scaling |
| Multi-Region | Do it yourself | **MemoryDB Multi-Region** active-active |
| Cost | Just servers | Nodes + **per-GB data written** |
| Admin commands | All | Some are **restricted** (managed service) |
- API is the same → apps usually need **almost no change**. That is the main selling point.
- Not everything is allowed: some admin commands are restricted, and ACL commands that write are not supported (users are managed through the MemoryDB API).
- MemoryDB engine versions follow Valkey/Redis OSS. New versions arrive after open-source releases (verify timing).

## K. MemoryDB vs ElastiCache (verified wording, plus notes)
| Topic | MemoryDB | ElastiCache (Valkey/Redis OSS) |
|---|---|---|
| Purpose | **Primary durable database** | **Cache** in front of a database |
| Durability | Multi-AZ transaction log, no loss | Not a durable store (snapshots/replication only, async) |
| Write latency | Single-digit milliseconds | Microseconds |
| Read latency | Microseconds | Microseconds |
| Source of truth | Yes | No (another DB holds the truth) |
| Typical cost | Higher (durability, data-written charge) | Lower |
| Best for | "Redis API as the database" | "Speed up reads of an existing DB" |
- If the question says **cache in front of RDS/DynamoDB**, choose **ElastiCache**.
- If it says **durable, Redis-compatible, primary database, no data loss**, choose **MemoryDB**.
- If it says **microsecond writes and loss is acceptable**, choose **ElastiCache**.
- (verify) ElastiCache has a serverless option; MemoryDB is node-based. Check current docs.
- Both support Valkey and Redis OSS APIs, TLS and encryption at rest, and vector search (verify ElastiCache vector support).
- Other nearby services: DAX (cache only for DynamoDB), DynamoDB (serverless key-value with durability, slower than in-memory).
- MemoryDB vs DynamoDB: MemoryDB is faster (microseconds) and has rich structures (sorted sets, lists, streams), but is memory-bound and costs more per GB. DynamoDB is serverless, virtually unlimited, cheaper for large data.

## L. Data structures and features you can name
- Strings, hashes, lists, sets, sorted sets, bitmaps, HyperLogLog, geospatial, **streams**, pub/sub, JSON (via commands), Lua scripts/functions, transactions (MULTI/EXEC).
- Sorted sets → leaderboards. Streams → lightweight event log/queue. Pub/sub → real-time messaging. Geospatial → nearby search.
- Key tracking supports client-side caching (metric `KeysTracked`).

## Scenarios (if → then, because)
- **If** you need the speed of Redis but must never lose data, **then** use **Amazon MemoryDB**, a durable in-memory database compatible with Valkey and Redis OSS. Reads take **microseconds** and writes take **single-digit milliseconds**. **This works because** every write is first stored in a **Multi-Availability Zone (Multi-AZ) transaction log** before the client gets the acknowledgment, so acknowledged writes survive failover or node restart. The catch: writes are slower than plain Redis because of that log write.
- **If** you only need to speed up reads of an **Amazon Relational Database Service (RDS)** database, **then** use **Amazon ElastiCache** as a cache in front of it. **This works because** RDS stays the source of truth, so the cache needs no durability, and ElastiCache is cheaper than MemoryDB (no durable log and no per-GB data-written charge).
- **If** a game needs leaderboards and the scores must survive failures, **then** use **MemoryDB sorted sets**, a Redis data structure that keeps members ordered by score. **This works because** MemoryDB gives in-memory speed for ranking reads and stores every write in the **Multi-AZ transaction log**, so scores are not lost when a node fails.
- **If** a dataset is large but you regularly use only about **20%** or less of it, **then** use **MemoryDB data tiering** on **r6gd** nodes, which have local SSD. **This works because** when memory is full, MemoryDB moves the least recently used (**LRU**) **values** to SSD and back when touched; keys always stay in memory. It can cut cost by **over 60%**. The catch: SSD reads add about **450 microseconds**, and you cannot scale between r6gd and r6g/r7g.
- **If** you need semantic (meaning-based) search with the lowest latency on a moderate dataset, **then** use **MemoryDB vector search**, which adds vector similarity search with `FT.CREATE` and `FT.SEARCH`. **This works because** vectors and indexes live in memory, making it the **fastest** vector store option. The catch: it is memory-bound and **limited to a single shard**, and it must be enabled when the cluster is created.
- **If** your vectors need more memory than one node has and must spread across many shards, **then** pick another store, such as **Amazon OpenSearch Service** (large-scale search plus vectors) or **Amazon Aurora PostgreSQL with pgvector**. **This works because** MemoryDB vector search is **single-shard**: you can only scale it **vertically** (bigger node) or add **replicas**, not add shards.
- **If** a client must read its own writes right away, **then** read from the **primary node**. **This works because** the primary is **strongly consistent** (read-after-write, kept across failover), while **replica nodes** are updated **asynchronously** and are only **eventually consistent**, so they may lag.
- **If** a shard's primary node fails, **then** MemoryDB promotes a replica to primary, and writes resume in **typically a few seconds**. **This works because** every acknowledged write is in the **Multi-AZ transaction log**, and MemoryDB promotes a replica **only after making sure it is consistent**, so no data is lost.
- **If** a shard has **no replica** and its primary fails, **then** writes stop until MemoryDB builds a new primary and it syncs from the transaction log. **This works because** there is no replica to promote. Data is still safe in the log, but downtime is longer, so always keep **at least 1 replica**.
- **If** an app already uses Redis commands, **then** move it to **MemoryDB** with almost no code change. **This works because** MemoryDB supports the same Valkey/Redis OSS data structures, APIs and commands. The catch: some admin commands are **restricted**, and you need a cluster-aware client.
- **If** you want vector search on an existing cluster, **then** take a **snapshot** and restore it into a **new search-enabled cluster**. **This works because** search **cannot be turned on for an existing cluster**; it can only be set when a cluster is created, and a snapshot of a non-search cluster can be restored into a search-enabled one.

## Verified from AWS docs on 2026-10-02
Read: MemoryDB overview, features, consistency, nodes/shards, supported node types, data tiering, vector search limits, ACL page, comparison page, pricing summary. Not confirmed (verify): full current Valkey/Redis OSS version list, vector distance metrics list, ElastiCache serverless/vector claims, whether single-shard cluster-mode-disabled is offered, full restricted command list, release timing of new engine versions.

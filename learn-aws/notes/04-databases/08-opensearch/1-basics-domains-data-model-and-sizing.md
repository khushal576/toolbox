# OpenSearch – 1. What it is, concepts, domains, node types, sizing, versions

Short notes. Each point is a fact you can be asked about.

## A. What it is (verified)
- **Amazon OpenSearch Service** is a managed **search and analytics engine** (OpenSearch is the open-source fork of Elasticsearch 7.10).
- It supports **OpenSearch** (1.x, 2.x, 3.x) and **legacy Elasticsearch OSS** up to 7.10.
- A **domain** = an OpenSearch **cluster** with the settings, instance types, instance counts and storage you choose. Each EC2 instance = one node.
- Three deployment styles:
  - **Provisioned domains** (you pick instances).
  - **OpenSearch Serverless** (collections, no nodes; see file 2).
  - **OpenSearch Ingestion** (managed pipelines that feed a domain/collection; see file 2).
- AWS provisions, detects and replaces failed nodes, patches, backs up (automated snapshots) and scales with one API call.
- Main use cases:
  - **Log and event analytics** (application logs, clickstream, security/SIEM).
  - **Full-text search** (site search, product search, document search).
  - **Real-time application monitoring** (with dashboards and alerts).
  - **Vector / semantic search** for GenAI and RAG (k-NN).
  - **Observability** (logs + metrics + traces).
- Includes **OpenSearch Dashboards** (visualization; successor of Kibana) and **SQL/PPL** query support.
- Scale: up to **1,002 data nodes** and **25 PB** attached storage per domain (doc numbers).

## B. When to use / not use
- Use it when you need **full-text search**, **relevance ranking**, **fuzzy matching**, **aggregations over logs**, or **near-real-time dashboards**.
- Use it for **log analytics** when you need fast ad-hoc search over recent logs.
- Use it for **vector search + keyword search together** (hybrid).
- Do not use it as a **system of record**. It is eventually consistent and can lose data in some failures. Keep the source of truth in S3, DynamoDB or a database.
- Do not use it for **transactions** or joins. Use RDS/Aurora.
- Do not use it for **heavy SQL analytics** on huge historical data. Use Athena/Redshift on S3.
- Do not use it for simple key-value lookups. Use DynamoDB.
- Do not use it for **long retention of cheap logs** unless you use UltraWarm/cold or S3 + Athena.
- Related services: **CloudWatch Logs Insights** (simple log queries, no cluster), **Athena** (SQL on S3), **Kendra** (managed enterprise search with ML), **Redshift** (warehouse).

## C. Core concepts (search engine basics)
- **Document**: one JSON record. **Index**: a collection of documents (like a table). **Field**: a key in a document.
- **Shard**: a slice of an index. Each shard is a Lucene index. **Primary shard** takes writes; **replica shard** is a copy.
- **Node**: one server running OpenSearch. **Cluster/domain**: group of nodes.
- **Inverted index**: maps terms → documents. This makes full-text search fast.
- **Mapping**: schema of an index (field types). Dynamic mapping guesses types; explicit mapping is safer.
- **text** field = analyzed (broken into tokens) for full-text search. **keyword** field = exact value (filters, sorting, aggregations).
- **Analyzer**: tokenizer + filters (lowercase, stop words, stemming). Chosen per field. (verify details)
- **Relevance**: results are scored (BM25). Higher score = better match.
- **Near-real-time**: a new document becomes searchable after a **refresh** (about 1 second by default). Not instant.
- **Query DSL**: JSON queries (match, term, bool, range, aggregations). Also **SQL** and **PPL** plugins.
- **Aggregations**: group and calculate (count, avg, histogram) → dashboards.
- **Alias**: a name pointing to one or more indexes (swap indexes without changing clients).
- **Index template**: auto-applies mappings/settings to new indexes (e.g., daily log indexes).
- **Rolling indexes**: time-based indexes (logs-2026-10-02). Delete whole old indexes instead of deleting documents.
- **Reindex / split / shrink**: ways to change shard counts later.
- Document `_id`: same id = update/overwrite. Auto id = new document each time.

## D. Node types in a domain
- **Data nodes**: store shards, run indexing and search. Hot storage (EBS or instance store).
- **Dedicated master (cluster manager) nodes**: manage cluster state only (no data, no queries). Improve stability.
- **Dedicated coordinator nodes** (optional): route requests and reduce load/IP use on data nodes (about 10% of data node count; verify).
- **UltraWarm nodes**: read-only data stored in S3 with cache (cheap).
- **Cold storage**: archived indexes in S3; not searchable until moved to warm.
- **OpenSearch Optimized instances (OR1, OR2, OM2, OI2)**: use S3-backed storage for durability; good price-performance for log analytics/ingest-heavy workloads. (verify exact differences)
- Instance families: general **M**, compute **C**, memory **R**, storage **I/Im4gn**, burstable **T3**, Graviton (**m6g/r6g/c6g/r7g/m7g/c7g/r8g…**). Graviton and gp3 are the cost-efficient defaults.
- **T2/T3** burstable types are for dev/test only; cannot use UltraWarm with T2/T3 data nodes.
- Storage options: **EBS (gp3 recommended, gp2, io1/Provisioned IOPS)** or **instance store** (I, R6gd, etc. – fastest, data lost if node lost, replicas needed).
- Magnetic EBS max 100 GiB (not for Graviton).
- EBS volume maximum depends on instance type (for example r6g.large gp3 up to 2 TiB; larger types up to 24–36 TiB).

## E. Dedicated master nodes (verified)
- Tasks: track nodes, indexes and shards; keep routing info; update and replicate cluster state; heartbeat checks.
- **Recommended: 3 dedicated master nodes** for production (quorum = 2). Never an even number.
- **1 is prohibited**. **2 has no quorum** after one fails. **4 is no better than 3** and can hurt Multi-AZ. **5** works but wastes money.
- Only **one master is active**; the others are standby for election.
- If quorum is lost, **reads and writes fail** (different from OpenSearch default).
- Masters are spread across **3 AZs even if data nodes use 2 AZs** (when the Region has 3).
- Sizing by RAM (2.17+): 8 GB master → up to ~30 nodes/15K shards; 16 GB → 60 nodes/30K shards; 32 GB → 120 nodes/60K shards; 64 GB → 240 nodes/120K shards; 128 GB → 480 nodes/240K shards. (For 1.x–2.15 limits are lower.)
- Bigger clusters or many shards/field mappings → bigger master instance.
- You pay hourly for master nodes like any node.

## F. Sizing: storage (verified)
- Two workload types: **long-lived index** (search catalogs) and **rolling indexes** (logs, retention window).
- Rolling index storage = data per period × retention period. Example: 200 MiB/hour ≈ 4.7 GiB/day ≈ 66 GiB for 14 days.
- Add:
  - **Replicas**: each replica is a full copy. Default 1 replica. Use at least 1.
  - **Indexing overhead**: about +10% (source+index ≈ 110% of source).
  - **Linux reserved space**: 5%.
  - **OpenSearch Service overhead**: 20% of each node's storage, up to 20 GiB per instance (merges, logs).
- Formula: **source × (1 + replicas) × (1 + 0.1) / 0.95 / 0.8** ≈ **source × (1 + replicas) × 1.45**.
- Example: 66 GiB, 1 replica → ≈ 191 GiB minimum.
- **Insufficient storage is the most common cause of cluster instability.**
- UltraWarm storage counts only **primary shards** (no replicas, no OS overhead).
- Over 1 PB → see petabyte scale guidance (use UltraWarm/cold, multiple tiers).

## G. Sizing: shards (verified)
- OpenSearch Service defaults: **5 primary shards + 1 replica** per index (differs from open source default of 1 primary). Decide shard count **before** first document; changing primaries later needs reindex/split/shrink.
- Target **shard size**: **10–30 GiB** when search latency matters; **30–50 GiB** for write-heavy log analytics. UltraWarm: max 50 GiB recommended.
- Too many small shards → CPU/memory pressure and out-of-memory. Too large shards → slow recovery.
- Primary shard formula: **(source data + growth) × 1.1 / desired shard size**.
- Spread shards evenly: pick a shard count that is a **multiple of the data node count** so nodes share load.
- **Max 25 shards per GiB of JVM heap** per node (rule of thumb).
- Shard count limits per node: **1,000** (ES 7.x and OpenSearch up to 2.15, adjustable with `cluster.max_shards_per_node`). **OpenSearch 2.17+: 1,000 per 16 GB of heap, max 4,000 per node, not changeable.**
- With Multi-AZ with Standby: max 1,000 shards per node, 75,000 per cluster, **shard size ≤ 65 GB**.
- JVM heap = **50% of instance RAM, up to 32 GiB** (r7g and OpenSearch optimized can use more via Auto-Tune or Support).
- Stay under **80% disk usage**.

## H. Sizing: instances
- Start with an estimate, then **test with a representative workload** and monitor.
- Search-heavy → more memory/CPU, more replicas. Log ingest-heavy → more shards/disk, fewer replicas on warm, bigger indexing throughput.
- Vector search → memory-optimized (graphs live in off-heap memory; see file 2).
- Keep data-node count a **multiple of AZ count** (3 AZs → 3, 6, 9 …) so shards balance across zones.
- Use **at least 2 replicas** when 3 AZs are used so each AZ holds a full copy (needed for Multi-AZ with Standby).

## I. Versions and support (verified)
- Supported OpenSearch versions at doc time: 3.5, 3.3, 3.1, 2.19, 2.17, 2.15, 2.13, 2.11, 2.9, 2.7, 2.5, 2.3, 1.3, 1.2, 1.1, 1.0. Elasticsearch: 7.10 down to 1.5.
- **Upgrade** to latest OpenSearch for best price-performance and features.
- **Standard support** gives bug and security fixes. **Extended support** (critical security fixes, extra charge) comes after.
  - End of standard support examples: ES 1.5–7.8 and OpenSearch 1.0–1.2, 2.3–2.9 → **7 Nov 2025**.
  - ES 6.8, 7.9, 7.10, OpenSearch 1.3, 2.11–2.19 → **7 Nov 2027**.
  - Extended-support charges: either **equal to the instance cost** (older versions after extension) or a **flat fee per Normalized Instance Hour** (e.g., $0.0065/NIH in us-east-1). Storage is not charged extra.
- Domains running a version no longer in standard support are charged extended support **automatically**.
- Serverless collections upgrade **automatically**.
- Configuration changes usually run as **blue/green deployments** (new nodes created, data copied, then switch). Safe but temporarily needs capacity and may cost extra.

## J. Domain basics you configure
- Engine and version. Instance types and counts. Dedicated master and (optional) coordinator nodes.
- Storage type/size. Multi-AZ choice (with/without Standby). UltraWarm/cold.
- Network: **public** or **VPC** (cannot change later). Access policy. Fine-grained access control. Encryption (at rest, node-to-node). TLS policy. Custom endpoint.
- Auto-Tune (automatic tuning of JVM, queue sizes, etc.).
- Off-peak window for service software updates (verify).
- Tags, logs publishing (slow logs, error logs, audit logs), snapshot settings.

## K. OpenSearch vs other AWS options (decision lines)
| Need | Pick |
|---|---|
| Full-text search, relevance, fuzzy, autocomplete | **OpenSearch** |
| Log analytics with fast ad-hoc search and dashboards | **OpenSearch** |
| Ad-hoc SQL on S3 logs, rarely, cheap | **Athena** |
| Historical analytics and BI | **Redshift** |
| Key lookup, serverless OLTP | **DynamoDB** |
| Simple log search inside AWS console | **CloudWatch Logs Insights** |
| ML-powered enterprise search across repositories | **Kendra** |
| Vector search with relational data | **Aurora PostgreSQL (pgvector)** |
| Vector search with ultra-low latency, in-memory | **MemoryDB** |
| Vector search at large scale + keyword search | **OpenSearch** |
| Graph traversals | **Neptune** |

## Scenarios (if → then, because)
- **If** an app needs search that tolerates typos and shows the best matches first, **then** use **Amazon OpenSearch Service**, a managed search and analytics engine. **This works because** it builds an **inverted index**, which maps each term to the documents that contain it, so full-text search is fast. Each result also gets a **relevance score** (**BM25**), so a higher score means a better match, and fuzzy matching handles typos.
- **If** you must keep logs for **14 days** and show them on dashboards, **then** write them to **rolling daily indexes** (for example logs-2026-10-02) and let an **Index State Management (ISM)** policy delete each index when it is older than 14 days. An **index template** applies the same mappings to every new daily index. **This works because** deleting a **whole old index** is cheap, while deleting single documents is slow. Storage needed is simply data per day × **14 days**.
- **If** you must size storage for **66 GiB** of source data with **1 replica**, **then** plan about **191 GiB** at minimum. The formula is **source × (1 + replicas) × 1.1 / 0.95 / 0.8**, roughly **source × (1 + replicas) × 1.45**. **This works because** each **replica** is a full copy, indexing adds about **10%**, Linux reserves **5%**, and OpenSearch Service keeps **20%** of each node's storage (up to 20 GiB) for merges and logs. Too little storage is the **most common cause** of cluster instability.
- **If** a team asks for **2 dedicated master nodes**, **then** use **3**. Dedicated master (cluster manager) nodes only manage the cluster state; they hold no data. **This works because** with 3 masters the **quorum** is 2, so the cluster survives one failure; with 2, losing one leaves **no quorum**, and then **reads and writes fail**. Never use an even number: **1 is not allowed**, and **4 is no better than 3**.
- **If** shards are only about **1 GB** each and there are **thousands** of them, **then** reduce the shard count (merge data into fewer, bigger shards, for example with **reindex** or **shrink**). Aim for **10–30 GiB** per shard when search speed matters, or **30–50 GiB** for write-heavy logs. **This works because** every shard uses **JVM heap** and **CPU**, so many tiny shards cause memory pressure and even out-of-memory errors. Keep to at most **25 shards per GiB of heap**.
- **If** an index needs more **primary shards** later, **then** **reindex** it into a new index (or use **split**). **This works because** the primary shard count is fixed when the index is created (the service default is **5 primaries + 1 replica**), so decide it before the first document.
- **If** a domain has **6 data nodes across 3 Availability Zones (AZs)** and you want a full copy of the data in each AZ, **then** set **at least 2 replicas** per index. **This works because** 1 primary + 2 replicas = **3 copies**, one per AZ, so losing an AZ still leaves full data. Keep the data-node count a **multiple of the AZ count** (3, 6, 9…) so shards balance. This is also required for **Multi-AZ with Standby**.
- **If** an old index is read-only but must stay searchable, **then** move it to **UltraWarm**, a tier that keeps read-only data in **Amazon S3** with a cache. **This works because** S3 storage is much cheaper than hot node disks, and UltraWarm counts only **primary shards** for storage (no replicas).
- **If** a new domain must be reachable only from inside a **Virtual Private Cloud (VPC)**, **then** choose **VPC access when you create it**. **This works because** network type (public or VPC) **cannot be changed** later; switching means a new domain plus a snapshot restore or reindex.
- **If** you need a **source of truth** for your data, **then** keep it in **Amazon S3**, **Amazon DynamoDB** or **Amazon Relational Database Service (RDS)**, and copy (index) it into OpenSearch for searching. **This works because** OpenSearch is **not a system of record**: it is eventually consistent and can lose data in some failures, so you must be able to rebuild the index from the source.

## Verified from AWS docs on 2026-10-02
Read: what-is page (features, versions, extended support, pricing), sizing pages (storage and shard sizing), multi-AZ page, dedicated master page, limits page. Not confirmed (verify): analyzer/refresh details (general OpenSearch knowledge), coordinator node ratio, OR1/OR2/OM2/OI2 specifics, off-peak window, Auto-Tune scope, exact EBS gp3 limits per type.

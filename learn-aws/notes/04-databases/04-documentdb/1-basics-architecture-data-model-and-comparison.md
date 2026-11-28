# DocumentDB – 1. Basics, architecture, clusters, data model, indexes, operations, vs DynamoDB

Short notes. Each point is a fact you can be asked about.

## A. What Amazon DocumentDB is
- Fully managed **document database** with **MongoDB compatibility**. You use MongoDB drivers, tools and query language against it.
- It is **not MongoDB**. AWS built a separate engine and emulates the MongoDB API (versions **3.6, 4.0, 5.0 and 8.0** are supported). Some MongoDB features are missing or behave differently.
- Data is stored as JSON-like documents (BSON) in collections inside databases.
- Pick it for: existing MongoDB apps moving to AWS with few code changes, content management, catalogs, user profiles, mobile/web backends, flexible schemas needing rich queries, aggregation pipelines, vector search on documents.
- Avoid it for: unlimited key-value scale with serverless pricing (DynamoDB), complex joins and strict relational integrity (RDS/Aurora), full-text search at scale (OpenSearch), graph traversal (Neptune), heavy analytics (Redshift/Athena).
- Runs inside your VPC only (no public endpoint).
- Compatible with MongoDB drivers and tools: mongosh, mongodump/mongorestore (use MongoDB Database Tools up to and including version 100.11.0 – verified).
- Same storage design family as Aurora: separate compute and storage, shared cluster volume.

## B. Cluster architecture (verified)
- A **cluster** = 0 to 16 instances + one cluster storage volume.
- **Primary instance**: the only one that accepts writes. **Replica instances**: up to **15**, read-only, share the same storage.
- Cluster volume: data copied **6 ways across 3 AZs**, independent of the number of instances.
- Storage auto-grows in **10 GB** steps up to **256 TiB** for engine 8.0 and later (128 TiB earlier). Pay only for what you use.
- Compute and storage scale separately. Add replicas in minutes regardless of data size.
- Replicas return results with minimal lag, usually well under 100 ms (often around 50 ms or less).
- Instance restarts do not need crash recovery replay; the buffer cache survives an instance restart (cache is separate from the database process).
- In engine 5.0 and 8.0, replicas do **not** restart when the primary restarts (better availability).
- A cluster in a Region with 2 AZs still stores data across 3 AZs but places compute only in the available AZs.
- Region compute AZ counts vary (for example us-east-1 has 6, most Regions 3).

## C. Endpoints and connecting (verified)
- **Cluster endpoint**: always points to the current primary. Use for writes.
- **Reader endpoint**: load-balances connections across replicas. Use for reads.
- **Instance endpoints**: a specific instance (avoid for app use).
- Port **27017**. TLS enabled by default; use the Amazon CA bundle (`global-bundle.pem`).
- Use **replica set mode**: connection string with `replicaSet=rs0`, and `readPreference=secondaryPreferred` so reads go to replicas and the primary does more writes. Include `retryWrites=false` for engines older than 8.0.2.
- Connecting from outside the VPC: use a bastion/EC2 with an SSH tunnel, VPN, Direct Connect or peered network. There is no public access.
- Always connect through the cluster endpoint, not an instance IP, so failover is transparent.
- Your app should retry transient errors with exponential backoff.

## D. Cluster types and instance options
- **Instance-based cluster** (classic): you choose instance classes. Scales reads with replicas, writes by scaling the primary up.
- **Elastic cluster** (sharded): automatic sharding for millions of reads/writes per second and petabytes of data (verified). Details in section F.
- **Instance classes (verified)**: memory-optimized R8G, R6G (Graviton), R6GD (NVMe-backed), R5, R4 (3.6 only), burstable T4G and T3, and **Serverless** (DCU-based). Not all classes exist in every Region.
- **RAM matters**: DocumentDB reserves about one-third of RAM for its own services, so only about two-thirds is available for cache. Size so the working set (data + indexes) fits in memory (verified best practice).
- Burstable T3/T4G (medium only): for dev/test; limited connections (1,000) and cursors.
- **NVMe-backed instances (R6GD)**: local tiered cache; metrics like `NVMeStorageCacheHitRatio`; for large working sets.
- **Storage configuration** (5.0+ instance-based): **Standard** (pay per I/O) or **I/O-Optimized** (no per-I/O charge). Choose I/O-Optimized when I/O is more than about 25% of your total DocumentDB cost (verified guidance).
- **DocumentDB Serverless**: instance class `db.serverless`; capacity in DCUs (about half-DCU steps); scales without disrupting transactions; for spiky, multi-tenant, dev/test workloads; readers can scale independently via promotion tiers; works with global clusters; can mix with provisioned instances (verified overview).
- Minimum production layout: 3 instances in 3 AZs (one primary + two replicas). Minimum for HA: 2 instances in 2 AZs.

## E. Data model basics
- **Database** → **collection** → **document**. A document is a JSON-like object with fields, arrays, nested documents.
- Every document has `_id` (unique in the collection; auto-generated ObjectId if omitted).
- Documents in one collection can have different shapes (schemaless). Use application-level validation if you need rules.
- Document size limit **16 MiB**. Nesting depth up to 200 levels (instance-based) (verified).
- BSON types: string, int32/int64, double, decimal128, boolean, date, ObjectId, array, object, binary, null, etc.
- Schema design: **embed** related data inside one document when it is read together and small and bounded (orders with line items); **reference** (store IDs, query separately or `$lookup`) when data is large, shared, or grows unbounded.
- Design for access patterns, but you can add indexes and run ad hoc queries later, unlike DynamoDB.
- Avoid unbounded arrays inside one document and unbounded numbers of top-level field names.
- Names: database 1–63 chars; collection 1–255 chars on 5.0+ (1–57 on 4.0 and earlier); index name up to 255 chars on 5.0+ (verified).
- Case-sensitive names. `admin`/`local` databases and `system.*` collections are not supported (verified).
- No schema migration locks like SQL; adding fields just means writing them.

## F. Elastic clusters (verified)
- Use **hash-based sharding**: you choose a **shard key** for each sharded collection; DocumentDB spreads documents across **shards**.
- Each shard has one writer and 0–15 read replicas (default two instances in different AZs). Up to **32 shards**; up to **64 vCPUs per shard instance**.
- Quotas: 20 elastic clusters per Region; 1,024 total vCPU per Region; storage up to 4 PiB per cluster (even distribution); sharded collection up to ~1 PB; unsharded collection 32 TiB; 1,000 sharded collections; 100,000 unsharded collections; 10,000 databases; 100 users per cluster; nesting depth 100; 20 manual snapshots per Region.
- Scale out by adding shards, scale up by adding vCPUs per shard. Data is redistributed automatically by copying within shared storage.
- Choose a shard key with **many unique values** and even access (like a user ID). A poor key creates hot shards.
- Elastic clusters are for very large write/read scale; instance-based clusters are simpler for most apps.
- Elastic clusters run engine compatibility close to 5.0 with some functional differences (for example `$elemMatch` matches only the first array level; some projection and `$regex` behaviors differ).
- Elastic clusters do not use the RDS-shared management technology (verified).
- MongoDB sharded data can be migrated to elastic clusters (offline, online, hybrid).

## G. Indexes
- Default index on `_id`. Add indexes for fields you filter, sort or join on.
- Types: single field, compound (up to **32** keys), multikey (arrays), sparse, unique, TTL, text, 2dsphere (geospatial), and **vector** indexes (HNSW, IVFFlat).
- Limits (verified): up to **64 indexes per collection**; index key up to 2,048 bytes; indexes count against storage and write cost.
- **Index builds**: only **one index build per collection at a time**; building runs in the foreground by default; a second `createIndex/dropIndex` on that collection fails while one is running (verified). TTL starts only after the index build completes.
- Index version `v: 3` supports arrays larger than 2,048 bytes total and multi-key compound indexes on the same array; recreate old indexes to get it (verified).
- **Sparse index**: queries must include `$exists` on the indexed field or the index is not used (verified).
- **$regex with index** needs `hint({field:1})`, works best for prefix regex without `i`, `m`, `o` options (verified).
- Best practices (verified): create indexes **before** bulk imports; index fields with **high cardinality** (duplicates under 1% of documents); keep indexes per collection to about **five or fewer** where possible; drop unused indexes; find missing indexes with profiler/explain. Each extra index adds write latency, I/O and storage.
- Use `explain()` and `hint()`; plans differ from MongoDB so verify.
- **TTL index**: set `expireAfterSeconds` on a date field. Deletion is **best effort** (not guaranteed timing). Each TTL delete costs I/O. For big time-series data, **rolling collections** (one per day/week, drop old ones) are cheaper than TTL (verified guidance). `TTLDeletedDocuments` metric counts deletions.
- **Vector indexes** (5.0 instance-based clusters): see section I.

## H. Operations and features
- **CRUD**: insertOne/Many, find, updateOne/Many, deleteOne/Many, bulkWrite, findAndModify. All CRUD statements are atomic and consistent per statement, even those touching many documents (verified: implicit transactions). Bulk operations are atomic per individual statement but the whole bulk batch is not atomic; use a transaction if you need ACID for the entire batch.
- **Aggregation pipeline**: up to **500 stages** (verified). Put `$match` first to cut data early. `$lookup` supports equality matches and uncorrelated subqueries; **correlated subqueries from engine 8.0.2** (verified). You can influence `$lookup` with a plan hint: `HASH`, `SORT`, or `NESTED_LOOP` (verified algorithms: hash for small foreign collections that fit in memory, nested loop for indexed small foreign collections, sort-merge for large unindexed data).
- **Transactions**: multi-document, multi-collection ACID transactions on engine **4.0 and later** (snapshot isolation). No extra charge; you pay normal I/O. Always commit or abort; long/idle transactions hold resources and cause write conflicts. Open transaction limits per instance class (for example 200 on r5.large, 50 on t3.medium) (verified). Default transaction timeout is short (about 1 minute; verify).
- **Change streams**: time-ordered change events (see file 3 for integrations).
- **Retryable writes**: supported from engine **8.0.2**; earlier versions require `retryWrites=false` (verified).
- **Sessions and cursors**: cursor limits per instance (for example 450 on r5.large). Cursor timeouts apply.
- **Result ordering is not guaranteed** unless you `sort()` (verified).
- `$natural` reverse sorting is not supported (verified).
- Unsupported or different (verified): admin/local databases; `$vectorSearch` as an independent operator before 8.0 (uses `$search` with `vectorSearch`); `$elemMatch` inside `$all`; `explain()` plans differ; `mongodump/mongorestore` do not dump the admin database (recreate users after restore). See the supported API list in docs for other operators (verify before migrating).
- Compatibility check tools: AWS Index Tool and Compatibility Tool help find unsupported features before migration.

## I. Vector search (exam skills 2.1.3, 2.1.8, 2.4.6)
- Available on **engine 5.0+ instance-based clusters** (verified).
- Store embeddings as arrays of numbers in a field (for example `vectorEmbedding: [0.2, 0.5, 0.8]`).
- Index types: **HNSW** (graph, best recall and query speed, slower build, no training step, can be built on an empty collection; default for new vector indexes on recent patches) and **IVFFlat** (clusters into lists, faster/cheaper to build, create after data exists).
- Without a vector index DocumentDB does an **exact nearest-neighbour search** (perfect recall, slow on big data).
- Create with `createIndex` (or `runCommand createIndexes` in drivers that reject `vectorOptions`): fields: `type` (hnsw/ivfflat), `dimensions` (**up to 2,000 indexed**; up to 16,000 dimensions can be stored unindexed), `similarity` (**euclidean, cosine, dotProduct**), HNSW `m` (default 16, range 2–100), `efConstruction` (default 64, range 4–1000, must be ≥ 2×m), IVFFlat `lists` (recommended documents/1000 up to 1M docs, sqrt(docs) above; max depends on instance size and dimensions).
- Query with `$search: { vectorSearch: { vector, path, similarity, k, efSearch (HNSW, default 40, range 1–1000), probes (IVFFlat, default 1) } }`. From engine 8.0 also `$vectorSearch` (`queryVector`, `path`, `limit`, `numCandidates`, `exact`, `index`; HNSW only).
- Higher `efSearch`/`probes` = better recall, slower. Suggested start for `probes`: sqrt(lists).
- Limits (verified): no compound, sparse or partial vector index options; parallel HNSW build not supported in 5.0.
- Load some data before creating an IVFFlat index.
- Use for semantic search, recommendations, RAG (Bedrock knowledge bases), fraud/anomaly detection, personalization.
- Alternatives: Aurora/RDS pgvector, OpenSearch k-NN, MemoryDB, DynamoDB vector indexes.

## J. DocumentDB vs DynamoDB – when to use which
| | **DocumentDB** | **DynamoDB** |
|---|---|---|
| Model | Documents (BSON), nested, flexible | Items by primary key; document-like attributes |
| API | MongoDB drivers, query language, aggregation | AWS SDK calls (GetItem/Query), PartiQL |
| Query power | Query any field, secondary indexes (up to 64/collection), aggregations, text/geo/vector | Fast by key; other patterns need GSIs; no joins/aggregations |
| Design style | Model documents, then index for queries; ad hoc queries are normal | Access-pattern-first; unknown queries are painful |
| Max item | **16 MiB** document | **400 KB** item |
| Capacity | Instances you size (or Serverless DCUs); replicas up to 15; elastic clusters for sharding | Serverless on-demand or provisioned; practically unlimited scale |
| Scaling writes | Scale up primary or use elastic cluster (shard key) | Automatic partitioning |
| Latency | Low milliseconds | Single-digit ms at any scale |
| Consistency | Primary strongly consistent; replicas eventually (lag <100 ms) | Eventual or strong per read |
| Transactions | Multi-document ACID (4.0+), snapshot isolation | Up to 100 items, ACID |
| Multi-Region | Global clusters: 1 writer Region + up to 10 read-only Regions | Global tables: multi-active |
| Network | Inside your VPC only | Public endpoint or VPC endpoints |
| Auth | Users, roles (RBAC), SCRAM, IAM (5.0); TLS | IAM only |
| Ops effort | Medium (instances, parameter groups, patching windows, sizing) | Very low |
| Change data capture | Change streams (enable per collection) | DynamoDB Streams / Kinesis |
| Cost model | Instance hours + storage + I/O (+ backup) | Per request/capacity + storage |
| Lock-in | MongoDB-compatible, portable-ish | AWS-specific |

**Pick DocumentDB when:** you already run MongoDB, need MongoDB compatibility and tools, need flexible ad hoc queries across many fields, aggregations, larger documents (>400 KB), or vector search on documents with a MongoDB-style API.
**Pick DynamoDB when:** access patterns are known and key-based, you need massive serverless scale and spiky traffic with no sizing, multi-Region active-active writes, deepest AWS integration (Lambda, Streams, IAM), or the lowest operations effort.
**Pick neither when:** you need joins and strict relational rules (RDS/Aurora), analytics (Redshift/Athena), search (OpenSearch), graph (Neptune).
- Migration direction: MongoDB → DocumentDB is easy; MongoDB → DynamoDB is a redesign (data model rewrite).
- Cost: DocumentDB has idle cost (instances run always, unless Serverless); DynamoDB on-demand costs nothing when idle.

## K. Scenarios (if → then, because)
- **If** a team already runs a MongoDB app and wants to move it to AWS with as little code change as possible, **then** use **Amazon DocumentDB**, a fully managed document database with MongoDB compatibility. The app keeps its **MongoDB drivers**, tools (like mongosh) and query language. **This works because** DocumentDB emulates the MongoDB API (versions **3.6, 4.0, 5.0 and 8.0**). The catch: it is **not MongoDB** but a separate AWS engine, so some features are missing or behave differently; run the AWS **Compatibility Tool** before migrating.
- **If** the data is read by a simple key lookup and traffic is huge and unpredictable, **then** use **Amazon DynamoDB on-demand** instead of DocumentDB. **This works because** DynamoDB is serverless, partitions automatically and scales practically without limit, and on-demand costs nothing when idle. DocumentDB runs instances that you must size, and they cost money even when idle.
- **If** the app needs **aggregation pipelines** and queries on any field, **then** use **DocumentDB**. **This works because** you can query any field, add secondary indexes (up to **64 per collection**), run ad hoc queries and build aggregations of up to **500 stages**. DynamoDB is fast by key only; other query patterns need Global Secondary Indexes (GSIs), and it has no joins or aggregations.
- **If** each document is about **5 MB**, **then** store it in **DocumentDB**, whose document limit is **16 MiB**. **This works because** the limits differ a lot: a **DynamoDB** item can be at most **400 KB**, so there you would have to keep the document body in **Amazon Simple Storage Service (S3)**.
- **If** most traffic is reads, **then** add **replica instances** (up to **15**, read-only) and connect through the **reader endpoint** with `readPreference=secondaryPreferred`. **This works because** the reader endpoint load-balances connections across the replicas, which all share the same storage, and `secondaryPreferred` sends reads to replicas so the primary has more room for writes. Replica lag is usually well under **100 ms**, so replica reads can be slightly behind.
- **If** write throughput grows beyond what the largest primary instance can handle, **then** use a DocumentDB **elastic cluster** with a good **shard key** (many unique values and even access, like a user ID). **This works because** an instance-based cluster has only **one writer**, while an elastic cluster uses hash-based sharding to spread documents across up to **32 shards**, each with its own writer. A poor shard key creates **hot shards**.
- **If** traffic is spiky and you do not want to choose instance sizes, **then** use **DocumentDB Serverless** (instance class `db.serverless`). **This works because** capacity is measured in capacity units (DCUs) that scale automatically without disrupting transactions, and you pay per DCU-hour used. The exact DCU ranges and pricing are not confirmed (verify).
- **If** you need geo, text or vector search in the same database as your documents, **then** use DocumentDB's built-in index types: **2dsphere** for geospatial queries, **text** for text search, and **vector** indexes (HNSW or IVFFlat) for similarity search. **This works because** one store handles all three, so you do not copy data to another service. For full-text search at large scale, **Amazon OpenSearch Service** is still the better fit.
- **If** the app needs **semantic search** (find similar meaning, not exact words) with a MongoDB-style API, **then** create a DocumentDB **vector index** of type **HNSW** on the field that holds the embeddings. **This works because** HNSW gives the best recall and query speed, needs no training step and can be built on an empty collection. Vector search needs **engine 5.0+ instance-based clusters**; without a vector index DocumentDB does an exact search, which is slow on big data.
- **If** you need read copies in other Regions with fast failover, **then** use a DocumentDB **global cluster**: one primary Region for writes plus up to **10 read-only secondary Regions**. **This works because** replication happens at the storage level with lag typically **under 1 second**, and a secondary can be promoted within minutes (Recovery Time Objective (RTO) typically under a minute, Recovery Point Objective (RPO) in seconds). Writes still go only to the primary Region.
- **If** you need a graph database or complex joins with strict relational rules, **then** do **not** use DocumentDB; use **Amazon Neptune** for graphs and **Amazon Aurora** (or RDS) for joins. **This works because** DocumentDB is a document store built for flexible documents, not for graph traversal or strict relational integrity.
- **If** a query using `$regex` is slow, **then** add an index on the field, write the regex as a **prefix** match without the `i`, `m` or `o` options, and force the index with `hint({field:1})`. **This works because** DocumentDB needs the hint to use an index for `$regex`, and prefix patterns use it best.
- **If** the working set (hot data plus indexes) does not fit in memory, **then** move to a **larger instance class** and watch the `BufferCacheHitRatio` metric. **This works because** DocumentDB keeps about one-third of RAM for its own services, so only about **two-thirds** is cache, and a low hit ratio means reads go to storage. Scale up until the ratio stops improving.
- **If** you must import a large dataset fast, **then** **create the indexes first** and load the data after. **This works because** building indexes before a bulk import makes the load faster (AWS best practice); the AWS **Index Tool** can copy index definitions from MongoDB.
- **If** you want to delete old data cheaply from a huge time-series collection, **then** use **rolling collections** (one per day or week) and **drop** the old ones instead of a Time To Live (TTL) index. **This works because** dropping a collection is fast and has no per-document cost, while every TTL delete costs I/O and its timing is only best effort.

## Verified from AWS docs on 2026-10-02
What is DocumentDB, quotas, functional differences, elastic clusters, replication, vector search, best practices and connection pages were read. Not confirmed (verify): the exact default transaction timeout, DocumentDB vs MongoDB Atlas differences, full supported-operator list, 5.0 vs 8.0 feature table, Serverless DCU ranges and pricing.

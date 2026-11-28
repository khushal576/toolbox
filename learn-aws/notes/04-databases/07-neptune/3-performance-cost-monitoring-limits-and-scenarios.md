# Neptune – 3. Performance, cost, monitoring, limits, traps and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Performance tuning (verified best practices)
- **Memory first**: graph traversals love the buffer cache. If **`BufferCacheHitRatio` < 99.9%**, move to a larger instance class.
- **Same instance class** for writer and readers in a cluster. Mixed sizes can cause lag or slowdowns after failover.
- **Scale reads** with replicas (up to 15). Use the **reader endpoint** for connection spread; use **instance/custom endpoints** to balance or isolate workloads (Neptune does **not** balance queries).
- **Custom endpoints** (up to 5): send heavy analytics to bigger replicas and OLTP reads to smaller ones.
- **Connection handling**: reuse client objects across threads; keep separate clients for read and write endpoints; add several reader endpoints to a Java connection pool; close clients to avoid hitting the connection limit.
- **After failover or replica change** → create a new connection and re-resolve DNS. **Disable DNS caching** (JVM, proxies).
- **Gremlin tips**: send queries as **bytecode** rather than strings (Java); consume the whole `ResultSet`; bulk add vertices/edges in **batches**; structure upserts for the **DFE** engine; set per-query timeouts; set `maxInProcessPerConnection` and `maxSimultaneousUsagePerConnection` equal.
- **openCypher tips**:
  - Use **parameterized queries**.
  - Put the most restrictive filters and nodes **early/left**.
  - Specify **edge labels** and use granular relationship names.
  - Prefer **directed** edges over bidirectional.
  - Batch with **`UNWIND`**; use flattened maps; avoid `WITH` and `COLLECT(DISTINCT())` when possible.
  - Avoid named paths unless needed; use custom node IDs; avoid ID computations in the query.
  - Use explicit transaction modes; add **retry logic**.
  - Open a new connection after failover; on Lambda, create connections per invocation context carefully.
- **SPARQL tips**: query all named graphs by default; name the graph on load; choose between `FILTER`, `FILTER…IN`, and `VALUES` for batch lookups.
- **OSGP index**: enable it if your RDF data has a **large number of predicates**.
- **Avoid long-running transactions** (they block purge and use memory).
- **Query tooling**: use **explain/profile** per language to see the plan (Gremlin `explain`/`profile`, SPARQL explain, openCypher explain).
- **Lookup cache** (r5d + local NVMe): speeds property lookups (not on Serverless).
- **Gremlin result cache**: caches query results (`NumResultCacheHit/Miss`, `ResultCacheSizeInBytes` metrics).
- **Request queue**: when requests exceed capacity, they wait in a queue; once the queue is full Neptune **throttles** (HTTP 429/ThrottlingException). Watch `MainRequestQueuePendingRequests`.
- **Query timeout** is set by a cluster parameter (default 120 seconds; verify). Long traversals may time out; reduce depth or add limits.
- **Undo log purge**: only the writer purges. If **`UndoLogListSize`** keeps growing → upgrade the writer. Before upgrading to 1.2.0.0+, the value must be under about **40k for 4xlarge and larger** (**10k** for smaller) or the upgrade rolls back.
- **Bulk loading**: use a **temporary larger writer**, then fail over / resize back; avoid repeated restarts; split files; load into an empty instance when possible.
- **Graph design**: avoid super-nodes with huge degree; use filters on labels; use selective starting points (index lookups) before traversing.
- **Serverless**: set minimum NCU high enough to hold your working set. Too low min/max → timeouts.
- **Resize the writer** by creating a bigger replica and failing over.

## B. Cost (verified model)
- **Provisioned instances**: billed **per hour** by instance class.
- **Serverless**: billed by **NCU-hours, per second**, between your min and max.
- **Storage**: **per GB-month**, billed on the **allocated (high-water mark)** size, not on what you currently use.
- **I/O**:
  - **Standard** storage: also pay **per million I/O requests**.
  - **I/O-Optimized** (engine **1.3.0.0+**): **no per-I/O charge**, but higher instance and storage price. Choose it when I/O is a large part of your bill. You can switch storage type only **once per 30 days**.
- **Backup storage**: free up to **100% of cluster storage**; extra is billed (`TotalBackupStorageBilled`).
- **Data transfer**: free within the same AZ, standard rates across AZs/Regions.
- **Global Database**: replicated write I/O and cross-Region transfer.
- **Streams**: extra I/O + storage.
- **Neptune Analytics**: memory-based **m-NCU**; paused graphs cost much less (about 10% per the pricing page).
- **Notebooks (Workbench)**: instance hours.
- **Database Savings Plans** (1-year) can reduce instance cost; **Reserved instances** (verify availability for Neptune today).
- Save money:
  - Use **Serverless** for spiky/dev/test; use **t3/t4g.medium** for dev.
  - Stop non-production clusters when idle (verify max stop duration, usually 7 days then auto-start).
  - Right-size memory using `BufferCacheHitRatio` and `FreeableMemory`.
  - Remove unneeded replicas; use auto scaling.
  - Delete old manual snapshots.
  - Turn Streams off if unused.
  - Pick I/O-Optimized if I/O is a big cost share.
  - Keep large blobs in S3.

## C. Monitoring (CloudWatch namespace `AWS/Neptune`, mostly 1-minute) (verified)
- **Compute**: `CPUUtilization`, `FreeableMemory`, `SwapUsage`, `EngineUptime`, `BufferCacheHitRatio`, `CPUCreditBalance` (burstable classes).
- **Requests**: `TotalRequestsPerSec`, `GremlinRequestsPerSec`, `SparqlRequestsPerSec`, `OpenCypherRequestsPerSec`, `LoaderRequestsPerSec`.
- **Errors**: `TotalClientErrorsPerSec`, `TotalServerErrorsPerSec`, per-language client/server errors, `Http4xx/5xx`.
- **Queue and throttle**: `MainRequestQueuePendingRequests`, `NumQueuedRequestsPerSec`.
- **Connections**: `GremlinWebSocketOpenConnections`, `OpenCypherBoltOpenConnections`.
- **Transactions**: `NumTxOpened`, `NumTxCommitted`, `NumTxRolledBack`.
- **Index activity**: `NumIndexReadsPerSec`, `NumIndexInsertsPerSec`, `NumIndexDeletesPerSec`.
- **Replication**: `ClusterReplicaLag` (ms), `ClusterReplicaLagMaximum/Minimum`, `GlobalDbProgressLag`.
- **Storage**: `VolumeBytesUsed` (billed, high-water), **`VolumeBytesLeftTotal`** (best metric to detect nearing 128 TiB), `VolumeReadIOPs`, `VolumeWriteIOPs`, `TempStorageIOPS`.
- **Serverless**: `ServerlessDatabaseCapacity`, `NCUUtilization`.
- **Undo**: `UndoLogListSize`, `NumUndoPagesPurged`.
- **Backups**: `BackupRetentionPeriodStorageUsed`, `SnapshotStorageUsed`, `TotalBackupStorageBilled`.
- **Network**: `NetworkThroughput`, `StorageNetworkThroughput`.
- Neptune sends a metric to CloudWatch **only when its value is non-zero**. Cumulative metrics reset on restart. Some metrics are 5-minute granularity.
- Other tools: Neptune **audit logs** (verify), CloudTrail, **Performance Insights** (verify support), query `status` API for running queries.
- Troubleshooting map:
  - Latency rises + low cache hit → bigger instance.
  - Many pending requests → add replicas / scale up; reduce long queries.
  - 429/throttling → queue full; scale or smooth the load.
  - Timeouts in Serverless → raise min/max NCU.
  - Replica lag → writer too busy or readers too small; match classes; raise serverless min.
  - Out of space error → `VolumeBytesLeftTotal` reached zero (128 TiB cap).
  - Connection errors after failover → stale DNS or old WebSocket connections.
  - Loader failures → missing IAM role, S3 VPC endpoint, wrong Region, bad format, SSE-C file.
  - Upgrade rollback → `UndoLogListSize` too high.

## D. Limits and numbers to remember (verified unless marked)
- Cluster volume max: **128 TiB** (64 TiB in China and GovCloud).
- Read replicas per cluster: **15**. Global Database: **5 secondary Regions**, **16 readers** per secondary.
- Custom endpoints: **5** per provisioned cluster.
- Failover with replicas: usually **under 120 s** (often under 60 s). Without replicas: up to ~**10 minutes**.
- Promotion tiers: **0–15**.
- Serverless: **1–128 NCUs**, smallest max **2.5**, **1 NCU = 2 GiB**, max **256 GB** memory, engine **1.2.0.1+**.
- **TLS** required; **TLS 1.2** minimum; **TLS 1.3** from engine **1.3.2.0**. HTTPS only since engine **1.0.4.0**.
- HTTP request payload (Gremlin/SPARQL over HTTP): **150 MB** max (WebSocket not limited by this).
- Single property/label/RDF value: **55 MB**.
- WebSocket concurrent connections per instance: **32,768** for larger types and Serverless; **512** on t3/t4g.medium; scales with class (2,048 on `.large`, 4,096 `.xlarge`, 8,192 `.2xlarge`, 16,384 `.4xlarge`).
- Idle WebSocket timeout: about **20–25 minutes**. With IAM auth: closed **a bit over 10 days** after opening.
- Bulk loader: **64 queued jobs**, **1,024 jobs** tracked, **10,000 errors** per job.
- Streams retention: **7 days default**, **1–90 days** configurable (engine 1.2.0.0+).
- Auto scaling: scale-out alarm breach **3 min**, scale-in **15 min**; cooldown default **300 s**.
- Storage type switch (Standard ↔ I/O-Optimized): **once per 30 days**; I/O-Optimized needs engine **1.3.0.0+**.
- Neptune ML classification works on **string** values only.
- Port **8182**. Needs a subnet group with **2+ AZs**.
- IAM auth: no username/password; **SigV4** only.
- Share limits with RDS: number of DB instances/clusters per account per Region (see RDS limits).

## E. Common traps
- Treating the **reader endpoint** like a query load balancer → it only balances **connections**.
- Caching DNS → failover does not move traffic.
- No replica → long outage on primary failure.
- Different instance classes in a cluster.
- Believing Neptune has users and passwords → it uses **IAM SigV4** or open access inside the VPC.
- Expecting to encrypt an existing cluster in place → snapshot, copy encrypted, restore.
- Expecting revoked IAM credentials to close open WebSockets.
- Streams: turning them off loses unread log data; they have no native Lambda trigger.
- Bulk loader with `.zip`, SSE-C files, or no S3 VPC endpoint.
- Using PG data with SPARQL or RDF with Gremlin.
- Using T-class instances in a Global Database.
- Confusing **Neptune Database** (OLTP, disk) with **Neptune Analytics** (in-memory analytics).
- Large property values (> 55 MB) stored in the graph instead of S3.
- Forgetting storage is billed on the **high-water mark**.

## F. Decision lines (exam style)
- "Highly connected data, relationships, multiple hops" → Neptune.
- "Property graph, existing Cypher/Neo4j" → openCypher on Neptune.
- "Property graph, TinkerPop" → Gremlin.
- "RDF, ontology, linked data" → SPARQL.
- "Spiky graph workload, no capacity planning" → Neptune Serverless.
- "Graph algorithms across a huge dataset, data science" → Neptune Analytics.
- "Global read performance + Region DR for graph" → Neptune Global Database.
- "Graph predictions (fraud, recommendations)" → Neptune ML.
- "Search within graph text" → OpenSearch via Streams.
- "Need every graph change in order" → Neptune Streams.
- "Load millions of rows from S3" → bulk loader.
- "Keep I/O cost predictable" → I/O-Optimized storage.

## Scenarios (if → then, because)
- **If** latency rises and `BufferCacheHitRatio` is **97%**, **then** move to a larger instance class with more memory. **This works because** graph traversals rely on the **buffer cache** in memory; below **99.9%** the working set does not fit, so queries go to storage more often. Keep writer and readers on the same class.
- **If** a spike hits for a few minutes daily, **then** use **Neptune Serverless** with a generous maximum **Neptune Capacity Unit (NCU)** setting (1 NCU = 2 GiB memory). **This works because** compute scales automatically in **half-NCU** steps between your min and max, and you pay **NCU-hours per second**. Too low a max causes **timeouts**.
- **If** readers run at **80% CPU** for hours, **then** add readers with **read-replica auto scaling** (target tracking on average reader CPU, up to **15** replicas) or scale up the instances. **This works because** reads spread over more replicas, and auto scaling adds a reader after a **3-minute** breach.
- **If** one team's heavy analytics queries hurt the app's OLTP reads, **then** create a **custom endpoint** (up to **5** per cluster) that points only to dedicated, possibly bigger, replicas. **This works because** a custom endpoint is a group of instances you choose, so analytics traffic stays off the replicas that serve the app.
- **If** the app talks to only one replica over a long **WebSocket** connection, **then** close it and reconnect so DNS returns another replica. **This works because** the **reader endpoint** balances only **connections** by changing DNS answers; every request on an open connection stays on the same replica.
- **If** a failover happened and the app still errors, **then** open a **new connection**, **disable DNS caching** (JVM, proxies) and add **retry logic**. **This works because** old WebSocket connections and cached DNS still point to the old primary; the cluster endpoint moves to the new primary only through a DNS update.
- **If** the bill is dominated by **I/O charges**, **then** switch storage to **I/O-Optimized** (engine **1.3.0.0+**). **This works because** it has **no per-I/O charge**, in exchange for higher instance and storage prices. The catch: you can switch storage type only **once per 30 days**.
- **If** dev/test sits idle, **then** stop the cluster (usually max 7 days, then it auto-starts: verify), or use **Neptune Serverless** or a small burstable **t4g.medium** instance. **This works because** provisioned instances are billed **per hour**, so idle compute is wasted money.
- **If** storage keeps growing near **128 TiB**, **then** set an alarm on **`VolumeBytesLeftTotal`**, the best metric for nearing the cap, and archive old subgraphs to **Amazon Simple Storage Service (S3)** or split graphs. **This works because** the cluster volume cannot grow past 128 TiB (64 TiB in China and GovCloud), and when space left reaches zero you get out-of-space errors. Storage is billed on the **high-water mark**.
- **If** throttling (HTTP **429**, verify) appears, **then** add capacity, smooth the request rate and batch writes. **This works because** requests beyond capacity wait in a queue, and once the queue is full Neptune throttles. Watch **`MainRequestQueuePendingRequests`** to see it coming.
- **If** bulk load of a huge file is slow, **then** use a **temporary larger writer**, split the data into many files, and load from an S3 bucket in the **same Region**. **This works because** a bigger instance loads faster and several files let the load run in parallel. Resize back afterwards, and avoid repeated restarts.
- **If** you must export changes to S3 or OpenSearch continuously, **then** run a consumer that reads **Neptune Streams**. **This works because** Streams logs every graph change in strict order with no duplicates; there is no native trigger, so the consumer polls the stream's HTTP API.
- **If** a Region fails and you have **Neptune Global Database**, **then** **detach and promote** a secondary cluster to a standalone primary (unplanned); for planned moves such as maintenance, use **managed planned failover**. **This works because** secondaries already hold a storage-level copy, and managed failover moves the primary with **no data loss**.
- **If** an upgrade fails with a rollback, **then** check **`UndoLogListSize`**, scale up the writer so it purges faster, then retry. **This works because** only the writer purges the undo log, and before upgrading to **1.2.0.0+** this value must be under about **40k** (4xlarge and larger) or **10k** (smaller), or the upgrade rolls back.
- **If** an auditor asks "who can query?", **then** show the **Identity and Access Management (IAM)** policies, including **query-action condition keys**, plus **AWS CloudTrail** for API calls and Neptune **audit logs** (verify). **This works because** Neptune has no users or passwords: access is controlled by IAM with SigV4-signed requests.

## Verified from AWS docs on 2026-10-02
Read: best practices index, CloudWatch metrics page, storage types page, auto scaling page, Serverless capacity page, limits page, Global Database page, pricing summary. Not confirmed (verify): default query timeout, Performance Insights support, stop/start maximum duration, reserved instances availability, Database Savings Plans terms for Neptune, audit log availability, exact queue and throttling error codes, paused Neptune Analytics price.

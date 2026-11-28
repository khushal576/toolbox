# Neptune – 1. What it is, graph models, query languages, cluster architecture, endpoints, instance types, Serverless, Analytics

Short notes. Each point is a fact you can be asked about.

## A. What it is (verified)
- **Amazon Neptune** is a fully managed **graph database**. It stores **relationships** as first-class data and queries them in **milliseconds**, even across billions of relationships.
- Built for **highly connected data**: recommendations, fraud detection, knowledge graphs, drug discovery, network/IT security, social networks, identity graphs, Customer 360.
- Supports three open query languages:
  - **Apache TinkerPop Gremlin** (property graph)
  - **openCypher** (property graph)
  - **SPARQL** (RDF graph, W3C standard)
- Managed: provisioning, patching, backups, failover, scaling of storage.
- **VPC-only** service. No public access. Port **8182**.
- Designed for more than **99.99% availability**.
- Storage is shared, replicated 6 ways across 3 AZs, and grows automatically (Aurora-like design).
- It is **not** a SQL database. You do not use JOINs; you **traverse** relationships.

## B. Why a graph database (exam reasoning)
- In SQL, "friends of friends of friends" needs many self-JOINs. They get slow as depth grows.
- In a graph, you **follow edges** directly. Cost depends on the neighborhood you touch, not on the total table size.
- Use a graph when the **questions are about relationships**: shortest path, who is connected to whom, common neighbors, patterns/rings, influence.
- Do not use a graph for simple key lookups (DynamoDB), reporting (Redshift), or document storage (DocumentDB).
- Typical exam phrases → Neptune: "relationships", "highly connected", "social network", "fraud ring", "knowledge graph", "recommendation by connections", "SPARQL", "Gremlin", "RDF".

## C. Graph models (verified)
- **Property graph (PG)**:
  - **Vertex (node)** = an entity (person, account, product). Has a **label** and **properties** (key-value).
  - **Edge (relationship)** = a directed connection between two vertices (FOLLOWS, BOUGHT). Has a label and properties.
  - Query with **Gremlin** and/or **openCypher** (same graph can be queried by both).
- **RDF (Resource Description Framework)**:
  - Data = **triples**: subject – predicate – object (for example *Alice – knows – Bob*). Neptune stores **quads** (adds a **named graph**).
  - Query with **SPARQL**.
  - Good for **linked data, ontologies, knowledge graphs, standards-based data sharing**.
- Neptune's internal unit is a **quad (S, P, O, G)**. In RDF, G is the named graph. In Gremlin, G holds the edge ID for edges.
- A PG dataset and an RDF dataset are queried with their own languages. You cannot query PG data with SPARQL (and vice versa). Pick the model first. (verify mixing both models in one cluster)
- Unlimited vertices, edges and quads. No limit on properties or labels per element.
- One property value or label can be up to **55 MB**. For bigger objects (images) store them in **S3** and keep the path as a property.
- Strings cannot contain **null characters**.

## D. Query languages: when to pick which
| Language | Model | Style | Use when |
|---|---|---|---|
| **Gremlin** | Property graph | Imperative traversal (step by step) | Developers like programming-style traversals; TinkerPop ecosystem |
| **openCypher** | Property graph | Declarative pattern matching (like SQL for graphs, `MATCH (a)-[:KNOWS]->(b)`) | Easiest to learn; teams coming from Neo4j or SQL |
| **SPARQL** | RDF | Declarative triple patterns | Semantic web, ontologies, standards data, linked data |
- Gremlin and openCypher can read the **same property graph** data.
- Neptune supports openCypher over **HTTPS** and **Bolt** protocol.
- Gremlin uses **WebSockets** (long-lived connections) or HTTP. SPARQL uses HTTP.
- Endpoints are paths under the same host/port: `/gremlin`, `/openCypher`, `/sparql` (verify exact path names).
- Neptune has differences from the TinkerPop standard (see "Gremlin implementation differences" page).
- Use **parameterized queries**, send Gremlin as **bytecode** (not strings) in Java, and reuse client objects. (best practices)
- Neptune ML and graph notebooks work with these languages.

## E. Transactions and query engine (partly verified)
- Neptune supports **ACID transactions** (verify exact isolation levels; documented as snapshot-style for reads and read-committed behavior for writes).
- Bulk loader is **non-ACID**.
- Neptune does not support **multiple concurrent queries in one openCypher transaction**.
- **DFE (Distributed Fabric Engine)**: query engine that speeds up openCypher and some Gremlin/SPARQL queries (engine details, verify).
- Neptune is **single-sharded by design**: one writer, shared storage. It does not shard the graph across many writers.
- **Writes go to one primary instance.** Reads can go to replicas.

## F. Cluster architecture (verified)
- **DB cluster** = **1 primary (writer) instance + up to 15 Neptune replicas (readers)** + one **cluster volume**.
- **Cluster volume**: shared by all instances. Stored on **NVMe SSD**, copies across **3 AZs in one Region** (six copies in total). Self-healing; disk failures repaired in background.
- Volume grows automatically up to **128 TiB** (64 TiB in China and GovCloud Regions).
- Replicas read the same storage, so **replication lag is small** (milliseconds) and adding replicas does **not copy data**.
- Billing is by **allocated storage (high water mark)**, not current used amount. (verify if newer versions shrink)
- **DB subnet group** must have subnets in **at least 2 AZs** (3 or more recommended).
- Failover target is chosen by **promotion tier** (0 highest priority to 15 lowest). More in file 2.
- Keep all instances in a cluster the **same class**. Different classes can cause replicas that can't keep up or perform differently after failover.
- Resize the writer by **creating a bigger replica and failing over** to it (best practice).

## G. Endpoints (verified)
- **Cluster endpoint** → always points to the **current primary**. Use it for **all writes** (and reads that must be on the primary). Survives failover (DNS updates).
- **Reader endpoint** → **round-robin of connections** across available replicas. Read-only (unless the cluster has no replicas, then it points to the primary).
- **Instance endpoint** → one specific instance. Use for fine-grained control.
- **Custom endpoint** → a group of instances you choose; **up to 5 per provisioned cluster**. Use to separate workloads (for example analytics replicas vs app replicas).
- Format: `<name>.cluster-<id>.<region>.neptune.amazonaws.com:8182`; reader uses `cluster-ro-`.
- **Neptune does not load balance queries.** The reader endpoint balances **connections** by changing DNS answers. After a connection is made, all its requests stay on that replica.
- Long-lived **WebSocket** connections stay on one replica → close and reconnect (re-resolve DNS) to rebalance.
- **Disable DNS caching** in clients/proxies, or failover and round robin will not work.
- To balance queries yourself, use **instance endpoints** and spread them in the app.
- Endpoints use **TLS**.

## H. Instance types and sizing
- Instance classes: memory-optimized **r5, r6g, r7g, r8g, r6i, r7i**, big-memory **x2g/x2iedn/x1e**, and **r5d / r6gd** (NVMe local disk, enables the **lookup cache**). Burstable **t3.medium / t4g.medium** for dev/test.
- Neptune no longer supports **R4**.
- Graph queries are **memory-hungry**: the buffer cache holds hot graph data. Choose memory first.
- Rule of thumb: if **BufferCacheHitRatio is below 99.9%** → bigger instance (more memory).
- **t3/t4g** are for dev/test only. Not supported in Neptune Global Database.
- **Lookup cache** (r5d, optional, needs local NVMe): caches property values for faster property lookups. Not compatible with Serverless.
- Instance family decides **max WebSocket connections** (small classes allow fewer).

## I. Neptune Serverless (verified)
- **On-demand autoscaling of compute.** Storage is unchanged.
- Capacity unit: **NCU (Neptune Capacity Unit) = 2 GiB memory + matching CPU/network**.
- Set **minimum and maximum NCUs** for the cluster: **min 1.0 NCU**, **max 128 NCUs**; smallest allowed max is **2.5**.
- Scales in **half-NCU** steps (as little as 0.5).
- A higher minimum helps it scale up faster (increments depend on current size). Too low a min or max can cause **timeouts** on memory-heavy queries.
- Max instance memory: **256 GB** (128 NCUs, similar to r6g.8xlarge).
- Use for: variable/spiky workloads, multi-tenant apps, new apps, dev/test, capacity-planning relief.
- Instance class value: `db.serverless`. You can change an instance between provisioned and serverless **without a new cluster**.
- **Mixed clusters** are allowed (for example a provisioned writer with serverless readers).
- **Promotion tiers**: readers in tiers **0 and 1** scale **with the writer** (ready for failover). Readers in tiers **2–15** scale **independently**. Low min capacity there can cause **replica lag**.
- Needs engine **1.2.0.1 or later**. Available in many (not all) Regions.
- Not compatible with the **lookup cache**.
- Can combine with **read-replica auto scaling**: set a high max NCU so serverless handles spikes; otherwise auto scaling adds unnecessary instances.
- Monitor: `ServerlessDatabaseCapacity` (NCUs now), `NCUUtilization` (% of max).

## J. Neptune Database vs Neptune Analytics (awareness)
| Topic | Neptune Database | Neptune Analytics |
|---|---|---|
| Purpose | **OLTP graph database**: serve apps, store graph durably | **Analytics engine**: analyze large graphs in memory |
| Storage | Disk cluster volume, 3 AZs | **Memory-optimized**, in-memory graph |
| Scale | Up to 100,000 queries/sec, HA, multi-Region | Tens of billions of relationships, fast analytics |
| Queries | Gremlin, openCypher, SPARQL | **openCypher** + built-in **graph algorithms** (verify languages) |
| Vectors | Not built in | **Vector search** inside graph traversals |
| Load from | Bulk loader (S3) | Neptune Database cluster/snapshot or **S3 / data lake** |
| Best for | Social, fraud alerts, Customer 360, online lookups | Data science, fraud investigation, recommendations, GraphRAG |
| Billing | Instances / NCU-hours, storage, I/O | **m-NCU** (memory-based); pause at lower cost |
- Neptune Analytics is for **investigation, exploration and data-science** workloads that need fast iteration. It "complements" Neptune Database.
- Typical flow: keep the system of record in Neptune Database → load into Analytics for heavy algorithms (PageRank, community detection, path-finding) and vector + graph (GraphRAG) retrieval.
- Neptune Analytics graphs can be loaded from **Amazon S3** (data lake) too.
- (verify) m-NCU sizes, supported algorithms list, and GraphRAG integration with Bedrock Knowledge Bases.

## K. Neptune vs other stores (decision lines)
- Relationships are the point → **Neptune**.
- Key-value / low-latency lookups → DynamoDB.
- Documents (JSON) → DocumentDB.
- Wide-column, Cassandra → Keyspaces.
- Relational with joins → RDS/Aurora (recursive CTEs can do small graph queries but don't scale on deep traversals).
- Search/text → OpenSearch. Neptune can send data to OpenSearch for full-text search.
- Ontology/semantic web → Neptune with RDF/SPARQL.
- Graph analytics on big data in memory → Neptune Analytics.

## L. Graph modeling hints
- Model **things as vertices**, **verbs as edges**. Use labels to separate types.
- Put properties on the element they describe. Use custom IDs when you will look up by ID often (better performance).
- Edges are directed, but you can traverse both ways. In openCypher prefer **directed** edges in queries (faster than bidirectional).
- Keep very high-degree "super nodes" in mind: they make traversals expensive.
- For RDF with many distinct predicates, enable the **OSGP index** (extra index) – best practice.

## Scenarios (if → then, because)
- **If** the question is "who is connected to whom through several hops" (for example friends of friends of friends), **then** use **Amazon Neptune**, a fully managed **graph database** that stores relationships as data. **This works because** a graph query **follows edges** (links) directly, so the cost depends on the part of the graph you touch, not on the total table size. In SQL the same question needs many self-JOINs that get slow as depth grows.
- **If** a team writes Neo4j Cypher queries today, **then** use **openCypher** on Neptune, a declarative pattern-matching language for property graphs (for example `MATCH (a)-[:KNOWS]->(b)`). **This works because** openCypher is the easiest Neptune language for teams coming from **Neo4j** or SQL, and Neptune accepts it over **HTTPS** and the **Bolt** protocol.
- **If** the data is linked open data or ontologies, **then** use the **Resource Description Framework (RDF)** model with the **SPARQL** query language. RDF stores data as triples: subject – predicate – object (for example *Alice – knows – Bob*). **This works because** Neptune supports these **W3C standards**, built for linked data, ontologies, knowledge graphs and standards-based data sharing. With many distinct predicates, enable the extra **OSGP index**.
- **If** the team prefers step-by-step, programming-style traversals, **then** use **Apache TinkerPop Gremlin**, an imperative property-graph language. **This works because** Gremlin builds the query one traversal step at a time and fits the TinkerPop ecosystem.
- **If** one app must read the same property graph with both Gremlin and openCypher, **then** this is allowed. **This works because** both languages query the **property graph** model, so they read the same data. The catch: property-graph data cannot be queried with SPARQL, and RDF data cannot be queried with Gremlin or openCypher.
- **If** you need to write data, **then** send it to the **cluster endpoint**. **This works because** this endpoint always points to the current **primary (writer)** instance, the only one that takes writes, and it follows the new primary after a failover through a DNS update.
- **If** many read clients need their load spread, **then** use the **reader endpoint**, which spreads **connections** round-robin across the replicas. For balance per **query**, use **instance endpoints** (one per instance) and spread queries in the app. **This works because** Neptune does **not** load balance queries: the reader endpoint only changes DNS answers, and all requests on one connection stay on the same replica.
- **If** a client keeps hitting one replica for hours, **then** close and reconnect so DNS is resolved again, and **disable DNS caching** in clients and proxies. **This works because** long-lived **WebSocket** connections (used by Gremlin) stay on one replica, and the reader endpoint balances only new connections by changing DNS answers. Cached DNS also stops failover and round robin from working.
- **If** load is spiky or unknown, **then** use **Neptune Serverless**, which scales compute on demand. You set a minimum and maximum in **Neptune Capacity Units (NCUs)**; one NCU is **2 GiB** memory plus matching CPU and network, from **1** to **128 NCUs**. **This works because** capacity moves in **half-NCU** steps with the load, while storage is unchanged. The catch: too low a minimum or maximum can cause **timeouts** on memory-heavy queries.
- **If** you need to run graph algorithms over **tens of billions** of relationships, **then** use **Neptune Analytics**, an analytics engine that loads the graph from a Neptune Database cluster, a snapshot or **Amazon Simple Storage Service (S3)**. **This works because** it keeps the graph **in memory** and has built-in algorithms (PageRank, community detection, path-finding). Neptune Database stays the system of record for the app.
- **If** the **`BufferCacheHitRatio`** metric (share of reads served from memory) is below **99.9%**, **then** scale up to a larger instance with more memory. **This works because** graph queries are memory-hungry: the buffer cache holds hot graph data, and a low hit ratio means the working set does not fit in memory.
- **If** a developer wants to store images on vertices, **then** store the images in **Amazon Simple Storage Service (S3)** and keep the S3 path as a property. **This works because** one property value can be at most **55 MB**, and big objects belong in S3.
- **If** you need SQL joins and reporting, **then** do not use Neptune; use **Amazon Aurora** (relational with joins) or **Amazon Redshift** (reporting). **This works because** Neptune is not a SQL database: it has no JOINs and is built to traverse relationships.

## Verified from AWS docs on 2026-10-02
Read: Neptune intro, features overview, data model, endpoints page, limits page, storage page summary, Serverless pages (overview and capacity scaling), Neptune Analytics vs Database page, best practices index. Not confirmed (verify): exact isolation levels, DFE engine details, endpoint path names, mixing PG and RDF in one cluster, 6-copy quorum numbers, whether billed storage shrinks, Neptune Analytics query languages/m-NCU sizes/GraphRAG details, high-degree node guidance.

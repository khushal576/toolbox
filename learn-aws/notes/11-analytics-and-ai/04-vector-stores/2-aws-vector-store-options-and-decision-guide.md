# Vector stores – 2. AWS options, limits, cost and decision guide

Short notes. Each point is a fact you can be asked about. (Concepts are in file 1. OpenSearch k-NN internals are also covered in `04-databases/08-opensearch`.)

## A. The options at a glance
| Option | Type | Where vectors live | Best for |
|---|---|---|---|
| **Amazon S3 Vectors** | Purpose-built vector storage | S3 (object storage) | Cheapest large, **infrequently queried** vector sets |
| **OpenSearch Service (managed)** | Search + vector engine | Cluster memory/disk | Hybrid search, filters, aggregations, **high QPS** |
| **OpenSearch Serverless (vector collection)** | Serverless search + vector | Managed (OCUs + S3) | Same, without cluster sizing |
| **Aurora / RDS PostgreSQL + pgvector** | Relational + vector | Table + index | Vectors **next to relational data**, SQL joins |
| **MemoryDB (vector search)** | In-memory Valkey/Redis-compatible | RAM | **Lowest latency**, semantic cache, real-time |
| **DocumentDB (vector search)** | JSON document DB | Collection + index | Existing document data, MongoDB-compatible apps |
| **Neptune Analytics (vector index)** | Graph + vector | In-memory graph | **GraphRAG**, relationships + similarity |
| **Bedrock Managed Knowledge Base** | Managed RAG store | AWS-managed | No vector DB to run |
| **Kendra GenAI index** | Managed enterprise search | AWS-managed | Connectors + ACLs, little tuning (see Kendra notes) |
| **Third-party (Pinecone, Redis Cloud, MongoDB Atlas)** | External SaaS | Vendor | Existing vendor standard; supported by Bedrock KB |
- **Also possible**: **DynamoDB** with **zero-ETL to OpenSearch** (vectors in OpenSearch, source of truth in DynamoDB); **Redshift** and **Athena** for analytics over embeddings (not low-latency ANN stores) **(verify any native vector features)**; **Aurora DSQL** and others **(verify)**.
- **Bedrock Knowledge Bases (customer-managed) can use**: OpenSearch Serverless, OpenSearch managed, **S3 Vectors**, Aurora PostgreSQL, Neptune Analytics (GraphRAG), Pinecone, Redis Enterprise Cloud, MongoDB Atlas. (**Not** MemoryDB or DocumentDB directly.)

## B. Amazon S3 Vectors
- **What**: a new **bucket type** (**vector bucket**) with **vector indexes** inside. Similarity search through dedicated APIs (`PutVectors`, `QueryVectors`, `GetVectors`, `ListVectors`, `DeleteVectors`).
- **Performance**: **sub-second** for infrequent queries, **as low as ~100 ms** for frequent queries. Not for very high QPS.
- **Durability/elasticity** like S3. **Strongly consistent writes** (you can query what you just wrote). Automatically optimizes the index as data changes. **No infrastructure to provision.**
- **Security**: own **`s3vectors`** IAM namespace; resource policies on bucket/index; **SCPs**; **S3 Block Public Access always on** (cannot be disabled). Encryption **SSE-S3 (default) or SSE-KMS**; the type is fixed at bucket creation (index-level override possible). Tags up to 50 per index.
- **Metadata**: string, number, boolean, **list**; **filterable by default**; mark keys **non-filterable** at index creation (max **10** such keys). Supports `ENHANCED` index filtering with up to **100** filter constraints **(verify details)**.
- **Distance**: **cosine** or **Euclidean**; **float32 only** (no binary).
- **Limits** (docs): **10,000 vector buckets** per Region; **10,000 indexes** per bucket; **up to 2 billion vectors per index**; **1–4,096 dimensions**; **metadata total 40 KB/vector** and **up to 50 keys**, **filterable metadata up to 2 KB**; **PutVectors up to 500 vectors/call**, **GetVectors up to 100**; **TopK up to 10,000**; **1,000 Put/Delete requests per second per index**, **2,500 vectors inserted/deleted per second per index**; request payload **20 MiB**.
- **Bedrock KB limits are tighter**: with KBs, custom metadata is about **1 KB and 35 keys per vector** (hierarchical chunking/context can exceed it → ingestion errors). Set `AMAZON_BEDROCK_TEXT` and `AMAZON_BEDROCK_METADATA` as **non-filterable** keys. `startsWith`/`stringContains` filters are not supported.
- **Cost (pricing page excerpts, us-east-1 style)**: **storage about $0.06/GB-month**; **PUT about $0.20 per logical GB uploaded**; **query API about $2.50 per million**; plus **query data processed per TB** (tiered by vector count: about **$0.004 / $0.002 / $0.0004 per TB** for the first 100K, 100K–10M, 10M+ vectors) **(verify)**.
- **Integrations**: **Bedrock Knowledge Bases**, **SageMaker Unified Studio**, **OpenSearch** (use S3 Vectors to cut vector storage cost while keeping OpenSearch APIs for hybrid search/aggregations; **export a snapshot to OpenSearch Serverless** for high QPS/low latency).
- **Pick it** when: large corpus, low/medium QPS, cost is the main driver, RAG archives, media similarity, dedup. **Avoid** when: you need hybrid keyword+vector in one query, aggregations/faceting, or thousands of QPS with single-digit ms.
- **Pattern**: S3 Vectors for the **cold/bulk** index + **OpenSearch** for the **hot** subset.

## C. Amazon OpenSearch Service and Serverless
- **Strengths**: **hybrid search** (BM25 + vector), rich **filters and aggregations**, **neural search**, scale, many engines (Faiss, Lucene, NMSLIB), **binary/quantized/disk-optimized** modes, multimodal.
- **Managed domains**: you choose instances, storage, shards, **memory** (HNSW graphs are off-heap: about **25% of instance RAM** is practical graph space with default settings, per existing notes), **UltraWarm/cold** for old k-NN indexes. **VPC or public**.
- **Serverless (vector search collection)**: auto-scaling **OCUs** (indexing + search + S3 storage); data access, encryption, network policies; **minimum OCUs** keep a baseline cost even when idle **(see OpenSearch notes)**.
- **GPU-accelerated and auto-optimized vector indexes** (announced Dec 2025): GPU workers speed up **index builds** (benchmarks: about **6–14x** faster) and are billed separately for indexing (OCU for vector acceleration); available in **OpenSearch 3.1+** domains and vector collections in a few Regions **(verify)**. Auto-optimization tunes recall/latency/cost trade-offs.
- **Bedrock KB**: needs **faiss**; managed domain **must be public** (no VPC domains); **binary vectors** only here; best **metadata filter** support.
- **Pick it** when: you need **hybrid + filters + aggregations**, high QPS, or an existing OpenSearch platform. Watch **cost** (always-on nodes or min OCUs) and **memory**.

## D. Aurora and RDS PostgreSQL with pgvector
- **pgvector** is a Postgres extension: `vector` type, distance operators (**L2 `<->`, inner product `<#>`, cosine `<=>`**, plus L1/Hamming/Jaccard in newer versions), indexes **HNSW** and **IVFFlat**.
- **HNSW needs pgvector 0.5.0+**. **0.8.0** adds **iterative index scans** (`hnsw.iterative_scan`, `hnsw.max_scan_tuples` default **20,000**) so **selective filters** do not return too few rows, plus faster HNSW search/build. 0.8.0 is on Aurora PostgreSQL **16.8, 15.12, 14.17, 13.20 and higher** **(verify RDS versions)**.
- **Index dimension limits (pgvector)**: **`vector` up to 2,000 dims indexed**, **`halfvec` up to 4,000**; a `vector` column can store more (docs for another store note 16,000 unindexed) **(verify for Aurora)**.
- **Bedrock KB on Aurora** needs: Aurora PostgreSQL **16.1+, 15.4+, 14.9+, 13.12+, 12.16+**, pgvector **0.5.0+**, **RDS Data API enabled**, a **Secrets Manager** secret; table with `id` (uuid), `embedding` (vector), `chunks` (text), `metadata` (json), optional `custom_metadata` (jsonb); indexes: HNSW (`vector_cosine_ops`; **`ef_construction=256`** recommended with parallel builds on 0.6.0+), GIN on `to_tsvector('simple', chunks)` for hybrid, GIN on `custom_metadata`.
- **Hybrid search** is easy: combine `tsvector` full-text rank with vector distance in one SQL query.
- **Why choose it**: **one database** for transactions + vectors, **SQL joins and filters**, ACID, row-level security, existing backups/HA/IAM auth, **Aurora Serverless v2** scaling.
- **Limits**: HNSW indexes are **memory-hungry** (keep the working set in RAM); big builds are slow; scaling is **vertical + read replicas** (no sharding built in); very large corpora (hundreds of millions of vectors) strain a single cluster.
- **Cost**: instance/ACU + storage + I/O (Aurora I/O-Optimized can help). No per-query fee.
- **Also**: **Aurora ML / `aws_ml` / `aws_bedrock`-style integrations** can call embedding models from SQL **(verify current extension names)**.
- **Pick it** when: data is already relational, moderate scale (millions to tens of millions of vectors), strong consistency, SQL filters/joins matter.

## E. MemoryDB (vector search)
- **Valkey/Redis OSS-compatible**, **durable** (multi-AZ transaction log) in-memory database with vector search. **Highest throughput and lowest latency**; AWS states fastest vector search at high recall among popular AWS options (as of 26 Jun 2024).
- **Use cases**: **semantic caching of LLM answers**, real-time recommendations, anomaly/fraud detection, RAG with tight latency, session memory for agents.
- **Index types**: **FLAT** (exact) and **HNSW**; metrics **L2, inner product, cosine**; also tag/numeric/text filters (`FT.CREATE`, `FT.SEARCH`, `FT.AGGREGATE`).
- **Limits** (docs): vectors up to **32,768 dimensions**; **10 indexes**; **50 fields per index**; HNSW `M` ≤ 512, `EF_CONSTRUCTION` ≤ 4,096, `EF_RUNTIME` ≤ 4,096; search timeout ≤ 10,000 ms.
- **Constraints**: vector search is **single shard only** (no horizontal scaling; scale **vertically and with replicas**); supported on **R6g, R7g, T4g** nodes; **existing clusters cannot be modified** to enable search (create a new one, optionally **from a snapshot**); snapshots with search indexes only import into another vector-enabled MemoryDB.
- **Operations**: after restarts the index **backfills** (search may be rejected during backfill; primary and replicas finish at different times, so **check backfill on all nodes**). If memory fills during backfill, backfills **pause**. `FT.CREATE` cannot run in MULTI/EXEC or scripts.
- **Memory sizing**: depends on **vector count, dimensions, M, and other data**; console has a **vector calculator** (docs example: 10M vectors × 1,536 dims, M=16 → about **105 GB** → `db.r7g.4xlarge`).
- **Pick it** when: latency and QPS dominate and the vector set **fits in RAM** on one shard. **Avoid** for huge, cost-sensitive corpora (RAM is expensive).

## F. DocumentDB (vector search)
- **MongoDB-compatible** JSON store. Vector search on **DocumentDB 5.0+ instance-based clusters** (the `$vectorSearch` stage arrives with **8.0**).
- **Indexes**: **HNSW** (default from engine patch 3.0.4574; params `m` default 16 [2–100], `efConstruction` default 64 [4–1000, ≥ 2×m]; search `efSearch` default 40 [1–1000]) and **IVFFlat** (`lists`; **recommended lists = docs/1,000 up to 1M docs, sqrt(docs) beyond**; `probes` start near sqrt(lists); max `lists` depends on instance size and dimensions).
- **Similarity**: **euclidean, cosine, dotProduct**.
- **Dimensions**: **index up to 2,000**; store up to **16,000** without an index.
- **No index = exact nearest-neighbor search (perfect recall)**. Adding an index can change results.
- **Restrictions**: no compound, sparse or partial options on vector indexes; **no parallel HNSW build in 5.0**; load some data **before** building IVFFlat.
- **Pick it** when: your operational data is already in DocumentDB and you want vectors in the same documents. Not a Bedrock KB store.

## G. Neptune Analytics (vector index and GraphRAG)
- **In-memory graph analytics** engine with **one vector index per graph**, **dimension fixed at graph creation (1–65,535)**. Capacity in **m-NCUs** (about 1 GiB memory each).
- **Combine graph traversal with vector similarity** (for example find similar chunks, then walk related entities). That is **GraphRAG**; Bedrock KB supports it.
- **Embeddings** attach to nodes (a node needs a label or property): load from CSV (`embedding:vector`, semicolon-separated) or `neptune.algo.vectors.upsert`. Not every node needs an embedding.
- **Caveat**: vector updates are **not atomic or isolated**; a failed bulk load can leave partial embeddings → make updates **idempotent**, avoid concurrent updates to the same vertex, do vector updates in **simple separate queries**.
- No loading vectors from Neptune Database/snapshot. Mismatched dimension → `ParsingException`.
- **Pick it** when: relationships matter (knowledge graphs, fraud rings, supply chain) alongside similarity.

## H. Decision guide
| Need | Pick |
|---|---|
| Cheapest at huge scale, queries rare | **S3 Vectors** |
| Hybrid keyword + vector, filters, aggregations, high QPS | **OpenSearch (managed or Serverless)** |
| Vectors beside relational data, SQL joins | **Aurora/RDS PostgreSQL pgvector** |
| Lowest latency, semantic cache, real-time, fits in RAM | **MemoryDB** |
| Data already in JSON documents (MongoDB API) | **DocumentDB** |
| Entities and relationships + similarity | **Neptune Analytics** |
| No store to operate, RAG focus | **Bedrock Managed Knowledge Base** |
| Enterprise search with connectors and per-user ACLs | **Kendra / Amazon Q Business** |
| Existing vendor standard | **Pinecone / Redis Cloud / MongoDB Atlas** (Bedrock KB supports them) |
- **Scale rule of thumb** (approximate): thousands to low millions → pgvector or OpenSearch; tens of millions → OpenSearch, pgvector with big instances, MemoryDB if RAM allows; hundreds of millions to billions → **OpenSearch with quantization/GPU build, S3 Vectors** **(verify per use case)**.
- **Cost rule of thumb**: **S3 Vectors** (pay per use) < **pgvector** (shared with an existing DB) < **OpenSearch Serverless** (min OCUs) ≈ **OpenSearch managed** < **MemoryDB** (RAM). Latency is the opposite order.
- **Hot/cold pattern**: recent or popular vectors in **OpenSearch/MemoryDB**, the long tail in **S3 Vectors**.
- **Semantic cache pattern**: MemoryDB stores (question embedding → answer); on a close match, skip the LLM call (saves tokens and latency).
- **Source of truth**: keep original documents in **S3**; vector stores are **rebuildable indexes**. Store the embedding model + chunking version in metadata.

## I. Operations, security and cost (shared)
- **Security**: KMS encryption; **VPC/PrivateLink** where supported; IAM (S3 Vectors `s3vectors:*`, OpenSearch data access policies, Aurora IAM auth/Secrets Manager, MemoryDB ACLs); **row/doc-level filters** for tenants; audit with **CloudTrail**; delete vectors when source data is deleted.
- **Monitoring**: OpenSearch `KNNGraphMemoryUsage`, search latency, indexing rejections; Aurora CPU, buffer cache hit ratio, `pg_stat_statements`; MemoryDB memory, engine CPU, backfill status; S3 Vectors request metrics; app-level **recall and latency** tests.
- **Cost levers**: smaller dimensions (512/256), **quantization/binary**, fewer/better chunks, drop unused indexes, S3 Vectors for cold data, right-size memory, schedule/scale Serverless, delete test collections.
- **Backups**: OpenSearch snapshots; Aurora backups/PITR; MemoryDB snapshots + multi-AZ log; DocumentDB backups; S3 Vectors durability (S3-class) but plan **re-embedding** from source as recovery.
- **Migration**: moving stores means **re-creating the index** (vectors can be exported and re-imported if the model and dimension stay the same). Changing models means **re-embedding**.

## J. Scenarios: "If X → Y, because Z"
- **If** you have **500 million** document chunks, they are searched only a few times per minute, and cost matters, **then** use **Amazon S3 Vectors**, a special S3 **vector bucket** with vector indexes inside. **This works because** you pay for storage (about **$0.06/GB-month** (verify)) and per query, with no cluster to run, and queries return in **sub-second** time (as low as **~100 ms** for frequent queries). One index holds **up to 2 billion vectors**. The catch: it is not for very high queries per second (QPS) and has no hybrid keyword search.
- **If** users type queries that mix **product codes** and natural language, **then** use **Amazon OpenSearch Service hybrid search**. **This works because** OpenSearch combines **BM25** keyword matching (good for exact codes) with **vector** similarity (good for meaning) in one query, plus rich **filters and aggregations**. Watch cost (always-on nodes or minimum capacity units) and memory.
- **If** the product catalog and orders already live in **Amazon Aurora** and you need "similar items in stock under $50", **then** use **Aurora PostgreSQL with pgvector** (a Postgres extension that adds a `vector` type and **HNSW**/**IVFFlat** indexes) plus normal **SQL filters**. **This works because** one database holds both the relational data and the vectors, so a single SQL query can join, filter and rank by similarity with no sync to another store. Limit: HNSW indexes are memory-hungry and scaling is vertical plus read replicas.
- **If** selective filters return too few rows in pgvector, **then** **upgrade to pgvector 0.8.0** and **enable iterative index scans** (`hnsw.iterative_scan`). **This works because** otherwise the filter is applied after the HNSW scan, so a strict filter removes most candidates; iterative scans keep scanning (up to `hnsw.max_scan_tuples`, default **20,000**) until enough rows pass. 0.8.0 is on Aurora PostgreSQL **16.8, 15.12, 14.17, 13.20** and higher **(verify RDS versions)**.
- **If** a chatbot must return cached answers to near-duplicate questions in milliseconds, **then** use **Amazon MemoryDB vector search as a semantic cache**: store question embedding → answer, and on a close match skip the large language model (LLM) call. **This works because** MemoryDB is an **in-memory**, **durable** (Multi-AZ transaction log) Valkey/Redis-compatible database with the lowest latency, and skipping the LLM saves tokens and time.
- **If** you must scale vector search beyond one **MemoryDB** shard, **then** **choose another store**, such as **Amazon OpenSearch Service**. **This works because** MemoryDB vector search is **single shard only**: it scales only **vertically and with replicas**, so the whole vector set must fit in one shard's RAM.
- **If** your app already stores JSON in **Amazon DocumentDB** (MongoDB-compatible) and wants recommendations, **then** add a **DocumentDB HNSW vector index** (on DocumentDB **5.0+** instance-based clusters). **This works because** the vectors live in the **same documents** as the operational data, so there is no second store to sync. Note: DocumentDB is not a Bedrock Knowledge Base store.
- **If** answers must follow relationships (for example supplier → part → product), **then** use **Amazon Neptune Analytics GraphRAG**. Neptune Analytics is an in-memory graph engine with **one vector index per graph**. **This works because** it combines **graph traversal** with **vector similarity**: find similar chunks, then walk the related entities. Amazon Bedrock Knowledge Bases support it.
- **If** you want retrieval-augmented generation (RAG) with no database to manage, **then** use an **Amazon Bedrock Managed Knowledge Base**. **This works because** AWS runs the vector store for you, so there is no vector database to operate and you focus on RAG.
- **If** an **Amazon Bedrock Knowledge Base** must use **binary embeddings** (1 bit per dimension, about **32x** less storage but less precise), **then** use **Amazon OpenSearch** as its vector store. **This works because** among Knowledge Base stores, only OpenSearch supports binary vectors.
- **If** **S3 Vectors** ingestion fails in a Bedrock Knowledge Base that uses **hierarchical chunking**, **then** the custom metadata is probably over the Knowledge Base limit of about **1 KB and 35 keys per vector**; reduce the chunk context or switch chunking strategy, and set `AMAZON_BEDROCK_TEXT` and `AMAZON_BEDROCK_METADATA` as **non-filterable** keys. **This works because** Knowledge Bases apply tighter limits than raw S3 Vectors (**40 KB** metadata, **2 KB** filterable).
- **If** an auditor asks you to delete a customer's data, **then** **delete the source data and its vectors** (by ID or filter) and verify. **This works because** embeddings are made from the source data and may still reveal sensitive information, so they must be deleted with it.
- **If** you changed the **embedding model**, **then** **build a new index and re-embed** everything from the source (keep originals in **S3**). **This works because** old and new vectors are not comparable. Storing the model and chunking version in metadata shows which vectors are from which model.

Verified from AWS docs on 2026-11-01 (S3 Vectors overview and limitations, MemoryDB vector search limits, DocumentDB vector search, Aurora PostgreSQL pgvector KB page, Neptune Analytics vector index, Bedrock KB vector store prerequisites, S3 pricing excerpt; pgvector 0.8.0 on Aurora and OpenSearch GPU-acceleration announcements via search).
Unconfirmed (verify): S3 Vectors pricing numbers and `ENHANCED` index details; Aurora/RDS version lists for pgvector 0.8.0; pgvector dimension limits on Aurora; native vector features in Redshift/Athena/Aurora DSQL; Aurora ML extension names; OpenSearch GPU acceleration Regions and the S3 Vectors integration details (snapshot export, engine option); the 25% graph-memory rule of thumb (from earlier OpenSearch notes); scale guidance by corpus size; whether MemoryDB/DocumentDB can be Bedrock KB stores (docs list says no).

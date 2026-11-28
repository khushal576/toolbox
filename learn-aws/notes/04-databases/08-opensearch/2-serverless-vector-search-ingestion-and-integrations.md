# OpenSearch – 2. Serverless, vector search (k-NN), ingestion pipelines, loading data and integrations

Short notes. Each point is a fact you can be asked about.

## A. OpenSearch Serverless (verified)
- **On-demand, serverless** option: no domains, nodes, shards, versions or capacity planning.
- Unit of organization = **collection**: a group of indexes for one workload.
- **Architecture**: indexing compute and search compute are **separate** and scale **independently**. Index data lives in **Amazon S3**. Search nodes pull data from S3 (cache locally).
- Compute is measured in **OCU (OpenSearch Compute Unit)** = **6 GiB memory** + vCPU + transfer to S3. OCUs are provisioned **separately for indexing and search**.
- Scales out and back automatically. You set **min and max OCUs** per **collection group**, separately for indexing and search.
  - Min can be **0** (no cost when idle, but cold-start delay). A higher min avoids cold start.
  - Max is a **budget cap**. Per collection group max **1,700 OCUs** each for indexing and search. Valid values: 2, 4, 8, 16 or multiples of 16.
- High availability by default (no standby nodes to configure).
- Collections in one **collection group** share OCUs (pooling = cost efficiency). A group holds only one collection type.
- **Classic collections** (no collection group): capacity set at **account level**; OCUs shared if they use the same KMS key. Each OCU has **120 GiB** hot ephemeral storage; up to **10 TiB** managed hot storage per collection; max **1,000 indexes** per collection.
- **Collection types** (choose at creation, cannot change):
  - **Time series**: logs/metrics; hot + warm storage (recent data hot). Classic collections only. Cannot index with custom document ID or upsert (update by ID is OK).
  - **Search**: full-text search; all data hot. No k-NN indexes.
  - **Vector search**: embeddings/semantic search for GenAI (chatbots, RAG, fraud). All data hot.
- Refresh interval about **10 seconds**. Shards, intervals and refresh are managed for you (not modifiable).
- Compatible with OpenSearch APIs; clients must work with OpenSearch **3.x**; some APIs/plugins are **not supported**; **no custom plugins**.
- Limits (verified):
  - No automatic migration from a domain → **reindex** into a collection.
  - **No cross-account** access to collections. **No cross-Region search or replication.**
  - **Manual snapshots not supported**; **automated snapshots supported**.
  - Sign requests with service name **`aoss`** (domains use `es`); the **`x-amz-content-sha256`** header is required.
  - Automatic upgrades to new OpenSearch versions.
  - Available only in a subset of Regions.
- Billing: **OCU-hours for indexing + OCU-hours for search + S3 storage** (usage types `ServerlessOCU`).
- Monitor: `SearchOCU`, `IndexingOCU` (account-level CloudWatch metrics). Alarm near limits.

### Serverless security (verified)
- Three policy types, all attached by **collection name or wildcard pattern**:
  1. **Encryption policy**: required. Chooses **AWS owned key** or **customer managed KMS key**. Must exist before the collection is created. Encryption at rest is always on.
  2. **Network policy**: **public** or **private** access. Private = via **OpenSearch Serverless-managed VPC endpoints** (PrivateLink) or **AWS service private access** (for example Amazon Bedrock). Separate settings for the **collection endpoint** and the **Dashboards endpoint**. Private service access cannot apply to Dashboards.
  3. **Data access policy**: rules with **resource type (collection/index)**, **granted resources** (names/wildcards), **permissions** (`aoss:*` etc.), and **principals** (IAM users/roles, **SAML** identities).
- A collection needs all three (encryption key, network access, matching data access policy) to work.
- Authentication: **IAM** (SigV4) and **SAML** (configured at account level).
- No fine-grained access control plugin; **data access policies replace it**.
- Dashboards login: if you are in the AWS console, you are logged in automatically.
- Control plane can also use PrivateLink.
- TLS 1.2 required, 1.3 recommended.

## B. Domains vs Serverless (verified)
| Topic | Provisioned domain | Serverless |
|---|---|---|
| Unit | Domain (cluster) | Collection |
| Capacity | You pick instances, storage, shards | **Auto-scaling OCUs**, no shards to manage |
| Billing | Instance hours + EBS | **OCU-hours + S3** |
| Encryption at rest | Optional | **Required** |
| Data access | IAM policies + fine-grained access control | **Data access policies** |
| Network | VPC or public (fixed at creation) | Network policies, VPC endpoints |
| Versions/updates | You upgrade | **Automatic** |
| Manual snapshots | Yes | **No** (automated only) |
| Plugins | Supported list + custom packages | Limited, no custom plugins |
| Cross-cluster features | Cross-cluster search/replication (verify) | **Not supported** |
| Best for | Predictable, tunable workloads; most features | Spiky/unknown load; low ops; GenAI vector apps |

## C. Vector search with k-NN (verified + notes)
- **k-NN** plugin finds the **k nearest neighbors** of a query vector by **Euclidean distance** or **cosine similarity** (and other spaces – verify list).
- Use cases: **semantic search, RAG for GenAI, recommendations, image similarity, fraud/anomaly detection**.
- Create an index with `"index.knn": true` and a field of type **`knn_vector`** with a `dimension`.
- Query with the `knn` query type. `k` is neighbors per shard-segment unless you also set `size`; **always set `size`**. Max `k` = **10,000**.
- Adding other query clauses (filters) can return **fewer than k** results (post-filter reduces results).
- The doc page states a `knn_vector` holds up to **10,000 floats** (limit may differ by engine/version; verify current maximum, newer engines allow more).
- **Index types / algorithms** (exam skill 2.1.8, partly verify):
  - **HNSW** (Hierarchical Navigable Small World): graph-based approximate search. Fast, high recall, **uses lots of memory** (graph kept in memory).
  - **IVF** (Inverted File): clusters vectors and searches nearest clusters. Needs a **training step**; less memory than HNSW; recall depends on clusters probed.
  - **Exact k-NN** (brute force / script score): accurate but slow; fine for small sets or filtered subsets.
  - Engines: **Faiss**, **NMSLIB**, **Lucene** (HNSW in Lucene; supports filtering inside the search; no separate off-heap graph).
  - Quantization / compression options (byte, binary, product quantization, disk-optimized mode) cut memory (verify names).
- **Memory rule**: graphs are stored **off-heap**. JVM heap = 50% of RAM; k-NN by default may use **50% of the remaining half**. A 32 GiB-RAM instance holds about **8 GiB of graphs** (32 × 0.5 × 0.5). Beyond that, performance drops.
- Watch CloudWatch metric **`KNNGraphMemoryUsage`** against `knn.memory.circuit_breaker.limit`.
- You can change all k-NN settings via `_cluster/settings` **except** `knn.memory.circuit_breaker.enabled` and `knn.circuit_breaker.triggered`.
- k-NN indexes can move to **UltraWarm/cold** (domain 2.17+; k-NN indexes created before 2.x cannot). Prefer Lucene engine or disk-optimized mode for warm; Faiss/NMSLIB need off-heap memory in warm nodes (use `uw.large`, not medium). k-NN indexes are not force-merged to one segment on migration (default 20 segments) to avoid OOM.
- Use `_msearch` for many vector queries in one call.
- **Hybrid search** = combine keyword (BM25) and vector scores. **Neural search** = built-in model that creates embeddings at ingest/query time (verify availability and models).
- Embeddings are created outside (Bedrock Titan, SageMaker, etc.) or via ML Commons/neural plugin. Model dimension (for example 1,536 for Titan) must match the field dimension.
- Serverless: **vector search collection** type is the managed way.
- Compare vector stores:
  - **OpenSearch**: large scale, keyword + vector hybrid, many algorithms.
  - **Aurora PostgreSQL pgvector**: relational data + vectors, HNSW/IVFFlat.
  - **MemoryDB**: fastest, memory-bound, single shard.
  - **DocumentDB**: vectors beside JSON documents.
  - **Neptune Analytics**: vectors + graph traversal.
  - **Bedrock Knowledge Bases** can use OpenSearch Serverless as a vector store.

## D. Index lifecycle: ISM, rollups, replication (verified + notes)
- **Index State Management (ISM)** automates index operations through **policies** made of **states**, **actions**, and **transitions** (conditions like `min_index_age`, `min_doc_count`, `min_size`).
- Requires OpenSearch or Elasticsearch **6.8+**.
- Job runs about **every 5–8 minutes** (30–48 on pre-1.3) with jitter. **ISM does not run when cluster status is red.**
- Apply policies with `POST _plugins/_ism/add/<index>` or an **`ism_template`** field in the policy (matches new index names). **Index templates can no longer attach ISM policies.**
- Standard actions: `rollover`, `delete`, `force_merge`, `read_only`, `replica_count`, `snapshot`, `open`, `close`, `notification`, `transition`.
- Service-specific actions: **`warm_migration`** (hot → UltraWarm), **`cold_migration`**, **`cold_delete`**.
- Typical log policy: **hot → warm (e.g., 10 days) → cold (e.g., 90 days) → delete (e.g., 365 days)**.
- Cold indexes need a **`timestamp_field`** and ISM calls with `?type=_cold`.
- Settings you may change on the service: only `plugins.index_state_management.enabled` and `…history.enabled`, plus the index-level `rollover_alias`.
- **Rollover** creates a new index when the current one hits a size/age/doc-count threshold → keeps shards in the right size band.
- Other automation (verify availability): **index rollups**, **transforms**, **Snapshot Management**, **cross-cluster replication** (active-passive follower indexes), **cross-cluster search**, **alerting**, **anomaly detection**.

## E. Getting data in: options and choice (verified + notes)
- **Amazon OpenSearch Ingestion** (managed **Data Prepper**): serverless pipelines that collect, filter, enrich, transform and deliver to domains/collections. Replaces Logstash/Jaeger.
  - Billed by **Ingestion OCUs** allocated to the pipeline, whether data flows or not. You can **stop/start** pipelines to save money.
  - Auto-scales between min and max OCUs you set.
  - Can run **inside a VPC**. Patched automatically. Blueprints for common use cases. CloudWatch metrics and CloudWatch Logs.
  - Currently Data Prepper **2.x** (pipeline config needs `version: "2"`). Minor upgrades happen when you update the pipeline.
  - Typical sources (verify): **S3** (with SQS notifications), **Kinesis Data Streams**, **DynamoDB** (full export + streams), **DocumentDB**, **HTTP/OTLP** (logs, traces, metrics from OpenTelemetry), **Kafka/MSK**, **Fluent Bit**.
  - Typical sinks: OpenSearch domain, OpenSearch Serverless collection, S3 (dead-letter).
- **Amazon Data Firehose** → OpenSearch domain or Serverless collection. Buffers and batches; can back up **failed or all documents to S3**; can transform with Lambda. Good for streaming logs with no code.
- **Kinesis Data Streams** → Lambda → OpenSearch (custom transformation).
- **DynamoDB Streams** → Lambda → OpenSearch (keep search index synced) or **DynamoDB zero-ETL integration** via OpenSearch Ingestion (managed, verify details).
- **S3 → Lambda (on object created) → OpenSearch** for files/logs.
- **CloudWatch Logs subscription** → Lambda or Firehose → OpenSearch. (Console offers a one-click subscription.)
- **IoT rules**, **Logstash/Beats/Fluent Bit** agents, **OpenSearch Bulk API** from apps/EMR/Glue (use the OpenSearch connector).
- **Neptune Streams** → OpenSearch for graph full-text search (see Neptune).
- **DocumentDB / Aurora / DMS**: replicate relational/document data into OpenSearch via DMS or zero-ETL (verify current support).
- **Zero-ETL integrations** (verify each): DynamoDB, S3 (**direct query** of S3 data without copying), CloudWatch Logs, Security Lake.
- **Bulk API** is the efficient way to index: batch docs, 5–15 MB per request; avoid one-doc-per-request.
- Max HTTP request payload: **10 MiB** on smaller instances (t2/t3, large sizes) and **100 MiB** on larger ones.
- Choice guide:
  - Streaming logs, no code → Firehose.
  - Need transformation, enrichment, routing, OTel traces → OpenSearch Ingestion.
  - Custom logic on events → Lambda.
  - Keep a DynamoDB table searchable → zero-ETL/OpenSearch Ingestion or DynamoDB Streams + Lambda.
  - Query S3 data without copying → direct query (zero-ETL) or Athena.

## F. Other features worth naming
- **OpenSearch Dashboards**: visualizations, dashboards, Discover, Dev Tools, **multi-tenancy** with fine-grained access control.
- **SQL and PPL** plugins: query with SQL (BI tool integration via JDBC/ODBC; verify). Index permission differences leak existence of indexes ("no permissions" vs "no such index").
- **Alerting**, **anomaly detection**, **observability** (traces/metrics/logs), **security analytics** (SIEM).
- **Custom packages**: dictionaries (synonyms, stop words) for better search relevance.
- **Auto-Tune**: automatic JVM/queue tuning; required for Multi-AZ with Standby.
- **Cross-cluster search/replication**: query or replicate across domains (verify limits).
- **Amazon Quick** (QuickSight) can visualize OpenSearch data.
- **Bedrock**: Knowledge Bases can store vectors in OpenSearch Serverless.
- **SageMaker/ML Commons**: host or connect embedding models for neural search (verify).

## Scenarios (if → then, because)
- **If** you need search with no capacity planning and the load is spiky, **then** use **Amazon OpenSearch Serverless**, which has no domains, nodes or shards to manage. You only create a **collection** (a group of indexes). **This works because** compute is measured in **OpenSearch Compute Units (OCUs)**, each **6 GiB** of memory plus CPU, and OCUs for indexing and for search **scale out and back automatically** between the min and max you set. The max (up to **1,700 OCUs**) acts as a **budget cap**.
- **If** idle cost must be **zero**, **then** put the collection in a **collection group** with **minimum OCUs set to 0**. **This works because** OCUs scale down to zero when idle, so there is no compute cost. The catch is a **cold-start delay** on the first request; set a higher minimum if that delay is not acceptable.
- **If** you need **custom plugins** or **manual snapshots**, **then** use a **provisioned domain** (you pick the instances). **This works because** OpenSearch Serverless allows **no custom plugins** and supports only **automated snapshots**, not manual ones.
- **If** an **Amazon Bedrock Knowledge Base** needs a vector store, **then** create an **OpenSearch Serverless vector search collection** and give it a **network policy** that allows **AWS service private access** for Bedrock. **This works because** Bedrock Knowledge Bases can store vectors in OpenSearch Serverless, and private service access lets Bedrock reach the collection without public access. The collection also needs an **encryption policy** and a matching **data access policy**, or it will not work.
- **If** vector queries get slow as data grows, **then** check the **Amazon CloudWatch** metric **`KNNGraphMemoryUsage`**, then add memory (bigger or memory-optimized instances) or use **quantization / disk-optimized mode** (verify names). **This works because** **HNSW** (Hierarchical Navigable Small World) graphs live in **off-heap memory**, and by default only about **25% of RAM** is for them (a 32 GiB instance holds about **8 GiB** of graphs). When graphs no longer fit, performance drops.
- **If** vectors must be filtered (for example by category) inside the search itself, **then** use the **Lucene engine**, which supports filtering inside the search (or efficient filtering). **This works because** adding a normal filter clause to a **k-nearest neighbors (k-NN)** query filters **after** the search, so it can return **fewer than k** results.
- **If** you must cut memory for a huge set of vectors, **then** use **IVF** (Inverted File) or **quantization / compression** (verify). IVF groups vectors into clusters and searches only the nearest ones; it needs a **training step**, and recall depends on how many clusters are checked. **This works because** **HNSW** keeps its whole graph in memory and is **memory heavy**, while IVF and quantization store less.
- **If** logs arrive from **Amazon Kinesis** and you want **no code**, **then** use **Amazon Data Firehose** to deliver them to OpenSearch, with **failed-document backup to Amazon S3**. **This works because** Firehose buffers and batches records itself and keeps documents that fail to index in S3, so nothing is lost.
- **If** you need to parse, enrich and route logs or traces, **then** use an **Amazon OpenSearch Ingestion** pipeline. This is managed **Data Prepper**: serverless pipelines that filter, transform and deliver data to domains or collections, including **OpenTelemetry** traces. **This works because** it runs the pipeline for you and auto-scales between min and max **Ingestion OCUs**. The catch: you pay for allocated OCUs even when no data flows, so **stop** pipelines you are not using.
- **If** an **Amazon DynamoDB** table needs full-text search, **then** copy its data into OpenSearch with the **DynamoDB zero-ETL integration** (through **OpenSearch Ingestion**) or with **DynamoDB Streams + AWS Lambda**. **This works because** DynamoDB is built for key lookups and **cannot do text search**, so you keep the table as the source and a search index beside it, kept in sync with every change.
- **If** moving indexes hot → warm → cold must be automatic, **then** write an **Index State Management (ISM)** policy using the service actions **`warm_migration`**, **`cold_migration`** and **`delete`**. A typical log policy is hot → warm at **10 days** → cold at **90 days** → delete at **365 days**. **This works because** ISM moves each index through states when conditions such as **`min_index_age`** are met.
- **If** **Index State Management (ISM)** stops moving indexes to the next state, **then** check the **cluster status** first. **This works because** ISM **does not run when the cluster is red**; fix the red status and ISM continues (it runs about every **5–8 minutes**).
- **If** an ISM policy is not applied to new indexes through an **index template**, **then** add an **`ism_template`** field to the ISM policy instead. **This works because** index templates **can no longer attach ISM policies**; `ism_template` matches new index names and applies the policy automatically.
- **If** a **bulk request** fails with HTTP **413**, **then** the request is **too large**, so send smaller batches. **This works because** the maximum HTTP request payload is **10 MiB** on smaller instances and **100 MiB** on larger ones.
- **If** another AWS account must read an **OpenSearch Serverless** collection, **then** share the data another way: **copy (replicate) it** to that account or use a **provisioned domain** instead. **This works because** Serverless has **no cross-account access** to collections (and no cross-Region search or replication).

## Verified from AWS docs on 2026-10-02
Read: Serverless overview, comparison, scaling page, security overview, k-NN page, ISM page, ingestion overview, UltraWarm page, limits page, zero-ETL summary page (summary only). Not confirmed (verify): k-NN supported spaces and current max dimensions, quantization/disk-mode names, neural search availability, Ingestion source list, zero-ETL integration list and details, rollups/transforms/cross-cluster replication availability, SQL JDBC/ODBC support, Firehose buffer defaults, Bulk size guidance (general practice).

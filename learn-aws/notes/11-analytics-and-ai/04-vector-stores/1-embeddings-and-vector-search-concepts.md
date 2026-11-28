# Vector stores – 1. Embeddings and vector search concepts

Short notes. Each point is a fact you can be asked about.

## A. Why vector stores exist
- A **vector store** (vector database/index) stores **embeddings** and finds the **nearest ones** to a query vector fast. It is the memory behind **semantic search, RAG, recommendations, deduplication, anomaly detection**.
- **Keyword search** (BM25/inverted index) matches **words**. **Vector search** matches **meaning**: "car" and "automobile" land near each other.
- Most real systems use **both** (hybrid search).
- **Not every workload needs a new database**: if your data already lives in Postgres, OpenSearch, Redis/Valkey, DocumentDB or S3, you may add vectors there.

## B. Embeddings
- An **embedding** = a list of numbers (a **vector**) that a model produces from text, an image, audio or video. Similar content → close vectors.
- **Dimension** = how many numbers (for example **256, 512, 1,024, 1,536**). Set by the **embedding model**. Bigger = more detail, more storage, slower search.
- **Typical AWS models**: **Titan Text Embeddings V2** (1,024 default; 512 or 256 options), Titan G1 (1,536), **Cohere Embed** (1,024), **Nova multimodal embeddings** (text + image + audio + video) **(verify)**.
- **Rules**:
  - Index and query must use the **same model** and **same dimension**.
  - **Changing the model = re-embed everything** (vectors from different models are not comparable).
  - Embeddings are **not reversible** to the original text but still may reveal sensitive info: protect the store like the source data.
- **Binary embeddings** (1 bit per dimension) cut storage ~32x but are less precise; only some stores/models support them (in Bedrock KBs: **OpenSearch** only).
- **Quantization** (scalar/int8, product, binary) shrinks vectors to save memory/cost at some recall loss.
- **Normalization**: unit-length vectors make **cosine and dot product equivalent**.
- **Embedding cost**: billed per input token. Chunk wisely to avoid re-embedding.

## C. Similarity (distance) metrics
- **Cosine similarity**: angle between vectors; ignores length. **Most common for text.**
- **Euclidean (L2)**: straight-line distance. Common default for float embeddings in some stores.
- **Dot product (inner product)**: fast; correct for **normalized** vectors or models trained for it.
- **Hamming**: for **binary** vectors.
- **Always match the metric the embedding model recommends.** Wrong metric = poor ranking.
- Some stores (for example **S3 Vectors**: cosine or Euclidean; **DocumentDB**: Euclidean, cosine, dot product; **Neptune Analytics**: fixed per index **(verify)**) fix the metric **at index creation**.

## D. Search methods
- **Exact k-NN (brute force / FLAT)**: compares the query with every vector. **100% recall**, slow at scale. Fine for small sets or filters that leave few candidates.
- **ANN (approximate nearest neighbor)**: trades a little **recall** for big **speed** gains.
- **HNSW (Hierarchical Navigable Small World)**: multi-layer **graph**. Best query speed and recall; **high memory**, slower build; no training step. **Default choice** for most stores.
  - **`M`**: connections per node (more = better recall, more memory). **`efConstruction`**: build-time candidate list (more = better graph, slower build). **`efSearch` / `ef_runtime`**: query-time candidate list (more = better recall, slower query).
- **IVF / IVFFlat (inverted file)**: **clusters** vectors into **lists**, searches only the nearest lists (**`probes`**). Faster build, **less memory**, **needs data before building** (training), generally lower recall than HNSW.
- **PQ (product quantization)** and **DiskANN-style** indexes: compress/store on disk for very large sets **(verify availability per service)**.
- **Recall** = fraction of true nearest neighbors found. **Latency vs recall** is the main tuning trade-off.
- **Metadata filtering**:
  - **Pre-filter**: restrict candidates first, then search (accurate, can be slower).
  - **Post-filter**: search first, then filter (fast, can return **too few** results when the filter is selective).
  - **Filtered/iterative HNSW** (for example pgvector 0.8 **iterative scans**) fixes the "too few results" problem.
- **Hybrid search**: combine **keyword score + vector score** (for example reciprocal rank fusion or weighted sum). Catches exact terms (IDs, names, codes) that embeddings miss.
- **Reranking**: retrieve more candidates cheaply, then **rerank** with a stronger model and keep the best few.
- **Multi-vector / late interaction** and **sparse vectors** (learned sparse like SPLADE) exist in some engines **(verify)**.
- **Top-K** = how many results you ask for. Large K costs more and may reduce quality of the prompt.

## E. Designing the index (the choices that matter)
- **What is one vector?** A **chunk** of a document (RAG), a whole product, an image, a user, a session. Chunk size and overlap strongly affect quality.
- **Store alongside each vector**: the **text chunk**, **source ID/URI**, **page**, **timestamps**, **tenant/user**, **ACL tags**, **type/category**, **version**. You need these for **filters, citations and deletes**.
- **Multi-tenancy** options: **index per tenant** (strong isolation, many indexes), **namespace/partition key + filter** (cheaper, rely on filters), **store per tenant** (strongest, most cost). Never trust the model to enforce tenant isolation.
- **Updates and deletes**: documents change. Keep a **stable ID per chunk**, delete old chunks on re-ingest, and re-embed only changed files. Some ANN indexes **degrade** after many deletes (rebuild/optimize).
- **Consistency**: some stores are **strongly consistent on write** (S3 Vectors); others are **near-real-time** (OpenSearch refresh interval) or have **non-atomic vector updates** (Neptune Analytics).
- **Capacity**: **memory-resident** (HNSW in OpenSearch, MemoryDB, pgvector working set) vs **storage-based** (S3 Vectors). Rough memory per float32 vector: `dimensions × 4 bytes` **plus graph overhead** (HNSW adds roughly `M × 8–16` bytes per vector) **(approximation)**.
  - Example: 10M vectors × 1,536 dims × 4 B ≈ **61 GB** of raw vectors before index overhead (MemoryDB's calculator gave about **105 GB** for that scale with M=16).
- **Latency tiers**: in-memory (MemoryDB, OpenSearch) → **single-digit to tens of ms**; S3 Vectors → **sub-second** (as low as **~100 ms** for frequent queries).
- **Throughput vs cost**: always-on clusters cost money idle; storage-based stores cost per query.
- **Security**: encrypt at rest (KMS), restrict network (VPC/PrivateLink), IAM/field-level access, log access, delete vectors when source data is deleted (**right to be forgotten**).

## F. Evaluating a vector store/search setup
- Build a **golden set** of queries with known relevant documents.
- Measure **recall@k**, **MRR/nDCG**, **latency p50/p95/p99**, **cost per 1M queries**, **index build time**, **memory**.
- Compare: embedding model, chunk size, ANN parameters, hybrid vs semantic, with/without rerank.
- **Bedrock RAG evaluation** can score a whole RAG pipeline (retrieval + answer).
- Re-test after **changing the embedding model, index parameters or data volume**.

## G. Common failure modes
- **Dimension mismatch** → ingestion errors.
- **Wrong metric** → odd ranking.
- **Filter too selective** (post-filtering) → few or zero results.
- **Chunks too big** → vague matches; **too small** → missing context.
- **Stale vectors** after a source update → wrong or outdated answers.
- **Everything is "close"** (low-quality embeddings, mixed languages) → use a multilingual or domain model, rerank.
- **Hot memory exhausted** (HNSW) → out-of-memory/slow queries → bigger nodes, quantization, smaller dimension, or move to disk/S3-based index.
- **Leaking restricted documents** through retrieval → enforce **ACL filters** at query time.

## H. Scenarios: "If X → Y, because Z"
- **If** users search with different words for the same idea (synonyms like "car" and "automobile", or paraphrases), **then** use **vector (semantic) search**. **This works because** an **embedding** model turns text into a list of numbers (a vector), and similar meaning gives close vectors, so a match is found even when no words are shared.
- **If** searches must find meaning but also exact **IDs, names or product codes**, **then** use **hybrid search**, which combines a **keyword score** (for example **BM25**) with a **vector score**, for example by **reciprocal rank fusion** or a weighted sum. **This works because** keyword search matches exact words, while embeddings capture meaning but are weak on exact tokens like codes. Most real systems use **both**.
- **If** the dataset is small (**thousands** of vectors), **then** use **exact k-nearest neighbor (k-NN)** search, also called brute force or **FLAT**, which compares the query with every vector. **This works because** at this size brute force is fast enough and gives **100% recall** (it finds all true nearest neighbors). It only becomes slow at scale.
- **If** the dataset is huge and queries are frequent, **then** use an **HNSW (Hierarchical Navigable Small World)** index, a multi-layer **graph** and the default choice for most stores. **This works because** HNSW gives the best query speed and recall of the approximate methods and needs no training step. The catch: it uses **high memory** and builds slowly; tune **`M`**, **`efConstruction`** and **`efSearch`** to trade recall for speed.
- **If** memory is the bottleneck and some recall loss is acceptable, **then** use an **IVF (inverted file)** index, **quantization** (scalar/int8, product or binary), **smaller dimensions** (for example 512 or 256), or a storage-based store like **Amazon S3 Vectors**. **This works because** IVF uses less memory than HNSW, quantization shrinks each vector, fewer dimensions mean fewer numbers to keep, and S3 Vectors keeps vectors in storage, not RAM. The cost is lower recall, or **sub-second** instead of millisecond latency for S3 Vectors.
- **If** a selective metadata filter returns too few results, **then** use **pre-filtering** or **iterative scans** (**pgvector 0.8**, the vector extension for PostgreSQL). **This works because** **post-filtering** searches first and filters after, so a strict filter drops most candidates. Pre-filtering restricts candidates before the search (accurate but can be slower), and iterative scans keep scanning the HNSW index until enough rows pass the filter.
- **If** you change the **embedding model**, **then** **re-embed all data into a new index**. **This works because** vectors from different models are not comparable: dimensions and vector spaces differ, and index and query must use the **same model and same dimension**.
- **If** results are decent but the top few are not the best, **then** **add a reranker**: retrieve more candidates cheaply, then re-score them with a stronger model and keep the best few. **This works because** the reranker looks at a larger candidate set more carefully than the fast vector search can.
- **If** each customer's (tenant's) data must be kept apart, **then** use an **index per tenant** or a **namespace/partition key per tenant**, always with **enforced filters**, or a **separate store per tenant** for the strongest isolation (at the most cost). **This works because** isolation must come from the store and its filters; the model cannot enforce it, so never trust it to.
- **If** the text lives in a document that is edited daily, **then** give each chunk a **stable chunk ID**, delete old chunks on re-ingest, and **re-embed only changed files**. **This works because** it avoids **stale duplicate** vectors (wrong or outdated answers) and saves cost, since embedding is billed **per input token**. Some indexes degrade after many deletes, so rebuild or optimize them.
- **If** you must prove deleted data is gone (**right to be forgotten**), **then** **delete the vectors together with the source data** and verify. **This works because** embeddings cannot be turned back into the original text but **may still reveal sensitive information**, so they must be treated like the source data.

Verified from AWS docs on 2026-11-01 (S3 Vectors, DocumentDB vector search, MemoryDB vector search limits, Neptune Analytics vector index, Bedrock KB vector store pages).
Unconfirmed (verify): the per-vector HNSW overhead approximation; PQ/DiskANN availability per AWS service; sparse/multi-vector support per engine; Nova multimodal embedding dimensions; Neptune Analytics metric options; exact normalization behavior of Titan V2.

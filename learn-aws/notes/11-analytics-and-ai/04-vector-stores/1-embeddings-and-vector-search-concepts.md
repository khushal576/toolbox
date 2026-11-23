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
- If searches must find synonyms and paraphrases → **vector (semantic) search**, because embeddings capture meaning.
- If searches must also match exact IDs/product codes → **hybrid search**, because embeddings are weak on exact tokens.
- If the dataset is small (thousands) → **exact k-NN**, because brute force is fast enough and gives perfect recall.
- If the dataset is huge and queries are frequent → **HNSW**, because it gives the best latency and recall (at memory cost).
- If memory is the bottleneck and some recall loss is OK → **IVF / quantization / smaller dimensions / S3 Vectors**, because they use less memory.
- If a selective filter returns too few results → **pre-filtering or iterative scans (pgvector 0.8)**, because post-filtering drops candidates.
- If you change the embedding model → **re-embed all data into a new index**, because dimensions and spaces differ.
- If results are decent but the top few are not best → **add a reranker**, because it re-scores a larger candidate set.
- If each customer's data must be isolated → **index/namespace per tenant plus enforced filters** (or separate stores), because the model cannot enforce isolation.
- If text lives in a doc that gets edited daily → **stable chunk IDs and incremental re-embedding**, because it avoids stale duplicates and cost.
- If you need to prove deleted data is gone → **delete vectors with the source** and verify, because embeddings can leak information.

Verified from AWS docs on 2026-11-01 (S3 Vectors, DocumentDB vector search, MemoryDB vector search limits, Neptune Analytics vector index, Bedrock KB vector store pages).
Unconfirmed (verify): the per-vector HNSW overhead approximation; PQ/DiskANN availability per AWS service; sparse/multi-vector support per engine; Nova multimodal embedding dimensions; Neptune Analytics metric options; exact normalization behavior of Titan V2.

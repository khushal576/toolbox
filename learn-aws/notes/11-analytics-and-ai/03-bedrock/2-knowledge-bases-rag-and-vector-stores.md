# Amazon Bedrock – 2. Knowledge Bases (RAG): ingestion, vector stores, retrieval

Short notes. Each point is a fact you can be asked about.

## A. RAG in one minute
- **RAG (Retrieval-Augmented Generation)**: find the **most relevant pieces of your own data**, put them in the prompt, and let the model answer from them.
- Why: models do not know your private data, and **retraining is expensive and goes stale**. RAG keeps data fresh and gives **citations**.
- **Two phases**:
  1. **Ingestion (offline)**: parse documents → **chunk** → **embed** each chunk → store vectors + text + metadata in a **vector index**.
  2. **Query (online)**: embed the question → **search** the index for nearest chunks (optionally rerank) → add chunks to the prompt → model writes the answer with sources.
- **Bedrock Knowledge Bases (KB)** automates both phases. You point it at data sources and a vector store (or let AWS manage the store).
- RAG vs fine-tuning: RAG adds **knowledge**; fine-tuning changes **style/behavior/format**. For fast-changing facts use RAG.

## B. Two kinds of Knowledge Base (current docs)
- **Bedrock Managed Knowledge Base** (recommended by AWS for most new builds):
  - AWS manages **ingestion, storage, indexing and retrieval**: an auto-scaling datastore of embeddings, text, metadata and raw files.
  - **Built-in managed embedding model and managed reranker at no extra cost**. You may supply your own Bedrock embedding model at creation (**float32, 1,024 dimensions**) and your own reranker at query time.
  - **7 native connectors**: S3, SharePoint, Confluence, Web Crawler, Google Drive, OneDrive, custom.
  - **Agentic retrieval** (`AgenticRetrieveStream`): a model **splits a complex question into sub-queries**, retrieves repeatedly, checks if results are enough, returns de-duplicated chunks + trace.
  - Built-in multimodal parser; **chunking**: built-in default or fixed-size.
  - **ACL awareness** for source permissions, **resource policies** (cross-account), **AgentCore Gateway** and **Amazon Quick** integration.
  - Quotas (docs): **10,000 KBs** per account/Region, **200 data sources** per KB (adjustable), **50 concurrent ingestion jobs** per KB, **10 TB raw data** per KB (adjustable), **600 Retrieve requests/min per KB** (burst 25 RPS), **300 AgenticRetrieveStream/min per account**, **10,000 characters** per query.
  - Metadata filters: `startsWith` and `stringContains` **not supported**; use equals, greater/less than, `in`, `notIn`. Reserved metadata fields use an underscore prefix (`_source_uri`).
  - Price (docs): **index storage $5 per GB of raw data per month**, **standard Retrieve $1 per 1,000 calls**, **agentic retrieval $4 per 1,000 calls plus $1 per 1,000 underlying Retrieve calls**; **parsing, embeddings and reranking with managed options are $0** **(verify, pricing page was truncated)**.
- **Customer-managed Knowledge Base** (bring your own vector store):
  - **You choose, provision and scale** the vector store and have direct access to it.
  - Connectors: **S3 and custom** (plus others as documented per connector **(verify)**); parsing choices: **default, foundation model, Bedrock Data Automation**.
  - Any Bedrock embedding model; optional reranker.
  - Choose it when you need **a specific vector database**, custom index tuning, **binary vectors**, **hybrid search control**, or to **reuse an existing OpenSearch/Aurora** index.
- **Quick pick**: end-to-end managed RAG, native connectors, agentic retrieval → **Managed KB**. Custom vector DB config, existing store, special tuning → **Customer-managed KB**.

## C. Data sources and ingestion (customer-managed KB details)
- **Sources**: **S3** (most used), **web crawler**, **Confluence**, **SharePoint**, **Salesforce**, **custom data source** (push documents with the API) **(verify exact connector list per KB type)**.
- **Sync (ingestion job)**: you start a **sync** (`StartIngestionJob`); only **new/changed/deleted** files are processed. **A sync is not automatic**: schedule it (EventBridge/Step Functions/Lambda) or trigger after uploads.
- **Direct ingestion** (`IngestKnowledgeBaseDocuments`): add or update documents **without a full sync** (custom/S3 sources).
- **Supported file types**: PDF, Word, Excel, CSV, HTML, Markdown, plain text; images (with multimodal parsing). File size limit is per file (historically **50 MB**; **verify**).
- **Inclusion/exclusion**: S3 **prefixes**; crawler URL scope and regex filters.
- **Metadata files**: put **`<filename>.<ext>.metadata.json`** beside each document (S3) with `metadataAttributes` (string, number, boolean, string list). Used for **filtering** at query time.
- **Parsing options**:
  - **Default parser**: text extraction, no model cost; weak for tables/figures.
  - **Foundation-model parser**: a model (for example a Claude model) reads pages with tables/figures; **costs model tokens**.
  - **Bedrock Data Automation parser**: multimodal (documents, images, audio, video → text/transcripts/scene summaries); **billed per page/minute** **(verify)**.
- **Ingestion failures to know**: dimension mismatch, metadata too large, unsupported file, KMS/permission errors on S3 or the vector store, vector store throughput too low (OpenSearch needs more IOPS/capacity).
- **Deleted source files** are removed from the index at the next sync.

## D. Chunking (how text is split)
- **Why it matters**: chunks that are too big dilute meaning; too small lose context. It is the **#1 RAG quality lever**.
- **Default chunking**: about **300 tokens**, respects sentence boundaries.
- **Fixed-size**: you set **max tokens** and **overlap %**.
- **Hierarchical**: **parent** and **child** chunks (set both sizes and overlap tokens). Search matches **small child chunks** (precise) but returns the **larger parent** (more context). Fewer results than requested may come back because children sharing a parent merge. **Not recommended with S3 Vectors** when sizes are large (over about 8,000 tokens combined) because of metadata limits.
- **Semantic**: splits where **meaning changes**, using a model. Settings: **max tokens, buffer size (neighbor sentences), breakpoint percentile threshold**. **Extra model cost.**
- **No chunking**: each file is one chunk (pre-split files yourself). **Page numbers in citations and page-number filtering do not work.**
- **Custom (Lambda) transformation**: your function chunks or enriches content (also used for table-level chunks).
- **Tables and figures**: for parsed content, a matched chunk can be replaced with the **whole page or table** (if 10,000 characters or fewer), so fewer, bigger results are returned.
- **Multimodal**: audio/video chunking happens in the embedding model (for example Nova multimodal embeddings: **1–30 s chunks, default 5 s**); text chunking settings only affect text files.
- **Changing the chunking strategy** means **re-ingesting**. Chunking and embedding model are fixed per data source at creation **(verify)**.

## E. Vector store options (customer-managed KB)
- **Quick create** (Bedrock makes the store for you) exists for some stores; otherwise create the index first and give Bedrock the field mappings.
- Supported stores (docs):
  - **Amazon OpenSearch Serverless** (vector search collection). Engine **faiss** (nmslib not supported for filters). Supports **binary vectors**, **hybrid search**, and the richest metadata filters.
  - **Amazon OpenSearch Managed Cluster**. Needs **public access** (VPC-only domains are **not** supported for KB), engine **2.13+** for k-NN (**2.16+** for binary vectors), **faiss** only, fine-grained access control recommended.
  - **Amazon S3 Vectors**: cheapest, durable, **sub-second** queries, best for **infrequent** query workloads; vector bucket + vector index; dimensions **1–4,096**; distance **cosine or euclidean**; **floating-point only** (no binary); per-vector metadata limit **about 1 KB custom metadata and 35 keys**; encryption type (SSE-S3 or SSE-KMS) **cannot be changed after bucket creation**; set `AMAZON_BEDROCK_TEXT` and `AMAZON_BEDROCK_METADATA` as **non-filterable** keys; no `startsWith`/`stringContains` filters.
  - **Amazon Aurora PostgreSQL (pgvector)**: table with `id` (UUID), `embedding` (vector), `chunks` (text), `metadata` (JSON), optional `custom_metadata` (JSONB); needs **HNSW index** on embedding and **GIN index** on text (and custom metadata); **Secrets Manager** secret + **Data API**; cluster must be in the **same account**; field names **cannot be changed after KB creation**; hybrid search supported; for metadata filtering enable **HNSW iterative scans** (pgvector 0.8+) so selective filters do not return too few rows.
  - **Neptune Analytics (GraphRAG)**: graph with a vector index; the index dimension is **set at graph creation** and must match the embedding model; use for **relationship-aware** retrieval.
  - **Third-party**: **Pinecone**, **Redis Enterprise Cloud**, **MongoDB Atlas** (credentials in **Secrets Manager**; you accept third-party terms). MongoDB metadata filtering needs manual index config.
- **Only OpenSearch (Serverless and managed) support binary vectors.**
- **Hybrid search** = vector + keyword; supported for **Aurora (RDS), OpenSearch Serverless and MongoDB** with a filterable text field. Other stores fall back to **semantic**.
- **Embedding model and store dimension must match** (Titan V2: 1,024/512/256; Titan G1: 1,536; Cohere: 1,024).
- **Rule of thumb**:
  - Lowest cost, few queries → **S3 Vectors**.
  - Heavy search, hybrid, filters, scale → **OpenSearch Serverless / managed**.
  - Data already in Postgres, SQL joins with relational data → **Aurora pgvector**.
  - Entity relationships matter → **Neptune Analytics GraphRAG**.
  - Want no store to manage → **Managed KB**.
- (See the `vector-stores` notes for a broader comparison.)

## F. Querying a knowledge base
- **`Retrieve`**: returns the **top chunks** (text/images + source + score + metadata). **You** call the model. Use for custom RAG, agents, pipelines.
- **`RetrieveAndGenerate`** (and `...Stream`): retrieve **+** generate an answer with **citations** in one call. Optional **session** to keep multi-turn context.
- **`GenerateQuery`**: converts natural language to a **SQL query** for **structured data** stores.
- **`AgenticRetrieveStream`** (managed KBs): multi-step retrieval with trace events.
- **Rerank API**: reorders documents by relevance (**text only**). Use with `Retrieve`/`RetrieveAndGenerate` or standalone on **any** list of documents. Lets you retrieve more candidates and pass **fewer, better** chunks to the model (cuts cost and latency). Reranker results **override** the default ranking.
- **Number of results**: default **5** chunks. The real count can be lower (hierarchical/page-context merging).
- **Search type**: **default** (Bedrock decides), **hybrid**, **semantic** (`overrideSearchType`).
- **Metadata filters**: `equals`, `notEquals`, `greaterThan(OrEquals)`, `lessThan(OrEquals)`, `in`, `notIn`, `startsWith`, `stringContains`, `listContains`; combine with `andAll` / `orAll` (**up to 5** filters per group, one level of nesting). Best support is on **OpenSearch Serverless**.
- **Implicit metadata filtering**: a **Claude model** builds the filter from the user's question and your metadata schema (`implicitFilterConfiguration`).
- **Query decomposition**: break a complex question into sub-queries (more retrieval calls, better answers).
- **Prompt templates**: customize the **orchestration** and **generation** prompts. Placeholders: `$query$`, `$search_results$`, `$output_format_instructions$` (**required for citations**), `$current_time$`.
- **Guardrails** attach to `RetrieveAndGenerate` (`guardrailConfiguration`); **contextual grounding check** helps catch hallucinations.
- **Citations**: each answer links to source chunks (S3 URI, page number where available).
- **Chat with a single document** (no KB): `RetrieveAndGenerate` with **external sources** for quick one-off Q&A.
- **Structured data retrieval**: connect a KB to **Redshift / Glue Data Catalog (Athena)** so natural language is converted to SQL **(verify supported stores)**.
- **Access control**: KB queries run with the **caller's IAM**. **Per-user document security** needs **metadata filters** or **ACL-aware connectors** (managed KB). A plain S3 KB gives every caller access to **all** indexed content.

## G. Using KBs from other parts of Bedrock and AWS
- **Agents (Classic) and AgentCore**: attach a KB as a knowledge tool; AgentCore Gateway exposes a **managed KB as an MCP tool**.
- **Flows**: a **Knowledge Base node**.
- **Amazon Quick** (BI/assistant) can use a managed KB natively.
- **Pipelines**: Step Functions/Lambda call `Retrieve` or schedule **ingestion jobs** after new files land in S3 (EventBridge S3 events → start sync).
- **Data-lake RAG pattern**: S3 raw → Glue/Textract/BDA clean text → S3 curated + metadata files → KB sync → app/agent. Tag metadata with **department, date, sensitivity, source system** for filters.

## H. Quality, cost and operations
- **Improve quality**: better parsing for tables, right chunk size, **hierarchical or semantic** chunking, **rerank**, **hybrid search**, metadata filters, query decomposition, a good generation prompt, and **grounding checks**.
- **Evaluate**: Bedrock **RAG evaluation** (retrieve-only or retrieve-and-generate; metrics like correctness, completeness, faithfulness, citation precision) and **LLM-as-judge** (see file 3). Test with a **golden question set**.
- **Cost drivers**: embedding tokens at ingestion (**re-embedding on every model/chunk change**), **vector store** (OpenSearch Serverless OCUs have a minimum even idle; S3 Vectors is cheap; Aurora ACUs), **parsing** with FM/BDA, **semantic chunking** model calls, reranker calls, generation tokens (more chunks = more input tokens), and **managed KB** storage/retrieve fees.
- **Cut cost**: S3 Vectors for low-QPS data, smaller dimensions (512/256), fewer/better chunks via rerank, **prompt caching** for stable context, **batch** for bulk summarization, incremental syncs only, delete unused KBs and OpenSearch Serverless collections.
- **Monitoring**: CloudWatch metrics for ingestion and API calls, **model invocation logging** (shows the final RAG prompt and default template), **CloudTrail**, managed KB **observability** features. Watch ingestion job status and `numberOfFailedDocuments`.
- **Troubleshooting**:
  - Ingestion job fails/documents skipped → file type/size, permissions, metadata size, dimension mismatch.
  - Empty or irrelevant results → wrong embedding model, chunks too big/small, filters too strict, **no sync after upload**, language mismatch.
  - Filters return too few results (Aurora) → enable **HNSW iterative scans**.
  - Filtering errors in OpenSearch ("Rewrite first") → custom metadata fields need `keyword` mapping.
  - No citations → `$output_format_instructions$` removed from the template.
  - Hallucinations → add **grounding check**, lower temperature, require citations, improve retrieval.
  - Access denied → KB **service role** needs S3, embedding model `bedrock:InvokeModel`, vector store permissions; encrypted stores need KMS.
  - Timeouts on huge syncs → split data sources, raise OpenSearch IOPS/throughput.

## I. Security
- **IAM service role** for the KB: read S3 data source, `bedrock:InvokeModel` on the embedding (and parsing) model, access to the vector store (OpenSearch data access policy, Aurora Data API + secret, S3 Vectors actions).
- **Encryption**: KMS keys for KB resources, transient data during ingestion, OpenSearch Serverless encryption policy, **S3 Vectors SSE-KMS** (fixed at creation), Secrets Manager secrets.
- **Network**: OpenSearch Serverless can use **VPC endpoint** access; managed OpenSearch domain for KB must be **public**; use PrivateLink for `bedrock-agent-runtime` calls.
- **Data privacy**: your documents are not used to train models and are not shared with providers (file 4).
- **Document-level security**: metadata filter per user group, or per-tenant KBs, or ACL-aware connectors. **Do not index documents users must not see.**
- **PII**: use **Guardrails sensitive-information filters** on retrieved text/answers; use **Macie** on the S3 bucket before indexing.

## J. Scenarios: "If X → Y, because Z"
- If you want the quickest, most managed RAG over SharePoint/Confluence/S3 → **Managed Knowledge Base**, because AWS manages ingestion, store, embedding and reranking with native connectors.
- If you must use an existing OpenSearch domain or tune the index → **Customer-managed KB (OpenSearch)**, because you control the vector store.
- If cost per stored vector must be minimal and queries are rare → **S3 Vectors**, because it is object-storage priced with sub-second queries.
- If you need keyword + semantic ranking → **hybrid search on OpenSearch Serverless / Aurora**, because other stores fall back to semantic only.
- If answers need relationships between entities → **GraphRAG on Neptune Analytics**, because it follows graph links, not just similarity.
- If answers lack surrounding context → **hierarchical chunking** (child match, parent returned), because small chunks match precisely but large ones inform better.
- If long documents are split at awkward places → **semantic chunking** (extra model cost) or custom Lambda, because it splits by meaning.
- If tables in PDFs are garbled → **foundation-model parser or Bedrock Data Automation parser**, because the default parser extracts plain text only.
- If you retrieve 20 chunks but only 4 matter → **add a reranker**, because it reorders and lets you pass fewer chunks (lower cost, better answers).
- If different users must see different documents → **metadata filters per request or ACL-aware managed connectors**, because KB access is IAM-based, not per-document.
- If files uploaded to S3 never appear in answers → **run a sync (ingestion job) or direct ingestion**, because KBs do not auto-sync.
- If you change the embedding model → **re-ingest everything into a new index with the new dimension**, because vectors from different models are not comparable.
- If the answer has no citations → keep **`$output_format_instructions$`** in the custom prompt, because it carries the citation formatting.
- If a complex multi-part question gets weak answers → **query decomposition or agentic retrieval (managed KB)**, because multiple sub-queries cover each part.
- If a Postgres team wants RAG next to relational data → **Aurora pgvector KB**, because one store serves SQL and vectors.
- If binary embeddings are needed to cut storage → **OpenSearch (Serverless or managed)**, because only those support binary vectors.

Verified from AWS docs on 2026-11-01 (Knowledge Bases overview, vector store prerequisites, chunking, retrieval, query configuration, managed KB, managed KB quotas, rerank, pricing page).
Unconfirmed (verify): the data-source list and file-size limit for each KB type (the data-source page returned no content, so these come from earlier knowledge); BDA parser pricing; whether sync can be scheduled natively; structured data store support (Redshift/Glue); reranker model names and quotas; "chunking fixed per data source after creation"; managed KB parsing/embedding being free on every plan; metadata size limits for stores other than S3 Vectors; 50 MB file limit; RAG evaluation metric names.

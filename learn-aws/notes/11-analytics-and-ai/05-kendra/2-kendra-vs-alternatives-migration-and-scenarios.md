# Amazon Kendra – 2. Kendra vs alternatives, migration to Bedrock, and decision scenarios

Short notes. Each point is a fact you can be asked about.

## A. Kendra vs the nearest services
| Need | Kendra | OpenSearch | Bedrock Knowledge Base | Amazon Q Business |
|---|---|---|---|---|
| Status | **Maintenance mode; closed to new customers (30 Jul 2026)** | Active | Active (Managed KB recommended) | Active |
| What you get | Managed intelligent **search/retrieval** | **Search engine** you design and tune | **RAG pipeline** (ingest, embed, store, retrieve, generate) | **Finished assistant app** for employees |
| Effort | Low | **High** (mapping, analyzers, scaling, relevance) | Low–medium | Lowest |
| Connectors | **~32+** | Few (Ingest pipelines, Logstash, custom) | **7** (managed) / S3 + custom | Many (connectors incl. Kendra-style) |
| ACL / per-user security | **Built-in** (connector ACLs + user context) | You build it (document-level security, filters) | Metadata filters / ACL-aware managed connectors | **Built-in** (identity via IAM Identity Center) |
| Search type | Semantic (+ keyword in GenAI index) | Keyword, vector, **hybrid**, your choice | **Hybrid** (managed KB always hybrid) | Managed |
| Generation | You call an LLM yourself | You call an LLM yourself | **RetrieveAndGenerate**, agentic retrieval | **Built-in** |
| Facets/suggestions/synonyms | **Yes** (Enterprise/Developer, partly GenAI) | Yes (you build) | **No** (workarounds) | Limited |
| Cost model | **Hourly per index capacity** + connector fees | Instances or OCUs | Storage + retrieval + tokens (Managed KB) | Per user subscription + index |
| Best for | Existing enterprise search to keep | Custom, high-scale search/analytics | New RAG apps and agents | Out-of-box employee assistant |
- **Rule**: **new RAG → Bedrock KB**; **end-user assistant with no code → Q Business**; **custom search engine / analytics → OpenSearch**; **existing Kendra → keep or migrate**.
- **Kendra vs Elasticsearch/OpenSearch**: Kendra is **opinionated and managed** (ML relevance, ACLs, connectors). OpenSearch is **flexible and cheaper at huge scale** but you must tune and secure it.
- **Kendra vs vector stores**: a vector store only stores and searches vectors. Kendra includes **ingestion, parsing, connectors, ranking and security**.

## B. Migrating Kendra → Bedrock Managed Knowledge Base (BMKB)
- AWS gives a **step-by-step guide**. Two main jobs: **re-ingest data** into BMKB and **rewrite application calls**.
- **BMKB facts** (docs):
  - Embeddings: **Titan Text V2, Cohere Embed English v3, Cohere Embed Multilingual v3, Cohere Embed v4, Nova Multimodal Embeddings**, all **1,024 dimensions, float32**.
  - Vector store **fully managed** (no OpenSearch/Aurora to run).
  - Chunking: **default (~300 tokens), fixed-size (maxTokens, overlap %), hierarchical, none**. **Semantic chunking not supported** on managed KBs.
  - Connectors: **S3, Confluence, SharePoint, Web Crawler, Google Drive, OneDrive, custom**.
  - **Always hybrid search** (no semantic-only mode). **`RetrieveAndGenerate`** and **agentic retrieval** built in.
  - Results: **up to 100** per Retrieve call.
  - **Metadata**: `.metadata.json` sidecar (**up to 10 KB** per file in the migration guide), types STRING/NUMBER/BOOLEAN.
- **Setup flow**: IAM role (trust `bedrock.amazonaws.com`, S3 + `bedrock:InvokeModel` on the embedding model) → **`CreateKnowledgeBase` with type `MANAGED`** → **`CreateDataSource`** (type managed connector; asynchronous, 2–5 minutes to AVAILABLE) → **`StartIngestionJob`** and poll status.
- **API mapping**:
  - `kendra.create_index` → `bedrock-agent.create_knowledge_base`
  - `create_data_source` → `create_data_source`
  - `start_data_source_sync_job` → `start_ingestion_job`
  - `batch_put_document` → **no direct equivalent**: upload to **S3** then ingest
  - `retrieve` → `bedrock-agent-runtime.retrieve` (query in `retrievalQuery.text`; filter under **`managedSearchConfiguration`**)
  - **RAG generation**: Kendra needs an external LLM; BMKB has `retrieve_and_generate`.
- **Filter mapping**: `EqualsTo`→`equals`; `ContainsAny`→`in`; `ContainsAll`→`in` (partial); `GreaterThan`/`LessThan` (and OrEquals) map directly; `NotFilter`→`notIn`/`notEquals`; `AndAllFilters`→`andAll`; `OrAllFilters`→`orAll`. **`startsWith` and `stringContains` are not supported** on managed KBs.
- **Feature gaps and workarounds**:
  - **Query suggestions / autocomplete** → OpenSearch suggester or an LLM completion service.
  - **Faceted search (counts)** → metadata filters in the UI (no dynamic counts).
  - **Custom synonyms (thesaurus)** → expand the query in your app (works well because BMKB is hybrid).
  - **Spell check** → Lambda with SymSpell/TextBlob or an LLM before querying.
  - **Incremental learning (feedback)** → rerankers + your own feedback store; maybe fine-tune embeddings later.
  - **Custom Document Enrichment** → pre-processing with Step Functions/Lambda before S3.
  - **32 connectors vs 7** → export unsupported systems to **S3** on a schedule (EventBridge/Lambda) with metadata files, then trigger ingestion.
  - **ACLs** → use BMKB **ACL-aware connectors** where available or **metadata filters per user group**, and **test access** before cutover.
- **Chunking choice**: Kendra chunks internally. For BMKB the guide suggests **fixed-size ~200 tokens with 30% overlap** to start; use **hierarchical** for strongly structured documents.
- **Validate before cutover**: run **both in parallel**; compare **NDCG/MRR on a golden set**, **latency p50/p95/p99**, **throughput**, **completeness**; confirm **ingestion succeeded with no failed docs**, **filters behave**, **access control workarounds hold**, **error handling for new response shapes**, **monitoring/alerts**.
- **Cost model shift**: Kendra = **hourly per capacity** (+ connector fees). BMKB = **per GB stored + per query + model tokens** (predictable with size and usage; see `bedrock` notes for numbers).
- **No deadline** to migrate, but **no new Kendra features** will arrive.

## C. Kendra with Amazon Q Business and Bedrock
- **Q Business** can use a **Kendra index as its retriever** (bring your index instead of Q's native retriever). Access control is by the user's **email ID** passed to Kendra; if data sources do not use email-based ACLs, **only public documents** are used in answers.
- **Bedrock Knowledge Bases** can use a **Kendra GenAI index** as a managed retriever; combine with agents/flows.
- **Lex** can answer questions through a Kendra search intent.
- These integrations help **existing** Kendra owners avoid rebuilding indexes.

## D. When Kendra still makes sense (existing customers)
- Large **existing index** with many connectors and ACLs that work.
- Features BMKB lacks: **faceted search, query suggestions, synonyms, feedback learning, CDE hooks**.
- Teams that need a **search UI** (Experiences) more than RAG.
- A migration would cost more than the remaining benefit, and the service **remains fully supported**.
- Plan a **review** each year: usage, cost, features, and migration readiness.

## E. Cost control for existing Kendra
- **Delete unused or test indexes** (idle = billed).
- **Right-size** storage and query units (watch documents indexed vs storage unit, QPS vs query unit).
- Prefer **GenAI Enterprise** pricing granularity if eligible (lower base and units; connectors flat **$30/month**).
- Reduce **sync frequency** and filter what is crawled (connector hours and documents scanned are billed on Basic editions).
- Use **Developer Edition only for tests**.
- Tag indexes and track in **Cost Explorer/Budgets**.

## F. Scenarios: "If X → Y, because Z"
- **If** a startup wants Retrieval-Augmented Generation (RAG) over **Confluence** and **Amazon S3** content, **then** use **Amazon Bedrock Managed Knowledge Base (BMKB)**. **This works because** Amazon Kendra is **closed to new customers** from **30 July 2026**, and BMKB has managed connectors for **both** Confluence and S3, plus built-in **`RetrieveAndGenerate`** to produce answers.
- **If** a bank runs Kendra in production with **SharePoint Access Control Lists (ACLs)**, **facets** and **synonyms**, **then** **keep Kendra** for now and **plan a staged migration** to **Bedrock Managed Knowledge Base (BMKB)**. **This works because** Kendra stays **fully supported** for existing customers with **no migration deadline**, while BMKB needs **workarounds** for those features. Run both **in parallel** and test access control before cutover.
- **If** you need **autocomplete** in a search box after migrating to **Bedrock Managed Knowledge Base (BMKB)**, **then** use an **OpenSearch suggester** or an **LLM (Large Language Model) completion service**. **This works because** BMKB has **no query suggestions API**, so suggestions must come from a separate service.
- **If** a data source has **no BMKB connector** (for example **ServiceNow**), **then** run a **scheduled export to Amazon S3** (using **Amazon EventBridge** and **AWS Lambda**) with metadata files, then start an **ingestion job**. **This works because** S3 is always supported by **Bedrock Managed Knowledge Base (BMKB)**, and the schedule lets **you control how fresh** the data is.
- **If** the goal is an **employee assistant** and nobody wants to build a custom UI, **then** use **Amazon Q Business**, which can even use an existing **Kendra index as its retriever**. **This works because** Q Business is a **finished assistant app** with built-in generation and identity via **IAM (Identity and Access Management) Identity Center**. Catch: Q Business passes the user's **email ID**; without email-based ACLs, only **public documents** are used.
- **If** you need full control of **ranking**, **analyzers** and **scale**, **then** use **Amazon OpenSearch Service**, a search engine you design and tune yourself. **This works because** Kendra and **Bedrock Managed Knowledge Base (BMKB)** are **managed and opinionated**, so they are less tunable. OpenSearch is **flexible and cheaper at huge scale (verify)**, but **effort is high**: you build mappings, scaling and security.
- **If** answers must respect **per-user permissions**, **then** use **ACL-aware connectors** or **metadata filters per user group**, plus an **authenticated** user identity on each request. **This works because** retrieval does **not** apply permissions unless you filter: Kendra returns **all documents** if no user information is sent. Coverage of ACL-aware managed connectors in every Region is **(verify)**.
- **If** a migration test shows **lower recall** in **Bedrock Managed Knowledge Base (BMKB)** than in Kendra, **then** try **hierarchical chunking**, a **reranker**, adjusting **fixed-size chunks and overlap** (the guide suggests starting at **~200 tokens with 30% overlap**), and adding **synonyms in the query layer**. **This works because** Kendra **chunks and ranks internally** in its own way, so BMKB defaults (about **300-token** chunks) will not match it.
- **If** Kendra costs a lot but is **rarely used**, **then** **delete or downsize** storage and query units, or **move to Bedrock Managed Knowledge Base (BMKB)**. **This works because** Kendra bills **hourly per provisioned capacity**, whatever the query count, while BMKB charges **per GB stored, per query and per model token**, so low use costs less.
- **If** someone asks **"is Kendra deprecated?"**, **then** answer: it is in **maintenance mode**, still **fully supported** (bug fixes and security updates) for **existing customers**, but **closed to new customers**. **This works because** AWS announced no new features from **30 June 2026** and closure to new customers from **30 July 2026**, with **no end-of-life date**.

Verified from AWS docs on 2026-11-01 (Kendra availability change and migration guidance, index types, pricing, quotas).
Unconfirmed (verify): Q Business retriever details beyond the index-types page; Lex–Kendra intent naming; OpenSearch/Elasticsearch comparisons (general knowledge); BMKB metadata size limit (10 KB per migration guide vs other docs); whether ACL-aware managed connectors cover SharePoint/Confluence/Google Drive/OneDrive in every Region.

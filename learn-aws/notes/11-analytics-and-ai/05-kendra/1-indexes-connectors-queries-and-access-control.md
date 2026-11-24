# Amazon Kendra – 1. Status, indexes, connectors, queries and access control

Short notes. Each point is a fact you can be asked about.

## A. Status first (this changes how you use these notes)
- **Amazon Kendra is in maintenance mode.** Timeline from AWS docs:
  - **30 June 2026**: no new features or capability development.
  - **30 July 2026**: **no longer open to new customers.**
- **Existing customers keep full support** (bug fixes and security updates). No end-of-life date is stated.
- **AWS recommends Amazon Bedrock Managed Knowledge Base (BMKB)** for new search/RAG work and as the migration target (see `bedrock` notes, file 2).
- So: learn Kendra to **run or migrate existing systems** and to answer comparison questions; **do not plan new builds on it** unless your account is already a customer.
- Kendra **GenAI indexes** can still be used as a **retriever in Bedrock Knowledge Bases and Amazon Q Business** for existing customers.

## B. What Kendra is
- **Managed intelligent enterprise search and retrieval**. It uses NLP and deep-learning models to judge **semantic and contextual relevance**, not just keyword matches.
- **Components**:
  - **Index**: holds documents and makes them searchable.
  - **Data source (connector)**: connects to a repository and syncs it into the index.
  - **Document addition API** (`BatchPutDocument`): add documents directly.
  - **`Retrieve` API**: returns relevant **passages** (for RAG).
  - **`Query` API**: searches and can return **answers, FAQ matches and documents**.
- **Question types it handles**: **factoid** (who/what/when/where; short answers), **descriptive** (a sentence, passage or document), **keyword / natural-language** (resolves word meaning from context).
- **Integrations**: **Amazon Q Business**, **Bedrock Knowledge Bases**, **Amazon Lex** (search intent), S3, **Kendra Intelligent Ranking** (re-rank another search service's results).
- **Deleting an index** deletes all its connectors and **permanently deletes its document information**.

## C. Index editions
- **GenAI Enterprise Edition** (recommended by AWS for RAG):
  - Highest accuracy for **`Retrieve`** (hybrid keyword + vector, semantic embeddings, **re-ranker** models). `Query` accuracy is similar to the other editions.
  - **Smaller, more granular capacity units and lower starting price.** Can be a **managed retriever** for Bedrock KBs/agents/flows and Q Business.
  - **Limitations**: Regions **US East (N. Virginia) and US West (Oregon)** per the index-types page (the quotas page also lists Ireland and Sydney: **verify**); **English only**; **only v2.0 connectors**; user context filtering **only by user attributes** (no token-based or user-ID/group-based control); **`CreateAccessControlConfiguration` disabled**; Q Business uses the user's **email ID** for access (no email or no email-based ACL → only **public** documents).
- **Basic Enterprise Edition**: semantic search, **high availability**, production use. **All features** for `Query`; most for `Retrieve`.
- **Basic Developer Edition**: same semantic features for **proof of concept only**; **not for production**; **cannot add capacity units**.
- **Free trial**: GenAI Enterprise or Developer index up to **750 hours in the first 30 days**. **Connector usage is not free.** After the trial you pay for **every provisioned index even if empty and unqueried.**

## D. Capacity, pricing and quotas
- **Capacity is bought in units** (storage units and query units):
  - **GenAI Enterprise base**: **$0.32/hour** → up to **20,000 documents or 200 MB extracted text** and **0.1 QPS (about 8,000 queries/day)**. Extra storage unit **$0.25/hr**; extra query unit **$0.07/hr**.
  - **Basic Enterprise base**: **$1.40/hour** → up to **100,000 documents or 30 GB extracted text**, **0.1 QPS**. Extra storage unit **$0.70/hr**; extra query unit **$0.70/hr**.
  - **Basic Developer**: **$1.125/hour** → up to **10,000 documents or 3 GB**, **0.05 QPS (about 4,000/day)**; **no extra units**.
- **Connectors**:
  - **GenAI Enterprise**: flat **$30 per index per month** (includes up to **500 sync hours/month**), charged each month a connector is configured.
  - **Basic editions**: **$0.35 per hour while syncing + $1 per million documents scanned.**
- **Billing is by the hour for provisioned capacity**, not per query. An idle index still costs money. Delete test indexes.
- **Quotas (docs)**:
  - **10 indexes** per account (adjustable).
  - **Data source connectors per index**: **5** (Developer, fixed), **50** (Enterprise/GenAI, adjustable).
  - **Max document size via connector 50 MB**; via **`BatchPutDocument` 5 MB**; text extracted from one document **5 MB** (Basic).
  - **Query text 1,000 characters** (token words before truncation **30**, adjustable on Basic).
  - **Search results per query 100**; per page 100.
  - **Queries per second is shared by `Query` and `Retrieve`.** Enterprise single query unit = **0.1 QPS**; Developer = **0.05 QPS**; up to **100 extra query units** (GenAI max 100).
  - **Storage units**: Enterprise adds up to **100** extra; GenAI max **50** per index **(doc table wording is confusing: verify)**.
  - **Custom attributes per index 500**; **FAQs per index 30** (5 MB each; question up to 300 characters, answer up to 2,000; **max 4 FAQ results**); **1 thesaurus** per index (**10,000 rules**, 5 MB); **1 block list** (**20,000** items); **50 featured result sets**; **50 Kendra experiences** per index.
  - **Max 200 ACL entries** per document (`AccessControlList`); **user-group list 1,000** per query attribute.
  - **Intelligent Ranking (Rescore)**: **25 documents** per request, **100 title tokens**, **200 body tokens**, **50 rescore execution plans**.

## E. Documents and ingestion
- **Document types**: HTML, PDF, Word, PowerPoint, Excel, plain text, CSV, JSON, XML, RTF, Markdown, email, images with text (OCR) **(verify exact list)**.
- **Document metadata/attributes**: built-in (`_category`, `_created_at`, `_last_updated_at`, `_source_uri`, `_view_count`, `_authors`, `_user_id`, `_group_ids`, `_data_source_id`, `_language_code`) and **custom attributes** (string, string list, long, date). Used for **filters, facets, sorting and relevance tuning**.
- **`BatchPutDocument`**: add up to 10 documents per call **(verify)**, optional ACL, attributes, and `AccessControlConfigurationId`.
- **Sync (data source sync job)**: **on-demand or on a schedule**; syncs **new, changed and deleted** files. Run-schedule is cron-like.
- **S3 connector**: **metadata files** (`<file>.metadata.json`) carry attributes and the **ACL**; an **S3 ACL configuration file** (up to 100 prefixes, 50 MB) can set access by prefix.
- **Custom Document Enrichment (CDE)**: **Lambda hooks before/after text extraction** to transform content, add metadata, redact PII. Bedrock BMKB has **no equivalent** (use a pre-processing pipeline).
- **Featured results, FAQs, thesaurus (synonyms)** let admins steer answers. **FAQs** return curated Q&A directly.
- **Experience Builder / Kendra experiences**: ready-made search UI **(verify naming)**.

## F. Connectors (data sources)
- **About 32+ native connectors** (BMKB has **7**: S3, Confluence, SharePoint, Web Crawler, Google Drive, OneDrive, custom).
- Families:
  - **Storage/files**: **S3**, **FSx** (Windows/ONTAP), **Box**, **Dropbox**, **Google Drive**, **OneDrive**, **SharePoint**.
  - **Wikis/CMS**: **Confluence**, **Alfresco**, **Drupal**, **Adobe Experience Manager**, **Quip**.
  - **Collaboration**: **Slack**, **Microsoft Teams**, **Yammer**, **Gmail**, **Exchange**.
  - **Ticketing/dev**: **Jira**, **ServiceNow**, **Zendesk**, **GitHub**.
  - **CRM**: **Salesforce**.
  - **Databases**: **Aurora/RDS (MySQL, PostgreSQL, Oracle, SQL Server)**, **MySQL, PostgreSQL, Oracle, SQL Server, IBM DB2** via JDBC.
  - **Web**: **Web Crawler** (public/internal sites, sitemaps).
  - **Custom**: write your own with `BatchPutDocument`.
- **Connector versions**: **v1.0** and **v2.0**. **GenAI Enterprise supports only v2.0.** Some connectors have behavior differences (for example Confluence user ID is the **account ID** in v1 Cloud, the **email** in v2).
- **VPC/network**: connectors can run **inside your VPC** to reach private repositories (subnets, security groups).
- **Credentials** live in **Secrets Manager**; the connector role needs permissions to the secret and the repository.
- **Sync limits**: GenAI Enterprise **500 sync hours/month** per index (adjustable).
- **No connector for a system?** Export content to **S3** (with metadata and ACL files) and use the S3 connector, or write a custom ingestion pipeline.

## G. Searching: `Query` vs `Retrieve`
- **`Retrieve` API**: returns **up to 100 passages** (semantic **chunks of up to about 200 tokens**) from documents, ranked **for RAG**. Use with an LLM. Shares QPS with `Query`.
- **`Query` API**: search results with three **result types**: **ANSWER** (extracted answer), **DOCUMENT** (ranked docs with excerpts), **QUESTION_ANSWER** (FAQ match). Better for **search boxes**.
- **Features on `Query`**: **facets** (counts per attribute), **sorting**, **collapse/expand** results, **suggested spell corrections**, **query suggestions (autocomplete)**, **boolean/exact/wildcard queries**, **confidence score buckets** (VERY_HIGH … LOW), **document ranking**.
- **Filters**: `AttributeFilter` with `EqualsTo`, `ContainsAll`, `ContainsAny`, `GreaterThan(OrEquals)`, `LessThan(OrEquals)`, `AndAllFilters`, `OrAllFilters`, `NotFilter`.
- **Relevance tuning**: **boost** by data source, document field, **freshness** (date), **count** (views), or specific values. Weights are per index.
- **Incremental learning**: `SubmitFeedback` (click/relevance signals) improves ranking over time. **BMKB has no equivalent.**
- **Query suggestions** are built from **search history and document vocabulary**; block lists remove words.
- **Kendra Intelligent Ranking** (`Rescore` API): semantically **re-rank results from another search engine** (OpenSearch, Elasticsearch, Solr) without moving the data. **Capacity units**, **25 docs per request**.

## H. Access control (document-level security)
- Each document can have an **ACL** (allow/deny **users and groups**; data sources can be principals). **Documents with no ACL are public.**
- **Where ACLs come from**: **connectors crawl them** from the source (for example Confluence/SharePoint/Salesforce permissions); **S3** uses the **metadata file**; **`BatchPutDocument`** uses the **`Principal`** objects (up to **200 entries**).
- **Query-time identity** (you must supply an **authenticated** user):
  - **Token-based**: a **JWT / JSON** token validated by the index (index-level token configuration). **Not supported on GenAI Enterprise.**
  - **User ID + groups + data-source groups** in **`UserContext`**; or only user ID if you registered mapping with **`PutPrincipalMapping`**; can resolve groups from **IAM Identity Center** (`UserGroupResolutionConfiguration`).
  - **User attributes** (`_user_id`, `_group_ids`) in **`AttributeFilter`** (up to 100 groups). **The only method on GenAI Enterprise.**
- **If no user information is sent, Kendra returns all documents.**
- **Important**: user context filtering is **not authentication**. **Your app must authenticate the user and send correct identity.** A bug here = data leak.
- **`CreateAccessControlConfiguration`**: change document access **without re-indexing** (S3 sources and `BatchPutDocument` docs; Enterprise/Developer only).
- **Database connectors** support only **allow lists of groups** from a column (semicolon-delimited string): **no deny lists, no individual users**.
- **Gotchas**: Confluence needs the user's email **visibility = Anyone**; OneDrive/SharePoint group IDs need a **site-name hash + `|` + group name** format; group names are lower-case in Confluence.

## I. Security, operations and monitoring
- **Encryption** at rest with **KMS** (customer-managed key optional) and TLS in transit. **IAM roles** for the index (CloudWatch logs), data sources (repo + Secrets Manager + S3), and users (`kendra:Query`, `kendra:Retrieve`).
- **VPC endpoints (PrivateLink)** for the Kendra API (`kendra`, `kendra-ranking`) **(verify)**.
- **Logging/audit**: **CloudTrail** for management/API calls; **CloudWatch Logs** for sync job logs and document-level ingestion status; **CloudWatch metrics** for documents indexed, query counts, sync success/fail **(verify exact metric names)**.
- **Tags** on indexes/data sources for cost allocation and IAM.
- **Resilience**: Enterprise editions are **highly available** (multi-AZ); Developer is not production-grade.

## J. Troubleshooting (symptom → cause → fix)
- **Documents not searchable** → sync failed, unsupported type/size, ACL excludes the user, wrong index/data source → check sync history and CloudWatch logs.
- **Everyone sees everything** → no ACL on documents, or the app is not sending user context → fix connectors/metadata and the query call.
- **Nobody sees restricted documents** → user/group names do not match ACL strings (email vs account ID, case) → align IDs.
- **Throttling on `Query`/`Retrieve`** → QPS (shared by both APIs) exceeds capacity → add **query units**.
- **Index full** → documents/GB over storage units → add **storage units** or prune.
- **Poor ranking** → add relevance tuning, FAQs, synonyms; use GenAI edition for RAG; feed feedback.
- **Q Business answers only from public docs** → ACLs not email-based or the user's email is missing.
- **Cost surprise** → idle indexes, extra capacity units, connector sync hours/documents scanned.

## K. Scenarios: "If X → Y, because Z"
- If you are a new customer starting search/RAG today → **Bedrock Managed Knowledge Base**, because Kendra is closed to new customers.
- If you already run Kendra and want RAG with Bedrock → connect the **GenAI Enterprise index** as a retriever (or migrate to BMKB), because the index can be reused by Bedrock KBs/Q Business.
- If you rely on facets, query suggestions, synonyms, spell check, feedback learning → **plan workarounds before migrating**, because BMKB lacks them (use metadata filters, OpenSearch suggesters, query rewrite, pre-processing Lambdas).
- If your repository is not supported by BMKB (it has 7 connectors) → **export to S3 with metadata sidecars and ingest**, because S3 is universally supported.
- If you need user-level security from SharePoint/Confluence → **Kendra connector ACLs + user context filtering with an authenticated identity**, because connectors crawl permissions, but your app must pass the user.
- If you need to revoke a user's access without re-indexing → **`CreateAccessControlConfiguration` (S3/BatchPutDocument docs)**, because it updates ACLs in place.
- If the app needs an extracted direct answer or FAQ → **`Query` API**; if it needs passages for an LLM → **`Retrieve` API**, because they return different result shapes.
- If another search engine is already in place → **Kendra Intelligent Ranking**, because it re-ranks its results without migrating data.
- If you want to test cheaply → **Developer Edition or GenAI free trial (750 hours/30 days)**, but **delete** the index afterwards, because empty indexes still bill hourly.
- If QPS limits hit → **add query capacity units**, because 0.1 QPS per Enterprise unit is shared by `Query` and `Retrieve`.

Verified from AWS docs on 2026-11-01 (Kendra overview, availability change/migration guide, index types, quotas, pricing, user context filtering).
Unconfirmed (verify): GenAI index Regions (two docs disagree); storage-unit quota wording; supported document-type list; `BatchPutDocument` batch size; CloudWatch metric names; PrivateLink endpoint names; Kendra experiences naming; whether any new-customer exceptions exist; connector count (about 32 per the migration guide).

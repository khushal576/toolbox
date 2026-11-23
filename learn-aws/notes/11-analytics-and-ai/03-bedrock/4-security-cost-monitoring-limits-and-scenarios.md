# Amazon Bedrock – 4. Security, data retention, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Data privacy and retention
- **Model Deployment Accounts**: in each Region there is one **AWS-owned deployment account per model provider**. AWS deep-copies the provider's inference software there. **Model providers have no access** to those accounts, so they **cannot see Bedrock logs, prompts or completions**.
- **Your data is not used to train the base models** and is **not shared with model providers** (sharing with providers is **not supported today**). Customization creates a **private copy** of the model for you.
- **Data retention is now a setting** (per Region, at **account** level, and at **project** level for `bedrock-mantle`). Modes, from least to most permissive:
  - **`none`**: **zero data retention**. Nothing written to durable storage. On the Responses API `store` defaults to false (and `store=true` is rejected); no background mode.
  - **`default`**: the **model's own policy** applies. AWS may keep data for **abuse detection**; the provider does not receive it.
  - **`aws_review`**: inputs/outputs may be **retained and reviewed by AWS** (inside the AWS boundary) because some providers require **human review** as a condition of access. Retained for **up to 30 days** (cross-Region: in the destination Region).
  - **`provider_data_share`** (**legacy**): no longer shares anything; behaves like `aws_review`; still satisfies models that need review.
  - **`inherit`**: no opinion; defer to a broader scope. **Effective mode = first non-inherit value of project → account → model default.**
- **Models can require a minimum mode** (`allowed_modes`). Example: **Claude Fable 5 and 5.1** need **`aws_review`** (or the legacy mode). If your effective mode is `none`/`default`, the model shows **`unavailable`** on mantle and gives **`ValidationException`** on runtime.
- Setting `aws_review` does **not** make every model retain data. Each model's own `allowed_modes` decides (a model that allows `none` stays zero-retention).
- **Claude models released before Fable 5 have no retention change.** ZDR for models that require retention is **per account and per model** through your account manager (Anthropic manages eligibility for Claude).
- **No console UI at launch** for retention: use the **API/SDK** (`PutAccountDataRetention` on control plane or mantle).
- **Enforce with IAM/SCP**: condition keys **`bedrock:DataRetentionMode`** and **`bedrock-mantle:DataRetentionMode`** on the write actions (for example **deny any value except `none`**, or deny `aws_review` to stop human review). Models that require review then become unavailable.
- **Abuse detection**: automated checks run on requests; see the AWS abuse-detection page for what is retained.
- **Do not put secrets in tags or free-text name fields** (they can appear in billing and diagnostics).

## B. Identity and access (IAM)
- **Identity-based policies** control who may call what. Typical actions: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` (also needed for Converse and Responses on runtime), `bedrock:ApplyGuardrail`, `bedrock:Retrieve`, `bedrock:RetrieveAndGenerate`, `bedrock:StartIngestionJob`, `bedrock:CreateModelCustomizationJob`, `bedrock:CreateProvisionedModelThroughput`, `bedrock-mantle:CreateInference`.
- **Resource scoping**: restrict to specific **foundation-model ARNs**, **inference-profile ARNs** (and all destination Region models for CRIS), **guardrail ARNs**, **KB ARNs**.
- **Condition keys** to know: `bedrock:GuardrailIdentifier` (require a guardrail on every call), `aws:RequestedRegion`, tags on resources, `bedrock:DataRetentionMode`.
- **Require guardrails by policy**: deny `InvokeModel`/`Converse` unless `bedrock:GuardrailIdentifier` equals your guardrail (or use **enforced guardrails**, file 3).
- **Service roles** (Bedrock assumes them): KB role (S3, embedding model, vector store), customization job role (S3 training data/output, KMS), batch inference role (S3), evaluation role, model invocation logging role, Flows role, Agent role (Classic). Trust principal `bedrock.amazonaws.com` with **`aws:SourceAccount` / `aws:SourceArn`** conditions (confused-deputy protection).
- **`iam:PassRole`** is needed for the user who creates jobs with a service role.
- **Service access control for tiers**: IAM can control who may use **service tiers** (Priority, Flex, Reserved).
- **API keys**: **short-term** (preferred; derived from IAM credentials, expire) and **long-term** keys. Keys still need IAM permissions and map to a principal. Treat long-term keys as secrets (Secrets Manager, rotation).
- **Resource-based policies**: guardrails (cross-account `ApplyGuardrail`), managed knowledge bases (cross-account).
- **Use roles, not users**: instance/task/function roles; **IAM Identity Center** for people. **Permission boundaries and SCPs** to confine who can enable Marketplace models or large models.
- **Marketplace/third-party model subscriptions** run through AWS Marketplace permissions **(verify)**.

## C. Encryption and network
- **In transit**: TLS 1.2+ (1.3 recommended). **FIPS endpoints** available for FIPS 140-3.
- **At rest**: AWS-managed keys by default. **Customer-managed KMS keys** for custom models, customization/training output, KB data/vector store, batch/evaluation output, invocation logs (S3 SSE-KMS or CloudWatch Logs KMS), AgentCore/agents resources. Key policy must allow the Bedrock service principal and your roles.
- **PrivateLink (interface VPC endpoints)** for the Bedrock endpoints (`bedrock`, `bedrock-runtime`, `bedrock-agent`, `bedrock-agent-runtime`, and mantle) keep traffic off the internet and **avoid NAT egress charges** (relevant for large prompts). Attach **endpoint policies** to limit models/actions.
- **Customization, batch inference and evaluation jobs** can run **inside your VPC** with security groups and subnets (and **S3 gateway endpoint** for data).
- **KB vector stores**: OpenSearch Serverless can be reached by **VPC endpoint**; a **managed OpenSearch domain for KB must be public** (VPC domains not supported); Aurora uses the **Data API** and Secrets Manager.
- **Logging safety**: invocation logs contain **full prompts and answers**: protect the S3 bucket/log group (KMS, least privilege, retention) or avoid logging sensitive modalities.
- **Prompt injection and data leakage** are the main GenAI threats: use **Guardrails (prompt attack, PII)**, treat retrieved text as **untrusted**, scope tool permissions, validate model output before acting (for example before running generated SQL), and **log + review**.

## D. Audit and governance
- **CloudTrail**: management events for control-plane calls (CreateGuardrail, CreateModelCustomizationJob, etc.); **data events** for runtime invocation (opt-in) **(verify exact event names)**. For cross-Region inference, CloudTrail logs in the **source Region** with `additionalEventData.inferenceRegion`.
- **Model invocation logging**: **disabled by default**. Destinations: **S3**, **CloudWatch Logs**, or both (**same account and Region only**). Logs full request/response JSON up to **100 KB** per body inline; **larger bodies and binary data (images)** go to **S3** under the data prefix. Choose modalities (text, image, embedding, video). Covers **`bedrock-runtime`** calls (Converse, InvokeModel, and the OpenAI-compatible APIs on runtime) but **not** `bedrock-mantle` calls.
  - Record fields: `requestId`, `operation`, `modelId`, `identity.arn` (caller), optional **`requestMetadata`** tags, token counts, input/output bodies.
  - Needs a bucket policy for `bedrock.amazonaws.com` (with `aws:SourceAccount`/`SourceArn`), bucket **ACLs disabled**, KMS key policy allowing `kms:GenerateDataKey`; for CloudWatch Logs an IAM role trusted by Bedrock.
  - Query with **Athena** (S3), **Logs Insights** (for example sum tokens by `identity.arn`), or load into OpenSearch.
- **AWS Config / Security Hub / Audit Manager**: Bedrock guidance and controls exist **(verify)**.
- **Organizations**: Bedrock policy type for **enforced guardrails** (file 3); **SCPs** for Regions and model access.
- **Compliance**: Bedrock is in scope for common programs (SOC, ISO, HIPAA eligibility, GDPR tooling, FedRAMP in some Regions **(verify per Region/model)**).
- **Model lifecycle** metric **`LegacyModelInvocations`** shows calls to legacy models so you can migrate before end of life.

## E. Monitoring (CloudWatch namespace `AWS/Bedrock`)
- **Runtime metrics** (dimension `ModelId`; some metrics also `ModelId + ContextWindow`):
  - **`Invocations`**: accepted requests (includes ones that later failed; **excludes throttled** and validation-rejected requests).
  - **`InvocationLatency`**: from request sent to **last token** received.
  - **`TimeToFirstToken`**: for streaming APIs (user-perceived speed).
  - **`InvocationClientErrors`** (4xx, includes quota-exceeded rejections) and **`InvocationServerErrors`** (5xx).
  - **`InvocationThrottles`**: throttled calls (not in the other counters). SDK retries change what you see.
  - **`InputTokenCount`**, **`OutputTokenCount`**, **`CacheReadInputTokenCount`** (reduced price, no quota), **`CacheWriteInputTokenCount`** (counts toward quota), **`OutputImageCount`**.
  - **`EstimatedTPMQuotaUsage`**: **approximation** only; real throttling is based on reserved `input + max_tokens`.
  - **`LegacyModelInvocations`**.
  - **Invocation-logging delivery metrics**: S3/CloudWatch/large-data **DeliverySuccess/Failure**.
- **Trap**: requests that fail before the model is identified are published **without `ModelId`**. Query **without a dimension** to count everything.
- **Long-context requests** (billed at a long-context rate) publish an extra `ContextWindow=1M` series that is a **subset** of the `ModelId` series, not additional usage.
- **OTPS** (output tokens per second) helps decide if higher latency is service slowness or just longer answers.
- **Mantle** has its own metrics page and its own quotas.
- **Other metric sets**: **Guardrails** (interventions, text units), **Agents**, **Knowledge Base ingestion**, **AgentCore Observability** (OpenTelemetry traces in CloudWatch).
- **Alarms to set**: `InvocationThrottles` > 0, `InvocationServerErrors` rate, `InvocationLatency`/`TimeToFirstToken` p95, token spend per hour, `LegacyModelInvocations` > 0, logging delivery failures.
- **EventBridge**: notifications for **batch/customization job state changes**.

## F. Cost: what you pay for
- **On-demand inference**: **per 1M input tokens and per 1M output tokens**; price **varies by model** (docs examples: DeepSeek v3.2 about **$0.62 / $1.85**, Mistral Large 3 about **$0.50 / $1.50**). **Output tokens cost more** than input. **Long-context** requests may bill at a higher rate. Embeddings are priced per input token; image models per image.
- **Cross-Region**: **no routing fee**; **global** profiles about **10% cheaper**; geographic = standard price. Price is for the **source Region**.
- **Service tiers**: **Priority about +75%**, **Flex about −50%**, **Reserved** = fixed monthly price per 1K TPM for 1/3 months (account team) **(verify)**.
- **Batch**: about **50% cheaper** than on-demand (supported models).
- **Prompt caching**: cache **reads** cheap (for example about 90% off on some models; one doc note says a **50% drop** in cache-read price for Claude Sonnet 5.5 from **7 Oct 2026**), cache **writes** can cost more (for example **1.25x** input on newer OpenAI models).
- **Provisioned Throughput**: **per model unit per hour** (no commitment / 1 month / 6 months). Docs examples: Cohere Command **$49.50 / $39.60 / $23.77** per MU-hour; many providers (Anthropic) are **contact account team**. Billed **even when idle** until deleted.
- **Customization**: **tokens × epochs** (fine-tuning), **per training hour** (RFT), **monthly storage per custom model** (docs example **$1.95**), then inference through PT or CMI.
- **Custom Model Import**: no import fee; **per Custom Model Unit per minute (5-minute windows)** while active (US example **$0.05718** per CMU-minute) + storage.
- **Knowledge Bases**: embedding tokens, **vector store** cost (OpenSearch OCUs, S3 Vectors storage/queries, Aurora ACUs), parsing (FM tokens or BDA), semantic-chunking model calls, reranker, **managed KB** ($5/GB-month storage, $1 per 1,000 Retrieve, $4 per 1,000 agentic Retrieve + $1 per 1,000 underlying retrieves) **(verify)**.
- **Guardrails**: per **1,000 text units** per policy (content filters about $0.15, denied topics $0.15, grounding $0.10, PII $0.10; regex/word filters free); **image content filter per image**; automated reasoning per policy.
- **Data Automation**: per page/image/minute and fields **(verify)**.
- **Intelligent Prompt Routing**: about **$1 per 1,000 requests** + tokens **(verify)**. **Model evaluation**: human tasks about **$0.21 each** + inference.
- **Web Search tool**: per query. **AgentCore**: consumption-based (runtime, memory, gateway, etc.).
- **Hidden costs**: NAT/data transfer (use **PrivateLink**), CloudWatch Logs ingestion for invocation logs, S3 for logs/batch, Lambda/Step Functions orchestration, KMS requests, re-embedding after model changes.
- **Cost attribution** (pick by need):
  - **IAM principal attribution**: bills show **per user/role** in Cost Explorer/CUR 2.0 (works on both endpoints). Behind a gateway, **assume a role per user (RoleSessionName / session tags)**.
  - **Application inference profiles** (+ cost allocation tags): per **application/team** on runtime (not on the Responses API there).
  - **Projects** (Responses/Chat Completions) and **Workspaces** (Anthropic Messages) on **mantle**.
  - **Per-request metadata tags**: per-prompt token counts in **invocation logs** only (you compute cost); not on mantle.
  - **Native methods give daily billed dollars; invocation logs give per-request detail.**
  - Use **CUR 2.0** (not classic CUR) for the new attribution columns **(verify)**; set **Budgets + Cost Anomaly Detection** on Bedrock service spend.
- **Cost-cutting checklist**:
  - Pick the **smallest model** that passes your **evaluation**.
  - **Distill** a big model to a small one; use **intelligent prompt routing**.
  - **Prompt caching** for long, repeated context; keep static content first.
  - **Reduce tokens**: shorter prompts, concise output instructions, **lower `max_tokens`**, trim retrieved chunks (rerank, fewer chunks).
  - **Batch or Flex** for offline work; **Global CRIS** (about 10% cheaper) when residency allows.
  - **S3 Vectors** instead of always-on OpenSearch for low-QPS RAG; smaller embedding dimensions.
  - Avoid paying for **idle Provisioned Throughput**; delete unused PT, KBs, collections, custom models (storage).
  - Block abuse early with **Guardrails input checks** (a blocked input saves the model call) and **usage plans/WAF** at the API layer.
  - Set **budget alerts** (see the Budgets notes) and a **token quota** per team.

## G. Limits and numbers to remember
- **Throttling basis**: TPM + RPM (embeddings: RPM only), plus TPD; separate quotas for **`bedrock-runtime`** and **`bedrock-mantle`**.
- **Quota formula**: reserved at start = **input tokens + `max_tokens`**; final = `input + cacheWrite + output × burndown`; cache reads excluded.
- **Burndown**: Claude 4.7 and below **5x**; Opus/Sonnet 5.x, Fable 5.1 and OpenAI GPT-5.6 on runtime **10x**; Claude 4.8 **15x**; most others **1x** **(verify per model)**.
- **Prompt caching**: minimum **512–4,096** tokens per checkpoint (model dependent), up to **4** checkpoints, TTL **5 min** (refreshes) / **1 h** (Claude) / **30 min** (newer OpenAI).
- **Reserved tier minimum**: **100,000 input TPM** and **10,000 output TPM**.
- **Provisioned Throughput commitments**: none / **1 month** / **6 months**.
- **Managed KB**: 10,000 KBs, 200 data sources/KB, 50 concurrent ingestion jobs, 10 TB/KB, **600 Retrieve RPM/KB** (burst 25 RPS), 300 agentic requests/min, 10,000 characters per query.
- **Default KB retrieval**: **5** results; filters **up to 5** per group.
- **Default chunking**: about **300 tokens**; Titan V2 dimensions **1,024/512/256**.
- **S3 Vectors**: dimensions **1–4,096**, about **1 KB** custom metadata and **35 keys** per vector.
- **Custom Model Import**: weights **< 200 GB text / 100 GB multimodal**, context **< 128K**, 4 Regions.
- **Invocation logging**: inline body **100 KB**, larger to S3; same account and Region only.
- **Agents Classic**: closed to new accounts from **30 July 2026**.
- **Guardrail enforcement**: one effective org policy per account; automated reasoning **not** supported in enforced guardrails.
- **Quota increases** are **not automatic** and depend on account history.

## H. Troubleshooting (symptom → cause → fix)
- **`ThrottlingException` (429)** → TPM/RPM exceeded, or `max_tokens` too high → lower `max_tokens`, backoff + jitter, cross-Region profile, cache, batch/Flex, request quota increase.
- **`AccessDeniedException` calling a model** → missing `bedrock:InvokeModel` on the model/profile ARN, SCP blocks Region/model, Marketplace/EULA not accepted, or model not enabled → fix policy, enable access.
- **AccessDenied only with `us.`/`eu.`/`global.` profile** → missing permission on a destination Region or SCP deny → allow all profile Regions.
- **`ValidationException` on a specific model** → unsupported parameter (for example `ttl` for caching, `toolConfig` in batch), or model requires **`aws_review`** retention that your account lacks.
- **Model shows unavailable** → retention mode below the model's requirement, model gated, or not in this Region/endpoint.
- **`ModelTimeoutException` / long latency** → very long output, big context, queueing on a busy model → stream, shorten, Priority tier, smaller model, check OTPS.
- **High `InvocationServerErrors`** → transient service issue → retry with backoff, fall back to another model/Region.
- **Guardrail blocks too much or too little** → tune strengths/thresholds, test in the test window, use Standard tier, allow-list tuning; remember updates to underlying models.
- **KB returns nothing** → not synced, wrong dimension/model, strict filter, permissions on role/store → file 2.
- **Invocation logs missing** → logging off by default, bucket policy/KMS/role wrong, **mantle calls not logged**, different Region/account.
- **Costs spike** → long contexts, high output tokens, retries on throttle, forgotten Provisioned Throughput, embedding re-ingestion, logging volume → find with `identity.arn`/request metadata, CUR 2.0.
- **Batch job fails** → bad JSONL, role lacks S3 access, record with unsupported field (for example tools in Converse format), provisioned model used.

## I. Scenarios: "If X → Y, because Z"
- If legal requires that prompts are never stored → set **`data_retention_mode: none`** (and use models that allow it), then **deny other modes with an SCP** (`bedrock:DataRetentionMode`), because the setting controls retention and models that need review become unavailable.
- If a team wants Claude Fable 5.x but gets ValidationException → set the account/project to **`aws_review`**, because that model requires human review by AWS.
- If security wants proof that every call uses a guardrail → **enforced guardrails (account/org)** or an IAM condition on **`bedrock:GuardrailIdentifier`**, because they apply regardless of app code.
- If traffic must not leave the AWS network → **interface VPC endpoints (PrivateLink)** for `bedrock-runtime`/agent endpoints with endpoint policies, because it removes internet/NAT paths.
- If you need to know which user spent the tokens → **IAM principal attribution** (role per user/session tags) for dollars, or **request metadata + invocation logs** for per-prompt detail, because native cost data is per identity/tag per day.
- If you need cost per product/app → **application inference profiles with cost allocation tags** (runtime) or **Projects/Workspaces** (mantle), because they tag spend on the bill.
- If invocation logs are empty for OpenAI-compatible traffic on mantle → expected; use **runtime** or other monitoring, because logging only covers `bedrock-runtime`.
- If you must audit prompts and answers → **enable model invocation logging to S3 with KMS and retention**, because it is off by default and stores full bodies (protect it).
- If latency is high but token counts are normal → check **TimeToFirstToken, OTPS, throttles/queueing**, then try **Priority tier**, because slowness can be service-side.
- If spend is too high with simple tasks → **smaller model, distillation, caching, batch/Flex, tighter `max_tokens`**, because token volume and model size drive cost.
- If you paid for Provisioned Throughput but traffic dropped → **delete it (after commitment)** or move to on-demand/Reserved, because PT bills hourly even when idle.
- If an auditor asks who changed a guardrail or enabled a model → **CloudTrail management events**, because control-plane actions are logged there.
- If a model you rely on is deprecated → watch **`LegacyModelInvocations`** and the lifecycle dates, then re-evaluate a replacement with model evaluation, because legacy models reach end of life.
- If an LLM answer will trigger an action (SQL, API call) → **validate and constrain it** (allow-list, read-only role, Policy), because model output is untrusted input.

Verified from AWS docs on 2026-11-01 (data protection, data retention, VPC, invocation logging, runtime metrics, cost management, pricing page excerpts, quotas/burndown pages).
Unconfirmed (verify): CloudTrail data-event names for runtime; compliance program coverage per Region/model; AWS Marketplace subscription permissions; the 90%-off cache-read example (only the Sonnet 5.5 50% drop and the 1.25x write cost are in the docs); long-context pricing details; Priority/Flex/batch percentages by model; Config/Security Hub/Audit Manager guidance; CUR 2.0 column names for Bedrock; mantle metrics and quotas details; retention behavior in Regions you have not configured (docs: falls back to the model default).

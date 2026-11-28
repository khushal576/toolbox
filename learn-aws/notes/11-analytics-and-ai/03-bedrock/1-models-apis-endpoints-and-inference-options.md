# Amazon Bedrock – 1. Models, APIs, endpoints and inference options

Short notes. Each point is a fact you can be asked about.

## A. What Bedrock is
- **Amazon Bedrock** is a fully managed service to use **foundation models (FMs)** from many providers through one set of APIs, with no servers to run.
- It also bundles the parts around a model: **Knowledge Bases (RAG), Agents/AgentCore, Guardrails, Flows, prompt management, evaluation, customization, Data Automation**.
- Pick it when:
  - You want GenAI in an app/pipeline without hosting models (summarize, classify, extract, chat, embed, generate).
  - You need a **choice of models** and the ability to swap them.
  - Data privacy matters (see file 4: prompts are not shared with model providers or used to train their models; some models require AWS-side retention and review, controlled by a **data retention mode**).
- Avoid or compare when:
  - You need to host **your own** open model or custom training loop → **SageMaker AI** (see the `sagemaker-ai` notes).
  - You only need classic ML tasks (OCR, sentiment) → **Textract / Comprehend** are cheaper and simpler.
  - You need enterprise search with connectors and per-user ACLs out of the box → **Kendra / Amazon Q Business**.
- **Data-engineering uses**: summarize or classify text in a pipeline, extract fields from documents (with **Bedrock Data Automation**), create **embeddings** for vector stores, generate SQL or metadata, describe schemas, quality-check data, build RAG over data-lake documents.

## B. Models available (names change fast: check the model cards)
- **100+ models** from many providers. Examples named in current AWS docs:
  - **Amazon**: **Nova** family (Nova 2 Lite, Pro, Lite, Micro; multimodal embeddings) and **Titan** (text embeddings, image generator).
  - **Anthropic Claude**: the 5.x line (for example **Fable 5.1, Opus 5.5, Sonnet 5.5, Haiku 5.5**; some tiers such as "Mythos" are **gated**), plus older 4.x/3.x models.
  - **OpenAI**: the GPT-5.6 and GPT-6 families (for example Sol, Terra, Luna, Astra).
  - **Others**: DeepSeek, Moonshot (Kimi), MiniMax, xAI (Grok), Meta Llama, Mistral, Cohere (embed, rerank), Qwen, Stability AI, and more.
  - Third-party models can also come through **Amazon Bedrock Marketplace** **(verify)**.
- **Model types by job**:
  - **Text/chat/reasoning** models (most common).
  - **Multimodal** (image/document understanding; some audio/video).
  - **Embedding** models (text → vector): Titan Text Embeddings V2, Cohere Embed, **Nova multimodal embeddings** (text, image, audio, video) **(verify)**.
  - **Reranking** models (Cohere Rerank, Amazon Rerank) to reorder retrieved chunks.
  - **Image/video generation** models (Nova Canvas/Reel, Stability).
- **Model access**: models are enabled per account/Region; serverless models are mostly **available by default** now, some require **accepting an end-user agreement** or are **gated/limited availability** **(verify current console behavior)**.
- **Lifecycle**: models go **Active → Legacy → End of life**. Legacy models still work but have an EOL date; **plan migrations** (pin the model ID and track the lifecycle notices).
- **Model cards** ("models at a glance") list model ID, Regions, modalities, context window, price, which endpoints/APIs, caching support and service tiers. The old "supported models" page redirects there.
- **Context window** = total tokens for input + output (examples in docs: **~1,050,000** tokens for GPT-6 Astra with up to 128,000 output; **500K** for Grok 4.6). Bigger context = more cost and latency, not always better.
- **Choosing a model**: start with a small/fast model, test accuracy on your own data, move up only if needed. Use **model evaluation** (file 3) to compare.

## C. Endpoints and APIs
- **Control-plane vs data-plane** endpoints:
  - **`bedrock`**: manage models, custom models, guardrails, provisioned throughput, inference profiles, batch jobs.
  - **`bedrock-runtime`**: **inference** (this is the recommended endpoint for new apps).
  - **`bedrock-agent`** / **`bedrock-agent-runtime`**: build and **query** Knowledge Bases and Agents/Flows.
  - **`bedrock-mantle`**: a second inference endpoint (OpenAI-compatible Responses/Chat Completions + Anthropic Messages API).
- **`bedrock-runtime` APIs**:
  - **`InvokeModel` / `InvokeModelWithResponseStream`**: **model-specific JSON body** (each provider has its own format). Use for non-chat tasks (embeddings, image generation) and provider-native features.
  - **`Converse` / `ConverseStream`**: **one consistent message format across models** (system prompt, messages, tool use, documents/images, guardrails, inference parameters). **Recommended for chat/text** because you can swap models by changing the model ID.
  - **Chat Completions** and **Responses API** (OpenAI-compatible), and **Messages API** (Anthropic-native) are also available here, using `/openai/v1` or `/anthropic` paths.
  - **Model-specific params** can still be passed through Converse in a model-specific field.
- **`bedrock-mantle` extras**: server-side tools (for example **web search**), **background/asynchronous** inference, **Projects** (OpenAI-style) and **Workspaces** (Anthropic-style) for isolation and cost tracking, and a few mantle-only models. **No** InvokeModel/Converse, **no Guardrails**, **no cross-Region inference profiles**, no intelligent prompt routing.
- **Same token price** on both endpoints for the same model. Choose by features, not cost.
- **Authentication**: **SigV4** (IAM roles) or **Bedrock API keys** (short-term or long-term; work with OpenAI SDKs by changing the base URL and key). An API key still maps to an IAM principal that needs permissions.
- **IAM actions**: `bedrock:InvokeModel` (also for Converse and Responses on runtime), `bedrock:InvokeModelWithResponseStream` for streaming, `bedrock-mantle:CreateInference` for mantle. **Restrict by model ARN** (and by inference profile ARN for cross-Region).
- **Streaming**: use `ConverseStream`/`InvokeModelWithResponseStream` to show tokens as they arrive (lower perceived latency). Streaming is a **different permission** (the `WithResponseStream` action).
- **Structured output**: models can return **validated JSON** (supported on Claude through both endpoints with `output_config.format`, and in Converse for supported models). Prefer it over prompt-and-parse.
- **Tool use / function calling**: the model asks your app to call a tool (client-side) and you return the result in the next turn. Server-side tools run inside the service (mantle).
- **Count tokens API**: check input size before you send (for quota planning and cost).
- **Region note**: `bedrock-runtime` is regional (`bedrock-runtime.<region>.amazonaws.com`); **PrivateLink** interface endpoints exist for runtime/agent endpoints (see file 4).
- **Prompt management and Prompt routing**: see file 3 and section F below.

## D. Ways to run inference (capacity and price modes)
- **On-demand (pay per token)**: default. Uses **shared capacity**, subject to **quotas (TPM/RPM)**. No commitment.
- **Cross-Region inference (CRIS)** via **inference profiles** (section E): route to another Region for more throughput.
- **Service tiers** (set `service_tier` on the request, per model support):
  - **Standard** (default): normal price and performance.
  - **Priority**: faster responses for a **price premium** (about **+75%** per the pricing page) and **no reservation** needed; prioritized over standard/flex.
  - **Flex**: **discount** (about **50% off**) for latency-tolerant work (evaluations, summarization, agent background steps).
  - **Reserved**: **reserve capacity** (tokens per minute, separate input and output) for **1 or 3 months**; fixed monthly price per 1K TPM; **overflows to Standard**; target **99.5%** uptime; **minimum 100K input TPM and 10K output TPM**; get it through your **AWS account team**; billing continues until you delete it.
  - The on-demand quota is **shared** by priority/default/flex; reserved capacity is **separate**. CloudWatch shows `ServiceTier` and `ResolvedServiceTier`.
- **Provisioned Throughput (PT)**: buy **model units (MUs)** for a model; **billed hourly** (whether used or not) until you delete it.
  - Commitments: **no commitment**, **1 month**, or **6 months** (longer = cheaper per hour; you cannot delete early).
  - **Required** to run a **custom (fine-tuned/distilled) model**. Price equals the base model's price.
  - **Not supported** with batch inference, and **inference profiles do not support PT**.
  - Use PT for steady, high, predictable volume or when a custom model must serve traffic. For flexible mission-critical capacity, **Reserved tier** is the newer option **(verify which models)**.
- **Batch inference**: **asynchronous** jobs. Put prompts in **JSONL in S3** (InvokeModel or Converse record format), start a job, get outputs in S3.
  - **Discount about 50%** versus on-demand for supported models.
  - Not for tool calling in Converse-type jobs (records with `toolConfig` fail with 400; use InvokeModel format for tools).
  - **Not for provisioned models.** **Prompt caching is not supported** in batch.
  - Notifications through **EventBridge** job state changes. Needs an **IAM service role** with S3 access.
  - Use for large offline work: bulk summarization, classification, embedding backfills, evaluation sets.
- **Choose**: spiky/small → on-demand; background bulk → **batch or Flex**; latency-critical customer-facing → **Priority** (or Reserved); steady very high volume or custom model → **Provisioned Throughput**; need higher on-demand throughput without commitment → **cross-Region inference**.

## E. Inference profiles and cross-Region inference (CRIS)
- An **inference profile** defines a **model + the Regions** requests may go to.
- **System-defined profiles**: **Geographic** (for example US, EU, APAC) or **Global**. IDs often start with `us.`, `eu.`, `apac.`, or `global.`.
- **Application inference profiles**: **you create** them (wrapping a model or a system profile) mainly to **track cost and usage** by app/team/tag. (Not usable on the Responses API on runtime.)
- **Geographic CRIS**: data processed **only inside the geography** (good for residency rules). **Standard pricing.**
- **Global CRIS**: any supported commercial Region; about **10% cheaper**; **no residency guarantee**.
- **No extra routing charge**. Price is for the **source Region** you call.
- **Data stays on the AWS network**, encrypted in transit. **CloudTrail** logs in the source Region; `additionalEventData.inferenceRegion` shows where it ran.
- CRIS can route to Regions **not enabled** in your account (no manual enablement needed).
- **IAM and SCP traps**:
  - Permissions are needed on the **profile** and on **each destination Region's model**.
  - Geographic: SCPs must **allow all destination Regions** in the profile.
  - Global: SCPs must allow **`aws:RequestedRegion` = `unspecified`** **(verify wording)**.
  - A Region-deny SCP is the classic cause of "AccessDenied only on cross-Region profiles".
- Quotas for CRIS profiles are tracked per profile and are **higher** than single-Region. Use it to absorb spikes.
- **Prompt caching** works with CRIS (can cause more cache writes at times of high demand).

## F. Quotas, tokens and throttling (very testable)
- **Throttling basis**: **tokens per minute (TPM)** and **requests per minute (RPM)** per model per Region (per endpoint). Plus **tokens per day (TPD)**.
- **Embedding models** are throttled by **RPM**, not TPM.
- **Quota formula at request start**: **input tokens + `max_tokens`** is reserved. If that exceeds your remaining quota, you are throttled (`ThrottlingException`, HTTP 429), **even if the real output would be short**.
- **At the end**: consumption = `InputTokenCount + CacheWriteInputTokenCount + (OutputTokenCount × burndown rate)`. Unused reservation is returned. **Cache reads do not count** toward the quota.
- **Burndown rate** (output tokens count extra): **5x** for older Claude (4.7 and below), **10x** for newer ones (Opus/Sonnet 5.x, Fable 5.1) and OpenAI GPT-5.6 on runtime, **15x** for Claude 4.8; **1x** for most other models **(verify per model card)**. You are **billed only for real tokens**.
- **Trap**: a high `max_tokens` (for example 32,000) cuts your concurrency. **Set `max_tokens` close to the expected output size.**
- **`bedrock-mantle`** uses separate input/output limits and **no burndown**, plus queueing for fair share.
- **Quota increases** are **not automatic**: request through Service Quotas/account team; account age, usage and payment history matter. Your real quota may be below the documented default.
- **Handling throttling**: **retry with exponential backoff + jitter** (SDK does some), reduce `max_tokens`, use **prompt caching**, **cross-Region profile**, **batch/Flex** for non-urgent work, spread across models, and add **multi-Region/multi-model fallback**.
- **429 vs 5xx**: `ThrottlingException` (429), `ModelTimeoutException`, `ServiceUnavailableException` (503), `ModelNotReadyException`, `ValidationException` (bad input or unsupported parameter, for example a `ttl` on a model that does not support it).

## G. Prompt caching
- **What**: reuse an unchanged **prompt prefix** (long system prompt, tool definitions, documents) across requests to cut **latency and input cost**.
- **Two types**:
  - **Implicit**: automatic, **best effort**, no changes to the request. Put **static content first**, dynamic content last.
  - **Explicit**: you add **cache checkpoints** (`cachePoint` in Converse, `cache_control` for Claude InvokeModel, `prompt_cache_breakpoint` for newer OpenAI models).
- **Minimum prefix**: about **512–4,096 tokens** depending on model (for example 1,024 for many; 4,096 for some older Claude). Below the minimum, the request works but **nothing is cached**.
- **Checkpoints per request**: up to **4** for Claude and Nova.
- **TTL**: **5 minutes** (default, **refreshes on every hit**), **1 hour** on supported Claude models (`"ttl": "1h"`; sending `ttl` to a model that does not support it → `ValidationException`), **30 minutes** for newer OpenAI models. Longer TTL entries must come **before** shorter ones in one request.
- **Cache order**: `tools` → `system` → `messages`. Changing an earlier section **invalidates the later sections**. The minimum is checked on the **cumulative** prefix.
- **Billing**: cache **reads** at a discounted rate; cache **writes** can cost **more** than normal input (for example **1.25x** on newer OpenAI models; model dependent). Check `cacheReadInputTokens` / `cacheWriteInputTokens` (Converse) or `cached_tokens` / `cache_write_tokens` (Responses).
- When caching is on, `inputTokens` is only the **non-cached** part. **Total input = inputTokens + cacheRead + cacheWrite.**
- **Not** supported with **batch** inference; **only on-demand** endpoints. Works with Prompt management and CRIS.
- **Best fit**: chatbots over a long uploaded document, agents re-sending big tool definitions, repeated few-shot examples.
- Cached reads are **not counted against the quota**, so caching also raises effective throughput.

## H. Intelligent Prompt Routing and prompt optimization
- **Intelligent Prompt Routing** (runtime only): a router sends each request to a **cheaper or stronger model within one family** based on predicted difficulty. Billed about **$1 per 1,000 requests** plus tokens **(verify current price)**. Not on mantle.
- **Prompt optimization** tools can rewrite prompts for a chosen model (simple optimizer priced per token) **(verify)**.
- **Model distillation** (file 3) is the permanent way to get cheap-model quality.

## I. Embeddings (needed for RAG and vector stores)
- An **embedding model** turns text/images into a **vector**. Same-meaning content gets nearby vectors.
- **Titan Text Embeddings V2**: output dimensions **1,024 (default), 512 or 256**; normalizes by default **(verify)**; supports many languages. **Titan G1 Text**: 1,536 dimensions (older).
- **Cohere Embed** (English/Multilingual): 1,024 dimensions. Some models offer **binary** vectors (1 bit per dimension: cheaper storage, less precise).
- **The vector index dimension must equal the model's output dimension.** A mismatch breaks ingestion. **Changing the embedding model requires re-embedding everything.**
- **Smaller dimensions** = less storage and faster search, slightly lower accuracy.
- **Cost**: embeddings are billed per **input token**; throttled by **RPM**.
- Use the **same model** for indexing and querying.

## J. Scenarios: "If X → Y, because Z"
- **If** you want to switch between models without rewriting your code, **then** use the **Converse API** (or **ConverseStream** for streaming) on the **`bedrock-runtime`** endpoint, the endpoint used for inference. **This works because** Converse uses **one consistent message format across models**: system prompt, messages, tool use, documents and images look the same for every model. To swap models you change only the **model ID**. Model-specific parameters can still be passed in a model-specific field.
- **If** you need a feature that only one provider offers, or you are making an **embedding** or **image-generation** call, **then** use **InvokeModel** (or **InvokeModelWithResponseStream**). **This works because** InvokeModel takes a **model-specific JSON body**, so each provider's own request format and native features are available. The catch: changing the model also means changing the request body.
- **If** your app already uses the **OpenAI SDK**, **then** point it at Bedrock by changing the **base URL** and using a **Bedrock API key**, and keep calling the **Responses** or **Chat Completions** API. **This works because** both Bedrock inference endpoints (`bedrock-runtime` and `bedrock-mantle`) offer these **OpenAI-compatible** APIs. The API key still maps to an **Identity and Access Management (IAM)** principal, which needs permission to call the model.
- **If** you need **server-side web search** or long **background (asynchronous)** inference, **then** use the **`bedrock-mantle`** endpoint, Bedrock's second inference endpoint. **This works because** these are mantle-only extras; `bedrock-runtime` does not offer them. The catch: mantle has **no** InvokeModel/Converse, **no Guardrails** and **no cross-Region inference profiles**. The token price is the **same** on both endpoints, so choose by features.
- **If** every model call must pass through **Guardrails** (Bedrock's safety filters on inputs and outputs), **then** call models through **`bedrock-runtime`** with **Converse** or **InvokeModel**. **This works because** **`bedrock-mantle` does not support Guardrails**, while the runtime APIs accept a guardrail on each request.
- **If** you get **ThrottlingException** (HTTP **429**) even though real answers are short, **then** **lower `max_tokens`** to near the expected output size. **This works because** at the start of each request Bedrock **reserves input tokens + `max_tokens`** against your **tokens-per-minute (TPM)** quota. A high `max_tokens` (for example 32,000) holds quota you never use, so fewer requests fit at once. Unused reservation is returned only when the request ends, and you are billed only for real tokens.
- **If** throttling comes from sudden **traffic spikes**, **then** call the model through a **cross-Region inference (CRIS) profile**, which lets Bedrock send requests to other Regions. **This works because** CRIS profiles have **higher quotas** than a single Region and pool capacity across Regions, with **no extra routing charge**. Also retry with **exponential backoff and jitter**.
- **If** data must stay in the **EU**, **then** use the **EU geographic inference profile** (ID starting with `eu.`), not a **global** profile. **This works because** a **geographic** profile processes data **only inside that geography**. A **global** profile can use any supported commercial Region; it is about **10% cheaper** but gives **no data-residency guarantee**.
- **If** you get **AccessDenied** only when using a cross-Region profile, **then** fix the **Service Control Policy (SCP)** (an AWS Organizations rule that can block Regions) and IAM. For a geographic profile the SCP must **allow all destination Regions**; for a global profile it must allow **`aws:RequestedRegion` = `unspecified`** **(verify)**. IAM must allow the **profile ARN** and **each destination Region's model**. **This works because** routing sends requests to other Regions, so a Region-deny SCP blocks them. This is the classic cause of this error.
- **If** you need Bedrock cost **per team or app**, **then** create **application inference profiles** (profiles you make around a model) and add **cost allocation tags**. **This works because** each app calls its own profile, so usage and cost are tracked per profile and tag. The catch: application profiles cannot be used on the Responses API on runtime.
- **If** you have **10 million documents** to summarize overnight, **then** use **batch inference**: put prompts as **JSONL in Amazon S3**, start a job, and read the outputs from S3. **This works because** the work is not interactive, and batch is **about 50% cheaper** than on-demand for supported models. **Amazon EventBridge** can tell you when the job changes state. The catch: batch does **not** support **prompt caching** or **Provisioned Throughput** models, and Converse-format records with tools fail.
- **If** a customer-facing chat must stay fast during peaks, **then** set the **Priority** service tier on requests, or use the **Reserved** tier when you need guaranteed capacity. **This works because** Priority requests are served ahead of Standard and Flex, for a **price premium** and with no reservation. Reserved books tokens per minute for **1 or 3 months** (minimum **100K input TPM and 10K output TPM**, through your AWS account team) and overflows to Standard.
- **If** the workload is **steady and very large**, or you must serve a **fine-tuned (custom) model**, **then** buy **Provisioned Throughput (PT)**: **model units (MUs)** reserved for one model. **This works because** custom models **require** PT, and PT gives fixed capacity. The catch: PT is **billed hourly whether used or not** until you delete it; **1-month** or **6-month** commitments are cheaper but cannot be deleted early.
- **If** the same long system prompt is sent on every call, **then** turn on **prompt caching**, with the **static part first** and changing content last. **This works because** Bedrock reuses the unchanged **prompt prefix**: **cache reads** are cheaper, faster and **do not count toward the quota**. The catch: **cache writes** can cost more than normal input, and caching does not work with batch inference.
- **If** the cache never hits, **then** check four things: the prefix is below the model's **minimum tokens** (about **512–4,096**), a checkpoint sits after content that changes, the **TTL** (default **5 minutes**) expired, or the tools/system section changed. **This works because** the cache order is **tools → system → messages**, and any change to an earlier section **invalidates all later sections**.
- **If** the vector index rejects your embeddings, **then** check for a **dimension mismatch**: the index dimension must equal the embedding model's output (for example **Titan Text Embeddings V2**: 1,024, 512 or 256). **This works because** every vector must fit the index size. Changing the embedding model means **re-embedding everything**.
- **If** you must choose the **cheapest acceptable model**, **then** start with a small, fast model, **test it on your own data** with **model evaluation**, and move up only if needed. Also consider **model distillation** (training a small model from a big one) or **Intelligent Prompt Routing**, which sends each request to a cheaper or stronger model in one family. **This works because** bigger models cost more per token, and a bigger context adds cost and latency.

Verified from AWS docs on 2026-11-01 (Bedrock overview, endpoints, cross-Region inference, token burndown, service tiers, Converse, prompt caching, batch inference, Provisioned Throughput pricing and quotas pages).
Unconfirmed (verify): the exact model line-up and gated models; Marketplace models; Bedrock default model access behavior; global-profile SCP wording; Priority +75% / Flex 50% / batch 50% figures by model; Reserved-tier model support; Titan V2 normalization; Nova multimodal embedding details; intelligent prompt routing price; burndown values for models not named in the doc; model-specific token minimums.

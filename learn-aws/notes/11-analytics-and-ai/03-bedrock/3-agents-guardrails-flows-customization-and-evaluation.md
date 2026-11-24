# Amazon Bedrock – 3. Agents/AgentCore, Guardrails, Flows, Data Automation, customization and evaluation

Short notes. Each point is a fact you can be asked about.

## A. Agents: Classic vs AgentCore (very current change)
- An **agent** = a model in a **loop** that plans, calls **tools/APIs**, reads **knowledge**, keeps **memory**, and returns a result.
- **Amazon Bedrock Agents Classic** (the original `bedrock-agent` Agents feature, launched Nov 2023):
  - **No longer open to new customers from 30 July 2026** (maintenance mode). **Existing accounts keep working**: accounts with Agents activity in the **past 12 months** are allow-listed (per account). Others get **`AccessDeniedException` (403)** on `CreateAgent` and `InvokeInlineAgent`.
  - **No exception process**. No new features; the model list is **frozen** at the 30 July 2026 date. **No extra charge** for Classic itself (you pay for model, KB, Lambda).
  - **No end-of-life date announced**. API names, IaC resource types and IAM prefixes did not change.
  - Components you may still meet: **instructions**, **action groups** (OpenAPI schema or function details + **Lambda executor**), attached **Knowledge Bases**, **memory**, **return of control**, built-in **user input** and **code interpreter**, **prompt overrides** (pre-processing, orchestration, KB response, post-processing), **multi-agent collaboration** (supervisor + collaborators), **versions and aliases** (`DRAFT`, test alias `TSTALIASID`), **trace**.
- **Amazon Bedrock AgentCore** (recommended replacement and the platform for new agents). Modular services, usable together or alone, with **any framework** (Strands, LangGraph, LangChain, CrewAI, LlamaIndex, OpenAI Agents SDK, Google ADK, Claude Agent SDK) and **any model** (Bedrock or outside):
  - **Harness**: managed agent loop; define model, system prompt and tools in **one API call**; each session in an isolated **microVM**; supports remote **MCP** servers, inline functions, custom container.
  - **Runtime**: secure **serverless** hosting for agents/tools; fast cold starts, **session isolation**, extended runtime for async agents, built-in identity; protocols **MCP** and **A2A**.
  - **Memory**: **short-term** (multi-turn) and **long-term** (across sessions), shareable across agents, learns from experience; **actor ID** isolates users.
  - **Gateway**: turns **APIs, Lambda functions and OpenAPI specs into MCP tools** (and connects existing MCP servers); can front a **Knowledge Base**; where **Policy** and guardrail enforcement happen.
  - **Identity**: agent identity, inbound/outbound auth with existing IdPs (Cognito, Okta, Entra ID, Auth0), credential vault for tools.
  - **Code Interpreter**: sandbox to run Python/JavaScript/TypeScript.
  - **Browser**: managed cloud browser (Playwright/BrowserUse) for web tasks.
  - **Observability**: traces, metrics, **OpenTelemetry**-compatible; data in **CloudWatch**.
  - **Evaluations** (quality scoring of sessions/traces/spans) and **Optimization** (AI-generated recommendations + **A/B tests** of prompts/tool descriptions).
  - **Policy**: deterministic rules (natural language or a **Cedar-compatible** language) that **intercept every tool call** at the Gateway.
  - **Registry**: governed catalog of agents, MCP servers, tools and skills with semantic + keyword search.
  - **Payments**: microtransactions for agents using the x402/MPP protocols with wallet and spend limits **(verify)**.
  - **Pricing**: **consumption-based**, no upfront or minimum (see the AgentCore pricing page); there is no separate harness orchestration fee.
- **Migration mapping (Classic → AgentCore)**:
  - Orchestration loop → **harness**.
  - Action groups → **Gateway tools (MCP)** over REST/Lambda.
  - KB attached to agent → **Gateway-fronted KB** or a retrieval tool.
  - Trace UI → **Observability** tracing.
  - Prompt overrides per stage → **system prompt**; stage-level overrides are **not** directly replicated.
  - Return of control / user input → **inline function tools** (agent pauses, client handles, resumes).
  - Memory → **AgentCore Memory**.
  - Multi-agent collaboration → agent-as-tool patterns or custom framework on **Runtime** (routing mode is limited).
  - Custom orchestrator → **code-defined agent on Runtime** (not available in the harness).
  - AgentCore CLI can **import** Classic configs; an `amazon-bedrock` skill in the "agent toolkit for AWS" can guide migration.
- **Choose**: new agent → **AgentCore harness**; need custom control/multi-agent → **code-defined agent on AgentCore Runtime**; existing Classic agent → keep running, plan migration.
- **Agents for data pipelines**: natural-language data questions (agent calls Athena/Redshift via a tool), ticket triage, pipeline-failure explainers, documentation assistants. **Least-privilege tools** matter: an agent can only do what its tools allow.
- **Security for agents**: scope the **tool IAM role**, validate tool inputs, use **Policy** to restrict tool calls, **Guardrails** against prompt injection, human approval (inline tools) for destructive actions, log all calls.

## B. Guardrails
- **Bedrock Guardrails** = configurable safeguards on **inputs and outputs** of text/chat models. One account can have **many guardrails**.
- **Policies (filters)**:
  - **Content filters**: **Hate, Insults, Sexual, Violence, Misconduct, Prompt Attack** (jailbreak/prompt injection). Strength per category: none/low/medium/high. Works on **text and images**.
  - **Denied topics**: define topics (with description and examples) to block.
  - **Word filters**: custom words/phrases + managed profanity list; case-insensitive whole-word match.
  - **Sensitive information filters**: **PII entities** (SSN, DOB, address, etc.) and **custom regex**; action **block** or **mask**.
  - **Contextual grounding check**: scores **grounding** (is the answer supported by the source?) and **relevance** (does it answer the question?) to catch **hallucinations** in RAG; set thresholds.
  - **Automated Reasoning checks**: validate answers against **logical rules** (formal reasoning) to detect hallucinations and unstated assumptions. **Not supported in enforced guardrails.**
  - **Tiers**: **Classic** and **Standard**. Standard adds protection against harmful content hidden in **code elements** (comments, variable names, strings), better multilingual and more consistent grounding scores; Standard needs **cross-Region guardrail inference** **(verify)**.
- **How it runs** (Converse/InvokeModel and streaming variants): input checked **in parallel per policy** → if blocked, the model is **not called** and your **blocked message** is returned → otherwise model runs → output checked → blocked/masked if violating.
- **Charges**: only for configured policies. **Input blocked** → guardrail charge, **no model charge**. **Output blocked** → guardrail charges for input and output **plus** the model call already made. Pass → both.
- **Prices (per 1,000 text units; 1 unit = up to 1,000 characters)**: content filters about **$0.15**, denied topics **$0.15**, grounding **$0.10**, sensitive information **$0.10**; **regex and word filters free**; image content filter per image; automated reasoning per policy **(verify current)**.
- **`ApplyGuardrail` API**: evaluate **any text** against a guardrail **without calling a model**. Use for **non-Bedrock models, your own app content, pre-processing pipelines, chat history checks**.
- **Embedding, reranking and image-generation models do not support guardrails.** **`bedrock-mantle` does not support guardrails.**
- **Guard content tags (selective evaluation)**: mark only the **user input** part for evaluation (skip system prompts/search results). SDK only (not console).
- **Streaming**: **synchronous** mode (checks before releasing chunks; safer, adds latency) vs **asynchronous** mode (releases chunks immediately, checks in background; faster, may expose content before block) **(verify)**.
- **Versions**: `DRAFT` working copy + **numbered immutable versions**. Production should use a **version**, not DRAFT.
- **Use with**: Converse, InvokeModel, **Knowledge Bases (`RetrieveAndGenerate`)**, Agents, Flows, AgentCore (through Gateway).
- **Enforcements (central control)**:
  - **Account-level enforcement**: one guardrail version applied to **all Bedrock model invocations in the account** (per Region; `PutEnforcedGuardrailConfiguration`).
  - **Organization-level enforcement**: **AWS Organizations "Amazon Bedrock policy"** (`BEDROCK_POLICY` declarative type) attaches a guardrail ARN + version to root/OU/accounts. Needs the guardrail **in each Region**, a **numeric version**, a **resource-based policy** granting `bedrock:ApplyGuardrail`, and IAM permission in member roles.
  - Policy inheritance resolves to **one effective policy** per account (check with `DescribeEffectivePolicy`); it is **not** a union of all attachments.
  - Request + account + org guardrails **all apply** (union; **most restrictive wins**).
  - `selective_content_guarding` (system/messages: **selective** or **comprehensive**, default comprehensive) and **model include/exclude lists** (exclude embedding models).
  - A wrong ARN causes policy violations and can **block model use**. A guardrail used in enforcement **cannot be deleted** by default.
  - Quotas count against the **calling (member) account**.
- **Cross-Region guardrail inference**: guardrail evaluation can use inference profiles for capacity (and Standard tier).
- **Limits to remember**: text units and **guardrail quotas** (TPS/text units per second) are separate from model quotas.
- **Not a replacement** for IAM/network controls or data classification. Test with the built-in **test window**; models behind safeguards are updated by AWS, so **re-test periodically**.

## C. Prompt management and Flows
- **Prompt management**: store **versioned prompts** with variables ({{var}}), model + inference settings, optional **prompt caching**; reuse across apps and Flows; **prompt optimization**. Compare variants in the console **(verify details)**.
- **Bedrock Flows**: **visual workflow builder** (and API) that links **prompts, models, Knowledge Bases, Lambda, S3, Lex, agents, conditions, iterators, loops** into an end-to-end GenAI workflow.
  - **Working draft** → prepare → test → publish an **immutable version** → create an **alias** → call **`InvokeFlow`** on the alias (roll back by repointing the alias).
  - **Flow executions** run **asynchronously** for long flows; **multi-turn** (converse with a flow) supported.
  - **Guardrails** can be added to flows; **Lambda in another account** is possible with a cross-account setup.
  - **Price**: no flow fee itself; you pay for the **models and resources** used.
  - Good for **low-code orchestration** (summarize → classify → route). For code-heavy or agentic loops prefer **AgentCore** or **Step Functions** (deterministic, auditable pipelines with Bedrock tasks).
- **Step Functions + Bedrock**: optimized `bedrock:invokeModel` task, `.sync` batch jobs, retries/catch, **Map** state for fan-out. The usual pick for **data pipelines** that call models.

## D. Bedrock Data Automation (BDA)
- **BDA** turns **unstructured content (documents, images, audio, video)** into **structured output** with generative AI.
- **Standard output**: default extraction (document text/layout, image descriptions, audio transcripts, video scene summaries, chapters, text in video, content moderation).
- **Custom output** with **blueprints**: define the **fields you want** (names, types, instructions) per document type (invoice, ID, receipt) and BDA fills them. **Projects** hold settings and blueprints.
- Features that build trust: **confidence scores** and **visual grounding** (where on the page a value came from).
- **Sync and async** APIs; results go to **S3**; used by **Knowledge Bases as a parser**.
- **Billing** is by **page, image, minute of audio/video, and fields** extracted (standard vs custom) **(verify numbers)**.
- Use for: **intelligent document processing (IDP)**, media analysis, RAG ingestion of PDFs with tables/charts.
- BDA vs **Textract**: Textract is classic OCR/forms/tables extraction with fixed outputs; BDA is **GenAI-based, multimodal, blueprint-driven**. Pick Textract for simple, cheap, high-volume OCR; BDA for flexible schemas and mixed media **(verify)**.

## E. Model customization
- **Why**: improve accuracy on a **narrow task**, match style/format, **shrink** to a smaller cheaper model. Start with **prompting + RAG** first (cheapest).
- **Methods (Bedrock-managed)**:
  - **Supervised fine-tuning**: labeled prompt → completion pairs adjust model weights for specific tasks.
  - **Reinforcement fine-tuning (RFT)**: you provide **prompts and reward functions** (usually a **Lambda** scoring responses) or logged invocations; the model improves from scores. Billed per **training hour** (docs example **$80/hour** for some models) **(verify)**.
  - **Distillation**: a large **teacher** generates answers for your prompts; a smaller **student** is fine-tuned on them. Bedrock handles **data synthesis**. Goal: teacher-like quality at **student cost and speed**.
  - **Continued pre-training** (unlabeled domain text) exists for some models **(verify availability)**.
- **Only some models** can be customized (and only in some Regions); check the model card.
- **Data**: JSONL in **S3**; validation set optional; IAM **service role** for S3; optional **KMS** and **VPC** for training jobs.
- **Charges**: **training = tokens processed × epochs** (or hours for RFT), plus **monthly storage per custom model** (docs example **$1.95 per model per month**).
- **Serving a custom model**: needs **Provisioned Throughput** (priced like the base model) for fine-tuned/distilled models **(verify for newer on-demand custom serving)**. **Custom Model Import models** use on-demand style per-minute billing instead.
- **Custom Model Import (CMI)**: bring **open-weight models you trained elsewhere** (for example in SageMaker) into Bedrock.
  - Needs **Hugging Face format** in S3: `.safetensors`, `config.json`, tokenizer files.
  - Architectures: **Mistral, Mixtral, Flan/T5, Llama 2/3.x, Mllama, GPTBigCode, Qwen2/2.5/3 (incl. VL), GPT-OSS (20B/120B, only us-east-1)**.
  - Limits: weights **under 200 GB (text) / 100 GB (multimodal)**, context **under 128K**, transformers **4.51.3**; **no embedding models**.
  - **Regions**: us-east-1, us-east-2, us-west-2, eu-central-1 (docs list).
  - Call with **InvokeModel** (Converse not supported for some, for example Qwen3). **Not supported**: batch inference, CloudFormation.
  - **No import charge**; billed per **Custom Model Unit per minute in 5-minute windows** (docs example about **$0.057 per CMU-minute** in US) while the model is active, plus storage; **cold start** after idle.
- **Model choice**: SFT for format/style/classification; **distillation** to cut cost; **RFT** when you can score outputs automatically; **RAG** for knowledge; **CMI** when you already have your own weights.
- **Compare with SageMaker**: **SageMaker AI** for full control, custom algorithms, any framework, GPU-level tuning; **Bedrock customization** for managed, no-infrastructure tuning of supported models.

## F. Evaluation
- **Bedrock evaluations** score **models** and **RAG** systems.
- **Model evaluation types**:
  - **Programmatic/automatic**: built-in or custom **prompt datasets**, metrics like accuracy, robustness, toxicity.
  - **LLM-as-a-judge**: a second model scores responses and explains why.
  - **Human evaluation**: your workers or subject-matter experts rate responses.
- **RAG evaluation** (LLM-judged): **retrieve-only** (context relevance/coverage) or **retrieve-and-generate** (correctness, completeness, faithfulness, citations). The dataset needs **ground truth** (expected texts/answers). Works for **Bedrock KBs and external RAG** (you provide the responses).
- **Evaluable targets**: foundation models, Marketplace models, **custom and imported models**, **prompt routers**, models with **Provisioned Throughput**.
- Datasets in **S3 (JSONL)**; **CORS** configuration needed on the S3 bucket for console jobs; reports and metrics are saved to S3.
- **Cost**: human tasks (docs example **$0.21 per human task**) plus the **inference** cost of the evaluated and judge models. Use **Flex tier or batch** for big evaluations.
- **When**: before choosing a model, before/after changing prompts/chunking, before promoting a guardrail or custom model, and as a **regression test** in CI/CD.
- **AgentCore Evaluations** covers **agent** traces and sessions.

## G. Other Bedrock features
- **Amazon Bedrock Marketplace**: 100+ extra (often niche/open) models deployed to **managed endpoints** you pay for by instance hours **(verify)**.
- **Prompt caching, Intelligent Prompt Routing**: see file 1.
- **Web Search tool** (mantle): built-in server-side search for OpenAI models in a few Regions (US East N. Virginia, Ohio, US West Oregon); billed per query.
- **Structured outputs**, **tool use**, **citations** (Claude), **extended thinking/reasoning controls** (model dependent).
- **Amazon Nova model family** and **Nova Forge/Act** features exist **(verify current names)**.

## H. Scenarios: "If X → Y, because Z"
- If a new account needs an agent platform → **AgentCore**, because Bedrock Agents Classic is closed to new customers since 30 July 2026.
- If you already run Classic agents → **keep them**, plan a migration (AgentCore harness or code-defined), because they continue to work but get no new features.
- If you want agent tools to wrap existing REST APIs and Lambdas → **AgentCore Gateway (MCP tools)**, because it converts APIs into agent-callable tools.
- If an agent must never call a dangerous API → **AgentCore Policy at the Gateway** plus a least-privilege tool role, because Policy checks every tool call deterministically.
- If different users need isolated agent memory → **AgentCore Memory with actor IDs**, because memory is scoped by actor.
- If you must block PII in model outputs → **Guardrails sensitive-information filter (mask)**, because it detects PII entities and regex in outputs.
- If hallucinations in RAG answers are the problem → **contextual grounding check** (and **Automated Reasoning** for rule-based domains), because they score answers against sources.
- If you use a non-Bedrock model but want the same safeguards → **`ApplyGuardrail` API**, because it works on any text without a model call.
- If compliance wants one guardrail on every Bedrock call in every account → **Organizations Amazon Bedrock policy (or account-level enforcement)**, because enforcement applies to all invocations centrally.
- If an enforced guardrail suddenly breaks all model calls → **check the guardrail ARN/version and Region in the policy**, because an invalid ARN causes violations and non-enforcement.
- If you need low-code GenAI orchestration → **Bedrock Flows**; if you need audited, deterministic data pipelines → **Step Functions**, because Step Functions give retries, state and governance.
- If invoices of many layouts must become JSON → **Bedrock Data Automation with blueprints** (or Textract for plain OCR), because blueprints define the fields to extract.
- If a smaller model must match a big model on your task → **distillation**, because the teacher generates the training data for the student.
- If you can score outputs automatically (for example SQL that runs) → **reinforcement fine-tuning with a Lambda reward**, because the reward replaces labels.
- If you already trained an open model in SageMaker → **Custom Model Import**, because you keep your weights and call it through Bedrock; no Provisioned Throughput needed.
- If your fine-tuned model is not serving → it needs **Provisioned Throughput** (for Bedrock-tuned models), because custom models are not on shared on-demand capacity **(verify current)**.
- If you must pick between two models or two prompts → **model evaluation with LLM-as-judge on your own dataset**, because public benchmarks do not reflect your data.
- If RAG quality dropped after a chunking change → **RAG evaluation with ground truth**, because it measures retrieval and answer quality before release.

Verified from AWS docs on 2026-11-01 (Agents Classic maintenance mode, AgentCore overview, Guardrails overview/how it works/enforcements, Flows, Data Automation overview, model customization, Custom Model Import, evaluation overview, pricing page).
Unconfirmed (verify): AgentCore Payments details; Guardrails Standard-tier requirements and streaming-mode behavior; guardrail unit prices beyond the pricing page excerpt; Prompt management feature details; Data Automation pricing and BDA vs Textract guidance; continued pre-training availability; serving of custom models without Provisioned Throughput; Bedrock Marketplace billing; Nova Forge/Act names; AgentCore Policy language name "Dogwood" appears in the AWS doc (confirm spelling); Region lists for AgentCore and CMI.

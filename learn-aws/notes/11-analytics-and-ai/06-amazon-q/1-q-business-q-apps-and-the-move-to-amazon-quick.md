# Amazon Q – 1. Q Business, Q Apps and the move to Amazon Quick

Short notes. Each point is a fact you can be asked about.

## A. Status first
- **Amazon Q Business is no longer open to new customers.** AWS keeps giving **bug fixes and security updates** to existing customers but **will not consider new feature requests**.
- **AWS recommends Amazon Quick** (Quick Suite) for new GenAI/agentic work and as the migration target. Pricing page: Quick Suite is "the next evolution of Q Business"; existing customers can keep their service or **use their Q index with Quick**.
- **Q Apps** live **inside** Q Business, so they are part of the same status. In Quick, their successor is **Quick Flows**.
- So: learn Q Business/Q Apps to **run, secure and migrate** existing deployments and to answer comparison and exam questions. **New projects → Amazon Quick** (or **Bedrock Knowledge Bases/AgentCore** when you want to build your own).
- (Amazon Q **Developer** is a **different product**: see file 2.)

## B. What Q Business is
- A **fully managed, GenAI assistant for your employees**. It answers questions, summarizes, drafts content and performs tasks **from enterprise data**, **respecting each user's permissions**, with **citations**.
- **Typical uses**: IT, HR and benefits help desks; internal knowledge search; document summarization; task automation.
- **Built on Amazon Bedrock** (automated abuse detection applies; Bedrock safety controls).
- **Hallucination mitigation**: checks supported chat responses for inconsistencies and **auto-corrects in real time**.
- **Conflicting answers**: when sources disagree it **lists each answer** with details.
- **Modes**: answers from **enterprise data only**, or **enterprise data + model (LLM) knowledge**. **LLM-knowledge responses are enabled by default** when you create an application.
- **Conversation history is kept 30 days**; conversations can be resumed within that window.

## C. Architecture and components
- **Application environment**: the top-level Q Business app. **Up to 50 applications per account.**
- **Identity** (who can sign in):
  - **IAM Identity Center** (recommended): organization instance (best, multi-account) or **account instance** (limited to one account and Region). Subscriptions are **deduplicated across Q Business apps** that share one Identity Center instance (each user billed once at the highest tier).
  - **IAM federation** with **OIDC (preferred) or SAML** when Identity Center is not possible. Billing is per AWS account; limits integration with other AWS apps.
  - **Anonymous applications** for public-facing use (no authentication) with **consumption pricing**.
- **Retriever**: how documents are found.
  - **Native retriever** (Q Business index) with **index units**.
  - **Amazon Kendra retriever** (reuse an existing Kendra index).
- **Index**: stores ingested content. **Starter** (single AZ, up to 5 units, for PoC) or **Enterprise** (3 AZs, production). Each unit holds about **20,000 documents or 200 MB of extracted text** and includes **100 connector hours/month**.
- **Data sources/connectors**: SharePoint, Salesforce, S3, Confluence, Slack, ServiceNow, Google Drive, and more **(see supported-connectors list)**; **up to 50 data sources per application**.
- **Document-level ACLs**: Q Business uses the user's **identity (email ID)** to filter documents. If a data source lacks email-based ACLs or the email is missing, answers use **only public documents**.
- **Web experience**: the hosted chat UI (custom branding, welcome message, **quick prompts**/conversation starters), or **embed** Q Business in your own app/website, browser extension, **Slack, Microsoft Teams, Outlook and Word** integrations (Pro).
- **Plugins and actions**: **built-in** (Jira, ServiceNow, Zendesk, Salesforce, PagerDuty, etc.) and **custom plugins** (OpenAPI) to **act** (create tickets, submit requests). **Up to 25 plugins per application, 20 actions per plugin.**
- **Data accessors**: securely share your Q index with **verified ISVs** (**up to 10 per application**).
- **Guardrails and chat controls**: **global controls** (response source, **blocked words/topics**, hallucination mitigation) and **topic-level controls** (block, or redirect to a message). Q Business **guardrails are not the same feature as Bedrock Guardrails**.
- **Q in Quick (QuickSight)**: integrate Q Business so users ask natural-language questions about dashboards (Pro includes Amazon Q in QuickSight reader pro).
- **File uploads in chat**: up to **5 documents per conversation, 10 MB each**.
- **Media ingestion**: images, **audio (up to 4 hours / 2 GB)**, **video (up to 4 hours / 10 GB, max 60 FPS)** **(US Regions only)**.
- **Regions**: **us-east-1, us-west-2**; **eu-west-1 and ap-southeast-2** with **limited features** (no Q Apps, Q Actions, or audio/video).

## D. Q Apps
- **What**: **lightweight, purpose-built GenAI mini-apps** that employees create **inside Q Business** (no code) to automate a repeated task, then **share**.
- **Requires the Pro subscription.** Since **1 July 2024**, **Lite users cannot create, run or view Q Apps**; Q Apps made by non-upgraded Lite users were **deleted on 30 Aug 2024**.
- **Enabled by default** when you create an application with IAM Identity Center or IAM federation. Reached from the web experience under **Apps**. Managed programmatically with the **Q Apps API**.
- **How users create them**:
  - **From a conversation**: choose **Create Amazon Q App** in a chat.
  - **From a prompt**: describe the app in the **Amazon Q Apps Creator**.
- **An app = a set of cards.** Card types:
  - **Text input** (user inputs), **file upload** (up to **20 file cards**, **50 MB** each), **text output** (generates text from a prompt), **plugin card** (takes an action through a plugin), and cards that can use **enterprise data** or a **specific data source** (needs extra admin IAM permission).
  - Cards can **reference each other with `@` mentions**.
  - **Data collection / forms** are supported for gathering input from users.
- **Limits**: **1,000 Q Apps per application environment**, **100 per web-experience user**, **35 cards per app**, creator prompt up to **10,000 characters**.
- **Library and sharing**: **Publish** an app to the company **Q Apps library** (with **custom labels** for grouping), or **share privately**. Others can **copy and customize** (only the **creator** edits the original). Users can **like** apps.
- **Verified apps**: admins can mark published apps **Verified** (blue check; shown first). **Editing a verified app removes the status until the admin re-applies it.**
- **Governance**: admins can **enable/disable** Q Apps, manage verified apps/labels, and control plugin use.
- **Examples**: marketing post generator (input → text outputs), onboarding assistant (inputs → **plugin card creating a Jira ticket** → welcome email → file upload).
- **Migration**: Q Apps are **not** carried by BYOI. Recreate them as **Quick Flows**; **forms are not yet in Quick Flows** (keep those Q Apps or use structured input).

## E. Pricing (pricing page; verify current)
- **User subscriptions (per user per month)**:
  - **Lite $3**: permission-aware Q&A, single sign-on, fast insights on uploaded files, browser extension. **No Q Apps.**
  - **Pro $20**: adds **Q Apps**, **Amazon Q in QuickSight (Reader Pro)**, **custom and managed third-party plugins**, **Slack, Outlook, Word, Teams** integrations.
  - Changing tiers is billed per the pricing examples (upgrade/downgrade proration).
- **Index (per unit-hour)**: **Starter $0.140** (max 5 units, single AZ, PoC); **Enterprise $0.264** (3 AZs, production). Each unit: **20,000 docs or 200 MB text** and **100 connector hours/month**.
- **Extra media**: images **$0.003** each, audio **$0.006/min**, video **$0.050/min**.
- **Consumption** (anonymous or embedded without per-user auth): **$200 per bundle of 30,000 units/month**; **2 units per ChatSync call or embedded chat prompt**; unused units do not roll over.
- **Free trial**: **60 days**, up to **50 Pro or Lite users** per application; **1,500 index hours** within 60 days; **one trial application per payer account**; QuickSight Pro trial 30 days (up to 4 users); no trial for the anonymous API.
- **Cost drivers**: number of **subscribed users × tier**, **index units × hours** (always on), data volume, media files, anonymous API usage.
- **Cost tips**: use **Lite** for users who only need Q&A; **Pro** only for creators/plugin users; start with **Starter** index for tests (delete after); right-size index units to document counts; remove unused applications and subscriptions; remember **subscriptions are per account** if you use account-level identity instances.

## F. Quotas to remember
- **Applications per account 50**; **data sources per app 50**; **plugins per app 25**; **actions per plugin 20**; **data accessors per app 10**.
- **Groups per user 1,000**.
- **Queries per second (QPS) per index: 1 (adjustable)**, shared across user queries; `SearchRelevantContent`, `Chat` and `ChatSync` are throttled differently.
- **OCR/visual insight limits**: up to **3,000 pages** per PDF/Word/PowerPoint and **500 images** per document.
- **Q Apps**: see section D.
- **File upload in console**: **50 MB** (all types).

## G. Security and governance
- **Access control**: responses are based on the **content the user can access** (ACLs from connectors/Identity). Test with users from different groups.
- **Identity**: prefer **IAM Identity Center** and **group-based** access. For IAM federation limit blast radius with scoped roles.
- **Data protection**: encryption in transit and at rest with **KMS** (customer-managed key option), **PrivateLink/VPC** options for the API and connectors **(verify)**, **VPC-connected data sources** for private repositories.
- **Prompt and content controls**: global and topic-level guardrails; restrict to **enterprise-only** answers for regulated use; **response source** setting.
- **Audit**: **CloudTrail** (API activity), **CloudWatch** metrics/logs for ingestion and chat analytics, **conversation logging** options **(verify)**.
- **Plugins and actions** can change systems: scope plugin credentials, require **user authorization (OAuth)** per user, review actions before enabling.
- **Data accessors** share data with third parties: approve **only verified ISVs**, review regularly.
- **Anonymous apps** expose data publicly: only use with **public** data.
- **Retention**: chat history **30 days**; delete users/apps to remove content; data source content is **deleted when removed from the index** (re-sync/delete).

## H. Migration: Q Business → Amazon Quick
- **Amazon Quick** (Quick Suite) = one AI assistant platform: **Quick Sight** (BI), **Quick Flows** (task automation), **Quick Automate** (multi-step workflows with human-in-the-loop), **Quick Research**, **Spaces** (shared knowledge/dashboards/topics), chat agents, **Apps**, plus mobile/desktop clients.
- **Phased path** (AWS migration guide):
  1. **Set up Quick** (account name, notification email, SPICE Region, authentication: password/SSO, **IAM Identity Center**, SSO only, or Active Directory).
  2. **BYOI (Bring Your Own Index)**: connect your **existing Q Business index** as a Quick **knowledge base** (no re-crawl). Q Business keeps running in parallel.
     - **Requirements**: **same AWS account and Region**; admin rights in Quick; for **IDC mode** both services use the **same Identity Center** instance.
     - **Limits**: **max 2 Q Business indexes per Region (not increasable)**; once selected they **cannot be unselected**; the index knowledge base **cannot be edited** like other Quick knowledge bases; only document types supported by Q Business; **Q Apps, Actions and Q Business chat guardrails are NOT included**.
     - **Identity modes**: **IDC** (access only for users who have access to the index; extra users need config in both consoles) vs **non-IDC** (native identities, Managed AD, IAM federation: **every Quick user gets access to the connected index**, so you must split content into separate knowledge bases and set permissions per space).
  3. **Native connectors in Quick** (instead of BYOI): configuring integrations needs the **Enterprise** subscription; Professional users use what is shared with them. Use **Knowledge** (for Q&A) vs **Connectors** (for actions).
  4. **MCP integrations** for sources without native connectors (Quick is the MCP client; validated examples: Visier, HuggingFace, Intercom, Linear, PagerDuty). **MCP supports actions, not knowledge-base indexing**; **60-second timeout** (HTTP 424), no custom headers, static tool lists after registration.
  5. **Identity and ACL migration**: IDC is simplest. Quick supports **document-level ACLs for S3, Confluence Cloud, SharePoint and Google Drive** knowledge bases; ACLs must be **enabled at creation (permanent)**; **documents without an ACL entry are not ingested** (stricter than Q Business, which opens unlisted S3 prefixes to all).
  6. **Q Apps → Quick Flows** (use Quick to describe each Q App, generate a Flow, test in Run Mode, **Share and Publish**). **Forms are not yet supported.**
- **Feature gaps**: **Guardrails/Actions** (rebuild with Quick governance and Flows); **User Store** (use Identity Center groups and Space-level sharing).
- **Cutover checklist**: users can sign in to Quick; response quality meets baseline; Q Apps recreated as Flows; **ACLs configured**; **MCP integrations working**.
- **Anonymous access and API integrations** need a **custom plan with AWS Support**.
- **Quick pricing (pricing page)**: **Professional $20/user/month**, **Enterprise $40/user/month**, plus **$250 per account per month** infrastructure fee; **agent hours** included (**8** Pro, **18** Enterprise per month; Enterprise extra **$3/agent-hour**, Pro cannot buy more); pooled index storage **25 GB (Pro) / 50 GB (Ent) per user**, overage **$5/GB-month**. Professional includes Flows, Research, Spaces and viewing dashboards; **Enterprise adds Quick Automate, dashboard authoring and certification**. **Free trial: Enterprise only, 30 days, up to 25 users**, waives the fees **(verify current)**.

## I. Troubleshooting (symptom → cause → fix)
- **Answers only from public documents** → ACLs not email-based or the user email missing → fix connector/identity mapping.
- **User sees no Apps tab** → Lite subscription, Q Apps disabled, or Region (eu-west-1/ap-southeast-2) lacks Q Apps → upgrade/enable/use a US Region.
- **"Couldn't find an answer"** → content not synced, **enterprise-only mode** on, or user lacks access → sync, check settings and ACLs.
- **Throttled** → index **QPS (default 1)** exceeded → request increase or add capacity/units.
- **Index capacity exceeded** → more than **20,000 docs or 200 MB per unit** → add index units.
- **Plugin action fails** → missing user authorization/OAuth or plugin limits → re-authorize, check action definitions.
- **Duplicate billing for one user** → multiple accounts/instances (account-level Identity Center or IAM federation per account) → consolidate to an organization Identity Center instance.
- **BYOI users see too much** → non-IDC mode gives all Quick users access to the index → segment into knowledge bases/spaces.

## J. Scenarios: "If X → Y, because Z"
- **If** a company that has never used Amazon Q Business wants an AI assistant for its employees, **then** use **Amazon Quick** (Quick Suite), AWS's AI assistant platform that combines **Quick Sight** (BI), **Quick Flows**, **Quick Research**, **Spaces** and chat agents. **This works because** **Amazon Q Business is no longer open to new customers**; it only gets bug fixes and security updates for existing customers, and AWS recommends Amazon Quick for all new generative AI (GenAI) and agentic work.
- **If** a company already runs Amazon Q Business and wants Amazon Quick features quickly, **then** use **Bring Your Own Index (BYOI)**: connect the existing **Q Business index** to Quick as a **knowledge base**. **This works because** Quick reuses the index, so nothing is **re-crawled**, and Q Business keeps running **in parallel** during the move. The catch: it needs the **same AWS account and Region**, allows at most **2 Q Business indexes per Region** (cannot be raised), a selected index **cannot be unselected**, and **Q Apps, Actions and chat guardrails are not included**.
- **If** existing Q Apps (small no-code AI mini-apps inside Q Business) must keep working after moving to Amazon Quick, **then** **recreate them as Quick Flows**: ask Quick to describe each Q App, generate a Flow, test it in **Run Mode**, then **Share and Publish**. **This works because** **BYOI does not carry Q Apps** over, and Quick Flows is their successor. The catch: **forms are not yet supported** in Quick Flows, so keep those Q Apps or use structured input.
- **If** employees need an HR or IT help-desk bot over **SharePoint** or **Confluence** where each person may only see their own permitted documents, **then** use **Amazon Q Business** (existing customers only) or **Amazon Quick** with **ACL-enabled knowledge bases** (ACL = access control list). **This works because** answers follow document permissions: Q Business filters documents by the user's **identity (email ID)**, and Quick supports **document-level ACLs** for S3, Confluence Cloud, SharePoint and Google Drive. The catch: in Quick, ACLs must be **enabled when the knowledge base is created** (permanent), and **documents without an ACL entry are not ingested**.
- **If** users must create a ticket straight from chat, **then** use a **Q Business plugin** (built-in **Jira**, **ServiceNow**, Zendesk and others, or a custom OpenAPI plugin) or a **Quick action connector**. **This works because** both can **act** on external systems, not just answer questions. Q Business allows **up to 25 plugins per application** and **20 actions per plugin**. The catch: actions change real systems, so require **per-user authorization (OAuth)** and review actions before enabling them.
- **If** a team wants to build its own retrieval-augmented generation (RAG) backend or a custom user interface, **then** use **Amazon Bedrock Knowledge Bases** for retrieval plus **Amazon Bedrock AgentCore** for agents. **This works because** Amazon Q and Amazon Quick are **finished end-user products** with limited customization, while Bedrock gives you the building blocks to build your own.
- **If** a test (pilot) Q Business setup keeps costing money after testing ends, **then** **delete the Starter index** and **unsubscribe the users**. **This works because** an index bills per **index unit per hour** and is **always on**, even with no queries, and user subscriptions bill **per user per month** until removed.
- **If** a public website needs a Q chat for visitors who do not sign in, **then** use an **anonymous application** with **consumption pricing**, holding **public data only**. **This works because** per-user subscriptions do not fit unknown visitors; instead you pay for **bundles of units**, with **2 units per ChatSync call** or embedded chat prompt (verify current price). The catch: anonymous apps **expose their content publicly**, and moving them to Amazon Quick needs a **custom plan with AWS Support**.
- **If** your identity provider (IdP) is Okta or Microsoft Entra and you cannot use **AWS IAM Identity Center**, **then** use **Identity and Access Management (IAM) federation** with **OpenID Connect (OIDC)** (preferred) or **SAML**. **This works because** IAM federation lets users sign in with the existing IdP. The catch: billing is **per AWS account** (one user in several accounts can be billed more than once), and it **limits integration** with other AWS apps.
- **If** Amazon Quick **Professional** users cannot create connectors, **then** **upgrade them to the Enterprise subscription** or have an **Enterprise admin set up the integration and share it**. **This works because** configuring integrations needs the **Enterprise** subscription; Professional users can only use what is shared with them.

Verified from AWS docs on 2026-11-01 (Q Business overview, how it works, Q Apps pages, quotas/Regions, availability change/migration guide, Q Business pricing page, Quick Suite pricing page).
Unconfirmed (verify): the Quick overview page returned no content (Quick feature list is from the migration guide and pricing page); connector and plugin lists; PrivateLink/VPC details for Q Business; conversation logging options; exact list of Q Apps card types (docs list text, file upload, plugin, data-source usage, forms); current Quick prices; Q Apps in eu-west-1/ap-southeast-2 timing.

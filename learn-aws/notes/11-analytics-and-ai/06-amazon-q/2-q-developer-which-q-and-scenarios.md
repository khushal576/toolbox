# Amazon Q – 2. Q Developer, "which Q?" and scenarios

Short notes. Each point is a fact you can be asked about.

## A. The Q family in one table
| Product | What it is | Who uses it | Status (docs, Nov 2026) |
|---|---|---|---|
| **Amazon Q Business** | Enterprise assistant over company data (+ **Q Apps**) | Employees | **Closed to new customers** → Amazon Quick |
| **Amazon Q Developer** | AI assistant for building and operating on AWS (console, CLI, chat apps) | Developers, operators | Active |
| **Amazon Quick (Suite)** | AI assistant platform + BI (Quick Sight), Flows, Research, Automate, Spaces | Business users | **Active; the recommended successor** |
| **Amazon Q in Connect** | AI for contact-center agents | Agents | Part of Amazon Connect **(verify)** |
| **Amazon Q in QuickSight / Quick** | Natural-language BI | Analysts | Now inside **Quick** |
- **Naming trap**: "Q Apps" belong to **Q Business** (not Q Developer). "Amazon Q in the console" is **Q Developer**.

## B. What Q Developer is
- A **GenAI conversational assistant** that helps you **understand, build, extend and operate AWS applications**. Built on **Amazon Bedrock** (with automated abuse detection), augmented with **AWS content** for referenced answers.
- **Where you use it**:
  - **AWS Management Console**, AWS docs site, AWS website, **AWS Console Mobile App** (chat icon; needs IAM permissions).
  - **Command line** (CLI agent) **(verify current naming)**.
  - **Chat applications**: **Microsoft Teams and Slack** (needs the `AmazonQDeveloperAccess` managed policy and channel guardrails). This is the **"Amazon Q Developer in chat applications"** feature that also relays **notifications** (for example Budgets/Cost Anomaly alerts).
- **IDE features**: chat about code, **inline code completions**, **generate new code**, **security scans** (find vulnerabilities), **code upgrades/transformation** (language/version upgrades, for example Java), debugging and optimization, **agentic workflows** (multi-step feature development, unit tests, docs).
- **Console features** **(verify)**: ask about AWS architecture, **your resources**, best practices, errors, **troubleshoot** issues (for example network connectivity), **cost** questions and analysis, **Support** help, compare services.
- **Pricing**: **Free tier** and **Q Developer Pro subscription** (per user per month; limits on agentic requests, code transformation lines, etc. differ by tier) **(verify numbers on the pricing page)**.

## C. Data-engineering uses of Q Developer
- **Write and explain SQL/PySpark/Glue code**, generate **CloudFormation/CDK/SAM** templates, **unit tests**, and refactor ETL scripts.
- **Troubleshoot**: paste an error (Glue job failure, Lambda timeout, Athena query error) and ask for causes (see service-specific troubleshooting notes).
- **Security**: **IDE security scan** for vulnerabilities and hard-coded secrets in pipeline code.
- **Upgrade code**: language/runtime upgrades (for example Python runtime for Lambda) via transformation features **(verify language support)**.
- **Operate**: console chat for "why did my bill increase?", "what changed in this security group?", "which IAM permission is missing?".
- **Limits of AI help**: it can be wrong. **Review generated IAM policies and IaC** (least privilege), **never paste secrets/PII**, run tests, use **code review** and **static analysis** as usual.

## D. Security and governance for Q Developer
- **Identity**: **AWS Builder ID** (free individual), **IAM Identity Center** (Pro, organizational control), **IAM** permissions for console chat.
- **Data handling**: **Pro tier** content is **not used to train** the service and is **not retained for improvement** per AWS tier terms; **free tier** terms differ (review) **(verify current terms and opt-out settings)**.
- **Admin controls (Pro)**: manage users/groups, **telemetry and data-sharing opt-out**, **customizations** (private code repos for tailored suggestions), **reference tracker** (flags suggestions similar to open-source code with license info) **(verify)**.
- **IAM**: use managed policies (for example **`AmazonQDeveloperAccess`**) or custom policies limiting `q:*` actions; **SCPs** can disable use in specific accounts.
- **Chat applications**: restrict via **channel guardrails** and **IAM roles per channel** so chat users cannot run broad actions.
- **Audit**: **CloudTrail** records Q Developer API activity **(verify)**.

## E. Choosing the right assistant or builder tool
- **Employees asking questions over company documents/apps** → **Amazon Quick** (or existing Q Business).
- **Developers needing help on AWS** → **Q Developer** (console, CLI, chat applications) or other AI coding tools.
- **Build your own RAG assistant with custom UI/logic** → **Bedrock Knowledge Bases + Converse**; **agents** → **AgentCore**.
- **Search over documents with connectors, no generation** → **Bedrock Managed KB** (Kendra only if already a customer).
- **Call-center agent assist** → **Amazon Connect (Q in Connect)** **(verify)**.
- **BI dashboards with natural language** → **Quick Sight / Quick** (Q in QuickSight was folded into Quick).
- **Automate multi-step business workflows** → **Quick Flows/Automate**, or **Step Functions** for deterministic cloud workflows.

## F. Cost control
- Q Business: **subscriptions × tier + index units × hours + media**; Quick: **per-user + $250/account/month + agent hours + index overage** (see file 1).
- Q Developer: **Free vs Pro per-user** subscriptions; unsubscribe leavers; use **Free** for occasional users where policy allows.
- Track with **Cost Explorer** (service filters), **Budgets** and **Cost Anomaly Detection**; use **tags** on Q Business apps/indexes.
- **Delete pilots**: Starter indexes and unused apps still bill by the hour.

## G. Scenarios: "If X → Y, because Z"
- **If** someone asks about "Q Apps", **then** the answer is **Amazon Q Business Q Apps**, small no-code AI mini-apps that need the **Pro subscription**. **This works because** Q Apps are a **Q Business feature**, not part of Amazon Q Developer (a common naming trap). Since Q Business is closed to new customers, Q Apps are now moving to **Amazon Quick Flows**.
- **If** you want an AWS error you see in the console explained, **then** use **Amazon Q Developer chat** in the **AWS Management Console**. **This works because** Q Developer is the console's AI assistant, built on **Amazon Bedrock** and augmented with **AWS content** for referenced answers; it can explain errors and help troubleshoot (verify). It needs **IAM permissions** to use.
- **If** a security team wants vulnerabilities in infrastructure as code (IaC) flagged while developers write it, **then** use the **Amazon Q Developer IDE security scan** plus normal **static analysis** and **code review**. **This works because** the scan finds **vulnerabilities and hard-coded secrets** in code inside the editor (IDE). The catch: AI help can be wrong, so keep the usual checks too.
- **If** AWS Budgets alerts must appear in **Slack** or **Microsoft Teams**, **then** use **Amazon Simple Notification Service (SNS)** with **Amazon Q Developer in chat applications**. **This works because** that feature **relays AWS notifications**, such as Budgets and Cost Anomaly alerts, into chat channels. It needs the **`AmazonQDeveloperAccess`** managed policy and **channel guardrails**.
- **If** a pipeline team wants Q Developer to generate IAM policies, **then** **review every generated policy for least privilege** before using it. **This works because** AI output **can be wrong or too broad**; run tests and normal code review, and **never paste secrets or personal data (PII)** into the chat.
- **If** HR wants a policy assistant over **SharePoint** that respects each user's permissions, **then** use **Amazon Quick** with ACL-enabled knowledge bases (or an **existing Amazon Q Business** app with ACL-aware connectors). **This works because** answers must follow **user permissions**, and both filter documents by access control lists (ACLs). Q Business is closed to new customers, so new projects use Quick.
- **If** a team needs a **custom retrieval API** for its own app, **then** use **Amazon Bedrock Knowledge Bases** and its **`Retrieve`** call. **This works because** Amazon Q and Amazon Quick are **end-user products**, while Bedrock Knowledge Bases lets you build your own retrieval and custom logic.
- **If** a company wants **one tool for dashboards and AI chat**, **then** use **Amazon Quick**. **This works because** Quick merges **Quick Sight** (BI dashboards), **Flows**, **Research**, **Automate** and **Spaces** with an AI assistant; Amazon Q in QuickSight was folded into Quick.
- **If** a pilot has ended but the bill keeps coming, **then** **delete the indexes and unused apps** and **remove user subscriptions**. **This works because** Q Business **index capacity bills by the hour** (Starter indexes too) and **users bill monthly** until removed. Track spend with **AWS Cost Explorer**, **AWS Budgets** and **tags**.

Verified from AWS docs on 2026-11-01 (Q Developer overview, Q Business availability change, Quick Suite pricing page).
Unconfirmed (verify): Q Developer feature list beyond the overview page (console cost/troubleshooting features, CLI agent, code transformation languages, reference tracker, customizations); Q Developer Free/Pro limits and prices; data-use terms by tier; Amazon Q in Connect status; CloudTrail coverage; whether console/mobile/chat-app Q Developer experiences have separate end-of-support dates; Kiro details beyond the notice.

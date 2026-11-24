# AWS Well-Architected Framework and Tool

Short notes. Each point is a fact you can be asked about.

**Source note:** the pillars list and the Workloads/HRI/MRI facts in section D2 were checked against AWS docs on 2026-11-09. The rest is product knowledge and marked **(verify)** where unsure.

## A. What it is
- The **AWS Well-Architected Framework** is a set of **design principles and best practices** for building secure, reliable, efficient, cost-effective and sustainable workloads on AWS.
- The **AWS Well-Architected Tool** (console/API/CLI, **free**) lets you **review workloads** against the framework (and lenses), record answers, see **risk**, and get **improvement plans**.
- Use it for: architecture reviews, design decisions, risk tracking, governance reporting. It does not scan your resources by itself (it is a questionnaire), but integrates with Trusted Advisor, Organizations and Jira **(verify)**.
- DEA-C01: know the six pillars and how they apply to data pipelines and the **Data Analytics Lens**.

## B. The six pillars
| Pillar | Focus | Data-pipeline examples |
|---|---|---|
| **Operational Excellence** | Run and monitor systems, continuous improvement | IaC, CI/CD for pipelines, runbooks, observability, game days |
| **Security** | Protect data and systems | Least-privilege IAM, KMS encryption, Lake Formation, VPC endpoints, logging/audit |
| **Reliability** | Recover from failure, meet demand | Multi-AZ, retries/DLQ, idempotent jobs, backups, DR, quotas |
| **Performance Efficiency** | Use resources efficiently as needs change | Right-size Spark/Redshift, partitioning/columnar formats, serverless where suitable |
| **Cost Optimization** | Avoid unnecessary cost | Lifecycle policies, Savings Plans, spot, serverless vs provisioned, data transfer reduction |
| **Sustainability** | Minimize environmental impact | Efficient compute (Graviton), right-size, storage tiering, delete unused data |
- **Pillar order** in exam questions often tests identifying which pillar a practice belongs to.

## C. Design principles (by pillar, short)
- **Operational excellence**: perform operations as code; make frequent small reversible changes; refine procedures; anticipate failure; learn from failures.
- **Security**: strong identity foundation; traceability; security at all layers; automate security; protect data in transit and at rest; keep people away from data; prepare for security events.
- **Reliability**: automatically recover; test recovery; scale horizontally; stop guessing capacity; manage change through automation.
- **Performance efficiency**: democratize advanced technologies; go global in minutes; use serverless; experiment more often; mechanical sympathy.
- **Cost optimization**: implement cloud financial management; adopt a consumption model; measure overall efficiency; stop spending on undifferentiated heavy lifting; analyze and attribute expenditure.
- **Sustainability**: understand impact; set sustainability goals; maximize utilization; anticipate and adopt more efficient offerings; use managed services; reduce downstream impact.

## D. Tool concepts
- **Workload**: the unit reviewed (application + resources + business context): name, description, environment (production/pre-production), Regions, account IDs, industry, architecture diagram URL, review owner.
- **Review**: you answer questions per pillar (choose best practices that apply, mark "none of these" or "question does not apply"). Answers produce a risk rating.
- **Lenses**: additional question sets for a domain. AWS lenses include **Serverless**, **Data Analytics**, **Machine Learning**, **Generative AI**, **SaaS**, **IoT**, **Financial Services Industry**, **Hybrid Networking**, **Container Build**, **SAP**, **Games**, **Sustainability** etc. **Custom lenses** can encode your company standards (JSON).
- **Risks**: **High risk issues (HRI)** and **Medium risk issues (MRI)** flagged by answers; **no risk** otherwise; unanswered questions.
- **Improvement plan**: prioritized list of HRIs/MRIs with guidance links per question.
- **Milestones**: saved snapshots of the workload's review state at points in time to track progress (for example before/after remediation).
- **Sharing**: share workloads with other AWS accounts, IAM users/roles, or across the organization (read or contributor); **lens sharing** too.
- **Profiles** (workload profiles) tailor questions by business priorities **(verify)**.
- **Organizations integration**: aggregate workload data across accounts (delegated admin) **(verify)**.
- **Trusted Advisor integration**: pulls checks relevant to questions to pre-fill or inform answers **(verify)**.
- **Jira integration**: sync improvement items to Jira **(verify)**.
- **Integrations with Partner Network** (AWS Well-Architected Partner Program) for guided reviews.
- **API/CLI**: `create-workload`, `update-answer`, `get-workload`, `create-milestone`, `list-lens-review-improvements`, `export-lens`/`import-lens`.
- **Cost**: the Tool is **free**; reviews via partners may cost.
- **Quotas** (verify): up to ~1,000 workloads per account? custom lenses limited; checks per Region.

## D2. Verified workload facts
- The Framework page confirms **six pillars**: operational excellence, security, reliability, performance efficiency, cost optimization, sustainability.
- A **workload** is "a collection of resources and code that delivers business value" (a customer-facing app or backend process). It can be a subset of one account or span **multiple accounts**.
- The **Workloads** page shows, per workload: name, **owner (AWS account ID)**, **questions answered**, **high risks**, **medium risks**, **improvement status**, last updated.
- **Improvement status** values: **None, Not Started, In Progress, Complete, Risk Acknowledged**.
- **HRIs** are choices AWS found "might result in significant negative impact to a business"; **MRIs** also might hurt but to a lesser extent. They come from **your answers** against the Framework and lenses.
- AWS suggests **documenting reasons** in workload notes when you cannot apply a best practice (risk may then be lower), marking the best practice **met** once fixed, and recording **business approval** if you choose not to fix.
- **Sharing**: a workload can be shared with other **AWS accounts, users, AWS Organizations, or OUs** (View details → Shares).
- **Delete**: only the **owner** can delete a workload; deleting removes **all its milestones** and cannot be undone.
- The docs mention an **AWS Well-Architected Agent in preview** (subject to change) **(verify scope)**.

## E. Data Analytics Lens (key themes)
- **Lens purpose**: best practices for **analytics workloads** (ingestion, storage, processing, analysis, orchestration) across the pillars.
- **Operational excellence**: monitor pipeline health (freshness, lag), automate deployment of data jobs, runbooks for backfills, data quality checks.
- **Security**: data classification, encryption (KMS), fine-grained access (Lake Formation), network isolation (VPC endpoints), audit (CloudTrail), PII discovery (Macie).
- **Reliability**: idempotent, retryable pipelines; checkpointing; DLQs; backups/snapshots; Multi-AZ and cross-Region replication for critical stores; schema evolution handling.
- **Performance efficiency**: choose the right store/engine (Athena vs Redshift vs EMR), partitioning, compression, columnar formats, file sizing, caching, materialized views.
- **Cost optimization**: tiered storage and lifecycle, right-sizing clusters/serverless, spot for EMR, pause Redshift, reduce scans, data transfer minimization, tagging/chargeback.
- **Sustainability**: process less data (pruning), efficient formats, scale to zero, retention policies.
- Also see **Streaming**, **Serverless**, **Machine Learning**, **Generative AI** lenses for adjacent patterns.

## F. How reviews run (process)
1. **Define scope** (workload boundaries, environments, owners).
2. **Choose lenses** (core framework + Data Analytics/Serverless etc.).
3. **Answer questions** with the team (usually a workshop).
4. **Review HRIs/MRIs**; discuss trade-offs and priorities.
5. **Create improvement plan** and backlog items (tickets).
6. **Save a milestone**.
7. **Implement improvements**; re-review periodically; track risk reduction.
- **Cadence**: before launch, after major changes, and at least yearly.
- **Evidence**: use AWS Config/Security Hub/Trusted Advisor/Cost Explorer data to back up answers.

## G. Related services (when to use which)
| Need | Service |
|---|---|
| Review architecture against best practices | **Well-Architected Tool** |
| Automated checks on cost/security/limits/fault tolerance | **Trusted Advisor** |
| Compliance rules on resource configuration | **Config** |
| Security posture score | **Security Hub** |
| Cost visibility | **Cost Explorer / Budgets** |
| Operational insights from ML | **DevOps Guru** |
| Resilience assessment and testing | **Resilience Hub**, **Fault Injection Service** |
| Architecture diagrams/guidance | **AWS Architecture Center / Well-Architected Labs** |
- **Trusted Advisor** categories: cost optimization, performance, security, fault tolerance, service limits, operational excellence (checks depend on Support plan).

## H. Exam skills mapping
- **1.3.2 Pipelines for performance, availability, scalability, resiliency**: resilient, scalable pipeline design.
- **1.2.4 Optimize cost while processing data**: cost optimization pillar.
- **4.1.6 Managed vs unmanaged services**: managed vs unmanaged service choice.

## I. Scenarios: "If X → Y, because Z"
- If a company wants a repeatable architecture review process → **Well-Architected Tool workloads with lenses and milestones**, because it records answers, risks and progress.
- If you need analytics-specific guidance → **Data Analytics Lens**, because it adds pillar questions for ingestion/storage/processing.
- If leadership asks "what are our biggest risks?" → **Review the High Risk Issues and improvement plan**, because they are prioritized by the tool.
- If standards are company-specific (tagging, encryption) → **custom lens**, because it encodes your own questions and best practices.
- If you want to track improvement over time → **milestones**, because they snapshot the review state.
- If a data pipeline lacks retries and alarms → **Reliability and Operational Excellence pillars**, because failure handling and monitoring map there.
- If storage lifecycle and Spot usage are being evaluated → **Cost Optimization pillar**, because they reduce spend.
- If you need automated detection of idle resources and open ports → **Trusted Advisor (and Config/Security Hub)**, because the Tool is a questionnaire, not a scanner.

Verified from AWS docs on 2026-11-09 (Framework pillars page; Workloads page: fields, improvement status, HRI/MRI, sharing, delete).
Unconfirmed (verify): everything in this file — lens list, integrations (Jira, Organizations, Trusted Advisor), quotas, custom lens format, profiles.

# Amazon SageMaker AI – 1. Overview, Studio, domains and Unified Studio

Short notes. Each point is a fact you can be asked about.

## A. What SageMaker is (and the names)
- **Amazon SageMaker AI** = fully managed service to **build, train and deploy ML and foundation models** with managed infrastructure and tools. (**Renamed from "Amazon SageMaker" on 3 Dec 2024**; API namespace `sagemaker`, CLI, `AmazonSageMaker*` managed policies, `AWS::SageMaker::*` CloudFormation, endpoints, console URLs **did not change**.)
- **Amazon SageMaker (next generation, released 3 Dec 2024)** = a **unified platform for data, analytics and AI**, made of:
  - **SageMaker AI** (build/train/deploy ML + FMs).
  - **SageMaker Lakehouse** (one access layer over S3 data lakes, Redshift and other sources; open Iceberg APIs).
  - **SageMaker Data and AI Governance** (**SageMaker Catalog**, built on **Amazon DataZone**).
  - **SQL Analytics** (Redshift), **Data Processing** (Athena, EMR, Glue).
  - **SageMaker Unified Studio** (one development environment for all of it).
  - **Amazon Bedrock** (GenAI apps) available inside Unified Studio.
- **Exam link** (DEA-C01): **SageMaker Unified Studio** domains/domain units/projects (4.1.7), **SageMaker Catalog** for business data catalogs and project data access (2.2.6, 4.5.6), **ML Lineage Tracking** (2.4.4), data prep (3.1.6), Feature Store as a serving store.
- **Pick SageMaker AI when**: you train or host **your own models**, need GPU/Trainium control, custom containers, MLOps pipelines, feature store, or managed fine-tuning of open models. **Pick Bedrock** for API access to foundation models with no hosting. **Pick Canvas** for no-code analysts. **Pick AI services (Comprehend, Textract...)** for standard tasks.

## B. Lifecycle status (check before building; AWS docs, Nov 2026)
- **Maintenance mode: no longer open to new customers from 30 July 2026** (announced 30 June 2026; existing customers keep using them with security/availability fixes only, **no new features**). Per AWS docs and a lifecycle summary:
  - **Model Monitor**, **Clarify**, **Ground Truth** (docs pages confirm the "no longer open to new customers" notice).
  - Also listed in the same group by the lifecycle summary **(verify on each docs page)**: **Augmented AI (A2I)**, **Mechanical Turk integration**, **Debugger**, **geospatial capabilities**, **Role Manager**, **Studio Lab**.
  - **Core SageMaker AI** (training, inference, Pipelines, Registry, Feature Store, JumpStart, HyperPod, Canvas, MLflow, Studio) is **not** affected.
- **Moved or folded**:
  - **Data Wrangler** → integrated into **SageMaker Canvas** (new "Data Wrangler in Canvas" with natural-language data prep). The older Data Wrangler lives in **Studio Classic**.
  - **Autopilot UI** → **Canvas** (the **AutoML API v2** remains for code users).
  - **Studio Classic** is the legacy experience (supported; migration guide to the new Studio exists).
- **Still active (examples)**: Training jobs, Inference options, **Pipelines**, **Model Registry**, **Feature Store**, **MLflow**, **HyperPod**, **JumpStart**, **Canvas**, **Unified Studio**.
- **Replacements AWS suggests**: Model Monitor/Clarify → **open-source monitoring solutions (MLflow + Evidently) + QuickSight + CloudWatch**, plus **SHAP** and **fmeval**; GenAI evaluation → **Bedrock Evaluations/Guardrails** (see file 5).

## C. Environments (where you work)
- **SageMaker Studio** (updated experience): web IDE suite.
  - **JupyterLab** (new, faster, more reliable), **Code Editor** (Code-OSS / VS Code open source), **RStudio**, **Canvas**, **Studio Classic** (legacy app), plus **HyperPod** views, jobs/endpoints/pipelines UI.
  - **Remote access** from your local IDE to **spaces**; **BYO image**; **lifecycle configurations**; **idle shutdown**; **trusted identity propagation**; **NVMe stores**; **local mode**.
- **Domain** = the top-level Studio environment: a set of **user profiles**, **spaces**, apps, an **EFS** home volume, VPC/subnet/security-group settings, an execution role and a KMS key.
  - **Authentication**: **IAM Identity Center** or **IAM**.
  - **Network access type**: **`PublicInternetOnly`** (default; Studio traffic via SageMaker-managed internet) or **`VpcOnly`** (all traffic through **your VPC**; you provide NAT or **VPC endpoints**).
  - **One domain per Region per account** is the default quota (adjustable) **(verify)**.
- **User profile**: a person within the domain (own execution role optional, own space defaults).
- **Space**: workspace for an app (private or **shared** between users). Holds app type, instance type, **EBS volume** and shared directory. **Shared spaces** enable real-time co-editing.
- **App**: a running application (JupyterLab, Code Editor...) on an **instance** you choose. **You pay for the instance while the app runs** (even idle). **Stop apps** or enable **idle shutdown**.
- **Home storage**: **Amazon EFS** auto-mounted per user/space (domain-level). Delete the domain's EFS when cleaning up or it keeps costing.
- **SageMaker Notebook Instances** (older): single EC2-based notebook server (lifecycle configs, root access, direct internet). Still supported; Studio is preferred.
- **SageMaker Canvas**: **no-code** ML. Chat with foundation models, **Ready-to-use models** (powered by Rekognition, Textract, Comprehend), custom models (numeric/categorical prediction, **time-series forecasting**, image and text classification), data prep. Needs a Canvas app; billed by **session (workspace instance hours)** plus model building/inference **(verify)**.
- **SageMaker JumpStart**: model hub and solutions: **pretrained and foundation models** you can **deploy, fine-tune and evaluate**; also integrates **Hugging Face** and some **Bedrock-compatible/import** paths **(verify)**. Deploys to SageMaker endpoints (you pay instances).
- **SageMaker geospatial**: ML on geospatial data (Earth observation jobs). **Maintenance mode** (see section B).
- **Partner AI Apps**: third-party apps (for example experiment tracking, labeling) run inside SageMaker with data kept in your security boundary.
- **Studio Lab**: free notebook environment (no AWS account needed). **Maintenance mode** (see section B).
- **Amazon Q Developer in Canvas** helps solve ML tasks by chat.

## D. SageMaker Unified Studio (the "one place" IDE)
- **What**: a **single web environment** for data, analytics, AI/ML and GenAI work. You sign in through **SSO (IAM Identity Center)** or **IAM credentials** with the **domain URL**.
- **Domain** (Unified Studio) = the organizing boundary. Admins manage **users, groups, domain units, project profiles, blueprints, connections**.
  - **IAM Identity Center–based** domains (workforce SSO) vs **IAM-based** domains **(verify naming)**.
- **Domain units**: hierarchy inside a domain (for example by business unit) to **delegate governance** (own owners, project creation rights, shared rules).
- **Projects**: the collaboration unit. A **project** gets a **project role**, **S3 location**, **compute connections** and **members** (owners/contributors). Work (notebooks, queries, ETL, models, apps) lives in projects.
  - **Project profiles** choose which capabilities (blueprints) a new project gets (for example **SQL analytics**, **data processing**, **ML and generative AI**).
  - **Blueprints/environments** deploy resources (Glue, EMR, Athena, Redshift, SageMaker AI, Bedrock) through **CloudFormation** under the hood.
- **Tools inside**: notebooks, **SQL editor** (Athena/Redshift), **visual ETL**, **Data processing** (Glue/EMR), **model development (SageMaker AI)**, **Bedrock IDE** (build GenAI apps, knowledge bases, agents, flows), **MLflow**, workflows (Airflow-based).
- **SageMaker Catalog** (from Amazon DataZone): **publish** data/AI assets, **business glossary and metadata forms**, **subscriptions** (request access → approve → grant via Lake Formation), **data products**, **lineage**. This is the **business data catalog** for exam skill 2.2.6 and the **governed data access through projects** for 4.5.6.
- **Lakehouse**: tables in **S3 Tables / Iceberg on S3 / Redshift** appear as one catalog; permissions via **Lake Formation**.
- **Governance roles** (DataZone-style): **domain owner**, **domain unit owner**, **project owner**, **project contributor**, **data owner/steward** **(verify exact names)**.
- **IAM for Unified Studio**: domain execution role, **domain service role**, **project role**, **provisioning role**, **manage-access role**; the project role is what notebooks/jobs use (least privilege matters).
- **Cost**: Unified Studio itself is mostly **pay for underlying services** (Glue, EMR, Redshift, Athena, SageMaker AI, Bedrock, S3) and Catalog/DataZone usage **(verify)**.
- **When to use which**: Studio for pure ML engineering; **Unified Studio** when data engineers, analysts and ML teams share governed data and projects.

## E. Compute, instances and naming
- **Instance names**: `ml.<family>.<size>`. Families: **`ml.t3/m5/m6i` (general)**, **`ml.c5/c6i` (compute)**, **`ml.r5` (memory)**, **`ml.g4dn/g5/g6/g6e` (NVIDIA GPU, inference/training)**, **`ml.p3/p4d/p4de/p5/p5e/p6` (large GPU training)**, **`ml.trn1/trn1n/trn2` (Trainium training)**, **`ml.inf1/inf2` (Inferentia inference)**.
- **Start small**: tabular data → small CPU (C5/M5); deep learning → small GPU (G4dn/G5), then scale.
- **Quotas are per instance type per use** (training job usage, endpoint usage, processing job usage, notebook instance usage are **separate**). Exceeding → **`ResourceLimitExceeded`**; request increases in **Service Quotas** (new accounts often have 0 for big GPUs).
- **Capacity**: high-demand GPUs may be unavailable; use **training plans**, **Capacity Blocks (via HyperPod/training plans)**, or other Regions **(verify)**.
- **Heterogeneous clusters**: mix CPU data-processing and GPU training nodes in one job.

## F. Everyday admin features
- **SageMaker Role Manager**: builds **least-privilege persona-based roles** (data scientist, MLOps engineer, compute admin). **Maintenance mode**: write the equivalent IAM policies yourself (file 6).
- **Lifecycle configurations**: scripts run when an app/notebook starts (install libs, set idle shutdown).
- **Idle shutdown**: auto-stop idle JupyterLab/Code Editor apps to save cost.
- **Notebook jobs (notebook-based workflows)**: run a notebook as a **scheduled non-interactive job** (EventBridge).
- **Remote decorator (`@remote`)**: run local Python functions as SageMaker training jobs.
- **Projects (MLOps templates)** (file 5), **Model Cards**, **Model Dashboard** (governance).
- **Tags** on domains, jobs, endpoints for cost allocation (**activate cost allocation tags**).

## G. Pricing basics (details in file 6)
- **Pay for what you use**: instance-hours per second for notebooks/apps, training, processing, endpoints; plus **S3, EBS, EFS**, data transfer.
- **Savings Plans** (SageMaker) and **Spot** (training) reduce cost.
- **Free tier** (new accounts): limited free hours for Studio notebooks, training, hosting for 2 months **(verify)**.

## H. Troubleshooting (symptom → cause → fix)
- **Domain creation or Studio launch fails** → VPC/subnet/security group or NAT/endpoint missing in `VpcOnly` mode, IAM role missing → add endpoints (SageMaker API, runtime, S3, STS, CloudWatch Logs, ECR), fix roles.
- **App will not start** → insufficient **instance quota** or capacity → request quota / change instance type or AZ.
- **No internet from notebook in VpcOnly** → expected; add **NAT gateway** or **VPC endpoints**/mirrors.
- **Unexpected bill** → apps/endpoints left running, EFS retained, large EBS volumes, JumpStart endpoints, Canvas sessions → stop/delete; **idle shutdown**; budgets and tags.
- **User cannot see a shared space** → different domain/profile permissions or Identity Center assignment.
- **Cannot access Unified Studio project data** → project role lacks Lake Formation/S3 permission or subscription not approved.

## I. Scenarios: "If X → Y, because Z"
- If a bank's analysts have no coding skills and need churn prediction → **SageMaker Canvas**, because it is no-code with built-in model building.
- If data engineers, analysts and ML engineers need governed shared data and projects → **SageMaker Unified Studio + SageMaker Catalog**, because projects and subscriptions govern access.
- If you must keep all notebook traffic off the internet → **domain in `VpcOnly` mode with VPC endpoints**, because traffic flows through your VPC.
- If notebooks cost too much overnight → **idle shutdown + lifecycle configuration + stop apps**, because apps bill per instance-hour.
- If a developer wants to run a function on a GPU from a laptop → **`@remote` decorator**, because it launches a training job for that code.
- If you need a business glossary and request/approve data sharing → **SageMaker Catalog**, because it is built on DataZone subscriptions.
- If a team wants Model Monitor/Clarify for a new project → **use open-source monitoring (Evidently + MLflow), SHAP and CloudWatch**, because the managed features are closed to new customers.
- If you need fine-tuning of an open model with a managed UI → **JumpStart** (or Bedrock customization for supported models), because JumpStart wraps training jobs for hub models.

Verified from AWS docs on 2026-11-01 (SageMaker AI overview/rename, features page, Studio overview, Canvas, Autopilot, Data Wrangler, Ground Truth, Model Monitor and Clarify availability pages, Unified Studio overview).
Unconfirmed (verify): Studio Lab status; Unified Studio domain types and role names; Canvas billing details; free-tier terms; one-domain-per-Region quota; JumpStart/Bedrock integration details; instance family list completeness; capacity-block options.

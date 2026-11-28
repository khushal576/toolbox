# AWS AI services – 3. ML infrastructure, lifecycle status and the "which service?" guide

Short notes. Each point is a fact you can be asked about.

## A. ML compute and infrastructure (when you run it yourself)
- **GPU instances (EC2)**: **G4dn/G5/G6/G6e** (NVIDIA T4/A10G/L4/L40S; inference and graphics, small training), **P3/P4d/P4de/P5/P5e/P6** (V100/A100/H100/H200/Blackwell; large training). **UltraClusters** (thousands of GPUs, **EFA** networking, **FSx for Lustre**) for the biggest jobs.
- **AWS Trainium (trn1, trn1n, trn2)**: AWS-designed chips for **training** (lower cost per training run for supported models). **AWS Inferentia (inf1, inf2)**: **inference**. Both use the **AWS Neuron SDK** (PyTorch/JAX via NeuronX; compile ahead of time). **Neuron-compatible code required**.
- **Deep Learning AMIs (DLAMI)** and **Deep Learning Containers (DLC)**: prebuilt PyTorch/TensorFlow/MXNet with CUDA/Neuron; used on EC2, ECS, EKS, SageMaker.
- **Storage for training**: **S3** (datasets), **FSx for Lustre** (linked to S3; high throughput for repeated epochs), **EFS** (shared home), **EBS/instance store NVMe** (local scratch). Use **S3 Express One Zone** for low-latency reads **(verify)**.
- **Networking**: **EFA** + cluster **placement groups** (single AZ) for distributed training; **Elastic Fabric Adapter** needs supported instance types.
- **Orchestration**: **SageMaker training jobs / HyperPod** (managed), **EKS** (Kubernetes, **Karpenter**, Kubeflow/Ray), **AWS Batch** (job queues with GPUs/Spot), **ParallelCluster** (Slurm HPC), **ECS**.
- **Capacity**: **On-Demand Capacity Reservations**, **EC2 Capacity Blocks for ML** (reserve GPU for days/weeks), **Savings Plans**, **Spot** (interruptible training/batch with checkpoints), **SageMaker training plans**.
- **Edge/IoT**: **IoT Greengrass** runs ML inference at the edge with models trained in SageMaker.
- **Serving your own models outside SageMaker**: **EKS/ECS + GPU nodes**, **Lambda** (small CPU models, container images up to 10 GB), **App Runner** (**closed to new customers: verify**), **Inferentia on EC2/EKS**.
- **Choose**: managed + MLOps → **SageMaker AI**; Kubernetes-native → **EKS**; HPC style → **ParallelCluster/HyperPod Slurm**; tiny/spiky → **Lambda or SageMaker serverless**.

## B. Lifecycle status table (services in maintenance mode; AWS docs and lifecycle summary, as of 2026-11-01; verify each service page)
| Service / feature | Status | Date(s) | What to use instead |
|---|---|---|---|
| **Amazon Kendra** | Maintenance; **closed to new customers** | New customers stop 30 Jul 2026 | **Bedrock Managed Knowledge Base** |
| **Amazon Q Business** (incl. Q Apps) | Maintenance; **closed to new customers** | 30 Jul 2026 | **Amazon Quick** (Flows replace Q Apps) |
| **Bedrock Agents Classic** | Maintenance; **closed to new accounts** | 30 Jul 2026 | **Bedrock AgentCore** |
| **SageMaker AI: Model Monitor, Clarify, Ground Truth** | Maintenance; closed to new customers | 30 Jul 2026 | Evidently + MLflow + CloudWatch; SHAP/fmeval; other labeling tools |
| **SageMaker AI: A2I, Mechanical Turk, Debugger, geospatial, Role Manager, Studio Lab** | Maintenance (per summary; verify) | 30 Jul 2026 | Custom review UIs, framework profilers, hand-written IAM roles |
| **Amazon Forecast** | Maintenance | Announced 29 Jul 2024 | **SageMaker Canvas** / AutoML time-series / DeepAR |
| **CodeGuru Reviewer** | Maintenance | Announced 7 Oct 2025 | Other code review tools |
| **Comprehend: Topic Modeling, Event Detection, Prompt Safety Classification** | Maintenance (features only) | Announced 31 Mar 2026 | LLMs, Bedrock Guardrails |
| **Rekognition: Streaming Events, Batch Image Content Moderation** | Maintenance (features only) | Announced 31 Mar 2026 | Other moderation workflows |
| **Glue Ray jobs** | Maintenance | Announced 31 Mar 2026 | Glue Spark, EMR, SageMaker/Ray on HyperPod |
| **Timestream for LiveAnalytics** | Maintenance | Announced 20 Jun 2025 | Timestream for InfluxDB |
- **Not mentioned in the summary I read (assume active; verify)**: **Textract, Transcribe, Translate, Polly, Lex, Personalize (core), HealthLake, Entity Resolution, Clean Rooms ML, DevOps Guru, SageMaker core features, Comprehend core, Rekognition core**.
- **Maintenance mode means**: existing customers keep using it with **security and availability fixes**, **no new features**, and **new customers are blocked**.
- **How to react**: inventory usage (AWS Health, Trusted Advisor, service pages), design replacements early, and keep exports of data/models.
- **Sunset, shut-down and end-of-support services are not covered in these notes** (removed on request). Check AWS announcements before relying on any older AI service.

## C. The "which service?" decision guide
| Goal | Pick |
|---|---|
| Chat/summarize/extract with LLMs, no hosting | **Bedrock** |
| RAG over your documents | **Bedrock Managed Knowledge Base** (+ vector store choices) |
| Build agents with tools | **Bedrock AgentCore** |
| Employee assistant app | **Amazon Quick** |
| OCR, tables, forms, invoices | **Textract** (or Bedrock Data Automation for flexible schemas) |
| Sentiment, entities, PII in text | **Comprehend** (or LLM) |
| Image/video labels, faces, moderation | **Rekognition** |
| Speech to text / text to speech / translate | **Transcribe / Polly / Translate** |
| Task chatbot with slots | **Lex** (or agents) |
| Recommendations | **Personalize** |
| Forecasting | **SageMaker Canvas/AutoML/DeepAR** (Forecast is in maintenance) |
| Fraud/anomaly | **SageMaker (XGBoost/RCF)**, WAF fraud control, OpenSearch anomaly detection |
| Match customer records | **Entity Resolution** |
| Joint analytics without sharing data | **Clean Rooms (+ ML)** |
| SQL analysts need models | **Redshift ML**, Athena ML, Aurora ML |
| Custom model training/hosting, MLOps | **SageMaker AI** |
| No-code ML for analysts | **SageMaker Canvas** |
| Large FM training | **SageMaker HyperPod / training plans**, Trainium/GPU |
| Vector search | **Vector store options** (see `vector-stores`) |
| Governed data + AI projects | **SageMaker Unified Studio + Catalog** |
| Ops anomaly insights | **DevOps Guru** (verify), CloudWatch anomaly detection |
| Sensitive data in S3 | **Macie** |
- **Ordering of effort/cost (rough)**: AI service API < Bedrock API < SageMaker custom model < self-managed GPU cluster. **Control** rises in the same order.
- **When to build custom** (SageMaker): unique data/labels, accuracy gap vs generic services, strict latency/cost at huge scale, regulatory control over model internals.
- **When to buy** (AI service/Bedrock): standard tasks, small team, need results in days.

## D. Common architecture patterns (data engineering view)
- **Document pipeline**: S3 → Textract (async) → Lambda parse → Comprehend (PII) → **Bedrock** (classify/summarize) → DynamoDB/OpenSearch → QuickSight. Add **human review** by your own UI/queue for low confidence (A2I in maintenance).
- **Media pipeline**: S3 video → **Transcribe** + **Rekognition** → **Translate** → **Bedrock** summaries → **OpenSearch** (search) → **Polly** voice output.
- **Streaming scoring**: Kinesis → Lambda/Flink → **SageMaker endpoint** (or Redshift ML) → S3/DynamoDB. Monitor drift (file 5 of SageMaker).
- **Feature + model loop**: Glue/EMR → **Feature Store** → SageMaker training → Registry → endpoint → monitoring → retrain.
- **RAG loop**: S3 docs → (Textract/BDA parsing) → **Bedrock KB** → app; evaluate with **Bedrock evaluations**.
- **Privacy-safe collaboration**: Entity Resolution → Clean Rooms.
- **Governance**: Lake Formation + Catalog for data; Model Registry/Cards for models; **Guardrails** for GenAI; **Macie** for S3 PII; **CloudTrail** everywhere.

## E. Shared security and cost rules for AI services
- **Use roles, least privilege, KMS and PrivateLink**; set the **AI services opt-out policy** in Organizations if content must not be used to improve services.
- **Never send secrets/PII** you do not need; mask first.
- **Cost drivers**: per-unit API fees, **custom model training and always-on endpoints/inference hours** (Comprehend custom endpoints, Rekognition Custom Labels, Personalize campaigns), **GPU hours**, storage and data transfer.
- **Control**: async/batch, caching, tier discounts, **stop idle endpoints**, **Budgets + Anomaly Detection**, tag by project.
- **Exam angle (DEA-C01)**: know **which service solves which data task** (Textract/Comprehend/Rekognition/Transcribe/Translate/Polly), **Redshift ML/Athena ML**, **SageMaker Feature Store and Pipelines** basics, **Macie** for PII, and that **managed AI services remove ML ops work**.

## F. Scenarios: "If X → Y, because Z"
- **If** a startup asks for "AI search over documents", **then** use **Amazon Bedrock Managed Knowledge Base**, not **Amazon Kendra**. A knowledge base does retrieval-augmented generation (RAG) over your documents. **This works because** Kendra is in **maintenance mode** and **closed to new customers** from **30 Jul 2026**, and AWS names Bedrock Managed Knowledge Base as its replacement.
- **If** an existing app uses **Amazon Forecast**, **then** plan a migration to **Amazon SageMaker Canvas** or **AutoML time-series** (or **DeepAR**). **This works because** Forecast has been in **maintenance mode** since **29 Jul 2024**: it gets only security and availability fixes, **no new features**, so you should design the replacement early and export your data.
- **If** a team needs GPUs for a 3-week training run next month, **then** reserve them with **Amazon EC2 Capacity Blocks for ML** or a **SageMaker training plan** **(verify details)**. **This works because** Capacity Blocks **reserve GPU capacity for days or weeks** ahead of time, so the run is not blocked when scarce GPUs are sold out.
- **If** the cost per training run must drop and the model is supported, **then** train on **AWS Trainium** (trn1, trn2) instances with the **AWS Neuron SDK**. Trainium is an AWS-designed chip for training. **This works because** it gives a **lower cost per training run** than comparable GPUs for supported models. The catch: code must be **Neuron-compatible** and compiled ahead of time.
- **If** you need Kubernetes-native distributed training, **then** use **Amazon Elastic Kubernetes Service (EKS)**, or **SageMaker HyperPod** on EKS. **This works because** EKS runs Kubernetes tools such as **Kubeflow, Ray and Karpenter**, and HyperPod adds a managed cluster for large training jobs.
- **If** an analyst wants to score a table from SQL, **then** use **Amazon Redshift ML** or **Amazon Athena ML** (Athena needs an **existing SageMaker endpoint**). **This works because** both turn model predictions into **SQL function calls**: Redshift ML trains and deploys a model as a SQL function, and Athena ML calls a SageMaker endpoint you already host.
- **If** a pipeline needs OCR, PII masking and a summary, **then** chain **Amazon Textract → Amazon Comprehend → Amazon Bedrock**. **This works because** each service does one step cheaply: **Textract** reads the text from documents, **Comprehend** detects and masks personally identifiable information (PII), and **Bedrock** summarizes with a foundation model. Add your own human review queue for low-confidence results (A2I is in maintenance).

Verified from AWS docs on 2026-11-01 via the AWS lifecycle summary (dev.classmethod.jp, 30 Jun 2026 roundup) and the individual Kendra, Q Business, Bedrock Agents Classic, SageMaker, Model Monitor, Clarify and Ground Truth docs pages.
Unconfirmed (verify): the exact membership of the 9-feature SageMaker maintenance group (A2I, Mechanical Turk, Debugger, geospatial, Role Manager, Studio Lab beyond the three confirmed on docs pages); App Runner status; any lifecycle notice for Textract, Transcribe, Translate, Polly, Lex, Personalize, HealthLake, DevOps Guru; S3 Express One Zone for training; Capacity Blocks details.

# Amazon SageMaker AI – 6. Security, cost, limits, troubleshooting and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Identity and access (IAM)
- **Execution role**: the IAM role SageMaker **assumes** to run notebooks/apps, training, processing, transform and endpoints. Trust principal **`sagemaker.amazonaws.com`**. Needs S3, ECR, CloudWatch Logs, KMS and (if used) VPC/ENI permissions.
- **`iam:PassRole`**: the **caller** creating a job/endpoint needs it for the execution role. Restrict with `iam:PassedToService = sagemaker.amazonaws.com` and role ARN.
- **Least privilege**: separate roles per persona and per environment: **data scientist** (create jobs, read specific buckets), **MLOps engineer** (pipelines, registry, deploy), **compute admin** (domains, quotas), **endpoint invokers** (only `sagemaker:InvokeEndpoint` on named endpoints). **SageMaker Role Manager** creates persona roles (**now in maintenance mode**: closed to new customers from 30 July 2026, so write the persona policies yourself).
- **Managed policies**: `AmazonSageMakerFullAccess` (broad; avoid in production), `AmazonSageMakerReadOnly`, `AmazonSageMakerCanvasFullAccess`, service-role policies for Pipelines/Projects. Prefer **custom scoped policies**.
- **Condition keys** (resource and request): `sagemaker:VolumeKmsKey`, `sagemaker:OutputKmsKey`, `sagemaker:RootAccess` (Disabled), `sagemaker:DirectInternetAccess` (Disabled), `sagemaker:VpcSubnets`, `sagemaker:VpcSecurityGroupIds`, `sagemaker:NetworkIsolation`, `sagemaker:InterContainerTrafficEncryption`, `sagemaker:InstanceTypes`, `sagemaker:DomainId`, `aws:ResourceTag/*`, `aws:RequestTag/*`.
  - Use them to **force** encrypted volumes, VPC attachment, network isolation, and approved instance types (and to **block GPU instances** for dev roles).
- **Studio access**: **IAM Identity Center** (SSO, per-user profiles) or **IAM**; **presigned domain URLs** for apps (short lived; restrict `sagemaker:CreatePresignedDomainUrl` by IP/VPC endpoint with `aws:SourceIp`/`aws:SourceVpce`).
- **Tag-based/ABAC**: tag users/spaces/jobs and write policies on tags (for example a user can only stop their own apps).
- **Endpoints**: resource policies and IAM on `sagemaker:InvokeEndpoint`/`InvokeEndpointAsync`; for external callers put **API Gateway/Lambda** in front with IAM/Cognito auth.
- **Cross-account**: Model Registry/feature groups/ECR/S3 sharing needs **resource policies + KMS key policies**.
- **MLflow**: `sagemaker-mlflow:*` actions.
- **Unified Studio**: domain/project roles (file 1); keep project roles least-privilege and tie data access to **Lake Formation**.

## B. Network security
- **VPC for jobs and endpoints**: pass **`VpcConfig`** (subnets + security groups) so training, processing, transform and hosting containers run **inside your VPC** (ENIs). Use **private subnets**.
- **Studio `VpcOnly` mode**: all traffic via your VPC. Provide **NAT gateway or VPC interface endpoints** for **SageMaker API, SageMaker Runtime, S3 (gateway), STS, CloudWatch Logs/Monitoring, ECR (api + dkr), Service Catalog (Projects), CodeCommit/Git, KMS**. Security groups must allow **NFS (2049) to EFS** and **intra-domain app traffic** (ports for Jupyter/kernel gateway) **(verify exact ports)**.
- **Network isolation (`EnableNetworkIsolation`)**: the container has **no outbound network** (no S3 calls from inside; SageMaker still delivers data/model). Use for untrusted code/models and **AWS Marketplace algorithm** containers (internet-free mode).
- **Inter-container traffic encryption** for **distributed training** (`EnableInterContainerTrafficEncryption`) encrypts traffic between training nodes (may slow training).
- **PrivateLink endpoints**: `com.amazonaws.<region>.sagemaker.api`, `.sagemaker.runtime`, `.sagemaker.runtime-fips`, **notebook**, **studio** (for Studio access) **(verify names)**, with **endpoint policies**.
- **Access to private data stores** (RDS, Redshift, EFS, FSx): same VPC or peering/Transit Gateway; **S3 gateway endpoint** with bucket policies (`aws:SourceVpce`).
- **Marketplace containers** and **AWS prebuilt images** are **scanned for CVEs**.
- **Egress control**: **disable direct internet access** on notebook instances/Studio (`DirectInternetAccess=Disabled`) and use proxies/allow-lists if packages are needed (mirror PyPI/conda via **CodeArtifact**).

## C. Encryption and data protection
- **At rest**: **KMS** for **notebook/Studio EBS volumes** (`VolumeKmsKeyId`), **training/processing/endpoint volumes**, **S3 outputs** (`OutputDataConfig.KmsKeyId`), **EFS** (domain), **Feature Store** (online and offline), **Model Registry artifacts in S3**, **HyperPod volumes** (customer-managed key), **MLflow** (KMS for apps), **batch transform** output.
- **In transit**: **TLS 1.2+** (1.3 recommended) for APIs; **inter-container encryption** option; HTTPS for endpoint invocations.
- **Key policies** must allow the **execution role** and (for cross-account) the other account's roles.
- **Secrets**: store credentials in **Secrets Manager/Parameter Store**, not in notebooks/hyperparameters/environment variables; training **hyperparameters and tags show in logs**.
- **Data privacy**: SageMaker does not use your data to train AWS services; you control S3 data. **Do not put PII or secrets in resource names, tags, feature group descriptions**.
- **Data minimization**: scrub PII before training (Macie/Comprehend/Glue), mask with **Lake Formation** column/row security, use **synthetic/de-identified** data in dev.
- **Model artifacts** are sensitive IP: lock S3 buckets (versioning, Object Lock if needed, block public access), restrict ECR repos.
- **Model theft/abuse**: authenticate endpoints, rate limit via API Gateway/WAF, monitor unusual invocation patterns.
- **LLM/GenAI risks**: prompt injection, data leakage, harmful output: use **Guardrails (Bedrock)** or custom filters around endpoints; evaluate with **fmeval/Bedrock Evaluations**.

## D. Audit, logging, compliance
- **CloudTrail**: all SageMaker API calls (management events); **`InvokeEndpoint` is a data event** (opt in); MLflow app data events (opt in).
- **CloudWatch Logs**: training/processing/transform/endpoint/notebook logs; **encrypt log groups with KMS**; set **retention**.
- **CloudWatch metrics and alarms**; **EventBridge** for job/endpoint/pipeline/registry state changes.
- **AWS Config**: tracks SageMaker resource configuration (for example notebook instances without VPC, endpoints without KMS) **(verify rules)**; **Security Hub** controls (for example "notebook instances should be in a VPC", "should not have direct internet access", "endpoints should have KMS") **(verify list)**.
- **Lineage and Model Cards** support **model governance**; **Audit Manager** frameworks for AI **(verify)**.
- **Compliance**: SageMaker AI is in scope for many programs (SOC, ISO, PCI DSS, HIPAA eligible, FedRAMP, etc.) **(verify per Region/feature)**.
- **Resilience**: multi-AZ endpoints (≥2 instances), cross-Region copies of **model artifacts** and **ECR images**, **Feature Store** multi-AZ, back up **EFS** and S3 artifacts.

## E. Cost model: what you pay for
- **Per-second billing (60 s minimum for some)** of **ML instance usage** across: **Studio apps/notebook instances**, **training jobs**, **processing jobs**, **real-time endpoints**, **async endpoints (when instances run)**, **batch transform**, **HyperPod nodes**, **warm pools**, **Canvas sessions**.
- **Serverless inference**: compute duration (ms, by memory size) + data processed; **provisioned concurrency** per hour.
- **Storage and data**: **S3** (data, models, checkpoints, logs), **EBS** volumes attached to instances, **EFS** (domain home), **ECR**, **Feature Store online/offline**, **data transfer** (cross-AZ/Region/internet), **NAT gateway** for VpcOnly setups.
- **Other**: **CloudWatch Logs/metrics**, **MLflow** tracking servers/apps (servers **bill while running**; stop them), **Catalog/Unified Studio** underlying services, **Pipelines** has no orchestration fee, **Data Wrangler/Canvas** instance/session costs, **JumpStart** endpoints.
- **Free tier** (page excerpt): first **2 months**, **250 hours of `sc.t3.medium`** for notebooks; existing Free Tier allocations carry over to Unified Studio **(verify full terms)**. SageMaker Data Agent about **$0.04 per credit** in the pricing page excerpt **(verify)**.
- **Savings Plans**: **SageMaker Savings Plans** commit to a **$/hour** for 1 or 3 years across eligible usage (Studio, training, processing, hosting, batch) regardless of instance family/Region **(discount percentages not on the page excerpt; verify)**.

## F. Cost optimization checklist
- **Stop idle**: Studio apps (**idle shutdown**), notebook instances, **MLflow tracking servers**, Canvas sessions, **HyperPod clusters**, JumpStart/dev **endpoints** (nightly schedules).
- **Right-size**: use **Debugger or CloudWatch/framework profilers** (training), **Inference Recommender** (endpoints), CloudWatch utilization.
- **Spot** for training (with checkpoints) and tuning; **Spot** for Studio? (not available) **(verify)**.
- **Pipes/FastFile + sharded data** reduce training wall time.
- **Autoscale endpoints**; use **serverless** or **async scale-to-zero** for spiky traffic; **batch transform** for offline scoring.
- **Share hardware**: **multi-model endpoints**, **inference components**, **GPU partitioning**.
- **Cheaper silicon**: **Inferentia/Trainium** where supported.
- **Warm pools** only when iterating frequently (they bill while warm).
- **Cache pipeline steps**; **avoid re-training** unless drift/metrics justify.
- **Smaller/LoRA fine-tunes** and **distillation** instead of full fine-tunes.
- **Storage hygiene**: lifecycle rules on S3 checkpoints/artifacts, delete old model versions/EBS/EFS leftovers, delete unused ECR images.
- **Tag everything** (`team`, `project`, `env`) and activate **cost allocation tags**; set **Budgets** with alerts and **Cost Anomaly Detection** on SageMaker; use **quotas** to cap GPU use (instance-type quotas act as guardrails).
- **SCP/IAM** to deny expensive instance types for dev accounts.

## G. Quotas and limits (typical; always check Service Quotas)
- **Per instance type and per usage** (training job usage, processing job usage, endpoint usage, transform job usage, notebook/Studio app usage, spot training) are **separate quotas**; new accounts start low or at **0** for big GPUs.
- **Serverless**: **200** max concurrency per endpoint, **1,000/500** per Region, **50 endpoints** per Region; memory **1–6 GB**; container image **10 GB**.
- **Async**: **1 GB** payload, **1 hour** processing. **Batch transform**: `MaxPayloadInMB` ≤ **100 MB**.
- **Real-time**: payload about **25 MB**, response timeout **60 s** **(verify)**.
- **Training**: **max runtime** configurable (up to **28 days**) **(verify)**; **many hyperparameters limit** (up to 100 per job) **(verify)**.
- **Feature Store, pipelines, model registry, experiments**: object-count and throughput quotas **(verify)**.
- **MLflow tracking server sizes**: sustained TPS **25/50/100**; **200 MB** download limit.
- **Studio**: apps per space/profile limits **(verify)**.
- **Increase requests**: Service Quotas console; plan GPU requests **weeks** ahead.

## H. Troubleshooting grid (cross-cutting)
- **AccessDenied on S3/ECR in a job** → execution role/bucket policy/KMS key policy/VPC endpoint policy missing → fix the trust and resource policies.
- **Job in VPC cannot reach S3/ECR/CloudWatch** → missing endpoints or NAT → add gateway/interface endpoints and routes.
- **`ResourceLimitExceeded`** → quota for that instance type and usage → request increase.
- **Studio `VpcOnly` app stuck starting** → missing endpoints (api/runtime/STS/ECR/Logs), security group rules (EFS NFS) → add them.
- **KMS errors (`AccessDeniedException` on `kms:Decrypt/GenerateDataKey`)** → key policy lacks the role → update key policy.
- **Large bill** → idle resources, oversized instances, forgotten endpoints/MLflow servers/EFS, GPU experimentation → list running resources (`list-endpoints`, `list-apps`, `list-notebook-instances`), stop and tag.
- **Endpoint invoke 403** → caller lacks `sagemaker:InvokeEndpoint` or VPC endpoint policy blocks → fix IAM/policy.
- **Container fails health check** → app not listening on 8080 or `/ping` slow → fix container entrypoint.

## I. Exam-style design scenarios: "If X → Y, because Z"
- If notebooks must have **no internet** and encrypt volumes → **VpcOnly domain, `DirectInternetAccess=Disabled`, KMS volume key, VPC endpoints**, because traffic stays private and storage is encrypted.
- If you must **enforce** that all training jobs use a VPC and KMS → **IAM/SCP conditions (`sagemaker:VpcSubnets`, `sagemaker:VolumeKmsKey`)**, because condition keys deny non-compliant API calls.
- If a vendor model container is untrusted → **network isolation**, because it blocks outbound calls from the container.
- If distributed training traffic must be encrypted → **inter-container traffic encryption**, because nodes exchange data over the VPC.
- If only specific apps may call a private endpoint → **VPC endpoint policy + IAM `InvokeEndpoint` scoped to the endpoint**, because both layers restrict callers.
- If cost must be capped for development → **limit instance types by SCP/IAM, quotas, idle shutdown, budgets**, because they prevent and detect runaway GPU use.
- If traffic is steady 24/7 and predictable → **Savings Plans + right-sized real-time endpoints**, because commitments lower hourly cost.
- If an endpoint is idle most of the day → **serverless or async scale-to-zero (or scheduled scale-down)**, because instance-hours drive cost.
- If auditors need to know who invoked a model → **CloudTrail data events for `InvokeEndpoint` + endpoint data capture**, because management events do not include invocations.
- If you must share a registered model with another account → **Model Registry resource policy + cross-account ECR/S3/KMS access**, because deployment pulls artifacts from those resources.
- If training data contains PII → **mask/remove before training (Macie/Comprehend/Lake Formation) and encrypt outputs**, because models and logs can leak data.
- If a team needs a production-grade ML platform quickly → **Studio/Unified Studio + Pipelines + Registry + MLflow (+ Projects templates)**, because they provide governed building blocks.
- If you only need OCR or sentiment → **Textract/Comprehend instead of custom SageMaker models**, because managed AI services are cheaper and simpler.

Verified from AWS docs on 2026-11-01 (infrastructure security, Studio, serverless, async, batch transform, Pipelines, Projects, Model Monitor/Clarify availability, HyperPod, pricing page excerpt).
Unconfirmed (verify): condition-key names beyond the commonly documented set; PrivateLink service names and Studio port requirements; Security Hub/Config control lists; Savings Plans discount percentages; the 60-second billing minimums; Spot support outside training; training max runtime and hyperparameter limits; real-time payload/timeout; free-tier terms beyond the 250-hour notebook example; MLflow tracking-server billing details.

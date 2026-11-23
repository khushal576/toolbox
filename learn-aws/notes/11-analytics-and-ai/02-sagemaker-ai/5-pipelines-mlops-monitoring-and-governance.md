# Amazon SageMaker AI – 5. Pipelines, MLOps, monitoring and governance

Short notes. Each point is a fact you can be asked about.

## A. MLOps in one picture
- **MLOps** = apply DevOps ideas to ML: **version everything** (code, data, features, models), **automate** train → evaluate → register → deploy, **monitor** in production, and **retrain** when needed.
- **Typical SageMaker flow**: data in S3/lakehouse → **Processing** (features) → **Training/Tuning** → **Evaluation** → **Condition** (is it good enough?) → **Register model** (approval status) → **Deploy** (endpoint/batch) → **Monitor** (drift/quality) → trigger **retrain**.
- **Triggers**: **code commit**, **new data in S3** (EventBridge), **schedule**, **model approval** (EventBridge on Registry status), **drift alarm**.
- **Environments**: **dev → staging → prod accounts** (multi-account), promote **registered model versions** with cross-account permissions.

## B. SageMaker Pipelines
- **What**: purpose-built **workflow orchestration for ML**. **Serverless** orchestration (no servers), authored in the **Python SDK**, **visual editor in Studio**, JSON definition, or APIs. **You pay only for the Studio/resources and the underlying jobs** (training, processing, inference, S3), not for the pipeline orchestration itself.
- **Core objects**: **Pipeline** (a **DAG** of steps), **Parameters** (`ParameterString/Integer/Float/Boolean` to reuse a pipeline with different inputs), **Execution** (a run; can be started manually, by **EventBridge**, API, SDK), **Step properties** (outputs passed between steps).
- **Common step types** (know these):
  - **Processing**, **Training**, **Tuning** (hyperparameter), **AutoML**, **Transform** (batch), **Model/CreateModel**, **RegisterModel** (Model Registry), **Condition** (if/else on metrics), **Callback** (wait for an external system through SQS), **Lambda**, **EMR** (run EMR steps), **Notebook job**, **Clarify check / QualityCheck** (data/model quality baselines; **tied to Clarify/Model Monitor**, now in maintenance), **Fail** (stop with a message), **Deploy model** / endpoint steps **(verify)**.
- **Step caching**: reuse results of a previous identical step (same arguments, **cache expiry** like `P30d`) to **save time and money**.
- **Retry policies** on steps (exception types, intervals, backoff).
- **Selective execution**: rerun chosen steps of a previous execution.
- **Lineage and versioning**: every execution is recorded; **ML Lineage Tracking** links artifacts automatically; pipelines have **versions**.
- **Local mode** and **notebook jobs** for testing.
- **Integration with other tools**: trigger from **EventBridge**; **Step Functions** has SageMaker tasks (`createTrainingJob.sync`, etc.); **Apache Airflow/MWAA** operators; **CodePipeline** can start Pipelines.
- **Pipelines vs alternatives**:
  - **Pipelines**: ML-native, lineage, caching, Registry integration, **SageMaker-centric**.
  - **Step Functions**: general-purpose, **error handling/branching/long waits/human approval**, **mixes many AWS services** (Glue, EMR, Lambda); good for end-to-end **data + ML** workflows.
  - **MWAA (Airflow)**: if you already use Airflow DAGs and Python operators.
  - **Kubeflow/Argo on EKS/HyperPod**: Kubernetes-native teams.
- **Limits**: steps per pipeline, parallelism and max execution time are quota-governed **(verify)**.

## C. SageMaker Projects (MLOps templates)
- **Projects** deploy an **end-to-end MLOps solution** (CI/CD) from a **template**: **source repo**, **build pipeline (CodeBuild)**, **model-build Pipeline**, **model registry group**, **deploy pipeline** (staging and production), **EventBridge** triggers.
- **Template sources**: **AWS Service Catalog**-based **AWS templates** (CodeCommit or **GitHub/third-party Git** with CodeStar Connections) and **custom organization templates**.
- **You see** project resources in Studio. **Delete projects** to remove CloudFormation stacks (check leftover endpoints).
- **Admins** need **Service Catalog** portfolio permissions and Studio project permissions; projects use **launch roles** (`AmazonSageMakerServiceCatalogProductsLaunchRole`) **(verify)**.
- **In Unified Studio**, **projects are a different concept** (collaboration/governance unit; file 1). Do not mix them up.
- **CI/CD pattern**: Git push → CodePipeline → CodeBuild runs the **Pipelines definition** → pipeline trains and **registers** a model (**PendingManualApproval**) → **approver** sets **Approved** → EventBridge triggers the **deployment pipeline** (CloudFormation) → **staging endpoint** test → manual approval → **prod endpoint**.

## D. Model Registry, cards and dashboard (governance)
- **Model Registry**: model groups → **versions** with approval status, metrics, lineage, **cross-account sharing**; **approval event** drives deployment (file 4).
- **Model Cards**: structured **documentation** (intended use, training details, evaluation results, risk rating, owners) for **governance and audits**.
- **Model Dashboard**: a **single view** of models, endpoints, jobs, and **monitoring status** (it integrates Model Monitor info, transform jobs, endpoints, lineage, CloudWatch).
- **SageMaker Role Manager** for least-privilege personas (**maintenance mode** for new customers).
- **SageMaker Catalog / DataZone** for **data and AI asset** discovery and approval workflows (file 1).
- **Audit**: **CloudTrail** (API calls), **lineage**, **MLflow runs**, **Pipelines executions**, **Config/Security Hub** controls for SageMaker resources (**verify**).

## E. Monitoring ML in production
- **What to monitor**: **system health** (latency, errors, CPU/GPU), **data quality** (missing values, schema change), **data drift** (input distribution shift), **model quality** (accuracy with ground truth, often delayed), **bias drift**, **feature-attribution drift**, **business KPIs**, and for LLMs **safety/relevance/hallucination**.
- **SageMaker Model Monitor (existing customers only)**:
  - **No longer open to new customers.** Existing customers can continue; **no new features**.
  - **Four monitor types**: **data quality**, **model quality**, **bias drift**, **feature attribution drift**.
  - **How it works**: enable **data capture** on the endpoint (or batch transform) → create a **baseline** (statistics + constraints from training data) → create a **monitoring schedule** (processing jobs, for example hourly) → reports compare to the baseline and list **violations** → **CloudWatch metrics** and alarms.
  - **Limits/notes**: **tabular data** statistics only; **single-model endpoints only** (no **multi-model endpoints**); **inference pipelines** analyzed as a whole; **keep disk use below 75%** or data capture stops; Studio in custom **VPC needs endpoints** for S3 and CloudWatch.
- **Replacement path AWS recommends** for new work:
  - **Open-source monitoring solutions** (in `aws-samples`): **SageMaker AI MLflow Apps + Evidently AI** (PSI and KS drift, `DataDriftPreset`, `ClassificationPreset`, `DataSummaryPreset`), orchestrated by **EventBridge + Lambda/Pipelines**, **Athena + Iceberg** tables, **SNS** alerts, **QuickSight** dashboards.
  - Variants: **batch monitoring pipeline**, **real-time endpoint monitoring (data capture)**, **QuickSight governance dashboards (delayed ground truth)**, **LLM inference monitoring**, **Grafana** resource and LLM quality dashboards.
  - **CloudWatch** custom metrics + **anomaly detection alarms** for light checks, and endpoint **enhanced metrics**.
  - Default thresholds in the samples (examples): alert when **more than 30% of features drift** (batch) or `drifted_columns_share` above **0.05** (real-time light solution); model quality alerts at **F1 0.70, accuracy 0.80, ROC-AUC 0.75** (configurable).
- **Clarify (existing customers only)**: **no longer open to new customers**. Replace with **pandas/scikit-learn computed bias metrics** (DPL, DPPL, DI, CI), **SHAP** for explanations, **fmeval** for LLM evaluation, **Bedrock Evaluations/Guardrails** for GenAI.
- **Ground truth latency**: capture **inference IDs** so labels arriving later can be **joined** to predictions for quality metrics.
- **Retraining triggers**: drift alarm → EventBridge → start **Pipelines** execution → new model **PendingManualApproval**.
- **Cost**: monitoring jobs use **Processing instances on a schedule** (for example `ml.m5.xlarge` hourly); **delete unused schedules**.

## F. MLflow in the MLOps loop
- **Managed MLflow** tracks **experiments, runs, artifacts, and GenAI traces**; **MLflow Model Registry → SageMaker Model Registry** automatic registration; **EventBridge events** for tracking-server and registry changes (for example version stage transitions) can trigger pipelines.
- **Tracking server vs MLflow App**: servers have **sizes (Small/Medium/Large)** and run in **one AZ**; **Apps** are the newer option on **MLflow 3.x** in many Regions.
- **IAM**: `sagemaker-mlflow:*` actions; **KMS** for apps; **CloudTrail** (data events for apps are opt-in).

## G. Data and ML lineage across the stack
- **Data side**: **Glue Data Catalog**, **Lake Formation**, **SageMaker Catalog/DataZone lineage**, **OpenLineage** events from Glue/EMR/MWAA **(verify)**.
- **ML side**: **SageMaker ML Lineage Tracking**, **MLflow runs**, **Pipelines execution graph**, **Model Registry versions linked to training jobs and datasets**.
- **Answer to audits**: dataset version → processing job → feature group → training job → model package → endpoint → monitoring report.

## H. Testing and quality gates
- **Unit-test** processing/training code; **data tests** (Great Expectations/Deequ/Glue Data Quality) as a **pipeline step**.
- **Evaluation step** writes **metrics JSON** → **Condition step** compares to thresholds (for example AUC ≥ 0.85) → **register or fail**.
- **Shadow test** and **canary** before full rollout (file 4).
- **Champion/challenger**: keep the current model, compare a new one on live traffic or recent data.
- **Reproducibility**: pin **container image digests**, library versions, random seeds; store **hyperparameters and data versions** in MLflow.

## I. Troubleshooting (symptom → cause → fix)
- **Pipeline step fails with AccessDenied** → pipeline execution role lacks S3/ECR/KMS or `iam:PassRole` for the job role → fix roles.
- **Step re-runs despite no changes** → caching off, cache expired, or arguments changed (for example timestamps in parameters) → enable caching and stable arguments.
- **Condition step always false** → metric path wrong in `JsonGet` / property file → verify the evaluation JSON and path.
- **Model never deploys after approval** → EventBridge rule/pattern wrong or deploy pipeline role missing → check the event pattern (`SageMaker Model Package State Change`).
- **Monitoring schedule fails** → data capture not enabled/disk full/baseline missing/VPC endpoints missing → fix capture and endpoints.
- **Drift alarms constant** → baseline unrepresentative or noisy thresholds → rebuild baseline, tune thresholds, slice by segment.
- **Cross-account deploy fails** → model package/ECR/S3/KMS not shared → add resource policies and key policy.

## J. Scenarios: "If X → Y, because Z"
- If a model must be retrained weekly with checks before release → **SageMaker Pipelines (process → train → evaluate → condition → register)**, because it automates and records each step.
- If a new model version must be approved before production → **Model Registry `PendingManualApproval` → Approved → EventBridge → deploy pipeline**, because approval events trigger CI/CD.
- If unchanged steps keep re-running → **enable step caching**, because identical steps reuse prior outputs.
- If the data/ML workflow mixes Glue, EMR, Lambda and human approval → **Step Functions** (with SageMaker tasks), because it orchestrates many services with rich error handling.
- If a new project needs drift monitoring → **Evidently + MLflow monitoring solution with EventBridge/Lambda, SNS and QuickSight (or CloudWatch)**, because Model Monitor is closed to new customers.
- If delayed ground truth arrives days later → **join by inference ID and compute quality metrics on a schedule**, because labels are not available at prediction time.
- If compliance wants an explanation and fairness report → **SHAP + pandas/sklearn bias metrics logged to MLflow, and Model Cards**, because Clarify is in maintenance.
- If auditors ask "which data trained this endpoint?" → **Lineage Tracking, Pipelines execution, Registry version and MLflow run**, because they link artifacts end to end.
- If teams want a ready-made CI/CD scaffold → **SageMaker Projects template (CodePipeline/CodeBuild/Registry)**, because it provisions the whole flow.
- If monitoring costs creep → **delete unused schedules and right-size processing instances**, because each schedule runs jobs repeatedly.

Verified from AWS docs on 2026-11-01 (Pipelines overview, Projects overview, Model Monitor and availability change pages, Clarify availability change, MLflow page, features page).
Unconfirmed (verify): the full Pipelines step list and current limits; exact Projects template roles and Service Catalog details; Deploy-model step availability; thresholds in AWS sample solutions beyond those quoted; Model Dashboard integrations after Model Monitor closure; OpenLineage support; Config/Security Hub controls for SageMaker.

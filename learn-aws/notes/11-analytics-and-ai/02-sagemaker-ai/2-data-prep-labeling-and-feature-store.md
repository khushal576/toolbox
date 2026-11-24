# Amazon SageMaker AI – 2. Data prep, labeling, Feature Store, lineage and experiments

Short notes. Each point is a fact you can be asked about.

## A. Data for ML: the big picture
- **Data prep** = collect, clean, label, transform, split and **featurize** data before training. In practice it is **most of the ML work** and a core **data-engineering** job.
- **Where data lives**: **S3** (default for training/processing), **EFS**, **FSx for Lustre** (fast training reads), **Redshift/Athena/Glue Catalog** (read through Data Wrangler/Canvas/processing), **Lakehouse/Iceberg**.
- **Pick the tool**:
  - **Big/ETL transforms** → **Glue / EMR / Athena** (see their notes) or **SageMaker Processing** (Spark/scikit/containers).
  - **Visual/no-code prep for ML** → **Data Wrangler in Canvas**.
  - **Labels from humans** → **Ground Truth** (existing customers) / other labeling vendors / **Augmented AI (A2I)** for review.
  - **Reusable features for training and serving** → **Feature Store**.

## B. SageMaker Processing
- **Processing job**: runs a **container** (scikit-learn, Spark, your own) on managed instances against **S3 in → S3 out**, then stops. Used for **preprocessing, feature engineering, evaluation, bias/quality checks**.
- **Built-in processors**: `SKLearnProcessor`, `PySparkProcessor`, `SparkJarProcessor`, `ScriptProcessor`, `FrameworkProcessor`, `ClarifyProcessor`, Model Monitor containers.
- **Input/output**: `ProcessingInput` (S3 → `/opt/ml/processing/input`), `ProcessingOutput` (`/opt/ml/processing/output` → S3). **Instances count and S3 data distribution** (`ShardedByS3Key` vs `FullyReplicated`) control parallelism.
- **Same engine runs** Data Wrangler exports, Clarify jobs, Model Monitor schedules, and **Pipelines Processing steps**.
- **Cost**: instance-seconds while running; use **Spot**? (not for Processing) **(verify)**; right-size instance and instance count.
- **Spark on SageMaker** for large transforms when you do not need a Glue/EMR cluster; **Glue** is cheaper/simpler for pure ETL.

## C. Data Wrangler and Canvas data preparation
- **Data Wrangler** (originally in Studio Classic): import from **S3, Athena, Redshift, Snowflake, Databricks (and more)**, build a **data flow**, apply **300+ built-in transforms**, **analyze** (histograms, target leakage, quick model), generate a **Data Quality and Insights report**, and **export** to S3, **Pipelines**, **Feature Store**, or a Python script.
- **Now integrated into SageMaker Canvas** ("Data Wrangler in Canvas") with a **natural-language interface** for exploring and transforming data (in addition to the visual UI). The Studio Classic version still works for existing users.
- **Use** it for fast, visual prep and **repeatable flows** you export into a Pipeline. For heavy production ETL use **Glue/EMR** and treat Data Wrangler as a design tool.
- **Related**: **AWS Glue DataBrew** (visual data prep for analytics, covered in Glue notes) and **Glue Studio**. Exam skill 3.1.6 lists **DataBrew** and **SageMaker Unified Studio** for data prep.

## D. Labeling: Ground Truth and A2I
- **SageMaker Ground Truth** (**closed to new customers**; existing customers continue): builds **labeled datasets** using **workforces** + ML.
  - **Workforces**: **private** (your employees/contractors), **vendor** (AWS Marketplace labeling companies). (The **Mechanical Turk** public workforce is in **maintenance mode** too: no new customers from 30 July 2026.)
  - **Built-in task types**: image classification, **bounding box**, semantic segmentation, text classification, named entity recognition, video/point-cloud labeling; **custom workflows** with your own UI template (HTML + Lambda pre/post).
  - **Automated data labeling**: a model labels easy items and sends hard ones to humans (can cut labeling cost).
  - **Input/output**: **input manifest** (JSON Lines in S3) → **output manifest** with labels. **Streaming labeling jobs** receive objects continuously (SNS/SQS).
  - **CloudWatch** logs under `/aws/sagemaker/LabelingJobs`.
- **Amazon Augmented AI (A2I)** (**maintenance mode**, closed to new customers from 30 July 2026 per the lifecycle summary; verify): builds **human review loops** for ML predictions (for example low-confidence Textract/Rekognition/custom model outputs). **Human review workflow** (flow definition + worker task template) with **private workforce** or vendor; results to S3.
- **Alternatives for labels**: use **Bedrock/LLMs to pre-label** and humans to verify, third-party tools, or **Label Studio** on AWS **(verify)**.
- **Quality**: use **consolidation** (multiple workers per item), **gold standards**, worker metrics, and review samples.

## E. SageMaker Feature Store
- **Why**: store, share and **reuse features** so **training and serving use the same values** (reduces **training-serving skew**), with **point-in-time** correct history.
- **Concepts**:
  - **Feature group** = a table: **features** (name + type: String, Integral, Fractional), a **record identifier** (unique key) and an **event time** feature (required; used for ordering and point-in-time queries).
  - **Record** = a row for one record ID. Feature groups are **mutable** (schema can evolve; you can add features).
  - Group names are unique per **Region and account**. Do **not** put PII in names/descriptions/tags.
- **Online store**: keeps **only the latest record per ID**; **low-millisecond reads**, high-throughput writes; for **real-time inference**. Storage types: **Standard** and **In-memory** (faster) **(verify)**; optional **TTL** to expire records **(verify)**.
- **Offline store**: **append-only history** in **S3** (Parquet; **Iceberg table format** option), registered in the **Glue Data Catalog**; queried with **Athena**; used for **training and batch inference**, **time travel**.
- **Both** online + offline is common: serve fresh values online, train from offline history.
- **Ingestion**:
  - **Streaming**: `PutRecord` (synchronous, small batches) and `PutRecord` from **Kinesis/MSK/Lambda** consumers.
  - **Batch**: **Processing job / Spark / Data Wrangler / Feature Processor SDK**; `ingest()` in the SDK; direct to offline store from Glue/EMR jobs **(verify)**.
  - **Delete**: `DeleteRecord` removes from the online store **and writes a deletion marker to offline** (history remains: handle **right-to-be-forgotten** with extra steps).
- **Querying**: online `GetRecord`/`BatchGetRecord`; offline with **Athena** or the SDK's `create_dataset` (point-in-time join builder).
- **Governance and security**: **KMS** encryption for the online store and the offline S3 location, **IAM**, **cross-account sharing** of feature groups (AWS RAM/Lake Formation) **(verify)**, **tags**, **discoverability** in Studio and Catalog.
- **Resilience**: distributed across **multiple AZs**.
- **Limits** (verify exact): record size, features per group, throughput quotas; online store **provisioned throughput** options.
- **Cost**: **online store** writes/reads/storage (and provisioned capacity if chosen), **offline store** S3 + Glue + Athena queries.
- **Use vs alternatives**: **DynamoDB/ElastiCache** can serve features but lack feature versioning, offline join tooling and catalog; Feature Store is purpose-built. For pure analytics skip it.

## F. Lineage, experiments and metadata
- **ML Lineage Tracking**: records **entities (artifacts, actions, contexts, trial components)** and **associations** for your ML workflow so you can trace **which data, code and model** produced what (exam skill 2.4.4 mentions it). Auto-created for **Pipelines** executions and some jobs; **query with the lineage API**.
- **SageMaker Experiments / MLflow**:
  - **Experiments (SDK)**: track runs, parameters, metrics, artifacts; **Studio Classic** UI; legacy for new work.
  - **Managed MLflow on SageMaker AI** (recommended): **MLflow Apps** (newer, serverless-style, **MLflow 3.x**) and **MLflow Tracking Servers** (**Small/Medium/Large**: sustained TPS **25/50/100**, burst **50/100/200**; teams of about **25/50/100** users; **single AZ**). **Artifact store is S3 in your account**; metadata store is managed by SageMaker. **200 MB download limit**.
  - Features: **experiment tracking, GenAI tracing**, **MLflow Model Registry** with **automatic registration into SageMaker Model Registry**, deploy via `ModelBuilder`, **IAM RBAC** (`sagemaker-mlflow` actions), **CloudTrail** (control-plane events; **data events** `CallMlflowApp` for apps are opt-in), **EventBridge** events (for example model version transitions), **KMS** support.
- **Model Cards**: documentation of intended use, training data, evaluation, risks. **Model Dashboard**: single view of models, endpoints, monitoring status.
- **SageMaker Catalog / Glue Data Catalog / Lake Formation**: the **data lineage** and governance side (see Unified Studio in file 1 and the Lake Formation notes).

## G. Data format and input tips (affect training cost and speed)
- Prefer **Parquet** (columnar, compressed) for tabular training; **RecordIO-protobuf** for some built-in algorithms; **TFRecord/WebDataset** shards for large image/NLP training.
- **Many small files** hurt S3 read speed: **combine/shard**. Use **FastFile** or **Pipe** mode, **FSx for Lustre** for repeated epochs.
- **Split** train/validation/test (and keep **time-based splits** for time series). Prevent **leakage** (features that use future information).
- **Imbalanced classes**: resample, class weights, appropriate metrics (**PR AUC**, F1).
- **Encode** categoricals consistently; **store transformers** with the model (or in Feature Store) so serving matches training.
- **Version datasets** (S3 versioning, manifest files, lakehouse snapshots) and record versions in **MLflow/lineage**.
- **PII**: detect with **Macie/Comprehend**, mask or remove before ML; use **Lake Formation** column/row permissions.

## H. Troubleshooting (symptom → cause → fix)
- **Processing job fails OutOfMemory** → instance too small or skewed data → bigger instance, more instances, Spark tuning.
- **Feature Store offline data missing** → ingestion went to online only, Glue/Athena table not updated, S3 permission, event-time wrong → check group config and role.
- **Online `GetRecord` returns old data** → newer record has an **older event time** (ignored) → fix event-time handling.
- **Training slow reading data** → many small S3 files / File mode → shard files, FastFile/Pipe, FSx.
- **Data Wrangler flow will not run in a VPC** → missing endpoints/subnets → add S3/Athena/Redshift endpoints.
- **Ground Truth job stuck** → workers not assigned, manifest wrong → check workforce, task time, manifest format.
- **MLflow cannot connect** → IAM `sagemaker-mlflow` permissions or network path (VPC) missing → fix role/endpoint.

## I. Scenarios: "If X → Y, because Z"
- If features must be identical in training and online serving → **Feature Store (online + offline)**, because one definition feeds both and reduces skew.
- If a model needs the feature values as they were at prediction time last month → **offline store with point-in-time query (Athena)**, because it is append-only history keyed by event time.
- If real-time inference needs a customer profile in a few milliseconds → **online store** (or DynamoDB), because online store returns the latest record fast.
- If analysts want visual data cleaning that becomes a pipeline step → **Data Wrangler in Canvas → export to Pipelines**, because flows are exportable and repeatable.
- If you need a labeled image set with your own staff → **Ground Truth with a private workforce (existing customer)** or another labeling tool, because Ground Truth is closed to new customers.
- If low-confidence document extractions need human check → **Augmented AI review loop**, because it routes uncertain predictions to reviewers.
- If a nightly feature transform is large → **Glue/EMR job writing to Feature Store offline store/S3**, because heavy ETL is cheaper there.
- If auditors ask "what data trained this model?" → **Lineage Tracking + MLflow + Pipelines execution records**, because they link datasets, code and model versions.
- If experiment tracking must scale for a team → **managed MLflow (pick tracking server size or MLflow App)**, because it is managed and integrates with the Model Registry.
- If training is I/O bound → **FSx for Lustre or FastFile mode and sharded Parquet/TFRecord**, because it removes S3 small-file and download overhead.

Verified from AWS docs on 2026-11-01 (Feature Store overview, Data Wrangler page, Ground Truth page, MLflow page, model training page, whatis-features).
Unconfirmed (verify): Feature Store limits, TTL and in-memory tier details, cross-account sharing mechanics; Ground Truth public workforce availability; Spark/Processing Spot support; Data Wrangler in Canvas details; MLflow App pricing; A2I details; exact Processing container paths (standard but not re-checked).

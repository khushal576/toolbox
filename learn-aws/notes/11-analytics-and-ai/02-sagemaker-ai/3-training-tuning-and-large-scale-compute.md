# Amazon SageMaker AI – 3. Training, tuning, AutoML, fine-tuning and large-scale compute

Short notes. Each point is a fact you can be asked about.

## A. Training jobs: how they work
- A **training job** = **containerized** ML code run on **managed EC2 instances** you pick. SageMaker **provisions, runs, then terminates** the instances. You pay **per second** of billable time.
- **Flow**: data in **S3** (or EFS/FSx) → job downloads/streams it into the container → your script trains → **model artifact** (`model.tar.gz`) written to **S3 output path** → instances shut down.
- **Container paths**: input channels at `/opt/ml/input/data/<channel>`, model output to `/opt/ml/model`, hyperparameters at `/opt/ml/input/config/hyperparameters.json`, checkpoints at `/opt/ml/checkpoints`.
- **Ways to define the algorithm** (more control = more work):
  1. **Low/no-code**: **Canvas, Autopilot (AutoML API), JumpStart** fine-tuning.
  2. **Built-in algorithms** (managed containers).
  3. **Framework estimators / script mode**: PyTorch, TensorFlow, Hugging Face, scikit-learn, XGBoost, MXNet containers; you supply a **training script**.
  4. **Bring your own container (BYOC)**: Docker image in **ECR** with the `sagemaker-training-toolkit`.
  5. **`@remote` decorator**: run local Python functions as jobs.
- **SDK**: high-level **SageMaker Python SDK** (Estimators, `ModelTrainer`) or low-level **Boto3 `create_training_job`** / AWS CLI.
- **Execution role** must allow S3 access, ECR pull (for BYOC), CloudWatch Logs; the **caller needs `iam:PassRole`**.
- **Logs and metrics**: **CloudWatch Logs** (`/aws/sagemaker/TrainingJobs`), **metric definitions (regex)** to publish custom training metrics, instance metrics (CPU/GPU/memory/disk).
- **Statuses**: InProgress, Completed, Failed, Stopping, Stopped. **Max runtime** (`StoppingCondition.MaxRuntimeInSeconds`; default 1 day; up to 28 days) **(verify)**.
- **Training-job cost** = instance price × billable seconds (incl. data download time and startup), **per instance**.

## B. Input data modes
- **File mode** (default): downloads the **entire dataset** to the instance's **EBS volume** before training starts. Simple; slow start for large data; needs disk space.
- **FastFile mode**: **streams** from S3 on demand but shows files as a **local filesystem**; fast start, good for **random access** and large datasets; best default for many frameworks.
- **Pipe mode**: **streams** data through a Unix **named pipe** (sequential), lowest disk use, fast for streaming-friendly formats; supports **augmented manifest files**.
- **S3 data distribution**: `FullyReplicated` (all instances get all data) vs `ShardedByS3Key` (split objects across instances).
- **Other sources**: **Amazon EFS** and **FSx for Lustre** (high throughput, great for repeated epochs; needs **VPC**).
- **Managed warm pools** + **persistent cache** reduce startup/download time for iterative runs.

## C. Built-in algorithms (names and uses; exam-style)
- **Supervised tabular**: **XGBoost** (classification/regression), **Linear Learner**, **Factorization Machines** (sparse data, recommendations), **K-Nearest Neighbors**, **AutoGluon-Tabular**, **LightGBM**, **CatBoost**, **TabTransformer**.
- **Unsupervised**: **K-Means** (clustering), **PCA** (dimensionality reduction), **Random Cut Forest** (anomaly detection), **IP Insights** (anomalous IP usage), **LDA/NTM** (topic modeling).
- **Text/NLP**: **BlazingText** (word2vec, text classification), **Object2Vec**, **Sequence-to-Sequence**.
- **Time series**: **DeepAR** (probabilistic forecasting; note: the managed **Forecast** service status: verify).
- **Vision**: **Image Classification**, **Object Detection**, **Semantic Segmentation**.
- **Input formats**: many accept **CSV** and **RecordIO-protobuf**; **Pipe mode** usually needs RecordIO-protobuf for best performance. XGBoost supports CSV, LibSVM, Parquet, and more.
- **Quick picks**: tabular classification → **XGBoost**; anomalies in streaming metrics → **Random Cut Forest**; segmentation of customers → **K-Means**; recommendation with sparse features → **Factorization Machines**; text categories → **BlazingText**.

## D. Cost and resilience for training
- **Managed Spot Training**: use **Spot instances** for up to about **90% savings**. **Requires checkpointing** (to S3 `CheckpointConfig`) so a replaced instance **resumes**. Set **`MaxWaitTimeInSeconds` ≥ `MaxRuntimeInSeconds`**. Savings shown as billable vs training seconds.
- **Checkpointing**: also protects against unexpected termination and supports **incremental training** (start from a prior model).
- **Warm pools**: keep instances alive after a job for a set time (**`KeepAlivePeriodInSeconds`**) to start the next job faster (billed while warm).
- **Heterogeneous clusters**: combine CPU and GPU instance groups in one job.
- **Instance choice**: start with the smallest suitable (CPU C5 for tabular; GPU G5 for deep learning). Use **Debugger, CloudWatch GPU metrics or framework profilers** to see utilization and downsize.
- **Savings Plans**: SageMaker Savings Plans cover training, endpoints, notebooks, processing for a committed **$/hour** (1 or 3 years).
- **Training Compiler**: compiles model graphs to speed GPU training (framework support limited) **(verify current status)**.
- **Automatic stop**: set max runtime; **early stopping** in tuning jobs.

## E. Distributed training
- **When**: data too big for one instance (**data parallel**) or model too big for one GPU (**model parallel**).
- **SageMaker distributed libraries**:
  - **Data parallelism library (SMDDP)**: optimized AllReduce for AWS network; plugs into PyTorch DDP / TensorFlow.
  - **Model parallelism library (SMP)**: **pipeline/tensor/sharded data parallelism** and **activation checkpointing/offloading** for large models (FSDP-style).
- **Or** use open frameworks: **PyTorch DDP/FSDP, DeepSpeed, Megatron-LM, NeMo, Horovod**, and **Hugging Face Accelerate** in your container.
- **Networking**: use instances with **EFA** (p4d/p5, trn1) for fast GPU-to-GPU traffic; cluster in a **single AZ** (placement).
- **Cost control**: avoid under-utilized GPUs (profile), choose communication-efficient settings, checkpoint often.

## F. Hyperparameter tuning (Automatic Model Tuning, AMT)
- **What**: runs **many training jobs** with different hyperparameters to **optimize an objective metric** (for example validation AUC).
- **Search strategies**: **Bayesian** (default; learns from past trials), **Random**, **Grid**, **Hyperband** (early-stops poorly performing jobs; saves cost on deep learning) **(verify availability by algorithm)**.
- **Define**: hyperparameter **ranges** (Continuous, Integer, Categorical), **objective metric** (and type Maximize/Minimize, from built-in metrics or **regex on logs**), **resource limits** (`MaxNumberOfTrainingJobs`, **`MaxParallelTrainingJobs`**).
- **Trade-off**: **more parallel jobs = faster but less learning between trials** (Bayesian works best with low parallelism).
- **Warm start**: reuse results of previous tuning jobs (**IDENTICAL_DATA_AND_ALGORITHM** or **TRANSFER_LEARNING**).
- **Early stopping**: `Auto` stops jobs unlikely to beat the best.
- **Combine with Spot** to cut tuning cost.
- **Tuning is a Pipelines step** (**Tuning step**).

## G. AutoML: Autopilot and Canvas
- **Autopilot** automates **data analysis, preprocessing, model selection, hyperparameter optimization, training, evaluation and deployment**, for datasets up to **hundreds of GB**.
  - **AutoML API v2 (`CreateAutoMLJobV2`)** supports **tabular (regression, binary, multiclass)**, **text classification**, **image classification**, **time-series forecasting**, and **fine-tuning LLMs for text generation**.
  - **Modes** (tabular): **AUTO**, **ENSEMBLING**, **HYPERPARAMETER_OPTIMIZATION** **(verify names)**.
  - Produces **explainability** (feature importance) and **performance reports**, plus **candidate-definition and data-exploration notebooks** (for tabular) so you can learn and modify.
  - **UI moved to Canvas**; Studio Classic keeps the old UI; code users use the **API**.
- **Canvas**: no-code builds the same kinds of models (**quick build vs standard build**), time-series forecasting, image/text classification.
- **Use** AutoML for **baselines** and when you lack ML expertise; use custom training for **fine control**.

## H. Foundation model fine-tuning on SageMaker
- **JumpStart fine-tuning**: choose a model (Llama, Mistral, Falcon, etc.), point to **S3 training data**, set hyperparameters (**instruction fine-tuning or domain adaptation**), optionally **LoRA/PEFT**; produces a model you **deploy to an endpoint**.
- **SageMaker training jobs for FM customization** and **HyperPod recipes** (NVIDIA NeMo and Neuronx Distributed Training based) for **pre-training/fine-tuning at scale**, runnable on **HyperPod or training jobs**.
- **Bedrock customization** is the managed alternative for **supported** models (see Bedrock notes); **Custom Model Import** brings SageMaker-trained open models into Bedrock.
- **Cost**: GPU hours dominate; use **LoRA/QLoRA**, smaller models, **Spot**, **training plans**.
- **Data**: JSONL instruction pairs in S3 (instruction/response or chat format); keep **eval sets** separate.
- **Reinforcement learning** (RLHF/DPO style) is possible with your own code on large instances **(verify first-party recipes)**.

## I. HyperPod and training plans (large-scale / FM work)
- **SageMaker HyperPod**: **resilient, persistent clusters** for large model training. **Automatic health checks, fault detection and node replacement**, **auto-resume** from checkpoints. Thousands of **GPUs (A100/H100/Blackwell) or Trainium**.
- **Orchestration**: **Slurm** (login/head/worker nodes, lifecycle scripts, direct SSH) or **Amazon EKS** (HyperPod cluster attached 1:1 to an EKS control plane; Kubeflow PyTorch jobs with **job auto-resume**).
- **UltraServers**: **NVL72** (18 instances, 72 Blackwell GPUs via NVLink) for trillion-parameter models; topology-aware scheduling.
- **Extras**: **HyperPod recipes**, **task governance** (quotas/priorities across teams on EKS clusters), **observability**, **Ray on HyperPod**, **model deployment (inference) on HyperPod**, **customer-managed KMS** for cluster volumes, **HyperPod in Studio**.
- **Regions**: about 18 Regions (US, EU, APAC, SA) per docs.
- **Training plans**: **compute reservations** for large training (jobs or HyperPod). Specify **timeline, duration and max compute**; SageMaker sets up infrastructure, runs the workload and handles fault recovery with a **predictable cost**.
- **Use HyperPod** for long, multi-node FM training where failures are likely; use **training jobs** for shorter, ephemeral runs.

## J. Trainium and Neuron
- **AWS Trainium (trn1, trn2)** chips for **cost-efficient training**; **Inferentia (inf1, inf2)** for inference. Both use the **AWS Neuron SDK** (PyTorch/JAX via `torch-neuronx`/NxD).
- Typical savings vs comparable GPUs (**AWS claims; verify**) but need **Neuron-compatible** code and compilation steps.
- **Use** when the model/framework is supported and cost matters at scale; stay on NVIDIA GPUs for broad compatibility.

## K. Debugger and training observability
- **SageMaker Debugger** (**maintenance mode**, closed to new customers from 30 July 2026; verify): collects **tensors/system metrics** during training; **built-in rules** detect **vanishing/exploding gradients, overfitting, loss not decreasing, low GPU utilization, dead ReLU**, etc.; can **stop a job**/send alerts via CloudWatch events.
- **Experiments/MLflow** track runs (file 2). **CloudWatch** shows metrics and logs.
- **Training-job events** go to **EventBridge** (status changes) to trigger pipelines or alerts.

## L. Troubleshooting (symptom → cause → fix)
- **`ResourceLimitExceeded`** → instance-type quota for training is 0 or too low → request quota, change instance type/Region.
- **`CapacityError`/InsufficientCapacity** → no instances available → retry, other instance type/AZ, training plan, warm pool.
- **Job fails during download** → wrong S3 path/permissions/VPC endpoint missing → check role, S3 endpoint, bucket policy, KMS.
- **OOM** → batch size/instance memory → reduce batch size, bigger instance, gradient accumulation, model parallelism.
- **Spot job stuck waiting** → Spot capacity low → raise wait time, flexible instance type, checkpoint to resume.
- **Slow training, low GPU utilization** → data loader/IO bottleneck → FastFile/Pipe, FSx, more workers, profile.
- **Metric not appearing in tuning** → regex does not match logs → fix `MetricDefinitions`.
- **Model artifact empty/wrong** → script did not save to `/opt/ml/model` → save outputs correctly.
- **`AlgorithmError`** → bad data format or hyperparameter → read CloudWatch log and algorithm docs.
- **Costs keep running** → warm pools, HyperPod cluster, notebook apps left on → stop/delete.

## M. Scenarios: "If X → Y, because Z"
- If training can be interrupted and cost matters → **managed Spot + checkpointing (and `MaxWaitTime` ≥ `MaxRuntime`)**, because Spot can save up to about 90% and resumes from checkpoints.
- If the dataset is hundreds of GB and training needs fast start → **FastFile or Pipe mode (or FSx for Lustre)**, because File mode downloads everything first.
- If repeated experiments waste time on startup → **managed warm pools**, because instances stay ready for the next job (billed while warm).
- If the best hyperparameters are unknown → **Automatic Model Tuning (Bayesian, with Hyperband/early stopping)**, because it searches and stops weak trials.
- If tuning is slow and you raised parallelism → **lower parallel jobs for better Bayesian learning**, because parallel trials do not inform each other.
- If a model does not fit in one GPU → **model parallelism (SMP/FSDP/DeepSpeed) or HyperPod**, because the weights must be sharded.
- If multi-week FM training must survive hardware failures → **HyperPod with auto-resume (and a training plan)**, because it replaces faulty nodes and resumes from checkpoints.
- If analysts want a model quickly with no code → **Canvas / Autopilot**, because they automate preprocessing, algorithm choice and tuning.
- If you need a GenAI model tuned on your instructions with a managed flow → **JumpStart fine-tuning (LoRA) or Bedrock customization for supported models**, because both wrap training and storage.
- If you need to detect anomalies in a metric stream → **Random Cut Forest**, because it scores unusual points without labels.
- If GPU utilization is 20% → **profile with Debugger or the framework profiler (PyTorch Profiler, Nsight)**, then fix data loading or downsize, because idle GPUs waste the most money.

Verified from AWS docs on 2026-11-01 (SageMaker model training page, HyperPod page, Autopilot page, whatis-features, MLflow page). The built-in algorithm list, container paths, Spot rules and tuning options are standard SageMaker behavior from earlier knowledge and were not re-fetched.
Unconfirmed (verify): max training runtime defaults; Hyperband availability by algorithm; Training Compiler status; Trainium savings claims; AutoML mode names; RL/RLHF recipes; Forecast service status; list of JumpStart models; heterogeneous cluster and warm-pool limits.

# Amazon SageMaker AI – 4. Deployment and inference options

Short notes. Each point is a fact you can be asked about.

## A. How hosting works
- **Three building blocks**: **Model** (container image + model artifact in S3 + execution role) → **Endpoint configuration** (instance types/counts, **production variants**, data capture, async/serverless config) → **Endpoint** (the running, invokable resource).
- **Invoke** with `InvokeEndpoint` (runtime API, **SigV4**), `InvokeEndpointWithResponseStream` (streaming), `InvokeEndpointAsync`. Some endpoints also expose **OpenAI-compatible APIs** **(verify)**.
- **Container contract**: container listens on **port 8080** with **`/ping`** (health, must return 200) and **`/invocations`** (inference).
- **Ways to deploy**: **JumpStart** (UI, pretrained/FMs), **`ModelBuilder` (SageMaker Python SDK)** for your own model, **Boto3/IaC (CloudFormation/CDK/Terraform)** at scale, **Pipelines** model step, **Model Registry** approval-triggered deploy.
- **Endpoint updates are blue/green by default** (new fleet created, traffic shifted, old fleet removed) so there is **no downtime**.

## B. The inference options (very testable)
| Option | Latency | Payload | Processing time | Scale to zero | Best for |
|---|---|---|---|---|---|
| **Real-time** endpoint | Low (ms–s) | Up to **25 MB** request **(verify)** | **60 s** response timeout **(verify)**; **streaming** longer | No (min 1 instance) | Interactive, steady traffic |
| **Serverless** | Cold start possible | Up to **4 MB** **(verify)** | **60 s** **(verify)** | **Yes** | Spiky/intermittent, tolerates cold start |
| **Asynchronous** | Near real time (queued) | Up to **1 GB** | Up to **1 hour** | **Yes** (scale to 0 instances) | Large inputs, long jobs (video, documents) |
| **Batch Transform** | Offline | Per mini-batch up to **100 MB** | Job-based | N/A (job ends) | Score whole datasets, no persistent endpoint |
- **Rule**: **steady + low latency** → real-time. **Unpredictable + small models** → serverless. **Big payload / long runtime / queue is fine** → async. **No endpoint needed, whole dataset** → batch transform.

## C. Real-time endpoints
- **Instances**: choose CPU/GPU/**Inferentia** types; **multiple instances across AZs** for availability (**at least 2** recommended for production).
- **Production variants**: several **model variants** behind one endpoint with **traffic weights** (**A/B testing**, **canary**). Each variant has its own instance type/count and **scaling**.
- **Invoke a specific variant** with `TargetVariant` (testing).
- **Auto scaling** (Application Auto Scaling): **target tracking** on **`SageMakerVariantInvocationsPerInstance`** (invocations per instance per minute), plus **scheduled** and **step** scaling; set **cooldowns**. **Scale-in** is **slower** than scale-out by design. Min/max capacity; custom metrics (for example **latency, queue depth, GPU use**).
- **Hosting options**:
  - **Multi-model endpoints (MME)**: host **thousands of models** on one fleet; models **loaded on demand from S3** into memory (cold load on first call; **LRU eviction**). **Cost-efficient** when many models have **similar framework/size and sparse traffic**. Metrics: `ModelCacheHit`, `LoadedModelCount`, `ModelLoadingWaitTime`.
  - **Multi-container endpoints (MCE)**: up to **15** containers on one endpoint, either **direct invocation** (pick container per request) or **serial inference pipelines**.
  - **Inference pipelines (serial)**: chain **2–15 containers** (for example preprocessing → model → postprocessing); **VPC and data capture** supported **(verify)**.
  - **Inference components**: deploy **one or more models as components on a shared endpoint** with **per-component compute allocation (CPU/GPU/memory)** and **component-level scaling and scale-to-zero**; used for **many foundation models** on shared GPU instances, **adapter (LoRA) inference components**, and **GPU partitioning**.
  - **Instance pools / heterogeneous** deployment across instance types.
  - **Large Model Inference (LMI) containers** (vLLM/DJL/TensorRT-LLM), **TGI**, **TorchServe**, **NVIDIA Triton**.
- **Response streaming** for LLM tokens; **data capture** (log requests/responses to S3 for monitoring/replay).
- **Endpoint security**: **VPC** config, **network isolation**, **KMS** for volume/model, IAM `sagemaker:InvokeEndpoint`; **resource policies**; **PrivateLink** (`sagemaker.runtime`).
- **Real-time cost**: **instance-hours** for all instances (even with no traffic) + data transfer + storage. **Delete endpoints** you do not use.

## D. Serverless inference
- **Pay per use** (compute duration by ms and data processed); **scales to 0**. **Memory 1,024–6,144 MB** (1/2/3/4/5/6 GB), compute scales with memory; **max container image 10 GB**; **5 GB ephemeral disk**.
- **Concurrency**: max **200 per endpoint**; account total **1,000** (many Regions) or **500** (some Regions) across serverless endpoints; **up to 50 serverless endpoints per Region**. Excess is **throttled**.
- **Provisioned concurrency**: keep a set number of workers **warm** (milliseconds response) for predictable bursts; **must be ≤ max concurrency**; can be **auto scaled** (target metric or schedule; **not supported in CloudFormation**).
- **Cold starts** depend on model size/download/container start; metric **`OverheadLatency`** measures it.
- **Not supported**: **GPUs**, Marketplace packages, private registries, **multi-model endpoints**, **VPC config**, network isolation, **data capture**, **multiple production variants**, **Model Monitor**, **inference pipelines**. **Cannot convert real-time → serverless**; serverless → real-time is possible (one way).
- **Use** for small models and unpredictable traffic; **avoid** for latency-critical, GPU, or VPC-only needs.

## E. Asynchronous inference
- Requests are **queued**. Client **uploads input to S3**, calls **`InvokeEndpointAsync`** with the S3 URI, gets an **inference ID and output location**; result lands in **S3**. Optional **SNS success/error notifications**.
- **Up to 1 GB payload, up to 1 hour** processing, **autoscale to zero** (scale on **`ApproximateBacklogSizePerInstance`**), configure **max concurrent invocations per instance**.
- Endpoint with `AsyncInferenceConfig` accepts **only async invocations**.
- Not compatible with some features (see the deployment guardrails exclusions list).
- **Use** for **computer vision on large images/videos**, document processing, long LLM jobs; **cheap when idle** because instances scale to 0.

## F. Batch Transform
- Runs inference on a **dataset in S3** with a **transform job**; creates instances, processes, writes **`<input>.out`** files to the **S3 output path**, then stops.
- **Parameters**: **`MaxPayloadInMB`** (≤ **100 MB**; `MaxConcurrentTransforms × MaxPayloadInMB` must also be ≤ 100 MB), **`MaxConcurrentTransforms`** (ideally = workers per instance), **`BatchStrategy`** (`SingleRecord` or `MultiRecord`), **`SplitType`** (`Line` to split a file into mini-batches; `None` sends the whole file), **`AssembleWith`** (`Line` to join output records).
- **Parallelism**: SageMaker maps **S3 objects to instances**. **One big file + many instances = only one instance works.** **Split data into multiple files** to use all instances.
- **Input/output association**: **`InputFilter`, `JoinSource`, `OutputFilter`** (JSONPath) to **join predictions to input records** or filter columns.
- **Output order** matches input order. CSV with **embedded newlines** not supported with `SplitType=Line`.
- **Use** for **nightly scoring**, **preprocessing** with a model, **testing variants** on validation data. **No persistent endpoint cost.**
- **Monitoring**: Model Monitor (existing customers) can monitor transform jobs; capture inputs/outputs.

## G. Safe deployment and testing
- **Deployment guardrails** (for real-time endpoints): **blue/green** with **all-at-once**, **canary**, or **linear** traffic shifting; **auto-rollback on CloudWatch alarms**; **baking period**.
- **Shadow tests (shadow variants)**: send a **copy of live traffic** to a new variant/infrastructure and **compare** latency, errors, and predictions without affecting users. Then promote.
- **A/B testing** with variant weights; **canary** with a small weight.
- **Rollback**: re-point to the previous endpoint config.
- **Inference Recommender**: **load tests** your model across instance types (**default** recommendations or **advanced** job with your traffic pattern) to find the best **instance type/count and container params** for cost/latency.
- **Model validation in production**: compare variants, use **Model Registry** approvals, **data capture** for drift analysis.

## H. Optimization and hardware
- **SageMaker Neo**: **compiles/optimizes** models for target hardware (CPU/GPU/**Inferentia**/edge) for faster, smaller models.
- **Inferentia (inf1/inf2)** via Neuron: lower cost per inference for supported models.
- **GPU endpoints**: G5/G6 for general GPU, P4/P5 for the biggest FMs; **GPU partitioning** (MIG) for inference components to share a GPU.
- **Quantization/compilation** (**AWQ, GPTQ, FP8, speculative decoding**) through **LMI/inference optimization toolkit** **(verify)**.
- **Autoscaling for LLMs**: scale on **concurrent requests/tokens** metrics rather than only invocations per instance.
- **Caching/batching** inside containers (continuous batching in vLLM/TGI/TensorRT-LLM).

## I. Model Registry and approvals
- **Model Registry**: **model groups** (collections of versions), **model package versions** with metadata, **approval status** (`PendingManualApproval`, `Approved`, `Rejected`), lineage, **Model Cards**, **cross-account** sharing, **Collections**. **Approval status change emits an EventBridge event** to trigger deployment pipelines (CI/CD).
- Register from **Pipelines** (`RegisterModel`/`ModelStep`), from **MLflow** (auto-register), or manually.
- **Deploy from the registry** (UI/SDK), **across accounts** with resource policies and cross-account ECR/S3 access.

## J. Monitoring endpoints (CloudWatch namespace `AWS/SageMaker`)
- **Invocation metrics**: `Invocations`, `InvocationsPerInstance`, `Invocation4XXErrors`, `Invocation5XXErrors`, **`ModelLatency`** (inside the container), **`OverheadLatency`** (SageMaker overhead, includes serverless cold start), `InvocationModelErrors`.
- **Instance metrics** (`/aws/sagemaker/Endpoints`): `CPUUtilization`, `MemoryUtilization`, `GPUUtilization`, `GPUMemoryUtilization`, `DiskUtilization`.
- **Enhanced metrics** per container/instance (and for inference components).
- **Async**: `ApproximateBacklogSize`, `ApproximateBacklogSizePerInstance`, `ApproximateAgeOfOldestRequest`, `RequestsNotProcessed`, `InvocationsProcessed`.
- **Alarms**: 5XX rate, latency p95/p99, backlog age, GPU memory; **rollback alarms** for deployment guardrails.
- **Logs**: CloudWatch Logs `/aws/sagemaker/Endpoints/<name>`; **CloudTrail** for control-plane calls.
- **Data capture + Model Monitor / open-source monitors** for data and model drift (file 5).

## K. Cost for inference
- **Real-time**: instance-hours per instance (all variants). **Biggest levers**: **right-size** (Inference Recommender), **autoscale**, **Savings Plans**, **MME/inference components** to share hardware, **Inferentia**, **delete idle endpoints**, shut down dev endpoints nightly.
- **Serverless**: per **ms of compute × memory** and data processed; provisioned concurrency adds a charge per provisioned-concurrency hour.
- **Async**: instance-hours **only while instances run** (scale to 0 when empty) + S3.
- **Batch transform**: instance-hours for the job duration.
- **Other**: data capture to S3, CloudWatch logs, data transfer, ECR storage.

## L. Troubleshooting (symptom → cause → fix)
- **Endpoint stuck `Creating`/fails** → container failed `/ping` within the **health-check timeout**, model download failed, wrong role/S3/KMS → read CloudWatch logs.
- **`ModelError` (424)** → exception inside the container → check container logs, input format.
- **413 / payload too large** → request over the limit (real-time 25 MB? serverless 4 MB) → use **async** or S3 pointers.
- **504 / timeout** → inference over 60 s on real-time → streaming, **async**, optimize model.
- **429/throttling on serverless** → concurrency limit → raise max concurrency or provisioned concurrency.
- **High latency spikes** → cold starts (serverless/MME load), CPU saturation, GPU memory pressure, noisy batching → provisioned concurrency, scaling, bigger instance.
- **Scale-out too slow** → target value too high or long instance start time → lower target, warm capacity, scheduled scaling.
- **MME model not found / slow first call** → artifact missing in S3 prefix or loading cold → verify path, pre-warm.
- **Async results missing** → output S3 permission or error file in `FailurePath`/SNS error topic → check notifications.
- **Bill high** → idle real-time endpoints, oversized GPUs, many variants → delete, right-size, schedule.

## M. Scenarios: "If X → Y, because Z"
- If a fraud model needs responses within 100 ms all day → **real-time endpoint with autoscaling across 2+ AZs**, because it is always warm and scales with traffic.
- If a chatbot model is used a few times per hour → **serverless inference** (CPU model) or a small real-time endpoint, because serverless scales to zero.
- If you must process 500 MB satellite images and results can wait minutes → **asynchronous inference**, because it supports 1 GB payloads and 1 hour jobs.
- If you must score 200 million rows tonight → **Batch Transform with many split files and instances**, because it needs no endpoint and parallelizes by file.
- If you have 5,000 small per-customer models with sparse traffic → **multi-model endpoint**, because models load on demand into shared instances.
- If you must run several foundation models on shared GPUs with independent scaling → **inference components on one endpoint**, because each component gets allocated compute and scales separately.
- If you must test a new model with real traffic but not affect users → **shadow test**, because it mirrors requests and compares behavior.
- If you want to gradually shift traffic with automatic rollback → **deployment guardrails (canary/linear) with CloudWatch alarms**, because they roll back on alarm.
- If you do not know the right instance size → **Inference Recommender**, because it load-tests candidates and recommends by cost/latency.
- If the serverless endpoint needs a GPU or VPC → **use a real-time endpoint**, because serverless does not support them.
- If queue backlog grows on async → **scale on `ApproximateBacklogSizePerInstance`**, because it reflects waiting work per instance.
- If a new model version needs approval before production → **Model Registry approval + EventBridge-triggered pipeline**, because status changes trigger automation.

Verified from AWS docs on 2026-11-01 (inference overview/options, serverless, async, batch transform pages, features page, MLflow/Model Registry pages).
Unconfirmed (verify): real-time payload (25 MB) and timeout (60 s) values and the serverless 4 MB payload; MCE container count (15); LMI/quantization toolkit options; OpenAI-compatible endpoint support; metric names beyond those standard in earlier SageMaker docs; data capture and VPC support for inference pipelines; Inference Recommender job types.

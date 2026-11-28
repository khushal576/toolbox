# AWS Batch – 2. Pipelines, security, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Starting Batch jobs (triggers and orchestration)
- **Direct API / CLI / SDK**: `aws batch submit-job --job-name x --job-queue q --job-definition def:3 --parameters input=s3://... --container-overrides ...`.
- **EventBridge rules → Batch target**:
  - **Scheduled** (cron/rate) jobs: for example a nightly aggregation at 02:00. Prefer **EventBridge Scheduler** with a Batch target for time zones and one-time schedules (verify Scheduler's Batch target support).
  - **Event-driven**: S3 object created (S3 → EventBridge) → submit a job with the object key passed as a parameter (input transformer).
  - EventBridge needs an IAM role allowed to `batch:SubmitJob`.
- **AWS Step Functions** (most common orchestration):
  - **`arn:aws:states:::batch:submitJob.sync`**: Step Functions submits the job and **waits for it to finish** (succeeded/failed), with no polling code.
  - Catch/Retry, branching, parallel states, **Map state** over a list of inputs (or launch one array job instead).
  - Mix Batch with Lambda, Glue, Athena, EMR, SNS steps in one workflow.
  - Without `.sync` (plain `submitJob`) the state finishes as soon as the job is submitted.
- **Amazon MWAA / Airflow**: `BatchOperator` submits and waits. `BatchSensor` watches a job. Good when the team already uses Airflow.
- **Lambda**: calls `SubmitJob` (for example from an S3 event). Keep it small; Lambda only hands off the heavy work to Batch.
- **AWS Batch job dependencies** (`dependsOn`, up to 20; N_TO_N / SEQUENTIAL for arrays) for simple chains without an orchestrator.
- **Nextflow, Snakemake, Cromwell, Metaflow** (scientific/ML workflow engines) have Batch executors (common in genomics).
- **SageMaker Training jobs** can be queued through Batch service environments with priorities and quota shares.

## B. Batch in data pipelines
- **Typical pattern**:
  1. Files land in S3 (raw).
  2. EventBridge/Step Functions submits a Batch job (or an **array job** over the file list/manifest).
  3. Containers read from S3, transform (pandas, polars, DuckDB, custom C++/Java, ML models) and write Parquet to S3 (curated).
  4. A Glue crawler or a direct catalog update registers partitions.
  5. Notify by SNS.
- **Fan-out with array jobs**:
  - Write a manifest (list of keys) to S3. Submit an array job of size N.
  - Each child reads line `AWS_BATCH_JOB_ARRAY_INDEX` of the manifest.
  - A final job (`dependsOn` the array) **fans in**: merges results, validates counts.
- **Chunking**: keep each job big enough to amortize container start (image pull, instance launch). Very tiny jobs waste time and money. Group small files per child.
- **Idempotent outputs**: jobs may be **retried** (Spot interruption, failures). Write to deterministic S3 keys or temp prefixes, then commit/rename. Avoid duplicate rows on retry.
- **Checkpointing** long jobs (save progress to S3/DynamoDB) so a retried Spot job resumes instead of restarting from zero.
- **Data access**:
  - S3 through the SDK (fastest: parallel GETs, Mountpoint for S3 for read-mostly file access).
  - **EFS** for shared POSIX files. **FSx for Lustre** (linked to S3) for HPC/ML high throughput.
  - Instance store/EBS for scratch space (set a launch template for big volumes).
- **Databases**: jobs in a VPC reach RDS/Redshift with security group rules. Credentials come from Secrets Manager. Use RDS Proxy or connection limits when many jobs run at once (or limit with **consumable resources** / queue size).
- **Batch vs Glue for ETL in exam answers**:
  - "Containerized custom code, GPUs, any language, Spot, long-running, many independent tasks" → **Batch**.
  - "Spark, catalog, crawlers, bookmarks, data quality, least ops for data lake ETL" → **Glue**.
- **Batch vs ECS RunTask in Step Functions**: Batch adds queuing, retries, Spot management and array jobs. Plain ECS tasks are fine for a few single containers.

## C. Performance and scaling
- **Startup time** has two parts:
  - **Instance launch** (EC2 CE scaling from 0 takes minutes).
  - **Image pull** (big images take longer and show in **STARTING**).
- To start faster:
  - Keep `minvCpus` > 0 at busy times.
  - Use smaller images and cached layers (ECR in the same Region; pull-through cache).
  - Use Fargate for small jobs.
  - Pre-bake large dependencies into a custom AMI (EC2).
- **Bin-packing**: Batch places several jobs on one EC2 instance if vCPU/memory fit. Right-size job requests so more jobs fit per instance.
- **Instance choice**:
  - Include many families and sizes (or `optimal`) so the allocation strategy has choices.
  - Use C for CPU-bound, R for memory-bound, G/P for GPU, `d` types for fast local disk, Graviton (arm64 images) for price/performance.
- **Allocation strategy**: `BEST_FIT_PROGRESSIVE` (On-Demand) or `SPOT_PRICE_CAPACITY_OPTIMIZED` (Spot) scale better than `BEST_FIT`, which can wait for one exact type.
- **Throughput limits**:
  - 50 SubmitJob TPS per account. Use array jobs for big fan-outs.
  - Max 1,000,000 jobs in SUBMITTED.
  - **EC2 vCPU quotas** (On-Demand and Spot per family) can stop scaling even below `maxvCpus`. Request increases.
- **ECS/EKS limits**: ENIs per instance in awsvpc mode (Fargate/EKS), IP addresses in subnets (each Fargate job uses one ENI and IP). **Use large subnets**.
- **Multi-node parallel**: cluster placement group + EFA for low latency.
- **GPU jobs**: use the ECS GPU-optimized AMI (default for GPU types). Request `GPU` in `resourceRequirements` so Batch assigns devices.
- **Shared memory** (`/dev/shm`) for PyTorch data loaders: set `sharedMemorySize` in `linuxParameters` (EC2).

## D. Security
- **IAM roles in Batch** (know which does what):
  - **Batch service role** (`AWSServiceRoleForBatch` service-linked role, or a custom service role): lets Batch manage EC2, ECS, Auto Scaling and Spot for you.
  - **ECS instance role** (instance profile on EC2 hosts, `AmazonEC2ContainerServiceforEC2Role`): the ECS agent on the host registers, pulls ECR images and writes logs (EC2 CEs).
  - **Execution role** (`AmazonECSTaskExecutionRolePolicy`): pulls images and **fetches secrets** for the container, and writes logs. **Required for Fargate**. Used for secrets on EC2 too.
  - **Job role** (task role, `jobRoleArn`): what **your code** can do (read S3, write DynamoDB, call Glue). **Least privilege per job definition**. This is the role your exam answers should give data access to.
  - **Spot Fleet role** (for BEST_FIT Spot CEs).
  - **EventBridge / Step Functions role** allowed to call `batch:SubmitJob` (plus `DescribeJobs`/`TerminateJob` for `.sync`).
- **Who can submit jobs**:
  - IAM on `batch:SubmitJob` with resource-level permissions on job queues and job definitions.
  - Conditions like `batch:Image`, `batch:Privileged`, `batch:User`, `batch:AWSLogsGroup` (verify names) to block privileged/root containers or unapproved images.
  - Tag-based ABAC per team.
- **Network**:
  - Run CEs in **private subnets**.
  - Allow outbound via **NAT** or **VPC endpoints**: ECR (`ecr.api`, `ecr.dkr`), S3 gateway (image layers live in S3), ECS (`ecs`, `ecs-agent`, `ecs-telemetry`), CloudWatch Logs, Secrets Manager, STS.
  - Security groups only allow what jobs need (DB ports).
- **Secrets**: `secrets` in the job definition reference **Secrets Manager** or **SSM Parameter Store**. They are injected as env vars at start (the execution role needs `secretsmanager:GetSecretValue`, `ssm:GetParameters`, `kms:Decrypt`). Never put secrets in `environment`, `command` or the image.
- **Encryption**:
  - EBS volumes on CE instances: encryption by default or via a launch template with a KMS key.
  - Fargate ephemeral storage is encrypted (AES-256; CMK option; verify).
  - Data in S3 uses SSE-KMS (the job role needs KMS permissions). Use TLS in transit.
- **Container security**:
  - **ECR image scanning** (basic / enhanced with Inspector), immutable tags or digests in job definitions.
  - Run as non-root (`user`), `readonlyRootFilesystem`, avoid `privileged`.
- **IMDS**: use IMDSv2 on CE instances (launch template). Block containers from reaching the instance role through IMDS (hop limit 1, or ECS settings) so jobs only use their **job role**.
- **Audit**: **CloudTrail** records Batch API calls (SubmitJob, CreateComputeEnvironment, UpdateJobQueue…), plus EC2/ECS calls made by the Batch service role.

## E. Cost
- **Batch itself: free**. Pay for:
  - EC2 instances (On-Demand/Spot) or Fargate vCPU/GB-seconds.
  - EBS volumes, data transfer, NAT gateway processing, CloudWatch Logs, ECR storage.
- **Cost levers**:
  - **Spot** (EC2 or Fargate Spot) for fault-tolerant jobs, with retries and checkpoints. Often the biggest saving.
  - **`minvCpus = 0`**: scale to zero, nothing running when idle.
  - **`maxvCpus`**: a budget ceiling.
  - **Right-size** job vCPU/memory requests so more jobs pack per instance. Over-requesting leaves capacity idle.
  - **Graviton (arm64)** instances/Fargate for better price/performance (multi-arch images).
  - **Savings Plans**: Compute Savings Plans cover EC2 and Fargate used by Batch. Use them for steady baseline batch usage.
  - **Allocation strategy**: BEST_FIT is cheapest but slower to scale. Progressive/price-capacity balance cost and speed.
  - **VPC endpoints** instead of NAT for heavy ECR/S3 traffic (NAT per-GB fees add up with large images).
  - **Smaller images** reduce pull time (instance time is billed while pulling).
  - **Log retention**: `/aws/batch/job` logs never expire by default. Set retention.
- **Fargate vs EC2 cost**: Fargate is pay-per-task and simple, often fine for spiky small jobs. EC2 with good bin-packing + Spot is usually cheaper at high, steady volume.

## F. Monitoring and logging
- **CloudWatch Logs**: container stdout/stderr go to **`/aws/batch/job`** by default. Stream name `jobDefinitionName/default/<ecs-task-id>`. Get the stream name from `DescribeJobs` (`logStreamName`). Use a custom log group/driver in the job definition (`awslogs-group`, `awsfirelens` to OpenSearch/Splunk).
- **EventBridge events from Batch**:
  - **Batch Job State Change**: SUBMITTED → … → SUCCEEDED/FAILED, with the status reason and exit code.
  - **Job queue blocked** events (a RUNNABLE job at the head can't run, with a reason).
  - Compute environment and service job events (verify list).
  - Route to **SNS** (alerts on FAILED), Lambda (auto-resubmit, ticketing) or Step Functions.
- **CloudWatch Container Insights** for ECS (cluster/task CPU, memory, network). Batch CE instances form ECS clusters, so Container Insights shows utilization.
- **CloudWatch metrics**: ECS cluster metrics, EC2/ASG metrics, Fargate usage metrics. Batch job-level metrics such as counts by state (verify which native metrics exist; often built from EventBridge events or `ListJobs`).
- **Dashboard in the Batch console**: jobs by state, queues, CEs. Job details show attempts, status reason, exit code and log link.
- **Job status reason** (`statusReason`, `container.reason`, `exitCode`) is the first place to look for failures (for example "OutOfMemoryError: Container killed due to memory usage", "Host EC2 (instance i-...) terminated", "CannotPullContainerError").
- **CloudTrail** for who submitted, cancelled or changed queues/CEs.
- **X-Ray / OpenTelemetry** inside your container code for tracing (optional).

## G. Troubleshooting (symptom → cause → fix)
- **Jobs stuck in RUNNABLE**:
  - **Capacity**: `maxvCpus` reached, EC2 **vCPU quota** hit, no capacity for the chosen instance types (BEST_FIT waiting), Spot unavailable. Fix: raise max/quotas, add instance types/AZs, use progressive / price-capacity strategies, add an On-Demand fallback CE.
  - **Misconfiguration**: the job asks for more vCPU/memory/GPU than **any allowed instance type** has (or exactly all of an instance's memory), wrong architecture (arm64 image on x86 CE), Fargate settings invalid. Fix: lower requests or add bigger types.
  - **Invalid CE**: bad service role, deleted subnet/SG, wrong AMI, launch template errors → CE status INVALID. Fix the CE.
  - **Networking**: instances in a private subnet with no NAT/endpoints can't register with ECS → never become available.
  - Use the **job queue blocked** event / `statusReason`, and `jobStateTimeLimitActions` to auto-cancel blockers.
- **Job stuck in STARTING** → large image pull, slow ECR access through NAT, init containers (EKS). Fix: smaller images, VPC endpoints, image caching.
- **`CannotPullContainerError`** → wrong image URI/tag, the execution/instance role lacks ECR permissions, no route to ECR/S3 (private subnet without NAT/endpoints), Fargate without a public IP or NAT, or Docker Hub rate limits (use ECR pull-through cache).
- **`OutOfMemoryError: Container killed due to memory usage`** (exit 137) → the memory request is too low or there's a leak. Raise `MEMORY`, process in chunks, or move to R types.
- **Failed with `Host EC2 (instance i-xxx) terminated`** → Spot interruption or host failure. Fix: retry strategy with `evaluateOnExit` `onStatusReason: "Host EC2*"` → RETRY, plus checkpointing.
- **`Task failed to start`** / `ResourceInitializationError` (Fargate) → can't fetch secrets or pull the image (execution role permissions, network). Fix the IAM/network.
- **`AccessDenied` from S3/DynamoDB inside the job** → the **job role** is missing or lacks permissions (or the code uses the instance role by mistake), or a KMS key policy/bucket policy denies it.
- **Job timed out** → `attemptDurationSeconds` too low or the job hangs. Raise it or fix the hang. Remember STARTING time doesn't count.
- **Job fails immediately with "invalid job definition"** → not retried. Fix the definition (resource values, Fargate combinations, missing role).
- **Array job partly failed** → check failed child indexes (`ListJobs --array-job-id` with status FAILED). Resubmit only those, or use retries.
- **Dependent job never runs** → a dependency FAILED (the dependent job then fails/cancels; verify), or a wrong job ID in `dependsOn`.
- **Costs higher than expected** → `minvCpus` > 0 keeping instances on, oversized requests leaving instances half-empty, big NAT data charges for image pulls, logs never expiring.
- **CE won't scale beyond a few instances** → EC2 quotas, subnet IP exhaustion (Fargate/awsvpc), a narrow instance type list, BEST_FIT waiting for one type.

## H. Limits and numbers to remember
| Item | Value |
|---|---|
| Job queues per Region | 50 (fixed) |
| Compute environments per Region | 50 (fixed) |
| CEs per job queue | 3 |
| Batch CEs per EKS cluster | 5 |
| Job dependencies per job | 20 |
| Array job size | 2 – 10,000 children |
| Jobs in SUBMITTED state | 1,000,000 |
| SubmitJob TPS per account | 50 |
| Job definition size | 24 KiB |
| SubmitJob payload | 30 KiB |
| Retry attempts | 1 – 10 (default 1) |
| Timeout minimum | 60 s per attempt (counts from RUNNING) |
| Job record kept after finish | at least 7 days |
| Consumable resources | 50k |
| Service environments | 50; 1 per job queue |
| Quota shares per quota-management queue | 20 |
| SubmitServiceJob TPS | 5; service job retries up to 10 |
| Default log group | /aws/batch/job (never expires by default) |
| Batch price | Free (pay for EC2/Fargate etc.) |
| Max overshoot of maxvCpus | 1 instance (non-BEST_FIT strategies) |

## I. Final scenario set (if → then, because)
- **If** a nightly containerized job must run at **02:00** and send an alert when it fails, **then** use **Amazon EventBridge Scheduler** (verify its Batch target support) or a scheduled EventBridge rule to call Batch **SubmitJob**, plus a second EventBridge rule on **Batch Job State Change** = **FAILED** that sends to **Amazon Simple Notification Service (SNS)**. **This works because** EventBridge can start Batch jobs on a cron schedule, and Batch sends a state-change event (with status reason and exit code) when a job ends. EventBridge needs an IAM role allowed to call `batch:SubmitJob`.
- **If** each new upload to **Amazon S3** must start a heavy processing container, **then** route **S3 → Amazon EventBridge → Batch target**, passing the object key as a job parameter (input transformer), or use **S3 → AWS Lambda → SubmitJob**. **This works because** the S3 event triggers the submit, and the heavy work runs in Batch. Lambda stays small and only hands off the job.
- **If** a workflow must run extract (Lambda) → transform (Batch, wait until done) → load (AWS Glue) with retries and error handling, **then** use **AWS Step Functions** with **`batch:submitJob.sync`**. **This works because** `.sync` submits the job and **waits** for it to succeed or fail with no polling code, and Step Functions adds Catch/Retry and branching. Without `.sync`, the step ends as soon as the job is submitted.
- **If** the team already orchestrates its pipelines in Apache Airflow, **then** use **Amazon Managed Workflows for Apache Airflow (MWAA)** with the **`BatchOperator`**. **This works because** `BatchOperator` submits a Batch job and waits for it, so Batch fits into the existing Airflow workflows.
- **If** **3,000** independent CSV files must be converted to Parquet with custom code at the lowest cost, **then** run one **array job** on a **Spot compute environment (CE)** using **price-capacity-optimized** allocation, with retries on host termination and **idempotent** S3 outputs. **This works because** the array job fans out one child per file, Spot is often the biggest saving, and retrying on `Host EC2*` covers Spot interruptions. Writing to fixed (deterministic) S3 keys means a retry does not create duplicate rows.
- **If** the same conversion is plain Spark on Data Catalog tables and must need the least operations work, **then** use **AWS Glue**, not Batch. **This works because** Glue is serverless Spark with the catalog, crawlers, bookmarks and data quality built in; Batch is for custom containerized code.
- **If** a long Spot job keeps restarting from zero after interruptions, **then** add **checkpointing** to **Amazon S3** (or DynamoDB) plus a **retry strategy**. **This works because** the retry restarts the job after a Spot interruption, and the saved checkpoint lets it resume from its last progress instead of starting over.
- **If** jobs must reach a private **Amazon Relational Database Service (RDS)** database, **then** run the compute environments in the VPC's **private subnets** with **security group** rules for the DB port, take credentials from **AWS Secrets Manager** through `secrets`, and limit parallelism with **consumable resources** or **`maxvCpus`**. **This works because** jobs in the VPC can reach the database through security groups, and capping how many jobs run at once stops them from exhausting the database's connections.
- **If** jobs in private subnets cannot pull images and there is no NAT gateway, **then** add **VPC endpoints**: ECR API and ECR DKR interface endpoints, an **S3 gateway endpoint**, a **CloudWatch Logs** endpoint, and ECS endpoints for EC2 compute environments. **This works because** image layers live in **S3**, and without NAT these endpoints are the only route to **Amazon Elastic Container Registry (ECR)**, ECS and logging.
- **If** job code must read only one S3 prefix, **then** give the job definition a **job role** (task role) with a least-privilege policy for just that prefix. **This works because** the job role controls what **your code** can do, set per job definition.
- **If** developers must not run privileged containers or unapproved images, **then** add **IAM conditions** on `SubmitJob`/`RegisterJobDefinition` (for privileged mode and image; verify the condition key names) plus **ECR image scanning**. **This works because** Identity and Access Management (IAM) conditions such as `batch:Privileged` and `batch:Image` can block those requests, and scanning (basic, or enhanced with Amazon Inspector) finds vulnerable images.
- **If** GPU model inference runs nightly on many images, **then** use an **EC2 GPU compute environment** (G family), an **array job** split into batches of images, and **`minvCpus = 0`**. **This works because** GPUs need EC2, the array job spreads the batches across children, and a minimum of 0 vCPUs scales the CE to zero so you stop paying during the day.
- **If** a **32-node** MPI weather model must run, **then** use a **multi-node parallel (MNP)** job on **EC2** with **Elastic Fabric Adapter (EFA)** and a **cluster placement group**. **This works because** an MNP job spans many instances as one tightly coupled job, and EFA plus the placement group give the low network latency MPI needs.
- **If** many teams must share batch capacity fairly, **then** use one compute environment and one queue with a **fair-share scheduling policy** and a **share identifier** per team. **This works because** fair-share gives each share identifier its share of capacity, so one team's backlog cannot starve the others.
- **If** jobs sit in **RUNNABLE** all night, **then** check the **job queue blocked** event and the job's **`statusReason`**. Common causes are EC2 vCPU quotas, `maxvCpus` reached, memory requests too big for any instance type, an **INVALID** compute environment, or instances that cannot register with ECS because of networking. **This works because** RUNNABLE means ready but waiting for capacity, and a job can wait there forever if no compute environment can fit it.
- **If** the bill shows idle EC2 instances for Batch, **then** look for **`minvCpus` above 0** and set it to **0** unless warm starts are needed. **This works because** a minimum above 0 keeps instances running all the time, while 0 lets the compute environment scale to zero.
- **If** logs fill **Amazon CloudWatch Logs** forever, **then** set a retention period on the **`/aws/batch/job`** log group. **This works because** Batch job logs go to that group by default and never expire unless you set retention.
- **If** an exam question says "run batch computing workloads of any scale on containers without managing a scheduler, using Spot to cut cost", **then** the answer is **AWS Batch**. **This works because** Batch is a free, fully managed scheduler and compute manager that queues container jobs, scales EC2/Fargate (including Spot) and scales back to zero.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: job states and log group details, jobs stuck in RUNNABLE (capacity, misconfiguration, invalid CE categories, queue-blocked events, jobStateTimeLimitActions), retry strategy behavior, allocation strategies, quotas table, Fargate compute environment basics, fair-share scheduling basics, SageMaker Training job queuing via service environments.
Not confirmed (verify): EventBridge Scheduler Batch target support, IAM condition key names for Batch, Fargate ephemeral storage encryption options, list of Batch EventBridge event types beyond job state change and queue blocked, native Batch CloudWatch job metrics, dependency-failure behavior for dependent jobs.

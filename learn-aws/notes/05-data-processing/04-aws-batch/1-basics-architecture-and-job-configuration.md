# AWS Batch – 1. Basics, architecture and job configuration

Short notes. Each point is a fact you can be asked about.

## A. What AWS Batch is
- **AWS Batch** = a fully managed **batch job scheduler and compute manager**. You submit **containerized jobs** to a **queue**. Batch picks, launches and scales the compute, runs the jobs in order/priority, retries failures and **scales back to zero** when the queue is empty.
- Runs on top of **Amazon ECS** or **Amazon EKS**, using **EC2 (On-Demand or Spot)**, **Fargate (and Fargate Spot)**, or **Amazon ECS Managed Instances** capacity.
- **No extra charge** for Batch itself. You pay only for the EC2/Fargate (and EBS, data transfer, logs) that jobs use.
- You don't install or run any scheduler (no Slurm/PBS/cron servers). This is the managed answer to "run thousands of batch jobs".
- Every job is a **container image** (usually from **ECR**). Code, libraries and runtime are inside the image.
- Typical workloads:
  - Big nightly ETL steps that are too long for Lambda.
  - File-by-file processing (thousands of files → array jobs).
  - Data conversions, genomics, simulations, risk models, media transcoding.
  - ML training/inference batches, report generation.
- Batch also offers **job queues for SageMaker Training jobs** (service environments). ML teams can queue training jobs with priorities and quotas.
- Pick Batch when:
  - Jobs run **longer than 15 minutes** (Lambda's limit) or need more than 10 GB memory, GPUs or big local disk.
  - You have **many independent jobs** that need queuing, priorities, retries and dependencies.
  - The code is any language in a container, not just Spark.
  - You want cheap **Spot** capacity with automatic retry.
- Avoid Batch when:
  - The work is **Spark/SQL ETL** on big datasets → **Glue** or **EMR** (distributed engines with catalog integration).
  - SQL on S3 → **Athena**.
  - Short event-driven tasks → **Lambda**.
  - Always-on services/APIs → **ECS/EKS services**.
- **Batch vs Glue**:
  - Glue = serverless Spark/Python shell with the Data Catalog, crawlers, bookmarks and DQ.
  - Batch = generic containers with full control of the runtime, any language/library, GPU, Spot.
  - The exam usually picks Glue for ETL on data-lake tables, and Batch for custom containerized compute jobs.
- **Batch vs EMR**: EMR runs distributed frameworks (Spark, Hive, Presto, Flink) across a cluster. Batch runs many **separate** containers (or MPI multi-node jobs), and doesn't give you Spark by itself.
- **Batch vs Step Functions**: Step Functions **orchestrates** steps. Batch **runs** the compute for a step. They are used together (Step Functions `SubmitJob.sync`).
- **Batch vs plain ECS/EKS tasks**: ECS RunTask runs a container but has **no queue, priorities, retries, dependencies or array jobs**. Batch adds the scheduling layer and capacity management.
- **Batch vs EC2 + cron**: cron on EC2 means managing servers, scaling and failures yourself. Batch handles it all and scales to zero.

## B. Core components
- **Compute environment (CE)** = a pool of compute capacity: EC2, Spot, Fargate, Fargate Spot, EKS nodes or ECS Managed Instances. Batch scales it between min and max vCPUs.
- **Job queue** = where jobs wait. It has a **priority** and an **ordered list of up to 3 compute environments** to place jobs on.
- **Job definition** = a template for jobs: image, vCPU, memory, GPU, command, environment, roles, retries, timeout, volumes, logging. **Versioned** (revisions `name:1`, `name:2`).
- **Job** = one unit of work submitted to a queue with a job definition (plus overrides). Can be a single job, an **array job** or a **multi-node parallel** job.
- **Scheduling policy** (optional) = **fair-share** rules for a queue. Without one, the queue is **FIFO**.
- **Service environment** (newer) = capacity/quotas for **SageMaker Training jobs** queued through Batch.
- Flow: `SubmitJob` → queue → scheduler finds a CE with room (in CE order) → Batch scales the CE if needed → container runs → exit code decides success or failure.

## C. Compute environments in detail
- **Managed CE** (recommended): Batch launches/terminates instances (through an Auto Scaling group / EC2 Fleet) to match queue demand, inside **min/max vCPUs**.
- **Unmanaged CE**: you run and manage the ECS container instances yourself. Batch only schedules. Rarely used, for special AMIs or hardware you control.
- **Provisioning models**:
  - **EC2 (On-Demand)**: reliable, any instance type, GPU, large memory, custom AMIs/launch templates.
  - **SPOT**: up to ~90% cheaper (verify). Jobs can be interrupted, so **use retries**. Good for fault-tolerant work.
  - **FARGATE**: serverless, no instances to choose. Each job gets its own isolated task. Fast to start for small/medium jobs.
  - **FARGATE_SPOT**: Fargate at a discount, can be interrupted.
  - **EKS CE**: Batch runs jobs as pods on EC2 nodes it manages in your **existing EKS cluster** (Fargate is not supported on Batch-on-EKS). Up to 5 Batch CEs per EKS cluster.
  - **ECS Managed Instances CE** (newer): ECS picks instance types from `instanceRequirements`. No allocation strategy needed (verify details).
- **Key EC2 CE settings**:
  - **`minvCpus`**: set **0** to **scale to zero** when idle (no cost). Above 0 keeps instances warm (faster starts, constant cost).
  - **`desiredvCpus`** (managed by Batch), **`maxvCpus`**: hard cap on CE size and spending. Batch may exceed max by **at most one instance** with progressive strategies.
  - **`instanceTypes`**:
    - A list of types or families, or **`optimal`**, which picks from current C, M and R families (verify the current definition).
    - Use `default_x86_64` / `default_arm64` (verify names) for newer defaults.
    - Include GPU types for GPU jobs.
  - **Allocation strategy** (EC2/Spot only; not Fargate or ECS Managed Instances):
    - **`BEST_FIT`** (default): picks the best-fitting **lowest-cost** type. If it is not available, it **waits**, which keeps cost low but can limit scaling. Not supported when updating a CE.
    - **`BEST_FIT_PROGRESSIVE`**: adds other large-enough types (lowest cost per vCPU first) if the first choice is unavailable. **Recommended for On-Demand**.
    - **`BEST_FIT_PROGRESSIVE_ORDERED`**: like progressive but follows **your order** of instance types (On-Demand only).
    - **`SPOT_CAPACITY_OPTIMIZED`**: picks Spot pools least likely to be interrupted.
    - **`SPOT_PRICE_CAPACITY_OPTIMIZED`**: considers both price and interruption risk. **AWS recommends it over capacity-optimized for most Spot use**.
    - **`SPOT_CAPACITY_OPTIMIZED_PRIORITIZED`**: capacity first, then your type order on a best-effort basis.
  - **Launch template**: custom user data (mount disks, install agents), larger root/data EBS volumes, IMDSv2 settings, tags. A **custom AMI** must be ECS-optimized (or EKS-optimized) to work.
  - **Networking**: VPC, **subnets** (several AZs for capacity), **security groups**. Instances in **private subnets need a NAT gateway or VPC endpoints** (ECR, ECS, S3, CloudWatch Logs) to pull images and send logs.
  - **Instance role** (ECS instance profile, `ecsInstanceRole`): lets the ECS agent on EC2 hosts register and pull images.
  - **Spot settings**: `bidPercentage` (max % of On-Demand price; leave empty to use the default up to the On-Demand price; verify). Spot Fleet role (needed with BEST_FIT on Spot).
  - **EC2 configuration**: image type (Amazon Linux 2023 ECS-optimized, GPU variants, EKS AL2023).
  - **Update policy**: how to replace instances when the CE changes (`terminateJobsOnUpdate`, `jobExecutionTimeoutMinutes`).
- **CE states**: `ENABLED`/`DISABLED` (a disabled CE takes no new jobs) and status `VALID`/`INVALID`. An **INVALID** CE (bad role, bad subnet, bad AMI) blocks jobs, which stay in RUNNABLE.
- Quotas: **50 CEs per Region** (fixed), **3 CEs per job queue**.

## D. Fargate vs EC2 compute environments
- **Fargate is better for**:
  - Small/medium jobs that should start fast with no instance management.
  - Strong per-job isolation (each job has its own kernel and ENI).
  - Spiky workloads with idle periods.
  - Both x86 and **ARM64 (Graviton)** jobs (per job via `runtimePlatform.cpuArchitecture`).
- **EC2 is better for**:
  - **GPU** jobs, **multi-node parallel** jobs, very large memory/vCPU, custom AMIs, large or fast local storage, privileged containers.
  - Very high job volume where bin-packing many jobs on big instances is cheaper.
  - Specific instance families.
- Fargate job resources: you set vCPU and memory from fixed combinations (up to 16 vCPU / 120 GB; verify), and ephemeral storage up to 200 GB (verify). Needs **platform version** and **`assignPublicIp`** settings (or NAT) to pull images.
- Fargate jobs need an **execution role** (to pull from ECR and write logs). EC2 jobs use the instance role for that.
- A job queue **cannot mix Fargate and EC2 CEs** (verify). Use separate queues.

## E. Job queues
- A queue has:
  - **Priority** (an integer, higher = scheduled first **when queues share the same CEs**).
  - **State** (ENABLED/DISABLED).
  - **Ordered list of CEs** (max 3; tried in order).
  - An optional **scheduling policy** (fair-share).
- Many queues can point to the **same CE**. For example, a "high-priority" queue (priority 100) and a "backfill" queue (priority 1) sharing a Spot CE. Urgent jobs then go first.
- **CE order** pattern: put the cheap Spot CE first, then an On-Demand CE as overflow. Or put Fargate first, then EC2.
- **FIFO by default**: jobs run in submission order (subject to resources).
- **Fair-share scheduling** (attach a **scheduling policy**):
  - Jobs carry a **share identifier** (for example per team or pipeline). The policy gives each identifier a **weight factor** (a lower weight gets a larger share; verify direction).
  - **Share decay** (how long past usage counts).
  - **Compute reservation** (keep some capacity free for share identifiers not currently active).
  - **Scheduling priority** inside a share identifier.
  - Prevents one big team's backlog from starving others.
- **`jobStateTimeLimitActions`** on a queue: auto-**cancel** jobs stuck in RUNNABLE longer than a threshold for given reasons (for example, misconfiguration or capacity). Stops one bad job **blocking the queue head**.
- **Quota management** (newer, for service environments / SageMaker jobs): quota shares per team inside a queue (max 20 per queue; verify scope).
- Quotas: **50 job queues per Region** (fixed).

## F. Job definitions
- **Type**: `container` (single-node), `multinode` (multi-node parallel), or EKS pod properties for Batch on EKS.
- **Platform capability**: `EC2` or `FARGATE`.
- **Container properties**:
  - `image` (ECR URI with a tag or **digest**; pin versions).
  - `command` (can use `Ref::param` placeholders filled from **parameters**).
  - `resourceRequirements` (`VCPU`, `MEMORY` in MiB, `GPU`).
  - `environment` (plain variables).
  - **`secrets`** (from **Secrets Manager** or **SSM Parameter Store**, injected as env vars; needs the execution role).
  - `jobRoleArn`, `executionRoleArn`.
  - `volumes` + `mountPoints` (host paths, **EFS** with an access point and IAM auth), `linuxParameters` (shared memory, devices, swap), `ulimits`, `readonlyRootFilesystem`, `privileged` (EC2 only), `user`.
  - `logConfiguration` (default `awslogs` to CloudWatch Logs; others like `awsfirelens`, `splunk`).
  - `ephemeralStorage` (Fargate), `networkConfiguration` (Fargate public IP), `fargatePlatformConfiguration`, `runtimePlatform` (CPU architecture).
- **Memory trap**: if the container uses more memory than set, it is **killed (OOM)**, so the job fails. Also, the instance reserves memory for the ECS agent and OS, so a job asking for the **full** instance memory may **never fit** and stays RUNNABLE (ask a little less).
- **Parameters**: default values in the job definition, overridden at `SubmitJob` (for example `Ref::input_key`). The same definition can run many inputs.
- **Retry strategy**:
  - **`attempts` 1–10** (default 1, so no retry).
  - **`evaluateOnExit`** (up to 5 conditions; verify vs 6) matches `onExitCode`, `onReason`, `onStatusReason` (glob patterns) → `RETRY` or `EXIT`. If none matches, the job is retried. Add a final catch-all `EXIT`.
  - Classic pattern: **retry on `Host EC2*` status reason** (Spot interruption/host termination), exit on application errors.
  - **Cancelled/terminated jobs and jobs with invalid definitions are not retried**.
  - The `AWS_BATCH_JOB_ATTEMPT` env var holds the attempt number.
- **Timeout**: `attemptDurationSeconds` (**minimum 60 s**). The time limit is **per attempt** and counts from **RUNNING** (STARTING time such as the image pull is not counted). On timeout the job is terminated and may be retried.
- **Propagate tags** to ECS tasks (cost allocation). **Scheduling priority** in the job definition for fair-share queues.
- **Consumable resources** (resource-aware scheduling): define counted resources (for example license seats, DB connection slots). Jobs request them, and Batch only runs jobs when units are free (max 50k consumable resources).
- Job definition size max **24 KiB**. **Deregister** old revisions to keep them tidy (revisions are not deleted, only marked INACTIVE).

## G. Job types
- **Single job**: one container, one attempt at a time.
- **Array job**:
  - One `SubmitJob` with **`arrayProperties.size` 2–10,000** creates N **child jobs** sharing the same definition and parameters.
  - Each child gets **`AWS_BATCH_JOB_ARRAY_INDEX`** (0…N-1), which the code uses to pick its input, for example the Nth file from a manifest in S3.
  - The parent job is PENDING while children run. It succeeds only if all children succeed (verify).
  - Ideal for "process 5,000 files in parallel" and parameter sweeps.
  - Array dependencies:
    - **`N_TO_N`**: child i of job B waits for child i of job A.
    - **`SEQUENTIAL`**: children run one after another in index order.
- **Multi-node parallel (MNP) job**:
  - One job spanning **many EC2 instances** (a main node + child nodes) with node ranges and per-range container properties.
  - For **tightly coupled HPC / MPI** and **distributed ML training**.
  - Needs **EC2** (not Fargate). Supports **EFA** and cluster placement groups for low latency.
  - The `AWS_BATCH_JOB_MAIN_NODE_INDEX`, `AWS_BATCH_JOB_NODE_INDEX` and `AWS_BATCH_JOB_NUM_NODES` env vars coordinate nodes.
  - Not supported with Spot (verify) and not with array jobs.
- **Job dependencies** (`dependsOn`): a job waits (PENDING) until up to **20** listed jobs **succeed**. If a dependency fails, the dependent job fails too (verify). Use them to build simple pipelines (extract → transform → load). Use Step Functions for richer logic.
- **Job states**:
  - **`SUBMITTED`**: not yet checked by the scheduler.
  - **`PENDING`**: waiting on dependencies (array parents sit here while children run).
  - **`RUNNABLE`**: ready, waiting for capacity. **Can wait forever** if no CE can fit it.
  - **`STARTING`**: placed on a host. **Image pull** and container start happen here (not counted in the timeout).
  - **`RUNNING`**: container running. Logs in CloudWatch.
  - **`SUCCEEDED`**: exit code 0.
  - **`FAILED`**: all attempts used. Exit code non-zero, OOM, timeout, host failure.
  - Finished jobs are kept in Batch for **at least 7 days**.
- **Cancel vs terminate**:
  - `CancelJob` stops jobs that are not yet running (SUBMITTED/PENDING/RUNNABLE).
  - `TerminateJob` stops jobs that are STARTING/RUNNING too.
  - Neither is retried.
- Submission limits: **50 SubmitJob TPS per account**, payload **30 KiB**, up to **1,000,000 jobs in SUBMITTED** state. For huge fan-outs, use **array jobs** instead of millions of single submits.

## H. Useful environment variables inside a job
- `AWS_BATCH_JOB_ID`, `AWS_BATCH_JQ_NAME`, `AWS_BATCH_CE_NAME`, `AWS_BATCH_JOB_ATTEMPT`.
- `AWS_BATCH_JOB_ARRAY_INDEX` (array children), `AWS_BATCH_JOB_ARRAY_SIZE` (verify).
- `AWS_BATCH_JOB_MAIN_NODE_INDEX`, `AWS_BATCH_JOB_NODE_INDEX`, `AWS_BATCH_JOB_NUM_NODES`, `AWS_BATCH_JOB_MAIN_NODE_PRIVATE_IPV4_ADDRESS` (MNP).

## Scenarios (if → then, because)
- **If** a nightly Python job runs for **2 hours** and needs custom native libraries, **then** run it on **AWS Batch**, a managed scheduler that runs containerized jobs from a queue, with the code and libraries baked into a **container image** (usually stored in **Amazon Elastic Container Registry (ECR)**). **This works because** **AWS Lambda** stops at **15 minutes**, and **AWS Glue** is a serverless Spark/Python shell service that may not fit custom native dependencies. A container gives full control of the runtime, any language and any library.
- **If** **8,000** files in **Amazon S3** must each be processed the same way, **then** submit one **array job** of size **8,000**. Each child job reads **`AWS_BATCH_JOB_ARRAY_INDEX`** (0 to 7,999) and uses it to pick its file, for example the Nth line of a manifest in S3. **This works because** one `SubmitJob` call fans out into thousands of **child jobs** that share the same job definition and parameters, instead of 8,000 separate submits.
- **If** **20,000** files must be processed, **then** submit **2 array jobs**, or make each child handle a group of files. **This works because** an array job is capped at **10,000** children (size 2–10,000), so one array job cannot cover all 20,000 files one-per-child.
- **If** jobs must be as cheap as possible and can survive interruption, **then** use a **Spot compute environment (CE)** with the **`SPOT_PRICE_CAPACITY_OPTIMIZED`** allocation strategy, many instance types, and a **retry strategy** that retries when the status reason matches **`Host EC2*`**. **This works because** Spot is up to about **90% cheaper (verify)**, price-capacity-optimized weighs both price and interruption risk (AWS recommends it for most Spot use), and a Spot interruption shows up as `Host EC2*`, so only those failures are retried.
- **If** **Spot** capacity runs out but jobs must still finish, **then** give the **job queue** two compute environments in order: the **Spot CE first** and an **On-Demand CE second**. **This works because** a queue tries its ordered list of up to **3** compute environments in order, so the cheap Spot pool is used first and On-Demand acts as overflow.
- **If** a job needs **GPUs**, **then** use an **EC2 compute environment** that includes GPU instance types, and request **`GPU`** in the job's **`resourceRequirements`**. **This works because** Batch only assigns GPU devices that the job asks for, and **AWS Fargate** (serverless containers) does not offer GPUs; GPU jobs are an EC2-only case.
- **If** a distributed **MPI** simulation needs **16 nodes** talking with low latency, **then** run a **multi-node parallel (MNP)** job on **EC2** with **Elastic Fabric Adapter (EFA)** and a **cluster placement group**. **This works because** an MNP job spans many EC2 instances (a main node plus child nodes) as one job, built for tightly coupled HPC; EFA and the placement group cut network latency. MNP needs EC2, not Fargate.
- **If** many small, short jobs must start fast with no servers to manage, **then** use a **Fargate compute environment**. **This works because** Fargate is serverless, each job gets its own isolated task, and it starts quickly for small and medium jobs with no instances to choose or manage.
- **If** the account should cost nothing when no jobs run, **then** use a **managed compute environment** with **`minvCpus = 0`**. **This works because** Batch itself is free and a managed CE scales between min and max vCPUs, so with a minimum of 0 it scales **down to zero** instances when the queue is empty.
- **If** jobs must start instantly every morning, **then** keep **`minvCpus` above 0** (warm instances) during working hours, then lower it again. **This works because** scaling an EC2 compute environment up from zero takes minutes; warm instances skip the launch but cost money all the time they run.
- **If** total spending must be capped, **then** set **`maxvCpus`** on the compute environments. **This works because** `maxvCpus` is a hard cap on CE size (Batch may exceed it by **at most one instance** with progressive strategies), so it acts as a budget ceiling.
- **If** urgent jobs keep waiting behind huge backfill jobs, **then** create a separate **high-priority job queue** on the same compute environment, or attach a **fair-share scheduling policy**. **This works because** queue **priority** (higher runs first) decides who goes first when queues share the same CEs; without a scheduling policy a queue is just **FIFO** (first in, first out).
- **If** three teams share one queue and one team floods it, **then** attach a **fair-share scheduling policy** and give each team its own **share identifier**. **This works because** the policy gives each share identifier a **weight factor** (a lower weight gets a larger share; verify direction), so one team's big backlog cannot starve the others.
- **If** step B must start only after step A succeeds, **then** submit B with **`dependsOn`** set to job A (or use **AWS Step Functions** for complex flows). **This works because** a dependent job waits in **PENDING** until up to **20** listed jobs succeed. Step Functions is the orchestrator for richer logic such as branching and error handling.
- **If** chunk i of the transform must wait only for chunk i of the extract, **then** use an **`N_TO_N` array dependency** between the two array jobs. **This works because** with `N_TO_N`, child i of job B waits for child i of job A, so each chunk starts as soon as its own input is ready.
- **If** a job needs a database password, **then** use **`secrets`** in the job definition pointing to **AWS Secrets Manager** (or **SSM Parameter Store**), and allow the **execution role** to read it. **This works because** Batch injects the secret as an environment variable at start, and the execution role is the role that fetches it, so the password never sits in the image or the command.
- **If** a job reads **Amazon S3** and writes **Amazon DynamoDB**, **then** set the **job role** (task role, `jobRoleArn`) with exactly those permissions, not the instance role. **This works because** the job role is what **your code** can do, per job definition, while the **instance role** is for the ECS agent on the host (registering and pulling images).
- **If** a job sometimes hangs forever, **then** set a timeout with **`attemptDurationSeconds`** (at least **60 s**) plus retries. **This works because** on timeout Batch terminates the attempt and may retry it. The limit is **per attempt** and counts from **RUNNING**, so image-pull time in STARTING is not counted.
- **If** a job asks for all **16 GiB** of a 16 GiB instance and never starts, **then** lower the memory request below the instance's available memory. **This works because** the instance reserves some memory for the ECS agent and the operating system, so a job asking for the full amount never fits and stays in **RUNNABLE**.
- **If** one misconfigured job blocks the head of the queue for hours, **then** set **`jobStateTimeLimitActions`** on the queue to cancel jobs stuck in **RUNNABLE**. **This works because** this setting auto-**cancels** jobs that wait in RUNNABLE longer than a threshold for given reasons (such as misconfiguration or capacity), so the jobs behind it can run.
- **If** only **5** software licenses exist for a tool, **then** define them as **consumable resources** (resource-aware scheduling) and have each job request one. **This works because** Batch only runs a job when units of its consumable resource are free, so at most 5 jobs use the license at once.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: what Batch is (ECS/EKS orchestration, EC2/Fargate/ECS Managed Instances capacity, SageMaker Training job queues), Batch quotas (50 queues, 50 CEs, 5 CEs per EKS cluster, 3 CEs per queue, 20 dependencies, 24 KiB definition, 30 KiB payload, 10,000 array size, 1,000,000 SUBMITTED jobs, 50 SubmitJob TPS, 50k consumable resources, service environment and quota share limits), allocation strategies (BEST_FIT default, BEST_FIT_PROGRESSIVE, BEST_FIT_PROGRESSIVE_ORDERED, SPOT_CAPACITY_OPTIMIZED, SPOT_PRICE_CAPACITY_OPTIMIZED recommended, SPOT_CAPACITY_OPTIMIZED_PRIORITIZED; exceed max by at most one instance), job states (STARTING not in timeout, 7-day retention, logs in /aws/batch/job), retries (1–10 attempts, evaluateOnExit, AWS_BATCH_JOB_ATTEMPT, cancelled/terminated not retried), Fargate (x86 + ARM64, ECS only, not on EKS), fair-share scheduling (FIFO default, scheduling policy, dependsOn), jobStateTimeLimitActions.
Not confirmed (verify): Spot discount figure, `optimal`/default instance type names, ECS Managed Instances CE details, bidPercentage default, Fargate max vCPU/memory/storage, mixing Fargate and EC2 CEs in one queue, fair-share weight direction, quota management scope, evaluateOnExit max entries (5 vs 6), array parent success rule, MNP with Spot, dependency failure behavior, AWS_BATCH_JOB_ARRAY_SIZE.

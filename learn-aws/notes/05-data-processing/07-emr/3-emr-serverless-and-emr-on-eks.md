# Amazon EMR – 3. EMR Serverless and EMR on EKS

Short notes. Each point is a fact you can be asked about.

## A. EMR Serverless: the idea
- **EMR Serverless** = a deployment option where you **do not configure, size, secure or operate clusters**. You create an **application**, submit **job runs**, and EMR **provisions workers, scales them per stage, and releases them** when jobs finish.
- **Engines**: **Apache Spark** and **Apache Hive** (the docs state these two). Pick the **EMR release label** for the engine version (for example `emr-6.6.0` → Spark 3.2.0). **Regional service** that spreads workloads across AZs for you.
- **Isolation**: **each application runs in a secure environment strictly apart from other applications**.
- **Good for**: spiky or unpredictable batch Spark/Hive jobs, teams without cluster-ops skills, dev/test, many small jobs, per-team cost control.
- **Not for**: HBase, Presto/Trino, Flink, custom daemons on nodes, SSH access to nodes, workloads needing very specific instance types/Spot control **(as of the docs; verify engines list)**.

## B. Core concepts
- **Release version**: set per application; pick when you need a specific Spark/Hive version. Use **separate applications** for different versions, A/B upgrades, test vs prod, per-team cost controls, or different engines.
- **Application**: the long-lived object (type `SPARK` or `HIVE`, release label, **maximum capacity**, **initial capacity**, auto start/stop, network, runtime configuration). **Application states**: `CREATED`, `STARTING`, `STARTED`, `STOPPING`, `STOPPED`, `TERMINATED`.
- **Job run**: one request to an application; **asynchronous**; runs **concurrently** with other job runs. Each job run specifies a **runtime role** (IAM) and may use a different role from other jobs.
- **Workers**: internal units (**driver** and **executors** for Spark; **driver** and **Tez task** workers for Hive). Default worker sizes depend on **application type and release**; you override per job. Jobs are broken into **tasks**; workers are provisioned and decommissioned automatically; **scaling follows parallelism at every stage**.
- **EMR Studio** is the console for Serverless apps (auto-created in your account when you create your first application); also used for **interactive notebooks** and running jobs from the UI.
- **Interactive**: **EMR Studio workspaces**/Livy-style sessions and **interactive endpoints** attach notebooks to Serverless applications **(verify)**.

## C. Capacity: initial, maximum and auto start/stop
- **Pre-initialized capacity (`initialCapacity`)**: a **warm pool** of **drivers and workers** kept ready so jobs **start in seconds**. Specify counts and per-worker **CPU/memory/disk** (for example 5 drivers × 2 vCPU/4 GB and 50 executors × 4 vCPU/8 GB).
  - **You pay for pre-initialized workers even when idle**. Use only where fast start matters (interactive, time-sensitive, iterative).
  - Jobs **use pre-initialized workers first**, then request more up to the **maximum capacity**. When jobs end, capacity **returns to `initialCapacity`**; extra workers are released.
  - **Restored automatically** if workers fail or are released.
  - An application reaches **`STARTED`** only when the requested pre-initialized capacity exists. With **no** pre-initialized capacity, it goes `CREATED` → `STARTED` immediately.
  - **Align worker size with Spark container size**: if executors ask for 2 vCPU/8 GB but pre-init workers are 4 vCPU/16 GB, half the worker is wasted. **Spark adds ~10% memory overhead** by default, so pre-init worker memory must be **bigger than executor memory + overhead** for a job to use it.
  - Changes to initial capacity need **all configurations specified** and only when the app is **`CREATED` or `STOPPED`**.
- **Maximum capacity (`maximumCapacity`)**: a hard **cap on total vCPU, memory (and disk)** for the application (for example `400vCPU`, `1024GB`). **Cost guardrail** and fairness among apps. Jobs beyond the cap **queue**/scale within the cap.
- **Auto start / auto stop**: the application **auto-starts on job submission** and **auto-stops after being idle** (default **15 minutes**) to release pre-initialized capacity. Keep **auto stop ON**, especially with pre-initialized workers, to avoid surprise charges.
- **Spark dynamic allocation defaults** on Serverless: `spark.dynamicAllocation.enabled=true`, `initialExecutors=3`, `minExecutors=0`, `maxExecutors=infinity` (6.10.0+; 100 on ≤6.9), `executorIdleTimeout=60s`; **`spark.emr-serverless.allocation.batch.size=20`** containers per 1-second cycle. **Set `maxExecutors`** (or app max capacity) to prevent runaway cost.
- **`dynamicAllocationOptimization=true`** (Spark classification): aligns executor requests with worker creation to **reuse workers across stages** (lower cost for multi-stage jobs; can slow "big–small–big" stage patterns).
- **Spark defaults**: driver/executor **4 cores**, **14 GB** memory (workers < 32 vCPU), **20 GB** disk, `spark.emr-serverless.memoryOverheadFactor=0.1`; disk types **Standard** (default) or **shuffle-optimized**.
- **Set driver/executor cores and memory in `StartJobRun`** (`sparkSubmitParameters --conf ...` or `configurationOverrides` `spark-defaults`), **not in your script**, because the script runs too late for worker sizing.
- **Config priority (high → low)**: EMR-provided `SparkSession` settings → `--conf` in `sparkSubmitParameters` → job `applicationConfiguration` overrides → application `runtimeConfiguration` → EMR optimized defaults → open-source defaults.
- **Worker architecture**: **x86_64 or arm64 (Graviton)** per application (cheaper, needs compatible libraries) **(verify)**.

## D. Jobs, logging and operations
- **`StartJobRun`** parameters: `applicationId`, `executionRoleArn` (runtime role), `jobDriver` (`sparkSubmit` with `entryPoint` in S3, `entryPointArguments`, `sparkSubmitParameters`; or `hive` with `query`, `initQueryFile`), `configurationOverrides` (`monitoringConfiguration`: **S3**, **CloudWatch Logs**, **managed persistence**; `applicationConfiguration`), `executionTimeoutMinutes` (default **720 = 12 hours**) **(verify)**, tags, **retry policy** (`retryPolicy` with `maxAttempts` for **job resiliency**, mainly streaming) **(verify)**.
- **Runtime role needs**: read S3 data and script/JAR, write S3 output and logs, KMS permissions, **Glue Data Catalog** access for Spark SQL.
- **Job states**: `SUBMITTED`, `PENDING`, `SCHEDULED`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELLING`, `CANCELLED`, `QUEUED`.
- **Logs**: S3 bucket must be in **the same account and Region** as the app; **managed persistence** keeps logs for the **Spark UI** for 30 days at no charge **(verify)**; **`GetDashboardForJobRun`** returns a Spark UI/Tez UI link.
- **Python dependencies**: **custom images (ECR)** for the app, or **`spark.archives` with a packed virtualenv** (venv-pack), or `--py-files`.
- **Custom images**: base image from the **EMR Serverless ECR public repo**, add libs, push to your ECR; reference in the application. Allows **JDK/Python/native libs**.
- **Streaming**: Spark Structured Streaming jobs are supported with the retry policy; long-running streaming can be **costly** vs Managed Flink/MSK processing.
- **Orchestration**: **Step Functions** (SDK integration), **MWAA** (`EmrServerlessStartJobOperator`), **EventBridge** (job state change events), **CloudFormation/CDK** (`AWS::EMRServerless::Application`).
- **Observability**: **CloudWatch metrics** (application capacity, running/pending workers), **`AWS/Usage` quota metrics**, **EventBridge** state events, **CloudTrail**.

## E. Networking and security (Serverless)
- Default: apps run in an **AWS-managed network** with **internet access to AWS public endpoints**.
- **Private resources** (RDS, Redshift in your VPC): attach the app to **your VPC** (subnets + security groups). Use **VPC endpoints (S3 gateway, Glue, STS, CloudWatch Logs, ECR if custom images)** or NAT for outbound access. Each **worker needs an ENI/IP** in the subnets, so use **large subnets in multiple AZs**.
- **IAM**: **runtime role per job** (least privilege), **app-level access** by IAM policies (users/roles can start jobs only on certain apps via tags/conditions), **`iam:PassRole`** for the runtime role.
- **Encryption**: S3 data with SSE-S3/SSE-KMS, **local worker disks encrypted at rest** by default **(verify)**, in-transit TLS; **customer-managed KMS** for logs/shuffle options.
- **Lake Formation / fine-grained access**: supported for Spark with runtime roles in recent releases **(verify)**; **S3 access grants** support.
- **Data privacy**: no SSH to workers; AWS manages the OS patching.

## F. Pricing and quotas (Serverless)
- **Billed per second (1-minute minimum)** for aggregate **vCPU-hours, memory GB-hours, and storage** used by workers, from when a worker **starts** until it **stops** (rounded up to the second).
- **Example rates (US East, pricing page excerpt)**: **$0.052624 per vCPU-hour**, **$0.0057785 per GB-hour of memory**. Standard storage: **first 20 GB per worker included**, extra billed; **shuffle-optimized storage**: all configured storage billed. **Graviton** workers have lower rates (values not shown).
- **Pre-initialized capacity** is billed while the workers are provisioned, **idle or not** (page excerpt did not detail it).
- **Worked example on the page**: 25–75 workers of 4 vCPU/30 GB ≈ **$9.60** for the stated run.
- **Quotas**: **max concurrent vCPUs per account = 16 default (adjustable)** and **new accounts start low; EMR Serverless raises quotas automatically based on usage**. API limits are low (for example **`StartJobRun` 1 TPS, burst 25**; `GetJobRun` 10 TPS, burst 50). Usage metrics publish to **`AWS/Usage`** every minute.
- **Cost controls**: set **maximum capacity**, cap **`maxExecutors`**, keep **auto-stop** on, avoid unneeded pre-initialized workers, right-size worker sizes, use Graviton, tune partitions, compact small files, and **set job timeouts**.
- **When Serverless costs more than EC2**: very large, steady, 24×7 workloads with **Spot-heavy EC2 fleets** can be cheaper; spiky work usually favors Serverless.

## G. EMR on EKS: the idea
- **EMR on EKS** runs **Spark jobs on an Amazon EKS cluster you already have**. AWS manages the **EMR runtime containers** (EMR-optimized Spark images) and job API; you keep Kubernetes in control.
- **Why**: **share one EKS cluster** between EMR and other container workloads, **improve utilization**, standardize on Kubernetes tools, run **different Spark versions** side by side, mix **EC2 and Fargate** compute, and use **Karpenter/Cluster Autoscaler** for nodes.
- **Concepts**:
  - **Virtual cluster**: a registered **EKS namespace** (and EKS cluster) where jobs run. **1 virtual cluster ↔ 1 namespace**. Create many per cluster for teams.
  - **Job run** (`StartJobRun`): spark-submit style job with **execution role**, release label, and driver/executor settings.
  - **Execution role**: an IAM role the job's pods assume through **IAM Roles for Service Accounts (IRSA)** or **EKS Pod Identity**; trust is set up by **`aws emr-containers update-role-trust-policy`** for the namespace's service account.
  - **Pod templates**: customize driver/executor pods (node selectors, tolerations, volumes, sidecars, resources).
  - **Job submitter pod** runs `spark-submit`; driver and executors are pods.
  - **Spark Operator / `spark-submit`** are also supported (**EMR containers Spark Operator**, YuniKorn/Volcano schedulers) **(verify)**.
- **Interfaces**: AWS CLI (`emr-containers`), SDK, **EMR Studio**, **Airflow/MWAA**, **Step Functions**.
- **Logs and monitoring**: S3 and CloudWatch Logs via `monitoringConfiguration`; **Spark History Server** via managed endpoints; **Prometheus/Grafana** on EKS; **CloudWatch Container Insights**.
- **Security**: **IRSA/Pod Identity** execution roles; **EKS security groups for pods**, **network policies**, **KMS for secrets/volumes**, **Lake Formation integration** (FGAC) in recent releases **(verify)**; **EKS access entries**/RBAC for the EMR service (`AWSServiceRoleForAmazonEMRContainers`).
- **Pricing**: EMR uplift **$0.007084 per vCPU-hour** and **$0.000777875 per GB-hour** (US East example), charged from **image download start to pod termination (per second)**; plus **$0.10/hour per EKS cluster**, plus **EC2/Fargate** costs for nodes/pods. Example: 100 vCPU + 300 GB for 30 minutes = **$0.4709** EMR uplift (excluding EKS/EC2).
- **Spot**: use **Spot node groups/Karpenter** with executors on Spot and the driver on On-Demand (node selectors).

## H. Choosing among the three EMR options (cheat sheet)
| Need | Pick |
|---|---|
| No cluster ops, bursty Spark/Hive, quick start | **EMR Serverless** |
| Already running EKS; many teams; mixed workloads | **EMR on EKS** |
| HBase/Presto/Flink/Hadoop, SSH, custom node setup, large steady fleets | **EMR on EC2** |
| Interactive science on big data | **EMR Studio** on any option |
| Cheapest at huge scale with deep tuning | **EMR on EC2 + Spot** |
| Smallest ETL with visual authoring and catalog crawlers | **Glue** (not EMR) |

## I. Troubleshooting (symptom → cause → fix)
- **Serverless job stays `PENDING`/queued** → account vCPU quota (16 default) or app **maximum capacity** reached → request increase, raise app max, reduce concurrency.
- **Job slow to start** → no pre-initialized capacity; worker image pulls (custom image) → add small initial capacity, slim the image.
- **Job fails: workers cannot reach S3/Glue in a VPC app** → missing endpoints/NAT → add VPC endpoints.
- **Unexpected cost** → pre-initialized workers left on, no `maxExecutors`, auto-stop off → cap and enable auto-stop.
- **`Insufficient memory` / executor lost** → undersized workers → increase `spark.executor.memory`/overhead via `StartJobRun` (not in script).
- **Wrong worker config ignored** → settings placed in script → move to `sparkSubmitParameters` or `configurationOverrides`.
- **Job cannot read S3 object** → runtime role lacks S3/KMS permission → fix role.
- **No logs** → no `monitoringConfiguration`, S3 bucket in another account/Region → configure same account/Region.
- **EKS job pods pending** → insufficient nodes/IPs, taints, quota → check Karpenter/CA, subnets, requests/limits.
- **EKS job cannot assume role** → trust policy not updated for service account → run the trust-policy update for the namespace.
- **API throttling on `StartJobRun`** → 1 TPS (burst 25) → batch submissions, use orchestrator retries.

## J. Scenarios: "If X → Y, because Z"
- If a company runs 200 small Spark jobs per day at random times → **EMR Serverless**, because it scales to zero between jobs and bills per second.
- If jobs must start within seconds for interactive analysis → **Serverless with a small pre-initialized capacity**, because warm workers avoid cold start (but cost while idle).
- If costs spike during a bad job → **application maximum capacity and `maxExecutors`**, because they cap resources.
- If a platform team already runs EKS for microservices and wants Spark there → **EMR on EKS**, because it shares nodes and uses Kubernetes tooling.
- If different teams need different Spark versions on shared infrastructure → **EMR on EKS virtual clusters or multiple Serverless applications**, because each has its own release label.
- If Spark needs a custom native library → **custom image (Serverless/EKS) or custom AMI (EC2)**, because the base image lacks it.
- If a Serverless job should reach a private RDS → **attach the application to your VPC with subnets/security groups**, because the default network cannot reach private resources.
- If you need Presto or HBase → **EMR on EC2**, because the other two options do not run them.
- If a team insists on no servers but needs Flink streaming → **Managed Flink**, because EMR Serverless covers Spark and Hive.

Verified from AWS docs on 2026-11-01 (EMR Serverless overview, pre-initialized capacity, Spark jobs configuration and defaults, endpoints and quotas, EMR on EKS overview, EMR pricing excerpt).
Unconfirmed (verify): Serverless engine list beyond Spark/Hive; default job timeout (12 h) and retry policy details; managed persistence retention; Graviton and custom image specifics; Lake Formation support on Serverless/EKS; interactive endpoint details; Spark Operator and scheduler support on EKS; worker size matrix; auto-raise behavior of quotas.

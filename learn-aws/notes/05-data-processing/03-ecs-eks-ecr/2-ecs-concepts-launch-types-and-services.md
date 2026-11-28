# ECS, EKS and ECR – 2. Amazon ECS: concepts, capacity and services

Short notes. Each point is a fact you can be asked about.

## A. Core concepts
- **Amazon ECS (Elastic Container Service)** = AWS's own **container orchestrator**. It decides where containers run, keeps the right number running, replaces failed ones, and wires them to load balancers, IAM, logs and service discovery.
- **No charge for ECS itself** (the control plane). You pay for the compute (EC2, Fargate, Managed Instances) and related resources.
- Building blocks:
  - **Cluster**: a logical group of capacity and services/tasks (one per environment or team is common).
  - **Task definition**: the **blueprint** (JSON) for 1–10 containers. Image, CPU/memory, ports, environment, secrets, roles, volumes, logging, network mode. **Versioned** as `family:revision`.
  - **Task**: a running instance of a task definition (one or more containers placed together).
  - **Service**: keeps **N tasks running** long-term. It replaces failed tasks, integrates with load balancers, auto scales and does deployments.
  - **Container instance**: an EC2 host registered to the cluster (runs the **ECS agent**).
  - **Capacity provider**: links the cluster to capacity (an Auto Scaling group, Fargate, Fargate Spot, Managed Instances) with scaling rules.
- **Two ways to run work**:
  - **Standalone tasks** (`RunTask`): run to completion and stop. Good for **batch/ETL jobs**, scheduled jobs and one-off migrations.
  - **Services**: long-running APIs, web apps, stream consumers (Kafka/Kinesis workers), Airflow components.
- ECS is regional. Tasks run across the AZs/subnets you give, and services spread tasks across AZs by default.

## B. Capacity options (launch types and capacity providers)
- **Fargate** (serverless):
  - No instances to manage. Each **task gets its own isolated micro-VM**, kernel and ENI.
  - Pay per **vCPU-second and GB-second** from image pull start to task stop (1-minute minimum).
  - CPU/memory from fixed combinations (0.25 vCPU / 0.5 GB up to **16 vCPU / 120 GB**; verify).
  - **Ephemeral storage 20 GiB default, up to 200 GiB**. Linux x86_64 and **ARM64 (Graviton)**, plus Windows.
  - No GPUs, no privileged containers, no custom AMIs, no daemon tasks.
  - Uses **platform versions** (Linux 1.4.0 latest; verify).
- **Fargate Spot**: Fargate at up to ~70% discount (verify). Tasks can be stopped with a **2-minute warning** (SIGTERM). For fault-tolerant tasks (batch, stateless workers).
- **EC2 launch type / Auto Scaling group capacity provider**:
  - You choose instance types/AMIs (ECS-optimized AMI, GPU AMI, Bottlerocket).
  - **Many tasks per instance (bin-packing)**, GPUs, large memory, custom kernels, daemon tasks, privileged containers.
  - You patch the AMIs. Pay for whole instances (On-Demand/Spot/Savings Plans).
- **ECS Managed Instances** (newer):
  - AWS **provisions, scales, patches and replaces** EC2 instances for ECS (Bottlerocket, AWS-managed AMI).
  - Choose default cost-optimized general-purpose types, or **attribute-based** requirements (vCPU, memory, **GPU/accelerators**, CPU maker).
  - **Multiple tasks per instance** (cheaper than one-task-per-VM Fargate), privileged Linux capabilities allowed.
  - **No SSH** (use ECS Exec), **no custom AMIs**. **Instances are drained and replaced after 14 days**, so tasks must tolerate that and >14-day tasks don't fit.
  - Billed for the EC2 instances (plus a management fee; verify). **Savings Plans apply**. Compatible with Fargate task definitions (platform 1.4.0). Set `requiresCompatibilities: MANAGED_INSTANCES`.
- **ECS Anywhere**: run ECS tasks on **on-premises/edge servers** (SSM-registered) managed from the ECS control plane. Per-instance hourly fee.
- **Capacity provider strategy**:
  - Per service/task, a list of providers with a **base** (minimum tasks on that provider) and a **weight** (ratio after base).
  - Example: base 2 on FARGATE, then weight 1 FARGATE : 3 FARGATE_SPOT → 2 guaranteed On-Demand tasks, the rest mostly Spot.
  - A strategy can only use **one type**: ASG providers, or Fargate/Fargate Spot, or Managed Instances (not mixed).
- **Cluster auto scaling (managed scaling)** for ASG capacity providers:
  - ECS scales the ASG to fit pending tasks using a **target capacity %** (100% = no spare; lower keeps headroom for fast starts).
  - **Managed termination protection** stops scale-in from killing instances that run tasks.
  - **Managed instance draining** moves tasks off instances before termination.

## C. Task definitions in detail
- **`requiresCompatibilities`**: `FARGATE`, `EC2`, `MANAGED_INSTANCES`, `EXTERNAL`.
- **CPU and memory**:
  - **Task-level** CPU/memory (required for Fargate) and **container-level** settings.
  - `memory` (hard limit; the container is **killed with exit 137** if it exceeds it) vs `memoryReservation` (soft, used for placement).
  - CPU is in units: 1024 = 1 vCPU.
- **Network modes**:
  - **`awsvpc`** (required for Fargate and Managed Instances; recommended): each task gets its **own ENI and private IP**, so **security groups per task**. ALB target type must be **`ip`**. Each task uses a subnet IP, so plan subnet size. ENI trunking raises ENIs per EC2 instance.
  - `bridge` (EC2): Docker virtual network with **dynamic host port mapping** (many tasks per host behind an ALB).
  - `host` (EC2/Managed Instances): the container uses the host's network directly (fastest, but ports conflict).
  - `none`.
- **Two IAM roles (very testable)**:
  - **Task execution role** (`executionRoleArn`): used **by ECS/agent** to **pull images from ECR**, **send logs** to CloudWatch, and **fetch secrets** (Secrets Manager / SSM) at task start. Managed policy `AmazonECSTaskExecutionRolePolicy`.
  - **Task role** (`taskRoleArn`): used **by your application code** inside the container to call AWS APIs (S3, DynamoDB, Glue…). **Least privilege per task definition**. Credentials are served at `169.254.170.2` through `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`.
  - On EC2, also the **container instance role** (`AmazonEC2ContainerServiceforEC2Role`) for the agent.
  - **Block tasks from using the instance role**: set `ECS_AWSVPC_BLOCK_IMDS` / IMDS hop limit on EC2 hosts, so tasks only use their task role.
- **Secrets**:
  - `secrets` → Secrets Manager ARN (optionally a JSON key and version) or SSM parameter ARN, injected as **environment variables at start** (needs the execution role).
  - Secrets are fetched only at task start. **Restart/redeploy to pick up rotated values**.
  - Never put secrets in `environment`, images or `command`.
- **Environment**: `environment` (key/values), `environmentFiles` (an `.env` file in S3).
- **Storage**:
  - **Bind mounts / ephemeral storage** (task scratch space).
  - **Amazon EFS** volumes (shared, persistent; access points + IAM auth + TLS in transit). Works on Fargate and EC2.
  - **Amazon EBS volumes attached to tasks** (one per task, configured at deploy; for databases or scratch needing block storage; verify Fargate support).
  - **FSx for Windows** (Windows tasks). Docker volumes (EC2).
- **Logging**:
  - **`awslogs`** driver → CloudWatch Logs (`awslogs-group`, `awslogs-stream-prefix`; `mode: non-blocking` to avoid app stalls).
  - **FireLens** (Fluent Bit sidecar) → S3, Firehose, OpenSearch, Datadog, Splunk.
- **Health checks**: a container `healthCheck` command (interval, retries, start period). An unhealthy essential container marks the task unhealthy and the service replaces it.
- **Essential containers and sidecars**: if an **essential** container stops, the whole task stops. Sidecars (log routers, proxies, agents) are often non-essential. `dependsOn` sets container start order (START, COMPLETE, SUCCESS, HEALTHY).
- **Other settings**:
  - `ulimits`, `linuxParameters` (init process, shared memory), `readonlyRootFilesystem`, `user` (non-root).
  - `stopTimeout` (graceful shutdown time; up to 120 s on Fargate).
  - `runtimePlatform` (OS / CPU architecture), `ephemeralStorage`.
  - `pidMode`/`ipcMode`, GPU `resourceRequirements` (EC2/Managed Instances).
- Max **10 containers per task definition** (verify). Task definition size limits apply.

## D. Running batch/ETL tasks on ECS
- **`RunTask`**: run N copies of a task definition (CLI/SDK), with **overrides** (command, environment, CPU/memory) per run. The task stops when the essential container exits. The exit code is in `DescribeTasks`.
- **Scheduled tasks**: **EventBridge Scheduler** (or EventBridge rules) with an ECS target: cron/rate, time zones, task count, network config. For example, run an ETL container nightly.
- **Step Functions**:
  - **`arn:aws:states:::ecs:runTask.sync`**: run a task and **wait for it to finish** (failure if the exit code is non-zero).
  - **`.waitForTaskToken`**: the container calls back with a token.
  - Pass inputs as container overrides.
- **MWAA / Airflow**: `EcsRunTaskOperator`.
- **Event-driven**: S3 → EventBridge → ECS task (input transformer passes the object key as an environment override).
- **ECS vs Batch for jobs**: plain ECS RunTask has **no queue, no retries, no priorities, no array jobs**. Use **AWS Batch** when you need those, or Step Functions for retries/flow.
- **ECS vs Lambda**: ECS tasks have no 15-minute limit, more CPU/memory/disk, and any runtime. They start slower (image pull, ENI).
- **Stream consumers as services**: a service with N tasks consuming Kinesis (KCL) or MSK, auto scaled on lag metrics.

## E. Services: load balancing, discovery and scaling
- **Desired count**: the service scheduler keeps it, replacing failed/unhealthy tasks and spreading across AZs.
- **Scheduling strategies**: **REPLICA** (N tasks; the default) or **DAEMON** (one task per EC2 instance, for agents; EC2 only).
- **Load balancers**:
  - **ALB** (HTTP/HTTPS, path/host routing, many tasks on dynamic ports or IPs).
  - **NLB** (TCP/UDP, static IPs, very high throughput).
  - GWLB (Managed Instances; verify).
  - Health checks on target groups. `healthCheckGracePeriodSeconds` gives slow-starting apps time.
- **Service discovery / connectivity**:
  - **ECS Service Connect** (recommended): service-to-service names, retries, metrics, built-in proxy, using Cloud Map namespaces.
  - **Cloud Map** DNS-based discovery.
  - **VPC Lattice** integration.
- **Service auto scaling** (Application Auto Scaling):
  - **Target tracking** (average CPU 60%, memory, ALB request count per target).
  - **Step scaling** (CloudWatch alarms, for example on SQS backlog or Kafka lag).
  - **Scheduled scaling** (more tasks at business hours, 0 at night for batch-like services).
  - **Predictive scaling** (verify for ECS).
  - Min/max task counts.
- **Scale to zero**: services can have desired count 0 (no compute cost on Fargate). Scale up on schedule or queue depth.
- **Task placement (EC2 only)**:
  - **Strategies**: **binpack** (fill instances by CPU/memory, the cheapest), **spread** (by AZ or instance, for availability), **random**. They can be combined, for example spread by AZ then binpack by memory.
  - **Constraints**: `distinctInstance` (one task per host), `memberOf` (Cluster Query Language, for example only `g5` instance types, or an attribute such as AZ).
  - Fargate handles placement automatically (spread across AZs).
- **Task protection**: protect tasks doing important work (a long job in a service) from scale-in termination.
- **ECS Exec**: `aws ecs execute-command` opens a shell in a running container (via SSM; needs task role SSM permissions and enabling on the service/task). Logged to CloudWatch/S3.

## F. Deployments
- **Rolling update** (ECS deployment controller, the default):
  - **`minimumHealthyPercent`** (default 100) and **`maximumPercent`** (default 200) control how many old/new tasks run during the update.
  - For example, min 50 / max 100 updates in place without extra capacity. Min 100 / max 200 starts new tasks before stopping old ones.
- **Deployment circuit breaker**: detects deployments whose tasks keep failing to reach steady state and **stops them**. With **rollback enabled** it reverts to the last working deployment. Turn it on for every service.
- **CloudWatch alarms in deployment config**: roll back if alarms fire during the deployment.
- **Native ECS blue/green** (2025+):
  - Runs blue and green revisions side by side, shifts traffic (ALB, NLB, Service Connect or VPC Lattice), keeps blue during **bake time**, and lets you roll back instantly.
  - **Lifecycle hooks** (Lambda or pause hooks) at stages like test traffic shift and production traffic shift.
  - **Linear** and **canary** variants (verify).
  - Temporarily doubles resources.
- **CodeDeploy blue/green** (`CODE_DEPLOY` controller): the older way. ECS canary/linear/all-at-once configs, test listener, AppSpec hooks. With NLB only all-at-once.
- **External controller**: a third-party tool manages deployments.
- **Deployment through CI/CD**: CodePipeline ECS (rolling) deploy action, CodeDeploy blue/green action, CloudFormation/CDK updates of the task definition + service, GitHub Actions `amazon-ecs-deploy-task-definition`.
- **Force new deployment** to restart tasks (for example, to pick up rotated secrets or a new image with the same tag; prefer new tags).

## G. Networking and data access for ECS tasks
- `awsvpc` tasks need **subnets and security groups** (`networkConfiguration`).
- **Private subnets + VPC endpoints** (ECR api/dkr, S3 gateway, CloudWatch Logs, Secrets Manager, SSM, ECS for EC2/Exec) or **NAT** for internet/AWS API access.
- Fargate in public subnets needs `assignPublicIp: ENABLED` to reach ECR without NAT (not recommended for production).
- Reach **RDS/Redshift/MSK** with security group references (DB SG allows the task SG).
- Read S3 with the **task role**. Use the **S3 gateway endpoint** for free, private, fast access.
- **IP exhaustion**: each awsvpc task uses one IP, so large Fargate fleets need big subnets (or IPv6).

## Scenarios (if → then, because)
- **If** a containerized extract-transform-load (ETL) job must run nightly with no servers, **then** run it as an Amazon Elastic Container Service (ECS) task on **AWS Fargate**, triggered by **Amazon EventBridge Scheduler**. **This works because** Fargate runs each task in its own micro-VM with no instances to manage, billed per second (1-minute minimum) only while it runs. EventBridge Scheduler starts the task on a cron or rate schedule, with time zones, task count and network settings. The task stops when its essential container exits.
- **If** a workflow must run a container step and wait for its result, **then** use **AWS Step Functions** with the `ecs:runTask.sync` integration. **This works because** `.sync` starts the Amazon Elastic Container Service (ECS) task and waits until it finishes, failing the step if the exit code is non-zero. Inputs are passed as container overrides.
- **If** thousands of queued jobs need retries, priorities and array fan-out, **then** use **AWS Batch** on top of Amazon Elastic Container Service (ECS), not raw `RunTask`. **This works because** plain ECS `RunTask` has **no queue, no retries, no priorities and no array jobs**. Batch adds a job queue and scheduler on top of ECS, with array jobs, retries and Spot.
- **If** an always-on Kafka or Kinesis consumer must scale with lag, **then** run it as an Amazon Elastic Container Service (ECS) **service** with **step scaling** on the lag metric. **This works because** a service keeps N tasks running long-term and replaces failed ones, and step scaling (Application Auto Scaling) adds or removes tasks when Amazon CloudWatch alarms on the lag fire. Min and max task counts set the limits.
- **If** the app code needs Amazon S3 read access, **then** put the permission in the **task role**, not the execution role or the instance role. **This works because** the task role is the Identity and Access Management (IAM) role your code uses inside the container to call AWS APIs, with least privilege per task definition. The **task execution role** is only for Amazon Elastic Container Service (ECS) itself (pull images, send logs, fetch secrets), and the instance role is shared by every task on the host.
- **If** tasks fail to start because secrets can't be fetched or images can't be pulled, **then** fix the **task execution role** (Amazon Elastic Container Registry (ECR), AWS Secrets Manager and AWS Key Management Service (KMS) permissions) and the network endpoints. **This works because** Amazon Elastic Container Service (ECS) uses the execution role at task start to pull the image and fetch secrets. If that role lacks permissions, or the task has no route (VPC endpoints or NAT) to those services, the task never starts.
- **If** a database password was rotated in **AWS Secrets Manager** but tasks still use the old one, **then** **force a new deployment** of the service. **This works because** Amazon Elastic Container Service (ECS) injects secrets as environment variables only **at task start**, so running tasks keep the old value until they are replaced.
- **If** a GPU inference service must run on Amazon Elastic Container Service (ECS) without managing AMIs or patching, **then** use **ECS Managed Instances** with a **GPU/accelerator attribute**. **This works because** with Managed Instances AWS provisions, scales, patches and replaces the EC2 instances (Bottlerocket, AWS-managed AMI), and attribute-based selection can ask for GPUs, while **AWS Fargate** has no GPUs. The catch: no SSH, no custom AMIs, and instances are drained and replaced after **14 days**.
- **If** many small tasks should share instances for lower cost, **then** use **EC2** or **ECS Managed Instances** capacity with **binpack** placement. **This works because** both run many tasks per instance, and binpack fills each instance by CPU/memory before using the next, which is the cheapest placement strategy. Fargate, by contrast, gives every task its own micro-VM.
- **If** workers must survive interruptions cheaply, **then** use **Fargate Spot** (or EC2 Spot) and keep a few On-Demand tasks with the capacity provider **base** and **weight**. **This works because** Spot is much cheaper (Fargate Spot up to ~70% off; verify) but tasks can be stopped with a **2-minute warning** (SIGTERM). For example, base 2 on FARGATE, then weight 1 FARGATE : 3 FARGATE_SPOT, keeps 2 On-Demand tasks always running and puts the rest mostly on Spot.
- **If** tasks on EC2 must spread across Availability Zones (AZs) for availability, **then** use the **spread** placement strategy on `attribute:ecs.availability-zone`. **This works because** spread places tasks evenly across AZs, so one AZ failure doesn't stop every task. It can be combined with binpack, for example spread by AZ then binpack by memory. Fargate spreads across AZs automatically.
- **If** a bad release keeps crashing tasks, **then** turn on the deployment **circuit breaker with rollback**. **This works because** the circuit breaker detects a deployment whose tasks keep failing to reach steady state, stops it, and with rollback reverts to the last working deployment. Turn it on for every service.
- **If** a new version must be checked with test traffic before switching, **then** use Amazon Elastic Container Service (ECS) native **blue/green** deployment with **lifecycle hooks** and **bake time**. **This works because** blue (old) and green (new) run side by side, hooks (AWS Lambda or pause hooks) run at stages like the test traffic shift, and blue is kept during bake time so you can roll back instantly. The catch: it temporarily doubles resources.
- **If** services need to call each other by name with retries and metrics, **then** use **ECS Service Connect**. **This works because** Service Connect gives service-to-service names using AWS Cloud Map namespaces and adds a built-in proxy with retries and metrics, so apps need no discovery code of their own.
- **If** a container exits with code **137**, **then** it exceeded its **memory hard limit** and was killed (out of memory, OOM): raise memory or fix the app's usage. **This works because** `memory` is a hard limit and the container is killed when it goes over, while `memoryReservation` is only a soft value used for placement.
- **If** you need a shell inside a running Fargate task to debug, **then** use **ECS Exec** (`aws ecs execute-command`). **This works because** ECS Exec opens a shell through AWS Systems Manager (SSM), with no SSH. It must be enabled on the service or task, the task role needs SSM permissions, and sessions are logged to CloudWatch or S3.
- **If** a simple web API must go live from an image with a URL and an Application Load Balancer (ALB) in minutes, **then** use **ECS Express Mode**. **This works because** Express Mode needs just the image and sets up the ALB, URL, networking and auto scaling for you at no extra charge. Up to 25 services can share one ALB.
- **If** on-premises servers must run the same containers, managed centrally, **then** use **ECS Anywhere**. **This works because** it registers your own servers through AWS Systems Manager (SSM) and runs Amazon Elastic Container Service (ECS) tasks on them from the same ECS control plane, for a per-instance hourly fee.
- **If** a Fargate fleet stops scaling with "insufficient IPs", **then** use bigger subnets or add more subnets. **This works because** the `awsvpc` network mode gives every task its own network interface (ENI) and private IP from the subnet, so a large fleet can use up all free IPs. IPv6 is another way out.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: ECS Managed Instances (attribute-based selection, Bottlerocket, multi-task placement, 14-day instance lifetime, no SSH, no custom AMIs, privileged capabilities, awsvpc/host networking, EBS data volume 30–16,384 GiB default 80, instance store option, Savings Plans apply, capacity provider strategy single type), ECS native blue/green terms (bake time, lifecycle hooks incl. pause hooks, ALB/NLB/Service Connect/VPC Lattice, NLB extra 10 minutes), ECS Express Mode announcement.
Not confirmed (verify): Fargate size and storage maxima, Fargate Spot discount, latest platform version, Managed Instances management fee, task EBS volumes on Fargate, max containers per task definition, GWLB support, predictive scaling for ECS, native linear/canary variants, deployment defaults (min 100 / max 200 from general knowledge).

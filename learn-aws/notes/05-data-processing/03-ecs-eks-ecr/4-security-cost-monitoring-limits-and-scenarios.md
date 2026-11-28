# ECS, EKS and ECR – 4. Security, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Security: identity and access
- **One role per workload**:
  - ECS **task role** / EKS **Pod Identity or IRSA** role, each scoped to exactly the buckets, tables and keys the app needs.
  - Never rely on the EC2 **instance/node role** for app permissions.
  - Block container access to IMDS: IMDSv2 with hop limit 1; on ECS `ECS_AWSVPC_BLOCK_IMDS`.
- **ECS execution role vs task role**:
  - Execution role = **platform** actions: pull from ECR, write logs, fetch secrets at start.
  - Task role = **application** actions.
  - Missing ECR/secret permissions → the task never starts. Missing app permissions → AccessDenied inside the code.
- **Who can deploy/run**:
  - IAM on `ecs:RunTask`/`UpdateService`/`RegisterTaskDefinition`.
  - **`iam:PassRole`** is needed to pass task/execution roles. Restrict which roles can be passed.
  - EKS **access entries / RBAC** for cluster users.
- **Least privilege for CI/CD**: separate deploy roles per environment, approvals for prod.
- **ECR access**: repository policies (cross-account, org condition) + IAM pull/push permissions. Separate push (CI) from pull (runtime) roles.
- **Kubernetes RBAC**: namespaces per team, Role/RoleBinding with minimum verbs. Avoid `cluster-admin` for apps. Service accounts per app.

## B. Security: secrets and data protection
- **Secrets**:
  - **Secrets Manager / SSM Parameter Store** referenced in ECS task definitions (`secrets`) or mounted on EKS via **Secrets Store CSI + ASCP**, or synced with External Secrets.
  - Rotate in Secrets Manager. ECS needs a **task restart** to pick up new values. The CSI driver can sync rotation.
  - **Never** put secrets in images, environment variables in plain text, Git or Helm values.
- **Encryption at rest**:
  - ECR repos (AES-256 or KMS).
  - EBS volumes (nodes, task volumes) with KMS.
  - EFS with KMS.
  - Fargate ephemeral storage (encrypted by default; CMK option for ECS; verify).
  - **EKS Kubernetes Secrets envelope encryption with a KMS key**.
  - CloudWatch Logs with KMS.
- **Encryption in transit**:
  - TLS on load balancers (ACM certificates).
  - **Service Connect** / service mesh mTLS (Service Connect TLS with ACM Private CA; VPC Lattice).
  - EFS mount with TLS. Databases with SSL.
- **Data access paths**: S3 via the gateway endpoint plus bucket policies with `aws:SourceVpce`. RDS via security groups and IAM auth or Secrets Manager.

## C. Security: network and runtime
- **Network isolation**:
  - Tasks/pods in **private subnets**.
  - **Security groups per task** (awsvpc) or per pod (Security Groups for Pods).
  - Kubernetes **NetworkPolicies** for pod-to-pod rules.
  - **VPC endpoints** instead of internet access (ECR api/dkr, S3, Logs, Secrets Manager, STS, ECS, EKS Auth).
- **Image security**:
  - ECR **enhanced scanning** (Inspector, continuous) and fail builds on critical CVEs.
  - **Immutable tags/digests**, image signing (Signer/Notation) + admission control (EKS: Kyverno/OPA Gatekeeper).
  - Minimal base images, non-root `USER`, `readOnlyRootFilesystem`, no privileged containers, drop Linux capabilities.
- **Runtime threat detection**: **Amazon GuardDuty Runtime Monitoring** for **ECS (incl. Fargate)**, **EKS** and EC2 (agent detects crypto-mining, reverse shells, privilege escalation). **GuardDuty EKS Protection** analyzes K8s **audit logs**.
- **Pod security**: Kubernetes **Pod Security Standards** (restricted/baseline) through Pod Security Admission. Policy engines block privileged pods and hostPath.
- **Audit**:
  - **CloudTrail** records ECS/EKS/ECR API calls (who deployed, who pulled; ECR pulls are data plane events, verify).
  - **EKS control plane logs** (api, audit, authenticator, controllerManager, scheduler) to CloudWatch Logs. Turn on **audit** logs for security.
  - **AWS Config** rules (for example `ecs-task-definition-user-for-host-mode-check`, `ecs-containers-nonprivileged`, `eks-secrets-encrypted`, `eks-endpoint-no-public-access`).
  - **Security Hub** controls aggregate findings.

## D. Cost: what you pay for
- **ECS control plane: free**. **EKS: $0.10/h per cluster** (standard support), **$0.60/h in extended support**, plus Provisioned Control Plane tiers if used.
- **Compute**:
  - **Fargate**: per vCPU-hour + GB-hour (per second, 1-minute minimum), plus ephemeral storage above 20 GiB. **Fargate Spot** is much cheaper.
  - **ARM64 (Graviton) Fargate is about 20% cheaper** than x86 (verify).
  - **EC2**: per instance (On-Demand/Spot/Savings Plans/RIs). **ECS Managed Instances**: EC2 price + management fee (verify). **EKS Auto Mode**: EC2 + per-instance management fee.
- **Other**:
  - Load balancers (ALB/NLB hourly + LCU/NLCU).
  - **NAT gateway** (hourly + per-GB, for image pulls and API calls).
  - VPC interface endpoints (hourly + per-GB).
  - Public IPv4 addresses (Fargate tasks with public IPs).
  - **CloudWatch Logs ingestion** (often large), Container Insights metrics.
  - ECR storage and cross-Region transfer.
  - Cross-AZ data transfer between services.
  - EMR on EKS per vCPU/GB uplift.
- **Savings Plans**: **Compute Savings Plans cover Fargate (ECS and EKS)** and EC2. They are the best commitment option for steady container usage.

## E. Cost optimization levers
- **Right-size** task/pod CPU and memory. **Over-requesting** is the biggest waste. Use Compute Optimizer recommendations (ECS on Fargate; verify EKS), VPA or Container Insights utilization.
- **Spot**: Fargate Spot for ECS, Spot node pools with Karpenter on EKS, Spot capacity providers. Keep a small On-Demand base (capacity provider base / Karpenter weights) for availability.
- **Graviton (arm64)** images for 20–40% better price/performance (verify).
- **Bin-packing**: EC2/Managed Instances with binpack placement. Karpenter **consolidation** removes underused nodes.
- **Scale to zero**: scheduled scaling to 0 for non-24/7 services. Batch-like work as tasks/Jobs instead of always-on services.
- **Fargate vs EC2**:
  - **Fargate**: simplest, per-task billing, no idle node waste, but a higher unit price.
  - **EC2/Managed Instances**: cheaper at high, steady utilization with good bin-packing and Savings Plans/Spot.
- **EKS-specific**:
  - Fewer, shared clusters (each costs $73+/month). **Stay on standard-support versions** (avoid the $0.50/h extended-support uplift).
  - Use Auto Mode only if the management fee is worth the saved effort.
- **Network**:
  - **S3 gateway endpoints** (free) instead of NAT for S3 traffic. ECR endpoints instead of NAT for heavy pulls.
  - Keep chatty services in the same AZ when possible (cross-AZ charges). Smaller images.
- **Logs**: set retention, filter noisy logs, use infrequent-access log classes (verify), sample debug logs.
- **Tagging**: propagate tags to tasks (`propagateTags`), use cost allocation tags. **Split cost allocation data** for ECS/EKS shows per-task/pod cost in CUR (verify).

## F. Monitoring and logging
- **CloudWatch Container Insights**:
  - Cluster/service/task (ECS) and node/pod/container (EKS) **CPU, memory, network, storage**, restarts, task counts.
  - **Enhanced observability** gives per-container detail and curated dashboards (verify naming).
  - EKS via the **CloudWatch Observability add-on**. ECS by enabling it on the cluster/account.
- **ECS service metrics** (free, `AWS/ECS`): `CPUUtilization`, `MemoryUtilization` per service/cluster. Used for target tracking. `RunningTaskCount` etc. come via Container Insights (verify).
- **Logs**:
  - ECS: **awslogs** → CloudWatch Logs, or **FireLens/Fluent Bit** → S3/Firehose/OpenSearch/third parties.
  - EKS: Fluent Bit DaemonSet (via the CloudWatch Observability add-on) → CloudWatch Logs.
  - EKS **control plane logs** must be enabled per log type.
- **Prometheus/Grafana**: **Amazon Managed Service for Prometheus** (scrape K8s/ECS metrics, PromQL) + **Amazon Managed Grafana** dashboards. Standard on EKS.
- **Tracing**: **AWS Distro for OpenTelemetry (ADOT)** → X-Ray / CloudWatch Application Signals.
- **Events**:
  - **ECS events to EventBridge**: task state change (RUNNING/STOPPED with `stoppedReason`), service actions, deployment state changes (completed/failed/rollback), container instance changes.
  - Route to SNS/Lambda for alerts (for example "ETL task stopped with exit code 1").
  - EKS: Kubernetes events (`kubectl get events`), plus EventBridge for EKS API/cluster events (verify).
- **Alarms**: service CPU/memory, ALB 5xx/latency/unhealthy hosts, task restarts, pending pods, Kafka/Kinesis consumer lag, IP availability in subnets.
- **CloudTrail**: who changed services, task definitions, clusters, repositories, IAM roles.

## G. Troubleshooting (symptom → cause → fix)
- **ECS task stuck in PROVISIONING/PENDING** → no capacity (EC2 cluster full, ASG at max, capacity provider not scaling), insufficient IPs in subnets (awsvpc), Fargate capacity in that AZ, or ENI limits on EC2. Fix: more subnets/IPs, managed scaling, more AZs, ENI trunking.
- **`CannotPullContainerError`** → wrong image/tag, no ECR permissions (execution/node role), no route to ECR/S3 (private subnet without NAT/endpoints, Fargate without a public IP or NAT), Docker Hub rate limit, or a cross-account repository policy/KMS issue.
- **`ResourceInitializationError` (Fargate)** → can't fetch secrets (execution role lacks `secretsmanager:GetSecretValue`/`kms:Decrypt`), can't reach Secrets Manager/SSM/Logs endpoints, or a bad log group config.
- **Task stops with exit code 137 / `OutOfMemoryError`** → the memory hard limit was exceeded. Raise task/container memory or fix the leak. EKS: **OOMKilled**, so raise limits/requests.
- **Exit code 1/2** → application error. Read CloudWatch Logs (log group/stream from the task definition).
- **Exit code 139** → segfault. **143** → SIGTERM (stopped by scale-in, deployment, Spot interruption). Handle SIGTERM gracefully within `stopTimeout`.
- **Service keeps restarting tasks / deployment never completes** → container health check failing, ALB health check path/port wrong, grace period too short, app crashing at start. The **circuit breaker** rolls back. Check `stoppedReason` and logs.
- **Tasks register but ALB shows unhealthy** → security group doesn't allow ALB → task port, wrong target type (must be `ip` for awsvpc), wrong health check path.
- **AccessDenied inside the app** → the task role/pod role is missing or lacks the permission. Or the pod uses the node role because the service account isn't associated/annotated. Or a KMS/bucket policy denies it.
- **EKS pod Pending** → insufficient CPU/memory on nodes (Karpenter/Cluster Autoscaler not scaling, NodePool limits), taints without tolerations, node selector mismatch, PVC can't bind (EBS volume in another AZ), or IP exhaustion.
- **EKS pod `ImagePullBackOff` / `ErrImagePull`** → the same causes as ECS pull errors (node role ECR permissions, endpoints, tag).
- **EKS pod `CrashLoopBackOff`** → the app keeps crashing. Check `kubectl logs --previous` and liveness probe settings.
- **"failed to assign an IP address to container" (EKS)** → VPC CNI out of IPs. Use prefix delegation, a secondary CIDR, larger subnets or IPv6.
- **`kubectl` "Unauthorized" / "You must be logged in"** → the IAM principal has no **access entry** (or aws-auth mapping), or an expired/wrong AWS profile. Add an access entry with a policy.
- **Pod can't get AWS credentials with Pod Identity** → agent add-on not installed, no association for that namespace/service account, pod on Fargate (unsupported), old SDK, or a proxy blocking `169.254.170.23` (add to `NO_PROXY`).
- **Fargate Spot tasks disappear** → interruptions (2-minute SIGTERM). Use a base of On-Demand tasks, graceful shutdown and retries.
- **Costs jumped on EKS** → extended-support version, idle nodes (no consolidation), large NAT/log charges.

## H. Limits and numbers to remember
| Item | Value |
|---|---|
| ECS control plane price | Free |
| EKS cluster price | $0.10/h standard; $0.60/h extended support |
| EKS version support | 14 months standard + 12 months extended |
| Fargate task size | up to 16 vCPU / 120 GB (verify) |
| Fargate ephemeral storage | 20 GiB default, up to 200 GiB |
| Fargate billing | per second, 1-minute minimum |
| Fargate Spot / EC2 Spot warning | 2 minutes (SIGTERM) |
| ECS Managed Instances lifetime | instances drained and replaced after 14 days |
| Managed Instances data volume | 30–16,384 GiB (default 80 GiB) |
| ECS task containers | up to 10 per task definition (verify) |
| ECS rolling defaults | minimumHealthyPercent 100, maximumPercent 200 |
| ECR auth token | valid 12 hours |
| ECR max layer size | 52,000 MiB |
| ECR images per repository | 100,000 (adjustable) |
| ECR lifecycle rules | 50 per policy |
| ECR replication | 25 rules, 25 destinations |
| ECR pull-through cache rules | 50 per registry |
| ECR basic scans | 1 per image per 24 h; 100,000 per day |
| ECS Express Mode | up to 25 services per ALB; no extra charge |
| EKS Pod Identity associations | 5,000 per cluster |
| Pods per EKS node | set by ENIs × IPs (raise with prefix delegation) |
| App Runner | closed to new customers since 30 April 2026 |

## I. Final scenario set (if → then, because)
- **If** a data team needs to run containerized Python extract-transform-load (ETL) jobs nightly with the least operations, **then** use Amazon Elastic Container Service (ECS) on **AWS Fargate**, started by **Amazon EventBridge Scheduler** (or **AWS Step Functions** `runTask.sync`). **This works because** the ECS control plane is free and Fargate has no servers to manage; you pay per vCPU and GB, per second, only while the job runs. Step Functions can also wait for the task to finish.
- **If** those jobs need queues, retries and array fan-out, **then** use **AWS Batch** (on Amazon Elastic Container Service (ECS) with Fargate, or EC2). **This works because** plain ECS `RunTask` has no queue, retries or array jobs, and Batch adds a job queue and scheduler on top.
- **If** the company standard is Kubernetes and teams use Helm and operators, **then** use **Amazon Elastic Kubernetes Service (EKS)**, and consider **EKS Auto Mode** to cut node management. **This works because** EKS is managed Kubernetes, so existing Helm charts and operators work, while Auto Mode lets AWS run nodes, patching and core add-ons for an extra per-instance fee. Each cluster costs **$0.10 per hour**.
- **If** Spark must run on the existing Amazon Elastic Kubernetes Service (EKS) cluster, **then** use **Amazon EMR on EKS**, with **Karpenter** and **Spot** for the executors. **This works because** EMR on EKS runs Spark with EMR's runtime on the cluster's shared capacity, and Karpenter launches cheap Spot nodes for executors and handles Spot interruptions.
- **If** container compute costs are too high for steady workloads, **then** combine **Compute Savings Plans**, **right-sizing**, **Graviton** and **Spot** for the parts that tolerate interruption. **This works because** Compute Savings Plans cover Fargate (ECS and EKS) and EC2, over-requesting CPU/memory is the biggest waste, Graviton (arm64) gives about 20–40% better price/performance (verify), and Spot is much cheaper but can stop with a 2-minute warning.
- **If** many small tasks waste money on Fargate's per-task pricing, **then** use **EC2** or **ECS Managed Instances** with **bin-packing**. **This works because** both run many tasks per instance and binpack fills each one before using the next. Fargate has the simplest, per-task billing but a higher unit price, while EC2 is cheaper at high, steady use. Managed Instances add a management fee on top of EC2 (verify).
- **If** tasks or pods in private subnets must pull images without internet access, **then** add the Amazon Elastic Container Registry (ECR) `api` and `dkr` **interface endpoints**, an **S3 gateway endpoint**, and a **CloudWatch Logs** endpoint. **This works because** these VPC endpoints give a private route to ECR, and image layers are served from Amazon S3. Without them (and without NAT), pulls fail with `CannotPullContainerError`.
- **If** the app inside a container needs DynamoDB access, **then** use an Amazon Elastic Container Service (ECS) **task role**, or on EKS a **Pod Identity** role (**IRSA** on Fargate), with least privilege. **This works because** each workload gets its own Identity and Access Management (IAM) role scoped to just the tables it needs, instead of the shared instance/node role. Pod Identity is not supported on Fargate, so Fargate pods use IAM Roles for Service Accounts (IRSA).
- **If** a task can't start because a secret can't be read, **then** fix the **task execution role** permission (`secretsmanager:GetSecretValue`, plus `kms:Decrypt`) and the **Secrets Manager endpoint**. **This works because** the execution role fetches secrets at task start. If it lacks permission or can't reach AWS Secrets Manager, the task never starts (on Fargate it shows `ResourceInitializationError`).
- **If** security wants detection of malicious activity inside running containers, **then** turn on **Amazon GuardDuty Runtime Monitoring** (Amazon Elastic Container Service (ECS) including Fargate, and EKS). **This works because** its agent watches the running containers and detects crypto-mining, reverse shells and privilege escalation. GuardDuty EKS Protection also analyzes Kubernetes audit logs.
- **If** images must be scanned continuously for new CVEs in OS and Python packages, **then** use Amazon Elastic Container Registry (ECR) **enhanced scanning** with **Amazon Inspector**. **This works because** enhanced scanning covers OS and language packages (pip, npm, Maven) and rescans when new vulnerabilities (CVEs) are published. Free basic scanning checks only OS packages.
- **If** deployments must roll back automatically when new tasks fail, **then** turn on the Amazon Elastic Container Service (ECS) deployment **circuit breaker with rollback** (or blue/green with CloudWatch alarms). **This works because** the circuit breaker detects tasks that keep failing to reach steady state, stops the deployment and reverts to the last working one. Alarms in the deployment config can also trigger a rollback.
- **If** a new version must take test traffic first, **then** use Amazon Elastic Container Service (ECS) native **blue/green** with **lifecycle hooks** (or the older AWS CodeDeploy blue/green). **This works because** old and new versions run side by side, hooks run at the test and production traffic shifts, and the old version is kept during bake time for instant rollback. It temporarily doubles resources.
- **If** you need per-container CPU and memory dashboards, **then** use **Amazon CloudWatch Container Insights** with **enhanced observability**. **This works because** Container Insights collects CPU, memory, network and storage for ECS tasks and EKS pods, and enhanced observability adds per-container detail and curated dashboards (verify naming).
- **If** you need PromQL metrics and Grafana dashboards for Amazon Elastic Kubernetes Service (EKS), **then** use **Amazon Managed Service for Prometheus** with **Amazon Managed Grafana**. **This works because** Managed Prometheus scrapes Kubernetes metrics and answers PromQL queries without you running Prometheus, and Managed Grafana hosts the dashboards. This is the standard setup on EKS.
- **If** an Amazon Elastic Kubernetes Service (EKS) cluster runs an old version and its control plane costs **6×** more, **then** upgrade it out of **extended support**. **This works because** a version gets 14 months of standard support at **$0.10/h**, then 12 months of extended support at **$0.60/h** per cluster. Staying on standard-support versions avoids the $0.50/h uplift.
- **If** a Fargate fleet can't scale because it runs out of IPs, **then** use bigger or more subnets; on EKS use **prefix delegation**, **custom networking** (secondary CIDR) or **IPv6**. **This works because** each `awsvpc` task, and each EKS pod with the VPC CNI, takes one IP from the subnet, so large fleets exhaust small subnets.
- **If** a team wants a web API live from an image with minimal setup, **then** use **ECS Express Mode**. **This works because** it needs only the image and sets up the Application Load Balancer (ALB), URL and auto scaling at no extra charge. **AWS App Runner** closed to new customers on **30 April 2026**, so it is not an option for new teams.
- **If** an exam question says "optimize container usage", **then** right-size requests, pick Fargate vs EC2 correctly, use Spot and Graviton, autoscale and bin-pack, and keep images small and close (Amazon Elastic Container Registry (ECR) in the same Region). **This works because** over-requested CPU/memory is the biggest waste, bin-packing and scale-to-zero remove idle capacity, Spot and Graviton lower prices, and small nearby images pull faster with less transfer cost.

## Verified from AWS docs on 2026-10-11
Read from current sources: EKS pricing and support windows, EKS Pod Identity limits, ECS Managed Instances details, ECS native blue/green basics, ECR quotas, App Runner closure (30 April 2026) and ECS Express Mode.
Not confirmed (verify): Fargate ephemeral storage CMK option, ECR pull CloudTrail event type, Config rule names, Fargate Graviton discount, Managed Instances management fee, Compute Optimizer coverage for EKS, log class names, split cost allocation data, Container Insights enhanced observability naming and ECS metric names, EKS EventBridge events, Fargate maximum size, ECS containers per task definition.

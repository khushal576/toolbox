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
- If a data team needs to run containerized Python ETL jobs nightly with least ops → ECS on **Fargate** with EventBridge Scheduler (or Step Functions `runTask.sync`).
- If those jobs need queues, retries and array fan-out → AWS Batch (on ECS/Fargate or EC2).
- If the company standard is Kubernetes and teams use Helm/operators → EKS (consider **Auto Mode** to cut node management).
- If Spark must run on the existing EKS cluster → **EMR on EKS** (with Karpenter + Spot executors).
- If container compute costs are too high for steady workloads → Compute Savings Plans + right-sizing + Graviton + Spot for tolerant parts.
- If many small tasks waste money on Fargate's per-task pricing → EC2 or **ECS Managed Instances** with bin-packing.
- If tasks/pods in private subnets must pull images without internet → ECR api/dkr interface endpoints + S3 gateway endpoint (+ Logs endpoint).
- If the app inside a container needs DynamoDB access → ECS **task role** / EKS **Pod Identity** (IRSA on Fargate) with least privilege.
- If a task can't start because a secret can't be read → **execution role** permission (+ KMS) and Secrets Manager endpoint.
- If security wants detection of malicious activity inside running containers → **GuardDuty Runtime Monitoring** (ECS incl. Fargate, EKS).
- If images must be continuously scanned for new CVEs in OS and Python packages → ECR **enhanced scanning** (Inspector).
- If deployments must roll back automatically when new tasks fail → ECS deployment **circuit breaker with rollback** (or blue/green with alarms).
- If a new version must take test traffic first → ECS native **blue/green** with lifecycle hooks (or CodeDeploy).
- If you need per-container CPU/memory dashboards → **Container Insights** (enhanced observability).
- If you need PromQL metrics and Grafana dashboards for EKS → Amazon Managed Service for Prometheus + Amazon Managed Grafana.
- If an EKS cluster runs an old version and costs 6× more for the control plane → upgrade out of **extended support**.
- If a Fargate fleet can't scale due to IPs → bigger/more subnets. On EKS: prefix delegation / custom networking / IPv6.
- If a team wants a web API live from an image with minimal setup → **ECS Express Mode** (App Runner is closed to new customers).
- If an exam question says "optimize container usage" → right-size requests, pick Fargate vs EC2 correctly, use Spot/Graviton, autoscale and bin-pack, keep images small and close (ECR in-Region).

## Verified from AWS docs on 2026-10-11
Read from current sources: EKS pricing and support windows, EKS Pod Identity limits, ECS Managed Instances details, ECS native blue/green basics, ECR quotas, App Runner closure (30 April 2026) and ECS Express Mode.
Not confirmed (verify): Fargate ephemeral storage CMK option, ECR pull CloudTrail event type, Config rule names, Fargate Graviton discount, Managed Instances management fee, Compute Optimizer coverage for EKS, log class names, split cost allocation data, Container Insights enhanced observability naming and ECS metric names, EKS EventBridge events, Fargate maximum size, ECS containers per task definition.

# ECS, EKS and ECR – 3. Amazon EKS: Kubernetes on AWS

Short notes. Each point is a fact you can be asked about.

## A. Kubernetes basics you need for AWS questions
- **Kubernetes (K8s)** = an open-source container orchestrator. You declare the desired state in YAML **manifests**, and controllers keep reality matching it.
- **Cluster** = **control plane** (API server, etcd database, scheduler, controllers) + **data plane** (worker **nodes** running **kubelet** and a container runtime).
- **Pod**: the smallest unit; one or more containers sharing network and storage. Pods are disposable.
- **Deployment**: keeps N **replicas** of a pod running and does rolling updates (like an ECS service).
- **StatefulSet**: pods with stable names and per-pod storage (databases, Kafka, ZooKeeper).
- **DaemonSet**: one pod per node (log agents, monitoring, CNI).
- **Job**: runs pods **to completion** (batch/ETL). **CronJob**: runs Jobs on a schedule (like cron).
- **Service**: a stable virtual IP/DNS name for a set of pods (ClusterIP, NodePort, LoadBalancer).
- **Ingress / Gateway API**: HTTP routing into the cluster (with the AWS Load Balancer Controller → ALB).
- **Namespace**: a logical partition (per team/environment) for names, quotas and RBAC.
- **ConfigMap** (config) and **Secret** (sensitive values; only base64 by default, so **encrypt** them with KMS on EKS).
- **ServiceAccount**: the identity of pods inside K8s. On EKS it maps to an **IAM role** (IRSA / Pod Identity).
- **RBAC**: Roles/ClusterRoles + bindings control what users and service accounts can do in the K8s API.
- **Resource requests and limits**:
  - **Requests** = guaranteed CPU/memory used for scheduling. **Limits** = the cap.
  - Exceeding the memory limit → **OOMKilled**. CPU above the limit is throttled.
  - Right-sized requests = good bin-packing = lower cost.
- **Scheduling tools**: node selectors/affinity, **taints and tolerations** (keep GPU or Spot nodes for specific pods), topology spread constraints (spread across AZs).
- **Autoscaling layers**:
  - **HPA** (Horizontal Pod Autoscaler: more pods on CPU/custom metrics).
  - **VPA** (right-size pod requests).
  - **Node autoscaling** (Cluster Autoscaler or **Karpenter**: add/remove nodes).
  - **KEDA** (event-driven scaling, for example on SQS depth or Kafka lag).
- **Helm** = the package manager (charts) to install apps (Spark operator, Airflow, Prometheus). `kubectl` = the CLI to talk to the API server.

## B. What Amazon EKS is
- **Amazon EKS (Elastic Kubernetes Service)** = **managed Kubernetes control plane**:
  - AWS runs the API servers and etcd across **3 AZs**, patches them and scales them. It is **upstream-conformant** Kubernetes.
  - You choose how to run the **data plane** (nodes).
- **Pricing** (per cluster, us-east-1):
  - **$0.10 per hour in standard support** (~$73/month).
  - **$0.60 per hour in extended support** (standard + $0.50).
  - **Provisioned Control Plane** tiers for very large clusters add a higher hourly fee (XL $1.65/h up to 8XL $13.90/h).
  - Plus nodes (EC2/Fargate), EBS, load balancers, NAT, logs.
- **Kubernetes versions**:
  - Each version gets **14 months of standard support**, then **12 months of extended support** (at the higher price).
  - After that, EKS **auto-upgrades** the control plane (verify).
  - Upgrade one minor version at a time: control plane first, then nodes and add-ons.
  - **Upgrade insights** flag deprecated APIs.
- Pick EKS when:
  - The team already uses Kubernetes, or needs portability (multi-cloud/on-prem with **EKS Anywhere / Hybrid Nodes**).
  - You want the K8s ecosystem (Spark operator, Kubeflow, Argo, Airflow on K8s, Flink operator).
  - You run many teams' workloads on shared clusters.
- Pick ECS instead when:
  - You want the **simplest AWS-native** option.
  - There is no K8s expertise, no control-plane fee, and tight AWS integration.
  - It is the usual exam answer for "least operational overhead" container orchestration.
- **Cluster endpoint access**:
  - **Public** (API reachable from the internet, restricted by CIDR), **private** (only from the VPC), or both.
  - Private endpoint for production, accessed via VPN/bastion/SSM.
- **Cluster access control**:
  - **EKS access entries** (the newer, recommended way): map IAM principals to K8s permissions with **access policies** (AmazonEKSClusterAdminPolicy, AmazonEKSViewPolicy…) via the EKS API.
  - Replaces the old **`aws-auth` ConfigMap**.
  - The **cluster creator** gets admin by default (can be turned off).

## C. Data plane options (where pods run)
- **Managed node groups**:
  - EKS creates and manages **EC2 Auto Scaling groups** of nodes with EKS-optimized AMIs (Amazon Linux 2023, Bottlerocket, GPU variants).
  - Handles **graceful node updates** (drain, then replace). On-Demand or **Spot** capacity types. Launch templates for customization.
  - You still pick instance types and pay for EC2.
- **Self-managed nodes**: your own ASGs/AMIs. Full control, full work (patching, joining the cluster).
- **AWS Fargate for EKS**:
  - **Fargate profiles** pick pods (by namespace/labels) to run on Fargate.
  - **One pod per micro-VM**, no nodes to manage, pay per pod vCPU/memory.
  - Limits: **no DaemonSets, no GPUs, no privileged pods, no EBS persistent volumes** (EFS works; verify), and **EKS Pod Identity is not supported on Fargate** (use IRSA).
  - Good for small, isolated or spiky workloads.
- **Karpenter** (open-source node autoscaler, AWS-backed):
  - Watches **unschedulable pods** and launches **right-sized EC2 instances directly** (no node groups needed), choosing from many types/sizes, **Spot or On-Demand**, x86/Graviton.
  - **Consolidates** underused nodes to save cost. Handles Spot interruptions.
  - Faster and more flexible than Cluster Autoscaler (which scales existing ASGs).
  - Configured with **NodePools** and **EC2NodeClasses**.
- **EKS Auto Mode** (Dec 2024+):
  - AWS manages the data plane too: **Karpenter-based** compute autoscaling, node OS (Bottlerocket) patching and replacement, plus **core add-ons**: VPC CNI, kube-proxy, CoreDNS, EBS CSI, load balancing, Pod Identity agent.
  - **Extra per-instance management fee** on top of EC2 (varies by type; for example about $0.037/h on c6a.2xlarge).
  - Nodes are **immutable** and replaced regularly (max lifetime; verify 21 days).
  - Closest EKS gets to "serverless Kubernetes" while keeping EC2 choice. A strong answer for "reduce EKS operational overhead".
- **EKS Hybrid Nodes**: use on-prem/edge machines as nodes of an EKS cluster (billed per vCPU-hour). **EKS Anywhere**: run the whole K8s on-prem (subscription).
- **Spot on EKS**:
  - Use Karpenter / managed node groups with Spot, many instance types, and the **Node Termination Handler** (or Karpenter interruption handling) to drain pods on the 2-minute warning.
  - Stateless/batch pods only. Use **PodDisruptionBudgets**.
- **Graviton nodes** for price/performance (multi-arch images).

## D. Networking on EKS
- **Amazon VPC CNI** (default plugin):
  - Each **pod gets a real VPC IP address** from the node's subnet (secondary IPs on ENIs). Pods are directly routable in the VPC, and security groups can apply to pods (**Security Groups for Pods**).
  - **Pods per node are limited by ENIs × IPs per ENI** of the instance type.
  - **Prefix delegation** assigns /28 prefixes to ENIs, giving far more pods per node and fewer IP API calls.
  - **IP exhaustion** in small subnets is a top EKS problem. Fixes: bigger subnets, a **secondary CIDR (100.64.0.0/10) with custom networking**, prefix delegation, or **IPv6** clusters.
- **kube-proxy** (service routing) and **CoreDNS** (cluster DNS) are core **add-ons**.
- **AWS Load Balancer Controller**: creates an **ALB** for Ingress / **NLB** for Service type LoadBalancer, using IP targets (pods) for direct routing.
- **Network policies** (pod-to-pod firewall rules) are supported by the VPC CNI (enable the network policy agent).
- **Private clusters**: nodes in private subnets need **VPC endpoints** (ECR api/dkr, S3, EC2, STS, CloudWatch Logs, EKS Auth for Pod Identity, ELB…) or NAT.
- **Node security group / cluster security group** control traffic between the control plane and nodes.

## E. IAM for pods (very testable)
- **Never** give apps the **node IAM role's** permissions. Every pod on that node would share them. Give **each workload its own role**.
- **IRSA (IAM Roles for Service Accounts)** (older, still common):
  - The cluster has an **OIDC identity provider** in IAM.
  - A K8s service account is annotated with a role ARN. The pod gets a projected token and calls **`AssumeRoleWithWebIdentity`**.
  - The role's trust policy references the cluster OIDC provider and `system:serviceaccount:<ns>:<sa>`.
  - **Works on Fargate**, and on any K8s with OIDC.
- **EKS Pod Identity** (newer, simpler):
  - Install the **Pod Identity Agent** add-on (built into Auto Mode). Create a **pod identity association** (cluster + namespace + service account → IAM role) through the **EKS API**.
  - The role trusts the single service principal **`pods.eks.amazonaws.com`**, so the **same role is reusable across clusters without editing the trust policy**, and no OIDC provider per cluster is needed.
  - Supports **session tags** for ABAC (cluster, namespace, service account tags; verify).
  - Up to **5,000 associations per cluster**.
  - Limits: **Linux EC2 nodes only**. **Not on Fargate**, not on Windows nodes, not on EKS Anywhere/Outposts.
  - Cross-account access is done by assuming a role in the other account (role chaining).
- Both deliver **temporary credentials** to the AWS SDK automatically (env vars + credential chain).
- **Block pod access to node IMDS** (IMDSv2 hop limit 1), so pods can't take the node role.
- **Node IAM role**: minimal permissions (EKS worker policy, CNI policy (or via IRSA for the CNI), ECR read-only for pulls).

## F. Add-ons and storage
- **EKS add-ons** (managed install/upgrade by EKS):
  - Core networking: VPC CNI, CoreDNS, kube-proxy, Pod Identity Agent.
  - Storage drivers: **EBS CSI**, **EFS CSI**, **Mountpoint for S3 CSI**, FSx CSI.
  - Security and observability: **GuardDuty agent**, **CloudWatch Observability** (Container Insights), **ADOT** (OpenTelemetry), snapshot controller.
  - **Community add-ons** (metrics-server, etc.; verify).
- **Storage**:
  - **EBS** volumes via the CSI driver: `PersistentVolumeClaim` + StorageClass (gp3, encryption). One AZ, one node at a time (ReadWriteOnce).
  - **EFS**: shared ReadWriteMany across AZs and pods.
  - **Mountpoint for Amazon S3 CSI**: mount buckets read-mostly for data/ML.
  - **FSx for Lustre** for high-throughput HPC/ML.
- **Secrets**:
  - K8s Secrets encrypted with **KMS envelope encryption** (on by default for new clusters; verify).
  - Or **Secrets Store CSI driver + AWS Secrets and Configuration Provider (ASCP)** to mount Secrets Manager/Parameter Store values as files (with rotation sync).
  - Or External Secrets Operator.

## G. Data workloads on EKS
- **Amazon EMR on EKS**:
  - Run **Spark** jobs on an existing EKS cluster (a "virtual cluster" mapped to a namespace).
  - Submit with `start-job-run`. EMR runtime performance and managed Spark versions. Pay EMR on EKS per vCPU/memory plus the EKS compute.
  - Shares cluster capacity with other apps. Use Karpenter + Spot for executors.
  - Alternatives: **Spark operator** (open source) or EMR Serverless (no cluster at all).
- **Apache Airflow on EKS** (official Helm chart, KubernetesExecutor: one pod per task) vs **MWAA** (managed Airflow; less ops). The exam prefers MWAA for "managed".
- **AWS Batch on EKS**: Batch queues/scheduling with jobs as pods on your EKS nodes.
- **Flink on EKS** (Flink operator) vs **Amazon Managed Service for Apache Flink** (managed).
- **Kafka on EKS** (Strimzi) vs **Amazon MSK** (managed). Managed is usually the exam answer.
- **ML**: Kubeflow, Ray (KubeRay), GPU node pools with Karpenter, NVIDIA device plugin, EFA for distributed training, **SageMaker HyperPod with EKS** orchestration.
- **K8s Jobs/CronJobs** for containerized ETL. Argo Workflows for DAGs on K8s.
- Data access from pods: S3 through IRSA/Pod Identity roles, the S3 gateway endpoint, Mountpoint CSI. Databases via security groups (Security Groups for Pods).

## H. ECS vs EKS decision guide
| Factor | ECS | EKS |
|---|---|---|
| Control plane cost | Free | $0.10/h per cluster (extended support $0.60/h) |
| Learning curve | Low (AWS concepts) | High (Kubernetes) |
| Portability | AWS only (ECS Anywhere for on-prem) | Any Kubernetes (multi-cloud, on-prem, Hybrid Nodes) |
| Ecosystem | AWS integrations | Huge K8s ecosystem (Helm, operators) |
| Serverless option | Fargate, Express Mode | Fargate profiles, Auto Mode (managed nodes) |
| Pod/task IAM | Task role | IRSA / Pod Identity |
| Upgrades | No versions to manage | K8s version upgrades every ~year |
| Typical exam answer | "Least operational overhead" containers on AWS | "Existing Kubernetes / portability / K8s tooling" |

## Scenarios (if → then, because)
- If a team already runs Spark and apps on Kubernetes and wants AWS to manage the control plane → Amazon EKS.
- If they want Spark jobs on that same EKS cluster with EMR's optimized runtime → **EMR on EKS**.
- If the goal is containers with the least operations and no Kubernetes skills → ECS (Fargate), not EKS.
- If EKS node management (patching, scaling, add-ons) is too much work → **EKS Auto Mode** (or Fargate profiles for some pods).
- If pods wait unscheduled and nodes should be added fast with the cheapest fitting types (Spot) → **Karpenter**.
- If a pod needs S3 access → **EKS Pod Identity** (or IRSA) for its service account, never the node role.
- If the same IAM role must work in 10 clusters without editing trust policies → **Pod Identity** (trusts `pods.eks.amazonaws.com`).
- If the pods run on **Fargate** and need AWS permissions → **IRSA** (Pod Identity is not supported on Fargate).
- If pods can't start with "failed to assign an IP address" → subnet IP exhaustion. Prefix delegation, secondary CIDR/custom networking, bigger subnets or IPv6.
- If a cluster is still on an old Kubernetes version and the bill jumped → it entered **extended support** ($0.60/h). Upgrade to a standard-support version.
- If pods need shared files across AZs → the **EFS CSI** driver (ReadWriteMany).
- If an app needs a database-style block volume → the **EBS CSI** driver with a gp3 StorageClass (single AZ).
- If K8s secrets must not be readable in etcd → KMS envelope encryption, or mount Secrets Manager values with the Secrets Store CSI driver.
- If developers need admin access to a new cluster → **EKS access entries** with access policies (not aws-auth edits).
- If the API server must not be internet-reachable → private endpoint only, with nodes in private subnets and VPC endpoints.
- If a nightly containerized job should run inside EKS → a K8s **CronJob** (or Batch on EKS for queues/retries).
- If on-prem servers must join the same cluster → **EKS Hybrid Nodes**.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: EKS pricing (standard $0.10/h, extended $0.60/h, 14 + 12 months support, Provisioned Control Plane tiers, Auto Mode per-instance fee example, Fargate billing basis, Hybrid Nodes tiers), EKS Pod Identity (agent, associations, `pods.eks.amazonaws.com` trust, reusability, 5,000 associations per cluster, Linux EC2 only, not on Fargate/Windows/Outposts/EKS Anywhere, not needed with Auto Mode setup).
Not confirmed (verify): automatic upgrade after extended support, Fargate for EKS EFS support detail, Auto Mode node maximum lifetime, Pod Identity session tags, default KMS secret encryption on new clusters, community add-on list.

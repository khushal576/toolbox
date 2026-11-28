# Amazon EMR – 4. Security, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Identity and roles (EMR on EC2)
- **Three IAM roles** to know:
  - **EMR (service) role** (`EMR_DefaultRole`): lets the **EMR service** act on your behalf (launch EC2, manage ENIs, security groups, resize).
  - **EC2 instance profile** (`EMR_EC2_DefaultRole`): attached to **every node**; application processes use it to call S3, DynamoDB, Glue, etc.
  - **Auto scaling role** (`EMR_AutoScaling_DefaultRole`): needed only for **custom auto scaling policies** (instance groups).
  - **Runtime role** (per step/job): a role you pass when you submit a **Spark/Hive step** (or Serverless/EKS job) so each job uses its **own** permissions.
- **Single-tenant vs multi-tenant**:
  - Default cluster = **single tenant**: the EC2 instance profile is the identity; anyone with access can run code with full cluster rights (and can **change OS/software**).
  - **Multi-tenant** = enable **runtime roles**, **IAM Identity Center**, **Kerberos**, or **LDAP**. With runtime roles or fine-grained access control (FGAC), **instance-profile access is blocked from user code via iptables**, so jobs are isolated.
- **Workforce identities**: **IAM Identity Center with trusted identity propagation** (user identity flows to S3 access grants/Lake Formation), **LDAP** (AD/OpenLDAP), **Kerberos** (KDC: cluster-dedicated or external; cross-realm trust with AD).
- **`iam:PassRole`** needed for EMR roles and runtime roles; restrict with `iam:PassedToService`.
- **Cluster-level IAM**: control who can create/terminate with **IAM policies + tags** (`elasticmapreduce:ResourceTag`, `RequestTag`), scope by **cluster tags** (for example `team=ds`).
- **EMRFS role mapping (authorization)**: map IAM **users/groups/S3 prefixes** to **different roles** so access to S3 differs by user (for Kerberos or runtime clusters); not needed when using runtime roles.

## B. Data access control (who can read which data)
- **IAM + S3 bucket policies** (baseline), **S3 access points**, **S3 access grants** (map directory identities/IAM principals to S3 locations; logs end-user identity to CloudTrail).
- **AWS Lake Formation** with EMR: **fine-grained (row/column/cell) access** to Glue Catalog tables for **Spark/Hive** jobs run with runtime roles; requires specific EMR releases and a **security setup** (for example Lake Formation enabled in the EMR security configuration, **Glue Catalog as metastore**). Jobs read data through **Lake Formation credential vending**, not the instance profile.
- **Apache Ranger** integration (plugins for Hive metastore, Spark SQL, S3): ranger-managed policies (needs a Ranger server).
- **Column masking, tag-based policies**: Lake Formation LF-tags (see the Lake Formation notes).
- **Best practice**: **no shared admin roles**; **runtime roles per job type**; **Lake Formation for lakehouse tables**.

## C. Encryption
- **At rest** (configured with an **EMR security configuration**):
  - **S3 data via EMRFS**: **SSE-S3**, **SSE-KMS**, **CSE-KMS** (client-side), **CSE-Custom**.
  - **Local disks**: **LUKS** encryption of instance-store/EBS data volumes, with a **KMS key or custom key provider**.
  - **EBS**: with the **EBS encryption** option (incl. root volume with custom AMI/security configuration).
  - **HDFS transparent encryption** (Hadoop KMS) for HDFS data.
- **In transit**: TLS for **Spark, Hive, Tez, Presto, HDFS RPC, YARN** using **PEM certificates in S3** or **custom provider**; configure via the security configuration.
- **Security configuration** = a reusable JSON (stored in EMR) applied at cluster creation: encryption, authentication (Kerberos), IAM roles for EMRFS, Lake Formation settings.
- **Keys**: **KMS** CMKs; allow the EMR EC2 role to use them; plan **key policies** for cross-account S3.
- **Logs**: cluster logs to **S3 log URI** (encrypt that bucket); `s3://.../<cluster-id>/` includes node, step, container logs.

## D. Network security
- **Place clusters in private subnets**, access via **SSM Session Manager**, **VPN/Direct Connect**, **bastion**, or **EMR Studio / persistent UIs** instead of public IPs and open SSH.
- **Security groups**: EMR creates **managed groups** for primary, core/task, and **service access** (for private subnets). Rules open ports between nodes; **no inbound from `0.0.0.0/0`** except what you add.
- **EMR block public access (BPA)**: **account/Region-level setting** that blocks launching a cluster whose security groups allow **inbound from public IPs on any port** except allowed exceptions (port 22 by default). **Turn it on.**
- **VPC endpoints**: **S3 gateway endpoint** (free; keeps S3 traffic private and avoids NAT charges), **interface endpoints** for EMR (`elasticmapreduce`), STS, Glue, KMS, CloudWatch Logs, Secrets Manager, SSM as needed.
- **Managed scaling** needs a path to its metrics service (see file 2).
- **IMDSv2**: require **instance metadata service v2** on cluster instances (`--metadata-options`) to reduce SSRF risk **(verify settings per release)**.
- **Patching**: Amazon Linux AMI does **not** auto-apply reboot-requiring kernel updates; **rebuild clusters on new AMIs**, use **custom AMIs**, or run bootstrap-time updates (needs HTTP/HTTPS egress to Amazon Linux repos in S3).
- **Serverless/EKS**: network and IAM models described in file 3.

## E. Auditing and governance
- **CloudTrail**: EMR API calls (`RunJobFlow`, `TerminateJobFlows`, `AddJobFlowSteps`, runtime role use) and S3/Lake Formation data events as configured.
- **AWS Config** rules for EMR (for example public access, encryption) **(verify rule names)**; **Security Hub** controls **(verify)**.
- **Tags and cost allocation**: tag clusters, propagate to EC2; use **Cost Explorer** with the tag; add **Budgets**.
- **Service Catalog** to offer **pre-approved EMR templates** (secure defaults) to teams.
- **Compliance**: EMR is in scope for many programs (HIPAA eligible, PCI, SOC, FedRAMP) **(verify per option)**.
- **Lineage/catalog**: Glue Data Catalog + Lake Formation; OpenLineage integrations **(verify)**.

## F. Cost: what you pay for
- **EMR on EC2**: **EC2 instance price + EMR uplift per instance-hour**, billed **per second with a 1-minute minimum**, plus **EBS**, **S3**, **data transfer**, **CloudWatch**. Docs example: **c4.2xlarge EMR charge $0.105/hr on top of EC2 $0.398/hr**; three c4.2xlarge On-Demand nodes for 730 h ≈ **$1,101.57/month**.
- **Purchase options for EC2 nodes**: **On-Demand**, **Reserved Instances**, **Capacity Savings Plans**, **Compute/EC2 Instance Savings Plans**, **Spot (up to ~90% cheaper)**. **The EMR uplift is not discounted by Spot** (you pay the uplift on top).
- **EMR on EKS**: **$0.007084 per vCPU-hour + $0.000777875 per GB-hour** (US East example) + **$0.10/hour per EKS cluster** + EC2/Fargate.
- **EMR Serverless**: **$0.052624 per vCPU-hour + $0.0057785 per GB-hour** (US East example) + storage beyond 20 GB/worker.
- **Cost drivers**: idle clusters, oversized nodes, **small-files overhead**, Spot interruptions causing retries, cross-AZ shuffle, S3 request charges, NAT charges (use S3 gateway endpoint), logging volume, unmanaged HDFS growth, **over-scaling due to DRA disabled**.
- **Cost levers (checklist)**:
  - **Transient clusters** with auto-terminate; **idle auto-termination policy** on long-running ones.
  - **Spot for task nodes** (fleets with many types); **On-Demand for primary/core**.
  - **Managed scaling** with a sensible **max** and **On-Demand limit**.
  - **Graviton** instances (better price-performance).
  - **Right-size** executors; use **memory-optimized only when needed**.
  - **Serverless for spiky jobs**; **EC2 + Savings Plans/Spot for steady jobs**.
  - **Columnar formats + partition pruning**, compact small files, **S3 Intelligent-Tiering/lifecycle** for old outputs.
  - **S3 gateway endpoint**; keep data and compute in the **same Region/AZ** where possible.
  - **Tag and budget** per team; alert on cluster runtime.
  - **Use the latest EMR release** (performance gains reduce runtime).
  - **Delete old EBS/AMIs/logs**; set **log retention**.
- **EMR vs Glue cost rule of thumb**: Glue (per DPU-hour, serverless) wins for **small/medium and irregular ETL**; EMR (esp. EC2 + Spot, or Serverless with tuning) often wins at **large sustained scale** **(workload dependent; verify with your numbers)**.

## G. Monitoring and troubleshooting
- **CloudWatch metrics (namespace `AWS/ElasticMapReduce`)**: `IsIdle`, `AppsRunning/Pending/Failed`, `ContainerAllocated/Pending`, `YARNMemoryAvailablePercentage`, `HDFSUtilization`, `CoreNodesPending`, `LiveDataNodes`, `MRUnhealthyNodes`, `MRLostNodes`, `TotalLoad`, `S3BytesRead/Written`, HA metrics `MultiMasterInstanceGroupNodes*`.
- **Alarms**: `IsIdle` for long idle (terminate), `HDFSUtilization` > 80–90%, `YARNMemoryAvailablePercentage` low, `MRLostNodes`, step failures via **EventBridge** (`EMR Step Status Change`, `EMR Cluster State Change`, `EMR Auto Scaling Policy State Change`).
- **Logs**: S3 log URI (`steps/`, `node/`, `containers/`), **CloudWatch agent** for logs/metrics, **Spark History Server**, **YARN UI**; **persistent application UIs** (viewable after termination).
- **Event-driven automation**: step failure → EventBridge → Lambda/SNS/Step Functions retry; cluster idle → terminate.
- **Common failures**:
  - **`VALIDATION_ERROR` / subnet IP exhaustion** → big clusters need many IPs.
  - **`INTERNAL_ERROR` bootstrap/step** → check logs.
  - **S3 `SlowDown` (503)** → too many requests per prefix → partition prefixes, backoff, reduce small files.
  - **Spark `FetchFailed`** → shuffle data lost (node lost/Spot) → shuffle decommission, more stable nodes.
  - **`Container killed by YARN for exceeding memory`** → raise overhead.
  - **Step stuck `PENDING`** → no YARN capacity → scale or concurrency.
  - **Cluster ARRESTED instance group** → resize failing (capacity/quota) → fix limits/capacity.
  - **Kerberos/Lake Formation access denied** → mapping or policy gaps.

## H. Limits and numbers to remember
- **Primary nodes**: 1 (default) or **3** (HA, quorum 2 of 3, On-Demand only, single AZ).
- **Instance fleet**: up to **5 instance types** per fleet **(verify exact)**.
- **EMR billing**: per second, **1-minute minimum** (EC2, EKS uplift, Serverless).
- **Managed scaling**: release **5.30.0+**, YARN apps only; **`dfs.replication`** floors core scale-in; **EBS < 90%**.
- **Serverless**: default **16 concurrent vCPUs** for new accounts (auto-increasing); **auto-stop idle 15 min** default; Spark default **4 cores/14 GB**; first **20 GB** disk per worker free; API: **`StartJobRun` 1 TPS** (burst 25).
- **EKS**: **1 virtual cluster per namespace**; **$0.10/h per EKS cluster**.
- **Latest release in docs**: **7.14.0**.
- **Spot interruption notice**: **2 minutes**.
- **Logs** for terminated clusters only if **log URI** set.

## I. Scenarios: "If X → Y, because Z"
- **If** different users on one cluster must have different **Amazon S3** access, **then** use **runtime roles** (an IAM role passed with each step or job), or **EMRFS role mapping** (maps users, groups or S3 prefixes to roles) or **Kerberos**. **This works because** by default every job uses the node's **EC2 instance profile**, so everyone gets the same rights. With runtime roles, user code is **blocked from the instance profile**, so each job uses only its own permissions.
- **If** Spark jobs need **row- and column-level security** on lake tables, **then** use **AWS Lake Formation** with EMR: **runtime roles**, a Lake Formation security configuration, and the **AWS Glue Data Catalog** as metastore. **This works because** jobs get data through **Lake Formation credential vending**: Lake Formation hands out scoped credentials that allow only the permitted rows, columns or cells, instead of the broad instance profile.
- **If** clusters must never expose a port to the internet, **then** turn on **EMR block public access (BPA)**, put clusters in **private subnets**, and connect through **AWS Systems Manager (SSM) Session Manager**. **This works because** BPA, an account- and Region-level setting, blocks launching any cluster whose security groups allow inbound traffic from public IPs (except allowed ports, port 22 by default **(verify)**), and private subnets have no public IPs.
- **If** all data must be encrypted at rest, including local disks, **then** create an **EMR security configuration** with S3 encryption (**SSE-S3**, **SSE-KMS** or client-side), **LUKS** local disk encryption and **EBS encryption**, plus **TLS** for data in transit. **This works because** each setting covers one storage layer (S3, instance-store and EBS disks, network), and the security configuration is a reusable JSON applied at cluster creation. Keys come from **AWS Key Management Service (KMS)**.
- **If** compliance requires patched kernels on long-running clusters, **then** rotate clusters regularly onto new **custom AMIs**. **This works because** the default Amazon Linux AMI does **not** auto-install kernel updates that need a reboot, so a new cluster on a new AMI is the clean way to patch.
- **If** most of the EMR bill is idle time, **then** use **transient clusters** (auto-terminate after steps), an **idle auto-termination policy** on long-running clusters, or **EMR Serverless**. **This works because** EMR on EC2 bills while instances run, busy or not; these options stop compute when there is no work, so you pay only for active time.
- **If** **Spot** interruptions threaten HDFS data, **then** keep **core nodes on On-Demand** and put **task nodes on Spot**. **This works because** only core nodes store HDFS data; losing a task node loses no data, while losing a core node loses HDFS blocks.
- **If** NAT gateway charges are high because of S3 traffic, **then** add an **S3 gateway VPC endpoint**. **This works because** the gateway endpoint is **free** and keeps S3 traffic private, so it no longer passes through the NAT.
- **If** many teams' jobs must be billed separately, **then** **tag** each cluster or application per team (tags propagate to EC2) and use **Cost Explorer** and **AWS Budgets** per tag. **This works because** costs can be grouped and alerted on by tag.
- **If** an auditor asks who ran which job, **then** use **AWS CloudTrail** with a **runtime role per job** and the cluster's step history. **This works because** CloudTrail logs EMR API calls such as `AddJobFlowSteps` and runtime role use, so each job's identity and actions are recorded.
- **If** **Graviton** (arm64) instances save money but a job fails, **then** rebuild the job's native libraries for **arm64**. **This works because** compiled binaries must match the CPU architecture.
- **If** HBase data must survive when the cluster is replaced, **then** use **HBase on S3** (HBase root directory in S3) **(verify current support)**. **This works because** the data lives in S3, outside the cluster, so a new cluster can use it.

Verified from AWS docs on 2026-11-01 (EMR security page, managed scaling page, high availability considerations, pricing excerpts, Serverless quotas).
Unconfirmed (verify): HDFS transparent encryption and key provider details; BPA default exception ports; IMDSv2 settings by release; Config/Security Hub rule names; HBase on S3 support; fleet type counts; log retention for persistent UIs; Lake Formation release/version requirements; Savings Plans applicability to the EMR uplift.

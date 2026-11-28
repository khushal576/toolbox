# EC2 – 3. Security, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Shared responsibility for EC2
- AWS secures the physical hosts, the Nitro hypervisor and the network fabric.
- **You** secure the guest OS (patches), software, security groups, IAM roles, keys, data encryption choices and backups.
- EC2 = **unmanaged** (IaaS). That is why exam answers that want "least operational effort" usually pick a managed service instead.
- **AWS Systems Manager Patch Manager** patches OS fleets on a schedule. **Amazon Inspector** scans EC2 for software vulnerabilities and unintended network exposure.

## B. Security groups (SG)
- An SG is a **stateful** virtual firewall on the **ENI** (instance level).
- **Allow rules only**. There are no deny rules. All rules are evaluated together. If any rule allows the traffic, it is allowed.
- **Stateful**: if inbound traffic is allowed, the reply goes out automatically, and the reverse. You do not open ephemeral ports for replies.
- A **new custom SG** has **no inbound rules** (all inbound denied) and **one outbound rule allowing all** traffic.
- The **default SG** of a VPC allows inbound from members of the same SG and all outbound.
- Sources can be CIDR ranges, **another security group ID** (anything carrying that SG), or a **managed prefix list** (for example, the S3 prefix list).
- Referencing an SG instead of IPs is the standard pattern: "DB SG allows 5432 only from App SG". It keeps working when IPs change or the ASG scales.
- Rule changes apply **immediately** to all associated instances. No reboot is needed.
- An SG belongs to **one VPC**. It can be associated with other VPCs in the same Region (SG VPC association) or shared via Organizations.
- Quotas (default):
  - **5 SGs per ENI** (up to 16).
  - **60 inbound and 60 outbound rules per SG**, counted separately for IPv4 and IPv6.
  - Rules × SGs per ENI cannot exceed 1,000.
- SGs do **not** filter traffic to Amazon DNS, DHCP, **instance metadata (IMDS)**, Amazon Time Sync, or Windows license activation.
- Best practice:
  - Never open SSH (22) or RDP (3389) to `0.0.0.0/0`. Prefer **Session Manager** with no inbound ports.
  - Do not open large port ranges. One SG per role (web, app, db).
- **IP allowlisting a data source**: put a fixed source IP on the data side's allowlist, and lock the SG to that source. From private subnets, the NAT gateway's Elastic IP is the source IP the outside world sees.
- Changing an SG on a running instance: yes, you can attach or detach SGs any time.

## C. Network ACLs (NACLs) vs security groups
| | Security group | Network ACL |
|---|---|---|
| Level | Instance (ENI) | Subnet |
| Rules | Allow only | Allow and deny |
| Evaluation | All rules together | In number order, first match wins |
| State | Stateful (replies auto-allowed) | Stateless (allow replies explicitly, incl. ephemeral ports 1024–65535) |
| Default | Custom SG: deny in, allow all out | Default NACL allows all in/out; a new custom NACL denies all |
- Use NACLs to **block** a specific IP or range (SGs cannot deny), or as a subnet-wide guard rail.
- Default quota: 20 inbound and 20 outbound rules per NACL (up to 40 each).
- NACLs cannot reference SGs or prefix lists.
- Exam trap: "outbound works but replies are dropped" with a custom NACL → the ephemeral port range is not allowed for return traffic.

## D. IAM roles for EC2 (instance profiles)
- Give an instance AWS permissions by attaching an **IAM role** through an **instance profile**. The console creates the profile automatically with the same name.
- Apps get **temporary credentials** from the instance metadata service. The SDKs/CLI pick them up automatically and refresh them before expiry.
- **Never** put access keys in code, AMIs, user data or config files on the instance.
- One instance profile (one role) per instance at a time. You can **attach, replace or detach** the role on a **running** instance.
- To launch an instance with a role, the caller needs **`iam:PassRole`** on that role plus `ec2:RunInstances`. Missing PassRole is a common "access denied" at launch.
- Least privilege: scope the role to the exact buckets, prefixes, tables, keys and actions the job needs.
- **Cross-account**: the instance role calls `sts:AssumeRole` into a role in the other account, or the other account's bucket policy / key policy allows the instance role ARN.
- Condition keys useful for EC2: `ec2:ResourceTag/...` (ABAC), `aws:RequestTag`, `ec2:InstanceType`, `ec2:Region`, `ec2:Encrypted` (EBS), `ec2:MetadataHttpTokens` (require IMDSv2).
- Tag-based (ABAC) policies: allow users to start or stop only instances tagged `Team=their-team`.

## E. Instance Metadata Service (IMDS)
- IMDS = a local endpoint at `169.254.169.254` (IPv6 `fd00:ec2::254` on Nitro). It gives instance ID, AMI, IPs, **IAM role credentials**, user data, Spot notices, tags (if enabled).
- **IMDSv1**: plain GET with no session. It is vulnerable to **SSRF** and open reverse proxies stealing role credentials.
- **IMDSv2**: session-based.
  - A **PUT** request gets a token (TTL 1 s to **6 hours**). Each GET must send the token header.
  - PUT requests carrying `X-Forwarded-For` are rejected.
  - The PUT response **hop limit** defaults to **1**, so the token cannot leave the instance.
- Set **HttpTokens = required** to force IMDSv2 only. Requests without a token then get `401`.
- **Containers on EC2** (Docker bridge networking, EKS pods) may need **hop limit 2** to reach IMDSv2.
- Where the setting comes from, highest precedence first: (1) launch parameters / launch template, (2) **account-level default per Region**, (3) **AMI setting** `ImdsSupport = v2.0` (which also sets hop limit 2).
- **Account-level IMDSv2 enforcement**: launches that would allow IMDSv1 fail.
- Enforce with IAM/SCP: deny `ec2:RunInstances` unless `ec2:MetadataHttpTokens = required`. Also deny changes back to optional.
- Amazon Linux 2023 AMIs are configured for IMDSv2-only by default (verify).
- IMDS can be **disabled** entirely on an instance. Apps that need role credentials will then break.
- Instance tags in metadata are **off by default**. Turn them on per instance or in the launch template.
- The SG does not filter IMDS traffic. Protect it with IMDSv2 and the hop limit, or with host firewall rules (iptables) that block non-root users.

## F. Connecting to instances (access)
- **AWS Systems Manager Session Manager** (preferred):
  - Shell access through the SSM Agent, with **no inbound ports**, **no bastion host** and **no SSH keys**.
  - Access is controlled by IAM. Session logs go to **S3 or CloudWatch Logs**, encrypted with KMS. API calls go to **CloudTrail**.
  - Needs the SSM Agent (preinstalled on Amazon Linux and recent Windows AMIs) and an instance role with **`AmazonSSMManagedInstanceCore`**.
  - It also needs a network path to SSM: internet/NAT, or **interface endpoints** `ssm`, `ssmmessages` and `ec2messages` (verify if ec2messages is still required) for fully private subnets.
  - Supports port forwarding (for example, to reach a private RDS through the instance). Session logging is not available for port-forwarding or SSH-over-SSM sessions.
- **EC2 Instance Connect**: pushes a one-time SSH public key (valid 60 s) through the API, controlled by IAM.
- **EC2 Instance Connect Endpoint** lets you SSH/RDP into private-subnet instances without a public IP or bastion.
- **SSH with key pairs**: classic method. You manage keys. Needs port 22 open from your IP and a public IP or a bastion.
- **Bastion host**: hardened jump box in a public subnet. Session Manager or Instance Connect Endpoint usually replaces it now.
- **EC2 Serial Console**: text console for fixing boot or network issues when SSH does not work. Off by default at the account level.

## G. Encryption
- **At rest (EBS)**:
  - EBS encryption uses **AWS KMS** (AES-256). It covers data at rest, data moving between the instance and the volume, snapshots, and volumes made from those snapshots.
  - There is almost no performance cost on Nitro.
  - **EBS encryption by default** is a per-account, **per-Region** setting. All new volumes and snapshot copies are then encrypted, with `aws/ebs` or your chosen CMK.
  - Enforce encryption with IAM/SCP conditions on `ec2:Encrypted`.
  - You cannot share a snapshot or AMI encrypted with the default **`aws/ebs` AWS managed key** with another account. Re-encrypt with a **customer managed key (CMK)**, share the snapshot or AMI, **and** allow the other account to use the key (key policy plus grants).
  - For an ASG in another account using your encrypted AMI, the key policy must allow the Auto Scaling service-linked role (verify exact setup).
  - KMS keys are Regional. A cross-Region copy must re-encrypt with a key in the destination Region.
- **At rest (instance store)**: NVMe instance store is encrypted with keys in the Nitro hardware and erased on stop/terminate (verify wording).
- **In transit**:
  - Use TLS for app and database connections (JDBC with SSL, HTTPS to S3).
  - Traffic between supported Nitro instance types in the same VPC (or peered VPCs) is **automatically encrypted** at the hardware level (verify which types).
  - **Encrypt before transit** = client-side encryption (SDK with a KMS data key) before uploading to S3.
- **Nitro Enclaves**: isolated compute inside an instance with no network, storage or admin access, for very sensitive data (keys, PII, tokenization). Uses cryptographic attestation with KMS.
- **AMD SEV-SNP** (on some AMD types) encrypts memory and protects it from the hypervisor. On Spot it adds a 10% fee.
- **Secrets on EC2**: fetch DB passwords from **Secrets Manager** (supports automatic rotation) or **SSM Parameter Store** (SecureString with KMS) at runtime using the instance role. Never store them in code, AMIs or user data.

## H. Audit and governance
- **CloudTrail** logs all EC2 **API** calls (RunInstances, TerminateInstances, ModifyInstanceAttribute, AuthorizeSecurityGroupIngress…): who, when, from where. It does **not** log what happens inside the OS.
- **CloudTrail Lake** lets you query API events with SQL over long periods (verify the current retention options).
- **AWS Config** records configuration **history** of instances, SGs, EBS volumes, ENIs and EIPs. It evaluates rules like `restricted-ssh`, `ec2-imdsv2-check`, `encrypted-volumes`, `ec2-instance-no-public-ip`, and can auto-remediate through SSM.
- **VPC Flow Logs** capture IP traffic metadata (source/destination, port, accept/reject) for a VPC, subnet or ENI. They go to CloudWatch Logs, S3 or Firehose. Query them with Athena or Logs Insights. They do not capture packet contents.
- **Amazon GuardDuty** detects threats from CloudTrail, VPC Flow Logs, DNS logs and runtime agents (crypto-mining, credential exfiltration from IMDS used outside AWS).
- **Amazon Inspector** scans EC2 for CVEs (via the SSM agent or agentless EBS scanning) and reports network reachability.
- **Security Hub CSPM** aggregates findings and checks against standards (for example, the CIS benchmarks).
- **SCPs** (Organizations): deny launching in unapproved Regions, deny unencrypted volumes, require IMDSv2, restrict instance types.
- **Data sovereignty**: block cross-Region AMI/snapshot copy and Backup copy to forbidden Regions with SCPs on `aws:RequestedRegion` and `ec2:CopyImage`/`ec2:CopySnapshot`.

## I. Cost: what you pay for
- **Instance usage**: per second (60-second minimum) for Linux/Windows while running. The price depends on type, size, Region, OS, tenancy and purchase option.
- **EBS**: GB-month for provisioned size (not used size), plus provisioned IOPS/throughput (gp3 above baseline, io1/io2). **Charged even when the instance is stopped.**
- **Snapshots**: GB-month of changed blocks stored. The archive tier is cheaper for long retention.
- **Public IPv4**: hourly charge for every public IPv4, both in-use and idle Elastic IPs.
- **Data transfer**:
  - Inbound from the internet is free.
  - **Outbound to the internet** is charged per GB.
  - **Cross-AZ** traffic is charged **each way** (about $0.01/GB each direction; verify).
  - Same-AZ traffic over **private IPs** is free.
  - Using a **public or Elastic IP** between instances in the same Region is charged even in the same AZ.
- **NAT gateway**: per hour plus per GB processed. **Interface endpoints**: per hour per AZ plus per GB. **Gateway endpoints** (S3, DynamoDB): free.
- **Detailed monitoring** and custom metrics, CloudWatch Logs ingestion and storage, CloudWatch alarms.
- Licensed OSes (Windows, RHEL, SQL Server) add license cost into the hourly price (or BYOL on Dedicated Hosts).

## J. Cost optimization levers
- **Right-size** first: **AWS Compute Optimizer** recommends instance types and sizes, EBS volumes and ASG configs from CloudWatch history. It works better with memory metrics from the CloudWatch agent.
- **Turn off idle**: stop dev/test instances at night (Instance Scheduler on AWS, or EventBridge Scheduler plus SSM Automation). Delete unattached EBS volumes and old snapshots. Release unused Elastic IPs.
- **Graviton**: same work for less money if the software runs on ARM.
- **Spot** for fault-tolerant jobs. **Savings Plans** for the steady baseline. **On-Demand** for the rest. A typical mix: Savings Plan baseline + Spot burst + On-Demand safety.
- **gp3 instead of gp2**: cheaper, and performance is set separately from size.
- **Keep traffic in one AZ** for chatty clusters (Spark, Kafka with rack awareness, follower fetching) to cut cross-AZ charges. Balance this against HA.
- **S3 gateway endpoint** instead of NAT for S3 traffic.
- **Instance store** for scratch instead of large provisioned EBS volumes.
- **Auto Scaling** to match capacity to demand instead of sizing for peak.
- Move suitable work to **serverless or managed** (Lambda, Fargate, Glue, EMR Serverless, Athena) to stop paying for idle servers.
- **Cost allocation tags** plus Cost Explorer and AWS Budgets: track spend per team, pipeline or project, and alert on spikes.
- **Trusted Advisor**: low-utilization EC2 instances, idle load balancers, unassociated Elastic IPs, RI/SP coverage.

## K. Monitoring with CloudWatch
- **Default (hypervisor-level) metrics, no agent**:
  - CPU: `CPUUtilization`.
  - Network: `NetworkIn`, `NetworkOut`, `NetworkPacketsIn`, `NetworkPacketsOut`.
  - Disk: `DiskReadOps`, `DiskWriteOps`, `DiskReadBytes`, `DiskWriteBytes` (**instance store only**), plus `EBSReadOps`, `EBSWriteBytes`, `EBSIOBalance%`, `EBSByteBalance%` on Nitro.
  - Status checks: `StatusCheckFailed`, `_Instance`, `_System`, `_AttachedEBS`.
  - Burstable credits: `CPUCreditBalance`, `CPUCreditUsage`, `CPUSurplusCreditsCharged`, and the related credit metrics.
  - Spot and metadata: `MetadataNoToken` (IMDSv1 calls still happening).
- **Not collected by default**: **memory usage**, **disk space used/free**, swap, per-process metrics, application logs. These need the **CloudWatch agent**.
- **Basic monitoring** (free): metrics every **5 minutes**. Status checks every 1 minute.
- **Detailed monitoring** (paid per metric): metrics every **1 minute**. It also allows aggregation across groups of instances. Useful for faster Auto Scaling reactions.
- **CloudWatch agent**:
  - Collects memory, disk, swap, netstat, processes (procstat), custom StatsD/collectd metrics, and **log files** (app logs, `/var/log/messages`, Windows Event Logs) into **CloudWatch Logs**.
  - Configure it through a JSON file, often stored in **SSM Parameter Store** and pushed with Systems Manager.
  - The instance role needs `CloudWatchAgentServerPolicy`.
- **CloudWatch Logs Insights**: query application logs with a query language. **Metric filters** turn log patterns (for example, `ERROR`) into metrics and alarms.
- **CloudWatch alarm actions on EC2**: stop, terminate, reboot or **recover** the instance; notify **SNS**; trigger Auto Scaling policies.
- **EventBridge** events from EC2:
  - Instance **state-change notification** (running, stopped, terminated…).
  - **Spot interruption warning** and **rebalance recommendation**.
  - Scheduled events (AWS Health).
  - ASG launch/terminate and lifecycle actions.
  - Route them to Lambda, SNS, SQS or Step Functions for automation, for example "when a worker terminates, re-queue its job".
- **AWS Health Dashboard**: scheduled maintenance, retirement and recovery events for your instances.
- Notifications pattern for pipelines: CloudWatch alarm or EventBridge rule → **SNS** topic (email/SMS/Lambda) or **SQS** queue.

## L. Troubleshooting (symptom → cause → fix)
- **`InsufficientInstanceCapacity`** on launch → AWS has no spare capacity of that type in that AZ right now. Fix: try another AZ or type, use flexible types (attribute-based), retry later, or use an **On-Demand Capacity Reservation** for critical launches.
- **`VcpuLimitExceeded` / `InstanceLimitExceeded`** → you hit the Regional **vCPU quota** for that family group. Fix: request a quota increase in **Service Quotas**, or terminate unused instances.
- **`InsufficientFreeAddressesInSubnet`** → the subnet ran out of IPs. Fix: use a larger or extra subnet.
- **Instance goes `pending` → `terminated` right away** → hit an EBS volume limit, a **corrupt or missing snapshot**, an **encrypted volume whose KMS key you cannot use** (no permission or key disabled), or an instance-store AMI missing parts. Check the state reason.
- **`UnauthorizedOperation` when launching with a role** → the caller lacks **`iam:PassRole`**.
- **SSH connection timed out** → SG has no inbound 22 from your IP, NACL blocks it or its return ports, no public IP / route to an internet gateway, or a host firewall. Fix the network path, or use Session Manager.
- **SSH "Permission denied (publickey)"** → wrong private key, wrong user name (`ec2-user`, `ubuntu`, `admin`), or bad key file permissions.
- **Session Manager cannot connect** → SSM Agent not running, instance role missing `AmazonSSMManagedInstanceCore`, or no route to SSM (add NAT or the SSM interface endpoints).
- **App on the instance gets "AccessDenied" to S3** → no instance role attached, role policy missing the action/resource, bucket policy denies it (for example a VPC endpoint condition), or the KMS key policy does not allow the role on SSE-KMS objects.
- **Instance in a private subnet cannot reach S3** → no NAT and no S3 gateway endpoint, or the endpoint route is not in that subnet's route table, or the endpoint policy blocks the bucket, or the SG outbound rule blocks HTTPS.
- **SDK on the instance cannot get credentials after IMDSv2 was enforced** → old SDK/agent using IMDSv1. Update it. In containers, raise the **hop limit to 2**.
- **Job got slower over the night on a T instance** → CPU credits exhausted (Standard mode). Check `CPUCreditBalance`.
- **Disk I/O much lower than the volume's provisioned IOPS** → the instance's EBS bandwidth limit (small size, 30-minute burst used up), gp2 burst credits gone, or a cold volume from a snapshot not initialized.
- **Network slower than the instance's advertised Gbps** → single-flow 5 Gbps limit, "up to" burst credits exhausted, internet gateway 5 Gbps limit on small instances, or PPS/conntrack allowance exceeded.
- **System status check failed** → AWS host problem. Stop/start or rely on recovery.
- **Instance status check failed** → OS problem (out of memory, kernel panic, full disk, bad fstab or network config). Get the system log and screenshot, use the Serial Console, or detach the root volume, fix it on another instance, and reattach.
- **Out of disk space** → not visible in default metrics. Install the CloudWatch agent for `disk_used_percent`, alarm on it, and grow the volume with Elastic Volumes.
- **Out of memory / OOM killer kills Spark executors** → no memory metric by default. Use the CloudWatch agent, move to an R family, tune executors.
- **Spot instances terminated unexpectedly** → capacity reclaimed. Check the EventBridge interruption warnings. Diversify types/AZs, use checkpointing, capacity rebalancing and price-capacity-optimized.
- **ASG keeps launching and terminating instances** → failed health checks (bad AMI, user data error, ELB health path wrong, grace period too short), or a lifecycle hook abandoning.
- **ASG does not scale out** → max capacity reached, vCPU quota hit, insufficient capacity, alarm not breaching (wrong metric or period), or processes suspended.
- **Elastic IP charges with no instance** → idle EIP still allocated. Release it.
- **Bill shows big "Data Transfer" or "NAT Gateway" lines** → cross-AZ chatter or S3 through NAT. Add a gateway endpoint and keep heavy traffic in-AZ.

## M. Limits and numbers to remember
| Item | Value |
|---|---|
| Billing minimum per start (Linux/Windows) | 60 seconds, then per second |
| Spot interruption notice | 2 minutes (hibernate: no 2-minute warning) |
| AWS-interrupted Spot in first hour | No charge |
| Savings Plans / RI terms | 1 or 3 years |
| Max discount: EC2 Instance SP / Compute SP / Database SP | 72% / 66% / 35% |
| Dedicated Host Reservation discount | Up to 70% |
| Dedicated Instance Regional fee | $2/hour per Region with any running |
| User data size | 16 KB raw (before base64) |
| IMDSv2 token TTL | 1 second to 6 hours |
| IMDS hop limit | 1 default (2 when AMI is `v2.0`), max 64 |
| Hibernation RAM limit | Linux < 150 GiB, Windows ≤ 16 GiB |
| T3/T4g credits after stop | Kept 7 days (T2: lost) |
| Spread placement group | 7 running instances per AZ per group |
| Partition placement group | 7 partitions per AZ |
| Single-flow bandwidth | 5 Gbps (10 Gbps in cluster PG, 25 Gbps ENA Express same AZ) |
| Internet gateway traffic | 5 Gbps if < 32 vCPUs, else 50% of bandwidth |
| ENA max | Up to 100 Gbps (newer types can be higher; verify) |
| EBS max-bandwidth burst on small sizes | 30 minutes per 24 hours |
| Elastic IPs per Region (default) | 5 |
| SGs per ENI (default / max) | 5 / 16 |
| Rules per SG (default) | 60 inbound + 60 outbound |
| NACL rules (default / max) | 20 / 40 each direction |
| On-Demand Standard family quota (new account) | 5 vCPUs shown in docs table (often raised automatically; verify for your account) |
| ASG health check grace period default | 300 s console, 0 CLI/SDK |
| Simple scaling cooldown default | 300 s |
| Lifecycle hook timeout | 1 hour default, max 48 hours (or 100× heartbeat) |
| Capacity Blocks for ML | Book ≤ 8 weeks ahead, ≤ 64 instances per block, ≤ 256 total |
| Future-dated Capacity Reservation | Minimum 32 vCPUs |
| Status checks frequency | Every 1 minute |
| Basic / detailed monitoring period | 5 minutes / 1 minute |
| Route 53 Resolver DNS limit | 1,024 packets/s per ENI (fixed) |

## Scenarios (if → then, because)
- **If** engineers need shell access to private instances with **no open ports** and a full audit trail, **then** use **AWS Systems Manager Session Manager** with session logs sent to S3 or CloudWatch Logs. **This works because** it connects through the SSM Agent with **no inbound ports, no bastion host and no SSH keys**, access is controlled by IAM, and API calls go to CloudTrail. The instance needs the `AmazonSSMManagedInstanceCore` role and a path to SSM (NAT or SSM interface endpoints).
- **If** a database security group (SG) must allow only the app servers, even as the Auto Scaling group scales, **then** add an inbound rule with the **app SG as the source**. **This works because** an SG reference covers anything carrying that SG, so it keeps working when IPs change.
- **If** one malicious IP range must be blocked from a subnet, **then** add a **Network ACL (NACL) deny rule**. **This works because** security groups have **allow rules only**, while NACLs work at the subnet level with allow and deny rules, checked in number order.
- **If** outbound connections from a subnet work only with the default NACL, **then** your **custom NACL** is missing the **ephemeral-port** (1024–65535) rules for return traffic. **This works because** NACLs are **stateless**: replies are not allowed automatically, and a new custom NACL denies everything.
- **If** an ETL script on EC2 must read S3 and write to DynamoDB, **then** attach an **Identity and Access Management (IAM) role** through an **instance profile** with a **least-privilege** policy, not access keys. **This works because** the app gets temporary credentials from instance metadata, and the policy can be scoped to the exact buckets, tables and actions.
- **If** a security audit flags **server-side request forgery (SSRF)** risk to instance credentials, **then** require **Instance Metadata Service version 2 (IMDSv2)** (`HttpTokens = required`), set the **account-level default or enforcement**, and add a Service Control Policy (SCP) condition on `ec2:MetadataHttpTokens`. **This works because** IMDSv1 answers plain GETs, while IMDSv2 needs a session token from a PUT request whose **hop limit** of 1 keeps it on the instance. The `MetadataNoToken` metric shows IMDSv1 calls still happening.
- **If** containers on EC2 break after enforcing **IMDSv2**, **then** raise the metadata **hop limit to 2**. **This works because** the default hop limit of **1** stops the token response from reaching containers that sit one network hop away (Docker bridge, EKS pods).
- **If** every new EBS volume must be encrypted, **then** turn on **EBS encryption by default** in **every Region** and add a Service Control Policy (SCP) on `ec2:Encrypted`. **This works because** the setting is **per account, per Region**, and the SCP blocks anyone creating unencrypted volumes.
- **If** an **encrypted AMI** must be used by another account, **then** re-encrypt it with a **customer managed key (CMK)** in AWS Key Management Service (KMS), share the AMI, and grant that account use of the key. **This works because** AMIs encrypted with the default **`aws/ebs`** key cannot be shared.
- **If** you must find who opened **port 22 to the world** last week, **then** search **AWS CloudTrail** for `AuthorizeSecurityGroupIngress`, and use **AWS Config** for the security group's configuration history. **This works because** CloudTrail logs every EC2 API call with who, when and from where, and Config records how resources changed over time.
- **If** you must continuously flag security groups that allow `0.0.0.0/0` on SSH, **then** use the **AWS Config** managed rule **`restricted-ssh`** with **auto-remediation through Systems Manager (SSM)**. **This works because** Config evaluates rules on every change and can fix the problem automatically.
- **If** you need to know which IPs talk to an instance and whether traffic was rejected, **then** turn on **VPC Flow Logs** and query them with **Amazon Athena** or **CloudWatch Logs Insights**. **This works because** Flow Logs record source, destination, port and accept/reject for a VPC, subnet or network interface. They do not capture packet contents.
- **If** an app's database password must **rotate automatically**, **then** store it in **AWS Secrets Manager** with rotation and read it at runtime using the instance role. **This works because** Secrets Manager supports automatic rotation, and the password never sits in code, AMIs or user data.
- **If** a pipeline must alert when an EC2 worker dies, **then** create an **Amazon EventBridge** rule on the instance **state-change** event (terminated) that targets **Amazon SNS**, **SQS** or **Lambda**. **This works because** EC2 sends state-change events automatically, and EventBridge routes them to automation.
- **If** **memory usage** must trigger scaling, **then** install the **CloudWatch agent** to publish `mem_used_percent` and use that metric in **target tracking**. **This works because** memory is **not** a default EC2 metric; the agent collects it (the role needs `CloudWatchAgentServerPolicy`).
- **If** application logs on instances must be searchable in one place, **then** send them with the **CloudWatch agent** to **CloudWatch Logs** and query with **Logs Insights**, or export to S3 and query with **Amazon Athena**. **This works because** the agent ships log files off each instance, and **metric filters** can turn patterns like `ERROR` into alarms.
- **If** Auto Scaling reacts too slowly, **then** turn on **detailed monitoring** (metrics every **1 minute** instead of 5) and set a proper **instance warmup**, or add **predictive** or **scheduled** scaling. **This works because** faster metrics trigger scaling sooner, warmup stops overshoot, and predictive/scheduled scaling adds capacity before load arrives.
- **If** you need to cut EC2 cost with **no app change**, **then** right-size with **AWS Compute Optimizer**, stop idle dev boxes on a schedule, buy **Savings Plans** for the steady baseline, and switch EBS from **gp2 to gp3**. **This works because** Compute Optimizer recommends sizes from real usage, stopped instances do not bill for compute, and gp3 is cheaper with performance set separately from size.
- **If** **cross-AZ** data transfer dominates the bill for a Spark cluster, **then** keep the cluster in **one Availability Zone (AZ)** (or use rack awareness in Kafka). **This works because** cross-AZ traffic is billed **each way** (about **$0.01/GB** each direction; verify), while same-AZ traffic over private IPs is free. Balance this against high availability.
- **If** launches fail with `VcpuLimitExceeded`, **then** request a **vCPU quota increase** in **Service Quotas** for that family group (or terminate unused instances). **This works because** On-Demand quotas are counted in **vCPUs per Region**, not instance count.
- **If** launches fail with `InsufficientInstanceCapacity`, **then** try other Availability Zones (AZs) or types, use flexible **attribute-based instance type selection**, or reserve with an **On-Demand Capacity Reservation (ODCR)**. **This works because** the error means AWS has no spare capacity of that type in that AZ right now, and an ODCR guarantees it for critical launches.
- **If** an instance launches and goes straight from `pending` to `terminated` with an encrypted root volume, **then** the launching identity cannot use the **AWS Key Management Service (KMS)** key, or the key is disabled. Fix the **key policy or grants**. **This works because** an encrypted volume whose KMS key you cannot use is a known cause of instant termination; check the state reason to confirm.
- **If** launching with an instance role fails with `UnauthorizedOperation`, **then** grant **`iam:PassRole`** on that role to the user or pipeline. **This works because** launching with a role needs `iam:PassRole` as well as `ec2:RunInstances`.
- **If** a compliance rule says **no data may leave approved Regions**, **then** use **Service Control Policies (SCPs)** that deny actions in other Regions (`aws:RequestedRegion`) and deny AMI, snapshot and AWS Backup copies to them (`ec2:CopyImage`, `ec2:CopySnapshot`). **This works because** SCPs in AWS Organizations can deny these actions for whole accounts, which also protects data sovereignty.
- **If** very sensitive personal data (PII) must be processed so that even admins on the instance cannot see it, **then** use **AWS Nitro Enclaves** with **AWS Key Management Service (KMS) attestation**. **This works because** an enclave is isolated compute inside the instance with **no network, storage or admin access**, and it uses cryptographic attestation with KMS.
- **If** a question asks managed vs unmanaged for a nightly transform with **least effort**, **then** choose **AWS Glue** or **Amazon EMR Serverless** over self-managed Spark on EC2. **This works because** EC2 is unmanaged (you patch, install and scale everything), while managed services let AWS run the stack.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: security group basics and quotas, SG vs NACL comparison, IMDSv2 behaviour (token TTL, hop limit, precedence, account-level enforcement), Session Manager features and logging, EBS/AMI encryption sharing rules, status checks, basic vs detailed monitoring, On-Demand vCPU quotas, Savings Plans discounts and Dedicated Instance fee, Spot billing, lifecycle hook timeouts, health check grace period, Capacity Blocks numbers, VPC quotas, public IPv4 charging, Route 53 Resolver per-ENI limit.
Not confirmed (verify): AL2023 IMDSv2-only default, whether `ec2messages` endpoint is still required for Session Manager, KMS key policy details for cross-account ASG launches, instance store and in-transit hardware encryption wording and supported types, cross-AZ price per GB, CloudTrail Lake retention options, Standard family vCPU default for new accounts, ENA above 100 Gbps on newest types.

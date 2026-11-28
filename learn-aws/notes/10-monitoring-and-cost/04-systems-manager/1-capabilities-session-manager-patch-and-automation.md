# AWS Systems Manager – 1. Capabilities, managed nodes, Session Manager, Run Command, Patch Manager and Automation

Short notes. Each point is a fact you can be asked about.

**Source note:** the intro, unified console and naming facts in section A2 were checked against the AWS "What is AWS Systems Manager?" page (2026-11-09). The rest comes from product knowledge and is marked **(verify)** where numbers or names are uncertain.

## A. What it is
- **AWS Systems Manager (SSM)** is an operations hub for **managing and automating work across AWS and hybrid nodes** (EC2, on-prem servers, VMs, edge devices): remote access, patching, inventory, configuration, runbooks, parameters and incident handling.
- It is **agent-based for node features**: the **SSM Agent** runs on the node (preinstalled on Amazon Linux 2/2023, Ubuntu, Windows AMIs) and talks to Systems Manager endpoints over HTTPS (port 443, outbound only).
- It is **Regional**. Many capabilities are free; some (Parameter Store advanced, OpsCenter, Automation steps beyond free tier, Incident Manager, on-prem node tier) cost.
- Pick it when: you need **no-SSH/no-bastion access**, **fleet patching**, **runbooks**, **inventory**, **parameter/config management**, or **incident response**.
- Data-engineering relevance: manage EMR/EC2 hosts, run commands on self-managed Kafka/Airflow/Spark nodes, **Parameter Store for pipeline config** (covered separately), **Automation runbooks as Config remediation actions**, Session Manager for private DB tunnelling.
- DEA-C01: operations and security (3.x/4.x): remediation with SSM Automation, Parameter Store, Session Manager access, patching of fleets.

## A2. Verified facts (unified console, node diagnosis, naming)
- Systems Manager "helps you centrally view, manage, and operate **nodes** at scale in AWS, on-premises and multicloud".
- **Unified console** (released **21 Nov 2024**): one place to see nodes across accounts and Regions with a dashboard (for example nodes running outdated OS software), filters by OS/version, Region, account and SSM Agent version, and **Amazon Q Developer** natural-language queries of instance metadata.
- Available in 16 Regions at launch (us-east-1/2, us-west-1/2, ca-central-1, sa-east-1, ap-south-1, ap-northeast-1/2, ap-southeast-1/2, eu-central-1, eu-north-1, eu-west-1/2/3). Individual tools are in more Regions.
- **Node diagnosis and remediation runbook**: finds why nodes are not "managed" (agent, IAM, networking) and recommends remediation runbooks; it can run **automatically on a schedule**.
- A **managed node** needs **SSM Agent installed and able to reach the Systems Manager service**.
- Core tool benefits listed by AWS: just-in-time node access, patching at scale, connect **without opening inbound ports**, remote commands, secure parameter storage, automation. No bastion hosts, SSH or remote PowerShell needed.
- **Naming history**: formerly "Amazon EC2 Systems Manager (SSM)". "SSM" survives in: SSM Agent, SSM parameters, endpoints `ssm.<region>.amazonaws.com`, CloudFormation `AWS::SSM::Document`, Config rule `EC2_INSTANCE_MANAGED_BY_SSM`, CLI `aws ssm …`, managed policies such as `AmazonSSMReadOnlyAccess`, and ARNs `arn:aws:ssm:…`.
- Windows note: some legacy documents need PowerShell 3.0+ (WMF 3.0+) on Windows Server nodes.

## B. Managed nodes (prerequisites)
- A **managed node** is any machine with SSM Agent, **IAM permission**, and network path to SSM.
- **IAM**: attach an **instance profile** with `AmazonSSMManagedInstanceCore` (EC2), or use **Default Host Management Configuration (DHMC)** to grant permissions account-wide; on-prem nodes use a **hybrid activation** (activation code + ID, creating `mi-` managed instance IDs).
- **Network**: outbound HTTPS to `ssm`, `ssmmessages`, `ec2messages` endpoints (public internet/NAT or **three interface VPC endpoints**; plus S3 gateway endpoint for some features and `logs`/`kms` if used).
- **Node IDs**: `i-…` for EC2, `mi-…` for hybrid.
- **Fleet Manager**: console view of managed nodes (file system, performance counters, users, registry) without RDP/SSH.
- **Tags** target nodes in commands, maintenance windows, patch baselines, State Manager associations.
- **Node tiers**: standard (free, up to 1,000 hybrid activations) vs **advanced** (paid for on-prem; needed above 1,000 hybrid nodes) **(verify)**.
- **Why a node isn't "managed"**: agent missing/old, no IAM role, no network path, wrong Region, DHMC not enabled, instance stopped.

## C. Session Manager
- **Session Manager** gives **interactive shell (browser or CLI), port forwarding and SSH tunnelling** to managed nodes **without opening inbound ports, bastion hosts or SSH keys**.
- **Auth**: IAM (user/role needs `ssm:StartSession`, scoped by tag/instance ARN); identities logged in CloudTrail.
- **Logging**: session logs to **S3 and/or CloudWatch Logs** (KMS encrypted), full command history optional; **session data encryption** with KMS.
- **Port forwarding** to remote host/port (for example RDS/Redshift in private subnets through an EC2 jump host) using document `AWS-StartPortForwardingSessionToRemoteHost`.
- **Preferences**: idle timeout (default 20 minutes), max session duration, run-as user, shell profile.
- **Compared with SSH/bastion**: no security group rules, no key management, IAM-based audit, works in private subnets with VPC endpoints.
- **EC2 Instance Connect Endpoint** is a related option for SSH/RDP to private instances without agents.
- Limits: sessions per account/Region quotas (e.g., 100s of concurrent) **(verify)**.

## D. Run Command
- **Run Command** executes **documents** (SSM documents) on many nodes at once: scripts (`AWS-RunShellScript`, `AWS-RunPowerShellScript`), package installs, agent updates, joining domains.
- Targeting: by instance IDs, **tags**, resource groups, or "all".
- Controls: **concurrency** and **error thresholds** (rate control), timeouts, output to S3/CloudWatch, SNS notifications, **command history** (kept 30 days).
- Output in console limited to first 2,500 characters (full output to S3/CloudWatch) **(verify)**.
- IAM: `ssm:SendCommand` scoped by document and target tags.
- Use for ad-hoc admin; for recurring/enforced state use **State Manager**.

## E. State Manager
- **State Manager** applies a **desired state configuration** via **associations**: "run document X on targets Y on schedule Z" (for example keep CloudWatch agent installed, enforce antivirus, set OS config, refresh inventory).
- Schedules: rate/cron; compliance reporting per association (Compliant/Non-compliant).
- **Quick Setup** configures common baselines org-wide (Host Management, Patch Policy, Config recording, DevOps Guru, CloudWatch agent) using StackSets/Organizations.

## F. Patch Manager
- **Patch Manager** automates **OS and application patching** (Windows, Linux, macOS) for managed nodes.
- **Patch baseline**: rules defining which patches are approved (classification, severity, auto-approval delay), exceptions (approved/rejected patches), per OS; **AWS-managed default baselines** and custom baselines. One default baseline per OS type.
- **Patch groups**: tag `Patch Group` on nodes to map to a baseline.
- **Operations**: **Scan** (report missing patches) or **Scan and install** (reboot options).
- **Scheduling**: via **maintenance windows**, State Manager associations, or **patch policies** (Quick Setup; org-wide configuration with schedule, baselines, targets across accounts/Regions).
- **Compliance**: per-node patch state (Compliant/Non-compliant), data in Inventory/Compliance; export to S3 with **Resource Data Sync**.
- **Patch sources**: OS vendor repos (needs outbound access), WSUS optional; offline/private networks need repo mirrors or VPC endpoints.
- **Rollback** is not automatic: use AMI snapshots/blue-green.
- For **EMR/containers**: patch by replacing AMIs/images rather than in-place (Patch Manager is for long-lived EC2).

## G. Automation (runbooks)
- **Automation** runs **runbooks (automation documents, YAML/JSON)** that orchestrate **multi-step workflows** with actions such as `aws:executeAwsApi`, `aws:runCommand`, `aws:changeInstanceState`, `aws:createImage`, `aws:invokeLambdaFunction`, `aws:branch`, `aws:approve`, `aws:waitForAwsResourceProperty`, `aws:sleep`, `aws:executeScript` (Python/PowerShell).
- **AWS-owned runbooks**: hundreds (`AWS-RestartEC2Instance`, `AWSConfigRemediation-*`, `AWS-CreateImage`, `AWS-ConfigureS3BucketPublicAccessBlock`, `AWS-EnableS3BucketEncryption`).
- **Execution roles**: `AutomationAssumeRole` (service role the runbook uses); principals need `ssm:StartAutomationExecution`.
- **Rate controls** for multi-target executions (concurrency, error thresholds), **multi-account/multi-Region automation** from a central account.
- **Triggers**: console, API, EventBridge rules (remediate on events), Config remediation, maintenance windows, CloudWatch alarms (via EventBridge), Incident Manager.
- **Approvals** (`aws:approve`) for human-in-the-loop steps with SNS.
- **Cost**: first 100,000 automation steps per month free; then per step; `aws:executeScript` duration billed **(verify)**.
- **Automation vs Step Functions**: Automation is built for AWS operations/runbooks with native Config/EventBridge/Incident Manager integration; Step Functions is general workflow orchestration.
- **Common DE runbooks**: stop idle EMR clusters, enforce S3 encryption/block public access, rotate credentials, snapshot volumes, restart agents, resize instances.

## H. Maintenance Windows
- **Maintenance window**: schedule (cron/rate), duration (1–24 h), cutoff, **targets** (tags), **tasks** (Run Command, Automation, Lambda, Step Functions) with priorities, concurrency/error settings.
- Used to run patching and risky ops during approved times.
- **Change Calendar** blocks automation/maintenance on specified dates (open/closed calendars).

## I. Exam skills mapping
- **4.1.1 Update VPC security groups**: access without opening security groups (Session Manager).
- **4.5.4 View configuration changes (Config)**: Automation as Config remediation.

## J. Scenarios: "If X → Y, because Z"
- **If** engineers need a shell on **Amazon Elastic Compute Cloud (EC2)** instances in private subnets, with an audit trail and no inbound ports open, **then** use **AWS Systems Manager (SSM) Session Manager** with session logs sent to **Amazon S3** and/or **Amazon CloudWatch Logs**. Session Manager gives a browser or CLI shell through the **SSM Agent**, which only makes **outbound HTTPS (port 443)** calls, so no bastion host, SSH keys or security group rules are needed. **This works because** access is controlled by **Identity and Access Management (IAM)** (`ssm:StartSession`, scoped by tag or instance), each identity is logged in **AWS CloudTrail**, and session logs can be encrypted with **AWS Key Management Service (KMS)**. In private subnets, the node needs **VPC endpoints** to reach Systems Manager.
- **If** you must patch **500 Linux instances** every month inside an approved time slot, **then** use **Patch Manager** with a **custom patch baseline** and a **maintenance window** (or a **patch policy** from Quick Setup). The baseline sets which patches are approved (by classification, severity and auto-approval delay), and the maintenance window runs **Scan and install** on tagged nodes on a cron/rate schedule. **This works because** Patch Manager both schedules the work and reports per-node **compliance** (Compliant/Non-compliant). The catch: **rollback is not automatic**, so keep AMI snapshots or use blue-green.
- **If** an **AWS Config** rule finds an unencrypted **Amazon S3** bucket, **then** set up **Config auto remediation** that runs a **Systems Manager Automation runbook**, such as the AWS-owned `AWS-EnableS3BucketEncryption`. A runbook is a YAML/JSON document of steps. **This works because** Config only detects the problem, while **Automation** actually applies the fix, using its `AutomationAssumeRole` (the service role the runbook acts with).
- **If** you need to run a command on all nodes tagged `role=kafka` without risking the whole fleet at once, **then** use **Run Command** with **concurrency** and **error thresholds** (rate control). Run Command executes an SSM document, such as `AWS-RunShellScript`, on many nodes targeted by **tags**. **This works because** concurrency limits how many nodes run at the same time, and the error threshold **stops** the run once too many nodes fail, so a bad command reaches only a few nodes.
- **If** an agent (for example the CloudWatch agent) must always stay installed, **then** use a **State Manager association**: "run document X on targets Y on schedule Z". **This works because** State Manager **re-applies** the desired state on its schedule and reports each association as Compliant or Non-compliant; Run Command is only for one-off jobs.
- **If** a runbook must get a manager's approval before it deletes data, **then** add an **Automation `aws:approve` step** before the delete step. **This works because** the runbook **pauses** at that step and notifies approvers through **Amazon Simple Notification Service (SNS)**, and only continues once a human approves.
- **If** a node does not appear in Systems Manager, **then** check the **three prerequisites** of a managed node: the **SSM Agent** is installed and current, it has **IAM permission** (an **instance profile** with `AmazonSSMManagedInstanceCore`, or **Default Host Management Configuration (DHMC)**), and it has a **network path** to the `ssm`, `ssmmessages` and `ec2messages` endpoints (internet/NAT or interface VPC endpoints). **This works because** a node is "managed" only when all three are true. Also check the **Region** and that the instance is running; the **node diagnosis and remediation runbook** can find the cause for you.

Verified from AWS docs on 2026-11-09 (What is AWS Systems Manager page; Parameter Store tiers page). The remaining sections are not verified.
Unconfirmed (verify): quotas (no usable quota page was returned) and costs; node tier limits; Run Command output size; session limits; free-tier steps; runbook names; DHMC specifics; patch policy behaviour.

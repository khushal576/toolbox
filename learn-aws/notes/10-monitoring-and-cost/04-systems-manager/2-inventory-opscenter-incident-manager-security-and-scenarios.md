# AWS Systems Manager – 2. Inventory, Explorer, OpsCenter, Incident Manager, Change Manager, Application Manager and operations

Short notes. Each point is a fact you can be asked about.

**Source note:** product-knowledge based (no fetched docs for these features in this session); items marked **(verify)** need checking against the Systems Manager User Guide.

## A. Inventory and Resource Data Sync
- **Inventory** collects metadata from managed nodes: installed applications, AWS components, network config, Windows updates, services, files, registry, custom inventory, instance details.
- Collection schedule via State Manager association (default every 30 minutes) **(verify)**.
- **Resource Data Sync** exports inventory/compliance data to an **S3 bucket** (JSON), including cross-account/Regions (organization), so you can query with **Athena/QuickSight**.
- **Inventory queries** in the console; filter by tags; compliance view for patch and association status.
- Used for software audits, license counts, finding vulnerable package versions across a fleet.

## B. Explorer, OpsCenter and OpsData
- **Explorer**: a customizable operations dashboard aggregating **OpsData** (EC2 instances, patch compliance, Config findings, Trusted Advisor, Compute Optimizer, OpsItems) across accounts and Regions (with Organizations).
- **OpsCenter**: central place to view, investigate and resolve **OpsItems** (operational issues).
  - OpsItems created manually or **automatically** by CloudWatch alarms, EventBridge rules, Security Hub, Config, DevOps Guru; contain related resources, runbooks, similar OpsItems.
  - Attach **Automation runbooks** to resolve; track status (Open, In progress, Resolved).
  - Pricing: per OpsItem and API usage after free tier **(verify)**.
- **Application Manager / Resource Groups**: group resources by application (tag/CloudFormation) to view metrics, alarms, runbooks together.

## C. Incident Manager
- **Incident Manager** helps respond to critical incidents: **response plans** (engagement via SMS/voice/email/chat, escalation plans, on-call schedules/rotations, runbooks, chat channel, related alarms), **timeline**, **post-incident analysis** (templates, action items).
- Starts from **CloudWatch alarms or EventBridge** events (or manually).
- Integrates with **AWS Chatbot / Amazon Q Developer in chat**, Systems Manager Automation, OpsCenter, and third-party ticketing.
- Multi-Region **replication set** for resilience; contacts and engagement plans per account.
- Pricing: per incident and engagement (SMS/voice) after free tier **(verify)**.

## D. Change Manager and Change Calendar
- **Change Manager**: enterprise change management with **change templates**, approval workflows, runbook-based changes, scheduling and reviews across accounts/Regions; integrates with Jira/ServiceNow **(verify)**.
- **Change Calendar**: define **open/closed** periods (iCal import); Automation and maintenance windows respect closures (e.g., freeze during quarter close).
- **Pricing**: per change request **(verify)**.

## E. Distributor, Compliance, Hybrid and others
- **Distributor**: package and distribute software (agents) to nodes; versions managed centrally.
- **Compliance**: aggregates **patch**, **association** and custom compliance results; can be exported/aggregated.
- **Hybrid & multicloud**: manage on-prem VMs, edge devices and other clouds (via hybrid activations and **node tiers**).
- **Fleet Manager**: GUI for managing nodes; file browser, process viewer, Windows registry; requires IAM permissions (and Session Manager infrastructure).
- **AppConfig** (feature flags and configuration deployments with validators and gradual rollout) and **Parameter Store** are Systems Manager capabilities (see separate notes for Parameter Store).
- **Quick Setup**: guided org-wide setup for Host Management, Patch policy, Config recording, DevOps Guru, CloudWatch agent and others.
- **Systems Manager for SAP** and **DevOps Guru** integration are niche.

## F. Security and access control
- **IAM**: separate permissions for `ssm:StartSession`, `ssm:SendCommand`, `ssm:StartAutomationExecution`, `ssm:PutParameter/GetParameter*`, `ssm:CreateOpsItem`, etc. Use **tag-based conditions** (`ssm:resourceTag/*`, `aws:ResourceTag`) to scope by environment/team.
- **Managed policies**: `AmazonSSMManagedInstanceCore` (node role), `AmazonSSMFullAccess`, `AmazonSSMReadOnlyAccess`, `AmazonSSMAutomationRole`, `AmazonSSMPatchAssociation` **(verify names)**.
- **Least privilege for Session Manager**: restrict `ssm:StartSession` resources to specific instances/tags and documents (`SSM-SessionManagerRunShell`, port forwarding docs); require **KMS-encrypted session logs** and **MFA** in IAM conditions.
- **Execution roles**: Automation uses `AutomationAssumeRole`; scope to the specific actions the runbook performs.
- **Parameter and document sharing**: share documents publicly/privately/cross-account carefully; documents run as the node's role (root/SYSTEM) → treat as code with review.
- **Network**: interface endpoints for `ssm`, `ssmmessages`, `ec2messages` (+ `kms`, `logs`, `s3`) with endpoint policies; no inbound rules required.
- **Audit**: CloudTrail records all SSM API calls; Session Manager logs commands; Run Command history; Config records managed instance inventory configuration.
- **Data**: command output may contain secrets; send to encrypted S3/CloudWatch; avoid secrets in command parameters (use `SecureString` parameters).
- **Agent security**: keep SSM Agent updated (State Manager `AWS-UpdateSSMAgent`), restrict who can modify documents.
- **Guardrails**: SCPs to block `ssm:SendCommand` outside approved roles; Config rules `ec2-instance-managed-by-systems-manager`, `ec2-managedinstance-patch-compliance-status-check`, `ec2-managedinstance-association-compliance-status-check` **(verify names)**.

## G. Cost
- **Free**: Session Manager, Run Command, State Manager, Patch Manager, Inventory, Fleet Manager, Parameter Store standard parameters, Distributor basics for EC2 nodes.
- **Paid**: Parameter Store advanced parameters/higher throughput, **Automation** (beyond 100,000 steps/month), **OpsCenter** (OpsItems/API), **Incident Manager** (incidents/engagements), **Change Manager** (requests), **Explorer** (no extra charge) **(verify)**, **on-prem advanced node tier**, **AppConfig** (configuration requests), data storage/logging in S3/CloudWatch, VPC endpoints, KMS.
- **Cost levers**: use standard parameters; avoid chatty Automation `aws:executeScript` loops; short log retention for sessions; share endpoints in a central VPC.

## H. Troubleshooting (symptom → cause → fix)
- **Node not listed as managed** → missing agent/role/endpoints, wrong Region, stale agent, instance metadata hop limit/IMDS settings (IMDSv2 must be allowed), proxy settings.
- **Session Manager can't connect** → missing `ssmmessages` endpoint, IAM `StartSession`, session preferences require KMS/S3 permissions, plugin not installed for CLI.
- **Run Command fails/times out** → SSM Agent unreachable, document parameter errors, execution timeout, node reboot, insufficient permissions to S3 for scripts.
- **Patch compliance wrong** → patch group tag/baseline mismatch, repo unreachable, reboot pending, unsupported OS.
- **Automation failed** → `AutomationAssumeRole` lacks permission, approval timeout, API throttling, bad parameters; check step output/execution history.
- **State Manager association failing** → document error, targets unmanaged, schedule conflicts, concurrency limits.
- **Inventory missing** → association not created or Resource Data Sync misconfigured (S3 policy).
- **OpsItems flood** → too many automated rules; deduplicate, tune sources.
- **High cost** → heavy Automation steps, advanced parameters, OpsCenter volume.

## I. Limits (selected, verify)
| Item | Value |
|---|---|
| Session idle timeout default | 20 minutes |
| Run Command history | 30 days |
| Maintenance window duration | 1–24 hours |
| Automation free steps | 100,000 / month |
| Parameter Store standard / advanced | 10,000 / 100,000 parameters |
| Hybrid activations (standard tier) | up to 1,000 nodes |
| Patch baselines | one default per OS |
| Documents size | 64 KB **(verify)** |
| Associations per instance | thousands **(verify)** |

## J. Exam skills mapping
- **3.3.3 Notifications for alerts**: OpsCenter and Incident Manager alerts.
- **4.2.2 Store credentials (Secrets Manager, Parameter Store)**: Parameter Store.

## K. Scenarios: "If X → Y, because Z"
- If you need an inventory of software across fleets queryable in Athena → **Inventory + Resource Data Sync to S3**, because it exports structured data.
- If alarms should open and track operational issues → **CloudWatch alarm → OpsCenter OpsItem**, because OpsCenter centralizes resolution with runbooks.
- If a critical alarm needs on-call escalation and a timeline → **Incident Manager response plan**, because it engages contacts and tracks response.
- If production changes need approvals and change windows → **Change Manager + Change Calendar**, because they enforce approval and freezes.
- If many accounts need a consistent baseline (patching, agent, Config) → **Quick Setup with Organizations**, because it deploys centrally.
- If you must give vendors temporary shell access with audit → **Session Manager with time-limited IAM role + session logs**, because it avoids SSH keys.
- If you need to tunnel to a private database from a laptop → **Session Manager port forwarding to remote host**, because no inbound ports are needed.

Verified from AWS docs on 2026-11-09 (none fetched for this file).
Unconfirmed (verify): everything in this file against the Systems Manager User Guide — features, pricing, managed policy names, Config rule names, limits.

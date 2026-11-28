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
- **If** you need a list of the software installed across your fleets that you can query with **Amazon Athena**, **then** use Systems Manager **Inventory** with **Resource Data Sync** to an **Amazon S3** bucket. Inventory collects metadata from managed nodes (installed applications, network config, services, Windows updates and more), and Resource Data Sync exports it as **JSON** to S3, even across accounts and Regions. **This works because** the data lands in S3 in a structured form, so Athena or **Amazon QuickSight** can query it for software audits, license counts or vulnerable package versions.
- **If** alarms should open and track operational issues, **then** have an **Amazon CloudWatch alarm** create an **OpsItem** in **OpsCenter**. An OpsItem is a record of one operational issue, with its related resources, runbooks and similar OpsItems. **This works because** OpsCenter is one central place to investigate and resolve issues: you attach **Automation runbooks** to fix them and track status (Open, In progress, Resolved). The catch: too many automated rules cause an **OpsItem flood**, and OpsItems are billed after the free tier **(verify)**.
- **If** a critical alarm needs on-call escalation and a record of what happened, **then** use an **Incident Manager response plan**, started by the **CloudWatch alarm** or an **Amazon EventBridge** event. A response plan holds the contacts, engagement (SMS, voice, email, chat), **escalation plans**, on-call rotations, runbooks and a chat channel. **This works because** Incident Manager automatically **engages** the right people, keeps a **timeline** of the response, and supports **post-incident analysis** with action items.
- **If** production changes need approvals and must avoid freeze periods, **then** use **Change Manager** with **Change Calendar**. Change Manager handles **change templates**, approval workflows and runbook-based changes; Change Calendar defines **open/closed** periods, for example a freeze during quarter close. **This works because** a change cannot run without approval, and Automation and maintenance windows **respect** closed calendar periods.
- **If** many accounts need the same baseline (patching, SSM Agent, AWS Config recording), **then** use **Quick Setup** with **AWS Organizations**. Quick Setup is a guided setup for Host Management, Patch policy, Config recording, CloudWatch agent and more. **This works because** it deploys the configuration **centrally** to all accounts and Regions using StackSets, instead of setting up each account by hand.
- **If** you must give vendors temporary shell access with a full audit, **then** use **Session Manager** with a **time-limited Identity and Access Management (IAM) role** and **session logs**. Scope `ssm:StartSession` to specific instances or tags, and you can require **MFA** in IAM conditions. **This works because** there are **no SSH keys** to hand out or revoke: access ends with the role, every API call is in **AWS CloudTrail**, and session logs (encrypted with **AWS Key Management Service (KMS)**) record the commands.
- **If** you need to reach a private database (for example **Amazon RDS** or **Amazon Redshift** in a private subnet) from a laptop, **then** use **Session Manager port forwarding to a remote host** with the document `AWS-StartPortForwardingSessionToRemoteHost`, through an EC2 managed node as the jump host. **This works because** the tunnel goes through the SSM Agent's **outbound** connection, so **no inbound ports** need to be opened.

Verified from AWS docs on 2026-11-09 (none fetched for this file).
Unconfirmed (verify): everything in this file against the Systems Manager User Guide — features, pricing, managed policy names, Config rule names, limits.

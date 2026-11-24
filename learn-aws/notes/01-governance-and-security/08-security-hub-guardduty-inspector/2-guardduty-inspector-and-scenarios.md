# AWS Security Hub, GuardDuty and Inspector – 2. GuardDuty, Inspector, Detective and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Amazon GuardDuty – what it is
- **GuardDuty** is a **threat detection** service. It continuously analyzes AWS logs and uses **threat intelligence, ML and anomaly detection** to generate **findings**. It **detects**; it does not block.
- **Agentless for foundational detection**: enable with one click; no software to deploy (Runtime Monitoring and some plans use an agent).
- **Foundational data sources** (analyzed independently; you don't enable the logs yourself):
  - **CloudTrail management events**
  - **VPC Flow Logs** (from EC2 ENIs)
  - **Route 53 Resolver DNS query logs**
- GuardDuty reads these **internally** — you do not need to turn on Flow Logs or DNS logging, and it does not use your copies/cost.
- **Protection plans** (optional **features**): **S3 Protection** (CloudTrail S3 data events), **EKS Protection** (audit logs), **Runtime Monitoring** (EKS/EC2/ECS-Fargate agent for OS events), **Malware Protection for EC2** (EBS volume scans), **Malware Protection for S3** (scan new objects; can be used standalone), **Malware Protection for AWS Backup**, **RDS Protection** (login activity for Aurora/RDS), **Lambda Protection** (network activity), **AI Protection** (Bedrock/AgentCore/SageMaker events), **Extended Threat Detection** (multi-stage attack sequences; automatic, no extra cost) **(verify cost and defaults)**.
- When first enabled: **30-day free trial**; all plans except Runtime Monitoring enabled by default.
- **Findings**: severity Low/Medium/High (numeric 1–8.9), type names like `Recon:EC2/PortProbeUnprotectedPort`, `UnauthorizedAccess:IAMUser/InstanceCredentialExfiltration.OutsideAWS`, `Exfiltration:S3/MaliciousIPCaller`, `Impact:S3/AnomalousBehavior.Delete`, `CryptoCurrency:EC2/BitcoinTool.B!DNS`, `Policy:S3/BucketAnonymousAccessGranted`, `Discovery:S3/AnomalousBehavior`, `Backdoor:EC2/C&CActivity.B`.
- **Finding format**: includes resource, actor (IP, geo, ASN), action, time, count, and sometimes a threat list match.
- **Trusted IP lists** (suppress known-good) and **threat intel lists** (add your own malicious IPs): up to **1 each per Region per account** (trusted: 1, threat: 6) **(verify)**; can only be managed by the **administrator** in multi-account.
- **Suppression rules** auto-archive matching findings.
- **Sample findings** and a **tester script** let you validate pipelines.

## B. GuardDuty multi-account, delivery and response
- **Delegated administrator** (Organizations) with **auto-enable**; members can't disable.
- **Regional**: enable in every Region (even unused, to catch unusual activity).
- **Findings export**: **EventBridge** (near real time; updates re-sent; frequency default 6 hours for updates, configurable 15 min/1 h/6 h), **Security Hub**, **S3 export** (encrypted with KMS; required for retention beyond 90 days), **Detective**.
- **Retention**: GuardDuty keeps findings **90 days**; export to S3 for longer.
- **Auto-remediation** pattern: EventBridge rule → Lambda/Step Functions: isolate EC2 (SG swap), disable IAM key/role session (attach deny policy), snapshot for forensics, notify via SNS, open ticket.
- **Prefer** **role session revocation** over key deletion for compromised credentials.
- **S3 Protection** is highly relevant for data lakes: detects data exfiltration and destructive actions (`DeleteObject` bursts, anomalous `GetObject`) and unusual access from Tor/malicious IPs.
- **Malware Protection for S3**: scans **new uploads** (and object versions) in selected buckets, tags objects `GuardDutyMalwareScanStatus` (NO_THREATS_FOUND / THREATS_FOUND / UNSUPPORTED / ACCESS_DENIED / FAILED), can trigger quarantine pipelines; supports KMS-encrypted objects with permissions; priced per GB scanned plus per object.
- **RDS Protection**: anomalous login attempts on Aurora/RDS (PostgreSQL, MySQL, MariaDB) using login activity.
- **Runtime Monitoring**: process/file/network events from containers/instances; needs the **GuardDuty agent** (managed install via SSM/EKS add-on/ECS).
- **Trade-offs**: more plans = broader coverage = higher cost; start with foundational + S3 + malware for data buckets.

## C. GuardDuty cost
- Priced by **volume of analyzed data**, per Region per account: CloudTrail management event count (per million), VPC flow log/DNS log GB (tiered), S3 data events (per million), EKS audit logs (per million), Runtime Monitoring (per vCPU/hour), Malware scans (per GB), RDS (per vCore), Lambda (per GB of logs) **(verify rates)**.
- **Usage statistics** in the console show cost per data source during the trial to forecast.
- **Cost levers**: disable plans you don't need, enable only in needed Regions (but threat coverage argues for all), tune S3 Protection scope, scan only high-risk buckets with Malware Protection, use organization-level configuration.
- **Extended Threat Detection** is included with GuardDuty at no extra cost **(per docs)**.

## D. Amazon Inspector – what it is
- **Inspector** is **vulnerability management**: it continuously scans **EC2 instances**, **ECR container images**, and **Lambda functions (and code)** for **software vulnerabilities (CVEs)** and **unintended network exposure**.
- **Automatic and continuous**: no scan scheduling; rescans on changes (new package, patch, new CVE).
- **Scan types**:
  - **EC2 scanning**: agent-based (via **SSM Agent**) or **agentless** (EBS snapshots scanning) **(verify default)**; also **network reachability** scanning (open ports to the internet).
  - **ECR scanning**: image scanning on push and continuous rescans; basic vs enhanced scanning (Inspector provides enhanced).
  - **Lambda standard scanning** (dependency vulnerabilities) and **Lambda code scanning** (code issues: injection, secrets).
  - **CIS benchmark scans** for EC2 OS hardening **(verify)**.
  - **Code security** scanning of repos (SAST/SCA/IaC) via integrations **(newer; verify)**.
- **Inspector risk score**: adjusts CVSS using the environment (e.g., lowers if no internet path) → severity Critical/High/Medium/Low/Informational/Untriaged.
- **Findings** types: **Package vulnerability**, **Network reachability**, **Code vulnerability**; include remediation steps and affected packages; **auto-close** when fixed.
- **Suppression rules** hide findings; **filters** and **CSV/JSON reports** exports.
- **SBOM export** (CycloneDX/SPDX) for inventory.
- **Delegated administrator** and auto-activation for organization accounts.
- **Integrations**: **EventBridge**, **Security Hub**, **Systems Manager** (Patch Manager for remediation), **ECR**, **Lambda**.
- **Coverage view** shows which resources are scanned/not scanned and why (e.g., SSM agent missing, unsupported OS).
- **Pricing**: per **EC2 instance scanned per month**, per **ECR image scanned (initial + rescans)**, per **Lambda function per month** (code scanning extra); **15-day free trial** **(verify)**.
- **Data-engineering relevance**: EMR/EC2 fleets (patching), ECS/EKS/Batch images in ECR, Lambda ETL functions' dependencies, MWAA custom images (not scanned directly).

## E. Amazon Detective (context)
- **Detective** builds a **graph/behavior model** from CloudTrail, VPC Flow Logs, GuardDuty findings, EKS audit logs to **investigate** root cause and blast radius of findings. It does not detect; it **investigates**.
- Use after GuardDuty/Security Hub finding: pivot to entity timelines (IAM role, IP, EC2).
- Requires GuardDuty enabled (at least 48 hours of data before investigation context is rich) **(verify)**.

## F. How the services fit together (exam table)
| Service | Question it answers | Looks at | Output |
|---|---|---|---|
| **GuardDuty** | "Is someone attacking / misusing my account?" | CloudTrail, VPC Flow, DNS, S3 data events, EKS, runtime, malware | Threat findings |
| **Inspector** | "Are my workloads vulnerable?" | EC2, ECR images, Lambda | CVE / exposure findings |
| **Macie** | "Where is my sensitive data in S3?" | S3 objects and bucket posture | Sensitive data & policy findings |
| **Security Hub** | "What is my overall posture and what needs attention?" | Findings + Config-based controls | Aggregated findings, scores |
| **Detective** | "How did this happen and what else was touched?" | Logs graph | Investigation views |
| **Config** | "Is this resource configured compliantly? What changed?" | Resource configuration | Compliance, history |
| **CloudTrail** | "Who called which API?" | API activity | Audit logs |
| **IAM Access Analyzer** | "What is exposed or unused?" | Policies | Access findings |
| **Firewall Manager** | "Are protections applied org-wide?" | Policies | Policy compliance |
| **Security Lake** | "Where is my central security data lake?" | OCSF logs from many sources | S3/Iceberg-style analytics |
- **Rule of thumb**: **threats → GuardDuty**, **vulnerabilities → Inspector**, **sensitive data → Macie**, **posture/aggregation → Security Hub**, **investigation → Detective**, **config compliance → Config**, **API audit → CloudTrail**.

## G. Reference architecture for a data platform
1. **Org trail** (CloudTrail) + **Config** in all accounts → central logging bucket (KMS, immutable).
2. **GuardDuty** with S3 Protection + Malware Protection (landing buckets) + RDS/Lambda plans as needed; delegated admin; auto-enable.
3. **Macie** on raw/landing buckets; **Inspector** for EC2/ECR/Lambda; **Access Analyzer** org analyzer.
4. **Security Hub** aggregation Region + standards (FSBP, CIS) → **EventBridge** → remediation workflows (Lambda/Step Functions/SSM) and **ticketing**.
5. **Security Lake/Athena** for long-term analytics; **Detective** for investigations.
6. **SCP guardrails** to prevent disabling these services (deny `guardduty:Delete*`, `securityhub:Disable*`, `config:Stop*`, `cloudtrail:StopLogging`).

## H. Troubleshooting
- **GuardDuty shows nothing** → normal if no threats; use sample findings; check Region, suspended state, member status.
- **Too many low-value findings** → suppression rules, trusted IP lists, tune plans.
- **Malware scan `ACCESS_DENIED`** → KMS key policy or bucket policy blocks the scan role.
- **Runtime Monitoring coverage issues** → agent not installed/healthy, unsupported OS or node group; check coverage status.
- **Inspector not scanning EC2** → SSM Agent not running or no SSM role, unsupported OS, agentless disabled; check coverage.
- **Inspector ECR scanning not triggering** → enhanced scanning not enabled or image too old (rescan duration limit settings, e.g., 30/90/180 days or lifetime) **(verify)**.
- **Findings missing in Security Hub** → integration disabled in one service or Region; Security Hub not enabled; suppressed/archived.
- **Delegated admin can't see members** → members not enabled, organization auto-enable off, Regions mismatch.
- **Cost surprise** → GuardDuty S3 data events volume, Runtime Monitoring vCPU-hours, Inspector ECR rescans.

## I. Limits and quick facts
| Item | Value |
|---|---|
| GuardDuty free trial | **30 days** |
| GuardDuty findings retention | **90 days** |
| GuardDuty members (Organizations) | **10,000** **(verify)** |
| GuardDuty finding update frequency | 15 min / 1 h / 6 h (default 6 h) |
| Inspector free trial | **15 days** **(verify)** |
| Inspector accounts (org) | **10,000** |
| Security Hub free trial | **30 days** |
| Macie free trial | **30 days** |

## J. Exam skills mapping
- **4.5.2 PII identification (Macie with Lake Formation)**: Macie vs GuardDuty vs Inspector.
- **4.4.1 CloudTrail for API calls (audit)**: threat detection and audit.
- **3.3.3 Notifications for alerts**: automated response.

## K. Scenarios: "If X → Y, because Z"
- If you must detect exfiltration from S3 data lake buckets → **GuardDuty S3 Protection** (+ Macie for sensitivity, CloudTrail data events for audit), because it analyzes S3 data event patterns and threat intel.
- If an IAM role's temporary credentials are used from an unusual external IP → **GuardDuty `InstanceCredentialExfiltration` finding → automated session revocation**, because it detects credential misuse.
- If you need to scan newly uploaded files for malware before analytics → **GuardDuty Malware Protection for S3**, because it scans objects on upload and tags results.
- If EC2/EMR hosts or ECR images must be checked for CVEs → **Inspector (enhanced scanning)**, because it continuously scans and prioritizes by environment.
- If you need to know where PII sits → **Macie**, not GuardDuty or Inspector, because only Macie classifies S3 content.
- If a SOC wants one prioritized queue across tools → **Security Hub (aggregation + automation rules)**, because it normalizes findings.
- If you need to investigate how a user got access and what they touched → **Detective on top of GuardDuty findings**, because it builds the entity timeline and graph.
- If someone tries to turn off monitoring → **SCP denying disable/delete APIs + alarms on those CloudTrail events**, because guardrails protect the detection stack.
- If only some Regions are used → **enable GuardDuty in all Regions anyway (and deny unused Regions by SCP)**, because attackers use unused Regions.
- If AWS Lambda functions use vulnerable dependencies → **Inspector Lambda standard scanning**, because it reports package CVEs and code issues.

Verified from AWS docs on 2026-11-03 (What is GuardDuty, What is Inspector, What is Security Hub CSPM, Macie pages).
Unconfirmed (verify): GuardDuty plan defaults, export/update frequency, trusted/threat list counts and pricing units; Extended Threat Detection cost; Inspector EC2 agentless default, free trial length, CIS/code security scanning, rescan duration settings; Detective data prerequisites; Security Lake details.

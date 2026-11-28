# AWS Security Hub – 1. Security Hub (CSPM) and the findings pipeline

Short notes. Each point is a fact you can be asked about.

## A. What it is and the naming
- **AWS Security Hub** aggregates, normalizes and prioritizes **security findings** from many AWS services and partners, and runs **continuous compliance checks** against standards.
- **Naming note (important)**: the classic service is now documented as **AWS Security Hub CSPM** (Cloud Security Posture Management). AWS also launched a newer **unified AWS Security Hub** (cloud security with exposure/risk correlation, **OCSF** format) **(verify current status and feature split)**. The exam and most docs still use the CSPM concepts below: **standards, controls, ASFF, aggregation, automation rules, delegated admin**.
- It is **Regional**, with **cross-Region aggregation** to one aggregation Region.
- It does not detect threats by itself: it **collects** (GuardDuty, Inspector, Macie, IAM Access Analyzer, Firewall Manager, Config, Systems Manager Patch Manager, Health, partners) and **checks** (security controls via **AWS Config service-linked rules**).
- **Requires AWS Config** (recording resources) for most control checks.
- DEA-C01: **4.4 log/monitor/audit** (security findings), **4.5 governance and compliance**, centralized monitoring in multi-account data platforms.

## B. Core concepts
- **Finding**: a record of a security issue or check result. Format **AWS Security Finding Format (ASFF)** (JSON) in CSPM.
- **Security standard**: a set of controls. Built-in standards:
  - **AWS Foundational Security Best Practices (FSBP)** (default, broad).
  - **CIS AWS Foundations Benchmark** (versions 1.2, 1.4, 3.0 …).
  - **PCI DSS**, **NIST SP 800-53 Rev. 5**, **NIST 800-171** **(verify)**, **AWS Resource Tagging Standard**, service-managed standards (for example Control Tower).
- **Security control**: a specific check (for example "S3 buckets should have server-side encryption", "KMS key rotation should be enabled", "Redshift clusters should be encrypted"). Control IDs like `S3.1`, `IAM.6`, `Redshift.2`. **Controls are shared across standards** (one finding per control, even if multiple standards enable it - "consolidated control findings").
- **Control status**: Passed, Failed, Warning, Not available; **severity**: Critical, High, Medium, Low, Informational.
- **Security score**: percentage of controls passed per standard/account.
- **Insights**: saved queries grouping findings (managed and custom).
- **Custom actions**: buttons that publish selected findings to EventBridge.
- **Automation rules**: rules that **automatically update findings** (suppress, change severity, add notes/user-defined fields) when criteria match, at ingestion time; up to **100 rules** per administrator **(verify)**.
- **Workflow status**: NEW, NOTIFIED, SUPPRESSED, RESOLVED; **record state**: ACTIVE, ARCHIVED.
- **Integrations**: **AWS services** (GuardDuty, Inspector, Macie, Config, Access Analyzer, Firewall Manager, Health, Detective, Systems Manager) and **third-party** (Palo Alto, CrowdStrike, Splunk…) via `BatchImportFindings`.

## C. Multi-account and multi-Region
- **Delegated administrator** (from Organizations) manages **member accounts**; central configuration policies (newer) set standards/controls per OU/account **(verify)**.
- **Auto-enable** for new organization accounts.
- **Cross-Region aggregation**: choose an **aggregation Region** (home) and **linked Regions**; findings, insights, standards status are aggregated to the aggregation Region. Settings: include new Regions automatically.
- **Findings in a Region** stay there unless aggregated; enable Security Hub in **all Regions** for full CIS coverage.
- **Member accounts** can be invited manually or auto-added by Organizations (up to the account limit, e.g., 10,000).
- **Config prerequisite**: Config must record resources **in every account/Region**; **global resources** (IAM) recorded in one Region only to avoid duplicates.

## D. Findings flow and data engineering uses
- **Sources → Security Hub → destinations**:
  - **EventBridge** (all new/updated findings, or custom actions) → Lambda/SNS/SQS/Step Functions/SSM Automation/ticketing.
  - **S3/Athena**: export via Firehose or the OCSF-based **Security Lake** for analytics; or query via **Security Hub finding export** **(verify)**.
  - **Detective** and **Security Lake** for investigation and long-term storage.
  - **SIEM/SOAR** partners.
- Typical data-platform controls to watch: S3 public access blocks, S3 encryption/versioning/logging, RDS/Aurora/Redshift/DynamoDB/Kinesis encryption, KMS rotation, CloudTrail enabled and validated, Config enabled, IAM root MFA/access keys, unrestricted security groups, public snapshots, Glue security configs, OpenSearch encryption and public access, EMR public access blocks.
- **Remediation automation**: Systems Manager Automation runbooks (AWS-owned `AWSConfigRemediation-*`), custom Lambda; often combined with **EventBridge → Step Functions** approvals.
- **Suppress** accepted risks via automation rules (with notes) to keep the score meaningful.
- **Findings retention**: active findings tracked; archived/resolved findings retained for **90 days** **(verify)**.
- **Update frequency**: control checks run on resource change or periodically (12 or 24 hours) depending on control type.

## E. Access control
- IAM actions `securityhub:GetFindings`, `BatchUpdateFindings`, `BatchImportFindings`, `EnableSecurityHub`, `UpdateStandardsControl`…
- **Managed policies**: `AWSSecurityHubFullAccess`, `AWSSecurityHubReadOnlyAccess`, `AWSSecurityHubOrganizationsAccess`.
- **Service-linked role** `AWSServiceRoleForSecurityHub`.
- Restrict `BatchUpdateFindings` (can change workflow/severity) to security teams.
- **Findings can contain sensitive metadata** (resource ARNs, IPs); protect with IAM and encryption (stored encrypted at rest).
- **Cross-account**: only administrator can see member findings.
- **Resource-level**: limited; use `securityhub:ASFFSyntaxPath/*` condition keys for fine-grained `BatchUpdateFindings` **(verify)**.

## F. Monitoring and troubleshooting
- **No findings** → Config not enabled/recording, service integration not enabled (GuardDuty/Inspector/Macie need to be enabled and integrated), Region mismatch, findings only after enabling.
- **Controls show "No data"** → Config rule evaluation not run yet, resource type not recorded.
- **Duplicate findings** → multiple standards (consolidated view off) or aggregation misconfiguration.
- **Score low** → failing high-weight controls; disable irrelevant controls with justification (e.g., not using a service).
- **Member not visible** → invitation not accepted, auto-enable off, Region not enabled.
- **EventBridge rule not triggering** → wrong event pattern (`source: aws.securityhub`, detail-type `Security Hub Findings - Imported`), Region.
- **Cost jump** → large number of ingested findings and checks across many accounts/Regions.
- **CloudTrail**: Security Hub API calls; **CloudWatch**: no native metrics for findings (use EventBridge counts).
- **Aggregated view stale** → aggregation takes minutes; check linked Regions.

## G. Cost
- **30-day free trial** when first enabled per account/Region.
- Pricing dimensions (CSPM): **security checks** (per check, tiered by volume) and **finding ingestion events** (per event, first 10,000/month per account/Region free, then per event) **(verify rates)**.
- **Config costs** (configuration items and rules) apply separately, except service-linked rules created only by Security Hub are not charged for rule evaluations.
- **Cost levers**: enable only the **standards** you need (FSBP baseline, plus CIS/PCI if required), disable unneeded controls, limit Regions, suppress noisy sources, reduce Config recording to needed resource types (carefully), centralize with delegated admin.

## H. Limits (selected, verify)
| Item | Value |
|---|---|
| Member accounts per administrator | up to **10,000** (Organizations) |
| Free trial | **30 days** |
| Aggregation | one aggregation Region, multiple linked Regions |
| Automation rules | ~100 per administrator account **(verify)** |
| Custom insights | ~100 **(verify)** |
| Custom actions | ~50 **(verify)** |
| Findings per `BatchImportFindings` | 100 per call; 240 KB/finding size **(verify)** |
| Findings retention | ~90 days after archive **(verify)** |

## I. Exam skills mapping
- **4.5.4 View configuration changes (Config)**: Config-based controls and standards.
- **4.4.1 CloudTrail for API calls (audit)**: centralized findings.
- **3.3.3 Notifications for alerts**: alerts via EventBridge.

## J. Scenarios: "If X → Y, because Z"
- **If** one security team needs a single dashboard for **Amazon GuardDuty**, **Amazon Inspector**, **Amazon Macie** and **AWS Config** checks across **80 accounts** and **3 Regions**, **then** use **AWS Security Hub** with a **delegated administrator** and **cross-Region aggregation**. The delegated administrator, set up through **AWS Organizations**, manages all member accounts, and **auto-enable** adds new accounts. One **aggregation Region** collects findings from the other **linked Regions**. **This works because** Security Hub collects findings from these services, **normalizes** them into one format and prioritizes them in one place. Security Hub is **Regional**, so without aggregation each Region keeps its own findings.
- **If** auditors ask for proof of **CIS benchmark** compliance, **then** enable the **CIS AWS Foundations Benchmark** standard in **AWS Security Hub**, together with **AWS Config** recording, in **all Regions**. **This works because** Security Hub runs the standard's controls as **Config service-linked rules** and shows a **security score** (the percentage of controls passed). Config must record resources in every account and Region, but **global resources** such as **Identity and Access Management (IAM)** are recorded in one Region only, to avoid duplicates.
- **If** a **Critical** finding must open a ticket automatically, **then** create an **Amazon EventBridge** rule (an event router) on Security Hub findings with severity **Critical**, and send matches to **AWS Lambda**, **Amazon Simple Notification Service (SNS)** or a ticketing tool such as Jira. **This works because** **AWS Security Hub** publishes every new or updated finding as an event. If the rule never fires, check the pattern (`source: aws.securityhub`, detail-type `Security Hub Findings - Imported`) and the **Region**.
- **If** a known, accepted finding keeps cluttering the list, **then** create a Security Hub **automation rule** that **suppresses** it and adds a **note** explaining why. **This works because** automation rules update matching findings **at ingestion time**, so nobody triages them by hand, and the security score stays meaningful. Limit: up to **100 rules** per administrator **(verify)**.
- **If** an **Amazon S3** bucket becomes public, **then** let the **AWS Security Hub** S3 control and the **Amazon Macie** policy finding flow to **Amazon EventBridge**, which triggers an **AWS Lambda** function that turns on **S3 Block Public Access**. **This works because** event-driven remediation reacts in **near real time**, with no person in the loop. For other fixes you can use **AWS Systems Manager Automation** runbooks (`AWSConfigRemediation-*`) instead of custom Lambda code.
- **If** you want long-term security analytics in **Amazon S3** with **Amazon Athena** (SQL on S3), **then** send findings to **Amazon Security Lake**, which stores them in the open **OCSF** format, or export them with **Amazon Data Firehose**. **This works because** Security Hub keeps archived or resolved findings only about **90 days** **(verify)**, so it is not a long-term store.
- **If** Security Hub controls do not evaluate (for example they show "No data"), **then** enable **AWS Config** and make sure it **records** the needed resource types. **This works because** most controls are **Config service-linked rules**; with no recording, there is nothing to check. Right after enabling, an evaluation may also simply not have run yet.
- **If** Security Hub costs rise as you add many accounts, **then** enable only the **standards** you need (for example the **AWS Foundational Security Best Practices (FSBP)** baseline), disable unneeded controls, limit **Regions**, and reduce the resource types **AWS Config** records (carefully). **This works because** cost scales with the number of **security checks** and **finding ingestion events** **(verify rates)**. Config charges its own costs on top, except for rule evaluations of service-linked rules created only by Security Hub.
- **If** third-party tools (for example Splunk or CrowdStrike) must send findings into Security Hub, **then** call the **`BatchImportFindings`** API with findings in **AWS Security Finding Format (ASFF)**, a JSON format; the newer unified Security Hub uses **OCSF** **(verify)**. **This works because** this API is the standard integration path for partners. Limit: **100 findings** per call **(verify)**.

Verified from AWS docs on 2026-11-03 (What is Security Hub CSPM, GuardDuty and Inspector overviews, Macie integration pages).
Unconfirmed (verify): new unified Security Hub vs CSPM split and format (OCSF); exact price rates; automation rule/custom insight/action limits; finding retention; check frequency; central configuration policies; NIST 800-171 availability.

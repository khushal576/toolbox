# AWS Config – 3. Security, cost, operations, comparison and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Security and access
- **IAM** controls who manages Config and who reads data: `config:*` actions such as `PutConfigRule`, `DeleteConfigRule`, `StartConfigurationRecorder`, `SelectResourceConfig`, `GetComplianceDetailsByConfigRule`, `PutRemediationConfigurations`.
- **AWS managed policies**: `AWS_ConfigRole` (service role for the recorder), `AWSConfigRulesExecutionRole` (Lambda rules), `AWSConfigUserAccess`, `AWSConfigRoleForOrganizations`, `AWSConfigMultiAccountSetupPolicy`; service-linked role `AWSServiceRoleForConfig`.
- **Least privilege**: separate roles for **recorder administrators**, **auditors (read-only)**, **remediation executors** (`AutomationAssumeRole`).
- **S3 bucket policy** must allow `config.amazonaws.com` `s3:PutObject` (with `bucket-owner-full-control`), `s3:GetBucketAcl`, `s3:ListBucket`; use `aws:SourceAccount`/`aws:SourceArn` conditions (**confused deputy**).
- **Encrypt** delivered data with SSE-S3 or **SSE-KMS** (Config role needs KMS permission); the **central log archive bucket** should be locked down (versioning, MFA delete or Object Lock, SCP protection).
- **Protect Config itself**: SCP deny `config:StopConfigurationRecorder`, `DeleteConfigurationRecorder`, `DeleteDeliveryChannel`, `DeleteConfigRule` except for security admins.
- **Cross-account delivery**: member accounts deliver to a central bucket owned by the log archive account.
- **Sensitive data**: CIs contain resource properties (policies, tags, sometimes parameters); treat them as sensitive.
- **Network**: interface VPC endpoint for Config API (`com.amazonaws.<region>.config`) **(verify)**.
- **Audit**: CloudTrail logs Config API calls.
- **Tag-based control**: tag rules/conformance packs and restrict by `aws:ResourceTag` **(verify support)**.

## B. Cost model and control
- Charges: **configuration items recorded** (continuous or daily), **rule evaluations** (detective and proactive), **conformance pack evaluations**, **custom configuration items**, plus S3, SNS, Lambda (custom rules), KMS and SSM Automation costs.
- Indicative prices (us-east-1): **$0.003** per CI (continuous); **$0.012** per CI (periodic) but max one per resource per day; **$0.001** per rule evaluation for the first 100,000 per month, cheaper above **(verify tiers)**.
- No upfront fees. Free usage is not advertised on the pricing page.
- **What drives cost**: number of resources × change frequency (continuous), number of rules × resources (evaluations), many accounts × Regions.
- **Cost levers**:
  - Record **only needed resource types** (inclusion list) or **exclude noisy types** (for example EC2 network interfaces, security group rules, route tables if not needed).
  - Use **daily recording** for high-churn types that don't need every change.
  - Prefer **configuration-change rules** over frequent periodic rules; reduce periodic frequency.
  - **Scope rules** by tag or resource type; avoid evaluating everything.
  - Use **conformance packs** wisely: evaluate once, share across frameworks (duplicate controls across standards multiply rules).
  - Turn on Config only in **Regions you use**; block other Regions with SCP.
  - Retention: set **shorter retention** if policy allows (30 days to 7 years); apply S3 lifecycle (Glacier) to delivered history.
  - Disable Security Hub standards/controls you don't need (they create rules).
- **Cost Explorer** usage types show CI and evaluation spend by Region.

## C. Operations playbook
- **Enable**: Control Tower or Organizations delegated admin; ensure recorder in every account/Region you use; central S3 bucket with KMS.
- **Baseline**: start with an operational-best-practices conformance pack (S3, IAM, encryption) or Security Hub standards; add data-platform rules (Glue, Redshift, Kinesis, Lake Formation).
- **Review**: weekly compliance report by aggregator; track NON_COMPLIANT counts; assign owners via tags.
- **Remediate**: automatic for low-risk (tagging, public access block), manual for risky (security group changes).
- **Exceptions**: document and apply `exceptions`/suppression with expiry.
- **Retire rules** that duplicate Security Hub controls.
- **Test**: deploy rules in a sandbox account; use proactive checks in CI/CD.
- **Disaster/recovery**: Config data is in S3; keep the bucket protected; recorder settings in IaC.
- **Automation**: manage recorder/rules/packs with CloudFormation/Terraform/StackSets.

## D. Config vs related services
| Question | Service |
|---|---|
| What is the configuration of this resource, now and in the past? | **Config** |
| Who made this API call? When? From where? | **CloudTrail** |
| Is it compliant with my rule/standard? | **Config rules / conformance packs** (and Security Hub) |
| Is something attacking my account? | **GuardDuty** |
| What are my vulnerabilities? | **Inspector** |
| Where is sensitive data? | **Macie** |
| Is a resource drifted from its CloudFormation template? | **CloudFormation drift detection** (Config can record it) |
| What metrics/logs show performance? | **CloudWatch** |
| What inventory of EC2/OS software? | **Systems Manager Inventory** |
| Org-wide guardrails that block actions | **SCP/RCP/Control Tower preventive controls** (Config = detective) |
- **Detective vs preventive**: Config **detects** (and remediates after the fact); SCPs/IAM **prevent**; proactive Config rules **check before deploy**.
- **Config vs CloudTrail Lake**: Lake is an event data store of API activity (SQL); Config is resource state. They complement each other.

## E. Troubleshooting (symptom → cause → fix)
- **Recorder not recording** → recorder stopped, role lacks permissions, delivery channel invalid → fix role/bucket and start recorder.
- **No files in S3** → bucket policy missing Config principal, wrong bucket or prefix, KMS denied.
- **Rule evaluations missing** → resource type not recorded; rule trigger type mismatch; rule in error state.
- **Custom rule error** → Lambda errors/timeouts, missing permissions, oversized CIs.
- **Aggregator shows no data** → authorization missing/not accepted, source recorder off, Region not included.
- **Organization rule/pack stuck** → trusted access missing, delegated admin not registered, source account recorder off, service-linked role missing.
- **Remediation not running** → automatic remediation off, SSM role permissions, parameter mismatch, max attempts reached.
- **High cost** → see cost levers.
- **Compliance flapping** → resource changing frequently; use periodic evaluation or fix automation conflict (a remediation fights an autoscaling change).
- **Duplicate/overlapping rules from several services** → use Security Hub consolidated findings and remove duplicate packs.

## F. Limits (summary)
| Item | Value |
|---|---|
| Config rules per Region | 1,000 **(verify)** |
| Conformance packs | 50 per account/Region; 130 rules/pack |
| Aggregators | 50 **(verify)** |
| Recorder / delivery channel | one per Region each |
| Retention | 30 days – 7 years |
| Periodic frequencies | 1/3/6/12/24 h |
| History delivery | about every 6 hours |
| Snapshot schedule | 1/3/6/12/24 h or on demand |
| Regions | per-Region enablement |

## G. Exam skills mapping
- **4.5.4 View configuration changes (Config)**: Config operations and cost.
- **4.5.3 Prevent backups or replication to disallowed Regions**: guardrails against disallowed Regions.

## H. Scenarios: "If X → Y, because Z"
- If compliance wants proof of S3 encryption history for 3 years → **Config recording with 3-year+ retention and history in S3**, because Config keeps point-in-time configuration.
- If an unencrypted RDS instance appears → **`rds-storage-encrypted` rule → NON_COMPLIANT → EventBridge → ticket** (encryption can't be added in place), because remediation is to restore from encrypted snapshot.
- If you must track which IAM policies were attached to a role last quarter → **Config history for the IAM role**, because it stores policy attachments over time.
- If you want to stop anyone from disabling recording → **SCP deny stop/delete recorder**, because SCPs guard even admins.
- If Config bills spike after enabling "all resource types" → **switch to specific types or exclusions and daily frequency for noisy types**, because continuous recording bills per CI.
- If multiple frameworks share the same controls → **use Security Hub consolidated controls**, because they avoid duplicate rule evaluations.
- If you need to know whether a CloudFormation stack has drifted → **record CloudFormation resources and use drift detection**, because Config surfaces drift status.
- If you need to answer "which Lambda functions run a deprecated runtime across all accounts" → **aggregator advanced query**, because it queries current configuration centrally.
- If Control Tower detective controls show "Not available" → **check recorder in that Region/account and the Config service-linked rules**, because they rely on Config.
- If auditors want evidence without console access → **read-only role + aggregator + saved queries**, because it supports least-privilege auditing.

Verified from AWS docs on 2026-11-09 (What is AWS Config, Config pricing, service quota summary).
Unconfirmed (verify): managed policy names; VPC endpoint availability; tag-based authorization for Config resources; exact free tier (none advertised); tiered evaluation prices; rule and aggregator limits; history delivery interval.

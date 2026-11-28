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
- **If** compliance wants proof of Amazon S3 encryption settings over the last **3 years**, **then** keep **AWS Config** recording S3 buckets, set **retention** to at least 3 years (default **7 years**; range 30 days to 7 years), and keep the delivered **history files in S3**. **This works because** Config stores point-in-time **configuration items (CIs)** for each resource, so you can show the encryption setting on any date. Lock down the bucket that holds the history (versioning, Object Lock) so the evidence cannot be changed.
- **If** an unencrypted Amazon Relational Database Service (RDS) instance appears, **then** let the AWS Config rule **`rds-storage-encrypted`** mark it **NON_COMPLIANT**, and use an **Amazon EventBridge** rule on that compliance change to open a **ticket** for a person. **This works because** encryption cannot be added to an existing instance in place; the fix is to **restore from an encrypted snapshot**, which is a planned manual job, not a quick automatic remediation.
- **If** you must show which policies were attached to an **Identity and Access Management (IAM)** role last quarter, **then** read the **AWS Config configuration history** for that role. **This works because** Config records IAM roles and policies as resources and keeps their configuration, including policy attachments, over time. IAM is a global resource type, so check which Region records it **(verify)**.
- **If** you want to stop anyone from turning off AWS Config recording, **then** add a **Service Control Policy (SCP)** that denies `config:StopConfigurationRecorder`, `DeleteConfigurationRecorder`, `DeleteDeliveryChannel` and `DeleteConfigRule`, except for security admins. **This works because** an SCP blocks these actions even for account administrators, who could otherwise stop the recorder with their own permissions.
- **If** AWS Config bills spike after you turn on recording of "all resource types", **then** switch to **specific types** (inclusion list) or **exclude** noisy types such as EC2 network interfaces and security group rules, and use **daily** recording for high-churn types. **This works because** continuous recording bills every **configuration item (CI)** (about **$0.003** each), so resources that change often create many CIs. Daily recording creates at most one CI per resource per day.
- **If** several compliance frameworks check the same controls, **then** use **AWS Security Hub consolidated controls** and remove duplicate conformance packs. **This works because** duplicate controls across standards create more AWS Config rules, and every rule **evaluation** is billed (about **$0.001** each for the first 100,000 per month **(verify tiers)**). A shared control is evaluated once.
- **If** you need to know whether an AWS CloudFormation stack has drifted from its template, **then** use **CloudFormation drift detection** and have **AWS Config** record CloudFormation stacks. **This works because** drift detection is a separate CloudFormation feature that finds the drift, and Config records the stack's **drift status** as part of its configuration, so it shows in history and rules.
- **If** you need to answer "which AWS Lambda functions run a deprecated runtime across all accounts", **then** run an **advanced query** on an AWS Config **aggregator**. **This works because** advanced queries use a **SQL-like** syntax over the **current** configuration of recorded resources, and the aggregator brings data from many accounts and Regions into one place.
- **If** AWS Control Tower **detective controls** show "Not available", **then** check that the **AWS Config recorder** is on in that account and Region, and that the **Config service-linked rules** exist. **This works because** Control Tower detective controls are Config rules, and a rule can only evaluate resources the recorder records.
- **If** auditors want evidence without broad admin access, **then** give them a **read-only Identity and Access Management (IAM) role**, an AWS Config **aggregator**, and **saved queries** (`PutStoredQuery`) for the checks they need. **This works because** the read-only role follows **least privilege**, the aggregator shows compliance across accounts in one place, and saved queries let them rerun the same checks.

Verified from AWS docs on 2026-11-09 (What is AWS Config, Config pricing, service quota summary).
Unconfirmed (verify): managed policy names; VPC endpoint availability; tag-based authorization for Config resources; exact free tier (none advertised); tiered evaluation prices; rule and aggregator limits; history delivery interval.

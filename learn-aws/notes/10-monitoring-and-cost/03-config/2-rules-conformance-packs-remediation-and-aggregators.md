# AWS Config – 2. Rules, conformance packs, remediation and aggregators

Short notes. Each point is a fact you can be asked about.

## A. Config rules
- A **Config rule** evaluates whether a resource's configuration **complies** with a desired setting. Results are per resource.
- **Compliance states**: **COMPLIANT**, **NON_COMPLIANT**, **NOT_APPLICABLE**, **INSUFFICIENT_DATA**. A rule's overall state is NON_COMPLIANT if any in-scope resource is non-compliant.
- **Rule types**:
  - **Managed rules**: prebuilt by AWS (hundreds), for example `s3-bucket-public-read-prohibited`, `s3-bucket-server-side-encryption-enabled`, `encrypted-volumes`, `rds-storage-encrypted`, `redshift-cluster-kms-enabled`, `cloud-trail-enabled`, `iam-user-mfa-enabled`, `root-account-mfa-enabled`, `cmk-backing-key-rotation-enabled`, `lambda-function-public-access-prohibited`, `access-keys-rotated`, `restricted-ssh`, `vpc-flow-logs-enabled`, `cloudwatch-log-group-encrypted`, `glue-job-logging-enabled` **(verify exact names)**.
  - **Custom rules with AWS Lambda**: your function evaluates the resource and calls `PutEvaluations`.
  - **Custom rules with AWS CloudFormation Guard** (policy-as-code DSL): **no Lambda** needed; write Guard rules over the CI JSON.
  - **Service-linked rules**: created by other services (Security Hub, Control Tower, Firewall Manager); you cannot edit them.
- **Trigger types** (detective mode):
  - **Configuration changes**: evaluated when a CI for an in-scope resource changes (scope by resource type, tag, or specific ID).
  - **Periodic**: evaluated at a frequency (1, 3, 6, 12 or 24 hours).
  - **Hybrid**: both (custom Lambda rules).
- **Evaluation modes**:
  - **Detective**: evaluates **deployed** resources after they exist.
  - **Proactive**: evaluates **resource configurations before deployment** (via `StartResourceEvaluation` API or CloudFormation Hooks) to stop non-compliant resources earlier.
- **Rule parameters**: managed rules accept parameters (for example required tag keys, max access key age).
- **Scope of changes**: choose resource types, tag key/value, or one resource.
- **Re-evaluation**: `StartConfigRulesEvaluation` forces a rule evaluation; changing a rule or recorded types also triggers evaluation.
- **Compliance timeline**: each resource shows compliance history.
- **Rule limits**: **1,000 rules per account per Region** (adjustable) **(verify)**.
- **Cost**: each **evaluation** is billed (about **$0.001 for the first 100,000 per Region per month**, then cheaper tiers); proactive evaluations also billed; rules with both modes may not double-bill.
- **Dependency**: a rule only evaluates resources the **recorder records**. If a resource type is not recorded, the rule shows no data.

## B. Remediation
- **Remediation actions** fix NON_COMPLIANT resources using **AWS Systems Manager Automation documents** (runbooks), for example `AWS-DisablePublicAccessForSecurityGroup`, `AWS-EnableS3BucketEncryption`, `AWSConfigRemediation-*` documents.
- **Manual** (you click remediate) or **automatic** (Config runs it when a resource becomes NON_COMPLIANT).
- **Automatic retry**: configure **maximum attempts** (up to 25) and **retry interval** **(verify)**.
- **Parameters**: static values or **resource ID** parameter (`ResourceValue`) to pass the non-compliant resource.
- **Execution role**: an **IAM role** that SSM Automation assumes (`AutomationAssumeRole`) with only the permissions needed to fix.
- **Custom remediation**: write your own runbook (SSM document) or trigger Lambda via EventBridge instead.
- **Safety**: start with manual remediation; add approvals (SSM `aws:approve` step) for production; log all actions; avoid remediation that breaks data pipelines (for example blocking public access on a bucket serving a website).
- **Exceptions**: remove a resource from automatic fix by excluding it from rule scope or marking **exceptions** with `PutRemediationExceptions` **(verify)**.
- **Multi-account**: use **organization conformance packs** plus StackSets to deploy runbook roles; or EventBridge in a central account.
- **Notifications**: EventBridge "compliance change" → SNS/chat/ticket for human fixes.

## C. Conformance packs
- A **conformance pack** is a **collection of Config rules and remediation actions** defined in a **YAML template** (CloudFormation-like) and deployed as a **single unit** to an account/Region or **organization**.
- Includes **sample packs** aligned to frameworks: **CIS, PCI DSS, HIPAA, NIST 800-53, FedRAMP, Operational Best Practices for S3, DynamoDB, Redshift, etc.**
- **Compliance score** (for packs): shows percent of compliant rules/resources.
- **Limits**: **50 conformance packs** per account per Region; **130 rules** per pack **(verify)**.
- **Organization conformance packs**: deployed from the management or delegated administrator account to all accounts (or OUs) in the organization; exclude accounts if needed.
- **Pack templates** live in an S3 bucket (name prefix `awsconfigconforms`) or are passed inline.
- **Pack cost**: each rule evaluation is billed as a **conformance pack evaluation** (about $0.001 for the first 100,000).
- **Updating**: change the template and redeploy; Config updates rules/remediations.
- **Deleting a pack** removes its rules and remediation configurations.
- **Use packs** when you need repeatable, framework-aligned governance across many accounts.

## D. Organization rules (multi-account)
- **Organization Config rules** deploy a rule to all member accounts from the management or delegated administrator account.
- Requirements: **Organizations (all features)**, trusted access for `config-multiaccountsetup.amazonaws.com`, Config enabled (recorder) in member accounts.
- **Delegated administrator** for Config: register to avoid using the management account.
- Rules are **read-only in member accounts** (managed by the administrator).
- **Excluded accounts** list lets you skip some accounts.
- Deploys using service-managed StackSet-like mechanism; propagation can take minutes.

## E. Aggregators (multi-account, multi-Region view)
- An **aggregator** collects **configuration and compliance data** from **multiple accounts and Regions** into one **aggregator account and Region** (read-only view).
- **Sources**: individual account IDs (each must **authorize** the aggregator account/Region via **aggregation authorization**) or an **Organization** (all accounts, auto-includes new ones; needs trusted access).
- **Up to 50 aggregators** per account **(verify)**.
- **What you can do**: dashboard of inventory and compliance, **advanced queries across accounts**, view compliance by rule/account/resource, drill into non-compliant resources.
- **What you cannot do**: change resources or rules in source accounts from the aggregator; remediation is performed in each source account.
- **Aggregator vs organization rules**: aggregator **views** data; organization rules/packs **deploy** rules.
- **Data stays in source accounts**; aggregator copies compliance/config metadata.
- **Cost**: aggregators do not add recorder charges by themselves; source accounts pay for CIs and evaluations.

## F. Integrations
- **Security Hub**: most standards controls are implemented as **Config service-linked rules**; Security Hub requires Config recording.
- **Control Tower**: **detective controls** are Config rules (and mandatory Config recording / central S3 bucket).
- **Firewall Manager**: needs Config to detect resources.
- **AWS Backup, Audit Manager**: use Config data for evidence.
- **CloudFormation**: Config records stacks; **CloudFormation Hooks** + proactive rules; drift status as resource.
- **CloudTrail**: CIs reference related events; Config evaluates **API-driven changes**.
- **EventBridge/SNS**: change and compliance notifications.
- **Athena/QuickSight**: analyze config history/snapshots in S3.
- **Service Catalog / Systems Manager**: remediation runbooks and inventory.

## G. Authoring custom rules
- **Guard (preferred for simple checks)**: write `rule` blocks over the CI, for example require `configuration.encrypted == true`; test with `cfn-guard`.
- **Lambda**: get `invokingEvent`, `ruleParameters`; fetch the CI (`configurationItem`), compute compliance, call `PutEvaluations` with `ResultToken`; handle `ScheduledNotification` vs `ConfigurationItemChangeNotification` vs `OversizedConfigurationItemChangeNotification`.
- **Lambda permissions**: allow `config.amazonaws.com` to invoke; role with `config:PutEvaluations`.
- **Best practice**: idempotent, fast (< timeout), cover NOT_APPLICABLE cases, version your rule code, test with sample events.
- **Annotations** (up to 256 chars) explain why a resource is non-compliant.

## H. Monitoring, troubleshooting and cost control
- **Rule shows NO_DATA / INSUFFICIENT_DATA** → resource type not recorded, rule scope too narrow, evaluation not yet run.
- **Everything NON_COMPLIANT after enabling a rule** → expected for existing resources; plan remediation waves.
- **Remediation fails** → `AutomationAssumeRole` missing permissions, wrong parameter mapping, SSM Automation concurrency/quotas, resource in use.
- **Custom Lambda rule failing** → timeout, missing `PutEvaluations` permission, invoke permission, oversized CI.
- **Aggregator shows missing accounts** → authorization not accepted, organization trusted access not enabled, recorder off.
- **Conformance pack deploy fails** → rule not supported in Region, resource type not recorded, template errors, quota.
- **Cost surprises** → continuous recording of noisy types (network interfaces, security group rules), many rules × many resources, frequent periodic rules. Fix with exclusion lists, daily recording, fewer/targeted rules, scope by tag.
- **Evaluations delayed** → throttling; eventual consistency.
- **Cost reference**: continuous recording about **$0.003 per CI**; daily/periodic about **$0.012 per CI** (but at most one per resource per day); rule evaluations about **$0.001 each** for the first 100,000 per month **(verify tiers)**.

## I. Limits cheat sheet
| Item | Value |
|---|---|
| Config rules per account/Region | **1,000** **(verify)** |
| Conformance packs per account/Region | **50** |
| Rules per conformance pack | **130** |
| Aggregators per account | **50** **(verify)** |
| Recorders / delivery channels per Region | **1 / 1** |
| Retention of configuration data | **30 days – 7 years** (default 7 years) |
| Periodic rule frequency options | 1, 3, 6, 12, 24 hours |
| Remediation attempts | up to **25** **(verify)** |
| Pricing (indicative) | $0.003/CI continuous; $0.012/CI periodic; $0.001/evaluation (first 100k) |

## J. Exam skills mapping
- **4.5.4 View configuration changes (Config)**: rules, conformance packs, aggregators.
- **3.3.3 Notifications for alerts**: compliance notifications.

## K. Scenarios: "If X → Y, because Z"
- If a bucket becomes public and must be fixed automatically → **Config rule `s3-bucket-public-read-prohibited` + auto remediation with an SSM runbook**, because Config detects drift and SSM fixes it.
- If you need CIS/PCI checks in 50 accounts → **organization conformance pack from a delegated administrator**, because it deploys rules centrally.
- If you need to block a non-compliant resource before deployment → **proactive rules/CloudFormation Hooks**, because proactive mode evaluates the template first.
- If you need a cross-account compliance dashboard → **organization aggregator**, because it centralizes inventory and compliance.
- If custom logic is simple (a property equals a value) → **Guard custom rule**, because it avoids Lambda code and cost.
- If a rule must check complex logic or call another API → **Lambda custom rule**, because Guard only reads the CI.
- If remediation could break production → **manual remediation with approval step**, because automation may be disruptive.
- If you only want some noisy resources checked daily → **periodic rule + daily recording**, because it cuts CI and evaluation counts.
- If Security Hub controls show no data → **enable the Config recorder for those resource types**, because controls rely on Config rules.
- If a compliance change must notify a team → **EventBridge rule on Config Rules Compliance Change → SNS**, because Config emits events when state changes.

Verified from AWS docs on 2026-11-09 (What is AWS Config, Config pricing, service quota summary).
Unconfirmed (verify): managed rule names; rule/aggregator/pack/remediation limits; Guard rule support details; exception API; delegated administrator registration; evaluation tier prices; proactive mode double-billing.

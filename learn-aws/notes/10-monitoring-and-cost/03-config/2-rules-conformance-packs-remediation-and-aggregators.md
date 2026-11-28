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
- **If** an Amazon S3 bucket becomes public and must be fixed automatically, **then** add the **AWS Config managed rule `s3-bucket-public-read-prohibited`** **(verify exact names)** and attach an **automatic remediation** that runs an **AWS Systems Manager (SSM) Automation runbook**. **This works because** the rule marks the bucket **NON_COMPLIANT** when its configuration changes, and Config then runs the runbook through an IAM role (`AutomationAssumeRole`) to fix it. Be careful: blocking public access can break a bucket that really serves a website.
- **If** you need CIS or PCI DSS checks in 50 accounts, **then** deploy an **organization conformance pack** from a **delegated administrator** account. A **conformance pack** is a set of AWS Config rules and remediation actions in one **YAML template**, and sample packs exist for CIS, PCI DSS, HIPAA and more. **This works because** an organization pack is deployed once to **all accounts (or OUs)** in AWS Organizations, and a delegated administrator avoids using the management account. Limits: **50 packs** per account per Region and **130 rules** per pack **(verify)**.
- **If** you need to block a non-compliant resource before it is deployed, **then** use AWS Config **proactive** rules, run through the `StartResourceEvaluation` API or **AWS CloudFormation Hooks**. **This works because** proactive mode evaluates the **resource configuration before deployment**, while the normal **detective** mode only checks resources after they exist. Proactive evaluations are billed too.
- **If** you need one compliance dashboard across many accounts, **then** create an AWS Config **aggregator** with an **AWS Organizations** source. **This works because** an aggregator copies configuration and compliance data from many accounts and Regions into **one account and Region**, and an Organizations source adds new accounts automatically (it needs trusted access). The view is **read-only**: remediation still runs in each source account.
- **If** your custom check is simple, for example a property must equal a value (`configuration.encrypted == true`), **then** write a **custom rule with AWS CloudFormation Guard**, a policy-as-code language. **This works because** Guard rules read the **configuration item (CI)** JSON directly, so you need **no AWS Lambda** code or Lambda cost.
- **If** a rule needs complex logic or must call another API, **then** write a **custom rule with AWS Lambda**: your function gets the configuration item, works out compliance and calls **`PutEvaluations`**. **This works because** Lambda can run any code, while **AWS CloudFormation Guard** can only read the configuration item (CI). The function must allow `config.amazonaws.com` to invoke it and must finish before its timeout.
- **If** an automatic fix could break production (for example blocking public access on a bucket that serves a website), **then** use **manual remediation** and add an **approval step** (the AWS Systems Manager (SSM) `aws:approve` step) to the runbook. **This works because** automatic remediation runs as soon as a resource becomes NON_COMPLIANT and can be disruptive, while an approval lets a person check first.
- **If** you only want some noisy resources checked once a day, **then** use a **periodic** AWS Config rule (every **24 hours**) together with **daily recording** for those resource types. **This works because** daily recording creates at most **one configuration item (CI) per resource per day**, and a periodic rule runs on a schedule instead of on every change, so both CI and **evaluation** counts (each billed) go down.
- **If** AWS Security Hub controls show no data, **then** make sure the **AWS Config recorder** is on and records the resource types those controls check. **This works because** most Security Hub controls are **Config service-linked rules**, and a rule only evaluates resources the recorder records; a type that is not recorded gives no data.
- **If** a team must be told when compliance changes, **then** create an **Amazon EventBridge** rule on the **Config Rules Compliance Change** event **(verify names)** that sends to an **Amazon Simple Notification Service (SNS)** topic. **This works because** AWS Config emits an event each time a rule's compliance state changes, for example to NON_COMPLIANT. SNS then delivers it to email, chat or a ticket.

Verified from AWS docs on 2026-11-09 (What is AWS Config, Config pricing, service quota summary).
Unconfirmed (verify): managed rule names; rule/aggregator/pack/remediation limits; Guard rule support details; exception API; delegated administrator registration; evaluation tier prices; proactive mode double-billing.

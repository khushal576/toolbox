# AWS Control Tower – 2. Landing zone, controls, Account Factory and operations

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS Control Tower** sets up and governs a **secure multi-account environment (landing zone)** using best practices. It **orchestrates** Organizations, Service Catalog, IAM Identity Center, CloudTrail, Config, CloudFormation StackSets/hooks, KMS and more.
- Goal: get a governed multi-account baseline in **under an hour**, then keep it governed with **controls** and **drift detection**.
- **No extra charge for Control Tower itself**; you pay for the underlying services it uses (Config, CloudTrail, S3, KMS, Service Catalog, etc.) **(verify)**.
- Pick it when: you start a new multi-account setup, need **account vending**, and want **prescriptive guardrails** without building a landing zone yourself.
- Avoid / supplement when: you need heavily customized OU structures or controls beyond the catalog → use **Organizations + custom IaC + Config conformance packs**, or extend with **CfCT / AFT**.
- DEA-C01: governance guardrails and data sovereignty (4.5), central logging (4.4).

## B. Core concepts
- **Landing zone**: the enterprise-wide multi-account environment Control Tower builds: OUs, accounts, Identity Center, logging, controls.
- **Home Region**: the Region where you launch Control Tower; **cannot be changed** later without decommissioning. Governed Regions are chosen separately.
- **Governed Regions**: Regions where Control Tower applies controls and resources. You can add Regions later by updating the landing zone.
- **Foundational OUs**: **Security** OU (holds the shared accounts) and **Sandbox** OU (default for experiments). More OUs can be created (**Custom**).
- **Shared accounts** (created by Control Tower):
  - **Management account** (existing).
  - **Log Archive account**: central S3 buckets for **CloudTrail and Config logs** from all enrolled accounts.
  - **Audit account** (security tooling): read/cross-account roles for security and audit teams; SNS topics for control notifications.
- **IAM Identity Center** is set up by default (or you can use an external IdP) with groups such as **AWSControlTowerAdmins**, **AWSSecurityAuditors**, **AWSAccountFactory**.
- **Account Factory**: standardized account provisioning through **Service Catalog**; captures email, name, OU, optional network baseline (VPC) and tags.
- **Enrollment**: bring an **existing** account/OU under Control Tower governance (register OU, enroll accounts).
- **Drift**: divergence from the expected baseline (for example someone moves an account or edits a controlled SCP). Detected and flagged; fix by **re-register / update**.
- **Dashboard**: shows accounts, OUs, enabled controls, non-compliant resources, drift.

## C. Controls (guardrails)
- A **control** is a high-level rule for governance. **Three types by how they work**:
  - **Preventive**: stop the action. Implemented with **SCPs** (and **RCPs**). States: Enforced / Not enabled.
  - **Detective**: detect non-compliance after the fact. Implemented with **AWS Config rules** (and Security Hub standards). States: Clear / In violation / Not available.
  - **Proactive**: check **before deployment**. Implemented with **CloudFormation Hooks** that block non-compliant resources in templates. States: Pass / Fail / Skip.
- **Behavior guidance**: **Mandatory** (always on, cannot disable; for example disallow changes to log archive buckets, enable CloudTrail), **Strongly recommended** (best practice), **Elective** (optional, for specific needs).
- **Control catalog** has hundreds of controls (pre-built; also maps to frameworks like **NIST, PCI DSS, CIS**) managed in the **Controls Reference Guide**.
- Controls are **enabled per OU** and apply to all accounts in the OU (including child OUs).
- **Region deny control**: preventive control that **denies use of non-governed Regions** (implemented via SCP) — key for **data sovereignty** (4.5.5). There is an OU-level and landing-zone-level variant **(verify)**.
- **Examples** (relevant to data engineers): disallow public read on S3 buckets, require S3 encryption, detect unencrypted EBS/RDS/Redshift, detect public RDS/Redshift, require CloudTrail log validation, disallow deletion of Log Archive, disallow changes to Control Tower's IAM roles/Config.
- **Custom controls**: you can create **detective controls** from your own **Config rules / Config managed rules**, and **proactive** via Hooks **(verify scope)**.
- **Control limits**: a landing-zone OU can have up to **10 SCPs** (Control Tower limit); many controls share SCP statements to stay within it; large control sets may need consolidation.
- **Control concurrency**: up to **100** control operations in flight overall; **10 at a time actively**, others queue (`EnableControl`/`DisableControl` APIs).
- **Control status** is visible on the dashboard; **Config rules** exist in each enrolled account/Region.
- **Controls do not replace IAM**; they add guardrails on top.

## D. Account Factory family
- **Account Factory (console/Service Catalog)**: self-service account creation with a standard template.
- **Account Factory for Terraform (AFT)**: GitOps pipeline using Terraform to **provision and customize** accounts; uses CodePipeline/CodeBuild/Step Functions/Lambda/DynamoDB; deployed in the Control Tower home Region (not available in some Regions).
- **Account Factory Customization (AFC)**: blueprint-based post-provisioning customization using **Service Catalog products** (CloudFormation or Terraform blueprints; Terraform blueprints deploy to **one Region**, by default the home Region).
- **Customizations for AWS Control Tower (CfCT)**: GitOps solution deploying **CloudFormation templates and SCPs** to OUs/accounts through a manifest; not in some Regions.
- **Concurrency**: accounts can be **provisioned/updated/enrolled concurrently up to 5**; **unmanage** one at a time; most other operations **one at a time**.
- **Network baseline**: Account Factory can create a **default VPC** configuration; typical practice is to **delete default VPCs** and use a central network account.
- **Auto-enrollment** of accounts moved into a registered OU.
- **Email uniqueness** applies as in Organizations.

## E. Operations and lifecycle
- **Set up landing zone** (home Region, governed Regions, OUs, log retention, KMS key option, Identity Center settings).
- **Update landing zone** when AWS releases new versions or you add Regions/OUs; needs **no manual changes in managed resources** (do not edit Control Tower-owned CloudFormation StackSets/roles).
- **Do not modify** resources created by Control Tower (roles `aws-controltower-*`, Config recorders, CloudTrail trail, StackSets); the **mandatory controls** deny some changes.
- **Repair** drift via **Re-register OU**, **Update account**, or **Repair landing zone**.
- **Decommission**: you can delete the landing zone (accounts are not deleted).
- **Trusted access / service-managed StackSets** are used for baselines.
- **Log retention** settings for S3 logs and access logs.
- **Encryption**: optional customer managed KMS key for CloudTrail/Config logs.
- **Existing org**: you can set up Control Tower in an org that already has accounts (requirements apply: Config not already recording in a conflicting way, no existing conflicting trail names, etc.) and **enroll** accounts.
- **Concurrency**: one operation at a time (with exceptions listed above). A long enrollment blocks other changes.
- **Supported size**: up to **10,000 accounts** in the landing zone's organization; OUs with > 1,000 directly nested accounts cannot be registered.
- **Service Catalog dependency**: Regions without Service Catalog do not support Account Factory Customizations.

## F. Integration with data and security services
- **Central logging**: CloudTrail organization trail and Config recording delivered to the **Log Archive** bucket (encrypted, access-controlled, protected by mandatory controls).
- **Security**: designate **Audit** account as delegated administrator for **GuardDuty, Security Hub, Macie, Config aggregator** (common pattern).
- **Data governance**: place **data lake accounts** (raw/curated/consumers) in OUs with different controls (for example stricter encryption controls in sensitive-data OU). Pair with **Lake Formation** for data-level access.
- **Cross-account data sharing** remains your design (RAM, LF, bucket policies) but sits within the guardrails.
- **Identity**: Identity Center permission sets give access to the Control Tower-managed accounts.
- **Sandbox OU**: budget-limited playground with Budgets alerts; looser controls.

## G. Control Tower vs alternatives
| Need | Control Tower | Organizations only | Landing Zone Accelerator (LZA) | Custom IaC |
|---|---|---|---|---|
| Time to value | **Fast** | Manual | Medium (config-driven) | Slow |
| Guardrail catalog | **Yes (managed)** | You write SCPs | Yes (config) | You write |
| Customization | CfCT/AFT/AFC | Anything | **High** (YAML config) | Anything |
| Maintenance | AWS-managed updates | You | You (solution updates) | You |
| Best for | Standard multi-account governance | Simple or custom needs | Regulated/complex environments | Full control |
- **LZA** (Landing Zone Accelerator on AWS) is an open-source solution deployed via CloudFormation/CDK for more complex compliance-heavy landing zones; can run **with Control Tower**.
- **Organizations alone** gives structure and SCPs but not account vending, baselines, dashboards or managed detective controls.

## H. Cost
- Control Tower: **no additional charge**; you pay for **Config** (configuration items and rule evaluations in each account/Region), **CloudTrail** (additional trails/data events), **S3** logs, **KMS**, **Service Catalog** API usage (small), **IAM Identity Center** (free), **CloudWatch** and any resources Account Factory baselines create (VPCs, NAT gateways).
- **Config cost** grows with the **number of accounts × governed Regions × enabled detective controls**.
- **Cost levers**: limit **governed Regions** to those you use; avoid unnecessary elective detective controls; set **log retention** lifecycle; use Region deny so resources (and Config costs) don't spread.

## I. Monitoring and troubleshooting
- **Landing zone drift** shown on the dashboard; notifications via SNS in the Audit account.
- **Failed enrollment**: common causes: existing AWS Config recorder/delivery channel conflicts, existing CloudTrail/IAM role names (`AWSControlTowerExecution`), missing `AWSControlTowerExecution` role in the account being enrolled, service-linked role issues, SCPs blocking Control Tower, unsupported Regions.
- **`AWSControlTowerExecution` role** must exist in enrolled accounts, trusting the management account.
- **Control stuck / failed**: check Config rule deployment in the account, StackSet instance status, SCP size limit (10 per OU).
- **Cannot change home Region** → decommission and rebuild.
- **Account Factory failing** → Service Catalog product portfolio permissions, unique email, quota of accounts.
- **Detective control "In violation"** → fix the resource, or if intended, adjust the control scope (cannot exempt per resource in the managed control; consider custom Config rule with exceptions).
- **Mandatory control blocks your change** → expected; work through Control Tower APIs/IaC.
- **CloudTrail**: Control Tower API calls (`SetupLandingZone`, `EnableControl`, `CreateManagedAccount`).
- **EventBridge** control-related and lifecycle events (account created/enrolled, control state changes) for automation.

## J. Limits cheat sheet
| Item | Value |
|---|---|
| Accounts supported | **10,000** (shared among OUs) |
| Directly nested accounts in an OU to register | **≤ 1,000** |
| SCPs per OU in landing zone | **10** |
| Control operations | **100** in progress, **10** concurrent |
| Account Factory concurrent operations | **5** |
| Landing zone operations | **one at a time** (mostly) |
| Home Region | fixed after setup |
| AFT concurrency defaults | 5 provisioning, 5 customizations |
| Regions | some do not support CfCT, AFT, or Service Catalog |

## K. Exam skills mapping
- **4.5.3 Prevent backups or replication to disallowed Regions**: Region deny control.
- **4.5.5 Data sovereignty**: data sovereignty.
- **4.5.4 View configuration changes (Config)**: detective controls via Config.

## L. Scenarios: "If X → Y, because Z"
- **If** you are starting a multi-account AWS setup and want standard best practices without building it yourself, **then** set up an **AWS Control Tower landing zone**. A landing zone is the governed multi-account environment: OUs, shared **Log Archive** and **Audit** accounts, **IAM Identity Center** for sign-in, central logging and controls. **This works because** Control Tower **orchestrates** AWS Organizations, IAM Identity Center, AWS CloudTrail, AWS Config, StackSets and more to build this baseline in **under an hour**, then keeps it governed with **controls** and **drift detection**.
- **If** data must stay in two approved Regions, **then** make only those two the **governed Regions** and enable the **Region deny control** on the OU or landing zone **(verify)**. This is a **preventive** control built on a **service control policy (SCP)** that denies use of non-governed Regions. **This works because** the SCP blocks API calls in any other Region, which supports **data sovereignty** (keeping data in allowed places).
- **If** you want to block unencrypted Amazon S3 buckets **before** they are deployed, **then** enable a **proactive control**, built on **AWS CloudFormation Hooks**. **This works because** the Hook checks the template and **fails** it (state **Fail**) before any non-compliant resource exists.
- **If** you only need to **know** about unencrypted Amazon Elastic Block Store (EBS) volumes, not block them, **then** enable a **detective control**, built on an **AWS Config rule**. **This works because** it checks resources after they exist and **reports** them as **In violation** without blocking anything.
- **If** developers must not be able to disable AWS CloudTrail, **then** rely on **mandatory preventive controls**, built on **SCPs**. Mandatory controls are always on and cannot be disabled; enabling CloudTrail is one of them. **This works because** an SCP **denies** the action itself, so even admins in the account cannot turn logging off.
- **If** every new team must get an account with a baseline VPC and standard tags, **then** use **Account Factory**, or **Account Factory for Terraform (AFT)** if you want a Terraform GitOps pipeline. Account Factory provisions accounts through **AWS Service Catalog** and captures email, name, OU, optional network baseline and tags. **This works because** every account is **vended** from the same template, so all accounts start the same; up to **5** accounts can be provisioned at once.
- **If** you need your own custom resources deployed to every account in an OU, **then** use **Customizations for AWS Control Tower (CfCT)** or **Account Factory Customization (AFC)** blueprints. CfCT deploys CloudFormation templates and SCPs to OUs/accounts from a manifest; AFC applies Service Catalog blueprints after provisioning. **This works because** both **extend** the Control Tower baseline instead of editing Control Tower-owned resources.
- **If** someone moved an account to a different OU by hand, **then** Control Tower flags **drift**; fix it with **Re-register OU** or **Update account**. **This works because** Control Tower tracks the expected baseline, including where each account should sit.
- **If** enrolling an existing account into Control Tower fails, **then** check for a conflicting **AWS Config recorder or delivery channel** and whether the **`AWSControlTowerExecution` role** exists (trusting the management account) **(verify)**. **This works because** these are the typical blockers; others are existing CloudTrail/IAM role names, service-linked role issues, SCPs blocking Control Tower and unsupported Regions.
- **If** the company needs heavy custom compliance (many frameworks, a custom network design), **then** use **Landing Zone Accelerator on AWS (LZA)**, an open-source solution deployed with CloudFormation/CDK; it can run **with Control Tower** **(verify)**. **This works because** LZA is driven by **YAML configuration** and is highly customizable, built for regulated and complex environments, while Control Tower alone favors standard setups.
- **If** AWS Config costs keep rising across many Regions, **then** **reduce the governed Regions** to those you use and turn off unneeded **elective detective controls**. **This works because** Config cost grows with **accounts × governed Regions × enabled detective controls**, since each adds recording and rule evaluations. Region deny also stops resources, and their Config cost, spreading to other Regions.

Verified from AWS docs on 2026-11-03 (What is AWS Control Tower, Control Tower limitations and quotas, Organizations quotas).
Unconfirmed (verify): Control Tower pricing statement; Region deny control variants; custom control scope (Config/Hooks); specific list of mandatory controls; framework mappings; exact enrollment prerequisites; LZA relationship; dashboard and notification details.

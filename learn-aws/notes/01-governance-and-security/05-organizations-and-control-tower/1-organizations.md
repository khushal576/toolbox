# AWS Organizations – 1. Multi-account structure, policies and operations

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS Organizations** lets you **group many AWS accounts** under one organization for **central governance, consolidated billing and shared services**.
- It is a **global** service (control plane in `us-east-1`). No extra charge.
- Why many accounts: **blast-radius isolation**, separate **environments** (dev/test/prod), separate **teams/data domains**, clean **billing**, easier **compliance boundaries**. The account is the strongest IAM/billing boundary.
- Data-engineering patterns: separate accounts for **raw/curated/consumer** data lake zones, a **central governance/catalog** account, **shared services/network**, **log archive** and **security tooling** accounts, **sandbox** accounts.
- DEA-C01: **4.5 data governance / sovereignty / guardrails**, **4.1–4.2** cross-account access, **4.4** central logging.

## B. Building blocks
- **Organization**: one **root** (exactly **one**), a **management account**, member accounts, OUs.
- **Management account** (formerly master/payer): creates the org, pays the bill, **not restricted by SCPs/RCPs**. Keep it **free of workloads**; protect it strictly (MFA, few admins).
- **Member account**: any other account; can belong to only **one organization** at a time.
- **Organizational unit (OU)**: container for accounts/OUs; **nesting up to 5 levels** under the root; up to **2,000 OUs**.
- **Root**: top container; policies attached to the root apply everywhere.
- **Delegated administrator**: a member account that administers an integrated service (Security Hub, GuardDuty, Macie, Config, Access Analyzer, Identity Center, Backup, Firewall Manager, CloudFormation StackSets, IPAM…) so you avoid using the management account.
- **Trusted access**: you enable an AWS service to work across the org (`EnableAWSServiceAccess`).
- **Organization-wide features** need **"All features"** mode. In **consolidated billing only** mode you only get billing, no SCPs.
- **Service-linked role** `AWSServiceRoleForOrganizations` is created for the service.
- **OrganizationAccountAccessRole**: role auto-created in accounts **created** via Organizations (trusting the management account) giving admin access; **not** created for invited accounts (you create it yourself).
- **Tags**: up to **50 tags** on roots, OUs, accounts.

## C. Account lifecycle
- **Create** a member account (`CreateAccount`): needs a **unique email** per account; takes minutes; up to **5 concurrent** creations. Alternatively **invite** an existing account (handshake valid **15 days**).
- **New accounts** may have a low initial account quota (default maximum **10 accounts** for an organization until you raise it; can go up to 50,000 by request, approved case by case).
- **Remove/leave**: an account created in Organizations can be removed only after a **minimum age of 4 days** and when it has its own payment method and contact info; the management account cannot leave unless it deletes the org.
- **Close** an account: closed accounts count toward the account quota until **permanently closed** (post-closure period). Close limits: 250 (or 20% of accounts) per 30 days, max 1,000; **3 concurrent** closures.
- **Move accounts** between OUs (`MoveAccount`) to change inherited policies.
- **Root user of member accounts**: with **centralized root access management** you can remove root credentials and do privileged root tasks via short sessions **(verify)**.
- **Alternate contacts** (billing, security, operations) should be set per account.
- **Regions**: opt-in Regions are enabled per account; control with SCP `aws:RequestedRegion`.

## D. Policy types
| Policy type | Purpose | Max size | Max per target (direct) | Max in org |
|---|---|---|---|---|
| **Service control policy (SCP)** | Max permissions for **IAM principals** | **10,240** chars | **10** | 10,000 |
| **Resource control policy (RCP)** | Max permissions on **resources** | **5,120** | **5** (incl. `RCPFullAWSAccess`) | 2,000 |
| **Declarative policy** | Enforce **service configuration baseline** | 10,000 | 10 | 1,000 |
| **Backup policy** | Org-wide **AWS Backup plans** | 10,000 | 10 | 1,000 |
| **Tag policy** | Standardize **tag keys/values** | 10,000 | 10 | 1,000 |
| **Chat applications policy** | Control Slack/Teams chat config | 10,000 | 5 | 1,000 |
| **AI services opt-out policy** | Opt out of AI content use | 2,500 | 5 | 1,000 |
| **Security Hub policy** | Central Security Hub configuration | 10,000 | 10 | 1,000 |
- Policies **inherit** down from root → OU → account. Policies attached directly count against limits; **inherited ones do not**.
- **Console strips whitespace** before counting size; **CLI/SDK does not**.
- **SCP** and **RCP**: see the IAM notes; both are **guardrails** (never grant), **do not affect the management account**, and do not affect service-linked roles.
- **Every entity must always have at least one SCP** attached (usually `FullAWSAccess`).
- **Effective policy** for tag/backup/declarative policies is the **merge** of inherited and attached policies; `DescribeEffectivePolicy` shows the result.
- **Tag policies** report non-compliant resources; can enforce for some resource types.
- **Backup policies**: define plans, vaults, rules, selections once; AWS Backup applies them in member accounts.
- **Declarative policies** (examples): block public EBS snapshot/AMI sharing, enforce IMDSv2, block public access to VPC resources, set default image/snapshot behavior **(verify attributes)**; enforced at the **service layer**, even for new APIs/features.

## E. Consolidated billing and cost
- One bill for all accounts; **volume discounts** (S3, data transfer) and **Savings Plans / Reserved Instances sharing** across accounts (can be turned off per account).
- **Cost allocation tags** and **Cost Categories**; view costs per account in Cost Explorer; **Budgets** at the org or account.
- **Billing transfer / responsibility transfer** between organizations (newer feature) **(verify)**.
- The management account sees **all** costs; members see their own (with permissions).
- **Organizations is free**; paying services cost normally.

## F. Integrations for data and security teams
- **CloudTrail organization trail**: one trail in the management (or delegated) account logs all accounts into a central S3 bucket.
- **AWS Config aggregator / org rules**: centralize compliance data and deploy rules org-wide.
- **Security Hub, GuardDuty, Macie, Inspector, Detective, Access Analyzer**: designate a delegated admin and **auto-enable** for new accounts.
- **IAM Identity Center**: org instance for single sign-on to all accounts (see IAM notes).
- **RAM (Resource Access Manager)**: share resources org-wide (subnets, Transit Gateway, Glue catalog tables via LF, License Manager); enable "sharing with AWS Organizations".
- **CloudFormation StackSets**: **service-managed** permissions deploy baselines to OUs, auto-deploy to new accounts.
- **Lake Formation / Glue catalog cross-account**: use RAM or LF grants; `aws:PrincipalOrgID` in S3/KMS policies for org-wide read.
- **S3 / KMS / SQS / Secrets Manager resource policies**: allow `aws:PrincipalOrgID` = org ID or `aws:PrincipalOrgPaths` for OU subsets.
- **Service Catalog**, **Firewall Manager** (org-wide WAF/SG policies), **Backup**, **Systems Manager** (Quick Setup), **Cost Optimization Hub**, **Compute Optimizer**.
- **Resource-based delegation policy** (up to 40,000 chars) lets the management account delegate specific read/policy-management APIs to a member account.

## G. Designing the account structure
- **Recommended OUs** (AWS prescriptive guidance): **Security** (log archive, audit/security tooling), **Infrastructure** (network, shared services), **Workloads** (prod/non-prod), **Sandbox**, **Policy staging**, **Suspended**, **Exceptions**, **Deployments**, **Transitional**.
- Put **similar policy needs** together; use OUs for **policy**, not for org chart reasons.
- **Prod vs non-prod** separation gives different SCPs (stricter in prod).
- **Data-lake multi-account**: producers (domain accounts), central catalog/governance account, consumers; share via Lake Formation + RAM.
- **Break-glass**: root recovery process documented; **delegated admins** for services.
- **Naming and email** convention: `aws+<env>-<workload>@company.com` aliases.
- **Account vending** automated by **Control Tower Account Factory** or IaC pipelines.
- **Avoid single giant account**: quotas are per account/Region, so many accounts also raise practical limits (for example Glue concurrent job runs, Lambda concurrency).

## H. Limits and numbers
| Item | Value |
|---|---|
| Roots per organization | **1** |
| Accounts (default) | **10** (adjustable up to 50,000 by request) |
| OUs per organization | **2,000** |
| OU nesting depth | **5** levels |
| SCP size / per target / per org | **10,240 chars / 10 / 10,000** |
| RCP size / per target / per org | **5,120 chars / 5 / 2,000** |
| Other policy types per org | 1,000 each |
| Tags per root/OU/account | **50** |
| Concurrent account creation | **5** |
| Concurrent account closure | **3** |
| Account removal minimum age (created accounts) | **4 days** |
| Invitation expiry | **15 days** |
| Enable-all-features request expiry | **90 days** |
| Invitation attempts per 24 h | max(20, account limit) |
| Delegation policy size | 40,000 chars |
| Service-specific caps | Security Hub/Macie/Inspector/Control Tower **10,000** accounts; Detective 1,200; Audit Manager 250; Identity Center 7,000 |
- API throttles are token-bucket (for example `DescribeAccount` 20/s base, 30 burst; `CreateAccount` 0.1/s).

## I. Exam skills mapping
- **4.5.3 Prevent backups or replication to disallowed Regions**: SCP guardrails on Regions.
- **4.5.5 Data sovereignty**: data sovereignty.
- **4.5.7 Governance framework and data sharing patterns**: governance structure.
- **4.4.1 CloudTrail for API calls (audit)**: organization trail.

## J. Scenarios: "If X → Y, because Z"
- **If** dozens of teams each need their own isolated environment but the company wants central control, **then** use **AWS Organizations** with **organizational units (OUs)** and **service control policies (SCPs)**. Organizations groups many AWS accounts under one organization; an OU is a folder of accounts; an SCP sets the maximum permissions for users and roles in those accounts. Give each team its own account and group accounts into OUs by policy need. **This works because** the **account** is the strongest isolation boundary, so a mistake in one account stays there (small blast radius), and policies attached to the root or an OU **inherit down** to every account below it.
- **If** a data bucket must be readable by every account in the company, **then** write an **Amazon S3 bucket policy** that allows access when the condition key **`aws:PrincipalOrgID`** equals your organization ID. **This works because** the condition matches any principal from any account in the organization, so **new accounts are included automatically** without editing the policy. Use **`aws:PrincipalOrgPaths`** instead if only some OUs should read.
- **If** production accounts must never use certain Regions or services, **then** attach an **SCP with a Deny** to the **Production OU**, for example a deny on Regions using the **`aws:RequestedRegion`** condition key. **This works because** an SCP is a **guardrail** that caps what IAM principals can do, so it blocks the action **even for account admins**. The catch: SCPs never grant anything, and they do **not** apply to the **management account** or to service-linked roles.
- **If** the security team needs one place to see all findings from every account, **then** make a member account the **delegated administrator** for **AWS Security Hub**, **Amazon GuardDuty** and **Amazon Macie**, and turn on **auto-enable** for new accounts. A delegated administrator is a member account allowed to run an integrated service for the whole organization. **This works because** findings from all accounts flow to that one account, new accounts join automatically, and the **management account stays free of workloads** and daily use.
- **If** every new account must get baseline logging and roles from day one, **then** use **AWS CloudFormation StackSets** with **service-managed** permissions and **auto-deploy** on the OU, or use **AWS Control Tower**. StackSets deploy one CloudFormation template to many accounts. **This works because** auto-deploy applies the baseline to any account that is created in, or moved into, the target OU, with no manual step.
- **If** you must stop any member account from leaving the organization, **then** attach an **SCP that denies `organizations:LeaveOrganization`**. **This works because** the SCP blocks the leave call from inside member accounts, so they stay under your guardrails and billing.
- **If** backups must be the same across all accounts, **then** attach a **backup policy** at the **OU**. A backup policy defines **AWS Backup** plans, vaults, rules and resource selections once. **This works because** AWS Backup then applies those plans in every member account below the OU, and the **effective policy** is the merge of inherited and attached policies.
- **If** tags are inconsistent and cost allocation by tag is unreliable, **then** use a **tag policy** together with an **SCP that requires tags on create**. A tag policy standardizes allowed tag keys and values. **This works because** the tag policy **reports** non-compliant resources (and can enforce only for some resource types), while the SCP **blocks** creating resources without the required tags.
- **If** you hit the default limit of **10 accounts** in the organization, **then** request a **quota increase** from the **management account** through **Service Quotas**. **This works because** only the management account can raise the organization's account quota; it can go up to **50,000** by request, approved case by case.
- **If** you invited an existing account and it has no **`OrganizationAccountAccessRole`**, **then** **create that role yourself** in the account, trusting the management account. This role gives the management account admin access into the member account. **This works because** Organizations auto-creates the role only in accounts **created** through Organizations, not in **invited** accounts **(verify)**.
- **If** the management account is running workloads, **then** **move them out** to member accounts and keep the management account empty, protected with MFA and few admins. **This works because** the management account is **not restricted by SCPs or resource control policies (RCPs)**, so a compromise there has no guardrails and the highest risk.

Verified from AWS docs on 2026-11-03 (Organizations quotas and service limits, SCPs, RCPs).
Unconfirmed (verify): centralized root access management details; declarative policy attribute list; billing/responsibility transfer; RAM org sharing steps; resource-based delegation policy use cases; OrganizationAccountAccessRole behaviours for invited accounts.

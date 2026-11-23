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
- If dozens of teams need isolated environments with central governance → **Organizations with OUs and SCPs**, because policies inherit down and accounts isolate blast radius.
- If a data bucket must be readable by all accounts in the company → **bucket policy with `aws:PrincipalOrgID`**, because new accounts are included automatically.
- If prod accounts must not use certain Regions or services → **SCP deny on the Production OU**, because it caps even admins.
- If you need one place to see all findings → **delegated administrator for Security Hub/GuardDuty/Macie with auto-enable**, because the management account stays clean.
- If a new account must get baseline logging and roles → **StackSets (service-managed, auto-deploy) or Control Tower**, because it applies to new accounts in the OU.
- If you must stop anyone from leaving the organization → **SCP deny `organizations:LeaveOrganization`**, because it blocks member-initiated exits.
- If backups must be standardized → **backup policy at the OU**, because AWS Backup plans apply org-wide.
- If tags are inconsistent for cost allocation → **tag policy + SCP requiring tags on create**, because the tag policy reports and the SCP enforces.
- If you hit the account limit of 10 → **request a quota increase from the management account via Service Quotas**, because only the management account can raise it.
- If invitations to existing accounts do not create `OrganizationAccountAccessRole` → **create the role manually**, because only accounts created via Organizations get it.
- If the management account runs workloads → **move them out**, because SCPs do not apply there and compromise risk is highest.

Verified from AWS docs on 2026-11-03 (Organizations quotas and service limits, SCPs, RCPs).
Unconfirmed (verify): centralized root access management details; declarative policy attribute list; billing/responsibility transfer; RAM org sharing steps; resource-based delegation policy use cases; OrganizationAccountAccessRole behaviours for invited accounts.

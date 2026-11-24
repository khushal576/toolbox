# AWS IAM and STS – 3. Identity Center, Organizations guardrails (SCP/RCP) and Access Analyzer

Short notes. Each point is a fact you can be asked about.

## A. IAM Identity Center (workforce access)
- **IAM Identity Center** (successor to AWS SSO) gives **central sign-in** to many **AWS accounts** and **applications** with one identity.
- **Instance types**: **organization instance** (recommended; enabled in the management account, manages access to all accounts) and **account instance** (limited to apps in one account) **(verify names)**. **Only one Identity Center instance per organization/account.**
- **Identity source** (pick one at a time):
  - **Identity Center directory** (built-in users and groups).
  - **Active Directory** (AWS Managed Microsoft AD or AD Connector; **one connected directory at a time**).
  - **External IdP** (Okta, Entra ID, Ping…) via **SAML 2.0** for sign-in plus **SCIM** to sync users and groups.
- **Permission set**: a template of policies (AWS managed, customer managed, one inline policy, optional **boundary**) plus **session duration (1–12 hours)**. When assigned to an account, Identity Center creates an **IAM role** `AWSReservedSSO_<name>_<id>` in that account.
- **Assignment** = (user or group) + (account) + (permission set). Prefer **groups**.
- **Identity Center users get short-lived credentials** (CLI via `aws sso login`, console via the access portal).
- **Customer managed policies in a permission set** must **already exist by name** in each target account.
- **Attributes for access control (ABAC)**: pass user attributes (department, cost center) as **session tags** so policies can use `aws:PrincipalTag`.
- **MFA**: configure at Identity Center (authenticator apps, security keys); context-aware options.
- **Trusted identity propagation**: pass the user's identity to supported services (Redshift, Athena workgroups, S3 Access Grants, Lake Formation, EMR) so they apply **per-user** authorization and audit.
- **S3 Access Grants** use Identity Center identities for directory-based S3 access **(verify)**.
- **Multi-Region**: Identity Center can replicate to **additional Regions** (quota **6** enabled Regions) **(verify)**.
- **Delegated administrator**: a member account can manage Identity Center day to day, so the management account is not used.
- **Application assignments**: SAML/OAuth apps (Salesforce, Amazon Q, QuickSight/Quick, SageMaker Unified Studio, Redshift Query Editor).
- **Quotas** (selected): permission sets **3,500** per instance; provisioned permission sets **500 per account**; managed policies per permission set **20 AWS+customer** (**uses the account's IAM managed-policy-per-role quota; raise the IAM quota to 20–25**) **(verify count)**; **1 inline policy** per permission set (up to 32,768 bytes, 10,240 non-whitespace); users **1,000,000**; groups **100,000**; accounts/apps **7,000** each; **100 groups** assignable to one permission set per account; API throttle **20 TPS**; session **up to 12 h**.
- **Provisioning**: changing a permission set requires **re-provisioning** to accounts; only **one permission-set role update at a time per account**.
- **Troubleshooting**: "no access to account" → missing assignment; "role missing" → not provisioned; "policy not found" → customer managed policy absent in the target account.
- **Do not create IAM users** for workforce if Identity Center is available.

## B. AWS Organizations basics (needed for guardrails)
- **Organization**: management (payer) account + member accounts, grouped in **OUs** under a **root**.
- **All features** mode is required for SCPs, RCPs, tag policies, backup policies, etc. (consolidated-billing-only mode does not support them).
- **Management account**: do not run workloads; **SCPs/RCPs never apply to it**.
- **Delegated administrator** accounts for services (Security Hub, GuardDuty, Config, IAM Access Analyzer, Identity Center, Backup…) keep the management account clean.
- **Policy types**: SCP, **RCP**, declarative policy, backup policy, tag policy, chat applications policy, AI services opt-out policy, Security Hub policy.
- **Inheritance**: a policy attached at the root or an OU applies to every account below it. An action must be allowed by **every level** from root to account.
- **Control Tower** automates a multi-account landing zone with guardrails (separate notes).

## C. Service control policies (SCPs)
- SCPs set the **maximum permissions** for **IAM users and roles** (and the **root user**) in **member accounts**. They **never grant**.
- **Not affected by SCPs**: management account principals; **service-linked roles**; some root-only tasks (enterprise support sign-up, CloudFront trusted signer, Lightsail reverse DNS…).
- **FullAWSAccess** is attached by default at root/OU/account. **Do not detach it** unless you replace it, or **all actions fail**.
- **Strategies**:
  - **Deny list** (default): keep `FullAWSAccess`, add `Deny` statements (block Regions, block leaving the organization, block disabling CloudTrail/GuardDuty, block deleting logs). Simple and common.
  - **Allow list**: remove `FullAWSAccess`, allow only chosen services. Strict, high maintenance.
- **Effective permissions** = SCP ∩ (RCP) ∩ boundary ∩ session ∩ identity-based (resource policies can still allow in same account).
- **Common guardrails**:
  - Deny actions outside approved Regions with `aws:RequestedRegion` (exempt global services using `NotAction`).
  - Deny `organizations:LeaveOrganization`.
  - Deny disabling/deleting **CloudTrail**, **Config**, **GuardDuty**, **Security Hub**.
  - Deny **creating IAM users/access keys** (force roles).
  - Require **encryption** (deny `s3:PutObject` without SSE-KMS) and **IMDSv2**.
  - Deny root user actions: `Principal`-style via `aws:PrincipalArn` = `arn:aws:iam::*:root`.
  - Deny removing a permissions boundary or changing a protected role (`aws:PrincipalArn` exemptions for admin roles).
- SCPs **do not affect** resource-based policies directly and **do not affect principals outside** the organization.
- **Limits**: SCP document up to **10,240 characters**; up to **10 SCPs attached directly** to each root/OU/account (inherited ones do not count; every entity needs at least one SCP attached); **10,000 SCPs per organization**; OU nesting **5 levels**; **2,000 OUs**. Whitespace is removed when saved from the console but **not** from CLI/SDK.
- **Disabling SCPs** in a root detaches all SCPs; re-enabling resets to only `FullAWSAccess`.
- **Testing**: attach to a test OU/account first; use **CloudTrail** `AccessDenied` events and **service last accessed data** to tune. Errors say "explicit deny in a service control policy".
- **Implicit deny by SCP**: a missing Allow in an allow-list SCP produces "no service control policy allows".

## D. Resource control policies (RCPs)
- RCPs set the **maximum permissions on resources** in member accounts, **regardless of who calls** (inside or outside the organization). They **never grant**.
- Purpose: build a **data perimeter** (for example "only my organization's principals may access my S3 buckets/KMS keys/SQS queues/Secrets Manager secrets/STS").
- **Supported services** include **S3, KMS, STS, SQS, Secrets Manager, DynamoDB, ECR, CloudWatch Logs, OpenSearch, Kinesis Video, MemoryDB, EventBridge, Firehose, Cognito, AWS WAF, Transfer** and others **(list changes; verify)**.
- **Not covered**: management account resources; **service-linked role** calls; **AWS managed KMS keys**; `kms:RetireGrant`.
- RCPs apply to **principals inside and outside** the organization (including the root user) accessing a member account's resources.
- Typical RCP: `Deny` `s3:*` unless `aws:PrincipalOrgID` = your org (with exceptions for AWS service principals via `aws:PrincipalIsAWSService` and confused-deputy conditions).
- Enable RCPs in the root (like SCPs); the default `RCPFullAWSAccess` policy is attached automatically and cannot be detached.
- **Limits**: RCP document up to **5,120 characters**; up to **5 RCPs attached directly** per root/OU/account (the automatic `RCPFullAWSAccess` counts as one and cannot be detached); **2,000 RCPs per organization**.
- **SCP vs RCP**:
  | Question | SCP | RCP |
  |---|---|---|
  | Controls what | **Principals** in my accounts | **Resources** in my accounts |
  | Who it stops | My users/roles doing too much | **Anyone** (incl. external accounts) reaching my resources |
  | Typical use | Region lock, deny dangerous API | Data perimeter, enforce TLS/org-only access |
  | Management account | Not affected | Not affected |
- Together they form the **data perimeter** ("trusted identities, trusted resources, expected networks") with VPC endpoint policies.

## E. Declarative policies and tag policies (brief)
- **Declarative policies** enforce **service-level baseline configuration** (for example block public EBS snapshots, block public AMIs, IMDSv2 defaults, VPC block public access) org-wide regardless of API calls **(verify supported attributes)**.
- **Tag policies** standardize tag keys/values (case, allowed values) and report compliance; can enforce on some resource types.
- **Backup policies** define AWS Backup plans org-wide (see AWS Backup notes).

## F. IAM Access Analyzer
- **Access Analyzer** uses **automated reasoning** to find and validate access.
- **Analyzer types**:
  - **External access**: finds resources shared with principals **outside your zone of trust** (account or organization). **Per Region.** Resources include **S3 buckets (and directory buckets), IAM roles, KMS keys, Lambda functions/layers, SQS queues, Secrets Manager secrets, SNS topics, EBS snapshots, RDS snapshots, ECR repos, EFS, DynamoDB tables/streams**.
  - **Internal access**: finds which **internal principals** can reach chosen critical resources (S3, DynamoDB, RDS snapshots) to check least privilege.
  - **Unused access**: finds **unused roles, unused access keys, unused passwords, unused services/actions** (based on last-accessed data; **not Region-specific**; billed per IAM role/user analyzed per month; SLRs excluded).
- **Zone of trust**: your **account** or **organization**. Access from inside = trusted.
- **Findings**: Active / Archived / Resolved; **archive rules** auto-archive known-good findings (for example a partner account).
- Findings refresh: within about **30 minutes** of a policy change; periodic rescans (up to 24 h); **rescan** button or `StartResourceScan`.
- **Policy validation**: checks grammar and best practices (errors, security warnings, suggestions) in console/API/CI.
- **Custom policy checks**: `CheckNoNewAccess` (new policy vs old), `CheckAccessNotGranted` (blocks critical actions like `s3:DeleteBucket`), `CheckNoPublicAccess` — usable in **CI/CD**.
- **Policy generation**: builds a least-privilege policy from **CloudTrail** activity over a chosen period (needs a trail and an access role).
- **Delegated administrator** for organization-wide analyzers.
- **Integration**: findings go to **Security Hub** and **EventBridge**.
- **Access Advisor / last accessed information**: per principal, which services (and actions for some) were used in the last **400 days**; also available in Organizations for SCP tuning.
- **IAM policy simulator**: tests whether identity policies allow actions (does not include resource-based or SCP effects fully **(verify)**).

## G. Exam-oriented comparisons
| Need | Use |
|---|---|
| Workforce SSO to many accounts | **IAM Identity Center** |
| Limit what any principal in an account can do | **SCP** |
| Limit access to my resources from anyone | **RCP** |
| Cap what roles developers create can do | **Permissions boundary** |
| Limit one temporary session | **Session policy** |
| Find publicly shared / cross-account resources | **Access Analyzer (external)** |
| Remove unused permissions/keys | **Access Analyzer (unused) + Access Advisor** |
| Generate least-privilege policy | **Access Analyzer policy generation** |
| Org-wide config baseline | **Declarative policy** |
| Data-lake fine-grained access | **Lake Formation** |
| Query who changed what | **CloudTrail** |
| Continuous compliance rules | **AWS Config** |

## H. Exam skills mapping
- **4.2.5 Role-based, tag-based, attribute-based authorization**: Identity Center attributes.
- **4.2.6 Least-privilege custom policies**: Access Analyzer and unused access.
- **4.5.3 Prevent backups or replication to disallowed Regions**: SCP Region guardrails.
- **4.5.5 Data sovereignty**: data sovereignty with aws:RequestedRegion.
- **4.5.7 Governance framework and data sharing patterns**: SCP/RCP data perimeter.

## I. Scenarios: "If X → Y, because Z"
- If 40 developers need console and CLI access to 15 accounts → **IAM Identity Center groups + permission sets**, because it provisions roles centrally with short-lived credentials.
- If your company IdP is Okta → **external IdP with SAML + SCIM to Identity Center**, because sign-in and user/group sync are automatic.
- If no one in any member account may run workloads outside two Regions → **SCP deny with `aws:RequestedRegion` (exempt global services)**, because SCP caps even admins.
- If an admin in a member account can still delete CloudTrail → **SCP deny `cloudtrail:StopLogging/DeleteTrail`**, because IAM admin policies cannot override SCP denies.
- If an external account can read an S3 bucket via a mistaken bucket policy and you want a hard stop → **RCP restricting `s3:*` to your org (data perimeter)**, because RCP blocks outsiders even if the bucket policy allows them.
- If you must prove nothing is shared outside the organization → **Access Analyzer external access analyzer (org zone of trust) in every Region + archive rules**, because it flags public and cross-account sharing.
- If roles have unused permissions after a project ends → **unused access analyzer + generate policy from CloudTrail**, because it shows what was actually used.
- If an SCP breaks everything after removing FullAWSAccess → **re-attach FullAWSAccess or add an allow-list**, because without any Allow all actions are implicitly denied.
- If the management account needs controlling → **keep it empty; SCPs cannot restrict it**, because the management account is exempt.
- If a new account must follow the baseline automatically → **Control Tower / Organizations OU with attached SCPs**, because new accounts inherit OU policies.
- If a service-linked role action is blocked by an SCP you wrote → **it is not**; SLRs are not restricted, because SCPs/RCPs do not apply to them.
- If users from Identity Center cannot use a customer managed policy in a permission set → **create a policy with the same name in each target account**, because the permission set references it by name.

Verified from AWS docs on 2026-11-03 (SCPs, RCPs, Access Analyzer overview, Identity Center quotas, IAM policy evaluation logic).
Unconfirmed (verify): Identity Center instance type names and per-instance rules; permission set managed-policy count; RCP supported service list (changes often); declarative policy attributes; list of Organizations policy types; Access Analyzer custom check names; policy simulator coverage of resource policies/SCPs; Access Advisor 400-day retention; multi-Region Identity Center details.

# AWS IAM and STS – 4. Monitoring, troubleshooting, best practices, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Cost
- **IAM, STS, Organizations and Identity Center are free.** You pay for what the identities use (and for some add-ons).
- **IAM Access Analyzer**: external access analysis is **free**; **unused access** is billed per IAM role/user analyzed per analyzer per month; **internal access** per resource monitored; **custom policy checks** per API request.
- **Roles Anywhere** is free; **AWS Private CA** (if used as trust anchor) costs per CA per month.
- **CloudTrail**: the first copy of management events is free in Event history (90 days); trails to S3, **CloudTrail Lake**, data events cost extra.
- **KMS** requests triggered by IAM-based encryption cost (see KMS notes).
- Hidden cost of **bad IAM**: manual access reviews, outages from over-tight SCPs, incident cost from leaked keys.

## B. Auditing and monitoring
- **CloudTrail** records IAM/STS/Identity Center calls: `CreateUser`, `AttachRolePolicy`, `PutRolePolicy`, `AssumeRole`, `AssumeRoleWithSAML`, `AssumeRoleWithWebIdentity`, `ConsoleLogin`, `CreateAccessKey`, `UpdateAssumeRolePolicy`, `DeleteRolePermissionsBoundary`. **IAM/STS global events are logged in `us-east-1`** for the global service endpoint (use Regional STS endpoints to see events in that Region) **(verify)**.
- **Access denied events** carry `errorCode: AccessDenied` / `UnauthorizedOperation` and an **encoded authorization failure message** that you decode with `sts:DecodeAuthorizationMessage` (needs permission).
- **CloudTrail Lake** lets you SQL-query events (including `userIdentity.sessionContext`).
- **EventBridge rules** on CloudTrail events trigger alerts: root login, `ConsoleLogin` without MFA, `CreateAccessKey` for root, policy changes, disabled logging.
- **IAM Access Analyzer** findings, **Security Hub** (CIS/AWS Foundational checks such as "root has MFA", "no root access keys", "IAM password policy"), **GuardDuty** (credential exfiltration, anomalous API use), **Config** (managed rules: `iam-user-mfa-enabled`, `root-account-mfa-enabled`, `access-keys-rotated`, `iam-policy-no-statements-with-admin-access`, `iam-user-unused-credentials-check`, `iam-no-inline-policy-check`).
- **Credential report** and **Access Advisor** (last accessed services, with action-level data for some services).
- **Policy changes**: AWS Config records IAM resource configuration history, so you can see who changed which policy and when.
- **CloudWatch metric filter + alarm** patterns on CloudTrail logs for the CIS benchmark (root usage, unauthorized API calls, IAM policy changes, console sign-in failures).
- **Session identification**: use meaningful `RoleSessionName` and **`SourceIdentity`** so audit logs show the human behind the role.
- **Organization trail** in the management account captures all member accounts, with log file validation, KMS encryption, and an immutable S3 bucket.

## C. Troubleshooting `AccessDenied` (symptom → cause → fix)
- **Step 1: identify the principal and action**: read the error message or CloudTrail event (`userIdentity.arn`, `eventName`, `errorMessage`).
- **"is not authorized to perform X on resource Y because no identity-based policy allows"** → implicit deny in identity policy → add Allow.
- **"... with an explicit deny in an identity-based policy / resource-based policy"** → remove or narrow the Deny, or fix a condition.
- **"... with an explicit deny in a service control policy"** → SCP guardrail; ask the org admin; check Region/service conditions.
- **"... because no service control policy allows"** → allow-list SCP missing the action.
- **"... with an explicit deny in a resource control policy"** → RCP/data perimeter; check `aws:PrincipalOrgID` or network conditions.
- **"... permissions boundary"** → boundary does not include the action.
- **"... session policy"** → session policy or Identity Center inline restriction.
- **Cross-account fails** → only one side allows; or KMS key policy forgets the other account.
- **S3 `AccessDenied` for objects** → missing `s3:GetObject`, missing `kms:Decrypt`, VPC endpoint policy, bucket policy deny on `aws:SecureTransport` or `aws:SourceVpce`, S3 Block Public Access, object ownership (ACLs), Lake Formation not granting.
- **Glue/Athena "Insufficient Lake Formation permission"** → IAM allows but Lake Formation does not grant (two-layer model).
- **`iam:PassRole` error** → add `PassRole` on the target role with correct `PassedToService`.
- **"Access denied" for KMS** → key policy must allow the principal (or IAM policies enabled via key policy `Principal: root`) and any grants/`ViaService` conditions.
- **`ExpiredToken` / `InvalidClientTokenId`** → expired or revoked temporary credentials; wrong partition/Region; clock skew.
- **`SignatureDoesNotMatch`** → bad secret key, wrong Region, clock skew > 5 minutes.
- **Role cannot be assumed** → trust policy principal/condition mismatch (ExternalId, MFA, org ID), caller lacks `sts:AssumeRole`, session duration > role max, role chaining > 1 h.
- **Works in console, fails in CLI** → CLI uses different credentials/profile or stale environment variables; run `aws sts get-caller-identity`.
- **Tag-based denial** → missing/different tag on principal or resource (ABAC), or tag edit denied.
- **Identity Center user lost access** → assignment removed or permission set changes not re-provisioned.
- **Tools**: **IAM policy simulator**, **Access Analyzer policy validation**, **CloudTrail event history (last 90 days)**, **`DecodeAuthorizationMessage`**, **AWS Config timeline**, the **IAM console "Policy evaluation" / last accessed** tabs.
- **Quick checklist order**: (1) who am I? (2) which layers apply (SCP/RCP/boundary/session/identity/resource/KMS/LF)? (3) any explicit deny? (4) condition keys match the request context (IP, VPC, tags, MFA, time)?

## D. Best practices (AWS list in short)
- Use **temporary credentials** (roles, Identity Center) instead of long-term keys.
- **Require MFA** for humans, and **phishing-resistant MFA** (FIDO2/passkeys) for admins and root.
- **Least privilege**; start with AWS managed policies, then refine with generated policies.
- **Review regularly**: remove unused users, roles, credentials, permissions (unused access analyzer).
- **Rotate** long-term keys; **never embed keys** in code/Git; scan repos for secrets.
- **Use conditions** (source VPC, org ID, MFA, tags).
- **Guardrails**: SCPs, RCPs, permissions boundaries, declarative policies.
- **Separate accounts** per environment/workload; use Organizations.
- **Monitor and alert** on IAM changes and root activity.
- **Root user**: MFA, no access keys, billing contacts/alternate contacts set, use only for root-only tasks.
- **Use groups/roles**, not individual user policies.
- **Customer managed policies** over inline.
- **IMDSv2 only**, **no wildcard principals** in trust policies.
- **Protect logs**: organization trail, immutable bucket, validation.
- **Test policy changes** with simulator/validation before deploying; deploy through IaC/PRs.
- **Tag** roles and users (owner, purpose).

## E. Data-engineering patterns (cheat sheet)
- **Glue + S3 + KMS + Lake Formation**: job role needs `glue:*` on needed jobs/tables, `s3:Get/Put/List` on prefixes, `kms:Decrypt/GenerateDataKey`, and **Lake Formation grants** if the location is registered; add `iam:PassRole` for whoever creates the job.
- **Athena**: user needs `athena:StartQueryExecution` etc., S3 read on data, S3 write on results bucket, Glue read, `kms` if encrypted, plus Lake Formation grants.
- **Redshift COPY/UNLOAD**: role attached to the cluster with S3 access; **cluster role must be associated**; cross-account via role chaining (Redshift supports chaining roles).
- **EMR**: three roles (service role, EC2 instance profile, optional Auto Scaling role); EMR Serverless job role; EMRFS role mapping for per-user S3 access.
- **Lambda**: execution role + resource policy for invokers; cross-account invocation needs both.
- **Step Functions**: execution role with exact integration actions and `.sync` EventBridge permissions.
- **MWAA**: execution role (DAG permissions) plus user policies for web login (Admin/Op/User/Viewer).
- **Firehose**: delivery role with S3, KMS, Glue (format conversion), Lambda; for cross-account, resource policy or assume role.
- **Cross-account data sharing**: bucket policy or RAM + Lake Formation; use `aws:PrincipalOrgID` for org-wide read.
- **Service-to-service confused deputy**: add `aws:SourceArn`/`aws:SourceAccount` in resource policies for CloudTrail, Config, SNS, S3 notifications.

## F. Limits cheat sheet
| Item | Default (max by request) |
|---|---|
| Users per account | 5,000 **(verify)** |
| Groups per account | 300 (500) |
| Roles per account | 1,000 (10,000) |
| Customer managed policies per account | 1,500 (10,000) |
| Managed policies per role | 10 (25) |
| Managed policies per user | 10 (20) |
| Managed policies per group | 10 |
| Instance profiles per account | 1,000 (10,000) |
| OIDC providers per account | 100 (700) |
| Server certificates | 20 |
| Access keys per user | 2 |
| MFA devices per user | 8 **(verify)** |
| Role trust policy | 2,048 chars (8,192) |
| Managed policy size | 6,144 chars (no whitespace) |
| Inline policy aggregate | user 2,048 / group 5,120 / role 10,240 chars |
| Role name / user name | 64 chars |
| Group / policy / instance profile name | 128 chars |
| Path | 512 chars |
| Role session duration | 15 min – 12 h (default 1 h) |
| Role chaining session | 1 h max |
| GetSessionToken / GetFederationToken | 15 min – 36 h (root 1 h) |
| Session name | 64 chars |
| Session tags | 50; key 128, value 256 |
| Session policy | 10 managed ARNs; 2,048 chars |
| SAML response (base64) | 100,000 chars |
| ExternalId | 2–1,224 chars |
| STS requests | 600/s per account per Region |
| Policy versions per managed policy | 5 |
| Identity Center permission sets | 3,500 (provisioned 500/account) |
| Identity Center users / groups | 1,000,000 / 100,000 |
| Identity Center session | up to 12 h |
- Check live usage with `GetAccountSummary`.

## G. Exam skills mapping
- **4.4.1 CloudTrail for API calls (audit)**: CloudTrail IAM/STS events.
- **3.3.5 CloudTrail for API calls**: CloudTrail for API calls.
- **4.2.6 Least-privilege custom policies**: least-privilege troubleshooting.
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: policy troubleshooting.

## H. Scenarios: "If X → Y, because Z"
- If a pipeline suddenly returns AccessDenied after a security change → **check CloudTrail for the denied event, then SCP/RCP/boundary/bucket policy/KMS**, because the error message and event show which layer denied.
- If the error message is an unreadable encoded blob → **`sts decode-authorization-message`**, because it expands the policy decision.
- If the auditors need who did what in a shared role → **require `SourceIdentity` or per-person session names, and keep an organization trail**, because role sessions otherwise look the same.
- If a long-term access key leaks → **deactivate/delete the key, review CloudTrail for its use, revoke sessions on roles it could assume, rotate secrets**, because keys cannot be partially revoked.
- If you suspect a compromised role session → **attach a deny-all with `aws:TokenIssueTime` before now (revoke sessions)**, because it invalidates existing sessions immediately.
- If root console login happens → **EventBridge rule on `ConsoleLogin` by root → SNS**, because root use should be rare and always reviewed.
- If MFA must be enforced for deleting production data → **Deny unless `aws:MultiFactorAuthPresent` is true**, because the condition makes MFA mandatory for that action.
- If you need to prove compliance for IAM controls → **Config rules/conformance packs + Security Hub standards**, because they continuously evaluate and report.
- If a role has too many broad permissions → **Access Analyzer policy generation from 90 days of CloudTrail**, because it builds a policy from real use.
- If you must list roles/users nobody uses → **unused access analyzer (org)**, because it flags unused roles, keys, and passwords.
- If a developer cannot see Glue tables in Athena but IAM is correct → **Lake Formation grants missing**, because LF is a second permission layer.
- If cross-account S3 access works for GetObject but not for KMS-encrypted objects → **add KMS key policy for the other account and `kms:Decrypt` in its identity policy**, because KMS is evaluated separately.
- If an IAM change must be reviewed before deployment → **IaC + pull request + Access Analyzer custom policy checks in CI**, because it stops unintended new access before it ships.

Verified from AWS docs on 2026-11-03 (IAM and STS quotas, policy evaluation logic, Access Analyzer overview, STS credentials, SCP/RCP documentation).
Unconfirmed (verify): users-per-account default; MFA devices per user; CloudTrail event Region for IAM/STS global endpoints; exact Config managed rule names; policy simulator scope; Security Hub standard control names; whether `DecodeAuthorizationMessage` covers all services; GuardDuty finding names for credential misuse.

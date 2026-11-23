# AWS IAM and STS – 2. Roles, trust, STS and federation

Short notes. Each point is a fact you can be asked about.

## A. Role basics
- A role has **two kinds of policy**: a **trust policy** (who may assume it) and **permission policies** (what it can do after assuming).
- The **trust policy** is a **resource-based policy on the role**. Its `Action` is `sts:AssumeRole` (or `AssumeRoleWithSAML`, `AssumeRoleWithWebIdentity`, `TagSession`, `SetSourceIdentity`).
- Trust `Principal` can be: an **AWS account/root**, a specific **user or role ARN**, a **service** (`glue.amazonaws.com`), a **SAML provider**, an **OIDC provider**, or `*` (dangerous without conditions).
- **Account root in the trust policy** means "any identity in that account that is allowed by its own IAM policy". The other account must also **allow `sts:AssumeRole`** in the caller's identity policy (cross-account = both sides).
- **Same account**: if the trust policy names the **exact user/role ARN**, the caller does not need `sts:AssumeRole` in its identity policy; if it names the **account root**, the caller needs it.
- **Role session duration**: `DurationSeconds` **900 s (15 min) up to the role's max session duration (1–12 hours)**. Default requested is **1 hour**. Console role switching uses the maximum or remaining user session, whichever is shorter. The max does **not** limit sessions assumed by AWS services.
- **Role chaining** (assuming a role with role credentials): session limited to **1 hour max**, and you cannot change it.
- **Session name** (`RoleSessionName`): **2–64** characters; shows up in CloudTrail and the assumed-role ARN. Make it identify the human or job.
- **Session tags**: up to **50**; **session policies** up to **10 managed policy ARNs** and **2,048 characters**; extra data adds to the **session token size** limit (`SessionTokenUtilization` response field).
- **Transitive session tags**: tags passed with `TransitiveTagKeys` persist across role chaining.
- **Role name 64 chars**, path up to 512, **roles per account 1,000 (up to 10,000)**.
- **Trust policy size** default 2,048 characters (up to 8,192).
- **Roles can be assumed by**: IAM users/roles, services, federated principals, and (with Roles Anywhere) workloads outside AWS.
- **Deleting and re-creating** a role with the same name creates a **new unique ID**; old references by ID break, but trust by name/ARN still works **(verify)**.
- **Tag a role** for ownership and ABAC; roles can carry `aws:PrincipalTag` attributes.

## B. Service roles for data engineering (patterns)
| Service | Role purpose | Trust principal |
|---|---|---|
| **Glue job/crawler** | Read/write S3, Catalog, logs, KMS | `glue.amazonaws.com` |
| **EMR (service role)** | EMR creates EC2/ASG on your behalf | `elasticmapreduce.amazonaws.com` |
| **EMR EC2 instance profile** | Code on nodes accesses S3/Dynamo | `ec2.amazonaws.com` |
| **EMR Serverless job role** | Job runtime permissions | `emr-serverless.amazonaws.com` |
| **Lambda execution role** | Logs + services the function calls | `lambda.amazonaws.com` |
| **Step Functions execution role** | Integrations it calls | `states.amazonaws.com` |
| **MWAA execution role** | S3 DAGs, logs, SQS, KMS | `airflow.amazonaws.com`, `airflow-env.amazonaws.com` |
| **Firehose delivery role** | Write to S3/Redshift/OpenSearch | `firehose.amazonaws.com` |
| **Redshift (COPY/UNLOAD, Spectrum)** | Access S3/Glue/Lake Formation | `redshift.amazonaws.com` (and `redshift-serverless.amazonaws.com`) |
| **DMS** | Endpoints and VPC | `dms.amazonaws.com` |
| **SageMaker** | Training/Processing | `sagemaker.amazonaws.com` |
| **ECS task role vs task execution role** | App permissions vs pull image/log | `ecs-tasks.amazonaws.com` |
| **Lake Formation registered location role** | Vend credentials to S3 | `lakeformation.amazonaws.com` |
- **Task role vs execution role (ECS)**: the **task role** is what your code uses; the **task execution role** is for the ECS agent (ECR pull, logs, secrets).
- **Lambda**: one execution role per function (can be shared); keep it narrow.
- **Resource-based trust** to cross accounts: a **Lambda resource policy** or **SQS/SNS policy** lets other accounts/services invoke without assuming roles.
- **Use one role per workload/function** so you can see and cut permissions independently.

## C. `iam:PassRole`
- To hand a role to a service (create a Glue job, start EMR, create a Lambda, create a Step Functions state machine), the **caller needs `iam:PassRole`** on that role ARN.
- Restrict with `iam:PassedToService` (for example `glue.amazonaws.com`) and a specific role ARN or path.
- Missing `PassRole` shows up as **"User is not authorized to perform iam:PassRole on resource"**.
- `PassRole` is **not an API call**; it is a permission checked when you pass the role.
- **Privilege escalation risk**: `iam:PassRole` on a powerful role + permission to create a service (Lambda/Glue/EC2) lets a user run code as that role. Scope tightly.
- Console users creating MWAA environments need `PassRole` with `iam:PassedToService = airflow.amazonaws.com`.

## D. STS API operations
| API | Who calls | Credential type | Typical duration | Use |
|---|---|---|---|---|
| **AssumeRole** | IAM user/role (signed) | Role session | **15 min – role max (≤12 h)**; default 1 h | Cross-account, elevation, MFA-gated access |
| **AssumeRoleWithSAML** | SAML federated user (unsigned) | Role session | 15 min – role max; default 1 h | Enterprise SSO |
| **AssumeRoleWithWebIdentity** | OIDC/web identity (unsigned) | Role session | 15 min – role max; default 1 h | EKS IRSA, GitHub Actions, mobile apps |
| **GetSessionToken** | IAM user (or root) | User session | **15 min – 36 h** (root: **1 h**); default 12 h | MFA-protected API for a user |
| **GetFederationToken** | IAM user | Federated user | **15 min – 36 h**; default 12 h | Custom identity broker (legacy) |
| **GetCallerIdentity** | anyone | – | – | "Who am I?" (needs **no permissions**) |
| **AssumeRoot** | Management/delegated admin | Privileged root session | short (≤ 15 min) | Central root tasks **(verify)** |
- `GetSessionToken` and `GetFederationToken` credentials **cannot call IAM or most STS operations** except with MFA (`GetSessionToken` with MFA can call some IAM APIs) **(verify details)**.
- **`AssumeRoleWithSAML` / `WithWebIdentity` need no AWS credentials** to call; the IdP token is the proof.
- **`sts:GetCallerIdentity`** is the quickest check for which credentials the CLI/SDK is actually using.
- **STS request quota**: **600 requests/second per account per Region** (shared across AssumeRole, GetCallerIdentity, GetFederationToken, GetSessionToken, etc.). Service-principal calls do not count. Cross-account calls count only against the **caller's** account.
- **Regional vs global endpoint**: use **Regional endpoints** (`sts.<region>.amazonaws.com`) for lower latency and resilience; the global endpoint `sts.amazonaws.com` is moving to behave like us-east-1 with its own quota **(verify)**.
- Temporary credentials from a Region work in all Regions; but STS **session tokens from the global endpoint** may be valid only in Regions enabled by default (older behaviour).
- **Credential size**: session token is typically < 4 KB but not fixed; do not assume a maximum.
- **Credentials are not revocable directly**: to cut off a compromised session, attach a **deny-by-`aws:TokenIssueTime`** policy to the role ("Revoke active sessions" in the console), then rotate.

## E. Cross-account access patterns
- **Pattern 1: assume a role in the target account** (most common): target role trusts the source account (or specific role); source role has `sts:AssumeRole` on the target role.
- **Pattern 2: resource-based policy** (S3, KMS, SQS, SNS, Lambda, Secrets Manager, Glue Catalog resource policy, Lake Formation): grant the other account's principal directly. The principal **keeps its own identity** (does not switch role).
- **Difference**: with assume-role the caller **gives up its original permissions** while in the new session; with resource policy it keeps them. This matters for **S3 object ownership** and for operations needing both accounts' resources.
- **KMS cross-account**: key policy must allow the other account **and** the caller's identity policy must allow `kms:*` actions on that key ARN.
- **Glue Data Catalog / Lake Formation cross-account**: use **RAM shares** or LF grants (see Lake Formation notes).
- **Organizations**: use `aws:PrincipalOrgID` for wide sharing.
- **Third-party access (SaaS vendor)**: role trusting the vendor account with a **unique `ExternalId`** condition (2–1,224 characters, alphanumeric and `+=,.@:/-`).
- **Confused deputy**: the vendor (or a service) is tricked into using its access on behalf of another customer. Mitigate with **`sts:ExternalId`** for third parties and **`aws:SourceArn` / `aws:SourceAccount`** for AWS services (for example SNS/S3/Lambda resource policies, CloudTrail, Config, Step Functions, MWAA).
- **Source identity** (`sts:SourceIdentity`): an immutable name set at first assume-role that persists through role chaining; shows in CloudTrail so you can tie actions back to a person.

## F. Federation
### F1. SAML 2.0
- IdP (Okta, Entra ID, ADFS) authenticates; IAM **SAML provider** trusts the IdP metadata; role trust names the SAML provider; **`AssumeRoleWithSAML`** returns credentials.
- Assertion must include **role ARN + provider ARN** attributes and a `RoleSessionName` attribute. Max assertion **100,000 characters** (base64).
- Console SSO uses the **AWS sign-in SAML endpoint**.
### F2. OIDC / web identity
- **OIDC provider** (GitHub Actions, GitLab, Google, Amazon Cognito, EKS cluster issuer) → role trust with `Federated` principal and **conditions on `aud` and `sub`** claims.
- **GitHub Actions**: trust `token.actions.githubusercontent.com` with `sub` restricted to `repo:org/repo:ref:refs/heads/main`. **Never trust `sub: *`**.
- **EKS IRSA** / **EKS Pod Identity**: pods assume roles; Pod Identity is simpler and avoids OIDC-provider-per-cluster limits. **OIDC providers per account: 100 (up to 700)**.
- **Cognito identity pools** exchange user pool/social tokens for AWS credentials via roles (auth vs unauth roles).
### F3. IAM Identity Center (successor to "AWS SSO")
- Central workforce sign-in and **permission sets** for many accounts (details in file 3).
### F4. IAM Roles Anywhere
- Gives **on-prem/other-cloud workloads** temporary credentials using **X.509 certificates** from a trust anchor (**AWS Private CA** or your CA). Replaces long-term keys on servers.
- Steps: trust anchor + profile + role (trust `rolesanywhere.amazonaws.com`) + `aws_signing_helper`/credential process.
### F5. Custom identity broker
- Your app calls **`AssumeRole`/`GetFederationToken`** and gives users a console sign-in URL or credentials (legacy; prefer Identity Center).
### F6. Directory integrations
- **AWS Managed Microsoft AD** or **AD Connector** can back Identity Center or console access.

## G. Credentials for applications (what to use where)
- **EC2**: instance profile (IMDSv2) → role credentials via metadata; **require IMDSv2** (`HttpTokens=required`) to stop SSRF theft.
- **Lambda/ECS/EKS/Glue/EMR**: service-provided role credentials (container credential provider, IRSA/Pod Identity).
- **Developers' laptops**: **IAM Identity Center** CLI sign-in (`aws sso login`) or `aws configure sso`; short-lived credentials.
- **CI/CD**: **OIDC federation** to a role (no stored keys).
- **On-prem servers**: **Roles Anywhere**; if impossible, an IAM user with **narrow policy + rotation** and conditions (IP).
- **Mobile/web apps**: **Cognito** (never embed keys).
- **Third parties**: cross-account role with ExternalId.
- **SDK credential provider chain** order (typical): environment variables → shared credentials/config (profile, SSO, `credential_process`) → web identity token → container credentials → instance metadata. A stale `AWS_ACCESS_KEY_ID` env var silently overrides everything else.
- **Rotation**: keys older than 90 days should be rotated; use **Access Analyzer unused access** and credential report to find them.

## H. Service-linked roles and AWS-managed trust
- SLRs are created when you first use a feature (for example Organizations, Lake Formation, Elastic Load Balancing, MWAA).
- SLR **permissions and trust cannot be edited**; SCPs/RCPs do **not** restrict them.
- You need `iam:CreateServiceLinkedRole` once (or the service creates it for you).
- Deleting an SLR requires that the service no longer use it.
- **Some services need a one-time role for the account** (Config, Macie, Security Hub use SLRs).

## I. Security patterns for roles
- Deny risky actions to everyone except an admin role (`iam:*`, `organizations:*`, `kms:ScheduleKeyDeletion`).
- Require **MFA** for sensitive role assumption: `aws:MultiFactorAuthPresent = true` in the trust policy.
- Restrict role assumption by **source IP/VPC** (`aws:SourceIp`, `aws:SourceVpc`) for human roles.
- Use **short max session duration** (1 h) for admin roles.
- Put **conditions on trust**: `aws:PrincipalOrgID`, `aws:PrincipalTag`, `sts:ExternalId`, `aws:SourceArn`.
- Monitor **`AssumeRole`**, **`AssumeRoleWithWebIdentity`**, `ConsoleLogin` in CloudTrail; alert on unusual principals/Regions.
- Use **`IAM Access Analyzer`** to flag roles that can be assumed from outside your organization.
- **Break-glass role**: highly privileged, MFA, alarms on use.

## J. Exam skills mapping
- **4.1.2 IAM groups, roles, endpoints, services**: roles and STS.
- **4.1.3 Create and rotate credentials (Secrets Manager)**: temporary credentials instead of long-term keys.
- **4.1.4 IAM roles for access (Lambda, API Gateway, CLI, CloudFormation)**: service roles and PassRole.

## K. Scenarios: "If X → Y, because Z"
- If a Lambda in account A must read an S3 bucket in account B → **bucket policy in B allowing A's Lambda role + A's role policy allowing S3**, or **assume a role in B**, because cross-account needs both sides to agree.
- If a vendor needs access to your account → **role trusting the vendor with a unique ExternalId**, because ExternalId prevents confused-deputy abuse.
- If an AWS service (CloudTrail, SNS, S3 events) writes to your resource → **add `aws:SourceArn`/`aws:SourceAccount` conditions**, because it blocks other customers' resources from using the service as a proxy.
- If GitHub Actions deploys to AWS → **OIDC provider + role with `sub` condition for the repo/branch**, because no long-term keys are stored.
- If an on-prem server needs AWS access → **IAM Roles Anywhere with a certificate**, because it issues temporary credentials without static keys.
- If a CI user created `iam:PassRole` problems → **grant PassRole on only the target role with `iam:PassedToService`**, because wildcards enable privilege escalation.
- If you must chain roles for a long job → **plan for the 1-hour chained limit; refresh credentials**, because chained sessions cannot exceed 1 hour.
- If a compromised session must be killed now → **revoke sessions (deny by `aws:TokenIssueTime`) and rotate**, because credentials cannot be deleted individually.
- If tokens from a role keep expiring in a long Glue/EMR job → **use the service's role (auto-refresh) instead of manual keys**, because SDKs in services refresh credentials automatically.
- If two Regions' STS calls hit throttling at 600/s → **cache credentials, use Regional endpoints, or request an increase**, because the limit is per account per Region.
- If users need console access to many accounts → **IAM Identity Center permission sets**, because it provisions roles centrally with short sessions.
- If a developer sees "not authorized to perform iam:PassRole" creating an EMR/Glue resource → **add `iam:PassRole` for that service role**, because the service gets the role only if the caller may pass it.

Verified from AWS docs on 2026-11-03 (IAM and STS quotas, request temporary security credentials, policy evaluation logic).
Unconfirmed (verify): `AssumeRole` same-account exact-ARN rule edge cases; GetSessionToken/GetFederationToken IAM-call limits; STS global endpoint change details; AssumeRoot duration; trust handling after delete/recreate; Roles Anywhere setup parameters; Pod Identity vs IRSA limits; SDK provider chain order per language.

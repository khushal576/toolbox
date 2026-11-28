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
- **If** an **AWS Lambda** function in **account A** must read an **Amazon S3** bucket in **account B**, **then** either (1) allow A's **Lambda execution role** in B's **bucket policy** and allow S3 in that role's own policy, or (2) let the function **assume a role in account B**. **This works because** cross-account access needs both sides to agree. With a bucket policy the role keeps its own identity; with assume-role it gives up its original permissions while in the new session.
- **If** a vendor (a third-party software company) needs access to your account, **then** create a role that trusts the vendor's account with a condition on a unique **`sts:ExternalId`** (2–1,224 characters). **This works because** the ExternalId stops the **confused deputy** problem: another customer of the vendor cannot trick the vendor into using its access on your account.
- **If** an AWS service such as **AWS CloudTrail**, **Amazon Simple Notification Service (SNS)** or **Amazon S3 event notifications** writes to your resource, **then** add **`aws:SourceArn`** and/or **`aws:SourceAccount`** conditions to the resource policy. **This works because** they make the service act only for your own resource or account, so other customers cannot use the service as a proxy (the confused deputy problem).
- **If** **GitHub Actions** deploys to AWS, **then** create an **OpenID Connect (OIDC) provider** for `token.actions.githubusercontent.com` and a role whose trust policy limits the **`sub`** claim to your repo and branch (for example `repo:org/repo:ref:refs/heads/main`). **This works because** the pipeline gets **temporary credentials** through **`AssumeRoleWithWebIdentity`**, so no long-term keys are stored. Never trust `sub: *`, or other repos could assume the role.
- **If** an on-premises server needs AWS access, **then** use **IAM Roles Anywhere**: the server proves itself with an **X.509 certificate** from a trust anchor (**AWS Private Certificate Authority (CA)** or your own CA). **This works because** it gives the server **temporary credentials** for a role, so no static access keys sit on the server.
- **If** a CI user's **`iam:PassRole`** permission is too wide (for example on `*`), **then** grant **PassRole** only on the exact target role ARN, with an **`iam:PassedToService`** condition (for example `glue.amazonaws.com`). **This works because** PassRole on a powerful role, plus permission to create a service such as Lambda or Glue, lets a user run code as that role (**privilege escalation**). Scoping it closes that path.
- **If** a long job must **chain roles** (assume a role using another role's credentials), **then** design for the **1-hour** chained limit and refresh credentials before they expire. **This works because** a chained session is capped at **1 hour** and you cannot change it, even if the role's max session duration is longer.
- **If** a compromised role session must be stopped now, **then** use **"Revoke active sessions"**, which attaches a **Deny** based on **`aws:TokenIssueTime`** to the role, then rotate related credentials. **This works because** temporary credentials **cannot be revoked directly**; the Deny blocks every session issued before that time.
- **If** credentials keep expiring in a long **AWS Glue** or **Amazon EMR** job, **then** use the **role the service provides** to the job instead of manual keys. **This works because** the service supplies the role credentials and the SDKs inside the service refresh them automatically; a role's max session duration does not limit sessions assumed by AWS services.
- **If** **AWS Security Token Service (STS)** calls are throttled at **600 requests per second** in a Region, **then** **cache** and reuse credentials, use **Regional STS endpoints**, or request a quota increase. **This works because** the limit is **per account per Region**, shared by all STS calls (AssumeRole, GetCallerIdentity and others), so each Region has its own 600/s. Calls by service principals do not count.
- **If** users need console access to many accounts, **then** use **IAM Identity Center** (successor to AWS SSO) with **permission sets**. **This works because** it creates the roles in each account centrally, and users sign in once to get **short-lived credentials**, so no IAM users are needed.
- **If** a developer sees **"not authorized to perform iam:PassRole"** when creating an **Amazon EMR** or **AWS Glue** resource, **then** grant **`iam:PassRole`** on that service role's ARN, ideally with `iam:PassedToService`. **This works because** the service gets the role only if the caller is allowed to pass it; PassRole is not an API call but a permission checked at that moment.

Verified from AWS docs on 2026-11-03 (IAM and STS quotas, request temporary security credentials, policy evaluation logic).
Unconfirmed (verify): `AssumeRole` same-account exact-ARN rule edge cases; GetSessionToken/GetFederationToken IAM-call limits; STS global endpoint change details; AssumeRoot duration; trust handling after delete/recreate; Roles Anywhere setup parameters; Pod Identity vs IRSA limits; SDK provider chain order per language.

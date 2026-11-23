# AWS IAM and STS – 1. Identities, policy types and evaluation logic

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS Identity and Access Management (IAM)** decides **who (authentication)** can do **what (authorization)** on **which resource** in an AWS account. It is **global** (not per Region) and **free**.
- **AWS Security Token Service (STS)** issues **temporary credentials**. It is how roles work.
- Everything in AWS is checked by IAM: every API call is **authenticated**, then **authorized** against policies.
- Default is **implicit deny**. Access needs an explicit **Allow** and no explicit **Deny**.
- Data-engineering relevance: Glue, EMR, Redshift, Lambda, Step Functions, MWAA, Firehose all run with **IAM roles**; most real pipeline failures are `AccessDenied` from a missing or blocked permission.
- DEA-C01 touchpoints: **4.1** authentication (roles, policies, endpoints, groups, credentials) and **4.2** authorization (policies, ABAC/RBAC/least privilege).

## B. Identities
- **Root user**: the account owner (email + password). Has **all permissions that cannot be limited by IAM policies** (SCPs can limit member-account roots). Use only for the few tasks that need it. Enable **MFA**, remove access keys, do not use daily.
- **IAM user**: a long-term identity with a name, optional console password and up to **2 access keys**. **Avoid for people**; use IAM Identity Center. Avoid for workloads; use roles.
- **IAM group**: a collection of users; attach policies to the group. **A group cannot be a principal** in a policy and **cannot contain groups**.
- **IAM role**: an identity with permissions but **no long-term credentials**. Anyone/anything trusted can **assume** it and get **temporary credentials** from STS.
- **Federated identity**: external users (SAML, OIDC, Identity Center) who get a role session.
- **Service role**: a role a **service assumes** on your behalf (Glue job role, EMR service role, Firehose role). **Service-linked role (SLR)**: predefined by the service, trust fixed, **cannot be edited or restricted by SCPs/RCPs**, deleted only through the service.
- **Instance profile**: container that passes a role to an **EC2 instance**.
- **Principal**: the entity making a request (user, role session, federated user, service, account root, anonymous).
- **Role session**: the temporary identity after assume-role; ARN looks like `arn:aws:sts::<acct>:assumed-role/<RoleName>/<SessionName>`.
- **IDs**: users start `AIDA…`, groups `AGPA…`, roles `AROA…`, managed policies `ANPA…`. Role/user **unique ID** survives delete-and-recreate checks that ARNs do not.

## C. Credential types
- **Console password**, **access keys** (`AKIA…` long-term; `ASIA…` temporary with a **session token**), **MFA device** (virtual TOTP, FIDO2/passkey, hardware), **X.509 certs** (legacy), **SSH/Git credentials** for CodeCommit **(verify; CodeCommit closed to new customers)**, **service-specific credentials** (for example Keyspaces, Bedrock API keys).
- A user can have **up to 2 access keys** (to rotate without downtime).
- **Best practice**: no long-term access keys; use **IAM Identity Center**, **roles**, **Roles Anywhere**, or **OIDC** for CI/CD.
- **Credential report** (account-wide CSV, generated at most every 4 hours) and **Access Advisor / last accessed** data help find stale credentials and unused permissions.
- **Password policy** (account level): min length, character types, expiry, reuse prevention.
- **Root user**: since 2024 **centralized root access management** in Organizations lets you remove root credentials from member accounts and use short-lived **privileged root sessions** **(verify)**.
- **MFA** can be enforced in policy with `aws:MultiFactorAuthPresent` / `aws:MultiFactorAuthAge`.

## D. The six policy types
| Type | Attached to | Grants? | Purpose |
|---|---|---|---|
| **Identity-based** | user, group, role | **Yes** | What the identity can do |
| **Resource-based** | resource (S3 bucket, KMS key, SQS, Lambda, role trust…) | **Yes** (incl. cross-account) | Who can use the resource |
| **Permissions boundary** | user or role | No | **Maximum** an identity-based policy can grant |
| **Session policy** | passed on `AssumeRole`/federation | No | Further limits **one session** |
| **SCP** (Organizations) | org, OU, account | No | Max permissions for **IAM principals** in member accounts |
| **RCP** (Organizations) | org, OU, account | No | Max permissions on **resources** in member accounts |
| **ACL** (S3, VPC) | resource | Yes (legacy) | Legacy; avoid (S3 ACLs disabled by default with Bucket owner enforced) |
- Only **identity-based, resource-based and ACLs grant**. Boundaries, session policies, SCPs and RCPs only **limit**.
- **Managed policies**: **AWS managed** (maintained by AWS, e.g. `AmazonS3ReadOnlyAccess`, `AWSGlueServiceRole`) and **customer managed** (yours, versioned: up to **5 versions**, can roll back).
- **Inline policy**: embedded in one identity; deleted with it. Use sparingly.
- AWS managed policies for **job functions** (for example `DataScientist`, `DatabaseAdministrator`) exist but are broad **(verify current names)**.
- Policies can be **attached to many** identities (managed) or **one** (inline).

## E. JSON policy structure
- Fields: `Version` (always `"2012-10-17"`; the older `2008-10-17` does not support policy variables), optional `Id`, `Statement` (array).
- Statement elements:
  - `Sid` – optional ID.
  - `Effect` – `Allow` or `Deny`.
  - `Principal` / `NotPrincipal` – **resource-based policies only** (who). Not used in identity policies (the principal is the attached identity).
  - `Action` / `NotAction` – API operations like `s3:GetObject`.
  - `Resource` / `NotResource` – ARNs.
  - `Condition` – optional extra tests.
- **`Action: "*"`** and **`Resource: "*"`** are wildcards; wildcards in actions (`s3:Get*`) are allowed.
- **`NotAction` with Allow** = "allow everything except these" (dangerous). **`NotAction` with Deny** = "deny everything except these" (common guardrail pattern).
- **Policy variables**: `${aws:username}`, `${aws:PrincipalTag/team}`, `${aws:userid}` for per-user paths (needs `Version 2012-10-17`).
- **ARN format**: `arn:partition:service:region:account-id:resource`. S3 bucket ARNs have no Region/account (`arn:aws:s3:::bucket/key`).
- Actions come in **access levels**: List, Read, Write, Permissions management, Tagging.
- **Resource-level permissions** vary by action; some actions only accept `Resource: "*"` (for example many `List*`/`Describe*`).
- Policy size limits: **inline policy per entity: user 2,048, group 5,120, role 10,240 characters** (aggregate, whitespace not counted); **managed policy 6,144 characters**; **role trust policy 2,048 default (up to 8,192)**.
- **Managed policies attached**: per **role default 10** (max 25 by request), per **user 10** (max 20), per **group 10**.
- Policy documents allow only certain characters (tab, LF, CR, U+0020–U+00FF).

## F. Conditions (know these)
- Structure: `"Condition": {"Operator": {"key": "value"}}`. **Multiple values for one key = OR; multiple keys/operators = AND.**
- Operators: `StringEquals`, `StringLike` (wildcards), `StringNotEquals`, `ArnLike/ArnEquals`, `NumericLessThan`, `DateGreaterThan`, `Bool`, `IpAddress/NotIpAddress`, `Null`, `...IfExists`, set operators `ForAllValues:` / `ForAnyValue:`.
- Common **global condition keys**:
  - `aws:PrincipalArn`, `aws:PrincipalOrgID`, `aws:PrincipalOrgPaths`, `aws:PrincipalTag/<key>`, `aws:PrincipalAccount`, `aws:PrincipalIsAWSService`
  - `aws:ResourceTag/<key>`, `aws:ResourceOrgID`, `aws:ResourceAccount`
  - `aws:RequestTag/<key>`, `aws:TagKeys`, `aws:RequestedRegion`
  - `aws:SourceIp`, `aws:SourceVpc`, `aws:SourceVpce`, `aws:VpcSourceIp`, `aws:ViaAWSService`, `aws:CalledVia`
  - `aws:SecureTransport`, `aws:MultiFactorAuthPresent`, `aws:CurrentTime`, `aws:userid`, `aws:SourceArn`, `aws:SourceAccount`
- **Service-specific keys** exist too (`s3:prefix`, `s3:x-amz-server-side-encryption`, `kms:ViaService`, `kms:EncryptionContext:…`, `iam:PassedToService`, `glue:…`).
- **`aws:SourceIp` does not work for calls made through a VPC endpoint** (use `aws:SourceVpc/SourceVpce`) or for AWS services calling on your behalf (use `aws:ViaAWSService`/`aws:CalledVia`).
- **`aws:PrincipalOrgID`** in a resource policy is the easy way to say "any account in my organization".
- **`Null`** tests whether a key exists; useful to require a tag.
- Using an IfExists-less operator with a key that is missing in the request makes the condition **false**.

## G. Evaluation logic (the exam favourite)
- **Order of thinking**:
  1. **Explicit Deny** anywhere (identity, resource, boundary, SCP, RCP, session) → **DENY**.
  2. Organization **RCPs**: must allow (resource side guardrail).
  3. Organization **SCPs**: must allow (principal side guardrail).
  4. **Resource-based policy** may allow.
  5. **Identity-based policy** must allow (for most same-account cases).
  6. **Permissions boundary** must allow if set.
  7. **Session policy** must allow if set.
  8. Otherwise **implicit deny**.
- **Same account**: access is the **union** of identity-based and resource-based policies (either can allow), except boundaries/SCPs/session policies act as intersections for identity-based grants. An explicit deny in any wins.
- **Cross-account**: both sides must allow: the **resource policy in the resource account** (or a role assumed in that account) **and** the **identity policy in the caller's account**.
- **Resource policy naming a role/user ARN directly** can grant same-account access **without** the identity policy allowing it. **Resource policy naming an assumed-role session ARN or a federated user** does **not** bypass boundaries the same way **(verify exact rule)**.
- **Permissions boundary**: effective permissions = **intersection** of identity-based policy and boundary. Boundaries do not limit resource-based grants to the user ARN (in same account) **(verify)**.
- **SCP**: even **Admin** or **root** in a member account cannot exceed the SCP. SCPs do not apply to the **management account** or to **service-linked roles**.
- **Session policy**: intersection with the role's identity policies; cannot add permissions. Max **10 managed policy ARNs** and **2,048 characters** combined (`AssumeRole`).
- **Allow-list vs deny-list SCP**: default `FullAWSAccess` is attached; deny-list adds Denies (easier). Allow-list removes `FullAWSAccess` and allows only listed services (stricter).
- **Implicit deny vs explicit deny**: implicit is overridden by any Allow; explicit is never overridden.
- **`NotPrincipal`** with Allow is dangerous; avoid it.
- **Anonymous (public) access** is evaluated with only the resource policy.
- **Policy simulator** and **IAM Access Analyzer** can test and validate.

## H. Permissions boundaries (delegation pattern)
- Attach a **boundary** to a role/user to cap what it can ever do, even if an admin attaches `AdministratorAccess`.
- Pattern: delegate role creation to developers **only if** `iam:CreateRole` has a condition `iam:PermissionsBoundary = <boundary ARN>`, and deny `DeleteRolePermissionsBoundary`.
- Boundaries apply to **users and roles**, not groups.
- Effective = identity-based ∩ boundary (∩ SCP ∩ session policy). Resource policies naming the principal directly can still allow beyond a boundary.
- Use for **self-service platforms** (data teams create Glue/EMR roles safely).

## I. RBAC vs ABAC
- **RBAC** (role-based): permissions by job function via roles/groups. Needs many roles as teams grow.
- **ABAC** (attribute-based): permissions by **tags**. Allow when `aws:PrincipalTag/project` = `aws:ResourceTag/project`. Scales with fewer policies.
- ABAC needs: consistent **tag governance**, who can set tags (`aws:RequestTag`, `aws:TagKeys` conditions), and **session tags** / identity-provider attributes (Identity Center attributes for access control).
- Not every service supports tag-based conditions equally; check the service authorization reference.
- **Tag-on-create** protection: require tags in the create call with `aws:RequestTag` and `aws:TagKeys`; deny tag edits for protected tags.
- **Lake Formation LF-Tags** are the data-lake version of ABAC (separate service).

## J. Least privilege workflow
- Start with a broad AWS managed policy in **dev**, then use **Access Advisor** (last accessed services/actions) and **IAM Access Analyzer policy generation** (from CloudTrail) to produce a tight policy.
- Use **Access Analyzer unused access** findings to remove unused roles, keys, and permissions.
- Use **customer managed policies** with **conditions** (VPC endpoint, tag, org ID, MFA) rather than wide `*`.
- Prefer **resource-level** ARNs and **specific actions**.
- Use **IAM policy validation** and **custom policy checks** in CI.
- Use **service control policies** for guardrails and **permissions boundaries** for delegated admin.

## K. Exam skills mapping
- **4.1.2 IAM groups, roles, endpoints, services**: groups, roles, service roles.
- **4.2.1 Custom IAM policies**: custom policies and conditions.
- **4.2.5 Role-based, tag-based, attribute-based authorization**: RBAC vs ABAC.
- **4.2.6 Least-privilege custom policies**: least privilege.

## L. Scenarios: "If X → Y, because Z"
- If a Glue job needs S3 and Glue Catalog access → **a service role trusted by `glue.amazonaws.com` with scoped S3/Glue permissions**, because jobs run as the role, not as the user.
- If a user has Allow on `s3:GetObject` but gets `AccessDenied` → **check for explicit deny (bucket policy, SCP, RCP, boundary, session policy) and KMS permissions**, because any one deny or missing layer blocks.
- If a bucket in account B must be read by a role in account A → **allow in the bucket policy for A's role AND allow in A's role policy**, because cross-account needs both sides.
- If an admin attaches AdministratorAccess to a dev's role but you want a hard cap → **permissions boundary (or SCP)**, because those limit even admin policies.
- If developers must create roles themselves safely → **boundary + `iam:CreateRole` with `iam:PermissionsBoundary` condition**, because it forces every new role under the cap.
- If many teams each need access only to their own tagged resources → **ABAC with `aws:PrincipalTag` = `aws:ResourceTag`**, because one policy scales across teams.
- If you must allow all accounts in your organization to read a bucket → **`aws:PrincipalOrgID` in the bucket policy**, because new accounts are covered automatically.
- If requests must come only through your VPC endpoint → **bucket policy Deny when `aws:SourceVpce` is not your endpoint**, because it blocks other paths.
- If `aws:SourceIp` rule breaks for Athena or Glue calls → **use `aws:ViaAWSService`/VPC conditions**, because the source IP is the service's, not the user's.
- If a managed policy hits the 6,144-character limit → **split policies or use tags/wildcards, or raise via multiple attachments**, because the limit is fixed per managed policy.
- If a role has 10 managed policies attached already → **request a quota increase (to 25) or consolidate**, because the default limit is 10.
- If the root user is used for daily work → **stop, enable MFA, delete root access keys, use roles/Identity Center**, because root cannot be limited by IAM.

Verified from AWS docs on 2026-11-03 (IAM policy evaluation logic, IAM and STS quotas, SCPs, RCPs, STS credential methods).
Unconfirmed (verify): resource-policy behaviour for assumed-role session principals vs boundaries; centralized root access management details; CodeCommit availability; job-function managed policy names; managed policy version count (5); credential report refresh interval (4 hours); `aws:SourceIp` edge cases.

# S3 – 3. Security: encryption, access control, private access, auditing

Short notes. Each point is a fact you can be asked about.

## A. The security layers (big picture)
- Layer 1: Block Public Access (stops public exposure whatever the policies say).
- Layer 2: IAM identity policies + bucket policies (who can do what).
- Layer 3: Object Ownership (who owns uploaded objects, ACLs off).
- Layer 4: Access Points / Access Grants (scalable sharing).
- Layer 5: Encryption at rest and in transit.
- Layer 6: Private network path (VPC endpoint, endpoint policy).
- Layer 7: Audit (CloudTrail, access logs, Access Analyzer, Macie).
- Layer 8: Data protection (versioning, Object Lock, MFA Delete, replication).
- Default for a new bucket: private, Block Public Access on, ACLs off, SSE-S3 on.

## B. Encryption at rest – the options
- Since 5 Jan 2023 every new object is encrypted with SSE-S3 automatically, at no cost.
- SSE-S3: S3 manages keys (AES-256). Free. No key control, no per-key audit.
- SSE-KMS: you use an AWS KMS key. Gives key policy control, CloudTrail audit of key use, rotation options. KMS request cost and KMS API limits apply.
- DSSE-KMS: two layers of encryption with KMS keys. For strict compliance rules. Bucket Keys are not supported with it.
- SSE-C: you send your own key with every request (HTTPS only). S3 does not store the key. You must manage keys; lose the key, lose the data.
- Client-side encryption: you encrypt before upload. AWS never sees plaintext or keys (for example AWS Encryption SDK or the S3 encryption client).
- SSE-C change: from 6 April 2026 SSE-C is disabled by default on all new buckets and on existing buckets with no SSE-C data. To use it you must set `BlockedEncryptionTypes` to NONE in the bucket's default encryption config. Blocked requests get 403 AccessDenied. (Reason: ransomware attacks used attacker-controlled keys.)
- Express One Zone: SSE-S3 default, SSE-KMS allowed, SSE-C and DSSE-KMS not supported.
- Default bucket encryption can only be set to SSE-S3, SSE-KMS or DSSE-KMS (not SSE-C).
- Changing the default does not re-encrypt existing objects. Re-encrypt old objects with S3 Batch Operations Copy (get the list from S3 Inventory).
- Encryption in S3 Storage Lens/Inventory shows the percent of encrypted objects.
- You cannot turn encryption off.

## C. SSE-KMS details
- Each object gets its own data key; S3 calls KMS on every PUT/GET without Bucket Keys.
- Heavy workloads (millions of GETs, Athena, EMR, Glue) can hit KMS request-rate limits and costs.
- S3 Bucket Keys: S3 asks KMS for a short-lived bucket-level key and uses it to make data keys. Reduces KMS requests and cost by up to 99%.
- Bucket Keys apply only to new objects after you enable it. For old objects use CopyObject.
- Bucket Key is shared only for objects with the same KMS key.
- With Bucket Keys the encryption context uses the bucket ARN, not the object ARN. Update IAM/KMS policies that used the object ARN as context.
- CloudTrail KMS events show the bucket ARN and fewer events.
- Not supported for DSSE-KMS.
- AWS managed key `aws/s3`: free key, but you cannot edit its policy and it cannot be shared cross-account. Use a customer managed key (CMK) for cross-account access or custom policies.
- Cross-account read of SSE-KMS data needs: bucket policy/IAM allow on S3 AND KMS key policy/IAM allow `kms:Decrypt` for the reader.
- Reader error "AccessDenied" while S3 permission looks fine usually means missing KMS permission.
- KMS key must be in the same Region as the bucket (multi-Region keys are separate keys per Region).
- To force a specific encryption: bucket policy deny `s3:PutObject` unless header `x-amz-server-side-encryption` equals `aws:kms` (and optionally the key ID).
- Deleting or disabling the KMS key makes the data unreadable.

## D. Encryption in transit
- S3 supports HTTPS (TLS). Use it always.
- Enforce HTTPS with a bucket policy: deny all actions when `aws:SecureTransport` is `false`.
- Enforce a minimum TLS version with the `s3:TlsVersion` condition key.
- Client-side encryption protects data before it leaves the client ("before transit").
- VPC endpoints and Direct Connect/VPN keep traffic off the public internet, but still use TLS.

## E. Block Public Access (BPA)
- Four independent settings: BlockPublicAcls, IgnorePublicAcls, BlockPublicPolicy, RestrictPublicBuckets.
- BlockPublicAcls: reject PUT calls that set public ACLs.
- IgnorePublicAcls: ignore all existing public ACLs.
- BlockPublicPolicy: reject bucket/access-point policies that allow public access.
- RestrictPublicBuckets: if a bucket has a public policy, only AWS services and authorized users in the owner's account can use it (blocks cross-account too).
- Levels: organization (AWS Organizations policy, all four together), account, bucket, access point. The most restrictive combination wins.
- Account level applies to all Regions. Not supported per object.
- BPA does not change existing policies/ACLs; removing BPA makes public policies live again.
- "Public" means ACL grants to AllUsers/AuthenticatedUsers, or policy with wildcard principal without a fixed restricting condition (such as fixed `aws:SourceVpce`, `aws:PrincipalOrgID`, or `aws:SourceIp` with a tight CIDR).
- Broad `aws:SourceIp` ranges (like 0.0.0.0/1) count as public.
- Access point BPA settings can only be set when you create the access point.
- Static website hosting needs BPA relaxed for that bucket only.
- Directory buckets: BPA always on and cannot be changed.
- IAM Access Analyzer for S3 lists buckets that are public or shared outside the account/org.

## F. Object Ownership and ACLs
- Bucket owner enforced (default): ACLs disabled, bucket owner owns every object. Access is only by policies. Recommended.
- Bucket owner preferred: ACLs on; objects uploaded with `bucket-owner-full-control` become owned by the bucket owner.
- Object writer: uploader owns the object. ACLs on. Old model; avoid.
- With ACLs disabled, PUT requests that set other ACLs fail with 400 `AccessControlListNotSupported`. `bucket-owner-full-control` or no ACL works.
- Problem fixed by enforced: another account uploads files and the bucket owner cannot read them.
- You can re-enable ACLs later; old ACL permissions return.
- Before disabling ACLs on an existing bucket: review ACL permissions, find requests that needed ACLs, fix policies using ACL condition keys.
- Replication with enforced ownership: replicas are owned by the destination bucket owner (replaces owner override).

## G. IAM policy vs bucket policy
- Identity-based policy: attached to a user/role. Says what that identity can do.
- Bucket policy: attached to the bucket. Says who (even other accounts, services, anonymous) can do what to it.
- Same account: an Allow in either IAM or bucket policy is enough (unless an explicit Deny exists).
- Cross-account: needs Allow in the caller's identity policy AND in the bucket policy.
- Explicit Deny always wins.
- Bucket policy size limit 20 KB. IAM policy size limits are smaller (docs cite 5 KB for the IAM side). Big environments outgrow these → Access Points or Access Grants.
- Resource ARNs: bucket actions (`s3:ListBucket`) use `arn:aws:s3:::bucket`. Object actions (`s3:GetObject`) use `arn:aws:s3:::bucket/*`. Mixing them up is the classic mistake.
- `s3:ListBucket` needs the bucket ARN; with a prefix, use the `s3:prefix` condition.
- Useful condition keys: `aws:SourceVpce`, `aws:SourceVpc`, `aws:SourceIp`, `aws:PrincipalOrgID`, `aws:SecureTransport`, `aws:PrincipalTag`, `s3:x-amz-server-side-encryption`, `s3:prefix`, `s3:TlsVersion`, `s3:object-lock-remaining-retention-days`.
- Permission delegation: an account that receives permissions cannot re-delegate cross-account.
- Bucket owner can deny access to or delete any object in its bucket, whoever owns it.
- Roles for services (Glue, Athena, EMR, Lambda) need S3 permissions on their role, not on the user.
- Service Control Policies (SCPs) and Resource Control Policies (RCPs) can set organization-wide limits.
- Use least privilege: grant only the prefixes and actions needed.

## H. Access Points
- A named endpoint attached to a bucket (or an FSx volume or a Backup recovery point). Each has its own policy (up to 20 KB) and its own network and BPA settings.
- Thousands per Region per account (default quota; verify exact).
- Solves: one huge bucket policy for many teams. Create one access point per team/app.
- Can be restricted to a VPC (network origin VPC): then reachable only from inside that VPC. Always counts as non-public.
- Access point policy works together with the bucket policy. Delegate by a bucket policy that allows access when `s3:DataAccessPointAccount` is your account.
- Only for object operations. You cannot delete buckets or set replication through an access point.
- Referenced by access point ARN, alias, or virtual-hosted style URI.
- Cross-account access points are possible (the bucket owner must also allow it).
- Multi-Region Access Point is a different thing (global routing) – see the replication file.

## I. S3 Access Grants
- Map identities to S3 prefixes: read-only, write-only, or read-write per prefix.
- Identities can be IAM principals or corporate directory users/groups (through IAM Identity Center).
- App asks Access Grants for temporary credentials for the end user; CloudTrail data events name the real user (with trusted identity propagation).
- Fits large numbers of users/datasets where bucket policies get too big.
- Supports cross-account grants.
- Works with Athena, EMR and other analytics tools through IAM Identity Center trusted identity propagation.

## J. Pre-signed URLs
- Temporary link for one object (download or upload) signed with the signer's credentials.
- The link works only as long as the signer's credentials are valid and the URL is not expired.
- If signed by a role with temporary credentials, the URL can expire sooner than the time you set.
- Use for letting browsers upload directly or sharing a file briefly.
- Not a good tool for broad access control. Anyone with the URL can use it.

## K. Private network access
- Gateway VPC endpoint for S3: free, route-table entry, traffic stays on the AWS network. Lets private subnets reach S3 without NAT.
- Interface endpoint (PrivateLink) for S3: costs money; works from on-premises over Direct Connect/VPN, and across Regions/VPCs.
- Endpoint policy: limits which buckets/actions are allowed through the endpoint.
- Bucket policy can require the endpoint: deny unless `aws:SourceVpce` equals your endpoint ID.
- A bucket policy that denies everything not from the VPC endpoint also blocks the console and your own admin access. Test carefully.
- Cheapest private path from EC2/Glue/EMR in a VPC to S3: gateway endpoint (NAT gateway costs per GB).
- Express One Zone also supports a gateway endpoint at no extra charge.

## L. Auditing and logging
- CloudTrail management events: bucket-level actions (create bucket, put policy, put lifecycle). On by default in Event history (90 days).
- CloudTrail data events: object-level actions (GetObject, PutObject, DeleteObject). Off by default; paid; turn on per bucket via advanced event selectors.
- Trail delivers logs to an S3 bucket (one copy of management events free). CloudTrail Lake lets you query events with SQL.
- Server access logging: best-effort detailed request logs delivered to another bucket (target bucket must not be the same bucket in practice; use a separate log bucket). Cheaper but not guaranteed complete or instant.
- CloudTrail is for structured, reliable API audit; server access logs are for per-request detail and cheap analysis (Athena).
- Server access logs are not supported on Express One Zone.
- CloudWatch metrics: daily storage metrics free; request metrics are optional and paid (per bucket/prefix/tag filters).
- S3 Storage Lens: org-wide usage and activity dashboards, also shows encryption and Object Ownership status.
- S3 Inventory: scheduled list of objects with metadata (including encryption status, replication status, Object Lock status).
- IAM Access Analyzer for S3: finds public and cross-account access.
- Amazon Macie: scans S3 for PII and credentials; findings go to Security Hub/EventBridge.
- AWS Config rules (for example public read prohibited, encryption enabled) detect and remediate drift.
- GuardDuty S3 protection: detects suspicious S3 data access from CloudTrail data events.

## M. Data protection checklist (ransomware, insider, mistakes)
- Versioning on, Block Public Access on, ACLs off.
- Object Lock (compliance) for must-keep data. MFA Delete for versioned buckets.
- Replicate to another account and Region with different keys.
- Restrict `s3:DeleteObjectVersion`, `s3:PutBucketPolicy`, `s3:PutLifecycleConfiguration`, and KMS key deletion.
- Use SCPs to protect critical buckets.
- Alert on policy changes and public-access changes (CloudTrail + EventBridge, Config).
- Keep SSE-C disabled unless needed.

## N. Scenarios (if → then, because)
- **If** a job in a private subnet must reach S3 with no internet and low cost, **then** use an **S3 gateway VPC endpoint**. It is a route-table entry that keeps traffic on the AWS network. **This works because** a gateway endpoint is **free** and lets private subnets reach S3 **without a NAT gateway**, which charges per GB.
- **If** only your Virtual Private Cloud (VPC) may read a bucket, **then** add a bucket policy that denies access unless **`aws:SourceVpce`** equals your VPC endpoint ID. **This works because** the condition ties access to that endpoint. The catch: this deny also blocks the console and your own admin access from outside the VPC, so test carefully.
- **If** an on-premises network must reach S3 privately, **then** use an **S3 interface endpoint** (AWS PrivateLink) over **AWS Direct Connect** or VPN. **This works because** interface endpoints are reachable from on-premises, while gateway endpoints are not. Interface endpoints cost money; gateway endpoints are free.
- **If** another account uploads files to your bucket and you cannot read them, **then** set **Object Ownership** to **bucket owner enforced**. **This works because** this setting turns off access control lists (ACLs) and makes the bucket owner own **every object**, so only policies decide access. It is the default for new buckets.
- **If** you must give **500 teams** different access to one data lake bucket, **then** use **S3 Access Points** (one per team, each with its own policy) or **S3 Access Grants** (map identities to prefixes as read, write or read-write). **This works because** one bucket policy is limited to **20 KB** and would grow too large; access points and grants split the rules into many small pieces.
- **If** users are in a corporate directory and you want per-user audit, **then** use **S3 Access Grants** with **AWS IAM Identity Center** trusted identity propagation. **This works because** the app gets temporary credentials for the end user, and AWS CloudTrail data events then name the real user.
- **If** auditors need to know who read which object, **then** turn on **AWS CloudTrail data events** for the bucket. **This works because** data events log object-level actions such as GetObject, PutObject and DeleteObject. They are **off by default** and paid; management events only cover bucket-level actions.
- **If** you need cheap bulk request history for analysis, **then** turn on **S3 server access logging** to a separate log bucket and query the logs with **Amazon Athena**. **This works because** access logs give cheap per-request detail. The catch: delivery is best-effort, so logs are not guaranteed complete or instant; use CloudTrail for reliable audit.
- **If** all uploads must be encrypted with **SSE-KMS** (server-side encryption with AWS Key Management Service keys), **then** set **default encryption** to SSE-KMS and add a bucket policy that denies `s3:PutObject` unless the header **`x-amz-server-side-encryption`** equals `aws:kms` (optionally also the key ID). **This works because** the default encrypts uploads that send no header, and the deny rejects uploads that ask for another type.
- **If** **SSE-KMS** makes Amazon Athena or AWS Glue queries throttle or cost too much, **then** turn on **S3 Bucket Keys** and raise the **AWS Key Management Service (KMS)** request quotas. **This works because** without Bucket Keys S3 calls KMS on every PUT and GET; with them, S3 uses a short-lived bucket-level key and cuts KMS requests and cost by up to **99%**. Bucket Keys apply only to new objects; copy old ones to use them.
- **If** another account cannot read your **SSE-KMS** objects, **then** use a **customer managed key (CMK)** and allow the reader `kms:Decrypt` in the key policy (or a grant), as well as in the bucket policy. **This works because** cross-account reads need permission on both S3 and AWS Key Management Service (KMS), and the AWS managed key `aws/s3` cannot be shared across accounts or have its policy edited.
- **If** only HTTPS may be used, **then** add a bucket policy that **denies** all actions when **`aws:SecureTransport`** is `false`. **This works because** any request over plain HTTP then fails.
- **If** no bucket may ever become public anywhere in your organization, **then** set **Block Public Access (BPA)** at the **organization level** (an AWS Organizations policy) and add a **Service Control Policy (SCP)**. **This works because** organization-level BPA applies all four settings, and the most restrictive level always wins, so one account or bucket cannot relax it.
- **If** a bucket policy is rejected as "public", **then** add a fixed restricting condition (such as **`aws:PrincipalOrgID`**, a fixed `aws:SourceVpce`, or a tight `aws:SourceIp` range) or name fixed principals. **This works because** S3 treats a wildcard principal without such a condition as public, and Block Public Access then rejects the policy.
- **If** you want to use your own keys and AWS must never see the data, **then** use **client-side encryption** (for example the AWS Encryption SDK). **This works because** data is encrypted before upload, so AWS never sees plaintext or keys.
- **If** you want all **old objects** encrypted with **SSE-KMS**, **then** list them with **S3 Inventory** and re-encrypt them with an **S3 Batch Operations Copy** job. **This works because** changing the bucket's default encryption only affects **new** objects; existing objects keep their old encryption until they are copied.
- **If** you need to know which buckets contain personal data (PII), **then** use **Amazon Macie**. **This works because** Macie scans S3 for PII and credentials and sends findings to Security Hub or EventBridge.
- **If** someone needs a temporary download link for one file, **then** create a **pre-signed URL**. **This works because** it is a time-limited link signed with your credentials. Anyone with the URL can use it, and it can expire sooner if signed with temporary role credentials.
- **If** a legal order requires that nobody can alter the data, **then** use **S3 Object Lock** in **compliance mode**. **This works because** in compliance mode nobody, **not even the root user**, can delete a locked version or shorten its retention.
- **If** you want to detect a bucket that becomes public, **then** use an **AWS Config** rule (for example public read prohibited) or an **IAM Access Analyzer** for S3 finding, with an **Amazon EventBridge** alert. **This works because** Config detects drift from your rules, and Access Analyzer lists buckets that are public or shared outside your account or organization.
- **If** a user can list a bucket but not read its objects, **then** add the object ARN **`arn:aws:s3:::bucket/*`** to the policy. **This works because** `s3:ListBucket` uses the bucket ARN, while `s3:GetObject` needs the object ARN; mixing them up is the classic mistake.

## Verified from AWS docs on 2026-10-02
Encryption overview, SSE-C change (April 2026), Bucket Keys, Block Public Access, Object Ownership, Access Points, Access Grants, CloudTrail logging pages were read. Not re-checked: exact access point quota, TLS condition key details, IAM policy size limits for roles vs users (verify).

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
- If a private-subnet job must reach S3 with no internet and low cost → S3 gateway VPC endpoint, because it is free and needs no NAT.
- If only your VPC may read a bucket → bucket policy with `aws:SourceVpce` condition, because it ties access to the endpoint.
- If on-premises must reach S3 privately → interface endpoint over Direct Connect/VPN, because gateway endpoints are not reachable from on-premises.
- If another account uploads files and you can't read them → Object Ownership bucket owner enforced, because the owner then owns all objects.
- If you must give 500 teams different access to one data lake bucket → Access Points or Access Grants, because one bucket policy would exceed 20 KB.
- If users are in a corporate directory and you want per-user audit → Access Grants with IAM Identity Center trusted identity propagation.
- If auditors need to know who read which object → CloudTrail data events for the bucket (they are off by default).
- If you need cheap bulk request history for analysis → server access logs queried with Athena.
- If all uploads must be KMS-encrypted → bucket policy deny unless `x-amz-server-side-encryption` is `aws:kms`, plus default encryption SSE-KMS.
- If SSE-KMS makes Athena/Glue queries throttle or expensive → enable S3 Bucket Keys and raise KMS quotas.
- If another account can't read SSE-KMS objects → add KMS key policy/grant and use a customer managed key, because aws/s3 keys can't be shared.
- If only HTTPS must be used → bucket policy deny when `aws:SecureTransport` is false.
- If you must not let any bucket become public in the whole organization → organization-level BPA policy plus SCP.
- If a bucket policy was rejected as "public" → add a fixed condition (such as `aws:PrincipalOrgID`) or fixed principals.
- If you need the client's own keys with AWS unable to see data → client-side encryption.
- If you want to encrypt all old objects with SSE-KMS → S3 Inventory + Batch Operations Copy, because changing default only affects new objects.
- If you need to know which buckets contain PII → Macie.
- If someone wants a temporary download link for a file → pre-signed URL.
- If a legal order requires nobody to alter data → Object Lock compliance mode.
- If you want to detect a bucket made public → Config rule or Access Analyzer finding with EventBridge alert.
- If a user can list but not read objects → missing `bucket/*` object ARN in the policy.

## Verified from AWS docs on 2026-10-02
Encryption overview, SSE-C change (April 2026), Bucket Keys, Block Public Access, Object Ownership, Access Points, Access Grants, CloudTrail logging pages were read. Not re-checked: exact access point quota, TLS condition key details, IAM policy size limits for roles vs users (verify).

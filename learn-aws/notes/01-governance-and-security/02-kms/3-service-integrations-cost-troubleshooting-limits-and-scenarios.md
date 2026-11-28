# AWS KMS – 3. Service integrations, cost, troubleshooting, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. How AWS services use KMS
- Services use **server-side encryption (SSE) with envelope encryption**: they call `GenerateDataKey`/`Decrypt` (or create **grants**) on your behalf using a **service principal or your role**.
- In CloudTrail you see the call made by the service with **`invokedBy`** and **encryption context** (for example `aws:s3:arn`, `aws:rds:db-id`).
- The caller (user/role) usually needs **permission on the key too**, because the service acts "via" them: the identity must be allowed `kms:Decrypt` (and often `GenerateDataKey`) for operations like reading S3 SSE-KMS objects.
- **Key policy conditions** like `kms:ViaService` limit use to that service.
- **Encryption setting often can't be changed in place** for some resources; plan the key at creation.

## B. S3
- **SSE-S3** (AES-256, AWS owned keys, free, default since Jan 2023), **SSE-KMS** (AWS managed `aws/s3` or CMK; audit via CloudTrail; per-request KMS cost), **DSSE-KMS** (dual-layer), **SSE-C** (customer-provided key per request, must use HTTPS), **client-side encryption**.
- **Default encryption** on every bucket: SSE-S3 unless you change to SSE-KMS (bucket-level setting).
- **S3 Bucket Keys**: S3 generates a bucket-level key from KMS and derives per-object data keys → **dramatically fewer KMS requests and lower cost**. Supported with SSE-KMS (not with SSE-C). Replication and Batch Operations preserve settings (check).
- **Reading SSE-KMS objects** needs `s3:GetObject` **and** `kms:Decrypt` on the key. **Writing** needs `s3:PutObject` and `kms:GenerateDataKey` (+ `kms:Decrypt` for multipart upload).
- **Cross-account access to SSE-KMS objects** requires the **customer managed key** policy to allow the other account; `aws/s3` **cannot be shared**.
- **Replication of SSE-KMS objects**: enable "replicate objects encrypted with KMS", specify the **destination key**, and the replication role needs `kms:Decrypt` (source) and `kms:Encrypt/GenerateDataKey` (destination).
- **Enforce SSE-KMS** with a bucket policy `Deny` on `PutObject` unless `s3:x-amz-server-side-encryption = aws:kms` (and optionally the key ID).
- **Athena/Glue/EMR/Redshift Spectrum** reading SSE-KMS objects need the **job/query role** to have `kms:Decrypt`.
- **Athena query results** can be encrypted with SSE-S3, SSE-KMS or CSE-KMS (workgroup setting).
- **S3 Express One Zone**: SSE-S3 or SSE-KMS (limited) **(verify)**.
- **Changing encryption of existing objects**: copy objects (S3 Batch Operations `Copy`) to apply the new key.

## C. Databases and warehouses
- **RDS/Aurora**: encryption chosen **at creation**; cannot be turned on later for an existing unencrypted instance (restore from encrypted **snapshot copy**). Read replicas, snapshots, logs, backups inherit encryption. **Cross-Region read replicas/snapshot copy need a destination-Region key**. Aurora Global DB uses a key per Region.
- **Redshift**: cluster encryption with KMS using a **hierarchy** (root key → cluster key → database key → data encryption keys); can be enabled by **modify cluster** (migration happens in the background); **Redshift Serverless** encrypts with KMS (AWS owned or CMK; set at namespace creation, changeable by update). **Snapshots** copied cross-Region need a destination-Region key and a **snapshot copy grant**.
- **DynamoDB**: always encrypted at rest; choose **AWS owned key** (default, free), **AWS managed key** (`aws/dynamodb`), or **CMK**; can switch among them on a table. **Global tables** need a key in each replica Region (MRK optional). DAX supports encryption at rest.
- **DocumentDB/Neptune/ElastiCache/MemoryDB/Keyspaces/Timestream/OpenSearch/MSK**: encryption at rest with KMS (AWS owned or CMK) set at creation mostly.
- **EBS**: volumes/snapshots encrypted with a key; **default EBS encryption** can be enabled per Region; sharing an encrypted snapshot cross-account needs a **CMK** and key sharing.
- **EFS/FSx**: encrypted with KMS; EFS must be encrypted **at creation**.

## D. Analytics, streaming and processing
- **Glue**: encryption settings via a **security configuration** (S3 encryption SSE-S3/SSE-KMS, CloudWatch Logs encryption, **job bookmark encryption**), plus **Data Catalog encryption** (metadata and connection passwords) with a KMS key. The Glue job role needs the key permissions.
- **EMR**: at-rest encryption for **EBS volumes** (EMR security configuration, LUKS or EBS encryption), **S3 data** (EMRFS SSE-S3/SSE-KMS/CSE-KMS), local disk encryption; **in-transit** via TLS (PEM certificates). EMR Serverless/Studio also support KMS.
- **Kinesis Data Streams**: SSE with KMS (AWS managed `aws/kinesis` or CMK); producers/consumers need KMS permissions; KMS throttling can slow throughput. **Firehose**: encrypts delivery to S3 with KMS and source stream SSE; role needs `kms` permissions.
- **MSK**: at-rest encryption with KMS; in-transit TLS.
- **Lambda**: environment variables encrypted with a KMS key; **encryption helpers** for sensitive vars; also function code/layers via S3.
- **Step Functions**: optional CMK for state machine definition and execution data (data key reuse 60–900 s).
- **MWAA**: AWS owned or CMK (cannot change later; alias/multi-Region keys not supported).
- **SQS/SNS**: SSE with KMS (`aws/sqs`/`aws/sns` or CMK); producers need `GenerateDataKey/Decrypt`; **S3/SNS → SQS** needs service principals in the key policy; data-key reuse period (60 s – 24 h) trades cost for freshness **(verify bounds)**.
- **CloudWatch Logs**: log group encryption with a CMK; key policy must allow `logs.<region>.amazonaws.com` with `kms:EncryptionContext:aws:logs:arn`.
- **CloudTrail**: SSE-KMS for log files; the key policy must allow `cloudtrail.amazonaws.com` (with `aws:SourceArn` and encryption-context conditions).
- **Secrets Manager / Parameter Store (SecureString)**: encrypted with `aws/secretsmanager` / `aws/ssm` or a CMK (CMK needed for cross-account sharing).
- **Athena**: encrypts query results and (for federated queries) spill buckets; supports CSE-KMS reading.
- **Lake Formation**: data location role needs KMS permissions for encrypted S3 locations.
- **SageMaker**: training volumes, endpoints, notebooks with KMS keys; **Bedrock** custom models/knowledge bases with CMK.
- **DMS**: encrypts replication instance storage and endpoint passwords with KMS.
- **AWS Backup**: backup vault encryption key (separate from source); cross-account copy needs the destination vault key policy.
- **Data lake pattern**: one CMK per data domain/zone (raw, curated, sensitive) with a policy allowing the data-platform roles, so you can revoke a domain by disabling/deleting its key.

## E. Encryption and data masking (DEA-C01 4.3)
- **Encryption** protects data from unauthorized reading at rest/in transit; **masking** hides parts of values from authorized-but-limited users.
- **Masking options**: Redshift **dynamic data masking**, Lake Formation **data filters (row/column/cell)**, Glue **Detect PII transform** (redact/hash/mask), Athena views/UDFs, Macie discovery, QuickSight column-level security.
- **Tokenization/hashing**: HMAC via KMS, SHA-256 with salt in Glue/Spark; **format-preserving** with partners.
- **Client-side field-level encryption** with the **AWS Encryption SDK** or DynamoDB Encryption Client for per-attribute protection.
- **Redshift column-level encryption** is done with SQL functions (not by the cluster key); use masking policies for display control.
- **Cross-Region encryption**: for S3 CRR, RDS/Redshift snapshot copy, EBS copy, DynamoDB global tables → keys are **per Region** (or MRK); the destination needs its key and permissions.

## F. Cost
- **Key fees**: $1/CMK/month (each MRK replica too); rotated key material adds $1 for first two rotations.
- **Requests**: $0.03 / 10,000 symmetric; $0.15 / 10,000 asymmetric; **20,000 free requests per month**.
- **AWS managed keys**: no key fee; requests billed.
- **Biggest drivers**: S3 SSE-KMS at billions of objects, DynamoDB/EBS/Redshift heavy use with CMKs, Lambda/Secrets Manager reads.
- **Cost levers**: **S3 Bucket Keys**, data key caching in apps, longer **data key reuse** for SQS/Step Functions (60–900 s), avoid one key per object/microservice, **consolidate keys per data domain** (not per bucket), delete unused keys, avoid CloudHSM keystores unless needed.
- **Custom key store**: $1/key plus CloudHSM (~$1.60/HSM/hour in the pricing example → ~$2,380 per two HSMs per month) — expensive.
- Use **Cost Explorer** usage types `*-KMS-Keys` and `*-KMS-Requests` to analyze.

## G. Troubleshooting (symptom → cause → fix)
- **`AccessDeniedException ... is not authorized to perform: kms:Decrypt`** → key policy does not allow the principal, or IAM lacks permission (and key policy does not enable IAM), or SCP/RCP denies, or `kms:ViaService`/context condition mismatch → fix the key policy/IAM, check conditions.
- **S3 `AccessDenied` on SSE-KMS object** → missing `kms:Decrypt` for the role, or key in another account not shared.
- **`KMSInvalidStateException` / "key is disabled/pending deletion"** → key state; enable or cancel deletion.
- **`NotFoundException`** → wrong Region, deleted key, wrong alias.
- **`InvalidCiphertextException`** → wrong key, corrupted ciphertext, wrong encryption context, ciphertext from another Region (single-Region key).
- **`ThrottlingException`** → shared request quota → reduce calls (Bucket Keys, caching), request increase.
- **`DisabledException`** → key disabled.
- **Cross-account decrypt fails** → no key policy statement for the other account or no IAM allow on their side.
- **CloudTrail/Config/logs delivery fails** → service principal missing from key policy.
- **EBS/RDS snapshot sharing fails** → snapshot encrypted with AWS managed key (not shareable); re-encrypt with a CMK.
- **Glue/Athena job cannot read encrypted data** → job role lacks `kms:Decrypt`, or Lake Formation location role lacks key access.
- **Key lockout** (nobody can manage the key) → key policy removed all admins and the root statement; contact AWS Support.
- **Imported key stopped working** → material expired or deleted; re-import the same material.
- **Custom key store key `Unavailable`** → disconnected CloudHSM/XKS proxy; reconnect.

## H. Limits and numbers
| Item | Value |
|---|---|
| Customer managed keys per account/Region | **100,000** (adjustable) |
| Aliases per key | **50** (adjustable) |
| Grants per key | **50,000** (adjustable) |
| Custom key stores per account/Region | **10** (adjustable) |
| On-demand rotations per key | **25** (hard) |
| Key deletion waiting period | **7–30 days** (default 30) |
| Direct `Encrypt` payload | **4,096 bytes** |
| Key policy size | **32 KB** |
| Automatic rotation default | **365 days** (configurable) |
| AWS managed key rotation | **yearly** (fixed) |
| Free requests | **20,000 / month** |
| Key spec / usage | fixed at creation |
| Data key reuse (SQS) / Step Functions | 60 s–24 h / 60–900 s **(verify)** |
- Resources you use but do not own (AWS owned keys, AWS managed keys) do **not** count against your key quota.

## I. Best practices
- Use **separate keys** per data classification/domain and environment; avoid one global key.
- Keep **admins and users separate**; use **conditions** (`ViaService`, `CallerAccount`, encryption context).
- Enable **automatic rotation** on CMKs where supported.
- Use **aliases** in apps; **don't hard-code key IDs**.
- **Never delete** a key before disabling and watching CloudTrail for failed uses.
- Enforce encryption with **bucket policies, SCPs, Config rules**.
- **Monitor** key policy changes, disables, deletions.
- Prefer **service integrations** and the **AWS Encryption SDK** over custom crypto.
- Plan **DR**: multi-Region keys or per-Region keys for replicas.
- Protect **key policies** with guardrails (SCP denying `kms:PutKeyPolicy`/`ScheduleKeyDeletion` except for security admins).

## J. Exam skills mapping
- **4.3.1 Masking and anonymization**: masking options.
- **4.3.2 Encryption keys (KMS)**: service integrations.
- **4.3.3 Encryption across account boundaries**: cross-account and cross-Region encryption.
- **2.1.1 Storage services for cost and performance**: encryption cost and performance (Bucket Keys).

## K. Scenarios: "If X → Y, because Z"
- **If** **Amazon Athena** cannot read **S3 server-side encryption with KMS (SSE-KMS)** data in a shared bucket, **then** give the **query role** **`kms:Decrypt`** on the **customer managed key (CMK)**, and if the key is in another account, allow that account in the **key policy**. **This works because** reading SSE-KMS objects needs **both** `s3:GetObject` **and** `kms:Decrypt`; S3 permission alone is not enough. The AWS managed key `aws/s3` **cannot be shared** across accounts.
- **If** an S3 bucket serves **10,000 requests per second** with **S3 server-side encryption with KMS (SSE-KMS)** and costs or throttling are high, **then** enable **S3 Bucket Keys**. **This works because** S3 gets a bucket-level key from AWS Key Management Service (KMS) and derives per-object data keys from it, so there are **far fewer** KMS calls and lower cost.
- **If** you must share an encrypted **Amazon RDS** or **Amazon EBS** snapshot with another account, **then** re-encrypt it (by snapshot copy) with a **customer managed key (CMK)** and share that key with the other account. **This works because** **AWS managed keys** such as `aws/rds` **cannot be shared** across accounts, so a snapshot encrypted with one cannot be used by the other account.
- **If** **Amazon Redshift** snapshots must be copied to **another Region**, **then** create a **snapshot copy grant** that uses a KMS key in the **destination Region**. **This works because** AWS Key Management Service (KMS) keys are **Regional**: a key in the source Region cannot encrypt data in the destination, so Redshift needs permission (the grant) to use a destination-Region key.
- **If** an **AWS Glue** job must write encrypted output and encrypted logs, **then** attach a **Glue security configuration** that sets **S3 encryption (SSE-KMS)**, **CloudWatch Logs encryption** and **job bookmark encryption**. **This works because** the security configuration controls encryption for **each destination** separately. The Glue **job role** also needs permissions on the KMS key.
- **If** **Amazon Kinesis Data Streams** producers slow down under heavy volume with server-side encryption (SSE), **then** check for **KMS throttling**, reduce per-record KMS calls, or request a **quota increase**. **This works because** every encrypt call counts against the AWS Key Management Service (KMS) request quota, which is **shared per account per Region**, so KMS throttling can slow throughput.
- **If** you must cut off access to a dataset **immediately**, **then** **disable** the **customer managed key (CMK)** for that data domain. **This works because** a disabled key cannot be used: all **reads fail** (no `Decrypt`) and **writes** cannot generate data keys. Disabling is **reversible**, unlike deletion. This is why a common pattern is **one CMK per data domain** (raw, curated, sensitive).
- **If** cross-Region disaster recovery (DR) needs the **same ciphertext** readable in two Regions, **then** use **multi-Region keys (MRKs)**: a primary key and a replica key in the other Region. **This works because** they share the **same key material**, so each replica can decrypt the other's ciphertext without re-encrypting or making cross-Region calls.
- **If** auditors want to see **who read** sensitive S3 objects, **then** use **AWS CloudTrail** **KMS `Decrypt` events**, which include the **encryption context** (for example `aws:s3:arn`), together with **S3 data events**. **This works because** both appear in CloudTrail logs: the KMS event shows which resource used the key and who called it, and the S3 data event shows the object read.
- **If** a **customer managed key (CMK)** must never be deleted by accident, **then** add a **Service Control Policy (SCP)** or **key policy deny** on `kms:ScheduleKeyDeletion` for everyone except a **break-glass** role, plus an **AWS Config rule** (`kms-cmk-not-scheduled-for-deletion`) to alert on pending deletion. **This works because** deleting a key is **irreversible** and makes all its data unrecoverable, so you block the action and also detect it early.
- **If** sensitive columns must be **hidden from analysts** but also **encrypted at rest**, **then** use **encryption with AWS Key Management Service (KMS)** plus **masking**, such as **Amazon Redshift dynamic data masking (DDM)** or **AWS Lake Formation data filters**. **This works because** encryption protects against unauthorized reading but **does not stop authorized users** from seeing plaintext; masking hides values from them.
- **If** log delivery to an encrypted S3 bucket fails after you switch to a **customer managed key (CMK)**, **then** add the service principal (`cloudtrail.amazonaws.com` or `delivery.logs.amazonaws.com`) to the **key policy**, with an **`aws:SourceArn`** condition. **This works because** the service itself must call **`GenerateDataKey`** on the key to write encrypted logs, so the key policy must allow it.

Verified from AWS docs on 2026-11-03 (KMS quotas, rotation, pricing, key policies; Step Functions encryption page; MWAA S3 bucket page).
Unconfirmed (verify): S3 Express One Zone KMS options; SQS data-key reuse bounds; Redshift in-place encryption flow for each deployment type; Glue Data Catalog encryption details; EMR LUKS vs EBS encryption options; Bucket Keys percentage; AWS Config rule names; DAX/OpenSearch encryption change rules.

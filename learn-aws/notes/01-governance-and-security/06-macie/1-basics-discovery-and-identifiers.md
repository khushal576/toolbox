# Amazon Macie – 1. Basics, discovery, data identifiers and findings

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **Amazon Macie** is a data-security service that **discovers sensitive data in Amazon S3** using machine learning and pattern matching, and **monitors S3 bucket security** (public access, sharing, encryption).
- **S3 only** (general purpose buckets). It does not scan RDS, DynamoDB, Redshift or EBS directly. To scan other stores, export or land the data in S3.
- It produces **findings** (policy findings and sensitive data findings), statistics and an **inventory** of buckets.
- Regional service; enable it per Region and per account (or via Organizations).
- Pick it when:
  - You must **find PII/PHI/financial/credential data** in a data lake and prove where it is.
  - You need **continuous detection of public or shared buckets** and unencrypted buckets.
  - You want an **audit trail** for privacy compliance (GDPR, HIPAA, PCI).
- Avoid / combine when: you need to **mask or redact** data (Macie finds but does not change data → use Glue PII transform, Lake Formation, Redshift masking); you need to scan non-S3 sources.
- DEA-C01: **4.5 data privacy and governance** (identify PII, classify data, Macie for sensitive data discovery), **4.3** masking and encryption context.

## B. How it works
- **Bucket inventory and monitoring**: after enabling, Macie maintains an inventory of **S3 general purpose buckets** and evaluates them for security and access control (public access, replication, encryption, shared access). It uses bucket metadata and CloudTrail-independent evaluation of policies/ACLs.
- **Automated sensitive data discovery**: continuous, **sampling-based** analysis across all buckets (or chosen ones); builds a **sensitivity score** per bucket and a data map. Enabled per account/organization. Objects are sampled, not all scanned.
- **Sensitive data discovery jobs**: **targeted** analysis you define: which buckets (or runtime bucket criteria), **sampling depth** (percent of objects), object criteria (prefix, tags, size, last modified, extension, storage class), **one-time or scheduled** (daily/weekly/monthly), identifiers to use.
- **Findings** are generated for:
  - **Policy findings** (bucket-level security): e.g. `Policy:IAMUser/S3BucketPublic`, `S3BucketEncryptionDisabled`, `S3BucketSharedExternally`, `S3BucketReplicatedExternally`, `S3BlockPublicAccessDisabled`, `S3BucketSharedWithCloudFront`.
  - **Sensitive data findings**: `SensitiveData:S3Object/Personal`, `/Financial`, `/Credentials`, `/CustomIdentifier`, `/Multiple`.
- **Findings include**: severity (Low/Medium/High), affected bucket/object, data types, counts and **locations** (line, column, page, cell, JSON path, record) but **not the raw sensitive values** (you can **reveal samples** within limits).
- **Sensitive data discovery results** (a separate, detailed record of what was analyzed, including non-sensitive and unprocessed objects) go to an **S3 repository bucket you configure** (encrypted with your KMS key). Required for jobs.
- **Retention**: findings kept **90 days** in Macie **(verify)**; store in S3/Security Hub for longer.
- Macie reads S3 objects with its **service-linked role**; for objects encrypted with a **customer managed KMS key**, the key policy must allow the Macie service-linked role / the job's access (`kms:Decrypt`, `kms:DescribeKey`).
- **Not analyzed**: objects it cannot read (access denied, unsupported format), objects in Glacier classes (Glacier Flexible/Deep Archive), client-side encrypted objects, files above size quotas **(verify storage-class list)**.

## C. Data identifiers
- **Managed data identifiers**: built-in detectors (hundreds) for **credentials** (AWS secret keys, private keys, API tokens), **financial** (credit card numbers, bank account numbers), **personal** (names, addresses, SSNs, passports, driver licenses, health insurance IDs, national IDs by country), **health** (HIPAA-related). Updated by AWS.
- **Custom data identifiers**: your own **regex** (up to a size limit) with optional **keywords** (proximity within a number of characters), **ignore words**, and **maximum match distance**; severity thresholds. Up to **10,000 per account**, **30 per job**.
- **Allow lists**: ignore specific **text** (≤100,000 entries / 35 MB) or **regex** (e.g., public company phone numbers, test data). Max **10 allow lists** per account (5 text + 5 regex).
- **Managed identifier selection** (jobs): all, none, custom set (include/exclude specific IDs); the default adds new managed identifiers as AWS releases them.
- **Detection of full names and mailing addresses** capped at **1,000 per file** (after that Macie stops counting).
- **Sensitivity score** (automated discovery): 1–100 per bucket; **labels**: Not sensitive, Sensitive, Classification in progress, Classification error, Sampling in progress **(verify)**.
- **Excluding buckets** from automated discovery: up to **1,000**.

## D. What file types are analyzed
- Text-based: **plain text, CSV, TSV, JSON/JSONL**, logs.
- Documents: **PDF, DOC/DOCX, XLS/XLSX**, email (**EML**).
- Big-data formats: **Parquet, Avro**.
- Archives: **ZIP, GZ/GZIP, TAR** (extracted; nested depth up to 10 levels; extracted files up to 1,000,000; 10 GB uncompressed overall; 3 GB per extracted file).
- **Unsupported**: images (no OCR), audio/video, encrypted client-side objects, password-protected files, unsupported binaries. **Macie does not OCR images/scans** (use Textract/Comprehend).
- Compressed text works; Parquet is columnar-aware.
- **File size limits per file**: PDF 1,024 MB; Avro/Parquet 8 GB; EML 20 GB; GZ 8 GB; XLS/XLSX 512 MB; DOC/DOCX 512 MB; text 20 GB; TAR 20 GB; ZIP 8 GB. Larger files are **skipped entirely**.
- **Time to analyze one file**: up to 10 hours.
- **JSON nesting**: 256 levels.

## E. Multi-account and organization
- **Administrator account** (delegated admin from Organizations, or invitation-based) manages **members** (up to **10,000** via Organizations, **1,000** via invitation).
- Admin can run jobs and see findings/buckets across member accounts; **members can't turn off** Macie if the admin enabled it via Organizations.
- Macie supports **auto-enable** for new organization accounts.
- **Cross-Region**: Macie is per Region; use **Security Hub aggregation** or EventBridge to centralize findings.
- **Bucket monitoring quota**: **10,000 buckets per account**; beyond that Macie fully monitors only the 10,000 most recently created/changed.

## F. Integration
- **EventBridge**: findings published as events (near real time) → Lambda, SNS, SQS, Step Functions for auto-remediation.
- **Security Hub (CSPM)**: Macie findings flow in using **ASFF/OCSF**; aggregate across accounts/Regions.
- **S3**: findings discovery results bucket; object tags for classification via automation (Lambda tags objects `sensitivity=high`).
- **Lake Formation / Glue**: use Macie results to apply **LF-Tags** or restrict access (custom automation).
- **Athena**: query **discovery results** (JSON Lines in S3) with a Glue table for reporting.
- **GuardDuty** (S3 protection) is complementary: it detects **suspicious access**; Macie detects **sensitive content** and exposure.
- **AWS Config / Access Analyzer**: other bucket posture checks.
- **Detective**: investigate findings **(verify)**.
- **Automated remediation**: EventBridge → Lambda to enable Block Public Access, apply encryption, move/quarantine object, notify owner.

## G. Exam skills mapping
- **4.5.2 PII identification (Macie with Lake Formation)**: PII identification.
- **4.3.1 Masking and anonymization**: masking companions.

## H. Scenarios: "If X → Y, because Z"
- If you must locate PII in a data lake before sharing it → **Macie sensitive data discovery job (or automated discovery) on the lake buckets**, because it identifies PII types and locations.
- If you want ongoing visibility without scanning everything → **automated sensitive data discovery**, because it samples continuously and scores buckets.
- If a data owner needs a deep scan of one prefix → **targeted job with prefix criteria and 100% sampling depth**, because jobs can be tuned.
- If your company has internal customer IDs to detect → **custom data identifier (regex + keywords)**, because managed identifiers don't know your formats.
- If scanning flags well-known public phone numbers → **allow list**, because it suppresses expected matches.
- If you must hide PII from analysts → **Macie finds, then mask via Glue Detect PII / Lake Formation column & cell filters / Redshift dynamic data masking**, because Macie does not modify data.
- If objects are SSE-KMS with a customer key and Macie can't read them → **allow Macie's service-linked role in the key policy**, because decrypt is required to analyze.
- If a bucket becomes public → **Macie policy finding → EventBridge → Lambda enables Block Public Access**, because it gives near-real-time remediation.
- If scans must cover several accounts → **delegated administrator via Organizations**, because the admin runs jobs and sees member findings.
- If you need to scan a database → **export/replicate it to S3 (DMS, Glue, UNLOAD) and scan the export**, because Macie only reads S3.
- If PDFs of scanned images are suspected to contain PII → **use Textract + Comprehend PII**, because Macie doesn't OCR.

Verified from AWS docs on 2026-11-03 (What is Macie, Macie quotas, Macie pricing).
Unconfirmed (verify): findings retention period (90 days); sensitivity score labels; skipped storage classes; managed identifier count; policy finding names; Detective integration; custom identifier regex length limit.

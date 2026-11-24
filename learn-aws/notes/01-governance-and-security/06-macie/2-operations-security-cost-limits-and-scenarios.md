# Amazon Macie – 2. Operations, security, cost, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Setting up and operating
- **Enable Macie** in each Region (console/API/Organizations). First enable starts a **30-day free trial** per account and Region.
- **Organizations**: enable trusted access, designate a **delegated administrator**, turn on **auto-enable** for new accounts.
- **Configure the results repository**: S3 bucket + **KMS key** for sensitive data discovery results (required before running jobs; Macie stores results as **.jsonl.gz**).
- **Service-linked role** `AWSServiceRoleForAmazonMacie` is created automatically; it lets Macie read bucket metadata and objects.
- **Jobs**: choose accounts/buckets (or runtime criteria such as "all buckets that are public/unencrypted/not scanned recently"), **sampling depth**, **object criteria** (include/exclude prefixes, tags, last modified, size, extensions), managed + custom identifiers, allow lists, **schedule** (one time, daily, weekly, monthly), **job name/tags**.
- **Runtime bucket criteria** keep a recurring job scoped automatically as buckets change.
- **Job status**: Active (Running/Idle), Paused, Complete, Cancelled, Paused by quota. A job pauses when the **monthly analysis quota (5 TB default)** is hit; it can resume after increase or next month.
- **Estimate cost before running** using Macie's **cost estimate** on job creation.
- **Findings management**: filter, group, **suppress** (suppression rules, max **1,000 filter/suppression rules**), archive; findings exported by API; finding events always published to EventBridge even when suppressed (suppressed findings are not sent to Security Hub) **(verify)**.
- **Reveal sensitive data samples**: retrieve limited samples of detected values (needs configuration with an S3 access method; **100 requests per day** per object; file size limits per type e.g. CSV 255 MB, JSON 25 MB, Parquet 100 MB, ZIP 355 MB).
- **Reveal access control**: separate IAM permissions (`macie2:GetSensitiveDataOccurrences`) and the requester's own access to the object and KMS key (or Macie's role) **(verify)**.
- **CloudTrail**: Macie API calls are logged; management events.
- **Disable/suspend**: disabling Macie deletes inventory/findings; **suspend** keeps data but stops processing; Macie data is not retained after disabling.

## B. Security and access control
- **IAM**: `macie2:*` actions; managed policies `AmazonMacieFullAccess`, `AmazonMacieReadOnlyAccess`, `AmazonMacieServiceRolePolicy` (for the SLR).
- **Least privilege**: separate roles for **running jobs**, **viewing findings**, **revealing samples** (high risk).
- **S3 bucket policies** must not deny Macie's SLR; if you use `Deny` statements, add exemptions for the role.
- **KMS**: customer managed key policy must allow Macie's SLR (`kms:Decrypt`, `kms:DescribeKey`) to read encrypted objects; the **results bucket key** must allow Macie to `GenerateDataKey`.
- **Cross-account**: member buckets are analyzed by the admin's jobs; member-account bucket policies and KMS must allow the Macie SLR **in the member account** (jobs run via the member's SLR).
- **Data stays in the Region**: Macie reads the bucket data and writes results in the Region configured; sample reveals are not stored by Macie.
- **Privacy**: Macie reports locations and counts; raw sensitive values are not stored in findings (only samples on request).
- **VPC endpoints**: Macie supports interface VPC endpoints for API calls (`com.amazonaws.<region>.macie2`) **(verify)**.
- **Encryption of Macie data**: findings and metadata encrypted at rest with AWS-managed keys.

## C. Cost
- **Pricing dimensions (US East example)**:
  - **Bucket inventory and monitoring**: about **$0.10 per S3 bucket per month** (prorated daily), up to 10,000 buckets.
  - **Automated sensitive data discovery**: about **$1 per GB analyzed** (first 1 GB free) plus **$0.01 per 100,000 S3 objects monitored** **(verify unit)**.
  - **Targeted discovery jobs**: about **$1 per GB** of supported data inspected, plus standard S3 `GET`/`LIST` costs.
  - **Free trial**: 30 days; inspects up to 150 GB of automated discovery per account; **does not cover targeted jobs**.
- **No tiering** for volume; compressed archives are priced on **uncompressed bytes** inspected **(verify)**.
- **Other costs**: S3 requests, KMS decrypt requests (customer managed keys), data transfer within Region, CloudWatch/EventBridge, Security Hub ingest, results bucket storage.
- **Cost levers**:
  - Scope jobs: **sample 10–25%** for first pass, scan **only buckets that matter**.
  - **Exclude** log, backup, and public-data buckets from automated discovery.
  - Use **object criteria** (prefix/extension/size/last modified) to skip stale or irrelevant objects.
  - Run **incremental jobs** (last modified criteria) rather than full scans every time.
  - Prefer **Parquet/compressed** formats carefully: compression expands during analysis, cost is per GB inspected.
  - Don't enable Macie in unused Regions.
- **Cost estimate APIs** and the console show projected monthly cost.

## D. Monitoring and troubleshooting
- **No findings from a job** → data truly clean, objects unsupported/too big/unreadable, sampling depth too low, wrong criteria, allow list too broad.
- **Job `Paused by quota`** → monthly 5 TB analysis quota reached; request increase (up to 1 PB via Service Quotas).
- **Access denied reading objects** → bucket policy deny, missing KMS permission, object ACLs, Block Public Access not relevant; check `Unprocessed` details in discovery results.
- **Results bucket errors** → results repository not configured or KMS key policy blocks Macie.
- **Objects skipped** → file larger than limit, unsupported format, encrypted with client-side key, archive depth/size limits.
- **Duplicate/noisy findings** → refine managed identifiers (exclude low-value types), use allow lists and suppression rules.
- **Findings not in Security Hub** → integration not enabled, Region differences, suppressed findings, or Security Hub not enabled.
- **Member account not scanned** → Macie not enabled in member account/Region, SLR blocked by SCP, or bucket count over 10,000.
- **Automated discovery sensitivity score stays "Classification in progress"** → big buckets take time; check exclusions and quota.
- **Reveal fails** → reveal not configured, object too large, daily request limit (100/day/object), insufficient permissions.
- **Cost jump** → a job scanning large buckets at 100% depth; check the estimated cost and pause the job.
- **Monitoring**: EventBridge on `Macie Finding` events; CloudWatch metrics for Macie usage (e.g., bytes classified) **(verify)**; usage statistics in console; Cost Explorer by usage type.

## E. Limits cheat sheet
| Item | Value |
|---|---|
| Free trial | **30 days** (150 GB automated discovery) |
| S3 buckets per account monitored | **10,000** |
| Monthly job analysis (default) | **5 TB** (up to 1 PB via Service Quotas) |
| Custom data identifiers | **10,000** per account; **30** per job |
| Allow lists | **10** (5 text + 5 regex); text list ≤ **100,000** entries / **35 MB** |
| Buckets per job | **1,000** (not for runtime criteria) |
| Buckets excluded from automated discovery | **1,000** |
| Filter/suppression rules | **1,000** |
| Findings per job run (console/API) | **100,000 + 5% of remaining** |
| Detection locations per finding | **15**; per result type **1,000** |
| Reveal requests | **100 per object per day** |
| `CreateClassificationJob` rate | **0.1/s** |
| Time to analyze a file | **10 hours** |
| Archive depth / extracted files / uncompressed | **10 / 1,000,000 / 10 GB** |
| Members via Organizations / invitation | **10,000 / 1,000** |
| JSON nesting | **256** levels |
| Names/addresses detected per file | **1,000** each |

## F. Design patterns for data teams
- **Data lake classification pipeline**: Macie job on `raw/` → EventBridge → Lambda tags objects/bucket (`sensitivity`) and writes to a classification table → Lake Formation LF-Tag grants or restricted prefixes → Glue transformation masks PII into `curated/`.
- **Pre-share gate**: before sharing data externally (Data Exchange, cross-account), run a one-time job; block share if `Credentials` or high-severity `Personal` found.
- **Ingestion quarantine**: land files in a quarantine bucket; scheduled Macie job; clean files move to the lake; flagged ones go to review.
- **Reporting**: Glue table over discovery results → Athena/QuickSight dashboard of PII by bucket/owner.
- **Cleanup**: Macie to find stale sensitive data → S3 lifecycle/Object delete workflow (with approvals).
- **Combine tools**: Macie (find) + Comprehend (PII in text) + Glue Data Quality/PII detection (transform) + Lake Formation (access) + KMS (encrypt) + CloudTrail (audit).

## G. Exam skills mapping
- **4.5.2 PII identification (Macie with Lake Formation)**: discovery jobs, findings, cost.
- **4.3.1 Masking and anonymization**: masking after discovery.

## H. Scenarios: "If X → Y, because Z"
- If monthly compliance requires a PII inventory by bucket → **scheduled Macie job (monthly) + discovery results in S3 queried by Athena**, because results contain per-object detections.
- If Macie costs too much → **sample, exclude, scope by prefix and last modified**, because cost is per GB inspected.
- If an auditor asks "which buckets are public or unencrypted" → **Macie bucket inventory/dashboard and policy findings**, because Macie evaluates bucket security posture continuously.
- If new accounts must be covered automatically → **Organizations delegated admin + auto-enable**, because it enables Macie in new accounts.
- If findings should open tickets → **EventBridge rule → SNS/Lambda/Jira integration**, because Macie publishes findings as events.
- If you need to prevent sensitive data from entering the curated zone → **scan the landing zone first and only promote clean objects (Step Functions + Macie job + EventBridge)**, because detection must happen before promotion.
- If Macie cannot analyze a Glacier-class dataset → **restore or copy to a readable class first**, because archived objects can't be read **(verify)**.
- If an SCP denies S3 access to non-listed roles → **exempt Macie's service-linked role**, because it needs to read objects.
- If Macie detects a false-positive pattern repeatedly → **allow list or suppression rule**, because it reduces noise without disabling detectors.
- If you must keep findings beyond Macie's retention → **send to Security Hub / S3 via EventBridge and Firehose**, because Macie keeps findings for a limited time.

Verified from AWS docs on 2026-11-03 (What is Macie, Macie quotas, Macie pricing).
Unconfirmed (verify): suppression behavior toward Security Hub; reveal-samples permission names; VPC endpoint availability; CloudWatch metrics names; automated discovery price unit; archive pricing basis; exact job status names; Glacier handling.

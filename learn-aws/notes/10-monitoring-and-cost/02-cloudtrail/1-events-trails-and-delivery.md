# AWS CloudTrail – 1. Events, event history, trails and delivery

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS CloudTrail** records **API calls and account activity** (console, CLI, SDK, other services) as **events**. It answers **"who did what, when, from where, to which resource"**.
- It is the core **audit** service. It does not show resource configuration history (that is **Config**) and does not detect threats (that is **GuardDuty**).
- Enabled automatically for every account: **Event history** shows the last **90 days** of **management events** in the current Region, free.
- To keep events longer or capture more types, create a **trail** (to S3/CloudWatch Logs) or an **event data store** (CloudTrail Lake).
- Pick it when: audit, security investigation, compliance (who deleted the bucket? who assumed this role?), operational troubleshooting, data-access auditing (S3 object-level, Lambda invoke).
- DEA-C01: **4.4.1 CloudTrail for API calls (audit)**, **4.4.3 CloudTrail Lake**, **4.4.4 analyze logs (Athena, Logs Insights)**, **4.5 governance**.

## B. Event types
- **Management events** (control plane): create/delete/modify resources and IAM actions; also sign-in events (`ConsoleLogin`), `AssumeRole`, STS calls, KMS control-plane calls. **Logged by default**.
  - **Read** (Describe/List/Get) vs **Write** (Create/Update/Delete/Put) events; you choose which to log in a trail.
- **Data events** (data plane, high volume): **S3 object-level** (`GetObject`, `PutObject`, `DeleteObject`), **Lambda `Invoke`**, **DynamoDB item-level**, Glue tables, KMS, Kinesis streams, S3 Access Points, Lake Formation, Bedrock, and many more resource types. **Off by default; costs extra**.
- **Network activity events**: VPC endpoint API activity (who used the endpoint, denied calls) - useful for **data perimeter** auditing.
- **Insights events**: unusual **API call rate** or **error rate** compared to a baseline (**ApiCallRateInsight**, **ApiErrorRateInsight**). Off by default; billed per events analyzed.
- **Aggregated events** (newer) summarize some high-volume data events **(verify)**.
- **Event record fields**: `eventTime`, `eventSource`, `eventName`, `awsRegion`, `sourceIPAddress`, `userAgent`, `userIdentity` (type, principalId, arn, accountId, `sessionContext` with `sessionIssuer`, `mfaAuthenticated`, `sourceIdentity`), `requestParameters`, `responseElements`, `errorCode`, `errorMessage`, `requestID`, `eventID`, `readOnly`, `recipientAccountId`, `resources`, `tlsDetails`, `vpcEndpointId`.
- **userIdentity types**: `IAMUser`, `AssumedRole`, `Root`, `FederatedUser`, `AWSService`, `AWSAccount`, `SAMLUser`, `WebIdentityUser`.
- **Errors**: `errorCode` like `AccessDenied`, `UnauthorizedOperation`, `Client.UnauthorizedOperation` shows denied attempts (used to tune SCPs).
- **Events are not an ordered stack trace**; do not rely on ordering.
- **Event size**: up to **256 KB** (v1.05+); CloudTrail does not send events > 256 KB to CloudWatch Logs or EventBridge.
- **Global service events** (IAM, STS, CloudFront, Route 53) are logged in `us-east-1` for the global endpoint, and in the Region of the endpoint used for regional STS endpoints. A **multi-Region trail** captures them.

## C. Event history (the free 90 days)
- Always on; **management events only**; **90 days**; per Region.
- Console, CLI/API `LookupEvents` (**2 TPS** quota), filter by event name, user, resource type, resource name, event source, access key, read-only.
- Includes **create/modify/delete** and read events; searchable on a limited attribute set.
- Good for quick investigations; **not** a long-term audit store - create a trail or Lake.
- Cannot be exported except via `LookupEvents` or CSV download (up to 200,000 events) **(verify)**.

## D. Trails
- A **trail** delivers events as **log files** to an **S3 bucket**, optionally to **CloudWatch Logs** and **EventBridge**, with SNS notifications.
- **Trail types**:
  - **Single-Region**: events from one Region.
  - **Multi-Region** (recommended): one trail records all Regions, including new Regions.
  - **Organization trail**: created in the management (or delegated administrator) account; logs **all member accounts**; members **cannot modify or delete** it.
- **Quota**: **5 trails per Region** (not adjustable). The **first copy of management events is free**; additional copies cost.
- **Delivery**: log files arrive in S3 typically **within about 5 minutes** of the API call (usually faster); `.json.gz` files, up to **50 MB before compression**.
- **S3 key format**: `AWSLogs/<orgId>/<accountId>/CloudTrail/<region>/<yyyy>/<mm>/<dd>/<file>.json.gz` (organization trails add the org ID prefix).
- **CloudWatch Logs integration**: send events to a log group for metric filters/alarms/Insights; the **delivery role** needs `logs:CreateLogStream/PutLogEvents`; delivery charge ~ $0.25/GB plus ingestion.
- **SNS notifications** on new log file delivery (optional).
- **EventBridge**: management events can be matched by EventBridge **API call** rules (`detail-type: AWS API Call via CloudTrail`) without a trail for default bus management events.
- **Selectors**:
  - **Basic event selectors** (up to 5 per trail): read/write type, include/exclude management events, data events for S3 / Lambda / DynamoDB.
  - **Advanced event selectors**: fine-grained fields (`eventCategory`, `resources.type`, `resources.ARN`, `eventName`, `readOnly`, `userIdentity.arn`, `eventSource`) with operators (equals, starts with, ends with, not…); **500 conditions** total across selectors. Required for most data event types and for event data stores.
  - **Data resources** per selector (basic): up to **250** across all selectors.
- **Log all data events** for all S3 buckets/Lambda functions, or limit by ARN prefix (`arn:aws:s3:::my-lake/raw/`).
- **Exclusions**: exclude noisy sources (KMS, Data API) from management events to cut cost **(verify controls)**.
- **Stop/start logging** with `StopLogging/StartLogging`; deleting a trail does not delete logs in S3.
- **Trail tags**, **KMS key**, **log file validation** are trail settings.

## E. Log file integrity validation
- When enabled, CloudTrail creates **digest files hourly** containing **SHA-256 hashes** of the log files delivered that hour, **digitally signed (RSA)**.
- Verify with `aws cloudtrail validate-logs` (checks tampering, deletion, modification) without trusting the S3 bucket.
- Digest files are stored in the same bucket under `CloudTrail-Digest/`.
- Use with S3 **Object Lock / versioning / MFA delete** for strong immutability.
- Validation detects **modified or deleted** log files and missing digests; it can't recover them.

## F. Protecting and organizing logs
- **S3 bucket policy**: allow `cloudtrail.amazonaws.com` `s3:GetBucketAcl` and `s3:PutObject` (with `bucket-owner-full-control`), restricted by `aws:SourceArn` (trail ARN) and `aws:SourceAccount` (confused deputy).
- **Encrypt with SSE-KMS**: key policy allows `cloudtrail.amazonaws.com` `kms:GenerateDataKey*` and `kms:DescribeKey`, with `kms:EncryptionContext:aws:cloudtrail:arn`; readers need `kms:Decrypt`.
- **Central log archive account**: organization trail writes to a bucket in a dedicated account; lock down delete (SCP, Object Lock, replication to another Region).
- **Lifecycle**: S3 lifecycle to Glacier after N days; expire after retention (commonly 1–7 years).
- **Cross-Region replication** of the log bucket for DR.
- **Alarms**: detect `StopLogging`, `DeleteTrail`, `UpdateTrail`, `PutEventSelectors`, `DisableAlarmActions`.
- **SCP**: deny `cloudtrail:StopLogging`, `DeleteTrail`, `UpdateTrail`, `PutEventSelectors` except for security admins.
- **Don't log secrets**: CloudTrail redacts many sensitive request parameters (for example passwords) but check service behaviour.

## G. Analyzing trail logs
- **Athena**: create a table over the S3 prefix (CloudTrail-specific DDL with partition projection by account/region/date); query for IAM changes, denied calls, S3 data events.
- **CloudWatch Logs Insights** and **metric filters** (CIS controls: root usage, unauthorized API calls, console login failures, IAM policy changes, S3 policy changes, security group changes).
- **OpenSearch** or **Security Lake** (OCSF) for SIEM-style analytics; **Glue** to convert to Parquet for cheaper scans.
- **EventBridge** for real-time response (e.g., new access key created).
- **Detective** and **GuardDuty** consume CloudTrail independently (GuardDuty needs no trail from you).
- **Typical data-platform queries**: who read objects from a sensitive prefix, who changed a bucket policy, who ran `GetSecretValue`, who decrypted with a KMS key, who assumed the Glue role, who changed Lake Formation permissions.

## H. Cost (trails)
- **Management events**: first copy per Region **free** (event history free); each **additional copy** about **$2.00 per 100,000 events**.
- **Data events**: about **$0.10 per 100,000 events**.
- **Network activity events**: about **$0.10 per 100,000 events**.
- **Insights**: about **$0.35 per 100,000 management events analyzed** (per insight type); data-event Insights about $0.03 per 100,000.
- **CloudWatch Logs delivery**: about **$0.25/GB** plus CloudWatch ingestion/storage.
- **S3 storage and requests**, KMS requests, Athena scans are extra.
- **Cost levers**: log data events only for sensitive buckets/prefixes; exclude noisy event sources; keep one organization trail instead of per-account trails (extra copies cost); compress/convert logs to Parquet; lifecycle old logs.

## I. Limits (summary)
| Item | Value |
|---|---|
| Event history | **90 days**, management events |
| Trails per Region | **5** (hard) |
| Basic event selectors per trail | **5** |
| Advanced selector conditions | **500** |
| Data resources across selectors | **250** |
| Event size | **256 KB** |
| S3 file size | **50 MB** before compression |
| `LookupEvents` | **2 TPS** |
| Digest files | hourly |
| Delivery latency | about 5 min typical |

## J. Exam skills mapping
- **4.4.1 CloudTrail for API calls (audit)**: CloudTrail for API calls.
- **3.3.5 CloudTrail for API calls**: audit trails.
- **3.3.1 Extract logs for audits**: extract logs for audits.

## K. Scenarios: "If X → Y, because Z"
- **If** you must find out who deleted a bucket, **then** look for the **`DeleteBucket`** management event in **AWS CloudTrail**, the service that records API calls as events. Check **Event history** (free, last **90 days**) or your **trail**. **This works because** management events are logged by default, and each event record holds the caller (`userIdentity`), the time and the **source IP address** (`sourceIPAddress`).
- **If** you need audit data for **7 years**, **then** create a **trail** that delivers events to an **Amazon Simple Storage Service (S3)** bucket, with an **S3 Lifecycle** rule that moves old logs to Glacier and expires them after the retention period. Or use a **CloudTrail Lake** event data store with **seven-year retention**. **This works because** **Event history** keeps only **90 days** of management events, so it is not a long-term audit store.
- **If** you must prove log files were not altered, **then** enable **log file integrity validation** and **S3 Object Lock**. With validation on, CloudTrail creates **digest files every hour** with **SHA-256 hashes** of that hour's log files, **digitally signed (RSA)**; `aws cloudtrail validate-logs` then checks for changed or deleted files. **This works because** the signed digests detect any change, and Object Lock makes the log objects immutable. Validation only detects changes; it cannot recover lost files.
- **If** you must audit reads of sensitive S3 objects, **then** turn on **S3 data events** (object-level calls such as `GetObject`) limited to that bucket or prefix, for example `arn:aws:s3:::my-lake/raw/`. **This works because** data events are **off by default** and cost extra (about **$0.10 per 100,000 events**), so scoping them logs what matters at lower cost.
- **If** you operate **100 accounts**, **then** create one **organization trail** in the management (or delegated administrator) account that writes to a bucket in a central **log archive account**. **This works because** an organization trail logs **all member accounts**, and members **cannot modify or delete** it. Lock down deletes in the archive bucket too (Service Control Policy (SCP), Object Lock).
- **If** you want near-real-time alerts on dangerous API calls, **then** use an **Amazon EventBridge** rule matching `AWS API Call via CloudTrail`, or send the trail to **Amazon CloudWatch Logs** and add a **metric filter** with an alarm. **This works because** both react to CloudTrail events after delivery. Events larger than **256 KB** are not sent to CloudWatch Logs or EventBridge.
- **If** an unusual spike in API calls appears, **then** enable **CloudTrail Insights**, which flags unusual **API call rate** (ApiCallRateInsight) or **error rate** (ApiErrorRateInsight). **This works because** it compares activity to a **baseline** (built over the previous **7 days** **(verify)**) and creates an Insights event when activity deviates. It is off by default and billed per events analyzed (about **$0.35 per 100,000** management events).
- **If** you need to see who used a VPC endpoint, **then** log **network activity events**. **This works because** they record the API calls made through the endpoint, including calls **denied** by the endpoint policy, which helps **data perimeter** auditing.
- **If** trail costs rise, **then** log data events only for sensitive buckets or prefixes, keep **one organization trail** instead of extra trails that copy management events, and exclude noisy event sources such as KMS **(verify)**. **This works because** the first copy of management events is **free**, but each **additional copy** costs about **$2.00 per 100,000 events**, and data events cost about **$0.10 per 100,000**.
- **If** someone stopped logging, **then** add a **Service Control Policy (SCP)** that denies `StopLogging`, `DeleteTrail`, `UpdateTrail` and `PutEventSelectors` to everyone except security admins, plus an **alarm** on those calls. **This works because** these are the calls used to tamper with the audit trail. Deleting a trail does not delete logs already in S3.

Verified from AWS docs on 2026-11-09 (CloudTrail concepts and quotas pages, CloudTrail pricing).
Unconfirmed (verify): aggregated events; CSV download limit; management event exclusion controls; global service event Region behaviour; CloudWatch Logs delivery cost; EventBridge default-bus behaviour; event history attribute filters.

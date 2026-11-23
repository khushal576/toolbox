# AWS CloudTrail – 3. Security, monitoring, troubleshooting, best practices and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Access control
- **IAM actions**: `cloudtrail:LookupEvents`, `CreateTrail`, `UpdateTrail`, `StartLogging`, `StopLogging`, `PutEventSelectors`, `CreateEventDataStore`, `StartQuery`, `GetQueryResults`, `PutInsightSelectors`, `DescribeTrails`, `GetTrailStatus`.
- **Managed policies**: `AWSCloudTrail_FullAccess`, `AWSCloudTrail_ReadOnlyAccess`, `AWSCloudTrailOrganizationAdminAccess` **(verify names)**.
- **Least privilege**: security team has full Lake/trail access; auditors read-only; developers `LookupEvents` limited; nobody except break-glass can stop logging.
- **Protect from tampering**: SCP deny `StopLogging`, `DeleteTrail`, `UpdateTrail`, `PutEventSelectors`, `DeleteEventDataStore`; **organization trails** cannot be changed by members.
- **S3 log bucket**: private, Block Public Access, bucket policy limited to `cloudtrail.amazonaws.com` (with `aws:SourceArn`), separate **log archive account**, **versioning + Object Lock (compliance mode)**, **MFA delete**, replicate to another Region, deny non-TLS.
- **KMS** for logs: SSE-KMS; control decrypt access separately from S3 read (two-person control).
- **Data events access** reveal sensitive object names: restrict access to logs.
- **Lake**: query access is IAM-controlled; use Lake Formation for Athena federation.
- **Multi-account**: delegated administrator for CloudTrail to manage org trails/Lake without using the management account.
- **Roots/Break glass**: alarm on any root usage, `ConsoleLogin` without MFA.

## B. Monitoring and alerting patterns
- **Real-time**: EventBridge rule on `AWS API Call via CloudTrail` for sensitive APIs (`CreateAccessKey`, `PutBucketPolicy`, `DeleteTrail`, `AuthorizeSecurityGroupIngress` to 0.0.0.0/0, `ConsoleLogin` by root, `DisableKey`, `ScheduleKeyDeletion`, Lake Formation `GrantPermissions`).
- **CloudWatch Logs metric filters + alarms** (CIS benchmark): unauthorized API calls, console login without MFA, root usage, IAM policy changes, CloudTrail config changes, console auth failures, CMK disable/deletion, S3 bucket policy changes, Config changes, security group/NACL/gateway/VPC changes.
- **Security Hub** controls: CloudTrail enabled, multi-Region, log file validation, encrypted with KMS, integrated with CloudWatch Logs, S3 bucket access logging; **Config rules**: `cloud-trail-enabled`, `cloud-trail-log-file-validation-enabled`, `cloud-trail-encryption-enabled`, `multi-region-cloudtrail-enabled`, `cloudtrail-s3-dataevents-enabled`, `cloud-trail-cloud-watch-logs-enabled`.
- **Health of the trail**: `GetTrailStatus` (`IsLogging`, `LatestDeliveryTime`, `LatestDeliveryError`, `LatestDigestDeliveryTime`); CloudWatch metrics for Lake ingestion **(verify)**.
- **Alarm if delivery stops**: use a Lambda/EventBridge schedule to check `LatestDeliveryTime` or alert on `StopLogging`.
- **Dashboards**: Lake dashboards or Athena/QuickSight over log tables.
- **Insights** for anomaly alerts (EventBridge on Insights events).

## C. Troubleshooting (symptom → cause → fix)
- **No logs in S3** → trail stopped, bucket policy missing CloudTrail principal, wrong bucket, KMS key policy blocks CloudTrail → fix policies, start logging.
- **Missing events** → event type not selected (data events), Region not covered (single-Region trail), event excluded by selector, sent only to history (older than 90 days), eventual delivery delay.
- **Cannot find event in history** → older than 90 days, not a management event, different Region, read-only filter, search attribute limits.
- **CloudWatch Logs delivery fails** → delivery role permissions, log group missing, event > 256 KB.
- **Digest validation fails** → log files modified/deleted, missing digest, validating wrong time range or Region.
- **`InsufficientS3BucketPolicyException`** → fix bucket policy for the trail.
- **`InsufficientEncryptionPolicyException`** → fix KMS key policy.
- **Organization trail not logging members** → trusted access for CloudTrail not enabled; member accounts removed; management event settings.
- **Athena query returns nothing** → partition projection/paths wrong (org ID segment), time range, region.
- **High cost** → data events on all buckets, extra management copies, Lake ingestion of noisy events.
- **Duplicate events** → multiple trails capturing the same events (charged as extra copies).
- **Lake EDS "stopped ingestion"** → permissions/KMS or manual stop.

## D. Best practices
- Turn on a **multi-Region organization trail** (all accounts) to a **central, locked-down bucket** with **KMS**, **log file validation**, **CloudWatch Logs** integration.
- Enable **data events** selectively for sensitive S3 prefixes, Lambda, DynamoDB, KMS and Lake Formation resources.
- Add **Insights** for management events.
- Use **Lake** (organization EDS) for investigations; keep an **S3 trail** for cheap long-term retention.
- Set **retention and lifecycle** to match policy (for example 1 year hot, 7 years archive).
- **Alert** on tampering and high-risk APIs; test alarms.
- Use **meaningful role session names** and **SourceIdentity** to attribute actions.
- Keep a **forensics runbook**: how to query by access key, role, IP, resource ARN.
- **Don't rely on event history** alone.
- Review CloudTrail coverage with **Config conformance packs/Security Hub**.

## E. Data-engineering audit queries (examples)
- **Who read a sensitive object?** `eventName = 'GetObject' AND resources[...] LIKE '%sensitive-prefix%'` (S3 data events).
- **Who changed Lake Formation grants?** `eventSource = 'lakeformation.amazonaws.com' AND eventName IN ('GrantPermissions','RevokePermissions','BatchGrantPermissions')`.
- **Who called `GetSecretValue`?** `eventSource = 'secretsmanager.amazonaws.com'`.
- **Who decrypted with a KMS key?** `eventSource = 'kms.amazonaws.com' AND eventName = 'Decrypt'` with `requestParameters.encryptionContext`.
- **Who assumed the Glue/EMR role?** `eventName = 'AssumeRole' AND requestParameters.roleArn LIKE '%GlueRole%'`.
- **Who ran Athena queries?** `eventSource = 'athena.amazonaws.com' AND eventName = 'StartQueryExecution'` (query string is in `requestParameters`).
- **Redshift/RDS/Glue changes**: `ModifyCluster`, `DeleteDBInstance`, `UpdateJob`, `DeleteTable`.
- **Denied calls**: `errorCode IN ('AccessDenied','UnauthorizedOperation')` grouped by `userIdentity.arn`.

## F. Related services (when to use which)
| Question | Service |
|---|---|
| Who called which API? | **CloudTrail** |
| What was the resource's configuration? | **Config** |
| Is it a threat? | **GuardDuty** |
| What happened to this resource over time and across services? | **Detective** |
| Application and system logs/metrics | **CloudWatch** |
| Network flows | **VPC Flow Logs** |
| S3 request logs (server access) | **S3 server access logs** (best effort) vs **CloudTrail S3 data events** (reliable, more detail) |
| Central security data lake (OCSF) | **Security Lake** |
- **S3 server access logs vs CloudTrail data events**: access logs are free to produce (storage costs only), best-effort, bucket-level; CloudTrail data events are reliable, include IAM identity, integrate with EventBridge, and cost per event.

## G. Exam skills mapping
- **4.4.1 CloudTrail for API calls (audit)**: audit security.
- **4.4.4 Analyze logs (Athena, Logs Insights, OpenSearch)**: audit queries.
- **3.3.2 Logging and monitoring for auditing and traceability**: alerts and monitoring.

## H. Scenarios: "If X → Y, because Z"
- If a bucket policy was changed and you need the actor → **CloudTrail `PutBucketPolicy` event**, because management events record the caller.
- If you need alarms for root logins → **EventBridge/CloudWatch metric filter on `userIdentity.type = Root`**, because CloudTrail logs root activity.
- If logs must be tamper-evident → **log file validation + Object Lock + separate account**, because digests detect changes and Object Lock prevents deletion.
- If you want to know every access to PII objects → **S3 data events limited to the PII prefixes**, because object-level reads aren't logged by default.
- If an auditor asks who decrypted data → **KMS `Decrypt` events (management event, includes encryption context)**, because KMS key use is logged.
- If a trail was deleted → **SCP to prevent it and alarm on `DeleteTrail`**, because deletion stops audit evidence.
- If events from SaaS apps must join AWS audit data → **Lake channels + queries**, because Lake ingests external audit events.
- If costs rise from S3 data events → **narrow selectors or exclude read events on low-risk buckets**, because charge is per event.
- If you need a cheap multi-year archive → **S3 trail + lifecycle to Glacier + Athena when needed**, because storage is cheap.

Verified from AWS docs on 2026-11-09 (CloudTrail concepts, quotas, pricing).
Unconfirmed (verify): managed policy names; Config rule names; Lake CloudWatch metrics; exact CIS filter list; query examples syntax for resources arrays.

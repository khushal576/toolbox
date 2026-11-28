# AWS Backup – 3. Organizations, audit, monitoring, security, cost and scenarios

Short notes. Each point is a fact you can be asked about.

## A. AWS Organizations integration
- **Cross-account management** is turned on in the **management account** (AWS Backup console → Settings) and has three parts:
  - **Backup policies**: deploy backup plans to member accounts/OUs.
  - **Cross-account monitoring**: see backup, copy and restore jobs of all accounts from one place.
  - **Cross-account backup**: allow copying recovery points between accounts in the org.
- Each feature must be **opted in** separately; trusted access for AWS Backup is enabled in Organizations **(verify wording)**.
- **Opt-in timing trap**: if a member account is opted in before the management account, cross-account monitoring can lag **up to 24 hours**.
- **Opt-in Regions**: delegated administrators can **launch policies** but **cannot use monitoring** there.
- Cross-account management is **not available** in some newer Regions (for example New Zealand, Taipei, Thailand, Mexico (Central)) per the Region table.

## B. Backup policies (Organizations policy type)
- A **backup policy** is an Organizations **management policy** (JSON) attached to the **root, OUs or accounts**.
- It describes **plans, rules (schedule, windows, lifecycle, copy actions), target vault and resource selection (by tag or ARN)**.
- **Inheritance**: policies merge down the tree using **inheritance operators** (`@@assign`, `@@append`, `@@remove`) and child-control operators; the result is the account's **effective policy** **(verify operator set)**.
- In each member account the effective policy creates an **organization-managed backup plan**, which the member **cannot edit or delete** locally.
- **Prerequisites in each member account**: the **target vault** and the **IAM role** named in the policy must **already exist** (deploy them with CloudFormation StackSets).
  - Correction vs older notes: the policy does not create the role or vault for you **(verify)**.
- **Quotas**: **30 tags per resource selection** in a cross-account backup policy; use more assignments or plans for more.
- **Policy size limit** comes from Organizations quotas (policy document max size) **(verify exact bytes)**.
- **Why use it**: guarantees every new account gets the baseline backup plan without anyone logging in to it.
- **Catch**: resources are still selected by **tags**, so tagging discipline (enforced with tag policies/SCPs) is part of backup compliance.

## C. Delegated administrator
- The management account can **register a member account as delegated administrator** for AWS Backup (service principal `backup.amazonaws.com`).
- The delegated admin can **manage backup policies** and use **cross-account monitoring** and **Audit Manager org reports** (in supported Regions).
- Why: keeps daily backup operations **out of the management account** (least privilege, smaller blast radius).
- Managing policies from a delegated admin also needs an Organizations **resource-based delegation policy** **(verify)**.
- Number of delegated admins for AWS Backup: one per org **(verify)**.

## D. Jobs dashboard and cross-account monitoring
- **Jobs dashboard**: summary of backup, copy and restore job status (completed, failed, expired) over time, per account or for the org.
- **Org view** works only in Regions that support **cross-account management and Audit Manager**.
- Cross-account monitoring shows jobs from **all member accounts** in the management or delegated admin account.
- Monitoring does not change anything; to act you still need permissions in the member account.

## E. AWS Backup Audit Manager
- **Audit Manager** checks backups against your rules using **controls** grouped into **frameworks**, and produces **reports**.
- **Needs AWS Config** recording for the AWS Backup resource types (`AWS::Backup::BackupPlan`, `BackupSelection`, `BackupVault`, `RecoveryPoint`) and the resource types being audited.
  - Trap: if Config is off, controls show no data or non-compliant.
- **Framework**: a set of controls with parameters; the console has a **default AWS Backup framework** you can deploy.
- **Quotas**: **15 frameworks per account per Region**, **50 controls per account per Region** (the same control in two frameworks counts twice), **20 report plans per account**, **1,000 frameworks per report plan**.
- **Control scopes**: resources by type, tagged resources (one key, optional value), or a single resource.
- **Only active resources** are evaluated (a **stopped EC2 instance is skipped**).

## F. Audit Manager controls (11)
| Control | What it checks | Defaults / parameters | Runs |
|---|---|---|---|
| Backup resources are included in at least one backup plan | Resource is in a backup plan | – | Every 24 h |
| Backup plan minimum frequency and minimum retention | Plan has a rule meeting frequency and retention | **1 day** frequency, **35 days** retention | Config change |
| Vaults prevent manual deletion of recovery points | Vault policy blocks manual deletes | Up to **5 IAM roles** allowed | Config change |
| Recovery points are encrypted | Recovery point is encrypted | – | Config change |
| Minimum retention established for recovery point | Recovery point retention | **35 days** | Config change |
| Cross-Region backup copy is scheduled | Plan copies to another Region | Optional Region(s) | Every 24 h |
| Cross-account backup copy is scheduled | Plan copies to another account | Up to **5 accounts**, same org | Every 24 h |
| Resources are in a backup plan with an AWS Backup Vault Lock | Backups go to a locked vault | Optional min/max retention | Every 24 h |
| Last recovery point was created | Recent backup exists | **1–744 hours** or **1–31 days** | Every 24 h |
| Restore time for resources meet target | Latest restore time ≤ target | `maxRestoreTime` (minutes) | Every 24 h |
| Resources in a logically air-gapped vault | A copy reached a LAG vault in time | **24–2,184 h** or **1–91 days**; recommend ≥ **7 days** | Every 24 h |
- **Frequency parameter** max: **24** (hours) or **31** (days).
- "**Last recovery point was created**" ignores recovery points **copied from another account**.
- **Encryption control remediation**: for non-fully-managed types you fix encryption in the source service (for example EBS encryption).
- **Restore time control** relies on restore jobs (often from restore testing); AWS Backup gives **no restore SLA**.

## G. Reports and AWS Audit Manager
- **Report plans** deliver reports to an **S3 bucket** in **CSV or JSON**.
- **Report types**: **backup jobs**, **copy jobs**, **restore jobs**, **scan jobs** **(verify)**, **resource compliance**, **control compliance**.
- **Job reports** cover the last 24 hours and refresh daily; **compliance reports** can also run **on demand** **(verify)**.
- **Org-level reports** (multiple accounts/Regions) from the management or delegated admin account.
- **Report quota**: accounts × Regions × (daily jobs + evaluations) per report plan ≤ **100,000**.
- **AWS Audit Manager** (separate service) can **import AWS Backup Audit Manager findings** as evidence in its frameworks (for example via the AWS Backup data source) **(verify mechanism)**.
- **Pricing**: **$0.00125 per control evaluation**, plus **AWS Config configuration items ($0.003 each)** billed by Config.

## H. Monitoring and notifications
- **CloudWatch metrics** (namespace `AWS/Backup`): job counts by state, for example `NumberOfBackupJobsCompleted`, `NumberOfBackupJobsFailed`, `NumberOfBackupJobsExpired`, `NumberOfCopyJobsFailed`, `NumberOfRestoreJobsCompleted`, `NumberOfRecoveryPointsCold`, `NumberOfRecoveryPointsExpired` **(verify exact list)**.
  - Use with **CloudWatch alarms** (for example failed jobs > 0 in 24 h).
- **EventBridge events** (source `aws.backup`): `Backup Job State Change`, `Copy Job State Change`, `Restore Job State Change`, `Recovery Point State Change`, `Backup Plan State Change`, `Region Setting State Change`, `Backup Vault State Change` **(verify names)**.
  - Use for automation: open a ticket, retry, trigger restore-test validation Lambda.
- **Vault SNS notifications** (`PutBackupVaultNotifications`): one topic per vault; events such as `BACKUP_JOB_STARTED`, `BACKUP_JOB_COMPLETED`, `COPY_JOB_STARTED`, `COPY_JOB_SUCCESSFUL`, `COPY_JOB_FAILED`, `RESTORE_JOB_STARTED`, `RESTORE_JOB_COMPLETED`, `RECOVERY_POINT_MODIFIED`, `S3_BACKUP_OBJECT_FAILED`, `S3_RESTORE_OBJECT_FAILED` **(verify list)**.
  - Trap: `BACKUP_JOB_COMPLETED` fires for success **and** failure; use an **SNS subscription filter** on the state to alert only on failures **(verify)**.
  - The SNS topic policy must allow `backup.amazonaws.com` to publish.
- **CloudTrail** records all AWS Backup API calls (management events): who deleted a recovery point, changed a lock, started a restore.
- **AWS Config** records plans, vaults, selections and recovery points (used by Audit Manager).
- **Restore testing jobs** appear on the **Restore jobs** tab with restore type **Test**.

## I. IAM roles and managed policies
- **Service role** for jobs: trusted by `backup.amazonaws.com`; default `AWSBackupDefaultServiceRole`.
- **Managed policies for the service role**: `AWSBackupServiceRolePolicyForBackup`, `AWSBackupServiceRolePolicyForRestores`, S3-specific `AWSBackupServiceRolePolicyForS3Backup` / `...ForS3Restore`, `AWSBackupServiceRolePolicyForScans` (malware) **(verify S3 names)**.
- **Managed policies for people**: `AWSBackupFullAccess`, `AWSBackupOperatorAccess` (run jobs, cannot delete), `AWSBackupAuditAccess` (view audit), `AWSBackupDataTransferAccess` (gateway/data transfer) **(verify)**.
- **Service-linked roles**: `AWSServiceRoleForBackup`, `AWSServiceRoleForBackupReports`, `AWSServiceRoleForBackupRestoreTesting` **(verify first two)**.
- **`iam:PassRole`** controls who can attach a powerful backup/restore role to a plan or job.
- **Separation of duties**: backup operators run jobs; only a break-glass security role can delete recovery points or change locks.
- **Tag-based IAM**: limit who can tag resources with the backup tag, so people cannot remove resources from protection.

## J. SCP patterns
- **Region restriction (DEA-C01 skill 4.5.3, data sovereignty)**: SCP deny `*` (or `backup:*`) when `aws:RequestedRegion` is not in the approved list, so no vault or copy can exist elsewhere.
  - Copy targets can also be checked with the condition key **`backup:CopyTargets`** on `CreateBackupPlan`/`UpdateBackupPlan`/`StartCopyJob` **(verify)**.
  - Remember global services exemptions (IAM, Organizations, STS) in Region-deny SCPs.
- **Deny deletes and tampering** for everyone except a break-glass role:
  - `backup:DeleteRecoveryPoint`, `backup:UpdateRecoveryPointLifecycle`, `backup:DeleteBackupVault`, `backup:DeleteBackupPlan`, `backup:DeleteBackupSelection`.
  - `backup:PutBackupVaultAccessPolicy`, `backup:DeleteBackupVaultAccessPolicy`.
  - `backup:DeleteBackupVaultLockConfiguration` (stops governance-lock removal).
  - `backup:PutBackupVaultLockConfiguration` too, so nobody adds an unwanted compliance lock with "Always" retention.
  - `kms:ScheduleKeyDeletion` and `kms:DisableKey` on backup keys.
  - `ec2:ModifySnapshotAttribute`, `ec2:ModifySnapshotTier`, `ec2:DisableImage`, `ec2:DeregisterImage` for backup snapshots/AMIs.
- **SCPs do not apply to the management account**; keep workloads out of it.
- **SCP vs vault policy**: SCP sets org-wide guardrails; vault policy protects one vault and also works on cross-account principals.

## K. MFA, break-glass and ransomware playbook
- **Break-glass role**: the only principal exempt from deny-delete policies; requires **MFA** (`aws:MultiFactorAuthPresent`), is monitored and alarmed in CloudTrail.
- AWS Backup has **no MFA Delete** feature like S3; use IAM conditions plus Vault Lock **(verify)**.
- **Ransomware playbook**:
  - Immutable vault (**compliance Vault Lock**) in a **separate backup account**.
  - **LAG vault** shared to a **recovery account**, with **MPA** for worst case.
  - **Least privilege** + **SCP deny deletes** + **CMK deletion guarded**.
  - **Malware scan** recovery points; restore the **latest clean** one.
  - **Restore testing** so RTO is known before an incident.
  - Alerts on `DeleteRecoveryPoint`, lock changes and failed jobs.
- **3-2-1-1-0 rule**: **3** copies, **2** different media/accounts, **1** off-site (cross-Region), **1** immutable/air-gapped (Vault Lock/LAG), **0** errors (restore testing and validation).

## L. Cost: what you pay for
- **Backup storage**: per **GB-month**, by resource type, tier (warm/cold) and Region.
  - Confirmed examples: **EFS warm $0.05/GB-month**, **S3 $0.05/GB-month**, **EBS $0.05/GB-month** (pricing examples, US East).
  - From memory **(verify)**: EFS cold about **$0.01**, EBS archive about **$0.0125**, DynamoDB warm about **$0.10** and cold **$0.03**, RDS snapshot about **$0.095**, Aurora about **$0.021** per GB-month.
- **LAG vault storage**: separate rate (example **$0.0575/GB-month** for EBS/EFS in Ireland).
- **Restore**: per GB restored for AWS Backup-billed types (example **$0.02/GB** EFS and S3 warm); cold restore costs more **(verify)**.
- **Item-level restore**: example **$0.50 per request + $0.02/GB**; **EBS file-level restore $0.03/GB**.
- **Cross-Region data transfer**: per GB from the source Region (examples **EBS $0.02/GB**, **EFS $0.04/GB**).
- **Restore testing**: **$1.50 per recovery point tested** + restored resource cost (example: EBS test storage $0, EFS warm restore $0.02/GB).
- **Backup search**: index **$0.20/million files**, index storage **$0.02/million items-month**, search **$0.07/million items**.
- **Audit Manager**: **$0.00125 per evaluation** + Config items **$0.003**.
- **Malware protection**: GuardDuty per-GB scan pricing.
- **S3 backups** also incur **S3 requests (GET/LIST)** and **EventBridge** usage on the source bucket.
- **Vault Lock and legal holds**: no fee, but they **extend storage time**.
- **Early deletion from cold**: charged for the rest of the 90 days.
- **Not-fully-managed types** may bill under the source service (for example EBS snapshots, RDS snapshots); **fully managed types** bill under AWS Backup with **cost allocation tags**.

## M. Cost levers
- Right-size **retention per data class** (35 days for dev, 7 years only where law requires).
- Avoid **"Always"** retention, especially in locked vaults.
- Use **lifecycle to cold** for long-retention data on cold-capable types (EFS, EBS archive, DynamoDB advanced, VMs...).
- Back up full-copy types (DynamoDB, DocumentDB, Neptune, Redshift) **less often**.
- **Exclude scratch data**: tag-based selection, `NotResources` exclusions, keep temp data out of protected buckets.
- **Remove duplicate protection** (native automated backups + AWS Backup, EFS automatic backup + custom plan).
- **Copy only critical data** cross-Region; set **shorter retention on copies**.
- Tiered plans (**gold/silver/bronze tags**) so only critical systems get frequent backups and copies.
- Keep **S3 versioning lifecycle** in check so backups do not include endless noncurrent versions.
- Limit restore testing to a **sample** (random recovery point, a few resources per type).

## N. Quotas to remember
- **300 backup plans** per Region per account; **2,000 versions** per plan.
- **10 rules per plan**; **100 resource assignments per plan**; **10 tag-based selections per plan**.
- **30 tags** in a selection; **30 conditions** per assignment; **10 tags** added to a recovery point; **5 copy actions per rule**.
- **300 vaults** (standard + LAG) per Region per account; **1,000,000 recovery points per vault**.
- **1 concurrent backup/copy job per resource**; **100 concurrent copy jobs** per destination Region (+5 per vault).
- **50 legal holds** per account; **20 hypervisors**; **4 jobs per backup gateway**; **10 nested stack layers**.
- **Audit Manager**: 15 frameworks, 50 controls, 20 report plans.
- **Restore testing**: 100 plans, 30 selections, start window 1–168 h, selection window ≤ 365 days.
- **Malware scans**: 150 running per account. **Search**: 10 concurrent searches, 20 recovery points per search.
- Correction vs older notes: plans 300 (not 100), rules per plan 10 (not 20), vaults 300 (not 100).

## O. RTO and RPO design
- **RPO** = data you can lose: hourly snapshots → up to **1 hour**; continuous backup → **seconds/minutes**; cross-Region copies → RPO of the copy schedule plus copy time.
- **RTO** = time to recover: depends on restore type and size; **no AWS SLA** → measure with **restore testing** and the restore-time control.
- **Cold storage** increases RTO (EBS archive restores take hours to days).
- **LAG vault shared with a recovery account** lowers RTO after account compromise (restore without first copying back).
- **Backups are not HA**: for minutes-level RTO use replicas (Multi-AZ, Aurora Global Database, DynamoDB global tables, S3 CRR) and keep backups for corruption/ransomware.
- **Item-level restore** lowers RTO for small mistakes (one file or object).
- Example tiers: **gold** = continuous + hourly + cross-Region + LAG; **silver** = daily + cross-Region; **bronze** = daily, 35 days, same Region.

## Troubleshooting (symptom → cause → fix)
- **Member accounts show no org plan** → backup policies not enabled, policy not attached, or vault/role missing in the account → enable the policy type, attach, deploy vault and role via StackSets.
- **Org-deployed plan cannot be edited in the member account** → organization-managed plans are read-only locally → change the backup policy.
- **Cross-account monitoring empty** → feature not opted in, Region lacks support, or 24-hour opt-in delay → opt in and wait.
- **Delegated admin cannot see jobs in an opt-in Region** → delegated admins have no monitoring there → use the management account.
- **Audit Manager shows no evaluations** → AWS Config not recording backup resource types → enable Config recording.
- **"Last recovery point" non-compliant though copies exist** → control ignores points copied from other accounts → evaluate in the source account.
- **Stopped instance not in compliance report** → only active resources are evaluated → expected.
- **No SNS emails on failures** → topic policy does not allow `backup.amazonaws.com`, or no subscription filter/event chosen → fix topic policy and events.
- **Too many SNS messages** → `BACKUP_JOB_COMPLETED` includes successes → add a filter policy on state.
- **Copies to an unapproved Region still possible** → no Region SCP → add `aws:RequestedRegion` deny (and `backup:CopyTargets` check).
- **Admin deleted recovery points** → no deny-delete vault policy/SCP or no compliance lock → add guardrails and Vault Lock.
- **Backup bill jumped** → new cross-Region copies, "Always" retention, full-copy types backed up hourly, duplicate native backups → review plans with cost allocation tags.
- **Unexpected cold early-deletion charges** → retention shortened or points deleted before 90 days in cold → keep cold points ≥ 90 days.
- **Restore test costs high** → many resources per run or long cleanup retention → sample fewer resources, shorten retention hours.

## Scenarios: "If X → Y, because Z"
- **If** **200 accounts** must get the same backup baseline automatically, **then** attach an **AWS Organizations backup policy** to the root or organizational units (OUs), selecting resources **by tag**. **This works because** each account gets an **effective policy** that creates an **organization-managed backup plan** it **cannot edit or delete** locally. Catch: the target vault and IAM role must already exist in each account (deploy with CloudFormation StackSets) **(verify)**.
- **If** backup admins must not work in the management account, **then** **register a member account as delegated administrator** for AWS Backup. **This works because** the delegated admin can manage **backup policies**, **cross-account monitoring** and **Audit Manager** org reports, keeping daily work out of the management account.
- **If** an auditor wants daily proof that all tagged resources are backed up with at least **35-day** retention, **then** deploy an **AWS Backup Audit Manager framework** with a **report plan** delivering reports to Amazon S3. **This works because** controls are checked automatically (on configuration changes or every 24 hours) and reports in CSV or JSON are kept in the bucket. Audit Manager needs **AWS Config** recording.
- **If** AWS Backup Audit Manager shows nothing after setup, **then** turn on **AWS Config recording** for the AWS Backup resource types and the audited types. **This works because** Audit Manager controls are built on **AWS Config** data; without it they show no data or non-compliant.
- **If** the on-call engineer needs a page for every failed backup, **then** create an **Amazon EventBridge** rule on the `Backup Job State Change` event **(verify)** with state **FAILED**, sending to Amazon Simple Notification Service (SNS). **This works because** EventBridge pushes job events **as they happen**, and filtering on FAILED avoids alerts for successful jobs.
- **If** data must never leave **eu-central-1** and **eu-west-1** (data sovereignty, skill 4.5.3), **then** add a **service control policy (SCP)** that denies requests when `aws:RequestedRegion` is not one of those Regions. **This works because** a copy needs a vault in the destination Region, and the SCP stops any vault or copy from being created elsewhere. Remember to exempt global services (IAM, Organizations, STS).
- **If** only the security team may delete backups, **then** use a **vault access policy** and a **service control policy (SCP)** that deny deletes for everyone except a **break-glass role** that needs **multi-factor authentication (MFA)**. **This works because** an explicit **deny overrides any allow**, so even admins cannot delete. Catch: SCPs do not apply to the management account.
- **If** a governance-mode Vault Lock must not be removed by account admins, **then** add a **service control policy (SCP)** denying `backup:DeleteBackupVaultLockConfiguration`. **This works because** a governance lock can be removed by anyone with that IAM permission, and the SCP takes it away.
- **If** ransomware is the main threat, **then** combine a **compliance-locked vault** in a central backup account, a **logically air-gapped (LAG) vault** shared to a recovery account, **malware scans** of recovery points, and **restore testing**. **This works because** together they give backups that are **immutable**, **isolated**, **clean** and **proven to restore**.
- **If** the bill shows high backup storage for Amazon DynamoDB, **then** **reduce backup frequency or retention**, or **move old backups to cold storage** after turning on DynamoDB **advanced features**. **This works because** DynamoDB backups are **full copies every time**, so each extra backup adds full storage; cold storage is only available with advanced features.
- **If** leadership asks for a **15-minute recovery point objective (RPO)** for Amazon Aurora, **then** use **continuous backup**. **This works because** continuous backup gives an RPO of seconds to minutes, while snapshot backups run **at most hourly**.
- **If** leadership asks for a **5-minute recovery time objective (RTO)** for a database, **then** use **replicas** (Multi-AZ or Aurora Global Database), not only backups. **This works because** most restores **create a new resource** and AWS Backup gives **no restore time SLA**; keep backups for corruption and ransomware.
- **If** you need backup cost per team, **then** use **fully managed** resource types or **cost allocation tags** on recovery points. **This works because** fully managed backups are billed under **AWS Backup** with cost allocation tags, while other types may bill under the source service.
- **If** you must show restores finish within **2 hours**, **then** use **restore testing** plus the Audit Manager control **"Restore time for resources meet target"** with `maxRestoreTime` **120** (minutes). **This works because** the control compares **measured restore durations** with the target, and restore testing produces those restores.

Verified from AWS docs on 2026-11-02 (pages used): Audit Manager controls and remediation; AWS Backup quotas; AWS Backup feature availability (Region and cross-account management notes); Restore testing; Logically air-gapped vault; Backup plan options and configuration; aws.amazon.com/backup/pricing.

Unconfirmed (verify): Organizations opt-in wording and trusted access; backup policy inheritance operators and size limit; vault/role prerequisite for backup policies; delegated admin delegation policy and count; report types (scan jobs) and on-demand behavior; AWS Audit Manager import mechanism; CloudWatch metric names; EventBridge event names; SNS vault event list and filter guidance; managed policy and service-linked role names; `backup:CopyTargets` condition key; no MFA Delete in AWS Backup; storage prices other than the $0.05 examples; cold restore pricing.

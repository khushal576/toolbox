# AWS Backup – 1. Concepts, plans, rules, resource assignment and resource support

Short notes. Each point is a fact you can be asked about.

## A. What AWS Backup is (and is not)
- **AWS Backup** = a **fully managed, policy-based service** that centralizes and automates backups across AWS services, plus on-premises/VMware workloads through **AWS Backup gateway**.
- One place for **schedules, retention, encryption, copies (cross-Region/cross-account), immutability, monitoring, audit reports and restores**.
- **Why**: it replaces per-service scripts and per-service snapshot schedules, so policy is **consistent and provable** to auditors.
- **It is regional**: plans, vaults and jobs live in one Region; you build multi-Region protection with **copy actions**.
- **It does not govern backups taken outside it**: native EBS snapshots, RDS automated backups you set in RDS, DynamoDB on-demand backups made in the DynamoDB console are **not** managed, audited or locked by AWS Backup.
  - Catch: auditors using AWS Backup Audit Manager only see what AWS Backup knows about.
- **It is not a replication service**: it makes point-in-time copies; for live replicas use S3 Replication, DynamoDB global tables, Aurora Global Database, etc.
- **It is not an archive for arbitrary files**: it backs up **supported resource types**, not loose data you upload.
- **AWS Backup cannot run locally on AWS Outposts**: backup operations and storage run in the **parent Region**; local retention on Outposts is **not supported**.

## B. Native backups vs AWS Backup
- For some services AWS Backup **uses the same infrastructure as the native feature** (for example **RDS/Aurora snapshots and continuous backups**, **EBS snapshots**, **FSx backups**).
  - Effect: the backup is still a native snapshot underneath; billing may appear under the service, not under "Backup".
- For **fully managed** types AWS Backup uses its **own separate storage layer** (for example **S3, EFS, DynamoDB with advanced features, Timestream, Aurora DSQL, SAP HANA, VMs, EKS**).
- **Duplicate cost trap**: keeping **native automated backups plus an AWS Backup plan** for the same resource means paying twice for overlapping data.
  - Fix: pick one owner per resource; for RDS let AWS Backup manage continuous backup instead of a separate long RDS retention.
- **Second trap**: native snapshots you create by hand are **not deleted by AWS Backup lifecycle**, so they pile up silently.
- **EFS automatic backups** (turned on by default for new EFS file systems in the console) are actually an **AWS Backup plan** (`aws/efs/automatic-backup-plan`, daily, 35-day retention, vault `aws/efs/automatic-backup-vault`) **(verify)**.
  - Trap: adding your own plan on top doubles EFS backup storage.

## C. Full AWS Backup management
- **Full AWS Backup management** is a per-resource-type feature (column in the feature table).
- Benefits:
  - **Independent encryption**: backups encrypted with the **vault's KMS key**, not the source resource's key (extra layer of defense).
  - **AWS Backup ARNs** (`arn:aws:backup:...`) for recovery points, so **vault access policies and IAM** work on them.
  - **Centralized billing** under "AWS Backup" and **cost allocation tags** in Cost Explorer.
- Fully managed types (feature table): **S3, EFS, DynamoDB with advanced features, Aurora DSQL, Timestream, SAP HANA on EC2, virtual machines, EKS**.
- **Not fully managed**: EC2, EBS, RDS, Aurora, FSx, Storage Gateway, DocumentDB, Neptune, Redshift, Redshift Serverless, CloudFormation, standard DynamoDB.
  - Catch: for these, encryption follows the **source resource's key** and backup encryption must be set in the source service.
  - Catch: cross-account copy of non-fully-managed types needs the source encrypted with a **customer managed key** (AWS managed keys cannot be shared).

## D. Core building blocks
- **Backup plan**: the policy document; contains **one or more backup rules**. Plan name up to **50 characters**.
- **Backup rule**: schedule + windows + lifecycle + target vault + copy actions + recovery point tags + options (continuous, indexing, malware scan).
  - Rule names are **case sensitive**, **1–50 alphanumeric characters or hyphens**.
- **Resource assignment (backup selection)**: which resources a plan protects and which **IAM role** it uses.
- **Backup vault**: container for recovery points; has a **KMS key** and an optional **resource-based access policy**.
- **Recovery point**: one backup (snapshot or continuous backup) stored in a vault; its **content is immutable**.
- **Jobs**: backup jobs, copy jobs, restore jobs (and scan, index jobs); each has a status you monitor.
  - Backup job states include `CREATED`, `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `EXPIRED`, `ABORTED`, `ABORTING`, `PARTIAL` **(verify full list)**.
- **Protected resources**: view of resources that have at least one recovery point.
- **Plan versions**: each update creates a new version; quota **2,000 versions per plan**.

## E. Schedule, frequency and time zone
- **Console frequencies**: **every hour, every 12 hours, daily, weekly (pick days), monthly (pick day)**, or a **custom cron**.
- **Most frequent snapshot schedule = hourly** (console, cron or CLI). There is no sub-hourly snapshot rule.
- **Cron**: AWS six-field cron (same as EventBridge), for example `15 * ? * * *` = every hour at :15; `0 12 * * ? *` = daily at 12:00 UTC.
- **Time zone**: the rule can run in a chosen time zone (console defaults to your local time); cron defaults to **UTC**.
- **DST trap**: a time zone with daylight saving can skip a run when clocks move forward; use UTC or take a manual backup that day.
- **Cron evaluation window**: AWS Backup evaluates cron between **00:00 and 23:59**; an "every 12 hours" rule that starts later than **11:59** runs **only once a day**.
- **Continuous backups cannot be scheduled** with time or cron; they record changes all the time once enabled.
- **Overlapping rules**: when start windows of rules in a plan overlap, AWS Backup takes **one backup** and keeps it under the rule with the **longer retention**.
  - Example from docs: hourly/1-day rule + 12-hourly/1-week rule → the 12-hour rule wins in its 8-hour start window; the hourly rule only runs outside it.
- **Database maintenance window**: AWS database services **cannot start a backup 1 hour before or during their maintenance window**; snapshot backups scheduled then **fail**.
  - **FSx**: cannot start **3 hours before or during** its maintenance or automatic backup window.
  - **Aurora is exempt** from this restriction.
  - Exception: if AWS Backup handles **both snapshot and continuous** backups for a supported service, it schedules around conflicts automatically.

## F. Start window and completion window
- **Start window** = how long AWS Backup may wait to **start** the job after the scheduled time.
- **Completion window** = how long a started job may run before it is **cancelled**.
- **Console defaults**: start time **00:30 local**, **start within 8 hours**, **complete within 7 days**.
  - Correction vs older notes: not "1 hour / 8 hours". **(verify API defaults; minimum start window is believed to be 60 minutes)**.
- **Completion window does not apply to Amazon FSx** resources.
- **During the start window** the job stays `CREATED`; on retryable errors AWS Backup **retries at least every 10 minutes** until it starts (`RUNNING`).
- **Expired vs cancelled**:
  - Job never started inside the start window → **`EXPIRED`**.
  - Job started but did not finish inside the completion window → **cancelled/aborted** (state shows the job did not complete) **(verify exact state name)**.
- Catch: a very short start window plus busy resources (or a maintenance window) is the classic cause of `EXPIRED` jobs.
- **Concurrent backup jobs per resource = 1** (not adjustable); a second job on the same resource waits or expires.

## G. Lifecycle, retention and cold storage
- **Every backup is created in warm storage**. Optionally transition to **cold storage** (cheaper storage, slower/costlier restore).
- **Lifecycle settings**: `MoveToColdStorageAfterDays` and `DeleteAfterDays` (console: "total retention period").
- **Retention range for snapshot backups**: **1 day to 100 years**, or **indefinite** if you leave it empty ("Always").
- **Retention range for continuous backups**: **1 to 35 days**.
- **Retention clock** starts at the **job start date**, not completion date.
- **Cold minimum**: backups must stay in cold storage **at least 90 days**, so `DeleteAfterDays` must be **≥ MoveToColdStorageAfterDays + 90**.
- **Early deletion** from cold (before 90 days) is charged **prorated** for the remaining days **(verify billing wording)**.
- **No move back**: once in cold storage it stays there; you cannot change "transition to cold after days" for a transitioned backup.
- **Warm time recommendation**: keep backups in warm storage **at least 8 days** before cold.
  - Why: incremental backups need **at least one warm full backup**; transitioning too soon (for example after 1 day) makes AWS Backup create **another warm full backup**.
  - Correction vs older notes: docs do not state a 60-day warm minimum for cold storage (60 days relates to S3 backup tiering, see file 2) **(verify)**.
- **Cold storage supported types** (plan options page):

| Resource | Data in cold tier |
|---|---|
| CloudFormation | Incremental |
| DynamoDB with advanced features | Full (no incremental in any tier) |
| EBS (EBS Snapshot Archive) | Full; incremental becomes full after transition |
| EFS | Incremental |
| SAP HANA on EC2 | Incremental |
| Timestream | Incremental |
| VMware virtual machines | Incremental |

- The feature table also marks **Aurora DSQL** with lifecycle to cold storage.
- **EBS cold** needs `OptInToArchiveForSupportedResources` and a frequency of **monthly or less often**.
- **Not cold-capable**: S3, RDS, Aurora, FSx, EC2 (AMI), DocumentDB, Neptune, Redshift, standard DynamoDB, EKS, Storage Gateway.
- **Billing nuance**: for incremental types, data moves to cold only when no warm backup still references it; data referenced by warm backups is billed warm.

## H. Incremental vs full backups
- **Incremental**: first backup is full, later ones store only changed data → cheaper storage.
- **Incremental types** (feature table): EC2, S3, EBS, RDS instances/clusters, EFS, FSx (all four), Storage Gateway, Timestream, VMs, Windows VSS, CloudFormation.
- **Aurora and SAP HANA**: snapshots are **full**; incremental comes only through **continuous backup (PITR)**.
- **Full every time**: DocumentDB, Neptune, DynamoDB (standard and advanced), Redshift, Aurora DSQL, EKS.
- Trap: frequent schedules on full-copy types multiply storage cost.

## I. Continuous backup and PITR
- **Continuous backup** = enables **point-in-time restore (PITR)** to any second in the window (up to **35 days**).
- **Supported**: **S3**, **RDS DB instances (single-AZ and Multi-AZ instance)**, **Aurora**, **SAP HANA on EC2**.
- **Not supported**: **RDS Multi-AZ DB clusters**, DynamoDB (it has **native PITR**, 1–35 days, outside AWS Backup), EFS, EBS, FSx.
- **S3 continuous** needs **versioning**; snapshot (periodic) S3 backups also need versioning.
- **RDS/Aurora continuous** uses the **native automated backups (transaction logs)** underneath; AWS Backup takes over their retention setting **(verify behavior on removal)**.
- **Copy of a continuous backup becomes a snapshot** (periodic) recovery point; **no PITR on the copy**.
- **CloudFormation stack backups**: nested S3/RDS resources **lose PITR** in the stack recovery point.
- **Best practice**: pair a continuous rule (short window, ≤ 35 days) with a daily/monthly snapshot rule for long retention.

## J. Other rule options
- **Target vault**: each rule writes to one vault (default vault named `Default` if you pick it).
- **Copy actions**: up to **5 copy actions per rule**; each names a destination vault ARN (same/other Region, same/other account) and its own lifecycle.
  - If the copy's `DeleteAfterDays` is not set, the copy **follows the source backup's lifecycle**.
  - Copy cold-storage rule is the same: **expire > transition + 90 days**.
  - The copy uses an **IAM role** (default role is created if missing).
- **Recovery point tags**: tags added automatically to backups the rule creates; up to **10 tags per recovery point** (policy quota).
- **Plan tags**: tags on the plan itself, for organizing.
- **Backup indexing**: a rule can create a **backup index** of **S3 and EBS** recovery points so you can later run **backup search** (file 2).
- **Malware scanning action**: a rule can trigger **GuardDuty malware scans** (incremental or full) of EC2, EBS or S3 recovery points (file 2).
- **Advanced backup settings – EC2**: **Windows VSS** for application-consistent backups of Windows apps (for example SQL Server); some instance types are excluded.
- **Advanced backup settings – S3**: option to **exclude ACLs and object tags** from backups.
  - Catch: restored objects without ACLs use the destination bucket's object ownership settings.
- **Advanced settings – DynamoDB**: this is the separate **"advanced features" opt-in** in Settings, not a per-rule toggle **(verify)**.

## K. On-demand backups and plan templates
- **On-demand backup**: start a backup job now for one resource, choosing vault, retention, start/completion window and role.
  - Use before risky changes; it is not tied to a plan's schedule.
  - On-demand backups can use **continuous** mode for supported types **(verify)**.
- **Backup plan templates** (console "start with a template"): for example **Daily-35day-Retention**, **Daily-Monthly-1yr-Retention**, **Daily-Weekly-Monthly-5yr-Retention**, **Daily-Weekly-Monthly-7yr-Retention** **(verify names)**.
- You can also build a plan from **JSON** (CLI/API) or IaC (CloudFormation `AWS::Backup::BackupPlan`, CDK, Terraform).

## L. Resource assignment (backup selections)
- A **resource assignment** maps resources to a plan; up to **100 assignments per plan** (not adjustable).
- **By resource type / all resource types**: "include all resource types" protects every **opted-in** type in the Region.
- **By ARN**: list specific resources; wildcards allowed (for example all EBS volumes) **(verify ARN quotas: about 500 without wildcards, 30 with wildcards)**.
- **By tags** (`ListOfTags`): resources matching **any** listed tag are included (**OR**).
- **Conditions** (`Conditions`): **StringEquals, StringLike, StringNotEquals, StringNotLike** on tag keys/values; all conditions must match (**AND**).
  - Trap: OR vs AND confusion is the top cause of "resource not backed up".
- **Exclusions** (`NotResources`): exclude specific ARNs, for example scratch volumes.
- **Quotas**: **30 tags** in a selection, **30 conditions** per assignment, **10 tag-based selections per plan**, **10 rules per plan**.
- **Tag-based assignment** = new resources with the right tag are protected automatically (best practice for scale).
- **IAM role**: the plan assumes a role trusted by `backup.amazonaws.com`.
  - **Default role**: `AWSBackupDefaultServiceRole` with managed policies `AWSBackupServiceRolePolicyForBackup` and `AWSBackupServiceRolePolicyForRestores`; created automatically if missing.
  - **S3** needs extra managed policies `AWSBackupServiceRolePolicyForS3Backup` / `AWSBackupServiceRolePolicyForS3Restore` **(verify)**.
  - Caller needs **`iam:PassRole`** for the role.
- **Service opt-in per Region** (Settings → service opt-in): AWS Backup only protects **resource types turned on in that Region**.
  - Trap: a plan with "all resource types" silently skips types that are off; newer types may be off by default **(verify defaults)**.
- **DynamoDB advanced features** are a separate opt-in in Settings (needed for copies, cold storage, full management).
- **Restore-testing resources** (tag `awsbackup-restore-test` or name prefix) are **ignored by backup plans**.

## M. Resource support matrix
Feature table (docs, read on 2026-11-02). Y = supported, – = not.

| Resource | X-Region | X-account | Audit Mgr | Incremental | PITR | Full mgmt | Cold | Item-level | Restore test | LAG vault |
|---|---|---|---|---|---|---|---|---|---|---|
| EC2 | Y | Y | Y | Y | – | – | – | – | Y | Y |
| S3 | Y | Y | Y | Y | Y | Y | – | Y | Y | Y |
| EBS | Y | Y | Y | Y | – | – | Y | Y | Y | Y |
| RDS instance (single/Multi-AZ instance) | Y | Y | Y | Y | Y | – | – | – | Y | – |
| RDS Multi-AZ cluster | – (see note) | – | Y | Y | – | – | – | – | Y | – |
| Aurora | Y | Y | Y | via PITR | Y | – | – | – | Y | Y |
| Aurora DSQL | Y | Y | – | – | – | Y | Y | – | – | Y |
| EFS | Y | Y | Y | Y | – | Y | Y | Y | Y | Y |
| FSx (Lustre, Windows, ONTAP, OpenZFS) | Y | Y | Y | Y | – | – | – | – | Y | Y |
| Storage Gateway | Y | Y | Y | Y | – | – | – | – | – | Y |
| DocumentDB | Y | Y | – | – | – | – | – | – | Y | Y |
| Neptune | Y | Y | – | – | – | – | – | – | Y | Y |
| Redshift (provisioned) | – | – | – | – | – | – | – | Y | Y | – |
| Redshift Serverless | – | – | – | – | – | – | – | Y | – | – |
| Timestream (LiveAnalytics) | Y | Y | – | Y | – | Y | Y | – | – | Y |
| Windows VSS | Y | Y | Y | Y | – | – | – | – | – | Y |
| Virtual machines (VMware) | Y | Y | Y | Y | – | Y | Y | Y (disk) | – | Y |
| CloudFormation | Y | – | Y | Y | – | – | Y | – | – | – |
| DynamoDB (standard) | – | – | Y | – | – | – | – | – | Y | – |
| DynamoDB advanced features | Y | Y | Y | – | – | Y | Y | – | Y | Y |
| SAP HANA on EC2 | Y | Y | – | via PITR | Y | Y | Y | – | – | – |
| EKS | Y | Y | – | – | – | Y | – | Y | – | Y |

- **Newer feature columns**: **backup search** = S3, EBS; **backup tiering** = S3 only; **malware protection** = EC2, S3, EBS; **access points** = S3 only.
- **No copy column = no copy at all**: if a type lacks cross-Region and cross-account checks, **even same-Region, same-account copies to another vault are not supported**.

## N. Per-resource traps
- **EC2**: backup = **AMI + EBS snapshots**; incremental; restore creates a **new instance**; Windows VSS optional; malware scan supported.
- **EBS**: backup = **EBS snapshot**; incremental; cold via **EBS Snapshot Archive** (full copy, 90-day minimum); item-level (file) restore and search supported.
- **S3**: needs **versioning on**; supports **continuous (PITR, ≤ 35 days)** and **periodic** backups; fully managed; item-level (object/prefix) restore; search, tiering, malware scan, access points.
  - Cost trap: versioning keeps noncurrent versions; add a lifecycle rule to expire them **(verify guidance)**.
  - S3 backups also generate **S3 request and EventBridge** usage.
- **RDS DB instances**: snapshots + continuous; **simultaneous cross-Region + cross-account copy in one action**.
- **RDS Multi-AZ DB clusters** (the two-readable-standby deployment): **no copy operations of any kind** and **no continuous backup/PITR** in AWS Backup.
  - Note: the docs table shows copy checks on the "RDS cluster" row, but footnote 3 says Multi-AZ clusters support no copy; trust the footnote **(verify)**.
- **Aurora**: snapshots are full; continuous backup gives PITR; copies are made from **full backups**; simultaneous cross-Region + cross-account copy.
- **Aurora DSQL**: fully managed, cross-Region/account, cold storage, LAG vault; **no Audit Manager, no restore testing**; limited Regions.
- **DynamoDB standard**: uses DynamoDB's own on-demand backup engine; **no copy, no cold storage**, billed by DynamoDB.
- **DynamoDB advanced features**: opt in once; gives **cross-Region and cross-account copy, cold storage, cost allocation tags, independent encryption**; billed by AWS Backup; still **full** backups.
- **EFS**: fully managed, incremental, cold storage, item-level (file/directory) restore.
- **FSx**: all four types (Lustre, Windows File Server, ONTAP, OpenZFS) use **native FSx backups**; no cold, no PITR.
  - FSx for Windows restore testing works only with **AWS Managed Microsoft AD**.
  - FSx for OpenZFS **Multi-AZ** restore only from FSx console/API (`CreateFileSystemFromBackup`).
- **Storage Gateway**: **Volume Gateway** volumes (backed by EBS snapshots); no restore testing.
- **DocumentDB** (instance-based clusters) and **Neptune**: full cluster snapshots; copy supported; **no Audit Manager column**; restore testing supported.
  - Unencrypted Aurora/DocumentDB/Neptune clusters **cannot go to a LAG vault**.
- **Redshift provisioned**: manual cluster snapshots through AWS Backup; **no copy** (use native Redshift cross-Region snapshot copy); item-level = **table restore**.
- **Redshift Serverless**: namespace snapshots; **no copy, no restore testing**; table-level (item) restore supported.
- **Timestream for LiveAnalytics**: supported and fully managed; **Timestream for InfluxDB is not supported**.
  - Quotas: **4 concurrent backup jobs**, **1 concurrent restore job** per account.
- **CloudFormation stacks** (application stacks): one composite recovery point of the template + supported nested resources; up to **10 nested layers**.
  - **Cross-Region yes, cross-account no**; nested resources keep their own features except PITR.
- **SAP HANA on EC2**: through **AWS Systems Manager for SAP** (Backint); continuous PITR; cold storage; no restore testing, no LAG.
- **VMware / virtual machines**: **AWS Backup gateway** (VM appliance) on VMware ESXi on-premises, **VMware Cloud on AWS**, or VMware on **Outposts**.
  - Quotas: **20 hypervisors**, **4 backup/restore jobs per gateway** (add gateways to scale).
- **EKS**: backs up **cluster state (Kubernetes objects)** plus **persistent storage** (for example EBS, EFS, S3); persistent volumes keep their own feature support.
  - Quotas: **10,000 namespaces**, **1,200 persistent storage backups** per cluster backup; **1 restore job per target cluster**.
- **Opt-in Regions**: **no cross-account copy for CloudFormation and Timestream**; FSx cross-Region copy not supported in Middle East (Bahrain) and (UAE).

## O. What AWS Backup does NOT cover (data platform view)
- **AWS Glue Data Catalog**: not supported; protect with IaC/exports.
- **Amazon OpenSearch Service**: not supported; use OpenSearch **automated/manual snapshots to S3**.
- **Kinesis Data Streams / Amazon MSK data**: not supported; rely on stream retention, replication (MSK Replicator) or landing data in S3.
- **Amazon Keyspaces, ElastiCache, MemoryDB, Lake Formation permissions, Athena workgroups**: not in the supported list; use native features **(verify Keyspaces/ElastiCache are still absent)**.
- **EMR**: no cluster backup; back up the S3 data and EBS/EC2 only if needed.
- **Timestream for InfluxDB**: not supported.
- Exam pattern: a data lake on S3 + Glue → **AWS Backup for S3** and **IaC for Glue metadata**.

## Scenarios: "If X → Y, because Z"
- **If** every production resource with a given tag, across Amazon Elastic Block Store (EBS), Amazon Relational Database Service (RDS), Amazon Elastic File System (EFS) and Amazon DynamoDB, must be backed up every night, **then** create **one AWS Backup plan** with a daily rule and a **tag-based resource assignment** (backup selection). **This works because** a tag-based assignment picks up **new resources automatically** as soon as they carry the right tag, so nobody has to add them by hand. Catch: tags listed in `ListOfTags` match with **OR**, while `Conditions` must all match (**AND**); mixing these up is the top cause of "resource not backed up".
- **If** a plan says "include all resource types" but Amazon S3 buckets are not being backed up, **then** turn on **S3 in Settings → service opt-in** for that Region and turn on **S3 versioning** on the buckets. **This works because** AWS Backup only protects resource types that are **opted in** in that Region, and S3 backups (periodic and continuous) need versioning. The plan skips opted-out types **silently**.
- **If** backup jobs for an Amazon Relational Database Service (RDS) instance fail at the same time every week, **then** move the backup rule's schedule **away from the database maintenance window**. **This works because** AWS database services **cannot start a backup 1 hour before or during** their maintenance window, so snapshot backups scheduled then **fail**. Aurora is exempt, and Amazon FSx needs **3 hours** of clearance instead.
- **If** backup jobs show `EXPIRED` on busy nights, **then** **widen the start window** of the rule. **This works because** the start window is how long AWS Backup may wait to start a job; a job that never starts inside it ends as `EXPIRED`. Only **1 backup job per resource** can run at a time, so a busy resource or a maintenance window easily uses up a short window.
- **If** you must restore an Amazon S3 bucket to exactly **10:42:15 yesterday**, **then** use **continuous backup**, which gives **point-in-time restore (PITR)** to any second within a window of up to **35 days**. **This works because** snapshot backups can only restore to the moment each snapshot was taken. S3 continuous backup needs **versioning** on the bucket.
- **If** Amazon Aurora data must be kept **7 years** and also be restorable to any second in recent weeks, **then** put two rules in the plan: a **continuous backup rule** (point-in-time restore (PITR), **35 days**) and a **monthly snapshot rule** kept **7 years**. **This works because** continuous backup retention is limited to **1–35 days**, while snapshot backups can be kept from 1 day to 100 years. Aurora snapshots are **full** copies, so a monthly (not daily) long-term rule keeps storage cost down.
- **If** Amazon Elastic File System (EFS) backups older than 30 days must cost less, **then** set the lifecycle to **move to cold storage after 30 days** and **delete no earlier than day 120**. **This works because** cold storage is cheaper but backups must stay there **at least 90 days**, so `DeleteAfterDays` must be **≥ move-to-cold day + 90**. Deleting earlier is still charged for the remaining days.
- **If** someone sets an Amazon Elastic Block Store (EBS) rule to move backups to cold storage after **1 day**, **then** expect **extra warm full backups** and **full-size archive copies**. **This works because** incremental backups need at least **one warm full backup**, so moving too soon makes AWS Backup create another warm full; and EBS cold storage (**EBS Snapshot Archive**) stores **full** snapshots. AWS recommends keeping backups warm **at least 8 days**; EBS cold also needs a **monthly or less frequent** schedule.
- **If** standard Amazon DynamoDB backups must be copied to another Region, **then** turn on **AWS Backup advanced features for DynamoDB** in Settings. **This works because** standard DynamoDB backups use DynamoDB's own backup engine and support **no copy**; advanced features add **cross-Region and cross-account copy**, cold storage and independent encryption.
- **If** Amazon Redshift snapshots must exist in another Region, **then** use **native Redshift cross-Region snapshot copy**. **This works because** AWS Backup has **no copy** support for Redshift at all.
- **If** an Amazon Relational Database Service (RDS) **Multi-AZ DB cluster** needs backups in another account, **then** AWS Backup cannot copy it; use native snapshot sharing/export or a different deployment. **This works because** Multi-AZ DB clusters support **no copy operations** in AWS Backup (the docs table and footnote disagree, trust the footnote **(verify)**).
- **If** a rule takes backups **every 12 hours** starting at **13:00** but only one runs per day, **then** set the start time to **11:59 or earlier**. **This works because** AWS Backup evaluates the schedule between **00:00 and 23:59**, so a 12-hourly rule that starts later than 11:59 only runs **once a day**.
- **If** an hourly rule and a daily rule with **longer retention** have overlapping start windows, **then** expect **one backup**, kept under the **daily (longer retention) rule**, during the daily rule's window. **This works because** when rules in a plan overlap, AWS Backup takes a single backup and keeps it under the rule with the **longer retention**; the hourly rule only runs outside that window.
- **If** the AWS Glue Data Catalog must be recoverable, **then** keep it in **infrastructure as code (IaC)** or a scripted export. **This works because** AWS Backup does **not support** the Glue Data Catalog.
- **If** backup costs doubled after adding Amazon Elastic File System (EFS) to a plan, **then** remove the duplicate: either the **EFS automatic backup** or your own plan. **This works because** EFS automatic backups are already an AWS Backup plan (daily, 35-day retention) **(verify)**, and both keep **separate recovery points**, so you pay twice.

Verified from AWS docs on 2026-11-02 (pages used): Backup plan options and configuration; AWS Backup feature availability (by resource and by Region); AWS Backup quotas; Logically air-gapped vault; Restore testing; Audit Manager controls and remediation; aws.amazon.com/backup/pricing.

Unconfirmed (verify): API default and minimum values for start/completion windows; exact name of the state for jobs cancelled by the completion window; full backup job state list; prorated early-deletion wording; EFS automatic backup plan/vault names; S3 backup/restore managed policy names; ARN-per-selection quotas; service opt-in defaults per type; RDS retention behavior when AWS Backup takes over continuous backup; on-demand continuous backups; plan template names; DynamoDB advanced features being a Settings opt-in only; S3 noncurrent-version guidance; Keyspaces/ElastiCache/MemoryDB still unsupported; RDS Multi-AZ cluster copy row conflict in the docs table.

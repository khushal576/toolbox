# AWS Backup – 2. Vaults, Vault Lock, air-gapped vaults, copies and restores

Short notes. Each point is a fact you can be asked about.

## A. Backup vaults
- A **backup vault** is a regional container that organizes **recovery points**; each rule writes to one vault.
- **Default vault**: named `Default`, exists per Region; create more to separate environments, data classes or compliance needs.
- **Quota**: **300 vaults per Region per account** (standard + logically air-gapped combined, adjustable).
- **Quota**: **1,000,000 recovery points per vault** (adjustable).
- Each vault has a **KMS key** set **at creation** (cannot be changed later) **(verify immutability of the key choice)**.
- Vaults can have **tags** and one **vault access policy** (resource-based policy).
- **Vault notifications**: one SNS topic per vault for chosen events (file 3).
- **Deleting a vault**: only possible when it holds **no recovery points**.
- Vault types: **backup vault** (standard), **logically air-gapped vault**, and **restore access backup vault** (a view of a shared LAG vault, see section F).

## B. Encryption
- Every recovery point is **encrypted**; there is no unencrypted vault.
- **Key options**: the AWS managed key **`aws/backup`** or a **customer managed key (CMK)**.
- **Fully managed types** (S3, EFS, DynamoDB advanced, Aurora DSQL, Timestream, SAP HANA, VMs, EKS): backups are encrypted with the **vault key**, independent of the source key.
  - Why it matters: even unencrypted sources get encrypted backups, and a compromise of the source key does not expose backups.
- **Not fully managed types** (EBS, EC2, RDS, Aurora, FSx, DocumentDB, Neptune, Redshift...): the backup keeps the **source resource's encryption**.
  - Catch: an unencrypted EBS volume gives an unencrypted snapshot; encrypt the source or encrypt on copy **(verify copy re-encryption rules per type)**.
- **Copy encryption**: copies are encrypted with the **destination vault's key** where the type allows **(verify per type)**.
- **Cross-account copy needs a CMK**: **AWS managed keys cannot be shared** across accounts.
  - The CMK key policy must allow the destination account (and the copy role) to use it.
- **CMK benefits**: cross-account sharing, rotation control, CloudTrail audit of key use, ability to disable.
- **Trap**: disabling or scheduling deletion of the CMK makes its backups **unrecoverable**; protect key deletion with SCPs.

## C. Vault access policies
- Resource-based JSON policy on the vault; controls AWS Backup API actions on the vault and its recovery points.
- **Typical deny-delete policy**: `Effect: Deny`, `Principal: "*"`, actions `backup:DeleteRecoveryPoint`, `backup:UpdateRecoveryPointLifecycle`, `backup:PutBackupVaultAccessPolicy`, with a condition that exempts a **break-glass role** (`ArnNotEquals aws:PrincipalArn`).
- **Allow cross-account copy in**: allow `backup:CopyIntoBackupVault` for specific accounts or for the whole org with `aws:PrincipalOrgID`.
- **Source side**: copying out of a vault needs `backup:CopyFromBackupVault` on the source vault.
- **Audit Manager control** "Vaults prevent manual deletion of recovery points" checks this policy; it allows **up to 5 IAM roles** to delete.
- **Catch**: access policies only cover **AWS Backup ARNs**; for non-fully-managed types the underlying snapshot can also be reached through the service's own APIs, so add IAM/SCP denies there too **(verify)**.
- **Access policy ≠ immutability**: an admin can edit or remove a policy; only **Vault Lock (compliance)** is immutable.

## D. AWS Backup Vault Lock (WORM)
- **Vault Lock** makes a vault **write-once-read-many (WORM)**: recovery points cannot be deleted or have their retention shortened while the lock applies.
- **One lock per vault**; **no extra charge** (normal storage still billed).
- Assessed by **Cohasset Associates** for **SEC 17a-4(f), FINRA 4511(c) and CFTC 1.31(c)-(d)**.
- **Two modes**:
  - **Governance mode**: users with permission (`backup:DeleteBackupVaultLockConfiguration`) can **change or remove** the lock.
  - **Compliance mode**: after the **grace time** ends, the lock is **immutable**; **no user, root or AWS** can remove or change it while recovery points exist.
- **How the mode is chosen**: include **`ChangeableForDays`** → compliance mode; omit it → governance mode.
- **Grace time (cooling-off)**: `ChangeableForDays` **minimum 3 days (72 hours)**, **maximum 36,500 days**.
  - During grace time you can still update or delete the lock (test it first).
  - `LockDate` (from `DescribeBackupVault`) shows when the lock becomes immutable.
- **Retention bounds**: optional **`MinRetentionDays`** (min **1** day) and **`MaxRetentionDays`** (max **36,500** days).
  - **New backup and copy jobs** whose retention falls outside the bounds **fail**.
  - **Existing recovery points are not changed**; the lock enforces on new points, and existing points keep their lifecycle **(verify whether existing points become undeletable early)**.
- **"Always" retention trap**: recovery points with no expiry in a compliance-locked vault are kept **forever** and billed forever; check before grace ends.
- **Continuous backup trap**: continuous retention max is 35 days, so a `MinRetentionDays` above 35 makes continuous jobs into that vault fail.
- **Account closure**: a closed account is suspended **90 days**; if not reopened, AWS **deletes vault contents even if locked**.
- **Empty vault**: a compliance-locked vault can be deleted **only when empty**.
- **EBS caveat**: even with Vault Lock, EC2 APIs can still **share** (`ec2:ModifySnapshotAttribute`) or **change tier** (`ec2:ModifySnapshotTier`) of AWS Backup EBS snapshots.
  - Fix: deny those actions with IAM/SCP (exempt the backup role), turn on **EBS snapshot block public access**, encrypt source volumes.
- **AMI caveat**: **disabling an AMI** (`ec2:DisableImage`) can block EC2 restores; deny it with IAM/SCP.
- **Use cases**: ransomware resilience, regulatory retention (for example **7 years ≈ 2,557 days**), insider-threat protection.

## E. Vault Lock vs other locks
| Feature | Protects | Notes |
|---|---|---|
| **AWS Backup Vault Lock** | Recovery points in an AWS Backup vault | Governance or compliance mode; all supported resource types |
| **S3 Object Lock** | Individual S3 object versions | Governance/compliance + legal hold; needs versioning; for live data |
| **S3 Glacier Vault Lock** | Archives in an S3 Glacier (vault API) vault | Glacier vault policy lock; unrelated to AWS Backup |
- Exam trap: "Glacier Vault Lock" is **not** the feature for locking AWS Backup backups.
- S3 Object Lock protects the **source bucket**; Vault Lock protects the **backup copies**; you can use both.

## F. Logically air-gapped (LAG) vaults
- A **logically air-gapped vault** is a specialized vault with extra security and **cross-account sharing** for faster recovery (better RTO) after an incident.
- **Always locked in Vault Lock compliance mode** (built in).
- **Encryption**: **AWS owned key by default** (recommended), or optionally a **customer managed key** (preferably from another account).
  - Correction vs older notes: CMK is an option, not only AWS-owned keys.
  - Service-owned keys rotate every **90 days** by default; deleted when the empty vault is deleted.
- **Required settings**: **minimum retention** (integer **≥ 7 days**) and **maximum retention**.
  - Backups whose retention is outside the range **cannot be copied into** the vault.
- **How backups get in**: as a **copy action** in a backup plan or an **on-demand copy** from a standard vault (same/cross-Region, same/cross-account where the type supports copy).
  - **Primary backups to LAG vaults** (writing backups directly, keeping a single copy) are possible after **onboarding to Multi-party approval**.
- **Source encryption rule**: fully managed types can be encrypted with CMK or AWS managed key; **other types must use a CMK** (AWS managed key not supported).
- **Unsupported**: **unencrypted Aurora, DocumentDB and Neptune clusters**.
- **Supported types** (feature table): EC2, S3, EBS, Aurora, Aurora DSQL, EFS, FSx (all four), Storage Gateway, DocumentDB, Neptune (not in Jakarta), Timestream, Windows VSS, VMs, DynamoDB advanced, EKS (not in Bahrain/UAE).
  - **Not supported**: RDS DB instances, RDS Multi-AZ clusters, Redshift, Redshift Serverless, CloudFormation, standard DynamoDB, SAP HANA.
- **Sharing via AWS RAM**: share with **individual account IDs only** (inside or outside your organization); **not with an OU or whole organization**.
  - The invited account has **12 hours** to accept the RAM invitation.
  - Sharing account needs `ram:CreateResourceShare`.
- **Restore from a shared vault**: the shared account can **view and restore**, but **cannot copy** out; copies are made by the **owning account**.
- **Restore access backup vault**: what a recovery account sees for a shared LAG vault; it holds no recovery points itself and can be deleted (even in FAILED state) despite the lock.
- **Multi-party approval (MPA)** integration: an approval team can grant access to the vault's backups **even if the owning account is inaccessible or closed**, until the **post-closure period** ends.
- **Copy rules**: LAG → LAG copy is **on demand only** (not in a plan); LAG → standard vault copy requires the copy to be encrypted with a **CMK**.
- **EC2 trap**: if **EC2 Allowed AMIs** is on, add the alias **`aws-backup-vault`** to the allowlist or copies/restores fail ("Source AMI ... not found").
- **CloudTrail noise**: AMI copies into LAG temporarily grant `launchPermission`/`createVolumePermission` to a service-owned account; auto-remediation tools may wrongly revert these.
- **Deletion**: a LAG vault can be deleted only when empty; its key is deleted **7 days** after vault deletion.
- **Regions**: available in most AWS Backup Regions; not in China or GovCloud, and some newer Regions are limited **(verify current list)**.
- **Quotas**: concurrent copies into LAG per source account per destination Region: **20** for EBS, Aurora, DocumentDB, Neptune, Storage Gateway; **5** for FSx (not adjustable).
- **Pricing**: separate storage rate (docs example **$0.0575/GB-month** for EBS and EFS in Europe (Ireland)).
- **Audit Manager control** "Resources in a logically air-gapped vault" checks a copy exists in the time frame.
- **Vault Lock vs LAG**: Vault Lock (compliance) stops deletion **inside your account**; LAG adds **isolated, shareable recovery** from another account if your account or credentials are compromised.

## G. Legal holds
- A **legal hold** stops recovery points from being deleted (by lifecycle or by hand) until the hold is **released**.
- Selection by **vaults, resource types/IDs and creation date range** **(verify exact criteria)**.
- **Quota**: **50 legal holds per account**.
- Difference from Vault Lock: a hold is **temporary, removable and case-based**; Vault Lock is policy-wide and (in compliance mode) permanent.
- Catch: points under hold keep costing storage beyond their planned retention.

## H. Backup indexing and search
- **Backup search** finds files/objects inside **S3 and EBS** recovery points by name, path, size or date, then restores just those items.
- Requires a **backup index**: created by an **index action in a backup rule** or on demand.
- **Quotas**: **40 concurrent indexing jobs** per account (most Regions; adjustable), **5 per resource**, **1 concurrent on-demand indexing job**, **10 concurrent search jobs**, **5 concurrent export jobs**, **20 recovery points per search job**.
- **EBS file-level restore jobs**: **25 concurrent** (most Regions).
- **Pricing examples**: index creation **$0.20 per million files**, index storage **$0.02 per million items-month**, search **$0.07 per million items searched**, file-level restore **$0.03/GB**.

## I. Malware protection, backup tiering, access points
- **Malware protection**: AWS Backup integrates with **Amazon GuardDuty** to scan **EC2, EBS and S3** recovery points.
  - Scan types: **incremental** or **full**; results let you choose a **clean recovery point** to restore.
  - Needs a role trusted by `malware-protection.guardduty.amazonaws.com` with `AWSBackupGuardDutyRolePolicyForScans`, and `AWSBackupServiceRolePolicyForScans` on the selection role.
  - Quotas: **150 running scan jobs per account**, **5 per resource**, **1 per recovery point**.
  - Priced per **GB scanned** under GuardDuty pricing.
- **Backup tiering (S3 only)**: moves older S3 backup data to a **lower-cost warm tier**; believed to apply to data kept **≥ 60 days** **(verify threshold)**.
- **Access points (S3 only)**: read-only access to S3 backup data **without a full restore** **(verify details)**.

## J. Cross-Region and cross-account copy
- **Cross-Region copy**: copy recovery points to a vault in another Region, as a **copy action** or **on demand**; for DR and distance rules.
- **Cross-account copy** requirements:
  - Both accounts in the **same AWS Organization**.
  - **Cross-account backup turned on** in the management account's AWS Backup settings.
  - **Destination vault access policy** allows `backup:CopyIntoBackupVault` from the source.
  - **CMK** for non-fully-managed types, with key policy granting the destination.
- **Patterns**: **fan-in** (many workload accounts → one central backup account) and **fan-out** (central → several DR Regions/accounts).
- **Copies are independent recovery points** with their own lifecycle and lock.
- **Continuous backup copies become snapshots**; PITR is not available on copies.
- **Simultaneous cross-Region + cross-account copy in one action**: **RDS, Aurora, DocumentDB, Neptune**.
- **RDS and S3** copy from incremental backups; **Aurora and SAP HANA** copy from full backups.
- **No copy at all**: Redshift, Redshift Serverless, standard DynamoDB, RDS Multi-AZ DB clusters; **CloudFormation** has no cross-account copy.
- **China**: cross-Region copy only between **Beijing and Ningxia**; cross-account works within the same org.
- **GovCloud**: cross-Region copy only between **US-East and US-West** GovCloud Regions.
- **Opt-in Regions**: no cross-account copy for **CloudFormation and Timestream**; FSx cross-Region copy not in Bahrain/UAE; FSx ONTAP copy not in New Zealand or China.
- **Quotas**: **100 concurrent copy jobs** per account in a destination Region (then up to **5** more per vault); **30 concurrent cross-account copies** of the same resource to the same destination Region; **1 concurrent backup/copy job per resource**.
- **Cost**: cross-Region **data transfer** charged per GB (examples: **EBS $0.02/GB**, **EFS $0.04/GB**) plus storage in the destination.
- **Chained copies** (A → B → C) are possible for some types **(verify)**.

## K. Restores: general
- A restore runs as a **restore job** using **restore metadata** (`GetRecoveryPointRestoreMetadata`) that you can override.
- Needs an **IAM restore role** (default role with `AWSBackupServiceRolePolicyForRestores`) and **KMS access** to the backup key (and target key).
- **Most restores create a new resource**; you then repoint applications (DNS, connection strings).
- **Restore SLAs**: AWS Backup gives **no restore time SLA**; measure RTO with restore testing.
- **Copy tags on restore** is supported for some types; DynamoDB, S3, SAP HANA, VMs and Timestream do not support tag-on-restore.
- **Cold restore** is slower and has a cold restore price **(verify rate)**; EBS archive restore takes **24–72 hours** **(verify)**.
- **Warm restore** charges per GB for types billed by AWS Backup (example **$0.02/GB** for EFS and S3).

## L. Restores by resource
- **EBS**: new volume (choose AZ, type, KMS); file-level restore from indexed backups.
- **EC2**: new instance from the AMI; choose subnet, security groups, instance profile (role needs `iam:PassRole`).
- **S3**: restore whole bucket, prefixes or objects to the **original bucket or a new/other bucket**; PITR to a second.
- **EFS**: full or item-level restore to a **new file system** or into the **existing file system** (in a new recovery directory).
- **RDS / Aurora**: new DB instance/cluster; PITR to a chosen time; choose class, subnet group, security groups.
- **DynamoDB**: always a **new table**.
- **FSx**: new file system (ONTAP can restore a volume into an existing file system) **(verify)**.
- **Redshift**: new cluster, or **single table** restore into an existing cluster.
- **DocumentDB / Neptune**: new cluster.
- **VMware**: restore to VMware (on-premises or VMware Cloud on AWS) or as an EC2 instance; item-level = disk.
- **EKS**: restore cluster state and persistent volumes to an existing or new cluster; **1 restore job per target cluster**, **5 EKS restore jobs per account**.
- **CloudFormation stack**: restores a new stack with its nested resources.

## M. Restore testing
- **Restore testing** = scheduled, automated restores that prove backups work and measure **restore duration**.
- **Plan parts**: plan (name, frequency/cron, start time, time zone, **start within** window) + one selection **per resource type**.
- **Recovery point selection**: source vaults (all or specific), eligible window (**up to 365 days**), algorithm **latest or random**, optionally include **continuous (PITR) points**.
- **Resource selection**: all protected resources of a type, specific ARNs (**up to 30**), or wildcard + tag conditions (**up to 30**, `StringEquals`/`StringNotEquals`); ARNs and conditions cannot be mixed.
  - Tag conditions match the **latest recovery point's tags**, not the chosen recovery point.
- **At most one recovery point per protected resource** per run.
- **Inferred restore metadata**: AWS Backup infers parameters; override things like subnet, KMS key or FSx settings.
- **Retention before cleanup**: default delete right after the test; or keep **1–168 hours** to run validation.
- **Validation**: your code (often **Lambda triggered by EventBridge**) checks the restored resource and reports with **`PutRestoreValidationResult`**; validation is not run from the console.
- **Cleanup**: restored resources get tag **`awsbackup-restore-test`** (where tag-on-restore works) and are deleted; removing that tag breaks automatic deletion.
  - S3 test buckets are emptied with lifecycle rules; full deletion can take days.
- **Supported types**: Aurora, DocumentDB, DynamoDB, EBS, EC2, EFS, FSx (Lustre, ONTAP, OpenZFS, Windows with AWS managed AD), Neptune, RDS, Redshift, S3.
  - Not: Aurora DSQL, Timestream, VMs, SAP HANA, Storage Gateway, Redshift Serverless, CloudFormation, EKS.
- **Uses a service-linked role** `AWSServiceRoleForBackupRestoreTesting` plus the restore role you choose.
- **Quotas**: **100 plans**, **30 selections per plan**, **50 tags per plan**, start window **1–168 hours**, names **50 characters**.
- **Concurrent test restores per type** (example): EBS/EC2 **100**, Aurora/RDS/DocumentDB/Neptune/FSx/DynamoDB **40**, EFS/S3/Redshift **30**.
  - Over the limit → job `FAILED` with "unable to start within the specified start window" → widen the start window.
- **Pricing**: **$1.50 per recovery point tested** plus any restore/storage cost while the resource exists.
- **Audit**: Audit Manager control "**Restore time for resources meet target**" (`maxRestoreTime` minutes).
- Best practice: run tests in a **dedicated restore-testing account**.

## Troubleshooting (symptom → cause → fix)
- **Copy job fails "access denied"** → destination vault policy lacks `CopyIntoBackupVault` or KMS key policy lacks the destination → update both.
- **Cross-account copy fails for EBS/RDS** → source encrypted with AWS managed key → re-encrypt with a CMK and share the key.
- **Copy option missing for a resource** → type has no copy support (Redshift, standard DynamoDB, Multi-AZ cluster) → use native copy or advanced DynamoDB.
- **Copy into LAG vault rejected** → retention outside the LAG min/max, unencrypted Aurora/DocumentDB/Neptune, or AWS managed key on non-fully-managed type → fix retention or encryption.
- **EC2 restore from LAG fails "Source AMI not found"** → EC2 Allowed AMIs enabled → add `aws-backup-vault` alias.
- **New jobs fail after locking a vault** → rule retention outside `MinRetentionDays`/`MaxRetentionDays` → align rule retention.
- **Cannot delete recovery points** → compliance lock, legal hold, or deny in the vault policy → expected; wait for expiry or release the hold.
- **Cannot remove a governance lock** → missing `backup:DeleteBackupVaultLockConfiguration` or SCP deny → use an authorized role.
- **Locked vault costs keep growing** → "Always" retention points → cannot fix after grace; plan retention before locking.
- **Restore fails with KMS error** → restore role or key policy lacks access to backup/target key → grant the role.
- **Restore test fails "No default VPC"/"No subnets found"** → inferred metadata needs default VPC → override `SubnetId` (or `DBSubnetGroupName` for databases).
- **Restore test fails "IAM Role cannot be assumed"** → role trust lacks `backup.amazonaws.com` → fix trust policy.
- **Restore test resource not deleted** → `awsbackup-restore-test` tag removed → delete manually.
- **PITR restore not offered on the DR copy** → copies of continuous backups are snapshots → restore to snapshot time or copy more often.
- **Search finds nothing** → no backup index for those recovery points → add an index action to the rule.

## Scenarios: "If X → Y, because Z"
- If regulators require backups nobody can delete for 7 years → **compliance-mode Vault Lock with MinRetentionDays ≈ 2,557**, because after the grace time not even root can remove it.
- If you want deletion protection but a way out with approval → **governance-mode lock**, because privileged IAM can remove it.
- If you want to test a compliance lock before it becomes permanent → **set ChangeableForDays ≥ 3 and test during the grace time**, because you can still change or delete it then.
- If the production account may be fully compromised → **copy to a logically air-gapped vault shared via RAM to a recovery account**, because restore works from outside the compromised account.
- If the vault-owning account gets closed → **use Multi-party approval to regain access before the post-closure period ends**, because MPA works when the owner account is inaccessible.
- If you must share a LAG vault with the whole security OU → **share with each account ID**, because RAM sharing for LAG vaults supports only individual accounts.
- If backups must land in a central security account → **cross-account copy (fan-in) with a vault policy allowing the org and a CMK**, because AWS managed keys cannot be shared.
- If DR needs RDS backups in another Region and another account at once → **one copy action to a cross-Region, cross-account vault**, because RDS supports simultaneous copy.
- If a lawsuit requires preserving certain backups beyond retention → **legal hold**, because it blocks deletion until released.
- If you must find which backup holds `report.csv` in a large S3 or EBS backup → **backup index + search, then item-level restore**, because search scans the index, not the data.
- If you must prove backups are restorable every week → **restore testing plan with Lambda validation via EventBridge**, because it restores, validates, records duration and cleans up.
- If ransomware may have reached recent backups → **malware scan recovery points and restore the latest clean one**, because GuardDuty marks scan results per recovery point.
- If EBS snapshots in a locked vault could still be shared publicly → **SCP deny `ec2:ModifySnapshotAttribute` plus EBS block public access**, because Vault Lock does not stop EC2 APIs.
- If an S3 bucket must be both immutable live and protected by backups → **S3 Object Lock on the bucket plus Vault Lock on the backup vault**, because they protect different copies.

Verified from AWS docs on 2026-11-02 (pages used): Logically air-gapped vault; Restore testing; AWS Backup quotas; AWS Backup feature availability; Backup plan options and configuration (copy lifecycle, malware scanning); Audit Manager controls; aws.amazon.com/backup/pricing.

Unconfirmed (verify): vault key immutability after creation; copy re-encryption behavior per non-fully-managed type; access-policy reach for non-fully-managed snapshots; Vault Lock effect on existing recovery points beyond "not changed"; legal hold selection criteria; backup tiering 60-day threshold; access point details; LAG Region list; chained copies; cold restore price and EBS archive restore time; FSx ONTAP volume restore into existing file system; Cohasset regulation wording carried from older notes.

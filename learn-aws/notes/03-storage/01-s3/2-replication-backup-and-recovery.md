# S3 – 2. Replication, backup, recovery and disaster recovery

Short notes. Each point is a fact you can be asked about.

## A. Why replicate
- Replication = automatic, asynchronous copy of objects from a source bucket to one or more destination buckets.
- Destination can be in the same account or another account, the same Region or another Region.
- Reasons: compliance (data far away), lower latency for far users, disaster recovery, log aggregation, prod-to-test copies, data sovereignty, keep a copy under another owner.
- It is not a backup by itself. A bad overwrite replicates too. Combine with versioning/Object Lock.

## B. Types of replication
- Live replication: copies new and updated objects as they are written.
- On-demand replication: S3 Batch Replication, copies objects that already existed.
- CRR (Cross-Region Replication): destination in a different Region. Has inter-Region transfer cost.
- SRR (Same-Region Replication): destination in the same Region. No data transfer charge.
- Two-way (bi-directional) replication: two rules, one each way, with replica modification sync on.
- Multiple destinations are allowed from one source.

## C. When to use CRR
- Compliance that needs distance beyond AZs.
- Lower latency by keeping copies near users.
- Compute clusters in two Regions analyzing the same objects.
- Disaster recovery to another Region.

## D. When to use SRR
- Aggregate logs from many buckets/accounts into one bucket.
- Live copy between production and test accounts.
- Data sovereignty: need multiple copies in separate accounts inside one country/Region.
- Give another account its own copy with its own owner.

## E. Requirements (very testable)
- Versioning must be on for both source and destination buckets.
- If you try to suspend versioning on the source, you must remove the replication config first.
- If versioning is turned off on the destination, replication fails (status FAILED).
- S3 needs an IAM role to read the source and write the destination (trust: `s3.amazonaws.com`).
- Both Regions must be enabled for the accounts involved (opt-in Regions need enabling).
- Cross-account: destination bucket owner must grant the source account permission with a bucket policy.
- The source bucket owner must have permission to read the objects (and ACLs). If someone else owns an object (older ACL model), they must grant the bucket owner READ and READ_ACP.
- If the source has Object Lock, the destination must have Object Lock too.
- The replication role needs `s3:GetObjectRetention` and `s3:GetObjectLegalHold` when Object Lock is used.
- Destination bucket cannot be Requester Pays in a cross-account setup.
- Setting up replication on an Object Lock bucket requires CLI, API or SDK (not the console, per docs).

## F. What gets replicated
- Objects created after you add the replication rule.
- Unencrypted objects.
- SSE-S3 objects. SSE-KMS objects (if you turn that on and give KMS permission). SSE-C objects.
- Object metadata and tags.
- Object ACL updates (unless you change the replica owner).
- Object Lock retention info (applies the same retention to replicas).
- Version-aware: it replicates specific versions with their version IDs.
- Replica can use a different storage class from the source (for example straight into Glacier Flexible).
- Owner override: replica can be owned by the destination bucket's account.

## G. What does NOT get replicated
- Objects that existed before the rule. Use Batch Replication.
- Objects that are themselves replicas from another rule (no chaining: A→B and B→C does not copy A's data to C). Use Batch Replication to do it.
- Objects already replicated to a different destination earlier.
- Objects in Glacier Flexible, Deep Archive, and Intelligent-Tiering Archive/Deep Archive tiers (restore and copy to another class first).
- Version-specific deletes (`DELETE ?versionId=`). Protects against malicious deletion.
- Delete markers by default (newer rule format). You can turn on delete marker replication for non-tag-based rules.
- With the old V1 format (no Filter element), user-made delete markers are replicated, but lifecycle-made ones are not.
- Delete markers added from another account are not replicated by default.
- Lifecycle actions (expirations, transitions) are not replicated. Configure lifecycle on both buckets if needed.
- Bucket-level subresource changes (lifecycle config, notification config) are not copied.
- Objects the bucket owner cannot read.
- Tag-based live rules only match objects tagged in the same PutObject call. Tagging later does not replicate (use Batch Replication).
- Annotation deletions are not replicated.

## H. Delete behavior (common trap)
- Simple delete in source → delete marker. By default not copied (V2 rules), so destination keeps the object visible.
- Delete a specific version in source → destination version stays, on purpose.
- So replication alone does not mirror deletes. That is a feature for protection.
- To mirror delete markers: enable delete marker replication on the rule (not on tag-filtered rules).

## I. Encryption and replication
- SSE-S3 objects replicate with no special setup.
- SSE-KMS objects only replicate if you enable it in the rule and name a KMS key in the destination Region.
- The replication role needs `kms:Decrypt` on the source key and `kms:Encrypt` (and generate data key) on the destination key.
- Cross-Region replication of KMS data requires a key in the destination Region (a multi-Region key can help, but the object is still re-encrypted).
- SSE-C objects replicate; the key must be supplied in the way docs describe (verify details if needed).

## J. Replication Time Control (RTC)
- RTC makes replication predictable: 99.99% of new objects replicated within 15 minutes, backed by an SLA.
- Costs extra. Gives replication metrics and events (bytes pending, operations pending, replication latency).
- Not available for Batch Replication.
- Without RTC, replication usually takes seconds to minutes but can take hours; large objects take longer. No SLA.
- Use RTC when compliance needs a time guarantee.

## K. Batch Replication
- On-demand job to replicate: existing objects, previously failed objects (status FAILED), objects already replicated to old destinations, replicas of replicas.
- Run from S3 Batch Operations. Uses an Inventory/manifest (S3 can create it for you).
- Can limit by creation date or status.
- Batch Replication cannot re-replicate objects deleted by version ID from the destination. Use a Batch Copy in place on the source to create new versions that replicate.
- Replicating an Intelligent-Tiering object counts as access.

## L. Replica modification sync
- Syncs metadata changes (tags, ACLs, Object Lock info) from replica back to source.
- Needed for two-way replication so metadata stays aligned.
- Used before setting up Multi-Region Access Point failover.

## M. Replication status
- On source objects: `PENDING`, `COMPLETED`, `FAILED`.
- On the replica: `REPLICA`.
- Find failures with S3 Inventory, replication metrics (CloudWatch), replication failure events (S3 Event Notifications), or HEAD object.
- Common failure causes: missing IAM permission, missing destination bucket policy (cross-account), destination versioning off, KMS permission missing, destination Object Lock missing, destination bucket Requester Pays, Region not enabled.

## N. Multi-Region Access Points (MRAP)
- One global endpoint that routes to the closest bucket among several Regions (uses AWS Global Accelerator).
- Use for active-active or active-passive multi-Region apps and failover.
- Needs buckets in different Regions with versioning. Use two-way replication rules for failover so writes made in the failover bucket flow back.
- You control failover with routing controls (active/passive), and can use replication metrics to decide when to fail over.
- Costs extra (routing and data transfer acceleration).

## O. Backup options for S3
- Versioning: best first defense against accidental deletes and overwrites.
- Object Lock: stops deletion for a period (ransomware and insider protection).
- Replication (CRR/SRR) to another bucket, ideally another account (limits damage if an account is breached).
- AWS Backup for S3: central backup plans. Continuous backups allow point-in-time restore (up to 35 days, needs versioning). Periodic backups are also available. Supports cross-Region and cross-account copies and Vault Lock. (Verify exact limits before relying on them.)
- S3 Batch Operations Copy to copy data to another bucket on demand.
- Move old data to Glacier classes with lifecycle (cheap long-term copy).
- For backups of other data into S3: use Standard-IA/Glacier classes and lifecycle.
- Backup of bucket settings (policy, lifecycle) is done with IaC (CloudFormation/Terraform), not with S3 itself.

## P. Restoring data
- Deleted object in versioned bucket: remove the delete marker, or copy a specific old version back.
- Overwritten object: copy an older version to become the latest version.
- Glacier Instant Retrieval: just GET (milliseconds).
- Glacier Flexible and Deep Archive: call RestoreObject first. You get a temporary Standard copy for the number of days you choose. The archived object stays archived.
- Restore options for Flexible Retrieval (and Intelligent-Tiering Archive Access): Expedited 1–5 minutes (objects under 250 MB), Standard 3–5 hours, Bulk 5–12 hours.
- Restore options for Deep Archive (and Intelligent-Tiering Deep Archive Access): Standard within 12 hours, Bulk within 48 hours. No Expedited.
- Via Batch Operations, Standard restores for Flexible start in minutes and finish in 3–5 hours; Deep Archive about 9–12 hours (up to 1–2 PB/day throughput).
- Bulk retrievals are free for Glacier Flexible Retrieval and Intelligent-Tiering. Standard retrieval is free for Intelligent-Tiering.
- Expedited is a premium. Provisioned capacity (units) guarantees Expedited availability: each unit gives at least 3 expedited retrievals every 5 minutes and up to 300 MB/s.
- Restore request rate limit is about 1,000 transactions per second per account. Use Batch Operations to restore many objects.
- Large objects over 5 TB restore at up to 300 MB/s (a 50 TB object can take up to 48 hours).
- Only one restore request at a time per object.
- While restored, you pay for the archive storage and for the temporary Standard copy.
- To change an archived object's class: restore it, then copy it over with the new class (the console does not support copy for restored Glacier objects; use CLI/SDK).

## Q. Disaster recovery patterns
- Backup and restore: cheapest. Versioning + lifecycle + occasional copy to another Region. Slowest recovery.
- Pilot light / warm standby: CRR to a second Region; apps in the second Region start on failover.
- Active-active: CRR both ways + Multi-Region Access Point; apps in both Regions.
- RPO (data loss allowed): CRR without RTC is "minutes to hours"; RTC gives about 15 minutes; two-way adds sync.
- RTO (time to recover) depends on app failover, DNS or MRAP routing change, and cache warming.
- Put the DR copy in a different account with a different KMS key and Object Lock for ransomware safety.

## R. Deleting data for legal/business reasons
- Right to erasure: delete the object version(s) and all copies (replicas, backups, Glacier, Inventory/Athena derived data).
- Versioned bucket: you must delete all versions, not just add a delete marker. Replication will not delete destination versions for you.
- Lifecycle expiration helps meet retention limits (delete after N days). Add noncurrent version expiry.
- Object Lock blocks deletion until retention ends (compliance mode: not even root). Plan retention carefully.
- Tables (Iceberg): use DELETE/MERGE and snapshot expiration so old data files disappear (see S3 Tables file).

## S. Scenarios (if → then, because)
- If you need a live copy in another Region for DR → CRR with versioning on both, because async replication copies new objects.
- If old objects must also be copied → run Batch Replication once, because live replication only copies new objects.
- If compliance requires replication within 15 minutes → enable RTC, because it carries an SLA.
- If logs from many accounts must land in one bucket → SRR, because it is same-Region and has no transfer fee.
- If a user deletes an object and DR still shows it → expected, delete markers are not replicated by default (V2).
- If you need deletes mirrored → turn on delete marker replication (non-tag rule).
- If a version was deleted by mistake in source but must stay safe → destination still has it, because version deletes are not replicated.
- If replication shows FAILED → check destination versioning, IAM role, destination bucket policy, KMS permissions, Object Lock on destination, then Batch Replication to retry.
- If objects are encrypted with SSE-KMS and not replicating → enable KMS replication in the rule and give the role KMS permissions on both keys.
- If objects are in Glacier Flexible and do not replicate → restore them and copy to another class first.
- If A→B and B→C is set up and C stays empty → no chaining; replicate A→C directly or use Batch Replication.
- If you need ransomware protection → versioning + Object Lock + replication to another account.
- If you need global low-latency access with failover → Multi-Region Access Point + two-way replication.
- If you need a point-in-time restore of a bucket → AWS Backup continuous backup (versioning required).
- If you need to restore millions of archived objects → S3 Batch Operations restore, because API restore rate is limited.
- If an urgent small restore must finish in minutes → Glacier Flexible Expedited (buy provisioned capacity if it must be guaranteed).
- If you need to delete a person's data everywhere → delete all versions in primary, replicas, backups, and clean Inventory/derived tables.
- If you replicate to Glacier Deep Archive directly → set destination storage class in the rule, because it saves a lifecycle step.
- If data may not leave a country → use SRR within the Region and an SCP denying other Regions, because CRR could cross borders.

## Verified from AWS docs on 2026-10-02
Replication overview, what is/isn't replicated, requirements, restore tiers were read from current AWS pages. Not re-checked: AWS Backup for S3 limits, MRAP price and failover details, SSE-C replication details (verify).

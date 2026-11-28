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
- **If** you need a live copy of a bucket in another Region for disaster recovery (DR), **then** use **S3 Cross-Region Replication (CRR)** with **versioning** turned on in both the source and the destination bucket. S3 needs an Identity and Access Management (IAM) role to read the source and write the destination. **This works because** replication copies new and updated objects to the other bucket automatically and asynchronously. The catch: it is not a backup by itself, since a bad overwrite is replicated too, and CRR adds inter-Region transfer cost.
- **If** objects that existed before the rule must also be copied, **then** run **S3 Batch Replication** once. **This works because** live replication only copies objects created after the rule is added, while Batch Replication is an on-demand S3 Batch Operations job that copies existing objects from a manifest.
- **If** compliance requires replication within **15 minutes**, **then** turn on **S3 Replication Time Control (RTC)**. **This works because** RTC replicates **99.99%** of new objects within 15 minutes and is backed by a service level agreement (SLA). Without RTC, replication usually takes seconds to minutes but can take hours. RTC costs extra and does not work with Batch Replication.
- **If** logs from many accounts must land in one bucket, **then** use **S3 Same-Region Replication (SRR)** from each source bucket into the central bucket. **This works because** SRR copies within the same Region, so there is **no data transfer charge**. Each bucket needs versioning, and the destination bucket policy must allow the other accounts.
- **If** a user deletes an object and the DR copy still shows it, **then** this is **expected**. **This works because** a simple delete adds a **delete marker**, and with the newer (V2) rule format delete markers are **not replicated by default**, so the destination keeps the object visible.
- **If** you need deletes mirrored to the destination, **then** turn on **delete marker replication** in the replication rule. **This works because** delete markers are then copied too. It works only on rules that do **not** filter by tags.
- **If** a version was deleted by mistake in the source but must stay safe, **then** nothing extra is needed: the **destination still has it**. **This works because** version-specific deletes (`DELETE ?versionId=`) are never replicated, on purpose, to protect against malicious deletion.
- **If** replication shows **FAILED**, **then** check **versioning** on the destination, the replication **IAM role**, the destination **bucket policy** (cross-account), **AWS Key Management Service (KMS)** permissions, and **Object Lock** on the destination; also that the destination is not Requester Pays and the Region is enabled. Then run **S3 Batch Replication** to retry. **This works because** these are the common failure causes, and Batch Replication can re-copy objects with status FAILED.
- **If** objects encrypted with **SSE-KMS** (server-side encryption with AWS Key Management Service keys) are not replicating, **then** enable KMS replication in the rule, name a KMS key in the destination Region, and give the replication role `kms:Decrypt` on the source key and `kms:Encrypt` (and generate data key) on the destination key. **This works because** SSE-KMS objects only replicate when you turn this on; SSE-S3 objects need no setup.
- **If** objects in **S3 Glacier Flexible Retrieval** do not replicate, **then** **restore** them and **copy** them to another storage class first. **This works because** replication skips objects in Glacier Flexible Retrieval, Deep Archive, and the Intelligent-Tiering Archive tiers.
- **If** you set up A→B and B→C and bucket C stays empty, **then** replicate **A→C directly**, or use **S3 Batch Replication**. **This works because** replication does **not chain**: objects that are replicas from another rule are not replicated again. Batch Replication can copy replicas of replicas.
- **If** you need ransomware protection, **then** combine **versioning**, **S3 Object Lock** and **replication to another account**. Versioning keeps old copies after a delete or overwrite, and Object Lock stops deletion for a set period. **This works because** a copy in a separate account, ideally in another Region with a different AWS Key Management Service (KMS) key, limits the damage if one account is breached.
- **If** you need global low-latency access with failover, **then** use a **Multi-Region Access Point (MRAP)** with **two-way replication**. An MRAP is one global endpoint that routes requests to the closest bucket among several Regions, using AWS Global Accelerator. **This works because** two-way replication makes writes made in the failover bucket flow back, and you control failover with routing controls (active/passive). MRAP costs extra.
- **If** you need a **point-in-time restore** of a bucket, **then** use **AWS Backup** **continuous backup** for S3. **This works because** continuous backups let you restore to a point in time up to **35 days** back (verify). The bucket must have **versioning** on.
- **If** you must restore **millions of archived objects**, **then** use an **S3 Batch Operations** restore job. **This works because** the restore API is limited to about **1,000 requests per second** per account, while Batch Operations handles the requests for you, at up to 1–2 PB per day.
- **If** an urgent small restore must finish in **minutes**, **then** use an **Expedited** restore from **S3 Glacier Flexible Retrieval** (1–5 minutes, objects under 250 MB), and buy **provisioned capacity** if it must be guaranteed. **This works because** each provisioned capacity unit gives at least 3 Expedited retrievals every 5 minutes and up to 300 MB/s. Deep Archive has no Expedited option.
- **If** you must delete a person's data everywhere, **then** delete **all object versions** in the primary bucket, in **replicas**, in **backups** and Glacier copies, and clean **S3 Inventory** and other derived (Athena) tables. **This works because** a simple delete in a versioned bucket only adds a delete marker, and replication does not delete destination versions for you. Object Lock blocks deletion until retention ends.
- **If** replicated data should go straight to **S3 Glacier Deep Archive**, **then** set the **destination storage class** in the replication rule. **This works because** a replica can use a different storage class from the source, so you skip a separate lifecycle step.
- **If** data may not leave a country, **then** use **S3 Same-Region Replication (SRR)** inside that Region, plus a **Service Control Policy (SCP)** that denies other Regions. **This works because** Cross-Region Replication (CRR) could copy data across the border, while a bucket's data stays in its Region unless you copy or replicate it.

## Verified from AWS docs on 2026-10-02
Replication overview, what is/isn't replicated, requirements, restore tiers were read from current AWS pages. Not re-checked: AWS Backup for S3 limits, MRAP price and failover details, SSE-C replication details (verify).

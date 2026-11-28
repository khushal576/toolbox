# S3 – 1. Basics, storage classes, lifecycle, versioning, Object Lock

Short notes. Each point is a fact you can be asked about.

## A. What S3 is (and is not)
- S3 = object storage. Store and fetch whole files (objects) by name over an HTTPS API.
- Designed for 11 nines (99.999999999%) durability.
- Total storage is unlimited. One object is max 5 TB.
- Not a file system: no real folders, no file locking, no in-place edit of part of a file.
- Not a database: no queries, no indexes, no transactions across objects.
- Not a block disk: you cannot install an OS on it or mount it like EBS (Mountpoint for S3 can mount read-heavy; it is not a full file system).
- Pick S3 for: data lakes, backups, archives, logs, media, static websites, ML datasets, exports.
- Avoid S3 for: frequent small edits to one file, millisecond random updates (use DynamoDB), shared POSIX file system (use EFS/FSx), relational data.
- Durability is not a backup. A mistaken delete or overwrite is executed as asked. Use versioning/Object Lock/replication for protection.

## B. Buckets
- Bucket = container for objects. Name is globally unique across all AWS accounts.
- Bucket name: 3 to 63 chars, lowercase letters, numbers, hyphens (for general purpose buckets).
- A bucket lives in one Region. Data stays there unless you copy/replicate it.
- Default account limit is 10,000 general purpose buckets (soft limit; verify current default).
- Bucket types: general purpose (normal), directory (S3 Express One Zone), table (S3 Tables), vector (S3 Vectors).
- New buckets: private, Block Public Access on, ACLs disabled (Object Ownership = bucket owner enforced), SSE-S3 default encryption.
- Bucket settings are per bucket: versioning, lifecycle, replication, encryption, policy, events, logging.
- Replication, lifecycle and event settings are not copied from source to destination bucket by replication.
- You cannot rename a bucket. To rename, create a new one and copy.
- A bucket must be empty before deletion (delete all versions and delete markers too).

## C. Objects
- Object = key + data + metadata + optional tags + version ID + storage class.
- Key = full name, up to 1,024 bytes. Case sensitive.
- Prefix = the beginning of a key (for example `logs/2026/10/`). It is just text, not a folder.
- The console shows "folders" using the `/` character. A console "folder" is a zero-byte object ending in `/`.
- System metadata: size, content type, last modified, storage class, encryption. User metadata: your key-values, set at upload.
- User metadata cannot be changed after upload without copying the object onto itself.
- Tags: up to 10 per object. Can be changed any time. Used for lifecycle filters, ABAC, cost tracking.
- Changing an object = upload a new copy with the same key. Without versioning the old data is gone.
- Renaming an object = copy to the new key, then delete the old one.
- ETag is not always an MD5 hash (differs for multipart or KMS-encrypted objects). Do not use it as a checksum for those.
- Use additional checksums (CRC32, CRC32C, SHA-1, SHA-256) to verify upload integrity.

## D. Consistency
- S3 gives strong read-after-write consistency for PUT, DELETE and LIST, in all Regions, no extra cost.
- After a successful write, the next read or list sees it right away.
- Old advice "eventual consistency for overwrite and delete" is out of date.
- When you enable versioning on a bucket for the first time, AWS suggests waiting about 15 minutes before writes, because the change spreads and you can see short 404 errors.

## E. Uploading and reading
- Single PUT: up to 5 GB.
- Above 5 GB you must use multipart upload. AWS recommends it from about 100 MB.
- Multipart: parts are 5 MiB to 5 GiB (last part can be smaller), up to 10,000 parts, max 5 TB total.
- Multipart benefits: parallel upload, retry only failed parts, upload while data is still being produced.
- Incomplete multipart uploads keep costing storage. Add a lifecycle rule `AbortIncompleteMultipartUpload` (for example after 7 days).
- Byte-range GET: read only part of an object (used by Parquet readers to read the footer). Speeds up and saves bytes.
- Pre-signed URL: temporary link to one object (GET or PUT). Works with the permissions of whoever signed it. Expires.
- CopyObject: server-side copy up to 5 GB in one call. Larger copies need multipart copy (UploadPartCopy).
- HEAD request returns details without the data (cheap check if an object exists).
- LIST returns up to 1,000 keys per call. Large lists need pagination. LIST on huge buckets is slow and costs per request (use Inventory instead).

## F. Storage classes (verified in AWS docs 2026-10-02)
| Class | AZs | Min duration | Min billed size | Retrieval | Typical use |
|---|---|---|---|---|---|
| Standard | 3+ | none | none | ms | hot, frequent access |
| Intelligent-Tiering | 3+ | none | none* | ms (main tiers) | unknown/changing access |
| Standard-IA | 3+ | 30 d | 128 KB | ms + per-GB fee | about monthly access |
| One Zone-IA | 1 | 30 d | 128 KB | ms + per-GB fee | re-creatable, monthly |
| Glacier Instant Retrieval | 3+ | 90 d | 128 KB | ms + per-GB fee | quarterly access archive |
| Glacier Flexible Retrieval | 3+ | 90 d | none (+40 KB metadata) | minutes to hours (restore) | yearly archive |
| Glacier Deep Archive | 3+ | 180 d | none (+40 KB metadata) | hours (restore) | cold compliance archive |
| Express One Zone | 1 | none | none | single-digit ms | hot, latency-sensitive |
\*Intelligent-Tiering: objects under 128 KB are not monitored and stay in the frequent tier.
- Durability is 11 nines for all classes. Availability: Standard 99.99%, IA/Intelligent/Glacier IR 99.9%, One Zone-IA 99.5%, Express One Zone 99.95%.
- All classes except One Zone-IA and Express One Zone survive the loss of an entire AZ.
- IA and Glacier classes charge a per-GB retrieval fee. If you read the data often, Standard is cheaper overall.
- Delete or move an object early and you still pay for the rest of the minimum duration.
- Reduced Redundancy Storage is old. Never choose it.
- Glacier Flexible and Deep Archive add about 40 KB per object: 8 KB billed at Standard price and 32 KB at the Glacier price. Many tiny archived objects get expensive. Bundle small files first.
- Glacier objects are still S3 objects. You use the S3 API. They are not in the separate old Glacier vault service.

## G. Intelligent-Tiering in detail
- Automatic tiers: Frequent Access, then Infrequent Access (30 days no access), then Archive Instant Access (90 days).
- Optional tiers you turn on: Archive Access (90+ days) and Deep Archive Access (180+ days). These need a restore before reading.
- No retrieval fee. A small monthly monitoring and automation fee per object.
- Access moves an object back to Frequent Access.
- Standard retrieval from its Archive tiers is free. Bulk retrieval from Archive Access is free.
- Replicating or copying an Intelligent-Tiering object counts as access and moves the source object back up.
- Good for data lakes where nobody knows which partitions will be read.
- Not worth it for tiny objects or for data you know is always hot or always cold.

## H. Express One Zone and directory buckets
- Single AZ that you choose, single-digit millisecond latency. Best next to your compute (same AZ).
- Request cost is lower than Standard (docs say about 80% lower); storage price per GB is higher.
- Uses directory buckets (a different bucket type). Zonal endpoints for object calls, Regional endpoint for bucket calls.
- Auth uses `CreateSession` (temporary session credentials valid about 5 minutes). SDKs handle it.
- Always encrypted with SSE-S3; SSE-KMS also supported. SSE-C and DSSE-KMS are not supported.
- Block Public Access is always on and cannot be changed. ACLs are not supported.
- Access control boundary is the bucket only (no prefix or tag level controls).
- Server access logs are not supported. CloudTrail data events are.
- Access from a VPC with a gateway endpoint, no extra charge.
- Use for ML training data, interactive analytics, many small random reads. Do not use as the only copy of important data (one AZ).

## I. How to pick a class (decision order)
- Need it in milliseconds? No and it is a true archive → Glacier Flexible or Deep Archive.
- Access pattern unknown or changing → Intelligent-Tiering.
- Hot, read often → Standard.
- Read about monthly, needs ms, important data → Standard-IA.
- Same but can re-create it → One Zone-IA.
- Read about quarterly but needs ms → Glacier Instant Retrieval.
- Hot and needs the lowest latency → Express One Zone.
- Rare read, can wait minutes to hours → Glacier Flexible Retrieval.
- Almost never read, can wait up to about 12 hours → Deep Archive.
- Many small files → combine them first. IA and archive classes punish small objects.
- Storage Class Analysis can suggest when to move Standard data to IA (needs about 30 days of data).

## J. Lifecycle rules
- Lifecycle rule = automatic action by object age. Two types: Transition (change class) and Expiration (delete).
- Scope a rule by prefix, tags, or object size (`ObjectSizeGreaterThan`, `ObjectSizeLessThan`), or the whole bucket.
- Transitions work as a waterfall, downward only. Standard → IA, Intelligent-Tiering, One Zone-IA, Glacier IR, Glacier Flexible, Deep Archive.
- Standard-IA → Intelligent-Tiering, One Zone-IA, Glacier IR/Flexible/Deep Archive.
- One Zone-IA and Glacier IR → Glacier Flexible or Deep Archive. Glacier Flexible → Deep Archive only.
- You cannot go back up with lifecycle. Deep Archive is one-way. To go back: restore, then copy into the new class.
- Objects under 128 KB are not transitioned by default (since September 2024). Add an object size filter to allow it. Older configs keep the old behavior until edited.
- You cannot chain transitions in one rule before the first class's minimum duration passes (for example Glacier IR 90 days means the next transition at 94+ days).
- Early move or delete still charges the remaining minimum duration.
- Transitions to Glacier Flexible/Deep Archive happen asynchronously. Billing at the new rate starts when the rule date is reached, even if the physical move is a bit later.
- Each transition is a billed request. Moving millions of tiny objects can cost more than it saves.
- Expiration deletes current objects (unversioned buckets) or adds a delete marker (versioned buckets).
- Rules for versioned buckets: `NoncurrentVersionTransition`, `NoncurrentVersionExpiration` (can keep N newer noncurrent versions).
- `ExpiredObjectDeleteMarker` cleanup removes delete markers that have no versions left.
- `AbortIncompleteMultipartUpload` frees leftover parts.
- Lifecycle runs once a day (asynchronous); expired objects stop being billed when expired even before physical deletion.
- Tag-based rules are evaluated daily and re-checked when the action runs; removing a tag late may not stop the action.
- Rule changes can take up to about 15 minutes to take effect.
- Lifecycle does not act on object access. For access-based tiering use Intelligent-Tiering.
- Can be notified of lifecycle actions with S3 Event Notifications (lifecycle expiration and transition events).
- Replication does not copy lifecycle actions. Set the same lifecycle on the destination if you want it.
- Objects with replication status Pending or Failed cannot be transitioned in versioned buckets.

## K. Versioning
- Keeps every version of an object. Three bucket states: unversioned (default), enabled, suspended.
- Once enabled, you can suspend but never go back to unversioned.
- Overwrite (PUT) creates a new version. Old one becomes noncurrent.
- Delete (without version ID) adds a delete marker. The object looks gone (GET returns 404) but all versions remain.
- Delete with a version ID permanently deletes that version. No delete marker.
- To restore a deleted object: delete the delete marker (or copy an older version to become current).
- Each version is a full copy, billed fully. Versions of big objects add cost fast.
- Pair versioning with lifecycle to expire noncurrent versions.
- Objects that existed before enabling keep version ID `null`.
- MFA Delete: needs MFA to permanently delete a version or change versioning state. Only the root user can enable it, via CLI/API.
- Versioning is required for replication and Object Lock.
- Actions that only change tags or ACLs do not create a new version. CopyObject and PUT do.
- Millions of versions of one key can cause 503 errors on PUT/DELETE for that key.
- Versioning protects from accidental delete/overwrite. It does not protect from someone with permission to delete versions, unless MFA Delete or Object Lock is used.

## L. Object Lock (WORM)
- Write Once Read Many. Prevents deleting or overwriting an object version for a set time or forever.
- Works only on buckets with versioning. Enable at bucket creation (can be enabled on existing buckets with support help via API in newer behavior; verify).
- Protects a specific version, not the key. New versions and delete markers can still be added.
- Retention period: fixed (retain-until date) or variable (event hold plus duration, newer feature).
- Governance mode: most users cannot delete or change; users with `s3:BypassGovernanceRetention` (and the bypass header) can.
- Compliance mode: nobody, not even root, can delete or shorten retention. The only way out is deleting the AWS account.
- Legal hold: no end date; stays until removed by someone with `s3:PutObjectLegalHold`. Independent of retention.
- An object can have retention, legal hold, both, or neither.
- You can extend a retention period but never shorten it in compliance mode.
- Bucket default retention applies to new objects unless the PUT sets its own.
- Permanent delete of a locked version returns 403. A simple delete just adds a delete marker.
- Replication copies lock settings; destination bucket must also have Object Lock enabled. The replication role needs `s3:GetObjectRetention` and `s3:GetObjectLegalHold`.
- Assessed by Cohasset for SEC 17a-4, CFTC and FINRA.
- Glacier Vault Lock is the similar feature for old Glacier vaults, not for S3 objects.

## M. Scenarios (if → then, because)
- **If** logs are read often for 30 days, rarely until 1 year, and must be kept for 7 years, **then** use one **S3 Lifecycle rule**. Logs start in **S3 Standard**. At **day 30** they move to **S3 Standard-Infrequent Access (Standard-IA)**, which is cheaper to store but charges a small fee per read; if reads are even rarer, move them to **S3 Glacier Instant Retrieval** at **day 90** instead. At **day 365** they move to **S3 Glacier Deep Archive**, the cheapest class, which needs a restore of hours before reading. At **7 years** the rule **expires** (deletes) them. **This works because** Lifecycle moves objects by **age**, and here age tells you how often logs are read. Moves only go **downward**, and deleting or moving before a class's minimum period (30, 90 or 180 days) still charges the remaining days.
- **If** you cannot predict how often objects will be read and you want no manual work, **then** use **S3 Intelligent-Tiering**. It watches each object and moves it by itself: to the Infrequent Access tier after **30 days** with no access, and to Archive Instant Access after **90 days**; any read moves it back to Frequent Access. **This works because** there is **no retrieval fee**, only a small monthly monitoring fee per object. The catch: objects under **128 KB** are not monitored and stay in the frequent tier, so it is not worth it for tiny objects.
- **If** you can re-create the data and read it about once a month, **then** use **S3 One Zone-Infrequent Access (One Zone-IA)**. It keeps data in **one Availability Zone (AZ)** instead of three or more, so it is cheaper, and reads still take milliseconds with a per-GB fee. **This works because** losing that one AZ is acceptable when you can rebuild the data. It has a **30-day** minimum duration and a **128 KB** minimum billed size.
- **If** the data is the only copy, **then** do **not** use **S3 One Zone-Infrequent Access (One Zone-IA)** or **S3 Express One Zone**. **This works because** both keep data in a **single Availability Zone (AZ)**, and that whole AZ can be lost. All other classes store data in **3+ AZs** and survive the loss of an entire AZ.
- **If** millions of **10 KB** files must be archived, **then** **bundle** them into larger files first. **This works because** small objects are expensive in cold classes: Standard-IA, One Zone-IA and Glacier Instant Retrieval bill each object as at least **128 KB**, and Glacier Flexible Retrieval and Deep Archive add about **40 KB** per object (8 KB at Standard price, 32 KB at Glacier price). Each lifecycle transition is also a billed request, so moving millions of tiny objects can cost more than it saves.
- **If** a lifecycle rule does not move small objects, **then** add an **object size filter** (`ObjectSizeGreaterThan` / `ObjectSizeLessThan`) to the rule. **This works because** since **September 2024**, objects under **128 KB** are not transitioned by default. Older rules keep the old behavior until you edit them.
- **If** regulators say nobody may delete the data for **6 years**, **then** use **S3 Object Lock** in **compliance mode** with a 6-year retention period. Object Lock is Write Once Read Many (WORM): it stops a locked object version from being deleted or overwritten. **This works because** in compliance mode nobody, **not even the root user**, can delete the version or shorten retention; the only way out is deleting the AWS account. Object Lock needs versioning on the bucket, and you can extend retention but never shorten it.
- **If** you must keep data for an audit with **no known end date**, **then** put a **legal hold** on the objects with **S3 Object Lock**. **This works because** a legal hold has no end date: it stays until someone with `s3:PutObjectLegalHold` removes it. It is independent of any retention period, so an object can have both.
- **If** data must be protected but admins must be able to override it in an emergency, **then** use **S3 Object Lock** in **governance mode**. **This works because** most users cannot delete or change locked versions, but users with the `s3:BypassGovernanceRetention` permission (who also send the bypass header) can. Compliance mode would not allow this, not even for root.
- **If** a user deleted a file in a **versioned bucket**, **then** delete the **delete marker** (or copy an older version to become current). **This works because** a delete without a version ID only adds a delete marker; the object looks gone (GET returns 404) but all versions are still there.
- **If** storage cost grew after you turned on **versioning**, **then** add a **lifecycle rule** that expires noncurrent versions (`NoncurrentVersionExpiration`, which can keep N newer versions). **This works because** every version is a full copy and is billed fully, so old versions of big objects add cost fast.
- **If** a **200 GB** upload keeps failing, **then** use **multipart upload**. **This works because** the file is split into parts (5 MiB to 5 GiB each, up to 10,000 parts) that upload in parallel, and only failed parts are retried. A single PUT is limited to **5 GB** anyway, so a 200 GB file must use multipart.
- **If** unfinished multipart uploads waste space, **then** add a lifecycle rule with **`AbortIncompleteMultipartUpload`** (for example after **7 days**). **This works because** leftover parts keep costing storage until the upload is aborted.
- **If** you need **single-digit millisecond** reads next to your compute, **then** use **S3 Express One Zone** in the same **Availability Zone (AZ)** as the compute. **This works because** it stores data in one AZ you choose, in directory buckets, with lower request cost than Standard. The catch: it is one AZ only, so do not keep your only copy of important data there.
- **If** archived data is needed in **minutes**, **then** use an **Expedited** restore from **S3 Glacier Flexible Retrieval** (1–5 minutes, for objects under 250 MB), or store the data in **S3 Glacier Instant Retrieval** from the start. **This works because** Glacier Instant Retrieval reads in milliseconds with no restore step, while Flexible Retrieval needs a restore first. Deep Archive has no Expedited option.
- **If** a team must stop permanent deletes even by admins, **then** use **MFA Delete** or **S3 Object Lock**. MFA Delete requires multi-factor authentication (MFA) to permanently delete a version or change the versioning state; only the root user can enable it, via CLI/API. **This works because** plain versioning still lets anyone with permission delete versions; MFA Delete and Object Lock close that gap.
- **If** you must move data from **S3 Glacier Deep Archive** back to **S3 Standard**, **then** **restore** the object, then **copy** it into the Standard class. **This works because** lifecycle only moves objects **downward** and cannot go back up; Deep Archive is one-way.
- **If** listing a bucket with **billions of objects** is slow, **then** use **S3 Inventory**, a scheduled report of the bucket's objects. **This works because** LIST returns only **1,000 keys** per call, so huge buckets need many slow, billed calls, while Inventory gives the whole list at once.
- **If** a file name needs to change, **then** **copy** the object to the new key, then **delete** the old one. **This works because** S3 cannot rename an object in place.
- **If** the checksum of a multipart object does not match its MD5, **then** use **additional checksums** (CRC32, CRC32C, SHA-1 or SHA-256) instead of the ETag. **This works because** the **ETag** is not an MD5 hash for multipart or KMS-encrypted objects.

## Verified from AWS docs on 2026-10-02
Storage class table, lifecycle transitions, versioning, Object Lock, Express One Zone were read from current AWS pages. Not re-checked: bucket count default (10,000), Object Lock on existing buckets wording (verify).

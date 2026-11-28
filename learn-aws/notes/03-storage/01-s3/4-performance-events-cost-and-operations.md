# S3 – 4. Performance, events, cost, operations, troubleshooting, limits

Short notes. Each point is a fact you can be asked about.

## A. Request performance
- S3 scales automatically. Baseline per prefix: at least 3,500 PUT/COPY/POST/DELETE and 5,500 GET/HEAD requests per second (verified).
- Number of prefixes in a bucket is unlimited. 10 prefixes → read capacity about 55,000 GET/s.
- Scaling to a new higher rate is gradual. You may see HTTP 503 "Slow Down" while S3 scales. Retry with exponential backoff and jitter.
- The prefix is everything in the key before the last delimiter-based partition S3 chooses. Spreading keys across several prefixes spreads load.
- Date-partitioned layouts (`year=/month=/day=`) already spread reads.
- Old advice "add a random hash to the start of the key name" is no longer required for performance.
- Typical first-byte latency: about 100–200 ms for small objects (verified in docs).
- Express One Zone gives single-digit millisecond latency (single AZ).
- Parallelize: many parallel connections, multiple threads, multiple instances.
- Large objects: use multipart upload (parallel parts) and byte-range GET (parallel ranges). Match the range size to part size (for example 8–16 MB).
- Use the AWS Common Runtime (CRT) SDK clients and the `aws s3` CLI settings (`max_concurrent_requests`, `multipart_chunksize`) to raise throughput.
- One EC2 instance can reach up to 100 Gb/s to S3 on large network cards (verified).
- Keep compute in the same Region (and for Express One Zone, same AZ) as the bucket.
- If KMS is used: SSE-KMS request limits apply (S3 Bucket Keys reduce calls).
- Caching: CloudFront for repeated downloads to users; ElastiCache/DAX-style caching for hot small objects.
- Transfer Acceleration: uploads and downloads go through the nearest CloudFront edge, then the AWS backbone to the bucket. Use for far-away clients and large files. Needs enabling per bucket, uses a special endpoint (`bucket.s3-accelerate.amazonaws.com`), extra per-GB fee, and bucket names must be DNS compatible without dots (verify).
- Transfer Acceleration charges only when it is actually faster (verify current wording).
- Mountpoint for Amazon S3: mounts a bucket as a local folder for read-heavy workloads (not full POSIX).
- Using S3 as a database is slow. Use Parquet and let query engines read column chunks.

## B. Data lake layout for speed
- Use Parquet or ORC (columnar) with compression (Snappy, ZSTD).
- Target file size roughly 128 MB to 1 GB. Thousands of tiny files are slow (one request per file, task overhead).
- Partition on columns you filter on and with low-to-medium cardinality (date, region). Not user IDs.
- Hive-style `key=value` folders let engines skip partitions.
- Compact small files with Glue/Spark/Athena CTAS, Firehose bigger buffers, or Iceberg/S3 Tables compaction.
- Do not make millions of partitions.
- Keep raw data immutable in its own prefix/bucket. Write curated data elsewhere.
- Separate buckets (or prefixes) per layer and per sensitivity, because lifecycle, encryption, replication and policies are per bucket/prefix.
- Avoid `LIST` on huge prefixes in code. Use Inventory or the partition catalog.
- Athena cost is per data scanned. Columnar + partition cuts the bill a lot.
- Redshift COPY works best from many equal-size compressed files (multiple of slices).

## C. Event notifications
- Notify when things happen in a bucket. Destinations: SNS topic, SQS queue, Lambda function, EventBridge.
- Delivery is at least once. Normally seconds, sometimes a minute or more. Duplicates and out-of-order are possible → idempotent consumers.
- Event types: object created (Put, Post, Copy, CompleteMultipartUpload), object removed (delete, delete marker created), object restore (post/completed), replication events, lifecycle expiration and transition events, Intelligent-Tiering archive events, object tagging, ACL put, Object Lock retention.
- Filters: prefix and suffix (no regex, no wildcards in the middle).
- Destination needs a resource policy that lets S3 send (SNS topic policy, SQS queue policy, Lambda resource policy).
- SQS FIFO queues are not supported as a direct destination. Use EventBridge to reach a FIFO queue.
- EventBridge: all events go to the default event bus when enabled; then use rules for filtering (including by object size, key patterns), many targets, archive/replay, cross-account. Slightly higher latency than direct.
- Avoid loops: if the Lambda writes back into the same bucket and prefix that triggers it, it triggers itself. Use separate buckets or prefixes.
- Overlapping prefix/suffix filters for the same event type to different destinations are not allowed in the classic notification config.
- Enabling events on a bucket with SSE-KMS: SQS/SNS queues also need KMS permission if encrypted.
- Typical pattern: file lands → event → Lambda/Step Functions/Glue workflow starts.
- Lifecycle events can notify when objects expire or move to Glacier.
- For more than a handful of consumers or complex routing, prefer EventBridge. For simple trigger of one Lambda, direct is fine.

## D. Management and analysis tools
- S3 Inventory: scheduled report (daily or weekly) as CSV, ORC or Parquet listing objects and fields (size, class, encryption, replication status, Object Lock, version ID, checksum). Query with Athena. Much cheaper than LIST at scale.
- S3 Batch Operations: run one action on billions of objects from an Inventory/manifest: Copy, Invoke Lambda, restore from Glacier, tag, ACL, Object Lock, replicate, checksum compute. Gives job reports and tracking.
- S3 Storage Lens: usage and activity metrics across accounts/org, free tier of metrics plus advanced paid metrics. Finds incomplete multipart bytes, non-current versions, unencrypted data, etc.
- Storage Class Analysis: recommends the age to move Standard data to IA.
- CloudWatch: daily storage metrics (free), request metrics (paid), replication metrics, data events.
- Requester Pays: requester pays request and transfer cost. Requests must be authenticated and include `x-amz-request-payer`. Not allowed as replication destination in cross-account.
- Static website hosting: HTTP only on the S3 website endpoint (use CloudFront for HTTPS and custom domain). Needs public read (BPA relaxed) or CloudFront Origin Access Control.
- CORS: browser cross-origin access rules, set on the bucket.
- Object tagging up to 10 tags; used for lifecycle, billing allocation, access rules.
- Object annotations, S3 Vectors and S3 Files are newer features (check docs; not core).

## E. What you pay for
- Storage: per GB-month by class (hot costs more per GB, cold costs more per request/retrieval).
- Requests: PUT/COPY/POST/LIST are priced higher than GET. Lifecycle transitions are billed as requests.
- Retrieval: per GB for IA/Glacier classes. Expedited, Standard, Bulk tiers differ.
- Data transfer: data in from internet is free. Data out to the internet costs. Same-Region S3 to EC2/Glue/Athena is free. Cross-Region costs. Replication costs destination storage + PUTs + CRR transfer.
- Management features: Inventory, Storage Lens advanced, Batch Operations, Object Lambda, analytics, replication RTC.
- Intelligent-Tiering: per-object monitoring fee, no retrieval fee.
- Minimum storage duration and 128 KB minimum size penalties for IA/Glacier IR.
- Glacier overhead: 40 KB metadata per archived object.
- Versioning: every version is billed.
- Incomplete multipart uploads: billed until aborted.
- KMS: per-request KMS charges with SSE-KMS (Bucket Keys cut up to 99%).
- Free: data in, same-Region transfer to AWS services, gateway endpoints, S3 Event Notifications (target costs apply).

## F. How to cut S3 cost
- Pick the right class: Intelligent-Tiering for unknown access, lifecycle for known aging.
- Expire what you do not need (logs, temp, old versions, delete markers, incomplete multipart).
- Convert to compressed Parquet. Smaller storage and cheaper scans.
- Combine small files; avoid archiving tiny objects.
- Keep compute and data in the same Region; use VPC gateway endpoints to avoid NAT per-GB charges.
- Use SRR/CRR only where needed; replicate prefixes by filter; replicate into cheaper classes.
- Turn on Bucket Keys for SSE-KMS.
- Use Storage Lens + Cost Explorer + cost allocation tags to find who spends.
- Avoid frequent LIST calls; use Inventory.
- Use CloudFront for repeated public downloads (cheaper egress, fewer GETs).
- Use Requester Pays when sharing big datasets to other parties.
- Delete or move test data; set bucket-level lifecycle by default.
- Do not use Express One Zone for cold data; do not use Standard for data nobody reads.

## G. Monitoring
- CloudWatch daily metrics: BucketSizeBytes, NumberOfObjects (by storage class).
- Request metrics (optional): AllRequests, GetRequests, PutRequests, 4xxErrors, 5xxErrors, FirstByteLatency, TotalRequestLatency.
- Replication metrics: BytesPendingReplication, OperationsPendingReplication, ReplicationLatency.
- Alarm on 5xx errors, replication latency, and unexpected size growth.
- CloudTrail data events + EventBridge for security alerts.
- Server access logs for request-level troubleshooting.
- Storage Lens dashboards for fleet-wide insights.

## H. Troubleshooting (symptom → cause → fix)
- 403 AccessDenied on GetObject: check identity policy, bucket policy, explicit Deny, SCP, VPC endpoint policy, KMS key permission, Block Public Access/RestrictPublicBuckets, Object Ownership (object owned by another account), object not yet restored from Glacier, requester pays header.
- 403 on cross-account read: need Allow on both sides; with SSE-KMS also allow in the key policy.
- 404 NoSuchKey: wrong key/case, delete marker current, wrong Region, object still being created (versioning just enabled).
- 404 NoSuchBucket: wrong name or Region endpoint.
- 301 PermanentRedirect: wrong Region endpoint.
- 400 AccessControlListNotSupported: bucket has ACLs disabled; remove the ACL from the request.
- 400 InvalidRequest with SSE-C: SSE-C blocked on the bucket (April 2026 default).
- 503 SlowDown: request rate spike on a prefix → backoff, spread prefixes, wait for scaling.
- 503 on a versioned bucket with huge version counts on one key → clean versions.
- 409 BucketAlreadyExists / BucketAlreadyOwnedByYou: names are global.
- 409 OperationAborted / conflicts: concurrent bucket config changes.
- 403 InvalidObjectState: object is in Glacier Flexible/Deep Archive → restore first.
- Athena "HIVE_BAD_DATA"/zero rows: schema mismatch or partitions not added; archived objects not restored.
- Replication FAILED: see replication file.
- Lifecycle did not run: wait up to a day, check the filter/prefix, rule status, size filter (128 KB), versioning state.
- Large upload fails: use multipart, check timeouts, abort stale uploads.
- Presigned URL fails: expired, wrong Region/SigV4, signing credentials expired, clock skew.
- Event notification not firing: destination policy missing, filter mismatch, overlapping configuration, KMS-encrypted queue.
- High costs surprise: versioned buckets with many noncurrent versions, incomplete multipart, lots of LIST/GET small objects, cross-Region transfer, NAT gateway traffic, KMS requests.
- CORS errors: add CORS rule with the right origins/methods/headers.

## I. Limits and numbers (verified or marked)
- Max object size: 5 TB. Max single PUT: 5 GB. Multipart: 10,000 parts, part size 5 MiB–5 GiB.
- Request rate per prefix: 3,500 write / 5,500 read per second.
- LIST page: 1,000 keys.
- Object key length: up to 1,024 bytes.
- Tags per object: 10. User metadata total: 2 KB (verify).
- Bucket name: 3–63 characters.
- Default buckets per account: 10,000 (verify).
- Bucket policy max size: 20 KB.
- Access point policy max size: 20 KB.
- Lifecycle: transitions downward only; min days before IA transition 30 (verify for rule day counts); small objects under 128 KB not transitioned by default.
- Min storage duration: IA/One Zone-IA 30 days; Glacier IR/Flexible 90 days; Deep Archive 180 days.
- Min billable object size: 128 KB for IA, One Zone-IA, Glacier IR.
- Glacier restore API rate: about 1,000 requests per second; 1–2 PB/day throughput (verified).
- Glacier Flexible restore: Expedited 1–5 min, Standard 3–5 h, Bulk 5–12 h. Deep Archive: Standard within 12 h, Bulk within 48 h.
- RTC: 99.99% of objects within 15 minutes.
- Pre-signed URL max validity: up to 7 days with IAM user credentials; shorter with temporary role credentials (verify).
- Event notification: at least once; filter by prefix/suffix only.
- Replication rules: one source can have multiple destinations; no chaining.
- S3 Tables quotas: 100 table buckets per Region, 10,000 namespaces and 10,000 tables per table bucket (verified, see file 5).
- Express One Zone: 99.95% availability, single AZ, session credentials last about 5 minutes (verified).

## J. S3 Select and Object Lambda status
- S3 Select is no longer offered to new customers. Existing customers can keep using it.
- S3 Object Lambda is no longer available to new customers since 7 Nov 2025 (existing customers and some partners can continue).
- Alternatives: Athena for SQL; byte-range GETs; Lambda or Glue for transformation; CloudFront functions/Lambda@Edge for response changes.

## K. Scenarios (if → then, because)
- **If** reads get **503 SlowDown** errors on one prefix, **then** spread keys across **more prefixes** and retry with **exponential backoff and jitter**. **This works because** limits apply **per prefix** (at least **5,500 GET** and **3,500 PUT** requests per second each), and S3 scales up to a new rate gradually. The number of prefixes is unlimited, so 10 prefixes give about 55,000 GET/s.
- **If** a far-away office uploads **50 GB** files slowly, **then** use **S3 Transfer Acceleration** together with **multipart upload**. **This works because** Transfer Acceleration sends data to the nearest Amazon CloudFront edge location and then over the AWS backbone to the bucket, while multipart uploads parts in parallel. It must be enabled per bucket, uses a special endpoint, and adds a per-GB fee (verify).
- **If** downloading one huge file is slow, **then** use parallel **byte-range GETs**. **This works because** each request reads one part of the object, so many ranges download at the same time; match the range size to the part size (for example 8–16 MB).
- **If** Amazon Athena scans cost too much, **then** store data as compressed **Parquet**, **partition** it on the columns you filter on, and **compact** small files. **This works because** Athena charges per data scanned, and columnar files plus partitions let it read only the columns and partitions it needs.
- **If** millions of tiny files slow AWS Glue or Amazon Athena, **then** compact them into files of **128 MB or more** (target 128 MB to 1 GB). **This works because** each file costs one request plus task overhead, so fewer, larger files read much faster.
- **If** you need to run one action on **2 billion objects**, **then** list them with **S3 Inventory** and act with **S3 Batch Operations**. **This works because** Batch Operations runs one action (copy, tag, restore, invoke Lambda and more) on billions of objects from an Inventory manifest, with job reports and tracking.
- **If** you need a count, size or storage class report for billions of objects, **then** use **S3 Inventory** and query it with **Amazon Athena**. **This works because** Inventory is a daily or weekly report (CSV, ORC or Parquet) of all objects and their fields, and it is much cheaper than LIST at scale.
- **If** you need to know which buckets waste money, **then** use **S3 Storage Lens**. **This works because** it shows usage and activity across accounts and the organization, and finds waste such as incomplete multipart upload bytes and noncurrent versions.
- **If** a new file should start a pipeline with several consumers, **then** send S3 events to **Amazon EventBridge**. **This works because** EventBridge rules can filter events (even by object size or key pattern), fan out to many targets, archive and replay events, and work cross-account. The catch: latency is slightly higher than direct notifications.
- **If** events must reach an **Amazon SQS FIFO queue**, **then** route them through **Amazon EventBridge**. **This works because** S3 Event Notifications do not support FIFO queues as a direct destination.
- **If** a Lambda function triggered by S3 keeps running forever, **then** make it write to a **different prefix or bucket**. **This works because** it is writing back into the prefix that triggers it, so each output fires the trigger again.
- **If** a partner downloads big datasets and you do not want to pay the transfer cost, **then** turn on **Requester Pays** for the bucket. **This works because** the requester then pays the request and transfer cost. Requests must be authenticated and include the `x-amz-request-payer` header.
- **If** a website needs HTTPS and a custom domain, **then** put **Amazon CloudFront** in front of S3 with **Origin Access Control (OAC)**. **This works because** the S3 website endpoint only serves HTTP, while CloudFront adds HTTPS and the custom domain, and OAC lets CloudFront read the bucket without making it public.
- **If** data transfer out from many repeated downloads is high, **then** cache the files with **Amazon CloudFront**. **This works because** CloudFront serves repeated downloads from its cache, giving cheaper egress and fewer GET requests to S3.
- **If** you want SQL on a single object without a query engine, **then** use **Amazon Athena** instead. **This works because** **S3 Select** is no longer offered to new customers (existing customers can keep using it). Byte-range GETs are another way to read part of a file.
- **If** you must cut NAT gateway cost for S3 traffic, **then** use an **S3 gateway VPC endpoint**. **This works because** gateway endpoints are free, while a NAT gateway charges per GB.
- **If** storage grew unexpectedly in a **versioned bucket**, **then** look at **noncurrent versions** and add a **lifecycle rule** to expire them. **This works because** every version is billed, so old versions quietly pile up cost.
- **If** AWS Key Management Service (KMS) bills are large, **then** turn on **S3 Bucket Keys** for SSE-KMS. **This works because** Bucket Keys cut KMS requests, and their cost, by up to **99%**.
- **If** a team stores **100 KB** files and wants Standard-Infrequent Access (Standard-IA), **then** it is **not worth it**; bundle the files first. **This works because** IA classes bill each object as at least **128 KB**, so every 100 KB file is billed as 128 KB.
- **If** a data scientist needs file-like access to S3 for training, **then** use **Mountpoint for Amazon S3**, or **S3 Express One Zone** for speed. **This works because** Mountpoint mounts a bucket as a local folder for read-heavy work (not full POSIX), and Express One Zone gives single-digit millisecond latency.
- **If** you need billions of small random reads at the lowest latency, **then** use **S3 Express One Zone** in the same **Availability Zone (AZ)** as your compute. **This works because** it gives single-digit millisecond latency and request cost about 80% lower than Standard. The catch: it is one AZ only, so do not keep your only copy there.
- **If** someone asks "is S3 eventually consistent?", **then** the answer is **no**. **This works because** S3 gives **strong read-after-write consistency** for PUT, DELETE and LIST in all Regions, at no extra cost; the old "eventual consistency" advice is out of date.

## Verified from AWS docs on 2026-10-02
Performance guidelines (request rates, scaling, latency), event notifications overview, S3 pricing structure, restore tiers, S3 Select/Object Lambda status were read. Not re-checked: Transfer Acceleration details, pre-signed URL expiry limits, bucket count default, user metadata size, exact KMS quota values (verify).

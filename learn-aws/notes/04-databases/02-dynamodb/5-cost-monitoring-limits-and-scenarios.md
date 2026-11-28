# DynamoDB – 5. Cost, monitoring and troubleshooting, limits, mixed scenarios

Short notes. Each point is a fact you can be asked about.

## A. What you pay for
- Read and write throughput: on-demand per request unit, or provisioned per capacity unit per hour.
- Data storage per GB-month (Standard or Standard-IA table class). First 25 GB per month is free in the free tier (verify).
- Backups: PITR (per GB-month of table + LSI size), on-demand backups (per GB-month), restores (per GB restored).
- Global tables: replicated write units in each replica Region, storage in every Region, cross-Region data transfer.
- Streams: DynamoDB Streams read requests (GetRecords) – first 2.5 million read request units per month free (verify). Kinesis Data Streams: change data capture units (1 KB each) plus Kinesis charges.
- Export to S3: per GB of table size (full) or data processed (incremental); import from S3: per GB; plus S3 storage and requests.
- DAX: node-hours by node type (cluster of 3+ nodes for production).
- Data transfer: in is free; out to the internet and cross-Region cost; same-Region traffic from EC2 to DynamoDB through gateway endpoint is free of endpoint charges.
- Interface endpoints (PrivateLink): hourly + per-GB; gateway endpoints are free.
- Reserved capacity: 1- or 3-year commitment for provisioned RCU/WCU only.
- Other: Contributor Insights (per event), CloudTrail data events, CloudWatch metrics/alarms, AWS Backup storage.

## B. Cutting cost (practical checklist)
- Pick the right mode: on-demand for spiky/unknown/low traffic; provisioned + auto scaling (+ reserved) for steady traffic. Re-evaluate every few months (switching limits apply).
- Prefer eventually consistent reads (half the read cost).
- Use Query/GetItem, not Scan. Scans cost for everything evaluated.
- Keep items small: short attribute names, compress large text, move blobs to S3.
- Project only needed attributes into GSIs (INCLUDE/KEYS_ONLY); delete unused GSIs (each GSI multiplies write cost).
- Use sparse GSIs.
- Use TTL to remove data you no longer need (free deletes).
- Use Standard-IA table class for large, rarely read tables.
- Use Export to S3 + Athena for analytics instead of scanning the live table.
- Use DAX or a cache to reduce repeated reads; it can allow lower read provisioning.
- Batch writes smartly: BatchWriteItem saves round trips, not capacity (each item still costs).
- Avoid transactions unless required (double cost).
- Use Import from S3 for bulk loads into new tables (no write capacity used).
- Avoid global tables unless the business needs multi-Region (replicated writes multiply cost).
- Shorten PITR window does not reduce price; disable PITR on tables that don't need it (but keep it for production).
- Delete old on-demand backups and test tables; set backup lifecycle with AWS Backup.
- Set maximum throughput on on-demand tables used by risky jobs to cap runaway cost.
- Use cost allocation tags + Cost Explorer per table.
- Use gateway endpoints instead of NAT for DynamoDB traffic from VPC.

## C. Monitoring – key CloudWatch metrics (verified list)
- Capacity: `ConsumedReadCapacityUnits`, `ConsumedWriteCapacityUnits` (use Sum ÷ 60 for per-second average), `ProvisionedRead/WriteCapacityUnits`.
- Throttling: `ThrottledRequests`, `ReadThrottleEvents`, `WriteThrottleEvents`, and the cause-specific `Read/WriteProvisionedThroughputThrottleEvents`, `Read/WriteKeyRangeThroughputThrottleEvents`, `Read/WriteMaxOnDemandThroughputThrottleEvents`, `Read/WriteAccountLimitThrottleEvents`.
- Errors: `UserErrors` (HTTP 400 – validation, not found, conflicts; excludes throttles and conditional failures), `SystemErrors` (HTTP 500 – DynamoDB side; alarm needs `TableName` + `Operation` dimensions), `ConditionalCheckFailedRequests`, `TransactionConflict`.
- Latency: `SuccessfulRequestLatency` (server-side only; per Operation; percentiles available).
- Data returned: `ReturnedItemCount`, `ReturnedBytes`.
- Indexes: dimension `GlobalSecondaryIndexName`; `OnlineIndexPercentageProgress` while building.
- TTL: `TimeToLiveDeletedItemCount`.
- Global tables: `ReplicationLatency`, `PendingReplicationCount` (legacy), write consumption `Source` dimension (Customer vs GlobalTable).
- Streaming to Kinesis: `AgeOfOldestUnreplicatedRecord`, `FailedToReplicateRecordCount`, `ThrottledPutRecordCount`.
- Account level: `AccountProvisionedReadCapacityUtilization`, `AccountProvisionedWriteCapacityUtilization`, `TableCount`, `MaxProvisionedTableRead/WriteCapacityUtilization`.
- Most capacity metrics are aggregated at 1-minute granularity; short spikes inside a minute can be hidden in averages.
- Contributor Insights: most accessed and most throttled keys. Turn on for hot-key investigation.
- Use alarms on throttles, `SystemErrors`, latency, replication latency, and consumed vs provisioned capacity (for example above 80%).
- Auto scaling reacts after 2 minutes over target; spikes shorter than a minute may be missed.
- CloudTrail for who changed what; AWS Health for service events.

## D. Troubleshooting (symptom → cause → fix)
- `ProvisionedThroughputExceededException` → exceeded provisioned capacity or a partition limit → raise capacity, enable auto scaling, switch to on-demand, fix hot key, use backoff.
- Throttling but low table-level usage → hot partition (`KeyRange` throttle events) → better key, write sharding, spread traffic, DAX for read hotspots.
- Throttling right after a traffic jump on an on-demand table → exceeded double the previous peak within 30 minutes → ramp up or pre-warm.
- Throttling after creating a GSI or when a GSI is under-provisioned → GSI write capacity too low → increase GSI capacity.
- Sudden high cost → Scan on a big table, large items, many GSIs, transactions, global replication, Standard instead of IA → check `ConsumedRead/WriteCapacityUnits`, Cost Explorer, Contributor Insights.
- `ValidationException` → bad key, type, expression, item over 400 KB, reserved word, empty key value → fix request; use expression attribute names.
- `ConditionalCheckFailedException` → condition not met (expected in locking/idempotency) → handle and retry or read again.
- `TransactionCanceledException` / `TransactionConflictException` → conflict, condition failure, capacity, size → read `CancellationReasons`, shorten transactions, retry with backoff.
- `ResourceNotFoundException` → wrong table/index name, Region, or table not ACTIVE yet.
- `LimitExceededException` → too many control-plane operations (create tables with indexes concurrently, too many tables, PITR changes).
- `ItemCollectionSizeLimitExceededException` → LSI item collection above 10 GB → redesign or remove LSI use (LSI can't be removed).
- `AccessDeniedException` → missing IAM action/resource (index ARN?), KMS key permission, resource policy deny, SCP, VPC endpoint policy.
- `InternalServerError` / HTTP 500 → retry with backoff; check `SystemErrors`.
- `ThrottlingException` / `RequestLimitExceeded` → control-plane or account-level request limits.
- Stale reads → eventual consistency (replicas, GSIs) → use `ConsistentRead=true` (table only) or wait.
- Query returns fewer items than expected → 1 MB page limit or `Limit` or filter expression; follow `LastEvaluatedKey`.
- Query on GSI misses attributes → not projected → add to projection or fetch from the table.
- Missing items from a GSI → item lacks the index key attribute (sparse behaviour) or index still backfilling.
- Streams consumer lag or stuck → poison record, throttled GetRecords (more than 2 readers on a shard), Lambda errors/timeouts, shard backlog.
- Expired items still visible → TTL deletion can take days → filter on TTL attribute.
- Expired items vanished unexpectedly → TTL attribute value too small (seconds vs milliseconds mistake).
- DAX returns old data → eventually consistent cache; item TTL in cache; stale after out-of-band writes.
- Restore finished but app can't connect → new table name; update app/config, scaling policies, alarms, IAM, TTL.
- Global table conflicts or missing writes → last-writer-wins; check `ReplicationLatency`, capacity and quotas in all Regions.
- Import failed → bad format, schema mismatch, object count above 50,000, quota limits.
- Export failed → PITR not enabled, S3 permissions/KMS missing.

## E. Limits and numbers (verified unless marked)
- Item size: 400 KB. Partition key value: 2048 bytes. Sort key value: 1024 bytes.
- Attribute nesting: 32 levels. Number precision: 38 digits.
- Table and index names: 3–255 characters.
- Tables per account per Region: 2,500 default (up to 10,000 by request).
- GSIs per table: 20 default. LSIs per table: 5 (created at table creation only).
- LSI item collection: 10 GB per partition key value.
- Projected (INCLUDE) attributes across all indexes of a table: 100.
- Query/Scan page: 1 MB per call.
- BatchGetItem: 100 items (16 MB). BatchWriteItem: 25 items (16 MB) (verify sizes).
- TransactWriteItems / TransactGetItems: 100 actions, 4 MB aggregate.
- Transaction idempotency token: 10 minutes.
- Per-table throughput default: 40,000 RCU/WCU (provisioned) or 40,000 read/write request units (on-demand). Per-account provisioned: 80,000 RCU/WCU. All increasable.
- New on-demand table: 4,000 writes/s, 12,000 reads/s initial; scales instantly to double the previous peak.
- Provisioned decreases: 4 at start of UTC day + 1 per hour (max 27 per day).
- Switching: provisioned → on-demand up to 4 times per rolling 24 hours (docs); verify other direction/limits.
- Reserved capacity: 1,000,000 units per account by default.
- Streams: 24-hour retention; at most 2 readers per shard (1 for global tables); max 40,000 WCU per table for provisioned tables with Streams (default quota).
- PITR window: 1–35 days. Restore: 50 concurrent / 50 TB (native), 50 / 25 TB (AWS Backup).
- Export: 300 concurrent or 100 TB in flight; incremental window 15 minutes–24 hours.
- Import: 50 concurrent jobs; 15 TB (us-east-1, us-west-2, eu-west-1) or 1 TB elsewhere; 50,000 S3 objects per job.
- Global tables: 400 MRSC tables per account (default); 10 TB per day backfill per account per destination Region; throughput quotas must match across Regions.
- Resource-based policy size: 20 KB.
- PrivateLink: 50,000 requests per second per endpoint.
- Vector indexes: 5 per table, up to 4,096 dimensions, TopK 100 (newer feature; verify).
- DescribeTable item counts and sizes refresh about every 6 hours.
- Partition ceilings (verify): about 10 GB data, 3,000 RCU and 1,000 WCU per partition.
- Capacity math: 1 RCU = 4 KB strongly consistent/second; eventual = half; transactional = double; 1 WCU = 1 KB/second; transactional = double; sizes round up.

## F. Mixed scenarios (if → then, because) – across all five files
1. **If** a game needs lookups by player ID at millions per second with no operations work, **then** use DynamoDB in **on-demand** mode with **partition key = player ID**. **This works because** DynamoDB is serverless with single-digit millisecond key lookups at any scale, and player ID has many distinct values that spread traffic evenly. Very high rates may need the default table quota (**40,000** request units per second) raised.
2. **If** the same game needs a top-100 leaderboard, **then** build a separate sorted structure: a **Global Secondary Index (GSI)** keyed by score bucket, or a sorted set in **Amazon ElastiCache** or **Amazon MemoryDB**. **This works because** a top-N across the whole table otherwise needs a Scan, while a sort key or sorted set keeps scores in order.
3. **If** a table has a steady 2,000 reads/s all day and you want the lowest cost, **then** use **provisioned** mode with **auto scaling**, and consider **reserved capacity** (1 or 3 years). **This works because** steady traffic uses its provisioned capacity fully, and reserved capacity discounts provisioned units (it does not apply to on-demand).
4. **If** a promotion may raise traffic 10x in minutes, **then** use **on-demand** plus **pre-warming** (warm throughput), and test the ramp. **This works because** on-demand instantly handles only **double the previous peak**; a bigger jump within **30 minutes** can throttle.
5. **If** items are **6 KB** and you need **100 strongly consistent reads/s**, **then** provision **200 RCU** (Read Capacity Units); eventually consistent reads need only **100 RCU**. **This works because** reads round up to 4 KB steps, so 6 KB counts as 8 KB = 2 units per read, and eventual reads cost half.
6. **If** a Lambda function consumes a stream and its own update of the item triggers an infinite loop, **then** do not write to the item that triggered it, or use **event filtering** to skip those changes. **This works because** every write that changes an item creates a new stream record, which invokes the function again.
7. **If** you must restore one item deleted yesterday, **then** do a **Point-in-Time Recovery (PITR)** restore to a **new table** at a time before the delete, and copy that item back. **This works because** a restore always creates a new table and never overwrites the live one, so all other recent changes are kept.
8. **If** a table must be available in Frankfurt and Virginia with local writes in both, **then** use **global tables** in **Multi-Region Eventual Consistency (MREC)** mode and design for **last writer wins**. **This works because** each replica accepts writes and replicates asynchronously in about a second; in a conflict, the later timestamp wins.
9. **If** a regulator forbids data leaving the EU, **then** use a single-Region table in an EU Region, with no replicas elsewhere, a **service control policy (SCP)** that denies other Regions, and backups and exports kept in the EU. **This works because** data stays in the chosen Region unless you add replicas, copy backups or export elsewhere.
10. **If** the data science team needs the data in the lake daily, **then** use **incremental exports to S3** (or **zero-ETL** to **Amazon Redshift**). **This works because** exports need PITR but use no read capacity, and incremental exports copy only the changes in a window of 15 minutes to 24 hours.
11. **If** analysts need ad hoc SQL over live order data in near real time, **then** use **Redshift zero-ETL**, or **Kinesis Data Streams → Firehose → S3 → Amazon Athena**. **This works because** DynamoDB has no ad hoc SQL or joins, so the data is copied continuously to a store built for analytics, without scanning the live table.
12. **If** a Query filters on `status = 'OPEN'` and 99% of items are closed, **then** create a **sparse GSI** that holds only open items. **This works because** filters run after the read and do not save read cost, while a sparse index contains only items that have the index key attribute.
13. **If** an app needs both "get by order ID" and "list orders by customer", **then** key the table by order ID and add a **GSI** on customer ID, or use customer as the partition key and order as the sort key with a GSI on order ID. **This works because** each access pattern needs its own key, and a GSI gives the second key, kept in sync automatically.
14. **If** a hot product page is read by millions, **then** cache it with **DynamoDB Accelerator (DAX)** (eventually consistent reads) or a **CloudFront**/API cache. **This works because** a cache serves repeated reads from memory, so the hot key does not overload one partition.
15. **If** a payment must debit and credit two items atomically, **then** use **TransactWriteItems** with **conditions** (for example enough balance). **This works because** the transaction is all or nothing, and one failed condition cancels every action.
16. **If** event processing must not run twice, **then** build an **idempotency table**: a conditional put of the event ID (`attribute_not_exists`) with **TTL** set for the idempotency window. **This works because** a second put with the same ID fails its condition, and TTL clears old IDs for free.
17. **If** items hold **5 MB** documents, **then** store each document in **Amazon S3** and keep its metadata plus the S3 key in DynamoDB. **This works because** a DynamoDB item is limited to **400 KB**.
18. **If** you need full-text search, **then** use the **Amazon OpenSearch Service zero-ETL integration**. **This works because** DynamoDB finds items only by key and cannot search text.
19. **If** you must migrate 2 TB of MongoDB-style data to DynamoDB, **then** use **AWS Database Migration Service (DMS)** with mapping rules, or export the source to S3 and **Import from S3** into a new table. **This works because** DMS supports DynamoDB as a target, and Import loads a new table without using write capacity.
20. **If** the team needs joins and reporting on the same data, **then** keep DynamoDB for operations and replicate the data to **Amazon Redshift** or **Amazon Aurora** for reporting. **This works because** DynamoDB is built for key lookups, not joins or analytics.
21. **If** each tenant must see only its own rows, **then** use the IAM condition `dynamodb:LeadingKeys` with the tenant ID as the partition key prefix, or a separate table per tenant. **This works because** LeadingKeys limits access to items whose partition key matches; a table per tenant isolates more strongly but costs more.
22. **If** a **customer managed key** in **AWS Key Management Service (KMS)** is accidentally scheduled for deletion, **then** cancel the deletion during the waiting period, and in future disable keys instead of deleting them. **This works because** a table whose key is disabled or deleted becomes inaccessible.
23. **If** a developer needs a local test database, **then** use **DynamoDB local**, a downloadable emulator, with **NoSQL Workbench** for data modeling and PartiQL. **This works because** both are made for development and testing away from production tables.
24. **If** a nightly job must update **10 million** items, **then** run parallel **BatchWriteItem** or **UpdateItem** workers with backoff on on-demand or pre-warmed capacity; or rebuild with export → **AWS Glue** → **Import from S3** into a new table. **This works because** parallel workers spread the load, and the export/import path uses no table read or write capacity.
25. **If** items must be removed **7 days** after creation without code, **then** set a **TTL** attribute = creation time + 7 days in **epoch seconds**. **This works because** TTL deletes expired items for free. The catch: deletion can take days, so filter expired items on read.
26. **If** analytics data may be 1–2 minutes old, **then** use **zero-ETL**; if it must be seconds old, use **DynamoDB Streams** or **Kinesis Data Streams**. **This works because** zero-ETL replicates near real time with no pipeline to build, while streams deliver each change as it happens.
27. **If** you must prove who accessed a record, **then** enable **AWS CloudTrail data events** and keep the logs immutable. **This works because** data events record item-level calls like GetItem, while CloudTrail logs only control-plane calls by default.
28. **If** a Scan job keeps throttling production, **then** move it to **Export to S3**, or run a rate-limited parallel Scan that uses only a set read percentage. **This works because** a Scan uses table read capacity for every item evaluated, while an export uses none.
29. **If** one customer generates **40%** of the traffic, **then** apply **write sharding** to that customer's key (add a random suffix 0–N), or move that customer to its own table. **This works because** one key value lives in one partition with a throughput ceiling; suffixes spread it over many partitions, and reads query all suffixes and merge.
30. **If** you need strongly consistent reads on a secondary key, **then** use a **Local Secondary Index (LSI)**, which must exist from table creation, or redesign so the base table can be queried. **This works because** GSIs are eventually consistent only, while LSIs support strong reads.
31. **If** your application is in a private subnet with no internet, **then** add **gateway VPC endpoints** for DynamoDB and S3. **This works because** gateway endpoints are free route-table targets that reach the service on the AWS network, with no NAT gateway needed.
32. **If** a table holds **10 TB** of old, rarely read data, **then** use the **Standard-Infrequent Access (Standard-IA)** table class, **TTL**, and export older data to S3. **This works because** Standard-IA lowers the storage price where storage is the main cost, TTL removes unneeded items for free, and S3 keeps the archive cheaply.
33. **If** creating a global table replica fails with a quota error, **then** make the table-level write throughput quotas equal in every Region first. **This works because** global tables require matching throughput quotas in every replica Region.
34. **If** you suddenly see many `ConditionalCheckFailedRequests`, **then** remember this is expected with optimistic locking or idempotency checks; investigate only if the rate is abnormal. **This works because** a failed condition is the normal signal that another writer got there first or the work was already done.
35. **If** you want an audit trail of every change, **then** send changes from **DynamoDB Streams** or **Kinesis Data Streams for DynamoDB** into S3 via **Firehose**. **This works because** change capture records what changed, with before and after images, and S3 keeps that history long after the 24-hour stream retention.

## Verified from AWS docs on 2026-10-02
Service quotas, capacity modes, read/write units, transactions, Streams, Kinesis integration, PITR, export/import limits, global tables, PrivateLink, CloudWatch metrics lists were read. Not confirmed (verify): free-tier amounts (25 GB, 2.5M stream read units), partition ceilings, batch size limits in MB, mode switching limits in the other direction, DAX node minimums, Standard-IA break-even.

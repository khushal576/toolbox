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
1. If a game needs lookups by player ID at millions per second with no ops → DynamoDB on-demand, partition key = player ID.
2. If the same game needs a leaderboard of top 100 scores → separate sorted structure (GSI with score bucket) or ElastiCache/MemoryDB sorted set, because a table-wide top-N needs a Scan otherwise.
3. If a table has steady 2,000 reads/s all day and you want the lowest cost → provisioned with auto scaling, maybe reserved capacity.
4. If a promo may jump traffic 10x in minutes → on-demand plus pre-warming; test ramp.
5. If items are 6 KB and you need 100 strongly consistent reads/s → 200 RCU (2 per read); eventually consistent → 100 RCU.
6. If a Lambda consumes a stream and an item update triggers an infinite loop → don't write to the same item that triggers it, or filter events.
7. If you need to restore a single deleted item from yesterday → PITR restore to a new table, copy that item back (don't overwrite the live table).
8. If a table must be available in Frankfurt and Virginia with local writes → global tables (MREC); design for last-writer-wins.
9. If a regulator forbids data leaving the EU → single-Region table in an EU Region, no replicas elsewhere, deny other Regions with SCP, keep backups and exports in EU.
10. If the data science team needs the data in the lake daily → incremental exports to S3 (or zero-ETL to Redshift).
11. If analysts need ad hoc SQL over live order data in near real time → Redshift zero-ETL; or Kinesis → Firehose → S3 → Athena.
12. If a Query filters on `status = 'OPEN'` and 99% of items are closed → sparse GSI on open items, because filters don't save read cost.
13. If an app needs both "get by order ID" and "list orders by customer" → table keyed by order ID + GSI on customer ID (or customer PK/order SK + GSI on order ID).
14. If a hot product page is read by millions → DAX (eventually consistent) or CloudFront/API cache.
15. If a payment needs debit and credit on two items atomically → TransactWriteItems with conditions.
16. If event processing must not run twice → conditional put of an event ID with TTL (idempotency table).
17. If items hold 5 MB documents → S3 for the document, DynamoDB for metadata + S3 key.
18. If you need full-text search → OpenSearch zero-ETL; DynamoDB can't search text.
19. If you need to migrate 2 TB from MongoDB-style data to DynamoDB → DMS or export to S3 then Import from S3 into a new table.
20. If the team needs joins and reporting on the same data → keep DynamoDB for operations; replicate to Redshift/Aurora for reporting.
21. If you need row-level isolation per tenant → `dynamodb:LeadingKeys` with tenant ID prefix or table-per-tenant (cost vs isolation).
22. If a CMK is accidentally scheduled for deletion → cancel deletion during the waiting period; disable instead of delete.
23. If a developer needs a local test database → DynamoDB local / NoSQL Workbench.
24. If a nightly job must update 10 million items → parallel BatchWriteItem or UpdateItem workers with backoff on on-demand/pre-warmed capacity; or rebuild via export → Glue → Import to a new table.
25. If items must be removed 7 days after creation without code → TTL attribute = created + 7 days (epoch seconds); remember deletion can take days and filter on read.
26. If you need only 1-2 minute-old analytics → zero-ETL; for seconds → Streams/Kinesis.
27. If you must prove who accessed a record → CloudTrail data events (and keep logs immutable).
28. If a Scan job keeps throttling production → move it to an export; or run a rate-limited parallel scan with a read percentage.
29. If one customer generates 40% of traffic → write sharding for that customer's key, or isolate that customer in a separate table.
30. If you need strongly consistent reads on a secondary key → LSI (must exist from table creation) or query the base table via a different design.
31. If your application is in a private subnet with no internet → gateway endpoint for DynamoDB and S3.
32. If a table is 10 TB of old data rarely read → Standard-IA + TTL + export older partitions to S3.
33. If global table replica creation fails with quota error → make table-level write quotas equal in every Region first.
34. If you suddenly see lots of `ConditionalCheckFailedRequests` → expected with optimistic locking/idempotency; investigate only if the rate is abnormal.
35. If you want an audit trail of every change → Streams or Kinesis for DynamoDB into S3 via Firehose.

## Verified from AWS docs on 2026-10-02
Service quotas, capacity modes, read/write units, transactions, Streams, Kinesis integration, PITR, export/import limits, global tables, PrivateLink, CloudWatch metrics lists were read. Not confirmed (verify): free-tier amounts (25 GB, 2.5M stream read units), partition ceilings, batch size limits in MB, mode switching limits in the other direction, DAX node minimums, Standard-IA break-even.

# DynamoDB – 2. Capacity modes, capacity math, indexes, performance, DAX

Short notes. Each point is a fact you can be asked about.

## A. Two capacity modes (verified)
- **On-demand**: pay per request. No capacity planning. Default and recommended for most workloads.
- **Provisioned**: you set read and write capacity per second. Pay for what you provision (used or not).
- Capacity mode is per table, and each GSI follows the table's mode.
- Same latency, SLA and security in both modes.
- On-demand is best for: new tables, spiky or unpredictable traffic, many small tables, serverless apps.
- Provisioned is best for: steady predictable traffic, cost control with auto scaling, reserved capacity discounts.
- Switching: provisioned → on-demand up to 4 times in a rolling 24 hours; on-demand → provisioned any time (per current docs; older material says once per 24 hours – verify).
- Idle on-demand tables cost nothing for throughput (you still pay storage).

## B. On-demand scaling behavior (verified)
- New on-demand tables sustain up to 4,000 writes/s and 12,000 reads/s.
- On-demand instantly handles up to double the previous peak traffic on the table.
- If traffic sets a new peak, that becomes the new "previous peak".
- Going beyond double the previous peak within 30 minutes can throttle. Space growth over 30+ minutes or pre-warm the table (warm throughput).
- Default table-level quota: 40,000 read request units and 40,000 write request units per second (can be raised with a quota request).
- Optional maximum throughput setting per on-demand table/GSI to cap spend and protect against runaway usage. Over the cap → throttled.
- Throttling can show as separate metrics: account limits, key range (partition) limits, max on-demand throughput.

## C. Capacity units – exact rules (verified)
- Read unit (RCU / RRU): one strongly consistent read per second of an item up to 4 KB.
- Eventually consistent read: half a read unit per 4 KB.
- Transactional read: two read units per 4 KB.
- Write unit (WCU / WRU): one write per second of an item up to 1 KB. Transactional write: two units per 1 KB.
- Reads round item size up to the next 4 KB. Writes round up to the next 1 KB.
- GetItem: round the item size up to 4 KB multiples; halve for eventually consistent.
- BatchGetItem: each item is rounded up separately, then summed (1.5 KB + 6.5 KB = 4 + 8 = 12 KB).
- Query: sum the sizes of all items returned (all treated as one read), then round up to 4 KB (10 items totaling 40.8 KB → 44 KB).
- Scan: counts the size of items evaluated, not returned. Filters do not reduce cost.
- Reading a missing item still costs read capacity. Query/Scan on empty data still costs.
- Projection (returning fewer attributes) does not reduce capacity used.
- PutItem: item size (larger of old and new item if replacing). UpdateItem: larger of before and after size, even if you change one attribute. DeleteItem: size of the deleted item.
- BatchWriteItem: each item rounded up to 1 KB separately, then summed (500 B + 3.5 KB = 1 + 4 = 5 KB).
- A failed conditional write still consumes write capacity (size of the new/existing item).
- Transactions use two underlying reads/writes per item (prepare + commit), even when canceled.
- Attribute names count toward item size, so short names save money.
- Each GSI has its own capacity. A table write that changes an indexed item also writes to the GSI (extra write units billed on the GSI).
- LSI reads/writes use the base table's capacity.
- DynamoDB Streams read requests are free of table capacity; Kinesis streaming uses change data capture units (1 KB each).

## D. Capacity practice (try before reading the answers)
1. Strongly consistent reads, 3 KB items, 10 per second. → 3 KB rounds to 4 KB = 1 unit each → **10 RCU** (5 if eventually consistent).
2. Strongly consistent reads, 6 KB items, 20 per second. → 8 KB = 2 units each → **40 RCU** (20 eventually consistent).
3. Transactional reads, 6 KB items, 10 per second. → 8 KB = 2 units × 2 = 4 each → **40 RCU**.
4. Writes of 0.5 KB items, 100 per second. → 1 unit each → **100 WCU**.
5. Writes of 2.5 KB items, 50 per second. → 3 KB = 3 units each → **150 WCU**.
6. Transactional writes of 1.5 KB items, 20 per second. → 2 KB = 2 × 2 = 4 each → **80 WCU**.
7. Query returns 10 items totaling 40.8 KB, strongly consistent. → 44 KB / 4 = **11 RCU** (5.5 eventually consistent).
8. BatchGetItem for items of 1.5 KB and 6.5 KB, strongly consistent. → 4 + 8 = 12 KB → **3 RCU** (1.5 eventually).
9. UpdateItem changes a 3 KB item into 3.8 KB. → larger size 3.8 → 4 KB → **4 WCU**.
10. Scan evaluates 100 items of 2 KB each (200 KB), filter returns only 5. → 200 / 4 = **50 RCU** strongly (25 eventually).
11. DeleteItem on a 1.6 KB item. → 2 KB → **2 WCU**.
12. Conditional write fails; the new item is 310 KB (existing 300 KB). → consumes **310 WCU** (docs example).
13. 1 KB item written to a table with 2 GSIs that project this item. → base **1 WCU** + **1 WCU on each GSI** = 3 WCU total, billed per table/index.
14. App needs 500 strongly consistent reads/s of 8 KB items and 200 writes/s of 1.5 KB items (provisioned). → reads 2 each = **1,000 RCU**; writes 2 each = **400 WCU**.
15. One transaction per second writes three 500-byte items. → each item 2 units (prepare + commit) → **6 WCU** (with DAX, 6 extra RCU for the background reads).
16. Table uses on-demand; yesterday's peak was 20,000 reads/s. → can instantly handle up to 40,000 reads/s; jumping to 100,000 suddenly may throttle.

## E. Provisioned mode details
- You set read and write units separately. Minimum 1 RCU and 1 WCU.
- Increase as often as needed (but not instantly huge jumps; limits apply).
- Decreases are limited: you start each UTC day with 4 decreases, gain 1 per hour, up to 27 per day (verified).
- Table and each GSI have separate decrease limits.
- Default quotas: 40,000 RCU and 40,000 WCU per table; 80,000 RCU/WCU per account per Region (verified; can be raised).
- Exceeding provisioned capacity → throttling (`ProvisionedThroughputExceededException`, HTTP 400).
- Auto scaling (Application Auto Scaling): set min, max and target utilization (for example 70%). Scales when consumption breaches the target for 2 consecutive minutes; scales down after 15 consecutive low data points. Updates take several minutes, so sudden spikes may still throttle.
- Auto scaling is for gradual change. Use on-demand for sharp unpredictable spikes.
- Reserved capacity: commit for 1 or 3 years for provisioned RCU/WCU to save money (not for on-demand). Account limit 1,000,000 reserved units by default (verified).
- Burst capacity: DynamoDB keeps unused capacity for a short time (about 5 minutes) to absorb short bursts (verify).
- Adaptive capacity: DynamoDB reshapes partitions and gives more throughput to hot keys, but the per-partition ceiling still applies (verify).
- Warm throughput: pre-set a table or index to handle higher throughput (useful before launches or migrations). Works for on-demand and provisioned (verify).

## F. Throttling (reading the signals)
- Provisioned throttle: `ProvisionedThroughputExceededException`; SDK retries with backoff automatically.
- Metrics split by cause: `ReadProvisionedThroughputThrottleEvents`, `WriteProvisionedThroughputThrottleEvents`, `ReadKeyRangeThroughputThrottleEvents` / `WriteKeyRange...` (partition limit), `Read/WriteMaxOnDemandThroughputThrottleEvents` (your cap), `Read/WriteAccountLimitThrottleEvents` (account limit).
- Key-range throttle with spare table capacity = hot partition.
- `ThrottledRequests` counts a whole request throttled; for batches only when every item is throttled; use the per-event metrics for batches.
- Fixes: better partition key, write sharding, raise capacity or switch to on-demand, spread traffic, add backoff with jitter, cache reads with DAX, batch smoothly, remove unneeded GSIs.
- A throttled GSI can block table writes (back-pressure). Give the GSI enough write capacity.
- Large scans or exports run in parallel can steal capacity. Use Export to S3 (does not use capacity).

## G. Secondary indexes (verified)
- GSI (global secondary index): different partition key and optional sort key from the table. Spans all partitions.
- LSI (local secondary index): same partition key as the table, different sort key. Only within one item collection.
- Each index is a copy of selected attributes with a different key. DynamoDB keeps it in sync automatically.
- Index key attributes must be top-level String, Number or Binary.
- Differences:
  - Creation: GSI anytime (add or delete later). LSI only when the table is created; cannot be added or removed afterwards.
  - Key: GSI simple or composite. LSI must be composite.
  - Capacity: GSI has its own capacity settings. LSI uses the base table's capacity.
  - Consistency: GSI eventual only. LSI supports eventual or strong.
  - Size limit: LSI limits each partition key value's total (table + index) to 10 GB item collection size. GSI has no such limit.
  - Attributes: GSI returns only projected attributes. LSI can fetch unprojected attributes from the base table.
- Limits (verified): 20 GSIs per table by default, 5 LSIs per table. Up to 100 projected (INCLUDE) attributes across all indexes of a table.
- Projection types: KEYS_ONLY, INCLUDE (chosen attributes), ALL. Smaller projection = cheaper writes and storage.
- Every index uses the same table class and capacity mode as the base table.
- Adding a GSI to a large table backfills it; track `OnlineIndexPercentageProgress`. You can query it only when ACTIVE.
- Sparse index: only items that have the index key attribute appear in the index. Use it to index a small subset (open orders, flagged items). Cheap and fast.
- Index overloading: reuse generic GSI keys (`GSI1PK`, `GSI1SK`) for different entity types in single-table design.
- GSI key choice rules are the same as the table: spread traffic evenly.
- DescribeTable index size/item counts refresh about every 6 hours.
- Cross-account Scan on a secondary index with resource-based policies is not supported.
- Index writes cost: a write that changes indexed attributes writes to every affected index.
- Deleting a table deletes its indexes.
- Multi-attribute composite keys and newer index features may exist (verify in current docs before relying on them).

## H. Query patterns using indexes
- "Find by email" → GSI with email as partition key.
- "Orders by status and date" → GSI partition key status (careful with hot key) or sparse GSI with composite key.
- "Latest 10 items for a user" → Query with `ScanIndexForward=false` and `Limit=10`.
- "Items in date range per user" → sort key as date, `BETWEEN`.
- "All items of a type" → avoid Scan; use GSI with type + time bucket as key.
- "Top-N across the whole table" → needs a different design (aggregate table, OpenSearch, or analytics export).
- Write sharding: add a suffix 0–N to a hot partition key, write to a random suffix, query all N suffixes and merge.
- Calculated suffix (hash of another attribute) lets you find a specific item without querying all shards.

## I. Performance rules (what actually makes it fast)
- Use GetItem/Query with the full key. Avoid Scan.
- Spread load evenly over many partition key values.
- Prefer eventually consistent reads (half the cost) unless you need the latest value.
- Keep items small; keep attribute names short; store big blobs in S3.
- Batch calls (BatchGetItem/BatchWriteItem) to cut round trips; retry unprocessed items.
- Parallelize with several workers; avoid one hot key.
- Use projection expressions to reduce network payload.
- Use sparse and projection-limited indexes.
- Cache hot reads with DAX or ElastiCache.
- Use SDK retries with exponential backoff and jitter (default in AWS SDKs).
- Put app compute in the same Region as the table. Use VPC gateway endpoint for private, low-latency access without NAT.
- For bulk loading new tables, use Import from S3 (no capacity used) rather than millions of PutItems.
- For analytics, use Export to S3 or zero-ETL; do not run big scans on the live table.
- Use on-demand or high enough provisioned capacity before big imports/migrations (warm throughput).
- Avoid "read-modify-write" loops with strong contention on one item; use atomic updates.
- Use table class Standard-IA for cold large tables to save storage cost (does not improve speed).

## J. DAX (DynamoDB Accelerator) – verified
- Managed in-memory cache for DynamoDB. Microsecond reads for eventually consistent data.
- API-compatible: use the DAX client in place of the DynamoDB client; minimal code changes (Java, Python, Node.js, Go, .NET).
- Write-through: writes go through DAX to DynamoDB and update the cache.
- Item cache (GetItem/BatchGetItem) and query cache (Query/Scan results).
- Strongly consistent reads and TransactGetItems are passed through to DynamoDB (not cached).
- Good for: read-heavy workloads, hot keys, repeated reads of the same items, bursty reads, saving read capacity, fastest response (real-time bidding, gaming, trading).
- Not good for: strongly consistent reads needed, write-heavy apps (replication load), apps without repeated reads (cache hit rate below about 90% hurts), apps that don't need microseconds.
- Runs in your VPC (EC2-VPC only). Cluster of nodes (one primary + replicas, Multi-AZ for availability).
- Encryption at rest and in transit (TLS) supported; access control with IAM; can be used cross-account.
- Cache metadata keeps top-level attribute names forever; an unbounded set of attribute names (timestamps/UUIDs as attribute names) can exhaust memory.
- DAX cluster role needs `dynamodb:DescribeTable`.
- DAX vs ElastiCache: DAX is DynamoDB-aware (no cache logic in the app); ElastiCache needs app code for cache-aside.
- DAX does not fix a bad partition key by itself; it hides read hotspots only for cached reads.

## K. Table classes (verified)
- Standard (default): for most workloads.
- Standard-Infrequent Access (Standard-IA): lower storage price, higher request price; for tables where storage is the dominant cost (logs, old orders, history).
- Class can be changed any time (not permanent). Indexes use the same class as the table. Works with global tables and CloudFormation.
- Rule of thumb: use Standard-IA when storage is about half or more of your throughput cost (verify).

## L. Vector search (newer, awareness)
- DynamoDB now supports vector indexes and a `SearchVectors` API for similarity search over embeddings stored in items (verify availability by Region).
- Quotas in docs: 5 vector indexes per table, up to 4,096 dimensions, TopK up to 100 per request, base table size limits apply without allow-listing.
- Compare with pgvector on Aurora, OpenSearch k-NN, MemoryDB vector search, S3 Vectors.

## M. Scenarios (if → then, because)
- If traffic is unpredictable or the table is new → on-demand, because there is no capacity planning.
- If traffic is steady and predictable → provisioned with auto scaling (and reserved capacity), because it is cheaper per request.
- If a job is throttled while table capacity looks fine → hot partition; check key-range throttle metrics and redesign the key or shard writes.
- If a sale causes a sudden 5x spike beyond past peaks → pre-warm (warm throughput) or ramp up, because on-demand handles only double the previous peak instantly.
- If you must query by a different key later → add a GSI (can be added any time).
- If you need strongly consistent query on an alternate sort key → LSI, but it must be created with the table.
- If you only need a few attributes from the index → INCLUDE or KEYS_ONLY projection to cut cost.
- If most items don't have the attribute → sparse GSI.
- If GSI writes throttle and slow the base table → increase GSI write capacity (or on-demand).
- If reads are repeated and you need microseconds → DAX.
- If your reads must be strongly consistent → DAX will not help.
- If an item is read 100,000 times per second → cache (DAX) or replicate the key (read sharding), because one partition caps throughput.
- If you need to count rows in a huge table → maintain a counter item or export; Scan/COUNT reads everything.
- If a table is mostly old data and rarely read → Standard-IA table class + TTL for expiry.
- If storage cost is high and data is cold → export to S3 and delete from DynamoDB.
- If you want to stop surprise bills in on-demand → set maximum throughput.
- If provisioned decreases are blocked → you used the daily decrease allowance (4 + 1 per hour).
- If a batch load is slow and costly → Import from S3, or on-demand + parallel BatchWriteItem with backoff.
- If the app sees `ProvisionedThroughputExceededException` after scaling events → auto scaling lag; raise min capacity, use on-demand, or retry with backoff.

## Verified from AWS docs on 2026-10-02
Capacity modes and scaling, read/write unit rules, secondary indexes, DAX, table classes, service quotas, CloudWatch metrics pages were read. Not confirmed (verify): burst capacity duration, adaptive capacity details, warm throughput specifics, Standard-IA break-even rule, mode switching frequency wording, vector search availability.

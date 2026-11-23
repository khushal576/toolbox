# DocumentDB – 3. Change streams, integrations, migration, performance, cost, monitoring, limits, scenarios

Short notes. Each point is a fact you can be asked about.

## A. Change streams (verified)
- A **time-ordered stream of change events** for collections, like MongoDB change streams. Events are stored for **3 hours by default** and can be kept up to **7 days** (`change_stream_log_retention_duration`).
- **Disabled by default**; enable per collection, per database, or cluster-wide with `modifyChangeStreams` (empty string = wildcard). Enabled if the collection, its database, or all databases are enabled. Dropping a collection doesn't disable the stream if the parent is enabled.
- List enabled streams with `$listChangeStreams`.
- Supported events: insert, update, delete, replace, and DDL events `createCollection`, `createIndexes` via `showExpandedEvents` (8.0.2+). Supported stages: `$match`, `$project`, `$redact`, `$addFields`, `$replaceRoot`, `$changeStreamSplitLargeEvent` (8.0.2+).
- Update events show only the changed fields. Use `fullDocument: 'updateLookup'` to get the latest full document (may reflect later changes).
- **Resume** with a resume token (`resumeAfter`), `startAtOperationTime` (4.0+; mutually exclusive with `resumeAfter`), or `postBatchResumeToken` (cheaper than an old token because it skips unmatched entries).
- Event limit 16 MB; larger events need `$changeStreamSplitLargeEvent` (8.0.2+) or you get a read failure.
- **Where to read**: engine 3.6/4.0: **primary only** (set `readPreference primary`). Engine 5.0: primary or secondaries (use `secondary` read preference; lag possible; use `startAtOperationTime`/tokens; monitor `DBInstanceReplicaLag`; works with global clusters).
- Long-running writes (`updateMany`, `deleteMany`) can stall change stream writing until they finish.
- Cost: extra I/O and storage while enabled (metric `ChangeStreamLogSize`). Log retention won't delete older logs until size is above about 50 GB (51,200 MB) (verified note).
- Uncommitted or aborted transactions don't appear in change streams.
- TTL deletions generate delete events (verify).
- Use cases: change notification, search index sync (OpenSearch), analytics (Redshift), cache invalidation, event-driven microservices, CDC to a lake.

## B. Integrations
- **Lambda**: a function (or app) reads the change stream and processes events; also triggered by DocumentDB as an event source (Lambda event source mapping for DocumentDB; verify details: batch size, starting position, collection must have change streams enabled). Needs VPC access to reach DocumentDB.
- **Kinesis / MSK / EventBridge**: stream change events to downstream systems via Lambda or MSK Connect / custom consumers; DMS with change stream-based CDC can also publish.
- **OpenSearch**: sync documents for full-text search through change streams or DMS.
- **Redshift / S3 / Glue / Athena**: export via DMS, mongodump/mongoexport to S3, or Glue connection (JDBC-like MongoDB connector) for ETL; DocumentDB is a Glue source via the MongoDB connector (verify). Zero-ETL to Redshift is not a DocumentDB feature (verify).
- **DMS**: DocumentDB can be a **source** or **target**. Targets: S3, Kinesis, OpenSearch, Redshift; sources: MongoDB, DocumentDB, relational (with mapping).
- **Secrets Manager**: store and rotate the primary password; apps fetch secrets at runtime.
- **CloudWatch** (metrics/logs/alarms), **CloudTrail** (API), **EventBridge** (cluster events), **SNS** (event subscriptions).
- **Bedrock Knowledge Bases**: DocumentDB can serve as a vector store (verify current support list) alongside OpenSearch Serverless, Aurora PostgreSQL, Neptune Analytics.
- **CloudFormation / CDK**: define clusters, instances, parameter groups, subnet groups; enable termination protection and deletion protection.
- **SageMaker / Comprehend**: not built in; call from application code.
- **Elastic Beanstalk / ECS / EKS / Lambda / EC2** apps connect over the VPC; use security group references.
- **Compass / mongosh / MongoDB drivers** for dev tools. Use the AWS-provided CA bundle.

## C. Migration (verified overview)
- Approaches to migrate MongoDB → DocumentDB:
  - **Offline**: `mongodump` then `mongorestore` (simple, downtime). Use MongoDB Database Tools ≤ 100.11.0. Admin DB isn't dumped; recreate users and roles.
  - **Online**: **AWS DMS** with full load + change data capture (CDC) to keep in sync, then cut over.
  - **Hybrid**: bulk copy first (dump/restore or DMS full load), then DMS CDC for changes since the dump.
- Before migrating: run the AWS **Compatibility Tool** to detect unsupported features and use the **Index Tool** to extract indexes from MongoDB and create them on DocumentDB **before** loading data (faster load).
- Test the full application on DocumentDB first (functionality, performance, operations, cost).
- Migrating **sharded MongoDB** → use **elastic clusters**. Migrating from **Couchbase** has a documented path (extract and load).
- Upgrading DocumentDB itself: in-place major version upgrade, minor upgrades, or migrate with DMS between clusters/versions. Extended Support and LTS options exist for older versions.
- Relational → DocumentDB: model tables into documents (embed child rows), use DMS or custom ETL.
- Keep a rollback plan: keep source in sync until after validation.
- Choose instance sizes by working set size (index + hot data); see section D.

## D. Performance tuning (verified best practices)
- **Instance sizing**: only about two-thirds of RAM is available for cache. Fit data + indexes in memory. Monitor `BufferCacheHitRatio` (higher is better); if it's low, scale up until it stops improving. `IndexBufferCacheHitRatio` for index pages.
- If CPU stays above 80%, scale up. If `FreeableMemory` dips below about 10% of instance memory often, scale up. `SwapUsage` should be near zero.
- Use **replicas** for reads (`secondaryPreferred`); keep analytic queries on a separate replica (custom replica) or isolate them to protect the operational cache.
- **Indexes**: create the right ones; use `explain()`; avoid collection scans on big collections; keep indexes few (≤5 as guideline); drop unused indexes; avoid low-cardinality indexes (booleans, day of week).
- **Profiler** logs slow operations; use it to find missing indexes and expensive queries.
- **Aggregation**: `$match` first; reduce data early; consider `allowDiskUse` for big aggregations (verify); use `$lookup` plan hints when needed.
- **Writes**: batch inserts/updates; many concurrent `batchInsert`/`batchUpdate` can drain `FreeableMemory` on the primary – lower concurrency or scale up.
- **Connection management**: use connection pools; stay under per-instance connection limits (for example r5.large 3,400 total / 1,100 active; t3.medium 1,000 / 102). Metrics: `DatabaseConnections`, `DatabaseConnectionsMax/Limit`, `DatabaseConnectionsActiveMax`.
- Cursors and transactions have per-instance quotas (metrics `DatabaseCursors*`, `TransactionsOpen*`).
- Large documents slow reads; keep documents small, avoid unbounded arrays.
- Low-memory throttling: `LowMemThrottleQueueDepth`, `LowMemNumOperationsThrottled` rise when memory is short → scale up.
- Prefer the same instance class for primary and replicas.
- Spread load: the reader endpoint balances connections, not queries; long-lived connections may stick to one replica.
- Use NVMe-backed (R6GD) when the working set exceeds RAM and you want a lower-latency tier.
- Be careful with TTL deletes at scale (I/O cost); use rolling collections for time-series.
- Disk queue depth and write latency rising → check I/O; consider I/O-Optimized.

## E. Cost (verified)
- You pay for: **instance hours** (billed per second, 10-minute minimum), **storage** (GB-month used, auto-grows), **I/O requests** (per million; Standard storage; none with I/O-Optimized), **backup storage** (beyond the free allowance), **data transfer**, and **change streams/TTL** (extra I/O + log storage). CloudWatch Logs charges apply to audit/profiler logs.
- **Serverless** charges per DCU-hour used (per second).
- **Storage configuration**: I/O-Optimized when I/O ≥ about 25% of total cost; else Standard.
- Savings ideas:
  - Single-instance cluster for dev/test (storage is still 6-way durable) (verified).
  - Stop dev/test clusters when not used.
  - Serverless for spiky/dev workloads.
  - Right-size by `BufferCacheHitRatio`/CPU; use Graviton (R6G/R8G).
  - Reserved Instances for steady production (verify availability).
  - Disable change streams and TTL if unused.
  - Replace TTL on huge collections with rolling collections.
  - Remove unused indexes; shorter backup retention; delete old snapshots.
  - Billing alerts at 50% and 75% of expected monthly bill (verified recommendation).
  - Keep apps in the same AZ/Region to limit transfer cost.
- Free trial: 1-month free trial offered (verified).

## F. Monitoring and troubleshooting
- Metrics (verified list):
  - Resource: `CPUUtilization`, `FreeableMemory`, `SwapUsage`, `FreeLocalStorage`, `DatabaseConnections*`, `DatabaseCursors*`, `TransactionsOpen*`, `LowMem*`.
  - Storage/backup: `VolumeBytesUsed`, `BackupRetentionPeriodStorageUsed`, `SnapshotStorageUsed`, `TotalBackupStorageBilled`, `ChangeStreamLogSize`.
  - I/O: `ReadIOPS`, `WriteIOPS`, `ReadLatency`, `WriteLatency`, `ReadThroughput`, `WriteThroughput`, `DiskQueueDepth`, `VolumeReadIOPs`, `VolumeWriteIOPs` (billed I/O, reported every 5 minutes).
  - Latency/lag: `DBClusterReplicaLagMaximum/Minimum`, `DBInstanceReplicaLag`.
  - Cache: `BufferCacheHitRatio`, `IndexBufferCacheHitRatio`, NVMe metrics.
  - Operations: `OpcountersInsert/Query/Update/Delete/Command/Getmore`, `Documents*`, `TTLDeletedDocuments`, `TransactionsStarted/Committed/Aborted`, command-level metrics `Command.<name>.AvgDuration/P100Duration/MaxConcurrent`.
  - System: `AvailableMVCCIds` (when it reaches 0 the cluster goes read-only until IDs are recycled), `EngineUptime`, `LongestActiveGCRuntime`.
  - T3: `CPUCreditBalance`, `CPUCreditUsage`.
  - Network: `NetworkThroughput`, `StorageNetworkThroughput`; compare their sum with the instance class limit.
- Idle clusters show ~50 opcounters from health checks (verified note). `DatabaseConnections` shows only customer connections (server status may show up to 10 more).
- Alarms: CPU, FreeableMemory, DatabaseConnections vs limit, replica lag (also >10 s), BufferCacheHitRatio drop, VolumeBytesUsed growth, AvailableMVCCIds low, DiskQueueDepth.
- Troubleshooting (symptom → cause → fix):
  - Slow queries → missing index/collection scan → profiler + explain, add index.
  - Low `BufferCacheHitRatio` → working set bigger than RAM → bigger instance or fewer indexes.
  - High CPU → heavy queries/aggregations → tune, add replicas, scale up.
  - Connection errors/limits → too many connections → pooling, bigger class, fix leaks.
  - Replica lag → heavy writes/long replica queries → see file 2.
  - `FreeableMemory` ~0 under batch writes → reduce batch concurrency or scale up.
  - Cluster read-only, `AvailableMVCCIds` near 0 → very high write rate and slow garbage collection; reduce write load, long transactions; check `LongestActiveGCRuntime`.
  - Authorization failure → wrong database context or missing role.
  - Cannot connect → not in VPC, SG missing 27017, TLS/CA bundle, wrong replica set settings.
  - "Retryable writes are not supported" → add `retryWrites=false` (engines before 8.0.2).
  - Index build fails/hangs → another build running on the same collection.
  - TTL not deleting on time → best effort; monitor `TTLDeletedDocuments`; load or index size.
  - Change stream read failure → event over 16 MB; use split stage; or reading from replica in 3.6/4.0.
  - Audit logs missing → missing parameter or CloudWatch Logs export step.
  - Global failover blocked → engine version mismatch.
  - Storage cost jump → change stream log, many indexes, large documents, clones/snapshots.

## G. Limits and numbers (verified)
- Clusters: 40 per account per Region; instances: 40 (shared with RDS/Neptune); parameter groups 50; subnet groups 50 (20 subnets each); event subscriptions 20; manual cluster snapshots 100; read replicas per cluster 15; tags per resource 50; security groups per instance 5.
- Elastic clusters: 20 per Region; 1,024 vCPU; 32 shards; 64 vCPU per shard; 16 instances per shard; 4 PiB; 128 TiB per shard.
- Cluster size 256 TiB (8.0) / 128 TiB; collection 32 TiB (excluding indexes); collections per cluster 100,000; databases 100,000.
- Document size 16 MiB; nesting depth 200 (100 on elastic); index key 2,048 bytes; indexes per collection 64; compound index keys 32; writes per batch 100,000; aggregation stages 500; users per cluster 1,000 (100 elastic); user-defined roles 100.
- Connections / cursors / open transactions (examples): t3.medium 1,000 / 30 / 50; r5.large 3,400 / 450 / 200; r5.xlarge 7,000 / 450 / 400; r5.2xlarge 14,200 / 450 / 800; r5.4xlarge 28,400 / 760 / 1,600; r5.8xlarge and above 60,000 connections. Active connections per class: t3 102; r5.large 1,100; r5.xlarge 2,700; r5.2xlarge and above 4,500.
- Naming: cluster/instance identifiers 1–63 letters/numbers/hyphens, start with a letter, no trailing or double hyphens, unique across RDS/Neptune/DocumentDB per account per Region. Primary username 1–63 alphanumerics starting with a letter; primary password 8–100 printable ASCII except `/`, `"`, `@`.
- Vector: 2,000 dimensions indexed (16,000 stored); HNSW m 2–100, efConstruction 4–1000, efSearch 1–1000; IVFFlat lists max depends on instance (for example r5.large 915 at 500 dims).
- Backup retention 1–35 days; PITR to within about 5 minutes; global clusters up to 10 secondary Regions; secondary up to 16 replicas.
- Change stream retention default 3 hours, max 7 days.
- Billing granularity per second with a 10-minute minimum.

## H. Mixed scenarios (if → then, because)
1. A company runs MongoDB 4.2 on EC2 with 2 TB and wants managed ops with the least code change → DocumentDB; migrate with dump/restore (offline) or DMS (online).
2. They need near-zero downtime → DMS full load + CDC, then cut over.
3. Before migrating they want to know if the app will break → AWS Compatibility Tool and a full app test on DocumentDB.
4. The product catalog needs flexible attributes and full-text/geo queries → DocumentDB with text and 2dsphere indexes.
5. Product recommendations by similarity → DocumentDB vector index (HNSW, cosine) or OpenSearch; pick DocumentDB when documents already live there.
6. A mobile app with spiky user traffic and a team that doesn't want to size servers → DocumentDB Serverless (or DynamoDB if key-based).
7. A leaderboard with millions of key lookups per second → DynamoDB (not DocumentDB).
8. A search index must be kept in sync → change streams → Lambda → OpenSearch.
9. Nightly analytics shouldn't slow the app → run on a dedicated replica; or export to S3 with DMS/mongoexport.
10. The primary instance is overloaded by writes → scale up; if beyond largest class → elastic cluster with a shard key.
11. The working set is 120 GB → pick an instance with at least ~180 GB RAM (two-thirds usable).
12. A regulator requires encryption with a customer key → CMK at creation; audit logs to CloudWatch.
13. A team needs read-only access to one DB → `read` role on that DB.
14. A Lambda should authenticate without passwords → IAM auth (5.0 instance-based) with the Lambda execution role.
15. Global users need local reads and DR → global cluster with secondaries in their Regions.
16. A dev cluster costs too much → single instance, stop when idle, or Serverless.
17. Old events need deleting from a 2 TB time-series collection cheaply → rolling collections and drop old ones.
18. A heavy TTL index inflates the I/O bill → switch to rolling collections.
19. A cluster needs to survive an AZ failure → 3 instances in 3 AZs, failover priorities set.
20. A restore is needed from last Tuesday 14:05 → PITR within retention (max 35 days) to a new cluster; if older than that → manual snapshot.
21. Index builds keep failing on a collection → only one build at a time per collection; wait or cancel the running one.
22. An app gets "Retryable writes are not supported" → set `retryWrites=false` or upgrade to engine 8.0.2+.
23. A migration from a sharded MongoDB cluster → elastic cluster.
24. Reads must hit replicas → `readPreference=secondaryPreferred` and the reader endpoint.
25. A query on `$regex` is slow → prefix regex, supporting index, and `hint()`.

## Verified from AWS docs on 2026-10-02
Change streams page, CloudWatch metrics page, quotas page, best practices, migration index, elastic cluster pages, vector search page, auditing page were read. Not confirmed (verify): Lambda event source mapping specifics, Glue connector details, DMS target list, Bedrock knowledge base vector store support for DocumentDB, Reserved Instance availability, `allowDiskUse` support details.

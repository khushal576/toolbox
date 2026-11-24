# DynamoDB – 3. Availability, backup and restore, Global Tables, Streams, TTL, export/import

Short notes. Each point is a fact you can be asked about.

## A. Built-in availability and durability
- Every table is stored across multiple AZs in the Region automatically. You cannot turn Multi-AZ off or configure it.
- Writes are acknowledged after they are durable on multiple AZs.
- No maintenance windows, no failover to manage, no patching downtime.
- Single-Region tables are designed for 99.99% availability; global tables for 99.999% (verify exact SLA wording).
- A Region outage affects single-Region tables. For Region-level resilience use global tables or cross-Region backup restore.
- Deletion protection: when on, the table cannot be deleted until you turn it off (protects against accidental `DeleteTable`). Turn it on for production tables.
- Accidental deletes of items are not undoable without backups/PITR. Plan backups.

## B. Backups – the three options
- **On-demand backups**: full copies taken whenever you ask. Kept until you delete them. No effect on table performance. Restore to a new table.
- **Point-in-time recovery (PITR)**: continuous backups. Restore to any second within the recovery window.
- **AWS Backup**: central policies and schedules for DynamoDB (and other services), cross-account/Region copies, vault lock, lifecycle to cold storage. Restore limits: 50 concurrent restores totaling 25 TB (vs 50 TB for native backups) (verified).
- Backups and restores use no table read/write capacity and do not slow the table.
- Restore always creates a **new table**. It does not overwrite the source table.
- Restore time depends on the size of the table (hours for big tables), not on the time since backup.

## C. PITR details (verified)
- Off by default. Turn it on per table.
- Recovery window is configurable 1 to 35 days (`RecoveryPeriodInDays`, default 35). Per-second granularity.
- Latest restorable time is typically about 5 minutes ago.
- Price is based on table size (plus LSI size). Shortening the window does not lower the price.
- If you turn PITR off and on again, the history resets.
- Can be enabled on each local replica of a global table. A restore creates an independent table, not part of the global table (you can create a new global table from it).
- Restores can go cross-Region (and between commercial, China and GovCloud Regions). You pay for data transfer out of the source Region and for creating the new table.
- CloudTrail logs PITR actions.
- Export to S3 and zero-ETL integrations require PITR.
- What a restore may not bring back (verify, then reconfigure): auto scaling settings, IAM policies, CloudWatch alarms/metrics, tags (can be copied), stream settings, TTL settings, deletion protection. GSIs and LSIs can be restored or skipped.
- Use PITR for "undo" after bad deploys, accidental deletes, or corruption; use on-demand backups for long-term snapshots (like before a migration).
- Restore limits (verified): up to 50 concurrent restores totaling 50 TB via native on-demand or continuous backups.

## D. Export to S3 and Import from S3 (verified)
- Export needs PITR on. Exports data from any point in the PITR window to S3.
- Full export, incremental export (window 15 minutes to 24 hours), and filtered exports are supported.
- No read capacity used and no impact on table performance or availability. Asynchronous; no completion-time SLA.
- Formats: DynamoDB JSON and Amazon Ion. Can write to an S3 bucket in another account and Region. Encrypted end-to-end.
- Cost: full export priced by table size at that point in time; incremental by data processed (10 MB minimum); plus S3 storage and PUT costs.
- Export limits: up to 300 concurrent exports or 100 TB in flight (verified).
- Use exports to run Athena/Glue/EMR/Redshift analytics without touching the live table, to archive cold data, or to copy a table.
- Import from S3 creates a **new table** from CSV, DynamoDB JSON or Ion files (verify formats). Does not use write capacity. Up to 50 concurrent imports; 15 TB total in us-east-1, us-west-2, eu-west-1 and 1 TB elsewhere; up to 50,000 S3 objects per import job (verified).
- Import is the cheapest, fastest bulk load into a new table. It cannot load into an existing table.
- Use import for migrations and restoring from exports.

## E. Global tables (verified)
- Fully managed, multi-Region, multi-active replication. Any replica accepts reads and writes.
- Current version is 2019.11.21 (version 2017.11.29 is legacy).
- Replication is asynchronous (typically about a second), with **last-writer-wins** conflict resolution by timestamp.
- Two consistency modes (chosen at creation, cannot be changed, replicas cannot be mixed):
  - **MREC** (multi-Region eventual consistency, default): writes replicate asynchronously; reads in another Region may be stale briefly. Low latency.
  - **MRSC** (multi-Region strong consistency): strongly consistent reads across Regions; zero RPO; higher write latency; same-account only; limited number of tables (400) (verified).
- Two account models: same-account (all replicas in one account) and multi-account (replicas in different accounts, separate IAM/KMS/billing/governance). MRSC supports only same-account.
- Needs DynamoDB Streams (managed for you), compatible capacity settings; table-level write throughput quotas must match in every replica Region.
- Adding a replica backfills existing data (quota: 10 TB per account per Region per day).
- Billing: replicated writes use replicated write units (rWCU / replicated write request units) in each replica Region, plus normal storage and cross-Region data transfer.
- TTL deletes replicate to all replicas (the first delete is free; replica deletes consume replicated write units).
- Transactions are atomic only within the Region where the write was made. Other Regions can briefly show partial results.
- Strongly consistent reads apply only within a Region (MREC).
- Conflict example: same item updated in two Regions at nearly the same time → the later timestamp wins; the other update is lost. Avoid by routing each item's writes to one home Region when possible.
- Global tables give RPO about 1 second (MREC) and near-zero RTO if the app can switch Regions.
- Use for: DR, low latency for global users, active-active apps, regulatory copies.
- Not for: reducing cost, or conflict-free multi-writer counters (use partitioning by Region).
- Each replica can have its own PITR, backups, KMS key (same-account), and table class settings (verify specifics).
- Monitor `ReplicationLatency` (per ReceivingRegion) and write-capacity consumption by the `Source` dimension (Customer vs GlobalTable).
- Adding replicas: they are online while backfilling; enable Streams on the table first for legacy flows.

## F. DynamoDB Streams (verified)
- Change log of item-level changes (create, update, delete) for a table, kept **24 hours**, then trimmed.
- Stream view types: KEYS_ONLY, NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES. Cannot be edited once set; to change, disable and re-enable (creates a new stream).
- Each stream record appears exactly once; changes to the same item appear in the order they happened (ordering per item, not across items).
- No stream record is written for a write that changes nothing.
- Streams are asynchronous: no impact on table performance. Free to enable; reading uses the Streams API/Lambda (data transfer rules apply).
- Streams have their own endpoint (`streams.dynamodb.<region>.amazonaws.com`).
- Shards: each open shard maps to one table partition; shards split and close automatically; process parent shards before children.
- At most **two** processes should read the same shard at once (one for global tables) or you risk throttling.
- Consumers: Lambda (event source mapping – most common), Kinesis Client Library via the DynamoDB Streams Kinesis Adapter, Apache Flink, custom apps using GetRecords.
- Lambda with Streams: one function instance per shard by default; `ParallelizationFactor` up to 10 for more concurrency per shard while keeping per-item order; batch size/window; retry limits; bisect batch on error; on-failure destination; event filtering to reduce invocations.
- Failure behaviour: a failing batch blocks that shard until it succeeds or records expire (24 h), unless you set retry limits/bisect/destination. Poison records can stall processing.
- Transactions: records from one transaction may appear at different times and interleaved; do not assume atomicity in consumers.
- TTL deletions appear as stream records marked as service deletes.
- Use for: reacting to changes, aggregates, cache invalidation, replication to other stores, audit trails, fan-out to SNS/SQS/EventBridge, materialized views.
- Not for: long-term history or replay (24 hours only) or many independent consumers → use Kinesis Data Streams for DynamoDB.

## G. Kinesis Data Streams for DynamoDB (verified)
- Alternative change capture sending item changes to a Kinesis data stream in the same account and Region. One KDS per table.
- Longer retention (Kinesis retention up to 365 days), multiple consumers with enhanced fan-out, access to Firehose (to S3/Redshift/OpenSearch) and Managed Service for Apache Flink.
- Records can be out of order or duplicated; use `ApproximateCreationDateTime` (millisecond or microsecond precision) to order and dedupe.
- Includes before and after snapshots of the item and the primary key.
- Binary values are base64 encoded twice (decode twice).
- Billing: DynamoDB charges change data capture units (1 KB of change per item = 1 unit, using the larger of before/after image) plus Kinesis Data Streams charges; no table capacity to provision.
- Streaming to Kinesis does not slow the table; you can have both Streams and KDS enabled.
- Metrics: `AgeOfOldestUnreplicatedRecord`, `FailedToReplicateRecordCount`, `ThrottledPutRecordCount`, `ConsumedChangeDataCaptureUnits`.
- Pick KDS when you need replay beyond 24h, many consumers, or Firehose/Flink pipelines. Pick DynamoDB Streams + Lambda for simple triggers.

## H. TTL – Time to Live (verified)
- Enable TTL on a table and name one attribute that holds each item's expiry time.
- The TTL attribute must be type **Number**, in **Unix epoch time (seconds)**. Items where it is another type are ignored.
- Items with no TTL attribute never expire.
- DynamoDB deletes expired items in the background, **typically within a few days** after the expiry time. Not exact and not instant.
- TTL deletes use **no write capacity** (free) in the source Region.
- Expired items that are not yet deleted still appear in reads, Query and Scan. Filter them out yourself with a condition (`ttl > :now`).
- You can still update an expired item that has not been deleted. Setting TTL to a future time (or removing the attribute) saves it. Use a condition expression so you don't resurrect an item that was just deleted.
- TTL deletes are removed from LSIs and GSIs like normal deletes.
- Stream records: TTL deletions show up in DynamoDB Streams as service deletes (the user identity is the DynamoDB service), so consumers can tell them apart from user deletes (verify field).
- Global tables: TTL deletes are replicated to all replicas; the replicated deletes cost replicated write units in each replica Region.
- Metric `TimeToLiveDeletedItemCount` shows how many items were deleted.
- One TTL attribute per table. It must be a top-level attribute (verify).
- Not suitable when a delete must happen at an exact time (legal deadlines, security tokens). Use explicit DeleteItem or filter at read time.
- Typical uses: sessions, temp tokens, cache entries, event logs, rolling window of data, idempotency keys.
- Pair with Streams: when an item expires, a Lambda can archive it to S3 (keep a cheap history while keeping the table small).

## I. Deleting data and retention (privacy, legal)
- Item delete: DeleteItem (or TTL). Data is removed from the table but may remain in:
  - PITR history until the window passes,
  - on-demand backups and AWS Backup recovery points until deleted,
  - exports in S3 (delete those objects too),
  - Streams for 24 hours, Kinesis streams for their retention,
  - global table replicas (delete replicates),
  - downstream copies (Redshift, OpenSearch, data lake).
- Right to erasure needs a plan covering all copies and backup retention windows.
- To keep data for a fixed period only: TTL + shorter PITR window + backup lifecycle.
- To stop data leaving a country: avoid global table replicas in other Regions; deny other Regions with SCP.

## J. Disaster recovery patterns
- Backup and restore (cheapest, slowest): PITR/on-demand/AWS Backup, copy to another Region. RPO minutes-hours, RTO hours (restore time grows with table size).
- Cross-Region PITR restore: restore the table directly into another Region.
- Global tables (MREC): active-active, RPO about 1 second, RTO minutes (app/DNS failover).
- Global tables (MRSC): zero RPO, strong consistency across Regions; accept higher write latency.
- Always combine global tables with PITR and backups, because replication also copies mistakes and deletes.
- Cross-account backup copies protect against account compromise.
- Test restores regularly and measure RTO.

## K. Scenarios (if → then, because)
- If you must undo a bad deploy that corrupted data 20 minutes ago → PITR restore to a new table at a time before the bug, then switch the app or copy items back.
- If an auditor wants a snapshot before a schema migration → on-demand backup.
- If backups must be centrally governed across accounts with retention rules → AWS Backup.
- If you need analytics on a table without touching production capacity → Export to S3 (PITR on) then Athena; or zero-ETL to Redshift.
- If you must load 500 GB into a new table cheaply → Import from S3.
- If users worldwide need local low-latency writes → global tables (MREC).
- If you can't tolerate any data loss on Region failure → MRSC global tables.
- If two Regions update the same item at once → last writer wins; design so one Region owns each item, or merge in the app.
- If an action must run when an item changes → Streams + Lambda.
- If you need to replay changes from 3 days ago → Kinesis Data Streams for DynamoDB (24-hour Streams is not enough).
- If several teams need the change feed independently → Kinesis Data Streams with enhanced fan-out.
- If a Lambda on a stream is stuck on one record → add retry limits, bisect batch, failure destination; fix the bad record.
- If sessions should disappear after 30 minutes → TTL attribute set to now + 1800 seconds, and filter by `ttl > now` in reads.
- If an item must be deleted at exactly midnight for compliance → explicit delete job, not TTL.
- If you want to archive expired items → Streams + Lambda reads the service-delete record and writes to S3.
- If a TTL value is stored as a string or in milliseconds → TTL ignores it (needs Number in seconds).
- If production tables get deleted by mistake → deletion protection + restricted IAM + PITR.
- If a restored table loses its auto scaling/alarms/TTL setup → re-create those; restore does not bring all settings (verify list).
- If compliance needs cross-account backup copies → AWS Backup with cross-account copy and vault lock.

## Verified from AWS docs on 2026-10-02
PITR page, export to S3 overview and limits, global tables overview and quotas, Streams page, Kinesis Data Streams for DynamoDB page, TTL page, service quotas were read. Not confirmed (verify): SLA percentages, exact list of what restore does not bring back, import formats, MRSC replica count details, TTL stream field names, TTL top-level attribute rule.

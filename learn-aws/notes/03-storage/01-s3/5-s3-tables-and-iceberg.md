# S3 – 5. S3 Tables, Apache Iceberg, open table formats, S3 Vectors

Short notes. Each point is a fact you can be asked about.

## A. The problem these solve
- Plain files on S3 (Parquet) cannot update or delete single rows, cannot do safe concurrent writes, and pile up small files.
- Table formats add a metadata layer on top of files: transactions, row-level changes, time travel, schema change, better planning.
- Open table formats: Apache Iceberg, Apache Hudi, Delta Lake. On AWS, Iceberg has the broadest and deepest support.
- S3 Tables = a bucket type that stores Iceberg tables and runs the table maintenance for you.

## B. Apache Iceberg basics
- Iceberg is a table format, not a storage engine or a query engine. Engines (Athena, Spark, Flink, Trino, Redshift, Snowflake) read and write it.
- Layers: catalog (points to the current metadata file) → metadata file (schema, partition spec, snapshots) → manifest list → manifest files → data files (Parquet/ORC/Avro).
- Every write creates a new snapshot. Readers see a consistent snapshot. Writers use optimistic concurrency (a commit fails and retries if someone else committed first).
- Time travel: query the table as of a snapshot ID or timestamp. Roll back to an older snapshot.
- Schema evolution: add, drop, rename, reorder, widen types without rewriting data (columns are tracked by ID).
- Partition evolution: change partitioning later; old data keeps old layout, new data uses the new one.
- Hidden partitioning: partition by a transform (`day(ts)`, `bucket(16, id)`, `truncate`, `year`, `month`, `hour`) and queries filter on the raw column; no extra partition column needed.
- Row-level changes: INSERT, UPDATE, DELETE, MERGE INTO.
- Copy-on-write (COW): rewrite whole data files on update/delete. Reads are fast, writes are heavier.
- Merge-on-read (MOR): write small delete files and merge on read. Writes are fast, reads do extra work until compaction.
- Iceberg V3 adds deletion vectors, row lineage, column default values, and new types (variant, geometry, geography, nanosecond timestamps). S3 table buckets support V3.
- Compaction (rewrite small files into big ones) and snapshot expiration are routine maintenance. Without them, tables slow down and cost more.
- Orphan files: data files not referenced by any snapshot (from failed writes). Remove them periodically.
- Deleting data for privacy: DELETE, then expire snapshots and remove orphans so old files really disappear.
- Statistics in manifests (min/max per column) let engines skip files.
- Iceberg tables in Athena: `CREATE TABLE ... TBLPROPERTIES ('table_type'='ICEBERG')`; supports INSERT/UPDATE/DELETE/MERGE, time travel; `OPTIMIZE` compacts; `VACUUM` expires snapshots and removes orphans.
- Glue ETL, EMR/Spark, Flink, Firehose (to Iceberg tables) can write Iceberg.
- Redshift can query Iceberg tables in S3 via Spectrum and S3 Tables via the catalog.

## C. Hudi and Delta (for comparison)
- Hudi: record-level upserts, indexes, COW and MOR table types, strong for streaming upserts and CDC.
- Delta Lake: Spark/Databricks-origin, transaction log, time travel; supported on AWS (Glue, EMR, Athena for Spark).
- Pick Iceberg by default on AWS (Athena, Redshift, Glue, EMR, S3 Tables, Lake Formation support). Pick Hudi for heavy record-level upsert streaming pipelines. Pick Delta if your team and tools are already Delta-centric.
- Plain Parquet + partitions still fine for append-only, rarely-changed data.

## D. What S3 Tables is
- A purpose-built storage type: **table buckets** store **tables** as Iceberg tables (a subresource, not normal objects you list).
- Hierarchy: table bucket → namespace → table.
- Higher transactions per second and better query throughput than self-managed Iceberg in a general purpose bucket.
- Same durability, availability and scalability as other S3 bucket types.
- AWS runs maintenance automatically: compaction, snapshot management, unreferenced file removal.
- Query with any Iceberg-compatible engine: Athena, Redshift, EMR/Spark, Glue, Quick (QuickSight), SageMaker Unified Studio.
- Block Public Access is always on for table buckets and cannot be disabled.
- Permissions use a different service namespace: `s3tables` (not `s3`).
- Table names and column names must be lowercase to work with Glue Data Catalog and Lake Formation. Capital letters make the table invisible to Athena (error "Unsupported Federation Resource - Invalid table or column names").
- Quotas (verified): 100 table buckets per Region per account, 10,000 namespaces per table bucket, 10,000 tables per table bucket (adjustable via Support).
- Supports dual-stack (IPv4/IPv6) endpoints and PrivateLink: `s3tables.<region>.api.aws`.

## E. S3 Tables vs Iceberg on a normal bucket
- S3 Tables: managed maintenance, less ops, table-aware permissions (per table), replication of tables, integrates with Glue catalog in a few clicks.
- Self-managed Iceberg on general purpose bucket: full control, works with any catalog (Glue, Hive metastore, REST, Nessie), you schedule compaction/expire/orphan cleanup, you can use bucket features like lifecycle and Inventory.
- Use S3 Tables when you want low-ops Iceberg on AWS; use general purpose buckets when you need custom catalogs, cross-cloud portability, or existing pipelines.

## F. Automatic maintenance (verified)
- Compaction (table level): on by default. Merges small files into bigger ones and applies row-level deletes. Default target file size 512 MB; configurable 64–512 MB. Works on Parquet, Avro, ORC.
- Compaction strategies: **auto** (default: uses sort if the table has a sort order, else binpack), **binpack** (combine small files, typically over 100 MB), **sort** (organize by sort-order columns), **z-order** (multi-dimensional clustering; needs a sort order in table properties and `s3tables:GetTableData`).
- Sort and z-order cost more than binpack.
- Snapshot management (table level): expires snapshots by `MinimumSnapshots` (default 1) and `MaximumSnapshotAge` (default 120 hours). Files referenced only by expired snapshots are marked noncurrent.
- Unreferenced file removal (table bucket level): deletes noncurrent and orphan files after a number of days (`NoncurrentDays`, `UnreferencedDays`; defaults not confirmed here – verify). Deletes are permanent; recovery needs AWS Support.
- Snapshot management **fails** for the whole table if the table has user-defined tags or branches, or Iceberg retention properties (`history.expire.max-snapshot-age-ms`, `history.expire.min-snapshots-to-keep`). Remove them to restore expiry.
- Check job status with `GetTableMaintenanceJobStatus`. Maintenance appears in CloudTrail management events.
- You can edit/disable maintenance with `PutTableMaintenanceConfiguration` (permissions `s3tables:Get/PutTableMaintenanceConfiguration`).
- Record expiration: removes records older than N days (1 to 2,147,483,647). Currently only for AWS-managed tables (S3 Storage Lens and SageMaker Catalog tables, plus S3 Metadata journal tables with its own setting). Not available for tables you create. Records expire within 24–48 hours after becoming eligible, and cannot be recovered.
- Parquet row-group default size used by S3 Tables: 128 MB.
- Maintenance costs extra (compaction and requests); see S3 pricing.

## G. Integration with analytics services
- Integration uses the AWS Glue Data Catalog: a federated catalog named `s3tablescatalog` that exposes table buckets, namespaces and tables.
- Created automatically in the console when you tick "Enable integration" (per Region), or with CLI `aws glue create-catalog`.
- Needs Glue permissions: `glue:CreateCatalog` and `glue:PassConnection` (connection `aws:s3tables`).
- Access control choices: IAM only (default for new integrations) or Lake Formation (IAM plus Lake Formation grants for fine-grained control: column/row/cell).
- Integration adds Glue request/storage cost; query engines add their own cost.
- SSE-KMS tables: the role used by the analytics service must be allowed to use the KMS key.
- Athena, Redshift, Quick, EMR, SageMaker Unified Studio then see the tables through the catalog.
- Spark can also use the S3 Tables Iceberg catalog client directly.

## H. Security
- Identity-based IAM policies, table bucket policies (bucket and namespace operations, or many tables), table policies (one table). All use `s3tables:` actions.
- SCPs can govern `s3tables` actions in an Organization.
- Encryption: SSE-S3 by default, SSE-KMS optional (per bucket or per table).
- VPC connectivity: PrivateLink / gateway-style endpoints for S3 Tables (verify specific endpoint type).
- Lake Formation can add column/row/cell filters on top of IAM for integrated engines.
- CloudTrail records management events (maintenance) and data events.

## I. Replication of tables
- Automatic, read-only replicas of Iceberg tables across table buckets: same Region or other Regions, same account or other accounts.
- Updates commit to the replica in the same order as the source (snapshots, metadata, data files), typically within minutes.
- Multiple destinations are allowed.
- Snapshot retention on replicas is independent of the source (for example 30 days at source, 90 days at replica) – gives longer time travel.
- Destination buckets can use S3 Intelligent-Tiering for lower cost; can use different KMS keys.
- Use for lower latency, compliance copies, centralized analytics, and dev/test copies. Replicas are read-only.

## J. S3 Metadata and S3 Tables in AWS-managed use
- S3 Storage Lens and SageMaker Catalog can store metrics/metadata as S3 tables (AWS-managed tables).
- S3 Metadata creates journal and live inventory tables for a bucket, so you can query object metadata with SQL (details: verify in current docs).

## K. S3 Vectors (awareness)
- S3 Vectors is a newer S3 capability for storing and querying vector embeddings (for semantic search / RAG). It uses vector buckets and indexes.
- Not a general data lake table format. Details change quickly; check current docs before use. Compare with OpenSearch vector search and Aurora pgvector for latency/price trade-offs.

## L. When to use what (data lake table decisions)
- Append-only logs, rarely changed → Parquet + partitions on a general purpose bucket.
- Need UPDATE/DELETE/MERGE, CDC upserts, GDPR deletes, time travel → Iceberg.
- Want Iceberg with low ops on AWS → S3 Tables.
- Streaming upserts with heavy record-level indexing → Hudi.
- Already Delta-centric → Delta.
- Many tiny streamed files → table format with automatic compaction (S3 Tables) or scheduled Athena `OPTIMIZE`/Glue compaction.
- Multi-engine reads (Athena + Redshift + Spark) → Iceberg through Glue Data Catalog.

## M. Scenarios (if → then, because)
- If you need to delete one user's rows in a data lake and prove the data is gone → Iceberg DELETE + snapshot expiration + orphan cleanup (or S3 Tables maintenance), because old snapshots still reference old files.
- If queries slow down as streaming adds many small files → compaction (automatic in S3 Tables), because small files add metadata and request overhead.
- If you want to see data as it was last Tuesday → Iceberg time travel by timestamp.
- If a bad write corrupted a table → roll back to a prior snapshot.
- If you want fewer operations on Iceberg → S3 Tables.
- If an S3 table is invisible in Athena → table or column name has uppercase letters, or the Glue/Lake Formation integration is not enabled, or LF permissions are missing.
- If S3 Tables snapshots never expire → check for user tags/branches or Iceberg retention table properties blocking snapshot management.
- If you must give column-level access to S3 tables → integrate with Lake Formation and grant column permissions.
- If a replica table needs longer time travel than the source → set a longer snapshot retention on the replica.
- If a query engine only supports old Iceberg V2 features → keep tables on V2 behavior; V3 is supported in table buckets, but engine support varies (verify per engine).
- If you need CDC from a database into a lake with updates → DMS to S3, then MERGE into Iceberg (Glue/Spark/Athena).
- If compaction cost is high → use binpack instead of sort/z-order, raise target file size, or reduce small-file creation upstream.
- If queries filter on 2–3 columns together → z-order compaction (needs sort order).
- If you need SQL over object metadata of a bucket → S3 Metadata tables or Inventory + Athena.
- If a team wants to store embeddings for semantic search → S3 Vectors, OpenSearch vector, or pgvector, depending on latency and scale.

## Verified from AWS docs on 2026-10-02
S3 Tables overview, maintenance (compaction, snapshot management, defaults), record expiration, replication, quotas, analytics integration were read. Iceberg internals and Hudi/Delta comparison come from general knowledge. Not confirmed: unreferenced file removal default day counts, exact VPC endpoint type, S3 Metadata and S3 Vectors details (verify).

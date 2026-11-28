# Amazon Data Firehose – 2. Transformations, format conversion, dynamic partitioning and Iceberg tables

Short notes. Each point is a fact you can be asked about.

## A. Processing features at a glance
- Built-in (no code): CloudWatch Logs decompression and message extraction, multi-record de-aggregation, JSON → Parquet/ORC conversion, dynamic partitioning with JQ, Iceberg routing with JQ.
- Custom code: one Lambda function per stream for anything else (parse CSV, mask PII, enrich, filter, route, compute partition keys).
- Order inside the stream: KPL de-aggregation → JSON/delimiter de-aggregation → Lambda → dynamic partitioning → format conversion → S3 delivery.
- Why order matters: Lambda sees single records (already de-aggregated), and format conversion sees Lambda's output, so Lambda must return JSON when conversion is on.
- Format conversion and dynamic partitioning work only for the S3 destination.

## B. CloudWatch Logs decompression and message extraction
- CloudWatch Logs subscription filters send data to Firehose **gzip-compressed**, with many log events packed in one record.
- Turn on **decompression** (built-in) to deliver plain JSON. Offered for S3 and Splunk destinations in the console.
- Decompression is required if you want format conversion or dynamic partitioning on CloudWatch Logs data.
- Optional **message extraction**: drops envelope fields (`owner`, `logGroup`, `logStream`, `subscriptionFilters`, `messageType`) and delivers only each `message`, one per line.
- Splunk destination needs message extraction on so Splunk can parse events.
- Use a decompression-enabled stream only for CloudWatch Logs subscriptions. Vended logs sent to the same stream will fail.
- Records that fail decompression go, still compressed, to the S3 error bucket under `decompression-failed`. Other records continue.
- Metrics: `OutputDecompressedBytes.Success/Failed`, `OutputDecompressedRecords.Success/Failed`.
- Pricing: about $0.00325 per GB decompressed (US East example).
- Quirk: on an existing stream without Lambda, you must turn Lambda on (pass-through) first, then enable decompression, then remove Lambda.
- The old "Process CloudWatch Logs sent to Firehose" Lambda blueprint is **deprecated**; decompressed data above 6 MB can fail and cost more.

## C. Lambda data transformation: flow
- Firehose buffers incoming data for Lambda separately from the destination buffer.
- Lambda buffer size hint: **0.2–3 MB**, default **1 MB** (256 KB for Splunk and Snowflake).
- Lambda buffer interval hint: **0–900 s**, default **60 s** (30 s for Snowflake).
- Firehose invokes Lambda **synchronously** (RequestResponse) with each batch.
- Request and response payload limit is **6 MB** each. Keep the batch small enough that the transformed response also fits.
- Max Lambda run time Firehose waits: **5 minutes**. Longer → "Firehose encountered timeout errors when calling AWS Lambda".
- Concurrency: up to **5 outstanding invocations per shard** for S3, Redshift and OpenSearch destinations; **10** for Splunk.
- One Lambda function per stream. Chain logic inside the function if you need several steps.

## D. Lambda contract (input and output)
- Input event has `invocationId`, `deliveryStreamArn`, `region`, and a `records` list.
- Each input record has `recordId`, `approximateArrivalTimestamp`, and base64 `data` (for MSK: `kafkaRecordValue` plus topic metadata).
- KDS source records also carry `kinesisRecordMetadata` (shard ID, partition key, sequence number) **(verify field names)**.
- Output must be `{"records": [...]}` with one entry per input record.
- Required output field `recordId`: must equal the input `recordId`. A mismatch = transformation failure.
- Required output field `result`: `Ok`, `Dropped`, or `ProcessingFailed`.
- `Ok` = transformed successfully. `Dropped` = intentionally removed (filtering). Both count as success.
- `ProcessingFailed` = could not transform → record goes to the error prefix.
- Required output field `data`: transformed payload, **base64-encoded** (for MSK the field is `kafkaRecordValue`).
- Records missing from the output are treated as failures **(verify)**.
- Optional `metadata.partitionKeys` = map of keys for dynamic partitioning (`partitionKeyFromLambda`).
- Optional `metadata.otfMetadata` = Iceberg routing: `destinationDatabaseName`, `destinationTableName`, `operation`.

## E. Lambda failure handling
- Invocation failures (network timeout, Lambda throttling, function error) are retried **3 times by default** (`NumberOfRetries`).
- After retries, Firehose skips that whole batch; the records count as failed.
- Failed records go to S3 under the `processing-failed/` prefix (or your `ErrorOutputPrefix`).
- Each failed record is a JSON line with `attemptsMade`, `arrivalTimestamp`, `errorCode`, `errorMessage`, `attemptEndingTimestamp`, `rawData` (base64 original), `lambdaARN`.
- Invocation errors can be logged to CloudWatch Logs (Firehose error logging). Log your own errors from the function code too.
- Lambda throttling (account concurrency) slows the whole stream. Reserve concurrency for the transform function.
- Slow Lambda = rising data freshness. Fix with more memory (more CPU), async I/O, or smaller batches.
- Metrics: `ExecuteProcessing.Duration`, `ExecuteProcessing.Success`, `SucceedProcessing.Records`, `SucceedProcessing.Bytes`.

## F. Blueprints and source record backup
- Lambda console blueprints (search "firehose"): generic record processing (Node.js, Python), syslog RFC3164 → JSON, and the deprecated CloudWatch Logs one.
- Source record backup: Firehose writes the **untransformed** records to S3 while sending transformed records to the destination.
- Why: replay or reprocess later if the transform had a bug.
- Source record backup can be added later but **cannot be turned off** once on.
- With KDS source and full backup on, Firehose reads each shard twice per second (one for delivery, one for backup).

## G. Record format conversion: what it is
- Converts **JSON** input to **Apache Parquet** or **Apache ORC** before writing to S3.
- Why: columnar files are smaller and much faster and cheaper to query with Athena, Redshift Spectrum, EMR, Glue.
- Input must be JSON. For CSV, syslog or other formats, add a Lambda that turns records into JSON first.
- Works only with the **S3 destination**. With conversion on, you cannot pick OpenSearch, Redshift or Splunk.
- Needs three parts: a deserializer (reads JSON), a schema (from a Glue Data Catalog table), and a serializer (writes Parquet or ORC).
- Multiple JSON documents in one record are fine as `{"a":1}{"b":1}`. A JSON array `[{...},{...}]` is **not** valid input.

## H. Deserializers
- **OpenX JSON SerDe** = default choice. Use it unless your timestamps need custom formats.
- OpenX parses timestamps like `yyyy-MM-dd'T'HH:mm:ss[.S]'Z'`, `yyyy-[M]M-[d]d HH:mm:ss[.S]`, epoch seconds, epoch milliseconds, and float epoch seconds.
- OpenX `CaseInsensitive` (default **true**): lowercases JSON keys before matching columns.
- OpenX `ConvertDotsInJsonKeysToUnderscores` (default false): `a.b` → `a_b`, because Hive columns cannot contain dots.
- OpenX `ColumnToJsonKeyMappings`: map a column to a JSON key with another name (for example a key named `timestamp`, a Hive keyword).
- **Apache Hive JSON SerDe**: use when you need custom timestamp formats (Joda-Time patterns, or `millis`).
- Hive SerDe rejects: dots in column names, `uniontype`, and numbers sent as strings (`{"a":"123"}` for an int column).

## I. Schema from the Glue Data Catalog
- Firehose reads column names and types from a Glue table (Region, database, table, version).
- `VersionId` `LATEST` (default) = Firehose picks up table changes automatically.
- Catalog defaults to your account and current Region; another Region is allowed.
- The schema role must be in the same account as the stream; cross-account roles are not allowed for this.
- Role needs `glue:GetTable`, `glue:GetTableVersion`, `glue:GetTableVersions` (and `glue:GetSchemaVersion` for schema registry) **(verify action list)**.
- Fields not in the schema are **dropped silently** in the output. Keep the table in sync with the data.
- Nested JSON → use `STRUCT` columns that mirror the structure.
- Practical limit of 32 MB of data per row for types without a size limit.
- `CHAR`/`VARCHAR` lengths truncate strings when reading.
- Glue crawler on DynamoDB data creates `SET<...>` types; conversion fails because they are not Hive types → change them to `ARRAY<...>`.

## J. Serializers and compression
- **Parquet SerDe** compression: `SNAPPY` (default), `GZIP`, `UNCOMPRESSED`.
- Parquet options: block size (default 256 MiB, min 64 MiB), page size (default 1 MiB, min 64 KiB), dictionary compression, writer version V1 (default) or V2.
- **ORC SerDe** compression: `SNAPPY` (default), `ZLIB`, `NONE`.
- ORC options: stripe size (default 64 MiB, min 8 MiB), block size 256 MiB, bloom filter columns, row index stride (default 10,000), format version V0_12 (default).
- With conversion on, the stream `CompressionFormat` must be **UNCOMPRESSED**. Compression happens inside the serializer.
- Snappy from conversion uses Hadoop-compatible framing, so Athena can read it.
- S3 buffer size must be **≥ 64 MiB** with conversion; default becomes **128 MiB**.

## K. Format conversion errors and metrics
- Records that cannot be parsed or do not match the schema go to S3 with the error prefix (`format-conversion-failed`).
- Error JSON includes `attemptsMade`, `arrivalTimestamp`, `ErrorCode`, `ErrorMessage`, `rawData`, sequence numbers, and the `dataCatalogTable` used.
- Trap: if writing the error record to S3 fails, Firehose **retries forever** and blocks delivery. Keep the error bucket healthy.
- Metrics: `SucceedConversion.Records`, `SucceedConversion.Bytes`, `FailedConversion.Records`, `FailedConversion.Bytes`.

## L. Dynamic partitioning: what and why
- Groups records by keys **inside the data** (for example `customer_id`, event date) and writes each group to its own S3 prefix.
- Why: queries scan only the partitions they need → less data scanned, faster, cheaper; also enables per-tenant S3 access control.
- S3 destination only.
- Must be turned on **at stream creation**. It cannot be added to an existing stream and **cannot be turned off** later.
- You can change keys and prefix expressions later; new values apply to new data.
- An `ErrorOutputPrefix` is **required** when dynamic partitioning is on.

## M. Dynamic partitioning: keys
- Inline parsing = built-in **JQ** parser (jq **1.6** only) on JSON records. No Lambda needed.
- Up to **50** dynamic partitioning keys per stream.
- JQ examples: `.customer_id`, `.type.device` (nested), `.event_timestamp | strftime("%Y")` for year from epoch.
- Use inline keys in the prefix as `!{partitionKeyFromQuery:customer_id}`.
- Lambda keys: the transform Lambda returns `metadata.partitionKeys`; use as `!{partitionKeyFromLambda:customer_id}`.
- Use Lambda keys when data is compressed, encrypted, not JSON, or needs logic JQ cannot express.
- Inline JQ and Lambda keys can be used together in one prefix.
- The number of key expressions in the prefix must match the keys you defined.
- Example: `customer_id=!{partitionKeyFromQuery:customer_id}/year=!{partitionKeyFromQuery:year}/` → Hive-style folders.
- Records where keys cannot be extracted or the prefix cannot be evaluated go to the error prefix.
- JQ processing is billed per JQ hour; heavy JQ adds cost and latency (`JQProcessing.Duration`).

## N. Dynamic partitioning: aggregated data and delimiters
- If producers pack many JSON events into one record, turn on **multi-record de-aggregation** first; partitioning works only after de-aggregation.
- De-aggregation type: `JSON` (consecutive objects, on one line or newline-delimited) or `Delimited` (custom delimiter, given base64-encoded, for example `####` → `IyMjIw==`).
- De-aggregation is capped at **500** sub-records per record.
- JSON arrays are still invalid input for de-aggregation.
- De-aggregation removes newlines → turn on the **newline delimiter** so S3 objects stay line-delimited.

## O. Dynamic partitioning: buffering, limits and small files
- Firehose keeps one buffer per **active partition** (each distinct evaluated prefix).
- Each partition is flushed separately when it hits its size or time hint → one S3 object per partition per flush.
- Multi-stage buffering means end-to-end delay can be about **1.5×** the buffer interval.
- Zero buffering is not available with dynamic partitioning. Minimum buffer size with DP is 64 MiB **(verify)**.
- Active partitions = partitions created per second × buffer interval (3 new partitions/s × 60 s ≈ 180 active).
- Default limit: **500 active partitions per stream**; raise to **2,500** with a limit request. Beyond that, records go to the error prefix as `activePartitionExceeded`.
- Need more → split traffic across several Firehose streams.
- Max throughput **1 GB/s per active partition**.
- Trap: high-cardinality keys (user ID, request ID, minute) → many tiny files, partition-limit errors, and higher per-object charges.
- Pick low or medium cardinality keys (tenant, region, date, hour) and longer buffers.
- Small files still happen → run compaction later (Glue job, Athena CTAS/INSERT, or Iceberg tables with automatic compaction).
- Metrics: `PartitionCount`, `ActivePartitionsLimit`, `PartitionCountExceeded` (1 = over limit), `PerPartitionThroughput`, `DeliveryToS3.ObjectCount`, `JQProcessing.Duration`.
- Partitions are new prefixes; register them in Glue with partition projection, a crawler, or `MSCK REPAIR`/`ALTER TABLE ADD PARTITION`.

## P. Combining features
- Lambda + dynamic partitioning: one function can transform and return partition keys.
- Dynamic partitioning + format conversion: partition first, then convert each partition's data to Parquet. Common data lake pattern.
- CloudWatch Logs + partitioning or conversion: decompression must be on.
- Lambda + format conversion: Lambda must output JSON that matches the Glue schema.

## Q. Apache Iceberg Tables destination: basics
- Firehose writes streaming data straight into **Apache Iceberg** tables in S3, either self-managed (general purpose bucket) or **Amazon S3 Tables** (table buckets).
- Catalog: AWS Glue Data Catalog. Same account by default, or cross-account, and same or different Region.
- For S3 Tables use the catalog ARN `arn:aws:glue:<region>:<account>:catalog/s3tablescatalog/<table bucket>`.
- Supports Lake Formation fine-grained (table and column) permissions for the Firehose role.
- Table format version **V2 only**. V1 tables fail (`Iceberg.NoSuchTable` / `Iceberg.InvalidTableName`) and data goes to the error bucket.
- Data files are written as **Parquet**. Row-level changes use **Merge-on-Read** (delete files + data files).
- Tables must be created through Iceberg's GlueCatalog API; tables made with the plain Glue SDK are not supported. Hyphens are not allowed in database or table names.
- S3 Tables: column names must be lowercase.
- Sources: Direct PUT, KDS, MSK provisioned. MSK Serverless is not supported for Iceberg.
- Buffering: 1–128 MiB and 0–900 s (default 5 MiB / 300 s). Larger buffers → fewer commits, bigger files, cheaper compaction.
- Retry duration 0–7,200 s (default 300 s). After that, failed data goes to the S3 backup error prefix (backup mode effectively failed-data only).
- No duplicates per AWS for this destination; records are not delivered in order.
- Encryption for S3 Tables is set on the table bucket (KMS), not in Firehose settings.

## R. Iceberg: routing and operations
- Single table: set one database and table in the stream config. No JQ or Lambda needed.
- Multi-table routing: one stream can write to many tables based on record content.
- Route with **JSONQuery (JQ) expressions** for database name, table name and optional operation. Each can be static (`"IoTevents"`) or dynamic (`.deviceId`, `.event.deviceId`).
- JQ routing is the simplest and cheapest option.
- Route with **Lambda**: return `metadata.otfMetadata` with `destinationDatabaseName`, `destinationTableName`, `operation`.
- If both are set, Firehose uses Lambda metadata first, then JQ for missing fields, then the single-table config.
- Database and table names must match exactly, or records go to the error bucket.
- Operations: `insert` (default), `update`, `delete`.
- Default insert keeps duplicates (same record twice = two rows).
- `update` and `delete` need **unique keys**: set per table in the stream (`UniqueKeys`) or as Iceberg `identifier-field-ids` on the table.
- Without unique keys, update/delete records fail to the error bucket.
- If you configure unique keys in the stream, the tables must exist before stream creation (Firehose validates them).
- `update` = delete file + insert; it also inserts the row if it does not exist (upsert behavior).
- Update/delete files are written per partition; global (unpartitioned) deletes on partitioned tables are not supported.

## S. Iceberg: data rules
- Firehose maps only the **first level** of JSON to columns; nested objects map to `struct` or `map` columns (up to 16 nesting levels).
- Column names and types must match the table exactly; mismatches go to the error bucket.
- Extra fields not in the table are **skipped**.
- One JSON object per Firehose record. Aggregated multiple objects → error (KPL aggregation from KDS is fine; it is de-aggregated).
- Timestamps must be sent in **microseconds**. Binary as base64 (basic, MIME, URL-safe) or hex.
- Automatic **schema evolution** and **table creation** settings exist in the API (`SchemaEvolutionConfiguration`, `TableCreationConfiguration`) but the API reference marks them preview **(verify status)**.

## T. Iceberg: throughput, partitions and maintenance
- Direct PUT to Iceberg: **5 MiB/s** per stream in N. Virginia, Oregon, Ireland; **1 MiB/s** elsewhere; raise with a limit request.
- `AppendOnly = true` (insert only, set at `CreateDeliveryStream`) lets Firehose scale throughput automatically. Using it with updates/deletes gives out-of-order results.
- Max active Iceberg partitions shrink as throughput grows: ≤20 MB/s ≈ 3,000; 20–40 MB/s 1,000; 40–400 MB/s 100; 400–750 MB/s 50; 750 MB/s–1.5 GB/s 1.
- Throughput here is measured after Lambda; a Lambda that expands records lowers your partition headroom.
- With KDS/MSK sources, use partition keys so records for one table land on few shards; spread different tables across shards.
- Do **not** point several Firehose streams at the same Iceberg table: optimistic concurrency lets one commit win; others retry then go to the error prefix.
- Every commit makes snapshots, data files and delete files → many small files and metadata growth.
- Self-managed tables: you run compaction (Glue Data Catalog automatic compaction, or Athena `OPTIMIZE`) and cleanup (`VACUUM`, snapshot expiration, orphan file removal).
- S3 Tables manage compaction and snapshot cleanup for you.
- Update operations add delete files → extra S3 PUT cost and read-time merge cost until compaction.
- Metrics: `DeliveryToIceberg.Bytes`, `.IncomingRowCount`, `.SuccessfulRowCount`, `.FailedRowCount`, `.DataFreshness`, `.Success` (commits), `JQProcessing.Duration`.

## U. Choosing a landing format
| Need | Pick | Why |
|---|---|---|
| Cheapest raw landing | S3, GZIP JSON lines | no feature fees |
| Fast Athena on append-only data | S3 + format conversion (+ dynamic partitioning) | columnar, partition pruning |
| Upserts/deletes, CDC, ACID, time travel | Iceberg destination (S3 Tables for managed maintenance) | row-level operations |
| Partition by a field inside the data | dynamic partitioning or Iceberg partition spec | arrival-time prefixes do not see data |
| Non-JSON input to Parquet | Lambda to JSON + conversion | conversion reads JSON only |

## V. Troubleshooting: processing
| Symptom | Cause | Fix |
|---|---|---|
| `processing-failed/` files appear | Lambda error, timeout, throttle, bad output | check Lambda logs; fix `recordId`/`result`/base64 |
| "timeout errors when calling AWS Lambda" | function > 5 min | faster code, smaller batches |
| Lambda fails on big batches | request or response > 6 MB | lower Lambda buffer size |
| Data freshness climbs with Lambda on | slow function or throttled concurrency | more memory, async I/O, reserved concurrency |
| Parquet files missing columns | fields not in Glue schema, key case mismatch | update table; case-insensitive OpenX |
| Conversion fails for numbers as strings | Hive SerDe strict typing | OpenX SerDe or fix producer |
| Conversion fails on DynamoDB set types | `SET<>` not a Hive type | change to `ARRAY<>` |
| `format-conversion-failed` with arrays | input is a JSON array | send objects, not arrays |
| Cannot enable conversion | compression set or destination not S3 | set UNCOMPRESSED; use S3 |
| `activePartitionExceeded` in error prefix | > 500 active partitions | lower key cardinality, longer interval, request 2,500, more streams |
| Cannot enable dynamic partitioning | stream already exists | create a new stream |
| Partitioning finds no keys on aggregated data | de-aggregation off | turn on multi-record de-aggregation |
| CloudWatch Logs data unreadable in S3 | still gzip with envelope | turn on decompression (+ extraction) |
| Vended logs fail on a stream | decompression on | separate stream for vended logs |
| Iceberg writes fail, `NoSuchTable` | V1 table, wrong name, hyphen | V2 table, exact names via GlueCatalog API |
| Iceberg update/delete rows rejected | no unique keys | set `UniqueKeys` or `identifier-field-ids` |
| Iceberg commits conflict | two streams on one table | one stream per table |
| Iceberg queries slow over time | small files, delete files | compaction / S3 Tables |

## Scenarios: "If X → Y, because Z"
- **If** CSV clickstream data must land in S3 as **Apache Parquet**, **then** add an **AWS Lambda** transform that turns each CSV record into JSON, and turn on **record format conversion** to Parquet. **This works because** format conversion accepts **JSON input only**. Lambda runs before conversion inside the stream, so conversion sees Lambda's JSON output. The JSON must match the **AWS Glue Data Catalog** table that holds the schema.
- **If** **Amazon Athena** costs are high on JSON logs, **then** turn on **format conversion to Parquet** with **SNAPPY** compression (the Parquet default). **This works because** columnar files are smaller and Athena scans only the columns a query needs, so fewer bytes are scanned and billed. Conversion costs about **$0.018 per GB** but pays for itself when query scans dominate cost.
- **If** format conversion is turned on but the stream rejects the configuration, **then** set the stream compression to **UNCOMPRESSED** and the S3 buffer size to **at least 64 MiB**. **This works because** the Parquet or ORC serializer does the compression itself, and columnar files need large buffers; with conversion on, the minimum buffer is **64 MiB** and the default becomes **128 MiB**.
- **If** a new JSON field appears in the data but not in the Parquet output, **then** add the column to the **Glue table** and keep `VersionId` set to **LATEST**. **This works because** fields not in the schema are **dropped silently**, and with LATEST Firehose picks up table changes automatically.
- **If** timestamps use a custom format like `dd/MM/yyyy HH:mm`, **then** use the **Apache Hive JSON SerDe** (deserializer) with a **Joda-Time** pattern. **This works because** the default **OpenX JSON SerDe** reads only a fixed list of timestamp formats (ISO-style, epoch seconds, epoch milliseconds), while the Hive SerDe accepts custom patterns. The catch: Hive SerDe is strict and rejects numbers sent as strings.
- **If** each tenant must get its own S3 prefix so **Identity and Access Management (IAM)** policies can isolate tenants, **then** use **dynamic partitioning** on `tenant_id`, for example prefix `tenant=!{partitionKeyFromQuery:tenant_id}/`. **This works because** dynamic partitioning groups records by a key **inside the data** and writes each group to its own prefix. It must be turned on **at stream creation** and needs an `ErrorOutputPrefix`.
- **If** S3 folders must follow **event date**, not arrival date, **then** use **dynamic partitioning** with a JQ query such as `.event_timestamp | strftime("%Y")` on the event field. **This works because** the `timestamp` prefix namespace uses arrival time only, while JQ (Firehose's built-in JSON query parser, jq 1.6) reads values inside each record.
- **If** partition keys sit inside **encrypted or compressed** payloads, **then** let the **Lambda** transform return them in `metadata.partitionKeys` and use `!{partitionKeyFromLambda:...}` in the prefix. **This works because** inline JQ parsing needs plain JSON, while Lambda can decode the data and compute the keys with any logic.
- **If** dynamic partitioning by `user_id` sends data to the error prefix, **then** switch to a coarser key such as tenant, region or date, and use longer buffers. **This works because** Firehose keeps one buffer per **active partition**, capped at **500 per stream** by default (**2,500** on request). Above that, records fail as `activePartitionExceeded`. High-cardinality keys also create many tiny files.
- **If** dynamic partitioning must be added to a stream that is already running, **then** create a **new stream** with it turned on and switch the producers over. **This works because** dynamic partitioning can be enabled **only at creation** and can never be turned off later.
- **If** producers pack **100 JSON events** into one record and partitioning fails, **then** turn on **multi-record de-aggregation** (type `JSON`) and the **newline delimiter**. **This works because** partitioning works only on single records, so de-aggregation must split them first (up to **500** sub-records per record). De-aggregation removes newlines, so the delimiter keeps S3 objects one record per line.
- **If** some records must be filtered out before reaching S3, **then** have the Lambda transform return **`Dropped`** for them. **This works because** `Dropped` counts as a success and the record is not delivered. Ingestion is still billed.
- **If** bad records must be kept for fixing later, **then** read the objects under **`processing-failed/`** and redrive the **`rawData`** field. **This works because** Firehose writes each failed record there as a JSON line with the original data in base64, plus the error code and message.
- **If** a raw, untransformed copy must be kept for audit, **then** turn on **source record backup**. **This works because** Firehose then writes the original records to S3 while sending transformed records to the destination, so you can reprocess if the transform had a bug. The catch: once on, it **cannot be turned off**.
- **If** the Lambda transform keeps timing out, **then** lower the **Lambda buffer size** (0.2–3 MB, default 1 MB) and make the code faster. **This works because** Firehose waits at most **5 minutes** for each invocation, and smaller batches finish sooner.
- **If** **Amazon CloudWatch Logs** from many log groups must land as plain JSON lines, **then** use Firehose with **decompression** and **message extraction** turned on. **This works because** subscription filters send data **gzip-compressed** with many events and an envelope (`logGroup`, `logStream` and so on) in one record. Decompression unzips it, and message extraction keeps only each `message`, one per line.
- **If** change data capture (CDC) changes must **upsert** into a data lake table in near real time, **then** use Firehose to **Apache Iceberg Tables** with `update` and `delete` operations and **unique keys** set. **This works because** Iceberg supports row-level changes (written as delete files plus data files), while plain S3 files cannot. `update` deletes the old row and inserts the new one, or just inserts if the row does not exist.
- **If** one stream carries events for many device types, **then** use **Iceberg multi-table routing** with a JQ expression such as `.deviceType` for the table name. **This works because** one Firehose stream can write to many Iceberg tables based on record content, and JQ routing is the simplest and cheapest option. Table names must match exactly.
- **If** routing rules are complex (lookups, enrichment), **then** have **Lambda** return `metadata.otfMetadata` with the database name, table name and operation. **This works because** JQ only extracts values from the record, while Lambda can run any logic. Firehose uses Lambda metadata first, then JQ for missing fields.
- **If** you want Iceberg tables without running compaction yourself, **then** use **Amazon S3 Tables** (table buckets) as the Iceberg destination. **This works because** S3 Tables run compaction and snapshot cleanup automatically. With self-managed tables you must run compaction and cleanup (for example Athena `OPTIMIZE` and `VACUUM`).
- **If** Iceberg **Direct PUT** throughput stalls at **1 MiB/s** outside the big Regions, **then** request a **limit increase**, or set **`AppendOnly = true`** at creation for insert-only data. **This works because** 1 MiB/s is the default cap there (5 MiB/s in N. Virginia, Oregon and Ireland), and `AppendOnly` lets Firehose scale throughput automatically. The catch: using it with updates or deletes gives out-of-order results.
- **If** two teams want separate Firehose streams writing the **same Iceberg table**, **then** use **one stream** (or one KDS stream feeding it). **This works because** Iceberg uses optimistic concurrency: one commit wins, and the others retry and then go to the error prefix.
- **If** an Iceberg `update` record fails with a missing key error, **then** define **`UniqueKeys`** in the stream or **`identifier-field-ids`** on the table. **This works because** `update` and `delete` need a unique key to find the row; without one, the records fail to the error bucket.
- **If** **Amazon Redshift** is the target but you want Parquet, **then** it is not possible in one stream. **This works because** format conversion works **only with the S3 destination**.
- **If** an exam asks for the least-code way to get **partitioned Parquet** in S3 from **Amazon Kinesis Data Streams (KDS)**, **then** use Firehose with **dynamic partitioning** plus **format conversion**. **This works because** both features are built in: Firehose partitions first, then converts each partition's data to Parquet, with no code to run.

Verified from AWS docs on 2026-11-02 (Firehose Developer Guide PDF: data transformation flow, required parameters, blueprints, failure handling, source record backup, CloudWatch Logs decompression and message extraction, dynamic partitioning keys, prefixes, aggregated data, buffering and errors, record format conversion, Iceberg considerations, prerequisites, routing, unique keys, metrics, data types, document history; API Reference: ProcessorParameter, ParquetSerDe, OrcSerDe, OpenXJsonSerDe, SchemaConfiguration, IcebergDestinationConfiguration, SchemaEvolutionConfiguration).
Unconfirmed (verify): `kinesisRecordMetadata` field names; missing output records treated as failures; Glue IAM action list for conversion; 64 MiB minimum buffer with dynamic partitioning; Iceberg schema evolution and table creation status (preview vs GA).

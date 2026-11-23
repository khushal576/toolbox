# Glue – 2. Data Catalog, crawlers, partitions and Schema Registry

Short notes. Each point is a fact you can be asked about.

## A. The Data Catalog
- The **Glue Data Catalog** = a managed, central **metadata** store. It holds **where data is, its schema, format and partitions**. It does **not** hold the data (data stays in S3, a database, a stream).
- Structure: **catalog → database → table → partitions** (plus table versions, connections, functions, crawlers' results).
- A **table** stores: column names and types, S3 location (or JDBC/stream details), **format** (classification such as parquet, csv, json), **SerDe** library, **partition keys**, and free-form **parameters** (table properties).
- One Data Catalog per **account per Region**. Its **catalog ID is the account ID**.
- Who reads it: **Athena**, **Redshift Spectrum**, **EMR** (as Hive metastore), **Glue ETL**, **Lake Formation**, QuickSight **(verify)**, and other tools that support the Hive metastore API.
- It is a **drop-in Apache Hive metastore** replacement. Use `--enable-glue-datacatalog` in a Glue job, or the Glue Catalog option on EMR. This is how you share one schema across engines.
- A table is just metadata. **Dropping a table does not delete the S3 data** (for external tables).
- **Table versions**: every schema update keeps a version. Quota **100,000 versions per table**. Old versions can be deleted.
- Table types to know: **external** (data stays where it is), **Iceberg / Hudi / Delta** tables (open table formats), **virtual views** (Athena/Glue views).
- Ways to fill the Catalog:
  1. **Crawlers** (auto-discover). Most common.
  2. **DDL in Athena** (`CREATE EXTERNAL TABLE`, `CREATE TABLE AS SELECT`).
  3. **Glue console / API / CLI / CloudFormation** (manual or automated).
  4. **ETL jobs** that write a table and update the Catalog (`enableUpdateCatalog`).
  5. **Hive metastore migration** from an existing Hive metastore.
  6. Lake Formation, DMS, zero-ETL and other services that register tables.
- **Quotas** (default, most adjustable): databases **10,000** per account; tables **200,000** per database and **1,000,000** per account; partitions **10,000,000** per table and **20,000,000** per account; connections **1,000**; crawlers **1,000** per account and **150** running at once; security configurations **250**.
- **Cost**: free for the first **1,000,000** objects stored and **1,000,000** requests per month. Above that: about **$1.00 per 100,000 objects** stored and **$1.00 per additional million requests** (verify current figures). Each **partition** and each **partition-index item** is an object.
- Many small tables or millions of partitions raise cost and slow `GetPartitions`. Fix with fewer partitions, **partition indexes**, or **partition projection** (Athena).

## B. Crawlers
- A **crawler** scans a data store, **infers schema and format**, groups files into tables and partitions, and writes them to the Catalog.
- Crawlers use an **IAM role** that can read the data store and write to the Catalog. S3 permission is `s3:GetObject` and list on the include path.
- Crawlable sources: **S3**, **JDBC databases** (via a connection), **DynamoDB**, **Delta Lake**, **Iceberg**, **Hudi**, **MongoDB/DocumentDB**, and others **(verify the full list)**. Kinesis and Kafka are **not** crawled. You create those tables by hand (file 3).
- Crawl steps in order:
  1. Run **custom classifiers** in the order you set. The first that recognizes the data wins (**certainty 1.0**).
  2. If none match, try **built-in classifiers** in their fixed order.
  3. Connect to the data store (some need a connection).
  4. Build the inferred **schema**.
  5. Write **table and partition** metadata to the Catalog.
- A crawler can crawl **several data stores (include paths) in one run**.
- **Schedule**: on demand, hourly, daily, weekly, monthly, or a **cron** expression. Minimum cron interval is **5 minutes** **(verify)**. Crawlers can also be started by **triggers**, **workflows**, **EventBridge** or Step Functions.
- Crawler output includes **new tables and new partitions** found since the previous run, and updates schemas based on the **schema change policy**.
- **Table naming rules**: letters, digits and `_` only. A custom **prefix** max **64** characters. Full name max **128** characters (truncated if longer). Duplicate names get a **hash suffix**.
- The crawler stores a **classification** (for example `parquet`, `csv`) on each table.
- Compressed files (whole-file gzip, bzip2, ZIP with one file, LZ4, Snappy) must be **downloaded to be read**. Columnar formats that compress **inside** the file (Parquet) do not set `compressionType` on the table.
- Cost: crawlers bill **$0.44 per DPU-hour**, per second (verify minimum). Crawling a big, many-file prefix repeatedly is a common hidden cost.

## C. Classifiers
- A **classifier** reads the data and says "this is format X with this schema" plus a **certainty** number. Highest certainty wins. If none above 0.0 → classification **UNKNOWN**.
- **Built-in** classifier order (first with certainty 1.0 wins): Avro, ORC, Parquet, JSON, BSON, XML, Ion, log formats (Combined Apache, Apache, Linux kernel, Microsoft, Ruby, Squid, Redis), **CSV**, then JDBC/DynamoDB classifiers (Redshift, MySQL, PostgreSQL, Oracle, SQL Server, DynamoDB).
- **Built-in CSV** rules:
  - Detects delimiters: comma, pipe, tab, semicolon, Ctrl-A.
  - Needs **at least 2 columns and 2 rows**.
  - Header is detected only if the first row is all strings, each column under **150** chars (except last), valid column names, and **different from the data rows**. Otherwise columns become `col1, col2, ...`.
  - Creates tables with **LazySimpleSerDe**. For quoted strings, change to **OpenCSVSerDe**, set types to string, set schema change policy to LOG and partitions to `InheritFromTable` for future crawls.
- **Custom classifiers** (you create them **before** the crawler, and they run **first**):
  - **Grok** (patterns for log-like text).
  - **XML** (you give the **row tag**).
  - **JSON** (you give a **JSON path** to the array/records).
  - **CSV** (set delimiter, quote symbol, header handling, and whether to allow single-column files).
- Changing a classifier does **not** reclassify data that was already crawled. To re-classify, **create a new crawler** with the updated classifier.
- Grok is also used for **streaming** log sources in tables (file 3).

## D. How crawlers decide tables vs partitions
- Set an **include path** at the folder where the table starts. If most schemas under it are **similar**, the crawler makes **one table with partitions** (the folders become partition keys).
- Example: `s3://sales/year=2019/month=Jan/day=1` → one table with partition keys `year`, `month`, `day`.
- Hive-style folders `key=value` give **named** partition columns. Other folders get `partition_0`, `partition_1`, ... (you can rename them in the table schema; delete partition indexes first).
- To force **separate tables**, add **each table's root folder as its own include path**.
- If two different schemas sit under one prefix, the crawler may create several tables. **Athena then returns zero results** because one table maps to one prefix. Fix: separate include paths per schema.
- Crawler options (Configure → Output / advanced):
  - **Create a single schema for each include path** (`TableGroupingPolicy = CombineCompatibleSchemas`) when the files are compatible.
  - **Table level** (`TableLevelConfiguration`): tell the crawler at which folder depth the table is.
  - **Table threshold**: max tables the crawler may create (a safety cap).
  - **Exclude patterns**: glob patterns to skip files/folders.
  - **Lake Formation credentials**: crawl S3 data using Lake Formation permissions (same or cross-account).
  - **Security configuration**: encrypts crawler's CloudWatch logs.
- **Sampling**: S3 crawls can sample a subset of files per folder to save time (verify option name).

## E. Recrawl and schema change behavior
- **Recrawl policy** (S3):
  - **Crawl all folders** (`CRAWL_EVERYTHING`): default. Re-reads everything each time.
  - **Crawl new folders only** (`CRAWL_NEW_FOLDERS_ONLY`): **incremental crawl**. Adds only new partitions. Does not change the existing table schema.
  - **Crawl based on events** (`CRAWL_EVENT_MODE`): uses **S3 event notifications** (through SQS) to list only changed subfolders. Fastest for big prefixes.
- **Schema change policy** (what the crawler does when it sees changes) **(verify exact wording)**:
  - Update behavior: **Update the table definition** (`UPDATE_IN_DATABASE`) or **Ignore the change, only log** (`LOG`).
  - Delete behavior (objects gone from the source): **Log**, **Delete table and partitions** (`DELETE_FROM_DATABASE`), or **Mark the table as deprecated** (`DEPRECATE_IN_DATABASE`).
- To **protect hand-edited schemas**, set update behavior to **LOG** and partitions output to **InheritFromTable**.
- The crawler can add **new columns** and new partitions, but it will not safely handle every type change. Plan a controlled schema evolution (Iceberg, Schema Registry) for critical tables.
- A crawler creates **partition indexes** by default for **S3 and Delta Lake** targets.

## F. Keeping partitions in sync with the Catalog (exam skill 2.2.4)
- New S3 folders do **not** appear in the Catalog by themselves. Pick one method:
  1. **Run the crawler** (best with incremental or event mode).
  2. **Athena `MSCK REPAIR TABLE`** (Hive-style folders only; slow for very large tables).
  3. **Athena `ALTER TABLE ADD PARTITION`** (explicit, good after each load).
  4. **API**: `BatchCreatePartition` / `CreatePartition` (good from Lambda or a job).
  5. **Glue ETL job** that writes data and updates the Catalog in the same run: use a catalog sink with **`enableUpdateCatalog=true`** and `updateBehavior` (`UPDATE_IN_DATABASE` or `LOG`), plus `partitionKeys`.
  6. **Athena partition projection**: Athena **computes** partitions from table properties, so **no partitions are stored** in the Catalog. Best for very many predictable partitions (dates, ids). Catch: works only for Athena (and engines that support it).
- If partitions are **not updated** after a job: check logs for "Attempting to fast-forward updates to the Catalog", confirm `enableUpdateCatalog` is true, and check that the schema matches or `updateBehavior` is `UPDATE_IN_DATABASE`.
- **Partition indexes** speed up `GetPartitions` on tables with many partitions:
  - Max **3 indexes** per table. An index is a list of partition keys (any order).
  - The **first key** of the index must be in the filter expression, or the index is not used.
  - Supported types: string/char/varchar, int/bigint/long/tinyint/smallint, date (`yyyy-MM-dd`).
  - Operators: `=, >, >=, <, <=, between`. **AND only**. `OR`, `IN`, `LIKE`, `NOT` are ignored by the index (then filtered after).
  - Each index adds **one index item per partition** and is **billed** as Catalog storage.
  - Index status: CREATING → ACTIVE (or FAILED). Failure examples: **encrypted partitions**, invalid values for the key type, missing partition values.
  - After an index exists you **cannot rename, retype or reorder** the indexed partition keys.
  - **Redshift Spectrum, EMR and Glue Spark DataFrames** use active indexes automatically. **Athena** needs table property `partition_filtering.enabled = true`. **Glue DynamicFrames** need `catalogPartitionPredicate` in `additional_options`.
- In ETL, `push_down_predicate` filters partitions **after** listing them from the Catalog; `catalogPartitionPredicate` filters **on the server** using indexes, so it is much faster for millions of partitions (file 3).

## G. Hive metastore, open table formats and Catalog extras
- **Hive metastore**: the Catalog can **replace** it for EMR and Spark. Migrate an existing metastore with the Glue Hive metastore migration tools (verify details), or point EMR to the Catalog.
- **Iceberg, Hudi, Delta** tables can be registered in the Catalog and read by Athena, EMR, Redshift Spectrum and Glue jobs (support differs per engine, check docs).
- **Table optimization** for **Iceberg** in the Catalog (managed): **compaction**, **snapshot retention**, **orphan file deletion**. Billed **$0.44 per DPU-hour**, per second, **1-minute minimum** (pricing page). Also **column statistics** generation and **materialized view refresh** use the same rate.
- **Column statistics** help cost-based query planning (Redshift Spectrum, Athena).
- **Federated catalogs** can register external catalogs (for example other metastores or lakehouse catalogs) **(verify)**.
- **Cross-account sharing**: use **Catalog resource policies**, **AWS RAM** shares, or **Lake Formation** grants. Lake Formation is the preferred, fine-grained way (database/table/column/row). Name resource links to share without copying **(verify)**.
- **Lake Formation vs IAM only**: with Lake Formation enabled, access to a table is checked by Lake Formation grants in addition to IAM. A job role needs Lake Formation permission, not only S3 permission.
- **Catalog encryption** (settings in the Data Catalog settings page):
  - **Metadata encryption** (KMS key). It encrypts **new** metadata written after you turn it on. **Existing metadata stays unencrypted.**
  - **Connection password encryption** (KMS key) for passwords stored in connections.
  - If the KMS key is disabled or deleted, jobs and crawlers that touch the Catalog fail. Index creation is not supported on **encrypted partitions**.
- **Business catalog** (descriptions, glossary, data products, discovery by analysts) is **SageMaker Catalog** (built on DataZone). The Glue Catalog is the **technical** catalog. Do not mix them.
- **Tags and metadata**: use table properties and Lake Formation tags for classification (for example `pii=true`).

## H. Connections for cataloging and crawling
- To crawl or read a JDBC source you need a **connection** (JDBC URL, credentials, VPC/subnet/security group if private).
- JDBC include path format: `database/schema/table` with `%` as wildcard (for example `mydb/%` or `mydb/public/%`). Different engines differ **(verify)**.
- Crawlers and jobs in a VPC need a route to **S3** (VPC endpoint or NAT) and the security group self-referencing rule (file 5 has the failure list).
- Test a connection from the console before creating the crawler. Many "crawler failed" cases are network, not code.
- One crawler uses one **network** configuration. Crawlers inside a VPC create ENIs in your subnet.

## I. Glue Schema Registry
- **What**: a central place to **register, version and enforce schemas** for **streaming** data. Producers and consumers agree on a schema (a contract). **Serverless and free** (no extra charge).
- **Formats**: **Avro** (1.11.x), **JSON Schema** (Draft-04, 06, 07), **Protobuf** (proto2 and proto3, no extensions or groups).
- **Model**: **registry** (container, has an ARN, can set permissions) → **schema** (name, data format, compatibility mode, checkpoint) → **schema version** (number, definition, metadata key/values).
- A **checkpoint** version is the one new versions are checked against. First version is the default checkpoint. Editing a schema in the console moves the checkpoint to the latest.
- **Compatibility modes** (8): **NONE**, **DISABLED** (no new versions allowed), **BACKWARD**, **BACKWARD_ALL**, **FORWARD**, **FORWARD_ALL**, **FULL**, **FULL_ALL**.
  - **BACKWARD** (recommended): consumers on the **new** schema can read **old** data. Allowed changes: **delete** fields or **add optional** fields. Checked against the **previous** version.
  - **FORWARD**: consumers on the **old** schema can read **new** data. Allowed changes: **add** fields or **delete optional** fields.
  - **FULL**: both directions against the previous version. Allowed: add or remove **optional** fields only.
  - **`_ALL`** variants check against **all previous versions**, not only the last.
  - **NONE**: no check (dev only).
- Avro: an **optional** field has `null` in its type. Adding a **required** field breaks BACKWARD. Removing a required field breaks FORWARD.
- **Serde libraries** (open source, Java): serialize at the producer, deserialize at the consumer. They fetch the schema by ID, **cache** it, and can **auto-register** schemas. Optional **ZLIB compression** of messages.
- **Integrations**: **MSK / Apache Kafka**, **Kinesis Data Streams**, **Managed Service for Apache Flink**, **Lambda** (event source mappings), and **Glue streaming jobs** (Avro only, with schema inference set to false).
- **Limits** (hard): **100 registries** per Region, **10,000 schema versions** per Region, schema payload **170 KB**. Soft: **10 metadata key-value pairs** per schema version.
- Not available in the console in some Regions (for example Middle East (UAE) at the time of the docs).
- When a new schema version appears for a **streaming job's catalog table**: stop the job → update the table's schema → restart the job.
- Schema Registry ≠ Data Catalog: the Registry governs **messages in motion**, the Catalog describes **data at rest**. A Catalog table can **reference** a registry schema.
- Exam angle: "stop breaking consumers when a producer changes a Kafka/Kinesis schema" → **Glue Schema Registry with BACKWARD (or FULL) compatibility**.

## J. Scenarios (if → then, because)
- If Athena, Redshift Spectrum and EMR must all query the same S3 data with one schema → **Glue Data Catalog**, because they all read the same metadata.
- If new daily folders appear in S3 and tables must show them → crawler with **crawl new folders only**, or `ALTER TABLE ADD PARTITION` after each load, because the Catalog does not auto-detect folders.
- If a bucket has millions of files and crawls are slow → **S3 event mode** crawler, because it lists only changed subfolders.
- If a table has millions of partitions and queries are slow to plan → **partition indexes** (or **Athena partition projection**), because `GetPartitions` loads all partitions without them.
- If Athena returns **zero rows** after a crawl → the crawler built several tables from one prefix. Use separate include paths, because Athena maps one table to one prefix.
- If a crawler keeps overwriting columns you renamed → set schema change policy to **LOG** and partitions to **InheritFromTable**.
- If CSV columns come back as `col1, col2...` → the header was not detected. Fix the table schema or use a **custom CSV classifier** that sets header handling.
- If CSV fields with commas inside quotes break → switch SerDe to **OpenCSVSerDe**.
- If a log file format is unusual → **custom grok classifier**.
- If an XML file needs a specific repeating element → **custom XML classifier** with the **row tag**.
- If a job writes new partitions and the Catalog must update in the same run → **`enableUpdateCatalog` + `updateBehavior`** with `partitionKeys`, because no crawler run is needed.
- If a Glue job reads Catalog tables from another account → **Lake Formation** cross-account grants (or a Catalog resource policy + RAM), because roles need table permission.
- If you turned on Catalog encryption and old tables are still readable in plain → expected, because only **new** metadata is encrypted.
- If a Kafka producer changes a field and consumers crash → **Schema Registry** with BACKWARD/FULL compatibility, because bad versions are rejected at registration.
- If a new optional field is added to an Avro schema and BACKWARD mode rejects it → check the field has `null` in its type (optional), because required additions break BACKWARD.
- If you need business glossary and data discovery for analysts → **SageMaker Catalog** (business catalog), not the Glue Catalog alone.
- If a table must be shared without copying metadata → **resource links** with Lake Formation **(verify)**.
- If a crawler fails in a private subnet → check **S3 VPC endpoint**, self-referencing security group rule and DNS, because most failures are network.

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: how crawlers work and partition detection, classifier list and CSV rules, crawler customization topics, partition indexes (limits, operators, engine behavior), partition predicates, Catalog encryption note, quotas page, pricing page, Schema Registry (formats, compatibility modes, limits, integrations).
Not confirmed (verify): schema change policy option labels, cron minimum of 5 minutes, crawl sampling option name, full list of crawlable sources, JDBC include path patterns, crawler DPU minimum billing, federated catalogs, resource links and RAM behavior, Hive metastore migration tooling, QuickSight as a Catalog reader.

# DynamoDB – 1. Basics, data model, APIs, PartiQL, transactions

Short notes. Each point is a fact you can be asked about.

## A. What DynamoDB is
- Fully managed, serverless NoSQL key-value and document database.
- Single-digit millisecond reads and writes at any scale (SLA-backed).
- No servers, no patching, no capacity planning in on-demand mode.
- Data is automatically replicated across 3 AZs in a Region.
- Schemaless: only the primary key is defined up front. Other attributes can differ item by item.
- Pick it for: key-based lookups at massive scale, sessions, carts, user profiles, IoT/device state, leaderboards, game state, metadata stores, event/idempotency stores, high-throughput APIs.
- Avoid it for: ad hoc queries and joins, unknown access patterns, heavy analytics/aggregations, full-text search, items over 400 KB, complex multi-table transactions at scale.
- Not a relational database. You design tables around the questions (access patterns) you will ask.
- Uses HTTP(S) API calls (no connections or drivers pool like SQL). Good with Lambda.

## B. Compared with other stores
- vs RDS/Aurora: DynamoDB scales horizontally with key lookups and no joins; RDS gives SQL, joins, ad hoc queries, transactions across tables.
- vs DocumentDB: DynamoDB is AWS-native, serverless, key-based, 400 KB items, multi-active global tables; DocumentDB is MongoDB-compatible, VPC-only, instance-based (or Serverless), 16 MiB documents, rich ad hoc queries and aggregations. Use DocumentDB for MongoDB apps and flexible queries; DynamoDB for known key-based access at huge scale. Full comparison table: `../04-documentdb/1-basics-architecture-data-model-and-comparison.md` (section J).
- vs Keyspaces: Keyspaces is Cassandra-compatible (CQL); DynamoDB has broader AWS integration.
- vs S3: S3 stores objects cheaply; DynamoDB gives millisecond item access by key. Store big payloads in S3 and keep a pointer in DynamoDB.
- vs ElastiCache/MemoryDB: those are in-memory; DynamoDB is durable disk-based; DAX adds a cache in front of DynamoDB.
- vs Redshift/Athena: those are for analytics; DynamoDB is for operational lookups. Export or zero-ETL data out for analysis.
- vs OpenSearch: OpenSearch does search; use DynamoDB zero-ETL or Streams to feed it.

## C. Core terms
- Table: a collection of items. No fixed schema except the key.
- Item: one record (like a row). Max 400 KB including attribute names and values.
- Attribute: a field in an item (name + value).
- Primary key: uniquely identifies an item. Two kinds:
  - Simple: partition key only.
  - Composite: partition key + sort key.
- Partition key (hash key): DynamoDB hashes it to choose the physical partition.
- Sort key (range key): orders items that share the same partition key and allows range queries.
- Item collection: all items with the same partition key (in a table with a sort key).
- Secondary index: an alternate key to query by (GSI or LSI). See file 2.
- Capacity: read/write units. See file 2.
- Stream: ordered log of item changes. See file 3.
- TTL: automatic expiry of items. See file 3.

## D. Data types and naming rules (verified)
- Scalar types: String (S), Number (N), Binary (B), Boolean (BOOL), Null (NULL).
- Document types: List (L), Map (M). Can nest up to 32 levels deep.
- Set types: String set (SS), Number set (NS), Binary set (BS). All elements same type, unique, unordered. Empty sets are not allowed.
- Key attributes must be String, Number or Binary only.
- Numbers: up to 38 digits of precision. Positive range 1E-130 to 9.99E+125. Use String for more precision. Numbers travel as strings over the wire.
- Dates: no native date type. Store ISO 8601 strings (sortable, readable) or epoch seconds as Number (smaller; required for TTL).
- Partition key value max 2048 bytes. Sort key value max 1024 bytes.
- Item size max 400 KB. Attribute names count toward item size. Short attribute names save storage and read units.
- Table and index names: 3 to 255 characters; letters, numbers, underscore, hyphen, dot.
- Attribute names: at least 1 character, under 64 KB. Secondary index key attribute names are limited to 255 characters.
- Names are case sensitive, UTF-8. Strings compare by UTF-8 bytes ("a" is greater than "A").
- Empty string/binary values are allowed for non-key attributes. Empty lists and maps are allowed.
- Reserved words and the characters `#` and `:` need expression attribute names/values (`#name`, `:val`).

## E. How partitions work (why key choice matters)
- DynamoDB spreads items across partitions using a hash of the partition key.
- Each partition has limits (about 10 GB of data, about 3,000 read units and 1,000 write units per second, verify). DynamoDB splits partitions automatically as data or traffic grows.
- A good partition key has many distinct values and spreads traffic evenly (user ID, order ID, device ID).
- A bad partition key has few values or one very popular value (country, status, today's date). It creates a hot partition and throttling even when total capacity is unused.
- Sort key design lets one Query read a group: `orderDate`, `type#id`, version numbers, hierarchy paths.
- Items with the same partition key are stored together and sorted by sort key.
- Throughput is per partition, so heavy traffic on one key is limited by the partition limit.
- Adaptive capacity helps with uneven access but does not remove the per-partition ceiling.

## F. Design approach (NoSQL is query-first)
- Start from access patterns: list every question the app asks, how often, and how fast.
- Then choose keys and indexes to answer them with Query/GetItem, not Scan.
- Relational thinking (normalize, join) does not fit. Denormalize: store data in the shape you read it.
- Single-table design: put several entity types in one table, use generic key names (`PK`, `SK`) and prefixes (`USER#123`, `ORDER#2026-10-01#9001`).
  - Benefit: one Query can return a parent and its children together (fewer calls, lower latency).
  - Cost: harder to understand, hard to change later, awkward for analytics and for teams new to NoSQL.
- Multiple tables are fine when entities have different scaling, security, backup, TTL or lifecycle needs, or when the team wants simplicity.
- Worked example (customers and orders):
  - `PK = CUSTOMER#c1`, `SK = PROFILE` → customer details.
  - `PK = CUSTOMER#c1`, `SK = ORDER#2026-10-01#o9` → one order for that customer.
  - Query `PK = CUSTOMER#c1` and `begins_with(SK, "ORDER#")` → all orders for a customer, sorted by date.
  - GSI with `GSI1PK = ORDER#o9` → fetch an order by ID alone.
  - GSI on `status` + `date` (sparse, only open orders) → list open orders.
- One-to-many: child items under the parent's partition key.
- Many-to-many: adjacency list pattern (items for each edge, with a GSI that flips the key direction).
- Time series: put the time in the sort key; for very high rates, shard the key (`device#3#2026-10`) or use separate tables per time period so old tables can be dropped cheaply.
- Large values: store in S3 and keep the S3 key in the item. Keep hot, small attributes in DynamoDB.
- Keep items small. Reads cost by item size, so split rarely-read big attributes into separate items.
- Version attribute for optimistic locking (see section I).

## G. API groups (verified)
- Control plane (manage tables): CreateTable, DescribeTable, ListTables, UpdateTable (capacity, indexes, streams, table class, deletion protection), DeleteTable.
- Data plane (work with items): PutItem, GetItem, UpdateItem, DeleteItem, BatchGetItem, BatchWriteItem, Query, Scan, TransactGetItems, TransactWriteItems, ExecuteStatement, BatchExecuteStatement, ExecuteTransaction.
- Streams API (separate endpoint): ListStreams, DescribeStream, GetShardIterator, GetRecords.
- Import/export/backup APIs: ExportTableToPointInTime, ImportTable, CreateBackup, RestoreTableFromBackup, RestoreTableToPointInTime, UpdateContinuousBackups.
- TTL APIs: UpdateTimeToLive, DescribeTimeToLive.
- Global tables APIs: UpdateTable with replica updates, DescribeTable.
- Control-plane calls are rate limited and eventually consistent (a new table is CREATING until ACTIVE). Create tables with secondary indexes one at a time or you get LimitExceededException.

## H. Reading and writing items
- PutItem: write one item. Replaces the whole existing item with the same key (no merge). Use a condition to avoid overwriting.
- GetItem: read one item by its full primary key. Can return a subset of attributes (projection expression). Eventually consistent by default; `ConsistentRead=true` for strong.
- UpdateItem: change some attributes without sending the whole item. Can SET, REMOVE, ADD (numbers, sets), DELETE (from sets). Creates the item if it does not exist (upsert).
- DeleteItem: remove one item by full key. Can return the old item.
- BatchGetItem: up to 100 items (and 16 MB) across tables. Unprocessed keys come back; retry them.
- BatchWriteItem: up to 25 puts/deletes (16 MB total, item 400 KB). No updates, no conditions. Partial success is possible; retry `UnprocessedItems` with backoff.
- Query: read items with one partition key value, optionally with a sort key condition (`=`, `<`, `<=`, `>`, `>=`, `BETWEEN`, `begins_with`). Fast and efficient. Works on tables and indexes. Can sort ascending/descending (`ScanIndexForward`).
- Scan: reads every item in the table or index, then filters. Slow and costly on big tables. Use only for small tables, one-off jobs, exports (prefer Export to S3), or parallel scans in controlled batches.
- Scan and Query return at most 1 MB per call. If more data exists, the response has `LastEvaluatedKey`; pass it as `ExclusiveStartKey` for the next page. The SDK paginators do this for you.
- `Limit` caps items evaluated per page, not total results.
- Filter expressions run after the read. You still pay for all items read; they only reduce what is returned.
- Key condition expression chooses items to read (cheap). Filter expression trims results (no saving).
- Projection expression returns only some attributes (saves bandwidth, not read capacity).
- Count: `Select=COUNT` still reads the items (same capacity).
- Parallel Scan: `Segment` and `TotalSegments` split a scan among workers.
- Return values: `ReturnValues` (NONE, ALL_OLD, ALL_NEW, UPDATED_OLD, UPDATED_NEW) on writes. `ReturnConsumedCapacity` shows capacity used.
- Query on a GSI/LSI works like Query on the table, but only returns projected attributes (GSI).
- Reading a missing item still consumes read capacity.
- Names and values in expressions use placeholders: `#n` for names, `:v` for values.

## I. Conditional writes, counters, locking
- Condition expression on PutItem/UpdateItem/DeleteItem: the write only happens if the condition is true. Otherwise `ConditionalCheckFailedException` (HTTP 400). A failed condition still consumes write capacity.
- Prevent overwrite: `attribute_not_exists(pk)` on PutItem (creates only if absent).
- Idempotent create: same as above with a client-provided ID.
- Atomic counter: `SET views = views + :one`. Safe under concurrency, but not idempotent if retried.
- Optimistic locking: keep a `version` attribute. Update with condition `version = :expected` and `SET version = :new`. If it fails, re-read and retry.
- Conditional delete: only delete if status is expected.
- Update expression functions: `if_not_exists`, `list_append`, `attribute_exists`, `size`, `contains`, `begins_with`.
- Use `ConditionCheck` inside transactions to guard other items.

## J. Consistency
- Eventually consistent read (default): may return stale data for a short time; costs half a read unit; available on tables, LSIs and GSIs.
- Strongly consistent read (`ConsistentRead=true`): latest committed data; full cost; not available on GSIs; not available for reads in other Regions of global tables.
- Transactional read: serializable; double cost.
- Writes are durable once acknowledged (replicated to multiple AZs).
- Global secondary indexes are updated asynchronously, so GSI queries are always eventually consistent.
- DAX only caches eventually consistent reads.

## K. PartiQL (SQL-compatible)
- DynamoDB supports a subset of PartiQL. Ion data format is not supported.
- Statements: SELECT, INSERT, UPDATE, DELETE.
- API calls: ExecuteStatement (one statement; reads multiple items or writes one), BatchExecuteStatement (many statements, one round trip), ExecuteTransaction (all-or-nothing).
- Same performance, latency and availability as the classic APIs; it is another way to call the same engine.
- Run from console, NoSQL Workbench, CLI, SDKs.
- SELECT with the partition key in WHERE behaves like a Query. Without a key condition it becomes a full Scan (verify) – costly.
- UPDATE and DELETE need the full primary key. INSERT writes one item per statement.
- Index queries use the table.index form (quoted names).
- Results are paged (1 MB) with `NextToken`.
- IAM actions are PartiQL-specific (`dynamodb:PartiQLSelect`, `PartiQLInsert`, `PartiQLUpdate`, `PartiQLDelete`) – verify names. A condition key can deny full table scans.
- CloudWatch has a `Verb` dimension for PartiQL operations (PartiQLSelect, etc.).
- Use PartiQL when SQL-style access is more convenient; keep the same key-design rules.

## L. Transactions (verified)
- TransactWriteItems: up to 100 actions (Put, Update, Delete, ConditionCheck) on up to 100 distinct items, total size 4 MB. All succeed or none.
- TransactGetItems: up to 100 Get actions, 4 MB. Gives an atomic snapshot read.
- Same AWS account and same Region only. Can span multiple tables.
- Cannot target the same item twice in one transaction. Cannot be performed through indexes.
- Idempotent with a client token (valid 10 minutes). Same token + different parameters → IdempotentParameterMismatch.
- Capacity: 2 reads/writes per item (prepare + commit). Costs the same even when canceled.
- Isolation: serializable between a transaction and a standard single-item read/write; between a transaction and BatchGet/Query/Scan it is read-committed; BatchWriteItem as a whole is not serializable with a transaction.
- Conflicts: `TransactionCanceledException` (with CancellationReasons per item) for transaction requests; `TransactionConflictException` for a single write that clashes with an in-flight transaction. SDKs do not retry canceled transactions automatically.
- `TransactionInProgressException` on idempotent retry while the first is still running.
- Changes reach GSIs, streams and backups gradually. Stream consumers should not assume transaction atomicity or order.
- Not atomic across Regions in global tables. Replicas may show partial transactions briefly.
- Best practices: keep transactions small, avoid for bulk loading (use BatchWriteItem), group frequently co-updated attributes in one item, enable auto scaling or on-demand.
- With DAX: TransactWriteItems writes through; TransactGetItems passes through uncached.

## M. Scenarios (if → then, because)
- **If** you know the full primary key and need just one item, **then** use **GetItem**, which reads one item by its full key. **This works because** it touches only that one item, so it is the cheapest read; an eventually consistent read costs half of a strongly consistent one.
- **If** you need all items for one customer, sorted by date, **then** use **Query** with partition key = the customer ID and a **sort key** condition on the date (for example `BETWEEN` or `begins_with`). **This works because** items with the same partition key are stored together in sort-key order, so one Query reads just that group. It can return newest first with `ScanIndexForward=false`.
- **If** you often need to find items by an attribute that is not part of the key (for example email), **then** add a **Global Secondary Index (GSI)**, an extra copy of the data with that attribute as its key, and Query the index. **This works because** a **Scan** reads every item in the table and you pay for all of it, while a Query on the index reads only matching items. A GSI can be added at any time.
- **If** you need to scan a large table for analytics, **then** use **Export to S3** (needs **Point-in-Time Recovery (PITR)** on) or a **zero-ETL** integration, and query the copy with **Amazon Athena** or **Amazon Redshift**. **This works because** a Scan uses read capacity for every item it evaluates and competes with the live app, while an export uses **no read capacity** and does not slow the table.
- **If** a write must never overwrite an existing item, **then** use **PutItem** with the condition `attribute_not_exists(pk)`. **This works because** PutItem normally replaces the whole item with the same key; with the condition it writes only when no item exists, otherwise it fails with `ConditionalCheckFailedException` (which still uses write capacity).
- **If** two clients may update the same item at the same time, **then** use **optimistic locking**: keep a `version` attribute and update with the condition `version = :expected` while setting a new version. **This works because** the second writer's condition fails instead of silently overwriting the first change; that client re-reads the item and retries.
- **If** many clients increase one counter, **then** use **UpdateItem** with `SET n = n + :1` (an **atomic counter**). **This works because** DynamoDB applies the increment safely under concurrency, with no read-modify-write in the app. The catch: it is **not idempotent**, so a retried request can count twice.
- **If** several items must change together, like a money transfer that debits one account and credits another, **then** use **TransactWriteItems**. **This works because** a transaction is **all or nothing**: up to **100** actions on up to 100 items (**4 MB** total), in one account and Region, either all succeed or none do. The catch: each item costs **two** writes (prepare + commit), even if the transaction is cancelled.
- **If** you must write 10,000 items fast and they do not need to succeed together, **then** use **BatchWriteItem** (up to **25** puts or deletes per call) and retry `UnprocessedItems` with backoff; for a brand-new table, use **Import from S3** instead. **This works because** batching cuts round trips, and Import loads a new table without using write capacity. BatchWriteItem allows no updates and no conditions, and partial success is possible.
- **If** an item would be larger than the **400 KB** item limit, **then** store the big payload in **Amazon S3** and keep only the S3 key (a pointer) plus small, often-read attributes in the DynamoDB item. **This works because** S3 stores large objects cheaply while DynamoDB gives fast access by key; smaller items also cost fewer read units.
- **If** a filter expression throws away most items after a Query, **then** redesign the keys or add an index (for example a sparse GSI) so the Query reads only the items you need. **This works because** filters run **after** the read: you still pay for every item read, and the filter only shrinks what is returned.
- **If** a read must see the newest data right after a write, **then** set `ConsistentRead=true` on GetItem or Query against the **table** (or a Local Secondary Index (LSI)), not a GSI. **This works because** a strongly consistent read returns the latest committed data, at full read cost. GSIs are updated asynchronously, so GSI reads are always eventually consistent.
- **If** a team prefers SQL-style syntax, **then** use **PartiQL**, DynamoDB's SQL-compatible language (SELECT, INSERT, UPDATE, DELETE), but still design around the keys. **This works because** PartiQL calls the same engine with the same performance. The catch: a SELECT without the partition key in WHERE becomes a full Scan (verify), which is costly.
- **If** a table is queried by status, which has only a few distinct values, **then** do **not** make status the partition key; use a **sparse GSI** (only items that have the index key appear, such as open orders) or a composite key. **This works because** DynamoDB spreads data by hashing the partition key; few values means a few **hot partitions** and throttling even when total capacity is unused.
- **If** a design needs joins across many entities or ad hoc queries, **then** consider **Amazon RDS** or **Amazon Aurora** (relational databases) instead. **This works because** DynamoDB has no joins and is built around known key-based access patterns, while RDS/Aurora give SQL, joins and ad hoc queries.
- **If** the data is a time series with heavy writes, **then** put the time in the sort key and use **time-bucketed partition keys** (for example `device#3#2026-10`) or separate tables per period, plus **Time to Live (TTL)** to expire old items. **This works because** buckets spread writes over many partitions, old tables can be dropped cheaply, and TTL deletes use no write capacity.
- **If** several related entity types are read together (for example a customer and their orders), **then** a **single-table design** with generic keys (`PK`, `SK`) lets one Query return the parent and its children; **if** entities differ in scaling, security, backup, TTL or lifecycle needs, **then** use **separate tables**. **This works because** a single table cuts calls and latency, but it is harder to understand and change, so split tables when needs differ.
- **If** someone suggests a date as the only partition key, **then** reject it and use a key with many distinct values (such as user or device ID), adding the date to the sort key or a shard suffix if needed. **This works because** every write of the day goes to the same key value, so all traffic hits **one hot partition**, which has its own throughput ceiling.
- **If** you must find an item by two different IDs, **then** keep the table keyed by one ID and add a **GSI** on the second ID, or store a duplicate item keyed by the second ID. **This works because** GetItem and Query need a key, and a GSI gives an alternate key that DynamoDB keeps in sync for you (eventually consistent).

## Verified from AWS docs on 2026-10-02
API overview, naming rules and data types, read/write capacity unit rules, transactions page were read. Not confirmed (verify): PartiQL scan behavior and IAM action names, exact partition ceilings (10 GB / 3,000 RCU / 1,000 WCU), BatchGetItem/BatchWriteItem size limits (16 MB).

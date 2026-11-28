# Redshift – 2. Table design: schemas, distribution, sort keys, encodings, VACUUM/ANALYZE, materialized views, locks, SQL features

Short notes. Each point is a fact you can be asked about.

## A. Dimensional design (star schema)
- **Fact table**: one row per event (order line, click, payment). Very large. Has foreign-key-like columns to dimensions plus numeric measures.
- **Dimension tables**: describe things (product, customer, store, **date**). Smaller; used in `WHERE`, `GROUP BY`.
- **Star schema**: fact in the center, dimensions around it (joined by keys). **Snowflake schema**: dimensions normalized further (more joins, less duplication).
- Queries look like: fact `JOIN` dimension `WHERE` dimension filter `GROUP BY` dimension column `SUM(measure)`.
- **Denormalize** for speed (fewer joins), unlike OLTP. Keep a **date dimension** for easy time grouping.
- **Slowly changing dimensions (SCD)**: type 1 overwrite; type 2 keep history rows with valid-from/valid-to dates.
- **Staging tables** hold raw loads, then transform into final tables (ELT).
- Redshift also supports wide denormalized tables and the **SUPER** type for semi-structured data.
- Schemas organize objects: `raw`, `staging`, `mart`. Max **9,900 schemas per database** (the doc says per database per cluster).

## B. Distribution styles (verified)
- Decides **which slice stores each row**. Goal: even spread + **co-located joins**.
- **AUTO** (default): Redshift picks. Starts small tables as **ALL**; as they grow may change to **KEY** (primary key column) or **EVEN**; changes happen in the background.
- **EVEN**: round-robin across slices. Use when the table is not joined or no clear choice between KEY and ALL.
- **KEY**: rows with the same value in the distribution column go to the same slice. Distribute **both sides of a big join on the join column** to avoid network movement.
- **ALL**: a full copy on **every node**. Use for **small, rarely changed dimension tables** joined often. Costs storage × nodes and slows loads/updates. Redshift says there is little benefit for very small tables (cheap to redistribute anyway).
- Rules of thumb:
  - Pick **KEY** on the most common big-join column (high cardinality, even spread).
  - Pick **ALL** for small, slow-changing dimensions.
  - Pick **EVEN** or **AUTO** otherwise.
  - Avoid KEY on a column with **skewed values** (one value with huge share) → **data skew**, one slice does most work.
  - Avoid KEY on a column you filter by a single value often (queries then hit one slice).
- No partitioning in Redshift tables: there are no table spaces or partition schemes; distribution + sort replace them.
- Change style later with `ALTER TABLE ... ALTER DISTSTYLE`, or rebuild with a **deep copy** (`CREATE TABLE AS` / insert into new table).
- See current style in `PG_CLASS_INFO`; recommendations in `SVV_ALTER_TABLE_RECOMMENDATIONS`; auto actions in `SVL_AUTO_WORKER_ACTION`.
- In EXPLAIN plans:
  - `DS_DIST_NONE`/`DS_DIST_ALL_NONE`: no data movement (good, co-located or ALL).
  - `DS_BCAST_INNER`: inner table broadcast to all nodes (OK for small inner).
  - `DS_DIST_ALL_INNER`, `DS_DIST_INNER`, `DS_DIST_OUTER`, `DS_DIST_BOTH`: data redistributed over the network (expensive for big tables).

## C. Sort keys (verified + notes)
- Rows are stored on disk **sorted by the sort key**. Each 1 MB block keeps min/max (zone map), so queries with filters on sort key columns **skip blocks**.
- Types:
  - **Compound sort key**: sorted by column 1, then column 2, etc. (like a phone book). Best when queries filter on the **leading column(s)**. Most common choice.
  - **Interleaved sort key**: gives equal weight to each column. Good for queries that filter on **different columns each time**. Needs heavier VACUUM; not supported by concurrency scaling; limited use today.
  - **AUTO** (default): Redshift picks or adds sort keys from query patterns (**automatic table optimization**).
- Good sort key columns: **timestamp/date** (most filtered, loaded in order), columns used in range filters, columns used in joins/merge joins.
- If you load data in time order and sort by timestamp, new rows are already sorted → little VACUUM needed.
- Only the first ~8 bytes of a long string participate in zone maps; avoid sorting by long text (verify).
- Use `SVV_TABLE_INFO` columns `unsorted` and `vacuum_sort_benefit` to decide whether sorting is worth it.
- Unlike an index, a sort key costs nothing extra to store; it affects load/VACUUM work.

## D. Automatic table optimization and encodings (verified + notes)
- **Automatic table optimization (ATO)**: Redshift observes queries and **applies sort and distribution keys automatically** (tables with AUTO). Changes happen in the background within hours when enough queries ran.
- **Column compression encodings**: Redshift can pick them automatically (`ENCODE AUTO`). Common encodings: **AZ64** (numbers, dates; Amazon's), **ZSTD** (general, strong), **LZO**, **BYTEDICT**, **RUNLENGTH**, **DELTA**, **RAW** (none), **TEXT255/TEXT32K**. Sort-key leading columns are often left **RAW** to keep zone maps effective (verify).
- `COPY` into an empty table can analyze data and set encodings (`COMPUPDATE`).
- `ANALYZE COMPRESSION` suggests encodings.
- Compression reduces I/O and storage. It does not change query results.
- Data types: standard numeric, `CHAR/VARCHAR`, `DATE`, `TIMESTAMP[TZ]`, `BOOLEAN`, `DECIMAL`, `GEOMETRY/GEOGRAPHY`, `VARBYTE`, `HLLSKETCH`, **SUPER**.
- Size `VARCHAR` realistically: too large wastes memory in queries (uses declared length for sort/hash memory).
- **Constraints**: `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE` are **informational only (not enforced)**. The optimizer uses them for plans, so wrong declarations give wrong results. **`NOT NULL` is enforced**.
- Identity columns, default values, and generated values exist; identity values are not guaranteed gap-free or sequential in parallel loads.

## E. SUPER type and semi-structured data (verified in streaming page + notes)
- **SUPER** stores JSON-like nested data (arrays, objects) without a fixed schema.
- Load JSON into SUPER with `JSON_PARSE` or `COPY ... FORMAT JSON 'noshred'`. Query with **PartiQL** dot/bracket notation (`data.customer.name`, `data.items[0]`), `UNNEST`, navigate arrays.
- Prefer **`JSON_PARSE` into SUPER** over many `JSON_EXTRACT_PATH_TEXT` calls: each extraction re-parses the JSON (slow). `JSON_EXTRACT_PATH_TEXT` also has a **16 MB** limit.
- A single SUPER value is limited to **16 MB**.
- Use SUPER for variable, nested events; promote hot fields into normal columns for speed.

## F. Maintenance: VACUUM and ANALYZE (verified)
- **Why**: DELETE and UPDATE do not remove rows immediately; they **mark rows deleted**. Updates are delete + insert. Over time tables have deleted-row space and an **unsorted region**.
- **VACUUM** reclaims space and re-sorts. Types: `FULL` (default: sort + delete), `SORT ONLY`, `DELETE ONLY`, `REINDEX` (interleaved), `RECLUSTER` (cheaper; sorts only unsorted portion), `BOOST` (more resources).
- **Automatic**: Redshift runs **automatic table sort** and **automatic VACUUM DELETE** in the background when load is low, and pauses during heavy load. You rarely need manual VACUUM, but may run it after a very large load.
- Default **sort threshold**: VACUUM skips sorting a table that is **more than 95% sorted**. Can change per table.
- VACUUM is I/O heavy. Run in quiet hours. Users can read/write while vacuuming; DDL is blocked until it finishes. Incremental merges briefly block concurrent UPDATE/DELETE.
- If VACUUM fails midway, the table stays **consistent**; restart manually.
- `TRUNCATE` and `VACUUM` **auto-commit** the current transaction.
- **ANALYZE** updates table statistics for the query planner. **Automatic analyze** runs in the background. Run `ANALYZE` after big loads or when plans look wrong. Stale stats = bad plans.
- Check `SVV_TABLE_INFO` columns: `stats_off`, `unsorted`, `tbl_rows`, `size`, `skew_rows`.
- Truncating and reloading a table is faster than DELETE-all + VACUUM.
- **Deep copy** (create new table, insert, drop old) can replace a heavy VACUUM.

## G. Materialized views (MV) (verified)
- An MV **stores the precomputed result** of a query (joins/aggregates). Queries on the MV avoid scanning base tables. Great for **predictable, repeated dashboards** (for example QuickSight).
- Can be defined on **other MVs**, base tables, **external (Spectrum) tables**, and can be stored as **Apache Iceberg tables** in S3 / S3 Tables registered in the Glue Data Catalog (readable by Spark, Athena, Trino). Iceberg MVs support incremental refresh.
- **Refresh**:
  - Manual: `REFRESH MATERIALIZED VIEW`.
  - **AUTO REFRESH YES**: Redshift refreshes when base tables change, when resources are available (workload-dependent timing).
  - **Scheduled** refresh via the query scheduler.
  - **Incremental** refresh when possible; otherwise full recompute.
- **Automatic query rewriting**: the optimizer can transparently use an MV for queries that don't reference it, **if the MV is up to date**.
- **Automated materialized views (AutoMV)**: Redshift creates/drops MVs for you from workload patterns.
- MVs for **streaming ingestion** (Kinesis/MSK) are special (see file 3).
- Monitor with `STV_MV_INFO`, `STL_MV_STATE`, `SVL_MV_REFRESH_STATUS`, `STV_MV_DEPS`.
- MVs can use UDFs (limits apply).
- Exam: "speed up repeated, expensive dashboard queries without changing them" → **materialized view with auto refresh + auto rewrite**.
- MV vs normal view: view = saved query, runs every time. MV = stored data, must be refreshed.
- **Late-binding views** don't bind to underlying tables until query time (needed for views over external tables).

## H. Transactions, isolation and locks (verified + notes; exam skill 2.1.6)
- Redshift supports **ACID transactions** with **serializable isolation** (default and only mode for user transactions).
- Reads see the **latest committed snapshot** — readers don't wait for writers ("MVCC-like").
- Default is **autocommit** per statement. A `BEGIN … COMMIT` block commits as one transaction. `TRUNCATE` and `VACUUM` auto-commit.
- **Concurrent writes** to the **same table** can conflict. If two overlapping transactions can't be serialized you get a **serializable isolation violation** (error 1023). Fix: retry the transaction, serialize writers (queue them), or write to separate tables then combine.
- **Locks** (table-level): ordinary `SELECT` takes `AccessShareLock`; INSERT/UPDATE/DELETE take `RowExclusiveLock`; DDL, TRUNCATE and `LOCK` can take `AccessExclusiveLock` (blocks readers and writers).
- **Deadlock** can occur if two transactions lock tables in opposite orders → one is aborted. **Always lock/touch tables in the same order**.
- Long-running transactions hold locks and block VACUUM and DDL. Idle open transactions are ended after **6 hours**.
- Troubleshoot locks: `SVV_TRANSACTIONS`, `STV_LOCKS`, `STV_RECENTS`/`SYS_QUERY_HISTORY`; kill blocker with `PG_TERMINATE_BACKEND(pid)` (superuser).
- Concurrent **COPY** into the same table is allowed in parallel batches; Redshift serializes commits.
- Best practice: keep transactions **short**, commit often, avoid user transactions that wrap long-running reads and writes.
- Locking contrasts: RDS/Aurora use row-level locks; Redshift locks at **table level** for most writes.

## I. SQL features worth naming
- **Window functions** (RANK, ROW_NUMBER, LAG), **CTEs**, **recursive CTEs**, subqueries, `UNION`, `INTERSECT`, `MINUS`.
- **MERGE** command (upsert) and the older **staging table pattern** (delete matching rows, insert new). (verify MERGE availability and syntax)
- **Stored procedures** (PL/pgSQL), up to **10,000** per database.
- **UDFs**: SQL UDFs, **Lambda UDFs** (call AWS Lambda). **Python UDFs: end of support after 30 June 2026.**
- **Temporary tables** (session-bound, faster, not backed up). Count toward table limits.
- **Approximate functions**: `APPROXIMATE COUNT(DISTINCT …)`, HyperLogLog (`HLLSKETCH`) for fast distinct counts.
- **PartiQL** for SUPER; **JSON functions**; `COPY`/`UNLOAD`; `CREATE TABLE AS`; `SELECT INTO`.
- **Roles (RBAC)**: `CREATE ROLE`, grant roles to users (see file 5). Up to **1,000 roles** per cluster/workgroup.
- **Datashares** appear as read-only (or writable) databases.
- **Case sensitivity**: identifiers are folded to lowercase by default; `enable_case_sensitive_identifier` changes this (matters for zero-ETL and streaming sources).
- **System views**: prefer new **`SYS_*`** views (work for provisioned and Serverless) over older `STL_/STV_/SVL_/SVV_` views.

## J. Design best practices (quick list)
- Pick **KEY** distribution on the biggest join column; **ALL** for small dimensions; otherwise AUTO.
- Pick **sort key = timestamp** column commonly filtered (compound), or leave AUTO.
- Let Redshift choose **encodings**.
- Define PK/FK as **informational** to help planner, but remember they are not enforced; **enforce uniqueness in ELT logic**.
- Use right-sized `VARCHAR`; avoid `SELECT *`.
- Load with `COPY` in bulk, never row-by-row `INSERT`.
- Use **materialized views** for repeated heavy aggregations.
- Keep statistics fresh (automatic analyze or manual after big loads).
- Use **temp/staging tables** for transformations.
- Don't over-use interleaved sort keys.
- Avoid tiny frequent transactions; batch writes.

## Scenarios (if → then, because)
- **If** two **5 TB** tables are joined on `customer_id` all day, **then** set **DISTKEY(customer_id)** (KEY distribution) on **both** tables. KEY distribution sends rows with the same value to the same **slice** (one parallel worker inside a node). **This works because** matching rows from both tables already sit together, so the join needs no data movement over the network. In the query plan you see `DS_DIST_NONE` instead of costly redistribution steps.
- **If** a small **50-row** `country` dimension table is joined often, **then** use **DISTSTYLE ALL** (or **AUTO**). ALL keeps a full copy of the table on **every node**. **This works because** every node can join locally with no data movement. The cost is extra storage and slower loads, so ALL suits small, rarely changed tables; AUTO starts small tables as ALL anyway.
- **If** one `customer_id` holds **40%** of all rows and is the distribution key, **then** switch to **EVEN** distribution (round-robin across slices) or a better-spread key. **This works because** KEY puts all rows of one value on one slice, so that slice does most of the work (**data skew**) while others wait. Change it with `ALTER TABLE ... ALTER DISTSTYLE` or a deep copy.
- **If** queries filter by `order_date` ranges, **then** make `order_date` the **sort key**. Rows are stored on disk in sort-key order. **This works because** each **1 MB block** keeps its min/max values (a **zone map**), so a date-range query skips every block outside the range. Loading data in date order also keeps new rows sorted, so little VACUUM is needed.
- **If** queries filter on many different columns with equal importance, **then** consider an **interleaved sort key**, which gives equal weight to each column. The catch: it needs heavier **VACUUM** (`REINDEX`), is not supported by **concurrency scaling** (verify), and has limited use today.
- **If** nobody on the team wants to tune tables, **then** leave **DISTSTYLE AUTO** and **SORTKEY AUTO**. **This works because** **automatic table optimization (ATO)** watches the queries and applies sort and distribution keys in the background, usually within hours once enough queries have run.
- **If** a table has many deleted rows and scans get slow, **then** let **automatic VACUUM DELETE** run, and run `VACUUM DELETE ONLY` yourself after a huge delete to speed things up. **This works because** DELETE and UPDATE only **mark** rows as deleted, and VACUUM reclaims that space. Automatic VACUUM runs only when load is low.
- **If** a query plan suddenly gets worse after a big load, **then** run **`ANALYZE`**. **This works because** ANALYZE updates table statistics for the query planner, and stale statistics give bad plans. Automatic analyze runs in the background but may not have caught up yet.
- **If** dashboards run the same heavy join every minute, **then** create a **materialized view (MV)** with **AUTO REFRESH YES**. An MV stores the precomputed result of a query. **This works because** dashboards read the stored result instead of scanning base tables each time, and Redshift refreshes the MV (incrementally when possible) when base tables change. **Automatic query rewriting** can even use the MV for queries that don't name it, if the MV is up to date.
- **If** two ETL jobs write the same table and one fails with **error 1023** (verify), **then** **retry** the failed transaction, or **serialize** the writers (queue them), or write to separate tables and combine. **This works because** Redshift uses **serializable isolation**: when two overlapping transactions can't be put in a safe order, it aborts one with a **serializable isolation violation**.
- **If** a DDL statement (like ALTER or DROP) hangs, **then** find the blocking session in `STV_LOCKS` or `SVV_TRANSACTIONS` and end it with `PG_TERMINATE_BACKEND(pid)` (superuser). **This works because** DDL needs an exclusive table lock, and long or idle open transactions hold locks that block it.
- **If** you need an **upsert** (update existing rows, insert new ones), **then** use the **`MERGE`** command (verify availability and syntax), or the **staging table pattern**: delete matching rows, then insert new ones, in **one transaction**. **This works because** Redshift does **not enforce** unique or primary keys, so a plain INSERT would create duplicates.
- **If** JSON events have a changing, nested schema, **then** store them in a **SUPER** column using **`JSON_PARSE`** and query them with **PartiQL** dot/bracket notation (`data.customer.name`). **This works because** SUPER holds JSON-like data without a fixed schema. One SUPER value is limited to **16 MB**.
- **If** you count on a **unique constraint** to reject duplicate rows, **then** it **won't**; check duplicates in your load logic instead. **This works because** `PRIMARY KEY`, `FOREIGN KEY` and `UNIQUE` are **informational only**: the optimizer uses them for plans, so wrong declarations can even give wrong results. Only **`NOT NULL`** is enforced.

## Verified from AWS docs on 2026-10-02
Read: distribution styles page, automatic table optimization page, VACUUM page, concurrent writes page index, materialized views overview, streaming ingestion page (SUPER/JSON tips), quotas page. Not confirmed (verify): interleaved sort key restrictions today, encoding list details, MERGE command availability, long-string sort-key zone-map behavior, exact lock names/matrix, error 1023 details, case-sensitivity defaults.

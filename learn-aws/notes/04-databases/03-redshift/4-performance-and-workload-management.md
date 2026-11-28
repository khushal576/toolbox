# Redshift – 4. Performance, workload management (WLM), concurrency scaling, query tuning, system views

Short notes. Each point is a fact you can be asked about.

## A. What decides query speed (verified)
- **Number of nodes / slices**: more slices = more parallelism (but more cost).
- **Node type**: size decides CPU, memory, storage speed.
- **Data distribution**: bad distribution = data moved over the network during joins.
- **Sort order**: good sort key = fewer blocks scanned.
- **Dataset size**: more rows to scan/redistribute; archive old data, filter with predicates.
- **Concurrent operations**: queries wait for queue slots and share memory.
- **Query structure**: return only needed rows/columns.
- **Code compilation**: first run of a new query may compile; Redshift uses a composition technique and a remote compilation cache, so new queries start fast and later runs reuse compiled code.
- **Result cache**: identical query on unchanged data returns instantly (cache hit uses no compute). Cache is invalidated when underlying data changes.
- **Statistics**: stale stats → bad plan. Keep ANALYZE current (automatic by default).
- **Hardware health/maintenance**: VACUUM/backups can compete for resources.

## B. Query lifecycle
1. Client sends SQL to the **leader node**.
2. Leader parses, optimizes, builds a plan, compiles code.
3. Query is **routed to a WLM queue** (by user, group, role, or query group, or by priority in auto WLM).
4. Query waits for a **slot/memory** if the queue is full.
5. Compute nodes/slices run the steps in parallel (scan, join, aggregate, redistribute).
6. Leader merges results and returns them (or writes them to S3 for UNLOAD).
- Time shown in monitoring: planning, waiting (queue), executing (read/insert/delete/update/CTAS/unload/copy), commit.

## C. Workload management (WLM) (verified)
- **WLM** controls how queries share cluster memory and concurrency using **queues**. Lets you protect short dashboards from long ETL.
- **Automatic WLM (recommended)**: Redshift decides concurrency and memory per query based on needs of running/queued queries. You can set **query priorities** (`CRITICAL`, `HIGHEST`, `HIGH`, `NORMAL`, `LOW`, `LOWEST`) per queue.
- **Manual WLM**: you set queue count, **concurrency (slots)**, memory %, timeouts.
  - Up to **8 user-defined queues** plus a reserved **superuser queue** (one extra slot; cannot be configured; used with the `superuser` query group).
  - **Default queue** (last in the list) concurrency = **5** by default. **Total slots across user queues max 50**.
  - Queue memory is split **evenly across its slots** (more slots = less memory each → possible disk spill).
  - Assign queries to queues via **user groups**, **user roles**, **query groups** (labels set with `SET query_group TO '…'`), optional **wildcards** (off by default).
  - Option: **concurrency scaling mode** per queue.
  - **WLM timeout** (`max_execution_time`) is deprecated; use **query monitoring rules** instead. If both `statement_timeout` and WLM timeout exist, the lower wins.
- WLM configuration lives in the **parameter group** (`wlm_json_configuration`). **Dynamic** changes apply without reboot; some (changing number of queues in manual WLM) need a reboot (verify).
- Concurrency in WLM is **not** the same as the number of connections (cluster connection limit: up to **2,000** on RA3/RG; DC2 large 500).
- **If more than ~15 queries must run in parallel** with automatic WLM → turn on **concurrency scaling** (adding slots above that can cause contention).
- **Serverless**: no WLM queues to manage; workload is auto-managed; use **max RPU**, **usage limits** and query timeouts.

## D. Query monitoring rules (QMR) (verified)
- Metrics-based rules attached to a WLM queue. When a query crosses a boundary the action is taken.
- Actions: **log** (record only), **hop** (move to another queue, manual WLM), **abort** (cancel), **change priority**.
- Typical metrics: query execution time, CPU time, **blocks read**, rows returned, **nested loop join row count**, spill to disk, queue time, scan row count.
- Examples: abort queries running longer than 60 s in the dashboard queue; log queries with huge nested loop joins; lower priority of queries returning millions of rows.
- Query hopping only moves queries that can be restarted (read-only SELECT, CTAS); others are cancelled.
- Predefined rule templates exist in the console.

## E. Short query acceleration (SQA) (verified)
- Automatically runs **predicted short queries** in a dedicated space so they don't wait behind long ones. Uses ML to predict runtime and a dynamic maximum threshold.
- With SQA you usually **don't need a separate "short queries" queue**.
- Works for SELECT and CTAS. Enabled by default on new clusters (verify).

## F. Concurrency scaling (verified)
- Adds **temporary extra clusters** automatically when queue wait builds up; queries run on them seamlessly. Users see current data.
- Supports **read queries** and common **write operations**: COPY, INSERT, DELETE, UPDATE, CTAS, VACUUM, manual MV refresh, automatic vacuum. Other DDL (for example plain `CREATE TABLE`) is not supported; non-supported writes in a transaction before supported writes keep the whole transaction on the main cluster. **Write support only on RG and RA3 nodes.**
- Turn on per **WLM queue** (`Concurrency Scaling mode = auto`). Eligible queries go to the scaling cluster instead of waiting.
- Parameters: `max_concurrency_scaling_clusters` (default 1; account quota 10). **Usage limits** can cap hours.
- **Cost**: free credit of **1 hour of concurrency-scaling per 24 hours of main-cluster running** (accrues); beyond that, billed **per second** at on-demand rates for the time scaling clusters actively run queries. Applies to read and write operations.
- Not supported for: queries on **tables with interleaved sort keys**, **temporary tables**, queries accessing system/catalog tables, **Python and Lambda UDFs**, queries to external resources under restrictive network/IAM conditions (`aws:sourceVpc`, `aws:sourceVpce`, `aws:sourceIp`), write ops on **DISTSTYLE ALL** target tables or tables with **identity columns**, COPY with ANALYZE.
- Main-cluster requirements: EC2-VPC, supported node types (dc2, rg, ra3), **not single-node**, **32 or fewer compute nodes** (and originally created with ≤ 32).
- Monitor: `ConcurrencyScalingActiveClusters`, `ConcurrencyScalingSeconds`, `SVCS_CONCURRENCY_SCALING_USAGE`, `STL_QUERY.concurrency_scaling_status`; usage-limit metrics.
- Concurrency scaling vs elastic resize: scaling handles **bursts of concurrent queries** (temporary), resize changes **permanent size**.
- Concurrency scaling vs data sharing: scaling clones the same cluster for bursts; data sharing creates **separate consumer** warehouses for isolation.

## G. Reading a slow query (tuning checklist)
- Use **EXPLAIN** to see the plan and cost. Look for:
  - `DS_BCAST_INNER` on a **big** inner table or `DS_DIST_BOTH` → bad distribution; set matching **DISTKEY** or ALL for small dimension.
  - **Nested Loop Join** → missing join condition (cross product) or wrong join; fix the SQL.
  - **Large scans** → add/choose a sort key on filtered column; add predicates; avoid functions on sort key columns in filters.
  - **Hash join spilling to disk** → more memory per query (fewer slots/ larger nodes), reduce rows.
- Look at system views:
  - `SYS_QUERY_HISTORY`, `SYS_QUERY_DETAIL` (new, works for Serverless too), `SYS_QUERY_EVENT`.
  - Classic: `STL_ALERT_EVENT_LOG` (alerts like missing statistics, nested loop, very selective filter, large distribution), `SVL_QUERY_SUMMARY`/`SVL_QUERY_REPORT`, `STL_EXPLAIN`, `SVL_QUERY_METRICS_SUMMARY`.
  - `SVV_TABLE_INFO` for **skew** (`skew_rows`), unsorted %, stats off %, table size.
  - `STV_WLM_QUERY_STATE` / `SYS_WLM_*` for queue time.
- **Disk-based queries**: intermediate results exceed memory and spill to disk → raise memory (fewer slots/larger WLM memory), reduce query width, add nodes. High `PercentageDiskSpaceUsed` can cause failures too.
- **Data skew**: one slice has more rows (bad distribution key) → change key/EVEN.
- **Stale statistics** or **many unsorted rows** → `ANALYZE` / `VACUUM`.
- **Over-wide columns** (large VARCHAR) inflate memory use.
- **Many small commits** (`CommitQueueLength` high): batch writes, avoid autocommit on tiny statements.
- **Too many concurrent users** → WLM, SQA, concurrency scaling, or separate warehouses with data sharing.
- **Join explosions**: check join keys/duplicates.
- Use **Query Editor v2** or console **query monitoring** tab to see CPU/query graphs and top queries.
- Prefer **materialized views** for repeated expensive aggregations; prefer **Spectrum** only for cold data.
- **Redshift Advisor** gives recommendations (compress tables, skip COPY compression, distribution key changes, short query accel…). **Table design advisor** suggests keys.

## H. Query performance patterns (do / don't)
- Do: filter on sort key and partition columns; join on distribution keys; select only needed columns; use `LIMIT` carefully; use CTAS for heavy repeated intermediate steps; use temp tables; use `UNION ALL` instead of `UNION` when duplicates are fine.
- Don't: `SELECT *` on wide tables; join without conditions; apply functions on filtered columns (kills block skipping); use `LIKE '%x%'` on huge text; run many tiny INSERTs; leave huge transactions open.
- **Large result sets** returned to clients are slow: `UNLOAD` to S3 or use cursors/paging.
- **Leader node bottleneck**: queries using leader-only functions or returning huge results strain the leader.

## I. Spectrum and data lake performance
- Partition by date; use Parquet/ORC; compress; large files; partition filters in `WHERE`.
- Use materialized views over external tables for repeated queries.
- Scanned bytes drive cost; select only needed columns in columnar formats.
- Table statistics on external tables (`numRows`) help the planner.

## J. Workload isolation options (compare)
| Option | What it does | Use when |
|---|---|---|
| WLM queues + priorities | Separate queues on the same cluster | Mixed ETL + BI on one cluster |
| QMR | Auto log/abort/hop bad queries | Protect from runaway queries |
| SQA | Fast lane for short queries | Many small dashboard queries |
| Concurrency scaling | Burst extra clusters | Spiky read/write concurrency |
| Data sharing (multi-warehouse) | Separate compute for producers/consumers | Strong isolation, chargeback |
| Serverless workgroups | Per-team autoscaling compute | Many teams, unpredictable load |
| Elastic resize | Permanent size change | Sustained growth |

## K. Maintenance impact
- **Automatic VACUUM / sort / analyze / table optimization** run in the background at low load and yield to user queries.
- **Backups** (automated snapshots) run in the background; manual snapshots may slow I/O briefly.
- **Patching** during the maintenance window (and **current/trailing** track choice).
- **Resize** affects availability briefly (elastic) or longer (classic).

## Scenarios (if → then, because)
- **If** a dashboard's **1-second** queries wait behind a **20-minute** ETL job, **then** use **workload management (WLM)**: put ETL in its own queue with **LOW** priority, or use **automatic WLM** priorities (verify details) plus **short query acceleration (SQA)**, which runs predicted short queries in a dedicated fast lane (verify). **This works because** WLM queues split cluster memory and concurrency, so short dashboard queries are protected from long ETL instead of waiting for a free slot.
- **If** **100** analysts query at 9 am and queues build up, **then** turn on **concurrency scaling** for the BI queue (`Concurrency Scaling mode = auto`). **This works because** Redshift adds **temporary extra clusters** only while queries are waiting, and users still see current data. You get **1 free hour** of scaling per **24 hours** the main cluster runs; beyond that it is billed **per second**.
- **If** you want strict isolation between ETL and BI teams with separate bills, **then** use **data sharing** with its own consumer cluster or workgroup per team. **This works because** each consumer runs on **separate compute** reading the producer's live data, and each consumer pays for its own compute, which makes chargeback easy.
- **If** a runaway query keeps hurting performance, **then** add a **query monitoring rule (QMR)** to the queue that **aborts** a query when `query_execution_time` or the **nested loop join** row count passes a limit (verify exact metric list). **This works because** QMR checks running queries against limits and takes the action (log, hop, abort or change priority) automatically.
- **If** the query plan shows **`DS_DIST_BOTH`** on two huge tables, **then** set a **DISTKEY** on the join column for **both** tables. **This works because** `DS_DIST_BOTH` means both tables are redistributed over the network during the join; with matching keys, joined rows already sit on the same slice.
- **If** one **slice** (parallel worker) holds **10×** the rows of others, **then** change the **distribution key**, or use EVEN. **This works because** this is **data skew**: work is uneven, so the whole query waits for the overloaded slice. Check `skew_rows` in `SVV_TABLE_INFO`.
- **If** a query is **disk-based** (its intermediate results don't fit in memory and spill to disk), **then** give it more memory with **fewer WLM slots** or **more nodes**, or select fewer columns. **This works because** queue memory is split evenly across slots, so fewer slots means more memory per query.
- **If** a query suddenly slowed after a big load, **then** run **`ANALYZE`** and check the **unsorted %** (VACUUM if high). **This works because** stale statistics give the planner a bad plan, and many unsorted rows mean zone maps can skip fewer blocks.
- **If** the same expensive report runs every hour, **then** create a **materialized view (MV)** with **auto refresh**. **This works because** the MV stores the precomputed result, so each run reads it instead of recomputing the joins and aggregates.
- **If** a repeated identical query returns in milliseconds, **then** it was a **result cache** hit, which uses no compute. If the underlying data changed, the cache is invalidated and the query runs again (verify invalidation rules).
- **If** a query on a **temporary table** isn't going to the concurrency-scaling cluster, **then** that is **expected**: concurrency scaling does not support temporary tables, so the query stays on the main cluster.
- **If** a table has an **interleaved sort key** and concurrency scaling isn't helping its queries, **then** that is a **known limitation**: concurrency scaling does not support queries on tables with interleaved sort keys. Consider a compound sort key instead.
- **If** **Redshift Serverless** costs spike, **then** set a **max RPU** (Redshift Processing Unit) cap and **usage limits**, find long-running or runaway queries, and tune them. **This works because** Serverless bills for compute used, so capping capacity and fixing heavy queries directly limits the bill.
- **If** the **`CommitQueueLength`** metric is high, **then** batch many small writes into fewer transactions. **This works because** each commit waits in a queue, so many tiny autocommit statements pile up there.
- **If** manual WLM queues use all **50** total slots and queries spill to disk, **then** **reduce the slots** or switch to **automatic WLM**. **This works because** a queue's memory is split evenly across its slots, so many slots leave little memory per query; automatic WLM sizes memory to each query's needs.

## Verified from AWS docs on 2026-10-02
Read: query performance factors page, manual WLM page, concurrency scaling page, CloudWatch metrics page. Not confirmed (verify): automatic WLM details, SQA default state and mechanics, exact QMR metric list, which WLM changes need reboot, Redshift Advisor recommendation list, EXPLAIN label meanings (general knowledge), view names beyond those in the docs (SYS_QUERY_DETAIL etc.), result-cache invalidation rules.

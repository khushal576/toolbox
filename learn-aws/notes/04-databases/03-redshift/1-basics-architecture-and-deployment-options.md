# Redshift – 1. Data warehouse basics, architecture, node types, Serverless, and when to choose Redshift

Short notes. Each point is a fact you can be asked about. Written for someone new to data warehouses.

## A. The problem a data warehouse solves (read this first)
- Normal databases (RDS, Aurora, DynamoDB) are built for **OLTP**: many users, each touching **one or a few rows**, answers in milliseconds, latest values only.
- Business questions are **OLAP**: "total sales per category per month for 3 years". They scan **millions or billions of rows** but only **2–3 columns**, are run by few people, and may take seconds.
- Running OLAP on an OLTP database is **slow** (reads whole rows, one server) and **hurts customers** (reports slow down orders).
- A **data warehouse** is a separate database built for OLAP:
  1. Copy data from many sources into one place (**ETL/ELT**).
  2. Keep **history** (years).
  3. Load in **batches** (or streams), read mostly.
  4. Shape data for questions, not for transactions.
  5. BI tools (QuickSight, Tableau, Power BI) and analysts query it.
- **Amazon Redshift** is AWS's managed data warehouse. It uses **SQL** based on **PostgreSQL**, so most SQL tools work with small changes.
- Redshift can do OLTP-type statements (INSERT/UPDATE/DELETE) but is **optimized for large analytic scans**, not for thousands of tiny transactions.
- Typical flow: sources → ingest (S3 + COPY, streaming, zero-ETL) → Redshift tables → BI dashboards / ML / data sharing.

## B. Words to know
| Word | Meaning |
|---|---|
| OLTP / OLAP | Transactions / analytics |
| ETL / ELT | Transform before loading / load first, transform inside the warehouse with SQL |
| Fact table | Big table of events (sales, clicks) |
| Dimension table | Small descriptive table (product, customer, date) |
| Star schema | Fact table in the middle, dimensions around it |
| Columnar storage | Data stored column by column |
| MPP | Massively parallel processing: many workers share the query |
| Leader node | Plans the query and talks to clients |
| Compute node | Stores data and runs query steps |
| Slice | One parallel worker inside a compute node |
| Distribution style/key | How rows are spread across slices |
| Sort key | Order rows are stored in (lets Redshift skip blocks) |
| WLM | Workload management (query queues) |
| RPU | Redshift Processing Unit (Serverless compute unit) |
| Data lake | Cheap files in S3 in open formats |
| Lakehouse | Warehouse + lake used together |

## C. Why Redshift is fast (five ideas) (verified architecture)
1. **Columnar storage**: each column is stored separately. A query that needs `amount` and `date` reads only those columns, not the whole row.
2. **Compression**: values in one column are similar, so they compress well. Less data read from disk = faster. Redshift picks encodings automatically (see file 2).
3. **MPP**: data is split across many slices; each works on its part in parallel. Intermediate results go to the leader for final merge.
4. **Co-located data (distribution)**: if matching rows of two joined tables live on the same slice, the join needs no network movement.
5. **Block skipping (sort keys + zone maps)**: each block remembers min/max values. If data is sorted by date, a "last week" query skips most blocks.
- Extras: **result caching**, **compiled query code** (cached on cluster and in a remote cache), **materialized views**, **automatic table optimization**, **managed storage cache**.
- Redshift has **no traditional indexes**. Sort keys and zone maps replace them.
- It is **not** good at: highly selective single-row lookups at high QPS, many tiny writes, or tables updated row by row all day.

## D. Architecture (verified)
- **Cluster** = **leader node** + one or more **compute nodes**. With a single node, leader and compute share the same node (not for production).
- **Leader node**:
  - Receives queries from clients, parses them, makes the plan, compiles code, sends it to compute nodes, merges results.
  - Clients (JDBC/ODBC/Data API) talk **only to the leader**.
  - You are **not billed** for the leader node in multi-node clusters; you pay for compute nodes.
  - Some functions run **only on the leader**; a query using them against compute-node tables errors.
- **Compute nodes**: own CPU, memory and storage; run the compiled plan; exchange data among themselves over a private high-speed network.
- **Slices**: each compute node is split into slices (number depends on node size). Each slice gets part of memory/disk and processes part of the data. Rows are assigned to slices by the **distribution style**.
- **Redshift Managed Storage (RMS)**: data lives in S3-backed managed storage with local **SSD as a tier-1 cache**. Hot/cold block placement is automatic (block temperature, age, workload).
- **Databases**: a cluster can have several databases (max **60** per provisioned cluster; **100** per Serverless namespace; excluding datashare databases).
- With 2+ compute nodes, data on each node is **mirrored** on another node to reduce data-loss risk, and continuously backed up to S3.
- Based on PostgreSQL 8.x-era SQL with many differences (no real indexes, informational constraints, different types). Redshift is **not** PostgreSQL-compatible for everything.
- Cluster runs in a **VPC**; you attach **security groups** and a **cluster subnet group**.

## E. Node types for provisioned clusters (verified)
- **RA3** (current main family): compute and managed storage are **separate**. Pay for compute nodes + managed storage used.
  - Sizes: `ra3.large`, `ra3.xlplus`, `ra3.4xlarge`, `ra3.16xlarge`.
  - Managed storage per node: large 8 TB (multi-node; single-node 1 TB), xlplus 32 TB (single-node 4 TB), 4xlarge/16xlarge 128 TB.
  - Node ranges at create: large 2–16, xlplus 2–16 (elastic resize to 32), 4xlarge 2–32 (resize to 64), 16xlarge 2–128.
  - Single-node RA3 clusters exist (large, xlplus) but are not for production.
- **RG** (new, **Graviton-based**): same managed-storage model as RA3, better price-performance, and an **integrated data-lake query engine** on the cluster (RA3 uses Redshift Spectrum for data-lake queries). Sizes: `rg.large`, `rg.xlarge`, `rg.4xlarge`, `rg.12xlarge`. (Newer family; verify availability by Region.)
- **DC2** (dense compute, **legacy**): local NVMe SSD, storage tied to nodes. `dc2.large` (160 GB), `dc2.8xlarge` (2.56 TB). AWS says for data under about **1 TB compressed** DC2 is good value, but recommends **RA3/RG** if data will grow. Max 128 nodes.
- **DS2** (dense storage) and older families are **no longer available**.
- Exam shortcut: "scale compute and storage independently" → **RA3** (or RG). "Small, under 1 TB, cheapest" → DC2 (legacy) or Serverless.
- Choose node count from **daily data processed**, not total data size (with RA3/RG).
- AWS console has "Help me choose" sizing recommendation.
- Reserved nodes give big discounts for steady production use.

## F. Redshift Serverless (verified + notes)
- **No nodes to manage**. Capacity scales automatically; pay for compute used, billed **per second** (60-second minimum per charge), in **RPU-hours**. **No charge when idle** (it pauses automatically).
- **Namespace** = storage side: databases, schemas, tables, users, KMS key, datashares, recovery points, usage limits.
- **Workgroup** = compute side: RPUs, VPC subnets, security groups, network and usage limits.
- Each namespace links to **one** workgroup and vice versa. Quotas: **25** namespaces and **25** workgroups by default (adjustable).
- You set **base capacity** in RPUs (and optionally **max RPU** as a cost cap). Redshift scales within limits. Higher base = faster queries; scaling takes a short time. (Base range 4–512 RPUs; verify exact limits.)
- 1 RPU ≈ 16 GB memory (verify). Storage-limit tiers: **4 RPU workgroups up to 32 TB**; **8/16/24 RPU up to 128 TB** managed storage.
- Uses **recovery points** (automatic, retained about 24 hours) and **snapshots** (not "automated snapshots" like clusters).
- Same SQL engine and features: Spectrum/data lake, data sharing, zero-ETL, streaming ingestion, materialized views, Redshift ML, RLS/DDM.
- Serverless limits: query timeout **24 hours**; idle session **1 hour**; max **2,000** connections; **200,000** tables per namespace.
- Audit logs for Serverless go **only to CloudWatch** (not S3 log files).
- When to pick Serverless: **unpredictable or spiky** workloads, new projects, dev/test, intermittent BI, many small teams, no admin staff.
- When to pick provisioned: **steady 24×7** heavy workloads (reserved nodes cheaper), need fine WLM control, predictable cost.
- Serverless "price-performance target" lets Redshift AI-scale capacity (verify).

## G. Multi-AZ, resize and pause (provisioned)
- **Multi-AZ** is for **RG/RA3** clusters. Compute runs in **two AZs** behind **one endpoint**; if an AZ fails, the other continues. **Zero RPO**; SLA **99.99%** (vs 99.9% single-AZ). Same hourly price per node; storage shared across AZs.
- **Resize**:
  - **Elastic resize**: add/remove nodes (or change node type in some cases) in minutes; cluster is briefly unavailable (connections held); number of slices per node may change.
  - **Classic resize**: copies data to a new cluster; longer; read-only during resize; needed for some changes (for example single-node → multi-node).
  - During `prep-for-resize`/`resize-cleanup`, reads/writes work but cluster operations like snapshots are not available.
- **Pause and resume**: stops compute billing; you pay only for storage and backups. Good for dev/test.
- **Maintenance window**: weekly 30-minute window for patching; choose **current** or **trailing** track (verify).
- **Cluster status** values include available, resizing, paused, hardware-failure, storage-full, incompatible-parameters, rotating-keys.
- Default **disk space alarm** can be created with the cluster (CloudWatch + SNS).

## H. When to use / not use Redshift
- Use for **BI and reporting** on structured data, **large aggregations and joins**, **history-heavy analytics**, **ELT with SQL**, **sharing live data** between teams, **combining warehouse with S3 lake** (Spectrum), **ML with SQL** (Redshift ML).
- Do not use for: OLTP, key-value lookups, low-latency single-row APIs, unstructured blobs, text search, graph traversal.
- Do not use for ad-hoc, rare queries on files in S3 with no warehouse need → **Athena**.
- Do not use for heavy custom code (Spark, ML pipelines) → **EMR/Glue**.

## I. Redshift vs neighbors (decision lines)
| Need | Pick |
|---|---|
| Enterprise warehouse, fast repeated SQL, many users, BI | **Redshift** |
| Ad-hoc SQL on S3, pay per TB scanned, no cluster | **Athena** |
| Big-data processing with Spark/Hive/Presto, custom code | **EMR** (or Glue) |
| Operational/transactional SQL | **RDS / Aurora** |
| Real-time key-value at scale | **DynamoDB** |
| Search and log analytics | **OpenSearch** |
| Open table format lakehouse (Iceberg) | **S3 Tables / Iceberg**, queried by Athena, Redshift, EMR |
| Simple dashboards from a few million rows | **Aurora/RDS + QuickSight** may be enough |
- **Redshift vs Athena** (very common question):
  - Redshift: loaded, optimized local tables, consistent speed, high concurrency, joins, materialized views, you pay for compute (provisioned/RPU).
  - Athena: serverless, query S3 directly, pay per TB scanned, good for ad-hoc and lake exploration; less predictable performance.
  - Redshift **Spectrum** lets Redshift query S3 too; use it to join warehouse tables with lake data.
- **Redshift vs EMR**: Redshift = SQL warehouse (managed, simple). EMR = flexible open-source frameworks (Spark etc.), more admin.
- **Redshift vs Aurora**: Aurora is OLTP (row-based); Redshift is columnar OLAP. **Zero-ETL** copies Aurora data into Redshift for analytics.

## J. Related features at a glance
- **Data sharing**: share live data between clusters/workgroups/accounts/Regions without copying (file 3).
- **Spectrum / data lake queries**: query S3 without loading (file 3).
- **Federated queries**: query RDS/Aurora PostgreSQL/MySQL live (file 3).
- **Zero-ETL**: automatic replication from Aurora/RDS/DynamoDB/apps (file 3).
- **Streaming ingestion**: Kinesis Data Streams and MSK straight into a materialized view (file 3).
- **Redshift ML**: create/train models with SQL (SageMaker behind the scenes).
- **Query Editor v2**: web SQL editor, charts, saved queries, scheduled queries.
- **Data API**: HTTP-based SQL calls, no drivers/connections (file 3).
- **Python UDFs are being retired**: Redshift will **no longer support Python UDFs after 30 June 2026** (phased enforcement). Use SQL UDFs or **Lambda UDFs** instead.

## Scenarios (if → then, because)
- If analysts' reports slow down the shop database → move analytics to Redshift, because OLAP and OLTP need different designs.
- If you need compute and storage to scale separately → RA3/RG (or Serverless), because managed storage is decoupled.
- If workload is spiky or unpredictable → Serverless, because you pay per RPU-second and it pauses when idle.
- If workload is steady and heavy 24×7 → provisioned with reserved nodes, because it is cheaper at constant load.
- If data is under 1 TB and static → Serverless or a small cluster; DC2 is legacy.
- If you need ad-hoc queries on S3 with no cluster → Athena.
- If you want one SQL query joining warehouse tables and S3 files → Redshift Spectrum.
- If you want an AZ-failure-proof warehouse → Multi-AZ (RG/RA3).
- If you need to stop paying for a test cluster overnight → pause it (storage only is billed).
- If a query uses a function that only runs on the leader against a compute table → it errors; rewrite with supported functions.
- If you need row-by-row API reads at high QPS → not Redshift; use DynamoDB or Aurora.

## Verified from AWS docs on 2026-10-02
Read: clusters and nodes page (node types, ranges, pause/resume, status), architecture page, Serverless namespaces/workgroups page, quotas page, Multi-AZ page, pricing summary. Not confirmed (verify): Serverless base RPU range and RPU memory, price-performance target details, RG availability by Region, maintenance track names, classic vs elastic resize exact behavior, "1 RPU = 16 GB".

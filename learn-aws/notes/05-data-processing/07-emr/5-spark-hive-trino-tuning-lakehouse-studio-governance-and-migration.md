# Amazon EMR – 5. Engine tuning cookbook, lakehouse formats, EMR Studio, Ranger/Lake Formation and Hadoop migration

Short notes. Each point is a fact you can be asked about.

## A. Spark tuning cookbook (EMR runtime for Spark)
- **EMR runtime for Spark** is a performance-optimized, API-compatible Spark build. It adds (default on from EMR 5.26.0 unless noted): **adaptive query execution (AQE)**, **dynamic partition pruning**, **flattening scalar subqueries**, **DISTINCT before INTERSECT**, **Bloom filter join**, **optimized join reorder**, and the **EMRFS S3-optimized committer**.
- **AQE** (on by default): re-plans using runtime stats.
  - **Adaptive join conversion**: converts sort-merge join to **broadcast-hash join** when one side's runtime size is below `spark.sql.autoBroadcastJoinThreshold` (**default 10 MiB**).
  - **Adaptive coalescing of shuffle partitions**: merges small shuffle partitions to a target. Properties: `spark.sql.adaptive.coalescePartitions.enabled` (true unless `spark.sql.shuffle.partitions` is explicitly set), `advisoryPartitionSizeInBytes` (**64 MB**), `coalescePartitions.minPartitionNum` (**25**), `coalescePartitions.initialPartitionNum` (**1000**).
  - Disabling `spark.sql.adaptive.enabled` disables all AQE features.
  - **Setting `spark.sql.shuffle.partitions` yourself turns off auto-coalescing** (a common trap).
  - AQE also handles **skew joins** (`spark.sql.adaptive.skewJoin.enabled`).
- **Dynamic partition pruning** (`spark.sql.dynamicPartitionPruning.enabled`, default true): reads only partitions matched by a join with a filtered dimension table. Needs partitioned fact tables and a broadcastable filtered side.
- **Bloom filter join** (`spark.sql.bloomFilterJoin.enabled`): pre-filters the big side with a Bloom filter built from the small side.
- **Optimized join reorder** (`spark.sql.optimizer.sizeBasedJoinReorder.enabled`): joins small filtered tables first.
- **Sizing executors**: aim for **4–5 cores per executor** (HDFS/S3 client throughput saturates beyond ~5), leave **1 core + 1 GB for OS/YARN per node**, set `spark.executor.memory` and `spark.executor.memoryOverhead` (default overhead 10% of executor memory, min 384 MB; raise for PySpark/off-heap/Parquet-heavy jobs).
- **`maximizeResourceAllocation`** (classification `spark`): EMR sets executor sizes to use the whole node (one big executor per node); simple but can cause GC issues and wastes capacity on mixed workloads.
- **Dynamic allocation** is on by default on EMR (`spark.dynamicAllocation.enabled=true`); with **managed scaling** it adds/removes nodes while Spark adds/removes executors. Set `spark.dynamicAllocation.maxExecutors` to cap runaway jobs.
- **Shuffle**: use **Kryo** serialization (`spark.serializer=org.apache.spark.serializer.KryoSerializer`), keep shuffle partitions about **100–200 MB**, avoid skewed keys (salting or AQE skew join), increase `spark.sql.shuffle.partitions` for huge shuffles when AQE is off.
- **Memory**: watch GC (use G1GC, `-XX:+UseG1GC`), avoid collecting huge results to the driver, increase `spark.driver.memory` for big broadcasts/`collect()`.
- **File layout**: target **128 MB–1 GB columnar files (Parquet/ORC)**; compact small files (`coalesce`/`repartition` before write, Iceberg `rewrite_data_files`, `S3DistCp --groupBy`).
- **Partitioning**: partition by low-cardinality columns used in filters (date); avoid over-partitioning (millions of tiny partitions slow listing and the metastore).
- **Predicate and column pushdown** work on Parquet/ORC; select only needed columns; avoid UDFs in filters (kills pushdown); prefer built-in functions or pandas UDFs.
- **Caching**: `cache()` only reused DataFrames, choose `MEMORY_AND_DISK`; unpersist when done.
- **Broadcast hints** (`broadcast(df)`) for small dimension tables beyond 10 MiB when memory allows.
- **S3 reads**: use **EMRFS** with `s3://`, enable **consistent view not needed** (S3 is strongly consistent), tune `fs.s3.maxConnections`, use S3 request-rate-friendly prefixes.
- **Output committers**: the **EMRFS S3-optimized committer** (default for Parquet writes via Spark SQL/DataFrames on EMR 5.19+; for other formats configure `spark.sql.parquet.fs.optimized.committer.optimization-enabled=true` **(verify)**) avoids rename and gives **job-level atomic commit**; for append with multipart uploads it speeds writes. **Do not use rename-based committers on S3** (slow, not atomic).
- **Glue Data Catalog as metastore**: set classification `spark-hive-site` `hive.metastore.client.factory.class=com.amazonaws.glue.catalog.metastore.AWSGlueDataCatalogHiveClientFactory`; enables sharing tables with Athena/Glue/Redshift Spectrum.
- **Monitoring**: Spark History Server, YARN ResourceManager, Ganglia/CloudWatch, **EMR Studio debug tools**, `spark.eventLog` to S3 for persistent history (Persistent UI).
- **Debug checklist**: long tail tasks → skew; OOM executors → memory/overhead/partition size; slow stage with many tasks → small files/over-partitioning; slow scan → no pruning/pushdown; shuffle spill → memory/partitions; driver OOM → collect/broadcast.

## B. Hive and Tez on EMR
- **Hive on Tez** is the default engine for Hive on EMR (MapReduce is legacy). Use **ORC or Parquet**, partitioning, bucketing, vectorization (`hive.vectorized.execution.enabled=true`), cost-based optimizer (`hive.cbo.enable=true`) with table/column stats (`ANALYZE TABLE … COMPUTE STATISTICS`).
- **Metastore options**: **AWS Glue Data Catalog** (recommended, serverless), **external RDS/Aurora MySQL** metastore, or the master-local MySQL (lost with the cluster; avoid for persistent data).
- **Hive LLAP** is not supported on EMR; use **Trino/Presto or Spark SQL** for interactive.
- **S3 + Hive**: `MSCK REPAIR TABLE` to discover partitions (or Glue crawlers/partition projection in Athena); avoid thousands of partition-add DDLs.
- **Hive ACID** tables on EMR require Hive 3.x (EMR 6+) and Tez; prefer **Iceberg** for ACID on S3.

## C. Trino and Presto on EMR
- **Trino** (EMR 6.1+ lineage, also Presto) is an in-memory distributed SQL engine for interactive and federated queries; catalogs configured via classifications (`trino-connector-hive`, `trino-connector-iceberg`, `trino-connector-delta` **(verify)**).
- **Coordinator on the primary node**, workers on core/task nodes; scale with managed scaling or custom policies.
- Strengths: ad-hoc low-latency queries, **federation** across Hive/Iceberg/JDBC/Redshift; weakness: no mid-query fault tolerance by default (fault-tolerant execution optional **(verify)**), memory-bound.
- **Tuning**: `query.max-memory`, `query.max-memory-per-node`, join distribution (`broadcast` vs `partitioned`), spill to disk, ORC/Parquet with stats, partition pruning, `task.concurrency`.
- **Compare with Athena**: Athena is serverless Trino; EMR Trino gives control over instances, configs, connectors and cost at steady heavy usage.

## D. Lakehouse table formats on EMR
- **Apache Iceberg**: open table format with **ACID, snapshot isolation, schema/partition evolution, time travel, hidden partitioning**. Available from **EMR 6.5.0** with Spark 3; EMR 7.14.0 ships **Iceberg 1.10.1-amzn-1**; EMR 6.15.0 ships **1.4.0-amzn-0** (verify later releases). Works with Spark, Hive, Trino, Flink.
  - **Catalog**: use the **Glue Data Catalog** (`org.apache.iceberg.aws.glue.GlueCatalog`), warehouse on S3; **Lake Formation** can govern tables.
  - Spark config (classification `spark-defaults`): `spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions`, `spark.sql.catalog.<name>=org.apache.iceberg.spark.SparkCatalog`, `…catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog`, `…warehouse=s3://bucket/path`, `…io-impl=org.apache.iceberg.aws.s3.S3FileIO`.
  - **Maintenance procedures**: `expire_snapshots`, `remove_orphan_files`, `rewrite_data_files` (compaction), `rewrite_manifests`; schedule them (Glue/EMR/MWAA) or use **Glue Data Catalog automatic table optimization** (compaction, snapshot expiry) instead.
  - **S3 Tables** (managed Iceberg tables) can be queried from EMR via the S3 Tables catalog client **(verify)**.
  - **Row-level operations**: `MERGE INTO`, `UPDATE`, `DELETE` with copy-on-write or merge-on-read.
- **Apache Hudi**: record-level upserts/deletes and incremental pulls; **COW** vs **MOR** table types; strong for CDC ingest (DeltaStreamer); supported on EMR with Spark/Hive/Presto; sync to Glue catalog.
- **Delta Lake**: open-source Delta tables supported on EMR (bring the jars/config or EMR-provided releases) **(verify)**; Athena/Redshift read Delta via manifests/native support.
- **Choosing**: **Iceberg** = broadest engine support (Athena, Redshift, Glue, EMR, Snowflake), best default; **Hudi** = heavy upsert/CDC with incremental consumption; **Delta** = Databricks-centric ecosystems.
- **Concurrency**: optimistic concurrency; conflicts retry; use catalog locks (Glue/DynamoDB) as configured.
- **Do not write non-transactional Parquet in place** on tables that are also managed by Iceberg metadata.

## E. EMR Studio
- **EMR Studio** is a web-based IDE with **managed Jupyter notebooks** (PySpark, Spark Scala, SparkSQL, Python, R) that attach to **EMR on EC2 clusters**, **EMR on EKS virtual clusters** and **EMR Serverless applications**.
- **Cost**: creating a Studio is **free**; you pay for S3 storage of notebooks and the compute clusters you use.
- **Authentication**: **IAM** or **IAM Identity Center** (optionally with **trusted identity propagation**, which passes the user's identity to Lake Formation/S3 Access Grants for per-user data access).
- **Workspaces** hold notebooks (saved to S3); **real-time collaboration** in the same Workspace; **Git repositories** (GitHub, Bitbucket, CodeCommit) linkable.
- **SQL Explorer**: browse the Glue catalog and run SQL, download results.
- **Debugging**: Spark History Server, Tez UI, YARN timeline server from the Studio.
- **Parameterized/headless notebooks** can run from **Airflow/MWAA** or Step Functions for scheduling.
- **Setup requirements**: a **service role** (EMR Studio service role, access to S3 and cluster management), a **user role/session policy** per user or group (what clusters and templates they may use), **VPC and subnets** (private subnets recommended; endpoints for S3, EMR, STS), **S3 bucket** for workspace storage (with optional KMS), **cluster templates** (Service Catalog) so users can create clusters safely.
- **Network**: Studio ENIs in your subnets; security group rules for Workspace ↔ cluster (Livy/port 8998 ↔ cluster master; Studio engine SG).
- **Compliance**: HIPAA eligible, HITRUST CSF, SOC 2, FedRAMP **(per docs)**.
- **SageMaker Unified Studio** can also use EMR on EC2 and EMR Serverless connections (Spark, Trino, Flink) for notebook work in a governed project.
- **Studio vs EMR Notebooks** (legacy): EMR Notebooks are cluster-attached older feature; EMR Studio is recommended.

## F. Fine-grained access: Lake Formation and Apache Ranger on EMR
- **Lake Formation + EMR**: enforce **table/column/row/cell** permissions for Spark, Hive, Trino/Presto on EMR:
  - **EMR on EC2** with Lake Formation: configure a **runtime role per job/step** (EMR 6.15+ / 7.x supports runtime roles with LF) and a **Lake Formation security configuration**; the EC2 instance profile role is less privileged for data.
  - **EMR Serverless / EMR on EKS** with LF integration use job runtime roles and a system-driver architecture to isolate user code from the filtering layer **(verify details)**.
  - Requires data locations **registered** with Lake Formation and **IAM_ALLOWED_PRINCIPALS** removed on governed databases.
  - **Trusted identity propagation** with Identity Center users for per-user authorization and audit **(verify engines)**.
- **Apache Ranger on EMR (EMR on EC2)**: **native integration with Apache Ranger** (EMR 5.32/6.3+): external Ranger Admin Server + plugins on the cluster (Spark SQL, Hive, EMRFS/S3, Trino) enforcing **policy-based authorization** and **audit to Solr/CloudWatch**; Ranger policies for databases/tables/columns, S3 prefixes (EMRFS authorization), and row filtering/column masking (Hive/Spark plugin).
  - Requires **Kerberos**-secured cluster (security configuration) and an AD/LDAP user source (often via **SSSD** or EMR **Active Directory** integration), a Ranger admin server (EC2) with its own DB and Solr (or OpenSearch for audit), TLS certificates, secrets in Secrets Manager.
  - Heavier to operate than Lake Formation; used by teams migrating from on-prem Hadoop with existing Ranger policies.
- **Choosing**: **Lake Formation** = AWS-native, central across Athena/Redshift/EMR/Glue (recommended for new lakes); **Ranger** = existing Hadoop-style policies, HBase/Hive-on-HDFS controls, cluster-local enforcement.
- **Also**: **EMRFS role mapping** (map users/groups to IAM roles for S3 prefix access), **Kerberos** for authentication, **S3 Access Grants**.
- **Audit**: Lake Formation → CloudTrail; Ranger → Solr/OpenSearch/CloudWatch; EMR API → CloudTrail.

## G. Migrating from on-premises Hadoop to EMR
- **Principles**: decouple **storage (S3)** from **compute (EMR)**, use **transient clusters** per workload, replace HDFS-as-lake with S3, and move the **metastore** to Glue.
- **Data**: HDFS → **S3** using **S3DistCp** (over DX/VPN), **DistCp** with S3A, **AWS DataSync** (agent reads HDFS), **Snow Family** for tens of PB, **Storage Gateway/file gateway** for incremental. Validate with checksums/row counts.
- **Metadata**: Hive Metastore → **Glue Data Catalog** (use the Glue Hive metastore migration utility / export-import) or keep an external RDS metastore for compatibility.
- **Processing**: Spark/Hive/Presto jobs mostly run unchanged; replace HDFS paths with `s3://`; recompile for supported versions; replace MapReduce with Spark/Tez.
- **Workflow**: **Oozie** → **MWAA/Airflow** or **Step Functions**; **Azkaban/Luigi** → MWAA; cron → EventBridge Scheduler.
- **HBase**: use **HBase on S3** (root dir on S3, storefile tracking) with EMR, or DynamoDB/Keyspaces if re-architecting.
- **Security**: Kerberos + Ranger → EMR Kerberos/Ranger or **Lake Formation + IAM**; encryption with KMS; network via VPC endpoints.
- **Operations**: Cloudera Manager/Ambari → EMR console/CloudWatch/Ganglia/Prometheus; configuration through **EMR configuration classifications** and bootstrap actions.
- **Sizing**: start with **instance fleets/groups** matching memory/cores per executor needs; use **Graviton (e.g., m6g/r6g)** where supported; use **Spot for task nodes**; benchmark and tune.
- **Cutover strategy**: dual-run, compare outputs, migrate by workload/domain, then decommission HDFS. **Incremental sync** until cutover.
- **Cost model shift**: from fixed cluster capex to pay-per-use; avoid leaving always-on large clusters (use auto-termination, EMR Serverless for spiky jobs).
- **Pitfalls**: HDFS small-file patterns on S3, rename-heavy jobs (use committers), reliance on HDFS locality, hard-coded namenode URIs, tools unsupported on EMR (check release components), long-lived cluster state, missing Kerberos/Ranger parity.
- **Reference path**: Assess (Application Discovery, TCO) → Plan (landing zone, network, security) → Migrate data → Migrate workloads → Optimize.

## H. Exam skills mapping
- **1.2.x** transformation engine choices and tuning; **2.x** table formats and catalog; **3.x** performance and troubleshooting; **4.x** Lake Formation/Ranger/Kerberos on EMR; migration scenarios (Hadoop → EMR).

## I. Scenarios: "If X → Y, because Z"
- **If** a Spark join with a small dimension table is slow, **then** raise `spark.sql.autoBroadcastJoinThreshold` (default **10 MiB**), add a **broadcast hint** (`broadcast(df)`), or rely on **adaptive query execution (AQE)** to switch the join at runtime. **This works because** a **broadcast join** sends the small table to every executor, so the large table does not need to be shuffled across the network. Only do this when the small table fits in memory.
- **If** a few tasks run far longer than the rest, **then** use **AQE skew-join** handling, **salting** (add a random part to hot keys), or repartition on a better key. **This works because** skewed keys put too much data on a few tasks, which become stragglers.
- **If** your job writes thousands of tiny output files, **then** use `coalesce`/`repartition` before writing, or run **Iceberg compaction** (`rewrite_data_files`). **This works because** small files slow reads and S3 listing; aim for **128 MB–1 GB** files.
- **If** AQE's automatic coalescing of shuffle partitions seems to be ignored, **then** remove your explicit `spark.sql.shuffle.partitions` setting. **This works because** setting it yourself turns off auto-coalescing, a common trap.
- **If** writes to S3 are slow and not atomic, **then** use the **EMRFS S3-optimized committer** (default for Parquet writes from Spark SQL/DataFrames on EMR 5.19+; other formats **(verify)**). **This works because** it skips the slow **rename** step and gives a **job-level atomic commit**. Do not use rename-based committers on S3.
- **If** you need **ACID** upserts and **time travel** on S3, **then** use **Apache Iceberg** with the **AWS Glue Data Catalog** as its catalog. **This works because** Iceberg keeps **snapshots** (for time travel) and supports row-level `MERGE INTO`, `UPDATE` and `DELETE`, and the Glue catalog shares the tables with Athena and Redshift.
- **If** **change data capture (CDC)** streams must be applied as incremental upserts, **then** use **Apache Hudi** with **merge-on-read (MOR)** tables, or Iceberg `MERGE INTO`. **This works because** both support record-level updates; Hudi is strong for heavy upsert/CDC ingest with incremental pulls.
- **If** analysts want notebooks on shared clusters with **single sign-on (SSO)**, **then** use **EMR Studio** with **IAM Identity Center** and **cluster templates** (from **AWS Service Catalog**). **This works because** Studio supports Identity Center sign-in, and templates let users launch only pre-approved, secure clusters. Creating a Studio is free; you pay for S3 and compute.
- **If** different users need to see different columns or rows on EMR, **then** use **AWS Lake Formation** with **runtime roles**, or **Apache Ranger** with **Kerberos**. **This works because** both enforce fine-grained policies (table, column, row). Lake Formation is AWS-native and central across Athena, Redshift, EMR and Glue; Ranger needs its own admin server and is heavier to run.
- **If** you must keep an existing on-premises Ranger policy set, **then** use **EMR's native Apache Ranger integration** (EMR on EC2). **This works because** Ranger plugins on the cluster enforce the same policies from an external Ranger Admin Server. It needs a **Kerberos**-secured cluster and an AD/LDAP user source.
- **If** you migrate petabytes of HDFS data with limited network bandwidth, **then** ship it with the **AWS Snow Family** devices (where available **(verify)**) and sync later changes with **AWS DataSync**. **This works because** shipping devices is faster than sending tens of petabytes over the WAN, and incremental sync keeps S3 current until cutover.
- **If** you migrate **Apache Oozie** workflows, **then** move them to **Amazon Managed Workflows for Apache Airflow (MWAA)** or **AWS Step Functions**. **This works because** both schedule and chain jobs without depending on a Hadoop cluster.

Verified from AWS docs on 2026-11-09 (EMR Spark performance optimizations, EMR Iceberg page, EMR Studio page).
Unconfirmed (verify): EMR-specific committer enablement for non-Parquet; Lake Formation runtime-role support per release and engine; Trino catalog classification names and fault-tolerant execution; Delta Lake packaging; S3 Tables catalog on EMR; Ranger version/prerequisites; Hudi/Delta supported versions; trusted identity propagation engine support.

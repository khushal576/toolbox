# Amazon EMR – 2. EMR on EC2: instance groups and fleets, scaling, high availability and performance

Short notes. Each point is a fact you can be asked about.

## A. Instance groups vs instance fleets
- **Uniform instance groups**: each node type (primary, core, task) is one **group of one instance type and one purchasing option** (On-Demand **or** Spot). You can have **multiple task groups**.
  - Simple and predictable. Supports **custom auto scaling policies** (CloudWatch-based) and **managed scaling**.
- **Instance fleets**: each node type is a **fleet** with **up to 5 instance types** (per fleet, via specifying `InstanceTypeConfigs`) and **target capacity in units** for **On-Demand and Spot**; EMR picks the cheapest/available mix.
  - Better **Spot availability**: if one type is unavailable, EMR tries others. Supports **multiple subnets/AZs for the launch** (but the cluster ends up in **one AZ**).
  - Options: **allocation strategy** (**price-capacity-optimized** recommended for Spot, **capacity-optimized**, **lowest-price**; On-Demand **lowest-price** or **prioritized**), **provisioning timeout** (`TimeOutDurationMinutes`, then `TERMINATE_CLUSTER` or `SWITCH_TO_ON_DEMAND`), **block duration** (older), **weighted capacity** (units per instance type).
  - **Custom auto scaling policies are not supported with fleets**; use **managed scaling**.
- **Choose**: fleets for **Spot-heavy, resilient** clusters and diverse instance types; groups for simple, fixed, or custom-scaling setups.
- **Mixing**: primary and core on **On-Demand** (reliability); **task on Spot** (cost); a common ratio is 10–20% On-Demand, 80–90% Spot for fault-tolerant Spark.
- **Instance type guidance (rules of thumb)**: **m5/m6g** general Spark; **r5/r6g/r6i** memory-heavy (shuffle, joins); **c5/c6g** CPU-bound; **i3/i4i** local NVMe for HDFS/shuffle-heavy; **Graviton (arm64: m6g, r6g, c6g, m7g...)** for **better price-performance** (needs arm-compatible libraries).
- **EBS**: choose volume type/size for HDFS and spills; **gp3** default; EBS-only instances need EBS (m5/c5 have no instance store).

## B. Spot Instances on EMR
- **Spot** can be **up to ~90% cheaper** than On-Demand but can be **interrupted with a 2-minute warning**.
- **Safe usage**: run **task nodes** on Spot; keep **core and primary** on On-Demand; keep **durable data in S3**; make jobs **retryable**; use **Spark dynamic allocation + speculative execution**; use **instance fleets** with multiple types.
- **Why not core on Spot**: HDFS blocks lost on interruption; replication pressure; data loss risk.
- **Decommissioning**: EMR gracefully decommissions nodes (YARN graceful decommission); Spark can **migrate shuffle blocks** on decommission (`spark.decommission.enabled`, `spark.storage.decommission.*`) in newer releases.
- **Capacity**: Spot capacity varies by AZ and type; flexible types + **price-capacity-optimized** reduce interruptions.
- **Interruption handling**: EMR replaces lost task nodes automatically (managed scaling/fleet target capacity).

## C. Scaling: three mechanisms (very testable)
- **Manual resize**: change instance counts for core/task groups or fleet targets (task can reach 0; **core cannot drop below `dfs.replication`**).
- **Custom automatic scaling (instance groups only)**: **CloudWatch metric rules** (for example `YARNMemoryAvailablePercentage`, `ContainerPendingRatio`, `AppsPending`) with **scale-out/in rules**, cooldowns, min/max. Needs the **EMR_AutoScaling_DefaultRole**. Older approach.
- **EMR managed scaling** (recommended, releases **5.30.0+** except 6.0.0; **latest release recommended**, 7.14.0 in docs): EMR **continuously evaluates metrics** and scales **core and task** nodes to optimize cost and speed. Works for **instance groups and fleets**.
  - **Parameters**: `MinimumCapacityUnits`, `MaximumCapacityUnits`, optional **`MaximumOnDemandCapacityUnits`** (cap On-Demand; the rest becomes Spot), optional **`MaximumCoreCapacityUnits`** (cap core; the rest becomes task). **Units** = instances or **vCPUs** (instance groups) or **fleet units** (fleets). **Limits apply to core and task only; the primary cannot be scaled.**
  - **Only YARN applications** (Spark, Hadoop, Hive, Flink). **Not Presto, not HBase** (non-YARN).
  - **Shuffle-data aware** scale-in (release **5.34.0+/6.4.0+**): does not remove nodes with actively used Spark shuffle data. **Application-master aware** scale-in: protects nodes running the AM.
  - **Node labels** (7.2.0+): by **market type (`ON_DEMAND`/`SPOT`)** or **node type (`CORE`/`TASK`)** so the Spark driver/AM stays off Spot. Only those built-in labels; set at cluster creation; custom labels unsupported.
  - **Keep Spark dynamic resource allocation (DRA) enabled** (`spark.dynamicAllocation.enabled=true`); disabling can cause over-scaling to the maximum.
  - **Needs CloudWatch metrics to flow**: alarm on missing metrics.
  - **Network requirement**: the metrics collector must reach the **managed scaling public API endpoint (API Gateway)**; an **API Gateway interface VPC endpoint with private DNS breaks it** (remove it/disable private DNS or use a private subnet).
  - If you remove the default outbound rule on the primary security group, allow **TCP 9443** to the service-access security group.
  - **Decommission tuning**: reduce `spark.blacklist.decommissioning.timeout` (1 h → 1 min) and raise `yarn.resourcemanager.nodemanager-graceful-decommission-timeout-secs` (default 60 min) so long tasks finish.
  - Keep **EBS utilization below 90%**.
- **Scaling choice**: managed scaling for most; custom policies only for **instance-group** clusters needing metric-specific rules; manual for fixed workloads.

## D. High availability and resilience
- **Multiple primary nodes (3)**: for **instance groups on 5.23.0+**, for **instance fleets on 5.36.1/5.36.2/6.8.1/6.9.1/6.10.1/6.11.1/6.12.0+**. **Primary nodes must be On-Demand**; all three use the **same instance type**.
- **Quorum**: **2 of 3 primary nodes must be healthy**; if two fail, the **cluster fails**. EMR replaces a failed primary automatically (needs spare IPs in the subnet; **dedicate a subnet** to the cluster).
- **Single-AZ clusters**: **all EMR clusters, including HA, run in one AZ** and **cannot tolerate an AZ outage**. For AZ resilience: **keep data in S3** and **recreate the cluster in another AZ/Region** (infrastructure as code).
- **HDFS**: use **at least 4 core nodes** for production; with ≤3 core nodes set **`dfs.replication ≥ 2`**; EMR **will not scale core below `dfs.replication`**. In 6.x+ all three primary nodes run **NameNode** (in HA).
- **HA monitoring metrics**: `MultiMasterInstanceGroupNodesRunning`, `...RunningPercentage` (**<100% and >50%** = one primary lost, being replaced; **<50%** = quorum lost, unrecoverable → migrate data), `...Requested`.
- **Supported HA applications** are limited (Hadoop/YARN, HDFS, Hive, Spark, Zookeeper, etc.); EMR does not guarantee HA for other apps **(check the list)**.
- **Termination protection**: prevents accidental termination (and some failures); disable to let `--auto-terminate` end clusters; **`KeepJobFlowAliveWhenNoSteps`** controls persistence.
- **Idle auto-termination**: cluster-level **auto-termination policy** (idle for N seconds; min 60 s, max 7 days **(verify)**) to avoid forgotten clusters.
- **Backup/DR**: data in **S3 (versioning, replication)**, configs in **IaC**, metastore in **Glue/RDS**, **HBase on S3** option (root dir in S3, read replicas).

## E. Getting data in and out
- **S3 as the system of record**: `spark.read.parquet("s3://...")`; **EMRFS** options: **S3 SSE/CSE encryption**, **role mapping for EMRFS authorization** (map principals/prefixes to IAM roles), **S3 access grants**.
- **S3DistCp** (`s3-dist-cp`): distributed copy **S3 ↔ HDFS** with **grouping small files** (`--groupBy`), **compression**, **filters**; run as a step.
- **DistCp** for HDFS↔HDFS/S3A; **Sqoop** for relational DB import/export (JDBC) **(verify availability in recent releases)**; Spark **JDBC** reads with partitioning; **Kinesis/Kafka connectors** for streaming sources; **DynamoDB connector** (Hive); **Redshift connector** (spark-redshift community/EMR integration).
- **Glue Data Catalog** tables/partitions; **partition projection** is Athena-specific.
- **Output**: **Parquet/ORC** partitioned by date; coalesce/repartition to control file counts; **compaction** jobs for small files.
- **Data movement cost**: S3 → EMR in the **same Region is free**; cross-AZ to nodes small cost; cross-Region/Internet egress charged. Use **VPC gateway endpoint for S3** (free) to avoid NAT charges.

## F. Performance tuning (Spark on EMR)
- **Right-size executors**: typical **4–5 cores per executor**, **leave 1 core and ~1 GB for OS/YARN per node**, `spark.executor.memory` + `spark.executor.memoryOverhead` ≤ container limit (`yarn.nodemanager.resource.memory-mb`). Set **`maximizeResourceAllocation`** (EMR classification) for a quick start on dedicated clusters.
- **Dynamic allocation** on; set `spark.dynamicAllocation.minExecutors/maxExecutors`.
- **Shuffle**: tune `spark.sql.shuffle.partitions` (default 200) to data size (aim ~100–200 MB per partition); use **AQE** (adaptive query execution, default on in Spark 3.x) for coalescing and skew-join handling.
- **Serialization**: **Kryo**; **broadcast joins** for small tables (`spark.sql.autoBroadcastJoinThreshold`); **salting** for skew.
- **File layout**: Parquet, partition pruning, **predicate pushdown**, avoid tiny files; **bucketing/Z-order (Iceberg/Delta)**.
- **I/O**: S3 request rate (spread prefixes, use **EMRFS S3-optimized committer**), **`fs.s3.maxConnections`**, **multipart upload** thresholds.
- **Memory pressure/spills**: choose **r-family** instances; **local NVMe (i3/i4i)** for spills.
- **Graviton** and **EMR runtime for Spark** (AWS-optimized runtime, faster than open source, free): use the latest release; **EMR-optimized Spark** often shows 2–5x speedup claims **(AWS claim; verify)**.
- **Caching**: `df.cache()` only when reused; avoid over-caching on Spot nodes.
- **GC**: G1GC defaults fine; reduce object churn with DataFrames/Dataset encoders.
- **Monitoring**: Spark History Server, YARN UI, CloudWatch (`YARNMemoryAvailablePercentage`, `ContainerPending`, `HDFSUtilization`), Ganglia/Prometheus in newer setups.

## G. Customization and operations
- **Custom AMI** to reduce bootstrap time; **bootstrap actions** for libs; **Docker on YARN** (container runtime) for dependencies; **Conda/virtualenv** for PySpark libs (`--archives` with venv-pack).
- **Reconfiguration** of running instance-group clusters (`ModifyInstanceGroups` with `Configurations`); fleets require **new cluster** for some changes **(verify)**.
- **Patching**: default Amazon Linux AMI **does not auto-install reboot-requiring kernel updates**; **rebuild with a newer custom AMI** or reboot/bootstrap on schedule. Plan **cluster rotation** for long-running clusters.
- **EMR release upgrades** = new cluster with new label; test Spark/Hive behavior changes.
- **Tags** on clusters (propagate to EC2) for cost allocation and IAM conditions.
- **Service quotas**: EC2 instance limits per type, EMR clusters per Region, API rates; Spot limits; check before large launches.

## H. Troubleshooting (symptom → cause → fix)
- **Cluster stuck `STARTING`/fails with `INSUFFICIENT_INSTANCE_CAPACITY`** → no capacity in the chosen AZ/type → use **fleets with several types/subnets**, other AZ, On-Demand fallback (`SWITCH_TO_ON_DEMAND`).
- **`VALIDATION_ERROR` / instance type not supported** → type not in AZ/release → choose another type; add `ec2:DescribeInstanceTypeOfferings`.
- **Bootstrap action failed** → script error/network/S3 permission → check `/emr/instance-state` and bootstrap logs in the S3 log URI.
- **Step failed** → read `stderr`/`controller`/`syslog` in S3 logs (`s3://<log-uri>/<cluster-id>/steps/<step-id>/`); check Spark executor logs via History Server.
- **OOM in executors/containers killed by YARN** → raise `memoryOverhead`, executor memory, reduce cores per executor, fix skew.
- **Lost nodes/`ExecutorLostFailure` on Spot** → interruptions → more task fleets/types, shuffle service/decommission, checkpoint outputs.
- **HDFS full / UnderReplicatedBlocks** → too few/too small core nodes → add core, reduce replication wisely, clean temp.
- **Managed scaling not scaling** → missing CloudWatch metrics, API Gateway VPC endpoint private DNS, non-YARN app, DRA off → fix per section C.
- **Slow S3 listing/writes** → too many small files/rename commit → use S3-optimized committer, compaction.
- **Cluster terminated unexpectedly** → termination protection off with `auto-terminate`, idle policy, or all steps finished → check `StateChangeReason`.
- **Primary node out of disk/memory** → large driver output, many concurrent steps → bigger primary, move driver to cluster mode.
- **Access denied to S3** → instance profile/EMRFS role mapping/runtime role missing → fix IAM or S3 policy.

## I. Scenarios: "If X → Y, because Z"
- **If** **Spot Instances** (spare EC2 capacity, up to ~90% cheaper, but reclaimed with a **2-minute warning**) keep killing your Spark job, **then** use **instance fleets** with many instance types (up to 5 per fleet), the **price-capacity-optimized** allocation strategy, Spot only for **task nodes**, and Spark **decommission settings** that move shuffle data off a leaving node **(verify by release)**. **This works because** more instance types and this strategy lower the chance of interruption, and core and primary nodes stay **On-Demand**, so HDFS data is safe. Also keep durable data in S3 and make jobs retryable.
- **If** you want the cluster to scale out and in automatically with little tuning, **then** use **EMR managed scaling** and set a **minimum** and **maximum** capacity, plus an optional **On-Demand limit** (the rest becomes Spot) and **core limit** (the rest becomes task nodes). **This works because** EMR keeps checking cluster metrics and resizes **core and task** nodes for you, and its scale-in is **shuffle-aware**: it does not remove nodes that hold Spark shuffle data in use. Keep Spark **dynamic allocation** on, or the cluster may over-scale to the maximum.
- **If** the cluster must keep running when a primary node fails, **then** launch it with **3 primary nodes** (high availability), all **On-Demand** and of the same instance type. **This works because** the cluster needs a **quorum of 2 of 3** healthy primaries, so it survives one failure and EMR replaces the lost node automatically. If **two** fail, the cluster fails.
- **If** you must survive the loss of a whole **Availability Zone (AZ)**, **then** keep all data in **Amazon S3** and recreate the cluster in another AZ automatically with **infrastructure as code**. **This works because** every EMR cluster, even a high-availability one, runs in **one AZ** and cannot tolerate an AZ outage, while S3 data stays available.
- **If** a production cluster has only **3 core nodes**, **then** set **`dfs.replication` to 2 or more**, or better, use **at least 4 core nodes**. **This works because** `dfs.replication` is how many copies HDFS keeps of each block; with only 1 copy, one failed node loses data. EMR also **will not scale core nodes below** `dfs.replication`.
- **If** managed scaling does not trigger and your VPC has an **interface VPC endpoint for Amazon API Gateway** with **private DNS** on, **then** remove that endpoint or turn off its private DNS. **This works because** the managed scaling metrics collector must reach the **public** managed scaling API endpoint, and private DNS sends its traffic to the wrong place.
- **If** **Presto** or **HBase** needs to scale, **then** use **manual resize** or, on **instance group** clusters only, **custom automatic scaling** policies (CloudWatch metric rules). **This works because** EMR managed scaling supports only **YARN** applications (Spark, Hadoop, Hive, Flink), and Presto and HBase do not run on YARN.
- **If** Spark jobs spend a long time renaming files in S3 at the end, **then** use the **EMRFS S3-optimized committer**. **This works because** it writes output without the slow **rename** step that normal committers use, and renames are expensive on S3.
- **If** clusters start slowly because bootstrap actions install many packages, **then** build a **custom AMI** (Amazon Machine Image) with the software already inside. **This works because** the packages are pre-baked, so nodes do not install them at every launch.
- **If** a job on a **Graviton** (arm64) cluster fails on a library, **then** use **arm64-compatible builds** of that library. **This works because** native code must match the CPU architecture; Graviton gives better price-performance but needs arm-compatible libraries.

Verified from AWS docs on 2026-11-01 (managed scaling page, high availability considerations page, pricing excerpts, security page).
Unconfirmed (verify): allocation strategy names and provisioning timeout options for the current release; auto-termination policy min/max; `dfs.replication` defaults; executor sizing rules of thumb; Spark decommission settings by release; Sqoop availability; EMR runtime speedup claims; reconfiguration limits for fleets.

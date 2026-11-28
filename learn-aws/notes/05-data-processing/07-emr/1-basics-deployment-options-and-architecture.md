# Amazon EMR – 1. Basics, deployment options and architecture

Short notes. Each point is a fact you can be asked about.

## A. What EMR is
- **Amazon EMR** (formerly Elastic MapReduce) = managed platform to run **open-source big data frameworks** on AWS: **Apache Spark, Hadoop (MapReduce/YARN/HDFS), Hive, Presto/Trino, Flink, HBase, Hudi, Iceberg, Delta, Livy, Jupyter/JupyterHub, Zeppelin, Tez, Pig, Sqoop, Phoenix**, and more (set by the **release label**, for example `emr-7.14.0`).
- It processes data in **S3, DynamoDB, RDS/JDBC sources, Kinesis/Kafka** and writes back to them. Best known for **large-scale ETL (Spark)**, ML data prep, log analysis, genomics, clickstream and **lakehouse table maintenance**.
- **Latest release in the docs**: **EMR 7.14.0** (managed scaling guidance recommends the latest release). Release version drives **framework versions**; **pin the release** in production and **upgrade on purpose**.
- **Pick EMR when**: you need **open-source Spark/Hive/Flink/HBase** with control of versions, configs, custom libraries, large or specialized workloads, or you are **migrating existing Hadoop/Spark** jobs.
- **Pick something else when**:
  - Simple serverless ETL with a visual or catalog-centric flow → **AWS Glue** (less to manage).
  - Ad-hoc SQL on S3 → **Athena**.
  - Warehouse-style SQL with BI → **Redshift**.
  - Streaming stateful processing with minimal ops → **Managed Flink**.
  - Kubernetes-first platform → **EMR on EKS**.

## B. Three deployment options (very testable)
| Option | You manage | Billing | Best for |
|---|---|---|---|
| **EMR on EC2** | Cluster (instance groups/fleets), scaling, nodes, OS patching choices | EC2 + EMR uplift per instance, per second (1-min minimum) | Long-running or tuned clusters, HBase/Presto/Hadoop, full control, Spot-heavy batch |
| **EMR on EKS** | Nothing for clusters; you run jobs on an existing **EKS cluster** | EMR uplift per **vCPU-hour and GB-hour** + EKS ($0.10/h per cluster) + EC2/Fargate | Teams standardized on Kubernetes, many Spark versions on one shared cluster |
| **EMR Serverless** | Only **applications and jobs** | **vCPU-hours, GB-hours, storage** used by workers (per second, 1-min minimum) | Spiky/unpredictable Spark and Hive jobs, no cluster ops |
- **Rule**: **no ops + Spark/Hive** → **Serverless**; **already on Kubernetes** → **EKS**; **max control / non-Spark frameworks / steady big fleets** → **EC2**.
- All three can use **S3** as the data lake, the **Glue Data Catalog** as metastore, **EMR Studio** for notebooks, and **Lake Formation** for access control (varies by option).

## C. EMR on EC2 architecture
- **Cluster** = a collection of **EC2 instances** called **nodes**, each with a **node type**:
  - **Primary node** (formerly master): coordinates the cluster; runs **YARN ResourceManager**, **HDFS NameNode**, Livy/Hive server, web UIs. **Only one by default**; **three** in **high availability** mode.
  - **Core nodes**: run **HDFS DataNodes** and **YARN NodeManagers/tasks**. They **store HDFS data**. Removing them risks data loss/slow decommission.
  - **Task nodes** (optional): compute only, **no HDFS**. Safe to add/remove; ideal for **Spot**.
- **Single-node cluster**: primary only (dev/test).
- **Layers**: storage (HDFS, EMRFS/S3, local disk), cluster resource management (**YARN**), data processing frameworks (**MapReduce, Spark, Tez, Flink**), applications/programs (Hive, Pig, Spark SQL).
- **Cluster lifecycle states**: `STARTING` → `BOOTSTRAPPING` → `RUNNING` → `WAITING` (idle, ready for steps) → `TERMINATING` → `TERMINATED` / `TERMINATED_WITH_ERRORS`.
- **Two cluster patterns**:
  - **Transient (job) cluster**: created for a job, **auto-terminates after steps finish** (`--auto-terminate`). Cheapest for batch ETL; pairs with S3 for persistence.
  - **Long-running (persistent) cluster**: stays `WAITING` for ad-hoc/interactive/HBase/streaming. Use **managed scaling** and **idle auto-termination**.
- **Steps**: units of work added to a cluster (**Spark `spark-submit`**, **Hive script**, **custom JAR**, shell via `script-runner`/`command-runner.jar`). Steps run **in order** (default concurrency 1; **step concurrency** can be raised, default max 256 **(verify)**). **`ActionOnFailure`**: `TERMINATE_CLUSTER`, `CANCEL_AND_WAIT`, `CONTINUE`.
- **Bootstrap actions**: scripts that run on **every node before applications start** (install libs, configure OS). Run only at **cluster creation**; slow bootstraps delay readiness; failure fails the cluster.
- **Configurations (`Classification`/`Properties`)**: JSON overrides for application configs (`spark-defaults`, `yarn-site`, `hive-site`, `core-site`), set at cluster launch or **reconfigured** on running clusters (instance group clusters).
- **Applications** chosen by the **release label**; **EMR Release Guide** lists components/versions.

## D. Storage on EMR (where data lives)
- **S3 via EMRFS** (the recommended persistent store): `s3://` paths through the **EMR File System** (Hadoop `s3` scheme). Gives **durability, decoupled storage and compute**, and **consistent reads** (S3 is strongly consistent; the old EMRFS consistent view is not needed).
- **HDFS**: distributed file system on **core nodes' local/EBS volumes**. Fast local I/O for intermediate data; **data is lost when the cluster terminates**. Default replication factor **3** (lower on tiny clusters). Use for **shuffle/temp**, not for the system of record.
- **Local file system / instance store**: ephemeral per node.
- **EBS volumes**: attached to instances for HDFS/temp (encryptable); **EBS gp3** common; keep **utilization below 90%** (managed scaling can misbehave).
- **Lakehouse formats**: **Apache Iceberg, Hudi, Delta Lake** supported in recent releases for **ACID tables on S3** (upserts, time travel).
- **Hive metastore**: **AWS Glue Data Catalog** (recommended, shared with Athena/Redshift Spectrum) or a **MySQL/RDS/Aurora external metastore**, or the local metastore (lost with the cluster).
- **S3 committers**: Spark's **EMRFS S3-optimized committer** (default in newer releases for Parquet) avoids slow renames; **Magic/S3A committers** also exist for Hadoop S3A.
- **Compression and formats**: **Parquet/ORC + Snappy/ZSTD** for analytics; avoid many small files (target **128 MB–1 GB** files), use **partitioning** and **compaction**.

## E. Interfaces and tools
- **EMR Studio**: web IDE (Jupyter-based **workspaces**, notebooks, SQL explorer, Git integration) that connects to **EMR on EC2, EMR on EKS and EMR Serverless**. Auth via **IAM** or **IAM Identity Center**. Workspaces are stored in **S3**.
- **EMR Notebooks** (older, in console) → superseded by EMR Studio.
- **AWS CLI / SDK / API** (`RunJobFlow`, `AddJobFlowSteps`, `DescribeCluster`, `ListSteps`), **CloudFormation/CDK** (`AWS::EMR::Cluster`), **Step Functions** (native EMR integration: `createCluster`, `addStep`, `terminateCluster`), **MWAA/Airflow** operators, **Livy** REST endpoint for Spark.
- **Web UIs**: YARN ResourceManager, Spark History Server, Tez UI, Ganglia (older), Hue, Zeppelin, via **SSH tunnel**/**persistent application UIs** (kept after termination for 30 days **(verify)**), or **on-cluster proxy**.
- **Apache Ranger / Lake Formation** for fine-grained access (see file 4).
- **EMR on EC2 Image**: **custom AMI** (built on the Amazon Linux base) to pre-bake software and speed up startup.

## F. EMR vs related services
- **EMR vs Glue**: Glue is **serverless, catalog-centric, pay per DPU**, great for standard ETL; **EMR** gives **version/config/framework control**, non-Spark engines, interactive data science and often **lower cost at large sustained scale with Spot**.
- **EMR vs Redshift**: Redshift is a **managed MPP data warehouse** for SQL/BI; EMR is a **general compute platform** over the lake.
- **EMR vs Athena**: Athena is **serverless SQL on S3** (Trino-based) for ad-hoc queries; EMR runs **long ETL and ML jobs**, custom code, streaming.
- **EMR vs Databricks/Snowflake**: third-party platforms; EMR is AWS-native, cheaper per unit, more DIY.
- **EMR vs SageMaker Processing/Training**: EMR for **big distributed data prep**; SageMaker for **ML training/hosting**; combine (EMR → S3 → SageMaker).
- **EMR vs Managed Flink**: for **stateful stream processing**, Managed Flink is easier; EMR can run **Flink** but you operate it.

## G. Typical data-engineering architectures
- **Batch ETL**: S3 raw → **transient EMR Spark** (Step Functions/MWAA triggers) → S3 curated (Parquet/Iceberg) → Glue Catalog → Athena/Redshift Spectrum/QuickSight.
- **Lakehouse compaction/maintenance**: scheduled EMR (or EMR Serverless) jobs run **Iceberg `rewrite_data_files`, snapshot expiry, Hudi compaction**.
- **Streaming ingest**: Kinesis/MSK → **Spark Structured Streaming** on EMR → Iceberg/Hudi on S3.
- **ML data prep**: EMR Spark builds features → **SageMaker Feature Store/S3** → training.
- **Migration**: on-prem Hadoop → **EMR + S3** (use **DistCp/S3DistCp**, **DataSync**, **Snowball (where available)**), Hive metastore → Glue Catalog.

## H. Scenarios: "If X → Y, because Z"
- **If** you run a Spark job every night and want to pay only while it runs, **then** use a **transient Amazon EMR cluster** (one created for the job that **auto-terminates** when its steps finish) or **EMR Serverless** (no cluster; you only submit jobs). **This works because** EMR bills compute **per second with a 1-minute minimum**, and your data stays in **Amazon Simple Storage Service (S3)**, so nothing is lost when the compute goes away. A long-running cluster would bill you all day, even when idle.
- **If** you do not want to manage clusters at all, **then** use **EMR Serverless**: you create an **application** and submit **jobs**, and nothing else. **This works because** EMR provisions the workers for each job, scales them up and down, and releases them when the job ends.
- **If** your platform team runs everything on Kubernetes and wants many Spark versions on one shared cluster, **then** use **EMR on EKS** (EMR running Spark jobs on your existing **Amazon Elastic Kubernetes Service (EKS)** cluster). **This works because** each **virtual cluster** is a registered EKS namespace, and many virtual clusters share the same EKS capacity while each job picks its own **release label** (Spark version). You still pay **$0.10/hour per EKS cluster** plus the nodes.
- **If** you need **HBase** (a NoSQL database on Hadoop) or **Presto** on a long-lived cluster, **then** use **EMR on EC2** (a cluster of **Amazon Elastic Compute Cloud (EC2)** instances you control). **This works because** EMR Serverless runs only **Spark and Hive** (as stated in the docs; other engines **(verify)**), and EMR on EKS runs Spark jobs. The catch: **EMR managed scaling** covers only YARN applications, so it does **not** scale Presto or HBase; you resize those yourself.
- **If** core nodes keep failing or causing trouble when the cluster scales in, **then** add and remove capacity with **task nodes** (compute only, no stored data) and keep **core nodes** stable. **This works because** core nodes store **Hadoop Distributed File System (HDFS)** data, so removing them risks data loss and slow decommissioning. Task nodes hold no HDFS data, so they are safe to add, remove, or run on **Spot**.
- **If** data on your cluster disappears after the cluster terminates, **then** it was stored on **HDFS**; keep durable data in **Amazon S3** (through **EMRFS**, the EMR File System) instead. **This works because** HDFS lives on the nodes' local or EBS disks and is lost at termination, while S3 is durable and separate from the compute.
- **If** you need to update rows and use **time travel** (read old versions) on tables stored in S3, **then** use an open table format on EMR: **Apache Iceberg**, **Apache Hudi** or **Delta Lake**. **This works because** these formats add **ACID** transactions (safe, all-or-nothing changes), upserts and snapshots on top of plain files in S3.
- **If** you want one shared table catalog for EMR, **Amazon Athena** (serverless SQL on S3) and **Amazon Redshift Spectrum**, **then** use the **AWS Glue Data Catalog** as the Hive metastore. **This works because** it is managed by AWS and shared by all these services, while a local metastore is lost with the cluster.
- **If** an analyst needs a notebook to work with big data, **then** use **EMR Studio**, a web IDE with Jupyter-based **workspaces** (stored in S3). **This works because** Studio attaches its notebooks to **EMR on EC2** clusters, **EMR on EKS** and **EMR Serverless** applications, and users sign in with **Identity and Access Management (IAM)** or **IAM Identity Center**.

Verified from AWS docs on 2026-11-01 (EMR overview, EMR Serverless overview, EMR on EKS overview, managed scaling page, high availability page, security page, pricing page excerpts).
Unconfirmed (verify): the exact framework list per release; step concurrency limits; persistent application UI retention; S3 committer defaults by release; Serverless engine support beyond Spark and Hive; EMR Notebooks status; migration tool availability (for example Snowball).

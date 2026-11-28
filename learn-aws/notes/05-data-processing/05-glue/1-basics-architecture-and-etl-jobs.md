# Glue – 1. Basics, architecture and ETL jobs

Short notes. Each point is a fact you can be asked about.

## A. What Glue is
- AWS Glue = **serverless data integration**. It finds data, catalogs it, and runs ETL (extract, transform, load) code. No cluster to build or patch.
- Pay for what runs. ETL jobs are billed in **DPU-hours** (per second). The catalog is billed by objects stored and requests.
- **DPU** (data processing unit) = **4 vCPU + 16 GB memory**. All Glue capacity and billing is counted in DPUs.
- Glue is not one thing. It is a family that shares one catalog:
  - **Data Catalog** (metadata store) and **crawlers** (fill it).
  - **ETL jobs** (Spark, Spark Streaming, Python shell, Ray).
  - **Triggers and workflows** (chain jobs and crawlers).
  - **Glue Data Quality** (rules on data).
  - **DataBrew** (no-code data preparation).
  - **Schema Registry** (versioned stream schemas).
  - **Glue Studio** (visual editor, notebooks, monitoring page) and **interactive sessions**.
  - **Zero-ETL integrations** (managed replication into the lakehouse or Redshift).
- Pick Glue when:
  - You need serverless Spark ETL on S3, JDBC, Redshift, DynamoDB, Kafka or Kinesis data.
  - You want one catalog that Athena, Redshift Spectrum, EMR and Lake Formation also use.
  - Batch ETL of GB to TB where you do not want to run a cluster.
  - Streaming ETL from Kinesis or Kafka into S3 or a JDBC store.
- Avoid or reconsider Glue when:
  - Very small, fast, event-driven work under 15 minutes → **Lambda** is cheaper and starts faster.
  - You need full control of Spark, custom Hadoop/Hive tools or long-lived clusters → **EMR**.
  - It is a pure SQL transform on S3 data → **Athena** (CTAS/INSERT) or Redshift may be simpler.
  - Container batch jobs that are not Spark → **AWS Batch** or ECS/Fargate.
- Glue vs EMR: Glue = serverless, less tuning, higher price per compute hour. EMR = more control, can be cheaper at steady scale (Spot, Graviton), but you run the cluster (EMR Serverless sits in between).
- Glue vs Lambda: Lambda max 15 minutes, no Spark. Glue Spark jobs can run up to 7 days.
- Glue vs Athena: Athena queries data in place. Glue **moves and reshapes** data and builds the catalog Athena reads.
- Glue vs Step Functions / MWAA: Glue workflows only chain Glue jobs and crawlers. Step Functions and MWAA orchestrate many services (covered in file 4).

## B. Job types
- **Spark ETL** (`glueetl`): Apache Spark in a managed runtime. Python (PySpark) or Scala. The main type.
- **Spark Streaming** (`gluestreaming`): continuous Spark Structured Streaming from Kinesis, Kafka or MSK (file 3).
- **Python shell** (`pythonshell`): plain Python on a tiny machine, no Spark. For small tasks and glue code.
- **Ray**: distributed Python (Ray runtime) for Python-native parallel work. Uses its own M-DPU quota (verify details).
- A job is: a **script** (in S3) + **role** + **type and version** + **capacity** + **parameters** + **connections**.
- You can write the script yourself, upload one, or let Glue Studio **generate** it from a visual flow or from source/target choices.

## C. Glue versions
- The Glue version sets the Spark and Python versions:
  - **6.0** → Spark 4.1.1, Python 3.13.
  - **5.1** → Spark 3.5.6, Python 3.11. **Default for new jobs** if no version is given.
  - **5.0** → Spark 3.5.4, Python 3.11.
  - **4.0** → Spark 3.3.0, Python 3.10.
  - **3.0** → Spark 3.1.1, Python 3.7.
- Newer versions add features. Examples: auto scaling needs **3.0+**; observability metrics need **4.0+**; the biggest worker types need **4.0+**.
- Glue 2.0 and older do not support the worker-type model fully. For 2.0+ you set **worker type + number of workers**, not "max capacity".
- Iceberg versions bundled: 5.1 → 1.10.0, 5.0 → 1.7.1, 4.0 → 1.0.0, 3.0 → 0.13.1.
- Python shell jobs ignore the Glue version setting. They use their own Python version (3.9 now; 3.6 is retired).
- Move jobs to newer versions with the AWS migration guides. Test first, because Spark behavior changes between versions.

## D. Workers, DPUs and capacity
- You choose a **worker type** and **number of workers**. Cost = DPUs per worker × workers × time.
- Worker types (G = general purpose, R = memory-optimized):

| Type | DPU | vCPU | Memory | Notes |
|---|---|---|---|---|
| G.025X | 0.25 | 2 | 4 GB | **Streaming only**, low-volume streams, Glue 3.0+ |
| G.1X | 1 | 4 | 16 GB | Default choice for most jobs |
| G.2X | 2 | 8 | 32 GB | Bigger transforms and joins |
| G.4X | 4 | 16 | 64 GB | Heavy joins/aggregations, Glue 3.0+ Spark ETL |
| G.8X | 8 | 32 | 128 GB | Heavier still |
| G.12X | 12 | 48 | 192 GB | Glue 4.0+, very large jobs |
| G.16X | 16 | 64 | 256 GB | Glue 4.0+, largest |
| R.1X–R.8X | 1–8 | – | memory-optimized | Out-of-memory problems, high memory-to-CPU |

- G.12X, G.16X and all R types have **higher startup latency** and are only in some Regions. G.4X/G.8X are also Region-limited.
- Each worker runs **one Spark executor**. The driver also takes a worker. So N workers gives N−1 executors plus the driver (verify exact split).
- Python shell capacity: **0.0625 DPU** (default) or **1 DPU**. Local disk is 20 GB.
- Old "Standard" worker type exists only for Glue 1.0 and older. Do not use it.
- **Flex execution class** (cheaper, slower start):
  - For non-urgent work: tests, pre-production, one-time loads, overnight batch.
  - Needs Glue **3.0+** and **G.1X or G.2X** only. The newer big types (G.12X, G.16X, R types) do **not** support Flex.
  - Price: **$0.29 per DPU-hour** vs **$0.44** standard (us-east pricing page; Region-dependent).
  - Billed per worker for the time it actually ran, because workers can be added or removed.
  - Standard class = fast start and dedicated capacity for time-sensitive runs.
- **Auto Scaling**:
  - For ETL, interactive and streaming jobs on Glue **3.0+**.
  - The number of workers becomes the **maximum**. Glue adds and removes workers as Spark stages need them.
  - Turn on with `--enable-auto-scaling true` (or the Studio checkbox "Automatically scale the number of workers").
  - Helps when: the driver lists many S3 files while executors idle, stages run with few tasks, or data is skewed.
  - After a run, `get-job-run` shows **DPUSeconds** for real usage (batch jobs on 4.0+, not streaming).
  - Glue sets `spark.sql.shuffle.partitions` and `spark.default.parallelism` from the **maximum** DPUs. Override with `--conf` if needed.
  - Streaming: scaling needs several micro-batches by default. `--auto-scale-within-microbatch` allows scaling inside one batch.
  - Does not support the old Standard worker type.
  - Do not set an extreme maximum for tiny data. You will not save money, and more partitions are created.
- **Job run queuing**:
  - If enabled, a run that cannot start (quota or temporary capacity limit) **waits in a queue** instead of failing.
  - Good for high-volume pipelines that may hit the concurrent-run quota.
  - Catch: for VPC jobs it queues only if the IP shortage is seen at launch. Running out of IPs later (executors) still **fails** the job.
  - The run-level setting overrides the job-level setting.

## E. Key job settings
- **IAM role**: Glue assumes it to read sources, write targets, write logs. The person who creates the job needs `iam:PassRole` for it.
- **Timeout**: max **7 days (10,080 min)**. If left blank, default is **2,880 min (48 h)** for Glue 4.0 and older, **480 min (8 h)** for 5.0+. Jobs that time out are **not retried**.
- **Retries**: **0 to 10** automatic restarts after a failure. Timeouts are not retried.
- **Maximum concurrency**: default **1**. A new run while one is active returns an error. Raise it for parallel runs (bookmarks do not like this, see section G).
- **Job parameters**: key-value pairs with a `--` prefix (for example `--myKey`). Defaults live on the job. A run or trigger can override them.
- **Special parameters** you must know:
  - `--enable-auto-scaling`, `--enable-metrics`, `--enable-continuous-cloudwatch-log`, `--enable-observability-metrics`.
  - `--datalake-formats` (`iceberg`, `hudi`, `delta`), `--conf` (Spark settings).
  - `--additional-python-modules` (pip installs), `--extra-py-files`, `--extra-jars`.
  - `--TempDir` (temp path in S3), `--job-bookmark-option`, `--enable-glue-datacatalog` (use the Catalog as the Hive metastore).
- **Temporary path** (S3): working space for Redshift reads/writes and some transforms. Glue may create a temp bucket if none exists. Check its public-access settings.
- **Delay notification threshold**: sends a notification if a run stays in RUNNING, STARTING or STOPPING longer than N minutes.
- **Libraries**: Python library path, dependent JARs path, referenced files path (S3 comma-separated).
- **Security configuration**: encryption of S3 output, logs and bookmarks (file 5).
- **Connections**: attach a connection to put the job in a VPC or to reach JDBC/Kafka sources (section I).
- Job script and temp folders live in S3. Make sure the script path ends in `/` and holds no file named like the folder.
- A job run has states such as STARTING, RUNNING, STOPPING, STOPPED, SUCCEEDED, FAILED, TIMEOUT, ERROR, WAITING (queued).

## F. DynamicFrame vs DataFrame
- **DynamicFrame** = Glue's own dataset type. Each record is **self-describing**, so no schema is needed up front.
- If a field has mixed types (for example a number in some rows, text in others), the schema shows a **choice type**. You resolve it on purpose with `resolveChoice`.
- Spark **DataFrame** needs a schema first. If types are mixed it often falls back to string.
- Use DynamicFrame for **messy or changing** data and for Glue transforms. Convert to DataFrame (`toDF()`) for Spark SQL, joins/aggregations and Spark-native code. Convert back with `DynamicFrame.fromDF()`.
- `resolveChoice` actions: `cast:<type>`, `make_cols` (one column per type, named `col_type`), `make_struct`, `project:<type>`, `match_catalog` (cast to the Catalog table's types).
- Common transforms (names are the exam words): `ApplyMapping` (rename + change types; **unlisted fields are dropped**), `SelectFields`, `DropFields`, `RenameField`, `Filter`, `Map`, `Join`, `Union`, `SplitFields`, `SplitRows`, `DropNullFields`, `Unnest`, `Relationalize`, `ResolveChoice`, `Spigot` (write a sample to S3 to check output).
- `Unnest` flattens nested structs into top-level columns (for example `Address.City`).
- `Relationalize` turns nested and array data into a **set of flat tables** with keys (`id`, `index`) so you can load them into a relational database.
- `mergeDynamicFrame` merges a staging frame into a source frame by primary keys. Staging records win.
- `GlueContext` is the entry object in scripts. `Job.init()` / `Job.commit()` bracket the script and are **needed for bookmarks**.
- Read from the Catalog with `create_dynamic_frame.from_catalog` (gets partition columns). `from_options` reads directly with no Catalog.

## G. Job bookmarks
- A **job bookmark** stores what a job already processed, so the next run reads only **new** data. It is state kept **per job** by Glue.
- Option values: **Enable** (track and update state), **Disable** (default; read everything every time), **Pause** (read new data but do **not** update state; sub-options `job-bookmark-from` / `job-bookmark-to` take run IDs).
- Sources that support bookmarks: **S3** (JSON, CSV, Avro, XML, Parquet, ORC), **JDBC**, and the Relationalize transform.
- **S3** bookmarks use the **last-modified time** of objects, not file names. An old file that gets rewritten is read again.
- **JDBC** bookmarks use key columns:
  - Default is the table's **primary key**, but only if values are **sequential** (increasing or decreasing, no gaps).
  - You can name your own bookmark keys in the script. Column names are not allowed to be case-sensitive.
  - Detects **new rows**, not updated rows (the key already exists).
- To make it work, scripts need: `job.init()`, `job.commit()`, and a **`transformation_ctx`** on every source/transform/sink you want tracked.
- **Reprocessing data** with bookmarks on usually means: missing `job.commit()`, missing `transformation_ctx`, input changed after the last run, non-sequential JDBC keys, or **max concurrency > 1**.
- **Do not change the source path** while keeping the same `transformation_ctx`. Glue assumes the files in the new path were already processed and skips them.
- **Concurrent runs break bookmarks** (error "version mismatch"). Keep max concurrency at 1 for bookmarked jobs.
- **Rewind** a bookmark to an earlier run for backfill, or **reset** it: `aws glue reset-job-bookmark --job-name <name>`.
- Resetting or rewinding does **not** clean target files. Only sources are tracked. Write to a new output or de-duplicate to avoid duplicates.
- Deleting a job deletes its bookmark.
- Bookmarks do **not** work for **streaming** jobs (they use checkpoints) or **Python shell** jobs.
- Jobs that read tables with **Lake Formation cell-level filters** cannot use bookmarks, bounded execution, pushdown predicates or catalog partition predicates.
- For huge S3 prefixes, the bookmark lists all files in a partition and can run the driver out of memory. Use the **Glue S3 file lister** (verify option name) and partition well.
- Use a **Catalog table + crawler** with bookmarks for easier partition tracking, and a pushdown predicate to pick partitions.

## H. Glue Studio and console: the UI tour (how you actually use it)
- The Glue console has two main work areas: **Data Catalog** (databases, tables, connections, crawlers, classifiers, schema registries) and **ETL** (jobs, triggers, workflows, blueprints, data quality, notebooks, monitoring). Glue Studio is the ETL authoring and monitoring experience (verify exact menu names, they move often).
- **Three ways to start a job** from **ETL jobs → Create job**:
  1. **Visual ETL**: drag-and-drop flow of source → transforms → target on a canvas. Glue generates a PySpark script for you.
  2. **Notebook** (interactive code): Jupyter-style notebook backed by an **interactive session**.
  3. **Script editor**: write or upload Spark (Python or Scala), Ray or Python shell code.
- **Catch**: if you start with the **script editor** you **cannot go back** to the visual editor for that job. Editing the generated script of a visual job in code is the one-way door (verify direction details in current UI).
- **Example (sample) jobs** give a starting template: a visual job that joins three CSV files, a Spark notebook with pandas, a Spark notebook with SQL.
- The **visual canvas**:
  - Each **node** = one action (source, transform, target). Click a node to set its properties in a side panel.
  - Node types: **sources** (S3, Data Catalog table, JDBC/RDS, Redshift, DynamoDB, Kinesis, Kafka, plus connectors), **transforms** (change schema/ApplyMapping, filter, join, aggregate, drop duplicates, SQL query, custom code, union, fill missing values, flatten, detect sensitive data, evaluate data quality), **targets** (S3, Catalog, JDBC, Redshift and others). Node list is approximate **(verify)**.
  - **Data preview**: runs on a sample using a session so you can see each node's output before saving.
  - **Output schema** tab shows the columns after each node.
  - Each node's **Data quality** and **PII** options are built in (file 4).
- Job editor tabs (typical): **Visual**, **Script**, **Job details** (role, version, workers, timeout, retries, bookmarks, metrics, logging, Spark UI, parameters), **Runs**, **Data quality**, **Schedules**, **Version control** (Git) **(verify tab names)**.
- **Job details** page is where the settings from section E live. This is the page to change worker type, enable auto scaling, enable job observability metrics, continuous logging, the Spark UI, and the security configuration.
- **Runs** tab and the **Monitoring** page show run history, status, duration, DPU hours, logs, and links to CloudWatch logs and the Spark UI. Job run insights flag problems and suggestions **(verify names)**.
- **Amazon Q / generative AI** in Glue can generate ETL code and help troubleshoot Spark failures (there is a quota for in-flight AI completion requests). Treat as helper, not a design decision.
- **Interactive sessions** (notebook engine):
  - Serverless Spark session that starts in seconds from Glue Studio notebooks, SageMaker Unified Studio, local Jupyter or VS Code.
  - Billed per second while active. Default 5 DPUs and a long default **idle timeout (2,880 min)**. Lower it with `%idle_timeout` to save cost **(verify defaults)**.
  - Magics: `%glue_version`, `%worker_type`, `%number_of_workers`, `%idle_timeout`, `%%configure`, `%stop_session`.
  - **Development endpoints** are the older, provisioned way. Use interactive sessions for new work.
- **Blueprints**: reusable workflow templates (parameterized). Import data from S3/JDBC and convert formats. They create workflows (file 4).
- **SageMaker Unified Studio** also offers visual ETL and workflows (Airflow-based) that run Glue code. It is a newer front door to the same engine.
- Exam angle: "no code, visual, analysts and engineers" → **Glue Studio visual ETL** or **DataBrew** (DataBrew is for data preparation by analysts; Studio is for ETL jobs).

## I. Connections and connectors
- A **connection** (Data Catalog object) stores how to reach a data store: URL, credentials (prefer **Secrets Manager**), and optionally VPC settings.
- Common types: **JDBC** (RDS, Redshift, SQL Server, Oracle, MySQL, PostgreSQL), **Kafka** (MSK or self-managed), **MongoDB/DocumentDB**, **Network**, and marketplace/custom connectors **(verify full list)**.
- **Network connection** = placement only: tells Glue which VPC subnet and security groups to use for jobs that read S3 or private resources.
- **Kafka** needs a connection (bootstrap servers over TLS; plaintext is not supported). **Kinesis** needs no connection.
- A job can have more than one connection. For VPC placement Glue uses the **first** connection in the list.
- Connectors from AWS Marketplace or custom connectors plug in extra sources through the Glue Spark connector framework.
- Credentials: avoid putting passwords in the connection. Use Secrets Manager. Catalog **connection password encryption** is a separate Catalog setting (file 5).

## J. Scenarios (if → then, because)
- **If** you need to run Apache Spark ETL (extract, transform, load) from Amazon S3 to S3 with almost no admin work, **then** use an **AWS Glue Spark ETL job** (`glueetl`). You write PySpark or Scala code, or let **Glue Studio** generate it, and Glue runs it in a managed Spark runtime. **This works because** Glue is **serverless**: there is no cluster to build or patch, and you pay only for the **data processing unit (DPU)** hours the job runs (1 DPU = 4 vCPU + 16 GB memory), billed per second.
- **If** the task is a **3-minute** validation of a file in Amazon S3, **then** use **AWS Lambda**, not Glue. **This works because** Lambda starts faster and is cheaper for small, event-driven work under its **15-minute** limit, while a Glue job has Spark startup time and DPU billing.
- **If** a job loads a one-time historical backfill and nobody is waiting for it, **then** run it with the **Flex execution class** on **G.1X** or **G.2X** workers. Flex costs **$0.29 per data processing unit (DPU) hour** instead of **$0.44** for the standard class (US pricing; varies by Region). **This works because** Flex is made for non-urgent work, so it is cheaper but starts slower. It needs Glue **3.0+**, and the big worker types (G.12X, G.16X, R types) do not support it.
- **If** a nightly job gets very different data sizes each night, **then** turn on **Auto Scaling** (`--enable-auto-scaling true`, Glue **3.0+**) with a sensible number of workers. **This works because** that number becomes the **maximum**, and Glue adds and removes workers as each Spark stage needs them, so you pay for what is used. Do not set an extreme maximum for small data: it saves nothing and creates more partitions.
- **If** a job does about **200 GB** of memory-heavy joins and runs out of memory, **then** use bigger workers (for example **G.4X** with 64 GB, or larger) or **R** (memory-optimized) workers, or fix data **skew**. **This works because** each worker runs one Spark executor, so a bigger or memory-optimized worker gives each executor more memory. If one key holds most of the data, fixing skew may help more. The biggest types (G.12X, G.16X, R) start slower and exist only in some Regions.
- **If** a run fails because the account hit its **concurrent-run quota**, **then** enable **job run queuing**, or ask for a higher quota. **This works because** with queuing a run that cannot start **waits in a queue** (state WAITING) instead of failing. Catch: for jobs in a Virtual Private Cloud (VPC), running out of IP addresses after launch still fails the job.
- **If** a job must process only the **new** daily files, **then** set **job bookmarks** to **Enable**, give every source, transform and sink a **`transformation_ctx`**, and call `job.init()` and **`job.commit()`** in the script. **This works because** a bookmark stores, per job, what was already processed (for Amazon S3, by each object's **last-modified time**), so the next run reads only new data. Keep **max concurrency at 1**, because concurrent runs break bookmarks.
- **If** a job with bookmarks still reprocesses old files, **then** check that the script calls **`job.commit()`**, that each step has a **`transformation_ctx`**, that **max concurrency = 1**, and that the files were not rewritten. **This works because** these are the usual causes: without commit or `transformation_ctx` the state is not saved, concurrent runs cause a version mismatch, and S3 bookmarks use **last-modified time**, so a rewritten old file looks new.
- **If** you need to reprocess all data once, **then** reset the bookmark with `aws glue reset-job-bookmark --job-name <name>` and write to a **clean target**. **This works because** a reset makes the job read everything again, but it does **not** clean target files, so writing to the old output would create duplicates.
- **If** Java Database Connectivity (JDBC) bookmarks miss **changed** rows, **then** use **change data capture (CDC)**, for example with AWS Database Migration Service (DMS), or a custom query based on a timestamp column. **This works because** JDBC bookmarks track **key columns** and detect only **new** keys; an updated row keeps its old key, so the bookmark skips it.
- **If** a source column is a number in some files and text in others, **then** read it as a **DynamicFrame** and fix it with **`resolveChoice`** (for example `cast:<type>` or `make_cols`). **This works because** a DynamicFrame is self-describing and shows the mixed field as a **choice type** that you resolve on purpose; a Spark DataFrame would often fall back to string. `make_cols` makes one column per type, named `col_type`.
- **If** nested JSON must be loaded into relational database tables, **then** use the **`Relationalize`** transform and write each output table. **This works because** Relationalize turns nested and array data into a **set of flat tables** linked by keys (`id`, `index`).
- **If** an analyst wants to build an ETL job without code, **then** use **Glue Studio visual ETL**. **This works because** you drag source, transform and target **nodes** onto a canvas, and Glue generates the PySpark script for you.
- **If** a developer wants to test a transform step by step, **then** use a **notebook** backed by a Glue **interactive session**. **This works because** the session is serverless Spark that starts in seconds and is billed per second while active. Lower `%idle_timeout`, because the default idle timeout is long (2,880 min) **(verify)**.
- **If** you need a small Python task that runs longer than 15 minutes and needs no Spark, **then** use a **Python shell** job with **0.0625** or **1 data processing unit (DPU)**. **This works because** Python shell runs plain Python on a tiny machine, so it is cheap, and unlike AWS Lambda it is not limited to 15 minutes.
- **If** a team wrote a job in the **script editor** and now wants the visual editor, **then** this is not possible for that job, so choose the authoring mode before you start. **This works because** starting in the script editor is a one-way door: that job cannot go back to the visual canvas **(verify)**.
- **If** a streaming job must scale by itself, **then** use Glue **3.0+** with **Auto Scaling**, and the **G.025X** worker (0.25 DPU, streaming only) for tiny streams. **This works because** Auto Scaling adds and removes workers as load changes; for streaming it scales between micro-batches by default, and `--auto-scale-within-microbatch` lets it scale inside one batch.
- **If** a job must read a private Amazon Relational Database Service (RDS) database, **then** attach a Glue **connection** with the Virtual Private Cloud (VPC), subnet and security group, and give the subnet an **S3 gateway VPC endpoint** or a **NAT gateway**. **This works because** the connection makes Glue create network interfaces in your subnet so workers can reach the database, but the job still needs a route to Amazon S3. Keep the password in **AWS Secrets Manager**.
- **If** a long-running job by mistake runs for days, **then** set a **timeout** (max **7 days**; default **8 h** for Glue 5.0+ and **48 h** for 4.0 and older) and a **delay notification threshold**. **This works because** jobs are billed by run time, so the timeout stops a stuck job, and the delay notification warns you when a run stays RUNNING longer than N minutes. Jobs that time out are not retried.
- **If** a job costs more than expected for little data, **then** you likely have too many workers: use **Auto Scaling**, fewer or smaller workers (start with **G.1X**), or **Flex**. **This works because** cost = DPUs per worker × workers × time, so idle workers still cost money. After a run, `get-job-run` shows **DPUSeconds**, the real usage.

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: Spark job properties (versions 3.0–6.0, worker types and specs, Flex, retries, timeouts, concurrency, queuing, parameters), pricing page (DPU-hour prices, Flex), job bookmarks, auto scaling, Python shell jobs, streaming ETL, Studio job creation options, DynamicFrame transforms.
Not confirmed (verify): the N−1 executor split, Ray details and M-DPU quota, exact Studio node list and tab names, job run insights wording, interactive-session defaults (idle timeout 2,880 min, 5 DPUs), connection type list, S3 file lister option name, per-second billing minimum (1 minute) for jobs, exact script-editor one-way behavior, Glue 2.0 and older worker model.

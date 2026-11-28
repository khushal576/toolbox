# Managed Service for Apache Flink – 1. Basics, architecture, KPUs, versions and Studio

Short notes. Each point is a fact you can be asked about.

## A. What it is (and the rename history)
- Amazon Managed Service for Apache Flink (MSF) runs Apache Flink stream processing jobs for you. No servers or clusters to manage.
- Apache Flink = open-source engine for stateful processing of unbounded (streaming) and bounded (batch) data, with low latency (milliseconds to seconds).
- Old name: Amazon Kinesis Data Analytics for Apache Flink. Renamed to Managed Service for Apache Flink on 30 August 2023.
- The rename did not change the API. The API and CLI are still `kinesisanalyticsv2`, the service principal is still `kinesisanalytics.amazonaws.com`, and log groups are still `/aws/kinesis-analytics/<app>`.
- Exam trap: an answer that says "Kinesis Data Analytics" usually means MSF. Treat them as the same service for Flink apps.
- Kinesis Data Analytics for SQL applications (the old SQL-on-streams product with in-application streams and pumps) was a separate product. It was not renamed. It was shut down.
- KDA for SQL dates: no bug fixes from 1 September 2025; no new apps from 15 October 2025 (existing apps were stopped into READY and could be restarted); apps deleted starting 27 January 2026 and support ended.
- Migration from KDA for SQL is a rewrite, not an upgrade. AWS points to MSF Studio (interactive SQL/Python/Scala) or MSF applications (Java, Python, Scala, embedded SQL).
- KDA for SQL features like `RANDOM_CUT_FOREST` and `HOTSPOTS` are gone with it. In Flink you build anomaly detection yourself (custom code, Flink CEP, or calling a SageMaker endpoint).
- Exam trap: if an older question says "use Kinesis Data Analytics SQL with RANDOM_CUT_FOREST", the current answer is MSF (Flink) or MSF Studio, because KDA for SQL no longer exists.
- Other Kinesis renames to know: Kinesis Data Firehose → Amazon Data Firehose. Kinesis Data Streams and Kinesis Video Streams keep their names.
- MSF is serverless in the sense of "no infrastructure", but it is not scale-to-zero. A running app always bills at least its KPUs plus one orchestration KPU.

## B. Pick it when / avoid it when
- Pick MSF for: real-time stateful processing such as windowed aggregations, joins of streams, sessionization, deduplication, pattern detection, enrichment, streaming ETL.
- Pick MSF when you need event-time processing with watermarks and late data handling. Lambda and Firehose cannot do this.
- Pick MSF when you need exactly-once state consistency (checkpoints) and long-running state (hours, days, months).
- Pick MSF when you need sub-second latency on continuous streams. Spark micro-batch is usually seconds.
- Pick MSF when you want open-source Flink code (portable) without running Flink clusters.
- Avoid MSF for simple per-record transforms or routing. Lambda or Firehose transforms are cheaper and simpler.
- Avoid MSF for pure delivery to S3/Redshift/OpenSearch with buffering. Firehose does this with no code.
- Avoid MSF for large one-time batch jobs on files in S3. Glue, EMR or Athena fit better.
- Avoid MSF for very spiky, tiny, rarely used streams. The minimum always-on cost (2 KPUs for the smallest app) can beat Lambda pricing only at steady load.
- Avoid MSF if you need custom Flink settings that the service does not allow. Use Flink on EMR (EC2 or EKS) for full control.

## C. MSF versus nearest alternatives
| Need | Best fit | Why |
|---|---|---|
| Stateful windows, joins, event time, exactly-once state | MSF | Flink state, watermarks, checkpoints |
| Simple per-record transform from Kinesis/MSK | Lambda | Pay per use, no state |
| Buffer and deliver stream to S3/Redshift/OpenSearch/Iceberg | Amazon Data Firehose | No code, managed delivery |
| Spark-based streaming ETL into the data lake | Glue streaming ETL | Spark Structured Streaming, micro-batch, Glue catalog |
| Full Flink control, custom configs, many jobs on a shared cluster | Flink on EMR / EMR on EKS | You manage cluster, any config |
| Your own consumer logic on servers | KCL app on EC2/ECS/EKS | Full control, you manage scaling and checkpoints |
| Interactive SQL on live streams | MSF Studio | Zeppelin notebook on Flink |
- Lambda with Kinesis/MSK: stateless per batch; tumbling windows only, up to 15 minutes, state per shard and small. No event-time watermarks, no stream joins.
- Lambda catch: each batch is retried as a unit; no checkpointed state; ordering per shard only.
- Glue streaming: Spark Structured Streaming in micro-batches; latency of seconds; billed per DPU-hour; good when the team already uses Spark and the Glue Data Catalog.
- Glue streaming catch: weaker for complex event-time logic, CEP and sub-second latency. Flink is the native streaming engine.
- EMR Flink: you choose instance types, Flink configs and versions; can run many jobs on one cluster; YARN or EKS.
- EMR Flink catch: you own patching, scaling, HA setup and cluster cost.
- Firehose: buffers by size and time, optional Lambda transform, format conversion to Parquet/ORC, dynamic partitioning, delivery to Iceberg tables.
- Firehose catch: no joins, no windows over many records, no long-lived state.
- KCL consumer: you write the loop and checkpoint to DynamoDB leases. You build any state store yourself.
- Common combo: KDS or MSK → MSF (enrich, aggregate) → Firehose or FileSink → S3 data lake, and → KDS/OpenSearch/DynamoDB for real-time use.
- Redshift streaming ingestion reads KDS/MSK directly into materialized views. Pick it when the goal is SQL in Redshift, not stream processing.

## D. Ways to build an MSF application
- Java (DataStream API, Table API, Flink SQL embedded in Java). Most features, most connectors, best documented.
- Python (PyFlink). Code plus dependencies zipped and uploaded to S3.
- Scala. Flink's Scala API is removed in Flink 2.x. Scala code can still call the Java API.
- SQL. Embedded in Java/Python apps (Table API `executeSql`), or interactive in Studio notebooks.
- Apache Beam pipelines can run on the Flink runner in MSF (niche; dependency version traps).
- Code location: one JAR (Java/Scala uber JAR) or ZIP (Python) in an S3 bucket. `CodeContentType` is `ZIPFILE` for both.
- Max application JAR size is 512 MiB. Over the limit, the app fails to start.
- AWS advises keeping the uber JAR small (target about 104 MB). Big JARs slow start and restart.
- Do not bundle dependencies the runtime provides (`flink-core`, `flink-streaming-java`, table planner, log4j). Mark them `provided`. They are ignored anyway because of parent-first class loading.
- Connectors are not provided by the runtime (except the FileSystem connector). Bundle them in the JAR.
- Use the Maven shade `ServicesResourceTransformer`. Without it, connector/format SPI files clash in the uber JAR.
- Shade (relocate) packages that conflict with the Flink runtime. Symptom of a conflict: `ExecutionException` at start.
- Never call `System.exit()` in the code. Throw an exception instead; the service then restarts or fails the job cleanly.
- Do not store long-term credentials in the code. The app uses its service execution role; non-IAM secrets go in Secrets Manager.

## E. Runtime properties
- Runtime properties = key/value pairs in named property groups, set on the application. Change them without rebuilding code.
- Read them in Java with `KinesisAnalyticsRuntime.getApplicationProperties()`, which returns `Map<String, Properties>`.
- Typical use: stream names, Region, bucket paths, operator parallelism, feature flags.
- Updating properties is an `UpdateApplication` call. A running app restarts to pick them up (with a snapshot if snapshots are on).
- Trap: an update request replaces the whole property set. Omit a group or key and it is deleted.
- PyFlink uses a special group `kinesis.analytics.flink.run.options` to say which Python file is main and which JARs to load **(verify key names: `python`, `jarfile`, `pyFiles`)**.

## F. Flink architecture inside MSF
- JobManager = the coordinator. It schedules tasks, triggers checkpoints, handles recovery. MSF runs and manages it for you.
- TaskManager = a worker JVM that runs the tasks. Each TaskManager offers task slots.
- Job graph: source operators → transformation operators → sink operators. Connected by data streams.
- Operator chaining: Flink fuses neighbouring operators into one task to avoid serialization between them.
- `keyBy` splits the stream by key and sends all records with the same key to the same parallel subtask. This is a network shuffle.
- Parallelism = how many parallel subtasks each operator runs. Each subtask handles a subset of keys, shards or partitions.
- Default: all operators use the application `Parallelism` unless the code sets `setParallelism()` per operator.
- Operator parallelism can be set equal to or lower than the application parallelism.
- Best practice: set operator parallelism as a fraction of app parallelism (for example `env.getParallelism()/2`) so it moves with autoscaling.
- You do not choose instance types, TaskManager count or JVM flags. MSF derives them from Parallelism and ParallelismPerKPU.
- Many Flink configuration keys are locked. Flink 2.2+ throws an exception if code tries to set an unsupported config key; some keys can be changed through a support ticket.
- The Flink Dashboard (web UI) is available and read-only. You cannot cancel or submit jobs from it.
- Console dashboard URL is valid 12 hours. A CLI pre-signed URL (`CreateApplicationPresignedUrl`, type `FLINK_DASHBOARD_URL`) must be opened within 3 minutes.
- Dashboard is where you see backpressure per operator, checkpoint stage durations, flame graphs, thread dumps, and records per subtask (skew).
- An MSF application runs one Flink job. One app = one job graph.

## G. KPUs, parallelism and ParallelismPerKPU
- KPU (Kinesis Processing Unit) = 1 vCPU + 4 GB memory. Name kept from the Kinesis Data Analytics era.
- Each KPU also gives 50 GB of running application storage (local disk for state and checkpoints in progress).
- `Parallelism`: default 1. Default maximum 256.
- `ParallelismPerKPU`: how many parallel subtasks share one KPU. Default 1, maximum 8.
- Formula: allocated KPUs = Parallelism ÷ ParallelismPerKPU (rounded up).
- Example: Parallelism 8, ParallelismPerKPU 2 → 4 KPUs (+1 orchestration KPU billed).
- Raise ParallelismPerKPU for I/O-bound jobs (waiting on network calls). More subtasks share each vCPU without wasting it.
- Keep ParallelismPerKPU at 1 for CPU- or memory-heavy jobs. Each subtask then gets a full vCPU and 4 GB.
- Trap: high ParallelismPerKPU means less memory per subtask. Too high → network buffer errors or OOM.
- One extra KPU per application is charged for orchestration (JobManager). It shows in the `KPUs` metric.
- KPU quota: 64 KPUs per application by default. Raise with a quota increase (name the application in the request).
- Parallelism limit = ParallelismPerKPU × KPU limit.
- `ParallelismConfiguration` has `ConfigurationType` `DEFAULT` or `CUSTOM`. Set `CUSTOM` to use your own Parallelism, ParallelismPerKPU and AutoScalingEnabled values.
- `DEFAULT` parallelism config means Parallelism 1, ParallelismPerKPU 1, autoscaling on **(verify)**.
- Billing is for allocated KPUs, not used CPU. An idle app with 10 KPUs pays for 10 KPUs.
- Source parallelism above the number of Kinesis shards or Kafka partitions leaves source subtasks idle. Each shard/partition is read by one subtask.
- Fix for few shards and heavy deserialization: read raw `byte[]`, `rebalance()`, then deserialize in a wider downstream operator.

## H. maxParallelism (key groups)
- maxParallelism = number of key groups. It caps how far the job can scale while keeping state.
- If you do not set it and start with parallelism ≤ 128, all operators get maxParallelism 128.
- The job can never scale above the lowest maxParallelism of any operator.
- Changing maxParallelism of an existing app breaks restore from older snapshots. You must start without a snapshot.
- If you plan to go above parallelism 128, set maxParallelism explicitly in code from day one.
- Autoscaling will not scale past maxParallelism. A manual scale past it makes the app fail to start.

## I. Running application storage and durable storage
- Running application storage = local disk on the workers (50 GB per KPU). Holds RocksDB state and temporary checkpoint data.
- Durable application storage = service-managed S3 storage for checkpoints and snapshots. You do not see or manage the bucket.
- State backend in MSF is RocksDB (embedded key/value store on local disk). Checkpoints upload state to durable storage.
- MSF uses incremental checkpoints: only changed RocksDB files are uploaded each time.
- Both storages are encrypted at rest by default (AWS owned keys). Customer managed KMS keys are optional (file 4).
- Running out of local disk (`containerDiskUtilization` near 100%) → add KPUs or reduce state.
- Snapshots (savepoints) count as durable application backups and are billed per GB-month.

## J. Application lifecycle and statuses
- Statuses: `READY` (created or stopped), `STARTING`, `RUNNING`, `UPDATING`, `AUTOSCALING`, `STOPPING`, `FORCE_STOPPING`, `DELETING`, `MAINTENANCE`, `ROLLING_BACK`, `ROLLED_BACK`.
- Create → `READY` (no charge for KPUs while READY). `StartApplication` → `STARTING` → `RUNNING`.
- `StopApplication` takes a snapshot first (if snapshots are on). `Force=true` stops without a snapshot.
- While `AUTOSCALING`, the only allowed action is `StopApplication` with `Force=true`.
- Each `UpdateApplication` creates a new `ApplicationVersionId`. Updates must pass the current version ID (optimistic locking) or a `ConditionalToken`.
- `RollbackApplication` returns to the previous version (code, config and runtime) and restores from the last snapshot taken before the update.
- System rollback (auto-rollback) can be turned on in `ApplicationSystemRollbackConfiguration`. If an update or upgrade fails to start, MSF rolls back without you.
- `ListApplicationOperations` shows history of updates, scaling, maintenance and rollbacks.
- An app that faults while restoring incompatible state can get stuck in `STOPPING` or `UPDATING`. Force stop, then fix (file 3).
- `ApplicationMode` is `STREAMING` (normal app) or `INTERACTIVE` (Studio notebook).

## K. Maintenance
- MSF patches OS and container images. Each Region has a fixed 8-hour maintenance window (for example US East N. Virginia 03:00–11:00 UTC).
- Maintenance restarts the app. Downtime is about 10–30 seconds, depending on state size and checkpoint recency.
- You can change the maintenance start time with `UpdateApplicationMaintenanceConfiguration`. The change applies to the next scheduled maintenance.
- You cannot opt out, pause or pick days for maintenance.
- Notifications come by email and AWS Health. `ListApplicationOperations` filtered on `ApplicationMaintenance` shows past events.
- Keep checkpoints on and set operator UIDs. Missing UIDs are a common cause of restore failures after maintenance.

## L. Supported Flink versions (as listed in AWS docs)
| Flink version | MSF status | Notes |
|---|---|---|
| 2.3.0 | Supported | Newest; Java 17, Python 3.12; no Studio |
| 2.2.1 | Supported | First 2.x on MSF; breaking changes; no Studio |
| 1.20 | Supported | Last 1.x line, community LTS |
| 1.19.1 | Supported | |
| 1.18.1 | Supported | Community unsupported |
| 1.15.2 | Supported | Community unsupported; Studio runtime base |
| 1.13 | Deprecated | MSF support ended 16 October 2025 |
| 1.6, 1.8, 1.11 | Retired | No create from Nov 2024; apps put in READY 14 July 2025; no START from 28 July 2025 |
- Runtime is set with `RuntimeEnvironment`, for example `FLINK-1_20` or `FLINK-2_2`.
- MSF versions follow Apache Flink releases with a delay. MSF can keep a version longer than the community does.
- Flink 2.x removed the DataSet API (use DataStream in batch mode or Table/SQL), the Scala API, and the legacy `SourceFunction`/`SinkFunction` interfaces (use FLIP-27 Source and FLIP-143 Sink).
- Flink 2.2 on MSF: Java 11 removed (Java 17 default), Python 3.8 removed (Python 3.12 default), Kryo 2.24 → 5.6 (state risk for POJOs with collections).
- Flink 2.2 on MSF: read-only root filesystem (write only under `/tmp`); instance metadata (IMDS) calls other than credentials/Region are blocked.
- Flink 2.2 metric changes: `fullRestarts` removed (use `numRestarts`); `uptime`/`downtime` deprecated (use `runningTime`, `restartingTime`, `cancellingTime`, `failingTime`).
- Flink 2.2 SQL additions: `VARIANT` type for JSON, `ML_PREDICT` and `CREATE MODEL`, ProcessTableFunction, multi-way join operator.
- Not supported on MSF 2.2/2.3: Materialized Tables, custom metric reporters, ForSt (disaggregated) state backend, Java 21.
- Flink 2.3 on MSF keeps `pipeline.watermark-alignment.max-drift` at 0 by default, so watermark alignment behaves as in older versions.
- Some connectors lagged for 2.x: at the time of writing, OpenSearch and Prometheus connectors had no 2.x release; JDBC 2.x is a new modular artifact (`flink-connector-jdbc-core` + database module).

## M. In-place version upgrades
- In-place version upgrade = change `RuntimeEnvironment` on the same application with `UpdateApplication`. Same ARN.
- Kept across the upgrade: snapshots, logs, metrics, tags, Flink configs, quota increases, VPC settings.
- You can upgrade from `RUNNING` (checked at update) or `READY` (checked at next start).
- Upload the new JAR with a different S3 file name and point the update at it together with the new runtime.
- CloudFormation now updates `RuntimeEnvironment` in place. Older behavior deleted and recreated the app, losing snapshots.
- Take a snapshot before upgrading (or keep automatic snapshots on). Rollback needs a pre-upgrade snapshot.
- Turn on system rollback first. If binary incompatibilities stop the job from starting, MSF rolls back within minutes.
- Incompatible state shows up after a "successful" upgrade as a restart loop within seconds. Use `RollbackApplication` manually.
- Major upgrade 1.x → 2.x is one-way for state. A 2.x snapshot cannot be restored on 1.x. Rollback uses the 1.x snapshot from before the upgrade.
- In-place version upgrades do not work for Studio notebooks.
- AWS advises testing the upgrade on a replica app and running 24+ hours before trusting it in production.

## N. Studio notebooks
- MSF Studio = serverless Apache Zeppelin notebooks backed by a Flink cluster. Interactive analysis of live streams.
- Languages: Flink SQL (`%flink.ssql`), Python/PyFlink (`%flink.pyflink`, `%flink.ipyflink`), Scala (`%flink`). Markdown with `%md`.
- Table API and SQL in SQL, Python or Scala; DataStream API in Scala.
- Zeppelin adds visualizations (charts) and export of results.
- Studio requires an AWS Glue Data Catalog database. Tables in the catalog hold the schemas, endpoints and connector properties of sources and sinks.
- Create a notebook from the MSF console (Studio tab), or from the KDS console or MSK console with "Process data in real time".
- API: a notebook is an MSF application with `ApplicationMode=INTERACTIVE` and a `ZEPPELIN-FLINK-x_0` runtime.
- Studio runtime versions: Flink 1.15 with Zeppelin 0.10 is the recommended Studio runtime. Older Studio runtimes (Flink 1.11, 1.13) are deprecated.
- Studio does not support Flink 2.2 or 2.3. It is stuck on the 1.x runtime.
- Checkpoints and savepoints are not enabled by default for Studio notebooks.
- Autoscaling does not apply to the notebook itself. It applies to an app deployed from the notebook.
- Studio pricing: 2 extra KPUs per notebook (one orchestration, one for the interactive environment) on top of the KPUs running your queries, plus running storage.
- Stop notebooks when not in use. A forgotten notebook bills KPUs every hour.
- Studio quotas: note size 5 MiB, websocket message 5 MiB, 1,000 notes, cumulative UDF size 100 MiB, cumulative dependency JARs 300 MiB.
- Custom connectors and UDFs are added as JAR dependencies on the notebook.
- Best practice: set paragraph result refresh interval to at least 1,000 ms.

## O. Deploy a Studio note as an application with durable state
- "Deploy as application" builds the note into code in S3 and creates a normal streaming MSF application from it.
- The deployed app runs continuously, keeps durable state (snapshots), and can autoscale.
- The S3 bucket for the exported code must be in the same Region as the notebook.
- Paragraphs run in order (top to bottom). Disabled and `%md` paragraphs are skipped.
- Allowed interpreters: `%flink`, `%flink.ssql`, `%flink.pyflink`, `%flink.ipyflink`, `%md`.
- Mix Python + SQL or Scala + SQL. Python and Scala together in one note cannot be deployed.
- A note must produce exactly one Flink job. At most one paragraph may contain DML (`INSERT`).
- Plain `SELECT` statements are not allowed in a deployed note, because there is no output section to show results. Use `INSERT INTO` a sink table.
- DDL (`CREATE`, `USE`, `SET`) must come before DML in a paragraph.
- Zeppelin context `z`, dynamic forms, `!` shell commands and IPython magics are not supported in deployed notes.
- `%flink.ssql(parallelism=32)` hints are ignored after deploy. Set Parallelism on the deployed app or turn on autoscaling.
- Deploying with durable state needs internet access from the VPC (or the documented no-internet workaround).

## Scenarios: "If X → Y, because Z"
- **If** a team still runs **Kinesis Data Analytics (KDA) for SQL** applications, **then** they must **rewrite** them, either as interactive SQL in **Managed Service for Apache Flink (MSF) Studio** notebooks or as a normal **MSF application** (Java, Python, Scala or embedded SQL). **This works because** KDA for SQL was a separate product that was shut down, not renamed: no new apps from **15 October 2025**, and apps were **deleted from 27 January 2026**. Moving over is a rewrite, not an upgrade, and features like `RANDOM_CUT_FOREST` are gone, so that logic must be rebuilt in Flink.
- **If** a question names "**Kinesis Data Analytics for Apache Flink**", **then** read it as **Amazon Managed Service for Apache Flink (MSF)**. **This works because** it is the same service, renamed on **30 August 2023**; the API (`kinesisanalyticsv2`), service principal and log group names did not change.
- **If** you need rolling metrics per user over **30 minutes**, and some events arrive late, **then** use **Managed Service for Apache Flink (MSF)** with **event-time windows**. Event time is the timestamp inside the record, and a **watermark** tells Flink when a window can close, so late events still land in the right window. **This works because** Flink supports watermarks and late-data handling, while **AWS Lambda** reading Kinesis has no watermarks, supports only tumbling windows of **at most 15 minutes**, and keeps only small state per shard.
- **If** you only need to land a stream in **Amazon S3** as **Parquet** files, **then** use **Amazon Data Firehose**, which buffers records by size and time, converts them to Parquet and delivers them with no code. **This works because** Managed Service for Apache Flink (MSF) would add code to maintain, plus an always-on cost of its **Kinesis Processing Units (KPUs)** and one orchestration KPU, with no gain when there is no stateful logic.
- **If** analysts want to explore a live **Kinesis Data Streams (KDS)** stream with SQL today, **then** use **Managed Service for Apache Flink (MSF) Studio**, serverless Apache Zeppelin notebooks backed by a Flink cluster. **This works because** Studio gives interactive Flink SQL (and Python or Scala) with charts, and can be created straight from the KDS console with "Process data in real time". Studio needs an **AWS Glue Data Catalog** database for table schemas. Stop the notebook when done, because it bills **2 extra Kinesis Processing Units (KPUs)** while running.
- **If** a Studio query must then run **24/7**, **then** use "**Deploy as application**" with durable state. This builds the note into code in Amazon S3 and creates a normal streaming Managed Service for Apache Flink (MSF) application. **This works because** notebooks are for interactive work: the notebook itself does not autoscale and has no checkpoints or savepoints by default. The deployed app runs continuously, keeps durable state (snapshots) and can autoscale. The note must produce exactly **one** Flink job, and the code bucket must be in the same Region.
- **If** a deployed Studio note fails because it contains a plain `SELECT`, **then** change it to `INSERT INTO` a sink table. **This works because** a deployed note has no output section to show results, so it must write its results somewhere.
- **If** an I/O-heavy job (one that mostly waits on network calls) shows **low CPU** but its lag keeps growing, **then** raise **ParallelismPerKPU**, the number of parallel subtasks that share one **Kinesis Processing Unit (KPU)** (1 vCPU + 4 GB memory). **This works because** more subtasks can wait on I/O at the same time on each vCPU, so no CPU is wasted. The default is **1** and the maximum is **8**. The catch: each subtask then gets less memory, so going too high can cause network buffer errors or out-of-memory (OOM) failures.
- **If** a CPU-heavy job hits **out-of-memory (OOM)** errors after you raised **ParallelismPerKPU**, **then** lower it back (ideally to **1**). **This works because** more subtasks per **Kinesis Processing Unit (KPU)** means each subtask shares the KPU's **4 GB** of memory with others; at 1, each subtask gets a full vCPU and 4 GB. Allocated KPUs = Parallelism ÷ ParallelismPerKPU, so lowering it adds KPUs and cost.
- **If** the job must later scale beyond **parallelism 128** while keeping its state, **then** set **maxParallelism** explicitly in code **now**. maxParallelism is the number of **key groups** and caps how far the job can scale with its state. **This works because** if you do not set it and start at parallelism ≤ 128, operators get **128**, and changing it later breaks restore from older snapshots, so you would have to start with empty state. Autoscaling also never goes past it.
- **If** an application needs more than **64 Kinesis Processing Units (KPUs)**, **then** request a **quota increase** for that application, naming the application in the request. **This works because** 64 KPUs per application is the default (soft) limit, and maximum parallelism = ParallelismPerKPU × the KPU limit.
- **If** the source **Kinesis Data Streams (KDS)** stream has **4 shards** and the app's parallelism is **16**, **then** only **4** source subtasks read data and the rest sit idle. **This works because** each shard is read by exactly one subtask. To use the wider parallelism, read raw `byte[]` at the source, call `rebalance()` (round robin to all subtasks), then do the heavy deserialization in a wider downstream operator.
- **If** you must run custom Flink configuration settings that Managed Service for Apache Flink (MSF) blocks, **then** run **Flink on Amazon EMR** (on EC2 or EKS). **This works because** MSF locks many Flink configuration keys (Flink 2.2+ throws an exception if code sets one; some can be changed through a support ticket), while on EMR you choose instance types, configs and versions. The catch: you then own patching, scaling, high availability and cluster cost.
- **If** you need many Flink jobs sharing one cluster, **then** use **Flink on Amazon EMR**. **This works because** one Managed Service for Apache Flink (MSF) application runs exactly **one** Flink job, while an EMR cluster can run many jobs. The catch is that you manage the cluster yourself.
- **If** an in-place upgrade to **Flink 2.2** "succeeds" but the app then enters a **restart loop**, **then** call `RollbackApplication` yourself. It returns to the previous code, config and runtime and restores the last snapshot taken before the update. **This works because** incompatible state only shows up after the job starts (a restart loop within seconds), so automatic **system rollback**, which catches jobs that fail to start, may not help. Always take a snapshot before upgrading; rollback needs it.
- **If** you must go back from **Flink 2.2** to **1.20**, **then** roll back to the **pre-upgrade snapshot** taken on 1.20. **This works because** a 1.x → 2.x upgrade is one-way for state: a 2.x snapshot cannot be restored on 1.x, so state built after the upgrade is lost.
- **If** a **Managed Service for Apache Flink (MSF) Studio** user wants **Flink 2.2** features, **then** that is not possible in Studio; build a normal MSF application on Flink 2.2 instead. **This works because** Studio does not support Flink 2.2 or 2.3; its recommended runtime is Flink 1.15 with Zeppelin 0.10, and in-place version upgrades do not work for notebooks.
- **If** an **AWS CloudFormation** stack must upgrade the Flink version without losing snapshots, **then** change `RuntimeEnvironment` (for example `FLINK-1_20` to `FLINK-2_2`) in place on the same application. **This works because** current CloudFormation updates `RuntimeEnvironment` in place, keeping the same ARN, snapshots, logs and settings. Older CloudFormation behavior deleted and recreated the app, which lost the snapshots.
- **If** the team cannot accept maintenance restarts on a weekday morning, **then** move the maintenance **start time** with `UpdateApplicationMaintenanceConfiguration`. **This works because** the service patches apps in a fixed **8-hour** window per Region with about **10–30 seconds** of downtime, and you cannot opt out, pause it or pick days. A new start time applies from the next scheduled maintenance.
- **If** the job writes temporary files to `/opt/...` and starts failing after moving to **Flink 2.2**, **then** change the paths to `/tmp`. **This works because** Flink 2.2 on Managed Service for Apache Flink (MSF) has a **read-only root filesystem**; only `/tmp` is writable.
- **If** code reads the instance ID from the **instance metadata service (IMDS)** on **Flink 2.2**, **then** pass that value through environment variables or app config (runtime properties) instead. **This works because** Flink 2.2 on Managed Service for Apache Flink (MSF) blocks IMDS calls other than credentials and Region.
- **If** a stopped app sits in **READY** status for a week, **then** you pay **no Kinesis Processing Unit (KPU)** charge for it. **This works because** only running apps bill KPUs; a READY app (created or stopped) does not. Its **snapshots** still bill as durable storage per GB-month.
- **If** an app fails to start right after its uber JAR grew to **600 MiB**, **then** slim the JAR. **This works because** **512 MiB** is the hard limit for the application JAR. Mark runtime-provided dependencies (such as `flink-core`, the table planner and log4j) as `provided`; AWS advises a target of about **104 MB**, because big JARs also slow start and restart.
- **If** connector classes are "not found" at runtime, **then** bundle the connector (for example Kinesis or Kafka) inside the application JAR. **This works because** the Managed Service for Apache Flink (MSF) runtime provides only core Flink and the **FileSystem connector**. Use the Maven shade `ServicesResourceTransformer` so connector SPI files do not clash in the uber JAR.

Verified from AWS docs on 2026-11-02 (MSF developer guide: how it works, scaling, quotas, release version list, Flink 2.2/2.3 pages, in-place upgrades, Flink 2.2 upgrade guide, Studio pages, deploy-as-application, maintenance, dashboard, best practices, API ApplicationDetail; KDA for SQL discontinuation page; rename announcement 30 Aug 2023; MSF pricing page).
Unconfirmed (verify): DEFAULT ParallelismConfiguration values; PyFlink run-options key names; exact Studio Zeppelin version label (docs table shows "0.1", likely 0.10); connector 2.x availability changes over time.

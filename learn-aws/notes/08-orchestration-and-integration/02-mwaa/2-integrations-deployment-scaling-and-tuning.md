# Amazon MWAA – 2. Integrations, DAG deployment, dependencies, scaling and tuning

Short notes. Each point is a fact you can be asked about.

## A. The S3 bucket and what goes in it
- You own one **S3 bucket per environment** (it can be shared by environments **(verify)**). It holds:
  - `dags/` – your DAG files (`.py`) and helper modules.
  - `plugins.zip` – custom operators, hooks, sensors, macros, and (for v2) plugins.
  - `requirements.txt` – extra Python packages.
  - `startup.sh` (any name, `.sh`) – optional startup script.
- Bucket rules: **Block all public access ON**, **Versioning ON**, **same Region** as the environment. The bucket name cannot be changed after creation.
- **Versioning matters**: for `plugins.zip`, `requirements.txt` and the startup script you pick the **S3 object version ID** when you update the environment. An update with a new file but an old version ID changes nothing.
- **DAGs are different**: MWAA **syncs the `dags/` folder continuously** (the scheduler re-scans); no environment update is needed for a DAG change. The scan interval is `dag_dir_list_interval` / `dag_processor.refresh_interval` (default **300 s**), and a changed file is re-parsed every `min_file_process_interval` (default **30 s**).
- Changes to **`requirements.txt`, `plugins.zip`, startup script, Airflow config or class** need an **environment update** (about **10–30 minutes**, rolling restart of components).
- Optional S3 encryption: **SSE-S3** or **SSE-KMS**. If you use your own KMS key for the bucket, it **must be the same key** used for the environment. KMS **aliases and multi-Region keys are not supported**.
- S3 **Object Lock** is optional.
- The execution role needs `s3:GetObject*`, `s3:GetBucket*`, `s3:List*` on the bucket (and `s3:GetAccountPublicAccessBlock` when the account blocks public access).

## B. Deploying DAGs (patterns)
- **CI/CD**: GitHub/CodePipeline → test (lint, `airflow dags list`, unit tests) → `aws s3 sync dags/ s3://bucket/dags/ --delete` → optional Airflow REST API smoke test.
- Use **`aws-mwaa-local-runner` / `aws-mwaa-docker-images`** to run an environment copy locally and test DAGs, `plugins.zip` and `requirements.txt` before upload.
- Use **separate environments** (dev / staging / prod) with the same pipeline; promote by copying the DAG bundle.
- **Do not edit DAGs in place in production S3**; deploy via pipeline so version history is clean (S3 versioning gives rollback).
- **Rollback**: re-upload the previous S3 object version (DAG files), or point to the previous version ID for `requirements.txt`/`plugins.zip`.
- **Airflow 3** adds **DAG versioning**, so a run keeps the DAG version it started with even if you push new code **(verify MWAA support)**.
- DAG file naming: avoid very large DAG files; split into modules. Files without the strings `airflow` and `dag` are skipped by "safe mode" parsing.
- Keep DAG code **fast to import**: heavy imports, DB/API calls at top level, and `Variable.get()` at top level slow parsing and hit the metadata DB and Secrets Manager repeatedly.

## C. Python dependencies
- Install extra packages with **`requirements.txt`**. MWAA runs `pip3 install -r requirements.txt` on **scheduler and every worker** (and web server for 2.2.2+).
- Always add a **constraints line** at the top: `--constraint "https://raw.githubusercontent.com/apache/airflow/constraints-<AIRFLOW_VERSION>/constraints-<PYTHON_VERSION>.txt"`. It is **required from Airflow 2.7.2** (MWAA adds one if you do not).
- **Pin versions** (`==`). Unpinned packages pull the latest and may conflict.
- If a dependency conflicts with the constraints, **`pip install` fails** and the update **rolls back**. Check the `requirements_install_ip` log stream in the **scheduler log group**.
- Recommended total size of libraries **< 1 GB**. If installation takes more than **10 minutes**, the Fargate task times out and MWAA rolls the environment back.
- Sources: **PyPI**, **wheel files** (`.whl` in `plugins.zip`), or a **private PEP-503 repo** (credentials via the startup script as environment variables, or CodeArtifact).
- A **private web server (no internet)** cannot reach PyPI: provide wheels in `plugins.zip` or use a private repo reachable inside the VPC. Packages installed on the web server must be reachable **from the web server's network**.
- **Provider packages** such as `apache-airflow-providers-amazon` are preinstalled; upgrade them via `requirements.txt` with the matching constraint (or a newer provider and a custom constraint **(verify)**).
- **`plugins.zip`**: a zip with custom operators/hooks/sensors in a folder structure; `.so`/wheels allowed. Re-zip and upload a **new S3 version**, then select the version in the environment.
- **Startup script (`startup.sh`)**: runs on **each component** (scheduler, worker, web server) **before** `requirements` install and before Airflow starts. Use it to:
  - install **Linux packages** (`sudo yum install …`), but **exclude Python** from `yum update` (`--exclude=python*`);
  - set **environment variables** (not reserved ones);
  - fetch tokens for private package repos.
- Component name is in `MWAA_AIRFLOW_COMPONENT` (`scheduler`, `worker`, `webserver`). Logs are in the `startup_script_execution_ip` stream.
- **Reserved environment variables** (for example `AIRFLOW_HOME`, `AIRFLOW__CORE__EXECUTOR`, `AIRFLOW__CELERY__WORKER_AUTOSCALE`, `SQL_ALCHEMY_CONN`) are reset by MWAA if you override them. You cannot change the **Python version**.
- Startup script needs the **S3 version ID** (like requirements and plugins).

## D. Airflow configuration options
- Set Airflow settings in **Airflow configuration options** on the environment (equivalent of `airflow.cfg`). Examples: `celery.worker_autoscale`, `core.default_task_retries`, `scheduler.catchup_by_default`, `webserver.default_ui_timezone`, `metrics.metrics_allow_list`.
- These **override** the same keys in an `airflow.cfg`.
- Some options are **MWAA-controlled** and ignored/overridden (`celery.worker_concurrency`, executor, broker, DB connection).
- Changing configuration options triggers an **environment update**.
- You can also set **environment variables** via the startup script.

## E. Connecting to AWS services from DAGs
- Operators come from `apache-airflow-providers-amazon`: `GlueJobOperator`, `GlueCrawlerOperator`, `EmrAddStepsOperator`/`EmrServerless…`, `AthenaOperator`, `RedshiftDataOperator`, `S3…Operator`, `LambdaInvokeFunctionOperator`, `BatchOperator`, `EcsRunTaskOperator`, `SageMaker…Operator`, `StepFunctionStartExecutionOperator`, `SnsPublishOperator`, `SqsPublishOperator`.
- **Sensors**: `S3KeySensor`, `GlueJobSensor`, `EmrStepSensor`, `AthenaSensor`, `RedshiftClusterSensor`, `StepFunctionExecutionSensor`.
- **Deferrable** versions (set `deferrable=True`) wait on the **triggerer** and use almost no worker resources.
- **Authentication to AWS**: the **default connection `aws_default`** uses the **environment's execution role**. No keys needed. All DAGs share this role.
- To use another role: create an Airflow **connection** with `role_arn` in extras (the execution role assumes it) or use per-task `aws_conn_id`.
- **Least privilege**: because all DAGs share one execution role (in the classic product), add only the actions your DAGs need and consider **separate environments** for different trust zones.
- Operators call APIs from **workers inside your VPC**, so the VPC needs a path to the AWS service (NAT or VPC endpoints).
- Cross-account access: execution role assumes a role in the other account.
- Anti-pattern: doing heavy processing **inside Airflow workers** (pandas on large data). Use Airflow to **trigger** Glue/EMR/Athena/Redshift/Batch and wait (ideally deferrable).
- Passing data: use **XCom for small values** (IDs, S3 keys). Large XComs bloat the metadata DB and slow the scheduler. Custom XCom backends (S3) exist **(verify support)**.
- **Dataset/Asset-driven scheduling** triggers a DAG when an upstream DAG updates an asset. Metrics `dataset.updates` etc. (2.6.3+).

## F. Secrets and connections
- Store **connections and variables** in the Airflow metadata DB (UI/CLI) **or** a **secrets backend**.
- **Secrets Manager backend** (recommended): set `secrets.backend = airflow.providers.amazon.aws.secrets.secrets_manager.SecretsManagerBackend` and `secrets.backend_kwargs = {"connections_prefix":"airflow/connections","variables_prefix":"airflow/variables"}`.
- Secret names then look like `airflow/connections/<conn_id>` and `airflow/variables/<var_name>`. A connection secret is a **URI string** (or JSON); variable secrets are plain text.
- **Systems Manager Parameter Store** is also supported as a backend.
- Execution role needs `secretsmanager:GetSecretValue` (and `ListSecrets`, optionally `DescribeSecret`) on the secrets (and `kms:Decrypt` if encrypted with a CMK).
- Use **lookup patterns** (`connections_lookup_pattern`, `variables_lookup_pattern`, provider ≥ 7.3.0) to cut API calls and cost: Airflow otherwise checks the backend for every lookup.
- Lookup order: **secrets backend first**, then environment variables, then the metadata DB.
- **Do not hard-code secrets** in DAGs or `requirements.txt`. Do not put quotes around values in the connection secret.
- Each secret and each API call has a **cost**; frequent top-level `Variable.get()` multiplies calls on every parse.

## G. Worker autoscaling
- MWAA scales **Celery workers** between **min** and **max** workers (defaults 1–10 for max 10; max up to **25** by default). **mw1.micro** does not autoscale.
- Formula: `(running tasks + queued tasks) / tasks-per-worker = workers needed`, from the `RunningTasks` and `QueuedTasks` metrics.
- Scale-out adds Fargate worker containers up to **max workers**. Scale-in happens when load falls; **workers still running tasks are protected** until they finish. Tasks can queue while workers scale in.
- If a worker gets a **new task during scale-in**, MWAA keeps it.
- Scale-out takes **a few minutes** (new container start), so very bursty DAGs queue briefly. Set **min workers** higher to keep capacity warm (costs more).
- `aws mwaa update-environment --max-workers 10 --min-workers 10 --name <env>` sets both.
- Tasks per worker defaults by class: micro 3, small 5, medium 10, large 20, xlarge 40, 2xlarge 80. Tune with `celery.worker_autoscale = max,min`.
- **Lower `worker_autoscale`** for memory-heavy tasks (a worker accepts up to `max` tasks even if memory is short; tasks then fail with OOM).
- **Raise `worker_autoscale`** for light I/O tasks (API calls, triggering jobs).
- **Stranded tasks**: Airflow may think tasks are still running; clear them in the UI (Mark failed / Clear).
- **Schedulers**: 2–5; more schedulers (and triggerers) improve throughput for many DAGs/deferred tasks; more cost.

## H. Performance tuning checklist
- **Keep top-level DAG code light**: no network or DB calls, no heavy imports. Heavy work belongs inside tasks.
- **Fewer, smaller DAG files**; dynamic DAGs generated in one file count as one parse but can be slow.
- Increase `min_file_process_interval` and `dag_dir_list_interval` to **cut scheduler CPU** if you have many files (trade-off: slower pick-up of changes).
- Decrease `scheduler.max_dagruns_to_create_per_loop` to leave capacity for scheduling tasks (default 10).
- `scheduler.parsing_processes` default is `(2 × vCPU) − 1`; must stay within the class (small: ≤1 other thread, medium: ≤3, large: ≤7).
- Increase `dagbag_import_timeout` (default 30 s) and `dag_file_processor_timeout` (default 50 s) if big DAG files time out (`ImportErrors`, `ProcessorTimeouts`). `dagbag_import_timeout` must be **smaller** than the processor timeout.
- `core.parallelism`: global ceiling on task instances (MWAA sets a high dynamic default); real limits come from workers, `worker_autoscale`, **pools** and `max_active_tasks_per_dag` (default 16; was `dag_concurrency` before 2.2).
- Use **pools** to limit concurrency to a database/API; use `max_active_runs` to stop DAG-run pile-ups.
- `celery.sync_parallelism` default **1** (avoids log delivery errors).
- Raise `min_serialized_dag_update_interval` for large DAG counts to reduce DB load.
- Use **reschedule/deferrable sensors**, smart timeouts, and `execution_timeout` so tasks cannot hang forever.
- Use **retries with exponential backoff** (`retries`, `retry_delay`, `retry_exponential_backoff`).
- Set **`catchup=False`** unless you really need backfill, or a new DAG with an old `start_date` floods the scheduler.
- Avoid XCom for big data; avoid very large DAGs (thousands of tasks in one DAG slow UI and scheduler).
- Clean old metadata (DAG runs, task instances, logs) with a **maintenance DAG** (`airflow db clean` style) to keep the DB fast and storage cost low.

## I. Operating tasks
- **Trigger a DAG**: UI, Airflow REST API (`InvokeRestApi`), Airflow CLI via CLI token (`trigger_dag`), or an upstream event (EventBridge → Lambda → API).
- **CLI**: get a token with `airflow:CreateCliToken`, then POST commands to the environment's CLI endpoint. Only a **subset** of Airflow CLI commands is allowed.
- **REST API**: `airflow:InvokeRestApi` on the Airflow role ARN (Admin/Op/User/Viewer/Public). Works for private web servers over the public MWAA API endpoint unless confined by `aws:SourceVpc`/`aws:SourceVpce`.
- **Environment lifecycle**: create (about 20–30 min), update (10–30 min), delete. Environment updates run as a **rolling replacement**; DAGs keep running but tasks can be interrupted on container swap.
- **Maintenance windows**: AWS patches the underlying images; minor versions are patched automatically within the same Airflow version **(verify)**.
- **Backups**: the **metadata DB is not directly backed up for you**; export DAG runs/variables/connections with a DAG or CLI as needed. Keep DAG code in Git and S3 versioning.
- **Migration** to a new environment (version upgrade across majors): follow the MWAA migration guide; use the **metadata export/import DAGs**.

## J. Exam skills mapping
- **1.1.5 Set up schedulers (EventBridge, Airflow, time-based) for jobs and crawlers**: cron and data-aware schedules, sensors.
- **1.3.1 Orchestrate ETL (Lambda, EventBridge, MWAA, Step Functions, Glue workflows)**: provider operators.
- **3.1.1 Orchestrate pipelines (MWAA, Step Functions)**: S3 deploy, requirements and plugins versions, autoscaling.
- **3.1.2 Troubleshoot managed workflows**: DAG import and scheduler issues.
- **3.1.3 Call SDKs from code**: calling AWS from DAGs.
- **4.2.2 Store credentials (Secrets Manager, Parameter Store)**: Secrets Manager backend.

## K. Scenarios: "If X → Y, because Z"
- **If** a **DAG change must go live fast**, **then** just upload the `.py` file to the `dags/` folder of the **Amazon S3** bucket. **This works because** MWAA **syncs `dags/` continuously**: the scheduler rescans the folder (default every **300 s**) and re-parses changed files, so **no environment update** is needed. Deploy through a CI/CD pipeline rather than editing production S3 by hand.
- **If** a **new Python package** must be available, **then** add it to `requirements.txt` (pinned with `==`, with the `--constraint` line at the top), upload it to S3, and **choose the new S3 object version ID** in the environment. **This works because** the bucket has **versioning on** and MWAA installs only the version ID you select; a new file with the old version ID changes nothing. The **environment update** takes about **10–30 minutes**.
- **If** the environment update **rolls back** after you change `requirements.txt`, **then** read the `requirements_install_ip` log stream in the scheduler's **Amazon CloudWatch** log group. **This works because** a rollback means `pip install` failed: a package **conflicts with the constraints file**, or the install took more than **10 minutes** and the Fargate task timed out. Keep libraries under **1 GB** in total.
- **If** the web server is **private (no internet)** and packages fail to install, **then** ship them as **wheel files** inside `plugins.zip`, or use a **private repository** reachable inside the Virtual Private Cloud (VPC). **This works because** a private web server **cannot reach the Python Package Index (PyPI)**, and packages installed on the web server must be reachable from its network.
- **If** you must install a **Linux library** (for example a database client), **then** use a **startup script** (`startup.sh`) that runs `sudo yum install`. **This works because** the script runs on **every component** (scheduler, worker, web server) **before** requirements install and before Airflow starts. Exclude Python from `yum update` (`--exclude=python*`), and select the script's S3 version ID like other files.
- **If** tasks are **queued while workers are still below max**, **then** wait for **autoscaling** (a few minutes) or **raise min workers** to keep capacity warm. **This works because** MWAA adds **AWS Fargate** worker containers only when `(running + queued tasks) / tasks per worker` needs them, and each new container takes minutes to start (verify). Higher min workers removes the wait but costs more.
- **If** **memory-heavy tasks fail** with out-of-memory (OOM) errors, **then** **lower the max** in `celery.worker_autoscale` or move to a **bigger environment class**. **This works because** each worker accepts up to `max` tasks **regardless of free memory**, so too many big tasks share one worker and get killed. Fewer tasks per worker, or bigger workers, gives each task more memory.
- **If** the **scheduler is slow with 500 DAG files**, **then** raise `min_file_process_interval` and `dag_dir_list_interval`, keep **top-level DAG code light**, **add schedulers** (up to **5**) or move to a **bigger class**. **This works because** parsing DAG files uses scheduler CPU, and heavy imports or DB/API calls at the top level run on every parse. The catch: longer intervals mean changes are picked up more slowly.
- **If** **connections must not live in the Airflow metadata database**, **then** use the **AWS Secrets Manager backend** with the `airflow/connections` prefix and **lookup patterns**. **This works because** Airflow reads credentials from Secrets Manager **first**, so they never sit in the DB, and lookup patterns (`connections_lookup_pattern`) stop Airflow calling Secrets Manager for every lookup, which cuts API calls and cost. The execution role needs `secretsmanager:GetSecretValue`.
- **If** a DAG must **wait hours for a file** without holding a worker slot, **then** use `S3KeySensor(deferrable=True)` or `mode="reschedule"`. **This works because** both **free the worker slot** while waiting: reschedule releases it between checks, and deferrable hands the wait to the **triggerer**.
- **If** an **AWS Glue job runs for 3 hours**, **then** start it with `GlueJobOperator(deferrable=True)`, or start it and wait with a `GlueJobSensor` in reschedule mode. **This works because** neither holds a worker slot for 3 hours: the heavy work runs in Glue, and Airflow only waits cheaply. Do not do heavy processing inside Airflow workers.
- **If** teams need **different AWS permissions per pipeline**, **then** use **separate MWAA environments**, or Airflow **connections** with a `role_arn` that the execution role assumes. **This works because** all DAGs in one environment share **one execution role** through the `aws_default` connection, so separate roles or environments are the way to split permissions.
- **If** you must **trigger a DAG when a file lands in S3**, **then** use an **Amazon EventBridge** rule → **AWS Lambda** → the **Airflow REST API** (`InvokeRestApi`), or let an Airflow S3 sensor wait for the file. **This works because** MWAA has **no native event trigger**; DAGs start on a schedule, from the UI, or through the REST API or CLI.
- **If** a DAG with an **old `start_date` floods the scheduler**, **then** set `catchup=False`. **This works because** with catch-up on, Airflow creates a run for **every missed interval** since `start_date`.

Verified from AWS docs on 2026-11-03 (environment class, autoscaling, performance tuning, dependencies, startup script, Secrets Manager backend, S3 bucket, access policies).
Unconfirmed (verify): whether one bucket can serve several environments; the current DAG-folder scan defaults on MWAA for Airflow 3; Airflow 3 DAG versioning on MWAA; custom S3 XCom backend support; whether provider upgrades beyond the constraint file are supported; scale-out latency; maintenance-window behaviour; metadata DB backup options; CLI command subset.

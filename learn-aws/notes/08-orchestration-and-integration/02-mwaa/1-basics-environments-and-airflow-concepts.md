# Amazon MWAA – 1. Basics, environments and Airflow concepts

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **Amazon Managed Workflows for Apache Airflow (MWAA)** runs **Apache Airflow** for you. AWS manages the scheduler, workers, web server, metadata database and patching. You provide **DAGs** (Python code) in S3.
- You still pick the **environment class**, **max workers**, **Airflow version**, **VPC**, and you own the **DAG code and dependencies**.
- It is **not serverless** in the classic form: an environment is **always on** and billed per hour even when no DAG runs.
- A newer option, **MWAA Serverless**, is a different product (section H) **(verify)**.
- Pick MWAA when:
  - You already use **Airflow** or need Python DAGs, **backfill/catch-up**, complex dependencies, sensors, SLAs, a rich UI and a huge operator/provider ecosystem.
  - You orchestrate **many tools** (Glue, EMR, Redshift, Athena, dbt, Spark, SaaS, on-prem) in one place.
  - You are **migrating** from self-managed Airflow.
- Avoid it when:
  - Workflows are small, AWS-only, event-driven → **Step Functions** (serverless, pay per use).
  - You only chain Glue jobs/crawlers → **Glue workflows**.
  - You need a very cheap, occasional scheduler → **EventBridge Scheduler** (+ Lambda/Step Functions).
  - You cannot afford an always-on environment.
- Data-engineering uses: nightly ETL DAGs, Glue/EMR/Redshift orchestration, dbt runs, ML retraining schedules, backfills, cross-system dependencies.
- DEA-C01 touchpoints: **1.1.5 schedulers** (Airflow), **1.3.1 orchestrate ETL**, **3.1.1 orchestrate pipelines (MWAA, Step Functions)**.

## B. Airflow core concepts (needed for the exam)
- **DAG** (Directed Acyclic Graph): a workflow defined in Python. Tasks have dependencies; no loops.
- **Task**: one unit of work. A **task instance** is one run of a task for one DAG run.
- **Operator**: a template for a task (`GlueJobOperator`, `S3KeySensor`, `PythonOperator`).
- **Sensor**: an operator that **waits** for a condition (file arrives, job done). Modes: `poke` (holds a worker slot) or `reschedule` (frees the slot between checks).
- **Deferrable operator** + **triggerer**: waits asynchronously and **frees the worker slot**. MWAA runs the **triggerer next to the scheduler**; more schedulers = more triggerers.
- **Hook**: a connector to an external system. **Connection**: stored credentials/endpoint for a hook. **Variable**: stored key/value.
- **XCom**: small data passed between tasks (stored in the metadata DB). Keep it **small**; pass S3 paths, not data.
- **Pool**: limits how many tasks of a type run at once (protect a database).
- **Schedule**: cron, preset (`@daily`), timetable, or **Dataset/Asset**-based (data-aware scheduling).
- **DAG run**: one execution of a DAG for a **logical date / data interval**.
- **Catchup / backfill**: Airflow can run missed intervals. Step Functions has no equivalent.
- **Executor**: MWAA uses the **Celery executor**. Workers pull tasks from an **SQS queue** owned by MWAA.
- **Airflow 3** changes: new UI, **DAG versioning**, task execution API, "assets" replace datasets, `core.dag_concurrency` removed, some old operators/APIs removed.
- **Task SDK / providers**: AWS integrations come from the `apache-airflow-providers-amazon` package (preinstalled; version tied to Airflow version).

## C. Architecture of an MWAA environment
- **Scheduler(s)**: parse DAGs, create DAG runs, queue tasks. Run in AWS-managed **Fargate** containers.
- **Workers**: run tasks (Celery). **Fargate** containers; autoscale between min and max.
- **Web server**: Airflow UI. Public or private access mode.
- **Metadata database**: **Amazon Aurora PostgreSQL**, managed by AWS, in AWS's account. You cannot connect to it directly.
- **Triggerer**: handles deferred tasks, co-located with the scheduler container.
- **Amazon SQS queue**: managed by MWAA; carries tasks from schedulers to workers (`airflow-celery-*`).
- **Amazon S3 bucket (yours)**: stores `dags/`, `plugins.zip`, `requirements.txt`, startup script.
- **CloudWatch**: logs and metrics.
- **VPC**: schedulers/workers/web server get ENIs in **your two private subnets**; the web server gets a VPC interface endpoint when private.
- Components are created in **two AZs** for availability; MWAA replaces failed containers.
- The environment lives in a **Region**; DAG code in S3 must be in the **same Region**.

## D. Environment classes (the numbers)
| Class | DAG capacity | Default concurrent tasks (per worker) | Worker size | Notes |
|---|---|---|---|---|
| **mw1.micro** | up to 25 | 3 | 1 vCPU / 3 GB | **No autoscaling**; 1 scheduler |
| **mw1.small** | up to 50 | 5 | 1 vCPU / 2 GB | |
| **mw1.medium** | up to 250 | 10 | 2 vCPU / 4 GB | |
| **mw1.large** | up to 1,000 | 20 | 4 vCPU / 8 GB | |
| **mw1.xlarge** | up to 2,000 | 40 | 8 vCPU / 24 GB | |
| **mw1.2xlarge** | up to 4,000 | 80 | 16 vCPU / 48 GB | |
- **DAG capacity** = number of DAG definitions, assuming dynamic DAGs in a single file written with best practices.
- The class sets worker/scheduler size, web server size and database size. Bigger class = more tasks per worker and more DAG capacity.
- **Workers**: default **10**, min **1**, max **25** (default console cap; more by support request **(verify)**).
- **Schedulers**: default **2**, range **2–5** (mw1.micro has **1**). More schedulers = faster scheduling of many DAGs and more triggerers.
- **Web servers**: scale with the class; extra web servers are billed hourly **(verify)**.
- Concurrency maths: `required workers = (running + queued tasks) / tasks per worker`.
- `celery.worker_autoscale` (max,min) changes **tasks per worker** (for example `5,5`). Raise it for lightweight tasks; lower it for memory-heavy tasks.
- Changing the class or workers triggers an environment **update** (tens of minutes; environment stays available but changes apply gradually).
- **You cannot downsize below the DAG/task need**: too small a class gives slow DAG parsing, scheduler lag and OOM-killed tasks.

## E. Airflow versions and lifecycle
- MWAA bundles an **Airflow image** (Airflow + Python + common libraries). The environment keeps its version until you upgrade it.
- Supported lines in the docs: **2.7.2, 2.8.1, 2.9.2, 2.10.1, 2.10.3, 2.11.x, 3.0.6, 3.2.1, 3.3.1** (Python **3.11** for 2.7–2.10, **3.12** for 2.11 and 3.x) **(verify the list; it changes monthly)**.
- If you do not specify a version, you get the **latest** supported one.
- MWAA commits to support **at least three minor versions** at a time, and each version for **at least 12 months**, with **180 days' notice** before end of support.
- **End of support**: 2.4.3, 2.5.1, 2.6.3 reached end of support on **30 Dec 2025**. After the date you cannot create/upgrade to that version; existing environments keep running **unsupported**.
- **Upgrades**: in-place **minor** upgrades (for example 2.9 → 2.10 → 2.11) are supported. **Major** jumps (2.x → 3.x) are **not in-place**; use the migration guide (new environment + metadata/DAG migration) **(verify)**.
- **Downgrades**: allowed to an earlier **supported minor** of the same major.
- From Airflow **2.7.2**, `requirements.txt` must contain a **`--constraint`** line, or MWAA adds one for you.
- Airflow versions before **2.2.2** could not install requirements/plugins on the web server; newer ones can.
- `Airflow 3` environments do not support **multi-team mode**.
- Test upgrades with the **`aws-mwaa-local-runner`** (Docker) or a **staging environment** before production.

## F. Where MWAA sits vs alternatives
| Need | MWAA | Step Functions | Glue workflows | EventBridge Scheduler |
|---|---|---|---|---|
| Authoring | Python DAGs | JSON/ASL (or CDK) | Console triggers | Cron/rate |
| Billing | **Hourly** (always on) | Per transition/request | Free orchestration | Per invocation |
| Backfill / catch-up | **Yes** | No | No | No |
| Long waits | Yes (use deferrable/reschedule) | Up to 1 year, free waiting | Limited | n/a |
| AWS service integration | Providers/operators | 200+ SDK integrations | Glue only | Targets |
| Operations | You manage DAG deploys, deps, upgrades | None | None | None |
| Best for | Complex, multi-tool, Airflow shops | AWS-native serverless flows | Glue-only chains | Simple schedules |
- **Rule of thumb**: if the question says "existing Airflow", "Python DAG", "backfill" or "many third-party operators" → **MWAA**. If it says "serverless", "least operational overhead", "AWS services only" → **Step Functions**.
- **MWAA can start Step Functions** executions (`StepFunctionStartExecutionOperator`) and the reverse (Step Functions can trigger MWAA via the REST API or Lambda).
- **Self-managed Airflow** on EC2/EKS: more control (plugins, executors, versions) and cheaper at scale, but you patch and operate it.
- **Glue workflows** are free but only orchestrate **Glue** jobs, crawlers and triggers.

## G. Key limits and defaults (summary)
- Environment name: **1–80** characters **(verify)**.
- **2 private subnets** in **2 AZs** are required; up to **5 security groups**.
- DAG capacity, workers and schedulers depend on the class (section D).
- The S3 bucket must have **versioning on** and **block public access on**, and be in the **same Region**.
- Environment creation takes about **20–30 minutes**; updates take a similar time.
- Airflow **REST API** and **CLI** are available through MWAA-issued tokens (file 3).
- Max task run time is set by Airflow config (`execution_timeout`); there is **no 15-minute cap** like Lambda, but long tasks hold a worker slot.

## H. MWAA Serverless (new option) – verify details
- Announced **Nov 2025** as a **serverless deployment option** for Airflow workflows **(verify GA status and Regions)**.
- Workflows can be defined in **YAML** (with a tool to convert Python DAGs) and Python is still supported; **80+ AWS operators** **(verify)**.
- **No Airflow web UI**; you monitor with **CloudWatch** and **CloudTrail**.
- **Per-workflow IAM role and VPC** selection gives stronger task isolation.
- **Pricing**: pay **per AWS-managed task, by duration**, one-second resolution with a **1-minute minimum**; example **$0.080 per task-hour** (us-east-1). **No idle environment cost.**
- Good for **low-to-medium, spiky** workloads; very heavy, constantly running workloads may be cheaper on a **provisioned environment**.
- Compute for your code must come from services such as **Lambda, Batch, Glue**; tasks are provisioned per run, so expect some **start-up delay**.
- Exam note: the DEA-C01 guide still says "MWAA" (provisioned). Know that a serverless option exists, but answer from the provisioned model unless the question says otherwise.

## I. Exam skills mapping
- **1.1.5 Set up schedulers (EventBridge, Airflow, time-based) for jobs and crawlers**: Airflow schedules.
- **1.3.1 Orchestrate ETL (Lambda, EventBridge, MWAA, Step Functions, Glue workflows)**: MWAA vs Step Functions vs Glue workflows.
- **3.1.1 Orchestrate pipelines (MWAA, Step Functions)**: operating MWAA.

## J. Scenarios: "If X → Y, because Z"
- If the team already has hundreds of Airflow DAGs → **MWAA**, because DAGs run with little change and MWAA removes cluster operations.
- If the workflow is a few AWS service calls triggered by events → **Step Functions**, because it is serverless and has no idle cost.
- If you need to rerun last month's missed runs → **Airflow backfill/catch-up on MWAA**, because Step Functions has no backfill concept.
- If the environment costs too much with little use → **right-size (mw1.small), cut min workers, or move light flows to Step Functions/Serverless**, because the environment is billed hourly even when idle.
- If a sensor wastes worker slots → **use `mode="reschedule"` or a deferrable operator**, because `poke` mode holds a slot while waiting.
- If tasks are queued while workers are idle → **check pools, `celery.worker_autoscale`, and max workers**, because concurrency limits, not capacity, may be the cause.
- If you cannot see DAGs → **check S3 path, parse errors (`ImportErrors`), and DAG file size/time**, because the scheduler only lists DAGs it parsed successfully.
- If you must upgrade from Airflow 2.x to 3.x → **create a new environment and migrate**, because major upgrades are not in-place **(verify)**.
- If the Airflow version is near end of support → **plan the upgrade now**, because after end of support you cannot create or move to it and get no technical support.
- If you want to run an Airflow job from a Step Functions flow → **call the Airflow REST API (InvokeRestApi) from Lambda/HTTP Task**, because Step Functions has no native MWAA task.

Verified from AWS docs on 2026-11-03 (environment classes, Airflow versions, networking, pricing, autoscaling, execution role, access policies, S3 bucket, CloudWatch metrics).
Unconfirmed (verify): MWAA Serverless GA status, definition format, operator count, Regions and price; whether a bucket name prefix `airflow-` is still required; max workers above 25 by request; environment name length; in-place upgrade path from 2.x to 3.x; web server count/billing; creation/update times; Airflow 3 feature list.

# Glue – 4. Triggers, workflows, Data Quality and DataBrew

Short notes. Each point is a fact you can be asked about.

## A. Triggers (the start button inside Glue)
- A **trigger** starts **jobs and/or crawlers**. It fires **on demand**, **on a schedule**, or **when other jobs or crawlers finish**.
- Three trigger types:
  - **Scheduled**: time-based, written as a **cron** expression (daily, weekly, custom).
  - **Conditional**: watches one or more **jobs and crawlers** and fires when they reach a state. You choose **ANY** or **ALL** of the watched events.
  - **On-demand**: fires when you start it by hand (console, API, CLI). It **stays in CREATED** state forever. It never becomes ACTIVATED or DEACTIVATED.
- EventBridge-based start exists **for workflows** (see section B), not as a standalone Glue trigger type.
- **Trigger states**: `CREATED`, `ACTIVATED`, `DEACTIVATED` (plus transitional states like ACTIVATING). Deactivate to pause a schedule without deleting it. Scheduled and conditional triggers can be **activated on creation** with a flag.
- **States a conditional trigger can watch**:
  - Jobs: `SUCCEEDED`, `STOPPED`, `FAILED`, `TIMEOUT`.
  - Crawlers: `SUCCEEDED`, `FAILED`, `CANCELLED`.
- Example: T1 starts job J3 when **both** J1 and J2 **succeed**; T2 starts J4 if **either** J1 or J2 **fails** (notification or cleanup job).
- **Dependent jobs** (started by a conditional trigger) only run if the watched job was itself **started by a trigger**. A whole chain must descend from **one scheduled or on-demand trigger**. A watched job started by hand will **not** fire the conditional trigger.
- A trigger can pass **arguments** (job parameters), a timeout, security configuration and so on to every job it starts. A passed key that matches a default argument **overrides** it. Non-overridable arguments are ignored.
- Limits: **only 2 crawlers** can be started by one trigger (use several include paths in one crawler instead). Default quota **50 jobs per trigger**, **1,000 triggers per account**.
- Cron cautions: "day 31" skips short months. Keep schedules in UTC. Minimum interval is about **5 minutes** **(verify)**.
- Other ways to schedule Glue (exam skill 1.1.5): **EventBridge Scheduler / rules** (call `StartJobRun`, start a workflow, start Step Functions), **MWAA** (Airflow schedule), **crawler's own schedule**, and **Step Functions** after another event.

## B. Workflows (a visual chain of Glue jobs, crawlers and triggers)
- A **workflow** groups **triggers, jobs and crawlers** into one run that you can **start, monitor and visualize as a graph**.
- It records progress and status per node and overall. Good for "crawl → transform → crawl → notify" inside Glue.
- Every workflow has one **start trigger**. Types: **Schedule**, **On demand**, **EventBridge event**.
- **EventBridge event start**:
  - Any EventBridge event can start a workflow. Typical case: **S3 object created** (`PutObject`).
  - **Batch conditions**: **batch size** (number of events) and optional **batch window** (seconds). Whichever is met **first** starts the run.
  - Default batch size **1** (start on the first event). Default and **maximum batch window = 900 seconds (15 minutes)**. The window starts when the **first event arrives**.
  - After the workflow starts, batch conditions reset and the trigger watches for the next batch.
- You can set **maximum concurrent workflow runs** at creation. A run that would exceed the limit is **not started**, and Glue **does not retry** it.
- If an event (or batch) starts a run that **fails**, that event is **not reused**. The next run starts only when a **new** event or batch arrives.
- **Workflow run properties**: name-value pairs shared by every job in the run. Jobs can **read and change** them through the API to pass state to later jobs (for example, the partition just loaded).
- **Static view vs dynamic view**: the static view is the **design**. The dynamic view is a **runtime graph** with the latest run status (success, error details) for each node. The console shows the dynamic view while running.
- **Limit**: keep **jobs + crawlers + triggers in one workflow at 100 or fewer**. Above that, resume or stop-run actions may fail.
- **Blueprints**: parameterized **templates** that create workflows. You write a blueprint (Python script + layout), register it, then create a workflow by giving parameters. AWS-provided examples include importing data from S3 or JDBC into S3 and converting formats/compaction **(verify list)**.
- Create a workflow: by **blueprint** (generated) or **manually** (add triggers, then jobs/crawlers) in the console or API.
- You can **resume or restart a failed run** from the failed nodes **(verify exact feature name)**.
- Workflows do **not** orchestrate other AWS services. For Lambda, Athena, EMR, SNS, approvals and branching on data → Step Functions or MWAA.
- Quota **1,000 workflows** per account (default).

## C. Choosing the orchestrator (exam skill 1.3.1)
- **Glue workflows**: pure Glue pipelines (crawler + jobs). Built-in graph. Least extra setup. No cost to model the chain **(verify)**. Weak on branching and other services.
- **Step Functions**: serverless state machine. Integrates Glue (`startJobRun.sync` waits for completion), Athena, EMR, Lambda, Batch, SNS, SQS, DynamoDB and 200+ services. Has **retry/catch**, **parallel**, **map**, **choice**, **wait**, **human approval**. Pick it for multi-service, error-handling-heavy ETL.
- **MWAA (managed Airflow)**: pick when the team already uses **Airflow DAGs** or needs very complex dependencies, backfills, and the Python operator ecosystem (Glue job/crawler/Data Quality operators exist). It has a monthly environment cost even when idle.
- **EventBridge**: event routing and **schedules**. Starts a workflow or state machine when something happens (file lands, job state changes).
- **Lambda**: small glue steps (start a job, read bookmark info, send a message). Not an orchestrator for long chains.
- **Rule of thumb**: only Glue → Glue workflow; many services or fine control → Step Functions; existing Airflow → MWAA; event reaction → EventBridge.
- **Notifications and reactions**: Glue sends **EventBridge events** for job state change, crawler state change, Catalog table changes, and Data Quality results. Route to **SNS, Lambda, Step Functions** **(verify exact detail-type names)**.
- A common event pattern: S3 upload → EventBridge → **Glue workflow (batch of events)** → job → crawler → **SNS** on failure.

## D. Glue Data Quality (DQ)
- **Glue Data Quality** measures and monitors data quality with **rules**. It is **serverless** and built on the open-source **Deequ** framework.
- Rules are written in **DQDL (Data Quality Definition Language)**, an open, simple language. **25+ rule types** out of the box.
- Two entry points:
  - **Data Catalog** (for data at rest): evaluate a **table or Athena view**. Console and APIs. For stewards, analysts and governance. Supports **rule recommendations**.
  - **ETL jobs** (for data in motion): evaluate **inside a job** with the **Evaluate Data Quality** transform (Glue Studio, notebooks, scripts). Stop or filter **bad data before** it lands in the lake.
- Comparison to remember:

| Feature | Catalog | ETL job |
|---|---|---|
| Data sources | S3, Redshift, JDBC, Iceberg/Hudi/Delta, Athena views | Anything Glue supports, incl. custom connectors |
| Rule **recommendation** | Yes | No |
| Author and run DQDL | Yes | Yes |
| **Row-level** failed-record identification | **No** | **Yes** |
| Auto Scaling and Flex | No | Yes |
| Incremental DQ | pushdown predicates | **job bookmarks** |
| EventBridge, CloudWatch, S3 results | Yes | Yes |
| ML anomaly detection, dynamic rules | Yes | Yes |

- **Terms**: **rule** (a DQDL expression that returns true/false), **ruleset** (a Glue resource holding rules, tied to a Catalog table, has an ARN), **analyzer** (gathers statistics without pass/fail), **observation** (an unconfirmed insight from statistics over time), **data quality score** (**percent of rules that pass**).
- DQDL example:
  ```
  Rules = [
    RowCount > 0,
    IsComplete "customer_id",
    Uniqueness "order_id" > 0.99,
    ColumnValues "status" in ["NEW","PAID","SHIPPED"],
    DataFreshness "updated_at" <= 1 days
  ]
  ```
- Common rule types **(verify the full list)**: `RowCount`, `IsComplete` / `Completeness`, `IsUnique` / `Uniqueness`, `ColumnValues`, `ColumnLength`, `ColumnExists`, `DistinctValuesCount`, `Mean`, `StandardDeviation`, `Sum`, `Entropy`, `ColumnCorrelation`, `DataFreshness`, `ReferentialIntegrity`, `DatasetMatch`, `SchemaMatch`, `CustomSql`, `AggregateMatch`, `RowCountMatch`, and file rules `FileFreshness`, `FileSize`, `FileUniqueness`, `FileMatch`.
- Newer DQDL features: **dynamic rules** (thresholds from history, e.g. `RowCount > avg(last(10))`), **composite rules** (AND/OR, nested), **`NOT`**, **`where` clause** (filter rows before checking), keywords `NULL`, `EMPTY`, `WHITESPACES_ONLY`, **labels** (group results by team/domain), **constants**, and a **Distribution analyzer**.
- Since March 2024: **`ColumnValues` does not let NULL pass** a comparison.
- **Recommendation runs**: Glue profiles the data and **suggests rules**. Default mode **BASIC**. An **ADVANCED** mode (Amazon Bedrock) uses table metadata and sampled rows **(new, Sept 2026)**.
- **ML anomaly detection** learns from statistics over time and flags unusual values. **Generally available since Aug 2024**. Works in ETL and the Catalog (Catalog use needs evaluation with `ObservationScope = ALL`).
- **Results** can go to: the console, **Amazon S3**, **CloudWatch metrics**, **EventBridge** (to alert or trigger fixes), and **Catalog Iceberg tables** for SQL analysis **(new in 2026)**.
- **Failure actions** in ETL: **fail the job**, **publish metrics only**, or **quarantine failed rows** to a separate output using the **row-level outcomes**. Evaluate Data Quality produces **`ruleOutcomes`** and **`rowLevelOutcomes`** outputs **(verify names)**.
- **Limits**: **2,000 rules** and **65 KB** per ruleset. **100,000 statistics** per account stored for **2 years** (no storage cost). DQ **cannot evaluate nested or list (array) columns**: flatten them first. Concurrency quotas: **50** evaluation runs, **25** recommendation runs, **10** observation runs (defaults).
- **Cost**:
  - **Catalog** runs (recommendation, evaluation): **$0.44 per DPU-hour**, **2 DPU minimum**, **1-minute minimum**.
  - **In ETL jobs**: included in the **job's own DPU cost**, no extra charge. Anomaly detection in ETL has no extra charge.
  - **Anomaly detection in Catalog**: 1 DPU per statistic while detecting/retraining.
- Do DQ checks **early** (at ingestion/landing) and **before publish** (gold). Fail fast on critical rules; log-only on soft rules.
- DQ **at rest** finds problems that already landed. DQ **in the job** prevents them from landing.
- Exam angle: "check completeness/uniqueness/freshness in a pipeline and alert on failure" → **Glue Data Quality + EventBridge → SNS**. "Quarantine bad rows" → **ETL Evaluate Data Quality row-level outcomes**.

## E. Detecting sensitive data (PII) in ETL
- Glue Studio has a **Detect Sensitive Data** (Detect PII) transform. It finds PII (names, emails, card numbers, IDs, and so on) **inside the data** while the job runs.
- Options **(verify details)**: detect in **selected columns** or **all columns**; choose **entity types** (patterns) or use the preset categories; decide how to **act**: **redact** with a fixed string, **hash**, or partially mask; optionally add a detection **column** that lists the entities found.
- Use it **before** writing to a shared or analytics zone. Combine with **Lake Formation** column/cell-level permissions to hide sensitive columns.
- **Amazon Macie** is different: it **scans S3 buckets** to discover PII. Glue's transform acts **during processing**. A common design: Macie finds → tag in Lake Formation → Glue masks.
- **DataBrew** also has PII handling steps (section F).

## F. AWS Glue DataBrew
- **DataBrew** = **visual, no-code data preparation**. Analysts, data scientists and engineers **clean and normalize** data **without writing code**. Serverless. Over **250 built-in transformations** (point-and-click).
- Pick DataBrew when: **non-coders** prepare data, you want quick **profiling** and **visual cleaning**, and the output goes to S3 for ML or analytics.
- Pick **Glue Studio / Spark jobs** when: big, production ETL with code control, complex joins, streaming, or open table formats.
- Core objects **(verify details)**:
  - **Dataset**: the source (S3 files, Catalog tables, databases via JDBC, uploaded files, and other connectors).
  - **Project**: an **interactive workspace** with a **grid view** of a **sample** of your data, value distributions and charts. Billed by **interactive session**.
  - **Recipe**: the **saved list of transformation steps**. Versioned and **reusable** across datasets. You can **publish** versions.
  - **Job**: runs a **recipe** on the **full dataset** and writes output (**recipe job**), or **profiles** it (**profile job**). Can be **scheduled** (cron).
- **Transform examples**: remove nulls, fill missing values, fix schema inconsistencies, change types, split or merge columns, create columns from functions, filter outliers, one-hot encode, scale numbers, text/NLP splits (sentences into phrases).
- Immediate **before/after preview** of a transform on the sample, so you can adjust before running on all data.
- **Data profile jobs** compute **statistics**: row/column counts, missing values, distinct values, **value distributions**, **correlations**, **outliers**, data types. Results appear as **charts**, supporting "visualize and investigate" tasks.
- **Data quality rules** in DataBrew: you define **rules and rulesets** on a dataset (checks such as completeness, value ranges, uniqueness) and **validate** them in a profile job. Failures show in the results. Use to **investigate consistency** across columns **(verify details)**.
- **PII and masking transforms** (examples **(verify)**): **substitute**, **hash**, **shuffle**, **delete**, **encrypt/decrypt** (deterministic or probabilistic), **mask** characters. Helps de-identify before sharing.
- **Output**: S3 (CSV, JSON, Parquet, Avro, ORC, XML and others **(verify list)**), also database targets for some. Prepared data is ready for Athena, Redshift, SageMaker.
- **Data lineage** view shows how the dataset moved through recipe and job **(verify)**.
- **Pricing**: **interactive sessions** about **$1.00 per 30-minute session**. **Jobs** about **$0.48 per node-hour**, billed per **minute**. Prices vary by Region **(pricing page)**.
- **Not** for streaming. **Not** for very custom logic (use Glue ETL).
- **Check current status**: confirm in the docs that DataBrew is still open for new customers and has no end-of-support notice **(verify)**. AWS retires or closes services fairly often.
- Exam angle: "analyst wants to clean and profile data without code, then output Parquet to S3" → **DataBrew**. "Run it daily" → **schedule the DataBrew job** (or Step Functions).

## G. The console screens for these features (UI guide)
- **Triggers**: Glue console → **ETL → Triggers**. Create → choose type (**Schedule**, **Job events**/conditional, **On demand**) → add the **jobs or crawlers** it starts → set **cron** or the **watched jobs and statuses** → activate. Dependency arrows show on the workflow graph.
- **Workflows**: **ETL → Workflows**. Open a workflow to see tabs for the **graph**, **history/runs**, and **settings** **(verify tab names)**.
  - The **graph** shows the **start trigger → jobs/crawlers → next triggers**, with **colors and icons for status** while it runs (dynamic view).
  - Click a node to see its **run details, errors, and logs**.
  - **Run properties** are edited here and via the API.
  - Use **Run** to start on demand, **Stop** and **Resume** for failed runs.
- **Blueprints**: **ETL → Blueprints**. Add blueprint → upload ZIP → **Create workflow** from it by filling parameters.
- **Data Quality (Catalog)**: open a **table → Data quality tab**. Steps: **Create rules** (write DQDL, or **Recommend rules**) → **Run** (choose the IAM role, run type, and workers) → view **score, per-rule pass/fail**, trend over runs, and (optionally) the **EventBridge / CloudWatch** setup.
- **Data Quality (ETL)**: drag an **Evaluate Data Quality** node onto the **visual canvas**; write DQDL in the node; choose **result output** (S3 location, CloudWatch metric publishing), **failure action**, and whether to produce **row-level results**. The job's **Data quality** tab shows results per run.
- **DataBrew console**: **Datasets → Projects → Recipes → Jobs** menus. A **project** opens a **grid** with **Schema**, **Profile**, and **Lineage** views, plus a **recipe panel** that lists steps and lets you **undo or reorder**. **Jobs** list shows runs with status and output links **(verify exact labels)**.
- **Monitoring and alerts**: Glue Studio **Monitoring** page summarizes runs; **CloudWatch** and **EventBridge** carry alarms and events (file 5).

## H. Scenarios (if → then, because)
- **If** a crawler must run after an ETL job succeeds, **then** create a **conditional trigger** that watches the job for **SUCCEEDED** and starts the crawler, or put both in a **Glue workflow**. **This works because** the crawler must see the job's new data, and a conditional trigger fires only when the watched job reaches the chosen state.
- **If** a cleanup job must run when **either** of two jobs fails, **then** use a **conditional trigger** with **ANY** and status **FAILED** on both jobs. **This works because** ANY fires when one of the watched events happens, while ALL waits for all of them.
- **If** a conditional trigger never fires after you started the watched job by hand, **then** this is expected. **This works because** dependent jobs fire only when the watched job was itself **started by a trigger**, so the whole chain must come from one scheduled or on-demand trigger.
- **If** a pipeline must start when a file lands in Amazon S3, **then** send the S3 event to **Amazon EventBridge** and start a **Glue workflow with an EventBridge event start trigger** (or AWS Step Functions). **This works because** the event starts the run directly, so nothing has to poll for new files.
- **If** 10,000 small files land and you want **one** run per 100 events, **then** set the workflow's EventBridge trigger **batch size to 100**, with a **batch window** of up to **900 seconds** (15 minutes). **This works because** Glue collects events and starts a run when the batch size or the window is reached, whichever comes first. The window starts at the first event.
- **If** a pipeline mixes Glue with Amazon Athena, AWS Lambda and a human approval step, **then** use **AWS Step Functions**, a serverless state machine. **This works because** Glue workflows only chain Glue jobs, crawlers and triggers, while Step Functions calls 200+ services and has retry/catch, choice, parallel and approval steps. It can wait for a Glue job with `startJobRun.sync`.
- **If** the team already runs Apache Airflow DAGs, **then** use **Amazon Managed Workflows for Apache Airflow (MWAA)**. **This works because** the team keeps its DAG tooling, and Airflow operators for Glue jobs, crawlers and Data Quality exist. Catch: MWAA has a monthly environment cost even when idle.
- **If** a pipeline is only crawler → job → crawler inside Glue, **then** use a **Glue workflow**. **This works because** it is the simplest option with the least extra setup, and it gives a built-in graph with the status of each node.
- **If** a workflow with **150** components gets stop/resume errors, **then** split it into smaller workflows. **This works because** AWS advises keeping jobs + crawlers + triggers in one workflow at **100 or fewer**; above that, resume or stop-run actions may fail.
- **If** a failed run must not be lost silently, **then** add an **Amazon EventBridge** rule on the Glue **job/workflow state-change event** **(verify)** that sends to **Amazon Simple Notification Service (SNS)**. **This works because** Glue does not retry these cases by itself: an event that started a failed run is not reused, and a run blocked by the concurrency limit is not started or retried.
- **If** you need rules like "row count > 0, no null IDs, status in a list" on a Data Catalog table without code, **then** use **Glue Data Quality** on the table's Data quality tab: click **Recommend rules**, then edit them. **This works because** Glue profiles the data and suggests rules in **DQDL** (Data Quality Definition Language), and only the Catalog entry point offers recommendations. Catalog runs cost **$0.44 per DPU-hour** with a 2 DPU minimum.
- **If** bad rows must be **separated** and only good rows loaded, **then** add the **Evaluate Data Quality** transform inside the ETL job and use its **row-level outcomes** to quarantine failed rows. **This works because** only the ETL entry point identifies failed records row by row; the Catalog entry point cannot.
- **If** thresholds should follow history (for example row count compared with the last 10 runs), **then** use **dynamic rules** (such as `RowCount > avg(last(10))`) or **ML anomaly detection**. **This works because** both use statistics stored from earlier runs (kept for 2 years) instead of a fixed number.
- **If** a source column is a nested struct or an array and Data Quality fails, **then** **flatten** it first (for example with Unnest or Relationalize). **This works because** Glue Data Quality cannot evaluate nested or list (array) columns.
- **If** analysts must clean CSV files without code and find outliers, **then** use **AWS Glue DataBrew**, a visual no-code data preparation tool: build a **recipe** (saved steps) and run a **profile job** **(verify)**. **This works because** DataBrew has 250+ point-and-click transforms with a before/after preview, and a profile job computes statistics such as missing values, distributions and **outliers** as charts. Check that DataBrew is still open to new customers **(verify)**.
- **If** personal data (PII) must be masked inside a Spark ETL job, **then** use the **Detect Sensitive Data** transform to redact or hash it **(verify)**. **This works because** it finds PII inside the data while the job runs, so only masked data is written to the shared zone.
- **If** Amazon S3 buckets must be scanned for PII you do not know about, **then** use **Amazon Macie**, not Glue. **This works because** Macie scans S3 buckets to discover PII, while Glue's transform only acts on data during a job.
- **If** Data Quality results must raise an alarm, **then** create an **Amazon EventBridge** rule on the Data Quality result event **(verify)** that sends to **Amazon SNS**, or a **CloudWatch alarm** on Data Quality metrics. **This works because** Glue Data Quality publishes its results to EventBridge and to CloudWatch metrics.
- **If** you want to avoid the extra cost of a Data Quality check on the Catalog, **then** run the checks **inside the ETL job** with Evaluate Data Quality. **This works because** Data Quality in a job is included in the job's own data processing unit (DPU) cost, while Catalog runs bill **$0.44 per DPU-hour** (2 DPU and 1-minute minimum).

## Verified from AWS docs on 2026-10-20
Read from current AWS pages: triggers (types, states, conditional rules, limits), workflows (start triggers, EventBridge batching, concurrency, 100-node guidance, run properties, static/dynamic views), Glue Data Quality overview (entry points, comparison table, terminology, limits, release notes through Sept 2026), pricing page (DQ, DataBrew), DataBrew overview, quotas page.
Not confirmed (verify): cron minimum interval, blueprint list, resume/restart failed run wording, EventBridge detail-types, full DQDL rule-type list, `ruleOutcomes` / `rowLevelOutcomes` names, Detect Sensitive Data options and actions, DataBrew details (datasets, profile/quality rules, PII transforms, output formats, lineage, job node defaults), DataBrew current availability, exact console tab and menu labels, Glue workflow cost statement, Macie-to-Lake Formation tagging flow.

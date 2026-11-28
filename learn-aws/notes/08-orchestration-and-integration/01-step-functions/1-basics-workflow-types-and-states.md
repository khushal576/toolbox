# AWS Step Functions – 1. Basics, workflow types and states

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS Step Functions** is a serverless **workflow orchestrator**. You define a **state machine** (a graph of steps) and it runs the steps, keeps the state, retries, waits and branches.
- It is the **control plane of a pipeline**, not the compute. The work runs in Lambda, Glue, EMR, Athena, Batch, ECS, Redshift and other services.
- You write the definition in **Amazon States Language (ASL)**, a JSON format. **Workflow Studio** is the visual editor that produces the same JSON.
- A running copy of a state machine is an **execution**. Each execution has its own input, state and history.
- Fully managed: no servers, no scheduler to patch, scales automatically, pay per use.
- Pick it when:
  - You orchestrate **AWS services** with retries, error handling, branching and waiting (ETL, ML pipelines, order flows).
  - You need **long-running** flows (up to 1 year) or a **human approval / callback** step.
  - You need **large parallel fan-out over S3 data** (Distributed Map).
  - You want an **audit trail** per execution (visual history, 90 days).
  - You want little or no glue code: **SDK integrations** call 200+ services directly.
- Avoid it when:
  - The logic is pure compute and fits one Lambda → just use Lambda.
  - You need **Python DAGs**, backfills, a big plugin ecosystem or existing Airflow code → **MWAA**.
  - You only need **Glue jobs and crawlers chained** inside Glue → **Glue workflows** (simpler, no extra service).
  - You need **sub-second, million-per-second** event routing without state → **EventBridge / SQS / Lambda**.
  - You need **exactly-once streaming** processing → **Managed Flink**.
- Data-engineering uses: ETL orchestration (Glue → Athena → Redshift), ML training pipelines, S3 file fan-out with Distributed Map, ingest validation, approval gates, error compensation (saga).

## B. Core concepts
- **State machine**: the definition (ASL JSON) plus a type (Standard or Express), an execution role, and optional logging/tracing/encryption.
- **State**: one step. Has a name, a `Type`, and either `Next` or `End`.
- **Execution**: one run with an input JSON and a final output JSON.
- **Task token**: a unique token that lets an outside system say "this waiting task is done".
- **Activity**: a task whose work is done by your own worker that polls Step Functions. Standard only.
- **Version**: an immutable snapshot of a state machine. **Alias**: a pointer to up to two versions with traffic weights.
- **Map Run**: the resource created by a **Distributed Map** state, holding its child executions.
- **Context object** (`$$`): read-only data about the execution (ID, start time, state name, task token, Map item index).
- Every state machine has a `StartAt` field naming the first state and a `States` object. An optional top-level `TimeoutSeconds` limits the whole execution.
- Optional top-level fields: `Comment`, `Version`, `QueryLanguage` (`JSONPath` default, or `JSONata`).
- State machine and execution names: **max 80 characters**, unique per account and Region, no whitespace, no wildcards `? *`, no brackets `< > { } [ ]`, no special characters like `" # % \ ^ | ~ ` $ & , ; : /`.
- Use **ASCII-only names**. Non-ASCII names work but **block CloudWatch logging and metrics**.
- **Workflow type cannot be changed** after creation. To switch Standard ↔ Express you create a new state machine ("Copy to new").

## C. Standard vs Express (the exam favourite)
| Feature | Standard | Express |
|---|---|---|
| Max duration | **1 year** | **5 minutes** |
| Execution semantics | **Exactly-once** | Async: **at-least-once**. Sync: **at-most-once** |
| Execution start rate | Soft quota (about 300/s refill in big Regions) | Very high (6,000/s refill) |
| State transition rate | Quota (5,000/s big Regions, 800/s others) | **No limit** |
| Pricing | Per **state transition** | Per **request + duration × memory** |
| Execution history | In Step Functions, **90 days**, up to **25,000 events** | **Only in CloudWatch Logs**, unlimited events |
| `.sync` (Run a Job) pattern | Yes | **No** |
| `.waitForTaskToken` (callback) | Yes | **No** |
| Distributed Map | Yes (as parent) | **No** |
| Activities | Yes | **No** |
| Redrive | Yes (14 days) | **No** |
| Best for | Long, durable, auditable, **non-idempotent** work (start EMR, payments) | High-volume, short, **idempotent** work (IoT, stream transforms, API backends) |
- Standard is **exactly-once for the workflow**: a state never runs twice unless you wrote a `Retry`.
- Express is **at-least-once (async)**, so a step could run more than once. Make Express steps **idempotent** (for example a DynamoDB `PutItem`).
- Standard automatically returns an **idempotent response if you start an execution with the same name** as a running one. Express does not: same name = another concurrent run.
- Standard **execution names can be reused only after the old history expires** (90 days).
- Express **Asynchronous**: `StartExecution` returns an acknowledgement; you read results from CloudWatch Logs.
- Express **Synchronous**: `StartSyncExecution` waits and returns the result. Used behind **API Gateway**, Lambda, or the SDK.
- In the **console**, `StartSyncExecution` times out at **60 seconds**. Use the SDK/CLI to run up to 5 minutes.
- `StartSyncExecution` calls **do not count toward** the account StartExecution capacity limits.
- Express **does not persist state between transitions**; a failure mid-run can lose in-flight state. Standard persists after every transition.
- Express memory model: billed by **memory consumed** (in 64 MB chunks), not by a size you pick.
- Express execution **history is not captured by Step Functions**. Turn on **CloudWatch Logs**, or you see nothing.
- Express logging is **best-effort**. If you need guaranteed history use **Standard**, or write records to DynamoDB.
- The Step Functions **console enables logging by default for Express** state machines it creates, not for Standard.
- You can **nest**: a Standard parent starts Express children for the idempotent high-volume parts. This is the main **cost trick**.
- Distributed Map **child workflows can be Express or Standard** (`ExecutionType`), but the **parent must be Standard**.

## D. State types
| State | What it does |
|---|---|
| **Task** | Does work: calls a Lambda, an AWS service API (optimized or SDK), an Activity, or an HTTPS endpoint |
| **Choice** | Branches with rules (`Variable` + comparison). Has a `Default` |
| **Map** | Runs a sub-workflow for each item of an array (Inline) or S3 dataset (Distributed) |
| **Parallel** | Runs several **different** branches at the same time |
| **Wait** | Pauses for seconds, until a timestamp, or from a path |
| **Pass** | Passes input to output, optionally injecting fixed data or reshaping it |
| **Succeed** | Ends the execution successfully |
| **Fail** | Ends the execution as failed with an `Error` and `Cause` |
- **Pass and Wait cannot raise runtime errors** (other states can).
- **Choice**, **Succeed** and **Fail** do **not** have `Next`. Choice uses `Choices[].Next` and `Default`.
- Every non-terminal state needs `Next` or `"End": true`. Terminal states are Succeed, Fail, or any with `End: true`.
- `Catch` and `Retry` are allowed only on **Task, Map, Parallel**.
- **Choice** has no `Retry/Catch`; if no rule matches and there is no `Default`, you get a `States.NoChoiceMatched` runtime error (**not retriable**).
- Choice operators: `StringEquals`, `NumericGreaterThan`, `BooleanEquals`, `TimestampLessThan`, `IsPresent`, `IsNull`, `StringMatches` (wildcards), and path-based variants (`...Path`). Combine with `And`, `Or`, `Not`.
- **Parallel**: every branch gets the **same input**; output is an **array of branch outputs in branch order**. If one branch fails (uncaught), the whole state fails and other branches are stopped.
- **Inline Map** vs **Distributed Map** (section F). Both are called `Map` and differ by `ProcessorConfig.Mode`.
- **Wait** options: `Seconds`, `Timestamp` (ISO 8601), `SecondsPath`, `TimestampPath`. Max wait is bounded by the **1-year** execution limit.
- **Pass** is used for tests, stubbing, shaping data, and setting variables with `Assign`.
- **Fail** has `Error` (a short name) and `Cause` (a human text). Dynamic versions: `ErrorPath`, `CausePath`.
- A `Task` state may have `TimeoutSeconds`, `HeartbeatSeconds`, `Retry`, `Catch`, `Credentials` (assume a role), `Comment`.
- `Task` **timeouts**: if you set none, request-response tasks get a default; **`.sync`, `.waitForTaskToken` and Activities can wait up to 1 year** unless you set a timeout. **Always set one.**
- `HeartbeatSeconds` must be **smaller than** `TimeoutSeconds`.
- States can have a `Comment` and an `OutputPath`/`Output` etc. (see file 2).
- **Credentials field** lets a Task assume another role (cross-account call) using `RoleArn`; the state machine role must be allowed `sts:AssumeRole` on it.

## E. Choosing a query language: JSONata vs JSONPath
- **JSONPath** is the original and the **default for state machines that do not set `QueryLanguage`** (backward compatibility).
- **JSONata** is the **recommended choice for new state machines**. Set `"QueryLanguage": "JSONata"` at the top level or per state.
- JSONata expressions are written inside `{% ... %}`.
- JSONata uses **`Arguments`** (replaces `Parameters`), **`Output`** (replaces `ResultSelector/ResultPath/OutputPath`), and **`Assign`** for variables.
- In JSONata, the state input is `$states.input`, the task result is `$states.result`, the error is `$states.errorOutput`, and context is `$states.context`.
- JSONata `Items`, `MaxConcurrency`, `ToleratedFailureCount/Percentage` can be **expressions** (no `...Path` versions needed).
- You can **mix** languages: a state machine in JSONPath can contain a few JSONata states, and the other way round.
- JSONPath fields: `InputPath`, `Parameters`, `ResultSelector`, `ResultPath`, `OutputPath`. See file 2.
- Under JSONata, the old five-field pipeline is **not available**. Mixing JSONPath fields in a JSONata state is a validation error.
- JSONata makes **Pass states that only reshape data** mostly unnecessary, so you pay for fewer transitions.

## F. Map state in detail
- **Inline Map**: iterations run **inside** the parent execution and its history. Concurrency up to **40** parallel iterations. Input must fit **256 KiB**. Good for small arrays.
- **Distributed Map**: each item (or batch) runs as a **child workflow execution** with its own history. Up to **10,000 parallel** child executions. Reads **S3 datasets** directly.
- Use Distributed Map when **any** is true: dataset **> 256 KiB**, history would exceed **25,000 events**, or you need **> 40 concurrent** iterations.
- Inline Map uses `ItemProcessor` with `ProcessorConfig.Mode = INLINE` (or no mode). Distributed uses `Mode = DISTRIBUTED` and **must** set `ExecutionType` (`STANDARD` or `EXPRESS`).
- `MaxConcurrency`: omit or `0` = **no limit** (Inline: service limit; Distributed: **10,000**). Set it to protect a downstream service such as Lambda or a database.
- Child executions are dispatched at up to **1,000/s for Express** and **100/s for Standard** children.
- The Map output is an **array of child results in input order**, unless you use `ResultWriter` to write them to S3.
- Legacy name: the old Map field was `Iterator`; use `ItemProcessor` now.
- `ItemSelector` (JSONPath) / JSONata `Items` reshapes each item before the iteration; useful to add shared context to every item. In JSONata the field is also named `ItemSelector` with `Arguments`-like content **(verify field naming)**.
- `Label` names a Distributed Map (max **40** chars) and appears in the Map Run ARN.
- A Distributed Map creates a **Map Run** you can open in the console to see counts of succeeded, failed, running, and pending items.
- Max **1,000 open Map Runs** per account per Region; extra Map Runs wait ("backlogged") at `MapRunStarted`.
- Distributed Map **cannot read variables from outer scopes** (you pass data through `ItemSelector`).
- Details of ItemReader, batching, failure thresholds and ResultWriter are in file 3.

## G. Versions, aliases and deployment safety
- **Publish a version** to freeze the current definition. Versions are **immutable**, numbered 1, 2, 3 …, up to **1,000 per state machine**.
- An **alias** (for example `PROD`) points to **one version, or two versions with weights** that must add up to 100. Up to **100 aliases** per state machine.
- Start an execution through the alias ARN (`...:stateMachine:name:PROD`) and Step Functions **randomly picks a version by weight** (canary / gradual deployment).
- Starting through the plain state machine ARN runs the **latest revision** (`$LATEST`).
- Alias cannot point to another alias.
- **Rollback**: update the alias to point back to the previous version (instant, no redeploy).
- Execution metrics get extra dimensions `Version` and `Alias`, so you can compare a canary against stable.
- An execution **keeps the version it started with**, even if you later move the alias.
- With **CloudFormation/CDK/SAM**, you can auto-publish versions and create aliases with deployment preferences.
- You can call `ValidateStateMachineDefinition` to lint a definition before creating it. `TestState` API tests a single state with sample input without running the whole execution.

## H. Compared with nearby services
| Need | Step Functions | MWAA | Glue workflows | EventBridge Pipes / Scheduler | Lambda |
|---|---|---|---|---|---|
| Model | State machine, JSON | Python DAG | Triggers + jobs/crawlers | Point-to-point + schedule | Code |
| Serverless | Yes | No (always-on env) | Yes | Yes | Yes |
| Best at | AWS service orchestration, retries, callbacks | Complex DAGs, backfills, many providers | Glue-only chains | Simple routing/cron | Compute |
| Long waits | Up to 1 year | Yes, uses worker slots | Limited | N/A | 15 min max |
| Cost model | Per transition / request | Hourly environment | Free orchestration (pay jobs) | Per event | Per invoke |
- **Step Functions vs MWAA**: Step Functions = serverless, pay per use, JSON/low-code, 200+ SDK integrations. MWAA = full Airflow (Python, backfill, catch-up, rich UI, huge operator library), pays hourly even when idle.
- **Step Functions vs Glue workflows**: Glue workflows can only chain **Glue crawlers and jobs** (and triggers). Step Functions can chain **any service** and has branching, retries and callbacks.
- **Step Functions vs Lambda**: Do not write a Lambda that calls another Lambda and waits; Lambda has a **15-minute** limit and you pay while waiting. Use Step Functions (waiting is free in Standard; you pay per transition).
- **Step Functions vs EventBridge Scheduler**: Scheduler **starts** an execution on a schedule; Step Functions **runs** the steps.
- **Step Functions vs SQS**: SQS decouples and buffers; Step Functions coordinates a defined sequence and tracks state.
- **Step Functions vs Lambda durable functions**: durable functions are code-based checkpointed Lambda; Step Functions is declarative and integrates directly with services **(verify current feature set)**.

## I. How executions start
- **Console** or **CLI/SDK**: `StartExecution` (async) or `StartSyncExecution` (Express only).
- **EventBridge rule** with Step Functions as target (S3 events, schedule, custom events). Needs a role on the rule that can `states:StartExecution`.
- **EventBridge Scheduler** (cron/rate/one-time), including time zones.
- **EventBridge Pipes**: SQS, Kinesis, DynamoDB streams, MSK → (filter/enrich) → Step Functions. Pipes can start **Standard async** or **Express sync/async** executions.
- **API Gateway**: REST or HTTP API integration (sync Express for request/response, async Standard otherwise).
- **Lambda** or application code via SDK.
- **Another state machine** (nested workflow) through `states:startExecution` (`.sync` for Standard parents).
- **S3 event notifications** go through EventBridge (S3 does not call Step Functions directly).
- Name your executions when you need **idempotent starts** in Standard (same name + same input returns the existing run).
- Start input is JSON, max **256 KiB**. Anything larger must go to S3 and pass the **object location**.

## J. Execution history, events and statuses
- Statuses: `RUNNING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `ABORTED`, `PENDING_REDRIVE`.
- Standard history is kept **90 days** after close (can be reduced to **30 days** via a support request, per account and Region).
- Standard history size is capped at **25,000 events**. At the cap the execution **fails**. Long loops must start a **new execution** to continue, or use Distributed Map.
- Each state typically writes several events (entered, started, succeeded, exited), so **25,000 events ≈ a few thousand states**.
- Console shows a **graph view**, **table view** and **event view**, with input/output per state, so you can see exactly where a run failed.
- `GetExecutionHistory` is for **Standard only**. For Express, query **CloudWatch Logs Insights**.
- `StopExecution` ends a running execution as `ABORTED`. It can carry an `error` and `cause`.
- `.sync` tasks that get aborted try to **cancel the underlying job** (for example StopExecution for nested workflows). It is **best effort**; you could still pay for the job if it cannot be stopped.
- An EventBridge event is sent for every **execution status change** (Standard; Express optional). Use it to alert on `FAILED/TIMED_OUT/ABORTED`.
- If the state machine uses a **customer managed KMS key**, input/output/error are **left out** of EventBridge status-change events.

## K. Exam skills mapping
- **1.3.1 Orchestrate ETL (Lambda, EventBridge, MWAA, Step Functions, Glue workflows)**: orchestrator choice vs MWAA and Glue workflows.
- **1.3.3 Serverless workflows**: Standard vs Express, serverless workflows.
- **3.1.1 Orchestrate pipelines (MWAA, Step Functions)**: state machines for pipelines.
- **1.1.5 Set up schedulers (EventBridge, Airflow, time-based) for jobs and crawlers**: Scheduler/EventBridge starts.
- **1.3.4 Alerts with SNS and SQS**: failure paths to SNS/SQS.

## L. Scenarios: "If X → Y, because Z"
- **If** a nightly pipeline runs an **AWS Glue crawler**, then a **Glue job**, then an **Amazon Athena** query, then an **Amazon Simple Notification Service (SNS)** alert, with retries, **then** use a **Standard AWS Step Functions** state machine with **`.sync`** (Run a Job) integrations. A `.sync` Task starts the job and **waits until it finishes** before moving on. **This works because** Standard **saves state after every step** and runs each state **exactly once**, so a long chain of jobs is durable and can retry step by step. Express has no `.sync`. The crawler start itself has no `.sync`, so it needs a short polling loop.
- **If** a workflow must **wait days** for a **human approval**, **then** use a **Standard** workflow with a **`.waitForTaskToken`** (Wait for Callback) Task. The Task sends a **task token** (a unique ID for this waiting step) through **Amazon Simple Notification Service (SNS)** or **Amazon Simple Queue Service (SQS)**, and the approval comes back with that token through `SendTaskSuccess` or `SendTaskFailure`. **This works because** Standard executions can wait up to **1 year**, and waiting is free (you pay per transition). Express supports no callbacks and stops at **5 minutes**.
- **If** you need **100,000 events per second** transformed in **under a second**, **then** use **Express** workflows, or skip Step Functions and use **AWS Lambda** or **Amazon Kinesis** directly. **This works because** Standard has a start-rate quota (about **300 per second** refill in big Regions), a state-transition quota, and is billed **per state transition**, which does not fit huge numbers of tiny runs. Express starts much faster (**6,000 per second** refill), has **no transition limit**, and is billed per request and duration. Express is **at-least-once**, so its steps must be safe to repeat.
- **If** a step is **non-idempotent** (running it twice causes harm), such as charging a card or starting an **Amazon EMR** cluster, **then** use a **Standard** workflow. **This works because** Standard is **exactly-once**: a state never runs twice unless you wrote a `Retry` for it. Express async is **at-least-once**, so a step could run more than once.
- **If** a step uses **`.sync`** or **`.waitForTaskToken`** and the state machine is **Express**, **then** the definition **fails validation**. **This works because** Express supports only the **Request Response** pattern (call the API and move on); waiting for a job or a callback needs **Standard**. The workflow type cannot be changed later, so you create a new Standard state machine.
- **If** you must process **10 million CSV rows** in **Amazon S3** in parallel, **then** use a **Distributed Map** state with an **ItemReader** pointed at the file. **This works because** Distributed Map **reads S3 datasets directly** and runs each item (or batch) as a **child workflow execution** with its own history, up to **10,000** at once. Inline Map cannot do this: its input must fit **256 KiB** and it runs at most **40** iterations in parallel.
- **If** a looping workflow reaches **25,000 history events**, **then** start a **new execution** that carries the remaining work (continue-as-new), or move the work into a **Distributed Map**. **This works because** the Standard history cap is hard: at **25,000 events** the execution **fails**. Each state writes several events, so the cap is only a few thousand states. Distributed Map children each keep their **own history**, so they do not fill the parent's.
- **If** a Map over **5,000 items** hits the **256 KiB** payload cap, **then** switch to a **Distributed Map** that reads the items from **Amazon S3**. **This works because** the items no longer pass through the state payload; Step Functions reads them from S3 itself. An Inline Map's input must fit inside **256 KiB**.
- **If** you only chain **AWS Glue jobs and crawlers**, **then** use **Glue workflows**. **This works because** they are simple and the orchestration is **free** (you pay only for the jobs). If you need **branching** or steps in **other services**, use Step Functions instead.
- **If** the team needs **Python DAGs** (task graphs written in Python), **backfills** and **Airflow plugins**, **then** use **Amazon Managed Workflows for Apache Airflow (MWAA)**. **This works because** MWAA is full Airflow with backfill, catch-up and a huge operator library, while Step Functions has **no backfill or catch-up** concept. The catch: MWAA is an always-on environment **paid hourly**, even when idle.
- **If** you need to roll out a new state machine definition safely, **then** **publish a version** and point an **alias** (for example `PROD`) at the old and new versions with weights such as **90/10**. **This works because** a version is an **immutable snapshot**, and a start through the alias **randomly picks a version by weight** (a canary). **Rollback** is one alias update back to the old version. A running execution keeps the version it started with.
- **If** an API needs a **synchronous multi-step backend** that finishes in under **5 minutes**, **then** put an **Express synchronous** workflow behind **Amazon API Gateway**. **This works because** `StartSyncExecution` waits and **returns the result in one call**. In the console it stops at **60 seconds**; the SDK or CLI allows the full 5 minutes. Sync Express is **at-most-once**.
- **If** a long **Standard** flow contains a **high-volume, idempotent** sub-flow and you want to cut cost, **then** **nest an Express workflow** for that part. **This works because** Standard is billed **per state transition**, while Express is billed **per request plus duration × memory**, which is cheaper for many short steps. The Standard parent still gives durable, exactly-once control of the whole run.
- **If** you cannot see the history of an **Express** workflow, **then** **enable Amazon CloudWatch Logs** on it. **This works because** Express keeps **no history inside Step Functions**; CloudWatch Logs is the only place to see it. Express logging is **best-effort**, so use Standard if you need guaranteed history.
- **If** you need to know whenever any run fails, **then** create an **Amazon EventBridge** rule on the **`Step Functions Execution Status Change`** event for `FAILED`, `TIMED_OUT` and `ABORTED`, sending to **Amazon Simple Notification Service (SNS)**. **This works because** `Catch` works only on states inside the workflow; a **failed top-level execution cannot be caught**. EventBridge receives an event for every status change (always for Standard, optional for Express).

Verified from AWS docs on 2026-11-03 (service quotas, choosing workflow type, service integration patterns, Distributed Map, versions and aliases, best practices, CloudWatch logging).
Unconfirmed (verify): the exact JSONata field naming for Distributed Map `ItemSelector`; the Lambda durable functions comparison; whether Inline Map's 40-iteration concurrency is still the documented ceiling; the EventBridge Pipes Express/Standard invocation options; whether `TestState` supports every state type.

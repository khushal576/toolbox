# AWS Step Functions – 3. Error handling, Distributed Map, scale and operations

Short notes. Each point is a fact you can be asked about.

## A. Where errors come from
- Every state **except Pass and Wait** can raise a runtime error.
- Three common sources:
  - **Definition problems**: Choice with no match and no `Default`, bad path, missing field.
  - **Task failures**: Lambda exception, Glue job failed, Athena query failed, HTTP 4xx/5xx from the integrated API.
  - **Transient issues**: throttling, network, service 5xx.
- **Default behaviour**: an unhandled error **fails the whole execution**.
- `Retry` and `Catch` exist only on **Task, Parallel, Map**. They do not exist on Choice, Pass, Wait, Succeed or Fail.
- **There is no catch for a failed top-level execution.** Handle it by: nesting in a parent workflow, an **EventBridge rule on status change** (`FAILED`, `TIMED_OUT`, `ABORTED`), or the caller handling it.
- Errors are **case-sensitive strings** called **error names**. Built-in names start with `States.`. Your own error names **cannot** start with `States.`.
- Error output has `Error` (name) and `Cause` (human text, a **string**, often escaped JSON). Convert with `States.StringToJson($.Cause)` or JSONata `$parse()`.

## B. Built-in error names
| Error name | Meaning | Retriable? |
|---|---|---|
| `States.ALL` | Wildcard for any known error | n/a (see exceptions) |
| `States.TaskFailed` | Any task failure **except `States.Timeout`** | Yes |
| `States.Timeout` | Task passed `TimeoutSeconds` or missed a heartbeat; also whole-execution timeout | Yes |
| `States.HeartbeatTimeout` | No heartbeat within `HeartbeatSeconds` | Yes |
| `States.Permissions` | Not enough IAM permission to run the task | Yes (but fix IAM) |
| `States.DataLimitExceeded` | Payload over **256 KiB** | Only if named explicitly |
| `States.Runtime` | Execution could not process something (bad path, null payload) | **No. Never caught or retried** |
| `States.NoChoiceMatched` | Choice found no rule and has no Default | No (runtime) |
| `States.ExceedToleratedFailureThreshold` | Distributed Map failed more items than allowed | Catch it |
| `States.ItemReaderFailed` | Map could not read its dataset | Catch it |
| `States.ResultWriterFailed` | Map could not write results to S3 | Catch it |
| `States.Http.Socket` | HTTP Task passed 60 s | Yes |
- **`States.ALL` rules**: must be **alone** in `ErrorEquals` and must be in the **last** retrier / catcher.
- **`States.ALL` does not match** `States.DataLimitExceeded` or `States.Runtime`. Name `States.DataLimitExceeded` explicitly if you want to handle it.
- **`States.TaskFailed`** is a wildcard for task errors, but **not for `States.Timeout`**. So "retry everything" often means listing both.
- A **nested workflow timeout** shows up in the parent as `States.TaskFailed`, not `States.Timeout`.
- Lambda errors: `Lambda.ServiceException`, `Lambda.AWSLambdaException`, `Lambda.SdkClientException`, `Lambda.TooManyRequestsException`, `Lambda.Unknown`, `Sandbox.Timedout`, or your own exception class name. Match with `Lambda.Unknown`, `Sandbox.Timedout`, `States.TaskFailed` for the generic cases.
- SDK integration errors are named `<Service>.<Exception>` (for example `S3.S3Exception`, `Athena.InvalidRequestException`).
- Custom errors: a Lambda raising `class MyError(Exception)` gives error name `MyError` (Python); Node uses the error name. Use this to route **retriable vs non-retriable** failures.
- `Fail` state lets you create your own error `Error` and `Cause`.

## C. Retry
- `Retry` is an **array of retriers**, checked **in order**; the **first** whose `ErrorEquals` matches is used.
- Fields and **defaults**:
  - `ErrorEquals` (required): array of error names.
  - `IntervalSeconds`: first wait. Default **1**. Max 99,999,999.
  - `MaxAttempts`: default **3**. `0` = never retry this error. Max 99,999,999.
  - `BackoffRate`: multiplier per retry. Default **2.0**.
  - `MaxDelaySeconds`: cap on the wait (must be > 0 and < 31,622,401). Default: no cap.
  - `JitterStrategy`: `FULL` or `NONE`. Default **`NONE`**. `FULL` randomizes each wait between 0 and the computed delay.
- Wait for attempt *n* = `IntervalSeconds × BackoffRate^(n-1)` (capped by `MaxDelaySeconds`).
- Example: `IntervalSeconds 3, BackoffRate 2, MaxAttempts 3` → waits 3 s, 6 s, 12 s.
- **Counters are per retrier**, across the visits to that state. A retrier that used up its `MaxAttempts` for one error **stops matching**; later errors fall to the next retrier or the Catch.
- Example of exclusion: `[{ErrorEquals:["States.Timeout"],MaxAttempts:0},{ErrorEquals:["States.ALL"]}]` retries everything **except** timeouts.
- **Retries count as state transitions** (Standard billing) and add history events.
- **Retry applies before Catch.** Only after retries are used up (or none match) does Catch run.
- On a **Parallel or Map** state, a Retry reruns the **whole** state (all branches / all iterations), not just the failed part.
- On a **Distributed Map**, a retry **creates a new Map Run** and the policy applies to all child executions.
- **Use Retry for transient errors only** (throttling, 5xx, timeouts). Retrying a bad-data error just wastes money.
- **Jitter** matters for Map/Parallel with many branches: it spreads retries to avoid a second wave of throttling.
- Retry is not **idempotency**: if a task is non-idempotent (charge, send email), design a key so a retry does not repeat the effect.
- After **redrive**, retry attempt counters of re-run states are **reset to 0**.

## D. Catch
- `Catch` is an array of **catchers**: `ErrorEquals`, `Next`, optional `ResultPath` (JSONPath) or `Output`/`Assign` (JSONata).
- Order matters; first match wins. `States.ALL` alone and last.
- **Default JSONPath `ResultPath` is `$`**, so the error object **replaces the whole input**. Use `"ResultPath": "$.error"` to **keep the input and add the error**.
- Catch-handler states often: write to a dead-letter location, publish to SNS, run a compensation step, then end with `Fail` or `Succeed`.
- A Catch can route to a state that **retries the original** after a fix (careful: loops → history cap).
- Catcher-run states see `Error` and `Cause`. In JSONata use `$states.errorOutput`.
- In JSONata, `Catch.Assign` can set variables in the **outer scope** (the scope containing the Parallel/Map).

## E. Timeouts and heartbeats
- `TimeoutSeconds` on a Task: Step Functions enforces it **itself**; it is not passed to the API. Failure = `States.Timeout`.
- For **request-response tasks**, a default timeout applies if you set none; for **`.sync`, callbacks and Activities** the default is effectively **1 year**.
- `HeartbeatSeconds`: the worker must call `SendTaskHeartbeat` within that interval, or `States.HeartbeatTimeout`. Keep it **smaller than** `TimeoutSeconds`.
- Top-level `TimeoutSeconds` caps the **whole execution**; reaching it gives `States.Timeout` and status `TIMED_OUT`.
- Max execution: **1 year** Standard, **5 minutes** Express. Hitting it = `TIMED_OUT` with `ExecutionsTimedOut` metric.
- A **tight timeout** on `.sync` is the main protection against a stuck job and a runaway bill.
- Idle limit equals the maximum execution time (1 year / 5 min).
- Task token timeout: after it expires, **late `SendTaskSuccess` calls fail** with `TaskTimedOut`; workers must handle it.

## F. Saga and compensation pattern
- For multi-step changes without a transaction: run step A, B, C; if C fails, **Catch → run undo steps** for B and A in reverse.
- Keep each action **idempotent** and each undo safe to repeat.
- Use **variables** to remember what completed so the compensation path knows what to undo.
- For data pipelines: write to a **staging prefix/table**, validate, then **commit** (rename/INSERT) at the end; on failure, delete staging.

## G. Distributed Map in depth
### G1. Reading the dataset (ItemReader)
- Sources: JSON array/object from previous state (`Items`/`ItemsPath`), **S3 ListObjectsV2**, **JSON** file, **JSON Lines**, **CSV** (or other delimiters), **Parquet**, **Athena manifest** (`UNLOAD`), **S3 Inventory** CSV manifest.
- `ReaderConfig.InputType`: `CSV`, `JSON`, `JSONL`, `PARQUET`, `MANIFEST`. `ManifestType`: `ATHENA_DATA` or `S3_INVENTORY` (do not set InputType for S3_INVENTORY).
- `Transformation`: `NONE` (default; iterate over **object metadata** from ListObjectsV2) or **`LOAD_AND_FLATTEN`** (read the **contents** of every listed object; removes the need for nested Maps).
- CSV: `CSVHeaderLocation` = `FIRST_ROW` or `GIVEN` (with `CSVHeaders`). `CSVDelimiter`: `COMMA` (default), `PIPE`, `SEMICOLON`, `SPACE`, `TAB`. Header max **10 KiB**.
- CSV rules: every field is a **string**; missing fields = empty strings; extra fields skipped. Convert types with `States.StringToJson` in `ItemSelector`.
- JSON: `ItemsPointer` (JSONPointer, < 2,000 chars, array start within the first **16 MB**) selects a nested array.
- Compression for text types: **GZIP, ZSTD** (by file extension). Parquet is internally compressed (GZIP, ZSTD, Snappy); **max row group 256 MB**, **max footer 5 MB**; `VersionId` not supported for Parquet.
- Max single S3 file: **10 GB**. Max items read: **`MaxItems` up to 100,000,000** (`MaxItemsPath` in JSONPath).
- **Bucket must be in the same account and Region** as the state machine for listing.
- Folders created in the **S3 console** appear as zero-byte items → extra child executions. Create prefixes with CLI, or filter them.
- Use a **trailing slash** on `Prefix` (`folder1/`) or `folder10/` also matches.
- Athena `UNLOAD` CSV has **no header row**; supply `CSVHeaders` with `GIVEN`.
### G2. Batching and selecting
- `ItemSelector` (JSONPath) reshapes/adds fields for each item. You can read the context (`$$.Map.Item.Index/Value`) here.
- `ItemBatcher` groups items so **one child execution handles a batch**. Settings: `MaxItemsPerBatch`, `MaxInputBytesPerBatch` (batch input must stay under **256 KiB**), and `BatchInput` for shared data.
- Batching **cuts the number of child executions** (and cost) and amortizes cold starts. A batch item arrives as `{ "Items": [...], "BatchInput": {...} }`.
- Pick batch size so the child's work fits inside its timeout and Lambda memory.
### G3. Running children
- `ItemProcessor.ProcessorConfig`: `Mode: DISTRIBUTED`, `ExecutionType: STANDARD | EXPRESS`.
- **Express children**: cheaper and faster for short idempotent work (≤ 5 min); at-least-once semantics.
- **Standard children**: when work is long, non-idempotent or needs `.sync`.
- `MaxConcurrency`: default/0 = **10,000**. Dispatch rate: **1,000/s Express**, **100/s Standard** children.
- Always set `MaxConcurrency` to what the **downstream** can take (Lambda concurrency, DB connections, API limits).
- Each child has **its own history**, so the parent's 25,000 events are not consumed.
- Open Map Runs per account: **1,000**; more wait in backlog (`ApproximateMapRunBacklogSize`).
### G4. Failure thresholds
- `ToleratedFailureCount` and/or `ToleratedFailurePercentage` (0–100). **Default 0**: any failed or timed-out child fails the Map Run.
- `100%` = never fail, even if all items fail (be careful; you must inspect results).
- If both are set, exceeding **either** fails the state with `States.ExceedToleratedFailureThreshold`.
- Percentage = (failed + timed out) / **total items**.
- Children may **keep running** briefly after the threshold is crossed before the Map Run fails.
### G5. Writing results (ResultWriter)
- Without `ResultWriter`, the Map returns an **array of child results in the parent payload** (limit 256 KiB). With big datasets use `ResultWriter` → **S3**.
- Output in S3: `manifest.json` plus result files split by status: `SUCCEEDED_n.json`, `FAILED_n.json`, `PENDING_n.json`. Each file holds results of children with that status.
- `ResultWriter` output formats: JSON or JSONL **(verify current options)**. The state output returns the S3 location and counts.
- Result file size can be capped (about **5 GB per file**) and Step Functions creates more files as needed **(verify)**.
### G6. Redrive of Map Runs
- You can **redrive a Distributed Map** to rerun only the **failed/aborted/timed-out child executions**; successful children are not rerun.
- Max **1,000 redrives** of a Map Run.
- Pattern: process millions of files, tolerate a few failures, **redrive after fixing the bad input**.

## H. Inline Map and Parallel notes
- **Inline Map** keeps everything in the parent history and payload; max concurrency **40**. Good for ≤ a few hundred items.
- `Parallel` output is an array ordered by branch order, not completion order.
- If one Parallel branch fails and is uncaught, **all other branches are stopped** (`.sync` tasks inside get cancel attempts).
- Map/Parallel `ResultSelector` can flatten an array of arrays (for example `$[*][*]`) **(verify path syntax)**.
- Use `ResultPath` / `Output` on the Map to **keep the original input** while adding results.

## I. Redrive (single execution)
- **Redrive** restarts a failed, aborted or timed-out **Standard** execution **from the failed step**, same input, same execution ARN, same state machine **version/alias**.
- Eligible: started on or after **15 Nov 2023**, not `SUCCEEDED`, within **14 days** after close, **under 1 year** open time, history **< 24,999 events** (history is appended).
- Not available for Express.
- Behaviour per state:
  - Task: **reschedules** and reruns; its timeout counter is reset.
  - Parallel / Inline Map: reruns only **failed or aborted** branches/iterations (unless the failure was `States.DataLimitExceeded`, then the whole state reruns).
  - Distributed Map: redrives unsuccessful child executions.
  - Choice: re-evaluates rules. Wait: if the time is in the past, exits. Fail: fails again. Pass/Succeed: not rerun.
- **Retry attempt counters reset to 0** on redrive; state-machine-level timeout also resets.
- Redrive counts as **state transitions** (billed).
- IAM needs `states:RedriveExecution`. Redrive uses the **same definition**; if you fixed the definition, you must start a **new execution** instead.
- Metrics: `ExecutionsRedriven`, `RedrivenExecutionsSucceeded/Failed/TimedOut/Aborted`.
- A fixed IAM role or fixed downstream resource is the typical reason to redrive; a fixed **definition** is not.

## J. Handling the 25,000-event history cap
- Long loops (polling, paginating) can hit **25,000 events**; the run **fails**.
- Fixes:
  - **Distributed Map**: each item runs in its own execution.
  - **Continue-as-new**: a Task calls `states:startExecution` for the same state machine with the remaining work, then ends.
  - **Nested workflows**: put the loop body in a child state machine (child history is separate).
  - Replace polling with **`.sync` or callback**.
  - Reduce events per loop (JSONata, fewer Pass states).
- Pagination pattern: keep the **next token** in a variable; loop state → Choice; every N pages start a new execution.

## K. Idempotency and duplicates
- **Standard**: same execution **name** while one is running returns the existing run (no duplicate); after it closes, a new start with the same name and **different input** errors until history expires (90 days) **(verify exact error)**.
- Use a **business key** as execution name to prevent double processing from at-least-once triggers (S3 events, SQS).
- **Express**: duplicates are possible; every step must be idempotent.
- Downstream writes: use conditional puts, `MERGE`, or deterministic output paths so reruns overwrite instead of duplicate.
- Glue job `.sync` retry **creates a new job run**: make jobs rerunnable (overwrite partitions, bookmarks).

## L. Operating at scale
- Workflow concurrency: Standard open executions **1,000,000** per account per Region (soft). Exceeding → `ExecutionLimitExceeded`. Monitor `OpenExecutionCount` (alarm on Maximum ≥ 100K).
- `StartExecution` throttle (Standard): bucket 1,300, refill 300/s in us-east-1, us-west-2, eu-west-1; **800 / 150** elsewhere. Express: 6,000/6,000.
- State transitions (Standard): bucket/refill **5,000/s** in the three big Regions, **800/s** elsewhere. **New accounts start lower** and are raised automatically.
- Throttled transitions show as **`ExecutionThrottled`** metric. Fix: add jitter to retries, spread starts, request a quota increase, move high-rate parts to Express or Distributed Map with Express children.
- API throttles to remember: `GetExecutionHistory` (20/s refill), `DescribeExecution` (15/s or 10/s), `SendTaskSuccess/Failure/Heartbeat` (500/s or 300/s), `GetActivityTask` (500/s or 300/s).
- `.sync` cross-account polling uses your API quota; heavy use may throttle `DescribeExecution`.
- **Buffer starts with SQS + Pipes** (batch size, max concurrency) to smooth bursty inputs.

## M. Testing and deployment
- **Workflow Studio** for drag-and-drop; **Local testing** with the Step Functions Local (Docker) **(verify current status)**; **TestState** API tests one state with mock input/role; **Mocked service integrations** test whole flows locally **(verify)**.
- **Infrastructure as code**: CloudFormation / SAM (`AWS::Serverless::StateMachine`, DefinitionSubstitutions) / CDK (`aws-stepfunctions`, `aws-stepfunctions-tasks`).
- Use **definition substitutions** to inject function ARNs and bucket names rather than hard-coding.
- Put **version + alias** in CI/CD: publish on deploy, shift weights, roll back by moving the alias.
- Tag state machines for cost allocation and ABAC; execution resources inherit the state machine's tags for tag-based IAM checks.

## N. Scenarios: "If X → Y, because Z"
- If a Lambda step is throttled sometimes → **Retry on `Lambda.TooManyRequestsException` + `Lambda.ServiceException` with backoff and `JitterStrategy: FULL`**, because they are transient and jitter spreads the retries.
- If bad input keeps failing a Glue job → **do not retry data errors; Catch → write to a quarantine S3 prefix → SNS**, because retries add cost and the result will not change.
- If you want to retry everything except timeouts → **first retrier `States.Timeout` with `MaxAttempts: 0`, then `States.ALL`**, because the first matching retrier decides.
- If a failure message loses the original input → **Catch with `ResultPath: $.error`**, because the default replaces the input with the error.
- If `States.ALL` does not catch a payload error → **add `States.DataLimitExceeded` explicitly**, because the wildcard excludes it (and `States.Runtime`).
- If a workflow fails with `States.Runtime` → **fix the definition/path (null input, missing field)**, because it is never retriable or catchable.
- If a run fails after 25,000 events → **use Distributed Map / child workflows / continue-as-new**, because the cap is hard.
- If you must process 2 million S3 files, tolerating 1% bad → **Distributed Map, `LOAD_AND_FLATTEN` or listing with batches, `ToleratedFailurePercentage: 1`, `ResultWriter` to S3**, because it scales out and keeps results out of the payload.
- If the Map hits a downstream limit → **lower `MaxConcurrency`**, because default is 10,000 parallel children.
- If some Map children failed after you fixed the data → **redrive the Map Run**, because only failed children rerun.
- If a failed execution must resume at the failed step after a permission fix → **RedriveExecution within 14 days**, because it reuses successful steps; but if the definition changed → **start a new execution**.
- If a callback never arrives → set **`HeartbeatSeconds` and `TimeoutSeconds`** and catch `States.Timeout`, because otherwise the run waits up to a year.
- If a 1-hour job needs Express-like cost → **it cannot be Express (5 min max)**; use Standard with `.sync`, because durability and duration need Standard.
- If starts spike and you see `ExecutionThrottled` → **buffer with SQS/Pipes, jitter retries, ask for a higher quota**, because the transition/start buckets are exhausted.
- If you need one place to be told about any failure → **EventBridge rule on execution status change → SNS**, because `Catch` cannot catch a top-level failure.
- If duplicates arrive from an at-least-once trigger → **use a business key as execution name (Standard)** and **idempotent writes**, because Standard dedupes by name only while running.

## O. Exam skills mapping
- **1.3.2 Pipelines for performance, availability, scalability, resiliency**: retries, Catch, Distributed Map, redrive.
- **3.1.2 Troubleshoot managed workflows**: redrive, Map Run failures, history cap.
- **1.3.3 Serverless workflows**: error handling patterns.

Verified from AWS docs on 2026-11-03 (error handling, Distributed Map and ItemReader, redrive, service quotas, best practices, CloudWatch metrics).
Unconfirmed (verify): ResultWriter file formats and file-size split; exact behaviour/error when reusing a closed Standard execution name; flatten path syntax for Map outputs; Step Functions Local and mocked integration status; TestState coverage; ItemBatcher field names under JSONata.

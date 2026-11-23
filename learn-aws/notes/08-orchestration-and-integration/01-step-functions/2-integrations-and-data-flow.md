# AWS Step Functions – 2. Service integrations and data flow

Short notes. Each point is a fact you can be asked about.

## A. Three ways a Task calls something
- **Optimized integration**: purpose-built for a service. Resource looks like `arn:aws:states:::glue:startJobRun`. Step Functions shapes the request and response for you.
- **AWS SDK integration**: calls **any API of 200+ services** with `arn:aws:states:::aws-sdk:<service>:<apiAction>` (for example `aws-sdk:redshiftdata:executeStatement`). No Lambda needed.
- **HTTP Task**: calls any **HTTPS endpoint** (third-party or private through EventBridge connection) with `arn:aws:states:::http:invoke`.
- **Legacy Lambda ARN**: `Resource` is the real Lambda function ARN. Still works, but the console no longer builds it. Use `lambda:invoke` instead.
- **Activity**: `Resource` is an activity ARN; your own worker polls for the work.
- The `arn:aws:states:::` prefix is a **namespace**, not a real resource. The empty region and account fields are filled from where the workflow runs.
- SDK integration naming: the API name is **lower-camel-case** in the ARN (`aws-sdk:s3:getObject`), but the **parameters keep the service's PascalCase** (`Bucket`, `Key`).
- SDK integration **errors** are named `ServiceName.ExceptionName` (for example `S3.NoSuchKeyException`). You can `Retry/Catch` on them by name.
- Optimized integrations are **more convenient**; SDK integrations are **wider**. If the API you need is not optimized, use SDK.

## B. The three integration patterns
| Pattern | Resource suffix | Step Functions does | Standard | Express |
|---|---|---|---|---|
| **Request Response** | none | Calls API, moves on when it gets the HTTP response | Yes | Yes |
| **Run a Job** | `.sync` | Calls API, then **waits until the job finishes** | Yes | **No** |
| **Wait for Callback** | `.waitForTaskToken` | Passes a **task token** and **waits** for `SendTaskSuccess/Failure` | Yes | **No** |
- **Request Response** does **not** wait for the work. Example: `athena:startQueryExecution` returns a query ID while the query still runs.
- **`.sync`** is supported only by some optimized integrations: Athena, Batch, Bedrock, CodeBuild, ECS/Fargate, EKS, EMR (cluster, EMR Serverless, EMR on EKS), Glue, Glue DataBrew, MediaConvert, SageMaker AI, and nested Step Functions.
- **`.sync` is not available for SDK integrations.** If an SDK API has no `.sync`, poll yourself (Wait + status call + Choice loop) or use a callback.
- **`.waitForTaskToken`** works for **SDK integrations** (when the API has a field to carry the token) and for optimized ones such as Lambda, SQS, SNS, EventBridge, API Gateway, ECS, EKS, Bedrock, nested Step Functions.
- **Task tokens must be returned by principals in the same AWS account.** A token sent from another account fails.
- Get the token with `$$.Task.Token` (JSONPath context) or `$states.context.Task.Token` (JSONata) and put it in the request (SQS message body, Lambda payload, etc.).
- If a callback Task **times out, a new random token is generated**, so the old token becomes invalid (`TaskTimedOut`).
- Callback APIs: `SendTaskSuccess` (with output), `SendTaskFailure` (with `error` and `cause`), `SendTaskHeartbeat` (keeps the task alive).
- **Heartbeat**: set `HeartbeatSeconds` so a dead worker is detected. Missing heartbeat → `States.HeartbeatTimeout` (also `States.Timeout`).
- `.sync` and `.waitForTaskToken` tasks have **no default timeout** and can wait up to **1 year**. Set `TimeoutSeconds`, or a stuck job holds the execution (and, if you run it, the cost).
- `.sync` uses **polling plus EventBridge events** behind the scenes. Same-account `.sync` uses events + polling; **cross-account `.sync` uses polling only**, which consumes your API quota.
- `.sync` and `.waitForTaskToken` need **extra IAM permissions** (for example `events:PutRule`, `events:PutTargets`, `events:DescribeRule` managed rules). The console can generate them; hand-written roles often miss them.
- If an aborted `.sync` task cannot be cancelled (no permission to call stop APIs, or an outage), you may be **billed by the integrated service** for the job that keeps running.
- Aborts happen when: the execution is stopped, a sibling **Parallel** branch fails uncaught, or a **Map** iteration fails uncaught.
- Combine `.sync` with Retry for transient launch errors, but remember a **job failure** (non-zero exit) comes back as `States.TaskFailed`.
- Callback to wait for a **human**: Step Functions sends the token by SNS/SQS/email link, the user clicks, API Gateway/Lambda calls `SendTaskSuccess`.

## C. Integrations data engineers use
| Service | Typical API | Pattern | Notes |
|---|---|---|---|
| **AWS Glue** | `glue:startJobRun` | `.sync` | Waits for job end; fails on job failure. Pass `Arguments` for job parameters |
| **Glue crawler** | `aws-sdk:glue:startCrawler` | SDK only | No `.sync`; poll `getCrawler` until `READY` |
| **Glue DataBrew** | `databrew:startJobRun` | `.sync` | Recipe jobs |
| **Amazon Athena** | `athena:startQueryExecution` | `.sync` | Then `athena:getQueryResults` to read rows (paged) |
| **Amazon EMR** | `emr:createCluster`, `addStep`, `terminateCluster` | `.sync` | `createCluster.sync` waits for cluster ready; steps wait to finish |
| **EMR Serverless** | `emrserverless:startJobRun` | `.sync` | Application must exist or use create/start |
| **EMR on EKS** | `emrcontainers:startJobRun` | `.sync` | |
| **AWS Batch** | `batch:submitJob` | `.sync` | Waits for job; supports array jobs |
| **ECS / Fargate** | `ecs:runTask` | `.sync` / `.waitForTaskToken` | Container overrides pass parameters |
| **AWS Lambda** | `lambda:invoke` | Request Response / token | Wrap result in `Payload`; see section D |
| **Redshift** | `aws-sdk:redshiftdata:executeStatement` | SDK, poll | Poll `describeStatement`, or use EventBridge callback |
| **DynamoDB** | `dynamodb:getItem/putItem/updateItem/deleteItem` | Request Response | Optimized only for these four |
| **S3** | `aws-sdk:s3:getObject/putObject/copyObject` | SDK | Also used by Distributed Map |
| **SNS / SQS** | `sns:publish`, `sqs:sendMessage` | RR / token | Standard fan-out and alerts |
| **EventBridge** | `events:putEvents` | RR / token | Emit domain events |
| **SageMaker AI** | `sagemaker:createTrainingJob`, `createProcessingJob`, `createTransformJob` | `.sync` | |
| **Bedrock** | `bedrock:invokeModel`, `createModelCustomizationJob` | RR / `.sync` | |
| **Step Functions** | `states:startExecution` | RR / `.sync` / token | Nested workflow |
| **API Gateway** | `apigateway:invoke` | RR / token | Calls a REST API stage |
| **HTTP** | `http:invoke` | RR | Needs an EventBridge **connection** for auth |
- Rule of thumb: **orchestrate, do not compute**. Let the integrated service do the heavy work; keep the workflow to start/wait/branch.
- **Athena** pattern: `startQueryExecution.sync` → (`getQueryResults` if you need rows) → next step. Use Athena `ClientRequestToken` for idempotency on retries.
- **Redshift** pattern: `executeStatement` returns an `Id` → Wait → `describeStatement` → Choice on `Status` (`FINISHED`, `FAILED`, `ABORTED`) → loop. Or use `Redshift Data API` event to EventBridge and a callback.
- **Glue crawler** pattern: `startCrawler` → Wait 30 s → `getCrawler` → Choice on `State == READY` → loop. Add a counter to avoid endless loops (history cap!).
- **EMR** pattern: `createCluster.sync` (with `Instances.KeepJobFlowAliveWhenNoSteps = true`) → `addStep.sync` one or more → `terminateCluster.sync`. Put `terminateCluster` in a `Catch` path too, so failed runs do not leave clusters running.
- **Glue job** `.sync`: if you also set `JobRunId` tracking, retries start **new** runs, so make the job idempotent.
- **Batch** `.sync`: Step Functions waits for the Batch job to reach `SUCCEEDED` or `FAILED`.
- **ECS `.sync`**: the state succeeds when the task stops with exit code 0.
- **Nested workflow** `states:startExecution.sync:2` returns the child output as **JSON** (the `:2` version); plain `.sync` returns the output as an **escaped string** **(verify)**.
- Task parameters often include a unique token (for example `$$.Execution.Name` or `States.UUID()`) to make calls **idempotent**.

## D. Lambda integration details
- Use `arn:aws:states:::lambda:invoke` with `Parameters: { FunctionName, Payload }` (JSONPath) or `Arguments` (JSONata).
- The response is an **envelope**: `{ "ExecutedVersion", "Payload", "SdkHttpMetadata", "SdkResponseMetadata", "StatusCode" }`. Your function's return value is in **`Payload`**.
- Add `"OutputPath": "$.Payload"` (JSONPath) or `Output: "{% $states.result.Payload %}"` (JSONata) to unwrap.
- Without unwrapping, the next state receives the whole envelope and the 256 KiB limit is easier to hit.
- Lambda **function errors** surface as the function's error type (for example `Lambda.Unknown`, `Sandbox.Timedout`, or your exception class name) and `States.TaskFailed`.
- Retry these Lambda service errors: `Lambda.ServiceException`, `Lambda.AWSLambdaException`, `Lambda.SdkClientException`, `Lambda.TooManyRequestsException`.
- Recommended retry: `IntervalSeconds 2, MaxAttempts 6, BackoffRate 2`. Use `JitterStrategy: FULL` to avoid thundering herd.
- `Lambda.TooManyRequestsException` means **Lambda concurrency throttling**; lower Map `MaxConcurrency` or raise reserved concurrency.
- Step Functions Lambda `invoke` is **synchronous** (`RequestResponse`) by default. `InvocationType: Event` makes it fire-and-forget.
- The Lambda **15-minute** limit still applies. For longer, use ECS/Batch/Glue with `.sync`.
- Lambda payload limit (6 MB sync) is higher than the **256 KiB** Step Functions limit; Step Functions' limit wins for data passed between states.

## E. Input and output processing – JSONPath mode
- The five JSONPath fields in order: **InputPath → Parameters → (task runs) → ResultSelector → ResultPath → OutputPath**.
- **InputPath**: picks part of the state input to be the effective input. Default `$`. `null` = empty object `{}`.
- **Parameters**: builds the exact request. Keys ending `.$` are **paths**; other keys are literals. Can read the **context object** with `$$.`.
- **ResultSelector**: reshapes the **task result** before ResultPath. Good for trimming big responses.
- **ResultPath**: where to **put the result in the original input**. Default `$` = **replace the whole input** with the result.
- **ResultPath: `null`** = discard the result and pass the input through unchanged (for notification steps).
- **ResultPath: `$.result`** = keep the input and add the result under `result`. The most common setting.
- **OutputPath**: final filter on what leaves the state. Default `$`.
- Common mistake: using default `ResultPath` and **losing the original input**.
- In a `Catch`, **ResultPath** puts the **error output** (`Error`, `Cause`) under a key; default replaces the whole input with the error.
- A path ending `.$` in `Parameters` that points at a missing field causes `States.Runtime` error (not retriable).
- **Reference paths** (single value, no `*`, `..`, filters) are required for some fields: `ResultPath`, `ItemsPath` (array), `MaxConcurrencyPath`.
- Intrinsic functions work inside `Parameters`, `ResultSelector`, `Assign` (JSONPath).
- **Variables** (section G) can be used in `Parameters`/`ResultSelector`/`Choice` etc., but **not in `ResultPath`**.

## F. Input and output processing – JSONata mode
- **Arguments**: the request to the task (replaces `Parameters`).
- **Output**: the state's final output (replaces `ResultSelector`, `ResultPath`, `OutputPath`). If you omit it, the output defaults to the **task result** for Task states and the **input** for Pass/Wait/Choice-like states **(verify)**.
- **Assign**: stores variables.
- `{% ... %}` marks an expression; strings inside objects and arrays are evaluated too.
- JSONata can do math, string work, filtering and joins without Lambda: `$sum()`, `$map()`, `$filter()`, `$join()`, `$now()`, `$uuid()`, `$partition()` **(verify the Step Functions-specific helpers)**.
- Step Functions adds helper functions such as `$partition`, `$range`, `$hash`, `$random`, `$uuid`, `$parse` **(verify)**.
- Because JSONata states can compute in place, you need **fewer Pass/Lambda transitions** → lower cost.
- `Assign` and `Output` are evaluated **at the same time** from the same inputs; assigning a variable does not change the output.
- JSONata Catch: `$states.errorOutput` gives `Error` and `Cause`.

## G. Variables (`Assign`)
- Variables let a later state read a value stored earlier, without passing it through every state output.
- Supported in **Pass, Task, Map, Parallel, Choice, Wait** states and in **Catch**; `Assign` is available at the top of each state except Succeed and Fail (and inside Choice rules).
- Read a variable by `$name`. Names follow Unicode identifier rules, **max 80 characters**.
- **Size limits**: one variable **256 KiB**; all variables in one `Assign` **256 KiB**; all stored variables in an execution **10 MiB**.
- **Scope**: top-level states share a scope. **Parallel branches and Map iterations** can read outer variables but their own assignments stay inside; outputs leave via `Output`.
- A variable assigned in an inner scope **cannot have the same name** as one in an outer scope.
- **Distributed Map cannot read outer-scope variables** (pass data via `ItemSelector`).
- You **cannot assign part of a variable** (`"x.y"` or `"x[2]"` are invalid).
- All expressions in one `Assign` are **evaluated first (using values at state entry)**, then assigned. Order of keys does not matter.
- The reserved variable **`$states`** exposes `input`, `result`, `errorOutput`, `context`.
- Variables are in-state-machine memory: they **count toward execution data** but not toward the per-state 256 KiB input/output limit (so they help beat the payload cap).

## H. Intrinsic functions (JSONPath mode)
- Used only in fields ending `.$` (Parameters, ResultSelector, Assign, Catch).
- **Array**: `States.Array`, `States.ArrayPartition`, `States.ArrayContains`, `States.ArrayRange`, `States.ArrayGetItem`, `States.ArrayLength`, `States.ArrayUnique`.
- **Data encoding**: `States.Base64Encode`, `States.Base64Decode`, `States.Hash` (MD5, SHA-1, SHA-256, SHA-384, SHA-512).
- **JSON**: `States.JsonMerge` (shallow), `States.StringToJson`, `States.JsonToString`.
- **Math**: `States.MathRandom`, `States.MathAdd`.
- **String**: `States.StringSplit`, `States.Format` (`{}` placeholders).
- **Unique ID**: `States.UUID`.
- `States.ArrayPartition` splits an array into chunks; handy to fit **batches** under limits.
- `States.StringToJson` is often used to parse a Lambda or Athena `Cause` string into JSON.
- Intrinsic functions can be **nested** but each field has limits **(verify nesting depth)**.

## I. The 256 KiB payload rule
- **Input or output of a state, task or execution is capped at 256 KiB** (UTF-8 string). Applies to Standard and Express.
- Exceeding it raises **`States.DataLimitExceeded`**, a terminal error that **`States.ALL` does not catch**. You must name it in `ErrorEquals`.
- It can be hit when: a Task returns a big result, `Parameters` builds a big request, or an array grows across loop iterations.
- Fixes:
  - **Store data in S3**, pass the **bucket and key** (ARN) between states.
  - Trim results with `ResultSelector`/`Output` early.
  - Use `ResultPath: null` or `Output` to **discard** results you do not need.
  - Use **variables** to hold data you need later but not in the next state's input.
  - Use **Distributed Map + ResultWriter** so results go to S3, not back into the parent payload.
- The **request** to any Step Functions API is also limited to **1 MB** total, and the state machine **definition to 1 MB**.
- Distributed Map **child execution input** is also 256 KiB, but the **item read from CSV/JSON/JSONL can be up to 8 MB** if `ItemSelector` shrinks it before dispatch.
- Athena `getQueryResults` pages results; do not try to pull millions of rows into state. Write results to S3 and pass the location.

## J. Context object (`$$`)
- Read-only data about the current run. JSONPath: `$$.Execution.Id`; JSONata: `$states.context.Execution.Id`.
- Fields: `Execution.Id/Input/Name/RoleArn/StartTime`, `State.Name/EnteredTime/RetryCount`, `StateMachine.Id/Name`, `Task.Token`.
- Inside a Map: `Map.Item.Index`, `Map.Item.Value`. Distributed Map adds `Map.Item.Source`.
- `Execution.Input` is the **original input** of the execution, available at any point (useful after `ResultPath` overwrote things).
- `State.RetryCount` helps build **idempotency keys** that change per retry.
- Use `Execution.Name` (often set to a business ID) as a natural **idempotency key** for downstream writes.

## K. Choice and Wait patterns for data workflows
- **Polling loop**: Task (status call) → Choice → Wait → back to Task. Always add a **maximum attempt counter** in a variable, or the **25,000 event** limit ends the run.
- **Prefer `.sync` or callbacks** to polling. Polling costs transitions and history events.
- **Wait until a time**: `TimestampPath` computed from input (for example run at next midnight UTC).
- **Choice rule** example logic: if `$.rowCount > 0` → process; else → `Succeed` (nothing to do).
- **Data-quality gate**: Glue job → Choice on result → Fail or Continue; failure path writes to SNS.
- **Idempotent writes**: use the execution name or a `States.Hash` of the input as a key to deduplicate.

## L. IAM for integrations
- The state machine has an **execution role** (service principal `states.amazonaws.com` can assume it). All integration calls use this role, unless the Task sets `Credentials`.
- Optimized and SDK integrations need **explicit IAM actions** (for example `glue:StartJobRun`, `athena:StartQueryExecution`, `s3:GetObject`).
- `.sync` for Glue/Athena/Batch/EMR/ECS also needs **EventBridge rule permissions** (`events:PutTargets`, `events:PutRule`, `events:DescribeRule`) on the managed rule `StepFunctionsGetEventsForXxxRule`.
- `states:StartExecution` and `states:DescribeExecution` (and `states:StopExecution` for cancel) are needed for **nested `.sync`** workflows.
- When the state machine reads a **S3 dataset in Distributed Map**, the role needs `s3:ListBucket` (with `s3:prefix` condition) and `s3:GetObject`; to write results, `s3:PutObject`.
- **Cross-account**: set `Credentials.RoleArn` on the Task; that role in the other account must trust the state machine role.
- The console can **auto-generate** a role for the actions it sees in the definition. Regenerated roles may not cover dynamic resources chosen by paths at runtime.

## M. Exam skills mapping
- **1.3.1 Orchestrate ETL (Lambda, EventBridge, MWAA, Step Functions, Glue workflows)**: .sync and callback integrations for Glue, Athena, EMR, Batch.
- **3.1.1 Orchestrate pipelines (MWAA, Step Functions)**: data flow between states.
- **3.1.3 Call SDKs from code**: SDK integrations.
- **1.2.5 Choose transformation services (EMR, Glue, Lambda, Redshift)**: pick the transformation service to call.
- **4.1.4 IAM roles for access (Lambda, API Gateway, CLI, CloudFormation)**: execution role and integration IAM.

## N. Scenarios: "If X → Y, because Z"
- If a Glue job must finish before the next step → **`glue:startJobRun.sync`**, because `.sync` waits and fails the state if the job fails.
- If you need to wait for a Glue crawler → **SDK `startCrawler` + Wait/`getCrawler`/Choice loop**, because crawler start has no `.sync`.
- If you need the Athena result rows → **`startQueryExecution.sync` then `getQueryResults`**, because `.sync` only waits; it does not return rows.
- If a Redshift SQL statement may run for minutes → **Data API `executeStatement` + poll `describeStatement`** (or EventBridge callback), because the SDK call returns immediately.
- If a step needs human approval → **`sqs:sendMessage.waitForTaskToken` or `sns:publish.waitForTaskToken` + `HeartbeatSeconds`/`TimeoutSeconds`**, because the token resumes the exact task and timeouts prevent a year-long hang.
- If the next state gets Lambda's whole envelope → add **`OutputPath: $.Payload`** (or JSONata `Output`), because `lambda:invoke` wraps the function result.
- If you lost the original input after a Task → set **`ResultPath: $.taskResult`**, because the default `$` overwrites the input.
- If a notification step should not change the data → **`ResultPath: null`**, because it discards the result and keeps the input.
- If you get `States.DataLimitExceeded` → **move data to S3 and pass its key**; and add it to `ErrorEquals` explicitly if you want to catch it, because `States.ALL` does not catch it.
- If you need to carry a value across many states without bloating each input → **`Assign` a variable**, because variables are separate from the state payload.
- If an Express workflow must call Glue and wait → **use Standard** (or start Glue with request-response and poll), because Express has no `.sync`.
- If a task token is returned from a different AWS account → it **fails**, because tokens only work from principals in the same account.
- If a `.sync` job keeps running after the workflow was stopped → check the **role's stop permissions**, because cancellation is best-effort and needs IAM.
- If you call a service that has no optimized integration → **AWS SDK integration**, because it supports 200+ services without Lambda.
- If you need to call a SaaS REST API → **HTTP Task with an EventBridge connection**, because it stores credentials securely and avoids a Lambda.
- If one Lambda step is throttled during a Map → **lower `MaxConcurrency` and retry `Lambda.TooManyRequestsException` with jitter**, because the burst exceeds concurrency.

Verified from AWS docs on 2026-11-03 (integration patterns and optimized integrations table, error handling, variables and JSONata, Distributed Map ItemReader, service quotas, best practices).
Unconfirmed (verify): `states:startExecution.sync:2` output format; JSONata Output defaults per state type; list of Step Functions-specific JSONata helper functions; intrinsic function nesting depth; exact IAM actions for each `.sync` managed rule; the Redshift Data API EventBridge callback pattern; whether Pipes can start Express sync executions.

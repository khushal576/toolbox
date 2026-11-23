# AWS Step Functions – 4. Security, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Identity and access
### A1. Who can do what (callers)
- Callers use IAM actions such as `states:StartExecution`, `states:StartSyncExecution`, `states:DescribeExecution`, `states:StopExecution`, `states:SendTaskSuccess`, `states:SendTaskFailure`, `states:SendTaskHeartbeat`, `states:RedriveExecution`, `states:CreateStateMachine`, `states:UpdateStateMachine`, `states:PublishStateMachineVersion`.
- **`StartExecution` on an alias or version** needs permission on that ARN form. Granting only the base state machine ARN may not cover the alias ARN **(verify)**.
- `iam:PassRole` is required to create or update a state machine with an execution role. Scope it to that role and add `iam:PassedToService = states.amazonaws.com`.
- `SendTaskSuccess/Failure` callers need IAM permission on `*` (tokens, not ARNs, identify the task); the token acts like a secret. **Do not log or expose task tokens.**
- **Tag-based access (ABAC)**: state machines and activities can be tagged. **Executions inherit the state machine's tags** for authorization, so `aws:ResourceTag/...` conditions work on `DescribeExecution`, `StopExecution`.
- Tag rules: up to **50 tags**, key 128 chars, value 256 chars, `aws:` prefix reserved.
- **Resource-based policies** on state machines let other accounts start executions without assuming a role **(verify the current support and scope)**.
### A2. The execution role
- Each state machine has an **execution role** that the service assumes (trust `states.amazonaws.com`). Every Task call uses it.
- **Least privilege**: allow only the exact actions and resources used (specific Glue job ARN, specific bucket prefix).
- Prevent the **confused deputy** problem: trust policy conditions `aws:SourceArn` (the state machine ARN) and `aws:SourceAccount`.
- Roles created in the console are **auto-generated** for the integrations in the definition; they cannot cover resources chosen at runtime by paths. Review and tighten.
- If you delete the console-created role, Step Functions **cannot recreate it** the same way.
- For `.sync` patterns, include the **EventBridge managed rule permissions**.
- For logging, the role needs CloudWatch Logs delivery permissions (`logs:CreateLogDelivery`, `PutLogEvents`, … on `*`).
- For X-Ray tracing, the role needs `xray:PutTraceSegments`, `xray:PutTelemetryRecords`, `xray:GetSamplingRules`, `xray:GetSamplingTargets`.
- **Cross-account tasks**: set `Credentials.RoleArn` in the Task state to a role in the other account.
- **Cross-account `.sync`** uses polling only and still needs the right permissions in the target account.
- **Task tokens** cannot be returned from a different account.

## B. Encryption
- **At rest**: always encrypted with **AWS owned keys**; cannot be turned off.
- Optional **customer managed KMS key** (symmetric) adds a **second layer** for a **state machine** (definition + execution history/data) and for an **activity** (activity inputs). Works for **Standard and Express**.
- Settings: `EncryptionConfiguration` with `Type` (`CUSTOMER_MANAGED_KMS_KEY` or `AWS_OWNED_KEY`), `KmsKeyId`, `KmsDataKeyReusePeriodSeconds` (**60–900 s**, default **300 s**). Longer reuse = fewer KMS calls = lower cost.
- Permissions:
  - Creator: `kms:DescribeKey` and `kms:GenerateDataKey` (state machine); `kms:DescribeKey` (activity).
  - **Execution role**: `kms:Decrypt` and `kms:GenerateDataKey` (sync Express: `kms:Decrypt` only).
  - API callers of `DescribeExecution`, `GetExecutionHistory`, `DescribeStateMachine`, `StartSyncExecution` need `kms:Decrypt`. Some calls support `METADATA_ONLY` to avoid needing it.
- **Encryption context** is `aws:states:stateMachineArn` (or `aws:states:activityArn`). Use it in key/IAM policy conditions to bind a key to specific state machines.
- Do **not** add `kms:ViaService` to an **execution role** policy; it can block or fail executions.
- If CloudWatch Logs is enabled with a CMK: key policy must allow `delivery.logs.amazonaws.com` `kms:Decrypt`; the execution role needs `kms:GenerateDataKey` with the logs source ARN condition.
- A **disabled or deleted/pending-deletion key** fails running executions and blocks new ones; data encrypted under a deleted key is **unrecoverable**.
- Activity encryption is **immutable**: to change it you create a **new activity** (CloudFormation replaces the resource).
- With a CMK, **execution status-change EventBridge events omit** input, output, error and cause.
- **In transit**: TLS to the service and to integrations. Step Functions decrypts payload with your key before sending to another service over TLS.
- Never put **secrets in state input/output**: they appear in history, logs and console. Pass a **Secrets Manager / Parameter Store reference** and let the worker fetch it.
- Use **data masking**: avoid `includeExecutionData` in logs for sensitive data, or filter/redact with `Output`/`ResultSelector`.

## C. Network and private access
- Step Functions API endpoints are public by default. Use an **interface VPC endpoint (AWS PrivateLink)** so VPC workloads call Step Functions without the internet: service names `com.amazonaws.<region>.states` and **`com.amazonaws.<region>.sync-states`** (for Express synchronous executions) **(verify exact names)**.
- Attach an **endpoint policy** to restrict which state machines can be started via the endpoint.
- Step Functions itself is not inside your VPC; integrations to **private resources** (RDS, private APIs) go through **Lambda in VPC**, ECS/Batch in VPC, or the service's own network setting.
- **HTTP Task** calls public endpoints; for private APIs use **API Gateway private** or an EventBridge connection to a private API through **VPC Lattice** **(verify)**.
- Interface endpoints carry **data transfer** charges via PrivateLink.
- Activity workers (outside AWS or in VPC) poll `GetActivityTask` over HTTPS; they need network egress or a VPC endpoint.

## D. Audit and governance
- **CloudTrail** records Step Functions **management API calls** (CreateStateMachine, UpdateStateMachine, StartExecution, etc.). Data events for executions are not a CloudTrail data-event type **(verify)**; state-level detail lives in **execution history / logs**.
- **KMS usage** shows in CloudTrail (`Decrypt`, `GenerateDataKey`, `DescribeKey`) with the encryption context.
- **AWS Config** tracks state machine configuration **(verify resource type coverage)**.
- **Service Control Policies** can deny `states:*` actions or require encryption configuration via condition keys **(verify available keys)**.
- Keep **versions + aliases** as the approved release record; restrict `UpdateStateMachine` to the pipeline role.
- Use **tags** for owner, environment, cost center; activate them as **cost allocation tags**.

## E. Cost
### E1. What you pay
- **Standard**: per **state transition**. A transition is counted each time a step completes. **Retries count**; **redrives count**. Free tier **4,000 transitions per month** (does not expire). Example price: **$0.000025 per transition** in us-east-1 (about $25 per million) **(verify current price)**.
- **Express**: per **request** (about **$1.00 per million**) plus **duration** priced per **GB-second/GB-hour of memory × time**, rounded up to **100 ms**; memory billed in **64 MB** chunks. Estimate: 50 MB + definition size + (data size × number of Parallel/Map steps). Duration price is tiered by monthly GB-hours **(verify rates)**.
- **Distributed Map**: each child execution counts as one **state transition** for the parent when children are Standard; inline Map has **no per-iteration** transition charge. Batching cuts child count.
- **Other charges**: the services you call (Lambda, Glue, Athena…), **CloudWatch Logs** (vended logs rate), X-Ray traces, KMS requests, PrivateLink and data transfer.
- Waiting is **free** in Standard: a 7-day `Wait` or callback costs only the transitions around it.
### E2. How to cut cost
- **Remove unnecessary states**: Pass states used only for reshaping → use JSONata `Output` / `Assign`.
- **Prefer SDK/optimized integrations** over a Lambda-in-the-middle; fewer transitions and no Lambda fee.
- Use **`.sync` / callbacks** instead of polling loops (each loop turn is 3+ transitions).
- **Batch** items in Distributed Map (`ItemBatcher`) so one child handles many.
- **Nest Express inside Standard** for high-volume idempotent segments, or move the whole workflow to Express if it is ≤ 5 min and idempotent and needs no `.sync`/callbacks.
- **Avoid retries that cannot succeed** (data errors): each retry is a billed transition.
- Lower **log level** (`ERROR`/`FATAL`) and stop logging execution data on high-volume Express flows; log ingestion often costs more than the workflow itself.
- Increase **KMS data key reuse period** to cut KMS calls.
- Use Express **memory-efficient payloads**: keep payloads small (memory is billed).
- Rule of thumb: Standard is cheaper for **few, long, many-step-with-waits** flows; Express is cheaper for **huge numbers of short** executions.

## F. Monitoring
### F1. CloudWatch metrics (`AWS/States`)
- Execution metrics (per state machine ARN): `ExecutionsStarted`, `ExecutionsSucceeded`, `ExecutionsFailed`, `ExecutionsAborted`, `ExecutionsTimedOut`, `ExecutionThrottled`, `ExecutionTime`.
- **`ExecutionsStarted` is emitted twice per execution**; its `SampleCount` shows 2. Use the **Sum** statistic for counts, **Average** for time metrics.
- Express: `ExpressExecutionBilledDuration`, `ExpressExecutionBilledMemory`, `ExpressExecutionMemory`.
- Redrive: `ExecutionsRedriven`, `RedrivenExecutionsSucceeded/Failed/TimedOut/Aborted`.
- Account-level: `OpenExecutionCount`, `OpenExecutionLimit`, `ApproximateOpenMapRunCount`, `OpenMapRunLimit`, `ApproximateMapRunBacklogSize`, `ConsumedCapacity`, `ProvisionedBucketSize`, `ProvisionedRefillRate`, `ThrottledEvents` (dimension `ServiceMetric: StateTransition`, `APIName`).
- Versions/aliases: `VersionCount`, `AliasCount`; execution metrics carry `Version` / `Alias` dimensions.
- Service integration metrics (dimension `ServiceIntegrationResourceArn`): `ServiceIntegrationsStarted/Succeeded/Failed/TimedOut/Scheduled`, `...RunTime`, `...ScheduleTime`, `...Time`.
- Activity metrics (`ActivityArn`): `ActivitiesStarted/Succeeded/Failed/TimedOut/HeartbeatTimedOut`, `ActivityRunTime`, `ActivityScheduleTime`.
- Legacy Lambda metrics (`LambdaFunctionArn`) exist only for tasks that use the **Lambda ARN directly** in `Resource`; `lambda:invoke` emits service integration metrics.
- Usage metrics (`AWS/Usage`): `StateMachineCount`, `ActivityCount`, `OpenExecutionCountPerStateMachine`.
- Metrics are **best-effort**: late, missing or duplicated points are possible; they are not a billing record.
- Baseline alarms: `ExecutionsFailed > 0`, `ExecutionsTimedOut > 0`, `ExecutionThrottled > 0`, `OpenExecutionCount` Maximum ≥ **100K**, `ApproximateOpenMapRunCount` Maximum ≥ **900** (limit 1,000), `ApproximateMapRunBacklogSize > 0`, `ExecutionTime` p95 above normal.
### F2. Logs
- **Standard**: history is kept in Step Functions; logging to CloudWatch Logs is **optional**.
- **Express**: CloudWatch Logs is the **only** place to see history.
- `LoggingConfiguration`: `level` (`ALL`, `ERROR`, `FATAL`, `OFF`), `includeExecutionData` (true/false), `destinations` (log group ARN).
  - `ALL` logs every event; `ERROR` logs failures at task/map/parallel level and execution failures; `FATAL` logs only execution-level failure/abort/timeout; `OFF` nothing.
- Payload fields (`input`, `output`, `assignedVariables`) are **truncated** when large; check `inputDetails.truncated`.
- Log group name: prefix **`/aws/vendedlogs/states/`** to avoid the CloudWatch Logs **resource policy 5,120-character limit**. Max **10 resource policies** per Region per account.
- Log delivery is **best-effort** and does not slow the execution.
- Common error: `AccessDeniedException: The state machine IAM Role is not authorized to access the Log Destination` → fix the role's logs permissions or the resource-policy size.
- Query with **CloudWatch Logs Insights** (filter on `execution_arn`, `type`, `details.error`).
### F3. Tracing and events
- **X-Ray tracing**: enable `TracingConfiguration` to see the service map and latency per integration (supports upstream/downstream propagation for Lambda, SNS, SQS, API Gateway…). Express tracing included.
- **EventBridge**: Standard executions send **Execution Status Change** events (`RUNNING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `ABORTED`); Express sends them only if configured **(verify)**.
- **Console views**: execution graph, event table, per-state input/output, Map Run page (counts, failures, redrive button).
- Alert pattern: EventBridge rule on `FAILED/TIMED_OUT/ABORTED` → SNS/Slack/Chatbot. Include `stateMachineArn` and `executionArn`.

## G. Troubleshooting (symptom → cause → fix)
- **Execution fails with `States.Runtime`** → bad path / null input / unsupported expression → check the state input in the event view; fix the definition; not retriable.
- **`States.DataLimitExceeded`** → payload > 256 KiB → pass S3 keys, trim with `ResultSelector`/`Output`, discard with `ResultPath: null`.
- **`States.Timeout`** → task or whole run exceeded `TimeoutSeconds` or heartbeat missed → raise limit, fix worker heartbeat, check downstream health.
- **`States.Permissions`/AccessDenied** → execution role lacks IAM for the integration (or KMS) → add the exact action; for `.sync` add EventBridge managed rule actions.
- **Execution stuck "Running" for hours** → waiting on `.sync`/callback/activity with no timeout → set `TimeoutSeconds` + `HeartbeatSeconds`; check the worker polling `GetActivityTask`.
- **`ExecutionLimitExceeded`** → > 1,000,000 open Standard executions → shorten runs, alarm earlier, request increase.
- **`ThrottlingException` / `ExecutionThrottled`** → transition or start bucket exhausted (new accounts are lower) → jitter, spread load, request increase, use Express/Distributed Map.
- **Lambda `TooManyRequestsException`** → Lambda concurrency → lower Map concurrency, raise reserved concurrency, retry with backoff.
- **Map Run `States.ExceedToleratedFailureThreshold`** → failed items > threshold → check `FAILED_*.json` in the ResultWriter prefix; fix and **redrive**.
- **`States.ItemReaderFailed`** → bucket/key/permission/format error, cross-account or cross-Region bucket → same account/Region, correct `InputType`, add `s3:GetObject/ListBucket`.
- **Redrive not offered** → older than 14 days, Express, history ≥ 24,999 events, or started before 15 Nov 2023.
- **No logs for Express** → logging not enabled, role missing log permissions, or non-ASCII names.
- **`ExecutionAlreadyExists`** (Standard) → same name with different input while history exists → use a unique or deterministic-per-input name.
- **Callback never resumes** → token sent from another account, expired after timeout, or worker did not call `SendTaskSuccess/Failure` → use heartbeats and same-account callers.
- **Definition rejected** → >1 MB, invalid ASL, bad Express/Standard feature mix (`.sync` in Express) → run `ValidateStateMachineDefinition`.
- **Console sync run stops at 60 s** → console limit for Express sync → use SDK/CLI.
- **Cost surprise** → polling loops, verbose Express logs, excessive retries → switch to `.sync`, lower log level, fix retry policy.

## H. Limits cheat sheet
| Item | Value |
|---|---|
| Standard max duration | **1 year** |
| Express max duration | **5 minutes** |
| Standard history events | **25,000** (execution fails at the cap) |
| Execution history retention (Standard) | **90 days** (30 on request) |
| Payload per state/task/execution | **256 KiB** |
| State machine definition size | **1 MB** |
| API request size | **1 MB** |
| Name length (state machine, execution, activity) | **80 chars** |
| Registered state machines / activities | **100,000** each (up to 150,000) |
| Open Standard executions per account/Region | **1,000,000** |
| Open Map Runs | **1,000** |
| Distributed Map parallel children | **10,000**; dispatch 1,000/s Express, 100/s Standard |
| Inline Map concurrency | **40** |
| Map redrives | **1,000** |
| Map `MaxItems` | **100,000,000** |
| ItemReader S3 file | **10 GB**; item up to **8 MB** (CSV/JSON/JSONL) with `ItemSelector` |
| CSV header | **10 KiB** |
| Parquet row group / footer | **256 MB / 5 MB** |
| Variable | **256 KiB** each; **10 MiB** per execution; name ≤ 80 chars |
| Map `Label` | **40 chars** |
| Versions per state machine | **1,000** |
| Aliases per state machine | **100** |
| Redrive window | **14 days** |
| Tags per resource | **50** |
| HTTP Task duration | **60 s**; token bucket 300 |
| `StartExecution` Standard | bucket/refill **1,300/300** (us-east-1, us-west-2, eu-west-1); **800/150** others |
| `StartExecution` Express | **6,000/6,000** |
| State transitions Standard | **5,000/s** (big 3 Regions); **800/s** others; Express unlimited |
| `StartSyncExecution` console timeout | **60 s** |
| Retry `MaxAttempts` / `IntervalSeconds` default | **3 / 1 s**, `BackoffRate` **2.0**, jitter **NONE** |
| Activity pollers (recommended) | **≥ 100** open polls per activity ARN |
| KMS data key reuse | **60–900 s** (default 300) |
- Many quotas are **soft** and per Region per account; execution-level quotas are **hard**.

## I. Exam skills mapping
- **4.1.4 IAM roles for access (Lambda, API Gateway, CLI, CloudFormation)**: execution role.
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: VPC endpoints and policies.
- **4.3.2 Encryption keys (KMS)**: customer managed KMS key.
- **3.3.2 Logging and monitoring for auditing and traceability**: logging and X-Ray.
- **3.3.4 Troubleshoot performance**: metrics and troubleshooting.
- **3.3.5 CloudTrail for API calls**: CloudTrail for API activity.

## J. Scenarios: "If X → Y, because Z"
- If compliance needs customer-controlled encryption of workflow data → **customer managed KMS key on the state machine** (and activity), because it adds a second layer you can disable or audit.
- If the key is accidentally disabled → running executions **fail** and new ones cannot start, because Step Functions cannot decrypt the data keys; **re-enable** the key.
- If workloads in a private VPC must start executions without internet → **interface VPC endpoint for Step Functions (and sync-states for Express sync)**, because it keeps traffic on the AWS network.
- If you must restrict which roles can start production executions → **IAM policy on the state machine/alias ARN + tag-based (ABAC) conditions**, because executions inherit state machine tags.
- If a workflow in account A must call Glue in account B → **`Credentials.RoleArn` on the Task, trust policy from A's execution role**, because the task then runs with B's role.
- If task tokens leak → anyone with IAM permission can complete the task, so **treat tokens as secrets, do not log them, scope `SendTask*` permission**, because the token alone identifies the task.
- If Express logs cost too much → **log level `ERROR`/`FATAL`, `includeExecutionData` off, shorter retention**, because vended-log ingestion is billed per GB.
- If the Standard bill is dominated by polling loops → **switch to `.sync` or callback tokens**, because each loop iteration is multiple transitions.
- If a Standard flow has a high-volume idempotent section → **nest an Express child workflow**, because Express is priced per request and duration.
- If many Lambda wrapper functions only call AWS APIs → **replace them with SDK integrations**, because you remove Lambda cost, cold starts and code.
- If you need to know who changed a state machine → **CloudTrail** (`UpdateStateMachine`), because it records management calls with the caller identity.
- If you need end-to-end latency per step → **enable X-Ray + check `ServiceIntegrationRunTime`**, because it shows time per integration.
- If a canary version raises failures → **compare `ExecutionsFailed` by `Version` dimension and move the alias back**, because metrics are split per version.
- If account is new and transitions throttle → **expect lower initial quotas that AWS raises with usage**; request an increase before launch, because the default bucket is smaller.
- If an auditor needs 1 year of run history → **send logs to CloudWatch Logs/S3 with long retention**, because Standard console history is only 90 days (30 if reduced).
- If data in payloads is sensitive (PII) → **keep it in S3/DynamoDB with KMS, pass references, redact logs**, because state input/output appears in history and logs.

Verified from AWS docs on 2026-11-03 (service quotas, pricing, encryption at rest, CloudWatch metrics, CloudWatch Logs logging, best practices, versions and aliases, redrive).
Unconfirmed (verify): current per-transition and Express duration prices; resource-based policy support for state machines; exact VPC endpoint service names (`states`, `sync-states`); CloudTrail data-event coverage for executions; AWS Config resource type; SCP condition keys for Step Functions; alias-ARN IAM scoping; X-Ray permission list; Express status-change events to EventBridge; HTTP Task private-endpoint support.

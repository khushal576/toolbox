# EventBridge – 1. Event buses, rules, event patterns, targets, delivery, logging, global endpoints

Short notes. Each point is a fact you can be asked about.

## A. What EventBridge is (and is not)
- EventBridge = serverless event router. Producers send events to an event bus; rules match events and send them to targets.
- It was called CloudWatch Events. Same API (`events`), same default bus. Old docs and IAM role names still say "CloudWatch Events".
- Three parts under one name: event buses (many-to-many routing), Pipes (point-to-point source → target), Scheduler (time-based invocations).
- No servers, no shards, no capacity to size. You pay per event (or per request for Pipes/Scheduler).
- Pick it for: reacting to AWS service state changes (Glue job failed, file landed in S3), routing by content, SaaS events, cross-account event routing, decoupling microservices.
- Avoid it for: high-throughput ordered streams with replay by position (use Kinesis or MSK), work queues where consumers pull at their own pace (use SQS), very large payloads (max 1 MB per request).
- Not a queue: events are not stored for consumers to pull. If no rule matches, the event is gone.
- Not a stream: no ordering guarantee, no consumer offsets on the classic bus.
- Delivery is at least once. A target can get the same event twice. Make targets idempotent.
- Typical latency is sub-second from ingestion to target invocation **(verify)**; monitor `IngestionToInvocationStartLatency`.
- Regional service. Buses, rules and archives live in one Region. Cross-Region needs an event bus target in the other Region.

## B. Two kinds of custom bus (new in Sept 2026)
- On 24 Sept 2026 AWS launched a new "Custom Event Bus" (API namespace `eventsv2`, ARN `event-busv2/...`).
- All older buses that use rules and targets are now shown as "Custom Event Bus - Classic". They keep working unchanged.
- Exam note: the DEA-C01 guide (Dec 2025) predates this. Exam questions use the classic model: default bus, custom buses, rules, up to 5 targets, archive and replay.
- New bus routes with subscribers, not rules. One subscriber = filters + one target + retry policy + DLQ.
- New bus keeps every event for 1–365 days (default 1 day). A subscriber can start from a past position, which is how it replays.
- New bus offers FIFO delivery per event group (`EventGroupId`) for subscribers that opt in. Classic has no ordering.
- New bus deduplicates at publish time (content hash or your key) within a fixed 5-minute window.
- New bus adds `PutRawEvents` for Avro, Protobuf and raw bytes. Classic `PutEvents` is JSON only.
- New bus is shared across accounts with AWS RAM. Each consumer account creates and owns its own subscribers.
- New bus quotas: 5 buses per account per Region (adjustable), 10,000 subscribers per bus, 500,000 events/s per bus (fixed), up to 100 entries per publish.
- New bus default retry is 5 attempts within 300 seconds (classic default is 185 attempts over 24 hours). Do not mix the two up.
- New bus pricing is per GB (ingress, egress per delivery, storage) instead of per million events.
- The rest of this guide describes the classic model unless it says "new bus".

## C. Event structure
- Every event is JSON with the same envelope: `version`, `id`, `detail-type`, `source`, `account`, `time`, `region`, `resources`, `detail`.
- `version` is always `"0"`. `id` is a UUID that EventBridge generates per event; use it as the idempotency key in targets.
- `detail-type` + `source` together identify the event type (for example `"Glue Job State Change"` + `"aws.glue"`).
- `source` for AWS services always starts with `aws.` (for example `aws.s3`). Custom events cannot use the `aws.` prefix.
- AWS recommends reverse-domain names for custom sources (for example `com.mycompany.orders`).
- `account` = 12-digit account ID where the event came from. Use it in patterns to filter cross-account events.
- `time` is set by the producer or by EventBridge. It can be earlier than when EventBridge received the event.
- `resources` = array of ARNs. The producer decides what goes in. CloudTrail API-call events have it empty.
- `detail` = JSON object with the event body. Can be `{}`.
- `replay-name` appears only on events re-sent by an archive replay.
- A valid custom event needs at least `source`, `detail-type` and `detail`.

## D. Bus types on the classic model
- Default bus: one per account per Region, already exists, cannot be deleted. AWS service events arrive here.
- Custom bus: you create it for your own application events. Good for separating domains and for per-bus permissions.
- Partner bus: receives events from a SaaS partner (for example Datadog, Zendesk, Shopify, Salesforce via AppFlow).
- Partner flow: partner creates a partner event source for your account → you associate it with a partner bus (name = `aws.partner/...`).
- Partner events sent to a source that is not yet associated with a bus are dropped immediately.
- Only the partner's account can send to a partner bus. `PutPermission` or a bus policy on a partner bus fails.
- AWS service events go only to the default bus. To use them on a custom bus, add a rule on the default bus that targets the custom bus.
- Rules belong to one bus. A rule on a custom bus never sees default-bus events unless they are forwarded.
- Classic quotas: 100 event buses per account per Region (adjustable), 300 rules per bus (100 in af-south-1, eu-south-1), adjustable.

## E. AWS service events
- Many services publish state-change events to the default bus for free (no charge to ingest AWS management events).
- Delivery level from the service is either best effort (rarely lost) or durable (at least once). Check per service.
- Data-pipeline events you should know (all on the default bus):

| Service | detail-type | Notes |
|---|---|---|
| Glue | `Glue Job State Change` | states SUCCEEDED, FAILED, TIMEOUT, STOPPED |
| Glue | `Glue Job Run Status` | RUNNING/STARTING/STOPPING past the job delay notification threshold (must set threshold) |
| Glue | `Glue Crawler State Change` | Started, Succeeded, Failed |
| Glue | `Glue Data Catalog Table State Change` / `Database State Change` | best effort, may be out of order or missing |
| Step Functions | `Step Functions Execution Status Change` | source `aws.states`; Standard workflows only, not Express |
| EMR | `EMR Cluster State Change`, `EMR Step Status Change` **(verify)** | step FAILED → alert |
| Batch | `Batch Job State Change` | FAILED, SUCCEEDED etc. |
| Athena | `Athena Query State Change` **(verify)** | query SUCCEEDED/FAILED |
| DMS | `DMS Replication Task State Change` **(verify)** | task stopped/failed |
| Redshift Data API | `Redshift Data Statement Status Change` **(verify)** | async SQL finished |
| S3 | `Object Created`, `Object Deleted`, ... | only if the bucket has EventBridge turned on |

- Glue job events are the standard way to alert on failure: rule `source=aws.glue`, `detail-type=Glue Job State Change`, `detail.state=["FAILED","TIMEOUT"]` → SNS.
- Step Functions Express workflows send no EventBridge events. Monitor them with CloudWatch Logs.
- Step Functions event detail can be truncated. Call `DescribeExecution` for full input/output.
- CloudTrail delivers API calls as `detail-type: "AWS API Call via CloudTrail"`. Needs an active CloudTrail trail.
- Other CloudTrail detail-types: `AWS Console Signin via CloudTrail`, `AWS Console Action via CloudTrail`, `AWS Service Event via CloudTrail`, `AWS Insight via CloudTrail`, `AWS Network Activity Event via CloudTrail`.
- Write (mutating) management events match normal `ENABLED` rules.
- Read-only management events (Get/List/Describe) match only rules in state `ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`.
- Trap: forwarding read-only events to another bus needs that special state on both the forwarding rule and the destination rule.
- S3 object-level API calls (data events) reach EventBridge only if the trail logs S3 data events. Costs CloudTrail data-event fees.
- Global services (IAM, Route 53) emit CloudTrail events only in us-east-1. A rule in another Region never sees them.
- CloudTrail-based events are slower (can take minutes) than native service events **(verify)**. Prefer native events when they exist.

## F. S3 to EventBridge vs S3 Event Notifications
- S3 Event Notifications (classic) send to SQS, SNS, Lambda or EventBridge. Configured per bucket, per event type, with prefix/suffix filters.
- S3 → EventBridge must be turned on per bucket (bucket properties: "Send notifications to Amazon EventBridge: On"). Off by default.
- Once on, S3 sends all supported event types to the default bus in the same account and Region. You cannot pick types in S3; you filter in rules.
- S3 EventBridge detail-types: Object Created, Object Deleted, Object Restore Initiated/Completed/Expired, Object Storage Class Changed, Object Access Tier Changed, Object ACL Updated, Object Tags Added/Deleted, Object Retention Updated, Object Annotation Created/Removed.
- `detail.reason` says how: `PutObject`, `POST Object`, `CopyObject`, `CompleteMultipartUpload`; for deletes `DeleteObject` or `Lifecycle Expiration`.
- `detail.deletion-type` is `Permanently Deleted` or `Delete Marker Created`.
- Key fields to match: `detail.bucket.name`, `detail.object.key`, `detail.object.size`.

| | S3 Event Notifications | S3 → EventBridge |
|---|---|---|
| Setup | per event type + destination | one switch on the bucket |
| Destinations | SQS (standard), SNS (standard), Lambda | 20+ target types, other buses, other accounts/Regions |
| Filtering | key prefix and suffix only | full patterns: prefix, suffix, wildcard, numeric size, anything-but, `$or` |
| Overlap | overlapping prefixes for the same event type are rejected | many rules can match the same event |
| Fan-out | one destination per config (use SNS for more) | up to 5 targets per rule, 300 rules |
| Archive/replay | no | yes |
| Extra cost | none | EventBridge pricing applies **(verify)** |

- Pick EventBridge when you need content filters (size > 0, `.csv` only under `raw/`), multiple consumers, or direct Step Functions/Glue workflow/ECS targets.
- Pick plain notifications for the simplest S3 → Lambda or S3 → SQS path.
- Trap: enabling EventBridge does not remove existing notifications. Both run side by side.
- Trap: an S3 bucket used as a log destination with EventBridge on can loop or disturb log delivery. Avoid it.

## G. Sending custom events (PutEvents)
- `PutEvents` takes up to 10 entries per request.
- Total request size must be under 1 MB (1,048,576 bytes). One entry can use the whole 1 MB.
- Older docs, practice exams and many blogs say 256 KB. The limit was raised to 1 MB **(verify the date)**; pricing still counts each 64 KB chunk as one event.
- Entry size = `Source` + `DetailType` + `Detail` + each `Resources` string (UTF-8 bytes) + 14 bytes if `Time` is set.
- For bigger data, store it in S3 and put the object URL in the event (claim-check pattern).
- Partial failure: the call returns HTTP 200 with `FailedEntryCount` > 0. Retry only entries that have an `ErrorCode`.
- Trap: `PutEvents` to a bus name that does not exist returns 200 and the event is silently dropped. Not counted as failed.
- `PutEvents` throttle (classic) per account per Region: 10,000/s in us-east-1, us-west-2, eu-west-1; lower elsewhere (400/s in smaller Regions). Adjustable. Throttled calls get `ThrottlingException`; back off and retry.

## H. Rules
- A rule watches one bus. It has either an event pattern or a schedule (not both).
- Event-pattern rule: runs when an event matches the pattern.
- Scheduled rule (legacy): runs on `rate()` or `cron()`. Only on the default bus. UTC only. 1-minute minimum precision.
- AWS now calls scheduled rules legacy and recommends EventBridge Scheduler (time zones, one-time schedules, flexible windows, millions of schedules).
- Classic cron has 6 fields: minutes, hours, day-of-month, month, day-of-week, year. Use `?` in day-of-month or day-of-week.
- Rule states: `ENABLED`, `DISABLED`, `ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`.
- Managed rules are created by AWS services (for example archives, Pipes event sources). You cannot edit them.
- New or changed rules and targets take a short time to take effect. A test event sent at once may not match.
- Infinite loop trap: a rule that reacts to a change and then makes the same change fires forever. Write patterns that only match the bad state.
- Use AWS Budgets alarms to catch runaway loops, because each loop event costs money.
- Rule throttling: when invocations exceed the account's invocation quota, invocations are delayed, not dropped. Metric `ThrottledRules` rises.

## I. Event pattern rules of matching
- A pattern has the same shape as the event. Include only the fields you want to test. Other fields are ignored.
- Every field in the pattern must exist in the event, with the same nesting, for a match (fields are AND).
- Values are always in a JSON array. Values in one array are OR: `"source": ["aws.ec2", "aws.glue"]`.
- If the event field is an array, the pattern matches when any element matches.
- String matching is exact, character by character, case sensitive. `"FAILED"` does not match `"failed"`.
- Use `equals-ignore-case` when case varies.
- Numbers are compared by their string form for plain matching: 300, 300.0 and 3.0e2 are not equal. Use `numeric` for math compare.
- `null` and empty string `""` are distinct values you can match.
- Duplicate keys in a pattern: only the last one counts. No error.
- Event pattern size max 2,048 characters (adjustable).
- Comparison operators work only on leaf values, except `$or` and `anything-but`.
- ARNs are matched exactly. Many services treat `:` and `/` as the same in ARNs; EventBridge does not.
- Test patterns with `TestEventPattern` API or the console Sandbox before relying on them.
- To match cross-account events only from known accounts, add `"account": ["111122223333"]`. Never put `"*"` in `account`; it matches nothing.

## J. Content filtering operators
| Operator | Example | Pipes support |
|---|---|---|
| Exact / OR list | `"state": ["FAILED", "TIMEOUT"]` | yes |
| prefix | `"key": [{"prefix": "raw/"}]` | yes |
| suffix | `"key": [{"suffix": ".csv"}]` | yes |
| prefix/suffix ignore case | `[{"suffix": {"equals-ignore-case": ".CSV"}}]` | yes |
| equals-ignore-case | `[{"equals-ignore-case": "failed"}]` | yes |
| anything-but | `[{"anything-but": ["SUCCEEDED"]}]` | yes |
| anything-but prefix/suffix/wildcard/ignore-case | `[{"anything-but": {"prefix": "tmp/"}}]` | no (buses only) |
| numeric | `[{"numeric": [">", 0, "<=", 1048576]}]` | yes |
| exists | `[{"exists": true}]` / `false` | yes |
| cidr (IP) | `[{"cidr": "10.0.0.0/24"}]` IPv4 and IPv6 | yes |
| null / empty | `[null]` / `[""]` | yes |
| wildcard | `[{"wildcard": "raw/*/data-*.csv"}]` | no (buses only) |
| $or | `"$or": [{"a": ["x"]}, {"b": ["y"]}]` | yes |

- `prefix` and `suffix` work on string values only.
- `anything-but` works on a string, a number, or a list of only strings or only numbers.
- `numeric` uses 64-bit floating point; exact for integers up to ±2^53. Values outside that are rejected in rules.
- `exists` works on leaf nodes only, not on intermediate objects.
- `exists: false` matches events where the field is missing (useful for "no error field").
- Wildcard: `*` matches any characters. Consecutive `**` is not allowed. Escape a literal `*` as `\*`.
- Only 30 rules per bus may contain wildcards (fixed). Complex wildcard patterns fail with `InvalidEventPatternException`.
- `$or` limit: multiplied combinations across all `$or` arrays must stay at or under 1,000.
- Plain lists give OR within one field; `$or` gives OR across different fields.
- Example S3 pattern: `source=aws.s3`, `detail-type=Object Created`, `detail.bucket.name=[my-bucket]`, `detail.object.key=[{"prefix":"raw/"}]`, `detail.object.size=[{"numeric":[">",0]}]`.

## K. Targets
- Up to 5 targets per rule. Fixed, cannot be raised. For more, use more rules, an SNS topic, or another bus.
- Classic rule targets: API destinations, event buses (same or other account/Region), API Gateway, AppSync, Batch job queue, CloudWatch log group, CodeBuild project, CodePipeline, EBS CreateSnapshot, EC2 Image Builder, EC2 Reboot/Stop/Terminate, ECS task, Firehose stream, Glue workflow, Incident Manager response plan, Kinesis stream, Lambda (async), Redshift cluster and Redshift Serverless Data API, SageMaker AI pipeline, SNS topic, SQS standard/FIFO/fair queues, Step Functions state machine (async), SSM Automation, SSM OpsItem, SSM Run Command.
- Trap: a Glue job is not a direct target. Glue workflow is. To start one job, use a workflow with an EVENT trigger, Step Functions, Lambda, or Scheduler universal target `glue:startJobRun`.
- Glue workflow target needs `glue:notifyEvent` permission. The workflow's EVENT trigger can batch events (batch size plus window up to 900 s).
- Lambda and Step Functions are invoked asynchronously. EventBridge does not wait for the function result.
- Redshift Data API target runs SQL (`RedshiftDataParameters`). Good for "run a stored procedure when a file lands".
- SQS FIFO target needs `SqsParameters.MessageGroupId`.
- ECS task target calls `RunTask` (Fargate or EC2) with overrides from the input transformer.
- CloudWatch Logs target: without a transformer, the event is the log message. With a transformer the template must be `{"timestamp":..., "message":...}`.
- Dynamic path parameters: target fields like `EcsParameters`, `RedshiftDataParameters`, `SqsParameters`, `HttpParameters` can be `$.detail.x`. The whole value must be one JSON path.
- Permissions per target: Lambda, SNS, SQS (and CloudWatch Logs) can use a resource-based policy. Other targets need an IAM execution role that trusts `events.amazonaws.com`.
- EventBridge now supports IAM execution roles for all target types. If no role is set on Lambda/SNS/SQS, it falls back to the resource policy.
- Encrypted SQS/SNS target with a customer managed KMS key: the key policy must allow `events.amazonaws.com` `kms:Decrypt` and `kms:GenerateDataKey`.
- Trap: SQS queues using the AWS managed key `aws/sqs` cannot be EventBridge targets or DLQs, because you cannot edit that key policy **(verify wording; docs say "AWS owned key")**.

## L. Target input and input transformer
- Four input options per target: matched event (default, whole event), part of the matched event (`InputPath`, for example `$.detail`), constant JSON (`Input`), input transformer.
- Input transformer = `InputPathsMap` (define up to 100 variables from JSON paths) + `InputTemplate` (text or JSON using `<var>`).
- Reserved variables: `<aws.events.rule-arn>`, `<aws.events.rule-name>`, `<aws.events.event.ingestion-time>`, `<aws.events.event>`, `<aws.events.event.json>`.
- `aws.events.event.json` = full original event; `aws.events.event` = event without `detail`. Both only as JSON values, not inside strings.
- Do not quote variables that hold objects or arrays. Strings are quoted automatically in JSON templates.
- A variable whose path does not exist is not created; it silently disappears from the output. No validation at create time.
- Use the transformer to shape events for API destinations, API Gateway, ECS overrides, CodeBuild `StartBuild`, SNS human-readable messages.
- Constant input is common for scheduled rules: pass a fixed JSON payload such as `{"run":"nightly"}`.

## M. Delivery, retries and DLQs
- At-least-once delivery. Rarely, a rule can fire twice for one event, or a target can be invoked twice.
- No ordering guarantee across events. Use event `time` or a sequence number in `detail` when order matters.
- Idempotency: dedupe on `id` (or a business key) in DynamoDB with a conditional write, or use SQS FIFO deduplication.
- Retry policy per target: default 24 hours max event age and 185 attempts, exponential backoff with jitter.
- Retry ranges: `MaximumEventAgeInSeconds` 60–86,400; `MaximumRetryAttempts` 0–185.
- Retried errors: throttling, timeouts, target unavailable, 5xx-type failures.
- Not retried (straight to DLQ or dropped): missing permissions, target no longer exists, invalid address/DNS failure.
- After retries run out the event is dropped unless a DLQ is set.
- DLQ = standard SQS queue. FIFO queues not allowed. Must be in the same Region as the rule. Can be in another account with a queue policy.
- DLQ messages carry attributes: `RULE_ARN`, `TARGET_ARN`, `ERROR_CODE`, `ERROR_MESSAGE`, `EXHAUSTED_RETRY_CONDITION`, `RETRY_ATTEMPTS`.
- Useful `ERROR_CODE` values: `NO_PERMISSIONS`, `NO_RESOURCE`, `THROTTLING`, `TIMEOUT`, `FAILED_TO_ASSUME_ROLE`, `CROSS_ACCOUNT_INGESTION_FAILED`, `THIRD_ACCOUNT_HOP_DETECTED`.
- The console adds the SQS queue policy for you. With the API or IaC you must add it (`sqs:SendMessage` for `events.amazonaws.com`, `aws:SourceArn` = rule ARN).
- Redrive: drain the DLQ with a Lambda event source mapping or your own SQS consumer, then re-put events.
- Metrics: `InvocationsSentToDlq` and `InvocationsFailedToBeSentToDlq`.
- Trap: a slow target that throttles for a long time may not get retried at all. Put SQS in front of fragile targets.

## N. Event bus resource policies
- Each bus can have a resource-based policy that says who may `events:PutEvents` (and manage rules) on it.
- Used to let other accounts or a whole AWS Organization send events: `Principal` = account, or `"*"` with `Condition aws:PrincipalOrgID`.
- Can restrict by `events:source` or `events:detail-type` condition keys **(verify key names)**.
- Policy size limit 10,240 characters per bus (adjustable). Use the org condition instead of listing many accounts.
- Default bus accepts AWS service events and same-account `PutEvents` without any policy.

## O. Event bus logging (launched 2025)
- A bus can send its own processing logs to CloudWatch Logs, Firehose and/or S3. Off by default.
- Log levels: `OFF`, `ERROR`, `INFO`, `TRACE`. Each level includes the previous one.
- `ERROR`: ingestion failed, invocation failed, throttled, retryable/permanent failure, sent to DLQ.
- `INFO` adds: event ingested, rule matched, no rules matched, invocation started/succeeded.
- `TRACE` adds every step (event received, rule matching started, each attempt).
- Optional "include detail data": event detail, target input, target request. Can contain sensitive data.
- Logs AWS service events only if they match a rule; logs all `PutEvents`, partner and replayed events.
- Best effort: completeness and timing not guaranteed.
- Log records are capped at 1 MB; large fields are dropped and listed in `dropped_fields`.
- With a customer managed key on the bus, `detail` and `error` in the logs are encrypted with that key.
- This is the first tool to answer "did my rule match?" without guessing. `No Rules Matched` at INFO proves a pattern problem.

## P. Global endpoints (Regional failover)
- Global endpoint = one URL for `PutEvents` that routes to a bus in a primary Region and fails over to a secondary Region.
- Health is a Route 53 health check, usually tied to a CloudWatch alarm on the primary bus.
- Failover sends custom events to the secondary Region within minutes. RTO and RPO about 360 s, max 420 s, if you follow AWS alarm guidance.
- Only custom events (your `PutEvents`) are covered. AWS service events and partner events are not.
- Custom buses must exist in both Regions with the same name in the same account.
- Event replication (recommended): sends every custom event to both Regions via managed rules. Needed for automatic failback.
- Without replication you must manually set the health check back to healthy to return to primary.
- No extra charge for the endpoint itself; events are billed as custom events, and replication adds cost.
- SDK must have the AWS Common Runtime (CRT) and uses SigV4A signing. Add `EndpointId` and `EventBusName` to `PutEvents`.
- Supported in a list of major Regions (US, Canada, Europe, Asia Pacific, São Paulo). Quota 100 endpoints per account per Region.

## Scenarios: "If X → Y, because Z"
- **If** an AWS Glue job fails and the team needs an email, **then** create a rule on the **default event bus** with `source=aws.glue`, `detail-type=Glue Job State Change` and `detail.state` = `FAILED` or `TIMEOUT`, and send it to an **Amazon Simple Notification Service (SNS)** topic, which emails the team. **This works because** Glue publishes job state-change events to the default bus by itself, and AWS service events are **free** to ingest. Match the state in **capital letters**, because matching is case sensitive.
- **If** a CSV file landing under `raw/` in Amazon S3 must start a Glue workflow, **then** turn on **"Send notifications to Amazon EventBridge"** for the bucket and create a rule on the **default bus** that matches `Object Created` with a **prefix** `raw/` and **suffix** `.csv` on `detail.object.key`. Its target is the **Glue workflow**, whose **EVENT trigger** starts the run. **This works because** a single Glue job is **not** a direct rule target, but a Glue workflow is. The rule's role needs the `glue:notifyEvent` permission.
- **If** the same S3 event must reach AWS Lambda, AWS Step Functions and an event bus in another account, **then** turn on EventBridge for the bucket and add **one rule with 3 targets**. **This works because** a rule can have up to **5 targets**, and buses in other accounts are valid targets, while classic **S3 Event Notifications** send to only **one destination per configuration** (you would need SNS to fan out).
- **If** S3 events never arrive in EventBridge, **then** check that **"Send notifications to Amazon EventBridge"** is **on** in the bucket properties. **This works because** this switch is **off by default**, and nothing is sent until it is on.
- **If** a rule lives on a **custom bus** and must react to S3 events, **then** add a **forwarding rule on the default bus** that targets the custom bus. **This works because** AWS service events (S3 included) land **only on the default bus**, and a rule only sees events on its own bus.
- **If** a pattern uses `"state": ["failed"]` and never matches, **then** write `"FAILED"` exactly as the event does, or use the **`equals-ignore-case`** operator. **This works because** EventBridge matches strings **exactly, character by character, case sensitive**.
- **If** a rule must ignore zero-byte "folder" objects in S3, **then** add `detail.object.size: [{"numeric": [">", 0]}]` to the pattern. **This works because** the S3 console creates **0-byte keys ending in `/`** for folders, and the **`numeric`** operator drops anything with size 0.
- **If** a rule must match every file **except** temporary files, **then** use **`anything-but`** combined with **`prefix`** (for example `tmp/`) or **`wildcard`** on the object key. **This works because** these combinations are allowed in **event bus** rules. The catch: **EventBridge Pipes** filters do **not** support them, so this only works on buses.
- **If** a rule needs **7 targets**, **then** split it into **two rules** with the same pattern, or send it to one **SNS topic** or **another event bus** that fans out further. **This works because** a rule can have at most **5 targets**, and this limit is **fixed** (it cannot be raised).
- **If** an event payload is **3 MB**, **then** store the data in **Amazon S3** and send only a pointer (the object URL) in the event; this is the **claim-check pattern**. **This works because** one **`PutEvents`** request is limited to **1 MB** in total. Smaller events also cost less, because each **64 KB** chunk is billed as one event.
- **If** a producer logs success but its events vanish, **then** check the **event bus name** it sends to. **This works because** **`PutEvents`** to a bus that does not exist returns **HTTP 200** and silently drops the event; it is not even counted as a failed entry.
- **If** **`PutEvents`** returns 200 but some entries are missing, **then** read **`FailedEntryCount`** in the response and retry **only** the entries that have an **`ErrorCode`**. **This works because** a partial failure does **not** raise an error: the call still returns HTTP 200.
- **If** a target receives duplicate events, **then** make it **idempotent** by deduplicating on the event **`id`** (for example a conditional write in **Amazon DynamoDB**). **This works because** delivery is **at least once**, so the same event can arrive twice, and `id` is a unique value EventBridge gives each event.
- **If** events must be processed in **strict order**, **then** send them through an **Amazon Simple Queue Service (SQS) FIFO** queue or **Amazon Kinesis Data Streams**, or use the **new Custom Event Bus** with **event groups** (`EventGroupId`). **This works because** classic buses give **no ordering guarantee**, while FIFO queues, Kinesis shards and new-bus event groups keep order.
- **If** a target was down for **30 hours**, **then** expect every event older than **24 hours** to be **dropped**, unless a **dead-letter queue (DLQ)** is set on the target. **This works because** the default retry policy keeps retrying for at most **24 hours** (max event age) and **185 attempts**; after that, events go to the DLQ or are lost. The DLQ must be a **standard SQS** queue.
- **If** events go to the DLQ **at once** with `ERROR_CODE` **`NO_PERMISSIONS`**, **then** fix the target's **IAM role** or its **resource-based policy** (for Lambda, SNS or SQS). **This works because** permission errors are **not retried**: EventBridge sends them straight to the DLQ.
- **If** creating a DLQ fails because it is a **FIFO** queue, **then** use a **standard SQS queue** in the same Region. **This works because** EventBridge DLQs must be **standard SQS**; FIFO queues are not allowed.
- **If** you need to react to **AWS Identity and Access Management (IAM)** `CreateUser` calls, **then** create the rule in **us-east-1** and make sure an **AWS CloudTrail** trail is on. **This works because** API calls reach EventBridge as **"AWS API Call via CloudTrail"** events, which need an active trail, and **global services** like IAM emit these events **only in us-east-1**. A rule in any other Region never sees them.
- **If** a rule must react to read-only calls such as `GetObject` or `ListBuckets`, **then** set the rule state to **`ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS`**. For object calls like `GetObject`, the **CloudTrail** trail must also log **S3 data events** (which cost extra). **This works because** normal **`ENABLED`** rules match only **write** (mutating) management events; read-only events are excluded by default.
- **If** you must alert on failures of **Step Functions Express** workflows, **then** use **Amazon CloudWatch Logs** and metrics. **This works because** Express workflows send **no EventBridge events**; only Standard workflows emit `Step Functions Execution Status Change`.
- **If** a nightly job must run at **02:00 New York time** all year, **then** use **EventBridge Scheduler** with a **cron** schedule and the time zone `America/New_York`. **This works because** Scheduler understands time zones and **daylight saving time (DST)**, while legacy **scheduled rules** run in **UTC only**, so their local hour shifts when the clocks change.
- **If** a target expects a specific JSON body, **then** use an **input transformer**: `InputPathsMap` picks values from the event, and `InputTemplate` builds the body. **This works because** by default the target gets the **whole event**, envelope included. Catch: a path that does not exist silently disappears, with no check at create time.
- **If** an auditor asks why an event did not reach a target, **then** turn on **event bus logging** at **`INFO`** or **`TRACE`** level, sent to CloudWatch Logs, Firehose or S3. **This works because** bus logs record each step: event ingested, **rule matched** or **"No Rules Matched"**, and each invocation attempt. Logging is **best effort**, and with detail data on it may copy sensitive fields.
- **If** producers must keep sending events during a **Regional outage**, **then** use a **global endpoint** with **event replication** and an **Amazon Route 53 health check** (usually tied to a CloudWatch alarm on the primary bus). **This works because** the endpoint gives one URL for `PutEvents` and fails **custom events** over to the secondary Region in about **6–7 minutes** (RTO/RPO about **360 s**, max **420 s**). Catch: AWS service and partner events are **not** covered, and the bus must exist in both Regions with the same name.

Verified from AWS docs on 2026-11-03 (EventBridge user guide: what is EventBridge, Custom Event Bus overview, event structure reference, event patterns and comparison operators, PutEvents, targets, input transformation, retry policy, DLQ, event bus logs, global endpoints, CloudTrail events, quotas, troubleshooting; S3 user guide EventBridge pages; Glue EventBridge events and Glue workflow EventBridge trigger; Step Functions EventBridge integration; AWS What's New for the Sept 2026 bus relaunch).
Unconfirmed (verify): typical sub-second latency figure; the date the PutEvents limit moved from 256 KB to 1 MB; exact detail-type strings for EMR, Athena, DMS and Redshift Data API events; CloudTrail event delay; S3-to-EventBridge charge on the default bus; bus policy condition key names; SQS "AWS owned key" vs AWS managed key wording for target/DLQ encryption.

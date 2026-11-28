# EventBridge – 2. Pipes, Scheduler, archive and replay, schemas, API destinations, cross-account routing, pipeline patterns

Short notes. Each point is a fact you can be asked about.

## A. EventBridge Pipes: what and why
- Pipe = point-to-point integration: one source → optional filter → optional enrichment → one target.
- It replaces "glue code" Lambda functions that only poll a queue or stream and forward data.
- A pipe polls the source for you (like a Lambda event source mapping), so the source does not need to push.
- Event buses = many-to-many routing. Pipes = one-to-one. They combine well: pipe from DynamoDB Streams → event bus → many rules.
- Execution role: the pipe assumes one IAM role (principal `pipes.amazonaws.com`) to read the source, call enrichment and call the target.
- You pay only for events that pass the filter. Filtered-out events are free.
- Pipe states: `CREATING`, `STARTING`, `RUNNING`, `STOPPING`, `STOPPED`, `UPDATING`, plus failure states with a `StateReason`.
- Quotas: 1,000 pipes per account per Region; concurrent pipe executions 3,000 in us-east-1, us-west-2, eu-west-1 and 1,000 elsewhere (contact support to raise).
- One pipe execution (enrichment + target) can run at most 5 minutes. Cannot be raised.
- Payload limit 6 MB, but the real limit is the smaller of 6 MB and the target's limit (event bus 1 MB, Step Functions 256 KB).

## B. Pipes sources
- Sources: SQS (standard and FIFO), Kinesis Data Streams, DynamoDB Streams, Amazon MSK, self-managed Apache Kafka, Amazon MQ (ActiveMQ and RabbitMQ).
- Not a source: S3, SNS, an event bus, or HTTP. For those, use rules or other integrations.
- Stream sources (Kinesis, DynamoDB) take a starting position: `TRIM_HORIZON` or `LATEST` (Kinesis also `AT_TIMESTAMP` **(verify)**).
- Kafka and MQ sources inside a VPC need network access to Pipes: a NAT gateway or a `pipes-data` VPC endpoint.
- MSK clusters must have security groups, or the pipe fails with a `StateReason`.
- Pipe needs source read permissions, for example `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes`.
- Source encrypted with a customer managed KMS key: add `kms:Decrypt` for the pipe role in the key policy and the role policy.

## C. Pipes filtering
- Filters use the same event pattern syntax as rules, applied to the source record.
- Field names depend on the source: SQS message body is under `body`, Kinesis payload under `data`, DynamoDB change under `dynamodb` **(verify)**.
- Filtering on `body`/`data` content works only when the payload is valid JSON.
- Pipes do not support `wildcard` or `anything-but` combined with prefix/suffix/wildcard/ignore-case. Plain `anything-but`, prefix, suffix, numeric, exists, cidr and `$or` work.
- SQS messages that do not match the filter are deleted from the queue (not left behind) **(verify)**.
- Filter early to save money, because enrichment and target calls are billed per pipe request.

## D. Pipes enrichment
- Enrichment options: Lambda, Step Functions Express workflow, API Gateway, API destination.
- Enrichment is always synchronous (`REQUEST_RESPONSE`). The pipe waits for the answer.
- Step Functions Standard workflows cannot enrich, because they cannot run synchronously. The pipe is stopped if you try.
- Enrichment response max 6 MB.
- Enrichment can act as a filter: return `""`, `{}` or `[]` to skip the target. Return `[{}]` to call the target with an empty payload.
- Enrichment can return a shorter or longer array than the batch it got, but not bigger than the target's batch limit.
- Partial batch failure handling is not supported for the enrichment step (only for the target).

## E. Pipes targets and invocation
- Targets: API destination, API Gateway, Batch job queue, CloudWatch log group, ECS task, event bus (same account and Region), Firehose, Kinesis, Lambda, Redshift Data API, SageMaker AI pipeline, SNS (not FIFO topics), SQS, Step Functions, Timestream for LiveAnalytics.
- Lambda and Step Functions Express targets can be `REQUEST_RESPONSE` (sync) or `FIRE_AND_FORGET` (async).
- Step Functions Standard targets must be async. Pipes cannot retry errors thrown inside a Standard workflow.
- Ordered sources (Kinesis, DynamoDB, SQS FIFO, Kafka) invoke targets synchronously by default, to keep order.
- Event bus target: pipe payload goes into `detail`; set `Source` and `DetailType` (can be dynamic, for example `$.body.type`).
- Dynamic target parameters: for example Kinesis `PartitionKey` = `$.body.customerId`.
- Input transformer in Pipes uses `InputTemplate` with `<$.body.field>` style paths, applied to each record in a batch separately.
- Classic exam pattern: SQS queue → pipe → Step Functions, with no Lambda in between.

## F. Pipes batching, concurrency, errors
- Batch size is limited by the smallest piece: Kinesis can give 10,000 records, but an SQS target takes 10, so the pipe max is 10.
- Target batch limits: CloudWatch Logs 10,000; Firehose 500; Kinesis 500; event bus 10; SNS 10; SQS 10; Lambda and Step Functions limited by payload size.
- Lambda and Step Functions receive a JSON array even if batch size is 1.
- Max concurrency per pipe by source: SQS 1,250; Amazon MQ 5; Kafka = partitions (up to 1,000); Kinesis/DynamoDB = shards × `ParallelizationFactor`.
- Ordered sources cap concurrency at the ordering unit (shards, message groups, partitions).
- Partial batch failure: Lambda/Step Functions targets return `batchItemFailures` with `itemIdentifier` (SQS `messageId`, Kinesis/DynamoDB `eventID`).
- Internal (AWS-side) errors are retried indefinitely until the record expires in the source.
- Customer errors (bad permissions, code errors): stream sources retry up to the pipe's `MaximumRetryAttempts` or `MaximumRecordAgeInSeconds`; SQS retries up to the queue's `maxReceiveCount`.
- Kafka and MQ sources retry customer errors like internal errors (until expiry).
- Nearly continuous 4xx errors (IAM, missing resource) can auto-disable the pipe with a `StateReason`.
- DLQ follows the source: SQS uses the queue's own redrive DLQ; Kinesis/DynamoDB pipes can set an SQS queue or SNS topic DLQ.
- No DLQ support for MSK or self-managed Kafka sources. FIFO DLQs not supported for stream sources.
- Set the pipe's `MaximumRecordAgeInSeconds` below the stream retention, so failed records reach the DLQ before they expire.
- SQS source with `MaximumBatchingWindowInSeconds` set: visibility timeout becomes about 7.5 min + window, so retries are slow.

## G. Pipes logging and Pipes vs Lambda ESM
- Pipe logs go to CloudWatch Logs, Firehose or S3. Levels `OFF` (API default), `ERROR`, `INFO`, `TRACE`.
- Console defaults to a new CloudWatch log group at `ERROR` level.
- Optional execution data: `payload`, `awsRequest`, `awsResponse`. May contain sensitive data; not redacted.
- Log records are capped at 256 KB when CloudWatch Logs is a destination; fields are truncated (`truncatedFields`).
- Pipes vs Lambda event source mapping (ESM): ESM only targets Lambda; Pipes target 15+ services with no code.
- Pick ESM when you need Lambda code anyway and ESM features (for example provisioned pollers for Kafka) **(verify)**.
- Pick Pipes for "move records from queue/stream to service X, maybe filter or enrich, no custom code".

## H. EventBridge Scheduler
- Scheduler = serverless scheduler for one-time and recurring invocations. Separate API (`scheduler`) and console section.
- Recommended over scheduled rules (legacy) for all new schedules.
- Schedule types: `at(yyyy-mm-ddThh:mm:ss)` one-time; `rate(value unit)` with minutes, hours, days; `cron(min hour dom month dow year)`.
- All types invoke with 60-second precision (anywhere inside the scheduled minute).
- Time zones: cron and one-time schedules use any IANA time zone (for example `America/New_York`). Default UTC.
- Daylight saving: spring forward skips a time that does not exist; fall back runs once, not twice.
- `rate(1 days)` means every 24 hours, even when DST makes a day 23 or 25 hours.
- Rate schedules start at `StartDate`, or immediately if none. Start/end dates are ignored by one-time schedules.
- Flexible time window: `Mode` `OFF` or `FLEXIBLE` with `MaximumWindowInMinutes` 1–1,440. Spreads invocations to avoid spikes.
- You must always set the flexible time window (use `OFF` for exact time).
- Templated targets: common actions such as Lambda Invoke, SQS SendMessage, SNS Publish, Step Functions StartExecution, EventBridge PutEvents, ECS RunTask, Kinesis PutRecord, Firehose PutRecord, CodeBuild, CodePipeline, SageMaker pipeline **(verify full list)**.
- Universal targets: call almost any API, ARN `arn:aws:scheduler:::aws-sdk:<service>:<apiAction>`, for example `aws-sdk:glue:startJobRun`. 270+ services, 6,000+ API actions.
- Universal targets cannot call read-only actions (prefixes `get`, `describe`, `list`, `query`, `scan`, `select`, `read`, `receive`, `poll`, `search`, `batchGet`, `invokeModel` and others).
- Trap: universal target `Input` is not validated at create time. Bad parameters fail on every run; look at the DLQ message.
- Target `Input` max 256 KB (fixed).
- Context attributes in the input: `<aws.scheduler.schedule-arn>`, `<aws.scheduler.scheduled-time>`, `<aws.scheduler.execution-id>`, `<aws.scheduler.attempt-number>`.
- Use `<aws.scheduler.scheduled-time>` so a nightly job knows which day it is processing, even on a retry.
- Execution role: each schedule has a role that trusts `scheduler.amazonaws.com` and allows the target action.
- Retry policy: `MaximumRetryAttempts` 0–185 and `MaximumEventAgeInSeconds` 60–86,400; defaults 185 attempts and 24 hours **(verify defaults)**.
- DLQ: standard SQS queue only (no FIFO), can be in another account. Execution role needs `sqs:SendMessage`.
- DLQ attributes include `ERROR_CODE`, `ERROR_MESSAGE`, `EXHAUSTED_RETRY_CONDITION`, `SCHEDULE_ARN`, `SCHEDULED_TIME`, `TARGET_ARN`, `RETRY_ATTEMPTS`.
- Delivery is at least once. Targets should be idempotent (use `execution-id`).
- Schedule groups organize schedules (tags, access control). A `default` group exists. Deleting a group deletes all its schedules.
- One-time schedules still count against the quota after they run. Set `ActionAfterCompletion: DELETE`.
- Quotas: 10,000,000 schedules per Region (adjustable to billions), 500 schedule groups, `CreateSchedule` 5,000 TPS in main Regions (250 elsewhere), invocations 1,000 TPS in main Regions (500 elsewhere). All adjustable.
- Invocations over the throttle limit are delayed, not dropped.
- Schedules can be encrypted with a customer managed KMS key (default AWS owned key).
- Pricing: 14 million free invocations per month (all Regions combined), then $1.00 per million.

## I. Scheduler vs scheduled rules
| | Scheduler | Scheduled rule (legacy) |
|---|---|---|
| Bus | none needed | default bus only |
| One-time schedules | yes (`at()`) | no |
| Time zones and DST | yes | UTC only |
| Flexible window | yes | no |
| Targets | templated + 6,000+ API actions | rule targets (about 30 types) |
| Scale | 10 million schedules per Region | 300 rules per bus |
| Targets per schedule | 1 | up to 5 per rule |
| Price | 14 M free/month, then $1/M | free for schedule events **(verify)** |
- Pick Scheduler for "run once at 9 AM on 15 Dec" or "one reminder per customer" (millions of schedules).
- A schedule with several targets is not possible; use one schedule per target or target an SNS topic or Step Functions.

## J. Archive and replay
- Archive = stored copy of events from one source bus. Optional event pattern filters what is archived.
- Retention in days; default is indefinite (keep forever) until you set a number.
- You cannot change an archive's source bus after creation. You can have many archives per bus.
- Archives work for custom events, partner events and AWS service events on that bus **(verify)**.
- Archive is encrypted with an AWS owned key by default; customer managed keys are supported (since April 2025).
- Events may take time to reach the archive. Wait about 10 minutes before replaying a time range.
- `EventCount` and `SizeBytes` in `DescribeArchive` reconcile over 24 hours, so numbers lag.
- Replay = re-send archived events for a start/end time window back to the same source bus only.
- Optionally replay only to specific rules on that bus, so other consumers are not hit twice.
- Replayed events carry `replay-name`. Targets can use it to tell replays from live events.
- An archive creates a managed rule with `"replay-name": [{"exists": false}]` so replayed events are not archived again.
- Replay order is not the original order. It replays in one-minute slices by event time.
- Max 10 active concurrent replays per account per Region. Replays can be cancelled while `Starting` or `Running`.
- Replay speed is based on, but separate from, the account `PutEvents` quota.
- Replaying does not delete events from the archive. Replay records are deleted after 90 days.
- Cost: archive processing per GB, archive storage per GB-month, replayed events billed as custom events.
- Use case: fix a bug in a consumer, then replay last 6 hours to that one rule.
- Trap: replay duplicates side effects. Targets must be idempotent or check `replay-name`.
- New Custom Event Bus has built-in retention and per-subscriber start position instead of archives.

## K. Schema Registry and discovery
- Schema = structure of an event. Registries: `aws.events` (all AWS service event schemas, built in), `discovered-schemas`, and your custom registries.
- Formats: OpenAPI 3 and JSONSchema Draft4.
- Schema discovery: turn it on per bus; EventBridge infers schemas from events and versions them when the shape changes.
- Discovery is not supported on buses encrypted with a customer managed key.
- Discovery sees the original event, not the input-transformed one.
- Code bindings: download typed classes for Java, Python, TypeScript and Go **(verify)**, also from IDE toolkits (VS Code, JetBrains).
- Quotas: 10 registries, 100 schemas per registry, 100 versions per schema, 10 discoverers, 200 discovered schemas, 255 nesting levels.
- Pricing: registry free; discovery has 5 million events/month free tier, billed per 8 KB chunk after that.
- Exam angle: Schema Registry here is for event shapes. It is not the Glue Schema Registry used for Kafka/Kinesis Avro serialization.

## L. API destinations and connections
- API destination = HTTPS endpoint as a target of a rule or pipe (and enrichment for Pipes). Any method except CONNECT and TRACE.
- Endpoint must be HTTPS with a publicly trusted certificate. No mTLS.
- Request timeout is 5 seconds max. Slow endpoints time out and are retried.
- Invocation rate limit per destination, default 300 per second (adjustable quota). Extra invocations are delayed, not dropped.
- Trap: a rate far below the incoming event rate builds a backlog; events older than 24 hours are dropped. Add a DLQ.
- Retries on HTTP 401, 407, 409, 429 and 5xx. No retry on other 4xx, 1xx, 2xx, 3xx.
- EventBridge honours the `Retry-After` header (uses the more conservative of it and the retry policy).
- Connection = auth + network settings, reused by many API destinations.
- Auth types: Basic (username/password), API key (header name + value), OAuth client credentials (client ID/secret + token endpoint).
- For OAuth, EventBridge fetches and refreshes the token for you.
- Credentials are stored in a Secrets Manager secret that EventBridge creates (service-linked role `AmazonEventBridgeApiDestinationsServiceRolePolicy`). Secrets Manager charges apply.
- Connection secrets can use a customer managed KMS key (since 2025).
- Connection states include `AUTHORIZED` and `DEAUTHORIZED` (for example bad credentials or OAuth failure).
- Private connections reach private endpoints in a VPC (via VPC Lattice resource configurations); quota 20 private connections.
- Quotas: 3,000 API destinations and 3,000 connections per account per Region.
- Use input transformer to shape the body; headers like `User-Agent` and `Range` cannot be overridden.
- Pricing: $0.20 per million invocations plus data transfer.
- Use case: push Glue job failures straight to a SaaS incident tool (PagerDuty, Slack webhook) with no Lambda.

## M. Cross-account and cross-Region routing (classic)
- Pattern 1: rule target = event bus in another account (or Region). Receiver bus policy must allow `events:PutEvents` from the sender.
- Since 2 March 2023 every new cross-account bus target needs an IAM role on the sender's rule. The role allows `events:PutEvents` on the target bus.
- The role makes SCPs apply to the sender, which is why AWS requires it.
- Receiver policy for a whole organization: `Principal "*"` + `Condition aws:PrincipalOrgID = o-xxxx`.
- Pattern 2 (since Jan 2025): direct delivery to cross-account targets that have resource policies: SQS, SNS, Lambda, Kinesis Data Streams, API Gateway.
- Direct delivery still needs an execution role on the sender's rule plus the target's resource policy allowing that role.
- Receiver side writes its own rules on its bus to match incoming events. Add `account` to patterns to accept only known senders.
- Hop limit: a receiver cannot forward events it got from one account on to a third account. Events are not delivered (`THIRD_ACCOUNT_HOP_DETECTED`).
- Same-account bus → bus → bus chains also stop after one hop.
- Cross-Region: rule target = bus ARN in another supported Region. Data transfer charges apply.
- Cost: the sending account pays (custom event rate per million delivered to another bus); the receiver is not charged.
- Central monitoring pattern: every account forwards `aws.glue`/`aws.states` failure events to a central ops bus in a security or ops account.
- New Custom Event Bus alternative: share one bus by AWS RAM; consumer accounts create their own subscribers. No bus-to-bus forwarding needed.

## N. SaaS and events to SaaS
- Inbound SaaS: partner event sources → partner bus (see file 1). Salesforce arrives through Amazon AppFlow.
- Lambda function URLs can receive webhooks from non-partner SaaS and put events on a bus.
- Outbound to SaaS: API destinations with a connection holding the SaaS token.
- AppFlow can also move SaaS data in bulk; EventBridge is for events, not bulk data loads.

## O. Data pipeline orchestration patterns
- File arrival trigger: S3 (EventBridge on) → rule → Step Functions → Glue `startJobRun.sync` → crawler → notify. Step Functions handles retries and branching.
- File arrival with batching: S3 → rule → Glue workflow with EVENT trigger, `BatchSize` N and `BatchWindow` up to 900 s, so 100 small files start one run.
- Nightly pipeline: Scheduler cron with time zone → Step Functions state machine (or Glue workflow, or MWAA DAG run).
- Simple nightly Glue job: Scheduler universal target `glue:startJobRun`, no Step Functions needed if no follow-up steps.
- Glue also has its own scheduled triggers and crawler schedules; EventBridge is better when the trigger is an event.
- MWAA (Airflow): EventBridge or Scheduler can call a Lambda or the MWAA API to trigger a DAG run **(verify direct target support)**; Airflow sensors are the alternative.
- Failure alerting: rules on `Glue Job State Change`, `Step Functions Execution Status Change` (FAILED, TIMED_OUT, ABORTED), `EMR Step Status Change`, `Batch Job State Change` → SNS or chat.
- Redshift: rule or schedule → Redshift Data API target runs `COPY` or a stored procedure; `Redshift Data Statement Status Change` event says when it finished.
- Lake update fan-out: Glue Data Catalog table/partition events → rule → Lambda refreshing a downstream cache (best effort; do not depend on order).
- Streaming glue: DynamoDB Streams → pipe (filter `eventName=INSERT`) → event bus → several consumers.
- Queue to workflow: SQS → pipe → Step Functions Express (sync) with enrichment via API destination.
- EventBridge starts work; Step Functions or MWAA manage multi-step dependencies. Do not chain many rules to build a DAG.

## Scenarios: "If X → Y, because Z"
- **If** messages in an **Amazon Simple Queue Service (SQS)** queue must start an **AWS Step Functions** workflow without any **AWS Lambda** code, **then** create an **EventBridge Pipe** with the SQS queue as **source** and the state machine as **target**. **This works because** a pipe **polls the queue for you** (like a Lambda event source mapping) and calls the target directly, replacing "glue code" functions. The pipe's IAM role needs read rights on the queue, such as `sqs:ReceiveMessage` and `sqs:DeleteMessage`.
- **If** only `ORDER_CREATED` messages from a queue should reach the target, **then** add a **Pipes filter** on the message type, for example under `body.type` (the SQS body field name is marked **(verify)**). **This works because** a pipe drops non-matching records before the target, and you pay **only for events that pass the filter**. Catch: filtering on the body works only when the message is **valid JSON**.
- **If** records need customer details from an HTTP API before they reach the target, **then** add **Pipes enrichment** with an **API destination** (an HTTPS endpoint EventBridge can call). **This works because** enrichment is always **synchronous**: the pipe waits for the answer and sends the enriched data to the target. The enrichment response can be at most **6 MB**.
- **If** someone sets a Step Functions **Standard** workflow as Pipes enrichment, **then** it fails and the **pipe is stopped**; use an **Express** workflow instead. **This works because** enrichment must run **synchronously**, and only Express workflows can do that; Standard workflows cannot.
- **If** a pipe from **Amazon Kinesis Data Streams** to an SQS target is set to batch size **100**, **then** it is not allowed: the pipe's maximum batch is **10**. **This works because** batch size is limited by the **smallest piece**: Kinesis can give 10,000 records, but an **SQS target takes only 10** per batch.
- **If** a pipe reading **Amazon Managed Streaming for Apache Kafka (MSK)** keeps failing on one bad ("poison") record, **then** handle that record in your own code (for example in enrichment or target logic). **This works because** Pipes has **no dead-letter queue (DLQ)** for MSK or self-managed Kafka sources, and Kafka sources keep retrying customer errors **until the record expires**.
- **If** a pipe reading MSK from a **private subnet** shows a connection error, **then** add a **NAT gateway** or a **`pipes-data` VPC endpoint**. **This works because** Kafka and MQ sources inside a VPC need a network path to the Pipes service. Also check that the MSK cluster has **security groups**, or the pipe fails with a `StateReason`.
- **If** **50,000 customers** each need a reminder at their own time, **then** create one **EventBridge Scheduler one-time schedule** (`at()`) per customer with **`ActionAfterCompletion: DELETE`**. **This works because** Scheduler scales to **10 million schedules per Region** (adjustable), and deleting each schedule after it runs matters because **completed one-time schedules still count** against that quota.
- **If** a report must run at **07:00 London time** across **daylight saving time (DST)**, **then** use an **EventBridge Scheduler cron** schedule with time zone `Europe/London`. **This works because** Scheduler supports **IANA time zones** and handles DST (a skipped time is skipped, a repeated hour runs once), while legacy **scheduled rules** are **UTC only**.
- **If** **10,000 hourly schedules** all hit an API at the same second, **then** set a **flexible time window** (`Mode: FLEXIBLE`, `MaximumWindowInMinutes` 1–1,440). **This works because** Scheduler then **spreads invocations** across the window instead of firing them all at once, which avoids spikes.
- **If** a schedule's **universal target** fails on every run, **then** read the **`ERROR_MESSAGE`** (and `ERROR_CODE`) attribute on the messages in the schedule's **DLQ**. **This works because** Scheduler does **not validate** the universal target `Input` when you create the schedule, so bad parameters only fail at run time.
- **If** a job must start **one AWS Glue job** nightly with no extra steps, **then** use a **Scheduler universal target** `aws-sdk:glue:startJobRun`. **This works because** universal targets can call almost any AWS API action, while a Glue job is **not** a classic rule target. You need **Step Functions** only if follow-up steps are required.
- **If** a consumer had a bug for **4 hours**, **then** fix the code, then **replay the archive** for those 4 hours **to only that rule**. **This works because** replay re-sends archived events to the **same bus** and can be limited to **specific rules**, so other consumers are not hit twice. Replayed events carry **`replay-name`**, and the target must be **idempotent** because side effects repeat.
- **If** replayed events must not be archived again, **then** do nothing. **This works because** every archive creates a **managed rule** with `"replay-name": [{"exists": false}]`, which skips replayed events.
- **If** you need to replay archived events from **30 minutes ago**, **then** wait about **10 minutes** after the time window ends before starting the replay. **This works because** events can take some time to reach the archive, so a replay started too early may miss some.
- **If** **12 replays** are requested at once, **then** only **10** can be active; cancel or wait for others. **This works because** the limit is **10 concurrent replays per account per Region**.
- **If** a bus encrypted with a **customer managed AWS Key Management Service (KMS) key** cannot turn on **schema discovery**, **then** use an **AWS owned key** on that bus or skip discovery. **This works because** schema discovery is **not supported** on buses encrypted with a customer managed key.
- **If** a SaaS webhook needs an **OAuth** token, **then** use an **API destination** with an **OAuth client-credentials connection** (client ID, secret and token endpoint). **This works because** EventBridge **fetches and refreshes the token** for you and stores the credentials in an **AWS Secrets Manager** secret it creates (Secrets Manager charges apply).
- **If** a slow SaaS API takes **8 seconds** to answer, **then** put a **queue or async endpoint** in front of it. **This works because** API destination requests **time out at 5 seconds**; slow calls time out and are retried, and this limit cannot be raised.
- **If** an API returns **HTTP 400** for some events, **then** expect them **not to be retried**: send them to a **DLQ** and fix the **input transformer** that builds the request. **This works because** API destinations retry only **401, 407, 409, 429 and 5xx** errors; other 4xx errors fail at once.
- **If** every account in an **AWS Organization** must send events to a **central bus**, **then** give the central bus a **resource policy** with `Principal "*"` and **`aws:PrincipalOrgID`**, and put an **IAM role** with `events:PutEvents` on **each sender's rule**. **This works because** one org condition grants the whole organization, and since **March 2023** every new cross-account bus target needs a role on the sender rule (so **SCPs** apply to the sender). The sending account pays for delivery.
- **If** a team in another account only wants events in their **SQS queue**, **then** use **direct cross-account delivery**: the rule targets their queue, with an **execution role** on the sender's rule and a **queue policy** that allows that role. **This works because** since **January 2025** rules can deliver straight to cross-account SQS, SNS, Lambda, Kinesis and API Gateway targets, so the team needs **no event bus** of its own.
- **If** account B forwards events it received from account A on to account C, **then** account C **never gets them**; send directly from account A instead. **This works because** EventBridge blocks a **third-account hop** (`THIRD_ACCOUNT_HOP_DETECTED`).
- **If** **200 small files** land per minute and **one Glue run** should process them, **then** use a **Glue workflow** target with an **EVENT trigger** that sets a **batch size** and a **batch window** (up to **900 s**). **This works because** the trigger waits until it has N events or the window ends, then starts **one run**; without batching, each S3 event would start its own run.
- **If** a multi-step ETL needs **retries, branches and waits**, **then** let an EventBridge rule or schedule **start** an **AWS Step Functions** state machine, and let Step Functions run the steps. **This works because** EventBridge only **starts** work: rules **cannot model dependencies**, so chaining many rules to build a pipeline is fragile.

Verified from AWS docs on 2026-11-03 (EventBridge user guide: Pipes overview, targets, enrichment, batching and concurrency, error handling, logging; archive and replay; API destinations; schemas; cross-account and cross-Region; SaaS; VPC endpoints; quotas; Scheduler user guide: what is Scheduler, schedule types, universal targets, flexible time windows, DLQ, quotas; Scheduler API RetryPolicy and FlexibleTimeWindow; Glue workflow EventBridge trigger; AWS What's New for cross-account direct delivery Jan 2025 and archive CMK Apr 2025; pricing page).
Unconfirmed (verify): Kinesis `AT_TIMESTAMP` start position for Pipes; Pipes filter field names (`body`, `data`, `dynamodb`); SQS filtered-out messages deleted; ESM-only features vs Pipes; full list of Scheduler templated targets; Scheduler retry defaults (185 / 24 h); scheduled-rule pricing; archives including AWS service events; code-binding languages; MWAA as direct target.

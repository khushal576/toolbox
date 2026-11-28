# EventBridge – 3. Security, monitoring, quotas, cost, troubleshooting, comparison, scenarios

Short notes. Each point is a fact you can be asked about.

## A. Who can do what (IAM)
- Identity policies control who can create rules, put targets, put events and manage Pipes/Scheduler.
- Actions live in different prefixes: `events:*` (buses, rules, archives, API destinations), `pipes:*`, `scheduler:*`, `schemas:*`.
- Producers need `events:PutEvents` on the bus ARN. Scope it to one bus, not `*`.
- Creating a rule with a role needs `iam:PassRole` on that role. Same for pipes and schedules.
- Least privilege: separate roles for producers (PutEvents), rule admins (PutRule/PutTargets) and readers.
- Condition keys for `PutEvents` and rules include `events:source`, `events:detail-type`, `events:eventBusInvocation` **(verify list)**.
- Use `events:source` in a producer policy so an app can only publish its own source (for example `com.mycompany.orders`).
- `events:ManagedBy` identifies managed rules created by AWS services **(verify)**.
- Tag-based access (ABAC) works on buses, rules and schedules with `aws:ResourceTag` **(verify coverage)**.
- Separate buses per domain or team give a clean permission boundary: grant `PutEvents` per bus ARN.
- `events:PutRule` on the default bus is powerful: a new rule can copy every AWS service event to any target. Restrict it.
- `events:PutTargets` lets someone add a target to an existing rule and exfiltrate events. Treat it like a write permission on data.
- Scheduler and Pipes are separate services: `events:*` does not grant `scheduler:*` or `pipes:*`.

## B. Resource-based policies
- Event bus policy: who (accounts, organization, roles) may put events or manage rules on this bus.
- Org-wide access: `"Principal": "*"` with `"Condition": {"StringEquals": {"aws:PrincipalOrgID": "o-xxxx"}}`.
- Trap: `"Principal": "*"` without a condition lets any AWS account send events to your bus.
- If you accept events from many accounts, add `account` to every rule pattern so strangers cannot trigger your targets.
- Target resource policies: Lambda function policy, SNS topic policy, SQS queue policy can grant `events.amazonaws.com`.
- Scope those with `aws:SourceArn` = rule ARN (and `aws:SourceAccount`) to stop the confused deputy problem.
- Trap: a Lambda permission with a `SourceAccount` field can block EventBridge invocation; the docs say to remove it and use `SourceArn`.
- When a rule targeting SNS is deleted quickly, the SNS policy statement may remain. Remove it by hand.
- Partner buses and the default bus have restrictions: partner bus policies are not allowed.
- New Custom Event Bus sharing uses AWS RAM managed permissions (publish only, subscribe only, event source access, full access).
- On the new bus, the owner can withdraw a consumer's subscriber with `RevokeResource`; revoked resources cannot be restored.

## C. Execution roles
- Rule target role: trusts `events.amazonaws.com`, allows the target action (for example `states:StartExecution`, `glue:notifyEvent`, `ecs:RunTask` + `iam:PassRole` for the task role).
- Cross-account bus target role: allows `events:PutEvents` on the remote bus ARN. Required for new cross-account targets since March 2023.
- Pipe role: trusts `pipes.amazonaws.com`; needs source read, enrichment invoke, target write, and KMS decrypt if the source is encrypted.
- Schedule role: trusts `scheduler.amazonaws.com`; needs the target action and `sqs:SendMessage` for its DLQ.
- Add `aws:SourceAccount` / `aws:SourceArn` conditions in role trust policies to stop other accounts' rules or schedules using your role.
- If the role cannot be assumed, the DLQ error is `FAILED_TO_ASSUME_ROLE`. Also check that regional STS endpoints are enabled.
- One role per rule or per target type keeps blast radius small; avoid one shared admin role for all targets.
- The console can create a role for each rule automatically; IaC templates must define and pass the role explicitly.
- ECS task targets need `iam:PassRole` for the task execution role and task role in the EventBridge role.

## D. Encryption
- In transit: all APIs and deliveries use TLS (HTTPS).
- At rest default: AWS owned key (AES-256), free, no audit trail, no key policy to manage.
- Customer managed KMS key (symmetric) supported for: event buses (custom and default), archives, Pipes, connections (API destination secrets), schedules.
- Bus CMK encrypts custom and partner events, rule event patterns, target info (input, transformers, parameters) and the `detail`/`error` of bus logs.
- Bus CMK does not cover AWS service events (always AWS owned key) or event metadata (envelope fields).
- Key policy for a bus: allow `events.amazonaws.com` `kms:DescribeKey`, `kms:GenerateDataKey`, `kms:Decrypt`, with conditions on `kms:EncryptionContext:aws:events:event-bus:arn` and `aws:SourceArn`.
- Encryption context for a bus = the bus ARN. Visible in CloudTrail KMS events.
- Admins creating a CMK bus need `kms:GenerateDataKeyWithoutPlaintext`, `kms:Encrypt`, `kms:Decrypt`, `kms:ReEncrypt*`, `kms:DescribeKey`.
- `DescribeRule`, `ListRules`, `PutRule`, `PutTargets`, `EnableRule`, `DisableRule` on a CMK bus also need `kms:Decrypt` for the caller.
- Set a DLQ on a CMK bus: events that fail encryption or decryption (for example key disabled) go there. AWS strongly recommends it.
- Error codes for key problems: `EVENT_ENCRYPTION_FAILURE`, `EVENT_DECRYPTION_FAILURE`, `RULE_DECRYPTION_FAILURE`, `ACTION_DECRYPTION_FAILURE`.
- Schema discovery cannot run on a CMK bus.
- Multi-Region keys and cross-account key access are supported.
- Encrypted targets (SQS, SNS, Kinesis with CMK): the target key policy must let EventBridge (or the role) use `kms:GenerateDataKey` and `kms:Decrypt`.
- CMK use costs KMS request fees and the monthly key fee; AWS owned keys are free.
- Changing the key on a bus re-encrypts stored configuration; metrics `EventBusEncryptionStarted/Completed/Failed` track it.
- Pipes CMK encrypts filter patterns, enrichment parameters and target parameters.
- Connection CMK encrypts the Secrets Manager secret that holds the API credentials.
- Do not put secrets or PII in event `detail` unless needed; bus logs and Pipes execution data can copy them into logs.
- Mask or drop sensitive fields with an input transformer before sending events to third-party API destinations.

## E. Network
- Interface VPC endpoints (PrivateLink): `com.amazonaws.<region>.events` (classic buses, `PutEvents`), `events-fips`.
- Pipes: `pipes` (control API, supports endpoint policies), `pipes-data` (data path for Kafka/MQ sources in a VPC; no endpoint policies).
- Schema registry: `schema`. Scheduler: `scheduler` **(verify)**. New Custom Event Bus: `eventsv2`.
- With an endpoint, producers in private subnets put events with no NAT or internet gateway.
- Endpoint policies can limit which buses or actions the VPC may call.
- EventBridge delivers to targets over AWS's network; targets do not need public endpoints (except API destinations, which need public HTTPS unless using a private connection).
- IP allowlists: API destination calls come from AWS public IP ranges; allowlisting is fragile. Prefer auth headers or private connections **(verify)**.

## F. Audit and monitoring
- CloudTrail logs EventBridge management calls (`PutRule`, `PutTargets`, `PutPermission`, `CreateEventBus`, `CreateArchive`, Pipes, Scheduler calls).
- `PutEvents` is a data event in CloudTrail and is not logged by default **(verify)**.
- CloudWatch metrics (namespace `AWS/Events`) are sent every minute, best effort.

| Metric | Meaning |
|---|---|
| `MatchedEvents` | events that matched any rule (by bus) or a given rule |
| `TriggeredRules` | rules that ran because an event matched |
| `Invocations` | target invocations (success + permanent failure), not retries |
| `FailedInvocations` | invocations that failed permanently (not sent to DLQ) |
| `InvocationAttempts` / `SuccessfulInvocationAttempts` / `RetryInvocationAttempts` | each try, each success, each retry |
| `ThrottledRules` | rule runs delayed by the invocation quota |
| `DeadLetterInvocations` | times a target was not invoked (includes loop protection) |
| `InvocationsSentToDlq` / `InvocationsFailedToBeSentToDlq` | DLQ success / DLQ failure |
| `IngestiontoInvocationStartLatency` | ingestion → first invocation attempt (ms) |
| `IngestionToInvocationSuccessLatency` | ingestion → successful delivery (ms) |
| `InvocationsCreated` | invocations created; compare to invocation quota |
| `PutEventsApproximateThrottledCount`, `PutEventsFailedEntriesCount`, `PutEventsLatency`, `PutEventsRequestSize` | producer side |
| `Events` (by `EventSourceName`) | partner events ingested |

- Many metrics (`Invocations`, `FailedInvocations`, DLQ metrics) are only emitted when non-zero. A missing metric often means zero.
- Dimension `RuleName` alone = default bus; `EventBusName` + `RuleName` = custom bus.
- Alarm on `FailedInvocations >= 1` and on `InvocationsFailedToBeSentToDlq >= 1`; the second means events are being lost.
- Alarm on rising `IngestionToInvocationSuccessLatency` to spot slow or throttling targets.
- Watch `ThrottledRules` and `InvocationsCreated` against the invocation quota before big launches.
- Pipes metrics (namespace `AWS/EventBridge/Pipes` **(verify)**): executions started, failed, throttled, timed out, target and enrichment stage failures.
- Scheduler metrics (namespace `AWS/Scheduler`): invocation attempts, target errors, throttles, DLQ sends **(verify names)**.
- Bus logging (OFF/ERROR/INFO/TRACE) and Pipes logging show per-event steps; metrics only show counts.
- Metrics are best effort: good for alarms and trends, not for exact accounting of every event.
- To prove delivery end to end, log the event `id` in the target and compare with bus logs.
- A CloudWatch Logs log group as a second target ("audit target") on important rules gives a cheap record of matched events.
- CloudTrail also records Custom Event Bus (new) management calls made through the `eventsv2` endpoint.
- For the new bus, check subscriber metrics in `AWS/EventsV2`: `FilterEvaluated`, `FilterMatched`, `TargetInvocations`, `EventsDelivered`, `EventsDropped`.

## G. Quotas and numbers (classic bus unless noted)
| Item | Value |
|---|---|
| Event buses per account per Region | 100 (adjustable) |
| Rules per bus | 300 (100 in af-south-1, eu-south-1), adjustable |
| Targets per rule | 5 (fixed) |
| Rules containing wildcards | 30 per bus (fixed) |
| Event pattern size | 2,048 characters (adjustable) |
| `$or` combinations | 1,000 max |
| Bus policy size | 10,240 characters (adjustable) |
| PutEvents entries / request size | 10 entries, 1 MB total |
| PutEvents TPS | 10,000 (us-east-1, us-west-2, eu-west-1); 2,400 (us-east-2, eu-central-1); 1,200 / 600 / 400 elsewhere; adjustable |
| Invocations TPS | 18,750 (us-east-1, us-west-2, eu-west-1); 4,500; 2,250; 1,100; 750 elsewhere; adjustable |
| Control plane APIs | 50 TPS (fixed) |
| Retry policy | default 24 h and 185 attempts |
| Input transformer variables | 100 |
| API destinations / connections | 3,000 / 3,000; rate 300/s per destination (adjustable) |
| Private connections | 20 |
| Global endpoints | 100; Create/Update/Delete 5 TPS |
| Concurrent replays | 10 per account per Region |
| Pipes | 1,000 per account; concurrent executions 3,000 (big Regions) / 1,000; 5-minute execution; 6 MB payload |
| Scheduler | 10 M schedules, 500 groups, 1,000 invocations/s (big Regions), 256 KB input |
| Schema registry | 10 registries, 100 schemas each, 100 versions, 10 discoverers |
| New Custom Event Bus | 5 buses, 10,000 subscribers per bus, 500,000 events/s per bus, 100 entries per publish, retention 1–365 days |

- Invocation throttling delays invocations; it does not drop them (until the 24-hour max age).
- PutEvents throttling rejects the call; the producer must retry.
- To raise limits use Service Quotas (service "Amazon EventBridge (CloudWatch Events)").
- API destination rate limit is shared by every rule that targets the same destination.
- Archive and replay events count toward the account's PutEvents-based replay throughput.
- Bus count includes custom and partner buses; the default bus is always there.
- Hard (fixed) limits to remember: 5 targets per rule, 30 wildcard rules per bus, 5-minute Pipes execution, 5-second API destination timeout, 10 concurrent replays.

## H. Cost (classic bus, US prices)
- AWS management (service) events on the default bus: free to ingest.
- Custom events: $1.00 per million ingested.
- Partner (SaaS) events: $1.00 per million ingested.
- Events delivered to a bus in another account: $1.00 per million (custom), charged to the sender; receiver pays nothing.
- AWS service events delivered to another account: $1.00 per million.
- Custom events delivered to a target service in the same account: no extra charge.
- Billing unit: each 64 KB chunk is one event. A 256 KB event = 4 events; a 1 MB event = 16.
- Cross-Region delivery adds standard data transfer charges.
- Global endpoints: no extra fee; events billed as custom events; replication adds events.
- Archive: processing about $0.10 per GB, storage about $0.023 per GB-month; replayed events billed as custom events ($1.00 per million).
- Schema discovery: 5 million events per month free; charged per 8 KB chunk after that. Registry free.
- API destinations: $0.20 per million invocations, plus data transfer.
- Pipes: $0.40 per million requests after filtering; each 64 KB chunk is one request. Batching cuts requests.
- Scheduler: 14 million invocations free per month, then $1.00 per million.
- Also pay for: KMS CMK, Secrets Manager secret per connection, CloudWatch Logs/S3/Firehose for logging, target services.
- New Custom Event Bus: per GB ingress (about $0.18/GB first tier), per GB egress per delivery, per GB storage, per million evaluations.
- Cost tips: filter in the pattern (not in Lambda), keep events small, batch with Pipes, avoid loops, use Scheduler free tier, do not forward every default-bus event to other accounts.
- Example: 10 M custom events ingested, 5 M delivered to another bus, 5 M to same-account targets = $10 + $5 + $0 = $15 per month.
- Example: 5 M AWS service events delivered cross-account = $5 per month (ingestion free).
- Example: 20 M Scheduler invocations = (20 M − 14 M free) × $1 = $6 per month.
- Example: Pipes with 10 M SQS messages, 25% pass the filter, batches of 5 = 0.5 M requests × $0.40 = $0.20 per month.
- Example: 2 M API destination calls = $0.40 per month plus data transfer.
- Rule evaluation itself is not billed on classic buses; you pay per event ingested or delivered.
- Partner events are billed even if no rule matches them, because ingestion is the billed step **(verify)**.

## I. Troubleshooting: rules and targets
| Symptom | Cause | Fix |
|---|---|---|
| Rule never fires | pattern mismatch (case, spelling, wrong nesting, numbers as strings) | test with `TestEventPattern`/Sandbox; check `MatchedEvents`; use `equals-ignore-case` |
| Rule on custom bus never sees AWS events | AWS service events only reach the default bus | forwarding rule on default bus → custom bus |
| `TriggeredRules` rises but target never runs | missing Lambda/SNS/SQS permission or role | add resource policy for `events.amazonaws.com` or a role; check `FailedInvocations` |
| Lambda not invoked, policy has `SourceAccount` | that condition blocks EventBridge | remove `SourceAccount`, keep `SourceArn` |
| SQS/SNS target gets nothing | queue/topic encrypted with a key EventBridge cannot use | CMK with key policy for `events.amazonaws.com` |
| Rule just created doesn't match | change not propagated yet | wait a short time and retest |
| Scheduled rule runs at the "wrong" hour | rule is UTC | convert to UTC or use Scheduler with a time zone |
| IAM/Route 53 API rule never fires | global service events only in us-east-1 | create the rule in us-east-1 |
| Read-only API calls not matched | rule state is `ENABLED` | use `ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS` |
| Pattern on `resources` matches nothing | CloudTrail events have empty `resources`; ARN chars differ | match `detail.requestParameters` instead; exact ARN |
| Wildcard rule rejected | > 30 wildcard rules or too complex | fewer `*`; prefix/suffix instead |
| `InvalidEventPatternException` with `$or` | over 1,000 combinations | split into several rules |
| Target delayed | throttled target or invocation quota | raise quotas; SQS buffer; watch `ThrottledRules` |
| Rule fires forever, bill spikes | infinite loop | narrow the pattern to the bad state; Budgets alarm |

- Debug order for "nothing happened": `MatchedEvents` (did the pattern match?) → `TriggeredRules` → `Invocations` → `FailedInvocations` / DLQ attributes.
- `MatchedEvents` = 0 means the event never matched: check bus, Region, pattern, or that the event was produced at all.
- `Invocations` > 0 but the target shows nothing: the target accepted the call but failed inside (for example a Lambda error after async invoke). Check the target's own logs and its async DLQ/destinations.
- Lambda async invoke from EventBridge has its own retries (2 by default) and on-failure destination, separate from the EventBridge retry policy.
- Console "Sandbox" lets you paste a sample event and test a pattern or input transformer without sending events.
- Re-adding a target in the console rewrites the Lambda/SNS resource policy, a quick fix for broken permissions.

## J. Troubleshooting: delivery, S3, cross-account
| Symptom | Cause | Fix |
|---|---|---|
| S3 events not arriving | EventBridge not turned on for the bucket; wrong Region; rule on custom bus | enable on the bucket; rule on default bus in bucket's Region |
| S3 rule fires for "folder" objects | 0-byte keys ending `/` | `numeric > 0` on size or `anything-but` suffix `/` |
| Glue workflow not starting from S3 | CloudTrail-based pattern with no data-event trail, or missing `glue:notifyEvent` | use S3 EventBridge events or enable data events; fix role |
| Events lost after outage | retries exhausted (24 h) and no DLQ | add DLQ; raise max age; buffer in SQS |
| `InvocationsFailedToBeSentToDlq` > 0 | DLQ missing policy, wrong Region, FIFO, or encrypted with unusable key | standard queue, same Region, queue policy, usable key |
| Duplicates downstream | at-least-once delivery, retries, replays | idempotency on event `id`; check `replay-name` |
| Out-of-order processing | no ordering on buses | sequence field + SQS FIFO/Kinesis; or new bus event groups |
| Cross-account events not delivered | receiver bus policy missing; no role on sender rule; receiver has no matching rule | add policy (org condition), add role with `events:PutEvents`, add receiver rule |
| Events stop at the third account | third-account hop blocked | send directly from the source account |
| Cross-account rule matches strangers' events | bus accepts all accounts | add `account` to patterns; tighten policy |
| `PutEvents` 200 but nothing happens | bus name typo (silently dropped) or no rule matches | correct bus; enable bus logging INFO for `No Rules Matched` |
| `PutEvents` throttled | above TPS quota | backoff; batch 10 per call; raise quota |
| API destination events dropped | 4xx not retried, or 5 s timeout, or low rate limit backlog | fix input; faster endpoint; raise rate; DLQ |
| Connection `DEAUTHORIZED` | bad credentials or OAuth token endpoint failing | update connection secret/parameters |
| Pipe stopped automatically | continuous 4xx (permissions, missing stream) or Standard workflow as sync target/enrichment | read `StateReason`; fix role; use Express or async |
| Pipe retries slowly on SQS | batching window set → long visibility timeout | remove `MaximumBatchingWindowInSeconds` or accept delay |
| Schedule succeeds in console but target fails | universal target input not validated | read DLQ `ERROR_CODE`/`ERROR_MESSAGE` |
| Schedule quota reached | completed one-time schedules still count | `ActionAfterCompletion: DELETE` |

- DLQ `ERROR_CODE` is the fastest root cause: `NO_PERMISSIONS`, `NO_RESOURCE`, `FAILED_TO_ASSUME_ROLE`, `THROTTLING`, `TIMEOUT`, `CROSS_ACCOUNT_INGESTION_FAILED`.
- `EXHAUSTED_RETRY_CONDITION` tells whether the event hit `MaximumRetryAttempts` or `MaximumEventAgeInSeconds`.
- Cross-account checklist: receiver bus policy, sender rule role, same supported Region pair, receiver rule pattern (with `account`), receiver target permissions.
- Missing events from Glue Data Catalog table/partition notifications can be normal: they are best effort.
- Duplicate S3 events can happen; dedupe on bucket + key + `sequencer` **(verify field name)** or the event `id`.
- For Pipes, read `StateReason` first; most auto-stops are IAM or networking.

## K. EventBridge vs SNS vs SQS vs Kinesis vs MSK
| | EventBridge (classic bus) | SNS | SQS | KDS | MSK |
|---|---|---|---|---|---|
| Model | event bus, rules route by content | pub/sub push | queue, consumers pull | ordered log, many readers | Kafka log |
| Routing/filtering | rich patterns on any field | subscription filter policies (attributes or body) | none (consumer decides) | none (consumer reads all) | none (topics/partitions) |
| Consumers | up to 5 targets per rule, 300 rules | many subscribers (millions) | one consumer per message | many independent apps | many consumer groups |
| Ordering | no (new bus: per event group) | FIFO topics | FIFO queues | per shard | per partition |
| Retention/replay | archive + replay (new bus: 1–365 days) | none (archive on FIFO topics) | up to 14 days, no replay after delete | 24 h – 365 days, replay by position | configurable, tiered storage |
| Max message | 1 MB per request | 256 KB **(verify)** | 1 MiB **(verify)** | 10 MiB | default 1 MB, configurable |
| Throughput | 10,000 PutEvents/s in big Regions (adjustable) | very high | nearly unlimited (standard) | per shard or on-demand | broker sizing |
| SaaS / AWS service events | built in | no | no | no | no |
| Best for | react to AWS/SaaS/app events, content routing, cross-account | fan-out notifications, email/SMS, mobile | buffering, work queues, smoothing spikes | real-time analytics, replay | Kafka apps and ecosystem |

- Common combo: EventBridge → SQS (buffer) → Lambda, to protect slow consumers and get retries and DLQ on the queue.
- SNS vs EventBridge for fan-out: SNS for huge subscriber counts and push to email/SMS/HTTP; EventBridge for content routing and AWS service events.
- Kinesis vs EventBridge: Kinesis for high-volume ordered streams and replay by sequence; EventBridge for discrete business or state-change events.
- SQS vs EventBridge: SQS when consumers must control their pace and messages wait up to 14 days; EventBridge pushes immediately and keeps nothing unless archived.
- MSK vs EventBridge: MSK when you need the Kafka protocol, Kafka Connect or Kafka Streams; EventBridge Pipes can still read MSK and route records.
- Firehose vs EventBridge: Firehose lands data in S3/Redshift/OpenSearch in buffered batches; EventBridge reacts to individual events (it can target Firehose).
- Step Functions vs EventBridge: Step Functions runs ordered multi-step workflows with state; EventBridge only starts or connects them.

## Scenarios: "If X → Y, because Z"
- **If** a file landing in **Amazon S3** must trigger an **AWS Glue** job, **then** turn on **S3 EventBridge events** for the bucket and create a rule whose target is either **AWS Step Functions** (which runs the job with Glue `startJobRun.sync`) or a **Glue workflow**. **This works because** a single Glue job is **not** a direct rule target. Step Functions adds retries and branching; a Glue workflow target needs the `glue:notifyEvent` permission.
- **If** a pipeline must run every night at **01:00 local time**, **then** use an **EventBridge Scheduler cron** schedule with a **time zone** that starts a **Step Functions** state machine. **This works because** Scheduler handles **daylight saving time (DST)**, and each schedule has a **retry policy** and a **dead-letter queue (DLQ)**; legacy scheduled rules are **UTC only**.
- **If** a Glue job failure must alert the on-call team, **then** create a rule on **`Glue Job State Change`** with state `FAILED` or `TIMEOUT` and send it to an **Amazon Simple Notification Service (SNS)** topic (email or chat). **This works because** Glue publishes these events to the **default bus** for **free**, so no polling code is needed.
- **If** events from **40 accounts** must reach a **central ops account**, **then** each account's rule targets the **central bus** using an **IAM role** that allows `events:PutEvents`, and the central bus policy uses `Principal "*"` with **`aws:PrincipalOrgID`**. **This works because** the org condition grants the **whole AWS Organization in one statement**, and new cross-account bus targets **require** a role on the sender's rule (since March 2023). Add `account` to the central rules' patterns to accept only known senders.
- **If** a consumer bug corrupted **2 hours** of output, **then** fix the code, then **replay the archive** for those 2 hours **to that rule only**. **This works because** replay can target **specific rules** on the source bus, and replayed events carry **`replay-name`**, so the target can tell them apart. Catch: replay repeats side effects, so the target must be **idempotent**.
- **If** a job must run **once** next Tuesday at 15:30, **then** use an **EventBridge Scheduler one-time schedule** (`at()`) with **`ActionAfterCompletion: DELETE`**. **This works because** legacy scheduled rules have **no one-time option**, and deleting the schedule after it runs stops it counting against the schedule quota.
- **If** an **Amazon Simple Queue Service (SQS)** queue must feed Step Functions without **AWS Lambda**, **then** use **EventBridge Pipes** (SQS source, Step Functions target). **This works because** a pipe **polls SQS** for you and invokes Step Functions **directly**, with no glue code.
- **If** security requires producers in **private subnets** with no internet access, **then** create an **interface VPC endpoint** (AWS PrivateLink) `com.amazonaws.<region>.events`. **This works because** producers can then call **`PutEvents`** without a **NAT gateway** or internet gateway. An **endpoint policy** can further limit which buses or actions the VPC may call.
- **If** compliance requires control over the encryption key, **then** use a **customer managed AWS Key Management Service (KMS) key** on the **bus** and the **archive**, and set a **DLQ** on the bus. **This works because** the default **AWS owned key** has **no audit trail** and no key policy you control, while a customer managed key shows its use in **CloudTrail**. The DLQ catches events that fail encryption or decryption (for example a disabled key). Catch: KMS request and monthly key fees apply.
- **If** a bus encrypted with a customer managed key suddenly stops delivering, **then** check whether the **key was disabled** or its **key policy changed**, and look in the bus **DLQ**. **This works because** events that EventBridge cannot decrypt fail with **`EVENT_DECRYPTION_FAILURE`** and are sent to the DLQ.
- **If** schema discovery is required on a bus with a customer managed key, **then** it is **not possible**; use a separate bus with an **AWS owned key** for discovery. **This works because** schema discovery is **not supported** on buses encrypted with a customer managed key.
- **If** any AWS account could put events on your bus, **then** replace `Principal "*"` with an **organization condition** (`aws:PrincipalOrgID`) and add **`account`** to every rule pattern. **This works because** `"Principal": "*"` **without a condition** lets **any AWS account** send events, and those strangers' events could trigger your targets.
- **If** a Lambda target is invoked **twice** for one event, **then** make it **idempotent** by deduplicating on the event **`id`**. **This works because** EventBridge delivery is **at least once**, so duplicates can happen.
- **If** the **`InvocationsFailedToBeSentToDlq`** alarm fires, **then** fix the DLQ at once: its **queue policy**, **Region** (must match the rule), **type** (must be standard, not FIFO) and **encryption key**. **This works because** this metric means events failed delivery **and** could not reach the DLQ, so they are **lost**.
- **If** a launch will push **30,000 matched events per second** in us-east-1, **then** request higher **invocation** and **`PutEvents`** quotas through **Service Quotas** before the launch. **This works because** the defaults in us-east-1 are **18,750** invocations/s and **10,000** `PutEvents`/s (both adjustable). Over the invocation quota, invocations are **delayed**; over the `PutEvents` quota, calls are **rejected** and the producer must retry.
- **If** a producer sends **900 KB** events and the bill is high, **then** shrink the payload or use the **claim-check pattern** (store data in S3, send a pointer). **This works because** each **64 KB chunk** is billed as **one event**, so a 900 KB event costs about **15 events**.
- **If** a pipe reads **10 million** SQS messages but only **10%** are relevant, **then** add a **Pipes filter**. **This works because** Pipes bills only the requests that **pass the filter** ($0.40 per million); filtered-out events are free.
- **If** a nightly schedule must reach **5 targets**, **then** point the one schedule at an **event bus** (via the EventBridge PutEvents templated target **(verify)**), an **SNS topic** or **Step Functions**, which fan out further, or create one schedule per target. **This works because** a Scheduler schedule has exactly **one target**.
- **If** an auditor asks **who changed a rule**, **then** search **AWS CloudTrail** for **`PutRule`** and **`PutTargets`** events. **This works because** CloudTrail logs EventBridge **management calls**, including who made them.
- **If** events must be **strictly ordered per customer** across accounts, **then** use **SQS FIFO** or **Amazon Kinesis Data Streams**, or the **new Custom Event Bus** with **`EventGroupId`**. **This works because** classic buses give **no ordering**; FIFO queues, Kinesis shards and new-bus event groups keep order.
- **If** many teams in many accounts need the same order events with their own filters, **then** share a **new Custom Event Bus** with **AWS Resource Access Manager (RAM)**, so each team creates and owns its own **subscribers**. **This works because** with the classic model you need a bus policy plus forwarding rules and receiver rules per team, while the new bus needs **no bus-to-bus forwarding**.
- **If** the exam asks for the **least operational overhead** way to react to an AWS service state change, **then** answer with an **EventBridge rule**. **This works because** AWS services publish state-change events to the default bus by themselves, so **no polling code or servers** are needed.
- **If** notifications must go by **email and SMS** to thousands of users, **then** use **Amazon SNS**, optionally fed by an EventBridge rule. **This works because** SNS pushes to **email, SMS and HTTP** for huge subscriber counts, while EventBridge has no email or SMS delivery of its own.
- **If** data must be **replayed by position** with strict ordering for analytics, **then** use **Amazon Kinesis Data Streams**. **This works because** Kinesis keeps an **ordered log per shard** with replay by sequence, while EventBridge archive replay works in **one-minute time slices** and does **not** keep the original order.
- **If** a third-party webhook receiver must only see some fields, **then** use an **input transformer** on the **API destination** target. **This works because** the transformer builds a new body from chosen fields, so it can **mask or drop sensitive fields** before the event leaves AWS.
- **If** someone added a **rogue target** to a production rule, **then** restrict **`events:PutTargets`** in IAM and **alert** on CloudTrail `PutTargets` events. **This works because** a new target receives **every event** the rule matches, so this permission can exfiltrate data and should be treated like a **write permission on data**.
- **If** a pipe reading an SQS queue encrypted with a **customer managed KMS key** fails with **access denied**, **then** allow **`kms:Decrypt`** for the pipe's role in **both** the **key policy** and the **role policy**. **This works because** the pipe's role needs explicit **decrypt rights** to read encrypted messages.
- **If** a CloudWatch alarm on **`FailedInvocations`** shows **no data**, **then** that is normal when there are no failures. **This works because** many EventBridge metrics are **only sent when non-zero**, so a missing metric often means zero.
- **If** the exam asks how to restrict a producer to **its own event source**, **then** add an **IAM `Condition`** on **`events:source`** **(verify)** in the producer's `events:PutEvents` policy (for example `com.mycompany.orders`). **This works because** EventBridge supports condition keys for `PutEvents`, so the app can publish only events with its own `source`.
- **If** a target in another account must be invoked with **no bus** in that account, **then** use a **direct cross-account target** (SQS, SNS, Lambda, Kinesis Data Streams or API Gateway), with an **IAM execution role** on the sender's rule and a **resource policy** on the target that allows that role. **This works because** **direct delivery**, launched in **January 2025**, sends events straight to cross-account targets that have resource policies.

Verified from AWS docs on 2026-11-03 (EventBridge user guide: encryption key options, event bus CMK encryption, DLQs, monitoring metrics, quotas, troubleshooting, cross-account delivery, VPC endpoints, Pipes error handling and logging; Scheduler quotas; EventBridge pricing page; Custom Event Bus overview and quotas).
Unconfirmed (verify): full list of EventBridge IAM condition keys and `events:ManagedBy`; ABAC coverage; Scheduler VPC endpoint name; API destination source IPs; `PutEvents` CloudTrail data event status; Pipes and Scheduler metric namespaces and names; SNS and SQS max message sizes in the comparison table; partner events billed when unmatched; S3 `sequencer` field name for dedupe.

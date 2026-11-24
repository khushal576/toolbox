# SQS and SNS – 3. Security, monitoring, cost, limits, troubleshooting and scenarios

Short notes. Each point is a fact you can be asked about.

## A. IAM (identity-based access)
- All SQS and SNS API access is through IAM and SigV4-signed requests. There are no queue users or passwords.
- SQS producer actions: `sqs:SendMessage` (covers `SendMessageBatch`), plus `sqs:GetQueueUrl` if the app looks up the URL.
- SQS consumer actions: `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, `sqs:GetQueueAttributes`.
- SQS admin actions: `CreateQueue`, `DeleteQueue`, `SetQueueAttributes`, `PurgeQueue`, `AddPermission`, tagging, message move tasks.
- SNS publisher action: `sns:Publish` (covers `PublishBatch`). Subscriber management: `sns:Subscribe`, `sns:Unsubscribe`, `sns:SetSubscriptionAttributes`.
- Scope policies to queue and topic ARNs. Do not give `sqs:*` or `sns:*` on `*` to applications.
- Separate roles for producers, consumers and admins, so a consumer cannot purge or delete the queue.
- Lambda ESM permissions come from the function execution role (`AWSLambdaSQSQueueExecutionRole`).
- SNS needs an IAM role for Firehose subscriptions and for delivery status logging to CloudWatch Logs.
- SQS supports tag-based conditions (ABAC) with `aws:ResourceTag/...` **(verify current coverage)**.
- Queue URLs and names are case-sensitive; a wrong case gives `QueueDoesNotExist`, not `AccessDenied`.

## B. Resource-based policies (queue policies and topic policies)
- SQS queue access policy and SNS topic access policy are resource-based JSON policies on the queue/topic.
- Use them for cross-account access and for letting AWS services (SNS, S3, EventBridge) send to the queue or publish to the topic.
- Cross-account: the resource policy allows the other account; the caller also needs IAM permission in its own account.
- SNS → SQS: queue policy allows principal `sns.amazonaws.com`, action `sqs:SendMessage`, condition `aws:SourceArn` = topic ARN.
- S3 → SQS or S3 → SNS: allow principal `s3.amazonaws.com` with `aws:SourceArn` = bucket ARN and `aws:SourceAccount` = bucket owner account.
- Why both for S3: bucket ARNs have no account ID, so `aws:SourceAccount` stops another account's bucket of the same name pattern.
- `aws:SourceArn` / `aws:SourceAccount` protect against the confused deputy problem (a service tricked into acting for another customer).
- Catch: without `aws:SourceArn`, `Principal: "*"` or a bare service principal lets any topic or bucket send to your queue.
- SQS policy quota: max 8,192 bytes, 20 statements, 50 principals, 10 conditions.
- `AddPermission` (SQS) / `AddPermission` (SNS) is a simple way to add account-level grants; full JSON policies are more flexible.
- Anonymous access to a queue is possible with `Principal: "*"` and no conditions. Avoid; SSE queues reject anonymous calls.
- Restrict to a VPC with `aws:SourceVpc` or `aws:SourceVpce` in a Deny statement.
- Remember service exceptions in Deny policies (for example DLQ redrive uses `aws:CalledViaLast` = `sqs.amazonaws.com`).

## C. Encryption in transit
- SQS and SNS endpoints support HTTPS (TLS). Queues/topics with SSE require HTTPS and SigV4.
- Enforce TLS with a Deny on `aws:SecureTransport = false` in the queue or topic policy.
- FIPS endpoints exist in some Regions (for example `sns-fips.us-east-1.api.aws`).
- Client-side encryption (encrypt before send) protects data even from people with queue access; consumers must decrypt.

## D. Encryption at rest: SQS
- Two options: SSE-SQS (SQS-managed keys, no KMS cost) or SSE-KMS (AWS KMS key).
- SSE-SQS is the default for newly created queues **(verify)**.
- SSE-KMS key choices: AWS managed key `alias/aws/sqs`, or a customer managed key (CMK).
- SSE encrypts only the message body. Not encrypted: queue name and attributes, message ID, timestamp, message attributes, metrics.
- Only messages sent after SSE is enabled are encrypted; backlogged messages stay plaintext. Disabling SSE does not decrypt existing messages.
- Moving to a DLQ keeps the original encryption state (encrypted stays encrypted, plaintext stays plaintext).
- Envelope encryption: KMS key encrypts a data key; the data key encrypts messages; the encrypted data key is stored with the message.
- Data key reuse period: 60 seconds to 86,400 seconds (24 hours). Default 300 seconds (5 minutes).
- Longer reuse period = fewer KMS calls and lower cost; shorter = tighter security.
- If KMS is briefly unreachable, SQS keeps using the cached data key.
- Data keys are not shared between principals, so KMS calls grow with the number of distinct producer/consumer principals.
- KMS request estimate per queue: R = (billing seconds / reuse period) × (2 × producers + consumers).
- Producers need `kms:GenerateDataKey` and `kms:Decrypt`; consumers need `kms:Decrypt`.
- Consumers of a DLQ also need `kms:Decrypt` on the source queue's key.
- Changing the queue key: old messages stay encrypted with the old key. Keep the old key enabled until those messages are gone.
- A queue encrypted with `aws/sqs` cannot invoke a Lambda function in another account. Use a CMK.
- AWS managed key policies cannot be edited, so other accounts and AWS service principals cannot be granted on `aws/sqs`.

## E. Encryption at rest: SNS
- SNS SSE uses AWS KMS only (no SNS-managed option). Key: `alias/aws/sns` or a customer managed key. Symmetric keys only.
- SSE encrypts the message body. Not encrypted: topic metadata, subject, message ID, timestamp, attributes, metrics.
- Publishers need `kms:GenerateDataKey*` and `kms:Decrypt` on the topic key.
- SNS reuses a data key for up to 5 minutes. KMS estimate per topic: R = (billing seconds / 300) × (2 × publishers).
- Encryption covers storage inside SNS. When SNS delivers to an encrypted SQS queue, the queue's own key applies.

## F. KMS key policies for AWS service producers (big exam trap)
- When an AWS service writes to an encrypted queue or topic, it needs KMS permissions on the key.
- You must use a customer managed key; the AWS managed keys (`aws/sqs`, `aws/sns`) cannot grant service principals.
- SNS → encrypted SQS: CMK key policy allows `sns.amazonaws.com` `kms:GenerateDataKey` and `kms:Decrypt`.
- S3 event notifications → encrypted SQS or SNS: key policy allows `s3.amazonaws.com` the same actions.
- EventBridge → encrypted SQS: key policy allows `events.amazonaws.com`.
- CloudWatch alarms → encrypted SNS topic: key policy allows `cloudwatch.amazonaws.com`.
- Other SNS event sources that need the key policy: DMS, RDS events (`events.rds.amazonaws.com`), Redshift, DynamoDB, SES, CodeCommit, Inspector.
- Some sources (Auto Scaling, AWS Config, IoT, CodePipeline, Elastic Beanstalk) need an IAM role in the key policy instead of a service principal.
- Add `aws:SourceArn`/`aws:SourceAccount` conditions to the key policy statement to block confused deputy use (not supported for EventBridge → encrypted SNS).
- Symptom of a missing grant: events silently stop arriving and the source logs KMS access denied (S3 events, SNS delivery failures).
- SNS subscription DLQ that is encrypted also needs a CMK that allows SNS.
- SNS FIFO archive replay from an encrypted topic needs `sns.amazonaws.com` decrypt rights on the key.

## G. Private network access
- SQS and SNS support interface VPC endpoints (AWS PrivateLink). There is no gateway endpoint for them.
- With the endpoint and private DNS, SDK calls from private subnets reach SQS/SNS without a NAT gateway or internet.
- VPC endpoint policies can limit which queues/topics and actions are reachable through the endpoint.
- Queue/topic policy with Deny when `aws:SourceVpce` is not your endpoint forces all access through it.
- Catch: such a Deny also blocks the console and AWS services unless you add exceptions.
- SNS delivers to HTTP/S endpoints over the public internet; it cannot reach a private-only HTTP endpoint inside your VPC. Use SQS or Lambda for private targets.
- Amazon MQ brokers run inside your VPC; access is controlled by security groups and broker users.

## H. Audit with CloudTrail
- Management events (logged by default): SQS `CreateQueue`, `DeleteQueue`, `SetQueueAttributes`, `PurgeQueue`, `AddPermission`, `TagQueue`, message move tasks.
- SNS management calls (`CreateTopic`, `Subscribe`, `SetTopicAttributes`, `DeleteTopic`) are logged as management events.
- SQS data events (opt-in, extra cost, advanced event selectors, resource type `AWS::SQS::Queue`): `SendMessage`, `ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility`, their batch versions, plus `GetQueueAttributes`, `GetQueueUrl`, `ListQueues` and others.
- Data events are not shown in CloudTrail Event history; you need a trail or event data store.
- The SQS message body is hidden in CloudTrail records (`HIDDEN_DUE_TO_SECURITY_REASONS`).
- SNS `Publish` is a data event for CloudTrail **(verify)**.
- Use CloudTrail to answer "who purged the queue" or "who changed the queue policy".

## I. Monitoring SQS (CloudWatch, namespace AWS/SQS, dimension QueueName)
- Metrics are pushed every minute for active queues, free of charge. Many are approximate.
- `ApproximateNumberOfMessagesVisible`: backlog waiting to be received. Main scaling and DLQ alarm metric.
- `ApproximateNumberOfMessagesNotVisible`: in flight (received, not deleted). High = slow or stuck consumers, or approaching the in-flight limit.
- `ApproximateNumberOfMessagesDelayed`: hidden by delay queue or message timers.
- `ApproximateAgeOfOldestMessage`: age of the oldest unprocessed message. Main latency/SLA alarm; alarm well before retention ends.
- Catch: on standard queues, messages received 3+ times are moved to the back and excluded from this age metric.
- `NumberOfMessagesSent`: messages added by send calls. Does not include automatic DLQ moves.
- `NumberOfMessagesReceived`: includes repeats of the same message, so it can exceed messages sent.
- `NumberOfMessagesDeleted`: successful deletes, may count duplicates. A drop to 0 with Lambda partial batches often means a bad response format.
- `NumberOfEmptyReceives`: receives that returned nothing. High = short polling or over-polling; switch to long polling.
- `SentMessageSize`: bytes per message sent; appears after the first send.
- FIFO only: `NumberOfDeduplicatedSentMessages` (duplicates dropped) and `ApproximateNumberOfGroupsWithInflightMessages` (parallelism).
- Fair queue metrics: `ApproximateNumberOfNoisyGroups` and the `...InQuietGroups` variants.
- Rare false non-zero `NotVisible` values can appear; alarm on several datapoints, not one.

## J. Monitoring SNS (namespace AWS/SNS, dimension TopicName)
- `NumberOfMessagesPublished`: messages published to the topic.
- `NumberOfNotificationsDelivered`: successful deliveries to subscriptions.
- `NumberOfNotificationsFailed`: failed deliveries. For HTTP/S it counts every failed attempt including retries; for SQS, email, SMS, push it counts once when SNS gives up.
- `NumberOfNotificationsFilteredOut` (+ `-MessageAttributes`, `-MessageBody`, `-NoMessageAttributes`, `-InvalidAttributes`, `-InvalidMessageBody`): messages rejected by filter policies.
- `NumberOfNotificationsRedrivenToDlq` and `NumberOfNotificationsFailedToRedriveToDlq`.
- `PublishSize`: bytes published (batch counted as one datapoint).
- SMS: `SMSMonthToDateSpentUSD`, `SMSSuccessRate`.
- Usage metrics (AWS/Usage): `NumberOfMessagesPublishedPerAccount`, `ApproximateNumberOfTopics`, `ApproximateNumberOfFilterPolicies`.
- Delivery status logs (CloudWatch Logs) give per-message success/failure details for SQS, Lambda, HTTP/S, Firehose and push.
- A topic is "active" for CloudWatch for 6 hours after its last API call; inactive topics stop emitting metrics.

## K. Alarms worth building
- DLQ `ApproximateNumberOfMessagesVisible` ≥ 1 → SNS alert (poison message or broken consumer).
- Source queue `ApproximateAgeOfOldestMessage` > SLA (and < retention) → consumers lagging.
- `ApproximateNumberOfMessagesVisible` rising → scale out workers (target tracking on backlog per instance).
- SNS `NumberOfNotificationsFailed` > 0 → endpoint or permission problem.
- SNS `NumberOfNotificationsFilteredOut` unexpectedly high → filter policy or attribute bug.
- Lambda `Throttles` and ESM metrics alongside queue age → concurrency limits.

## L. Pricing: SQS
- Free tier: 1 million SQS requests per month, every month, across Regions (not GovCloud).
- Every API action is a billed request (send, receive, delete, change visibility, get attributes, empty receives too).
- Each 64 KB chunk of payload counts as one request. A 256 KB message = 4 requests; a 1 MiB message = 16 requests.
- A batch of 1–10 messages is one request per 64 KB chunk of the total batch.
- Standard: about $0.40 per million requests (first 100 billion per month, lower tiers after) **(verify)**.
- FIFO: about $0.50 per million requests **(verify)**. FIFO rates apply to send, receive, delete and change-visibility calls on FIFO queues.
- Fair queues: calls involving messages with a group ID on standard queues pay a fair-queue rate on top of standard **(verify amount)**.
- Data transfer in the same Region is free; cross-Region and internet transfer use standard AWS rates.
- SSE-KMS adds KMS request charges (and CMK monthly fee). SSE-SQS adds nothing.
- Extended client payloads add S3 storage and request costs.
- Lambda ESM polling makes SQS requests even when idle (low but not zero); provisioned mode pollers cost extra on the Lambda bill.

## M. Pricing: SNS
- Standard topics: billed per publish request (each 64 KB chunk = 1 request) plus per delivery, by endpoint type.
- Approximate standard rates: $0.50 per million publishes; HTTP/S $0.60 per million; email $2.00 per 100,000; mobile push $0.50 per million; deliveries to SQS and Lambda have no SNS delivery fee **(verify all rates)**.
- Free tier: 1 million publishes, 100,000 HTTP/S deliveries, 1,000 email deliveries per month **(verify)**.
- SMS: per message, varies by country, billed under AWS End User Messaging.
- FIFO topics: billed per published message and per subscribed message, plus payload GB. Messages under 1 KB round up to 1 KB.
- Attribute-based filtering free; payload-based filtering billed by data scanned (1 KB minimum per message).
- Archiving: by data volume and storage time (1-day minimum). Replay at FIFO request and payload rates.
- Data transfer: into SNS free; SNS pricing page lists transfer to SQS/Lambda at data transfer rates **(verify)**.
- KMS charges for encrypted topics.

## N. Cost optimization
- Long polling (20 s) to cut empty receives.
- Batch send/delete (10 per call) to cut requests up to 10x.
- Keep messages small (under 64 KB) or put big data in S3 and send a pointer.
- Use standard queues unless you truly need order or dedupe; FIFO costs more per request.
- Use SSE-SQS, or raise the KMS data key reuse period (up to 24 h), to reduce KMS calls.
- Use attribute-based filtering instead of payload-based when possible.
- Subscribe a standard SQS queue (not FIFO) to a FIFO topic for analytics consumers that do not need order.
- Delete idle queues and topics in dev accounts; Lambda pollers on idle queues still make requests.

## O. Quotas and numbers (SQS)
| Item | Value |
|---|---|
| Message size | 1 byte – 1 MiB (2 GB via Extended Client + S3) |
| Retention | 60 s – 14 days, default 4 days |
| Visibility timeout | 0 s – 12 h, default 30 s |
| Delay (queue or message) | 0 – 15 min (FIFO: queue level only) |
| Long poll wait | max 20 s |
| Messages per receive / batch | max 10 |
| Message attributes | 10 per message |
| In flight | ~120,000 standard; 120,000 FIFO |
| FIFO throughput (normal) | 300 TPS per action, 3,000 msg/s with batching |
| FIFO high throughput | up to 70,000 TPS / 700,000 msg/s batched (largest Regions) |
| Dedupe interval | 5 minutes (fixed) |
| Group ID / dedupe ID length | 128 characters |
| Queue name | 80 characters (`.fifo` suffix included) |
| Backlog | unlimited |
| Purge | once per 60 s |
| DLQ redrive | max 500 msg/s custom, 36 h per task, 100 active tasks per account |
| Redrive allow policy byQueue | 10 source queues |
| Queue policy | 8,192 bytes, 20 statements, 50 principals, 10 conditions |
| Tags | 50 recommended max per queue |
| Data key reuse | 60 s – 24 h, default 5 min |

## P. Quotas and numbers (SNS and Lambda)
| Item | Value |
|---|---|
| Topics | 100,000 standard, 1,000 FIFO per account |
| Subscriptions | 12,500,000 per standard topic, 100 per FIFO topic |
| Pending subscriptions | 5,000 per account |
| Message size | 256 KiB default, up to 1 MiB with `MaximumMessageSize` (2 GB via Extended Client) |
| PublishBatch | 10 messages |
| Filter policies | 200 per topic, 10,000 per account; 5 keys; 150 combinations; 256 KB |
| Email delivery | 10 msg/s per subscription (hard) |
| FIFO topic | 300 msg/s per group; 3,000 msg/s or 20 MB/s per topic (topic scope) |
| Archive retention | 1 – 365 days (FIFO only) |
| Retries, AWS endpoints | 100,015 attempts over 23 days |
| Retries, email/SMS/push | 50 attempts over 6 hours |
| HTTP/S retry policy | max 100 retries, max 3,600 s total |
| Lambda ESM batch size | 10,000 standard, 10 FIFO |
| Lambda ESM batching window | up to 300 s (standard only) |
| Lambda ESM default max concurrency | 1,250 (provisioned mode up to 100,000) |
| ESM maximum concurrency setting | 2 – 1,000 |

## Q. Troubleshooting: SQS
| Symptom | Likely cause | Fix |
|---|---|---|
| Same message processed twice (standard) | at-least-once delivery, or visibility timeout shorter than processing | idempotent consumers; raise visibility timeout; heartbeat with `ChangeMessageVisibility` |
| Duplicates in FIFO | producer retried after 5-minute window, or consumer crashed before delete | reuse dedupe ID within window; idempotent writes |
| Distinct messages missing in FIFO | content-based dedupe on identical bodies | explicit dedupe IDs or unique field in body |
| Many messages stuck "in flight" | consumers not deleting, crashed, or very long visibility timeout | fix delete logic; shorter timeout; check `NotVisible` metric |
| `OverLimit` on receive | ~120,000 in-flight limit (short polling) | delete faster, more queues, quota increase |
| Messages go to DLQ but code is fine | `maxReceiveCount` too low, timeouts, Lambda throttling | raise count (≥ 5), visibility ≥ 6x function timeout, check concurrency |
| Poison message retried forever | no redrive policy | add DLQ with `maxReceiveCount` |
| FIFO group stops progressing | one failing message blocks its group | fix the message, DLQ, or let it expire |
| DLQ messages expire too soon | standard keeps original enqueue time | DLQ retention longer than source (14 days) |
| Messages vanish without processing | retention expired, or purge | longer retention, alarm on oldest age, check CloudTrail `PurgeQueue` |
| High cost with an idle queue | short polling loops, many empty receives | long polling 20 s; fewer pollers |
| `InvalidMessageContents` | characters outside the allowed set | Base64 or clean the body |
| Send fails with size error | over 1 MiB or over queue `MaximumMessageSize` | Extended Client (S3) or raise attribute |
| FIFO throughput capped | no batching, few message groups, normal mode | batch, more groups, high-throughput mode |
| Consumers get empty responses though messages exist | short polling samples a subset of servers | long polling |

## R. Troubleshooting: Lambda + SQS
| Symptom | Likely cause | Fix |
|---|---|---|
| Whole batch reprocessed after one bad record | no partial batch response | enable `ReportBatchItemFailures`, return failed IDs |
| Failed records do not return to queue | wrong response format (bad key, empty ID) | return `batchItemFailures` with valid `itemIdentifier`s |
| Lambda throttled, queue age grows | reserved/account concurrency lower than ESM scale | raise reserved concurrency ≥ ESM max concurrency; use max concurrency to share |
| Mapping creation fails | function timeout > queue visibility timeout | raise visibility timeout (6x function timeout) |
| Lambda cannot read encrypted queue | role lacks `kms:Decrypt` | add KMS permission and key policy grant |
| Cross-account Lambda trigger fails on encrypted queue | queue uses `aws/sqs` key | switch to a customer managed key |
| FIFO Lambda concurrency stays low | few active message groups | more group IDs |
| Batch smaller than batch size | 6 MB payload limit or short batching window | larger window, smaller messages |

## S. Troubleshooting: SNS
| Symptom | Likely cause | Fix |
|---|---|---|
| Messages not reaching SQS subscriber | queue policy does not allow the topic | allow `sns.amazonaws.com` `sqs:SendMessage` with `aws:SourceArn` = topic |
| SNS → encrypted SQS fails (KMS AccessDenied) | queue uses `aws/sqs` or key policy lacks SNS | CMK with `sns.amazonaws.com` `GenerateDataKey` + `Decrypt` |
| S3 events not arriving in SQS/SNS | missing resource policy or KMS grant for `s3.amazonaws.com`; FIFO target | fix policies; use standard target or EventBridge for FIFO |
| CloudWatch alarm cannot publish to topic | encrypted topic with `aws/sns` | CMK allowing `cloudwatch.amazonaws.com` |
| Filter not matching | wrong scope (attributes vs body), case mismatch, wrong attribute type, missing attributes, not double-escaped, 15-min delay | check `FilterPolicyScope`, `NumberOfNotificationsFilteredOut-*` metrics |
| Email/HTTP subscriber gets nothing | subscription pending confirmation | confirm subscription |
| HTTP endpoint overloaded | default delivery policy, bursty publishing | delivery policy with throttle and backoff |
| Messages lost after endpoint outage | retries exhausted, no DLQ | subscription DLQ; for HTTP/S longer retry policy (max 1 h) |
| Raw delivery to SQS drops messages | more than 10 attributes | reduce attributes or disable raw delivery |
| Publish fails with `InvalidParameter` | message over topic `MaximumMessageSize` | raise to 1 MiB or use Extended Client |
| Throttling on Publish | Region publish quota | `PublishBatch`, quota increase, spread topics |
| Cannot delete FIFO topic | active archive policy | disable archive (deletes archive) then delete |

## Scenarios: "If X → Y, because Z"
- If a partner account must send messages to your queue → queue policy allowing their account (and their IAM allowing send), because cross-account needs both sides.
- If S3 must notify an SQS queue → queue policy for `s3.amazonaws.com` with `aws:SourceArn` and `aws:SourceAccount`, because bucket ARNs lack an account ID.
- If S3 notifications to an encrypted queue stop arriving → use a CMK whose key policy allows `s3.amazonaws.com`, because `aws/sqs` cannot grant service principals.
- If SNS fan-out to an encrypted SQS queue fails → CMK key policy allowing `sns.amazonaws.com`, because SNS must generate data keys to write.
- If compliance needs a key you control, with audit of key use → SSE-KMS with a customer managed key, because key policy and CloudTrail give control.
- If encryption is required at no extra cost → SSE-SQS, because it uses SQS-managed keys without KMS charges.
- If KMS costs on a busy queue are high → raise the data key reuse period (up to 24 h), because fewer data keys mean fewer KMS calls.
- If old messages still use the previous KMS key after rotation to a new key → keep the old key until they drain, because existing messages are not re-encrypted.
- If workers in private subnets must reach SQS without NAT → interface VPC endpoint, because SQS has no gateway endpoint.
- If only your VPC endpoint may use the queue → Deny with `aws:SourceVpce` condition in the queue policy, because IAM alone allows any network path.
- If all access must use TLS → Deny `aws:SecureTransport = false`, because it rejects plain HTTP calls.
- If auditors ask who purged a queue → CloudTrail management events, because `PurgeQueue` is logged by default.
- If auditors ask who read messages → enable SQS data events in CloudTrail, because receive/delete are not logged by default.
- If secrets are put in message attributes → move them into the encrypted body, because SSE does not encrypt attributes.
- If you need warning before messages expire → alarm on `ApproximateAgeOfOldestMessage` below retention, because expired messages are deleted silently.
- If a worker fleet must scale with load → target tracking on backlog per instance (`ApproximateNumberOfMessagesVisible` / instances), because CPU does not show queue depth.
- If the bill shows many SQS requests for an idle app → long polling and batching, because every empty receive is billed.
- If 200 KB messages cost 4x expected → it is the 64 KB chunk rule, because each chunk is one request; compress or move data to S3.
- If DLQ alarms never fire even though messages fail → alarm on DLQ `ApproximateNumberOfMessagesVisible`, because `NumberOfMessagesSent` ignores automatic DLQ moves.
- If SNS failures need alerting → alarm on `NumberOfNotificationsFailed` plus subscription DLQ, because SNS drops messages after retries.
- If filtered messages are "missing" → check `NumberOfNotificationsFilteredOut`, because filtered messages are not counted as failures.
- If a data lake pipeline gets every S3 upload, needs ordered per-customer processing, and must not lose data → S3 → EventBridge → SQS FIFO (group = customer) → Lambda with DLQ, because S3 cannot target FIFO directly.
- If ingestion bursts overwhelm a Redshift loader → SQS buffer with a fixed number of consumers, because the queue absorbs spikes.
- If one event stream must feed an ETL queue, a search indexer and an S3 archive → SNS topic with two SQS subscriptions and one Firehose subscription, because SNS fans out to mixed targets.
- If large files must flow through the messaging layer → store in S3 and send the key (or Extended Client), because SQS/SNS cap messages at 1 MiB.
- If retries must back off before going to a DLQ → visibility timeout / `ChangeMessageVisibility` for delay plus `maxReceiveCount`, because each failed receive counts toward the DLQ.
- If a JMS application must move to AWS with minimal change and survive an AZ loss → Amazon MQ ActiveMQ active/standby, because it keeps JMS and fails over across AZs.
- If an exam asks for the most operationally simple decoupling option → SQS (standard), because it is serverless with no capacity planning.

Verified from AWS docs on 2026-11-03 (SQS SSE and key management, DLQ redrive permissions and VPC exceptions, SQS CloudTrail logging, SQS CloudWatch metrics, SQS quotas, SQS pricing page text, SNS SSE and key management, SNS quotas, SNS CloudWatch metrics, SNS delivery retries, SNS raw delivery, SNS pricing page text, Lambda SQS ESM pages, S3 event destinations).
Unconfirmed (verify): SSE-SQS default on new queues; SQS ABAC coverage; SNS Publish as a CloudTrail data event; exact SQS per-million prices (standard, FIFO, fair queues); exact SNS per-delivery prices and free tier; SNS data transfer wording to SQS/Lambda.

# SQS and SNS – 1. SQS queues, FIFO, visibility timeout, DLQs and Lambda

Short notes. Each point is a fact you can be asked about.

## A. What SQS is (and is not)
- Amazon SQS (Simple Queue Service) = fully managed message queue. Producers send messages, consumers poll, process and delete them.
- It decouples producer and consumer. The producer does not wait for the consumer and does not need it to be up.
- It is a buffer: a spike of writes waits in the queue while consumers work at their own speed.
- Pull model: consumers must call `ReceiveMessage`. SQS never pushes to your code (Lambda polls for you).
- One message is meant for one consumer. After a consumer deletes it, it is gone for everyone.
- No replay: a deleted message cannot be read again. Keep a copy elsewhere (S3, KDS) if you need replay.
- Messages are stored redundantly across multiple AZs before `SendMessage` returns success.
- Regional service. A queue lives in one Region; there is no built-in cross-Region replication.
- Pick SQS for: work queues, decoupling microservices, absorbing bursts, retry with DLQ, S3 event fan-in, job dispatch to a worker fleet.
- Avoid SQS for: many independent readers of the same data (use SNS fan-out or KDS), replay/history (KDS, MSK), large files (put them in S3), strict ordered log analytics (KDS).
- Two queue types: standard (default) and FIFO. You choose at creation and cannot convert later.

## B. Message lifecycle
- 1) Producer calls `SendMessage` / `SendMessageBatch`. SQS returns a `MessageId`.
- 2) Consumer calls `ReceiveMessage`. It gets up to 10 messages, each with a receipt handle.
- 3) The message stays in the queue but is hidden for the visibility timeout ("in flight").
- 4) Consumer processes it, then calls `DeleteMessage` with the receipt handle.
- 5) If not deleted before the visibility timeout ends, it becomes visible again and is received again.
- Delete needs the receipt handle from a receive, not the message ID. Each receive gives a new receipt handle.
- Every receive increases the system attribute `ApproximateReceiveCount`. The DLQ rule uses this count.
- If nobody deletes a message, it is removed automatically when the retention period ends (data loss, silently).

## C. Standard vs FIFO queues
| | Standard | FIFO |
|---|---|---|
| Delivery | at-least-once (duplicates possible) | exactly-once processing (no duplicates added in 5-min window) |
| Ordering | best-effort, can be out of order | strict order within a message group |
| Throughput | nearly unlimited API calls per second | 300 TPS per API action (3,000 msg/s batched); high-throughput mode much higher |
| Name | any (up to 80 chars) | must end in `.fifo` (suffix counts in 80 chars) |
| Per-message delay | yes (message timers) | no, queue-level delay only |
| S3 event notification target | yes | no (use EventBridge) |
| `MessageGroupId` | optional (enables fair queues) | required |
| Price | lower | higher per request |
- Standard: design consumers to be idempotent, because the same message can arrive twice.
- FIFO: order is per message group, not per queue. Different groups can interleave.
- FIFO: send without `MessageGroupId` fails. Send without dedupe ID fails unless content-based dedupe is on.

## D. FIFO details: message groups and deduplication
- Message group ID = ordering key (for example customer ID, order ID, device ID). Up to 128 characters.
- Messages in one group are processed one batch at a time: while a group has in-flight messages, SQS returns no more from that group.
- This is how FIFO gives ordering with many consumers: different consumers take different groups in parallel.
- Catch: one hot group is a serial bottleneck. Use many distinct group IDs for parallelism.
- Use the same group ID for all messages only if every message must be strictly ordered (then throughput is one-at-a-time).
- A single receive can return up to 10 messages from the same group, in order; it may add other groups when fewer are available.
- Message deduplication ID = token. A second send with the same ID inside 5 minutes is accepted (success) but not delivered.
- Deduplication interval is fixed at 5 minutes. A resend after 5 minutes creates a duplicate.
- SQS keeps tracking the dedupe ID even after the message is received and deleted (within the window).
- Content-based deduplication: SQS makes the dedupe ID from a SHA-256 hash of the body. Message attributes are not part of the hash.
- Catch: with content-based dedupe, two genuinely different events with identical bodies inside 5 minutes collapse into one. Add a unique field (timestamp, event ID) to the body or send an explicit ID.
- An explicit `MessageDeduplicationId` overrides the content-based one.
- `ReceiveRequestAttemptId`: lets a consumer retry a failed `ReceiveMessage` and get the same batch back, without breaking order.
- Exactly-once is about not adding duplicates to the queue. Your consumer can still process twice if it crashes after work but before delete. Make side effects idempotent.
- Dedupe scope can be `queue` or `messageGroup`. With `messageGroup`, the same dedupe ID in two groups is two messages.

## E. FIFO throughput and high-throughput mode
- Normal FIFO: 300 transactions per second per API action (`SendMessage`, `ReceiveMessage`, `DeleteMessage`).
- With batching (10 per call): up to 3,000 messages per second per action.
- High-throughput FIFO: set deduplication scope = message group AND FIFO throughput limit = per message group ID.
- If you change either required setting back, the queue returns to normal throughput.
- High-throughput limits are per Region (non-batched TPS): 70,000 in us-east-1, us-west-2, eu-west-1; 19,000 in us-east-2 and eu-central-1; 9,000 in Mumbai, Singapore, Sydney, Tokyo, Spain; 4,500 in London and São Paulo; 2,400 elsewhere.
- With batching these become up to 10x messages per second (for example 700,000 msg/s in us-east-1).
- FIFO data lives in partitions. SQS adds and removes partitions automatically; you never manage them.
- Group ID is hashed to pick the partition. Many distinct group IDs spread load evenly.
- Each partition supports up to 300 operations per second, or 3,000 messages per second with batching.
- Catch: a few hot group IDs land on few partitions and hit the per-partition limit even in high-throughput mode.
- Tip: batch messages with the same group ID together when calling `SendMessageBatch`.

## F. Fair queues (standard queues, new feature)
- Fair queues reduce the "noisy neighbor" problem in multi-tenant standard queues.
- Enable by adding `MessageGroupId` (as a tenant ID) to messages on a standard queue. No queue setting, no consumer change.
- When one tenant has too many in-flight messages, SQS prefers returning other tenants' messages, so quiet tenants keep low dwell time.
- It does not cap any tenant. A noisy tenant still gets capacity when nothing else is waiting.
- On standard queues `MessageGroupId` does not give ordering. It is only a tenant label. Throughput stays unlimited.
- Extra metrics: `ApproximateNumberOfNoisyGroups`, `ApproximateNumberOfMessagesVisibleInQuietGroups`, `ApproximateAgeOfOldestMessageInQuietGroups` and others.
- Cost catch: standard-queue calls that involve messages with a group ID are billed at fair queue rates on top of standard rates.

## G. Visibility timeout
- Visibility timeout = how long a received message stays hidden from other consumers.
- Default 30 seconds. Minimum 0. Maximum 12 hours.
- Set at queue level, or override per receive (`VisibilityTimeout` parameter on `ReceiveMessage`).
- Too short → message reappears while still being processed → duplicate processing, receive count rises, may land in DLQ.
- Too long → a crashed consumer's message waits a long time before retry.
- `ChangeMessageVisibility` extends or shortens the timeout of one in-flight message (batch version exists).
- Heartbeat pattern: a long job keeps calling `ChangeMessageVisibility` to extend while it works.
- Catch: the 12-hour maximum counts from the first receive. Extending does not reset it. Jobs over 12 hours need Step Functions or splitting.
- Set visibility to 0 with `ChangeMessageVisibility` to release a message right away for another consumer.
- Standard queues: even within the visibility timeout, a rare duplicate delivery is possible (at-least-once).
- FIFO: while a message of a group is in flight, the next messages of that group wait. A slow message delays its whole group.

## H. Short vs long polling
- Short polling (default, wait time 0): queries a subset of servers and returns at once, even if empty.
- Short polling can return empty or partial results while messages exist ("false empty"). With fewer than 1,000 messages, a later request returns them.
- Long polling (wait time 1–20 seconds): queries all servers and waits until at least one message arrives or the wait ends.
- Maximum wait is 20 seconds.
- Enable per call with `WaitTimeSeconds`, or per queue with the `ReceiveMessageWaitTimeSeconds` attribute.
- The call parameter `WaitTimeSeconds` overrides the queue attribute.
- Long polling cuts empty receives, so it cuts cost (every receive is a billed request) and latency.
- Use short polling only when one thread must poll many queues and cannot block.
- `MaxNumberOfMessages` 1–10 (default 1). Ask for 10 to reduce request count.

## I. Retention, delay queues and message timers
- Retention: default 4 days. Minimum 60 seconds. Maximum 14 days (1,209,600 seconds).
- After retention, SQS deletes the message even if never processed.
- Delay queue: queue-level `DelaySeconds`, 0 (default) to 15 minutes. New messages stay invisible for that time.
- Message timer: per-message `DelaySeconds` on send, 0–15 minutes. Overrides the queue delay.
- FIFO queues do not support per-message timers. Only queue-level delay.
- Standard queue: changing the queue delay is not retroactive (old messages keep the old delay).
- FIFO queue: changing the queue delay is retroactive (affects messages already waiting).
- Need more than 15 minutes delay → EventBridge Scheduler (or Step Functions wait), not SQS.

## J. Message size, content and attributes
- Max message size is 1 MiB (1,048,576 bytes). Raised from the old 256 KiB limit; older notes and exam dumps may still say 256 KB.
- Queue attribute `MaximumMessageSize` can be set lower than the max.
- Body may be XML, JSON or unformatted text from an allowed Unicode set. Invalid characters → `InvalidMessageContents`. Base64-encode binary.
- Extended Client Library (Java, Python): stores the payload in S3 and sends a pointer in the message. Payloads up to 2 GB.
- Extended client is a client library, not a queue setting. Both producer and consumer must use it. Works only with synchronous clients.
- Catch: you also pay S3 storage, and S3 objects are not removed when you delete the message unless the client is set to do it.
- Message attributes: up to 10 per message. Name, type (String, Number, Binary, custom suffix) and value.
- System attributes returned on receive: `SentTimestamp`, `ApproximateReceiveCount`, `ApproximateFirstReceiveTimestamp`, `SenderId`, `MessageGroupId`, `MessageDeduplicationId`, `SequenceNumber`, `DeadLetterQueueSourceArn`.
- Message system attribute you can send: only `AWSTraceHeader` (X-Ray). It does not count toward size.
- SSE encrypts the body only. Attributes and metadata are not encrypted, so do not put secrets in attributes.

## K. Batching, in-flight limits and throughput
- Batch APIs: `SendMessageBatch`, `DeleteMessageBatch`, `ChangeMessageVisibilityBatch`. Up to 10 entries per call.
- Batch total size limit is 1 MiB.
- Each batch entry has its own ID (up to 80 chars). Check per-entry results: a batch can partly fail with HTTP 200.
- Batching cuts cost up to 10x, because a batch of 10 is one billed request (per 64 KB chunk).
- Standard queue in-flight limit: about 120,000 messages (received, not deleted).
- At that limit with short polling, SQS returns `OverLimit`. With long polling, no error; it just returns no new messages.
- FIFO queue in-flight limit: 120,000 (current quota page). Older material says 20,000 for FIFO; use 120,000 unless told otherwise.
- Fix in-flight limit issues: delete promptly, shorten slow processing, use more queues, or ask for an increase.

## L. Dead-letter queues (DLQs) and redrive
- DLQ = a normal SQS queue that receives messages that failed processing too many times.
- Configure on the source queue with a redrive policy: `deadLetterTargetArn` + `maxReceiveCount`.
- When `ApproximateReceiveCount` exceeds `maxReceiveCount`, SQS moves the message to the DLQ.
- DLQ must be in the same account and Region as the source queue.
- DLQ type must match: FIFO source → FIFO DLQ, standard → standard.
- `maxReceiveCount` too low (for example 1) sends good messages to the DLQ after one timeout or throttle. Use enough retries (Lambda guidance: at least 5).
- Redrive allow policy (set on the DLQ): who may use it as a DLQ. `allowAll` (default), `byQueue` (up to 10 source queue ARNs), or `denyAll`.
- Standard queues: a message received 3+ times without delete (with maxReceiveCount > 3) is moved to the back of the queue.
- FIFO catch: a DLQ breaks strict order (the failed message leaves, later ones continue). Skip a DLQ if order must never break.
- FIFO without a DLQ: a failing message blocks its group until it succeeds or expires.
- Retention trap (standard): expiry uses the original enqueue timestamp. A message that spent 3 days in a 4-day source expires 1 day after entering a 4-day DLQ.
- Fix: set the DLQ retention longer than the source queue retention (often 14 days).
- FIFO: enqueue timestamp resets when moved to the DLQ.
- On FIFO→FIFO DLQ moves, the dedupe ID is replaced with the original message ID, so DLQ dedupe does not drop distinct messages.
- Alarm on DLQ `ApproximateNumberOfMessagesVisible` > 0. `NumberOfMessagesSent` does not count automatic DLQ moves.

## M. DLQ redrive (move messages back)
- DLQ redrive moves messages from a DLQ back to the source queue (default) or to any other queue of the same type.
- APIs: `StartMessageMoveTask`, `ListMessageMoveTasks` (last 10), `CancelMessageMoveTask` (only while RUNNING).
- Velocity: system optimized, or custom max up to 500 messages per second.
- Redriven messages are new messages: new message ID, new enqueue time, so retention restarts.
- Redrive cannot filter or edit messages. Fix the bug first, then redrive.
- A redrive task can run up to 36 hours. Up to 100 active redrive tasks per account.
- Permissions: on DLQ `sqs:StartMessageMoveTask`, `ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes`; on destination `sqs:SendMessage`; plus `kms:Decrypt` / `kms:GenerateDataKey` if encrypted.
- With VPC-restricted queue policies (`aws:SourceVpc`), add an exception with `aws:CalledViaLast = sqs.amazonaws.com` or `aws:ViaAWSService`, because redrive runs outside your VPC.

## N. Purge, delete queue and temporary queues
- `PurgeQueue` deletes all messages, including in-flight ones. They cannot be recovered.
- Purge takes up to 60 seconds. A second purge within 60 seconds fails with `PurgeQueueInProgress`.
- Messages sent just after the purge call may also be deleted.
- After deleting a queue, wait about 60 seconds before creating one with the same name **(verify)**.
- Temporary Queue Client (Java): many "virtual queues" mapped onto one real host queue.
- Use it for request-response patterns: each requester gets a private reply queue without creating real queues.
- Virtual queues make no SQS API calls to create or delete, so they cost nothing; TPS limits are shared on the host queue.

## O. Lambda event source mapping (ESM) for SQS
- Lambda polls the queue for you (long polling), invokes the function synchronously with a batch, and deletes the batch on success.
- Queue and function must be in the same Region; they can be in different accounts.
- Execution role needs `sqs:ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes` (managed policy `AWSLambdaSQSQueueExecutionRole`) plus `kms:Decrypt` for encrypted queues.
- Batch size: standard up to 10,000; FIFO up to 10.
- Batch size above 10 requires a batching window (`MaximumBatchingWindowInSeconds`) of at least 1 second. Max window 300 seconds.
- Batching window applies only to standard queues.
- Batch also stops at the 6 MB synchronous payload limit; SQS/Lambda metadata counts toward it.
- Visibility timeout guidance: at least 6x the function timeout (plus the batching window). Gives room for throttling retries.
- Lambda rejects the mapping if the function timeout is longer than the queue visibility timeout.
- Set `maxReceiveCount` on the source queue to at least 5 so throttles do not push messages to the DLQ.
- Default error behavior: if the function errors, the whole batch returns to the queue after the visibility timeout, including messages that succeeded.
- Partial batch response: enable `ReportBatchItemFailures` and return `{"batchItemFailures":[{"itemIdentifier":"<messageId>"}]}`.
- Only listed failed messages return; others are deleted. Empty or null list = full success.
- Complete failure if: function throws, invalid JSON, empty/null `itemIdentifier`, or an unknown message ID.
- FIFO with partial batch: stop at the first failure and return that message and all later ones, to keep order.
- With `ReportBatchItemFailures`, Lambda does not scale down polling on failures.
- Lambda-side DLQs and on-failure destinations are for async invokes. For SQS ESM, use the queue's own redrive policy DLQ.
- Event filtering on the ESM: messages that do not match the filter are deleted from the queue, not left for others **(verify)**.

## P. Lambda scaling with SQS
- Standard queues (default mode): starts with 5 concurrent batches, adds up to 300 concurrent invokes per minute.
- Default maximum is 1,250 concurrent invokes per ESM. At low traffic it can drop to 2 to save requests.
- Maximum concurrency setting (2–1,000): caps one ESM so one queue cannot eat all the function's or account's concurrency.
- Maximum concurrency vs reserved concurrency: separate settings. Keep reserved concurrency ≥ sum of max concurrency of all ESMs on the function, or messages get throttled.
- Throttled batches return to the queue and raise the receive count. Low `maxReceiveCount` + throttling = good messages in DLQ.
- Provisioned mode: dedicated event pollers with min (2–200) and max (2–2,000). Faster scaling (up to 1,000 concurrency per minute), up to 100,000 concurrent invokes.
- Provisioned mode and maximum concurrency cannot be used together.
- FIFO queues: concurrency is capped by the number of active message groups (or max concurrency, whichever is lower).
- FIFO: Lambda retries a failed group before taking more messages from that group, so order holds.

## Q. Patterns
- Decouple ingestion: API/producer → SQS → workers. Producer stays fast when workers are slow or down.
- Buffer writes to a database: SQS smooths spikes so RDS/DynamoDB see a steady write rate.
- Worker pool with Auto Scaling: scale EC2/ECS on backlog per worker (`ApproximateNumberOfMessagesVisible` / workers).
- S3 event notifications → standard SQS queue → Lambda/Glue/EMR loader. FIFO queues are not supported S3 targets.
- S3 event message is up to 64 KB, so keep queue `MaximumMessageSize` at least 64 KB.
- Large payload: store the file in S3, send the S3 key in the message (claim-check pattern).
- Ordered processing per entity: FIFO with group ID = entity ID.
- Fan-out: SNS topic → many SQS queues (one per consumer). SQS alone cannot fan out.
- EventBridge Pipes can read from SQS and send to targets (Step Functions, EventBridge bus, etc.) with filtering and enrichment.

## R. SQS vs KDS vs SNS vs EventBridge vs Amazon MQ
| | SQS | Kinesis Data Streams | SNS | EventBridge | Amazon MQ |
|---|---|---|---|---|---|
| Model | queue, pull | ordered log, pull/push | pub/sub push | event bus + rules | managed broker (ActiveMQ/RabbitMQ) |
| Consumers per message | one | many independent | many subscribers | many targets per rule | depends (queue or topic) |
| Replay | no | yes, within retention | FIFO archive/replay only | archive and replay | no (broker dependent) |
| Ordering | FIFO per group | per shard/partition key | FIFO topics per group | no | per queue |
| Retention | up to 14 days | 24 h – 365 days | none (archive for FIFO, up to 365 d) | archive optional | until consumed |
| Max message | 1 MiB (2 GB via S3) | 10 MiB | 256 KiB default, 1 MiB max (2 GB via S3) | 256 KB **(verify)** | broker limit |
| Scaling | automatic | shards or on-demand | automatic | automatic | instance size |
| Best for | work queues, buffering | real-time analytics, replay | notifications, fan-out | SaaS/AWS event routing | lift-and-shift JMS/AMQP apps |
- SQS vs KDS: SQS deletes after processing and scales without shards; KDS keeps data for many readers and allows replay.
- SQS vs Amazon MQ: SQS is serverless with a proprietary API; MQ speaks JMS/AMQP/MQTT/STOMP for existing apps.

## Scenarios: "If X → Y, because Z"
- If a slow consumer must not slow down the producer → put SQS between them, because the queue buffers messages until consumers catch up.
- If the same order is charged twice by a worker → make processing idempotent or use FIFO with dedupe IDs, because standard queues deliver at least once.
- If messages for one customer must be processed in order but customers in parallel → FIFO queue with group ID = customer ID, because order is per group.
- If a FIFO queue is slow and one group has most traffic → spread across more group IDs, because one group is processed one batch at a time.
- If FIFO throughput is capped near 300 messages/s → batch 10 per call and enable high-throughput mode, because limits are per API request.
- If high-throughput FIFO still throttles → use more distinct group IDs, because hot groups hash to few partitions.
- If a producer retries after a network timeout and FIFO must not duplicate → reuse the same dedupe ID, because duplicates within 5 minutes are dropped.
- If two different events with the same body get lost on FIFO → send explicit dedupe IDs or add a unique field, because content-based dedupe hashes only the body.
- If a job takes 20 minutes and messages are processed twice → raise the visibility timeout or heartbeat with `ChangeMessageVisibility`, because the message reappeared at 30 seconds.
- If a job may take 15 hours → use Step Functions or split it, because visibility cannot exceed 12 hours from first receive.
- If consumers get many empty responses and cost is high → long polling with 20 seconds wait, because it waits for messages and queries all servers.
- If a message must be processed 10 minutes after it is sent → message timer or delay queue (up to 15 min), because it hides the message on arrival.
- If a reminder must fire in 3 days → EventBridge Scheduler, because SQS delay maxes at 15 minutes.
- If messages are lost after a long outage → raise retention up to 14 days, because SQS deletes messages after the retention period.
- If a 5 MB payload must go through SQS → Extended Client Library with S3, because SQS messages max out at 1 MiB.
- If one bad message keeps failing and blocks workers → DLQ with sensible `maxReceiveCount`, because it isolates poison messages.
- If DLQ messages disappear sooner than expected (standard) → set DLQ retention longer than the source, because the original enqueue time is kept.
- If messages in the DLQ are fixed and must be reprocessed → DLQ redrive to the source queue, because it moves them back as new messages.
- If only queues of team A may use a DLQ → redrive allow policy `byQueue`, because it limits source queues (up to 10).
- If FIFO order must never break, even on failures → do not attach a DLQ, because moving a message out breaks the sequence.
- If Lambda reprocesses whole batches after one bad record → `ReportBatchItemFailures`, because only failed IDs return to the queue.
- If good messages land in the DLQ during a traffic spike → raise `maxReceiveCount` (≥ 5) and visibility (≥ 6x timeout), because throttles count as receives.
- If one queue's Lambda starves other functions → ESM maximum concurrency, because it caps concurrent invokes per queue.
- If Lambda on a FIFO queue never scales past 6 → you have 6 active groups, because FIFO concurrency is capped by group count.
- If Lambda needs more than 1,250 concurrent invokes from one queue → provisioned mode, because default scaling caps at 1,250.
- If an S3 upload must trigger ordered processing in a FIFO queue → S3 → EventBridge → SQS FIFO, because S3 notifications cannot target FIFO queues.
- If a multi-tenant standard queue has one tenant flooding it → send tenant ID as `MessageGroupId` (fair queues), because SQS then favors quiet tenants.
- If many short-lived reply queues are needed → Temporary Queue Client virtual queues, because they avoid creating real queues.
- If several apps each need every message → SNS fan-out to one queue per app, because one SQS message goes to one consumer.
- If you need urgent and normal jobs → two queues and poll the urgent one first, because SQS has no priority.

Verified from AWS docs on 2026-11-03 (SQS message/standard/FIFO quotas, standard queues, FIFO delivery logic, exactly-once processing, high-throughput FIFO and enabling it, fair queues, visibility timeout, short/long polling, delay queues, DLQs, DLQ redrive, temporary queues, PurgeQueue and SendMessage API references, SQS CloudWatch metrics, Lambda SQS configure/scaling/error-handling pages, S3 event destinations).
Unconfirmed (verify): 60-second wait before reusing a deleted queue name; Lambda ESM filter deleting non-matching SQS messages; EventBridge max event size in the comparison table; the older 20,000 FIFO in-flight figure in exam material (current docs say 120,000).

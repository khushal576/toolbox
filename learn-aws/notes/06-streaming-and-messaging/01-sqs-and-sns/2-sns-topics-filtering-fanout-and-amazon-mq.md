# SQS and SNS – 2. SNS topics, filtering, fan-out, delivery retries, and Amazon MQ

Short notes. Each point is a fact you can be asked about.

## A. What SNS is (and is not)
- Amazon SNS (Simple Notification Service) = fully managed publish/subscribe (pub/sub) service.
- A publisher sends one message to a topic. SNS pushes a copy to every subscription on that topic.
- Push model: subscribers do not poll. SNS calls the endpoint (or puts the message in the SQS queue).
- No storage for standard topics: if a delivery fails after all retries and there is no DLQ, the message is lost.
- No replay for standard topics. FIFO topics can archive and replay.
- Two kinds of use: application-to-application (A2A: SQS, Lambda, HTTP/S, Firehose) and application-to-person (A2P: SMS, email, mobile push).
- Regional service. A topic lives in one Region, but it can deliver to SQS queues and Lambda functions in other Regions (standard topics).
- Pick SNS for: fan-out to many consumers, alerts and notifications, decoupled event broadcast, CloudWatch alarm notifications.
- Avoid SNS for: buffering work for slow consumers (add SQS behind it), replay of standard events (KDS), complex content routing across many AWS targets (EventBridge often fits better).
- SNS + SQS together = durable fan-out: SNS broadcasts, each SQS queue stores its own copy.
- DEA-C01 angle: SNS is the standard way to send pipeline alerts (Glue job failed, Step Functions failed, CloudWatch alarm).

## B. Standard vs FIFO topics
| | Standard topic | FIFO topic |
|---|---|---|
| Delivery | at-least-once, duplicates possible | exactly-once (dedupe in 5-minute window) to SQS FIFO |
| Ordering | best-effort, no guarantee | strict within a message group |
| Subscribers | SQS, Lambda, HTTP/S, email, email-json, SMS, mobile push, Firehose | SQS only (FIFO or standard queues) |
| Subscriptions per topic | 12,500,000 | 100 |
| Topics per account | 100,000 | 1,000 |
| Archive and replay | no | yes (1–365 days) |
| Name | any | must end in `.fifo` |
| Publish throughput | Region quota (for example 30,000 msg/s in us-east-1) | 300 msg/s per message group; 3,000 msg/s or 20 MB/s per topic in topic scope |
- FIFO topics need `MessageGroupId` on publish, plus a dedupe ID or content-based dedupe (same rules as SQS FIFO).
- FIFO topic `FifoThroughputScope`: `Topic` (3,000 msg/s or 20 MB/s per topic) or `MessageGroup` (higher, 300 msg/s per group).
- FIFO topics cannot deliver to email, SMS, mobile push or HTTP/S. Subscribing them returns an error.
- To get FIFO messages into Lambda: SNS FIFO → SQS FIFO queue → Lambda ESM.
- A standard SQS queue can subscribe to a FIFO topic: cheaper, but it loses strict ordering and exactly-once.
- You cannot convert a topic between standard and FIFO after creation.
- S3 event notifications support standard SNS topics only, not FIFO topics.

## C. Publishing messages
- `Publish` sends one message. `PublishBatch` sends up to 10 messages in one call.
- Default max message size: 256 KiB (262,144 bytes), body plus attributes.
- Newer option: set the topic `MaximumMessageSize` attribute up to 1 MiB (1,048,576 bytes). Range 1,024–1,048,576 bytes.
- Topics above 256 KiB only support Firehose, SQS and Lambda subscriptions, and at most 100 subscriptions.
- If the message is bigger than the topic's `MaximumMessageSize`, publish fails with `InvalidParameter`.
- For SQS subscribers, the topic's `MaximumMessageSize` is the effective limit; the queue's own `MaximumMessageSize` does not apply to SNS deliveries.
- Firehose records max 1,000 KiB including SNS metadata, so keep large-message topics with Firehose below 1 MiB.
- Over 1 MiB: SNS Extended Client Library (Java, Python) stores the payload in S3 and publishes a pointer. Up to 2 GB. Works with standard and FIFO topics.
- Message attributes: name, type (`String`, `String.Array`, `Number`, `Binary`), value. Used mainly for filtering.
- Message header max 16 KiB.
- `Subject` field is used for email subjects; `MessageStructure=json` lets you send different text per protocol.
- Publish throughput quota is per account per Region (Publish + PublishBatch combined): 30,000 msg/s us-east-1; 9,000 us-west-2/eu-west-1; 1,500 in several big Regions; 300 elsewhere (soft limits).
- Publish to a missing or deleted topic fails; SNS does not create topics on the fly.

## D. Subscriptions and protocols
- Protocols: `sqs`, `lambda`, `http`, `https`, `email`, `email-json`, `sms`, `application` (mobile push), `firehose`.
- HTTP/S endpoints, email addresses, and resources in other AWS accounts must confirm the subscription before they get messages.
- Confirmation: SNS sends a message with a token/`SubscribeURL`; the endpoint visits the URL or the owner calls `ConfirmSubscription`.
- Unconfirmed subscriptions stay "pending confirmation". Pending subscriptions quota: 5,000 per account.
- Confirmation tokens are short-lived (about 3 days) **(verify)**.
- `AuthenticateOnUnsubscribe=true` on confirm: only the topic owner or subscription owner can unsubscribe (stops anyone with the email link from unsubscribing).
- Firehose subscription needs a subscription role ARN (IAM role SNS uses to write to Firehose).
- A subscription owner can attach up to 5 Firehose streams to one topic.
- Email delivery is limited to 10 messages per second per email subscription (hard limit).
- SMS: default account spend limit is 1.00 USD per month; raise it before production. SMS is billed through AWS End User Messaging.
- Lambda subscribers are invoked asynchronously (Lambda then has its own retries and on-failure destinations).
- SNS to Lambda in another Region or account is allowed for standard topics (needs Lambda resource policy).
- Subscribers can be added and removed at any time without changing the publisher. This is the main decoupling benefit.

## E. Fan-out pattern (SNS → many SQS queues)
- Publish once to SNS; each subscribed SQS queue gets its own copy.
- Each queue has its own consumers, retry speed, DLQ and backlog. A slow consumer does not affect others.
- Classic data use: S3 event → SNS topic → queue A (ETL loader), queue B (indexer), queue C (audit). One S3 bucket can send a given event type/prefix to only one destination, so fan-out through SNS.
- Add a new pipeline later by adding a new queue subscription. No change to producers.
- The SQS queue access policy must allow `sns.amazonaws.com` to `sqs:SendMessage`, with `aws:SourceArn` = the topic ARN.
- Encrypted queue: the KMS key must be a customer managed key whose key policy allows `sns.amazonaws.com` `kms:GenerateDataKey` and `kms:Decrypt`. The AWS managed `aws/sqs` key will not work.
- Cross-account fan-out: queue policy allows the topic ARN; the subscription must be confirmed (or created by the queue owner).
- Cross-Region: standard topic can deliver to an SQS queue in another Region.
- Without raw delivery, each SQS message body is an SNS JSON envelope; the real payload is in the `Message` field.
- Use filter policies so each queue receives only the events it needs, instead of every consumer discarding most messages.
- SNS FIFO + SQS FIFO fan-out keeps per-group order in every queue.
- Alternative fan-out options: EventBridge rules (content routing, many targets), KDS with multiple consumers (replay, high volume).

## F. Message filtering
- Filter policy is a JSON document on a subscription (not on the topic). Only matching messages are delivered.
- No filter policy = the subscription gets every message.
- Filter policy scope: `MessageAttributes` (default) or `MessageBody` (payload-based filtering).
- Attribute-based: matches message attributes of type String, String.Array and Number. Binary attributes are ignored. No nested policies.
- Payload-based: message body must be valid JSON; nested policies are allowed.
- Logic: AND across different keys; OR across values inside one key's array; `$or` operator for OR across keys.
- String operators: exact match, `anything-but` (also with prefix, suffix, wildcard), `prefix`, `suffix`, `equals-ignore-case`, `wildcard`, `cidr` (IP address/subnet).
- Numeric operators: exact, `anything-but`, ranges (`"numeric": [">", 0, "<=", 100]`).
- Key matching: `{"exists": true}` / `{"exists": false}` on an attribute or property.
- String matching is case-sensitive unless you use `equals-ignore-case`.
- Numeric values: −1 billion to +1 billion, 5 decimal digits precision.
- Max 5 keys per policy (payload-based: only leaf keys count).
- Max 150 total value combinations (multiply the number of values of each key; payload-based also multiplies nesting depth).
- Max policy size 256 KB. Default 200 filter policies per topic and 10,000 per account (soft).
- Wildcards: max 3 per pattern; total wildcard complexity max 100 points.
- New or changed filter policies take up to 15 minutes to take effect (eventual consistency).
- Messages with no attributes are dropped by an attribute-based policy (metric `NumberOfNotificationsFilteredOut-NoMessageAttributes`).
- Filtered-out messages are not failures; they appear in `NumberOfNotificationsFilteredOut`, not `NumberOfNotificationsFailed`.
- Cost: attribute-based filtering is free; payload-based filtering is billed by payload data scanned.
- Attribute special characters (`"` and `\`) must be double-escaped or the policy will not match.
- FIFO topics support the same filtering as standard topics.

## G. Raw message delivery
- Default: SNS wraps the message in a JSON envelope (`Type`, `MessageId`, `TopicArn`, `Subject`, `Message`, `Timestamp`, signature fields, `UnsubscribeURL`).
- Raw message delivery sends only the original body. Supported for SQS, HTTP/S and Firehose subscriptions.
- Why: consumers (or Firehose to S3) get clean payloads without parsing the envelope.
- SQS with raw delivery: message attributes are passed as SQS message attributes, max 10. More than 10 → message discarded as a client-side error.
- HTTP/S with raw delivery: header `x-amz-sns-rawdelivery: true` is added; message attributes are not sent.
- Firehose with raw delivery: only the body is delivered; attributes are not sent.
- Common exam pattern: SNS → Firehose (raw) → S3 for clean archived records.

## H. Delivery retries (delivery policies)
- SNS retries only on server-side errors (endpoint unavailable, 5xx, 429). Client-side errors (deleted endpoint, policy denies SNS) are not retried.
- AWS managed endpoints (SQS, Lambda; Firehose for non-throttle errors): 3 immediate retries, 2 at 1 s, 10 with backoff 1–20 s, then 100,000 at 20 s. Total 100,015 attempts over 23 days.
- Customer managed endpoints (email/SMTP, SMS, mobile push): 0 immediate, 2 at 10 s, 10 with backoff 10–600 s, 38 at 600 s. Total 50 attempts over about 6 hours.
- Firehose throttling errors use the customer managed (50 attempts / 6 hours) policy.
- Only HTTP/S delivery policies can be customized. Others are fixed by SNS.
- HTTP/S policy phases: no-delay, pre-backoff (min delay), backoff (function), post-backoff (max delay).
- HTTP/S defaults: `numRetries` 3, `minDelayTarget` 20 s, `maxDelayTarget` 20 s, `backoffFunction` linear.
- HTTP/S `numRetries` max 100. Total retry time max 3,600 seconds (hard limit).
- Backoff functions: arithmetic, exponential, geometric, linear. SNS adds jitter.
- `throttlePolicy.maxReceivesPerSecond`: average deliveries per second per subscription to protect your server. Self-throttled messages do not use up retries.
- `requestPolicy.headerContentType`: default `text/plain; charset=UTF-8`; can be `application/json`.
- Set the HTTP/S policy at topic level (all HTTP/S subscriptions) or subscription level (one endpoint).
- After retries are exhausted, SNS discards the message unless the subscription has a DLQ.

## I. Subscription dead-letter queues
- An SNS DLQ is an SQS queue attached to a subscription (redrive policy with `deadLetterTargetArn`), not to the topic.
- Why per subscription: delivery happens per subscription, so you see which endpoint failed.
- Messages go to the DLQ on client-side errors (immediately) or after server-side retries are exhausted.
- DLQ queue must be in the same account and Region as the subscription.
- FIFO topic subscriptions use FIFO queues as DLQs; standard subscriptions use standard queues.
- Encrypted DLQ needs a customer managed KMS key that allows the SNS service principal.
- The DLQ queue policy must allow SNS to send to it.
- AWS recommends 14-day retention on SNS DLQs.
- Metrics: `NumberOfNotificationsRedrivenToDlq`, `NumberOfNotificationsFailedToRedriveToDlq`.
- Reprocess by draining the DLQ with Lambda or custom consumer code.

## J. FIFO topic archiving and replay
- Archive policy on a FIFO topic: SNS keeps a copy of every published message for 1 to 365 days (`MessageRetentionPeriod`).
- Available only for application-to-application FIFO topics, not standard topics.
- The topic owner sets the archive; a subscriber sets a replay policy on its subscription with a start (and optional end) time.
- Replay delivers archived messages to that subscription only, for example to rebuild a new or broken consumer.
- `BeginningArchiveTime` (topic attribute) = oldest time you can replay from.
- You cannot delete a topic with an active archive policy. Disabling the archive deletes all archived messages.
- Encrypted topics: the KMS key policy must let `sns.amazonaws.com` decrypt, or replay fails.
- Cost: archive priced by data volume and storage time (1-day minimum); replay billed at FIFO request and payload rates.
- Archive metrics: `ApproximateNumberOfMessagesArchived`, `ApproximateNumberOfBytesArchived` (60-minute resolution).
- Standard topic needing history → subscribe Firehose and land messages in S3, or use EventBridge archive.

## K. Message data protection (closed to new customers)
- SNS message data protection let a topic owner audit, mask/de-identify, or deny PII (inbound or outbound) using managed data identifiers.
- Not available to new customers from April 30, 2026. Existing users can keep it; no new enhancements.
- AWS recommended alternative: inbound SNS topic → Lambda that uses Amazon Bedrock Guardrails to log, block or redact → outbound SNS topic.
- Exam questions written earlier may still name it as the PII masking answer for SNS. Know both the old feature and the change.

## L. SNS → Firehose for archiving and analytics
- Subscribe a Firehose stream to a standard topic to store every message in S3, Redshift, OpenSearch, Splunk or partner tools.
- Use raw message delivery so S3 gets the payload, not the envelope.
- Firehose has its own throughput quota; if publish rate is higher, deliveries back up and latency grows. Raise Firehose quotas.
- Delivery status logging supports Firehose endpoints.
- FIFO topics cannot use Firehose subscriptions; route through SQS or use archive/replay.

## M. Delivery status logging
- Logs success/failure of deliveries to CloudWatch Logs for SQS, Lambda, HTTP/S, Firehose and platform application (mobile push) endpoints.
- Configure per protocol on the topic: IAM role for success, role for failure, and success sample rate (0–100%).
- Shows endpoint response and dwell time (publish to hand-off).
- Use it to debug "message published but never arrived" for supported protocols.

## N. Amazon MQ (short)
- Amazon MQ = managed message broker for Apache ActiveMQ Classic and RabbitMQ.
- Pick it for lift-and-shift: existing apps that use JMS, AMQP, MQTT, STOMP, OpenWire or WebSocket and you do not want to rewrite them.
- ActiveMQ protocols: OpenWire (JMS), AMQP 1.0, STOMP, MQTT, WebSocket **(verify full list)**. RabbitMQ: AMQP 0-9-1.
- Not serverless: you choose broker instance types (for example `mq.m5`, `mq.m7g`) and pay per broker-hour plus storage.
- Runs in your VPC; can be private or publicly accessible. TLS for connections; encryption at rest with KMS.
- ActiveMQ deployment: single-instance (one AZ) or active/standby (two AZs, shared EFS storage, automatic failover).
- Active/standby clients use the ActiveMQ failover transport URL with both endpoints (`-1` and `-2`).
- ActiveMQ can also form a network of brokers for scale **(verify)**, and supports cross-Region data replication (CRDR) with manual failover.
- ActiveMQ storage: EFS (default, multi-AZ durable, lower throughput) or EBS (single AZ, higher throughput, only `mq.m5`, not with active/standby). Storage type cannot be changed later.
- Approximate per-broker enqueue rates (1 KB messages): in-memory 5,000/s (non-persistent), EBS 500/s, EFS 80/s.
- RabbitMQ deployment: single-instance (one AZ, behind an NLB) or cluster (3 nodes across 3 AZs behind an NLB).
- RabbitMQ storage is EBS. Cluster mode replicates queues across nodes; quorum queues are supported and help with poison messages.
- RabbitMQ 4.x (4.2, 4.3) runs only on `mq.m7g`; 3.13 on `mq.t3`, `mq.m5`, `mq.m7g`. RabbitMQ streams are not supported.
- Maintenance windows reboot brokers; clients must reconnect automatically.
- Lambda can consume from Amazon MQ with an event source mapping.
- Avoid Amazon MQ for new cloud-native designs: SQS/SNS scale automatically with no brokers to size or patch.
- Amazon MQ vs MSK: MQ is a message broker for JMS/AMQP apps; MSK is Kafka for log-based streaming.

## Scenarios: "If X → Y, because Z"
- If one event must reach three independent pipelines → SNS topic with three SQS queue subscriptions, because each queue keeps its own copy and pace.
- If an S3 bucket must trigger two different processors for the same prefix → S3 → SNS → two SQS queues, because overlapping S3 notifications to two destinations are not allowed.
- If a consumer only needs `order_type = refund` events → subscription filter policy, because SNS then drops other messages for that subscription.
- If the filter must look inside the JSON body → set `FilterPolicyScope` to `MessageBody`, because attribute filtering only sees message attributes.
- If a new filter policy seems ignored → wait up to 15 minutes, because policy changes are eventually consistent.
- If messages without attributes never reach a filtered subscription → add attributes or use payload filtering, because attribute policies reject messages with no attributes.
- If the SQS consumer has to parse an SNS JSON wrapper → enable raw message delivery, because it sends only the body.
- If SNS to SQS with raw delivery drops messages with 12 attributes → reduce to 10 attributes or disable raw delivery, because raw delivery to SQS allows max 10.
- If a webhook server is overloaded by SNS → HTTP/S delivery policy with `maxReceivesPerSecond` and backoff, because only HTTP/S policies are customizable.
- If failed deliveries must not be lost → subscription DLQ (SQS), because SNS discards messages after retries otherwise.
- If a Lambda subscriber was deleted and messages vanish → client-side error, no retries; attach a DLQ and fix the endpoint, because SNS does not retry client errors.
- If price updates must reach two apps in strict order per product → SNS FIFO topic + SQS FIFO queues, group ID = product ID, because FIFO keeps order per group.
- If a FIFO topic must also feed a cheap analytics queue → subscribe a standard SQS queue, because FIFO topics can deliver to standard queues.
- If a new consumer must reprocess the last 30 days of FIFO topic messages → archive policy + replay policy, because FIFO topics can store and replay up to 365 days.
- If every SNS message must be kept in S3 for audit → Firehose subscription with raw delivery, because SNS standard topics do not store messages.
- If a 700 KB message must go through SNS to SQS → set topic `MaximumMessageSize` up to 1 MiB, because the default is 256 KiB.
- If a 50 MB payload must be broadcast → SNS Extended Client Library with S3, because SNS caps messages at 1 MiB.
- If a team needs Lambda behind a FIFO topic → SNS FIFO → SQS FIFO → Lambda, because FIFO topics only deliver to SQS.
- If a Glue job failure must email the on-call team → EventBridge rule or CloudWatch alarm → SNS topic with email subscription, because SNS handles A2P notifications.
- If email subscribers never get alerts → check pending confirmation, because email subscriptions must be confirmed.
- If SMS alerts stop mid-month → raise the SMS spend limit, because the default is 1 USD per month.
- If PII must be masked before subscribers see it (new account in 2026) → Lambda + Bedrock Guardrails between two topics, because SNS data protection is closed to new customers.
- If an on-premises app uses JMS with ActiveMQ and must move fast → Amazon MQ for ActiveMQ, because it keeps the same protocol and API.
- If an Amazon MQ ActiveMQ broker must survive an AZ failure → active/standby with EFS, because single-instance runs in one AZ.
- If an ActiveMQ broker needs maximum throughput and can accept single-AZ storage → EBS storage on `mq.m5`, because EBS is faster than EFS.
- If a new serverless pipeline needs a queue → SQS, not Amazon MQ, because MQ needs broker sizing and patching.

Verified from AWS docs on 2026-11-03 (SNS quotas page, FIFO topics and FIFO delivery, archiving for topic owners, delivery retries, subscription DLQs, filter policies and constraints, string matching operators, raw message delivery, large message payloads, delivery status logging, Firehose subscriber, creating subscriptions, ConfirmSubscription API, data protection availability change, Amazon MQ welcome/storage/ActiveMQ and RabbitMQ deployment/RabbitMQ versions).
Unconfirmed (verify): confirmation token lifetime (about 3 days); full ActiveMQ protocol list; ActiveMQ network of brokers details.

# Lambda – 2. Event sources, data pipelines and storage

Short notes. Each point is a fact you can be asked about.

## A. Push vs poll: how sources invoke Lambda
- **Push (the service invokes Lambda)**:
  - The source needs permission in the function's **resource-based policy** (`lambda:InvokeFunction` for `s3.amazonaws.com`, `sns.amazonaws.com`…).
  - Async push: S3, SNS, EventBridge, CloudWatch Logs, SES, IoT.
  - Sync push: API Gateway, ALB, function URLs, Cognito, Step Functions.
- **Poll (event source mapping, ESM)**:
  - Lambda runs a poller for you: SQS, Kinesis Data Streams, DynamoDB Streams, Amazon MSK, self-managed Kafka, Amazon MQ, DocumentDB.
  - The function's **execution role** needs permission to **read** the source (for example `sqs:ReceiveMessage`, `kinesis:GetRecords`).
- Every ESM invokes the function **synchronously with a batch**. Every ESM is **at-least-once**, so duplicates can happen. Write **idempotent** code.
- ESM **batching**: Lambda collects records until one of these happens:
  - the **batch size** is reached,
  - the **batching window** (up to **5 minutes**) expires,
  - or the **6 MB payload** limit is hit.
- **Event filtering** on an ESM: JSON filter patterns drop records **before** the function runs. You don't pay for filtered-out invokes.
  - For SQS, filtered-out messages are **deleted** from the queue.
  - For streams, filtered-out records are skipped (the checkpoint moves on).
  - Up to 5 filters per ESM by default (verify; can be raised).
- ESMs can be **enabled or disabled** to pause processing without deleting the setup.
- **Provisioned mode** for ESMs (SQS, Kafka; Kinesis/DynamoDB verify):
  - Dedicated **event pollers** with a minimum and maximum count. Faster scaling and higher throughput. Extra cost (per event poller unit hour).
- Starting a new ESM can take several minutes. With `LATEST` you can **miss records** during create/update. Use `TRIM_HORIZON` (or `AT_TIMESTAMP`) when nothing may be lost.

## B. Kinesis Data Streams → Lambda
- Lambda polls **each shard**. By default it processes **one batch per shard at a time, in order**.
- Polling modes:
  - **Standard iterator**: shares the shard's 2 MB/s read limit with other consumers; polled about once per second.
  - **Enhanced fan-out (EFO) consumer**: dedicated 2 MB/s per shard per consumer, pushed over HTTP/2. Lower latency. Extra Kinesis cost. Use it when many consumers read the same stream.
- Settings (with defaults):
  - **BatchSize**: default **100**, max **10,000**.
  - **MaximumBatchingWindowInSeconds**: 0–300 s.
  - **StartingPosition**: `TRIM_HORIZON` (oldest), `LATEST` (new only), `AT_TIMESTAMP`.
  - **ParallelizationFactor**: **1–10** concurrent batches **per shard**. Order is still kept **per partition key**. Use it when **IteratorAge** grows without adding shards.
  - **MaximumRetryAttempts**: default **-1 (infinite)**, up to 10,000.
  - **MaximumRecordAgeInSeconds**: default **-1 (infinite, until the stream retention expires)**, up to 604,800 (7 days).
  - **BisectBatchOnFunctionError**: on error, split the batch in two and retry each half. Helps isolate a **poison record**.
  - **On-failure destination**: SQS, SNS or S3 gets **metadata** about discarded records (shard, sequence numbers). It is **not the data** for SQS/SNS. Read the data back from the stream before it expires.
  - **FunctionResponseTypes = ReportBatchItemFailures**: the function returns the sequence number of the first failed record. Lambda checkpoints before it and retries from there.
  - **TumblingWindowInSeconds**: 0–**900** s. Stateful aggregation per shard over fixed windows. Lambda passes state between invocations in the window.
- **Concurrency for Kinesis** = shards × parallelization factor. Example: 100 shards × factor 2 = 200 concurrent invokes.
- **Default error trap**: with the default infinite retries, one bad record **blocks the shard** until it expires (up to the stream retention, 24 h default, up to 365 days). Downstream lag grows. Always set **max retries / max record age + bisect + on-failure destination**, or use partial batch response.
- Key metric: **`IteratorAge`** = age of the last record read. Rising IteratorAge = falling behind (slow function, errors blocking, throttling, too few shards, factor too low).
- Throughput fixes:
  - Add shards (more parallel batches).
  - Raise ParallelizationFactor.
  - Raise batch size or batching window (more records per invoke).
  - Use EFO when there are many consumers.
  - Speed up the function (memory).
- Ordering: guaranteed **per shard** (per partition key with parallelization). Not across shards.
- Kinesis record aggregation (KPL): Lambda de-aggregates. With a parallelization factor and no EFO, all sub-records must share the partition key, or the order guarantee is lost.

## C. DynamoDB Streams → Lambda
- Same model as Kinesis: shards, batch per shard, in order, retries until success or expiry.
- Lambda polls shards about **4 times per second**.
- Stream records are kept **24 hours**. Records older than that are gone.
- **StreamViewType** (set on the table stream): `KEYS_ONLY`, `NEW_IMAGE`, `OLD_IMAGE`, `NEW_AND_OLD_IMAGES`.
- The same settings as Kinesis: batch size, batching window, ParallelizationFactor 1–10, bisect, max retries, max record age, on-failure destination, ReportBatchItemFailures, tumbling windows.
- Order is guaranteed **per item** (partition key + sort key).
- **At most 2 Lambda functions** should read the same shard of a single-Region table (more → throttling). For **global tables, use 1**. For more consumers, fan out: one Lambda → SNS/EventBridge, or use **Kinesis Data Streams for DynamoDB** instead.
- Use cases: change data capture → S3/OpenSearch, keep aggregates or materialized views up to date, send notifications, replicate to other stores, audit trails.
- **Event filtering** on DynamoDB streams is common: for example, process only `INSERT` events, or only items where `status = "SHIPPED"`.
- Writing back to the **same table** from the stream handler can create a loop. Lambda's recursion detection does not cover DynamoDB. Guard it with conditions or filters.

## D. SQS → Lambda
- Lambda **long-polls** the queue, receives a batch, and invokes the function. On **success** Lambda **deletes** the batch. On error the messages become visible again after the **visibility timeout**.
- **BatchSize**: default **10**. Max **10,000** for standard queues (needs a batching window above 0 for over 10), max **10** for **FIFO**.
- **MaximumBatchingWindowInSeconds**: 0–300 s. **Not supported for FIFO**. With low traffic Lambda may wait up to 20 s (long polling) even with a smaller window.
- **Visibility timeout rule**: set the queue's visibility timeout to at least **6 × the function timeout** (plus the batching window). Otherwise messages reappear while still being processed and run twice (verify exact wording in current docs).
- **Partial batch response** (`ReportBatchItemFailures`): return only the failed message IDs. Only those return to the queue, and successful ones are deleted. Without it, **one failure retries the whole batch**.
- **Dead-letter queue**: set the **redrive policy on the source SQS queue** (`maxReceiveCount`), **not on the Lambda function**. The function-level DLQ is only for async invokes.
- **Scaling (standard queues, default mode)**:
  - Starts with **5 concurrent batches**, then adds up to **300 more concurrent invokes per minute**.
  - Max **1,250 concurrent invokes per ESM**.
  - Drops back as the queue empties.
- **Maximum concurrency** (ScalingConfig): **2–1,000** per SQS ESM. It caps how many concurrent invokes that queue can drive. Use it to protect a downstream DB or to share concurrency between several queues.
- Max concurrency vs reserved concurrency: set the function's **reserved concurrency ≥ the sum of max concurrency** of all its SQS mappings. Otherwise Lambda throttles and messages go back to the queue (and may hit the DLQ).
- **Provisioned mode for SQS**:
  - Event pollers from a minimum of **2–200** to a maximum of up to 2,000 (verify; another doc page says 10,000).
  - Each poller handles about **1 MB/s, 10 concurrent invokes, 10 polls/s**.
  - Scales about **3× faster** (up to 1,000 concurrent invokes per minute), up to **100,000** concurrent invokes.
  - Cannot be combined with maximum concurrency.
- **FIFO queues**: order is kept **per message group ID**. Concurrency is capped by the **number of active message groups** (or max concurrency, whichever is lower). A failure in a group blocks that group until it succeeds or goes to the DLQ.
- SQS and Lambda must be in the **same Region**. They can be in **different accounts** (queue policy plus execution role).
- Throttled SQS invokes **do not lose messages**. They return to the queue after the visibility timeout. They can end up in the DLQ if `maxReceiveCount` is too low. Set `maxReceiveCount` at least **5** when throttling is possible (verify guidance).
- SQS is the classic **buffer** between a bursty producer and a fragile consumer (a DB with limited connections). It smooths load.

## E. Kafka (Amazon MSK and self-managed) → Lambda
- An ESM reads one or more topics. One consumer per **partition**, so concurrency is up to the number of partitions (verify scaling details).
- Order is kept **per partition**.
- Settings: batch size, batching window, starting position (`TRIM_HORIZON`, `LATEST`, `AT_TIMESTAMP` for MSK; verify), consumer group ID, filtering.
- Error handling: retries, max record age, bisect (verify), **on-failure destination** (SQS, SNS, S3, or a Kafka topic).
- **Provisioned mode** (event pollers) for high and steady throughput.
- Networking: Lambda must reach the brokers. MSK in a VPC needs the cluster's subnets/SG set up for the ESM, plus VPC endpoints or NAT for Lambda/STS (verify current requirement).
- Auth: IAM, SASL/SCRAM (Secrets Manager), mTLS. For self-managed Kafka: SASL/SCRAM, mTLS, or a VPC.
- **Schema registry** integration (Glue Schema Registry, Confluent) to decode Avro/Protobuf records before invoking (verify availability).

## F. Push sources used in data pipelines
- **S3 event notifications** (async):
  - Events such as `s3:ObjectCreated:*` and `s3:ObjectRemoved:*`, with **prefix and suffix filters** (for example `raw/` and `.csv`).
  - Delivery is at-least-once, and **order is not guaranteed**.
  - **Recursion trap**: a function triggered by `ObjectCreated` that writes **back to the same bucket/prefix** triggers itself again and again. Fix: write to a different bucket or prefix, filter on prefix/suffix, and rely on **recursive loop detection** (it covers S3).
  - Alternatively send S3 events to **EventBridge** for richer filtering, multiple targets and replay/archive.
  - For very high object rates, buffer with **S3 → SQS → Lambda** to control concurrency and retries.
- **EventBridge rules** (async):
  - Route AWS service events (Glue job state change, Step Functions status, EC2 state, S3 via EventBridge) and custom events to Lambda.
  - Content filtering. Archive and **replay**.
- **EventBridge Scheduler / scheduled rules**: cron or rate expressions to run a Lambda (for example, every hour start an Athena partition repair or a data export). Scheduler supports time zones, one-time schedules and flexible windows.
- **SNS** (async): fan-out. One message → many subscribers (several Lambdas, SQS queues, HTTP). The **SNS → SQS → Lambda** fan-out gives durable buffering per consumer.
- **API Gateway / ALB / function URL** (sync): Lambda-backed **data APIs**. API Gateway adds throttling, API keys, usage plans, validation, caching and authorizers.
- **CloudWatch Logs subscription filters** → Lambda: process or forward log events in near real time.

## G. Lambda inside data pipelines
- **Step Functions**: orchestrate Lambda with Glue, Athena, EMR, Batch, ECS and SNS steps. Built-in retries/catch, **Map state** for parallel fan-out over many S3 objects (Distributed Map for millions of items). Breaks long jobs into many sub-15-minute Lambda calls.
- **Amazon Data Firehose data transformation**:
  - Firehose calls a Lambda on each buffered batch. The function returns each record with `recordId`, `result` (`Ok`, `Dropped`, `ProcessingFailed`) and the transformed `data`.
  - Used for cleaning, enrichment, and JSON fixes before Firehose converts to **Parquet/ORC** and writes to S3.
  - Firehose can retry the Lambda. Failed records go to an S3 error prefix (verify buffer size and timeout limits).
- **Triggering Glue**: Lambda on an S3 event calls `glue:StartJobRun` or `StartCrawler`. Alternatives: Glue workflows with EventBridge triggers, or Step Functions.
- **Running Athena**: Lambda calls `StartQueryExecution` (async). Poll `GetQueryExecution` or let Step Functions wait for completion. Useful for scheduled `MSCK REPAIR` / `ALTER TABLE ADD PARTITION`, or small CTAS jobs.
- **Redshift Data API**: Lambda runs SQL on Redshift with no JDBC driver, no connection management and no VPC needed (IAM or Secrets Manager auth). Async with statement IDs.
- **MWAA (Airflow)**: Airflow tasks invoke Lambda (LambdaInvokeFunctionOperator). Lambda can also trigger DAGs through the MWAA REST API / CLI token.
- **Glue Data Catalog / Lake Formation**: Lambda can update partitions with the Glue API after writing files, so new data is queryable at once.
- **Kinesis/MSK → Lambda → S3/DynamoDB/OpenSearch**: a classic light real-time ETL path.
- **Fan-out / fan-in**:
  - Fan-out with SNS topics, EventBridge, Step Functions Map, or one Lambda writing many SQS messages.
  - Fan-in by writing results to DynamoDB/S3 and using a final aggregation step (Step Functions waits for all branches).
- **Replayability**:
  - Kinesis/MSK can replay with `AT_TIMESTAMP` / `TRIM_HORIZON` or a new ESM.
  - EventBridge **archives** can replay events.
  - SQS DLQ **redrive** sends messages back to the source queue.
  - Keep raw data in S3 so you can reprocess.

## H. Format conversion and transforms in Lambda
- Lambda can convert **CSV/JSON → Parquet** for small and medium files with **pandas + pyarrow**.
- The **AWS SDK for pandas** (awswrangler) is published as an **AWS-managed Lambda layer**. It reads/writes S3 Parquet, updates the Glue Catalog and runs Athena/Redshift queries in a few lines.
- Limits to respect: 10 GB memory, 10 GB `/tmp`, 15 minutes, 6 MB sync payload. Stream large files from S3 in chunks or ranges, and avoid loading huge files fully into memory.
- When files are big (many GB), when joins across datasets are needed, or when you have thousands of files per run → use **Glue (Spark)**, **EMR**, or Athena CTAS/`INSERT INTO`, not Lambda.
- Many small Lambda outputs make many **small files**. Compact them later (Glue job, Athena CTAS, Iceberg compaction) for query performance.
- For streaming conversion to Parquet with no code → **Firehose record format conversion** (uses a Glue table schema). A Lambda is only needed for cleanup.

## I. Storage options for Lambda
- **`/tmp` (ephemeral storage)**:
  - 512 MB free, up to **10 GB**. Fast local disk, private to one environment, gone when the environment ends.
  - For scratch files, downloaded models, temporary decompress.
- **Amazon EFS mount**:
  - Shared, persistent POSIX file system mounted at a path under **`/mnt`**.
  - The function must be in a **VPC** with a route to the EFS mount targets, and use an **EFS access point** (sets the POSIX user and root directory).
  - The execution role needs `elasticfilesystem:ClientMount` / `ClientWrite`.
  - Uses: large ML models or libraries over 250 MB, files shared between functions or with EC2/ECS, stateful workloads.
  - Watch EFS throughput mode: bursting credits can run out under high Lambda concurrency. Use **Elastic throughput**.
- **Amazon S3 Files mount**:
  - Mount an **S3 bucket as a file system** with normal file reads and writes on the local mount path (verify setup details: VPC, permissions).
  - A function can use **EFS or S3 Files, not both**.
  - SnapStart is not supported with EFS or S3 Files.
- **S3 through the SDK**: the normal way to read and write data objects. Use `GetObject` byte ranges and multipart uploads for big objects. No VPC needed unless the function is VPC-attached (then use an **S3 gateway endpoint** or NAT).
- **Layers / container images**: read-only code and data shipped with the function (under `/opt`, or in the image).
- **Databases / caches**: DynamoDB (HTTP, no connections), RDS/Aurora (use **RDS Proxy** or the **Data API**), ElastiCache (VPC).
- Exam mapping, "mount storage volumes in Lambda" → **EFS (or S3 Files) mounted via VPC + access point**, and **ephemeral `/tmp` up to 10 GB**.

## Scenarios (if → then, because)
- **If** a Lambda consumer of **Amazon Kinesis Data Streams** falls behind and **IteratorAge** (the age of the last record read) keeps rising, **then** raise the **ParallelizationFactor** (up to **10** batches per shard at once), add **shards**, raise the **batch size**, or give the function more **memory**. **This works because** by default Lambda processes one batch per shard at a time, so throughput depends on shards × parallelization factor, records per invoke and how fast the function runs. Order is still kept per partition key with a higher factor.
- **If** one bad Kinesis record blocks a shard for hours, **then** set **MaximumRetryAttempts** and **MaximumRecordAgeInSeconds**, turn on **BisectBatchOnFunctionError**, add an **on-failure destination**, and use **ReportBatchItemFailures**. **This works because** by default retries are **infinite**, so one "poison record" blocks the shard until it expires (24 hours by default, up to 365 days). Bisect splits the batch in half to isolate the bad record, the limits stop endless retries, and partial batch response retries from the failed record only. The catch: an Amazon SQS or SNS destination gets only **metadata** (shard, sequence numbers), not the data.
- **If** several apps read the same Kinesis stream and latency must stay low, **then** use **enhanced fan-out (EFO)** consumers. **This works because** each EFO consumer gets a **dedicated 2 MB/s per shard**, pushed over HTTP/2, instead of sharing the shard's 2 MB/s read limit with the other consumers. The catch is extra Kinesis cost.
- **If** you need per-minute counts from a stream without an external store, **then** use Lambda **tumbling windows** (up to **900 s**). **This works because** Lambda passes **state** between invocations inside each fixed window per shard, so the function can aggregate without a database.
- **If** 5 different services must react to **Amazon DynamoDB Streams** changes, **then** let **one** Lambda read the stream and fan out through **Amazon Simple Notification Service (SNS)** or **Amazon EventBridge**, or use **Kinesis Data Streams for DynamoDB** instead. **This works because** at most **2** Lambda functions should read the same stream shard (only **1** for global tables); more readers cause throttling, while SNS or EventBridge deliver one change to many targets.
- **If** only `INSERT` events from a DynamoDB stream matter, **then** add an **event filter** on the event source mapping (ESM), for example `eventName = INSERT`. **This works because** the filter drops records **before** the function runs, and you do not pay for filtered-out invokes.
- **If** one failed Amazon Simple Queue Service (SQS) message makes the whole batch run again, **then** turn on **ReportBatchItemFailures** (partial batch response). **This works because** the function returns only the failed message IDs: only those go back to the queue and the successful ones are deleted. Without it, one failure retries the whole batch.
- **If** SQS messages are processed twice while still running, **then** the queue's **visibility timeout** is shorter than the processing time. Set it to at least **6 × the function timeout** (plus the batching window) (verify). **This works because** a received message stays hidden only for the visibility timeout; if the function is still working when it ends, the message becomes visible again and another invoke picks it up.
- **If** an SQS-triggered Lambda overloads an Amazon Relational Database Service (RDS) database, **then** set the event source mapping **maximum concurrency** (and the function's **reserved concurrency**), and use **Amazon RDS Proxy**. **This works because** maximum concurrency (**2–1,000** per SQS mapping) caps how many invokes the queue can drive, and RDS Proxy pools and reuses database connections across many Lambda environments. The catch: keep reserved concurrency at least the sum of max concurrency of all SQS mappings, or Lambda throttles and messages go back to the queue.
- **If** failed SQS messages must be kept for inspection, **then** set a **redrive policy** with a **dead-letter queue (DLQ)** on the **source SQS queue** (`maxReceiveCount`), and **redrive** them after fixing the bug. **This works because** for SQS sources the DLQ belongs to the queue, not the function; the function-level DLQ is only for async invokes.
- **If** strict per-customer ordering is needed with queue processing, **then** use an **SQS FIFO** queue with **MessageGroupId = customer ID**. **This works because** FIFO keeps order **per message group ID**. The catch: concurrency is limited by the number of **active message groups**, and a failure blocks that group until it succeeds or goes to the DLQ.
- **If** a burst of **1 million** SQS messages must drain fast with predictable scaling, **then** use **provisioned mode** on the SQS event source mapping, which gives dedicated **event pollers** with a minimum and maximum count. **This works because** it scales about **3× faster** (up to 1,000 concurrent invokes per minute) and up to **100,000** concurrent invokes, while default mode starts at 5 concurrent batches, adds up to 300 per minute and stops at 1,250. The catch: it costs extra per event poller unit hour and cannot be combined with maximum concurrency.
- **If** a function triggered by Amazon Simple Storage Service (S3) writes back to the same bucket and runs forever, **then** write to **another bucket or prefix** and use **prefix/suffix filters** on the event notification. **This works because** each write creates a new `ObjectCreated` event that triggers the function again; separating input and output breaks the loop. **Recursive loop detection** covers S3 and stops the loop after about **16** invocations, but it is a safety net, not the fix.
- **If** several consumers need the same S3 upload event, **then** send S3 events to **Amazon EventBridge** (or fan out with **Amazon Simple Notification Service (SNS)**). **This works because** EventBridge gives richer filtering, **multiple targets** and archive/replay, and SNS delivers one message to many subscribers.
- **If** a job must run every night at **02:00** in a local time zone, **then** use **Amazon EventBridge Scheduler** with a **cron expression** and a **time zone**, targeting Lambda (or AWS Step Functions). **This works because** Scheduler runs targets on cron or rate schedules and supports time zones, one-time schedules and flexible windows.
- **If** you must process **50,000** S3 files in parallel with retries, **then** use **AWS Step Functions Distributed Map**, which invokes Lambda per file or per batch. **This works because** the Map state fans out over many S3 objects (Distributed Map handles millions of items) with built-in retries and catch, and breaks the work into many sub-15-minute Lambda calls.
- **If** streaming JSON must land in S3 as **Parquet** with light cleanup, **then** use **Amazon Data Firehose** with a **Lambda transform** plus **record format conversion**. **This works because** Firehose calls the Lambda on each buffered batch to clean or fix records, then converts them to Parquet using an AWS Glue table schema and writes them to S3. Failed records go to an S3 error prefix (verify the buffer and timeout limits).
- **If** a nightly job must run SQL on Amazon Redshift without managing connections, **then** use Lambda with the **Redshift Data API**. **This works because** the Data API runs SQL with no JDBC driver, no connection management and no Virtual Private Cloud (VPC) needed, using Identity and Access Management (IAM) or AWS Secrets Manager auth; calls are async with statement IDs.
- **If** a pipeline must start an **AWS Glue** job when a file arrives, **then** use **S3 → Amazon EventBridge rule → Glue workflow** (or **AWS Step Functions**), or **S3 → Lambda**, where the function calls `glue:StartJobRun`. **This works because** the S3 event marks the file's arrival, and both paths turn it into a job start with no polling.
- **If** a function needs a **2 GB** model file shared across invocations, **then** mount **Amazon Elastic File System (EFS)** (the function in a Virtual Private Cloud (VPC), using an **EFS access point**), or package the model in a **container image**. **This works because** EFS is a shared, persistent file system mounted under `/mnt`, and a container image can be up to 10 GB, while a .zip package is limited to 250 MB unzipped. The catch: under high concurrency use EFS **Elastic throughput**, because bursting credits can run out.
- **If** a function needs **5 GB** of scratch space to decompress a file, **then** raise its **ephemeral storage** (`/tmp`) up to **10 GB**. **This works because** `/tmp` is fast local disk: 512 MB is free and you pay for more. It is private to one environment and lost when that environment ends.
- **If** a function attached to a Virtual Private Cloud (VPC) suddenly cannot reach Amazon S3, **then** check that the VPC has a **Network Address Translation (NAT) gateway** or an **S3 gateway endpoint**. **This works because** a VPC-attached function reaches S3 only through NAT or an endpoint.
- **If** you must reprocess yesterday's stream data after a bug fix, **then** create a **new event source mapping** starting at **`AT_TIMESTAMP`** (within the stream's retention period), or replay from an **Amazon EventBridge archive** or a raw copy kept in Amazon S3. **This works because** streams keep records until retention ends, so a new mapping can read them again from a chosen time. The catch: DynamoDB Streams keep records only **24 hours**, so keep raw data in S3 for longer replays.
- **If** you want to move Amazon Simple Queue Service (SQS) messages to AWS Step Functions with filtering and no glue code, **then** use **Amazon EventBridge Pipes**. **This works because** Pipes connects a source to a target with filtering and enrichment built in, so no Lambda is needed just to move data.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: Kinesis ESM polling, EFO, batching window, ParallelizationFactor and parameters (batch size, retries, record age, bisect, destination, tumbling window); DynamoDB Streams ESM polling rate, readers per shard, ordering; SQS ESM batching, partial batch response, scaling (5 start, +300/min, 1,250 max), maximum concurrency 2–1,000, provisioned mode, FIFO behavior; async destinations; recursive loop detection services (SQS, S3, SNS, EventBridge custom buses, Lambda) and the ~16 threshold; file system options (EFS or S3 Files, not both); MSK as an event source overview.
Not confirmed (verify): number of filters per ESM, provisioned mode support for Kinesis/DynamoDB, SQS provisioned max pollers (2,000 vs 10,000 between pages), visibility timeout 6× wording, maxReceiveCount ≥5 guidance, Kafka scaling/bisect/starting positions/networking/schema registry details, Firehose Lambda buffer and timeout limits, S3 Files setup details.

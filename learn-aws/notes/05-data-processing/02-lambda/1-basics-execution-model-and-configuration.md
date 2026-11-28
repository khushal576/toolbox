# Lambda – 1. Basics, execution model and configuration

Short notes. Each point is a fact you can be asked about.

## A. What Lambda is
- AWS Lambda = serverless functions. You upload code, and AWS runs it when an event arrives. No servers to manage, patch or scale.
- You pay per request plus per **GB-second** of run time. Idle costs nothing (scale to zero).
- Lambda is **stateless** by design. Each invocation must not depend on memory or disk from an earlier one. Store state in S3, DynamoDB, ElastiCache or a database.
- Max run time: **15 minutes** (900 s) per invocation on default Lambda.
- Memory: **128 MB to 10,240 MB**. CPU is given **in proportion to memory**. At **1,769 MB** a function gets the equal of **1 vCPU**. Up to 6 vCPUs at 10 GB (verify).
- Lambda is a **managed** service in the shared responsibility model. AWS runs the OS, runtime patching (managed runtimes), scaling and availability across AZs.
- Pick Lambda when:
  - The work is short and event-driven: S3 upload → process file, stream record → transform, API call → response.
  - Glue code between services: start a Glue job, run an Athena query, send an alert.
  - Spiky or unpredictable traffic that would leave servers idle.
  - Light per-record transforms, validation, enrichment and routing.
- Avoid Lambda when:
  - A job runs longer than 15 minutes → AWS Batch, ECS/Fargate, Glue, EMR, Step Functions (to split the work), or Lambda durable functions.
  - Big-data joins and aggregations over many GB/TB → Glue Spark, EMR, Athena, Redshift.
  - Steady, very high, 24/7 load where an always-on server is cheaper → ECS/EC2, or Lambda Managed Instances.
  - You need GPUs, a special OS, or more than 10 GB of memory.
- Lambda vs Glue Python shell: both run small Python jobs. Glue Python shell fits catalog-aware ETL longer than 15 minutes. Lambda fits event-driven, sub-15-minute work with very fast start.
- Lambda vs Step Functions: Lambda runs code. Step Functions **orchestrates** many steps (Lambda, Glue, Athena, EMR, Batch) with retries, branching, waits and state. Use both together.
- Lambda vs EventBridge Pipes: Pipes connects a source (SQS, Kinesis, DynamoDB Streams, Kafka) to a target with filtering and enrichment, **without writing a Lambda** just to move data.

## B. Core building blocks
- **Function** = code + configuration (runtime, handler, memory, timeout, role, environment variables, VPC, layers).
- **Handler** = the entry function Lambda calls with `(event, context)`. The event is JSON from the source. The context has the request ID, remaining time and function ARN.
- **Execution role** = IAM role Lambda assumes to run your code. It sets what the code can do (read S3, write DynamoDB, write logs).
- **Resource-based policy** = who can **invoke** the function (S3, SNS, EventBridge, API Gateway, another account).
- **Trigger / event source** = what invokes the function. It is either a **push** (the service calls Lambda) or a **poll** (an event source mapping that Lambda runs).
- **Layer** = a .zip of shared libraries or data, added under `/opt`. Up to **5 layers** per function. Layers count toward the 250 MB unzipped limit.
- **Extension** = a companion process inside the execution environment (monitoring agents, secrets caching, log shipping). It runs as part of the layer system.
- **Versions** and **aliases**: covered in section H.

## C. Execution environment lifecycle
- Each concurrent request gets its own **execution environment** (a Firecracker microVM on default Lambda). One environment handles **one request at a time** on default Lambda.
- **Init phase**:
  - Lambda creates the environment, downloads the code, starts the runtime and extensions.
  - It then runs your **code outside the handler** (imports, SDK clients, DB connections).
  - Init is limited to **10 seconds** for on-demand functions (verify). If it runs longer, it is retried on the first invoke with the function timeout.
- **Invoke phase**: runs the handler. Limited by the configured timeout.
- **Shutdown phase**: after idle time, Lambda freezes then removes the environment. Extensions get a short shutdown signal.
- **Cold start** = a request that needs a new environment (Init plus Invoke). This adds latency: from tens of ms to several seconds, depending on runtime, package size and init code.
- **Warm start** = reuse of an existing environment. Only the handler runs.
- Reuse means:
  - Globals and SDK clients stay in memory.
  - `/tmp` files may still be there.
  - Open connections may be reused.
- Use reuse as a **cache**, never as a source of truth. AWS can recycle environments at any time.
- Best practice: create SDK clients and DB connections **outside the handler** so warm calls reuse them.
- Cold starts happen on first calls, on scale-out, after code or config updates, and after idle periods.
- VPC attachment no longer adds big cold-start delays. ENIs are created when the function is created or updated, not per invoke (see file 3).

## D. Runtimes and packaging
- **Managed runtimes**: Node.js, Python, Java, .NET, Ruby. AWS patches them automatically.
- **OS-only runtimes** (`provided.al2023`, `provided.al2`): for Go, Rust, C++ or a custom runtime that uses the Runtime API.
- Go now runs on the OS-only runtime. The old `go1.x` runtime is retired (verify).
- **Runtime deprecation**: AWS ends support for runtimes when the language version reaches end of life. After deprecation you get no patches. Later you can no longer **create**, and then no longer **update**, functions on that runtime. Existing functions keep running (verify current phases).
- **Runtime management controls**: Auto (default, patch automatically), Function update (patch when you deploy), Manual (pin a runtime version and roll back if a patch breaks you).
- **.zip deployment package**:
  - **50 MB** zipped through the API/console. Upload bigger packages through S3.
  - **250 MB** unzipped, including all layers.
- **Container image**:
  - Up to **10 GB** uncompressed, stored in **Amazon ECR**.
  - Use for big ML libraries or native dependencies, or to reuse a Docker build process.
  - Must implement the Lambda Runtime API: use an AWS base image or add the Runtime Interface Client.
  - Layers are not used with images. Bake everything into the image.
- **Architectures**: `x86_64` or **`arm64` (Graviton)**. arm64 gives better price/performance and a lower GB-second price (about 20% cheaper; verify). Native libraries must be built for ARM.
- Code storage: **300 GB per Region** for .zip functions and layers (all versions count). Self-managed S3 code storage is an option beyond that. Clean up old versions.

## E. Memory, CPU, timeout and storage settings
- **Memory**: 128–10,240 MB in 1 MB steps. More memory also means more CPU and more network bandwidth.
- A CPU-bound function often runs **faster and cheaper** with more memory, because it is billed per GB-second and finishes sooner. Test with **AWS Lambda Power Tuning** or Compute Optimizer.
- Above about 1.8 GB you get more than 1 vCPU. Single-threaded code does not speed up past that. Use multiple threads or processes to gain.
- **Timeout**: 1 s to **900 s**. Default **3 s**. Set it close to real need plus margin.
- **Ephemeral storage `/tmp`**:
  - **512 MB** to **10,240 MB**. 512 MB is free; you pay for more.
  - Local to the environment, not shared between environments, encrypted (verify), lost when the environment ends.
- **Environment variables**: key/value config, **4 KB total**. Encrypted at rest with KMS (AWS managed key by default, or your CMK). Not for large secrets (see file 4).
- **File descriptors**: 1,024. **Processes/threads**: 1,024.
- **Network bandwidth** per environment: **625 Mbps** default. Non-VPC functions can request an increase that scales with memory, up to about 3 Gbps.

## F. Invocation types
- **Synchronous** (RequestResponse):
  - The caller waits for the result. Errors go back to the caller, and **the caller decides on retries**.
  - Used by API Gateway, ALB, function URLs, the SDK `Invoke`, Step Functions task (default), and Cognito triggers.
  - Payload limit **6 MB** request and **6 MB** response. Response streaming allows up to **200 MB**.
- **Asynchronous** (Event):
  - Lambda puts the event on an **internal queue** and returns **HTTP 202** at once. A separate process invokes the function later.
  - Used by **S3 event notifications, SNS, EventBridge**, CloudWatch Logs subscriptions, SES, and the SDK with `InvocationType=Event`.
  - Payload limit **1 MB** (raised from 256 KB).
  - Lambda handles retries (section G).
- **Event source mapping (poll-based)**:
  - A Lambda-managed poller reads from **SQS, Kinesis Data Streams, DynamoDB Streams, Amazon MSK, self-managed Kafka, Amazon MQ, DocumentDB change streams**.
  - It invokes the function **synchronously** with a **batch**.
  - Retry behavior depends on the source (file 2).
- **Function URL**: a dedicated HTTPS endpoint for a function, with auth type `AWS_IAM` or `NONE`. Supports response streaming. It is simpler than API Gateway but has no throttling, API keys or request validation.
- Who retries? Synchronous: the caller. Asynchronous: Lambda (up to 2 retries). Event source mapping: the poller, until success or the record expires (streams), or the visibility timeout / redrive (SQS).
- **At-least-once delivery**: async and event source mapping invocations can deliver the **same event more than once**. Make functions **idempotent** (dedupe keys, conditional writes, Powertools idempotency).

## G. Asynchronous invocation details
- On a **function error** (exception, timeout, out of memory), Lambda retries **2 more times** by default: 1 minute after the first failure, then 2 minutes after the second.
- **Retry attempts** can be set to **0, 1 or 2**.
- **Maximum event age**: **60 s to 6 hours** (default 6 hours). Events older than this are dropped (or sent to a failure target).
- On **throttling (429)** or system errors (5xx), Lambda keeps the event and retries with exponential backoff (1 s up to 5 minutes) for up to the max event age (6 hours default).
- If the queue is very long, events may age out before running. Monitor `AsyncEventAge` and `AsyncEventsDropped` (verify metric names).
- **Destinations** (preferred over DLQ):
  - **On-success** and **on-failure** targets: **SQS, SNS, Lambda, EventBridge**, and **S3 (on failure only)**.
  - The record includes the request **and** the response or error details.
  - Can be set per function, version or alias.
- **Dead-letter queue (DLQ)** (older):
  - **SQS standard queue or SNS standard topic** only. Failures only.
  - The original event only, plus error attributes (RequestID, ErrorCode, ErrorMessage).
  - Set at function level only, shared by all versions.
- FIFO queues and FIFO topics are **not** supported as async destinations or DLQs.
- An SNS destination has a 256 KB message limit, so 1 MB async payloads can fail delivery there. Use SQS or S3 instead.
- Setting **reserved concurrency to 0** on an async function sends new events straight to the DLQ / on-failure destination without retries. Use it as an emergency stop.
- **Destinations for event source mappings**: Kinesis, DynamoDB Streams and Kafka mappings have their own **on-failure destination** (SQS, SNS, S3; Kafka can also use a Kafka topic). SQS sources use a **DLQ on the queue itself**, not on the function.

## H. Versions and aliases
- **`$LATEST`** = the editable, unpublished version.
- **Publishing a version** freezes code plus configuration into an **immutable** numbered version (1, 2, 3…), each with its own ARN.
- **Qualified ARN** ends with `:version` or `:alias`. An **unqualified ARN** points to `$LATEST`.
- **Alias** = a named pointer (`prod`, `dev`) to one version, or **split by weight between two versions** (canary). Triggers and callers use the alias, so you can repoint it without changing them.
- Weighted aliases let CodeDeploy do **canary / linear / all-at-once** traffic shifting, with automatic rollback on CloudWatch alarms (file 4).
- Provisioned concurrency and SnapStart work on **published versions or aliases**, not `$LATEST`.
- Event source mappings and resource policies can target a specific alias, so dev and prod each get their own triggers.
- Old versions use code storage. Delete the ones you no longer need.

## I. SnapStart (faster cold starts)
- When you **publish a version**, Lambda runs Init, takes a **Firecracker snapshot** of memory and disk, encrypts it and caches it. New environments **resume from the snapshot** instead of running Init.
- Supported: **Java 11+, Python 3.12+, .NET 8+** managed runtimes (zip and container images on AWS base images).
- Not supported: Node.js, Ruby, OS-only runtimes. Also not with **provisioned concurrency**, **EFS**, **S3 Files**, or **`/tmp` above 512 MB**.
- Works only on **published versions and aliases**, not `$LATEST`.
- Pricing: **free for Java**. Python and .NET pay a **caching** charge (minimum 3 hours, per active version) plus a **restore** charge per resume.
- **Uniqueness trap**: anything generated in Init (random seeds, unique IDs, temp credentials, cached timestamps) is copied into every resumed environment. Generate unique values in the handler, or use **runtime hooks** (before snapshot / after restore).
- Network connections made during Init may be stale after restore. Validate and reconnect. AWS SDK connections usually recover by themselves.
- Use **provisioned concurrency** instead when you need guaranteed double-digit-millisecond starts.

## J. Newer Lambda options (know they exist)
- **Lambda durable functions**:
  - Multi-step workflows written as normal code (JavaScript/TypeScript, Python, Java SDK). They can run for **up to 1 year**.
  - Use **checkpoints and replay**: after an interruption, code re-runs from the start but skips completed steps.
  - **Waits suspend without compute charges**, which fits human approvals and polling.
  - Limits: max 3,000 durable operations and 100 MB persisted data per execution.
  - Vs Step Functions: durable functions = code-first inside Lambda. Step Functions = visual/ASL orchestration with 220+ native service integrations.
- **Lambda Managed Instances**:
  - Run Lambda functions on **EC2 instances in your account**, chosen through a **capacity provider** (VPC, instance types, scaling). Lambda manages them: patching, scaling, routing.
  - **Multi-concurrent**: one execution environment handles many requests at once, so code must be thread-safe.
  - **No cold starts** (scales on CPU use). Keeps a minimum number of environments. **No scale to zero**.
  - Pricing: **EC2 price + 15% management fee + $0.20 per 1M requests**. EC2 **Savings Plans / RIs** apply to the EC2 part only.
  - Timeout up to **90 minutes** for async and most event source mapping invocations.
  - For high-volume, steady, predictable workloads, or when you need specific hardware.
- **Lambda MicroVMs** (announced June 2026):
  - A separate resource for running **untrusted user or AI-generated code** in VM-level isolation (Firecracker).
  - Sessions up to **8 hours** that can suspend and resume. Images are built from a Dockerfile. arm64 (Graviton).
  - Not a data-pipeline tool. Know it is distinct from Lambda functions.
- **Response streaming**: send the response progressively (up to 200 MB) through function URLs or the API. It improves time-to-first-byte.
- **Lambda@Edge / CloudFront Functions**: run at CloudFront edge locations for request/response changes. Not used for data pipelines.

## K. Things that commonly trip people up
- Lambda's default concurrency quota is **1,000 per Region, shared by all functions**. New accounts may get **lower** concurrency and memory quotas until usage grows. One runaway function can starve the others (file 3).
- The **15-minute timeout** is hard on default Lambda. Long jobs must be split (Step Functions Map, SQS fan-out, durable functions) or moved.
- `/tmp` is **per environment**, not shared. Two concurrent invocations do not see each other's files.
- Payload limits: **6 MB sync, 1 MB async**, and event source batches up to 6 MB. Pass large data by **S3 reference** (bucket/key), not inline.
- Async invocation returns success (202) even if the function later fails. Use destinations or a DLQ to see failures.
- Environment variable changes, memory changes and code changes all create **new environments** (cold starts) on the next invokes.
- The console editor is for quick edits only. Real deployments go through SAM/CloudFormation/CDK and CI/CD.

## Scenarios (if → then, because)
- **If** a CSV file lands in Amazon Simple Storage Service (S3) and must be checked and written to Amazon DynamoDB within seconds, **then** use an **S3 event notification** that triggers an **AWS Lambda** function. S3 calls Lambda **asynchronously** as soon as the object is created, and the function validates the rows and writes them. **This works because** Lambda is event-driven, runs short jobs (up to **15 minutes**) with no servers to manage, and you pay only per request and run time, so idle time costs nothing.
- **If** a transform takes **40 minutes**, **then** do not use plain Lambda, because one invocation can run at most **15 minutes** (900 s). Use **AWS Glue**, **AWS Batch** or **Amazon Elastic Container Service (ECS) on AWS Fargate** instead, or split the work into small pieces with **AWS Step Functions** or an **Amazon Simple Queue Service (SQS)** fan-out. **This works because** the 15-minute limit is hard on default Lambda, while these services run long jobs, or turn one long job into many short Lambda calls.
- **If** a CPU-heavy function is slow at **512 MB**, **then** raise its **memory**. Lambda gives CPU **in proportion to memory** (about **1 vCPU at 1,769 MB**). **This works because** you pay per **GB-second**: with more CPU the function finishes sooner, so it often costs the same or less while running faster. Test sizes with **AWS Lambda Power Tuning**.
- **If** a Python function loads large libraries at cold start and latency matters, **then** use **Lambda SnapStart** (Python **3.12+**), or **provisioned concurrency** when latency is strict. With SnapStart, Lambda runs the Init code once when you **publish a version**, saves a snapshot of memory and disk, and new environments **resume from the snapshot** instead of running Init again. **This works because** the slow library loading happens once, not on every cold start. The catch: SnapStart works only on published versions or aliases, and Python pays a small caching and restore charge.
- **If** an API needs guaranteed low latency at all times, **then** set **provisioned concurrency** on an **alias**. It keeps a number of execution environments **already initialized and warm**, so requests up to that number never cold start. **This works because** SnapStart still restores a snapshot whenever a new environment is needed, while provisioned concurrency gives guaranteed double-digit-millisecond starts. The catch: provisioned concurrency costs money for as long as it is on.
- **If** dependencies such as machine learning libraries are bigger than **250 MB unzipped**, **then** package the function as a **container image** stored in **Amazon Elastic Container Registry (ECR)**. **This works because** a .zip package plus its layers is limited to 250 MB unzipped, while a container image can be up to **10 GB**. Layers are not used with images, so bake everything into the image.
- **If** many functions share the same helper libraries, **then** put them in a **Lambda layer**, a .zip of shared code added under `/opt`. **This works because** each function can attach up to **5 layers**, so the shared code lives in one place. Layers still count toward the 250 MB unzipped limit.
- **If** you want to know when **asynchronous** invocations fail and see the error details, **then** set an **on-failure destination**: Amazon Simple Queue Service (SQS), Amazon Simple Notification Service (SNS), Amazon EventBridge, another Lambda function, or Amazon S3. **This works because** a destination record holds the request **and** the error details, while an older **dead-letter queue (DLQ)** stores only the original event. The catch: an async call returns success (202) even if the function later fails, so without a destination or DLQ you never see the failure.
- **If** async events must not be retried because the function has non-idempotent side effects, **then** set **retry attempts to 0** and send failures to an **on-failure destination**. **This works because** Lambda normally retries a failed async event **2 more times** (after 1 minute, then 2 minutes); with 0 the event runs once and failures are kept for review.
- **If** old async events are useless after 10 minutes, **then** set the **maximum event age** to **600 seconds**. **This works because** Lambda drops (or sends to a failure target) events older than this age; it can be set from **60 s to 6 hours** (default 6 hours).
- **If** Amazon S3 sends the same event twice and the function inserts duplicate rows, **then** make the function **idempotent**: use **conditional writes**, dedupe keys, or an idempotency table (for example Powertools idempotency). **This works because** async and event source mapping delivery is **at-least-once**, so the same event can arrive more than once; an idempotent function gives the same result however many times it runs.
- **If** new code must first go to **10%** of traffic, **then** **publish a version** and use a **weighted alias**, with **AWS CodeDeploy** running a **canary** shift and **Amazon CloudWatch alarms** for rollback. A published version is an immutable copy of code and settings; an alias is a named pointer that can split traffic by weight between two versions. **This works because** callers use the alias, so traffic moves slowly to the new version without changing them, and CodeDeploy rolls back automatically if an alarm fires.
- **If** dev and prod triggers must call different code, **then** create separate **aliases** (`dev`, `prod`), each pointing to its own version, with their own **event source mappings** or resource policy permissions. **This works because** event source mappings and resource policies can target a specific alias, so each environment gets its own triggers.
- **If** a SnapStart function returns the same "random" ID in many invocations, **then** the ID was created in the **Init** code, before the snapshot. Create it in the **handler** or in an **after-restore runtime hook**. **This works because** everything generated in Init is copied into every environment resumed from the snapshot, while the handler runs fresh on each request.
- **If** an approval step must wait days without paying for idle compute, **then** use **AWS Step Functions** (wait or callback steps) or **Lambda durable functions** (wait operations). **This works because** a plain Lambda runs at most 15 minutes and you pay while it waits, while durable functions can run **up to 1 year** and their **waits suspend without compute charges**. Step Functions keeps the waiting outside your code.
- **If** a steady **24/7** high-volume function costs more than an Amazon Elastic Compute Cloud (EC2) fleet would, **then** consider **Lambda Managed Instances** or **Amazon Elastic Container Service (ECS)**. Managed Instances run your functions on **EC2 instances in your account**, priced at the **EC2 price + 15% management fee + $0.20 per 1M requests**, and **EC2 Savings Plans / Reserved Instances** lower the EC2 part. **This works because** for steady, predictable load always-on servers are cheaper than paying per GB-second. The catch: Managed Instances do **not scale to zero**.
- **If** a webhook needs a quick HTTPS endpoint with no API features, **then** use a **Lambda function URL**, a dedicated HTTPS endpoint for one function with auth type **`AWS_IAM`** or **`NONE`**. **This works because** it is simpler than Amazon API Gateway; the catch is no throttling, API keys or request validation.
- **If** an async function must be stopped immediately, **then** set its **reserved concurrency to 0**. **This works because** no invocation can then run, so new events go straight to the **dead-letter queue (DLQ)** or **on-failure destination** without retries, an emergency stop.
- **If** you must move Amazon Simple Queue Service (SQS) or Amazon Kinesis Data Streams records to a target with simple filtering and no custom code, **then** use **Amazon EventBridge Pipes** instead of a "pass-through" Lambda. **This works because** Pipes connects a source to a target with filtering and enrichment built in, so you write and run no function just to move data.
- **If** the requirement says "least operational overhead" for small event-driven tasks, **then** choose **Lambda** over Amazon Elastic Compute Cloud (EC2) or containers. **This works because** AWS runs the operating system, patching, scaling and availability across Availability Zones (AZs), and you pay nothing when idle.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: Lambda quotas (memory, timeout, payloads incl. 1 MB async and 200 MB streaming, deployment package and image sizes, /tmp, env vars, layers, file descriptors, network bandwidth, code storage), concurrency basics, async invocation, error handling and retry timing, destinations vs DLQ, SnapStart runtimes, limits and pricing, durable functions overview and quotas, Lambda Managed Instances concurrency, pricing and comparison. Lambda MicroVMs from the AWS What's New post (June 2026) and press coverage.
Not confirmed (verify): 6 vCPUs at 10 GB, Init phase 10-second limit, go1.x retirement wording, exact runtime deprecation phases, arm64 ~20% price difference, /tmp encryption wording, async metric names (`AsyncEventAge`, `AsyncEventsDropped`).

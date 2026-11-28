# Lambda – 4. Security, deployment, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Two kinds of permissions
- **Execution role** (identity-based): what the **function code** may do. Lambda assumes this role and gives the code temporary credentials through environment variables.
  - The trust policy must allow `lambda.amazonaws.com` to assume it.
  - Minimum to write logs: **`AWSLambdaBasicExecutionRole`** (`logs:CreateLogGroup`, `CreateLogStream`, `PutLogEvents`).
  - VPC functions add **`AWSLambdaVPCAccessExecutionRole`**. Pollers (ESM) need read rights on the source (for example `AWSLambdaSQSQueueExecutionRole`, `AWSLambdaKinesisExecutionRole`, `AWSLambdaDynamoDBExecutionRole`).
  - Destinations, DLQs and on-failure targets need send/publish rights in the **execution role** (`sqs:SendMessage`, `sns:Publish`, `events:PutEvents`, `s3:PutObject`).
- **Resource-based policy** (function policy): **who may invoke** (or manage) the function.
  - Push sources (S3, SNS, EventBridge, API Gateway, CloudWatch Logs) are added here, usually with `aws:SourceArn` / `aws:SourceAccount` conditions to stop "confused deputy" calls.
  - **Cross-account invoke**: add the other account (or a role in it) to the resource policy. The caller also needs `lambda:InvokeFunction` in its own IAM policy.
  - Max size **20 KB**.
- To create or update a function with a role, the deployer needs **`iam:PassRole`** on that role.
- Least privilege: one role per function, scoped to the exact buckets/prefixes, tables, queues and KMS keys it uses. Avoid `*` actions.
- **Condition keys** for governance:
  - `lambda:FunctionArn`, `lambda:SourceFunctionArn` (calls made by function code)
  - `lambda:VpcIds`, `lambda:SubnetIds`, `lambda:SecurityGroupIds`
  - `lambda:Layer`, `lambda:CodeSigningConfigArn`, `lambda:Principal`, `lambda:FunctionUrlAuthType`
- **Tag-based (ABAC)**: allow teams to update only functions tagged with their team (`aws:ResourceTag/team`).
- A function role **cannot** be shared safely across very different functions without over-granting. Prefer separate roles.

## B. Secrets and configuration
- **Environment variables** are encrypted at rest with KMS (the AWS managed key `aws/lambda` by default, or your **customer managed key**).
- With a CMK, you can also use **encryption helpers** (client-side encrypt in the console). The code then must call `kms:Decrypt`.
- Anyone with `lambda:GetFunctionConfiguration` can see env var values (decrypted) unless you use the helpers. So env vars are **not** a good place for secrets.
- Preferred: **AWS Secrets Manager** (rotation, cross-account, versioning) or **SSM Parameter Store SecureString**, fetched at runtime with the execution role.
- The **AWS Parameters and Secrets Lambda Extension** caches secrets/parameters locally over an HTTP endpoint. Fewer API calls and lower cost and latency.
- Cache secrets in memory between warm invocations, with a refresh interval (rotation-safe).
- **RDS IAM authentication** or **RDS Proxy** with Secrets Manager avoids passwords in code.

## C. Code integrity and isolation
- **Code signing** with **AWS Signer**: a code signing configuration lists the allowed signing profiles. Lambda can **warn** or **enforce** (reject unsigned or modified code). Works for .zip packages (not container images; verify).
- **Container images**: scan in **ECR** (basic/enhanced scanning with Inspector). Use immutable tags or digests.
- **Amazon Inspector** scans Lambda functions and layers for vulnerable packages, and can also scan code (verify current coverage).
- Isolation: each execution environment is a **Firecracker microVM**. Environments are never shared across functions or accounts. Managed Instances use containers on Nitro instances, with the **capacity provider as the security boundary**.
- **Function URLs**:
  - **`AWS_IAM` auth** → callers sign requests (SigV4) and need `lambda:InvokeFunctionUrl`.
  - **`NONE`** → public. Protect it in code, add CORS settings, or put CloudFront/WAF in front.
- **API Gateway** adds authorizers (IAM, Cognito, Lambda authorizers), throttling, usage plans, WAF and request validation in front of Lambda.

## D. Encryption
- **At rest**: code, layers, env vars and snapshots (SnapStart) are encrypted by AWS. You can use a **CMK** for env vars and SnapStart snapshots (verify the CMK scope).
- **In transit**: Lambda API calls use TLS. Your code must use TLS to targets (HTTPS, DB SSL).
- **Data your function writes**: use SSE-KMS on S3, encryption on DynamoDB/SQS/SNS. The **execution role needs `kms:Encrypt`/`GenerateDataKey`/`Decrypt`** on the CMK, and the **key policy must allow it**. A missing KMS permission is a top cause of "AccessDenied" when reading SSE-KMS objects.
- **Cross-account encryption**: when a Lambda reads a KMS-encrypted object from another account, the **key policy in the owner account** must allow the Lambda role, and the role must allow `kms:Decrypt` on that key ARN.
- **Client-side encryption before transit**: the code encrypts with a KMS data key (envelope encryption, AWS Encryption SDK) before writing.

## E. Audit and governance
- **CloudTrail management events**: `CreateFunction`, `UpdateFunctionCode`, `UpdateFunctionConfiguration`, `AddPermission`, `CreateEventSourceMapping`, `PutFunctionConcurrency`… record who changed what.
- **CloudTrail data events**: **`Invoke`** calls (who invoked which function). **Off by default** (extra cost). Turn them on for audit of invocations.
- **AWS Config** rules:
  - `lambda-function-public-access-prohibited`
  - `lambda-inside-vpc`
  - `lambda-function-settings-check` (runtime, timeout, memory, role)
  - `lambda-concurrency-check`
  - `lambda-dlq-check`
- **Security Hub** controls flag deprecated runtimes, public resource policies and missing VPC config.
- **SCPs**: block deprecated runtimes, require VPC config, block function URLs with `NONE` auth (`lambda:FunctionUrlAuthType`), restrict Regions.

## F. Deployment and IaC
- **AWS SAM (Serverless Application Model)**:
  - A CloudFormation **transform** (`Transform: AWS::Serverless-2016-10-31`) with short resource types: `AWS::Serverless::Function`, `::Api`, `::HttpApi`, `::SimpleTable`, `::LayerVersion`, `::StateMachine`.
  - One SAM resource expands into many CloudFormation resources (function, role, permissions, event source mappings, API).
  - **`Events`** property on a function wires up triggers (S3, SQS, Kinesis, DynamoDB, Schedule, Api, EventBridgeRule) in a few lines.
  - **Policy templates** (`S3ReadPolicy`, `DynamoDBCrudPolicy`, `SQSPollerPolicy`) give least-privilege roles quickly.
  - CLI:
    - `sam init` (scaffold)
    - `sam build` (resolve dependencies, optionally in a container with `--use-container`)
    - `sam deploy --guided` (package to S3/ECR + CloudFormation changeset)
    - `sam local invoke` / `sam local start-api` (local testing in Docker)
    - `sam sync --watch` (fast dev sync)
    - `sam logs`, `sam pipeline init` (CI/CD templates)
  - **`AutoPublishAlias`** + **`DeploymentPreference`** in SAM set up **CodeDeploy** traffic shifting and alarms with no extra code.
- **CloudFormation**: `AWS::Lambda::Function`, `::Version`, `::Alias`, `::EventSourceMapping`, `::Permission`, `::LayerVersion`. Code comes from S3 (or inline for tiny functions; `ZipFile`, 4 KB; verify).
- **AWS CDK**: define Lambda in TypeScript/Python/Java/.NET/Go. Constructs like `NodejsFunction` / `PythonFunction` bundle code. It synthesizes to CloudFormation.
- **Terraform** and the **Serverless Framework** are also common (not AWS-native).
- **CodeDeploy for Lambda** (traffic shifting on an alias):
  - **Canary** (for example `Canary10Percent5Minutes`: 10% then 100% after 5 min).
  - **Linear** (for example `Linear10PercentEvery1Minute`).
  - **AllAtOnce**.
  - **Pre-traffic / post-traffic hooks** (Lambda functions that run validation tests).
  - **CloudWatch alarms** trigger automatic **rollback**.
- **CI/CD**:
  - CodePipeline/CodeBuild (or GitHub Actions) → `sam build` → unit tests → `sam deploy` to dev → integration tests → prod with canary.
  - Keep code in Git, and keep config and IaC versioned.
- **Testing**:
  - Unit tests with mocked AWS calls (moto, stubs).
  - `sam local` for integration.
  - Test events in the console (shareable test events; 10 per function in the editor).
  - Test in a real dev account for IAM/networking issues.
- **Packaging dependencies**: build native libraries for the right architecture (manylinux, arm64) using `sam build --use-container` or a Docker build. A wrong-arch binary fails with import errors.

## G. Cost
- **Requests**: **$0.20 per 1M** requests (us-east-1).
- **Duration**: per GB-second, metered **per 1 ms**. x86 about **$0.0000166667 per GB-s** in us-east-1 (first tier). **arm64 is cheaper** per GB-s (about 20% less; verify). Volume tiers lower the price above billions of GB-s per month.
- **Free tier**: **1M requests and 400,000 GB-seconds per month** (applies to x86 and arm64 together; verify), always free.
- **Ephemeral storage** above 512 MB: about $0.0000000309 per GB-s.
- **Provisioned concurrency**: pay for the allocation (about $0.0000041667 per GB-s) while it is enabled, plus a lower duration rate (about $0.0000097222 per GB-s) for invokes. **No free tier** for PC.
- **SnapStart** (Python/.NET): cache + restore charges. Java is free.
- **ESM provisioned mode**: per event poller unit (EPU) hour (about $0.00925 per EPU-hour in the SQS example).
- **Lambda Managed Instances**: $0.20 per 1M requests + **EC2 price + 15% management fee**. Savings Plans/RIs reduce only the EC2 part.
- **Durable functions**: charges for durable operations and storage on top of compute (verify pricing details).
- **Hidden costs**:
  - CloudWatch Logs ingestion/storage (often bigger than the Lambda bill), X-Ray traces.
  - NAT gateway data processing for VPC functions, interface endpoints.
  - Data transfer out, and downstream service calls (S3 requests, DynamoDB writes, KMS requests).
  - SQS empty receives for idle queues are handled by Lambda but still billed as SQS requests.
- **Compute Savings Plans** cover Lambda duration and provisioned concurrency (up to about 17% off; verify).
- **Cost optimization**:
  - Right-size memory (Power Tuning). Switch to **arm64**. Cut duration (connection reuse, batching, async calls).
  - Use **ESM event filtering** to skip useless invokes. Raise batch sizes.
  - Set **log retention** and log levels (JSON logs with `WARN` in prod). Avoid VPC/NAT when not needed (use gateway endpoints).
  - Remove idle provisioned concurrency.
- **When Lambda becomes more expensive than containers/EC2**: steady high utilization 24/7 (for example, many millions of long invocations). Compare with Fargate/EC2/Managed Instances.

## H. Monitoring and observability
- **CloudWatch metrics** (namespace `AWS/Lambda`), **free**, 1-minute:
  - **Invocations**: `Invocations`, `Errors` (function errors; not throttles), `Throttles`, `DeadLetterErrors`, `DestinationDeliveryFailures`, `RecursiveInvocationsDropped`.
  - **Performance**: `Duration`, `PostRuntimeExtensionsDuration`, `IteratorAge` (streams), `OffsetLag` (Kafka).
  - **Concurrency**: `ConcurrentExecutions`, `ProvisionedConcurrencyUtilization`, `ProvisionedConcurrencySpilloverInvocations`, `UnreservedConcurrentExecutions`.
  - **Async**: `AsyncEventsReceived`, `AsyncEventAge`, `AsyncEventsDropped`.
  - **Event source mapping**: polled/filtered/failed event counts, `ProvisionedPollers` (verify names).
- **Error rate** = Errors ÷ Invocations. Alarm on it, and on Throttles and IteratorAge, then send to **SNS** for alerts.
- **CloudWatch Logs**:
  - Each function writes to `/aws/lambda/<function-name>` by default (a custom log group is possible).
  - Each invoke logs `START`, `END` and a **`REPORT` line** with Duration, Billed Duration, Memory Size, **Max Memory Used** and Init Duration (cold starts).
  - **Log format**: **plain text or JSON** (structured).
  - **Log level filtering**: application log level (TRACE…FATAL) and system log level (DEBUG/INFO/WARN), set **without code changes** when you use JSON format.
  - Set **log retention** (default is never expire). Logs can go to **S3 or Firehose** directly as alternative destinations (verify current support).
- **CloudWatch Logs Insights**: query logs. For example, find the slowest invocations, count cold starts (`@initDuration`), or find memory near the max.
- **Metric filters** turn log patterns (for example "ERROR") into metrics/alarms. The **Embedded Metric Format (EMF)** writes custom metrics through logs with no API calls (Powertools Metrics uses it).
- **AWS X-Ray / CloudWatch Application Signals**: **active tracing** shows end-to-end request paths (API Gateway → Lambda → DynamoDB/S3), latency breakdown, init vs invoke, and downstream errors. Needs X-Ray permissions on the role. ADOT/OpenTelemetry layers are supported.
- **Lambda Insights**: a CloudWatch extension (layer) that collects **system-level metrics** (CPU, memory, network, disk), cold starts and worker shutdowns, at extra cost.
- **CloudTrail data events** for invoke auditing (see E).
- **AWS Health / email** notifications for recursive loop stops and runtime deprecations.
- **Synthetic tests**: CloudWatch Synthetics canaries for API endpoints backed by Lambda.

## I. Troubleshooting (symptom → cause → fix)
- **`Task timed out after X seconds`** → slow downstream call, waiting on a VPC resource with no route (NAT/endpoint missing), cold start plus heavy init, or the timeout is too low. Fix: raise the timeout, add NAT/endpoints, set SDK timeouts below the function timeout, use async patterns.
- **`Runtime exited with error: signal: killed` / "Max Memory Used" = memory size** → out of memory. Raise memory, stream data instead of loading all of it, reduce batch size.
- **`TooManyRequestsException` / Throttles metric** → account or reserved concurrency reached, or the scaling rate exceeded. Fix: request a quota increase, adjust reserved concurrency, use SQS buffering, backoff and retries.
- **`AccessDeniedException` calling S3/DynamoDB from code** → execution role missing the action/resource, bucket or key policy denies, **KMS key policy** missing, or the VPC endpoint policy blocks. Check the role and the resource policies.
- **S3/SNS/EventBridge never invokes the function** → missing **resource-based policy** permission for that service, or wrong event filter/prefix.
- **`ResourceNotFoundException` / invoking wrong code** → wrong qualifier/alias, or a trigger pointing to `$LATEST` instead of an alias.
- **Kinesis/DynamoDB IteratorAge rising** → errors retrying the same batch (poison record), throttling, slow function, too few shards. Fix: bisect, partial batch response, max retries/age, parallelization factor, more memory.
- **SQS messages processed twice** → visibility timeout shorter than processing time, or a whole-batch retry after a partial failure. Fix: visibility ≥ 6× timeout, ReportBatchItemFailures, idempotency.
- **SQS messages piling up in the DLQ** → persistent errors or throttling with a low `maxReceiveCount`. Fix the bug, raise concurrency/receive count, then **redrive**.
- **Async events missing** → max event age expired or retries exhausted with no destination/DLQ. Add an on-failure destination, monitor `AsyncEventsDropped`.
- **Function stuck in `Pending` / `Inactive`** → VPC ENI being created (or reclaimed after 14 idle days), or an ENI/IP quota limit in the subnets. Wait, add free IPs, check the ENI quota.
- **`EC2ThrottledException` / `ENILimitReachedException`** (VPC) → subnet out of IPs or ENI quota. Use bigger subnets, reuse SG/subnet combinations.
- **`Unable to import module` / `Runtime.ImportModuleError`** → missing dependency, wrong handler name, or a native library built for the wrong arch/OS. Rebuild with `sam build --use-container` for the right architecture.
- **`RequestEntityTooLargeException`** → payload over 6 MB sync / 1 MB async. Pass an S3 reference instead.
- **`CodeStorageExceededException`** → the 300 GB Regional code storage is full of old versions/layers. Delete unused versions.
- **Unexpected huge bill / runaway invocations** → a recursive loop (S3 writes back to its own trigger bucket, SQS re-queue). Recursion detection stops some loops (SQS, SNS, S3, EventBridge custom buses, Lambda). Others (DynamoDB) need guards. Set billing alarms and Cost Anomaly Detection.
- **Cold-start latency spikes** → bursty traffic or new deploys. Use provisioned concurrency/SnapStart and slimmer packages.
- **Logs missing** → the role lacks CloudWatch Logs permissions, the log group was deleted, or the log level filters drop messages.

## J. Limits and numbers to remember
| Item | Value |
|---|---|
| Timeout | 1–900 s (15 min), default 3 s; 90 min on Managed Instances (async/ESM) |
| Memory | 128–10,240 MB in 1 MB steps; 1,769 MB ≈ 1 vCPU |
| `/tmp` ephemeral storage | 512 MB (free) to 10,240 MB |
| Sync payload | 6 MB request / 6 MB response (200 MB streamed) |
| Async payload | 1 MB |
| Environment variables | 4 KB total |
| Layers | 5 per function; 250 MB unzipped total with code |
| .zip package | 50 MB zipped (direct upload), 250 MB unzipped |
| Container image | 10 GB uncompressed |
| Code storage per Region | 300 GB (not increasable; use self-managed S3 storage) |
| Resource-based policy | 20 KB |
| Account concurrency | 1,000 default per Region (raise to tens of thousands) |
| Unreserved minimum | 100 always kept unreserved |
| RPS limit | 10 × concurrency |
| Scaling rate | 1,000 environments per 10 s per function |
| PC allocation rate | up to 6,000 environments per minute per function |
| Async retries | 0–2 (default 2); waits 1 min then 2 min |
| Async max event age | 60 s – 6 h (default 6 h) |
| Batching window (ESM) | up to 300 s (5 min); not for SQS FIFO |
| Kinesis/DynamoDB batch size | default 100, max 10,000 |
| ParallelizationFactor | 1–10 per shard |
| Tumbling window | up to 900 s |
| Stream max record age | -1 (infinite) or up to 604,800 s |
| Stream max retries | -1 (infinite) or up to 10,000 |
| SQS batch size | default 10; max 10,000 standard, 10 FIFO |
| SQS ESM scaling | starts 5, +300/min, max 1,250 concurrent (default mode) |
| SQS max concurrency setting | 2–1,000 |
| SQS provisioned mode | up to 100,000 concurrent, ~1,000 more per minute |
| DynamoDB stream readers per shard | 2 (1 for global tables) |
| Recursive loop stop | about 16 invocations in one chain |
| VPC Hyperplane ENI | ~65,000 connections each; idle 14 days → Inactive |
| ENIs per VPC (Lambda quota) | 3,000 default |
| File descriptors / processes | 1,024 / 1,024 |
| Network bandwidth | 625 Mbps per environment (increase possible for non-VPC) |
| Control plane API | 15 requests/s total (GetFunction 100/s) |
| Durable functions | up to 1 year; 3,000 operations, 100 MB stored per execution |
| Lambda MicroVMs | up to 8 hours per MicroVM |
| Free tier | 1M requests + 400,000 GB-s per month |

## K. Final scenario set (if → then, because)
- **If** files land in Amazon Simple Storage Service (S3) and each must be checked and loaded in under a minute, **then** trigger an **AWS Lambda** function from an **S3 event notification**. **This works because** S3 invokes the function as soon as each object is created, Lambda is event-driven and needs **no servers**, and you pay only when files arrive.
- **If** **10,000** files arrive at once and the target database can take only **20** parallel writers, **then** send the events **S3 → Amazon Simple Queue Service (SQS) → Lambda** and set the event source mapping (ESM) **maximum concurrency** to **20**, with **Amazon RDS Proxy** in front of the database. **This works because** SQS buffers the burst, maximum concurrency caps how many invokes the queue can drive at once, and RDS Proxy pools database connections. Messages wait safely in the queue instead of overloading the database.
- **If** a Lambda must process **Amazon Kinesis Data Streams** records in order per device, **then** use the **device ID as the partition key**. **This works because** Lambda keeps order **per shard**, and per partition key even with a **ParallelizationFactor** above 1. There is no order across shards, so the key is what keeps one device's records in order.
- **If** a transform needs **30+ minutes**, **then** use **AWS Glue**, **Amazon EMR**, **AWS Batch** or **AWS Fargate**, or let **AWS Step Functions** split the work into Lambda-sized chunks. **This works because** one Lambda invocation can run at most **15 minutes**, a hard limit on default Lambda.
- **If** Lambda reads from Kinesis and failed records must be kept for analysis, **then** add an **on-failure destination** (Amazon SQS, Amazon Simple Notification Service (SNS) or S3), turn on **BisectBatchOnFunctionError**, and set **maximum retries** and **maximum record age**. **This works because** the limits stop a bad record from being retried forever, bisect splits the batch to isolate it, and the destination records what was discarded. The catch: SQS/SNS destinations get **metadata** (shard, sequence numbers), not the data, so read the records back from the stream before they expire.
- **If** several Lambdas need retries with backoff, branching and a human approval step, **then** use **AWS Step Functions** (or **Lambda durable functions** if you prefer code). **This works because** Step Functions orchestrates many steps with built-in retries, branching, waits and state, while durable functions write the same workflow as normal code, with checkpoints and waits that cost no compute.
- **If** the team deploys serverless pipelines and wants local testing and a short template, **then** use the **AWS Serverless Application Model (SAM)**: `sam build`, `sam local invoke`, `sam deploy`. **This works because** SAM is an AWS CloudFormation transform where one short resource expands into the function, role, permissions and triggers, and `sam local` runs functions locally in Docker.
- **If** new versions must go to **10%** of traffic and roll back on errors, **then** use SAM **`AutoPublishAlias`** + **`DeploymentPreference`**, which set up an **AWS CodeDeploy canary** (for example `Canary10Percent5Minutes`) with **Amazon CloudWatch alarms**. **This works because** SAM publishes each new version behind an alias, and CodeDeploy shifts traffic on that alias step by step: 10% first, then 100% after 5 minutes. If an alarm fires, it rolls back automatically, with no extra code.
- **If** infrastructure must be defined in **Python** with reusable components, **then** use the **AWS Cloud Development Kit (CDK)**. **This works because** CDK defines Lambda in TypeScript, Python, Java, .NET or Go with reusable constructs (such as `PythonFunction`, which bundles code), and it synthesizes to CloudFormation.
- **If** a database password must not be in code or environment variables, **then** store it in **AWS Secrets Manager** and read it at runtime with the **execution role**, using the **AWS Parameters and Secrets Lambda Extension** to cache it. **This works because** anyone with `lambda:GetFunctionConfiguration` can see environment variable values, while Secrets Manager adds rotation and versioning. The extension caches the secret locally, so there are fewer API calls and lower cost and latency.
- **If** Amazon S3 must be allowed to invoke a function in another account, **then** add a **resource-based policy** statement for `s3.amazonaws.com` with `aws:SourceAccount` / `aws:SourceArn` conditions. **This works because** the resource-based policy decides **who may invoke** the function, and the conditions make sure only your bucket and account can call it, which stops "confused deputy" calls.
- **If** an app in account B must invoke a function in account A, **then** add a **resource-based policy** in A that allows B's role, plus `lambda:InvokeFunction` in B's role policy. **This works because** cross-account access needs both sides: the function's policy must allow the caller, and the caller's own Identity and Access Management (IAM) policy must allow the call.
- **If** reading objects encrypted with **SSE-KMS** fails with **AccessDenied** although the S3 permissions are right, **then** add `kms:Decrypt` to the execution role and allow the role in the **AWS Key Management Service (KMS) key policy**. **This works because** reading an SSE-KMS object also uses the key, so both the role and the key policy must allow it. A missing KMS permission is a top cause of this error.
- **If** only signed, approved code may be deployed, **then** use a **code signing configuration** with **AWS Signer** in **Enforce** mode. **This works because** the configuration lists the allowed signing profiles, and in Enforce mode Lambda rejects unsigned or modified code (Warn mode only warns).
- **If** auditors need a list of who invoked a sensitive function, **then** enable **AWS CloudTrail data events** for Lambda. **This works because** data events record each **`Invoke`** call; they are **off by default** and cost extra, while management events record only changes such as `UpdateFunctionCode`.
- **If** you need to find configuration changes to functions over time, **then** use **AWS Config** (plus **CloudTrail management events**). **This works because** AWS Config checks function settings with rules such as `lambda-function-settings-check`, and CloudTrail management events show who changed what (`UpdateFunctionConfiguration`, `AddPermission` and more).
- **If** operators need alerts when a pipeline Lambda fails, **then** create an **Amazon CloudWatch alarm** on `Errors` (or the error rate) that notifies **Amazon Simple Notification Service (SNS)**, or use an async **on-failure destination** to SNS or **Amazon EventBridge**. **This works because** CloudWatch Lambda metrics are free and per minute, and error rate = Errors ÷ Invocations; a destination also carries the failed event and error details.
- **If** you need to see where time is spent across **Amazon API Gateway**, Lambda and **Amazon DynamoDB**, **then** turn on **AWS X-Ray active tracing** (or **CloudWatch Application Signals**). **This works because** tracing shows the whole request path with the latency of each step, init versus invoke time and downstream errors. The role needs X-Ray permissions.
- **If** you need memory and CPU use per invocation to right-size a function, **then** use the **REPORT** log line (**Max Memory Used**), **Lambda Insights** and **AWS Compute Optimizer**. **This works because** each invoke logs a REPORT line with duration and memory used, Lambda Insights collects system metrics (CPU, memory, network, disk) at extra cost, and Compute Optimizer recommends memory from real usage.
- **If** you need to search errors across many functions' logs, **then** use **CloudWatch Logs Insights** with **JSON** structured logs. **This works because** Logs Insights queries logs, and JSON logs give named fields you can filter and count.
- **If** logs cost too much, **then** use the **JSON log format** with a higher **log level** (for example `WARN`) in prod, and set **log retention**. **This works because** with JSON format you can filter log levels without code changes, and by default logs **never expire**. CloudWatch Logs costs are often bigger than the Lambda bill.
- **If** most of the monthly bill is duration for a CPU-heavy x86 function, **then** switch to **arm64 (AWS Graviton)** and tune memory. **This works because** arm64 has a lower price per GB-second (about 20% less; verify), and right-sizing memory with Power Tuning cuts duration. The catch: native libraries must be built for ARM.
- **If** a function has a steady 24/7 load and costs more than containers, **then** compare **AWS Fargate**, Amazon Elastic Compute Cloud (EC2), or **Lambda Managed Instances** with **Savings Plans**. **This works because** under steady high use, always-on compute is cheaper than per-request billing. Managed Instances cost the **EC2 price + 15% management fee** + $0.20 per 1M requests, and Savings Plans lower only the EC2 part.
- **If** a synchronous API must never cold start during business hours, **then** set **provisioned concurrency** on an **alias** with **scheduled auto scaling**. **This works because** provisioned concurrency keeps environments warm, and the schedule raises it for business hours and lowers it after, so you pay only when needed. There is no free tier for provisioned concurrency.
- **If** an S3-triggered function writes back into the same bucket and costs explode, **then** use a **separate output bucket or prefix** and **prefix/suffix filters**. **This works because** each write triggers the function again, creating a loop. **Recursive loop detection** breaks the S3 loop after about **16** invocations; set billing alarms too.
- **If** a Lambda in a Virtual Private Cloud (VPC) must call a public SaaS API, **then** put it in **private subnets** with a route to a **Network Address Translation (NAT) gateway**, not in a public subnet. **This works because** Lambda network interfaces never get public IP addresses, so only NAT gives a VPC function internet access.
- **If** you must run ad-hoc **Amazon Athena** queries after each upload, **then** have Lambda call Athena **`StartQueryExecution`**, and use **AWS Step Functions** to wait for the results. **This works because** the call is async: it starts the query and returns at once, and waiting inside Lambda pays for idle time, while Step Functions can wait for completion.
- **If** a team wants the "least operational overhead" way to run small event-driven Python transforms, **then** use **Lambda**, with the **AWS SDK for pandas** layer if needed. **This works because** Lambda needs no servers, and the AWS-managed AWS SDK for pandas layer reads and writes S3 Parquet, updates the AWS Glue Data Catalog and runs Athena queries in a few lines.
- **If** transforms are big Spark jobs on terabytes, **then** use **AWS Glue** or **Amazon EMR**, not Lambda. **This works because** Lambda is limited to 10 GB memory, 10 GB `/tmp` and 15 minutes, while Glue and EMR run Spark for big joins and aggregations.
- **If** a streaming workload needs exactly-once effects per key, **then** use **idempotent writes**, such as **conditional puts** or **upserts**. **This works because** Lambda delivery is **at-least-once**, so a record can arrive twice; idempotent writes give the same result each time.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: Lambda quotas table (incl. code storage, control plane API limits, durable function and MicroVM quotas), concurrency and scaling rules, async destinations and DLQ details (incl. S3 on-failure only, SNS 256 KB caveat, FIFO not supported), recursive loop detection, VPC permissions and condition keys, SnapStart pricing, Managed Instances pricing, and the pricing page for us-east-1 request, duration, free tier, ephemeral storage, provisioned concurrency and EPU prices.
Not confirmed (verify): code signing support for container images, Inspector code scanning coverage, CMK scope for SnapStart snapshots, CloudFormation inline `ZipFile` size, arm64 price difference (~20%), whether the free tier spans both architectures, Compute Savings Plans discount for Lambda (~17%), durable functions pricing details, exact metric names for async and ESM metrics, log delivery directly to S3/Firehose.

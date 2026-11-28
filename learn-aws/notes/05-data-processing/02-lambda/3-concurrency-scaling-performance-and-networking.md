# Lambda – 3. Concurrency, scaling, performance and networking

Short notes. Each point is a fact you can be asked about.

## A. Concurrency basics
- **Concurrency** = the number of requests a function handles **at the same moment**. On default Lambda, each one needs its own execution environment.
- Formula: **concurrency = requests per second × average duration (seconds)**.
  - 100 req/s × 0.5 s = 50 concurrent.
  - 5,000 req/s × 0.2 s = 1,000 concurrent.
- Shorter duration = less concurrency for the same traffic. Optimizing code also lowers throttling risk.
- **Account concurrency quota**: **1,000 per Region** by default, **shared by all functions**. It can be raised to tens of thousands. New accounts can start lower and are raised automatically with use.
- **Requests-per-second limit** = **10 × concurrency quota** (10,000 RPS at the default 1,000). Very short functions (<100 ms) can hit the RPS limit before the concurrency limit.
- **Scaling rate** per function: up to **1,000 new execution environments every 10 seconds** (or +10,000 RPS every 10 s). Each function scales independently.
- When the quota or reserved limit is reached, extra requests are **throttled** (`TooManyRequestsException`, HTTP **429**).
- What happens on throttling depends on the invocation type:
  - **Synchronous**: the caller gets the 429 and must retry (API Gateway returns 429/502 to the client; the SDK retries with backoff).
  - **Asynchronous**: Lambda keeps the event and **retries up to 6 hours** (max event age), then drops it to the DLQ/destination.
  - **Kinesis/DynamoDB ESM**: the poller retries the batch. The shard waits, so **IteratorAge rises**. No data is lost until the record expires.
  - **SQS ESM**: the message returns to the queue after the visibility timeout. It can reach the DLQ if `maxReceiveCount` is low.
- **Metrics**: `ConcurrentExecutions`, `UnreservedConcurrentExecutions`, `ClaimedAccountConcurrency`, `Throttles`, `ProvisionedConcurrencyUtilization`, `ProvisionedConcurrencySpilloverInvocations` (verify the full list).

## B. Reserved concurrency
- **Reserved concurrency** sets **both a guarantee and a cap** for one function:
  - Guarantee: that many units are **set aside** only for this function, and no other function can use them.
  - Cap: the function can **never** scale above that number, even if the account has spare concurrency.
- **Free**: no extra charge.
- Lambda always keeps **100 units unreserved** for functions without reservations. With the default 1,000 quota you can reserve up to **900** in total.
- Uses:
  - Protect a **critical** function from being starved by others.
  - **Throttle on purpose** to protect a downstream system (a database with 100 connections → reserved concurrency 50).
  - **Emergency stop**: reserved concurrency = **0** throttles every invocation (the console's "Throttle" button does this).
- Trap: reserved concurrency set too low causes throttles even when the account has spare capacity.
- Trap: reserving lots of concurrency for idle functions wastes capacity that other functions can't use.

## C. Provisioned concurrency
- **Provisioned concurrency (PC)** = a number of environments **pre-initialized and kept warm**. No cold start for requests up to that number.
- Set on a **published version or alias**, not `$LATEST`.
- **Costs money**: you pay for the PC allocation (GB-s) while it is enabled, plus a lower duration price for invokes that run on it. The free tier does not apply.
- Above the PC level, the function **spills over** to on-demand concurrency (with cold starts), unless reserved concurrency caps it.
- PC counts toward the account quota. You **cannot** set more PC than reserved concurrency on the same function.
- Allocation takes a minute or two. Lambda can allocate up to **6,000 environments per minute** per function. Requests can't use the new PC until allocation finishes.
- Even with PC, environments are recycled in the background. A rare cold start is still possible after an error resets an environment.
- **Application Auto Scaling** can scale PC:
  - **Scheduled** (for example, raise PC at 08:00 on weekdays).
  - **Target tracking** on `LambdaProvisionedConcurrencyUtilization` (for example, keep it at 70%).
- Init code runs when PC is allocated, not per request. The `AWS_LAMBDA_INITIALIZATION_TYPE` environment variable is `provisioned-concurrency` there.
- **PC vs SnapStart**:
  - PC = guaranteed warm, lowest latency, costs money, any runtime.
  - SnapStart = cheaper or free, faster restores, supported runtimes only (Java/Python/.NET).
  - You **cannot use both** on the same version.

## D. Comparing the concurrency controls
| Control | What it does | Cost | Cold starts |
|---|---|---|---|
| None (on-demand) | Shares the unreserved pool | Pay per use | Yes |
| Reserved concurrency | Guarantees and caps a slice of the pool | Free | Yes |
| Provisioned concurrency | Keeps N environments initialized | Extra charge | No (up to N) |
| SQS ESM max concurrency | Caps how many invokes one queue drives | Free | Yes |
| SnapStart | Restores from a snapshot instead of running Init | Free (Java) / small fee (Python, .NET) | Faster restore |

## E. Cold start reduction checklist
- Keep the deployment package **small**. Include only the needed libraries (tree-shake/bundle for Node.js, strip unused Python packages).
- Do heavy setup **once** in Init (outside the handler) and reuse it on warm calls. Lazy-load things that only some paths need.
- Choose a runtime that starts fast (Python, Node.js) for latency-critical paths. Use **SnapStart** for Java/Python/.NET.
- Use **provisioned concurrency** for strict latency SLAs or predictable peaks.
- More memory also speeds up Init (more CPU).
- **arm64** often has similar or better start times at a lower price.
- Avoid big frameworks in latency-sensitive functions (Spring without SnapStart, heavy ML imports).
- Cold starts matter for **user-facing sync APIs**. They rarely matter for async/batch data processing.

## F. Memory, CPU and duration tuning
- Duration cost = **memory (GB) × duration (s)**. Doubling memory **halves the time** for CPU-bound code, so the **cost stays the same** while the function runs **twice as fast**.
- I/O-bound functions (waiting on S3, APIs or a DB) gain little from more memory. Lower memory may be cheapest.
- **AWS Lambda Power Tuning** (an open-source Step Functions tool) runs your function at many memory sizes and plots cost vs speed.
- **AWS Compute Optimizer** gives memory recommendations for Lambda from real usage.
- Above 1,769 MB the function has more than 1 vCPU. Use **multithreading / multiprocessing** to use them (Python `concurrent.futures`, Node.js worker threads).
- Reuse **connections** (HTTP keep-alive is on by default in recent SDKs) and **SDK clients** across invocations.
- Batch work: process many records per invoke (larger ESM batch sizes) to spread fixed overhead.
- Don't sleep or poll in Lambda while you pay per ms. Use Step Functions waits, EventBridge Scheduler or durable function waits.
- Stream big S3 objects (ranged GETs) instead of loading everything into memory.
- Use **S3 Select** only on older accounts (closed to new customers). Otherwise use Athena, or read Parquet columns directly with pyarrow.

## G. Protecting downstream systems
- Lambda can scale faster than a database or third-party API can handle. Common controls:
  - **Reserved concurrency** on the function = a hard cap on parallel calls.
  - **SQS buffer** between producer and Lambda, plus ESM **maximum concurrency**.
  - **RDS Proxy** pools and reuses DB connections across many Lambda environments. It also handles failover faster and supports IAM auth / Secrets Manager.
  - **Aurora / RDS Data API**: HTTP-based SQL with no connection to manage (Aurora Serverless v2 and provisioned Aurora; verify engines).
  - **API rate limits**: token bucket in DynamoDB/ElastiCache, or exponential backoff with jitter.
- DynamoDB is a natural fit for Lambda (HTTP, no connection limits). Watch WCU/RCU throttling with on-demand vs provisioned capacity.
- **Batching writes**: `BatchWriteItem`, Kinesis `PutRecords`, Firehose `PutRecordBatch` to cut call counts.

## H. Idempotency and duplicate handling
- Duplicates are normal: async retries, ESM at-least-once delivery, client retries on sync timeouts, SQS visibility timeouts.
- Make processing **idempotent**:
  - Use a natural key or event ID.
  - Use **conditional writes** (`attribute_not_exists`) in DynamoDB.
  - Use `MERGE`/upserts in SQL.
  - Use deterministic S3 keys (overwriting is harmless).
- **Powertools for AWS Lambda** (Python, TypeScript, Java, .NET) gives ready utilities:
  - **Idempotency** (DynamoDB-backed record of processed keys with TTL).
  - **Batch processing** (partial batch responses for SQS/Kinesis/DynamoDB).
  - **Logger** (structured JSON logs), **Metrics** (CloudWatch EMF), **Tracer** (X-Ray), parameters/secrets helpers, event parsing and validation.
- **Stateless vs stateful**: Lambda is stateless. Keep state in DynamoDB/S3/Step Functions. **Tumbling windows** (streams) and **durable functions** are the built-in stateful options.

## I. Lambda in a VPC
- By default a function runs in a **Lambda-managed VPC** with **internet access** and access to public AWS endpoints. It **cannot** reach private resources in your VPC (RDS, ElastiCache, private EC2, MSK).
- **VPC-attached function**: you choose **private subnets and security groups**. Lambda creates **Hyperplane ENIs** for that **subnet + SG combination**.
- One Hyperplane ENI is **shared by all functions** using the same subnet + SG combination, and supports up to **65,000 connections/ports**. Lambda adds more as needed.
- ENIs are created when the function is **created or updated** (state **Pending**, can take minutes), **not per invocation**. So VPC no longer adds big cold-start delays.
- If a VPC function is **idle for 14 days**, Lambda reclaims the ENIs and the function becomes **Inactive**. The next invoke fails, and the function re-enters Pending while the ENI is recreated.
- Removing VPC config can take up to **20 minutes** to delete the ENI.
- The execution role needs ENI permissions: managed policy **`AWSLambdaVPCAccessExecutionRole`** (`ec2:CreateNetworkInterface`, `DescribeNetworkInterfaces`, `DeleteNetworkInterface`, `AssignPrivateIpAddresses`, `UnassignPrivateIpAddresses`, `DescribeSubnets`).
- **Internet access from a VPC function**:
  - Put the function in **private subnets** with a route to a **NAT gateway**.
  - Putting it in a **public subnet does NOT give internet access**, because Lambda ENIs never get public IPs.
- **AWS services from a VPC function** without NAT: use **VPC endpoints**:
  - **Gateway endpoints**: S3, DynamoDB (free).
  - **Interface endpoints**: Secrets Manager, SQS, SNS, KMS, STS, CloudWatch Logs, Glue, Kinesis… (hourly + per GB).
- Use subnets in **at least 2 AZs** for availability.
- **Security groups**:
  - The Lambda SG needs **outbound** rules to the target (for example, port 5432 to the RDS SG).
  - The target's SG must allow **inbound from the Lambda SG**.
- IPv6: outbound IPv6 is supported in **dual-stack subnets** (opt-in). Not in IPv6-only subnets. Not for non-VPC functions.
- Lambda can't attach directly to a VPC with **dedicated tenancy**. Peer it to a default-tenancy VPC.
- **Cross-account VPC**: a function can be attached to subnets **shared** with it via RAM, or reach other VPCs through peering / Transit Gateway (verify current cross-account attachment support).
- IP planning: Hyperplane uses few IPs, but each **subnet + SG combination** needs addresses. Keep enough free IPs in the subnets. The ENI quota is **3,000 per VPC** by default.
- **Governance** condition keys: `lambda:VpcIds`, `lambda:SubnetIds`, `lambda:SecurityGroupIds`. For example, deny creating functions that are not VPC-attached.
- Least privilege: deny the function **code** from calling the EC2 ENI APIs using the `lambda:SourceFunctionArn` condition. Lambda the service still manages the ENIs.
- **Only attach to a VPC when needed** (to reach private resources). It adds NAT/endpoint cost and complexity.

## J. Networking performance notes
- Default bandwidth per environment: **625 Mbps**. Non-VPC functions can request an increase that scales with memory (up to about 3 Gbps at 10 GB).
- For high S3 throughput, use **parallel ranged GETs / multipart uploads** across threads.
- Through NAT gateways, watch **NAT per-GB processing** cost and the NAT's port limits (55,000 simultaneous connections per destination; verify).
- Keep the function in the **same Region** as its data. Cross-Region calls add latency and data transfer cost.

## Scenarios (if → then, because)
- **If** a function takes **0.2 s** and receives **6,000** requests per second, **then** it needs about **1,200** concurrency, so request a **quota increase** above the default **1,000**. **This works because** concurrency = requests per second × average duration (6,000 × 0.2 = 1,200), and the default quota of 1,000 per Region is shared by all functions; requests above it are throttled with HTTP 429.
- **If** a **20 ms** function at **30,000** requests per second throttles even though concurrency is only **600**, **then** the **requests-per-second (RPS) limit** is the problem: request a concurrency quota of **3,000+**. **This works because** the RPS limit is **10 × the concurrency quota** (10,000 RPS at the default 1,000). Very short functions hit the RPS limit before the concurrency limit, and a quota of 3,000 allows 30,000 RPS.
- **If** a reporting function uses all account concurrency and the order API starts throttling, **then** set **reserved concurrency** on the order API, and/or cap the reporting function with its own reserved concurrency. **This works because** reserved concurrency is both a **guarantee** (units set aside only for that function) and a **cap** (it never scales above it), and it is free. Without it, all functions share one pool, so one busy function can starve the others.
- **If** a Lambda fed by Amazon Simple Queue Service (SQS) opens too many database connections, **then** limit it with **reserved concurrency** or the event source mapping (ESM) **maximum concurrency**, **plus Amazon RDS Proxy**. **This works because** the limits cap how many environments run at once (each may hold a connection), and RDS Proxy pools and reuses connections across many Lambda environments.
- **If** a public API needs steady low latency at **9am every weekday**, **then** use **provisioned concurrency** with **scheduled Application Auto Scaling** (or **target tracking** on `LambdaProvisionedConcurrencyUtilization`). **This works because** provisioned concurrency keeps environments initialized and warm, so there are no cold starts up to that number, and the schedule raises it before the peak and lowers it after. The catch: you pay while it is on, and allocation takes a minute or two.
- **If** a Java API has **6-second** cold starts and the budget is tight, **then** use **Lambda SnapStart**, not provisioned concurrency. **This works because** SnapStart resumes new environments from a snapshot taken after Init, which removes most of the startup time, and it is **free for Java**, while provisioned concurrency costs money as long as it is enabled. You cannot use both on the same version.
- **If** you must stop a misbehaving async function right now, **then** set its **reserved concurrency to 0** (the console's **Throttle** button). **This works because** a reserved concurrency of 0 throttles every invocation, an emergency stop.
- **If** throttled async events must not be lost, **then** know that Lambda keeps them and **retries for up to 6 hours** (the maximum event age), and add an **on-failure destination** to catch the ones that still fail. **This works because** on throttling Lambda retries with backoff until the event is too old, then drops it unless a destination or dead-letter queue (DLQ) receives it.
- **If** Amazon Kinesis Data Streams processing lags because the function is throttled, **then** raise its **reserved concurrency** or the **account quota**, then raise the **ParallelizationFactor**. **This works because** a throttled batch is retried while the shard waits, so **IteratorAge** rises; Kinesis concurrency = shards × parallelization factor, and that needs enough concurrency to run.
- **If** a CPU-heavy transform costs too much at **512 MB**, **then** run **AWS Lambda Power Tuning** to test memory sizes. **This works because** you pay **memory × duration**, and more memory gives more CPU, so a larger size often cuts the run time enough to lower total cost. Power Tuning runs the function at many sizes and plots cost against speed.
- **If** a function at **4 GB** is no faster than at **2 GB**, **then** the code is **single-threaded**: add multithreading or multiprocessing, or keep the smaller size. **This works because** above **1,769 MB** the function gets more than 1 vCPU, and single-threaded code uses only one.
- **If** a function attached to a Virtual Private Cloud (VPC) times out calling an external API, **then** its **private subnets** have no route to a **Network Address Translation (NAT) gateway**; add one. **This works because** a VPC function reaches the internet only through NAT. A **public subnet does not help**, because Lambda network interfaces never get public IP addresses.
- **If** a VPC-attached function must read Amazon S3 cheaply with no internet, **then** add an **S3 gateway endpoint**. **This works because** gateway endpoints (S3 and DynamoDB) give private access to the service for **free**, so no NAT gateway or its per-GB cost is needed.
- **If** a VPC-attached function cannot get its secrets, **then** add an **AWS Secrets Manager interface endpoint** (or a NAT gateway) and allow **HTTPS** in the security groups (SGs). **This works because** without internet access the function needs an interface endpoint to reach Secrets Manager, and the security groups must let that traffic through. Interface endpoints cost per hour and per GB.
- **If** a function must reach an Amazon Relational Database Service (RDS) instance in a private subnet, **then** attach the function to the **VPC** (private subnets and a **Lambda security group**) and allow **inbound from the Lambda SG** on the database's security group. **This works because** by default a function runs in a Lambda-managed VPC and cannot reach private resources; once attached, Lambda creates network interfaces in your subnets. The Lambda SG also needs an **outbound** rule to the database port (for example 5432), and the role needs `AWSLambdaVPCAccessExecutionRole`.
- **If** a rarely used VPC function fails on its first call after weeks, **then** it became **Inactive** after **14 idle days**. **This works because** Lambda reclaims the function's network interfaces (Hyperplane ENIs) after 14 idle days; the next invoke fails while the function goes back to **Pending** and the ENI is recreated. Retry, or keep the function in use.
- **If** governance requires every function to run in approved VPCs, **then** use Identity and Access Management (IAM) policies or **service control policies (SCPs)** with the `lambda:VpcIds` / `lambda:SubnetIds` condition keys. **This works because** these keys let a policy deny creating functions that are not attached to the allowed VPCs or subnets.
- **If** retries cause duplicate charges to customers, **then** make the processing **idempotent**, for example with the **Powertools for AWS Lambda idempotency utility** backed by an Amazon DynamoDB table. **This works because** duplicates are normal (async retries, at-least-once event source mappings, client retries), and the utility records processed keys (with a TTL) so a repeated event is not processed twice.
- **If** a stream batch should keep its successful records and retry only from the failure, **then** use the **Powertools batch processor** with **ReportBatchItemFailures**. **This works because** the function reports the first failed record, so Lambda checkpoints before it and retries from there instead of the whole batch (for Amazon SQS, only the failed messages return to the queue).
- **If** a function checks an external job's status every **30 s** for an hour, **then** move the waiting into **AWS Step Functions** (a **Wait** state or **callback**) or **Lambda durable functions**. **This works because** Lambda bills per millisecond, so sleeping or polling inside a function pays for idle time; Step Functions waits and durable function waits suspend without compute charges.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: concurrency formula, account quota 1,000, 100 units always unreserved, RPS = 10 × concurrency, scaling rate 1,000 per 10 s per function, reserved vs provisioned concurrency behavior and table, PC allocation rate (6,000/min), PC and SnapStart can't be combined, VPC attachment (Hyperplane ENIs shared per subnet+SG, 65,000 connections, Pending state, 14-day Inactive, 20-minute removal, required permissions, NAT needed, public subnet gives no internet, IPv6 dual-stack, dedicated tenancy limit, condition keys, SourceFunctionArn deny pattern), network bandwidth 625 Mbps, ENI quota 3,000 per VPC.
Not confirmed (verify): full list of concurrency metric names, Data API engine support, cross-account VPC attachment specifics, NAT port limit figure.

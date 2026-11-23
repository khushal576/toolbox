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
- If a function takes 0.2 s and receives 6,000 req/s → it needs about 1,200 concurrency. Request a quota increase above the default 1,000.
- If a 20 ms function at 30,000 req/s throttles even though concurrency is only 600 → the RPS limit (10 × concurrency quota) is hit. Request a concurrency quota of 3,000+.
- If a reporting function uses all account concurrency and the order API starts throttling → reserved concurrency for the order API (guarantee), and/or cap the reporting function.
- If an SQS-driven Lambda opens too many DB connections → reserved concurrency / ESM maximum concurrency **plus RDS Proxy**.
- If a public API needs consistent low latency at 9am every weekday → provisioned concurrency with scheduled Application Auto Scaling (or target tracking on utilization).
- If a Java API has 6-second cold starts and budget is tight → SnapStart (free for Java), not provisioned concurrency.
- If you must stop a misbehaving async function right now → set reserved concurrency to 0 (the Throttle button).
- If throttled async events must not be lost → they are retried for up to 6 hours. Add an on-failure destination to catch the rest.
- If Kinesis processing lags because the function is throttled → raise reserved concurrency or the account quota, then raise ParallelizationFactor.
- If a CPU-heavy transform costs too much at 512 MB → run Power Tuning. A larger memory size often lowers total cost by cutting duration.
- If a function at 4 GB is no faster than at 2 GB → the code is single-threaded. Add parallelism or keep the smaller size.
- If a VPC-attached function times out calling an external API → no NAT gateway route from its private subnets (a public subnet won't help).
- If a VPC-attached function must read S3 cheaply with no internet → add an S3 gateway endpoint.
- If a VPC-attached function can't get secrets → add a Secrets Manager interface endpoint (or NAT) and allow HTTPS in the SGs.
- If a function must reach an RDS instance in a private subnet → attach it to the VPC (private subnets, Lambda SG) and allow the Lambda SG inbound on the DB SG.
- If a rarely used VPC function fails on its first call after weeks → it went Inactive after 14 idle days. The next call re-creates the ENI. Retry, or keep it warm.
- If governance requires all functions to run in approved VPCs → IAM/SCP with `lambda:VpcIds` / `lambda:SubnetIds` conditions.
- If retries cause duplicate charges to customers → idempotency (Powertools idempotency utility with a DynamoDB table).
- If a stream batch should keep successful records and retry only failed ones → Powertools batch processor + ReportBatchItemFailures.
- If a function polls an external job status every 30 s for an hour → move the wait to Step Functions (Wait state / callback) or durable functions to stop paying for idle time.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: concurrency formula, account quota 1,000, 100 units always unreserved, RPS = 10 × concurrency, scaling rate 1,000 per 10 s per function, reserved vs provisioned concurrency behavior and table, PC allocation rate (6,000/min), PC and SnapStart can't be combined, VPC attachment (Hyperplane ENIs shared per subnet+SG, 65,000 connections, Pending state, 14-day Inactive, 20-minute removal, required permissions, NAT needed, public subnet gives no internet, IPv6 dual-stack, dedicated tenancy limit, condition keys, SourceFunctionArn deny pattern), network bandwidth 625 Mbps, ENI quota 3,000 per VPC.
Not confirmed (verify): full list of concurrency metric names, Data API engine support, cross-account VPC attachment specifics, NAT port limit figure.

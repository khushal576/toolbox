# Amazon API Gateway – 3. WebSocket, deployment, streaming, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. WebSocket APIs
- **WebSocket API** = a **persistent two-way** connection. The server can **push** to the client without a request (chat, live dashboards, notifications, streaming status).
- Messages in JSON are routed by a **route selection expression**, for example `${request.body.action}`. The value is matched to a **route key**.
- **Predefined routes**:
  - **`$connect`**: called when the connection starts. **Authorization happens here** (IAM, Lambda authorizer; not per message). Return non-2xx to reject.
  - **`$disconnect`**: called when the client or server disconnects (best effort, cannot block).
  - **`$default`**: used when no route matches, or the message is **not JSON**.
  - **Custom routes**: any other route key (`sendMessage`, `joinRoom`).
- Integrations: Lambda, HTTP, AWS services, mock, VPC link.
- **State is yours**: API Gateway gives each client a **connection ID**. Store it (usually **DynamoDB**) on `$connect`, delete it on `$disconnect`.
- **Pushing to clients** from the backend: call the **`@connections` management API**:
  - URL: `https://{api-id}.execute-api.{region}.amazonaws.com/{stage}/@connections/{connectionId}`.
  - **POST** sends a message, **GET** returns connection info, **DELETE** disconnects the client.
  - Caller needs IAM permission **`execute-api:ManageConnections`**.
  - A stale connection returns **410 Gone** → remove the ID from your table.
- Alternatively use an integration with a **route response** to answer the sender.
- **Binary media types are not supported** (status 1003). Send text/JSON (or base64 inside JSON).
- Close codes: **1001** (idle 10 min or 2 h limit), **1003** (binary), **1008** (too many requests), **1009** (message too big), **1011** (internal error).
- WebSocket limits (typical): idle timeout **10 minutes**, max connection **2 hours**, message **128 KB**, frame **32 KB** **(verify)**. Clients should send **pings** or reconnect.
- **Cost**: per message (32 KB increments) + per connection-minute (see section D).
- Alternatives: **AWS AppSync** (GraphQL subscriptions), **IoT Core** (MQTT), **SNS/SQS + polling**. WebSocket API is for custom protocols and Lambda-based messaging.

## B. Deployments, stages and releases
- **REST**: you must **create a deployment** to publish changes to a **stage**. Rollback = redeploy a previous deployment to the stage.
- **HTTP**: **auto-deploy** per stage (`$default` stage), no manual deployments.
- **Stage settings** (REST): logging, metrics, tracing, throttling, cache, WAF, client certificate, canary, stage variables, **tags**.
- **Stage variables** let one API definition point to different backends (for example Lambda **alias** `prod`/`dev`). You must give API Gateway permission for each alias/function.
- **Canary release (REST)**:
  - Add **canary settings** to a stage: a canary **deployment ID**, **`percentTraffic`** (0.0–100.0), **stage variable overrides**, **`useStageCache`**.
  - Traffic is split at random between the base release and the canary.
  - Canary has **its own CloudWatch logs and metrics** (log group suffix `/Canary`).
  - **Promote** the canary (it becomes the stage's deployment) or **delete** it to roll back.
  - While a canary exists, the stage cannot take another normal deployment.
  - Not available on HTTP APIs.
- **Blue/green alternative**: two stages or two APIs + custom domain **API mappings** or Route 53 weighted records.
- Infra as code: **CloudFormation/SAM/CDK** (`AWS::ApiGateway::*` for REST, `AWS::ApiGatewayV2::*` for HTTP/WebSocket; SAM `AWS::Serverless::Api` and `HttpApi`). In CloudFormation, REST **Deployment** resources need a trigger (such as a changing logical ID or `AutoPublishAlias`/SAM) or changes are not redeployed.
- **Export/import** with **OpenAPI 3** or Swagger. **SDK generation** for clients (REST).
- **Documentation** parts, versioned, can be published with the API (REST).

## C. REST response streaming and large payloads
- Default payload cap is **10 MB** request and response. Timeout default **29 s**.
- **Response streaming** (REST only): set the integration **response transfer mode** to **`STREAM`** (default `BUFFERED`).
  - Works only for **`HTTP_PROXY`** and **`AWS_PROXY`** (Lambda proxy, private integrations through HTTP proxy).
  - Supports **all REST endpoint types**.
  - Up to **15 minutes** per stream. **Idle timeout** is **5 min** (Regional/private) or **30 s** (edge-optimized).
  - Exceeds the **10 MB** and **29 s** limits. First **10 MB** has no bandwidth limit; after that **2 MB/s**.
  - **Not supported with streaming**: **caching**, **content encoding (compression)**, **VTL response transformation**. Request streaming is **not supported**.
  - Use cases: gen-AI chat (low time-to-first-byte), SSE progress updates, big files without pre-signed URLs.
  - Lambda may keep running after a client/gateway timeout.
  - Billed per 10 MB increment of response (see section D).
- Other ways for big data: **S3 pre-signed URLs** (upload/download direct), **multipart upload** by the client, **CloudFront** for downloads, **asynchronous pattern** (return 202 + job ID, poll status).
- **Long-running work** (over 29 s): return **202 Accepted** and process through **SQS/Step Functions/Lambda async**, or use **Step Functions Standard** + callback. Raising the integration timeout (Regional/private REST only) may need a **lower account throttle** limit.
- **Compression**: REST can compress responses (enable with a minimum size) when the client sends `Accept-Encoding`.

## D. Cost
- **Pay per request**; no minimum, no upfront (prices are us-east-1 examples; check your Region).
- **HTTP API**: **$1.00 per million** for the first 300 million per month, then **$0.90** per million. Requests are metered in **512 KB** increments **(verify)**.
- **REST API**: **$3.50 per million** for the first 333 million, **$2.80** for the next 667 million, **$2.38** beyond. Metered in 512 KB increments **(verify)**.
- **Private REST API**: **$3.50 per million** requests, **no data transfer out charge**, plus **PrivateLink** (**$0.01 per AZ per hour** per VPC endpoint and **$0.01 per GB**).
- **WebSocket**: **$1.00 per million messages** (32 KB increments, max 128 KB; ping/pong not metered) + **$0.25 per million connection minutes**.
- **Response streaming**: **$3.50 per million** requests, billed per **10 MB** (rounded up; a 65 MB response = 7 requests). Data transfer applies.
- **Cache** (REST): billed **per hour** by size (for example **$0.038/hour for 1.6 GB**); not in the free tier; billed while provisioned even with no traffic. Cache is a fixed cost: only worth it with real hit ratios.
- **Data transfer out** to the internet: standard AWS rates (for example **$0.09/GB** for first tiers). Data into AWS is free. Cross-Region and cross-AZ rules apply to private integrations.
- **Not billed** (REST): requests that fail authentication/authorization before reaching the method (for example failed IAM/Cognito/Lambda authorizer checks) **(verify)**. Throttled (429) requests are **not billed** **(verify)**. Lambda authorizer function invocations **are** billed by Lambda.
- **Free tier** (new customers, 12 months): **1M REST calls, 1M HTTP calls, 1M WebSocket messages, 750,000 connection minutes** per month. Newer accounts also get up to **$200 credits**; a free plan lasts 6 months.
- **Portals** (developer portal): **$125 per month** (includes 10 portal products, up to 40 REST endpoints each); extra products **$12.50/month**.
- **Related costs**: Lambda duration, CloudWatch Logs ingestion/storage (execution logging at INFO is expensive at scale), X-Ray, WAF, CloudFront, VPC endpoints, NAT.
- **Cost cutting**:
  - Use **HTTP API** when REST-only features are not needed.
  - Use **AWS service integrations** instead of Lambda "glue" functions.
  - Enable **caching** (or CloudFront) for repeated reads, but size it correctly.
  - Add **request validation** so bad calls never reach Lambda.
  - Lower **log level** (ERROR) and set **log retention**; use sampling.
  - Use **Lambda authorizer caching** (higher TTL) to cut authorizer invocations.
  - Delete unused stages/caches. Use **WAF rate rules** and **Budgets** against abuse (usage plans are best effort).
  - Prefer **Regional + your own CloudFront** only when you need CloudFront features; edge-optimized has no extra API Gateway fee.

## E. Monitoring, logging and troubleshooting
- **CloudWatch metrics** (1-minute, kept 15 months). Dimensions: `ApiName`, `Stage` (and `Resource`/`Method` with **detailed metrics**; HTTP uses `ApiId`, `Route`).
  - **`Count`**: number of API requests.
  - **`4XXError`** / **`5XXError`**: client / server error counts (REST names; HTTP API uses `4xx`, `5xx`).
  - **`Latency`**: time from receiving the request to returning the response (**includes** API Gateway overhead).
  - **`IntegrationLatency`**: time the **backend** took. `Latency − IntegrationLatency` ≈ API Gateway overhead (authorizers, mapping, etc.).
  - **`CacheHitCount`** / **`CacheMissCount`** (REST caching).
  - WebSocket: `ConnectCount`, `MessageCount`, `IntegrationError`, `ClientError`, `ExecutionError`.
- **Alarm** on `5XXError` rate, `Latency` p99, `Count` drops (and throttles through `4XXError` spikes).
- **Execution logs** (REST, CloudWatch Logs): request/response and mapping detail, log level **ERROR** or **INFO**, optional **full request/response data (do not enable in production: leaks data)**. Needs an **account-level CloudWatch Logs role** (`AmazonAPIGatewayPushToCloudWatchLogs`) set in API Gateway settings.
- **Access logs** (REST and HTTP): one line per request in a format you choose (JSON common), with `$context.*` variables such as `requestId`, `identity.sourceIp`, `status`, `responseLatency`, `integrationLatency`, `authorizer.error`. Destination: **CloudWatch Logs**, or **Amazon Data Firehose** (REST only).
- Access log template max size **3 KB**.
- **X-Ray tracing** (REST): trace API Gateway → Lambda → downstream. Also **Application Signals** options.
- **CloudTrail**: API Gateway **control-plane** actions (CreateRestApi, CreateDeployment, ...). Not invocations.
- **AWS Config** tracks API Gateway configuration. **Security Hub** controls check logging, caching encryption, WAF, TLS.
- **Dashboards** per API in the console (calls, latency, errors).
- **Symptom → cause → fix**:
  - **403 Missing Authentication Token** → wrong path/method or stage not deployed → check URL/stage and redeploy.
  - **403 Forbidden** → API key missing/invalid, authorizer denied, WAF/resource policy → check key header, policy, WAF logs.
  - **401 Unauthorized** → token missing/invalid → check identity source and authorizer.
  - **429** → throttle or quota → raise limits, add backoff, buffer.
  - **500/502** → authorizer error, Lambda error, bad proxy response format → check execution logs and Lambda logs.
  - **503** → backend/VPC link unavailable → check NLB/targets/security groups.
  - **504** → integration over timeout (29 s) → async pattern, speed up backend, adjust timeout, streaming.
  - **High Latency but low IntegrationLatency** → authorizer, VTL mapping, cache misses, edge hop, large payloads.
  - **Lambda cold starts** inflate latency → provisioned concurrency/SnapStart.
  - **Logs missing** → account CloudWatch role not set, log group/stage not configured.
  - **CORS errors** → missing CORS headers in the method or gateway responses.

## F. Limits and numbers (defaults; check adjustability)
- **Account throttle** per Region: **10,000 RPS**, **5,000 burst** (some newer Regions 2,500 / 1,250). RPS adjustable; burst set by AWS.
- **Payload size**: **10 MB** (not adjustable; streaming can exceed on responses).
- **Integration timeout** (REST): **50 ms – 29 s**. Raisable for **Regional** and **private** APIs (may reduce account throttle); **not** for edge-optimized.
- **HTTP API max integration timeout**: **30 s** (fixed).
- **Header size**: REST **20,480 bytes** total (private API **8,000**); HTTP request line + headers **10,240 bytes**.
- **URL length**: edge **8,192**, Regional **10,240**, private **8,192** characters.
- **Idle connection timeout** (REST): **310 s**.
- **REST quotas**: Regional APIs **600** per Region, edge-optimized **120**, private **600** per account per Region (not adjustable); resources per API **300** (adjustable); stages per API **10** (adjustable); stage variables **100**; authorizers per API **10**; VPC links **20** (adjustable); usage plans **300**; API keys **10,000**; usage plans per key **10**; client certificates **60** (generated, adjustable), ACM client certs 500; mapping template **300 KB**; model **400 KB**; import file **6 MB**; cache TTL **0–3,600 s**, cached response **1 MB**.
- **HTTP quotas**: routes **300** (adjustable); integrations **300**; stages **10**; authorizers **10**; **VPC links 10** and **10 subnets** each; Lambda authorizer response **10 s**; JWKS timeout **1,500 ms**; log entry **1 MB**.
- **Management API rate limits** (not adjustable): CreateDeployment **1 per 5 s**, CreateRestApi **1 per 3 s** (edge **1 per 30 s**), CreateDomainName **1 per 30 s**, UpdateUsagePlan **1 per 20 s**, total control-plane operations **10 RPS** with burst 40. Automation (CI/CD) can hit **429 Too Many Requests** from the control plane.
- **Custom domains**: public **120**, private **50** per account per Region; multi-level API mappings **200** per domain.
- **WebSocket** (typical, verify): idle **10 min**, connection **2 h**, message **128 KB**, frame **32 KB**.

## G. Data-engineering patterns and exam mapping
- **Serverless data API**: client → API Gateway (auth, throttle, cache) → Lambda → DynamoDB/Athena/RDS Data API/S3. Use **pagination tokens** and **cache** hot queries.
- **Ingestion gateway**: producers → API Gateway → **Kinesis Data Streams/Firehose/SQS** (AWS integration), no Lambda. Add **WAF**, **API keys + usage plans** (per-producer rate limits), **request validation**.
- **Webhook intake**: API Gateway → SQS (buffer) → Lambda/Glue/Step Functions workers.
- **Async job API**: `POST /jobs` returns **202 + jobId** (Step Functions Standard or SQS); `GET /jobs/{id}` returns status; avoids the 29 s limit.
- **Transfer Family custom identity provider**: API Gateway (+ Lambda) as the IdP, protected with **WAF** and throttling.
- **Private data API**: Private REST API + interface endpoint + resource policy + VPC link to internal services.
- **Real-time updates**: WebSocket API + DynamoDB connection table + Lambda pushing with `@connections`.
- **Security best practice**: authorize every route (IAM/Cognito/JWT/Lambda), least privilege, WAF, TLS 1.2+, no secrets in API keys or stage variables, log with retention.
- **Exam skills**:
  - **1.2.8 Create data APIs**: API Gateway + Lambda/AWS integrations, REST vs HTTP, throttling, caching, validation.
  - **4.1.4 IAM roles**: API Gateway **execution role** for AWS service integrations, **Lambda resource policy** for invocation, IAM auth (`execute-api:Invoke`).
  - **3.x Monitoring**: CloudWatch metrics (`Count`, `Latency`, `IntegrationLatency`, `4XXError`, `5XXError`, cache metrics), access/execution logs, X-Ray, CloudTrail.
  - **1.2.4 Cost**: HTTP vs REST pricing, caching trade-off, direct service integrations.

## H. Scenarios: "If X → Y, because Z"
- **If** a chat or live-dashboard app needs the server to **push** messages, **then** use a **WebSocket API**. Store each client's **connection ID** in **Amazon DynamoDB** on `$connect`, delete it on `$disconnect`, and push with the **`@connections` management API** (needs `execute-api:ManageConnections`). **This works because** a WebSocket keeps a persistent two-way connection, so the server can send without a request, while REST cannot push. A stale connection returns **410 Gone**, so remove that ID.
- **If** a WebSocket client is dropped after **10 minutes** or **2 hours**, **then** this is expected: the client should send **pings** or **reconnect**. **This works because** a WebSocket API has a fixed idle timeout of 10 minutes and a maximum connection time of 2 hours (verify), shown by close code **1001**.
- **If** you need to release safely to **5%** of traffic, **then** add a **canary release** to the REST stage with `percentTraffic` set to 5. **This works because** the canary splits traffic at random between the base release and the canary, and the canary has its **own CloudWatch logs and metrics**. You then **promote** it or **delete** it. Not available on HTTP APIs.
- **If** you need a rollback, **then** **redeploy the previous deployment** to the stage, or **delete the canary** if one is running. **This works because** a stage points at a deployment (a snapshot of the API config), so pointing it back restores the old version.
- **If** a response must be bigger than **10 MB** or stream for minutes, **then** use **REST response streaming** (transfer mode `STREAM`, only for `HTTP_PROXY` and `AWS_PROXY` integrations), or an **Amazon S3 pre-signed URL**. **This works because** normal buffered responses are capped at **10 MB** and **29 s**, while a stream can run up to **15 minutes**. The catch: streaming does not support caching, compression or VTL response mapping, and after the first 10 MB bandwidth is **2 MB/s**.
- **If** processing takes more than **29 s**, **then** **return 202 Accepted** with a job ID and process **asynchronously** through Amazon SQS or AWS Step Functions; the client polls for status. **This works because** the default REST integration timeout is **29 s**, and the async pattern answers at once. Raising the timeout works only for Regional/private REST and may lower the account throttle.
- **If** you want to ingest events cheaply with no code, **then** use an API Gateway **AWS service integration** straight to **Amazon Kinesis Data Streams, Amazon SQS or Amazon Data Firehose**, with **mapping templates** to shape the request. **This works because** API Gateway calls the service API itself, so you skip Lambda cost and latency.
- **If** many producers each need their own rate limit, **then** use a **REST API** with **usage plans**, **API keys** and an **authorizer**. **This works because** only REST supports per-client throttling through usage plans; HTTP APIs throttle only per stage and route. The key identifies the producer; the authorizer does the real authentication.
- **If** the bill is dominated by API Gateway requests and you only use basic features, **then** **move to an HTTP API**. **This works because** HTTP APIs cost **$1.00 per million** requests versus **$3.50** for REST, about **70% cheaper** (verify), based on us-east-1 list prices. You cannot convert in place: create a new API (or export/import OpenAPI) and migrate.
- **If** the same GET requests repeat constantly, **then** add a **cache**: the REST **stage cache** or **Amazon CloudFront** in front. **This works because** cache hits are answered without calling the backend. The catch: the stage cache is a fixed hourly cost, so it pays only with real hit ratios.
- **If** Amazon CloudWatch Logs cost is large, **then** lower the execution log level to **ERROR**, **stop full request/response logging**, and set **log retention**. **This works because** INFO-level and full-body logs ingest a lot of data at scale, and ingestion and storage are billed.
- **If** the `Latency` metric is high but `IntegrationLatency` is low, **then** look at **authorizers, mapping templates, cache misses and payload size**. **This works because** `Latency` includes API Gateway's own overhead while `IntegrationLatency` is only the backend time, so the gap is spent inside API Gateway, not the backend.
- **If** a CI/CD pipeline gets **429** when deploying many APIs, **then** **slow down and retry**. **This works because** management (control-plane) API limits are fixed, for example **1 CreateDeployment per 5 s** and **10 requests/s** in total, and they cannot be raised.
- **If** you must audit who changed an API, **then** use **AWS CloudTrail**. **This works because** CloudTrail records control-plane calls such as CreateRestApi and CreateDeployment. It does not record request data; use **access logs** for that.
- **If** an API must reach a private Amazon Elastic Container Service (ECS) service, **then** use a **VPC link** to a **Network Load Balancer (NLB)** or **Application Load Balancer (ALB)** in front of it. **This works because** the VPC link lets API Gateway reach inside the Virtual Private Cloud (VPC) while the targets stay private.
- **If** you need to control cost from abusive callers, **then** use **AWS WAF rate-based rules** to block them and **AWS Budgets** to watch spend. **This works because** usage plans are **best effort** and are not a hard cost control, while WAF can block traffic by IP.

Verified from AWS docs on 2026-10-31 (pricing page, quotas pages, response streaming, throttling, caching, authorizers, WebSocket overview, canary).
Unconfirmed (verify): WebSocket quota values (idle 10 min, 2 h, 128 KB, 32 KB); request-size metering increments (512 KB) for HTTP/REST; whether throttled/unauthorized requests are billed; WebSocket and HTTP CloudWatch metric names and dimensions; CloudFormation REST deployment redeploy behaviors; the 237 GB max cache size referenced in file 2; "about 70% cheaper" is based on the us-east-1 list price.

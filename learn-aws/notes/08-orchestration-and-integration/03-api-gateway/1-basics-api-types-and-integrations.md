# Amazon API Gateway – 1. Basics, API types, endpoints and integrations

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **Amazon API Gateway** is a managed service to create, publish, secure, throttle, monitor and scale **HTTP/REST/WebSocket APIs** in front of backends.
- It is a **front door**, not compute. The work happens in the backend (Lambda, HTTP service, AWS service).
- Fully managed and serverless: no servers, scales automatically, pay per request.
- Pick it when:
  - You need a managed public API with auth, throttling, API keys, validation or caching.
  - You front **Lambda** with a real API (not just a function URL).
  - You need a **WebSocket** endpoint with managed connections.
  - You want to put an API directly in front of an AWS service (SQS, Kinesis, DynamoDB, Step Functions) with no code.
- Avoid it when:
  - You only need a quick HTTPS endpoint for one Lambda → **Lambda function URL** is simpler and free (no throttling, keys or validation).
  - You need long-lived, high-throughput or gRPC/raw TCP traffic → ALB/NLB.
  - Payloads are above **10 MB** (use S3 pre-signed URLs or REST response streaming).
- Data-engineering uses: data APIs over Athena/DynamoDB/S3 through Lambda, ingestion APIs into Kinesis/SQS/Firehose, webhook receivers, custom identity provider for Transfer Family.

## B. Three API types
- **REST API** (v1): the full-featured product. Highest price per request.
- **HTTP API** (v2): minimal features, **lower price** and lower latency. Supports OIDC/JWT.
- **WebSocket API**: two-way, stateful connections, routes selected from message content.
- (There is also a **REST API private** flavour via the Private endpoint type; see section C.)
- REST vs HTTP feature table (the exam favourite):

| Feature | REST API | HTTP API |
|---|---|---|
| Edge-optimized endpoint | Yes | No |
| Regional endpoint | Yes | Yes |
| Private endpoint | Yes | No |
| API keys + usage plans (per-client throttle/quota) | Yes | No |
| AWS WAF | Yes | No |
| Resource policies | Yes | No |
| Cache (stage cache) | Yes | No |
| Request validation | Yes | No |
| Request **body** transformation (VTL) | Yes | No |
| Request **parameter** mapping | Yes | Yes |
| Canary release | Yes | No |
| Mock integration | Yes | No |
| Custom gateway responses | Yes | No |
| X-Ray tracing | Yes | No |
| Execution logs | Yes | No |
| Access logs to **Firehose** | Yes | No (CloudWatch Logs only) |
| Response streaming | Yes | No |
| Test invoke in console | Yes | No |
| Backend client certificates | Yes | No |
| IAM auth | Yes | Yes |
| Lambda authorizer | Yes | Yes |
| Cognito | Authorizer type | Through a JWT authorizer |
| **JWT authorizer** | No (use a Lambda authorizer) | Yes |
| Mutual TLS (custom domain) | Yes | Yes |
| Private integration NLB / ALB | Yes / Yes **(verify ALB)** | Yes / Yes |
| Private integration Cloud Map | No | Yes |
| **Automatic deployments** | No | Yes (`$default` stage with auto-deploy) |
| Developer portal | Yes | No |

- Rule of thumb: **HTTP API unless you need a REST-only feature** (API keys, WAF, caching, private API, validation, body mapping, canary).
- HTTP API is about **70% cheaper** per request than REST (**$1.00 vs $3.50 per million**; see file 3).
- **Cannot convert** a REST API to an HTTP API in place. You create a new API (or export/import OpenAPI) and migrate.

## C. Endpoint types (REST APIs)
- **Edge-optimized** (default for REST):
  - Requests go to the nearest **CloudFront POP**, then to API Gateway in its home Region.
  - Good for geographically spread clients.
  - The CloudFront distribution is **owned by AWS** (you cannot manage it).
  - Capitalizes HTTP header names (for example `Cookie`). CloudFront sorts cookies.
  - A custom domain applies **across all Regions**. The ACM certificate must be in **us-east-1**.
  - Integration timeout **cannot be raised** for edge-optimized APIs.
- **Regional**:
  - For clients in the same Region (EC2, Lambda, other services) or a small number of clients.
  - Header names pass through unchanged.
  - A custom domain is **per Region**; ACM certificate in the **same Region**. Use Route 53 latency routing for multi-Region.
  - Want CloudFront features (WAF at the edge, caching, own certificate)? Use Regional + **your own CloudFront distribution**.
- **Private**:
  - Reachable only from a **VPC** through an **interface VPC endpoint** (`execute-api`, PrivateLink).
  - Controlled by a **resource policy** (allow specific VPCs / VPC endpoints / `aws:SourceVpce`).
  - No internet exposure. No data transfer out charges for private APIs, but PrivateLink charges apply (see file 3).
  - Can be reached from on premises over Direct Connect/VPN through the VPC endpoint.
  - Header size cap is smaller for private APIs: **8,000 bytes** vs 20,480.
- **HTTP APIs** are **Regional only**.
- You can **change** a REST API between Regional and Edge-optimized (not simply to/from Private without care **(verify)**).
- The default invoke URL `https://{api-id}.execute-api.{region}.amazonaws.com/{stage}` is always there unless you disable it (**disable default endpoint** when you only want the custom domain).

## D. Core building blocks (REST)
- **Resource** = a URL path part (`/orders`, `/orders/{id}`). A **method** = HTTP verb on a resource.
- **Method request** (what the client may send) → **Integration request** (what is sent to the backend) → **Integration response** → **Method response** (what the client gets). Non-proxy integrations configure all four.
- **Proxy resource** `{proxy+}` catches all child paths. `ANY` method catches all verbs. Together they pass everything to one backend (cuts resource count; limit is 300 resources per API).
- **Deployment** = a snapshot of the API config. **A change is not live until you deploy it to a stage.** (Top exam trap.)
- **Stage** = a named, deployed version (`dev`, `prod`). Each stage has its own invoke URL, logging, throttling, caching, WAF, canary, stage variables.
- **Stage variables**: key/value settings per stage (up to 100). Use them for Lambda alias or backend URL per stage (for example `${stageVariables.lambdaAlias}`). Not secrets.
- **Models / schemas** (JSON Schema) describe request and response bodies for validation and SDK generation.
- **OpenAPI / Swagger** import and export. Can import with API Gateway extensions (`x-amazon-apigateway-*`).
- **HTTP API stage**: `$default` stage + **auto-deploy** means changes go live without a manual deployment.
- HTTP API **routes** = `METHOD /path` (and `$default`). Integrations attach to routes.

## E. Integration types (REST)
- **Lambda proxy (`AWS_PROXY`)**:
  - Recommended for Lambda. API Gateway passes the whole request as an event; Lambda returns `{statusCode, headers, body}`.
  - No mapping templates. Lambda must return the right format or the client gets **502 Bad Gateway**.
- **Lambda custom (`AWS`)**: you write mapping templates for request and response. More control, more work.
- **HTTP proxy (`HTTP_PROXY`)**: pass request/response straight to a public HTTP backend.
- **HTTP custom (`HTTP`)**: with mapping templates.
- **AWS service integration (`AWS`)**:
  - Call AWS APIs directly (SQS `SendMessage`, Kinesis `PutRecord`, DynamoDB `PutItem`, Step Functions `StartExecution`, S3, SNS, EventBridge).
  - You supply an **IAM execution role** that API Gateway assumes, plus VTL mapping templates.
  - No Lambda needed → cheaper and faster.
- **Mock (`MOCK`)**: API Gateway answers itself. Used for CORS `OPTIONS`, tests, parallel frontend work.
- **VPC link / private integration**:
  - Reach resources **inside a VPC** without exposing them.
  - REST API **VPC link** targets a **Network Load Balancer**. HTTP API **VPC link** (V2) targets **ALB, NLB or Cloud Map** services.
  - REST ALB support through VPC links is newer **(verify)**.
  - VPC link needs subnets (and security groups for V2).
- **Integration timeout**: **50 ms – 29 s** default for Regional/private REST (Regional and private can request more with a possible lower account throttle; edge cannot). HTTP API max is **30 s**, fixed.
- Timeout hit → client gets **504 Gateway Timeout**.
- **Lambda throttled / bad response format** → 502 or 429. Bad backend response → **502**.
- **Lambda invoke permission**: API Gateway needs permission to call the function. Console adds the **resource-based policy** (`lambda:InvokeFunction`, principal `apigateway.amazonaws.com`, `aws:SourceArn`). With IaC you must add it yourself.

## F. Mapping templates and data transformation (REST)
- **Mapping templates** use **VTL (Velocity Template Language)** + `$input`, `$context`, `$util`, `$stageVariables`.
- Use cases: turn JSON into the shape an AWS service expects (SQS body, Kinesis `Data` base64, DynamoDB item), rename fields, remove fields, return a different response shape.
- **Passthrough behavior** when no template matches the `Content-Type`:
  - `WHEN_NO_MATCH`: pass the body through unchanged.
  - `WHEN_NO_TEMPLATES`: pass only if **no templates are defined at all**, else **415 Unsupported Media Type**.
  - `NEVER`: always **415** if no template for the content type.
- **Base64 and binary**: set **binary media types** on the API and content handling (`CONVERT_TO_BINARY`, `CONVERT_TO_TEXT`, passthrough) when moving images/files. Lambda proxy returns `isBase64Encoded: true`.
- Max mapping template size **300 KB**; `#foreach` iterations **1,000**.
- HTTP APIs only support **parameter mapping** (headers, query, path, stage vars), not body templates.
- Request **parameter mapping** (REST and HTTP): copy/override headers/query/path between method and integration request.

## G. Quick data-ingestion examples
- **Webhook → SQS**: API Gateway AWS integration → `SendMessage`. Decouples bursts, no Lambda cost, SQS absorbs spikes (API Gateway throttle protects it).
- **Producer → Kinesis Data Streams**: AWS integration → `PutRecord`. Mapping template builds `StreamName`, `Data`, `PartitionKey`.
- **Producer → Firehose**: AWS integration → `PutRecord(Batch)` → S3.
- **Client → API Gateway → Lambda → DynamoDB/Athena/S3**: classic serverless data API.
- **Large upload**: return an **S3 pre-signed URL** from the API; client uploads straight to S3 (bypasses the 10 MB payload cap).
- **API Gateway → Step Functions**: Express (sync) for quick responses, Standard (async) returns an execution ARN.
- **API Gateway → ALB/NLB via VPC link**: expose private containers/EC2 safely.

## H. Scenarios: "If X → Y, because Z"
- **If** you only need one public HTTPS endpoint for one AWS Lambda function, **then** use a **Lambda function URL** instead of Amazon API Gateway. **This works because** a function URL is simpler and **free**, with no extra service to run. The catch: it has no throttling, API keys or request validation.
- **If** you need a separate rate limit and quota for each customer, **then** use a **REST API** with **usage plans** and **API keys**. An API key identifies the client; a usage plan sets its throttle and its quota per day, week or month. **This works because** only REST APIs have API keys and usage plans; **HTTP APIs** (the cheaper, simpler type) lack both.
- **If** you need **AWS WAF** (Web Application Firewall, which blocks bad traffic) on the API, **then** use a **REST API**, or put **Amazon CloudFront** (the AWS content delivery network) with WAF in front of an HTTP API. **This works because** REST APIs support WAF per stage, but HTTP APIs do not support WAF directly.
- **If** the API must not be on the internet at all, **then** use a **Private REST API**. Clients reach it only from a **Virtual Private Cloud (VPC)** through an **interface VPC endpoint** (`execute-api`, AWS PrivateLink), and a **resource policy** says which VPCs or endpoints may call it. **This works because** the Private endpoint type is the only VPC-only type, and it exists only for REST APIs. On-premises clients can still reach it over Direct Connect or VPN through the VPC endpoint.
- **If** cost matters most and you only need JSON Web Token (JWT) auth with Lambda or HTTP backends, **then** use an **HTTP API**. **This works because** it costs **$1.00 per million** requests versus **$3.50** for REST, about **70% cheaper** (verify), based on us-east-1 list prices. Pick REST only when you need a REST-only feature such as API keys, WAF, caching or validation.
- **If** clients are spread around the world and you want low latency without managing CloudFront yourself, **then** use an **edge-optimized REST API** (the REST default). Requests go to the nearest **CloudFront Point of Presence (POP)**, then to API Gateway in its home Region. **This works because** AWS builds in and owns that CloudFront distribution. The catch: you cannot manage it, and a custom domain needs its AWS Certificate Manager (ACM) certificate in **us-east-1**.
- **If** clients are in the same Region (for example internal services on EC2 or Lambda), **then** use a **Regional** endpoint. **This works because** requests go straight to API Gateway and skip the CloudFront hop of an edge-optimized endpoint.
- **If** you change a REST API's configuration and nothing happens, **then** **create a deployment** to the stage. **This works because** a deployment is a snapshot of the config, and a change is **not live until you deploy it** to a stage. HTTP APIs with the `$default` stage and **auto-deploy** do not have this problem.
- **If** the client gets **502 Bad Gateway** from a **Lambda proxy** integration (`AWS_PROXY`), **then** check that the function returns the right **response format**: `statusCode`, `headers` and `body`. **This works because** in proxy mode there are no mapping templates, so API Gateway passes the Lambda result straight through and rejects a malformed response with 502.
- **If** the client gets **504 Gateway Timeout**, **then** the integration took longer than the timeout (**29 s** default for REST). Make the work **asynchronous** (return 202 and use Amazon SQS or AWS Step Functions), speed up the backend, use **REST response streaming**, or request a higher timeout. **This works because** 504 always means the timeout was hit. The catch: only Regional and private REST APIs can raise the timeout (maybe with a lower account throttle); edge-optimized cannot, and HTTP APIs are fixed at **30 s**.
- **If** you want to send records to Amazon Kinesis or Amazon SQS with no code, **then** use an **AWS service integration** with a **mapping template** (written in Velocity Template Language, VTL) that builds the request, for example `StreamName`, `Data` and `PartitionKey`. **This works because** API Gateway can call the service API directly with an **IAM execution role** it assumes, so no Lambda is needed, which is cheaper and faster.
- **If** you want to expose containers in private subnets, **then** use a **VPC link** (private integration) to a **Network Load Balancer (NLB)** or **Application Load Balancer (ALB)**. **This works because** API Gateway reaches resources inside the VPC while the targets stay private. REST VPC links target an NLB (ALB support is newer (verify)); HTTP API VPC links target ALB, NLB or Cloud Map.
- **If** a frontend team needs a working API before the backend exists, **then** use a **mock integration** (`MOCK`). **This works because** API Gateway answers by itself with canned responses, so no backend is called.
- **If** you get **415 Unsupported Media Type**, **then** the request `Content-Type` does not match any **mapping template** and the **passthrough behavior** blocks it. With `NEVER`, any unmatched content type gets 415; with `WHEN_NO_TEMPLATES`, it gets 415 only when other templates are defined. **This works because** passthrough decides what happens when no template matches; `WHEN_NO_MATCH` would pass the body through unchanged.
- **If** you want the same API in two Regions behind one hostname, **then** use **Regional endpoints** with a **custom domain** in each Region and **Amazon Route 53** latency or failover routing. **This works because** a Regional custom domain is **per Region** (with its ACM certificate in that same Region), so Route 53 picks which Region answers.

Verified from AWS docs on 2026-10-31.
Unconfirmed (verify): REST API private integration support for ALB through VPC links; REST endpoint-type change rules (Regional ↔ Edge ↔ Private); the exact "about 70% cheaper" figure (it follows from $1.00 vs $3.50 per million list price in us-east-1 and varies by Region and tier).

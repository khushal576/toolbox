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
- If you only need one public HTTPS endpoint for one Lambda → **function URL**, because it is free and has no extra service.
- If you need per-customer rate limits and quotas → **REST API + usage plans + API keys**, because HTTP APIs lack both.
- If you need WAF on the API → **REST API** (or CloudFront in front of an HTTP API), because HTTP APIs do not support WAF directly.
- If the API must not be on the internet → **Private REST API + VPC endpoint + resource policy**, because only that type is VPC-only.
- If cost is the priority and you only need JWT auth and Lambda/HTTP backends → **HTTP API**, because it is about 70% cheaper.
- If clients are worldwide and want low latency without managing CloudFront → **edge-optimized REST**, because AWS-managed CloudFront is built in.
- If clients are in the same Region (internal services) → **Regional**, because it avoids the CloudFront hop.
- If you change API config and nothing happens → **deploy to the stage** (REST), because changes are not live until deployed.
- If the client gets **502** from a Lambda proxy → check the **response format** (`statusCode`, `body` as string), because API Gateway rejects malformed proxy responses.
- If the client gets **504** → integration took more than the timeout (29 s default); make it async (SQS/Step Functions) or request an increase / use response streaming.
- If you want to send records to Kinesis/SQS with no code → **AWS service integration with mapping template**, because API Gateway can call the service API directly.
- If you want to expose containers in private subnets → **VPC link to NLB/ALB**, because the targets stay private.
- If a frontend team needs a working API before the backend exists → **mock integration**, because API Gateway returns canned responses.
- If you get **415 Unsupported Media Type** → the content type does not match a mapping template and passthrough is `WHEN_NO_TEMPLATES`/`NEVER`.
- If you want the same API in two Regions with one hostname → **Regional endpoints + custom domain + Route 53** latency/failover routing, because Regional custom domains are per Region.

Verified from AWS docs on 2026-10-31.
Unconfirmed (verify): REST API private integration support for ALB through VPC links; REST endpoint-type change rules (Regional ↔ Edge ↔ Private); the exact "about 70% cheaper" figure (it follows from $1.00 vs $3.50 per million list price in us-east-1 and varies by Region and tier).

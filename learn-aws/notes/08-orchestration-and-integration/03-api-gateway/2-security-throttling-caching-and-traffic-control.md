# Amazon API Gateway – 2. Security, throttling, caching and traffic control

Short notes. Each point is a fact you can be asked about.

## A. Authentication and authorization options
- **Who can call the API** (pick one or combine):
  - **IAM (SigV4)**: caller signs requests with AWS credentials. Best for AWS-to-AWS and internal callers. Policy action `execute-api:Invoke`.
  - **Cognito user pool authorizer** (REST): validates a Cognito token (ID or access token). No Lambda code.
  - **Lambda authorizer** (REST and HTTP): your function returns an IAM policy. For custom tokens, SAML, OAuth from any provider, database lookups.
  - **JWT authorizer** (HTTP only): validates OIDC/OAuth 2.0 JWTs (Cognito, Auth0, Okta, any OIDC issuer).
  - **Resource policy** (REST only): who/where from (account, IP/CIDR, VPC endpoint).
  - **mTLS**: client certificate checked on a custom domain (REST and HTTP).
  - **API keys**: identify clients for throttling/quotas. **Not** an auth mechanism.
- **Authentication vs authorization**: IAM/Cognito/JWT check identity; policies and scopes decide what is allowed.
- Unauthorized outcomes: **401 Unauthorized** (no/invalid token), **403 Forbidden** (denied by policy/authorizer/WAF/resource policy). You can customise both as **gateway responses** (REST).
- **Pick quickly**:
  - Internal AWS callers / roles → **IAM**.
  - Mobile/web users with Cognito → **Cognito authorizer** (REST) or **JWT authorizer** (HTTP).
  - Third-party identity provider using OIDC → **JWT authorizer** (HTTP) or Lambda authorizer (REST).
  - Custom rules (headers, DB lookup, API-key checks) → **Lambda authorizer**.
- **IAM auth details**: caller needs an identity policy allowing `execute-api:Invoke` on the API ARN (`arn:aws:execute-api:region:acct:api-id/stage/METHOD/path`). Cross-account: need the resource policy and the caller's IAM policy.
- **Resource policy** examples: allow only an IP range, allow only a **VPC endpoint**, allow another account. Required for **private APIs**. Limit **8,192 characters** (adjustable).

## B. Lambda authorizers (REST)
- Two types:
  - **`TOKEN`**: reads **one** header (bearer token). Cache key = the token. Optional **regex validation** of the token before calling Lambda.
  - **`REQUEST`**: reads **headers, query strings, stage variables and context variables**. Cache key = all identity sources together (order matters). Recommended by AWS.
- With caching and a `REQUEST` authorizer, if an identity source is missing/empty → **401 without invoking** the function.
- Output the function must return:
  - **`principalId`** and **`policyDocument`** (an IAM policy allowing/denying `execute-api:Invoke`).
  - Optional **`context`** map: string/number/boolean values only (**no objects or arrays**). Passed to the backend (`$context.authorizer.key`; Lambda proxy: `event.requestContext.authorizer.key`).
  - Optional **`usageIdentifierKey`** when `apiKeySource` is `AUTHORIZER` (maps the caller to an API key for usage plans).
- **Caching** (authorizer result TTL): default **300 s**, max **3,600 s**, **0 disables** **(verify)**.
- **Caching trap**: the cached policy is reused for other methods/paths in the API. **Write the policy for all resources the caller may use** (wildcard resource), or else a cached `Allow` for one method yields **403** on another.
- Method ARN max **1,600 bytes**; the policy `Resource` string max **512 characters**. A long path parameter can cause **414 Request URI Too Long**. Send big JWTs in a **header**, not the URL.
- Return `Deny` → **403**. Throw `"Unauthorized"` → **401**. Other errors → **500**.
- **Lambda authorizer for HTTP APIs**:
  - Payload format **1.0** (IAM policy response) or **2.0**.
  - Format 2.0 supports a **simple response** `{ "isAuthorized": true, "context": {...} }`.
  - Result cache TTL up to 3,600 s. Authorizer must answer within **10 s**.
- **Authorizers per API**: **10** (REST and HTTP), increase through support.
- A Lambda authorizer can live in **another account** (grant `lambda:InvokeFunction` to API Gateway).

## C. JWT authorizers (HTTP APIs)
- Configure **issuer** (`iss`) and **audience** (`aud`/`client_id`) and the identity source (`$request.header.Authorization`).
- Validation checks: token present and decodable, signature (**RSA-based algorithms only**, public key from the issuer `jwks_uri`, cached up to **2 hours** best-effort), `kid`, `iss`, `aud`/`client_id`, `exp`, `nbf`, `iat`, and **scopes** (`scope`/`scp` must contain at least one of the route's scopes).
- Claims are passed to the backend (`event.requestContext.authorizer.jwt.claims`).
- Failure → **401** (invalid token) or **403** (missing scope).
- Cognito works as an OIDC issuer: `https://cognito-idp.{region}.amazonaws.com/{userPoolId}`.
- **Trap**: ID tokens and access tokens are both JWTs; require **scopes** on the route to be sure only access tokens pass.
- **Key rotation**: allow a grace period, because the public key may be cached up to 2 hours.
- Limits: 50 audiences per authorizer, 10 scopes per route, 1,500 ms JWKS/discovery timeout.

## D. API keys and usage plans (REST only)
- **API key**: an alphanumeric value (20–128 chars) sent in the **`x-api-key`** header. Identifies the client.
- **Usage plan**: ties keys to **API stages/methods** and sets **throttle (rate + burst)** and a **quota** (requests per **day/week/month**).
- **Not security**: a key is not authentication. Anyone with a valid key for one API in a usage plan can reach **all** APIs in that plan. Keys appear in logs and headers.
- Always combine with a real authorizer (IAM/Cognito/Lambda).
- Method must be marked **API key required** for the key to be checked. Missing/invalid key → **403 Forbidden**.
- `apiKeySource`: `HEADER` (default, `x-api-key`) or `AUTHORIZER` (the Lambda authorizer returns `usageIdentifierKey`).
- A key can be in several usage plans, but **only one plan per stage** for a given key. Best practice: one key per plan.
- Keys per account per Region: **10,000** (fixed). Usage plans: **300** (adjustable). Method-level throttle settings per plan: **20**.
- **Best effort**: quotas and throttles are targets, not hard caps. Clients may exceed them. **Do not use usage plans to control cost**: use **AWS Budgets** to watch cost and **AWS WAF** to block traffic.
- Changes to a plan can take a few minutes to apply. `UpdateUsagePlan` is limited to 1 request every 20 s.
- Use API-Gateway-generated keys (do not put secrets in keys).
- **HTTP APIs have no API keys or usage plans.**

## E. Throttling
- **Token bucket** per Region per account: default **10,000 requests/s steady rate** with a **5,000 burst** bucket (some newer Regions: 2,500 RPS and 1,250 burst). Account RPS is **adjustable**; the burst is **set by AWS** based on the rate.
- This account limit is shared across **all** APIs and API types (HTTP, REST, WebSocket) in the Region. One noisy API can throttle the others.
- Excess requests get **429 Too Many Requests**. Clients should **retry with exponential backoff and jitter**.
- **Order applied (most specific wins)**:
  1. Per-client / per-method limits in a **usage plan**.
  2. Per-method limits on the **stage** (method settings).
  3. **Account** level per Region.
  4. AWS Regional (hard) limits.
- Stage defaults can apply to all methods; override per method (for example, low limit on an expensive `POST`).
- Throttle limits can never exceed the account limit.
- **HTTP APIs**: throttling at **stage default and per-route** level. No per-client throttle.
- **WebSocket**: connection and message-rate throttles also apply (status code 1008 "too many requests").
- Throttling is **best effort**, so plan for slightly more than the limit.
- Protect backends too: Lambda concurrency (reserved), SQS buffer, DynamoDB capacity. API Gateway throttle alone does not size your backend.
- **Throttling vs WAF rate-based rules**: usage plans limit **known API-key clients**; WAF rate-based rules limit by **IP** (and other keys). Use both for public APIs.

## F. Caching (REST only)
- **Stage cache**: a dedicated cache instance you **provision per stage**, sizes from **0.5 GB to 237 GB** **(verify)**. Charged **per hour** by size. **Not in the free tier**.
- **TTL**: default **300 s**, max **3,600 s**, **0 = caching off**. Can be overridden per method.
- Only **GET** is cached by default. Other methods can be turned on through method overrides (be careful with non-idempotent verbs).
- **Cache key** = the parameters you mark as **cache keys** (headers, path, query string). At least one is needed for a resource with parameters. Different values are cached separately.
  - Unmarked parameters are **ignored** for matching (two requests that differ only there get the same cached response).
- Max cached response size **1 MB** (1,048,576 bytes; encryption may add overhead). Larger responses are not cached.
- Provisioning or deleting a cache takes **about 4 minutes**. Changing its size **deletes and recreates** it → cached data is lost.
- **Flush** the whole stage cache (`flush-stage-cache`). Flushing causes a burst of backend calls and latency.
- **Invalidate one entry**: client sends header **`Cache-Control: max-age=0`**. Needs the IAM permission **`execute-api:InvalidateCache`** if "require authorization" is on. Unauthorized handling options: `FAIL_WITH_403`, `SUCCEED_WITH_RESPONSE_HEADER`, `SUCCEED_WITHOUT_RESPONSE_HEADER`. Cross-account invalidation is **not supported**.
- **Encrypt cache data** per method when responses are sensitive.
- Caching is **best effort**. Watch `CacheHitCount` and `CacheMissCount`. Do not use the CloudFront `X-Cache` header to judge hits.
- **Not supported with response streaming.**
- **Canary releases** can share the stage cache (`useStageCache`). With different deployments, prod and canary responses are cached separately.
- Run a **10-minute load test** to choose cache size (size affects CPU, memory, network).
- Caching alternatives: **CloudFront** in front (longer TTLs, global), **ElastiCache/DAX** in the backend.

## G. Request validation, WAF and more
- **Request validation** (REST): validate required parameters/headers and the body against a **JSON Schema model** **before** calling the backend. Invalid → **400** and no backend charge. Saves cost and protects the backend.
- **AWS WAF** (REST APIs, per stage): managed rule groups, rate-based rules, IP sets, geo blocking, SQLi/XSS. **Not for HTTP APIs** directly (put CloudFront+WAF in front, or use REST).
- **AWS Shield Standard** is on by default for the edge/regional endpoints. Shield Advanced is paid.
- **TLS**: minimum TLS version via **security policy** on custom domains (TLS 1.2 recommended; TLS 1.0 only for legacy).
- **Custom domain names**:
  - Use **ACM** certificates (free, auto-renew). Edge-optimized needs the certificate in **us-east-1**; Regional in the API's Region.
  - **API mappings** map `domain/path` to an API + stage. Single-level mappings (such as `/prod`) do not count against the 200 multi-level mapping quota.
  - Create a Route 53 **alias** record to the domain's target name.
  - **Public custom domains: 120** per account per Region (adjustable). Private custom domains: 50.
- **mTLS**: upload a **truststore** (PEM bundle in S3, up to 1,000 certs / 1 MB). Clients must present a certificate from it. Needs a **custom domain**; disable the default `execute-api` endpoint or clients bypass mTLS.
- **Backend authentication**: REST can send an **API-Gateway-generated client certificate** to the backend (backend verifies). Not supported on HTTP APIs.
- **Private integrations / VPC links** keep backend traffic off the internet.
- **Disable default endpoint** so only the custom domain (with WAF/mTLS) is used.
- **Resource policy + VPC endpoint policy** both apply to private APIs.
- **Encryption**: HTTPS only (HTTP is not accepted). Cache can be encrypted. Logs in CloudWatch can use KMS.
- **CloudTrail** records API Gateway **management** (control plane) calls. **Invocations** go to access/execution logs, not CloudTrail.

## H. CORS
- **CORS** is a browser rule: another origin may call the API only if it allows it.
- **HTTP API**: turn on the built-in CORS settings (allowed origins, methods, headers, max age, credentials). API Gateway answers preflight.
- **REST API**:
  - Add an **`OPTIONS`** method (usually a **mock** integration) returning `Access-Control-Allow-*` headers.
  - **Also** return `Access-Control-Allow-Origin` from the real method (**Lambda proxy: your code must add the header**).
  - Gateway error responses (4xx/5xx) need CORS headers set in **gateway responses**, or browsers hide the error.
- CORS is **not security**: it is only enforced by browsers, not by `curl` or servers.
- Browser shows a CORS error but the real cause is 403/5xx without CORS headers → fix **gateway responses**.

## I. Gateway responses and error codes (REST)
- **Gateway responses** are the errors API Gateway produces itself (for example `UNAUTHORIZED`, `ACCESS_DENIED`, `THROTTLED`, `MISSING_AUTHENTICATION_TOKEN`, `BAD_REQUEST_BODY`, `API_CONFIGURATION_ERROR`, `INTEGRATION_TIMEOUT`, `QUOTA_EXCEEDED`). You can change status, headers and body template.
- **Common codes**:
  - **400** bad request / validation failure.
  - **401** unauthorized (token missing/invalid; authorizer error).
  - **403** forbidden (policy deny, WAF block, missing/invalid API key, resource policy, **or hitting a path/stage that does not exist - "Missing Authentication Token"**).
  - **413** payload too large (>10 MB).
  - **414** URI too long.
  - **415** unsupported media type (no mapping template match).
  - **429** throttled / quota exceeded.
  - **502** bad gateway: malformed backend response (Lambda proxy format) or backend error.
  - **503** service unavailable (backend not reachable / VPC link).
  - **504** integration timeout.
- **Famous trap**: "**Missing Authentication Token**" usually means a **wrong URL/path/method or stage not deployed**, not a real auth problem.

## J. Scenarios: "If X → Y, because Z"
- If the API is called by other AWS services/roles → **IAM auth (SigV4)**, because no tokens to manage and policies control access.
- If web/mobile users sign in with Cognito and the API is a REST API → **Cognito user pool authorizer**, because no Lambda code and low cost.
- If you use an HTTP API with Cognito/Auth0/Okta → **JWT authorizer**, because it is native, cheap and needs no Lambda.
- If tokens are custom or checked against a database → **Lambda authorizer (REQUEST)**, because you can run any logic and cache the result.
- If a Lambda authorizer allows one method but others return 403 → the **cached policy only covered one resource**; return a wildcard-resource policy, because the cache is reused across methods.
- If you want per-customer rate limits and monthly quotas → **usage plans + API keys + an authorizer**, because keys identify clients but do not authenticate them.
- If you want to stop abuse from an IP → **WAF rate-based rule**, because usage plans cannot limit by IP.
- If a quota/limit must be hard because of cost → **do not rely on usage plans**; use **AWS Budgets, WAF and backend limits**, because throttles are best effort.
- If clients get **429** during a spike → raise the account limit, add stage/method limits, use client backoff, or buffer with SQS, because the account token bucket is shared.
- If an API is hit by repeated identical reads → enable the **stage cache** (or CloudFront), because it cuts backend calls and latency.
- If the cache must be bypassed for one request → send **`Cache-Control: max-age=0`** with `execute-api:InvalidateCache` permission, because that invalidates a single entry.
- If a response is bigger than 1 MB → it will **not be cached**; use a pre-signed URL or CloudFront.
- If the API must be internal only → **private API + interface endpoint + resource policy**, because there is no public path.
- If an HTTP API needs WAF → place **CloudFront + WAF** in front (or switch to REST), because HTTP APIs do not integrate with WAF directly.
- If browsers show CORS errors only on failures → add CORS headers to **gateway responses**, because API Gateway-generated errors lack them by default.
- If clients must present certificates → **mTLS on a custom domain + disable the default endpoint**, because otherwise clients can bypass the custom domain.
- If you want to block malformed payloads early and save backend cost → **request validation with a JSON Schema model**, because invalid calls return 400 without invoking the backend.

Verified from AWS docs on 2026-10-31.
Unconfirmed (verify): Lambda authorizer result cache TTL default 300 s / max 3,600 s for REST; stage cache size range (0.5–237 GB); WebSocket throttling behaviors and the exact set of gateway response names; HTTP API Lambda authorizer payload format and TTL details; whether REST API caching limits changed recently.

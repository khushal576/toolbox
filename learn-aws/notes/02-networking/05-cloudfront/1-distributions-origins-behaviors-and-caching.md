# Amazon CloudFront – 1. Distributions, origins, behaviors, caching and performance

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **Amazon CloudFront** is a global **content delivery network (CDN)**. It caches and accelerates content from **origins** at hundreds of **edge locations** and **Regional Edge Caches**, and terminates TLS close to users.
- It also accelerates **dynamic and API traffic** (persistent connections to origin over the AWS backbone), supports **WebSocket**, and can run code at the edge.
- It is a **global** service; ACM certificates for CloudFront must be in **us-east-1**; WAF web ACLs for CloudFront are `CLOUDFRONT` scope in us-east-1.
- Pick it when: you serve **static assets, downloads, video, APIs, or websites** to distributed users; need **DDoS resilience, WAF, TLS, signed access**; want to **reduce origin load and egress cost**.
- Data-engineering relevance: serving **data downloads from S3**, **API Gateway/ALB data APIs**, BI dashboards (Superset/Grafana behind ALB), static reports, **private S3 content with signed URLs**.
- DEA-C01: appears as part of securing/serving data (signed URLs, OAC to S3, WAF) and cost/performance of data distribution.

## B. Core components
- **Distribution**: the CloudFront configuration with a domain name `dxxxx.cloudfront.net`, origins, behaviors, TLS, logging. Up to **500 distributions per account** (adjustable).
- **Origin**: where CloudFront fetches content: **S3 bucket**, **S3 static website endpoint (custom origin)**, **ALB/NLB/EC2**, **API Gateway**, **MediaPackage/MediaStore**, **Lambda function URL**, any **custom HTTP(S) origin**, or **VPC origin** (private ALB/NLB/EC2 in a VPC with no public IP).
  - Up to **100 origins** per distribution; **10 origin groups**.
- **Origin group**: primary + secondary origin with **failover** on specified HTTP status codes (500/502/503/504, 403/404) or timeouts. Works for GET/HEAD/OPTIONS.
- **Cache behavior**: path pattern (`/api/*`, `*.jpg`, default `*`) → origin, **viewer protocol policy**, allowed methods, **cache policy**, **origin request policy**, response headers policy, function associations, signed access settings. Up to **75 behaviors** per distribution (adjustable). First matching pattern wins (order matters; default behavior last).
- **Edge locations / Regional Edge Caches**: request flow: viewer → edge → regional edge cache → (Origin Shield) → origin.
- **Origin Shield**: optional extra caching layer in one chosen Region that **collapses requests** from all edges to the origin (higher cache hit ratio, less origin load); adds a per-request fee.
- **Price classes**: All edge locations (default), **Price Class 200** (excludes the most expensive Regions), **Price Class 100** (cheapest: US, Canada, Europe, Israel); trade off cost vs global performance.
- **Alternate domain names (CNAMEs)**: up to 100 per distribution; require a matching **ACM/IAM certificate** (SNI is free; dedicated IP custom SSL is paid and limited).
- **Default root object** (for example `index.html`), **custom error pages**, **error caching minimum TTL** (default 10 s).
- **HTTP versions**: HTTP/1.1, HTTP/2, **HTTP/3 (QUIC)**; IPv6 supported.
- **Compression**: gzip and Brotli at the edge for files 1,000 bytes – 10 MB when `Accept-Encoding` is present and the cache policy enables it.
- **Limits**: max cacheable object **50 GB** per GET response; max request body **64 GB**; request/response header+query max **32 KB** (URL 8 KB); data transfer **150 Gbps** and **250,000 requests/s** per distribution (adjustable).
- **Continuous deployment**: staging distribution receives a % or header-based subset of traffic to test config changes safely (20 staging distributions per account).
- **Multi-tenant distributions** and **Anycast static IPs** for SaaS and allow-listing scenarios **(verify details)**.

## C. Caching mechanics
- **Cache key**: what makes two requests "the same object": URL path plus selected **headers, cookies, query strings** from the **cache policy**. Fewer elements in the key → higher hit ratio.
- **Cache policy** (managed or custom): TTLs (min, default, max), what is in the cache key, compression. **Managed policies**: `CachingOptimized` (for S3/static), `CachingDisabled` (APIs), `Elemental-MediaPackage`, `Amplify`.
- **Origin request policy**: what is **forwarded to the origin but not part of the cache key** (headers, cookies, query strings), for example `AllViewer`, `CORS-S3Origin`.
- **Response headers policy**: add CORS, security headers (HSTS, CSP, X-Frame-Options), custom headers.
- **TTL logic**: effective TTL derived from origin `Cache-Control: max-age/s-maxage`, `Expires`, clamped by the policy's **min/max TTL**; default TTL used when origin gives none (default 24 hours).
- **Cache statuses** (`X-Cache` header): `Hit from cloudfront`, `Miss from cloudfront`, `RefreshHit`, `Error from cloudfront`, plus `x-amz-cf-pop` and `x-amz-cf-id` for troubleshooting.
- **Cache hit ratio** is the key tuning metric (CloudFront reports); improve with normalized query strings, no unnecessary cookies/headers, longer TTLs, Origin Shield, versioned file names.
- **Invalidation**: remove objects before TTL: `/*` or specific paths; **first 1,000 invalidation paths/month free**, then about $0.005 per path; quotas: 150 paths/tags per second, 1 wildcard invalidation per second. Prefer **versioned file names** (`app.v123.js`) over invalidations. **Tag-based invalidation** is newer **(verify)**.
- **Stale content**: `stale-while-revalidate` and `stale-if-error` directives supported.
- **POST/PUT/PATCH/DELETE** are not cached (but accelerated); `allowed methods` choose GET/HEAD, GET/HEAD/OPTIONS, or all.
- **Range requests** and **streaming** (HLS/DASH) supported; **byte-range** caching on.
- **Cookies/headers in key** for personalization lower hit ratio drastically.
- **Query string forwarding**: whitelist only needed params; sort/normalize via function if needed.

## D. Origins in detail
- **S3 origin (private)** with **Origin Access Control (OAC)**: CloudFront signs requests (SigV4) to S3; bucket policy allows only the distribution (`AWS:SourceArn` = distribution ARN, principal `cloudfront.amazonaws.com`). Supports **SSE-KMS** (key policy must allow the CloudFront service principal), PUT/DELETE uploads. **OAI (legacy)** still works but OAC is recommended (100 OAI/OAC each per account default).
- **S3 static website endpoint**: treated as a **custom origin** (HTTP only), public bucket or custom header secret needed; no OAC.
- **ALB/EC2/custom origin**: choose protocol policy (HTTP only, HTTPS only, match viewer), **origin SSL protocols**, timeouts (**connection timeout 1–10 s**, attempts 1–3, **response timeout 1–120 s**, **keep-alive 1–300 s**).
- **VPC origins**: CloudFront reaches **private subnets** (ALB, NLB, EC2) via a managed ENI-based connection, so the origin has **no public IP/internet exposure**; up to 25 VPC origins per account.
- **Custom headers** (up to 30) added to origin requests, for example a **secret header** the origin verifies.
- **Origin protection** for ALB origins without VPC origins: security group allowing the **CloudFront managed prefix list** (`com.amazonaws.global.cloudfront.origin-facing`) + secret header/WAF check.
- **API Gateway origin**: use regional endpoints; caching rarely used for APIs (use `CachingDisabled` or short TTL) but CloudFront still gives TLS termination, WAF, geo restriction and lower latency.
- **Lambda function URL origin** with OAC (IAM auth).
- **MediaStore/MediaPackage**, **Elemental** for video.

## E. Edge compute
| Feature | **CloudFront Functions** | **Lambda@Edge** |
|---|---|---|
| Runtime | JavaScript (lightweight, ECMAScript 5.1+/modern subset) | Node.js, Python |
| Triggers | Viewer request/response | Viewer request/response, **origin request/response** |
| Execution time | sub-millisecond; max ~1 ms | up to 5 s (viewer) / **30 s** (origin) |
| Scale | millions of requests/s, at 200+ edge locations | thousands of requests/s per Region |
| Package size | **10 KB** code, 2 MB memory | 1 MB (viewer) – **50 MB** (origin) |
| Network/file access | No | Yes (network calls, AWS SDK) |
| Body access | No | Yes (origin events) |
| Cost | cheaper (per invocation) | higher (per request + duration) |
| Use cases | URL rewrites, redirects, header manipulation, cache-key normalization, simple auth (JWT validation), A/B | Complex auth, dynamic origin selection, SEO/SSR, image resize, calling APIs |
- **KeyValueStore** (CloudFront Functions): up to 5 MB store, key ≤512 B, value ≤1 KB, 50 keys or 3 MB per update.
- **Lambda@Edge** functions are authored in **us-east-1** and replicated; 100 functions per distribution; logs in the Region closest to the edge.
- **Connection Functions** (mTLS-related) are newer **(verify)**.

## F. Performance patterns
- **Static assets**: `CachingOptimized`, long TTL, versioned names, Brotli.
- **Dynamic APIs**: `CachingDisabled`, forward needed headers/cookies/query (origin request policy), HTTP/2/3, persistent connections, **Origin Shield** if repeated reads.
- **Large downloads**: range requests, multi-part, S3 origin; consider **S3 Transfer Acceleration** for uploads (not CloudFront).
- **Uploads**: CloudFront can accept PUT/POST to S3 via OAC; for large uploads use S3 multipart direct/presigned URLs (CloudFront request body up to 64 GB).
- **Video streaming**: HLS/DASH with MediaPackage; signed cookies.
- **Real-time delivery**: **WebSocket** supported (10-minute idle timeout); **gRPC** supported over HTTP/2 **(verify)**.
- **Reduce origin egress**: CloudFront-to-origin traffic from S3/AWS origins is **free of data transfer-out charges** to CloudFront; CloudFront data-out has its own pricing (cheaper than direct S3 egress at scale).

## G. Exam skills mapping
- **1.2.8 Create data APIs**: data API delivery.
- **4.3.4 Encryption in transit or before transit**: encryption in transit (TLS).
- **1.1.4 Consume data APIs**: consuming data APIs.

## H. Scenarios: "If X → Y, because Z"
- **If** users must download large files quickly from a **private Amazon S3 bucket**, **then** put **Amazon CloudFront** (the AWS content delivery network, CDN) in front of it with **Origin Access Control (OAC)**, and add **signed URLs** when only some users may download. CloudFront caches files at **edge locations** near users, so repeat downloads do not travel back to S3. **This works because** OAC lets only CloudFront read the bucket (it signs each request with SigV4), so S3 stays private. Signed URLs are time-limited links to one file. One cached object can be up to **50 GB**.
- **If** the S3 bucket must accept requests only through CloudFront, **then** use **Origin Access Control (OAC)** and a **bucket policy** that allows the principal `cloudfront.amazonaws.com` with the condition **`AWS:SourceArn` = your distribution's ARN**. **This works because** OAC signs every request CloudFront sends to S3, and the policy lets in only signed requests from that one distribution, so **S3 Block Public Access** can stay on. If objects use **SSE-KMS** encryption, the **AWS Key Management Service (KMS)** key policy must also allow the CloudFront service principal.
- **If** the origin is overloaded because many edge locations ask it for the same object, **then** enable **Origin Shield**, an optional extra cache layer in **one Region you choose**. **This works because** all edges send their cache misses through Origin Shield, which **collapses** them into a single request to the origin, so the cache hit ratio rises and origin load falls. The catch is an extra **per-request fee**.
- **If** the **cache hit ratio** (share of requests served from cache) is poor, **then** shrink the **cache key** in the **cache policy**: include only the headers, cookies and query strings you really need, normalize query strings (for example sort them with a function), and use longer **Time to Live (TTL)** values. **This works because** the cache key is the URL path plus those selected values, so every extra value splits one object into many cached copies. Values the origin needs but that should not split the cache go in an **origin request policy** instead. Cookies or headers added for personalization lower the hit ratio a lot.
- **If** a new version of your assets must appear for users at once, **then** use **versioned file names** (for example `app.v123.js`), or **invalidate** the changed paths. **This works because** a new file name is a new cache key, so edges fetch it fresh, while old files would otherwise stay cached until their **TTL** ends (default **24 hours** when the origin sends none) **(verify)**. Versioning is preferred: invalidations are free for the first **1,000 paths a month**, then about **$0.005 per path** **(verify)**.
- **If** the origin **Application Load Balancer (ALB)** must have no public exposure, **then** use a **CloudFront VPC origin**. **This works because** CloudFront reaches the ALB (or NLB or EC2) in **private subnets** through a managed connection based on network interfaces (ENIs), so the origin needs **no public IP** and is not open to the internet. The limit is **25 VPC origins per account**.
- **If** you need cheap header rewrites or redirects at very high scale, **then** use a **CloudFront Function**: small JavaScript code that runs on **viewer request/response** at every edge location. **This works because** it is lightweight (about **1 ms** max run time **(verify)**, **10 KB** code), scales to **millions of requests per second**, and costs less per invocation than **Lambda@Edge**. The catch: it has **no network or file access** and cannot read the request body.
- **If** your custom authentication must call an external service, **then** use **Lambda@Edge**, AWS Lambda functions (Node.js or Python) run by CloudFront. **This works because** Lambda@Edge can make **network calls** and use the AWS SDK, which CloudFront Functions cannot. It runs up to **5 s** on viewer events and **30 s** on origin events, and you write it in **us-east-1**. It costs more (per request plus duration).
- **If** the primary origin can fail and a static fallback copy exists, **then** create an **origin group**: a primary and a secondary origin with **failover**. **This works because** when the primary returns chosen error codes (500, 502, 503, 504, 403, 404) or times out, CloudFront retries the request on the secondary. Failover works only for **GET, HEAD and OPTIONS** requests, and a distribution can have **10 origin groups**.
- **If** CloudFront costs are high because traffic is served from expensive far-away Regions, **then** choose **Price Class 100** (cheapest: US, Canada, Europe, Israel) or **Price Class 200** (leaves out the most expensive Regions) instead of the default **all edge locations**. **This works because** a price class limits which edge locations serve your users, and so which pricing tier you pay. The catch: users far from the included locations get slower performance.

Verified from AWS docs on 2026-11-09 (CloudFront quotas page, CloudFront pricing/flat-rate page).
Unconfirmed (verify): tag-based invalidation; managed policy list; Connection Functions and multi-tenant details; gRPC support; Function execution time caps; invalidation price; default TTL 24 h; Origin Shield price.

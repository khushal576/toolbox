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
- If you want users to download large files from a private S3 bucket quickly → **CloudFront + OAC (+ signed URLs)**, because CloudFront caches at the edge and S3 stays private.
- If the S3 bucket must accept requests only through CloudFront → **bucket policy allowing `cloudfront.amazonaws.com` with `AWS:SourceArn` = distribution**, because OAC signs requests.
- If origin load is high with many edges requesting the same object → **enable Origin Shield**, because it collapses misses to a single Region.
- If cache hit ratio is poor → **reduce cache key (fewer headers/cookies/query strings), normalize, lengthen TTL**, because the key fragments the cache.
- If you must deploy a new version of assets instantly → **versioned file names (or invalidate paths)**, because TTL would otherwise serve stale files.
- If the origin ALB must have no public exposure → **CloudFront VPC origin**, because CloudFront connects privately.
- If you need a header rewrite/redirect at scale cheaply → **CloudFront Function**, because it's lightweight and cheaper than Lambda@Edge.
- If you need custom auth that calls an external service → **Lambda@Edge**, because it can make network calls.
- If the primary origin fails and static fallback exists → **origin group with failover**, because CloudFront retries the secondary origin.
- If costs are high due to far-away Regions → **Price Class 100/200**, because it limits edge locations used (and thus pricing tier).

Verified from AWS docs on 2026-11-09 (CloudFront quotas page, CloudFront pricing/flat-rate page).
Unconfirmed (verify): tag-based invalidation; managed policy list; Connection Functions and multi-tenant details; gRPC support; Function execution time caps; invalidation price; default TTL 24 h; Origin Shield price.

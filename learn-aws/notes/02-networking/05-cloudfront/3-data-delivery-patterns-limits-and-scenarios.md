# Amazon CloudFront – 3. Data delivery patterns, limits and exam scenarios

Short notes. Each point is a fact you can be asked about.

## A. Patterns for data engineers
- **Public open-data download site**: S3 (public data) + CloudFront (Price Class 100/200) + long TTL + versioned prefixes (`/v2026-11/…`) + logs to S3 for usage analytics.
- **Private dataset delivery**: private S3 + **OAC** + **signed URLs** minted by a Lambda/API after authorization; short expiry; log access.
- **Data API acceleration**: CloudFront in front of **API Gateway/ALB** with `CachingDisabled` or short-TTL caching for GETs, WAF rate rules, TLS 1.3, HTTP/3.
- **BI dashboard exposure**: CloudFront → **VPC origin ALB** → Superset/Grafana/Airflow UI (private) + WAF + OIDC auth on the ALB or Lambda@Edge/Verified Access.
- **Report/PDF distribution**: pipeline writes to S3, EventBridge triggers Lambda to create a signed URL emailed to users.
- **Static data catalog / docs site**: S3 website content with OAC and `index.html` rewrite via CloudFront Function.
- **ML model / artifact distribution**: large objects through CloudFront (up to 50 GB cacheable) with range requests.
- **Ingestion endpoint (uploads)**: CloudFront accepts PUT/POST to S3 via OAC for moderate uploads; for large/parallel uploads use S3 Transfer Acceleration or presigned multipart.
- **Log analytics pipeline**: standard logs → S3 → Glue crawler/partition projection → Athena; or real-time logs → Kinesis → Firehose → OpenSearch/S3.
- **Multi-Region origin failover**: origin group primary S3 bucket (Region A) with secondary bucket (CRR replica, Region B).
- **Edge personalization / A/B testing**: CloudFront Functions or KeyValueStore.

## B. CloudFront vs related options
| Need | CloudFront | S3 Transfer Acceleration | Global Accelerator | API Gateway edge-optimized | Route 53 |
|---|---|---|---|---|---|
| Cache content at edge | **Yes** | No | No | Uses CloudFront internally | No |
| Speed up **uploads** to S3 | Partial (PUT via OAC) | **Yes (edge → S3 backbone)** | No | n/a | No |
| TCP/UDP non-HTTP | No | No | **Yes** | No | No |
| Static anycast IPs | Optional (Anycast static IPs) | No | **Yes (2 static IPs)** | No | No |
| WAF/DDoS | Yes | No | Shield | WAF | DNS only |
| Best for | HTTP(S) content/APIs | Large uploads from far clients | Non-HTTP, fast regional failover, static IPs | Public APIs | DNS routing |
- **Global Accelerator vs CloudFront**: CloudFront = cache + HTTP; Global Accelerator = **no caching**, TCP/UDP, fixed IPs, health-based endpoint failover.
- **Edge-optimized API Gateway** uses a CloudFront distribution managed by AWS (you can't configure it); use **regional endpoint + your own CloudFront** for control.
- **S3 presigned URL vs CloudFront signed URL**: presigned goes straight to S3 (no cache, supports uploads); CloudFront signed URL goes via cache/WAF/custom domain.

## C. Limits summary (from the quotas page)
| Item | Default |
|---|---|
| Distributions per account | **500** |
| Origins per distribution | **100** |
| Origin groups per distribution | **10** |
| Cache behaviors per distribution | **75** |
| Alternate domain names (CNAMEs) | **100** |
| Data transfer rate per distribution | **150 Gbps** |
| Requests per second per distribution | **250,000** |
| Max cacheable object (GET) | **50 GB** |
| Max request body | **64 GB** |
| Max URL length | 8,192 bytes |
| Request/response header+query size | 32,768 bytes |
| Connection timeout / attempts | 1–10 s / 1–3 |
| Response timeout | 1–120 s |
| Keep-alive timeout | 1–300 s |
| Custom cache / origin request policies | 20 each |
| Response headers policies | 20 |
| CloudFront Functions per account | 100 (10 KB, 2 MB mem) |
| KeyValueStores per account | 200 (5 MB each) |
| Lambda@Edge functions per distribution | 100; timeout 30 s (origin) / 5 s (viewer) |
| Lambda@Edge response size | viewer 40 KB / origin 1 MB |
| Dedicated IP SSL certificates | 2 |
| Invalidations | 150 paths/s; 1 wildcard/s |
| Key groups per account / per behavior | 10 / 4; 5 public keys per group |
| Real-time log configs | 150 |
| WebSocket idle timeout | 10 minutes |
| Staging distributions | 20 |
| Tags per distribution | 50 |
| Field-level encryption | 10 fields, 16 KB each, body 1 MB |
| WAF associations per web ACL | 100 |

## D. Best practices
- **Always use OAC** for S3; keep buckets private; no OAI for new setups.
- **Set cache policies deliberately**; avoid forwarding all headers/cookies/query strings.
- **Version assets** instead of invalidating.
- **Compress** (Brotli/gzip) and use **HTTP/3**.
- **Use Origin Shield** for expensive or limited-capacity origins and multi-edge fan-in.
- **Use VPC origins/prefix lists** to protect origins.
- **Enable WAF** with rate limits, and **Shield Advanced** for critical sites.
- **Monitor**: cache hit rate, origin latency, 4xx/5xx; alarms with SNS.
- **Log** to S3 and analyze with Athena; keep logs partitioned and lifecycle-managed.
- **IaC** for distributions; use **continuous deployment** for risky config changes.
- **Pick price class** based on audience geography.
- **Keep security headers** in response headers policies.
- **Test with `curl -I`** to review `x-cache` headers.
- **Plan certificates** (ACM us-east-1, SAN coverage) and renewals (ACM auto-renews when DNS-validated).

## E. Troubleshooting quick map
| Symptom | Likely cause |
|---|---|
| 403 AccessDenied (S3) | OAC/bucket policy/KMS/missing object |
| 502 | Origin TLS/connect failure |
| 503 | Origin overloaded or capacity |
| 504 | Origin timeout (response timeout) |
| Stale content | TTL, not invalidated |
| High origin traffic | Low cache hit ratio, no Origin Shield |
| Wrong content per user | Cookies/headers in cache key missing or too many |
| Mixed content errors | HTTP assets on HTTPS page |
| CORS failure | Origin header not forwarded / response headers policy |
| Certificate error | CNAME missing or cert not in us-east-1 |
| Signed URL rejected | Key group/expiry/policy mismatch |

## F. Exam skills mapping
- **1.2.8 Create data APIs**: data API delivery.
- **4.3.4 Encryption in transit or before transit**: encryption in transit (TLS).
- **1.1.4 Consume data APIs**: consuming data APIs.

## G. Scenarios: "If X → Y, because Z"
- **If** you must serve a **20 GB** dataset privately to partners around the world, **then** use **Amazon CloudFront** with **Origin Access Control (OAC)** on a private S3 bucket and **signed URLs** created by a Lambda function or API after it checks the user. **This works because** CloudFront can cache objects up to **50 GB** at edge locations and supports range requests, OAC keeps S3 private, and each signed URL is **time-limited**. Use a short expiry and log access.
- **If** clients far from the bucket upload large files slowly, **then** use **S3 Transfer Acceleration**. **This works because** uploads enter at a nearby edge location and travel to S3 over the AWS backbone. CloudFront is mainly for delivery: it accepts PUT/POST to S3 through OAC only for **moderate** uploads; for large or parallel uploads use Transfer Acceleration or presigned multipart uploads.
- **If** a game or IoT backend needs **static anycast IP addresses** over **TCP/UDP**, **then** use **AWS Global Accelerator**. **This works because** it gives **2 static IPs**, carries any TCP/UDP traffic and fails over between endpoints based on health, but does **no caching**. CloudFront handles only HTTP(S), and its fixed IPs (Anycast static IPs) are an optional extra, not the default **(verify)**.
- **If** every request must be logged for security review, **then** send **standard logs** to **Amazon S3**, and add **real-time logs** to **Amazon Kinesis Data Streams** for alerting. **This works because** both capture per-request fields (client IP, URL, status, time). Standard logs arrive **within minutes**, real-time logs **within seconds**.
- **If** an API distribution must be limited to paying customers, **then** use **AWS WAF** (web application firewall) plus token checks (API keys or **JSON Web Token (JWT)** validation) in a **CloudFront Function** or **Lambda@Edge**. **This works because** requests without a valid token are blocked at the edge, before they reach your API origin. CloudFront Functions suit simple JWT checks; Lambda@Edge is needed when the check must call another service.
- **If** S3 data-transfer (egress) costs from a popular dataset are high, **then** put **CloudFront** in front of the bucket with a **long Time to Live (TTL)**. **This works because** transfer from AWS origins like S3 to CloudFront is **free**, CloudFront data-out is cheaper than direct S3 egress at scale, and a long TTL lets edges serve most requests from cache instead of S3.
- **If** dashboards (for example Superset or Grafana) must stay private inside a **Virtual Private Cloud (VPC)**, **then** use a **CloudFront VPC origin** pointing to a private **Application Load Balancer (ALB)**, plus **AWS WAF** and authentication (OIDC on the ALB, or Lambda@Edge). **This works because** CloudFront reaches the private ALB without a public IP, so there is no public ALB to attack, and only signed-in users get through.
- **If** a small site needs a **predictable monthly CDN cost**, **then** choose a **CloudFront flat-rate plan** such as **Pro ($15/month)** or **Business ($200/month)**. **This works because** each plan is a fixed monthly price per distribution that bundles data transfer, requests, **WAF**, DDoS protection and more, with **no overage charges** **(verify details)**. Pro includes **10 million requests** and Business **125 million** a month.

Verified from AWS docs on 2026-11-09 (CloudFront quotas page, CloudFront flat-rate pricing plans page).
Unconfirmed (verify): Anycast static IP specifics; CloudFront upload limits via PUT behaviours; Security Savings Bundle; flat-rate plan inclusions beyond the pricing page table; Global Accelerator vs CloudFront edge-case claims.

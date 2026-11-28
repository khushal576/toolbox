# Amazon CloudFront – 2. Security, signed access, TLS, WAF, geo restriction and logging

Short notes. Each point is a fact you can be asked about.

## A. Securing the viewer connection (HTTPS)
- **Viewer protocol policy** per behavior: HTTP and HTTPS, **Redirect HTTP to HTTPS**, or HTTPS only.
- **TLS certificates**: use **ACM public certificates in us-east-1** (free) or imported/IAM certificates. **One certificate per distribution** (can include SANs/wildcards).
- **SNI** (free, modern browsers) vs **dedicated IP custom SSL** (about $600/month per certificate, for legacy clients; limited quota of 2).
- **Security policy** = minimum TLS version and ciphers (for example `TLSv1.2_2021`); newer policies add TLS 1.3. Choose the latest unless legacy clients require older.
- **Origin protocol policy**: HTTPS only to origin; validate origin certificates (CloudFront requires a trusted CA cert on custom origin; no self-signed).
- **HSTS** and security headers via **response headers policies**.
- **mTLS (viewer mutual TLS)** with **trust stores** (CA bundle) is available **(verify)**; trust stores 20 per account, 25 certs per bundle.
- **Post-quantum hybrid TLS** support may be available **(verify)**.
- **Field-level encryption**: encrypt up to 10 sensitive POST fields (≤16 KB each, request body ≤1 MB) at the edge with your public key; only the holder of the private key (a downstream app) can decrypt.

## B. Restricting who can access content
| Mechanism | What it does | Use for |
|---|---|---|
| **Signed URLs** | Time-limited URL for a **single object** (path), optionally IP-restricted | Per-file downloads (reports, datasets) |
| **Signed cookies** | Grant access to **multiple files** (path pattern) | Streaming/video segments, whole sites/areas |
| **Origin Access Control (OAC)** | Only CloudFront can read the S3 origin | Private S3 buckets |
| **Geo restriction** | Allow/deny countries (allowlist or blocklist) at distribution level | Licensing/compliance |
| **WAF web ACL** | L7 filtering, rate limiting, bot control | Abuse protection |
| **Custom header secret** | Origin validates a shared header | Non-S3 origins |
| **VPC origin / managed prefix list** | Origin reachable only from CloudFront | Private ALB/EC2 |
| **Field-level encryption** | Protects selected form fields end-to-end | Sensitive form data |
| **Lambda@Edge/CloudFront Functions auth** | JWT/token validation | Custom auth |
- **Signed URL/cookie mechanics**:
  - Use **key groups** (preferred; trusted key groups with public keys) rather than the legacy root-account **CloudFront key pairs**.
  - Behavior must have **"Restrict viewer access"** enabled with the trusted key group(s).
  - Policy: **canned policy** (resource URL + expiry; shorter URL) or **custom policy** (adds start time, IP range; supports wildcards).
  - The application (Lambda/EC2) signs with the **private key** (store in Secrets Manager); CloudFront validates with the public key.
  - Limits: **5 public keys per key group**, **4 key groups per behavior**, **10 key groups per account** (adjustable).
- **When to use signed URL vs S3 presigned URL**: CloudFront signed URLs for **cached/edge delivery**, geo-restriction/WAF, custom domains, and cheaper egress; S3 presigned URLs for direct S3 access (including uploads) without a distribution.
- **Geo restriction** is country-level (uses third-party geo-IP DB); for finer rules use **WAF geo match** or Lambda@Edge.
- **Referer-based** or **IP-based** restrictions via WAF or functions.
- **Bucket policy for OAC**: `Principal: {"Service":"cloudfront.amazonaws.com"}`, `Condition: StringEquals AWS:SourceArn = arn:aws:cloudfront::<acct>:distribution/<id>`; for **SSE-KMS** objects also allow the same principal in the **KMS key policy** (`kms:Decrypt`, `kms:GenerateDataKey*`).
- **S3 Block Public Access** stays on when using OAC.
- **Public S3 website endpoints** can't use OAC; prefer REST endpoint + OAC.

## C. DDoS and WAF
- **AWS Shield Standard** is automatic for CloudFront; **Shield Advanced** adds detection, SRT and cost protection (CloudFront distributions are protected resources).
- **AWS WAF** (CLOUDFRONT scope, created in **us-east-1**): rate-based rules, managed rule groups, bot control; up to **100 associations** per web ACL (adjustable). Body inspection default 16 KB, up to **64 KB**.
- **CloudFront flat-rate pricing plans** (new): per-distribution monthly plans (Free, Pro, Business, Premium) bundling data transfer, requests, **WAF, DDoS protection, Route 53, logging allowances, S3 credits** with no overage charges; useful for predictable cost **(verify details; see below)**.
- **Origin cloaking**: combine VPC origins or prefix-list SG + secret header so attackers can't bypass CloudFront.
- **Rate limiting** at the edge with WAF protects origins from floods.

## D. Logging and monitoring
- **Standard logs (access logs)**: delivered to **S3** (or CloudWatch Logs / Firehose via the newer logging v2) within minutes; include `date`, `time`, `x-edge-location`, `sc-bytes`, `c-ip`, `cs-method`, `cs(Host)`, `cs-uri-stem`, `sc-status`, `cs(Referer)`, `cs(User-Agent)`, `x-edge-result-type`, `x-edge-request-id`, `time-taken`, `cs-protocol`, `ssl-protocol`, `ssl-cipher`, etc.
- **Real-time logs**: stream to **Kinesis Data Streams** within seconds; choose fields and sampling rate (1–100%); 150 real-time log configurations per account.
- **CloudWatch metrics** (`AWS/CloudFront`, us-east-1): **default**: `Requests`, `BytesDownloaded`, `BytesUploaded`, `4xxErrorRate`, `5xxErrorRate`, `TotalErrorRate`; **additional metrics** (extra cost): `CacheHitRate`, `OriginLatency`, `ErrorRateByStatusCode`.
- **Reports in console**: cache statistics, popular objects, top referrers, usage, viewers (devices/browsers/locations).
- **CloudTrail** logs CloudFront control-plane changes; **Config** records distributions.
- **Analyze logs with Athena** (partitioned S3 logs; Parquet conversion via Glue/CTAS) or OpenSearch.
- **Alarms**: `5xxErrorRate` > 1%, `OriginLatency`, WAF block spikes, cache hit rate drops.
- **Troubleshoot** with headers `x-cache`, `x-amz-cf-pop`, `x-amz-cf-id`, `via`, `age`.

## E. Cost (pay-as-you-go summary)
- **Data transfer out to the internet** (tiered by Region and volume; cheaper per GB than direct from S3/EC2 beyond free tier); **free tier**: 1 TB data transfer out and 10 million HTTP/HTTPS requests per month (always free) **(verify)**.
- **HTTP/HTTPS requests** priced per 10,000 (HTTPS more than HTTP; varies by Region).
- **Data transfer from AWS origins to CloudFront is free** (S3, ALB, etc.); from non-AWS origins you pay normal egress at the origin.
- **Invalidations**: first 1,000 paths per month free, then about $0.005 per path.
- **Origin Shield**: per 10,000 requests.
- **Functions**: CloudFront Functions per million invocations; Lambda@Edge per request + GB-second.
- **Real-time logs** per million lines; **additional metrics** per metric; **dedicated IP custom SSL** about $600/month.
- **Field-level encryption** per 10,000 requests.
- **WAF/Shield Advanced** billed separately (Shield Advanced fee covers some WAF usage).
- **Flat-rate plans** (per distribution per month, no overages): **Free $0** (1M requests, 100 GB, 5 GB S3 credit; no logging), **Pro $15** (10M requests, 50 TB, 50 GB S3), **Business $200** (125M requests, 50 TB, 1 TB S3), **Premium $1,000** (500M requests, 50 TB, 5 TB S3), **Custom** via sales. Each includes serverless edge compute and a TLS certificate **(per pricing page)**.
- **Cost levers**: higher cache hit ratio, compression, right price class, Origin Shield for expensive origins, avoid unnecessary invalidations, long TTL for static, CloudFront Functions over Lambda@Edge, S3 + CloudFront instead of direct S3 egress for popular objects, savings via **CloudFront Security Savings Bundle** commitment **(verify)**.

## F. Troubleshooting (symptom → cause → fix)
- **403 from S3 origin** → OAC/bucket policy mismatch, KMS key policy missing CloudFront, object missing (S3 returns 403 for missing keys if no list permission), Block Public Access + OAI misconfig.
- **403/502 to custom origin** → origin SG blocks CloudFront, TLS mismatch (certificate name, protocols), origin timeouts, missing custom header.
- **502 Bad Gateway** → can't connect to origin, SSL negotiation failure, invalid response; **504 Gateway Timeout** → origin response timeout (increase to up to 120 s or fix origin).
- **Stale content** → TTL too long; invalidate or version files.
- **Low cache hit rate** → cache key too wide, `Cache-Control: no-store/private`, query string randomization, small TTL.
- **CORS errors** → forward `Origin` header via origin request policy and add response headers policy; S3 CORS config.
- **Wrong domain/cert error** → alternate domain name missing, certificate not in us-east-1 or doesn't cover the name.
- **Access denied for signed URLs** → wrong key group, expired policy, wrong resource pattern, clock skew, behavior not restricted.
- **Different content per location** → eventual consistency of caches, geo/headers in key.
- **Increase in 5xx** → origin overloaded; enable Origin Shield, scale origin, add origin failover.
- **Logs missing** → bucket ACL/permissions (standard logs need ACL write for `awslogsdelivery`; v2 uses delivery sources), wrong prefix.

## G. Exam skills mapping
- **1.2.8 Create data APIs**: data API delivery.
- **4.3.4 Encryption in transit or before transit**: encryption in transit (TLS).
- **1.1.4 Consume data APIs**: consuming data APIs.

## H. Scenarios: "If X → Y, because Z"
- **If** paying subscribers may download a dataset for only **1 hour**, **then** give them **CloudFront signed URLs** with a 1-hour expiry, signed with a **key group**. Turn on **"Restrict viewer access"** on the cache behavior and trust that key group. Your app signs the URL with a **private key** (stored in **AWS Secrets Manager**), and CloudFront checks it with the matching **public key**. **This works because** the policy inside the URL holds the expiry time, so CloudFront rejects the URL once it has expired. Key groups are preferred over legacy root-account key pairs.
- **If** a whole video library needs authentication, **then** use **CloudFront signed cookies**. **This works because** one signed cookie grants access to **many files** that match a path pattern (for example all video segments), while a signed URL covers only **one file**.
- **If** only users in certain countries may download, **then** use CloudFront **geo restriction** (an allowlist or blocklist of countries for the whole distribution), or an **AWS WAF** (web application firewall) **geo match** rule for finer rules. **This works because** CloudFront looks up each viewer's country from its IP address (using a third-party geo-IP database) and blocks the others at the edge. Geo restriction works only at **country level**.
- **If** sensitive form fields must stay protected end to end, **then** use **field-level encryption**. CloudFront encrypts up to **10** chosen POST fields (each up to **16 KB**, request body up to **1 MB**) at the edge with your **public key**. **This works because** only the downstream app that holds the **private key** can decrypt those fields, so servers in between never see them in plain text.
- **If** you must stop traffic that bypasses CloudFront and goes straight to the **Application Load Balancer (ALB)**, **then** use a **VPC origin**, or a **security group** that allows only the **CloudFront managed prefix list** (`com.amazonaws.global.cloudfront.origin-facing`) plus a **secret custom header** the origin checks. **This works because** the ALB then accepts traffic only from CloudFront (this is called **origin cloaking**), so attackers cannot reach it directly.
- **If** requests spike maliciously, **then** add an **AWS WAF rate-based rule** (web ACL in `CLOUDFRONT` scope, created in **us-east-1**) and rely on **AWS Shield**. **Shield Standard** is automatic for CloudFront; **Shield Advanced** adds detection, the Shield Response Team (SRT) and cost protection. **This works because** WAF throttles abusive clients at the edge, so the flood never reaches your origin.
- **If** analysts need CDN usage analytics, **then** send **standard logs** (access logs) to **Amazon S3** and query them with **Amazon Athena** (SQL on S3 files). **This works because** each log line holds per-request fields such as time, edge location, client IP, URL, status code and bytes sent. Logs arrive **within minutes**; keep them partitioned (and convert to Parquet with AWS Glue or CTAS) for cheaper queries.
- **If** you need visibility within seconds, **then** use **real-time logs** streamed to **Amazon Kinesis Data Streams**. **This works because** real-time logs arrive **within seconds**, while standard logs are delayed by minutes. You choose the fields and a sampling rate (**1–100%**), and you pay per million log lines.
- **If** S3 objects are encrypted with **SSE-KMS** and CloudFront returns **403**, **then** add the CloudFront service principal (`cloudfront.amazonaws.com`) to the **AWS Key Management Service (KMS) key policy** with `kms:Decrypt` and `kms:GenerateDataKey*`. **This works because** CloudFront must decrypt each object before serving it, and the bucket policy alone does not grant use of the key.

Verified from AWS docs on 2026-11-09 (CloudFront quotas page, CloudFront flat-rate pricing plans page).
Unconfirmed (verify): free tier amounts (1 TB/10M); invalidation price; mTLS and post-quantum availability; logging v2 delivery targets; tag invalidation; additional metrics list; Security Savings Bundle; dedicated IP SSL price; WAF association quota.

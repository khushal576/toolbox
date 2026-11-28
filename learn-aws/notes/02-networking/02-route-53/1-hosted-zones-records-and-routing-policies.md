# Amazon Route 53 – 1. Hosted zones, records and routing policies

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **Amazon Route 53** is a highly available, scalable **DNS** service with **domain registration**, **health checking** and **traffic routing**, plus **Route 53 Resolver** for VPC/hybrid DNS.
- It is a **global** service (control plane in `us-east-1`; quotas viewed in us-east-1). It has a **100% availability SLA** for DNS queries.
- The name comes from **TCP/UDP port 53**.
- Pick it when: you need DNS for public sites/APIs, **private DNS inside VPCs**, **failover and latency-based routing**, **hybrid DNS**, or to name AWS resources (CloudFront, ALB, API Gateway, S3 websites, endpoints).
- Data-engineering relevance: friendly names for Redshift/RDS/OpenSearch endpoints, **private hosted zones** for data services, **Resolver rules** so on-prem can resolve VPC endpoints, failover for data APIs, DNS for PrivateLink service names.
- DEA-C01 touchpoints: networking for ingestion/serving (private DNS for endpoints, hybrid DNS), Multi-Region failover patterns.

## B. Hosted zones
- A **hosted zone** is a container of **records** for a domain and its subdomains.
- **Public hosted zone**: answers queries from the internet. On creation Route 53 assigns **4 name servers** (a delegation set); you set these NS records at your registrar.
- **Private hosted zone (PHZ)**: answers only within **associated VPCs**. Requires VPC DNS attributes **enableDnsSupport** and **enableDnsHostnames** on.
- **Quotas**: **500 hosted zones** per account (adjustable); **10,000 records** per hosted zone (adjustable with extra charge); up to **300 VPC associations per PHZ** (use Route 53 **Profiles** for more).
- **Cross-account PHZ association**: create an **authorization** in the zone-owner account, then **associate** from the VPC-owner account using CLI/API (console cannot do both sides).
- **Split-horizon DNS**: a public and a private hosted zone with the **same name**; inside the VPC the private zone wins; outside, the public answers.
- **Reusable delegation sets**: reuse the same 4 name servers across multiple hosted zones (100 per account).
- **Subdomain delegation**: create NS records in the parent zone pointing at the child zone's name servers.
- **Hosted zone fees**: about **$0.50 per hosted zone per month** (first 25), then less; extra for >10,000 records **(verify)**.
- **DNSSEC signing** for public hosted zones using KMS keys (see file 2).

## C. Records
- **Record fields**: name, type, TTL, value(s), routing policy, set identifier, health check.
- **Common types**: **A** (IPv4), **AAAA** (IPv6), **CNAME** (alias to another name), **MX**, **TXT**, **NS**, **SOA**, **SRV**, **PTR**, **CAA**, **DS**, **NAPTR**, **SPF** (deprecated, use TXT), **HTTPS/SVCB**.
- **CNAME restriction**: **cannot be created at the zone apex** (example.com); a CNAME cannot coexist with other records of the same name.
- **Alias records (Route 53 specific)**: point a name to an AWS resource **and work at the zone apex**. Targets: **CloudFront, ELB (ALB/NLB/CLB), API Gateway custom domain, Elastic Beanstalk, S3 website endpoint, VPC interface endpoint, Global Accelerator, another record in the same hosted zone**.
  - **Free queries** to alias records pointing at AWS resources (CNAME queries are billed).
  - Alias has no TTL setting (uses the target's TTL).
  - Alias can have **Evaluate Target Health** (uses the target's health).
  - Alias is not visible as a CNAME to the world (looks like A/AAAA).
- **TTL**: how long resolvers cache. Lower TTL (60 s) before cutovers; higher TTL (300–86400 s) reduces query cost and latency.
- **Record sets** (same name+type) can hold up to **400 values**; routing-policy record sets with same name/type up to **100** (geoproximity 30).
- **Wildcard records** `*.example.com` match only names with no more specific record.
- **Change propagation**: Route 53 changes propagate to its global servers in about **60 seconds**; resolver caches obey TTLs.
- **ChangeResourceRecordSets**: batch up to 1,000 `ResourceRecord` elements (UPSERT counts double) and 32,000 characters.
- **Records for AWS endpoints**: Redshift/RDS/OpenSearch endpoints are DNS names; create a **CNAME** (not alias) from your friendly name to them, or use private zones.

## D. Routing policies (exam favourite)
| Policy | What it does | Health checks | Typical use |
|---|---|---|---|
| **Simple** | One record, one or more values (random order) | No (no per-value health) | Single resource |
| **Weighted** | Splits traffic by weights 0–255 | Yes | A/B tests, canary/blue-green, gradual migration |
| **Latency-based** | Routes to the AWS Region with lowest latency to the user | Yes | Multi-Region apps |
| **Failover** | Primary/secondary; secondary used when primary unhealthy | Required for primary | Active-passive DR |
| **Geolocation** | Routes by user's country/continent/state (default record required for unmatched) | Yes | Localization, compliance, content restriction |
| **Geoproximity** | Routes by geographic distance with a **bias** to shift traffic; needs **Traffic Flow** (or newer record-level support) | Yes | Shift load between Regions |
| **IP-based** | Routes by client IP **CIDR collections** (ISP/enterprise ranges) | Yes | Route known networks to specific endpoints |
| **Multivalue answer** | Returns up to **8 healthy records** | Yes (per record) | Simple client-side load distribution |
- **Weighted routing**: weight 0 = no traffic (unless all are 0, then equal); total weights needn't equal 100.
- **Latency** is measured between users' networks and AWS Regions (not your servers) and based on past measurements.
- **Failover** requires a health check on the primary; the secondary can be an S3 static page, another Region, or on-prem.
- **Geolocation vs geoproximity**: geolocation = "where the user is" (rules); geoproximity = "how far from the resource" (distance + bias).
- **Combine policies** with **alias to other record sets** (nested), or **Traffic Flow** visual policies (traffic policy records: 5 per account default; 50 policies; versions 1,000) for complex trees.
- **CIDR collections**: 5 per account, 1,000 CIDR blocks per collection (IP-based routing).
- **Set identifier** is required for routing-policy records.
- **Cost**: queries ~ $0.40 per million standard; latency/geo/IP-based about $0.60–$0.70 per million; alias to AWS resources free **(verify)**.

## E. Health checks
- **Types**:
  - **Endpoint health check**: Route 53 health checkers (from multiple Regions) call **HTTP, HTTPS, or TCP**; optional string matching in first **5,120 bytes** of response; **fast** interval 10 s or standard 30 s; failure threshold 1–10.
  - **Calculated health check**: combines up to **255 child checks** with AND/OR/at-least-N.
  - **CloudWatch alarm health check**: status follows a CloudWatch alarm (use for private resources/metrics such as an RDS metric).
- **Health checks cannot reach private IPs directly** (checkers are on the public internet) → use **CloudWatch alarm-based** checks or expose a public health endpoint; or monitor via Lambda that publishes a metric.
- **Health checker IP ranges** must be allowed in firewalls/SGs.
- **Evaluate Target Health** on alias records avoids creating separate checks for ELB/CloudFront targets.
- **Invert health check** option; **disable** health check; **latency graphs** and health data in CloudWatch (`HealthCheckStatus`, `HealthCheckPercentageHealthy`, `ChildHealthCheckHealthyCount`) in **us-east-1**.
- **Quota**: **200 health checks** per account (adjustable).
- **DNS failover timing** ≈ (interval × threshold) + TTL; fast interval 10 s + threshold 3 + TTL 60 s ≈ ~1.5–2 minutes.
- **Cost**: per health check per month (AWS endpoints cheaper), extra for fast interval, HTTPS, string matching.

## F. Domain registration and transfers
- **Domain registrar** for many TLDs (.com, .org, .io etc.); registration includes WHOIS privacy, auto-renew, transfer lock.
- **Domains per account**: 20 default for new accounts (adjustable).
- Route 53 can host DNS for domains registered elsewhere; transfers need unlock + auth code; transfers take days.
- Registration creates a **public hosted zone** automatically ($0.50/month).

## G. Typical designs
- **Active-active multi-Region API**: latency-based alias records to regional ALB/API Gateway + health checks.
- **Active-passive DR**: failover records (primary ALB, secondary static S3 site or DR Region).
- **Blue/green cutover**: weighted records 100/0 → 90/10 → 0/100 with low TTL.
- **Data API behind CloudFront**: alias A/AAAA to distribution; origin ALB private via VPC origins.
- **Private data platform**: PHZ `data.internal.company.com` with records to Redshift/RDS/OpenSearch endpoints, associated with all VPCs (or via Profiles).
- **Cross-account PHZ sharing**: associate VPCs from multiple accounts with one PHZ (authorization + association), or Profiles with RAM.

## H. Exam skills mapping
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: private DNS for endpoints and PrivateLink.
- **2.3.6 Resiliency and availability of data**: resiliency and availability (failover routing).

## I. Scenarios: "If X → Y, because Z"
- **If** you must point the **zone apex** `example.com` (the bare domain with nothing in front) at an **Application Load Balancer (ALB)**, **then** create a Route 53 **alias A record** that targets the ALB. **This works because** a **CNAME** record (which points one name at another name) **cannot be created at the zone apex**, while an alias record is a Route 53 feature that points a name straight at an AWS resource and **does work at the apex**. The alias uses the target's own TTL.
- **If** traffic should move gradually from an old stack to a new one, **then** use **weighted routing** with a **low Time To Live (TTL)**, for example **60 seconds**. Start at weights **100/0**, then **90/10**, and end at **0/100**. **This works because** weighted routing splits traffic by weights from **0 to 255**, so you control the share each stack gets, and a low TTL means resolvers stop caching the old answer quickly. A weight of **0** sends no traffic, and weights do not need to add up to 100.
- **If** users should reach the AWS Region with the lowest delay, **then** use **latency-based routing** with **health checks** on each Regional record. **This works because** Route 53 picks the Region with the lowest latency between the user's network and AWS Regions, based on past measurements (not live tests of your servers). The health checks stop an unhealthy Region from being returned.
- **If** the primary Region fails and you need an automatic cutover, **then** use **failover routing** with a **health check on the primary** record. **This works because** failover routing has a primary and a secondary record, and Route 53 answers with the secondary when the primary's health check says it is unhealthy. The secondary can be an **Amazon S3** static page, another Region, or on-premises. The health check on the primary is **required**, and cutover takes about (interval × failure threshold) + TTL, roughly **1.5–2 minutes** with fast checks.
- **If** EU users must be served only by EU endpoints, **then** use **geolocation routing**: a record for **Europe** that points to the EU endpoint, plus a **default** record that points to a global endpoint. **This works because** geolocation routes by where the user is (country, continent or state). The default record is **required** to answer users who match no location rule.
- **If** you need to shift traffic between Regions gradually based on geography, **then** use **geoproximity routing** with a **bias**. **This works because** geoproximity routes by the distance between the user and the resource, and the bias makes a Region's area bigger or smaller so it pulls in more or less traffic. It needs **Route 53 Traffic Flow** (visual routing policies) or the newer record-level support **(verify)**.
- **If** the endpoint is in a private subnet and you still need DNS failover, **then** use a **CloudWatch alarm health check**, whose status follows an **Amazon CloudWatch** alarm on a metric (for example an Amazon RDS metric). **This works because** Route 53 health checkers run on the **public internet** and **cannot reach private IP addresses** directly. Another option is to expose a public health endpoint.
- **If** a Virtual Private Cloud (VPC) in another AWS account must resolve your **private hosted zone (PHZ)**, **then** first create an **authorization** in the zone-owner account, then **associate** the VPC from the VPC-owner account using the CLI or API. For many VPCs, use **Route 53 Profiles** shared with **AWS Resource Access Manager (RAM)** instead. **This works because** a cross-account association needs **both steps** in this order, and the console cannot do both sides.
- **If** DNS query costs are too high, **then** use **alias records** for AWS resources and set **longer TTLs** (for example **300–86,400 seconds**). **This works because** queries to alias records that point at AWS resources are **free** **(verify)**, while standard queries cost about **$0.40 per million** **(verify)**. A higher TTL lets resolvers cache answers longer, so fewer queries reach Route 53.

Verified from AWS docs on 2026-11-09 (Route 53 quotas page).
Unconfirmed (verify): hosted zone/query/health check prices; propagation time (about 60 s); CloudWatch metric names; geoproximity record-level support; health check string match bytes; fast interval limits.

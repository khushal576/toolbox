# Amazon Route 53 – 2. Resolver, hybrid DNS, DNS Firewall, DNSSEC and Profiles

Short notes. Each point is a fact you can be asked about.

## A. Route 53 VPC Resolver (formerly Resolver)
- Every VPC has an **Amazon-provided DNS resolver** at the **VPC base address + 2** (for example 10.0.0.2) and **169.254.169.253**. It resolves: public names, **private hosted zones** associated with the VPC, **VPC-internal EC2 names**, and **interface endpoint private DNS**.
- **Limit**: **1,024 packets per second per network interface** to the resolver (not adjustable).
- **Requires** `enableDnsSupport` (and `enableDnsHostnames` for hostnames/private DNS).
- **Resolver endpoints** make hybrid DNS work:
  - **Inbound endpoint**: on-premises DNS servers **forward queries into** the VPC resolver (to resolve PHZ names, endpoint names). Needs ≥2 IPs in ≥2 AZs; SG allows TCP/UDP 53.
  - **Outbound endpoint**: VPC resolver **forwards queries out** to on-prem or other DNS via **forwarding rules**.
- **Forwarding rules**: domain name → target IPs (up to 6 IPs per rule); **system rules** override (`AWS internal`); **rules shared across accounts** with RAM and **associated with VPCs**.
- **Quotas**: **4 endpoints** per Region, **6 IPs per endpoint**, **1,000 rules** per Region, **2,000 rule-VPC associations**; each endpoint IP handles about **10,000 UDP QPS** (lower, down to ~1,500, with connection tracking or NLB paths). Add ENIs when usage exceeds 50% of capacity.
- **Cost**: endpoint ENI-hours (about $0.125/hour each) + queries processed per million **(verify)**.
- **Autodefined rules** for reverse lookups.
- **Resolver on Outposts** exists (not exam core).
- **DNS over HTTPS/TLS** support on Resolver endpoints (DoH/DoT) **(verify)**.

## B. Hybrid DNS patterns
- **On-prem → AWS**: conditional forwarder on corporate DNS for `corp.aws.internal` and `*.amazonaws.com` privatelink names → **Inbound endpoint** IPs.
- **AWS → on-prem**: forwarding rule `corp.example.com` → on-prem DNS IPs via **Outbound endpoint**; share the rule with RAM to all accounts/VPCs.
- **Centralized DNS account**: PHZs and resolver endpoints in a shared-services VPC; other VPCs associated or use **Profiles**.
- **Interface endpoint DNS from on-prem**: forward `*.amazonaws.com` (or the service-specific domain like `glue.us-east-1.amazonaws.com`) to the inbound endpoint so names resolve to endpoint ENI IPs; ensure routes via VPN/DX/TGW.
- **Active Directory integration**: forward AD domain queries to AD DNS controllers via outbound rules.
- **Avoid loops**: do not forward the same domain in both directions.

## C. Route 53 Profiles
- **Profiles** bundle **PHZ associations, Resolver rules, DNS Firewall rule group associations, query logging configs** into one resource that can be **shared (RAM)** and **applied to many VPCs/accounts**.
- Quotas: **5 profiles** per account/Region; **1,000 VPCs** per profile; **5,000 PHZs** per profile; **1,000 Resolver rules** per profile; 5 DNS Firewall rule groups per profile.
- Solves the **300 VPCs-per-PHZ** limit and simplifies multi-account DNS governance.

## D. Resolver DNS Firewall
- **DNS Firewall** filters **outbound DNS queries from VPCs** using **domain lists** and rule groups: actions **ALLOW, ALERT, BLOCK** (BLOCK can return NODATA, NXDOMAIN or an override CNAME).
- **Managed domain lists** (AWS-managed: malware, botnet C2, aggregate threats, ...) and **custom lists** (up to 250,000 domains per S3 file; 100,000 domains total across lists default).
- **Rule groups** (up to 100 rules each; 5 rule groups per VPC), priorities, **fail-open or fail-closed** behaviour when the firewall can't evaluate.
- Managed by **Firewall Manager** across accounts.
- Protects against **DNS exfiltration** and malware callbacks; complements Network Firewall and security groups.
- **Query logging** lets you review what was blocked.

## E. Query logging
- **Public DNS query logs** (public hosted zones): to **CloudWatch Logs in us-east-1** only; 1 query-log config per hosted zone.
- **Resolver query logs** (VPC): log DNS queries from VPC resources to **CloudWatch Logs, S3, or Firehose**; 20 configs per Region; 100 VPC associations; shareable with RAM.
- Use for security investigations (suspicious domains), troubleshooting resolution failures, and data-exfil detection (with GuardDuty DNS logs analyzed internally).
- Fields: query name/type/class, response code, answers, source IP/VPC/instance, transport.
- **Cost**: vended log ingestion/storage.

## F. DNSSEC
- **DNSSEC signing for public hosted zones**: Route 53 manages **zone signing keys (ZSK)**; you provide a **key-signing key (KSK)** backed by an **asymmetric KMS key (ECC_NIST_P256, in us-east-1)**. Up to **2 KSKs per hosted zone**.
- Steps: create KSK → enable signing → create a **DS record** in the parent zone (registrar) to establish the chain of trust.
- **Protects** against DNS spoofing/cache poisoning by letting resolvers validate responses; **does not encrypt** queries.
- Enable **alarms** on `DNSSECInternalFailure` and `DNSSECKeySigningKeysNeedingAction`.
- Risks: wrong DS record or disabled KSK can cause **domain resolution failures**; follow the procedure carefully; keep TTLs low during rollout.
- **Resolver DNSSEC validation**: VPC Resolver can validate DNSSEC for public domains **(optional setting)**.
- Private hosted zones do **not** support DNSSEC.

## G. Route 53 Application Recovery Controller (ARC)
- **ARC** coordinates **multi-Region/multi-AZ failover** with **routing controls** (highly available on/off switches that drive Route 53 health checks), **readiness checks**, and **zonal shift/autoshift** for load balancers.
- Use for **controlled, safe failover** of critical apps/data APIs across Regions; routing controls live in a 5-Region cluster for resilience.
- Pricing per cluster-hour/readiness check **(verify)**.
- Exam note: ARC = "reliable failover control", not the DNS records themselves.

## H. Common DNS issues (symptom → cause → fix)
- **Name doesn't resolve inside VPC** → `enableDnsSupport` off, PHZ not associated, custom DHCP DNS servers not forwarding.
- **Private DNS for endpoint resolves public IPs** → "Enable private DNS name" off, `enableDnsHostnames` off, PHZ conflicts.
- **On-prem can't resolve AWS names** → no conditional forwarder to inbound endpoint, routing/SG blocked on 53, wrong AZ coverage.
- **Resolver throttling** → > 1,024 pps per ENI; cache, spread, reduce per-request lookups (Spark/Lambda DNS storms).
- **Stale record after change** → TTL caching; lower TTL ahead of changes.
- **Cutover failed** → NS records at registrar don't match hosted zone, DS record mismatch with DNSSEC.
- **Failover not triggering** → health check isn't attached, wrong threshold, secondary unhealthy, alias target health not evaluated.
- **PriorRequestNotComplete / Throttling** → too many `ChangeResourceRecordSets` calls to the same zone.
- **Cross-account PHZ association error** → missing authorization or wrong order.
- **DNS Firewall blocking valid domains** → review rule priority/domain lists; use ALERT first.

## I. Cost summary (indicative US prices)
| Item | Price |
|---|---|
| Hosted zone | about **$0.50 / month** (first 25) |
| Standard queries | about **$0.40 / million** |
| Latency / geo / IP-based queries | about **$0.60–$0.70 / million** |
| Alias queries to AWS resources | **free** |
| Health checks | about **$0.50–$0.75 / month** (AWS endpoints cheaper; extras for HTTPS, string match, fast interval) |
| Resolver endpoint ENI | about **$0.125 / hour** each + per million queries |
| DNS Firewall | per rule group/domain list association + per million queries |
| Query logging | CloudWatch/S3/Firehose costs |
| Domain registration | per TLD yearly |
| Traffic Flow policy record | about **$50 / month** each **(verify)** |
- **Levers**: alias records, higher TTLs, centralize resolver endpoints (share rules), fewer health checks (use Evaluate Target Health), turn off unused query logging.

## J. Limits cheat sheet
| Item | Value |
|---|---|
| Hosted zones | **500** |
| Records per zone | **10,000** |
| VPC associations per PHZ | **300** |
| Health checks | **200** |
| Child checks in calculated check | **255** |
| Traffic policies / policy records | **50 / 5** |
| Reusable delegation sets | **100** |
| Resolver endpoints / IPs per endpoint | **4 / 6** |
| Resolver rules / associations | **1,000 / 2,000** |
| Resolver per-ENI limit | **1,024 pps** |
| DNS Firewall rule groups per VPC | **5** |
| API (Resolver) | 5 requests/s |
| Profiles | 5 per Region |

## K. Exam skills mapping
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: private DNS for endpoints and PrivateLink.
- **2.3.6 Resiliency and availability of data**: resiliency and availability (failover routing).

## L. Scenarios: "If X → Y, because Z"
- **If** on-premises extract, transform, load (ETL) jobs must resolve the private name of an **Amazon Redshift** cluster or an **interface endpoint**, **then** create a **Route 53 Resolver inbound endpoint** in the VPC and add a **conditional forwarder** on the corporate DNS that sends those domains to the inbound endpoint's IPs. **This works because** on-premises DNS cannot see **private hosted zones** or VPC names by itself; the inbound endpoint lets it forward queries into the VPC resolver. The endpoint needs at least **2 IPs in 2 Availability Zones (AZs)**, and its security group must allow **TCP/UDP port 53**.
- **If** VPC workloads must resolve corporate domains such as `corp.example.com`, **then** create a **Resolver outbound endpoint** and a **forwarding rule** that sends that domain to the on-premises DNS IPs, and share the rule with **AWS Resource Access Manager (RAM)** to all accounts and VPCs. **This works because** the outbound endpoint lets the VPC resolver forward queries out to on-premises DNS. Do not forward the same domain in both directions, or you create a loop.
- **If** **800 VPCs** need the same private hosted zones (PHZs) and Resolver rules, **then** put them in a **Route 53 Profile** and share it with **AWS Resource Access Manager (RAM)**. A Profile bundles PHZ associations, Resolver rules, DNS Firewall rule groups and query logging configs into one shareable resource. **This works because** a PHZ can be associated with only **300 VPCs**, while one Profile can be applied to up to **1,000 VPCs**.
- **If** VPC workloads must be stopped from reaching known malware domains, **then** use **Route 53 Resolver DNS Firewall** with **AWS-managed domain lists** (for example malware and botnet lists). **This works because** DNS Firewall filters **outbound DNS queries** from VPCs and can **BLOCK**, **ALERT** or **ALLOW** each domain, so a bad name never resolves. Query logging lets you review what was blocked.
- **If** you must protect a public domain against DNS spoofing, **then** turn on **Domain Name System Security Extensions (DNSSEC) signing** for the public hosted zone. You create a **key-signing key (KSK)** backed by an asymmetric **AWS Key Management Service (KMS)** key in us-east-1 **(verify)**, enable signing, then add a **DS record** in the parent zone at the registrar. **This works because** resolvers can then **validate** that answers are real, which stops spoofing and cache poisoning. DNSSEC **does not encrypt** queries, and a wrong DS record can break resolution of the domain.
- **If** failover must be controlled by an operator and be safe, **then** use **Route 53 Application Recovery Controller (ARC)** **routing controls**. **This works because** routing controls are highly available on/off switches that drive Route 53 health checks, so flipping a switch moves traffic. They live in a cluster across **5 Regions** for resilience **(verify)**. ARC controls the failover; it is not the DNS records themselves.
- **If** DNS lookups from Apache Spark executors overload the VPC resolver, **then** **cache** DNS answers, **reduce** lookups per request, and **spread** the load across more network interfaces. **This works because** the Amazon-provided resolver allows only **1,024 packets per second per network interface**, and this limit **cannot be raised**.
- **If** you need an audit trail of DNS requests made from VPCs, **then** turn on **Resolver query logging** to **Amazon S3** or **Amazon CloudWatch Logs** (Firehose is also supported). **This works because** it records each query's name, type, response code and answers, plus the source IP, VPC and instance. You can use the logs for security investigations and troubleshooting.

Verified from AWS docs on 2026-11-09 (Route 53 quotas page).
Unconfirmed (verify): endpoint hourly price and DoH/DoT; Traffic Flow price; ARC pricing and architecture details; DNSSEC KMS key region/spec; DNS Firewall fail mode behaviours; managed domain list names.

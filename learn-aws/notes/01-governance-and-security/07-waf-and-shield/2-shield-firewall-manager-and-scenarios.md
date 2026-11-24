# AWS WAF and Shield – 2. AWS Shield, Firewall Manager, network defences and scenarios

Short notes. Each point is a fact you can be asked about.

## A. AWS Shield overview
- **AWS Shield** is a managed **DDoS protection** service. Two tiers: **Shield Standard** (automatic, free) and **Shield Advanced** (paid, extra detection, response and cost protection).
- DDoS types: **volumetric** (UDP reflection floods), **protocol/state-exhaustion** (SYN floods), **application layer** (HTTP floods).
- Shield focuses on **L3/L4** (network and transport); **L7** is handled by **WAF** (rate-based rules) and, for Advanced, a managed L7 DDoS rule group.
- DEA-C01 relevance: choosing the right control to protect public ingestion/API endpoints (Shield vs WAF vs security group vs NACL vs Network Firewall).

## B. Shield Standard
- **Free and always on** for all AWS customers; no enablement or configuration.
- Protects against the **most common L3/L4 attacks** on AWS edge and infrastructure: applies to **CloudFront**, **Route 53**, and, at AWS network level, resources like **ELB** and **EC2** public IPs.
- Gives no per-customer visibility, no cost protection, no response team.
- Pair with **CloudFront + Route 53** for best absorption (global edge capacity).

## C. Shield Advanced
- **Subscription**: about **$3,000 per month**, with a **1-year commitment** that **auto-renews**; billed per **payer account** (organization-level covers linked accounts). Plus **data transfer out** usage fees on protected resources (CloudFront, ELB, EC2/EIP, Global Accelerator; e.g., ALB about $0.05/GB example) **(verify)**.
- **Protected resource types**: **CloudFront distributions**, **Route 53 hosted zones**, **Global Accelerator accelerators**, **Application Load Balancers**, **Classic Load Balancers**, **Network Load Balancers** (via EIP), **Elastic IP addresses** (EC2 and NLB) **(verify exact list)**.
- You must **explicitly add resources** to protection (individually, by tag, or via **Firewall Manager** policy).
- **Features**:
  - **Enhanced detection** and **near-real-time metrics/attack diagnostics** in CloudWatch and Shield console; **event notifications** via SNS/EventBridge.
  - **Layer 7 mitigation**: **automatic application-layer DDoS mitigation** (Shield creates WAF rules for you) or the **Anti-DDoS managed rule group** **(verify naming)**.
  - **WAF included** at no extra WAF request fees for Shield Advanced protected resources (up to the stated usage, e.g., 50 billion requests per payer at default 1,500 WCUs; Bot Control, Fraud Control and managed rule fees are **not** waived).
  - **Shield Response Team (SRT)** (formerly DRT): AWS experts you can engage during attacks (requires **Business or Enterprise Support**); they can write WAF rules on your behalf if you grant access.
  - **Proactive engagement**: SRT contacts you when health checks show an attack.
  - **Health-based detection** using **Route 53 health checks** to improve detection.
  - **DDoS cost protection**: credits for scaling charges (ELB, CloudFront, Route 53, EC2) caused by a DDoS **if the 1-year commitment is met**.
  - **Global threat dashboard** and **DDoS-event history**.
  - **Protection groups**: group resources so detection considers them together.
  - **Shield Advanced for VPC network ACL automation** (auto-update NACLs) **(verify)**.
- **Network security director** (new posture tool) is **not** included in Shield **(per pricing page)**.

## D. WAF vs Shield vs other controls
| Threat | Best control | Notes |
|---|---|---|
| SQLi / XSS / bad inputs | **WAF managed rules** | L7 content inspection |
| HTTP flood / scraping | **WAF rate-based + Bot Control** | per IP/key limits |
| Volumetric / SYN flood | **Shield Standard/Advanced** | L3/L4 |
| Block a bad IP range at subnet | **NACL** | stateless, subnet level |
| Restrict ports/sources to a service | **Security group** | stateful, instance/ENI level |
| Deep packet inspection, domain filtering, IPS | **AWS Network Firewall** | VPC traffic |
| Org-wide firewall rules | **Firewall Manager** | WAF, Shield, SG, NFW, DNS Firewall |
| DNS exfiltration/malware domains | **Route 53 Resolver DNS Firewall** | outbound DNS |
| Hide origin from internet | **CloudFront + origin access control / VPC origins** | reduces attack surface |
| Sensitive S3 exposure | **Block Public Access + Macie** | not WAF/Shield |
| Threat detection (not prevention) | **GuardDuty** | anomalies |
- **Security group vs NACL**: SG is stateful and allow-only; NACL is stateless, allow and deny, ordered rules.
- **Network Firewall** protects VPC-level traffic (stateful rules, Suricata-compatible, domain lists); WAF protects HTTP apps.
- **Layered pattern**: Route 53 + CloudFront (+ Shield) → WAF → ALB → private subnets with SGs → app. Use **origin protection** (CloudFront prefix list in SG, custom header secret).

## E. AWS Firewall Manager
- **Firewall Manager** centrally configures and enforces protections across **accounts and resources** in an **AWS Organization**.
- Policy types: **AWS WAF**, **Shield Advanced**, **security groups** (common, audit, usage), **Network Firewall**, **Route 53 Resolver DNS Firewall**, **third-party firewalls**, **VPC network ACL**.
- Needs: **Organizations (all features)**, a designated **Firewall Manager administrator account**, **AWS Config enabled** in member accounts.
- **Auto-remediation** attaches protections to new/non-compliant resources; **compliance dashboard** per account.
- **First/last rule groups**: central rule groups run before/after the account's own rules in WAF policies.
- **Cost**: policy per Region per month plus underlying service costs **(verify price)**; limit: up to 10,000 accounts.

## F. Using WAF/Shield with data endpoints (patterns)
- **API Gateway data API**: WAF on the REST API stage (rate limits, SQLi rules); use **usage plans** for client quotas; **resource policies** for IP/VPC restrictions.
- **ALB-hosted tools** (Airflow UI on EKS, Superset, Metabase, Grafana): WAF + **Cognito/OIDC auth on ALB**, restricted by IP or corporate VPN.
- **CloudFront data distribution** for public datasets: signed URLs/cookies, WAF, geo restriction, Shield Advanced for high-value sites.
- **AppSync GraphQL**: WAF with rate limits and depth control (query complexity cannot be inspected by WAF; use AppSync limits).
- **Cognito hosted UI**: WAF + ATP to protect sign-in.
- **Private data services** (Redshift, RDS, MSK): not WAF targets; secure with VPC, SGs, IAM, TLS, PrivateLink.
- **Kinesis/Firehose ingestion over HTTPS** from the internet: front with **API Gateway + WAF** if you need L7 control.

## G. Monitoring and incident response
- **CloudWatch metrics for Shield Advanced**: `DDoSDetected`, `DDoSAttackBitsPerSecond`, `DDoSAttackPacketsPerSecond`, `DDoSAttackRequestsPerSecond`, `VolumeBitsPerSecond` etc. per protected resource.
- **Alarms** on `DDoSDetected` → SNS/PagerDuty.
- **Shield event details** show attack vectors, top contributors, mitigations.
- **WAF logs + metrics** for L7 incidents; **VPC Flow Logs** for L3/L4 analysis.
- **Runbook**: confirm via metrics → scale (auto), apply WAF rate rules, geo-block, engage SRT (Advanced), enable CloudFront in front, contact support.
- **Post-incident**: review SRT report, tune WAF thresholds, add Route 53 health checks.
- **CloudTrail** for Shield/WAF/Firewall Manager API actions.
- **Security Hub** for Firewall Manager and WAF compliance findings.

## H. Limits cheat sheet
| Item | Value |
|---|---|
| Shield Standard | free, automatic |
| Shield Advanced fee | about **$3,000/month**, **1-year** commitment |
| Shield Advanced protected resource types | CloudFront, Route 53, Global Accelerator, ALB/CLB, EIP (NLB/EC2) |
| SRT engagement | needs **Business or Enterprise Support** |
| WAF included with Advanced | up to 50 billion requests/payer/month at 1,500 WCUs |
| Firewall Manager accounts | up to 10,000 |
| WAF web ACLs per Region | 100 |
| NACL rules per NACL | 20 default (adjustable up to 40) **(verify)** |
| Security groups per ENI | 5 default (up to 16) **(verify)** |

## I. Exam skills mapping
- **1.2.8 Create data APIs**: protect data APIs from DDoS.
- **4.1.1 Update VPC security groups**: security groups and NACLs vs Shield/WAF.

## J. Scenarios: "If X → Y, because Z"
- If a public site suffers a large SYN flood → **Shield Standard already absorbs; use CloudFront/Route 53 in front; Advanced for detection, SRT and cost protection**, because L3/L4 attacks are Shield's domain.
- If you need AWS experts during a DDoS and cost protection → **Shield Advanced (with Business/Enterprise Support)**, because SRT access and cost credits are Advanced features.
- If an HTTP flood hits your ALB → **WAF rate-based rule + managed bot rules (or Advanced auto L7 mitigation)**, because L7 floods look like normal HTTP.
- If you must apply the same WAF policy to 50 accounts → **Firewall Manager WAF policy with auto-remediation**, because it deploys and enforces centrally.
- If you want to restrict a database to a single app tier → **security groups (and NACLs for subnet-level denies)**, because WAF/Shield don't protect database ports.
- If you need to block known-bad domains from workloads reaching out → **Route 53 Resolver DNS Firewall or Network Firewall domain lists**, because WAF only inspects inbound HTTP.
- If origin servers are being attacked directly → **restrict origin to CloudFront (managed prefix list / origin access control / VPC origins)**, because bypassing the edge defeats protections.
- If Shield Advanced bills surprise you → **check data transfer out fees and the 1-year commitment**, because usage fees apply on top of the monthly fee.
- If you need per-client daily quotas for your data API → **API Gateway usage plans/API keys**, with WAF for abuse, because WAF rate rules are not quota systems.
- If a NLB-based service needs L7 filtering → **CloudFront or ALB with WAF in front**, because WAF can't attach to NLB.

Verified from AWS docs on 2026-11-03 (AWS WAF quotas, WAF pricing, Shield pricing).
Unconfirmed (verify): exact Shield Advanced protected resource list and EIP/NLB handling; Anti-DDoS rule group naming; Firewall Manager price; NACL and security group limits; Shield network ACL automation; SRT support-plan requirements wording.

# Elastic Load Balancing – 2. ALB, NLB and GWLB features

Short notes. Each point is a fact you can be asked about.

## A. Application Load Balancer (ALB): rules and routing
- **Listener rules** are checked in **priority order** (lowest number first). The **default rule** runs when nothing matches.
- **Rule conditions** (up to 5 condition values per rule; wildcards allowed):
  - **Host header**: `api.example.com` vs `admin.example.com` (many domains on one ALB).
  - **Path**: `/orders/*`, `/reports/*`.
  - **HTTP header**: for example `User-Agent`, a custom `X-Tenant`.
  - **HTTP request method**: GET/POST…
  - **Query string**: `?version=2`.
  - **Source IP**: CIDR ranges (for example an internal-only path).
- **Actions**:
  - **Forward**: to one target group, or **weighted forward to up to 5 target groups** (for example 90% blue / 10% green for canary/blue-green). Optional target group stickiness.
  - **Redirect**: HTTP → HTTPS (common default on port 80), or to another host/path/port (301/302).
  - **Fixed response**: return a status code and body directly (maintenance page, 404, health text).
  - **Authenticate**: **Amazon Cognito** user pools or any **OIDC** provider (Okta, Google, Azure AD) **before** forwarding. The ALB handles login and passes user claims in headers (`x-amzn-oidc-data` JWT).
- **One ALB, many apps**: host- and path-based rules let one ALB serve many services. It saves cost (fewer ALBs) and certificates (SNI).
- **Rules quota**: 100 rules per ALB (adjustable). 5 target groups per forward action. 100 target groups per ALB.
- **URL rewrite / header transforms** (newer; rewrite host/path, modify headers; verify).

## B. ALB: protocols and integrations
- **HTTP/1.1 and HTTP/2** from clients. HTTP/2 to targets with protocol version HTTP2. **gRPC** end-to-end (gRPC health checks with gRPC status codes).
- **WebSockets** supported (long-lived connections; mind the idle timeout).
- **Lambda targets**:
  - The ALB converts the HTTP request to a JSON event and invokes the function (sync). The response must be a JSON with statusCode/headers/body.
  - One function per target group, with a 1 MB response limit (verify).
  - Multi-value headers optional.
  - Lambda processed-bytes LCU is smaller (0.4 GB/h).
- **Headers added by ALB**:
  - **`X-Forwarded-For`** (client IP chain), **`X-Forwarded-Proto`** (http/https), **`X-Forwarded-Port`**.
  - `X-Amzn-Trace-Id` for request tracing.
  - Options to append/preserve/remove XFF and to preserve the host header (verify names).
- **Desync mitigation mode** (defensive, monitor, strictest) protects against HTTP request smuggling.
- **Drop invalid header fields** option.
- **mTLS (mutual TLS)** on HTTPS listeners:
  - **Verify** mode: ALB checks client certificates against a **trust store** (CA bundle in S3) and revocation lists.
  - **Passthrough** mode: sends the client cert to targets in headers.
  - Max 2 verify-mode listeners per ALB.
- **AWS WAF** attaches to an ALB: OWASP rules, rate limiting, IP sets, bot control. **Shield Advanced** can protect ALBs.
- **Integrations**:
  - **Auto Scaling groups**: attach the target group; the ASG registers/deregisters instances.
  - **ECS**: services register tasks (`ip` targets for awsvpc). **EKS**: **AWS Load Balancer Controller** creates ALBs from `Ingress` resources (IP mode targets pods directly).
  - **CloudFront** in front of an ALB: caching, global edge, WAF at the edge. Restrict the ALB to CloudFront using the **CloudFront managed prefix list** in the ALB security group and/or a secret custom header, or **VPC origins** (a private ALB as a CloudFront origin; verify).
  - **Global Accelerator** in front of ALBs: static anycast IPs, multi-Region failover.
  - **Route 53** alias records, health-check-based failover between Regions.
  - **Cognito**, **ACM**, **CloudWatch**, **X-Ray** (trace header), **VPC Lattice** (alternative for service-to-service).

## C. Network Load Balancer (NLB)
- **Layer 4**: forwards **TCP, UDP, TCP_UDP, TLS** connections without looking at HTTP content.
- **Performance**: millions of requests per second, ultra-low latency, handles sudden spikes without pre-warming (scales automatically; LCU reservation available for planned events).
- **Static IPs**:
  - **One static IP per AZ**. For internet-facing NLBs you can assign your own **Elastic IP per AZ**. Internal NLBs can use chosen private IPs.
  - This is the classic answer for **firewall allowlisting**.
- **Client source IP preservation**: targets see the real client IP (instance targets by default; configurable for IP targets). Then the target security group must allow client IPs, not just the NLB.
- **TLS listeners**: the NLB terminates TLS (ACM certificates, SNI, security policies) and forwards TCP or TLS to targets. Or use a TCP listener for **TLS passthrough** (end-to-end encryption, targets hold the certificates).
- **Security groups on NLB** (since 2023): attach SGs to the NLB, so targets can reference the NLB SG. **Must be enabled at creation** (you can't add SGs to an NLB created without them; verify). Can skip SG evaluation for PrivateLink traffic.
- **Target types**: `instance`, `ip` (incl. on-prem over DX/VPN, or other VPC IPs), **`alb`** (ALB behind NLB for static IPs + layer 7 routing).
- **PrivateLink**: an **NLB is required to create a VPC endpoint service**. Consumers in other VPCs/accounts create **interface endpoints** to reach your service privately, with no peering and no overlapping-CIDR problems.
- **Health checks**: TCP, HTTP or HTTPS. Unhealthy targets are removed. Fail open if all are unhealthy.
- **Cross-zone**: off by default (inter-AZ data charges if on).
- **DNS**: one A record per AZ IP. **Availability Zone DNS affinity** settings keep clients in their own AZ (verify). **Zonal shift** (ARC) moves traffic away from an impaired AZ.
- **Proxy Protocol v2**: passes client info when IPs can't be preserved.
- **UDP use cases**: DNS, syslog, gaming, IoT, media streaming.
- **Long-lived connections**: TCP idle timeout 350 s default (configurable; verify). Use TCP keep-alives for longer idle streams (database connections, MQTT).
- **Quotas**: 50 NLBs per Region, 50 listeners per NLB, **500 targets per AZ per NLB**, 3,000 targets per NLB (500 total if cross-zone is on), 1,200 NLB ENIs per VPC.

## D. Gateway Load Balancer (GWLB)
- **Purpose**: deploy, scale and manage **third-party virtual appliances** (Palo Alto, Fortinet, Check Point firewalls, IDS/IPS, DPI) **transparently** in the traffic path.
- Works at **layer 3** (IP packets). Uses **GENEVE encapsulation on UDP port 6081** to send packets to appliances, keeping the original packet intact.
- **GWLB endpoint (GWLBe)**: a VPC endpoint (PrivateLink-based) placed in the traffic path via **route tables**. Traffic from the internet gateway/subnets is routed to the GWLBe → GWLB → appliances → back → destination.
- **Centralized inspection** pattern:
  - A **security/inspection VPC** with the GWLB + appliance fleet (Auto Scaling).
  - Spoke VPCs use GWLB endpoints or **Transit Gateway** routing to send traffic there.
- **Flow stickiness** keeps both directions of a flow on the same appliance (5-tuple default; 3- or 2-tuple options).
- Health checks on appliances. Fail open/closed behavior is configurable (verify target failover settings).
- Cost: hourly per AZ + GLCU, plus GWLB endpoint hourly + per-GB.
- Alternative: **AWS Network Firewall** (managed firewall, no appliances to run).

## E. Classic Load Balancer (previous generation)
- One listener → targets are **EC2 instances directly** (no target groups). HTTP/HTTPS/TCP/SSL.
- Sticky sessions, cross-zone (free), connection draining, health checks, proxy protocol v1.
- **Missing**: path/host routing, IP/Lambda targets, multiple apps per LB, HTTP/2, WebSockets with routing, static IPs, PrivateLink, SNI with many certs (verify; CLB supports one cert per listener), WAF.
- Migrate with the console **migration wizard** (creates an equivalent ALB or NLB). Then switch DNS.

## F. Load balancers in common architectures
- **Classic 3-tier**: internet-facing ALB (public subnets) → app instances/containers (private subnets) → internal NLB/ALB (optional) → databases (private).
- **Microservices**:
  - One ALB with host/path rules → many ECS services / EKS ingresses.
  - Internal ALBs for east-west traffic, or **ECS Service Connect / VPC Lattice** instead of many internal LBs.
- **Blue/green and canary**:
  - ALB **weighted target groups** (manual or automated by ECS native blue/green / CodeDeploy) shift traffic gradually and allow instant rollback.
  - NLB blue/green through ECS native blue/green (extra 10 minutes per traffic stage).
- **Multi-Region**: an ALB in each Region + **Route 53 latency/failover** records, or **Global Accelerator** with endpoint groups per Region.
- **Static IP + HTTP features**: Global Accelerator → ALB, or NLB → ALB (alb target type).
- **Hybrid**: `ip` targets on-prem over Direct Connect/VPN. A VPC LB can front on-prem servers during migration.
- **SaaS / data provider**: expose an API privately to customer VPCs with **NLB + PrivateLink endpoint service** (consumers connect via interface endpoints, no internet).

## G. Data-engineering uses
- **Data APIs** (skill 1.2.8): ALB → ECS/EKS services or Lambda that serve query results, feature lookups or ingestion endpoints. Use API Gateway instead when you need API keys, usage plans, request validation or throttling per client.
- **Ingestion endpoints**: an NLB for high-throughput TCP/UDP producers (syslog, IoT, custom collectors) → ECS consumers → Kinesis/MSK/S3.
- **Partner allowlisting**: partners only accept your traffic from fixed IPs, or must reach your endpoint by fixed IP:
  - **Outbound** from your VPC: a NAT gateway Elastic IP.
  - **Inbound** to you: NLB Elastic IPs or Global Accelerator static IPs.
- **Private data services across accounts**: an NLB endpoint service (PrivateLink) for a data product consumed by other business units' VPCs.
- **Kafka/MSK access**: MSK brokers aren't behind your LB normally. MSK multi-VPC private connectivity uses PrivateLink managed by MSK (verify). Self-managed Kafka behind NLBs needs per-broker listeners.
- **Airflow/Superset/Jupyter UIs**: internal ALB with Cognito/OIDC authentication, in private subnets, reached via VPN.
- **Access logs** (ALB/NLB/CLB → S3) are themselves a data source: query with **Athena** for traffic analytics, errors and security investigations (file 3).

## Scenarios (if → then, because)
- If `api.company.com` and `admin.company.com` must share one load balancer → ALB with **host-based** rules (and SNI certificates).
- If HTTP must always redirect to HTTPS → ALB port-80 listener with a **redirect action**.
- If a maintenance page is needed without any backend → ALB **fixed-response** action.
- If users must log in through the corporate IdP before reaching an internal dashboard → ALB **authenticate-oidc** (or Cognito) action.
- If 10% of traffic must go to a new version → ALB **weighted forward** across two target groups (with target group stickiness).
- If clients must present client certificates → ALB **mTLS verify** mode with a trust store (or NLB TCP passthrough to targets).
- If the app needs protection from SQL injection and bad bots → **AWS WAF** on the ALB (WAF can't attach to an NLB).
- If an ingestion service receives UDP syslog from thousands of devices → **NLB** with a UDP listener.
- If a database proxy must keep the client IP and hold long TCP connections → NLB with client IP preservation and tuned TCP idle timeout/keep-alives.
- If an NLB's targets must only accept traffic from the NLB → enable **security groups on the NLB** (at creation) and reference it in the target SG.
- If your data API must be consumed privately by 20 customer accounts with overlapping CIDRs → NLB + **VPC endpoint service (PrivateLink)**.
- If an ALB must sit behind static IPs → NLB with an `alb` target group, or Global Accelerator.
- If all north-south traffic must pass a third-party firewall fleet → **GWLB** + GWLB endpoints in route tables (or AWS Network Firewall for managed).
- If an EKS app needs an ALB from Kubernetes manifests → **AWS Load Balancer Controller** with an Ingress (IP targets).
- If CloudFront fronts an ALB and direct ALB access must be blocked → allow only the CloudFront managed prefix list in the ALB SG (and/or a secret header rule), or use VPC origins with an internal ALB.
- If a Lambda must answer HTTP calls behind the same domain as other services → ALB `lambda` target group on a path rule.
- If an old CLB must be modernized → migration wizard to ALB/NLB, test, then switch DNS.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: ALB quotas (50 ALBs, 25 certificates, 50 listeners, 5 target groups per action, 100 target groups per ALB, 1,000 targets per ALB/target group, 100 rules, 5 condition values, 6 wildcards, trust stores 20, 2 mTLS verify listeners, header size limits, LCU reservation quotas), NLB quotas (25 certificates, 50 listeners, 1,200 ENIs per VPC, 50 NLBs, 500 targets per AZ, 3,000 per NLB, 500 if cross-zone, ALB target counts as 50/100, 100 rules, 5 target groups per action), ELB pricing dimensions.
Not confirmed (verify): ALB URL rewrite/header transform feature, Lambda response size via ALB, XFF/host header option names, CloudFront VPC origins details, NLB security group timing rule, AZ DNS affinity naming, TCP idle timeout range, GWLB failover settings, CLB certificate/SNI limits, MSK PrivateLink details.

# Elastic Load Balancing – 3. Security, availability, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. TLS and certificates
- **TLS termination at the LB**:
  - **HTTPS listener (ALB)** or **TLS listener (NLB)** decrypts traffic at the load balancer.
  - Saves CPU on targets and centralizes certificate management.
  - Traffic from LB to targets can be HTTP (inside the VPC) or **re-encrypted** (HTTPS/TLS to targets) for end-to-end encryption.
- **End-to-end encryption options**:
  - **Re-encrypt**: HTTPS listener → HTTPS target group (targets have their own certs; self-signed is OK because the ALB doesn't verify target certs; verify).
  - **Passthrough**: NLB **TCP** listener on 443 → targets terminate TLS. The LB never sees plaintext (needed when the app must handle client certs itself or strict compliance requires it).
- **Certificates**:
  - **AWS Certificate Manager (ACM)**: free public certificates, auto-renewal, deployed to ALB/NLB/CloudFront. Private certificates from **ACM Private CA**.
  - Imported third-party certificates are also possible (you renew them).
  - ACM certificates are **Regional**: request in the same Region as the LB (CloudFront needs us-east-1).
- **SNI (Server Name Indication)**: multiple certificates on one HTTPS/TLS listener (up to **25 extra certificates** per ALB/NLB). The LB picks the right cert by the hostname the client requests. Many domains on one ALB.
- **Security policies**:
  - Predefined `ELBSecurityPolicy-*` sets choose allowed **TLS versions and ciphers**.
  - Use a **TLS 1.2+ or TLS 1.3** policy (for example `ELBSecurityPolicy-TLS13-1-2-2021-06`) and FIPS policies where required.
  - Old TLS 1.0/1.1 policies are only for legacy clients.
- **Post-quantum TLS** policies are available on ELB (hybrid key exchange; verify).
- **mTLS** (ALB): verify mode with trust stores (CA bundle + CRLs in S3), or passthrough mode.
- **HTTP → HTTPS redirect** on port 80, plus **HSTS** headers from the app or the ALB response header settings (verify).

## B. Network security
- **Security groups**:
  - **ALB**: always has security groups. Allow inbound 80/443 from clients (0.0.0.0/0 for public, or corporate CIDRs / the CloudFront prefix list).
  - **NLB**: security groups optional (choose at creation).
  - **Target security groups** should allow traffic **only from the LB's security group** (SG reference), not from the internet. This is the standard least-privilege pattern.
  - Health check ports must also be allowed from the LB SG.
- **Network ACLs** on LB subnets must allow the listener ports and the **return ephemeral ports**.
- **Internal load balancers** for anything not public. Internet-facing only for real public endpoints.
- **Targets in private subnets**: only the internet-facing LB lives in public subnets.
- **AWS WAF** (ALB, also API Gateway/CloudFront/AppSync/Cognito/App Runner): managed rule groups (OWASP Top 10, known bad inputs, SQLi), IP reputation, **rate-based rules**, geo blocking, Bot Control.
- **AWS Shield**:
  - **Standard** (free, automatic) protects against common layer 3/4 DDoS for all ELBs.
  - **Shield Advanced** (paid) adds layer 7 protection with WAF, a DDoS response team, and **cost protection** for scaling during attacks.
- **Authentication at the ALB**: Cognito / OIDC actions, so apps don't implement login. Combine with WAF.
- **Deletion protection**: an attribute that stops accidental deletion of a load balancer.
- **Restricting origin access**: when CloudFront/Global Accelerator fronts the ALB, block direct access (prefix-list SG, custom header check, internal ALB with VPC origins).
- **IAM**: who can modify listeners/rules/certificates (`elasticloadbalancing:*`). Resource tags + ABAC. CloudTrail audits changes.

## C. Availability and resilience
- **Multi-AZ**: enable **at least 2 (preferably 3) AZs**, with targets in each AZ. The LB nodes in each AZ are managed and replaced by AWS.
- **Health checks** remove bad targets. ASG health type ELB replaces them. Tune intervals/thresholds for faster detection, but don't flap.
- **Cross-zone** for even distribution when target counts per AZ differ.
- **AZ failure**:
  - With targets in other AZs, traffic continues.
  - **Zonal shift / zonal autoshift (Amazon Application Recovery Controller)** moves traffic away from an impaired AZ for ALB/NLB (cross-zone settings matter; verify).
  - **DNS failover** (target group health requirements; verify) removes an unhealthy AZ's IP from DNS.
- **Region failure**: duplicate the stack in another Region + **Route 53 failover/latency routing** with health checks, or **Global Accelerator** (fast failover with static IPs).
- **Scaling of the LB itself**: ALB/NLB scale automatically. For **sudden huge spikes** (launch events), use **LCU Reservation** (reserve minimum capacity; replaces old "pre-warming" support tickets).
  - ALB up to 15,000 reserved LCUs per LB. NLB up to 45,000 per AZ (quota adjustable; Region quota starts at 0, so request it).
- **Graceful deployments**: deregistration delay (draining), slow start, weighted target groups, ECS circuit breaker / CodeDeploy rollback.
- **Session state** outside targets (ElastiCache/DynamoDB) so any target can serve any user, which avoids sticky-session fragility.

## D. Cost
- **ALB** (us-east-1):
  - **$0.0225 per hour** (partial hours billed as full hours), **plus $0.008 per LCU-hour**.
  - You are billed on the **highest** of 4 LCU dimensions. One LCU = **25 new connections/s**, **3,000 active connections/min** (1,500 with mTLS), **1 GB/hour processed** (0.4 GB for Lambda targets), **1,000 rule evaluations/s** (first 10 rules free).
- **NLB**:
  - **$0.0225 per hour + $0.006 per NLCU-hour**.
  - Per NLCU, TCP: 800 new connections/s, 100,000 active, 1 GB/h. UDP: 400 new flows/s, 50,000 active, 1 GB/h. TLS: 50 new/s, 3,000 active, 1 GB/h.
- **GWLB**: **$0.0125 per hour per AZ + $0.004 per GLCU-hour**. GWLB endpoints are about $0.01/h + $0.0035/GB.
- **CLB**: $0.025 per hour + $0.008 per GB processed.
- **LCU reservation**: pay for reserved LCUs at the normal LCU rate. Usage above the reservation is billed normally.
- **Other charges**:
  - **Inter-AZ data transfer** when NLB/GWLB cross-zone is on (ALB cross-zone is free).
  - **Public IPv4 addresses** of internet-facing LBs (per IP per hour). Dualstack-without-public-IPv4 avoids this (ALB; verify).
  - Data transfer out to the internet.
  - Access log storage in S3.
- **Cost tips**:
  - **Consolidate** many apps behind one ALB with host/path rules (one hourly fee instead of many). Keep rule counts sensible.
  - **Delete idle load balancers** (Trusted Advisor "idle load balancers" check). Each costs ~$16+/month even with no traffic.
  - Avoid NLB cross-zone if traffic is balanced per AZ.
  - Use internal LBs or VPC Lattice / Service Connect for service-to-service traffic instead of many internal ALBs.
  - CloudFront in front for cacheable content (cuts LCUs and data out).
  - Set S3 lifecycle rules on access logs.

## E. Monitoring and logging
- **CloudWatch metrics** (namespace `AWS/ApplicationELB`, `AWS/NetworkELB`, `AWS/GatewayELB`; 1-minute; free):
  - **ALB**:
    - Traffic: `RequestCount`, `ActiveConnectionCount`, `NewConnectionCount`, `ProcessedBytes`, `ConsumedLCUs`.
    - Target health: **`HealthyHostCount` / `UnHealthyHostCount`** (per target group).
    - Latency: **`TargetResponseTime`** (latency from targets).
    - Errors: **`HTTPCode_ELB_4XX/5XX_Count`** (generated **by the LB**) vs **`HTTPCode_Target_2XX/3XX/4XX/5XX_Count`** (returned **by targets**), `TargetConnectionErrorCount`, **`RejectedConnectionCount`** (LB at max connections), `ELBAuthError`, `AnomalousHostCount` (anomaly mitigation; verify).
  - **NLB**: `ActiveFlowCount`, `NewFlowCount`, `ProcessedBytes`, `HealthyHostCount`, `TCP_Client_Reset_Count`, `TCP_Target_Reset_Count`, `TCP_ELB_Reset_Count`, `ConsumedLCUs`, `PeakPacketsPerSecond`.
- **Alarms**: unhealthy host count > 0, ELB 5XX rate, target 5XX rate, p99 TargetResponseTime, rejected connections → SNS / auto rollback (ECS/CodeDeploy alarms).
- **Access logs**:
  - **ALB/NLB/CLB access logs** → **S3** (every 5 minutes; optional, free except S3 storage).
  - They contain timestamp, client IP:port, target IP:port, request/target/response processing times, ELB and target status codes, bytes, request line, user agent, TLS cipher/protocol, target group ARN, trace ID, matched rule, error reason.
  - The bucket policy must allow the ELB log delivery service. Encryption: **SSE-S3** works, and SSE-KMS is supported now (verify).
  - **Query with Amazon Athena** (create a table with the AWS-provided DDL and partition projection) for top client IPs, 5xx by path, slowest requests, attack detection.
  - NLB access logs are written **only for TLS listeners** (verify).
- **ALB connection logs** (client certificate info for mTLS, TLS handshake details) → S3.
- **Health check logs** (newer; verify).
- **AWS X-Ray**: ALB adds `X-Amzn-Trace-Id`. Apps continue the trace.
- **CloudTrail**: API changes (`CreateLoadBalancer`, `ModifyListener`, `CreateRule`, `RegisterTargets`, certificate changes) for audit. **Not** individual requests (use access logs).
- **VPC Flow Logs** on LB ENIs for packet-level accept/reject analysis.
- **Reachability Analyzer / Network Access Analyzer** to debug paths through LBs and security groups.

## F. Troubleshooting (symptom → cause → fix)
- **HTTP 502 Bad Gateway (ALB)** → the target closed the connection or sent a malformed response:
  - The backend **keep-alive timeout is shorter than the ALB idle timeout**.
  - The target crashed mid-request, or the response headers are too large.
  - A Lambda target returned an invalid response format or errored.
  - TLS handshake to an HTTPS target failed.
  - Fix: longer backend keep-alive, fix the app, check `HTTPCode_ELB_502_Count` and access log `error_reason`.
- **HTTP 503 Service Unavailable (ALB)** → the target group has **no registered targets** (or no target group for the rule), or the LB is out of capacity (rare; check LCU reservation). Fix: register targets / check ASG/ECS registration.
- **HTTP 504 Gateway Timeout (ALB)** → the target didn't respond within the **idle timeout** (slow queries), or the connection to the target timed out (SG/NACL blocks the target port, target overloaded). Fix: raise the idle timeout / make work async, fix SGs, scale targets.
- **HTTP 500 (ELB-generated)** → an ALB-side error (auth action failure with the IdP, WAF/config errors, rule issues). Check `error_reason` in access logs.
- **HTTP 460** → the client closed the connection before the LB responded (client timeout shorter than the backend time). **463** → `X-Forwarded-For` has more than 30 IPs. **561** → authentication action got an error from the IdP (verify codes).
- **4XX from the ELB** (`HTTPCode_ELB_4XX`) vs from targets: check which metric rises to know whether the LB or the app returned it.
- **Targets unhealthy** →
  - The target SG doesn't allow the health check port from the LB SG.
  - Wrong health check path/port/success codes.
  - The app is slow to start (raise the grace period/thresholds).
  - The HTTPS health check fails on certificates.
  - The instance is in an AZ not enabled on the LB.
  - Read the **target health reason codes** (`Target.Timeout`, `Target.ResponseCodeMismatch`, `Target.FailedHealthChecks`, `Elb.RegistrationInProgress`…).
- **All targets unhealthy but traffic still flows** → fail-open behavior. Fix the health check or the app.
- **Can't reach the LB** → LB SG/NACL blocks the port, an internet-facing LB in subnets without an internet gateway route, an internal LB used from the internet, DNS pointing at the wrong record.
- **Uneven load across targets** → NLB long-lived connections (flow hash), cross-zone off with uneven targets per AZ, sticky sessions, clients caching one AZ IP. Fix: cross-zone on, LOR algorithm (ALB), shorter connection reuse.
- **Connections reset / dropped at 350 s on NLB** → TCP idle timeout. Use keep-alives or raise the idle timeout.
- **Client IP shows as an LB IP in app logs** → ALB: read `X-Forwarded-For`. NLB: client IP preservation was turned off, so enable it or use Proxy Protocol v2.
- **Certificate errors in browsers** → wrong certificate for the hostname (SNI list missing the domain), expired imported cert, or the ACM certificate is in another Region.
- **`RejectedConnectionCount` rising (ALB)** → the LB is at its connection limit for current capacity. Wait for scaling, or use LCU reservation for spikes.
- **Health checks pass but users get errors** → shallow health checks. Add a meaningful readiness endpoint, alarms on target 5XX, anomaly mitigation.
- **Deployments drop requests** → deregistration delay too short, or the app doesn't finish in-flight requests on SIGTERM.

## G. Limits and numbers to remember
| Item | Value |
|---|---|
| ALBs / NLBs per Region | 50 each (adjustable) |
| Target groups per Region | 3,000 (shared ALB + NLB) |
| Listeners per ALB / NLB | 50 / 50 |
| Rules per ALB | 100 (adjustable) |
| Condition values per rule | 5 (wildcards 6) |
| Target groups per forward action | 5 |
| Target groups per ALB | 100 |
| Targets per ALB / per target group | 1,000 / 1,000 (adjustable) |
| Targets per NLB | 3,000; 500 per AZ; 500 total with cross-zone |
| Lambda targets per target group | 1 |
| Load balancers per target group | 1 |
| Extra certificates per ALB / NLB (SNI) | 25 |
| mTLS verify listeners per ALB | 2; trust stores 20 per account |
| ALB HTTP header limits | request line 16K, single header 16K, request headers 64K, response headers 32K |
| ALB idle timeout | 60 s default (1–4,000 s) |
| NLB TCP idle timeout | 350 s default (configurable; verify) |
| Deregistration delay | 300 s default (0–3,600 s) |
| Slow start | 30–900 s |
| Sticky cookie duration (ALB) | 1 s – 7 days |
| ALB price | $0.0225/h + $0.008/LCU-h |
| NLB price | $0.0225/h + $0.006/NLCU-h |
| GWLB price | $0.0125/h per AZ + $0.004/GLCU-h |
| CLB price | $0.025/h + $0.008/GB |
| Reserved LCUs | ALB 15,000 per LB; NLB 45,000 per AZ; Region quota starts at 0 |
| Access log delivery | every 5 minutes to S3 |
| GWLB protocol | GENEVE, UDP 6081 |

## H. Final scenario set (if → then, because)
- **If** a public data API must be HTTPS only with free, auto-renewing certificates, **then** use an **Application Load Balancer (ALB) HTTPS listener** with an **AWS Certificate Manager (ACM)** certificate, plus an **HTTP→HTTPS redirect** on port 80. **This works because** ACM public certificates are **free** and **renew automatically**. The catch: the certificate must be in the **same Region** as the load balancer.
- **If** compliance requires encryption all the way to the targets, **then** use **Application Load Balancer (ALB) re-encrypt** (an HTTPS target group), or a **Network Load Balancer (NLB) TCP passthrough** on 443. **This works because** with re-encrypt the ALB decrypts and then encrypts again to the targets; with passthrough the targets terminate TLS and the load balancer **never sees plaintext**.
- **If** **15 customer domains** must be served by one load balancer, **then** use an **Application Load Balancer (ALB)** with **Server Name Indication (SNI)** and **host-based rules**. **This works because** SNI allows up to **25 extra certificates** on one listener and picks the right one by the hostname the client asks for, and host rules route each domain.
- **If** old **TLS 1.0** clients must be blocked, **then** choose a **TLS 1.2 or TLS 1.3 security policy** (an `ELBSecurityPolicy-*` set) on the listener. **This works because** the security policy decides which TLS versions and ciphers the listener accepts.
- **If** the app must be protected from injection attacks and abusive IPs, **then** attach **AWS WAF** (web application firewall) to the **Application Load Balancer (ALB)** with **managed rule groups** and **rate-based rules**. **This works because** managed rules block known bad inputs such as SQL injection, and rate-based rules limit IPs that send too many requests.
- **If** a DDoS-sensitive public service needs expert response and cost protection, **then** use **AWS Shield Advanced** (paid). **This works because** it adds **layer 7** protection with WAF, a **DDoS response team**, and **cost protection** for scaling during attacks. **Shield Standard** is free but covers only common layer 3/4 attacks.
- **If** targets must accept traffic only from the load balancer, **then** set the target **security group (SG)** to allow inbound **only from the load balancer's SG** (an SG reference), including the health check port. **This works because** an SG reference allows only traffic from members of that SG, so nothing from the internet reaches the targets directly.
- **If** a partner must allowlist your endpoint IPs, **then** use a **Network Load Balancer (NLB)** with **Elastic IPs** (one per Availability Zone), or **AWS Global Accelerator** static IPs. **This works because** these IPs never change, while Application Load Balancer IPs change as it scales.
- **If** the service must keep running during an **Availability Zone (AZ) failure**, **then** enable **2–3 AZs** with targets in each, use **health checks**, and use **zonal shift / zonal autoshift** from **Amazon Application Recovery Controller (ARC)**. **This works because** traffic continues on targets in the healthy AZs, and zonal shift moves traffic away from the impaired AZ (how cross-zone settings affect it: verify).
- **If** a product launch will bring a sudden **10× spike** at a known time, **then** set up an **LCU reservation** (reserved Load Balancer Capacity Units) ahead of the event. **This works because** it reserves a **minimum capacity**, so the load balancer does not have to scale up during the spike. The catch: the Region quota **starts at 0**, so request it first.
- **If** the security team wants to know which IPs got **403s** last week, **then** query **Application Load Balancer (ALB) access logs in Amazon S3** with **Amazon Athena**. **This works because** access logs record every request with client IP and status codes, delivered to S3 **every 5 minutes**, and Athena runs SQL over them.
- **If** someone changed a listener rule and broke routing, **then** check **AWS CloudTrail** for the API change, and the **access logs** for the matched rule. **This works because** CloudTrail records API calls like `ModifyListener` or `CreateRule` (who and when), while access logs show which rule each request matched.
- **If** users see **504s** on long report generation, **then** raise the **idle timeout**, or change to async (a job plus an **Amazon S3 presigned URL**). **This works because** a 504 means the target did not respond within the **idle timeout** (ALB default **60 s**).
- **If** users see random **502s**, **then** make the **backend keep-alive timeout longer** than the **Application Load Balancer (ALB) idle timeout**, or fix app crashes. **This works because** a 502 means the target closed the connection or sent a bad response. Check the access log **`error_reason`** field to find which.
- **If** you get **503s** right after a deployment, **then** check that the target group has **registered targets** yet (Amazon ECS or Auto Scaling group registration delay). **This works because** an ALB 503 means the target group has **no registered targets**. If targets are registered but all unhealthy, the ALB **fails open** and still sends traffic.
- **If** the bill shows many **Application Load Balancers (ALBs)** with tiny traffic, **then** consolidate apps onto one ALB with **host/path rules** and **delete idle load balancers**. **This works because** each load balancer pays an **hourly fee** (about **$16+/month** even with no traffic), so one shared ALB pays it once.
- **If** **Network Load Balancer (NLB)** cross-AZ data charges are high, **then** turn **cross-zone load balancing off** and keep **balanced targets per Availability Zone (AZ)**. **This works because** NLB cross-zone causes **inter-AZ data transfer** charges; with equal targets per AZ, each node can serve its own AZ evenly.
- **If** alarms must catch app-side failures, not load-balancer-side ones, **then** alarm on **`HTTPCode_Target_5XX_Count`**; for load-balancer-side errors, alarm on **`HTTPCode_ELB_5XX_Count`**. **This works because** the Target metric counts errors **returned by targets**, while the ELB metric counts errors **generated by the load balancer** itself.
- **If** client certificates must be validated centrally, **then** use **Application Load Balancer (ALB) mutual TLS (mTLS) verify mode** with a **trust store**, plus **connection logs**. **This works because** the ALB checks client certificates against the CA bundle and revocation lists in Amazon S3, and connection logs record client certificate details.
- **If** a multi-Region active-passive setup needs fast failover with static IPs, **then** put **AWS Global Accelerator** in front of an **Application Load Balancer (ALB)** in each Region, or use **Amazon Route 53 failover records**. **This works because** Global Accelerator gives **static IPs** and **fast failover** between Regions, while Route 53 fails over by changing DNS answers based on health checks.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: ALB and NLB quotas (all numbers in the limits table, incl. reserved LCU quotas, mTLS and header limits), ELB pricing (ALB/NLB hourly and LCU/NLCU dimensions, GWLB hourly per AZ and GLCU, GWLB endpoint example, CLB rates, LCU reservation billing, public IPv4 and data transfer apply).
Not confirmed (verify): ALB not verifying target certificates, post-quantum TLS policies, ALB HSTS/response header settings, zonal shift behavior with cross-zone, DNS failover/target group health requirements, `AnomalousHostCount` metric name, SSE-KMS for access logs, NLB access logs only for TLS listeners, health check logs, HTTP 460/463/561 meanings, NLB idle timeout range.

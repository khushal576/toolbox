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
- If a public data API must be HTTPS only with free auto-renewing certificates → ALB HTTPS listener with an **ACM** certificate + HTTP→HTTPS redirect.
- If compliance requires encryption all the way to the targets → ALB re-encrypt (HTTPS target group), or NLB TCP passthrough.
- If 15 customer domains must be served by one load balancer → ALB with **SNI** (up to 25 extra certificates) + host-based rules.
- If old TLS 1.0 clients must be blocked → choose a TLS 1.2/1.3 **security policy** on the listener.
- If the app must be protected from injection attacks and abusive IPs → **WAF** with managed rules and rate-based rules on the ALB.
- If a DDoS-sensitive public service needs expert response and cost protection → **Shield Advanced**.
- If targets must accept traffic only from the load balancer → target SG allows inbound **only from the LB security group**.
- If a partner must allowlist your endpoint IPs → **NLB Elastic IPs** (or Global Accelerator).
- If the service must keep running during an AZ failure → 2–3 AZs with targets in each, health checks, and zonal shift/autoshift.
- If a product launch will bring a sudden 10× spike at a known time → **LCU reservation** ahead of the event.
- If the security team wants to know which IPs got 403s last week → ALB **access logs in S3 queried with Athena**.
- If someone changed a listener rule and broke routing → **CloudTrail** for the API change. Access logs show the matched rule.
- If users see 504s on long report generation → raise the idle timeout, or change to async (job + S3 presigned URL).
- If users see random 502s → backend keep-alive timeout shorter than the ALB idle timeout, or app crashes. Check `error_reason`.
- If you get 503s right after a deployment → the target group has no registered/healthy targets yet (ECS/ASG registration delay).
- If the bill has many ALBs with tiny traffic → consolidate apps onto one ALB with host/path rules and delete idle LBs.
- If NLB cross-AZ data charges are high → turn off cross-zone and keep balanced targets per AZ.
- If alarms must catch app-side failures, not LB-side → alarm on `HTTPCode_Target_5XX_Count`. For LB-side, alarm on `HTTPCode_ELB_5XX_Count`.
- If client certificates must be validated centrally → ALB **mTLS verify** mode with a trust store + connection logs.
- If a multi-Region active-passive setup needs fast failover with static IPs → **Global Accelerator** in front of ALBs in each Region (or Route 53 failover records).

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: ALB and NLB quotas (all numbers in the limits table, incl. reserved LCU quotas, mTLS and header limits), ELB pricing (ALB/NLB hourly and LCU/NLCU dimensions, GWLB hourly per AZ and GLCU, GWLB endpoint example, CLB rates, LCU reservation billing, public IPv4 and data transfer apply).
Not confirmed (verify): ALB not verifying target certificates, post-quantum TLS policies, ALB HSTS/response header settings, zonal shift behavior with cross-zone, DNS failover/target group health requirements, `AnomalousHostCount` metric name, SSE-KMS for access logs, NLB access logs only for TLS listeners, health check logs, HTTP 460/463/561 meanings, NLB idle timeout range.

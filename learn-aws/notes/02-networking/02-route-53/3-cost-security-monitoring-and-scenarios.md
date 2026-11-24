# Amazon Route 53 – 3. Security, monitoring, troubleshooting and exam scenarios

Short notes. Each point is a fact you can be asked about.

## A. Security and access control
- **IAM actions**: `route53:ChangeResourceRecordSets`, `ListHostedZones`, `CreateHostedZone`, `AssociateVPCWithHostedZone`, `CreateVPCAssociationAuthorization`, `CreateHealthCheck`, `route53domains:*`, `route53resolver:*`.
- **Fine-grained control**: IAM conditions on hosted zone ID, record name/type (`route53:ChangeResourceRecordSetsNormalizedRecordNames`, `…RecordTypes`, `…Actions`) so teams can edit only their subdomain records.
- **Managed policies**: `AmazonRoute53FullAccess`, `AmazonRoute53ReadOnlyAccess`, `AmazonRoute53DomainsFullAccess`, `AmazonRoute53ResolverFullAccess` **(verify names)**.
- **Delegation**: separate AWS accounts own subdomains via NS delegation; central team owns the parent zone.
- **Domain security**: enable **transfer lock** and **auto-renew**; use **MFA** on the registering account; monitor registrar contacts.
- **Dangling DNS / subdomain takeover**: delete records that point to deleted resources (S3 website endpoints, CloudFront, Elastic Beanstalk); use Config/Access Analyzer-style scans.
- **DNS exfiltration protection**: Resolver DNS Firewall + query logs + GuardDuty DNS findings.
- **Private hosted zone**: not resolvable from the internet; restrict who can associate VPCs.
- **Audit**: CloudTrail logs Route 53 API calls (control plane); query logging for data plane.
- **Encryption**: DNS queries are not encrypted by default (DNSSEC for authenticity, DoH/DoT on Resolver endpoints for transport) **(verify)**.
- **Endpoint security**: SG on Resolver endpoints (53 TCP/UDP) from on-prem CIDRs only.

## B. Monitoring
- **CloudWatch metrics** (`AWS/Route53`, in us-east-1): `HealthCheckStatus`, `HealthCheckPercentageHealthy`, `ChildHealthCheckHealthyCount`, `ConnectionTime`, `TimeToFirstByte`, `SSLHandshakeTime`, `DNSQueries` (per hosted zone, if enabled), `DNSSECInternalFailure`, `DNSSECKeySigningKeysNeedingAction`.
- **Resolver endpoint metrics** (`AWS/Route53Resolver`): `InboundQueryVolume`, `OutboundQueryVolume`, `OutboundQueryAggregateVolume` per endpoint/IP.
- **Alarms** on health check status (notify via SNS in us-east-1), DNSSEC issues, resolver capacity (> 50% of 10,000 QPS per IP).
- **Logs**: public DNS query logs (CloudWatch us-east-1), Resolver query logs (S3/CloudWatch/Firehose).
- **Config**: records of hosted zones/health checks (Config supports Route 53 hosted zones and domains) **(verify)**.
- **Dashboards** combining health checks, alias target health, ELB/CloudFront metrics.
- **Testing tools**: `dig`, `nslookup`, console **test record set**/`TestDNSAnswer`, Reachability Analyzer for endpoint paths.

## C. Troubleshooting checklist
1. **Is the zone authoritative?** NS records at the registrar must match the hosted zone's name servers.
2. **Which zone answers?** Public vs private (split-horizon): inside the VPC the private zone takes precedence, even for names missing from it (NXDOMAIN).
3. **TTL/caching**: wait or flush; check negative caching (SOA minimum).
4. **Alias target correct and healthy?**
5. **Health checks**: firewall allows checker IPs; correct path/port/host header; HTTPS cert valid; string match present in first 5,120 bytes.
6. **VPC settings**: `enableDnsSupport/enableDnsHostnames`, DHCP options not overriding resolver.
7. **Hybrid DNS**: forwarders/rules, SGs on endpoints, routing for return traffic, no overlapping rules.
8. **DNSSEC**: DS record matches KSK; KMS key enabled.
9. **Throttling**: API calls or resolver limits.
10. **Search logs** for NXDOMAIN/SERVFAIL patterns.

## D. Best practices
- Use **alias** records for AWS targets; low TTL before migrations, restore afterward.
- **Health checks + failover/latency** for multi-Region services; don't depend on health checks that can't see the app (use a deep health endpoint that verifies dependencies carefully).
- Separate **public** and **private** zones; use **Profiles** for VPC/DNS governance.
- **Centralize** Resolver endpoints in a shared-services VPC and share rules with RAM.
- Protect **registrar and hosted zones** with least-privilege IAM and change reviews (IaC).
- Enable **DNSSEC** for high-value public zones with careful rollout.
- Turn on **query logging** (Resolver) for security visibility.
- Remove stale records; tag zones; use IaC for zones and records.
- Consider **ARC** for critical failover with human-controlled switches.
- Set **CAA** records to restrict who can issue certificates for your domain.

## E. Data-platform DNS design examples
- **Friendly names for data endpoints**: PHZ `analytics.example.internal` → CNAMEs to Redshift/RDS/OpenSearch/MSK bootstrap addresses (so cluster replacement doesn't change app configs); remember Redshift/RDS endpoints can change on restore/failover (cluster endpoint stays).
- **Multi-Region read endpoints**: latency-based routing to regional read replicas (Aurora/OpenSearch/DynamoDB endpoints behind APIs) using health checks.
- **Blue/green data API**: weighted alias records to old/new ALB.
- **Hybrid access**: on-prem BI tools resolve `*.data.internal` via inbound endpoint; reach Redshift privately over DX/VPN.
- **PrivateLink-based SaaS access**: PHZ overriding vendor hostname to your interface endpoint IPs (split-horizon).
- **DR**: failover record pointing to a standby Region's API; routing controls for data pipeline cutover decisions.

## F. Exam skills mapping
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: private DNS for endpoints and PrivateLink.
- **2.3.6 Resiliency and availability of data**: resiliency and availability (failover routing).

## G. Scenarios: "If X → Y, because Z"
- If a CNAME is required for the zone apex → **use an alias A/AAAA to the AWS resource**, because CNAME at apex is invalid.
- If a name resolves differently inside the VPC than outside → **split-horizon (public + private zones with the same name)**, because the private zone overrides inside associated VPCs.
- If a health check on a private ALB always fails → **use a CloudWatch alarm health check or a public health endpoint**, because Route 53 checkers are on the internet.
- If only certain teams may edit `team-a.example.com` records → **IAM conditions on record names/types or delegate the subdomain**, because they limit change scope.
- If you must route users in a specific corporate network to a private endpoint → **IP-based routing with a CIDR collection**, because it matches client CIDRs.
- If a partner's SaaS endpoint must be reached privately by name → **PHZ record to your interface endpoint**, because PHZ answers inside the VPC only.
- If DNS cutover causes long outages → **lower TTL ahead of time**, because caches hold old answers until TTL expires.
- If you need to prove nothing exfiltrates via DNS → **DNS Firewall with query logs**, because it blocks and records lookups.
- If you manage 200 accounts' VPC DNS → **Profiles shared via RAM**, because they apply DNS config at scale.
- If your zone changes fail with `PriorRequestNotComplete` → **batch changes and back off**, because Route 53 processes changes per zone sequentially.

Verified from AWS docs on 2026-11-09 (Route 53 quotas page).
Unconfirmed (verify): IAM condition key names; managed policy names; metric names; Config resource support; DoH/DoT support; negative-caching behaviour; CAA recommendation details.

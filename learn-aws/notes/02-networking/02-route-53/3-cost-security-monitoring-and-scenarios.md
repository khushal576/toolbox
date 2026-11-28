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
- **If** you want the **zone apex** (`example.com`, the bare domain) to point at an AWS resource, where you would normally use a CNAME, **then** create an **alias A or AAAA record** to that resource. **This works because** a **CNAME** record **cannot be created at the zone apex**, while an alias record is a Route 53 feature that points at AWS resources and works at the apex. To the outside world it looks like a normal A/AAAA record.
- **If** a name must resolve differently inside the VPC than outside, **then** use **split-horizon DNS**: a **public hosted zone** and a **private hosted zone (PHZ)** with the **same name**. **This works because** inside associated VPCs the private zone wins, and outside the public zone answers. Catch: inside the VPC the private zone wins even for names missing from it, which return **NXDOMAIN** (name not found).
- **If** a health check on a private **Application Load Balancer (ALB)** always fails, **then** use a **CloudWatch alarm health check** (its status follows an **Amazon CloudWatch** alarm) or expose a public health endpoint. **This works because** Route 53 health checkers run on the **public internet** and **cannot reach private IP addresses**.
- **If** only certain teams may edit the `team-a.example.com` records, **then** use **Identity and Access Management (IAM) conditions** on record names and types, or **delegate the subdomain** to the team's own account with NS records. **This works because** both limit what each team can change: IAM conditions restrict which records a user may edit, and delegation gives the team its own zone while the central team keeps the parent.
- **If** users on a specific corporate network must be sent to a private endpoint, **then** use **IP-based routing** with a **CIDR collection** (a list of client IP ranges). **This works because** IP-based routing matches the client's IP address against the CIDR blocks and returns the endpoint set for that range. Limit: **5 CIDR collections** per account, **1,000 CIDR blocks** each.
- **If** a partner's software-as-a-service (SaaS) endpoint must be reached privately by its normal name, **then** create a **private hosted zone (PHZ)** that overrides the vendor's hostname and points to your **interface endpoint** IPs (AWS PrivateLink). **This works because** a PHZ answers only inside associated VPCs, so your VPC gets the private IPs while the internet still gets the public answer (split-horizon).
- **If** DNS cutovers cause long outages, **then** **lower the Time To Live (TTL)** (for example to **60 seconds**) well before the change, and restore it afterwards. **This works because** resolver caches keep the old answer until the TTL expires, so a short TTL makes clients pick up the new record quickly.
- **If** you must prove that no data leaks out through DNS lookups (DNS exfiltration), **then** use **Route 53 Resolver DNS Firewall** together with **Resolver query logs**. **This works because** DNS Firewall **blocks** lookups to bad domains and the query logs **record** every lookup, which gives you proof. Amazon GuardDuty DNS findings can add detection.
- **If** you manage VPC DNS for **200 accounts**, **then** use **Route 53 Profiles** shared with **AWS Resource Access Manager (RAM)**. **This works because** a Profile bundles PHZ associations, Resolver rules, DNS Firewall rule groups and query logging configs, and applies them to many VPCs and accounts at once (up to **1,000 VPCs** per Profile).
- **If** record changes fail with `PriorRequestNotComplete` or throttling errors, **then** **batch** the changes into fewer `ChangeResourceRecordSets` calls and **back off** before retrying. **This works because** the error means too many change calls were sent to the **same hosted zone**. One call can hold up to **1,000** record values and **32,000 characters**.

Verified from AWS docs on 2026-11-09 (Route 53 quotas page).
Unconfirmed (verify): IAM condition key names; managed policy names; metric names; Config resource support; DoH/DoT support; negative-caching behaviour; CAA recommendation details.

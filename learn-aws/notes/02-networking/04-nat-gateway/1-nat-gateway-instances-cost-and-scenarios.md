# NAT Gateway – NAT gateways, NAT instances, cost and scenarios

Short notes. Each point is a fact you can be asked about.

## A. What NAT is and why you need it
- **NAT (Network Address Translation)** rewrites the **source IP** of outgoing packets from private resources to the NAT device's IP, and maps the replies back.
- **Problem it solves**:
  - Resources in **private subnets** (no public IPs, no route to the internet gateway) sometimes need **outbound** access: OS/package updates, pip/npm installs, calling external APIs/SaaS, partner SFTP/HTTPS endpoints, and public AWS service endpoints without VPC endpoints.
  - But they must **not accept inbound connections** from the internet.
- **NAT = outbound-only**: connections must be **started from inside the VPC**. Unsolicited inbound traffic can't reach the private resources through NAT.
- **Public vs private subnet**:
  - **Public subnet** = its route table has `0.0.0.0/0 → internet gateway (IGW)`.
  - **Private subnet** = no route to the IGW. Internet-bound traffic goes `0.0.0.0/0 → NAT gateway` instead.
- **Flow (public NAT gateway)**:
  - The instance's private IP is translated to the NAT gateway's private IP.
  - The IGW then maps that to the NAT gateway's **Elastic IP**, and the packet goes out.
  - The reply returns the same path, and the NAT gateway translates it back to the instance.
- **Stateful**: the NAT gateway remembers connections, so replies to outbound requests are allowed back automatically.
- NAT is **IPv4 only** for normal use. **For IPv6 outbound-only, use an egress-only internet gateway** (no NAT needed, since IPv6 addresses are global). NAT gateways also do **NAT64** (IPv6-only workloads reaching IPv4 destinations with **DNS64** on Route 53 Resolver).

## B. NAT gateway types
- **Public NAT gateway** (default, zonal):
  - Created **in a public subnet** with an **Elastic IP** associated at creation.
  - Private subnets route `0.0.0.0/0` to it. Its subnet routes to the IGW.
  - **Needs an internet gateway** attached to the VPC (creation fails otherwise).
  - Can also route to a **Transit Gateway** or **virtual private gateway**. Then the source IP is its **private** IP (the EIP is only used with the IGW in the same VPC).
- **Private NAT gateway** (zonal):
  - **No Elastic IP**, no internet. Translates private IPs to the NAT gateway's private IP for traffic to **other VPCs or on-premises** via Transit Gateway or a virtual private gateway.
  - Use case: **overlapping CIDRs**. Hide a VPC's (possibly overlapping) range behind a routable, non-overlapping NAT IP.
  - Traffic routed from a private NAT gateway to an IGW is **dropped**.
- **Regional NAT gateway** (availability mode "regional", **launched Nov 2025**):
  - **One NAT gateway ID for the whole VPC**. It **automatically expands and contracts across AZs** where your workloads (ENIs) exist, giving **high availability by default** with zonal affinity.
  - **No public subnet needed**. It is a standalone resource with **its own route table** (pre-configured route to the IGW). Fewer public subnets mean less chance of misconfiguring private resources.
  - The **same route entry** (`0.0.0.0/0 → regional NAT ID`) works for private subnets in every AZ.
  - **Up to 32 IP addresses per AZ** (vs 8 for zonal), so more connections to popular destinations.
  - **Automatic mode** (AWS manages IPs and AZ expansion; recommended) or **manual mode** (you manage IPs per AZ).
  - Expanding to a new AZ can take **up to 60 minutes**. Meanwhile that AZ's traffic is processed **cross-zone** by an existing AZ.
  - **Does not support private NAT** (use zonal for private NAT). Not in constrained AZs. Supports Transit Gateway routes in its route table.
  - **Pricing: per hour per AZ it runs in + per GB processed** (same rates as zonal).
  - AWS **recommends regional NAT for all use cases except private NAT**.
  - Migrating from zonal resets connections (do it in a maintenance window). You can reuse old EIPs by deleting the zonal gateways first.
  - Metrics use the `NatGatewayId` + `AvailabilityZone` dimensions.

## C. How a (zonal) NAT gateway works
- **Created in one specific AZ** (in one subnet), **redundant within that AZ** only. If that AZ fails, the NAT gateway fails.
- **Protocols**: TCP, UDP, ICMP. **No IPsec** directly (use NAT-T, i.e. IPsec in UDP). No IP fragmentation support for TCP/ICMP. MTU up to 8,500 (use 1,500 toward the internet).
- **Bandwidth**: **5 Gbps, auto-scales to 100 Gbps**. **Packets**: 1M pps, auto-scales to **10M pps** (beyond that it drops packets). For more, split workloads across multiple NAT gateways/subnets.
- **Connections**: each IPv4 address supports **55,000 simultaneous connections to each unique destination** (destination IP + port + protocol). Add **secondary IPs (up to 8 total per zonal NAT: 1 primary + 7 secondary)** to raise it.
  - **Elastic IPs per public NAT gateway: 2 by default** (quota increase up to 8).
- **Idle timeout: 350 seconds**. Idle connections are dropped. The NAT gateway sends **RST** (not FIN) if the client keeps using the stale connection. Use **TCP keep-alive under 350 s** for long-lived idle connections (database connections to external hosts, long polling).
- **Ports**: the NAT gateway uses source ports **1024–65535**, so **NACLs must allow these ephemeral ports** for return traffic.
- **No security groups on a NAT gateway**. Control traffic with **security groups on the instances** and **NACLs** on the subnets.
- It has a **requester-managed ENI** you can see but not modify (only tag).
- **Routing rules**:
  - **Can't route traffic into a NAT gateway through VPC peering** (Client → Peering → NAT → Internet is not supported).
  - Traffic **from** a NAT gateway **to** a peered VPC works, with automatic "return to sender".
  - **Can't reach a NAT gateway from Site-to-Site VPN / Direct Connect via a virtual private gateway**. It **works via a Transit Gateway**.
- **Quota**: **5 NAT gateways per AZ** (adjustable). Pending/available/deleting gateways count.
- **Not pingable**: a NAT gateway doesn't answer ping. Test from a private instance instead.
- **Fully managed**: no patching, no instance sizing. AWS handles availability inside the AZ and scaling.

## D. High availability design
- **Zonal NAT gateways**:
  - **Create one NAT gateway per AZ**, each in that AZ's public subnet.
  - Give each AZ's private subnets **their own route table** pointing to the **same-AZ NAT gateway**.
  - Why:
    1. **Resilience**: if one AZ fails, other AZs keep internet access.
    2. **Cost**: avoids **cross-AZ data charges** (traffic from AZ-b to a NAT in AZ-a pays inter-AZ transfer **plus** NAT processing).
- **Single shared NAT gateway** = cheaper hourly, but a **single point of failure** for all AZs and cross-AZ charges. OK for dev/test only.
- **Regional NAT gateway**: gives per-AZ affinity and HA automatically with one route target. It is the simplest HA design now (public NAT use cases).
- **Centralized egress** (many VPCs):
  - Spoke VPCs → **Transit Gateway** → an **egress VPC** with NAT gateways (per AZ) + optional **AWS Network Firewall** → IGW.
  - Fewer NAT gateways overall, central inspection and logging.
  - Adds Transit Gateway attachment/processing costs. Compare with a NAT per VPC.

## E. NAT gateway vs NAT instance
| | NAT gateway | NAT instance |
|---|---|---|
| Managed by | AWS (no patching) | You (EC2 you patch/scale) |
| Availability | Redundant within the AZ (use one per AZ, or regional) | Single instance; you script failover/ASG |
| Bandwidth | 5 → 100 Gbps auto | Limited by instance type |
| Cost | Hourly + per-GB processing | EC2 instance price (cheap types possible), no per-GB NAT fee |
| Security groups | Not supported (use NACLs + instance SGs) | Supported |
| Public IP | Elastic IP (or regional automatic IPs) | Elastic IP / public IP |
| Port forwarding / bastion | Not supported | Possible (custom config) |
| Source/destination check | n/a | **Must be disabled** on the instance |
| Fragmentation | Not supported for TCP/ICMP | Supported |
| Timeout behavior | 350 s idle, sends RST | Your OS settings |
- The **NAT AMI** is built on **Amazon Linux AMI 2018.03**, which reached **end of maintenance support on 31 Dec 2023**. AWS recommends **migrating to NAT gateways**. If a NAT instance is still needed, **build your own NAT AMI** from current Amazon Linux (iptables masquerade).
- When a NAT instance can still make sense:
  - Very low-traffic dev environments where the NAT gateway hourly + per-GB cost dominates.
  - Endpoints that send **fragmented packets**.
  - A need for SGs/port forwarding on the NAT box.
- Exam default answer: **NAT gateway** ("managed, highly available, scalable, least operational overhead").

## F. Alternatives to sending traffic through NAT
- **VPC gateway endpoints** for **S3 and DynamoDB**:
  - **Free** (no hourly or per-GB charge). Added as routes in route tables.
  - Private traffic **bypasses the NAT gateway** entirely. The #1 NAT cost saver for data pipelines.
- **VPC interface endpoints (PrivateLink)** for most other AWS services: ECR api/dkr, CloudWatch Logs, STS, Secrets Manager, SSM, KMS, Glue, Kinesis, SQS, SNS, Athena…
  - Hourly per AZ + per-GB. Often **cheaper than NAT for heavy traffic** and keeps traffic private.
  - Compare by volume.
- **Egress-only internet gateway**: IPv6 outbound-only, **free** (no processing fee). Dual-stack / IPv6 workloads can avoid NAT for IPv6 destinations.
- **Public subnets with public IPs** (no NAT): only for resources that must be reachable. This increases exposure and public IPv4 costs, so not recommended for backends.
- **AWS PrivateLink to SaaS providers** (the vendor offers an endpoint service): private connectivity without NAT.
- **Proxy fleets** (Squid on EC2/ECS) for domain allowlisting, and caching (rarely needed now with Network Firewall).

## G. Security and egress control
- **NAT is not a firewall**: it blocks **unsolicited inbound** but allows **any outbound destination**. Add egress control:
  - **Security groups** on instances: restrict outbound ports/destinations (for example only 443).
  - **NACLs** on subnets: stateless allow/deny (remember ephemeral ports 1024–65535).
  - **AWS Network Firewall**: stateful inspection, **domain allowlists (SNI/Host)**, IPS, between private subnets and NAT, or in a centralized egress VPC.
  - **Route 53 Resolver DNS Firewall**: block DNS resolution of malicious/unapproved domains (data exfiltration protection).
  - **GWLB + third-party firewalls** in the egress path.
- **NAT Elastic IP as a stable source IP**: outbound calls from all private resources appear to come from the **NAT gateway's EIP(s)**. **Partners allowlist those IPs** (skill 1.1.8). Keep EIPs fixed (don't release them). With multiple AZs, give partners all the NAT EIPs. A regional NAT in manual mode lets you control the IPs (BYOIP/IPAM policies in automatic mode).
- **Visibility**:
  - **VPC Flow Logs** on the NAT gateway ENI or subnets show who talks to which external IPs (query with Athena).
  - **NAT gateway traffic inspection** (Network Firewall integration; verify specifics).
- **Data exfiltration concerns**: private workloads with open NAT egress can upload data anywhere. Restrict with Network Firewall domain lists, DNS Firewall, endpoint policies, and SCPs/permissions.
- **No inbound through NAT**: to let the internet reach a private service, use a **load balancer** (or API Gateway, CloudFront with VPC origins), never NAT.

## H. Cost
- **NAT gateway pricing** (US East example):
  - **$0.045 per hour** per NAT gateway (zonal) or **per AZ** (regional).
  - **Plus $0.045 per GB processed**, **in both directions** through the gateway (verify direction wording).
  - **Plus standard data transfer** (for example internet egress ~$0.09/GB, **cross-AZ** $0.01/GB each way if the NAT is in another AZ).
  - **Plus public IPv4 charges ($0.005/h per EIP)**.
- **Monthly baseline**: one NAT gateway running 24/7 ≈ **$32/month** before any data. Three AZs ≈ **$97/month** + data.
- **Big hidden cost (exam favorite)**:
  - Private EMR/Glue/ECS/EKS/Lambda/EC2 workloads reading/writing **TBs in S3**, or pulling **large container images from ECR**, through NAT.
  - Each GB pays **$0.045 NAT processing** (+ cross-AZ if misrouted).
  - **Fix**: an **S3 gateway endpoint (free)**, ECR/other interface endpoints, keep each AZ on its own NAT.
- **Cost optimization checklist**:
  1. S3 + DynamoDB gateway endpoints in every VPC with private workloads.
  2. Interface endpoints for high-volume AWS APIs (ECR, Logs, STS, Kinesis…) when cheaper than NAT per GB.
  3. One NAT per AZ with same-AZ routing (or regional NAT) to avoid cross-AZ fees.
  4. Delete NAT gateways in idle dev/test VPCs (they bill hourly even with no traffic). Use **IPv6 + egress-only IGW** where possible.
  5. Centralized egress via Transit Gateway when you have many VPCs (fewer NATs), but compare TGW per-GB costs.
  6. Cache packages/images (CodeArtifact, ECR pull-through cache) instead of downloading from the internet every build.
- **Find NAT spend**: Cost Explorer (usage types `NatGateway-Hours`, `NatGateway-Bytes`), **CloudWatch `BytesOutToDestination`**, and VPC Flow Logs + Athena to find top talkers and destinations (for example S3 IP ranges → add an endpoint).

## I. Monitoring
- **CloudWatch metrics** (namespace `AWS/NATGateway`, 1-minute, kept 15 months):
  - Traffic: **`BytesOutToDestination`**, `BytesInFromSource`, `BytesInFromDestination`, `BytesOutToSource` (and the matching `Packets*` metrics).
  - Connections: **`ActiveConnectionCount`**, `ConnectionAttemptCount` vs `ConnectionEstablishedCount` (a gap = destinations not answering).
  - Errors: **`ErrorPortAllocation`** (> 0 means port exhaustion: too many connections to the same destination), **`IdleTimeoutCount`** (connections reaching the 350 s idle timeout), **`PacketsDropCount`** (> 0.01% of traffic → check AWS service health).
  - Peaks: `PeakBytesPerSecond`, `PeakPacketsPerSecond`.
- **Alarms**: `ErrorPortAllocation > 0`, `PacketsDropCount` rising, `BytesOutToDestination` above a budget threshold (cost spike), `IdleTimeoutCount` spikes.
- **VPC Flow Logs** for per-flow details (source instance, destination, bytes, accept/reject). Use Athena or CloudWatch Logs Insights.
- **CloudTrail** for API changes (`CreateNatGateway`, `DeleteNatGateway`, route table changes).
- **Reachability Analyzer** to check whether a path from an instance to the internet via NAT is valid (routes, NACLs, SGs).

## J. Troubleshooting (symptom → cause → fix)
- **Private instance can't reach the internet** →
  - The private subnet route table lacks `0.0.0.0/0 → nat-…`, or a more specific route sends traffic elsewhere.
  - The NAT gateway is in a **private** subnet (its subnet must route to the IGW), or the VPC has no IGW.
  - The NAT is not `Available` yet.
  - The SG on the instance blocks outbound, or **NACLs block outbound or the ephemeral return ports (1024–65535)**.
  - An unsupported protocol (only TCP/UDP/ICMP).
- **NAT gateway creation `Failed`** → subnet has no free IPs, no IGW attached, the EIP is already associated, AZ not supported (`NotAvailableInZone`, constrained AZ). Failed gateways auto-delete after about 1 hour.
- **"exceed the limit of 5 NAT gateways"** → per-AZ quota. Request an increase or wait for deleting ones to clear.
- **"maximum number of addresses has been reached"** → EIP quota (5 per Region default). Release unused EIPs or request an increase.
- **Connections drop after 350 seconds idle** → NAT idle timeout. Enable TCP keep-alive under 350 s, or send traffic periodically.
- **`ErrorPortAllocation` / can't open more connections to one destination** → over 55,000 simultaneous connections per IP per destination. Add secondary IPs (up to 8 zonal, 32 per AZ regional), spread across NAT gateways/AZs, reuse connections (connection pooling, HTTP keep-alive), close idle connections.
- **Some TCP connections fail to a specific destination** → the destination sends **fragmented packets** (not supported), or `tcp_tw_recycle` is on at the remote server. Fix the remote side, or use a NAT instance.
- **IPsec VPN from a private instance fails** → NAT gateways don't support raw IPsec. Use NAT-T (UDP 4500).
- **Large ping fails** (`ping -s 10000`) → fragmentation is not supported. Expected behavior.
- **Traceroute doesn't show the NAT IP** → traffic is using another gateway (a more specific route to the IGW/VGW).
- **Unexpected huge NAT bill** → S3/ECR/AWS API traffic through NAT, cross-AZ routing to one NAT, idle NATs in unused VPCs. Add gateway/interface endpoints, per-AZ routing, delete idle NATs.
- **One AZ's workloads lost internet when another AZ failed** → all subnets routed to a single NAT in the failed AZ. Use one NAT per AZ, or a regional NAT gateway.
- **Partner says your requests come from unexpected IPs** → traffic leaves via different NAT EIPs per AZ (or a new NAT after recreation). Give the partner all EIPs, and keep EIPs stable.
- **On-prem users can't use the VPC's NAT via VPN/DX** → not supported through a virtual private gateway. Use a Transit Gateway.

## K. Limits and numbers to remember
| Item | Value |
|---|---|
| NAT gateways per AZ | 5 (adjustable) |
| Bandwidth | 5 Gbps, auto-scales to 100 Gbps |
| Packets per second | 1M, auto-scales to 10M |
| Connections per IP per unique destination | 55,000 |
| IPs per zonal NAT gateway | up to 8 (1 primary + 7 secondary) |
| IPs per AZ (regional NAT) | up to 32 |
| EIPs per public NAT gateway (default) | 2 (quota increase to 8) |
| Elastic IPs per Region (default) | 5 |
| Idle timeout | 350 seconds (sends RST) |
| Ephemeral ports used | 1024–65535 |
| Protocols | TCP, UDP, ICMP (no raw IPsec, no fragmentation for TCP/ICMP) |
| MTU | 8,500 supported; use 1,500 to the internet |
| Regional NAT expansion to a new AZ | up to 60 minutes |
| Failed NAT gateway auto-delete | about 1 hour |
| Price (US East example) | $0.045/h per NAT (or per AZ for regional) + $0.045/GB processed |
| Public IPv4 | $0.005/h per address |
| Gateway endpoints (S3, DynamoDB) | Free |
| CloudWatch metric retention | 15 months, 1-minute data |
| NAT AMI (NAT instances) | Amazon Linux 2018.03, end of maintenance 31 Dec 2023 |

## Scenarios (if → then, because)
- **If** EC2, ECS or Lambda workloads in **private subnets** must download packages from the internet but must stay unreachable from outside, **then** use a **NAT gateway** (Network Address Translation gateway) and add the route `0.0.0.0/0 → NAT gateway` to the private subnets' route tables. A public NAT gateway sits in a public subnet with an **Elastic IP (EIP)** and sends traffic out through the **internet gateway (IGW)**. **This works because** NAT is **outbound-only**: it rewrites the private source IP to its own IP, and connections must start from inside the VPC. It is **stateful**, so replies come back automatically, but unsolicited inbound traffic cannot reach the private resources.
- **If** internet access must survive an **Availability Zone (AZ)** outage, **then** create **one NAT gateway per AZ**, each in that AZ's public subnet, and give each AZ's private subnets their own route table pointing to the **same-AZ NAT gateway**; or use one **regional NAT gateway**. **This works because** a zonal NAT gateway is redundant only **inside its own AZ**, so if that AZ fails, it fails. One NAT per AZ keeps the other AZs online and also avoids **cross-AZ data charges**. A regional NAT gateway spreads across AZs automatically.
- **If** the team wants highly available outbound internet with the least setup and no public subnets, **then** use a **regional NAT gateway** in **automatic mode**, where AWS manages the IPs and the AZ expansion. **This works because** one NAT gateway ID serves the whole VPC: it expands and contracts across the AZs where your workloads run, has **its own route table** to the IGW, and needs **no public subnet**. The same route `0.0.0.0/0 → regional NAT ID` works in every AZ. The catch: expanding to a new AZ can take **up to 60 minutes**, and it does **not support private NAT**.
- **If** a private **Amazon EMR** or **AWS Glue** job reads **50 TB** from **Amazon S3** and the NAT bill explodes, **then** add an **S3 gateway endpoint** (a VPC gateway endpoint, added as a route in the route tables). **This works because** S3 traffic then goes privately through the endpoint and **bypasses the NAT gateway**, so it no longer pays **$0.045 per GB** NAT processing (plus cross-AZ fees if misrouted). Gateway endpoints for S3 and DynamoDB are **free**, with no hourly or per-GB charge.
- **If** pulling container images through NAT is expensive, **then** add **Amazon Elastic Container Registry (ECR) interface endpoints** (AWS PrivateLink, for the ECR api and dkr) plus an **S3 gateway endpoint**, or use an **ECR pull-through cache**. **This works because** image traffic then skips **NAT processing per GB**. Interface endpoints cost per hour per AZ plus per GB, so they are often **cheaper than NAT for heavy traffic**; compare by volume.
- **If** a partner API allows calls only from fixed source IPs, **then** send outbound calls through a **NAT gateway with Elastic IPs (EIPs)** and give the partner those EIPs. **This works because** all private resources' outbound calls appear to come from the NAT gateway's EIPs. With several AZs, give the partner **all** the NAT EIPs, and keep them fixed (do not release them).
- **If** two VPCs with **overlapping CIDR ranges** must talk to an on-premises network, **then** use a **private NAT gateway** (zonal) with **AWS Transit Gateway** routing. **This works because** a private NAT gateway has **no Elastic IP** and no internet access; it translates the VPC's private IPs to its own routable, **non-overlapping** private IP for traffic to other VPCs or on-premises. Regional NAT gateways do not support private NAT.
- **If** IPv6 workloads need outbound-only internet access, **then** use an **egress-only internet gateway**, not NAT. **This works because** IPv6 addresses are global, so no address translation is needed, and the egress-only gateway allows outbound only. It is **free**, with no processing fee.
- **If** IPv6-only workloads must reach IPv4-only services, **then** use the NAT gateway's **NAT64** feature together with **DNS64** on **Amazon Route 53 Resolver**. **This works because** NAT gateways can translate IPv6-only traffic to IPv4 destinations, and DNS64 gives the workloads addresses they can use for those IPv4-only names.
- **If** outbound traffic must be limited to approved domains only, **then** put **AWS Network Firewall** with a **domain allowlist** in the egress path (between the private subnets and the NAT, or in a central egress VPC), plus **Route 53 Resolver DNS Firewall**. **This works because** **NAT is not a firewall**: it blocks unsolicited inbound traffic but allows **any outbound destination**. Network Firewall does stateful inspection and checks domains (SNI/Host), and DNS Firewall blocks the DNS lookup of unapproved domains, which helps stop data exfiltration.
- **If** many VPCs each pay for **3 NAT gateways**, **then** build a **centralized egress VPC**: spoke VPCs send traffic through **AWS Transit Gateway (TGW)** to one egress VPC with NAT gateways per AZ (and optional AWS Network Firewall). **This works because** you run **fewer NAT gateways** overall and get central inspection and logging. The catch: it adds Transit Gateway attachment and **per-GB processing** costs, so compare with one NAT per VPC.
- **If** long-lived idle connections to an external database keep dropping, **then** enable **TCP keep-alive under 350 seconds**. **This works because** the NAT gateway drops connections idle for **350 s** and sends **RST** if the client reuses them; keep-alive traffic stops them going idle.
- **If** `ErrorPortAllocation` alarms fire during a big crawl of one API, **then** add **secondary IPs** to the NAT gateway (up to 8 for zonal), spread traffic across more NAT gateways, and **reuse connections** (connection pooling, HTTP keep-alive). **This works because** each NAT IP supports only **55,000 simultaneous connections** to each unique destination (IP + port + protocol); `ErrorPortAllocation` above 0 means that port limit is used up. More IPs and fewer new connections give more room.
- **If** a security review asks "can the internet reach my private instances through NAT?", **then** the answer is **no**: to let the internet reach a private service, use a **load balancer** or **Amazon API Gateway**, never NAT. **This works because** NAT is **outbound-only**; connections must start from inside the VPC.
- **If** a cost-sensitive dev VPC rarely uses the internet, **then** **delete the NAT gateway** when idle, use **VPC endpoints** for AWS services, or, rarely, run a small **self-built NAT instance** (an EC2 instance doing NAT). **This works because** a NAT gateway bills **hourly even with no traffic** (about **$32/month** each before data), while a NAT instance costs only the EC2 price. The catch: the old NAT AMI reached end of maintenance on **31 Dec 2023**, so you must build your own AMI, and you patch, scale and handle failover yourself.
- **If** an exam asks for "managed, scalable, highly available, least maintenance" outbound internet for private subnets, **then** choose a **NAT gateway**, not a NAT instance. **This works because** AWS manages it (no patching or sizing), it is redundant within its AZ, and it scales automatically from **5 to 100 Gbps**.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages and announcements: NAT gateway connectivity types (public/private, EIP rules, TGW/VGW source IP behavior, NAT64), NAT gateway basics (zonal redundancy, TCP/UDP/ICMP, 5→100 Gbps, 1M→10M pps, 55,000 connections per destination per IP, up to 8 IPs, 2 EIPs default, no security groups, requester-managed ENI, ports 1024–65535, peering and VPN/DX via VGW limits, MTU 8,500), regional NAT gateways (Nov 2025: automatic multi-AZ expansion, no public subnet, own route table, 32 IPs per AZ, automatic/manual modes, up to 60 minutes expansion, no private NAT, not in constrained AZs, migration steps, recommended for all except private NAT), CloudWatch metrics and dimensions (15-month retention), troubleshooting topics (350 s idle timeout with RST, failed creation causes, 5 per AZ quota, fragmentation, IPsec), NAT instances (NAT AMI end of maintenance 31 Dec 2023), VPC pricing (US East (Ohio) example $0.045/h and $0.045/GB, regional per AZ, public IPv4 $0.005/h, gateway endpoints free).
Not confirmed (verify): whether per-GB processing applies to both directions in all cases, NAT gateway traffic inspection feature specifics, us-east-1 exact NAT prices (example used Ohio, which matches commonly quoted us-east-1 rates).

# Amazon VPC and PrivateLink – 4. Cost, monitoring, security best practices, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Network cost model (what you pay for)
- **VPC itself, subnets, route tables, SGs, NACLs, IGW, gateway endpoints**: **free**.
- **NAT gateway**: about **$0.045/hour** + **$0.045/GB** processed (us-east-1) **(verify)**; per AZ for HA. Biggest hidden network cost for data pipelines.
- **Interface endpoints (PrivateLink)**: about **$0.01 per AZ-hour** + **$0.01/GB** (tiered) **(verify)**.
- **Transit Gateway**: about **$0.05/attachment-hour** + **$0.02/GB** processed **(verify)**.
- **VPC peering**: no hourly fee; data transfer: same-AZ free, cross-AZ about $0.01/GB each way, cross-Region standard inter-Region rates.
- **Data transfer**: **in from internet free**; **out to internet** tiered (about $0.09/GB first tiers); **between AZs** about $0.01/GB each direction; **between Regions** about $0.02/GB; **within the same AZ using private IP** free.
- **Elastic IPs**: public IPv4 addresses cost about **$0.005/hour each** (since Feb 2024), whether attached or not **(verify)**.
- **Site-to-Site VPN**: about $0.05/connection-hour + data out.
- **Direct Connect**: port-hours + reduced data transfer out; no charge for data in.
- **Flow Logs**: ingestion/storage in CloudWatch/S3/Firehose.
- **Reachability Analyzer / Network Access Analyzer**: per analysis.
- **Traffic Mirroring**: per ENI-hour.
- **Client VPN**: per association-hour + per connection-hour.
- **Network Firewall**: per endpoint-hour + per GB.

## B. Cost optimization for data platforms
- **S3 and DynamoDB gateway endpoints** in every VPC that talks to them: removes NAT data charges for the largest flows.
- **Keep chatty services in the same AZ** when latency/availability permit (Spark shuffles, Kafka clients) or use rack/AZ awareness; cross-AZ traffic costs add up.
- **One NAT per AZ** (not per subnet); consider **centralized egress via TGW** only if traffic volumes justify TGW per-GB fees (centralized egress adds TGW processing cost).
- **Interface endpoints**: share centrally via TGW? (DNS complexity) or deploy only the ones needed; don't create dozens in dev VPCs.
- **Use IPv6 / egress-only IGW** to avoid NAT costs for IPv6-capable traffic.
- **Release unused EIPs**; avoid public IPv4 where private/endpoint access suffices.
- **Compress and batch** data crossing AZs/Regions; use S3 same-Region buckets and cross-Region replication only when required.
- **Review NAT bytes** with CloudWatch `BytesOutToDestination` and **VPC Flow Logs** to find top talkers and move them to endpoints.
- **Cost Explorer usage types**: `NatGateway-Bytes`, `DataTransfer-Regional-Bytes`, `VpcEndpoint-Hours`, `TransitGateway-Bytes`.

## C. Monitoring
- **VPC Flow Logs** (S3 + Athena) for connectivity/security/cost analysis.
- **CloudWatch metrics**: NAT gateway (`ErrorPortAllocation`, `PacketsDropCount`, `BytesOutToInternet`, `ActiveConnectionCount`), TGW (`BytesIn/Out`, `PacketDropCountNoRoute`), VPN (`TunnelState`), Direct Connect, VPC endpoint (`BytesProcessed`, `PacketsDropped`) **(verify names)**, Network Firewall.
- **Reachability Analyzer** for path debugging; **Network Access Analyzer** for unintended exposure; **VPC IPAM** for IP planning; **Network Manager** for global view.
- **AWS Config rules**: `vpc-flow-logs-enabled`, `vpc-default-security-group-closed`, `restricted-ssh`, `restricted-common-ports`, `vpc-sg-open-only-to-authorized-ports`, `internet-gateway-authorized-vpc-only`, `no-unrestricted-route-to-igw`, `subnet-auto-assign-public-ip-disabled`.
- **GuardDuty** uses flow logs and DNS logs automatically for threats.
- **Security Hub** controls (EC2.x/VPC): default SG restrictions, flow logs enabled, no 0.0.0.0/0 on admin ports.
- **Alarms**: NAT `ErrorPortAllocation` > 0, VPN `TunnelState` < 1, TGW drops, endpoint packet drops.

## D. Security best practices
- **Least-privilege SGs**: reference SGs, no `0.0.0.0/0` on management ports; use **SSM Session Manager** instead of SSH/RDP.
- **Private subnets** for compute and data; **isolated subnets** for databases; no public IPs unless needed.
- **VPC endpoints + endpoint policies + bucket policies** to build a data perimeter.
- **Block default VPC usage**; delete default VPCs; use **VPC BPA**.
- **Flow Logs on** in all VPCs; central log archive.
- **Network Firewall / proxy** for egress control (domain allow lists).
- **Segment** by environment (separate VPCs/accounts) and use **TGW route tables** for isolation.
- **Use PrivateLink** to expose services instead of broad peering.
- **IMDSv2**, **encryption in transit (TLS)**, **ACM** certificates on load balancers.
- **Tag and automate** via IaC (CloudFormation/CDK/Terraform); guardrails with SCPs (deny `ec2:CreateInternetGateway`, `ec2:AttachInternetGateway`, `ec2:CreateVpcPeeringConnection` outside network team).
- **Public access for data services**: avoid public Redshift/RDS/OpenSearch; use VPN/Client VPN/Verified Access for admin UIs.

## E. Troubleshooting (symptom → cause → fix)
- **Instance in private subnet has no internet** → missing NAT route, NAT in wrong subnet/AZ, SG/NACL egress, NAT out of ports (`ErrorPortAllocation`).
- **Can't SSH** → SG, NACL, route, key, public IP/EIP missing, using private subnet without bastion/SSM.
- **Can't reach S3 from private subnet** → no gateway endpoint/NAT, endpoint policy deny, bucket policy `aws:SourceVpce` mismatch, wrong Region.
- **Intermittent timeouts to AWS APIs** → NAT port exhaustion, missing endpoint, DNS issues.
- **Peering works one way** → route missing on one side or SG blocking.
- **Overlapping CIDR errors** → re-IP or use PrivateLink.
- **Large packets drop over VPN/TGW** → MTU/MSS mismatch (VPN 1500).
- **ENI limit/IPs exhausted** → subnet too small (Glue/EMR/Lambda/Fargate consume IPs) → add subnets/secondary CIDR, request ENI quota.
- **Lambda/Glue "unable to create ENI"** → IP exhaustion or SG/subnet issues or ENI quota.
- **Elevated NAT costs** → find top flows via Flow Logs, add endpoints, reduce cross-AZ.
- **Route 53 Resolver throttling** → 1,024 pps/ENI limit → caching/distribution.

## F. Limits cheat sheet
| Item | Default |
|---|---|
| VPCs per Region | **5** (adjustable to hundreds) |
| Subnets per VPC | **200** |
| IPv4 CIDRs per VPC | **5** (to 50) |
| Route tables per VPC | **200** |
| Routes per table | **500** (to 1,000); propagated 100 |
| Security groups per Region | **2,500** |
| Rules per SG | **60** in / **60** out (per IP version) |
| SGs per ENI | **5** (to 16); rules × SGs ≤ 1,000 |
| NACL rules | **20** per direction (to 40) |
| NACLs per VPC | 200 |
| IGW per Region | 5 (equals VPC quota) |
| NAT gateways per AZ | **5** |
| EIPs per Region | **5** |
| ENIs per Region | **5,000** (per AZ) |
| Prefix lists | 100 per Region; 1,000 entries |
| NAU per VPC | **64,000** (to 256,000) |
| TGW attachments | **5,000**; route tables 20 |
| TGW MTU | 8500 (VPN 1500) |
| VPN tunnel throughput | 1.25 Gbps |
| DNS per ENI to resolver | 1,024 pps |

## G. Exam skills mapping
- **1.2.4 Optimize cost while processing data**: cut NAT and transfer cost.
- **3.3.4 Troubleshoot performance**: troubleshoot connectivity and performance.

## H. Scenarios: "If X → Y, because Z"
- If NAT data charges dominate the bill and most traffic is S3 → **S3 gateway endpoint**, because it's free and bypasses NAT.
- If a Glue job fails with ENI/IP errors → **bigger subnets / secondary CIDR, check ENI quota**, because jobs allocate many ENIs/IPs.
- If a Lambda in a VPC needs Kinesis → **kinesis-streams interface endpoint or NAT**, because VPC Lambdas lack internet by default.
- If security wants only approved S3 buckets reachable from the VPC → **gateway endpoint policy with allowed bucket ARNs**, because the endpoint policy filters destinations.
- If database access for engineers must avoid public exposure → **private subnet + SSM Session Manager port forwarding (or Client VPN)**, because it avoids opening inbound ports.
- If auditors want network evidence → **Flow Logs to S3 with Athena queries + Config rules**, because they show accepted/rejected flows and configuration compliance.
- If cross-AZ costs jump after scaling Spark → **AZ-aware placement or restrict to one AZ for transient jobs**, because cross-AZ data transfer is billed.
- If a new VPC cannot be peered to the data VPC → **check CIDR overlap and route/SG configuration**, because peering cannot route overlapping ranges.

Verified from AWS docs on 2026-11-09 (Amazon VPC quotas, Transit Gateway quotas, PrivateLink concepts).
Unconfirmed (verify): all price figures (NAT, endpoints, TGW, EIP public IPv4 charge, data transfer rates); CloudWatch metric names for endpoints; Config rule names; Security Hub control IDs; centralized egress cost trade-offs.

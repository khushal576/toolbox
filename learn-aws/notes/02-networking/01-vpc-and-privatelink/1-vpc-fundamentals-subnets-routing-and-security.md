# Amazon VPC and PrivateLink – 1. VPC fundamentals, subnets, routing and network security

Short notes. Each point is a fact you can be asked about.

## A. What a VPC is
- An **Amazon VPC** is your **logically isolated virtual network** inside one AWS **Region**. It spans all **Availability Zones (AZs)** of the Region, but each **subnet lives in exactly one AZ**.
- You choose the **IP address range (CIDR)**, create **subnets**, configure **route tables**, gateways, security groups and network ACLs.
- Every account has a **default VPC** in each Region (CIDR `172.31.0.0/16`, one public subnet per AZ, internet gateway). Production should use **custom VPCs**.
- Data-engineering relevance: Glue connections, EMR, Redshift, RDS/Aurora, MWAA, MSK, OpenSearch, SageMaker, Lambda-in-VPC, DMS, and Kinesis consumers all run in or attach to a VPC.
- DEA-C01: **4.1.1 update VPC security groups**, **4.1.x private connectivity**, VPC endpoints (S3 gateway endpoint, PrivateLink) for secure ingestion.

## B. CIDR and addressing
- **IPv4 CIDR for a VPC**: between **/16 (65,536 addresses) and /28 (16 addresses)**. Use RFC 1918 ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) (also `100.64.0.0/10` carrier-grade NAT range is allowed with limits).
- **Up to 5 IPv4 CIDR blocks per VPC** by default (up to 50 on request); the primary block cannot be changed, secondary blocks can be added/removed.
- **IPv6**: Amazon-provided **/56** per VPC, **/64 per subnet**; BYOIP IPv6 supported; **dual-stack** or **IPv6-only subnets**.
- **Subnet CIDR**: /16 to /28. **AWS reserves 5 IPs** in each subnet (first four and the last): network address, VPC router, DNS, future use, broadcast (not supported).
- **Plan CIDRs to avoid overlap** with other VPCs and on-premises networks (peering, TGW, VPN need non-overlapping ranges).
- **Network Address Usage (NAU)** units measure VPC size: default **64,000** per VPC (up to 256,000); peered NAU **128,000** (up to 512,000).
- **DHCP option sets** define DNS servers, domain name, NTP; one per VPC.
- **VPC DNS attributes**: `enableDnsSupport` (Amazon-provided resolver at VPC CIDR+2, `169.254.169.253`), `enableDnsHostnames` (public DNS names for instances). **Both must be on for interface endpoint private DNS and for private hosted zones**.
- **Route 53 Resolver**: 1,024 packets/second per network interface to the resolver (hard limit).

## C. Subnets
- **Public subnet**: route table has a route `0.0.0.0/0 → internet gateway (IGW)`; resources need a public IPv4 (Elastic IP/auto-assigned) or IPv6 to be reachable.
- **Private subnet**: no route to an IGW; outbound internet via **NAT gateway** (IPv4) or **egress-only internet gateway** (IPv6).
- **Isolated subnet**: no route to the internet at all (only local + VPC endpoints). Common for databases and secure data processing.
- **Subnets per VPC**: 200 default (adjustable).
- **Subnet auto-assign** public IPv4 setting; **Elastic IPs** (5 per Region default).
- **Per-AZ design**: one subnet per tier per AZ for high availability; spread Glue/EMR/Redshift/MWAA across ≥2 AZs (MWAA requires **2 private subnets in different AZs**; Redshift subnet groups; DMS subnet groups; RDS DB subnet groups need ≥2 AZs).
- **Subnets can be shared** with other accounts using **AWS RAM (VPC sharing)** inside an Organization: owner manages network, participants run resources (up to 100 participant accounts per VPC, 100 shared subnets per account, defaults).
- **Wavelength/Local Zone/Outposts subnets** extend VPCs (not core to exam).

## D. Route tables and gateways
- **Route table**: rules mapping destination CIDR → target. Every subnet is associated with exactly one route table (main by default). **Most specific route (longest prefix) wins**.
- **Local route** (VPC CIDR → local) always exists and cannot be removed.
- **Targets**: internet gateway, NAT gateway, VPC peering connection, transit gateway, virtual private gateway, VPC endpoint (gateway type), network interface/instance, egress-only IGW, Gateway Load Balancer endpoint, carrier gateway.
- **Propagated routes** (VGW/TGW with route propagation): up to 100 per table; static routes: 500 default (up to 1,000).
- **Route tables per VPC**: 200; **gateway route tables** (edge association) steer inbound traffic to appliances.
- **Internet gateway (IGW)**: horizontally scaled, redundant, no bandwidth constraints, free; provides 1:1 NAT for public IPv4. One IGW per VPC.
- **NAT gateway**: managed outbound-only IPv4 for private subnets; **zonal** (one per AZ for HA); priced per hour + per GB; up to 5 per AZ; can be **public** (with EIP) or **private** (for private-to-private translation). Details in the NAT gateway notes.
- **Egress-only IGW**: IPv6 outbound only.
- **Virtual private gateway (VGW)**: VPN/Direct Connect termination on the VPC side (one per VPC); **Transit gateway** is the scalable alternative.
- **VPC Block Public Access (BPA)**: account-level switch to block internet gateway traffic for VPCs/subnets with exclusions (50 per Region).
- **Edge associations**, **Reachability Analyzer** (analyze paths between sources and destinations, shows blocking component) and **Network Access Analyzer** (find unintended access paths).

## E. Security groups vs network ACLs (exam favourite)
| Feature | **Security group (SG)** | **Network ACL (NACL)** |
|---|---|---|
| Level | **ENI / instance / resource** | **Subnet** |
| State | **Stateful** (return traffic allowed automatically) | **Stateless** (must allow both directions, including ephemeral ports 1024–65535) |
| Rules | **Allow only** | **Allow and Deny** |
| Evaluation | All rules evaluated | **Ordered by rule number**, first match wins; `*` rule denies |
| Default | Inbound deny all, outbound allow all | Default NACL allows all; custom NACL denies all until rules added |
| Source/destination | CIDR, **other SG**, prefix list | CIDR only |
| Attach | up to **5 SGs per ENI** (16 max) | one NACL per subnet |
| Limits | **60 rules** per SG per direction (IPv4 and IPv6 separately); 2,500 SGs per Region | **20 rules** per direction (up to 40) |
- **SG referencing**: allow traffic from another SG (best practice: app tier SG allowed to DB SG on 5432 instead of IP ranges).
- **SG changes apply instantly** to existing connections? (new rules apply immediately; **tracked connections** continue until idle/timeouts; untracked connections for certain rules) **(verify nuance)**.
- **Self-referencing SG** rule needed for clusters (EMR, Redshift, MWAA, Glue ENIs, MSK) so nodes talk to each other.
- **Glue connections/jobs** need an SG with a **self-referencing inbound rule (all TCP)** and outbound access to data stores.
- **Prefix lists**: managed groups of CIDRs for SGs and route tables (AWS-managed lists like S3 and DynamoDB gateway endpoint prefixes `com.amazonaws.<region>.s3`).
- **NACLs for explicit denies** (block an IP range) and as a second layer; SGs for fine-grained least privilege.
- **AWS Network Firewall** (stateful/stateless deep inspection, domain filtering), **Route 53 Resolver DNS Firewall**, **Firewall Manager** and **WAF** add higher-layer controls.
- **ENI**: virtual network card with private IPv4s, optional EIP, IPv6, MAC, SGs. **Network interfaces per Region: 5,000 (adjustable)** per AZ.
- **Traffic Mirroring**: copy ENI traffic to a monitoring appliance.

## F. VPC Flow Logs and visibility
- **VPC Flow Logs** capture **IP traffic metadata** (not payload) at VPC, subnet or ENI level. Fields: version, account, interface, source/dest IP/port, protocol, packets, bytes, start/end, action (`ACCEPT/REJECT`), log-status; custom format adds `pkt-srcaddr`, `vpc-id`, `subnet-id`, `tcp-flags`, `flow-direction`, `traffic-path`, etc.
- **Destinations**: CloudWatch Logs, S3 (text or Parquet, Hive-compatible partitions), Firehose.
- **Aggregation interval**: 1 or 10 minutes (default 10 minutes).
- **Not captured**: DHCP, Amazon DNS server traffic, Windows license, instance metadata (169.254.169.254), Time Sync, traffic to the VPC router reserved IP, etc.
- **Use cases**: troubleshoot connectivity (REJECT), security analysis, cost analysis (NAT data processed), compliance. **Athena** over S3 Flow Logs is the standard analysis pattern.
- GuardDuty reads flow logs on its own (you don't need to enable them).
- **Cost**: vended-log ingestion/S3 storage; S3 Parquet reduces Athena scans.
- **Traffic Mirroring**, **Reachability Analyzer**, **Network Access Analyzer**, **VPC IPAM** (IP address management across accounts/Regions) complete the toolset.

## G. Data-platform networking patterns
- **Glue jobs in a VPC**: a **Glue network connection** gives the job ENIs in your subnet; requires **NAT or VPC endpoints** for S3, Glue, CloudWatch, STS, KMS if no internet; S3 access via **gateway endpoint** (cheap).
- **EMR in private subnets**: S3 gateway endpoint, endpoints for STS/KMS/Glue/Secrets Manager as needed; control plane access via VPC endpoint for EMR **(verify)**.
- **Redshift in a VPC**: subnet group (≥2 AZs), SGs, **enhanced VPC routing** to force COPY/UNLOAD traffic through the VPC (so endpoints/NAT, flow logs, policies apply); **public accessibility** off for prod.
- **MWAA**: 2 private subnets, SG self-reference, endpoints for private routing (see MWAA notes).
- **RDS/Aurora**: private subnets only; access via SG-to-SG rules, bastion/SSM, or PrivateLink/TGW from other VPCs.
- **Lambda in VPC**: ENIs in subnets; needs NAT/endpoints for AWS APIs; set SGs.
- **MSK**: brokers in private subnets; clients in same or peered VPC; **multi-VPC private connectivity** uses PrivateLink.
- **QuickSight / Athena / SageMaker Studio** can attach to VPCs with endpoints.
- **Layered pattern**: public subnets (load balancers, NAT) → private app subnets → isolated data subnets.
- **Egress control**: NAT + Network Firewall or proxy for allow-listed domains; endpoint policies to restrict data exfiltration.

## H. Exam skills mapping
- **4.1.1 Update VPC security groups**: security groups vs NACLs.
- **1.1.8 Create IP allowlists for data sources**: IP allowlists and network paths.
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: endpoint policies.

## I. Scenarios: "If X → Y, because Z"
- **If** instances in a private subnet must download patches from the internet, **then** put a **NAT gateway** in a **public subnet** and add a route **`0.0.0.0/0` → NAT gateway** to the private subnet's route table. A NAT gateway gives private resources **outbound-only IPv4** access. **This works because** a private subnet has no route to the **internet gateway (IGW)**, but the NAT gateway in the public subnet does. NAT gateways are **zonal**, so use **one per Availability Zone (AZ)** for high availability; they charge **per hour and per GB**.
- **If** you need to block one malicious IP range, **then** add a **deny rule** to the subnet's **network access control list (NACL)**. **This works because** NACLs support both **allow and deny** rules, checked in **rule-number order** (first match wins), while **security groups (SGs)** can only **allow**.
- **If** a database should accept traffic only from the app tier, **then** add an inbound rule on the database's **security group (SG)** that names the **app tier's SG** as the source (for example on port **5432**), not IP ranges. **This works because** the rule follows SG membership: any new app server with that SG is allowed automatically, so you never manage IP lists as the app scales.
- **If** return traffic fails after you add **network access control list (NACL)** rules, **then** also allow the **ephemeral ports 1024–65535** in the other direction (outbound and inbound). **This works because** NACLs are **stateless**: they do not remember a connection, so reply traffic needs its own allow rule. **Security groups (SGs)** are stateful and allow replies automatically.
- **If** an **AWS Glue** job running in a VPC cannot reach **Amazon S3**, **then** add an **S3 gateway endpoint** (or a **NAT gateway**) and give the job a **security group (SG)** with a **self-referencing inbound rule (all TCP)** (verify). A **Glue network connection** puts the job's **elastic network interfaces (ENIs)** in your subnet, and those ENIs have **no internet path**. **This works because** the gateway endpoint gives a private, cheap route to S3, and the self-referencing rule lets the job's ENIs talk to each other. Without internet, the job also needs endpoints or NAT for Glue, CloudWatch, **AWS Security Token Service (STS)** and **AWS Key Management Service (KMS)**.
- **If** you suspect something is blocking a connection, **then** run **Reachability Analyzer**, which analyzes the path between a source and a destination. **This works because** it shows the exact **blocking component**, such as a missing route, a **security group (SG)** or a **network access control list (NACL)** rule, so you do not check each one by hand.
- **If** you need to know who talks to what and which traffic is rejected, **then** send **VPC Flow Logs** to **Amazon S3** and query them with **Amazon Athena**. Flow Logs capture **IP traffic metadata** (not the payload) at VPC, subnet or network-interface level. **This works because** each record has source and destination IP and port, bytes, and an **action** of **ACCEPT** or **REJECT**. Storing them as **Parquet** reduces Athena scan cost. Some traffic, such as Amazon DNS and instance metadata, is not captured (verify).
- **If** your VPC's IP ranges (CIDR blocks) overlap with on-premises networks, **then** re-plan the addresses, or connect through a **private NAT gateway** (private-to-private translation) (verify) or **AWS PrivateLink**. **This works because** VPC peering, **Transit Gateway (TGW)** and VPN **cannot route overlapping ranges**, while PrivateLink exposes only one service through an endpoint and does not route whole networks. Plan CIDRs early to avoid this.
- **If** the VPC runs out of IP addresses, **then** **add a secondary IPv4 CIDR block** and create new subnets in it. **This works because** a VPC can have **up to 5 IPv4 CIDR blocks** by default (up to **50** on request). The **primary block cannot be changed**, but secondary blocks can be added or removed.

Verified from AWS docs on 2026-11-09 (Amazon VPC quotas page, PrivateLink concepts).
Unconfirmed (verify): SG tracked-connection nuance; flow-log exclusions; private NAT details; BPA behaviour; default values not on the fetched quota page; Glue self-referencing rule specifics; EMR VPC endpoint availability.

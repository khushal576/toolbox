# Amazon VPC and PrivateLink – 3. Hybrid connectivity: Site-to-Site VPN, Direct Connect, Client VPN and Cloud WAN

Short notes. Each point is a fact you can be asked about.

## A. Choosing a hybrid link
| Need | Option | Notes |
|---|---|---|
| Quick, encrypted, internet-based link | **Site-to-Site VPN** | Up to 1.25 Gbps per tunnel; ready in minutes |
| Consistent latency, high bandwidth, private | **AWS Direct Connect (DX)** | Weeks to provision; 50 Mbps–400 Gbps |
| Encrypted + private | **VPN over DX** (public VIF or TGW transit VIF) or **MACsec** on dedicated DX | |
| Remote users | **AWS Client VPN** | OpenVPN-based, per-user |
| Global WAN | **AWS Cloud WAN** | Managed global network policy |
| Resilience | **DX + VPN backup**, or two DX at different locations | |
- DEA-C01 touchpoints: moving data from on-premises to AWS (DataSync/DMS/Transfer over DX or VPN), network choices for migration speed and security.

## B. AWS Site-to-Site VPN
- Connects your **customer gateway (CGW)** device to AWS via **IPsec** over the internet.
- **AWS side**: **virtual private gateway (VGW)** (one VPC) or **Transit Gateway** (many VPCs; supports ECMP) or **Cloud WAN**.
- **Each VPN connection has 2 tunnels** (two AWS endpoints in different AZs) for redundancy; configure both on your device.
- **Throughput**: **up to 1.25 Gbps per tunnel**; **ECMP** across tunnels/connections with TGW (dynamic routing only) to scale; VGW doesn't support ECMP.
- **Routing**: **static** or **dynamic (BGP)**. BGP preferred for failover and route propagation.
- **Features**: **IKEv2** (and IKEv1), AES-256, SHA-2, DH groups, **NAT-T**, **dead peer detection**, **accelerated VPN** (via Global Accelerator, TGW only), **private IP VPN** over Direct Connect, **IPv6 inside tunnels** **(verify)**.
- **MTU** for VPN: 1,500 (TGW), lower for some paths; clamp MSS (~1,379).
- **Cost**: about **$0.05 per VPN connection-hour** plus data transfer out; TGW attachment fees if used.
- **Monitoring**: CloudWatch `TunnelState`, `TunnelDataIn/Out`, logs of tunnel activity (VPN logs to CloudWatch).
- **Limits**: 10 VPN connections per VGW; 50 per TGW? (higher) **(verify)**; 100 routes via BGP from CGW per tunnel (VGW) **(verify)**.
- Use for: quick DMS/DataSync links, backup path for DX, small sites.

## C. AWS Direct Connect
- **Direct Connect** is a **dedicated private network connection** from your data center/colocation to AWS through a **DX location**.
- **Connection types**:
  - **Dedicated connection**: physical port **1, 10, 100, 400 Gbps**, ordered from AWS; you cross-connect at the DX location.
  - **Hosted connection**: sub-1G to 25 Gbps (50 Mbps – 25 Gbps), provisioned by an **AWS Direct Connect Partner**.
- **Virtual interfaces (VIFs)** run on a connection (802.1Q VLANs + BGP):
  - **Private VIF**: access **VPC resources** via a VGW or **Direct Connect gateway** (private IPs).
  - **Public VIF**: access **AWS public services** (S3, DynamoDB, etc.) with public IPs over the DX (no internet).
  - **Transit VIF**: connect to **Transit Gateway(s)** via a **Direct Connect gateway** (hybrid hub-and-spoke).
- **Direct Connect gateway (DXGW)**: a global resource connecting a DX private/transit VIF to **VGWs or TGWs in multiple Regions/accounts**; **no VPC-to-VPC transit through DXGW**.
- **Link Aggregation Group (LAG)**: bundle up to **4** same-speed ports into one logical link (active/active).
- **Resiliency models**: **Maximum resiliency** (separate connections at ≥2 DX locations with separate devices), **High resiliency** (≥2 locations), **Development** (single). AWS recommends **two connections at two locations**.
- **MACsec** (IEEE 802.1AE) encryption on 10/100/400 Gbps dedicated connections (layer 2).
- **IPsec VPN over DX** (public VIF or private IP VPN) for L3 encryption.
- **SiteLink**: connect two on-premises sites over the AWS backbone via DX locations **(verify)**.
- **BGP**: ASN, MD5 auth, communities to influence path and scope; **BFD** for fast failover.
- **Jumbo frames**: MTU 9001 on private VIF/transit VIF (8500 TGW), 1500 on public VIF.
- **Provisioning time**: weeks (cross-connect, LOA-CFA); not instant. Hosted connections faster.
- **Cost**: **port-hours** (by speed) + **data transfer out** at a lower rate than internet egress; data transfer **in is free**.
- **Latency**: more consistent than internet; no encryption by default.
- **Bandwidth and migration math**: 1 Gbps ≈ 10.8 TB/day theoretical (~7–8 TB/day realistic).
- **Use for**: large/continuous transfers (DMS CDC, DataSync, Redshift COPY from on-prem staging, Kafka mirror), predictable performance, compliance requiring private links.

## D. Transit Gateway with VPN/DX
- **TGW VPN attachment**: Site-to-Site VPN directly to TGW; supports **ECMP** and accelerated VPN.
- **TGW + DXGW**: transit VIF to DXGW associated with up to **6 TGWs per DXGW**; **20 DXGWs per TGW** (quota page); bandwidth up to 100 Gbps per AZ burst.
- Route advertisement limits: 200 prefixes from AWS to on-prem via DXGW → TGW; summarize routes **(verify)**.
- **Inspection/egress** hubs for hybrid traffic.

## E. AWS Client VPN
- **Managed OpenVPN-based client VPN** for remote users to reach VPCs and on-prem.
- **Authentication**: **Active Directory** (AWS Managed Microsoft AD / AD Connector), **mutual certificate** (ACM), **SAML 2.0 federated** (IAM Identity Center/Okta), combinations.
- **Authorization rules** (by AD group or SAML group) and **security groups** control access; split-tunnel or full-tunnel; logging to CloudWatch Logs.
- Billed by **endpoint association-hours** and **active connection-hours**.
- Used to reach **private web servers (MWAA UI, Grafana, OpenSearch Dashboards, bastion-free DB access)**.
- Alternatives: **AWS Verified Access** (zero trust per-app access without VPN), **SSM Session Manager** (shell/port forwarding without opening ports), **EC2 Instance Connect Endpoint**.

## F. AWS Cloud WAN and Network Manager (brief)
- **Cloud WAN**: build a **global network** with a **core network policy** (segments, attachments from VPC, VPN, TGW, SD-WAN); automates routing across Regions.
- **Network Manager**: global view/monitoring of TGWs, VPNs, DX, SD-WAN devices (topology, events, route analyzer).
- Mentioned for completeness; core for network architects, lighter for DEA-C01.

## G. Hybrid DNS
- **Route 53 Resolver endpoints**: **inbound** (on-prem → resolve AWS private zones/endpoint names) and **outbound** (VPC → on-prem DNS via **forwarding rules**).
- **Conditional forwarding** needed so on-prem resolves interface endpoint private DNS names.
- **Private hosted zones** associated with VPCs; split-horizon DNS.
- (See Route 53 notes.)

## H. Data movement over hybrid links (patterns)
- **DataSync** agent → DX/VPN → S3/EFS (uses a **DataSync VPC endpoint** for private path).
- **DMS** replication instance in VPC with VPN/DX to on-prem sources.
- **Transfer Family** SFTP endpoint in VPC (internal) reachable over DX/VPN.
- **S3 access from on-prem** via **public VIF** or **interface endpoint over private VIF**.
- **Kafka (MSK) multi-VPC / on-prem MirrorMaker** over DX.
- **Redshift/RDS** access by BI tools on-prem via private IPs through TGW/DX.
- **Snow Family** when bandwidth/time is insufficient (device shipping).
- Throughput estimate: size ÷ effective bandwidth; add 20–30% overhead.

## I. Monitoring and troubleshooting
- **VPN tunnel down** → mismatched IKE/IPsec parameters, CGW NAT/firewall blocking UDP 500/4500, wrong peer IP, DPD timeout, BGP session down.
- **VPN asymmetric routing** → route preference (BGP AS path, MED), static vs dynamic precedence; TGW ECMP requires dynamic.
- **DX BGP down** → VLAN/ASN/IP mismatch, MD5 key, cross-connect not established, LOA expiry.
- **DX path not preferred** → local preference communities, route precedence: DX is preferred over VPN for the same prefix on VGW (longest prefix first).
- **Can't reach VPC from on-prem** → missing route propagation, SG/NACL, on-prem firewall, overlapping CIDRs.
- **High latency/loss** → internet path (VPN), saturated link, MTU/MSS problems (fragmentation).
- **Client VPN access denied** → authorization rule/group mismatch, SG, certificate or SAML issues, DNS.
- **Metrics**: `AWS/DX` `ConnectionState`, `ConnectionBpsEgress/Ingress`, `ConnectionLightLevelTx/Rx`, `ConnectionCRCErrorCount`; `AWS/VPN` `TunnelState`, `TunnelDataIn/Out`.

## J. Limits and numbers
| Item | Value |
|---|---|
| VPN tunnels per connection | **2** |
| VPN throughput per tunnel | up to **1.25 Gbps** |
| DX dedicated speeds | **1 / 10 / 100 / 400 Gbps** |
| DX hosted speeds | **50 Mbps – 25 Gbps** |
| LAG members | up to **4** |
| TGW per DXGW | **6**; DXGW per TGW **20** |
| TGW MTU | 8500 (VPN 1500) |
| Client VPN | per association/connection billing |
| DX data transfer in | free |

## K. Exam skills mapping
- **2.1.4 Integrate migration tools (Transfer Family)**: migration tools over VPN/DX.
- **1.1.2 Read data from batch sources (S3, Glue, EMR, DMS, Redshift, Lambda, AppFlow)**: batch ingestion over hybrid links.

## L. Scenarios: "If X → Y, because Z"
- **If** you need a network link up this week for a data migration, **then** use **AWS Site-to-Site VPN**, an encrypted **IPsec** tunnel over the internet between your **customer gateway** device and AWS. **This works because** a VPN is ready in **minutes**, while **AWS Direct Connect (DX)** takes **weeks** to provision. Each tunnel carries up to **1.25 Gbps**.
- **If** continuous replication needs consistent high throughput, **then** use **AWS Direct Connect (DX)**, a dedicated private connection to AWS, with **two connections at two DX locations**. **This works because** DX does not use the internet, so bandwidth and latency are **predictable**, with speeds from **50 Mbps to 400 Gbps**. Two locations is what AWS recommends for resilience. The catch: provisioning takes **weeks**, and DX is **not encrypted** by default.
- **If** traffic over **AWS Direct Connect (DX)** must be encrypted, **then** use **MACsec** (layer-2 encryption on **10/100/400 Gbps** dedicated connections) or run an **IPsec VPN over DX**. **This works because** DX is private but **unencrypted by default**; MACsec or IPsec adds the encryption.
- **If** a **Site-to-Site VPN** needs more than **1.25 Gbps**, **then** attach it to **AWS Transit Gateway (TGW)** and use several tunnels with **Equal-Cost Multi-Path (ECMP)** and **dynamic Border Gateway Protocol (BGP)** routing. **This works because** each tunnel is **capped at 1.25 Gbps**, and ECMP spreads traffic across tunnels. A **virtual private gateway (VGW)** does **not** support ECMP, and ECMP does not work with static routing.
- **If** many VPCs in several Regions need on-premises access, **then** use a **Direct Connect gateway (DXGW)** with a **transit virtual interface (transit VIF)** to **Transit Gateways (TGWs)** in each Region. **This works because** a DXGW is a **global** resource that connects one DX link to TGWs in **multiple Regions and accounts** (up to **6 TGWs per DXGW**), and each TGW is a hub for many VPCs. A DXGW does **not** carry VPC-to-VPC traffic.
- **If** remote analysts need the **Amazon Managed Workflows for Apache Airflow (MWAA)** or **OpenSearch Dashboards** UI in private subnets, **then** give them **AWS Client VPN** (a managed, OpenVPN-based VPN per user), or **AWS Verified Access** or **SSM Session Manager port forwarding**. **This works because** users reach the private UI with **no public exposure**. Client VPN controls access with **authorization rules** and security groups; Verified Access gives zero-trust per-app access without a VPN.
- **If** on-premises systems must call **Amazon S3** privately, **then** use a **Direct Connect public virtual interface (public VIF)**, which reaches AWS public services over DX without the internet, or an **S3 interface endpoint** over a **private VIF**. **This works because** **gateway endpoints** work **only inside the VPC** and cannot be reached from on-premises. On-premises DNS needs **conditional forwarding** to resolve the interface endpoint's private names.
- **If** the **AWS Direct Connect (DX)** link fails, **then** keep a **Site-to-Site VPN** as a **backup path** with **lower preference**. **This works because** **Border Gateway Protocol (BGP)** fails over to the VPN path when the DX routes go away. On a **virtual private gateway (VGW)**, DX is preferred over VPN for the same prefix, so traffic uses DX while it is up.

Verified from AWS docs on 2026-11-09 (Transit Gateway quotas, VPC quotas additional resource pointers).
Unconfirmed (verify): VPN features (IPv6, accelerated), limits per VGW/TGW; DX speeds and SiteLink; Cloud WAN details; Client VPN billing; prefix-advertisement limits; BFD/MACsec scope.

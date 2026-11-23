# Amazon VPC and PrivateLink – 2. VPC peering, Transit Gateway, VPC endpoints and PrivateLink

Short notes. Each point is a fact you can be asked about.

## A. VPC-to-VPC connectivity options
| Option | Best for | Transitive? | Overlapping CIDRs? | Scale | Cost |
|---|---|---|---|---|---|
| **VPC peering** | A few VPCs, simple, low latency | **No** | **No** | 125 peerings per VPC (default 50) | No hourly fee; data transfer (cross-AZ/Region) |
| **Transit Gateway (TGW)** | Many VPCs/on-prem, hub-and-spoke | **Yes** (via route tables) | No | 5,000 attachments | Per attachment-hour + per GB processed |
| **PrivateLink (interface endpoints)** | Expose **one service** to many VPCs | n/a (not routed) | **Yes** | high | Per endpoint-hour + per GB |
| **VPC Lattice** | Service-to-service app networking with auth | n/a | Yes | high | per service/request/GB |
| **Cloud WAN** | Global managed network | Yes | No | large | per attachment/core network |
- **Rule of thumb**: few VPCs → **peering**; many VPCs/hybrid → **TGW**; expose a service without full network access or with overlapping CIDRs → **PrivateLink**.

## B. VPC peering
- A **peering connection** is a 1:1 private link between two VPCs (same or different account/Region). Traffic stays on the AWS backbone, **no IGW/VPN/NAT** needed.
- **Setup**: requester → accepter accepts → **add routes on both sides** → update SGs/NACLs (can reference peer SG by ID for same-Region peering).
- **Limits/rules**: **no overlapping CIDRs**; **no transitive routing** (A↔B and B↔C does not give A↔C); **no edge-to-edge routing** (can't use peer's IGW, NAT, VPN, or gateway endpoints); inter-Region peering traffic is encrypted and doesn't use the public internet; MTU 9001 intra-Region (8500 inter-Region).
- **DNS resolution** across peering: enable "DNS resolution from accepter/requester VPC".
- **Cost**: no hourly fee; data transfer between AZs/Regions charged.
- Data example: EMR/Glue in VPC A reading RDS in VPC B via peering with SG rules.

## C. AWS Transit Gateway
- **Transit Gateway** is a Regional **network hub** connecting **VPCs, VPNs, Direct Connect gateways, other TGWs (peering), Connect (SD-WAN) attachments**.
- **Attachments**: up to **5,000 per TGW**; one attachment per VPC per TGW; a VPC attachment requires choosing **one subnet per AZ** (ENIs created).
- **Route tables**: up to **20 per TGW** (adjustable); each attachment is **associated** with one route table and can **propagate** its routes to one or more route tables; **static routes** also supported. Use separate tables for **isolation** (prod/dev, shared services).
- **Total routes** across tables: 10,000.
- **Bandwidth**: up to 100 Gbps per VPC attachment per AZ (burst) **(per quota page)**; VPN tunnels 1.25 Gbps each, **ECMP** over multiple tunnels for more (dynamic BGP VPN only).
- **MTU**: 8500 bytes for VPC/Direct Connect/peering; **1500 for VPN**.
- **Inter-Region peering** between TGWs (encrypted, uses AWS backbone); static routes only.
- **Multicast** support, **appliance mode** (keeps flow symmetry through an inspection VPC), **Network Manager** (global network visibility).
- **Cost**: per **attachment-hour** (about $0.05) and per **GB processed** (about $0.02) **(verify)**; peering adds data transfer.
- **TGW vs peering**: TGW adds hourly + per GB cost but simplifies routing and gives transitivity; peering is cheaper for few VPCs.
- **Centralized egress/inspection** architecture: spoke VPCs → TGW → egress VPC with NAT + Network Firewall.
- **Sharing**: share TGW across accounts with **AWS RAM** (organization).

## D. VPC endpoints (the exam core)
- A **VPC endpoint** lets resources in your VPC reach AWS services/PrivateLink services **privately** without IGW, NAT, VPN or public IPs.
- **Gateway endpoints** (only **S3** and **DynamoDB**):
  - Implemented as **route table entries** with a **prefix list** target (`pl-xxxx`).
  - **Free** (no hourly or data charge).
  - Work only within the **same Region**, **not accessible from on-premises or peered VPCs / TGW** (use interface endpoints or proxies for that).
  - Controlled by **endpoint policies** (restrict buckets/actions) and S3 bucket policies (`aws:SourceVpce`).
- **Interface endpoints** (AWS PrivateLink; most services, plus partner/own services):
  - Create **ENIs** with private IPs in your subnets (one per chosen AZ); DNS names resolve to them.
  - **Private DNS** (`enableDnsSupport` + `enableDnsHostnames` + "Enable private DNS name") overrides the public service hostname (for example `glue.us-east-1.amazonaws.com`) to resolve to the endpoint IPs inside the VPC.
  - Billed **per endpoint per AZ-hour (about $0.01)** plus **per GB (about $0.01 first PB)** **(verify)**.
  - Reachable from **on-premises** over VPN/Direct Connect and from peered/TGW-connected VPCs (using the endpoint's DNS names / Route 53 Resolver rules).
  - Have **security groups** (allow 443 from clients) and **endpoint policies**.
  - Support **IPv4, IPv6 or dual-stack** depending on service.
  - **S3 interface endpoint** exists too (for on-premises/other-VPC access); it can coexist with the gateway endpoint (use gateway for in-VPC, interface for hybrid).
- **Gateway Load Balancer endpoints**: route traffic to third-party virtual appliances (firewalls) transparently.
- **Resource endpoints** and **service-network endpoints** (VPC Lattice / resource configurations): access a specific resource (DB, IP, DNS target) or service network across VPCs without a load balancer.
- **Endpoint services (PrivateLink provider side)**: you expose your service behind an **NLB** (or GWLB) as an endpoint service; consumers create interface endpoints; provider accepts/rejects connections and sets allowed principals.
- **Endpoint policy**: IAM resource policy on the endpoint; default **allow all**. Use to restrict principals/resources/actions (for example only my data lake buckets via `aws:ResourceOrgID`/bucket ARNs).
- **Data perimeter**: combine **endpoint policies** (trusted resources), **bucket policies** with `aws:SourceVpce` / `aws:SourceVpc` (expected networks), and **SCP/RCP** (trusted identities).
- **Cross-Region PrivateLink** (consumer in another Region) is supported for endpoint services **(verify scope)**.
- **Quotas**: interface endpoints per VPC 50 (default), gateway endpoints per VPC 20 **(verify)**, bandwidth per endpoint ENI scales up to 100 Gbps.

## E. Interface vs gateway endpoint for S3 (exam favourite)
| Feature | Gateway endpoint | Interface endpoint |
|---|---|---|
| Services | S3, DynamoDB | S3 and ~all other services |
| Mechanism | Route table prefix list | ENI + private DNS |
| Cost | **Free** | Hourly + per GB |
| On-premises access | **No** | **Yes** |
| Peered VPC / TGW access | **No** | **Yes** |
| Cross-Region | No | S3 interface supports some cross-Region patterns **(verify)** |
| Use for | In-VPC workloads to S3/DynamoDB | Hybrid, other-VPC, other services |
- **Common exam answer**: "reduce NAT gateway cost for S3 traffic" → **S3 gateway endpoint**.
- "Private access to S3 from on-premises" → **S3 interface endpoint (PrivateLink)** over Direct Connect/VPN.

## F. Endpoints needed for data workloads (private subnets, no NAT)
| Workload | Typical endpoints |
|---|---|
| **Glue jobs** | S3 (gateway), Glue (interface), CloudWatch Logs, STS, KMS (if CMK), Secrets Manager, Glue DataBrew? |
| **Lambda in VPC** | S3/DynamoDB gateway, plus interface endpoints for each API called (SQS, SNS, Kinesis, Secrets Manager, STS, KMS) |
| **EMR** | S3 gateway, STS, EMR, KMS, Glue, Secrets Manager, CloudWatch Logs |
| **Redshift** (enhanced VPC routing) | S3 gateway, Glue, KMS, STS, Lake Formation/Redshift data API as needed |
| **MWAA** (private routing) | S3, SQS, Logs, Monitoring, ECR (api/dkr), KMS, Airflow endpoints |
| **Step Functions callers in VPC** | `states` / `sync-states` interface endpoint |
| **Athena/QuickSight private access** | `athena`, `glue`, S3, Lake Formation, QuickSight VPC connections |
| **SageMaker** | `sagemaker.api`, `sagemaker.runtime`, S3, ECR, STS, Logs |
| **Kinesis/Firehose producers** | `kinesis-streams`, `firehose` |
| **Secrets/KMS/SSM** | `secretsmanager`, `kms`, `ssm`, `ec2messages`, `ssmmessages` |
- **Missing endpoint symptoms**: timeouts to the service hostname; private DNS not enabled; SG blocks 443; endpoint policy denies.

## G. PrivateLink for your own services (provider/consumer)
- Provider: service behind **NLB** (or GWLB) in provider VPC → **create endpoint service** → set **allowed principals** (accounts/roles/Org) → choose auto-accept or manual accept → optionally **private DNS name** (needs domain verification).
- Consumer: create **interface endpoint** to the service name (`com.amazonaws.vpce.<region>.vpce-svc-…`) → pick subnets/SG → use endpoint DNS name or private DNS.
- **Benefits**: no peering/TGW, **overlapping CIDRs OK**, only the service is exposed (not the whole network), one-way (consumer → provider), scalable to thousands of consumers.
- **Use cases**: SaaS vendors exposing APIs; internal shared services (data platform APIs, Kafka via MSK multi-VPC); **Snowflake/Databricks/AppFlow private connectivity**.
- **Cost**: provider pays NLB; consumer pays endpoint hours and data processing.

## H. Troubleshooting connectivity
- **Peering routes missing** → add routes in both route tables and update SGs; DNS resolution option off.
- **TGW no connectivity** → route table association/propagation missing, subnet route to TGW missing in VPC route table, SG/NACL blocking, overlapping CIDRs, appliance mode needed for stateful inspection.
- **Gateway endpoint not used** → route not added to the subnet's route table, bucket in a different Region, endpoint policy denies.
- **Interface endpoint DNS still resolves public IPs** → private DNS disabled, `enableDnsHostnames` off, custom DNS not forwarding to the VPC resolver.
- **On-prem cannot reach endpoint** → no route over VPN/DX to endpoint ENIs, on-prem DNS lacks conditional forwarders to Route 53 Resolver inbound endpoint.
- **PrivateLink connection pending** → provider has not accepted; principal not allowed.
- **Throughput issues through NAT** → many small requests; move S3/DynamoDB traffic to gateway endpoints.

## I. Exam skills mapping
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: S3 access points, PrivateLink, endpoint policies.
- **1.1.1 Read data from streaming sources (Kinesis, MSK, DynamoDB Streams, DMS, Glue, Redshift)**: private streaming ingestion paths.

## J. Scenarios: "If X → Y, because Z"
- If EMR in private subnets reads S3 and NAT cost is high → **S3 gateway endpoint**, because gateway endpoints are free and avoid NAT data processing.
- If on-premises ETL must call S3 without the internet → **S3 interface endpoint over Direct Connect/VPN**, because gateway endpoints are not reachable from on-prem.
- If 30 VPCs and on-prem must communicate → **Transit Gateway**, because peering isn't transitive and doesn't scale.
- If two partner VPCs have overlapping CIDRs but need one API → **PrivateLink**, because it doesn't route networks.
- If you must restrict a bucket to your network only → **bucket policy Deny when `aws:SourceVpce` isn't your endpoint** (plus endpoint policy), because it blocks other paths.
- If a vendor needs to reach your internal service privately → **expose via NLB endpoint service**, because only the service is exposed.
- If an inspection firewall must see all traffic → **TGW + inspection VPC with appliance mode (or GWLB endpoints)**, because it keeps flows symmetric.
- If a Lambda in a VPC loses internet access → **add NAT or interface/gateway endpoints**, because VPC Lambdas lose default internet.

Verified from AWS docs on 2026-11-09 (Amazon VPC quotas, Transit Gateway quotas, PrivateLink concepts).
Unconfirmed (verify): endpoint and peering default counts; hourly/GB prices; cross-Region PrivateLink scope; S3 interface endpoint cross-Region patterns; EMR/Glue endpoint list; TGW appliance-mode details.

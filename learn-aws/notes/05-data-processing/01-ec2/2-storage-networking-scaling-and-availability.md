# EC2 – 2. Storage, networking, scaling and availability

Short notes. Each point is a fact you can be asked about.

## A. Storage options seen from the instance
- **EBS** (Elastic Block Store) = network disk in **one AZ**. It survives stop/start. You can detach it and attach it to another instance in the same AZ. You can snapshot it to S3-backed storage.
- **Instance store** = NVMe or SSD/HDD disks **physically on the host**. Very fast, included in the instance price, **temporary**.
- **EFS** = shared NFS file system across many instances and AZs (Linux).
- **FSx** = managed file systems (Lustre for HPC/ML scratch on S3, Windows File Server, NetApp ONTAP, OpenZFS).
- **S3** = object storage. Read and write from EC2 with the SDK/CLI using an IAM role. It is not a mounted disk by default (Mountpoint for Amazon S3 can mount a bucket read-mostly).
- **Root volume** = the disk the OS boots from. It is EBS for almost all current AMIs. Instance-store-backed AMIs exist only for older Linux uses.
- **EBS-backed instance** can stop/start and hibernate. **Instance-store-backed instance** can only reboot or terminate.

## B. EBS from the EC2 point of view (short summary)
- Volume types:
  - **gp3**: general purpose SSD and the default choice. Baseline 3,000 IOPS / 125 MiB/s, raise IOPS and throughput separately from size.
  - **gp2**: older SSD; IOPS tied to size.
  - **io2 Block Express / io1**: provisioned IOPS SSD for databases, sub-millisecond latency. Multi-Attach only on io1/io2.
  - **st1**: throughput HDD for big sequential reads (logs, Kafka, data warehouse).
  - **sc1**: cold HDD, cheapest.
- HDD volumes (st1, sc1) **cannot be boot volumes**.
- A volume and its instance must be in the **same AZ**. To move a volume to another AZ: snapshot → create a volume from the snapshot in the new AZ.
- Snapshots are **incremental** and **Regional**. They can be copied to other Regions and shared with other accounts.
- **DeleteOnTermination**: default **true for the root volume**, **false for extra volumes** attached later or at launch (verify for volumes added in the launch wizard). Change it if you need the root disk after terminate.
- **EBS-optimized**: dedicated bandwidth between instance and EBS. It is on by default on current-generation types at no extra cost. Some older types needed it turned on for an hourly fee.
- An instance's EBS bandwidth has a cap. Total disk performance = the **lower** of (sum of volume limits) and (instance EBS limit). A huge io2 volume on a small instance is limited by the instance.
- Smaller sizes of many families can hit **max EBS bandwidth for only 30 minutes per 24 hours**, then fall back to a baseline. Larger sizes sustain the max.
- **EBS encryption** uses KMS. Encrypting the root volume is required for hibernation. **EBS encryption by default** is a per-Region account setting.
- You cannot directly encrypt an existing unencrypted volume. Snapshot → copy with encryption → create volume → swap.
- **Elastic Volumes**: grow size or change type/IOPS while attached. Then extend the file system inside the OS. Shrinking is not supported.
- **Attached EBS status check** (Nitro only) fails if a volume cannot complete I/O. ASGs can replace instances on this check.

## C. Instance store details
- Comes only with certain types: the `d` option (`m7gd`, `c6id`, `r8gd`), storage optimized `I`, `Im`, `Is`, `D` families.
- Attached **only at launch**. You cannot attach, detach or move it later.
- Data **persists through reboot**, and through a power failure (on reboot).
- Data is **lost** on stop, hibernate, terminate, instance type change, host retirement, simplified or CloudWatch recovery, and on disk failure.
- On stop/hibernate/terminate every block is **cryptographically erased**. NVMe instance store data is encrypted at rest with hardware keys (verify wording).
- Not included in an EBS-backed AMI or in EBS snapshots. You cannot snapshot instance store.
- No extra charge. It is part of the instance price.
- Best for: buffers, caches, Spark shuffle and spill, HDFS on replicated clusters, Kafka/Cassandra with replication, scratch for ETL temp files.
- Rule: use instance store only when the data can be rebuilt or is replicated elsewhere.
- New NVMe instance store volumes can show slower first-write performance on some older types. Initialize (pre-write) them if needed (verify which types).

## D. AMIs (images) in more depth
- Create an AMI from an EBS-backed instance → EC2 snapshots each EBS volume and registers an AMI that points to them.
- By default EC2 **reboots** the instance before creating the AMI for file system consistency. "No reboot" is faster but risks an inconsistent image.
- An AMI is **Regional**. To launch in another Region: **copy** the AMI to that Region (copy runs in the destination Region).
- An AMI copy does **not** copy launch permissions or S3 bucket permissions. Copied user tags are optional. System tags are not copied.
- You can **encrypt** or re-encrypt snapshots during AMI copy (choose a KMS key in the destination Region).
- **Time-based copy**: set a completion window from 15 minutes to 48 hours for an extra charge. Otherwise the copy is best effort and free (you pay storage).
- **Sharing**: share with specific account IDs, Organizations or OUs, or make it public. Shared users can launch but cannot modify or delete it.
- Encrypted AMIs can be shared only if their snapshots use a **customer managed KMS key**. You must also grant the other account use of that key. AMIs encrypted with the default **`aws/ebs` key cannot be shared**.
- **Block public access for AMIs** is an account setting that stops AMIs being made public. It is on by default for new accounts (verify).
- AMI lifecycle features: **deprecate** (hide from new launches after a date), **disable** (cannot be used to launch), **deregister** (delete; snapshots remain and still cost money until deleted).
- **Recycle Bin** can protect deregistered AMIs and deleted snapshots for a retention period.
- **EC2 Image Builder** = managed pipeline that builds, tests and patches "golden" AMIs (and container images) on a schedule, then distributes them across Regions/accounts.
- **Golden AMI** pattern: bake software into the AMI so instances boot fast. Pass only small runtime config through user data. This is faster than installing everything at boot.

## E. Networking basics for an instance
- Every instance has a **primary network interface (ENI)** in one subnet, which sets its AZ. It has one primary private IPv4 address.
- **ENI** (Elastic Network Interface): virtual network card with private IPs, optional public IP or Elastic IP, security groups, a MAC address and a source/destination check flag.
- You can attach **secondary ENIs** (same AZ, can be in other subnets of the same VPC). Moving a secondary ENI to a standby instance is a classic quick-failover trick.
- The number of ENIs and IPs per ENI depends on the instance type.
- **Private IP**: kept through stop/start; released on terminate.
- **Auto-assigned public IPv4**: comes from Amazon's pool. It **changes on stop/start** and is released on terminate. It cannot be moved.
- **Elastic IP (EIP)**: a static public IPv4 owned by your account. You can remap it to another instance or ENI. Default quota **5 per Region**.
- **All public IPv4 addresses are charged** per hour, both in-use EIPs and auto-assigned public IPs. Idle EIPs are charged too. Use IPv6, NAT or private endpoints to cut the count.
- **Public subnet** = route table has a route to an **internet gateway**. An instance needs a public IP plus that route to talk to the internet directly.
- **Private subnet** = no route to the internet gateway. Outbound internet goes through a **NAT gateway** in a public subnet.
- NAT gateway: managed, scales automatically, lives in **one AZ**. For high availability create one per AZ and route each private subnet to its own AZ's NAT.
- NAT gateway costs an **hourly fee plus a per-GB processing fee**. Heavy S3/DynamoDB traffic through NAT is a common hidden cost.
- **Gateway VPC endpoints** for **S3 and DynamoDB**: free, added as a route in route tables, same Region only. Traffic to S3 stays private and **skips the NAT gateway**.
- Gateway endpoints **cannot** be used from on-premises, from peered VPCs in other Regions, or through a transit gateway. Use **interface endpoints (PrivateLink)** for those (hourly + per-GB cost).
- **Interface endpoints** give private IPs (ENIs) in your subnets for most AWS services (SSM, Secrets Manager, KMS, CloudWatch Logs, STS, Glue, Kinesis…).
- With a VPC endpoint, S3 bucket policies use `aws:SourceVpce` or `aws:SourceVpc`, **not** `aws:SourceIp` (private addresses are seen). Use `aws:VpcSourceIp` for private IP ranges.
- **Endpoint policies** can limit which buckets or principals are reachable through the endpoint (for example, only company buckets, to block data exfiltration).
- **Source/destination check**: on by default. Turn it off only for NAT instances, firewalls or routers that forward traffic for others.
- DNS: instances get a private DNS name. With DNS hostnames enabled, public IPs also get a public DNS name that resolves to the private IP inside the VPC.
- The Route 53 Resolver limit is **1,024 packets per second per ENI** for DNS queries and cannot be raised. Heavy DNS lookups in big jobs can hit it (cache DNS locally).

## F. Network performance
- **Enhanced networking** uses SR-IOV for higher bandwidth, higher packets per second and lower latency at no extra cost.
- **ENA** (Elastic Network Adapter): up to 100 Gbps on supported types (some newer types go higher; verify). All Nitro instances use ENA. Older types use the Intel 82599 VF interface (up to 10 Gbps).
- **ENA Express** (SRD protocol): up to 25 Gbps **single-flow** between eligible instances in the **same AZ**, with lower tail latency.
- **EFA** (Elastic Fabric Adapter): ENA plus **OS-bypass** (Libfabric) for HPC (MPI) and ML (NCCL) between instances. Low and steady latency. No extra cost.
- EFA traffic **cannot cross AZs or VPCs and is not routable**. Normal IP traffic on the same EFA still routes.
- Bandwidth grows with instance size. Types with 16 vCPUs or fewer usually show "**up to** X Gbps". That is a **baseline plus burst** using network I/O credits (burst lasts about 5–60 minutes).
- **Single-flow** (one TCP/UDP 5-tuple) limit:
  - **5 Gbps** outside a cluster placement group.
  - **10 Gbps** inside a cluster placement group.
  - Up to 25 Gbps with ENA Express in the same AZ.
- Traffic through an **internet gateway** (or to on-premises over Direct Connect from a cluster group):
  - Instances with fewer than 32 vCPUs are limited to **5 Gbps**.
  - Larger instances get **50%** of their bandwidth.
- Traffic to **S3 in the same Region** (public endpoint or VPC endpoint) can use the full aggregate instance bandwidth. Use many parallel connections (multipart, many threads) because each flow is capped.
- Instance-level allowances can drop packets before bandwidth is reached: packets per second, connection tracking, link-local traffic. ENA driver stats (`bw_in_allowance_exceeded`, `pps_allowance_exceeded`) show this.
- The 1-minute or 5-minute CloudWatch metrics can miss **microbursts** that cause drops.

## G. Placement groups
- **Cluster**:
  - Packs instances close together in **one AZ** for the lowest latency and highest throughput between them.
  - Best for tightly coupled HPC, Spark shuffle-heavy jobs and ML training.
  - Risk: one rack or host failure can hit many instances. Capacity errors are more likely.
  - Launch all instances in **one request** with the **same instance type** to avoid capacity errors.
  - If a launch fails, stop and start all instances in the group and try again (they may move to hardware with room).
  - Not supported for burstable (T) instances, Mac1 or M7i-flex.
  - Can span peered VPCs in the same Region.
  - Reserve capacity there with an On-Demand Capacity Reservation (zonal RIs cannot).
- **Partition**:
  - Splits instances into logical **partitions**. Each partition sits on its own **racks** (own power and network).
  - Up to **7 partitions per AZ**. Can span AZs in a Region. Hundreds of instances, limited only by account limits.
  - Instances can see which partition they are in, so topology-aware apps (**HDFS, HBase, Cassandra, Kafka**) can place replicas in different partitions.
  - Dedicated Instances: maximum 2 partitions.
- **Spread**:
  - Each instance on **distinct hardware (rack)**.
  - Maximum **7 running instances per AZ per group**. Can span AZs (for example 21 instances over 3 AZs).
  - Good for a small number of critical instances: a primary/standby pair, ZooKeeper or quorum nodes, a few master nodes.
  - Host-level spread only on Outposts. Not supported for Dedicated Instances.
- Capacity Reservations do not reserve capacity in spread or partition groups. Capacity Blocks do not support placement groups.
- **Precision time placement group**: places instances on hardware with high-precision time (microsecond clock sync, PTP hardware clock). For distributed databases and financial timestamping. No extra charge.
- You can move a **stopped** instance into or out of a placement group (verify via CLI only).
- Exam cue: "lowest latency between nodes" → cluster. "HDFS/Kafka/Cassandra rack awareness" → partition. "Few critical instances must not fail together" → spread.

## H. Availability of a single instance
- One instance = one AZ = a single point of failure. **High availability needs multiple instances across AZs** behind a load balancer or with app-level replication.
- **Status checks** run every minute:
  - **System status check**: AWS hardware, host, power or network problem. Fix: wait for AWS, or **stop and start** (moves to a new host). Instance-store-backed: terminate and replace.
  - **Instance status check**: your OS or config problem (bad network config, out of memory, corrupt file system, wrong kernel). Fix it yourself: reboot or repair.
  - **Attached EBS status check** (Nitro): a volume cannot complete I/O. Fix: wait, replace the volume, or stop/start. ASG can replace on this.
  - **Application status check** (opt-in): HTTP/HTTPS check of your app path and response codes.
- CloudWatch metrics: `StatusCheckFailed_System`, `StatusCheckFailed_Instance`, `StatusCheckFailed_AttachedEBS`, `StatusCheckFailed` (any).
- **Simplified automatic recovery**:
  - **On by default** on supported instances. It acts when a **system** status check fails.
  - Not for metal sizes or instances with instance store at launch.
- **CloudWatch action-based recovery**:
  - You create an alarm on `StatusCheckFailed_System` with the "recover" action.
  - Supports some metal and instance-store types (instance store data is lost). Faster recovery and SNS notifications.
- Recovery **keeps**: instance ID, private, public and Elastic IPs, instance metadata, placement group, attached EBS volumes, AZ.
- Recovery **loses**: RAM contents and instance store data (CloudWatch action), and OS uptime resets.
- Recovery does **not** run for instance status check failures. Those are your problem. A CloudWatch alarm can **reboot** on instance check failure.
- **Scheduled events**: AWS posts planned reboots, stops or **instance retirement** (degraded hardware) in advance. Stop/start before the date to move hosts on your schedule.
- EBS-backed instances survive host loss with their data. Instance-store data does not.

## I. Auto Scaling groups (ASG)
- An **ASG** keeps a group of instances at a **desired capacity** between **min** and **max**. It replaces unhealthy instances and scales with demand.
- An ASG uses a **launch template** and spreads instances evenly over the chosen subnets/AZs. **AZ rebalancing** moves capacity back to balance after an AZ issue.
- An ASG is free. You pay for the instances (and CloudWatch alarms, load balancers).
- **Health checks**:
  - **EC2** status checks are always on.
  - Optional checks: **ELB**, **EBS** (attached EBS status), **VPC Lattice** and **custom** health.
  - An unhealthy instance is **terminated and replaced**. An ASG does not reboot or repair it.
- **Health check grace period**: default **300 s in the console**, **0 in CLI/SDK**. It stops new instances being killed before they finish booting. With launch lifecycle hooks you can use 0.
- If you **stop** an instance that is in an ASG, the ASG marks it unhealthy and replaces it. Use **standby** to take one out for maintenance.
- **Scaling types**:
  - **Manual**: change desired capacity yourself.
  - **Scheduled**: set capacity at known times (for example, add 20 instances at 01:00 for the nightly batch).
  - **Dynamic**, three kinds:
    - **Target tracking** (AWS recommended): keep a metric at a target, like a thermostat (CPU 50%, requests per target, SQS backlog per instance).
    - **Step scaling**: different adjustments for different alarm breach sizes.
    - **Simple scaling** (legacy): one adjustment, then wait for the **cooldown** (default 300 s). Avoid it.
  - **Predictive**: uses history to forecast daily/weekly cycles and launches capacity **before** load arrives. Good for regular patterns and slow-booting apps.
- **SQS-driven scaling**: scale workers on "backlog per instance" (`ApproximateNumberOfMessagesVisible` ÷ running instances) with target tracking. Classic for queue-based ETL workers.
- With several policies, the ASG picks the one that gives the **largest** capacity (for both scale-out and scale-in).
- **Default instance warmup**: how long until a new instance's metrics count toward the group metrics. Set it so scaling does not overshoot.
- **Lifecycle hooks**:
  - Pause an instance in **Pending:Wait** (launch) or **Terminating:Wait** (terminate) to run custom actions: install software, register with a cluster, **copy logs off before termination**, drain work.
  - Default timeout **1 hour**. Maximum **48 hours** or 100 × the heartbeat timeout, whichever is smaller.
  - The result is **CONTINUE** or **ABANDON**.
  - Notifications go through EventBridge (or SNS/SQS via API).
- **Warm pools**:
  - A pool of **pre-initialized** instances kept **Stopped** (cheapest), **Hibernated** or Running.
  - A scale-out pulls from the pool for fast starts.
  - Not supported with **Spot** in mixed groups or with instance weighting.
  - Root must be EBS for stopped/hibernated pools.
- **Mixed instances policy**:
  - One ASG with several instance types (or attribute-based selection) and both **On-Demand and Spot**.
  - Settings: **On-Demand base capacity** (first N instances On-Demand) and **percentage On-Demand above base**. The rest is Spot.
  - Spot allocation: **price-capacity-optimized** (recommended), capacity-optimized, capacity-optimized-prioritized, lowest-price (CLI only, not recommended).
  - On-Demand allocation: **lowest-price** or **prioritized** (use prioritized to hit types covered by RIs).
  - **Instance weighting**: one big instance can count as several capacity units.
- **Capacity Rebalancing**: when a Spot instance gets a rebalance recommendation, the ASG launches a replacement first, then terminates the at-risk one.
- **Instance refresh**: rolling replacement of instances to roll out a new AMI or launch template. Set minimum healthy %, checkpoints and skip-matching. Supports rollback.
- **Maximum instance lifetime**: replace instances older than N days (for example, forced re-patching).
- **Termination policy** (default): pick the AZ with the most instances, then terminate the instance whose launch template/config is oldest, then the one nearest the next billing hour (verify order details).
- **Scale-in protection**: protect specific instances (for example, ones running a long batch task) from scale-in.
- **Suspend processes** (Launch, Terminate, HealthCheck, ReplaceUnhealthy, AZRebalance…) for troubleshooting.

## J. Load balancers (only as they relate to EC2)
- **ALB** (Application, layer 7): HTTP/HTTPS, path/host routing, targets are instances, IPs, Lambda or containers. Health checks on an HTTP path.
- **NLB** (Network, layer 4): TCP/UDP/TLS, very high throughput and low latency, **static IP per AZ**, keeps the client source IP. Use it to give partners fixed IPs to **allowlist**.
- **GWLB** (Gateway): sends traffic through third-party virtual firewalls.
- Use **ELB health checks** in the ASG so the group replaces instances that are running but whose app is broken.
- Load balancers span AZs. Cross-zone load balancing is on by default for ALB, off by default for NLB (verify).
- **Connection draining (deregistration delay)** lets in-flight requests finish before an instance leaves.

## K. Backup and DR for EC2
- AWS does **not** back up instances for you.
- **AMI** = full-instance backup (all EBS volumes plus launch info). **EBS snapshot** = one volume.
- **AWS Backup**:
  - Central backup plans (schedule, retention, lifecycle to cold storage, cross-Region and cross-account copy) for EC2, EBS, RDS, EFS, DynamoDB and more.
  - For EC2 it creates AMIs with snapshots.
  - **Backup Vault Lock** gives WORM protection.
- **Data Lifecycle Manager (DLM)**: free, tag-based policies to create, copy and delete **EBS snapshots and EBS-backed AMIs** on a schedule.
- **Application-consistent** backups on Windows use VSS through AWS Backup. On Linux, pause writes or use pre/post scripts.
- DR patterns for EC2: copy AMIs and snapshots to another Region (backup/restore). Pilot light (small always-on core). Warm standby (scaled-down copy). Multi-site active/active.
- **AWS Elastic Disaster Recovery** replicates servers continuously to a low-cost staging area for fast recovery (minutes RTO, seconds RPO; verify).
- **AWS Backup** and **SCPs** can block copying backups to Regions that are not allowed (data sovereignty).

## Scenarios (if → then, because)
- If Spark shuffle needs the fastest local scratch disk and data can be rebuilt → instance types with NVMe instance store (`d`, `I`), because it is the fastest disk and free with the instance.
- If data must survive stop/start → EBS (or S3/EFS), never instance store.
- If an instance was stopped and now has a different public IP → auto-assigned public IPs change on stop/start. Use an Elastic IP or a DNS name / load balancer.
- If a partner must allowlist a fixed IP for your EC2-based API → Elastic IP on the instance, or an NLB with static or Elastic IPs per AZ.
- If a private-subnet ETL instance reads TBs from S3 and the NAT bill is huge → add an S3 **gateway endpoint**, because it is free and skips NAT processing fees.
- If on-premises servers must reach S3 privately over Direct Connect → S3 **interface endpoint**, because gateway endpoints cannot be used from outside the VPC.
- If an S3 bucket must accept requests only from your VPC → bucket policy with `aws:SourceVpce` or `aws:SourceVpc` plus a VPC endpoint.
- If tightly coupled HPC or distributed training needs lowest node-to-node latency → cluster placement group plus EFA, same instance type, one launch request.
- If a self-managed Kafka/HDFS/Cassandra cluster needs rack-aware replica placement → partition placement group.
- If three ZooKeeper nodes must never share hardware → spread placement group.
- If an EC2 launch in a cluster placement group fails with InsufficientInstanceCapacity → launch all at once with one type, stop/start the group, try another AZ, or reserve capacity with an ODCR in the group.
- If a single TCP copy to another instance tops out near 5 Gbps → single-flow limit. Use multiple streams, a cluster placement group (10 Gbps), or ENA Express (25 Gbps).
- If an instance fails the **system** status check → stop and start it (or rely on automatic recovery), because the host is at fault.
- If an instance fails the **instance** status check → fix the OS (memory, disk, network config). Reboot. AWS recovery will not help.
- If you need an instance to come back automatically with the same IP after a host failure → simplified automatic recovery (default) or a CloudWatch recover alarm, because recovery keeps IDs and IPs.
- If a web tier must survive an AZ outage → ASG across at least 2 AZs behind an ALB with ELB health checks.
- If a queue-processing ETL fleet must scale with work → ASG target tracking on SQS backlog per instance.
- If nightly batch load starts at the same time every day → scheduled scaling (or predictive scaling), because reactive scaling is too late.
- If new instances take 10 minutes to boot and miss traffic spikes → warm pool (stopped instances) or a baked golden AMI, plus predictive scaling.
- If logs on instances are lost when the ASG scales in → termination lifecycle hook to copy logs to S3, or stream logs continuously with the CloudWatch agent.
- If a mixed ASG must always keep 2 On-Demand instances and the rest cheap → On-Demand base capacity = 2, 0% On-Demand above base, Spot price-capacity-optimized.
- If you must roll a new AMI to 100 instances safely → ASG instance refresh with minimum healthy percentage and checkpoints.
- If ASG instances keep getting replaced right after launch → health check grace period too short or the ELB health check path is wrong.
- If you need the same AMI in another Region for DR → copy the AMI (and re-encrypt with a KMS key in that Region).
- If you need to share an encrypted AMI with another account → encrypt with a customer managed KMS key, share the AMI and grant the key. AMIs on `aws/ebs` cannot be shared.
- If you need automatic daily AMIs with 30-day retention and a cross-Region copy → AWS Backup plan (or DLM).
- If deregistered AMIs keep costing money → delete their snapshots too, because deregistering does not delete snapshots.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: instance store persistence table, EBS-optimized defaults and 30-minute burst footnote, AMI copy and sharing rules, enhanced networking (ENA, ENA Express, EFA limits), network bandwidth rules (single-flow, internet gateway limits, "up to" burst), placement group rules and limits, status check types, automatic recovery (simplified vs CloudWatch), VPC quotas (EIPs, SGs, NACL rules), public IPv4 charging, S3 gateway endpoint rules, Auto Scaling health checks, grace period defaults, dynamic and predictive scaling, lifecycle hooks, warm pools, mixed instances allocation strategies.
Not confirmed (verify): DeleteOnTermination default for extra volumes added in the launch wizard, NVMe instance store hardware encryption wording and which types need initialization, AMI block public access default for new accounts, ENA above 100 Gbps on newest types, moving a stopped instance into a placement group, exact ASG default termination policy order, cross-zone defaults for ALB/NLB, Elastic Disaster Recovery RPO/RTO figures.

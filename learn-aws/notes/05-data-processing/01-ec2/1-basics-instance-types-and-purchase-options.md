# EC2 – 1. Basics, instance types and purchase options

Short notes. Each point is a fact you can be asked about.

## A. What EC2 is
- EC2 (Elastic Compute Cloud) = virtual servers (instances) that you rent by the second in an AWS Region.
- You manage the operating system, patches, software, scaling and backups. AWS manages the hardware and hypervisor.
- EC2 is **unmanaged** compute in the shared responsibility model. Glue, Athena, Lambda, EMR Serverless and Fargate are managed or serverless: AWS runs more of the stack.
- An instance runs in **one Availability Zone** (AZ). It lives in one subnet of one VPC.
- Many AWS data services run on EC2 under the hood: EMR clusters, ECS/EKS worker nodes, AWS Batch compute, self-managed Kafka/Airflow/Spark.
- Pick EC2 when: you need full OS control, custom software or drivers, long-running jobs over 15 minutes (Lambda limit), special hardware (GPU, huge RAM, local NVMe), licensed software tied to cores, or steady 24/7 load that is cheaper with commitments.
- Avoid EC2 when: a managed service does the job (Glue for ETL, Athena for SQL on S3, Lambda for short event code, MWAA for Airflow). Managed = less operations work, and the exam usually prefers "least operational overhead".
- EC2 vs Lambda: Lambda runs at most 15 minutes, is billed per request plus duration, and has no servers to patch. EC2 has no time limit but you pay while it runs, even when idle.
- EC2 vs Fargate: Fargate runs containers without managing hosts. EC2 launch type for ECS/EKS gives you GPUs, custom AMIs, Spot control and Savings on large steady fleets.
- EC2 vs EMR: EMR installs and manages Spark/Hive/Presto on EC2 for you. Raw EC2 means you install and tune Hadoop/Spark yourself.
- EC2 vs AWS Batch: Batch picks instances, queues jobs and scales EC2 or Fargate for you. Use Batch instead of hand-built job schedulers on EC2.

## B. Core building blocks
- **AMI** (Amazon Machine Image) = template with the root volume snapshot, launch permissions and block device mapping. Every instance launches from an AMI.
- AMIs are **Regional**. To use one in another Region, copy it there.
- AMI sources: AWS-provided (Amazon Linux 2023, Windows, Ubuntu), AWS Marketplace (paid software), community AMIs (public, be careful), and your own (custom "golden" AMIs).
- **Instance type** = the hardware shape: vCPU, memory, network, local storage (for example `m7g.xlarge`).
- **Key pair** = SSH public key placed on the instance for login. AWS keeps only the public key. If you lose the private key you cannot SSH in with it (use Session Manager or replace the key).
- **Security group** = stateful virtual firewall attached to the network interface. Covered in file 3.
- **IAM instance profile** = container that passes an IAM role to the instance. Apps on the instance get temporary credentials from instance metadata. Never store access keys on the instance.
- **User data** = script or cloud-init config that runs at first boot as root. Limit 16 KB raw (before base64).
- User data runs **only at first launch** by default. To run on every start you must configure it (cloud-init `scripts-user always`, or `<persist>true</persist>` on Windows).
- You can change user data only while the instance is **stopped**.
- User data is **not encrypted and not secret**. Anyone with `ec2:DescribeInstanceAttribute` or access to instance metadata can read it. Put secrets in Secrets Manager or Parameter Store.
- User data is not copied into an AMI you create from the instance.
- **Launch template** = saved, versioned launch settings (AMI, type, SG, role, user data, tags, Spot options, IMDS options). Required for mixed-instance Auto Scaling, EC2 Fleet, and most new features.
- **Launch configurations** (old ASG templates) are being retired: no new instance types since 1 Jan 2023, and accounts created on or after 1 Oct 2024 cannot create them at all. Use launch templates.
- **Tags** = key/value labels. Used for cost allocation, IAM conditions (ABAC) and automation. Tags can be exposed in instance metadata if you enable it.
- **Instance ID** stays the same through stop/start and recovery. It changes only when a new instance is launched.

## C. Instance families and naming
- Name format: `series` + `generation` + `options` + `.size`. Example `c7gn.xlarge` = compute (c), 7th generation, Graviton (g), network optimized (n), size xlarge.
- Series letters:
  - **M** general purpose (balanced CPU:RAM, about 1:4)
  - **T** burstable general purpose (cheap, CPU credits)
  - **C** compute optimized (about 1:2 CPU:RAM)
  - **R** memory optimized (about 1:8)
  - **X**, **U**, **z** high memory / memory intensive / high frequency
  - **I**, **Im**, **Is**, **D** storage optimized (local NVMe or dense HDD)
  - **P** GPU (training), **G** graphics/GPU inference, **Inf** AWS Inferentia, **Trn** AWS Trainium, **F** FPGA, **VT** video transcoding
  - **Hpc** high performance computing, **Mac** macOS
- Option letters:
  - **g** = AWS Graviton (ARM)
  - **a** = AMD
  - **i** = Intel
  - **d** = local NVMe instance store disks
  - **n** = higher network and EBS bandwidth
  - **b** = block storage (EBS) optimized
  - **e** = extra memory, extra storage or extra GPU memory
  - **z** = high CPU frequency
  - **flex** = Flex instance (cheaper, for workloads that do not use full CPU all the time)
- Size ladder: nano, micro, small, medium, large, xlarge, 2xlarge … 48xlarge, and **metal** (bare metal, no hypervisor).
- Doubling the size roughly doubles vCPU, RAM, network baseline and price inside a family.
- Higher generation = better price/performance. Prefer the newest generation available in the Region.
- **Nitro System** = AWS hardware cards plus a light hypervisor. Almost all current instances are Nitro. Nitro gives near bare-metal performance, ENA networking, NVMe EBS and features like the attached-EBS status check.
- Older Xen-based types (T2, M4, C4, R4, I3 and older) miss newer features. The exam may treat them as "previous generation".
- **vCPU** = one thread. On most Intel/AMD types, 1 physical core = 2 vCPUs (hyper-threading). On Graviton, 1 vCPU = 1 physical core. T2 and T4g are exceptions too.
- You can change CPU options at launch (fewer cores, threads per core = 1) to cut per-core software license cost. vCPU-based billing does not change.

## D. Choosing an instance type for data work
- Spark executors, pandas, in-memory joins, caches → **R** (memory optimized).
- CPU-heavy parsing, compression, encoding, batch transforms → **C** (compute optimized).
- Mixed web/ETL/app servers, Airflow workers → **M** (general purpose).
- HDFS, Kafka brokers, Cassandra, Elasticsearch with local disks, Spark shuffle scratch → **I** or **D**, or any type with **d** (NVMe instance store).
- ML training → **P** or **Trn**. ML inference → **G** or **Inf**.
- Dev boxes, low-traffic tools, small schedulers → **T** (burstable).
- Use **attribute-based instance type selection** (vCPU and memory ranges) in ASGs and EC2 Fleet so AWS picks any matching type. This improves Spot availability.
- **EC2 instance type finder** (console, uses Amazon Q) and **AWS Compute Optimizer** recommend types from your needs or from your real usage.
- Changing instance type: stop the instance (EBS-backed), change type, start. Instance store data is lost. The new type must support the AMI architecture (x86 vs ARM) and virtualization type.
- You **cannot** change an x86 instance into a Graviton (ARM) instance in place. You must launch from an ARM AMI.

## E. Graviton (ARM)
- Graviton = AWS-designed ARM processors. AWS calls them the best price/performance for most workloads.
- Up to about 40% better price/performance than comparable x86 for many workloads, and lower energy use (verify exact figure).
- Catch: software must have ARM (arm64) builds. Most Linux, Java, Python, Spark, and containers built multi-arch work. Some closed-source binaries or Windows do not.
- Many managed services offer Graviton options too (RDS, ElastiCache, EMR, Lambda arm64, Fargate, OpenSearch). Moving to Graviton is a common cost answer.
- Graviton instances show `g` in the name: `m7g`, `c8g`, `r8g`, `t4g`, `x8g`, `i8g`.

## F. Burstable T instances (T2, T3, T3a, T4g, T8i)
- T instances give a **baseline** CPU % and **burst** above it using **CPU credits**.
- 1 CPU credit = 1 vCPU at 100% for 1 minute (or 1 vCPU at 50% for 2 minutes, and so on).
- Baseline examples: `t3.nano` 5% per vCPU, `t3.micro` 10%, `t3.small`/`medium` 20%, `t3.large` 30%, `t3.xlarge`/`2xlarge` 40%.
- Credits are earned below baseline and spent above baseline. Accrual cap = the credits the instance can earn in 24 hours.
- **Standard mode**: when credits run out, the CPU drops to baseline. The job gets slow, but you pay no extra.
- **Unlimited mode**: the instance can keep bursting. If average CPU over a rolling 24 hours (or the instance lifetime, if shorter) is above baseline, you pay a flat extra rate per vCPU-hour.
- Default mode: **T3, T3a, T4g, T8i launch as Unlimited**. **T2 launches as Standard**.
- T3 on a Dedicated Host launches as Standard; Unlimited is not supported there.
- Only T2 Standard gets **launch credits**. T3/T4g/T8i have no launch credits but can burst at once because they are Unlimited.
- Credit balance after stop: T2 loses all credits. T3/T3a/T4g/T8i keep credits for **7 days** after stop.
- Trap: "a nightly job on t3 suddenly takes 4× longer" → credits exhausted in Standard mode. Fix: Unlimited mode, a bigger T size, or move to M/C.
- Trap: "unexpected EC2 charges on t3 instances" → Unlimited mode running above baseline for long periods. Fix: watch `CPUSurplusCreditsCharged`, or switch to fixed-performance types.
- CloudWatch metrics: `CPUCreditBalance`, `CPUCreditUsage`, `CPUSurplusCreditBalance`, `CPUSurplusCreditsCharged`.
- T instances are **not supported in cluster placement groups**.

## G. Instance lifecycle and billing by state
- States: `pending` → `running` → `stopping` → `stopped` → (start again) … or `shutting-down` → `terminated`.
- Billed for instance usage only in **running**. Hibernation is also billed during `stopping`.
- Not billed in pending, stopping (normal stop), stopped, shutting-down, terminated.
- EBS volumes, Elastic IPs and public IPv4 addresses are **still charged** while the instance is stopped.
- Linux and Windows (excluding some licensed OSes) are billed **per second with a 60-second minimum** each time the instance moves to running.
- **Reboot**: same host, keeps public IP, keeps instance store data, no new billing period.
- **Stop/start** (EBS-backed only):
  - The instance usually moves to a new host.
  - Instance store data is erased and RAM is lost.
  - The private IP and the Elastic IP are kept.
  - The **auto-assigned public IPv4 changes**.
- **Hibernate** (EBS-backed only): RAM is saved to the encrypted EBS root volume. On start, processes resume where they were. Instance store data is erased. Same IP rules as stop.
- **Terminate**:
  - The instance is gone for good.
  - The root EBS volume is deleted by default (`DeleteOnTermination=true`). Extra data volumes are kept by default.
  - The Elastic IP is disassociated but stays in your account, still billed.
- An instance with an **instance store root** cannot be stopped. It can only reboot or terminate.
- **Termination protection** (`DisableApiTermination`) blocks terminate from console/API/CLI. **Stop protection** blocks stop.
- Neither protection stops a shutdown run inside the OS, or Spot interruptions, or Auto Scaling scale-in. (ASG uses its own **instance scale-in protection**.)
- `InstanceInitiatedShutdownBehavior` decides whether an OS `shutdown` command **stops** (default) or **terminates** an EBS-backed instance.
- Reserved Instances keep billing after the matching instance is terminated (you committed to the term).

## H. Hibernation details
- Must be **enabled at launch**. You cannot turn it on for an existing instance.
- Root volume must be **EBS** (gp2, gp3, io1, io2), **encrypted**, and big enough to hold RAM.
- RAM limit: Linux **less than 150 GiB**, Windows **16 GiB or less**.
- Supported families include most current M, C, R, T, I and some X families. Bare metal is not supported.
- Spot can use hibernation only with a `persistent` request and no launch group.
- Use case: apps with slow warm-up (big caches, JVM warm-up) that you want to pause and resume quickly. Also used by ASG warm pools.
- Hibernation does not guarantee capacity on resume, even with a Capacity Reservation.

## I. Purchase options (pricing models)
| Option | Commitment | Discount vs On-Demand | Capacity guaranteed? | Best for |
|---|---|---|---|---|
| On-Demand | None, per second | 0% | No | Short, spiky, unpredictable, cannot be interrupted |
| Savings Plans | $/hour for 1 or 3 years | Up to 72% (EC2 Instance SP), up to 66% (Compute SP) | No | Steady baseline usage |
| Reserved Instances | Specific config for 1 or 3 years | Up to 72% (verify per class) | Only zonal RIs | Legacy; AWS now recommends Savings Plans |
| Spot | None | Up to 90% (verify) | No, can be interrupted with 2-minute notice | Fault-tolerant, flexible, batch, big data |
| Dedicated Instances | None or RI/SP | Pay per instance + Regional fee | No | Compliance needing single-tenant hardware |
| Dedicated Hosts | Per host, On-Demand or Reservation | Up to 70% with Host Reservation | The host is yours | BYOL per-socket/per-core licenses |
| On-Demand Capacity Reservation | None (or committed if future-dated) | None by itself | Yes, in one AZ | Guarantee capacity for critical events |
| Capacity Blocks for ML | Pay up front for a time window | Market price | Yes, GPU in UltraClusters | Short GPU training jobs |

## J. On-Demand
- Pay per second (60-second minimum), no commitment, start and stop any time.
- Best for short-term, irregular workloads that cannot be interrupted, and for testing.
- On-Demand quotas are counted in **vCPUs per Region**, not instance count. Example: the "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" quota.
- Default for many families (P, G, X, Trn, Inf, High Memory, DL, F, HPC) on a new account can be **0 vCPUs**. You must request an increase in Service Quotas.
- Stopped, hibernated, pending and stopping instances do **not** count toward the quota. Capacity Reservations **do**, even unused.

## K. Savings Plans
- You commit to spend a fixed **$ per hour** for **1 or 3 years**. Usage up to that amount gets the discounted rate. Usage above it pays On-Demand.
- Payment: All Upfront, Partial Upfront, No Upfront. More upfront = bigger discount.
- **Compute Savings Plans**: up to 66% off.
  - Apply to EC2 in **any family, size, AZ, Region, OS and tenancy**.
  - Also apply to **Fargate** and **Lambda**.
  - The most flexible plan. Pick it if you may move Regions, change families, or move from EC2 to containers or serverless.
- **EC2 Instance Savings Plans**: up to 72% off.
  - Locked to **one instance family in one Region** (for example `m7g` in us-east-1).
  - Flexible on size, OS and tenancy within that family.
- **Database Savings Plans**: up to 35% off on Aurora, RDS, DynamoDB, ElastiCache, DocumentDB, Neptune, Keyspaces, Timestream, DMS, OpenSearch. Not EC2.
- **SageMaker AI Savings Plans**: up to 64% off SageMaker instance usage.
- Both Compute and EC2 Instance plans cover the EC2 instances under **EMR, ECS and EKS** clusters. They do not cover EKS control-plane fees or EMR service fees.
- Savings Plans **do not reserve capacity**. Pair them with On-Demand Capacity Reservations if you need both discount and guarantee.
- You **cannot cancel or change** a Savings Plan after purchase. You can only add more plans.
- The $2/hour Regional fee for Dedicated Instances is **not** discounted by Savings Plans.
- Cost Explorer gives Savings Plans purchase recommendations from your past usage.

## L. Reserved Instances (RIs)
- AWS now **recommends Savings Plans over RIs**. RIs still exist and still appear in exams.
- An RI is a **billing discount**, not a physical instance. It applies to running instances that match its attributes.
- Attributes that set the price: instance type, Region, tenancy, platform (OS).
- Term: 1 year or 3 years (3 years = bigger discount). They **do not auto-renew**. After expiry you pay On-Demand.
- Payment: All Upfront, Partial Upfront, No Upfront.
- You cannot cancel an RI. You may be able to modify, exchange (Convertible) or sell it (Standard, on the RI Marketplace).
- **Standard RI**: biggest RI discount. Can be modified (AZ, scope, size within family on Linux) but **not exchanged**. Can be **sold on the RI Marketplace**.
- **Convertible RI**: smaller discount. Can be **exchanged** for another Convertible RI with a different family, OS or tenancy (equal or greater value). Cannot be sold on the Marketplace (verify).
- **Regional RI**:
  - Applies in **any AZ** in the Region.
  - Has **instance size flexibility** inside the family (Linux/Unix, default tenancy only).
  - **Does not reserve capacity**. Purchases can be queued.
- **Zonal RI**:
  - Locked to **one AZ**, exact type and size.
  - **Reserves capacity** in that AZ. Purchases cannot be queued.
- Size flexibility uses a **normalization factor** (for example, one `large` = 4 units, one `xlarge` = 8 units).
- Scheduled RIs are no longer offered (verify).

## M. Spot Instances
- Spot = spare EC2 capacity at a steep discount, up to 90% off On-Demand (verify). The price changes slowly with long-term supply and demand.
- AWS can take capacity back at any time. You get a **2-minute interruption notice**, except with hibernate, which starts at once with no 2-minute warning.
- Interruption reasons: AWS needs the **capacity** back (the main reason), the Spot price goes **above your max price** (if you set one), or a group **constraint** (launch group / AZ group) can no longer be met.
- AWS advice: **do not set a max price**. Setting one causes more interruptions. The default max is the On-Demand price.
- **Interruption behavior**: terminate (default), stop, or hibernate. Stop and hibernate need EBS-backed instances and `persistent` requests.
- Notice delivery:
  - EventBridge event `EC2 Spot Instance Interruption Warning`.
  - Instance metadata path `/latest/meta-data/spot/instance-action`.
  - AWS suggests checking metadata every 5 seconds. Notices are best effort.
- **Rebalance recommendation** = an earlier signal that the instance is at **elevated risk** of interruption. It often arrives before the 2-minute notice. ASG **Capacity Rebalancing** uses it to launch a replacement before the old instance is interrupted.
- Billing when interrupted:
  - **AWS** interrupts a Linux/Windows Spot instance in its **first hour** → **no charge**.
  - AWS interrupts after the first hour → charged per second used.
  - **You** stop or terminate → charged per second used.
- Request types: **one-time** (does not come back after interruption) and **persistent** (re-opens and relaunches when capacity returns).
- **Spot Fleet** and **EC2 Fleet** launch a mix of Spot and On-Demand across many instance types and AZs to hit a target capacity. EC2 Fleet is the newer API. ASGs with mixed instances do the same job with scaling.
- **Capacity pool** = one instance type in one AZ. More pools (more types and AZs) = fewer interruptions and better fulfilment.
- Spot allocation strategies:
  - **price-capacity-optimized**: **AWS recommended** for most workloads (data/analytics, batch, containers, CI). Picks the pools with the most capacity, then the cheapest of those.
  - **capacity-optimized**: picks the most available pools. For jobs where interruption is very costly. `capacity-optimized-prioritized` also honours your type priority, best effort.
  - **diversified**: spreads across all pools. For large or long-running fleets.
  - **lowest-price**: **not recommended**, the highest interruption risk. It is the CLI default for EC2 Fleet/Spot Fleet, so override it.
- Spot is good for:
  - Spark/EMR **task** nodes
  - Batch jobs with checkpoints
  - Stateless containers and CI runners
  - Rendering and ML training with checkpointing
  - Any job that can retry
- Spot is bad for:
  - Databases, the EMR primary node and EMR core nodes holding HDFS data
  - Single long jobs with no checkpoint
  - Anything with a strict deadline and no fallback
- Spot Blocks (fixed 1–6 hour Spot) are discontinued (verify).
- Spot Instance quotas are separate from On-Demand quotas, also counted in vCPUs (verify exact quota names).

## N. Dedicated Instances vs Dedicated Hosts
- Both put your instances on hardware **dedicated to your account**. Neither differs in performance or security from the other.
- **Dedicated Instance**:
  - Billed **per instance**, plus a **Regional fee** ($2/hour in each Region with at least one running Dedicated Instance).
  - No visibility of sockets or cores and no placement control.
  - Works with Capacity Reservations.
- **Dedicated Host**:
  - A whole physical server, billed **per host**.
  - You see sockets and physical cores, and can control placement with **host affinity**.
  - Supports **BYOL** for per-socket, per-core or per-VM licenses (Windows Server, SQL Server, Oracle, RHEL, SUSE).
  - Can be shared with other accounts via AWS RAM.
  - Does **not** support Capacity Reservations.
- Dedicated Host Reservations give up to 70% off On-Demand host pricing.
- RDS cannot run on Dedicated Hosts.
- Exam cue: "license bound to physical cores/sockets" → **Dedicated Host**. "Compliance says no shared hardware, licensing not an issue" → **Dedicated Instance** (cheaper and simpler).
- Tenancy options on launch: `default` (shared), `dedicated` (Dedicated Instance), `host` (Dedicated Host). You can change between dedicated and host on a stopped instance. You cannot change default to dedicated after launch (verify).

## O. On-Demand Capacity Reservations (ODCR)
- Reserve capacity for an exact instance type, platform, AZ and tenancy, for **any duration**.
- **Immediate-use** reservation: no term, cancel any time. You pay the On-Demand rate for the reserved capacity **whether or not instances run in it**.
- **Future-dated** reservation: pick a start date and a commitment period. Billing starts on the start date. You cannot reduce the count or the period during the commitment. Minimum 32 vCPUs total.
- Gives **no discount** by itself. Combine with **Savings Plans or Regional RIs** to get the discount. Zonal RIs do not apply to Capacity Reservations.
- **Open** reservations auto-match any running instance with matching attributes. **Targeted** reservations are used only by instances that name them.
- Can be shared with other accounts (RAM). Can be created inside a **cluster placement group**. Not supported in spread or partition groups, or on Dedicated Hosts.
- Counts toward your On-Demand vCPU quota, even when unused.
- Exam cue: "must be sure capacity exists in a specific AZ for an event / DR / month-end batch" → Capacity Reservation (plus Savings Plans for price).

## P. Capacity Blocks for ML
- Reserve **GPU / Trainium** instances (P5, P5e, P5en, P6, P4d, Trn1, Trn2 and others) for a fixed future window, for short ML training or fine-tuning jobs.
- Book up to **8 weeks** ahead. Each block holds up to **64 instances**. You can hold up to **256 instances** across Capacity Blocks.
- Instances are placed close together in **EC2 UltraClusters** for low-latency, non-blocking networking.
- No cancellation. Instances are terminated near the end time (the termination process starts at 11:00 UTC on the last day; blocks end at 11:30 UTC).
- Does not support placement groups. Does not count toward On-Demand quotas.
- Exam cue: "need 32 GPUs for 10 days next month, guaranteed" → Capacity Blocks for ML.

## Q. Cost traps tied to purchase choice
- A Regional RI or a Savings Plan does not guarantee you can launch in an AZ. Capacity errors are still possible.
- A Zonal RI gives capacity but only in one AZ. Losing that AZ means losing the capacity benefit.
- Unused Capacity Reservations are billed like running instances.
- Unused Savings Plan commitment is wasted. Size the commitment to your **minimum steady** usage, not your peak.
- An EC2 Instance Savings Plan does not follow you if you change family or Region. A Compute Savings Plan does.
- T3 Unlimited surplus charges can make a "cheap" instance cost more than an M instance.

## Scenarios (if → then, because)
- If a nightly Spark job must finish cheaply and can retry → Spot (price-capacity-optimized, many instance types), because it is up to 90% off and interruptions only slow the job.
- If a steady 24/7 baseline will run for 3 years but may move to Fargate or another Region → Compute Savings Plan, because it covers EC2, Fargate and Lambda in any Region.
- If the baseline is fixed on one family in one Region → EC2 Instance Savings Plan, because it gives the highest Savings Plan discount (up to 72%).
- If you must guarantee 50 instances in one AZ for a 3-day migration window → On-Demand Capacity Reservation, because it is the only option that reserves capacity without a 1–3 year term.
- If you need capacity guarantee and discount for steady load → Capacity Reservation plus Savings Plan (or Regional RI).
- If software licenses are per physical core → Dedicated Host, because only it shows sockets and cores for BYOL.
- If compliance only needs single-tenant hardware → Dedicated Instances, because they are simpler and cost less than whole hosts.
- If a t3 instance slows down every night → CPU credits ran out in Standard mode. Switch to Unlimited or a fixed-performance type.
- If t3 bills are higher than expected → Unlimited mode surplus credits. Move the steady load to M/C instances.
- If a Linux Spot instance is interrupted by AWS after 20 minutes → no charge for that partial hour.
- If you want warning before a Spot interruption to drain work → handle the rebalance recommendation and the 2-minute notice (EventBridge or IMDS polling).
- If an ASG of Spot instances keeps getting interrupted → add more instance types and AZs, use price-capacity-optimized, and turn on Capacity Rebalancing.
- If a team needs 64 GPUs for two weeks of model training next month → Capacity Blocks for ML.
- If a job needs to run longer than 15 minutes with custom native libraries → EC2 (or Batch/ECS on EC2), not Lambda.
- If the requirement is "least operational overhead" for ETL → Glue or EMR Serverless, not self-managed Spark on EC2.
- If you want to cut cost without changing code on Java/Python/Spark → try Graviton (`g`) instances, because they give better price/performance.
- If an app needs 2 minutes of warm-up after every start → hibernation (enabled at launch, encrypted root) or an ASG warm pool.
- If you change instance type and data on the local NVMe disks is gone → instance store does not survive stop/start or a type change.
- If you can't launch 20 `p5` instances in a new account → the On-Demand P instance vCPU quota is 0 by default. Request an increase.
- If a script on the instance needs AWS credentials → attach an IAM role via an instance profile. Never bake keys into the AMI or user data.
- If secrets were placed in user data → move them to Secrets Manager or Parameter Store, because user data is readable through metadata and the API.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: instance type naming and families, burstable credit concepts and defaults, instance lifecycle and billing by state, hibernation prerequisites, user data limits, launch configuration retirement, On-Demand vCPU quotas, Savings Plans types and discounts, RI scope and offering classes, Capacity Reservations, Capacity Blocks for ML, Dedicated Hosts vs Instances, Spot interruptions, notices, billing and allocation strategies.
Not confirmed (verify): Graviton "40%" figure, Spot "up to 90%", exact Standard/Convertible RI discounts, Convertible RI not sellable on Marketplace, Scheduled RIs and Spot Blocks discontinued, Spot quota names, changing tenancy from default to dedicated after launch.

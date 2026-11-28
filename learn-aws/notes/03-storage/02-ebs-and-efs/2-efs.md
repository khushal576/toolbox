# EFS (Elastic File System) – full notes

Short notes. Each point is a fact you can be asked about.

## A. What EFS is
- EFS = managed, elastic, shared file system using NFS (v4.1 and v4.0). Many servers mount it at the same time.
- It grows and shrinks automatically. No capacity to provision. You pay for what you store.
- Linux only. Windows is not supported (use FSx for Windows File Server).
- Works with EC2, ECS, EKS, Fargate, Lambda, and on-premises servers (over Direct Connect or VPN).
- Use for: shared content, web serving, home directories, CI/CD shared artifacts, ML training data, containers needing shared state, Lambda needing big shared files/models.
- Avoid for: boot disks or single-instance databases needing lowest latency (EBS), cheap object storage (S3), Windows/SMB workloads (FSx), HPC with extreme throughput (FSx for Lustre).
- EFS vs EBS: EFS = shared, multi-AZ, NFS, elastic; EBS = one instance, one AZ, block, fast.
- EFS vs S3: EFS = POSIX file system with locking and low-latency random access; S3 = objects, cheapest, API access.

## B. File system types
- Regional: data stored across multiple AZs in a Region. Highest durability and availability. Use for production.
- One Zone: data stored in a single AZ. Lower price. Lower availability. Use for dev/test or re-creatable data.
- One Zone file systems always use General Purpose performance mode.
- Regional designed for 11 nines durability and 99.99% availability; One Zone 11 nines within one AZ and 99.9% availability (verify).

## C. How you connect
- Create the file system, then create **mount targets**: one per AZ (a network interface in a subnet). Max 1 mount target per AZ per file system.
- Clients mount via NFS over TCP **port 2049**. Mount target security groups must allow inbound 2049 from the clients (max 5 security groups per mount target).
- Mount with the EFS mount helper (`amazon-efs-utils`) for TLS and IAM options, or plain NFS.
- Mount on-premises: use Direct Connect or VPN; latency must be low for full throughput.
- Mount from another VPC or account: VPC peering or Transit Gateway, then mount target IP (or DNS with proper config). One VPC per file system (limit 1 VPC for mount targets).
- Containers: ECS task definitions and EKS (EFS CSI driver) mount EFS volumes. Fargate supports EFS.
- Lambda: attach an EFS access point to the function (needs VPC config). Good for large models/shared files.
- Use DNS name `fs-xxxx.efs.region.amazonaws.com`; it resolves to the mount target in the client's AZ.
- NFS limits: `nconnect` not supported; NFSv2/v3 not supported.
- POSIX permissions (user ID, group ID, mode) control access inside the file system.
- Max 16 group IDs per user in NFS (extra groups are cut off).

## D. Performance modes
- General Purpose (default, recommended): lowest latency. Up to 250,000 file operations per second (docs quota table).
- Max I/O: older mode for highly parallel workloads with higher latency. Not available for One Zone or Elastic throughput. AWS recommends General Purpose for all file systems.
- Monitor `PercentIOLimit` to see how close you are to the General Purpose IOPS limit.

## E. Throughput modes
- **Elastic** (recommended default): throughput scales up and down automatically with workload. Pay for data read/written. Best for spiky or unpredictable workloads or when average-to-peak is about 5% or less.
- **Provisioned**: you set the throughput you need, independent of size. Pay for the provisioned amount above the baseline. Best when you know the need or average-to-peak is 5% or more.
- **Bursting**: baseline throughput grows with stored size (50 KiB/s per GiB of Standard data), with burst credits. Bursts up to 100 MiB/s per TiB when credits exist.
- Bursting facts: baseline 50 MiBps per TiB; burst 100 MiBps per TiB; min 1 MiBps metered; credit balance cap 2.1 TiB per TiB stored; can burst up to 12 hours/day on large file systems.
- Reads are metered at one-third the rate of writes (reads are "discounted").
- You cannot switch from Provisioned to Elastic/Bursting or lower the provisioned amount for 24 hours after setting/changing Provisioned.
- If Bursting runs out of credits (BurstCreditBalance 0) → switch to Elastic or Provisioned.
- Per-file-system limits (General Purpose):
  - Regional Elastic: read up to 20–60 GiB/s, write 1–5 GiB/s (depends on Region; big Regions 60/5), IOPS read 900,000–2,500,000 and write 500,000 (with quota raise).
  - Regional Provisioned: read 3–10 GiB/s, write 1–3.33 GiB/s; IOPS 55,000 read / 25,000 write.
  - Regional Bursting: read 3–5 GiB/s, write 1–3 GiB/s; IOPS 35,000 read / 7,000 write.
  - One Zone: read 3 GiB/s, write 1 GiB/s; IOPS 35,000 / 7,000.
  - Per client: up to 1,500 MiB/s (Elastic with amazon-efs-utils 2.0+ or CSI driver) else 500 MiB/s.
- Latency: reads about 1 ms, writes about 2.7 ms for Standard; tens of ms for IA and Archive first byte.
- Tips: parallelize (many threads, many clients), use larger I/O, use the EFS mount helper, avoid many tiny files over high-latency links.

## F. Storage classes
- Standard: frequently accessed. SSD. Regional, multi-AZ.
- Infrequent Access (IA): lower storage price, per-GB access fee, 30-day minimum.
- Archive: lowest price for rarely accessed data, access fee, 90-day minimum.
- One Zone, One Zone-IA, One Zone Archive: same ideas, single AZ.
- First-byte latency for IA and Archive is tens of milliseconds (Standard about 1 ms read).
- Lifecycle management: automatically move files not accessed for N days (for example 7, 14, 30, 60, 90 days) to IA, and to Archive (typically 90+ days) — exact choices: verify.
- Intelligent Tiering behavior: you can choose to move files back to Standard on first access (so hot files return to fast storage) or not.
- Files under 128 KiB are not moved to IA or Archive (stay in Standard) (verify).
- No retrieval fee in Standard and One Zone Standard.
- Choose: active shared data → Standard; old project data → lifecycle to IA/Archive; non-critical → One Zone classes.

## G. Backup and replication
- EFS is durable but you still need protection against deletion/corruption.
- AWS Backup integration: automatic daily backups can be enabled (console default for new file systems; verify). Backups are incremental, restore to the same or new file system, can be copied cross-Region/account, vault lock for immutability.
- Restore options: full restore or specific files/directories.
- Replication: automatic and continuous copy of data and metadata to a destination file system in the same or another Region (and across accounts with an IAM role). RPO typically 15 minutes (can be longer for very large or very busy file systems).
- Destination is read-only while replication is on. For DR: fail over by deleting the replication configuration (destination becomes writable), later fail back by replicating in reverse.
- Replication creates about 12 MiB of hidden metadata on the destination (you are billed).
- Replication uses the service-linked role or a custom IAM role (required for cross-account). Does not support ABAC with tags.
- Regional file systems are already multi-AZ. Use replication for Region failure, compliance copies, lower-latency read copies.
- One Zone file systems are lost if the AZ is lost (use backups/replication).
- You can monitor `TimeSinceLastSync` in CloudWatch.
- DataSync can copy data to/from EFS (also from on-premises NFS, S3).

## H. Security
- Network: mount targets in your VPC with security groups; no public endpoint. Use VPC endpoints for the EFS API (interface endpoint). Block public access policy available.
- Encryption at rest: AWS KMS. Encrypt at creation; it cannot be changed later (create a new encrypted file system and copy data with DataSync/rsync). Console creates encrypted file systems by default (verify); you can enforce with IAM/SCP/Config.
- Encryption in transit: TLS using the EFS mount helper (`-o tls`) or the CSI driver. Can enforce with a file system policy deny when `aws:SecureTransport` is false.
- IAM authorization for NFS clients: enable with mount option `iam`; the IAM identity needs `elasticfilesystem:ClientMount`, `ClientWrite`, `ClientRootAccess`.
- File system policy: resource-based JSON policy (up to 20,000 characters). Use it to require TLS, require access points, restrict principals, enforce read-only for some roles, allow cross-account.
- Access points: application-specific entry points that enforce a POSIX user/group and a root directory for everyone using that access point, plus their own IAM policy. Great for multi-tenant and Lambda. Up to 10,000 per file system (default).
- POSIX permissions: file mode, owner, group enforced inside the file system. Root squashing: by default IAM controls root access via `ClientRootAccess`.
- ACLs, Kerberos and mandatory locking are not supported.
- Logging: CloudTrail logs API calls (management). Access to files is not logged by CloudTrail; use NFS-level or application logs.
- Compliance: HIPAA eligible and others (see AWS compliance programs).
- Shared responsibility: AWS secures the service; you manage IAM, security groups, encryption choices, data.

## I. Cost
- Pay for storage per GB-month by class (Standard highest, IA lower, Archive lowest; One Zone classes cheaper than Regional).
- Pay access fees per GB for IA and Archive reads/writes (plus lifecycle transition charges).
- Throughput: Elastic charges per GB read/written; Provisioned charges for throughput above the free baseline; Bursting included in storage price.
- Replication: destination storage, data transfer between Regions, ~12 MiB hidden data.
- Backup: AWS Backup storage per GB-month.
- Savings: lifecycle policies to IA/Archive; One Zone for non-critical data; right throughput mode (Elastic for spiky, Provisioned for steady heavy); delete old data; keep clients in the same AZ/Region to avoid cross-AZ transfer; consider S3 for cold large data.
- Data transfer: traffic between client and mount target in a different AZ costs; use the mount target in the same AZ.
- Reading many small files from IA classes costs access fees; keep hot data in Standard.

## J. Monitoring and troubleshooting
- CloudWatch metrics: `PermittedThroughput`, `MeteredIOBytes`, `TotalIOBytes`, `DataReadIOBytes`, `DataWriteIOBytes`, `MetadataIOBytes`, `BurstCreditBalance` (bursting), `PercentIOLimit` (General Purpose), `ClientConnections`, `StorageBytes` (by class), `TimeSinceLastSync` (replication).
- Alarm on `BurstCreditBalance` low, `PercentIOLimit` near 100, `ThroughputUtilization` high.
- Mount hangs or times out → security group does not allow 2049 from client, no mount target in that AZ/subnet, DNS resolution off in VPC, wrong NFS client settings.
- "Access denied" on files → POSIX permissions, IAM `ClientMount/ClientWrite`, file system policy, access point root dir/user, 16-GID limit.
- Slow performance → bursting credits exhausted, too few parallel threads, small I/O, high latency link (on-prem), IA/Archive access, Max I/O mode latency.
- Lambda cannot mount → function not in VPC, security group, access point missing, mount target not in same AZ as function subnet.
- Cannot change encryption → create a new encrypted file system and migrate.
- File too large or too many locks → limits (single file max 47.9 TiB; 512 locks per file; 25,000 connections per file system).
- Throttling at the connection limit → reduce connections or split across file systems.
- Cannot switch throughput mode → 24-hour restriction after Provisioned changes.
- Replication lag → check `TimeSinceLastSync`; huge/hot file systems may exceed 15 minutes.

## K. Limits and numbers (verified from AWS quotas page)
- File systems per account per Region: 1,000 (can increase).
- Access points per file system: 10,000 (can increase).
- Connections per file system: 25,000 (fixed).
- Mount targets per file system per AZ: 1. Per VPC: 1,400. Security groups per mount target: 5. VPCs per file system: 1.
- Tags per file system: 50.
- File name length: 255 bytes. Symlink length 4,080 bytes. Hard links per file 177. Directory depth 1,000.
- Max single file size: about 47.9 TiB.
- Locks on a single file: 512 across all clients. Locks per client mount: 65,536. Open files per instance: 65,536.
- File system policy max 20,000 characters.
- File operations per second (General Purpose): 250,000.
- Elastic IOPS defaults: 90,000 read (infrequent data), 250,000 read (frequent data), 50,000 write; can request up to 10 times more.
- NFS versions: 4.1 and 4.0 only; Windows not supported.

## L. Scenarios (if → then, because)
- **If** many Linux servers or containers must share the same files, **then** use Amazon Elastic File System (EFS), a managed shared file system using **NFS** (Network File System). Many servers mount it at the same time, and it grows and shrinks by itself, so you pay only for what you store. **This works because** a **Regional** EFS file system stores data across multiple Availability Zones (AZs), and clients in each AZ reach it through a **mount target** in their AZ.
- **If** Windows servers need a shared drive over Server Message Block (SMB), **then** use **Amazon FSx for Windows File Server**. **This works because** EFS is **Linux only** and supports only NFS 4.0 and 4.1; Windows is not supported.
- **If** one database server needs a single fast disk, **then** use Amazon Elastic Block Store (EBS), not EFS. **This works because** EBS is a block disk for one instance with low latency, while EFS is built for sharing files across many servers.
- **If** workload traffic is spiky or unknown, **then** use the **Elastic** throughput mode, the recommended default. **This works because** Elastic scales throughput up and down automatically and you pay **per GB read and written**, so cost follows use. It fits best when average throughput is about **5% or less** of peak.
- **If** you know you need steady, heavy throughput all the time, **then** use the **Provisioned** throughput mode, where you set the throughput yourself, independent of storage size. **This works because** Provisioned is built for a known need: you pay for the amount you set above the free baseline, and it fits best when average throughput is **5% or more** of peak. The catch: after setting or changing it, you cannot lower it or switch mode for **24 hours**.
- **If** throughput can grow with stored size and burst credits are enough, **then** use the **Bursting** throughput mode. **This works because** its baseline grows with data stored (**50 KiB/s per GiB**, or 50 MiB/s per TiB), and saved **burst credits** let it reach **100 MiB/s per TiB** for a while. Throughput is included in the storage price.
- **If** your file system keeps hitting throughput limits in Bursting mode, **then** switch to **Elastic** or **Provisioned** throughput. **This works because** Bursting slows to its baseline when **`BurstCreditBalance`** reaches **0**, while Elastic and Provisioned do not depend on credits.
- **If** old files are rarely used and storage cost is high, **then** add a **lifecycle policy** that moves files not accessed for N days to **Infrequent Access (IA)** and later to **Archive** (exact day choices: verify), with "move back to Standard on first access" turned on. **This works because** IA and Archive cost less to store, and hot files return to fast **Standard** storage. The catch: IA and Archive charge **access fees** and have **30-day** and **90-day** minimums; files under **128 KiB** stay in Standard (verify).
- **If** data can be re-created and cost matters, **then** use a **One Zone** file system with One Zone storage classes. **This works because** One Zone stores data in a **single AZ** at a lower price. The catch: availability is lower (99.9%, verify), and data is **lost** if that AZ is lost.
- **If** you need disaster recovery (DR) for a whole Region failure, **then** use **EFS replication** to a file system in another Region, or **AWS Backup** with **cross-Region copy**. **This works because** replication continuously copies data and metadata with a recovery point objective (RPO) of about **15 minutes**. The destination is **read-only**; to fail over, **delete the replication configuration** so it becomes writable.
- **If** backups must be immutable, **then** use **AWS Backup** with **vault lock**. **This works because** vault lock stops anyone from deleting or changing the backups, which protects against deletion and corruption.
- **If** an app must run as a specific user inside a shared file system, **then** give it an **EFS access point** that enforces a **POSIX user and group** and a **root directory**. **This works because** everyone using that access point is forced to that identity and directory, and the access point has its own Identity and Access Management (IAM) policy, which suits multi-tenant apps.
- **If** an AWS Lambda function needs big shared model files, **then** mount EFS into the function through an **access point**, with the function placed **in the VPC** (Virtual Private Cloud). **This works because** EFS has no public endpoint and is reached only through mount targets in your VPC, and the access point sets the user and directory for the function.
- **If** you must require encryption in transit, **then** add a **file system policy** that **denies** access when **`aws:SecureTransport`** is false, and mount with TLS (Transport Layer Security) using the EFS mount helper (`-o tls`). **This works because** the policy rejects any client that is not using TLS, so plain NFS mounts fail.
- **If** an unencrypted file system must be encrypted, **then** create a **new encrypted** file system and copy the data with **AWS DataSync** (or rsync). **This works because** encryption at rest is set **only at creation** and cannot be changed later.
- **If** you must copy data from an on-premises NFS server to EFS, **then** use **AWS DataSync**, a managed data copy service. **This works because** DataSync can copy into EFS from on-premises NFS and from Amazon S3.
- **If** on-premises servers need to mount EFS, **then** connect over **AWS Direct Connect** or a **VPN**, then do a normal NFS mount. **This works because** EFS is reached only inside your VPC. Expect lower throughput than in the VPC, because latency must be low for full speed.
- **If** Amazon Elastic Container Service (ECS) or Amazon Elastic Kubernetes Service (EKS) pods need persistent shared storage, **then** use **EFS volumes**: in ECS task definitions, and with the **EFS CSI driver** on EKS. **This works because** containers come and go, but files on EFS stay and are shared; AWS Fargate supports EFS too.
- **If** you need the lowest latency for small random I/O on one host, **then** use **EBS** or **instance store**, not EFS. **This works because** EFS is reached over the network with reads of about **1 ms** and writes of about **2.7 ms**, which is slower than a local or single-instance disk.
- **If** you need a parallel high-performance computing (HPC) file system, **then** use **Amazon FSx for Lustre**. **This works because** EFS is not meant for HPC with extreme throughput, and FSx for Lustre is.
- **If** EFS mounts hang or time out, **then** check that the mount target's **security group** allows inbound **TCP port 2049** from the clients, that there is a **mount target** in the client's AZ and subnet, and that **DNS resolution** is on in the VPC. **This works because** clients reach EFS only over NFS on port 2049 through a mount target, found by the file system's DNS name.

## Verified from AWS docs on 2026-10-02
EFS performance specifications, storage classes overview, quotas, security topics list and replication page were read. Not re-checked (verify): availability/durability percentages, default encryption and automatic backup behavior, lifecycle day options, 128 KiB minimum for IA, exact IAM mount options.

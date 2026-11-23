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
- If many Linux servers/containers must share the same files → EFS, because it is shared NFS across AZs.
- If Windows servers need an SMB share → FSx for Windows File Server, because EFS is Linux only.
- If you need a single fast disk for one database server → EBS, not EFS.
- If workload traffic is spiky or unknown → Elastic throughput, because it scales automatically and you pay per use.
- If a steady heavy throughput is known and sustained → Provisioned throughput.
- If throughput needs to follow storage size and credits suffice → Bursting.
- If your file system keeps hitting throughput limits with Bursting → switch to Elastic or Provisioned.
- If old files are rarely used and cost is high → lifecycle policy to IA/Archive, with "move back on access".
- If data can be re-created and cost matters → One Zone classes.
- If Region-level DR is needed → EFS replication (RPO about 15 minutes) or AWS Backup cross-Region copy.
- If you need immutable backups → AWS Backup with vault lock.
- If an app must run as a specific user inside a shared file system → EFS access point with enforced POSIX user and root directory.
- If a Lambda function needs big shared model files → mount EFS via access point (function in the VPC).
- If you must require encryption in transit → file system policy deny when `aws:SecureTransport` is false, and mount with TLS.
- If an unencrypted file system must be encrypted → create a new encrypted file system and copy data (DataSync), because encryption cannot be changed.
- If you must copy data from on-premises NFS to EFS → DataSync.
- If on-premises servers need to mount EFS → Direct Connect or VPN, then NFS mount (expect lower throughput than in-VPC).
- If ECS/EKS pods need persistent shared storage → EFS volumes (CSI driver on EKS).
- If you need the lowest latency for random small I/O on one host → EBS/instance store.
- If you need parallel HPC file system → FSx for Lustre.
- If EFS mounts hang → check security group port 2049, mount target in the AZ, and DNS.

## Verified from AWS docs on 2026-10-02
EFS performance specifications, storage classes overview, quotas, security topics list and replication page were read. Not re-checked (verify): availability/durability percentages, default encryption and automatic backup behavior, lifecycle day options, 128 KiB minimum for IA, exact IAM mount options.

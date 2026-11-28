# EBS (Elastic Block Store) – full notes

Short notes. Each point is a fact you can be asked about.

## A. What EBS is
- EBS = network-attached block storage (a virtual disk) for EC2 instances.
- The disk lives in one Availability Zone and attaches to an instance in the same AZ.
- Data stays when the instance stops. It is a different thing from instance store (disk physically inside the host, lost on stop/terminate).
- Use for: boot volumes, databases on EC2, transactional workloads, big-data nodes (EMR, Kafka, Cassandra), anything needing a normal disk with a file system.
- Avoid for: shared files between many servers (use EFS), unlimited cheap object storage (S3), caches that can use instance store.
- Block storage = you format it (ext4, XFS, NTFS) and mount it. EBS itself does not know about files.
- EBS volumes are replicated inside their AZ for durability. They do not survive loss of the AZ by themselves. Snapshots do (they are regional).
- AWS does not back up EBS volumes for you. You must create snapshots (manually, with Data Lifecycle Manager, or AWS Backup).
- EBS vs S3 vs EFS: EBS = one instance, low latency, disk; S3 = objects, unlimited; EFS = shared NFS files for many instances.

## B. Volume types (verified in AWS docs, 2026-10-02)
| Type | Kind | Size | Max IOPS | Max throughput | Notes |
|---|---|---|---|---|---|
| gp3 | General purpose SSD | 1 GiB–64 TiB | 80,000 | 2,000 MiB/s | Default choice. Durability 99.8–99.9% |
| gp2 | General purpose SSD (older) | 1 GiB–16 TiB | 16,000 | 250 MiB/s | IOPS tied to size (3 IOPS per GiB) |
| io2 Block Express | Provisioned IOPS SSD | 4 GiB–64 TiB | 256,000 | 4,000 MiB/s | 99.999% durability, sub-ms latency, Multi-Attach |
| io1 | Provisioned IOPS SSD | 4 GiB–16 TiB | 64,000 | 1,000 MiB/s | Older; Multi-Attach |
| st1 | Throughput-optimized HDD | 125 GiB–16 TiB | 500 | 500 MiB/s | Big sequential reads: logs, data warehouse, Kafka |
| sc1 | Cold HDD | 125 GiB–16 TiB | 250 | 250 MiB/s | Cheapest, infrequent access |
| standard | Magnetic (old) | 1 GiB–1 TiB | 40–200 | 40–90 MiB/s | Avoid |
- HDD volumes (st1, sc1) cannot be boot volumes. SSD types can.
- Multi-Attach works only on io1 and io2 (not gp3/gp2/st1/sc1).
- gp3: you get 3,000 IOPS and 125 MiB/s as baseline regardless of size, and you pay extra to raise IOPS and throughput separately from size (verify baseline numbers).
- gp2: 3 IOPS per GiB (min 100), can burst up to 3,000 IOPS using credits on small volumes (under 1,000 GiB); a big gp2 is just as fast as a gp3 for throughput planning only if sized large. gp3 is cheaper and more predictable.
- io1 IOPS to size ratio up to 50:1; io2 up to 500:1 (verify).
- Max IOPS needs the right I/O size (16 KiB for io1/io2, 25.6 KiB for gp3 in the docs) and a Nitro-based instance.
- Non-Nitro instances can attach volumes with up to 64,000 provisioned IOPS but reach only about 32,000.
- To reach 1,000 MiB/s on io1, provision 64,000 IOPS on a Nitro instance.
- Volumes created long ago (before Dec 2017/2018) may need a modify to reach full performance.
- Choose: general workloads → gp3. Needs sustained high IOPS / sub-ms latency / more than 80,000 IOPS → io2 Block Express. Big sequential data and logs, cost-sensitive → st1. Rare access, cheapest → sc1.
- Databases like Oracle/SQL Server needing consistent IOPS → io2.
- Kafka, Hadoop/EMR HDFS, log processing → st1 (cheaper per MiB/s) or gp3.

## C. Key behaviors
- Volume is tied to one AZ. To move it to another AZ: snapshot, then create a volume from the snapshot in the target AZ.
- One volume normally attaches to one instance at a time. Many volumes can attach to one instance.
- Multi-Attach (io1/io2): attach one volume to multiple Nitro instances in the same AZ (up to 16, verify). The apps must manage writes (cluster-aware file system). Not for normal ext4/XFS.
- Root (boot) volume deleted on termination by default. Additional volumes are kept by default (DeleteOnTermination=false). You can change both.
- Elastic Volumes: change size, type, IOPS and throughput of a live volume without detaching. You can only increase size, never shrink. After a change there is a cooldown (about 6 hours) before another change on that volume. The file system must be extended inside the OS after a size increase.
- To shrink: create a smaller volume, copy data, swap.
- EBS-optimized instances give dedicated bandwidth to EBS. Nearly all current instance types have it by default. Instance size limits total EBS throughput and IOPS too.
- RAID 0 across volumes adds IOPS/throughput (no redundancy); RAID 1 mirrors. EBS already replicates inside the AZ, so RAID 0 is often used for speed.
- Volumes created from a snapshot load lazily: first read of each block is slower. Fix: initialize (read all blocks with `fio`/`dd`) or use Fast Snapshot Restore.
- Instance store is faster and free with the instance but ephemeral. Use EBS when data must survive.
- Volume states: creating, available, in-use, deleting, error.
- Volumes can be attached/detached on running instances (unmount in the OS first).

## D. Snapshots (backup)
- Snapshot = point-in-time copy of a volume, incremental: only changed blocks since the previous snapshot are stored.
- First snapshot copies all used data; later ones only changes. Deleting an older snapshot never loses data needed by newer ones (AWS keeps the needed blocks).
- Stored in S3 (managed by AWS, you cannot see the buckets). Regional storage: replicated across AZs in the Region.
- You can restore a volume from a snapshot in any AZ in the Region.
- Snapshots of encrypted volumes are encrypted. Volumes made from encrypted snapshots are encrypted.
- Crash-consistent by default (like pulling the power). For application-consistent backups, quiesce the app (stop writes, flush) or use VSS-aware tools / AWS Backup with pre/post scripts. Multi-volume snapshots of an instance can be made together (consistent group).
- Copy snapshots to another Region for disaster recovery. Copy also lets you change the KMS key or encrypt an unencrypted snapshot.
- Share snapshots with specific AWS accounts. Encrypted snapshots can be shared only if encrypted with a customer managed KMS key (not the default aws/ebs key) and the target account is allowed to use the key.
- Public snapshots of encrypted volumes are not allowed. Block public access for snapshots can be turned on per Region.
- Fast Snapshot Restore (FSR): volumes created from the snapshot are fully initialized at creation (no lazy-load latency). Enabled per snapshot per AZ, billed per hour per snapshot per AZ. Limited number of snapshots per Region.
- Snapshot Archive tier: cheaper storage for snapshots you rarely restore (about 75% cheaper; minimum 90 days; restoring takes up to 24–72 hours; archived snapshot is a full copy, not incremental) (verify exact numbers).
- Recycle Bin: keep deleted snapshots (and AMIs) for a retention period so you can recover from accidental deletion.
- Snapshot Lock: make snapshots immutable (governance or compliance mode) for ransomware protection.
- Data Lifecycle Manager (DLM): create policies for scheduled snapshots, retention, cross-Region copy, cross-account copy, by tag.
- AWS Backup: central backup plans, cross-account, cross-Region, vault lock, supports EBS and many other services.
- Snapshots cost per GB-month of stored changed data. Deleting a snapshot may not reduce cost if blocks are used by others.
- Snapshot events go to CloudWatch Events / EventBridge.
- A snapshot taken while the volume is busy may take longer; I/O continues during the snapshot.
- Instance backup: AMI = snapshots of all volumes plus launch settings.

## E. Encryption
- EBS encryption uses AWS KMS. Encryption happens on the host servers, so data is protected at rest and in transit between the instance and the volume.
- Protects: data at rest on the volume, data moving between instance and volume, snapshots, and volumes created from those snapshots.
- Encryption by default: an account setting per Region. New volumes and snapshot copies are then always encrypted.
- You cannot encrypt an existing unencrypted volume in place. Snapshot it, then create an encrypted volume from the snapshot (or copy the snapshot with encryption on).
- You cannot remove encryption from an encrypted volume or snapshot.
- You cannot change the KMS key of an existing volume. Copy its snapshot with a different key, then create a volume.
- Default key: `aws/ebs` (AWS managed). Use a customer managed key for cross-account sharing, custom policy, or key control.
- Encrypted and unencrypted volumes can be attached to the same instance. All current instance types support EBS encryption.
- Little to no performance impact from encryption.
- Deleting or disabling the KMS key makes data unreadable.
- Control with IAM/SCP: require encryption (`ec2:Encrypted` condition key) for volume creation.
- AWS Config rule `encrypted-volumes` can detect unencrypted volumes.

## F. Performance
- Performance depends on: volume type, provisioned IOPS/throughput, I/O size, queue depth, instance type limits, EBS-optimized, network.
- IOPS = operations per second (best for small random I/O). Throughput = MiB/s (best for large sequential I/O).
- Match the volume to the workload: random small I/O → SSD; large sequential → st1.
- Instance-level caps: a small instance cannot use a huge volume's full performance. Check instance EBS bandwidth.
- Keep queue depth appropriate (about 1 per 500 IOPS rule of thumb for SSD; verify).
- Use striping (RAID 0) for more than a volume's max.
- Initialize volumes made from snapshots (or FSR) before production use.
- gp2 and st1/sc1 use burst credit buckets; watch `BurstBalance`. When it hits 0, performance drops to baseline. Move to gp3 (no burst credits) or io2.
- Pre-warming is not needed for new empty volumes.
- Use Nitro instances for the highest IOPS/throughput and for 256,000 IOPS io2 volumes.
- Latency: gp3 about single-digit ms; io2 Block Express averages under 500 microseconds (16 KiB I/O).

## G. Availability and durability
- gp3/gp2/io1/st1/sc1 durability 99.8–99.9% (annual failure rate 0.1–0.2%). io2 Block Express 99.999%.
- This is much lower than S3's 11 nines, so take snapshots.
- Volume lives in one AZ. AZ failure = volume unavailable. Recovery: restore from snapshot in another AZ.
- High availability patterns: snapshots + cross-Region copy; replicate at the application layer (database replication); Multi-AZ managed services (RDS) instead of self-run DB on EBS; Auto Scaling group with launch template and user data.
- EC2 instance failure: the volume survives; attach to a new instance in the same AZ.
- RPO depends on snapshot frequency (DLM can run every 1–24 hours).

## H. Cost
- You pay for: provisioned GB-month, provisioned IOPS (above included), provisioned throughput (above included), snapshots (GB-month of stored data), Fast Snapshot Restore (per hour per AZ), snapshot archive retrievals, data transfer for cross-Region copy.
- Unattached (available) volumes still cost money. Delete orphaned volumes and old snapshots.
- gp3 is typically about 20% cheaper per GB than gp2 and lets you set IOPS and throughput separately.
- Right-size volumes (you pay for provisioned size, not used size).
- Use st1/sc1 for big sequential data to save.
- Move old snapshots to the archive tier; set DLM retention to expire old ones.
- Use Cost Explorer and tags to find waste; Trusted Advisor flags idle/unattached volumes; Compute Optimizer recommends volume changes.
- Instance store is free with the instance (use for temp data, shuffle, caches).

## I. Monitoring and troubleshooting
- CloudWatch metrics: VolumeReadBytes/WriteBytes, VolumeReadOps/WriteOps, VolumeTotalReadTime/WriteTime, VolumeQueueLength, VolumeIdleTime, BurstBalance (gp2, st1, sc1), VolumeThroughputPercentage and VolumeConsumedReadWriteOps (io1/io2 volumes).
- Volume status checks (ok, warning, impaired, insufficient-data).
- High VolumeQueueLength plus latency → the volume is saturated; raise IOPS/throughput or change type.
- BurstBalance low → performance throttled; switch to gp3 or increase size.
- Instance slower than volume → instance EBS bandwidth limit.
- Volume at 100% of provisioned IOPS → increase IOPS.
- "Cannot attach volume" → different AZ, already attached (non-Multi-Attach), or wrong instance state.
- Cannot modify volume again → wait for cooldown (about 6 hours) or optimization to finish.
- Restored volume is slow at first → lazy loading; initialize or use FSR.
- Snapshot sharing fails → encrypted with aws/ebs managed key; use a customer managed key.
- Disk full inside OS after resizing → extend the partition and file system.
- Need alerts → CloudWatch alarms on BurstBalance, VolumeQueueLength, status checks.

## J. EBS for data engineering (where it shows up)
- EMR: core/task nodes use EBS for HDFS and shuffle. Choose volume type/size per node; HDFS data is lost when the cluster ends.
- MSK: broker storage is EBS-backed; supports auto expansion and tiered storage to S3.
- OpenSearch: data nodes use EBS (gp3/io1); size for index plus replicas.
- Self-managed databases and Kafka on EC2: st1 or gp3 for logs, io2 for strict latency.
- Glue/Athena/Redshift Serverless do not expose EBS to you.
- Redshift DC2 and RDS use SSD storage managed by the service (RDS storage uses EBS under the hood).

## K. Limits and numbers
- Volume sizes and IOPS as in table B.
- Elastic Volumes change cooldown: about 6 hours (verify).
- Max volumes per instance depends on instance type/OS (verify).
- Snapshot Archive minimum 90 days; restore from archive takes up to a few days (verify).
- Multi-Attach: io1/io2 only, same AZ, up to 16 Nitro instances (verify).
- Delete on termination default: root yes, extra volumes no.

## L. Scenarios (if → then, because)
- **If** you need a normal disk for an Amazon Elastic Compute Cloud (EC2) instance with no special needs, **then** use an Amazon Elastic Block Store (EBS) **gp3** volume, the general purpose SSD and the default choice. It gives a baseline of **3,000 IOPS** and **125 MiB/s** at any size (verify), and you can pay to raise IOPS and throughput separately from size. **This works because** gp3 is about **20% cheaper per GB** than the older **gp2**, and it does not tie speed to size or rely on burst credits, so performance is predictable.
- **If** a database needs more than **80,000 IOPS** (input/output operations per second) or **sub-millisecond latency**, **then** use **io2 Block Express**, the Provisioned IOPS SSD volume. It reaches up to **256,000 IOPS** and **4,000 MiB/s**, averages under **500 microseconds** latency, and has **99.999%** durability. **This works because** gp3 tops out at **80,000 IOPS**, while io2 is built for sustained high IOPS. The catch: you need a **Nitro-based** instance to reach the top numbers.
- **If** you need to stream big log files cheaply from a disk, **then** use **st1**, the Throughput Optimized HDD volume (up to **500 MiB/s**). **This works because** st1 is made for big **sequential** reads like logs, Kafka and data warehouses, and it is cheaper per MiB/s than SSD. It cannot be a boot volume.
- **If** you need the cheapest disk for data that is rarely read, **then** use **sc1**, the Cold HDD volume (up to **250 MiB/s**). **This works because** sc1 is the cheapest EBS type and is meant for infrequent access. Like st1, it cannot be a boot volume.
- **If** a volume must move to another Availability Zone (AZ), **then** take a **snapshot** (a point-in-time copy) and create a new volume from it in the target AZ. **This works because** a volume is tied to one AZ, but snapshots are **regional** and can be restored in any AZ of the Region.
- **If** a volume must be backed up **daily** and kept for **30 days**, **then** use an Amazon **Data Lifecycle Manager (DLM)** policy or an **AWS Backup** plan. DLM creates scheduled snapshots with a retention rule, selected by tag; AWS Backup is a central backup service for EBS and many other services. **This works because** AWS does **not** back up EBS volumes for you, and both tools take snapshots on schedule and expire old ones automatically.
- **If** you need disaster recovery (DR) in another Region, **then** **copy snapshots** to that Region, on a schedule with **Data Lifecycle Manager (DLM)** or **AWS Backup**. **This works because** a volume lives in one AZ and dies with it, but a snapshot copied to another Region lets you rebuild the volume there. Copying data across Regions has a data transfer cost.
- **If** you must encrypt an existing unencrypted volume, **then** take a **snapshot**, then create an encrypted volume from it (or **copy** the snapshot with encryption on and create the volume from the copy), and swap the new volume in. **This works because** you **cannot** encrypt a volume **in place**, but encryption with AWS Key Management Service (KMS) can be turned on when you create a volume or copy a snapshot.
- **If** all new volumes must be encrypted, **then** turn on **EBS encryption by default** in **each Region** (it is an account setting per Region), and add an Identity and Access Management (IAM) policy or Service Control Policy (SCP) that requires the **`ec2:Encrypted`** condition key. **This works because** with the default on, new volumes and snapshot copies are always encrypted, and the policy blocks anyone creating an unencrypted volume.
- **If** you share an encrypted snapshot with another AWS account, **then** encrypt it with a **customer managed** AWS Key Management Service (KMS) key and allow the other account to use that key. **This works because** snapshots encrypted with the default **`aws/ebs`** AWS managed key cannot be shared, so sharing fails. Public sharing of encrypted snapshots is never allowed.
- **If** a volume made from a snapshot is slow on its first reads, **then** **initialize** it (read all blocks with `fio` or `dd`) or turn on **Fast Snapshot Restore (FSR)** for that snapshot. **This works because** restored volumes **load lazily**: each block is fetched on first read. FSR makes volumes fully ready at creation, but it is billed **per hour per snapshot per AZ**.
- **If** many instances must read and write the same files, **then** use Amazon Elastic File System (EFS) (or Amazon FSx), not EBS. **This works because** an EBS volume normally attaches to **one instance** in one AZ, while EFS is a shared NFS file system for many instances.
- **If** a clustered application needs one shared disk, **then** use an **io2** (or io1) volume with **Multi-Attach** and a **cluster-aware file system**. Multi-Attach connects one volume to up to **16 Nitro** instances in the **same AZ** (verify). **This works because** only io1/io2 support Multi-Attach. The catch: the application must manage writes itself; normal ext4 or XFS is not suitable.
- **If** temporary scratch data needs the fastest disk and can be lost, **then** use **instance store**, the disk physically inside the host. **This works because** it is faster and free with the instance, but data is **lost** on stop or terminate, so use it only for temp data, shuffle and caches.
- **If** an admin deletes snapshots by mistake, **then** use a **Recycle Bin** retention rule. **This works because** Recycle Bin keeps deleted snapshots (and Amazon Machine Images, AMIs) for a **retention period**, so you can recover them before they are gone for good.
- **If** ransomware protection is required, **then** use **Snapshot Lock** and copy snapshots to **another account**. Snapshot Lock makes snapshots **immutable** (in **governance** or **compliance** mode), so they cannot be deleted. **This works because** locked snapshots survive an attacker with delete rights, and a copy in a separate account survives even if the first account is taken over.
- **If** costs are high from forgotten disks, **then** **delete unattached volumes** and old snapshots, and move snapshots you rarely restore to the **Snapshot Archive tier** (about **75% cheaper**, minimum **90 days**, restore takes **24–72 hours**) (verify). **This works because** unattached (available) volumes still cost money, since you pay for **provisioned size**. Trusted Advisor flags idle or unattached volumes.
- **If** a **gp2** volume slows down after a period of heavy use, **then** its **burst credits** ran out; move it to **gp3**. **This works because** gp2 bursts to **3,000 IOPS** using credits, and when **`BurstBalance`** hits **0** it drops to its baseline (**3 IOPS per GiB**). gp3 has no burst credits, so speed stays steady.
- **If** you need to grow a volume, **then** use **Elastic Volumes** to increase the size while it is attached and live, then **extend the partition and file system** inside the operating system. **This works because** Elastic Volumes changes size, type, IOPS and throughput without detaching, but the OS does not see new space by itself. After a change, wait about **6 hours** (verify) before changing that volume again.
- **If** you need to shrink a volume, **then** create a **smaller** volume, copy the data, and swap the volumes. **This works because** Elastic Volumes can only **increase** size, never shrink it.
- **If** a database needs an **application-consistent** snapshot, **then** **quiesce** it first (stop writes and flush), or use Volume Shadow Copy Service (VSS)-aware tools or **AWS Backup** with pre/post scripts. **This works because** snapshots are only **crash-consistent** by default, like pulling the power, so unflushed database writes could be missing.

## Verified from AWS docs on 2026-10-02
Volume types table, snapshots overview, encryption were read from current AWS pages. Not re-checked (verify): gp3 baseline values, Multi-Attach instance count, snapshot archive numbers, modification cooldown, io2 IOPS ratio, queue depth guidance.

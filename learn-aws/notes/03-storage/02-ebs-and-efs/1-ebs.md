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
- If you need a default disk for EC2 → gp3, because it is cheaper than gp2 and sets IOPS/throughput separately.
- If a database needs over 80,000 IOPS or sub-millisecond latency → io2 Block Express.
- If you need to stream big log files cheaply from a disk → st1.
- If you need the cheapest archive-like disk that is rarely read → sc1.
- If a volume must be moved to another AZ → snapshot, then create the volume in the target AZ.
- If a volume must be backed up daily and kept 30 days → Data Lifecycle Manager policy or AWS Backup plan.
- If you need DR in another Region → copy snapshots cross-Region (DLM or AWS Backup).
- If you must encrypt an existing unencrypted volume → snapshot, copy with encryption (or create volume from snapshot with encryption), swap volumes.
- If all new volumes must be encrypted → turn on EBS encryption by default for each Region (and SCP requiring `ec2:Encrypted`).
- If you share an encrypted snapshot with another account → encrypt with a customer managed key and share the key too.
- If a volume made from a snapshot is slow for the first reads → initialize it or use Fast Snapshot Restore.
- If many instances need to read and write the same files → EFS (or FSx), not EBS.
- If a clustered application needs a shared disk → io2 with Multi-Attach and a cluster-aware file system.
- If temporary scratch data needs the fastest disk and can be lost → instance store.
- If an admin deletes snapshots by mistake → Recycle Bin retention rule.
- If ransomware protection is required → Snapshot Lock + cross-account copy.
- If costs are high from forgotten disks → delete unattached volumes and old snapshots; use archive tier for old snapshots.
- If gp2 volume slows down after a period of heavy use → burst credits ran out; move to gp3.
- If you need to grow a volume → Elastic Volumes (modify size), then extend the file system.
- If you need to shrink a volume → create a smaller one and copy data; shrinking is not supported.
- If an application-consistent snapshot of a database is required → quiesce writes first, or use AWS Backup with app-consistent support.

## Verified from AWS docs on 2026-10-02
Volume types table, snapshots overview, encryption were read from current AWS pages. Not re-checked (verify): gp3 baseline values, Multi-Attach instance count, snapshot archive numbers, modification cooldown, io2 IOPS ratio, queue depth guidance.

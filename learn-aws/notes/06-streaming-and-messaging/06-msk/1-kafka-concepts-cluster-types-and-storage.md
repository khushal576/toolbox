# Amazon MSK – 1. Kafka concepts, cluster types and storage

Short notes. Each point is a fact you can be asked about.

## A. What MSK is
- Amazon MSK (Managed Streaming for Apache Kafka) = AWS runs open-source Apache Kafka for you. You use normal Kafka clients, APIs and tools.
- AWS handles broker hardware, patching, metadata nodes (ZooKeeper or KRaft controllers), failed broker replacement and Multi-AZ placement.
- You still own Kafka design: topics, partition count, replication factor, client settings, retention, consumer groups.
- MSK is Regional. A cluster lives in one VPC in one Region, with brokers spread across Availability Zones (AZs).
- Clients connect to "bootstrap brokers" (a list of broker DNS names and ports) and then talk directly to partition leaders.
- Three ways to run it: MSK Provisioned with Standard brokers, MSK Provisioned with Express brokers, and MSK Serverless.
- Extra features: MSK Connect (managed Kafka Connect), MSK Replicator (managed cluster-to-cluster copy), and MSK data delivery (topics into S3 / Iceberg tables, Express only).
- Pick MSK when: you need Kafka APIs, Kafka ecosystem tools (Kafka Connect, Kafka Streams, Debezium, MirrorMaker), long retention, or are moving an existing Kafka workload to AWS.
- Pick MSK when: you need very high throughput per cluster, log compaction, transactions / exactly-once, or many consumer groups reading the same data.
- Avoid MSK when: you want a fully AWS-native stream with no Kafka knowledge → Kinesis Data Streams is simpler.
- Avoid MSK when: you only need to land data in S3/Redshift/OpenSearch with no custom readers → Amazon Data Firehose.
- Avoid MSK when: you need a work queue where each message is deleted after one consumer handles it → SQS.
- Catch: "managed" does not mean "auto-sized" on Provisioned. You pick broker count, size and (Standard) storage, and you rebalance partitions.

## B. Kafka building blocks
- Broker = one Kafka server. It stores partitions on disk and serves produce and fetch requests.
- Cluster = a group of brokers that share metadata and replicate data between them.
- Topic = a named stream of records (for example `orders`). Producers write to a topic; consumers read from it.
- Partition = an ordered, append-only log. A topic is split into one or more partitions. Partitions are the unit of parallelism.
- Offset = the position number of a record inside one partition. Offsets grow by one per record and are never reused.
- Offsets only mean something inside one partition. Offset 100 in partition 0 has no relation to offset 100 in partition 1.
- Record = key (optional) + value + headers + timestamp. The key decides the partition when the default partitioner is used.
- Log segment = the files on disk that make up a partition. Old data is removed one whole segment at a time, never record by record.
- Replica = a copy of a partition on a broker. Replication factor (RF) = number of copies, including the leader.
- Leader = the one replica that takes all writes for a partition. By default it also serves reads.
- Follower = a replica that copies data from the leader. It can take over if the leader fails.
- ISR (in-sync replicas) = the leader plus followers that are fully caught up.
- A follower falls out of the ISR if it has not caught up for `replica.lag.time.max.ms` (MSK default 30,000 ms = 30 s).
- Only ISR members are normally allowed to become the new leader. This is what prevents data loss on failover.
- Controller = the broker/node that manages cluster metadata: which broker leads each partition, topic creation, ISR changes.
- `ActiveControllerCount` should be exactly 1 across the cluster. 0 or more than 1 means a metadata problem.
- Consumer group = a set of consumers sharing a group ID. Each partition is read by only one consumer in the group at a time.
- Different consumer groups read the same topic independently. This is Kafka's fan-out.
- Reading does not delete data. Records stay until retention or compaction removes them, so you can replay.
- Committed offsets for consumer groups are stored in the internal topic `__consumer_offsets`.
- MSK creates internal topics `__amazon_msk_canary` and `__amazon_msk_canary_state` for health checks. They are tiny and can't be deleted.

## C. ZooKeeper vs KRaft (metadata mode)
- Old Kafka stored metadata in a separate Apache ZooKeeper ensemble. New Kafka uses KRaft (Kafka Raft) controllers inside Kafka.
- On MSK, ZooKeeper nodes and KRaft controllers are both included at no extra cost and fully managed.
- MSK supports KRaft from Kafka 3.7.x. Kafka 3.9 is the last version with both ZooKeeper and KRaft. Kafka 4.x is KRaft only.
- KRaft raises the broker quota per cluster: 60 brokers for KRaft vs 30 for ZooKeeper (default, adjustable).
- Partitions per broker are the same in both modes. KRaft just allows more brokers, so more partitions per cluster.
- Existing ZooKeeper clusters can now be migrated in place to KRaft with `UpdateClusterKafkaVersion` (target version like `3.9.x.kraft`).
- ZooKeeper → KRaft migration needs: Kafka 3.9.x first, 3 AZs (Standard), no `kafka.t3.small`, ZooKeeper client access disabled, all clients using `--bootstrap-server`.
- Migration keeps the cluster available, moves no data, can take several hours, and cannot be reversed.
- The `--zookeeper` flag in Kafka tools is deprecated since 2.5 and removed in 3.0. Use `--bootstrap-server` for admin and ACL work.
- Trap: on ZooKeeper clusters, IAM access control does not protect ZooKeeper. Protect it with its own security group and TLS.

## D. Retention vs log compaction
- `cleanup.policy=delete` (default): whole old segments are deleted when they pass the time or size limit.
- Time limit: `retention.ms` (topic) or `log.retention.hours/minutes/ms` (cluster). Kafka default is 7 days (168 hours).
- Size limit: `retention.bytes` is per partition, not per topic. Default -1 = no size limit.
- Whichever limit is hit first (time or size) makes Kafka start removing inactive segments.
- Topic-level settings override cluster-level settings.
- Catch: the active (newest) segment is never deleted, so data can live longer than `retention.ms` until the segment rolls (`segment.ms`, `segment.bytes`).
- `cleanup.policy=compact`: Kafka keeps at least the latest record for each key and removes older records with the same key.
- Compaction is for "latest state per key" topics: customer profiles, config, CDC table snapshots, Kafka Connect internal topics.
- A record with a key and null value is a tombstone. After `delete.retention.ms` the key is removed fully.
- `compact,delete` together = keep latest per key, but also drop anything older than retention.
- Compaction needs keys. Records without keys can't be compacted.
- Trap: compaction is not instant. `min.compaction.lag.ms` and segment roll timing decide when old values disappear.
- Trap: tiered storage does not support compacted topics. MSK Serverless limits compacted partitions (120 per cluster by default).

## E. Cluster types at a glance
| Feature | Provisioned – Standard | Provisioned – Express | Serverless |
|---|---|---|---|
| You choose | Broker size, count, EBS storage | Broker size, count | Nothing (capacity is automatic) |
| Instance families | kafka.t3, kafka.m5, kafka.m7g | express.m7g only | Hidden |
| AZs | 2 or 3 | 3 only | Multi-AZ, managed |
| Storage | EBS you size; tiered storage optional | Managed, pay per GB, virtually unlimited | Managed, pay per GB |
| Auth | IAM, SASL/SCRAM, mTLS, unauthenticated | IAM, SASL/SCRAM, mTLS, unauthenticated | IAM only |
| Kafka ACLs | Yes | Yes | No |
| Broker config | Most configurable | Mostly fixed best-practice values | Broker config fixed; few topic configs |
| Public access | Yes (after create) | Yes (after create) | No **(verify)** |
| Best for | Full control, tuning, tiered storage | High throughput, fast scaling, less ops | Spiky or unknown load, small/medium scale |

- You can't switch an existing cluster between Standard and Express. Create a new cluster and migrate.
- You can't switch Provisioned to Serverless or back. Migrate with MSK Replicator or MirrorMaker 2.

## F. Standard brokers
- Sizes: `kafka.t3.small`; `kafka.m5.large` to `kafka.m5.24xlarge`; `kafka.m7g.large` to `kafka.m7g.16xlarge`.
- M7g = AWS Graviton (Arm). Better price-performance and less power than M5. Supported on Kafka 2.8.2, 3.3.2 and later.
- T3 brokers use CPU burst credits. Use them for dev/test or low, spiky throughput. Watch `CPUCreditBalance`.
- T3 limitations: no tiered storage, no multi-VPC private connectivity, no MSK Replicator, no ZooKeeper→KRaft migration, 4 new IAM connections/s per broker.
- All brokers in a cluster are the same size.
- Recommended partitions per Standard broker (leaders + followers): t3.small 300; m5/m7g large and xlarge 1,000; 2xlarge 2,000; 4xlarge and larger 4,000.
- "Maximum that support update operations": t3.small 300; large/xlarge 1,500; 2xlarge 3,000; 4xlarge+ 6,000.
- Above the max, MSK blocks: configuration updates, moving to a smaller broker size, and associating SCRAM secrets.
- Throughput example from AWS: m7g.16xlarge Standard broker ≈ 153.8 MBps safe write rate (vs 500 MBps on Express of the same size).
- Broker throughput bottlenecks: EBS volume throughput, EC2-to-EBS network bandwidth, and EC2 egress (grows with number of consumer groups).
- Maintenance: AWS patches Standard brokers with rolling restarts, one broker at a time (operation type `SECURITY_PATCHING`).
- During patching expect brief client disconnects, p99 latency spikes up to ~2 seconds, and `UnderReplicatedPartitions` rising temporarily.

## G. Express brokers
- Express brokers = MSK Provisioned broker type with AWS-managed storage and pre-set best-practice configs.
- Up to 3x more throughput per broker than Standard, up to 20x faster scaling, and up to 90% faster recovery (AWS numbers).
- No storage to provision or monitor. Storage is pay-as-you-go and virtually unlimited.
- Only 3-AZ clusters. Only `express.m7g` sizes (large up to 16xlarge).
- Supported Kafka versions (per docs): 3.6, 3.8, 3.9, 4.2. KRaft mode from 3.9. Kafka 4.2 is currently Express only.
- Replication factor is always 3 and `min.insync.replicas` is always 2 (read-only). `unclean.leader.election.enable` is fixed at false.
- Editable: retention, cleanup policy, compression, `message.max.bytes`, `auto.create.topics.enable`, `allow.everyone.if.no.acl.found`, timestamp settings and more.
- Express enforces client throughput quotas so client traffic can't starve replication and repairs.
- Sustained (recommended) ingress per broker: large 15.6, xlarge 31.2, 2xlarge 62.5, 4xlarge 124.9, 8xlarge 250, 12xlarge 375, 16xlarge 500 MBps.
- Sustained egress per broker is 2x ingress: large 31.2 up to 16xlarge 1,000 MBps.
- Hard throttle (maximum quota) is about 1.5x sustained ingress (for example 23.4 MBps on large, 750 MBps on 16xlarge). Above it, reads/writes are throttled.
- Per-partition throughput on Express: max 15 MB/s.
- Express partitions per broker: recommended 1,000 (large, xlarge) up to 20,000 (16xlarge); hard max 1,500 (large) up to 32,000 (16xlarge).
- Sizing rule: divide needed ingress and egress by the per-broker sustained numbers. Example: 45 MBps in / 90 MBps out → 3 × express.m7g.large.
- No maintenance windows. MSK reboots single brokers spread across the month; operations show as broker maintenance.
- Intelligent rebalancing: on by default for new Express clusters. MSK moves partitions automatically on scale up/down and when load is skewed.
- Intelligent rebalancing is free, finishes scaling within ~30 minutes, and supports up to 20,000 partitions per broker.
- Since June 18, 2026 it is available on all Express clusters. Clusters created before Nov 20, 2025 have it in Paused state until you set it Active.
- Trap: while intelligent rebalancing is Active you can't use Cruise Control or partition reassignment APIs. Pause it first.
- Express does not fully support the Kafka Streams API yet, and does not support KIP-932 (Queues for Kafka) yet.
- Express can't use tiered storage (storage is already managed) and has no EBS metrics like `KafkaDataLogsDiskUsed`; use `StorageUsed`.

## H. MSK Serverless
- Serverless = no brokers to size. AWS scales capacity and manages partition placement. You pay for throughput and storage.
- Authentication is IAM access control only. No SASL/SCRAM, no mTLS, no unauthenticated, no Kafka ACLs.
- Cluster limits (defaults): 200 MBps ingress, 400 MBps egress per cluster.
- Per-partition limits: 5 MBps ingress, 10 MBps egress.
- Max 2,400 leader partitions for non-compacted topics, 120 for compacted topics (raise with a support case).
- Max partition size for compacted topics: 250 GB.
- Max 3,000 client connections and 100 connection attempts per second per cluster.
- Max message size 8 MiB (topic `max.message.bytes` default ~1 MB, max 8388608).
- Max 500 consumer groups per cluster. Max 15,000 requests per second. Max fetch 55 MB per request.
- Max 5 client VPCs per cluster. Give at least 2 subnets per VPC so clients survive an AZ outage.
- Retention: topic default 7 days and 250 GiB per partition; both can be set to -1 (unlimited).
- Editable topic configs only: `cleanup.policy` (only at creation), `compression.type`, `max.message.bytes`, `message.timestamp.*`, `retention.bytes`, `retention.ms`.
- You can't change broker configs or `segment.bytes`. Kafka Streams internal topics may need adjusted settings.
- Over a limit → throttling (slowdown with throttle time in the response), not data loss. Too many connections → connections closed.
- Creating a Serverless cluster creates VPC endpoints, so the creator needs `ec2:CreateVpcEndpoint`.
- Serverless monitoring is DEFAULT level only, per topic and per consumer group (no per-broker metrics, because brokers are hidden).
- Pick Serverless when: load is unpredictable, under ~200 MBps, team has little Kafka ops skill, and IAM auth is fine.
- Avoid Serverless when: you need SCRAM/mTLS/ACLs, broker configs, more than 2,400 partitions, very high throughput, or DMS as a producer.

## I. Multi-AZ: 2 AZs vs 3 AZs (Standard brokers)
- Broker count must be a multiple of the number of AZs (for example 3, 6, 9 for 3 AZs).
- MSK places brokers evenly across AZs and sets `broker.rack` to the AZ ID, so Kafka spreads replicas across AZs.
- 3 AZs is the AWS recommendation for production.
- Default `default.replication.factor`: 3 for 3-AZ clusters, 2 for 2-AZ clusters.
- Default `min.insync.replicas`: 2 for 3-AZ clusters, 1 for 2-AZ clusters.
- With RF=2 / minISR=1, a write can be acknowledged by only one broker. Losing that broker before the follower catches up loses data.
- RF=1 can cause offline partitions during rolling updates. RF=2 may lead to data loss. Use RF=3.
- Set minISR = RF − 1 at most. minISR = RF blocks producers (acks=all) whenever one broker is restarting.
- Trap: 2-AZ is cheaper but an AZ outage halves your brokers, and ZooKeeper→KRaft migration requires 3 AZs.

## J. Standard broker storage (EBS)
- Each Standard broker has its own EBS volume for Kafka data. Size per broker: 1 GiB minimum, 16,384 GiB (16 TiB) maximum.
- Total cluster storage = per-broker size × broker count, but each byte is stored RF times.
- Storage price is per GB-month of provisioned storage, used or not.
- You can increase storage but never decrease it. To shrink, migrate to a new cluster.
- After any storage increase there is a cool-down of at least 6 hours (up to over 24 hours) before the next increase.
- The extra space is usable right away and volumes stay online during the change.
- Storage auto scaling uses Application Auto Scaling with a target-tracking policy.
- Auto scaling target utilization: 10%–80% of current capacity (AWS suggests 50–60%). Max capacity up to 16 TiB per broker.
- Each auto scaling step adds the larger of 10 GiB or 10% of current storage. MSK checks utilization every minute.
- Auto scaling never scales in. It is not supported in a few Regions (Osaka, Cape Town, Malaysia).
- Catch: the auto scaling CloudWatch alarm survives cluster deletion. Remove the policy before deleting the cluster.
- Alarm on `KafkaDataLogsDiskUsed` at 85%: then grow storage, cut retention, or delete unused topics.
- Full disk = broker can't accept writes; partitions can go offline. Disk is the most common Standard-broker outage cause.
- Default EBS throughput baseline is 250 MiB/s per broker volume.
- Provisioned storage throughput: only for `kafka.m5.4xlarge`+ or `kafka.m7g.2xlarge`+ and volumes ≥ 10 GiB.
- Max provisioned throughput: m5.4xlarge 593, m5.8xlarge 850, m5.12xlarge+ 1,000; m7g.2xlarge 312.5, m7g.4xlarge 625, m7g.8xlarge+ 1,000 MiB/s.
- Also raise `num.replica.fetchers` (default 2) when you raise storage throughput, or you will not see the gain.
- A throughput change can take up to 24 hours to apply (~6 hours for a busy 1 TiB volume). Performance never drops below the old level meanwhile.

## K. Tiered storage (Standard brokers only)
- Tiered storage = a low-cost, AWS-managed second tier. Older segments move off EBS; the cluster still serves them through Kafka APIs.
- It follows Kafka KIP-405. Clients need no changes to read tiered data.
- Needs Kafka 3.6.0+ (or the old 2.8.2.tiered). Provisioned only, not t3.small, not in GovCloud.
- Turn it on per topic with `remote.storage.enable=true` (and the cluster must have tiered storage enabled).
- `local.retention.ms` / `local.retention.bytes` = how long data stays on the EBS (hot) tier.
- `retention.ms` / `retention.bytes` = total life of the data across both tiers. Local retention must be smaller than total retention.
- `retention.ms` is mandatory for tiered topics, with a minimum of 3 days in the low-cost tier.
- Default `local.retention.*` = -2, meaning "same as total retention" (data kept in both tiers and expires together).
- Tiered storage needs `cleanup.policy=delete`. Compacted topics are not supported, and you can't change the cleanup policy later.
- You can disable tiered storage per topic but not for the whole cluster. Once disabled for a topic, it can't be re-enabled.
- Kafka 3.9 can keep the tiered data when you disable tiering on a topic.
- First bytes read from the low-cost tier have higher latency; sequential reads after that are close to primary-tier speed.
- Partition reassignment is faster because tiered data is not copied between brokers.
- Billing: GB-month in the low-cost tier plus a per-GB retrieval charge when consumers read it.
- Default `log.segment.bytes` drops to 128 MiB on tiered clusters (vs 1 GiB) so segments tier sooner. Minimum segment 48 MiB or 10 minutes.
- Trap: clients with `isolation.level=read_committed` reading the remote tier can have issues; use `read_uncommitted` unless you really use transactions.
- Use case: keep 30 days hot on EBS and 1 year in tiered storage for replay, without adding brokers.

## L. Configurations
- An MSK configuration = a named set of `server.properties` values with numbered revisions. Apply it to one or many clusters.
- If you give no configuration, MSK uses its default configuration (values differ from plain Kafka defaults in places).
- Quotas: 100 configurations and 50 revisions per configuration per account (default).
- Static properties need a rolling broker restart when changed; dynamic ones apply without restart (`kafka-configs.sh`).
- MSK default: `auto.create.topics.enable=false`. DMS and some apps that expect auto-create need it set to true.
- MSK default: `num.partitions=1` for auto-created topics.
- MSK default: `allow.everyone.if.no.acl.found=true` (any principal can use a resource that has no ACL).
- MSK default: `unclean.leader.election.enable=true` on non-tiered Standard clusters, false on tiered clusters and Express.
- Unclean leader election lets an out-of-sync replica become leader. It brings the partition back faster but can lose data. Set false for durability.
- With transactions, high `HeapMemoryAfterGC` can be cut by lowering `transactional.id.expiration.ms` from 7 days to 1 day.

## M. Kafka versions and upgrades
- Currently supported on MSK (as of Nov 2026): 3.8.x, 3.9.x (recommended), 4.0.x, 4.1.x, 4.2.x (Express only).
- 3.6.0 reached end of support 2026-06-01 and 3.7.x on 2026-09-01.
- `.x` versions (3.7.x and later) get Kafka patch releases automatically without a version upgrade.
- MSK gives 3.9 extended support for at least two years from its release (it is the last ZooKeeper version).
- After a version's end of support date, MSK auto-upgrades the cluster to the recommended version at any time, with no notice.
- Upgrades are in-place rolling updates (one broker at a time). Clients keep producing and consuming if RF/minISR/retries are right.
- Version downgrades are not supported.
- During an upgrade, broker size change or config update you can't start other cluster updates.
- Upgrades can be blocked if partitions per broker are above the documented max.
- Kafka 4.0: ZooKeeper removed, Java 17 for brokers/tools, new consumer rebalance protocol (KIP-848) GA.
- Kafka 4.1: Queues for Kafka (KIP-932) preview, Eligible Leader Replicas (ELR) on by default, Streams rebalance protocol early access.
- Kafka 3.x clients default to `acks=all` and `enable.idempotence=true` (older clients defaulted to `acks=1` and no idempotence).
- Client upgrades are not bound to cluster end-of-support dates. Kafka keeps old and new clients compatible both ways.

## N. Troubleshooting: symptom → cause → fix
| Symptom | Likely cause | Fix |
|---|---|---|
| Partitions offline, replicas out of sync | Disk full on Standard broker | Raise storage / auto scaling, cut retention, delete topics |
| Can't grow storage again | 6-hour+ cool-down after last increase | Wait; size ahead; use tiered storage or Express |
| Storage bill too high but disk mostly empty | Over-provisioned EBS can't shrink | Migrate to smaller cluster, or Express / tiered storage |
| Producers fail during patching with `NotEnoughReplicas` | minISR equals RF | Set minISR = RF − 1 (2 for RF 3) |
| Partition offline during rolling update | RF = 1 | Recreate topic with RF 3 |
| Data loss after broker failure | Unclean leader election true, or RF 2 / minISR 1 | `unclean.leader.election.enable=false`, RF 3, minISR 2, acks=all |
| Config update or broker downsize blocked | Partitions per broker above max | Reduce partitions or add brokers first |
| Provisioned throughput shows no gain | `num.replica.fetchers` still 2, or change not yet applied | Raise fetchers; wait up to 24 h |
| Can't use Cruise Control on Express | Intelligent rebalancing Active | Pause intelligent rebalancing |
| Can't migrate to KRaft | Not on 3.9.x, 2 AZs, t3.small, ZooKeeper access on, or public access + open monitoring | Fix each prerequisite |
| Serverless producer slowed down | Hit 200 MBps cluster or 5 MBps partition limit | Add partitions, spread keys, or move to Provisioned |
| Cluster auto-upgraded without warning | Version passed end of support | Upgrade before end-of-support dates |

## Scenarios: "If X → Y, because Z"
- **If** a team needs **Kafka Connect**, **Kafka Streams** and its existing Kafka clients on AWS, **then** use **Amazon Managed Streaming for Apache Kafka (MSK)**, where AWS runs open-source Apache Kafka for you. **This works because** MSK uses the normal Kafka clients, APIs and tools, so code and ecosystem tools work unchanged. AWS handles broker hardware, patching and failed broker replacement, but you still own topic, partition and retention design.
- **If** load is unpredictable, stays under **200 MBps**, and **Identity and Access Management (IAM)** authentication is acceptable, **then** use **MSK Serverless**, where there are no brokers to size. **This works because** AWS scales capacity and manages partition placement, and you pay for throughput and storage. The catch: Serverless allows **IAM auth only** (no SASL/SCRAM, mutual TLS or Kafka ACLs) and has limits such as **2,400** partitions and **5 MBps** ingress per partition.
- **If** the security team requires **SASL/SCRAM** (username and password) or **mutual TLS (mTLS)** (client certificates), **then** use **MSK Provisioned** (Standard or Express brokers). **This works because** Provisioned supports IAM, SASL/SCRAM, mTLS and unauthenticated access, while **MSK Serverless** supports **IAM access control only**.
- **If** a workload needs **400 MBps** of writes with minimal operations work, **then** use **MSK Provisioned with Express brokers**, a broker type with AWS-managed storage and pre-set best-practice configs. **This works because** each Express broker gives up to **3x** the throughput of a Standard broker, scales up to **20x** faster, and has no storage to provision or monitor. Size it by dividing the needed ingress and egress by the sustained per-broker numbers. Express clusters always use **3 Availability Zones (AZs)**.
- **If** you must keep **1 year** of data for replay without adding brokers, **then** use **Standard brokers with tiered storage**, or **Express brokers**. Tiered storage is a low-cost, AWS-managed second tier: older log segments move off the broker's **Elastic Block Store (EBS)** disk but are still read through normal Kafka APIs. **This works because** you keep, for example, **30 days** hot on EBS and the rest in the cheap tier, while Express storage is already managed and virtually unlimited. The catch: tiered topics need `cleanup.policy=delete`, and the first bytes read from the cheap tier are slower.
- **If** a tiered-storage topic must also be **compacted** (keep only the latest record per key), **then** it is **not possible**. **This works because** tiered storage only supports `cleanup.policy=delete`, and the cleanup policy of a tiered topic can't be changed later. Use a non-tiered topic for compaction.
- **If** a production cluster has replication factor (**RF**) **3** and `min.insync.replicas` (**minISR**) **3**, **then** set **minISR to 2**. minISR is how many in-sync copies must have a write before an `acks=all` producer gets success. **This works because** with minISR equal to RF, one broker restarting (for patching or an upgrade) blocks all `acks=all` writes with `NotEnoughReplicas`. The rule is minISR = RF − 1 at most.
- **If** a **2-AZ** cluster uses MSK defaults, **then** it gets **RF 2** and **minISR 1**, so move to **3 Availability Zones (AZs)** with **RF 3** and **minISR 2**. **This works because** with RF 2 / minISR 1 a write can be acknowledged by only one broker, and losing that broker before the follower catches up loses data. 3 AZs is also the AWS recommendation for production, and a 2-AZ cluster loses half its brokers in an AZ outage.
- **If** durability matters more than availability on a **Standard, non-tiered** cluster, **then** set `unclean.leader.election.enable=false`. Unclean leader election lets an out-of-sync replica become leader. **This works because** MSK defaults it to **true** on non-tiered Standard clusters, which brings partitions back faster but can lose data. Tiered clusters and Express already have it false.
- **If** `KafkaDataLogsDiskUsed` passes **85%** on a Standard broker, **then** grow storage, shorten retention, or delete unused topics. **This works because** a full disk means the broker can't accept writes and partitions can go offline; disk is the most common Standard-broker outage cause.
- **If** the team increased storage an hour ago and needs more now, **then** they must **wait** for the cool-down. **This works because** after any storage increase MSK enforces a cool-down of at least **6 hours** (up to over **24 hours**) before the next increase. Size ahead, or use tiered storage or Express brokers to avoid this.
- **If** Elastic Block Store (EBS) storage was oversized and must shrink, **then** **migrate to a new cluster** with smaller storage. **This works because** MSK storage can be increased but **never decreased**, and you pay per GB-month of provisioned storage whether it is used or not.
- **If** an app needs **MSK Replicator**, **multi-VPC private connectivity** or **tiered storage**, **then** don't use `kafka.t3.small` brokers; use M5 or M7g. **This works because** T3 brokers don't support those features (nor ZooKeeper→KRaft migration), and they run on CPU burst credits meant for dev/test or low, spiky load.
- **If** a cluster has **7,000** partition replicas per `kafka.m7g.4xlarge` broker, **then** **add brokers** (or reduce partitions) before updating the configuration. **This works because** **6,000** is the maximum per 4xlarge+ broker that still allows update operations. Above it, MSK blocks configuration updates, moving to a smaller broker size, and associating SCRAM secrets. The recommended level is **4,000**.
- **If** a **ZooKeeper** cluster must move to **KRaft** (Kafka's built-in metadata controllers), **then** upgrade to Kafka **3.9.x** first, meet the prerequisites, and migrate in place with `UpdateClusterKafkaVersion`. **This works because** migration only starts from 3.9.x. Prerequisites: **3 AZs**, no `kafka.t3.small`, ZooKeeper client access disabled, and all clients using `--bootstrap-server`. Migration keeps the cluster available and moves no data, but can take hours and **cannot be reversed**.
- **If** a team wants Kafka **4.2**, **then** use **Express brokers**. **This works because** Kafka 4.2 is currently supported on **Express only**.
- **If** a cluster runs Kafka **3.7.x** today (**Nov 2026**), **then** upgrade now with an in-place rolling upgrade. **This works because** 3.7.x reached end of support on **2026-09-01**, and after that date MSK can auto-upgrade the cluster to the recommended version at any time, with no notice. Downgrades are not supported.
- **If** a Standard `kafka.m5.4xlarge` cluster is limited by disk throughput, **then** enable **provisioned storage throughput** and also raise `num.replica.fetchers` (default **2**). **This works because** the default EBS baseline is **250 MiB/s** per broker volume, and provisioned throughput raises it (up to **593 MiB/s** on m5.4xlarge). Without more replica fetchers you won't see the gain, and the change can take up to **24 hours** to apply.
- **If** a `kafka.m5.2xlarge` cluster needs provisioned storage throughput, **then** scale to **m5.4xlarge or larger** first. **This works because** provisioned throughput is only for `kafka.m5.4xlarge`+ or `kafka.m7g.2xlarge`+ with volumes of at least **10 GiB**.
- **If** you want an existing Standard cluster to become Express, **then** build a **new Express cluster** and migrate the data. **This works because** the broker type can't be switched on an existing cluster. The same is true between Provisioned and Serverless, where MSK Replicator or MirrorMaker 2 can do the copy.
- **If** an Express cluster scales out and partitions must move automatically, **then** rely on **intelligent rebalancing**. **This works because** it is on by default for new Express clusters, is free, and moves partitions on scale up/down and when load is skewed, finishing within about **30 minutes** with no third-party tools. The catch: while it is Active you can't use Cruise Control or partition reassignment APIs, and clusters created before **Nov 20, 2025** start with it Paused.
- **If** a **Kafka Streams** app must run on Express brokers, **then** test it carefully first. **This works because** Express does not fully support the Kafka Streams API yet.
- **If** a topic must always hold the **latest value per customer ID**, **then** use a **compacted topic** (`cleanup.policy=compact`) with the customer ID as the record key. **This works because** compaction keeps at least the latest record for each key and removes older records with the same key. Compaction needs keys, and it is not instant: old values disappear later, depending on `min.compaction.lag.ms` and segment roll timing.

Verified from AWS docs on 2026-11-02 (MSK Developer Guide: broker types, Express brokers, Express read-only/read-write configs, broker sizes, Standard/Express best practices, quotas, Serverless and Serverless config, storage scaling and auto scaling, provisioned throughput, tiered storage and topic-level guidelines, default configuration, metadata management, ZooKeeper-to-KRaft migration, supported versions, version support and upgrades, patching, intelligent rebalancing, encryption).
Unconfirmed (verify): public access not available on Serverless; Express hard-throttle ratio stated as "about 1.5x" (table values confirmed); tiered storage not available on Express (inferred from managed storage); `kafka-configs` dynamic vs static split per property; Kafka default retention 7 days applying unchanged on Express.

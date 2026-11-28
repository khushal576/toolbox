# Amazon MSK – 4. Monitoring, scaling, cost, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. CloudWatch monitoring levels (Provisioned)
- MSK pushes metrics to CloudWatch every 1 minute in the `AWS/Kafka` namespace.
- Four levels: `DEFAULT`, `PER_BROKER`, `PER_TOPIC_PER_BROKER`, `PER_TOPIC_PER_PARTITION`.
- Only `DEFAULT` metrics are free. Higher levels add more metrics and you pay CloudWatch custom-metric prices.
- Each level includes all metrics of the levels below it.
- `DEFAULT`: cluster and broker health (CPU, disk, memory, URP, controller count, bytes in/out, partition counts, topic-level consumer lag).
- `PER_BROKER`: request latencies, throttling, network allowance exceeded, IAM connection metrics, EBS volume metrics, tiered storage metrics.
- `PER_TOPIC_PER_BROKER`: per-topic bytes/messages per broker and per-topic tiered storage metrics.
- `PER_TOPIC_PER_PARTITION`: partition-level lag (`OffsetLag`, `EstimatedTimeLag`, `RollingEstimatedTimeLag`).
- Change the level any time with `UpdateMonitoring`; no restart.
- Cost trap: `PER_TOPIC_PER_PARTITION` on a cluster with thousands of partitions creates thousands of billable metrics.
- With Kafka 2.4.1+, `PER_TOPIC_PER_BROKER` metrics only appear after their value is non-zero once.
- Very high partition or consumer-group counts can make metrics go missing in CloudWatch and Prometheus.
- Serverless has DEFAULT-level metrics only, per cluster, topic and consumer group (`BytesInPerSec`, `BytesOutPerSec`, `MessagesInPerSec`, `MaxOffsetLag`, `SumOffsetLag`, `EstimatedMaxTimeLag`, `ClientConnectionCount`).

## B. Key metrics and alarm values
| Metric | Level | Healthy value / alarm |
|---|---|---|
| `ActiveControllerCount` | DEFAULT (cluster) | Sum must be exactly 1 |
| `OfflinePartitionsCount` | DEFAULT (cluster) | Must be 0; any value = partitions unavailable |
| `UnderReplicatedPartitions` (URP) | DEFAULT (broker) | 0; short spikes OK during patching |
| `UnderMinIsrPartitionCount` | DEFAULT (broker) | 0; above 0 = acks=all writes fail for those partitions |
| `KafkaDataLogsDiskUsed` | DEFAULT (broker, Standard) | Alarm at 85% |
| `CpuUser` + `CpuSystem` | DEFAULT (broker) | Keep under 60% (metric math) |
| `HeapMemoryAfterGC` | DEFAULT (broker) | Alarm above 60% |
| `CPUCreditBalance` | DEFAULT (t3) | Falling to 0 = throttled CPU |
| `ClientConnectionCount` | DEFAULT | Near 3,000 per broker with IAM = limit |
| `StorageUsed` | DEFAULT (Express, cluster) | Tracks managed storage (and bill) |
| `MaxOffsetLag`, `SumOffsetLag`, `EstimatedMaxTimeLag` | DEFAULT (group, topic) | Growing = consumers falling behind |

- `MemoryUsed` high / `MemoryFree` low is normal. Kafka uses memory for page cache. Watch `HeapMemoryAfterGC` instead.
- `CpuIdle` is not always 100 − user − system; iowait, irq, softirq and steal also count.
- `UnderReplicatedPartitions` spiky = cluster too small for traffic. Constantly above 0 even when quiet = ACLs blocking broker replication, or a failing broker.
- `OfflinePartitionsCount` > 0 often follows a full disk, RF 1 topics, or unclean election disabled with all ISR down.
- `LeaderCount` and `PartitionCount` per broker show imbalance. Uneven CPU across brokers = poor partition spread.
- `UserPartitionExists` = 1 means the broker still holds user partitions (must be 0 before removing that broker).
- `GlobalPartitionCount` counts partitions without replicas; summed `PartitionCount` includes replicas.
- `BytesInPerSec` / `BytesOutPerSec` per broker and topic show throughput and hot spots.
- `ProduceTotalTimeMsMean` and fetch `TotalTimeMs` metrics show latency; they rise with CPU.
- Throttling metrics (`ProduceThrottleTime`, `FetchThrottleTime`, `RequestThrottleTime`) show client quotas being hit (common on Express).
- `BwInAllowanceExceeded`, `BwOutAllowanceExceeded`, `PpsAllowanceExceeded`, `ConntrackAllowanceExceeded` = EC2 network limits hit → bigger broker.
- `TrafficShaping` (DEFAULT) is the high-level signal for those network limits.
- `VolumeReadBytes`, `VolumeWriteBytes`, `VolumeQueueLength` (PER_BROKER) show EBS saturation.
- `RemoteCopyLagBytes` (tiered) growing = data not moving to tiered storage fast enough.
- `RemoteLogSizeBytes` = bytes in the tiered storage tier (Kafka 3.7.x+).
- `KafkaFileDescriptorsUsagePercent` and `KafkaMemoryMappedFilesUsagePercent` (Standard) should stay below 80%.
- `IAMTooManyConnections` > 0 = more than 100 new IAM connections per second.
- `ZooKeeperSessionState` = 1.0 means connected (ZooKeeper clusters only).
- Express intelligent rebalancing: `RebalanceInProgress` (1 while moving) and `UnderProvisioned` (add brokers or scale up).
- Consumer lag metrics need STABLE/EMPTY groups, committed offsets, ASCII names and no `:` in the group name.
- Use CloudWatch alarms → SNS for notifications, or EventBridge/Lambda for automated actions.
- Express brokers have no disk metrics (`KafkaDataLogsDiskUsed`, `RootDiskUsed`) because storage is managed; watch `StorageUsed` and throttling instead.
- Consumer lag metrics on Express use dimensions Consumer Group + Topic (no Broker ID).
- `PerSec` metrics are published once per minute; the 1-minute Sum statistic equals the per-second value.
- For cluster-wide CPU use metric math: average of (`CpuUser` + `CpuSystem`) across brokers, plus a per-broker max to catch hot brokers.

## C. Open monitoring with Prometheus and logs
- Open monitoring exposes JMX Exporter (broker metrics) and Node Exporter (host metrics) on the brokers for Prometheus to scrape.
- Free from MSK; you pay cross-AZ data transfer for scraping.
- Works with Amazon Managed Service for Prometheus (remote write) and tools like Datadog, New Relic, Lenses, Sumo Logic.
- AWS suggests a scrape interval of 60 s or more; shorter intervals raise broker CPU.
- KRaft-mode and Express clusters can't have open monitoring and public access both on.
- KRaft clusters created on 4.1+ (or migrated from ZooKeeper) expose no controller endpoints; scrape brokers only and use `ActiveControllerCount`.
- Prometheus metrics are the input for Cruise Control.
- Broker logs (to CloudWatch Logs, S3, Firehose) help debug client errors; query them with Logs Insights or Athena (S3).
- MSK Connect metrics (`CpuUtilization`, `ErroredTaskCount`, `RunningTaskCount`, `WorkerCount`) are free under `ConnectorName`, kept 15 months.
- MSK Replicator metrics (`ReplicationLatency`, `MessageLag`) are in the target Region.

## D. Partition rebalancing and Cruise Control
- Kafka does not move existing partitions to new brokers by itself. After adding brokers, new brokers sit empty until you reassign.
- Tools: `kafka-reassign-partitions.sh`, LinkedIn Cruise Control, or (Express) intelligent rebalancing.
- AWS guidance: reassign at most 10 partitions per `kafka-reassign-partitions` call on Standard, 20 on Express.
- Use `--throttle` (bytes/s) on reassignment so replication traffic doesn't starve clients.
- Reassignment copies data between brokers, so it adds CPU, network and disk load. AWS advises against it above ~70% CPU.
- Tiered storage speeds reassignment because remote data isn't copied.
- Cruise Control: open-source, runs on your EC2, reads Prometheus metrics, proposes and runs rebalances, detects anomalies.
- Cruise Control on KRaft/Express must run without ZooKeeper; Express needs Cruise Control 2.5.60+ and a huge `DISK` capacity value.
- Cruise Control concurrency: `num.concurrent.partition.movements.per.broker` limits moves at once.
- AWS provides a CloudFormation template that deploys Cruise Control + Prometheus for MSK.
- Express intelligent rebalancing replaces Cruise Control. Pause it before using third-party rebalancers.
- `auto.leader.rebalance.enable=true` only moves leadership back to preferred replicas; it doesn't move data.

## E. Scaling MSK Provisioned
- Scale up (vertical): `UpdateBrokerType` changes all brokers' size in a rolling update. No partition moves needed.
- A size change takes about 10–15 minutes per broker (Standard). Clients keep working if RF/minISR/retries are right.
- Allowed Standard size moves: M5 or T3 → M7g, T3 → M5, M7g → M5. Can't go to a smaller size (for example M7g.large → T3.small).
- Can't downsize when partitions per broker exceed the max for the smaller size.
- Scale out (horizontal): `UpdateBrokerCount` adds brokers. Target count must be a multiple of the AZ count.
- New brokers get no partitions until you reassign or create new topics. Add partitions to high-traffic unkeyed topics to use them.
- AWS order of options when CPU > 60%: 1) bigger broker size, 2) add brokers + add partitions to unkeyed topics, 3) add brokers + reassign partitions.
- Scale in: remove brokers (Kafka 2.8.1+, M5/M7g, KRaft too). First move all user partitions off them; `UserPartitionExists` must show 0.
- Remove one broker per AZ in each operation (for example 3 brokers in a 3-AZ cluster).
- Express scale out/in is up to 20x faster, and intelligent rebalancing moves partitions automatically in one operation.
- Storage (Standard): scale up only, manual or auto scaling, 6-hour+ cool-down, never down.
- Storage throughput (Standard, large brokers): provisioned throughput up to 1,000 MiB/s.
- Serverless scales itself up to its quotas (200 MBps in / 400 MBps out per cluster by default).
- MSK Connect scales by workers (autoscaled mode) and by MCUs per worker.
- Lambda ESM scales up to one concurrent batch per partition.
- Broker reboot (`RebootBroker`) is supported on Standard and Express to test client failover.
- Only one cluster update runs at a time. Wait for `UPDATE_COMPLETE` (see `DescribeClusterOperation` / `ListClusterOperations`) before the next.
- Every update API needs the cluster's current version string (not a simple number) to avoid conflicting changes.
- Always use MSK APIs to add brokers. Brokers added outside MSK (for example via ZooKeeper commands) are not part of the cluster and can cause data loss.
- Scale test: reboot a broker under peak load to confirm clients fail over before a real event.

## F. Pricing (US East N. Virginia examples, Nov 2026)
- Standard brokers: broker instance-hours, for example `kafka.m5.large` $0.21/h, `kafka.m7g.large` $0.204/h.
- Standard storage: $0.10 per GB-month of provisioned EBS (per broker, whether used or not).
- Provisioned storage throughput: $0.08 per MB/s-month above the baseline.
- Tiered storage: $0.06 per GB-month plus $0.0015 per GB read from the tier.
- Express brokers: instance-hours (for example `express.m7g.large` $0.408/h) + $0.01 per GB written + $0.10 per GB-month storage used.
- Express storage bills only what is stored (after replication handled by MSK) **(verify whether priced on single copy)**.
- Serverless: $0.75 per cluster-hour + $0.0015 per partition-hour + $0.10 per GB in + $0.05 per GB out + $0.10 per GB-month storage.
- MSK Connect: $0.11 per MCU-hour.
- MSK Replicator: $0.30 per Replicator-hour + $0.08 per GB replicated + standard cross-Region data transfer.
- MSK data delivery: $10 per TB to S3 Tables (Iceberg), $8 per TB to S3 buckets, plus S3 costs.
- Multi-VPC private connectivity: about $0.0225 per hour per authentication scheme + $0.006 per GB processed **(verify unit)**.
- No charge for data replicated between brokers or between brokers and metadata nodes.
- You do pay normal data transfer for client traffic, for example cross-AZ traffic between clients and brokers in other AZs.
- KRaft controllers and ZooKeeper nodes are free.
- Public access has no MSK fee; data transfer out and public IPv4 charges apply.
- Open monitoring is free; DEFAULT CloudWatch metrics are free; higher levels cost CloudWatch fees.
- Lambda provisioned-mode ESMs cost Event Poller Unit hours; AWS Private CA (mTLS) costs per CA per month.
- No MSK free tier.
- Cost example (Standard): 3 × m7g.large for 730 h ≈ 3 × $0.204 × 730 ≈ $447/month before storage and data transfer.
- Each byte on Standard is stored RF times, so 1 TB of topic data with RF 3 needs about 3 TB of EBS across brokers.
- Serverless example: 1 cluster + 100 partitions ≈ $0.75 + $0.15 per hour (≈ $657/month) before per-GB charges.

## G. Cost optimization
- Right-size brokers: keep CPU under 60% but not at 10%. Graviton M7g is cheaper per performance than M5.
- Don't over-provision EBS: it can't shrink. Start right-sized with auto scaling at 50–60% target.
- Move long retention to tiered storage instead of adding brokers or EBS.
- Express can be cheaper at high throughput: fewer brokers and no idle storage.
- Serverless is cheap for small/spiky loads, but partition-hours and per-GB charges add up for large, steady traffic.
- Delete unused topics and partitions (Serverless charges per partition-hour; Provisioned limits partitions per broker).
- Use rack-aware consumers (`client.rack`) to cut cross-AZ client data transfer.
- Compress on the producer (lz4/zstd) to reduce bytes stored, transferred and billed per GB.
- Use DEFAULT or PER_BROKER monitoring normally; turn on partition-level metrics only when debugging.
- Use autoscaled MSK Connect connectors and `maxAutoscalingTaskCount` to avoid idle MCUs.
- Use Firehose or MSK data delivery instead of running custom consumer fleets for simple "to S3" delivery.
- Use the MSK Sizing and Pricing spreadsheet from AWS for estimates, then load test.

## H. Quotas and limits (defaults)
| Item | Limit |
|---|---|
| Brokers per account (Standard and Express) | 90 |
| Brokers per cluster | 30 ZooKeeper / 60 KRaft |
| Storage per Standard broker | 1 GiB – 16,384 GiB |
| Express storage | Unlimited |
| IAM TCP connections per broker | 3,000 |
| IAM new connections per broker | 100/s (4/s on t3) |
| Configurations / revisions | 100 per account / 50 |
| Express per-partition throughput | 15 MB/s |
| Serverless ingress / egress per cluster | 200 / 400 MBps |
| Serverless ingress / egress per partition | 5 / 10 MBps |
| Serverless partitions | 2,400 (120 compacted) |
| Serverless max message | 8 MiB |
| Serverless connections / consumer groups | 3,000 / 500 |
| Serverless clusters per account / client VPCs | 10 / 5 |
| MSK Connect | 100 plugins, 100 worker configs, 60 workers per account, 10 workers per connector |
| MSK Replicator | 15 per account, 750 topics each, 1 GB/s ingress, 10 MB (CRR) / 20 MB (SRR) records |
| SCRAM | 1,000 users per cluster, 10 secrets per associate call |
| Data delivery channels | 50 per cluster, 10 per topic, 5–15 min freshness, 10 GB/s per channel |

- Most quotas are raised through Service Quotas or a support case; increases can take days.
- Non-IAM auth has no MSK-enforced connection limit; watch CPU and memory instead.

## I. MSK vs Kinesis Data Streams
| | Amazon MSK | Kinesis Data Streams |
|---|---|---|
| API | Open-source Kafka protocol | AWS Kinesis API (SDK, KPL, KCL) |
| Unit of scale | Partitions on brokers you size (Serverless: automatic) | Shards (provisioned) or on-demand |
| Per-unit throughput | Depends on broker; Serverless 5 MBps in per partition; Express 15 MB/s per partition | 1 MB/s or 1,000 records/s in, 2 MB/s out per shard |
| Max record | ~1 MB default, configurable (Serverless max 8 MiB) | 1 MiB default, up to 10 MiB |
| Retention | Any (time/size); unlimited with tiered storage, Express, Serverless | 24 hours default, up to 365 days |
| Log compaction | Yes | No |
| Exactly-once / transactions | Yes (Kafka transactions) | No native transactions (dedupe in consumer) |
| Fan-out | Unlimited consumer groups (limited by broker egress) | Shared 2 MB/s per shard, or enhanced fan-out 2 MB/s per consumer |
| Ordering | Per partition | Per shard |
| Ops work | Topics, partitions, brokers, storage, upgrades | Very little (on-demand almost none) |
| Auth | IAM, SCRAM, mTLS, unauthenticated | IAM only |
| Ecosystem | Kafka Connect, Kafka Streams, Debezium, MirrorMaker | Firehose, KCL, Lambda, Flink |
| Cross-Region copy | MSK Replicator, MirrorMaker 2 | Build yourself (Lambda/Flink) |

- Pick MSK for Kafka compatibility, Connect/Debezium, compaction, transactions, very long retention or migrating Kafka.
- Pick KDS for AWS-native, low-ops streams with IAM, tight Firehose/Lambda integration, and pay-per-shard simplicity.
- Both: Lambda, Firehose, Managed Flink, Glue streaming, Redshift streaming ingestion and Glue Schema Registry integrate with each.

## J. Troubleshooting: symptom → cause → fix
| Symptom | Likely cause | Fix |
|---|---|---|
| `ActiveControllerCount` ≠ 1 | Metadata/controller problem | Open an AWS case; check ZooKeeper session state |
| `OfflinePartitionsCount` > 0 | Full disk, all replicas down, RF 1 | Free disk/scale storage; use RF 3 |
| URP spiky under load | Brokers undersized | Bigger brokers or more brokers |
| URP > 0 when idle | ACLs deny brokers READ/DESCRIBE, failing broker | Fix ACLs; check broker logs |
| CPU > 60% on all brokers | Not enough compute | Scale up size, or add brokers + partitions |
| CPU high on one broker | Hot partition or uneven placement | Rebalance (Cruise Control / intelligent rebalancing); fix keys |
| New brokers idle after scale out | Partitions not reassigned | Reassign partitions; add partitions |
| Latency high, network allowance metrics rising | EC2 bandwidth limit of broker size | Larger broker size |
| Disk throughput maxed, `VolumeQueueLength` high | EBS throughput limit | Provisioned throughput (4xlarge+), more brokers |
| `HeapMemoryAfterGC` > 60% | Too many partitions/groups, long transactional ID expiry | Fewer partitions, delete empty groups, lower `transactional.id.expiration.ms` |
| t3 cluster slow after some hours | CPU credits exhausted | Move to m5/m7g |
| Express clients see throttle time | Hit per-broker throughput quota | Add brokers or bigger size |
| `UnderProvisioned` = 1 on Express | Not enough capacity to rebalance | Add brokers or scale up |
| CloudWatch bill jumped | `PER_TOPIC_PER_PARTITION` on many partitions | Drop to lower level |
| Cluster stuck in CREATING | Creation can take up to ~30 min | Wait; if FAILED, retry |
| "No default security group" on create | Shared VPC without describe permission | Get `ec2:DescribeSecurityGroups` rights |
| Serverless create fails | No `ec2:CreateVpcEndpoint` permission | Grant it |
| Consumer group stuck in `PreparingRebalance` | Old Kafka bug (2.3.1/2.4.1) or flapping consumers | Upgrade; static membership |
| Clients can't connect from another VPC | No peering/TGW/multi-VPC, SG rules | Add connectivity and SG rules on the right port |

## Scenarios: "If X → Y, because Z"
- **If** a company runs self-managed Kafka on Amazon EC2 and wants less operations work with no code change, **then** use **MSK Provisioned**. **This works because** it runs the same open-source Kafka APIs while AWS manages the brokers (hardware, patching, failed broker replacement). You still choose broker size and count.
- **If** the team wants zero cluster sizing and traffic is unpredictable, **then** use **MSK Serverless**. **This works because** it scales capacity automatically up to its quotas (**200 MBps** in / **400 MBps** out per cluster by default). Watch the cost: partition-hours and per-GB charges add up for large, steady traffic.
- **If** a team needs the simplest AWS-native stream and doesn't need Kafka, **then** use **Amazon Kinesis Data Streams (KDS)**. **This works because** KDS needs very little operations work (almost none in on-demand mode), while MSK needs you to manage topics, partitions, brokers, storage and upgrades.
- **If** a dashboard needs alerts when consumers fall behind, **then** create an **Amazon CloudWatch alarm** on `EstimatedMaxTimeLag` or `MaxOffsetLag` that notifies through **Amazon Simple Notification Service (SNS)**. **This works because** these consumer lag metrics are free DEFAULT-level metrics. They only appear for STABLE or EMPTY groups with committed offsets and ASCII names without `:`.
- **If** an alarm must fire when any partition becomes unavailable, **then** alarm on `OfflinePartitionsCount` **> 0**. **This works because** it counts unavailable partitions and must be 0 on a healthy cluster.
- **If** writes start failing with `NotEnoughReplicas`, **then** check `UnderMinIsrPartitionCount` and broker health. **This works because** the in-sync replicas (ISR) have fallen below `min.insync.replicas`, so `acks=all` writes fail for those partitions. Restore the brokers, and check that minISR isn't equal to the replication factor.
- **If** brokers average **75% CPU**, **then** move to the **next broker size** with `UpdateBrokerType`. **This works because** AWS recommends keeping CPU under **60%**, and a size change is a rolling update that needs no partition moves. It takes about **10–15 minutes** per Standard broker.
- **If** brokers were added but load didn't move, **then** **reassign partitions** with Cruise Control or `kafka-reassign-partitions.sh` (or add partitions to busy unkeyed topics). **This works because** Kafka doesn't move existing partitions to new brokers by itself, so new brokers sit empty.
- **If** scaling an Express cluster must rebalance automatically, **then** keep **intelligent rebalancing** Active. **This works because** it redistributes partitions after scale events in one operation. `RebalanceInProgress` shows when it is moving data, and `UnderProvisioned` means add brokers or scale up.
- **If** a partition reassignment slows producers, **then** add `--throttle` and move fewer partitions per call (AWS: at most **10** on Standard, **20** on Express). **This works because** reassignment copies data between brokers, and that replication traffic competes with clients for CPU, network and disk. AWS advises against reassigning above about **70%** CPU.
- **If** disk usage hits **85%** at 2 a.m., **then** use **storage auto scaling** with a **50–60%** target. **This works because** it uses Application Auto Scaling to grow broker volumes without a human, checking utilization every minute. It never scales in, and the 6-hour+ cool-down still applies.
- **If** traffic dropped and the team wants to pay less, **then** **remove brokers** after moving all partitions off them. **This works because** MSK supports broker removal on M5/M7g (Kafka 2.8.1+). `UserPartitionExists` must show **0** first, and you remove one broker per AZ in each operation.
- **If** they also want less Elastic Block Store (EBS) storage, **then** **migrate to a smaller cluster**. **This works because** MSK storage can't shrink.
- **If** per-partition debugging is needed for one day, **then** turn on `PER_TOPIC_PER_PARTITION` monitoring with `UpdateMonitoring`, then turn it off. **This works because** only DEFAULT metrics are free; higher levels are billed at CloudWatch custom-metric prices, and thousands of partitions mean thousands of billable metrics. Changing the level needs no restart.
- **If** the team already runs Grafana and Prometheus, **then** enable **open monitoring**, optionally with **Amazon Managed Service for Prometheus**. **This works because** MSK exposes JMX Exporter (broker metrics) and Node Exporter (host metrics) for Prometheus to scrape. It is free from MSK, but you pay cross-AZ data transfer; use a scrape interval of **60 s** or more.
- **If** **Cruise Control** (an open-source rebalancing tool you run on EC2) is needed on a **KRaft** cluster, **then** run it without ZooKeeper, using Prometheus metrics. **This works because** KRaft clusters have no ZooKeeper endpoint, and Cruise Control takes its input from Prometheus metrics.
- **If** a 3-AZ cluster's consumers cause large cross-AZ charges, **then** use **rack-aware fetching** (`client.rack` on consumers). **This works because** consumers then read from replicas in their own Availability Zone (AZ), and cross-AZ client traffic is billed as normal data transfer.
- **If** retention must grow from **3 days** to **90 days** cheaply, **then** use **tiered storage** (Standard brokers) or **Express brokers**. **This works because** keeping 90 days on every broker's EBS volume is expensive; tiered storage costs **$0.06** per GB-month (plus a read fee), and Express storage is managed and billed per GB used.
- **If** a dev Serverless cluster has **2,000** idle partitions, **then** delete them. **This works because** Serverless bills **$0.0015** per partition-hour, so idle partitions still cost money.
- **If** a workload is **500 MBps** steady, **then** use **MSK Provisioned** (Express or Standard). **This works because** Serverless caps at **200 MBps** ingress per cluster by default and throttles above it.
- **If** a team must copy a topic to another Region for disaster recovery with managed offset translation, **then** use **MSK Replicator**. **This works because** it syncs data, topic configs, ACLs and consumer group offsets. Its metrics, such as `ReplicationLatency` and `MessageLag`, are in the target Region.
- **If** a security team asks for proof of who changed a topic config, **then** use **AWS CloudTrail** with **IAM access control**. **This works because** with IAM access control, MSK logs Kafka admin actions such as `AlterTopicDynamicConfiguration` in CloudTrail.
- **If** an exam asks which metric shows the controller, **then** answer `ActiveControllerCount`. **This works because** exactly one controller must be active, so the cluster-wide sum must be **1**.
- **If** broker memory shows **95% used**, **then** take no action unless `HeapMemoryAfterGC` is high (alarm above **60%**). **This works because** Kafka uses free memory as page cache, so high `MemoryUsed` is normal.
- **If** an IAM client fleet reconnects in a storm after a deploy, **then** raise `reconnect.backoff.ms` and reuse connections. **This works because** each broker accepts only **100** new IAM connections per second (4 on t3); above that, clients get "Too many connects" and `IAMTooManyConnections` rises.
- **If** Express brokers return throttle time to producers, **then** add brokers or use a bigger size. **This works because** Express enforces per-broker client throughput quotas so client traffic can't starve replication.
- **If** a `kafka.t3.small` production cluster slows after bursts, **then** move to **M7g** brokers. **This works because** T3 brokers run on CPU burst credits; when `CPUCreditBalance` falls to 0, CPU is throttled.
- **If** the owner must choose a stream for **exactly-once** Kafka-to-Kafka processing, **then** use **MSK with Kafka transactions**. **This works because** Kinesis Data Streams has no native transactions, so its consumers must deduplicate.
- **If** a Kafka topic must be queryable in **Amazon Athena** as **Apache Iceberg** within **15 minutes** on an Express cluster, **then** use **MSK data delivery** to **Amazon S3 Tables**. **This works because** it writes Iceberg tables with **5–15 minute** freshness and compacts them inline, with no connectors to run. Price: about **$10 per TB** plus S3 costs.
- **If** an MSK Connect connector reports `ErroredTaskCount` **> 0**, **then** check the connector logs in Amazon CloudWatch Logs or Amazon S3. **This works because** task errors are logged there.
- **If** Replicator `MessageLag` keeps growing, **then** check the target cluster's capacity and the `ThrottleTime` metric. **This works because** Replicator can only write as fast as the target cluster accepts.
- **If** a cluster's Kafka version is near end of support, **then** **upgrade in place** (a rolling update, one broker at a time). **This works because** after the end-of-support date MSK auto-upgrades the cluster at any time, with no notice. Clients keep working during the upgrade if replication, minISR and retries are set right.
- **If** a cost review shows idle storage on many Standard brokers, **then** consider **Express brokers**. **This works because** Standard bills **$0.10** per GB-month of provisioned EBS, used or not, while Express charges only for storage used (plus **$0.01** per GB written).
- **If** a **cross-account Amazon Data Firehose** stream must read MSK privately, **then** use **multi-VPC private connectivity** with IAM auth and a **cluster policy** that allows Firehose. **This works because** Firehose connects by calling `kafka:CreateVpcConnection`, which the cluster policy must allow.
- **If** a team must replicate between **two accounts**, **then** use **MirrorMaker 2**. **This works because** MSK Replicator works within one account only.
- **If** a cluster with storage auto scaling was deleted and its alarm remains, **then** delete the leftover target-tracking CloudWatch alarm. **This works because** that alarm is not removed with the cluster; next time, remove the scaling policy before deleting the cluster.
- **If** a **1 TB/day** topic with **RF 3** keeps **7 days** on Standard brokers, **then** plan about **21 TB** of EBS across brokers plus headroom. **This works because** 7 days is 7 TB of topic data, and each byte is stored once per replica (3 times). Keep disk below the **85%** alarm level.
- **If** a nightly batch adds **3 brokers** and removes them in the morning on Standard, **then** consider **Express brokers**. **This works because** on Standard, new brokers stay empty until you reassign partitions, and brokers can be removed only after their partitions are moved off, which is slow. Express scales up to **20x** faster, and intelligent rebalancing moves partitions automatically.

Verified from AWS docs on 2026-11-02 (MSK CloudWatch metrics for Standard and Express brokers, Serverless monitoring, consumer lag, open monitoring, logging, Cruise Control and rebalancing guidelines, intelligent rebalancing, broker count/size/removal, storage scaling, best practices, troubleshooting, quotas, MSK Connect monitoring, Replicator monitoring, MSK pricing page).
Unconfirmed (verify): Express storage priced on single logical copy; multi-VPC hourly price unit; exact Serverless and Express prices outside us-east-1; CloudWatch custom-metric pricing per MSK metric; EBS volume metrics level for Express.

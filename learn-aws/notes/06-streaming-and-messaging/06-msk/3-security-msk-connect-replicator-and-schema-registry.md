# Amazon MSK – 3. Security, MSK Connect, MSK Replicator and Schema Registry

Short notes. Each point is a fact you can be asked about.

## A. Security layers
- Network: MSK runs in your VPC. Security groups on the brokers decide which clients can reach which ports.
- Control plane (AWS API like `CreateCluster`, `UpdateBrokerCount`, `GetBootstrapBrokers`): always IAM, actions start with `kafka:`.
- Data plane (Kafka protocol: produce, consume, create topic): your chosen client authentication, plus authorization by IAM policy or Kafka ACLs.
- IAM data-plane actions start with `kafka-cluster:`. Don't confuse `kafka:` (manage the cluster) with `kafka-cluster:` (use the cluster).
- Encryption at rest: always on, with AWS KMS.
- Encryption in transit: TLS between clients and brokers and between brokers (choices below).

## B. Client authentication options (Provisioned)
| Method | Port (inside AWS / public) | Authorization | Notes |
|---|---|---|---|
| IAM access control (SASL/IAM) | 9098 / 9198 | IAM policies | Authn + authz in one; needs TLS |
| SASL/SCRAM-SHA-512 | 9096 / 9196 | Kafka ACLs | Users/passwords in Secrets Manager; needs TLS |
| Mutual TLS (mTLS) | 9094 / 9194 | Kafka ACLs | Client certs from AWS Private CA |
| Unauthenticated | 9092 plaintext / 9094 TLS | Kafka ACLs mostly useless (anonymous) | Not allowed with public access |

- You can turn on more than one method at once. Each method gets its own listener and port.
- IPv6 (dual-stack) ports: 20092 plaintext, 20094 TLS, 20096 SCRAM, 20098 IAM.
- MSK Serverless supports IAM only (port 9098).
- Authentication can be changed after creation with `UpdateSecurity` while the cluster is ACTIVE.
- IAM, SCRAM and mTLS all require client-broker TLS. Unauthenticated allows TLS, PLAINTEXT or TLS_PLAINTEXT.
- SASL/PLAIN is not supported on MSK.

## C. IAM access control
- One mechanism for authentication and authorization. Clients sign in with IAM credentials (roles, users, instance profiles, Lambda roles).
- Works for Java and non-Java clients (Python, Go, JavaScript, .NET). Non-Java needs Kafka 2.7.1+ clusters.
- Java clients use the `aws-msk-iam-auth` library with `sasl.mechanism=AWS_MSK_IAM` or `OAUTHBEARER`. Non-Java clients use `OAUTHBEARER` with an MSK signer library.
- Actions are denied by default. Every needed action must be allowed explicitly.
- Every action needs `kafka-cluster:Connect` on the cluster ARN.
- Produce needs: `Connect`, `DescribeTopic`, `WriteData` (+ `WriteDataIdempotently` on the cluster for idempotent producers).
- Consume needs: `Connect`, `DescribeTopic`, `ReadData` on topics and `DescribeGroup`, `AlterGroup` on the consumer group.
- Transactions need `DescribeTransactionalId` and `AlterTransactionalId` on the transactional-id ARN.
- Admin actions: `CreateTopic`, `AlterTopic`, `DeleteTopic`, `AlterTopicDynamicConfiguration`, `AlterCluster`, `AlterClusterDynamicConfiguration`.
- Resource ARN types: `cluster/name/uuid`, `topic/name/uuid/topic`, `group/name/uuid/group`, `transactional-id/name/uuid/id`.
- Wildcards are allowed after `cluster/`, `topic/`, `group/`, `transactional-id/`. Example: `topic/MyCluster/*/orders-*`.
- Least privilege: separate producer, consumer and admin roles, each scoped to specific topic and group ARNs.
- When IAM is used, Kafka ACLs have no effect on IAM principals, and `allow.everyone.if.no.acl.found` doesn't apply to them.
- IAM access control doesn't cover ZooKeeper nodes.
- Limits per broker for IAM: 3,000 TCP connections, 100 new connections/second (m5/m7g, Express) or 4/second (t3).
- "Too many connects" error = IAM connection-rate limit hit. Raise client `reconnect.backoff.ms`, reuse connections, fewer clients.
- "Session too short" error = IAM credentials about to expire when connecting. Refresh credentials earlier.
- Monitor with `ClientConnectionCount` (Client Authentication = IAM) and `IAMTooManyConnections`.

## D. SASL/SCRAM with Secrets Manager
- Usernames/passwords live in Secrets Manager secrets associated with the cluster. MSK syncs them to brokers.
- Only SCRAM-SHA-512 is supported.
- Secret name must start with `AmazonMSK_`.
- The secret must be encrypted with a customer managed KMS key. The default Secrets Manager key (`aws/secretsmanager`) does not work. Asymmetric keys don't work.
- Secret must be in the same account and Region as the cluster.
- Up to 10 secrets per `BatchAssociateScramSecret` call; up to 1,000 users per cluster.
- Turning on SCRAM turns on TLS for client-broker traffic.
- Authorization is by Kafka ACLs. Set ACLs, then set `allow.everyone.if.no.acl.found=false`, or every user can access topics without ACLs.
- Rotation: MSK supports password-only rotation (single-user strategy). It reads only the `AWSCURRENT` version.
- To change a username safely: create a new secret, associate it, set ACLs, move clients, then disassociate the old secret.

## E. Mutual TLS (mTLS) with AWS Private CA
- Clients present certificates issued by an AWS Private CA (ACM PCA). The CA can be in the same or another account.
- The broker side uses public ACM certificates from Amazon Trust Services, so default truststores trust them. Self-signed broker certs aren't used.
- Principal in ACLs is the certificate's distinguished name, for example `User:CN=app1`.
- MSK does not support certificate revocation lists (CRLs). To block a compromised cert, remove its ACLs and tighten security groups.

## F. Unauthenticated access and Kafka ACLs
- Unauthenticated = anyone who can reach the port can connect. Only network controls (security groups) protect it.
- Not allowed together with public access or multi-VPC private connectivity.
- Kafka ACL format: principal P is allowed/denied operation O from host H on resource R.
- MSK enables the Kafka authorizer. Brokers are super users so replication works even with ACLs.
- MSK default `allow.everyone.if.no.acl.found=true`: a resource with no ACL is open to all. Set false once ACLs exist.
- Trap: setting it to false before creating ACLs locks every client out.
- Manage ACLs with `kafka-acls.sh --bootstrap-server`, never `--zookeeper`, especially on KRaft.

## G. Encryption
- At rest: always on with KMS. Default is an AWS managed key (`aws/kafka`). You can pick a customer managed key at creation.
- The at-rest KMS key can't be changed after cluster creation **(verify)**.
- Customer managed key = you control the key policy, rotation and CloudTrail usage; needed for cross-account key control.
- In transit client-broker: `TLS` (default), `TLS_PLAINTEXT` (both), or `PLAINTEXT`.
- In transit broker-broker (in-cluster): on by default. It can be turned off only at creation and can never be changed later.
- Trap: a cluster created with in-cluster encryption off can never enable public access, IAM, SCRAM or mTLS (they need it on).
- Default TLS 1.2. TLS 1.3 on Provisioned through TLS security policies: `MSK-TLS1.2-Default-2026`, `MSK-TLSv1.3-2026` (1.2 + 1.3), `MSK-TLSv1.3-Only-2026`.
- You move between TLS policies one step at a time (can't jump from TLS1.2-Default to TLSv1.3-Only).
- MSK renews broker TLS certificates every 13 months automatically.
- Encrypt before transit (client-side encryption) when brokers must never see plaintext; MSK has no built-in field-level encryption.

## H. Network access patterns
- Default: clients must be in the cluster's VPC (or a connected network) and allowed by security groups.
- Other VPCs: VPC peering, Transit Gateway, or multi-VPC private connectivity (PrivateLink).
- On-premises: Site-to-Site VPN or Direct Connect into the VPC.
- Public access (Provisioned only, Kafka 2.6.0+): can't be on at creation; turn it on later with `UpdateConnectivity`.
- Public access requirements: public subnets (route to an internet gateway), unauthenticated off, IAM/SCRAM/mTLS on, in-cluster encryption on, plaintext off.
- For SCRAM/mTLS public access, set ACLs and `allow.everyone.if.no.acl.found=false` first.
- Public access uses service-provided Elastic IPs (`SERVICE_PROVIDED_EIPS`). No extra MSK fee, but data transfer and public IPv4 charges apply.
- ZooKeeper and KRaft controllers are never public.
- KRaft-mode and Express clusters can't have both open monitoring and public access on.
- Multi-VPC private connectivity = MSK-managed PrivateLink connections from client VPCs (same or other accounts) to the cluster.
- Multi-VPC supports IAM, TLS and SCRAM auth (not unauthenticated), Kafka 2.7.1+, not t3.small, same Region only, not to ZooKeeper.
- Client subnets must match the cluster's AZ IDs and count. Overlapping CIDRs across VPCs are fine.
- Multi-VPC has an hourly charge per auth scheme plus a per-GB data processed charge.
- Cluster policy = resource-based policy on the MSK cluster. It lets other accounts call `kafka:CreateVpcConnection`, `GetBootstrapBrokers`, `DescribeCluster`, `DescribeClusterV2`.
- With IAM auth, the cluster policy can also grant `kafka-cluster:*` data-plane actions on topics and groups to other accounts.
- Cluster policy APIs: `PutClusterPolicy`, `GetClusterPolicy`, `DeleteClusterPolicy`.
- Firehose, MSK Replicator (cross-Region) and cross-account Lambda all use multi-VPC connectivity plus a cluster policy.
- MSK Serverless connects up to 5 client VPCs through VPC endpoints it creates.

## I. Logging and audit
- Broker logs (INFO level by default) can go to CloudWatch Logs, S3, and/or Data Firehose (then OpenSearch).
- Authorizer logs record allow/deny decisions; useful to audit who tried to read or write a topic.
- You create the destination first. Firehose streams need the tag `LogDeliveryEnabled=true`.
- S3 log buckets using SSE-KMS need the key policy to allow `delivery.logs.amazonaws.com`.
- CloudTrail logs all MSK API operations. With IAM access control it also logs Kafka admin actions: create/alter/delete topic and dynamic config changes.
- CloudTrail does not log every produce/consume call. Use authorizer logs for data access auditing.

## J. MSK Connect basics
- MSK Connect = managed Apache Kafka Connect. Runs source and sink connectors without servers.
- Source connector: external system → Kafka (for example Debezium CDC from MySQL/PostgreSQL, JDBC source).
- Sink connector: Kafka → external system (for example S3 sink, OpenSearch sink, EventBridge sink).
- Works with MSK clusters and self-managed Kafka reachable from a VPC.
- Kafka Connect versions: 2.7.1 (Java 11) and 3.7.x (Java 17).
- Custom plugin = your connector code: a JAR or ZIP of JARs uploaded to S3. MSK Connect copies it at create time.
- Plugins can't be updated in place. Create a new plugin and update connectors to use it.
- Bundle all dependencies (uber JAR or ZIP), or runtime errors happen.
- Worker = a JVM process running connector tasks. Tasks are the parallel threads that move data.
- Worker configuration = shared settings like converters. Default uses `StringConverter` for key and value.
- Converters (JSON, Avro, Protobuf with a schema registry) decide the bytes written to Kafka.
- Each worker uses one IP address in your subnets. Plan subnet size for max workers.
- Connector-to-cluster auth: IAM or none (unauthenticated) **(verify for SCRAM/mTLS support)**.
- Service execution role: IAM role the connector assumes for AWS access (S3 write, Secrets Manager read) and for IAM cluster auth. Service-linked role can't be used.
- Internet access (for example a SaaS source) needs private subnets with a NAT gateway. Workers have no public IPs.
- Secrets in connector config: use config providers (Secrets Manager, Parameter Store, S3) instead of plaintext.
- Plugins must mark secret fields as `PASSWORD` type, or values can appear in logs.
- Logs go to CloudWatch Logs, S3 or Firehose. High log volume may be rate-limited and dropped.

## K. MSK Connect capacity and scaling
- MCU (MSK Connect Unit) = 1 vCPU + 4 GiB memory. Price is per MCU-hour.
- MCUs per worker: you choose; vertical scaling between 1 and 8 vCPUs per worker with `UpdateConnector`.
- Provisioned capacity: fixed worker count and MCUs per worker.
- Autoscaled capacity: min/max workers, scale-out and scale-in CPU % thresholds (`CpuUtilization`), MCUs per worker.
- In autoscaled mode MSK Connect overrides `tasks.max` = workers × MCUs × 2.
- `maxAutoscalingTaskCount` caps tasks (must be ≥ max workers). Use it when topic partitions are fewer than computed tasks.
- Quotas: 100 custom plugins, 100 worker configurations, 60 workers per account, 10 workers per connector (defaults).
- Autoscaled connectors count their max workers against the 60-worker account quota.
- Sink parallelism is capped by topic partitions: tasks beyond partition count sit idle.
- Updating plugin or worker config starts new workers, moves tasks, then removes old workers; health checks can roll back.
- Kafka Connect internal topics: config, offsets (source connectors) and status topics, all compacted.
- Sink connectors store progress as normal consumer group offsets (group `connect-<connector-name>`).
- Key metrics: `CpuUtilization`, `MemoryUtilization`, `RunningTaskCount`, `ErroredTaskCount`, `WorkerCount`, `SinkRecordSendRate`, `SourceRecordWriteRate`.

## L. Common connectors
- Debezium source: reads the database transaction log (MySQL binlog, PostgreSQL WAL) and writes one topic per table. Row-level CDC with low source load.
- Debezium needs DB settings: MySQL binlog ROW format; PostgreSQL logical replication; a user with replication rights.
- Debezium uses compacted topics keyed by primary key, so the latest row state is kept.
- S3 sink (for example Confluent S3 sink): writes topic data to S3 in JSON, Avro or Parquet, partitioned by time or field, with `flush.size` controlling file size.
- Small `flush.size` creates many small S3 files; tune for larger files.
- EventBridge sink connector sends Kafka records to an EventBridge bus.
- MirrorMaker 2 is built on Kafka Connect, so it can run on MSK Connect **(verify)**.

## M. MSK Replicator
- MSK Replicator = fully managed, serverless replication of data, topic configs, Kafka ACLs and consumer group offsets between Kafka clusters.
- Cross-Region replication (CRR) and same-Region replication (SRR).
- MSK-to-MSK: Provisioned and Serverless in any combination. Source and target must be in the same AWS account.
- Self-managed Kafka (2.8.1+, SASL/SCRAM, mTLS or OAUTHBEARER) can be a source when the target is MSK Provisioned. Used for migrations.
- Cross-account MSK-to-MSK is not supported. Use MirrorMaker 2 for that.
- MSK clusters must have IAM access control on. Replicator connects on port 9098.
- CRR: the source cluster needs multi-VPC private connectivity for IAM plus a cluster policy for `kafka.amazonaws.com` (`CreateVpcConnection`, `GetBootstrapBrokers`, `DescribeClusterV2`).
- SRR: no multi-VPC needed; security groups must allow Replicator ↔ clusters on 9098; subnets in the same AZs.
- Not t3.small. Kafka 2.7.0+ (identical topic names need 2.8.1+). At least 3 brokers per Provisioned cluster (4 if 2 AZs).
- Replication is asynchronous. Replicator deploys in the target Region and buffers data in memory only (it doesn't store your data).
- Default start: latest offset. You can choose earliest at creation to copy existing data.
- "Detect and copy new topics" finds new topics/partitions within about 30 seconds. Records written before the target topic exists are not copied.
- Target topics are created with RF 3 (change on target if needed).
- Topic naming "Prefixed" (default): target topic = `<sourceKafkaClusterAlias>.<topic>`. Good for active-active; consumers can subscribe with a wildcard.
- Topic naming "Identical": keeps names. Easier failover and migration. Loops are prevented with the `__mskmr` record header.
- Trap: don't strip the `__mskmr` header, or identical-name bidirectional replication can loop.
- ACLs copied: LITERAL topic ACLs only (not PREFIXED, not other resource types). Write ACLs are not copied. Deletes are not copied.
- IAM policies are not copied. For IAM clients, create matching IAM policies for the target cluster yourself.
- Offset sync translates committed consumer offsets so consumers resume near the same place after failover.
- Offset translation is approximate and conservative: expect a few duplicates after failover (design idempotent consumers).
- Offsets sync to a target group only while no consumer of that group is active on the target.
- Legacy one-way offset sync has no failback. Bidirectional (two Replicators, identical names, enhanced sync) supports failover and failback.
- Serverless targets: Replicator uses 83 compacted partitions; only some topic configs sync; Kafka ACLs aren't replicated.
- Quotas: 15 Replicators per account, 750 topics per Replicator, 1 GB/s ingress per Replicator, record size 10 MB (CRR) / 20 MB (SRR).
- Metrics in the target Region: `ReplicationLatency`, `MessageLag`, `ReplicatorThroughput`, `ReplicatorFailure`, `AuthError`, `ThrottleTime`, `ConsumerGroupOffsetSyncFailure`.
- Logs can go to CloudWatch Logs, S3 or Firehose (off by default).
- Pricing: per Replicator-hour plus per GB replicated, plus normal cross-Region data transfer.

## N. MirrorMaker 2 (MM2)
- Open-source Kafka replication tool built on Kafka Connect. You run and scale it yourself (EC2, ECS/EKS, or Kafka Connect).
- Use MM2 when: cross-account replication, non-IAM MSK clusters, or custom replication rules that Replicator doesn't support.
- MM2 connectors: MirrorSourceConnector (data + configs), MirrorCheckpointConnector (offset translation), MirrorHeartbeatConnector (health).
- Default naming adds the source alias prefix (`source.topic`); `IdentityReplicationPolicy` keeps the same names.

## O. AWS Glue Schema Registry
- Glue Schema Registry = serverless, free schema registry. Producers and consumers use AWS Serde libraries.
- Formats: Avro (1.11.4), JSON Schema (Draft-04, -06, -07), Protobuf (proto2 and proto3, no extensions or groups).
- Registry = container of schemas with its own ARN for IAM control. Schema = versioned definition. Each version is checked against a compatibility mode.
- Compatibility modes (8): NONE, DISABLED, BACKWARD, BACKWARD_ALL, FORWARD, FORWARD_ALL, FULL, FULL_ALL.
- NONE = any change accepted. DISABLED = no new versions allowed.
- BACKWARD (recommended, default **(verify)**): new consumers can read data from the previous version. Allows deleting fields and adding optional fields.
- FORWARD: old consumers can read data from the new version. Allows adding fields and deleting optional fields.
- FULL: both directions against the previous version. Only add or remove optional fields.
- `_ALL` variants check against all earlier versions, not just the last one.
- Example trap: adding a required field fails BACKWARD; make it optional (with a default) to pass.
- The serializer adds a schema version ID to each record; consumers fetch and cache schemas by ID.
- Auto-registration can register new schemas from producers (control with IAM in production).
- Optional ZLIB compression of records.
- Integrations: Kafka/MSK clients, Kinesis Data Streams (KPL/KCL), Managed Service for Apache Flink, Lambda, Glue streaming ETL, MSK data delivery (JSON with Glue schema).
- Quotas: 100 registries per Region, 10,000 schema versions per Region per account, 170 KB per schema, 10 metadata key-value pairs per version.
- Alternative: Confluent Schema Registry (self-managed). Glue Schema Registry is the AWS-native, IAM-controlled choice.

## P. Troubleshooting: symptom → cause → fix
| Symptom | Likely cause | Fix |
|---|---|---|
| IAM client gets authorization error on consume | Missing `AlterGroup`/`DescribeGroup` on the group ARN | Add group permissions |
| Idempotent producer fails with IAM | Missing `WriteDataIdempotently` on cluster | Add it |
| SCRAM secret can't be associated | Secret uses default Secrets Manager key, wrong name prefix, other account | Customer managed KMS key, `AmazonMSK_` prefix, same account/Region |
| Every SCRAM user sees every topic | `allow.everyone.if.no.acl.found=true` | Create ACLs, then set it false |
| All clients locked out after config change | Set `allow.everyone.if.no.acl.found=false` before ACLs | Add ACLs (brokers are super users) |
| Can't enable public access | Unauth on, plaintext on, private subnets, or in-cluster encryption off | Fix each; if in-cluster encryption was off at create, rebuild |
| Public access on but can't connect | Security group lacks public port rules (9198/9196/9194) | Allow client IPs on the public ports |
| Compromised mTLS cert still works | MSK doesn't support CRLs | Remove its ACLs; tighten security groups |
| "Too many connects" | IAM connection rate limit per broker | Raise `reconnect.backoff.ms`, reuse connections |
| Connector stuck creating | Not enough subnet IPs, no NAT for internet sinks, wrong role | Bigger subnets, NAT, fix execution role |
| Connector creates many idle tasks | Autoscaled `tasks.max` > partitions | Set `maxAutoscalingTaskCount` |
| Replicator can't be created cross-account | Not supported | Use MirrorMaker 2 |
| IAM clients fail after Replicator failover | IAM policies not replicated | Pre-create target IAM policies |
| Consumers reprocess some records after failover | Offset translation is approximate | Make consumers idempotent |
| Schema registration rejected | Change breaks the compatibility mode | Make fields optional, or pick another mode deliberately |

## Scenarios: "If X → Y, because Z"
- If a team wants no passwords and per-topic control with existing AWS roles → IAM access control, because it does authentication and authorization with IAM policies.
- If a consumer role needs least privilege → allow `Connect`, `DescribeTopic` and `ReadData` on one topic ARN plus `DescribeGroup`/`AlterGroup` on one group ARN, because consumption needs group actions too.
- If a third-party Kafka tool only supports username/password → SASL/SCRAM with Secrets Manager, because SCRAM-SHA-512 is the password option.
- If a SCRAM secret fails to attach → check the `AmazonMSK_` prefix and customer managed KMS key, because the default Secrets Manager key isn't allowed.
- If passwords must rotate automatically → Secrets Manager rotation on the associated secret (password-only), because MSK reads the `AWSCURRENT` version.
- If clients must authenticate with certificates → mTLS with AWS Private CA, because MSK verifies client certs from that CA.
- If a compliance team needs TLS 1.3 only → apply TLS policies step by step to `MSK-TLSv1.3-Only-2026`, because you can't jump policies.
- If the cluster must be reached from the internet → enable public access after creation with IAM/SCRAM/mTLS and TLS, because MSK blocks public access at creation and for unauthenticated clusters.
- If a cluster was created with in-cluster encryption off and now needs public access → create a new cluster, because in-cluster encryption can't be turned on later.
- If clients in 10 VPCs across 3 accounts with overlapping CIDRs need access → multi-VPC private connectivity plus a cluster policy, because PrivateLink handles overlapping IPs.
- If a partner account must read one topic with IAM → cluster policy granting their account `kafka-cluster` read actions on that topic, because resource policies allow cross-account data access.
- If auditors want a record of who deleted a topic → CloudTrail with IAM access control, because MSK logs `kafka-cluster:DeleteTopic` there.
- If auditors want to see denied reads → authorizer logs to CloudWatch Logs or S3, because CloudTrail doesn't log produce/consume.
- If the team needs to control the at-rest key policy → customer managed KMS key at cluster creation, because the default is an AWS managed key.
- If database changes must stream into MSK with low source load → Debezium source connector on MSK Connect, because it reads the transaction log.
- If topic data must land in S3 as Parquet with custom partitioning → S3 sink connector on MSK Connect, because Firehose gives less connector-level control.
- If connector load varies a lot → autoscaled capacity with CPU thresholds, because MSK Connect adds and removes workers.
- If a connector must call a SaaS API on the internet → private subnets plus a NAT gateway, because workers have no public IPs.
- If a DR copy in another Region is needed for an IAM-auth cluster in the same account → MSK Replicator CRR with offset sync, because it is managed and translates offsets.
- If DR must fail over and fail back → two Replicators with identical topic names and enhanced offset sync, because legacy sync has no failback.
- If clusters in two accounts must replicate → MirrorMaker 2, because Replicator works only within one account.
- If a migration from self-managed Kafka with SCRAM to MSK Provisioned is planned → MSK Replicator with the self-managed cluster as source, because it supports SCRAM/mTLS/OAuth sources.
- If active-active writes happen in two Regions → prefixed topic names, because each Region's data stays in its own topic and loops are avoided.
- If producers change schemas and old consumers must keep working → FORWARD (or FULL) compatibility, because old readers must read new data.
- If consumers upgrade first and must read old data → BACKWARD, because new readers must read previous data.

Verified from AWS docs on 2026-11-02 (MSK IAM access control, IAM action semantics, use cases, client config; SASL/SCRAM how it works, limitations, rotation; mTLS; Kafka ACLs; encryption; TLS security policies; update security; port info; public access; multi-VPC connectivity, cluster policy, permissions; logging and CloudTrail; MSK Connect overview, capacity, max task count, plugins, workers, logging, monitoring, internet access, execution role, update connector, internal topics; MSK Replicator supported configs, prerequisites, network, how replication works, topic naming, metadata/ACL replication, offset sync, monitoring, quotas; migration/MirrorMaker 2; Glue Schema Registry).
Unconfirmed (verify): at-rest KMS key immutable after creation; Glue Schema Registry default compatibility BACKWARD; MSK Connect support for SCRAM/mTLS cluster auth; MirrorMaker 2 on MSK Connect.

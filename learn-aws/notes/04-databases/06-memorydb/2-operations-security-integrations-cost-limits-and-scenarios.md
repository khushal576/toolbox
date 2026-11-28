# MemoryDB – 2. High availability, scaling, snapshots, Multi-Region, security, monitoring, migration, cost, limits, scenarios

Short notes. Each point is a fact you can be asked about.

## A. High availability and failover (verified)
- Multi-AZ is **automatic** when each shard has more than one node. Needs at least 1 replica per shard.
- **Replica fails**: MemoryDB removes it, launches a replacement in the **same AZ**, and the new node **syncs from the transaction log**. Cluster keeps serving.
- **Primary fails (Multi-AZ)**: MemoryDB fails over to a replica **after making sure it is consistent**, then launches a new replica in the failed primary's AZ.
- Failover time: writes resume in **typically a few seconds**.
- **No data loss** in any failure case, because the log holds all acknowledged writes.
- **Primary + some replicas fail**: an up-to-date replica is promoted; new replicas rebuild from the log.
- **Entire cluster fails**: all nodes are rebuilt in the same AZs and sync from the log. Still **no data loss**.
- **Single-node shard (no replica)**: if the primary fails, **writes stop** until the new primary is built and synced.
- Promoting a replica is faster than building a new primary. Always keep at least one replica.
- Planned maintenance node replacements finish **while the cluster still serves writes**.
- Test failover with `FailoverShard`: max **5 times in 24 hours**. If you test several shards in one cluster, finish each node replacement before the next call.
- `FailoverShard` is for **testing the app**, not an operational fix. AWS can block it during large events.
- Multi-AZ is **high availability**, not a backup. Use snapshots for point-in-time copies.

## B. Scaling (verified)
- **Scale out/in = change the number of shards** (online resharding). Cluster keeps serving requests during the change.
- **Scale up/down = change node type** (online vertical scaling). Builds new nodes and syncs them with old ones. Do it in **low-traffic hours**. Test first.
- Change the **number of replicas** to scale reads or improve availability.
- Add shards → more write capacity and more memory. Add replicas → more read capacity.
- New shards get the **same node count** as the smallest existing shard.
- Scale in: MemoryDB first checks that all data **fits in the remaining shards**. If not, the request stops and nothing changes.
- You cannot remove **all** shards. Delete the cluster instead.
- Large items: a key holding an item **over 256 MB (serialized)** is not moved when scaling out, and its shard is not removed when scaling in. This can leave **unbalanced shards**.
- You cannot move between a **data tiering** node type (r6gd) and a normal one (r6g/r7g).
- **Vector search** clusters: no horizontal scaling (single shard); only vertical and replicas.
- (verify) Application Auto Scaling support for MemoryDB shards/replicas. Check current docs.
- Best practice: size for peak memory. Keep memory use below the limit so snapshots and replication buffers do not cause trouble. Watch `DatabaseMemoryUsagePercentage`.

## C. Snapshots and restore (verified)
- MemoryDB already protects data with the **transaction log**. Snapshots are **extra point-in-time copies** stored in **Amazon S3**.
- **Automatic snapshots**: daily, retention up to **35 days**. Set `SnapshotRetentionLimit` and a snapshot window. (A retention of 0 turns them off – verify.)
- **Manual snapshots**: kept until you delete them. Max **20 manual snapshots per cluster in any 24 hours**.
- **Final snapshot** when deleting a cluster is taken from the **primary** nodes (latest data).
- Snapshots are **cluster-level only**. No shard or node snapshots.
- During a snapshot you **cannot run other API/CLI operations** on that cluster.
- **Restore** always creates a **new cluster** (you can change node type, engine version, shard count).
- **Copy** a snapshot (same or other Region/account). **Export** to your S3 bucket (needs bucket permissions).
- Exported snapshot files use S3 server-side encryption. **Customer managed KMS keys cannot be used for the export** itself; you can re-encrypt the file afterwards.
- **Seed a new cluster** from an RDB file (for example from self-managed Redis or ElastiCache). This is the common migration path.
- Snapshots of a **vector search** cluster contain indexes that only another MemoryDB vector-enabled cluster can read.
- Encryption of snapshots follows the cluster key. Copying keeps the source key unless you choose another.
- Snapshot storage cost: free up to **100% of cluster size**, then billed per GB.

## D. Multi-Region (verified)
- **MemoryDB Multi-Region**: fully managed **active-active** database across Regions. Up to **99.999% availability**.
- Local reads (microseconds) and local writes (single-digit ms) in each Region.
- Replication is **asynchronous**, usually **under a second**.
- Conflicts use **CRDT with Last Writer Wins (LWW)**:
  - **String** → resolved at key level.
  - **Hash, Set, Sorted set** → resolved at **element/sub-key** level (two Regions adding different fields both survive).
  - **Counters** → full-value replication, last writer wins (increments from two Regions **do not add up**).
  - Non-deterministic commands (like `SETNX`) are replicated as deterministic `SET/HSET/SADD/ZADD` or deletes.
- If a Region is cut off, pending writes are tracked and **replicated when it returns** (no matter how long).
- Available in a limited list of Regions (US East/West, Ireland, Frankfurt, London, Tokyo, Sydney, Mumbai, Seoul, Singapore at doc time – verify).
- Metric: `MultiRegionClusterReplicationLag` (per shard, per Region pair).
- Cost: nodes + data written locally + snapshot storage + **cross-Region data transfer**.
- Use Multi-Region for global apps and Region-level DR. Do not rely on it for strict cross-Region transactions.

## E. Security (verified)
- **Network**: VPC only. Control access with **security groups** (port 6379) and subnet groups. No public access.
- **Encryption at rest**: **always on**, cannot be turned off. Covers the transaction log, disk during sync/snapshot/swap, and snapshots in S3. Options: **service-managed key** (default) or **customer managed symmetric KMS key**.
- **KMS rules**:
  - One KMS **grant per cluster**, plus one per snapshot during creation.
  - If you **delete or disable the key or revoke the grant**, the cluster becomes **irrecoverable** (cannot be modified or recovered after hardware failure).
  - **Automatic rotation** is fine. Manual key swap is not supported.
  - Use condition `kms:ViaService` = `memorydb.<region>.amazonaws.com`.
- **Encryption in transit**: TLS. **TLS 1.2 is the minimum** (since 20 July 2023). Covers client connections and replication. Server authentication is supported.
- **Cluster names appear in public Certificate Transparency logs.** Never put sensitive text in the name.
- **Authentication and authorization with ACLs**:
  1. Create **users** (name, up to 2 passwords, access string).
  2. Put users in an **ACL**.
  3. Attach the ACL to the cluster.
- Every cluster must have an ACL. A built-in **`open-access` ACL** (contains the `default` user with full access) exists; it **cannot be changed**. Prefer real ACLs with least privilege.
- The `default` user cannot be modified or deleted.
- **Clusters without TLS must use `open-access`.** An empty ACL (no users) = no access and works only with TLS-enabled clusters.
- **Access string** examples: `on ~* &* +@all` (full) ; `on ~app::* -@all +@read` (read-only on keys starting `app::`). `on/off` sets the user active/inactive. `~` = key patterns, `&` = pub/sub channels, `+@category` = commands.
- Rules: no passwords inside the access string (set them via API), no `reset`, no restricted commands.
- Passwords: **16–128 printable characters**; these are not allowed: `,` `"` `/` `@`. Changing a password **keeps existing connections**.
- Removing a user from an ACL **ends that user's open connections**.
- **IAM authentication** (Valkey/Redis OSS **7.0+**):
  - Create a user with **authentication mode = IAM**.
  - IAM policy grants **`memorydb:connect`** on the **cluster ARN and the user ARN**.
  - Client sends a **short-lived SigV4 token as the password**. Token valid **15 minutes**. A connection is **dropped after 12 hours** unless you re-send `AUTH`/`HELLO` with a new token.
  - **Not supported inside `MULTI/EXEC`.** Some global condition keys unsupported.
  - Good for no stored passwords and federated access. Use a client with a **credentials-provider** interface.
- IAM also controls **management APIs** (create cluster, snapshots) with tag-based access control.
- Audit: **CloudTrail** logs API calls. ACL failures appear as metrics (`AuthenticationFailures`, `CommandAuthorizationFailures`, `KeyAuthorizationFailures`). Use `ACL LOG` for detail. Alarm on these.
- Compliance programs apply (HIPAA, PCI etc. – check the AWS services-in-scope page).
- TLS 1.2 required, TLS 1.3 recommended. FIPS endpoints exist for API calls.

## F. Monitoring (CloudWatch namespace `AWS/MemoryDB`) (verified metrics)
- `EngineCPUUtilization`: the single engine thread. Use for scaling decisions on nodes with 4+ vCPU.
- `CPUUtilization`: whole host. Watch this on small nodes (2 vCPU or fewer) because background processes use CPU too.
- `DatabaseMemoryUsagePercentage`: used memory vs max memory. Alarm before it fills.
- `DatabaseCapacityUsagePercentage`: same idea including SSD for data tiering.
- `BytesUsedForMemoryDB`: total bytes used (dimension `Tier` for data tiering).
- `Evictions`: keys removed due to max memory. Rising = memory pressure (check the eviction policy in the parameter group).
- `KeyspaceHits` / `KeyspaceMisses`, `CurrItems`, `CurrConnections`, `NewConnections`.
- `ReplicationLag`: seconds a replica is behind the primary (replicas only).
- `MaxReplicationThroughput`: above about **100 MB/s** you can see higher write latency (replication throttling). `ReplicationDelayedWriteCommands` counts delayed writes.
- `SuccessfulReadRequestLatency` / `SuccessfulWriteRequestLatency` (microseconds, percentiles allowed, Valkey 7.2+).
- `PrimaryLinkHealthStatus`, `IsPrimary`, `MemoryFragmentationRatio` (keep above 1.0), `ErrorCount`.
- `SearchNumberOfIndexes`, `SearchNumberOfIndexedKeys`, `SearchTotalIndexSize` for vector search.
- Events can go to **Amazon SNS**. Use `DescribeEvents` to follow failovers.
- Troubleshooting map:
  - High latency + high `EngineCPUUtilization` → scale up node or add shards; check big keys, slow commands.
  - High memory % / evictions → scale up, add shards, set TTLs, or use data tiering.
  - Replica lag → heavy writes; add shards or bigger nodes.
  - Auth failures → ACL/password mismatch or TLS not used.
  - Cannot connect → security group, subnet routing, TLS, or cluster-aware client missing.

## G. Migration and integration
- **ElastiCache/self-managed Redis → MemoryDB**: take an RDB snapshot, **seed/restore** a new MemoryDB cluster from it. Then cut over apps. (verify the online/live migration options in the current migration guide)
- Check commands and engine version compatibility first. MemoryDB restricts some admin commands.
- Because the API is compatible, app changes are small: new endpoint, cluster-aware client, TLS, ACL credentials.
- MemoryDB → other: snapshot export to S3 as RDB.
- Integrates with: **CloudWatch** (metrics), **CloudTrail**, **VPC**, **KMS**, **IAM**, **SNS**, **EventBridge via events** (verify), Lambda/ECS/EC2 clients inside the VPC.
- Lambda needs VPC access to reach MemoryDB. Reuse connections between invocations.

## H. Cost (verified model)
- You pay for: **node hours** (by node type), **data written** (per GB, the durability cost; reads are free of this charge), **snapshot storage beyond 100% of cluster size**, **data transfer** (cross-AZ/Region), and Multi-Region replication traffic.
- **Reserved nodes** (1 or 3 years; no, partial or all upfront) give big discounts for steady use.
- **Data tiering** (r6gd) can cut cost by **over 60%** for cold-heavy data.
- Right-size: use fewer, larger nodes if the workload is memory-heavy; avoid over-replicating (each replica costs a full node).
- Use **t4g** for dev/test, not production.
- Compared with ElastiCache: MemoryDB costs more because of durability. If you do not need durability, use ElastiCache.
- Set **TTL** on keys to save memory; avoid keeping dead data.
- Avoid storing huge values (large items also hurt resharding).
- (verify) A free trial exists for new users.

## I. Limits and numbers to remember
- Replicas per shard: **0–5**. Nodes per cluster: up to **500**. Storage: **100+ TB** (with 1 replica).
- Automatic snapshot retention: up to **35 days**. Manual snapshots: **20 per cluster per 24 hours**.
- `FailoverShard` test: **5 per 24 hours**.
- IAM token: **15 minutes**. IAM connection: **12 hours**.
- ACL password: **16–128** printable chars, **2** passwords per user.
- TLS minimum: **1.2**.
- Large item (resharding issue): **over 256 MB**.
- Vector search: **32,768 dims, 10 indexes, 50 fields/index, M ≤ 512, EF ≤ 4096, 1 shard**.
- Data tiering: **19%** DRAM reserved; about **450 µs** extra on SSD reads.
- Default port **6379**.
- (verify) account-level quotas (nodes per Region, subnet groups, ACLs, users) – see Service Quotas.

## J. Common traps
- Choosing MemoryDB just as a cache → you pay for durability you don't use. Choose ElastiCache.
- Assuming replicas return the latest data → they are eventually consistent.
- Single-shard single-node cluster → no HA and writes stop if the primary fails.
- Deleting/disabling the KMS key → cluster cannot be recovered.
- Putting secrets in the cluster name → it ends up in public CT logs.
- Using `open-access` ACL in production.
- Forgetting vector search must be enabled **at creation** and works on **one shard**.
- Using IAM auth with an old engine (below 7.0) or inside `MULTI/EXEC`.
- Counting on counters to merge across Multi-Region → last writer wins.
- Scaling between data-tiering and non-tiering node families → not supported.

## Scenarios (if → then, because)
- **If** a shard's primary fails and the app must lose no writes, **then** keep **Multi-Availability Zone (Multi-AZ)** on with **at least 1 replica** per shard. **This works because** MemoryDB fails over **only to a consistent replica**, and the **transaction log** holds every acknowledged write, so writes resume in **typically a few seconds** with no data loss. Without a replica, writes stop until a new primary is built and synced.
- **If** you need point-in-time copies for **30 days**, **then** set **automatic snapshot** retention (`SnapshotRetentionLimit`) to **30**; the maximum is **35 days**. **This works because** the transaction log gives durability but is not a history of old versions. Snapshots are daily copies stored in **Amazon S3**, and a restore always creates a **new cluster**.
- **If** you only need a disaster recovery (DR) copy in another Region, **then** **copy the snapshot** to that Region. **This works because** snapshots can be copied to another Region or account and restored there as a new cluster. If you instead need a live copy that serves traffic in both Regions, use **MemoryDB Multi-Region** (active-active).
- **If** a global app needs local reads and writes in several Regions, **then** use **MemoryDB Multi-Region**, a fully managed **active-active** database with up to **99.999%** availability. **This works because** each Region serves reads in microseconds and writes in single-digit milliseconds, and replication is **asynchronous** (usually **under a second**). Conflicts are resolved with a conflict-free replicated data type (**CRDT**) and **Last Writer Wins (LWW)**. Do not rely on it for strict cross-Region transactions.
- **If** two Regions increment the same counter, **then** expect **last writer wins**, not a sum, and design around it (for example, avoid shared counters written from several Regions). **This works because** Multi-Region replicates counters as the **full value**, so increments from two Regions **do not add up**.
- **If** memory is full and the `Evictions` metric rises, **then** scale up to a bigger node, add shards, set a **time to live (TTL)** on keys, or use **data tiering**. **This works because** evictions mean MemoryDB is removing keys to stay under max memory. Watch `DatabaseMemoryUsagePercentage` and alarm before it fills.
- **If** only the single engine thread is busy (high `EngineCPUUtilization`), **then** scale up the node or **add shards**, and cut slow commands or big keys. **This works because** each shard's primary runs its own engine thread, so more shards spread the writes. Adding **replicas** helps only with reads.
- **If** you must remove stored passwords from app config, **then** use **Identity and Access Management (IAM) authentication** (Valkey/Redis OSS **7.0+**). An IAM policy grants `memorydb:connect` on the cluster and user ARNs. **This works because** the client sends a short-lived **SigV4 token** (valid **15 minutes**) as the password. Connections drop after **12 hours** unless re-authenticated, and IAM auth does not work inside `MULTI/EXEC`.
- **If** one team must only read keys starting with `app::`, **then** create an **Access Control List (ACL)** user with the access string `on ~app::* -@all +@read` and add it to the cluster's ACL. **This works because** `~` limits key patterns, `-@all` removes all commands, and `+@read` adds back only read commands.
- **If** auditors ask for failed access attempts, **then** set **Amazon CloudWatch** alarms on `AuthenticationFailures` (plus `CommandAuthorizationFailures` and `KeyAuthorizationFailures`) and read `ACL LOG` for detail. **This works because** MemoryDB reports ACL failures as metrics, and **AWS CloudTrail** logs the API calls.
- **If** a cluster cannot be reached from the internet, **then** that is expected: MemoryDB is **VPC-only** with no public endpoint. Connect from inside the Virtual Private Cloud (VPC), for example a bastion host, or over **VPN**, **AWS Direct Connect** or peering. **This works because** access is controlled by **security groups** on port **6379** and subnet groups.
- **If** you want to move from **ElastiCache** with minimal code change, **then** take an **RDB snapshot**, **seed** a new MemoryDB cluster from it, and point the app at the new endpoint. **This works because** the API is compatible; app changes are small (new endpoint, cluster-aware client, TLS, ACL credentials). Check engine version and restricted commands first.
- **If** your dataset is large but only about **20%** is hot, **then** use **data tiering** on **r6gd** nodes. **This works because** cold **values** move to local SSD while keys stay in memory, which can cut cost by **over 60%**. SSD reads add about **450 microseconds**.
- **If** vectors must scale beyond one shard, **then** use **Amazon OpenSearch Service** or **Amazon Aurora PostgreSQL with pgvector** instead. **This works because** MemoryDB vector search is limited to **one shard** and can only scale vertically or with replicas.
- **If** the **AWS Key Management Service (KMS)** key used by the cluster was scheduled for deletion by mistake, **then** cancel the deletion immediately. **This works because** if the key is deleted or disabled, or its grant is revoked, the cluster becomes **irrecoverable**: it cannot be modified or recovered after a hardware failure.

## Verified from AWS docs on 2026-10-02
Read: resilience/failover pages, Multi-AZ page, snapshot index and constraints, online resharding, vertical scaling, Multi-Region page, data protection, at-rest and in-transit encryption, ACL page, IAM authentication page, metrics page, pricing summary. Not confirmed (verify): automatic snapshot retention value 0 = off, Application Auto Scaling support, online/live migration options, EventBridge integration, exact account-level quotas, Multi-Region Region list changes, free trial terms, maintenance window defaults.

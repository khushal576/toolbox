# Keyspaces – 2. Capacity modes, PITR, multi-Region, TTL, CDC, security, monitoring, migration, cost, limits, scenarios

Short notes. Each point is a fact you can be asked about.

## A. Capacity modes (verified)
- **On-demand** (default): pay per request. No planning. Good for new tables, unknown or spiky traffic.
- **Provisioned**: you set reads/writes per second. Good for predictable or slowly changing traffic. Use **auto scaling** to follow load.
- **Units**:
  - **RRU/RCU**: one `LOCAL_QUORUM` read per second of a row up to **4 KB**; `LOCAL_ONE`/`ONE` reads cost **half**.
  - **WRU/WCU**: one write per second of a row up to **1 KB** (writes are always LOCAL_QUORUM).
  - Bigger rows use more units: 8 KB row = 2 RRU (quorum) or 1 RRU (local one); 2 KB row = 2 WRU.
- **Lightweight transactions (LWT)**: no extra multiplier in the capacity docs. A failed condition check still consumes write units based on row size (see `ConditionalCheckFailedRequests`).
- **On-demand scaling**: instantly serves up to **double the previous peak**. Going past double within about **30 minutes** can cause throttling → ramp up gradually.
- New on-demand table starts with a "previous peak" of **2,000 WRU and 6,000 RRU** → can serve **4,000 WRU / 12,000 RRU** immediately.
- Switching an existing provisioned table to on-demand: previous peak = half of the old provisioned values or the new-table default, whichever is higher.
- **Switching modes**: provisioned → on-demand only **once per 24 hours**. On-demand → provisioned any time (a new on-demand table can go back to on-demand only 24 hours after creation). Switching takes several minutes.
- **Provisioned errors**: reads fail with `Read_Timeout`, writes with `Write_Timeout`. Metrics `ReadThrottleEvents` / `WriteThrottleEvents`. Drivers may show `NoHostAvailableException`.
- Decreasing provisioned capacity: up to **4 times per day** (UTC) + 1 more per hour with no decrease → max **27 per day**. Increases are unlimited (within quotas).
- **Auto scaling** uses Application Auto Scaling (target tracking). Up to **1,500 scalable targets** per Region per account.
- **Pre-warming** (warm throughput) lets you prepare a table for a known big event (verify exact feature name and limits).
- Pick on-demand when you cannot forecast; pick provisioned (with auto scaling) when traffic is steady → usually cheaper.

## B. Point-in-time recovery (PITR) (verified)
- **Continuous backups**, restore to **any second** in the last **35 days** (window fixed, cannot be changed).
- You must **enable PITR per table**. You can only restore to a time when PITR was on.
- **Disabling PITR erases backup history.** Re-enabling starts a new window.
- Restore always creates a **new table** (never overwrites). Use CQL `RESTORE TABLE ...`, CLI or console.
- You can restore a **deleted table** if PITR was on and deletion was within 35 days. Creating a new table with the same name makes the old deleted one **non-restorable**.
- No performance or availability impact on the base table; restore uses **no table throughput**.
- Restore time is **not directly tied to size**: at least up to ~**20 minutes** to create the table, hours for big tables, longer if data is skewed.
- **What restore keeps**: schema, data, and table custom properties (capacity mode, provisioned throughput, auto scaling, PITR setting) from the **current** source settings (can be overridden in the restore command).
- **What restore does NOT restore**: **CDC streams, IAM policies, CloudWatch metrics and alarms**, and **tags** (add them with `WITH TAGS`).
- **Encrypted tables**: the **customer managed key must still be accessible**, else restore fails. You can change the key at restore time.
- **Multi-Region tables**: PITR must be on in **all** replicas, and the target must use the same Regions.
- **UDTs** must exist; missing ones are recreated if possible. Dropped and recreated UDT = a new type (restore with old schema is rejected).
- Quotas: **4 concurrent restores**, **5 TB restored per 24 hours** (adjustable).
- Cost: PITR billed by table size; restores billed by data size restored.
- Keyspaces has **no separate on-demand backup** feature in these notes; PITR is the backup tool. (verify if AWS Backup supports Keyspaces)

## C. Multi-Region replication (verified)
- **Active-active**: each Region reads and writes locally. Data replicates **asynchronously**, typically **under 1 second** (no SLA on this lag).
- Replicas follow your choice of Regions. **GovCloud and China Regions are not supported.**
- Conflicts: **cell-level timestamps + Last Writer Wins**. Fully managed.
- Writes use **LOCAL_QUORUM** (two replicas in the local Region) and then replicate. **QUORUM/synchronous replication not supported.**
- Add a Region later with **`ALTER KEYSPACE`** (single or multi-Region keyspace). Existing tags are not copied to the new Region.
- **ADD REGION restores data**: quota 10 TB concurrent.
- Restrictions at doc time:
  - Set **TTL when creating** the multi-Region table; you cannot turn TTL on/off or change the default later.
  - Use **AWS owned key** for encryption (no customer managed key for multi-Region tables). Before adding a Region, no table may use a customer managed key.
  - With provisioned mode, use the **Keyspaces API** (not raw Application Auto Scaling) to configure auto scaling.
- Billing: **writes are billed in each Region**. A 3 KB write in a 2-Region keyspace = 6 WRU. No charge for the replication data transfer itself (cross-Region transfer rules apply to your own traffic).
- Metric: `ReplicationLatency` per receiving Region (average/max).
- On-demand multi-Region tables may see a short **replication latency increase** when a replica hits a new traffic peak. Provisioned tables can see throttling and lag if capacity is too low → use auto scaling.
- Each replicated write also counts toward the **3,000 requests/sec per connection** quota → use more connections.
- `system.peers` shows only local info; client sees a single-datacenter cluster.
- Use for: global apps, low-latency local access, Region-failure resilience (no failover step needed: just point to another Region).

## D. Time to Live (TTL) (verified)
- Set a **default TTL for the table** and override per **row or column** with `INSERT ... USING TTL` / `UPDATE ... USING TTL`.
- Expired data is **hidden immediately** from reads and DML.
- Physically deleted from storage typically **within 10 days** after expiry. Storage billing stops once deleted.
- TTL deletes are billed in **TTL delete units**: 1 per KB of data per row deleted or updated (2.5 KB update+delete = 3; 3.5 KB row = 4). Metric `TTLDeletes`.
- TTL does not hurt table performance or availability.
- Statement column limit drops from 225 to **166** when TTL is used.
- With client-side timestamps the system also uses `SystemReconciliationDeletes` units for tombstones.
- TTL can be enabled with CloudFormation at table creation.
- Use TTL for: expiring sessions, ads, telemetry, retention rules, cost saving.

## E. Change data capture (CDC) streams (verified)
- Captures **row-level changes** in near real time.
- Records are **time-ordered and de-duplicated**. Retention up to **24 hours**.
- Serverless; **uses no table capacity** for compute or storage.
- Read with the **Keyspaces Streams API** (endpoint `cassandra-streams.<region>.api.aws`). Billed per `GetRecords` call (**streams read request units**, up to 1 MB each).
- Encrypted with the same key as the table.
- Uses: send changes to OpenSearch, Redshift, S3; fraud detection; IoT event reactions; continuous archival; ML feature updates.
- Provisioned tables with CDC enabled: default write quota **40,000**.
- CDC settings are **not restored** by PITR.
- Metrics: `ReturnedRecordsCount`, `SuccessfulRequestLatency`, `SystemErrors`, `UserErrors` (CDC dimensions `StreamLabel`).
- Compare: DynamoDB Streams (24 h), Neptune Streams (7 days default, up to 90), DocumentDB change streams.

## F. Security (verified)
- **Encryption at rest**: **AES-256**, always on for new tables. Key choice: **AWS owned key** (default, no charge) or **customer managed KMS key** (KMS charges). Envelope encryption with a key hierarchy.
- Switch between the two keys: up to **4 times per 24 hours per table** (+1 per 6 hours after) = max **8 per day**. Switching **to the AWS owned key** has no limit.
- If Keyspaces loses access to your customer managed key, the table becomes inaccessible (and may be deleted by the service after a period – verify). Keep the key enabled and the grant intact.
- **Encryption in transit**: **TLS required** for every connection (min TLS 1.2). Server certificates chain to **Amazon Trust Services Root CAs 1–4**. Driver must trust these.
- **Authentication**:
  - **IAM SigV4 plugin** for Cassandra drivers using IAM user keys or **temporary credentials from a role** (recommended).
  - **Service-specific credentials** (username/password generated for an IAM user) for drivers that don't support the plugin. (verify wording)
- **Authorization** with IAM policies at keyspace/table level. Typical actions: `cassandra:Select`, `Modify`, `Create`, `Alter`, `Drop`. Drivers also need read access to **system tables** (verify exact permissions).
- No Cassandra roles/GRANT: **security settings are replaced by IAM**.
- **Network**: public service endpoints over TLS, or **interface VPC endpoints (AWS PrivateLink)** for private access from a VPC. No security group on the table itself; control access with IAM + VPC endpoint policies.
- **Audit**: **CloudTrail** logs control-plane and PITR/table operations. CloudWatch for metrics.
- Compliance: HIPAA, PCI DSS, SOC and others (see compliance page).
- TLS 1.2 required, 1.3 recommended. FIPS endpoints exist in some Regions.

## G. Monitoring (CloudWatch, 1-minute metrics) (verified)
- `ConsumedReadCapacityUnits` / `ConsumedWriteCapacityUnits`: use **Sum ÷ 60** for average per second.
- `ProvisionedReadCapacityUnits` / `ProvisionedWriteCapacityUnits` (5-minute).
- `ReadThrottleEvents` / `WriteThrottleEvents`: requests refused for table, account, per-connection, or partition limits.
- `StoragePartitionThroughputCapacityExceeded`: hot partition (1,000 write / 3,000 read units per second per storage partition).
- `PerConnectionRequestRateExceeded`: more than **3,000 CQL requests/sec on one connection** → open more connections.
- `SuccessfulRequestLatency`, `SuccessfulRequestCount`, `SystemErrors` (server errors, should be 0), `UserErrors` (invalid request).
- `ConditionalCheckFailedRequests` (failed LWT conditions).
- `BillableTableSizeInBytes` (storage cost; 4–6 hour average).
- `TTLDeletes`, `SystemReconciliationDeletes`.
- Account level: `AccountProvisionedReadCapacityUtilization`, `AccountMaxTableLevelReads`, etc.
- `ReplicationLatency` (multi-Region).
- Metrics are kept **15 months**. Use CloudWatch alarms and a CloudFormation dashboard template (GitHub sample).
- Troubleshooting map:
  - Throttling on one table but low average → hot partition; fix the key.
  - Throttling after sudden jump on on-demand → more than double previous peak; ramp up.
  - Provisioned throttling → raise capacity or enable auto scaling.
  - Driver `NoHostAvailableException` after throttles → capacity problem, not network.
  - Connection errors → TLS/CA bundle, port 9142, wrong region endpoint, or IAM credentials.

## H. Migration and integration (verified)
- **Offline migration**: `cqlsh COPY FROM` (small/test data), **DSBulk** (more robust), **AWS Glue** ETL (large; transform), **Spark Cassandra connector**.
- **Online migration (near zero downtime)**: **dual writes** (for example with MSK/Kafka), **CQLReplicator** (near real-time copy), **ZDM Dual Write Proxy**.
- Plan: break into **by cluster / keyspace / table / data subset**; migrate easy, offline-friendly data first.
- Use the Keyspaces **pricing calculator** (GitHub) with `nodetool status` numbers to compare cost.
- Cassandra `nodetool` features, compaction settings, and secondary indexes don't carry over → redesign.
- Integrates with: **IAM**, **KMS**, **CloudWatch**, **CloudTrail**, **CloudFormation**, **Application Auto Scaling**, **VPC endpoints**, **Glue**, **Spark/EMR**, **Kafka/MSK**, **CDC → OpenSearch/Redshift/S3**.
- **Lambda** and apps connect with Cassandra drivers (SigV4 plugin) from inside or outside a VPC; reuse the session and keep connections warm.

## I. Cost (verified model)
- **On-demand**: pay per RRU and WRU consumed.
- **Provisioned**: pay per RCU/WCU-hour provisioned (auto scaling lowers waste). (verify reserved capacity option)
- **Storage**: billed on table size (`BillableTableSizeInBytes`), per GB-month.
- **PITR**: per GB-month of table size when enabled; restore billed per GB restored.
- **TTL**: per TTL delete unit (KB deleted).
- **Multi-Region**: writes billed in every Region.
- **CDC streams**: per streams read request unit.
- **Data transfer**: inbound free; same-Region to other AWS services free; cross-Region charged on both sides; no extra charge for multi-Region replication itself.
- **Free tier** (doc): 30 million on-demand read/write units per month and 1 GB storage for 3 months.
- Save money: LOCAL_ONE reads when staleness is OK (half price); small rows (fit in 1 KB writes / 4 KB reads); TTL to remove old data; provisioned + auto scaling for steady load; avoid `ALLOW FILTERING` scans; only enable PITR where needed.

## J. Limits and numbers to remember
- Keyspaces per Region: **256**; tables per Region: **256** (adjustable).
- Row size: **1 MB**. Static data per partition: **1 MB**.
- Partition key: **2,048 bytes**. Clustering key: **850 bytes**.
- Table schema size: **350 KB**. Concurrent DDL operations: **50**.
- Queries per connection: **3,000/sec**. Per storage partition: **1,000 write / 3,000 read units per sec**.
- Per-table throughput default: **40,000 read and 40,000 write** units/sec. Account provisioned total: **80,000 each**.
- Logged batch **100** statements / **4 MB**; with static columns **50**; unlogged batch **30**.
- `IN` subqueries: **100**. Columns in INSERT/UPDATE: **225** (**166** with TTL). Nested frozen collections: **8**.
- PITR window **35 days**; concurrent restores **4**; **5 TB**/24 h restored.
- TTL physical delete: usually within **10 days**.
- CDC retention: **24 hours**.
- Encryption key switches: **4 per 24 h** then +1 per 6 h.
- Provisioned decreases: **27 per day** max.
- Port **9142** (CQL, TLS); **443** (SDK/CLI).
- Mode switch to on-demand: **once per 24 h**.

## K. Common traps
- Using unsupported consistency levels (QUORUM, ALL, SERIAL).
- Expecting secondary indexes, materialized views, UDFs or TRUNCATE.
- Hot partition key → throttling even with low total traffic.
- Jumping traffic more than 2× previous peak on on-demand.
- Disabling PITR by accident → loses backup history.
- PITR does not restore IAM policies, alarms, CDC streams, or tags.
- Multi-Region: TTL must be set at creation; no customer managed key; writes billed per Region.
- Forgetting the TLS CA bundle or using the wrong port.
- Assuming the writes need a consistency setting: writes are always LOCAL_QUORUM.

## Scenarios (if → then, because)
- **If** traffic is **unknown or spiky**, **then** use **on-demand capacity mode** (the default), where you pay per read and write request. **This works because** there is **no capacity planning**: the table instantly serves up to **double its previous peak**. Going past double within about **30 minutes** can still throttle.
- **If** traffic is **steady and predictable**, **then** use **provisioned capacity mode** with **auto scaling** (Application Auto Scaling, target tracking). **This works because** you pay for the reads and writes per second you set, which is usually **cheaper** than on-demand for steady load, and auto scaling follows the load so you waste less.
- **If** a marketing event will multiply load by **10**, **then** prepare before the event: switch the table to **provisioned mode** with enough capacity, or **pre-warm** it (warm throughput; verify exact feature name and limits), and **ramp traffic up gradually**. **This works because** **on-demand** mode only serves **2× the previous peak** instantly; jumping higher within about 30 minutes causes throttling. Remember that switching from provisioned back to on-demand is allowed only **once per 24 hours**.
- **If** a developer drops the wrong table, **then** restore it with **point-in-time recovery (PITR)**, which keeps continuous backups for **35 days**. The restore always creates a **new table**. **This works because** a deleted table can be restored if **PITR was enabled** and the delete was within 35 days. Do **not** create a new table with the same name first: that makes the deleted one **non-restorable**. Restore also does not bring back IAM policies, CloudWatch alarms, CDC streams or tags.
- **If** you need **active-active** across Regions, **then** use a **multi-Region keyspace**. **This works because** each Region reads and writes locally, and data replicates **asynchronously**, typically in **under 1 second**. Conflicts are solved by **cell-level timestamps** and **Last Writer Wins**. The catch: writes are **billed in every Region**, and there is no synchronous (QUORUM) replication.
- **If** expired records must disappear without extra code, **then** set a **Time to Live (TTL)** on the table, or per row or column with `USING TTL`. **This works because** Keyspaces **hides** expired data from reads immediately and then **deletes** it from storage, usually within **10 days**. Deletes are billed in TTL delete units.
- **If** downstream systems need each change in **near real time**, **then** enable **change data capture (CDC) streams** and send changes to **Amazon OpenSearch Service**, **Amazon Redshift** or **Amazon S3**. **This works because** CDC captures **row-level changes**, time-ordered and de-duplicated, keeps them **24 hours**, and uses **no table capacity**. You read them with the Keyspaces Streams API.
- **If** a Cassandra cluster must move to Keyspaces with **minimal downtime**, **then** use an **online migration**: **dual writes** (for example the **ZDM Dual Write Proxy**) or **CQLReplicator** for near real-time copying, then **cut over** the app. **This works because** both databases stay in sync while you migrate, so the app keeps running until the switch.
- **If** you need to bulk load a **small test set**, **then** use `cqlsh COPY FROM`. For **large** data, use **DSBulk**, **AWS Glue** ETL (which can also transform data) or the **Spark Cassandra connector**, because they are more robust at scale.
- **If** your driver **cannot use the SigV4 plugin** (the plugin that signs requests with AWS Identity and Access Management (IAM) credentials), **then** use **service-specific credentials**, a username and password generated for an IAM user (verify wording). **This works because** they let drivers without the plugin still authenticate through IAM.
- **If** compliance requires **your own encryption key**, **then** encrypt the table with a **customer managed key** in **AWS Key Management Service (KMS)** instead of the default AWS owned key. **This works because** Keyspaces encrypts all data at rest with **AES-256** and lets you choose the key. The catch: **multi-Region tables** cannot use a customer managed key, and if Keyspaces loses access to the key, the table becomes **inaccessible**.
- **If** an **AWS Lambda** function in a **Virtual Private Cloud (VPC)** must reach Keyspaces privately, **then** create an **interface VPC endpoint (AWS PrivateLink)**. **This works because** traffic then stays inside the VPC instead of using the public endpoint. Control access with IAM and **VPC endpoint policies**, since a table has no security group.
- **If** throttling appears while **total throughput is low**, **then** check how the **partition key** spreads traffic, and look at the CloudWatch metric `StoragePartitionThroughputCapacityExceeded`. **This works because** each storage partition allows only about **1,000 write** and **3,000 read units per second**, so one **hot key** can throttle while the table as a whole is quiet. Fix the key design (bucket/salt).
- **If** one driver connection becomes slow at a high request rate, **then** **open more connections**. **This works because** each connection allows only **3,000 CQL requests per second**; above that, Keyspaces refuses requests and shows `PerConnectionRequestRateExceeded`.
- **If** storage cost keeps growing, **then** add **Time to Live (TTL)** to remove old data, **remove unused tables**, and keep **rows small**. **This works because** storage is billed per GB-month on table size (`BillableTableSizeInBytes`), and deleted or expired data stops being billed once it is removed.

## Verified from AWS docs on 2026-10-02
Read: capacity mode pages (on-demand, provisioned, switching), quotas, PITR overview and how it works, multi-Region page and usage notes, TTL page, CDC overview, data protection and encryption at rest, credentials page, endpoints page, metrics page, migration tools page, pricing summary. Not confirmed (verify): pre-warming (warm throughput) details, reserved capacity option, service-specific credentials wording, exact IAM action list and system-table permissions, AWS Backup support, behavior when the customer managed key is lost, TLS 1.3 support for Keyspaces endpoints.

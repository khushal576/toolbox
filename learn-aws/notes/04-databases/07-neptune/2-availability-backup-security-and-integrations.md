# Neptune – 2. High availability, Global Database, backup, security, bulk loader, Streams, search, ML, Analytics

Short notes. Each point is a fact you can be asked about.

## A. High availability inside a Region (verified)
- Storage is replicated across **3 AZs** (six copies). It survives an AZ failure with no data loss.
- **Compute** availability comes from **replicas**. Put at least **one or more replicas in two or more AZs**.
- If the primary fails, Neptune either **promotes a replica** or **creates a new primary**.
- With replicas: failover service is restored **typically in under 120 seconds, often under 60 seconds**. During failover, reads and writes fail with exceptions → apps need **retry logic** and must **reconnect**.
- With **no replicas**: the primary is **recreated**, which typically takes **under 10 minutes**. Much slower → add a replica for production.
- **Promotion tiers 0–15** (0 = highest priority). Highest priority replica is promoted. Same tier → the **largest** instance; if still equal → an arbitrary one.
- Changing a priority does **not** trigger a failover.
- Auto scaling readers get tier **15** (lowest priority) by default.
- Use the **cluster endpoint** for writes and the **reader endpoint** for reads so clients follow failover.
- Open a **new connection after failover** (WebSocket clients keep old connections open).
- Disable **DNS caching** in clients so they pick up the new primary.
- Multi-AZ is **not a backup**. Replicas copy mistakes.

## B. Read-replica auto scaling (verified)
- Uses **Application Auto Scaling** with a **target tracking policy** on average reader **CPUUtilization** (predefined metric `NeptuneReaderAverageCPUUtilization`).
- Needs a cluster with **one writer and at least one reader**, all readers `available`.
- Register scalable target: `min-capacity` / `max-capacity` (0–15 readers; at least one reader must exist).
- Policy fields: `TargetValue` (for example 60%), `ScaleOutCooldown`, `ScaleInCooldown` (default 300 s), `DisableScaleIn`.
- Damping: scale-out alarm needs a breach for at least **3 minutes**; scale-in alarm **15 minutes**.
- New readers use the same class as the writer unless you set `neptune_autoscaling_config` (instance class, maintenance window, tags).
- Auto scaling **only removes readers it created** (named `autoscaled-reader-...`, tag `autoscaled-reader=TRUE`).
- Enabled with the **AWS CLI/API only** (not the console).
- Not supported in a few Regions (Cape Town, UAE, GovCloud).
- Neptune Serverless reacts faster to spikes; auto scaling suits stable trends. They can be combined if max NCU is set high.

## C. Neptune Global Database (verified)
- **One primary cluster** in one Region (read/write) + up to **5 secondary Regions** (read-only). Each secondary can have up to **16 readers**.
- Replication is **storage-level**, typically **under 1 second** lag. Writer/reader CPU is not used for replication.
- Use for: **low-latency reads** worldwide, and **Region-failure DR** (lower RTO/RPO than ordinary cross-Region copies).
- Two failover types:
  - **Managed planned failover**: for maintenance; moves the primary to a secondary Region with **no data loss**.
  - **Unplanned detach-and-promote**: after a Region outage, detach a secondary and promote it to a standalone primary.
- Limits:
  - Only in some Regions (list in docs).
  - Not for **db.t3.medium / db.t4g.medium**.
  - **No auto scaling for secondary clusters.**
  - Cannot stop/start clusters individually.
  - A primary writer restart used to restart secondary readers; from engine **1.4.0.0** secondary readers stay available (**survivable replicas**).
  - Apply custom parameter groups per Region after a major upgrade.
- Metrics: `GlobalDbDataTransferBytes`, `GlobalDbReplicatedWriteIO`, `GlobalDbProgressLag`.
- Billing: replicated write I/O and data transfer.
- Other DR options: **cross-Region snapshot copy** (higher RPO) or **Neptune Streams** cross-Region replication.

## D. Backup and restore
- **Automated backups**: continuous, to S3, **no performance impact**. Retention **1–35 days** (verify default). Enable **point-in-time restore (PITR)** within that window.
- **Manual snapshots**: stay until you delete them. Use before big changes and for long retention beyond 35 days.
- Restore always creates a **new cluster** (new endpoints; reattach parameter group, security groups; add instances).
- Snapshots can be **copied to other Regions** and **shared with other accounts**. Encrypted snapshots follow KMS key rules (share requires a customer managed key and key access – verify).
- **Cloning** (copy-on-write fast clone) for test/dev without full copy (verify availability and limits).
- Backup storage is free up to **100% of your cluster storage** (pricing page); beyond that billed. Metrics: `BackupRetentionPeriodStorageUsed`, `SnapshotStorageUsed`, `TotalBackupStorageBilled`.
- Take a **final snapshot** when deleting a cluster. Turn on **deletion protection** for production.
- To change from unencrypted to encrypted: **snapshot → copy with encryption → restore** (you cannot encrypt in place).
- AWS Backup support for Neptune (verify).

## E. Security (verified)
- **VPC only.** Instances do not allow access from outside the VPC. Use security groups (port 8182), subnet groups, VPN, Direct Connect, peering, or a bastion.
- **Encryption in transit**: **only SSL/TLS (HTTPS)** since engine **1.0.4.0**. **TLS 1.2** with strong cipher suites required; **TLS 1.3** supported from engine **1.3.2.0**.
- **Encryption at rest**: **AWS KMS**. It encrypts storage, **automated backups, snapshots, and replicas** of that cluster. Choose it at **creation**; cannot be disabled afterwards (verify). Default or customer managed key.
- **IAM database authentication** (optional, enable on the cluster):
  - Every request must be **signed with SigV4**. There is **no username/password** access control in Neptune.
  - Neptune authenticates **at connection time**; for WebSockets it re-checks permissions periodically.
  - **Revoking/deleting/rotating credentials does not close connections already open.**
  - With IAM auth, a WebSocket connection is closed **a few minutes after 10 days**.
  - From engine **1.2.0.0**, use IAM **condition keys for query-level actions** (fine-grained: read, write, delete). Before 1.2.0.0, IAM auth controls access at DB cluster level only.
  - Data actions are in the `neptune-db:*` family (for example read data, write data, delete data, StartLoaderJob; verify names).
  - Management actions (`rds:*`/`neptune` API) are separate from data access.
- Neptune console needs **NeptuneReadOnlyAccess**-like permissions for viewing.
- **Service-linked role** for Neptune and for Application Auto Scaling.
- **Interface VPC endpoints (PrivateLink)** for the management API.
- **Audit**: CloudTrail for API calls; **audit logs** can be exported to CloudWatch Logs (verify).
- Do not put sensitive text in names/tags (they appear in logs/billing).
- Neptune does not offer fine-grained row-level security inside the graph; control access by cluster/IAM or separate clusters/graphs.
- Compliance: HIPAA, PCI, SOC, etc. (see compliance page).

## F. Bulk loader (verified)
- **Loader command** loads files from **S3** directly into Neptune: faster, less overhead than millions of `INSERT`/`addV`/`addE` calls.
- Steps: put files in S3 → IAM role with **read/list on the bucket** attached to the cluster → **S3 VPC endpoint** (gateway) in the VPC → send **loader HTTP request** to the Neptune endpoint → Neptune assumes the role and loads.
- Formats:
  - Property graph: **Gremlin CSV** (`csv`) and **openCypher CSV** (`opencypher`). Both can be queried by Gremlin and openCypher.
  - RDF: **N-Triples** (`ntriples`), **N-Quads** (`nquads`), **RDF/XML** (`rdfxml`), **Turtle** (`turtle`).
- Files must be **UTF-8**. Compression: **gzip** (`.gz`) or **bzip2** (`.bz2`), one file each (no `.tar`/`.zip` archives).
- Encrypted S3 data: **SSE-S3 and SSE-KMS** work (role needs `kms:Decrypt`). **SSE-C is not supported.**
- Loader is **not ACID**.
- Limits: **64 bulk load jobs queued**, tracks **last 1,024 jobs**, keeps **last 10,000 error details** per job.
- Best practices: **temporary larger instance** while loading, avoid repeated restarts, split into multiple files for parallelism, same-Region bucket.
- `SPARQL UPDATE LOAD` from a URL works only for resources **inside the same VPC** (for example S3 in the same Region with a VPC endpoint, HTTPS URL, auth in the URL). Prefer the loader API.
- Export/convert: GraphML → Neptune CSV tools exist.
- For databases: **AWS DMS** can migrate some sources into Neptune (verify), and **AWS Glue** can transform to CSV in S3.

## G. Neptune Streams (change log) (verified)
- Logs **every graph change in order**, fully managed. Written **synchronously** with each transaction.
- Guarantees: **strict order, no duplicates, complete**, can rebuild state from a known start.
- Read with an **HTTP REST API** (`GetRecords`-style). Read from writer or replicas; no limit on concurrent readers.
- **Retention**: default **7 days**; from engine **1.2.0.0** set `neptune_streams_expiry_days` **1–90 days**.
- Enable/disable with the cluster parameter. **Disabling makes all log data inaccessible immediately.**
- Costs: extra **I/O and storage**; slight **write performance** reduction.
- **No native Lambda trigger** (stream doesn't generate Lambda events). Run a poller (Lambda on a schedule, ECS, etc.).
- Highly durable (multi-AZ), encrypted like data, backed up with PITR.
- Uses: notify on changes, keep OpenSearch/ElastiCache/S3 copies in sync, **cross-Region replication for DR**, audit.
- Compare: DynamoDB Streams (24 h), Keyspaces CDC (24 h).

## H. Full-text search with OpenSearch (verified)
- Neptune integrates with **Amazon OpenSearch Service** (also **OpenSearch Serverless** from engine 1.3.0.0) for **full-text search** in Gremlin and SPARQL queries.
- Uses **Neptune Streams** + a poller to replicate data to OpenSearch (CloudFormation stack available).
- **Blank nodes are not replicated.** If OpenSearch has fine-grained access control, enable **IAM auth** in Neptune.
- Needs Elasticsearch 7.1+ / OpenSearch 2.3+.
- Use when users need keyword search plus graph traversal.

## I. Neptune ML (verified)
- Uses **graph neural networks (GNNs)** with **Amazon SageMaker AI** and **Deep Graph Library (DGL)** to learn from graph structure.
- Inference tasks: **node classification**, **node regression**, **edge classification**, **edge regression**, **link prediction**.
- Models: **GNN (R-GCN)** for all tasks; **knowledge graph embedding (TransE, DistMult, RotatE)** for link prediction only; your own custom models.
- **Transductive** (pre-computed at training) vs **inductive** (computed in real time on current data) inference.
- Classification supports **string** values only.
- Examples: recommend products, predict fraud, predict links (drug-disease), predict node properties.
- Flow: export graph data → train in SageMaker → get predictions through Gremlin/SPARQL/openCypher queries.

## J. Neptune Analytics integration (awareness)
- Load graph data **from a Neptune Database cluster/snapshot or from S3** into an in-memory Neptune Analytics graph.
- Run **graph algorithms**, low-latency analytical queries and **vector similarity** inside graph traversals.
- Good fit for **GenAI graph retrieval (GraphRAG)** combining embeddings and relationships (verify exact Bedrock integration).
- Priced by memory-based **m-NCU**; can be paused to save cost (verify the exact paused price).

## K. Other integrations to remember
- **Amazon SageMaker AI notebooks / Neptune Workbench (Jupyter)**: explore the graph with visualization; notebooks have instance-hour cost.
- **AWS Lambda / ECS / EKS**: apps inside the VPC connect via Gremlin/openCypher/SPARQL clients. Reuse connections; handle failover; use IAM auth with temporary credentials.
- **CloudWatch** metrics and logs; **CloudTrail**; **EventBridge/SNS events** for cluster events (verify).
- **AWS CloudFormation** for clusters and for the OpenSearch/Streams poller.
- **S3** for loader, snapshots export is not offered the same way as Aurora (verify export options).

## Scenarios (if → then, because)
- **If** production must survive an **Availability Zone (AZ)** failure, **then** run the cluster with one or more **replicas** in two or more AZs. **This works because** storage is already copied **six ways across 3 AZs**, but compute is not: only a replica can quickly take over as the new primary. Remember Multi-AZ is **not a backup**, because replicas copy mistakes too.
- **If** failover must be fast, **then** keep at least one replica. **This works because** with replicas Neptune **promotes** one, and service is back **typically in under 120 seconds, often under 60**. With no replica, Neptune must **recreate** the primary, which typically takes **under 10 minutes**. Apps still need **retry logic** and must reconnect during failover.
- **If** a specific replica must take over first, **then** give it **promotion tier 0**, the highest priority (tiers run **0–15**). **This works because** Neptune promotes the highest-priority replica; within the same tier it picks the largest instance. Changing a tier does not trigger a failover.
- **If** read load grows slowly, **then** use **read-replica auto scaling**, which adds or removes readers with **Application Auto Scaling** based on average reader CPU; if load spikes quickly, use **Neptune Serverless** with a high maximum **Neptune Capacity Unit (NCU)** setting. **This works because** auto scaling suits stable trends (it waits for a **3-minute** breach before adding readers), while Serverless reacts faster to spikes. Both can be combined if max NCU is set high.
- **If** you need **disaster recovery (DR)** in another Region with very small lag, **then** use **Neptune Global Database**: one read/write primary cluster plus up to **5 read-only secondary Regions**. **This works because** replication happens at the **storage level**, typically in **under 1 second**, and does not use instance CPU. After a Region outage you detach a secondary and promote it to primary.
- **If** you only need cheap, cold DR, **then** copy **snapshots** to another Region. **This works because** snapshots can be copied across Regions and restored only when needed. The catch: the **Recovery Point Objective (RPO)**, the amount of recent data you can lose, is higher than with Global Database or Neptune Streams replication.
- **If** someone deleted data by mistake, **then** use **point-in-time restore (PITR)** to a moment before the delete, within the backup retention window (**1–35 days**, verify). **This works because** automated backups are continuous. Restore always creates a **new cluster** with new endpoints, so you reattach parameter and security groups and add instances.
- **If** an auditor requires encryption, **then** turn on **encryption at rest** with **AWS Key Management Service (KMS)** when you create the cluster; it covers storage, automated backups, snapshots and replicas. For an existing unencrypted cluster, take a **snapshot**, **copy it with encryption**, then **restore**. **This works because** you cannot encrypt a cluster in place (encryption set only at creation: verify).
- **If** apps must not hold passwords, **then** enable **Identity and Access Management (IAM) database authentication** and give apps IAM roles. **This works because** every request is signed with **Signature Version 4 (SigV4)**, and Neptune has no username/password access control. The catch: revoking or rotating credentials does not close connections already open.
- **If** you need to restrict a role to read-only queries, **then** use an **Identity and Access Management (IAM)** policy with **query-action condition keys** (read, write, delete). **This works because** from engine **1.2.0.0** IAM can control access per query action; before that, IAM auth works only at the cluster level.
- **If** you must load billions of rows from **Amazon Simple Storage Service (S3)**, **then** use the Neptune **bulk loader**: put files in S3, attach an IAM role with read/list on the bucket, add an **S3 VPC endpoint** (gateway), and send a loader HTTP request to Neptune. **This works because** the loader reads S3 directly, with far less overhead than millions of single insert calls. The catch: the loader is **not ACID**.
- **If** load files are `.zip`, **then** they are not supported; repack them as single **gzip** (`.gz`) or **bzip2** (`.bz2`) files. **This works because** the loader accepts one compressed file each, not archives such as `.zip` or `.tar`.
- **If** data in S3 is encrypted with **server-side encryption with customer-provided keys (SSE-C)**, **then** the loader cannot read it; use **SSE-S3** or **SSE-KMS** instead, and give the loader role `kms:Decrypt` for SSE-KMS.
- **If** downstream systems need every change in order, **then** use **Neptune Streams**, a managed change log of every graph change. **This works because** it is written with each transaction and guarantees **strict order, no duplicates and completeness**. Retention is **7 days** by default, settable to **1–90 days** from engine 1.2.0.0. Disabling Streams makes the log unreadable at once.
- **If** you need **AWS Lambda** to react to changes, **then** run a poller (for example a scheduled Lambda) that reads Neptune Streams. **This works because** Streams has **no native Lambda trigger**; it is read through an HTTP REST API.
- **If** users need keyword search in a graph, **then** integrate **Amazon OpenSearch Service**. **This works because** **Neptune Streams** plus a poller copies the data to OpenSearch, which then serves full-text search inside Gremlin and SPARQL queries. The catch: **blank nodes are not replicated**.
- **If** you need predictions on graph data (fraud, recommendations), **then** use **Neptune ML**. **This works because** it trains **graph neural networks (GNNs)** in **Amazon SageMaker AI** that learn from the graph structure, and you get predictions such as node classification or link prediction through normal Gremlin, SPARQL or openCypher queries.
- **If** analysts need heavy algorithms over a huge graph, **then** use **Neptune Analytics**, which loads data from a Neptune Database cluster, a snapshot or S3 into an **in-memory** graph. **This works because** it runs graph algorithms and vector similarity fast in memory, while Neptune Database keeps serving the app. It is priced by memory-based **m-NCU** and can be paused to save cost.
- **If** a global app needs local reads, **then** add **Neptune Global Database** secondary Regions near the users. **This works because** each secondary (up to **16 readers**) receives data with typically **under 1 second** lag. The catch: secondaries are **read-only**, so writes still go to the primary Region.

## Verified from AWS docs on 2026-10-02
Read: fault tolerance page, global database page, auto scaling page, data protection page index, IAM authentication page, limits page, bulk loader overview and formats, Streams page, ML page, full-text search page, Neptune Analytics pages. Not confirmed (verify): automated backup default retention (1–35 days range from summary), cloning details, AWS Backup support, snapshot sharing key rules, whether encryption can only be set at creation, audit log export, exact `neptune-db` action names, DMS/Glue source support, EventBridge events, snapshot export to S3, Analytics m-NCU pause price.

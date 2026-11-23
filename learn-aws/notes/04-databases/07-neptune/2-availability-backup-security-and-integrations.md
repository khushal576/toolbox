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
- If production must survive an AZ failure → cluster with one or more replicas in other AZs, because storage already spans AZs but compute needs replicas.
- If failover must be fast → keep replicas (failover under 120 s, often under 60 s), because recreating a primary can take up to 10 minutes.
- If a specific replica must take over first → give it promotion tier 0.
- If read load grows slowly → read-replica auto scaling on CPU; if it spikes quickly → Serverless with a high max NCU.
- If you need DR in another Region with seconds of lag → Neptune Global Database (up to 5 secondary Regions).
- If you only need cheap cold DR → copy snapshots to another Region (higher RPO).
- If someone deleted data by mistake → PITR within the retention window to a new cluster.
- If an auditor requires encryption → encryption at rest with KMS at creation; for an existing cluster do snapshot → copy encrypted → restore.
- If apps must not hold passwords → IAM database authentication with SigV4 and roles (Neptune has no passwords).
- If you need to restrict a role to read-only queries → IAM policy with query-action condition keys (engine 1.2.0.0+).
- If you must load billions of rows from S3 → bulk loader with an IAM role and an S3 VPC endpoint.
- If load files are `.zip` → not supported; use `.gz`/`.bz2` single files.
- If data is encrypted with SSE-C in S3 → the loader cannot read it; use SSE-S3 or SSE-KMS.
- If downstream systems need every change in order → Neptune Streams (retention up to 90 days).
- If you need Lambda to react to changes → poll the stream (no native trigger).
- If users need keyword search in a graph → OpenSearch integration via Streams.
- If you need predictions on graph data (fraud, recommendations) → Neptune ML.
- If analysts need heavy algorithms over a huge graph → Neptune Analytics.
- If a global app needs local reads → Global Database secondary Regions (read-only).

## Verified from AWS docs on 2026-10-02
Read: fault tolerance page, global database page, auto scaling page, data protection page index, IAM authentication page, limits page, bulk loader overview and formats, Streams page, ML page, full-text search page, Neptune Analytics pages. Not confirmed (verify): automated backup default retention (1–35 days range from summary), cloning details, AWS Backup support, snapshot sharing key rules, whether encryption can only be set at creation, audit log export, exact `neptune-db` action names, DMS/Glue source support, EventBridge events, snapshot export to S3, Analytics m-NCU pause price.

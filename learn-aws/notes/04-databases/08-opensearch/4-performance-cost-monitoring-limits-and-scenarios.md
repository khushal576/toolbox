# OpenSearch – 4. Performance, cost, monitoring, troubleshooting, limits, traps and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Performance: indexing (write) tuning
- **Use the Bulk API**, not one request per document. Batch size is tuned by testing (commonly a few MB up to ~15 MB). (general practice, verify)
- **Max HTTP payload**: 10 MiB on small instances (t2/t3, many `.large`), 100 MiB on bigger (limits page).
- **Parallelize** bulk requests across several clients/threads. Back off on `429 Too Many Requests` (thread pool queue full).
- **Increase refresh interval** (for example 30 s) or set `-1` during large loads; restore after. Fewer refreshes = faster indexing. (general practice)
- **Reduce replicas to 0 during initial bulk loads**, then raise back (re-create copies after). Only if you can recover from source.
- **Use auto-generated IDs** when you don't need updates (avoids lookups).
- **Right-size shards** (30–50 GiB for logs). Too many tiny shards waste CPU/heap.
- **Time-based indexes + rollover** keep shards in the target size range and make deletes cheap.
- **Disable dynamic mapping explosions**: control the number of fields (`mapping.total_fields.limit`) and use explicit mappings.
- **Use gp3 / Provisioned IOPS / instance store** for faster I/O. Instance-store types (I3, Im4gn, R6gd) give the best write throughput.
- **OpenSearch Optimized (OR1/OR2)** instances target high-ingest log workloads (verify).
- Watch `IndexingLatency`, `ThreadpoolWriteQueue`, and write rejection metrics (`CoordinatingWriteRejected`, `PrimaryWriteRejected`, `ReplicaWriteRejected` on 7.1+).

## B. Performance: search tuning
- **Use filters (`filter` context, `term`, `range`) for exact conditions** — they are cached and unscored. Use `match` only for relevance.
- **Avoid wildcard-leading queries and deep pagination** (`from + size` large). Use `search_after` or scroll/PIT for deep paging.
- **Fewer, larger shards** → fewer shard hits per query. Keep shard size 10–30 GiB for search-heavy workloads.
- **More replicas** raise read throughput (and availability) but cost storage.
- **Use `_source` filtering**; return only needed fields.
- **Use aliases and routing** (custom routing) to send a query to fewer shards. (general practice)
- **Force-merge** read-only indexes to fewer segments (also done during UltraWarm migration).
- **Coordinator nodes** offload request routing/aggregation from data nodes.
- **Cache**: node query cache and request cache help repeated filters/aggregations.
- **JVM heap**: 50% of RAM up to 32 GiB. Keep `JVMMemoryPressure` below ~80% (verify). Heavy aggregations on `text` fields are costly — use `keyword`.
- **Warm tier** search is slower; keep hot data in hot tier.
- **Auto-Tune** adjusts queue sizes/JVM automatically (required for Multi-AZ with Standby).
- For **vector search**: choose HNSW for speed, IVF/quantization for memory; keep graphs inside off-heap memory budget (see file 2); watch `KNNGraphMemoryUsage`.
- **Slow logs** (search and indexing) show the queries to optimize.
- Test with representative data before choosing instance types.

## C. Cost model (verified)
- **Provisioned domain** = instance hours + **EBS volume size** (provisioned, even if empty) + data transfer. Instance-store types need no EBS.
- **Data transfer**: standard AWS rules, **except** traffic **between AZs in a Multi-AZ domain is free**, shard rebalancing traffic is free, and **UltraWarm/cold ↔ S3 is free**.
- **UltraWarm**: pay for **warm node hours + S3 data stored** (used, not provisioned). Cheaper than hot for old data.
- **Cold storage**: pay for stored data only (no compute node while idle). Moving back to warm is free.
- **Dedicated master / coordinator nodes**: billed hourly like others.
- **Serverless**: OCU-hours (indexing and search) + S3 storage. Min OCU > 0 costs even when idle; min 0 costs nothing idle.
- **OpenSearch Ingestion**: Ingestion OCU-hours (stop pipelines to save).
- **Extended support** surcharge on old versions (instance-cost equal, or $0.0065 per Normalized Instance Hour in us-east-1). Upgrade to avoid.
- **Reserved Instances** (1 or 3 years) cut instance cost for steady workloads (verify current terms).
- Usage type codes in the bill: `ESInstance`, `EBS`, `ServerlessOCU`, `IngestionOCU`.
- Savings levers:
  - **Graviton** (m6g/r6g/r7g/r8g) + **gp3** storage.
  - **ISM**: move to UltraWarm/cold, delete old indexes.
  - **Reduce replicas** on old data (e.g., 0 replicas after 7 days if you can re-create) — ISM `replica_count`.
  - **Right-size**: remove idle capacity; avoid over-sharding.
  - **Compression** (best compression codec for logs, verify) and **drop unused fields**.
  - **Use OpenSearch Optimized instances** for log-heavy work (verify).
  - **Serverless** for spiky/dev workloads; stop/pause what you don't use.
  - **Archive to S3 + Athena** for cold, rarely searched data.
  - **Sample / filter logs** before ingesting (ingestion pipeline filtering).

## D. Monitoring (verified metrics)
- Metrics are sent to CloudWatch every **60 seconds** (EBS volume metrics every 5 minutes for gp2/magnetic). CloudWatch metrics for the domain are retained **two weeks** in the console graphs. Cumulative metrics (rejections) **reset on node restart/replacement/blue-green**.
- **Cluster health**: `ClusterStatus.green / yellow / red` (value 1 = state). Alarm on red ≥ 1 and yellow ≥ 1 for several minutes.
- `Shards.active`, `Shards.unassigned`, `Shards.initializing`, `Shards.relocating`, `Nodes`, `SearchableDocuments`.
- **Storage**: `FreeStorageSpace` (per node; a `ClusterBlockException` is thrown when it reaches 0). Recover by deleting indexes, adding larger instances/EBS. **`ClusterIndexWritesBlocked` = 1** means writes are blocked (low disk or high JVM pressure).
- **Memory**: `JVMMemoryPressure` (max heap % across data nodes). High → add memory/nodes, reduce shards/fielddata.
- **CPU**: `CPUUtilization` (max and average). Also `HighSwapUsage` = swapping (bad).
- **Latency**: `SearchLatency`, `IndexingLatency`.
- **Rejections**: `ThreadpoolSearchRejected`, `ThreadpoolWriteRejected` (growing = scale), `ThreadpoolWriteQueue`.
- **HTTP**: `2xx`, `3xx`, `4xx`, `5xx` counts. `OpenSearchRequests`.
- **Master**: `MasterReachableFromNode` (0 = master unreachable, usually network/AWS dependency problem), `MasterCPUUtilization`, `MasterJVMMemoryPressure`.
- **Snapshots**: `AutomatedSnapshotFailure` = 1 means **no automated snapshot in the last 36 hours**.
- **KMS**: `KMSKeyError` = key disabled → **re-enable** to recover. `KMSKeyInaccessible` = key **deleted or grant revoked** → **domain cannot be recovered**; use a manual snapshot to migrate data to a new domain.
- **k-NN**: `KNNGraphMemoryUsage`, `KNNCacheCapacityReached`, etc. (verify names).
- **UltraWarm**: `WarmCPUUtilization`, `WarmJVMMemoryPressure`, `WarmFreeStorageSpace` (use Sum), `HotToWarmMigrationQueueSize`, `WarmToHotMigrationQueueSize`.
- **Serverless**: `SearchOCU`, `IndexingOCU`, plus collection-level request and latency metrics.
- **Ingestion**: pipeline metrics in CloudWatch + error logs in CloudWatch Logs.
- Logs to CloudWatch Logs: **search slow logs, index slow logs, error logs, audit logs** (audit needs FGAC).
- **EventBridge** for domain events; **CloudTrail** for configuration API calls.
- **Recommended alarms** (AWS publishes a table; typical values, verify): `ClusterStatus.red ≥ 1` (1 min), `ClusterStatus.yellow ≥ 1` (5 min), `FreeStorageSpace` low (below ~20% of node storage), `ClusterIndexWritesBlocked ≥ 1`, `JVMMemoryPressure ≥ 95%` (or 80%), `CPUUtilization ≥ 80%` (several periods), `Nodes` below expected, `MasterReachableFromNode < 1`, `AutomatedSnapshotFailure ≥ 1`, `KMSKeyError`/`KMSKeyInaccessible ≥ 1`, thread pool rejections.

## E. Troubleshooting map (symptom → cause → fix)
- **Red status** → unassigned primary shard (lost node without replica, disk, allocation) → check `_cluster/allocation/explain`, restore from automated snapshot, add capacity. Fix quickly: snapshots and ISM stop while red.
- **Yellow status** → replicas can't be allocated (not enough nodes/AZs, disk) → add nodes or reduce replicas.
- **Writes rejected / `ClusterBlockException` / 429** → disk watermark hit or thread pool full → add storage, delete old indexes, scale, slow down clients, use bulk.
- **`FORBIDDEN/12/index read-only / allow delete`** → flood-stage disk watermark → free space; the block may need clearing after space is available (verify).
- **JVM memory pressure high / OutOfMemoryError** → too many shards, big aggregations, big fielddata, undersized heap → fewer shards, bigger instances, close unused indexes, tune queries.
- **High CPU** → heavy queries/aggregations, too much indexing, too few nodes → optimize queries, add nodes, split workloads (coordinator nodes).
- **Slow searches** → large shards or too many shards, no caching, unfiltered queries, UltraWarm cache misses → tune shards, use filters, move hot data back.
- **Node dropped / `MasterNotDiscovered`** → network problem, master overloaded, no quorum → check masters (3 recommended), sizing of masters for shard count, `MasterReachableFromNode`.
- **Unauthorized/403 `security_exception`** → missing FGAC role mapping, signing mismatch, domain policy → map roles, sign with SigV4 or use basic auth consistently.
- **Dashboards stuck "server is not ready yet"** → `rest.action.multi.allow_explicit_index` set to false, or broken Dashboards index → set to true.
- **Cannot connect to VPC domain** → computer not in VPC, security group, DNS resolution, subnet routing → use VPN/proxy/SSH tunnel; allow 443 from the client SG.
- **Snapshot registration fails** → missing `iam:PassRole`, trust policy not `es.amazonaws.com`, unsigned request.
- **Blue/green change stuck** → not enough capacity/IPs in subnets, shard allocation problems, health not green → fix health, free IPs, retry.
- **Domain upgrade fails** → breaking changes, red cluster, not enough free storage → run upgrade eligibility checks, take a manual snapshot before upgrade.
- **Serverless "ThrottlingException"/capacity** → max OCU cap reached → raise max OCU or lower load.
- **Ingestion pipeline errors** → permissions on source/sink, FGAC role mapping for the pipeline role, DLQ configuration.

## F. Limits and numbers to remember (verified)
- Data nodes: up to **1,002** per domain (3-AZ, newer engines/families); **334 per AZ**. UltraWarm nodes up to **750** (3-AZ). Total node limits depend on instance family (Graviton default **80**, T2/T3 **10**) and are adjustable.
- Storage: up to **25 PB** per domain (doc number).
- **Dedicated masters: 3** (recommended); 1 not allowed; sizing by RAM.
- Shards: default **5 primaries + 1 replica** per index; **1,000 shards per node** (≤ 2.15); **1,000 per 16 GB heap, max 4,000** (2.17+); Standby: **75,000 per cluster**, **shard ≤ 65 GB**.
- Shard size guidance: **10–30 GiB** (search), **30–50 GiB** (logs). **≤ 25 shards per GiB heap**.
- JVM heap = **50% RAM, up to 32 GiB**.
- **HTTP payload**: 10 MiB (small instances) / 100 MiB (larger).
- **Access policy size**: **100 KiB**.
- **Snapshots**: automated **hourly, 336 retained, 14 days**; `cs-ultrawarm` snapshots **14 days** after index deletion.
- **UltraWarm**: medium **1.5 TiB**, large **20 TiB**; migration queue **200** (to warm), **10** (to hot); `search.max_buckets` **10,000**.
- **Free storage rule**: stay under **80% disk**.
- **Cluster blocked** when `FreeStorageSpace` reaches 0.
- **ISM** job interval **5–8 minutes**.
- **k-NN**: max `k` **10,000**; graph memory budget about **25% of RAM** (32 GiB RAM → ~8 GiB graphs).
- **Serverless**: OCU = **6 GiB**; max **1,700 OCU** (indexing and search) per collection group; **1,000 indexes** per collection; **10 TiB** hot per classic collection; refresh ~10 s.
- **VPC IPs**: **3 × ceil(data nodes ÷ AZs)** per subnet.
- **Extended support** starts after end of standard support (key date **7 Nov 2025** for many old versions, **7 Nov 2027** for ES 7.10/OpenSearch 2.19 and others).
- FGAC migration period: **30 days**.
- IAM/Dashboards: Cognito, SAML, internal DB; JWT for APIs.

## G. Common traps
- Treating OpenSearch as the **system of record**.
- Choosing **too many small shards** or **very large shards** (> 50–65 GiB).
- Using **2 or 4 dedicated masters**; or none for a large production domain.
- Running **one node with replicas** → yellow forever.
- Not sizing for **replicas + overhead** (the 1.45 factor).
- Forgetting **VPC vs public cannot change** later.
- Putting an **IP-based policy on a VPC domain** (not allowed).
- Enabling **FGAC without role mappings** → everyone gets errors.
- Mixing **SigV4 principals in the access policy with basic auth** clients.
- Relying on **resource policy deny** to isolate indexes (bypassed by `_all`, `_bulk`).
- Setting **`allow_explicit_index=false`** and breaking Dashboards.
- Storing **warm data and expecting updates** (warm is read-only).
- Using **T2/T3** for production or with UltraWarm.
- Forgetting **automated snapshots stop while red** (data loss after ~2 weeks).
- **Deleting or disabling the KMS key** (domain unrecoverable if key deleted/grant revoked).
- Using **Glacier** lifecycle on the manual snapshot bucket.
- Assuming **Serverless supports manual snapshots, cross-account or cross-Region**.
- Choosing the wrong **Serverless collection type** (cannot change; k-NN only in vector collections).
- Leaving a **Serverless min OCU > 0** or an **Ingestion pipeline running** when idle.
- Staying on **old engine versions** → extended support charges.

## H. Decision lines (exam style)
- "Full-text search / relevance / autocomplete / typo tolerance" → OpenSearch.
- "Near-real-time log analytics dashboards" → OpenSearch (+ Firehose/Ingestion).
- "Cheap, rare SQL on logs in S3" → Athena.
- "Unpredictable search workload, no ops" → OpenSearch Serverless.
- "Vector search for RAG, keyword + vector hybrid, large scale" → OpenSearch (vector collection/k-NN).
- "Older logs rarely searched, still searchable" → UltraWarm; "archive, rarely read" → cold or S3.
- "Automate retention/tiering" → ISM.
- "Highest availability, production" → Multi-AZ with Standby.
- "Fine-grained, per-field/document access" → FGAC (domain) or data access policies (Serverless).
- "Stream logs to OpenSearch with no code" → Firehose; "parse/enrich/route" → OpenSearch Ingestion.
- "Move domain data to another domain/account" → manual snapshot in S3 + restore.
- "Private-only search domain" → VPC domain with security groups.

## Scenarios (if → then, because)
- If searches slow down as the index grows to thousands of tiny shards → reduce shard count (shrink/reindex), because each shard uses heap and CPU.
- If writes suddenly fail with cluster block → free storage (delete old indexes/add EBS), because FreeStorageSpace hit the watermark.
- If `JVMMemoryPressure` stays above 80% → scale up or out, cut shards/aggregations, because heap is exhausted.
- If logs older than 7 days are queried rarely → ISM to UltraWarm at day 7, cold at day 30, delete at day 365.
- If retention rules require data deletion exactly at 90 days → ISM `delete` after `min_index_age: 90d`, using daily indexes.
- If a data node fails and replicas exist → shards re-allocate to other nodes; domain stays green after recovery, with extra load meanwhile.
- If the whole AZ fails in a 3-AZ domain with Standby → standby activates in under a minute, no data movement.
- If the team only wants to pay when searching → Serverless with min OCU 0.
- If a bulk job needs speed → raise refresh interval, set replicas to 0 temporarily, use parallel bulk.
- If Dashboards users must log in with corporate SSO → SAML (or Cognito with federation).
- If a Lambda writer to a domain with FGAC gets 403 → map its role to a backend role with index permissions.
- If `AutomatedSnapshotFailure` alarm fires → check cluster status (red?) and S3/KMS permissions; fix within days.
- If a KMS key was deleted → data on that domain is unrecoverable via the domain; restore from a manual snapshot to a new domain.
- If a domain runs Elasticsearch 7.10 after 2027 support end → upgrade to OpenSearch to avoid extended-support charges.
- If costs spike → check EBS size, replica counts, over-provisioned masters, extended support, idle Serverless min OCUs, pipelines left running.

## Verified from AWS docs on 2026-10-02
Read: CloudWatch metrics page (from saved output), what-is page (pricing/extended support), limits page, sizing pages, dedicated master page, UltraWarm page, snapshots page, VPC page, access-control and FGAC pages, Serverless scaling page. Not confirmed (verify): recommended alarm thresholds table, bulk size and refresh tuning numbers (general practice), read-only block clearing behavior, Reserved Instance terms, compression codec options, OR1/OR2 behavior, k-NN metric names beyond `KNNGraphMemoryUsage`, JVM pressure alarm threshold (80% vs 95%).

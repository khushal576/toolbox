# OpenSearch – 3. Multi-AZ, storage tiers (UltraWarm, cold), snapshots, VPC, access control, encryption

Short notes. Each point is a fact you can be asked about.

## A. Multi-AZ with Standby (verified)
- Recommended for **production** domains. Offers **99.99% availability**, no extra cost.
- Layout: **3 AZs**, one acting as **standby** (its nodes do not serve search requests).
- Requirements/mandated best practice:
  - **3 dedicated master nodes**, **3 data nodes (or a multiple of 3)**.
  - **At least 2 replicas** per index (so a full copy lives in each AZ; copies = multiple of 3).
  - Current-generation instance types; **Auto-Tune on**.
  - Engine **OpenSearch 1.3+**; Region with **3 AZs**.
  - Instance families allowed include m5, c5, r5, r6g, c6g, m6g, r6gd, r7g, c7g, m7g, r7gd, i3, or1, or2, om2, oi2 (verify full list).
  - Storage: **gp3, Provisioned IOPS SSD, or instance store** only.
  - If UltraWarm is used, **warm node count must be a multiple of the AZ count**.
- On AZ/infrastructure failure the **standby is activated in under a minute**. No data redistribution → performance stays stable.
- Limits with standby: **1,000 shards per node**, **75,000 per cluster**, **max shard size 65 GB**.
- "Easy create" in the console builds this config (3 AZ with standby, 3 masters, 3 data nodes, Auto-Tune, gp3).

## B. Multi-AZ without Standby (verified)
- **99.9% availability**. You choose AZ count (1, 2 or 3), nodes and replicas. Not recommended unless existing workflows require it.
- Need **at least 1 replica** per index, or shards can't be placed in other AZs.
- Shards are spread across AZs on a **best-effort** basis. Odd node counts can overload a node. Use a **multiple of 3** nodes with 3 AZs.
- Behavior when **one AZ fails**:
  | AZs chosen | Dedicated masters | Result |
  |---|---|---|
  | 2 | 0 | **Downtime** (lose half the nodes before a master can be elected) |
  | 2 (Region has 2 AZs) | 3 | **50/50 downtime** (2 masters in one AZ, 1 in the other) |
  | 2 (Region has 3+ AZs) | 3 | **No downtime** (masters placed in 3 AZs) |
  | 3 | 0 | No downtime (about 2/3 of nodes remain) |
  | 3 | 3 | No downtime (2 masters remain) |
- In all cases the remaining nodes face **extra load** while replacements are built; size with headroom.
- You **cannot simulate** an AZ outage manually.
- **Multi-AZ is not a backup.** Replicas copy deletes and bad writes too.

## C. Cluster health and shard states
- **Green**: all primary and replica shards assigned.
- **Yellow**: all primaries assigned, **some replicas unassigned** (data safe but less redundancy). Common on a single-node domain with 1 replica (replica has no other node).
- **Red**: **at least one primary shard unassigned** (data in that shard unavailable). Writes/searches to it fail.
- **While red**: automated snapshots **fail**; ISM jobs **do not run**. If red is not fixed in **about two weeks**, you can **permanently lose data**.
- Common red causes: node lost with no replica, disk full, bad shard allocation, JVM pressure, a failed blue/green change.
- Fix path: restore from the latest automated snapshot, add capacity, fix disk, or delete the broken index and reindex.

## D. Storage tiers (verified)
- **Hot**: EBS or instance store attached to data nodes. Fastest indexing and search.
- **UltraWarm**: read-only data stored in **S3** with a cache layer. Much cheaper per GiB. Best for **immutable data like logs**.
- **Cold storage**: very cheap archive in S3. **Not searchable** until migrated back to warm (free). Cannot read or write directly.
- **OpenSearch Optimized instances** (OR1/OR2/OM2/OI2): data durability backed by S3 on the hot tier. OI2: **80% of local storage is cache**, max addressable warm storage = **5× cache size**.
- Requirements for warm/cold:
  - OpenSearch or Elasticsearch **6.8+** (cold needs 7.9+; verify).
  - **Dedicated master nodes**.
  - **Not** T2/T3 data nodes.
  - Fine-grained access control users need the **`ultrawarm_manager`** role (cold: `cold_manager`) to call the APIs.
  - Encryption at rest and node-to-node encryption (verify for cold).
- **UltraWarm details**:
  - Storage billing is **pay for what you use** (data in S3), not for provisioned capacity. Plus an **hourly rate per warm node**.
  - Counts **primary shards only** for storage (no replicas, no OS overhead). Dashboards/`_cat` still report total including replicas.
  - Instance types: `ultrawarm1.medium` (up to **1.5 TiB** each), `ultrawarm1.large` (up to **20 TiB** each). Warm node limit up to 750 per domain (3-AZ config; table in limits page).
  - Recommended max shard size **50 GiB**. Broad queries over many shards can stress warm CPU. Monitor `WarmCPUUtilization`, `WarmJVMMemoryPressure`.
  - `search.max_buckets` defaults to **10,000** on domains with UltraWarm (not 65,536).
  - Warm indexes are **read-only**. You can query/delete indexes, not update documents.
  - Hot → warm: `POST _ultrawarm/migration/<index>/_warm`. Steps: snapshot, force merge (default to **1 segment**; **20** for k-NN), full snapshot, shard relocation. **Index health must be green.** Indexes stay available during migration.
  - Queue: up to **200 hot→warm migrations**; **10 warm→hot**. Migrations run one at a time. Metrics: `HotToWarmMigrationQueueSize`, `WarmToHotMigrationQueueSize`, `HotToWarmMigrationForceMergeLatency`.
  - Warm → hot: `POST _ultrawarm/migration/<index>/_hot`. Returns with **1 replica**.
  - Warm → cold and back: `cold_migration` (ISM) / API. Cold → warm is **free**.
  - Disable UltraWarm: first delete or move all warm indexes to hot; wait about **5 minutes**.
- **Automate** with an **ISM policy**: hot → warm → cold → delete.
- Choose tiers by access pattern: hot (days, frequent), warm (weeks, occasional), cold (months/years, rare), S3 + Athena (archive, ad-hoc).

## E. Snapshots and restore (verified)
- A snapshot = backup of **indexes and cluster state** (settings, node info, index settings, shard allocation).
- **Automated snapshots**:
  - For **cluster recovery only** (red status or data loss). Stored in a **preconfigured S3 bucket at no charge**.
  - **Hourly**, incremental, **up to 336 retained for 14 days** (OpenSearch/ES 5.3+). (ES 5.1 and earlier: daily, 14 retained, max 30 days.)
  - Cannot change the retention window.
  - Warm indexes have their own repo **`cs-ultrawarm`** (one index per snapshot; kept **14 days** even after you delete the index). Restoring from it brings the index back to **warm**. Snapshots from `cs-automated`/`cs-automated-enc` restore to **hot**.
- **Manual snapshots**:
  - Kept until you delete them. Stored in **your S3 bucket** (standard S3 cost). **No Glacier lifecycle** on that bucket.
  - Used for recovery **or moving data** between domains/self-managed clusters.
  - Needs: S3 bucket, an **IAM role (`TheSnapshotRole`)** trusted by **`es.amazonaws.com`** with S3 permissions, and the caller must have **`iam:PassRole`** on that role plus **`es:ESHttpPut`**.
  - You must **register the repository** with a signed request (cannot use basic auth for registration).
  - With **fine-grained access control**, map **`manage_snapshots`** to the IAM role used for the signed request.
  - Manual snapshots of warm indexes: only **one warm index per snapshot**; cannot mix hot and warm; restore to **hot**. Not recommended (automated `cs-ultrawarm` already exists).
- Automation options: **ISM `snapshot` action** (one snapshot per index), **Snapshot Management** (group of indexes), **Curator**.
- Restore: `POST _snapshot/<repo>/<snapshot>/_restore`. Existing index with same name must be **deleted or renamed** (`rename_pattern`). Restores create/replace indexes inside the domain (no new domain created).
- **Migration**: take a snapshot on source (self-managed) → upload to S3 → register repo on the domain → restore.
- Public → VPC move requires **new domain + snapshot restore or reindex**.
- Snapshots are **not** a replacement for the source of truth; consider the real data in S3/DB.

## F. Network: VPC vs public (verified)
- Choose at **creation**; **cannot switch** (public ↔ VPC) afterwards. Use snapshot/reindex to a new domain.
- **VPC domain**: endpoint `https://vpc-<name>-<id>.<region>.es.amazonaws.com`. Reachable only through the VPC (VPN, Direct Connect, transit gateway, proxy, bastion/SSH tunnel). Security groups control access.
- **Public domain**: endpoint `https://search-<name>-…`. Reachable from the internet; must be protected with access policies + (ideally) fine-grained access control.
- VPC domain rules:
  - **No IP-based access policies** (security groups handle IPs).
  - Cannot use a VPC with **dedicated tenancy**.
  - After creation you can **change subnets and security groups**, but **cannot move to another VPC**.
  - Console shows less info (no Indices/shard details).
  - Needs **service-linked role** `AWSServiceRoleForAmazonOpenSearchService` (created automatically with `iam:CreateServiceLinkedRole`).
  - Subnets must be in **different AZs** when multi-AZ.
- **IP reservation**: OpenSearch Service creates ENIs in your subnets. Reserve **3 × (data nodes ÷ number of AZs, rounded up)** IP addresses per subnet. Example: 9 nodes over 3 AZs → 9 IPs per subnet. Use **dedicated subnets**. **Dedicated coordinator nodes** reduce IP use.
- Resolve the endpoint **periodically** (about once a minute); IPs can change; clear client DNS caches.
- Optional **egress through your VPC** (default egress, e.g., to custom endpoints, goes via public internet).
- **OpenSearch Service-managed VPC endpoints** (PrivateLink) let other VPCs/accounts reach a domain privately (verify).
- Dashboards in a VPC domain also need VPC reachability (proxy or tunnel).

## G. Access control: three layers (verified)
1. **Network**: VPC + security groups, or public.
2. **Domain access policy** (resource-based): allow/deny at the "edge".
3. **Fine-grained access control (FGAC)**: users, roles and mappings **inside** OpenSearch.
- **Policy types**:
  - **Resource-based (domain access policy)**: attached to the domain; has a Principal; actions `es:ESHttp*` (or `es:ESHttpGet/Put/Post…`); resource `…:domain/<name>/*`. The trailing `/*` means **subresources** (indexes/APIs), not the domain config.
  - **Identity-based**: IAM policy on users/roles. Typically for **configuration API** (`es:CreateDomain`, `es:UpdateDomainConfig`, `es:Describe*`). Can use **tags** (`aws:ResourceTag`, `aws:RequestTag`, `aws:TagKeys`).
  - **IP-based**: resource policy with `aws:SourceIp` condition; allows **unsigned** requests (curl, Dashboards via proxy). **Not allowed on VPC domains.**
- Evaluation: **default deny; explicit deny wins; explicit allow overrides default.** If either identity or resource policy allows (and neither denies) → allowed for subresources.
- If a resource policy names IAM principals, clients must **sign requests with SigV4**. This can conflict with **basic auth** (you can't send both).
- With FGAC on, a common setup is an **open-ish domain policy** (principal = account root, action `es:ESHttp*`) and let FGAC decide.
- `aws:SecureTransport` condition can require **HTTPS**.
- Access policy size limit: **100 KiB**.
- **Anonymous access** (`Principal: *`) is dangerous; combine with IP condition, VPC or FGAC.
- Trap: **`rest.action.multi.allow_explicit_index = true`** (default) lets users bypass index-level permissions via `_bulk`/`_mget`/`_msearch` with index names in the body. Setting it **false breaks Dashboards**, so prefer FGAC.
- Trap: a deny on `restricted-index/*` still lets `_all/_search` and index deletion unless you also deny `restricted-index*` — use FGAC for real isolation.

## H. Fine-grained access control (FGAC) (verified)
- Gives **role-based access control**, **index-, document-, and field-level security**, **field masking**, **Dashboards multi-tenancy**, and **HTTP basic auth**.
- Requirements: OpenSearch or Elasticsearch **6.7+**, **HTTPS**, **encryption at rest**, **node-to-node encryption**.
- **Cannot be disabled** once enabled.
- **Master user**: either an **IAM principal** (all requests must be SigV4-signed; IAM permissions on that principal are ignored—only for authentication) or a **user in the internal user database** (username + password; also works with basic auth; stored in an index, not shared across domains).
  - Use IAM master user when you want the same users across domains, Cognito for Dashboards, or SigV4-capable clients.
  - Use internal user database when you need basic auth or no IAM for Dashboards.
- Master user is mapped to **`all_access`** and **`security_manager`** roles. Other admins need both mapped.
- **Roles** (not IAM roles): cluster permissions, index permissions, document-level (query), field-level (include/exclude), field masking (hashed; use pattern-based masking for correct aggregations), tenants.
- **Mapping** attaches roles to **users** and **backend roles** (IAM role ARNs or strings). Without mappings every request gets a permission error.
- Predefined roles help (e.g., `opensearch_dashboards_user`, `readall`, `ultrawarm_manager`, `cold_manager`, `ml_full_access`, `notifications_*`).
- **Enabling on an existing domain**: causes a **blue/green deployment** (health goes red but operations continue). Optional **30-day migration period** for open/IP-based policies (anonymous access continues; auto-ends after 30 days; cannot be re-enabled). With identity-based policies, users are mapped to **`default_role`** temporarily—delete it after creating real mappings.
- **Dashboards login** options: internal DB basic auth, **Amazon Cognito**, **SAML**, **IAM Identity Center**, **JWT** (API calls). IAM master user without Cognito/SAML shows a non-functional sign-in page.
- Limits/quirks: role-mapping `hosts` don't work in VPC domains; SQL error messages can reveal index existence; `max_clause_count=1` breaks domains on 2.3+.
- Other services (Firehose, Lambda, IoT) need their IAM roles **mapped** to FGAC roles with enough permissions (cluster `cluster_composite_ops`, `cluster_monitor`; index `create_index`, `manage`, `crud`).
- Serverless uses **data access policies** instead.

## I. Encryption (verified + notes)
- **Encryption at rest**: optional on domains (required for FGAC, UltraWarm/cold, and for Serverless collections). Uses **KMS** (AWS owned or customer managed key). Encrypts indexes, logs, swap files, automated snapshots, app directory. **Cannot be turned off after enabling; enabling on existing domains needs a new domain or snapshot restore in older versions** (verify current rules).
- **Node-to-node encryption**: TLS between nodes. Required for FGAC. Cannot be disabled after enabling (verify).
- **HTTPS enforcement** (`EnforceHTTPS`) and **TLS security policy** (for example `Policy-Min-TLS-1-2-2019-07`) on the domain endpoint. Custom endpoints supported (ACM certificate).
- TLS 1.2 required; 1.3 recommended for AWS APIs.
- KMS key loss/disable → domain becomes inaccessible. Keep the key and grants.
- Encryption of **snapshots**: automated snapshots encrypted if the domain is encrypted (`cs-automated-enc`).

## J. Audit, logs and compliance
- **Audit logs** (FGAC required): who accessed what (authentication failures, index access, etc.). Sent to **CloudWatch Logs**.
- **Slow logs** (search and index) and **error logs**: publish to CloudWatch Logs; set thresholds per index.
- **CloudTrail**: records **configuration API** calls (not data access).
- **EventBridge**: domain events (service software, Auto-Tune, VPC endpoint changes; verify list).
- **Compliance programs** (HIPAA, PCI, SOC etc.) cover the service; check the services-in-scope page.
- Use **Amazon Macie** for sensitive data in S3 sources; OpenSearch has no built-in PII detection (verify).
- Do not put sensitive data in **index names** (visible in errors/SQL).

## Scenarios (if → then, because)
- If production needs 99.99% availability → Multi-AZ with Standby, 3 masters, 3×n data nodes, 2+ replicas.
- If one AZ fails with 2-AZ domain and 3 masters in a 3-AZ Region → no downtime, because masters are spread across 3 AZs.
- If cluster is yellow on a one-node domain → expected (no node for replicas); add a node or set replicas to 0 for dev.
- If cluster is red → find unassigned primaries; restore index from automated snapshot; automated snapshots fail while red, so act within days.
- If logs older than 30 days are rarely searched → UltraWarm (read-only), then cold; ISM to automate.
- If an index needs updates again → migrate it back to hot (`_hot`).
- If someone must recover yesterday's index → restore from hourly automated snapshot (14-day window).
- If you must keep snapshots 1 year → manual snapshots to your S3 bucket (use S3 lifecycle, not Glacier).
- If registering a snapshot repo fails with PassRole error → add `iam:PassRole` for `TheSnapshotRole` and `es:ESHttpPut`.
- If FGAC is on and snapshot registration is denied → map `manage_snapshots` to the IAM role.
- If a domain must be private → create it in a VPC (cannot add later); use security groups and no IP policy.
- If an app on-premises needs access to a VPC domain → VPN/Direct Connect/proxy.
- If analysts should see only some fields/documents → FGAC document-level and field-level security (or masking).
- If sensitive field must be visible only as hash → field masking (pattern-based if you need aggregations).
- If different teams need separate dashboards → Dashboards multi-tenancy.
- If a team wants to use IAM roles for apps and Cognito for Dashboards → IAM master user + Cognito authentication.
- If you need basic auth for legacy clients → internal user database.
- If an existing public domain needs stricter security → enable FGAC (blue/green) with migration period, then lock down.
- If auditors want to know who read an index → audit logs to CloudWatch Logs (FGAC needed).
- If all data must be encrypted with your own key → customer managed KMS key at domain creation.

## Verified from AWS docs on 2026-10-02
Read: multi-AZ page, storage tiers page (summary), UltraWarm page, snapshots page, VPC page, access control page, FGAC page, security index, limits page. Not confirmed (verify): cold storage prerequisites and engine version, `cold_manager` role, exact warm node count limits, encryption-at-rest enablement on existing domains, node-to-node encryption irreversibility, managed VPC endpoint behavior, EventBridge event list, audit log content, Macie/PII statements.

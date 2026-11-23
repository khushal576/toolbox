# RDS and Aurora – 4. Security, connectivity, RDS Proxy, Data API, integrations, vector search

Short notes. Each point is a fact you can be asked about.

## A. Layers of security
- Network: VPC, private subnets, security groups, public accessibility off.
- Authentication: database passwords, IAM database authentication, Kerberos/Active Directory, Secrets Manager.
- Authorisation: database users/roles/grants (inside the DB) + IAM (for the AWS API and IAM DB auth).
- Encryption: at rest (KMS), in transit (TLS).
- Audit: CloudTrail, database logs, Database Activity Streams.
- Data protection: backups, snapshots, deletion protection, network isolation.
- Two different permission worlds: IAM controls AWS API actions (create/modify/delete DB, snapshots). The database engine controls SQL permissions (SELECT on table). IAM DB auth only maps an IAM identity to a database login.

## B. Network security
- DB instances run inside your VPC in subnets from the DB subnet group.
- **Publicly accessible = No** (recommended): no public IP. Reach it from the app in the VPC, VPN, Direct Connect, or bastion/SSM.
- **Publicly accessible = Yes**: gets a public IP; still needs a security group rule allowing the client IP. Avoid for production.
- Security group: allow only the DB port from application security groups (reference SG IDs, not CIDRs).
- NACLs can add subnet-level filtering.
- Control-plane API (create, modify) can use interface VPC endpoints (PrivateLink) for the RDS API; data traffic goes to the DB endpoint inside the VPC.
- RDS Proxy is VPC-only (never public); the database behind it can be public (verified).
- Cross-VPC/Region access: VPC peering or Transit Gateway; remember DNS resolution and security groups.
- Lambda inside the VPC to reach RDS needs subnets/security groups; Lambda outside the VPC can use Aurora **Data API** instead.
- Encryption in transit between AZs is automatic at the network layer; some Nitro instance types also encrypt between instances in the same VPC (verified list: M6i, R6i, M7g, R7g, X2idn etc.).

## C. Authentication options
- **Password (native)**: master user at creation. Others created with SQL. Store in Secrets Manager.
- **RDS managed master password** in Secrets Manager: RDS creates and rotates the master secret automatically (verify rotation period). Not supported for Aurora Global Database when adding a Region (verified: turn off first).
- **Secrets Manager rotation**: Lambda-based rotation of DB credentials (built-in templates for RDS engines). Apps fetch the secret at runtime. Rotation can be single-user or alternating-users (zero downtime).
- **IAM database authentication** (verified): MariaDB, MySQL, PostgreSQL (RDS and Aurora).
  - You call `generate-db-auth-token`; the token (a signed SigV4 string, ~1 KB+) lasts **15 minutes** and is used as the password. The connection must use SSL/TLS.
  - Policy action `rds-db:connect` on resource `arn:aws:rds-db:region:account:dbuser:resource-id/db-user`.
  - Benefits: no passwords in code, central IAM control, instance profile credentials on EC2/Lambda.
  - Limits: needs about 300–1000 MiB extra memory on the DB; limited new connections per second (about 200/s recommended; verify); some global condition keys unsupported (`aws:SourceIp`, `aws:SourceVpc`, `aws:SourceVpce`, `aws:Referer`, `aws:UserAgent`, `aws:VpcSourceIp`); PostgreSQL users granted `rds_iam` can only log in with IAM; PostgreSQL can't enable IAM and Kerberos together; not supported on RDS Outposts; token generation isn't logged by CloudTrail; can't use a custom Route 53 record to generate the token; token may be truncated by drivers (check driver limits).
  - Not for high connection churn (use RDS Proxy; the proxy can authenticate clients with IAM and use Secrets Manager to the DB).
- **Kerberos / Microsoft AD (AWS Managed AD)**: Windows authentication for SQL Server, Oracle, PostgreSQL, MySQL (verify list). Needs a directory and domain join.
- **Rotate credentials** regularly; never embed them in AMIs or code.
- Application-level roles: create separate DB users per app with least privilege (GRANT SELECT only for read apps). Do not use the master user for apps.

## D. Encryption at rest (verified)
- Uses AWS KMS and AES-256. Covers storage, automated backups, snapshots, read replicas and logs.
- **Enable at creation only.** You cannot encrypt an existing unencrypted instance, and you cannot unencrypt an encrypted one.
- To encrypt an existing DB: snapshot → copy snapshot with encryption → restore → cut over. You can't create an encrypted snapshot of an unencrypted DB; you encrypt during the copy.
- Choose AWS managed key (`aws/rds`, per Region) or a customer managed key (CMK). If you don't choose, the AWS managed key is used.
- You can't change the KMS key of an existing encrypted DB; change by copying a snapshot with a new key.
- Replica rules: encrypted replica must use the same KMS key as the source in the same Region; cross-Region replica uses a key from the destination Region. No mixed encrypted/unencrypted.
- Snapshot sharing: snapshots with the AWS managed key can't be shared; use a CMK and share the key.
- Copying encrypted snapshot cross-Region: specify a destination-Region KMS key.
- If the KMS key is disabled/deleted or access is lost: instance moves to `inaccessible-encryption-credentials-recoverable` (stopped, up to 7 days; re-enable key and start to recover) and later `inaccessible-encryption-credentials` (terminal; restore from snapshot; RDS also creates a final snapshot `rds-final:...` in many cases). Revoking a user's key access later doesn't affect a running DB (grants), but disabling the key does. (verified)
- Oracle and SQL Server also support **TDE** (Transparent Data Encryption), separately from RDS encryption. You manage separate keys; slight performance cost. (verified)
- Unsupported old classes: db.m1, db.m2, db.t2.micro (verified).
- Encrypt Aurora: enable at cluster creation (same rules).
- Use AWS Config / SCP to require `StorageEncrypted=true` for new DBs.

## E. Encryption in transit
- All RDS/Aurora engines support SSL/TLS. Download the RDS CA bundle and verify certificates.
- Enforce TLS with parameters: PostgreSQL `rds.force_ssl=1`; MySQL/MariaDB `require_secure_transport=ON`; SQL Server `rds.force_ssl=1`; Oracle SSL option in option group (verify).
- IAM database auth requires SSL.
- CA certificate rotation happens periodically; update client trust stores before expiry.
- Data between source and replicas is encrypted, even cross-Region (verified).

## F. RDS Proxy (verified)
- Fully managed connection pooler between app and database. Pools and **multiplexes** connections (several client connections share fewer DB connections).
- Benefits: survive connection storms (Lambda), reduce DB memory/CPU use for connections, faster and more graceful **failover** (keeps client connections and connects to the new primary; AWS cites reduced failover time), enforce IAM authentication to the proxy, store DB credentials in Secrets Manager.
- Engines: MySQL, MariaDB, PostgreSQL, SQL Server (not SQL Server 2022 or 2014, no AD), and Aurora MySQL/PostgreSQL. Not for RDS Custom for SQL Server. (verified)
- Proxy rules:
  - Must be in the same VPC as the database; it is **not publicly accessible**.
  - 20 proxies per account (default); up to 200 Secrets Manager secrets per proxy; one target DB per proxy (several proxies can point to one DB); up to 20 additional endpoints; the default endpoint spans two AZs. (verified)
  - For replication setups you associate the proxy with the writer only (not a read replica); read-only proxy endpoints exist for Aurora readers. (verified)
  - Fixed listener ports: 3306 (MySQL/MariaDB), 5432 (PostgreSQL). (verified)
  - **Pinning**: some session state (temp tables, `SET` variables, prepared statements in some cases, statements over 16 KB, advisory locks) pins a client to one DB connection and disables multiplexing → loses the benefit. Avoid pinning patterns. (verified)
  - Parameter group changes need an instance reboot to reflect on the proxy. (verified)
  - Don't modify the auto-created `rdsproxyadmin` user. (verified)
  - PostgreSQL `CancelRequest` isn't supported; the default `postgres` DB must exist. (verified)
  - Pricing is per vCPU-hour of the target DB (verify).
- Use RDS Proxy for: Lambda, serverless apps, apps that open and close connections often, many microservices, quicker failover.
- Don't use it for: very long-lived sessions that pin, apps needing features the proxy lacks.

## G. Aurora Data API (verified)
- HTTPS SQL endpoint for Aurora: no persistent connections, no VPC config in the caller. Auth via IAM + credentials in Secrets Manager.
- Good for Lambda, AppSync, quick scripts, query editor. Avoids connection management.
- Limits (verified from quotas page): request body 4 MB; result set 1 MB; JSON response 10 MB. Serverless v1-specific concurrency limits are older.
- Slower per call than a native connection; not for high-throughput transactional loops.
- Can be reached privately with a VPC endpoint (PrivateLink).
- Supported for Aurora provisioned and Serverless v2 clusters (verify versions/Regions).

## H. Auditing and monitoring for security
- **CloudTrail**: logs RDS API calls (create/modify/delete, snapshot actions). Not SQL statements. IAM DB token generation isn't logged.
- **Database logs** to CloudWatch Logs: error, slow query, general, audit (MariaDB/MySQL audit plugin; PostgreSQL `pgaudit`; Oracle audit; SQL Server audit/ERRORLOG).
- **Database Activity Streams (DAS)**: near-real-time, tamper-resistant stream of database activity to Kinesis Data Streams, encrypted with KMS, for Aurora and some RDS engines (Oracle, SQL Server). Used for compliance, with Guardium-like tools. Admins can't turn it off without trace (verify).
- **Performance Insights / CloudWatch Database Insights**: DB load, wait events, top SQL (retention: free short window, paid longer; verify). Access via IAM `pi:*`.
- **Enhanced Monitoring**: OS metrics every 1–60 seconds to CloudWatch Logs.
- **AWS Config**: rules for encryption, public accessibility, Multi-AZ, backup retention, deletion protection.
- **GuardDuty RDS Protection**: detects suspicious login activity on Aurora and RDS (verify).
- **Security Hub / Inspector** findings; **Trusted Advisor** checks (public snapshots, no backups, no Multi-AZ).
- Events: RDS event subscriptions to SNS/EventBridge (failover, backup, low storage).

## I. Authorisation inside the database and privacy
- Use roles/groups; grant on schemas/tables/columns; revoke PUBLIC defaults.
- PostgreSQL: `rds_superuser` is the highest role (not true superuser); row-level security (RLS) policies for per-tenant filtering; column privileges.
- MySQL: users `user@host`; roles in 8.0; `GRANT ... TO`; the master user is not SUPER-equivalent in RDS (uses RDS stored procedures).
- SQL Server: logins and users; no `sysadmin`; use `rdsadmin` procs.
- Oracle: `rdsadmin` utilities; profiles; fine-grained audit.
- Masking and PII: no managed masking in RDS. Options: views with masking functions, PostgreSQL extensions (for example anonymization extensions; verify availability), app-layer tokenization, separate encrypted columns, Macie only scans S3 (use it on exports), Glue/DataBrew when moving data downstream.
- Row-level or column security for analysts: replicate to Redshift/Lake Formation and apply controls there.
- Multi-tenancy: schema-per-tenant or RLS; use separate clusters for strong isolation.

## J. Integrations (what connects where)
- **Lambda**: call functions from Aurora (`aws_lambda` extension for PostgreSQL; `lambda_sync/async` for MySQL), or Lambda uses RDS Proxy/Data API to query. Note: invoking from the DB needs IAM roles attached to the cluster (up to 5 per instance/cluster; verified quota).
- **S3**: import/export data. Aurora MySQL `LOAD DATA FROM S3` / `SELECT INTO OUTFILE S3`; PostgreSQL `aws_s3` extension (`table_import_from_s3`, `query_export_to_s3`); SQL Server native backup/restore to S3; Oracle S3 integration (Data Pump, files). Needs an IAM role with S3 access attached to the DB.
- **DMS**: migrate to/from RDS/Aurora (full load + CDC). Source prerequisites: MySQL `binlog_format=ROW`, binary logs retained; PostgreSQL `rds.logical_replication=1`, replication slots; Oracle supplemental logging; SQL Server CDC/replication. Replication slots left behind fill WAL storage.
- **SCT / DMS Schema Conversion**: convert schema and code between engines (Oracle/SQL Server → PostgreSQL/Aurora).
- **Zero-ETL integrations (verified)**: Aurora (MySQL and PostgreSQL) → **Amazon Redshift** or **SageMaker lakehouse**, near real time, no pipeline.
  - Source and target must be in the same Region; source cluster needs at least one instance.
  - Limits: 5 integrations per source cluster; 50 per target; 100 per account; can't rename the source cluster; delete integrations before deleting the cluster; DDL can trigger table resync; unsupported data types exist.
  - Aurora MySQL: InnoDB only, binlog based, no foreign keys with CASCADE/SET NULL/SET DEFAULT actions, XA transactions put it in Syncing state. Aurora PostgreSQL: at least one data filter pattern required (for example `db.*.*`), all databases UTF-8, **primary keys required** on filtered tables (tables without PK fail), partitioned table parts replicate but not the parent, two-phase transactions unsupported, no Limitless Database source.
  - Zero-ETL for RDS MySQL/PostgreSQL also exists (verify engines).
  - Initial seeding can take 20–25+ minutes or more.
  - If the primary cluster fails over to another Region in an Aurora global database, the integration becomes inactive (delete and recreate).
- **Snapshot export to S3** for batch lake loads (file 3).
- **Glue**: JDBC connection to RDS/Aurora; crawlers can catalog tables; ETL reads (use read replicas to avoid load).
- **Athena Federated Query**: RDS/Aurora connectors (Lambda). **Redshift Federated Query**: Aurora/RDS PostgreSQL and MySQL via external schema.
- **EMR/Spark**: JDBC reads; prefer replicas.
- **QuickSight**: direct query (or SPICE) from RDS/Aurora.
- **Step Functions**: invoke SQL through Lambda or Data API.
- **EventBridge/SNS**: RDS events, e.g. failover or backup completed.
- **Kinesis**: Database Activity Streams destination.
- **Aurora machine learning (verified)**: call Amazon Bedrock, Amazon Comprehend, SageMaker AI from SQL (Aurora PostgreSQL extension `aws_ml`; Aurora MySQL has ML functions) – needs IAM role and supported versions/Regions.
- **Secrets Manager**: credentials and rotation. **Systems Manager Parameter Store**: config.
- **CloudFormation/CDK**: define DB, parameter groups, subnet groups, proxies.

## K. Vector search with pgvector (exam skills 2.1.3, 2.1.8, 2.4.6)
- What a vector is: a list of numbers (embedding) produced by a model that represents meaning of text/images. Similar meaning = nearby vectors. Search = find nearest vectors (similarity search).
- **pgvector** is a PostgreSQL extension available on **RDS for PostgreSQL** and **Aurora PostgreSQL**. Install with `CREATE EXTENSION vector;` (use 0.5.0+ for HNSW) (verified).
- Store embeddings in a `vector(n)` column. n = model dimension (for example Titan Text Embeddings V2: 256/512/1024; Titan Multimodal G1: 1536; Cohere Embed: 1024) (verified list in docs).
- Distance operators: `<->` L2 (Euclidean), `<=>` cosine distance, `<#>` negative inner product; newer versions add `<+>` (L1) and Hamming/Jaccard for bit vectors (verify exact operator symbols).
- Query pattern: `SELECT ... ORDER BY embedding <=> $1 LIMIT 10;` Combine with normal SQL filters (metadata, tenant, date) – a big advantage of keeping vectors in a relational DB.
- Other types: `halfvec` (half precision, saves memory), `sparsevec` (sparse), `bit` (binary) (verified).
- Dimension limit for **indexes**: up to **2,000** dimensions (verified for HNSW and IVFFlat); the column itself can hold more.
- **No index = exact (flat) search**: perfect recall, slow on large tables (full scan). Good for small data or when recall must be 100%.
- **HNSW** index (Hierarchical Navigable Small World): graph-based approximate nearest neighbour (ANN).
  - Create: `CREATE INDEX ON t USING hnsw (embedding vector_cosine_ops);` Choose the ops class matching your distance (`vector_l2_ops`, `vector_cosine_ops`, `vector_ip_ops`).
  - Parameters (verified defaults): `m = 16` (connections per node; higher = better recall, more memory), `ef_construction = 64` (build quality; AWS suggests 256 for Bedrock with pgvector 0.6+ parallel builds), query-time `hnsw.ef_search = 40` (higher = better recall, slower).
  - Pros: fast queries, high recall, no training step; can be built on an empty table and updated as data arrives. Cons: slower and more memory-hungry to build; bigger index.
- **IVFFlat** index (Inverted File with Flat storage): clusters vectors into `lists`; at query time searches the nearest `probes` lists.
  - Create: `CREATE INDEX ON t USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);`
  - Parameters: `lists` (number of clusters), `ivfflat.probes` (how many clusters to search; higher = better recall, slower).
  - Build **after** the table has data (it needs data to compute clusters). Cheaper and smaller than HNSW, faster to build; recall is lower unless probes is raised; recall degrades if data distribution shifts (rebuild).
  - Rules of thumb (pgvector guidance; verify): lists ≈ rows/1000 up to 1M rows, ≈ sqrt(rows) above; probes ≈ sqrt(lists).
- Choose: need best speed/recall and can afford memory → HNSW. Need fast/cheap builds, large data, memory limits → IVFFlat. Small data or perfect accuracy → no index.
- Build memory: raise `maintenance_work_mem` before creating indexes; more parallel workers speed builds (pgvector 0.6+).
- Iterative index scans help when filters remove many results (verified feature mention).
- Aurora PostgreSQL optimized reads (NVMe) helps large vector indexes that exceed memory (verify).
- **Bedrock Knowledge Bases with Aurora PostgreSQL (verified)**: Aurora can be the vector store for RAG. Needs Aurora PostgreSQL 12.16+/13.12+/14.9+/15.4+/16.1+, pgvector 0.5.0+, RDS Data API enabled, a Secrets Manager secret. Create schema `bedrock_integration`, user `bedrock_user`, table with columns `id uuid PRIMARY KEY, embedding vector(n), chunks text, metadata json, custom_metadata jsonb`, an HNSW cosine index, a GIN index on `to_tsvector('simple', chunks)`, and (if used) a GIN index on `custom_metadata`.
- RAG flow: documents in S3 → chunk → embed with a model → store vectors in the DB → at query time embed the question → nearest-neighbour search → pass results to an LLM.
- Embedding model's dimension must match the column's `vector(n)`.
- Alternatives for vectors on AWS: OpenSearch (k-NN, HNSW/IVF engines), MemoryDB (vector search), DocumentDB (vector search), Neptune Analytics, DynamoDB vector indexes (new), S3 Vectors. Pick Aurora/RDS pgvector when you want SQL + transactions + joins with vectors in one database; OpenSearch for large-scale hybrid text+vector search; MemoryDB for ultra-low latency.

## L. Scenarios (if → then, because)
- If a database must not be reachable from the internet → publicly accessible = No, private subnets, SG from app SG only.
- If apps shouldn't hold DB passwords → IAM database authentication (MySQL/MariaDB/PostgreSQL) or Secrets Manager with rotation.
- If thousands of short-lived Lambda connections overload the DB → RDS Proxy (or Aurora Data API).
- If Lambda shouldn't be in a VPC → Aurora Data API.
- If an unencrypted production DB must be encrypted → snapshot, encrypted copy, restore, switch endpoint.
- If a DB must be encrypted with keys the customer controls → CMK; remember replicas and snapshots need the same key rules.
- If auditors need every SQL statement streamed to a SIEM → Database Activity Streams (Aurora, Oracle, SQL Server) to Kinesis.
- If you need to know who deleted a DB → CloudTrail.
- If you must enforce TLS → set the engine parameter (`rds.force_ssl`/`require_secure_transport`).
- If analysts need near-real-time analytics on Aurora data → zero-ETL to Redshift (check PK/filters).
- If a lake needs a one-off full copy cheaply → snapshot export to S3 (Parquet) + Athena.
- If you must migrate from Oracle to Aurora PostgreSQL with little downtime → SCT/DMS Schema Conversion + DMS full load + CDC.
- If RAG needs a vector store with SQL filters and transactions → Aurora/RDS PostgreSQL with pgvector (HNSW index, cosine).
- If vector queries are slow on millions of rows → create an HNSW index (or IVFFlat after loading data), raise `ef_search`/`probes` for recall, give the index enough memory.
- If an index build fails or is very slow → raise `maintenance_work_mem`, use parallel workers, build IVFFlat after loading data.
- If embeddings from the model have 1024 dimensions → column must be `vector(1024)`.
- If recall must be exactly 100% on a small table → no ANN index (exact search).
- If a proxy doesn't reduce DB connections → sessions are being pinned; remove session-state statements and large statements.
- If you need credentials rotated with no downtime → Secrets Manager alternating-users rotation.
- If a KMS key was disabled and the DB went inaccessible → re-enable the key and start the instance within 7 days, or restore from the final snapshot.

## Verified from AWS docs on 2026-10-02
Encryption, IAM database authentication, RDS Proxy, Data API (index), zero-ETL, pgvector on RDS, Aurora PostgreSQL as a Bedrock Knowledge Base, Aurora ML intro pages and quotas were read. Not confirmed (verify): exact pgvector operator symbols beyond L2/cosine/inner product, IVFFlat tuning rules, DAS engine list, GuardDuty RDS Protection scope, new-connection-rate limits for IAM auth, anonymization extension availability.

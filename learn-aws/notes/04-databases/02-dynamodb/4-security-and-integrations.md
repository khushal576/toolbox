# DynamoDB – 4. Security, private access, auditing, integrations, data engineering patterns

Short notes. Each point is a fact you can be asked about.

## A. How access works
- Every request is signed (SigV4) by an IAM identity. There are no database users or passwords.
- Authorisation is IAM only: identity-based policies, resource-based policies, and service control policies (SCPs).
- Applications should use IAM roles (Lambda execution role, EC2 instance profile, ECS task role, Glue job role), never long-lived access keys.
- Mobile/web users: Amazon Cognito identity pools give temporary credentials; use fine-grained conditions to limit each user to their own items.
- Every API call goes over HTTPS (TLS). Encryption in transit is always on for the DynamoDB endpoints.
- Table, index and stream ARNs: `arn:aws:dynamodb:region:account:table/Name`, `.../index/IndexName`, `.../stream/label`.

## B. IAM policies (identity-based)
- Actions are API-like: `dynamodb:GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Query`, `Scan`, `BatchGetItem`, `BatchWriteItem`, `DescribeTable`, `CreateTable`, `UpdateTable`, `ExportTableToPointInTime`, etc.
- Resources: table ARN plus `/index/*` for indexes (queries on a GSI need the index ARN in the policy).
- Least privilege: allow only the actions and tables the job needs. Deny `Scan` for app roles if you want to force key-based access.
- Fine-grained access control with condition keys:
  - `dynamodb:LeadingKeys`: restrict access to items whose partition key equals a value (for example the caller's Cognito ID). Gives per-user row-level access.
  - `dynamodb:Attributes`: restrict which attributes can be read or written (column-level).
  - `dynamodb:Select`, `dynamodb:ReturnValues`, `dynamodb:ReturnConsumedCapacity`: control what the caller may request.
  - `dynamodb:EnclosingOperation`: limit what a PartiQL statement can do (verify).
- Attribute-based access control (ABAC): tag tables and principals, then allow based on tag match (`aws:ResourceTag/...`, `aws:PrincipalTag/...`). Scales better than listing tables.
- AWS managed policies exist (for example read-only, full access). They are broad; write custom policies for production.
- Use permissions boundaries and SCPs to cap what teams can do (for example block `DeleteTable`, deny access outside approved Regions).
- Roles need trust policies for services (Lambda, Glue, EMR, etc.) and `iam:PassRole` for whoever creates the job with that role.
- Cross-account without resource policy: assume a role in the table's account.

## C. Resource-based policies (verified)
- Attach a JSON policy directly to a table, index or stream (max 20 KB).
- Main use: simple cross-account access (grant principals in another account access without role assumption).
- Both sides still matter: the caller's account may also need an identity policy unless the resource policy allows directly (check evaluation rules).
- Block Public Access: DynamoDB blocks policies that give public access (on by default in the workflow).
- IAM Access Analyzer reports external access found in resource policies.
- Cross-account **Scan on a secondary index** with a resource-based policy is not supported (verified).
- Policy is evaluated with identity policies; an explicit Deny anywhere wins.

## D. Encryption
- Encryption at rest is **always on** for tables, indexes, streams, backups, global table replicas. You cannot turn it off.
- Key options (per table): AWS owned key (default, no cost, not visible in your account), AWS managed key (`aws/dynamodb`, visible in KMS/CloudTrail), customer managed key (CMK, full control: key policy, rotation, disable, audit).
- You can switch between key types later (verify limits per switch).
- If a CMK is disabled, scheduled for deletion, or access is revoked, the table becomes inaccessible. Protect the key.
- For global tables each replica can use its own key (same-account model; verify details).
- Backups, exports and streams are encrypted; exports to S3 are encrypted (S3 settings/KMS key you choose).
- DAX supports encryption at rest and in transit separately (set when creating the cluster).
- Client-side encryption (AWS Database Encryption SDK) for attribute-level encryption when even AWS must not see plaintext, or to encrypt only sensitive attributes. Encrypted attributes can't be queried/sorted in the usual way.
- In transit: TLS 1.2+. Interface endpoints do not support TLS 1.1 (verified).
- Cross-account encryption: if the table uses a CMK, the other account's principals need KMS permissions too.
- CloudTrail logs KMS key usage for audit.

## E. Private network access (verified)
- DynamoDB is a public regional endpoint, but traffic from your VPC can stay on the AWS network using VPC endpoints.
- **Gateway endpoint**: a route-table target; free; uses DynamoDB public IPs; works for resources inside the VPC; **no on-premises access; no cross-Region access**.
- **Interface endpoint (AWS PrivateLink)**: private IPs in your subnets; **billed**; reachable from on-premises (Direct Connect/VPN) and from other VPCs/Regions via peering or Transit Gateway.
- You can use both in the same VPC: in-VPC apps use the free gateway endpoint, on-premises uses the interface endpoint.
- Interface endpoint limits: no TLS 1.1; no private/hybrid DNS overrides – use the endpoint-specific DNS name (`vpce-...dynamodb.region.vpce.amazonaws.com`) in the client config; do not override `dynamodb.region.amazonaws.com` with private hosted zones (verified).
- Up to 50,000 requests per second per PrivateLink endpoint (verified).
- Endpoint policy: limit which tables and actions are allowed through the endpoint (for example allow only `GetItem` and `PutItem` on one table).
- Pair with IAM condition `aws:SourceVpce` (or `aws:SourceVpc`) to require private access.
- DAX is VPC-only and has its own PrivateLink support.
- Lambda in a VPC needs a gateway endpoint or NAT to reach DynamoDB.
- Console private access needs both `dynamodb` and `dynamodb-streams` endpoints.

## F. Auditing and monitoring for security
- CloudTrail logs control-plane calls (CreateTable, UpdateTable, DeleteTable, backup, PITR changes) by default as management events.
- Data-plane calls (GetItem, PutItem, Query, etc.) can be recorded as **data events** if you enable them (paid; high volume).
- Streams / Kinesis change capture gives an item-level change audit trail (what changed, before/after images).
- Contributor Insights shows the most accessed and most throttled keys (find hot keys or abusers).
- AWS Config: rules for encryption, PITR enabled, deletion protection, backup plans.
- AWS Backup reports show backup compliance.
- Access Analyzer finds external access in resource policies.
- CloudWatch alarms for errors and throttles (`UserErrors`, `SystemErrors`, `ThrottledRequests`).
- Use tags for cost and ownership; enforce tagging with SCP/Config.

## G. Privacy and masking
- DynamoDB has no built-in masking. Options: store tokens instead of raw PII, encrypt sensitive attributes client-side, split PII into a separate table with tighter IAM, restrict attributes with `dynamodb:Attributes`.
- Find PII in exports with Macie (on the S3 export) or Glue sensitive-data detection.
- Data sovereignty: choose the Region; avoid replicas in other Regions; SCP deny of other Regions; check backups and exports stay in-region.
- Retention/deletion: see file 3 section I.

## H. Integrations (what connects to what)
- **Lambda**: event source mapping from Streams; also called directly by API Gateway/Step Functions. Reuse SDK clients across invocations.
- **API Gateway**: direct service integration to DynamoDB (no Lambda) for simple CRUD; or Lambda for logic.
- **Step Functions**: optimized integrations for GetItem, PutItem, UpdateItem, DeleteItem; callback and idempotency patterns.
- **EventBridge Pipes**: Streams as a source with filtering, enrichment and targets (SQS, SNS, Lambda, Kinesis, etc.).
- **Kinesis Data Streams / Firehose / Flink**: change capture for real-time analytics and loading to S3, Redshift, OpenSearch.
- **S3**: Export (PITR) and Import; store large payloads and keep pointers.
- **Athena**: query exports in S3; or use the Athena DynamoDB connector (federated query via Lambda) for light ad hoc reads (reads live data using table capacity).
- **Glue**: ETL reads from DynamoDB (including reading via S3 export to avoid using read capacity) and writes back; Glue Data Catalog can describe exported data.
- **Redshift**: zero-ETL integration (continuous replication into Redshift, needs PITR); also `COPY` from a DynamoDB table (uses table read capacity; `READRATIO` caps the share used).
- **OpenSearch**: zero-ETL integration for search over DynamoDB data (needs PITR).
- **SageMaker lakehouse / S3 Tables**: zero-ETL toward lakehouse (verify details).
- **EMR / Hive / Spark**: DynamoDB connector (uses read capacity; set read percentage).
- **DMS**: DynamoDB as a target (from relational/NoSQL sources) with object mapping; also as a source (verify).
- **DAX**: caching layer.
- **AWS Backup**: central backups.
- **CloudFormation / CDK / SAM**: tables, indexes, scaling, streams, global tables; `AWS::Serverless::SimpleTable` for simple SAM tables.
- **AppSync (GraphQL)**: resolvers to DynamoDB (listed out of scope in the exam guide).
- **NoSQL Workbench**: modeling and PartiQL tool. **DynamoDB local**: downloadable emulator for dev/test.
- **Cognito**: identity pools + fine-grained IAM for direct client access (use carefully).

## I. Data engineering patterns
- Operational DB → data lake: enable PITR, schedule incremental exports to S3, crawl with Glue, query with Athena. No impact on production reads.
- Near-real-time analytics: Kinesis Data Streams for DynamoDB → Firehose → S3 (Parquet) or Flink aggregations.
- Direct warehouse feed: Redshift zero-ETL for DynamoDB (near real time, no pipelines).
- Search: OpenSearch zero-ETL for text search and filters.
- CDC to downstream services: DynamoDB Streams → Lambda/EventBridge Pipes → SNS/SQS/other stores.
- Materialized aggregates: Streams + Lambda update summary items (counters, leaderboards, rollups).
- Cache invalidation: Streams event → delete cache key.
- Dedup / idempotency store: DynamoDB with conditional `PutItem` and TTL for the idempotency window.
- Pipeline state store: DynamoDB table for job metadata, watermarks, checkpoints (KCL uses DynamoDB for leases).
- Migration into DynamoDB: DMS (with mapping rules), or export source to S3 then Import from S3 to a new table.
- Backfill/transform: Glue/EMR job reading an S3 export, writing to a new table via BatchWrite or Import.
- Two-way sync across Regions: global tables (not custom Lambda).
- Hybrid: store metadata in DynamoDB and big blobs in S3; use S3 events to update DynamoDB.

## J. Scenarios (if → then, because)
- If a mobile user must only read their own items → Cognito identity pool + IAM policy with `dynamodb:LeadingKeys` = user ID.
- If an app role must not run Scans → policy denying `dynamodb:Scan` (and PartiQL scans).
- If another AWS account must read a table → resource-based policy on the table (or cross-account role).
- If a table's data must be encrypted with keys you control and can revoke → customer managed KMS key.
- If you need to see every read of sensitive items → enable CloudTrail data events for the table (cost).
- If an EC2 app in a private subnet must reach DynamoDB with no internet and no extra cost → gateway VPC endpoint.
- If on-premises servers must call DynamoDB privately → interface VPC endpoint over Direct Connect/VPN.
- If only your VPC may use the table → endpoint policy + IAM `aws:SourceVpce` condition.
- If analytics runs slow your production table → stop scanning it; use Export to S3 (or zero-ETL).
- If you want near-real-time data in Redshift with no pipeline → zero-ETL integration (needs PITR).
- If search on DynamoDB attributes is required (text, fuzzy) → OpenSearch zero-ETL.
- If you want to react to item changes → Streams + Lambda (or EventBridge Pipes).
- If several consumers need the change feed and replay → Kinesis Data Streams for DynamoDB.
- If PII must not be visible to analysts → keep PII out of the exported datasets, mask in ETL, restrict attributes via IAM, and use Lake Formation on the lake copy.
- If you must stop deletion of production tables → deletion protection plus an SCP denying `DeleteTable`.
- If you must detect tables without PITR → AWS Config rule.
- If a Lambda writes to DynamoDB and retries cause duplicates → conditional writes with an idempotency key (and TTL).
- If you want a REST API on a table with no code → API Gateway direct integration.
- If you store attribute-level secrets that even admins shouldn't read → client-side encryption (Database Encryption SDK).

## Verified from AWS docs on 2026-10-02
Security overview, resource-based policies, PrivateLink/gateway endpoint comparison, DAX encryption mention, zero-ETL and Kinesis integration pages were read. Not confirmed (verify): exact condition-key names for PartiQL, key-type switching rules, global table per-replica key behavior, DMS source/target detail, Redshift COPY READRATIO, Glue export-read option.

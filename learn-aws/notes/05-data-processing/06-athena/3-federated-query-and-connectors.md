# Athena – 3. Federated query and connectors

Short notes. Each point is a fact you can be asked about.

## A. What federated query is
- **Federated query** = run Athena SQL against data **outside S3** (relational DBs, NoSQL, logs, metrics, other clouds) without copying it first. You can also **join** it with S3 tables in one query.
- Athena calls a **data source connector**. The connector decides what to read, splits the work for parallelism, and **pushes down filters** to the source where it can.
- Uses: one-off or low-frequency joins of lake data with a live lookup table; quick look at an operational DB; building a pipeline that **extracts from many sources and writes to S3** (CTAS / INSERT INTO over a federated read).
- Not for: heavy, repeated, large cross-source joins; high-concurrency BI on an OLTP database; writes to the source.
- Federated sources are **read-only**. `INSERT INTO` to a federated catalog fails: "This operation is currently not supported for external catalogs".
- **Cross-Region** federated queries are not supported.

## B. Two kinds of connectors (current model)
- **AWS Glue Data Catalog federated connectors** – use an **AWS Glue connection** to store connection info. Can use **Lake Formation** for fine-grained access control.
  - **With Lambda**: connector runs as a Lambda function in your account. You can optionally *register* it as a Glue catalog.
  - **Without Lambda**: newly created connectors from **21 April 2026** (for certain sources) are registered as Glue catalogs automatically and run **without a Lambda in your account** (Athena provisions what it needs; for VPC sources Athena creates an **ENI** in your VPC).
- **Athena data catalog federated connectors** – the older, Athena-only type. Always need a **Lambda** in your account. **Cannot** be registered as Glue/Lake Formation catalogs. All **custom** connectors (built with the Athena Query Federation SDK) are this type.
- Table of what exists (summary of the docs matrix):
  - No-Lambda Glue connector available for: **DocumentDB, DynamoDB, OpenSearch, Redshift, BigQuery, MySQL, Oracle, PostgreSQL, SAP HANA, Snowflake, SQL Server, Teradata** (verify the list changes often).
  - Glue-with-Lambda or Athena-type only (Lambda needed): CloudWatch Logs, CloudWatch Metrics, Timestream, CMDB, Db2, Db2 iSeries, Azure Data Lake Storage, Azure Synapse, Cloudera Hive/Impala, Google Cloud Storage, HBase, Vertica, TPC-DS.
  - **Athena-type only** (cannot be Glue catalogs): **MSK, Kafka, Confluent, Neptune, Redis OSS, Hortonworks, custom**.
- Old generic **AthenaJdbcConnector is deprecated**. Use the database-specific connector (MySQL, PostgreSQL, Redshift…).
- Third-party connectors built with the SDK are **not supported by AWS**; talk to the provider.
- "We do not support data sources that are end-of-life" – connectors follow the vendor's support.

## C. How a Lambda-based connector works
- Connector = **Lambda function** built on the **Athena Query Federation SDK**. Deployed from the **AWS Serverless Application Repository (SAR)**, the console, or CloudFormation/CDK. Container images pulled from ECR are used for some (you can pull images into your own account's ECR).
- Query steps:
  1. Athena asks the Lambda for **metadata**: list databases/tables, table schema (`GetTableLayout`, partitions).
  2. Lambda returns **splits** (chunks of work).
  3. Athena sends splits to the Lambda, many in **parallel** → many concurrent Lambda invocations.
  4. Lambda reads the source and returns Apache **Arrow** data.
  5. If a response is larger than Lambda's **6 MB** response limit, Lambda **spills** it to the **spill bucket** in S3 (encrypted); Athena reads it from there.
- Connector reads metadata from: the source itself, or **Glue** (some connectors let you define tables in a Glue database, e.g., DynamoDB, DocumentDB, Redis, HBase) (verify per connector).
- Lambda settings that matter: **memory** (also sets CPU), **timeout** (max **15 min**), reserved/available **concurrency**, **VPC** config.
- **Lambda concurrency** is shared with your other functions in the account. A federated query can use up the account's concurrency or hit `TooManyRequestsException` (Rate exceeded). Reserve concurrency or request an increase.

## D. Spill bucket
- Parameter `SpillBucket` (and optional prefix) is **required** for Lambda connectors.
- Holds data bigger than the Lambda response size. Athena **does not delete** spilled data; it is not reused. Add an **S3 lifecycle rule** to expire it.
- Spilled data is encrypted by the SDK by default (or your KMS key via connector settings). If you use a KMS key, the principals reading it need `kms:Decrypt`.
- The Athena user must be able to **read the spill location** (the query runs as them).
- In cross-account sharing the other account needs `s3:GetObject`/`ListBucket` on the spill bucket.

## E. Setting up a data source (console flow)
- Athena console → **Data sources and catalogs** → **Create data source**. Choices:
  - A **prebuilt connector** (MySQL, DocumentDB, PostgreSQL, …).
  - **S3 – AWS Glue Data Catalog** (normal, non-federated).
  - **S3 – Apache Hive metastore** (external Hive via Lambda connector).
  - **Custom or shared connector** (your own Lambda ARN or one shared from another account).
- **Data source name**: up to **127** characters, unique in the account, **cannot be changed** later. Allowed: letters, digits, `_`, `@`, `-`. Reserved: `awsdatacatalog`, `hive`, `jmx`, `system`.
- Connector app parameters (Lambda type): **`AthenaCatalogName`** (lowercase function name), **`SpillBucket`**, plus source-specific ones (connection string, Secrets Manager secret name, VPC subnets, security groups).
- You must tick "I acknowledge that this app creates custom IAM roles and resource policies".
- What Athena creates for you:
  - Glue connector without Lambda: **Glue connection + Glue catalog** (+ ENI if VPC).
  - Glue connector with Lambda: Glue connection + **Lambda execution role + Lambda function**.
  - Athena-type connector: Lambda execution role + Lambda function.
- You can also register a data source with the **`CreateDataCatalog`** API (type `LAMBDA`).
- Glue connection VPC settings (`subnet_ids`, `security_group_ids`) **cannot be updated**; create a new connection.
- Update a connector by redeploying/updating the SAR app or Lambda image; the docs describe an update flow.

## F. Querying
- Syntax: `SELECT * FROM "catalog_name"."database"."table"`. Use **double quotes** for names with special characters (e.g., CloudWatch log group `/var/app/name`).
- Terminology differs by source (schema = database; DynamoDB table = Athena table; CloudWatch log group = database; log stream = table). Tables are *qualified* by catalog.name.
- **Joining sources**: `FROM my_dynamodb.default.orders o JOIN my_mysql.products.catalog p ON ... JOIN my_documentdb.default.customers c ON ...`. Mix with S3 using `awsdatacatalog.<db>.<table>`.
- **Federated views**: `CREATE VIEW` over federated and S3 tables.
  - Needs engine version 3.
  - View definition is stored in **Glue**, not in the source.
  - Must use fully qualified names (`"ddbcatalog"."default"."customers"`).
  - Users need permission on the sources too, plus `athena:GetDataCatalog`.
  - **Not supported** once the source is registered as a Glue Data Catalog (Lake Formation).
- **Passthrough queries**: send native SQL straight to the source (uses the source's own engine, e.g., to push joins or aggregates down). Not supported after you register the source as a Glue Data Catalog. (Check exact `TABLE(catalog.system.query(...))` syntax in the connector page (verify).)
- **Delimited (quoted) identifiers** are not supported for federated queries (docs limitation).
- **JDBC driver** with federated queries or Hive metastore needs `MetadataRetrievalMethod=ProxyAPI` in the connection string.
- **Case handling**: connectors have a **case resolver mode** (`NONE`, `LOWER`, `UPPER`, `CASE_INSENSITIVE_SEARCH`, and legacy `ANNOTATION` for Snowflake and SAP HANA).
  - All JDBC connectors support NONE/LOWER/UPPER.
  - `CASE_INSENSITIVE_SEARCH`: schema names must be unique and table names unique per schema (cannot have both "Apple" and "APPLE").
  - Glue only stores lowercase, so registered Glue/Lake Formation connectors work only with `NONE` or `LOWER`.
- **Pagination of table listing** exists in DocumentDB, DynamoDB, MySQL, OpenSearch, Oracle, PostgreSQL, Redshift, SQL Server connectors. Others may time out with many tables.
  - Keep **under ~1,000 tables per catalog** for fast `ListTableMetadata`.
  - If `ListTableMetadata` times out, query `information_schema` via `StartQueryExecution` instead.

## G. Pushdown and performance
- **Predicate pushdown**: filters (`WHERE`) are sent to the source. **Projection pushdown**: only needed columns are requested. When a connector does **not** support predicate pushdown, a filtered query is slow: small data about **2 minutes on average**, large data may time out.
- Joins between two federated tables happen **in Athena**, after pulling both sides across Lambda. Large cross-source joins are slow and costly.
- **Parallelism** comes from splits (partitions, shards, key ranges). Limited by Lambda concurrency and by how many connections the source accepts.
- Source-side effects: a federated query is a normal client on your database. Scans can hurt production. Point it at a **read replica** or reader endpoint.
- Make it faster:
  - Filter on indexed/partition columns so pushdown helps.
  - Select few columns.
  - Raise Lambda memory/timeout.
  - For repeated use, **copy to S3** with CTAS/`INSERT INTO` (or DMS/Glue) and query Parquet instead.
  - Use federated queries mainly for **small lookups** and for **extracting** data into S3.
- **Query result reuse** does not work with federated catalogs (file 1).

## H. Networking
- Connector Lambda (or the managed ENI) must **reach the source**. For sources in a VPC (RDS, Redshift, DocumentDB, on-prem via VPN/Direct Connect):
  - Give the Lambda **subnets** and **security groups** of that VPC.
  - Source security group must allow the connector's security group on the DB port.
  - Lambda in a VPC loses internet access: it needs a **NAT gateway** or **VPC endpoints** to reach **Athena, S3, Secrets Manager, Glue, CloudWatch Logs** etc.
- **Secrets Manager** is used for DB credentials (connection string refers to `${secret_name}`). Using Secrets Manager in a VPC connector requires a **Secrets Manager VPC private endpoint** (docs requirement).
- Doing nothing about networking is the #1 reason a VPC federated query times out.
- Connectors for AWS services in the public network (DynamoDB, CloudWatch) usually run outside a VPC and need no VPC setup.

## I. Security and permissions
- Who needs what (Lambda-based connectors):
  - **Query user/role**: Athena permissions (`athena:StartQueryExecution`, `GetQueryExecution`, `GetQueryResults`, `GetDataCatalog`), S3 access to results and spill bucket, and `lambda:InvokeFunction` on the connector. Using the managed policy `AmazonAthenaFullAccess` covers most of the Athena side.
  - **Admin creating the source**: `athena:CreateDataCatalog`, `lambda:*` as needed to create/deploy, `iam:PassRole`, SAR/CloudFormation rights, Glue connection permissions (`glue:CreateConnection`, `GetConnection`, `UpdateConnection`, `DeleteConnection`).
  - **Lambda execution role**: S3 access to the spill bucket, read access to the data source (e.g., DynamoDB read, Secrets Manager `GetSecretValue`), EC2 network interface permissions if in a VPC, CloudWatch Logs.
- **No-Lambda Glue connector**: the **Glue Data Catalog IAM role** you pass needs `glue:ManagedConnector`, `s3:PutObject` (spill), Secrets Manager `Describe/Get/PutSecretValue`, EC2 ENI actions (if VPC), and source-specific actions (e.g., DynamoDB `Query`, `Scan`, `GetItem`, `BatchGetItem`, `DescribeTable`, `ListTables`).
- **Lake Formation** on federated data:
  - Works for **Glue-registered** federated catalogs: grant database/table/column permissions in Lake Formation.
  - Console path: data source details → **Get started with AWS Lake Formation** → pick catalog name and a Lake Formation IAM role → Athena data source is **deleted and replaced** by a Glue catalog (queries must use the new catalog name). Athena no longer manages the Lambda.
  - Registered connector list includes CMDB, Timestream, ADLS, Synapse, Db2, Db2 iSeries, GCS, HBase, TPC-DS, Cloudera Hive, CloudWatch, CloudWatch Metrics, Vertica, BigQuery, DocumentDB, DynamoDB, MySQL, Oracle, PostgreSQL, Redshift, SAP HANA, Snowflake, SQL Server, Teradata, OpenSearch (verify).
  - The Lake Formation role must read the spill bucket, invoke the Lambda and access the Glue connection.
  - If you write your own IAM policy, make sure end users **cannot** call the Lambda directly, read the spill bucket, or use the Glue connection/LF role (that would bypass Lake Formation).
  - Without registration, access control = IAM only (invoke permission on the Lambda). The connector can sometimes also filter by the calling user.
- **Cross-account (Lambda-type only)**: Account A owns the connector, Account B queries.
  - In A: Lambda **resource-based policy** allowing B's principal to `lambda:InvokeFunction`; spill bucket policy allowing B (`s3:GetObject`, `s3:ListBucket`); if a custom KMS key encrypts spill, key policy allows B `kms:Decrypt`.
  - In B: create role **`AthenaCrossAccountCreate-<accountA-id>`** (trusts A) with `athena:CreateDataCatalog`.
  - A then clicks **Share** on the data source in the console (name + account ID). Config changes in A flow to B automatically. A keeps ownership.
  - B can also add a shared connector by entering A's **Lambda ARN** as a "Custom or shared connector".
  - Not available for Glue-connection-based sources or Hive metastore. For registered Glue catalogs use **Glue/Lake Formation cross-account sharing** instead.
  - Error "Account A does not have permission to assume role in Account B" → role name or policy wrong.
- **Encryption**: spill data encrypted; connection to the source should use TLS (connector-specific). Secrets in **Secrets Manager**, never in the Lambda environment as plain text.
- **Audit**: CloudTrail logs Athena calls; Lambda logs go to CloudWatch Logs (look there first when a federated query fails).

## J. Cost
- Athena bills federated queries **per TB scanned** (data scanned across sources), **rounded up per query to the nearest MB with a 10 MB minimum**, unless you use provisioned capacity (then the minimum rule does not apply).
- You **also pay** for **Lambda** (requests + GB-seconds) for each invocation. Lambda free tier applies.
- S3 requests/storage for the **spill bucket**; Secrets Manager; NAT gateway / data transfer if the connector sits in a VPC; the source database load.
- Cut cost: filter at the source, copy hot data to S3 Parquet, shorten Lambda duration, lifecycle on the spill bucket.

## K. Troubleshooting (symptom → cause → fix)
- Query hangs then times out on a VPC source → Lambda has no route to Athena/S3/Secrets Manager or the DB security group blocks it → add NAT/VPC endpoints, fix security groups.
- `Rate exceeded` / `TooManyRequestsException` → Lambda throttling (account or reserved concurrency) → raise concurrency, lower query parallelism, reduce splits.
- `ListTableMetadata` timeout in the console → too many tables or slow source → keep <1,000 tables, raise Lambda memory/timeout, use `information_schema` through `StartQueryExecution`.
- `Access Denied` on spill → user lacks read on the spill bucket or KMS key → grant S3 and `kms:Decrypt`.
- Table not found because of case → set case resolver mode (`LOWER` or `CASE_INSENSITIVE_SEARCH`) or use correct case.
- Slow filtered queries → connector without predicate pushdown → use a connector/column that supports it, or copy data to S3.
- Cannot create view after Lake Formation registration → federated views are not supported on Glue-registered sources.
- Passthrough query stopped working after registration → not supported with Glue Data Catalog registration.
- "This operation is currently not supported for external catalogs" → you tried `INSERT`/write to a federated source.
- Missing quoted identifier → delimited identifiers aren't supported for federated queries.
- Stale connector bugs → update the SAR app / image to the latest version; read the Lambda logs.

## L. Federated query vs alternatives
- **Athena federated query**: query in place, no ETL, good for small/occasional. Costs: Lambda + scan; speed depends on the source.
- **Redshift federated queries**: Redshift querying RDS/Aurora PostgreSQL/MySQL from the warehouse (needs a Redshift cluster).
- **Redshift zero-ETL** from Aurora/RDS/DynamoDB: continuous replication into Redshift (or S3 Tables / SageMaker Lakehouse) for heavy analytics.
- **DMS** or **Glue**: full load + CDC into S3, then Athena on Parquet. Best for repeated, large analytic use.
- **Aurora/RDS export to S3** (snapshot export in Parquet): cheap one-time lake copy; does not hit the live DB.
- Rule: *occasional + small + fresh* → federated; *frequent + big* → move the data to S3 (or the warehouse).

## M. Scenarios: If X → Y, because Z
- If an analyst needs a one-time join of S3 clickstream with an RDS customer table → Athena federated query (MySQL/PostgreSQL connector), because there is no ETL to build.
- If the same join runs every hour on big tables → land the RDS data in S3 (DMS/Glue/export) and query Parquet, because Lambda connectors do not scale like columnar scans.
- If the source is a private RDS in a VPC → connector with VPC subnets + security groups, NAT/endpoints for Athena/S3/Secrets, because the Lambda must reach both the DB and AWS APIs.
- If DB credentials must not be in config → Secrets Manager + VPC endpoint for Secrets Manager, because the connector fetches them at runtime.
- If a query returns huge data and the Lambda response limit is hit → data spills to the S3 spill bucket automatically; add a lifecycle rule, because Athena does not delete it.
- If column-level access control on a federated database is required → register the connector as a Glue Data Catalog and use Lake Formation, because IAM on the Lambda is all-or-nothing.
- If another AWS account must use your connector → share it (Lambda resource policy + spill bucket policy + role `AthenaCrossAccountCreate-<id>`), because Lambda-type connectors support console sharing.
- If you need to hide a complex 3-source join from analysts → federated view, because the view is stored in Glue and analysts query one name (only if not registered in Lake Formation).
- If a federated query overloads production DB → point the connector to a read replica and filter early, because the connector is a normal DB client.
- If you need to read Kafka/MSK topics from SQL → MSK/Kafka connector (Athena-type, Lambda), because those have no Glue-catalog version.
- If you want to inspect CloudWatch Logs with SQL → CloudWatch connector, but for heavy log analysis export to S3 or use Logs Insights, because the connector is slow on large ranges.

## Verified from AWS docs on 2026-10-25
Read from current Athena User Guide pages: Use Athena Federated Query (connector types and support matrix), Create a data source connection (+permissions, console steps), Register your connection as a Glue Data Catalog, Enable cross-account federated queries, Available data source connectors, Run federated queries, troubleshooting (federated), pricing page.
Not confirmed (verify): exact passthrough query syntax; which connectors support Lambda-less mode beyond the table (list changes after 21 April 2026); Lambda concurrency/memory defaults per connector; whether each connector paginates `ListTableMetadata`; Glue-based table definitions per connector (DynamoDB, DocumentDB, Redis, HBase); exact Lambda 15-minute / 6 MB values (standard Lambda limits, cited here from Lambda docs and the cross-account page for 6 MB).

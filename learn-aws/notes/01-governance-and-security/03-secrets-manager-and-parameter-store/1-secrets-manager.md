# AWS Secrets Manager (with Parameter Store comparison) – 1. Secrets Manager

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS Secrets Manager** stores, retrieves, **rotates** and audits **secrets**: database credentials, API keys, OAuth tokens, certificates-as-text, any key/value or string up to **64 KB**.
- It replaces **hard-coded credentials** in code, config files and environment variables. Apps call `GetSecretValue` at runtime.
- Secrets are **encrypted with KMS** (AWS managed key `aws/secretsmanager` by default, or your **customer managed key**), and every access is logged in **CloudTrail**.
- Regional service; can **replicate** secrets to other Regions.
- Pick it when:
  - You need **automatic rotation** (databases, third-party keys).
  - You need **fine-grained access control + audit** per secret, **cross-account sharing**, or **multi-Region replication**.
  - You want first-class integrations: **RDS, Aurora, Redshift, DocumentDB**, Glue connections, DMS endpoints, Lambda, ECS, EKS (CSI driver), MWAA backend, EMR, QuickSight data sources.
- Avoid it when: you only need non-sensitive config or cheap, high-volume values (use **Parameter Store**), or you need key material management (use **KMS**).
- DEA-C01: **4.1.3 create and rotate credentials** (Secrets Manager), **4.2.2 store credentials**, **4.3.2** KMS encryption, integrations in 1.x ingestion jobs.

## B. Core concepts
- **Secret**: the protected value plus metadata (name, description, tags, KMS key, rotation config, resource policy, replica Regions).
- **Secret value**: string or binary, **max 65,536 bytes**. Often JSON, e.g. `{"username":"admin","password":"…","host":"…","port":3306,"dbname":"…","engine":"mysql"}`.
- **Version**: each `PutSecretValue`/`UpdateSecret`/rotation creates a version identified by a **VersionId** (UUID).
- **Staging labels** mark versions: **`AWSCURRENT`** (what `GetSecretValue` returns by default), **`AWSPENDING`** (during rotation), **`AWSPREVIOUS`** (last current). You can add **custom labels**. A label sits on **one version** at a time per secret.
- **Quotas**: **100 versions** per secret (unlabeled versions older than 24 h are pruned beyond 100), **20 staging labels** across a secret, **500,000 secrets** per Region, name up to 512 chars.
- **Name** rules: letters, digits, `/_+=.@-`; use paths (`prod/app/db`) to organize and write path-based IAM policies.
- **ARN** ends with a **random 6-character suffix** (`…:secret:prod/db-AbCdEf`) so deleted and recreated secrets have different ARNs. Policies can wildcard the suffix (`prod/db-*`).
- **Secret types**: custom, **managed secrets** (created by services such as RDS/Aurora, Redshift, DocumentDB with `ManageMasterUserPassword`; named `rds!…`), **external secrets** from partners (managed external rotation).
- **Do not update a secret more than once every 10 minutes** sustained, or you create versions faster than cleanup.

## C. Retrieving secrets
- API: `GetSecretValue` (by name/ARN; optional `VersionId` or `VersionStage`), `BatchGetSecretValue` (up to 20 secrets per call **(verify)**), `DescribeSecret` (metadata, no value), `ListSecrets`.
- **Request quotas** (per Region): `GetSecretValue` **10,000/s**; `DescribeSecret` 40,000/s; `BatchGetSecretValue` 100/s; `ListSecrets` 100/s; `CreateSecret` 50/s; `PutSecretValue/UpdateSecret…` 50/s combined; `RotateSecret` 50/s combined.
- **Cross-account** requests count against the **caller's** account quota.
- **Cache secrets** in the app with the official **caching components** (Java, Python, .NET, Go, JavaScript, Rust) or the **AWS Parameters and Secrets Lambda Extension** (local cache, default TTL 300 s) to cut cost, latency and throttling.
- **Console/CLI**: `aws secretsmanager get-secret-value --secret-id prod/db`.
- **Container secrets injection**: ECS task definition `secrets` (from Secrets Manager ARN or Parameter Store); EKS via **Secrets Store CSI driver / ASCP**.
- **CloudFormation dynamic reference**: `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` keeps secrets out of templates.
- **Random password**: `GetRandomPassword` (configurable length/character classes/exclusions).
- Secrets in **environment variables** of Lambda are visible in config; prefer fetching at runtime (or the extension).
- **Client-side hygiene**: never log secret values; refresh on `AccessDenied/auth failure` because a rotation may have changed it.

## D. Rotation
- **Rotation** periodically changes the secret **and** the credential in the target system.
- **Three forms**:
  - **Managed rotation**: for **managed secrets** (RDS/Aurora master user secrets, Redshift admin, DocumentDB). Service configures it; **no Lambda**; default schedule is service-defined (e.g. every 7 days for RDS master secret) **(verify)**.
  - **Managed external secrets**: rotation by partners (e.g., Salesforce, Snowflake, Confluent) **(verify)**.
  - **Lambda rotation**: you (or a template) provide a **rotation Lambda**; templates exist for **RDS (MySQL, PostgreSQL, Oracle, SQL Server, MariaDB, Db2), Redshift, DocumentDB, MongoDB, Elasticsearch/OpenSearch**, generic.
- **Schedule**: `rate(...)` or `cron(...)` with a **rotation window** (duration) and **rotate immediately** option on enabling. Frequency down to **4 hours** **(verify)**; typical 30–90 days.
- **Four Lambda steps** (Secrets Manager invokes the function with a `Step` field):
  1. **`createSecret`**: create the new secret version labeled `AWSPENDING`.
  2. **`setSecret`**: set the new credential in the database/service.
  3. **`testSecret`**: test the `AWSPENDING` credential works.
  4. **`finishSecret`**: move `AWSCURRENT` to the new version (old becomes `AWSPREVIOUS`).
- **Strategies for databases**:
  - **Single-user**: updates the same user's password; brief window where open connections with the old password can fail.
  - **Alternating users** (a.k.a. two-user): two users, alternately rotated; **no downtime** window; needs a **superuser/master secret** to clone/alter the user; use for production.
- **Network**: the rotation Lambda must reach the database (**same VPC / subnets / security groups**) and reach **Secrets Manager** (VPC endpoint or NAT). The DB security group must allow the Lambda.
- **Lambda permissions**: resource policy lets `secretsmanager.amazonaws.com` invoke it; execution role needs Secrets Manager actions (`GetSecretValue, PutSecretValue, DescribeSecret, UpdateSecretVersionStage, GetRandomPassword`) and KMS.
- **Apps must tolerate rotation**: fetch `AWSCURRENT` regularly, retry on auth failure, don't cache forever. Connection pools should re-read credentials.
- **Cancel rotation**: `CancelRotateSecret`; failed rotation leaves `AWSPENDING` stuck: fix and re-run, or move labels back.
- **Rotation cost**: Secrets Manager does not charge for versions; you pay for the **rotation Lambda** (and API calls) except managed rotation.
- **Secrets Manager rotation does not rotate the KMS key**; configure KMS rotation separately.
- **RDS master user secret integration**: `ManageMasterUserPassword=true` (RDS/Aurora, Redshift) → RDS creates and rotates the secret (encrypted with `aws/secretsmanager` or your CMK) so you never see the password.

## E. Access control
- **Identity-based IAM policies**: allow `secretsmanager:GetSecretValue` on specific ARNs/paths; also `DescribeSecret`, `PutSecretValue`, `RotateSecret`, `DeleteSecret`, `GetResourcePolicy`.
- **Resource-based policy** on the secret (up to **20,480 characters**): grant other accounts/roles, deny unless from the org (`aws:PrincipalOrgID`), require VPC endpoint (`aws:SourceVpce`).
- **KMS permissions**: caller needs **`kms:Decrypt`** on the key. For `aws/secretsmanager` (AWS managed key) cross-account use is **not possible**; use a **customer managed key** and share it.
- **Cross-account access** needs: resource policy on the secret (other account principal), CMK key policy allowing the other account, and the other account's IAM policy allowing both.
- **ABAC**: tag secrets (`team=data`) and allow when `aws:ResourceTag/team` = `aws:PrincipalTag/team`.
- **Block public policies**: Secrets Manager can **validate** resource policies (`ValidateResourcePolicy`) and optionally **block public access** (`BlockPublicPolicy`).
- **Condition keys**: `secretsmanager:ResourceTag/…`, `secretsmanager:SecretId`, `secretsmanager:VersionStage`, `secretsmanager:resource/AllowRotationLambdaArn`, `secretsmanager:RecoveryWindowInDays`, `secretsmanager:ForceDeleteWithoutRecovery`.
- **Least privilege**: grant `GetSecretValue` on the specific secret to the specific workload role; separate roles for managing (admin) and using (app).
- **Access Analyzer** flags secrets shared externally; **RCPs** can enforce an org-only perimeter for Secrets Manager.

## F. Replication, deletion and recovery
- **Multi-Region secrets**: pick **replica Regions** and an optional per-Region KMS key. Replicas are **read-only copies kept in sync**; rotation happens in the primary and replicates. Each replica is **billed as a secret**.
- **Promote a replica** to standalone for DR.
- **Deletion**: `DeleteSecret` schedules deletion with a **recovery window of 7–30 days (default 30)**; during the window the secret can't be read but **can be restored** (`RestoreSecret`). Use `ForceDeleteWithoutRecovery` to delete immediately (no undo).
- **Name reuse**: a secret pending deletion keeps its name until deleted; create a new secret with another name or force-delete.
- **Backups**: Secrets Manager is highly available; export is not provided. Use IaC for definitions and keep **break-glass** copies per policy.
- **Versions** give a short history; revert by moving `AWSCURRENT` back with `UpdateSecretVersionStage`.

## G. Network and encryption
- **VPC interface endpoint** for Secrets Manager (`com.amazonaws.<region>.secretsmanager`) keeps calls private; add an **endpoint policy**.
- **FIPS endpoints** exist. TLS in transit.
- **At rest**: AES-256 envelope encryption via KMS; each secret value encrypted with a data key; version and label metadata are not secret.
- **CMK per environment/team** for separation; remember KMS costs and quotas.
- **Secrets Manager caches nothing server-side for you**; clients cache.

## H. Monitoring and audit
- **CloudTrail**: `GetSecretValue`, `PutSecretValue`, `RotateSecret`, `DeleteSecret`, `PutResourcePolicy`. Management events are on by default; GetSecretValue is a **management event** (recorded) **(verify)**.
- **CloudWatch metrics** (`AWS/SecretsManager`): `SecretCount`; others via CloudTrail metric filters.
- **EventBridge** events: rotation succeeded/failed, secret deleted, version staged **(verify names)**; alert on failed rotation.
- **AWS Config** rules: `secretsmanager-rotation-enabled-check`, `secretsmanager-scheduled-rotation-success-check`, `secretsmanager-secret-unused`, `secretsmanager-using-cmk`, `secretsmanager-secret-periodic-rotation`.
- **Security Hub** controls: rotation enabled, unused secrets, CMK encryption.
- **Last accessed date** (`DescribeSecret.LastAccessedDate`) finds unused secrets.

## I. Cost
- **$0.40 per secret per month** (prorated hourly) and **$0.05 per 10,000 API calls** (us-east-1 example; check current). No charge for secret **versions**.
- **Replica secrets** are billed like secrets.
- **Rotation Lambda** invocations and duration billed by Lambda; KMS charges apply for a CMK (and per request).
- **Cost levers**: **cache** secrets; **delete unused** secrets; store **many related values in one JSON secret** (one fee) when they rotate together; use **Parameter Store standard** for non-secret or low-sensitivity config.
- Compare: Parameter Store SecureString **standard** is free (up to limits); Secrets Manager adds **rotation, cross-account, replication, larger values**.

## J. Limits cheat sheet
| Item | Value |
|---|---|
| Secret value size | **65,536 bytes** |
| Secrets per Region | **500,000** |
| Versions per secret | **100** |
| Staging labels per secret | **20** |
| Resource policy length | **20,480 chars** |
| Recovery window | **7–30 days** (default 30) |
| `GetSecretValue` rate | **10,000/s** per Region |
| `DescribeSecret` rate | 40,000/s |
| `BatchGetSecretValue` rate | 100/s |
| `CreateSecret` / `RotateSecret` | 50/s |
| Update frequency guidance | not more than once per 10 min sustained |
| Quotas adjustable? | Mostly **not adjustable** |

## K. Exam skills mapping
- **4.1.3 Create and rotate credentials (Secrets Manager)**: rotation.
- **4.2.2 Store credentials (Secrets Manager, Parameter Store)**: store credentials.
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: resource policies.

## L. Scenarios: "If X → Y, because Z"
- If an application stores a database password in code → **move it to Secrets Manager and fetch at runtime**, because it removes hard-coded credentials and enables rotation.
- If DB credentials must rotate every 30 days with zero downtime → **Lambda rotation with the alternating-users strategy**, because one user always stays valid during rotation.
- If you run RDS/Aurora/Redshift and want no one to ever see the admin password → **managed master user secret (`ManageMasterUserPassword`)**, because the service creates, stores and rotates it.
- If rotation fails with timeouts → **put the rotation Lambda in the DB's VPC and add a Secrets Manager VPC endpoint/NAT**, because it must reach both.
- If another AWS account must read a secret → **resource policy + customer managed KMS key shared to that account**, because `aws/secretsmanager` can't be shared.
- If a secret is read thousands of times per second → **client-side caching or the Lambda extension**, because it cuts API cost and throttling.
- If you need DR in another Region → **replicate the secret to a replica Region (with a key there)**, because replicas are kept in sync and can be promoted.
- If someone deleted a secret by mistake → **`RestoreSecret` within the recovery window**, because deletion is scheduled for 7–30 days.
- If MWAA/Airflow connections must not live in the metadata DB → **Secrets Manager backend with `airflow/connections/*`**, because credentials stay in Secrets Manager.
- If rotation breaks a long-lived connection pool → **make the app re-fetch on auth errors and use `AWSCURRENT`**, because the old password stops working after rotation.
- If you must find stale secrets → **`LastAccessedDate` + Config rule `secretsmanager-secret-unused`**, because unused secrets cost money and add risk.

Verified from AWS docs on 2026-11-03 (Secrets Manager quotas, pricing, rotation overview, MWAA Secrets Manager backend page).
Unconfirmed (verify): `BatchGetSecretValue` batch size; minimum rotation frequency; managed rotation default schedules; which partners support managed external rotation; EventBridge event names; whether `GetSecretValue` appears as a management event in default CloudTrail history; Config rule names; Lambda extension default TTL.

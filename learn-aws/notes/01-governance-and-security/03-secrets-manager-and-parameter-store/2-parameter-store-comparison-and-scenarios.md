# AWS Systems Manager Parameter Store – 2. Parameter Store, comparison and scenarios

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **Parameter Store** (a capability of **AWS Systems Manager**) is a hierarchical store for **configuration data and secrets**: strings, lists and encrypted values.
- Use it for **app config** (feature flags, endpoints, AMI IDs, job parameters) and for **low-cost secrets** (SecureString).
- Regional, with IAM control, versioning, change notifications through **EventBridge**, and CloudTrail audit.
- It does **not** rotate secrets automatically (no built-in rotation).
- DEA-C01: used for **pipeline configuration** and credentials (4.2.2 store credentials), referenced from Glue, Lambda, ECS, CloudFormation, CodeBuild, MWAA.

## B. Parameter types
- **String**: plain text (config).
- **StringList**: comma-separated values.
- **SecureString**: value **encrypted with KMS** (`aws/ssm` AWS managed key by default, or a **customer managed key**). Use `--with-decryption` to read plaintext.
- **Data type** `text` or `aws:ec2:image` (validates AMI IDs).
- **Public parameters**: AWS-published values under `/aws/service/…` (latest AMI IDs for AL2023/Windows, ECS optimized AMIs, EKS AMIs, Glue/other service defaults). Read-only.

## C. Tiers and limits
| Feature | Standard | Advanced |
|---|---|---|
| Parameters per account/Region | **10,000** | **100,000** |
| Value size | **4 KB** | **8 KB** |
| Parameter policies (expiration, notifications) | **No** | **Yes** |
| Cross-account sharing (via RAM) | **No** | **Yes** |
| Cost | **Free** | **Charged per advanced parameter/month** (and higher per-API charges) |
| Change tier | Can **upgrade** to advanced | **Cannot downgrade** (recreate instead) |
- **Default tier setting**: Standard, Advanced, or **Intelligent-Tiering** (auto-promotes to advanced when needed).
- **Hierarchy**: names like `/prod/data/glue/db-name`; up to **15 levels**; fetch many at once with `GetParametersByPath` (recursive, filters).
- **Name rules**: letters, numbers, `.-_/`; a name cannot begin with `aws` or `ssm` (reserved); case-sensitive; max length 1,011 chars including path **(verify)**.
- **Versions**: each update creates a new version (history up to **100** versions); you can attach **labels** (e.g., `prod`) and reference `name:version` or `name:label`.
- **Throughput**: default standard throughput about **40 TPS** for `GetParameter(s)`; **higher throughput** setting (extra cost) raises it (up to ~3,000 TPS) **(verify numbers)**.
- `GetParameters` returns up to **10** names per call; `GetParametersByPath` returns up to 10 per page.
- **Parameter policies** (advanced only): **Expiration** (delete at a date), **ExpirationNotification** (event X days before), **NoChangeNotification** (event if not changed for N days).

## D. Access control and encryption
- **IAM**: `ssm:GetParameter`, `GetParameters`, `GetParametersByPath`, `PutParameter`, `DeleteParameter`, `DescribeParameters`; scope by **path ARN** (`arn:aws:ssm:region:acct:parameter/prod/data/*`).
- **SecureString** also needs **`kms:Decrypt`** (and `kms:GenerateDataKey` to write) on the key. With the default `aws/ssm` key, any principal allowed by IAM in that account can decrypt via SSM; with a **CMK** the key policy adds a second control layer.
- **ABAC**: tag parameters; allow with `aws:ResourceTag`.
- **Cross-account**: share **advanced** parameters via **AWS RAM** (then the other account references the full ARN); SecureString sharing needs a **CMK** shared to the other account.
- **Block** wildcards: `ssm:GetParametersByPath` on `/prod/*` returns everything under it; avoid giving workloads access to the entire tree.
- **No resource policies** directly on parameters (use RAM or IAM).
- **VPC interface endpoint** for `ssm` keeps calls private.
- **Audit**: CloudTrail logs `GetParameter` calls (including SecureString decrypt). Use EventBridge `Parameter Store Change` events for updates.

## E. Where parameters are used in pipelines
- **CloudFormation**: `AWS::SSM::Parameter::Value<String>` type and `{{resolve:ssm:/path}}` / `{{resolve:ssm-secure:/path}}` dynamic references.
- **Lambda**: read at start-up or with the **Parameters and Secrets Lambda Extension** (caches both SSM and Secrets Manager).
- **ECS/Fargate**: task definition `secrets` can reference SSM parameters (plain or SecureString).
- **CodeBuild/CodePipeline**: environment variables of type `PARAMETER_STORE`.
- **Glue**: pass job arguments; read SecureString in the job script with boto3 (job role needs permissions).
- **Step Functions**: SDK integration `aws-sdk:ssm:getParameter` for configuration lookups.
- **MWAA/Airflow**: SSM can be the **secrets backend** (`SystemsManagerParameterStoreBackend`) for variables/connections.
- **EMR/EC2/Systems Manager automation and State Manager**: read config.
- **AMI lookup**: `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64` public parameter.
- **Environment promotion**: same code, `/dev/…` vs `/prod/…` paths set by an env var.

## F. Secrets Manager vs Parameter Store (exam favourite)
| Feature | **Secrets Manager** | **Parameter Store** |
|---|---|---|
| Purpose | **Secrets** with lifecycle | **Config + simple secrets** |
| Automatic **rotation** | **Yes** (managed + Lambda) | **No** (DIY with Lambda/EventBridge) |
| Value size | **64 KB** | 4 KB (standard) / 8 KB (advanced) |
| Cost | **$0.40/secret/mo + $0.05/10k calls** | Standard **free**; advanced paid |
| Cross-account | **Resource policy** + CMK | **Advanced + RAM** (+ CMK for SecureString) |
| Multi-Region replication | **Built in** | Manual (copy/EventBridge) |
| Versioning | Staging labels (`AWSCURRENT`…) | Numeric versions + labels |
| Encryption | **Always** KMS | Optional (SecureString) |
| Integration | RDS/Redshift/DocumentDB managed secrets, DMS, Glue, QuickSight | CloudFormation, ECS, CodeBuild, public AMI parameters |
| Throughput | 10,000 GetSecretValue/s | ~40 TPS default standard (higher throughput option) |
| Hierarchy | Names with `/` (no real tree API) | **True hierarchy** + `GetParametersByPath` |
| Expiry/notifications | Rotation/deletion events | **Parameter policies** (advanced) |
| Best for | DB creds, API keys that must rotate | Feature flags, endpoints, AMI IDs, cheap secrets |
- **Rule of thumb**: **needs rotation or cross-Region replication or managed DB integration → Secrets Manager**. **Plain config, high-volume reads, cost-sensitive, hierarchy → Parameter Store**.
- Secrets Manager secrets can be read **through the Parameter Store API** using the reserved path `/aws/reference/secretsmanager/<secret-name>`, giving one API for both.
- Both are **Regional**, **KMS-integrated**, **IAM-controlled** and **audited in CloudTrail**.

## G. Other secret/config options (context)
- **AWS AppConfig**: feature flags and dynamic configuration with **validation and gradual deployment** (part of Systems Manager); good for runtime config rollouts.
- **Lambda environment variables**: small config; encrypted at rest; visible in console; avoid secrets in plain.
- **S3 + KMS**: files with credentials (avoid for secrets).
- **Glue connection properties / DMS endpoint passwords**: can reference Secrets Manager instead of storing passwords.
- **Redshift Data API**: authenticate using a **Secrets Manager ARN** or IAM temporary credentials.
- **IAM roles / IAM database authentication** (RDS/Aurora/Redshift): **no stored password** at all (preferred when supported).
- **Redshift IAM `GetClusterCredentials`**: temporary DB credentials.
- **Certificates**: **ACM** (public/private certs) rather than secrets.

## H. Monitoring and troubleshooting
- **Parameter not found** → wrong Region, wrong path/case, deleted, or `GetParametersByPath` without recursion.
- **AccessDenied on SecureString** → missing `kms:Decrypt`, wrong key, or policy scoped to wrong ARN path.
- **Throttling (`ThrottlingException`)** → default throughput; cache values, use `GetParametersByPath`, or enable higher throughput.
- **Value too large** → standard 4 KB limit; move to advanced or store large data in S3 and keep a pointer.
- **Cannot downgrade advanced to standard** → recreate as a new standard parameter.
- **Cross-account fails** → parameter is standard (not shareable), or RAM share not accepted, or KMS CMK not shared.
- **Stale values** → app cached too long; use short TTL or refresh on change events.
- **Change tracking**: EventBridge rule on `Parameter Store Change` → Lambda/SNS; Config managed rules; CloudTrail `PutParameter`.
- **Cost surprise** → many advanced parameters or higher throughput.

## I. Cost
- **Standard parameters**: no charge for storage; standard API interactions free (within default throughput).
- **Advanced parameters**: per parameter per month (about **$0.05**) plus per-10,000 API interactions **(verify current prices)**.
- **Higher throughput**: charged per 10,000 interactions **(verify)**.
- **SecureString with CMK**: KMS key fee ($1/month) and request fees; with `aws/ssm`, KMS requests still count against KMS quotas but no key fee.
- **Secrets Manager**: $0.40/secret/month + $0.05 per 10,000 calls (see file 1).
- **Choose per value**: thousands of config values → Parameter Store standard; a few critical DB credentials → Secrets Manager.

## J. Limits summary
| Item | Standard | Advanced |
|---|---|---|
| Parameters | 10,000 | 100,000 |
| Value size | 4 KB | 8 KB |
| Hierarchy depth | 15 | 15 |
| Versions kept | 100 | 100 |
| Policies | none | up to 10 per parameter **(verify)** |
| Sharing | none | RAM |

## K. Exam skills mapping
- **4.2.2 Store credentials (Secrets Manager, Parameter Store)**: Parameter Store vs Secrets Manager.
- **4.1.3 Create and rotate credentials (Secrets Manager)**: rotation limits of Parameter Store.

## L. Scenarios: "If X → Y, because Z"
- If a database password must rotate automatically every 30 days → **Secrets Manager**, because Parameter Store has no built-in rotation.
- If thousands of non-sensitive config values are read frequently at low cost → **Parameter Store standard with caching**, because it is free and hierarchical.
- If you need to store a 6 KB certificate chain as config → **advanced parameter (8 KB)** or Secrets Manager (64 KB), because standard is limited to 4 KB.
- If another account must read a parameter → **advanced parameter shared via RAM (and shared CMK for SecureString)**, because standard parameters cannot be shared.
- If you need alerts before a temporary credential parameter expires → **advanced parameter with Expiration + ExpirationNotification policies**, because policies are an advanced-tier feature.
- If a CloudFormation template needs the latest Amazon Linux AMI → **public SSM parameter `/aws/service/ami-amazon-linux-latest/...`**, because AWS keeps it current.
- If a Lambda runs hot and hits Parameter Store throttling → **cache with the Lambda extension or increase throughput**, because default throughput is limited.
- If auditors need to see who read a secret value → **CloudTrail `GetSecretValue` / `GetParameter` events + KMS `Decrypt` events**, because both services log access.
- If you want no stored database password at all → **IAM database authentication (RDS/Aurora) or Redshift temporary credentials**, because authentication uses IAM tokens.
- If a SecureString cannot be decrypted in another account → **use a customer managed key shared with that account**, because `aws/ssm` is not shareable.
- If you need one API to read both secrets and parameters → **`/aws/reference/secretsmanager/<name>` through Parameter Store**, because it proxies Secrets Manager.
- If dynamic config must roll out gradually with rollback → **AWS AppConfig**, because it adds validators and deployment strategies.

Verified from AWS docs on 2026-11-03 (Parameter Store tiers, Secrets Manager quotas and pricing, MWAA secrets backend page).
Unconfirmed (verify): Parameter Store default and higher throughput numbers; advanced parameter price; parameter name length; number of policies per parameter; whether intelligent-tiering has extra cost; `/aws/reference/secretsmanager` path behaviour for rotation labels; AppConfig details.

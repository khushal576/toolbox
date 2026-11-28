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
- **If** a database password must **rotate automatically every 30 days**, **then** store it in **AWS Secrets Manager**, not in **AWS Systems Manager Parameter Store**. **This works because** Secrets Manager has built-in rotation (managed rotation or an **AWS Lambda** rotation function), while Parameter Store has **no built-in rotation**; you would have to build it yourself with Lambda and Amazon EventBridge.
- **If** thousands of **non-sensitive config values** are read often and cost must stay low, **then** use **AWS Systems Manager Parameter Store** **Standard** parameters and **cache** the values in the app. **This works because** Standard parameters are **free** (up to **10,000** per account and Region), and names form a **true hierarchy** (`/prod/data/...`) that `GetParametersByPath` reads many at a time. The catch: default throughput is only about **40 TPS** **(verify)**, so caching matters.
- **If** you must store a **6 KB** certificate chain as config, **then** use an **Advanced** parameter in **AWS Systems Manager Parameter Store** (up to **8 KB**) or a secret in **AWS Secrets Manager** (up to **64 KB**). **This works because** a **Standard** parameter is limited to **4 KB**. The catch: Advanced parameters cost money each month and **cannot be downgraded** back to Standard.
- **If** another AWS account must read a parameter, **then** make it an **Advanced** parameter and share it with **AWS Resource Access Manager (RAM)**; for a **SecureString**, also share a **customer managed key** from **AWS Key Management Service (KMS)**. The other account then uses the full Amazon Resource Name (ARN). **This works because** only Advanced parameters can be shared; **Standard parameters cannot be shared**, and parameters have no resource policies.
- **If** you need an alert before a temporary credential stored as a parameter **expires**, **then** use an **Advanced** parameter with the **Expiration** policy (delete at a date) and the **ExpirationNotification** policy (send an Amazon EventBridge event some days before). **This works because** **parameter policies** exist only in the **Advanced** tier of **AWS Systems Manager Parameter Store**.
- **If** an **AWS CloudFormation** template needs the **latest Amazon Linux AMI** (Amazon Machine Image) ID, **then** reference the **public parameter** `/aws/service/ami-amazon-linux-latest/...` from **AWS Systems Manager Parameter Store**. **This works because** AWS publishes and keeps these read-only values current, so the template always gets the newest AMI ID.
- **If** a busy **AWS Lambda** function hits **Parameter Store throttling** (`ThrottlingException`), **then** cache values with the **AWS Parameters and Secrets Lambda Extension** or turn on the **higher throughput** setting. **This works because** default throughput is limited (about **40 TPS** for `GetParameter(s)` **(verify)**); the cache cuts calls, and higher throughput raises the limit at **extra cost**.
- **If** auditors need to see **who read a secret value**, **then** check **AWS CloudTrail** for **`GetSecretValue`** (AWS Secrets Manager) **(verify)** and **`GetParameter`** (AWS Systems Manager Parameter Store) events, plus **AWS Key Management Service (KMS)** **`Decrypt`** events. **This works because** both services log access in CloudTrail, and reading an encrypted value also needs a KMS decrypt.
- **If** you want **no stored database password at all**, **then** use **IAM database authentication** (Identity and Access Management, for Amazon RDS and Aurora) or **Amazon Redshift temporary credentials** (`GetClusterCredentials`). **This works because** login uses **IAM** identities and short-lived tokens or credentials instead of a saved password, so there is nothing to store or rotate.
- **If** a **SecureString** parameter cannot be decrypted in another account, **then** encrypt it with a **customer managed key** in **AWS Key Management Service (KMS)** and share that key with the other account. **This works because** the reader needs **`kms:Decrypt`** on the key, and the default **`aws/ssm`** key cannot be shared across accounts.
- **If** you want **one API** to read both secrets and parameters, **then** read **AWS Secrets Manager** secrets through **AWS Systems Manager Parameter Store** using the reserved path **`/aws/reference/secretsmanager/<secret-name>`**. **This works because** Parameter Store passes the request on to Secrets Manager, so the app uses only the Parameter Store API.
- **If** dynamic config must **roll out gradually** with **rollback**, **then** use **AWS AppConfig** (part of AWS Systems Manager) **(verify)**. **This works because** it adds **validation** and **gradual deployment** strategies for feature flags and runtime config, which plain Parameter Store does not have.

Verified from AWS docs on 2026-11-03 (Parameter Store tiers, Secrets Manager quotas and pricing, MWAA secrets backend page).
Unconfirmed (verify): Parameter Store default and higher throughput numbers; advanced parameter price; parameter name length; number of policies per parameter; whether intelligent-tiering has extra cost; `/aws/reference/secretsmanager` path behaviour for rotation labels; AppConfig details.

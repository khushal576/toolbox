# Amazon MWAA – 3. Security, networking, cost, monitoring, limits and scenarios

Short notes. Each point is a fact you can be asked about.

## A. Who can do what (access control)
- Three separate layers of access:
  1. **Managing the environment** (create, update, delete) → IAM `airflow:*` actions.
  2. **Opening the Airflow UI / REST API / CLI** → IAM tokens (`airflow:CreateWebLoginToken`, `airflow:InvokeRestApi`, `airflow:CreateCliToken`).
  3. **What tasks can do in AWS** → the environment's **execution role**.
- Managed-style policies you should know:
  - **AmazonMWAAFullConsoleAccess**: create/manage environments in the console.
  - **AmazonMWAAFullApiAccess**: all MWAA management APIs, **no Airflow UI access**.
  - **AmazonMWAAReadOnlyAccess**: list/get environments only.
  - **AmazonMWAAWebServerAccess**: `airflow:CreateWebLoginToken` → open the **Airflow UI** as an Airflow role.
  - **AmazonMWAARestAPIAccess**: `airflow:InvokeRestApi` → call the **Airflow REST API**.
  - **AmazonMWAAAirflowCliAccess**: `airflow:CreateCliToken` → run **CLI** commands.
- For web login, the policy `Resource` is `arn:aws:airflow:<region>:<acct>:role/<environment>/<airflow-role>`. The **environment ARN is not supported** in this resource field.
- **Airflow RBAC roles** that IAM maps to: **Admin, Op, User, Viewer, Public**. Pick the role in the IAM policy to control UI power. You can restrict a user to a **subset of DAGs** using custom Airflow roles.
- `iam:PassRole` (with `iam:PassedToService = airflow.amazonaws.com`) is needed to create an environment with an execution role.
- Prefer **federation / IAM Identity Center permission sets** and roles over IAM users.
- A **service-linked role** `AWSServiceRoleForAmazonMWAA` is created for networking (ENIs, VPC endpoints) on your behalf.
- UI tokens are **short-lived**; users reach the UI through the console or by calling `CreateWebLoginToken`.
- Private web server: users also need **network access** to the VPC endpoint (VPN, Direct Connect, bastion, Client VPN) in addition to the IAM token.

## B. The execution role (what your DAGs can do)
- **One execution role per environment**. All DAGs and tasks use it by default through the `aws_default` connection.
- **Trust policy** principals: `airflow.amazonaws.com` and `airflow-env.amazonaws.com`.
- Minimum permissions (the console can create them):
  - `airflow:PublishMetrics` on the environment.
  - **S3**: `s3:GetObject*`, `s3:GetBucket*`, `s3:List*` on the DAG bucket (and a **Deny** `s3:ListAllMyBuckets` on it in the sample); `s3:GetAccountPublicAccessBlock` when the account has a public access block.
  - **CloudWatch Logs**: create/put/get events on `airflow-<env>-*` log groups; `logs:DescribeLogGroups`.
  - `cloudwatch:PutMetricData`.
  - **SQS**: `ChangeMessageVisibility, DeleteMessage, GetQueueAttributes, GetQueueUrl, ReceiveMessage, SendMessage` on `arn:aws:sqs:<region>:*:airflow-celery-*`.
  - **KMS**: depends on the key type (below).
- **MWAA cannot add permissions** for the services your DAGs call (Glue, EMR, Redshift, Athena, Secrets Manager). **You add them** to the role. Added permissions apply immediately.
- Removing a needed permission breaks DAGs. You can **swap the execution role** on an existing environment at any time.
- **Do not reuse the name of a deleted execution role.**
- **Least privilege**: scope Glue job ARNs, S3 prefixes, secret ARNs; avoid `*`.
- **Per-team isolation**: because the role is per environment, use **separate environments** or **assumed roles via connections** to separate duties.

## C. Encryption
- **At rest**: MWAA encrypts the metadata DB, SQS queue, logs, and S3 data.
  - Default: **AWS owned key** (no key to manage).
  - Option: **customer managed KMS key** (symmetric, single-Region, referenced by **key ID or ARN – aliases and multi-Region keys not supported**).
- **The encryption choice cannot be changed after creation.**
- With an AWS owned key, the execution role's SQS KMS permission uses `NotResource` for keys in your own account; a DAG could in theory reach **SQS queues named `airflow-celery-*` in another account** that use a key that account allows. Mitigate with code review or use a **customer managed key**.
- With a **CMK**: the execution role needs `kms:Decrypt, DescribeKey, GenerateDataKey*, Encrypt` on the key with `kms:ViaService` for **SQS and S3**; the key policy must allow **CloudWatch Logs** (`logs.<region>.amazonaws.com`) with the `kms:EncryptionContext:aws:logs:arn` condition.
- The S3 bucket may use **SSE-S3 or SSE-KMS**; if SSE-KMS with your key, it must be the **same key** as the environment.
- **In transit**: TLS to the web server (HTTPS), TLS to AWS APIs; the web server access uses IAM-signed login tokens.
- **Secrets**: use Secrets Manager / Parameter Store backend rather than the metadata DB or Airflow Variables.
- The Airflow **Fernet key** encrypting DB connection passwords is managed by MWAA (reserved).

## D. Networking
- MWAA runs in **your VPC**. You must supply **two private subnets in two different AZs** and **1–5 security groups**.
- **Security group**: must have a **self-referencing inbound rule** (all traffic from itself) and an **outbound allow** (all, `0.0.0.0/0`). You may narrow to **TCP 443** and **TCP 5432** (metadata DB) in the self-referencing rule.
- **Network ACLs**: allow all traffic in and out of the subnets (recommended).
- **Web server access mode**:
  - **Public network**: UI reachable over the internet (still needs IAM login token).
  - **Private network**: UI reachable only through a **VPC interface endpoint** inside your VPC (use VPN, Direct Connect, Client VPN, bastion).
  - **Both public and private**: available for **Airflow 3.2.1 and later** **(verify)**; useful when the VPC has no internet but users do.
- **Routing**:
  - **Public routing** VPC: two public + two private subnets, **NAT gateway** (one per AZ for HA) and an **internet gateway**; private subnets route out via NAT.
  - **Private routing** VPC (no internet): private subnets only, **no NAT/IGW**; you need **VPC endpoints** for every AWS service the environment uses.
- **Required VPC endpoints for private routing** (with **private DNS enabled**, in both private subnets, using the environment security group): S3 (gateway), **SQS**, **CloudWatch Logs**, **CloudWatch Monitoring**, **ECR (api and dkr)**, **KMS** (if CMK), **Secrets Manager** (if used), plus MWAA's own **Airflow endpoints** (`airflow.api`, `airflow.env`, `airflow.ops`) **(verify exact service names)**. Plus endpoints for services your DAGs call (Glue, Athena, EMR, STS…).
- **VPC endpoint policies** must allow the needed actions; the **S3 gateway endpoint policy** must allow the DAG bucket.
- Private routing environments **cannot install packages from PyPI** (no internet): use wheels in `plugins.zip` or a private repo with VPC access.
- MWAA creates **1–2 VPC endpoints (ENIs)** in your VPC for the web server (and database) depending on the access mode.
- **Shared VPCs** (owned by another account) are supported.
- **Reach on-prem or other VPC resources**: peering, Transit Gateway, VPN/Direct Connect from the private subnets; remember security groups and DNS.
- **IPv6/dual-stack**: supported with specific subnet settings **(verify)**.
- The **Airflow REST API** can be called over the public MWAA API endpoint even for private web servers (needs IAM); restrict with `aws:SourceVpc/SourceVpce` conditions.

## E. Audit and governance
- **CloudTrail** records MWAA API calls (create/update/delete environment, `CreateWebLoginToken`, `InvokeRestApi`, `CreateCliToken`).
- **Airflow audit**: task/DAG activity in the **Airflow logs** (CloudWatch). Airflow's own event log is in the UI (Admin).
- Use **tags** on the environment for cost allocation and ABAC.
- **Service control policies** can block creation in disallowed Regions or require private web server mode via condition keys **(verify keys)**.
- **AWS Config** tracks MWAA environment configuration **(verify)**.
- Patch/Version hygiene: end-of-support versions get **no technical support**; plan upgrades (180-day notice, 12-month minimum support).

## F. Logging
- Five Airflow log types, each to its own **CloudWatch log group** (`airflow-<env>-<type>`): **DAG processing**, **scheduler**, **task**, **web server**, **worker**.
- Each type has a **log level** (`CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`) set per environment; enable what you need.
- Task logs are also viewable in the Airflow UI (read from CloudWatch).
- Special streams: `requirements_install_ip` (scheduler group), `startup_script_execution_ip`.
- **Retention**: set a CloudWatch Logs retention policy; the default is **never expire**, which grows cost.
- Use **CloudWatch Logs Insights** to search errors across tasks.
- **Log level DEBUG** can multiply log volume and cost.

## G. Metrics and alarms
- CloudWatch namespaces: **`AmazonMWAA`** (Airflow StatsD metrics) and **`AWS/MWAA`** (service metrics for the container health, for example CPU/memory per component **(verify names)**).
- Key Airflow metrics (dimension: `Function`, `DAG`, `Task`, `Pool`, `Operator`):
  - Capacity: **`RunningTasks`**, **`QueuedTasks`**, `OpenSlots`, `PoolOpenSlots`, `PoolStarvingTasks`.
  - Scheduler health: **`SchedulerHeartbeat`**, `SchedulerLoopDuration`, `CriticalSectionBusy`, `TasksStarving`, `TasksExecutable`.
  - DAG parsing: **`ImportErrors`**, **`TotalParseTime`**, `DagBagSize`, `ProcessorTimeouts`, `DAGFileProcessingLastDuration`, `DAGFileRefreshError`.
  - Task outcome: **`TaskInstanceFailures`**, `TaskInstanceSuccesses`, `OperatorFailures`, `ZombiesKilled`, `TasksKilledExternally`, `TaskInstanceDuration`, `TaskInstanceQueuedDuration`, `TaskCpuUsage`, `TaskMemoryUsage` (2.10.1+).
  - DAG timing: `DAGDurationSuccess/Failed`, `DAGScheduleDelay`, `FirstTaskSchedulingDelay`.
  - Triggerer: `TriggersRunning`, `TriggerHeartbeat`, `TriggersFailed`.
- Control volume with `metrics.metrics_allow_list` / `metrics.metrics_block_list` (comma-separated prefixes; **allow list wins** if both set; applies from 2.6.3).
- Baseline alarms: `SchedulerHeartbeat` missing, `ImportErrors > 0`, `QueuedTasks` high for long, `TaskInstanceFailures` spike, worker CPU/memory high, `TotalParseTime` rising.
- Alert from DAGs with callbacks (`on_failure_callback`) → **SNS** or **EventBridge**.
- MWAA publishes health with `airflow:PublishMetrics`.

## H. Troubleshooting (symptom → cause → fix)
- **DAG not in the UI** → file not in `dags/`, syntax/import error, parse timeout, scheduler overloaded → check DAG processing logs, `ImportErrors`, raise timeouts, simplify top-level code.
- **"Broken DAG" import error** → missing package/plugin → fix `requirements.txt`/`plugins.zip` and update the environment.
- **Environment update fails and rolls back** → requirements conflict or > 10 min install, bad startup script → read `requirements_install_ip` and `startup_script_execution_ip` logs.
- **Tasks stay queued** → worker max reached, pool slots exhausted, `max_active_tasks_per_dag`, `worker_autoscale` low → raise limits/max workers; check `QueuedTasks`.
- **Tasks fail with `Task exited with return code -9` / zombie** → worker out of memory → lower `worker_autoscale` or bigger class.
- **Scheduler heartbeat lost / slow scheduling** → too many DAGs or slow parsing → increase class/schedulers, reduce parse load.
- **Task cannot reach AWS service (timeout)** → no NAT or missing VPC endpoint in private routing → add NAT/endpoint, check security group egress.
- **`AccessDenied` from Glue/Athena/EMR** → execution role lacks permission → add to role (MWAA won't).
- **Cannot open UI (private)** → no network path to the VPC endpoint or missing `CreateWebLoginToken` → VPN/bastion, IAM policy.
- **Login works but "Access denied" in UI** → wrong Airflow role in the IAM resource ARN → use Admin/Op/User/Viewer as needed.
- **Logs missing in task view** → logging not enabled for task logs, execution role lacks logs permission, KMS key policy blocks CloudWatch Logs.
- **Secrets Manager errors** → role lacks `GetSecretValue`, wrong prefix, quoted values in connection URI.
- **Sensor never ends** → `poke` mode holding slot, no `timeout` → set `timeout`, use `reschedule`/deferrable.
- **Duplicate runs after catch-up** → `catchup=True` with old `start_date` → set `catchup=False`.
- **Stuck "running" tasks** → stranded tasks after scale-in/restart → clear/mark failed in the UI.
- **High cost** → idle environment, high min workers, large class, extra schedulers → right-size, lower min workers, schedule windows (delete/recreate non-prod) or use Serverless/Step Functions.
- **Version end-of-support notice** → upgrade in staging, then production.

## I. Cost
- Provisioned MWAA bills by the hour (per second) for:
  - **Environment** (by class): includes the base web server, one worker set, schedulers and DB. Example us-east-1: **small $0.49/hr, large $0.99/hr** (check current rates).
  - **Additional workers** (autoscaled above the included ones): example **small $0.055/hr, large $0.22/hr** per worker.
  - **Additional schedulers**: example large $0.22/hr.
  - **Additional web servers**: example large $0.11/hr.
  - **Metadata DB storage**: about **$0.10 per GB-month** (no pre-provisioning).
- **No upfront or minimum fees**, but you **pay while the environment exists** even with no DAG runs.
- Other costs: **NAT gateway/data transfer**, **VPC endpoints**, **CloudWatch Logs and metrics**, **S3**, **Secrets Manager** secrets and API calls, **KMS**, plus the services DAGs call (Glue, EMR…).
- Examples from the pricing page: large env + 10 peak workers + 4 web servers + 3 schedulers + 40 GB ≈ **$1,047/month**; small env spiking to 50 workers 1 h/day + 10 GB ≈ **$449/month** (illustrative).
- **Cost levers**:
  - Pick the **smallest class** that fits DAG count and parse time.
  - Lower **min workers**; let autoscaling handle peaks.
  - Use **deferrable operators/reschedule sensors** so fewer workers are needed.
  - Offload heavy compute to **Glue/EMR/Batch** (billed separately and only while running).
  - **Delete dev/test environments** outside working hours (rebuild from IaC; export metadata first).
  - Set **log retention** and sensible log levels; cut metrics with allow lists.
  - Consider **Step Functions / EventBridge Scheduler / MWAA Serverless** for simple or sparse workloads.
  - Reduce NAT charges with **VPC endpoints** (S3 gateway endpoint is free).
- MWAA Serverless example: **$0.080 per task-hour** (us-east-1), one-second billing, 1-minute minimum, no idle cost **(verify)**.

## J. Limits and numbers
| Item | Value |
|---|---|
| Subnets | **2 private** in **2 AZs** (public routing: plus 2 public) |
| Security groups | **1–5**; self-referencing inbound required |
| Workers | min **1**, default max **10**, max **25** by default |
| Schedulers | default **2**; **2–5** (mw1.micro: 1) |
| DAG capacity (definitions) | micro 25, small 50, medium 250, large 1,000, xlarge 2,000, 2xlarge 4,000 |
| Default tasks per worker | micro 3, small 5, medium 10, large 20, xlarge 40, 2xlarge 80 |
| `requirements.txt` libraries total | recommended **< 1 GB**; install must finish in **10 min** |
| Environment create / update | about **20–30 min** / **10–30 min** |
| Airflow version support | ≥ **3 minor versions**, ≥ **12 months** each, **180 days'** notice |
| Upgrades | in-place **minor** only; major needs migration **(verify)** |
| Constraints file | **required from 2.7.2** |
| Web server login token | short-lived; roles Admin/Op/User/Viewer/Public |
| S3 bucket | versioning **on**, public access **blocked**, same Region |
| Log groups | 5 types; retention default never expires |
| `dag_dir_list_interval` default | **300 s**; `min_file_process_interval` **30 s** |
| `dagbag_import_timeout` / `dag_file_processor_timeout` | **30 s / 50 s** |
| `max_active_tasks_per_dag` | **16** |
| `celery.sync_parallelism` | **1** |
- Other service quotas (environments per Region, etc.) are in **Service Quotas**; many are soft.

## K. Exam skills mapping
- **3.1.2 Troubleshoot managed workflows**: troubleshoot managed workflows.
- **3.3.4 Troubleshoot performance**: metrics and scaling.
- **3.3.7 CloudWatch Logs for application data**: Airflow logs in CloudWatch.
- **4.1.4 IAM roles for access (Lambda, API Gateway, CLI, CloudFormation)**: execution role.
- **4.1.1 Update VPC security groups**: VPC security groups.
- **4.3.2 Encryption keys (KMS)**: KMS choice.

## L. Scenarios: "If X → Y, because Z"
- **If** users must open the Airflow UI **only from the corporate network**, **then** use **private network** web server mode. The UI is then reached through a **VPC interface endpoint**, which users reach over a VPN or **AWS Direct Connect**. **This works because** the UI is **not reachable from the internet**. Users still need an Identity and Access Management (IAM) login token (`airflow:CreateWebLoginToken`) as well as the network path.
- **If** a developer should **trigger DAGs but not change the environment**, **then** give **AmazonMWAAAirflowCliAccess** or **AmazonMWAARestAPIAccess**, plus **AmazonMWAAWebServerAccess** with the Airflow **User** role, and **no AmazonMWAAFullConsoleAccess**. **This works because** MWAA keeps access in separate layers: **managing the environment** (`airflow:*` IAM actions) is separate from **using Airflow** (UI, REST API and CLI tokens).
- **If** a user should **open the UI but must not edit connections**, **then** put the **Viewer** or **User** Airflow role in the resource ARN of the `CreateWebLoginToken` policy (`.../role/<environment>/<airflow-role>`). **This works because** the Airflow role-based access control (RBAC) role (Admin, Op, User, Viewer, Public) comes from that **IAM resource ARN**. The environment ARN is not supported there, and a wrong role gives "Access denied" inside the UI.
- **If** DAG tasks call **AWS Glue** and fail with `AccessDenied`, **then** add the needed Glue permissions to the environment's **execution role** (the IAM role all tasks use). **This works because** MWAA **cannot detect or add** permissions for the services your DAGs call; you add them. Added permissions apply **immediately**; scope them to specific job ARNs.
- **If** the VPC has **no internet** and tasks **time out calling Amazon Athena**, **then** add **VPC interface endpoints** for Athena and every other service the DAGs call (Glue, STS…). **This works because** private routing has **no NAT gateway or internet gateway**, so workers in the private subnets reach AWS services only through VPC endpoints. Endpoint policies and security groups must allow the traffic.
- **If** compliance needs **customer-controlled encryption**, **then** create the environment with a **customer managed AWS Key Management Service (KMS) key**: symmetric, single-Region, given by key ID or ARN (**no alias**). **This works because** the encryption choice **cannot be changed after creation**, so it must be set at the start. The key policy must allow CloudWatch Logs, and an SSE-KMS S3 bucket must use the same key.
- **If** you want to **keep database passwords out of the Airflow metadata DB**, **then** use the **AWS Secrets Manager backend** with the `airflow/connections` prefix. **This works because** each connection is stored as a secret (`airflow/connections/<conn_id>`), protected by **KMS** encryption and **IAM** permissions, and Airflow checks the backend first.
- **If** the **bill is high but there are few DAGs**, **then** **downsize** the environment class, **lower min workers**, or move to **AWS Step Functions** or **MWAA Serverless** (verify). **This works because** a provisioned environment is billed **by the hour** while it exists, even with no DAG runs (for example **small $0.49/hr**, **large $0.99/hr** in us-east-1). Step Functions and Serverless have no idle cost.
- **If** a **non-production environment sits idle at night**, **then** **delete it** and **recreate it from Infrastructure as Code (IaC)**, for example on a schedule. **This works because** billing **stops only when the environment is deleted**. Export metadata (variables, connections) first, since the metadata DB is not backed up for you, and expect about **20–30 minutes** to recreate.
- **If** you need to pass a **2 GB dataset between tasks**, **then** write it to **Amazon S3** and pass only the **S3 key through XCom**. **This works because** XCom is stored in the **metadata DB** and is meant for small values; large XComs bloat the DB and slow the scheduler.
- **If** the **scheduler heartbeat stops**, **then** check the `SchedulerHeartbeat` metric, DAG parse time (`TotalParseTime`) and the **environment class size**. **This works because** too many DAGs or slow parsing **overload the scheduler**, and an overloaded scheduler stops heartbeating. Fix it with a bigger class, more schedulers, or less parse load.
- **If** an Airflow version **reaches end of support**, **then** upgrade in a **staging environment first**, then production. **This works because** after that date you **cannot create or upgrade to** that version and get **no technical support**. MWAA gives **180 days' notice**.
- **If** an **auditor asks who opened the Airflow UI**, **then** search **AWS CloudTrail** for `CreateWebLoginToken` events. **This works because** every UI login starts with that API call, and CloudTrail records it with other MWAA API calls.
- **If** DAGs must **call an on-premises database**, **then** give the private subnets routes over **VPN**, **AWS Direct Connect** or **AWS Transit Gateway (TGW)**, and add **security group** rules. **This works because** MWAA workers run **inside your VPC**, so they reach the database through the VPC's routing, security groups and DNS.

Verified from AWS docs on 2026-11-03 (execution role, access policies, networking, S3 bucket, environment class, autoscaling, metrics, pricing, versions).
Unconfirmed (verify): exact list/names of VPC endpoints for private routing; `AWS/MWAA` service metrics names; "both public and private" web server mode details; SCP condition keys; AWS Config support; IPv6 dual-stack details; log-group default retention; current prices per class; MWAA Serverless price and GA; per-Region quotas for environments.

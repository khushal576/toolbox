# AWS CLI – configuration, credentials, commands and scenarios

Short notes. Each point is a fact you can be asked about.

## A. What the AWS CLI is
- The **AWS Command Line Interface (CLI)** = one tool (`aws`) that calls **AWS service APIs** from a terminal or script. Command shape: `aws <service> <operation> [--options]`. Example: `aws s3api list-buckets`, `aws glue start-job-run --job-name x`.
- Every CLI call is a **signed API request** (SigV4), the same as the SDKs make. **IAM decides** what you can do, and **CloudTrail records** every call.
- **CLI v2** is current:
  - Bundled installer with its own Python (no pip needed).
  - **IAM Identity Center (SSO)** support, **auto-prompt**, `--output yaml`, a pager by default.
  - **Standard retry mode** by default.
  - Wizards, binary format handling (`--cli-binary-format`).
- **CLI v1** (pip install) is in maintenance. Use v2.
- The CLI is built on **botocore** (the same core as **boto3**, the Python SDK). So configuration (profiles, credentials, Regions, retries) works the same way for Python scripts.
- **AWS CloudShell** = a browser-based shell in the console with the **CLI preinstalled** and credentials of the **signed-in console user**. Region follows the console, 1 GB persistent home directory per Region, can run inside a VPC (verify). There are no keys to set up.
- CLI vs SDK vs console vs IaC:
  - CLI for ad-hoc ops, scripts, automation glue and debugging.
  - SDKs (boto3, Java, JS…) inside applications and Lambda.
  - Console for exploration.
  - **IaC** (CloudFormation/SAM/CDK) for creating infrastructure, **not** long CLI scripts.
- Exam link: skill 3.1.3 "call SDKs/APIs from code", 4.1.4 "IAM roles for CLI access", plus scripted operations in pipelines.

## B. Config and credentials files
- **`~/.aws/config`** (Windows `%UserProfile%\.aws\config`): settings per **profile**: `region`, `output`, `role_arn`, `source_profile`, `sso_session`, `retry_mode`, `max_attempts`, `cli_pager`, `s3` transfer settings, endpoint settings.
  - Profiles appear as `[profile name]`, except `[default]`.
- **`~/.aws/credentials`**: secret values per profile: `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token`. Profiles appear as `[name]` (no `profile` word).
- **`aws configure`**: interactive setup of the access key, secret, Region and output for the default (or `--profile x`) profile. `aws configure list` shows which values are in effect and **where they came from**. `aws configure get/set` reads/writes single values. `aws configure list-profiles` lists profiles.
- **Named profiles**: choose with **`--profile name`** or **`AWS_PROFILE=name`**. Use one profile per account/role/environment (`dev`, `prod-readonly`).
- Override file locations with `AWS_CONFIG_FILE` and `AWS_SHARED_CREDENTIALS_FILE`.
- **Never commit** `~/.aws/credentials` or keys to Git. Keep the files readable only by you (chmod 600).

## C. Credential and setting precedence (very testable)
- The CLI uses the **first** source that provides credentials/settings, in this order:
  1. **Command-line options** (`--profile`, `--region`, `--output`, `--endpoint-url`).
  2. **Environment variables** (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_PROFILE`, `AWS_REGION`/`AWS_DEFAULT_REGION`…).
  3. **Assume role** (a profile with `role_arn` + `source_profile`/`credential_source`).
  4. **Assume role with web identity** (`AWS_ROLE_ARN` + `AWS_WEB_IDENTITY_TOKEN_FILE`; EKS IRSA, GitHub OIDC).
  5. **IAM Identity Center (SSO)** profile (after `aws sso login`).
  6. **Credentials file** (`~/.aws/credentials`).
  7. **Custom process** (`credential_process` in config: an external program returns JSON credentials).
  8. **Config file** (keys placed in `~/.aws/config`).
  9. **Container credentials** (ECS task role; also used by CodeBuild).
  10. **EC2 instance profile** credentials from IMDS.
- **Trap**: leftover `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` env vars **override** your profile and instance role, which gives "wrong account" or `AccessDenied` surprises. `unset` them, and check with `aws configure list`.
- **Region resolution**: `--region` > `AWS_REGION` > `AWS_DEFAULT_REGION` > profile `region` (> IMDS on EC2 for some cases; verify). With no Region, the CLI errors with "You must specify a region".
- **Who am I?** `aws sts get-caller-identity` shows the account, ARN and user/role actually in use. It needs no permissions. It is the first troubleshooting step.

## D. Ways to authenticate (from best to worst)
- **On AWS compute**: use the **instance profile (EC2)**, **task role (ECS/Fargate)**, **IRSA / Pod Identity (EKS)**, the **Lambda execution role**, or the **CodeBuild service role**. **No keys at all**. Temporary credentials rotate automatically.
- **Humans**: **IAM Identity Center (SSO)**:
  - `aws configure sso` writes an `sso_session` block and profiles (account + permission set role).
  - `aws sso login --profile x` opens the browser and caches a token (session length set by Identity Center).
  - Short-lived, MFA through the identity provider, central access control across many accounts.
  - `aws sso logout` clears the cache.
- **`aws login`** (newer): sign in with your **console credentials** to get short-term CLI credentials, without access keys (verify availability and details).
- **Assume-role profiles** (switch roles):
  ```
  [profile prod-admin]
  role_arn = arn:aws:iam::222222222222:role/Admin
  source_profile = default        # or credential_source = Ec2InstanceMetadata | EcsContainer | Environment
  mfa_serial = arn:aws:iam::111111111111:mfa/me
  duration_seconds = 3600
  external_id = abc               # third-party access
  role_session_name = khushal-cli
  ```
  - The CLI calls `sts:AssumeRole` and **caches** the temporary credentials (`~/.aws/cli/cache`). It prompts for the MFA code if `mfa_serial` is set.
  - Cross-account access pattern: the target role's trust policy allows the source account/role, and the source identity has `sts:AssumeRole` on the target role.
  - Role chaining limits the session to **1 hour** max.
- **Web identity / OIDC**: CI systems (GitHub Actions, GitLab) get an OIDC token and call `AssumeRoleWithWebIdentity`. There are no stored secrets.
- **`credential_process`**: plug in external tools (IAM Roles Anywhere's `aws_signing_helper` for on-prem servers with X.509 certificates, or password vault helpers).
- **Long-term IAM user access keys** (last resort):
  - Rotate regularly (at most 2 keys per user, to allow rotation).
  - Never embed them in code, AMIs, user data or Git. Least privilege. Require MFA for sensitive calls (`aws:MultiFactorAuthPresent`).
  - `aws sts get-session-token --serial-number ... --token-code ...` gets MFA-backed temporary credentials.
- **Manual STS**: `aws sts assume-role` returns `AccessKeyId`, `SecretAccessKey`, `SessionToken`, `Expiration`. Export them as env vars (all **three**: missing `AWS_SESSION_TOKEN` gives "invalid token").

## E. Global options and output
- **`--region`**, **`--profile`**, **`--output json|yaml|yaml-stream|text|table`** (json is the default), **`--endpoint-url`** (custom/VPC endpoints, LocalStack, S3-compatible stores), **`--no-verify-ssl`** (avoid), **`--ca-bundle`**.
- **`--query`**: **JMESPath** filtering of the response, **on the client side** (after the data is downloaded).
  - `aws ec2 describe-instances --query "Reservations[].Instances[].{id:InstanceId,state:State.Name}" --output table`
  - `aws s3api list-objects-v2 --bucket b --query "Contents[?Size > \`1000000\`].Key"`
  - `--query "length(Items)"`, `sort_by(...)`, `[0]`, `[-1]`.
- **Server-side filtering**:
  - `--filters` (EC2 Name/Values), `--prefix` (S3), `--filter-expression` (DynamoDB scan; still reads all items).
  - These reduce the data sent back. **`--query` does not reduce API calls or cost**.
- **`--output text`** + `--query` is best for shell scripts (`ID=$(aws ... --query 'X' --output text)`).
- **Pagination**:
  - The CLI **auto-paginates** by default (it keeps calling until all pages are fetched).
  - **`--no-paginate`** returns only the first page.
  - **`--page-size`** sets items per API call (fewer timeouts on big lists).
  - **`--max-items`** caps the total and prints a **`NextToken`**; continue with **`--starting-token`**.
- **Pager**: CLI v2 pipes output to a pager (less). Turn it off for scripts with `--no-cli-pager`, `AWS_PAGER=""`, or `cli_pager =` in config.
- **`--dry-run`** (EC2 and some services): checks permissions without doing the action. It returns `DryRunOperation` if allowed, `UnauthorizedOperation` if not.
- **`--generate-cli-skeleton`** creates an input JSON/YAML template. **`--cli-input-json file://x.json`** / `--cli-input-yaml` runs from a file (repeatable, reviewable calls).
- **`file://`** loads parameter values from local files (text). **`fileb://`** loads binary (for example, Lambda zip, KMS ciphertext).
- **Binary payloads**: in v2, blob parameters expect **base64** by default. For raw JSON text in `aws lambda invoke --payload`, add **`--cli-binary-format raw-in-base64-out`** (or set it in config).
- **Waiters**: `aws <service> wait <condition>` polls until a state is reached or times out. Examples: `aws cloudformation wait stack-create-complete`, `aws ec2 wait instance-running`, `aws rds wait db-instance-available` (verify the Glue/Athena waiter list). They are useful in scripts in place of sleep loops.
- **`--debug`**: full request/response logs, credential provider chain, retries and endpoints. Great for troubleshooting.
- **`--cli-auto-prompt`** / `AWS_CLI_AUTO_PROMPT=on-partial`: interactive completion of commands and parameters (v2).
- **Aliases** (`~/.aws/cli/alias`): custom shortcuts, for example `whoami = sts get-caller-identity`.
- **`--cli-read-timeout`**, **`--cli-connect-timeout`**: socket timeouts (default 60 s; 0 = blocking; verify).
- **Command completion**: `aws_completer` for bash/zsh.
- **`aws <service> help`**: built-in docs for any command.

## F. Retries, endpoints and networking
- **Retry modes**:
  - **standard** (**default in CLI v2**): max_attempts 3 total (2 retries), exponential backoff up to 20 s. It retries throttling (`ThrottlingException`, `SlowDown`, `ProvisionedThroughputExceededException`…) and 500/502/503/504 errors.
  - **legacy** (v1 default): 5 total attempts (DynamoDB 10).
  - **adaptive** (experimental): standard + **client-side rate limiting** (token bucket). Useful for heavy scripts that hit throttling.
  - Set with `retry_mode` / `max_attempts` in config, or `AWS_RETRY_MODE` / `AWS_MAX_ATTEMPTS`.
- **Endpoints**:
  - `--endpoint-url`, `AWS_ENDPOINT_URL` (all services), `AWS_ENDPOINT_URL_<SERVICE>` (one service, for example `AWS_ENDPOINT_URL_S3`), or an `endpoint_url` per service in config.
  - Used for **VPC interface endpoints**, **LocalStack/local DynamoDB testing**, and S3-compatible storage.
- **FIPS endpoints**: `AWS_USE_FIPS_ENDPOINT=true` / `use_fips_endpoint`. **Dual-stack (IPv6)**: `AWS_USE_DUALSTACK_ENDPOINT`.
- **Proxy**: `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY` env vars. Corporate TLS inspection needs `AWS_CA_BUNDLE`.
- From a **private subnet** with no internet, the CLI needs **VPC endpoints** (interface endpoints for most services, a gateway endpoint for S3/DynamoDB) or a NAT gateway. With private DNS on interface endpoints, the normal hostnames resolve to the endpoint, so no `--endpoint-url` is needed.
- **Clock skew**: requests are signed with a timestamp. If the machine clock is off by more than about 5 minutes (verify), you get `SignatureDoesNotMatch` / `RequestTimeTooSkewed`. Sync time (NTP / Amazon Time Sync).

## G. S3 commands (high-level `s3` vs low-level `s3api`)
- **`aws s3`** (high-level, file-like):
  - `ls`, `cp`, `mv`, `rm`, `sync`, `mb`, `rb`, `presign`, `website`.
  - Handles **multipart upload, parallel transfers and retries automatically**.
- **`aws s3api`** (low-level): one-to-one with S3 API operations (`put-object`, `get-object`, `list-objects-v2`, `put-bucket-policy`, `put-bucket-lifecycle-configuration`, `put-object-tagging`, `head-object`, `restore-object`, `create-multipart-upload`…). Use it for bucket settings and fine control.
- **`aws s3 cp`**: copy local ↔ S3 or S3 ↔ S3. `--recursive` for folders. `--exclude`/`--include` patterns (**order matters**: later filters win; for example `--exclude "*" --include "*.parquet"`).
- **`aws s3 sync`**: copies **only new or changed** files (by size and last-modified time; `--exact-timestamps`, `--size-only` options).
  - **`--delete`** removes files in the destination that are not in the source. Dangerous: test with **`--dryrun`** first.
  - Used to deploy DAGs to MWAA, push Glue scripts, or back up folders.
- **`aws s3 mv`**: copy then delete. **`aws s3 rm --recursive`**: delete everything under a prefix. `aws s3 rb --force` deletes the bucket and its contents.
- **Upload options**:
  - `--sse aws:kms --sse-kms-key-id <key>` (or `--sse AES256`).
  - `--storage-class STANDARD_IA|INTELLIGENT_TIERING|GLACIER_IR|...`.
  - `--acl bucket-owner-full-control` (legacy, cross-account; ACLs are usually disabled now).
  - `--metadata`, `--content-type`, `--expected-size` (streams over 50 GB), `--checksum-algorithm` (CRC32/CRC32C/SHA256…).
- **Streaming**: `aws s3 cp - s3://b/k` reads from stdin. `aws s3 cp s3://b/k -` writes to stdout. Pipe with gzip/jq without temp files.
- **`aws s3 presign s3://b/k --expires-in 3600`**: a pre-signed **GET** URL. Default 3,600 s, max 7 days with SigV4. Bounded by the lifetime of the credentials that signed it, so short with role credentials.
- **Transfer tuning** (`s3` section in config):
  - **`max_concurrent_requests`** (default **10**), `max_queue_size` (1,000).
  - **`multipart_threshold`** (default **8 MB**), **`multipart_chunksize`** (default **8 MB**, minimum 5 MB).
  - `max_bandwidth`, `use_accelerate_endpoint` (bucket must have **Transfer Acceleration** on).
  - **`preferred_transfer_client = crt`** (the **AWS CRT** high-throughput client; auto-selected on supported EC2 instances) with `target_bandwidth`.
  - Raise concurrency for many small files or big bandwidth. Lower it on weak links.
- S3 limits worth knowing: a single PUT is up to 5 GB, multipart up to **50 TB per object** (verify; was 5 TB), and max 10,000 parts.
- **S3 Express One Zone** directory buckets work with `aws s3`/`s3api` (session auth is automatic).

## H. Useful data-engineering commands
- **Identity**: `aws sts get-caller-identity`.
- **Glue**:
  - `aws glue start-job-run --job-name etl --arguments '{"--run_date":"2026-10-11"}'`.
  - `aws glue get-job-run --job-name etl --run-id jr_...` (poll the state).
  - `aws glue start-crawler --name c`, `aws glue get-tables --database-name db`.
  - `aws glue batch-create-partition` / `get-partitions`.
- **Athena**:
  - `aws athena start-query-execution --query-string "..." --work-group primary --query-execution-context Database=db`.
  - Poll `get-query-execution` until `SUCCEEDED`, then `get-query-results` (paginated) or read the CSV from the S3 output location.
- **Step Functions**: `aws stepfunctions start-execution --state-machine-arn ... --input file://in.json`. `describe-execution`. `start-sync-execution` (Express workflows).
- **Lambda**:
  - `aws lambda invoke --function-name f --payload '{"k":"v"}' --cli-binary-format raw-in-base64-out out.json`.
  - `--invocation-type Event` for async. `--log-type Tail` returns the last 4 KB of logs, base64-encoded.
  - `update-function-code --zip-file fileb://f.zip`, `publish-version`, `update-alias`.
- **Kinesis**:
  - `aws kinesis put-record --stream-name s --partition-key k --data '...'` (base64 in v2 unless raw-in-base64-out).
  - `get-shard-iterator` + `get-records` to peek at data. `describe-stream-summary`.
- **Firehose**: `aws firehose put-record --delivery-stream-name d --record Data=...`.
- **DynamoDB**:
  - `get-item`, `put-item`, `query` (`--key-condition-expression`, `--expression-attribute-values`), `scan` (`--filter-expression`; still reads everything, so consumes capacity).
  - `batch-write-item`, `export-table-to-point-in-time` (to S3).
- **Redshift Data API**: `aws redshift-data execute-statement --workgroup-name wg --database dev --sql "..."` (or `--cluster-identifier` + `--secret-arn`), then `describe-statement` and `get-statement-result`. No JDBC needed.
- **CloudFormation / SAM**: `aws cloudformation deploy --template-file t.yaml --stack-name s --capabilities CAPABILITY_IAM --parameter-overrides Env=dev`. `aws cloudformation package`. `describe-stack-events`. `wait stack-update-complete`.
- **CloudWatch Logs**:
  - `aws logs tail /aws/lambda/f --follow --since 1h --filter-pattern ERROR`.
  - `aws logs start-query` (Logs Insights) + `get-query-results`.
- **Secrets / parameters**:
  - `aws secretsmanager get-secret-value --secret-id x --query SecretString --output text`.
  - `aws ssm get-parameter --name /app/x --with-decryption`.
- **EMR**: `aws emr add-steps`, `aws emr-serverless start-job-run`. **MWAA**: `aws mwaa create-cli-token` (run Airflow CLI commands).
- **Lake Formation**: `aws lakeformation grant-permissions`. **DataZone / SageMaker** CLIs also exist.
- **Decode auth errors**: `aws sts decode-authorization-message --encoded-message <msg>` turns the encoded EC2 "UnauthorizedOperation" message into readable policy details (needs `sts:DecodeAuthorizationMessage`).
- **IAM Access Analyzer policy checks**: `aws accessanalyzer validate-policy` / `check-no-new-access`, usable in CI.

## I. Scripting good practice
- Use `set -euo pipefail` in bash. Check exit codes. **The CLI returns a non-zero exit code on errors** (255 for general errors, 252/253/254 for parsing/client/service errors; verify codes).
- Prefer **waiters** over sleep loops. Use exponential backoff for your own polling.
- Use `--output text` / `--query` for values, and `jq` for complex JSON.
- Use **idempotent** patterns (check before create, use client tokens where APIs support `--client-request-token`/`--client-token`).
- Pin the CLI version in CI images to avoid behavior changes.
- Run scripts on AWS with **roles** (CodeBuild, Lambda, ECS, SSM Run Command), not with keys from laptops.
- For anything that **creates infrastructure**, use IaC instead of long CLI scripts. Keep the CLI for operations: start jobs, query state, backfills, data movement.
- `aws configure export-credentials --profile x --format env` prints the current temporary credentials as env vars for tools that can't read profiles (verify).

## J. Security
- **Least privilege per profile/role**: separate read-only and admin profiles. Use admin only when needed (SSO permission sets).
- **MFA** for privileged roles (`mfa_serial` in assume-role profiles, IAM conditions on `aws:MultiFactorAuthPresent`).
- **No long-term keys** where avoidable. If you use them, rotate them. Use **IAM Access Analyzer / credential reports** and the "last used" info to find stale keys.
- **CloudTrail** records every CLI call. The `userAgent` field shows `aws-cli/2.x ...`, the role session name shows who assumed a role, and `sourceIPAddress` shows where from. Set **`role_session_name`** to your username for traceability.
- **Credential cache files** (`~/.aws/cli/cache`, `~/.aws/sso/cache`) hold temporary tokens. Protect the home directory and log out on shared machines.
- **`--debug` output can include sensitive data** (headers, sometimes payloads). Don't paste it publicly.
- **SCPs / permission boundaries** still apply to CLI calls. The CLI has no special power.
- **CloudShell** uses console credentials. Restrict it with IAM (`cloudshell:*`) if needed.

## K. Troubleshooting (symptom → cause → fix)
- **`Unable to locate credentials`** → no profile, env vars or role found. Run `aws configure` / `aws sso login`, set `AWS_PROFILE`, or attach an instance role.
- **`You must specify a region`** → no Region set. Use `--region`, `AWS_REGION`, or `region` in the profile.
- **`ExpiredToken` / `The security token included in the request is expired`** → SSO or assumed-role credentials expired, or old env vars are lingering. Run `aws sso login` again / re-assume, and `unset AWS_SESSION_TOKEN`.
- **`InvalidClientTokenId` / `The security token is invalid`** → wrong or deleted access key, `AWS_SESSION_TOKEN` missing with temporary keys, or a key from another partition.
- **`SignatureDoesNotMatch`** → wrong secret key, or a **clock skew** on the machine. Fix keys or sync the time.
- **`AccessDenied` / `AccessDeniedException`** → the identity lacks permission, or a resource policy, SCP, permission boundary, KMS key policy or VPC endpoint policy denies it. Check `aws sts get-caller-identity` (are you who you think?), then the policies.
- **`UnauthorizedOperation` (EC2) with an encoded message** → decode it with `aws sts decode-authorization-message`.
- **Works in one terminal, fails in another** → different env vars (`AWS_PROFILE`, keys) override the profile. Check `aws configure list`.
- **Wrong account touched** → default profile or env vars point elsewhere. Always use explicit `--profile` in scripts, and confirm with `get-caller-identity`.
- **`ThrottlingException` / `Rate exceeded` / `SlowDown`** → too many calls. Use adaptive retry mode, raise `max_attempts`, add backoff, use `--page-size`, or batch APIs.
- **Command hangs from a private subnet** → no route to the service endpoint. Add a VPC endpoint or NAT, check SGs and NACLs, check proxy settings.
- **`Could not connect to the endpoint URL`** → wrong Region for the service, typo in `--endpoint-url`, service not available in that Region, or DNS/proxy issues.
- **Lambda invoke error "Invalid base64"** → CLI v2 expects base64 for blobs. Add `--cli-binary-format raw-in-base64-out`.
- **`aws s3 sync` deleted files unexpectedly** → `--delete` with wrong source/destination or filters. Always `--dryrun` first, and enable bucket versioning for recovery.
- **`--query` returns `null`** → wrong JMESPath path or capitalization (keys are case-sensitive). Inspect raw `--output json` first.
- **Script prints nothing / waits** → the pager is on in CLI v2. Set `AWS_PAGER=""` or use `--no-cli-pager`.
- **Large S3 upload is slow** → raise `max_concurrent_requests` / chunk size, use the CRT client on EC2, Transfer Acceleration for long distances, or check the instance network limits.

## L. Numbers and defaults to remember
| Item | Value |
|---|---|
| Default output | json (also yaml, yaml-stream, text, table) |
| Retry mode default | standard in CLI v2 (legacy in v1) |
| Standard max attempts | 3 total (2 retries), backoff up to 20 s |
| Legacy max attempts | 5 total (DynamoDB 10) |
| S3 max_concurrent_requests | 10 |
| S3 multipart threshold / chunk size | 8 MB / 8 MB (min 5 MB part) |
| S3 max_queue_size | 1,000 |
| Presigned URL default / max | 3,600 s / 7 days (and ≤ credential lifetime) |
| IMDS credential timeout | 1 s default, 1 attempt (configurable) |
| Role chaining session max | 1 hour |
| Access keys per IAM user | 2 |
| Credentials precedence | CLI options > env vars > assume role > web identity > SSO > credentials file > credential_process > config file > container > instance profile |
| Region precedence | `--region` > `AWS_REGION` > `AWS_DEFAULT_REGION` > profile |

## Scenarios (if → then, because)
- **If** an engineer must work in **5 AWS accounts** from the terminal without any access keys, **then** use **AWS IAM Identity Center (SSO)**, the central sign-in service for many accounts. Run **`aws configure sso`** once: it writes an `sso_session` block and one profile per account and permission set (role). Each day, **`aws sso login --profile x`** opens the browser and caches a token. **This works because** the credentials are **short-lived**, MFA comes through the identity provider, and access is controlled in one central place. `aws sso logout` clears the cached token.
- **If** a script on an **Amazon Elastic Compute Cloud (EC2)** server must call **Amazon S3** and **AWS Glue**, **then** attach an **instance profile** (an Identity and Access Management (IAM) role for the instance) and do **not** run `aws configure`. **This works because** the CLI finds the instance profile credentials from the Instance Metadata Service (IMDS) automatically, as the last step of its credential search, and these temporary credentials rotate by themselves. There are no keys to leak.
- **If** a CLI call suddenly touches the **wrong account**, **then** run **`aws sts get-caller-identity`** to see the account and identity really in use, and **`aws configure list`** to see where each value came from. **This works because** leftover environment variables such as `AWS_ACCESS_KEY_ID` come **before** the profile in the precedence order, so they silently override it. `unset` them, and use an explicit `--profile` in scripts.
- **If** you must run a command in **another account** as an admin role with **multi-factor authentication (MFA)**, **then** create an **assume-role profile** in `~/.aws/config` with **`role_arn`** (the target role), **`source_profile`** (your normal credentials) and **`mfa_serial`** (your MFA device), and call it with **`--profile`**. **This works because** the CLI calls `sts:AssumeRole`, asks for the MFA code, and **caches** the temporary credentials in `~/.aws/cli/cache`. The target role's trust policy must allow your account or role.
- **If** **GitHub Actions** must run CLI deploy commands, **then** use an **OpenID Connect (OIDC) web identity role**. **This works because** GitHub gets an OIDC token and calls `AssumeRoleWithWebIdentity` to get temporary credentials, so **no keys are stored** in the CI system.
- **If** an **on-premises server** must call AWS without long-term keys, **then** use **IAM Roles Anywhere** through **`credential_process`**, with its signing helper (`aws_signing_helper`). **This works because** `credential_process` lets an external program return credentials as JSON, and the helper gets temporary credentials using the server's **X.509 certificate**, not stored access keys.
- **If** you need only the **IDs of running instances** as plain text, **then** combine `--filters Name=instance-state-name,Values=running` with `--query "Reservations[].Instances[].InstanceId"` and `--output text`. **This works because** **`--filters`** filters on the server (less data comes back), **`--query`** picks fields on the client with JMESPath, and **text** output is easy to use in shell scripts.
- **If** listing **millions of S3 objects** times out, **then** use a smaller **`--page-size`**, narrow the list with **`--prefix`**, or use **S3 Inventory** instead of listing. **This works because** `--page-size` asks for fewer items per API call while the CLI still auto-paginates, and `--prefix` is a server-side filter that returns less data. `--query` would not help: it filters only after download.
- **If** a script must **wait until a CloudFormation stack is ready**, **then** use the waiter **`aws cloudformation wait stack-create-complete`**. **This works because** a waiter polls until the state is reached or times out, so you need no sleep loop.
- **If** you must deploy **Apache Airflow DAGs** to **Amazon Managed Workflows for Apache Airflow (MWAA)** from CI, **then** run **`aws s3 sync dags/ s3://mwaa-bucket/dags/ --delete --exclude "*.pyc"`**, and test it with **`--dryrun`** first. **This works because** `sync` copies only **new or changed** files, and **`--delete`** removes files in the bucket that are no longer in the source. That is also the danger: a wrong source or filter deletes files, so dry-run first and keep bucket versioning on for recovery.
- **If** only **new or changed** files should be uploaded to the raw zone, **then** use **`aws s3 sync`**, not `aws s3 cp --recursive`. **This works because** `sync` compares **size and last-modified time** and skips files that are already the same, while `cp --recursive` copies everything again.
- **If** uploads must use **server-side encryption with AWS Key Management Service (SSE-KMS)** and a **specific key**, **then** run **`aws s3 cp --sse aws:kms --sse-kms-key-id <key-arn>`**. **This works because** these upload options tell S3 to encrypt the object with that KMS key instead of the default.
- **If** a partner needs **temporary download access to one object**, **then** create a **pre-signed URL** with **`aws s3 presign s3://b/k --expires-in <seconds>`**. **This works because** the URL carries your signature and allows a **GET** of that object until it expires (default **3,600 s**, max **7 days**). The catch: the URL also stops working when the **credentials that signed it** expire, so sign with credentials that live at least that long (role credentials are short).
- **If** a **big upload from an EC2 instance** is slow, **then** set **`preferred_transfer_client = crt`** in the `s3` config section and/or raise **`max_concurrent_requests`** (default **10**). **This works because** the **AWS Common Runtime (CRT)** client is built for high throughput, and more parallel requests use more of the network bandwidth. Lower concurrency again on weak links.
- **If** **bulk API calls get throttled**, **then** set **`retry_mode = adaptive`** and a higher **`max_attempts`**, or switch to **batch APIs**. **This works because** **adaptive** mode adds **client-side rate limiting** on top of standard retries with backoff, so the script slows itself down, and batch APIs need fewer calls. Adaptive mode is still marked **experimental**.
- **If** an EC2 **`UnauthorizedOperation`** error returns a long **encoded message**, **then** run **`aws sts decode-authorization-message --encoded-message <msg>`**. **This works because** it turns the message into readable policy details; the caller needs the `sts:DecodeAuthorizationMessage` permission.
- **If** you must **check permissions** for launching instances **without launching** them, **then** run **`aws ec2 run-instances ... --dry-run`**. **This works because** `--dry-run` only checks permissions: it returns **`DryRunOperation`** if allowed and **`UnauthorizedOperation`** if not, and nothing is created.
- **If** you want to test against **LocalStack** or a **local DynamoDB**, **then** point the CLI at it with **`--endpoint-url http://localhost:4566`** (or the **`AWS_ENDPOINT_URL`** environment variable for all services). **This works because** the endpoint setting sends requests to that address instead of the normal AWS endpoint, with the same commands.
- **If** a **nightly backfill** must run a **Glue job per date**, **then** write a CLI loop with **`aws glue start-job-run --arguments`** (passing the date) and poll **`aws glue get-job-run`** for the state, or better, use an **AWS Step Functions Map state**. **This works because** each run gets its own date argument and polling tells you when it finishes. A Step Functions Map state runs the same per-date step as a managed workflow instead of a hand-written loop.
- **If** a quick **Amazon Athena** check must run from a terminal, **then** call **`aws athena start-query-execution`**, poll **`get-query-execution`** until it shows **`SUCCEEDED`**, then read **`get-query-results`**. **This works because** the query is only started by the first call, and the results (paginated, also saved as CSV in the S3 output location) can be read only after it succeeds.
- **If** someone needs a shell with the CLI but **cannot install anything**, **then** use **AWS CloudShell**, a browser-based shell in the console. **This works because** it has the **CLI preinstalled** and uses the credentials of the **signed-in console user**, so there are no keys to set up.
- **If** auditors ask **which human ran a CLI command** through an assumed role, **then** look in **AWS CloudTrail**, which records every CLI call, at the **role session name** and the **source IP** (`sourceIPAddress`). **This works because** the role session name shows who assumed the role, so set **`role_session_name`** to your username in the profile beforehand.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: credential/config precedence list (CLI options → env vars → assume role → web identity → IAM Identity Center → credentials file → custom process → config file → container → instance profile), environment variables (AWS_REGION over AWS_DEFAULT_REGION, endpoint vars, FIPS/dual-stack, IMDS timeout and attempts, web identity vars, pager), S3 transfer settings defaults (10 concurrent requests, 1,000 queue, 8 MB threshold and chunk size, CRT client and target bandwidth), retry modes (standard default in v2 with 3 attempts and 20 s max backoff; legacy 5 attempts, DynamoDB 10; adaptive experimental). Note: the environment variable page still calls legacy the default retry mode; the retries page says standard is the v2 default.
Not confirmed (verify): CloudShell VPC support and storage details, `aws login` command details, IMDS Region fallback, timeout defaults, the full Glue/Athena waiter list, S3 maximum object size (50 TB vs 5 TB), clock skew tolerance, CLI exit code meanings, `configure export-credentials` availability.

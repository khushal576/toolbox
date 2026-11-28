# CI/CD – 2. CodeBuild and CodePipeline

Short notes. Each point is a fact you can be asked about.

## A. AWS CodeBuild: what it is
- **CodeBuild** = fully managed **build and test** service. It runs commands in a fresh container (or VM/Lambda) per build: compile, unit test, lint, package, build Docker images, run `sam build`/`cdk synth`, run integration tests.
- No build servers to manage. Pay **per build minute** by compute type. It scales to many parallel builds (within quotas).
- Building blocks:
  - **Build project**: source, environment, service role, buildspec, artifacts, logs, VPC, cache.
  - **Build** = one run.
- Sources: CodeCommit, GitHub/GitHub Enterprise, GitLab, Bitbucket (via CodeConnections or OAuth), S3, or **no source** (CodePipeline passes the input artifact). Multiple sources are possible (primary + secondary).
- Triggers:
  - CodePipeline action.
  - **Webhooks** (push/PR/tag events with filter groups on branch, file path, actor, event type).
  - Manual / `start-build` API.
  - EventBridge schedule.
  - **GitHub Actions runner** mode (CodeBuild-hosted runners for GitHub Actions / GitLab runners; verify).

## B. Build environments and compute
- **Environment image**:
  - AWS-managed images (Amazon Linux, Ubuntu standard, Windows, ARM). They bundle runtimes, selected with `runtime-versions` in the buildspec.
  - Or a **custom Docker image** from ECR/Docker Hub.
- **Privileged mode** must be on to **build Docker images** (Docker-in-Docker).
- **Compute modes**:
  - **On-demand EC2 compute**: Small (3 GB/2 vCPU), Medium, Large, XLarge, 2XLarge, GPU, ARM. Per-minute billing (verify sizes).
  - **Lambda compute**: 1–10 GB memory, Linux x86/ARM. **Starts in seconds**, billed per second, **no Docker builds**, **max 15 minutes**, fewer features (no privileged mode; `on-failure` not supported). Good for fast lint/unit-test jobs.
  - **Reserved capacity fleets**: always-warm instances you pay for while provisioned. No queueing/cold start, and custom AMI/VPC caching (verify).
- **Timeouts**:
  - Build timeout **5 minutes to 36 hours (2,160 min)**. Default **60 minutes** (verify the default).
  - Queued timeout is separate (verify range).
- **Concurrency quotas** are per compute type and Region. New accounts start low (often 1 per type). Request increases. Error: "Cannot have more than X active builds for the account".
- **VPC builds**: attach the project to private subnets + security groups to reach RDS, Redshift, internal APIs or MSK during tests. **Internet/S3 access then needs a NAT gateway or VPC endpoints**. Up to 16 subnets and 5 security groups.
- **Caching**:
  - **S3 cache** (shared across hosts; use for dependency folders like `~/.m2`, `~/.cache/pip`).
  - **Local cache** (Docker layer, source, custom) on the build host. Best effort.
  - Cache keys with fallback keys in buildspec (newer).
- **Batch builds**: build-list, build-matrix, build-graph (dependencies), build-fanout (verify). Run many builds from one buildspec, for example test on 3 Python versions in parallel.
- **Session Manager debugging**: pause a build (`codebuild-breakpoint`) and connect interactively (verify).
- **Local testing**: CodeBuild local agent / Docker image to run buildspecs on your laptop.

## C. buildspec.yml
- YAML file at the **repo root** by default (`buildspec.yml`). You can override the name/path per project or per build. Only one buildspec per project.
- `version: 0.2` (recommended). In 0.2 **all commands run in the same shell instance**, so `cd` and exports persist between commands. In 0.1 each command ran separately.
- **`env`**:
  - `variables` = plain text. **Not for secrets**: visible in the console/API.
  - **`parameter-store`** = values from SSM Parameter Store (the role needs `ssm:GetParameters`).
  - **`secrets-manager`** = `KEY: secret-id:json-key:version-stage:version-id` (the role needs `secretsmanager:GetSecretValue`, and KMS decrypt if a CMK is used).
  - **`exported-variables`** = pass values to later CodePipeline actions (as `#{BuildVariables.VAR}`).
  - `git-credential-helper` and `shell` settings.
- Secret values from Parameter Store / Secrets Manager and AWS access key IDs are **masked in logs**, but only if printed **exactly**. A transformed value (base64, upper-case) is not masked.
- **Variable precedence**: value in the **start-build call** > **project** setting > **buildspec**.
- **`phases`** (fixed names, run in order): **`install`** (runtime-versions, install tools) → **`pre_build`** (login to ECR, install deps, run linters) → **`build`** (compile, test, package) → **`post_build`** (push images, notify, package templates).
  - **`finally`** block in a phase runs even if a command in that phase fails.
  - **`on-failure`**: `ABORT`, `CONTINUE`, `RETRY`, `RETRY-<count>`, `RETRY-<regex>` (EC2 compute only).
  - Default transitions: if `build` fails, `post_build` **still runs** (so it can clean up or report), but the build is marked failed. If `install` or `pre_build` fails, later phases are skipped (verify exact transitions).
  - `run-as` to run commands as a non-root Linux user.
- **`reports`**: test reports (JUnit XML, Cucumber, NUnit, TestNG, TRX) and **code coverage** (Cobertura, JaCoCo, Clover, SimpleCov) to **report groups**. Kept 30 days. Up to 5 report groups per project.
- **`artifacts`**: `files` (globs like `'**/*'`), `base-directory`, `discard-paths`, `exclude-paths`, `name`, `secondary-artifacts` (multiple outputs). Uploaded to S3, or passed to CodePipeline as output artifacts.
- **`cache`**: `paths` to cache, plus `key` / `fallback-keys`.
- **`batch`**: batch build configuration.
- Built-in env vars:
  - `CODEBUILD_SRC_DIR`, `CODEBUILD_BUILD_ID`, `CODEBUILD_BUILD_NUMBER`, `CODEBUILD_RESOLVED_SOURCE_VERSION` (commit ID), `CODEBUILD_WEBHOOK_TRIGGER`, `AWS_REGION`.
  - Names starting with `CODEBUILD_` are reserved.

## D. CodeBuild security and logging
- **Service role**: the IAM role CodeBuild assumes to run the build.
  - Minimum: write CloudWatch Logs, read/write the artifact bucket, decrypt with the artifact KMS key.
  - Plus whatever the build does (ECR push, `cloudformation:*` for deploy steps, `ssm:GetParameters`, `secretsmanager:GetSecretValue`, `codeartifact:GetAuthorizationToken` + `sts:GetServiceBearerToken`).
  - Least privilege matters: **build scripts run with this role's rights**, and untrusted PR code could abuse it.
- **Untrusted pull requests** (public repos / forks):
  - Don't run them with a powerful role.
  - Use webhook filters (actor account ID), a separate low-privilege project, and require approval to build PRs from untrusted contributors (newer setting; verify).
- **Logs**: CloudWatch Logs (default) and/or S3. Logs can be encrypted with KMS. Set log retention.
- **Artifacts encryption**: KMS (AWS managed or customer managed key). Cross-account artifact access needs a CMK with key policy grants.
- **VPC + endpoints** to keep build traffic private. Proxy settings for explicit proxies.
- **Build badges** show status in README (public link; turn off for private projects if not wanted).
- **Image security**: use ECR with scanning for custom images. Pin versions. Avoid `latest`.

## E. AWS CodePipeline: what it is
- **CodePipeline** = managed **continuous delivery orchestration**. It models a release process as **stages** of **actions** and moves **artifacts** between them automatically on every change.
- Structure:
  - **Pipeline** → **stages** (at least 2: the first is the **Source** stage, up to 50) → **actions** (1–50 per stage; sequential using `runOrder`, or parallel with the same `runOrder`).
  - Actions have **input and output artifacts**, stored in the pipeline's **S3 artifact store** (one per Region used).
- **Action categories and common providers**:
  - **Source**: CodeCommit, CodeConnections (GitHub, GitLab, Bitbucket), S3, ECR.
  - **Build**: CodeBuild, **Commands action** (V2: run shell commands directly without a CodeBuild project), Jenkins, ECR build and publish (verify).
  - **Test**: CodeBuild, third-party tools.
  - **Deploy**:
    - **CloudFormation** (create/update stack, change sets, StackSets), **CodeDeploy** (EC2/on-prem, Lambda, ECS blue/green).
    - **ECS** (rolling), **S3** (extract files to a bucket), Elastic Beanstalk, AppConfig, Service Catalog, Alexa.
    - **EC2 deploy action** (verify), **EKS deploy action** (verify).
  - **Approval**: **manual approval** (with optional SNS notification, review URL and comments).
  - **Invoke**: **Lambda** invoke (custom steps), **Step Functions** invoke (start a state machine, for example a data-validation workflow), Inspector scan (verify).
- **Pipeline types**:
  - **V1**: classic structure. **$1 per active pipeline per month** (free for the first 30 days; 1 free active pipeline per month).
  - **V2** (default for new pipelines; verify): adds release-safety and trigger features. Priced at **$0.002 per action execution minute** (100 free minutes per month). Manual approval and custom actions are not charged.
- **V2-only features**:
  - **Triggers with filters**: push on branches, **Git tags**, **pull request** events (opened/updated/closed), **file paths** (include/exclude globs). Max 50 triggers, 3 filters per trigger, 8 include + 8 exclude patterns.
  - **Pipeline-level variables**: pass values at **start time** (for example `ENV=prod`, a dataset date). Max 50 per pipeline.
  - **Execution modes**:
    - **SUPERSEDED** (default; a newer run replaces older waiting runs at stage boundaries).
    - **QUEUED** (runs processed one by one in order, nothing skipped).
    - **PARALLEL** (runs fully independent, for example PR/feature environments).
    - Up to 50 concurrent executions in QUEUED/PARALLEL.
  - **Stage conditions** (entry, on-success, on-failure rules):
    - For example, block entry outside a deployment window, check that a CloudWatch alarm is OK, or require a Lambda rule to pass.
    - Results: fail, **rollback**, **skip**, or retry.
  - **Stage rollback**: automatic rollback to the last successful execution's artifacts on stage failure, or manual rollback.
  - **Automatic retry** of a failed stage.
  - **Source revision overrides**: start with a specific commit, tag or S3 version.
  - **Commands action**: run simple shell commands without a CodeBuild project.

## F. CodePipeline concepts in practice
- **Change detection**: event-based (EventBridge for CodeCommit/S3/ECR, webhooks/connections for GitHub etc.) is recommended over **polling** (legacy; max 300 polling pipelines per Region).
- **Variables**:
  - **Action output variables** (namespaced; for example the source commit ID `#{SourceVariables.CommitId}`, CodeBuild exported variables, CloudFormation stack outputs) can be used in later action configurations.
  - **Pipeline-level variables** (V2).
- **Manual approval**:
  - Pauses the pipeline. Default timeout **7 days** (configurable 5 minutes to 60 days per action). After timeout the action **fails**.
  - Approvers need `codepipeline:PutApprovalResult`.
  - Not charged in V2.
- **Retry**: retry failed actions/stage without re-running the whole pipeline. **Stop execution** (stop and wait, or abandon).
- **Transitions**: disable the transition between stages to **block promotion** (for example, freeze prod) and re-enable later.
- **Execution history** retained **12 months**.
- **Artifact limits**:
  - Source artifacts up to **7 GB** from S3 and **1 GB** from CodeCommit/GitHub.
  - CloudFormation action input max **256 MB**.
  - CloudFormation `ParameterOverrides` JSON max **1 KB**.
  - Large files belong in S3, referenced by key.
- **Action timeouts**:
  - CodeBuild action up to 36 hours. CloudFormation deploy action 3 days. CodeDeploy action 5 days.
  - Lambda invoke action 24 hours, with 20-minute heartbeats via `PutJobSuccessResult` / continuation tokens.
  - Step Functions invoke 7 days. Commands action 55 minutes. Most other actions 1 hour.
- **Quotas**: 1,000 pipelines per Region (adjustable), 1,000 actions per pipeline, up to 100 parallel and 100 sequential actions in a stage, 50 tags.

## G. CloudFormation deploy actions in CodePipeline
- Action modes:
  - **`CREATE_UPDATE`**: create the stack or update it directly.
  - **`CHANGE_SET_REPLACE`**: create/replace a **change set** (no changes applied).
  - **`CHANGE_SET_EXECUTE`**: execute a change set.
  - **`DELETE_ONLY`**: delete a stack (teardown of test environments).
  - **`REPLACE_ON_FAILURE`**: delete and recreate a failed stack (good for test stacks).
- **Production pattern**: `CHANGE_SET_REPLACE` → **manual approval** (reviewers read the change set) → `CHANGE_SET_EXECUTE`.
- Inputs:
  - **TemplatePath** (`BuildArtifact::packaged.yaml`), **TemplateConfiguration** (a JSON file with `Parameters`, `Tags`, `StackPolicy` per stage), **ParameterOverrides** (JSON ≤ 1 KB; can use `Fn::GetArtifactAtt` / `Fn::GetParam`).
  - **Capabilities** (`CAPABILITY_IAM`, `CAPABILITY_NAMED_IAM`, `CAPABILITY_AUTO_EXPAND` for SAM).
  - **RoleArn** = the CloudFormation **service role** that makes the changes (passed with `iam:PassRole` by the pipeline role).
- **Output file**: stack outputs written to a JSON artifact and exposed as variables for later actions (for example the API URL for tests).
- **StackSets actions**: `CloudFormationStackSet` and `CloudFormationStackInstances` to deploy to many accounts/Regions from the pipeline.
- **SAM in pipelines**:
  - Build step runs `sam build` + `sam package` (or `aws cloudformation package`), uploading code to S3 and producing `packaged.yaml`.
  - The deploy step uses CloudFormation actions with `CAPABILITY_AUTO_EXPAND`.
  - Or `sam pipeline init` generates all of this.
- **CDK in pipelines**: CDK Pipelines (self-mutating CodePipeline), or a CodeBuild step running `cdk deploy` with bootstrap roles.

## H. Cross-Region and cross-account pipelines
- **Cross-Region actions**: set the action's `region`. CodePipeline needs an **artifact bucket in each Region** used, and copies artifacts there.
- **Cross-account deploys** (tools account → dev/test/prod accounts). Needed pieces:
  - A **customer managed KMS key** for the artifact bucket(s). Its key policy allows the target accounts' roles to decrypt. **The AWS managed key can't be shared cross-account**.
  - An **artifact bucket policy** allowing the target accounts to read.
  - A **cross-account role** in each target account that the pipeline action assumes (`RoleArn` on the action), with permission to pass the CloudFormation deploy role there.
  - A **CloudFormation service role** in the target account that does the deploy.
- Pattern: separate AWS accounts per environment (AWS Organizations), one central **tools/CI account** hosting the pipeline. Prod changes need approvals and run with least-privilege deploy roles.

## I. CI/CD patterns for data pipelines
- **Typical pipeline**:
  1. Source (Git, branch `main`, or a tag).
  2. Build/test (CodeBuild):
     - Lint and unit tests (pytest, local Spark).
     - `sam build` / `cdk synth`.
     - cfn-lint, cfn-guard / cdk-nag.
     - Package Glue scripts and wheels, upload to the S3 artifact bucket.
  3. Deploy **dev** (CloudFormation change set + execute).
  4. Integration tests (CodeBuild or a Step Functions invoke): run the Glue job/Step Functions on sample data, run data quality checks, compare row counts.
  5. Deploy **test/staging**, then **manual approval**.
  6. Deploy **prod** (change set + execute, Lambda canary with alarms).
- **Glue jobs**: the build step uploads `job.py` and dependencies (`--extra-py-files`, wheels) to versioned S3 paths. The template points the job at the new path. Glue job versions are tracked through Git + IaC. Glue **interactive sessions / Docker image** for local tests.
- **Airflow (MWAA)**: CI syncs DAGs, `requirements.txt` and plugins to the MWAA S3 bucket (`aws s3 sync dags/ s3://.../dags/`). Test DAG imports in CI (`python -c "import dag"` / `airflow dags list` in the MWAA local runner).
- **SQL / dbt**: run `dbt build` against a dev warehouse in CI. Promote to prod with tags. Redshift schema migrations with Flyway/Liquibase in a build step.
- **Step Functions**: definitions in Git (ASL JSON/YAML), deployed via SAM/CDK. Test with Step Functions Local or TestState API (verify).
- **Data quality gates**: a stage condition or test action fails the pipeline if quality checks fail, so bad logic never reaches prod.
- **Feature/PR environments**: V2 PARALLEL mode + PR triggers deploy a temporary stack per PR, then `DELETE_ONLY` when the PR closes.

## Scenarios (if → then, because)
- **If** every commit to `main` must be linted, unit-tested and packaged automatically, **then** run **AWS CodeBuild** (a managed build and test service) as the build stage of an **AWS CodePipeline** pipeline, or use a CodeBuild project started by a **webhook**. **This works because** each build runs the buildspec commands in a fresh container with no build servers to manage, and the push event starts it automatically.
- **If** a build needs to build and push a Docker image, **then** turn on **privileged mode** in the **AWS CodeBuild** project and log in to **Amazon Elastic Container Registry (ECR)** in the **`pre_build`** phase. **This works because** building Docker images inside the build container (Docker-in-Docker) needs privileged mode; without it the build fails with "Cannot connect to the Docker daemon".
- **If** unit tests must run in seconds for many small repos, **then** use **AWS CodeBuild Lambda compute**. **This works because** it **starts in seconds** and is billed per second. The limits: **no Docker builds**, **15 minutes maximum**, and fewer features (no privileged mode), so it suits fast lint and unit-test jobs.
- **If** builds wait in a queue every morning, **then** request higher **concurrent build quotas** for the compute type, or use **AWS CodeBuild reserved capacity fleets** (verify). **This works because** concurrency quotas are per compute type and Region and start low on new accounts (often 1), while reserved fleets are always-warm instances with no queueing or cold start (verify). Reserved capacity is billed for as long as it is provisioned.
- **If** integration tests must reach a private Amazon RDS database or Amazon Redshift cluster, **then** run **AWS CodeBuild in the Virtual Private Cloud (VPC)**: attach the project to private subnets and a security group. **This works because** the build then runs inside your network and can reach private resources. The catch: internet, Amazon S3 and Amazon ECR access then needs a **NAT gateway** or **VPC endpoints**. A project can use up to 16 subnets and 5 security groups.
- **If** the build needs a database password, **then** reference it in the buildspec `env` with **`secrets-manager`** (AWS Secrets Manager) or **`parameter-store`** (SSM Parameter Store), not plain `variables`. **This works because** plain `variables` are visible in the console and API, while these values are fetched at build time and **masked in logs** if printed exactly. The CodeBuild role needs `secretsmanager:GetSecretValue` or `ssm:GetParameters`.
- **If** a later pipeline stage needs a value computed in the build (a version number or image tag), **then** list it under **`exported-variables`** in the buildspec and read it later as **`#{BuildVariables.NAME}`**. **This works because** exported variables become **action output variables** that later CodePipeline action configurations can use.
- **If** a cleanup command must run even when tests fail, **then** put it in a **`finally`** block of the phase, or in **`post_build`**. **This works because** a `finally` block runs even if a command in that phase fails, and if `build` fails, `post_build` **still runs** (verify exact transitions), though the build is still marked failed.
- **If** test results and coverage must be visible for each build, **then** add a **`reports`** section to the buildspec that sends **JUnit XML** test reports and **Cobertura** coverage to **report groups**. **This works because** AWS CodeBuild reads these files and shows them per build. Reports are kept **30 days**, with up to **5 report groups** per project.
- **If** dependency installs make every build slow, **then** use an **AWS CodeBuild S3 cache** for folders like `~/.cache/pip` or `~/.m2`, with **cache keys** based on lock files. **This works because** the S3 cache is shared across build hosts, so dependencies are restored instead of downloaded every time, which also cuts build minutes and cost.
- **If** a pipeline in a **monorepo** must run only when its own folder changes, **then** use an **AWS CodePipeline V2** trigger with **file-path filters** (include/exclude globs). **This works because** the trigger checks which files changed. Limits: **3 filters per trigger** and **8 include + 8 exclude** patterns.
- **If** a release pipeline must start only on Git tags like `v*`, **then** use an **AWS CodePipeline V2** trigger with a **tag filter**. **This works because** V2 triggers can filter on **Git tags**, not just branches.
- **If** deployments must not overlap and none may be skipped, **then** use **AWS CodePipeline V2 QUEUED** execution mode. **This works because** runs are processed **one by one in order** and nothing is skipped. The default **SUPERSEDED** mode lets a newer run replace older waiting runs at stage boundaries, so some changes would never deploy alone.
- **If** each pull request (PR) should get its own test environment, **then** use **AWS CodePipeline V2 PARALLEL** mode with **PR triggers**, deploy a temporary stack per PR, and remove it with the AWS CloudFormation **`DELETE_ONLY`** action when the PR closes. **This works because** PARALLEL runs are fully independent (up to **50** concurrent executions), and PR triggers fire on opened, updated and closed events.
- **If** you want to pass `ENV=prod` or a backfill date when starting a pipeline, **then** use **AWS CodePipeline V2 pipeline-level variables**. **This works because** they take values at **start time**, and actions can read them. Limit: **50** per pipeline.
- **If** prod deploys must not happen outside a change window or while an alarm is firing, **then** add **AWS CodePipeline V2 stage entry conditions** to the prod stage. **This works because** a condition is checked before the stage starts: it can block entry outside a deployment window, check that an **Amazon CloudWatch alarm** is OK, or require an AWS Lambda rule to pass. The result can be fail, rollback, skip or retry.
- **If** a failed prod stage must go back to the last good version automatically, **then** use **AWS CodePipeline V2 stage rollback**, plus **AWS CodeDeploy** alarms for AWS Lambda and Amazon ECS deployments. **This works because** stage rollback redeploys the **last successful execution's artifacts** when the stage fails, while CodeDeploy alarms roll back traffic during the deployment itself.
- **If** prod changes must be reviewed before they are applied, **then** use three AWS CloudFormation actions: **`CHANGE_SET_REPLACE`** → **manual approval** → **`CHANGE_SET_EXECUTE`**. **This works because** a **change set** lists exactly what will change without applying anything; reviewers read it during the approval, and only then is it executed.
- **If** an AWS Serverless Application Model (SAM) template fails to deploy from the pipeline with a capabilities error (InsufficientCapabilities), **then** add **`CAPABILITY_AUTO_EXPAND`** (plus `CAPABILITY_IAM` or `CAPABILITY_NAMED_IAM`) to the AWS CloudFormation action. **This works because** SAM templates are macros that CloudFormation must expand, and creating IAM resources needs explicit permission.
- **If** a pipeline in the tools account deploys into prod and fails with **AWS Key Management Service (KMS) AccessDenied** on artifacts, **then** encrypt the artifact bucket with a **customer managed KMS key** whose key policy lets the prod account's roles decrypt, and update the **bucket policy** so prod can read. **This works because** the **AWS managed key cannot be shared across accounts**; only a customer managed key can.
- **If** the same stack must be deployed into **30 accounts** from the pipeline, **then** use the AWS CloudFormation **StackSet actions** (`CloudFormationStackSet` and `CloudFormationStackInstances`). **This works because** StackSets deploy one template to many accounts and Regions from a single action.
- **If** a custom step (call an API, validate data) is needed in the middle of a pipeline, **then** use an **AWS Lambda invoke action**, which must report job success or failure, or an **AWS Step Functions invoke action** that starts a state machine. **This works because** these actions run your own logic as a pipeline step. Lambda invoke can run up to **24 hours** with 20-minute heartbeats; Step Functions invoke up to **7 days**.
- **If** the team wants to stop promotions to prod for a while, **then** **disable the transition** into the prod stage and re-enable it later. **This works because** a disabled transition stops runs from moving into that stage, so prod is frozen without changing the pipeline.
- **If** a pipeline has 10 short actions per run and runs rarely, **then** **AWS CodePipeline V2** is likely cheaper; for frequent long runs, compare it with **V1**. **This works because** V2 costs **$0.002 per action execution minute** (100 free minutes per month, manual approval not charged), while V1 costs a flat **$1 per active pipeline per month**.
- **If** someone must approve prod but ignores the approval for a week, **then** the **manual approval** action times out after **7 days** (the default) and **fails**. Set a suitable timeout (**5 minutes to 60 days**) and send **Amazon Simple Notification Service (SNS)** notifications to approvers. **This works because** approvals are not open forever, and notifications make sure someone sees the request in time.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: CodePipeline V1 vs V2 features (parallel/queued modes, pipeline variables, stage conditions incl. skip, stage rollback, auto retry, source revision overrides, triggers with Git tags/PR/branch/file-path filters, Commands action) and pricing ($1 per active V1 pipeline; $0.002 per V2 action minute; free tiers), CodePipeline quotas (pipelines, actions, stages 2–50, actions per stage 1–50, artifact sizes, timeouts, approval 7 days / 5 min–60 days, 12-month history, trigger and variable limits, 50 concurrent executions), CodeBuild quotas (build timeout 5–2,160 minutes, concurrency per compute type, VPC subnets/SGs, reports 30 days, 5 report groups per project), buildspec reference (env sections, masking rules, precedence, phases, `finally`, `on-failure` values, reports formats, artifacts, cache keys).
Not confirmed (verify): CodeBuild default timeout 60 minutes, exact compute sizes, queued timeout range, phase transition details, batch build types list, runner mode and PR approval settings, reserved capacity features, V2 as the default type, EC2/EKS/Inspector/ECR build actions, Step Functions TestState API.

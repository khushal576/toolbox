# CI/CD – 3. CodeDeploy, security, cost, monitoring and scenarios

Short notes. Each point is a fact you can be asked about.

## A. AWS CodeDeploy: what it is
- **CodeDeploy** = managed **deployment** service that rolls out new application versions with controlled speed, health checks and **automatic rollback**.
- **Compute platforms**:
  - **EC2/On-premises**: installs a revision on servers through the **CodeDeploy agent**.
  - **AWS Lambda**: shifts traffic between Lambda **versions** using an **alias**.
  - **Amazon ECS**: blue/green between task sets behind a load balancer.
- Building blocks:
  - **Application** = a name + compute platform.
  - **Deployment group** = target set (EC2 tags, Auto Scaling groups, on-prem tags / Lambda function / ECS service) + deployment config + service role + alarms + rollback settings + load balancer.
  - **Revision** = what to deploy: zip/tar in S3 or GitHub for EC2; an AppSpec for Lambda/ECS.
- **AppSpec file** (`appspec.yml`/`.json`):
  - EC2: `files` (source → destination), `permissions`, `hooks` (scripts per lifecycle event).
  - Lambda: function name, alias, current and target version, hooks.
  - ECS: task definition, container name/port, hooks.
- **Service role**: CodeDeploy assumes it to act (managed policy `AWSCodeDeployRole`, `AWSCodeDeployRoleForLambda`, `AWSCodeDeployRoleForECS`).
- Used directly, or as a **CodePipeline deploy action**, or behind **SAM `DeploymentPreference`** / CDK `LambdaDeploymentGroup`.

## B. EC2/On-premises deployments
- Needs the **CodeDeploy agent** on each instance (install it through SSM Distributor or bake it into the AMI). The instance profile needs **S3 read** on the revision bucket.
- **On-premises servers** register with IAM user/role credentials or IAM Roles Anywhere (verify).
- **In-place deployment**: stop the app, install the new revision on the **same instances**, restart, in batches. The capacity reduction is set by the deployment config.
- **Blue/green deployment (EC2)**: provisions a **new replacement fleet** (copy of the ASG, or manually tagged instances), deploys there, **reroutes the load balancer** traffic, then terminates the old fleet after a wait (or keeps it).
- **Deployment configs (EC2)**:
  - **`CodeDeployDefault.OneAtATime`** (**default**; safest/slowest).
  - **`HalfAtATime`**.
  - **`AllAtOnce`** (fastest; succeeds if even one instance succeeds).
  - **Custom** with **minimum healthy hosts** (count or %) and optional **minimum healthy hosts per AZ** (zonal config).
- **EC2 AppSpec lifecycle hooks** (in order):
  - `ApplicationStop` → (DownloadBundle) → **`BeforeInstall`** → (Install) → **`AfterInstall`** → **`ApplicationStart`** → **`ValidateService`**.
  - With a load balancer: `BeforeBlockTraffic` / `AfterBlockTraffic` and `BeforeAllowTraffic` / `AfterAllowTraffic` around the traffic steps.
  - Hook scripts run as a chosen user, with a timeout per script (verify the max, often 3,600 s).
- **ASG integration**: CodeDeploy deploys the latest revision to **new instances launched by scale-out** automatically (via a lifecycle hook). Suspend scaling during deployments to avoid mixed versions.
- **ValidateService** is the place for smoke tests. A failed script fails the instance's deployment.

## C. Lambda and ECS deployments
- **Lambda**: always a **traffic shift** on an **alias** from the old version to the new version. No servers.
  - Configs:
    - `CodeDeployDefault.LambdaCanary10Percent5Minutes` / `10Minutes` / `15Minutes` / `30Minutes`.
    - `LambdaLinear10PercentEvery1Minute` / `2Minutes` / `3Minutes` / `10Minutes`.
    - `LambdaAllAtOnce`.
    - Custom canary/linear.
  - Hooks: **`BeforeAllowTraffic`** and **`AfterAllowTraffic`** (Lambda functions that report success/failure with `PutLifecycleEventHookExecutionStatus`).
  - SAM `DeploymentPreference` creates all of this (PreTraffic = BeforeAllowTraffic, PostTraffic = AfterAllowTraffic).
- **ECS blue/green**:
  - The new task set (green) is registered to a **second target group**. **Test traffic** can go through a test listener first. Then production traffic shifts (canary/linear/all-at-once) and the original (blue) task set is terminated after a wait.
  - Configs: `ECSLinear10PercentEvery1Minutes`, `ECSLinear10PercentEvery3Minutes`, `ECSCanary10Percent5Minutes`, `ECSCanary10Percent15Minutes`, `ECSAllAtOnce`. **With a Network Load Balancer only `ECSAllAtOnce`** is supported.
  - Hooks: `BeforeInstall`, `AfterInstall`, `AfterAllowTestTraffic`, `BeforeAllowTraffic`, `AfterAllowTraffic`.
  - Amazon ECS now also has **native blue/green deployments** without CodeDeploy (verify current recommendation).
- CodePipeline's **ECS (rolling) deploy action** uses ECS rolling updates. The **CodeDeployToECS** action does blue/green (input artifacts max 3 MB: appspec + taskdef).

## D. Rollback and health
- **Automatic rollback** triggers: **deployment fails**, or a **CloudWatch alarm** in the deployment group goes to ALARM (for example Lambda errors, 5xx on the ALB, p99 latency).
- Rollback = CodeDeploy **redeploys the last known good revision** as a new deployment (EC2), or shifts traffic back to the old version (Lambda/ECS).
- You can also **stop** a deployment and roll back manually.
- Health in EC2 deployments: per-instance lifecycle status (Pending, InProgress, Succeeded, Failed, Skipped, Unknown). Minimum healthy hosts controls when the deployment fails.
- **Deployment logs** on instances: `/opt/codedeploy-agent/deployment-root/deployment-logs/codedeploy-agent-deployments.log` (Linux). Send them to CloudWatch Logs with the agent.

## E. Security for CI/CD
- **Separate roles per service**:
  - Pipeline role (orchestrates; needs `iam:PassRole` for the roles it hands over).
  - CodeBuild service role (build commands).
  - CloudFormation deploy role (creates resources).
  - CodeDeploy service role.
  - Each has least privilege.
- **Build commands run with the CodeBuild role**. Anyone who can change the buildspec or code in a trusted branch can use that role. Protect branches, restrict who can edit pipeline/build definitions, and keep deploy rights in the **deploy role**, not the build role.
- **Cross-account**:
  - The tools account pipeline assumes **deploy roles in target accounts**.
  - Artifacts encrypted with a **customer managed KMS key** shared to those accounts.
  - Bucket policies limited to those accounts.
  - Prod deploy roles trust only the pipeline role.
- **Secrets**:
  - Never in Git, buildspec `variables`, or pipeline variables.
  - Use **Secrets Manager / Parameter Store** references in CodeBuild, dynamic references in CloudFormation, and **CodeConnections** instead of tokens.
- **Supply chain**:
  - Pin dependencies (lock files), use **CodeArtifact** (upstream control, origin controls), and scan images (**ECR + Inspector**).
  - Sign code (**AWS Signer** for Lambda code signing; container image signing with Notation/Signer; verify).
  - Generate SBOMs (Inspector SBOM export; verify).
- **Approval gates**: manual approvals restricted by IAM (`codepipeline:PutApprovalResult` on specific actions). Use stage conditions for automated gates.
- **Policy as code in CI**: cfn-lint, cfn-guard, cdk-nag, IAM Access Analyzer **policy validation / custom policy checks** (`check-no-new-access`) on templates before deploy.
- **Encryption**:
  - Artifact buckets (SSE-KMS), CodeBuild logs (KMS), CodeCommit repos (KMS, AWS managed or customer managed key), CodeArtifact domains (KMS).
  - Enforce TLS (`aws:SecureTransport`) on artifact buckets.
- **Audit**: CloudTrail logs all CodePipeline/CodeBuild/CodeDeploy/CodeCommit API calls (who started, approved or changed a pipeline). AWS Config tracks project/pipeline configuration (rules like `codebuild-project-envvar-awscred-check`, `codebuild-project-source-repo-url-check`).
- **Notifications** (AWS CodeStar Notifications / "Developer Tools notifications"): pipeline, build, deployment and repository events → **SNS** or **Amazon Q Developer in chat applications** (formerly AWS Chatbot) for Slack/Teams.

## F. Cost
- **CodePipeline**:
  - **V1**: **$1 per active pipeline per month**. Free for the first 30 days. 1 free active pipeline/month. Inactive pipelines (no change that month) are free.
  - **V2**: **$0.002 per action execution minute** (rounded up per action). **100 free minutes/month**. Manual approval and custom actions not charged.
  - Plus S3 artifact storage, KMS requests, and the services called.
- **CodeBuild**: per **build minute** by compute type and OS (Linux small is the cheapest; ARM cheaper than x86; GPU most expensive). Lambda compute per second.
  - Free tier: **100 build minutes/month** on general1.small (verify current tier).
  - Reserved capacity is billed while provisioned.
  - Plus CloudWatch Logs, S3 and data transfer.
- **CodeDeploy**: **free** for EC2, Lambda and ECS deployments. **On-premises** instances cost about **$0.02 per instance update** (verify).
- **CodeCommit**: first 5 active users free, then about $1 per user per month, with storage and Git request allowances (verify current pricing after GA return).
- **CodeArtifact**: per GB stored per month + per request + data transfer out.
- **Cost tips**:
  - Lambda compute or small instances for quick builds. Caching to cut minutes.
  - Avoid polling sources. Delete idle V1 pipelines.
  - Use V2 path filters so unrelated pipelines don't run.
  - Tear down PR/test stacks automatically (`DELETE_ONLY`).
  - Set log retention.

## G. Monitoring and notifications
- **EventBridge events**:
  - CodePipeline: **pipeline execution**, stage execution and action execution **state changes** (STARTED, SUCCEEDED, FAILED, SUPERSEDED, STOPPED).
  - CodeBuild: **build state change**, build phase change.
  - CodeDeploy: **deployment state change**, instance state change.
  - CodeCommit: repository state change, PR events.
  - Route them to SNS (email/SMS), Lambda (auto-ticket, Slack), Step Functions, or the CloudWatch Logs.
- **Developer Tools notifications** (notification rules) give simple setup per resource to SNS or Amazon Q Developer in chat applications.
- **CloudWatch metrics**:
  - CodeBuild: `Builds`, `SucceededBuilds`, `FailedBuilds`, `Duration`, `QueuedDuration`, CPU/memory utilization (verify).
  - CodePipeline execution metrics (verify which are emitted).
  - Alarm on failed builds or long queues.
- **Logs**: CodeBuild → CloudWatch Logs/S3. CodeDeploy agent logs on instances. CloudFormation stack events for deploy failures.
- **Dashboards**: pipeline execution history (12 months), build history (1 year), deployment history. DORA-style metrics (deploy frequency, lead time, change failure rate, MTTR) can be computed from EventBridge events (verify built-in support).
- **CloudTrail**: who triggered, approved, retried or changed pipelines and builds.

## H. Troubleshooting (symptom → cause → fix)
- **Pipeline does not start on push** → wrong branch/filters in V2 triggers, CodeConnections connection not **Available**, polling disabled with no event rule, or (CodeCommit/S3) the EventBridge rule/CloudTrail data events are missing.
- **Source action fails "insufficient permissions" for GitHub** → the pipeline role lacks `codeconnections:UseConnection`, or the GitHub App lacks access to that repo.
- **CodeBuild "AccessDenied" during build** → the CodeBuild service role lacks the permission (S3 artifact, ECR, SSM, Secrets Manager, KMS decrypt). Add least-privilege statements.
- **CodeBuild can't reach the internet/S3 in VPC mode** → private subnets without NAT or VPC endpoints. Add a NAT gateway or S3/ECR/logs endpoints.
- **"Cannot have more than X active builds"** → concurrency quota per compute type. Request an increase or use reserved capacity.
- **Docker build fails "Cannot connect to the Docker daemon"** → privileged mode is off (or Lambda compute, which doesn't support Docker).
- **Build passes locally but fails in CodeBuild** → a different runtime version (pin `runtime-versions`), missing environment variables, or architecture (ARM vs x86) differences. Test with the CodeBuild local agent.
- **Secret shows in logs** → it was transformed or printed from a plain variable. Store it exactly as used in Secrets Manager/Parameter Store, and never echo secrets.
- **Cross-account deploy fails with KMS/S3 AccessDenied** → the artifact bucket uses the AWS managed key (not shareable) or the CMK key policy / bucket policy lacks the target account role.
- **CloudFormation action fails with InsufficientCapabilities** → add `CAPABILITY_IAM` / `CAPABILITY_NAMED_IAM` / `CAPABILITY_AUTO_EXPAND`.
- **CloudFormation action "iam:PassRole not authorized"** → the pipeline (or cross-account) role can't pass the CloudFormation service role. Add `iam:PassRole` for that role ARN.
- **Artifact too large** → over the CloudFormation 256 MB input or source limits. Move big files to S3 and reference them.
- **Manual approval expired** → the 7-day default timeout. Re-run the stage, set an appropriate timeout and notifications.
- **CodeDeploy EC2 deployment stuck "Pending" / instances skipped** → the agent isn't running/installed, the instance profile can't read the S3 revision, tags don't match the deployment group, or there's no outbound access to CodeDeploy endpoints.
- **CodeDeploy hook script timeout** → the script hangs (waiting for input, long download). Fix the script, raise the hook timeout, check agent logs.
- **Deployment rolled back automatically** → an alarm fired or a hook/ValidateService failed. Check alarm history and hook logs.
- **Lambda canary never shifts** → the PreTraffic hook did not report status to CodeDeploy (missing `PutLifecycleEventHookExecutionStatus` or permissions).
- **ECS blue/green with NLB fails using canary config** → NLB supports only `ECSAllAtOnce`.
- **Old V1 pipeline costs money but runs rarely** → it's billed only in months with activity. Delete unused ones, or migrate to V2 if per-minute pricing is cheaper.

## I. Limits and numbers to remember
| Item | Value |
|---|---|
| Pipelines per Region | 1,000 (adjustable) |
| Polling pipelines per Region | 300 (fixed) |
| Stages per pipeline | 2–50 |
| Actions per stage | 1–50 |
| Actions per pipeline | 1,000 |
| Parallel / sequential actions in a stage | 100 / 100 |
| Concurrent executions (QUEUED/PARALLEL) | 50 |
| Source artifact size | 7 GB (S3), 1 GB (CodeCommit/GitHub) |
| CloudFormation action input artifact | 256 MB; ParameterOverrides ≤ 1 KB |
| CodeDeployToECS input artifact | 3 MB |
| Manual approval timeout | 7 days default (5 min – 60 days) |
| CodeBuild action timeout | 36 hours |
| CloudFormation deploy action timeout | 3 days |
| CodeDeploy action timeout | 5 days |
| Lambda invoke action | 24 hours (20-minute heartbeat) |
| Step Functions invoke action | 7 days |
| Commands action build timeout | 55 minutes |
| Pipeline execution history | 12 months |
| V2 triggers | 50 per pipeline; 3 filters per trigger; 8 include + 8 exclude patterns |
| Pipeline-level variables (V2) | 50 per pipeline |
| CodeBuild build timeout | 5 minutes – 36 hours |
| CodeBuild build history | 1 year |
| CodeBuild projects per Region | 5,000 (adjustable) |
| CodeBuild report retention | 30 days; 5 report groups per project |
| CodeBuild VPC config | 16 subnets, 5 security groups |
| CodeBuild Lambda compute | ≤ 15 minutes, no Docker |
| CodePipeline V1 price | $1 per active pipeline/month |
| CodePipeline V2 price | $0.002 per action minute (100 free/month) |
| CodeDeploy EC2/Lambda/ECS | Free |

## J. Final scenario set (if → then, because)
- If a data team wants every merge to `main` to test and deploy a SAM-based pipeline to dev, then prod after approval → CodePipeline: Source (CodeConnections) → CodeBuild (tests + `sam build/package`) → CloudFormation deploy dev → integration tests → manual approval → change set + execute in prod.
- If the prod deploy must show what will change before it happens → `CHANGE_SET_REPLACE` → approval → `CHANGE_SET_EXECUTE`.
- If Lambda releases must be canary with automatic rollback on errors → CodeDeploy Lambda canary (via SAM `DeploymentPreference`) + CloudWatch alarms.
- If an EC2 web/ETL fleet must update with at least 75% capacity always healthy → CodeDeploy in-place with a custom config (minimum healthy hosts 75%).
- If an EC2 app needs zero-downtime release with instant switch-back → CodeDeploy **blue/green** with the load balancer, keeping the original fleet for a while.
- If deployments must stop automatically when 5xx errors rise → alarms on the deployment group + automatic rollback on alarm.
- If smoke tests must run after install on each server → `ValidateService` hook script.
- If new instances launched by Auto Scaling must get the current version → CodeDeploy ASG integration (deployment group targets the ASG).
- If a pipeline in a tools account must deploy to separate prod and dev accounts → cross-account roles + customer managed KMS key for artifacts + bucket policy + CloudFormation deploy roles in each account.
- If secrets must be used during builds without being visible → Secrets Manager/Parameter Store in the buildspec `env`, plus CloudWatch Logs masking.
- If the team must be told in Slack when a pipeline fails → notification rule or EventBridge rule → Amazon Q Developer in chat applications (or SNS → Lambda).
- If auditors ask who approved last week's prod deploy → CloudTrail `PutApprovalResult` events + pipeline execution history.
- If GitHub Actions is the CI of choice but must deploy to AWS securely → OIDC federation to an IAM role (no stored keys), then `sam deploy`/`cdk deploy`/CloudFormation.
- If builds are slow because dependencies download each time → CodeBuild S3 cache with lock-file-based keys, or CodeArtifact as a nearby package mirror.
- If on-prem servers must also receive deployments → CodeDeploy on-premises instances (registered with the agent).
- If the cheapest option is needed for many short pipeline runs → V2 pipelines (per action minute) with Lambda-compute CodeBuild steps.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: CodeDeploy predefined deployment configurations for EC2 (OneAtATime default, HalfAtATime, AllAtOnce, minimum healthy hosts, zonal config), Lambda (canary 5/10/15/30, linear 1/2/3/10, all-at-once) and ECS (linear 1/3, canary 5/15, all-at-once; NLB only all-at-once); CodePipeline pricing (V1 and V2, free tiers, excluded action types); CodePipeline and CodeBuild quotas; buildspec masking and precedence rules.
Not confirmed (verify): IAM Roles Anywhere for on-prem registration, hook script max timeout, ECS native blue/green recommendation, code signing/SBOM tooling details, CodeBuild free tier and metric names, CodeCommit and CodeDeploy on-prem pricing, CodePipeline metrics and DORA metric support.

# CI/CD on AWS – 5. CodeDeploy AppSpec, lifecycle hooks and deployment patterns

Short notes. Each point is a fact you can be asked about. (File 3 has the CodeDeploy overview, rollback, security and cost; this file goes deep on the AppSpec file and hooks.)

## A. The AppSpec file
- **`appspec.yml` / `appspec.json`** describes **what to deploy and which scripts or validation functions to run**.
- **Location**: **root of the application revision** (bundle). For EC2/on-premises the file name must be exactly **`appspec.yml`** (or `.json`) at the root.
- **Sections depend on the compute platform**:
  - **EC2/On-premises**: `version`, `os` (linux/windows), **`files`** (source → destination copy rules), **`permissions`** (owner/group/mode), **`hooks`** (scripts).
  - **AWS Lambda**: `version`, **`Resources`** (function name, alias, current version, target version), **`Hooks`** (Lambda validation functions).
  - **Amazon ECS**: `version`, **`Resources`** (task definition, container name and port, optional platform version, network configuration, capacity provider strategy), **`Hooks`** (Lambda validation functions).
- **Revision** = bundle with AppSpec + app files (zip/tar/tgz) in **S3** or a **GitHub** commit (EC2/on-premises). **Lambda/ECS** revisions are the AppSpec in S3/inline.
- **The AppSpec used for `ApplicationStop` and for rollback scripts comes from the PREVIOUS successfully deployed revision**, not the new one (a classic trap).

## B. EC2/on-premises lifecycle events and hooks
- **In-place order**: `ApplicationStop` → `DownloadBundle` → `BeforeInstall` → `Install` → `AfterInstall` → `ApplicationStart` → `ValidateService`. With a **load balancer** in the deployment group, **six traffic hooks** also run: `BeforeBlockTraffic` → `BlockTraffic` → `AfterBlockTraffic` (deregister) at the start and `BeforeAllowTraffic` → `AllowTraffic` → `AfterAllowTraffic` (register) at the end.
- **Reserved (cannot run your scripts)**: **`DownloadBundle`, `Install`, `BlockTraffic`, `AllowTraffic`** (plus Start/End). You influence `Install` through the **`files`** section.
- **What each scriptable hook is for**:
  - **`ApplicationStop`**: stop the running app gracefully; runs **before** the new revision is downloaded; uses the **previous revision's** AppSpec and scripts; **does not run on the very first deployment** to an instance (no previous AppSpec).
  - **`BeforeInstall`**: pre-install tasks (backup, decrypt files, install dependencies).
  - **`AfterInstall`**: configure the app, set file permissions, run migrations.
  - **`ApplicationStart`**: start/restart services.
  - **`ValidateService`**: verify the deployment (health check, smoke test); **last event**.
  - **`BeforeBlockTraffic` / `AfterBlockTraffic`**: work before/after deregistering from the LB (drain, flush).
  - **`BeforeAllowTraffic` / `AfterAllowTraffic`**: work before/after registering with the LB (warm up, final check).
- **Availability by scenario**:
  - **In-place** (and its rollback): all events, with traffic hooks only if an LB is configured.
  - **Blue/green, original instances**: only the **block-traffic** hooks (`BeforeBlockTraffic`, `BlockTraffic`, `AfterBlockTraffic`).
  - **Blue/green, replacement instances**: the install/start/validate events and **allow-traffic** hooks (`ApplicationStop`, `DownloadBundle`, `BeforeInstall`, `Install`, `AfterInstall`, `ApplicationStart`, `ValidateService`, `BeforeAllowTraffic`, `AllowTraffic`, `AfterAllowTraffic`).
  - **Blue/green rollback**: original instances run `BeforeAllowTraffic`/`AllowTraffic`/`AfterAllowTraffic`; replacement instances run the block-traffic hooks.
  - **Auto Scaling launch deployment**: install/start/validate events plus allow-traffic hooks. **Auto Scaling termination deployment**: `ApplicationStop` and block-traffic hooks (use for graceful scale-in).
- **Hook entry structure**:
  - `location` (**required**; path **relative to the bundle root**), `timeout` (seconds; **default 3,600 = max**), `runas` (user to run as; **Amazon Linux and Ubuntu only**; **no password support**).
  - **Several scripts per event**; **total timeout per event ≤ 3,600 s** (1 hour). A script exceeding its timeout **fails the deployment on that instance**.
  - A script **fails if it exits non-zero**; make scripts **idempotent** and set `set -e`.
- **Environment variables available to hook scripts**: `APPLICATION_NAME`, `DEPLOYMENT_ID`, `DEPLOYMENT_GROUP_NAME`, `DEPLOYMENT_GROUP_ID`, `LIFECYCLE_EVENT`; plus **`BUNDLE_BUCKET`, `BUNDLE_KEY`, `BUNDLE_VERSION`, `BUNDLE_ETAG`** for S3 bundles and **`BUNDLE_COMMIT`** for GitHub bundles. Use them to branch by environment (for example **Staging vs Production** config).
- **Files in hook scripts**: prefer **absolute paths**. Archive location: `<root>/<deployment-group-id>/<deployment-id>/deployment-archive` (Linux root `/opt/codedeploy-agent/deployment-root`, Windows `%ProgramData%\Amazon\CodeDeploy`). **Relative paths depend on the agent working directory** (`/` for systemd on rpm Linux, `/opt/codedeploy-agent` for init.d/Ubuntu, `C:\Windows\System32` on Windows).
- **Agent facts**: the **CodeDeploy agent** must be installed and running on EC2/on-prem instances (not needed for Lambda/ECS); it polls CodeDeploy; the instance profile needs **S3 read** access to the bundle bucket; keep the agent updated (SSM association can auto-update).
- **Troubleshoot** `ApplicationStop` / `BeforeBlockTraffic` / `AfterBlockTraffic` failures by checking the **previous revision's** scripts and `*_last_successful_install` file (in `/opt/codedeploy-agent/deployment-root/deployment-instructions`).

## C. Lambda deployments (alias traffic shifting)
- **Hooks**: only **`BeforeAllowTraffic`** and **`AfterAllowTraffic`**. Each is **one Lambda function name**; **runs once per deployment**.
- **Flow**: CodeDeploy shifts traffic on a **Lambda alias** from the **old version to the new version** using a **configuration**:
  - **Canary**: shift **X% first**, wait N minutes, then the rest (for example `Canary10Percent5Minutes`, `Canary10Percent10Minutes`, `Canary10Percent15Minutes`, `Canary10Percent30Minutes`).
  - **Linear**: shift **X% every N minutes** (for example `Linear10PercentEvery1Minute`, `Every2Minutes`, `Every3Minutes`, `Every10Minutes`).
  - **All-at-once** (`AllAtOnce`): move 100% immediately.
- **Validation hook contract**: the hook function **receives `DeploymentId` and `LifecycleEventHookExecutionId`** and must call **`codedeploy:PutLifecycleEventHookExecutionStatus`** with `Succeeded` or `Failed`. **No callback within 1 hour = failed deployment**.
- **Rollback**: automatic when a **hook returns `Failed`**, when a **CloudWatch alarm** (attached to the deployment group) fires during traffic shifting, or manually. Traffic returns to the old version (alias repoint).
- **SAM/CloudFormation**: SAM **`DeploymentPreference`** (`Type`, `Alarms`, `Hooks: PreTraffic/PostTraffic`) creates the CodeDeploy app/group, role and alias wiring for you.
- **Trap**: the **hook Lambda role** needs `codedeploy:PutLifecycleEventHookExecutionStatus`; the **CodeDeploy service role** needs permission to **invoke** the hook functions (managed policy `AWSCodeDeployRoleForLambda`).

## D. ECS deployments (blue/green with ALB/NLB)
- **Blue/green only** (for ECS, CodeDeploy does **blue/green**; ECS also has its own **rolling** and newer **built-in blue/green** deployment types **(verify)**).
- **Steps**: create **replacement task set** → attach it to the **second target group** → optional **test listener** (test traffic) → **reroute production traffic** to the replacement → **terminate the original task set** after a wait time.
- **Hooks (all are Lambda functions)**: `BeforeInstall` (before the replacement task set exists; **no rollback possible at this point**), `AfterInstall`, **`AfterAllowTestTraffic`** (run integration tests against the test listener), `BeforeAllowTraffic`, `AfterAllowTraffic`. **Hook results at AfterInstall onward can trigger rollback.**
- **Traffic shifting**: **Canary** (for example `ECSCanary10Percent5Minutes`, `ECSCanary10Percent15Minutes`), **Linear** (`ECSLinear10PercentEvery1Minutes`, `ECSLinear10PercentEvery3Minutes`), **AllAtOnce**.
- **AppSpec `Resources`** needs **TaskDefinition ARN**, **LoadBalancerInfo** (container name/port), optional **PlatformVersion**, **NetworkConfiguration**, **CapacityProviderStrategy**.
- **Requires**: a **load balancer with two target groups** and (optionally) a **test listener**; **CodeDeploy service role** (`AWSCodeDeployRoleForECS`).
- **Rollback**: failed hook, alarm, or manual stop. **Termination wait time** (0 min to 2 days) keeps the old task set for quick rollback.
- **CodePipeline integration**: ECS deploy action **CodeDeployToECS** with `appspec.yaml` and `taskdef.json` artifacts (**placeholder `<IMAGE1_NAME>` replaced by the build output image**).

## E. Deployment configurations (EC2/on-premises)
- **In-place** configs: **`CodeDeployDefault.AllAtOnce`**, **`OneAtATime`**, **`HalfAtATime`**, or **custom** (minimum healthy hosts as number or percent).
- **Blue/green** (EC2): provision a **new Auto Scaling group** (copy), deploy, reroute LB traffic, wait, **terminate or keep** the original instances.
- **Minimum healthy hosts**: a deployment **fails** if too few instances stay healthy; **OneAtATime** is safest, slowest.
- **Deployment groups** target **EC2 tags**, **Auto Scaling groups**, or **on-premises tags**; one application can have **many deployment groups** (staging/prod).
- **Rollbacks**: **automatic on deployment failure or CloudWatch alarm**; rollback **redeploys the last known good revision** as a **new deployment** (new deployment ID); **instances that failed** can be left for debugging.
- **Auto Scaling interaction**: CodeDeploy hooks into ASG **launch/terminate lifecycle hooks** so **new instances get the latest successful revision**; if a deployment is running when a scale-out happens, you may get **two revisions** (outdated instances): use **blue/green** or ensure the last revision is deployed (CodeDeploy redeploys to fix) **(verify behavior)**.

## F. Deployment strategy comparison
| Strategy | Downtime | Rollback speed | Cost | Best for |
|---|---|---|---|---|
| In-place (all at once) | Yes | Slow (redeploy) | Lowest | Dev/test |
| In-place rolling (OneAtATime/Half) | Low (capacity drops) | Medium | Low | Small fleets |
| Blue/green (EC2/ECS) | **None** | **Fast** (flip back) | **Double capacity briefly** | Production web/API |
| Canary / Linear (Lambda/ECS) | None | Fast | Low | Risk-controlled releases |
- **Which platforms support what**: **in-place** → **EC2/on-premises only**; **canary/linear traffic shifting** → **Lambda and ECS**; **blue/green** → **EC2, ECS (and Lambda via aliases)**.
- **Data stores/ETL**: for **Glue jobs/Lambda/Step Functions** use **CloudFormation/CDK/SAM** stack deploys (with **Lambda alias canaries** where useful); for **EC2/ECS data services** use CodeDeploy; **schema changes** need backward-compatible (**expand/contract**) migrations because rollbacks do not undo data changes.

## G. Triggers, alarms and notifications
- **Deployment group alarms**: attach up to **10 CloudWatch alarms**; if any enters **ALARM** during the deployment, CodeDeploy **stops and rolls back** (if enabled).
- **Notifications**: **SNS triggers** (deployment/instance events) or **notification rules** (CodeStar Notifications) to SNS/Slack/Teams.
- **EventBridge**: **`CodeDeploy Deployment State-change Notification`** and **`Instance State-change Notification`** events.
- **CloudTrail** for API calls; **CodeDeploy agent logs** at `/var/log/aws/codedeploy-agent/` and deployment logs in `/opt/codedeploy-agent/deployment-root/deployment-logs/codedeploy-agent-deployments.log`.
- **Deployment lifecycle events per instance** visible in the console (**Succeeded, Failed, Skipped**); **failed script output** is shown (last 4 KB) and in the log files.

## H. Security and IAM
- **CodeDeploy service role** (trust `codedeploy.amazonaws.com`): managed policies **`AWSCodeDeployRole`** (EC2/on-premises, ASG, SNS, CloudWatch alarms, ELB), **`AWSCodeDeployRoleForLambda`**, **`AWSCodeDeployRoleForECS`** (and limited variants).
- **EC2 instance profile**: S3 read on the revision bucket, plus **SSM** if managed by Systems Manager.
- **On-premises instances**: register with an **IAM user/ARN**, or use **IAM Roles Anywhere** **(verify)**; install the agent.
- **Least privilege** on who can **create deployments** (`codedeploy:CreateDeployment`) and **change deployment groups/configs**.
- **Encrypt** revision buckets (SSE-KMS; add KMS permission to the instance role).
- **Hook scripts run as root by default** (the agent runs as root): review them like production code.
- **Never put secrets in the bundle**; fetch at runtime from **Secrets Manager/Parameter Store**.

## I. Troubleshooting (symptom → cause → fix)
- **`ApplicationStop` fails** → the **previous** revision's script is broken → fix and redeploy; temporarily set deployment group option to **ignore ApplicationStop failures** (an allowed setting) **(verify option name)**.
- **`DownloadBundle` "UnknownError: not opened for reading"** → agent can't read bundle (S3 permission, disk, corrupt revision) → check instance role, disk space.
- **Hook timed out** → script slower than `timeout` (max 1 h per event) → raise timeout, optimize, background long work.
- **`ValidateService` fails** → app not healthy or health check URL wrong → check app logs, retry with longer startup wait.
- **Lambda/ECS deployment hangs 1 hour then fails** → hook function never called **`PutLifecycleEventHookExecutionStatus`** → fix function permissions/code.
- **Deployment skipped instances** → tags don't match, instance not running the agent, or **instance health too low** for min healthy hosts.
- **Traffic not shifting (ECS)** → listener/target group wiring or `TaskDefinition` mismatch → check AppSpec `LoadBalancerInfo` and listener rules.
- **Unexpected rollback** → CloudWatch alarm fired or a hook returned Failed → check alarm history and hook logs.
- **Agent not responding** → service stopped/old version/no network to CodeDeploy endpoint → restart agent, VPC endpoints (`codedeploy`, `codedeploy-commands-secure`), proxy settings.

## J. Scenarios: "If X → Y, because Z"
- **If** you must stop the app gracefully before its files are replaced, **then** use the **`ApplicationStop`** hook in the AWS CodeDeploy AppSpec file. **This works because** it runs **before** the new revision is downloaded and installed. The trap: it uses the **previous** revision's AppSpec and script, so a broken old script fails the new deployment.
- **If** the first deployment to a new instance skips `ApplicationStop`, **then** this is **expected**. **This works because** `ApplicationStop` uses the previous revision's AppSpec, and on the very first deployment there is no previous AppSpec.
- **If** you need to check the app before users are sent to it, **then** use the **`ValidateService`** hook (in-place) or the **`BeforeAllowTraffic`** hook (with a load balancer). **This works because** both run **before** the instance is registered with the load balancer (the AllowTraffic step), so a failed check stops that instance from getting traffic.
- **If** you need zero downtime on Amazon EC2, **then** use **AWS CodeDeploy blue/green with Elastic Load Balancing (ELB)**, or in-place with a load balancer and **`OneAtATime`**. **This works because** traffic moves only to healthy instances. Blue/green has **no downtime** and fast rollback but briefly needs **double capacity**; in-place rolling only lowers capacity a little while each instance updates.
- **If** AWS Lambda releases must reach **10%** of users first with automatic rollback, **then** use an **AWS CodeDeploy canary** config (`Canary10Percent5Minutes`) with a **pre-traffic hook** and **Amazon CloudWatch alarms**, or let AWS Serverless Application Model (SAM) **`DeploymentPreference`** set it up. **This works because** CodeDeploy shifts traffic on the Lambda **alias** gradually: 10% first, then the rest after 5 minutes. If the hook returns Failed or an alarm fires, traffic goes back to the old version.
- **If** an Amazon ECS release needs integration tests before real users see it, **then** use an **`AfterAllowTestTraffic`** Lambda hook that tests through the **test listener**. **This works because** in AWS CodeDeploy blue/green, test traffic reaches the replacement task set **before** production traffic is rerouted, and a failed hook result can trigger rollback.
- **If** a deployment fails with no response from a validation AWS Lambda function, **then** make the hook call **`PutLifecycleEventHookExecutionStatus`** with Succeeded or Failed, and give its role that permission. **This works because** AWS CodeDeploy waits up to **1 hour** for this callback and then fails the deployment.
- **If** config differs by environment, **then** branch on the **`DEPLOYMENT_GROUP_NAME`** environment variable in the hook script (for example Staging vs Production). **This works because** AWS CodeDeploy sets this variable for each deployment.
- **If** a hook script takes longer than **1 hour**, **then** **split the work** or run it **asynchronously** (in the background). **This works because** the total timeout per lifecycle event is **3,600 seconds**, a hard limit; a script that exceeds it fails the deployment on that instance.
- **If** a database schema change must ship with code, **then** use **backward-compatible expand/contract migrations**. **This works because** an AWS CodeDeploy rollback redeploys the old **code** but does **not undo data** changes, so the old code must still work with the new schema.

Verified from AWS docs on 2026-11-01 (AppSpec "hooks" section reference for ECS, Lambda and EC2/on-premises: hook lists, availability table, timeout/runas, environment variables, 1-hour callback rule). Deployment configuration names, IAM policy names, traffic-shifting config names, Auto Scaling interaction details and the troubleshooting items beyond the hooks page come from earlier knowledge and were not re-fetched.
Unconfirmed (verify): ECS and Lambda canary/linear configuration names; managed policy names; ECS built-in deployment types; Auto Scaling interaction edge cases; the "ignore ApplicationStop failure" option name; on-premises IAM Roles Anywhere support; log file paths; alarm limit per group.

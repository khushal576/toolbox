# CloudFormation, CDK and SAM – 3. CDK, security, operations and scenarios

Short notes. Each point is a fact you can be asked about.

## A. What AWS CDK is
- **AWS Cloud Development Kit (CDK)** = an open-source framework to define infrastructure in **real programming languages**: TypeScript/JavaScript, Python, Java, C#/.NET, Go.
- CDK code **synthesizes** (`cdk synth`) into **CloudFormation templates** plus **assets** (Lambda code, Docker images, files). CloudFormation then deploys them. So stacks, rollback, limits and DeletionPolicy all still apply.
- Current version is **CDK v2**: one library, `aws-cdk-lib`, plus `constructs`. **CDK v1 reached end of support on 1 June 2023**.
- Pick CDK when:
  - You want loops, conditions, functions, classes, type checking and IDE help.
  - You want to reuse **constructs** across teams.
  - You have large or complex apps, or want unit tests for infrastructure.
- Trade-offs: more abstraction (harder to see the final template, so read `cdk diff`/`synth`), a language toolchain to maintain, and generated names and IDs.

## B. Core concepts
- **App** → contains one or more **Stacks** → each contains **Constructs** → which make CloudFormation resources. This is the **construct tree**.
- **Construct levels**:
  - **L1** (`Cfn*` classes, for example `CfnBucket`): **one-to-one** with a CloudFormation resource. No defaults or helpers. You set every property. Generated from the CloudFormation spec, so new resources show up quickly.
  - **L2** (for example `s3.Bucket`, `lambda.Function`): **curated** resources with **safe defaults** and helper methods, like `bucket.grantRead(fn)`, `queue.grantSendMessages(fn)`, `table.grantReadWriteData(fn)`, `fn.addEventSource(...)`, `bucket.addLifecycleRule(...)`.
  - **L3** (patterns, for example `ecs_patterns.ApplicationLoadBalancedFargateService`): several resources wired together for a common architecture.
- **`grant*` methods** write **least-privilege IAM** automatically: resource-scoped policies on the role, plus key policies for KMS where needed. This is a big reason to use L2s.
- **Environment** = account + Region for a stack. Set it explicitly (`env`) for production, or leave it environment-agnostic (some lookups need a concrete env).
- **Context and lookups**: `Vpc.fromLookup`, `HostedZone.fromLookup`, SSM `valueFromLookup` read real values at synth time and cache them in **`cdk.context.json`**. **Commit that file** so builds are deterministic.
- **Assets**: local files/folders (Lambda code, Glue scripts) and Docker images are packaged by CDK and uploaded to the **bootstrap S3 bucket / ECR repo** during deploy. Use `aws_s3_deployment.BucketDeployment` to copy files into your own buckets.
- **Removal policy**: `removalPolicy: RemovalPolicy.RETAIN | DESTROY | SNAPSHOT` sets DeletionPolicy and UpdateReplacePolicy.
  - L2 stateful resources (S3 bucket, DynamoDB table, RDS…) default to **RETAIN** (verify per resource).
  - `autoDeleteObjects: true` on an S3 bucket adds a custom resource that empties it on delete (dev only).
- **Aspects**: visitors that walk the whole construct tree to check or change things, for example "every bucket must be encrypted" or "add tags". **cdk-nag** uses aspects to check against rule packs (AWS Solutions, HIPAA, NIST).
- **Escape hatches**:
  - `node.defaultChild` to reach the underlying L1.
  - `addPropertyOverride` to set any raw CloudFormation property an L2 doesn't expose.
- **Tags**: `Tags.of(scope).add('team', 'data')` tags all taggable resources below a scope.
- **Stack outputs**: `CfnOutput`. **Cross-stack references** inside one CDK app are made automatically as exports/imports when one stack uses another's resource (watch the export lock-in, section F).
- **Construct Hub** (constructs.dev): community and partner construct libraries.

## C. CDK CLI and bootstrapping
- **`cdk init app --language python`**: new project.
- **`cdk bootstrap aws://ACCOUNT/REGION`**:
  - Deploys the **`CDKToolkit`** stack in **each account + Region** you will deploy to.
  - It creates an **S3 bucket** (assets), an **ECR repository** (images) and **IAM roles**: deploy role, file-publishing role, image-publishing role, lookup role and the **CloudFormation execution role**.
  - Needed **once per environment** before the first deploy.
  - **`--trust ACCOUNT`** lets a pipeline/tools account deploy into this account (cross-account CI/CD).
  - `--cloudformation-execution-policies` limits what the CloudFormation execution role can do (default is AdministratorAccess; tighten it in enterprises).
- **`cdk synth`**: produce the CloudFormation template (in `cdk.out/`). Good for review, cfn-lint/cfn-guard checks, and `sam local` testing.
- **`cdk diff`**: compare code with the deployed stack. Shows resource and IAM/security changes.
- **`cdk deploy`**:
  - Publishes assets and deploys via a change set.
  - Asks for approval on broadening IAM/security changes (`--require-approval`).
  - `--all` for all stacks, `--express` for express mode.
- **`cdk watch`** / **`cdk deploy --hotswap`**:
  - Fast dev loop. For supported resources (Lambda code, Step Functions definitions, ECS images) it **calls service APIs directly, skipping CloudFormation**, which causes drift.
  - Dev only. Compare with CloudFormation express mode, which still goes through CloudFormation.
- **`cdk destroy`**: delete stacks (retained resources stay).
- **`cdk import`**: bring existing resources into a CDK stack. **`cdk migrate`**: convert a CloudFormation template, a deployed stack or **IaC generator** scan results into a new CDK app.
- **`cdk doctor`**, **`cdk ls`**, **`cdk context`**, **`cdk notices`** (verify current list), **`cdk drift`** (newer; verify), **`cdk refactor`** (move resources between stacks while keeping them; preview; verify).
- **CDK Pipelines** (`pipelines.CodePipeline` construct):
  - A **self-mutating** CodePipeline: on each commit it rebuilds itself, synthesizes, publishes assets and deploys **stages** (dev → test → prod, many accounts/Regions).
  - Supports manual approvals and pre/post test steps.
  - Needs target accounts bootstrapped with `--trust` for the pipeline account.

## D. CDK for data engineering (typical L2s)
- `s3.Bucket` (encryption `KMS`, `blockPublicAccess`, `versioned`, `lifecycleRules`, `enforceSSL`, event notifications to Lambda/SQS/SNS).
- `lambda.Function` / `lambda_python_alpha.PythonFunction` (bundles requirements) / `NodejsFunction` (esbuild), with `aws_lambda_event_sources` (`SqsEventSource`, `KinesisEventSource`, `DynamoEventSource`, `S3EventSource`).
- `glue` (L1 `CfnJob`, `CfnCrawler`, `CfnDatabase`, and alpha L2 `glue_alpha.Job`/`Database`/`Table`; verify maturity), plus `aws_s3_assets.Asset` to upload Glue scripts.
- `stepfunctions` + `stepfunctions_tasks` (`LambdaInvoke`, `GlueStartJobRun`, `AthenaStartQueryExecution`, `EmrServerless…`, `CallAwsService`): define workflows in code with `.next()` chaining. Integration patterns: `RUN_JOB` (`.sync`) and `WAIT_FOR_TASK_TOKEN`.
- `events.Rule` / `scheduler` (EventBridge Scheduler) for schedules and S3/Glue state-change triggers.
- `kinesis.Stream`, `kinesisfirehose` (`DeliveryStream` with S3 destination), `msk` (alpha), `redshift` (alpha) / `redshiftserverless` L1, `athena.CfnWorkGroup`, `lakeformation` L1 resources.
- `kms.Key` (with `enableKeyRotation`), `iam.Role`, `secretsmanager.Secret` (`generateSecretString`), `ssm.StringParameter`.
- `cloudwatch.Alarm` from metrics like `fn.metricErrors()`, `queue.metricApproximateAgeOfOldestMessage()`, plus `cloudwatch_actions.SnsAction`.
- **Alpha modules** (`@aws-cdk/aws-xxx-alpha`) are experimental, and their APIs can change. Note this for production use.

## E. Choosing between the tools
- **CloudFormation**:
  - Pure declarative, the base of everything, needs no toolchain.
  - Required knowledge for StackSets, Hooks, drift, change sets.
- **SAM**:
  - Serverless shorthand, **local Lambda testing**, `sam sync`, built-in **gradual Lambda deployments**, policy templates/connectors.
  - Best for Lambda/API/Step Functions apps.
- **CDK**:
  - Programming languages, reusable constructs, `grant*` least privilege, unit tests.
  - Best for large, mixed infrastructure and platform teams.
- **Combining**:
  - **SAM CLI can locally test CDK apps** (`sam local invoke -t cdk.out/Stack.template.json`).
  - CDK can include an existing template (`CfnInclude`).
  - SAM templates can include plain CloudFormation.
- **Terraform**: multi-cloud, its own state file (S3 + DynamoDB locking), large provider ecosystem. Not AWS-native. SAM CLI can test Terraform-built Lambdas.
- Exam wording:
  - "serverless application + local testing + simple template" → **SAM**.
  - "define infrastructure using Python/TypeScript code" → **CDK**.
  - "deploy the same template to many accounts/Regions" → **CloudFormation StackSets**.
  - "repeatable deployment of data pipelines" → any IaC, usually **CloudFormation/CDK**.

## F. Security for IaC
- **Least-privilege deploy path**:
  - Humans/pipelines get CloudFormation permissions plus **`iam:PassRole`** for a **CloudFormation service role** (or the CDK CloudFormation execution role).
  - The service role does the actual resource changes.
  - Limit the service role with permissions boundaries / SCPs.
- **IAM capabilities**: templates that create IAM need `CAPABILITY_IAM` / `CAPABILITY_NAMED_IAM`. SAM/macros need `CAPABILITY_AUTO_EXPAND`. Review IAM changes (`cdk diff` security section, change set details).
- **Secrets**:
  - Never put secrets in templates, parameters, `cdk.context.json` or Git.
  - Use **dynamic references** (`{{resolve:secretsmanager:...}}`, `ssm-secure`), let Secrets Manager **generate** secrets (`GenerateSecretString`), RDS `ManageMasterUserPassword`, or CDK `secretsmanager.Secret` + `SecretValue.secretsManager()`.
  - `NoEcho` only masks display.
- **Encryption by default in code**: KMS keys with rotation, bucket encryption, `enforceSSL`, encrypted queues/topics/streams/logs. Enforce with cdk-nag, cfn-guard, Hooks, or Config rules.
- **Policy as code**:
  - **cfn-lint** (syntax/best practice), **cfn-guard** (custom rules), **cdk-nag** (CDK aspects), **CloudFormation Hooks** (block non-compliant resources at deploy).
  - Control Tower proactive controls. AWS Config for detective checks after deploy.
- **Stack protection**: termination protection, stack policies, `DeletionPolicy`/`UpdateReplacePolicy` (RETAIN/SNAPSHOT) on stateful resources.
- **SCPs** and **permissions boundaries** to stop IaC from creating disallowed resources (for example public buckets or wrong Regions), even when the template asks for them.
- **Audit**:
  - **CloudTrail** records CloudFormation API calls (`CreateStack`, `UpdateStack`, `ExecuteChangeSet`) **and** the resource API calls made by CloudFormation. The calls are made by the service role, with the `invokedBy` field `cloudformation.amazonaws.com`.
  - Stack events give per-resource history. **AWS Config** tracks configuration, and **drift detection** finds manual changes.
- **CDK bootstrap roles** are powerful. Restrict who can assume them, and tighten `--cloudformation-execution-policies` for production accounts.
- **Cross-account deploys**: the pipeline account assumes deploy roles in target accounts (CDK `--trust`, SAM `pipeline bootstrap` roles, StackSets execution roles). KMS keys for artifact buckets must be shared to target accounts.

## G. CI/CD with IaC
- Typical flow:
  - Source (CodeCommit is closed to new customers; use GitHub/GitLab/Bitbucket via **CodeConnections**; verify) → **build** (CodeBuild: `sam build`/`cdk synth`, unit tests, cfn-lint/cfn-guard/cdk-nag).
  - → **deploy dev** (CloudFormation deploy action or `sam deploy`/`cdk deploy`) → integration tests → **manual approval** → **deploy prod** (change set create + execute, canary for Lambda).
- **CodePipeline CloudFormation actions**: `CREATE_UPDATE`, `CHANGE_SET_REPLACE` + `CHANGE_SET_EXECUTE` (review step in between), `DELETE_ONLY`, `REPLACE_ON_FAILURE`. Template configuration files hold per-stage parameters.
- **SAM**: `sam pipeline init` creates a ready pipeline. **CDK**: CDK Pipelines (self-mutating). **CloudFormation**: Git sync for simple Git-driven stacks.
- **Multi-account / multi-Region**: separate stages per account (dev/test/prod accounts in AWS Organizations), StackSets for baselines.
- **Infrastructure and app code together** in one repo is common for serverless data pipelines. Version everything (templates, Glue scripts, Lambda code, Step Functions definitions).
- **Testing IaC**:
  - CDK unit tests with **assertions** (`Template.fromStack(stack).hasResourceProperties(...)`) and snapshot tests.
  - `sam validate --lint`, cfn-lint, cfn-guard.
  - `sam local` for function behavior. Integration tests in a dev account.
- **Rollback strategy**: CloudFormation rollback on failure, rollback triggers on alarms, CodeDeploy canary rollback for Lambda, git revert + redeploy.

## H. Cost
- **CloudFormation**: no charge for AWS resource types and custom resources. Charges apply per handler operation for **registry third-party / private resource types and hooks** (verify current pricing).
- **SAM** and **CDK**: free, open source. You pay for:
  - the S3 bucket and ECR repo storing artifacts (bootstrap bucket, SAM managed bucket);
  - CodeBuild/CodePipeline minutes;
  - CodeDeploy (free for Lambda deployments; verify);
  - and, of course, the resources created.
- IaC lowers cost by making it easy to **tear down dev stacks** (`sam delete`, `cdk destroy`), tag everything for cost allocation, and enforce right-sized defaults.
- Watch for **retained** resources (RETAIN policies, `Retain` buckets, snapshots) that keep costing money after a stack is deleted.
- Clean up old **asset** objects in the CDK bootstrap bucket/ECR repo (lifecycle rules, `cdk gc` garbage collection; verify) and old Lambda versions.

## I. Monitoring and operations
- **Stack events** (console, `describe-stack-events`, `sam deploy` output) show progress and the **first failure reason**. Read the **earliest** `*_FAILED` event, not the cascade after it.
- **EventBridge** gets CloudFormation **stack status change**, resource status and **drift detection** events. Route them to SNS/Slack/Lambda for deployment notifications.
- **Drift detection** on a schedule (Config rule or EventBridge Scheduler + Lambda) to catch manual changes.
- **Stack notifications** (SNS topic per stack, `--notification-arns`) for older setups.
- **CloudTrail** for who deployed what, and **CodePipeline/CodeBuild** logs for pipeline runs.
- For applications deployed with SAM: `sam logs --tail`, `sam traces`, and CloudWatch alarms in the template.

## J. Troubleshooting (symptom → cause → fix)
- **`ROLLBACK_COMPLETE` after first create** → the first create failed. Read the first failure event, fix it, **delete the stack** and create it again (it can't be updated).
- **`UPDATE_ROLLBACK_FAILED`** → a resource changed or deleted outside CloudFormation, a dependency is missing, or permissions are missing. Fix it, then **ContinueUpdateRollback** (skip resources if needed).
- **`DELETE_FAILED` on S3 bucket** → bucket not empty (or versioned objects remain). Empty it, use a custom resource / CDK `autoDeleteObjects`, or `Retain`.
- **`DELETE_FAILED` on a security group or ENI** → still used by Lambda Hyperplane ENIs or other resources. Wait for Lambda to release the ENIs (up to ~20 minutes) and retry.
- **"Export X cannot be deleted as it is in use by Y"** → another stack imports it. Remove the import first (or move to SSM parameters). In CDK, two-step deploy: keep the export with `exportValue` until consumers change.
- **"Resource already exists" / "bucket name already taken"** → a custom physical name clashes, or a retained resource from an old stack. Use generated names, or **import** the existing resource.
- **"Circular dependency between resources"** → two resources reference each other (for example, an SG rule referencing both SGs, or a Lambda permission plus a bucket notification). Split into separate resources (`AWS::EC2::SecurityGroupIngress`) or break the reference.
- **`InsufficientCapabilitiesException`** → add `CAPABILITY_IAM` / `CAPABILITY_NAMED_IAM` / `CAPABILITY_AUTO_EXPAND`.
- **"Template format error" / unresolved resource dependencies** → YAML indentation, wrong `!Ref` target, or a condition referencing a missing parameter. Run `cfn-lint` / `sam validate`.
- **Template too large** → over 51,200 bytes inline. Upload to S3 (1 MB limit; SAM/CDK do this automatically), or split into nested stacks.
- **Over 500 resources** → split stacks (CDK makes this easy with multiple stacks or `NestedStack`).
- **Custom resource hangs for an hour** → the Lambda never sent a response (crash, timeout, VPC without internet to the S3 response URL). Fix the code, always respond (also on Delete), set `ServiceTimeout`.
- **CDK: "This stack uses assets, so the toolkit stack must be deployed"** / `SSM parameter /cdk-bootstrap/... not found` → run `cdk bootstrap` for that account/Region (and with `--trust` for cross-account).
- **CDK: unexpected resource replacement** → a construct ID or logical ID changed (renamed or moved construct). Keep IDs stable, use `overrideLogicalId`, or `cdk refactor` (verify).
- **SAM: `Unable to import module`** after deploy → dependencies not built for the Lambda platform/arch. Use `sam build --use-container` and check `Architectures`.
- **SAM: S3 event fails "bucket must be in the same template"** → SAM `S3` events only work for buckets defined in the same template. For external buckets, use EventBridge notifications or configure the notification separately.
- **Deploy is very slow** → waiting for stabilization (CloudFront, RDS). Use express mode in dev, split stacks, and avoid replacing heavy resources.
- **Drift found after hotfix in console** → update the template to match (or revert), then redeploy. Stop manual changes with SCPs/permissions.
- **StackSet operations failing in some accounts** → missing execution role (self-managed), target account not in OU, Region not enabled, or failure tolerance exceeded. Check stack instance status reasons.

## K. Limits and numbers to remember
| Item | Value |
|---|---|
| Resources per template | 500 |
| Parameters / Outputs / Mappings | 200 each |
| Template body inline / from S3 | 51,200 bytes / 1 MB |
| Template description | 1,024 bytes |
| Parameter value | 4,096 bytes |
| Stacks per account (Region) | 2,000 (adjustable) |
| Stack name | 128 characters |
| Resources per nested-stack operation | 2,500 |
| Dynamic references per template | 60 |
| cfn-signal / custom resource response data | 4,096 bytes |
| StackSets per admin account | 1,000 |
| Stack instances per StackSet | 100,000 |
| Concurrent StackSet instance operations per Region | 10,000 |
| Hooks per account / per resource | 100 / 100 |
| IaC generator | 500 resources per template; scan valid 30 days; 100,000 resources per scan |
| Custom resource default wait | up to 1 hour unless `ServiceTimeout` set (verify) |
| Rollback trigger monitoring period | up to 180 minutes (verify) |
| SAM transform | `AWS::Serverless-2016-10-31` |
| SAM canary types | 10% then rest after 5/10/15/30 min |
| SAM linear types | 10% every 1/2/3/10 min |
| CDK bootstrap stack | `CDKToolkit`, once per account + Region |
| CDK v1 | End of support 1 June 2023 |

## L. Final scenario set (if → then, because)
- If a data team needs repeatable deployment of a full pipeline (S3, Glue, Step Functions, Lambda, IAM) in 3 accounts → IaC (CloudFormation/SAM/CDK) deployed by a CI/CD pipeline per account, because manual setup drifts and can't be reviewed.
- If the team writes Python and wants reusable infrastructure components with built-in least privilege → AWS CDK (Python) with L2 constructs and `grant*` methods.
- If the team builds Lambda-based pipelines and wants to test functions locally before deploy → AWS SAM (`sam local invoke` / `start-api`).
- If an org must deploy a baseline (CloudTrail, Config, KMS key, logging bucket) to every current and future account → CloudFormation StackSets with service-managed permissions and auto-deployment.
- If production changes must be reviewed before applying → change sets (CodePipeline `CHANGE_SET_REPLACE` → approval → `CHANGE_SET_EXECUTE`), or `cdk diff` in the pipeline.
- If deployers must not have broad IAM rights → CloudFormation service role (or the CDK execution role) + `iam:PassRole`, plus permissions boundaries.
- If a template must never contain the DB password → dynamic reference to Secrets Manager, or a generated secret.
- If every bucket must be encrypted and non-public before it is created → cfn-guard / cdk-nag in CI plus a CloudFormation Hook in FAIL mode, plus an SCP as a backstop.
- If a stateful table must survive accidental stack deletion and replacements → `DeletionPolicy: Retain` + `UpdateReplacePolicy: Retain` (CDK `RemovalPolicy.RETAIN`) + termination protection.
- If someone edited a Glue job in the console → drift detection shows it. Update code and redeploy, and restrict console edits.
- If existing hand-built resources must move into CDK → IaC generator scan → `cdk migrate` (or `cdk import`).
- If a pipeline must deploy CDK stacks into dev/test/prod accounts → CDK Pipelines, with target accounts bootstrapped using `--trust` for the tools account.
- If developers want very fast cloud feedback on Lambda code changes → `sam sync --watch` or `cdk watch` (hotswap) in dev; CloudFormation express mode for template changes.
- If new Lambda code must be released gradually with automatic rollback → SAM `AutoPublishAlias` + `DeploymentPreference` canary + alarms (CDK: `LambdaDeploymentGroup`).
- If a template exceeds 500 resources → nested stacks (or multiple CDK stacks).
- If one network stack's subnet IDs are needed by many teams' stacks → exports + `Fn::ImportValue`, or SSM parameters for looser coupling.
- If cross-stack exports block an update ("export in use") → change consumers first, or switch to SSM parameters.
- If a stack is stuck in `UPDATE_ROLLBACK_FAILED` → fix the root cause, then ContinueUpdateRollback with skipped resources if needed.
- If an S3 bucket blocks stack deletion → empty it first (custom resource/`autoDeleteObjects` in dev), or retain it.
- If you need to audit who changed infrastructure and how → CloudTrail (CloudFormation calls + resource calls via the service role) + AWS Config history + stack events.
- If the question asks which tool turns short serverless YAML into CloudFormation → AWS SAM (the `AWS::Serverless-2016-10-31` transform).
- If the question asks which tool synthesizes CloudFormation from TypeScript/Python → AWS CDK (`cdk synth`).

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: CDK v2 status and v1 end of support, bootstrapping (CDKToolkit stack, S3 bucket, ECR repo, IAM roles, per environment), construct levels L1/L2/L3 and Construct Hub, express mode vs CDK hotswap comparison, IaC generator with `cdk migrate`, CloudFormation quotas, Hooks options, dynamic references, stack failure options, SAM gradual deployment types.
Not confirmed (verify): L2 default removal policies per resource, glue/msk/redshift alpha module maturity, `cdk drift` / `cdk refactor` / `cdk gc` / `cdk notices` availability, CodeCommit availability for new customers, CodeDeploy pricing for Lambda, CloudFormation registry/hook handler pricing, custom resource default wait time, rollback trigger monitoring maximum.

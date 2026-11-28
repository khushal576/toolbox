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
- **If** a data team needs a repeatable deployment of a full pipeline (Amazon S3, AWS Glue, AWS Step Functions, AWS Lambda, Identity and Access Management (IAM)) in **3 accounts**, **then** define it as **infrastructure as code (IaC)** with AWS CloudFormation, AWS Serverless Application Model (SAM) or AWS Cloud Development Kit (CDK), deployed by a **CI/CD pipeline** with a stage per account. **This works because** every account gets the same reviewed template, while manual setup drifts and cannot be reviewed.
- **If** the team writes Python and wants reusable infrastructure components with built-in least privilege, **then** use **AWS CDK in Python** with **L2 constructs** and **`grant*` methods** (for example `bucket.grantRead(fn)`). **This works because** L2 constructs have safe defaults, and `grant*` writes resource-scoped IAM policies automatically. Constructs can be shared across teams.
- **If** the team builds Lambda-based pipelines and wants to test functions locally before deploy, **then** use **AWS SAM** with **`sam local invoke`** or **`sam local start-api`**. **This works because** SAM CLI runs functions in a local Docker container that mimics Lambda, and can run a local API Gateway.
- **If** an organization must deploy a baseline (AWS CloudTrail, AWS Config, an AWS Key Management Service (KMS) key, a logging bucket) to every current and future account, **then** use **CloudFormation StackSets** with **service-managed permissions** and **automatic deployment**. **This works because** a StackSet deploys one template to many accounts × Regions, and automatic deployment adds it to **new accounts** that join the target organizational unit (OU).
- **If** production changes must be reviewed before applying, **then** use **change sets**: in AWS CodePipeline, **`CHANGE_SET_REPLACE`** → **manual approval** → **`CHANGE_SET_EXECUTE`**; for CDK, run **`cdk diff`** in the pipeline. **This works because** a change set previews every add, modify, remove and **replacement**, and nothing changes until it is executed.
- **If** deployers must not have broad IAM rights, **then** use a **CloudFormation service role** (or the **CDK CloudFormation execution role**) plus **`iam:PassRole`** for deployers, and limit the role with **permissions boundaries**. **This works because** the role does the actual resource changes, so people and pipelines need only CloudFormation permissions.
- **If** a template must never contain the database password, **then** use a **dynamic reference** to **AWS Secrets Manager** (`{{resolve:secretsmanager:...}}`), or let Secrets Manager **generate** it (`GenerateSecretString`). **This works because** the value is resolved at deploy time and never stored in the template, parameters or Git. `NoEcho` only masks display.
- **If** every bucket must be encrypted and non-public before it is created, **then** check with **cfn-guard** or **cdk-nag** in CI, block with a **CloudFormation Hook** in **FAIL** mode, and add a **service control policy (SCP)** as a backstop. **This works because** CI catches problems early, the Hook blocks non-compliant resources at deploy, and the SCP stops them even if a template asks for them.
- **If** a stateful table must survive accidental stack deletion and replacements, **then** set **`DeletionPolicy: Retain`** and **`UpdateReplacePolicy: Retain`** (in CDK, **`RemovalPolicy.RETAIN`**) and turn on **termination protection**. **This works because** `DeletionPolicy` covers delete, `UpdateReplacePolicy` covers replacement, and termination protection blocks stack deletion.
- **If** someone edited a Glue job in the console, **then** **drift detection** will show it; update the code to match (or revert) and redeploy, and restrict console edits (for example with SCPs). **This works because** drift detection compares real settings with the template, but it does **not** fix drift itself.
- **If** existing hand-built resources must move into CDK, **then** scan them with the **IaC generator** and convert with **`cdk migrate`**, or bring them into an existing stack with **`cdk import`**. **This works because** `cdk migrate` turns a template, a deployed stack or IaC generator scan results into a new CDK app without re-creating the resources.
- **If** a pipeline must deploy CDK stacks into dev, test and prod accounts, **then** use **CDK Pipelines** (`pipelines.CodePipeline`), with each target account bootstrapped using **`--trust`** for the tools account. **This works because** the pipeline is **self-mutating** and deploys stages across accounts, and `--trust` lets the tools account deploy into the targets.
- **If** developers want very fast cloud feedback on Lambda code changes, **then** use **`sam sync --watch`** or **`cdk watch`** (hotswap) in dev, and **CloudFormation express mode** for template changes. **This works because** sync and hotswap call service APIs directly, skipping CloudFormation, which causes drift (dev only). Express mode still goes through CloudFormation but does not wait for resources to stabilize.
- **If** new Lambda code must be released gradually with automatic rollback, **then** use SAM **`AutoPublishAlias`** + **`DeploymentPreference`** canary + **alarms** (in CDK, the **`LambdaDeploymentGroup`** construct). **This works because** AWS CodeDeploy shifts traffic on the alias in steps and rolls back if an Amazon CloudWatch alarm fires.
- **If** a template exceeds **500 resources**, **then** split it into **nested stacks** (or several CDK stacks / `NestedStack`). **This works because** 500 resources per template is a hard limit.
- **If** one network stack's subnet IDs are needed by many teams' stacks, **then** use **exports** with **`Fn::ImportValue`**, or **AWS Systems Manager (SSM) parameters** for looser coupling. **This works because** exports share values across stacks in one account and Region, while SSM parameters avoid the export lock-in.
- **If** cross-stack exports block an update ("export in use"), **then** change the consuming stacks first, or switch to **SSM parameters**; in CDK, keep the export with **`exportValue`** until consumers change. **This works because** an export cannot be changed or deleted while any stack still imports it.
- **If** a stack is stuck in **`UPDATE_ROLLBACK_FAILED`**, **then** fix the root cause (a resource changed outside CloudFormation, a missing dependency, or missing permissions), then run **ContinueUpdateRollback**, skipping resources if needed. **This works because** the rollback can only finish once the blocker is gone or skipped.
- **If** an S3 bucket blocks stack deletion, **then** empty it first (a custom resource, or CDK **`autoDeleteObjects`** in dev), or retain it. **This works because** a bucket with objects (including versioned objects) cannot be deleted, so the stack ends in `DELETE_FAILED`.
- **If** you need to audit who changed infrastructure and how, **then** use **CloudTrail** (CloudFormation API calls plus the resource calls made by the service role, marked `invokedBy` `cloudformation.amazonaws.com`), **AWS Config** history and **stack events**. **This works because** together they show who deployed, what each resource call was, and how configuration changed over time.
- **If** the question asks which tool turns short serverless YAML into CloudFormation, **then** the answer is **AWS SAM**. **This works because** the **`AWS::Serverless-2016-10-31`** transform expands SAM resources into normal CloudFormation.
- **If** the question asks which tool synthesizes CloudFormation from TypeScript or Python, **then** the answer is **AWS CDK**. **This works because** **`cdk synth`** turns CDK code into CloudFormation templates plus assets.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: CDK v2 status and v1 end of support, bootstrapping (CDKToolkit stack, S3 bucket, ECR repo, IAM roles, per environment), construct levels L1/L2/L3 and Construct Hub, express mode vs CDK hotswap comparison, IaC generator with `cdk migrate`, CloudFormation quotas, Hooks options, dynamic references, stack failure options, SAM gradual deployment types.
Not confirmed (verify): L2 default removal policies per resource, glue/msk/redshift alpha module maturity, `cdk drift` / `cdk refactor` / `cdk gc` / `cdk notices` availability, CodeCommit availability for new customers, CodeDeploy pricing for Lambda, CloudFormation registry/hook handler pricing, custom resource default wait time, rollback trigger monitoring maximum.

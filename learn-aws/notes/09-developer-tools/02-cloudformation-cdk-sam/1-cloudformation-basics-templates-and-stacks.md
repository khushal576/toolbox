# CloudFormation, CDK and SAM – 1. CloudFormation basics, templates and stacks

Short notes. Each point is a fact you can be asked about.

## A. What CloudFormation is
- AWS CloudFormation = **infrastructure as code (IaC)**. You describe AWS resources in a **template** (YAML or JSON), and CloudFormation creates, updates and deletes them as one unit called a **stack**.
- **Declarative**: you say *what* you want. CloudFormation works out the order (dependencies) and the API calls.
- Why IaC:
  - The same environment every time (dev, test, prod).
  - Changes reviewed in Git.
  - Rollback on failure.
  - No "click-ops" drift.
  - Easy to rebuild after disaster.
  - Easy to copy to new accounts and Regions.
- **SAM** and **CDK** both end up as CloudFormation:
  - SAM = shorthand YAML that a **transform** expands.
  - CDK = real code that **synthesizes** a template.
  - So CloudFormation rules (stacks, rollback, limits, deletion policies) apply to all three.
- CloudFormation is **free** for AWS resource types (`AWS::*`) and custom resources. You pay for the resources it creates. Third-party/registry resource handler operations have a small charge (verify).
- Regional service: a stack lives in one Region and one account. **StackSets** reach many accounts and Regions.
- Alternatives: Terraform (multi-cloud, HCL, state file), Pulumi. The exam focuses on CloudFormation, SAM and CDK.

## B. Template anatomy
- `AWSTemplateFormatVersion: '2010-09-09'` (optional; the only valid value).
- `Description`: free text, up to 1,024 bytes.
- `Metadata`: extra info. For example `AWS::CloudFormation::Interface` (console parameter grouping) and `AWS::CloudFormation::Init` (cfn-init config).
- `Parameters`: inputs at deploy time:
  - Types: `String`, `Number`, `List<Number>`, `CommaDelimitedList`.
  - AWS-specific types: `AWS::EC2::KeyPair::KeyName`, `AWS::EC2::VPC::Id`, `AWS::EC2::Subnet::Id`, `List<AWS::EC2::Subnet::Id>`.
  - **SSM parameter types**: `AWS::SSM::Parameter::Value<String>` reads the value from Parameter Store at deploy time (for example, the latest AMI ID).
  - Constraints: `AllowedValues`, `AllowedPattern`, `MinLength`/`MaxLength`, `MinValue`/`MaxValue`, `Default`.
  - **`NoEcho: true`** masks the value in the console and API output. It is still not a secure store; use dynamic references.
- `Rules`: validate parameter combinations before deployment (for example, prod must use a large instance type).
- `Mappings`: static lookup tables, read with `Fn::FindInMap`. For example, per-Region AMI IDs or per-environment sizes.
- `Conditions`: boolean logic (`Fn::Equals`, `And`, `Or`, `Not`, `If`) to create resources or set properties only in some cases (for example, `IsProd`).
- `Transform`: macros applied before processing:
  - `AWS::Serverless-2016-10-31` (SAM).
  - `AWS::Include` (insert snippets from S3).
  - `AWS::LanguageExtensions` (`Fn::ForEach`, `Fn::Length`, `Fn::ToJsonString`, default `DeletionPolicy` from parameters; verify list).
- `Resources`: the **only required section**. Each resource has a logical ID, `Type` and `Properties`, plus optional attributes (section E).
- `Outputs`: values to show or **export** (`Export: Name:`) for other stacks (for example, a bucket name or VPC ID).
- **Logical ID** = the name in the template. **Physical ID** = the real AWS name/ARN.
  - If you don't set a name, CloudFormation generates a unique physical name like `stack-MyBucket-ABC123`. Letting it do so avoids replacement conflicts.

## C. Intrinsic functions and pseudo parameters
- **`Ref`**: a parameter's value, or a resource's main identifier (often its name or ID; for example, a bucket name or queue URL).
- **`Fn::GetAtt`**: a resource attribute (`!GetAtt MyBucket.Arn`, `!GetAtt MyQueue.QueueName`).
- **`Fn::Sub`**: string substitution: `!Sub 'arn:aws:s3:::${BucketName}/*'`, `${AWS::Region}`.
- `Fn::Join`, `Fn::Split`, `Fn::Select`, `Fn::GetAZs`, `Fn::Cidr`, `Fn::Base64` (EC2 user data).
- `Fn::If`, `Fn::Equals`, `Fn::And`, `Fn::Or`, `Fn::Not`: for conditions.
- **`Fn::ImportValue`**: read an **exported** output from another stack in the same account and Region.
- `Fn::FindInMap`: read Mappings.
- `Fn::Transform`: call a macro on part of a template.
- **Pseudo parameters**:
  - `AWS::AccountId`, `AWS::Region`, `AWS::StackName`, `AWS::StackId`, `AWS::Partition` (aws, aws-cn, aws-us-gov), `AWS::URLSuffix`.
  - `AWS::NoValue` removes a property when used with `Fn::If`.
- Use `AWS::Partition` and `AWS::Region` instead of hard-coding ARNs, so templates work in any Region or partition.

## D. Stacks and the stack lifecycle
- **Create stack** → CloudFormation builds a dependency graph from `Ref`/`GetAtt`/`DependsOn` and creates independent resources **in parallel**.
- Status flow: `CREATE_IN_PROGRESS` → `CREATE_COMPLETE`, or on error `CREATE_FAILED` → `ROLLBACK_IN_PROGRESS` → `ROLLBACK_COMPLETE`.
- A stack in **`ROLLBACK_COMPLETE`** (failed create) **cannot be updated**. You must **delete it and create again**.
- **Update stack** → `UPDATE_IN_PROGRESS` → `UPDATE_COMPLETE`, or on error `UPDATE_ROLLBACK_IN_PROGRESS` → `UPDATE_ROLLBACK_COMPLETE` (back to the last good state).
- **`UPDATE_ROLLBACK_FAILED`**: the rollback itself failed. Common causes: a resource was changed or deleted outside CloudFormation, or permissions are missing. Fix the cause, then **ContinueUpdateRollback**, optionally **skipping** resources that can't roll back.
- **Delete stack** deletes all resources in reverse dependency order, except those with `Retain`/`Snapshot` policies. **`DELETE_FAILED`** is common for non-empty S3 buckets, resources in use, or exports still imported.
- **Stack failure options** ("preserve successfully provisioned resources", `--disable-rollback`):
  - On failure, CloudFormation keeps the successful resources instead of rolling everything back.
  - Then you choose **Retry**, **Update** or **Roll back**. This speeds up fixing long stacks.
  - Not for immutable (replacement) updates.
- **Rollback triggers**: CloudWatch alarms watched during an update and for a **monitoring period** after it (up to 180 minutes; verify). If an alarm fires, CloudFormation rolls back.
- **Express mode** (new):
  - Reports a resource done as soon as its API call succeeds, without waiting for it to stabilize. Much faster stack operations for **dev iteration**.
  - Rollback is **off by default** in express mode. Not supported with StackSets. Custom resources still wait for their response.
  - Enable with `--deployment-config '{"mode":"EXPRESS"}'`, `cdk deploy --express` or `sam deploy --express`.
  - Use the default mode for production.
- **Termination protection**: blocks stack deletion until you turn it off. Nested stacks inherit it from the root.
- **Capabilities** you must acknowledge:
  - `CAPABILITY_IAM` (creates IAM resources).
  - `CAPABILITY_NAMED_IAM` (IAM resources with custom names).
  - `CAPABILITY_AUTO_EXPAND` (templates with macros/transforms like SAM, or nested stacks with transforms).
  - A missing capability → `InsufficientCapabilitiesException`.
- **Service role** for CloudFormation: an IAM role CloudFormation assumes to make the changes. Users then need only CloudFormation permissions plus **`iam:PassRole`** on that role, not direct rights to every resource. Classic least-privilege pattern.
- **Stack events** show each resource status change and the reason. They are the first place to look on failure.

## E. Resource attributes
- **`DependsOn`**: force an order when there is no `Ref`/`GetAtt` link. Classic case: an EC2 instance that needs the internet gateway attachment first.
- **`DeletionPolicy`** (on stack delete, or when a resource is removed from the template):
  - **`Delete`** (default for most types).
  - **`Retain`**: keep the resource. It still costs money, and is now outside the stack.
  - **`RetainExceptOnCreate`**: retain, except when the creating operation rolls back (cleans up empty new resources).
  - **`Snapshot`**: take a final snapshot, then delete. Supported for EBS volumes, RDS instances/clusters, Aurora, DocumentDB, Neptune, ElastiCache, Redshift.
  - **Default is `Snapshot`** for `AWS::RDS::DBCluster` and for `AWS::RDS::DBInstance` without `DBClusterIdentifier`.
  - S3 buckets with `Delete` fail to delete if not empty. Empty them first (custom resource, lifecycle rules) or use `Retain`.
- **`UpdateReplacePolicy`**: what to do with the **old** physical resource when an update **replaces** it: `Delete` (default), `Retain`, `Snapshot`. `DeletionPolicy` does **not** apply to replacement. Set both on databases and buckets.
- **`CreationPolicy`**: wait for success signals before marking the resource complete. For example, an EC2 instance or ASG waits for `cfn-signal` from user data, with a `Timeout` (like `PT15M`) and a `Count`.
- **`UpdatePolicy`**: how to update ASGs (`AutoScalingRollingUpdate`, `AutoScalingReplacingUpdate`), Lambda aliases (`CodeDeployLambdaAliasUpdate`) and some others.
- **`Condition`**: create the resource only if the condition is true.
- **`Metadata`**: per-resource data (cfn-init config).

## F. Update behaviors and change sets
- Each property change has an update type (shown in the docs for every property):
  - **No interruption**: updated in place, no downtime.
  - **Some interruption**: in place but restarted (for example, EC2 instance type change needs a stop/start).
  - **Replacement**: a new resource with a **new physical ID** is created, references are updated, and the **old one is deleted**. Data is lost unless retained or snapshotted. Example: renaming an S3 bucket, or changing an RDS engine (verify per property).
- **Change set** = a preview of what an update will do:
  - Add / modify / remove, and whether each change **replaces** a resource (`Replacement: True/False/Conditional`).
  - Create it, review it, then **execute** (or delete it).
  - Best practice for production updates and required for approvals in pipelines.
- Change sets also support importing resources (resource import) and nested stack changes.
- Custom-named resources can't be replaced in place, because two resources can't share the name during replacement. The update fails. Prefer generated names.

## G. Protecting stacks and resources
- **Stack policy**: a JSON policy that **denies updates** to chosen resources during stack updates (for example, deny `Update:Replace` / `Update:Delete` on the production DB).
  - Once set it cannot be removed, only changed.
  - It can be overridden temporarily for one update.
  - It does not protect against stack **deletion** (use termination protection and `DeletionPolicy`).
- **Termination protection** + `DeletionPolicy: Retain/Snapshot` + `UpdateReplacePolicy` = full protection for stateful resources (buckets, tables, databases).
- **Drift detection**: compares actual resource configuration with the template and flags `MODIFIED`, `DELETED`, `IN_SYNC` or `NOT_CHECKED`. It only checks supported resource types and properties set in the template. It **does not fix** drift: you update the template, or revert the manual change.
- AWS Config rule `cloudformation-stack-drift-detection-check` can run drift checks on a schedule. EventBridge can alert on drift status changes.
- **Resource import**: bring existing resources (made by hand or by another stack) **into** a stack without re-creating them. Needs the identifier and a `DeletionPolicy` in the template.
- **Moving resources between stacks**: set `Retain`, remove from stack A, then import into stack B. Or use the stack **refactoring** feature (verify).

## H. Splitting templates: nested stacks vs cross-stack references
- **Nested stacks**: a resource of type `AWS::CloudFormation::Stack` points to a child template in S3.
  - Use for **reusable components** (a standard VPC, a standard bucket with policies) deployed **as part of one parent**.
  - The parent controls the lifecycle: update and delete go through the root stack.
  - Helps you get past the **500 resources per template** limit.
  - Outputs of children are read with `!GetAtt ChildStack.Outputs.Name`.
- **Cross-stack references**: stack A **exports** an output, stack B uses `Fn::ImportValue`.
  - For **separately managed** layers (network team's VPC stack used by many app stacks).
  - Same account and Region only. Export names must be unique per Region.
  - **You cannot delete or change an export while any stack imports it**.
- Alternative to exports: write values to **SSM Parameter Store** and read them with SSM parameter types or dynamic references. That couples stacks less tightly.
- Rule of thumb: same lifecycle → nested stacks. Different owners/lifecycles → exports or SSM parameters.

## I. StackSets (many accounts and Regions)
- **StackSet** = one template deployed as **stack instances** to many **accounts × Regions** from an **administrator account** (or a delegated administrator in Organizations).
- Permission models:
  - **Self-managed**: you create IAM roles yourself: `AWSCloudFormationStackSetAdministrationRole` in the admin account, `AWSCloudFormationStackSetExecutionRole` in each target.
  - **Service-managed** (AWS Organizations): AWS creates the roles. You target **OUs**, and **automatic deployment** adds the stack to **new accounts** that join the OU (and can remove it when they leave).
- Deployment options:
  - **Maximum concurrent accounts** (number or %).
  - **Failure tolerance** (how many failures before stopping).
  - **Region order** and Region concurrency (sequential/parallel).
  - Concurrency mode (strict vs soft failure tolerance).
- **Parameter overrides** per account or Region. **Drift detection** on StackSets. Import existing stacks into a StackSet.
- Service-managed StackSets **cannot use templates with macros/transforms** (so no SAM transform). Use plain CloudFormation there.
- Uses:
  - Org-wide guardrails: CloudTrail, AWS Config rules, IAM roles for auditors, GuardDuty.
  - The same data-platform baseline (buckets, KMS keys, Lake Formation roles) in every account/Region.
- Quotas: 1,000 StackSets per admin account, 100,000 stack instances per StackSet, 10,000 concurrent instance operations per Region.

## J. Extending CloudFormation
- **Custom resources** (`AWS::CloudFormation::CustomResource` or `Custom::Name`):
  - CloudFormation sends Create/Update/Delete events to a **Lambda function or SNS topic**. Your code does the work and **responds** to a pre-signed S3 URL.
  - Uses: empty an S3 bucket before delete, look up values, call third-party APIs, seed a database, run Athena DDL.
  - If your code never responds, the stack hangs for up to 1 hour by default. Set **`ServiceTimeout`** to fail faster.
  - Response data limit: 4,096 bytes.
- **Registry / resource types**:
  - Public third-party types (Datadog, MongoDB Atlas…), private types you build with the CloudFormation CLI.
  - **Modules**: reusable resource bundles.
  - **Hooks** (section K).
- **Macros**: Lambda-backed template processors. Transforms (`AWS::Serverless`, `AWS::Include`, `AWS::LanguageExtensions`) are AWS-hosted macros. Templates with macros must be deployed through **change sets** (verify) and need `CAPABILITY_AUTO_EXPAND`.
- **Helper scripts for EC2** (Amazon Linux has them preinstalled):
  - **`cfn-init`**: reads `AWS::CloudFormation::Init` metadata (packages, files, services, commands) and applies it.
  - **`cfn-signal`**: sends success/failure to a `CreationPolicy` or `WaitCondition`.
  - **`cfn-hup`**: daemon that detects metadata changes and re-runs config on update.
  - `cfn-get-metadata`.
- **WaitCondition / WaitConditionHandle**: an older signal mechanism. Prefer `CreationPolicy` for EC2/ASG.
- **Dynamic references** (keep secrets out of templates):
  - `{{resolve:ssm:/path/param}}` (plain String), `{{resolve:ssm-secure:/path/param}}` (SecureString, only in supported properties), `{{resolve:secretsmanager:secret-id:SecretString:json-key}}`.
  - Resolved at deploy time and **not stored in the template**. Up to **60 per template**.
  - Not supported in custom resources (for secure values), EC2 `UserData` or `AWS::CloudFormation::Init`.
  - Don't use them in properties that form a resource's primary identifier (the value could leak).
  - Pairs with `ManageMasterUserPassword` (RDS) and `AWS::SecretsManager::Secret` with `GenerateSecretString` to create random DB passwords.

## K. Governance and authoring tools
- **CloudFormation Hooks**: proactive checks that run **before** resources, stacks or change sets are provisioned (also for Cloud Control API).
  - Ways to write them: **Guard rules**, **Lambda functions**, custom Hooks, or Control Tower **proactive controls**.
  - Failure mode: **FAIL** (block the operation) or **WARN** (allow but warn).
  - Examples: block public buckets, require encryption, restrict instance sizes.
- **CloudFormation Guard (cfn-guard)**: policy-as-code DSL to validate templates in CI (shift-left) or inside Hooks.
- **cfn-lint**: linter for template syntax and best practices. Runs in IDEs and CI.
- **IaC generator**:
  - **Scans** existing resources in an account/Region (scan valid 30 days) and **generates a template**.
  - Then **imports** the resources into a stack, or migrates to a CDK app with `cdk migrate`.
  - Up to 500 resources per generated template. Only supports Cloud Control API resource types.
  - Use it to bring click-ops resources under IaC.
- **Git sync**:
  - CloudFormation watches a **Git repo** (GitHub, GitHub Enterprise, GitLab, Bitbucket) for a template file plus a **stack deployment file** (parameters, tags). Commits auto-update the stack.
  - Can comment on pull requests with the planned changes. Uses AWS CodeConnections.
- **Infrastructure Composer** (formerly Application Composer): visual drag-and-drop designer that writes CloudFormation/SAM templates. Also in VS Code via the AWS Toolkit.
- **Template studio / CloudFormation console designer**: edit and validate templates in the console (the old Designer is replaced; verify).
- **Cloud Control API**: a single CRUD API for AWS and registry resource types. It powers the IaC generator, Terraform AWSCC provider, Hooks for non-CFN changes.

## L. CloudFormation for data platforms
- Typical resources:
  - S3 buckets (encryption, versioning, lifecycle, bucket policies).
  - Glue databases, tables, crawlers, jobs, triggers, workflows.
  - Lake Formation permissions and settings.
  - Athena workgroups, Kinesis streams, Firehose delivery streams, MSK clusters.
  - Redshift clusters / Serverless workgroups.
  - Step Functions state machines, EventBridge rules, Lambda functions, IAM roles, KMS keys, SNS topics, SQS queues.
- Upload Glue job scripts and Lambda code to S3 first (or let SAM/CDK do it as **assets**), then reference the S3 location in the template.
- Parameterize per environment (`Env=dev|prod`). Use Conditions for prod-only resources (alarms, bigger sizes, cross-Region replication).
- Protect **data stores** with `DeletionPolicy: Retain`/`Snapshot` + `UpdateReplacePolicy`. Never let a rename silently replace a bucket or table.
- Store pipeline config in SSM Parameter Store and read it with SSM parameter types or dynamic references.

## Scenarios (if → then, because)
- If the same pipeline (buckets, Glue jobs, roles) must be built identically in dev, test and prod → one CloudFormation/SAM/CDK template with environment parameters, because IaC gives repeatable deployments.
- If you must see whether an update will **replace** the production database before applying it → create a **change set** and check `Replacement`.
- If a stack update must never replace or delete the prod RDS instance → stack policy denying `Update:Replace`/`Update:Delete` on it, plus `DeletionPolicy: Snapshot` and `UpdateReplacePolicy: Snapshot`.
- If the data lake bucket must survive stack deletion → `DeletionPolicy: Retain` (and termination protection on the stack).
- If a stack delete fails on an S3 bucket → the bucket is not empty. Empty it (custom resource or manual), or set `Retain`.
- If a first create failed and the stack is in `ROLLBACK_COMPLETE` → delete the stack and create it again. It can't be updated.
- If a stack is stuck in `UPDATE_ROLLBACK_FAILED` because someone deleted a resource by hand → fix or recreate the resource, then ContinueUpdateRollback (skipping resources if needed).
- If a long stack fails near the end and you don't want a full rollback each try → "preserve successfully provisioned resources" (`--disable-rollback`), then Retry/Update.
- If developers want fast iteration on dev stacks → express mode (`--express`), but not for prod.
- If the network team owns the VPC and many app teams need its subnet IDs → export outputs (or SSM parameters), and app stacks use `Fn::ImportValue`.
- If a reusable "standard secure bucket" is needed inside many stacks → nested stack (or a CDK construct / CloudFormation module).
- If a template has more than 500 resources → split it into nested stacks.
- If CloudTrail and Config must be in every account and Region of the organization, including new accounts → service-managed **StackSet** targeting OUs with automatic deployment.
- If a DB password must not appear in the template or console → `{{resolve:secretsmanager:...}}` or generate it with `AWS::SecretsManager::Secret`, and never use plain parameters.
- If someone changed a security group by hand and you need to find it → drift detection on the stack.
- If buckets and roles were created by hand last year and must now be managed as code → IaC generator scan → template → resource import (or `cdk migrate`).
- If deployments must be blocked when a bucket is not encrypted → CloudFormation Hook (Guard rule) in FAIL mode, and cfn-guard in CI.
- If developers should deploy stacks without having admin rights → CloudFormation **service role** plus `iam:PassRole` for developers.
- If deployment fails with `InsufficientCapabilitiesException` → acknowledge `CAPABILITY_IAM`/`CAPABILITY_NAMED_IAM`/`CAPABILITY_AUTO_EXPAND`.
- If an EC2 instance must finish installing software before the stack is complete → `CreationPolicy` + `cfn-signal` from user data (with `cfn-init`).
- If a bucket must be emptied or an Athena table created during deployment → Lambda-backed custom resource (with `ServiceTimeout`).
- If an update to a custom-named resource fails because the resource must be replaced → remove the custom name or rename it, because replacement needs a new unique name.
- If deploys should trigger automatically from Git commits without building a pipeline → CloudFormation Git sync.
- If an update must roll back automatically when error alarms fire after deploy → rollback triggers with CloudWatch alarms and a monitoring period.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: CloudFormation quotas (500 resources, 200 parameters/outputs/mappings, 51,200-byte template body / 1 MB from S3, 2,000 stacks, 1,000 StackSets, 100,000 stack instances, 60 dynamic references, 4,096-byte cfn-signal and custom resource data, 2,500 resources per nested stack operation), DeletionPolicy options and RDS Snapshot defaults, dynamic reference rules, stack failure options and rollback-stack, express mode, StackSets topics and the macros restriction for service-managed StackSets, IaC generator quotas and `cdk migrate`, Git sync providers, Hooks implementation options.
Not confirmed (verify): third-party resource handler charges, `AWS::LanguageExtensions` function list, rollback trigger monitoring maximum (180 minutes), examples of replacement properties, stack refactoring feature, macros needing change sets, current state of the old Designer vs template studio.

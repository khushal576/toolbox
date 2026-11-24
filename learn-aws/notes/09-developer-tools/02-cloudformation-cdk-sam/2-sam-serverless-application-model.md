# CloudFormation, CDK and SAM – 2. AWS SAM (Serverless Application Model)

Short notes. Each point is a fact you can be asked about.

## A. What SAM is
- **AWS SAM** = an open-source framework for building **serverless applications** with IaC. It has two parts:
  - **SAM template**: an **extension of CloudFormation** with short serverless resource types.
  - **SAM CLI**: a tool to **build, test locally, deploy, sync, view logs and set up pipelines**.
- A SAM template starts with **`Transform: AWS::Serverless-2016-10-31`**. During deployment CloudFormation runs the SAM transform, which **expands** each SAM resource into normal CloudFormation resources.
- Example: one `AWS::Serverless::Function` with an SQS event becomes an `AWS::Lambda::Function`, an IAM role, an `AWS::Lambda::EventSourceMapping` and, if needed, versions/aliases/permissions.
- **Every CloudFormation feature still works** in a SAM template: normal `AWS::*` resources, Parameters, Conditions, Outputs, DeletionPolicy, nested stacks. You can mix SAM and plain resources freely.
- Because of the transform, deploys need **`CAPABILITY_AUTO_EXPAND`** (plus `CAPABILITY_IAM` for generated roles). Service-managed **StackSets cannot use SAM templates** (no macros there).
- Pick SAM when:
  - Building Lambda-centric apps: APIs, event-driven pipelines, Step Functions workflows.
  - You want short **declarative YAML** close to CloudFormation.
  - You want **local testing** and fast deploy loops for Lambda.
  - The exam asks for "serverless data pipeline deployment" with **AWS SAM** (skill 1.4.6).
- Pick CDK instead when you prefer **code** (loops, classes, reuse) over YAML, or have large, mixed infrastructure. SAM CLI can still test CDK apps locally.
- Pick plain CloudFormation when there is little serverless content, or you need StackSets with service-managed permissions.
- SAM CLI also supports **Terraform** projects for local testing and debugging of Lambda functions and layers.

## B. SAM resource types
- **`AWS::Serverless::Function`**: Lambda function plus role, triggers (`Events`), versions/aliases, layers, destinations, deployment preferences.
- **`AWS::Serverless::Api`**: API Gateway **REST API** (stages, auth, usage plans, OpenAPI definition body).
- **`AWS::Serverless::HttpApi`**: API Gateway **HTTP API** (cheaper, simpler, JWT authorizers).
- **`AWS::Serverless::WebSocketApi`**: WebSocket APIs (verify; newer).
- **`AWS::Serverless::GraphQLApi`**: AWS AppSync GraphQL API.
- **`AWS::Serverless::StateMachine`**: Step Functions state machine:
  - Definition inline or from a file, with `DefinitionSubstitutions`.
  - Policies, `Events` (Schedule, EventBridge, Api).
- **`AWS::Serverless::SimpleTable`**: a DynamoDB table with one primary key, for simple cases. Use `AWS::DynamoDB::Table` for anything advanced (GSIs, streams, TTL…).
- **`AWS::Serverless::LayerVersion`**: Lambda layer (with `RetentionPolicy` to keep old versions).
- **`AWS::Serverless::Application`**: a **nested application**, from the **Serverless Application Repository (SAR)** or a local/S3 template. Becomes a nested stack.
- **`AWS::Serverless::Connector`**: permissions between resources (section E).
- **`AWS::Serverless::CapacityProvider`**: Lambda Managed Instances capacity provider (VPC, instance types, scaling) (verify property details).
- **`AWS::Serverless::NetworkConnector`** and **`AWS::Serverless::MicrovmImage`**: newer types for networking and Lambda MicroVMs (verify details).
- **`Globals`** section: shared defaults for all functions/APIs/tables, for example `Runtime`, `Timeout`, `MemorySize`, `Architectures`, `Tracing`, `Environment`, `Layers`, `VpcConfig`, `LoggingConfig`. A setting on a resource overrides Globals (maps are merged, lists added; verify merge rules).

## C. Key `AWS::Serverless::Function` properties
- `CodeUri` (local folder or S3 path) + `Handler` + `Runtime`. Or `PackageType: Image` + `ImageUri` with build `Metadata` (Dockerfile) for container images. `InlineCode` for tiny functions.
- `MemorySize`, `Timeout`, `Architectures: [arm64]`, `EphemeralStorage`, `Environment.Variables`, `Layers`, `VpcConfig`, `FileSystemConfigs` (EFS), `Tracing: Active` (X-Ray), `LoggingConfig` (JSON, log levels, log group).
- `ReservedConcurrentExecutions`, `ProvisionedConcurrencyConfig` (needs `AutoPublishAlias`), `SnapStart: ApplyOn: PublishedVersions`.
- `DeadLetterQueue`, `EventInvokeConfig` (max retries, max event age, on-success/on-failure destinations).
- `Role` (bring your own) **or** `Policies` (SAM builds the role): AWS managed policy names, **policy templates**, or inline policy statements.
- `AutoPublishAlias` + `DeploymentPreference` (section G).
- `FunctionUrlConfig` (function URL with `AuthType` and CORS).
- `RuntimeManagementConfig`, `RecursiveLoop`, `CodeSigningConfigArn`, `KmsKeyArn`.
- `Events` (section D) wires up triggers in a few lines.

## D. `Events`: wiring triggers
- **`S3`**: bucket (must be in the **same template**), events (`s3:ObjectCreated:*`), prefix/suffix `Filter`. SAM adds the notification and the invoke permission.
- **`SQS`**: queue ARN, `BatchSize`, `MaximumBatchingWindowInSeconds`, `FunctionResponseTypes: [ReportBatchItemFailures]`, `ScalingConfig.MaximumConcurrency`, `FilterCriteria`.
- **`Kinesis`** / **`DynamoDB`** (streams): `StartingPosition`, `BatchSize`, `ParallelizationFactor`, `MaximumRetryAttempts`, `MaximumRecordAgeInSeconds`, `BisectBatchOnFunctionError`, `DestinationConfig.OnFailure`, `TumblingWindowInSeconds`, `FilterCriteria`.
- **`MSK`** / **`SelfManagedKafka`** / **`MQ`** / **`DocumentDB`**: other event source mappings.
- **`Schedule`** / **`ScheduleV2`**:
  - `Schedule` uses an EventBridge rule (`rate(5 minutes)`, `cron(0 2 * * ? *)`).
  - `ScheduleV2` uses **EventBridge Scheduler** (time zones, flexible windows, one-time schedules).
- **`EventBridgeRule`** (and `CloudWatchEvent`): event pattern on a bus, with retry policy and DLQ.
- **`Api`** / **`HttpApi`**: path + method on an implicit or explicit API.
- **`SNS`**, **`CloudWatchLogs`**, **`Cognito`**, **`IoTRule`**, **`AlexaSkill`**.
- One function can have **many events**. Each event becomes its own CloudFormation resources.

## E. Permissions: policy templates and connectors
- **SAM policy templates** = ready least-privilege IAM statements with a parameter:
  - Storage: `S3ReadPolicy: {BucketName: !Ref RawBucket}`, `S3WritePolicy`, `S3CrudPolicy`.
  - DynamoDB: `DynamoDBReadPolicy`, `DynamoDBCrudPolicy`, `DynamoDBStreamReadPolicy`.
  - Queues and topics: `SQSPollerPolicy`, `SQSSendMessagePolicy`, `SNSPublishMessagePolicy`.
  - Streams: `KinesisStreamReadPolicy`, `KinesisCrudPolicy`, `FirehoseWritePolicy`.
  - Orchestration and query: `StepFunctionsExecutionPolicy`, `AthenaQueryPolicy`.
  - Secrets and keys: `AWSSecretsManagerGetSecretValuePolicy`, `SSMParameterReadPolicy`, `KMSDecryptPolicy`.
  - Events and VPC: `EventBridgePutEventsPolicy`, `VPCAccessPolicy`.
  - (verify the exact names in the current list)
- Faster and safer than hand-written policies. Each template is scoped to the named resource.
- **Connectors** (`Connectors` attribute on a source resource, or `AWS::Serverless::Connector`):
  - You state "Source → Destination with **Read**/**Write** permissions". SAM writes the IAM policies (and resource policies where needed).
  - Example: Function → `Write` → DynamoDB table. API → `Write` → Function. Function → `Write` → SQS queue. S3 → `Write` → Function. StateMachine → `Write` → Function.
  - Works between serverless and non-serverless resource types in supported pairs. Supports multiple destinations from one connector.
  - Exam cue: "least-privilege permissions between resources without writing IAM policies" → **SAM connectors** (or policy templates).
- You can also attach managed policies (`AWSLambdaBasicExecutionRole`, `AmazonS3ReadOnlyAccess`) or full inline statements in `Policies`. Avoid broad policies.
- `PermissionsBoundary` can be set on generated roles (in Globals too), which is often required in enterprise accounts.

## F. SAM CLI commands
- **`sam init`**: scaffold a project from templates (runtime, app type such as "Hello World", "Data processing"…).
- **`sam validate`**: check the template (with `--lint` it uses cfn-lint).
- **`sam build`**:
  - Resolves dependencies per function (requirements.txt, package.json, Maven/Gradle) and prepares artifacts in `.aws-sam/build`.
  - **`--use-container`** builds inside a Lambda-like Docker image. Use it for **native dependencies** and the correct **architecture** (arm64/x86).
  - `--parallel` and `--cached` speed up builds.
- **`sam deploy`**:
  - Packages artifacts (zips to **S3**, images to **ECR**), creates a **CloudFormation change set** and executes it.
  - **`--guided`** asks questions the first time and saves answers in **`samconfig.toml`** (stack name, Region, capabilities, parameters, confirm changeset, resolve S3/ECR).
  - `--resolve-s3` creates or uses a managed artifact bucket.
  - `--no-execute-changeset` lets you review first.
  - `--parameter-overrides`, `--config-env prod` (environment sections in samconfig).
  - `--express` uses CloudFormation express mode for speed in dev.
- **`sam package`**: older two-step flow. Upload artifacts and output a template with S3 URIs. `sam deploy` now does this for you.
- **`sam delete`**: delete the stack and the packaged artifacts.
- **`sam local invoke`**: run one function locally in a Docker container that mimics Lambda, with an event file (`-e event.json`) and env vars (`--env-vars`).
- **`sam local start-api`**: run a local API Gateway on localhost to test HTTP endpoints. Hot reload of code.
- **`sam local start-lambda`**: local endpoint that emulates the Lambda Invoke API (for SDK-based tests, Step Functions Local).
- **`sam local generate-event`**: sample events for S3, SQS, Kinesis, DynamoDB, API Gateway, EventBridge, etc.
- **`sam local execution`** / **`sam local callback`**: test **durable functions** locally (verify).
- **`sam sync`**:
  - Fast cloud dev loop. **`--watch`** syncs local changes to the cloud as you save.
  - Code-only changes are pushed **directly with service APIs** (skipping CloudFormation) where possible. Infrastructure changes go through CloudFormation.
  - **For dev only**: it causes drift, so never use it on prod.
- **`sam logs`**: fetch/tail CloudWatch logs for functions in the stack (`--tail`, filters). **`sam traces`**: fetch X-Ray traces.
- **`sam remote invoke`**: invoke a deployed function (or Step Functions / SQS / Kinesis target) from your machine. **`sam remote test-event`**: manage shareable test events in the cloud.
- **`sam list`**: list endpoints, resources and stack outputs.
- **`sam pipeline bootstrap`**: create pipeline resources per stage (IAM roles, artifact buckets, ECR repos).
- **`sam pipeline init`**: generate a CI/CD config for CodePipeline, GitHub Actions, GitLab CI, Jenkins or Bitbucket, with multiple stages (dev → prod).
- **`sam publish`**: publish an app to the **Serverless Application Repository**.
- Local testing needs **Docker** (or a compatible runtime). Local runs use your local AWS credentials for calls to real AWS services. Mock or point at dev resources.

## G. Safe deployments (gradual rollout)
- **`AutoPublishAlias: live`**: on each code change, SAM **publishes a new version** and points the alias `live` at it. Triggers and callers should use the **alias**.
- **`DeploymentPreference`** adds **CodeDeploy** traffic shifting on the alias:
  - **Canary**: `Canary10Percent5Minutes`, `Canary10Percent10Minutes`, `Canary10Percent15Minutes`, `Canary10Percent30Minutes` (10% first, the rest after N minutes).
  - **Linear**: `Linear10PercentEvery1Minute`, `Linear10PercentEvery2Minutes`, `Linear10PercentEvery3Minutes`, `Linear10PercentEvery10Minutes`.
  - **`AllAtOnce`**.
  - **`Alarms`**: CloudWatch alarms (errors, latency). If any fires, CodeDeploy **rolls back** to the old version.
  - **`Hooks`**:
    - `PreTraffic` runs a Lambda before shifting traffic.
    - `PostTraffic` runs a Lambda after shifting is done.
    - Each hook must report success/failure to CodeDeploy (`PutLifecycleEventHookExecutionStatus`).
  - SAM creates the CodeDeploy application, deployment group and service role automatically.
- The **first** deploy needs an existing version to shift from. Deploy first with only `AutoPublishAlias`, then add `DeploymentPreference`.
- Works with provisioned concurrency on the alias and with SnapStart versions.
- Exam cue: "release new Lambda code to a small % of users and roll back automatically on errors" → `AutoPublishAlias` + `DeploymentPreference` canary + alarms.

## H. Organizing larger SAM apps
- **Parameters + `samconfig.toml` environments** (`[default]`, `[prod]`) for per-stage values (bucket names, memory, alarms).
- **Conditions** for prod-only resources (alarms, provisioned concurrency).
- **Nested applications** (`AWS::Serverless::Application`): split big apps into reusable child stacks, or pull shared components from the **Serverless Application Repository** (public or private/shared to accounts and orgs).
- **Layers** (`AWS::Serverless::LayerVersion` with `BuildMethod`) for shared libraries. The AWS-managed **AWS SDK for pandas** layer is referenced by ARN.
- **Outputs** for API URLs, function ARNs, queue URLs. Read them with `sam list stack-outputs`.
- **Tags** applied to all resources with `--tags` or the `Tags` property (cost allocation).
- **`Metadata: BuildMethod`** (python3.x, nodejs, makefile, esbuild for TypeScript) to control builds per function.
- **Infrastructure Composer** can draw and edit SAM templates visually (also inside VS Code with the AWS Toolkit).

## I. SAM for data pipelines (typical shapes)
- **S3 → Lambda → DynamoDB/S3**: a bucket + function with an `S3` event (prefix `raw/`, suffix `.csv`) + `S3ReadPolicy` / `DynamoDBCrudPolicy` (or connectors) + output bucket.
- **Kinesis → Lambda → Firehose → S3**: a `Kinesis` event with bisect/retry/on-failure SQS destination, and `FirehoseWritePolicy`.
- **SQS-buffered workers**: an `SQS` event with `ReportBatchItemFailures` + `MaximumConcurrency` + a redrive DLQ on the queue (plain `AWS::SQS::Queue` with `RedrivePolicy`).
- **Scheduled jobs**: `ScheduleV2` with cron + time zone → Lambda that starts Glue jobs or Athena queries (`AthenaQueryPolicy`, Glue permissions).
- **Orchestration**: `AWS::Serverless::StateMachine` with `DefinitionUri: statemachine/etl.asl.json`, `DefinitionSubstitutions` for function ARNs, `Policies` (`LambdaInvokePolicy`, `StepFunctionsExecutionPolicy`), `Events` (Schedule/EventBridge).
- **Glue in the same template**: plain `AWS::Glue::Job`, `::Crawler`, `::Trigger`, `::Database` resources next to SAM functions. Upload scripts to S3 (or via the SAM artifact bucket with a custom build step).
- **Monitoring as code**: `AWS::CloudWatch::Alarm` on `Errors`/`Throttles`/`IteratorAge` → SNS topic, defined in the same template.

## J. SAM vs CloudFormation vs CDK (quick view)
| | CloudFormation | SAM | CDK |
|---|---|---|---|
| Style | Declarative YAML/JSON | Declarative YAML + serverless shorthand | Imperative code (TS, Python, Java, .NET, Go) |
| Output | Itself | Transformed to CloudFormation | Synthesized to CloudFormation |
| Strength | Everything, StackSets, governance | Serverless apps, local testing, gradual Lambda deploys | Abstractions, loops, reuse, big apps |
| Local Lambda testing | No | Yes (`sam local`) | Via SAM CLI on synthesized output |
| Fast dev loop | Express mode | `sam sync --watch` | `cdk watch` / hotswap |
| Gradual Lambda deploys | Manual CodeDeploy resources | `DeploymentPreference` | `LambdaDeploymentGroup` construct |

## Scenarios (if → then, because)
- If a team must deploy a serverless ETL (S3 trigger → Lambda → DynamoDB) as code with minimal YAML → AWS SAM template with `AWS::Serverless::Function` + `Events: S3` + a policy template or connector.
- If a function needs read access to one bucket only → `S3ReadPolicy` policy template with that bucket name, because it scopes the permission.
- If permissions between a function and a table must be least-privilege without writing IAM → SAM connector (Function → Table, Write).
- If code with native libraries (numpy/pyarrow) fails with import errors after deploy → `sam build --use-container` (match the Lambda OS and architecture).
- If developers want to test a Lambda with an S3 event on their laptop → `sam local generate-event s3 put` + `sam local invoke -e`.
- If developers want an HTTP API running locally → `sam local start-api`.
- If developers want code changes in the cloud within seconds while coding → `sam sync --watch` (dev stacks only).
- If the first-time deploy must ask for stack name, Region and parameters and remember them → `sam deploy --guided` (saves to samconfig.toml).
- If prod and dev need different parameter values from the same template → `samconfig.toml` environments + `--config-env`, or parameter overrides in the pipeline.
- If new Lambda code must go to 10% of traffic for 10 minutes and roll back on errors → `AutoPublishAlias` + `DeploymentPreference: Canary10Percent10Minutes` + Alarms.
- If integration tests must pass before any traffic shifts → `PreTraffic` hook Lambda.
- If a CI/CD pipeline with dev and prod stages is needed quickly → `sam pipeline bootstrap` + `sam pipeline init` (CodePipeline or GitHub Actions).
- If several apps share a standard "alerting" component → publish it to the Serverless Application Repository and use `AWS::Serverless::Application`.
- If a nightly job must run at 01:00 in Asia/Kolkata time → `ScheduleV2` event with a cron and `ScheduleExpressionTimezone`.
- If a Step Functions ETL workflow and its Lambdas must deploy together → `AWS::Serverless::StateMachine` + functions in one SAM template with `DefinitionSubstitutions`.
- If deploy fails with "Requires capabilities: [CAPABILITY_AUTO_EXPAND]" → add it (SAM transform/nested apps need it).
- If an org-wide StackSet must deploy a SAM template → not possible with service-managed StackSets (no transforms). Package/transform to plain CloudFormation first, or use self-managed approaches.
- If you need DynamoDB with GSIs and streams → use `AWS::DynamoDB::Table`, not `SimpleTable`.
- If you must test Lambda code from a CDK or Terraform project locally → SAM CLI supports both.
- If all functions must share runtime, timeout, tracing and log format → put them in `Globals`.

## Verified from AWS docs on 2026-10-11
Read from current AWS pages: what SAM is and when to use it (incl. CDK and Terraform support, connectors, sam sync), the SAM resource type list (Api, Application, CapacityProvider, Connector, Function, GraphQLApi, HttpApi, WebSocketApi, LayerVersion, MicrovmImage, NetworkConnector, SimpleTable, StateMachine), SAM CLI command list, connectors syntax and behavior, gradual deployment types/alarms/hooks and the two-step first deploy, express mode flags for SAM.
Not confirmed (verify): WebSocketApi, CapacityProvider, NetworkConnector and MicrovmImage property details, Globals merge rules, exact policy template names, `sam local execution`/`callback` being for durable functions.

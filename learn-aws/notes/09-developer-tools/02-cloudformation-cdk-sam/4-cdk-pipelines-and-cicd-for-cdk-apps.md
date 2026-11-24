# CloudFormation, SAM and CDK – 4. CDK Pipelines and CI/CD for CDK apps

Short notes. Each point is a fact you can be asked about. (File 3 covers CDK basics, bootstrapping and operations; this file covers **CDK Pipelines**.)

## A. What CDK Pipelines is
- **CDK Pipelines** = a **high-level construct library** (`aws-cdk-lib/pipelines`, class **`pipelines.CodePipeline`**) that builds an **AWS CodePipeline** that **builds and deploys your CDK app**. The pipeline itself is **defined in CDK code**.
- **Two APIs**:
  - **`aws-cdk-lib/pipelines`** (opinionated, **self-mutating**, synth + deploy for you): use this.
  - **`aws-cdk-lib/aws-codepipeline`** (low-level L2 constructs): you define **stages and actions** yourself; **no self-mutation or auto synth**.
- **Why use it**: one repo defines **app + pipeline**; the pipeline **updates itself**, **deploys to many accounts/Regions**, handles **cross-account roles, KMS keys, Docker/file assets**, and shows **per-stack deploy actions** with change sets.
- **Not for**: simple one-stack apps (a `cdk deploy` from CI may be enough), or non-CDK stacks (use CloudFormation actions in plain CodePipeline).

## B. Core pieces
- **Pipeline stack**: a normal `Stack` containing `new pipelines.CodePipeline(this, 'Pipeline', {...})`. Deploy it **once manually** (`cdk deploy`); afterwards **commits drive everything**.
- **`synth`** (required): a **`ShellStep`** (commands run in CodeBuild; input = source) or **`CodeBuildStep`** (same plus CodeBuild options: image, role, VPC, env vars, cache). Typical commands: `npm ci`, `npm run build`, **`npx cdk synth`**. Output = **cloud assembly** (`cdk.out`), set as `primaryOutputDirectory` (default `cdk.out`).
- **Sources (`CodePipelineSource`)**:
  - **`connection(repo, branch, { connectionArn })`** for **GitHub, GitLab, Bitbucket** via **AWS CodeConnections** (formerly CodeStar Connections). The connection must be **authorized once in the console**.
  - **`gitHub(...)`** (legacy webhook-style; prefer connections), **`codeCommit(repo, branch)`**, **`s3(bucket, key)`**, **`ecr(...)`**.
- **Stages**: **`pipeline.addStage(new MyAppStage(...), { pre, post })`**. A **`cdk.Stage`** subclass groups the **stacks** deployed together and carries the **target `env` (account/Region)**.
- **Waves**: **`pipeline.addWave('Name')`** deploys **several stages in parallel**; add stages to the wave (**faster multi-Region** rollouts, with `pre`/`post` steps on the wave).
- **Steps** you can add **`pre`/`post`**: `ShellStep` (tests, smoke checks), `CodeBuildStep`, **`ManualApprovalStep`** (human gate), `ConfirmPermissionsBroadening` (**security-changes check**: pauses when IAM/SG permissions broaden), custom `Step`s with **dependencies** (`addStepDependency`).
- **Stack-level ordering/extension**: `stage.addPre/addPost`, `pipeline.addStage(..., { stackSteps: [{ stack, pre, changeSet, post }] })` to run steps **around a specific stack**, or **insert a manual check on the change set**.
- **Action order inside a stage**: **Prepare (create change set) → Deploy (execute change set)** per stack, with **dependencies** respected.
- **Outputs/variables**: steps can export **`envFromCfnOutputs`** (use deployed stack outputs, for example an API URL, in a post-deploy test step).

## C. Self-mutation (the key idea)
- The pipeline has an **`UpdatePipeline`** stage after **Build** that runs **`cdk deploy` on the pipeline stack itself**. If your commit **changes the pipeline definition**, it **updates the pipeline** and **restarts the run** with the new definition **before** deploying app stages.
- **Disable** with **`selfMutation: false`** (then you must deploy pipeline changes manually, and the pipeline just deploys app stages).
- The **self-mutation CodeBuild project** runs `cdk deploy` with the **bootstrap deploy role** in the pipeline account: keep that role least-privilege.
- **Trap**: if you change something the pipeline **cannot self-update** (for example **source connection** permissions broken, or a synth bug), the **pipeline gets stuck**: fix and run `cdk deploy` locally to repair.
- **`dockerEnabledForSelfMutation: true`** if the pipeline stack itself uses **Docker assets**.

## D. Bootstrapping and cross-account trust (very testable)
- **Bootstrap every target environment** (account/Region) with **`cdk bootstrap`** so it has the **CDKToolkit** stack: **assets S3 bucket**, **ECR repo**, **deploy/file-publishing/image-publishing/lookup roles**, **CloudFormation execution role**.
- **Modern bootstrap** (required for CDK Pipelines): `cdk bootstrap` (new-style, qualifier `hnb659fds` default). The legacy bootstrap is **not supported** for pipelines.
- **Pipeline account**: bootstrap normally.
- **Target accounts**: `cdk bootstrap aws://<TARGET>/<REGION> --trust <PIPELINE-ACCOUNT> --cloudformation-execution-policies arn:aws:iam::aws:policy/<Policy>` so the **pipeline account's roles may assume the target's deploy roles**, and CloudFormation uses the **execution policy** (avoid `AdministratorAccess` in production; use a **scoped policy** or a **permissions boundary**).
- **`--trust-for-lookup`** lets the pipeline account **perform context lookups** (VPC, AMI) in the target account.
- **`crossAccountKeys: true`** creates a **customer-managed KMS key** on the pipeline artifact bucket so **other accounts can decrypt artifacts** (**cost** for the key). Required when the pipeline deploys **to other accounts**. (With `crossAccountKeys: false` only same-account deploys work.)
- **Environment-agnostic stacks do not work** with cross-account pipelines: each `Stage` needs an explicit **`env`**.
- **Region/account of the pipeline stack must be explicit** (not environment-agnostic).
- **Docker/file assets** are **published** to the target account's bootstrapped **ECR/S3** by **asset publishing steps** (separate CodeBuild projects), then referenced by the stack.
- **Asset publishing options**: `publishAssetsInParallel` (default true; set false if asset projects hit **CodeBuild concurrency limits**), **`dockerEnabledForSynth`** for Docker builds during synth, **`useChangeSets`** (default true).

## E. CodePipeline type, execution mode and settings
- **`pipelineType: PipelineType.V2`** uses **CodePipeline V2** (newer pricing and features: **execution modes** `QUEUED`, `SUPERSEDED` (default), `PARALLEL`; **pipeline-level variables**; **triggers with branch/file-path filters**; **stage-level conditions and rollback**; **manual start with variables**) **(verify details)**. **V1** is the older type.
- **Pricing (CodePipeline)**: **V1** = **$1 per active pipeline per month** (first pipeline free, **30-day** inactivity rule); **V2** = **per action-execution minute** **(verify current prices)**.
- **Artifact bucket** is created by the construct (**S3, encrypted**); set **`artifactBucket`** to reuse one; add **lifecycle rules** to expire old artifacts.
- **Pipeline role/permissions** are generated; extend with `pipeline.pipeline.role.addToPolicy` after **`pipeline.buildPipeline()`** if you need custom permissions.
- **Notifications**: **`pipeline.buildPipeline()`** then add **`notificationRules`** (CodeStar Notifications) to **SNS/Slack/Teams** on stage failure/approval.
- **CodeBuild settings** via **`codeBuildDefaults`** (compute type, build image, **VPC**, **security groups**, **cache**, **role policy statements**, environment variables, **logging to CloudWatch**).
- **Synth caching** (`cache: codebuild.Cache.local(...)`/S3) cuts build time for `npm ci`.
- **Reuse existing `codepipeline.Pipeline`** by passing **`codePipeline`** property (advanced) **(verify)**.

## F. Release patterns with CDK Pipelines
- **Multi-environment**: `Dev` (auto) → `Test` (auto + integration tests as `post`) → **`Prod` with `ManualApprovalStep` in `pre`** (and **wave** for several Regions).
- **Branch strategy**: **one pipeline per branch** (`main` → prod pipeline, `feature/*` → ephemeral dev pipelines/stacks) or **short-lived stacks** via `cdk deploy` in CI.
- **Safe deploys**: **Lambda aliases with `DeploymentPreference`** (CodeDeploy) inside your app stacks for **canaries**; **CloudFormation rollback triggers** (alarms); **stack termination protection** and **retain policies** for data.
- **Approval on permission changes**: **`ConfirmPermissionsBroadening`** prevents silent IAM/security group widening (the pipeline **pauses** with a manual gate).
- **Testing**: **unit tests** (CDK assertions, `Template.fromStack`), **snapshot tests**, **cdk-nag** (policy-as-code), **integration tests** (post steps), **`cdk diff`** in PR builds.
- **Data pipelines**: pipeline deploys **Glue jobs, Step Functions, Lambda, Redshift/Athena resources**, **ETL code assets** (S3), **Feature Store/SageMaker** stacks; keep **stateful resources** (S3, DynamoDB, Kinesis) in **separate stacks** with **retention** and **termination protection**.
- **Drift and lifecycle**: use **CloudFormation drift detection**; avoid manual changes; **imports** for pre-existing resources.

## G. Alternatives and comparison
- **CDK Pipelines** vs **plain CodePipeline + CloudFormation actions**: Pipelines **self-mutates, auto-wires cross-account roles/keys, publishes assets**; plain CodePipeline is **manual to wire** but flexible for **non-CDK** stacks.
- **CDK Pipelines vs GitHub Actions/GitLab CI + `cdk deploy`**: external CI is simpler for **single-account** and when you already use it; Pipelines keeps **everything inside AWS** with **IAM roles, no long-lived keys**, and **self-updating**.
- **CDK Pipelines vs SAM Pipelines** (`sam pipeline init`): SAM generates **CodePipeline/CodeBuild/OIDC role templates** for **SAM apps**; CDK Pipelines is for **CDK apps**.
- **CDK Pipelines vs Service Catalog/Control Tower Account Factory for Terraform/AFC**: those provision **accounts and baselines**; Pipelines deploy **application stacks** (can be combined).
- **CDK Pipelines vs AWS Proton/Service Catalog** for platform templates **(Proton status: verify)**.
- **CDK Pipelines v1 construct (`@aws-cdk/pipelines` originals, `CdkPipeline`)** was replaced; **new code uses `pipelines.CodePipeline`**.

## H. Security and cost
- **Least privilege**: the **CloudFormation execution role** in each target should be **scoped** (policy/permissions boundary), not admin; the **deploy role** is only assumable by the **pipeline account's** roles; use **`--trust`** per account.
- **No static credentials**: the pipeline uses **IAM roles**; connections to GitHub use **CodeConnections** (OAuth app/installation). Use **OIDC** if running CDK from GitHub Actions instead.
- **Protect the pipeline repo/branch**: PR approvals; the pipeline can **deploy to production** from a merge, so **branch protection = production protection**.
- **Secrets**: pull from **Secrets Manager/SSM** in stacks (dynamic references), not from the repo.
- **Artifact encryption**: S3 + **KMS (cross-account key)**; **restrict bucket policy** to pipeline roles.
- **Audit**: **CloudTrail**, **CodePipeline execution history**, **CloudFormation events/change sets**, **notification rules**.
- **Cost**: CodePipeline (V1 per pipeline; V2 per action minute), **CodeBuild minutes** (synth, self-mutation, asset publishing, tests), **KMS key + requests**, **S3 artifacts**, **ECR images**. Reduce with **caching**, **smaller compute types**, **artifact lifecycle**, **fewer asset projects (parallel off only if limits)**.

## I. Troubleshooting (symptom → cause → fix)
- **"Policy contains a statement with one or more invalid principals" / cannot assume role in target** → target account **not bootstrapped with `--trust <pipeline-account>`** → re-bootstrap target.
- **"This CDK deployment requires bootstrap stack version X"** → **outdated bootstrap** → re-run `cdk bootstrap` in that environment.
- **Pipeline stuck at `UpdatePipeline`** → self-mutation failed (synth error, role permission) → read the CodeBuild log, fix, or deploy the pipeline stack manually.
- **Artifact decrypt error in another account** → `crossAccountKeys` off or key policy missing → enable cross-account keys.
- **Docker build fails in synth** → Docker not enabled → `dockerEnabledForSynth: true` (privileged mode).
- **Asset publish throttled / many CodeBuild projects** → raise **CodeBuild concurrency limits** or set `publishAssetsInParallel: false`.
- **Cross-account deploy uses wrong Region/account** → stage `env` missing or environment-agnostic stacks → set explicit `env`.
- **Connection "Pending"** → CodeConnections authorization not completed → authorize in the Developer Tools console.
- **Stack update fails (resource already exists)** → import/rename conflict → use `cdk diff`, retain/import patterns.
- **Rollback `UPDATE_ROLLBACK_FAILED`** → continue rollback and skip stuck resources, then fix the template.

## J. Scenarios: "If X → Y, because Z"
- If a CDK app must deploy to dev, test and prod accounts from one pipeline → **CDK Pipelines with a `Stage` per account and bootstrapped trust (`--trust`)**, because it wires cross-account roles and keys.
- If someone changes the pipeline code and wants it live without manual steps → **self-mutation (`UpdatePipeline`)**, because the pipeline deploys itself before app stages.
- If production deploys need a human gate → **`ManualApprovalStep` in the Prod stage `pre`**, because the pipeline pauses until approved.
- If IAM permissions must not widen silently → **`ConfirmPermissionsBroadening`**, because it pauses for review when permissions grow.
- If several Regions should deploy in parallel → **`addWave`**, because stages in a wave run concurrently.
- If artifacts must be readable from other accounts → **`crossAccountKeys: true`**, because it creates a KMS key whose policy allows cross-account roles.
- If CloudFormation in the target account should not have admin rights → **`--cloudformation-execution-policies` with a scoped policy**, because it limits what stacks can create.
- If your team already uses GitHub Actions and one account → **`cdk deploy` with OIDC role**, because it is simpler than a full pipeline.
- If a SAM (not CDK) app needs CI/CD → **`sam pipeline init`**, because it generates CodePipeline templates for SAM.
- If the pipeline stops after a bad change to the pipeline stack → **`cdk deploy` locally to repair**, because self-mutation cannot fix a broken self-mutation step.

Verified from AWS docs on 2026-11-01: only the CDK Pipelines docs page outline loaded; the descriptions here come from earlier knowledge and a summary of the CDK v2 pipelines API, and were not checked line by line.
Unconfirmed (verify): CodePipeline V2 features and pricing; CodeConnections naming; `ConfirmPermissionsBroadening` and stack-step options; exact bootstrap flags and qualifier default; Proton status; the `codePipeline` reuse property; CodeBuild defaults for asset publishing; all pricing figures.

# CI/CD on AWS – 4. AWS CodeCommit in depth

Short notes. Each point is a fact you can be asked about. (File 1 has the short Git/source-provider overview; this file goes deeper.)

## A. What CodeCommit is
- **Managed, private Git repositories** hosted by AWS. Standard Git works (clone, push, pull, branches, tags), plus AWS CLI/API commands.
- **Encrypted at rest and in transit**. Integrated with **IAM**. HIPAA-eligible, in scope for many compliance programs (SOC, ISO 27001, PCI DSS, FIPS endpoints available).
- **No limit on repository size or file types** (docs), but Git itself degrades with certain patterns.
- **Status**: my earlier notes say CodeCommit became generally available to all customers again in **Nov 2025**; the docs page I read shows **no closure notice**. **Check the current CodeCommit page before a new build** **(verify)**, because AWS changed its availability before.
- **Pick it when**: you want a private Git repo **inside your AWS account** with **IAM access control**, **no extra vendor**, and simple CodePipeline/CodeBuild integration. **Avoid** when you need rich code-review UX, issues/projects, Actions-style CI, or an existing GitHub/GitLab standard.

## B. What not to put in CodeCommit (AWS guidance)
- **Large files that change often** (over about **5 MB** with many revisions): Git's delta chains grow. → **S3 with versioning**.
- **Databases**: repositories only grow. → **DynamoDB**.
- **Audit trails/log streams**: constant generated commits slow Git. → **S3**, **CloudTrail/Config/CloudWatch**.
- **Backups of file systems/DB dumps**. → **AWS Backup**.
- **Thousands of branches/tags**: every push/pull negotiates all refs. → **delete stale branches and tags**. Count refs with `git ls-remote | wc -l`.
- **CodeCommit vs S3 versioning**: CodeCommit tracks **batches of changes across files, collaboration and merges**; S3 versioning only restores past versions of single objects.

## C. Access and authentication
- **HTTPS with Git credentials** (IAM user): service-specific username/password generated per IAM user (limit **2** sets per user) **(verify)**.
- **HTTPS (GRC) with `git-remote-codecommit`**: uses your **IAM role/federated/SSO credentials** (**no static Git credentials**). **Best for roles, SSO and temporary credentials**.
- **SSH**: upload a public key to the IAM user; SSH key ID used as the username.
- **AWS CLI credential helper** (`credential.helper`) for HTTPS with IAM user keys or roles.
- **Federated/SSO users**: use **GRC** or the credential helper; **root user cannot use** Git credentials/SSH.
- **IAM actions**: `codecommit:GitPull`, `codecommit:GitPush`, `CreateBranch`, `CreatePullRequest`, `MergePullRequest...`, `GetRepository`, `DeleteRepository`. **Restrict by repository ARN and branch** using the **`codecommit:References`** condition key (for example deny `GitPush` to `refs/heads/main` for developers).
- **Cross-account access**: create an **IAM role in the repo account** that the other account **assumes** (with `sts:AssumeRole`); there is **no resource-based policy** on repos.
- **Network**: Git endpoints `git-codecommit.<region>.amazonaws.com` and **VPC interface endpoints (PrivateLink)** for `git-codecommit` and `codecommit` APIs.
- **Encryption**: default **AWS-managed KMS key** (`aws/codecommit`) or a **customer-managed KMS key** chosen at repo creation **(verify whether changeable)**.

## D. Collaboration features
- **Branches and tags**, **default branch** setting, **branch protection** by IAM (`codecommit:References` conditions) and **approval rules**.
- **Pull requests**: compare **source vs destination branch**, inline comments, emoji reactions, **merge strategies** (**fast-forward, squash, three-way**), **conflict resolution** in console, **approval rules** (number of approvers + approver pool), **override approval** permission, **merge restrictions**.
- **Approval rule templates**: define rules once and **associate with many repositories** (including **auto-associate by repo name pattern**), so every repo requires, for example, **2 approvers** for merges to `main`.
- **Commit comments** and **comparing commits**; **blame** is not provided in console **(verify)**.
- **Notifications**: **notification rules** (via **AWS CodeStar Notifications**) send events (PR created/updated/merged, comments, approvals, branch created) to **SNS topics** and **Slack/Teams through Amazon Q Developer in chat applications**. **Triggers** (older) invoke **SNS or Lambda** on push/create/delete events.
- **Repository metadata**: tags, description, **default branch**, **clone URL**, **repository size** shown.
- **Large repo performance**: `--depth` shallow clones, **sparse checkout**, avoid huge binaries; **`git gc`** locally.

## E. Integrations
- **CodePipeline**: CodeCommit as a **source action**. **Change detection** uses **EventBridge (event-based, recommended)** instead of polling; pipeline output artifact is a **zip** of the commit, or **"Full clone"** (git repo with history) for CodeBuild if you need Git metadata **(verify option names)**.
- **CodeBuild**: source provider CodeCommit (clone, webhooks not supported for CodeCommit; use EventBridge) **(verify)**.
- **EventBridge**: events for **`CodeCommit Repository State Change`**, **`Pull Request State Change`**, **`Comment on Pull Request`** → start pipelines, Lambda, notifications.
- **Lambda**: triggers on push (for example lint/validation), or **Amazon Q/Bedrock** automated PR comments **(verify)**.
- **CloudFormation/CDK/SAM**: `AWS::CodeCommit::Repository`, CDK `codecommit.Repository`; CDK Pipelines can use CodeCommit as a source.
- **Cloud9** and **IDE toolkits** (AWS Toolkit for VS Code/JetBrains) clone and push.
- **GitHub/GitLab/Bitbucket**: use **AWS CodeConnections** (formerly CodeStar Connections) for CodePipeline sources and **CodeBuild** webhooks; mirror to CodeCommit if required (push to two remotes).
- **Migration**: **import any Git repo** (clone mirror → push to CodeCommit). **From CodeCommit to GitHub/GitLab**: `git clone --mirror`, push mirror, update pipeline sources to CodeConnections, then archive/delete the repo.

## F. Branching and workflow patterns (data pipelines)
- **Trunk-based** with short-lived feature branches + PR approval to `main` (fits CI/CD for ETL code, dbt, IaC).
- **GitFlow** (develop/release/hotfix) for slower release cycles.
- **Environments**: separate branches or **separate pipelines** per environment; **tags** for releases (immutable references for deploys).
- **Repo layout**: one repo for **IaC (CDK/CloudFormation)**, one for **pipeline code (Glue jobs, Lambda, SQL/dbt)**, or a monorepo with path-based change detection **(verify tooling)**.
- **Protect `main`**: IAM deny direct push, require PR + approval rule template, run **CodeBuild test job on PR** (EventBridge on PR events posts results back as a PR comment/approval).
- **Secrets**: never commit secrets (use **Secrets Manager/Parameter Store**); consider **pre-commit hooks** and **Amazon CodeGuru Security/other scanners** **(CodeGuru Reviewer is in maintenance mode; verify alternatives)**.

## G. Limits and numbers (verify in Service Quotas/docs)
- **Repositories per account** (default about **1,000**, adjustable) **(verify)**.
- **Single file size** limits in console/API (for example **6 MB** for console file view, **API 6 MB per file in `PutFile`**) **(verify)**.
- **Maximum number of references/branches**: no hard limit but performance degrades.
- **Approval rules per pull request**: up to **25** **(verify)**; **approval rule templates per account** **(verify)**.
- **Triggers per repo**: **10** **(verify)**.
- **Git credentials per IAM user**: **2**; **SSH keys per IAM user**: **5** **(verify)**.

## H. Cost and operations
- **Pricing**: historically **per active user per month** (with free tier of **5 active users**, plus included storage and Git requests), then extra **storage/request** charges **(verify current price page)**. An **active user** = someone who accesses a repo in the month.
- **Cost tips**: remove inactive IAM users, avoid huge binaries, use **shallow clones** in CI.
- **Monitoring**: **CloudTrail** records API calls (Git operations appear as `GitPull`/`GitPush` data events **(verify)**), **CloudWatch metrics** limited; **EventBridge** for state changes; **notification rules** for people.
- **Backup/DR**: CodeCommit is **replicated across multiple AZs** in a Region; for **cross-Region/external backup**, **mirror pushes** to another remote or run **scheduled `git clone --mirror`** (CodeBuild + EventBridge) to **S3**/another repo.
- **Disaster plan**: pipelines reference repos by name per Region; keep **IaC** so you can recreate the repo and re-push from a mirror.

## I. Troubleshooting (symptom → cause → fix)
- **403 / "The requested URL returned error: 403"** → IAM user/role lacks `GitPull/GitPush`, wrong credentials (cached), or SSO session expired → fix policy, clear credential cache, use **GRC**.
- **Push rejected on `main`** → IAM `codecommit:References` deny or approval rule → open a pull request.
- **Pipeline not triggered** → EventBridge rule missing/disabled, branch name mismatch, pipeline execution role missing → check the **EventBridge rule** created by the pipeline.
- **Slow clones/pushes** → huge repo/many refs → delete stale refs, shallow clone, move binaries to S3.
- **Merge conflict in PR** → resolve in console or locally and push.
- **Cross-account push denied** → role not assumable or **KMS key policy** blocks the other account → fix trust and key policy.
- **Cannot see repository** → wrong **Region** (repositories are regional) → switch Region.

## J. Scenarios: "If X → Y, because Z"
- **If** developers use AWS IAM Identity Center (SSO) or IAM roles and cannot use static keys, **then** use **`git-remote-codecommit` (GRC) over HTTPS**. **This works because** GRC uses the developer's **temporary role, federated or SSO credentials**, so no static Git credentials are needed.
- **If** `main` must never receive direct pushes, **then** add an **Identity and Access Management (IAM)** policy that **denies `GitPush`** when **`codecommit:References`** is `refs/heads/main`, and require **pull requests** with an **approval rule template**. **This works because** IAM enforces the branch protection for every push, so changes reach `main` only through an approved pull request. A rejected push is the expected sign that this works.
- **If** every new repo needs **2 approvers**, **then** create an **approval rule template** with **auto-association** by repo name pattern. **This works because** the template defines the rule once and applies it to every matching repo, including new ones.
- **If** a pipeline should start on each push without polling, **then** use an **AWS CodeCommit source** in AWS CodePipeline with **Amazon EventBridge change detection**. **This works because** it is **event-based**: the push event starts the pipeline at once, which is faster than polling. If it does not trigger, check the EventBridge rule the pipeline created.
- **If** another AWS account must push code, **then** create an **Identity and Access Management (IAM) role in the repo account** that the other account **assumes** (`sts:AssumeRole`). **This works because** AWS CodeCommit repos have **no resource-based policy**, so access across accounts must go through a role. If the repo uses a customer managed key, its **KMS key policy** must also allow that role.
- **If** the repo holds large model files or datasets, **then** store them in **Amazon S3 with versioning** and keep only pointers or metadata in Git. **This works because** large files that change often (over about **5 MB** with many revisions) make Git's delta chains grow and slow every operation.
- **If** your organization standardizes on GitHub, **then** use **AWS CodeConnections** (formerly CodeStar Connections) for AWS CodePipeline and AWS CodeBuild. **This works because** pipelines read GitHub directly, so you avoid keeping duplicate repos in AWS CodeCommit.
- **If** you need a backup outside the Region, **then** run a **scheduled mirror** (`git clone --mirror`) to Amazon S3 or another repo, using **AWS CodeBuild** started by **Amazon EventBridge**. **This works because** AWS CodeCommit is **regional**: it is replicated across Availability Zones (AZs) in one Region, but not to other Regions.
- **If** the branch count is in the thousands and clones are slow, **then** **delete stale branches and tags** (count refs with `git ls-remote | wc -l`). **This works because** every push and pull negotiates **all refs**, so fewer refs means faster operations.

Verified from AWS docs on 2026-11-01 (CodeCommit "What is" page: scope, use-case guidance, workflow). Everything else here (authentication methods, IAM condition keys, approval rules, pricing, limits, EventBridge details) is from earlier knowledge and was not re-fetched.
Unconfirmed (verify): current CodeCommit availability/status for new customers; pricing and free tier; all quotas (repositories, file sizes, triggers, credentials, approval rules); KMS key changeability; "full clone" artifact option naming; CodeBuild webhook behavior with CodeCommit; blame support; CloudTrail data-event names for Git operations.

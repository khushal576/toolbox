# CI/CD – 1. Git basics, source and artifacts

Short notes. Each point is a fact you can be asked about.

## A. Why CI/CD for data pipelines
- **Version control** (Git) = every change to code and config is tracked: who, what, when, why. You can roll back, review and audit.
- **CI (continuous integration)** = every change is built and tested automatically (lint, unit tests, template validation) **before** it is merged or deployed.
- **CD (continuous delivery/deployment)** = tested changes move automatically through environments (dev → test → prod).
  - Continuous **delivery** keeps a manual approval before prod.
  - Continuous **deployment** has no manual gate.
- For data engineering, "code" includes:
  - IaC templates (CloudFormation/SAM/CDK/Terraform).
  - Glue/Spark scripts, Lambda code, Step Functions definitions, SQL/dbt models.
  - Airflow DAGs, data quality rules, schema files, config per environment, and tests.
- The exam's software engineering best practices (skill 1.4.4): **version control, testing, logging, monitoring**. CI/CD (1.4.9) ties them together.
- Benefits: repeatable releases, smaller and safer changes, fast rollback, less manual work, an audit trail for compliance.

## B. Git concepts (must know)
- **Repository (repo)**: project history. **Local** (on your machine) and **remote** (GitHub, GitLab, Bitbucket, CodeCommit).
- **Commit**: a snapshot of changes with a message and an author. It has a unique hash (SHA). Commits are immutable.
- **Staging area (index)**: `git add` picks changes for the next commit. `git commit` records them.
- **Branch**: a movable pointer to a line of commits. `main` is the default branch. Feature branches isolate work.
- **HEAD**: the commit/branch you are on now.
- **Merge**: combines branches.
  - Fast-forward = the pointer just moves.
  - Merge commit = keeps both histories.
- **Rebase**: replays your commits on top of another branch to give linear history. Never rebase **shared/pushed** branches (it rewrites history).
- **Squash**: collapse many commits into one (often on pull request merge).
- **Merge conflict**: the same lines changed on both sides. Resolve by hand, then commit.
- **Pull request (PR) / merge request (MR)**: a request to merge a branch, with code review, comments, CI checks and approvals. This is the main quality gate.
- **Tag**: a fixed name for a commit, used for releases (`v1.4.0`). Pipelines can trigger on tags.
- **Clone / fetch / pull / push**:
  - `clone` copies a remote repo.
  - `fetch` downloads changes without merging.
  - `pull` = fetch + merge (or rebase).
  - `push` uploads commits.
- **Revert vs reset**:
  - `git revert` creates a new commit that undoes an old one. Safe for shared branches.
  - `git reset` moves the branch pointer and can discard history. Local use only.
- **Cherry-pick**: copy one commit onto another branch (for example, a hotfix).
- **Stash**: park unfinished changes for a moment.
- **`.gitignore`**: files Git must not track: secrets, `.env`, credentials, local data files, build output (`.aws-sam/`, `cdk.out/`, `__pycache__`, `.venv`).
- **Never commit secrets**. If a secret is pushed, **rotate it at once**. Removing it from history is not enough, because others may have cloned it. Use pre-commit secret scanners (git-secrets, gitleaks) and repo-side scanning.
- **Large files**: Git is bad at big binary/data files. Keep data in **S3**, not Git. Use **Git LFS** if large binaries must be versioned.
- **Signed commits** (GPG/SSH) prove who made a commit. Branch protection can require them.

## C. Branching strategies
- **Trunk-based development**:
  - Short-lived feature branches (hours to days) merged often into `main`. `main` is always deployable.
  - Use feature flags for unfinished work.
  - Best fit for CI/CD and small, frequent releases.
- **GitHub flow**: branch from `main` → PR → review + CI → merge → deploy. Simple and common.
- **GitFlow**:
  - Long-lived `develop` and `main`, plus `feature/*`, `release/*`, `hotfix/*` branches.
  - More process. Suits scheduled releases. Heavier for CI/CD.
- **Environment branches** (`dev`, `test`, `prod`, each deploying to its own account): easy to understand, but branches drift apart. Prefer one artifact promoted through stages.
- **Branch protection rules**:
  - Require PR reviews and passing CI checks.
  - Block force-push and deletion.
  - Require signed commits or linear history.
  - CODEOWNERS for mandatory reviewers on sensitive paths (IAM, prod config).
- **Promote the same build artifact** through environments ("build once, deploy many"). Only per-environment config/parameters change. Don't rebuild for prod.

## D. Repo layout for data pipelines
- **Monorepo** (one repo for many pipelines/services): shared tooling, atomic cross-pipeline changes. Needs **path filters** so a change triggers only the affected pipeline. CodePipeline V2 triggers support file-path filters.
- **Repo per pipeline/service**: clear ownership and independent releases, but shared code duplication or package versioning.
- Typical folders:
  - `infra/` (SAM/CDK/CFN), `glue_jobs/`, `lambdas/`, `stepfunctions/`, `sql/` or `dbt/`, `tests/` (unit + data quality), `config/dev.json` / `config/prod.json`.
  - `buildspec.yml`, `samconfig.toml` / `cdk.json`, `README`, `CODEOWNERS`.
- **Testing layers**:
  - Unit tests (pure functions, Spark transforms with local Spark, pytest).
  - Contract/schema tests.
  - Integration tests in a dev account (run the Glue job on sample data, check outputs).
  - Data quality checks (Glue Data Quality, Deequ, Great Expectations).
- **Linting/validation**: flake8/ruff/black, `sam validate --lint`, cfn-lint, cfn-guard, cdk-nag, sqlfluff, yamllint.

## E. Source providers for AWS pipelines
- **AWS CodeCommit**:
  - AWS-managed private **Git** repositories (HTTPS with Git credentials / IAM + `git-remote-codecommit`, or SSH keys). Encrypted at rest with KMS.
  - IAM-based access. Approval rules for pull requests. Triggers/notifications.
  - **Status history**:
    - July 2024: closed to new customers.
    - **November 2025: returned to general availability** and is open to new customers again.
    - Git LFS support and new Regions were announced for 2026 (verify which have shipped).
  - CodePipeline can use CodeCommit as a source with **EventBridge** change detection (event-based, not polling).
- **GitHub / GitHub Enterprise / GitLab / GitLab self-managed / Bitbucket / Azure DevOps** (verify Azure DevOps):
  - Connected through **AWS CodeConnections** (formerly **CodeStar Connections**).
  - A **connection** resource is authorized once with the provider (OAuth app / GitHub App). Pipelines and CodeBuild use it, with **no personal tokens in pipelines**.
  - The connection must be completed in the console (status **Available**) before first use. New connections start as **Pending**.
  - IAM: the pipeline role needs `codeconnections:UseConnection` (older `codestar-connections:UseConnection`).
  - Supports webhooks/event-based triggers, **branch, tag, file-path and PR filters** (V2 pipelines), and full clone for Git metadata.
- **Amazon S3 as a source**:
  - A versioned bucket + object key (zip). Change detection by **EventBridge** (CloudTrail data events) or polling (old).
  - Good for artifacts produced elsewhere, or for regulated environments without Git access.
- **Amazon ECR as a source**: a new image push (tag) starts the pipeline. Used for container deploys.
- **GitHub Actions / GitLab CI** can deploy to AWS directly, without CodePipeline:
  - Use **OIDC federation** (an IAM identity provider for `token.actions.githubusercontent.com` plus a role whose trust policy limits `sub` to `repo:org/repo:ref:refs/heads/main`).
  - **No long-term access keys** stored as secrets.
- Old **GitHub version 1 (OAuth token) source action** is legacy. Use CodeConnections (GitHub version 2).

## F. Artifacts and packages
- **Pipeline artifact store**: CodePipeline passes **artifacts** (zips) between actions through an **S3 bucket** per Region.
  - Encrypted with **KMS** (the AWS managed key `aws/s3` by default, or a customer managed key).
  - **A customer managed key is required for cross-account** pipelines.
- Source artifact = repo snapshot (zip). Build output artifact = what CodeBuild produced (packaged template, zips, wheels, jars).
- **"Build once, deploy many"**: the same artifact (same hash) is deployed to dev, test and prod. Only parameters differ. This makes releases traceable and reproducible.
- **AWS CodeArtifact** = managed **private package repository** for **pip (PyPI), npm, Maven/Gradle, NuGet, RubyGems, Swift, Cargo, generic** (verify current formats):
  - **Domain** (owns assets and holds the KMS encryption key, shared by many repos) → **repositories**.
  - **Upstream repositories** and **external connections** to public registries (pypi.org, npmjs.com, Maven Central). They cache public packages, so builds still work if the public registry is down, and you can control what is allowed.
  - Publish your own internal libraries (a shared data-quality library, Spark utils) as versioned packages.
  - Auth: `aws codeartifact login --tool pip|npm|twine` gives a **temporary token** (default 12 hours; verify) configured into the tool.
  - Cross-account sharing with domain/repository resource policies.
  - VPC endpoints for private builds (`codeartifact.api`, `codeartifact.repositories`, plus S3).
  - Package version status (Published, Unlisted, Archived, Disposed) and origin controls (block public versions of internal package names). This prevents **dependency confusion** attacks.
- **Amazon ECR**: container image registry. Image scanning (basic/enhanced with Inspector), immutable tags, lifecycle policies, cross-Region/account replication, pull-through cache for public registries.
- **Glue job scripts** and **Lambda zips** are usually uploaded to an S3 "artifacts" bucket by the build step (or by SAM/CDK asset handling), with versioned keys (`.../build-<id>/job.py`).
- **Semantic versioning** (MAJOR.MINOR.PATCH) for libraries and releases. Tag commits that produced releases.

## Scenarios (if → then, because)
- If two engineers keep overwriting each other's Glue script changes → put scripts in Git with feature branches and pull requests, because Git tracks and merges changes safely.
- If a bad change reached prod and must be undone on a shared branch → `git revert` the commit and redeploy, because reset rewrites shared history.
- If every change to `main` must be reviewed and tested → branch protection: required PR approvals + required CI status checks.
- If IAM and prod config changes must be approved by the security team → CODEOWNERS on those paths + required reviews.
- If a monorepo holds 10 pipelines and any commit triggers all of them → CodePipeline V2 triggers with **file-path filters** per pipeline.
- If releases should deploy only when a version tag is pushed → V2 pipeline trigger on **Git tags**.
- If a pipeline must use GitHub without storing a personal access token → AWS **CodeConnections** (GitHub App), plus `codeconnections:UseConnection` on the pipeline role.
- If a new pipeline fails with "connection not available" → the CodeConnections connection is still **Pending**. Complete the handshake in the console.
- If GitHub Actions must deploy to AWS without access keys → IAM OIDC identity provider + a role trusting the repo/branch `sub` claim.
- If an AWS secret key was committed to Git → deactivate and rotate the key immediately, check CloudTrail for misuse, then clean history and add secret scanning.
- If builds fail when pypi.org is slow or down, or security wants to control packages → CodeArtifact with an upstream external connection to PyPI.
- If a shared Python data library must be reused by many Glue/Lambda projects → publish it to CodeArtifact as a versioned package.
- If an attacker could publish a public package with your internal package's name → CodeArtifact package origin controls (block upstream for internal names).
- If prod must run exactly what was tested in staging → build once, store the artifact, and promote the same artifact with stage-specific parameters.
- If a team needs a fully AWS-managed private Git repo with IAM access → CodeCommit (generally available again since Nov 2025).
- If large data files are being committed to Git → move them to S3 (and Git LFS only for unavoidable binaries).

## Verified from AWS docs on 2026-10-11
Read from current sources: CodeCommit closed to new customers in July 2024 and returned to general availability on 24–25 November 2025 (AWS DevOps blog, CodeCommit document history, InfoQ), with Git LFS and Region expansion planned for 2026; CodePipeline V2 trigger filters (branches, tags, file paths, pull requests), artifact size limits per source.
Not confirmed (verify): whether CodeCommit Git LFS / new Regions have shipped, Azure DevOps support in CodeConnections, CodeArtifact supported formats list, CodeArtifact token default duration.

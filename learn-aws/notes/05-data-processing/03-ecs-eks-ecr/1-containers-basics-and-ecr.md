# ECS, EKS and ECR – 1. Container basics and Amazon ECR

Short notes. Each point is a fact you can be asked about.

## A. Container basics for data engineers
- **Container** = an application plus its libraries and runtime, packaged to run the same everywhere. Containers share the host OS **kernel** (unlike VMs), so they start fast and are light.
- **Image** = the read-only template (built from a **Dockerfile**). **Container** = a running instance of an image.
- **Layers**: each Dockerfile instruction adds a cached layer. Unchanged layers are reused on rebuilds and pulls. Put rarely changing steps (OS packages, `pip install -r requirements.txt`) **before** often-changing steps (copy code) for faster builds.
- **Dockerfile basics**: `FROM` (base image), `RUN`, `COPY`, `WORKDIR`, `ENV`, `USER` (run as non-root), `ENTRYPOINT`/`CMD` (what runs).
  - **Multi-stage builds** keep the final image small (build tools are left out).
- **Tags vs digests**:
  - A **tag** (`:v1.4`, `:latest`) is a movable label. The same tag can point to different images over time.
  - A **digest** (`@sha256:...`) is the **immutable** content hash.
  - Pin digests or immutable tags in production. **Avoid `latest`**.
- **Multi-architecture images**: one image index (manifest list) with `linux/amd64` and `linux/arm64` variants. Needed to run on both x86 and **Graviton**. Built with `docker buildx`.
- **Registry** = image storage (Amazon ECR, Docker Hub, GitHub Container Registry…). **Repository** = images of one application (many tags).
- **Why containers for data work**:
  - Same environment in dev/CI/prod (no "works on my machine").
  - Any language and native library.
  - Easy scaling of many identical workers.
  - Portable between ECS, EKS, Batch, Lambda (image), SageMaker, Glue (custom images not supported in Glue; verify) and EMR on EKS.
- **Container vs serverless functions**: containers suit long-running or heavy jobs with full runtime control. Lambda suits short event-driven code (it can also run container images up to 10 GB).
- **Image size matters**: big images = slow pulls = slow task start and more data transfer (NAT costs). Use slim bases (Amazon Linux minimal, distroless, `python:3.x-slim`), clean caches, and multi-stage builds.

## B. Choosing an AWS container service (map)
- **Amazon ECS**: AWS-native orchestrator. Simple, deeply integrated with IAM, ALB, CloudWatch and Step Functions. No control-plane charge. Best default for AWS-only teams.
- **Amazon EKS**: managed **Kubernetes**. Portable, huge ecosystem (Helm, operators, Spark operator, Airflow on K8s), multi-cloud/hybrid skills. More complex. A control-plane fee per cluster.
- **AWS Fargate**: a **capacity option** (serverless compute for containers) used by **ECS** and **EKS** (and Batch). No servers to manage, pay per task vCPU/GB-second.
- **Amazon ECS Managed Instances**: ECS picks, patches and scales EC2 instances for you (GPUs, specific instance types), with multi-task bin-packing. No SSH. Instances are replaced at 14 days.
- **AWS Batch**: job queue + scheduler on top of ECS/EKS for **batch jobs** (array jobs, retries, Spot).
- **AWS Lambda** (container image packaging): short, event-driven, up to 15 minutes, 10 GB image.
- **AWS App Runner**: fully managed web apps from code/images. **Closed to new customers since 30 April 2026**. Existing customers keep it. AWS points new users to **ECS Express Mode**.
- **ECS Express Mode** (Nov 2025): deploy a containerized web app/API from just an image. ECS sets up the ALB (up to 25 services share one ALB), domain/URL, networking and auto scaling. No extra charge, and the resources stay editable in your account.
- **Amazon ECR**: the image registry used by all of the above.
- **Exam cue for skill 1.2.1 "optimize container usage"**:
  - Right-size task CPU/memory.
  - Choose Fargate vs EC2 vs Spot wisely, use Graviton.
  - Bin-pack on EC2, scale to zero for batch, auto scale services.
  - Use small images and keep images close (same Region ECR / pull-through cache).

## C. Amazon ECR basics
- **Amazon Elastic Container Registry (ECR)** = fully managed, private **OCI/Docker** image registry.
  - Highly available, images stored durably (backed by S3).
  - Integrated with IAM, ECS, EKS, Lambda, Batch, SageMaker, CodeBuild.
  - Also stores **OCI artifacts** (Helm charts, SBOMs, signatures).
- **Registry** = one per account per Region (`<account>.dkr.ecr.<region>.amazonaws.com`). **Repositories** live inside it (`my-etl`, `team/spark-jobs`).
- **ECR Public** (`public.ecr.aws`) for public images. The **ECR Public Gallery** includes AWS official images (for example Amazon Linux, Lambda base images).
- **Authentication**:
  - Docker clients log in with a **token valid 12 hours**: `aws ecr get-login-password --region r | docker login --username AWS --password-stdin <registry>`.
  - The **ECR credential helper** (`docker-credential-ecr-login`) automates this.
  - ECS/EKS/Lambda/Batch pull with their roles (no manual login).
- **IAM permissions to pull**: `ecr:GetAuthorizationToken` (registry-level, resource `*`), `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`, `ecr:BatchCheckLayerAvailability`. Managed policy `AmazonEC2ContainerRegistryReadOnly` (or the newer `...PullOnly`; verify).
- **To push** add `ecr:InitiateLayerUpload`, `UploadLayerPart`, `CompleteLayerUpload`, `PutImage`.
- **Who pulls with what role**:
  - **ECS on EC2**: the container instance role (or task execution role).
  - **ECS on Fargate**: the **task execution role**.
  - **EKS**: the **node IAM role** (kubelet pulls).
  - **Lambda**: the service (with a repository policy allowing Lambda, set up automatically in the same account).
  - **Batch**: the instance/execution role.
- **Repository policy** (resource-based): allow **other accounts** or services to pull/push. Cross-account pulls need the repository policy **plus** IAM permissions in the pulling account. Also use **Organizations conditions** (`aws:PrincipalOrgID`).
- **Registry permissions** (registry-level policy) control **replication** and **pull-through cache** creation (verify scope).
- **Repository creation templates**: default settings (encryption, immutability, lifecycle, policies) for repositories auto-created by replication or pull-through cache.

## D. Tag immutability and lifecycle policies
- **Tag immutability** (`IMMUTABLE`): a pushed tag can't be overwritten. This stops accidental or malicious replacement of `v1.4`, so deployments are reproducible.
  - Exclusion filters allow mutable tags like `latest` while others stay immutable (newer; verify).
- **Lifecycle policies**: automatic cleanup rules (up to **50 rules** per policy). Examples:
  - Expire **untagged** images older than 7 days.
  - Keep only the **last 30 images** with tag prefix `prod-`.
  - Expire images not pulled in 90 days (newer `sinceImagePulled`-style rules; verify).
- Rules are evaluated by **priority**. You can **preview** a policy before applying it. Lifecycle cleanup lowers **storage cost**.
- Images can also be **archived** to a cheaper tier (newer ECR archive storage class; verify).
- Without lifecycle rules, CI builds pile up thousands of images and storage cost grows silently.

## E. Image scanning and supply-chain security
- **Basic scanning**:
  - Free. Uses the **Clair-based/AWS native** CVE database for **OS packages**.
  - **Scan on push** or manual scans (1 scan per image per 24 hours; 100,000 basic scans per day).
- **Enhanced scanning** (with **Amazon Inspector**):
  - **Continuous** scanning of OS **and programming-language packages** (pip, npm, Maven…).
  - Rescans when new CVEs appear, with findings in Inspector and Security Hub, and EventBridge events.
  - Paid through Inspector. Set at registry level with repository filters.
- Findings severity → gate CI/CD (fail the build on CRITICAL) or block deployment with policies.
- **Image signing**:
  - **AWS Signer + Notation** sign images.
  - Verify at deploy time: EKS with Kyverno/Gatekeeper/Ratify admission control; ECS with signature checks in the pipeline (verify built-in ECS support).
  - **Managed signing in ECR** (newer; verify).
- **SBOM**: Inspector can export SBOMs for scanned images.
- **Base image hygiene**: rebuild regularly to pick up patches. Use minimal bases. Run as non-root. Never bake **secrets** into images (they stay in layers forever; anyone who can pull can read them).

## F. Replication, pull-through cache and performance
- **Replication**:
  - **Cross-Region** and **cross-account** replication of images (registry-level rules, filters by repository prefix).
  - Up to **25 rules** and **25 unique destinations**.
  - Use it to keep images **close to compute** in each Region (faster pulls, no cross-Region data charges at pull time) and for DR.
  - Only images pushed **after** setup replicate (verify). Replicated repositories are created automatically (use creation templates for their settings).
- **Pull-through cache**:
  - ECR caches images from upstream registries: **Docker Hub, ECR Public, Quay, GitHub Container Registry, GitLab, Kubernetes registry, Azure Container Registry**, and **other ECR private registries** (verify list).
  - The first pull fetches upstream. Later pulls come from your private ECR, and ECR keeps them synced.
  - Avoids **Docker Hub rate limits** and outages, keeps traffic private (VPC endpoints), and lets you scan cached images.
  - Upstream credentials go in **Secrets Manager** (name prefix `ecr-pullthroughcache/`). Up to **50 rules** per registry.
- **VPC endpoints for private pulls**: `com.amazonaws.<region>.ecr.api`, `com.amazonaws.<region>.ecr.dkr` (interface) **plus an S3 gateway endpoint** (image layers are served from S3). Also CloudWatch Logs if tasks log there.
  - Without these (and without NAT), tasks in private subnets fail with `CannotPullContainerError`.
- **Pull performance**:
  - Same-Region ECR. Smaller images, fewer/larger cached layers.
  - **SOCI** (Seekable OCI) **lazy loading** on Fargate/ECS: the container starts before the full image downloads (needs a SOCI index pushed to ECR).
  - Pre-pulled images on EC2 AMIs. Image cache on EKS nodes.
- **Rate quotas** (per Region, adjustable): GetDownloadUrlForLayer 3,000/s, BatchGetImage 2,000/s, GetAuthorizationToken 500/s, PutImage 10/s, UploadLayerPart 500/s. Massive parallel scale-outs (thousands of tasks at once) can hit pull rate limits, which give throttling errors.
- **Other limits**:
  - 100,000 repositories and 100,000 images per repository (adjustable).
  - **Max layer size 52,000 MiB**, 1,000 tags per image.
  - Lifecycle policy up to 30,720 characters.

## G. Encryption and cost
- **Encryption at rest**:
  - Default **AES-256 (S3-managed keys)**, or **SSE-KMS** with the AWS managed key or a **customer managed key** (also **DSSE-KMS**; verify).
  - Set **at repository creation**; it can't be changed later.
  - A CMK needs key policy permissions for pullers (cross-account pulls of KMS-encrypted images need key access).
- **In transit**: TLS (HTTPS) for all registry API and layer transfers.
- **ECR pricing**:
  - **Storage** per GB-month (about $0.10/GB-month private; verify).
  - **Data transfer**: free within the same Region to AWS services (verify); charged for internet egress and **cross-Region** transfer (replication counts as cross-Region transfer).
  - Enhanced scanning billed via Inspector. Pull-through cache billed as normal storage + upstream transfer.
- **ECR Public**: free storage up to a limit (50 GB; verify) and free anonymous pulls with rate limits (more when authenticated).
- **Cost tips**:
  - Lifecycle policies to delete old/untagged images.
  - Replicate only needed repositories.
  - Pull from the same Region.
  - VPC endpoints instead of NAT for heavy pulls (NAT per-GB fees).
  - Smaller images.

## Scenarios (if → then, because)
- **If** Amazon Elastic Container Service (ECS) tasks in private subnets fail with `CannotPullContainerError`, **then** add the **Amazon Elastic Container Registry (ECR)** interface **VPC endpoints** `ecr.api` and `ecr.dkr` plus an **S3 gateway endpoint** (or a **NAT gateway**), and check that the **task execution role** has the ECR pull permissions. **This works because** a task in a private subnet has no route to ECR on its own, and image layers are served from **Amazon S3**, so the S3 endpoint is needed too. Add a CloudWatch Logs endpoint as well if tasks log there.
- **If** a deployment must always run exactly the image that was tested, **then** deploy by **digest** (`@sha256:...`) or an **immutable tag**, never `latest`. **This works because** a digest is the image's fixed content hash, while a tag like `latest` is a movable label that can point to a different image over time.
- **If** someone overwrote the `prod` tag by mistake, **then** turn on **tag immutability** (`IMMUTABLE`) on the Amazon Elastic Container Registry (ECR) repository and deploy by version tags or digests. **This works because** with immutability a pushed tag can't be overwritten, so `v1.4` always means the same image and deployments are reproducible. Exclusion filters can keep tags like `latest` mutable (newer; verify).
- **If** Amazon Elastic Container Registry (ECR) storage costs keep rising from Continuous Integration (CI) builds, **then** add **lifecycle policies**, for example expire **untagged** images after **7 days** and keep only the **last 30 images** with tag prefix `prod-`. **This works because** lifecycle rules delete old images automatically (up to **50 rules** per policy, evaluated by **priority**, with a preview before applying). Without them, CI builds pile up thousands of images and storage, billed per GB-month, grows silently.
- **If** security needs continuous scanning for known vulnerabilities (CVEs), including Python packages, **then** turn on Amazon Elastic Container Registry (ECR) **enhanced scanning** with **Amazon Inspector**. **This works because** enhanced scanning covers OS **and programming-language packages** (pip, npm, Maven) and rescans when new CVEs appear, sending findings to Inspector, Security Hub and EventBridge. **Basic scanning** is free but checks only OS packages, on push or manually; enhanced scanning is paid through Inspector.
- **If** builds fail randomly because of **Docker Hub rate limits**, **then** set up an Amazon Elastic Container Registry (ECR) **pull-through cache** rule for Docker Hub, with the Docker Hub credentials in **AWS Secrets Manager** (name prefix `ecr-pullthroughcache/`). **This works because** only the first pull goes to Docker Hub; later pulls come from your private ECR copy, which ECR keeps synced. This avoids rate limits and outages, keeps traffic private and lets you scan cached images.
- **If** another AWS account's Amazon Elastic Container Service (ECS) or Amazon Elastic Kubernetes Service (EKS) must pull your images, **then** add a **repository policy** allowing that account (or your organization, with `aws:PrincipalOrgID`), give **IAM pull permissions** in that account, and grant **AWS Key Management Service (KMS)** key access if the repository uses a customer managed key (CMK). **This works because** cross-account pulls need both sides: the resource-based repository policy on your side and Identity and Access Management (IAM) permissions on theirs. Images encrypted with a CMK also need the key policy to allow the puller.
- **If** workloads run in 3 Regions and pulls are slow or expensive, **then** set up Amazon Elastic Container Registry (ECR) **cross-Region replication** to each Region. **This works because** each Region then pulls from a nearby copy, which is faster, avoids cross-Region data charges at pull time and helps disaster recovery. Limits: up to **25 rules** and **25 destinations**, replication itself is billed as cross-Region transfer, and only images pushed after setup replicate (verify).
- **If** large machine learning (ML) images make tasks slow to start on **AWS Fargate**, **then** use **SOCI (Seekable OCI) lazy loading**, slimmer base images and **multi-stage builds**. **This works because** SOCI lets the container start before the full image downloads (it needs a SOCI index pushed to ECR), and smaller images pull faster. Multi-stage builds leave build tools out of the final image.
- **If** the same image must run on **AWS Graviton** (Arm) and x86, **then** build a **multi-architecture image** (one image index, or manifest list) with `docker buildx`. **This works because** the index holds both a `linux/amd64` and a `linux/arm64` variant, so each host gets the one that matches its CPU.
- **If** a secret was baked into an image layer, **then** rotate the secret, delete and rebuild the image, and read secrets at runtime from **AWS Secrets Manager** or **Systems Manager (SSM) Parameter Store** instead. **This works because** a secret stays in its layer forever and anyone who can pull the image can read it, so the old value must be treated as leaked. Runtime secrets never enter the image.
- **If** a team needs a simple way to run a web API from an image with a load balancer and a URL, **then** use **Amazon ECS Express Mode**. **This works because** Express Mode deploys a containerized app from just an image and sets up the Application Load Balancer (ALB), domain/URL, networking and auto scaling, at no extra charge, with the resources still editable in your account. Up to **25 services** share one ALB. **AWS App Runner** is not an option for new users: it closed to new customers on **30 April 2026**.
- **If** images must be encrypted with your own AWS Key Management Service (KMS) key, **then** create the Amazon Elastic Container Registry (ECR) repository with **SSE-KMS** encryption and a **customer managed key (CMK)**. **This works because** ECR uses AES-256 S3-managed keys by default, and encryption is chosen **at repository creation** and can't be changed later. Pullers, including other accounts, also need access in the key policy.

## Verified from AWS docs on 2026-10-11
Read from current sources: ECR service quotas (repositories, images per repository, layer size 52,000 MiB, layer parts, lifecycle rules 50 and length, tags per image 1,000, scan limits, pull-through cache rules 50, replication rules/destinations 25, API rate quotas), App Runner closed to new customers on 30 April 2026 with ECS Express Mode as the recommended path, ECS Express Mode announcement (Nov 2025: image-only deployment, automatic ALB/URL/auto scaling, 25 services per ALB, no extra charge), ECS Managed Instances overview.
Not confirmed (verify): Glue custom image support, newer ECR pull-only managed policy name, registry policy scope, tag immutability exclusion filters, pull-time-based lifecycle rules and archive tier, managed signing in ECR and ECS signature verification, replication of pre-existing images, pull-through cache upstream list, DSSE-KMS support, ECR and ECR Public pricing figures.

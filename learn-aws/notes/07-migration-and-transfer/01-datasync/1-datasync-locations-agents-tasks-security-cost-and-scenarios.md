# DataSync – Online file and object transfer: locations, agents, task modes, options, security, cost, limits, scenarios

Short notes. Each point is a fact you can be asked about.

## A. What it is (verified)
- **AWS DataSync** is a secure, high-speed **online** transfer service for **files and objects** between storage systems and AWS storage services.
- Fully managed, handles the hard parts: parallel transfer, encryption, retries, **data integrity checks**, scheduling, monitoring.
- Faster than DIY tools (`cp`, `rsync`, `aws s3 sync`): purpose-built protocol, **parallel multi-threaded** architecture.
- Common use cases:
  - **Migrate** active datasets into AWS.
  - **Archive** cold data straight to **S3 Glacier Flexible Retrieval / Deep Archive**.
  - **Replicate** data (including to a standby EFS/FSx or another Region).
  - **Move data for in-cloud processing** (ML, analytics, media, genomics).
- Works with files (NFS/SMB/HDFS) and objects (S3 and S3-compatible). It is **not** for databases (use DMS) or servers (use MGN).
- **Online** = over network (Internet, VPN, Direct Connect). For slow or no network → Snow Family (closed to new customers) or **Data Transfer Terminal**.

## B. Locations (where you can transfer) (verified)
- **On-premises / self-managed**: **NFS**, **SMB**, **HDFS**, **self-managed object storage** (S3-compatible).
- **AWS storage**: **Amazon S3**, **Amazon EFS**, **Amazon FSx for Windows File Server**, **FSx for Lustre**, **FSx for OpenZFS**, **FSx for NetApp ONTAP**.
- **Other clouds**: **Google Cloud Storage**, **Microsoft Azure Blob Storage**, **Azure Files**, plus S3-compatible stores: Wasabi, DigitalOcean Spaces, Oracle Cloud Object Storage, Cloudflare R2, Backblaze B2, NAVER Cloud, Alibaba Cloud OSS, IBM Cloud Object Storage, Seagate Lyve Cloud.
- A **task** has one **source location** and one **destination location**.
- Transfers can be **same Region**, **cross-Region** (you pay data transfer OUT from the source Region), and **cross-account**.
- Not DataSync: **DynamoDB, RDS, Redshift** → use their own tools.

## C. Core concepts (verified)
- **Agent**: a VM appliance (VMware ESXi, KVM, Nutanix AHV via KVM image, Microsoft Hyper-V, or **EC2 instance**) deployed near your storage; reads/writes on-premises or cloud storage over NFS/SMB/etc.
- **Location**: describes a source or destination (type, path, credentials).
- **Task**: a transfer definition: source, destination, options (mode, filters, schedule, verification).
- **Task execution**: one run of a task.
- Agents are **activated** with an **activation key** and connect to the DataSync service through a **public endpoint**, **FIPS endpoint**, or **VPC (PrivateLink) endpoint**.
- One DataSync **location** can have up to **4 Basic-mode agents** and **4 Enhanced-mode agents**. Multiple agents increase throughput but are **not** high availability (all must be online to run).

## D. When you need an agent (verified)
- **Need an agent**: transfers between AWS storage and **on-premises** storage; between EFS/FSx and **other clouds**; some **cross-account** transfers where neither side is S3; transfers between a commercial Region and **GovCloud** where both sides are EFS/FSx.
- **No agent**: AWS storage ↔ AWS storage in the **same account**; **S3 ↔ other AWS storage across accounts**; **S3 ↔ object storage in other clouds**; commercial ↔ GovCloud when either side is S3.
- Agent type must match task mode: **Basic mode → Basic agent**; **Enhanced mode → Enhanced agent**.
- For millions of small files use **multiple tasks in parallel with one agent each**, or multiple agents per location.
- Agent **requirements** (CPU/RAM/disk) rise with dataset size; for more than 20 million files/objects allocate **at least 64 GB RAM**. (exact VM sizes: verify)

## E. Task modes (verified)
| Capability | Enhanced mode | Basic mode |
|---|---|---|
| Pipeline | Lists, prepares, transfers, verifies **in parallel** | Prepares, transfers, verifies **sequentially** |
| Items per task execution | **Virtually unlimited** objects | **Quotas apply** (25–50 million) |
| Speed | Higher for most workloads | Slower |
| Metrics/counters | More (objects found, prepared, folders) | Fewer |
| Logs | Structured **JSON** | Unstructured |
| Locations | S3 ↔ EFS ↔ FSx Lustre (no agent); NFS/SMB/HDFS ↔ AWS (Enhanced agent); Azure Blob / object storage ↔ AWS (no agent to/from S3) | **All** location types |
| Verification | **Only transferred data** | Verify only transferred, **all data**, or none |
| Task execution concurrency | 120 concurrent Enhanced executions (quota) | — |
- **Cannot change task mode after creation.**
- **FSx for Windows File Server** and some other locations need **Basic mode**.
- Enhanced mode needs `iam:CreateServiceLinkedRole`.
- Choose **Enhanced** whenever supported (large datasets, many objects, S3↔S3, S3↔EFS); choose **Basic** for FSx for Windows/ONTAP/OpenZFS and other unsupported combos.

## F. How a task execution runs (verified)
- Phases: **Launching → Preparing → Transferring → Verifying → Success/Error**.
- **Preparing**: scans source and destination to decide what changed. If you chose **transfer all data**, DataSync doesn't compare, but still scans the source.
- **Skipped items**: unchanged files (when transferring changed data only); items that won't overwrite (overwrite off); **archived S3 objects not restored**; items DataSync cannot read.
- **Verification**: always checksums during transfer; at the end optionally re-verify (see options).
- **Open/locked files**: open files usually transfer; if modified during transfer, verification may flag it → rerun; **locked files are skipped** and logged; DataSync **cannot lock/unlock** files.
- **Special files**: handles symbolic/hard links, directories per documented rules.
- Metrics: bytes/files transferred, throughput, duration, errors; per-task execution history kept **30 days**.

## G. Task options (verified + notes)
- **Transfer mode**: **changed data only** (default; incremental after first run) or **all data**.
- **Overwrite**: whether to overwrite destination files that differ.
- **Deleted files**: option to **remove destination files that no longer exist at source** (keep vs delete) → makes destination mirror the source.
- **Preserve metadata**: POSIX permissions, owner/group IDs (UID/GID), timestamps (mtime/atime), ACLs for SMB, S3 object tags, user metadata, symlinks. Metadata mapping rules differ by location type (NFS↔S3 keeps POSIX info as S3 metadata).
- **Bandwidth limit**: throttle in bytes/sec per task execution (so you don't saturate the link).
- **Include/exclude filters**: pattern lists separated by `|` (for example `*.tmp|/folder/*`); **include** filters match first, then exclude; total up to **102,400 characters**.
- **Manifest**: transfer an **exact list** of files/objects (Enhanced mode manifest up to **20 GB**). Verification with manifest only checks listed items.
- **Verification** (`VerifyMode`):
  - **`ONLY_FILES_TRANSFERRED`** (recommended): checksum compared at the end for just the transferred data. Required for transfers to **S3 Glacier Flexible Retrieval / Deep Archive**.
  - **`POINT_IN_TIME_CONSISTENT`** (verify all data): full compare of source and destination at the end; **not for Enhanced mode**, **not for Glacier classes**; slower on big datasets.
  - **`NONE`**: integrity checks only during transfer.
- **Scheduling**: cron or rate expressions (EventBridge syntax), **minimum interval 1 hour**; can **pause** (Status DISABLED); DataSync may auto-disable a schedule after repeated identical failures or if you disable the Region.
- **Task queueing**: up to **50 queued executions** per task.
- **Task reports**: summary/detailed reports to S3 (what transferred, skipped, failed, verified).
- **Logging**: CloudWatch Logs (levels: OFF, BASIC, TRANSFER); Enhanced mode logs are JSON.
- **S3 destination storage class**: choose per task (Standard, Intelligent-Tiering, IA, One Zone-IA, Glacier Instant/Flexible, Deep Archive…) → put cold data straight into cheaper classes. For Glacier classes use verify-only-transferred; archived objects at the **source** must be restored first.
- **S3 behavior**: S3 "folders" (prefixes) count as directories for quotas in Basic mode.
- **Object tags** (`ObjectTags=PRESERVE/NONE`); transfers to locations without tags fail or report per-object errors depending on mode.

## H. Performance and quotas (verified)
- Throughput per task: up to **10 Gbps** (with an agent); **5 Gbps** (no agent). Real speed depends on network, storage, file sizes.
- Quotas: **100 tasks** per account/Region (adjustable); Basic mode up to **50 million** items (on-prem/other cloud ↔ AWS) or **25 million** (AWS ↔ AWS) per execution, adjustable (or split with filters); **120 concurrent Enhanced mode** executions; **50 queued executions** per task; **30 days** execution history; filter ≤ **102,400** chars.
- File limits: path ≤ **4,096 bytes**; path component ≤ **255 bytes**; S3 object name ≤ **1,024** UTF-8 chars; Windows domain ≤ 253 chars; server hostname ≤ 255 chars.
- Speed tips: **multiple tasks/agents** with partitioned datasets; place agent close to storage; give agent enough RAM; use **Enhanced mode**; avoid tiny-file overhead where possible (tar or combine); use **Direct Connect** or compression-friendly paths; throttle with bandwidth limit if sharing link.
- Large-file and many-file workloads behave differently; test a sample.

## I. Security (verified + notes)
- **In transit**: all data encrypted with **TLS** between agent, service and AWS storage.
- **At rest**: destination services' encryption applies: S3 SSE-S3/SSE-KMS, EFS KMS, FSx KMS. DataSync does not store your data (it passes through).
- **IAM**:
  - Users need DataSync permissions (managed policy `AWSDataSyncFullAccess` or read-only).
  - DataSync assumes an **IAM role** to access **S3 buckets** (S3 location role with trust to `datasync.amazonaws.com`).
  - For **SSE-KMS** buckets the role needs KMS permissions.
  - For cross-account, use bucket policies/roles accordingly.
- **Network isolation**: use **VPC interface endpoints (AWS PrivateLink)** so agent ↔ DataSync control and data traffic never use the public internet; security groups need the required ports (443; 1024–1064 for data when using a VPC endpoint — verify); **FIPS endpoints** for compliance.
- **Credentials** for SMB/object-storage locations can be stored in **Secrets Manager** (service-managed or customer secrets with KMS).
- **Agent activation keys** authenticate an agent to your account; keep them private; activation is Region-bound.
- **Audit**: **CloudTrail** records DataSync API calls; CloudWatch logs for transfers.
- **Least privilege**: scope the S3 role to the specific bucket/prefix.
- Compliance programs apply (HIPAA, PCI, SOC; see services-in-scope page).

## J. Monitoring and troubleshooting
- **CloudWatch metrics** (task execution): bytes transferred, files/objects prepared/transferred/verified, errors, throughput; Enhanced adds folder and discovery counters.
- **CloudWatch Logs** and **task reports** to find failed or skipped items.
- **EventBridge** events for task execution state changes → trigger Lambda/Step Functions (post-processing).
- Typical issues:
  - **Agent offline** → network/firewall, VM stopped, wrong endpoint; the task can't start if any agent is offline.
  - **Permission denied** (NFS/SMB export/ACLs, S3 role) → fix permissions; root squash on NFS.
  - **Task slow** → agent RAM/CPU, network bandwidth, many small files, storage latency.
  - **Verification failures** → file changed during transfer → rerun.
  - **Skipped archived S3 objects** → restore from Glacier first.
  - **Quota exceeded (Basic mode)** → split by prefix with filters or use Enhanced mode.
  - **Schedule auto-disabled** → look at `DisabledReason`.

## K. Cost (verified model)
- **Per-GB** fee for data **copied** (examples in the pricing page: Enhanced mode higher per GB than Basic; Enhanced mode also has a **per-task-execution** fee). No upfront costs or minimums. No charge for the agent itself.
- **S3 request charges** (LIST/GET/PUT/COPY/HEAD) apply on S3 locations.
- **Data transfer**: cross-Region billed as **transfer OUT** from the source Region; other AWS data transfer rules apply; **PrivateLink**, CloudWatch, Secrets Manager charges if used.
- Savings: transfer **only changed data**; exclude junk with filters; avoid repeated full copies; pick the right S3 storage class at destination (avoid extra lifecycle transitions); use the same-Region path when possible.

## L. DataSync vs neighbors (decision lines)
| Need | Pick |
|---|---|
| Online bulk/recurring transfer of files/objects to S3/EFS/FSx | **DataSync** |
| Local file-protocol access to S3 with local cache (hybrid) | **Storage Gateway (File Gateway)** |
| Partners using SFTP/FTPS/FTP/AS2 into S3/EFS | **Transfer Family** |
| Terabytes–petabytes with poor network (offline) | **Snow Family** (closed to new customers) / **Data Transfer Terminal** |
| Database migration | **DMS** |
| Migrate whole servers | **MGN** |
| One-time small copy | `aws s3 sync` / console |
| Continuous S3 → S3 replication | **S3 Replication** (native) |
| Block devices/EBS | Snapshots, MGN |
| Event-driven file arrival processing | **S3 events + Lambda**, Transfer Family workflows |

## Scenarios (if → then, because)
- **If** you must move **200 TB** of **Network File System (NFS)** data from on-premises to **Amazon Simple Storage Service (S3)** over **AWS Direct Connect** and keep it in sync afterwards, **then** use **AWS DataSync**, a managed online transfer service. Deploy a DataSync **agent** (a VM near your storage) and create a **task** in **changed data only** mode with an **hourly schedule**. **This works because** after the first full copy, each run only moves what changed, and DataSync checks data integrity with checksums. With an agent a task can reach up to **10 Gbps**. The catch: the shortest schedule interval is **1 hour**.
- **If** you copy S3 bucket A to bucket B in the **same account**, **then** use **AWS DataSync without an agent** (or **S3 Replication** or **S3 Batch Operations**). **This works because** both sides are AWS storage locations, and DataSync needs no agent for AWS-to-AWS transfers in the same account.
- **If** the dataset has **hundreds of millions** of objects, **then** create the DataSync task in **Enhanced mode**, which lists, prepares, transfers and verifies **in parallel**. **This works because** Enhanced mode handles a virtually unlimited number of objects per run, while **Basic mode** has quotas of **25–50 million** items per execution. The catch: you **cannot change** the task mode after creation.
- **If** the destination is **Amazon FSx for Windows File Server**, **then** create the DataSync task in **Basic mode** with a Basic agent. **This works because** Enhanced mode does not support FSx for Windows File Server, and the agent type must match the task mode.
- **If** the source is **Microsoft Azure Blob Storage** and the destination is **Amazon S3**, **then** use **AWS DataSync without an agent**, in **Enhanced mode**. **This works because** both are cloud object storage, and DataSync can move data between S3 and object storage in other clouds without an agent; Enhanced mode supports Azure Blob to S3.
- **If** you need cold archives to land directly in **S3 Glacier Deep Archive**, **then** set the **S3 destination storage class** to Deep Archive in DataSync and choose the verify mode **`ONLY_FILES_TRANSFERRED`** (check only the transferred data). **This works because** data goes straight into the cheapest class, with no extra Lifecycle moves later. The catch: the "verify all data" mode does not work with Glacier classes, so verify-only-transferred is required.
- **If** the network link is shared with production traffic, **then** set a **bandwidth limit** (in bytes per second) on the DataSync task. **This works because** the limit throttles each task execution so it does not fill the whole link.
- **If** the same source must be read by many agents for more speed, **then** add more agents to the DataSync **location**: up to **4 Basic-mode** and **4 Enhanced-mode** agents per location. **This works because** several agents raise throughput. The catch: this is **not high availability**; all agents must be online, or the task cannot start.
- **If** only a specific list of files should move, **then** give the DataSync task a **manifest**, an exact list of files or objects to transfer. **This works because** DataSync then transfers, and verifies, only the listed items.
- **If** files arrive all the time and must be processed after each transfer, **then** use an **Amazon EventBridge** rule on the DataSync task execution state change to start **AWS Lambda** or **AWS Step Functions**. **This works because** DataSync sends an EventBridge event when a task execution changes state, so post-processing starts as soon as the transfer finishes.
- **If** you need file sync more often than every hour (near real time), **then** do not use **AWS DataSync**; use **AWS Storage Gateway (File Gateway)**, **AWS Transfer Family** or **S3 Replication** for faster flows. **This works because** a DataSync schedule cannot run more often than once per **1 hour**, so it suits bulk or recurring copies, not instant sync.
- **If** agent traffic must never use the public internet, **then** connect the DataSync agent through a **VPC interface endpoint (AWS PrivateLink)** for DataSync. **This works because** both control and data traffic between the agent and DataSync then stay on private AWS networking. Security groups must allow the required ports.
- **If** you need the destination to be an exact mirror that also deletes files removed at the source, **then** turn on the DataSync **deleted files** option (remove destination files that no longer exist at source). **This works because** DataSync then makes the destination match the source. The catch: it is **destructive**, so deleted source files are also lost at the destination.

## Verified from AWS docs on 2026-10-09
Read: what-is page, how-it-works page, choosing task mode, agent need page, verification options page, scheduling page, quotas page, pricing summary, security index page. Not confirmed (verify): agent VM sizes, exact VPC endpoint port range, filter syntax details, S3 storage class list on the location page, task option names beyond those on read pages, auto-disable schedule rules, Enhanced mode agent specifics.

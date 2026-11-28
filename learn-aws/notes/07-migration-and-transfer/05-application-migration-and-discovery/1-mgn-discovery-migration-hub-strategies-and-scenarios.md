# Application Migration and Discovery – MGN, Application Discovery Service, Migration Hub, strategies, status, scenarios

Short notes. Each point is a fact you can be asked about.

## A. The big picture and current status (verified)
- Moving applications to AWS has phases: **assess/discover → plan → migrate → optimize**. AWS has services for each, but several are now **closed to new customers** and pointed toward **AWS Transform**:
  - **AWS Application Migration Service (MGN)** is now called **AWS Transform MGN** in the docs. It is the **primary service for lift-and-shift** of servers. The docs banner says you can now "accelerate your migration and modernization with **AWS Transform**".
  - **AWS Application Discovery Service**: **no longer open to new customers**; use **AWS Transform** for similar capabilities.
  - **AWS Migration Hub**: **no longer open to new customers as of 7 November 2025**; explore **AWS Transform** for similar capabilities.
- Older names you may see in videos/exams: **CloudEndure Migration** and **AWS Server Migration Service (SMS)** were replaced by **MGN**. (SMS retired; verify date.)
- Databases are migrated with **DMS** (see that service), files with **DataSync**, offline bulk with **Snow/Data Transfer Terminal**, SFTP with **Transfer Family**.
- This service folder is mostly **concept-level** for the exam; DEA focuses on data movement, but "which migration service for which asset" questions appear.

## B. The migration strategies ("7 Rs") (general knowledge)
| R | Meaning | Example |
|---|---|---|
| **Retire** | Turn it off | Unused apps |
| **Retain** | Keep where it is for now | Compliance, recently upgraded |
| **Rehost** (lift and shift) | Move as-is to EC2 | **MGN** |
| **Relocate** | Move to AWS with no changes to OS/apps (hypervisor level) | VMware Cloud on AWS, Amazon EVS |
| **Repurchase** | Replace with SaaS/new product | CRM → SaaS |
| **Replatform** (lift, tinker, shift) | Small optimizations | DB → RDS/Aurora via DMS; app server → Elastic Beanstalk |
| **Refactor / re-architect** | Redesign cloud-native | Monolith → microservices/serverless |
- Typical exam mapping: "move servers quickly with minimal change" → **rehost with MGN**; "move DB to managed engine" → **replatform with DMS**; "break up monolith" → **refactor**.

## C. AWS Application Migration Service / AWS Transform MGN (verified)
- Automates migrating **physical, virtual and cloud servers** to AWS with **minimal downtime** (cutover windows typically **minutes**).
- **Continuous block-level replication** of source servers into a low-cost **staging area** in your AWS account, then **converts** them to run natively on EC2 at launch.
- Works across a wide range of OSes (Windows Server, many Linux distributions); supports **IPv4 and IPv6**; works into standard AZs or **Local Zones**.
- **No compatibility/performance disruption** for the source: it replicates at block level in the background.
- Three templates control behavior:
  - **Replication template**: how data replicates (staging subnet, replication server type, EBS volume type, encryption, bandwidth throttling, private connectivity, security groups). Applied to newly added servers (changes don't alter existing servers; per-server overrides allowed).
  - **Launch template**: EC2 launch settings for test and cutover instances (instance type, subnet, security groups, licensing, IAM profile).
  - **Post-launch template**: actions run after launch (install agents, run scripts, SSM documents).
- Manage at scale with **applications** (group of servers) and **waves** (group of applications); run launch/cutover/archive at server, application or wave level.
- **Agent**: install the **AWS Replication Agent** on each source server; it needs outbound connectivity to the AWS endpoints and the replication servers (TCP **443** and TCP **1500** — verify).
- **Replication servers** (small EC2 instances) in a **staging subnet** receive data and write to **EBS staging disks**; one replication server serves multiple source servers (lightweight).
- **Lifecycle** (states): Not ready → Ready for testing → Test in progress → Ready for cutover → Cutover in progress → Cutover complete → (Disconnect) → Archive.
  - **Launch test instances** anytime without stopping replication; validate the app.
  - **Cutover**: final sync, launch production instance; then **finalize cutover** to clean up replication resources (stops replication to save cost).
  - **Disconnect** removes the server from the service; **archive** hides finished servers.
- **Rehost** keeps the same OS/app/IP strategy (you can change networking); then **modernize** using AWS services later (replatform/refactor).
- Related: **AWS Elastic Disaster Recovery (DRS)** uses the same replication technology for **DR**, not migration (keep the idea separate).
- Exam hint: "Minimal downtime migration of on-premises VMs/physical servers to EC2" → **MGN**.
- Pricing (general knowledge, verify): MGN replication is **free for a set period per server (about 90 days)**; you pay for the **staging resources** (replication servers, EBS, snapshots, data transfer) and the migrated EC2 resources.
- Regions: many commercial Regions and GovCloud (doc table).

## D. AWS Application Discovery Service (verified; closed to new customers)
- Collects **usage and configuration data** about on-premises **servers and databases** to plan migrations. Data is stored in your **Migration Hub home Region**.
- **Three ways to collect**:
  1. **Agentless Collector**: OVA deployed in **VMware vCenter**; discovers VMs/hosts; collects static config (hostnames, IPs, MAC addresses, disk allocation), average/peak utilization (CPU, RAM, disk I/O) — **cannot see inside VMs** (no processes). Interval about **60 minutes**.
  2. **Discovery Agent**: installed on each **VM or physical server** (Windows/Linux); collects static config, **time-series performance**, **inbound/outbound TCP connections**, **running processes**; interval about **15 seconds**.
  3. **File-based import**: upload a **Migration Hub import template** or **RVTools export** (single snapshot; no connections or processes).
- **Database and analytics discovery**: Agentless Collector module inventories **Oracle, SQL Server, MySQL, PostgreSQL** (LDAP in Active Directory to find servers) and collects metadata + utilization → used by **DMS Fleet Advisor** for target recommendations and complexity (verify Fleet Advisor status).
- **Network dependency mapping** (agents/collector): shows which servers talk to which → helps **group servers into applications**.
- **Exports**: CSV, or to **Amazon Athena / Amazon Quick** for analysis; cost modeling inputs (EC2 right-sizing recommendations from utilization).
- Works with **partner discovery tools** that write via the public API.
- Limitation for exam: if you need processes and network connections → **agent**; if you only have vCenter and want low effort → **agentless collector**.
- Use `set home region` in Migration Hub before any discovery.

## E. AWS Migration Hub (verified; closed to new customers since 7 Nov 2025)
- A **single place** to **discover servers, plan, and track** migration status of applications, regardless of tool.
- Receives status from **MGN** and **DMS**.
- Requires choosing a **home Region** (stores migration tracking data; you can migrate into any supported Region).
- Related capabilities (old): **Strategy Recommendations** (suggests rehost/replatform/refactor per app), **Refactor Spaces** (incremental refactor of monoliths to microservices), **Orchestrator** (automates workflows for server and enterprise-app migrations, such as SAP).
- Replacement path: **AWS Transform**.

## F. Other tools (awareness)
- **Migration Evaluator** (formerly TSO Logic): builds a **business case** and right-sizes cost from on-prem inventory (verify availability).
- **AWS Transform**: AI-driven service for **migrating and modernizing** (VMware workloads, .NET, mainframe, etc.) and for discovery/planning that replaces Migration Hub/Application Discovery for new customers. (details: verify)
- **VMware Cloud on AWS / Amazon Elastic VMware Service (EVS)**: run VMware workloads on AWS (relocate).
- **AWS Mainframe Modernization**: migrate/refactor mainframe apps.
- **AWS Backup / snapshots / AMI import (VM Import/Export)**: image-based moves of single VMs to EC2.
- **AWS DMS Fleet Advisor**: database inventory.
- **CloudEndure Disaster Recovery** → **Elastic Disaster Recovery**.

## G. Putting it together (typical migration plan)
1. **Discover** (Agentless Collector/Agent or import) → inventory + dependencies. *(For new customers: AWS Transform.)*
2. **Group** servers into applications; choose strategy (7 Rs).
3. **Replicate** servers with **MGN**; migrate databases with **DMS**; move file shares with **DataSync**.
4. **Test** launched instances; fix issues; **cutover** in waves.
5. **Finalize/cleanup**; decommission on-prem.
6. **Optimize** (right-size, managed services, refactor).

## H. Security notes (general)
- MGN agents use **TLS** to send data; staging EBS volumes can be **KMS encrypted**; use **private connectivity** (VPN/Direct Connect) and security groups to restrict replication traffic.
- IAM roles/policies control who can add servers, launch instances, and edit templates; **CloudTrail** logs actions.
- Discovery data sits in Migration Hub home Region; restrict with IAM; encrypt exports in S3.

## I. Common traps
- Using **DMS** to move whole servers or **MGN** to move databases with ongoing replication into managed engines (use DMS for DB engines).
- Forgetting **cutover finalization** → replication keeps costing.
- Choosing the **Agentless Collector** when you need process or network dependency details.
- Setting up discovery before choosing a **Migration Hub home Region**.
- Assuming Application Discovery Service or Migration Hub are available to **new customers** (closed).
- Confusing **MGN** (migration) with **Elastic Disaster Recovery** (DR).
- Rehosting without sizing (use utilization data to right-size EC2).

## J. Decision lines (exam style)
- "Lift-and-shift VMs/physical servers with minimal downtime" → **MGN**.
- "Inventory VMware VMs without installing anything on them" → **Agentless Collector**.
- "See running processes and network dependencies" → **Discovery Agent**.
- "Track many migrations in one place" → **Migration Hub** (legacy) / **AWS Transform**.
- "Move database with continuous replication" → **DMS**.
- "Break a monolith into microservices step by step" → **Refactor Spaces** (legacy) / refactor strategy.
- "Business case for migration" → **Migration Evaluator**.
- "AI-assisted modernization of .NET/mainframe/VMware" → **AWS Transform**.

## Scenarios (if → then, because)
- **If** **300** on-premises VMware servers must move to Amazon EC2 with only **minutes** of downtime, **then** use **AWS Application Migration Service (MGN)**, now called **AWS Transform MGN**, the main lift-and-shift (rehost) service. Install the **AWS Replication Agent** on each server. It copies the disks into a low-cost **staging area** in your account. Launch **test instances** to check the app, then **cut over** group by group in **waves** (a wave is a group of applications), and **finalize** each cutover. **This works because** MGN uses **continuous block-level replication** in the background, so the source keeps running, and at cutover it only does a final sync and **converts** the servers to run natively on EC2.
- **If** you cannot install software on the VMs but you have **VMware vCenter** access, **then** use the **Agentless Collector** of **AWS Application Discovery Service** (a tool that collects data about on-premises servers to plan a migration). **This works because** it runs as an appliance (OVA) inside vCenter and reads each VM's config (hostnames, IPs, disks) and average/peak **CPU, RAM and disk I/O** use. The catch: it **cannot see inside VMs** (no processes or connections), and the service is **closed to new customers**.
- **If** you need to group servers into applications by **who talks to whom**, **then** install the **Discovery Agent** of **AWS Application Discovery Service** on each VM or physical server. **This works because** the agent records **inbound and outbound TCP connections** and **running processes**, which build a **network dependency map** showing which servers belong together. The Agentless Collector cannot do this, because it cannot see inside VMs.
- **If** the Chief Financial Officer (CFO) wants a cost estimate before migrating, **then** collect server **utilization** with **AWS Application Discovery Service**, **export** it (CSV, or to **Amazon Athena** or **Amazon Quick** for analysis) and use its **EC2 right-sizing** recommendations; or use **Migration Evaluator** (formerly TSO Logic) to build a **business case** (availability: verify). **This works because** real utilization shows how big each EC2 instance needs to be, so the estimate is not based on oversized on-premises hardware.
- **If** a new customer asks for **AWS Migration Hub**, **then** tell them it is **closed to new customers since 7 November 2025** and to use **AWS Transform**, which now covers discovery, planning and migration tracking (exact feature scope: verify).
- **If** cutover is done but MGN costs continue, **then** **finalize the cutover**. **This works because** finalizing **stops replication** and cleans up the replication resources (the **replication servers** and **EBS staging disks**), which you pay for until they are removed.
- **If** a legacy app must move together with its **Oracle** database to **Amazon Aurora**, **then** split the job: use **AWS Application Migration Service (MGN)** to rehost the **app servers** on EC2, and **AWS Database Migration Service (DMS)**, with its schema conversion (see the DMS notes), to move the **database**. **This works because** MGN copies whole servers as they are, while moving a database into a managed engine like Aurora is a **replatform** job with ongoing replication, which is what DMS does. Using MGN for the database is a common trap.

## Verified from AWS docs on 2026-10-09
Read: MGN overview page ("AWS Transform MGN"), Application Discovery Service overview page, Migration Hub overview page. MGN replication settings and lifecycle pages came back as outlines (general knowledge used). Not confirmed (verify): MGN ports (443/1500), free replication period, replication server defaults, exact lifecycle names, Migration Evaluator availability, AWS Transform feature scope, SMS retirement date, Fleet Advisor status, Discovery Agent/collector collection intervals.

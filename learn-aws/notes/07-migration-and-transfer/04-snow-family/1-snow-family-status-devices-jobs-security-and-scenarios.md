# Snow Family – Offline bulk data transfer and edge devices: status, devices, jobs, security, cost, alternatives, scenarios

Short notes. Each point is a fact you can be asked about.

## A. Status first (verified)
- **AWS Snowball Edge is no longer available to new customers** (AWS docs banner on the Snowball Edge guide). AWS points new customers to:
  - **AWS DataSync** for **online** transfers,
  - **AWS Data Transfer Terminal** for **secure physical transfers** (you bring your own storage devices to a terminal),
  - **AWS Partner** solutions,
  - **AWS Outposts** for **edge computing**.
- Existing customers may continue to use Snowball Edge; check the current availability notice before relying on it in new designs.
- **Snowcone** and **Snowmobile** are also part of the original Snow Family; their current availability needs checking in the docs (verify). Treat the whole family as **legacy / wind-down** in exam and design answers unless the question clearly says a Snow device is already in use.
- Older exam questions still ask: "petabytes, weak network, weeks to transfer online" → **Snow Family**. Know the concept and the modern replacement.
- This repo's CLAUDE.md already flags the Snow wind-down.

## B. What the Snow Family is (concepts)
- Physical, rugged, **tamper-evident**, **encrypted** devices that AWS **ships to you**. You load data, ship it back, and AWS **imports it into S3** (offline transfer).
- Also used to **run compute and storage at the edge** where there is little or no connectivity (ships, mines, remote sites, military).
- Three problems it solves:
  1. **Bulk migration** when network transfer would take too long or costs too much.
  2. **Edge processing** (pre-process/filter data before it ever reaches the cloud).
  3. **Disconnected operations** and data collection in harsh environments.

## C. Devices (general knowledge; verify numbers)
- **Snowball Edge Storage Optimized**: large local storage (about **80 TB** usable on the standard model; a **210 TB** NVMe variant exists), optional compute (EC2-compatible instances), 10/25/40/100 Gb network ports (varies).
- **Snowball Edge Compute Optimized**: many vCPUs, large memory, optional **GPU**, smaller storage (for example up to ~28 TB NVMe usable); for ML inference and edge applications.
- **Snowcone**: tiny (about 4.5 lb), **8 TB HDD or 14 TB SSD**, 2 vCPUs, battery-capable; can use **DataSync agent** pre-installed to send data online or ship back offline.
- **Snowmobile**: a 45-foot shipping container truck for **exabyte-scale** moves (up to ~100 PB per Snowmobile). (Retirement status: verify.)
- Devices can be used **standalone** or in **clusters** (for example 5–10 Snowball Edge devices) for higher durability and capacity (cluster quorum protects data if a device fails).
- Typical rule: a single Snowball Edge fits tens of terabytes; use multiple devices in parallel for petabytes.

## D. Job types and flow (general knowledge; verify details)
- **Import into S3**: you fill the device; AWS loads data into your S3 bucket.
- **Export from S3**: AWS loads data from S3 onto the device and ships it to you.
- **Local compute and storage**: use the device at the edge (EC2-compatible instances, Lambda-style functions, S3-compatible storage, NFS).
- Flow for an import job:
  1. **Create a job** in the console (choose device, S3 bucket, KMS key, IAM role, shipping address).
  2. **Receive** the device; power on; connect to your network.
  3. **Get credentials**: download the **job manifest** and **unlock code** from the console/CLI.
  4. **Unlock** the device with the Snowball Edge client/OpsHub.
  5. **Copy data** using the **S3 interface** (S3-compatible endpoint on the device; use AWS CLI/SDK) or **NFS** or the **Snowball client** tools.
  6. **Ship back**: the **E Ink shipping label** automatically shows the return address; carrier delivers to AWS.
  7. AWS **imports** to S3 and **erases** the device (NIST 800-88 media sanitization).
  8. Track status via console, SNS notifications, CloudWatch events.
- **AWS OpsHub**: GUI to manage devices, copy files, monitor.
- Time: expect days to weeks end-to-end (shipping + loading + import).

## E. Security (verified headline + general knowledge)
- Data is **encrypted** on the device with **256-bit** keys that are managed with **AWS KMS**; keys are **not stored on the device**.
- The **unlock code** and **manifest** are needed to read data; they travel separately from the device.
- **Tamper-resistant** enclosure; **Trusted Platform Module (TPM)** to detect tampering.
- **E Ink shipping label** prevents wrong shipments; **tracking** with SNS/text notifications.
- After import, AWS **sanitizes** the device (NIST 800-88).
- **IAM** controls who can create jobs; an **IAM role** lets the job write to your S3 bucket; **CloudTrail** logs API calls.
- Use **KMS customer managed keys** for control; use **VPC/private network** for loading data inside your site.
- Physical custody: keep the device in a locked room and follow your site's chain-of-custody rules.

## F. Data Transfer Terminal (modern physical alternative) (verified summary)
- A **physical site** where you **bring your own storage devices** and upload to **any AWS endpoint (S3, EFS…)** over a very fast connection.
- You **reserve a time slot** at a nearby terminal in the console; you **keep custody** of your devices the entire time.
- Good for: high-resolution media from poor-connectivity sites, **automotive test-fleet sensor data**, IoT data from remote sites, legacy data migration while keeping custody.
- Availability depends on terminal locations.

## G. How to choose a transfer method (decision table)
| Situation | Pick |
|---|---|
| Good network (Direct Connect/internet), recurring or one-time file/object transfer | **DataSync** |
| Partners push files by SFTP/FTPS/FTP/AS2 | **Transfer Family** |
| Databases | **DMS** |
| Entire servers | **MGN** |
| Local protocol access with cache to S3 | **Storage Gateway** |
| Tens or hundreds of TB, weak/expensive network, you can ship | **Snow Family** (if available to you) or **Data Transfer Terminal** |
| Edge compute needed | **Outposts** (current) / Snowball Edge compute (legacy) |
| One-time small data | S3 console/CLI |
- **Network time math** (exam style): data ÷ usable bandwidth. Example: 100 TB over 1 Gbps at 80% efficiency ≈ ~11–12 days; over 100 Mbps ≈ ~110 days. If the time or cost is too high → offline option.
- Mix methods: **Snow for the bulk first**, then **DataSync/DMS CDC for the delta** until cutover.

## H. Cost model (general knowledge; verify)
- **Per-job service fee** per device (with a number of included on-site days, e.g., about 10 days for Snowball Edge), **extra day charges** beyond included time.
- **Shipping** charged (carrier rates).
- **Data transfer into S3: free.** Export from S3 follows standard S3 retrieval/transfer rules.
- Compute options billed for time/usage on device (edge workloads).
- Compared with network: no per-GB transfer fee, but time and logistics.
- Costs go up if the device sits at your site too long; plan data staging ahead.

## I. Limits and numbers (verify)
- Device capacity (see section C); cluster size 5–10 (Snowball Edge).
- S3 object size limits still apply on import (verify per job).
- The **job manifest** and **unlock code** are required to unlock.
- Throughput depends on network ports, file sizes, and parallel copies; many small files are slow → archive/batch them.
- Data on the device is protected only as long as keys remain with you and KMS; losing KMS access prevents import.

## J. Common traps
- Choosing Snow for **small** or **fast-network** transfers (DataSync is simpler).
- Forgetting **network time math**: Snow only wins when online transfer takes too long.
- Assuming Snow is open to **new customers** today (Snowball Edge is closed).
- Expecting Snow to replicate **ongoing changes** (no CDC; use DataSync/DMS after bulk load).
- Copying tiny files individually (slow) instead of batching.
- Losing the unlock code/manifest or KMS key access.
- Forgetting export jobs need S3 permissions and a role.
- Confusing Snow Family (offline devices) with **DataSync** (online) and **Transfer Family** (SFTP).

## Scenarios (if → then, because)
- If you must move 500 TB from a remote site with a 50 Mbps link → offline method (Snow device if available, or Data Transfer Terminal / partner), because online would take years.
- If you need ongoing sync after the bulk load → DataSync or DMS for the delta, because Snow is one-time.
- If a new customer asks for a Snowball Edge in 2026 → explain it is closed to new customers; offer DataSync (online), Data Transfer Terminal (physical), or partners.
- If a ship must run ML inference with no internet → edge compute (Outposts or legacy Snowball Edge Compute Optimized).
- If security demands that keys never be on the device → Snow uses KMS-managed keys with unlock code and manifest delivered separately.
- If compliance wants proof the device was wiped → NIST 800-88 sanitization after import.
- If a job needs data exported from S3 to an isolated lab → export job to a device, then unlock on site.

## Verified from AWS docs on 2026-10-09
Read: Snowball Edge security page (banner stating no longer available to new customers), Data Transfer Terminal overview page. The "what is Snowball", "device types" pages returned only outlines, so device specs, flow, security details, pricing and Snowcone/Snowmobile status are general knowledge. Not confirmed (verify): current availability of Snowcone and Snowmobile, device capacities and vCPU counts, included on-site days, cluster sizes, NIST sanitization wording, OpsHub details.

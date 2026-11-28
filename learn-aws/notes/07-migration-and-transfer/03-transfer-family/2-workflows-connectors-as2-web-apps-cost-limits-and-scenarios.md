# Transfer Family – 2. Managed workflows, connectors, AS2, web apps, monitoring, cost, limits, scenarios

Short notes. Each point is a fact you can be asked about.

## A. Managed workflows (post-upload processing) (verified)
- A **managed workflow** runs automatically **after a file is uploaded** over SFTP, FTPS or FTP. It orchestrates processing without servers.
- Purposes: preprocess data before downstream apps; meet B2B compliance; end-to-end **audit and visibility**.
- Built-in (**nominal**) steps:
  - **Copy** file to another location (can rename, overwrite).
  - **Decrypt** (PGP) file.
  - **Tag** the file (S3 object tags).
  - **Delete** the original.
  - **Custom** step: call an **AWS Lambda** function for scanning, validation, transformation, notifications.
- **Exception-handling steps**: run if a nominal step fails (for example send an alert, quarantine). A custom Lambda step triggers the exception path by returning `Status="FAILURE"`.
- Two workflow hooks on a server: **OnUpload** (complete upload) and **OnPartialUpload** (session dropped early).
- Needs a **workflow execution role** that Transfer Family assumes (S3/EFS, Lambda invoke, KMS as needed).
- Deployable through **IaC** (CloudFormation templates) to standardize across business units.
- Each step writes detailed logs to CloudWatch for lineage.
- **Limits and rules** (verified):
  - **10 workflows** per Region per account.
  - **8 steps** per workflow.
  - **50 tags** per workflow.
  - Custom step max timeout **30 minutes** (approximate).
  - **250 concurrent executions** with a decrypt step per workflow.
  - Decrypted file max **10 GB**; max **3 PGP private keys** per server per user.
  - Throttling: token bucket, burst **100**, refill **1**; throttled executions are **not queued**.
  - **Same Region** for S3 buckets and the workflow; **no cross-account / cross-Region Lambda**; decrypt destination must match source type and Region.
  - Only **asynchronous custom steps**.
  - **Zero-byte files do not start workflows.**
  - **AS2 messages do not run workflows** even if one is attached.
  - After replacing a workflow or changing the execution role, wait about **10 minutes** (cache) and **re-login** SFTP sessions.
- Use **S3 events + Lambda/Step Functions/EventBridge** when you need more complex orchestration than 8 steps.

## B. SFTP connectors (verified summary + notes)
- **Connectors** let Transfer Family act as the **client**: **send** files to and **retrieve** files from **remote SFTP servers** (partners, banks) with **no custom code**, from/to S3.
- Features:
  - **Credentials in Secrets Manager** (username/password or private key), not in config.
  - **Trusted host keys**: connector connects only to servers you approve (prevents man-in-the-middle).
  - **VPC egress**: send traffic through your VPC (static IPs via NAT, private partner networks).
  - **Directory listing** of remote paths.
  - **EventBridge** notifications for transfer results.
- Typical design: scheduled EventBridge rule → `StartFileTransfer` (send) or retrieve → S3 → workflow/Lambda processing.
- Use with **PGP encryption** steps for compliant managed file transfer.
- Contrast: **server** = partners connect to you; **connector** = you connect to partners.

## C. AS2 (B2B/EDI messaging) (general knowledge, verify)
- **AS2** securely exchanges business documents over HTTP/HTTPS with **signing**, **encryption** and **MDN receipts**.
- **S3 only** (EFS not supported).
- Concepts: **local profile** (your AS2 ID), **partner profile**, **certificates** (signing and encryption, X.509), **agreement** (links local + partner profiles to a base S3 directory and access role), **connector** (outbound AS2), **MDN** (message disposition notification, sync or async).
- Algorithms: signing (SHA-256 etc.), encryption (AES-256), optional compression.
- Use for retail/healthcare/logistics partners that mandate AS2 (EDI X12/EDIFACT payloads inside).
- AS2 inbound goes to the server's AS2 endpoint (HTTP/HTTPS) in a VPC endpoint; workflows don't run for AS2 messages.
- Feed EDI payloads in S3 to **AWS B2B Data Interchange** for EDI translation (verify service naming).

## D. Transfer Family web apps (verified summary + notes)
- A **web app** is a **fully managed browser UI** for end users to **browse, upload and download** data in **S3** (no client software).
- Identity via **IAM Identity Center**; access scoped with **S3 Access Grants** (so users see only what they are granted); can be branded/customized.
- Use for centralized, simple access to S3 for a wide business audience; visualize Access Grants in a managed interface.
- Different from SFTP servers: no protocol clients needed.

## E. Security (verified + notes)
- **Authentication**: service-managed SSH keys, AD, or custom IdP (Okta, Cognito, Entra ID…). Add MFA through the IdP.
- **Authorization**: per-user **IAM role** + **session policy**; home directory; logical directories; S3 Access Points/Grants.
- **Network**: VPC endpoints; **security groups** with partner CIDRs; **Elastic IPs**; **AWS WAF** + **API Gateway** in front of a custom IdP (blocks bad IPs/rate limits).
- **Encryption**: SFTP/FTPS/AS2/HTTPS in transit; **KMS** (SSE-KMS) for S3/EFS at rest; PGP workflow decryption.
- **Security policies** (cipher suites) – pick current; **FIPS** options.
- **Host keys** protect clients from rogue servers.
- **Malware scanning**: integrate **GuardDuty Malware Protection for S3** or a custom Lambda step.
- **Least privilege** roles; separate buckets/prefixes per partner; S3 bucket policies; Block Public Access.
- **Audit**: **CloudTrail** (API calls), **CloudWatch Logs** (per-session/transfer logs), S3 server access logs/CloudTrail data events for object access.
- **Secrets**: store passwords/keys in Secrets Manager; rotate.
- Tips from AWS: restrict protocols, use SFTP, restrict source IPs, enable logging, keep identity provider hardened, regularly review users.

## F. Monitoring and troubleshooting
- **CloudWatch metrics** per server: bytes in/out, files in/out, auth failures, workflow success/failure counts, etc.
- **CloudWatch Logs**: needs a logging role; use to see logins, commands, errors; filter by user/session ID.
- **Common problems**:
  - **Cannot connect** → wrong endpoint type, security group, firewall, DNS, host key changed, ports (22, 21, 990, 8192–8200).
  - **Permission denied / Couldn't canonicalize** → role lacks S3/EFS access, wrong home directory, EFS POSIX permissions.
  - **Authentication failed** → wrong key format, key not added, custom IdP Lambda returns empty, Lambda not allowed to be invoked.
  - **Home directory not found (EFS)** → create the user's folder.
  - **S3 rename/append quirks** → S3 has no native rename or append.
  - **Workflow not running** → 10-minute cache, zero-byte file, role missing, quota throttling, region mismatch.
  - **FTPS handshake fails** → certificate hostname mismatch/expired.
  - **Slow cross-continent uploads** → use Global Accelerator, closer endpoints (latency-based DNS).
- **Alarm** on failed authentications, workflow failures, and unusual transfer volumes.

## G. Cost (verified model summary; numbers verify)
- **Per protocol per hour** while a server **endpoint exists** (SFTP, FTPS, FTP, AS2 each billed).
- **Data transferred** (uploaded and downloaded) per GB through the protocol.
- **AS2**: per message charges.
- **Connectors**: per file/message transfer and data.
- **Workflows**: per step/execution charges (verify).
- **Web apps**: per hour per web app plus per-user/transfer charges (verify).
- **VPC endpoint** charges, Elastic IP, NAT, data transfer, CloudWatch Logs, S3/EFS storage and requests, Lambda.
- Cost tips: delete idle servers; enable only needed protocols; one server for many partners (users) instead of many servers; use S3 lifecycle to archive; avoid unnecessary workflows; use SFTP over FTP.

## H. Limits and numbers to remember
- Protocol versions: **SFTP v3**.
- FTP/FTPS data ports **8192–8200**; SFTP **22**; FTPS control **21**/**990** (verify); AS2 HTTPS.
- Up to **3 AZs** per server endpoint.
- Service-managed **logical directory entries: 2,000**.
- Username length **3–100**.
- Workflows: **10/Region**, **8 steps**, custom step **30 min**, **250** decrypt concurrency, decrypted file **10 GB**, **3 PGP keys**/user/server, burst **100**/refill **1**.
- Workflow cache refresh **~10 minutes**.
- Quotas for servers per account, users per server, connectors, session timeouts: see Service Quotas (not retrieved; verify).

## I. Common traps
- Public endpoint with FTPS/FTP (not supported) or expecting fixed IPs on a public endpoint.
- Using service-managed users and expecting passwords.
- Forgetting the Lambda invoke permission for custom IdPs.
- Giving every partner the same IAM role without session policies (data bleed).
- Leaving **FTP** exposed.
- Assuming AS2 supports EFS or runs workflows.
- Assuming workflows run for empty files or partial uploads automatically (OnPartialUpload is separate).
- Expecting S3 to support rename/append like a file system.
- Leaving test servers running (hourly billing).
- Not opening the data port range 8192–8200 for FTP/FTPS.

## J. Decision lines (exam style)
- "Partners send files by SFTP and you want them in S3 with no servers" → **Transfer Family**.
- "Fixed IP for partner allow-list" → **VPC internet-facing endpoint + Elastic IPs**.
- "Authenticate against corporate AD" → **Directory Service identity provider**.
- "Authenticate against Okta/Cognito or custom DB" → **custom identity provider (Lambda/API Gateway)**.
- "Isolate each customer to their folder" → **home directory + restricted/session policy**, **logical directories**.
- "Decrypt PGP files after upload and tag them" → **managed workflow**.
- "Pull files from a partner's SFTP on a schedule" → **SFTP connector + EventBridge**.
- "EDI between trading partners" → **AS2**.
- "Business users upload via a browser" → **web apps**.
- "Bulk historic migration" → **DataSync** (not Transfer Family).

## Scenarios (if → then, because)
- **If** uploads must be **virus-scanned** before the data enters the data lake, **then** attach a **managed workflow** with a **custom step** that calls an **AWS Lambda** function to scan the file, plus an **exception-handling step** that moves bad files to a quarantine location; or use **Amazon GuardDuty Malware Protection for S3** to scan uploaded files. **This works because** a managed workflow runs **automatically after every upload**, and a Lambda step that returns `Status="FAILURE"` starts the exception path. The catch: zero-byte files never start a workflow.
- **If** a bank requires you to **pull statements nightly** from **their SFTP server**, **then** use a **Transfer Family SFTP connector** with the login stored in **AWS Secrets Manager**, the bank's **trusted host key**, and an **Amazon EventBridge** scheduled rule that starts the transfer into **Amazon S3**. **This works because** a connector makes Transfer Family the **client**, so you need no custom code. Secrets Manager keeps credentials out of config, and the trusted host key lets the connector connect only to the real bank server, preventing man-in-the-middle attacks.
- **If** partners **cannot change the hostname** they connect to, **then** create a **custom hostname** in **Amazon Route 53** that points to the Transfer Family endpoint, and **import the old host key**. **This works because** partners keep the same DNS name, and the same host key means their clients do not warn about a changed server identity.
- **If** **authentication failures** suddenly increase, **then** check **Amazon CloudWatch Logs** for the user and source IP, review the **custom identity provider** function, and put **AWS WAF** (web application firewall) in front of the **Amazon API Gateway** that fronts the custom IdP to block bad IPs and rate-limit. **This works because** CloudWatch Logs show logins and errors per user and session, and WAF protects the IdP API from attack traffic. Set a CloudWatch alarm on auth failures.
- **If** a **workflow does not start** after an upload, **then** check whether the file was **zero bytes**, or whether the workflow or execution role was just changed: wait about **10 minutes** and **log in again**. **This works because** zero-byte files never start workflows, and workflow settings are **cached** for about 10 minutes.
- **If** uploads from **overseas partners** are slow, **then** use **AWS Global Accelerator** with a VPC endpoint (verify), or run servers in closer Regions with **latency-based routing** in **Amazon Route 53**. **This works because** Global Accelerator carries traffic over the AWS network, and latency-based DNS sends each partner to the nearest endpoint.
- **If** compliance requires encryption **with your own keys**, **then** use **AWS Key Management Service (KMS)** encryption (**SSE-KMS**) on the Amazon S3 bucket or Amazon EFS file system, and give each user's **IAM role** permission to use the KMS key. **This works because** data is then encrypted at rest with keys you control; without KMS permissions in the role, the user's uploads and downloads fail.
- **If** a partner uses a **very old FTP client**, **then** enable **FTP** only on an **internal VPC endpoint**, never exposed publicly. **This works because** FTP is **unencrypted**, so it should run only inside private networks.

## Verified from AWS docs on 2026-10-09
Read: What is Transfer Family page, workflows page (including limits), service-managed users page. Server creation, custom IdP, connectors, AS2, limits and pricing pages returned outlines/404; those sections use general knowledge. Not confirmed (verify): connector/AS2/web-app feature details and pricing items, security policy names, FTPS control ports, quotas for servers/users/connectors, B2B Data Interchange relationship, whether OFFLINE servers still bill.

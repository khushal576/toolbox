# Transfer Family – 1. What it is, protocols, servers and endpoint types, identity providers, users, storage and access

Short notes. Each point is a fact you can be asked about.

## A. What it is (verified)
- **AWS Transfer Family** is a **fully managed file-transfer service**. Partners and apps use ordinary file-transfer clients; your files land in **Amazon S3** or **Amazon EFS**.
- Supported protocols:
  - **SFTP** (SSH File Transfer Protocol, **version 3**).
  - **FTPS** (FTP over TLS).
  - **FTP** (plain, unencrypted).
  - **AS2** (Applicability Statement 2, for B2B/EDI).
  - **Browser-based transfers** (Transfer Family **web apps**).
- You keep **existing client configurations** (authentication, access, firewalls); nothing changes for partners → easy **migration of on-prem SFTP/FTP servers**.
- No servers to run: **scales in real time**, built on an auto scaling, redundant fleet across up to **3 AZs**.
- Backing stores: **S3** (all protocols) and **EFS** (SFTP/FTPS/FTP; **not AS2**).
- Common use cases:
  - **S3 data lakes** fed by vendors/partners over SFTP.
  - **Subscription-based data distribution** to customers.
  - **Internal transfers** between teams.
  - **EFS**: data distribution, supply chain, content management, web serving.
  - **AS2**: compliance-heavy B2B (supply chain logistics, payments, ERP/CRM integrations).
  - **Web apps**: give business users simple browser access to S3 data without a client.
- FTP/FTPS **data channel ports**: **8192–8200** (open these on security groups/firewalls).
- Works with standard clients: OpenSSH, WinSCP, Cyberduck, FileZilla, and scripts.
- Pay only for what you use: no upfront cost.

## B. Why use it instead of running your own SFTP server
- No patching, capacity planning, HA clustering or storage management.
- Data lands directly in **S3/EFS** → immediately usable by **Athena, Glue, Lambda, EMR, Redshift, QuickSight**.
- Integrated **IAM, KMS, CloudWatch, CloudTrail, VPC, Route 53, WAF/API Gateway** options.
- **Managed workflows** process files after upload (copy, decrypt, tag, custom Lambda).
- Pairs with **Storage Gateway** (File Gateway) for local-protocol access, and with **DataSync** for bulk copies.

## C. Servers and protocols (verified + notes)
- A **server** is the endpoint that accepts connections. One server can enable **multiple protocols** at once (SFTP, FTPS, FTP, AS2).
- **SFTP**: works on **all endpoint types**; SSH key or password authentication depending on identity provider.
- **FTPS**: needs an **ACM certificate** and a **VPC endpoint** (not public endpoint).
- **FTP**: **VPC only**, **unencrypted** — use only inside private networks or when legacy systems demand it.
- **AS2**: S3 only; uses certificates, profiles, agreements, connectors (see file 2).
- **Security policy**: choose a `TransferSecurityPolicy-*` version to control allowed ciphers, key exchange algorithms and MACs (use a recent or FIPS policy for compliance).
- **Host key** (SFTP): the server's identity; AWS generates one or you **import your own** so clients' known_hosts do not change after migration.
- **Custom hostname**: map `sftp.example.com` to the server via **Route 53** alias/CNAME (or another DNS). For FTPS the certificate must match the hostname.
- **Logging**: give the server an **IAM logging role** to send logs to **CloudWatch Logs**.
- **FIPS** endpoints and security policies available in supported Regions.
- **Server state**: ONLINE, OFFLINE, STARTING, STOPPING.
- **Delete** servers you no longer need. Billing is **hourly per enabled protocol** while the server exists; whether an OFFLINE server still bills (verify).

## D. Endpoint types (verified general knowledge; verify details)
| Type | Reachability | Protocols | Notes |
|---|---|---|---|
| **Public** | Internet; AWS-managed IPs that can change | **SFTP only** | No VPC, no security groups, no Elastic IPs; simplest; cannot allow-list fixed IPs |
| **VPC – internet-facing** | Internet through Elastic IPs in your VPC | SFTP, FTPS, FTP | **Fixed IPs** (Elastic IPs) for partner allow-lists; security groups control access |
| **VPC – internal** | Only inside the VPC / connected networks (VPN, Direct Connect, peering) | SFTP, FTPS, FTP | Private IPs; for internal and hybrid transfers |
- VPC endpoints let you use **security groups** (restrict by partner CIDR), **NACLs**, **Elastic IPs**, and **AWS WAF** (via Network/Application setups, verify) and support **Global Accelerator** for better throughput for distant users.
- Servers span **up to 3 AZs** (choose subnets); use **latency-based Route 53** records for multi-Region designs.
- Older endpoint type **VPC_ENDPOINT** (PrivateLink only) was replaced by **VPC**; AWS recommends migrating to **VPC**.
- Use **elastic IPs** when partners ask for a static IP allow-list.
- To meet "no internet exposure": **VPC internal** endpoint + VPN/Direct Connect.

## E. Identity providers (who can log in) (verified)
- **Service managed**: users and **SSH public keys** stored in Transfer Family itself. For **SFTP only** (SSH key auth). Simple; good for few partners. Limit: **2,000 logical directory entries** per user.
- **AWS Directory Service for Microsoft Active Directory**: authenticate users/groups from AD (SFTP/FTPS/FTP with passwords); map **AD groups** to access roles.
- **Custom identity provider**: you call your own system using **AWS Lambda** or **Amazon API Gateway (+ Lambda)** — works with **Okta, Azure AD/Entra, Cognito, Secrets Manager, DynamoDB**, any LDAP/SSO.
  - Transfer Family sends **username, password (empty for key auth), server ID, protocol, source IP**.
  - Your function returns a **response**: IAM **Role**, **HomeDirectory** (PATH or LOGICAL + `HomeDirectoryDetails`), optional **Policy** (session policy), **PublicKeys** (for key auth), **PosixProfile** (EFS UID/GID). Empty `{}` = deny.
  - Use for **password-based SFTP**, MFA, dynamic users, IP-based checks, multiple tenants.
  - Lambda needs a resource policy allowing `transfer.amazonaws.com` to invoke it.
- Key rule: **service managed users cannot use passwords** (SFTP keys only); for passwords use custom IdP (Lambda/API Gateway) or AD.
- **Source IP allow lists** can be enforced in the custom IdP function (exam skill 1.1.8: create IP allowlists for data sources) or by security groups on VPC endpoints.

## F. Users, access and home directories (verified)
- Each user maps to an **IAM role** (what AWS resources they may touch) plus optional **session policy** (extra limit), and a **home directory**.
- **Username rules**: 3–100 characters; letters, digits, `_ - . @`; cannot start with `-`, `.`, `@`.
- **Home directory**: where the user lands. Use a path that includes the username (for example `/bucket/home/${Transfer:UserName}`) so one **session policy** (policy variables) can isolate users.
- **Restricted** (chroot): user cannot see or navigate above the home directory and cannot see the bucket name. Home directory + restricted is usually enough; add a session policy for extra control. If **Restricted**, you cannot choose "auto-generate policy based on home folder".
- **Logical directories** (virtual folders): map friendly paths (`/`, `/inbox`) to real S3/EFS paths; hide bucket structure; one user can see multiple buckets/prefixes. Service-managed users: max **2,000** entries.
- **Session policy**: JSON policy limiting the role further; can use `${transfer:HomeBucket}`, `${transfer:HomeFolder}`, `${transfer:UserName}`.
- **Fine-grained S3 access**: use **S3 Access Points** or **S3 Access Grants** (also used by web apps) for large multi-tenant designs.
- **EFS users**: need **POSIX UID/GID** (and secondary GIDs). First admin user can be UID 0 / GID 0. Role must allow EFS client mount/write. "Restricted" breaks symlink resolution for EFS users.
- **Cross-account S3**: use bucket policy + role trust (documented pattern).
- **SSH keys**: service-managed users upload **public keys** (RSA, ECDSA, ED25519; validated by service); users can rotate keys; self-service key rotation can be built with Lambda.
- Cognito, DynamoDB or Secrets Manager commonly store user records for custom IdPs.

## G. Storage options
- **Amazon S3**: choose bucket/prefix; use SSE-S3 or SSE-KMS (role needs KMS permissions); lifecycle policies; event notifications for processing.
- **Amazon EFS**: POSIX permissions; good for shared file workloads/legacy apps; same-VPC access.
- Choose S3 for data lakes, cost, scale; EFS when apps need NFS semantics.
- S3 object semantics: SFTP rename/append behave via copy/replace (S3 has no true rename/append) — large renames are costly.
- Large files transfer in multi-part; the service handles it.
- Files of **size 0** do not trigger workflows.

## H. Security policies, protocols and exposure (quick rules)
- Prefer **SFTP** (encrypted, single port 22). Use **FTPS** when partners demand FTP+TLS. Avoid **FTP** except internally.
- Choose the strongest **security policy** your clients support; FIPS if required.
- Put servers in **VPC** with **security groups** limiting partner CIDRs; use **Elastic IPs** for allow-lists.
- Protect custom IdP APIs with **AWS WAF** (when using API Gateway) and throttling.
- Use **CloudWatch** alarms on auth failures; **CloudTrail** for management actions.
- Consider **GuardDuty malware protection for S3** to scan uploaded files (reference architecture).
- Encrypt data at rest in S3/EFS with KMS; encryption in transit by protocol (SFTP/FTPS/AS2/HTTPS).
- Rotate SSH keys, remove unused users, review IAM roles.

## I. Transfer Family vs neighbors
| Need | Pick |
|---|---|
| Partners upload via SFTP/FTPS/FTP/AS2 into S3/EFS | **Transfer Family** |
| Web UI for business users into S3 | **Transfer Family web apps** |
| Local NFS/SMB access to S3 with cache | **Storage Gateway (File Gateway)** |
| Bulk scheduled copy from on-prem to S3/EFS | **DataSync** |
| Offline huge transfers | Snow (closed to new) / Data Transfer Terminal |
| Pull files from a partner's SFTP server on a schedule | **Transfer Family SFTP connectors** |
| Direct HTTPS uploads from apps | S3 pre-signed URLs / SDK |

## Scenarios (if → then, because)
- If a partner needs a fixed IP to allow-list → VPC internet-facing endpoint with Elastic IPs, because public endpoint IPs can change.
- If partners need FTPS → VPC endpoint with an ACM certificate and a custom hostname, because FTPS isn't supported on public endpoints.
- If users must log in with passwords from Okta/Azure AD → custom identity provider (Lambda/API Gateway), because service-managed supports keys only.
- If users come from corporate Active Directory → AWS Managed Microsoft AD identity provider with group-to-role mapping.
- If each customer must see only their own folder → home directory `/bucket/${username}` with Restricted or a session policy using policy variables.
- If you must hide the bucket name and present clean paths → logical directories.
- If a legacy system speaks FTP only → FTP on a VPC internal endpoint; no internet exposure.
- If workloads need NFS semantics → EFS backend with POSIX users.
- If users must connect only from certain IPs → security group CIDRs on the VPC endpoint or IP checks in the custom IdP.
- If migrating from an on-prem SFTP host without changing partner clients → import the existing host key and point the DNS name at the Transfer endpoint.
- If AS2 is required → server with AS2 enabled, S3 only (not EFS).

## Verified from AWS docs on 2026-10-09
Read: What is AWS Transfer Family page (protocols, storage, use cases, ports), service-managed users page, workflows page (for cross references). Server-creation, custom identity provider, connectors and AS2 pages came back as summaries or outlines (general knowledge used). Not confirmed (verify): public endpoint = SFTP only; VPC endpoint features list; stop/billing behavior of servers; service-managed password support; Global Accelerator/WAF integration details; username limits for non-service-managed IdPs.

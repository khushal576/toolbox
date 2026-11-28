# AWS WAF and Shield – 1. AWS WAF

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **AWS WAF** is a managed **web application firewall** for **Layer 7 (HTTP/HTTPS)**. It inspects requests and **allows, blocks, counts, or challenges (CAPTCHA / Challenge)** them.
- You write rules in a **web ACL** (the console now also calls it a **protection pack**) and **associate** it with a protected resource.
- It protects against **SQL injection, XSS, bad bots, scrapers, credential stuffing, IP/geo abuse, request floods**, and allows custom business rules.
- It does **not** stop volumetric network DDoS (that is **AWS Shield**) and does not scan your code.
- Pick it when: you expose **public HTTP APIs/websites/data APIs** (CloudFront, ALB, API Gateway, AppSync, Cognito, App Runner, Verified Access, Amplify) and need request filtering, rate limiting, bot control.
- Data-engineering touchpoints: **API Gateway data APIs**, **ALB in front of Superset/Metabase/Airflow/Grafana**, **CloudFront** for data downloads, **Cognito** hosted UI, **AppSync** GraphQL APIs.
- DEA-C01: appears under **security of ingestion/data APIs (4.x)** mostly through **API Gateway + WAF**, plus attack-protection choices (WAF vs Shield vs security groups vs NACLs).

## B. Where WAF attaches (resource types)
- **Global** scope: **Amazon CloudFront** distributions (create the web ACL in **us-east-1**, scope `CLOUDFRONT`).
- **Regional** scope: **Application Load Balancer**, **API Gateway REST API stage**, **AWS AppSync GraphQL API**, **Cognito user pool**, **App Runner service**, **Verified Access instance**, **AWS Amplify**, **Bedrock AgentCore Gateway** (newer).
- **Not supported**: Network Load Balancer, Classic Load Balancer, HTTP API (API Gateway v2) directly **(verify)**, EC2 instances, Lambda function URLs (front with CloudFront/ALB).
- One **web ACL per resource**; one web ACL can be associated with many resources of supported types (up to 100 per type) in the same Region.
- **AWS Firewall Manager** applies WAF policies across accounts/OUs automatically.

## C. Building blocks
- **Web ACL (protection pack)**: ordered list of rules + **default action** (Allow or Block).
- **Rule**: a **statement** + **action** (Allow, Block, Count, CAPTCHA, Challenge) + optional **labels** and **custom request/response**.
- **Statements**: match on IP set, geo, regex pattern set, string match, size constraint, SQLi match, XSS match, label match, **rate-based**, byte match; combine with **AND / OR / NOT**.
- **Rule group**: reusable set of rules. Kinds: **managed rule groups** (AWS or Marketplace sellers) and **your own** rule groups.
- **IP set**: up to **10,000 CIDRs**; **regex pattern set**: up to 10 patterns, each up to 200 characters.
- **Web ACL capacity units (WCUs)**: each rule has a WCU cost (complexity). **Default 1,500 WCUs; max 5,000** per web ACL / rule group. Above 1,500 costs more.
- **Rule evaluation**: rules are checked in **priority order** (lowest number first). **Allow/Block/CAPTCHA/Challenge terminate** evaluation; **Count** does not (continues).
- **Labels**: rules can add labels that later rules match on (powerful for composing managed rules).
- **Text transformations** (up to 10 per statement): URL decode, lowercase, HTML entity decode, compress whitespace, base64 decode…, to defeat evasion.
- **Field to inspect**: URI path, query string, single header, all headers, cookies, JSON body, body, method, HTTP version, JA3/JA4 fingerprints, header order **(verify)**, IP/forwarded IP.
- **Request body inspection limits**: **8 KB** for ALB and AppSync; **64 KB max** for CloudFront, API Gateway, Cognito, App Runner, Verified Access (default 16 KB, adjustable up to 64 KB). Body beyond the limit is not inspected; choose how to handle oversize (match/continue/no-match).
- **Custom responses**: block with your own status code, headers, body (≤ 4 KB each; combined ≤ 50 KB).
- **Custom request headers**: insert headers on allowed requests (≤ 100 per web ACL).

## D. Managed rule groups (AWS managed)
- **Baseline**: **Core rule set (CRS)**, **Admin protection**, **Known bad inputs**.
- **Use-case specific**: **SQL database**, **Linux/POSIX/Windows/PHP/WordPress operating system or application** sets.
- **IP reputation**: **Amazon IP reputation list**, **Anonymous IP list**.
- **Bot Control**: **Common** (verified bots, signature-based) and **Targeted** (ML, browser fingerprinting, behavior). Extra cost.
- **Fraud Control**: **Account Takeover Prevention (ATP)** protects login pages; **Account Creation Fraud Prevention (ACFP)** protects signup. Extra cost, tiered per request.
- **Anti-DDoS managed rule group** (L7 DDoS protection) for Shield Advanced customers or optional **(verify)**.
- **Versioning**: managed groups have versions; pin a version or use the default (auto-updated).
- **Override actions**: set a managed group to **Count** first (observe), then switch to Block (**override rule actions**). Use **rule action overrides** per rule to exclude false positives.
- **Marketplace** groups (F5, Fortinet, Trend Micro…) cost extra.
- **Scope-down statements** limit expensive groups (Bot Control, ATP) to certain paths (for example `/login`).

## E. Rate-based rules
- Count requests per **aggregation key** over a **window** (1, 2, 5, 10 minutes; default 5) and **block** when the count exceeds the **limit** (minimum limit **10**).
- Aggregation keys: **source IP**, **forwarded IP** (X-Forwarded-For), **custom keys** (header, cookie, query arg, URI path, label namespace, IP+path…), or **constant** (count all).
- Limits: up to **10 rate-based rules per web ACL**, **4 per rule group**; each rule can track up to **10,000 unique IPs** **(verify)**.
- Typical use: protect `/login`, `/api/query`, API keys; block scrapers.
- **Rate limit per API key / customer ID**: custom key on header `x-api-key`.
- Rate-based rules are **approximate** (distributed counters), not exact.
- The blocked requestor is unblocked automatically when the rate falls below the limit.
- Pair with **API Gateway usage plans** for per-client quotas (WAF is edge-level traffic control; usage plans are API-key quotas).

## F. Bot and fraud features
- **CAPTCHA** action shows a puzzle; **Challenge** action runs a silent browser check; both issue a **token** (AWS WAF token) valid for an immunity time (default 300 s; configurable).
- **Token domains**: up to 10 per web ACL.
- **AWS WAF JavaScript / mobile SDK** integrations obtain tokens for apps and enable Targeted Bot Control / ATP.
- **Bot Control** categories: verified bots (search engines) vs unverified; labels like `awswaf:managed:aws:bot-control:bot:category:...`.
- **ATP**: inspects login requests, compromised credentials DB, volumetric login attempts.
- **ACFP**: checks account creation, phone/email reputation.

## G. Logging, monitoring and testing
- **Logging** (full request details) to: **CloudWatch Logs** (log group name must start with `aws-waf-logs-`), **S3** (bucket name starts with `aws-waf-logs-`), or **Kinesis Data Firehose** (stream name starts with `aws-waf-logs-`). Choose **redacted fields** (headers, query) and **filters** (log only blocked/counted).
- **Sampled requests** (last 3 hours, up to 100 per rule) in the console, free.
- **CloudWatch metrics** (`AWS/WAFV2`): `AllowedRequests`, `BlockedRequests`, `CountedRequests`, `CaptchaRequests`, `ChallengeRequests`, `PassedRequests`, per web ACL/rule/rule group; Bot Control and ATP metrics.
- **Rule action `Count` mode** to test new rules before blocking.
- **Athena** over WAF logs (S3) for analysis; **Security Lake** can ingest.
- **Security Hub**, **Firewall Manager** policy compliance, **GuardDuty** complement.
- **CloudTrail**: WAF API changes (UpdateWebACL).
- **Alarms**: spike in `BlockedRequests`, rate-limit hits, no `AllowedRequests` (misconfiguration blocking all traffic).
- **Test with** curl, `waf-testing` tools; deploy changes through IaC and staged **Count** first.
- **Version handling**: web ACL updates apply within seconds to a few minutes globally.

## H. Cost
- **Web ACL**: about **$5.00 per month** each (US example).
- **Rules**: about **$1.00 per rule per month** (including each rule inside your rule groups; each managed rule group you add counts as **$1/month**).
- **Requests**: about **$0.60 per million** requests inspected.
- **WCU surcharge**: about **$0.20 per million requests per 500 WCUs above 1,500**.
- **Body inspection above default**: about **$0.30 per million requests per extra 16 KB**.
- **CAPTCHA**: about **$0.40 per 1,000** attempts; **Challenge** priced separately.
- **Bot Control**: $10/web ACL/month + per-request (Common: 10M free then ~$1/million; Targeted: 1M free then ~$10/million).
- **Fraud Control (ATP/ACFP)**: $10/web ACL/month each + tiered per-request fees (expensive; scope down to login/signup).
- **Marketplace rule groups**: seller fees on top.
- **Logging**: CloudWatch Logs/S3/Firehose ingestion and storage; "each 1M requests includes 500 MB of vended logs" credit **(verify)**.
- **Shield Advanced** customers get limited WAF usage included (see file 2).
- **Cost levers**: reuse web ACLs across resources, scope down managed groups, avoid unneeded Bot Control, trim WCUs, log only blocked requests, use sampling filters.

## I. Limits cheat sheet
| Item | Value |
|---|---|
| Web ACLs (protection packs) per Region | **100** |
| Rule groups per Region | **100** |
| IP sets per Region | **100** |
| Regex pattern sets per Region | **10** |
| WCU per web ACL / rule group | **1,500 default (billing threshold)**, **5,000 max** |
| IPs per IP set | **10,000** CIDRs |
| Rate-based rules | **10 per web ACL**, **4 per rule group**; min rate **10** |
| Reference statements per web ACL / rule group | **50** |
| Max requests/second per web ACL | **100,000** (adjustable) |
| Text transformations per statement | **10** |
| String match / regex length | **200** chars |
| Geo codes per statement | **50** |
| Body inspection | ALB/AppSync **8 KB**; others up to **64 KB** |
| Associations per web ACL (per type) | **100** |
| Custom response body | **4 KB** each; **50 KB** total |
| Token domains | **10** |
| API rates | Associate/Disassociate 1 per 2 s; Create/Update 1/s |

## J. Exam skills mapping
- **1.2.8 Create data APIs**: protect data APIs.
- **1.1.8 Create IP allowlists for data sources**: IP allowlists with WAF IP sets.
- **4.1.5 IAM policies on roles, endpoints, services (S3 Access Points, PrivateLink)**: edge protections for endpoints.

## K. Scenarios: "If X → Y, because Z"
- **If** a public API is getting **SQL injection** attempts (attackers hiding database commands inside requests), **then** attach an **AWS Web Application Firewall (WAF)** web ACL to the **Amazon API Gateway** REST API stage or the **Application Load Balancer (ALB)**, with the AWS managed **Core rule set (CRS)** and **SQL database** rule groups. **This works because** WAF works at **Layer 7 (L7)**, the HTTP layer, so it reads the request content (query string, headers, body) and blocks requests that match known attack patterns before they reach your app.
- **If** one client floods your **`/login`** page with requests, **then** add a **rate-based rule** keyed on **source IP** (or on an **API key** header), with a scope-down statement so it only counts **`/login`**. **This works because** a rate-based rule counts requests per key over a window (default **5 minutes**) and blocks that key once it passes the limit (minimum **10**). The block lifts by itself when the rate drops, and counts are **approximate**, not exact.
- **If** you want to test a new rule safely, **then** set its action to **Count** first. **This works because** Count records matches in metrics and logs but does **not** block, so you can check for false positives before switching to Block.
- **If** an AWS managed rule blocks a valid request (a false positive), **then** use a **rule action override** to set just that one rule to **Count**, or add a **scope-down statement** so the group skips that path. **This works because** you remove the false positive while the rest of the managed rule group keeps protecting you.
- **If** you need to block traffic from specific countries, **then** add a **geo match rule** to your WAF web ACL. **This works because** WAF can match the request's country code, with up to **50** country codes per statement.
- **If** a service behind a **Network Load Balancer (NLB)** needs L7 (HTTP) protection, **then** put an **Application Load Balancer (ALB)** or **Amazon CloudFront** (the AWS content delivery network) in front and attach WAF there. **This works because** WAF cannot attach to an NLB; it only attaches to supported resources such as CloudFront, ALB and API Gateway.
- **If** you need protection from **Distributed Denial of Service (DDoS)** attacks at the network and transport layers (**Layer 3/Layer 4**), such as SYN floods, **then** rely on **AWS Shield Standard** (free, always on) or **Shield Advanced** (paid). **This works because** WAF only handles **L7** HTTP traffic; volumetric network floods are Shield's job.
- **If** WAF logs must be analyzed with SQL, **then** send WAF logs to an **Amazon S3** bucket whose name starts with **`aws-waf-logs-`** and query them with **Amazon Athena** (a serverless SQL query service). **This works because** the logs land in S3 as JSON files, which Athena can read with SQL.
- **If** **100 accounts** need the same WAF baseline, **then** create an **AWS Firewall Manager** WAF policy. Firewall Manager centrally manages firewall rules across an **AWS Organization**. **This works because** it deploys web ACLs to every account and resource in scope and keeps enforcing them org-wide. It needs Organizations with all features, an administrator account, and **AWS Config** turned on in member accounts.
- **If** request bodies are larger than WAF's inspection limit and that is a risk, **then** raise the body inspection limit on **CloudFront** or **API Gateway** (default **16 KB**, up to **64 KB**), or set the oversize handling to **block** (match) oversize requests. **This works because** WAF does not inspect content past the limit, so an attack could hide there. **Application Load Balancer (ALB)** and **AWS AppSync** are fixed at **8 KB**, and a higher limit adds cost.
- **If** scrapers keep getting past your IP blocking, **then** add the **Bot Control** managed rule group at the **Targeted** level, plus **CAPTCHA** (a puzzle) or **Challenge** (a silent browser check) actions. **This works because** Targeted Bot Control uses machine learning, browser fingerprinting and behaviour, and CAPTCHA/Challenge issue a **token**, so changing IP addresses does not help the scraper. Bot Control costs extra.
- **If** your WAF bill rises sharply, **then** check the scope of **Bot Control**, **Account Takeover Prevention (ATP)** and **Account Creation Fraud Prevention (ACFP)**, whether you use more than **1,500 Web ACL Capacity Units (WCUs)**, and your **logging volume**. **This works because** each of these adds per-request or storage charges. Scope expensive groups down to paths like `/login`, and log only blocked requests.

Verified from AWS docs on 2026-11-03 (AWS WAF quotas, WAF pricing, Shield pricing).
Unconfirmed (verify): HTTP API (v2) support; Anti-DDoS managed rule group availability; logging credit statement; JA3/JA4 field availability; unique-IP cap per rate rule; Challenge pricing; Lambda function URL support via CloudFront only.

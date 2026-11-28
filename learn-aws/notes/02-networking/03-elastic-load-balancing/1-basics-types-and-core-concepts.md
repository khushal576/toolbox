# Elastic Load Balancing – 1. Basics, types and core concepts

Short notes. Each point is a fact you can be asked about.

## A. What a load balancer does
- **Elastic Load Balancing (ELB)** = a managed service that **spreads incoming traffic** across many targets (EC2 instances, containers, IP addresses, Lambda functions, appliances) in **one or more AZs**.
- Why use one:
  - **High availability**: if a target or a whole AZ fails, traffic goes to healthy targets elsewhere.
  - **Health checks**: sends traffic only to healthy targets.
  - **Scaling**: Auto Scaling groups/ECS/EKS add or remove targets behind one stable entry point.
  - **Single DNS name** for clients, while servers change behind it.
  - **TLS termination** (offloads encryption work, central certificates via ACM).
  - **Security**: only the load balancer is exposed. Targets sit in private subnets.
  - **Routing**: send different paths/hosts to different services (ALB).
- **Managed**: AWS runs, patches and **scales the load balancer nodes automatically** as traffic grows. Highly available across the AZs you enable.
- **Regional** service: one load balancer serves one Region. For multi-Region, use **Route 53** (latency/failover routing) or **Global Accelerator** in front.
- Shared terms:
  - **Listener**: the port + protocol the LB accepts (for example HTTPS:443).
  - **Target group**: a set of targets + health check + protocol/port.
  - **Rules**: how a listener maps requests to target groups.

## B. The four types
| Type | Layer | Protocols | Pick it for |
|---|---|---|---|
| **Application LB (ALB)** | 7 (application) | HTTP, HTTPS, HTTP/2, gRPC, WebSockets | Web apps, REST/data APIs, microservices, content-based routing, Lambda targets, user authentication |
| **Network LB (NLB)** | 4 (transport) | TCP, UDP, TLS, TCP_UDP (QUIC; verify) | Extreme performance (millions of req/s), **static IPs / Elastic IPs**, non-HTTP protocols, client IP preservation, **PrivateLink** services |
| **Gateway LB (GWLB)** | 3 (network) | IP packets via **GENEVE** (port 6081) | Inserting **third-party virtual appliances** (firewalls, IDS/IPS, deep packet inspection) transparently |
| **Classic LB (CLB)** | 4 and 7 (legacy) | HTTP, HTTPS, TCP, SSL | Old EC2 apps only. **Previous generation**; migrate to ALB/NLB |
- **CLB status**: previous generation, still available (not formally retired as of this writing; verify). AWS recommends **ALB or NLB**. CLB lacks target groups, path/host routing, IP/Lambda targets, HTTP/2, and more. The **migration wizard** copies a CLB config to an ALB/NLB.
- **Quick picking rules**:
  - "Route by URL path / host header / HTTP header" → **ALB**.
  - "Static IP address / Elastic IP / allowlist by IP" → **NLB** (or Global Accelerator).
  - "TCP/UDP non-HTTP, ultra-low latency, millions of connections" → **NLB**.
  - "Expose a service privately to other VPCs/accounts via PrivateLink" → **NLB** (endpoint service; also GWLB for appliances).
  - "Insert a firewall appliance fleet into traffic flow" → **GWLB**.
  - "Authenticate users with Cognito/OIDC before reaching the app" → **ALB**.
  - "Invoke Lambda over HTTP" → **ALB** (or API Gateway / function URL).
  - "Need a WAF" → **ALB** (WAF attaches to ALB, not NLB).

## C. Load balancer scheme, AZs and nodes
- **Internet-facing**: has a public DNS name resolving to public IPs. It must sit in **public subnets** (route to an internet gateway). Targets can be in private subnets.
- **Internal**: only private IPs, reachable inside the VPC / peered / VPN / Direct Connect. For internal microservices, internal data APIs and tiers behind a web tier.
- **Subnets / AZs**:
  - You enable **one subnet per AZ**. The LB places **nodes** (ENIs) in each enabled subnet.
  - **ALB needs at least 2 AZs**. NLB can use 1+ (verify). Use 2–3 AZs for HA.
  - The subnet must have free IPs: the ALB needs **at least 8 free IPs per subnet** (/27 or bigger recommended) because it scales nodes; the NLB uses one IP per AZ.
  - An ALB can't change AZs to fewer than 2.
- **DNS name**:
  - Clients use the LB's **DNS name** (`name-123.region.elb.amazonaws.com`), which returns the IPs of the nodes.
  - **ALB IPs change** as it scales. **Never hard-code ALB IPs**. Use DNS, a Route 53 **alias** record, or put an NLB/Global Accelerator in front for static IPs.
  - **NLB IPs are static per AZ** (one IP per AZ, or your own **Elastic IP** per AZ for internet-facing NLBs).
- **IP address type**: IPv4, **dualstack** (IPv4 + IPv6), or dualstack-without-public-IPv4 (ALB; avoids public IPv4 charges; verify).
- **Route 53 alias records** point a domain (also the zone apex like `example.com`) to the LB for free. They are better than CNAMEs.

## D. Listeners, rules and target groups
- **Listener** = protocol + port (ALB: HTTP/HTTPS; NLB: TCP/UDP/TLS/TCP_UDP). Each listener has a **default action** plus optional **rules** (ALB, and NLB rules for some features; verify).
- **Target group**:
  - **Target type**:
    - **`instance`**: EC2 instance IDs; traffic to the instance's primary IP.
    - **`ip`**: IP addresses: containers with awsvpc (**ECS Fargate, EKS pods**), on-prem servers over VPN/DX, peered VPC IPs.
    - **`lambda`**: ALB only; one function per target group.
    - **`alb`**: NLB only; an ALB as the NLB target, giving static IPs in front of an ALB.
  - **Protocol/port** for targets (HTTP/HTTPS/gRPC for ALB; TCP/UDP/TLS for NLB). Protocol version HTTP1/HTTP2/gRPC.
  - **Health check settings** (section E).
  - **Attributes**: deregistration delay, slow start, stickiness, load balancing algorithm, cross-zone per target group (ALB).
  - A target group belongs to **one load balancer**. A target can be in many target groups (for example on different ports).
- **Registering targets**: manually, through **Auto Scaling groups** (attach target groups to the ASG), **ECS services** (register tasks automatically), or the **AWS Load Balancer Controller** (EKS).

## E. Health checks
- The LB sends periodic checks to each target and routes only to **healthy** ones.
- **ALB health check**: HTTP/HTTPS **path** (for example `/health`), port, expected **success codes** (default 200; can be 200-399).
- **NLB health check**: TCP connect, or HTTP/HTTPS path.
- **GWLB health check**: TCP/HTTP/HTTPS to appliances.
- **Settings** (ALB defaults; verify):
  - **Interval 30 s** (5–300).
  - **Timeout 5 s**.
  - **Healthy threshold 5** consecutive successes.
  - **Unhealthy threshold 2** consecutive failures.
  - NLB defaults differ (interval 30 s, thresholds 5/2; verify).
- **Fail-open**: if **all** targets in a target group are unhealthy, the ALB sends traffic to **all** of them anyway (and the NLB fails open too). **Target group health requirements** (DNS failover thresholds) can change this (verify).
- **ASG + ELB health checks**: set the ASG health check type to **ELB** so instances failing LB health checks are **replaced**, not just skipped.
- **ECS**: `healthCheckGracePeriodSeconds` on the service gives slow-starting containers time before health checks count.
- Design: the health endpoint should check the app is truly ready (dependencies), but be **light and fast**. A deep check that calls the database on every probe can cause a cascade of failures.
- Health check traffic comes from LB node IPs. The **target security group must allow the health check port** from the LB security group.

## F. Cross-zone load balancing
- **Off**: each LB node sends traffic **only to targets in its own AZ**. Uneven target counts per AZ → uneven load.
- **On**: each node spreads traffic **across targets in all enabled AZs** evenly.
- **Defaults and cost**:
  - **ALB**: **always on at the LB level and free** (no inter-AZ charge). It can be **turned off per target group** (since 2022).
  - **NLB**: **off by default**. Turning it on causes **inter-AZ data transfer charges**.
  - **GWLB**: **off by default**. Inter-AZ charges if on.
  - **CLB**: on by default when created in the console, off via API/CLI (verify). Free.
- Turn cross-zone **on** for NLB when target counts per AZ are uneven or clients cache one AZ's IP (DNS caching).
- With cross-zone off, keep **equal capacity per AZ**.

## G. Routing algorithms (how a target is picked)
- **ALB**:
  - **Round robin** (default): requests rotate across healthy targets.
  - **Least outstanding requests (LOR)**: sends to the target with the fewest in-flight requests. Better when requests vary in cost (heavy data queries mixed with light ones). Not compatible with slow start.
  - **Weighted random** with **Automatic Target Weights (ATW) / anomaly mitigation**: detects targets returning errors/timeouts more than others and **reduces their traffic** automatically (verify name).
- **NLB**:
  - **Flow hash**: protocol, source IP/port, destination IP/port (and TCP sequence) → one target **per connection/flow**. A long-lived connection stays on one target.
  - So a few very busy long-lived connections can make NLB load uneven.
- **GWLB**: flow-based stickiness (5-tuple / 3-tuple / 2-tuple) so both directions of a flow hit the same appliance.

## H. Connection behavior settings
- **Deregistration delay** (connection draining):
  - When a target is deregistered (scale-in, deployment), the LB **stops new requests** but lets **in-flight requests finish** for up to the delay.
  - **Default 300 s**, range 0–3,600 s.
  - Lower it for fast deployments of short-request apps. Raise it for long uploads/queries.
- **Slow start** (ALB): a new target's share of traffic **ramps up linearly** over 30–900 s (warm caches, JIT). Not with LOR.
- **Sticky sessions (session affinity)**:
  - ALB **duration-based** cookie (`AWSALB`, 1 s – 7 days).
  - Or an **application-based** cookie (your app's cookie + `AWSALBAPP`).
  - NLB stickiness by **source IP**.
  - Stickiness keeps a user on one target (in-memory sessions) but **uneven load**, and sessions are lost if the target dies. Prefer **stateless apps** with sessions in ElastiCache/DynamoDB.
  - With weighted target groups (blue/green), **target group stickiness** keeps users on one version.
- **Idle timeout**:
  - **ALB connection idle timeout default 60 s** (1–4,000 s). If no data is sent within that time, the connection closes. Long-running API calls or reports need a higher timeout (or async patterns).
  - The backend keep-alive timeout should be **longer** than the ALB idle timeout, or you get random 502s.
  - **NLB TCP idle timeout 350 s** by default (configurable 60–6,000 s; verify). **UDP 120 s**.
- **HTTP keep-alive / client keep-alive duration** (ALB setting; verify).
- **Connection termination on deregistration** (NLB option): close existing connections after the delay.
- **Preserve client IP**:
  - **NLB**: client IP preserved by default for `instance` targets and configurable for `ip` targets (verify defaults). It can be off with PrivateLink.
  - **ALB**: replaces the source IP with its own. The client IP is in the **`X-Forwarded-For`** header.
- **Proxy protocol v2** (NLB): sends the original client IP/port in a header to targets when IP preservation is not possible (for example via PrivateLink).

## Scenarios (if → then, because)
- **If** a data API must send `/v1/query` to one service and `/v1/ingest` to another, **then** use an **Application Load Balancer (ALB)** with **path-based listener rules**, each rule forwarding to its own **target group** (a set of targets with a health check). **This works because** the ALB works at **layer 7**, so it can read the URL path of each request and route on it. A Network Load Balancer (NLB) works at layer 4 and never looks at HTTP content.
- **If** partners must allowlist fixed IPs for your ingestion endpoint, **then** use a **Network Load Balancer (NLB)** with your own **Elastic IP** (a fixed public IP) in each Availability Zone (AZ), or put **AWS Global Accelerator** in front. **This works because** NLB IPs are **static per AZ**. ALB IPs **change** as the ALB scales, so they can never be given to a partner.
- **If** you need **static IPs and HTTP routing** together, **then** put a **Network Load Balancer (NLB)** in front and register the **Application Load Balancer (ALB)** as its target using the **`alb` target type**, or put **AWS Global Accelerator** in front of the ALB. **This works because** the NLB (or Global Accelerator) gives the fixed IPs, while the ALB behind it still does layer 7 routing by path, host or header.
- **If** a service must be offered privately to other VPCs or accounts without VPC peering, **then** put it behind a **Network Load Balancer (NLB)** and create a **VPC endpoint service (AWS PrivateLink)**. **This works because** consumers create **interface endpoints** in their own VPCs and reach your service privately through them. The NLB is the load balancer type used for PrivateLink endpoint services.
- **If** all traffic must pass through third-party firewalls, **then** use a **Gateway Load Balancer (GWLB)** with **GWLB endpoints**. **This works because** the GWLB works at **layer 3** (IP packets) and sends packets to the firewall appliances using **GENEVE** on port **6081**, so the appliances are inserted **transparently** into the traffic flow.
- **If** a TCP or UDP service that is not HTTP needs very low latency and **millions of connections**, **then** use a **Network Load Balancer (NLB)**. **This works because** the NLB works at **layer 4** (TCP, UDP, TLS) and is built for extreme performance, handling millions of requests per second.
- **If** an old app still uses a **Classic Load Balancer (CLB)**, **then** move it to an **Application Load Balancer (ALB)** or **Network Load Balancer (NLB)** with the **migration wizard**, which copies the CLB configuration. **This works because** the CLB is **previous generation**: it lacks target groups, path/host routing, IP/Lambda targets and HTTP/2, and AWS recommends ALB or NLB.
- **If** containers on **AWS Fargate** (Amazon ECS) or **Amazon Elastic Kubernetes Service (EKS)** pods must be targets, **then** use the **`ip` target type**. **This works because** awsvpc tasks and pods get **their own IP addresses**, so the load balancer sends traffic straight to those IPs instead of to an EC2 instance ID.
- **If** an HTTP endpoint should invoke an **AWS Lambda** function, **then** use an **Application Load Balancer (ALB)** with a **`lambda` target group**. **This works because** only the ALB supports Lambda targets, with **one function per target group**.
- **If** instances that fail health checks should be **replaced**, not just skipped, **then** set the **Auto Scaling group (ASG) health check type to ELB**. **This works because** the ASG then uses the load balancer's health checks, so an instance that fails them is terminated and replaced instead of only being bypassed.
- **If** one AZ has **2 targets** and the other has **8** behind a **Network Load Balancer (NLB)**, and load is uneven, **then** turn **cross-zone load balancing** on, or keep equal targets per Availability Zone (AZ). **This works because** with cross-zone **off** (the NLB default), each node sends traffic only to targets in its own AZ, so the 2 targets get half of all traffic. The catch: NLB cross-zone adds **inter-AZ data transfer charges**.
- **If** some queries are heavy and others light, and round robin overloads some servers, **then** switch the **Application Load Balancer (ALB)** algorithm to **least outstanding requests (LOR)**. **This works because** LOR sends each request to the target with the **fewest in-flight requests**, instead of rotating evenly. The catch: LOR **cannot be used with slow start**.
- **If** one bad instance keeps returning errors, **then** use **Application Load Balancer (ALB) anomaly mitigation**, the **weighted random** algorithm with **Automatic Target Weights (ATW)** (verify name), plus health checks. **This works because** the ALB detects targets returning **more errors or timeouts** than others and **reduces their traffic** automatically, even before health checks mark them unhealthy.
- **If** deployments are slow because draining waits **300 s** for short requests, **then** lower the **deregistration delay**. **This works because** this delay is how long the load balancer lets in-flight requests finish on a removed target (default **300 s**, range 0–3,600 s); short requests finish quickly, so a long wait is wasted.
- **If** long report downloads are cut at **60 s**, **then** raise the **Application Load Balancer (ALB) idle timeout**, or move to async jobs with **Amazon S3 presigned URLs**. **This works because** the ALB closes a connection when no data is sent for the idle timeout (**default 60 s**, range 1–4,000 s).
- **If** random **502** errors appear under load, **then** make the **backend keep-alive timeout longer** than the **Application Load Balancer (ALB) idle timeout**. **This works because** when the backend closes an idle connection first, the ALB may still send a request on it and gets a closed connection, which it returns as a 502.
- **If** the app needs the client's real IP, **then** behind an **Application Load Balancer (ALB)** read the **`X-Forwarded-For`** header; behind a **Network Load Balancer (NLB)** use **client IP preservation** (defaults depend on target type; verify) or **Proxy Protocol v2**. **This works because** the ALB replaces the source IP with its own, while the NLB can keep it or pass it in a header.
- **If** users lose their session when they hit a different server, **then** keep sessions outside the servers in **Amazon ElastiCache** or **Amazon DynamoDB** (stateless app), or use **ALB sticky sessions** as a short-term fix. **This works because** any target can then serve any user. Stickiness keeps a user on one target, but causes **uneven load** and loses sessions if that target dies.
- **If** a new instance gets overwhelmed right after joining, **then** turn on **Application Load Balancer (ALB) slow start**. **This works because** slow start **ramps up** the new target's share of traffic linearly over **30–900 s**, giving caches and JIT time to warm up.
- **If** someone hard-coded the **Application Load Balancer (ALB)** IP and it broke, **then** always use the load balancer's **DNS name** or an **Amazon Route 53 alias record**. **This works because** ALB IPs **change** as it scales, while the DNS name always returns the current node IPs.

## Verified from AWS docs on 2026-10-11
Read from current sources: ALB and NLB quotas (used for target type and target counts), ELB pricing page (used for cross-zone/cost notes in file 3), CLB status search (no official retirement found; EC2-Classic networking retirement is complete).
Not confirmed (verify): NLB QUIC support, NLB rules support, NLB single-AZ allowance, dualstack-without-public-IPv4, health check defaults, target group health requirements behavior, CLB cross-zone defaults, ATW/anomaly mitigation naming, NLB idle timeout range and client IP preservation defaults, ALB client keep-alive setting.

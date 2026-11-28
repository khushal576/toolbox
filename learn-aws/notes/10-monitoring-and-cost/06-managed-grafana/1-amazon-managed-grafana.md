# Amazon Managed Grafana – Workspaces, data sources, access and cost

Short notes. Each point is a fact you can be asked about.

## A. What it is
- **Amazon Managed Grafana (AMG)** is a **fully managed Grafana service** for visualizing and analyzing **metrics, logs and traces** from multiple sources. AWS provisions, scales, patches and secures the Grafana servers.
- You create **workspaces** (logically isolated Grafana servers), then build **dashboards**, alerts and visualizations.
- Pick it when: you want **Grafana dashboards** across many AWS/open-source data sources, **SSO**, and no server management; teams already use Grafana/Prometheus; you need **multi-account/multi-Region** dashboards in one pane.
- Alternatives: **CloudWatch dashboards** (native, simpler, AWS-only), **QuickSight** (BI for business data), **OpenSearch Dashboards** (log analytics on OpenSearch), self-managed Grafana (more control, more ops).
- DEA-C01: used for **operational monitoring dashboards** of pipelines (CloudWatch, Prometheus, Athena, Timestream, OpenSearch data sources).

## B. Core concepts
- **Workspace**: the Grafana instance; has its own URL, users, data sources, plugins, alert settings. Supports Grafana versions (v9, v10, v11+) chosen at creation/upgrade **(verify current versions)**.
- **Account access mode**: **current account** or **organization** (multi-account data sources via AWS Organizations) — and **service-managed** vs **customer-managed** IAM permissions:
  - **Service managed**: AMG creates and manages an IAM role with permissions for the data sources you select (easiest).
  - **Customer managed**: you supply the role and policies (fine-grained control; needed for cross-account roles).
- **Authentication** (required): **AWS IAM Identity Center** and/or **SAML 2.0 IdP** (Okta, Entra ID, etc.). Users and groups are assigned roles in the workspace.
- **Roles in Grafana**: **Admin**, **Editor**, **Viewer** (Viewer cannot edit dashboards).
- **Service accounts / API keys**: for automation (create dashboards, provisioning); billed as users per active use.
- **Data sources** supported (AWS and others):
  - AWS: **Amazon CloudWatch** (metrics, logs), **Amazon Managed Service for Prometheus**, **Amazon OpenSearch Service**, **AWS X-Ray**, **Amazon Timestream**, **AWS IoT SiteWise**, **IoT TwinMaker**, **Amazon Athena**, **Amazon Redshift**, **Amazon RDS (MySQL/PostgreSQL via plugin)**, **CloudWatch Logs Insights**.
  - Open source/third-party: Prometheus, Loki, Tempo, InfluxDB, Graphite, Elasticsearch, Jaeger, Zabbix, Datadog, Splunk, ServiceNow, Dynatrace, Snowflake, Databricks, MongoDB, GitHub, Jira (some require **Enterprise plugins**).
- **Plugins**: community and enterprise plugins; install/upgrade through the workspace.
- **Alerting**: Grafana unified alerting with contact points (SNS, Slack, PagerDuty, email, OpsGenie, webhook), notification policies, silences.
- **Dashboards as code**: provision with API/Terraform/CloudFormation (`AWS::Grafana::Workspace`) and Grafana provisioning.
- **Networking**: workspaces can reach **VPC data sources** via a **VPC connection** (private subnets and security groups); public or private access to the workspace URL (private via VPC endpoint/network access control: IP allowlist/VPCe) **(verify)**.
- **Regions** (documented): us-east-1/2, us-west-2, ap-northeast-1/2, ap-southeast-1/2, eu-central-1, eu-west-1/2, GovCloud.
- **Grafana Enterprise** features via the Enterprise plugin license: enterprise data sources, reporting, usage insights **(verify)**.

## C. Common data-pipeline dashboards
- **CloudWatch**: Glue, Lambda, Kinesis, Firehose, Step Functions, MWAA, EMR metrics (iterator age, errors, freshness).
- **Prometheus (AMP)**: Spark/Kafka/Flink exporters, EKS/EMR on EKS metrics, custom pipeline metrics.
- **Athena**: query S3 data (data quality tables, audit tables, FinOps CUR) directly in dashboards.
- **Redshift/RDS**: operational and warehouse KPIs.
- **OpenSearch**: log analytics and security events.
- **Timestream**: time series ingest metrics.
- **X-Ray**: service maps/traces.
- **Cost**: CUR via Athena for cost dashboards.
- **Combine** multiple accounts/Regions in one dashboard through cross-account roles or organization mode.

## D. Security and access
- **No local Grafana users**: access only via IAM Identity Center/SAML.
- **Data source permissions**: workspace role + (service-managed) permissions per data source; restrict who can edit data sources.
- **Network access control**: restrict workspace access to allowed CIDRs/VPC endpoints; HTTPS only.
- **Encryption**: data in transit TLS; workspace data encrypted at rest (AWS-managed; customer KMS option may exist **(verify)**).
- **Least privilege**: avoid broad `*` read for data sources; for customer-managed roles, scope CloudWatch/Athena/Redshift permissions.
- **Audit**: CloudTrail logs workspace API; Grafana audit logs for Enterprise **(verify)**.
- **Secrets**: data source credentials stored encrypted in the workspace; prefer IAM-based auth (SigV4) over passwords.
- **Service accounts**: rotate tokens; short TTL.

## E. Cost
- **Per active user per workspace per month**: **Editor/Admin about $9**, **Viewer about $5**; **Enterprise plugins add about $45/user**. A workspace needs **at least one Editor** license. Users count as active if they log in or make API calls in the billing month. Service accounts/API keys billed like users.
- **90-day free trial**: up to 5 free users per account.
- No upfront fees; data source query costs (CloudWatch API, Athena scans, Redshift compute) are billed by those services.
- **Cost levers**: use Viewer licenses for most users; remove inactive users; share dashboards instead of many workspaces; cache heavy queries (Athena), use CloudWatch metric streams/Prometheus for cheaper high-volume metrics; avoid too many high-frequency refresh dashboards.

## F. Limits and operations
- **Quotas** (verify): workspaces per account/Region (default 5), users per workspace, API request rates, dashboard counts per Grafana limits.
- **Upgrades**: choose Grafana version; AWS applies patches; plan upgrades (plugins compatibility).
- **Monitoring**: workspace health in console; CloudWatch metrics for Grafana alert evaluation? (limited) **(verify)**.
- **Backup**: export dashboards JSON to Git; provision with IaC.
- **Troubleshooting**:
  - **Can't log in** → user not assigned to the workspace/Identity Center group, SAML attribute mapping.
  - **No data in CloudWatch panel** → role lacks `cloudwatch:GetMetricData`, wrong Region/account selection.
  - **Athena panel errors** → workgroup/output bucket permissions, Glue catalog access, Lake Formation.
  - **VPC data source timeouts** → VPC connection subnets/SGs, route/DNS.
  - **Alerts not delivered** → contact point misconfig, SNS permissions.
  - **High cost** → many users with Editor role.

## G. Exam skills mapping
- **3.2.1 Visualize data (DataBrew, QuickSight)**: visualize operational data.
- **3.3.2 Logging and monitoring for auditing and traceability**: monitoring dashboards.
- **3.3.4 Troubleshoot performance**: performance troubleshooting.

## H. Scenarios: "If X → Y, because Z"
- **If** site reliability engineering (SRE) teams already use **Grafana** and want AWS metrics and **Prometheus** metrics in one dashboard, without running their own servers, **then** use **Amazon Managed Grafana (AMG)**. You create a **workspace** (your own Grafana server) and add data sources such as **Amazon CloudWatch** and **Amazon Managed Service for Prometheus (AMP)**. **This works because** AMG is fully managed Grafana: AWS sets up, scales, patches and secures the servers, and it connects to many AWS and open-source data sources out of the box.
- **If** you only need dashboards for AWS service metrics, **then** use **Amazon CloudWatch dashboards**. **This works because** they are native to AWS and simpler, with no workspace or user licenses to manage; the catch is they cover AWS data only.
- **If** business users need self-service business intelligence (BI) reports, **then** use **Amazon QuickSight**, the AWS BI service for business data. **This works because** Grafana is built for operational monitoring of metrics, logs and traces over time, not for business reporting.
- **If** you need log search and analytics on data stored in **Amazon OpenSearch Service**, **then** use **OpenSearch Dashboards**. **This works because** it is built into OpenSearch and made for log analytics on that data.
- **If** dashboards must show data from **many AWS accounts**, **then** use the workspace's **organization** access mode (data sources across accounts through **AWS Organizations**), or a **customer-managed Identity and Access Management (IAM) role** that can assume roles in the other accounts. **This works because** these give the workspace permission to read data in other accounts, so one dashboard can combine accounts and Regions. The catch: the default **service-managed** role is easiest but only covers the data sources you pick; cross-account roles need the customer-managed option, where you write and scope the policies yourself.
- **If** most users only look at dashboards, **then** give them **Viewer** licenses. **This works because** AMG charges per active user per workspace per month: about **$5** for a Viewer versus about **$9** for an Editor or Admin. A workspace still needs **at least one Editor**, and a user counts as active if they log in or make API calls that month.
- **If** a data source sits in a **private subnet** of a Virtual Private Cloud (VPC), **then** add a **VPC connection** to the workspace, choosing the private subnets and security groups. **This works because** without it AMG cannot reach the private network. If queries time out, check the connection's subnets, security groups, routes and DNS.

Verified from AWS docs on 2026-11-09 (Amazon Managed Grafana overview and pricing pages).
Unconfirmed (verify): Grafana versions available; Enterprise features; network access control options; KMS options; workspace quotas; data source list completeness; audit logging.

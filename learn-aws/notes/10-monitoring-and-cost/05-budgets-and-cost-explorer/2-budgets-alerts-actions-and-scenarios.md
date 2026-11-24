# AWS Budgets – 2. Budget types, alerts, actions, cost controls and scenarios

Short notes. Each point is a fact you can be asked about.

## A. What AWS Budgets is
- **AWS Budgets** tracks cost and usage against a **target you set** and **alerts** (or **acts**) when you pass it, or are forecast to pass it.
- It is **proactive and limit-based**. Cost Explorer shows history; Anomaly Detection finds surprises; **Budgets enforces a plan**.
- **Not a hard cap**: AWS billing data arrives with a delay, so spend can exceed the threshold before you hear about it, and cost may keep rising after the alert.
- Budgets update **up to 3 times a day** (about every **8–12 hours**). Some pages say "at least once per day". Plan for a **delay of hours**, never minutes.
- Budgets can be created from the **console, CLI/API (`budgets`), CloudFormation (`AWS::Budgets::Budget`) or CDK**. Good for IaC baseline budgets per account.
- The **Budgets API/endpoint is global** (us-east-1 control plane).
- First budget **auto-enables Cost Explorer** (graph can take up to 24 hours to appear).
- By default, accounts (standalone, management, member) **can create budgets**. Member accounts create their **own**, not others'. Use IAM to control who can create/edit.
- **No cross-account** usage of budgets by IAM. A budget made in the management account for a member account is **visible only through the management account** (unless access is shared).
- **Tags on budgets** exist only for **IAM access control**; they are **not** cost allocation tags and do **not** appear in cost data.

## B. Budget types
- **Cost budget**: spend vs a dollar target (most common).
- **Usage budget**: usage amount (for example **GB stored**, **EC2 hours**, **requests**) vs a target. Good to stay inside a service limit or free tier.
- **Reservation (RI) utilization budget**: alert when RI **utilization falls below** a % (unused RIs).
- **Reservation (RI) coverage budget**: alert when **coverage falls below** a % (too much on-demand).
- **Savings Plans utilization budget**: alert when utilization drops below a threshold.
- **Savings Plans coverage budget**: alert when coverage drops below a threshold.
- **Direction rule**: cost and usage budgets alert when you go **above** (exceed). Utilization and coverage budgets alert when you go **below**.
- Utilization/coverage budgets are usually **daily** (period options differ: **daily, monthly, quarterly, annual**; cost/usage also allow **custom period**).
- **Templates (simplified)**: **Zero spend budget** (alert when spend goes above **$0.01**, for free-tier accounts), **Monthly cost budget**, **Daily Savings Plans coverage budget**, **Daily reserved instance utilization budget**. **Customize (advanced)** gives all options.

## C. Budget configuration
- **Period**: **daily, monthly, quarterly, annually**, or **custom period** (your own start/end dates, for example a project or fiscal year).
  - Custom period: end date within **3 years** of start; **does not auto-renew** (it just expires); the start date is included and the end date is excluded; forecast starts when today is within **12 months** of the end date.
  - **Recommended**: use **recurring** budgets so alerts do not silently stop.
- **Budget method (how the amount changes)**:
  - **Fixed**: same amount every period.
  - **Planned**: different amount **per month** (seasonality, launches).
  - **Auto-adjusting**: the target is set from **past usage** (for example "last 6 months average") or a **growth percentage**. It moves each period.
- **Scope filters** (narrow what is counted): **service, linked account, region, availability zone, usage type, usage type group, instance type, purchase option, platform, tag (active cost allocation tag), cost category, billing entity, charge type, record type, API operation, legal entity**, and more.
  - Filtering by **tag or cost category** gives **per-team or per-project** budgets.
  - **Tags must be activated** as cost allocation tags first (see Cost Explorer notes).
- **Cost type aggregation** (advanced): **unblended, blended, net unblended, amortized, net amortized**.
- **Charge-type options**: include or exclude **credits, refunds, upfront reservation fees, recurring reservation charges, other subscription costs, taxes, support charges, discounts**.
  - **Trap**: if credits are included, spend looks lower; exclude credits to track real usage-based spend.
  - **Amortized** is the better choice when you hold RIs/Savings Plans (smooth daily numbers).
- **Billing views** let a budget cover a **filtered set of accounts across the organization**. The target account needs `budgets:ModifyBudget`/`billing:GetBillingViewData` and a **service-linked role**; health shows `HEALTHY` or `UNHEALTHY` (for example `BILLING_VIEW_NO_ACCESS`, `INVALID_FILTER`).
- **Account leaves the Organization**: the budget **only tracks cost after it left**, **no notification** is sent. Review budgets after org changes.
- **Copy, edit, download (CSV), delete** budgets in the console. You can **copy** a budget to speed up setup.

## D. Alerts (notifications)
- Each budget can have **several alerts** (up to **5** per budget **(verify)**).
- **Threshold**: a **percentage** of the budget or an **absolute amount**.
- **Trigger on**: **Actual** spend (after it happens) or **Forecasted** spend (predicted to reach it).
- **Common practice**: alert at **50%/80% actual** and **100% forecasted** (forecast gives early warning).
- **Actual alerts** are sent **once per budget period** per threshold when first crossed.
- **Forecasted alerts** can fire **again** in the same period if the forecast falls below and rises above the threshold again.
- **Forecast needs history**: about **5 weeks** of usage data. A brand-new account cannot use forecasted alerts yet.
- **Notification channels per alert**:
  - **Email**: up to **10 email addresses**. Recipients may need to **confirm** (verification) depending on setup.
  - **One Amazon SNS topic** per alert. SNS can fan out to **SMS, email, Lambda, SQS, HTTPS**.
  - **Amazon Q Developer in chat applications** (Slack, Microsoft Teams, Chime) through an SNS topic.
  - **Budget alerts to EventBridge** are not native; use **SNS → Lambda/EventBridge Pipes** for automation **(verify)**.
- **SNS permissions**: the SNS **topic policy** must allow `budgets.amazonaws.com` to `SNS:Publish` (with `aws:SourceAccount`/`aws:SourceArn` conditions). **You must also confirm the SNS subscription.** Missing policy = silent failure.
- If the SNS topic is **encrypted with a KMS key**, the key policy must allow Budgets to use it **(verify)**.
- **Budgets Reports**: scheduled emailed **reports** about budget status (daily/weekly/monthly). **$0.01 per report delivered**.
- Alerts about budgets also show in the **Budgets dashboard** (status: OK, Exceeded, Forecasted to exceed).

## E. Budget Actions
- **Budget actions** run **automatically or after your approval** when a threshold (actual or forecasted) is crossed.
- **Three action types**:
  1. **Apply an IAM policy** to a **user, group or role** (for example a policy that **denies** launching EC2, Redshift clusters, or creating Glue jobs).
  2. **Apply a Service Control Policy (SCP)** to an **account or OU**. Only from the **management account**. Blocks new resource creation account-wide (SCPs do not affect the management account itself).
  3. **Stop specific EC2 or RDS instances** (you pick instance IDs and Region). Done through **Systems Manager automation**. Works **only in the same account**; you **cannot target EC2/RDS in another account**.
- **Approval mode**:
  - **Automatic**: runs as soon as the threshold hits.
  - **Manual approval**: a person confirms first (the budget shows a pending action). Good for production.
- You can configure **multiple actions** at the same threshold (for example deny IAM + stop dev instances).
- **Reverse / reset**: you can **reverse** an action; actions can run again each period when the budget resets.
- **Needs an IAM role** that Budgets assumes: trust `budgets.amazonaws.com`; permissions to attach/detach policies, create SCPs, and run SSM automation (use the **AWS managed policies for Budgets actions**). The **user creating the action needs `iam:PassRole`** for that role. AWS provides managed policies for this setup **(names: verify)**.
- **Only for cost and usage budgets** (not utilization/coverage budgets) **(verify)**.
- **Caveats (exam traps)**:
  - **Auto Scaling**: if the instance is in an ASG, the ASG **starts a replacement**, so "stop instance" is not enough. Add a second action that **removes permissions** from the launch role/limits the ASG.
  - Actions are subject to the same **billing data delay**.
  - **IAM deny policy** only stops **new** actions; running resources keep running and billing.
  - Stopping RDS stops compute cost, but **storage** continues; RDS auto-starts after 7 days.
  - SCP actions do **not** reduce costs of already-running resources.
  - It is **not a hard cap**.
- **Pricing for actions**: **first 2 action-enabled budgets per month are free** (regardless of how many actions each has); **each additional action-enabled budget costs $0.10 per day**.

## F. Pricing and quotas
- **Monitoring budgets and receiving notifications is free.** (No charge for cost/usage/utilization/coverage budgets and alerts.)
- **Action-enabled budgets**: first **2 free** per month; then **$0.10 per day** each.
- **Budgets Reports**: **$0.01 per report**.
- **Hidden related cost**: SNS notifications (tiny), Lambda automations, the Cost Explorer API if you query it.
- **Quotas**: number of budgets per account/management account is large (tens of thousands) **(verify the exact number)**; up to **5 alerts** per budget and **10 emails + 1 SNS topic** per alert **(verify alert count)**.
- Older material says "first 2 budgets are free, then a small per-day charge per budget". The current page says monitoring is **free** and only **action-enabled** budgets are charged. Use the current model **(verify against the pricing page)**.

## G. Budgets vs the other cost tools
- **Budgets** vs **Cost Explorer**: Budgets = **target + alert/action** (forward looking). Cost Explorer = **analysis** (look at spend).
- **Budgets** vs **Cost Anomaly Detection**: Budgets uses **your** fixed/planned number; Anomaly Detection uses **ML** to find spend that is unusual **without** a number. Anomaly Detection is better for sudden spikes in services you did not budget for.
- **Budgets** vs **CloudWatch billing alarm**: the alarm watches only the **total estimated charge** (us-east-1, needs billing alerts enabled). Budgets can filter by service/tag/account, forecast, and **act**.
- **Budgets** vs **Service Quotas**: quotas limit **how much you can create**; Budgets limits **how much you spend**.
- **Budgets** vs **usage plans/WAF (API Gateway)**: API Gateway usage plan quotas are **best effort**; AWS's own guidance is to use **Budgets for cost** and **WAF for blocking**.
- **Budgets** vs **Billing Conductor**: Conductor customizes **pro forma** cost views; **pro forma budgets** can be created from a Billing Conductor view.
- **Free Tier alerts**: Billing console can alert before **free tier** limits; a **zero-spend budget** alerts as soon as you pay anything.

## H. Cost control patterns
- **Baseline for every account**: monthly **cost budget** (50/80% actual, 100% forecast) → **SNS → email/Slack**. Deploy by **CloudFormation StackSet / CDK / Control Tower** to all accounts.
- **Per-team budgets**: filter by **active cost allocation tag** or **cost category**.
- **Per-service data budgets**: separate budgets for **Athena** (scan cost), **Glue**, **Redshift**, **EMR**, **Kinesis**, **S3 data transfer**, with Athena **workgroup data usage limits** as the actual hard control.
- **Guardrail**: at **90% forecast** → budget action: apply **IAM deny policy** (launching new expensive resources) + **stop dev EC2/RDS** with **manual approval for prod**.
- **Account-level lockdown**: at **100%** → budget action attaches an **SCP** denying create actions to a **sandbox OU**. Sandbox accounts get tight budgets.
- **Automation**: SNS topic → **Lambda** → stop EMR clusters/Glue dev endpoints/SageMaker notebooks, delete resources, open a ticket. Use when built-in actions (IAM/SCP/EC2/RDS) are not enough.
- **Commitment hygiene**: **Savings Plans utilization < 80%** and **coverage < target** alerts (daily budget).
- **Free-tier accounts / learners**: **zero-spend budget** + low monthly budget.
- **Organization view**: management account budgets with **linked account filters**; share the dashboards; review after account moves.
- **Pair with**: **Cost Anomaly Detection** (surprises), **tag policies + SCP on required tags** (clean tags), **Config** (find untagged), **Compute Optimizer/Cost Optimization Hub** (savings), **CUR 2.0 + Athena** (investigation).
- **Data-engineering cost drivers to budget** (common exam content): S3 requests and retrieval, **NAT gateway data processing**, cross-AZ/Region transfer, Athena scanned bytes, Redshift idle clusters, Glue DPU-hours, EMR idle clusters, Kinesis shards/on-demand, DynamoDB capacity, OpenSearch instance hours, CloudWatch Logs ingestion, MSK brokers, Lambda duration.

## I. Security and governance
- **IAM** for Budgets: `budgets:ViewBudget`, `budgets:ModifyBudget`, `budgets:CreateBudgetAction`, etc. Users creating budgets in the console also need permission to **view billing**, create **CloudWatch alarms** and **SNS notifications** (per AWS best practices).
- **Use a dedicated role** for programmatic Budgets API access. Use **resource-level permissions and tags** on budgets for governance.
- **Protect the SNS topic**: restrictive topic policy (service principal + source account), and confirmed subscriptions only.
- **SCPs** can restrict who may **edit or delete budgets** (deny `budgets:ModifyBudget`, `budgets:DeleteBudget`) in member accounts so teams cannot silence alerts.
- **CloudTrail** records budget creation/changes (control plane). **Config** tracks budget configuration **(verify)**.
- **Least privilege for the action role**: only the IAM policies/SCPs/instances it needs.
- Keep **emails current**: alerts to a mailbox nobody reads = no control. Prefer **SNS group alias** or chat channel.

## J. Monitoring and troubleshooting
- **Alert never arrives**:
  - Email not confirmed or in spam → verify recipients.
  - SNS topic policy missing `budgets.amazonaws.com` publish → fix the policy.
  - SNS subscription not confirmed → confirm.
  - Forecast alert but account is new (needs about 5 weeks) → wait or use actual alerts.
  - Budget filter (tag/category) is not active → activate tag first.
- **Alert arrives late** → billing data delay (8–12 hours); expected.
- **Budget shows $0** → filter too narrow, tag not activated, wrong cost type, or Cost Explorer not yet ready (up to 24 hours).
- **Action did not run** → role/permissions missing, `iam:PassRole` missing, manual approval pending, action already executed this period, or the instance was not in the same account/Region.
- **Stopped instance came back** → Auto Scaling replaced it; add an IAM/permission action.
- **Budget numbers differ from the bill** → cost type (unblended vs amortized), credits/taxes/support included or excluded, timing.
- **Budget stopped after account move** → account left the Organization (tracks only cost after leaving); recreate/review.
- **Budget status UNHEALTHY** (billing view) → access to the billing view was removed or the filter is invalid.
- **Custom period budget stopped alerting** → period ended (custom budgets do not renew).

## K. Limits and numbers to remember
- Update frequency: **up to 3 times/day**, about **8–12 hours** apart.
- Forecast needs about **5 weeks** of usage data.
- Alerts: up to **10 emails + 1 SNS topic** per alert; about **5 alerts** per budget **(verify)**.
- Actual alerts fire **once per period**; forecast alerts can **repeat**.
- Custom period: max **3 years**; forecast when within **12 months** of the end.
- **Free**: monitoring and notifications. Actions: **2 free**, then **$0.10/day**. Reports: **$0.01** each.
- Actions: **IAM policy, SCP (management account), stop EC2/RDS (same account only)**; modes **automatic / manual approval**.
- Cost Explorer related: **13 months** history, forecast **18 months**, hourly data **14 days**, API **$0.01** per paginated request.
- Cost Categories **50**, active tag keys **500**, saved reports **300**, anomaly subscriptions **100**, customer monitors **500**.

## L. Final scenario set: "If X → Y, because Z"
- If you want an email at 80% of a monthly limit → **cost budget with an 80% actual alert**, because actual alerts fire once when first reached.
- If you want an early warning before the limit → **forecasted alert at 100%**, because it predicts and fires before spend arrives (needs about 5 weeks of history).
- If an alert goes to SNS but nothing arrives → **topic policy must allow `budgets.amazonaws.com` and the subscription must be confirmed**, because Budgets cannot publish otherwise.
- If a sandbox account must stop creating resources when over budget → **budget action applying an SCP to the account/OU (from the management account)**, because SCPs block new resource creation.
- If you only want to deny a user group from launching instances → **budget action applying an IAM deny policy to the group/role**, because it targets identities.
- If dev EC2/RDS must be stopped automatically → **budget action with stop instance**, only in the **same account**; use **manual approval** for risky ones.
- If a stopped instance keeps coming back → it is in an **Auto Scaling group**, so add an action that removes launch permissions, because the ASG replaces stopped instances.
- If you need a strict hard cap on spend → **not possible with Budgets alone**; combine actions, SCPs, service-level limits (Athena workgroup limits, Service Quotas), because billing data is delayed.
- If each team needs its own budget → **budget filtered by active cost allocation tag or cost category**, because filters scope the spend counted.
- If your tag filter budget shows $0 → **activate the tag as a cost allocation tag** and wait up to 24 hours, because inactive tags are not in billing data.
- If you hold Savings Plans and want to know they are used → **Savings Plans utilization budget (daily, alert below 80%)**, because it fires when utilization **falls**.
- If you want to know when you are paying too much on-demand → **coverage budget**, because it alerts when coverage drops below target.
- If you use the free tier and want to know the moment you are charged → **zero-spend budget**, because it alerts as soon as spend is above $0.01.
- If a project runs April–July only → **custom period budget**, because it matches the project dates (it will not renew).
- If spending seasonality is known → **planned budget** (a different amount per month), because a fixed amount would trigger false alerts.
- If growth should be tracked automatically → **auto-adjusting budget**, because the target follows past usage or a growth percentage.
- If a sudden spike hits a service you never budgeted → **Cost Anomaly Detection**, because ML needs no target.
- If AWS Marketplace charges need alerts → **cost budget with the billing entity filter**, because Anomaly Detection does not cover most Marketplace charges.
- If you need to know where cost came from in detail → **Cost Explorer or CUR 2.0 + Athena**, because Budgets shows only the budget vs the amount.
- If you want to lower the bill (not just watch it) → **Cost Optimization Hub, Compute Optimizer, Savings Plans/RIs, rightsizing, delete idle resources**, because Budgets only alerts and acts on permissions.
- If member accounts must not delete budgets → **SCP denying `budgets:DeleteBudget`/`ModifyBudget`**, because the default lets account owners edit their own budgets.
- If an API Gateway usage plan quota is used for cost control → **replace with Budgets + WAF**, because usage plans are best effort and not cost controls.
- If you want to send alerts to Slack → **SNS topic + Amazon Q Developer in chat applications**, because that is the supported chat path.

Verified from AWS docs on 2026-11-01 (Budgets overview, best practices, budget actions, pricing, creation, quotas pages).
Unconfirmed (verify): the exact number of alerts per budget (about 5) and number of budgets per account; whether actions apply only to cost/usage budgets; the AWS managed policy names for budget actions and KMS-encrypted SNS requirements; RDS auto-restart after 7 days; whether Budgets alerts reach EventBridge natively; the custom-period and billing-view details beyond what the docs pages state; whether Config records budget configuration.

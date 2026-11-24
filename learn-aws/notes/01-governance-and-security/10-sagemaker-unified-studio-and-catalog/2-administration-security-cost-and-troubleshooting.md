# Amazon SageMaker Unified Studio and Catalog – 2. Administration, security, cost and troubleshooting

Short notes. Each point is a fact you can be asked about.

**Source note:** AWS pages fetched were overviews only (no quota table). Specifics are marked **(verify)** and should be checked in the Administrator Guide and Service Quotas.

## A. Administration tasks
- Admins work in the **SageMaker management console** (`console.aws.amazon.com/datazone`) or the **DataZone APIs**.
- Typical setup order **(verify)**:
  1. Choose **authentication**: IAM Identity Center, IAM or SAML.
  2. **Create the domain** (name, Region, execution/service roles, optional **KMS key**).
  3. **Enable blueprints** and create **project profiles**.
  4. **Associate AWS accounts** (via RAM) where projects may deploy.
  5. Add **users/groups** to the domain; assign **project creation** rights.
  6. Define **glossary** and **metadata forms**; set approval rules.
- **Roles**: domain execution role, service role for provisioning, **project role** per project **(verify names)**.
- **Per-project roles** give each team its own least-privilege boundary.
- **Network**: choose VPC and private subnets for project compute; create VPC endpoints (S3, Glue, Athena, STS, SageMaker, KMS, logs) for private setups.
- **Regions**: a domain lives in one Region; data in other Regions needs separate arrangements.

## B. Access control model
- **Domain membership** controls who can enter the studio; **project membership** (owner/contributor) controls what they can do in a project.
- **Data access** flows through the **project role**, not the user's IAM identity, so revoking membership removes access without touching data permissions.
- **Subscriptions** control cross-project data access; an **approver** decides.
- **Lake Formation** (and Redshift datashares) enforces the final permissions **(verify)**.
- **IAM Identity Center groups** map to domain/project roles for scalable administration.
- **SCPs/RCPs** and **permissions boundaries** still apply to project roles.
- **Least privilege**: restrict which **blueprints** and compute types each profile allows.
- **KMS**: project roles need `kms:Decrypt/GenerateDataKey` on keys protecting S3, Glue, Redshift and EMR data.
- **Audit**: CloudTrail logs domain/project/subscription API calls; Lake Formation and Athena/Redshift logs show data access; lineage and subscription history show data use.

## C. Encryption and network security
- Domain metadata can use a **customer managed KMS key** **(verify)**.
- Data stays under the **source service's encryption** (S3 SSE-KMS, Redshift KMS, EBS).
- **In transit**: TLS everywhere.
- **Private networking**: place project compute in private subnets; use interface endpoints; control egress with NAT/Network Firewall.
- **Secrets**: connections to external data use Secrets Manager.

## D. Cost
- You pay for the **underlying services** used in projects: Athena scanned data, Redshift compute/storage, EMR/Glue jobs, SageMaker AI notebooks/training/endpoints, Bedrock tokens, S3, KMS, CloudWatch, NAT/endpoints.
- The **Catalog** (DataZone-based) has its own pricing dimensions such as metadata requests/storage and data source run compute **(verify current model)**.
- **Cost levers**: limit compute choices in **project profiles**, auto-stop idle notebook spaces and clusters, schedule data source runs sparingly, tag project resources and set **budgets per project**, share data through **subscriptions/datashares** instead of copies.

## E. Monitoring and troubleshooting (symptom → cause → fix)
- **Subscription approved but query fails** → Lake Formation grants missing, S3 location not registered, KMS key not usable by the project role → fix grants/registration/key policy.
- **Asset missing from inventory** → data source run failed or lacks permissions on Glue/Redshift → check run logs and role.
- **Cannot create project** → blueprint not enabled, account not associated, role or quota issue.
- **User cannot sign in** → not assigned to domain, Identity Center/SAML mismatch.
- **Queries fail on Athena/Redshift** → VPC endpoint or network issue, project role permissions, cluster paused.
- **Lineage missing** → job does not emit lineage events or integration not enabled.
- **Cross-account fulfilment fails** → RAM share not accepted or Lake Formation cross-account version settings **(verify)**.
- **Monitoring**: CloudTrail, CloudWatch Logs of Glue/EMR/Athena, EventBridge events for catalog actions **(verify names)**.

## F. Limits
- Quotas for domains, projects, assets, data sources, subscriptions, glossary terms and account associations are in **Service Quotas** (service likely `datazone`) **(verify; not confirmed in fetched docs)**.

## G. Comparison table
| Need | SageMaker Unified Studio + Catalog | Lake Formation | Glue Data Catalog | Data Exchange |
|---|---|---|---|---|
| Business catalog + glossary | **Yes** | No | Technical only | Product listings |
| Publish/subscribe with approval | **Yes** | Manual grants | No | **Yes (external)** |
| Fine-grained data permissions | Via Lake Formation | **Yes** | No | Via source |
| Collaborative dev workspace | **Yes** | No | No | No |
| Best for | Governed internal data/AI sharing | Data lake permissions | Metadata store | External data |

## H. Exam skills mapping
- **4.1.7 Domains, domain units, projects in SageMaker Unified Studio**: domain administration.
- **4.5.6 Data access through SageMaker Catalog projects**: project-based access.
- **4.5.7 Governance framework and data sharing patterns**: sharing governance.

## I. Scenarios: "If X → Y, because Z"
- If a new analyst joins a team → **add them to the Identity Center group mapped to the project**, because project access follows membership.
- If compliance wants an audit of data use → **CloudTrail + subscription history + Lake Formation logs**, because each layer records access.
- If projects overspend → **restrict compute in project profiles, auto-stop idle resources, budgets per project**, because profiles define allowed tools.
- If a dataset must be shared widely but controlled → **publish once, approve subscriptions per consumer project**, because access is granted per subscription.
- If asset metadata is stale → **schedule data source runs**, because metadata is imported, not live.
- If external vendors supply data → **land via Data Exchange, then catalog and publish internally**, because the Catalog governs internal sharing.

Verified from AWS docs on 2026-11-04 (SageMaker Unified Studio admin and user guide overview pages).
Unconfirmed (verify): roles and names, setup order, KMS option, network details, Catalog pricing dimensions, quotas, event names, cross-account fulfilment settings.

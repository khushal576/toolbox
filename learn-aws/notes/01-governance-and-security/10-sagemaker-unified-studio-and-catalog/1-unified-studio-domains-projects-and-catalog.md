# Amazon SageMaker Unified Studio and Catalog – 1. Domains, projects, catalog and publishing

Short notes. Each point is a fact you can be asked about.

**Source note:** the AWS pages I could fetch were short overviews. Most detail below comes from general product knowledge and is marked **(verify)**. Re-check against the SageMaker Unified Studio Administrator Guide before relying on specifics.

## A. What it is
- **Amazon SageMaker Unified Studio** is one **development environment** for **data, analytics, AI and ML**: SQL, Spark, notebooks, ML, generative AI (Amazon Bedrock serverless models), workflows and Amazon Q, in a single interface. It is part of the "next generation of Amazon SageMaker".
- **Administrators** use the **SageMaker management console** (the console URL still uses `datazone`) or the **DataZone HTTPS APIs** to set up domains, users, groups and resources.
- **Authentication** options: **AWS IAM**, **AWS IAM Identity Center**, or **SAML**.
- **SageMaker Catalog** is the **governance layer** (data and AI asset catalog) built on **Amazon DataZone**: business catalog, publish/subscribe with approval, glossary, lineage, data quality.
- Capabilities covered: analytics, ML, SQL, generative AI, and **data and AI governance**.
- Pick it when: you want a **governed, collaborative workspace** with **project-level access** and a **publish/subscribe catalog**.
- Combine / avoid: for pure ETL orchestration use Glue, MWAA or Step Functions directly; for pure data-lake permissions use **Lake Formation** (the catalog uses Lake Formation for grants **(verify)**).
- DEA-C01: **4.5.6 data access through SageMaker Catalog projects**, **4.5.7 governance framework and data sharing patterns**, **2.x cataloging and metadata**.

## B. Core concepts
- **Domain**: top-level boundary holding users, projects, catalog assets, glossary and settings. Created by an admin in one AWS account and Region.
- **Domain units**: organizational hierarchy that delegates governance to business units **(verify)**.
- **Project**: the **collaboration workspace** for a team, with members, an **IAM role**, a data lakehouse area, storage, compute and tools. **Data access is granted to the project**, not to individual users.
- **Project profile**: an "uber template" for projects in a domain: a **collection of blueprints** that decides what a project gets. A profile can mark a blueprint as **enabled when the project is created** or **available later for users to enable on demand**. Only **domain administrators** can create and manage profiles.
- **Template project profiles** you can create from (verified): **All capabilities**, **SQL analytics**, **Generative AI application development**, and **Custom** (any combination you define). Choosing a template creates the matching profile in your domain.
- **Blueprint**: reusable definition of resources deployed into a project (lakehouse database, Athena, Redshift, EMR, MLflow, Bedrock, Airflow workflows) **(verify list)**.
- **Connection**: stored link to compute or data used by notebooks and queries (Athena, Redshift, Spark, S3).
- **Asset**: a cataloged resource (Glue table, Redshift table/view, S3 data, ML model, custom type) with **technical** and **business** metadata.
- **Data source**: connector that **imports metadata** (Glue Data Catalog, Redshift, others) on a schedule or on demand.
- **Business glossary** and **metadata forms**: terms and structured fields (owner, classification, retention) attached to assets.
- **Subscription**: a consumer project requests access to a published asset; an approver accepts or rejects; approved access is **fulfilled** (Lake Formation grants / Redshift datashare) **(verify mechanics)**.
- **Lineage**: tracks data movement and transformation, using **OpenLineage-style events** from supported tools **(verify sources)**.
- **Data quality**: shows quality results from Glue Data Quality or imported metrics **(verify)**.
- **Search**: faceted search and AI-assisted metadata suggestions **(verify)**.

## C. Publish → discover → subscribe → consume
1. A **producer project** creates or imports data (Glue tables, Redshift, S3).
2. A **data source run** brings technical metadata into the project inventory.
3. The producer **enriches** (descriptions, glossary terms, forms) and **publishes** the asset to the domain catalog.
4. A **consumer** searches the catalog and **requests a subscription** for their project with a justification.
5. The **approver** accepts. Access is fulfilled automatically for supported sources, manually for others **(verify)**.
6. The consumer queries the data in their project with **Athena, Redshift or Spark**, using the project's role.
7. **Revoking** the subscription removes access; **unpublishing** hides the asset from the catalog.
- **Cross-account**: consumer and producer accounts can be **associated with the domain** (shared through AWS RAM) and use cross-account Lake Formation grants **(verify)**.
- Lake Formation prerequisites: the S3 location is **registered**, and databases are governed by Lake Formation rather than the default IAM-allowed mode **(verify)**.

## D. Relationship to other services
- **Glue Data Catalog** holds technical metadata; the Catalog adds the **business layer**.
- **Lake Formation** enforces table, column, row and cell permissions when access is granted.
- **IAM / IAM Identity Center**: users sign in with SSO; each project has an **IAM role**, giving least privilege per project instead of per user.
- **Redshift**: sharing via **datashares**.
- **EMR / Glue Spark**: run inside projects with the project role.
- **Amazon Bedrock**: build generative AI apps (serverless models) inside projects **(verify guardrails/agents support)**.
- **SageMaker AI**: notebooks, training, endpoints, MLflow.
- **Amazon Q**: assistance in the studio.
- **SageMaker Lakehouse** (open Iceberg-compatible access across S3 data lakes and Redshift via the Glue Data Catalog) is the data foundation **(verify naming)**.

## E. Exam skills mapping
- **4.1.7 Domains, domain units, projects in SageMaker Unified Studio**: domains, domain units, projects.
- **4.5.6 Data access through SageMaker Catalog projects**: data access through projects.
- **2.2.6 Business data catalogs (SageMaker Catalog)**: business data catalog.
- **2.4.4 Data lineage (SageMaker ML Lineage Tracking, SageMaker Catalog)**: lineage.
- **4.5.7 Governance framework and data sharing patterns**: governance and sharing patterns.

## F. Scenarios: "If X → Y, because Z"
- **If** several teams need one governed place to share datasets, and every share must be approved, **then** use **projects in Amazon SageMaker Catalog** (the governance layer of **Amazon SageMaker Unified Studio**, built on **Amazon DataZone**) with **publish/subscribe**. A **producer project** publishes an asset to the domain catalog. A **consumer project** searches, then **requests a subscription** with a justification, and an **approver** accepts or rejects it. **This works because** access is requested, approved and **fulfilled per project**, automatically for supported sources and manually for others **(verify)**. **Revoking** the subscription removes the access again.
- **If** data access should follow a team, not each person, **then** grant data to the **project's Identity and Access Management (IAM) role** and manage who is in the project with **AWS IAM Identity Center** (single sign-on) **groups**. **This works because** in SageMaker Unified Studio **data access is granted to the project**, and members use the project role. Removing someone from the project removes their access without changing any data permissions, and each project gets its own **least-privilege** boundary.
- **If** your data lake tables have only technical details and you want business context, **then** add the **AWS Glue Data Catalog** as a **data source** and **enrich** the imported assets in SageMaker Catalog with descriptions, **business glossary** terms and **metadata forms** (fields such as owner, classification, retention). **This works because** the Glue Data Catalog holds the **technical metadata**, and SageMaker Catalog adds the **business layer** on top of it.
- **If** consumers may see only some columns or rows of a published asset, **then** use **AWS Lake Formation** filters on that asset. Lake Formation is the service that manages data lake permissions. **This works because** when a subscription is fulfilled, Lake Formation enforces **table, column, row and cell** permissions, so each consumer project gets only the part it is allowed to see.
- **If** the consumer project is in another AWS account, **then** **associate that account with the domain** (shared through **AWS Resource Access Manager (RAM)**) and let it subscribe as usual. **This works because** associated accounts can use **cross-account Lake Formation grants** to receive the data **(verify)**. One catch: the S3 location must be **registered** with Lake Formation and the databases must be governed by Lake Formation, not the default IAM-allowed mode **(verify)**.
- **If** you need to trace where data came from and how it changed, **then** use **lineage** in SageMaker Catalog. **This works because** lineage tracks data movement and transformation, using **OpenLineage-style events** sent by supported tools **(verify sources)**.
- **If** you only need table permissions on a data lake, with no business catalog or approval workflow, **then** use **AWS Lake Formation** alone. **This works because** Lake Formation already handles data lake permissions, while SageMaker Catalog adds domains, projects and publishing that you may not need.

Verified from AWS docs on 2026-11-09 (SageMaker Unified Studio user and admin guide overviews; project profiles page: template profile types and enable-at-create vs on-demand blueprints). Domains and catalog pages returned no body text, so those parts remain unverified.
Unconfirmed (verify): everything beyond the overview — profiles and blueprints, domain units, subscription fulfilment mechanics, lineage and quality sources, Bedrock/SageMaker AI asset publishing, SageMaker Lakehouse naming, DataZone branding.

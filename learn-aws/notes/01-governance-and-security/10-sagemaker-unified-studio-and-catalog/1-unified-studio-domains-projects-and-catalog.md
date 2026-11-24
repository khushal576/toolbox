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
- If teams need a governed place to share datasets with approval → **SageMaker Catalog projects with publish/subscribe**, because access is requested, approved and fulfilled per project.
- If access should follow a team → **grant to the project role and manage membership with Identity Center groups**, because permissions attach to the project.
- If you want business context on lake tables → **Glue Data Catalog as source + Catalog enrichment**, because the Catalog layers business metadata on Glue.
- If consumers must see only some columns/rows → **Lake Formation filters on the published asset**, because Lake Formation enforces fine-grained access.
- If the consumer is in another AWS account → **associate the account with the domain and subscribe**, because grants work cross-account.
- If you need to trace data origin → **lineage in the Catalog**, because it stores lineage graphs.
- If you only need table permissions → **Lake Formation alone**, because the Catalog adds overhead you may not need.

Verified from AWS docs on 2026-11-09 (SageMaker Unified Studio user and admin guide overviews; project profiles page: template profile types and enable-at-create vs on-demand blueprints). Domains and catalog pages returned no body text, so those parts remain unverified.
Unconfirmed (verify): everything beyond the overview — profiles and blueprints, domain units, subscription fulfilment mechanics, lineage and quality sources, Bedrock/SageMaker AI asset publishing, SageMaker Lakehouse naming, DataZone branding.

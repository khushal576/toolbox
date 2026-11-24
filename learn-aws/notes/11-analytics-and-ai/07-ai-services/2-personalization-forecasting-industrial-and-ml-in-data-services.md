# AWS AI services – 2. Personalization, forecasting, anomaly/fraud, industrial and ML inside data services

Short notes. Each point is a fact you can be asked about.

## A. Amazon Personalize (recommendations)
- **What**: managed **recommender system** from **user–item interaction data**; you do not manage models.
- **Datasets (dataset group)**: **Interactions** (required: user, item, timestamp, event type/value), **Items** (metadata), **Users** (metadata). **Domain dataset groups** (**ECOMMERCE**, **VIDEO_ON_DEMAND**) provide **recommenders** with prebuilt use cases ("Recommended for you", "Customers who viewed X also viewed", "Most popular", "Best sellers"). **Custom dataset groups** let you pick **recipes**.
- **Recipes (custom)**: **User-Personalization** (and **User-Personalization-v2**), **Personalized-Ranking** (re-rank a list), **SIMS** (similar items), **Popularity-Count**, **Trending-Now**, **Next-Best-Action**, **Similar-Items**, plus **Item-Affinity** **(verify current list)**.
- **Real-time**: **event tracker** + **PutEvents** API feed live behavior; recommendations update within minutes. **Filters** (include/exclude by rules), **promotions**, **metadata and context** (device, location) in requests.
- **Serving**: **campaigns** (custom, billed by **TPS-hours provisioned**) or **recommenders** (domain, billed by **requests**) and **batch inference jobs** (S3 in/out).
- **Cold start**: new items/users handled with metadata and **exploration** weights.
- **Metrics**: offline (**precision at K, coverage, mean reciprocal rank, NDCG**) and online via **A/B tests**; **metric attribution** to measure impact.
- **Pricing**: data ingestion (per GB), **training per hour**, **real-time inference per TPS-hour or per request**, batch per 1,000 recommendations. **Idle campaigns still bill** (set low `minProvisionedTPS`; delete unused).
- **Security**: IAM, **KMS** for dataset buckets, VPC endpoints, no cross-customer data use.
- **Pipeline**: events (Kinesis/Firehose) → S3 → Personalize import jobs/PutEvents → API/Lambda → app. **Status**: no 2026 lifecycle notice found in the summaries I read **(verify)**.
- **Choose vs SageMaker**: Personalize for **fast recommenders**; SageMaker/Factorization Machines/custom for **special algorithms** or full control.

## B. Amazon Forecast (time-series forecasting)
- **Status**: **maintenance mode (announced 29 Jul 2024)**; the **migration guide points to SageMaker Canvas** (and Autopilot/AutoML time-series, **DeepAR**, or open-source like **AutoGluon-TimeSeries**) **(verify details)**. Do not start new builds on Forecast.
- **What it did**: **target time series + related time series + item metadata**, **predictors** (AutoPredictor ensembles of **ARIMA, ETS, NPTS, Prophet, DeepAR+, CNN-QR**), **forecasts at quantiles (P10/P50/P90)**, **explainability** and **what-if analyses**.
- **Replacement choices**: **SageMaker Canvas** (no-code time-series), **AutoML API v2 time-series**, **DeepAR** built-in algorithm, **Chronos/foundation time-series models** on SageMaker JumpStart/Bedrock Marketplace **(verify)**, Athena/Redshift ML for simple cases.

## C. Fraud and anomaly detection options
- **Options**: **Random Cut Forest** (SageMaker built-in; also **Kinesis Data Analytics/Managed Flink RANDOM_CUT_FOREST** function), **CloudWatch anomaly detection**, **OpenSearch anomaly detection plugin**, **Rekognition Custom Labels** (visual), **SageMaker AI custom models**, **Cost Anomaly Detection** (cost spend only).

## D. Entity resolution and data collaboration
- **AWS Entity Resolution**: match and link **records referring to the same real-world entity** (customers, products) across datasets **without building your own ML**.
  - **Matching workflows**: **rule-based** (exact/fuzzy rules), **ML-based** (trained model), and **provider-based** (third-party **ID** services, for example LiveRamp/UID2/ID resolution).
  - **Input**: **Glue Data Catalog tables** on S3 (schema mapping); **output** to S3 with **MatchID**; **incremental** processing; **ID namespaces** and **ID mapping workflows** for privacy-safe cross-party matching.
  - Use for **customer 360, deduplication, clean rooms prep**.
  - **Pricing**: **per record processed** (varies by workflow type) **(verify)**.
- **AWS Clean Rooms** (collaboration without sharing raw data) and **Clean Rooms ML**: train and run **lookalike/audience models** on combined data **without exposing each party's data**; also **custom ML** models inside clean rooms **(verify)**. Controls: **collaboration**, **configured tables**, **analysis rules**, **differential privacy**, **cryptographic computing (C3R)**.
- **Pattern**: Entity Resolution (match IDs) → Clean Rooms (joint analysis/ML) → results to S3/QuickSight.

## E. ML inside data services (SQL-first ML)
- **Amazon Redshift ML**: `CREATE MODEL ... FROM (SELECT ...) FUNCTION fn(...)` **trains with SageMaker (Autopilot, XGBoost, KMeans, custom) behind the scenes**, then you **call predictions in SQL**. Data is exported to **S3**, trained in SageMaker, model deployed as a **SQL function** (local inference in Redshift for supported models). Also **remote inference** to SageMaker endpoints and **LLM functions via Bedrock** **(verify)**. **Needs IAM role and an S3 bucket**; **cost = SageMaker training + S3 + Redshift** (CREATE MODEL has a cost limit setting like `MAX_CELLS`/`MAX_RUNTIME`).
- **Amazon Athena ML** (`USING EXTERNAL FUNCTION ... SAGEMAKER '<endpoint>'`): call **SageMaker endpoints** from Athena SQL for inference on S3 data (you must host the endpoint). Athena can also call **UDFs in Lambda**.
- **Aurora ML (Aurora MySQL/PostgreSQL)**: SQL functions that call **SageMaker endpoints**, **Comprehend** (sentiment/entities) and **Bedrock** (text generation/embeddings) from queries (`aws_ml` / `aws_bedrock`-style extensions; **verify names**). Needs **IAM role attached to the cluster**.
- **Neptune ML**: **graph neural networks (DGL)** with SageMaker to predict **node/edge properties** and **link prediction** inside Neptune queries (Gremlin/SPARQL/openCypher).
- **QuickSight/Quick ML insights**: **anomaly detection (Random Cut Forest)** and **forecasting** on dashboards; **Q in Quick** natural-language queries now part of **Amazon Quick**.
- **Glue / EMR**: Spark MLlib; **Glue ML transforms (FindMatches)** for fuzzy dedup of records **(verify status; Glue ML Transforms have moved toward Entity Resolution)**.
- **DynamoDB/OpenSearch**: **OpenSearch ML Commons/neural search** and **Neural Sparse**, **k-NN**; **OpenSearch anomaly detection**.
- **Choose**: SQL analysts who want quick models → **Redshift ML**; serve an existing model into SQL → **Athena ML or Aurora ML**; relationship-based predictions → **Neptune ML**.

## F. Healthcare and specialized
- **AWS HealthLake**: HIPAA-eligible **FHIR R4 data store** with **NLP (Comprehend Medical) that extracts and indexes medical entities**; supports FHIR REST APIs, bulk **import/export** to S3, **SMART on FHIR**, analytics through Athena/Lake Formation **(verify features)**.
- **Amazon Comprehend Medical**, **Transcribe Medical**, **AWS HealthScribe** (clinical documentation from conversations) **(verify status)**.
- **Amazon Omics / HealthOmics** (genomics) **(verify)**; **Amazon Kinesis Video Streams** (ingest/store video for Rekognition/SageMaker) is active.
- **AWS IoT**: use **IoT Greengrass ML inference** with SageMaker-trained models at the edge.

## G. AI-assisted operations and developer services
- **Amazon DevOps Guru**: ML-based **operational anomaly detection** for applications (CloudWatch metrics, CloudTrail, Config, X-Ray) with **insights and recommendations** (RDS "Proactive insights"). **Status not listed in the lifecycle summary I read (verify).**
- **Amazon CodeGuru Reviewer**: ML code review. **Maintenance mode** (announced 7 Oct 2025). **CodeGuru Profiler** status **(verify)**; AWS points to **Amazon Q Developer/Kiro** and other tools.
- **AWS Compute Optimizer, Trusted Advisor**: ML-driven recommendations (see cost notes).
- **Amazon Macie**: ML/pattern **sensitive data discovery in S3**; **Amazon GuardDuty**: ML threat detection; **Amazon Inspector**: vulnerability scanning (not ML-first).
- **Amazon Connect** (contact center) with **Contact Lens** (speech analytics), **Q in Connect**, **Customer Profiles** **(verify names)**.

## H. Scenarios: "If X → Y, because Z"
- If an e-commerce site needs "recommended for you" within weeks → **Personalize domain recommender (ECOMMERCE)**, because it ships ready-made recommenders from interaction data.
- If clickstream must influence recommendations immediately → **Personalize event tracker + `PutEvents`**, because real-time events update recommendations.
- If idle Personalize cost is high → **lower campaign TPS or delete unused campaigns**, because campaigns bill by provisioned TPS-hours.
- If you were using Amazon Forecast → **move to SageMaker Canvas/AutoML time-series or DeepAR/AutoGluon**, because Forecast is in maintenance and AWS points to Canvas.
- If two systems hold the same customers with different IDs → **AWS Entity Resolution (rule/ML-based workflow)**, because it links records without custom ML.
- If a retailer and a brand want joint audience insights without sharing raw data → **Clean Rooms (and Clean Rooms ML)**, because collaborations keep data private.
- If analysts want a churn model using only SQL → **Redshift ML `CREATE MODEL`**, because SageMaker trains behind the scenes and the model becomes a SQL function.
- If Aurora rows need sentiment on insert → **Aurora ML calling Comprehend (or Bedrock)**, because SQL functions invoke the services.
- If link prediction in a knowledge graph is needed → **Neptune ML**, because it trains GNNs on graph data.
- If clinical notes must be searchable as FHIR resources → **HealthLake (with Comprehend Medical)**, because it indexes extracted medical entities.
- If you need ops anomaly insights without building models → **DevOps Guru** (verify status first), because it analyzes metrics and logs with ML.

Verified from AWS docs on 2026-11-01 only through the lifecycle summary (Forecast maintenance 29 Jul 2024; CodeGuru Reviewer maintenance). The feature descriptions for Personalize, Entity Resolution, Clean Rooms, Redshift/Athena/Aurora/Neptune ML, HealthLake and DevOps Guru are from earlier knowledge and were not re-fetched.
Unconfirmed (verify): current Personalize recipe list and status; Forecast migration details; Entity Resolution pricing and provider list; Clean Rooms ML feature set; Aurora/Redshift ML extension and function names; Glue FindMatches status; HealthLake and HealthScribe status; DevOps Guru and CodeGuru Profiler status; Omics naming.

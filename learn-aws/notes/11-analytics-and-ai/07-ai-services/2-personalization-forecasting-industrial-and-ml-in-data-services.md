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
- **If** an e-commerce site needs "Recommended for you" within weeks, **then** use an **Amazon Personalize** **domain dataset group** for **ECOMMERCE** with a ready-made **recommender**. Personalize is a managed recommender system. **This works because** domain recommenders come with prebuilt use cases ("Recommended for you", "Customers who viewed X also viewed", "Best sellers") built from your **user–item interaction data**, so you do not build or manage models. Recommenders are billed **per request**.
- **If** clickstream behavior must change recommendations quickly, **then** use a Personalize **event tracker** and the **`PutEvents`** API. **This works because** live events feed the model, and recommendations update **within minutes**. You can also add **filters** and context (device, location) in requests.
- **If** Personalize costs are high while traffic is low, **then** **lower the campaign's `minProvisionedTPS`** or **delete unused campaigns**. **This works because** custom **campaigns** are billed by **provisioned TPS-hours** (transactions per second), so an idle campaign still bills for the capacity it keeps ready.
- **If** you were using **Amazon Forecast**, **then** move to **Amazon SageMaker Canvas** (no-code time-series), **AutoML time-series**, the **DeepAR** built-in algorithm, or open-source **AutoGluon-TimeSeries** **(verify details)**. **This works because** Forecast has been in **maintenance mode** since **29 Jul 2024**, and the AWS migration guide points to **SageMaker Canvas**. Do not start new builds on Forecast.
- **If** two systems hold the same customers under different IDs, **then** use **AWS Entity Resolution** with a **rule-based** or **ML-based** matching workflow. **This works because** Entity Resolution matches and links records that refer to the **same real-world entity**, without you building your own ML. It reads **AWS Glue Data Catalog** tables on S3 and writes output to S3 with a shared **MatchID**.
- **If** a retailer and a brand want joint audience insights without sharing raw data, **then** use **AWS Clean Rooms** and **Clean Rooms ML**. **This works because** a Clean Rooms **collaboration** allows joint analysis under **analysis rules**, **differential privacy** and **cryptographic computing (C3R)**, so neither party sees the other's raw data. Clean Rooms ML trains **lookalike/audience models** on the combined data without exposing it.
- **If** analysts want a churn model using only SQL, **then** use **Amazon Redshift ML** `CREATE MODEL`. **This works because** Redshift exports the data to **S3**, **Amazon SageMaker** trains the model behind the scenes, and the model comes back as a **SQL function** you call for predictions. It needs an **IAM role and an S3 bucket**, and cost is **SageMaker training + S3 + Redshift** (limit it with settings like `MAX_RUNTIME`).
- **If** Aurora rows need a sentiment score when they are inserted, **then** use **Aurora machine learning (Aurora ML)** to call **Amazon Comprehend** (or **Amazon Bedrock**) from SQL. **This works because** Aurora ML adds SQL functions that invoke these services from inside queries (extension names: **verify**). It needs an **IAM role attached to the cluster**.
- **If** you need link prediction in a knowledge graph, **then** use **Amazon Neptune ML**. Neptune is a graph database. **This works because** Neptune ML trains **graph neural networks (GNNs)** with SageMaker on your graph data, then predicts **links** and **node/edge properties** inside Neptune queries (Gremlin, SPARQL, openCypher).
- **If** clinical notes must be searchable as **Fast Healthcare Interoperability Resources (FHIR)** resources, **then** use **AWS HealthLake**, which uses **Amazon Comprehend Medical**. HealthLake is a HIPAA-eligible FHIR R4 data store. **This works because** it extracts medical entities from the notes with natural language processing and **indexes** them, so they can be searched through FHIR APIs **(verify features)**.
- **If** you need operational anomaly insights without building models, **then** use **Amazon DevOps Guru** (verify status first). **This works because** DevOps Guru uses ML to analyze **CloudWatch metrics, CloudTrail, Config and X-Ray** data and returns **insights and recommendations**. Its lifecycle status was not confirmed in the notes, so check it before relying on it.

Verified from AWS docs on 2026-11-01 only through the lifecycle summary (Forecast maintenance 29 Jul 2024; CodeGuru Reviewer maintenance). The feature descriptions for Personalize, Entity Resolution, Clean Rooms, Redshift/Athena/Aurora/Neptune ML, HealthLake and DevOps Guru are from earlier knowledge and were not re-fetched.
Unconfirmed (verify): current Personalize recipe list and status; Forecast migration details; Entity Resolution pricing and provider list; Clean Rooms ML feature set; Aurora/Redshift ML extension and function names; Glue FindMatches status; HealthLake and HealthScribe status; DevOps Guru and CodeGuru Profiler status; Omics naming.

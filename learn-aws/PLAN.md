# Remaining work plan (approved 2026-11-01)

Quality bar for every file: **150–200 bullets**, short notes per `TEMPLATE.md`, limits/defaults/traps, symptom → cause → fix, "If X → Y, because Z" scenarios at the end, `Verified from AWS docs on <date>` footer with the (verify) list. Research current AWS docs before writing. Note retirements and renames.

## Wave 1 – re-deepen thin guides + streaming
| Folder | Files | Scope |
|---|---|---|
| `06-streaming-and-messaging/03-kinesis-data-streams/` (re-deepen) | 4 | (1) concepts, records, shards, partition keys, capacity modes (On-demand Standard/Advantage, provisioned), sizing; (2) producers: SDK, KPL deep (aggregation, collection, TTL, backpressure), Kinesis Agent, CloudWatch Logs subscriptions, IoT, DMS, EventBridge Pipes; resharding mechanics; (3) consumers: GetRecords, EFO, KCL 2.x/3.x internals (leases, checkpoints, balancing, failover, shutdown, multi-stream), Lambda ESM deep, Flink/Firehose/Spark/Redshift streaming ingestion, KDS for DynamoDB vs DynamoDB Streams, ordering/duplicates/idempotency, cross-Region patterns, data delivery (Iceberg/S3); (4) security, monitoring, cost, limits, troubleshooting, KDS vs SQS vs MSK vs Firehose vs EventBridge table, scenarios. Glue Schema Registry with KDS. Kinesis Video Streams short section. |
| `06-streaming-and-messaging/04-firehose/` | 3 | (1) sources, destinations, buffering, retries, S3 backup, error output; (2) Lambda transforms, record format conversion (Parquet/ORC, Glue schema), dynamic partitioning, Iceberg/S3 Tables, Redshift COPY, OpenSearch, Splunk, HTTP, Snowflake, CloudWatch Logs decompression; (3) security, VPC delivery, cost, monitoring, limits, scenarios |
| `06-streaming-and-messaging/05-managed-flink/` | 4 | (1) Managed Service for Apache Flink (rename from Kinesis Data Analytics; KDA for SQL shut down), architecture, KPUs, Studio notebooks; (2) DataStream/Table/SQL APIs, windows, watermarks, event time, state; (3) checkpoints, savepoints, snapshots, exactly-once, scaling/parallelism, connectors (Kinesis, MSK/Kafka, S3, Iceberg, DynamoDB), versions/upgrades; (4) security, cost, monitoring, troubleshooting, scenarios |
| `06-streaming-and-messaging/06-msk/` | 4 | (1) Kafka concepts, MSK provisioned (standard/Express brokers), MSK Serverless, storage, tiered storage; (2) topics, partitions, replication, ISR, acks, consumer groups, configs, sizing; (3) security (IAM, SASL/SCRAM, mTLS, TLS, ACLs, multi-VPC/private connectivity), MSK Connect, MSK Replicator, Glue Schema Registry; (4) monitoring, cost, scaling, limits, troubleshooting, scenarios |
| `06-streaming-and-messaging/01-sqs-and-sns/` | 3 | (1) SQS standard vs FIFO, visibility timeout, long polling, DLQ/redrive, delay, message size/extended client, Lambda integration; (2) SNS topics, subscriptions, filtering, FIFO topics, fan-out, delivery retries, DLQ, message archiving; Amazon MQ short section; (3) security, cost, limits, troubleshooting, scenarios |
| `06-streaming-and-messaging/02-eventbridge/` | 3 | (1) event buses, rules, patterns, targets, input transforms; (2) Pipes, Scheduler, archive/replay, schema registry, API destinations, cross-account/Region; (3) security, quotas, cost, troubleshooting, scenarios |
| `11-analytics-and-ai/01-quick-sight/` (re-deepen) | 3 | datasets deep (joins, custom SQL, calculated fields, LAC, parameters, filters), refresh/incremental, sources (S3 manifest, Athena, Redshift, Lake Formation), visuals/geospatial/themes/alerts, Q topics, embedding flows, admin/editions, security, cost math, limits, Quick rename context |
| `05-data-processing/07-emr/` (re-deepen) | 5 | keep existing 4, deepen each, add (5) Spark/Hive/Presto tuning cookbook, lakehouse formats, EMR Studio, Ranger/Lake Formation setup, Hadoop migration |
| `03-storage/03-aws-backup/` (re-deepen) | 3 | deepen plans/vaults/resource support, Vault Lock/air-gapped vault, organizations, restore testing, audit, cost |

## Wave 2 – orchestration, security, monitoring
| Folder | Files |
|---|---|
| `08-orchestration-and-integration/01-step-functions/` | 4 |
| `08-orchestration-and-integration/02-mwaa/` | 3 |
| `08-orchestration-and-integration/04-appflow/` | 2 |
| `01-governance-and-security/01-iam-and-sts/` (incl. Identity Center, policy evaluation, SCP/RCP, Access Analyzer) | 4 |
| `01-governance-and-security/05-organizations-and-control-tower/` | 2 |
| `01-governance-and-security/02-kms/` | 3 |
| `01-governance-and-security/03-secrets-manager-and-parameter-store/` | 2 |
| `10-monitoring-and-cost/01-cloudwatch/` (incl. X-Ray, Application Signals) | 4 |
| `10-monitoring-and-cost/02-cloudtrail/` (incl. CloudTrail Lake) | 3 |
| `10-monitoring-and-cost/03-config/` | 3 |

## Wave 3 – networking and the rest, plus AI/ML audit
| Folder | Files |
|---|---|
| `02-networking/01-vpc-and-privatelink/` (incl. Direct Connect, VPN, Transit Gateway) | 4 |
| `02-networking/02-route-53/` | 3 |
| `02-networking/05-cloudfront/` | 3 |
| `01-governance-and-security/06-macie/` | 2 |
| `01-governance-and-security/07-waf-and-shield/` | 2 |
| `01-governance-and-security/08-security-hub-guardduty-inspector/` | 2 |
| `01-governance-and-security/09-data-exchange/` | 1 |
| `01-governance-and-security/10-sagemaker-unified-studio-and-catalog/` | 2 |
| `10-monitoring-and-cost/04-systems-manager/` | 2 |
| `10-monitoring-and-cost/06-managed-grafana/` | 1 |
| `10-monitoring-and-cost/07-well-architected-tool/` | 1 |
| Audit and re-deepen this session's AI/ML folders (bedrock, vector-stores, kendra, amazon-q, sagemaker-ai, ai-services) | as needed |

## After each wave
Update category `README.md` files, `EXAM-COVERAGE.md`, `CLAUDE.md` reference list, run a bullet-count check, list "(verify)" items for the owner.

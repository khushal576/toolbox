# Streaming And Messaging

Moving data and events in real time.

| Service folder | What it is | Status |
|---|---|---|
| `kinesis-data-streams/` | Shards, capacity modes (On-demand Standard/Advantage, provisioned), KPL and producers, resharding, KCL 3.x, EFO, Lambda ESM, S3/Iceberg delivery, security, cost (4 files) | written |
| `firehose/` | Managed delivery to S3, Iceberg/S3 Tables, Redshift, OpenSearch, Splunk, Snowflake, HTTP; Lambda transforms, Parquet/ORC conversion, dynamic partitioning, security, cost (3 files) | written |
| `managed-flink/` | Managed Service for Apache Flink (KDA for SQL shut down): KPUs, Studio, windows/watermarks/state, checkpoints, exactly-once, autoscaling, connectors, security, cost (4 files) | written |
| `msk/` | Kafka concepts, Standard vs Express vs Serverless, tiered storage, RF/minISR/acks, exactly-once, IAM/SCRAM/mTLS, multi-VPC, MSK Connect, Replicator, Schema Registry, integrations, monitoring, pricing (4 files) | written |
| `sqs-and-sns/` | SQS standard vs FIFO (high-throughput, fair queues), visibility timeout, polling, DLQs and redrive, Lambda ESM; SNS topics, filtering, fan-out, retries, FIFO archive/replay; short Amazon MQ; security/KMS, monitoring, pricing (3 files) | written |
| `eventbridge/` | Event buses (default/custom/partner, new Sept 2026 Custom Event Bus vs Classic), rules, event patterns and content filters, targets, input transformers, retries/DLQ, bus logging, global endpoints, Pipes, Scheduler, archive/replay, schema registry, API destinations, cross-account routing, security, quotas, pricing (3 files) | written |

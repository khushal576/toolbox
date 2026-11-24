# Data Processing

Engines that query and transform data.

| Service folder | What it is | Status |
|---|---|---|
| `glue/` | Serverless ETL, Data Catalog, crawlers, partitions, streaming ETL, workflows, Data Quality, DataBrew, Schema Registry, Glue Studio/console UI, security, cost, monitoring (5 files) | written |
| `athena/` | Serverless SQL on S3: workgroups, CTAS/UNLOAD, Iceberg, partition projection, federated query and connectors, Lake Formation, cost, log analysis, Spark (5 files) | written |
| `emr/` | EMR on EC2, EMR Serverless, EMR on EKS: clusters, scaling, security, cost, tuning, lakehouse formats, Studio, Ranger/Lake Formation, Hadoop migration (5 files) | written |
| `lambda/` | Serverless functions: execution model, event sources, concurrency, VPC, SAM, cost, monitoring (4 files) | written |
| `aws-batch/` | Container batch jobs at scale: compute environments, queues, array jobs, Spot (2 files) | written |
| `ecs-eks-ecr/` | Containers: ECS, EKS and ECR, Fargate, Managed Instances, Auto Mode (4 files) | written |
| `ec2/` | Virtual servers: instance types, purchase options, Auto Scaling, networking, security (3 files) | written |

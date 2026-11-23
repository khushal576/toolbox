# Writing MCQs for Learn AWS

One JSON file per service, at `learn-aws/mcq/<NN-category>/<NN-service>.json` (same path as the service folder under `learn-aws/notes/`, for example `mcq/03-storage/01-s3.json`). The server picks them up at start-up and adds a **Quiz** to that service and to the **Practice** page. `tests/unit/test_learn_aws.py` rejects a bad file (bad shape, duplicate id, invalid answer index, missing `source` note) — run it before rebuilding.

## Format

```json
{
  "questions": [
    {
      "id": "s3-001",
      "skill": "1.1.6",
      "source": "4-performance-events-cost-and-operations.md",
      "q": "A company needs every object upload to trigger several independent consumers, filtered by key prefix. Which design is best?",
      "options": [
        { "t": "S3 Event Notifications directly to one Lambda", "why": "Wrong: one target per prefix rule and no fan-out." },
        { "t": "S3 to EventBridge, with one rule per consumer", "why": "Right: rules filter on key prefix and each rule can have its own targets." },
        { "t": "A cron job that lists the bucket", "why": "Wrong: polling is slow and costs requests." },
        { "t": "CloudTrail data events to SNS", "why": "Wrong: works, but is the heavier, delayed path." }
      ],
      "answer": [1],
      "explain": "EventBridge is the S3 event path that supports fan-out and content filtering.",
      "remember": "Several consumers or filtering on an S3 upload → route through EventBridge, not a direct notification.",
      "variants": [
        "Only one target and no filtering → a direct S3 event notification is enough.",
        "The consumers must be triggered by a schedule → EventBridge Scheduler."
      ]
    }
  ]
}
```

| Field | Rule |
|---|---|
| `id` | Unique across the repo, for example `s3-001`. Progress is saved by id, so never reuse or renumber one. |
| `q` | The scenario and question. Backticks make `code`. |
| `options` | 3 to 6 options. **Every option needs `t` (text) and `why`** (why it is right, or why it is wrong). |
| `answer` | List of correct option indexes, counted from 0. One item = pick one. Two or more = "Choose N". |
| `explain` | Optional one-line summary shown under the result. |
| `remember` | The rule of thumb behind the question, in 1–2 sentences (shown as the **Remember** box after answering). Write it so it also answers reworded versions of the question. |
| `variants` | 2–4 short "If the question changes → answer" lines: the same concept with one detail swapped (a different service, a different condition). Shown under **If the question changes**. |
| `skill` | Optional exam skill from `EXAM-COVERAGE.md` (for example `3.2.1`). Shown after answering. |
| `source` | Optional note file the question comes from. Becomes an "open notes" link in the review. |

## Writing rules (DEA-C01 style)
- Short scenario, one decision: cost, latency, scale, operations effort, security or reliability. Test judgement, not trivia.
- Wrong options are real AWS services or settings that look plausible but fail one requirement in the scenario.
- Options are shuffled on screen, so never write "all of the above", "both A and B" or refer to letters.
- Every question gets a `remember` and `variants`, so a slightly reworded exam question can still be solved from the rule.
- Quality over quantity. Size each service by how much the exam uses it (budget below). Each question must be answerable from the notes.
- Take every fact from the notes. Anything marked "(verify)" there must not become the correct answer.

## Question budget by exam importance
Ranking comes from how many DEA-C01 skills reference a service in `EXAM-COVERAGE.md`, adjusted for cross-cutting topics (IAM and KMS appear inside almost every service).

| Tier | Questions | Services |
|---|---|---|
| **A: core** | 30–40 | IAM and STS (39, done), KMS (32, done), Glue, Lambda, S3 (36, done), Kinesis Data Streams, Firehose, Managed Flink, MSK, Redshift, Athena, DynamoDB, Lake Formation, EventBridge, SQS and SNS |
| **B: important** | 18–25 | EMR, RDS and Aurora, ECS/EKS/ECR, EC2, AWS Batch, Step Functions, MWAA, CloudFormation/CDK/SAM, CI/CD, CloudWatch, CloudTrail, DMS, Elastic Load Balancing |
| **C: supporting** | 8–12 | DocumentDB, OpenSearch, API Gateway, EBS and EFS, VPC and PrivateLink, NAT Gateway, AWS CLI, DataSync, Transfer Family, Secrets Manager, Config, Systems Manager, Macie, Security Hub, Organizations, AWS Backup, Quick Sight, MemoryDB, Neptune, Keyspaces, SageMaker AI, SageMaker Unified Studio, AppFlow, Route 53, CloudFront |
| **D: light** | 4–6 | Snow Family, Application Migration, Budgets and Cost Explorer, Data Exchange, Bedrock, Kendra, Amazon Q, AI services, Vector stores, Managed Grafana, Well-Architected Tool |

Spend the extra questions on facts the exam asks: choosing between services, limits and defaults that change a design, security and troubleshooting scenarios. Skip trivia.

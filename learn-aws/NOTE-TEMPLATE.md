# Template for a service folder

Copy this layout into `<category>/<service>/`. Files are numbered only to show reading order. Keep the number of files small: the whole point is short notes, about 150–200 points per file.

## Rules
- Short notes. One idea per bullet. A bullet may take 2–3 lines when the idea needs it.
- Each bullet should be enough to write an exam question from.
- No stories and no long theory paragraphs.
- Name the "why" and the catch in a few words.
- Each service folder stands alone. Do not tell the reader to open another service to understand this one.
- Cost and optimization are NOT separate files for small services. They are sections inside a file.
- Mark any fact not confirmed in current AWS docs with **(verify)**.
- End every file with: `Verified from AWS docs on <date>` and the list of unconfirmed items.

## Section order inside a service (use as headings, spread over files)
1. What it is, pick it when / avoid it when, versus nearest alternatives
2. How it works (core ideas, types, modes, sizing)
3. Getting data in and out, connecting, integrations
4. Performance
5. Availability, backup, recovery, replication, retention, deleting data
6. Security (authentication, authorisation, encryption, private network, audit, privacy)
7. Cost (what you pay, how to cut it)
8. Monitoring and troubleshooting (symptom → cause → fix)
9. Limits and numbers
10. Scenarios: "If X → Y, because Z"

## File count guide
- Small service (one clear job): 1 file, all sections.
- Medium service: 2 files (basics + operations/security), or one file per related service when two are combined (for example EBS + EFS).
- Big service (S3, Redshift, Glue, DynamoDB, Kinesis): 3–5 files, grouped by topic in reading order. Each file ends with its own scenarios.

## Example file split for a big service (S3)
1. basics-and-storage-classes
2. replication-backup-and-recovery
3. security-and-access
4. performance-events-cost-and-operations
5. s3-tables-and-iceberg

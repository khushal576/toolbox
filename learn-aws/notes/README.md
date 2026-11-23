# AWS Service Guides

Plain-English refresher guides, one folder per AWS service. Open any service, read the files in order, and you can answer questions about it and design with it.

## How to use
- **Read it as a website:** open `index.html` in a browser (works offline, no server). Rebuild it after any change with `python3 build.py`. See [mcq/README.md](mcq/README.md) for the quiz format.
- Pick a category, then a service folder.
- Read the files **in number order**: what it is, how it works, setup, data in/out, performance, availability and backup, security, cost, troubleshooting, limits, scenarios.
- Each service folder stands alone. You never need another folder to understand it.
- `11-scenarios.md` in each service is the quick test: cover the answer, try to say it.
- To add a service: copy the layout in [TEMPLATE.md](TEMPLATE.md) into the right category folder.
- [EXAM-COVERAGE.md](EXAM-COVERAGE.md) maps the AWS Certified Data Engineer Associate guide (v1.1) to these folders.

## Categories
- [governance-and-security](./01-governance-and-security/README.md): Who can see what, keys, secrets, privacy.
- [networking](./02-networking/README.md): Private and public network paths.
- [storage](./03-storage/README.md): Where data lives: object, block, file storage and backups.
- [databases](./04-databases/README.md): Databases and warehouses: pick the right store for the access pattern.
- [data-processing](./05-data-processing/README.md): Engines that query and transform data.
- [streaming-and-messaging](./06-streaming-and-messaging/README.md): Moving data and events in real time.
- [migration-and-transfer](./07-migration-and-transfer/README.md): Getting data and workloads into AWS.
- [orchestration-and-integration](./08-orchestration-and-integration/README.md): Connecting steps and systems together.
- [developer-tools](./09-developer-tools/README.md): Building and deploying pipelines.
- [monitoring-and-cost](./10-monitoring-and-cost/README.md): Watching, auditing and paying for things.
- [analytics-and-ai](./11-analytics-and-ai/README.md): BI and AI touchpoints for data engineers.

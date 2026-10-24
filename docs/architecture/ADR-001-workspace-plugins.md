# ADR-001: Toolbox becomes a plugin workspace

- **Status:** Accepted (owner, 2026-10-24)
- **Replaces:** the "one repo, one Dockerfile, one container, no gateway" decision in `CLAUDE.md`
  (it stays in force for phases 0–B and is replaced from phase C on).
- **Plan:** `docs/roadmap/ROADMAP.md` (sessions, order, status).

## Context
- Toolbox today: one container, one uvicorn process (`--workers 1`), every tool imported and mounted
  at startup by `main.py`. 20 tools, image about 1.3 GB (mostly TeX Live for LaTeX to PDF).
- Seven tools hold state in process memory (DataFrame Studio, SQL Studio, DuckLab, Data Syncer,
  Schema Copy, Data Dumper, SSH & SFTP). Six keep SQLite files on Docker volumes (Schema Map, Vault,
  Data Syncer, Schema Copy, Data Dumper, SSH & SFTP).
- The owner expects **1000+ tools**, wants **only the tools in use to consume resources**, expects
  some tools (DataDiff) to be called by **hundreds of other apps**, and may add **more nodes** later.

## Decision
1. **Tools become plugins** described by a `manifest.yaml` (kind, runtime, tier, state, resources,
   scaling, dependencies). The workspace discovers manifests; custom apps can be dropped into a
   mounted `plugins/` folder without rebuilding.
2. **Lazy loading:** a tool's code is imported on its first request; disabled tools are never loaded.
3. **Tiers decide where a tool runs**, not one container per tool:
   - Tier 1 static/client-side (no server cost), tier 2 light stateless Python (shared "light"
     runtime), tier 3 data-heavy (shared "data" runtime, scalable), tier 4 special/heavy image
     (LaTeX, SSH, Postgres client tools: own runtime, started on demand).
   - A handful of runtime images host all tools. 1000 tools ≠ 1000 containers.
4. **No state in process memory or on local disk:** sessions and queues in **Redis**, durable records
   in **Postgres**, files in **S3-compatible storage** (bundled SeaweedFS since B1 — MinIO community images were discontinued in 2025). This is what makes multiple workers and multiple
   nodes possible.
5. **Plugins talk over HTTP, not by importing each other.** Shared heavy logic (DataDiff) becomes a
   versioned API with replicas; long work goes through an **RQ** job queue.
6. **Gateway + supervisor** (from phase C): the gateway serves the workspace UI and routes
   `/tools/<name>` to the right runtime; the supervisor starts runtimes on first use, stops them when
   idle, applies CPU/memory limits, and scales replicas by queue length. Docker access only through a
   docker-socket-proxy.
7. **Multiple nodes later** (phase F): k3s + KEDA on own machines, or ECS Fargate in the cloud. Same
   images and state services; no code change in tools.

## Rejected
- **ZooKeeper** (and similar coordination services): solves leader election/locks/config for
  distributed systems; does not schedule, start, route or scale containers. Heavy and unnecessary.
- **Kafka, service mesh:** far more than the load needs; RQ on Redis covers the job queue.
- **One container per tool:** does not scale to 1000 tools (memory, images, ops).
- **Kubernetes now:** costs ~0.5 GB RAM and ops effort on a single laptop for no gain. Adopt in F.
- **Keeping everything in one process forever:** cannot unload Python modules, cannot isolate heavy
  images, cannot scale one hot tool without scaling all of them.

## Consequences
- More moving parts from phase B (Redis, Postgres, MinIO) and C (gateway, several runtimes).
- Stateful tools must be refactored (phase B) before workers or nodes can increase.
- Custom **Python** plugins are trusted code with container-level access; static/external plugins are
  the safe default. After B7 plugins reach secrets only through the Vault's scoped API.
- Giving the supervisor Docker access is effectively host-root; limited by the socket proxy and only
  acceptable for a single-owner deployment.
- Every phase is measured against the S0.2 baseline; phases C–F are re-confirmed after B9.

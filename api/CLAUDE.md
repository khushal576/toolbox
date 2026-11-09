# DataDiff Pro (`api/` + `core/` + `ui/`) — tool notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Manifest: `api/manifest.yaml` (name `datadiff-pro`). Code map: `api/KNOWLEDGE_MAP.md`. Repo-wide rules: root `CLAUDE.md`.
`core/` is also the shared library every tool imports from (see `docs/architecture/shared-connectors.md`).

## DataDiff as a shared service (roadmap D1/D2)

> Moved **verbatim** from the root `CLAUDE.md` by roadmap session O3 (2026-11-10). The root keeps only the rules and an index;
> nothing was reworded. Paths in the text are repo-root relative.

- **DataDiff as a shared service (roadmap D1):** runtime `datadiff` (own
  188 MB image, `rt-datadiff` with 2 replicas behind the gateway — one can be
  stopped or killed and every request still succeeds). Versioned API
  `/api/v1/compare`, `/api/v1/compare/structured`, `/api/v1/health` (names
  the replica), OpenAPI at `/tools/datadiff-pro/docs`; `/compare` stays as an
  alias. Other code calls it through `core/clients/datadiff.py` — never
  `core.pipeline` directly (unit test). The worker's orchestrator uses it via
  `TOOLBOX_DATADIFF_URL`. **Background compares (roadmap D2):** `POST
  /api/v1/jobs` stores the input in S3 storage and queues `api.jobs.run_job`
  for the `worker`; status in the job's Redis channel, gzipped result in S3
  (`datadiff/<id>/…`, kept 7 days) — any replica answers `GET
  /api/v1/jobs/{id}` and `/result`; `DELETE` cancels (a running diff can't be
  interrupted, its result is discarded). The page uses it automatically for
  > 2 MB of input; client `submit_*`/`wait`; CLI `--background`.

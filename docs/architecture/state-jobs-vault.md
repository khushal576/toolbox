# State services, Vault, Postgres records, background jobs, backups

> Moved **verbatim** from the root `CLAUDE.md` by roadmap session O3 (2026-11-10). The root keeps only the rules and an index;
> nothing was reworded. Paths in the text are repo-root relative.

- **State services (roadmap B1):** compose also runs `redis`, `postgres`
  (Toolbox's OWN records, db/user `toolbox`) and `seaweedfs` (S3-compatible
  files) with named volumes, not published on host ports. Code reaches them
  only through `core/state/` (`db`, `sessions`, `objects`, `health()`) and the
  `TOOLBOX_*` env vars in `core/state/config.py` — to use an existing Postgres,
  set `TOOLBOX_DATABASE_URL` in a `.env` file (dedicated `toolbox` database).
  Check with `GET /api/state/health` or
  `docker compose exec toolbox python -m core.state.selftest`. Defaults are
  local-only passwords; override `TOOLBOX_DB_PASSWORD`,
  `TOOLBOX_S3_ACCESS_KEY`, `TOOLBOX_S3_SECRET_KEY` in `.env`.

- **Backups (Ops session):** `scripts/backup.sh` → one dated archive in
  `backups/` (git-ignored, mode 600): Postgres dump (pg_dump in a one-off
  `docker compose run` of the worker), every S3 object (`core/state/backup.py`
  streams a tar), `.env` (Vault key!), `workspace.yaml`; keeps the last 7.
  `scripts/restore.sh <file>` stops the tool containers, `pg_restore --clean
  --single-transaction`, replaces the bucket, puts `.env`/settings back,
  starts everything. Tested by restoring into a second compose project
  (`COMPOSE_PROJECT_NAME=toolbox-restoretest TOOLBOX_HOST_PORT=8001`). The
  Status page shows the last backup (Redis `toolbox:backup:last`) and nags
  after 7 days. Owner how-to: **`docs/runbook.md`**. Two copies of the stack can
  run side by side: supervisor/autoscaler/balancer filter Docker by THIS
  project and ignore `docker compose run` one-offs (`core_plugins/dockerapi.py`).

- **Vault (roadmap B7):** secrets in Postgres (schema `vault`), dataset
  blobs in S3 storage, key from `TOOLBOX_VAULT_KEY` in the git-ignored
  `.env` (back that file up — without it the Vault can't be decrypted).
  Tool code reaches secrets only via `vault_store.scoped("<tool>")`, limited
  to the kinds its manifest declares under `vault:`; a unit test fails if a
  tool imports `core.vault` unscoped. See `vault/CLAUDE.md`.
- **Tool records in Postgres (roadmap B6):** schema-map, data-syncer,
  schema-copy, data-dumper and ssh-sftp keep their tables in Toolbox's
  Postgres, one schema each (`schema_map`, `data_syncer`, …), through
  `core/state/sqlstore.py` (`SqlStore`: sqlite3-shaped API — `?`
  placeholders, `row["col"]`, one transaction per `with connect()`; SQLite
  when run standalone). On first start each tool copies its old SQLite file in
  once (`<schema>._meta` records it; the file stays as a backup). New tools
  with small relational state use `SqlStore` too. Gotcha: store queries run
  with `prepare=False` — the same SQL text in two tools' schemas must never
  share a prepared plan on a pooled connection.
- **Background jobs (roadmap B4):** the `worker` service (same image,
  `python -m core.jobs.worker`) runs long jobs from the Redis queue via
  `core/jobs/` (`Channel` = heartbeat "alive" key + log tail + stop flag +
  meta, `enqueue`, `StopFlag`). A web restart never kills a job; scale with
  `docker compose up -d --scale worker=N`. `/api/state/health` reports
  `jobs` (workers listening, jobs waiting) — no worker = not ok. Jobs run the
  same tool code, so the worker mounts the same data volumes. New job-running
  tools use `core/jobs/runner.py` (`JobRunner`: queue mode + thread fallback,
  log tail, progress, stop — B5) and keep files in S3 storage with
  `core/state/filecache.py` (`FileCache`: publish / fetch / remove_all, local
  cache trimmed to a budget). The worker clears its own stale Redis
  registration on start (a killed worker used to crash-loop on restart).

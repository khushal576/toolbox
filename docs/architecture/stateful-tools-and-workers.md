# Standing rule: stateful tools and `--workers`

> Moved **verbatim** from the root `CLAUDE.md` by roadmap session O3 (2026-11-10). The root keeps only the rules and an index;
> nothing was reworded. Paths in the text are repo-root relative.

## Standing rule: stateful tools and `--workers`

**Since roadmap B9 the web app runs several worker processes** (`TOOLBOX_WEB_WORKERS`, default 4 in compose;
the image's own default is 1 for a bare `docker run`). That is safe ONLY because every stateful tool keeps its
state outside the process — and it must stay that way:

- **Rule for every tool, existing or new:** no request may depend on something an earlier request left in
  this process's memory. Multi-request state goes to `core/state/` (Redis sessions, Postgres via `SqlStore`,
  S3 via `objects`/`FileCache`), long work goes to the `worker` service (`core/jobs/runner.JobRunner`),
  secrets to the Vault (`vault_store.scoped(...)`). Per-process *caches* are fine if they can be rebuilt from
  the shared state (df-studio's LRU, duck-lab's local DuckDB copies, ssh-sftp's browse connections).
- **Exception: `singleton: true` plugins** (sql-studio, schema-map — one live DB pool, password never stored,
  owner decision in B3) run in the separate `singletons` service (same image, `TOOLBOX_ROLE=singletons`, one
  process, never scaled); every web worker forwards their `/tools/<name>/` traffic there through
  `core_plugins/proxy.py` (`ProxyApp`, streams both ways, 503 page if that process is down). A new tool that truly
  needs one process gets `singleton: true` — it doesn't pin the whole app to one worker.
- **Things that are per process by nature, handled in `main.py`:** the on/off switches (every worker re-reads
  `workspace.yaml` when its mtime changes — at most 1 s behind) and "is this tool loaded" (each process
  publishes its loaded/failed tools to Redis, `toolbox:procs:*`, TTL 60 s; `/api/workspace/status` combines
  them). A load-state from a process that just died can show for up to 60 s.
- Cost: each web worker has its own ~40 MB floor and imports a tool on its own first use (idle container
  32 → ~170 MiB with 4 workers; `docs/roadmap/measure-B9.md`). Lower `TOOLBOX_WEB_WORKERS` in `.env` on a
  small machine.

History (why the pin existed, B2–B8 resolved each case):

The container runs uvicorn with **`--workers 1`**, pinned in `Dockerfile`.
This is because DataFrame Studio keeps its session state (the uploaded
DataFrame, the pipeline of steps) in a plain in-memory Python dict —
`engine.SESSIONS` in `df-studio/engine.py`. With more than one worker,
uvicorn runs separate OS processes that don't share memory, so a session
created by one request can be invisible to the next request if it lands on
a different worker — this happened for real once (see `df-studio/CLAUDE.md`)
and looked like random, unexplained "session not found" errors.
**Resolved for DataFrame Studio in roadmap B2** (sessions in Redis + S3
storage); the instances below still apply until their B-sessions land.

SQL Studio's live database connection (`sql-studio/db_engine.py`,
`STATE`) — **kept single-process by owner decision in roadmap B3**
(`singleton: true`; same for schema-map's pool) — is a second, independent instance of the same constraint — a
single module-level global holding the active Postgres connection pool,
not a per-cookie dict (see `sql-studio/CLAUDE.md` for why it deliberately
does NOT copy df-studio's per-cookie shape). The failure mode here is
worse than a lost DataFrame: with >1 worker, "Connect" landing on one
worker would be invisible to "Run" landing on another, and an orphaned
pool means real, live connections held open against a real external
database (visible in that database's own `pg_stat_activity`, consuming
its connection-limit budget) until something notices and kills it — not
just an inert lost value in memory.

Duck Lab's loaded files + DuckDB connection (**resolved in roadmap B3**:
table list/result in Redis, files in S3 storage, local DuckDB copies rebuilt
per worker — the rest of this paragraph is history) were a **third** instance of this — it deliberately copies
df-studio's per-cookie-dict shape (not SQL Studio's single global), because
each browser tab legitimately wants its own independent set of loaded
files, the same reasoning df-studio uses. See `duck-lab/CLAUDE.md`.

Data Syncer (`data-syncer/runner.py`) was a **fourth** instance — **resolved in
roadmap B4**: syncs are jobs on the Redis queue run by the `worker` container
(`core/jobs/`), live state in Redis. History: each sync
ran on a background thread, and the job registry plus the log ring buffer
lived in that one process's memory. Its durable progress (per-table resume
positions) is in Postgres since B6 and survives anything, but "is a run alive right
now" and the log tail do not — with >1 worker a Start on one process would be
invisible to the status poll on another. See `data-syncer/CLAUDE.md`.

Schema Copy (`schema-copy/runner.py`) was a **fifth** and Data Dumper
(`data-dumper/runner.py`) a **sixth** — both **resolved in roadmap B5**: runs are
jobs in the `worker` container through the shared `core/jobs/runner.py`
(`JobRunner`), and generated scripts / dump files live in S3 storage with the
local folders as per-process caches (`core/state/filecache.py`). Their
catalogues/last-run results are in Postgres since B6. See their `CLAUDE.md`s.

SSH & SFTP (`ssh-sftp/sessions.py`, `runner.py`) was a **seventh** — **resolved in
roadmap B8**: uploads/commands are worker jobs (`core/jobs/runner.py`), staged uploads
live in S3 storage, history in Postgres (B6). Its browsing connection cache stays per
process by design (recreated on demand). See `ssh-sftp/CLAUDE.md`.

**Roadmap:** B2–B8 moved all seven stateful tools' state out of process; **B9 lifted the `--workers 1`
pin** (ticked in `docs/roadmap/ROADMAP.md`). The rule at the top of this section replaces the old "decided
now" paragraph.

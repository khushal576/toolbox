<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Data Syncer — mounted at `/tools/data-syncer/`

Copy or upsert whole tables from one Vault-saved Postgres connection to
another, in resumable key-ranged chunks. Progress (a key position per
table) is saved after every chunk, so a run can be stopped or killed at any
time and resumed; the page shows only status/counts/positions and the last
N log lines, never data. Two modes per project: **upsert** (insert/update,
needs a unique index on the key in the target) and **copy** (raw bulk
`COPY`, target must be empty, no transformation). No manual connection form —
connections are picked from the Vault. See `data-syncer/CLAUDE.md` for the
design (why chunks are key *ranges*, the copy-mode crash-recovery marker,
what is deliberately not built).

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| How a Vault entry becomes a live connection (SSH tunnel, reconnect, keepalives, UTF8) | `data-syncer/connections.py` (`Endpoint`, `resolve`) |
| The COPY / upsert SQL, chunk-boundary query, NULL-key and unique-index checks, table discovery | `data-syncer/sync_ops.py` (`PostgresSyncOps`) |
| Adding another database engine (MSSQL/Oracle) | new class in `data-syncer/sync_ops.py` + register in `_OPS`; the engine is dialect-agnostic |
| The resumable loop: retries/backoff, stop, crash cleanup, FK ordering, per-table failure handling | `data-syncer/engine.py` (`sync_table`, `run_project`, `order_tables`) |
| What "Preflight" checks | `data-syncer/sync_ops.py` (`preflight_table`) + `data-syncer/engine.py` (`preflight_project`) — the engine runs the same checks before every table |
| Where progress/positions/projects are stored, manual position edits, reset | `data-syncer/state_store.py` (Postgres schema `data_syncer` via `core/state/sqlstore.py` since B6) |
| Starting/stopping a run (queued job in the `worker` container), the log tail (last N lines), orphan recovery | `data-syncer/runner.py`, shared `core/jobs/` (Channel, StopFlag, enqueue), `core/jobs/worker.py` |
| Moving auto-increment sequences up to the max id after a sync (raise-only), the "Fix sequences now" button | `data-syncer/sync_ops.py` (`fix_sequences`), `data-syncer/engine.py` (`_fix_sequences`, `fix_sequences_project`), `POST /projects/{id}/fix-sequences` in `data-syncer/server.py`; option `fix_sequences` in `state_store.py` |
| API endpoints, input validation, "can't edit while running" guards | `data-syncer/server.py` |
| The page (project list/editor/run view, polling, log box) | `data-syncer/ui/index.html` |

### Known non-obvious behavior (read before touching these areas)

- **Chunks are key ranges `(lower, upper]`, never `LIMIT n`** — a LIMIT cut can
  split rows sharing a key value across two batches and lose some, and a range
  can be re-run exactly. Keys are stored as text and cast back in SQL.
- **Copy-mode `inflight` marker** — writing a chunk (target DB) and saving the
  position (Postgres) can't be atomic; the recorded in-flight range is deleted
  from the target before a re-copy. Upsert is naturally idempotent.
- **Boundary queries alias their output columns** (`AS _k0`) — without it,
  `ORDER BY "id"` sorts by the `::text` output column. A real bug found by test.
- **Runs are worker jobs since roadmap B4** (Redis queue): live state (heartbeat,
  log tail, stop flag) in Redis, durable state in Postgres (B6). Orphaned `running`
  tables become `interrupted` only when no job is alive (`recover_orphans`/`heal`).
- Postgres → Postgres only for now; no table creation, no delete propagation,
  no change-tracking (a re-run is a full pass).

<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Schema Copy — mounted at `/tools/schema-copy/`

Copies a Postgres database's **structure — everything except the rows** —
into a new, empty database: tables (partitions, inheritance, identity/
generated columns), constraints, indexes, sequences, views, materialized
views (created unpopulated), functions, procedures, triggers, rules, RLS
policies, types, extensions, schemas, comments. Source and target are Vault
connections. The DDL is the real `pg_dump --schema-only` (bundled into the
image), wrapped with preflight, a one-transaction apply (first error rolls
everything back) and a source-vs-target verification report. See
`schema-copy/CLAUDE.md` — especially why a bare `pg_dump` is NOT used (it
copies user-mapping passwords in cleartext).

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| Which `pg_dump` flags are used, how credentials/cancel are passed to the child process | `schema-copy/pgtools.py` |
| Where the `pg_dump`/`psql` binaries come from (and their shared libs) | `Dockerfile` stage `pgclient` (`FROM postgres:${PG_CLIENT_MAJOR}-bookworm`, default 18 — must be ≥ the newest source server you copy from) → `/opt/pgclient`; env override `PGCLIENT_BIN_DIR`/`PGCLIENT_LIB_DIR` |
| What the script contains beyond pg_dump's output (extensions, `IF NOT EXISTS` schemas, sequence values, header) | `schema-copy/engine.py` (`build_script`) |
| What Preflight checks (empty target, same-or-newer server, extensions available, client version, foreign tables) | `schema-copy/engine.py` (`preflight`) + `schema-copy/catalog.py` |
| How a failed apply is reported (failing line + context) | `schema-copy/engine.py` (`_explain_failure`) |
| What "Verify" compares / adding an object category to the report | `schema-copy/catalog.py` (`_NAME_QUERIES`, `compare`) |
| Projects, last-run result, the saved `.sql` script | `schema-copy/state_store.py` (Postgres schema `schema_copy` since B6; scripts in S3 storage via `SCRIPTS` = `core/state/filecache.py`, `scripts/` is a local cache) |
| Run as a job in the `worker` container (thread fallback standalone), log tail | `schema-copy/runner.py` → shared `core/jobs/runner.py` (`JobRunner`) |
| API endpoints, guards | `schema-copy/server.py` |
| The page | `schema-copy/ui/index.html` |
| Vault entry → live connection incl. SSH tunnel (shared with data-syncer) | `core/db_endpoint.py` |

### Known non-obvious behavior (read before touching these areas)

- **Never run an unfiltered `pg_dump` here** — it emits foreign servers, publications
  and USER MAPPINGS WITH PASSWORDS. Every schema is passed with `-n`; that in turn
  drops `CREATE EXTENSION`, which `build_script` re-adds from the catalog.
- **The toolbox image is Debian 12, the stock `postgres:N` image is Debian 13** —
  the `pgclient` Docker stage deliberately uses `postgres:N-bookworm`.
- Postgres → Postgres only; target must be empty; roles/owners/grants stripped by
  default; matviews created empty; sequences fresh unless opted in.
- **Runs are worker jobs since roadmap B5** (`core/jobs/runner.py`); the last run's result is in Postgres (B6).

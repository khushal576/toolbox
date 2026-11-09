# Shared connectors and headless recipes (do not write a 4th copy)

> Moved **verbatim** from the root `CLAUDE.md` by roadmap session O3 (2026-11-10). The root keeps only the rules and an index;
> nothing was reworded. Paths in the text are repo-root relative.

## Headless recipes vs. a new tool

Not everything that calls into a tool's engine needs a web UI. `orchestrator/`
(see `orchestrator/CLAUDE.md`) is a plain Python package + CLI — no
`server.py`, no `ui/`, no `manifest.yaml`, no `main.py` mount — for
composing existing engines (DataDiff through its client since D1,
duck-lab-style DuckDB reads, a one-shot Postgres connector), invoked as
`docker compose exec worker python -m orchestrator.cli ...` (since C2). Use it when the real need is "call
this logic without a browser" (e.g. diffing data that lives in a database,
not pasted text) — not a workflow engine, not a plugin system, just direct
function calls between modules that already run in the same process. If a
headless need later grows an actual UI requirement, that's when it becomes
a new tool under the checklist below, not before.

## Shared connectors — one multi-database connector, one file loader, one vault

**Multi-database support (Postgres/SQL Server/Oracle)** lives behind
`core/db/dialect.py`'s `Dialect` protocol — one concrete class per
database (`core/db/dialect_postgres.py`, `dialect_mssql.py`,
`dialect_oracle.py`) implementing conninfo-building, pool open/checkout/
close, the row-cap SQL template, and introspection (`schema_fetch_query()`
plus 11 SQL-text-returning methods — `list_tables_sql()`,
`list_functions_sql()`, `list_foreign_keys_sql()`, etc. — symmetric
across all three databases, not just Postgres). `core/db/registry.py`'s
`get_dialect(db_type)` is the one lookup point from a `"postgres"`/
`"mssql"`/`"oracle"` string to a `Dialect` instance. `core/pooled_db.py`'s
`PooledDbConnection` is the generalized pool+reaper lifecycle built on
top — dialect-agnostic, parametrized by whichever `Dialect` a given
`connect()` call passes in. **This is the precedent any future tool
needing more than one database type should extend** — SQL Studio
(`sql-studio/db_engine.py`/`query_guard.py`) is the first and so far
only consumer that lets the dialect vary per connection; don't hand-roll
a fourth connector or a second dialect-dispatch mechanism.

`core/postgres_conn.py` (conninfo/verify primitives) and
`core/pooled_postgres.py` (now a thin subclass of `PooledDbConnection`
with `PostgresDialect` fixed as its default — see that file's own
docstring) still exist exactly as before, backward-compatible: schema-map
and the orchestrator's one-shot connector only ever talk to Postgres, so
they keep using these directly, unaware anything underneath changed.
File-extension-to-DuckDB-function mapping lives in `core/file_source.py`,
shared by duck-lab and the orchestrator's file connector. A bounded,
streaming, async outbound HTTP executor (timeout + response-size cap,
never buffers an unbounded response) lives in `core/http_exec.py`,
built for cURL Builder's "Run" feature but kept generic/reusable there
rather than tool-local, same reasoning as everything else in this
section. **Don't add a fourth independent implementation of any of
these** — if a new tool needs to connect to a database, read a
CSV/JSON/Parquet file, or make an outbound HTTP request, it calls into
these, the same way duck-lab/sql-studio/schema-map/orchestrator/
curl-builder already do.

Data Syncer (`data-syncer/`) is a **consumer of these, not a new
connector**: it resolves Vault entries via `core.vault`, opens (optionally
SSH-tunnelled) connections with `core.postgres_conn`'s primitives, and puts
its own write-side database operations (COPY/upsert, key-range chunking —
things `Dialect` has no notion of) behind a small per-database class in
`data-syncer/sync_ops.py`. A new database engine means a new class there.

`core/db_endpoint.py` is the shared **Vault entry → live connection**
helper (SSH tunnel aware, reconnectable, exposes the tunnel-aware host/port
for subprocess clients like `pg_dump`) used by Data Syncer and Schema Copy —
it was extracted from `data-syncer/connections.py` (now a thin re-export)
when the second consumer appeared, per this section's "don't add another
independent implementation" rule.

`core/pgclient.py` runs the **bundled `pg_dump`/`pg_restore`/`psql`** (Dockerfile stage `pgclient`)
as subprocesses — cancel-aware, streaming stderr, credentials via `PGPASSWORD` only — and
`core/pg_inspect.py` holds the small shared catalog helpers (server version, empty-target check,
available extensions). Both were extracted from Schema Copy when Data Dumper became the second
consumer (`schema-copy/pgtools.py` is a thin re-export), per this section's rule.

`core/ssh_client.py` opens **host-key-pinned SSH/SFTP connections from a Vault `ssh_server` entry** (no agent,
no ~/.ssh, timeouts + keepalives, plain scrubbed errors) for the SSH & SFTP tool and the Vault's "Add SSH
server" form. The DB tools' SSH *tunnels* (`core/postgres_conn.py`) are a different, older path and are
deliberately untouched.

`core/vault.py` is the shared, generic encrypted secret store (Fernet,
no master password by deliberate owner choice — see `vault/CLAUDE.md`
for the full trust-model writeup) behind the "Vault" tool's management
page. sql-studio and schema-map's Connection panels both have "Save this
connection"/"Load saved connection" controls calling `/tools/vault/...`
directly (same-origin, no proxy — see `schema-map/CLAUDE.md` Phase D for
the precedent), and the orchestrator's `--left-vault <name>` loads one
without an HTTP round-trip. Any future tool that wants to remember a
credential (or any other secret) should save it here under its own
`kind` tag, not invent a second store.

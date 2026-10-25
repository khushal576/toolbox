# Schema Copy — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the symptom→file map across every tool. This is
the fast-orientation version scoped to this folder.

## What this tool is

Copy a Postgres database's **structure — everything except the rows** — into a
new, empty database: tables (partitioned tables + partitions, inheritance,
identity/generated columns, defaults), all constraints and indexes, sequences,
views, **materialized views (created unpopulated)**, functions, procedures,
aggregates, triggers, rules, RLS policies, types/domains, extensions, schemas,
comments. The natural next step is the Data Syncer (copy the rows).

Source and target are **Vault connections** (never typed). A project stores
the Vault ids, an optional schema subset, and two options: keep owners/GRANTs
(default off) and copy sequence current values (default off). Actions:
**Preflight** (checks only), **Preview DDL** (generate the script, apply
nothing), **Apply** (generate + apply + verify), **Verify** (diff source vs
target any time).

## How it works — and why `pg_dump`

The DDL comes from the real `pg_dump --schema-only`. Re-implementing
dependency ordering across ~15 object kinds from the catalogs would silently
miss something; `pg_dump` is what DBAs trust. `engine.py` wraps it because a
bare dump is wrong for this job in four *measured* ways:

1. **A bare dump copies USER MAPPINGS WITH THEIR PASSWORDS IN CLEARTEXT** (plus
   foreign servers and publications). So every schema is named explicitly with
   `-n` — never an unfiltered dump. A downloadable script must never hold credentials.
2. `-n` drops `CREATE EXTENSION` (extensions aren't schema members), so the
   extensions are re-emitted from `pg_extension` at the top of the script
   (a `gin_trgm_ops` index needs `pg_trgm` first).
3. Foreign tables still get dumped under `-n` but their servers don't exist on
   the target — they're excluded with `-T` and listed as warnings.
4. `CREATE SCHEMA x;` is rewritten to `CREATE SCHEMA IF NOT EXISTS x;` — a fresh
   database already has `public`, and extension schemas are pre-created.

The script is applied with `psql -v ON_ERROR_STOP=1 --single-transaction`: the
first error rolls EVERYTHING back (target untouched) and the UI shows the
failing line with the script lines around it. Stop kills `psql`, which also
rolls back.

## Where things live

| Concern | File |
|---|---|
| Spawning `pg_dump`/`psql` (bundled binaries, env, cancel, argv) | `pgtools.py` (thin re-export of `../core/pgclient.py`, shared with data-dumper) |
| Read-only catalog queries: schemas, extensions, foreign tables, target-emptiness, the per-category object-name sets used for verification | `catalog.py` |
| Preflight, script building, applying, verification, one run end to end | `engine.py` |
| Projects + last-run result (Postgres schema `schema_copy`, B6; SQLite standalone) and the script files (S3 storage, local cache) | `state_store.py` |
| Run as a job in the `worker` container + log tail (shared `../core/jobs/runner.py`) | `runner.py` |
| API + page | `server.py`, `ui/index.html` |
| Vault entry → connection (SSH tunnel aware; shared with data-syncer) | `../core/db_endpoint.py` |

## Things that will bite you if you don't know them

- **The binaries are bundled, not apt-installed.** `../Dockerfile` has a
  `pgclient` stage built `FROM postgres:${PG_CLIENT_MAJOR}-bookworm` (default
  **18**; the stock `postgres:N` is Debian 13 while the toolbox image is Debian 12,
  so its binaries don't run here) that copies `pg_dump` + `psql` and the shared
  libs they need into `/opt/pgclient`. `LD_LIBRARY_PATH` is set for the child
  processes only. **A pg_dump only dumps servers up to its own major version**, so
  keep `PG_CLIENT_MAJOR` ≥ the newest source you copy from (an 18 source with the
  original 17 bundle failed preflight — that is how this was found); newer
  clients dump all older servers. Preflight reports a too-old client.
- **Credentials reach the tools via `PGPASSWORD` in the child's environment**,
  never on the command line, and nothing logs the environment. SSH tunnels work
  because `Endpoint.open()` exposes `.host/.port` (the local tunnel end).
- **The target must be empty** (an empty `public` is fine). Preflight lists what's
  already there and refuses. The tool never creates a database, tables, or roles.
- **Roles are never copied** (server-level objects). Owners/GRANTs are stripped
  by default so the script runs on a server without the same roles.
- **Extensions must be installed on the target server** (preflight checks
  `pg_available_extensions`); the default version for the target is created.
- **Verification diffs name SETS, not counts** (`catalog.object_names`) — a
  missing index and an extra one would cancel out in a count. Extension-owned
  objects are excluded on both sides.
- **Materialized views are created `WITH NO DATA`** (pg_dump's schema-only
  behaviour) — they are empty until you `REFRESH` them after loading data.
- **Sequences start fresh** unless "copy sequence values" is on (then
  `setval(..., last_value, true)` lines are appended). That is the only
  "data-ish" thing the tool ever reads, and it is opt-in.
- **A schema subset can fail the apply** if chosen schemas depend on unchosen
  ones; preflight warns, the one-transaction apply keeps it safe.
- **Runs are jobs in the `worker` container since roadmap B5** (`runner.run_action` via the shared
  `core/jobs/runner.JobRunner`; a background thread when standalone without Redis). Log tail + "running" live in
  Redis, so any web process sees them and a web restart doesn't kill an apply. A worker that dies mid-run just
  shows as not running ~30 s later (the last run result stays the previous one; psql's transaction rolls back).
- **The script's home is S3 storage** (`state_store.SCRIPTS`, `core/state/filecache.py`): built as
  `<id>.sql.part`, renamed, then uploaded; `scripts/` is only a cache, re-downloaded by apply/preview/download
  when missing. A failed/stopped build no longer overwrites the previous script.

- **Stop an apply**: `psql` is terminated, so the single transaction is never
  committed and nothing is left behind (verified) — but the server only
  notices the dropped client when its current statement finishes, so a very
  slow statement can keep a backend alive briefly before the rollback.
- **The script starts with `\restrict <key>` / ends with `\unrestrict`**
  (psql meta-commands added to pg_dump in the 2025 security releases). The
  bundled `psql` (17.11) handles them; a downloaded script run with an OLD
  `psql` may reject them — delete those two lines or use a current psql.
- **The extension block comes before pg_dump's own output** and installs each
  extension at the target's default version; the report compares extension
  names, not versions.

## Verified (real Postgres 17 source, throwaway containers; bundled pg_dump/psql 17.11 inside the toolbox image — the bundle has since been bumped to 18, re-verify against a v18 source)

A source with: 3 extensions (pg_trgm, btree_gist, postgres_fdw), range/list/
default partitions, inheritance, identity + generated columns, enum/domain/
composite types, GIN-trigram/partial/expression/covering indexes, exclusion +
check + FK constraints, RLS policy, rule, trigger, function/procedure/aggregate,
view, materialized view, comments, a role with GRANTs and an owner, a foreign
table + server + user mapping with a password, and a publication. Result: all
20 verification categories match; zero rows copied; the matview is created
unpopulated; the user-mapping password / server / publication / foreign table
are NOT in the script. Also verified: non-empty target refused before anything
is generated; a failing apply (schema subset) reports the failing statement and
leaves ZERO objects behind (incl. extensions); keep-owner and sequence values
(`setval` to 4242); Verify catches a dropped index and a stray view; same-DB
source/target refused; Stop mid-apply rolls back; the whole UI driven in
headless Chrome (create → load schemas → preview → view script → apply →
report). Not tested: SSH-tunnelled connections; a source newer than the bundled
client (it is caught by preflight); the missing-extension-on-target preflight error.

## Not built (decided, not forgotten)

Postgres → Postgres only; no CREATE DATABASE; no two-phase split (tables first,
indexes/constraints after the data load — would make the Data Syncer's bulk load
faster; `pg_dump --section=pre-data/post-data` supports it); no foreign
servers/user mappings (credentials); no roles; no event triggers, publications
or subscriptions; no incremental "sync only what changed" of structure (diff +
ALTER) — this is a one-shot copy into an empty database.

# Data Dumper — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and
`../KNOWLEDGE_MAP.md` for the symptom→file map across every tool. This is the fast-orientation
version scoped to this folder.

## What this tool is

Take a Postgres dump you can **download**, and **restore** a dump into any database — whole, or
only what you choose. Sources/targets are Vault connections (never typed). A dump is a FILE on the
`data_dumper_data` volume (kept until deleted) plus a catalogue row; a dump can also be **uploaded**
(`.dump`, `.sql`, `.sql.gz`). Each dump remembers how it was taken (source, format, scope, owner
option) — groundwork for the planned scheduler: a cron job is just "dump again" (`POST /dumps/{id}/again`).

Formats: **custom** (`pg_dump -Fc`, the default — compressed, restorable selectively) and **plain**
(`-Fp -Z gzip:6` → `.sql.gz`, restored whole through `psql`).

Restore choices (custom dumps; plain = whole only):
- presets: everything · structure only · data only · **phase 1 before data / 2 data / 3 after data**
  (load data before indexes and FKs — much faster) → plain `pg_restore` flags;
- **schemas / tables / objects**: a `pg_restore -L` LIST FILE built from the dump's table of contents
  (`toc.py`), with options structure / data / shared objects / foreign keys;
- options: one transaction (default on), keep owners/GRANTs (default off), **replace existing**.

## Where things live

| Concern | File |
|---|---|
| Running `pg_dump`/`pg_restore`/`psql` (bundled, cancel, live stderr, atomic replace pipe) | `../core/pgclient.py` (shared with schema-copy) |
| Vault entry → connection (SSH tunnel aware) | `../core/db_endpoint.py` |
| Server version / empty-target check / extension availability | `../core/pg_inspect.py` |
| Understanding a dump's contents + building a selection | `toc.py` (pure functions, no DB) |
| Dump, upload validation, contents cache, restore plan/preflight/run | `engine.py` |
| Catalogue + run history (SQLite) and the files | `state_store.py` |
| Background thread + log tail + progress | `runner.py` |
| API + page | `server.py`, `ui/index.html` |

## Things that will bite you if you don't know them

- **`pg_restore -n/-t` are NOT used for selection** (measured): `-t` restores only the bare table +
  data + comment — no indexes, constraints, triggers, policies or sequences; `-n` skips the CREATE
  SCHEMA. So `toc.Toc.select()` builds a `-L` list. The TOC names an INDEX by index name only, so which
  table owns it (and which sequence/partition/foreign key belongs to which table) is read from the SQL
  `pg_restore -f -` emits for `--section=pre-data` and `--section=post-data` (`toc.parse_relations`).
  Never run `-f -` over the data section — it would stream every row into memory.
- **Foreign keys are included only when both tables are restored; partitions follow their parent;
  a partition's `TABLE ATTACH` only if the parent is chosen; shared objects (extensions, schema,
  types/domains/functions of the involved schemas) are on by default.** `pg_restore` never adds
  dependencies itself: a table whose type/function is missing fails — and rolls back.
- **Everything runs in ONE transaction** (`pg_restore --single-transaction`, implies exit-on-error):
  a failed or STOPPED restore leaves the target untouched. A whole-database restore (`all`,
  `schema_only`, `pre_data`) needs an EMPTY target — preflight refuses otherwise.
- **"Replace existing" does NOT use `pg_restore --clean`** — that fails on partitioned tables ("cannot
  drop inherited constraint"). Instead the restore script (`pg_restore -f -`, data inline) is piped
  into `psql --single-transaction` with our own DROPs written first (`pgclient.pg_restore_replace`): whole
  schemas (`DROP SCHEMA … CASCADE`, so objects NOT in the dump go too) for `all/schema_only/pre_data/schemas`,
  per-object `DROP … IF EXISTS … CASCADE` for `tables/objects`. Atomic: if the restore part fails, the
  drops roll back (verified). Not available for plain dumps or data-only/post-data restores.
- **Dumps are written to `<id>.<ext>.part` and renamed only when `pg_dump` exits 0**; a stopped/failed dump
  leaves no file. A restart marks dumps still 'running' as failed (`recover_interrupted`).
- **pg_dump only dumps servers up to its own major version** (bundled client: `PG_CLIENT_MAJOR` in the
  Dockerfile, default 18). An uploaded dump from a NEWER pg_dump cannot be read — the error says so.
- **Owners/GRANTs are stripped by default** (`--no-owner --no-privileges`) so a dump restores on any
  server; roles themselves are never in a pg_dump.
- **Dumps are plain files on a volume, unencrypted, downloadable by anyone who can open the toolbox** —
  the same trust model as the Vault (single trusted user). No retention/cleanup yet (manual delete).
- **Dropped connections ("SSL error: unexpected eof")**: a dump/restore holds ONE connection for minutes and
  NATs, proxies, load balancers and tunnels silently drop idle-looking ones. `core/pgclient.py` therefore
  passes a conninfo to `-d` with TCP keepalives (idle 30s) and a connect timeout (verified: the socket
  shows a ~30s keepalive countdown instead of libpq's ~2h default), and `engine.run_dump` RETRIES a dump up
  to 3 times when the failure matches `pgclient.TRANSIENT_RE` (a dump has no state to resume, so a retry is
  always safe; non-connection errors are never retried). Failure messages end with `[last step: …]` — the
  last thing `pg_dump -v` reported — which tells a catalog-phase failure from one while copying rows.
  A restore is NOT auto-retried (it rolls back, so re-running is the user's call). If it still fails after
  3 attempts the cause is outside the tool: a proxy/tunnel with a hard timeout, the server killing the
  backend (check the server log; a read replica cancels long queries on recovery conflicts), or a very
  slow/lossy link (pg_dump runs thousands of catalog queries before the first row).
- **In-process job registry → `--workers 1`**, a sixth stateful tool in `../CLAUDE.md`'s standing rule.

## Not built (decided, not forgotten)

The scheduler (cron) and shipping dumps elsewhere (S3/SFTP) — the catalogue already records how a dump
was taken so both can be added on top; retention/auto-cleanup; encryption at rest; parallel restore
(`-j`, incompatible with one-transaction); `pg_dumpall --globals-only` (roles); per-table dump selection
at DUMP time (you choose at RESTORE time instead); other engines.

## Verified (real PostgreSQL 18 server, bundled client 18.6)

A source with extensions, partitions (range + default), identity/serial sequences, enum/domain types,
GIN/expression indexes, FK/check constraints, RLS policy, trigger, function/procedure, view and
materialized view, plus a 2M-row table. Custom and plain dumps restore IDENTICALLY (rows, checksums, every
index/constraint/trigger/policy/view/sequence count); the three phases rebuild the database exactly;
non-empty target refused; replace-existing on a populated target with partitions (identical afterwards)
and per table; replace is atomic (restore failing after the drop rolled the drop back); selective restores
of one table (data + 4 indexes + trigger + identity sequence that continues at 501), a partitioned table
with its FK table, structure-only then data-only, schemas, a single dropped index by object; a schema
whose matview needs an unselected table fails with the reason and leaves nothing behind; stopping a dump
leaves no file and stopping a restore rolls back to empty; upload validation (valid dump accepted, binary
junk rejected, .sql and .sql.gz accepted); a failing plain restore reports its line and rolls back;
an unreachable source fails cleanly; a connection killed mid-dump is retried automatically (and killed on every attempt fails with the cause + last step, no partial file); 2M-row dump ≈10 s, restore ≈7 s; the whole UI in headless Chrome
(dump → download → selective restore → preflight refusal). Not tested: SSH-tunnelled connections,
a source/dump newer than the bundled client, restoring onto an older server than the dump.

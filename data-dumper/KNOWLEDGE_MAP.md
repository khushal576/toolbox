<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Data Dumper — mounted at `/tools/data-dumper/`

Take a Postgres dump you can **download** and **restore** a dump into any database — whole, or only
what you pick: structure, data, a phase (before data / data / after data), chosen schemas, chosen
tables, or single objects. Sources/targets are Vault connections; dumps are files on the
`data_dumper_data` volume (also uploadable). Restores run in one transaction (a failure/stop rolls
back); a whole-database restore needs an empty target unless "replace existing" is chosen. See
`data-dumper/CLAUDE.md` — especially why selection is a `pg_restore -L` list built from the dump's
contents and why "replace existing" is not `pg_restore --clean`.

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| How `pg_dump`/`pg_restore`/`psql` are invoked (flags, env, cancel, live progress lines, the atomic replace pipe) | `core/pgclient.py` |
| Which restore choices exist and what they map to (presets → flags, schemas/tables/objects → list file) | `data-dumper/engine.py` (`_plan`, `PRESETS`), `data-dumper/toc.py` (`Toc.select`) |
| Parsing a dump's contents; which index/sequence/partition/FK belongs to which table | `data-dumper/toc.py` (`parse_toc`, `parse_relations`, `Toc.owner_table`) |
| The DROP statements behind "replace existing" | `data-dumper/toc.py` (`schema_wipe_sql`, `object_drop_sql`) + `core/pgclient.py` (`pg_restore_replace`) |
| Preflight (empty target, extensions, versions, "needs structure") | `data-dumper/engine.py` (`preflight_restore`) |
| Taking a dump (progress, disk checks, `.part` → final rename) | `data-dumper/engine.py` (`run_dump`) |
| Validating an uploaded dump file | `data-dumper/engine.py` (`finalize_upload`) |
| The dump catalogue, run history, file locations | `data-dumper/state_store.py` (Postgres schema `data_dumper` since B6; dump files + TOC caches in S3 storage via `FILES` = `core/state/filecache.py`, `files/` is a local cache trimmed to `DATA_DUMPER_CACHE_MB`) |
| Run as a job in the `worker` container (thread fallback), log tail, progress (mirrored to Redis), orphan recovery (`recover_orphans`/`heal` → `state_store.fail_orphans`) | `data-dumper/runner.py` → shared `core/jobs/runner.py` (`JobRunner`) |
| API endpoints (incl. download, contents, upload) | `data-dumper/server.py` |
| The page | `data-dumper/ui/index.html` |
| The bundled client version / what is bundled | `Dockerfile` stage `pgclient` (`PG_CLIENT_MAJOR`, pg_dump + pg_restore + psql) |

### Known non-obvious behavior (read before touching these areas)

- **`pg_restore -t/-n` are not used for selection** — `-t` gives a bare table (no indexes/constraints/
  sequences), `-n` skips CREATE SCHEMA. The list file is built from the TOC instead.
- **"Replace existing" = our DROPs + `pg_restore -f -` piped into one `psql --single-transaction`**, because
  `pg_restore --clean` breaks on partitioned tables and can't be made atomic with extra drops.
- Dumps are unencrypted files on a volume; anyone who can open the toolbox can download them.
- **Stateful, `--workers 1`**: sixth entry for `../CLAUDE.md`'s standing rule (job registry/log tail in memory).

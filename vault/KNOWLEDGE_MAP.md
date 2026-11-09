<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Vault — mounted at `/tools/vault/`

A management page for `core/vault.py`'s shared, encrypted secret store —
list/delete/clear, an "Add connection" form (test-before-save, for the
one shape — a DB connection — this page itself understands), and a
Backup & restore card. Creating any OTHER secret shape is still always
done from the tool that uses it (e.g. sql-studio's "Save this
connection"). Started to fix one pain: sql-studio/schema-map's idle
reaper drops the live DB connection after 20 minutes, and retyping
credentials every time was real friction. **Grew a second, bigger
purpose**: a generic hand-off point for feeding one tool's output into
another as input (e.g. a transformed Postgres query result → DataDiff
Pro), with memory use bounded regardless of dataset size — see
`vault/CLAUDE.md`'s "datasets" section. See that file for the full
picture, especially its security posture (no master password, by
deliberate owner choice) and the "Backup & restore" section (what
actually survives a container rebuild vs. not, and why SQLite stays the
right engine here rather than switching to a client-server database).

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| The actual encryption/storage (Postgres schema `vault` + S3 blobs since B7; Fernet key from `TOOLBOX_VAULT_KEY`) | `core/vault.py` (`_load_or_create_key`, `_ready_store`, `STORE`, `BLOBS`) |
| Which plugin may read/write which secret kind (scopes), the HTTP scoped API + tokens | manifest `vault:` → `core/vault.py` (`scoped`, `ScopedVault`, `Scope`, `plugin_token`); `vault/server.py` `/api/v1/*` |
| Credential save/load (small, whole-value encryption) | `core/vault.py` (`save_secret`, `get_secret`, `get_secret_by_name`) |
| Dataset save/load (chunked encryption, bounded memory regardless of size) | `core/vault.py` (`save_dataset`, `load_dataset_file`, `load_dataset_file_by_name`, `CHUNK_SIZE`) |
| API endpoints (`GET /secrets`, `POST /secrets`, `GET /secrets/{id}/reveal`, `DELETE /secrets/{id}`, `POST /clear`, `POST /test-connection`, `GET /backup`, `POST /restore`) | `vault/server.py` |
| The management page itself (list/delete/clear/add-connection/backup) | `vault/ui/index.html` |
| Downloading/restoring a full backup of the vault (rows + key + every blob) | `core/vault.py` `export_backup()`/`import_backup()` (format 2, reads format 1, re-encrypts other-key backups); thin wrappers in `vault/server.py` |
| Producing a dataset to save (Postgres → Vault, DuckDB result → Vault) | `sql-studio/server.py`'s `/export/vault` (streaming cursor), `duck-lab/server.py`'s `/export/vault` (DuckDB `COPY TO`) |
| Consuming a saved dataset headlessly, any size | `orchestrator/recipes/compare.py`'s `"vault_dataset"` source kind |
| Consuming a saved dataset in a browser, size-capped (DataDiff Pro only) | `vault/server.py`'s `GET /datasets/{id}/preview`, `core.vault.preview_dataset_as_csv()`, wired up in `ui/index.html`'s "Load from Vault" buttons — the ONE path that enforces a row cap, since DataDiff Pro's textarea is paste-based |
| Consuming a saved dataset in a browser as a brand-new table/session, uncapped (Duck Lab, DataFrame Studio) | `duck-lab/server.py`'s `/load/vault` (via `core.vault.load_dataset_file()`, loads into a new DuckDB table), `df-studio/server.py`'s `/load/vault` (same function, loads into a new pandas session) — uncapped because each tool already owns its own size story for an ordinary upload (DuckDB disk-backed views, pandas full-materialization) and this just sources the same path from a vault blob instead of an HTTP upload, not a second size policy to keep in sync |

### Known non-obvious behavior (read before touching these areas)

- **`list_secrets()` must never return decrypted data** — that's the one
  invariant that keeps this page safe to leave open. `get_secret()`/
  `get_secret_by_name()` (credentials) and `load_dataset_file()`/
  `load_dataset_file_by_name()` (datasets) are the only functions that
  decrypt anything, and are called only at the moment a tool is actually
  about to use the secret/dataset — sql-studio/schema-map's "Load saved
  connection," the orchestrator's `--left-vault`/`--right-vault`
  (connections) or `--left-vault-dataset`/`--right-vault-dataset` (data
  — a deliberately different flag, see `orchestrator/CLAUDE.md`).
- **A dataset entry's bulk data is NEVER in `ciphertext`** — that column
  holds only small metadata (`format`/`columns`/`row_count`) for a
  dataset row; the real data is chunk-encrypted separately into a file
  under `blobs/`, named by the row's `blob_path`. This split is what
  keeps `save_dataset()`/`load_dataset_file()`'s memory use bounded by
  `CHUNK_SIZE` (4 MiB) instead of by dataset size — verified directly:
  saving/loading a 61 MB generated file showed essentially the same
  process RSS as an 8 MB one.
- **`has_data` in `list_secrets()`'s output is just `blob_path IS NOT
  NULL`** — `false` for an ordinary credential, `true` for a dataset.
  Doesn't decrypt anything to compute this.
- **No vault master password, by deliberate owner choice** — the
  encryption key lives in a `0600` file on the same volume as the
  encrypted data. Protects against casually reading the DB file or a
  stray backup; does NOT protect against anyone with access to the
  running container. See `vault/CLAUDE.md` for the full writeup and what
  would need to change if the threat model ever does.
- **`core/vault.py` has no opinion on what a given `kind`'s data shape
  is** — sql-studio/schema-map both save `{host, port, database,
  username, password, ssh_tunnel}` under `kind: "postgres_connection"`
  by convention, not because this module enforces it. A new consuming
  tool is free to use its own `kind` and shape.
- **This is a THIRD stateful... actually, it's NOT** — unlike df-studio/
  sql-studio/schema-map/duck-lab, Vault has no in-memory per-worker
  state at all (every call reads/writes SQLite through
  `asyncio.to_thread`, same as `schema-map/project_store.py`) — it
  doesn't add a new entry to `../CLAUDE.md`'s "Standing rule: stateful
  tools and `--workers`" list, even though it's backend-touching.

| The prod / non-prod label of a connection or SSH server (set, list, badge) | `core/vault.py` `environment_of` / `environments` / `set_environment`; `server.py` `/environments`, `/secrets/{id}/environment`; `ui/index.html` `envControl` |

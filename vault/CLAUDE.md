# Vault — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A management page for `core/vault.py`'s shared, encrypted secret store —
list what's saved, delete one, or clear everything. Built to fix a real
pain: sql-studio/schema-map's idle reaper drops the live DB connection
after 20 minutes, and retyping host/port/database/username/password
every time is real friction. The store is deliberately generic, not
DB-specific — "may have many app which support so can use among all
tool also not for db many thing we may need also" (the owner's own
framing) — any tool can save any named secret under a free-form `kind`
tag.

## Second pass — datasets, not just credentials

**The real motivating case for this whole tool**: "run a transforming
query against Postgres, save the result to the vault, then feed it into
DataDiff Pro" — without ever holding the whole dataset in memory at
once ("data can be any amount in ram can break things," the owner's own
framing). Credentials (the original shape) are small and get
whole-value Fernet encryption; a **dataset** is a second shape sharing
the same `secrets` table (one new nullable column, `blob_path`):
`ciphertext` holds only small metadata (`format`/`columns`/`row_count`),
and the actual bulk data is encrypted separately, in fixed-size
(`core.vault.CHUNK_SIZE`, 4 MiB) chunks, into a file under
`core/vault.py`'s `BLOBS_DIR`. `save_dataset()`/`load_dataset_file()`
never hold more than one chunk in memory — **verified directly**: saving
and loading a 61 MB generated CSV showed essentially the same process
RSS as an 8 MB one (≈72 MB vs. ≈68 MB, dominated by fixed import/library
overhead, not file size) — memory genuinely does not scale with dataset
size.

**Producers** (getting a real result onto disk without full
materialization, each tool's own job — this module just takes a path):
duck-lab's `POST /tools/duck-lab/export/vault` (`COPY _result TO
...PARQUET` — DuckDB's own streaming write) and sql-studio's `POST
/tools/sql-studio/export/vault` (a server-side/named psycopg cursor,
`fetchmany()` in batches — see `sql-studio/CLAUDE.md`, this is the one
place that deliberately bypasses the 500-row display cap). **Consumer**:
the orchestrator's `vault_dataset` source kind
(`orchestrator/recipes/compare.py`) — `load_dataset_file_by_name()` to a
temp file, read with the same DuckDB technique the plain `file` source
already uses, delete the temp file, feed the rows into
`core.pipeline.run_compare()` unchanged.

**A second, bounded consumer**: DataDiff Pro's "Load from Vault" buttons
(one per side, next to the format `<select>`). This UI is paste-based, so
pulling an unbounded dataset into it would reintroduce the exact RAM
problem this feature exists to avoid — `GET /tools/vault/datasets/{id}/preview`
(`core.vault.preview_dataset_as_csv()`) checks the real row count
BEFORE reading any row data, and refuses (400) anything over
`max_rows` (default 2000) instead of truncating silently. Only when a
dataset is small enough does it actually get read and returned as CSV
text to paste into the textarea. Anything bigger still goes through the
orchestrator, headless, no browser involved — see
`orchestrator/CLAUDE.md`. These are deliberately two different code
paths for two different size regimes, not one path with a cap bolted
onto it: the orchestrator's `vault_dataset` source never checks a row
count at all (it was never going into a browser), while this preview
endpoint's whole reason to exist IS the row-count gate.

**A third, uncapped consumer**: Duck Lab's and DataFrame Studio's own
"load from Vault" pickers (`POST /tools/duck-lab/load/vault` and `POST
/tools/df-studio/load/vault`) — unlike DataDiff Pro's preview endpoint,
these load a saved dataset as a brand-new table/session the same way
each tool already handles an ordinary file upload, with no row-count
gate at all. That's not an oversight — each tool already owns its own
size story for an upload (Duck Lab never reads the file into Python,
DuckDB scans it off disk; DataFrame Studio already fully materializes
every upload into pandas, documented as its own accepted tradeoff), so
sourcing the same bytes from a decrypted vault blob instead of an HTTP
body doesn't introduce a new size problem to solve here — it just calls
`core.vault.load_dataset_file()` directly, the same unbounded function
the orchestrator's `vault_dataset` source already uses. DataDiff Pro
needed the row-count gate specifically because ITS target is a
paste-based textarea — these two don't have that constraint.

`list_secrets()` now reports `has_data: bool` per entry (whether
`blob_path` is set) so the Vault page and any consuming tool can tell a
credential from a dataset without decrypting anything — the one addition
to the existing "metadata only, never decrypted data" invariant below.
`delete_secret()` removes the blob file too if present; `clear_all()`
wipes the whole `blobs/` directory, not just the SQLite rows.

## Add connection (with test-before-save)

The Vault page has an "Add connection" form (DB type, host/port/database/
username/password, optional SSH tunnel with password or private key +
passphrase), so a connection can be saved without opening SQL Studio
first. This reverses the page's original "no add form" rule at the
owner's request — it saves only the one shape the tools already use
(`kind: "postgres_connection"`, data `{host, port, database, username,
password, db_type, ssh_tunnel}`), so the Connection panels' "Saved
connections" pickers list it as-is. "Test & save" first calls
`POST /test-connection` (one-off, unpooled connect through the tunnel if
configured, via the same `dialect.verify_connection` Connect uses; nothing
stored), and refuses to save on failure; "Test only" and a deliberate
"Save anyway (untested)" are also there. Password/key fields are cleared
after a save. Verified in headless Chrome against a real Postgres and a
real SSH bastion: empty form, bad password, good plain, SSH wrong/right
passphrase, save-anyway, and loading the saved entries into SQL Studio and
connecting (plain and via tunnel). SQL Server/Oracle test path untested.

## SSH servers (second saved shape: kind `ssh_server`)

The page also has an "Add SSH server" form for the SSH & SFTP tool (`../ssh-sftp/CLAUDE.md`): host, port,
username, a private key (+ passphrase) or a password, and a read-only switch. It is a TWO-STEP test
(`POST /test-ssh-server`): first it fetches the server's host key WITHOUT logging in and shows the
fingerprint for the user to confirm; only after that does it log in (using the pinned key) and allow
Save. The confirmed key is stored in the entry (`host_key`), and every later connection must match it
(`core/ssh_client.py`). `core/vault.update_secret()` exists so a key can be pinned later without changing
the entry's id.

## Since roadmap B7 — storage, key, scopes (read first; older sections below are history where they disagree)

- **Rows in Toolbox's Postgres** (schema `vault`, `../core/state/sqlstore.py`), **dataset blobs in S3 storage**
  (`vault/<id>/<id>.blob`, `../core/state/filecache.py`; local `blobs/` is a cache of *encrypted* chunks). The old
  `vault.db` was copied in once on first start and old blob files are uploaded on start; both stay on the
  `vault_data` volume as a backup. Standalone (no `TOOLBOX_DATABASE_URL`) it is still SQLite + local blobs.
- **The key comes from `TOOLBOX_VAULT_KEY`** (compose passes it from the git-ignored `.env`), or
  `TOOLBOX_VAULT_KEY_FILE`; the legacy `/app/data/vault/vault.key` is only a fallback (health then warns
  "key is on the data volume"). The existing key was moved into `.env` during B7 — **back up `.env`**: without
  that key the secrets can't be decrypted. `vault._vault_meta.key_check` (a Fernet token of a fixed string)
  makes a wrong key fail at startup with `VaultKeyMismatch` instead of failing every decrypt later; the first
  fingerprint is only written after an existing secret decrypts with the key.
- **Scoped access**: plugin server code uses `vault_store.scoped("<plugin>")` (`ScopedVault`), allowed by its
  manifest's `vault: {read: [...], write: [...], datasets: none|read|write}`. A database tool can't read an
  `ssh_server` entry and vice versa; `core/db_endpoint.py` has a fixed library scope (`postgres_connection`
  only); the orchestrator (trusted host code, no manifest) declares its own `Scope`. Only this tool and `core/`
  use the unscoped functions — `tests/unit/test_plugins.py::test_tools_never_use_the_unscoped_vault` enforces it.
- **HTTP scoped read API** for plugin code outside this process (phase C runtimes): `GET /api/v1/scope`,
  `GET /api/v1/secrets?kind=`, `GET /api/v1/secrets/{id}` with headers `X-Toolbox-Plugin: <name>` and
  `Authorization: Bearer <token>`; token = HMAC-SHA256(vault key, plugin name) — `python -m core.vault token <name>`
  (nothing stored; changing the key revokes all tokens). 401 wrong token, 403 kind not in scope. Datasets are not
  served over HTTP yet. The browser-facing endpoints (`/secrets`, `/reveal`, …) are unchanged (same trust model).
- **Backup format 2**: `vault.json` (rows, ciphertext base64) + `vault.key` + `blobs/`. Restore reads format 2
  and the old format 1 (`vault.db` zip). Because the key now comes from the environment, a restore **re-encrypts**
  secrets (and blobs, chunk by chunk) made with another key instead of swapping key files — the old
  `invalidate_key_cache()` dance is gone. Every secret is decrypted before anything is replaced, so a damaged
  backup changes nothing. Verified: unit tests (same key, other-key format-1 backup, damaged backup) and a live
  backup download; the live wipe-and-restore was not run on the owner's vault (blocked as destructive) — the unit
  tests cover it on an isolated vault.
- `/api/state/health` has `vault` (secret count, key source, storage).

## Security posture — read this before touching `core/vault.py`

**No vault master password**, by explicit owner choice. The encryption
key (`core/vault.py`'s `KEY_PATH`, a Fernet key) lives in a `0600` file
on the same persistent volume (`vault_data`) as the encrypted SQLite
database. This means:
- Secrets ARE protected against: casually reading the raw DB file,
  a stray backup of the data volume, an accidental `git add -A` (not
  that this volume is in the repo — it's a Docker volume, not a
  tracked path — but the principle holds for any copy of it).
- Secrets are NOT protected against: anyone with access to the running
  container (they can read both the key file and the DB file). This
  matches the trust model this toolbox already has elsewhere — see
  `df-studio/CLAUDE.md`'s `custom_code` note ("single-user local tool,
  the owner's own code on the owner's own machine... if this tool is
  ever exposed beyond one trusted local user, that decision needs
  revisiting before anything else does"). The same caveat applies here,
  identically.
- **If this is ever deployed somewhere multi-user or remotely
  accessible, this needs a real redesign** (a master password deriving
  the key, a proper secrets manager/KMS) before the vault is trusted
  with anything real — don't patch around it with half-measures (e.g.
  "just obfuscate the key file path") if that day comes.

## How it's built

- `server.py` — thin FastAPI app: `GET /secrets` (metadata only — id/
  name/kind/created_at/updated_at/has_data, **never decrypted data**),
  `POST /secrets` (save — any tool can call this), `GET /secrets/{id}/reveal`
  (decrypts a credential's full data — called only by a consuming
  tool's own "load saved connection" action, never by this page),
  `GET /datasets/{id}/preview` (the row-count-gated CSV preview for
  DataDiff Pro's "Load from Vault" — see `core.vault.preview_dataset_as_csv()`),
  `DELETE /secrets/{id}`, `POST /clear`, `POST /test-connection` (used by
  this page's own "Add connection" form to validate before saving — see
  below), `GET /backup`/`POST /restore` (see "Backup & restore" below).
- `ui/index.html` — lists name/kind/timestamps, a Delete button per row,
  a confirmed "Clear vault" button, an "Add connection" form, and a
  "Backup & restore" card. **This page now has ONE add-secret form of
  its own — but only for the one shape it genuinely understands**: a
  database connection (host/port/database/username/password/db_type,
  optionally an SSH tunnel), test-before-save via `POST /test-connection`
  (a one-off `dialect.verify_connection()` call, nothing stored unless
  the save button is actually clicked — or "Save anyway" to skip the
  test). This does NOT contradict the module's own "no opinion on what
  fields a kind's data contains" design — this page just happens to also
  know one common shape, the same way any other tool could. Every OTHER
  secret shape (an SSH-only credential, a `curl_request`, a
  `curl_result`, anything a future tool invents) still only ever gets
  created from the tool that actually uses that shape, calling
  `POST /tools/vault/secrets` directly — same same-origin cross-tool
  pattern schema-map's Compare feature already uses to call DataDiff
  Pro's endpoint (see `schema-map/CLAUDE.md` Phase D).
- `core/vault.py` — the actual storage/encryption, shared by every
  consuming tool, not owned by this one. See its own docstring for the
  SQLite-on-Docker-volume pattern (copied from `schema-map/project_store.py`)
  and the `Fernet`/key-file mechanics.

## Backup & restore — a real, portable safety net

Added after the owner asked directly: "does this survive if I delete the
container... can we use a different database for this?" Answered by
reading the code, not assumed: `core/vault.py` stores everything under
`/app/data/vault/` (`vault.db`, `vault.key`, `blobs/`), and
`../docker-compose.yml` mounts that exact path to the named Docker
volume `vault_data`. That volume already survives an ordinary
`docker-compose up --build -d` / container recreation — proven
empirically across dozens of rebuilds this project has already gone
through with zero data loss. It does NOT survive an explicit
`docker-compose down -v` or a manual volume deletion, both of which
require a deliberate action, never triggered by a normal rebuild.
**Recommendation that stands: keep SQLite, don't switch to a
client-server database** — SQLite is already the right engine for a
single local writer with a moderate record count, and the actual bulk
data already bypasses it entirely via the chunked-blob-file pattern; a
"real" database would add a whole second service to operate for zero
real gain at this scale, breaking this repo's explicit one-container
decision. The real fix for "is my data safe" is a backup, not a
different engine underneath:

- `GET /backup` — bundles `vault.db` + `vault.key` + every file under
  `blobs/` into one streamed zip (built via `zipfile`, written straight
  to a temp file and cleaned up via a `BackgroundTask` after the
  response is sent — never held fully in memory, since a dataset's blob
  can be sizable). A "⬇ Download backup" button in `ui/index.html`.
- `POST /restore` — accepts that zip (streamed straight to a temp file
  via `shutil.copyfileobj`, same "never buffer the whole upload in
  Python memory" convention `duck-lab/server.py`'s own upload handler
  already uses), extracts it into `DATA_DIR`, **replacing everything
  currently there** — `blobs/` is removed first (`shutil.rmtree`) so a
  restore can never leave orphaned blob files from before it ran. The
  frontend's own confirm dialog (naming exactly what's being replaced)
  is what makes this a deliberate action; the endpoint itself just does
  it unconditionally once called, same as `/clear`.
- **`vault.invalidate_key_cache()`** — called at the end of every
  restore. `core/vault.py` caches the Fernet key in a module-level
  variable after first load (`_cached_key`), on the correct assumption
  that the key never changes during a process's normal lifetime — but a
  restore is exactly the one case that DOES change it out from under a
  running process. Without this call, every decrypt after a restore
  would keep using the stale OLD in-memory key against data now
  encrypted under a genuinely DIFFERENT key, and fail. **Verified for
  real, not just reasoned about**: built a second, independent
  vault.db+vault.key pair with its own freshly-generated key (not a
  copy of the running instance's), restored it onto the already-running
  process, and confirmed the newly-restored secret decrypted correctly
  — this would have thrown a Fernet `InvalidToken` error had the cache
  invalidation not actually been wired in. A naive restore-and-reload
  test using the SAME instance's own backup would NOT have caught this
  bug, since the key never actually changes in that case — don't
  mistake that weaker test for proof this works if you ever touch this
  code again.

## Things that will bite you if you don't know them

- **`list_secrets()` must never be extended to include decrypted data**
  "for convenience" — that's the one invariant that keeps this page safe
  to leave open/screenshot/share. If a future feature genuinely needs to
  show a secret's value, that's a new, explicit, separately-reasoned
  decision — not a tweak to the existing list endpoint.
- **`preview_dataset_as_csv()` always checks the real row count BEFORE
  reading any row data** (`SELECT count(*)` first, the actual
  `SELECT *` only if that count is within `max_rows`). Don't "simplify"
  this into read-everything-then-check-len() — that would defeat the
  entire point (a huge dataset would get fully materialized in memory
  just to be rejected, the exact outcome the row cap exists to prevent).
- **`clear_all()` doesn't touch the key file** — it deletes every row AND
  wipes the whole `blobs/` directory (not just rows — a leftover blob
  file with no SQLite row pointing at it would just be dead weight on
  disk, so clearing removes both). The key file staying in place is
  harmless (there's nothing left to decrypt) and avoids a pointless
  extra file-system operation.
- **Every consuming tool's own `kind` string is just a convention, not
  enforced here.** `core/vault.py` doesn't validate `data`'s shape
  against `kind` at all — if a tool saves inconsistent fields under its
  own kind over time, that's a contract between that tool's save/load
  code, not something this module polices.
- Mounted at `/tools/vault/` by `main.py` in the repo root — this folder
  never needs to know that; it's a fully self-contained ASGI app either
  way (verify with `cd vault && uvicorn server:app --reload`).

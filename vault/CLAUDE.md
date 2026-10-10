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
  `DELETE /secrets/{id}`, `POST /clear`.
- `ui/index.html` — lists name/kind/timestamps, a Delete button per row,
  a confirmed "Clear vault" button. **Deliberately has no add-new-secret
  form** — this page has no opinion on what fields a "postgres_connection"
  vs. an "ssh_credential" needs, so creating one always happens from the
  tool that actually uses that shape of data (sql-studio's "Save this
  connection" button calls `POST /tools/vault/secrets` directly — same
  same-origin cross-tool pattern schema-map's Compare feature already
  uses to call DataDiff Pro's endpoint, see `schema-map/CLAUDE.md` Phase D).
- `core/vault.py` — the actual storage/encryption, shared by every
  consuming tool, not owned by this one. See its own docstring for the
  SQLite-on-Docker-volume pattern (copied from `schema-map/project_store.py`)
  and the `Fernet`/key-file mechanics.

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

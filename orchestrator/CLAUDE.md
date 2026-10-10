# Orchestrator — headless recipes, not a mounted tool

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.

## What this is — and isn't

A way to call any tool's existing engine directly and chain them together,
without a browser. **Not a workflow/DAG engine, not a plugin registry, not
an HTTP dispatch service.** Every tool already runs in one container, one
Python process (`PYTHONPATH=/app`) — composing them is just importing two
modules and calling functions in sequence. This package has no `server.py`,
no `ui/`, no `registry.yaml` entry, no `main.py` mount — it's a plain Python
package + CLI, invoked as a one-shot process:

```
docker compose exec toolbox python -m orchestrator.cli compare \
  --left-kind postgres --left-host host --left-database db --left-username user --left-password pass \
  --left-query "SELECT * FROM t ORDER BY id" \
  --right-kind file --right-path /app/data/expected.csv
```

Or, loading a connection saved in the vault instead of specifying it by hand:

```
docker compose exec toolbox python -m orchestrator.cli compare \
  --left-vault "prod-replica" --left-query "SELECT * FROM t ORDER BY id" \
  --right-kind file --right-path /app/data/expected.csv
```

The motivating case: comparing data across two databases (e.g. after a
migration) doesn't fit "paste text into a browser form" at all — the data
already lives in a database. If you ever need to trigger a recipe from
*outside* this machine, that's the point to add an HTTP layer — not before.

## How it's built

- `connectors/postgres.py` — `fetch_rows(host, port, database, username,
  password, query, *, ssh_tunnel=None) -> list[dict]`. A fresh, minimal,
  **one-shot** connect→query→close helper, using `psycopg.connect()`
  directly (plus `core.postgres_conn.open_ssh_tunnel()` first, when
  `ssh_tunnel` is given). Deliberately NOT built on
  `core.pooled_postgres.PooledPostgresConnection` (the shared class
  `sql-studio/db_engine.py` and `schema-map/db_engine.py` both now use —
  see their own `CLAUDE.md`s) — that class is `async def` and built
  around a pool+reaper lifecycle; a script that connects once, runs one
  query, and exits needs none of it. It does share
  `core.postgres_conn.build_conninfo()`/`scrub_password()` with those two
  tools, so an error surfaces the same way everywhere, one shared primitive rather
  than three.
- `connectors/file.py` — `read_rows(path) -> list[dict]`, using
  `core.file_source.build_read_expr()` — the same extension-to-DuckDB-
  function mapping (`read_csv_auto`/`read_json_auto`/`read_parquet`)
  `duck-lab/engine.py`'s `load_file()` uses, shared rather than
  re-derived here. duck-lab still can't be reused directly, though —
  `duck_lab.engine.Session`'s cookie/data-dir/web-session shape doesn't
  fit a one-shot script.
- `recipes/compare.py` — `compare(left: Source, right: Source,
  **diff_kwargs) -> dict`. Fetches both sides via whichever connector
  matches each `Source`'s `kind` ("postgres", "file", or
  "vault_dataset"), then passes the two row-lists straight into
  `core.pipeline.run_compare()` — **skipping `normalize()` entirely**,
  since DB/file rows are already structured Python objects, not pasted
  text that needs parsing first.
  **`"vault_dataset"`** (`_read_vault_dataset()`) is the real cross-tool
  hand-off this orchestrator was built for: `core.vault.load_dataset_file_by_name()`
  decrypts a dataset saved by duck-lab's or sql-studio's "Save/Export to
  Vault" to a temp file (streamed, bounded memory regardless of size —
  see `vault/CLAUDE.md`), `connectors.file.read_rows()` reads it the
  same way the plain `"file"` source already does, then the temp file is
  deleted. **Verified end-to-end**: saved a 1200-row Postgres query
  result (via sql-studio's uncapped export) and a 3-row Duck Lab result
  to the vault, then `compare --left-vault-dataset ... --right-vault-dataset ...`
  produced the correct diff (matches on shared keys, `EXTRA_LEFT` for
  the 1197 rows only on the Postgres side) — this is the owner's own
  worked example ("postgres, transformed, load in vault, provide to
  DataDiff"), not a synthetic test.
- `cli.py` — `argparse`-based. One subcommand today (`compare`); add a
  second recipe by adding one function in `recipes/` and one subcommand
  here, following the same shape. `--left-vault-dataset`/
  `--right-vault-dataset` are a DIFFERENT flag from `--left-vault`/
  `--right-vault` — the latter loads a DB *connection* (credential),
  the former loads actual *data*; both live in the same vault, under
  different `kind`s, but conflating them in one flag would be a real
  footgun (passing a connection name where a dataset name is expected,
  or vice versa, with no type-level way to catch it).

## One Postgres connector, one file loader — not three/two of each

Before this was cleaned up, sql-studio, schema-map, and this orchestrator
each had their own independent "connect to Postgres safely" logic
(conninfo building, credential pre-validation, password scrubbing), and
duck-lab and this orchestrator each had their own "map a file extension
to a DuckDB read function." Real duplication, not just similar-looking
code. `core/postgres_conn.py` (low-level connect/verify/scrub primitives)
and `core/pooled_postgres.py` (the pool+reaper lifecycle built on top,
used by sql-studio/schema-map) and `core/file_source.py` (the extension
mapping) are now the one shared place each of those lives — this
connector and duck-lab both call `core.file_source.build_read_expr()`
rather than each re-deriving it, and this connector shares
`core.postgres_conn.scrub_password()` with the two pooled tools (it
doesn't use `PooledPostgresConnection` itself — see `connectors/postgres.py`'s
own docstring for why that class is the wrong shape for a one-shot script).

**SSH tunnel support** now exists, shared the same way: `core.postgres_conn.open_ssh_tunnel()`
opens the tunnel (`sshtunnel`/`paramiko`), the caller connects through its
local forwarded port. `connectors/postgres.fetch_rows()` takes an
optional `ssh_tunnel: SSHTunnelConfig` and opens/closes the tunnel around
that one connection — `cli.py`'s `--left-ssh-host`/`--left-ssh-port`/
`--left-ssh-username`/`--left-ssh-password`/`--left-ssh-key-file` flags
(and the `right-` equivalents) build that config. One implementation,
reached from sql-studio, schema-map, and here.

**`--left-vault <name>` / `--right-vault <name>`** load a saved
`"postgres_connection"` secret (host/port/database/username/password,
and its SSH tunnel config if one was saved with it) from `core.vault`
directly — no HTTP round-trip needed here, unlike the browser-based
tools, since the orchestrator already runs in-process in the same image.
`--left-query`/`--right-query` still come from the command line even
when loading from the vault — the vault only ever stores *connection*
details, never a query. See `vault/CLAUDE.md` for the vault itself.

## `core/pipeline.py` — why this exists, and why it's shared

DataDiff Pro's web UI (`api/app.py`'s `/compare` endpoint) and this
orchestrator need the *exact* same mapping/equivalence/diff logic — the
only difference is where the two input objects come from (pasted text run
through `core/normalizer.py`, vs. DB rows/file rows already structured).
`core/pipeline.py`'s `run_compare(left_data, right_data, **kwargs) -> dict`
is that shared logic, extracted out of the endpoint so there's one copy,
not two drifting apart. It raises `PipelineError` (plain Python, not
HTTP-shaped) on any input problem — `api/app.py` catches it and wraps it as
a 422 JSON envelope; `cli.py` catches it (along with connector errors) and
prints to stderr with exit code 1.

## Adding a second recipe

1. A new function in `recipes/<name>.py` that calls whichever
   connector(s) it needs and returns a plain dict (JSON-serializable).
2. A new subcommand in `cli.py`'s `main()`.
3. A new connector in `connectors/` only if the data source doesn't fit
   `postgres.py`/`file.py` — otherwise reuse what's there.
4. If it needs its own throwaway dependency, add it to the root
   `requirements.txt` and re-run `./download-wheels.sh` (same as any
   other tool — see `../CLAUDE.md`).

## Things that will bite you if you don't know them

- **This is not mounted by `main.py` and has no `--workers` concern** —
  it's invoked as a one-shot `python -m orchestrator.cli ...` process, not
  a long-running server. Don't add FastAPI/session state here; if a recipe
  genuinely needs a web UI, that's a new tool under the normal "Adding a
  new tool" checklist in `../CLAUDE.md`, not a change to this package.
- **`fetch_rows()`/`read_rows()` return everything in one `list[dict]`** —
  there's no pagination or streaming here, unlike duck-lab's web UI. A
  recipe run against a genuinely huge table will hold the whole result in
  memory. That's an acceptable tradeoff for a one-shot script (same
  reasoning df-studio/duck-lab use for their own ceilings) — if a recipe
  ever needs to handle something that doesn't fit in memory, that's a real
  design question to raise, not a silent truncation to add here.
- **`compare()`'s `diff_kwargs` are passed straight through to
  `run_compare()` with no validation of its own** — `recipes/compare.py`
  trusts the caller (the CLI, or your own script) to pass sensible
  keyword arguments; `run_compare()` itself still validates
  `mapper_direction`, the environment YAML, etc. and raises
  `PipelineError` same as it does for the web UI.

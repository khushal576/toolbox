# SQL Practice — tool-local notes

> **Start here:** repo rules `../CLAUDE.md` · where things live: `./KNOWLEDGE_MAP.md`. Content (datasets + questions) lives OUTSIDE this repo in `../../learn-sql/practice/`, mounted read-only at `/practice` in `rt-data` (`TOOLBOX_PRACTICE_DIR`, compose).

## What it is
LeetCode-style SQL practice. Pick a question → read it → open **Schema** (panel above the page) → write a query in the editor → **Run**.
**Check** runs your query and the reference, compares both result sets with DataDiff (`provision.check`): columns must match by name AND order; numbers are rounded to 2 decimals; text is exact (DataDiff calls 'y'/'Y' EQUIVALENT — we treat anything but MATCH as a difference). Unordered questions match rows by content (so you see "missing" / "unexpected" rows); `compare: {order_matters: true}` first compares the ROWS by content (extra / missing rows are reported, positional cell diffs are suppressed because extra rows shift every later position); only when the rows are right does it compare by position, which yields the "right rows, wrong order — add a tie-breaker" hint.
**Progress** is in Toolbox's own Postgres, schema `sql_practice` (so Toolbox backups cover it). Status: new → attempted → solved (✓) | revealed (gave up after 3 wrong Checks; counts for moving on, not for ✓, to be revisited). A syntax error is not an attempt.
**Order:** `questions/_path.yaml` lists the topics in order, then by id; a question is locked until the one before it is solved/revealed (the page's "Keep order" box can be unticked; it is not enforced by the server). **The solution, `trap`, `followup` and `alternatives` fields of a question file reach the browser only once it is completed.**
Question YAML extras: `trap`, `followup`, `alternatives` (shown after completion), `compare: {order_matters, decimals}`.
Next: see `learn-sql/practice/PATH.md` (the step-by-step build list).

## Decisions (owner, 2026-11-14)
- **Own database `practice`** on Toolbox's bundled Postgres, no new container. One SCHEMA per dataset.
- **Learner SQL never runs as the `toolbox` login** (that database holds the Vault). It runs as `practice_user`: CONNECT on the toolbox DB is revoked from PUBLIC, SELECT only on the dataset schemas, read-only transaction, always rolled back, 10 s timeout, 500-row cap, one statement per request (`prepare=True`). Setup alone uses the `toolbox` login (a superuser on the bundled Postgres; an external Postgres needs a role that may CREATE ROLE/DATABASE).
- **The editor is a COPY of SQL Studio's** (`ui/vendor/cm-bundle.js` + the schema→autocomplete function) so SQL Studio can change freely. No connection panel: the editor is already connected; autocomplete comes from `GET datasets/<ds>/schema.json`.
- **Schema preview = a generated page, in Schema Map's look**: circles sized by row count, FK arrows, plus a LEFT column list (types, PK, FK, NOT NULL; click a table in either place to highlight its neighbours). Built from the live practice database by `provision.schema_page()` + `ui/schema_template.html` and served at `datasets/<ds>/schema.html`, so it never drifts and needs no manual export. A hand-saved `learn-sql/practice/datasets/<name>/schema.html` (e.g. a real Schema Map export) overrides it if present. The panel is a fixed OVERLAY above the page (owner: opening it must not move or re-render the question/editor); Esc closes it.
- Questions are YAML files, `questions/<topic>/<id>.yaml`; `solution_sql` is never sent to the browser. `GET /validate` runs every reference SQL (must run, return rows, be deterministic).

## Files
- `provision.py` — create role/DB, load datasets (sha256-tracked, idempotent), run learner SQL, question loading, validator.
- `server.py` — thin FastAPI routes. `ui/index.html` — the page.
- Datasets must be deterministic (no `random()`); a changed `schema.sql`/`seed.sql` is reloaded on the next Set up.

## Gotchas
- `docker-compose.yml` mounts `${TOOLBOX_PRACTICE_DIR:-../learn-sql/practice}` — keep the learn-sql repo next to toolbox or set the variable in `.env`.
- YAML turns bare `null`/`yes`/`no` into values — quote tags like `"null"`.
- `core/vault.py` seeds the Vault connection "Practice database (built-in)" (password `TOOLBOX_PRACTICE_PASSWORD`, default `practice-local-only`; not a secret worth protecting — it can only read practice data).

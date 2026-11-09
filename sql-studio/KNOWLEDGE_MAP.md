<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: SQL Studio — mounted at `/tools/sql-studio/`

A multi-database SQL workspace (Postgres, SQL Server, or Oracle — a
"Database type" selector in the Connection panel, see `core/db/`'s
`Dialect` abstraction in the repo-wide table above): paste/edit/pretty-print a query (arbitrary
complexity, comments preserved), an optional schema panel — paste
`{"table_name": {"column_name": "data_type"}}` to get table/column
autocomplete, or click "⚡ Fetch Schema" (in the main toolbar, next to
Run) to fetch and load it live once connected — a schema-filter dropdown
right next to it picks which schema(s) to pull from (one, several, or
"All schemas"; not hardcoded to `public`), with same-named tables across
different schemas auto-disambiguated as `schema.table` only when they'd
actually collide — several named query buffers/tabs, keyboard shortcuts
(Ctrl+Enter format, Ctrl+Shift+Enter Run, Ctrl+K template
search, Ctrl+F find/replace floating top-right of the editor VS
Code-style, auto-format on paste), a Templates panel (sidebar, between
Connection and Schema) with ~125 prebuilt Postgres/PL/pgSQL snippets that
insert at the cursor as real Tab-navigable fields, live-filtered against
whatever you're typing with the last word weighted highest — and a
**live Run against a real database of any of the three types**: a
Connection panel (top of the sidebar, collapsed by default, collapses to
a compact status line once connected) opens a server-side pool of up to
3 connections, Run executes exactly one statement at a time with a hard
500-row cap enforced by the database itself (a dialect-specific wrap —
`LIMIT` for Postgres, a trailing `OFFSET/FETCH` for SQL Server, `FETCH
FIRST` for Oracle — never fetched-then-truncated), destructive statements
(`DROP`/`TRUNCATE`/`DELETE`/`ALTER`) require an explicit confirm, and
results show in a dismissible overlay with CSV/JSON export — plus **"show"
commands** (`show tables`, `show table orders definition`, `show
functions`, `show triggers`, `show activity`, ...), a `psql \d`-family
equivalent typed as plain phrases: type one and press Run, the real
system-catalog SQL runs in its place, results show the same way. 32 for
Postgres; an additional ~11 each for SQL Server/Oracle (the highest-value
subset — several Postgres ones, like extensions or enum-type catalogs,
have no clean equivalent in the other two and are Postgres-only by
design, not an oversight). They're listed in the Templates panel (typing
"show" surfaces them, deduplicated across dialects since the phrase is
identical either way — see `sql-studio/CLAUDE.md`) and in a full
cheatsheet behind the "?" button next to Run, filtered to whichever
database type is currently selected. Format,
Templates, and Schema autocomplete remain 100% client-side and
unaffected — only Run/Connect/Export/schema-fetch touch
`sql-studio/server.py`'s backend routes (`db_engine.py`/`query_guard.py`);
show commands are a pure client-side text substitution before Run's
normal pipeline, not a new backend capability.
**Only the header's old "🧩 Templates" nav button was removed** (at the
owner's explicit request) — the Templates panel itself was NOT removed
and is still fully present and always visible; `Ctrl+K` still jumps to
its search box the same way the button used to. See
`sql-studio/CLAUDE.md`'s "Live database connection (Run)" section for the
full Run design (why one global connection instead of df-studio's
per-cookie pattern, the row-cap mechanism's real limits, the
two-copies-kept-in-sync tokenizer).

| If you need to change...                                              | Go to |
|-------------------------------------------------------------------------|-------|
| The CodeMirror editor setup (extensions, basicSetup, keymap, search, paste handler, doc-change listener) | `sql-studio/ui/index.html` — `view`/`EditorState.create(...)` |
| How the pasted schema JSON becomes autocomplete suggestions             | `index.html` — `buildSchemaNamespace()` |
| Applying a newly-pasted schema without rebuilding the editor            | `index.html` — `sqlLangCompartment` / `makeSqlExtension()` / `applySchema()` |
| Format behavior (indentation, keyword case, dialect)                   | `index.html` — `formatQuery()` (`sqlFormat(...)`) — called from the Format button, Ctrl+Enter, and paste-triggered auto-format alike |
| Formatting inside a `$$...$$` stored procedure/function body            | `index.html` — `reformatDollarQuotedBodies()` + `formatPlpgsqlBody()` (sql-formatter itself never touches dollar-quoted content — see `sql-studio/CLAUDE.md` for the known limitations of this hand-rolled pass) |
| Buffer tabs (add/close/rename/switch), migration from the old single-query key | `index.html` — `loadBuffers()`, `switchBuffer()`/`addBuffer()`/`closeBuffer()`/`renameBuffer()`, `renderBufferTabs()` |
| Keyboard shortcuts (Ctrl+Enter format, Ctrl+Shift+Enter Run, Ctrl+K template search) | `index.html` — the `keymap.of([...])` extension in `view`'s config (Format/Run), and the global `keydown` listener near the bottom of the script (Ctrl+K) |
| Ctrl+F find/replace (functionality is stock CodeMirror; only its position/look is custom) | `index.html` — `search({ top: true })` extension + `#editor .cm-panel.cm-search` CSS block (see `sql-studio/CLAUDE.md` for the DOM structure this CSS targets) |
| Auto-format on paste                                                    | `index.html` — `EditorView.domEventHandlers({ paste: ... })` in `view`'s config, `chkAutoFormat` |
| Schema panel parsing/validation/persistence                            | `index.html` — `applySchema()`, `schemaErr` box |
| The "copy schema-fetch query" pgAdmin round-trip helper                 | `index.html` — `SCHEMA_FETCH_QUERY` const, `btnCopySchemaQuery` (uses `json_object_agg`, not `jsonb_object_agg` — see `sql-studio/CLAUDE.md` for a real ordering bug caught by testing against an actual Postgres) |
| Fetching + loading the schema live from the connected database          | `index.html` — `btnFetchSchema` click handler (runs `buildSchemaFetchQuery(getCurrentSchemaFilter())` via `POST /query`, then `applySchema()`) — shares the same query-builder as the manual-copy path (`btnCopySchemaQuery`) above |
| Which schema(s) Fetch Schema pulls from, adding/changing the schema-filter dropdown | `index.html` — `#btnSchemaFilter`/`#schemaFilterPanel`, `schemaFilterAll`/`selectedSchemas` state, `getCurrentSchemaFilter()`, `ensureSchemaListLoaded()`, `resetSchemaFilterState()` (called from `applyConnectionStatus()` on connect/disconnect) — see `sql-studio/CLAUDE.md` for the cross-schema table-name-collision handling in `buildSchemaFetchQuery()` |
| The Templates library (adding/editing snippets, categories, search)     | `index.html` — `TEMPLATES` array (one `{cat, name, sql}` per entry — add a template by adding an entry, nothing else to wire up) |
| The live "type to find it" ranking (last-word priority)                | `index.html` — `currentLineWords()` + `scoreTemplate()` (see `sql-studio/CLAUDE.md` for how the weighting works and how it was verified) |
| Templates panel rendering / search / insertion                          | `index.html` — `renderTemplateList()`, `insertTemplate()` (live mode replaces the trigger word via `currentLineLastWordSpan()`; blank-line padding uses `isAtLineStart()`/`isAtLineEnd()`, whitespace-aware not just single-character — see `sql-studio/CLAUDE.md` for two real bugs found here) |
| Which words in a template become Tab-stop fields, adding a new one     | `index.html` — `PLACEHOLDER_TOKENS` Set (whitelist, not auto-detected) + `toSnippetTemplate()` — see `sql-studio/CLAUDE.md` for how the whitelist was built and verified against all 125 templates |
| localStorage keys for restoring buffers/schema on reload                | `index.html` — `BUFFERS_KEY` (`sql_studio_buffers`), `ACTIVE_BUFFER_KEY` (`sql_studio_active_buffer`), `SCHEMA_KEY` (`sql_studio_schema`), `AUTOFORMAT_KEY` (`sql_studio_autoformat_on_paste`), `CONNECTION_KEY` (`sql_studio_connection` — host/port/database/username only, password never persisted); `QUERY_KEY` (`sql_studio_query`) is legacy, read-only, for one-time migration into buffer #1 |
| The live connection pool (connect/disconnect/status, idle reaper) for whichever of Postgres/SQL Server/Oracle is currently selected | `sql-studio/db_engine.py`'s `_POOL` — a `core.pooled_db.PooledDbConnection` (module-level, singular — see `sql-studio/CLAUDE.md` for why NOT a per-cookie dict) with NO fixed dialect; `connect(db_type=...)` resolves one via `core.db.registry.get_dialect()` and passes it in per call, so the same `_POOL` can hold a Postgres connection, then later a SQL Server one, never both at once |
| Whether a query is allowed to run, the destructive-statement check, the row-cap wrap (dialect-specific template, see `core/db/dialect_*.py`'s `wrap_row_cap`/`wrap_dml_returning_cap`) | `sql-studio/query_guard.py` — `prepare(sql_text, dialect)` (entry point), `classify(statement, dialect)`, `split_statements()` — the server-side, authoritative copy; `index.html`'s `splitTopLevelStatements()`/`firstStatementKeyword()` is the client-side UX-only twin, kept in sync by hand. A row-returning `INSERT`/`UPDATE`/`DELETE ... RETURNING`/`OUTPUT` statement that this dialect can't safely cap (`wrap_dml_returning_cap()` returns `None` — Oracle's `RETURNING INTO`, SQL Server's `OUTPUT`) is rejected with a clear `GuardError`, not run uncapped |
| Connect/Disconnect/Run/Export backend routes                            | `sql-studio/server.py` — `/connect`, `/disconnect`, `/status`, `/query`, `/export/csv`, `/export/json`, `/export/vault` (the uncapped, streamed-to-Vault export — see `db_engine.export_to_file`) |
| Connection panel UI (collapsed-by-default ↔ full-form ↔ collapsed-status-line, localStorage persistence) | `index.html` — `applyConnectionStatus(status, forceOpen)`, `loadConnectionFields()`/`saveConnectionFields()`, `#detConnection` (see `sql-studio/CLAUDE.md` for the `forceOpen` rule — only Disconnect's click handler passes `true`) |
| Run button, the results overlay, the destructive-confirm dialog          | `index.html` — `runQuery()`/`sendQuery()`, `renderResults()` (`#resultsDialog`), `openConfirmDialog()` (`#confirmDialog`) |
| The "show tables"/"show table X definition"/etc. commands — adding one, changing the mapped SQL, the "?" cheatsheet | `index.html` — `SHOW_COMMANDS` array (single source of truth for matching AND the cheatsheet AND the Templates entries), `matchShowCommand()`, `buildHelpDialog()` (`#helpDialog`) — see `sql-studio/CLAUDE.md`'s "Show commands" section before touching array order |
| Which database type is selected/connected, and everything that follows from it (port default, "Database" vs "Service Name" label, CodeMirror highlighting dialect, sql-formatter language, which `SHOW_COMMANDS`/schema-fetch/schema-list query applies) | `index.html` — `#connDbType`, `currentDbType()`, `DB_TYPE_LABELS`/`DB_TYPE_DEFAULT_PORTS`/`CM_DIALECT_FOR_DBTYPE`/`FORMATTER_LANG_FOR_DBTYPE`/`CONN_DATABASE_LABELS` lookup tables, `applyDbTypeToForm()` (called on page load and on the selector's `change` event — also what re-runs `buildHelpDialog()` and `refreshSqlDialectExtension()`) |
| A `SHOW_COMMANDS` entry's dialect scope — which db type(s) it applies to | `index.html` — the entry's `dbTypes` field (array of `"postgres"`/`"mssql"`/`"oracle"`; **missing entirely means Postgres-only**, since all 32 original entries predate multi-database support); `commandAppliesToCurrentDbType()` is the one function both `matchShowCommand()` and `buildHelpDialog()` check before matching/listing an entry |
| Fetching the schema live from a connected database (any of the three types) | `index.html` — `buildSchemaFetchQuery()` dispatches to `buildSchemaFetchQueryPostgres`/`Mssql`/`Oracle` by `currentDbType()`; Python twins (same SQL, verified against real containers) live in `core/db/dialect_*.py`'s `schema_fetch_query()` — two independent copies, kept in sync by hand, same convention as the tokenizer |
| Calling the SAME introspection (tables/columns/functions/triggers/indexes/foreign keys/views/activity/grants/version) headlessly, without a browser, for any of the three database types | `core/db/dialect_*.py`'s `list_tables_sql()`/`table_columns_sql()`/`table_definition_sql()`/`list_functions_sql()`/`list_triggers_sql()`/`list_indexes_sql()`/`list_foreign_keys_sql()`/`list_views_sql()`/`activity_sql()`/`grants_sql()`/`version_sql()` — real SQL-text-returning methods on every `Dialect`, not just Postgres; this is what makes `core/db/` an actual reusable introspection base, not just a connector. `ui/index.html`'s `SHOW_COMMANDS` keeps its own independent copy (same convention as above); both were fixed together when a system-schema-filtering gap was found (see `sql-studio/CLAUDE.md`) |

### Known non-obvious behavior

- **Loaded via `<script type="module">`, not a plain `<script>`** — the
  only tool in the Toolbox that does this. CodeMirror 6 is ESM-only, so its
  packages (and `sql-formatter`) are imported directly from esm.sh rather
  than a classic `<script src>` tag like df-studio's Tabulator.js.
- **CodeMirror 6 needs all its packages to resolve to one shared instance**
  of `@codemirror/state`/`@codemirror/view`, or importing them separately
  causes an "Unrecognized extension value" runtime error — hit for real
  while building this tool. Fixed by importing `@codemirror/state` as the
  version *range* `@^6.0.0` (matching the range baked into `codemirror`'s
  own bundle) via esm.sh, so both resolve to the same shim URL. See
  `sql-studio/CLAUDE.md` for the full verification trail — don't change
  these import URLs without re-reading it.
- **`sql-formatter` throws on unparseable SQL** rather than best-effort
  formatting — surfaced in the red error box under the editor, not
  swallowed silently.
- **A structure Outline panel (parsed DECLARE/IF/LOOP/CASE tree, click to
  jump, click-a-variable-to-highlight-its-uses) existed briefly and was
  removed** at the owner's request — too much sidebar/scroll weight for
  this tool's actual workflow. It's not recoverable from git history
  (`sql-studio/` — really the whole repo — is untracked, no VCS at all) —
  see `sql-studio/CLAUDE.md` for the approach if it's ever rebuilt. The
  Templates panel is a **different** case — it's still fully present, see
  the next bullet; only its header nav button was removed.
- **Only the header's old "🧩 Templates" nav button was removed, NOT the
  Templates panel** — the panel (~125-snippet searchable library with
  live-filtering and Tab-stop snippet fields) is still fully present and
  always visible in the sidebar, between Connection and Schema. The
  button just used to open/scroll to it and focus search; `Ctrl+K` still
  does that exact same thing. Don't confuse this with the Outline panel
  above, which really was removed entirely — these are two different
  histories for two different features.
- **The sidebar (`.col-right`) DOES cap its own height and scroll
  independently** (`max-height: calc(100vh - 40px); overflow-y: auto`,
  still `position: sticky`) — **this is a reversal of an earlier
  decision, not an oversight.** The identical change was tried once right
  after the Outline panel shipped, explicitly reverted at the owner's
  request, and documented here as "don't reintroduce without asking
  again." The owner then asked again, once Connection + Templates + 32
  show commands + Schema stacked in one column made an unbounded sidebar
  genuinely unusable (confirmed by the owner's own screenshot). See
  `sql-studio/CLAUDE.md`'s "What this tool is" section for the full
  history — if this gets reverted a second time, treat that the same way
  as the first revert (don't silently re-add it without being asked).
- **Ctrl+F's find/replace panel floats top-right of the editor instead of
  its library-default full-width bottom bar** — the find/replace
  functionality itself is 100% stock `@codemirror/search` (bundled into
  `basicSetup`'s `searchKeymap`, no custom logic); only its position and
  look are overridden (`search({ top: true })` + `#editor .cm-panel.cm-
  search` CSS, `position: absolute` anchored to `#editor`). See
  `sql-studio/CLAUDE.md` for the DOM structure that CSS depends on.
- **Buffer tabs replaced a single flat `sql_studio_query` key** with an
  array (`sql_studio_buffers`) — an existing user's previously-saved query
  is migrated into buffer #1 automatically on first load after this
  shipped, verified against fresh-install/migration/existing-buffers/
  corrupted-JSON scenarios with a standalone Node test before shipping.
- **The paste event fires before CodeMirror inserts the pasted text** —
  auto-format-on-paste's handler has to `setTimeout(fn, 0)` before calling
  `formatQuery()`, or it formats the doc as it was *before* the paste.
- **The live Postgres connection is one global value, not per browser
  tab** — every open tab shares the same connection/pool and sees the same
  `GET /status`. This is deliberate (the owner asked for "a single
  database at a time" with "a pool of 3"), not a missed per-session-cookie
  pattern — see `sql-studio/CLAUDE.md` for why copying df-studio's
  per-cookie `SESSIONS` shape here would have broken that constraint.
- **The idle-connection reaper starts lazily on first successful
  `/connect`, not via a FastAPI `lifespan` hook** — `main.py` mounts every
  tool via `app.mount(...)`, and Starlette does not forward lifespan
  events into mounted sub-apps, so a `lifespan=` handler here would
  silently never run. See `sql-studio/CLAUDE.md`'s "Live database
  connection (Run)" section.
- **Run is hard-limited to exactly one statement, and rejects `COPY`
  outright** — both checked via `query_guard.py`'s statement splitter
  (server-side, authoritative) and `index.html`'s `splitTopLevelStatements()`
  (client-side, UX-only fast path). A `;` or a keyword inside a string,
  comment, or `$$...$$` dollar-quoted body is never mistaken for a
  statement boundary — both implementations reuse the same
  string/comment/dollar-quote-aware tokenizing rules as the PL/pgSQL
  formatter's own `tokenizePlpgsqlBody()`.
- **Export never re-runs the query — it serializes the last cached
  result** (`db_engine._last_result`, a module-level variable local to
  sql-studio — deliberately not part of the shared pool class, since
  it's this tool's own concern — set on every successful rows-shaped
  `/query`, cleared on every non-rows one and explicitly on disconnect).
  Re-querying on export would double-execute a `DELETE`/`UPDATE`; this is
  why it doesn't.
- **The 500-row cap is enforced by an outer `LIMIT` at Postgres itself**
  (`SELECT * FROM (<query>) AS _sq LIMIT 500`), not fetched-then-truncated
  in Python — guarantees the row count returned, but does **not** by
  itself guarantee bounded query *cost* for aggregate/`GROUP BY`/window
  queries over a huge table (Postgres still computes the full aggregation
  before the outer `LIMIT` trims output). Runtime is bounded separately —
  see the next bullet.
- **A 15-second `statement_timeout` applies to every query, set on the
  connection pool's conninfo** (`db_engine.STATEMENT_TIMEOUT_MS`, passed
  as `statement_timeout_ms` to `PooledPostgresConnection`) — this
  is what actually bounds a slow query, since the row cap above doesn't. A
  query that runs long gets cancelled by Postgres (`QueryCanceled`) and
  surfaced as a clean error instead of hanging one of the pool's 3
  connections indefinitely.
- **The live connection already survives an ordinary browser refresh —
  no session/cookie/client-side storage involved.** `_POOL.state` lives
  in server-process memory; `GET /status` (polled on every page load)
  reports it regardless of how many times the page reloads. Only three
  things actually drop it: the 20-minute idle reaper (passed as
  `idle_timeout_seconds` to `PooledPostgresConnection`), an explicit
  Disconnect click, or the
  server process itself restarting (e.g. `docker-compose up --build` to
  ship a code change) — the last one is easy to mistake for "refresh
  drops it" if a rebuild and a refresh happen close together during
  active development. Verified directly (connect, then poll `/status`
  repeatedly with nothing else touched — stayed connected). Don't add
  session storage or client-side reconnect logic to "fix" this.
- **Run honors a text selection (pgAdmin/DataGrip-style)** — a non-empty
  selection in the editor runs only that selected text
  (`view.state.sliceDoc(...)`), not the whole buffer; no selection falls
  back to the previous whole-document behavior. Covers the Run button,
  `Ctrl+Shift+Enter`, and the destructive-confirm preview all at once,
  since they all just consume whatever `runQuery()` decides `sqlText` is.
- **A `<dialog>`'s `display` CSS must stay scoped to `[open]`** — a real
  bug: `dialog#resultsDialog { display: flex; ... }` with no `[open]`
  qualifier out-specificities the browser's own `dialog:not([open]) {
  display: none; }` (an ID selector beats a type+pseudo-class one), so the
  results panel showed permanently, inline in the page, instead of only
  via `showModal()` on Run. Fixed by moving `display: flex;
  flex-direction: column;` to `dialog#resultsDialog[open]`; sizing rules
  stayed unscoped since they don't affect visibility. See
  `sql-studio/CLAUDE.md` before adding more dialog CSS.
- **The Connection panel starts collapsed and stays that way on a silent
  page-load status check** — only an explicit Disconnect click passes
  `forceOpen: true` to re-expand it. A silent `GET /status` on load must
  never force it open; an earlier version did, which is what the owner
  flagged as "connection should not [be] shown [by] default." See
  `sql-studio/CLAUDE.md`'s "Live database connection (Run)" section.
- **The header has no trust badge at all now** — just the title. Both
  badges that ever existed (the original "100% client-side" one, and a
  later Run-specific second line) plus the descriptive subtitle line were
  each tried and explicitly removed at the owner's request ("wasting
  space, no use case" the first time, "make more space" the second).
  Don't reintroduce any of them without asking again.
- **The "⚡ Fetch Schema" button lives in the main editor toolbar (next to
  Run), not inside the Schema panel** — moved there at the owner's
  request so it's reachable without expanding/scrolling the sidebar. Its
  id (`btnFetchSchema`) and all its JS (click handler, the disabled/title
  toggling in `updateConnectionGatedButtons()`) are unchanged — only its
  HTML position moved, `getElementById` doesn't care where in the page an
  element lives.
- **The Schema panel's two explanatory hint paragraphs were removed**
  ("no one reads this") — `btnLoadExample` survived, relocated to a small
  link next to `btnApplySchema`. The third hint (explaining
  `btnCopySchemaQuery`, directly above that button) was left alone.
- **"show" commands are a pure client-side text substitution, not a new
  backend capability** — `matchShowCommand()` swaps the typed phrase for
  real SQL entirely in the browser, before `POST /query` is ever called;
  `query_guard.py` never sees or knows about "show tables" text. All 32
  are verified against a real Postgres (not written from memory) — see
  `sql-studio/CLAUDE.md`'s "Show commands" section.
- **`SHOW_COMMANDS` array order matters for literal-phrase commands that
  share a prefix with a generic parameterized one** — e.g. `show table
  sizes` must be listed before the generic `show table <name>` pattern,
  or "sizes" gets matched as if it were a table name. Parameterized
  patterns with a trailing suffix (`show table X definition`) don't have
  this problem — they're strictly anchored and can't collide with the
  bare `show table X` form regardless of order.
- **Object definitions are looked up by bare name via explicit catalog
  joins, not `'name'::regclass`/`'name'::regproc` casts** — those depend
  on the connection's `search_path` and silently do the wrong thing for
  anything outside it. See `sql-studio/CLAUDE.md` for the specific bug
  this was rewritten to avoid.
- **Clicking a "?" cheatsheet row runs it immediately for a no-parameter
  command, but only inserts it into the editor for a parameterized one**
  — a real reported friction point, not a design nicety: "Show
  Materialized Views" used to just paste text requiring a manual Run
  press, exactly backwards when the whole point was seeing the list of
  names right away. Each row's small right-aligned tag ("▶ run now" / "✎
  fill in & run") tells you which one to expect before clicking. See
  `sql-studio/CLAUDE.md` for the detection mechanism and its one sharp
  edge (a future parameterized command not written with a `(\S+)`
  capture group would be silently misclassified as run-now).
- **`show table X definition`/`show function X definition`/etc. used to
  render as one unreadable line** — the results `<table>`'s CSS needs
  `white-space: nowrap` for ordinary short-value rows, which silently
  collapsed the real embedded newlines in these DDL results. Fixed by
  detecting the *shape* (one row, one column, the cell is a string
  containing `\n`) and rendering that case as preformatted text instead
  of a table — see `sql-studio/CLAUDE.md` for `.results-definition` and
  why it uses `pre-wrap` rather than plain `pre`.

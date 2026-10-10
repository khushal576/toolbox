# SQL Studio — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A Postgres SQL workspace for legacy/messy queries: paste a query, edit it,
pretty-print it (indentation, keyword casing, preserves `--` and `/* */`
comments), and optionally **run it against a real Postgres database** (see
"Live database connection (Run)" below — the one part of this tool that
isn't client-side). Optionally paste a schema as `{"table_name":
{"column_name": "data_type"}}` to get table and column name autocomplete
while typing — or, once connected, click "⚡ Fetch Schema" (in the main
toolbar above the editor, next to Run — see below) to fetch and load it
automatically instead of the manual pgAdmin round-trip (re-runnable any
time you connect to a different database or alter tables).
Several named query buffers (tabs above the editor, localStorage-backed)
can be open at once. `Ctrl+Enter` formats, `Ctrl+Shift+Enter` runs,
`Ctrl+K` jumps into template search, and an "auto-format on paste" toggle
formats automatically on paste. A "Templates" panel — in the sidebar,
between Connection and Schema — holds a searchable library of ~125 common
Postgres/PL/pgSQL snippets (tables, indexes, views, functions, procedures,
triggers, control flow, cursors, queries, window functions, DML,
JSON/arrays, transactions, common patterns) plus 32 "show" commands (see
"Show commands" below) that insert at the current cursor position as real
Tab-navigable snippet fields. Its default (search box empty) mode is a
live "type to find it" list — it re-scores every template against the
words on the editor's current line every keystroke, weighting the last
word far higher than earlier ones, so typing e.g. "alter" or "rank"
surfaces the matching templates without any extra action. **The header's
old "🧩 Templates" nav button (which just opened/scrolled to this
always-visible panel and focused search) was removed at the owner's
explicit request — the panel itself was NOT removed, it's still always
visible in the sidebar exactly as before; only that one header shortcut
button is gone.** `Ctrl+K` still does the same jump-and-focus the button
used to do, since that's a distinct keyboard-workflow feature, not the
thing that was asked to be removed. The header is now just the title —
a descriptive subtitle line, and both trust-badge lines that ever
existed (the original "100% client-side" one and a later Run-specific
one), were each tried and explicitly removed at the owner's request
("wasting space, no use case" / "make more space") — **don't reintroduce
any of them without asking again.** The sidebar (`.col-right`) DOES now
cap its own height and scroll independently (`max-height: calc(100vh -
40px); overflow-y: auto`, still `position: sticky`) — **this reverses an
earlier decision**, not an oversight: an identical-shaped change was
tried once before, explicitly reverted at the owner's request, and
documented here as "don't reintroduce without asking again" — the owner
then asked again, once Connection + Templates + 32 show commands +
Schema stacked in one column made an unbounded-height sidebar genuinely
unusable (confirmed by the owner's own screenshot). If this gets
reverted a second time, don't silently re-add it a third time without
being asked just as explicitly as this time. CodeMirror's own built-in
Ctrl+F find/replace (from `@codemirror/search`,
already wired through `basicSetup`'s `searchKeymap` — no keybinding code
needed for it to work) has its panel repositioned to float top-right of
the editor, VS Code style, instead of its library default of a full-width
bar at the bottom — see the `search({ top: true })` extension and the
`#editor .cm-panel.cm-search` CSS override below. A structure outline
panel (parsed `DECLARE`/`IF`/`LOOP`/`CASE` tree, click to jump) existed
briefly between earlier feature rounds and was removed at the owner's
request — it added a third sidebar panel and scroll weight without
earning its keep for this tool's actual workflow. This repo isn't under
git (`git status` shows `sql-studio/` — really the whole repo — as
untracked, no commit history to recover a prior version from), so if the
outline panel is ever rebuilt it's from scratch: the parsing approach
(reuse `tokenizePlpgsqlBody()` + `topFrame()`/`popFrame()`, add a `start`
offset field to the tokenizer's segments, scan for structural keywords
with real document positions instead of re-flowed text) is still sound.

## How it's built

- `server.py` — serves `ui/index.html`, plus the Run feature's backend
  routes: `/connect`, `/disconnect`, `/status`, `/query`, `/export/csv`,
  `/export/json`. Thin — parses the request, delegates to `db_engine`/
  `query_guard`, turns their exceptions into clean 400/409 JSON errors.
- `db_engine.py` — the live Postgres connection. One module-level pool
  instance (`_POOL`, a `core.pooled_postgres.PooledPostgresConnection`),
  **not** a per-cookie dict — see "Live database connection (Run)" below
  for why that's a deliberate departure from df-studio's session pattern,
  not an oversight. The pool+reaper lifecycle itself (the `ConnectionState`
  dataclass, the idle reaper, credential pre-validation before opening the
  pool) is now shared with `schema-map/db_engine.py` via
  `core/pooled_postgres.py` — each tool still builds its **own** `_POOL`
  instance (genuinely separate connections, not a shared one); only the
  mechanics moved, not the state. This file keeps its own `execute()`/
  `last_result`/`STATEMENT_TIMEOUT_MS`/`ROW_CAP` — the SQL-execution and
  result-caching behavior specific to Run, built on `_POOL.run(...)`
  rather than duplicating pool-checkout logic. Every psycopg call is
  still sync, still run via `asyncio.to_thread` inside the shared
  `_POOL.run()` (same reason df-studio does this — see its own
  CLAUDE.md's `--workers 1` gotcha). The idle-connection reaper is owned
  by the shared class now, lazily started on first successful connect —
  see the lifespan gotcha below for why it's *not* wired through
  FastAPI's `lifespan=`.
- `query_guard.py` — the actual security boundary for Run: splits input
  into statements and classifies the one statement Run is allowed to
  execute (destructive? does it return rows? does it need the `LIMIT 500`
  wrap?). Has a **Python port** of `tokenizePlpgsqlBody()` (`tokenize()`
  here) — see the "two copies, kept in sync by hand" gotcha below.
- `ui/index.html` — everything else. Single file, no build step. Uses
  `<script type="module">` (not a plain `<script>` like the rest of the
  Toolbox) because CodeMirror 6 is ESM-only — imports are loaded directly
  from esm.sh, no bundler (see the CDN-dedup gotcha below before touching
  any import line).
- **Format, Templates, and Schema autocomplete are still 100% client-side**
  — same reasoning as `encode-decode/` and `curl-builder/`, unchanged by
  the Run feature. Formatting runs through `sql-formatter`, the Templates
  panel is a static in-page data array, and autocomplete runs through
  CodeMirror's `@codemirror/lang-sql` — all three entirely in the browser;
  nothing involved in them is ever sent to this server. **Run, Connect,
  Export, and the schema "Fetch from connected DB" button are the
  deliberate exception** — this tool's CLAUDE.md used to say "no backend
  processing, intentionally... re-raise the tradeoff with the owner
  first"; that re-raising happened (the owner explicitly asked for real
  database connectivity), and this backend is the result. **No trust
  badge exists in the header at all anymore** — both the original "100%
  client-side" badge and a later, more scoped Run/Connect/Export-specific
  second line were each tried and explicitly removed at the owner's
  request (once as "wasting space, no use case," again later as "make
  more space"). Don't reintroduce either without asking again — the
  trust-boundary facts themselves (Format/Templates/Schema autocomplete
  stay client-side, only Run/Connect/Export/schema-fetch touch the
  backend) are true regardless of whether a badge states them in the UI,
  they just live here in this file now, not in the page itself.

## Where each feature lives (inside `ui/index.html`'s module script)

- `view` (the `EditorView`) — the CodeMirror instance, built with
  `basicSetup` (line numbers, history, bracket matching, default
  autocomplete UI, etc.) plus the SQL language extension.
- `sqlLangCompartment` / `makeSqlExtension()` — the SQL language + schema
  config is wrapped in a `Compartment` specifically so a newly-pasted
  schema can be applied to the *already-running* editor via
  `view.dispatch({ effects: sqlLangCompartment.reconfigure(...) })` instead
  of tearing down and rebuilding the editor.
- `buildSchemaNamespace()` — turns the pasted `{table: {col: type}}` JSON
  into the `SQLNamespace` shape `@codemirror/lang-sql` expects (table names
  become top-level completions automatically from the object's own keys;
  each table's value becomes an array of column `Completion` objects).
- `formatQuery` (the `btnFormat` click handler) — calls `sql-formatter`
  with `language: "postgresql"`, then `reformatDollarQuotedBodies()`.
- `reformatDollarQuotedBodies()` / `formatPlpgsqlBody()` — sql-formatter
  treats a `$$...$$` / `$tag$...$tag$` block as one opaque string token and
  never reformats what's inside it, which left stored-procedure/function
  bodies completely untouched (the exact case this tool exists for — see
  history: this was reported broken and fixed after shipping v1). These two
  functions are a small line-oriented PL/pgSQL pretty-printer that runs
  *after* sql-formatter, finds each dollar-quoted block sql-formatter left
  alone, and re-indents it using a block-frame stack (`topFrame`/
  `popFrame`) that tracks DECLARE/BEGIN/END, IF/ELSIF/ELSE/END IF, LOOP/END
  LOOP (including FOR/WHILE headers), CASE/WHEN/END CASE, and
  EXCEPTION/WHEN nesting. `maybeFormatStatement()` additionally re-runs
  `sql-formatter` on any embedded DML line (SELECT/INSERT/UPDATE/DELETE/
  WITH) found inside the body. `tokenizePlpgsqlBody()` keeps string
  literals, `--`/`/* */` comments, and nested dollar-quotes from ever being
  touched by the keyword-based line-breaking pass.
- Schema panel (`applySchema()`, `btnApplySchema`, `btnLoadExample`) —
  parses the pasted JSON, validates it's a plain object (not an array/null/
  primitive), reconfigures the compartment, updates the "N tables" badge.
  **The panel's two explanatory `<p class="hint">` paragraphs (the schema-
  paste JSON-shape explanation, and the "Connected to a database? Fetch
  and load..." one) were removed at the owner's request** ("no one reads
  this") — `btnLoadExample` survived, just relocated from inside the
  removed first paragraph to its own small link next to `btnApplySchema`
  at the bottom of the panel. The third hint (explaining
  `btnCopySchemaQuery`, just below it) was left alone — not asked for,
  and it's directly adjacent to the one button it explains rather than
  generic filler.
- `buildSchemaFetchQuery(schemas)` — **a function now, not a constant**
  (it was `SCHEMA_FETCH_QUERY` originally, hardcoded to `WHERE n.nspname =
  'public'` — a real limitation the owner caught: "but we can work in any
  schema"). Takes `"all"` (every non-system schema, same
  `SYS_SCHEMA_FILTER` the `SHOW_COMMANDS` use) or an array of specific
  schema names, and produces the `{"table_name": {"column_name":
  "data_type"}}` shape the schema box expects, as a single JSON cell. Two
  ways to use it: `btnCopySchemaQuery` (in the Schema panel) copies it to
  run manually in pgAdmin/psql and paste the result back — the original
  path, still there for anyone without a live connection; `btnFetchSchema`
  ("⚡ Fetch Schema", main toolbar next to Run) runs it directly through
  `POST /query` against the live connection and calls `applySchema()`
  automatically. Both read `getCurrentSchemaFilter()` (below) for which
  schemas to use, so a change to either the query or the filter logic
  only needs to happen once.
  **`btnFetchSchema`'s handler doesn't go through `runQuery()`/
  `sendQuery()`** (no results dialog, no destructive-confirm dance needed
  for a plain `SELECT`) — it's a standalone `fetch("query", ...)` call.
  One thing worth knowing: `POST /query` wraps every row-returning
  statement as `SELECT * FROM (<stmt>) AS _sq LIMIT 500` (see "Live
  database connection (Run)" below), and psycopg auto-decodes `json`/
  `jsonb` result columns into Python objects — which round-trip through
  the JSON response as already-parsed JS objects, not strings — so the
  handler does `JSON.stringify(cell, null, 2)` before handing it to
  `applySchema()` (which expects text, same as a manually-pasted schema
  would be), not `JSON.parse`.
- **Schema-filter dropdown** (`#btnSchemaFilter`/`#schemaFilterPanel`, in
  the main toolbar next to Fetch Schema) — lets the owner pick which
  schema(s) to fetch from instead of the old hardcoded `public`-only
  behavior. State: `schemaFilterAll` (bool) + `selectedSchemas` (a
  `Set<string>`), read via `getCurrentSchemaFilter()` (returns `"all"` or
  `[...selectedSchemas]`) and written by the checkbox listeners in
  `renderSchemaFilterList()`/the `#chkAllSchemas` listener.
  `ensureSchemaListLoaded()` fetches the actual schema list live (via
  `POST /query`, same `SYS_SCHEMA_FILTER`), cached per-connection in
  `schemaListLoaded`/`availableSchemas` so re-opening the dropdown doesn't
  re-query every time — **`resetSchemaFilterState()` is called from
  `applyConnectionStatus()` on every connect/disconnect transition**
  (not every redundant status poll — guarded by comparing against the
  previous `isConnected` value) so a stale schema list or stale selection
  from a previous database can never leak into a new connection. Default
  selection on first load of a fresh connection: `public` pre-checked if
  it exists (keeps the tool's historical behavior as the default), else
  nothing pre-checked — never guesses at an unfamiliar database's "main"
  schema. Selecting zero schemas (and not checking "All") is treated as
  an error at Fetch time (`showSchemaError(...)`), not silently
  interpreted as "all" or "none" — an explicit choice was ambiguous
  either way, so it's surfaced instead of guessed.
- **Cross-schema table-name collisions are handled automatically, not
  ignored.** Selecting more than one schema (or "All") makes same-named
  tables across schemas a real possibility — the schema box's format is
  flat `{"table_name": {...}}` with no schema qualifier (matches
  `@codemirror/lang-sql`'s `SQLNamespace` shape and the existing example/
  manually-pasted format), so two tables named `orders` in different
  schemas would otherwise collide on the same JSON key and silently lose
  one. `buildSchemaFetchQuery()` uses a `count(*) OVER (PARTITION BY
  table_name)` window-function pass (in a `per_table` → `disambiguated`
  CTE chain) that qualifies a table as `"schema.table"` **only** when
  it's not unique among the selected schemas — everything else stays flat
  and identical to a single-schema fetch. Verified against a real
  Postgres with two schemas (`public`, `analytics`) both containing an
  `orders` table: fetching `"all"` or both explicitly produced
  `analytics.orders` + `public.orders`, while fetching either schema
  alone produced a plain flat `orders` — not assumed correct from reading
  the SQL, actually run and the JSON keys inspected. **Uses
  `json_object_agg`, not `jsonb_object_agg`, deliberately** — this was a
  real bug in the owner's original draft of this query, caught and fixed
  by actually running both versions against a throwaway `postgres:16`
  Docker container (not guessed from syntax alone): `jsonb` canonicalizes/
  reorders object keys internally, so `jsonb_object_agg(..., ORDER BY
  a.attnum)`'s `ORDER BY` is syntactically valid but silently discarded —
  columns came back out of table-definition order. `json_object_agg`
  (text-based `json`, not `jsonb`) preserves aggregation order exactly, so
  the `ORDER BY a.attnum` actually does something. Re-verified after the
  fix, and separately confirmed the resulting Postgres output (which comes
  back with spaces around `:`/`,` — pgAdmin/psql pretty-prints `json`,
  unlike `jsonb`) still parses cleanly through `applySchema()`'s
  `JSON.parse`. If this query is ever touched again, re-verify against a
  real Postgres rather than reasoning about aggregate/ORDER BY syntax from
  memory — that's exactly what went wrong the first time.
- `loadStored()` / `saveStored()` — the `localStorage` read/write helpers.
  Query text persists under `sql_studio_query`, schema JSON text under
  `sql_studio_schema`. Both restore on page load.
- `TEMPLATES` — the plain data array (`{cat, name, sql}` per entry) behind
  the Templates panel. To add a template, add one entry here; search and
  live-matching both derive from this array automatically, nothing else
  to update.
- `currentLineWords()` — pulls the words out of the editor's current line,
  from line start up to the cursor only (not past it) — this is
  deliberately "what the user has typed so far," not the whole line, so
  content sitting after the cursor can't skew matching.
- `scoreTemplate()` — ranks one template against those words: the *last*
  word gets 5x the weight of earlier words, and a match in the template's
  `name` counts 3x a match merely somewhere in its `sql` body. This is
  the whole "type alter or rank and it surfaces the right templates,
  weighted toward what you just typed" behavior — verified with a
  standalone Node script that the top result reorders correctly when the
  same words appear in a different order (i.e. the ranking genuinely
  tracks *last* word, not just word presence).
- `renderTemplateList()` — the single render path for the sidebar list,
  branching on whether the search box has text: non-empty means an
  explicit plain-substring search across all 125 (capped at
  `MAX_SEARCH_MATCHES`); empty means the live `currentLineWords()` +
  `scoreTemplate()` ranking (capped at `MAX_LIVE_MATCHES`, kept short on
  purpose — a long re-ranked list every keystroke would defeat the "need
  speed" point of this feature). Called both from the search box's
  `input` listener and from the editor's own `updateListener` (see above)
  on every doc change *and* every selection change, so moving the cursor
  to a different line without typing also re-targets the suggestions.
- `currentLineLastWordSpan()` / `insertTemplate()` — in **live mode**
  (search box empty), picking a template replaces the exact word that
  triggered the match — typing "begin" and clicking the BEGIN/EXCEPTION
  template replaces "begin" itself, it doesn't leave "begin" sitting there
  with the template pasted in below it. This was a real reported bug: the
  first version always inserted at the bare cursor position regardless of
  mode, so the trigger word never got consumed and a stray blank line
  showed up from the same-line padding logic. `currentLineLastWordSpan()`
  finds the `[from, to)` span of the word ending exactly at the cursor (not
  the whole line — trailing whitespace after the word means "you've moved
  on," so it returns `null` and `insertTemplate()` falls back to a plain
  insert-at-cursor instead of replacing something stale). In **explicit
  search mode** (search box has text), there's no trigger word tied to the
  editor, so it keeps the original plain-insert behavior. Verified against
  four cases with a real `EditorState` before shipping: typed word in an
  empty doc, typed word on its own line after existing content, trailing
  space after the word (must NOT replace), and explicit search mode (must
  NOT replace, unaffected by this change).
  `isAtLineStart()`/`isAtLineEnd()` decide whether to add that blank-line
  padding — a **second** real reported bug: the first version checked only
  the single character immediately before/after the replaced span, so a
  word preceded by pure indentation (`"      alter"`, or `"raise"` indented
  inside a procedure body) had a *space* as that character, which counted
  as "real content" and wrongly inserted a blank-line gap, pushing the
  template onto new unindented lines instead of continuing right after the
  existing indentation. The fix checks whether everything from the actual
  line start up to the insertion point is whitespace-only (not just one
  character), so indentation before the replaced word doesn't count as
  "not a boundary." Verified with a real `EditorState` against exactly the
  reported cases (6-space-indented `alter`, `raise` indented inside a
  `BEGIN...END` body) plus a regression check that mid-line insertion after
  real content (`"SELECT 1; begin"`) still gets padded correctly. Note
  this does **not** re-indent a multi-line template's own internal lines
  to match the ambient indentation — only the first line inherits it
  naturally by starting at that position; deeper reindentation was out of
  scope for this fix.
  Placeholders in a template are real Tab-navigable snippet fields (see
  `PLACEHOLDER_TOKENS` / `toSnippetTemplate()` right above `insertTemplate()`
  — not plain text the user has to manually find-and-replace, VS Code-style
  tab-stops via CodeMirror's own `@codemirror/autocomplete` `snippet()`.

  **`PLACEHOLDER_TOKENS`** is a hand-curated whitelist Set of the exact
  generic placeholder identifiers used across `TEMPLATES` (`table_name`,
  `column_name`, `function_name`, `param_1`, …) — deliberately a whitelist,
  not "any lowercase snake_case word." Most templates also use realistic
  illustrative names as part of the example itself (`orders`, `customers`,
  `customer_id`, `now()`, `jsonb_build_object`, table aliases like `o`/`c`)
  that are NOT meant to be tabbed through and replaced — wrapping those too
  would turn a two-decision template into a dozen-field slog. The
  whitelist was built by extracting and frequency-ranking every distinct
  token across all 125 templates and manually separating "generic slot"
  from "illustrative content." **Adding a new template**: if it uses a
  genuinely generic placeholder not already in the list, add that exact
  token to `PLACEHOLDER_TOKENS` — otherwise it just inserts as plain text
  (safe default, not a broken state).

  **`toSnippetTemplate()`** does a single word-boundary regex pass, wrapping
  each whitelisted token occurrence as `${token}` and leaving everything
  else untouched, then appends a trailing `${}` (CodeMirror's "final
  cursor position after tabbing through everything" marker, same role as
  VS Code's `$0`). Repeated occurrences of the same token within one
  template automatically become **linked fields** — editing one instance
  updates all of them — handled entirely by CodeMirror's own name-based
  field matching, not by this function. Word-boundary matching means
  `table_name` can never collide with `table_name` as a substring of a
  longer identifier like `idx_table_name_column` (underscore is a `\w`
  character, so there's no boundary between them) — both are separate,
  independently-whitelisted whole tokens.

  A template with **zero** whitelisted tokens still works correctly: the
  only field left is the trailing `${}`, which CodeMirror's `snippet()`
  recognizes as "no real fields" (its internal field-numbering treats the
  sole empty-name marker as field 0, and snippet/tab-stop mode only
  activates when at least one field has index >0) and falls back to a
  plain insert — verified against a real `EditorState`, not assumed, so no
  `if (hasPlaceholders)` branch was needed in `insertTemplate()` itself.

  **`insertTemplate()`** builds the snippet text (placeholder wrapping +
  the existing line-boundary padding logic above, unchanged) and calls
  `snippet(body)(view, null, from, to)` — the function `snippet()` returns
  does its *own* `view.dispatch()` internally (changes, selecting the
  first field, `scrollIntoView`), including auto-installing the Tab/
  Shift-Tab field-navigation keymap and Escape-to-clear on first use via
  CodeMirror's `appendConfig` mechanism — **no extra extensions needed in
  `view`'s own config** for snippet fields to work; this was verified
  (not assumed) by checking `@codemirror/autocomplete`'s actual source
  before relying on it.

  **Verified before shipping**, against the real `@codemirror/autocomplete`
  package (not the plain-text version's behavior): ran `toSnippetTemplate()`
  over all 125 templates, instantiated each via the real `snippet()`
  function against a real `EditorState`, confirmed the resulting document
  has no stray `${`/`#{` left over, and walked every field chain via
  `nextSnippetField()`/`hasNextSnippetField()` to confirm each one
  terminates cleanly (102 of 125 templates ended up with at least one real
  navigable field; the other 23 are illustrative-pattern templates with no
  whitelisted placeholder — e.g. "Create Table With Foreign Key" — and
  correctly fall back to a plain insert per the zero-token case above).
- **The header's old "🧩 Templates" nav button was removed** at the
  owner's explicit request — the Templates sidebar panel it used to open
  (`.open = true`, scroll into view, focus search) was NOT removed and is
  still always visible, so losing the button just means one less shortcut
  to reach a panel that was already always there. **`Ctrl+K` still does
  the exact same jump-and-focus the button used to do** (`document`-level
  `keydown` listener near the bottom of the script, `preventDefault()`s
  the browser's own Ctrl+K first) — that binding was NOT part of what was
  asked to be removed, don't remove it too without being asked.
- **Buffer tabs** (`#bufferTabs`, above the editor toolbar) — replaced the
  old single `sql_studio_query` localStorage key with an array under
  `sql_studio_buffers` (`[{id, name, query}, ...]`) plus
  `sql_studio_active_buffer` for which one is open. `loadBuffers()`
  migrates an existing user's old single saved query into buffer #1 on
  first run after this shipped — **verified** with a standalone Node test
  covering fresh install, legacy-key migration, buffers-already-exist, and
  corrupted-JSON-falls-back-to-migration, so don't remove that migration
  path without re-checking those cases don't regress.
  - `switchBuffer()`/`addBuffer()`/`closeBuffer()`/`renameBuffer()` all
    call `renderBufferTabs()` and, when the visible doc changes,
    `updateStats()` via `loadBufferIntoEditor()` — if you add a new
    per-buffer UI element later, wire it into `loadBufferIntoEditor()` so
    buffer switches keep it in sync too.
  - At least one buffer always stays open — `closeBuffer()` is a no-op
    when `buffers.length <= 1`.
  - Renaming/naming a new buffer uses a plain `prompt()`, not a custom
    dialog — deliberate scope call to avoid new modal UI for a rare action.
- **Keyboard shortcuts**: `Ctrl/Cmd+Enter` runs `formatQuery()`,
  `Ctrl/Cmd+Shift+Enter` runs `runQuery()` — both wired as a single
  CodeMirror `keymap.of([...])` extension (needs its own import, `keymap`
  from `@codemirror/view@^6.0.0` — same version-*range* import pattern as
  `@codemirror/state`, verified the same way, see the CDN-dedup entry
  below) so neither fires unless focus is in the editor, not e.g. the
  schema textarea or a connection field. Run deliberately does NOT reuse
  `Ctrl/Cmd+Enter` — that's Format's established binding, reusing it for a
  second, destructive-capable action risked a costly muscle-memory
  mistake. `Ctrl/Cmd+K` (global, `document`-level `keydown` listener, see
  above) focuses template search — unaffected by the header's "🧩
  Templates" nav button being removed, since Ctrl+K was always a separate
  binding, not the button's click handler.
- **Auto-format on paste** (`#chkAutoFormat`, persisted under
  `sql_studio_autoformat_on_paste`) — wired via
  `EditorView.domEventHandlers({ paste: ... })` (a static method on the
  already-imported `EditorView`, not a separate import). The paste event
  fires *before* CodeMirror has actually inserted the pasted text into the
  document, so the handler defers with `setTimeout(fn, 0)` before calling
  `formatQuery()` — calling it synchronously inside the paste handler
  would format the *old* doc, missing what was just pasted.
- **Ctrl+F find/replace** — functionally this is 100% stock CodeMirror
  (`@codemirror/search`'s `search()` extension + `searchKeymap`, already
  bundled into `basicSetup`); nothing custom was built for the actual
  find/replace logic. What *is* custom: `search({ top: true })` in `view`'s
  extension list, plus the `#editor .cm-panel.cm-search` CSS block (and its
  matching `.cm-textfield`/`.cm-button`/`label`/`button[name="close"]`
  sub-rules) that turns the library's default full-width bottom bar into a
  floating top-right box, VS Code-style. Positioning is `position:
  absolute` anchored to `#editor` (which needs `position: relative` —
  already set on `.cm-editor`), not just `top: true`'s own top/bottom
  panel placement, since a floating overlay (rather than a bar that pushes
  code down) was the actual ask. The DOM structure (`input.cm-textfield`,
  `button.cm-button`, plain `<label>` checkboxes, a `<br>` between the
  search row and the replace row, `button[name="close"]`) was confirmed by
  reading `@codemirror/search`'s actual source, not guessed — if this ever
  needs re-touching after a version bump, re-check that structure first
  rather than assuming today's class names still apply.

### SSH tunnel + Vault (connect without retyping credentials)

- **SSH tunnel**: the Connection panel's "Use SSH tunnel" checkbox reveals
  SSH host/port/username + a password-or-private-key choice.
  `server.py`'s `ConnectRequest.ssh_tunnel` becomes a
  `core.postgres_conn.SSHTunnelConfig`, passed straight through to
  `db_engine.connect(..., ssh_tunnel=...)` → `_POOL.connect(...)`, which
  opens the tunnel first (`core.postgres_conn.open_ssh_tunnel()`) and
  connects through its local forwarded port — see
  `core/pooled_postgres.py`'s own docs for the tunnel-lifecycle details
  (tied to `disconnect()`, same as the pool itself). `status()`'s
  `via_ssh_tunnel` field drives the "(via SSH tunnel)" suffix in the
  connected-status text. **Verified against a real, isolated setup**: a
  throwaway Postgres container reachable ONLY from inside a throwaway SSH
  container's own Docker network (confirmed unreachable directly from the
  toolbox container first), connected successfully through the tunnel
  with both password and private-key SSH auth, and confirmed the query
  actually returned real data — not a no-op tunnel.
- **Vault**: "Save this connection" (`POST /tools/vault/secrets`,
  `kind: "postgres_connection"`) and "Load saved connection"
  (`GET /tools/vault/secrets?kind=...` + `GET /tools/vault/secrets/{id}/reveal`)
  call the Vault tool's endpoints **directly from the frontend** — same
  same-origin pattern schema-map's Compare feature already uses to call
  DataDiff Pro's endpoint (see `schema-map/CLAUDE.md` Phase D), not a
  proxy through this tool's own backend. The saved JSON blob is
  `{host, port, database, username, password, ssh_tunnel}` —
  `ssh_tunnel` is `null` for a plain connection, or the same shape the
  Connection panel's SSH fields produce. This is a genuinely separate,
  explicit action from the ordinary connect flow — saving to the vault
  does NOT change the existing "password never persisted in
  localStorage" rule for a connection you don't explicitly save. See
  `vault/CLAUDE.md` for the vault's own trust model (no master
  password, by deliberate choice — encrypted at rest, not from anyone
  with access to this running container).
- **"Export FULL result to Vault" (`btnExportVault` / `POST
  /export/vault`) is a genuinely different operation from Run, not a
  mode of it.** It exists for one real case: "I ran a transforming query
  against Postgres, now I want to feed the real result into another
  tool (e.g. DataDiff Pro, via the orchestrator's `vault_dataset`
  source)" — and Run's `LIMIT 500` cap exists specifically so that case
  doesn't apply to ordinary Run. `db_engine.export_to_file()` deliberately
  does NOT use `query_guard.classify()`'s `executable_sql` (the
  LIMIT-wrapped version) — it re-validates with `split_statements()` +
  `classify()` (exactly one statement, not destructive, must return
  rows) and then runs the ORIGINAL statement text, unwrapped, via a
  **server-side (named) psycopg cursor** (`conn.cursor(name=...)`,
  `fetchmany(EXPORT_BATCH_SIZE)` in a loop) instead of `execute()`'s
  plain `cur.fetchall()` — bounded memory regardless of row count, same
  reasoning duck-lab's own DuckDB `COPY TO` already has. The existing
  pool-level `statement_timeout` still applies (it's part of the
  conninfo, not something Run-specific), so a runaway export still gets
  cut off the same way a runaway Run would. **Verified against a real
  1200-row table** (well over the 500 cap): ordinary Run returned
  exactly 500 rows with `capped: true`; "Export FULL result to Vault" on
  the identical query saved exactly 1200 — the one thing that would have
  silently defeated the entire point of this feature if missed. Also
  verified the destructive-statement refusal fires correctly (a `DELETE`
  is rejected before anything runs, not exported).

### Live database connection (Run)

- **One global connection, not a per-cookie session dict.** df-studio keys
  its state (`engine.SESSIONS`) per browser-tab cookie because each tab
  legitimately owns independent data. SQL Studio's live connection is
  different on purpose: the owner asked for "a single database at a time"
  with "a pool of 3 connections" — a global toggle, not N independent
  per-tab resources. Keying this the df-studio way would let every open
  tab silently open its own 3-connection pool (3 tabs = up to 9 live
  connections against the target database), which breaks the "pool of 3"
  requirement outright. `db_engine._POOL` (a `PooledPostgresConnection`,
  see `core/pooled_postgres.py`) holds a single optional connection state
  internally (`_POOL.state`); `GET /status` reports the same answer to
  every tab —
  that's correct behavior for "one database at a time," not a bug to fix
  by adding per-tab state.
- **The idle reaper is started lazily, not via FastAPI `lifespan=`.**
  `main.py` mounts every tool's app with `app.mount(...)` (an in-process
  ASGI mount) — Starlette does not forward lifespan startup/shutdown
  events into mounted sub-apps, so a `lifespan` handler defined on
  `sql_studio.server.app` would silently never fire under the real
  toolbox process. `db_engine._ensure_reaper_started()` is called instead
  from `connect()` itself, the first time a connection actually succeeds,
  guarded so it only starts once per process. A graceful shutdown closing
  the pool cleanly is therefore *not* guaranteed the way df-studio's
  "in-memory only, a restart drops state" gap is already accepted —
  document this as the same kind of accepted gap, not a promise this code
  currently keeps. **Idle threshold is 20 minutes**
  (passed as `idle_timeout_seconds=20*60` to `PooledPostgresConnection`
  in `db_engine.py`, lowered from an initial 30 — the owner's own call
  on the leaked-connection-risk/annoying-re-login tradeoff, not a
  default worth second-guessing without being asked).
- **The connection already survives an ordinary browser refresh with zero
  extra code** — `_POOL.state` lives in server-process memory, not in any
  per-browser session/cookie, so `GET /status` (what `loadInitialStatus()`
  calls on every page load) reports the real live connection regardless
  of how many times the page has been reloaded. The only things that
  actually drop it: the 20-minute idle reaper above, an explicit
  Disconnect click, or the **server process itself restarting** — which,
  during active development, happens on every `docker-compose up --build`
  used to ship a code change, and can look indistinguishable from "it
  drops on refresh" if a rebuild and a refresh happen close together.
  Verified directly: connected via `/connect`, then polled `/status`
  repeatedly with nothing else touched — stayed `connected: true` across
  every poll, exactly what a real refresh does client-side. Don't "fix"
  refresh-survival by adding session storage, cookies, or client-side
  reconnect logic — there is nothing broken here to fix.
- **The 500-row cap is a `LIMIT`-wrap, not a cost limiter — `statement_timeout`
  is what bounds cost.** `query_guard.classify()` wraps a row-returning
  statement as `SELECT * FROM (<statement>) AS _sq LIMIT 500` (or a
  `WITH _dml AS (<statement>) SELECT * FROM _dml LIMIT 500` for
  `INSERT`/`UPDATE`/`DELETE ... RETURNING`). This guarantees Postgres
  never hands back more than 500 rows — but for a `GROUP BY`/aggregate/
  window query over a huge table, Postgres generally still has to fully
  compute the aggregation before the outer `LIMIT` trims the output; the
  cap bounds what comes back over the wire, not how much work the
  database does to get there. That's the actual gap `db_engine.py`'s
  `STATEMENT_TIMEOUT_MS` (15s, set via `options=-c
  statement_timeout=...` in the pool's conninfo — applies to every
  statement on every connection the pool ever opens) closes: a query that
  would otherwise run indefinitely gets cancelled and surfaced as a clean
  error instead of hanging one of the pool's 3 connections forever. Two
  independent controls, don't conflate them — the row cap bounds output
  size, the timeout bounds runtime.
- **For `DELETE ... RETURNING`, the row cap is a display control, not a
  blast-radius limit.** The outer `LIMIT 500` only caps what's echoed back
  to the browser — it has no bearing on how many rows the inner `DELETE`
  actually deletes. The destructive-statement confirmation gate
  (`is_destructive`) is the real safety control for `DELETE`/`DROP`/
  `TRUNCATE`/`ALTER`; the row cap is unrelated to it.
- **Two independent copies of the same tokenizer/classifier, kept in sync
  by hand.** `tokenizePlpgsqlBody()` in `ui/index.html` and `tokenize()` in
  `query_guard.py` must stay behaviorally identical (string/comment/
  dollar-quote-aware segmentation), and so must
  `splitTopLevelStatements()`/`isOnlyCommentsOrWhitespace()` in
  `ui/index.html` vs. `split_statements()`/`_is_only_comments_or_whitespace()`
  in `query_guard.py`. The JS copy exists purely for a zero-round-trip UX
  win (the destructive-confirm dialog appears instantly on Run click,
  before any network call) — it is **never** the actual security decision.
  `query_guard.prepare()` on the server re-derives everything from
  scratch and is what actually gates execution; a client claiming
  `confirmed: true` for a statement it never classified as destructive
  gets no special treatment. If you change the splitting/classification
  rules, change both files and re-run the same test cases against each
  (see the comment-only-trailing-chunk fix — `"SELECT 1; -- comment"` must
  count as **one** statement in both implementations, not two).
- **Export reads a cached result, it never re-runs the SQL.**
  `db_engine._last_result` (a module-level variable in `db_engine.py`
  itself, deliberately NOT part of the shared `PooledPostgresConnection`
  — it's SQL Studio's own concern, not a generic pool behavior) is set
  on every successful *rows*-shaped `/query` and cleared on every
  non-rows one AND on disconnect (`db_engine.disconnect()` clears it
  explicitly before calling `_POOL.disconnect()` — this matters: before
  the shared-pool refactor, clearing `STATE` on disconnect implicitly
  cleared `last_result` too; now that they're two separate things,
  disconnect has to clear both on purpose or a stale cached result
  could outlive the connection it came from); `/export/csv` and
  `/export/json` just serialize whatever's cached there. This is
  deliberate, not a shortcut: re-running the SQL on export would silently
  double-execute a `DELETE`/`UPDATE` a second time, and would re-trigger
  the confirmation flow for no reason. If you ever "simplify" export back
  into taking a `sql` parameter and re-querying, you've reintroduced that
  bug.
- **The password is never persisted anywhere** — not `localStorage`, not a
  cookie, not on disk, not in a server-side log (see
  `core.postgres_conn.scrub_password()` — shared with schema-map now,
  same defense-in-depth, and verify it against the actually-installed
  `psycopg` version before trusting it blindly — see the next bullet).
  It lives only inside the live `ConnectionPool`'s own connection
  objects for as long as `_POOL.state` exists. Reconnecting after a
  disconnect (explicit or reaper-triggered) always means re-typing it —
  that's the intended forcing function, not friction to remove.
- **Validating credentials means a direct, unpooled `psycopg.connect()`
  first — NOT just opening the `ConnectionPool` and hoping a bad
  host/port/db/password surfaces on its own.** Two real bugs found this
  way, not assumed from the `psycopg_pool` docs, both caught by actually
  connecting with a deliberately wrong password against a throwaway
  `postgres:16-alpine` container: (1) with `min_size=0`, `pool.open()`
  doesn't eagerly create any real connection — it only starts the pool's
  background worker — so a bad password wasn't caught until the first
  query ran; (2) even forcing a checkout via `pool.connection()`,
  `ConnectionPool` retries failed connection attempts in the background,
  and a timed-out checkout raises a generic `"couldn't get a connection
  after 10.00 sec"` instead of the real error, and takes the full 10s
  timeout to fail instead of failing immediately.
  `core.postgres_conn.verify_connection()` (shared with schema-map, called
  from `PooledPostgresConnection._connect_sync()` in `core/pooled_postgres.py`)
  validates with a plain `psycopg.connect(conninfo, connect_timeout=10)`
  + a trivial `SELECT 1` *before* constructing the pool — this raises the
  actual `OperationalError` (e.g. `"FATAL: password authentication failed
  for user ..."`) immediately, and the pool is only built once that
  succeeds. If you ever "simplify" this back to just `pool.open()`,
  you've reintroduced both bugs — in BOTH sql-studio and schema-map at
  once now, since they share this code.
- **`core.postgres_conn.scrub_password()`'s password-redaction regex is
  defense-in-depth, verified against the real thing, not just asserted
  safe.** Connected with a deliberately wrong password against a throwaway
  `postgres:16-alpine` container and inspected the actual error text
  psycopg/libpq raise (`"connection failed: connection to server at
  ..., port 5432 failed: FATAL: password authentication failed for user
  \"...\""`, and the equivalent for a nonexistent database) — confirmed
  the cleartext password is never embedded in that text, in the API
  response, or in the server's own stdout logs. `_scrub()` stays in place
  as defense-in-depth for a future psycopg version or a differently-
  shaped error string, not because this specific version was found to
  leak anything.
- **The Connection panel is collapsed by default and stays collapsed once
  connected** (`applyConnectionStatus()` in `ui/index.html`, toggling
  `#detConnection`'s `open` attribute and swapping `#connectionForm` for
  `#connectionStatusView`) — deliberate UX, not a bug to "fix" by leaving
  it expanded. Two distinct rules, don't conflate them: (1) on page load,
  a silent `GET /status` check must NOT force the panel open — only a
  human action should (a real bug: an earlier version force-opened it
  whenever disconnected, including on every page load, which is exactly
  what the owner flagged as "connection should not [be] shown default");
  (2) the instant `/connect` succeeds, it force-collapses to a compact
  status line regardless of whatever the previous `open` state was.
  `applyConnectionStatus(status, forceOpen)`'s second parameter is what
  encodes rule (1) — only `$("btnDisconnect")`'s click handler passes
  `true`, precisely so the form is right there to reconnect after an
  explicit disconnect, without every silent status poll doing the same.
- **Run is hard-restricted to exactly one statement.** `query_guard.
  prepare()` rejects anything that splits into more than one top-level
  statement (via the shared tokenizer's `;`-boundary detection) before any
  database round-trip — this bounds the `LIMIT`-wrap mechanism (only has
  well-defined semantics for one statement) and the destructive check
  (needs to apply to the one statement being run, not a batch). `COPY` is
  rejected outright for the same "doesn't fit a single query-string
  executor" reason — use `psql` for that. Neither is a temporary
  limitation waiting to be lifted casually; multi-statement/`COPY` support
  would need real per-statement UX (separate confirm dialogs, separate
  results), not a one-line change to the split check.
- **Run honors a text selection, pgAdmin/DataGrip-style** — `runQuery()`
  checks `view.state.selection.main` first; a non-empty selection runs
  `view.state.sliceDoc(selection.from, selection.to)` instead of the whole
  document, letting you execute one subquery or a single line out of a
  larger pasted script without touching the rest of the buffer. No
  selection falls back to the previous whole-document behavior, unchanged.
  This is a one-line change at the top of `runQuery()` — everything
  downstream (the one-statement check, `matchShowCommand()`, the
  destructive-keyword check, the confirm-dialog preview) already just
  operates on whatever `sqlText` turns out to be, so it covers the Run
  button, `Ctrl+Shift+Enter`, and the destructive-confirm flow all at
  once with no separate code paths to keep in sync. Verified
  `EditorState.sliceDoc()` against the real `@codemirror/state` package
  (not assumed from the type signature) before relying on it.
- **A `<dialog>`'s CSS must keep `display` scoped to `[open]`, or the
  dialog force-shows on every page load instead of only via
  `showModal()`.** A real bug, caught by the owner seeing it happen:
  `dialog#resultsDialog { ...; display: flex; }` — no `[open]` qualifier —
  has higher specificity (an ID selector) than the browser's own default
  `dialog:not([open]) { display: none; }` (a type selector + pseudo-class),
  so it won permanently, showing an empty "Results" panel inline in the
  page at all times instead of only after Run. Fixed by splitting it:
  sizing rules (`width`/`max-width`/`height`) stay unscoped since they're
  harmless either way, but `display: flex; flex-direction: column;` moved
  to `dialog#resultsDialog[open]`. If you add more dialog-specific CSS,
  keep anything touching `display` scoped to `[open]` the same way.

### Show commands

A `psql \d`-family equivalent, but plain-English phrases instead of
backslash syntax: type `show tables`, `show table orders definition`,
`show functions`, etc. in the editor and press Run — the app recognizes
the phrase and silently substitutes the real Postgres system-catalog SQL
before it's sent, so what actually executes is never what's typed. 32
commands total (see `SHOW_COMMANDS` in `ui/index.html`), covering tables/
columns, schemas, views, materialized views, indexes, constraints,
foreign/primary keys, functions, procedures, triggers, sequences, enum
types, roles, grants, table/database size, `pg_stat_activity`, `pg_locks`,
version, and extensions.

- **Purely client-side text substitution — zero backend changes.** Every
  command resolves to an ordinary read-only `SELECT` (or a `WITH ...
  SELECT` CTE chain for the harder ones), so it goes through the exact
  same `runQuery()` → `sendQuery()` → `POST /query` pipeline as any other
  query: same 500-row `LIMIT`-wrap, same server-side re-classification.
  `query_guard.py` never sees or knows about "show tables" text at all —
  by the time anything reaches the network, the browser has already
  replaced it with real SQL. This also means these commands are never
  destructive by construction (always `SELECT`/`WITH`), so
  `matchShowCommand()` is checked in `runQuery()` *before* the destructive
  keyword check and skips it entirely when it matches.
- **`SHOW_COMMANDS`** (in `ui/index.html`, just above the "Connection
  panel + Run" section) is the single source of truth — an array of
  `{ cat, name, template, desc, pattern, buildSql }`. `matchShowCommand()`
  linearly scans it (first match wins) against the one statement Run
  already extracted. **Array order matters for literal-phrase commands
  that share a prefix with a generic parameterized one** — `show table
  sizes` is listed before the generic `show table <name>` pattern, or
  "sizes" gets swallowed as if it were a table name being asked for its
  columns. Every parameterized pattern is strictly anchored (`^...$`), so
  `show table X` (no trailing text) and `show table X definition`
  (trailing " definition") never collide with each other regardless of
  order — ordering only matters for the literal-vs-generic case above.
- **Every mapped query was verified against a real Postgres before
  shipping** — this tool's own dev database (`sqlstudio-postgres` in
  `docker-compose.yml`), seeded with real tables, a view, a materialized
  view, a function, a trigger, an enum type, indexes, and constraints
  (FK/PK/CHECK), specifically so every command had something real to
  return. All 32 were run twice: once directly via `psql` while designing
  the SQL, and once more end-to-end through the actual `POST /query`
  HTTP endpoint (with the server's `LIMIT`-wrap applied on top) before
  being considered done — not assumed correct from writing the SQL alone.
- **Object lookups filter out system internals** (`pg_catalog`,
  `information_schema`, `pg_toast%`, `pg_temp%`) via the shared
  `SYS_SCHEMA_FILTER` JS constant — "widely used, easy to see" means user
  objects, not Postgres's own bookkeeping tables. A name match against
  more than one schema (rare) deterministically picks one (`ORDER BY
  schema name, LIMIT 1`) rather than erroring; this is a pragmatic default
  for a single-name lookup, not full schema-qualification support (no
  `show table myschema.orders definition` syntax).
- **`show table <name> definition` reconstructs `CREATE TABLE` by hand**
  — unlike views/functions/triggers, Postgres has no built-in
  `pg_get_tabledef()`. The query (a CTE chain: columns, then
  constraints via `pg_get_constraintdef()`, then any non-PK indexes via
  `pg_get_indexdef()` appended as trailing `CREATE INDEX` statements) was
  the one genuinely tricky piece here and needed real iteration against a
  table with a PK, an FK, a CHECK constraint, and a non-constraint index
  all at once before it was trusted — see the verification note above,
  this is the specific query that motivated building that full fixture
  set rather than testing against a bare `customers`/`orders` pair alone.
- **Definitions are looked up by bare name, not `::regclass`/`::regproc`
  casts.** An earlier draft used `'name'::regclass` / `'name'::regproc`,
  which resolves through the connection's current `search_path` — fine
  for the common "everything in `public`" case, but silently wrong (or a
  resolution error) for anything outside `search_path`. Rewritten to look
  up the object's oid explicitly via a `pg_class`/`pg_proc`/`pg_trigger`
  join filtered by `SYS_SCHEMA_FILTER`, independent of `search_path`.
- **These templates are folded into the same `TEMPLATES` array** Templates
  already uses (see `SHOW_COMMANDS.forEach((cmd) => TEMPLATES.push(...))`
  right after `TEMPLATES` is declared) — typing "show" in the editor
  surfaces them through the exact same live-filter/search/Tab-stop-field
  insertion path as any other template, zero changes needed to
  `renderTemplateList()`/`insertTemplate()`. Parameter placeholders in
  each command's `template` text (`table_name`, `function_name`,
  `trigger_name`, `view_name`, `procedure_name`, `schema_name`) are all
  already in `PLACEHOLDER_TOKENS` from the original 125 templates, so
  they become real Tab-stop fields automatically — no whitelist changes
  needed either.
- **The "?" button (`#btnShowHelp` / `#helpDialog`) is a cheatsheet, not a
  second command list** — `buildHelpDialog()` renders directly from
  `SHOW_COMMANDS`, so it can never drift out of sync with what Run
  actually recognizes. **Clicking a row does one of two different things,
  and which one depends on whether the command needs a name filled in:**
  a no-parameter command (`show tables`, `show materialized views`, ...)
  runs **immediately** — closes the dialog and calls `sendQuery(cmd.
  buildSql(), false, cmd.name)` directly, the exact same execution path
  Run itself uses, landing straight in the results dialog. A parameterized
  command (`show table <name> definition`, ...) still falls back to
  `insertTemplate(cmd.template)` — there's no name to run against yet, so
  the best available action is inserting it as a snippet with the
  placeholder ready to Tab into and fill in. **This was a real reported
  friction point, not a preemptive nicety**: the owner tried to refresh a
  materialized view without knowing its name, clicked "Show Materialized
  Views" expecting to just see the list, and instead got template text
  pasted into the editor that still needed a manual Run press — exactly
  backwards from what a no-parameter command should do. Each row shows
  a small right-aligned tag ("▶ run now" / "✎ fill in & run") so which
  behavior to expect is visible before clicking, not a surprise either
  way. The needs-a-parameter check
  (`cmd.pattern.source.includes("(\\S+)")`) relies on every parameterized
  `SHOW_COMMANDS` pattern being written with exactly one `(\S+)` capture
  group, which is already true for all 12 of them — if you ever add a
  parameterized command using some other capture syntax, update this
  check too, or it'll be silently treated as a no-parameter, run-now
  command with nothing to substitute into its `buildSql()`. **Falls back
  to inserting even for a no-parameter command when nothing is
  connected** — running isn't possible yet, so inserting the text is the
  most useful thing left to do, not a dead click. **Groups by category via
  a `Map`, not by "does
  this row's `cat` differ from the previous row's."** `SHOW_COMMANDS`
  itself is ordered for *matching precedence* (literal-phrase commands
  before the generic parameterized patterns they'd otherwise collide
  with — see the array-order bullet above), not grouped by category — a
  category with both kinds (Tables, Views, Functions & Procedures,
  Triggers, ...) has its literal entries in the first half of the array
  and its parameterized ones in the second half, with many other
  categories' entries in between. The original version emitted a new
  category header every time `cmd.cat` changed from the previous
  iteration, which meant every such category printed as **two separate,
  non-adjacent sections** in the dialog — a real bug the owner spotted
  ("2 show tables") within minutes of trying it, not a hypothetical.
  Fixed by grouping fully into a `Map` first (`cat -> [cmds]`, keys in
  first-seen order) and rendering each category's complete list as one
  contiguous block — `SHOW_COMMANDS`'s own array order is untouched,
  since changing it to "fix" the display would break matching precedence
  instead.
- **The results dialog title reflects which command ran**, not a generic
  "Results" — `renderResults(data, label)`'s second parameter is the
  matched command's `name` (e.g. "Show Tables"), passed through from
  `runQuery()` → `sendQuery()`. Ordinary Run (no show command matched)
  passes `null` and keeps the generic title.
- **A single-row, single-column, multi-line text result renders as
  preformatted text (`<pre class="results-definition">`), not the normal
  results `<table>`.** A real reported bug: `table.results-table`'s CSS
  uses `white-space: nowrap` (needed so ordinary short-value rows don't
  blow out the table layout), which silently collapses embedded newlines
  — so `show table X definition`/`show function X definition`/etc., all
  of which return exactly one row and one text column full of real `\n`
  characters, rendered as one long unreadable line despite the DDL
  itself being correctly formatted server-side. `renderResults()` now
  checks the result's *shape* (`data.rows.length === 1 && data.columns.
  length === 1`, and the one cell is a string containing `\n`) before
  building the table — not the command name, so this also helps an
  ordinary query that happens to return one long text column, not just
  the `show ... definition` family. `.results-definition` uses
  `white-space: pre-wrap` (preserves the DDL's real indentation/line
  breaks, but still wraps an unusually long single line instead of
  forcing horizontal scroll) rather than plain `pre` (`white-space: pre`
  would preserve formatting perfectly but never wrap, forcing horizontal
  scroll for something like a long `CHECK` constraint line).

### Multi-database support (Postgres, SQL Server, Oracle)

Originally Postgres-only. A "Database type" selector in the Connection
panel now lets Run/Connect/Export/Fetch Schema/show-commands all work
against SQL Server and Oracle too — built explicitly as a reusable base
(`core/db/`'s `Dialect` abstraction, see root `CLAUDE.md`'s "Shared
connectors" section), not a one-off bolted onto this tool alone, though
this is still the only tool that actually uses it. Schema Map stays
Postgres-only and untouched.

- **One `Dialect` per database** (`core/db/dialect_postgres.py`/
  `dialect_mssql.py`/`dialect_oracle.py`, looked up by
  `core/db/registry.py`'s `get_dialect(db_type)`) is what every
  dialect-specific piece of behavior hides behind — conninfo building,
  pool open/checkout/close, the row-cap SQL template, streaming export
  cursors, and the schema-fetch query. `sql-studio/db_engine.py`'s
  `_POOL` (a `core.pooled_db.PooledDbConnection`) has no fixed dialect
  of its own — `connect(db_type=...)` resolves one fresh each call, so
  reconnecting under a different `db_type` just works, same "one
  connection at a time" model as before.
- **Drivers: `python-tds` (SQL Server) and `python-oracledb` in thin
  mode (Oracle)** — both pure-Python, no ODBC/FreeTDS/Oracle Instant
  Client install needed in the one shared Dockerfile, chosen
  specifically to avoid repeating this repo's documented `duckdb`
  wheel-availability pain. `pytds` turned out to need no `pyodbc`
  fallback at all — confirmed directly against a real throwaway
  `mssql/server` container: immediate failure on a bad password (no
  hang), `fetchmany()` streaming without a named server-side cursor,
  and a genuine working per-statement timeout via its own `timeout=`
  kwarg (cut a deliberate 5-second query off at ~1 second).
- **Row-cap wrapping is a different SQL template per dialect, found the
  hard way for SQL Server specifically.** Postgres (unchanged):
  `SELECT * FROM (<sql>) AS _sq LIMIT {n}`. Oracle (12c+):
  `SELECT * FROM (<sql>) FETCH FIRST {n} ROWS ONLY` — confirmed to work
  even when `<sql>` itself is a multi-CTE `WITH ...` chain. **SQL
  Server's first implementation used the same "wrap in TOP + a derived
  table" shape and was wrong in two different ways, both found only by
  running it against a real engine, not by reasoning about T-SQL
  syntax**: (1) a trailing `ORDER BY` inside a derived table is illegal
  in T-SQL unless that inner query itself has `TOP`/`OFFSET`/`FOR XML`
  — real error, not hypothetical (`"The ORDER BY clause is invalid in
  views, inline functions, derived tables..."`); (2) wrapping a
  `WITH ...` (CTE) statement the same way is ALSO illegal
  (`"Incorrect syntax near the keyword 'WITH'"`) — which matters a lot
  here specifically because `dialect_mssql.py`'s own `schema_fetch_query()`
  always produces a multi-CTE statement, so the original wrap broke
  Fetch Schema outright for this dialect. Rewritten entirely: SQL Server
  now appends a trailing `OFFSET 0 ROWS FETCH NEXT {n} ROWS ONLY`
  directly onto the original statement instead of wrapping it in
  anything — if the statement already ends in a top-level `ORDER BY`
  (detected by `core/db/dialect_mssql.py`'s own small string/comment/
  paren-depth-aware scanner, `_has_trailing_order_by()` — NOT a reuse of
  this file's own tokenizer, since `core/` doesn't import from a tool
  folder), the suffix is appended right after it; otherwise a dummy
  `ORDER BY (SELECT NULL)` is inserted first, since T-SQL's `FETCH`
  clause requires an `ORDER BY` to be legal at all. This sidesteps both
  bugs at once — no derived table, no CTE-nesting problem, no
  TOP-must-come-after-DISTINCT ordering problem either. Verified against
  a real SQL Server: a plain `SELECT`, a `SELECT ... ORDER BY`, and a
  multi-CTE `WITH ...` chain all cap correctly at exactly `n` rows.
- **Row-returning DML (`INSERT`/`UPDATE`/`DELETE ... RETURNING`, SQL
  Server's `OUTPUT`, Oracle's `RETURNING ... INTO`) has no safe cap for
  SQL Server or Oracle, confirmed empirically, not assumed.** Wrapping
  either in the same SELECT-cap pattern fails outright against a real
  engine (SQL Server: `"Incorrect syntax near 'OUTPUT'"`; Oracle:
  `"ORA-00903: invalid table name"` — `RETURNING INTO` is
  bind-variable-based, never a real result set, so it can't sit inside
  a `FROM` clause at all). `wrap_dml_returning_cap()` returns `None` for
  both dialects, and `query_guard.prepare()` rejects that case with a
  clear error ("Row-returning UPDATE isn't supported through Run for
  oracle yet...") rather than running it uncapped or guessing at a
  rewrite. This does NOT affect "Export FULL result to Vault" — that
  path never reads `executable_sql` at all, it always runs the
  original, unwrapped statement (see that section above), so exporting
  a row-returning DML statement for these two dialects still works.
- **Oracle CLOB columns need an explicit decode — FastAPI's
  `JSONResponse` can't serialize an `oracledb.LOB` object, and this
  isn't hypothetical: `dialect_oracle.py`'s own `schema_fetch_query()`
  returns one.** `db_engine.py`'s `_decode_lob_cell()` detects any
  value with a `.read` attribute (driver-agnostic — Postgres/SQL Server
  rows never have this) and reads it into a plain string before it's
  ever put in a response, in both `_execute_sync` (ordinary Run) and
  `_export_sync` (the uncapped Vault export). Without this, ANY query
  touching a CLOB/BLOB column against Oracle would 500, not just the
  schema-fetch one.
- **Column names must be read by index (`d[0]`), never `.name`** — a
  real portability gap, not a style preference: `psycopg`'s cursor
  `description` entries support `.name` as a convenience, but `pytds`'s
  are plain tuples and don't (confirmed directly against a real SQL
  Server: `'tuple' object has no attribute 'name'`). `[0]` is the one
  access pattern the DB-API spec actually guarantees across all three
  drivers.
- **Schema-fetch's result shape differs by dialect, and the frontend
  has to handle both.** Postgres's `json_object_agg` comes back as an
  already-parsed nested object (psycopg auto-decodes `json`/`jsonb`
  columns), round-tripping through this response's own JSON encoding
  with zero extra work. SQL Server (`STRING_AGG` + manual string
  concatenation — no built-in "aggregate into one JSON object"
  function available on this image) and Oracle (`JSON_OBJECTAGG`, after
  the LOB-decode fix above) both come back as a plain STRING containing
  JSON text, needing an explicit `JSON.parse()` first.
  `ui/index.html`'s `btnFetchSchema` handler branches on
  `typeof cell === "string"` to cover both cases with one code path.
- **Oracle's `JSON_OBJECTAGG` defaults to a 4000-character `VARCHAR2`
  output and throws `ORA-40478` the moment a real schema's JSON exceeds
  that — found only by running it against real tables, not from reading
  Oracle's own docs.** Both the inner (per-table) and outer
  (whole-schema) aggregation in `dialect_oracle.py`'s
  `schema_fetch_query()` need `RETURNING CLOB` explicitly — a single
  wide table's own column list alone can exceed 4000 characters, so the
  inner one needs it too, not just the outer.
- **Oracle's default install ships several more built-in schemas than
  the obvious `SYS`/`SYSTEM`** — found by running the UNFILTERED schema
  list query against a real `gvenzl/oracle-free` container and seeing
  `APPQOSSYS`/`AUDSYS`/`DBSFWUSER`/`DBSNMP`/`DVSYS`/
  `GSMADMIN_INTERNAL`/`LBACSYS`/`VECSYS` show up as real owners of real
  tables. `_ORACLE_SYSTEM_SCHEMAS` in `core/db/dialect_oracle.py` and
  `ORACLE_SYSTEM_SCHEMAS` in `ui/index.html` are the same list, kept in
  sync by hand — if a newer Oracle version ships yet another one, it'll
  show up as a surprise "schema" in the Fetch Schema filter dropdown,
  not a crash; add it to both lists.
- **`ALL_TAB_PRIVS`'s schema-name column is `TABLE_SCHEMA`, not
  `OWNER`, on this Oracle version** — the "Show Grants" oracle
  show-command was written assuming `OWNER` (matching older Oracle
  documentation/training data) and failed with `ORA-00904` until
  checked directly against the real catalog's actual columns. Re-verify
  column names against the real engine rather than trusting recalled
  Oracle documentation, especially for less common `ALL_*`/`DBA_*`
  views — this project's own history already has one precedent for this
  exact mistake (see "Show commands" above, the `json_object_agg`/
  `jsonb_object_agg` bug).
- **Show-commands parity is deliberately NOT 32-for-32.** SQL Server and
  Oracle each get the ~11 highest-value commands (tables, table
  columns, table definition, functions/procedures, triggers, indexes,
  foreign keys, views, activity, grants, version) — tagged
  `dbTypes: ["mssql"]`/`["oracle"]` on their `SHOW_COMMANDS` entries.
  Entries with NO `dbTypes` field are implicitly Postgres-only (every
  one of the original 32 predates multi-database support and is
  entirely `pg_catalog`-based) — `commandAppliesToCurrentDbType()` is
  the one function both `matchShowCommand()` (Run) and
  `buildHelpDialog()` (the "?" cheatsheet) check before a command is
  allowed to match/show. ~20 of the original 32 (extensions, enum-type
  catalogs, several sequence/tablespace variants) have no clean 1:1
  concept in the other two databases at all and are staying
  Postgres-only for the foreseeable future — not a gap to "complete"
  without a real design discussion, since several of them genuinely
  don't translate.
- **The mssql/oracle show-command phrases deliberately reuse the EXACT
  same text as their Postgres equivalent** (`"show tables"` means the
  same thing no matter which database is connected) — which means
  `SHOW_COMMANDS.forEach((cmd) => TEMPLATES.push(...))` needed a
  dedup step (`seenShowTemplates`, a `Set` keyed on `cmd.template`) to
  avoid the Templates search panel showing 2-3 visually-identical
  "show tables" rows. Deduplicating is correct here, not just
  convenient — clicking any copy inserts byte-identical text, and
  `matchShowCommand()` already resolves to the right dialect's real SQL
  at Run time regardless of which copy was clicked.
- **`buildHelpDialog()` is now a rebuildable function, not a load-time
  IIFE** — called once on page load and again every time `connDbType`
  changes (from `applyDbTypeToForm()`), so the "?" cheatsheet always
  lists exactly the commands that apply to whichever database is
  currently selected, not whatever was selected when the page first
  loaded.
- **Verified with the same discipline as the original Postgres-only
  build — every new SQL template run against a real throwaway container
  (`mcr.microsoft.com/mssql/server`, `gvenzl/oracle-free`) before being
  trusted, not written from memory and assumed correct.** This is what
  caught every bug listed above; none of them were visible from reading
  the SQL alone.

### The introspection SQL also lives in `core/db/` now, not just `ui/index.html`

A second pass, after the owner explicitly asked "will this become the
base for what's next" and "is everything each database supports
actually shown." Each `Dialect` (`core/db/dialect_postgres.py`/
`dialect_mssql.py`/`dialect_oracle.py`) gained 11 methods —
`list_tables_sql()`, `table_columns_sql(table)`, `table_definition_sql(table)`,
`list_functions_sql()`, `list_triggers_sql()`, `list_indexes_sql()`,
`list_foreign_keys_sql()`, `list_views_sql()`, `activity_sql()`,
`grants_sql(table=None)`, `version_sql()` — each returning SQL TEXT
(same shape as `schema_fetch_query()`), ported verbatim from the
already-verified `SHOW_COMMANDS` entries (Postgres's included — those
existed only as JS before this pass). **The point**: before this,
these queries existed ONLY as JavaScript in this file — a future
headless tool (a multi-db Schema Map, a migration tool, anything
without a browser) had nothing to call. Now `core/db/` has a genuinely
symmetric introspection API across all three databases, not just a
connector. `ui/index.html`'s `SHOW_COMMANDS` keeps its own copy
unchanged in shape — same "two independent copies, kept in sync by
hand" convention already used for `schema_fetch_query` and the
tokenizer — this was additive, not a rewire of Run's execution path.

**A real, more severe bug found BY doing this verification pass, not
by the original build**: re-running `list_tables_sql()` against real
containers surfaced that Oracle's version returned **138,097 rows** —
every catalog/internal table in the entire instance, not just the
connected user's own tables, because none of the six "list everything"
queries (tables, functions, triggers, indexes, foreign keys, views)
had a system-schema exclusion filter at all, unlike `schema_fetch_query()`
(which already filtered via `_ORACLE_SYSTEM_SCHEMAS`). SQL Server had
the identical gap at a smaller scale (housekeeping tables mixed in
with real ones). Fixed by applying the SAME exclusion filter
(`_ORACLE_SYSTEM_SCHEMA_FILTER`/`_MSSQL_SYSTEM_SCHEMA_FILTER`, both
derived from the constants `schema_fetch_query()` already used) to all
six queries, **in both the new Python methods AND their pre-existing
JS twins** — the JS ones had exactly the same gap and are what SQL
Studio's UI actually runs, so fixing only the new Python copies would
have left the real bug live in the product. Verified by creating a
genuine non-system user+table on each real container (`TESTUSER`/
`testdb`, not `SYSTEM`/`master` — the original test accounts, which
are themselves excluded by the fix and would have silently shown zero
results) and confirming `list_tables_sql()`/`list_views_sql()`/
`list_foreign_keys_sql()`/`list_indexes_sql()` each correctly surface
the real table/view/FK/index while showing zero rows from any system
schema — Oracle's count dropped from 138,097 to exactly the 6 rows
belonging to the real test tables.

## Things that will bite you if you don't know them

- **CodeMirror 6 packages must resolve to one shared instance of
  `@codemirror/state`/`@codemirror/view` across all imports**, or you get a
  runtime error like "Unrecognized extension value" from duplicate module
  instances — this actually happened while building this tool (see
  history: the first draft pinned `@codemirror/state@6.7.6` via jsDelivr's
  `+esm`, while `codemirror@6.0.2`'s own bundle internally pulled in
  `@codemirror/state@6.5.2` — two different files, two different singleton
  registries). Imports now go through **esm.sh**, not jsDelivr, and the
  `@codemirror/state` import is written as `@codemirror/state@^6.0.0` (a
  version *range*, matching the exact range string baked into
  `codemirror@6.0.2`'s own published bundle) rather than a pinned patch
  version. esm.sh resolves a given range string to a shim file that
  re-exports from one canonical resolved version, and since our import and
  codemirror's internal import use the identical range string, they hit the
  identical shim URL and therefore the identical underlying module — this
  was verified by fetching and diffing the actual resolved `.mjs` URLs, not
  assumed. **Do not swap this back to a pinned exact version or to
  jsDelivr's `+esm`** without re-verifying this chain (fetch each package's
  shim with `curl`, confirm the `@codemirror/state`/`@codemirror/view`
  import lines inside `codemirror.mjs`, `autocomplete.mjs`, and
  `language.mjs` all resolve to the same final file). The `keymap` import
  (added for Ctrl+Enter) follows the identical rule — `@codemirror/view@^6.0.0`,
  not a pinned version — and was re-verified the same way (headless Node
  script building a real `EditorState` with `keymap.of(...)` +
  `EditorView.domEventHandlers(...)` included, confirming no
  "Unrecognized extension value" error) before shipping. `@codemirror/search`
  (added for the Ctrl+F panel) is the one exception that's pinned to an
  *exact* version (`@codemirror/search@6.7.2`, same style as
  `@codemirror/lang-sql`) rather than a range — safe here because its own
  internal `@codemirror/state`/`@codemirror/view` dependencies use
  *different* range strings than ours (`^6.37.0` for view, vs. our
  `^6.0.0`), and this was explicitly checked to still resolve to the exact
  same final `.mjs` files via esm.sh (both ranges are currently satisfied
  by the identical latest published version) before assuming it was safe —
  don't assume a different range string is automatically fine without
  re-checking this the same way if package versions ever get bumped. The
  `snippet` import (for Templates' tab-stop fields) uses
  `@codemirror/autocomplete@^6.0.0` — the *exact* same range string that
  `codemirror.mjs` and `lang-sql.mjs` already import internally for
  autocomplete (confirmed by reading both files' own import lines, not
  inferred), so this one needed no extra dedup verification beyond that
  direct match.
- **`sql-formatter` throws on genuinely unparseable SQL** — it does not
  best-effort format broken input. That's surfaced via the red error box
  below the editor (`showFormatError()`), not swallowed. Don't wrap it in a
  bare try/no-op.
- **The PL/pgSQL body formatter is deliberately regex/keyword-based, not a
  real parser — known limitations, by design, not oversights:**
  - Comparison operators inside `IF`/`WHILE` conditions aren't spaced out
    (`IF b>10000 THEN` stays as typed) — only DML lines get re-run through
    `sql-formatter`, not control-flow condition expressions.
  - A `--` comment immediately trailing a statement on the same source line
    moves to its own line in the output rather than staying inline —
    content is preserved, just not the exact line it was originally on.
  - A bare `FOR`/`CASE` appearing inside *plain SQL* rather than PL/pgSQL
    control flow (e.g. `SELECT ... FOR UPDATE`, or an inline `CASE WHEN`
    expression in a `SELECT` list) can be misdetected as a PL/pgSQL
    statement boundary and mis-indented. Rare in legacy procedure bodies in
    practice; fixing it properly needs real parsing, not worth the
    complexity for this tool's scope.
  - `RAISE EXCEPTION '...'` is explicitly guarded against being confused
    with the `EXCEPTION` block-marker of a `BEGIN...EXCEPTION...END`
    handler (`(?<!RAISE )\bEXCEPTION\b` in `insertStructuralBreaks()`) —
    this was a real bug caught during testing, not a hypothetical; if you
    add more RAISE variants or other statements containing "EXCEPTION",
    re-check this guard.
  - Verified against: the reported broken example (nested IF-via-ELSE,
    comments, `RAISE EXCEPTION`), a `FOR...LOOP`/`CASE...WHEN`/
    `EXCEPTION...WHEN` handler with inline comments, multiple
    `CREATE FUNCTION` statements pasted together, and a plain non-PL/pgSQL
    query (regression check — must be byte-for-byte what `sql-formatter`
    alone would have produced, since `reformatDollarQuotedBodies()` is a
    no-op when no `$$`/`$tag$` pair is found).
- **Schema JSON is parsed with `JSON.parse` inside a `try/catch` only —
  never `eval`.** It's pasted, untrusted-shaped text; treat it as data.
- **Format, Templates, and Schema autocomplete stay client-side,
  intentionally** — if you're tempted to route formatting, template
  insertion, or autocomplete through the new backend "since it exists now
  anyway," that's scope creep this tool doesn't need: those three features
  work fully offline today and adding a network round-trip to them would
  be a straight regression, not an improvement. The backend that does
  exist (`db_engine.py`/`query_guard.py`) is scoped to Run/Connect/Export/
  schema-fetch only — keep it that way unless the owner asks otherwise.
  See "Live database connection (Run)" above for everything specific to
  that backend.
- Mounted at `/tools/sql-studio/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way. The new `fetch("connect")`/`fetch("query")`/etc. calls in
  `ui/index.html` all use relative paths (no leading `/`), same repo-wide
  convention as every other tool, so they resolve correctly under the
  `/tools/sql-studio/` prefix.

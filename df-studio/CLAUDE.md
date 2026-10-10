# DataFrame Studio — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

Click-driven pandas: upload a CSV/JSON/XML/Parquet file, transform it
through a UI (rename/drop/add column, filter rows, sort, or a free-form
Query box) instead of writing pandas from a blank cell, inspect it
(describe/info/nunique/value counts), export the result — or export the
whole pipeline as a standalone `.py` script, or save it as a reusable
named template. Every UI step shows the real pandas line it corresponds
to — the point is to bridge "knows pandas, but the first load-and-wrangle
friction is annoying," not to replace pandas.

**Phase 2 complete.** The MVP (rename/drop/add/filter/sort + export) shipped
first; a second pass added a free-form custom-Python step, the
pipeline-as-script export, and saved templates. All three slotted into the
existing replay-pipeline model (original df + ordered step list) without a
redesign, as planned.

**Query box (third pass).** The custom-Python step started as one more
option buried in the "Add step" dropdown, form-submit-to-commit like every
other step. That made it unusable for anything you weren't already sure
about — one typo and you'd committed a broken step to the pipeline (still
recoverable via the ✕, but no way to *see* the result before committing).
Pulled it out into its own always-visible "Query" card above "Add step",
with two modes instead of one submit: **Check** (`/step/check`) runs the
code against the current DataFrame and shows what it would produce without
touching `session.steps`, and **Add to pipeline** (`/step`, unchanged)
commits it. Also added quick-insert snippet buttons (`SNIPPETS` in
`ui/index.html`) so you start from working code for the common shapes
(sort, filter, group by, dedupe, fillna, parse date, clean text, ...)
instead of a blank `def transform(df):`.

**Check-result panel + scale pass (fourth pass).** Two follow-ups from
actually using it: (1) the Check result was rendering inside the 320px
sidebar column — useless once a dataset has more than a handful of
columns, since you're scrolling a tiny box both ways. Moved it to
`#queryCheckPanel`, a full-width card between the upload bar and the main
`.layout` grid, with its own "Add to pipeline" button (commits exactly the
code that was last Checked, via `lastCheckedCode` — not whatever's
currently sitting in the textarea, in case you kept editing after
Checking) and a "✕ Dismiss" button. (2) asked directly: does this survive
5000 columns × 50k rows? Answer was no as originally built — see the cell-
budget gotcha and the Tabulator many-columns gotcha below for what was
fixed and what's still an open, bigger-scope item (searchable column
pickers instead of thousand-option `<select>`s — not built yet, flagged
for when it's actually needed).

**Head/sample toggle, cell overflow, fixed-viewport layout, refresh
survival (fifth pass).** Four things from actually using it on a real
screen: (1) a head/sample toggle for the preview grid (`preview_mode` +
`sample_seed` on `Session`, a fixed seed so `.sample()` doesn't reshuffle
on every incidental `recompute()` — see the seed gotcha below); (2) long
cell values had no overflow handling — `maxWidth`/`tooltip` on Tabulator
columns, ellipsis + `title` attribute on the plain result tables; (3) the
whole page scrolled instead of the table/sidebar scrolling independently
— `body`/`.wrap`/`.layout` restructured into a fixed-viewport flex/grid
shell, see the `min-width:0` gotcha below for the real bug this surfaced;
(4) a browser refresh lost everything even though the session was still
alive server-side — new `GET /session` restores it on page load.

**Non-blocking pandas calls + load options (sixth pass).** Loading a real
large file (~235MB) looked completely frozen — no feedback, nothing
responded. Two separate problems, both fixed: (1) every pandas-calling
endpoint ran its work directly inside `async def`, which with
`--workers 1` blocks the ONE process's entire event loop for the call's
whole duration — now wrapped in `asyncio.to_thread` (see the gotcha
below); (2) there was no upload/parse feedback at all — `loadFile()` now
uses `XMLHttpRequest` (not `fetch`, which has no reliable cross-browser
upload-progress event) to show a real percentage during upload, then an
indeterminate bar during server-side parsing. Also added, directly
requested: a "Load options" panel (separator incl. TSV/custom, encoding,
header row toggle, optional row limit) and a size-based warning
suggesting the row limit on files over 150MB.

**Better custom_code errors, a real snippet catalog, shared result panel,
format-aware load/export options (seventh pass).** Five follow-ups from
actually using it: (1) a raw pandas `KeyError` (e.g. `drop_duplicates(subset=
["HR"])` when `"HR"` is a cell value, not a column) surfaced as an opaque
`Index(['HR'], dtype='object')` — `custom_code` now catches `KeyError`
specifically and explains the likely mistake; (2) the 10-button snippet
quick-insert grew into 51 functions across 10 categories in `SNIPPETS`
(`ui/index.html`), rendered as a `<select>` with `<optgroup>`s instead of a
button grid — every snippet spells out the function's real pandas keyword
defaults, with `<placeholder>` markers only where there's no sensible
default; (3) Insights (describe/info/nunique/value_counts) used to render
into a cramped 320px sidebar box — they now open in the exact same
full-width panel Check results use (`#queryCheckPanel`, literally the same
DOM element, not a lookalike second one — see the shared-panel gotcha
below); (4) load options were CSV-only even though JSON/XML/Parquet have
their own real pandas read options — `engine.load_dataframe()` now takes
format-specific kwargs (`orient`/`lines` for JSON, `xpath` for XML,
`columns` for Parquet) and the Load Options panel shows the right field
group based on the selected file's extension; (5) export was three
one-click buttons with hardcoded settings — clicking one now opens a
native `<dialog>` (centered by the browser automatically, zero extra
positioning code) with format-specific options (CSV separator/index, JSON
orient/date_format/indent, Parquet compression/index) before downloading.

## How it's built

- `server.py` — FastAPI app: serves `ui/index.html`, plus `/load`,
  `/load/vault`, `/step`, `/step/check`, `/step/remove`, `/step/reset`,
  `/insight`, `/export`, `/script`, `/template/list`, `/template/save`,
  `/template/apply`, `/template/delete`. This is the one tool in the
  Toolbox so far with real backend state (every other tool is
  client-side-only or stateless), hence the extra modules below.
  `/load/vault` is the consumer side of duck-lab's/sql-studio's
  `/export/vault` — decrypts a saved vault dataset via
  `core.vault.load_dataset_file()`, reads its bytes, then feeds them
  into the exact same `engine.load_dataframe()`/`create_session()` path
  `/load` already uses for an uploaded file, so a vault-sourced load
  gets the same preview/insight/export/template behavior as any other
  session with zero special-casing downstream. Like every other
  pandas/vault-touching call in this file, it runs through
  `asyncio.to_thread` — see the gotcha below for why that matters here
  specifically (unlike duck-lab's own `/load/vault`, which deliberately
  does NOT use `to_thread`, matching that tool's own convention).
- `engine.py` — session store (`SESSIONS: dict[str, Session]`, in-memory,
  keyed by a `df_studio_sid` cookie) and the **replay model**: a session
  keeps `original_df` + an ordered `steps` list; the "current" DataFrame is
  always recomputed by folding every step over the original
  (`recompute()`), never mutated incrementally. This is what makes
  "remove step #2 of 5" trivially correct — just replay the remaining 4 —
  instead of needing undo/redo snapshot bookkeeping. `_run_step()` is the
  shared core (look up the handler, replay to get the current df, run the
  handler); `apply_step()` wraps it and appends to `session.steps`,
  `preview_step()` wraps it and returns just the resulting df **without**
  appending — that's the whole Check/Add split, one shared code path so
  they can never quietly diverge in behavior. Also has `generate_script()`
  (joins every step's generated code into a standalone runnable `.py`) and
  `apply_template()` (clears the pipeline, replays a saved template's steps
  via `apply_step()`, stops and reports at the first step that doesn't fit
  — see gotcha below).
- `steps.py` — one handler per step type in `STEP_HANDLERS`, each
  `(df, params) -> (new_df, generated_pandas_code_line)`. The generated
  code string is what the UI's pipeline panel **and** the `/script` export
  display — adding a step type means writing a handler here **and** its
  form fieldset in `ui/index.html` (`#f-<step_type>`). Every handler raises
  plain `ValueError` on bad input (not `engine.StepError`) — see the
  exception-type gotcha below before touching error handling here.
  `custom_code` backs the Query box: `exec()`s user code that must define
  `transform(df)`, with `pd`/`np` in scope, **no sandboxing** — see the
  trust-boundary note below. It's no longer reachable through the "Add
  step" dropdown/fieldset pattern — the Query card calls it directly by
  type name (`"custom_code"`) via `/step` and `/step/check`, so if you
  rename this step type, update both `ui/index.html`'s query-box JS and
  `STEP_LABELS` together or the pipeline panel's label breaks silently.
- `templates_store.py` — saved pipelines as `{name: [{type, params}, ...]}`
  in one JSON file (`data/templates.json`, gitignored, created on first
  save). Only `type`/`params` are persisted, never the generated code —
  code is always regenerated fresh from the current `STEP_HANDLERS` when a
  template is applied.
- `ui/index.html` — single file, no build step. Uses Tabulator.js from
  cdnjs (the one non-vanilla-JS dependency in this tool; DataDiff Pro's own
  `ui/index.html` already pulls in `xlsx.js` from the same CDN, so this
  isn't a new precedent). `STATE`/`API`/`RENDER`/`EVENTS` sections in the
  `<script>` block, same shape as subnet-calc's engine/UI split. Pipeline
  entries with multi-line code (i.e. `custom_code` steps) render in a
  `<pre>`, single-line ones stay inline `<code>` — see `renderPipeline()`.
  The Query card's snippets live in the `SNIPPETS` object near the top of
  the `<script>` block — add an entry there (not a new fieldset) to add a
  new quick-insert.

## The one import gotcha

`engine.py` and `server.py` both use a try/except dual import
(`from df_studio import X` → falls back to `import X`) so the tool works
**both** mounted inside the toolbox (`PYTHONPATH=/app`, package
`df_studio`) **and** run standalone from inside this folder for dev/testing
(`cd df-studio && uvicorn server:app --reload`, flat imports, no package).
Every other Toolbox tool only has `server.py`, so this never came up for
them — if you add a fourth local module here, give it the same try/except
at its own internal-import call sites, not just at the entrypoint.

## Things that will bite you if you don't know them

- **In-memory sessions — a server restart silently drops every open
  session.** No persistence to disk by design (matches the tool's
  no-durability posture: nothing here is meant to survive past "export
  it"). If sessions need to survive restarts later, that's a real design
  change (cache to `data/<session>.parquet`), not a quick patch.
- **This is why `../Dockerfile`'s uvicorn CMD is pinned to `--workers 1`.**
  With more than one worker, `SESSIONS` isn't shared across the separate
  OS processes uvicorn spawns — a session created by `/load` on worker A is
  invisible to worker B, so a later request can hit the other worker and
  fail with "No active session" even though nothing expired and nothing
  was deleted. This is exactly what happened once when the Dockerfile still
  said `--workers 2` (real incident, not hypothetical) — it looked random
  and time-delayed because it depends on which worker answers each
  request, not on any timer. Don't raise `--workers` back up without giving
  this tool a real shared session store (Redis/SQLite) first — every other
  tool in the Toolbox is stateless/client-side and genuinely doesn't care
  about worker count, so this constraint is specific to df-studio alone.
- **`add_column`/`filter_rows` use `df.eval(...)`/`df.query(...,
  engine="python")`** — supports arithmetic, comparisons, string
  concatenation referencing columns by bare name. It does **not** give you
  arbitrary Python (no `lambda`, no calling into numpy/custom functions) —
  that's what the separate `custom_code` step is for. Don't let the UI hint
  text drift from what `engine="python"` actually accepts.
- **`custom_code` runs with zero sandboxing** — full `exec()` with real
  `pd`/`np`, on whatever machine runs the container. That's a deliberate
  trust-boundary decision (single-user local tool, the owner's own code on
  the owner's own machine), not an oversight. If this tool is ever exposed
  beyond one trusted local user, that decision needs revisiting before
  anything else does. This applies equally to Check (`/step/check`) — it
  still `exec()`s the code, it just skips the append; "Check" is not a
  safer sandbox, only a "don't commit yet" toggle.
- **`/step/check` never touches `session.steps` — but it does run
  `recompute()` first**, same as every other read here. So Check reflects
  whatever's currently *committed* in the pipeline, not whatever's sitting
  unsaved in the Query textarea from a previous Check. Two sequential
  Checks without an Add between them are independent — the second doesn't
  build on the first's hypothetical result.
- **Step handlers raise plain `ValueError`, not `engine.StepError`** —
  `StepError` is a subclass of `ValueError`, not the other way around, so
  `except StepError` does **not** catch what the handlers actually throw.
  `engine.apply_template()`'s per-step try/except had exactly this bug
  (caught `StepError`, missed the `ValueError`s `custom_code`/`add_column`/
  etc. actually raise, so a template hitting a bad step crashed with an
  unhandled 500 instead of reporting `template_errors`) — fixed, but if you
  add another `except StepError` anywhere in this tool, make it
  `except ValueError` instead, or add both.
- **Preview rows are capped by `PREVIEW_CELL_BUDGET` (400,000 cells) in
  `engine.py`, not just by row count.** `row_cap = PREVIEW_CELL_BUDGET //
  num_columns`, floored at `MIN_PREVIEW_ROWS` (20) and ceilinged at
  `PREVIEW_ROW_CAP` (5000). A normal file (tens of columns) still shows up
  to 5000 rows, unchanged from before. A wide file (measured live at 5000
  columns × 300 rows) shows 80 rows instead of sending 300×5000 = 1.5M
  cells of JSON on every single click. `/export` always operates on the
  full uncapped DataFrame regardless — "my export has more rows than the
  table showed" is expected, not a bug.
- **Even with that cap, 5000 real columns is still heavy** — the capped
  preview response for the 5000-column test case above was ~8.4MB and took
  ~2.7s per step, because DataFrame→JSON serialization cost scales with
  cell count and the cap only bounds it, it doesn't make it free. This is
  the honest ceiling of "render everything as one big table": it protects
  against the worst case (payload growing with row count on top of column
  count) but doesn't make thousands of columns feel snappy. If someone
  actually needs comfortable use at that width, the real fix is not
  rendering all 5000 columns at once — a column search/subset picker
  (see below) rather than a bigger cap.
- **`server.py`'s `COPY df-studio/ ./df_studio/`  in `../Dockerfile` copies
  the whole folder in one line**, unlike every other tool's two-line
  `server.py` + `ui/` copy — because this tool has extra modules
  (`engine.py`, `steps.py`). If you add a `data/` cache folder later, make
  sure it isn't swept into the image if it's meant to be a runtime-only
  writable path.
- **The grid rebuilds Tabulator from scratch on every `renderTable()` call**
  (`table.destroy()` then `new Tabulator(...)`) instead of the previous
  `setColumns`/`setData` incremental update — needed so the layout mode
  (`fitColumns` vs `fitDataStretch`) always matches the CURRENT column
  count rather than whatever the first load had. Trades a little flicker
  per step for always-correct layout; if that flicker becomes annoying at
  normal (non-wide) column counts, the fix is to only force-rebuild when
  crossing `MANY_COLUMNS_THRESHOLD` (60), not on every render.
- **Columns beyond `MANY_COLUMNS_THRESHOLD` (60) get a fixed 160px width**
  in `ui/index.html`'s `renderTable()` instead of Tabulator's content-based
  auto-sizing — the auto-sizing pass (measuring every column's content to
  pick a width) is what actually stalls the grid at high column counts, not
  rendering itself. Couldn't verify this visually in this environment (no
  browser available here, only the HTTP API) — the backend-side numbers
  above were measured directly, but the Tabulator perf claim is a
  documented-best-practice fix, not something profiled in a real browser
  against a real 5000-column render. Worth an actual look before trusting
  it blindly at that scale.
- **The `.col-select` pickers (rename/drop/sort/value-counts column choice)
  are still plain `<select>`/`<select multiple>` elements** —
  `populateColumnSelects()` rebuilds one `<option>` per column on every
  preview. Fine up to maybe a few hundred columns; a genuinely unusable
  scrolling list at thousands. Not fixed yet — flagged, not built, because
  it's a real UI component (search-as-you-type, and for the multi-select
  fields a chip/tag picker) across five different form fields, not a
  one-line change like the two above. Build it when wide files are an
  actual, not hypothetical, use case.
- **The Check-result and Insight panels are the literal same DOM element**
  (`#queryCheckPanel`) and the literal same JS state (`#queryCheckTitle`,
  `#queryCheckMeta`, `#queryCheckResult`) — not two visually-matching
  panels. `showInsightPanel()` hides `#queryCheckAddBtn` (nothing to commit
  for a read-only insight) and blanks the meta line; the Check handler
  un-hides the Add button and resets the title back to "Check result" every
  time it runs. If you add a third thing that wants a full-width result
  panel, extend this same show/hide pattern rather than adding another
  near-identical `<div>` — that's exactly the duplication that prompted
  this consolidation in the first place.
- **`engine.load_dataframe()`'s extra kwargs are format-specific and mostly
  silently ignored by the wrong format** — passing `orient` to a CSV load
  does nothing (CSV branch never reads it), passing `sep` to a JSON load
  does nothing. This is deliberate (the UI only ever sends the kwargs for
  the detected format) but means a bad param name here fails silently
  instead of loudly — if you add a new kwarg, make sure `ui/index.html`'s
  `LOAD_FORMAT_GROUPS`/`collectLoadOptions()` actually gate it to the right
  format group, or it'll just be dead weight sent-and-ignored on every load.
- **`/export`'s three formats now validate their options before writing**
  (`orient` checked against `_VALID_JSON_ORIENTS`; anything else — a
  multi-character CSV `sep`, an unknown Parquet `compression` codec —
  surfaces as a clean 400 via the `try/except` around the `to_csv`/
  `to_json`/`to_parquet` call, not an unhandled 500). If you add a new
  export option, keep it inside that `try` — the endpoint had NO error
  handling around the write step before this pass, which was already a
  latent gap even for the old hardcoded no-options version.
- Mounted at `/tools/df-studio/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way (verify with `cd df-studio && uvicorn server:app --reload`).

# Mini Sheet — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and `../KNOWLEDGE_MAP.md` for the
symptom→file map. Plan and status: `../docs/roadmap/ROADMAP.md`, Phase M.

## What this tool is

A small spreadsheet for editing data **by hand** (owner: "a mini excel where I can edit data easily manually, basic Excel-like
functionality, not full"). Open a Vault Data table, a pasted block from Excel/Sheets, or a CSV/TSV/JSON/XLSX file (or a blank
sheet); edit cells; use basic formulas; sort / filter / find & replace / undo; save back to Vault Data as a typed table or
download CSV/XLSX. For **small data** — up to 50,000 rows × 200 columns and 5 M cells (`MINI_SHEET_MAX_ROWS/_COLS/_CELLS`),
files up to 25 MB; bigger tables are offered as "first N rows", bigger files are sent to Vault → Vault Data → Load files.
The sheet lives **in the browser**; since roadmap M2 it is a **workbook of several sheets** (Excel-style tabs, up to 50) and a copy of the
unsaved workbook is **autosaved on the server as a draft** (Redis + S3 storage, never in a process's memory — manifest `state: [session]`), so a
reload or a closed tab loses nothing and any worker can answer.

## Where things live

| Concern | File |
|---|---|
| Endpoints (page, `/formula.js`, `/wrap.js`, `/limits`, `/catalog-lite`, `/table`, `/save`, `/save-all`, `/parse`, `/import`, `/export`, `/draft`), name rules, replace/backup | `server.py` |
| The draft store: one gzip-JSON workbook per browser cookie, `rev` for the two-tab check, sliding TTL, sweep (Redis record + S3 object, or a dict standalone) | `draftstore.py` |
| Typing a sheet into Parquet (every cell checked), table → JSON, paste/CSV/JSON/XLSX parsing + type guessing, CSV/XLSX downloads; sheet-name rules, all-sheets xlsx in (`parse_xlsx_all`) and out (`build_export_workbook`), workbook size limits | `sheetio.py` |
| The formula language: tokenizer, parser, evaluator, cycle detection (shared across sheets), `shift()` for fill, `retargetSheet()` for sheet rename/delete | `ui/formula.js` (also run by node in the tests) |
| How many lines a text takes in a column of a given width (`countLines`, `estimateLines`, `rowHeight`) — pure, no DOM | `ui/wrap.js` (also run by node in the tests) |
| The page: workbook + tabs, grid (own DOM virtualisation, variable row heights), selection, editor, clipboard, fill, undo/redo, filter/sort/find, dialogs, draft autosave/restore | `ui/index.html` |
| Tests | `../tests/unit/test_mini_sheet.py` (node + sheetio + draft store), `test_mini_sheet_server.py` (HTTP + Vault Data, needs DuckDB), `mini_sheet_formula_cases.js`, `mini_sheet_wrap_cases.js` |

## How it behaves (and why)

- **Cells are raw JS values**: `null`, number, text, boolean, or a formula string starting with `=`. Numbers/booleans appear only when
  the column's kind says so (`integer`, `number`, `boolean`) — text columns keep what was typed. Dates are ISO text (`YYYY-MM-DD`,
  `YYYY-MM-DD HH:MM:SS`); decimals keep their exact text (`"10.25"`); integers beyond 2^53 travel as text (JS would round them).
- **Types are the table's own**: opening a Vault Data table keeps each column's SQL type (`sql` on the column: bigint, smallint, numeric(10,2),
  timestamptz …); saving rebuilds exactly those Parquet types (`sheetio.arrow_type`). A column the user adds or re-types gets the default for
  its kind. uuid/json/time/binary/nested values are edited as text and saved as varchar (a note says so when opening).
- **Never silently wrong**: `sheetio.coerce_table` checks EVERY cell; a value that doesn't fit (letters in a whole-number column, a third
  decimal in `numeric(10,2)`, `2026-02-30`, a smallint overflow…) makes `/save` answer **422** with the first 200 problems (row, column,
  value, reason) and nothing is written. The page shows the same problems softly while editing (red cell + tooltip, count in the status bar).
  Blank cells are NULL. Formula errors (`#DIV/0!`…) block saving/downloading until fixed.
- **Formulas are saved as their computed values** — Vault Data tables have no formulas. The page says so in the Save dialog.
- **Partial sheets can't overwrite their source**: if a table was opened as "first N rows", `/save` refuses `overwrite`/`replace_keep` onto the
  same table (400) — saving would delete the rest. `create` under a new name works.
- **Replace = rename-then-create**: `replace_keep` renames the existing table to `<name>_backup_YYYYMMDD_HHMM` and writes the new one (rolled back
  if the write fails), so the old data really is kept. `overwrite` is lake's own overwrite: the old files are deleted (a history row stays).
  A bare name goes to workspace `system`; `ws.name` in the table box is split.
- **Not Excel on purpose**: refs are plain positions (`A1` = first column, first DATA row — the header row is not counted) and do **not**
  move when rows are inserted/deleted/sorted. Fill-down/right (Ctrl+D, Ctrl+R, drag handle) DOES shift relative refs (`$A$1` anchors stay).
  Excel precedence is followed (`-2^2` = 4, `2^3^2` = 64). Text that looks like a number ("12") counts as a number in formulas.

### Workbook, sheets, cross-sheet formulas (M2)

- `W = {name, sheets, active}`; `S` is always the ACTIVE sheet and nearly all page code works on `S`, so switching a sheet is just
  `activateSheet(i)` (saves the old sheet's scroll, swaps `S`, redraws). Each sheet owns its selection, scroll, filters, search, widths, wrap flags,
  **undo/redo stack** (undo applies to the active sheet only) and "as saved" baseline. Tab names: 1–31 characters, none of `[ ] : * ? / \`,
  no leading/trailing `'`, unique ignoring case (`checkSheetName` on the page, `sheetio.check_sheet_name(s)` on the server — keep both in step).
- **Opening**: an .xlsx opens EVERY sheet (`/import` with `all_sheets=true` → `parse_xlsx_all`; empty / over-limit sheets are skipped with a note);
  CSV / paste / JSON / a Vault Data table are one sheet. When a workbook is already open every Open dialog offers *Add as a new sheet* (default) or
  *Replace the whole workbook* (asks if anything is unsaved). *Open ▾ → Blank sheet* adds a sheet to an open workbook; *Close workbook* starts over.
- **Saving**: *Save* = the active sheet, exactly as before. *Save all sheets…* = `POST /save-all`: EVERYTHING is checked first (names, a bad cell in any
  sheet → 422 listed per sheet, an existing table when `on_exists` is `ask` → 409 listing them) and only then written, one table per sheet.
  Downloads: Excel = all sheets (one worksheet each), CSV = the active sheet.
- **Cross-sheet formulas**: `=Sheet2!A1`, `='My sheet'!A1:B9` (quote a name with spaces/odd characters; `''` for an apostrophe). Unknown sheet = `#REF!`.
  One cycle detector is shared by all sheets (`opts.shared`), so a loop through two sheets is `#CIRC!`. Sheet names are only ever looked up through a Map-like
  search on the page (`sheetByName`), never used as object keys — `__proto__!A1` is just an unknown sheet. Any edit clears EVERY sheet's formula cache.
  **Renaming a sheet** rewrites the formulas that point at it (`F.retargetSheet`, also on each sheet's "as saved" copy so nothing lights up as edited);
  **deleting** one turns them into `#REF!`. Both clear the undo history of the sheets whose formulas changed (an old undo step would bring the old name back).
  Sheet add / rename / delete / duplicate / move are NOT undoable.

### Draft (autosave) (M2)

- The whole workbook (columns incl. widths/wrap flags, raw cells incl. formulas, the "as saved" baseline so yellow/green highlights survive, origin, filters,
  selection, scroll, active sheet) is PUT to `/draft` ~2 s after the last change (longer for big workbooks), on tab hide and on page hide. Body = gzip JSON
  (`X-Draft-Encoding: gzip`, browser `CompressionStream`; plain JSON if unavailable). Server: cookie `mini_sheet_sid` (HttpOnly, SameSite=Lax, 7 days,
  `MINI_SHEET_DRAFT_TTL`), at most `MINI_SHEET_DRAFT_MAX_MB` (40) compressed (413 above; the page shows "Draft not saved (…)"), unpacked size capped (zip-bomb guard).
- On page open `GET /draft` restores it with a banner ("Restored your unsaved work from … — Discard"). **Undo history is not stored.** Saving to Vault Data keeps the
  draft (the workbook is still open); *Close workbook* / Discard delete it. `?nodraft` in the URL turns autosave and restore off (browser tests).
- **Two tabs of one browser share one draft.** Each PUT carries the `rev` the tab last saw; if another tab has written since, the server answers 409 and this tab
  pauses autosave ("Draft paused — also open in another tab (click)") until the user takes over. The check is get-then-set, not atomic (fine for one person).
- Draft layout: `{v, changed, wb:{name, active, sheets:[{id,name,cols,rows:[[rid,[…]]],orig,…}]}}`. `orig` is either `diff` (columns as opened: only the rows that
  differ from their saved copy, plus `fresh` row ids and a `gone` count) or `full` (columns were added/moved/deleted: the whole saved copy). The server
  validates names and size limits (`_check_draft`) but never interprets cells.
- The leave-page warning now only appears while the draft is NOT safely stored (pending, failing or paused) — a reload with a saved draft just restores it.

### Wrap text per column + variable row heights (M2)

- Column header ⋮ → **Wrap text** (a checkbox), plus the toolbar's *↵ Wrap ▾* → wrap/unwrap every column. `col.wrap` is part of the sheet (and the draft), not an
  undoable edit and not a "change" (it doesn't make the sheet unsaved). A wrapped column shows its whole text (`white-space: pre-wrap; overflow-wrap: anywhere`,
  line breaks kept); each row is as tall as its tallest wrapped cell (min 26 px, at most 40 lines = 689 px, then "…" + the text on hover).
- Geometry: `S.rowY` (a `Float64Array` of row tops, `null` while no column wraps → plain `r * 26`) with `rowTop(r)`, `rowHt(r)`, `totalH()` and a binary-search
  `rowAtY(y)`. EVERY place that used `r * RH` goes through these (render, gutter, selection boxes, fill handle, scroll-into-view, hit-testing, drag-select,
  PageUp/Down, editor placement). New code must not assume a row is 26 px.
- Heights are guessed first (`WR.estimateLines` from the text length) and replaced by exact ones (`WR.countLines` with a canvas `measureText` in the cell's real
  font) only for the rows on screen (`measureRows` in `renderBody`) — so 50,000 rows stay fast (wrapping one column ≈ 0.1 s). When the exact heights differ, the
  layout is rebuilt and the scroll position re-anchored on the row at the top (`relayoutKeepAnchor`; it also stays pinned to the very end). `row.h` / `row.ex` are the
  cached height and "was measured" flag; any edit sets `ex = false` for the sheet's rows.
- Dragging a column edge re-wraps live: the resize updates the width at once and re-measures once per animation frame.
- Editing a wrapped cell uses a text area (`#edw`) that grows with the text; **Alt+Enter** inserts a line break, Enter commits. Other columns still use the one-line `#ed`.
- Header / gutter selections (a whole column or row) no longer scroll the grid (a whole-column click used to jump to the last row — painful with tall rows).

## Things that will bite you

- **The formula language must never become `eval`**. `formula.js` tokenizes, parses to a tree, walks the tree; functions live in a
  null-prototype table and are looked up with `hasOwnProperty`; limits: 1000 chars, 600 tokens, nesting 40, eval depth 250, ranges clamped to the
  sheet and refused above 5 M cells. `tests/unit/mini_sheet_formula_cases.js` has the hostile cases (`=__proto__`, `=constructor`,
  `=alert(1)`, deep nesting, huge ranges, 5,000-long chains); a unit test also greps the page for `eval(` / `new Function`.
- **Undo is a stack of command objects** (`cmdSet`, `cmdInsertRows`, `cmdDeleteCols`, `batch`…): each keeps the row/column OBJECTS (not
  positions) and relies on strict stack order — undo only works because the state at undo time equals the state right after the command.
  New operations must be commands that `exec()`; mutating `S.rows` directly breaks undo and the dirty highlight. `batch(makers)` builds
  later steps AFTER earlier ones ran (paste adds columns, then rows, then sets cells). `S.cleanIdx` = undo-stack length at open/save → "unsaved".
- **Dirty highlight** compares each cell with `S.origRows` (row id → original values) via `S.origColIdx` (column id → original index); new rows
  (no entry) show green. `rebaseline()` after a save resets both.
- **The grid is virtual**: only ~400 cells are in the DOM (`renderBody` from scroll position; overlays for selection/active cell/fill handle are
  separate absolutely-positioned divs; headers/gutter are translated copies kept in step with `#vp` scroll). Selection is in VIEW coordinates
  (after filter/search); formulas and the evaluator use DATA indices (`S.view[r]`).
- **Clipboard**: copy/cut/paste use the browser's `copy`/`cut`/`paste` events (no Clipboard API permission). Copy gives the DISPLAYED values
  (formulas as results). Pasting past the last row/column adds rows/columns (named `column_N`).
- **Header ⋮ menu**: the document-level `mousedown` that closes menus runs in the CAPTURE phase on purpose — in the bubble phase it closed
  the header menu the same click opened it.
- CSV downloads prefix text that Excel would run as a formula (`=`, `@`, `+x`, `-x`) with an apostrophe; XLSX writes such text as a string cell.
- `window.__sheet` is a test hook (the browser tests drive the page through it) — harmless, keep it small.
- Double-clicks on the sheet tabs and on column headers are detected BY HAND (two clicks within 420 ms): the first click redraws that strip, and the browser never
  fires its own `dblclick` on an element that was replaced between the clicks.
- Playwright's driver does not start in the dev environment; the browser checks were run with Selenium + `/usr/bin/chromium` + `/usr/bin/chromedriver` against
  `uvicorn server:app` (standalone, in-memory drafts, temp Vault Data catalog).
- Run the page standalone: `cd mini-sheet && uvicorn server:app` (Vault Data then uses SQLite under `../data/lake` — don't do that on a
  checkout you care about; the browser tests use a temp catalog instead).

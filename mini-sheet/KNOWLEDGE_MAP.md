<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Mini Sheet — mounted at `/tools/mini-sheet/`

A small spreadsheet for editing data by hand (roadmap M1; M2 = autosaved draft, per-column wrap, several sheets). The sheet lives in the browser; the
server opens/saves/converts and keeps one autosaved draft per browser. Read `mini-sheet/CLAUDE.md` first. Runtime `data`, manifest
`vault: {data: write}`, `state: [session]` (the draft is in Redis + S3 storage, not in a process).

| If you need to change... | Go to |
|---|---|
| The size limits (rows / columns / cells / upload MB), their env vars | `sheetio.py` (`MAX_ROWS`, `MAX_COLS`, `MAX_CELLS`, `MAX_UPLOAD_BYTES`); `server.py` `GET /limits` tells the page |
| Opening a Vault Data table (the 413 "open the first N rows" answer, notes about uuid/json/binary columns) | `server.py` `get_table` → `sheetio.table_to_json`; page: `openTable()` |
| What a column's kind / SQL type becomes in Parquet (round trip) | `sheetio.kind_of`, `arrow_type`, `sql_type_of` |
| Which cells are rejected when saving, and the wording of the reason | `sheetio._conv` (`CellError`), `coerce_table` (the 422 list, `MAX_ERRORS`); the page's soft check is `problem()` in `ui/index.html` — keep both in step |
| Save behaviour: bare name → `system`, `ws.name`, create / overwrite / replace_keep (backup table), partial-sheet guard | `server.py` `save`, `_split`, `_backup_name`, `_write_sheet`, `_partial_guard` |
| Pasted text / CSV / TSV / JSON / XLSX parsing and the type guessing | `sheetio.parse_text`, `parse_file`, `parse_json`, `parse_xlsx`, `infer_kind` |
| CSV / XLSX download (Excel-formula safety) | `sheetio.build_export`, `_csv_safe`; `server.py` `export` |
| The formula language (functions, errors, precedence, limits, cycle detection, fill's reference shifting) | `ui/formula.js` (`FUNCS`, `parse`, `createEvaluator`, `shift`, `LIMITS`); cases: `tests/unit/mini_sheet_formula_cases.js` |
| The grid: virtual rendering, selection overlay, header/gutter, column resize | `ui/index.html` `renderBody`, `renderHeads`, `drawOverlay`, `layoutCols` |
| Row heights (wrapped columns make rows taller): `rowTop` / `rowHt` / `totalH` / `rowAtY`, the guess-then-measure logic, scroll anchoring, "wrap this column" | `ui/index.html` `layoutRows`, `measureRows`, `relayoutKeepAnchor`, `setWrap`, `wrapAll`; line counter `ui/wrap.js` (cases: `tests/unit/mini_sheet_wrap_cases.js`) |
| Sheets / tabs: add, rename (formulas follow), duplicate, delete (→ `#REF!`), move, which sheet is active | `ui/index.html` `renderTabs`, `activateSheet`, `renameSheet`, `deleteSheet`, `duplicateSheet`, `moveSheet`, `rewriteSheetRefs`, `placeSheets` |
| Formulas that point at other sheets (`Sheet2!A1`, `'My sheet'!A1:B9`), sheet-name quoting, rename/delete rewriting, cross-sheet cycles | `ui/formula.js` (`readCellOrRange`, `targetCtx`, `createEvaluator` `opts.shared` / `opts.sheet`, `retargetSheet`, `quoteSheet`); page `attachEvaluator`, `sheetByName` |
| The autosaved draft: what is stored, when it is written, restore banner, the two-tab 409 pause | page: `serializeWorkbook`, `sheetFromDraft`, `flushDraft`, `tryRestore`, `takeOverDraft`; server: `server.py` `/draft` (`_check_draft`, `_gunzip`), `draftstore.py` (`StateBackend`, `MemoryBackend`, `RevConflict`); env `MINI_SHEET_DRAFT_TTL`, `MINI_SHEET_DRAFT_MAX_MB` |
| Opening every sheet of an .xlsx; one .xlsx with all sheets out; sheet-name rules; workbook limits | `sheetio.parse_xlsx_all`, `build_export_workbook`, `check_sheet_name(s)`, `check_workbook_size`; `server.py` `/import` (`all_sheets`), `/export` (`sheets`) |
| Save all sheets (all-or-nothing checks, 422 per sheet, 409 list, replace/backup per table) | `server.py` `save_all`, `_write_sheet`, `_partial_guard`; page `openSaveAllDialog` |
| Editing: in-cell editor (one-line `#ed`, or the growing text area `#edw` in a wrapped column; Alt+Enter = new line), formula bar, typed-key start, Enter/Tab/F2 rules | `startEdit`, `commitEdit`, `growEditor`, the `#ed` / `#edw` / `#fx` key handlers |
| Undo / redo and every edit as a command | `exec`, `undo`, `redo`, `cmd*` factories, `batch` |
| Copy / paste (TSV, Excel quoting), paste that grows the sheet | `copyText`, `parseTSV`, `pasteGrid` |
| Fill down/right, the drag handle, series (3,4 → 5,6) and formula shifting | `fillItems`, `fillDownRight`, drag kind `"fill"` in `dragMove` |
| Sort, per-column filter syntax (`>5`, `=x`, `!x`, `empty`), search box | `sortCol`, `makeFilter`, `rebuildView` |
| Find & replace | `findMatcher`, `matches`, `replaceCells`, `openFind` |
| Dirty-cell highlight / "unsaved" status / the cell-type warning count | `isDirty`, `rebaseline`, `isChanged`, `updateStats` |
| The Open / Save dialogs and the 409 "replace / backup / other name" choice | `openTableDialog`, `openPasteDialog`, `openFileDialog`, `openSaveDialog`, `showCellErrors` |

Non-obvious behaviours (details in `mini-sheet/CLAUDE.md`): formulas are saved as computed values; refs are positions that don't move on
insert/sort (fill shifts them); a "first N rows" sheet can't overwrite its source; `replace_keep` renames the old table to
`<name>_backup_<time>` while `overwrite` deletes its files; the outside-click menu closer runs in the capture phase. M2: `S` is the ACTIVE sheet (all sheets
share one cycle detector); no code may assume a row is 26 px (use `rowTop`/`rowHt`); undo history is per sheet and is NOT in the draft; sheet
rename/delete rewrite formulas and start the affected sheets' undo afresh; two tabs of one browser pause each other's autosave (409).

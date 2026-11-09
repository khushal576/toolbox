<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Text Editor — mounted at `/tools/text-editor/`

Notepad++-style editor for messy text, entirely in the browser (tier 1, runtime light): tabs, regex find/replace,
multi-cursor, validate + format JSON / JSON Lines / XML / HTML / CSV with line numbers, format Python (ruff wasm) and SQL
(sql-formatter, PostgreSQL style), line tools, regex line tools, split compare, Mask (sensitive data → editable
original→masked JSON → masked text) and Visualize (live sandboxed HTML/CSS preview). Read `text-editor/CLAUDE.md` first.

| If you need to change... | Go to |
|---|---|
| Serving the page, the editor bundle and the ruff `.wasm` (cache headers, `?v=`) | `text-editor/server.py` |
| JSON / JSON Lines check (positions, messages) | `text-editor/ui/index.html` `jsonError`, `validateJson` |
| XML / CSV checks | `validateXml` (DOMParser), `validateCsv` (`splitCsv`) |
| Format / Minify (JSON never parsed — big numbers stay exact; XML indenter; HTML = js-beautify; SQL = sql-formatter; Python = ruff wasm) | `formatJson`, `minifyJson`, `formatXml`, `doFormat`, `pyWhere` |
| Mask: what counts as sensitive, the mapping JSON, applying / restoring | `DETECTORS`, `keyCategory`, `scanSensitive`, `openMask`, `maskReplace` (`#maskDlg`) |
| Mask → 🧠 Find names (AI): the browser-side name model, its files, the `/ner/…` route, chunking / grouping tokens into names | `aiNames`, `loadNer` (`#maskAI`); `text-editor/server.py` `serve_ner`; `scripts/get-ner-model.sh` (files in git-ignored `./models/ner`) |
| Visualize (live HTML preview, sandbox, page width) | `togglePreview`, `renderPreview` (`#preview`) |
| Line tools (sort, dedupe, trim, case, SQL IN, join/split…) | `LINE_OPS`, `applyLines` |
| Regex keep/remove/extract/count | the `#regexBar` handler (`getRx`) |
| Split compare | `openCompare`, `buildMerge` (`MergeView`, `diffConfig`), `syncBack` |
| Keyboard shortcuts | `extraKeys` (+ CodeMirror defaults) |
| Tabs kept between visits (4 MB) | `persist`, `KEEP_LIMIT` |
| The bundle's contents / rebuild | `text-editor/ui/vendor/entry.js` + `text-editor/CLAUDE.md` |

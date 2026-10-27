# Text Editor — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and `../KNOWLEDGE_MAP.md` for the
symptom→file map.

## What this tool is

A Notepad++-style editor for messy text when Notepad++ isn't at hand (owner request, 2026-10-28): tabs, line
numbers, regex find/replace, multi-cursor editing, validate (JSON / JSON Lines / XML / CSV, every problem with its
line) and format/minify (JSON / XML / HTML), line tools (sort, dedupe, trim, case, SQL IN quoting, join/split…),
regex line tools (keep/remove matching lines, extract matches → new tab, count) and a split **compare** view with
the differences highlighted. **Client-side only (tier 1):** the server serves the page and one JS bundle; no text is
ever sent to it.

## Where things live

| Concern | File |
|---|---|
| Serving the page + the bundle (`/vendor/editor-bundle.js`, cached immutable — the page asks for `?v=N`) | `server.py` |
| Everything else (tabs, validation, formatters, line/regex tools, compare, persistence) | `ui/index.html` |
| The bundle (CodeMirror 6 + lang-json/xml/html + lint + merge + js-beautify) and its entry file | `ui/vendor/editor-bundle.js`, `ui/vendor/entry.js` |

## Things that will bite you

- **Big texts:** CodeMirror only draws the visible lines, so 50k+ lines (tested with 200k) edit smoothly; nothing
  needs batching on a server. Live validation stops above 8 MB (`LIVE_LIMIT`; the button still works). Tabs are kept
  in localStorage up to 4 MB in total (`KEEP_LIMIT`); a bigger tab comes back empty, marked "(too big to keep)".
- **JSON is checked by our own scanner (`jsonError`), not JSON.parse** — exact line/column and a plain message on
  every browser (V8's wording/positions differ by version), and JSON Lines is recognised (each line checked on its
  own, every bad line listed). **Format/Minify never parse values** (`formatJson`/`minifyJson` walk the characters),
  so 20-digit ids and `1.10` stay exactly as written — JSON.stringify(JSON.parse()) would round them.
- **XML** is checked with the browser's DOMParser (line/column taken from Chromium's or Firefox's error text);
  `formatXml` is a token-based indenter (keeps CDATA/comments; `<a>text</a>` stays on one line). HTML has no strict
  check; Format uses js-beautify.
- **Multi-cursor:** Ctrl+Alt+↑/↓ is CodeMirror's default; Shift+Alt+↑/↓ is bound too because some Linux desktops take
  Ctrl+Alt+arrows for switching workspaces. Alt+drag = box selection, Ctrl+D = next occurrence, Ctrl+click = cursor.
- **Line tools act on the selected lines, else on everything**, as one undo step; a final newline is kept at the end.
- **Compare** builds a `MergeView` from the current tab (left) and another tab (right; an empty tab is made if there
  is only one); edits made there are written back to both tabs when it closes. `diffConfig` (scanLimit 20000,
  timeout 3 s) keeps two huge, very different texts from freezing the page — the diff is just coarser then.

## Rebuilding the bundle

In an empty temp dir: `npm i codemirror@6.0.2 @codemirror/state@6 @codemirror/view@6 @codemirror/commands@6
@codemirror/search@6 @codemirror/language@6 @codemirror/lang-json@6 @codemirror/lang-xml@6 @codemirror/lang-html@6
@codemirror/lint@6 @codemirror/merge@6 js-beautify@1.15.4 esbuild@0.25.0`, copy `ui/vendor/entry.js` there, run
`npx esbuild entry.js --bundle --format=esm --minify --target=es2022 --outfile=editor-bundle.js`, copy it to
`ui/vendor/` and **bump `?v=` in the page's import**. Built with state 6.7.6, view 6.43.15, commands 6.11.1, search
6.7.2, merge 6.12.3, lint 6.9.7 (715 KB).

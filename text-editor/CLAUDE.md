# Text Editor — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and `../KNOWLEDGE_MAP.md` for the
symptom→file map.

## What this tool is

A Notepad++-style editor for messy text when Notepad++ isn't at hand (owner request, 2026-10-28): tabs, line
numbers, regex find/replace, multi-cursor editing, validate (JSON / JSON Lines / XML / CSV, every problem with its
line) and format/minify (JSON / XML / HTML), format Python and SQL, **Mask** and **Visualize** (below), line tools (sort, dedupe, trim, case, SQL IN quoting, join/split…),
regex line tools (keep/remove matching lines, extract matches → new tab, count) and a split **compare** view with
the differences highlighted. **Client-side only (tier 1):** the server serves the page and one JS bundle; no text is
ever sent to it.

## Where things live

| Concern | File |
|---|---|
| Serving the page + the bundle (`/vendor/editor-bundle.js`, cached immutable — the page asks for `?v=N`) | `server.py` |
| Everything else (tabs, validation, formatters, line/regex tools, compare, persistence) | `ui/index.html` |
| The bundle (CodeMirror 6 + lang-json/xml/html/python/sql + lint + merge + js-beautify + sql-formatter + ruff loader) and its entry file | `ui/vendor/editor-bundle.js`, `ui/vendor/entry.js` |
| The Python formatter engine (ruff compiled to WebAssembly, fetched only on first Format of Python) | `ui/vendor/ruff_fmt_bg.wasm` |

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
- **SQL Format** = `sql-formatter` 15.9.0, the same library and options as SQL Studio (`postgresql`, upper-case keywords,
  2 blank lines between statements) — SQL Studio's extra `$$ … $$` body re-formatting is NOT copied. **Python Format** =
  `@wasm-fmt/ruff_fmt` (Black-compatible, 4 spaces — or tabs when the indent box says tabs; the 2-space default is
  ignored for Python because PEP 8 says 4). The `.wasm` is loaded lazily from `./vendor/ruff_fmt_bg.wasm`; a syntax
  error is reported as line/col (ruff gives UTF-8 byte offsets, `pyWhere` converts) and the cursor jumps there.
  Everything stays in the browser. Auto-detect guesses SQL/Python from the first statement/`def`/`import` line.
- **Mask** (`🛡`, Ctrl+Shift+M): `scanSensitive` runs `DETECTORS` (most specific first, a character is claimed once) plus
  a key=value pass (`"password": "x"`, `PASSWORD=x`, `name: Jane` — `keyCategory` decides from the key) and a
  "long key-looking token" pass. The result is a JSON `{ "original": "[EMAIL_1]" }` in a second CodeMirror: the user edits,
  adds or deletes rows. **Mask text** replaces by exact text, longest key first, in one pass (a mask is never masked
  again; substring match, no word boundaries — "John" also hits "Johnson"), on the selection if there is one, else
  everything, one undo step. **Restore text** applies the JSON backwards (refused when two originals share a mask).
  Download / Load JSON move the mapping in and out; it is also remembered per tab for the session (`t.maskMap`), and
  **Scan** only ADDS entries (counters continue from the existing `[CAT_n]`). Heuristics are deliberately loose — cards
  need Luhn, IBANs mod 97, bare 10-digit phones only as Indian mobiles — and names/addresses are found only through
  their JSON/`key:` field; free text names are not detected (add them by hand).
- **Visualize** (`👁`, Ctrl+Shift+P, HTML tabs only): a live (300 ms debounce) `srcdoc` iframe beside the editor. The
  sandbox is EMPTY by default; "run scripts" adds `allow-scripts` only — never `allow-same-origin` (with scripts it would
  let a pasted page reach the Toolbox origin), and there is deliberately no "open in new tab" (a blob URL would be
  same-origin). It follows the active tab; closing/opening Compare switches it off.
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
6.7.2, merge 6.12.3, lint 6.9.7, lang-python 6.2.1, lang-sql 6.10.0, sql-formatter 15.9.0, @wasm-fmt/ruff_fmt 0.15.20
(1.09 MB bundle + 1.2 MB wasm). The install line above also needs `@codemirror/lang-python@6 @codemirror/lang-sql@6.10.0
sql-formatter@15.9.0 @wasm-fmt/ruff_fmt@0.15.20`; copy `node_modules/@wasm-fmt/ruff_fmt/ruff_fmt_bg.wasm` to `ui/vendor/`
too (and bump the `?v=` on its URL in `doFormat`).

<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: HTTP Methods & Status Codes — mounted at `/tools/http-methods-status/`

Entirely client-side — the Python backend (`http-methods-status/server.py`)
only serves the static page; both reference sets (methods, status codes)
are data arrays baked into the page.

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| Add/edit a method (examples, edge cases, best practices, mistakes)   | `http-methods-status/ui/index.html` — `METHODS` array |
| Add/edit a status code (meaning, when-to-return, examples, compare)  | `index.html` — `STATUS_CODES` array (grouped by `cls`) |
| Add/edit a Decision Guide question (either tab)                       | `index.html` — `METHOD_GUIDE` / `STATUS_GUIDE` arrays |
| Search/filter behavior                                                | `index.html` — `methodMatches()` / `statusMatches()` |
| Status class filter chips (1xx–5xx)                                   | `index.html` — `renderClassChips()` |
| Whether the backend does anything beyond serving the page             | `http-methods-status/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **The Decision Guide is the reason this tool exists, not a bonus
  feature.** It was built specifically to answer "which one do I pick"
  questions (PUT vs PATCH, 401 vs 403, 301 vs 308, 500 vs 502, etc.) — if
  you redesign this tool's layout, keep it prominent (open by default,
  above the searchable list), don't collapse it into an afterthought.
- **`compare` on a status-code entry is inserted as raw HTML, not
  escaped** (so it can bold the "vs NNN" lead-in) — every other field
  (`meaning`, `whenToReturn`, example notes) IS escaped via `escHtml()`.
  Only hand-written trusted text belongs in `compare`.
- **`compare` is deliberately sparse** — only set on the ~13 codes with a
  genuinely common real-world confusion, not added to every code for
  symmetry. Adding it everywhere would bury the comparisons that actually
  matter.
- **A method's `idempotent` field isn't always boolean** — PATCH uses the
  string `'Usually, not guaranteed'` because that's the honest, spec-
  accurate answer (idempotency there depends entirely on the patch
  document's semantics). `methodBadges()` already handles the
  string-vs-boolean split; don't assume boolean elsewhere.
- **No backend processing, intentionally** — same rationale as every
  other reference tool in this toolbox.
- Mounted at `/tools/http-methods-status/` by `main.py` — this folder is
  a fully self-contained ASGI app and doesn't need to know that.

# HTTP Methods & Status Codes — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

Two-tab reference: **Methods** (all 9 HTTP methods — GET through CONNECT)
and **Status Codes** (the full 1xx–5xx set, ~50 codes). Each entry has
plain-word meaning, multiple real-world examples, edge cases, best
practices, and common mistakes (methods) or "what it means when you get
it" vs "when to return it" plus similar-code comparisons (status codes).
Both tabs open on a **Decision Guide** — an architect-style Q&A answering
the comparisons that actually come up when designing an API (PUT vs
PATCH, 401 vs 403, 301 vs 308, 500 vs 502, etc.) — this is the feature the
tool exists for, not an afterthought; don't bury or shrink it.

## How it's built

- `server.py` — serves `ui/index.html` and nothing else, same as every
  other tool here.
- `ui/index.html` — single file, no build step. Three data arrays at the
  top of the `<script>` block are the entire content:
  - `METHODS` — one entry per HTTP method.
  - `STATUS_CODES` — one entry per status code, grouped by `cls`
    (`'1xx'`...`'5xx'`).
  - `METHOD_GUIDE` / `STATUS_GUIDE` — the two Decision Guide Q&A lists.
  Everything below the data is pure render/filter functions over these
  arrays — no fetch, no backend, no external dependencies.

## Where each feature lives

- Add/edit a method → `METHODS` array (each has `examples`, `edgeCases`,
  `bestPractices`, `commonMistakes` as separate arrays — keep them
  separate, don't collapse them into one blob, the UI renders each under
  its own heading).
- Add/edit a status code → `STATUS_CODES` array. `compare` is optional —
  only set it on codes with a genuinely common "which one do I pick"
  confusion (see the ones that already have it: 200, 301, 302, 308, 400,
  401, 403, 404, 409, 422, 429, 500, 503). Don't add `compare` to every
  code just for symmetry — it's supposed to flag the comparisons that
  actually matter.
- Add/edit a Decision Guide question → `METHOD_GUIDE` / `STATUS_GUIDE`.
- Search/filter logic → `methodMatches()` / `statusMatches()`.
- Status class filter chips (All/1xx/2xx/3xx/4xx/5xx) → `renderClassChips()`.

## Things that will bite you if you don't know them

- **`compare` strings may contain a literal `<b>` tag** (for bolding the
  "vs NNN" lead-in) and are inserted as raw HTML, not escaped — every
  other user-facing field (`meaning`, `whenToReturn`, example `note`s) IS
  escaped via `escHtml()`. If you add a new `compare` entry, only put
  trusted hand-written text in it (never anything derived from user
  input — there is none here, but keep the asymmetry in mind if this
  file's data model is ever extended).
- **Each status code lives in exactly one `cls` group** — the class-filter
  chips and the grouped rendering both key off `s.cls` matching one of
  `'1xx'`–`'5xx'` exactly; a typo there silently drops that code from its
  class group (it would still show up under "All" search results, just
  never under its own class filter).
- **`idempotent` on a method entry can be `true`, `false`, or a string**
  (PATCH uses `'Usually, not guaranteed'`) — `methodBadges()` only
  colors the badge green/gray for the boolean cases and falls back to a
  neutral warn color for a string value. Don't assume it's always boolean
  when reading this field elsewhere.
- **No backend processing, intentionally** — same rationale as every
  other reference tool in this toolbox (Encode/Decode, cURL Builder,
  Header Reference): nothing needs to leave the browser, there's nothing
  to look up server-side.
- Mounted at `/tools/http-methods-status/` by `main.py` — this folder is
  a fully self-contained ASGI app and doesn't need to know that.

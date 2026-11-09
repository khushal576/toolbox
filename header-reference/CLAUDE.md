# HTTP Header Reference — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A browsable, categorized glossary of widely-used HTTP headers — pick a
category (or search), click a header to expand its full explanation,
example, spec pointer, and related headers. No paste-and-analyze feature
by design (deliberately scoped out — see decision below); this is a
reference to browse, not an inspector to run your own traffic through.

## How it's built

- `server.py` — does exactly one thing: serves `ui/index.html`. No other
  routes, no request handling of any kind.
- `ui/index.html` — everything else. Single file, no build step, no
  external dependencies. Two parts:
  1. **`CATEGORIES` + `HEADERS`** — the entire glossary as plain data
     arrays at the top of the `<script>` block. This is where you add,
     correct, or re-categorize a header — never touch the render functions
     just to change content.
  2. **State + render functions** (`renderSidebar`, `renderResults`,
     `headerCardHtml`, `jumpToHeader`) — pure functions over `HEADERS` /
     `CATEGORIES` and the `state` object (search text, active category,
     side/status filters, which card is expanded). No fetch, no backend.

## Where each feature lives

- Add/edit a header → `HEADERS` array, grouped by category with a comment
  banner per category for quick scanning.
- Add/edit a category (and its plain-language definition, shown under the
  group heading in the results list) → `CATEGORIES` array.
- Search/filter logic → `matches(h)`.
- The "Related" chips that jump to another header (clearing filters,
  switching to All Categories, expanding and scrolling to it) →
  `jumpToHeader()`.
- Sidebar per-category counts → computed live in `renderSidebar()` from
  `HEADERS`, never hand-maintained — don't add a separate count field to
  `CATEGORIES`, it would drift out of sync.

## Things that will bite you if you don't know them

- **A header can only ever have ONE canonical entry in `HEADERS`,
  categorized once** — a header relevant to two categories (e.g. `Origin`
  matters to both Request Context and CORS) lives under the category that
  best explains its *primary purpose*, and gets cross-referenced via
  `related` from the other category's entries instead of being duplicated.
  Duplicating an entry would make search results show it twice and the
  sidebar counts lie.
- **`related` entries must be exact, case-sensitive matches of another
  header's `name` field** — `jumpToHeader()` does a plain `===` lookup, no
  fuzzy matching. A typo there silently does nothing when clicked (no
  error, the click handler just finds no header and returns).
- **`side` is `'request'` / `'response'` / `'both'` — not a free string.**
  The CSS badge classes (`.badge.side-request` etc.) and the sidebar
  filter chips both hardcode these three values; a fourth value renders
  with no badge color and never matches the filter chips.
- **`status` defaults to `'standard'` and only needs a badge for the other
  three** (`legacy`, `non-standard`, `deprecated`) — `headerCardHtml()`
  only renders a status badge when it's not `'standard'`, so a plain
  reference-grade header stays visually uncluttered.
- **This was deliberately scoped to browse-only, not paste-and-analyze.**
  The user was offered both up front and chose the glossary; a "paste your
  raw headers and get them explained" mode is a natural fast-follow if
  asked for later, but don't add it unprompted — it'd need its own parsing
  layer (splitting raw header text, matching names case-insensitively
  against `HEADERS`) that doesn't exist here yet.
- Mounted at `/tools/header-reference/` by `main.py` in the repo root —
  this folder never needs to know that; it's a fully self-contained ASGI
  app either way.

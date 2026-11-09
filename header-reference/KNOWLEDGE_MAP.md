<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: HTTP Header Reference — mounted at `/tools/header-reference/`

Entirely client-side — the Python backend (`header-reference/server.py`)
only serves the static page; the glossary itself is a data array baked
into the page, no lookups of any kind happen over the network.

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| Add, correct, or re-categorize a header                              | `header-reference/ui/index.html` — `HEADERS` array |
| Add/edit a category or its plain-language definition                 | `index.html` — `CATEGORIES` array |
| Search/filter behavior                                                | `index.html` — `matches()` |
| The "Related" cross-reference chips (jump to another header)         | `index.html` — `jumpToHeader()` |
| Sidebar per-category counts                                           | Computed live in `renderSidebar()` from `HEADERS` — never hand-maintained |
| Whether the backend does anything beyond serving the page             | `header-reference/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **No backend processing, intentionally** — same rationale as
  Encode/Decode and cURL Builder: nothing the user types (search text)
  needs to leave the browser, and there's nothing to look up server-side
  since the glossary is static data.
- **Deliberately scoped to browse-only, not paste-and-analyze.** The user
  was offered a choice between a browsable glossary, a paste-your-headers
  analyzer, or both — they chose the glossary alone. Don't add a
  paste-and-analyze mode unprompted; it needs its own header-text parser
  that doesn't exist here.
- **Each header has exactly one canonical entry, in exactly one
  category** — a header relevant to more than one category (e.g. `Origin`
  matters to both Request Context and CORS) lives under whichever
  category best explains its primary purpose, and is cross-referenced via
  `related` from the other category's entries instead of being
  duplicated. Duplicating an entry would double-count it in search
  results and in the sidebar's per-category counts.
- **`related` array entries are exact, case-sensitive header names** —
  `jumpToHeader()` does a plain equality lookup; a typo there just fails
  silently (click does nothing) rather than erroring.
- Mounted at `/tools/header-reference/` by `main.py` — this folder is a
  fully self-contained ASGI app and doesn't need to know that.

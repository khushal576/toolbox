<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Cookie Lab — mounted at `/tools/cookie-lab/`

No backend processing (`cookie-lab/server.py` only serves the static
page) — but unlike every other client-side tool here, this one is **not
purely static**. Its frontend performs real, persistent reads and writes
against `document.cookie`, a live browser API — a deliberate live
playground, not a generator (see the tool's own `CLAUDE.md` for the full
rationale; don't mistake this for a "no backend processing" violation).

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| The cookie-string builder / pre-click validation warnings             | `cookie-lab/ui/index.html` — `buildCookieString()` / `validateForm()` |
| How a Set Cookie attempt is diagnosed (accepted/rejected + why)       | `index.html` — `setCookieLive()` / `diagnoseOutcome()` |
| Parsing `document.cookie` into the live "Current Cookies" view        | `index.html` — `parseDocumentCookie()` / `renderCurrentCookies()` |
| The "Configured This Session" memory + delete actions                 | `index.html` — `configuredCookies` Map, `recordConfigured()`, `deleteConfigured()` |
| Suggested Experiments cards                                           | `index.html` — `EXPERIMENTS` array |
| Theory/reference content, categories                                  | `index.html` — `THEORY` / `THEORY_CATEGORIES` arrays |
| Decision Guide questions                                              | `index.html` — `COOKIE_GUIDE` array |
| Whether the backend does anything beyond serving the page             | `cookie-lab/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **`Secure` will likely still succeed on `http://localhost:8000`, not
  get rejected** — browsers treat `localhost` as a trustworthy origin
  regardless of scheme, which is what the Secure check actually verifies.
  The tool's copy reflects this as an honest live diagnosis, not a
  canned "rejected" assumption — don't "correct" it to claim rejection.
- **`HttpOnly` set via `document.cookie` drops the ENTIRE write, not just
  that flag.** The checkbox stays enabled on purpose so the user can
  trigger and observe this, rather than being grayed out.
- **`Path` is validated differently than `Domain`** — an unrelated Path
  is never rejected at set-time, only invisible from documents whose
  path doesn't match it; `Domain` IS actively validated and can be
  rejected outright. Copy throughout keeps this distinction precise.
- **The "delete with wrong Path" demo deliberately omits `Max-Age`**
  rather than using `Max-Age=0` — a `Max-Age=0` write to a path with no
  existing cookie is a silent, invisible no-op that teaches nothing; the
  real classic bug (a second, visible, empty-valued sibling cookie
  appearing instead of a clean delete) requires the write to actually
  persist, which needs no expiry at all.
- **No true cross-subdomain `Domain` demo is possible** — this tool is a
  single page on a single host; genuinely testing subdomain-sharing
  behavior needs two real subdomains, which this deployment doesn't
  have. That stays theory-only, stated explicitly in the Reference tab.
- **jsdom (used during this tool's development) is not faithful for**:
  the localhost-Secure exception, `SameSite=None`-requires-`Secure`
  enforcement, HttpOnly's whole-write-drop behavior, `__Host-`/
  `__Secure-` prefix enforcement, and the ~4KB size limit (confirmed
  directly — a 5KB value round-tripped successfully under jsdom, where a
  real browser would drop it) — its `tough-cookie`-backed jar doesn't
  model these browser-specific behaviors. Changes touching them need
  manual verification in a real browser against the running deployment.
- Mounted at `/tools/cookie-lab/` by `main.py` — this folder is a fully
  self-contained ASGI app and doesn't need to know that. Its default
  cookie Path is `location.pathname` (not a hardcoded `/tools/cookie-lab/`)
  for the same relative-path reason every tool's own API calls use
  relative paths — see the root `CLAUDE.md`.

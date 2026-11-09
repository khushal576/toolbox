# Cookie Lab — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A live `document.cookie` playground (not a generator — it actually
sets/reads/deletes real cookies for this page's origin) plus a full
theory/reference section and a Decision Guide. Two tabs: **Playground**
(every cookie attribute exposed as a live control, a "Current Cookies"
view reading `document.cookie` in real time, a "Configured This Session"
view tracking what attributes YOU asked for, and a flat list of
Suggested Experiments) and **Reference** (categorized theory glossary +
architect-style Q&A). Deliberately NOT a locked slideshow — the owner
explicitly rejected a guided flow in favor of "provide all options and I
do and check" — every control is visible and usable in any order.

## The one real architectural deviation from every sibling tool

Every other reference tool in this toolbox (`header-reference`,
`http-methods-status`, `encode-decode`) is **purely static**: their
frontend only ever renders a fixed data array, a pure function of its own
render state. **This tool is different: its JS performs real reads and
writes against `document.cookie`, a live, persistent, stateful browser
API.** Those writes genuinely create/modify/delete cookies scoped to this
origin, visible to the browser (and any other tab open on
`/tools/cookie-lab/`) until they expire or are explicitly deleted —
exactly like any other website's cookies would behave.

This is still "no backend processing" in the repo-wide sense —
`server.py` serves one static file and nothing else, no request ever
reaches Python except that one initial page load. The deviation is
entirely client-side: this is the first tool here whose frontend has
side effects that outlive the page itself. **Do not "fix" this by
routing cookie operations through a backend endpoint** — that would be a
regression, not an improvement. A live playground was the owner's
explicit choice over a pure string-generator when this tool was designed
(see the plan this tool was built from).

## Where each feature lives (inside `ui/index.html`'s script)

- `buildCookieString(form, opts)` / `validateForm(form)` — pure functions,
  no DOM. `buildCookieString` builds exactly what `document.cookie` would
  receive; pass `{forceHttpOnly: true}` only for the read-only "what a
  server would send" preview, never for an actual write (JS categorically
  cannot produce a working HttpOnly cookie — see below).
- `parseDocumentCookie()` — the only place `document.cookie` is read and
  split into `{name, raw, value}` entries. Handles duplicate names (two
  cookies sharing a name at different paths both appear, space-separated,
  in `document.cookie`) as an array, not a map — don't "simplify" this
  into an object keyed by name, you'll silently drop the duplicate-name
  edge case the "wrong-Path delete" experiment deliberately produces.
- `setCookieLive(form)` — the one function that actually writes
  `document.cookie`, then diffs before/after via `diagnoseOutcome()` to
  report what really happened, never an assumed outcome.
- `configuredCookies` (a `Map`) — the playground's own memory of what
  attributes it asked for per cookie, separate from and contrasted
  against `parseDocumentCookie()`'s live truth in `renderConfigured()`.
  This exists specifically because JS can never read a cookie's own
  attributes back from the browser — see the Reference tab entry of the
  same description.
- `deleteConfigured(key, mode)` — `'correct'` re-sends with the exact
  original Name+Domain+Path and `Max-Age=0`. `'wrong-path'` deliberately
  reproduces the REAL classic bug: re-sending with a *different* Path and
  **no expiry at all** (not `Max-Age=0`) — a `Max-Age=0` write to a path
  that never had a cookie is a silent no-op and teaches nothing visible;
  omitting the expiry instead creates a second, visible, empty-valued
  cookie with the same name, which is the actual mess this bug produces
  in the wild. Don't "clean up" `wrong-path` to use `Max-Age=0` — it would
  stop demonstrating anything.
- `EXPERIMENTS` — each has a `setup` object merged onto `defaultForm()`
  (never onto whatever's currently in the form) so every experiment is
  reproducible from a clean baseline, and an `expect` string describing
  the outcome honestly, including the localhost-Secure exception (see
  below) — never a canned "this will be rejected" for cases where it
  won't be.
- `THEORY` / `THEORY_CATEGORIES` / `COOKIE_GUIDE` — ported, same shape
  and same render functions (`renderRefSidebar`, `refMatches`,
  `theoryCardHtml`, `jumpToTheory`, `renderGuide`), as `header-reference`'s
  `HEADERS`/`CATEGORIES` and `http-methods-status`'s decision guide.

## Things that will bite you if you don't know them

- **`Secure` will likely still succeed on `http://localhost:8000`, not
  get rejected.** Browsers treat `localhost` as a "potentially
  trustworthy origin," which is what the Secure check actually verifies
  — not literally "is this HTTPS." `isTrustworthyHost()` and the
  info-level (not warning-level) note in `validateForm()` reflect this
  on purpose. Don't "fix" the copy to claim Secure gets rejected here —
  it's the opposite of what actually happens, and the whole point of the
  Suggested Experiments entry for this is to surface that surprise.
- **`HttpOnly` checked in the form drops the ENTIRE cookie write, not
  just that one flag**, when the resulting string is assigned to
  `document.cookie`. The HttpOnly checkbox stays enabled (not disabled)
  specifically so the user can check it and click "Set Cookie" anyway and
  watch nothing get stored — that's the demonstration, not a bug to
  prevent by graying out the control.
- **`Path` is never rejected at set-time, only invisible from documents
  whose path doesn't match it** — unlike `Domain`, which the browser
  actually validates and can reject. Copy throughout this tool is
  written to keep that distinction precise; don't lump Path into the
  same "accept/reject" framing as Domain.
- **True cross-subdomain `Domain` behavior can't be demonstrated live** —
  this whole tool runs on one page at one host. The Reference tab entry
  "Cross-Subdomain Behavior Can't Be Demonstrated on a Single Page" says
  so explicitly; don't try to fake it with `document.domain` tricks or
  similar — that would misrepresent what a real cross-subdomain test
  would show.
- **jsdom (used to verify this tool during development) is NOT faithful
  for the localhost-Secure exception, `SameSite=None`-requires-`Secure`
  enforcement, HttpOnly's whole-write-drop behavior, `__Host-`/
  `__Secure-` prefix enforcement, or the ~4KB size limit** — its cookie
  jar (`tough-cookie`) does not model the browser-specific trustworthy-
  origin carve-out, may not implement the newer prefix rules, and (
  confirmed directly, not just suspected) does not enforce any size
  ceiling at all — a 5KB value was written and read back successfully
  under jsdom in a version where a real browser would drop it entirely.
  Any change touching those behaviors needs manual verification in a
  real browser against the actual running deployment, not just a passing
  jsdom test. Everything else this tool does (Domain-mismatch rejection,
  Path-prefix visibility, the additive-not-replacing nature of
  `document.cookie`, Max-Age=0 deletion, and the wrong-Path-delete bug
  producing a visible duplicate cookie) WAS confirmed to behave correctly
  under jsdom's real cookie jar during development — see the scratch test
  this tool was built against if you need to re-verify after a change.
- Mounted at `/tools/cookie-lab/` by `main.py` — this folder never needs
  to know that; it's a fully self-contained ASGI app either way. Note
  that `defaultForm()`'s `path` defaults to `location.pathname` for
  exactly the reason the root `CLAUDE.md` requires relative API paths
  elsewhere in the repo: it must behave correctly whether mounted under
  `/tools/cookie-lab/` or served from `/` in a standalone dev run.

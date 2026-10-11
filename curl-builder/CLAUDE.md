# cURL Builder — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A form-based curl command generator — pick method/URL/query params/auth/
headers/body/cookies/flags, and it builds a copy-pasteable `curl` command
for bash/zsh, cmd.exe, or PowerShell, with correct quoting for each.

**Second pass: it can now also actually run the request and show the real
result** (owner's explicit ask, reversing this tool's original "no backend
processing" decision — see "Why the no-backend decision was reversed"
below), save the built request or a result into the shared Vault for
reuse, repeat a request N times, and give any query/header/cookie/form
field a list of values to run every combination of (with the ability to
select only specific combinations before actually running them). The
original command-generation feature is completely unchanged — Run is an
addition, not a replacement.

## Why the no-backend decision was reversed

This file used to say, flatly: *"If you're tempted to add a 'send this
request for me' endpoint, don't — that would turn this into an open SSRF
proxy. This tradeoff needs the owner's sign-off to reverse, not a silent
addition."* The owner explicitly asked for exactly that — "can hit curl
actually and see result" — so this is that sign-off being exercised, not
skipped. The reasoning that made the original decision correct hasn't
changed (a backend that issues arbitrary outbound requests on command IS
a real SSRF surface); what changed is the trust context: this toolbox
already extends the same trust to SQL Studio's live DB connections and
DataFrame Studio's unsandboxed `custom_code` — a single trusted local
user running this on their own machine, not a multi-tenant service. Run
fits the same posture, deliberately bounded rather than wide open:

- **Per-request timeout**: default 30s, capped at 120s server-side
  regardless of what the client sends (`core/http_exec.py`'s
  `MAX_TIMEOUT_S`).
- **Response size cap**: 10MB, enforced by streaming and cutting off
  mid-read — never buffers an unbounded response in memory (same "never
  load unbounded data" discipline as Duck Lab/Vault). Truncation is
  flagged visibly in the result, never silent.
- **Requests-per-click ceiling**: 200, enforced client-side before any
  request fires (`MAX_REQUESTS_PER_RUN` in `ui/index.html`) — covers
  both the repeat-count field and the cartesian-combination count
  together, so neither path can quietly add up to something unbounded.
- **No IP/localhost blocking, deliberately** — hitting your own local or
  internal APIs (a dev server, an internal service with no public DNS)
  is an explicit, primary use case for this feature, not something to
  silently prevent. If this tool is ever exposed beyond one trusted
  local user, that decision needs revisiting before anything else does
  — same caveat df-studio/CLAUDE.md already states for `custom_code`.

## How it's built

- `server.py` — serves `ui/index.html`, plus one real route:
  `POST /execute`, a thin wrapper around `core/http_exec.py`'s
  `execute_request()`. This is the ONLY backend route in this tool that
  touches the request itself — Format/Templates-equivalent generation
  (the copyable command string) is still 100% client-side, unchanged.
- `core/http_exec.py` (shared, not tool-local — see root `CLAUDE.md`'s
  "Shared connectors" section) — the bounded, streaming, async HTTP
  executor. Lives in `core/` rather than inlined here because "make an
  outbound HTTP call safely" is a genuinely reusable primitive, same
  lesson as `core/db/`'s `Dialect` abstraction.
- `ui/index.html` — everything else, still one file, no build step.
  - `generate()`/`assemble(shell)` — **completely unchanged**, still the
    one function that builds the shell-quoted copyable command.
  - `assembleRequest()` — a deliberately SEPARATE, independent function
    (not a refactor of `generate()`) that reads the same form state into
    a plain, unquoted `{method, url, headers, body, canRun, blockedReason}`
    object for Run to consume. Kept independent on purpose: `generate()`
    was already working and verified; growing a second consumer off a
    shared extraction would risk regressing it for no real benefit,
    since both are just read-only views over the same DOM state anyway.
  - `makeRowList(...)`'s rows gained `listMode`/`listValues` — a 📋
    toggle per row (query params, headers, cookies, urlencoded fields;
    NOT multipart, which is excluded from Run entirely, see below) swaps
    the single value `<input>` for a newline-separated `<textarea>`.
  - `activeListAxes()` / `cartesianCombinations()` — pure functions,
    find every list-mode row with real values and compute their full
    cartesian product. `cartesianCombinations([])` returns one empty
    combo (meaning "nothing varies"), which is what makes the plain
    repeat-N-times path and the combination path share one execution
    loop in `btnRun`'s handler instead of needing two.
  - `executeOnce()` / `btnRun`'s handler — the actual run loop.
    Sequential, not concurrent (one request awaited at a time) — gives
    live incremental results as they land, same "show progress, don't
    freeze" standard applied to Duck Lab/Vault this session.
  - Save/Load request and Save-result-to-Vault all call
    `/tools/vault/secrets` directly from the frontend — same-origin,
    same pattern SQL Studio/Schema Map's "Save connection" already uses
    (see `schema-map/CLAUDE.md` Phase D for the precedent).

## Run's scope — what it supports, and what it deliberately doesn't

**Supported**: body types `none`/`raw`/`graphql`/`urlencoded`; auth types
`none`/`basic`/`bearer`/`apikey`.

**NOT supported, by necessity not oversight — `canRun`/`blockedReason`
in `assembleRequest()` disable the Run button with a clear message**:
- **Multipart and Binary bodies.** Both can reference a file by a typed
  local path (the multipart "File" toggle, the Binary body's file
  path) — this tool's own long-standing design is that these are just
  text inputs, never real file uploads (`ui/index.html`'s file fields
  read a path string, nothing more; see the existing "File fields are
  just typed paths, not uploads" note below). A browser-based tool
  genuinely cannot read an arbitrary local file from a typed path
  string — there's no way to execute these short of adding a real file
  picker and a multipart-encoding path, which was judged not worth the
  complexity for v1. Copy the command and run it in a real terminal
  instead; the generated command itself is completely unaffected.
- **Digest auth.** A real implementation needs a server challenge
  round-trip (the server replies 401 with a `WWW-Authenticate` header
  containing a nonce, and the real request is re-sent with a computed
  response hash) — not a single static header computable upfront the
  way Basic/Bearer are. Out of scope for v1; same "copy the command
  instead" fallback.
- These three are the ONLY blocked cases — every other combination
  (including list-mode/combinations) is fully supported.

**Saving a result to Vault uses the plain whole-value path
(`save_secret()`), not the chunked `save_dataset()` path** SQL Studio's
full-export feature uses — a deliberate simplification, not a copy-paste
miss: `core/http_exec.py` already caps every response at 10MB, so the
unbounded-size problem `save_dataset()`'s chunking exists to solve
doesn't apply here. If that cap is ever raised significantly, revisit
this.

## Things that will bite you if you don't know them

- **Multipart bodies must never get a manual `Content-Type` header.**
  Unchanged from before — curl sets its own with the multipart boundary.
- **Form URL-Encoded body does *not* get an explicit `Content-Type`
  header in the COMMAND** (curl adds it automatically for
  `--data-urlencode`) — but `assembleRequest()`'s own Run path DOES set
  `application/x-www-form-urlencoded` explicitly, since there's no curl
  binary involved to add it implicitly when going through `/execute`.
  These two code paths intentionally differ here; don't "fix" one to
  match the other.
- **File fields are just typed paths, not uploads — now also the exact
  reason Run is blocked for those body types.** The path the user types
  must exist on whatever machine runs the *generated command*; this
  page never reads real files from the browser, for the copyable
  command OR for Run.
- **List-mode fields show only their FIRST value in the copyable
  command** — `generate()` was deliberately left untouched rather than
  taught to understand list mode, so a list-enabled row's `.value`
  (never cleared, just hidden behind the textarea while list-mode is
  on) is what the command string still uses. A warning is shown
  ("N fields are in list mode...") so this isn't a silent surprise.
- **`btnRun`'s handler temporarily mutates row `.value`s while iterating
  combinations, then restores them in a `finally` block** — if you add
  a new way to exit that loop early, make sure the restore still runs
  (it's in `finally` specifically so a thrown error can't leave the form
  showing some mid-run combination's value instead of what was actually
  typed).
- **Only bash/zsh, cmd.exe, and PowerShell are supported targets** for
  the copyable command. If a fourth is ever added, it needs its own
  entries in both `quote()` and `contJoiner()`.
- Mounted at `/tools/curl-builder/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way.

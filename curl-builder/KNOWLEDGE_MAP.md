<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: cURL Builder — mounted at `/tools/curl-builder/`

Builds a copy-pasteable curl command — AND can now actually run it and
show the real result, reversing this tool's original "no backend
processing" decision on the owner's explicit ask (see its own
`CLAUDE.md`'s "Why the no-backend decision was reversed" for the full
reasoning and the concrete safety bounds: timeout, 10MB response cap,
200-requests-per-click ceiling). The command-generation feature itself
is still 100% client-side and completely unchanged.

| If you need to change...                                            | Go to |
|---------------------------------------------------------------------|-------|
| Anything about the form fields (method, URL, auth, body, headers, cookies, flags) | `curl-builder/ui/index.html` — the relevant `<div class="card">`/`<details>` block |
| The generic dynamic key/value row list (used by query params, headers, cookies, urlencoded + multipart body fields, now also list-mode via `listMode`/`listValues`) | `index.html` — `makeRowList(...)` |
| Shell-specific quoting/escaping (bash, cmd.exe, PowerShell)          | `index.html` — `quote()` and `contJoiner()` |
| How the final curl command string is assembled from form state      | `index.html` — `generate()` / `assemble(shell)` (unchanged) |
| Which manual headers get silently overridden by Auth/Body settings  | `index.html` — `autoHeaderKeys` inside `generate()` |
| Assembling the UNQUOTED request object Run actually sends (separate from the command-string builder above) | `index.html` — `assembleRequest()` — see its own scope note (`canRun`/`blockedReason`) for what's NOT supported (multipart/binary bodies, Digest auth) |
| Actually issuing the HTTP request | `curl-builder/server.py`'s `POST /execute` → `core/http_exec.py`'s `execute_request()` (shared, bounded async HTTP client — timeout + streaming response cap) |
| Multi-value fields → cartesian product → selective run | `index.html` — `activeListAxes()`, `cartesianCombinations()`, `btnGenerateCombos`/`btnComboAll`/`btnComboNone`, the `btnRun` handler |
| Saving/loading the built request, or saving a result, via the shared Vault | `index.html` — `snapshotFormState()`/`applyFormState()` (`kind: "curl_request"`), `saveResultToVault()` (`kind: "curl_result"`) — direct same-origin calls to `/tools/vault/secrets`, same pattern as SQL Studio/Schema Map's saved connections |

### Known non-obvious behavior

- **The no-backend-processing decision was deliberately reversed, not
  quietly bypassed** — see `curl-builder/CLAUDE.md` for the full
  reasoning and the bounds now in place. Don't reverse it FURTHER
  (e.g. remove the timeout/size/count caps) without the same
  explicit re-raising this already went through once.
- **`assembleRequest()` is a second, independent read of the form state
  — not a refactor of `generate()`.** The two intentionally never share
  code, to keep zero regression risk to the already-working copyable
  command feature.
- **Run does not support multipart/binary bodies or Digest auth** — all
  three need something a browser-based tool genuinely can't do (read a
  local file by path, or a server challenge round-trip) — `canRun`/
  `blockedReason` disable the Run button with a clear message rather
  than silently sending something wrong. Not a gap to "complete" without
  a real design discussion (a real file picker + multipart encoding, or
  a real Digest challenge-response implementation).
- **List-mode fields show only their first value in the copyable
  command** — `generate()` was deliberately left untouched; a warning
  ("N fields are in list mode...") makes this visible, not silent.
- **Multipart bodies must never carry a manual `Content-Type` header** —
  curl sets its own with the boundary; the generator already strips a
  manual one and shows a warning, don't remove that guard.
- **File fields are typed paths, not real uploads.** The browser never
  reads the file; the path only needs to exist on whatever machine
  actually runs the generated command — now also the exact reason Run
  is blocked for multipart/binary bodies.
- Mounted at `/tools/curl-builder/` by `main.py` — this folder is a fully
  self-contained ASGI app and doesn't need to know that.

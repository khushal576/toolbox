# Key Store (`key-store/`, package `key_store`) — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.

Created from `tools/_template` on 2026-11-22 (roadmap P2), built in numbered steps KS1–KS4 (owner rule: **one step at a time**, the owner tests each before the next). **Keep this file current as steps land.**

## What it is
The owner's single place for **generating strong passwords** and (from step KS2) **storing and searching keys, URLs, connection strings, hosts and passwords** with one-click copy, replacing loose txt files that get lost.
It deliberately does NOT build its own secret store: saved entries go into the existing Vault (`vault_store.scoped("key-store")`, Fernet, key in `.env`), under their own `kind` so they never mix with database connections.

**Owner decisions (2026-11-22):** name "Key Store"; Vault database connections stay in the Vault tool (not mixed in); the optional master-passphrase lock is a later, separate step (if forgotten, entries are lost — decide then).

**Steps:** KS1 scaffold + generator ☑ · KS2 save / list / search / copy (Vault, tags, type, prod/non-prod label, masked values, 30-day trash) ☑ · KS3 import from messy txt (`KEY=value`, `key: value`, bare URLs, with a preview) + encrypted export / `.env` export ☐ · KS4 extras (last 5 old values, clipboard auto-clear, "copy as", health check, expiry reminders) ☐.

## How entries are stored (KS2)
- Vault `kind` = `key_store`; manifest `vault: {read: [key_store], write: [key_store]}` — **only its own kind**. Runtime is `data` (the light runtime has no encryption library, so it cannot reach the Vault).
- Vault `name` column = `ks-<random>`: that column is **not encrypted**, so the real name lives inside the encrypted JSON (`name, value, type, tags, note, environment, pinned, last_used, trashed_at`). Side effect: the Vault page shows these as `key_store · ks-…`.
- Lists (`GET entries`) never contain a value. A value leaves the server only via `GET entries/{id}` (edit form, 👁 reveal, masked again after 10 s) and `POST entries/{id}/copy` (clipboard; also records `last_used`).
- A row shows a value without the eye only when `store.safe_preview` says it is clearly not a secret (a `host`, or a `url` with no user-info/query/long token in its path). Webhook-style URLs stay masked.
- Search matches name, tags, type, note, environment (all words must match; name matches rank first). "Also search inside values" decrypts on the server and never returns the value.
- Delete = trash (30 days, `trashed_at` in the data, purged lazily on the next list) → "Delete forever" uses `ScopedVault.delete_secret` (added in KS2 to `core/vault.py`: allowed only for kinds in the plugin's `write` list; datasets refused).
- Names are unique ignoring case among non-trashed entries; restoring into a taken name renames to "… (restored)".
- **No `ai:` section in the manifest and no `postMessage` from the page: the AI helper / MCP can never see or call this tool** (tests enforce both, and that `mcp_server/vault_scope.yaml` never lists `key_store`).

## Where things live
| Concern | File |
|---|---|
| The ASGI app: pages/scripts, `/health`, the entries API (maps HTTP to `store.py`), strict CSP (`connect-src 'self'`), `no-store` on every response | `server.py` |
| Entries logic (pure; takes a scoped Vault): validation, search/rank, trash, previews | `store.py` |
| Page shell, styles, entry dialog, tab switching | `ui/index.html` |
| Generator page code (options, rendering, copy, "Save to Store…" event) | `ui/generator.js` |
| Store tab (search, copy, reveal, edit form, trash) | `ui/store.js` |
| Generator logic, no DOM (CSPRNG + rejection sampling, entropy, crack-time words) | `ui/keygen.js` |
| EFF Large Wordlist (7776 words, CC BY 3.0 US — keep the credit header) | `ui/words.js` |
| How it is mounted (runtime data, state durable, order 25, vault scope) | `manifest.yaml` |

## Rules for this tool (repo-wide rules are in `../CLAUDE.md`)
- Runtime `data` (needs the Vault); the package name `key_store` is unique — never rename it without updating the Dockerfile `COPY`/`touch` lines.
- The page calls the API with **relative paths**, through the single `api()` helper in `store.js` (a test enforces one `fetch(`, no absolute URLs). `keygen.js` / `generator.js` make no network calls at all.
- **A value is never put in HTML, a URL, `localStorage`, the console or a `postMessage`** (tests scan all page code). `localStorage` holds only `keystore.genopts` (generator options) and `keystore.tab`.
- No request depends on this process's memory; persistent state goes to `core/state/`. Secrets only via `vault_store.scoped("key-store")` with the kinds declared in the manifest.
- Every endpoint that touches outside systems needs a smoke/unit test that does not need them (fakes).

## Gotchas
- **Randomness:** only `crypto.getRandomValues` through `KeyGen.randInt` (rejection sampling). A unit test fails on `Math.random`. Never "simplify" `randInt` to `x % n` (modulo bias).
- Strength numbers are entropy of the *generator's choice space*, an honest upper bound for a random value; "time to crack" assumes 10 billion guesses/second and a fast hash (worst case). A PIN is always instant offline: the page says so.
- "Safe for connection strings and URLs" limits symbols to `- _ . ~` because `@ : / ? # % & =` break connection strings.
- `words.js` is 60 KB; do not edit it by hand. If the list ever changes, update `key_store_keygen_cases.js` (it pins first/last word and the count).
- Adding a file under `ui/` ships automatically (the Dockerfile copies the folder) but needs a route in `server.py` AND an entry in `SCRIPTS` to be served. Adding a new Python file next to `server.py` needs its own `COPY` line in the Dockerfile (done for `store.py`).
- `server.py` loads `store.py` as `key_store.store` in the image and by path in a checkout (the folder `key-store/` is not importable); tests that patch `get_store` must use `server.store.KeyStore` so exception classes match.
- The Vault has no rename: the name is inside the encrypted data, which is also why renaming works.

## Tests
- `tests/unit/key_store_keygen_cases.js` (run by `tests/unit/test_key_store.py`, needs `node`): generator uniformity, rejection sampling, every option, entropy, word list integrity.
- `tests/unit/test_key_store.py`: no `Math.random`; generator code makes no network calls; the Store page talks only to its own API; no HTML building / console / storage of values / `postMessage`; security headers; routes.
- `tests/unit/test_key_store_store.py`: against a real temporary Vault: encrypted at rest (names too), lists never hold values, validation, search + ranking, previews, trash/expiry/restore, scopes (MCP and other tools cannot read or delete these entries), the HTTP layer.
- `tests/unit/test_key_store_ui.py` (+ `key_store_ui_driver.js`): the real page in headless Chromium on a temporary Vault, ~45 checks (needs chromium; skips without).
- `tests/smoke/test_key_store.py` (live, via `scripts/smoke.sh`) and the `API_CHECKS` line in `tests/smoke/test_api.py`.

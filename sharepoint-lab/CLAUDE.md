# SharePoint Lists — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and `../KNOWLEDGE_MAP.md` (section
"Tool: SharePoint Lists") for the symptom→file map.

## What this tool is

Connect many SharePoint sites at once (several connections, several sites each), browse every list with ALL its columns
(internal vs display name, type, required/read-only/hidden/system, choices), edit cells or add items in a grid — or stage
edits from a notebook with Python — and write them to SharePoint **only after a review screen shows exactly what changes
(old → new) and the owner approves**. Owner decisions (2026-10-30): Microsoft **Graph** API; approval before any write;
**no destructive operations — no delete, ever**.

## Where things live

| Concern | File |
|---|---|
| Token for a connection: client-secret (app-only) or device-code (delegated, refresh token kept in the Vault) | `auth.py` |
| Graph client: paging, retry/throttling, `$batch`, the "no delete" write guard | `graph.py` |
| Column types → what is editable, coercion/validation, "same value?", Graph payloads | `columns.py` |
| Connections (Vault), browsing, staging, review digest, apply with conflict check, rebase, CSV export | `service.py` |
| Staged edits + audit trail (Postgres schema `sharepoint_lab`, SQLite standalone) | `store.py` |
| API | `server.py` |
| Page (no framework) | `ui/index.html` |
| Python in a notebook: `import toolbox_sharepoint as sp` (read → DataFrame, edit, `sp.stage(df)`) | `../notebook-lab/lib/toolbox_sharepoint.py` |
| Fake Microsoft sign-in + Graph; a dev server to try the page without a tenant | `../tests/unit/fake_graph.py`, `../tests/unit/sp_dev_server.py` |

## The write path (every rule is tested in `tests/unit/test_sharepoint.py`)

1. **Editing only stages.** `PUT /staged` validates the value (`columns.coerce`) and stores `{field: {old, new}}` in our own
   database. UI edits and Python (`/staged/bulk`) land in the same rows (`source` = ui | python).
2. **Review** (`GET /staged`) re-validates everything and returns a **digest** of exactly what it shows.
3. **Apply** (`POST /apply`) needs that digest — if anything was staged/changed since, it answers 409 and the page reopens the
   review. It refuses on a read-only connection. Then, per row: re-read the item **now**; if a field differs from the staged
   `old` someone else changed it → **conflict, the row is skipped** (never overwritten; stays staged; "Refresh old values"
   = `/staged/rebase`); if SharePoint already has the new value → unchanged. The rest is written in `$batch` groups of 20,
   the stored value is read back (shown as "stored: …", flagged if it differs), every field goes to `audit`, applied rows
   are un-staged. One failing row never stops the others (423 locked, 404 gone, throttled sub-requests are retried).
4. **No delete:** `graph.py` has no delete method and `_check_write` refuses anything except GET, `PATCH …/items/{id}/fields`,
   `POST …/items` and `POST /$batch` (sub-requests checked too). `store.delete_rows` only removes OUR staged rows.
   A test asserts the fake Graph never sees a DELETE/PUT. Don't add one without the owner asking.
5. A paging link (`@odata.nextLink`) is only followed when it is on the same Graph host.

## Connections (Vault kind `sharepoint_connection`)

Saved from the page's "+" dialog (the Vault page lists/deletes them like any secret). Two sign-in methods:
- **Sign in as me (device code)** — tenant and client id are OPTIONAL: left empty they default to tenant `organizations` and
  Microsoft's public "Microsoft Graph Command Line Tools" app (`auth.PUBLIC_CLIENT_ID`), so a person with only a username and
  password needs no app registration (the password is typed on Microsoft's page, never here; ROPC/password grant is deliberately
  not supported — it fails with MFA). A tenant may still demand admin consent for that app. With your own registration: Entra app registration with *Allow public client flows = Yes* and the **delegated** Graph
  permission `Sites.ReadWrite.All` (or `Sites.Read.All` for a read-only connection — a read-only connection asks for the
  read scope only). Tenant id = Directory (tenant) id, client id = Application (client) id. Edits are attributed to the
  person and limited to what they may do. The refresh token is stored in the Vault entry (manifest grants `write` for that).
  Changing read-only ↔ read-write clears it (different scope: sign in again).
- **App secret** — app registration + client secret + the **application** permission `Sites.Selected` (an admin then grants
  the app access to each site) or `Sites.ReadWrite.All`. Edits show as the app. "Read-only" is enforced by the tool (an app
  role can't be down-scoped).
`cloud` = global / us_gov / china. Site URLs: `https://contoso.sharepoint.com/sites/Team` (anything after the site name is dropped).
Pending device-code sign-ins live in Redis (`sharepoint-signin`, 15 min) so any web worker can answer the poll.

## Things that will bite you

- **Not verified against a real tenant** — built and tested against `fake_graph.py` (written from the Graph docs). First real
  use: try a read-only connection on a test list, then one edit. Things most likely to differ: date-only columns,
  `$expand=fields($select=…)` on a single item, multi-choice detection (`displayAs: checkBoxes`), column `readOnly` flags.
- **Dates** travel as UTC instants (what Graph returns). The page shows/edits date-only columns in the BROWSER's time zone
  (local midnight ↔ UTC), assuming the site is in the same zone. A bare `2026-10-30` sent from Python means UTC midnight.
  The "stored: …" line after a write shows what SharePoint really kept.
- **Only plain columns are editable** (text, note, number, currency, yes/no, date, datetime, choice incl. multi). Lookup, person,
  link, calculated, managed metadata, location, image, approval status and every system column are shown (lookups/people as
  `#<id>` — the tool does not resolve ids to names yet) but read-only.
- Internal vs display names: a column's data key is its internal name (`Project_x0020_Name`); lookups/people are `<name>LookupId`
  (`columns.key_of`). The schema dialog shows both.
- Lists over 5,000 items: items are paged by Graph's cursor (not filtered server-side), so this works; the page's filter and
  sort are over the rows loaded so far (auto-loads on scroll, cap 50,000 for "load all", 3,000 rendered).
- Per-process caches (schema 2 min, lists 2 min, access tokens) are rebuildable; no request depends on process memory.
- **The Python bridge is not an authentication boundary.** The notebook kernel gets only `SP_BRIDGE_URL` (no token) and can
  read lists and STAGE; but the Toolbox has no login, so any HTTP client on the network — including a kernel — could also call
  `/apply` with a digest it fetched itself. The review screen is the intended gate, not a security control. Keep it in mind
  before running notebooks you don't trust (they already can reach every other Toolbox endpoint).
- Staged edits are per connection+list, shared by everyone using the Toolbox (single owner).

## Testing

`tests/unit/test_sharepoint.py` (68 tests, no network): run in the data image —
`docker run --rm -v $PWD/tests:/app/tests:ro -v $PWD/sharepoint-lab:/app/sharepoint_lab:ro -v $PWD/notebook-lab:/app/notebook_lab:ro -w /app toolbox-rt-data sh -c "pip install -q pytest; python -m pytest tests/unit/test_sharepoint.py -q"`.
To click through the page without a tenant: `tests/unit/sp_dev_server.py` (docstring has the command; two seeded connections).

## Not done yet (ideas, not promises)

Resolve lookup/person ids to names and edit them; hyperlink editing; document libraries/files; "Mirror to Vault Data" (so
DuckDB/DataDiff can join lists); delta sync for very large lists; staging new rows from Python; a certificate credential for app-only.

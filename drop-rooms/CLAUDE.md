# Drop Rooms (`drop-rooms/`, package `drop_rooms`) — tool-local notes

> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log · design and threat model: `../docs/architecture/ADR-DROP-ROOMS.md`. Do not change anything outside this tool's folder unless the task says so.

Built in numbered steps DR0–DR5 (owner rule: **one step at a time**, the owner tests each before the next).

## What it is
Discord-style **rooms with a key** for dropping text, **files and folders (≤ 100 MB each)** between devices or people. Everyone who joins a room with its key sees everything in it. Every item expires (5 s to **30 days max**, page presets 1 h–30 d, default **6 h** per room) and is invisible to everyone the moment it does. Anyone in a room may edit or delete anything (delete is immediate for all, 10 s Undo for the deleter, real erasure 20 s later).
It deliberately does NOT have accounts, a "never delete" option, or any AI access.

**Owner decisions (2026-11-22):** name "Drop Rooms"; per-room key; ≤ 100 MB files, 1 GB per room, 20 GB total (DR2); default retention 6 h, max 30 d; owner can rename/delete the room, reset the key, set the default retention, remove devices; end-to-end encryption later (DR5); Toolbox locked to this computer now (DR0). **Still open:** who joins rooms (only the owner's devices → Tailscale, or other people → public tunnel). That decides DR3; do not build DR3 before it is answered.

**Steps:** DR0 decisions + lock Toolbox to this computer ☑ · DR1 rooms, keys, devices, text, retention, edit, delete+undo, live sync by polling ☑ · DR2 files, folders, downloads, previews, quotas, real erasure ☑ · DR3 restricted entrance for other devices/people, HTTPS, attempt limits ☐ (blocked on the open decision) · DR4 unread dots, presence, reactions, pins, search, QR join link, phone share ☐ · DR5 optional end-to-end rooms, admin key, activity log ☐.

## Model (details and reasons: `../docs/architecture/ADR-DROP-ROOMS.md`)
- **Device** = a browser: random token in an HttpOnly cookie `dr_device`; only its SHA-256 is stored (`devices`). No accounts. A device idle 30 days is forgotten with its memberships.
- **Room** = name + key (25 chars, 125 bits, Crockford base32, shown `XXXXX-XXXXX-…`). `rooms.key_hash` = SHA-256 of the normalised key (lookup); the key itself is a Vault secret `dr-<roomid>` of kind `drop_room_key` (so members can re-share the invite). `epoch` bumps on **reset key** and silently removes everyone who joined with the old key.
- **Member** = device + room + nickname + role (`owner` | `member`). **Item** = `text`, `file` or `folder` (a ZIP built by the browser), `version` for edit conflicts, `expires_at`, `deleted_at` (undo window). File bytes live in Toolbox's S3 storage under `drop-rooms/<room>/<item>` (never in the database, never in the Vault); the database row holds name, size, sniffed type and that key (the key is never sent to a browser).
- `rooms.rev` bumps on every change; the page polls `GET rooms/{id}/items?rev=N` every 2 s (10 s when the tab is hidden) and gets a tiny `{changed:false}` when nothing changed. Expired items are hidden by every query and by the page's own 1 s clock; erasure is lazy (`purge()` on reads/writes) — **Toolbox has no scheduler**, so data of an idle room is erased on the next visit (access is cut off immediately regardless).
- A stranger, a removed member and a non-existent room all get the **same** 404 ("Room not found…"); a wrong key gets "That key does not match any room." Never reveal that a room exists.

## Where things live
| Concern | File |
|---|---|
| Rooms, keys, devices, items, retention, undo, purge — pure logic over a SqlStore + scoped Vault + clock | `store.py` |
| HTTP: device cookie, `X-Drop-Rooms: 1` guard, Redis join rate limits, strict CSP, `no-store`, endpoints | `server.py` |
| The page (Discord-style layout, dialogs, uploads, file cards, viewer) | `ui/index.html` + `ui/app.js` |
| Folder → ZIP in the browser (store method, cleaned paths); verified against Python's zipfile | `ui/zip.js` (tests: `tests/unit/drop_rooms_zip_cases.js`) |
| File storage adapter (`S3Files`: put / delete / head / stream), upload endpoint, downloads and previews | `server.py` (logic: `store.py` `add_file`, `file_for_download`, `text_preview`) |
| Mount info (runtime data, state durable+session, Vault scope `drop_room_key`, no `ai:`) | `manifest.yaml` |

## Rules for this tool (repo-wide rules are in `../CLAUDE.md`)
- Runtime `data` (needs Postgres driver + Vault); package `drop_rooms` is unique. Tables live in Postgres schema `drop_rooms` (SqlStore); join rate limits in Redis (`toolbox:drop_rooms:rl:*`), **fail closed**.
- **Every non-GET request must carry `X-Drop-Rooms: 1`** (request-forgery guard; the page's single `api()` helper sends it). Cookie is `HttpOnly; SameSite=Lax`, `Secure` when the request came over HTTPS.
- Messages and keys are shown with `textContent`/text nodes only; links only `http(s)` with `rel=noopener noreferrer`. The room key is **never** put in `localStorage`, a URL path or the console (the join link keeps it in the `#fragment`, which browsers never send). Tests scan the page code.
- No `ai:` section and no `postMessage` from the page: the AI helper / MCP can never see or call this tool; `mcp_server/vault_scope.yaml` must not list `drop_room_key`.
- Retention is capped at 30 days in `clamp_retention`; never add a "never expires" option without the owner asking.
- **File safety (DR2):** a download is ALWAYS `application/octet-stream` + `Content-Disposition: attachment` + `nosniff` + `Content-Security-Policy: sandbox; default-src 'none'`; the only thing shown inline is a PNG/JPEG/GIF/WebP whose **first bytes** say so (`sniff_image`, never the name or the browser's claim; no SVG, no HTML, no PDF). File names are cleaned (`clean_filename`); a folder ZIP is re-validated on the server (`check_zip`: real ZIP, ≤ 5,000 entries, no absolute / `..` / drive-letter paths). Downloads stream THROUGH this tool, so every download re-checks membership, expiry and deletion. Never serve a file from a URL that skips `file_for_download`.
- **Limits:** 100 MB per file/folder-ZIP, 1 GB per room, 20 GB for the tool (`MAX_FILE`, `ROOM_QUOTA`, `TOTAL_QUOTA` in `store.py`). Membership and free space are checked BEFORE the upload body is read (`upload_ticket`); the body is counted as it arrives. Quotas count files not yet erased (disk use is honest).
- **Erasure:** a file is deleted from storage when its item expires, is deleted (after the undo window), or the room is deleted (`purge` / `delete_room` → `files.delete`). `core/state/backup.py` skips the `drop-rooms/` prefix (`SKIP_PREFIXES`): temporary files are neither backed up nor wiped by a restore.

## Gotchas
- `server.py` loads `store.py` as `drop_rooms.store` in the image and by path in a checkout; tests that patch the service must use `server.store.DropRooms` so exception classes match. Importing `server.py` creates a `SqlStore` object but no files; tests must patch `server.STORE` (and `_initialised`) so nothing is written into the repo.
- Adding a Python file next to `server.py` needs its own `COPY` in the Dockerfile (done for `store.py`); a new file under `ui/` ships automatically but needs a route in `server.py` and an entry in `SCRIPTS`.
- `GET /rooms` creates a device row when the browser has no cookie (that is how a device is born); the smoke test therefore leaves a few tiny rows that expire after 30 idle days.
- Uploads use ONE `XMLHttpRequest` (`upload()` in `app.js`: a raw `PUT` whose body is the file, so progress events work and the server can count bytes while it arrives); everything else is the single `fetch` in `api()`. Tests enforce both counts. A folder is zipped in the browser (memory ≈ its size, ≤ 100 MB).
- `webkitdirectory` (the 📁 button) and dropping folders rely on Chromium/Firefox/Safari support; the tests fake the file list by overriding `input.files`.
- Text preview is limited to a list of text extensions (`TEXT_EXTS`), ≤ 5 MB, first 200 KB; anything with a NUL byte is refused. PDFs are download-only on purpose.
- **Never bulk-delete on the live database** (`DELETE FROM devices`, "clean everything"): the owner may be using the tool at that moment. A device row is the only thing that ties a browser's cookie to its rooms, and its token cannot be recreated, so deleting it silently removes someone from their own rooms (happened once, 2026-11-22; repaired by re-linking the room to the browser's new device). When a live test needs cleanup, delete only the rows the test created, by id (print the ids as the test creates them); room deletion through the service already removes a room's members, items, files and Vault key.
- Polling is deliberate (no process memory allowed, so no in-process push). If instant updates are wanted later: Server-Sent Events over Redis pub/sub, not in-memory queues.

## Tests
- `tests/unit/test_drop_rooms_store.py`: against a real temporary SQLite store + Vault: keys, hashing, joining, isolation, sync, retention, expiry, edit conflicts, delete/undo/erase, owner powers, key reset, room deletion, device handling, scopes; plus the HTTP layer with two cookie jars (CSRF header, cookie flags, rate limits, no secrets on the wire).
- `tests/unit/test_drop_rooms_zip.py`: the browser's ZIP verified by Python's `zipfile`, and the server's unsafe-ZIP refusals.
- `tests/unit/test_drop_rooms_page.py`: static guard rails on the page code (one `fetch`, one `XMLHttpRequest`, no HTML building, no blob URLs).
- `tests/unit/test_drop_rooms_ui.py` (+ `drop_rooms_ui_driver.js`): **two real browsers = two devices** in one room against the real server on a temporary database and an in-memory file store: text, edit, delete/undo, key reset, **files, thumbnails, downloads, previews, a pasted image, a folder, the size-limit message, file deletion**, and that deleting the room leaves no bytes in storage (needs chromium; skips without).
- `tests/smoke/test_drop_rooms.py` (live, via `scripts/smoke.sh`).

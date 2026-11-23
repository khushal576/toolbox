# ADR — Drop Rooms (roadmap DR0–DR5)

Status: DR0–DR2 built (2026-11-22). Owner: Khushal. Written for the next session: read this before changing the tool or starting DR3.

## What and why
The owner works on several devices and wants to move text, files and folders between them, and sometimes with other people, like a private chat:
**rooms**, each with a **key**; everyone in a room sees everything in it; **everything expires** (default 6 h, max 30 days) and is then inaccessible.

## Decisions (owner, 2026-11-22)
- Own tool inside Toolbox, not a separate product. Name "Drop Rooms".
- Access = the room key (no accounts). Owner powers: rename/delete room, reset key, default retention, remove devices.
- Files ≤ 100 MB (so no resumable-upload machinery), 1 GB per room, 20 GB overall (DR2). Folders are downloaded as ZIP.
- Anyone in a room may edit/delete anything; delete is immediate for everyone with a 10 s Undo for the deleter.
- Retention presets 1 h … 30 d, never "forever". Editing text does not reset its timer unless asked.
- Defaults accepted for everything else. **Open:** who joins rooms (owner's own devices only → Tailscale; other people → public HTTPS tunnel). This decides DR3.

## Storage
| What | Where | Why |
|---|---|---|
| rooms, devices, members, items (text, metadata) | Postgres schema `drop_rooms` via `SqlStore` | durable, shared by every web worker |
| room keys | Vault secret `dr-<roomid>`, kind `drop_room_key` (scoped to this tool) | members must be able to re-share the invite; Vault is where secrets live |
| file bytes (DR2) | Toolbox S3 storage (`core/state/objects`), keys `drop-rooms/<room>/<item>`, streamed through the tool; **excluded from backups** (`core/state/backup.py` `SKIP_PREFIXES`) | large, short-lived; not the Vault |
| join rate limits | Redis | shared across workers; fails closed |
Device tokens and room-key lookups are stored only as SHA-256 hashes (both are high-entropy random values).

## Threat model (why it is built this way)
- **Key = the only protection**, so it is 125 bits random; joining is rate-limited (8 / 10 min per device, 300 / 10 min overall) and a wrong key says nothing about whether rooms exist; non-members, removed members and unknown rooms all get the identical 404.
- **Key reset** bumps `epoch`: old members lose access instantly (not just on their next join).
- **Request forgery:** cookie `SameSite=Lax` + required custom header `X-Drop-Rooms: 1` on every non-GET (cannot be sent cross-site without a CORS pre-flight, which is never allowed).
- **XSS:** text is rendered as text nodes; strict CSP (`default-src 'self'`, `connect-src 'self'`); tests scan the page code. Uploads (DR2) are always served as downloads with `nosniff`, never rendered; only a short list of image types gets a preview.
- **AI:** no `ai:` manifest section, no `postMessage`, Vault scope limited to `drop_room_key`, MCP scope untouched and tested not to see it.
- **Expiry** is enforced at read time by every query (and by the page's clock), so "after retention no access" holds even if cleanup has not run. Erasure is lazy because Toolbox has no scheduler; an idle room's data is erased on the next visit (DR3+: consider a daily janitor on the worker).
- **Not protected:** the Toolbox owner and anyone with database + Vault-key access can read content (until the optional end-to-end rooms in DR5). Anyone who already downloaded or copied something keeps it.

## Network exposure (DR0 finding, 2026-11-22)
Before DR0 the gateway was published on `0.0.0.0:8000` with no login: every tool (including the Vault page) answered on the LAN address. No other device had used it in the previous 72 h (gateway log). DR0 bound it to `127.0.0.1` (`TOOLBOX_BIND`).
**DR3 design (not built):** a restricted entrance that serves **only** `/tools/drop-rooms/**` (never the rest of Toolbox) on its own port, ideally inside the existing gateway process (no new container; confirm when DR3 starts), reachable over HTTPS (Tailscale serve, or a Cloudflare tunnel with the entrance as its only target). HTTPS also unlocks the clipboard API, installable app and Android "Share to Drop Rooms".

## Files and folders (DR2)
- Upload is a raw `PUT` (not multipart) so the server can refuse by `Content-Length` / counted bytes and check membership + free space before reading the body. Folders are zipped in the browser (so the server only ever stores one file); the server re-validates the ZIP (no absolute / `..` / drive paths, ≤ 5,000 entries).
- A download is always opaque bytes the browser saves; only a real image (first-bytes check at upload) is shown inline, inside a CSP sandbox. No SVG/HTML/PDF inline.
- Limits: 100 MB per file, 1 GB per room, 20 GB total; erased on expiry, delete and room deletion.

## Not done / ideas
Unread dots, presence UI, reactions, pins, search, QR join, phone share (DR4); end-to-end encrypted rooms, admin key, activity log, rename file (DR5); instant push via SSE + Redis pub/sub; a daily purge job.

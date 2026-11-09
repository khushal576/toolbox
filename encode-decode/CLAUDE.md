# Encode/Decode — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.


Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

Base64/URL/Hex/HTML-entity encoding, Gzip, AES-GCM, RSA-OAEP, JWT
(HS256/RS256), and SHA hashing — all in one page.

## How it's built

- `server.py` — does exactly one thing: serves `ui/index.html`. No other
  routes, no request handling of any kind.
- `ui/index.html` — everything else. Single file, no build step, one
  `<script>` block using the browser's native Web Crypto API.
- **No backend processing, by design.** Every operation, including the
  ones involving real secrets (AES passphrases, RSA private keys), runs
  entirely in the browser. Nothing is ever sent over the network. If you're
  tempted to add a POST endpoint here for "convenience," don't — that
  tradeoff was made deliberately and needs the owner's sign-off to reverse.

## Where each feature lives (inside `ui/index.html`'s script)

Text Encoding tab · Gzip tab · AES-GCM tab · RSA-OAEP tab · JWT tab · Hash
tab — each is its own clearly-commented section. Find the tab name as a
comment header and everything for it is right there.

## Things that will bite you if you don't know them

- **RSA-OAEP has a plaintext size ceiling** (~190 bytes at 2048-bit key /
  SHA-256 — the padding overhead eats into the usable space). It's meant
  for wrapping a small secret like an AES key, not general data. Keep the
  UI's size hint if you touch that tab.
- **AES output format is `base64(salt[16] + iv[12] + ciphertext)`** — one
  blob, fixed layout. The decrypt path assumes exactly this. Changing the
  layout breaks every ciphertext already produced by this tool; treat that
  as a breaking change, not a tweak.
- Mounted at `/tools/encode-decode/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way.

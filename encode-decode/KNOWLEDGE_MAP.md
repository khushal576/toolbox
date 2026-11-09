<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: Encode/Decode — mounted at `/tools/encode-decode/`

Entirely client-side — the Python backend (`encode-decode/server.py`) only
serves the static page; it has no other routes and never sees any input.

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| Anything at all about behavior (every operation runs client-side) | `encode-decode/ui/index.html` (`<script>` block) |
| Base64 / Base64URL / Hex / URL / HTML entity logic              | `index.html` — "Text Encoding tab" section of the script |
| Gzip compress/decompress                                        | `index.html` — "Gzip tab" section (`CompressionStream`/`DecompressionStream`) |
| AES-GCM passphrase encryption                                   | `index.html` — "AES-GCM tab" section (`deriveAesKey`, PBKDF2 100k iterations) |
| RSA key generation / encrypt / decrypt                          | `index.html` — "RSA-OAEP tab" section |
| JWT signing/verification (HS256, RS256)                         | `index.html` — "JWT tab" section |
| SHA hashing                                                      | `index.html` — "Hash tab" section |
| Whether the backend does anything beyond serving the page        | `encode-decode/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **No backend processing, intentionally.** This was a deliberate security
  choice (see `CLAUDE.md` history / conversation) — real secrets
  (passphrases, private keys) must never be sent over the network, even
  locally. Don't add a `/encrypt`-style POST endpoint to `server.py` without
  re-raising that tradeoff with the owner first.
- **RSA-OAEP has a plaintext size limit** (~190 bytes at 2048-bit/SHA-256).
  It's meant for wrapping a small secret (like an AES key), not general
  data. The UI hints at this; don't remove the hint if touching that tab.
- **AES output packs `salt(16) + iv(12) + ciphertext` into one Base64
  blob** — the decrypt path assumes that exact layout. If the format ever
  changes, old ciphertexts become undecryptable; treat that as a breaking
  change worth flagging, not a silent tweak.

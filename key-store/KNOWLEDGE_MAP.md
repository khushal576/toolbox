<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ./CLAUDE.md -->

## Tool: Key Store — mounted at `/tools/key-store/`

| If you need to change... | Go to |
|---|---|
| The page shell, styles, entry dialog, tab switching | `ui/index.html` |
| Generator page behaviour (options, copy, "Save to Store…") | `ui/generator.js` |
| Store tab behaviour (search, copy, reveal, edit, trash) | `ui/store.js` |
| How an entry is validated, stored, searched, ranked, trashed, previewed | `store.py` (tests: `../tests/unit/test_key_store_store.py`) |
| What an AI / other tool may see of it (nothing): the Vault scope | `manifest.yaml` `vault:`, `../mcp_server/vault_scope.yaml`, `../core/vault.py` `ScopedVault` |
| How a password / passphrase / PIN / token / UUID is made, entropy, strength words | `ui/keygen.js` (tests: `../tests/unit/key_store_keygen_cases.js`) |
| The passphrase word list | `ui/words.js` (EFF Large Wordlist, CC BY 3.0 US) |
| An endpoint, the security headers (CSP), which files are served (`SCRIPTS`) | `server.py` |
| How the tool is listed / mounted (title, icon, runtime, order, secrets) | `manifest.yaml` |
| Its image / packages | `../Dockerfile` (`COPY key-store/…`), `../requirements/light.txt` |
| Its smoke tests | `../tests/smoke/test_key_store.py`, `../tests/unit/test_key_store.py`, `../tests/unit/test_key_store_ui.py`, the `API_CHECKS` line in `../tests/smoke/test_api.py` |

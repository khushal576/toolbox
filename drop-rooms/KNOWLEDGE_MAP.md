<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ./CLAUDE.md -->

## Tool: Drop Rooms — mounted at `/tools/drop-rooms/`

| If you need to change... | Go to |
|---|---|
| How a room, key, member, item, retention, undo, edit conflict or purge works | `store.py` (tests: `../tests/unit/test_drop_rooms_store.py`) |
| An endpoint, the device cookie, the request-forgery header, join rate limits, security headers | `server.py` |
| The layout, dialogs, countdowns, polling, edit/delete/undo behaviour, file cards, viewer, drag-and-drop, paste | `ui/app.js`, `ui/index.html` |
| How a folder becomes a ZIP in the browser | `ui/zip.js` |
| File limits, quotas, name cleaning, image sniffing, ZIP checks, erase hooks | `store.py` (`MAX_FILE`, `ROOM_QUOTA`, `TOTAL_QUOTA`, `clean_filename`, `sniff_image`, `check_zip`, `add_file`, `purge`) |
| Upload / download / preview endpoints and the S3 adapter | `server.py` (`S3Files`, `upload_file`, `_serve`) |
| Why files are not in backups | `../core/state/backup.py` (`SKIP_PREFIXES`) |
| Table definitions (Postgres schema `drop_rooms`) | `store.py` `SCHEMA` |
| Retention presets / limits (30 days, 100 items…) | `store.py` constants (`PRESETS`, `MAX_RETENTION`, `DEFAULT_RETENTION`, `MAX_*`) |
| Who may see the room keys (nobody but this tool; not the AI) | `manifest.yaml` `vault:`, `../mcp_server/vault_scope.yaml`, `../core/vault.py` `ScopedVault` |
| Design, threat model, the open network decision | `../docs/architecture/ADR-DROP-ROOMS.md` |
| Its image / packages | `../Dockerfile` (`COPY drop-rooms/…`) — no new Python packages |
| Its tests | `../tests/unit/test_drop_rooms_*.py`, `../tests/unit/drop_rooms_zip_cases.js`, `../tests/unit/drop_rooms_ui_driver.js`, `../tests/smoke/test_drop_rooms.py`, the `API_CHECKS` line in `../tests/smoke/test_api.py` |

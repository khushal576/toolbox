<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ./CLAUDE.md -->

## Tool: SQL Practice — mounted at `/tools/sql-practice/`

| If you need to change... | Go to |
|---|---|
| The page (layout, behaviour) | `ui/index.html` |
| An endpoint, request/response shape | `server.py` |
| How the tool is listed / mounted (title, icon, runtime, order, secrets) | `manifest.yaml` |
| Its image / packages | `../Dockerfile` (`COPY sql-practice/…`), `../requirements/data.txt` |
| Its smoke tests | `../tests/smoke/test_sql_practice.py`, the `API_CHECKS` line in `../tests/smoke/test_api.py` |
| The practice database: role/DB creation, dataset loading, safe query running, question files, validator | `provision.py` |
| A dataset or a question (content, not code) | `../../learn-sql/practice/{datasets,questions}/` — then `GET /tools/sql-practice/validate` |
| Why learner SQL cannot touch Toolbox's own data | `CLAUDE.md` "Decisions" · `provision.py` header |
| The Vault entry "Practice database (built-in)" | `../core/vault.py` `_seed_default_connections` |

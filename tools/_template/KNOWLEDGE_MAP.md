<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ./CLAUDE.md -->

## Tool: __TOOL_TITLE__ — mounted at `/tools/__TOOL_NAME__/`

| If you need to change... | Go to |
|---|---|
| The page (layout, behaviour) | `ui/index.html` |
| An endpoint, request/response shape | `server.py` |
| How the tool is listed / mounted (title, icon, runtime, order, secrets) | `manifest.yaml` |
| Its image / packages | `../Dockerfile` (`COPY __TOOL_NAME__/…`), `../requirements/__TOOL_RUNTIME__.txt` |
| Its smoke tests | `../tests/smoke/test___TOOL_PACKAGE__.py`, the `API_CHECKS` line in `../tests/smoke/test_api.py` |

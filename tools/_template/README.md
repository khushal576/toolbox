# Tool template (roadmap P2)

Not a tool — a starting point. Create a new tool with:

    python3 scripts/new_tool.py my-tool "My Tool" --icon 🧩 --description "What it does" [--runtime light|data] [--dry-run]

It copies this folder to `my-tool/`, fills the `__TOOL_*__` placeholders, and makes the four edits people forget
(Dockerfile COPY + package `__init__`, smoke `API_CHECKS` line, smoke test file, `KNOWLEDGE_MAP.md` index row).
Then: edit `server.py` and `ui/index.html`, fill in the tool's `CLAUDE.md`, rebuild (`docker compose up -d --build`), run the tests.
Placeholders: `__TOOL_NAME__` (slug) · `__TOOL_PACKAGE__` (python package) · `__TOOL_TITLE__` · `__TOOL_DESCRIPTION__` · `__TOOL_ICON__` ·
`__TOOL_RUNTIME__` · `__TOOL_ORDER__` · `__TOOL_DATE__`. This folder is never scanned by the plugin loader (it is two levels deep and its manifest is invalid on purpose).

Remove a tool again (dry run by default): `python3 scripts/remove_tool.py my-tool` — see `scripts/remove_tool.py`.

<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ./CLAUDE.md -->

## Tool: Speak English — mounted at `/tools/learn-english/`

| If you need to change... | Go to |
|---|---|
| A module, its Hindi set, its cheat sheet | `modules/mNNN.js`, `practice/hNNN.js`, `cheat/cNNN.js` |
| The course map, phases, which modules are ready | `modules/manifest.js` |
| Top bar, sidebar, home screen | `ui/index.html` (`home`, `side`, the `.tb` header) |
| Lessons, questions, boss, build-your-own | `ui/index.html` (`play`, `renderQ`, `renderBoss`, `renderBuild`) |
| Hindi practice (Plain/Tough), cheat sheet screen | `ui/index.html` (`hindiSetup`, `hindiPractice`, `cheatSheet`) |
| Saving progress (browser side) | `ui/index.html` (`save`, `push`, `absorb`, boot at the end) |
| Saving progress (server side), merge rules, summary | `server.py` (`clean`, `merge`, `_write`, `progress_summary`) |
| Which content files can be served | `server.py` (`CONTENT`, `content`) |
| Content checks / private test copy | `tools/validate.js`, `tools/run_private.py` |
| Tests | `../tests/unit/test_learn_english.py`, `../tests/smoke/test_learn_english.py` |

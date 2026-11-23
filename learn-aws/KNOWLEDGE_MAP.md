<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ./CLAUDE.md -->

## Tool: Learn AWS — mounted at `/tools/learn-aws/`

| If you need to change... | Go to |
|---|---|
| The notes or the questions | the `learn-aws-services` repo, then `python3 learn-aws/sync.py` → `notes/`, `mcq/` |
| The page: layout, look, Markdown rendering, search box | `ui/index.html` (`render`, `inline`, `buildNav`, `openNote`) |
| The quiz screens | `ui/index.html` (`openPractice`, `startQuiz`, `showQuestion`, `showSummary`) |
| Endpoints, ordering, search ranking | `server.py` (`_load`, `_load_mcq`, `search`, `mcq_questions`) |
| How the tool is listed / mounted, the AI action | `manifest.yaml` |
| Its image | `../Dockerfile` (`COPY learn-aws/…` incl. `notes/` and `mcq/`) |
| Tests | `../tests/unit/test_learn_aws.py`, `../tests/smoke/test_learn_aws.py` |

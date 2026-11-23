# learn-aws — AWS service notes + practice questions inside Toolbox

> Repo rules: `../CLAUDE.md` · map: `../KNOWLEDGE_MAP.md` · tool checklist: `../docs/architecture/adding-a-tool.md`

## What it is
A read-only reader for the owner's AWS notes (65 services, study order) with search and an exam-style Practice quiz. Category `learn`, runtime `light`,
no server state, no Vault, no database. Quiz progress lives only in the visitor's browser (localStorage key `learnAws.quiz`).
**The look (white page on a blue-grey desk, Contents panel, floating Read pill) was chosen by the owner — keep it.** Do not swap in the notes repo's own
`index.html` site: that was tried on 2026-11-23 and the owner rejected it ("just add the MCQs").

## Where things live
- `notes/` and `mcq/` — **copies** from the `learn-aws-services` repo. Never edit here: edit there (notes, `mcq/<category>/<service>.json`), then
  `python3 learn-aws/sync.py` (`--dry-run` first), `docker compose up -d --build`, commit. Sync mirrors deletions and refuses a broken question file.
- `server.py` — loads both once at start-up. `GET /tree` (categories → services → files, with question counts), `/note?path=`, `/search?q=`
  (also `?query=` for the AI action), `/mcq/questions?service=<category>/<service>|ALL`, `/health`. Only paths/keys already in the index are served.
- Study order = the folder numbers (`01-governance-and-security`, `01-s3` …); the numbers are stripped from display names.
- `ui/index.html` — one page: Markdown renderer, Contents, search, themes, and the quiz (`openPractice`, `startQuiz`, `showQuestion`, `showSummary`).
  Built with DOM calls only — no HTML injection API (a unit test greps for it). Routes: `#<note path>`, `#practice`, `#quiz:<category>/<service>`.
- Manifest `ai:` has one read-only action `search_notes`.

## Gotchas
- Question format and writing rules live in the notes repo: `learn-aws-services/mcq/README.md`. Its `build.py` validates them; `tests/unit/test_learn_aws.py` re-checks shape, unique ids, valid answers and that every `source` note exists.
- AI action input names must be ≥ 2 characters (`query`, not `q`).
- Book 2 (the `learn-aws-de` exam course) was built and removed at the owner's request (2026-11-23).

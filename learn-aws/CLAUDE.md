# learn-aws — AWS service notes + practice questions inside Toolbox

> Repo rules: `../CLAUDE.md` · map: `../KNOWLEDGE_MAP.md` · tool checklist: `../docs/architecture/adding-a-tool.md`

## What it is
A read-only reader for the owner's AWS notes (65 services, study order) with search and an exam-style Practice quiz. Category `learn`, runtime `light`,
no server state, no Vault, no database. Quiz progress lives only in the visitor's browser (localStorage key `learnAws.quiz`).
**The look (white page on a blue-grey desk, Contents panel, floating Read pill) was chosen by the owner — keep it.** Do not swap in a different site or design:
that was tried on 2026-11-23 and the owner rejected it ("just add the MCQs").

## Where things live
- `notes/<NN-category>/<NN-service>/<N>-<topic>.md` — **the notes themselves (the only copy).** Also `notes/README.md`, `notes/EXAM-COVERAGE.md` and one `README.md` per category.
- `mcq/<NN-category>/<NN-service>.json` — **the practice questions (the only copy).** Format and rules: `MCQ-GUIDE.md`.
- `NOTE-TEMPLATE.md` — layout of a service note. `PLAN.md` — the approved plan of remaining note work (2026-11-01).
- `server.py` — loads notes and questions once at start-up. `GET /tree` (categories → services → files, with question counts), `/note?path=`,
  `/search?q=` (also `?query=` for the AI action), `/mcq/questions?service=<category>/<service>|ALL`, `/health`. Only paths/keys already in the index are served.
- Study order = the folder numbers (`01-governance-and-security`, `01-s3` …); the numbers are stripped from display names.
- `ui/index.html` — one page: Markdown renderer, Contents, search, Read controls in the top bar, themes, and the quiz (`openPractice`, `startQuiz`,
  `showQuestion`, `showSummary`). Built with DOM calls only — no HTML injection API (a unit test greps for it). Routes: `#<note path>`, `#practice`, `#quiz:<category>/<service>`.
- Manifest `ai:` has one read-only action `search_notes`.
- After any change to notes or questions: `python3 -m pytest tests/unit/test_learn_aws.py -q`, then `docker compose up -d --build`.

## Writing notes (moved here from the deleted learn-aws-services repo, 2026-11-24)
Goal: the owner reads one service months later and can answer any exam (DEA-C01, exam guide v1.1) or real design question about it.
1. **Plan first.** Before writing a service, show the owner the file split and the topics per file (and the exam skills from `notes/EXAM-COVERAGE.md`). Wait for approval; the owner also studies from videos and may add topics.
2. Only after approval: research the service in current AWS docs, then write. One service at a time.
3. After writing: update the category `README.md` and `notes/EXAM-COVERAGE.md`, and tell the owner what is marked "(verify)".
- Style (`NOTE-TEMPLATE.md`): short notes, one idea per bullet, easy English, name the why and the catch; files numbered by reading order
  (basics → how it works → data in/out → performance → availability → security → cost → monitoring → limits → scenarios); small service 1 file, big 3–5,
  about 150–200 points per file; cost inside the files; "If X → Y, because Z" scenarios at the end; edge cases, limits, defaults and traps.
- Accuracy: check numbers against current AWS docs; mark unconfirmed facts **(verify)**; end each file with `Verified from AWS docs on <date>` and the
  unconfirmed list; use current service names and note retirements (Kinesis Data Analytics → Managed Flink, QuickSight → Amazon Quick, S3 Select closed to new customers …).
- Keep folder numbers in study order; a new service gets the next number. Theory only — no labs unless asked.

## Writing questions
- **Plan first** (topics/skills and the count from the tier table in `MCQ-GUIDE.md`), wait for approval, then write. Core services 30–40, important 18–25, supporting 8–12.
- DEA-C01 style: short scenario, one decision, plausible wrong options, a `why` for every option, plus `remember` and `variants`.
- Every fact from the notes; nothing marked "(verify)" may be a correct answer. Ids are permanent (browser progress is keyed by id) — never renumber.
- Done so far: 37 services, 532 questions (see `mcq/`). Not yet written: the tier A core services (Glue, Lambda, Athena, Redshift, DynamoDB, Lake Formation, EventBridge, SQS and SNS, Kinesis Data Streams, Firehose, Managed Flink, MSK), CloudWatch, CloudTrail, DMS, Elastic Load Balancing, and the tier D services. CI/CD has no question from note 4 (CodeCommit, mostly "(verify)").

## Gotchas
- `tests/unit/test_learn_aws.py` checks question shape, unique ids, valid answers and that every `source` note exists — it is the only validator now.
- The old `learn-aws-services` repo (local and GitHub) was deleted on 2026-11-24 at the owner's request; this folder is the source of truth.
- AI action input names must be ≥ 2 characters (`query`, not `q`).
- Book 2 (the `learn-aws-de` exam course) was built and removed at the owner's request (2026-11-23).

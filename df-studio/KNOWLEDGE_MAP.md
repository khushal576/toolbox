<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: DataFrame Studio — mounted at `/tools/df-studio/`

Click-driven pandas: load CSV/JSON/XML/Parquet, transform via UI
(rename/drop/add column, filter, sort, or a free-form Query box with
Check/Add-to-pipeline modes and quick-insert snippets), inspect
(describe/info/nunique/value counts), export — as a file, as a standalone
`.py` script, or save the pipeline as a reusable named template. Every
step shows the pandas line it maps to. See `df-studio/CLAUDE.md` for the
full picture.

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| Session state, the replay model, file loading, insights, script export, template replay, the Check/Add split (`preview_step`/`apply_step`) | `df-studio/engine.py` |
| A transformation step's behavior or its generated pandas code line     | `df-studio/steps.py` (`STEP_HANDLERS`); the DF1 cleaning steps are in `df-studio/clean_steps.py` (`HANDLERS`) |
| A no-code cleaning step (fill empty, change type, clean text, replace, extract/split/join, date parts, dedupe, drop sparse/constant, outliers, bins, bulk rename, filter builder) — what it validates, the pandas line it builds and runs, the note it reports | `df-studio/clean_steps.py` (one function per step; `run()` executes the generated code; `note()` → page warnings) |
| The Formula bar: what is allowed, the function list, how `a / b` becomes `df['x'] = (df['a'] / df['b'])`, the plain-language errors | `df-studio/formula.py` (`FUNCS`, `Emitter`, `compile_lines`, `expression`) |
| Turning a step off/on, moving it, refusing a change that would break a later step; notes stored per step; "Step N (…):" error prefix | `df-studio/engine.py` (`toggle_step`, `move_step`, `_swap_steps`, `recompute`, `apply_step_ex`) |
| The ⋮ column menu's stats + suggested fix | `df-studio/engine.py` `suggest_fixes` + `column_stats(df, columns)`; `server.py` `GET /column-stats?column=`; UI `openMenu()` |
| API endpoints (`/load`, `/load/vault`, `/step`, `/step/check`, `/step/remove`, `/step/toggle`, `/step/move`, `/formula/help`, `/column-stats`, `/insight`, `/export`, `/script`, `/template/*`) | `df-studio/server.py` (all walked by `tests/unit/test_df_studio_server.py`) |
| Saved-template storage (JSON on disk)                                  | `df-studio/templates_store.py` |
| The frontend: grid (Tabulator.js), "load from Vault" picker, form-based step fields, Query box (Check/Add + snippets), pipeline panel, script/template panels | `df-studio/ui/index.html` |
| Loading a saved Vault dataset in as a new session (the consumer side of duck-lab's/sql-studio's `/export/vault`) | `df-studio/server.py`'s `/load/vault` — decrypts via `core.vault.load_dataset_file()`, reads the bytes, then reuses the exact same `engine.load_dataframe()`/`create_session()` path `/load` uses for an upload |
| Adding a brand-new form-based step type                                | `steps.py` (handler) **and** `ui/index.html` (`#f-<type>` fieldset + `<option>`) |
| Adding a new Clean-box action (no-code step)                           | `clean_steps.py` (handler + `HANDLERS` + `LABELS`) **and** `ui/index.html`'s `CLEAN` object (fields) — no new fieldset |
| The Clean card, column picker, ⋮ menu, Formula card + autocomplete, pipeline on/off/▲▼ | `df-studio/ui/index.html` — the "PHASE DF" block near the end of the script |
| Adding a new Query-box quick-insert snippet                            | `ui/index.html` — `SNIPPETS` object only, no backend change |

### Known non-obvious behavior (read before touching these areas)

- **Sessions are stored outside the process since roadmap B2**
  (`df-studio/session_store.py`: metadata in Redis, original DataFrame in S3
  storage) — they survive restarts and work across worker processes. Every
  session-changing function must call `engine.save_session()`. Templates are
  in Postgres (`df_studio.templates`).
- **The "current" DataFrame is always recomputed by replaying `steps` over
  `original_df`** (`engine.recompute`), never mutated in place — this is
  what makes removing a step from the middle of the pipeline just work.
- **`add_column`/`filter_rows` use `df.eval`/`df.query(engine="python")`** —
  arithmetic, comparisons, string concat on bare column names only, not
  arbitrary Python. The Query box's `custom_code` step is the escape hatch
  for that (real `exec()`, `pd`/`np` in scope, **no sandboxing** —
  deliberate, single-user local tool; revisit before this is ever exposed
  beyond one trusted user). Check mode (`/step/check`) still `exec()`s the
  code — it's a "don't commit yet" toggle, not a safer sandbox.
- **The DF1 cleaning steps RUN the code they show** (`clean_steps.run()` exec's the generated line on a copy of the DataFrame);
  every user value goes through `repr()` — never paste user text into the code string. The Formula bar is different again: the
  text is parsed with `ast`, checked against an allow-list and the pandas is GENERATED from the tree (`formula.Emitter`);
  the typed text is never executed. New function = a `FUNCS` entry **and** an emitter branch (a test fails when they disagree).
- **Turning a step off / moving / removing one is refused (400, nothing changed) when a later step needs it** —
  `engine._swap_steps` replays the whole pipeline first. Disabled steps are skipped by `recompute`, by the script and by templates.
- **Step handlers raise plain `ValueError`, never `engine.StepError`** —
  `StepError` is a subclass, so `except StepError` alone misses them. This
  bit `engine.apply_template()` for real (a step failing mid-template
  crashed with an unhandled 500 instead of a clean `template_errors`
  response) — fixed by catching `ValueError`. Match that in any new
  per-step try/except.
- **The grid caps preview rows at `engine.PREVIEW_ROW_CAP` (5000)** but
  `/export` and `/script` always run against the full DataFrame — a bigger
  export than the table showed is expected, not a bug.
- **Templates persist `{type, params}` only, never the generated code** —
  code is regenerated from the live `STEP_HANDLERS` on every apply, so a
  codegen fix in `steps.py` automatically improves old saved templates.
- **This is the one tool copied as a whole folder in `../Dockerfile`**
  (`COPY df-studio/ ./df_studio/`) instead of the usual two-line
  `server.py` + `ui/` copy, because it has extra backend modules. Its
  `server.py`/`engine.py` use a try/except dual import so the tool still
  runs standalone from inside `df-studio/` for dev, not just mounted.
- **`/load/vault` reads the whole decrypted dataset into memory**
  (`content = await asyncio.to_thread(tmp_path.read_bytes)`) before
  calling `engine.load_dataframe()` — consistent with this tool's own
  accepted design (every upload is already fully materialized into
  pandas, unlike duck-lab), not a new ceiling introduced by this
  endpoint. Unlike duck-lab's equivalent endpoint, this one DOES wrap
  its vault/file calls in `asyncio.to_thread`, matching every other
  pandas-touching endpoint in this file (duck-lab's own convention is the
  opposite — direct synchronous calls — because duck-lab never runs
  pandas on the request path).

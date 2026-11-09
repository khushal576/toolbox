<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: DataDiff Pro — mounted at `/tools/datadiff-pro/`

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| How JSON / XML / CSV text gets parsed into Python objects              | `core/normalizer.py` |
| XML-specific quirks (attributes, `xsi:nil`, list detection)            | `core/normalizer.py` (`_parse_xml` and helpers) |
| CSV delimiter sniffing / cell type coercion                            | `core/normalizer.py` (`_parse_csv`, `_coerce_csv_value`) |
| Field renaming / restructuring rules ("Field Mapper" panel)            | `core/mapper.py` |
| Generic nested path lookup/insert/delete used by the mapper & validator | `core/path_resolver.py` |
| The actual left-vs-right comparison logic, MATCH/MISMATCH/EQUIVALENT   | `core/diff_engine.py` |
| How two lists of objects get paired up before comparing                | `core/list_resolver.py` |
| What counts as "equivalent but not equal" (null-likes, bool-likes, numeric tolerance, custom YAML groups) | `core/equivalence.py` |
| "Deep Mode" — parsing string-encoded JSON/XML found inside fields      | `core/deep_expander.py` |
| Post-mapping check for silently dropped fields                         | `core/validator.py` |
| The mapping → deep-expand → equivalence/list-resolver → diff sequence itself (shared with the headless orchestrator, see `orchestrator/CLAUDE.md`) | `core/pipeline.py` (`run_compare`) |
| The API contract: `POST /api/v1/compare` (text), `/api/v1/compare/structured` (parsed values, tagged Decimal/date/UUID/bytes), `/api/v1/health`, OpenAPI at `/tools/datadiff-pro/docs`; `/compare` = old alias | `api/app.py` (roadmap D1) |
| Background compares: submit/status/result/cancel, input + result storage, the worker-side job body, the page's > 2 MB switch | `api/jobs.py` (`submit`, `status`, `result_path`, `cancel`, `run_job`, `FILES`, `JOBS`), `/api/v1/jobs*` in `api/app.py`, `compareInBackground` in `ui/index.html`, client `submit_text/submit_data/job/result/wait/cancel` (roadmap D2) |
| Calling DataDiff from other code (never import `core.pipeline` outside DataDiff — a unit test enforces it) | `core/clients/datadiff.py` (`DataDiffClient`, `DataDiffError`, value codec) |
| DataDiff's own service: image `datadiff` (188 MB), `rt-datadiff` × 2 replicas behind the gateway | Dockerfile target `datadiff`, `requirements/datadiff.txt`, compose `rt-datadiff` (`deploy.replicas`) |
| The FastAPI app object that `main.py` mounts                           | `api/app.py` (`app = FastAPI(...)`) |
| The frontend: layout, results table, filters, export (JSON/CSV/Excel)  | `ui/index.html` (single file, no build step) |
| "Load from Vault" (per side, size-capped at 2000 rows by default)     | `ui/index.html`'s `refreshVaultDatasetSelects()`/`loadVaultDataset()` — calls `vault/server.py`'s `GET /datasets/{id}/preview`, same-origin, no proxy |
| Example equivalence-rule / list-key YAML config                        | `environments/example.yaml` |
| Batch/large-file comparison outside the browser                        | `notebook/compare_automation.ipynb` |

### Data flow (in call order)

```
ui/index.html --POST api/v1/compare--> gateway --> rt-datadiff (×2) --> api/app.py
  -> core/normalizer.py     (parse both sides)
  -> core/deep_expander.py  (only if deep_mode)
  -> core/mapper.py         (only if a field mapping was supplied)
       -> core/path_resolver.py   (path lookups used internally)
  -> core/validator.py      (only if a mapping was applied)
  -> core/equivalence.py + core/list_resolver.py   (built inside api/app.py,
       then handed to DiffEngine)
  -> core/diff_engine.py    (the actual comparison, returns DiffResult)
<- api/app.py returns JSON -> ui/index.html renders the table
```

### Known non-obvious behavior (read before touching these areas)

- **Frontend API calls must stay relative** (`fetch('compare', ...)`, never
  `fetch('/compare', ...)`). This is what lets `ui/index.html` work both
  mounted at `/tools/datadiff-pro/` and if ever run standalone. Any new
  fetch call added to the frontend must follow this.
- **`core/mapper.py`'s `_apply_single`** used to silently drop intermediate
  target-path segments when the target path was deeper than the source path
  (e.g. `a` → `x.y` produced `{"y": ...}` instead of `{"x": {"y": ...}}`).
  Fixed — see git log for `core/mapper.py`. If touching the leaf-rename
  branch again, re-run the depth-mismatch case as a regression check.
- **`core/list_resolver.py`'s `resolve()`** used to silently drop any
  non-dict item sharing a list with dict items (no EXTRA_LEFT/RIGHT record
  at all). Fixed — mixed lists now get the dict items paired normally and
  the leftover scalar items paired by index, merged into one result. If
  touching `resolve()`, re-check a mixed dict+scalar list still surfaces
  every item.
- **XML root tag is deliberately kept as a data key**, not unwrapped (see
  `_unwrap_xml_lists`'s docstring in `core/normalizer.py`) — this is so XML
  and its JSON equivalent produce the same top-level shape. Don't "fix" this
  by unwrapping the root; it would break XML-vs-JSON comparisons.

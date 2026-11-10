# __TOOL_TITLE__ (`__TOOL_NAME__/`, package `__TOOL_PACKAGE__`) — tool-local notes

<!-- O3-pointer -->
> **Start here:** repo rules `../CLAUDE.md` (hard rules + task→file table) · where things live in this tool: `./KNOWLEDGE_MAP.md` · what was done last / what is left: `../docs/roadmap/ROADMAP.md` Handoff log. Do not change anything outside this tool's folder unless the task says so.

Created from `tools/_template` on __TOOL_DATE__ (roadmap P2). **Fill this file in as the tool grows** — a future session opened in this folder should be able to work from it alone.

## What it is
__TOOL_DESCRIPTION__ (one short paragraph: who uses it, what it does, what it deliberately does NOT do.)

## Where things live
| Concern | File |
|---|---|
| The ASGI app and its endpoints | `server.py` |
| The page | `ui/index.html` |
| How it is mounted (runtime, tier, state, order, secrets) | `manifest.yaml` |

## Rules for this tool (repo-wide rules are in `../CLAUDE.md`)
- Runtime `__TOOL_RUNTIME__`; the package name `__TOOL_PACKAGE__` is unique — never rename it without updating the Dockerfile `COPY`/`touch` lines.
- The page calls the API with **relative paths** (`fetch('echo')`).
- No request depends on this process's memory; persistent state goes to `core/state/`. Secrets only via `vault_store.scoped("__TOOL_NAME__")` with the kinds declared in the manifest.
- Every endpoint that touches outside systems needs a smoke/unit test that does not need them (fakes).

## Gotchas
- (none yet — write down every surprise you hit here.)

## Tests
- `tests/smoke/test___TOOL_PACKAGE__.py` (live, via `scripts/smoke.sh`); add unit tests under `tests/unit/` for logic that needs no server.

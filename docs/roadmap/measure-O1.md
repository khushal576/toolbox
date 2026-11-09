# Roadmap O1 — no-code diet (2026-11-10)

Method: `docker stats --no-stream` on every `toolbox-*` container, **idle** (no requests since the container started),
before and after. Host: 7.5 GiB. "Before" = the stack as it ran after the 2026-11-09 pull/rebuild; "after" = after the
changes below, then `docker compose restart toolbox rt-data rt-light singletons rt-datadiff` so lazily loaded tools did not
inflate the reading (a smoke run loads tools in every runtime and adds ~100 MiB — measure before running it).

## What was changed
- `.env`: `TOOLBOX_WEB_WORKERS=1` (was 4), `TOOLBOX_DATA_WORKERS=1` (was 2).
- `api/manifest.yaml`: DataDiff `scaling: {min: 1, max: 4}` (was min 2). The compose pool stays 4 and `TOOLBOX_WORKER_SCALING`
  stays `1:3` — the autoscaler keeps only the minimum running when idle and still scales up under load.
- Switched off (Settings / `workspace.yaml`): cookie-lab, header-reference, http-methods-status, packet-journey, vlan-designer,
  subnet-calc, dns-lookup, sharepoint, notebook, mini-sheet.
- Tests only: smoke tests skip switched-off tools (`tests/smoke/conftest.py`); the traffic test uses `encode-decode`;
  `test_autoscale` expects `(1, 4)`.

## Memory (MiB, idle)
| Container | Before | After |
|---|---|---|
| toolbox (gateway) | 243.6 | 59.5 |
| rt-data | 106.9 | 36.6 |
| rt-datadiff (all running replicas) | 74.6 (2) | 36.2 (1)* |
| rt-light | 38.2 | 40.2 |
| singletons | 38.1 | 38.6 |
| worker | 21.8 | 21.8 |
| postgres / redis / docker-proxy | 38.1 | 45.0 |
| seaweedfs | 49.8 | 75.0 |
| rt-ssh / rt-pgtools / rt-latex / rt-notebook (on-demand) | 164.9 | 213.4** |
| **Total** | **775.9** | **603.7** |

\* the second replica was still being stopped by the autoscaler when this was taken.
\** on-demand runtimes were still awake from earlier use (they sleep after 15–30 min idle) — not a result of the diet.
Excluding them and SeaweedFS/Postgres noise, the always-on tool containers went from about 520 to about 230 MiB.

## Not measured / left open
- DataDiff scale-up under load with `min: 1` was not load-tested (only the minimum changed; the D3 logic is unchanged).
- Latencies: home page and tool pages answer in 2–6 ms warm; first request of a tool pays its import (unchanged by O1).
  With one web worker a very busy session queues requests instead of spreading over 4 processes.

## Undo
Delete the two `.env` lines (or raise them), set `min: 2` back in `api/manifest.yaml` and rebuild, and flip the tools back on
in Settings. See `docs/runbook.md` §6.

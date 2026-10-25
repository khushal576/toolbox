# Measurement after roadmap C4 (2026-10-25)

Same laptop as `baseline.md` (8 CPUs, 7.5 GB RAM). `docker stats` working-set memory, idle (no requests), every
container freshly restarted. Compare with `baseline.md` (S0.2), `measure-A3.md` and `measure-B9.md`.

## Images (disk)

| Image | Size | Runs as | TeX Live |
|---|---|---|---|
| (before C1) one image | 1.35 GB | everything | yes |
| `gateway` | 241 MB | `toolbox` (workspace UI + proxy) | no |
| `light` | 187 MB | `rt-light` | no |
| `data` | 629 MB | `rt-data`, `singletons` | no |
| `pgtools` | 267 MB | `rt-pgtools` (on demand) | no |
| `ssh` | 250 MB | `rt-ssh` (on demand) | no |
| `latex` | 746 MB | `rt-latex` (on demand) | **yes — the only one compose runs** |
| `worker` | 647 MB | `worker` (jobs) | no (was the 1.2 GB `full` image until C4) |
| `full` | 1.2 GB | not run by compose (single-container `docker run` only) | yes |

## Memory

| Container | All awake, nothing opened | On-demand runtimes asleep |
|---|---|---|
| toolbox (gateway, 4 workers) | 177 MiB | 195 MiB |
| rt-data (2 workers) | 104 MiB | 104 MiB |
| rt-light | 37 MiB | 37 MiB |
| singletons | 38 MiB | 38 MiB |
| worker | 22 MiB | 22 MiB |
| rt-latex / rt-pgtools / rt-ssh | 37 + 38 + 39 MiB | **0** (stopped) |
| docker-proxy | 3 MiB | 3 MiB |
| postgres + redis + seaweedfs (state services) | 26 + 9 + 114 MiB | same |
| **Total** | **643 MiB** | **548 MiB** |

After the three tier-4 tools were actually used (LaTeX page + a TikZ compile, Schema Copy / Data Dumper pages,
SSH & SFTP server/transfer lists), their containers held **168 MiB** (latex 38, pgtools 55, ssh 75); the supervisor
stopped them after the idle timeout and that memory went back to **0**. A real LaTeX compile or a dump preflight
peaks higher while it runs and is freed the same way.

## Reading these numbers honestly

- Against the very first measurement (one container, every tool imported at startup: 174 MiB; 32 MiB after lazy
  loading in A3) the whole stack is BIGGER at idle: phase B added the state services (~150 MiB, mostly SeaweedFS)
  and phase C gives every container its own Python floor (~37 MiB each). That was the trade for sessions/jobs/files
  surviving restarts, several workers, and per-runtime images.
- What C3/C4 improve is the cost of a tool you are NOT using: heavy tier-4 runtimes cost nothing when idle, and
  the images that run all the time no longer carry TeX Live. Adding more heavy tools now adds disk, not idle RAM.
- Knobs for a small machine (`.env`): `TOOLBOX_WEB_WORKERS=1` (gateway −~110 MiB), `TOOLBOX_DATA_WORKERS=1`
  (rt-data −~40 MiB). The state services could be swapped for lighter ones (e.g. Garage instead of SeaweedFS).

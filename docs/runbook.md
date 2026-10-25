# Toolbox runbook

How to run, update, back up and fix Toolbox — written for the owner, no development knowledge needed.
Everything is run from the repo folder (`toolbox/`). Architecture details: `../CLAUDE.md`.

## 1. Daily use

| What | Command / place |
|---|---|
| Start everything | `docker compose up -d` |
| Stop everything | `docker compose down` (keeps all data) |
| Open Toolbox | http://localhost:8000 |
| See what's going on | **📊 Status** in the sidebar (red/amber number = something needs a look) |
| Logs of one part | Status page → "logs" button, or `docker compose logs -f <service>` |
| What is running | `docker compose ps` |

**Never run `docker compose down -v`** unless you mean it: `-v` deletes the data volumes (database, files).

What runs (one machine, Docker Compose): `toolbox` (the gateway: workspace page + routing, port 8000),
`rt-light` / `rt-data` / `rt-datadiff` (×2–4) / `rt-pgtools` / `rt-ssh` / `rt-latex` (the tools, grouped by what
they need), `singletons` (SQL Studio + Schema Map), `worker` (×1–3, background jobs), `postgres`, `redis`,
`seaweedfs` (file storage), `docker-proxy` (lets the gateway start/stop tool containers — nothing else).

Some containers stop on purpose:
- **asleep (on demand)** — LaTeX, SSH & SFTP, Schema Copy/Data Dumper containers stop after 15 min unused and start
  again in 1–2 s when you open the tool.
- **standby (scaled down)** — extra DataDiff replicas / workers are stopped when there's no load and started under
  load.
A plain `docker compose up -d` starts all of them again; they go back to sleep by themselves.

## 2. Update after pulling new code

```bash
git pull
docker compose up -d --build
```
Then open the Status page: everything green? If a tool shows "unavailable", see section 5.

## 3. Backups

**What a backup contains:** the database (Vault secrets, projects, sync positions, dump catalogue, history), every
stored file (dumps, generated scripts, saved datasets, DataDiff results, staged uploads), `.env` (holds the Vault
key) and the on/off settings. Redis is not included (only short-lived data).

```bash
scripts/backup.sh                          # → backups/toolbox-YYYY-MM-DD_HHMMSS.tar.gz (keeps the last 7)
BACKUP_KEEP=14 scripts/backup.sh           # keep more
BACKUP_DIR=/media/usb/toolbox scripts/backup.sh   # write somewhere else
```
- Runs while Toolbox is up (no downtime), ~30 s. The Status page shows **Backups: last …** and reminds you after
  7 days.
- **The archive contains the Vault key** — treat it like a password: keep it private (it is created readable only
  by you), and copy it to a second place (external disk / your cloud drive). A backup on the same disk doesn't
  survive a broken disk.
- **`.env` alone is precious**: without `TOOLBOX_VAULT_KEY` the saved secrets can't be decrypted.

**Automatic daily backup** (optional): `crontab -e` and add (adjust the path):
```
30 2 * * *  cd /home/khushal/Desktop/git_repo_directory/toolbox && scripts/backup.sh >> backups/backup.log 2>&1
```

## 4. Restore

```bash
scripts/restore.sh backups/toolbox-2026-10-25_183203.tar.gz     # asks you to type "restore"
```
- **Replaces** the current data with the backup's (anything newer is lost). The tool containers are stopped
  during the restore and started again at the end (~15 s + start-up).
- A different current `.env` is kept as `.env.before-restore-<time>` before the backup's `.env` is put back.
- The database restore is one transaction: if it fails, the database is left as it was.

**Moving to a new machine:** install Docker, `git clone` the repo, `docker compose up -d --build` once, copy the
backup file over, `scripts/restore.sh <file>`.

Tested: a backup of this stack restored into a fresh second copy (all tables, files, secrets and settings
identical; a secret decrypted with the restored key).

## 5. When something is wrong

| You see | What it means / what to do |
|---|---|
| "**X is starting or unavailable**" on a tool | Its container is down or still starting. Wait 10 s and reload. Still there: Status page → that container's logs, or `docker compose up -d`. |
| A **red container** on the Status page | Stopped or unhealthy. `docker compose up -d` restarts it; the logs button shows why it stopped. |
| "**keeps restarting**" | It crashes on start — read its logs (often a missing `.env` value or a full disk). |
| "**N server errors in the last hour**" | Status → Recent errors shows which request failed and the message. |
| "**jobs are waiting**" | More background work than workers. It scales to 3 workers by itself; persistent backlog → check the worker logs. |
| "**No backup yet**" / "**last backup N days ago**" | Run `scripts/backup.sh`. |
| **VaultKeyMismatch** / saved connections don't work | `.env` has the wrong `TOOLBOX_VAULT_KEY`. Put back the right `.env` (from a backup). Never generate a new key while secrets exist. |
| **Disk filling up** | Status → Storage shows who uses space (dumps, Duck Lab files). Delete old dumps in Data Dumper. Old Docker images: `docker image prune` (safe; removes unused images only). |
| You changed `docker_proxy_rules` in docker-compose.yml | `docker compose up -d --force-recreate docker-proxy` (compose doesn't notice that change by itself). |

## 6. Settings you can change (in `.env`, then `docker compose up -d`)

| Setting | Default | What it does |
|---|---|---|
| `TOOLBOX_HOST_PORT` | 8000 | Port of the website on this machine |
| `TOOLBOX_WEB_WORKERS` | 4 | Gateway processes (1 = less memory, ~40 MB each) |
| `TOOLBOX_DATA_WORKERS` | 2 | Processes of the data tools container |
| `TOOLBOX_WORKER_SCALING` | `1:3` | Min:max background-job workers |
| `TOOLBOX_IDLE_TIMEOUT_S` | (manifests: 900) | Minutes-unused before LaTeX/SSH/pgtools sleep, in seconds |
| `TOOLBOX_SLOW_MS` | 2000 | When a request counts as "slow" on the Status page |
| `TOOLBOX_DATABASE_URL` | bundled Postgres | Use your own Postgres instead (a dedicated `toolbox` database) |
| `TOOLBOX_DB_PASSWORD`, `TOOLBOX_S3_ACCESS_KEY`, `TOOLBOX_S3_SECRET_KEY` | local-only defaults | Passwords of the bundled services |
| `TOOLBOX_VAULT_KEY` | (moved here in B7) | The Vault key — **back it up, never change it** while secrets exist |

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

**Use it as an app (own window, icon in the app menu/taskbar):** open http://localhost:8000 in Chromium/Chrome →
the install icon at the right end of the address bar (or ⋮ menu → *Cast, save and share* → *Install page as app…*)
→ **Install**. From then on start "Toolbox" like any program; right-click its icon for *Status* / *Settings*.
Toolbox must be running (`docker compose up -d`) — the app is only a window onto it. Uninstall: in the app
window, ⋮ → *Uninstall Toolbox*. (Without installing: `chromium --app=http://localhost:8000`.)

**Your data files (Vault → Vault Data → ⬆ Load files):** put files you want to load into **`~/toolbox-data`** (Toolbox sees it read-only;
it can never change or delete them). Then open **Vault** → **📦 Vault Data** → *Load files* → *Data folder* → pick a file, a folder or a pattern →
choose a workspace (default: **system**, the built-in one) and a table name → *Load*. Uploading through the page or loading from a link works too. Browse the
result under *Tables*. Another folder: set `TOOLBOX_DATA_DIR=/path/to/folder` in `.env`, then
`docker compose up -d`.

**Querying your tables:** open **Duck Lab**, pick tables from its Tables bar (they appear as `workspace.table`) and write SQL there,
e.g. `SELECT c.country, sum(o.amount) FROM sales.orders o JOIN crm.customers c USING (customer_id) GROUP BY 1`.
Use *📦 Save to Vault Data* to keep a result as a table (a bare name goes to the `system` workspace).

**Loading only some columns, renaming, casting, hiding sensitive data:** in **Vault → Vault Data → ⬆ Load files** pick the data, then
press **🔍 Preview columns** (step 2). You get one row per column: untick *Keep* to leave it out, type a new name under *Load as*,
choose a *Type* (a value that doesn't convert becomes empty and you are told how many — or choose "stop the load"), and put a value
under *If empty* to fill blanks. *Protect* hides sensitive data while loading: **mask** (`j***@mail.com`, `**** 1234`), **hash** (a one-way
code — the same person always gets the same code, so joins still work; needs a secret *salt* that is never stored), **redact** (fixed
text), **empty** (NULL) or **shuffle** (values are swapped between rows: each row gets another row's value — realistic but not the right
person's). Columns that look sensitive (e-mail, phone, Aadhaar, PAN, card, names, addresses…) are pre-set and marked orange — it is only a
guess, check it. Nothing happens until you press Load; if you never press Preview the file loads as is. **Same structure again?** *Save as
template…* and later *Apply template* (by column name, or by position for files without headers) — templates keep names, types and the
kind of protection, never salts or seeds. A **masked copy** of a table already in Vault Data: Tables → open the table → *Copy with column
map…*. Not available for database copies or read-in-place tables. A big shuffle uses more memory than a plain load.

**Using tables in other tools:** Duck Lab, DataFrame Studio, SQL Studio (import dialog) and DataDiff list your
tables under **📦 workspace** in their "Load from Vault" lists; their **📦 Save to Vault Data** buttons save a
result as `workspace.table` (just `table` = it goes to **system**). **Copying tables out of a database** (e.g. staging for a migration): save the
connection in the Vault once, then Vault Data → Load files → *Database* → pick the connection → *Show tables* → tick tables (or
write one SELECT) → workspace → *Load*. The database is only read.

**Tables in AWS S3 (or MinIO etc.):** Vault Data → Load files → *S3* → *+ new S3 location* (name, access key, secret, region; an
endpoint only for non-AWS storage) → *Test* → *Save to Vault*. Then type `s3://bucket/folder/` or a pattern →
*Load* (copies it in) or tick *Read in place* (stays in S3, read on every query).

**Knowing your data:** Vault → 📦 Vault Data → Tables → a table → *Profile columns* (empty values, distinct values, min/max,
averages, most common values) and *Suggest joins* (which columns match other tables). In Vault Data → SQL, the 🔗 next
to a table does the same and writes the JOIN for you; *📊 Chart* draws a result.

**A terminal on a server (SSH & SFTP → Terminal):** save the server once in the Vault (*Add SSH server*), then pick it
and press *Open a terminal*. It logs in once and stays logged in — type as many commands as you like; a page reload
brings you back to the same session. It closes when you type `exit`, press ✕, or after 30 minutes without the page
open. Servers saved as read-only get no terminal.

**Duck Lab / DataFrame Studio** work only with Vault Data tables (left *Tables* list → *Load*; loaded tables turn
green, ✕ unloads). Load as many as you need: in Duck Lab each is a SQL table (write your JOIN); in DataFrame Studio
the first is `df` and the others are variables named after the table (`df.merge(customers, on="customer_id")` in
Query). *📊 Column stats* shows empty / distinct / min / max / average per column in the grid header.
**Cleaning without code (DataFrame Studio):** click the **⋮** on a column header for its empty %, a suggested fix and the actions
that fit it, or use the **Clean** box (pick what to fix, pick the columns — one step can fix many — press *Check*, then *Add to
pipeline*). The **Formula** box makes a new column from one line (`ratio = a / b`; names with spaces in backticks). In the Pipeline
list every step can be switched off/on (it stays listed), moved ▲▼ or removed ✕; a change that would break a later step is refused.
The *Query* box (full Python) is still there for anything else. Inside any tool
the left menu hides — press ☰ (top left) or Ctrl+K to open it.

**Never run `docker compose down -v`** unless you mean it: `-v` deletes the data volumes (database, files).

What runs (one machine, Docker Compose): `toolbox` (the gateway: workspace page + routing, port 8000),
`rt-light` / `rt-data` / `rt-datadiff` (×2–4) / `rt-pgtools` / `rt-ssh` / `rt-notebook` / `rt-latex` (the tools, grouped by what
they need), `singletons` (SQL Studio + Schema Map), `worker` (×1–3, background jobs), `postgres`, `redis`,
`seaweedfs` (file storage), `docker-proxy` (lets the gateway start/stop tool containers — nothing else).

Some containers stop on purpose:
- **asleep (on demand)** — LaTeX, SSH & SFTP, Schema Copy/Data Dumper containers stop after 15 min unused and start
  again in 1–2 s when you open the tool.
- **standby (scaled down)** — extra DataDiff replicas / workers are stopped when there's no load and started under
  load.
A plain `docker compose up -d` starts all of them again; they go back to sleep by themselves.

### Connecting SharePoint (SharePoint Lists tool)

In the Microsoft Entra admin center create an **app registration** (this tenant only), then in the tool press **+**:
- **Sign in as me, no app registration** — just a name and the site URL(s) (copy them from the browser's address bar).
  The tool uses Microsoft's own public sign-in app; you type your username and password (and MFA) on Microsoft's page
  at microsoft.com/devicelogin, never into the tool. If Microsoft says it needs administrator approval, your IT admin
  must approve "Microsoft Graph Command Line Tools" once — or use the next option with your own registration.
- **Sign in as me, with your own app registration** — app registration → *Authentication* → *Allow public client flows* = Yes; *API permissions* →
  Microsoft Graph → **Delegated** → `Sites.ReadWrite.All` (or `Sites.Read.All` for a read-only connection; your admin may
  need to consent). Paste the *Directory (tenant) ID* and *Application (client) ID*, add the site URLs, Save, then enter the
  shown code at microsoft.com/devicelogin.
- **App secret** — *Certificates & secrets* → new client secret; *API permissions* → **Application** → `Sites.Selected`
  (an admin then grants the app each site) or `Sites.ReadWrite.All`. Paste tenant id, client id and the secret value.
Connections are stored in the Vault (back up `.env` as usual). Nothing is written to SharePoint until you press
*Approve & write* in the Review screen, and the tool never deletes anything.

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
| `TOOLBOX_IDLE_TIMEOUT_S` | (manifests: 900) | Minutes-unused before LaTeX/SSH/pgtools/Notebook sleep, in seconds (overrides Notebook's own 30 min too) |
| `TOOLBOX_SLOW_MS` | 2000 | When a request counts as "slow" on the Status page |
| `TOOLBOX_DATA_DIR` | `~/toolbox-data` | The folder Vault Data → Load files can read from (shared read-only) |
| `TOOLBOX_DATABASE_URL` | bundled Postgres | Use your own Postgres instead (a dedicated `toolbox` database) |
| `TOOLBOX_DB_PASSWORD`, `TOOLBOX_S3_ACCESS_KEY`, `TOOLBOX_S3_SECRET_KEY` | local-only defaults | Passwords of the bundled services |
| `TOOLBOX_VAULT_KEY` | (moved here in B7) | The Vault key — **back it up, never change it** while secrets exist |

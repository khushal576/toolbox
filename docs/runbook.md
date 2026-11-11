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

**Editing a small table by hand (Mini Sheet):** open **Mini Sheet** → *Open* → *Vault Data table…* (or paste from Excel, or open a CSV /
Excel / JSON file, or start a blank sheet). Click a cell and type; **Enter** goes down, **Tab** goes right, **F2** or a double-click edits
what is already there, **Esc** cancels. Paste straight from Excel with Ctrl+V; **Ctrl+D** fills down, drag the small square at the corner of the
selection to fill or continue a series; right-click for rows/columns (insert, delete, move, rename — double-click a header to rename) and the
column's *type*, sort and filter. **Ctrl+Z / Ctrl+Y** undo and redo (300 steps), **Ctrl+F** is find & replace. Yellow cells are changed since you
opened it, green rows are new, red cells don't fit their column's type. A cell starting with **=** is a formula: `=A1+B1`, `=SUM(A1:A9)`,
`=IF(B2>10,"big","small")` (also ROUND, AVERAGE, MIN, MAX, COUNT, CONCAT, LEN, UPPER, LOWER, TRIM, ABS, TODAY) — **formulas are saved as their
results**, and `A1` means the first column's first data row (the header isn't counted; it doesn't move when you insert or sort rows). **Save** puts it
back into Vault Data (a bare name goes to **system**); every cell is checked first, so nothing is silently turned empty — you get a list of the
cells to fix. If the table exists you can *replace it and keep a backup copy* (`<name>_backup_<date>`), replace it, or use another name. A table
opened as "first N rows" can only be saved under a new name. For small data only (50,000 rows); bigger files: Vault → Vault Data → Load files.
**Long text, several sheets, and "did I lose my work?" (Mini Sheet):** your work is **saved automatically** a couple of seconds after you stop typing
(the toolbar says *Draft saved ✓*), so a reload or a closed tab brings it back with a green *Restored your unsaved work…* bar (*Discard* throws it away; the
undo history is not kept). If the same browser has Mini Sheet open in two tabs, the second one pauses its autosave — click the note in the toolbar to make that
tab the one that is kept. To show long text in full, open a column's **⋮** menu → **Wrap text** (or *↵ Wrap* → *every column*): the rows grow to fit, and
drag the column edge to see the text re-wrap as you go. Double-click a cell in a wrapped column to edit it; **Alt+Enter** adds a line break inside the cell.
A workbook can have many **sheets** (tabs at the bottom): **＋** adds one, double-click a tab to rename it, right-click for duplicate / delete / move. An Excel file opens
**all** its sheets. A formula can read another sheet: `=Sheet2!A1` or `='My sheet'!B2:B9` (renaming a sheet updates those formulas; deleting it makes them `#REF!`).
*Save* saves the sheet you are looking at; **Save all sheets…** saves every sheet as its own Vault Data table (and saves nothing at all if any cell is wrong).
*Download → Excel* gives one file with all sheets. *Open → Close workbook* starts over.

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
| **VaultKeyMismatch** / saved connections don't work | `.env` has the wrong `TOOLBOX_VAULT_KEY` — or **no `.env` at all**: then only the containers with the old `vault_data` volume (data tools, singletons, worker) find the key, while Data Dumper / Schema Copy (`rt-pgtools`) and SSH & SFTP (`rt-ssh`) make up a new one per container and can't read the Vault. Put back the right `.env` (from a backup; the key also lives on the `vault_data` volume as `/app/data/vault/vault.key`), then `docker-compose up -d`. Never generate a new key while secrets exist. |
| **Disk filling up** | Status → Storage shows who uses space (dumps, Duck Lab files). Delete old dumps in Data Dumper. Old Docker images: `docker image prune` (safe; removes unused images only). |
| You changed `docker_proxy_rules` in docker-compose.yml | `docker compose up -d --force-recreate docker-proxy` (compose doesn't notice that change by itself). |

## 6. Settings you can change (in `.env`, then `docker compose up -d`)

| Setting | Default | What it does |
|---|---|---|
| `TOOLBOX_HOST_PORT` | 8000 | Port of the website on this machine |
| `TOOLBOX_WEB_WORKERS` | 4 (this machine: 1 since O1) | Gateway processes (1 = less memory, ~40 MB each). Raise it if many people use Toolbox at once |
| `TOOLBOX_DATA_WORKERS` | 2 (this machine: 1 since O1) | Processes of the data tools container |
| `TOOLBOX_WORKER_SCALING` | `1:3` | Min:max background-job workers |
| `TOOLBOX_IDLE_TIMEOUT_S` | (manifests: 900) | Minutes-unused before LaTeX/SSH/pgtools/Notebook sleep, in seconds (overrides Notebook's own 30 min too) |
| `TOOLBOX_TRUSTED_PLUGINS` | 0 (off) | Allow your own **Python** plugins in `plugins/` (`1` = on). They are trusted code with full access (database, secrets) — see `plugins/README.md` before turning it on. |
| `TOOLBOX_SLOW_MS` | 2000 | When a request counts as "slow" on the Status page |
| `TOOLBOX_DATA_DIR` | `~/toolbox-data` | The folder Vault Data → Load files can read from (shared read-only) |
| `TOOLBOX_DATABASE_URL` | bundled Postgres | Use your own Postgres instead (a dedicated `toolbox` database) |
| `TOOLBOX_DB_PASSWORD`, `TOOLBOX_S3_ACCESS_KEY`, `TOOLBOX_S3_SECRET_KEY` | local-only defaults | Passwords of the bundled services |
| `TOOLBOX_VAULT_KEY` | (moved here in B7) | The Vault key — **back it up, never change it** while secrets exist |

## Text Editor: finding names with AI (optional)

Mask → **🧠 Find names (AI)** needs a one-time download (~127 MB, runs entirely in your browser afterwards):
`./scripts/get-ner-model.sh`, then `docker-compose up -d --force-recreate rt-light`. Without it the button answers "The name
model is not installed"; everything else in Mask works. The files live in `./models/` (git-ignored); behind a TLS-inspecting
proxy run the script on the host (it trusts the host's certificates).

## Small-machine setup and how to scale back up (roadmap O1)

This machine runs the "diet" from `docs/roadmap/measure-O1.md` (idle memory ~776 → ~604 MiB). Everything is reversible:

| Change | To undo / scale up |
|---|---|
| `TOOLBOX_WEB_WORKERS=1`, `TOOLBOX_DATA_WORKERS=1` in `.env` | Raise the numbers (e.g. 4 and 2), then `docker compose up -d`. |
| DataDiff keeps 1 replica when idle (`scaling: {min: 1, max: 4}` in `api/manifest.yaml`) | Nothing needed: it adds replicas by itself under load (up to 4). For a permanent 2, set `min: 2` and `docker compose up -d --build`. |
| Background workers | Already automatic: 1 idle, up to 3 by queue length (`TOOLBOX_WORKER_SCALING`). |
| Tools switched off (cookie-lab, header-reference, http-methods-status, packet-journey, vlan-designer, subnet-calc, dns-lookup, sharepoint, notebook, mini-sheet) | Home → Settings → switch them on (immediate, no restart). The smoke tests skip tools that are off. |

## Connect Claude to Toolbox (MCP, read-only — roadmap K2)

Claude can use Toolbox's data tools (list tables and connections, preview, run a SELECT, compare two data sets) instead of writing scripts.
Nothing can be changed through it, and Claude never sees a database password: it names a saved connection and Toolbox does the rest.

1. Keep the stack running (`docker compose up -d`).
2. In Claude Code run once (change the path to where this repo is):
   `claude mcp add toolbox -- docker compose -f /home/khushal/Desktop/git_repo_directory/toolbox/docker-compose.yml run --rm -T --no-deps worker python -m mcp_server`
   For another MCP client use the same command with `docker` as the program and the rest as arguments. It starts in about a second and stops when the client closes.
3. In Claude ask for something like "call toolbox_guide, then show me the tables". The first call explains what exists, the limits and the rules.
4. **Label your connections** (Vault → each saved connection → Environment: Prod / Non-prod). A connection without a label is treated as **prod**: tighter limits (100 rows,
   15 s) and a warning on every result. Nothing ever writes to a database.
5. **Give the database user read-only rights** as well — it is a second, outside safety net.
6. **See what the AI did:** `docker compose run --rm -T --no-deps worker python -m mcp_server recent 30` (time, session, tool, connection, prod/non-prod, rows, how long, refusals).
7. Limits can be changed in `.env` (defaults): `MCP_ROWS=200`, `MCP_MAX_ROWS=5000`, `MCP_PROD_ROWS=100`, `MCP_PROD_MAX_ROWS=500`, `MCP_MAX_BYTES=1000000`, `MCP_SECONDS=30`,
   `MCP_PROD_SECONDS=15`, `MCP_ACTION_SECONDS=20` (how long `run_action` waits for a tool's answer), `MCP_COMPARE_MAX_ROWS=50000`, `MCP_PROD_COMPARE_MAX_ROWS=5000` (compose passes them to the worker; a change applies the next time Claude starts the server).
**Scripts:** ask Claude "generate an INSERT script for system.orders into sales.orders (postgres)". Toolbox writes the script as text — it never runs it and never connects to the target;
you review it and run it yourself (first on a non-prod database). It refuses to build a script from a partial result (more than 5,000 rows, or 500 for prod / unlabelled sources) — raise
`MCP_SCRIPT_MAX_ROWS` / `MCP_PROD_SCRIPT_MAX_ROWS` in `.env` if you really need more. PostgreSQL syntax is verified end to end; SQL Server and Oracle syntax follows the documented rules but was **not** run against real engines.
Only PostgreSQL connections can be queried through it for now; SQL Server / Oracle data can be staged into Vault Data first.

### Allow the AI to change things — safely (AI Access, roadmap K4)

By default Claude can only read. Open **🤖 AI Access** in the sidebar:
1. **Set your PIN first** (6+ characters, only you know it). It is needed to allow changes and to resume after a stop. Write it down — there is no recovery except clearing it in the database.
2. **⛔ Stop AI access now** — one click (no PIN): every AI request is refused (even reading) and all permissions are removed. **Resume** needs the PIN and comes back read-only.
3. **Allow changes for a limited time** — pick what (a Vault Data workspace, a database connection or an SSH server), which actions, how long (15 min – 8 h) and an optional row limit, then your PIN. Prod / unlabelled
   targets need an extra tick. There is no permission to delete or drop anything. The permission ends by itself; **Revoke** ends it at once (no PIN).
4. **What the AI did** — the live timeline: time, session, tool, which connection (prod in red), the exact query/command (click the row), result, rows, duration. No results or secrets are stored.
5. Same things from a terminal: `docker compose run --rm -T --no-deps worker python -m mcp_server status | kill | resume | set-pin | grants | revoke <id> | grant <kind> <target> --actions …`
6. **Know the limit:** Toolbox has no login. If your AI client can also run shell commands on this machine, keep those on manual approval (the PIN stops it from granting itself rights, but it could still read this page or press Stop).

### Let Claude debug a server over SSH (roadmap K5)

1. Save the server in the Vault (**Add SSH server**, confirm its host key) and set its **Environment** (Prod / Non-prod). Claude can only connect to servers whose host key is pinned.
2. By default Claude cannot use SSH at all. When you want help: **🤖 AI Access → Allow changes for a limited time → SSH server**, pick the server, tick *Run read-only diagnostic commands*, choose how long (15 min – 8 h), enter your PIN. (Prod / unlabelled servers need the extra tick.)
3. Claude then uses `ssh_servers` and `ssh_run`. Only **read-only** commands work: `ls cat head tail wc du df stat file uname uptime free id date find grep sort uniq cut ps ss ip-show journalctl systemctl-status docker ps/logs/stats git status/log/diff` and
   a plain `|` pipe into `grep/head/tail/wc/sort/uniq/cut`. Anything that writes, redirects, chains (`;` `&&`), substitutes (`$` `` ` ``), runs `sudo`/shells/editors, follows logs (`-f`) or reads keys / `.env` files is refused and never sent.
4. Each command is limited to 30 s and 64 KB (15 s / 32 KB on prod); a command that runs too long is killed on the server. Likely secrets in the output (`password=…`, private keys, tokens) are replaced by `[redacted]`.
5. **Watch it live** on the AI Access page (exact command, exit code, time). **Stop** at any moment with the big red button; the permission also ends by itself.
6. Remember: logs can still contain things you would not want shared. Enable a server only while you need it, and prefer non-prod.

### Let Claude clean and reshape a table (roadmap K6)

Claude can use DataFrame Studio's cleaning steps (fill empty values, change types, clean text, replace, split/merge columns, dates, duplicates, outliers, bins, rename, filter) and formulas on a Vault Data table.
1. **Preview needs no permission:** ask "clean `system.orders`: cast amount to number, fill empty with 0, add gross = amount * 1.18". Claude shows the exact pandas code, rows before/after, what each step changed and a sample. Nothing is stored.
2. **Keeping the result needs your permission:** 🤖 AI Access → Allow changes → *Vault Data workspace* → pick or type the target workspace (a new name is fine) → *Create a NEW Vault Data table* (and, only if you want it, *Replace a table*) → time → PIN.
3. Claude then does a **dry-run** (shows the plan: target table, rows, columns, what it would replace) and, if that is what you want, **confirms** (a one-time code, valid 10 minutes, only for exactly that plan — it stops working if the source table changed).
4. The new table is read back and checked. The **source table is never changed**; *Replace* keeps the old table as `<name>_backup_<time>`. Every step is in the audit timeline and stored in the new table's history.
5. Limits: 200,000 rows (raise `MCP_TRANSFORM_MAX_ROWS` in `.env`), 30 steps. Tables with exact **decimal** columns need a *Change type* step before arithmetic; converting decimals to numbers can round them (Claude is told, and the result says so).

## Set up the AI helper (roadmap H1 — the "Ask Claude" engine)
What it is: a small background service on **your computer** (not in Docker) that lets Toolbox ask your own Claude Code, using your Claude Pro login — no API key, no extra bill.
It can only use Toolbox's own tools (no shell, no file changes). The panel is the **🤖 Ask Claude** button at the top right of Toolbox (or **Ctrl+J**): hidden until you open it, it sits beside whatever tool you are using. This section sets up the engine behind it.

1. Make sure Claude Code works and is logged in: run `claude auth status` in a terminal (it should say `loggedIn: true`, method `claude.ai`).
2. In the Toolbox folder run: `python3 ai-bridge/install.py install --write-env` — it creates a private key file, starts the service, and adds two lines to `.env` (a backup of `.env` is kept).
3. Restart the gateway so it learns the address: `docker compose up -d --no-deps toolbox`.
4. If your computer has a firewall (ufw), allow Toolbox to reach the helper — once: `sudo ufw allow from 172.16.0.0/12 to any port 8787 proto tcp` (only Docker's private networks).
5. Check: open `http://localhost:8000/api/helper/status` — it should say `"state":"ready"`. Then click 🤖 in Toolbox and ask something. **New chat** starts a fresh conversation; **Chats ▾** goes back to an earlier one.

It starts by itself every time you log in. To start it also at boot before login (optional): `loginctl enable-linger $USER`.
What the status words mean: **ready** · **not_logged_in** (run `claude`, then `/login`) · **limit_reached** (your Pro usage limit; it says when it resets) · **bridge_down** (`systemctl --user start toolbox-helper`) · **not_set_up** (do steps 2–3) · **token_mismatch** (run step 2 and 3 again).
Check / stop / remove: `python3 ai-bridge/install.py status` · `systemctl --user stop toolbox-helper` · `python3 ai-bridge/install.py uninstall` (`--purge` also deletes its settings).
**Moving data with Claude (query → table → JSON → database).** Ask in the panel, for example: "stage `SELECT * FROM events` from dev-db into scratch.events, flatten the payload column, and load it into sales.events on dev-db". Claude does the reading itself; every step that **writes** (a Vault Data table, or rows added to a database table) first shows an **approval card** in the panel: check what/where/rows (and Prod/Non-prod), type your PIN, click **Approve** — it allows that one action for 10 minutes. Nothing is ever updated or deleted: loading only **adds** rows to a table that already exists, all or nothing. Set your PIN first on **AI Access**.
**Recipes (repeat without AI):** when it worked, say "save this as a recipe". Later open **Recipes ▾** in the panel and press **Run (no AI)** — no tokens are used; writes still stop at an approval card, and you press **Continue** after approving. If a table the recipe reads has changed, it stops and asks before running.
**Chats are kept** on your computer (`~/.config/toolbox-helper/chats.db`), so after a reload — or in another browser — the panel shows your last chat again (🕘 lists the earlier ones; scroll up for older messages). The ✕ next to a chat removes it from the list only. **Each tool has its own policy** (⚙️ → pick the tool at the top; it opens on the tool you are in). Under every answer there are 👍 / 👎: a 👎 with a short note ("do not paste rows") is kept, and in ⚙️ you see those notes for that tool with **Make it a rule** — so the helper improves from your own review, tool by tool, and you can see 👍/👎 counts over time. **DataFrame Studio** is always "give me the command": Claude sees your current columns and the steps you already added, so it writes only the next step (paste it as a new Custom Python step). **Mode** in other tools: the pill above the box switches between **⌨️ Give me the command** (default: Claude gives code to copy and run yourself — fastest, nothing is run) and **⚡ Run it** (Claude does it with Toolbox's tools). **Policy:** the ⚙️ button opens a plain-text policy (how short to answer, whether to show data, habits…) — edit it and press Save; it applies from your next question (file: `~/.config/toolbox-helper/policy.md`). It can change style, never the safety rules (approvals, PIN, read-only).
After Claude **saves** something (a table, rows), the tool you are looking at reloads by itself so you can check it; a plain preview or question changes nothing on screen.
Usage counts against your Pro limits (shared with claude.ai and VS Code). Keep Toolbox on localhost — anyone who can open it could spend your quota.

## Remove a tool you no longer want (roadmap P3)

Just switching a tool **off** in Settings is reversible and enough in most cases (it then uses no memory). To remove it for good:
1. `python3 scripts/remove_tool.py <tool>` — a **dry run**: it lists what it would delete, **what still uses the tool** (it refuses while other tools import it or call its URL), and the data it would leave behind.
2. If that looks right: `python3 scripts/remove_tool.py <tool> --apply` (add `--confirm <tool>` — typing the name — when the tool is enabled, when Toolbox is not running, or when it has stored data).
3. Its saved data is **never deleted automatically**: Postgres tables, Vault entries and S3 files stay (the plan prints how to drop them yourself if you want). Its Docker volume is kept unless you add `--remove-volumes` (the files in it are then gone for good).
4. Then `docker compose up -d --build` so the image no longer contains it. Mentions of the tool in other docs are listed for you to tidy up; they are not rewritten.
The core tools (Vault, DataDiff) can't be removed with the script.


# SSH & SFTP — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture and `../KNOWLEDGE_MAP.md`
for the symptom→file map across every tool. This is the fast-orientation version scoped to this folder.

## What this tool is

Browse files, upload/download, make folders, rename, delete (a file or an EMPTY folder only), and run
commands on servers **saved in the Vault** (kind `ssh_server`; added on the Vault page's "Add SSH server"
form, never typed here). Built to be safe and stable rather than featureful: no interactive terminal, no
recursive delete, no port forwarding.

## Where things live

| Concern | File |
|---|---|
| Connecting: host-key pinning, auth, timeouts, keepalives, error mapping | `../core/ssh_client.py` (shared with the Vault form) |
| Vault entry shape / safe public view / `update_secret` (to pin a key) | `../core/ssh_client.py` (`public_view`), `../core/vault.py` (`update_secret`) |
| The Vault "Add SSH server" form + `POST /test-ssh-server` | `../vault/ui/index.html`, `../vault/server.py` |
| Cached browsing session per server (health-checked, reconnect once, idle reaper) | `sessions.py` |
| List/mkdir/rename/delete/download, the resumable upload, commands | `engine.py` |
| Transfer + command history (Postgres schema `ssh_sftp`, B6; SQLite standalone) and staged uploads (S3 storage + local cache, B8) | `state_store.py` |
| Upload/command jobs in the `worker` container + log tail (shared `../core/jobs/runner.py`) | `runner.py` |
| API + page | `server.py`, `ui/index.html` |

## Safety rules (each is tested — see the end)

- **Host keys are pinned.** The Vault entry stores the server's key; every connection must present exactly
  it (`core/ssh_client.open_client` loads it as a known host key, so the right key TYPE is negotiated and a
  server offering several types can't cause a false alarm). No pin → `HostKeyUnverified` (UI asks the user
  to confirm the fingerprint — the Vault form does this BEFORE any credential is sent); a different key →
  `HostKeyMismatch`, blocked loudly. `POST /servers/{id}/trust` re-fetches the key and pins it only if it is
  still the fingerprint the user confirmed, and **refuses to re-pin a server that already has a pin** — a
  changed key must be resolved by deleting/re-adding the server in the Vault, deliberately.
- **Only `ssh_server` entries** can be used (`sessions.resolve` checks the id's kind) — a database
  credential's id can never be coaxed into an SSH login. `GET /servers` returns only non-secret fields.
- **No agent, no ~/.ssh keys**: only the Vault credential is tried. Errors are plain sentences, scrubbed.
- **Read-only servers** (`read_only` in the Vault entry) refuse upload, mkdir, rename, delete and commands;
  browsing and download still work.
- **Dangerous commands** (`engine.DANGEROUS`: `rm -rf /` or `~`, mkfs, dd to a device, shutdown/reboot, fork bomb,
  recursive chmod/chown of `/`) need an explicit confirm (HTTP 428 → the page asks). A safety net, not a
  sandbox: the account can still do anything else it is allowed to. Command text is stored in the history
  (output is not) and is visible in the remote process list — don't put passwords in commands.

## Uploads: why they are staged, atomic and resumable

`POST /servers/{id}/upload` streams the file to `data/ssh-sftp/stage/<id>.stage` (hashing as it goes, never
holding it in memory — a 400 MB upload peaked at ~125 MiB container memory), THEN a background job sends it:
1. refuses if the target exists and overwrite wasn't ticked, or is a folder (no retries wasted on that);
2. writes to `.<name>.<sha256-prefix>.part` next to the target, never to the real name;
3. on a dropped connection/timeout it reconnects and **resumes from the size already on the server** (≤ 6
   attempts, back-off); permission / missing folder / disk-full / "already exists" are NOT retried;
4. verifies size, then SHA-256 (`sha256sum` on the server, else a read-back up to 256 MB, else it says
   "size verified only"). A resumed prefix that hashes wrong is detected, deleted and re-sent from zero;
5. renames into place (`posix_rename` when overwriting — atomic; falls back with a note if unsupported);
6. a failure or Stop keeps the staged file and the remote `.part`, so **Retry** continues instead of
   restarting ("Replace & retry" also allows overwriting). Staged files of finished/old (7 days) transfers
   are removed at startup (`state_store.sweep_stage`, storage + local). A transfer whose job died is marked
   failed; Retry resumes.

**Since roadmap B8** the staged file is uploaded to S3 storage right after it is received
(`state_store.publish_stage`, keys `ssh-sftp/<id>/<id>.stage`) and the send runs as a job in the `worker`
container; `engine.run_upload` gets the file via `store.fetch_stage` (downloads it when this process has no
local copy) and deletes it everywhere on success. Verified: a 300 MB upload with the worker killed at ~83 MB →
marked failed after the heartbeat expired → local stage deleted → Retry downloaded the stage from storage and
"resum[ed] from 93,749,248 of 300,000,000 bytes", SHA-256 verified; two 150 MB uploads ran on two workers in
parallel (`--scale worker=2`) and survived a web restart, both checksums identical.

## Things that will bite you if you don't know them

- `sessions.is_dead` separates "the connection died" (EOFError/SSHException/OSError **without** errno) from
  "the server said no" (OSError **with** errno) — only the former reconnects. SFTP reports many failures as a
  bare `Failure`, so `make_dir`/`rename` pre-check existence to give real messages.
- Long jobs (upload, download, command) use their OWN connection; only browsing uses the cached one.
- `paramiko`'s `known hosts` name for a non-22 port is `[host]:port` (handled in `open_client`).
- The page's status is "connected" only after the first listing succeeds.
- **Jobs and staged files are out of process since roadmap B8** (worker jobs via `core/jobs/runner.JobRunner`
  with `quiet=True` — a command's log IS its output pane; Redis log tail with `since` paging, written in batches
  so 3000 output lines aren't 6000 round trips). The browsing connection cache (`sessions.py`) stays per process
  on purpose: it is recreated on demand, so several web workers each just open their own. Orphans (job died) are
  failed by `runner.recover_orphans()` at start and on every list/status read; a just-started command has a 20 s
  grace so a queued one isn't called an orphan.
- **Trust model**: anyone who can open the toolbox can use the saved servers to run commands/move files — same
  as the Vault's trust model (one trusted user, trusted machine). Use a key with a passphrase and a read-only
  entry where you only need to look.

## Not built (decided, not forgotten)

Interactive terminal; recursive delete; resumable DOWNLOADS (they stream; a drop means starting again);
port forwarding / jump hosts; SSH agent; per-command allow-lists; editing a saved server in place.

## Verified (real OpenSSH server in Docker)

Password and passphrase-protected ed25519 key login; unknown host → asks; pinned → connects; different key →
"HOST KEY CHANGED"; wrong password/user, closed port, bad host, wrong/missing passphrase → plain messages.
Browse, mkdir, rename (never overwrites), delete file/empty folder (non-empty refused), missing folder. Upload:
atomic + SHA-256 verified, no `.part` left, overwrite protection, missing/unwritable folder fail fast; **a
60 MB upload whose connection was killed at 20 MB reconnected and resumed from 20,971,520 bytes, byte-identical**;
a corrupt remote partial was detected and replaced; Stop kept the partial and Retry resumed; the cached browse
session silently reconnected after the server dropped it. Commands: stdout/stderr, exit codes, timeout, Stop, no
trailing newline, 3000 lines, unknown command. Danger confirm; read-only refuses everything but browse/download;
a database secret's id refused; no secrets in the server list. UI in headless Chrome: Vault form (fingerprint
step, trust required, save), connect, upload, command, declined `rm -rf /` never ran, first-use trust banner,
changed-key block. 400 MB upload streamed with flat memory. Not tested: a server without `sha256sum` or SFTP
subsystem quirks other than OpenSSH, jump hosts, very slow links.

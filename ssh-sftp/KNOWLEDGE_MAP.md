<!-- Split out of the root KNOWLEDGE_MAP.md by roadmap session O3 (2026-11-10), text unchanged. -->
<!-- Repo-wide map: ../KNOWLEDGE_MAP.md · Rules: ../CLAUDE.md · This tool's own notes: ./CLAUDE.md -->

## Tool: SSH & SFTP — mounted at `/tools/ssh-sftp/`

Browse files, upload/download, make folders, rename, delete (a file or an EMPTY folder) and run commands on
servers saved in the Vault (kind `ssh_server`, added on the Vault page — never typed here). Host keys are pinned
(first use asks the user to confirm a fingerprint; a changed key is blocked), uploads are staged, SHA-256
verified, atomic and resumable and never overwrite unless told to, a server can be saved read-only, and
destructive commands need a confirm. See `ssh-sftp/CLAUDE.md`.

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| How a connection is made: host-key pinning, auth, timeouts/keepalives, error wording | `core/ssh_client.py` |
| The Vault "Add SSH server" form (fingerprint confirm → test login → save) | `vault/ui/index.html` (bottom script), `vault/server.py` (`/test-ssh-server`) |
| Pinning a key later without changing the entry's id | `core/vault.py` (`update_secret`) + `ssh-sftp/server.py` (`/trust`) |
| Cached browsing session, reconnect-on-dead, idle close | `ssh-sftp/sessions.py` |
| The upload (staging, resume, verify, atomic rename), downloads, commands, dangerous-command list | `ssh-sftp/engine.py` |
| Transfer/command history, staged-file cleanup, orphan recovery | `ssh-sftp/state_store.py` (Postgres schema `ssh_sftp` since B6; staged uploads in S3 via `STAGE` since B8, `stage/` is a local cache; `fail_orphans`, `sweep_stage`) |
| Upload/command jobs (worker container, thread fallback), log tail with `since` paging | `ssh-sftp/runner.py` → shared `core/jobs/runner.py` (`JobRunner(quiet=True)`, batched Redis logging `_BufferedLog` → `Channel.log_many`) |
| API endpoints and error → HTTP mapping | `ssh-sftp/server.py` |
| The page | `ssh-sftp/ui/index.html` |
| Live terminal (sessions, output stream, input, limits, idle close) | `ssh-sftp/terminal.py`, `server.py` `/terminals*`; page `ensureXterm`/`attach`; rt-ssh pinned to 1 web process in `docker-compose.yml` |

### Known non-obvious behavior (read before touching these areas)

- **A server already pinned can never be re-pinned from the tool** (`/trust` refuses); a changed host key is
  resolved by deleting and re-adding the server in the Vault.
- Resume is by the SIZE already on the server + a final SHA-256 check; the `.part` name contains the file's
  hash prefix so a different file never resumes onto the wrong bytes.
- SFTP reports most failures as a bare "Failure": pre-checks (`make_dir`, `rename`, upload target) produce the
  real reasons.
- **Stateful, `--workers 1`**: seventh entry for `../CLAUDE.md`'s standing rule (connection cache + job registry).

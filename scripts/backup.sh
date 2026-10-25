#!/usr/bin/env bash
# Toolbox backup — ONE dated archive with everything needed to rebuild your data:
#   postgres.dump   Toolbox's own database (Vault secrets, projects, sync positions, dump catalogue, history)
#   objects.tar     every stored file (dump files, scripts, datasets, DataDiff results, staged uploads)
#   env             the .env file — it holds TOOLBOX_VAULT_KEY: without it the Vault cannot be decrypted
#   workspace.yaml  which tools are on/off
#   manifest.json   what is inside, when, from which commit
# Redis is NOT backed up on purpose: it only holds short-lived things (sessions, live job state, counters).
#
# Usage:   scripts/backup.sh                  → backups/toolbox-YYYY-MM-DD_HHMMSS.tar.gz
#          BACKUP_DIR=/mnt/usb scripts/backup.sh   BACKUP_KEEP=14 scripts/backup.sh   (default: keep the last 7)
# The stack must be running (docker compose up -d). Takes no downtime.
# THE ARCHIVE CONTAINS THE VAULT KEY — keep it as private as .env (it is written with mode 600).
set -euo pipefail

cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
NAME="toolbox-${STAMP}.tar.gz"
DC=(docker compose)

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mbackup failed: %s\033[0m\n' "$*" >&2; exit 1; }

"${DC[@]}" ps --status running --services 2>/dev/null | grep -qx postgres || fail "the stack is not running (docker compose up -d)"

umask 077
mkdir -p "$BACKUP_DIR"
WORK="$(mktemp -d "${BACKUP_DIR}/.tmp-${STAMP}-XXXX")"
trap 'rm -rf "$WORK"' EXIT

# One-off container of the worker service: it has pg_dump 18, boto3 and the TOOLBOX_* settings (also when
# TOOLBOX_DATABASE_URL points at your own Postgres). --no-deps: never (re)starts other services.
RUN=("${DC[@]}" run --rm --no-deps -T worker)

say "1/4 database (pg_dump)…"
"${RUN[@]}" sh -c 'LD_LIBRARY_PATH=/opt/pgclient/lib exec /opt/pgclient/bin/pg_dump -Fc --no-owner --no-privileges "$TOOLBOX_DATABASE_URL"' \
  > "$WORK/postgres.dump" || fail "pg_dump"
[ -s "$WORK/postgres.dump" ] || fail "pg_dump produced an empty file"

say "2/4 stored files (S3)…"
"${RUN[@]}" python -m core.state.backup objects-export > "$WORK/objects.tar" || fail "file storage export"

say "3/4 settings (.env, workspace.yaml)…"
if [ -f .env ]; then cp .env "$WORK/env"; else echo "  (no .env — the Vault key is then on the data volume, see docs/runbook.md)"; fi
"${DC[@]}" exec -T toolbox sh -c 'cat /app/data/workspace/workspace.yaml 2>/dev/null || true' > "$WORK/workspace.yaml" || true

say "4/4 packing…"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
cat > "$WORK/manifest.json" <<EOF
{"format": 1, "created_at": "$(date -Iseconds)", "commit": "$COMMIT",
 "files": {"postgres.dump": $(stat -c %s "$WORK/postgres.dump"), "objects.tar": $(stat -c %s "$WORK/objects.tar"),
           "env": $( [ -f "$WORK/env" ] && echo true || echo false ),
           "workspace.yaml": $( [ -s "$WORK/workspace.yaml" ] && echo true || echo false )}}
EOF
tar -C "$WORK" -czf "$BACKUP_DIR/$NAME.part" .
mv "$BACKUP_DIR/$NAME.part" "$BACKUP_DIR/$NAME"
chmod 600 "$BACKUP_DIR/$NAME"
SIZE="$(stat -c %s "$BACKUP_DIR/$NAME")"

# for the Status page ("Last backup: …"); a failure here doesn't spoil the backup
"${RUN[@]}" python -m core.state.backup mark "$NAME" "$SIZE" >/dev/null 2>&1 || echo "  (could not record the backup time for the Status page)"

# keep only the newest BACKUP_KEEP archives
ls -1t "$BACKUP_DIR"/toolbox-*.tar.gz 2>/dev/null | tail -n +"$((BACKUP_KEEP + 1))" | while read -r old; do rm -f -- "$old"; echo "  removed old backup $(basename "$old")"; done

say "done: $BACKUP_DIR/$NAME ($(numfmt --to=iec "$SIZE" 2>/dev/null || echo "$SIZE bytes"))"
echo "Copy it somewhere safe (another disk / cloud drive). It contains the Vault key."

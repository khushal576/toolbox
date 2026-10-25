#!/usr/bin/env bash
# Toolbox restore — puts a backup from scripts/backup.sh back: database, stored files, Vault key (.env) and the
# on/off settings. It REPLACES what is there now (data created after the backup is gone), so it asks first.
#
# Usage:   scripts/restore.sh backups/toolbox-2026-10-25_183000.tar.gz          (asks to type "restore")
#          scripts/restore.sh <file> --yes                                        (no question — for scripts)
# Works on the same machine or a fresh one: clone the repo, `docker compose up -d --build` once, then restore.
#
# What happens: the tool containers are stopped (Postgres, Redis and file storage keep running), the database is
# restored with pg_restore --clean, the bucket is replaced by the backup's files, .env and workspace.yaml are put
# back (a different current .env is kept as .env.before-restore-<time>), then everything is started again.
set -euo pipefail

cd "$(dirname "$0")/.."
FILE="${1:-}"
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "usage: scripts/restore.sh <backup.tar.gz> [--yes]" >&2; exit 2; }
DC=(docker compose)
say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\033[31mrestore failed: %s\033[0m\n' "$*" >&2; exit 1; }

umask 077
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar -C "$WORK" -xzf "$FILE" || fail "cannot read $FILE"
[ -f "$WORK/manifest.json" ] && [ -f "$WORK/postgres.dump" ] && [ -f "$WORK/objects.tar" ] || fail "not a Toolbox backup"
echo "Backup: $(basename "$FILE")"; cat "$WORK/manifest.json"; echo

if [ "${2:-}" != "--yes" ]; then
  echo "This REPLACES the current Toolbox data (project: $("${DC[@]}" config --format json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["name"])' 2>/dev/null || echo '?'))."
  read -r -p 'Type "restore" to continue: ' answer
  [ "$answer" = "restore" ] || { echo "cancelled"; exit 1; }
fi

say "1/6 putting back .env (Vault key) first…"
if [ -f "$WORK/env" ]; then
  if [ -f .env ] && ! cmp -s .env "$WORK/env"; then
    keep=".env.before-restore-$(date +%Y%m%d_%H%M%S)"; cp .env "$keep"; echo "  current .env kept as $keep"
  fi
  cp "$WORK/env" .env; chmod 600 .env
else
  echo "  (the backup has no .env — keeping the current one)"
fi

say "2/6 state services up, tool containers stopped…"
"${DC[@]}" up -d postgres redis seaweedfs >/dev/null
for i in $(seq 1 60); do
  "${DC[@]}" exec -T postgres pg_isready -q >/dev/null 2>&1 && break; sleep 2
done
SERVICES="$("${DC[@]}" config --services | grep -vxE 'postgres|redis|seaweedfs')"
# shellcheck disable=SC2086
"${DC[@]}" stop $SERVICES >/dev/null 2>&1 || true

RUN=("${DC[@]}" run --rm --no-deps -T worker)

say "3/6 database (pg_restore)…"
"${RUN[@]}" sh -c 'LD_LIBRARY_PATH=/opt/pgclient/lib exec /opt/pgclient/bin/pg_restore --clean --if-exists --no-owner --no-privileges --single-transaction -d "$TOOLBOX_DATABASE_URL"' \
  < "$WORK/postgres.dump" || fail "pg_restore (the database was left as it was — one transaction)"

say "4/6 stored files (S3)…"
"${RUN[@]}" python -m core.state.backup objects-import < "$WORK/objects.tar" || fail "file storage import"

say "5/6 workspace settings…"
if [ -s "$WORK/workspace.yaml" ]; then
  "${DC[@]}" run --rm --no-deps -T --entrypoint sh toolbox -c 'mkdir -p /app/data/workspace && cat > /app/data/workspace/workspace.yaml' \
    < "$WORK/workspace.yaml" || fail "workspace.yaml"
else
  echo "  (none in the backup — every tool at its default)"
fi

say "6/6 starting everything…"
"${DC[@]}" up -d >/dev/null
echo "Restored from $(basename "$FILE"). Check the Status page: http://localhost:${TOOLBOX_HOST_PORT:-8000}/#/status"

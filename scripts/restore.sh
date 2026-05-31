#!/usr/bin/env bash
#
# Inv-Keep restore — overwrites data/ with the contents of a backup .tar.gz
# previously produced by scripts/backup.sh OR Settings → "Download backup".
#
# Usage:
#   ./scripts/restore.sh path/to/inv-keep-20260531-040000.tar.gz
#
# The container is stopped before restore (if running via docker compose) and
# restarted afterwards. A safety copy of the existing data/ is left at
# data.before-restore-<ts>/.
#
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$*"; }
die()  { printf "${RED}✗ %s${RESET}\n" "$*" >&2; exit 1; }

SRC="${1:-}"
[ -n "$SRC" ]    || die "Usage: $0 path/to/inv-keep-YYYYMMDD-HHMMSS.tar.gz"
[ -f "$SRC" ]    || die "Backup file not found: $SRC"
command -v tar >/dev/null 2>&1 || die "tar not found."

# Inspect the bundle (must contain BACKUP_INFO.txt + at least one .db).
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
tar -tzf "$SRC" >/dev/null || die "Not a readable tar.gz"
tar -xzf "$SRC" -C "$TMP"
[ -f "${TMP}/BACKUP_INFO.txt" ] || warn "BACKUP_INFO.txt missing — proceeding anyway."
DB_COUNT="$(find "$TMP" -maxdepth 1 -name '*.db' -type f | wc -l)"
[ "$DB_COUNT" -gt 0 ] || die "No .db files in the bundle. Aborting."

ok "Bundle looks valid (${DB_COUNT} database file(s))."
[ -f "${TMP}/BACKUP_INFO.txt" ] && cat "${TMP}/BACKUP_INFO.txt" | sed 's/^/    /'
echo ""

# Confirm.
if [ -z "${ASSUME_YES:-}" ]; then
  read -r -p "This will REPLACE the contents of ./data/. Continue? (y/N) " ans
  [ "${ans:-N}" = "y" ] || [ "${ans:-N}" = "Y" ] || die "Aborted."
fi

# Try to stop the running container so the DB isn't being written during the swap.
COMPOSE=""
docker compose version >/dev/null 2>&1 && COMPOSE="docker compose"
[ -z "$COMPOSE" ] && command -v docker-compose >/dev/null 2>&1 && COMPOSE="docker-compose"
if [ -n "$COMPOSE" ] && $COMPOSE ps --services --filter status=running 2>/dev/null | grep -q '^inv-keep$'; then
  $COMPOSE stop inv-keep
  ok "Stopped running container."
  STARTED=1
else
  STARTED=0
fi

# Safety copy of current data/.
TS="$(date -u +%Y%m%d-%H%M%S)"
SAFE="data.before-restore-${TS}"
mv data "$SAFE"
ok "Existing data/ preserved at ${SAFE}/"

# Lay down the new data/.
mkdir -p data
shopt -s dotglob
mv "$TMP"/* data/
shopt -u dotglob
rm -f data/BACKUP_INFO.txt
ok "data/ replaced."

# Restart the container if we stopped it.
if [ "$STARTED" = "1" ]; then
  $COMPOSE up -d inv-keep
  ok "Container restarted. Check logs:  $COMPOSE logs -f inv-keep"
fi

warn "If everything looks right, remove the safety copy:  rm -rf ${SAFE}"

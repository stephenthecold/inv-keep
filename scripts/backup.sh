#!/usr/bin/env bash
#
# Inv-Keep backup — snapshots data/ to a timestamped .tar.gz.
#
# Uses SQLite's online .backup so the snapshot is consistent even if the app
# is writing to the DB concurrently (no need to stop the container).
#
# Usage:
#   ./scripts/backup.sh                       # writes to ./backups/inv-keep-<ts>.tar.gz
#   ./scripts/backup.sh /path/to/dest.tar.gz  # writes to the given path
#   BACKUP_KEEP=14 ./scripts/backup.sh        # also prune backups/ older than 14 days
#
# Environment overrides:
#   DATA_DIR    folder to snapshot (default: ./data)
#   BACKUP_DIR  where ./backups/inv-keep-*.tar.gz lives (default: ./backups)
#   BACKUP_KEEP days to keep older backups (unset = keep forever)
#
set -euo pipefail
cd "$(dirname "$0")/.."

GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$*"; }
die()  { printf "${RED}✗ %s${RESET}\n" "$*" >&2; exit 1; }

DATA_DIR="${DATA_DIR:-./data}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
[ -d "$DATA_DIR" ] || die "No data directory at $DATA_DIR — is this an Inv-Keep checkout?"
command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 CLI not found (apt install sqlite3 / brew install sqlite)."
command -v tar     >/dev/null 2>&1 || die "tar not found."

TS="$(date -u +%Y%m%d-%H%M%S)"
OUT="${1:-${BACKUP_DIR}/inv-keep-${TS}.tar.gz}"
mkdir -p "$(dirname "$OUT")"

# Work in a tempdir so a half-finished backup never ends up as the final file.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Snapshot every *.db with SQLite's online backup (handles WAL mirroring).
shopt -s nullglob
for db in "$DATA_DIR"/*.db; do
  name="$(basename "$db")"
  sqlite3 "$db" ".backup '${WORK}/${name}'"
  ok "snapshotted ${name}"
done
shopt -u nullglob

# Mirror uploads/ verbatim (rsync if available for sparse + perms; cp otherwise).
if [ -d "${DATA_DIR}/uploads" ]; then
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --quiet "${DATA_DIR}/uploads" "${WORK}/"
  else
    cp -R "${DATA_DIR}/uploads" "${WORK}/"
  fi
  ok "mirrored uploads/"
fi

# Tag the bundle with version + timestamp for support.
{
  echo "inv-keep backup"
  echo "created_at_utc: $(date -u -Iseconds)"
  echo "hostname: $(hostname)"
  if [ -f app/version.py ]; then
    echo "app_version: $(grep -m1 '^__version__' app/version.py | awk -F'"' '{print $2}')"
  fi
} > "${WORK}/BACKUP_INFO.txt"

tar -czf "$OUT" -C "$WORK" .
SIZE="$(du -h "$OUT" | awk '{print $1}')"
ok "backup → ${OUT} (${SIZE})"

# Prune old backups by mtime (only inside our own backups dir, never the user's path).
if [ -n "${BACKUP_KEEP:-}" ] && [ -z "${1:-}" ]; then
  if command -v find >/dev/null 2>&1; then
    DELETED=$(find "$BACKUP_DIR" -maxdepth 1 -name 'inv-keep-*.tar.gz' -type f -mtime "+${BACKUP_KEEP}" -delete -print | wc -l)
    [ "$DELETED" -gt 0 ] && warn "pruned ${DELETED} backup(s) older than ${BACKUP_KEEP} days"
  fi
fi

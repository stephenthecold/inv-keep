#!/usr/bin/env bash
#
# Inv-Keep one-line installer bootstrap.
#
# Usage (when the repo is public):
#   curl -fsSL https://raw.githubusercontent.com/stephenthecold/inv-keep/main/scripts/quickstart.sh | bash
#
# Or, pinned to a specific tag:
#   curl -fsSL https://raw.githubusercontent.com/stephenthecold/inv-keep/v1.21.0/scripts/quickstart.sh | bash
#
# Environment overrides:
#   INV_KEEP_DIR    target directory  (default: ./inv-keep)
#   INV_KEEP_REPO   repo URL          (default: https://github.com/stephenthecold/inv-keep.git)
#   INV_KEEP_REF    tag / branch      (default: main)
#   INV_KEEP_YES    if non-empty, runs install.sh -y (no prompts)
#
# What it does:
#   1. Checks docker, git, and (if -y) compose are available
#   2. Clones the repo into INV_KEEP_DIR
#   3. Hands off to install.sh inside that directory
#
set -euo pipefail

REPO="${INV_KEEP_REPO:-https://github.com/stephenthecold/inv-keep.git}"
REF="${INV_KEEP_REF:-main}"
DIR="${INV_KEEP_DIR:-./inv-keep}"

GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
say()  { printf "%s\n" "$*"; }
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$*"; }
die()  { printf "${RED}✗ %s${RESET}\n" "$*" >&2; exit 1; }

say ""
say "${BOLD}Inv-Keep quickstart${RESET}"
say "  repo : ${REPO}"
say "  ref  : ${REF}"
say "  dir  : ${DIR}"
say ""

command -v git    >/dev/null 2>&1 || die "git is required. Install it and rerun."
command -v docker >/dev/null 2>&1 || warn "docker not on PATH — install.sh will still write .env, but you'll need Docker (and the compose plugin) to actually start the stack."

if [ -e "$DIR" ]; then
  # If it's an existing checkout of this repo at the right ref, reuse it; otherwise abort.
  if [ -d "$DIR/.git" ] && [ "$(cd "$DIR" && git config --get remote.origin.url 2>/dev/null || true)" = "$REPO" ]; then
    warn "$DIR exists and is an Inv-Keep checkout — fetching latest and reusing."
    (cd "$DIR" && git fetch --tags --quiet && git checkout --quiet "$REF" && git pull --ff-only --quiet || true)
  else
    die "$DIR exists and isn't an Inv-Keep checkout. Set INV_KEEP_DIR=/some/other/path and rerun."
  fi
else
  say "Cloning…"
  git clone --depth 1 --branch "$REF" "$REPO" "$DIR" \
    || die "git clone failed. If this is a private repo, make sure you're authenticated (ssh key, gh auth login, or a PAT in your git creds)."
fi

cd "$DIR"
ok "Cloned to $(pwd)"

if [ ! -x ./install.sh ]; then
  chmod +x ./install.sh || die "install.sh isn't executable and chmod failed."
fi

say ""
say "Handing off to install.sh…"
say ""

if [ -n "${INV_KEEP_YES:-}" ]; then
  exec ./install.sh -y
else
  exec ./install.sh
fi

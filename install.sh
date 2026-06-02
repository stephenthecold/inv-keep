#!/usr/bin/env bash
#
# Inv-Keep interactive installer.
# Prompts for hostname / port / SSL / email / OIDC, writes .env, and starts the
# stack with Docker Compose (optionally with the automatic-HTTPS Caddy proxy).
#
# Usage:  ./install.sh            (interactive)
#         ./install.sh -y         (accept defaults, no prompts)
#
set -euo pipefail

cd "$(dirname "$0")"

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
say()  { printf "%s\n" "$*"; }
ok()   { printf "${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$*"; }
die()  { printf "${RED}✗ %s${RESET}\n" "$*" >&2; exit 1; }

ASSUME_YES=0
[ "${1:-}" = "-y" ] && ASSUME_YES=1

ask() { # ask "Prompt" "default" -> echoes answer
  local prompt="$1" def="${2:-}" ans=""
  if [ "$ASSUME_YES" = "1" ]; then printf "%s" "$def"; return; fi
  if [ -n "$def" ]; then read -r -p "$prompt [$def]: " ans || true; else read -r -p "$prompt: " ans || true; fi
  printf "%s" "${ans:-$def}"
}
ask_secret() { # ask_secret "Prompt" -> echoes answer (hidden)
  local prompt="$1" ans=""
  if [ "$ASSUME_YES" = "1" ]; then printf ""; return; fi
  read -r -s -p "$prompt: " ans || true; echo >&2
  printf "%s" "$ans"
}
yesno() { # yesno "Question" "y|n" -> returns 0 for yes
  local def="${2:-n}" ans; ans="$(ask "$1 (y/n)" "$def")"
  case "$ans" in [Yy]*) return 0;; *) return 1;; esac
}

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then python3 -c "import secrets;print(secrets.token_hex(32))"
  else head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

# --- compose command detection ---
COMPOSE=""
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
fi

VERSION="$(grep -m1 '^__version__' app/version.py 2>/dev/null | awk -F'"' '{print $2}')"
say ""
say "${BOLD}Inv-Keep installer${RESET}${DIM}${VERSION:+  (v${VERSION})}${RESET}"
say "${DIM}This writes .env and starts the app with Docker Compose. Everything${RESET}"
say "${DIM}else — timezone, markup %, email, alerts, RBAC — is set under Settings.${RESET}"
say ""

command -v docker >/dev/null 2>&1 || warn "Docker not found on PATH — install Docker Desktop / Engine before starting the stack."
[ -n "$COMPOSE" ] || warn "Docker Compose not found — you can still write .env now and run compose later."

# --- existing .env guard ---
if [ -f .env ] && [ "$ASSUME_YES" != "1" ]; then
  yesno "A .env already exists. Overwrite it?" "n" || die "Aborted; existing .env kept."
fi

# --- gather config ---
say "${BOLD}1) Hostname & access${RESET}"
HOSTNAME_IN="$(ask "Public hostname (domain or IP)" "localhost")"
APP_PORT="$(ask "Host port for direct access" "8000")"

say ""
say "HTTPS / TLS — how should certificates be handled?"
say "  ${DIM}3) Your own reverse proxy  — DEFAULT. No bundled proxy; your existing${RESET}"
say "  ${DIM}                             nginx/Traefik/Caddy/etc. terminates TLS.${RESET}"
say "  ${DIM}Optional bundled Caddy proxy (only if you have NO reverse proxy already):${RESET}"
say "  ${DIM}  1) Let's Encrypt  — Caddy auto-obtains/renews certs for a public domain${RESET}"
say "  ${DIM}  2) My own cert    — Caddy serves your cert files (certs/cert.pem + key.pem)${RESET}"
TLS_CHOICE="$(ask "Choose 3 (own proxy), or 1/2 to enable the bundled Caddy" "3")"
USE_SSL=0; CADDY_CONFIG="./Caddyfile"; ACME_EMAIL="admin@${HOSTNAME_IN}"
case "$TLS_CHOICE" in
  1)
    USE_SSL=1; CADDY_CONFIG="./Caddyfile"
    case "$HOSTNAME_IN" in
      localhost|127.0.0.1|"") warn "Let's Encrypt needs a real public domain with DNS + ports 80/443. 'localhost' won't get a cert.";;
    esac
    ACME_EMAIL="$(ask "Email for Let's Encrypt notices" "admin@${HOSTNAME_IN}")"
    BASE_URL="https://${HOSTNAME_IN}"
    ;;
  2)
    USE_SSL=1; CADDY_CONFIG="./Caddyfile.custom"
    mkdir -p certs
    warn "Place your certificate at certs/cert.pem and private key at certs/key.pem (PEM format) before/after this."
    BASE_URL="https://${HOSTNAME_IN}"
    ;;
  *)
    USE_SSL=0
    if yesno "Will your separate reverse proxy serve HTTPS for ${HOSTNAME_IN}?" "y"; then
      BASE_URL="https://${HOSTNAME_IN}"
    else
      BASE_URL="http://${HOSTNAME_IN}:${APP_PORT}"
    fi
    ;;
esac

say ""
say "${BOLD}2) Branding${RESET}"
APP_TITLE="$(ask "App title" "Inv-Keep")"
CURRENCY="$(ask "Currency symbol" "$")"

say ""
say "${BOLD}3) Authentication (OIDC — bring your own provider)${RESET}"
say "${DIM}Inv-Keep ships no identity provider. To enable login, point it at your${RESET}"
say "${DIM}own OIDC provider (Authentik, Entra, Okta, Keycloak, …).${RESET}"
AUTH_MODE="none"; OIDC_DISCOVERY=""; OIDC_CLIENT_ID=""; OIDC_CLIENT_SECRET=""; OIDC_REDIRECT=""
if yesno "Configure OIDC login now?" "n"; then
  AUTH_MODE="oidc"
  OIDC_DISCOVERY="$(ask "OIDC discovery URL" "https://auth.${HOSTNAME_IN}/application/o/inv-keep/.well-known/openid-configuration")"
  OIDC_CLIENT_ID="$(ask "OIDC client ID" "")"
  OIDC_CLIENT_SECRET="$(ask_secret "OIDC client secret")"
  OIDC_REDIRECT="${BASE_URL}/auth/callback"
  ok "Register this redirect URI in your IdP: ${OIDC_REDIRECT}"
fi

SESSION_SECRET="$(gen_secret)"
# Defensive: the app refuses to start with a placeholder / <32-char secret.
if [ ${#SESSION_SECRET} -lt 32 ]; then
  die "gen_secret produced a session secret shorter than 32 chars (${#SESSION_SECRET}). Install openssl or python3 and rerun."
fi

# --- write .env ---
say ""
say "${BOLD}Writing .env …${RESET}"
{
  echo "# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "DATABASE_URL=sqlite:////code/data/app.db"
  echo "SESSION_SECRET=${SESSION_SECRET}"
  echo ""
  echo "HOSTNAME=${HOSTNAME_IN}"
  echo "APP_PORT=${APP_PORT}"
  echo "ACME_EMAIL=${ACME_EMAIL}"
  echo "CADDY_CONFIG=${CADDY_CONFIG}"
  echo ""
  echo "APP_TITLE=${APP_TITLE}"
  echo "CURRENCY=${CURRENCY}"
  echo ""
  echo "AUTH_MODE=${AUTH_MODE}"
  echo "OIDC_DISCOVERY_URL=${OIDC_DISCOVERY}"
  echo "OIDC_CLIENT_ID=${OIDC_CLIENT_ID}"
  echo "OIDC_CLIENT_SECRET=${OIDC_CLIENT_SECRET}"
  echo "OIDC_REDIRECT_URL=${OIDC_REDIRECT}"
} > .env
chmod 600 .env
ok ".env written (mode 600)."

mkdir -p data

# --- start ---
say ""
START_HINT="docker compose up -d --build"
[ "$USE_SSL" = "1" ] && START_HINT="docker compose --profile ssl up -d --build"

if [ -z "$COMPOSE" ]; then
  warn "Docker Compose not available; skipping startup."
  say "Run later:  ${BOLD}${START_HINT}${RESET}"
  exit 0
fi

if yesno "Build and start Inv-Keep now?" "y"; then
  if [ "$USE_SSL" = "1" ]; then
    say "Starting with the optional bundled Caddy proxy (--profile ssl)…"
    $COMPOSE --profile ssl up -d --build
  else
    say "Starting the app only — no bundled proxy (point your own at port ${APP_PORT})…"
    $COMPOSE up -d --build
  fi
  ok "Inv-Keep is starting."
  say ""
  say "Open:  ${BOLD}${BASE_URL}${RESET}"
  say ""
  say "${BOLD}First things to do in the UI:${RESET}"
  say "  ${DIM}1. Settings → General — set your timezone, currency, default markup %.${RESET}"
  say "  ${DIM}2. Clients → add the companies you bill. Jobs → ticket / WO refs.${RESET}"
  say "  ${DIM}3. Items → add your stock (or scan a new barcode to be prompted).${RESET}"
  say "  ${DIM}4. Home (scan) → barcode a known item to open the cart, set client/job once,${RESET}"
  say "  ${DIM}   keep scanning, submit. Auto-numbered ORD-YYYYMM-NNNN per order.${RESET}"
  say "  ${DIM}5. Records → Report for monthly billing · Map for charge-out locations.${RESET}"
  if [ "$AUTH_MODE" = "oidc" ]; then
    say ""
    say "${BOLD}OIDC reminder:${RESET}"
    say "  ${DIM}- The default RBAC role for new logins is Admin (permissive — change in Settings).${RESET}"
    say "  ${DIM}- Add YOUR verified IdP email to 'Always-admin emails' in Settings → Authentication${RESET}"
    say "  ${DIM}  before tightening the default role, so you don't lock yourself out.${RESET}"
    say "  ${DIM}- Break-glass if locked out: set DISABLE_AUTH=1 in .env and restart.${RESET}"
  fi
else
  say "Skipped startup. Start later with:"
  if [ "$USE_SSL" = "1" ]; then say "  ${BOLD}$COMPOSE --profile ssl up -d --build${RESET}"; else say "  ${BOLD}$COMPOSE up -d --build${RESET}"; fi
fi

# Inv-Keep

A small self-hosted web app (MSP-oriented) for charging bulk inventory (patch cables, adapters,
connectors, etc.) out to clients and jobs with a barcode scanner, and producing a monthly
billing report.

- **Cart-based charge-out** — scan a known barcode and it lands in a **Current
  order** card. Pick Client + Job once, keep scanning, hit **Submit Order**. Each
  submitted order gets an auto-generated number **`ORD-YYYYMM-NNNN`** (counter
  resets monthly) stamped on every line. Cancel any time and stock is restored.
  Works with any USB "keyboard-wedge" barcode scanner.
- **Custom (off-catalog) items** — `+ Custom item` on the cart card logs an
  ad-hoc purchase (name, description, optional photo, cost, price, qty) for
  things you bought in the field. Stored as an archived Part, hidden from the
  catalog but billed normally.
- **Live quick-search** — type an item name or barcode and matches appear
  instantly; pick one to add it straight to the cart.
- **Auto barcodes + printable labels** — add an item with the barcode blank and
  the app generates a Code128 value and a printable label (per-item or a whole
  sheet at `/labels`). Brother / DYMO / Zebra / Rollo / Epson / Brady presets,
  optional QR mode.
- **Custom item icons** — emoji, a built-in line-SVG (network cable, server,
  router, wrench, …), or your own uploaded photo.
- **Bulk + unique items** — "bulk" = one barcode shared by many identical units
  (qty-tracked); "unique" = a single labeled item.
- **Nested categories** — any depth, each with a description.
- **Clients + Jobs** — clients carry the full contact record (account #,
  contact, email, phone, location, address, notes); Jobs are a separate section
  attached to a client (ticket / WO ref). Every charge-out logs against both.
- **Reports** — group by client → job → line, with cost, charge, margin. Filter
  by **multi-client checkbox** + **month or arbitrary date range**. One-click
  CSV export honours the same filter. All dollar values **round UP to the
  nearest cent** so client-facing numbers never under-bill.
- **Default client markup %** — set once in Settings, the Add-Item and Custom-
  Item forms auto-suggest the client price as `ceil(our_cost × (1 + markup%))`.
- **Geo capture + maps** — the browser is asked (best-effort) for the device
  location at scan-time; lat/lng are stored on each charge-out line. View as a
  collapsible map on `/transactions` or a full-page **/map**, both built on
  vendored Leaflet + OpenStreetMap.
- **Timezone-aware timestamps** — pick any IANA zone in Settings; audit log,
  History and Recent activity render in that zone (storage stays UTC).
- **Audit log** — every charge-out, void, order open/submit/cancel, and config
  change is recorded with user, timestamp, and a contextual summary. Filterable.
- **Email alerts** — low-stock alerts and daily / weekly / monthly report
  emails. SMTP or OAuth2 (Microsoft 365 / Gmail). All in the UI.
- **Security baked in** — CSRF token on every form + JSON API; OIDC email
  trusted only when `email_verified`; session cookie `Secure` + `SameSite=Lax`;
  request-body cap; non-root container; refuses to start with a weak
  `SESSION_SECRET`.
- **Fully UI-configurable** — title, currency, timezone, low-stock thresholds,
  markup %, email, alerts, **and authentication (Authentik/OIDC or
  forward-auth)** all live in the app database and are edited under
  **Settings** — no env editing / redeploy.

It uses its own SQLite database and is independent of Snipe-IT.

The running version is shown in the footer and under Settings; releases are tagged in git
(`vX.Y.Z`) and recorded in [CHANGELOG.md](CHANGELOG.md).

## What stays in env vs. the UI

Only three things live in `.env`: `DATABASE_URL`, `SESSION_SECRET`, and the optional
`DISABLE_AUTH` break-glass flag. **Everything else** — app title, currency, low-stock
defaults, email sending, alert rules, **and the entire auth configuration** — is set under
**Settings** in the UI and stored in the database. The `AUTH_MODE` / `OIDC_*` env vars are
only read once to seed the defaults on a brand-new database.

## Email & alerts (configured in Settings → Email)

- **SMTP**: host, port, username, password, STARTTLS — works with any mail server.
- **OAuth2 (Microsoft 365 / Gmail)**: enter the client ID/secret (and tenant for Microsoft),
  save, then click **Connect mailbox** to grant access. The page shows the exact redirect URI
  to register with your OAuth app: `https://your-domain/settings/email/oauth/callback`.
  Microsoft scope used is `SMTP.Send`; Gmail uses `https://mail.google.com/`.
- **Test button** sends a one-off email so you can confirm it works.
- **Low-stock alerts** email once when a part drops to/under its threshold (per-part override
  or the global default), and re-arm after restock.
- **Monthly report** is emailed automatically on a configurable day of the month (a background
  scheduler checks hourly), or on demand with **Send now**.

## Quick start — interactive installer (recommended)

```bash
./install.sh
```
Asks for **hostname, port, SSL (Let's Encrypt), branding and OIDC**, writes `.env`
(with a generated `SESSION_SECRET`), and starts the stack — adding the automatic-HTTPS
proxy if you enable SSL. Use `./install.sh -y` for all-defaults. See [docs/DEPLOY.md](docs/DEPLOY.md).

## Quick start — manual (Docker Compose)

```bash
cp .env.example .env
# Generate a session secret (the app refuses to start with a weak / placeholder one):
python3 -c "import secrets; print(secrets.token_hex(32))"
# Paste the 64-char output into SESSION_SECRET in .env.

docker compose up -d --build                 # http://HOSTNAME:APP_PORT (default :8000)
# ...or with automatic HTTPS (needs a real domain + ports 80/443 + ACME_EMAIL):
docker compose --profile ssl up -d --build   # https://HOSTNAME
```

It starts with **no login** so you can try it immediately on a trusted network.
**Set up authentication in the UI before exposing it** (see below).

First steps in the UI:
1. **Settings → General** — set your timezone, currency, and (optional) default
   client markup %.
2. **Clients** → add the companies you bill. **Jobs** → ticket / WO refs, each
   attached to a client.
3. **Items** → add your stock: name, icon, description, barcode (leave blank to
   auto-generate + print a label), bulk vs unique, **our cost**, **client
   price** (auto-suggested from markup %), starting qty. Scanning an unknown
   barcode on the home page jumps straight to Add Item with it pre-filled.
4. **Home (scan)** → barcode a known item; it lands in the **Current order**
   card. Pick Client + Job once, keep scanning more items (or use
   **+ Custom item** for off-catalog purchases), tweak quantities, hit
   **Submit Order**. Each submit produces an `ORD-YYYYMM-NNNN`.
5. **Records → Report** — pick a month or arbitrary date range and any subset
   of clients; export CSV for billing. **Records → Map** — see every geo-tagged
   charge-out on a map.

## Authentication (Settings → Authentication, in the UI)

Pick one of three modes and save — no env editing or redeploy:

### Option 1 — Authentik / OIDC (app handles login itself)
In Authentik, create an **OAuth2/OpenID Provider** + **Application**. In Inv-Keep's
**Settings → Authentication**, choose **Authentik / OIDC** and enter:

- **Discovery URL** — `https://auth.example.com/application/o/<app-slug>/.well-known/openid-configuration`
- **Client ID** and **Client secret**
- (optional) a **Redirect URL override** if running behind a proxy that rewrites the URL

The page shows the exact **redirect URI** to register in Authentik
(`https://your-domain/auth/callback`). If you terminate TLS at a reverse proxy, make sure it
forwards `X-Forwarded-Proto: https` so the callback URL is built as https.

### Option 2 — Forward auth (Authentik outpost / proxy provider)
Front the app with your reverse proxy + Authentik outpost and choose **Forward-auth** in
Settings. The app trusts the username/email headers the outpost injects (defaults
`x-authentik-username` / `x-authentik-email`). In this mode your proxy must protect **every**
route, since the app trusts those headers implicitly.

### Locked out? (break-glass)
If an OIDC misconfiguration prevents login, set `DISABLE_AUTH=1` in `.env` and restart. That
bypasses all auth so you can reach **Settings**, fix the config, then remove the flag.

## Android AIO scanners (PWA)
Inv-Keep is an installable **PWA** tuned for Android all-in-one barcode scanners
(Zebra, Sunmi, Chainway, etc.): set the scanner to keyboard-wedge mode and “Add to
Home screen”. Full setup, and how to build an APK (Trusted Web Activity), is in
**[docs/ANDROID.md](docs/ANDROID.md)**.

## Thermal label printing
Label pages print through the OS print dialog at exact `@page` sizes, with presets
for **Rollo** (4×6, 2.25×1.25 in) and **Brother** (P-touch 12/18/24 mm tapes, QL
62×29 mm / continuous). Set a default under Settings → Printing. See
**[docs/PRINTING.md](docs/PRINTING.md)**.

## Backups
Everything lives in `./data/` — `app.db` plus any uploaded brand logo under
`./data/uploads`. Back up that folder (or snapshot the volume).

## Run locally without Docker
```bash
pip install -r requirements.txt
export DATABASE_URL="sqlite:///./data/app.db"
uvicorn app.main:app --reload
```

## Documentation
- [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) — one-page architecture & decisions digest
- [CONFIGURATION.md](CONFIGURATION.md) — every environment variable and in-app setting
- [CHANGELOG.md](CHANGELOG.md) — versioned list of changes
- [docs/DEPLOY.md](docs/DEPLOY.md) — hostname, ports, SSL (Let's Encrypt / own cert / external), installer
- [docs/ANDROID.md](docs/ANDROID.md) — Android AIO scanners / PWA / APK
- [docs/PRINTING.md](docs/PRINTING.md) — Brother, DYMO, Zebra & Rollo thermal printing

## Versioning
Inv-Keep uses [SemVer](https://semver.org). The version lives in `app/version.py`,
shows in the footer and Settings, and each release is tagged in git (`vX.Y.Z`) with
a matching CHANGELOG entry.

## License
[MIT](LICENSE) — free to use, modify and distribute. (Swap the LICENSE file if you
prefer a different open-source license before publishing.)

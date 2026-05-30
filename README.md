# Inv-Keep

A small self-hosted web app (MSP-oriented) for charging bulk inventory (patch cables, adapters,
connectors, etc.) out to clients and jobs with a barcode scanner, and producing a monthly
billing report.

- **Scan-first home page** — the home page is a scan/search box. Scan a barcode (or type to
  search with live suggestions) to pull the item up, then confirm quantity, client and job
  before it's charged out. Works with any USB "keyboard-wedge" barcode scanner.
- **Live quick-search** — start typing an item name or barcode and matching items appear
  instantly to pick from, so you can find things without an exact scan.
- **Item icons + descriptions** — give each item an emoji icon and description; the icon
  shows in the search results and charge panel for fast visual identification.
- **Cost + client price** — each item tracks **our cost** and the **price we charge clients**.
  Charge-outs snapshot both, so the report shows billable totals plus cost and margin.
- **Bulk + unique items** — a "bulk" item is one barcode shared by many identical units
  (uses a quantity); a "unique" item is a single labeled unit (always counts as 1).
- **Auto barcodes + printable labels** — add an item with the barcode left blank and the app
  generates a Code128 value and a printable label (per-item or a whole sheet at `/labels`).
- **Nested categories** — organise items in a category tree of any depth, each with a description.
- **White-label branding** — set the app title, brand emoji or uploaded logo, accent colour
  and footer text under Settings; they apply across the whole app.
- **Clients & Jobs** — clients hold a full contact record (account #, contact, email, phone,
  location, address, notes). **Jobs** are a separate section, each attached to a client
  (ticket / work-order ref), and charge-outs are logged against a job.
- **Monthly report** — grouped by client → job with line costs, job subtotals, client totals,
  grand total, and a one-click CSV export for billing.
- **Audit log** — every charge-out, void, and configuration change is recorded and filterable.
- **Email alerts** — low-stock alerts and an automatic monthly report email. Send via plain
  SMTP or OAuth2 (Microsoft 365 / Gmail). All configured in the UI.
- **Fully UI-configurable** — title, currency, low-stock thresholds, email, alerts, **and
  authentication (Authentik/OIDC or forward-auth)** all live in the app database and are
  edited under **Settings** (no env editing / redeploy needed).

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
# Generate a session secret and paste it into SESSION_SECRET:
python3 -c "import secrets; print(secrets.token_hex(32))"

docker compose up -d --build                 # http://HOSTNAME:APP_PORT (default :8000)
# ...or with automatic HTTPS (needs a real domain + ports 80/443 + ACME_EMAIL):
docker compose --profile ssl up -d --build   # https://HOSTNAME
```

It starts with **no login** so you can try it immediately on a trusted network.
**Set up authentication in the UI before exposing it** (see below).

First steps in the UI (use the **+ Add new …** button in the top-right of each list page):
1. **Clients** → add the clients you bill. **Jobs** → add jobs (each attached to a client).
2. **Items** → add your cables/adapters: name, icon, description, barcode, bulk vs unique,
   **our cost**, **client price**, stock. Scanning an unknown barcode on the home page jumps
   straight to Add Item with the barcode pre-filled.
3. **Home (scan)** → scan or search an item → confirm quantity, client and job → charge out.
4. **Monthly Report** → pick the month; see billable total, cost and margin; export CSV.

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
- [CONFIGURATION.md](CONFIGURATION.md) — every environment variable and in-app setting
- [CHANGELOG.md](CHANGELOG.md) — versioned list of changes
- [docs/DEPLOY.md](docs/DEPLOY.md) — hostname, ports, SSL, reverse proxies, installer
- [docs/ANDROID.md](docs/ANDROID.md) — Android AIO scanners / PWA / APK
- [docs/PRINTING.md](docs/PRINTING.md) — Brother, DYMO, Zebra & Rollo thermal printing

## Versioning
Inv-Keep uses [SemVer](https://semver.org). The version lives in `app/version.py`,
shows in the footer and Settings, and each release is tagged in git (`vX.Y.Z`) with
a matching CHANGELOG entry.

## License
[MIT](LICENSE) — free to use, modify and distribute. (Swap the LICENSE file if you
prefer a different open-source license before publishing.)

# Changelog

All notable changes to Inv-Keep are recorded here. Versions are tagged in git
(`vX.Y.Z`) and the running version is shown in the app footer and Settings.

## [1.5.0] — 2026-05-30
- **Account menu** — History, Report, Audit and Settings moved into a clickable
  account dropdown (top-right), decluttering the main nav (Scan / Items /
  Categories / Clients / Jobs).
- **Currency picker** — currency is now a dropdown of the top ~20 world currencies
  (custom values still respected).
- **Item photos** — upload a custom photo per item; it shows in the items table,
  search results and the charge panel (falls back to the emoji icon).
- **Separate cable icons** — distinct “Network / Ethernet cable” and “Power cord /
  plug” options in the icon dropdown.
- **Tidier restock** — Edit + Restock grouped in a stable Actions cell that no
  longer shifts around as the window resizes.
- **More label brands + size-aware preview** — added **Epson** (ColorWorks /
  LabelWorks) and **Brady** (M21 / self-laminating) presets; the label customizer
  preview now resizes to the selected label size.

## [1.4.0] — 2026-05-30
- **Fix: stale assets** — the service worker is now network-first (cache only as an
  offline fallback) and CSS/JS are version-busted, so updates apply immediately.
  This was the root cause of broken logo/brand styling and the icon picker.
- **Logo scaling & optional title** — header logo is constrained and never overflows
  the window; the app-title text next to the logo is now optional (Settings →
  Branding → “Show title text”) and aligned. Page no longer horizontally overflows.
- **Item icon dropdown** — the emoji button grid is replaced by a tidy dropdown
  (with a custom option), in both Add and Edit.
- **Edit items after the fact** — items now have an **Edit** modal (name, icon,
  description, category, costs, threshold, active); the items table is compact and
  no longer overflows.
- **Label customizer live preview** — Settings → Printing shows a sample label that
  updates as you toggle fields.
- Button-wrapping / alignment fixes (e.g. “Send now”).

## [1.3.0] — 2026-05-30
- **Bring-your-own-cert / external proxy** — TLS now has three modes: bundled Caddy
  with Let's Encrypt, bundled Caddy with **your own certificate** (`Caddyfile.custom`
  + `certs/`), or **no bundled proxy** (use your own nginx/Traefik). The installer
  asks which. See [docs/DEPLOY.md](docs/DEPLOY.md).
- **Customizable label content** — Settings → Printing lets you choose what prints on
  each label (icon, name, barcode digits, price, description, category) plus a
  **company/header line** and **extra footer line**.
- **Full APK framework + PWA** — completed `android/twa-manifest.json` (versioned,
  shortcuts, splash, fingerprint flow) and `android/README.md`; PWA continues to work
  with no build.
- **docs/PROJECT_STATE.md** — consolidated handoff/context digest of the whole project.

## [1.2.0] — 2026-05-30
- **Top-4 label-brand presets** — label-size dropdown is now grouped by brand:
  **Brother** (QL + P-touch), **DYMO** (LabelWriter + LabelManager), **Zebra**
  (2×1 … 4×6 in) and **Rollo**, plus generic sizes. See [docs/PRINTING.md](docs/PRINTING.md).
- **Deployment config** — `HOSTNAME`, `APP_PORT`, and optional **automatic HTTPS**
  via a bundled Caddy reverse proxy (`docker compose --profile ssl up`). The app now
  runs behind proxy headers so OIDC/PWA URLs build as `https`. See [docs/DEPLOY.md](docs/DEPLOY.md).
- **`install.sh`** — interactive installer that collects hostname, port, SSL +
  Let's Encrypt email, branding, and OIDC up front, writes `.env`, and starts the stack.
- **Android build pipeline** — `.github/workflows/android.yml` builds a TWA APK/AAB
  in CI; `/.well-known/assetlinks.json` is served from a Settings field so the
  installed app can hide the URL bar. Plus a `ci.yml` checks workflow.

## [1.1.0] — 2026-05-30
- **Progressive Web App (PWA)** — installable on Android (and desktop): app
  manifest, service worker, icons, theme colour and a standalone fullscreen
  display. Optimised for **Android AIO barcode scanners** (keyboard-wedge input,
  responsive touch layout, persistent scan focus). See [docs/ANDROID.md](docs/ANDROID.md).
- **Thermal label printing** — label pages now offer size presets for **Rollo**
  (4×6 in, 2.25×1.25 in) and **Brother** (P-touch 12/18/24 mm tapes, QL 62×29 mm /
  62 mm continuous) with exact `@page` sizing, plus a default label size in
  Settings → Printing. See [docs/PRINTING.md](docs/PRINTING.md).
- **Open-source preparation** — added MIT `LICENSE`, `CONFIGURATION.md` (every env
  var + UI setting), this changelog, and a Bubblewrap TWA config for building an APK.
- Responsive layout improvements for small handheld screens.

## [1.0.0] — 2026-05-30
First versioned release. Cumulative feature set:

- **Scan-first home page** with live quick-search and a charge-out panel
  (quantity, client, job) before committing.
- **Items** (renamed from Parts) with **descriptions** and **emoji icons** that
  show in the search results and charge panel for quick identification.
- **Nested categories** with **descriptions**.
- **Clients** (renamed from Customers) with full contact records, and **Jobs**
  as a separate section attached to clients.
- **Cost vs. client price** tracked per item; reports show billable totals plus
  cost and margin.
- **Auto-generated barcodes + printable Code128 labels** for items with no barcode.
- **Monthly charge-out report** grouped by client → job, with CSV export.
- **Audit log** of every charge-out, void and configuration change.
- **Email alerts** (low stock + monthly report) via SMTP or OAuth2 (Microsoft 365 / Gmail).
- **UI-managed authentication** (Authentik/OIDC or forward-auth) with a
  `DISABLE_AUTH` break-glass override.
- **White-label / branding**: app title, brand emoji or uploaded logo, accent
  colour, and footer text — all configurable in Settings.
- **Add-new** actions presented as top-right buttons opening modal dialogs.
- Everything (except `DATABASE_URL`, `SESSION_SECRET`, `DISABLE_AUTH`) is
  configurable in the UI and stored in the database.

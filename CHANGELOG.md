# Changelog

All notable changes to Inv-Keep are recorded here. Versions are tagged in git
(`vX.Y.Z`) and the running version is shown in the app footer and Settings.

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

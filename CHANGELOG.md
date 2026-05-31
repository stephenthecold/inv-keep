# Changelog

All notable changes to Inv-Keep are recorded here. Versions are tagged in git
(`vX.Y.Z`) and the running version is shown in the app footer and Settings.

## [1.10.0] — 2026-05-30
- **Custom items in the cart** — new **+ Custom item** button on the order
  card opens a modal for ad-hoc / off-catalog purchases (name, description,
  optional photo, cost, client price, qty). Server creates an archived
  `Part` on the fly so the line still flows through reports / audit / voids
  like any other transaction; the catalog stays clean (Items page hides
  archived parts by default, **Show archived** toggle reveals them).
- **Map of charge-outs** — every transaction with a captured location is now
  pinnable on an embedded Leaflet + OpenStreetMap map. There's a collapsible
  map at the top of /transactions and a full-page **/map** view (linked
  from the Records dropdown). Both honour the same month / date-range
  filters as the report. Leaflet 1.9.4 is **vendored** under
  `app/static/vendor/leaflet/` — fully self-hosted, no CDN.

## [1.9.0] — 2026-05-30
- **Cart-based charge-out flow** — scanning a known item now opens a persistent
  **Current order** card on the home page. Set Client + Job once (asked after
  your first scan), then keep scanning items into the same cart; tweak qty
  inline or remove lines, and hit **Submit Order** when done. Each submitted
  order gets an auto-generated number **ORD-YYYYMM-NNNN** (counter resets
  monthly) that's stamped on every line. **Cancel** restores stock and
  discards the cart. One open cart per signed-in user; closing the browser
  doesn't lose the work — the cart reopens on next visit.
- **Order # on /transactions and the home page Recent activity** — every line
  now shows its `ORD-…` number (or `—` for legacy single-scan rows).
- **Reports + History exclude open-cart lines** — only submitted (or legacy)
  transactions count toward totals; a cart in progress doesn't pollute the
  monthly bill.
- Removed `/api/checkout`; the cart API (`/api/cart/scan`, `/api/cart/set`,
  `/api/cart/line/{id}`, `/api/cart/submit`, `/api/cart/cancel`) replaces it.
- **Schema**: new `orders` table; `transactions.order_id` (nullable FK);
  `transactions.customer_id` relaxed to nullable so a cart line can exist
  before the client is picked. Upgrade is automatic via `ensure_columns()` —
  including a one-time SQLite table rebuild to lift the old NOT NULL.

## [1.8.0] — 2026-05-30
- **Report — multi-client filter + date range** — the Charge-Out report now takes
  any combination of clients (multi-select dropdown, default = all) and either a
  month or an explicit From/To date window. CSV export honours the same filter.
- **Timezone-aware timestamps** — new General setting (curated IANA list,
  default UTC); audit log, transactions and scan-page recent activity render
  in the configured zone. Storage stays UTC; conversion is at the template layer
  via a new `local_dt` filter.
- **Geo capture on charge-out** — the browser is asked (best-effort, 4 s cap) for
  the device location before each `/api/checkout` POST; lat/lng/accuracy persist
  on the Transaction row and surface as a 📍 pin (OpenStreetMap link) on
  /transactions and in the audit summary. Denial / unsupported = the charge-out
  still goes through silently.
- **Default client markup %** — a new General setting (admin-only — hidden from
  managers); when adding an item the Client price field auto-fills as
  `our cost × (1 + markup%)`, rounded **up** to the nearest cent. Editing the
  price manually disables autofill for that item. Managers still get the
  autofill silently; only admins see and control the percentage.
- **Dollar values round up to the cent** — display + CSV totals are ceiling-rounded
  (`$1.231 → $1.24`) so client-facing numbers never under-bill. Stored values
  keep full precision; rounding is at the presentation layer.
- **Cleaner item icons** — every built-in SVG icon redrawn for recognition at
  small sizes; the patch-cable icon in particular is now a clear RJ45 plug +
  trailing cable. No data migration needed.
- **Fix: Add-Item modal didn't auto-open from a scan** — `openModal` was being
  called before `app.js` had loaded; wrapped in `DOMContentLoaded`.
- **Security hardening** — refuses to start with the placeholder `SESSION_SECRET`
  (raises at import time); OIDC email is only trusted if `email_verified=true`;
  session cookie now `Secure` + `SameSite=Lax`; SVG dropped from logo upload
  whitelist (stored-XSS); `html.escape` on the auth error page; 8 MB request-body
  cap in middleware (pre-DoS guard); `brand_accent` regex-validated; Dockerfile
  drops to a non-root user; `/logout` is now POST; audit-log summaries strip
  control chars.
- **CSRF protection** — pure ASGI middleware verifies a per-session token on
  every state-changing request via `X-CSRF-Token` header (for JSON/AJAX) or
  hidden `_csrf` form field (for HTML forms). Closes the cross-site write hole
  in `forward` auth mode where the proxy attaches SSO cookies cross-site.

## [1.7.0] — 2026-05-30
- **Label preview fixed** — the Settings live preview now reflects the chosen **code
  type** (shows a QR when QR is selected) and **fills the label** (flex distribution
  + the code grows to fill dead space), matching what prints.
- **Smarter monthly schedule** — choose "on day N" *or* "on the first/second/third/
  fourth/last <weekday> of every month" (e.g. first Monday).
- **Records dropdown** — History, Report and Audit moved out of the account menu
  into a single top-bar **Records ▾** dropdown; the account menu keeps Settings,
  Users & roles and Log out.

## [1.6.0] — 2026-05-30
- **Custom SVG icon set** — items can use crisp built-in line icons (network cable,
  power plug, connector, server, router, etc.) picked from a dropdown with a live
  preview; they render in the table, search, charge panel and on labels (custom
  emoji still supported).
- **Dynamic labels (Snipe-IT style)** — label content now flex-fills the label so
  bigger labels aren't half-empty: the barcode grows and fonts scale to the size.
  Added an optional **QR code** mode alongside Code128.
- **More alert schedules** — daily / weekly / monthly report emails, each with its
  own day/weekday + hour and recipients (checked hourly).
- **Users, roles & permissions (RBAC)** — granular permissions (view, checkout,
  manage items/clients/settings/users, view audit) grouped into roles
  (Admin/Manager/Operator/Viewer + custom). Users signing in via Authentik / Entra /
  OIDC are auto-created and mapped to roles by **IdP group claim** (configurable
  map), with per-user override, always-admin emails, and nav/route enforcement.

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

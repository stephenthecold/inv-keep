# Inv-Keep — project state (handoff for the next Claude / contributor)

**Read this first.** It is the durable substitute for the build chat. Reading this +
[CONFIGURATION.md](../CONFIGURATION.md) + [CHANGELOG.md](../CHANGELOG.md) reconstructs
the whole project; you do **not** need the original conversation. Current version:
**v1.21.x** (tags `v1.0.0` … `v1.21.0`, one per release).

## What it is
A small, self-hosted, MSP-oriented inventory **charge-out** app. Scan an item →
it lands in a cart with an auto-numbered order; set the client/job once, keep
scanning, submit. Each line is logged with optional geo-tag and feeds
**monthly/weekly/daily billing reports** (cost vs client price vs margin), plus
a **map** of every geo-tagged charge-out. Stock is tracked **per location**
(office / trucks / job-site cages) with bulk **per-location stocktake**, atomic
**transfers** between locations, and a touch-first **category drill-down browser**
for the catalog. Locked-down **Kiosk PIN mode** for front-desk shared devices.
Independent of Snipe-IT. Single SQLite DB. Installable PWA for Android AIO scanners.

## Stack
- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2, Jinja2 (server-rendered HTML).
- **DB**: SQLite under `./data` (auto-migrates added columns on startup — see
  `database.ensure_columns()`; includes one-shot SQLite table-rebuild paths).
  No Alembic.
- **Frontend**: one CSS file + one vanilla JS file (`app/static/`). PWA (manifest + SW).
  Leaflet 1.9.4 vendored at `app/static/vendor/leaflet/` for the map views.
- **Deploy**: Docker Compose; optional bundled **Caddy** for TLS (3 modes), or your
  own reverse proxy. Interactive `install.sh`.
- **Runtime deps**: `requirements.txt` (fastapi, uvicorn, sqlalchemy, authlib,
  python-barcode, qrcode, tzdata, …). **Build-only** (NOT runtime): `Pillow`
  (icon PNGs), `pyyaml` (validation) — installed ad-hoc in the venv, never
  imported at runtime.
- **Dev venv**: `.venv/` (gitignored). Tests run via `./.venv/bin/...`. On
  Windows boxes that lack a system tzdb, `pip install tzdata` makes `zoneinfo`
  resolve named zones — already in requirements.txt.

## Repo map (what each file does)
```
app/
  main.py            ALL routes + middleware (auth + RBAC enforcement) + PWA + labels +
                     cart API + report query helpers + map endpoint
  models.py          ORM: Setting, Category (self-referential parent_id),
                     Part(=Item, w/ archived flag), Client(table "customers"),
                     Job, Location, StockLevel (per-part/per-loc qty),
                     Transfer + TransferLine, Order, Transaction (w/ order_id +
                     location_id + geo cols), Role, User, AuditLog
  database.py        engine + ensure_columns() additive migrations + a SQLite
                     table-rebuild migration that relaxed transactions.customer_id
                     to nullable (needed for open-cart lines pre-client-pick)
  settings_store.py  DB-backed settings + DEFAULTS (env seeds first-run only).
                     Includes: timezone, default_markup_pct.
  config.py          env vars (pydantic-settings): DATABASE_URL, SESSION_SECRET,
                     DISABLE_AUTH, + first-run seeds (APP_TITLE, AUTH_MODE, OIDC_*).
                     SESSION_SECRET must be ≥32 chars and not the placeholder; app
                     refuses to start otherwise.
  auth.py            effective_mode(), build_oidc() (dynamic), resolve_user()->perms
  rbac.py            PERMISSIONS, DEFAULT_ROLES, seed_roles(), resolve_login(),
                     required_perm(path, method)
  csrf.py            Pure ASGI CSRFMiddleware (not BaseHTTPMiddleware — needed to
                     buffer + replay the body to the inner app). Token in the session
                     cookie, echoed via X-CSRF-Token header or _csrf form field.
                     Required for forward-auth mode in particular.
  orders.py          next_order_number (ORD-YYYYMM-NNNN, monthly counter),
                     open_cart_for(user), cart_lines, cart_totals.
  icons.py           built-in SVG icon set (ICON_SET / ICON_CHOICES) + render_html().
                     v1.8 redraw: all 20 icons cleaner / readable at small sizes.
  labels.py          Code128 + QR SVG render, LABEL_SIZES presets (Brother/DYMO/Zebra/
                     Rollo/Epson/Brady), grouped_sizes(), size_preset()
  reports.py         build_report_range()/build_report() (client→job→lines, charge/
                     cost/margin) + CSV. Excludes lines whose Order.status='open' or
                     'cancelled' so abandoned carts don't pollute the report.
  emailer.py         SMTP + OAuth2(MS/Google) send; low-stock + daily/weekly/monthly
                     schedules (run_due_jobs, nth_weekday_date); hourly scheduler thread
  audit.py           audit.record() helper; strips ASCII control chars on store
  version.py         __version__ (footer + Settings)
  templates/*.html   base (header + mobile drawer + favicon link),
                     scan (cart card UI; cart-lines hide Barcode/Unit on phones),
                     parts (v1.18+ drill-down category browser — root shows
                       category cards, items render under ?cat=<id> or ?cat=all),
                     categories (flat admin editor, still served for power users),
                     clients, jobs,
                     locations (index) + location_detail (per-loc audit/stocktake),
                     transfers + transfer_form + transfer_detail,
                     transactions (=History, w/ inline map),
                     report (multi-client + date range), audit,
                     settings + _settings_nav (tabbed sidebar, shared partial),
                     users (renders inside the same settings shell),
                     label (sized + sheet variants; @page pins physical mm),
                     map (full-page Leaflet)
  static/            style.css, app.js (cart + Leaflet popups), icons/ (PWA PNGs),
                     vendor/leaflet/ (1.9.4: CSS/JS + marker images)
install.sh           interactive installer (hostname/port/TLS/email/OIDC -> .env -> compose)
docker-compose.yml   pulls ghcr.io/stephenthecold/inv-keep:${INV_KEEP_VERSION:-latest}
                     + optional caddy (profile "ssl") + container healthcheck
docker-compose.dev.yml  override that adds build: . for local-build dev
scripts/quickstart.sh  one-line bootstrap (git clone → install.sh)
scripts/backup.sh    consistent SQLite .backup + uploads → ./backups/inv-keep-<ts>.tar.gz
scripts/restore.sh   verify + stop container + swap data/ + restart
Caddyfile / Caddyfile.custom   Let's Encrypt / bring-your-own-cert (certs/)
android/             twa-manifest.json + README (full APK framework via Bubblewrap)
.github/workflows/   ci.yml (checks + regression tests), release.yml (multi-arch
                     ghcr.io image build on v* tag push), android.yml (TWA APK)
docs/                PROJECT_STATE(this), CONFIGURATION, CHANGELOG, DEPLOY,
                     BACKUPS, ANDROID, PRINTING
scripts/make_icons.py  regenerate PWA icons (needs Pillow; results committed)
```

## Data model (essentials)
- **Category** — self-referential tree (`parent_id`). Items have an optional
  `category_id` and the `/parts` browser drills down through the tree.
- **Part** = an *Item* (UI label "Items"; route paths stay `/parts`; table `parts`).
  Fields: name, description, icon (emoji or `svg:<key>`), image (uploaded photo
  path), barcode (auto-generated `PCO000001` if blank → printable label, or
  `CUSTOM-<hex>` for ad-hoc cart additions), type bulk|unique, **unit_cost** +
  **unit_price**, **quantity_on_hand** (aggregate across all locations — see
  StockLevel for per-location), category, low_stock_threshold/alerted,
  barcode_generated, active, **archived** (hidden from /parts by default;
  "Show archived" toggle. Archive is reversible, delete is permanent and
  refused on items with any history).
- **Location** — a place stock is kept. Name, notes, `active`, `archived` (refused
  while stock > 0). Seeded with "Main" on first boot.
- **StockLevel** — per-(part, location) qty row (unique on the pair). Cart scans,
  custom items, restocks, stocktakes, and transfers all flow through this table;
  `Part.quantity_on_hand` is kept equal to the sum across locations.
- **Transfer** + **TransferLine** — atomic stock movement between locations
  (decrement source + increment destination + one audit row). Used by the
  `/transfers/new` multi-line page and by the per-item `Stock → Move` action.
- **Client** — UI label "Clients"; **table is still `customers`** (preserves data
  through the Customer→Client rename). Full contact record. `archived=True` is
  reserved for one-off walk-in clients created from the cart card.
- **Job** — belongs to a Client (ticket/WO ref).
- **Order** — bundles transactions into a single billable unit. Fields: number
  (ORD-YYYYMM-NNNN, null while open), customer_id, job_id, **location_id**
  (source location for every line scanned in), status
  (open|submitted|cancelled|voided), created_by, submitted_by/_at, voided_by/_at.
  One **open** cart per username at a time.
- **Transaction** — a charge-out line: customer_id (nullable for open-cart lines
  pre-client-pick), job_id, part_id, **order_id** (nullable FK to Order; legacy
  pre-cart rows are NULL), **location_id** (source location), qty, **snapshots**
  of cost & price at the time, **lat / lng / geo_accuracy_m** (optional, captured
  best-effort from the browser), scanned_by, voided. Props
  `total_charge/total_cost/margin`.
- **Role / User** — RBAC (below). **AuditLog** — every sale/void/order
  open/submit/cancel/stocktake/transfer/config change.
- **Setting** — key/value for all UI-configurable settings (see CONFIGURATION.md).

## Cart-based charge-out (v1.9+, the only flow)
- Scanning a known barcode on `/` posts `/api/cart/scan`. If the user has no
  open cart, one is created (`status=open`, `created_by=username`). The line
  is written as a real Transaction immediately so stock decrements right then
  (two techs can't both grab the last cable).
- The user picks Client + Job once via `/api/cart/set`; the handler backfills
  `customer_id` / `job_id` onto every existing line so submitted lines carry
  the right targets at report time.
- `/api/cart/line/{id}` (qty edit) and `/api/cart/line/{id}/remove` (void+
  restore-stock) act on individual lines.
- `/api/cart/custom` (multipart, accepts an image upload) creates an **archived
  Part** on the fly for one-off purchases (e.g. a part bought at Home Depot in
  the field) and adds it to the cart. The Part is hidden from the catalog but
  the line behaves normally for reports/audit.
- `/api/cart/submit` stamps a fresh `ORD-YYYYMM-NNNN` (orders.next_order_number,
  monthly counter), flips status to `submitted`, audit-logs the bundle.
- `/api/cart/cancel` voids every line (restoring stock) and marks status
  `cancelled`. Audit-logged.
- Reports + `/transactions` outerjoin Order and filter `status='submitted' OR
  order_id IS NULL` so open / cancelled carts never pollute history.

## Auth + RBAC (important)
- Modes (UI-managed, stored in DB): `none` (everyone = local Admin), `oidc`
  (any OpenID Connect provider — Authentik/Entra/Okta/…), `forward` (proxy injects
  identity headers; `x-authentik-*` names are the configurable defaults).
- `resolve_user(request, db)` returns `{username, email, role, perms:set, is_admin}`.
  `auth.py` reads OIDC session / forward headers; `rbac.resolve_login()` finds-or-creates
  the `User`, picks a `Role` from **IdP group claim** (`oidc_group_role_map`, lines
  `group = RoleName`) else `rbac_default_role`, with per-user **lock** override and
  always-admin emails. Groups come from the OIDC `groups` claim (configurable) or the
  forward groups header. **OIDC email is only trusted when `email_verified=true`** —
  this protects the admin-email allow-list from IdPs that allow self-set emails.
- **Permissions** (v1.21): `view` (scan + cart + history), `view_catalog`
  (browse /parts /categories /clients /jobs /labels /map /report read-only),
  `see_cost` (show "Our cost" column + the matching Add/Edit input),
  `checkout`, `manage_items`, `manage_clients`, `manage_locations`,
  `view_audit`, `manage_settings`, `manage_users`. **Built-in roles**: Admin
  (all), Manager (everything except admin / users), Operator (view +
  view_catalog + checkout), Viewer (read-only incl. cost), Kiosk (view +
  view_catalog + checkout — no see_cost so a shared device shows client
  prices only). Plus custom roles (Users & roles page).
- **Enforcement**: middleware maps each path→permission via `rbac.required_perm()` and
  403s if lacking; nav links/actions are hidden via the `can(perm)` template helper.
- **Kiosk PIN mode** (v1.10+ feature, v1.20.1+ semantics):
  - Operators authenticate via a numeric PIN on `/welcome` (configured under
    Settings → Kiosk PIN). The session carries `is_kiosk=True`.
  - `auth._kiosk_user(db)` loads the **live** perm set from the Kiosk role
    row in the DB, so edits under `/users#roles` take effect immediately.
  - The middleware enforces a hardcoded path **allowlist** only while
    `_kiosk_lockdown_active()` is true — i.e. the Kiosk role still has its
    built-in floor `{view, view_catalog, checkout}`. The allowlist permits
    `/`, `/transactions`, `/parts`, `/categories`, `/clients`, `/jobs`,
    `/api/cart*`, `/api/search*`, `/api/checkout*`, `/api/void*`. POSTs
    still require `manage_items`/`manage_clients` so the floor is
    read-only.
  - The moment an admin grants any other permission to the Kiosk role
    (`manage_items`, `view_audit`, `manage_settings`, …), the lockdown
    lifts and standard RBAC governs the session. Use this to temporarily
    let a kiosk add catalog items during data-entry, then revoke.
- **CSRF (v1.8+)**: `csrf.CSRFMiddleware` (pure ASGI, sits inside SessionMiddleware
  and outside the route handlers). Token in session cookie, echoed via
  `X-CSRF-Token` header or `_csrf` form field. Exempts `/auth/callback` (IdP
  redirect-back). Required for `forward` auth mode where the proxy attaches SSO
  cookies cross-site without an app-managed cookie to SameSite-pin.
- **Cookie hardening**: SessionMiddleware uses `https_only=True` (unless
  `DISABLE_AUTH=1`) and `same_site=lax`.
- **Default role is Admin** out of the box (so enabling OIDC never locks you out).
  Tighten by setting default to Viewer/Operator + mapping your admin group / listing
  admin emails. **Break-glass**: env `DISABLE_AUTH=1` forces `none`.
- Order of middleware registration matters: `app.add_middleware(CSRFMiddleware)` then
  `app.add_middleware(SessionMiddleware, ...)`. Later-registered = outermost; this
  puts Session outside CSRF (which needs `scope['session']`).

## Money + timezone + markup
- **Ceiling-cents money** (`main.money_filter` Jinja filter, `main.ceil_cents`
  Jinja global, `ceilCents()` in app.js). Every dollar shown — UI and CSV — is
  rounded UP to the next cent. Stored values keep full precision; rounding is
  presentation-only. So a markup of 35% on $1.23 displays as $1.67 (`ceil(1.6605
  cents)`), never $1.66.
- **Default markup %** (Settings → General, admin-only field). Drives the
  client-price autofill on the Add-Item form and the Custom-Item modal via
  `window.DEFAULT_MARKUP_PCT`. The value is in the rendered HTML for everyone
  (no server-side compute path yet) — UI hides it from non-admins.
- **Timezone** (Settings → General, IANA name). Stored as UTC, displayed via
  the `local_dt` Jinja filter (uses Python `zoneinfo` + the `tzdata` pip
  package). Audit log, transactions, scan-page Recent activity all honour it.

## Geo capture + maps
- The scan flow asks the browser for `getCurrentPosition` (best-effort, 4s
  cap) before each `/api/cart/scan` and `/api/cart/custom`. lat/lng/accuracy
  flow through to the Transaction columns. Browser denial / timeout = the
  charge-out still goes through, geo NULL.
- Display:
  - `/transactions` has a collapsible Leaflet map of every visible txn with
    geo; pin popups show order# / part / qty / charge / time / by.
  - `/map` is the full-page version, accepts `?month=` or
    `?date_from=&date_to=`.
- Both maps use Leaflet 1.9.4 vendored under `app/static/vendor/leaflet/`
  (no CDN dependency) and OpenStreetMap tiles.

## Labels & icons
- Code128 (default) or **QR** (`label_barcode_type`). Sizes grouped by brand in
  `labels.LABEL_SIZES` (Brother/DYMO/Zebra/Rollo/Epson/Brady + generic), exact CSS
  `@page`. Labels **dynamically fill** (flex space-between, barcode/QR grows, fonts
  scale to height) — Snipe-IT style. Content toggles + company/footer lines; the
  Settings **live preview** mirrors code type + size + fill.
- Item icons: built-in SVG set (`icons.py`, value `svg:<key>`) chosen from a dropdown
  with preview, OR a custom emoji, OR an uploaded photo (`Part.image`). v1.8
  redraw made every glyph readable at the ~18px display size used in the items
  table. `icon_html()` is a Jinja global; `iconHTML()` mirrors it in JS via
  `window.ICON_SET`.

## Scheduling (emailer.run_due_jobs, hourly thread)
- Low-stock: immediate, once per crossing (re-arms on restock).
- Daily (hour) / Weekly (weekday+hour) / Monthly. Monthly mode = **day-of-month** OR
  **nth weekday** (first/second/third/fourth/last) via `nth_weekday_date()`. De-duped by
  period tag; daily bills prev day, weekly prev 7 days, monthly prev calendar month.
  Times use the **server clock (UTC in Docker)** — the user-facing timezone
  only affects display, not the scheduler.

## Run / build / deploy / release
- Install (one-line): `git clone https://github.com/stephenthecold/inv-keep.git && cd inv-keep && ./install.sh`
  (or the curl-pipe form once the repo is public; see README).
- Install (interactive): `./install.sh` (or `-y`).
- Distribution: published as a multi-arch image at
  `ghcr.io/stephenthecold/inv-keep:{vX.Y.Z, vX.Y, latest}` by
  `.github/workflows/release.yml` on every `v*` tag push.
- Upgrade: `docker compose pull && docker compose up -d` — data persists
  via the `./data` volume mount; `ensure_columns()` runs additive
  migrations on startup.
- Local dev with own changes: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build`
  (uses the local `Dockerfile`, tags the build with the same image name so
  it's interchangeable with the published one).
- Local dev without Docker: `DATABASE_URL=sqlite:///./data/app.db SESSION_SECRET=<32+chars> ./.venv/bin/uvicorn app.main:app --reload`.
- Backup / restore: `./scripts/backup.sh` + `./scripts/restore.sh`, plus
  admin-only UI download at Settings → Backup. See [BACKUPS.md](BACKUPS.md).
- Cut a release: bump `app/version.py` → CHANGELOG entry → commit → `git tag -a vX.Y.Z` → `git push --tags`.
  The tag push triggers `release.yml` which builds + pushes the image.

## How each release was verified (do the same)
`./.venv/bin/python -m py_compile app/*.py` · `node --check app/static/app.js` ·
run uvicorn + curl all pages (expect 200, no tracebacks) · for UI-heavy work, drive a
real browser via the Claude Preview MCP (launch config in `.claude/launch.json` at the
workspace root: starts uvicorn on :8096 with a `data/preview.db`). The compact-JSON API
returns no spaces after colons — grep with that in mind. **Never commit** `.env`, DBs,
`.venv/`, `data/uploads/`, certs, keystores (all gitignored).

## Recent additions worth knowing about (v1.17+)
- **Drill-down `/parts` browser** (v1.18). Root = top-level category cards;
  `?cat=<id>` = sub-cats + items at that level; `?cat=all` = legacy flat
  table; `?cat=none` = uncategorized only. Empty categories hide in browse
  mode (`subtree_counts == 0`); turn **Manage** on (`?manage=1`) to see
  every cat with inline rename / +Sub / Delete. **Single-child chains
  auto-skip** so tapping a top cat lands where items actually live, with
  the full breadcrumb still showing how deep you are.
- **Per-location detail + bulk stocktake** (v1.19). `/locations/<id>`
  lists everything stocked there with a Δ-chip-per-row form; one Save
  commits every changed row and writes one `part.stock_set` audit row
  per change plus a `location.stocktake` rollup.
- **Settings + Users sidebar shell** (v1.20). Both pages include
  `_settings_nav.html`; sections render with `display: none` and JS
  reveals one at a time based on `location.hash` /
  `localStorage["inv-keep:last-settings-tab"]`. POST handlers can keep
  redirecting to plain `/settings` — the tab survives the round-trip.
- **Update check** (v1.20). `GET /settings/check-update` proxies the
  GitHub Releases API with a 5-min DB cache; Settings → Version &
  updates shows "Up to date" or "vX.Y.Z available". The app never
  self-updates (that would break the container boundary); the recipe
  `docker compose pull && docker compose up -d` is inline.
- **Item lifecycle** (v1.21). `POST /parts/<id>/archive` `/restore`
  `/delete`. Delete refuses when the part has any `Transaction` or
  `TransferLine` rows and tells the user to archive instead.

## Known limitations / good next tasks
- **Email OAuth** (MS/Google) implemented but only the **SMTP** path was live-tested.
- **Printing** uses the OS print dialog — no silent printing or raw ZPL/ESC-P. Item
  **photos** show in the UI but labels print the **SVG/emoji icon**, not photos.
- **APK** must be built with Android tooling (local Bubblewrap or the CI workflow).
- **Scheduler** is in-process (fine for one container; not multi-replica). Hour-level
  precision (no minutes).
- **Markup % leakage**: `window.DEFAULT_MARKUP_PCT` is emitted in the rendered
  HTML for every authenticated user; only the UI hides it from non-admins. A
  view-source-curious manager can still read the percentage. Server-side compute
  would close this. (`see_cost` gates the cost column but not the markup default.)
- **Map tiles** load from the public `tile.openstreetmap.org` — works offline-
  ish (no tiles past your cached zoom) but not strictly self-hosted. Swap for a
  self-hosted tileserver if that matters.
- **TWA `packageId`** is `com.invkeep.twa` and `host` is `inv-keep.example.com`
  in `android/twa-manifest.json` — set real values before publishing the APK
  via Bubblewrap. PWA install on Android works without changing either.
- **Stocktake doesn't track who counted what at the row level** — the audit
  rollup records the operator and the reason, and per-part `part.stock_set`
  rows carry the prior→new delta, but there's no separate "stocktake session"
  table tying a multi-row count together for audit-trail searches.

### Fixed in earlier releases (don't reintroduce)
- **Order-number race** — solved by the `IntegrityError` retry loop in
  `api_cart_submit` (v1.10.1). Don't strip it.
- **Cart-row XSS** — `c.lines.forEach` uses `createElement` + `textContent`
  in `app.js` (v1.10.1). Template literals + `innerHTML` would re-open it.
- **NaN-bypass geo** — `_finite()` rejects `lat=NaN, lng=NaN` in
  `/api/cart/scan` (v1.10.1). Range checks alone are bypassable.
- **`/uploads` SVG XSS** — favicon/logo upload allowlist excludes SVG
  (v1.12.2). Stored XSS from same-origin SVG.
- **Mobile bfcache stale CSRF** — `Cache-Control: no-store` stamp on
  every text/html response in `auth_middleware` (v1.12.1).
- **Kiosk role perms ignored** — `_kiosk_user` loads from DB; allowlist
  is a *floor*, not absolute (v1.20.1).
- **Archived items in cart-bar search** — `/api/search` filters
  `archived == False` (v1.20.1).
- **Label print spilling to 5 sheets** — print CSS hides app chrome and
  zeroes body/main padding (v1.20).
- **Label barcode left-anchored** — `.label-barcode svg` scales by
  height with `margin: 0 auto` (v1.21).
- The instance is branded "Connected Technologies". After any update users
  must reload once (network-first SW then keeps assets current).

# Inv-Keep — project state (handoff for the next Claude / contributor)

**Read this first.** It is the durable substitute for the build chat. Reading this +
[CONFIGURATION.md](../CONFIGURATION.md) + [CHANGELOG.md](../CHANGELOG.md) reconstructs
the whole project; you do **not** need the original conversation. Current version:
**v1.7.0** (tags `v1.0.0` … `v1.7.0`, one per release).

## What it is
A small, self-hosted, MSP-oriented inventory **charge-out** app. Scan/search an item
→ confirm quantity, client and job → it logs the charge-out, decrements stock, and
feeds **monthly/weekly/daily billing reports** (cost vs client price vs margin).
Independent of Snipe-IT. Single SQLite DB. Installable PWA for Android AIO scanners.

## Stack
- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2, Jinja2 (server-rendered HTML).
- **DB**: SQLite under `./data` (auto-migrates added columns on startup — see
  `database.ensure_columns()`). No Alembic.
- **Frontend**: one CSS file + one vanilla JS file (`app/static/`). PWA (manifest + SW).
- **Deploy**: Docker Compose; optional bundled **Caddy** for TLS (3 modes), or your
  own reverse proxy. Interactive `install.sh`.
- **Runtime deps**: `requirements.txt` (fastapi, uvicorn, sqlalchemy, authlib,
  python-barcode, qrcode, …). **Build-only** (NOT runtime): `Pillow` (icon PNGs),
  `pyyaml` (validation) — installed ad-hoc in the venv, never imported at runtime.
- **Dev venv**: `.venv/` (gitignored). Tests run via `./.venv/bin/...`.

## Repo map (what each file does)
```
app/
  main.py            ALL routes + middleware (auth + RBAC enforcement) + PWA + labels
  models.py          ORM: Setting, Category, Part(=Item), Client(table "customers"),
                     Job, Transaction, Role, User, AuditLog
  database.py        engine + ensure_columns() additive migrations
  settings_store.py  DB-backed settings + DEFAULTS (env seeds first-run only)
  config.py          env vars (pydantic-settings): DATABASE_URL, SESSION_SECRET,
                     DISABLE_AUTH, + first-run seeds (APP_TITLE, AUTH_MODE, OIDC_*)
  auth.py            effective_mode(), build_oidc() (dynamic), resolve_user()->perms
  rbac.py            PERMISSIONS, DEFAULT_ROLES, seed_roles(), resolve_login(),
                     required_perm(path, method)
  icons.py           built-in SVG icon set (ICON_SET / ICON_CHOICES) + render_html()
  labels.py          Code128 + QR SVG render, LABEL_SIZES presets (Brother/DYMO/Zebra/
                     Rollo/Epson/Brady), grouped_sizes(), size_preset()
  reports.py         build_report_range()/build_report() (client→job→lines, charge/
                     cost/margin) + CSV
  emailer.py         SMTP + OAuth2(MS/Google) send; low-stock + daily/weekly/monthly
                     schedules (run_due_jobs, nth_weekday_date); hourly scheduler thread
  audit.py           audit.record() helper
  version.py         __version__ (footer + Settings)
  templates/*.html   base, scan, parts(=Items), categories, clients, jobs,
                     transactions(=History), report, audit, settings, users, label
  static/            style.css, app.js, icons/ (PWA PNGs)
install.sh           interactive installer (hostname/port/TLS/email/OIDC -> .env -> compose)
docker-compose.yml   app + optional caddy (profile "ssl")
Caddyfile / Caddyfile.custom   Let's Encrypt / bring-your-own-cert (certs/)
android/             twa-manifest.json + README (full APK framework via Bubblewrap)
.github/workflows/   ci.yml (checks), android.yml (build TWA APK)
docs/                PROJECT_STATE(this), CONFIGURATION, CHANGELOG, DEPLOY, ANDROID, PRINTING
scripts/make_icons.py  regenerate PWA icons (needs Pillow; results committed)
```

## Data model (essentials)
- **Part** = an *Item* (UI label "Items"; route paths stay `/parts`; table `parts`).
  Fields: name, description, **icon** (emoji or `svg:<key>`), **image** (uploaded photo
  path), barcode (auto-generated `PCO000001` if blank → printable label), type
  bulk|unique, **unit_cost** (our cost) + **unit_price** (client charge), qty, category,
  low_stock_threshold/alerted, barcode_generated, active.
- **Client** — UI label "Clients"; **table is still `customers`** (preserves data
  through the Customer→Client rename). Full contact record.
- **Job** — belongs to a Client (ticket/WO ref).
- **Transaction** — a charge-out: `customer_id` (the client) + optional `job_id` + part,
  qty, **snapshots** of cost & price at the time. Props `total_charge/total_cost/margin`.
- **Role / User** — RBAC (below). **AuditLog** — every sale/void/config change.
- **Setting** — key/value for all UI-configurable settings (see CONFIGURATION.md).

## Auth + RBAC (important)
- Modes (UI-managed, stored in DB): `none` (everyone = local Admin), `oidc`
  (Authentik/Entra/any OIDC), `forward` (proxy injects X-authentik-* headers).
- `resolve_user(request, db)` returns `{username, email, role, perms:set, is_admin}`.
  `auth.py` reads OIDC session / forward headers; `rbac.resolve_login()` finds-or-creates
  the `User`, picks a `Role` from **IdP group claim** (`oidc_group_role_map`, lines
  `group = RoleName`) else `rbac_default_role`, with per-user **lock** override and
  always-admin emails. Groups come from the OIDC `groups` claim (configurable) or the
  forward groups header.
- **Permissions**: view, checkout, manage_items, manage_clients, view_audit,
  manage_settings, manage_users. **Built-in roles**: Admin (all), Manager, Operator,
  Viewer; plus custom roles (Users & roles page).
- **Enforcement**: middleware maps each path→permission via `rbac.required_perm()` and
  403s if lacking; nav links/actions are hidden via the `can(perm)` template helper.
- **Default role is Admin** out of the box (so enabling OIDC never locks you out).
  Tighten by setting default to Viewer/Operator + mapping your admin group / listing
  admin emails. **Break-glass**: env `DISABLE_AUTH=1` forces `none`.
- `SessionMiddleware` is added LAST so it's outermost (OIDC reads `request.session`).

## Labels & icons
- Code128 (default) or **QR** (`label_barcode_type`). Sizes grouped by brand in
  `labels.LABEL_SIZES` (Brother/DYMO/Zebra/Rollo/Epson/Brady + generic), exact CSS
  `@page`. Labels **dynamically fill** (flex space-between, barcode/QR grows, fonts
  scale to height) — Snipe-IT style. Content toggles + company/footer lines; the
  Settings **live preview** mirrors code type + size + fill.
- Item icons: built-in SVG set (`icons.py`, value `svg:<key>`) chosen from a dropdown
  with preview, OR a custom emoji, OR an uploaded photo (`Part.image`). `icon_html()` is
  a Jinja global; `iconHTML()` mirrors it in JS via `window.ICON_SET`.

## Scheduling (emailer.run_due_jobs, hourly thread)
- Low-stock: immediate, once per crossing (re-arms on restock).
- Daily (hour) / Weekly (weekday+hour) / Monthly. Monthly mode = **day-of-month** OR
  **nth weekday** (first/second/third/fourth/last) via `nth_weekday_date()`. De-duped by
  period tag; daily bills prev day, weekly prev 7 days, monthly prev calendar month.
  Times use the server clock (UTC in Docker).

## Run / build / deploy / release
- Install: `./install.sh` (or `-y`). Manual: `docker compose up -d --build`
  (`--profile ssl` for HTTPS). TLS: Let's Encrypt | own cert (`Caddyfile.custom` +
  `certs/`) | external proxy. See [DEPLOY.md](DEPLOY.md).
- Local dev: `DATABASE_URL=sqlite:///./data/app.db SESSION_SECRET=x ./.venv/bin/uvicorn app.main:app --reload`.
- Cut a release: bump `app/version.py` → add CHANGELOG entry → `git tag -a vX.Y.Z`.

## How each release was verified (do the same)
`./.venv/bin/python -m py_compile app/*.py` · `node --check app/static/app.js` ·
run uvicorn + curl all pages (expect 200, no tracebacks) · for UI-heavy work, drive a
real browser via the Claude Preview MCP (launch config in `.claude/launch.json` at the
workspace root: starts uvicorn on :8096 with a `data/preview.db`). The compact-JSON API
returns no spaces after colons — grep with that in mind. **Never commit** `.env`, DBs,
`.venv/`, `data/uploads/`, certs, keystores (all gitignored).

## Known limitations / good next tasks
- **Email OAuth** (MS/Google) implemented but only the **SMTP** path was live-tested.
- **Printing** uses the OS print dialog — no silent printing or raw ZPL/ESC-P. Item
  **photos** show in the UI but labels print the **SVG/emoji icon**, not photos.
- **APK** must be built with Android tooling (local Bubblewrap or the CI workflow).
- **Scheduler** is in-process (fine for one container; not multi-replica). Hour-level
  precision (no minutes).
- Built-in **SVG icons** are simple hand-drawn glyphs — fine but basic.
- **LICENSE/author** are placeholders ("Inv-Keep contributors", MIT); TWA `packageId`
  is `com.invkeep.twa` — set real values before publishing.
- The user runs their own instance branded "Connected Technologies / TEST". After any
  update they must reload once (network-first SW then keeps assets current).

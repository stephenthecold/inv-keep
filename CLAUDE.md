# Working on Inv-Keep with Claude

Per-session ramp-up. **Read this first**, then [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)
for the full architecture digest. CHANGELOG.md tells you what each version added; this
file tells you how to actually *work* in the repo without re-learning the foot-guns.

## Verification recipe (run this on every meaningful change)

```bash
# Python syntax (uses the working venv at C:\temp\inv-keep-venv on this machine —
# the project's own ./.venv is a broken Linux symlink farm from OneDrive sync).
/c/temp/inv-keep-venv/Scripts/python.exe -m py_compile app/*.py

# JS syntax
node --check app/static/app.js

# Live UI verification — the Claude Preview MCP launch config is at the WORKSPACE
# root (../.claude/launch.json), NOT inside inv-keep/.  Starts uvicorn on :8096
# with data/preview.db.  See preview_start, preview_screenshot, preview_eval.
```

CI runs the equivalent on every push (`.github/workflows/ci.yml`) plus a growing
regression suite: cart-flow end-to-end, NaN-geo rejected, CSRF rejected without
token, XSS payload kept as JSON-escaped data, kiosk PIN lockdown enforces the
view/view_catalog/checkout floor (admin paths 403, catalog browse 200), per-item
stock-modal payload renders on `/parts?cat=all`, per-location stocktake adjusts
counts + writes audit rows. **When you change a URL or perm, expect to update
CI assertions too** — that's how every CI failure since v1.17 has played out.

## Known gotchas on this Windows + OneDrive box

- **Watchfiles + OneDrive miss new-file create events**. After a `Write` of a new
  module (vs an `Edit` of an existing one), restart the preview server cleanly:
  `preview_stop` → delete `app/__pycache__` → `preview_start`. Otherwise you'll see
  `ImportError: cannot import name 'foo' from 'app'` even though the file exists.
- **PowerShell drops Secure cookies over plain HTTP**. The session cookie is
  `Secure=True` unless `DISABLE_AUTH=1`. So PowerShell-driven smoke tests against
  `http://localhost:8000` get CSRF-rejected — POST handlers never see the session.
  Either set `DISABLE_AUTH=1` in `.env` for local smoke OR test through the browser
  via the Preview MCP.
- **The project's `.venv/` is unusable** on this machine (OneDrive turned the Linux
  symlinks into 8-byte text files). Use `C:\temp\inv-keep-venv` instead, or rebuild
  the venv freshly inside the project on a non-OneDrive disk.
- **gh CLI and Docker aren't on the default PATH.** Use the full paths:
  - `C:\Program Files\GitHub CLI\gh.exe`
  - `C:\Program Files\Docker\Docker\resources\bin\docker.exe`

## Known gotchas in production / on the docker host

- **`data/` ownership.** The container runs as uid `10001` (see Dockerfile);
  the bind-mounted `./data` host directory MUST be writable by that uid or
  every write throws `sqlite3.OperationalError: attempt to write a readonly
  database` — and the user-visible symptom is a 500 on whatever POST tries
  to flush an audit-log row (settings saves were the first place we saw
  this). Fix on the host: `sudo chown -R 10001:0 ./data && sudo chmod -R
  u+rwX ./data && docker compose restart inv-keep`. `install.sh` does the
  chown for fresh installs; restores / manual file ops can re-flip it.
- **GitHub Releases creates the tag, not the other way round.** The
  release pipeline (`.github/workflows/release.yml`) triggers on push of
  any `v*` tag and publishes a multi-arch image to GHCR. The Releases UI
  is the ONLY way to create the tag from the browser: Draft new release →
  type the version into "Choose a tag" → click **"+ Create new tag:
  vX.Y.Z on publish"** → Publish. Editing the *title* of an existing
  release does nothing — the workflow doesn't fire and `:latest` on GHCR
  stays put. Verify the tag actually exists with
  `git ls-remote --tags origin "v*"`.
- **"docker compose pull" silently no-ops when the registry hasn't
  changed.** Tells: `Pulled` finishes in <1s AND `up -d` reports
  `Container inv-keep Running` (not `Recreated`/`Started`). Means GHCR's
  `:latest` SHA matches what's already on disk — almost always because the
  release workflow hasn't published a new image yet. Confirm with
  `docker image inspect ghcr.io/stephenthecold/inv-keep:latest --format
  '{{.Created}}'` — old date = no new image.

## When you add X, also do Y

| Adding… | …also do |
|---|---|
| A new POST route | Nothing extra for CSRF — the middleware covers everything except `/auth/callback`. Add `@app.post(...)` and you're done. |
| A new HTML form | Include `<input type="hidden" name="_csrf" value="{{ csrf_token }}">` inside the `<form>`. Forms with the split `<form id=...></form>` + `<input form=...>` pattern need the csrf hidden put INSIDE the empty form element. |
| A new `fetch(..., {method: 'POST'})` in `app.js` | Pass `headers: csrfHeaders(...)` (helper at top of the file). Multipart POSTs use `{'X-CSRF-Token': csrfToken()}` directly — don't override the multipart `Content-Type`. |
| A new column on an existing table | Add it to `app/database.py:_ADDED_COLUMNS` for the additive migration. SQLite can't ALTER a column's NOT NULL — see `_relax_transactions_customer_id` for the rebuild pattern if you need to relax a constraint. |
| A new Jinja template rendering dollar values | Use `{{ x | money(cfg.currency) }}`. Never `'%.2f'|format(x)`. Mirror in JS as `money(n)` (calls `ceilCents` internally — rounds UP to next cent). |
| A new endpoint accepting lat/lng | Validate with `_finite()` not just range checks — NaN compares False against everything, so `lat < -90 or lat > 90` is bypassable. |
| A new Jinja global / window.* | Goes in `<head>` of `base.html`, NOT after `{% block content %}` — block-internal IIFEs run BEFORE the `</main>`-and-after script tags. Bit me twice this build. |
| A new inline `<script>` inside a `{% block content %}` that calls helpers from `app.js` | Wrap in `document.addEventListener('DOMContentLoaded', ...)` — `app.js` is loaded after `</main>` and isn't defined when block scripts execute. |
| A new Leaflet popup or DOM render with user-controlled strings | Build via `document.createElement` + `.textContent`. Template literals + `innerHTML` are an XSS vector — that's the v1.10.1 fix you're not allowed to re-break. |
| A new top-level nav link (Items / Clients / Records sections) | Also add it to the mobile drawer in `base.html` (the `<aside class="nav-mobile">` block). The desktop `<nav>` is hidden below 720px and the drawer is a *separate* flat link list — adding to one and not the other will leave phone users unable to reach the page. v1.12.2 pattern. |
| A new user-uploadable brand asset (favicon, logo, …) | Mirror the favicon route in `app/main.py:settings_branding_favicon`: allowlist of image content-types **excluding SVG** (SVG executes script when fetched from `/uploads/` — stored XSS), size cap, stable filename so the old one is overwritten, cache-bust via `?v=<hex>` query string on the stored path, `audit.record(...)` + `db.commit()`. Add the setting to `settings_store.DEFAULTS` and the upload form to `templates/settings.html`. |
| A new HTML response served behind auth | Nothing extra — `auth_middleware` already stamps `Cache-Control: no-store, must-revalidate, max-age=0` + `Pragma: no-cache` on every `text/html` response so mobile bfcache can't hand back a stale CSRF token. Don't strip those headers downstream. |
| A new GET route exposing the catalog / clients / jobs | Route is gated by `view_catalog` via `rbac.required_perm` (path-prefix rule). Default Kiosk role has `view_catalog`; default everyone else has it too. If you want a path to require *more* than `view_catalog`, add an explicit `if path.startswith("/your-path"): return "manage_X"` branch *above* the catalog block in `required_perm`. v1.21. |
| A new column that exposes our cost / margin to the UI | Gate the render with `{% if can('see_cost') %}`. Default Kiosk does NOT have `see_cost`, so a shared front-desk device shows client price only. Mirror this on the matching Add/Edit input — when hidden it should still POST as `<input type="hidden" name="unit_cost" value="0">` so the form-body shape doesn't change. v1.21. |
| A new path that kiosks should reach by default | Add it to `_KIOSK_ALLOWED_PREFIXES` or `_KIOSK_ALLOWED_EXACT` in `app/main.py`. The allowlist is the **floor** that applies while the Kiosk role still has only its built-in perms (`{view, view_catalog, checkout}`); adding any extra perm to the Kiosk role under /users#roles lifts the lockdown and RBAC alone governs. Conservative default: leave it OUT of the allowlist so admins opt in by editing the role. v1.20.1 / v1.21. |
| A new section to `/settings` | Wrap in `<section class="card settings-tab" id="tab-<slug>" data-tab-pane="<slug>" data-tab-title="<title>">…</section>` and add a matching `{{ item("<slug>", "<label>", "<emoji>") }}` line to `_settings_nav.html`. The tab-switching JS at the bottom of `settings.html` flips visibility per `data-tab-pane`; localStorage remembers the last tab across POST→redirect, so form handlers can keep redirecting to `/settings` (no `?tab=` needed). v1.20.0. |
| A new section to `/users` | Add an anchor `<h2 id="<slug>">` and reuse the same sidebar partial. The inline script at the bottom of `users.html` watches `location.hash` to keep the matching sidebar entry highlighted (currently `users` ↔ `roles`). v1.20.0. |
| A new place that lists items / parts the operator can pick | If the source is `/api/search`, the suggestion row already dims + strikes through zero-stock items via the `.oos` class. Match it elsewhere: check `qty <= 0` and apply class `oos` + a `<span class="tag oos-tag">Out of stock</span>` badge. Do NOT auto-archive items at zero stock — archive is a deliberate admin action. v1.21. |
| A new test against the items table in CI | Hit `/parts?cat=all`, not `/parts` — v1.18 turned the root URL into a category browser (cards, not item rows). The flat table only lives under `?cat=all`. The stock-modal regression test learned this the hard way in PR #6. |

## Conventions

- **Versioning**: SemVer. Bump `app/version.py`, add a CHANGELOG entry under a new
  `## [X.Y.Z] — YYYY-MM-DD` heading, commit. Tag + image-publish is driven by
  GitHub Releases: Draft new release → "Create new tag vX.Y.Z on publish" → target
  `main` → Publish, which fires `release.yml` and pushes a multi-arch image to
  `ghcr.io/stephenthecold/inv-keep` as `:vX.Y.Z` + `:vX.Y` + `:latest`. Per-version
  commits, one per release, is the established pattern.
- **Git author** (per-repo, already set in this checkout): `Inv-Keep <noreply@anthropic.com>`.
- **CHANGELOG voice**: bullets describing the **why** + the **what**, not file lists.
  Group user-facing features above plumbing.
- **Secrets** (`.env`, certs, keystores, `data/*.db`, `data/uploads/`) are gitignored
  and must NEVER be committed. The local `.env` also includes a 64-char dev
  `SESSION_SECRET`; the app refuses to start with anything shorter or the placeholder.
- **Currency display**: ceiling-rounded to the next cent everywhere (so client-facing
  totals never under-bill). Stored values keep full precision; rounding is at the
  presentation layer (`money_filter` in main.py / `ceilCents` in app.js).
- **Time display**: UTC in the DB, configured-tz in templates via `| local_dt(cfg.timezone)`.
  The scheduler uses server clock (UTC in Docker) regardless of the UI tz setting.

## How the post-v1.16 surfaces actually work

These changed enough that the old mental model from v1.16 will mislead you.

### `/parts` is a drill-down browser, not a flat table (v1.18+)

`/parts` has four views, picked by the `cat` query param:

| URL                | View                                                         |
|--------------------|--------------------------------------------------------------|
| `/parts`           | Root — top-level category cards (no item rows)               |
| `/parts?cat=<id>`  | Detail — sub-category cards + items directly in that category |
| `/parts?cat=none`  | Uncategorized items only                                     |
| `/parts?cat=all`   | Legacy flat table, items grouped by category path            |

Two behaviors that surprise people:

- **Empty categories are hidden in browse mode** (subtree-count 0).
  Toggle **Manage** (`?manage=1`) to see every category and get inline
  rename / + Sub / Delete on each card. The Manage toggle is also the
  way to add a sub-category to a parent that has no items in it yet.
- **Single-child chains auto-skip**. Tapping `Wiring` when its only
  populated descendant is `Wiring → Ethernet → Cat 6 → 7ft` drops the
  user straight at `7ft`; the breadcrumb still shows the full path so
  navigation history isn't lost. Disabled in Manage mode so you can
  park on an intermediate to rename / add siblings.

### `/locations/<id>` is the per-location audit + stocktake page (v1.19+)

Every row on `/locations` is a link into `/locations/<id>` which shows
everything stocked there with a bulk stocktake form (prior / new /
live Δ chip per row, single Save commits every changed row). Add `?zero=1`
to also show items that aren't stocked here yet — useful during a count.
`POST /locations/<id>/stocktake` walks `qty_<part_id>` form fields and
writes one `part.stock_set` audit row per change + a `location.stocktake`
rollup so the audit page shows the count as a single event.

### `/settings` and `/users` share a sidebar shell (v1.20+)

`_settings_nav.html` is included by both pages. Tabs are client-side:
sections render with `display: none` and only the one matching the
URL hash / localStorage value is shown. POST handlers can keep
redirecting to plain `/settings` — the JS reads `localStorage['inv-keep:last-settings-tab']`
to restore where the user was. Add a section: see the table above.

### Kiosk permissions (v1.20.1 + v1.21)

Two layers, in order:

1. **`auth._kiosk_user(db)`** loads the live perm set from the Kiosk
   role row in the DB. It used to hardcode `{view, checkout}` — that
   was the bug v1.20.1 fixed. Whatever permissions you set on the
   Kiosk role under `/users#roles` are what the session gets.
2. **`auth_middleware` lockdown floor**. The hardcoded path allowlist
   (`_KIOSK_ALLOWED_EXACT` + `_KIOSK_ALLOWED_PREFIXES`) is enforced
   **only while** `_kiosk_lockdown_active()` is true — i.e. the Kiosk
   role still has only its built-in floor permissions
   (`{view, view_catalog, checkout}`). The moment an admin grants any
   other permission to the Kiosk role (e.g. `view_audit`,
   `manage_items`, `manage_locations`), the lockdown lifts and
   standard RBAC alone governs the session. Settings → Kiosk PIN
   explains this to the operator.

Default Kiosk reach under the lockdown: `/`, `/transactions`,
`/parts`, `/categories`, `/clients`, `/jobs`, `/api/cart*`,
`/api/search*`, `/api/checkout*`, `/api/void*`. Not in the floor:
`/locations`, `/transfers`, `/map`, `/report`, `/labels`, `/audit`,
`/settings`, `/users` — those require explicit perm grants on the
Kiosk role.

### Item lifecycle (v1.21)

Items can now be Archived (reversible, history preserved) or Deleted
(permanent, refused if any `Transaction` or `TransferLine` references
the part — the error message tells the user to archive instead). Routes:

```
POST /parts/<id>/archive   → archived=True   (manage_items)
POST /parts/<id>/restore   → archived=False  (manage_items)
POST /parts/<id>/delete    → row gone        (manage_items, refused on history)
```

The Edit-item modal renders Archive + Delete buttons that retarget
their `form.action` via JS based on `data-archived`. Items at zero
stock are NOT auto-archived — they get an amber "Out of stock" tag
and dim in the cart-bar search. Archive is always an explicit choice.

### Update check (v1.20+)

`GET /settings/check-update` proxies the GitHub Releases API
(`/repos/stephenthecold/inv-keep/releases/latest`) with a 5-minute
DB cache (`store.get/set("_update_cache")`) and returns
`{current, latest, behind, url, error?}`. The Settings → Version &
updates tab calls it via fetch and renders the result. The app
deliberately does not self-update — the recipe is `docker compose pull
&& docker compose up -d` on the host.

## File layout (10-second tour)

```
app/
  main.py         routes + middleware (incl. /welcome splash + no-store stamp) + cart API + map endpoint + helpers
  models.py       Order, Transaction (w/ order_id + lat/lng), Part (w/ archived), …
  database.py     ensure_columns() additive migrations + a SQLite-rebuild path
  csrf.py         pure ASGI CSRFMiddleware + self-recovering 403 page (meta-refresh to same-origin Referer)
  orders.py       cart helpers + ORD-YYYYMM-NNNN generator
  reports.py      build_report_range — outerjoins Order and excludes open/cancelled carts
  static/
    app.js                cart UI + Leaflet popups + global search + mobile nav drawer toggle
    style.css             desktop styles + the < 720px breakpoint where the header collapses to brand + hamburger, plus print rules that hide app chrome for label printing (v1.20)
    vendor/leaflet/       1.9.4, self-hosted (no CDN)
  templates/
    base.html             header + mobile drawer + favicon link
    scan.html             cart card (cart-lines table hides barcode + unit cols on phones)
    parts.html            drill-down category browser (v1.18) — cat-grid + breadcrumb + Edit/Stock/Archive/Delete modals
    location_detail.html  per-location stocktake form (v1.19)
    settings.html         tabbed settings shell — sections wrapped in .settings-tab[data-tab-pane]
    users.html            users + roles inside the same settings shell
    _settings_nav.html    shared sidebar partial — both settings.html and users.html include this
    label.html            label print page (sized + sheet variants; @page CSS pins physical dimensions)
docker-compose.yml   inv-keep (pulls ghcr.io/stephenthecold/inv-keep:${INV_KEEP_VERSION:-latest}) + optional caddy (profile "ssl")
docker-compose.dev.yml override that adds `build: .` for local-source iteration
.github/workflows/release.yml  tag-push trigger that builds + pushes the multi-arch image to GHCR
install.sh           interactive installer (hostname, TLS, OIDC → .env → compose up)
scripts/quickstart.sh  one-line bootstrap (clone + install.sh) for curl-pipe / git-clone
```

## Don't break

- The cart submit retry on `IntegrityError` (`api_cart_submit`) — pins the order#
  race fix from v1.10.1.
- The `_finite()` geo guard — pins the NaN bypass fix.
- The `{% if user.is_admin %}` gate around `window.DEFAULT_MARKUP_PCT` in `base.html` —
  pins the markup % leak fix.
- The `c.lines.forEach` row builder in `app.js` using `createElement` + `textContent` —
  pins the cart XSS fix.
- The `Cache-Control: no-store` stamp on `text/html` responses inside
  `auth_middleware`, and the `wants_html` → `/welcome` branch — pins the
  mobile sign-in fix (bfcache restoring a stale CSRF token, plus the
  multi-redirect login loop). v1.12.1.
- The favicon / logo upload allowlist that excludes SVG. SVG served from
  `/uploads/` (same origin as the app) is a stored-XSS vector. v1.12.2 +
  v1.10.1.
- The mobile drawer markup (`<aside class="nav-mobile">`) and its
  `< 720px` CSS in `style.css`. If you move things around in `base.html`,
  keep both the desktop `<nav>` and the drawer in sync so mobile users
  retain every link. v1.12.2.
- The `_kiosk_lockdown_active()` check in `auth_middleware`. It must
  read the *live* perm set from `user["perms"]`, not a snapshot, or
  edits to the Kiosk role under `/users#roles` won't take effect on
  existing sessions. v1.20.1.
- The `Part.archived` flag is set ONLY by explicit user action (the
  Archive button on the edit modal, or the CUSTOM-… walk-in item
  creation at `/api/cart/custom`). No code path archives a part on
  zero stock — items hitting zero just render with the OOS badge.
  v1.21.
- The `/parts/<id>/delete` "has history" refusal — items with any
  `Transaction.part_id == id` or `TransferLine.part_id == id` must
  not be deletable, since their history would lose the part name.
  v1.21.
- The `view_catalog` permission gates GET on `/parts`, `/categories`,
  `/clients`, `/jobs`, `/labels`, `/map`, `/report` in
  `rbac.required_perm`. Every default role except Kiosk also has
  `see_cost` — gating cost columns / inputs behind `can('see_cost')`
  is what keeps a kiosk session from seeing margin on a shared
  device. v1.21.
- The `.label-barcode svg` print rule that scales by **height** and
  centers via `margin: 0 auto`. The earlier `width: 100%` rule
  left-anchored the python-barcode SVG's fixed-mm output and was the
  centering complaint from the user. v1.21.
- The `Part.archived == False` filter inside `/api/search`. Without
  it, archived CUSTOM-… walk-in items keep showing up in the
  cart-bar autocomplete after their order has closed. v1.20.1.

## Where to push back

If the user asks for something that breaks the patterns above, raise it before
doing it. Same if they ask to commit `.env` / `data/` / `certs/` — those are
gitignored for good reason.

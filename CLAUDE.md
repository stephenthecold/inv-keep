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

CI runs the equivalent on every push (`.github/workflows/ci.yml`): the four
original regression tests (cart-flow end-to-end, NaN-geo rejected, CSRF
rejected without token, XSS payload kept as JSON-escaped data) plus three
feature smokes added since: kiosk-PIN flow (v1.14), admin impersonation
(v1.14), per-location stock + transfers end-to-end (v1.15), and per-item
Stock dialog endpoints (v1.16). Any change touching cart / stock / auth /
permissions should land alongside its own CI block in `ci.yml`.

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
| Any code that mutates `Part.quantity_on_hand` | Also mutate the matching `StockLevel` row — that counter is now the **sum** across `stock_levels`. Use `orders.ensure_stock_row(db, part_id, loc_id)` to fetch-or-create the row, then adjust both. Skipping this breaks the per-location chips on `/parts`, the Stock dialog, and the `/report` "By location" subtotal. |
| Any code that writes a `Transaction` | Stamp `Transaction.location_id` from `cart.location_id`. Voids/cancels MUST restore stock to that same location, not just bump `Part.quantity_on_hand` — see `api_cart_cancel`, `api_cart_line_remove`, `api_void` for the pattern. |
| Any code that opens a new cart (`Order(status="open", ...)`) | Set `cart.location_id = orders.default_location_id(db)` so the first scan doesn't strand stock at the no-location fallback path. Three places do this today: `api_cart_scan`, `api_cart_custom`, `api_cart_walkin`. |
| A new permission key | Append to `app/rbac.py:PERMISSIONS`, slot into the right `DEFAULT_ROLES` rows (Manager picks up most non-admin perms; Kiosk gets only `view` + `checkout`), and rely on `seed_roles()` to additively backfill it onto existing built-in rows on next startup. |
| A new path the Kiosk role shouldn't reach | Either let `required_perm()` route it (Kiosk lacks `manage_*`, `view_audit`, `manage_locations`, `manage_settings`, `manage_users`) or, for paths that only require `view` / `checkout` and would therefore leak, add them to neither `_KIOSK_ALLOWED_EXACT` nor `_KIOSK_ALLOWED_PREFIXES` in `main.py`. The middleware's allow-list gate runs **before** `required_perm()`. |
| A new admin-only "view as another role" check | Read `user.is_impersonating` and `user.real_role` — the regular `user.is_admin` flag is intentionally `False` while impersonating, so guarding admin-only UX on `is_admin` does the right thing automatically. |
| A new nav link in `base.html` | Drop it into the appropriate dropdown (`#inventory-menu` for items / categories / locations / transfers, `#records-menu` for history / report / map / audit) AND the mobile drawer's matching section. Both lists are perm-gated with `{% if can('...') %}`. |

## Conventions

- **Versioning**: SemVer. Bump `app/version.py`, add a CHANGELOG entry under a new
  `## [X.Y.Z] — YYYY-MM-DD` heading, commit, tag with `git tag -a vX.Y.Z -m "vX.Y.Z"`,
  push. Per-version commits, one per release, is the established pattern.
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

## File layout (10-second tour)

```
app/
  main.py         routes + middleware + cart API + locations/transfers + helpers
  models.py       Part, Order, Transaction (now w/ location_id), Location,
                  StockLevel, Transfer, TransferLine, Role, User, Setting, AuditLog
  database.py     ensure_columns() + seed_locations_and_stock() (v1.15 migration:
                  creates "Main" location, copies Part.quantity_on_hand into
                  stock_levels, auto-cancels any pre-1.15 open carts)
  auth.py         OIDC / forward / none + kiosk-PIN session + impersonation
                  downgrade (_maybe_impersonate, _kiosk_user)
  rbac.py         PERMISSIONS (incl. manage_locations), DEFAULT_ROLES (incl. Kiosk),
                  seed_roles() additively backfills new perms onto built-in rows
  csrf.py         pure ASGI CSRFMiddleware (must register BEFORE SessionMiddleware)
  orders.py       cart helpers + ORD-YYYYMM-NNNN generator + stock_at /
                  ensure_stock_row / default_location_id helpers
  reports.py      build_report_range — accepts location_id filter, totals include
                  by_location breakdown for the /report "By location" card
  settings_store.py  DB-backed settings; SECRET_KEYS masks kiosk_pin et al
  static/
    app.js                cart UI (location dropdown + payload), Leaflet popups,
                          per-item Stock modal opener
    vendor/leaflet/       1.9.4, self-hosted (no CDN)
  templates/      base.html (Inventory + Records dropdowns), scan, parts (+ Stock
                  dialog), transactions (+ From column + location filter),
                  report (+ By location card), settings (+ Kiosk card),
                  locations, transfers, transfer_form, transfer_detail
docker-compose.yml   inv-keep + optional caddy (profile "ssl")
install.sh           interactive installer (hostname, TLS, OIDC → .env → compose up)
scripts/quickstart.sh  one-line bootstrap (clone + install.sh) for curl-pipe / git-clone
```

## Stock model in one paragraph

`Part.quantity_on_hand` is now an **aggregate** equal to the sum of
`StockLevel.quantity` rows for that part. Every write that changes one MUST
change the other — there's no trigger or constraint enforcing this; the
audit + CI tests are what catch drift. Carts/scans/voids decrement at
`cart.location_id` (or the line's `location_id` on rewind). Restocks,
moves, and stocktake "set absolute" all go through
`orders.ensure_stock_row(db, part_id, loc_id)` then adjust both sides. The
multi-line transfer flow lives at `/transfers/new`; single-item moves
from the per-item Stock dialog post to `/parts/{id}/stock/move` and write
the same `Transfer` + `TransferLine` rows so history is uniform. On first
boot, `seed_locations_and_stock()` creates a `Main` location and copies
existing quantities into it — idempotent, safe to re-run.

## Auth surface in one paragraph

Three modes (`none` / `oidc` / `forward`) selected via Settings, plus a
**kiosk PIN** session (set on `/welcome`, grants the built-in `Kiosk` role
which only has `view` + `checkout` and is further restricted to a path
allow-list in `auth_middleware`). Admins can **impersonate** another role
via the user menu — `auth._maybe_impersonate` swaps the user dict's
`role`, `perms`, and `is_admin=False` while flagging `is_impersonating`
and stashing the real role under `real_role`. `DISABLE_AUTH=1` env flag is
the break-glass override that forces `none` mode. Permissions are checked
in `rbac.required_perm()` (URL-prefix → permission key) and enforced by
`auth_middleware`. New permission introduced in v1.15: `manage_locations`
(Admin + Manager).

## Don't break

- The cart submit retry on `IntegrityError` (`api_cart_submit`) — pins the order#
  race fix from v1.10.1.
- The `_finite()` geo guard — pins the NaN bypass fix.
- The `{% if user.is_admin %}` gate around `window.DEFAULT_MARKUP_PCT` in `base.html` —
  pins the markup % leak fix.
- The `c.lines.forEach` row builder in `app.js` using `createElement` + `textContent` —
  pins the cart XSS fix.
- The `hmac.compare_digest` call in `/kiosk/login` and the per-IP
  `_KIOSK_PIN_FAILS` throttle — pins the constant-time + brute-force
  hardening from v1.14.
- `auth._maybe_impersonate` setting `is_admin=False` on the downgraded
  dict — every admin-only gate (UI and route) relies on this; flipping
  it back to the real flag re-opens the impersonation gap.
- The `_KIOSK_ALLOWED_EXACT` / `_KIOSK_ALLOWED_PREFIXES` allow-list and
  its early-return in `auth_middleware`. Kiosk has `view`, which would
  otherwise leak `/parts`, `/clients`, `/report`, `/map`, etc. — the
  allow-list is what keeps the kiosk locked to scan + 24h history.
- The Stock-modal DOM-builder in `parts.html` using `createElement` +
  `.textContent` to render per-location rows from `data-stock` JSON.
  Same XSS reasoning as the cart row builder; location names are
  admin-supplied but flow through Jinja's `| tojson` so escaping must
  stay in the DOM layer too.
- `Part.quantity_on_hand` and `Σ stock_levels` MUST stay equal. Every
  cart / void / restock / transfer / move / set-absolute path adjusts
  both sides; if you add a new write path that touches only one, you've
  introduced ledger drift that will surface as wrong totals on `/parts`
  and the Stock dialog.

## Where to push back

If the user asks for something that breaks the patterns above, raise it before
doing it. Same if they ask to commit `.env` / `data/` / `certs/` — those are
gitignored for good reason.

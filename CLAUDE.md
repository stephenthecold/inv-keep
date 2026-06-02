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

CI runs the equivalent on every push (`.github/workflows/ci.yml`) plus four regression
tests: cart-flow end-to-end, NaN-geo rejected, CSRF rejected without token, XSS payload
kept as JSON-escaped data not parseable HTML.

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
    style.css             desktop styles + the < 720px breakpoint where the header collapses to brand + hamburger
    vendor/leaflet/       1.9.4, self-hosted (no CDN)
  templates/      base (header + mobile drawer + favicon link), scan (cart card), parts, transactions (+ inline map), map (full-page), …
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

## Where to push back

If the user asks for something that breaks the patterns above, raise it before
doing it. Same if they ask to commit `.env` / `data/` / `certs/` — those are
gitignored for good reason.

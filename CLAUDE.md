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
  main.py         routes + middleware + cart API + map endpoint + helpers
  models.py       Order, Transaction (w/ order_id + lat/lng), Part (w/ archived), …
  database.py     ensure_columns() additive migrations + a SQLite-rebuild path
  csrf.py         pure ASGI CSRFMiddleware (must register BEFORE SessionMiddleware)
  orders.py       cart helpers + ORD-YYYYMM-NNNN generator
  reports.py      build_report_range — outerjoins Order and excludes open/cancelled carts
  static/
    app.js                cart UI + Leaflet popups + helpers
    vendor/leaflet/       1.9.4, self-hosted (no CDN)
  templates/      base, scan (cart card), parts, transactions (+ inline map), map (full-page), …
docker-compose.yml   inv-keep + optional caddy (profile "ssl")
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

## Where to push back

If the user asks for something that breaks the patterns above, raise it before
doing it. Same if they ask to commit `.env` / `data/` / `certs/` — those are
gitignored for good reason.

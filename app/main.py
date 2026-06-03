import html
import math
import os
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone as _tz
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from . import audit, auth, csrf, emailer, icons, labels, orders, rbac, reports
from . import settings_store as store
from .config import settings

_PLACEHOLDER_SECRET = "change-me-generate-a-random-value"
if (not settings.session_secret
        or settings.session_secret == _PLACEHOLDER_SECRET
        or len(settings.session_secret) < 32):
    raise RuntimeError(
        "SESSION_SECRET must be a random value of 32+ characters. "
        "Generate one with:  python -c \"import secrets; print(secrets.token_hex(32))\""
    )
from .database import Base, SessionLocal, engine, ensure_columns, get_db, seed_locations_and_stock
from .models import (
    AuditLog, Category, Client, Job, Location, Order, Part, Role,
    StockLevel, Transaction, Transfer, TransferLine, User,
)
from .version import __version__

Base.metadata.create_all(bind=engine)
ensure_columns()
# v1.15: seed the Main location + per-part stock_levels from the legacy
# Part.quantity_on_hand counter, and auto-cancel any pre-existing open carts.
seed_locations_and_stock()

# Seed the built-in roles (Admin/Manager/Operator/Viewer) if missing.
_seed_db = SessionLocal()
try:
    rbac.seed_roles(_seed_db)
finally:
    _seed_db.close()

# Uploaded brand assets live alongside the database (under the mounted ./data volume).
UPLOAD_DIR = os.path.join("data", "uploads")
ITEM_IMG_DIR = os.path.join(UPLOAD_DIR, "items")
os.makedirs(ITEM_IMG_DIR, exist_ok=True)

# Top ~20 currencies for the Settings dropdown: (code, symbol, name).
CURRENCIES = [
    ("USD", "$", "US Dollar"), ("EUR", "€", "Euro"), ("GBP", "£", "British Pound"),
    ("JPY", "¥", "Japanese Yen"), ("CNY", "¥", "Chinese Yuan"), ("INR", "₹", "Indian Rupee"),
    ("AUD", "A$", "Australian Dollar"), ("CAD", "C$", "Canadian Dollar"), ("CHF", "Fr", "Swiss Franc"),
    ("HKD", "HK$", "Hong Kong Dollar"), ("SGD", "S$", "Singapore Dollar"), ("SEK", "kr", "Swedish Krona"),
    ("KRW", "₩", "South Korean Won"), ("NZD", "NZ$", "New Zealand Dollar"), ("MXN", "MX$", "Mexican Peso"),
    ("BRL", "R$", "Brazilian Real"), ("ZAR", "R", "South African Rand"), ("RUB", "₽", "Russian Ruble"),
    ("AED", "د.إ", "UAE Dirham"), ("PLN", "zł", "Polish Zloty"),
]

_IMG_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
_MAX_ITEM_IMG = 4 * 1024 * 1024  # 4 MB

# Curated IANA timezone list for the Settings dropdown. Users with anything more
# exotic can hand-edit the DB; this covers >90% of MSP deployments.
TIMEZONES = [
    "UTC",
    "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
    "America/Toronto", "America/Vancouver", "America/Edmonton", "America/Halifax",
    "America/Mexico_City", "America/Bogota", "America/Sao_Paulo",
    "Europe/London", "Europe/Dublin", "Europe/Paris", "Europe/Berlin",
    "Europe/Amsterdam", "Europe/Madrid", "Europe/Rome", "Europe/Stockholm",
    "Europe/Helsinki", "Europe/Warsaw", "Europe/Moscow",
    "Africa/Johannesburg", "Africa/Cairo", "Africa/Lagos",
    "Asia/Dubai", "Asia/Kolkata", "Asia/Bangkok", "Asia/Singapore",
    "Asia/Hong_Kong", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul",
    "Australia/Perth", "Australia/Adelaide", "Australia/Sydney", "Australia/Brisbane",
    "Pacific/Auckland",
]


async def _save_item_image(image, part_id):
    """Save an uploaded item photo, return its served path or None."""
    if not image or not getattr(image, "filename", ""):
        return None
    ext = _IMG_EXT.get(image.content_type)
    if not ext:
        return None
    data = await image.read()
    if not data or len(data) > _MAX_ITEM_IMG:
        return None
    fname = f"{part_id}{ext}"
    with open(os.path.join(ITEM_IMG_DIR, fname), "wb") as fh:
        fh.write(data)
    return f"/uploads/items/{fname}?v={secrets.token_hex(4)}"

app = FastAPI(title=settings.app_title)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["icon_html"] = icons.render_html


def ceil_cents(value) -> float:
    """Round a dollar amount UP to the next cent. Stored values keep full
    precision; this is for *display* (and for the markup autofill when
    creating an item, so the client-visible price never under-bills)."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    # math.ceil on cents; the +1e-9 guards against float drift turning
    # e.g. 1.20 (stored as 1.1999...) into 1.21.
    return math.ceil(v * 100 - 1e-9) / 100


def money_filter(value, currency_symbol=None):
    """Format a number as currency, ceiling-rounded to the nearest cent.
    When called without an explicit symbol the template should pass
    cfg.currency; we don't reach into request state here to keep the
    filter pure."""
    return f"{currency_symbol or ''}{ceil_cents(value):.2f}"


templates.env.globals["ceil_cents"] = ceil_cents
templates.env.filters["money"] = money_filter


def _zone(name):
    """Resolve an IANA timezone name to a ZoneInfo, falling back to UTC for
    typos / unavailable zones (e.g. the system tzdata isn't installed)."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_dt_filter(value, tz_name="UTC", fmt="%Y-%m-%d %H:%M"):
    """Convert a stored UTC datetime to the configured display timezone.
    Templates use:  {{ row.created_at | local_dt(cfg.timezone) }}.
    Naive datetimes (which SQLAlchemy gives us for SQLite columns) are
    assumed UTC — matches how the scheduler / DB writes them."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value  # already preformatted somewhere; pass through
    if value.tzinfo is None:
        value = value.replace(tzinfo=_tz.utc)
    return value.astimezone(_zone(tz_name)).strftime(fmt)


templates.env.filters["local_dt"] = local_dt_filter

# Network-FIRST service worker: always fetch fresh (so CSS/JS/template updates
# apply immediately), falling back to cache only when offline. Static assets are
# cached opportunistically for offline use. Having a fetch handler is also what
# makes the app installable. Bump CACHE to invalidate any older cached assets.
_SERVICE_WORKER_JS = """
const CACHE = 'inv-keep-v2';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  e.respondWith(
    fetch(req).then((res) => {
      if (req.url.includes('/static/') && res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match(req))
  );
});
""".strip()

PUBLIC_PATHS = {"/welcome", "/login", "/auth/callback", "/logout", "/health", "/manifest.webmanifest",
                "/sw.js", "/.well-known/assetlinks.json", "/kiosk/login"}

# In-memory PIN-attempt throttle keyed by client IP. Single-process app, so a
# dict is fine; matches the rest of the codebase (no Redis dependency).
# Maps ip -> (failure_count, locked_until_epoch).
_KIOSK_PIN_FAILS = {}
_KIOSK_PIN_MAX_FAILS = 5

# Paths a kiosk-PIN session is allowed to reach. Everything else returns 403
# from auth_middleware, even when the Kiosk role technically has `view` —
# `view` is needed for /, /api/cart*, and /transactions but not as a free pass
# to /parts, /clients, /report, /map, etc.
_KIOSK_ALLOWED_EXACT = {"/", "/transactions", "/logout"}
_KIOSK_ALLOWED_PREFIXES = ("/api/cart", "/api/search", "/api/checkout", "/api/void")


def _kiosk_allowed(path: str, method: str) -> bool:
    if path in _KIOSK_ALLOWED_EXACT:
        return True
    for p in _KIOSK_ALLOWED_PREFIXES:
        if path == p or path.startswith(p + "/") or path.startswith(p + "?"):
            return True
    return False

_stop_event = threading.Event()


@app.on_event("startup")
def _start_scheduler():
    threading.Thread(target=emailer.scheduler_loop, args=(_stop_event,), daemon=True).start()


@app.on_event("shutdown")
def _stop_scheduler():
    _stop_event.set()


_MAX_REQUEST_BODY = 8 * 1024 * 1024  # 8 MB hard cap — generous wrt logo (2MB) + item image (4MB)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path in PUBLIC_PATHS:
        return await call_next(request)
    # Reject oversized bodies before Starlette buffers them (memory + disk DoS).
    # Content-Length is client-controlled, so this is a coarse first-pass guard;
    # per-endpoint length checks remain authoritative.
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > _MAX_REQUEST_BODY:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
        except ValueError:
            pass
    db = SessionLocal()
    try:
        user = auth.resolve_user(request, db)
        mode = auth.effective_mode(db)
    finally:
        db.close()
    if not user:
        if mode == "oidc":
            # Avoid implicit redirect chains on mobile (slow networks +
            # bfcache cause confusing multi-reload-to-log-in behaviour).
            # Hand off to an explicit splash page with a Sign-in button;
            # API and non-GET requests still get a clean 401 so XHRs can
            # detect the auth boundary without parsing HTML.
            wants_html = (request.method == "GET"
                          and "text/html" in request.headers.get("accept", ""))
            if wants_html and not path.startswith("/api/"):
                return RedirectResponse("/welcome")
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    request.state.user = user

    # Kiosk sessions are limited to a tiny allowlist of paths regardless of
    # their `view` permission — the role has `view` because /, /api/cart*, and
    # /transactions all require it via required_perm(), but the operator
    # behind a kiosk PIN should not see /parts, /clients, /report, /map, etc.
    if user.get("is_kiosk") and not _kiosk_allowed(path, request.method):
        if path.startswith("/api/"):
            return JSONResponse({"ok": False, "error": "kiosk_restricted"}, status_code=403)
        return HTMLResponse(
            "<html><body style='font-family:system-ui;max-width:560px;margin:4rem auto;color:#333'>"
            "<h2>Kiosk mode</h2><p>This page isn't available in kiosk charge-out mode. "
            "<a href='/'>← Back to scan</a></p></body></html>",
            status_code=403,
        )

    # Permission enforcement
    perm = rbac.required_perm(path, request.method)
    perms = user.get("perms", set())
    if not user.get("is_admin") and perm not in perms:
        if path.startswith("/api/"):
            return JSONResponse({"ok": False, "error": "forbidden", "need": perm}, status_code=403)
        return HTMLResponse(
            "<html><body style='font-family:system-ui;max-width:560px;margin:4rem auto;color:#333'>"
            f"<h2>Not permitted</h2><p>Your role (<b>{html.escape(user.get('role',''))}</b>) doesn't have the "
            f"<code>{html.escape(perm)}</code> permission. Ask an administrator for access.</p>"
            "<p><a href='/'>← Back</a></p></body></html>",
            status_code=403,
        )
    response = await call_next(request)
    # Stop browsers (especially mobile Safari + Android Chrome bfcache) from
    # restoring auth'd HTML out of memory with a now-stale CSRF token. Static
    # assets keep their long-cache headers — we only touch HTML.
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


# Content-Security-Policy is intentionally lax: the app uses many inline
# <script>/<style> blocks, so 'unsafe-inline' is required. img-src MUST allow the
# OpenStreetMap tile servers or the Leaflet maps (transactions + map pages) break.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://*.tile.openstreetmap.org; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Apply hardening headers to every response (HTML, API, static, errors)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", _CSP)
    # HSTS only when the request actually arrived over HTTPS (directly or via a
    # TLS-terminating proxy that sets X-Forwarded-Proto). Setting it on a plain
    # HTTP LAN deployment would wrongly force the browser onto HTTPS.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# CSRF must sit INSIDE SessionMiddleware (so it can read scope['session'])
# and OUTSIDE the auth/handler chain (so the body it replays reaches the
# route handler). add_middleware adds to the FRONT of the stack, so the LAST
# add_middleware call ends up outermost: register CSRF first, Session second.
app.add_middleware(csrf.CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=not settings.disable_auth,
    same_site="lax",
)


def ctx(request: Request, db: Session, **kwargs):
    base = {
        "request": request,
        "user": getattr(request.state, "user", {"username": "", "email": ""}),
        "settings": settings,
        "cfg": store.all_settings(db),
        "version": __version__,
        "icon_set": icons.ICON_SET,
        "icon_choices": icons.ICON_CHOICES,
        "now": datetime.utcnow(),
        "csrf_token": csrf.issue(request),
        "disable_auth": settings.disable_auth,
    }
    u = base["user"]
    base["can"] = lambda p: bool(u.get("is_admin")) or p in u.get("perms", set())
    base["msg"] = request.query_params.get("msg", "")
    base["ok"] = request.query_params.get("ok", "1") != "0"
    # Roles for the admin impersonation dropdown in the header user menu.
    # Cheap query (handful of rows). Real_is_admin gates rendering in the
    # template — a session that's already impersonating shouldn't see it
    # twice. We expose the real-admin flag explicitly so the template
    # doesn't have to introspect session state.
    base["real_is_admin"] = bool(u.get("is_admin") or u.get("is_impersonating"))
    if base["real_is_admin"]:
        base["impersonate_roles"] = [
            r.name for r in db.query(Role).order_by(Role.name).all()
            if r.name != "Admin"
        ]
    else:
        base["impersonate_roles"] = []
    base.update(kwargs)
    return base


def current_user(request: Request):
    return getattr(request.state, "user", {"username": ""})


# ---- category helpers ------------------------------------------------------
def category_choices(db):
    """Flat list of (id, indented_label, depth, category) ordered as a tree."""
    cats = db.query(Category).all()
    by_parent = {}
    for c in cats:
        by_parent.setdefault(c.parent_id, []).append(c)
    out = []

    def walk(parent_id, depth):
        for c in sorted(by_parent.get(parent_id, []), key=lambda x: x.name.lower()):
            out.append((c.id, ("    " * depth) + c.name, depth, c))
            walk(c.id, depth + 1)

    walk(None, 0)
    return out


def category_path(db, cat):
    parts = []
    seen = set()
    while cat is not None and cat.id not in seen:
        seen.add(cat.id)
        parts.append(cat.name)
        cat = cat.parent
    return " › ".join(reversed(parts))


def _cat_index(db):
    """Indexed category tree. Returns (by_parent, by_id, paths) where
    `by_parent` maps parent_id (None for top-level) → list of Category
    sorted by name, `by_id` maps id → Category, and `paths` maps id →
    " › "-joined path string. One DB query, reused across the page so
    every row doesn't re-walk the tree."""
    cats = db.query(Category).all()
    by_id = {c.id: c for c in cats}
    by_parent = {}
    for c in cats:
        by_parent.setdefault(c.parent_id, []).append(c)
    for k in by_parent:
        by_parent[k].sort(key=lambda x: (x.name or "").lower())
    paths = {}

    def walk(parent_id, prefix):
        for c in by_parent.get(parent_id, []):
            paths[c.id] = (prefix + " › " + c.name) if prefix else c.name
            walk(c.id, paths[c.id])

    walk(None, "")
    return by_parent, by_id, paths


def _category_counts(db, by_parent, show_archived):
    """Direct + subtree item counts. `direct` maps category_id (or None
    for uncategorized) → count of parts directly assigned. `subtree`
    maps category_id → count including every descendant; populated
    branches are obvious at a glance from card labels."""
    q = db.query(Part.category_id, func.count(Part.id))
    if not show_archived:
        q = q.filter(Part.archived == False)  # noqa: E712
    direct = {cid: n for cid, n in q.group_by(Part.category_id).all()}
    subtree = {}

    def walk(cid):
        total = direct.get(cid, 0)
        for child in by_parent.get(cid, []):
            total += walk(child.id)
        subtree[cid] = total
        return total

    for top in by_parent.get(None, []):
        walk(top.id)
    return direct, subtree


def _category_crumbs(cat, by_id):
    """[(id, name), ...] from root → cat. Cycle-safe via seen-set."""
    out = []
    seen = set()
    cur = cat
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        out.append((cur.id, cur.name))
        cur = by_id.get(cur.parent_id) if cur.parent_id else None
    return list(reversed(out))


def redirect(path, msg="", ok=True):
    sep = "&" if "?" in path else "?"
    if msg:
        path = f"{path}{sep}msg={msg}&ok={'1' if ok else '0'}"
    return RedirectResponse(path, status_code=303)


def reports_money(db, value):
    return f"{store.get(db, 'currency')}{value:.2f}"


# ============================================================ auth routes
@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================ PWA
@app.get("/manifest.webmanifest")
def manifest(db: Session = Depends(get_db)):
    name = store.get(db, "app_title") or "Inv-Keep"
    accent = store.get(db, "brand_accent") or "#2f81f7"
    logo = store.get(db, "brand_logo")
    icons = [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ]
    if logo:
        icons.insert(0, {"src": logo, "sizes": "any", "type": "image/png", "purpose": "any"})
    return JSONResponse(
        {
            "name": name,
            "short_name": name[:12],
            "description": "Inventory charge-out and barcode scanning",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#0f1419",
            "theme_color": accent,
            "icons": icons,
        },
        media_type="application/manifest+json",
    )


@app.get("/.well-known/assetlinks.json")
def asset_links(db: Session = Depends(get_db)):
    """Digital Asset Links for the Android TWA (hides the URL bar). Configure the
    JSON under Settings → Android once you know your APK's signing fingerprint."""
    import json as _json

    raw = store.get(db, "android_asset_links")
    try:
        data = _json.loads(raw) if raw.strip() else []
    except ValueError:
        data = []
    return JSONResponse(data, media_type="application/json")


@app.get("/sw.js")
def service_worker():
    # Served from the root so its scope is the whole app.
    return Response(
        content=_SERVICE_WORKER_JS,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


def _auth_error_page(detail):
    safe_detail = html.escape(str(detail))
    return HTMLResponse(
        "<html><body style='font-family:system-ui;max-width:640px;margin:4rem auto;color:#333'>"
        "<h2>Sign-in is not working</h2>"
        "<p>The OpenID Connect provider could not be reached or rejected the request:</p>"
        f"<pre style='background:#f4f4f4;padding:1rem;border-radius:8px;white-space:pre-wrap'>{safe_detail}</pre>"
        "<p>Check the discovery URL, client ID/secret, and redirect URI in your IdP. "
        "If you are locked out, set the environment variable <code>DISABLE_AUTH=1</code> and "
        "restart the app to regain access, then fix the settings.</p>"
        "</body></html>",
        status_code=502,
    )


@app.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request, db: Session = Depends(get_db)):
    """Mobile-friendly splash. Replaces the implicit redirect chain so the
    user has a single visible tap target instead of three opaque redirects
    in a row, which mobile browsers handle poorly on slow networks."""
    # /welcome is public, so auth_middleware skipped user resolution — do it
    # here so an already-signed-in user landing on the splash bounces straight in.
    if auth.effective_mode(db) == "none" or auth.resolve_user(request, db):
        return RedirectResponse("/")
    title = html.escape(store.get(db, "app_title") or "Inv-Keep")
    accent = html.escape(store.get(db, "brand_accent") or "#2f81f7")
    emoji = html.escape(store.get(db, "brand_emoji") or "📦")
    kiosk_enabled = store.get_bool(db, "kiosk_enabled") and bool(store.get(db, "kiosk_pin"))
    tok = html.escape(csrf.issue(request), quote=True)
    err = html.escape(request.query_params.get("err", ""))
    kiosk_block = ""
    if kiosk_enabled:
        err_html = f'<div class="err">{err}</div>' if err else ""
        kiosk_block = f"""
<div class="kiosk-sep"><span>or</span></div>
<form class="kiosk-form" method="post" action="/kiosk/login" autocomplete="off">
  <input type="hidden" name="_csrf" value="{tok}">
  <label for="kiosk-pin">Kiosk PIN</label>
  <input id="kiosk-pin" name="pin" type="password" inputmode="numeric" pattern="[0-9]*" autocomplete="off" required>
  {err_html}
  <button type="submit">Enter charge-out mode</button>
  <small>Limited mode: scan &amp; charge out only.</small>
</form>"""
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sign in · {title}</title>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="{accent}">
<style>
  html,body{{margin:0;padding:0;background:#0f1115;color:#e6e6e6;font-family:system-ui,-apple-system,sans-serif;
    min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
    padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}}
  .splash{{max-width:380px;width:100%;text-align:center;padding:2rem 1.25rem}}
  .splash .mark{{font-size:4.5rem;line-height:1;margin-bottom:1rem}}
  .splash h1{{font-size:1.5rem;margin:0 0 .35rem}}
  .splash p{{margin:0 0 1.75rem;color:#9aa4b2}}
  .splash a.btn{{display:block;padding:1rem 1.25rem;border-radius:14px;background:{accent};
    color:#fff;text-decoration:none;font-weight:600;font-size:1.05rem;
    -webkit-tap-highlight-color:transparent;touch-action:manipulation}}
  .splash a.btn:active{{transform:scale(.98)}}
  .splash small{{display:block;margin-top:1.25rem;color:#6b7280;font-size:.8rem}}
  .kiosk-sep{{display:flex;align-items:center;gap:.75rem;margin:1.5rem 0 1rem;color:#6b7280;font-size:.85rem}}
  .kiosk-sep::before,.kiosk-sep::after{{content:"";flex:1;height:1px;background:#26303d}}
  .kiosk-form{{display:flex;flex-direction:column;gap:.5rem;text-align:left}}
  .kiosk-form label{{font-size:.85rem;color:#9aa4b2}}
  .kiosk-form input[type=password]{{padding:.85rem 1rem;border-radius:12px;border:1px solid #2a3340;
    background:#161b22;color:#e6e6e6;font-size:1.15rem;letter-spacing:.25rem;text-align:center}}
  .kiosk-form button{{margin-top:.4rem;padding:.9rem 1rem;border:0;border-radius:12px;background:#1f2730;
    color:#e6e6e6;font-weight:600;font-size:1rem;cursor:pointer}}
  .kiosk-form button:active{{transform:scale(.98)}}
  .kiosk-form small{{color:#6b7280;margin-top:.25rem;text-align:center}}
  .kiosk-form .err{{background:#3a1d22;border:1px solid #5a2a32;color:#fca5a5;padding:.5rem .75rem;
    border-radius:8px;font-size:.85rem;text-align:center}}
</style></head><body><div class="splash">
<div class="mark" aria-hidden="true">{emoji}</div>
<h1>{title}</h1>
<p>Tap below to sign in.</p>
<a class="btn" href="/login">Sign in</a>
<small>You'll be redirected to your identity provider.</small>
{kiosk_block}
</div></body></html>"""
    )


@app.get("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    if auth.effective_mode(db) != "oidc":
        return RedirectResponse("/")
    redirect_uri = store.get(db, "oidc_redirect_url") or str(request.url_for("auth_callback"))
    try:
        client = auth.build_oidc(db)
        return await client.idp.authorize_redirect(request, redirect_uri)
    except Exception as e:  # noqa: BLE001
        return _auth_error_page(e)


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        client = auth.build_oidc(db)
        token = await client.idp.authorize_access_token(request)
    except Exception as e:  # noqa: BLE001
        return _auth_error_page(e)
    info = token.get("userinfo") or {}
    claim = store.get(db, "oidc_groups_claim") or "groups"
    groups = info.get(claim) or []
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.replace(";", ",").split(",") if g.strip()]
    # Only trust the email claim if the IdP marked it verified; otherwise drop
    # it so an unverified address can't match rbac_admin_emails.
    raw_email = info.get("email", "")
    email = raw_email if info.get("email_verified") is True else ""
    request.session["user"] = {
        "username": info.get("preferred_username") or raw_email or "user",
        "email": email,
        "groups": list(groups),
    }
    return RedirectResponse("/")


@app.post("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    request.session.pop("kiosk", None)
    request.session.pop("kiosk_started_at", None)
    request.session.pop("impersonate_role", None)
    return RedirectResponse("/welcome", status_code=303)


def _client_ip(request: Request) -> str:
    # X-Forwarded-For is fine to trust for rate-limit bucketing (worst case a
    # spoofer just lengthens their own lockout). Falls back to direct client.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/kiosk/login")
async def kiosk_login(
    request: Request,
    pin: str = Form(""),
    db: Session = Depends(get_db),
):
    """Validate the configured kiosk PIN and grant a locked-down Kiosk
    session. CSRF-protected via the global middleware (the /welcome page
    issues the token). Throttled per-IP after _KIOSK_PIN_MAX_FAILS bad
    attempts."""
    import time as _time
    if not store.get_bool(db, "kiosk_enabled"):
        return RedirectResponse("/welcome", status_code=303)
    expected = store.get(db, "kiosk_pin") or ""
    if not expected:
        return RedirectResponse("/welcome?err=Kiosk+is+enabled+but+no+PIN+is+set.", status_code=303)
    ip = _client_ip(request)
    now = _time.time()
    fails, locked_until = _KIOSK_PIN_FAILS.get(ip, (0, 0))
    if locked_until and now < locked_until:
        wait = int(locked_until - now)
        return RedirectResponse(f"/welcome?err=Too+many+attempts.+Try+again+in+{wait}s.", status_code=303)
    submitted = (pin or "").strip()
    import hmac as _hmac
    if not submitted or not _hmac.compare_digest(submitted, expected.strip()):
        fails += 1
        cooldown = 0
        if fails >= _KIOSK_PIN_MAX_FAILS:
            mins = store.get_int(db, "kiosk_lockout_minutes", 5) or 5
            cooldown = int(now + mins * 60)
            fails = 0  # reset after locking
        _KIOSK_PIN_FAILS[ip] = (fails, cooldown)
        return RedirectResponse("/welcome?err=Incorrect+PIN.", status_code=303)
    # Success — clear throttle, drop any stale OIDC session, install kiosk flag.
    _KIOSK_PIN_FAILS.pop(ip, None)
    request.session.pop("user", None)
    request.session.pop("impersonate_role", None)
    request.session["kiosk"] = True
    request.session["kiosk_started_at"] = datetime.utcnow().isoformat()
    audit.record(db, {"username": store.get(db, "kiosk_username") or "kiosk"},
                 "kiosk.login", "kiosk", None, f"PIN session opened from {ip}")
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/impersonate")
async def impersonate(
    request: Request,
    role: str = Form(""),
    db: Session = Depends(get_db),
):
    """Admin-only: assume another role's permissions for this session.
    Posting role="" (or "stop") clears the override."""
    user = current_user(request)
    # Block when the request is already running under an impersonated identity:
    # otherwise an admin who downgraded to Viewer would still see the dropdown
    # and could chain switches. The "Stop" action below is allowed.
    target = (role or "").strip()
    if target.lower() in ("", "stop", "off", "none"):
        if user.get("is_impersonating") or user.get("is_admin"):
            request.session.pop("impersonate_role", None)
        return redirect("/", "Stopped impersonating.")
    if not user.get("is_admin"):
        return JSONResponse({"detail": "Admin only"}, status_code=403)
    role_row = db.query(Role).filter(Role.name == target).first()
    if not role_row:
        return redirect("/", f"Unknown role '{target}'.", ok=False)
    # Refuse impersonating Admin — pointless and confusing (it's the same
    # permission surface but with the banner permanently up).
    if role_row.is_admin:
        return redirect("/", "Impersonating another Admin role is a no-op.", ok=False)
    request.session["impersonate_role"] = role_row.name
    audit.record(db, user, "impersonate.start", "rbac", role_row.id,
                 f"Admin {user.get('username','')} now viewing as {role_row.name}")
    db.commit()
    return redirect("/", f"Now viewing as {role_row.name}.")


# ============================================================ scan page
@app.get("/", response_class=HTMLResponse)
def scan_page(request: Request, db: Session = Depends(get_db)):
    # Filter archived clients (walk-ins) and their jobs out of the picker
    # dropdowns — they're for one-off orders, not selectable for new ones.
    clients = (
        db.query(Client)
        .filter(Client.active == True, Client.archived == False)  # noqa: E712
        .order_by(Client.name).all()
    )
    jobs = (
        db.query(Job).join(Client, Job.client_id == Client.id)
        .filter(Job.active == True, Client.archived == False)  # noqa: E712
        .order_by(Job.name).all()
    )
    locations = (
        db.query(Location)
        .filter(Location.active == True, Location.archived == False)  # noqa: E712
        .order_by(Location.name).all()
    )
    # Eager-load the relationships the template hits per row so we don't
    # pay 15× N+1 trips on Part / Client / Job lookups when rendering.
    recent = (db.query(Transaction)
                .options(
                    selectinload(Transaction.part),
                    selectinload(Transaction.client),
                    selectinload(Transaction.job),
                )
                .order_by(Transaction.created_at.desc()).limit(15).all())
    # Kiosk sessions optionally start with a pinned default location.
    user = current_user(request)
    default_loc = ""
    if user.get("is_kiosk"):
        default_loc = store.get(db, "kiosk_location_id") or ""
    return templates.TemplateResponse(
        "scan.html",
        ctx(request, db, clients=clients, jobs=jobs, recent=recent,
            locations=locations, default_location_id=default_loc),
    )


# -------------------- cart helpers (response serializer) --------------------

def _cart_payload(db, cart):
    """Build the JSON-able cart dict the frontend renders from."""
    if cart is None:
        return {"open": False}
    lines = orders.cart_lines(db, cart)
    charge, cost, margin = orders.cart_totals(lines)
    return {
        "open": True,
        "id": cart.id,
        "number": cart.number,
        "status": cart.status,
        "client_id": cart.customer_id,
        "client_name": cart.client.name if cart.client else "",
        # True when the attached client is a walk-in (archived) — frontend
        # uses this to render a "Walk-in: <name>" badge instead of the
        # client dropdown.
        "client_walkin": bool(cart.client and cart.client.archived),
        "job_id": cart.job_id,
        "job_name": cart.job.name if cart.job else "",
        "location_id": cart.location_id,
        "location_name": cart.location.name if cart.location else "",
        "lines": [
            {
                "id": ln.id,
                "part_id": ln.part_id,
                "part": ln.part.name,
                "icon": ln.part.icon or "",
                "image": ln.part.image or "",
                "barcode": ln.part.barcode,
                "type": ln.part.type,
                "quantity": ln.quantity,
                "unit_cost": float(ln.unit_cost_at_time),
                "unit_price": float(ln.unit_price_at_time),
                "charge": ln.total_charge,
                "remaining_stock": ln.part.quantity_on_hand,
            }
            for ln in lines
        ],
        "subtotal": charge,
        "cost": cost,
        "margin": margin,
    }


# -------------------- cart API --------------------

class CartScanIn(BaseModel):
    barcode: str
    quantity: int = 1
    # Optional geo capture (best-effort; browser permission may be denied).
    lat: Optional[float] = None
    lng: Optional[float] = None
    geo_accuracy_m: Optional[float] = None


class CartSetIn(BaseModel):
    client_id: Optional[int] = None
    job_id: Optional[int] = None
    location_id: Optional[int] = None


class CartLineIn(BaseModel):
    quantity: int


def _finite(v):
    """True if v is a finite real number. Guards against NaN / Infinity
    sneaking in via JSON — every comparison against NaN returns False, so a
    range check alone is bypassable."""
    if v is None:
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _sanitize_geo(payload):
    lat, lng, acc = payload.lat, payload.lng, payload.geo_accuracy_m
    if not (_finite(lat) and -90 <= lat <= 90):
        lat = None
    if not (_finite(lng) and -180 <= lng <= 180):
        lng = None
    if lat is None or lng is None:
        return None, None, None
    if not (_finite(acc) and acc > 0):
        acc = None
    return lat, lng, acc


@app.get("/api/cart")
def api_cart_get(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    cart = orders.open_cart_for(db, user.get("username", ""))
    return {"ok": True, "cart": _cart_payload(db, cart)}


@app.post("/api/cart/scan")
def api_cart_scan(payload: CartScanIn, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    barcode = payload.barcode.strip()
    part = db.query(Part).filter(Part.barcode == barcode, Part.active == True).first()  # noqa: E712
    if not part:
        return {"ok": False, "error": "unknown_barcode", "barcode": barcode}

    qty = 1 if part.type == "unique" else max(1, payload.quantity)

    cart = orders.open_cart_for(db, user.get("username", ""))
    fresh = False
    if cart is None:
        cart = Order(status="open", created_by=user.get("username", ""))
        # Default to the first active location so the first scan doesn't
        # bounce; the operator can change it via the dropdown.
        cart.location_id = orders.default_location_id(db)
        db.add(cart)
        db.flush()
        fresh = True
        audit.record(db, user, "order.open", "order", cart.id, f"Opened cart #{cart.id}")

    # Enforce stock at the cart's source location. Falls back to a no-location
    # row if the cart somehow still has no location pinned (no active
    # locations) — old behaviour, decrementing Part.quantity_on_hand only.
    location_id = cart.location_id
    if location_id is not None:
        sl = orders.ensure_stock_row(db, part.id, location_id)
        if sl.quantity < qty:
            return {"ok": False, "error": "insufficient_stock",
                    "available": sl.quantity, "part": part.name,
                    "location": cart.location.name if cart.location else ""}
        sl.quantity -= qty
    else:
        if part.quantity_on_hand < qty:
            return {"ok": False, "error": "insufficient_stock",
                    "available": part.quantity_on_hand, "part": part.name}

    part.quantity_on_hand -= qty
    lat, lng, acc = _sanitize_geo(payload)
    txn = Transaction(
        order_id=cart.id,
        part_id=part.id,
        customer_id=cart.customer_id,  # null until /api/cart/set; backfilled on client pick
        job_id=cart.job_id,
        location_id=location_id,
        quantity=qty,
        unit_cost_at_time=part.unit_cost,
        unit_price_at_time=part.unit_price,
        scanned_by=user.get("username", ""),
        lat=lat, lng=lng, geo_accuracy_m=acc,
    )
    db.add(txn)
    db.flush()
    emailer.maybe_low_stock_alert(db, part)
    db.commit()
    return {"ok": True, "cart": _cart_payload(db, cart), "fresh": fresh}


@app.post("/api/cart/custom")
async def api_cart_custom(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    unit_cost: float = Form(0.0),
    unit_price: float = Form(0.0),
    quantity: int = Form(1),
    image: UploadFile = File(None),
    lat: Optional[float] = Form(None),
    lng: Optional[float] = Form(None),
    geo_accuracy_m: Optional[float] = Form(None),
    db: Session = Depends(get_db),
):
    """Log an ad-hoc / off-catalog purchase into the cart (e.g. parts bought
    in the field). Creates an archived Part on the fly so the line still
    flows through reports / audits / voids like any other transaction."""
    user = current_user(request)
    name = name.strip()
    if not name:
        return {"ok": False, "error": "name_required"}
    qty = max(1, int(quantity))
    cart = orders.open_cart_for(db, user.get("username", ""))
    fresh = False
    if cart is None:
        cart = Order(status="open", created_by=user.get("username", ""))
        cart.location_id = orders.default_location_id(db)
        db.add(cart)
        db.flush()
        fresh = True
        audit.record(db, user, "order.open", "order", cart.id, f"Opened cart #{cart.id}")
    # Build the archived Part. It needs a unique barcode — generate one and
    # never bother printing a label for it.
    part = Part(
        name=name,
        description=description.strip(),
        type="bulk",
        unit_cost=unit_cost,
        unit_price=unit_price,
        quantity_on_hand=qty,
        archived=True,
        barcode=f"CUSTOM-{uuid.uuid4().hex[:12].upper()}",
        barcode_generated=False,
        active=True,
    )
    db.add(part)
    db.flush()
    img_path = await _save_item_image(image, part.id)
    if img_path:
        part.image = img_path
    # Decrement stock to 0 — the qty we "bought" is what we're billing.
    part.quantity_on_hand -= qty
    # Stamp a stock_levels row at the cart's location too so the per-location
    # ledger stays consistent: this transient part starts with qty, then we
    # immediately decrement it to 0.
    if cart.location_id is not None:
        sl = orders.ensure_stock_row(db, part.id, cart.location_id)
        sl.quantity = 0
    # Reuse the strict finite-check from _sanitize_geo so a NaN/Infinity in
    # the multipart body can't poison Transaction.lat.
    g_lat = lat if (_finite(lat) and -90 <= lat <= 90) else None
    g_lng = lng if (_finite(lng) and -180 <= lng <= 180) else None
    if g_lat is None or g_lng is None:
        g_lat = g_lng = g_acc = None
    else:
        g_acc = geo_accuracy_m if (_finite(geo_accuracy_m) and geo_accuracy_m > 0) else None
    txn = Transaction(
        order_id=cart.id,
        part_id=part.id,
        customer_id=cart.customer_id,
        job_id=cart.job_id,
        location_id=cart.location_id,
        quantity=qty,
        unit_cost_at_time=part.unit_cost,
        unit_price_at_time=part.unit_price,
        scanned_by=user.get("username", ""),
        note="custom",
        lat=g_lat, lng=g_lng,
        geo_accuracy_m=g_acc if g_acc and g_acc > 0 else None,
    )
    db.add(txn)
    db.flush()
    audit.record(db, user, "order.custom", "transaction", txn.id,
                 f"Custom item: {name} × {qty}")
    db.commit()
    return {"ok": True, "cart": _cart_payload(db, cart), "fresh": fresh}


@app.post("/api/cart/set")
def api_cart_set(payload: CartSetIn, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    cart = orders.open_cart_for(db, user.get("username", ""))
    if cart is None:
        return {"ok": False, "error": "no_open_cart"}
    if payload.client_id:
        client = db.get(Client, payload.client_id)
        if not client:
            return {"ok": False, "error": "no_client"}
        cart.customer_id = client.id
    if payload.job_id:
        job = db.get(Job, payload.job_id)
        if not job or job.client_id != cart.customer_id:
            return {"ok": False, "error": "bad_job"}
        cart.job_id = job.id
    else:
        # 0 or None → caller is clearing the job association.
        cart.job_id = None
    # Source location can be changed mid-cart. Validate it's a real, active
    # location, then re-stamp all open lines so reporting + voids point at
    # the right location.
    if payload.location_id is not None:
        loc = db.get(Location, payload.location_id) if payload.location_id else None
        if payload.location_id and (not loc or not loc.active or loc.archived):
            return {"ok": False, "error": "bad_location"}
        cart.location_id = loc.id if loc else None
    # Backfill the new client/job/location onto open transactions so
    # submitted lines carry the right values at report time.
    line_updates = {}
    if cart.customer_id:
        line_updates["customer_id"] = cart.customer_id
        line_updates["job_id"] = cart.job_id
    if payload.location_id is not None:
        line_updates["location_id"] = cart.location_id
    if line_updates:
        db.query(Transaction).filter(
            Transaction.order_id == cart.id,
            Transaction.voided == False,  # noqa: E712
        ).update(line_updates)
    db.commit()
    return {"ok": True, "cart": _cart_payload(db, cart)}


class CartWalkinIn(BaseModel):
    name: str


@app.post("/api/cart/walkin")
def api_cart_walkin(payload: CartWalkinIn, request: Request, db: Session = Depends(get_db)):
    """Attach a one-time / walk-in client to the open cart. Server creates an
    archived Client with the typed name (so the line still flows through
    reports + audit normally) and points the cart at it. Use this when the
    customer isn't on the recurring roster (cash sale, drop-in, side job)."""
    user = current_user(request)
    name = (payload.name or "").strip()
    if not name:
        return {"ok": False, "error": "name_required"}
    if len(name) > 200:
        return {"ok": False, "error": "name_too_long"}
    cart = orders.open_cart_for(db, user.get("username", ""))
    fresh_cart = False
    if cart is None:
        cart = Order(status="open", created_by=user.get("username", ""))
        cart.location_id = orders.default_location_id(db)
        db.add(cart)
        db.flush()
        fresh_cart = True
        audit.record(db, user, "order.open", "order", cart.id, f"Opened cart #{cart.id} (walk-in start)")
    client = Client(name=name, archived=True, active=True, notes="Walk-in / one-time client")
    db.add(client)
    db.flush()
    cart.customer_id = client.id
    cart.job_id = None
    # Backfill onto any existing scanned lines.
    db.query(Transaction).filter(
        Transaction.order_id == cart.id,
        Transaction.voided == False,  # noqa: E712
    ).update({"customer_id": client.id, "job_id": None})
    audit.record(db, user, "client.walkin", "client", client.id,
                 f"Created walk-in client: {name}")
    db.commit()
    return {"ok": True, "cart": _cart_payload(db, cart), "fresh_cart": fresh_cart}


@app.post("/api/cart/line/{line_id}")
def api_cart_line_update(line_id: int, payload: CartLineIn, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    cart = orders.open_cart_for(db, user.get("username", ""))
    if cart is None:
        return {"ok": False, "error": "no_open_cart"}
    line = db.get(Transaction, line_id)
    if not line or line.order_id != cart.id or line.voided:
        return {"ok": False, "error": "bad_line"}
    new_qty = max(1, int(payload.quantity))
    if line.part.type == "unique":
        new_qty = 1
    delta = new_qty - line.quantity
    # Stock check is against the line's source location (set when scanned).
    if line.location_id is not None:
        sl = orders.ensure_stock_row(db, line.part_id, line.location_id)
        if delta > 0 and sl.quantity < delta:
            return {"ok": False, "error": "insufficient_stock",
                    "available": sl.quantity, "part": line.part.name,
                    "location": line.location.name if line.location else ""}
        sl.quantity -= delta
    else:
        if delta > 0 and line.part.quantity_on_hand < delta:
            return {"ok": False, "error": "insufficient_stock",
                    "available": line.part.quantity_on_hand, "part": line.part.name}
    line.part.quantity_on_hand -= delta
    line.quantity = new_qty
    db.commit()
    return {"ok": True, "cart": _cart_payload(db, cart)}


@app.post("/api/cart/line/{line_id}/remove")
def api_cart_line_remove(line_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    cart = orders.open_cart_for(db, user.get("username", ""))
    if cart is None:
        return {"ok": False, "error": "no_open_cart"}
    line = db.get(Transaction, line_id)
    if not line or line.order_id != cart.id or line.voided:
        return {"ok": False, "error": "bad_line"}
    # Restore to the same location the stock came from.
    if line.location_id is not None:
        sl = orders.ensure_stock_row(db, line.part_id, line.location_id)
        sl.quantity += line.quantity
    line.part.quantity_on_hand += line.quantity
    line.voided = True
    db.commit()
    return {"ok": True, "cart": _cart_payload(db, cart)}


@app.post("/api/cart/submit")
def api_cart_submit(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    cart = orders.open_cart_for(db, user.get("username", ""))
    if cart is None:
        return {"ok": False, "error": "no_open_cart"}
    lines = orders.cart_lines(db, cart)
    if not lines:
        return {"ok": False, "error": "empty_cart"}
    if not cart.customer_id:
        return {"ok": False, "error": "no_client"}
    # next_order_number is SELECT-max+1 with no row lock, so two concurrent
    # submits can both compute the same value. Retry on the UNIQUE-constraint
    # violation; SQLite serializes commits so a single retry almost always
    # wins, and 3 is generous head-room.
    charge, _cost, _margin = orders.cart_totals(lines)
    for attempt in range(3):
        cart.number = orders.next_order_number(db)
        cart.status = "submitted"
        cart.submitted_by = user.get("username", "")
        cart.submitted_at = datetime.utcnow()
        summary = (f"{cart.number}: {len(lines)} line(s) → "
                   f"{cart.client.name}{(' / ' + cart.job.name) if cart.job else ''} "
                   f"({reports_money(db, charge)})")
        audit.record(db, user, "order.submit", "order", cart.id, summary)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            # Re-load the cart row so we can re-stamp; status was rolled back too.
            cart = orders.open_cart_for(db, user.get("username", ""))
            if cart is None:
                return {"ok": False, "error": "no_open_cart"}
    else:
        return {"ok": False, "error": "number_collision"}
    return {"ok": True, "order": {"id": cart.id, "number": cart.number, "subtotal": charge,
                                  "lines": len(lines)}}


@app.post("/api/cart/cancel")
def api_cart_cancel(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    cart = orders.open_cart_for(db, user.get("username", ""))
    if cart is None:
        return {"ok": False, "error": "no_open_cart"}
    # Snapshot first so the audit summary has line count + restored value.
    lines = orders.cart_lines(db, cart)
    charge, _cost, _margin = orders.cart_totals(lines)
    for ln in lines:
        if ln.location_id is not None:
            sl = orders.ensure_stock_row(db, ln.part_id, ln.location_id)
            sl.quantity += ln.quantity
        ln.part.quantity_on_hand += ln.quantity
        ln.voided = True
    cart.status = "cancelled"
    cart.voided_by = user.get("username", "")
    cart.voided_at = datetime.utcnow()
    where = (cart.client.name + (f" / {cart.job.name}" if cart.job else "")) if cart.client else "(no client)"
    summary = (f"Cancelled cart #{cart.id}: {len(lines)} line(s), "
               f"restored {reports_money(db, charge)} of stock → {where}")
    audit.record(db, user, "order.cancel", "order", cart.id, summary)
    db.commit()
    return {"ok": True}


@app.get("/api/search")
def api_search(q: str = "", db: Session = Depends(get_db)):
    q = (q or "").strip()
    if not q:
        return {"results": []}
    like = f"%{q}%"
    rows = (
        db.query(Part)
        .filter(Part.active == True, or_(Part.name.ilike(like), Part.barcode.ilike(like)))  # noqa: E712
        .order_by(Part.name)
        .limit(10)
        .all()
    )
    return {
        "results": [
            {
                "id": p.id,
                "name": p.name,
                "icon": p.icon or "",
                "image": p.image or "",
                "description": p.description or "",
                "barcode": p.barcode,
                "type": p.type,
                "qty": p.quantity_on_hand,
                "unit_cost": float(p.unit_cost),
                "unit_price": float(p.unit_price),
            }
            for p in rows
        ]
    }


@app.get("/api/search/global")
def api_search_global(q: str = "", db: Session = Depends(get_db)):
    """Cross-entity search for the header bar. Returns grouped results
    (items / categories / clients / jobs / orders). Each section caps at 8 so
    the dropdown stays scrollable. Permission gate: every signed-in user
    already has `view`; archived rows are EXCLUDED from header search to
    keep walk-ins / off-catalog items from polluting suggestions."""
    q = (q or "").strip()
    if not q or len(q) < 2:
        return {"q": q, "groups": []}
    like = f"%{q}%"
    CAP = 8

    # Items (active, non-archived; matches name or barcode).
    items = (
        db.query(Part)
        .filter(
            Part.active == True,                # noqa: E712
            Part.archived == False,             # noqa: E712
            or_(Part.name.ilike(like), Part.barcode.ilike(like)),
        )
        .order_by(Part.name)
        .limit(CAP)
        .all()
    )

    # Categories.
    cats = (
        db.query(Category)
        .filter(or_(Category.name.ilike(like), Category.description.ilike(like)))
        .order_by(Category.name)
        .limit(CAP)
        .all()
    )

    # Clients (non-archived for cleanliness; name, contact_name, reference, email).
    clients = (
        db.query(Client)
        .filter(
            Client.archived == False,  # noqa: E712
            or_(
                Client.name.ilike(like),
                Client.contact_name.ilike(like),
                Client.reference.ilike(like),
                Client.email.ilike(like),
            ),
        )
        .order_by(Client.name)
        .limit(CAP)
        .all()
    )

    # Jobs (under non-archived clients).
    jobs = (
        db.query(Job).join(Client, Job.client_id == Client.id)
        .filter(
            Client.archived == False,  # noqa: E712
            or_(Job.name.ilike(like), Job.reference.ilike(like)),
        )
        .order_by(Job.name)
        .limit(CAP)
        .all()
    )

    # Orders (submitted only — open carts shouldn't be searchable history).
    # Match the order number, the client name, or the job name.
    orders_q = (
        db.query(Order)
        .outerjoin(Client, Order.customer_id == Client.id)
        .outerjoin(Job, Order.job_id == Job.id)
        .filter(
            Order.status == "submitted",
            or_(
                Order.number.ilike(like),
                Client.name.ilike(like),
                Job.name.ilike(like),
            ),
        )
        .order_by(Order.submitted_at.desc().nullslast())
        .limit(CAP)
        .all()
    )

    def _g(label, items):
        return {"label": label, "items": items} if items else None

    groups = [g for g in (
        _g("Items", [
            {"name": p.name, "href": f"/parts?q={p.id}#part-{p.id}",
             "meta": f"{p.barcode} · on hand {p.quantity_on_hand}",
             "icon": p.icon or "", "image": p.image or ""}
            for p in items
        ]),
        _g("Categories", [
            {"name": c.name, "href": "/categories",
             "meta": (c.description[:60] + "…") if c.description and len(c.description) > 60 else (c.description or "")}
            for c in cats
        ]),
        _g("Clients", [
            {"name": c.name, "href": "/clients",
             "meta": " · ".join(x for x in (c.reference, c.email, c.phone) if x)}
            for c in clients
        ]),
        _g("Jobs", [
            {"name": j.name, "href": "/jobs",
             "meta": " · ".join(x for x in (j.client.name if j.client else "", j.reference) if x)}
            for j in jobs
        ]),
        _g("Orders", [
            {"name": o.number or f"(open #{o.id})",
             "href": f"/transactions?month={o.submitted_at.strftime('%Y-%m')}" if o.submitted_at else "/transactions",
             "meta": " · ".join(x for x in (
                 o.client.name if o.client else "",
                 o.job.name if o.job else "",
                 o.submitted_at.strftime('%Y-%m-%d') if o.submitted_at else "",
             ) if x)}
            for o in orders_q
        ]),
    ) if g is not None]

    return {"q": q, "groups": groups}


@app.post("/api/void/{txn_id}")
def api_void(txn_id: int, request: Request, db: Session = Depends(get_db)):
    txn = db.get(Transaction, txn_id)
    if not txn or txn.voided:
        return {"ok": False}
    txn.voided = True
    part = db.get(Part, txn.part_id)
    if part:
        part.quantity_on_hand += txn.quantity
    # Restore to the location the line came from. Legacy rows without
    # a location_id only restore the aggregate Part.quantity_on_hand.
    if txn.location_id is not None:
        sl = orders.ensure_stock_row(db, txn.part_id, txn.location_id)
        sl.quantity += txn.quantity
    audit.record(
        db, current_user(request), "sale.void", "transaction", txn.id,
        f"Voided {txn.quantity} × {part.name if part else '?'}",
    )
    db.commit()
    return {"ok": True}


# ============================================================ locations + transfers
@app.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request, db: Session = Depends(get_db)):
    show_archived = request.query_params.get("archived") == "1"
    q = db.query(Location)
    if not show_archived:
        q = q.filter(Location.archived == False)  # noqa: E712
    locs = q.order_by(Location.name).all()
    # One GROUP BY for all totals; cuts N round-trips on a long location
    # list down to a single SUM-and-group query.
    totals = {lid: n for lid, n in (
        db.query(StockLevel.location_id, func.sum(StockLevel.quantity))
          .group_by(StockLevel.location_id).all()
    )}
    return templates.TemplateResponse(
        "locations.html",
        ctx(request, db, locations=locs, totals=totals, show_archived=show_archived),
    )


@app.post("/locations/add")
def locations_add(request: Request, name: str = Form(...), notes: str = Form(""),
                  db: Session = Depends(get_db)):
    nm = (name or "").strip()
    if not nm:
        return redirect("/locations", "Name is required.", ok=False)
    if db.query(Location).filter(Location.name == nm).first():
        return redirect("/locations", f"A location named '{nm}' already exists.", ok=False)
    loc = Location(name=nm, notes=notes.strip(), active=True, archived=False)
    db.add(loc)
    db.flush()
    audit.record(db, current_user(request), "location.add", "location", loc.id, f"Added {nm}")
    db.commit()
    return redirect("/locations", f"Location '{nm}' added.")


@app.post("/locations/{loc_id}/edit")
def locations_edit(loc_id: int, request: Request, name: str = Form(...), notes: str = Form(""),
                   active: str = Form(""), db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        return redirect("/locations", "Location not found.", ok=False)
    nm = (name or "").strip()
    if not nm:
        return redirect("/locations", "Name is required.", ok=False)
    dup = db.query(Location).filter(Location.name == nm, Location.id != loc.id).first()
    if dup:
        return redirect("/locations", f"A location named '{nm}' already exists.", ok=False)
    loc.name = nm
    loc.notes = notes.strip()
    loc.active = active == "on"
    audit.record(db, current_user(request), "location.edit", "location", loc.id, f"Edited {nm}")
    db.commit()
    return redirect("/locations", "Location saved.")


@app.post("/locations/{loc_id}/archive")
def locations_archive(loc_id: int, request: Request, db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        return redirect("/locations", "Location not found.", ok=False)
    # Refuse if there's still stock here — archiving would orphan it.
    stock = (db.query(func.coalesce(func.sum(StockLevel.quantity), 0))
             .filter(StockLevel.location_id == loc.id).scalar() or 0)
    if stock > 0:
        return redirect("/locations",
                        f"Move the remaining {stock} unit(s) out of '{loc.name}' before archiving.",
                        ok=False)
    loc.archived = True
    loc.active = False
    audit.record(db, current_user(request), "location.archive", "location", loc.id, f"Archived {loc.name}")
    db.commit()
    return redirect("/locations", f"Location '{loc.name}' archived.")


@app.post("/locations/{loc_id}/restore")
def locations_restore(loc_id: int, request: Request, db: Session = Depends(get_db)):
    loc = db.get(Location, loc_id)
    if not loc:
        return redirect("/locations", "Location not found.", ok=False)
    loc.archived = False
    loc.active = True
    audit.record(db, current_user(request), "location.restore", "location", loc.id, f"Restored {loc.name}")
    db.commit()
    return redirect("/locations", f"Location '{loc.name}' restored.")


@app.get("/locations/{loc_id}", response_class=HTMLResponse)
def location_detail(loc_id: int, request: Request, db: Session = Depends(get_db)):
    """What's at this location, with inputs to run a stocktake. By default
    only parts with non-zero stock here are listed; ?zero=1 widens the
    view to every non-archived part so an auditor can add stock for a
    new SKU during the count without leaving the page."""
    loc = db.get(Location, loc_id)
    if not loc:
        return redirect("/locations", "Location not found.", ok=False)
    show_zero = request.query_params.get("zero") == "1"
    # One outer-join so we get every Part + its row at this loc (None if
    # never stocked here). Filter archived parts out — they'd just be
    # noise during a count.
    rows = (db.query(Part, StockLevel)
              .outerjoin(StockLevel, and_(
                  StockLevel.part_id == Part.id,
                  StockLevel.location_id == loc.id,
              ))
              .filter(Part.archived == False)  # noqa: E712
              .order_by(Part.name).all())
    by_parent, _by_id, paths = _cat_index(db)
    items = []
    total = 0
    for p, sl in rows:
        qty = sl.quantity if sl else 0
        if not show_zero and qty == 0:
            continue
        items.append({
            "part": p, "qty": qty,
            "cat_label": paths.get(p.category_id, "") if p.category_id else "",
        })
        total += qty
    return templates.TemplateResponse(
        "location_detail.html",
        ctx(request, db, location=loc, items=items, total=total, show_zero=show_zero),
    )


@app.post("/locations/{loc_id}/stocktake")
async def location_stocktake(loc_id: int, request: Request, db: Session = Depends(get_db)):
    """Bulk per-location stocktake. Each input is named `qty_<part_id>` and
    only rows where the new count differs from the current one are written.
    Mirrors the per-part /parts/<id>/stock/set path so audit history reads
    the same regardless of which UI started the adjustment."""
    loc = db.get(Location, loc_id)
    if not loc:
        return redirect("/locations", "Location not found.", ok=False)
    if loc.archived or not loc.active:
        return redirect(f"/locations/{loc_id}", "Location is inactive — restore it first.", ok=False)
    form = await request.form()
    reason = (form.get("reason") or "").strip()
    changes = []
    for key, value in form.multi_items():
        if not key.startswith("qty_"):
            continue
        try:
            part_id = int(key[4:])
            new_qty = int(value)
        except (TypeError, ValueError):
            continue
        if new_qty < 0:
            return redirect(f"/locations/{loc_id}",
                            "Counts can't be negative.", ok=False)
        part = db.get(Part, part_id)
        if part is None or part.archived:
            continue
        sl = orders.ensure_stock_row(db, part.id, loc.id)
        prior = sl.quantity
        if prior == new_qty:
            continue
        delta = new_qty - prior
        sl.quantity = new_qty
        part.quantity_on_hand += delta
        if delta > 0 and part.low_stock_alerted:
            part.low_stock_alerted = False
        changes.append((part, prior, new_qty, delta))

    if not changes:
        return redirect(f"/locations/{loc_id}",
                        "Stocktake submitted — no counts changed.", ok=True)

    note_suffix = f" — {reason}" if reason else ""
    user_obj = current_user(request)
    # Per-part rows for granular history…
    for part, prior, new_qty, delta in changes:
        audit.record(db, user_obj, "part.stock_set", "part", part.id,
                     f"{loc.name}: {prior} → {new_qty} (Δ {delta:+d}) [audit]{note_suffix}")
    # …plus one roll-up entry so the audit page shows the stocktake as a
    # single discoverable event linked to the location.
    audit.record(db, user_obj, "location.stocktake", "location", loc.id,
                 f"Stocktake at {loc.name}: {len(changes)} item(s) adjusted{note_suffix}")
    db.commit()
    return redirect(f"/locations/{loc_id}",
                    f"Stocktake recorded — {len(changes)} item(s) adjusted.")


@app.get("/transfers", response_class=HTMLResponse)
def transfers_page(request: Request, db: Session = Depends(get_db)):
    # selectinload on the locations + lines so the index doesn't fire
    # 200×3 follow-up queries when rendering names + line counts.
    rows = (db.query(Transfer)
            .options(
                selectinload(Transfer.from_location),
                selectinload(Transfer.to_location),
                selectinload(Transfer.lines),
            )
            .order_by(Transfer.created_at.desc())
            .limit(200).all())
    return templates.TemplateResponse(
        "transfers.html",
        ctx(request, db, transfers=rows),
    )


@app.get("/transfers/new", response_class=HTMLResponse)
def transfer_new_page(request: Request, db: Session = Depends(get_db)):
    locs = (db.query(Location)
            .filter(Location.active == True, Location.archived == False)  # noqa: E712
            .order_by(Location.name).all())
    parts = (db.query(Part)
             .filter(Part.active == True, Part.archived == False)  # noqa: E712
             .order_by(Part.name).all())
    return templates.TemplateResponse(
        "transfer_form.html",
        ctx(request, db, locations=locs, parts=parts),
    )


@app.post("/transfers/new")
async def transfer_create(
    request: Request,
    from_location_id: int = Form(...),
    to_location_id: int = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = current_user(request)
    if from_location_id == to_location_id:
        return redirect("/transfers/new", "Source and destination must differ.", ok=False)
    src = db.get(Location, from_location_id)
    dst = db.get(Location, to_location_id)
    if not src or not dst:
        return redirect("/transfers/new", "Unknown location.", ok=False)
    if src.archived or dst.archived or not src.active or not dst.active:
        return redirect("/transfers/new", "Both locations must be active.", ok=False)

    # Lines are submitted as parallel arrays (part_id[] + quantity[]). FastAPI
    # parses repeated form fields when typed as List, but we read the raw form
    # to keep the markup simple.
    form = await request.form()
    part_ids = form.getlist("part_id")
    qtys = form.getlist("quantity")
    pairs = []
    for pid, q in zip(part_ids, qtys):
        try:
            pid_i = int(pid)
            q_i = int(q)
        except (TypeError, ValueError):
            continue
        if pid_i and q_i > 0:
            pairs.append((pid_i, q_i))
    if not pairs:
        return redirect("/transfers/new", "Add at least one part + quantity.", ok=False)

    # Validate sufficient stock at source for every line *before* mutating.
    insufficient = []
    for pid, q in pairs:
        sl = orders.ensure_stock_row(db, pid, src.id)
        if sl.quantity < q:
            part = db.get(Part, pid)
            insufficient.append(f"{part.name if part else '#'+str(pid)}: need {q}, have {sl.quantity}")
    if insufficient:
        return redirect("/transfers/new",
                        "Source doesn't have enough stock — " + "; ".join(insufficient),
                        ok=False)

    # Apply atomically. Source decrement + dest increment + Transfer row, one commit.
    transfer = Transfer(
        from_location_id=src.id,
        to_location_id=dst.id,
        status="completed",
        created_by=user.get("username", ""),
        notes=notes.strip(),
        completed_at=datetime.utcnow(),
    )
    db.add(transfer)
    db.flush()
    for pid, q in pairs:
        src_sl = orders.ensure_stock_row(db, pid, src.id)
        dst_sl = orders.ensure_stock_row(db, pid, dst.id)
        src_sl.quantity -= q
        dst_sl.quantity += q
        db.add(TransferLine(transfer_id=transfer.id, part_id=pid, quantity=q))
    audit.record(db, user, "transfer.complete", "transfer", transfer.id,
                 f"{src.name} → {dst.name}: {len(pairs)} line(s)")
    db.commit()
    return redirect(f"/transfers/{transfer.id}", f"Transfer #{transfer.id} completed.")


@app.get("/transfers/{tid}", response_class=HTMLResponse)
def transfer_detail(tid: int, request: Request, db: Session = Depends(get_db)):
    t = db.get(Transfer, tid)
    if not t:
        return redirect("/transfers", "Transfer not found.", ok=False)
    return templates.TemplateResponse(
        "transfer_detail.html",
        ctx(request, db, transfer=t),
    )


# ============================================================ parts
@app.get("/parts", response_class=HTMLResponse)
def parts_page(request: Request, db: Session = Depends(get_db)):
    """Combined items + category browser. The same URL serves four
    views — root (top-level categories), detail (a single category's
    sub-cats + direct items), uncategorized, and the flat "all
    items" power view — picked by the `cat` query param:

      ?cat=        (or absent)        root
      ?cat=<id>                       detail view of that category
      ?cat=none                       parts with no category
      ?cat=all                        flat list, grouped by category

    The shape is mobile-first drill-down (cards + breadcrumb); CSS
    rearranges into a two-pane layout on wider screens."""
    show_archived = request.query_params.get("archived") == "1"
    cat_param = (request.query_params.get("cat") or "").strip()

    by_parent, by_id, paths = _cat_index(db)
    direct_counts, subtree_counts = _category_counts(db, by_parent, show_archived)

    # Decide which view we're rendering. Unknown cat ids fall back to root
    # rather than erroring — defends against stale bookmarks after a delete.
    view = "root"
    current_cat = None
    if cat_param == "all":
        view = "all"
    elif cat_param == "none":
        view = "uncategorized"
    elif cat_param:
        try:
            sel_id = int(cat_param)
        except ValueError:
            sel_id = None
        if sel_id is not None and sel_id in by_id:
            view = "detail"
            current_cat = by_id[sel_id]

    base_q = db.query(Part)
    if not show_archived:
        base_q = base_q.filter(Part.archived == False)  # noqa: E712

    manage_mode = (request.query_params.get("manage") == "1")

    def _visible_children(parent_id):
        """Children of `parent_id`, with empty branches hidden unless we're
        in manage mode. Empties (subtree count 0) just add clutter when
        browsing; in manage mode they need to be visible so admins can
        rename / delete / fill them."""
        kids = by_parent.get(parent_id, [])
        if manage_mode:
            return kids
        return [c for c in kids if subtree_counts.get(c.id, 0) > 0]

    sub_cats = []
    crumbs = []
    if view == "root":
        items = []
        sub_cats = _visible_children(None)
    elif view == "detail":
        # Auto-skip single-child chains: if the current category has no
        # direct items and exactly one populated sub-category, fall through
        # to it. Keep going until we hit a node that holds items, has
        # multiple kids, or is a leaf. Lets a tree like
        # Wiring → Ethernet → Cat 6 → 7ft land you straight at 7ft.
        # Disabled in manage mode so admins can park on intermediates to
        # rename / add siblings.
        if not manage_mode:
            seen = set()
            while current_cat is not None and current_cat.id not in seen:
                seen.add(current_cat.id)
                if direct_counts.get(current_cat.id, 0) > 0:
                    break
                kids = _visible_children(current_cat.id)
                if len(kids) == 1:
                    current_cat = kids[0]
                    continue
                break
        items = base_q.filter(Part.category_id == current_cat.id).order_by(Part.name).all()
        sub_cats = _visible_children(current_cat.id)
        crumbs = _category_crumbs(current_cat, by_id)
    elif view == "uncategorized":
        items = base_q.filter(Part.category_id.is_(None)).order_by(Part.name).all()
    else:  # "all"
        rows = base_q.order_by(Part.name).all()
        # Sort so categories cluster, with uncategorized at the bottom.
        def _key(p):
            label = paths.get(p.category_id, "") if p.category_id else "~"
            return (label.lower(), (p.name or "").lower())
        items = sorted(rows, key=_key)

    cats_flat = category_choices(db)
    cat_names = paths  # already path-formatted, reuse for table column display

    locations = (db.query(Location)
                 .filter(Location.active == True, Location.archived == False)  # noqa: E712
                 .order_by(Location.name).all())
    parts = items  # downstream stock-map builder references `parts`
    # Scope the per-location stock query to just the parts we're rendering
    # (root view shows no items, so we skip it entirely). Older versions
    # pulled the whole stock_levels table on every page hit; this caps the
    # query to the current page's parts.
    stock_map = {}
    if parts:
        part_ids = [p.id for p in parts]
        for sl in (db.query(StockLevel)
                     .filter(StockLevel.part_id.in_(part_ids)).all()):
            stock_map[(sl.part_id, sl.location_id)] = sl.quantity
    # Per-part [(loc, qty), ...] for the chips on the table; skip zero rows
    # so the inline row stays compact.
    part_stock = {}
    # Per-part full per-location array (includes zeros) — fed to the Stock
    # modal as a JSON data-* attr so the modal can show every location.
    part_stock_full = {}
    for p in parts:
        rows = []
        full = []
        for loc in locations:
            qty = stock_map.get((p.id, loc.id), 0)
            full.append({"loc_id": loc.id, "loc_name": loc.name, "qty": qty})
            if qty:
                rows.append((loc, qty))
        part_stock[p.id] = rows
        part_stock_full[p.id] = full
    total_count = sum(direct_counts.values())
    uncategorized_count = direct_counts.get(None, 0)
    def qs(cat=None, archived=None, manage=None):
        """Build a /parts query string preserving the surrounding state.
        Passing `None` for an arg means "keep current"; passing `""` or
        `False` drops it. Lets templates link to the same page with one
        toggle changed without re-listing every other param."""
        out_cat = cat_param if cat is None else cat
        out_arch = show_archived if archived is None else archived
        out_manage = manage_mode if manage is None else manage
        parts_qs = []
        if out_cat:
            parts_qs.append(f"cat={out_cat}")
        if out_arch:
            parts_qs.append("archived=1")
        if out_manage:
            parts_qs.append("manage=1")
        return ("?" + "&".join(parts_qs)) if parts_qs else ""

    return templates.TemplateResponse(
        "parts.html",
        ctx(request, db, view=view, parts=parts, categories=cats_flat,
            cat_names=cat_names, current_cat=current_cat, sub_cats=sub_cats,
            crumbs=crumbs, direct_counts=direct_counts,
            subtree_counts=subtree_counts, top_cats=by_parent.get(None, []),
            uncategorized_count=uncategorized_count, total_count=total_count,
            show_archived=show_archived, locations=locations,
            part_stock=part_stock, part_stock_full=part_stock_full,
            manage=manage_mode, cat_param=cat_param, qs=qs,
            prefill=request.query_params.get("barcode", "")),
    )


@app.post("/parts/add")
async def parts_add(
    request: Request,
    name: str = Form(...),
    barcode: str = Form(""),
    type: str = Form("bulk"),
    icon: str = Form(""),
    description: str = Form(""),
    unit_cost: float = Form(0.0),
    unit_price: float = Form(0.0),
    quantity_on_hand: int = Form(0),
    category_id: str = Form(""),
    low_stock_threshold: str = Form(""),
    image: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    barcode = barcode.strip()
    cat_id = int(category_id) if category_id else None
    threshold = int(low_stock_threshold) if low_stock_threshold.strip() else None
    if type == "unique":
        quantity_on_hand = max(quantity_on_hand, 1)

    if barcode:
        if db.query(Part).filter(Part.barcode == barcode).first():
            return redirect("/parts", "That barcode already exists.", ok=False)
        part = Part(
            name=name.strip(), barcode=barcode, type=type, unit_cost=unit_cost, unit_price=unit_price,
            quantity_on_hand=quantity_on_hand, category_id=cat_id, low_stock_threshold=threshold,
            icon=icon.strip(), description=description.strip(),
        )
        db.add(part)
        db.flush()
        generated = False
    else:
        part = Part(
            name=name.strip(), barcode="tmp-" + uuid.uuid4().hex, type=type, unit_cost=unit_cost,
            unit_price=unit_price, quantity_on_hand=quantity_on_hand, category_id=cat_id,
            low_stock_threshold=threshold, icon=icon.strip(), description=description.strip(),
        )
        db.add(part)
        db.flush()
        part.barcode = labels.generate_value(part.id)
        part.barcode_generated = True
        generated = True

    img_path = await _save_item_image(image, part.id)
    if img_path:
        part.image = img_path
    # Seed the new part's stock at the default location so per-location
    # accounting matches the legacy single counter on day one.
    default_loc = orders.default_location_id(db)
    if default_loc is not None and part.quantity_on_hand:
        sl = orders.ensure_stock_row(db, part.id, default_loc)
        sl.quantity = part.quantity_on_hand
    audit.record(db, current_user(request), "part.create", "part", part.id, f"Created {part.name} ({part.barcode})")
    db.commit()
    if generated:
        return redirect(f"/parts/{part.id}/label", "Barcode generated — print the label.")
    return redirect("/parts", "Part added.")


@app.post("/parts/{part_id}/edit")
async def parts_edit(
    part_id: int,
    request: Request,
    name: str = Form(...),
    icon: str = Form(""),
    description: str = Form(""),
    unit_cost: float = Form(0.0),
    unit_price: float = Form(0.0),
    category_id: str = Form(""),
    low_stock_threshold: str = Form(""),
    active: str = Form(""),
    image: UploadFile = File(None),
    remove_image: str = Form(""),
    db: Session = Depends(get_db),
):
    part = db.get(Part, part_id)
    if part:
        part.name = name.strip()
        part.icon = icon.strip()
        part.description = description.strip()
        part.unit_cost = unit_cost
        part.unit_price = unit_price
        part.category_id = int(category_id) if category_id else None
        part.low_stock_threshold = int(low_stock_threshold) if low_stock_threshold.strip() else None
        part.active = active == "on"
        if remove_image == "on":
            part.image = ""
        img_path = await _save_item_image(image, part.id)
        if img_path:
            part.image = img_path
        audit.record(db, current_user(request), "part.edit", "part", part.id, f"Edited {part.name}")
        db.commit()
    return redirect("/parts", "Part saved.")


@app.post("/parts/{part_id}/restock")
def parts_restock(part_id: int, request: Request, amount: int = Form(...),
                  location_id: str = Form(""), db: Session = Depends(get_db)):
    part = db.get(Part, part_id)
    if not part:
        return redirect("/parts", "Part not found.", ok=False)
    # Resolve target location: explicit -> first active.
    loc_id = None
    if location_id.strip():
        try:
            loc_id = int(location_id)
        except ValueError:
            loc_id = None
    if loc_id is None:
        loc_id = orders.default_location_id(db)
    if loc_id is None:
        return redirect("/parts", "No active location to restock into — add one under Inventory → Locations.", ok=False)
    loc = db.get(Location, loc_id)
    if not loc or loc.archived or not loc.active:
        return redirect("/parts", "Pick an active location.", ok=False)
    sl = orders.ensure_stock_row(db, part.id, loc.id)
    sl.quantity += amount
    part.quantity_on_hand += amount
    if part.low_stock_alerted:
        part.low_stock_alerted = False
    audit.record(db, current_user(request), "part.restock", "part", part.id,
                 f"+{amount} → {loc.name} (total {part.quantity_on_hand})")
    db.commit()
    return redirect("/parts", "Stock updated.")


@app.post("/parts/{part_id}/stock/set")
def parts_set_stock(
    part_id: int,
    request: Request,
    location_id: int = Form(...),
    quantity: int = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    """Stocktake helper: set the absolute on-hand count for this part at the
    given location. Adjusts Part.quantity_on_hand by the delta so the
    aggregate counter stays equal to the sum of stock_levels."""
    if quantity < 0:
        return redirect("/parts", "Stocktake count cannot be negative.", ok=False)
    part = db.get(Part, part_id)
    if not part:
        return redirect("/parts", "Part not found.", ok=False)
    loc = db.get(Location, location_id)
    if not loc or loc.archived or not loc.active:
        return redirect("/parts", "Pick an active location.", ok=False)
    sl = orders.ensure_stock_row(db, part.id, loc.id)
    prior = sl.quantity
    delta = quantity - prior
    sl.quantity = quantity
    part.quantity_on_hand += delta
    if delta > 0 and part.low_stock_alerted:
        part.low_stock_alerted = False
    note = f" — {reason.strip()}" if reason.strip() else ""
    audit.record(db, current_user(request), "part.stock_set", "part", part.id,
                 f"{loc.name}: {prior} → {quantity} (Δ {delta:+d}){note}")
    db.commit()
    return redirect("/parts", f"Set {part.name} at {loc.name} to {quantity}.")


@app.post("/parts/{part_id}/stock/move")
def parts_move_stock(
    part_id: int,
    request: Request,
    from_location_id: int = Form(...),
    to_location_id: int = Form(...),
    quantity: int = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Single-line transfer for one specific part — drives the per-item
    Stock modal's Move action so the operator doesn't have to leave /parts
    to disperse stock. Writes a Transfer row identical to the multi-line
    flow at /transfers/new so history is uniform."""
    user = current_user(request)
    if quantity <= 0:
        return redirect("/parts", "Quantity must be positive.", ok=False)
    if from_location_id == to_location_id:
        return redirect("/parts", "Source and destination must differ.", ok=False)
    part = db.get(Part, part_id)
    src = db.get(Location, from_location_id)
    dst = db.get(Location, to_location_id)
    if not part or not src or not dst:
        return redirect("/parts", "Unknown part or location.", ok=False)
    if src.archived or dst.archived or not src.active or not dst.active:
        return redirect("/parts", "Both locations must be active.", ok=False)
    src_sl = orders.ensure_stock_row(db, part.id, src.id)
    if src_sl.quantity < quantity:
        return redirect("/parts",
                        f"{src.name} only has {src_sl.quantity} of {part.name}.",
                        ok=False)
    dst_sl = orders.ensure_stock_row(db, part.id, dst.id)
    transfer = Transfer(
        from_location_id=src.id,
        to_location_id=dst.id,
        status="completed",
        created_by=user.get("username", ""),
        notes=notes.strip(),
        completed_at=datetime.utcnow(),
    )
    db.add(transfer)
    db.flush()
    src_sl.quantity -= quantity
    dst_sl.quantity += quantity
    db.add(TransferLine(transfer_id=transfer.id, part_id=part.id, quantity=quantity))
    audit.record(db, user, "transfer.complete", "transfer", transfer.id,
                 f"{src.name} → {dst.name}: {quantity} × {part.name}")
    db.commit()
    return redirect("/parts", f"Moved {quantity} × {part.name}: {src.name} → {dst.name}.")


def _label_ctx(request, db, parts, sheet):
    size_key = request.query_params.get("size") or store.get(db, "label_size") or "sheet"
    preset = labels.size_preset(size_key)
    show_code = store.get_bool(db, "label_show_code_text")
    btype = store.get(db, "label_barcode_type") or "code128"
    # Scale the 1D barcode height to the label so big labels fill instead of empty.
    ph = preset["h"]
    module_height = max(8.0, min(ph * 0.42, 60.0)) if ph else 14.0

    def _render(p):
        if btype == "qr":
            return labels.render_qr_svg(p.barcode)
        return labels.render_svg(p.barcode, show_text=show_code, module_height=module_height)

    rendered = [(p, _render(p)) for p in parts]
    content = {
        "icon": store.get_bool(db, "label_show_icon"),
        "name": store.get_bool(db, "label_show_name"),
        "price": store.get_bool(db, "label_show_price"),
        "description": store.get_bool(db, "label_show_description"),
        "category": store.get_bool(db, "label_show_category"),
        "company": store.get(db, "label_company_text"),
        "extra": store.get(db, "label_extra_text"),
    }
    return dict(
        parts_to_print=rendered,
        sheet=sheet,
        barcode_type=btype,
        size_groups=labels.grouped_sizes(),
        size_key=size_key,
        page_w=preset["w"],
        page_h=preset["h"],
        size_label=preset["label"],
        content=content,
        currency=store.get(db, "currency"),
    )


@app.get("/parts/{part_id}/label", response_class=HTMLResponse)
def part_label(part_id: int, request: Request, db: Session = Depends(get_db)):
    part = db.get(Part, part_id)
    if not part:
        return redirect("/parts", "Part not found.", ok=False)
    return templates.TemplateResponse("label.html", ctx(request, db, base_path=f"/parts/{part_id}/label", **_label_ctx(request, db, [part], False)))


@app.get("/labels", response_class=HTMLResponse)
def labels_sheet(request: Request, db: Session = Depends(get_db)):
    parts = (
        db.query(Part)
        .filter(Part.barcode_generated == True, Part.active == True)  # noqa: E712
        .order_by(Part.name)
        .all()
    )
    return templates.TemplateResponse("label.html", ctx(request, db, base_path="/labels", **_label_ctx(request, db, parts, True)))


# ============================================================ categories
@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db)):
    # Direct (non-archived) item counts per category, so the Categories page
    # surfaces which buckets are actually populated.
    cat_counts = {}
    rows = (db.query(Part.category_id, func.count(Part.id))
              .filter(Part.archived == False)  # noqa: E712
              .group_by(Part.category_id).all())
    for cid, n in rows:
        if cid is not None:
            cat_counts[cid] = n
    return templates.TemplateResponse(
        "categories.html",
        ctx(request, db, tree=category_choices(db), cat_counts=cat_counts),
    )


@app.post("/categories/add")
def categories_add(request: Request, name: str = Form(...), description: str = Form(""), parent_id: str = Form(""), db: Session = Depends(get_db)):
    cat = Category(name=name.strip(), description=description.strip(), parent_id=int(parent_id) if parent_id else None)
    db.add(cat)
    db.flush()
    audit.record(db, current_user(request), "category.create", "category", cat.id, f"Created {cat.name}")
    db.commit()
    return redirect("/categories", "Category added.")


@app.post("/categories/{cat_id}/edit")
def categories_edit(cat_id: int, request: Request, name: str = Form(...), description: str = Form(""), parent_id: str = Form(""), db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id)
    if cat:
        new_parent = int(parent_id) if parent_id else None
        if new_parent != cat.id:
            cat.parent_id = new_parent
        cat.name = name.strip()
        cat.description = description.strip()
        audit.record(db, current_user(request), "category.edit", "category", cat.id, f"Edited {cat.name}")
        db.commit()
    return redirect("/categories", "Category saved.")


@app.post("/categories/{cat_id}/delete")
def categories_delete(cat_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id)
    if cat:
        for child in list(cat.children):
            child.parent_id = cat.parent_id
        for p in db.query(Part).filter(Part.category_id == cat_id).all():
            p.category_id = cat.parent_id
        audit.record(db, current_user(request), "category.delete", "category", cat.id, f"Deleted {cat.name}")
        db.delete(cat)
        db.commit()
    return redirect("/categories", "Category deleted.")


# ============================================================ clients
@app.get("/clients", response_class=HTMLResponse)
def clients_page(request: Request, db: Session = Depends(get_db)):
    show_archived = request.query_params.get("archived") == "1"
    q = db.query(Client)
    if not show_archived:
        q = q.filter(Client.archived == False)  # noqa: E712
    clients = q.order_by(Client.name).all()
    return templates.TemplateResponse(
        "clients.html",
        ctx(request, db, clients=clients, show_archived=show_archived),
    )


@app.post("/clients/add")
def clients_add(
    request: Request,
    name: str = Form(...),
    reference: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    c = Client(
        name=name.strip(), reference=reference.strip(), contact_name=contact_name.strip(),
        email=email.strip(), phone=phone.strip(), location=location.strip(),
        address=address.strip(), notes=notes.strip(),
    )
    db.add(c)
    db.flush()
    audit.record(db, current_user(request), "client.create", "client", c.id, f"Created {c.name}")
    db.commit()
    return redirect("/clients", "Client added.")


@app.post("/clients/{client_id}/edit")
def clients_edit(
    client_id: int,
    request: Request,
    name: str = Form(...),
    reference: str = Form(""),
    contact_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    location: str = Form(""),
    address: str = Form(""),
    notes: str = Form(""),
    active: str = Form(""),
    db: Session = Depends(get_db),
):
    c = db.get(Client, client_id)
    if c:
        c.name = name.strip()
        c.reference = reference.strip()
        c.contact_name = contact_name.strip()
        c.email = email.strip()
        c.phone = phone.strip()
        c.location = location.strip()
        c.address = address.strip()
        c.notes = notes.strip()
        c.active = active == "on"
        audit.record(db, current_user(request), "client.edit", "client", c.id, f"Edited {c.name}")
        db.commit()
    return redirect("/clients", "Client saved.")


# ============================================================ jobs
@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, db: Session = Depends(get_db)):
    # Hide jobs belonging to archived clients (walk-ins) unless explicitly asked.
    show_archived = request.query_params.get("archived") == "1"
    q = db.query(Job).join(Client, Job.client_id == Client.id)
    if not show_archived:
        q = q.filter(Client.archived == False)  # noqa: E712
    jobs = q.order_by(Client.name, Job.name).all()
    clients = (
        db.query(Client)
        .filter(Client.active == True, Client.archived == False)  # noqa: E712
        .order_by(Client.name).all()
    )
    return templates.TemplateResponse(
        "jobs.html",
        ctx(request, db, jobs=jobs, clients=clients, show_archived=show_archived),
    )


@app.post("/jobs/add")
def jobs_add(
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    reference: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if not db.get(Client, client_id):
        return redirect("/jobs", "Pick a valid client.", ok=False)
    job = Job(client_id=client_id, name=name.strip(), reference=reference.strip(), notes=notes.strip())
    db.add(job)
    db.flush()
    audit.record(db, current_user(request), "job.create", "job", job.id, f"Created {job.name}")
    db.commit()
    return redirect("/jobs", "Job added.")


@app.post("/jobs/{job_id}/edit")
def jobs_edit(
    job_id: int,
    request: Request,
    client_id: int = Form(...),
    name: str = Form(...),
    reference: str = Form(""),
    notes: str = Form(""),
    active: str = Form(""),
    db: Session = Depends(get_db),
):
    job = db.get(Job, job_id)
    if job:
        if db.get(Client, client_id):
            job.client_id = client_id
        job.name = name.strip()
        job.reference = reference.strip()
        job.notes = notes.strip()
        job.active = active == "on"
        audit.record(db, current_user(request), "job.edit", "job", job.id, f"Edited {job.name}")
        db.commit()
    return redirect("/jobs", "Job saved.")


# ============================================================ history
def _txn_markers(txns, tz_name):
    """Subset of transactions that have geo, in the shape the Leaflet renderer
    expects. Time formatted in the configured timezone for the popup."""
    out = []
    for t in txns:
        if t.lat is None or t.lng is None:
            continue
        out.append({
            "id": t.id,
            "lat": t.lat,
            "lng": t.lng,
            "accuracy": t.geo_accuracy_m,
            "order": t.order.number if t.order and t.order.number else "",
            "part": t.part.name if t.part else "",
            "qty": t.quantity,
            "charge": t.total_charge,
            "client": t.client.name if t.client else "",
            "job": t.job.name if t.job else "",
            "when": local_dt_filter(t.created_at, tz_name),
            "by": t.scanned_by or "",
        })
    return out


@app.get("/transactions", response_class=HTMLResponse)
def transactions_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    # Exclude lines that still belong to an open / cancelled cart — they
    # aren't real history. Legacy rows with order_id=NULL stay visible.
    q = (
        db.query(Transaction)
        .outerjoin(Order, Transaction.order_id == Order.id)
        .filter((Order.id.is_(None)) | (Order.status == "submitted"))
    )
    month = request.query_params.get("month", "")
    location_id_q = request.query_params.get("location_id", "")
    selected_loc = None
    if user.get("is_kiosk"):
        # Kiosk sessions only see the past 24h of kiosk-submitted charge-outs.
        # The month + location query strings are ignored.
        kiosk_username = store.get(db, "kiosk_username") or "kiosk"
        cutoff = datetime.utcnow() - timedelta(hours=24)
        q = q.filter(
            Transaction.created_at >= cutoff,
            Transaction.scanned_by == kiosk_username,
        )
        month = ""
        location_id_q = ""
    else:
        if month:
            try:
                year, mon = (int(x) for x in month.split("-"))
                start, end = reports.month_bounds(year, mon)
                q = q.filter(Transaction.created_at >= start, Transaction.created_at < end)
            except ValueError:
                pass
        if location_id_q:
            try:
                lid = int(location_id_q)
                q = q.filter(Transaction.location_id == lid)
                selected_loc = lid
            except ValueError:
                pass
    # selectinload prevents 500× per-row trips to fetch part / client / job /
    # location relationships from the template (transactions.html touches
    # all four). One query per relationship instead of one per row.
    txns = (q.options(
                selectinload(Transaction.part),
                selectinload(Transaction.client),
                selectinload(Transaction.job),
                selectinload(Transaction.location),
            )
            .order_by(Transaction.created_at.desc()).limit(500).all())
    cfg = store.all_settings(db)
    markers = _txn_markers(txns, cfg.get("timezone") or "UTC")
    filter_locs = (db.query(Location)
                   .filter(Location.archived == False)  # noqa: E712
                   .order_by(Location.name).all())
    return templates.TemplateResponse(
        "transactions.html",
        ctx(request, db, txns=txns, month=month, markers=markers,
            currency=cfg.get("currency", "$"),
            filter_locations=filter_locs,
            selected_location_id=selected_loc if selected_loc is not None else ""),
    )


@app.get("/map", response_class=HTMLResponse)
def map_page(request: Request, db: Session = Depends(get_db)):
    """Full-page map of every geo-tagged charge-out in the window.
    Honours ?month= or ?date_from=&date_to= (same shape as /report)."""
    qp = request.query_params
    start, end, label, month_str, date_from, date_to = _resolve_report_window(qp)
    q = (
        db.query(Transaction)
        .outerjoin(Order, Transaction.order_id == Order.id)
        .filter(
            Transaction.voided == False,  # noqa: E712
            Transaction.created_at >= start,
            Transaction.created_at < end,
            Transaction.lat.isnot(None),
            (Order.id.is_(None)) | (Order.status == "submitted"),
        )
        .order_by(Transaction.created_at.desc())
    )
    txns = q.all()
    cfg = store.all_settings(db)
    markers = _txn_markers(txns, cfg.get("timezone") or "UTC")
    return templates.TemplateResponse(
        "map.html",
        ctx(request, db, markers=markers, range_label=label, month=month_str,
            date_from=date_from, date_to=date_to, currency=cfg.get("currency", "$")),
    )


# ============================================================ audit
@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, db: Session = Depends(get_db)):
    q = db.query(AuditLog)
    action = request.query_params.get("action", "")
    user = request.query_params.get("user", "")
    month = request.query_params.get("month", "")
    if action:
        q = q.filter(AuditLog.action.like(f"{action}%"))
    if user:
        q = q.filter(AuditLog.user.like(f"%{user}%"))
    if month:
        try:
            year, mon = (int(x) for x in month.split("-"))
            start, end = reports.month_bounds(year, mon)
            q = q.filter(AuditLog.created_at >= start, AuditLog.created_at < end)
        except ValueError:
            pass
    entries = q.order_by(AuditLog.created_at.desc()).limit(500).all()
    actions = [r[0] for r in db.query(AuditLog.action).distinct().all()]
    return templates.TemplateResponse(
        "audit.html",
        ctx(request, db, entries=entries, actions=sorted(actions), f_action=action, f_user=user, f_month=month),
    )


# ============================================================ users & roles
@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.username).all()
    roles = db.query(Role).order_by(Role.is_admin.desc(), Role.name).all()
    return templates.TemplateResponse(
        "users.html", ctx(request, db, users=users, roles=roles, permissions=rbac.PERMISSIONS)
    )


@app.post("/users/{user_id}/save")
def users_save(
    user_id: int,
    request: Request,
    role_id: str = Form(""),
    active: str = Form(""),
    locked: str = Form(""),
    db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if u:
        u.role_id = int(role_id) if role_id else None
        u.active = active == "on"
        u.locked = locked == "on"
        audit.record(db, current_user(request), "user.edit", "user", u.id, f"Updated {u.username or u.email}")
        db.commit()
    return redirect("/users", "User saved.")


@app.post("/users/roles/add")
def roles_add(request: Request, name: str = Form(...), permissions: List[str] = Form([]), db: Session = Depends(get_db)):
    name = name.strip()
    if name and not db.query(Role).filter(Role.name == name).first():
        valid = [p for p in permissions if p in rbac.ALL_PERMS]
        db.add(Role(name=name, permissions=",".join(valid), is_admin=False, builtin=False))
        audit.record(db, current_user(request), "role.create", "role", None, f"Created role {name}")
        db.commit()
    else:
        return redirect("/users", "Role name missing or already exists.", ok=False)
    return redirect("/users", "Role created.")


@app.post("/users/roles/{role_id}/save")
def roles_save(role_id: int, request: Request, permissions: List[str] = Form([]), db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if role and not role.is_admin:  # Admin always keeps all permissions
        role.permissions = ",".join(p for p in permissions if p in rbac.ALL_PERMS)
        audit.record(db, current_user(request), "role.edit", "role", role.id, f"Edited role {role.name}")
        db.commit()
    return redirect("/users", "Role saved.")


@app.post("/users/roles/{role_id}/delete")
def roles_delete(role_id: int, request: Request, db: Session = Depends(get_db)):
    role = db.get(Role, role_id)
    if role and not role.builtin:
        default = db.query(Role).filter(Role.name == "Viewer").first()
        for u in db.query(User).filter(User.role_id == role.id).all():
            u.role_id = default.id if default else None
        audit.record(db, current_user(request), "role.delete", "role", role.id, f"Deleted role {role.name}")
        db.delete(role)
        db.commit()
    return redirect("/users", "Role deleted.")


# ============================================================ reports
def _parse_month(value: str):
    if value:
        try:
            year, mon = (int(x) for x in value.split("-"))
            return year, mon
        except ValueError:
            pass
    now = datetime.utcnow()
    return now.year, now.month


def _parse_date(value: str):
    """Parse an HTML <input type=date> value (YYYY-MM-DD) → datetime, or None."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _resolve_report_window(qp):
    """Return (start, end, label, month_str, date_from, date_to).

    Precedence: explicit ?date_from=&date_to= wins; falling back to ?month=YYYY-MM
    (default = current month). end is exclusive so reports include the full last day.
    """
    df = _parse_date(qp.get("date_from", ""))
    dt = _parse_date(qp.get("date_to", ""))
    if df and dt:
        if dt < df:
            df, dt = dt, df
        end = datetime(dt.year, dt.month, dt.day) + timedelta(days=1)
        return df, end, f"{df:%Y-%m-%d} → {dt:%Y-%m-%d}", "", qp.get("date_from", ""), qp.get("date_to", "")
    year, mon = _parse_month(qp.get("month", ""))
    start, end = reports.month_bounds(year, mon)
    return start, end, f"{year:04d}-{mon:02d}", f"{year:04d}-{mon:02d}", "", ""


def _selected_client_ids(qp):
    ids = qp.getlist("client_id") if hasattr(qp, "getlist") else [
        v for k, v in qp.multi_items() if k == "client_id"
    ]
    out = []
    for v in ids:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            pass
    return out


def _selected_location_id(qp):
    raw = qp.get("location_id", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@app.get("/report", response_class=HTMLResponse)
def report_page(request: Request, db: Session = Depends(get_db)):
    qp = request.query_params
    start, end, label, month_str, date_from, date_to = _resolve_report_window(qp)
    client_ids = _selected_client_ids(qp)
    loc_id = _selected_location_id(qp)
    report, totals = reports.build_report_range(db, start, end, client_ids=client_ids or None,
                                                 location_id=loc_id)
    all_clients = db.query(Client).filter(Client.active == True).order_by(Client.name).all()  # noqa: E712
    all_locations = (db.query(Location)
                     .filter(Location.archived == False)  # noqa: E712
                     .order_by(Location.name).all())
    return templates.TemplateResponse(
        "report.html",
        ctx(request, db, report=report, totals=totals,
            month=month_str, range_label=label,
            date_from=date_from, date_to=date_to,
            all_clients=all_clients, selected_client_ids=set(client_ids),
            all_locations=all_locations, selected_location_id=loc_id),
    )


@app.get("/report.csv")
def report_csv(request: Request, db: Session = Depends(get_db)):
    qp = request.query_params
    start, end, label, month_str, date_from, date_to = _resolve_report_window(qp)
    client_ids = _selected_client_ids(qp)
    loc_id = _selected_location_id(qp)
    report, totals = reports.build_report_range(db, start, end, client_ids=client_ids or None,
                                                 location_id=loc_id)
    csv_text = reports.report_csv_for(report, totals)
    if month_str:
        filename = f"charge-out-{month_str}.csv"
    else:
        filename = f"charge-out-{date_from}_to_{date_to}.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================ settings
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    kiosk_locs = (db.query(Location)
                  .filter(Location.active == True, Location.archived == False)  # noqa: E712
                  .order_by(Location.name).all())
    return templates.TemplateResponse(
        "settings.html",
        ctx(request, db, providers=emailer.PROVIDERS, this_month=datetime.utcnow().strftime("%Y-%m"),
            disable_auth=settings.disable_auth, size_groups=labels.grouped_sizes(),
            currencies=CURRENCIES, label_sizes=labels.LABEL_SIZES,
            timezones=TIMEZONES,
            roles=db.query(Role).order_by(Role.name).all(),
            kiosk_locations=kiosk_locs),
    )


@app.get("/settings/check-update")
def settings_check_update(request: Request, db: Session = Depends(get_db)):
    """Compare our running version against the latest GitHub release.
    Returns JSON: {current, latest, behind, url, error?}. Caches the
    response for 5 minutes so a few impatient clicks don't burn through
    the unauthenticated 60-req/hr GitHub rate limit. The app never
    applies updates itself — that has to happen on the host."""
    import json as _json
    import time as _time
    import urllib.request as _ur
    import urllib.error as _ue

    cache_raw = store.get(db, "_update_cache") or ""
    cached = None
    if cache_raw:
        try:
            cached = _json.loads(cache_raw)
        except Exception:
            cached = None
    now = int(_time.time())
    if cached and (now - int(cached.get("_at", 0))) < 300:
        out = {k: v for k, v in cached.items() if not k.startswith("_")}
        return JSONResponse(out)

    out = {"current": __version__, "latest": "", "behind": False, "url": ""}
    try:
        req = _ur.Request(
            "https://api.github.com/repos/stephenthecold/inv-keep/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "inv-keep-update-check"},
        )
        with _ur.urlopen(req, timeout=5) as r:
            data = _json.loads(r.read().decode("utf-8"))
        latest = (data.get("tag_name") or "").lstrip("v")
        out["latest"] = data.get("tag_name") or ""
        out["url"] = data.get("html_url") or ""
        # Lexicographic-on-tuples version compare; "1.20.0" beats "1.19.0".
        def _t(v):
            try:
                return tuple(int(x) for x in v.split("."))
            except Exception:
                return (0,)
        out["behind"] = _t(latest) > _t(__version__) if latest else False
    except _ue.HTTPError as e:
        out["error"] = f"HTTP {e.code}"
    except _ue.URLError as e:
        out["error"] = str(e.reason)
    except Exception as e:  # noqa: BLE001 - surface any other failure as a string
        out["error"] = str(e)

    cache_payload = dict(out)
    cache_payload["_at"] = now
    try:
        store.set(db, "_update_cache", _json.dumps(cache_payload))
        db.commit()
    except Exception:
        pass
    return JSONResponse(out)


@app.get("/settings/backup", name="settings_backup")
def settings_backup(request: Request, db: Session = Depends(get_db)):
    """Admin-only: stream a tar.gz of every *.db (consistent online-snapshot via
    sqlite3 .backup) plus the uploads/ folder. Audit-logged so backup pulls
    show up alongside other admin actions."""
    user = current_user(request)
    if not user.get("is_admin"):
        return JSONResponse({"detail": "Admin only"}, status_code=403)

    import io as _io
    import sqlite3 as _sqlite3
    import tarfile as _tarfile
    import tempfile as _tempfile

    # Resolve the data dir from the configured DATABASE_URL (sqlite:////code/data/app.db
    # under Docker; sqlite:///./data/app.db locally). Fallback: ./data.
    db_url = settings.database_url or ""
    if db_url.startswith("sqlite:////"):
        db_path = "/" + db_url[len("sqlite:////"):]
    elif db_url.startswith("sqlite:///"):
        db_path = db_url[len("sqlite:///"):]
    else:
        db_path = "data/app.db"
    data_dir = os.path.dirname(db_path) or "data"

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    fname = f"inv-keep-{ts}.tar.gz"

    with _tempfile.TemporaryDirectory() as workdir:
        # Snapshot every *.db in the data dir.
        snapped = []
        try:
            for entry in os.listdir(data_dir):
                if entry.endswith(".db"):
                    src = os.path.join(data_dir, entry)
                    dst = os.path.join(workdir, entry)
                    src_conn = _sqlite3.connect(src)
                    try:
                        dst_conn = _sqlite3.connect(dst)
                        try:
                            src_conn.backup(dst_conn)
                        finally:
                            dst_conn.close()
                    finally:
                        src_conn.close()
                    snapped.append(entry)
        except FileNotFoundError:
            return JSONResponse({"detail": f"Data dir not found at {data_dir}"}, status_code=500)

        info = (
            "inv-keep backup\n"
            f"created_at_utc: {datetime.utcnow().isoformat(timespec='seconds')}Z\n"
            f"app_version: {__version__}\n"
            f"databases: {', '.join(snapped) or '(none)'}\n"
        )
        with open(os.path.join(workdir, "BACKUP_INFO.txt"), "w", encoding="utf-8") as fh:
            fh.write(info)

        # Build the tarball in-memory and stream it as the response.
        buf = _io.BytesIO()
        with _tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for entry in os.listdir(workdir):
                tf.add(os.path.join(workdir, entry), arcname=entry)
            uploads_dir = os.path.join(data_dir, "uploads")
            if os.path.isdir(uploads_dir):
                tf.add(uploads_dir, arcname="uploads")
        body = buf.getvalue()

    audit.record(db, user, "settings.backup", "settings", None,
                 f"Downloaded backup ({len(body)} bytes, {len(snapped)} db file(s))")
    db.commit()
    return Response(
        content=body,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _restore_extract_dir(data_dir):
    """Where we move the live data/ aside before restoring (alongside data/
    so it's on the same volume — atomic mv)."""
    parent = os.path.dirname(data_dir.rstrip("/")) or "."
    base = os.path.basename(data_dir.rstrip("/")) or "data"
    return os.path.join(parent, f"{base}.before-restore-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}")


@app.post("/settings/restore")
async def settings_restore(request: Request, bundle: UploadFile = File(...), db: Session = Depends(get_db)):
    """Admin-only: extract an uploaded backup .tar.gz and copy its tables into
    the live DB via SQLite's online backup (in-place — no container restart).
    Existing uploads/ is replaced; existing DB rows are overwritten."""
    user = current_user(request)
    if not user.get("is_admin"):
        return JSONResponse({"detail": "Admin only"}, status_code=403)

    import io as _io
    import sqlite3 as _sqlite3
    import tarfile as _tarfile
    import tempfile as _tempfile
    import shutil as _shutil

    blob = await bundle.read()
    if not blob:
        return redirect("/settings", "Empty file upload — pick a backup .tar.gz first.", ok=False)
    if len(blob) > 200 * 1024 * 1024:
        return redirect("/settings", "Backup bundle is over 200 MB; restore via ./scripts/restore.sh on the host.", ok=False)

    # Resolve the data dir from DATABASE_URL (same logic as backup).
    db_url = settings.database_url or ""
    if db_url.startswith("sqlite:////"):
        db_path = "/" + db_url[len("sqlite:////"):]
    elif db_url.startswith("sqlite:///"):
        db_path = db_url[len("sqlite:///"):]
    else:
        db_path = "data/app.db"
    data_dir = os.path.dirname(db_path) or "data"
    live_db_name = os.path.basename(db_path)

    # Extract + validate the bundle in a tempdir.
    with _tempfile.TemporaryDirectory() as workdir:
        try:
            with _tarfile.open(fileobj=_io.BytesIO(blob), mode="r:gz") as tf:
                # Refuse anything that tries to escape workdir (zip-slip).
                for m in tf.getmembers():
                    target = os.path.normpath(os.path.join(workdir, m.name))
                    if not target.startswith(os.path.normpath(workdir) + os.sep) and target != os.path.normpath(workdir):
                        return redirect("/settings", f"Refusing path traversal in bundle: {m.name}", ok=False)
                tf.extractall(workdir)
        except _tarfile.TarError as e:
            return redirect("/settings", f"Not a valid backup tar.gz: {html.escape(str(e))}", ok=False)

        # Validate: must contain at least one .db
        db_files = [f for f in os.listdir(workdir) if f.endswith(".db")]
        if not db_files:
            return redirect("/settings", "Bundle has no .db files — refusing.", ok=False)

        # Sanity check: the bundle's live-db file (or any .db) should open.
        snap_live = os.path.join(workdir, live_db_name)
        if not os.path.exists(snap_live):
            # Fall back to the first .db in the bundle (e.g. if the user
            # backed up under a different DATABASE_URL and the names differ).
            snap_live = os.path.join(workdir, db_files[0])
        try:
            _sqlite3.connect(snap_live).close()
        except _sqlite3.DatabaseError as e:
            return redirect("/settings", f"Snapshot DB is corrupt: {html.escape(str(e))}", ok=False)

        # Take a safety copy of the current data/ before any destructive op.
        safe_dir = _restore_extract_dir(data_dir)
        try:
            _shutil.copytree(data_dir, safe_dir)
        except FileExistsError:
            pass  # vanishingly unlikely (timestamp collision in same second)

        # --- 1. Restore each DB via online backup (preserves connections) ---
        # The live engine holds connections — close them so SQLite releases its
        # locks, then use sqlite3.backup() to copy snapshot → live.
        engine.dispose()
        restored = []
        for fname in db_files:
            src = os.path.join(workdir, fname)
            dst = os.path.join(data_dir, fname)
            if not os.path.exists(dst):
                # New DB introduced by the bundle — just copy it in place.
                _shutil.copy2(src, dst)
            else:
                src_conn = _sqlite3.connect(src)
                try:
                    dst_conn = _sqlite3.connect(dst)
                    try:
                        src_conn.backup(dst_conn)
                    finally:
                        dst_conn.close()
                finally:
                    src_conn.close()
            restored.append(fname)

        # --- 2. Replace uploads/ contents ---
        # Two-pass mirror (merge in + sweep stale). Avoids rmtree() on the
        # live directory — Windows can hold an open handle on empty dirs and
        # fail with WinError 5; the live host (Linux container) is happy
        # either way.
        uploads_dst = os.path.join(data_dir, "uploads")
        uploads_src = os.path.join(workdir, "uploads")
        if os.path.isdir(uploads_src):
            os.makedirs(uploads_dst, exist_ok=True)
            _shutil.copytree(uploads_src, uploads_dst, dirs_exist_ok=True)
            # Sweep files in uploads_dst that aren't in uploads_src.
            for root, _dirs, files in os.walk(uploads_dst):
                rel = os.path.relpath(root, uploads_dst)
                for f in files:
                    if not os.path.exists(os.path.join(uploads_src, rel, f)):
                        try:
                            os.remove(os.path.join(root, f))
                        except OSError:
                            pass

    # Re-run migrations on the new DB (in case the bundle was from an older
    # version that's missing newer columns).
    ensure_columns()

    # Audit log the action — note: the audit row gets WRITTEN into the
    # *restored* DB, so it'll show whatever the user the bundle thinks did it.
    # Re-open a fresh session against the restored DB to log.
    fresh = SessionLocal()
    try:
        audit.record(fresh, user, "settings.restore", "settings", None,
                     f"Restored from upload ({len(blob)} bytes, {len(restored)} db file(s); "
                     f"safety copy at {safe_dir})")
        fresh.commit()
    finally:
        fresh.close()

    return HTMLResponse(
        "<html><body style='font-family:system-ui;max-width:640px;margin:4rem auto;color:#333'>"
        "<h2 style='color:#16a34a'>✓ Restore complete</h2>"
        f"<p>Restored <b>{len(restored)}</b> database file(s) and the uploads folder.</p>"
        f"<p>The previous data was saved on the server at "
        f"<code>{html.escape(os.path.basename(safe_dir))}/</code> "
        "(delete it once you've confirmed the restore looks right).</p>"
        "<p><a href='/'>Refresh the app →</a></p>"
        "</body></html>",
        status_code=200,
    )


@app.post("/settings/general")
def settings_general(
    request: Request,
    app_title: str = Form(...),
    currency: str = Form("$"),
    low_stock_threshold: int = Form(5),
    default_markup_pct: str = Form("0"),
    timezone: str = Form("UTC"),
    db: Session = Depends(get_db),
):
    user = current_user(request)
    # Validate timezone (silently fall back to UTC if unrecognized so a typo
    # doesn't lock the form).
    tz_name = (timezone or "UTC").strip()
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return redirect("/settings", f"Unknown timezone '{tz_name}'.", ok=False)
    # Markup % is admin-only — non-admins can't move it (silently ignored).
    if user.get("is_admin"):
        try:
            markup = float(default_markup_pct.strip() or "0")
        except ValueError:
            return redirect("/settings", "Markup % must be a number (e.g. 35 for 35%).", ok=False)
        if markup < 0 or markup > 1000:
            return redirect("/settings", "Markup % must be between 0 and 1000.", ok=False)
        store.set(db, "default_markup_pct", f"{markup:g}")
    store.set(db, "app_title", app_title.strip())
    store.set(db, "currency", currency.strip())
    store.set(db, "low_stock_threshold", low_stock_threshold)
    store.set(db, "timezone", tz_name)
    audit.record(db, user, "settings.general", "settings", None, "Updated general settings")
    db.commit()
    return redirect("/settings", "General settings saved.")


@app.post("/settings/printing")
def settings_printing(request: Request, label_size: str = Form("sheet"), label_barcode_type: str = Form("code128"), db: Session = Depends(get_db)):
    if label_size not in labels.LABEL_SIZES:
        label_size = "sheet"
    store.set(db, "label_size", label_size)
    store.set(db, "label_barcode_type", "qr" if label_barcode_type == "qr" else "code128")
    audit.record(db, current_user(request), "settings.printing", "settings", None, f"Label {label_size}/{label_barcode_type}")
    db.commit()
    return redirect("/settings", "Printing settings saved.")


@app.post("/settings/label-content")
def settings_label_content(
    request: Request,
    label_show_icon: str = Form(""),
    label_show_name: str = Form(""),
    label_show_code_text: str = Form(""),
    label_show_price: str = Form(""),
    label_show_description: str = Form(""),
    label_show_category: str = Form(""),
    label_company_text: str = Form(""),
    label_extra_text: str = Form(""),
    db: Session = Depends(get_db),
):
    for field, val in [
        ("label_show_icon", label_show_icon),
        ("label_show_name", label_show_name),
        ("label_show_code_text", label_show_code_text),
        ("label_show_price", label_show_price),
        ("label_show_description", label_show_description),
        ("label_show_category", label_show_category),
    ]:
        store.set(db, field, "1" if val == "on" else "0")
    store.set(db, "label_company_text", label_company_text.strip())
    store.set(db, "label_extra_text", label_extra_text.strip())
    audit.record(db, current_user(request), "settings.label_content", "settings", None, "Updated label content")
    db.commit()
    return redirect("/settings", "Label content saved.")


@app.post("/settings/android")
def settings_android(request: Request, android_asset_links: str = Form(""), db: Session = Depends(get_db)):
    store.set(db, "android_asset_links", android_asset_links.strip())
    audit.record(db, current_user(request), "settings.android", "settings", None, "Updated Android asset links")
    db.commit()
    return redirect("/settings", "Android settings saved.")


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")


@app.post("/settings/branding")
def settings_branding(
    request: Request,
    brand_accent: str = Form(""),
    brand_emoji: str = Form("📦"),
    brand_show_title: str = Form(""),
    brand_footer: str = Form(""),
    db: Session = Depends(get_db),
):
    accent = brand_accent.strip()
    if accent and not _HEX_COLOR.match(accent):
        return redirect("/settings", "Accent colour must be a hex like #2f81f7.", ok=False)
    store.set(db, "brand_accent", accent)
    store.set(db, "brand_emoji", brand_emoji.strip() or "📦")
    store.set(db, "brand_show_title", "1" if brand_show_title == "on" else "0")
    store.set(db, "brand_footer", brand_footer.strip())
    audit.record(db, current_user(request), "settings.branding", "settings", None, "Updated branding")
    db.commit()
    return redirect("/settings", "Branding saved.")


@app.post("/settings/branding/logo")
async def settings_branding_logo(request: Request, logo: UploadFile = File(...), db: Session = Depends(get_db)):
    # SVG intentionally excluded: it executes script when fetched directly, which
    # would be served from /uploads/ in this app's own origin (stored XSS).
    allowed = {"image/png": ".png", "image/jpeg": ".jpg",
               "image/webp": ".webp", "image/gif": ".gif", "image/x-icon": ".ico"}
    ext = allowed.get(logo.content_type)
    if not ext:
        return redirect("/settings", "Unsupported image type (use PNG, JPG, WEBP, GIF or ICO).", ok=False)
    data = await logo.read()
    if len(data) > 2 * 1024 * 1024:
        return redirect("/settings", "Logo too large (max 2 MB).", ok=False)
    # Stable filename so the old one is overwritten; cache-bust via query string.
    fname = f"logo{ext}"
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as fh:
        fh.write(data)
    store.set(db, "brand_logo", f"/uploads/{fname}?v={secrets.token_hex(4)}")
    audit.record(db, current_user(request), "settings.branding_logo", "settings", None, "Uploaded brand logo")
    db.commit()
    return redirect("/settings", "Logo uploaded.")


@app.post("/settings/branding/logo/remove")
def settings_branding_logo_remove(request: Request, db: Session = Depends(get_db)):
    store.set(db, "brand_logo", "")
    audit.record(db, current_user(request), "settings.branding_logo", "settings", None, "Removed brand logo")
    db.commit()
    return redirect("/settings", "Logo removed.")


@app.post("/settings/branding/favicon")
async def settings_branding_favicon(request: Request, favicon: UploadFile = File(...), db: Session = Depends(get_db)):
    # Mirrors the logo upload's allowlist — SVG deliberately excluded to keep
    # /uploads/ free of script-executing assets served from this origin.
    allowed = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
               "image/gif": ".gif", "image/x-icon": ".ico",
               "image/vnd.microsoft.icon": ".ico"}
    ext = allowed.get(favicon.content_type)
    if not ext:
        return redirect("/settings", "Unsupported favicon format (use PNG, JPG, WEBP, GIF or ICO).", ok=False)
    data = await favicon.read()
    if len(data) > 512 * 1024:
        return redirect("/settings", "Favicon too large (max 512 KB).", ok=False)
    fname = f"favicon{ext}"
    with open(os.path.join(UPLOAD_DIR, fname), "wb") as fh:
        fh.write(data)
    store.set(db, "brand_favicon", f"/uploads/{fname}?v={secrets.token_hex(4)}")
    audit.record(db, current_user(request), "settings.branding_favicon", "settings", None, "Uploaded favicon")
    db.commit()
    return redirect("/settings", "Favicon uploaded.")


@app.post("/settings/branding/favicon/remove")
def settings_branding_favicon_remove(request: Request, db: Session = Depends(get_db)):
    store.set(db, "brand_favicon", "")
    audit.record(db, current_user(request), "settings.branding_favicon", "settings", None, "Removed favicon")
    db.commit()
    return redirect("/settings", "Favicon removed.")


@app.post("/settings/auth")
def settings_auth(
    request: Request,
    auth_mode: str = Form("none"),
    oidc_discovery_url: str = Form(""),
    oidc_client_id: str = Form(""),
    oidc_client_secret: str = Form(""),
    oidc_redirect_url: str = Form(""),
    forward_auth_user_header: str = Form(""),
    forward_auth_email_header: str = Form(""),
    forward_auth_groups_header: str = Form(""),
    oidc_groups_claim: str = Form("groups"),
    oidc_group_role_map: str = Form(""),
    rbac_default_role: str = Form("Admin"),
    rbac_admin_emails: str = Form(""),
    rbac_auto_create: str = Form(""),
    db: Session = Depends(get_db),
):
    if auth_mode not in ("none", "oidc", "forward"):
        auth_mode = "none"
    store.set(db, "auth_mode", auth_mode)
    store.set(db, "oidc_discovery_url", oidc_discovery_url.strip())
    store.set(db, "oidc_client_id", oidc_client_id.strip())
    store.set(db, "oidc_redirect_url", oidc_redirect_url.strip())
    store.set(db, "forward_auth_user_header", forward_auth_user_header.strip() or "x-authentik-username")
    store.set(db, "forward_auth_email_header", forward_auth_email_header.strip() or "x-authentik-email")
    store.set(db, "forward_auth_groups_header", forward_auth_groups_header.strip() or "x-authentik-groups")
    store.set(db, "oidc_groups_claim", oidc_groups_claim.strip() or "groups")
    store.set(db, "oidc_group_role_map", oidc_group_role_map.strip())
    store.set(db, "rbac_default_role", rbac_default_role.strip() or "Admin")
    store.set(db, "rbac_admin_emails", rbac_admin_emails.strip())
    store.set(db, "rbac_auto_create", "1" if rbac_auto_create == "on" else "0")
    if oidc_client_secret:
        store.set(db, "oidc_client_secret", oidc_client_secret)
    audit.record(db, current_user(request), "settings.auth", "settings", None, f"Auth mode set to {auth_mode}")
    db.commit()
    note = "Authentication settings saved."
    if auth_mode == "oidc":
        note += " Log out and back in to test it (break-glass: set DISABLE_AUTH=1 if locked out)."
    return redirect("/settings", note)


@app.post("/settings/kiosk")
def settings_kiosk(
    request: Request,
    kiosk_enabled: str = Form(""),
    kiosk_pin: str = Form(""),
    kiosk_username: str = Form("kiosk"),
    kiosk_lockout_minutes: str = Form("5"),
    kiosk_location_id: str = Form(""),
    db: Session = Depends(get_db),
):
    """Admin-only kiosk PIN settings. Enabling without a PIN is rejected so
    the welcome page never shows a form that nothing can answer."""
    user = current_user(request)
    if not user.get("is_admin"):
        return JSONResponse({"detail": "Admin only"}, status_code=403)
    enabled = "1" if kiosk_enabled == "on" else "0"
    pin = (kiosk_pin or "").strip()
    if pin:
        if not pin.isdigit() or len(pin) < 4 or len(pin) > 12:
            return redirect("/settings", "Kiosk PIN must be 4–12 digits.", ok=False)
        store.set(db, "kiosk_pin", pin)
    if enabled == "1" and not (pin or store.get(db, "kiosk_pin")):
        return redirect("/settings", "Set a PIN before enabling kiosk mode.", ok=False)
    store.set(db, "kiosk_enabled", enabled)
    uname = (kiosk_username or "kiosk").strip() or "kiosk"
    store.set(db, "kiosk_username", uname)
    try:
        mins = max(1, min(1440, int(kiosk_lockout_minutes or "5")))
    except ValueError:
        mins = 5
    store.set(db, "kiosk_lockout_minutes", str(mins))
    # Default kiosk source location: validate it's a real, active location.
    raw_loc = (kiosk_location_id or "").strip()
    if raw_loc:
        try:
            lid = int(raw_loc)
        except ValueError:
            lid = None
        if lid is None:
            store.set(db, "kiosk_location_id", "")
        else:
            loc = db.get(Location, lid)
            if not loc or loc.archived or not loc.active:
                return redirect("/settings", "Pick an active location for the kiosk default.", ok=False)
            store.set(db, "kiosk_location_id", str(lid))
    else:
        store.set(db, "kiosk_location_id", "")
    audit.record(db, user, "settings.kiosk", "settings", None,
                 f"Kiosk mode {'enabled' if enabled == '1' else 'disabled'}")
    db.commit()
    return redirect("/settings", "Kiosk settings saved.")


@app.post("/settings/email")
def settings_email(
    request: Request,
    email_method: str = Form("none"),
    email_from: str = Form(""),
    email_from_name: str = Form(""),
    smtp_host: str = Form(""),
    smtp_port: str = Form("587"),
    smtp_username: str = Form(""),
    smtp_password: str = Form(""),
    smtp_use_tls: str = Form(""),
    oauth_client_id: str = Form(""),
    oauth_client_secret: str = Form(""),
    oauth_tenant: str = Form("common"),
    db: Session = Depends(get_db),
):
    store.set(db, "email_method", email_method)
    store.set(db, "email_from", email_from.strip())
    store.set(db, "email_from_name", email_from_name.strip())
    store.set(db, "smtp_host", smtp_host.strip())
    store.set(db, "smtp_port", smtp_port.strip() or "587")
    store.set(db, "smtp_username", smtp_username.strip())
    store.set(db, "smtp_use_tls", "1" if smtp_use_tls == "on" else "0")
    store.set(db, "oauth_client_id", oauth_client_id.strip())
    store.set(db, "oauth_tenant", oauth_tenant.strip() or "common")
    if smtp_password:
        store.set(db, "smtp_password", smtp_password)
    if oauth_client_secret:
        store.set(db, "oauth_client_secret", oauth_client_secret)
    audit.record(db, current_user(request), "settings.email", "settings", None, f"Email method set to {email_method}")
    db.commit()
    return redirect("/settings", "Email settings saved.")


@app.post("/settings/email/test")
def settings_email_test(request: Request, test_to: str = Form(...), db: Session = Depends(get_db)):
    ok, message = emailer.send(
        db, test_to, "Inv-Keep test email",
        "<p>This is a test email from your Inv-Keep app. If you got this, email works. 🎉</p>",
    )
    return redirect("/settings", message, ok=ok)


@app.get("/settings/email/oauth/connect")
def email_oauth_connect(request: Request, db: Session = Depends(get_db)):
    method = store.get(db, "email_method")
    if method not in emailer.PROVIDERS:
        return redirect("/settings", "Pick an OAuth email method and save first.", ok=False)
    state = secrets.token_urlsafe(16)
    request.session["email_oauth_state"] = state
    request.session["email_oauth_method"] = method
    redirect_uri = str(request.url_for("email_oauth_callback"))
    url = emailer.authorize_url(db, method, redirect_uri, state)
    return RedirectResponse(url)


@app.get("/settings/email/oauth/callback", name="email_oauth_callback")
def email_oauth_callback(request: Request, db: Session = Depends(get_db)):
    if request.query_params.get("state") != request.session.get("email_oauth_state"):
        return redirect("/settings", "OAuth state mismatch — try again.", ok=False)
    method = request.session.get("email_oauth_method")
    code = request.query_params.get("code")
    if not code or method not in emailer.PROVIDERS:
        return redirect("/settings", "OAuth failed (no code).", ok=False)
    redirect_uri = str(request.url_for("email_oauth_callback"))
    try:
        emailer.exchange_code(db, method, code, redirect_uri)
        audit.record(db, current_user(request), "settings.email_oauth", "settings", None, f"Connected {method}")
        db.commit()
    except Exception as e:  # noqa: BLE001
        return redirect("/settings", f"OAuth token exchange failed: {e}", ok=False)
    return redirect("/settings", "Mailbox connected via OAuth.")


@app.post("/settings/alerts")
def settings_alerts(
    request: Request,
    alert_low_stock_enabled: str = Form(""),
    alert_low_stock_recipients: str = Form(""),
    alert_monthly_enabled: str = Form(""),
    alert_monthly_mode: str = Form("day"),
    alert_monthly_day: int = Form(1),
    alert_monthly_nth: int = Form(1),
    alert_monthly_weekday: int = Form(0),
    alert_monthly_hour: int = Form(6),
    alert_monthly_recipients: str = Form(""),
    alert_weekly_enabled: str = Form(""),
    alert_weekly_weekday: int = Form(0),
    alert_weekly_hour: int = Form(6),
    alert_weekly_recipients: str = Form(""),
    alert_daily_enabled: str = Form(""),
    alert_daily_hour: int = Form(6),
    alert_daily_recipients: str = Form(""),
    db: Session = Depends(get_db),
):
    def hr(v):
        return max(0, min(23, v))

    store.set(db, "alert_low_stock_enabled", "1" if alert_low_stock_enabled == "on" else "0")
    store.set(db, "alert_low_stock_recipients", alert_low_stock_recipients.strip())
    store.set(db, "alert_monthly_enabled", "1" if alert_monthly_enabled == "on" else "0")
    store.set(db, "alert_monthly_mode", "weekday" if alert_monthly_mode == "weekday" else "day")
    store.set(db, "alert_monthly_day", max(1, min(28, alert_monthly_day)))
    store.set(db, "alert_monthly_nth", alert_monthly_nth if alert_monthly_nth in (1, 2, 3, 4, -1) else 1)
    store.set(db, "alert_monthly_weekday", max(0, min(6, alert_monthly_weekday)))
    store.set(db, "alert_monthly_hour", hr(alert_monthly_hour))
    store.set(db, "alert_monthly_recipients", alert_monthly_recipients.strip())
    store.set(db, "alert_weekly_enabled", "1" if alert_weekly_enabled == "on" else "0")
    store.set(db, "alert_weekly_weekday", max(0, min(6, alert_weekly_weekday)))
    store.set(db, "alert_weekly_hour", hr(alert_weekly_hour))
    store.set(db, "alert_weekly_recipients", alert_weekly_recipients.strip())
    store.set(db, "alert_daily_enabled", "1" if alert_daily_enabled == "on" else "0")
    store.set(db, "alert_daily_hour", hr(alert_daily_hour))
    store.set(db, "alert_daily_recipients", alert_daily_recipients.strip())
    audit.record(db, current_user(request), "settings.alerts", "settings", None, "Updated alert settings")
    db.commit()
    return redirect("/settings", "Alert settings saved.")


@app.post("/settings/alerts/send-monthly")
def settings_send_monthly(request: Request, month: str = Form(""), to: str = Form(""), db: Session = Depends(get_db)):
    year, mon = _parse_month(month)
    recipients = to.strip() or store.get(db, "alert_monthly_recipients")
    if not recipients:
        return redirect("/settings", "No recipients for the monthly report.", ok=False)
    html = emailer.build_monthly_html(db, year, mon)
    ok, message = emailer.send(db, recipients, f"Monthly charge-out report — {year:04d}-{mon:02d}", html)
    return redirect("/settings", message, ok=ok)

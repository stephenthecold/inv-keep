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
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
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
from .database import Base, SessionLocal, engine, ensure_columns, get_db
from .models import AuditLog, Category, Client, Job, Order, Part, Role, Transaction, User
from .version import __version__

Base.metadata.create_all(bind=engine)
ensure_columns()

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

PUBLIC_PATHS = {"/login", "/auth/callback", "/logout", "/health", "/manifest.webmanifest",
                "/sw.js", "/.well-known/assetlinks.json"}

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
            return RedirectResponse("/login")
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    request.state.user = user

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
    return await call_next(request)


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
    }
    u = base["user"]
    base["can"] = lambda p: bool(u.get("is_admin")) or p in u.get("perms", set())
    base["msg"] = request.query_params.get("msg", "")
    base["ok"] = request.query_params.get("ok", "1") != "0"
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
    return RedirectResponse("/", status_code=303)


# ============================================================ scan page
@app.get("/", response_class=HTMLResponse)
def scan_page(request: Request, db: Session = Depends(get_db)):
    clients = db.query(Client).filter(Client.active == True).order_by(Client.name).all()  # noqa: E712
    jobs = db.query(Job).filter(Job.active == True).order_by(Job.name).all()  # noqa: E712
    recent = db.query(Transaction).order_by(Transaction.created_at.desc()).limit(15).all()
    return templates.TemplateResponse("scan.html", ctx(request, db, clients=clients, jobs=jobs, recent=recent))


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
        "job_id": cart.job_id,
        "job_name": cart.job.name if cart.job else "",
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
    if part.quantity_on_hand < qty:
        return {"ok": False, "error": "insufficient_stock",
                "available": part.quantity_on_hand, "part": part.name}

    cart = orders.open_cart_for(db, user.get("username", ""))
    fresh = False
    if cart is None:
        cart = Order(status="open", created_by=user.get("username", ""))
        db.add(cart)
        db.flush()
        fresh = True
        audit.record(db, user, "order.open", "order", cart.id, f"Opened cart #{cart.id}")

    part.quantity_on_hand -= qty
    lat, lng, acc = _sanitize_geo(payload)
    txn = Transaction(
        order_id=cart.id,
        part_id=part.id,
        customer_id=cart.customer_id,  # null until /api/cart/set; backfilled on client pick
        job_id=cart.job_id,
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
    # Backfill the new client/job onto open transactions so submitted lines
    # carry the right customer/job at report time.
    if cart.customer_id:
        db.query(Transaction).filter(
            Transaction.order_id == cart.id,
            Transaction.voided == False,  # noqa: E712
        ).update({"customer_id": cart.customer_id, "job_id": cart.job_id})
    db.commit()
    return {"ok": True, "cart": _cart_payload(db, cart)}


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


@app.post("/api/void/{txn_id}")
def api_void(txn_id: int, request: Request, db: Session = Depends(get_db)):
    txn = db.get(Transaction, txn_id)
    if not txn or txn.voided:
        return {"ok": False}
    txn.voided = True
    part = db.get(Part, txn.part_id)
    if part:
        part.quantity_on_hand += txn.quantity
    audit.record(
        db, current_user(request), "sale.void", "transaction", txn.id,
        f"Voided {txn.quantity} × {part.name if part else '?'}",
    )
    db.commit()
    return {"ok": True}


# ============================================================ parts
@app.get("/parts", response_class=HTMLResponse)
def parts_page(request: Request, db: Session = Depends(get_db)):
    show_archived = request.query_params.get("archived") == "1"
    q = db.query(Part)
    if not show_archived:
        q = q.filter(Part.archived == False)  # noqa: E712
    parts = q.order_by(Part.name).all()
    cats = category_choices(db)
    cat_names = {cid: category_path(db, c) for cid, _label, _d, c in cats}
    return templates.TemplateResponse(
        "parts.html",
        ctx(request, db, parts=parts, categories=cats, cat_names=cat_names,
            show_archived=show_archived,
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
def parts_restock(part_id: int, request: Request, amount: int = Form(...), db: Session = Depends(get_db)):
    part = db.get(Part, part_id)
    if part:
        part.quantity_on_hand += amount
        if part.low_stock_alerted:
            part.low_stock_alerted = False
        audit.record(db, current_user(request), "part.restock", "part", part.id, f"+{amount} → {part.quantity_on_hand}")
        db.commit()
    return redirect("/parts", "Stock updated.")


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
    return templates.TemplateResponse("categories.html", ctx(request, db, tree=category_choices(db)))


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
    clients = db.query(Client).order_by(Client.name).all()
    return templates.TemplateResponse("clients.html", ctx(request, db, clients=clients))


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
    jobs = db.query(Job).join(Client, Job.client_id == Client.id).order_by(Client.name, Job.name).all()
    clients = db.query(Client).filter(Client.active == True).order_by(Client.name).all()  # noqa: E712
    return templates.TemplateResponse("jobs.html", ctx(request, db, jobs=jobs, clients=clients))


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
    # Exclude lines that still belong to an open / cancelled cart — they
    # aren't real history. Legacy rows with order_id=NULL stay visible.
    q = (
        db.query(Transaction)
        .outerjoin(Order, Transaction.order_id == Order.id)
        .filter((Order.id.is_(None)) | (Order.status == "submitted"))
    )
    month = request.query_params.get("month", "")
    if month:
        try:
            year, mon = (int(x) for x in month.split("-"))
            start, end = reports.month_bounds(year, mon)
            q = q.filter(Transaction.created_at >= start, Transaction.created_at < end)
        except ValueError:
            pass
    txns = q.order_by(Transaction.created_at.desc()).limit(500).all()
    cfg = store.all_settings(db)
    markers = _txn_markers(txns, cfg.get("timezone") or "UTC")
    return templates.TemplateResponse(
        "transactions.html",
        ctx(request, db, txns=txns, month=month, markers=markers, currency=cfg.get("currency", "$")),
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


@app.get("/report", response_class=HTMLResponse)
def report_page(request: Request, db: Session = Depends(get_db)):
    qp = request.query_params
    start, end, label, month_str, date_from, date_to = _resolve_report_window(qp)
    client_ids = _selected_client_ids(qp)
    report, totals = reports.build_report_range(db, start, end, client_ids=client_ids or None)
    all_clients = db.query(Client).filter(Client.active == True).order_by(Client.name).all()  # noqa: E712
    return templates.TemplateResponse(
        "report.html",
        ctx(request, db, report=report, totals=totals,
            month=month_str, range_label=label,
            date_from=date_from, date_to=date_to,
            all_clients=all_clients, selected_client_ids=set(client_ids)),
    )


@app.get("/report.csv")
def report_csv(request: Request, db: Session = Depends(get_db)):
    qp = request.query_params
    start, end, label, month_str, date_from, date_to = _resolve_report_window(qp)
    client_ids = _selected_client_ids(qp)
    report, totals = reports.build_report_range(db, start, end, client_ids=client_ids or None)
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
    return templates.TemplateResponse(
        "settings.html",
        ctx(request, db, providers=emailer.PROVIDERS, this_month=datetime.utcnow().strftime("%Y-%m"),
            disable_auth=settings.disable_auth, size_groups=labels.grouped_sizes(),
            currencies=CURRENCIES, label_sizes=labels.LABEL_SIZES,
            timezones=TIMEZONES,
            roles=db.query(Role).order_by(Role.name).all()),
    )


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

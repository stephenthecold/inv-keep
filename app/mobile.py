"""Mobile / Android-companion REST API.

Self-contained router mounted at ``/mobile``. Bearer-token auth instead of
the session cookie + CSRF dance the web UI uses, because the Android app
hits the API from a native client (no cookies, no DOM, no token-in-form).

Tokens are opaque random strings stored in the ``mobile_sessions`` table —
12-hour lifetime, revocable by deleting the row. A "tech" is a ``KioskPin``
row: each PIN is a station/identity with a default location + audit
username, which is exactly what a field technician needs (the web UI's
existing PIN-login flow already treats it that way).

Routes live OUTSIDE the cookie auth middleware and outside CSRF — see the
``/mobile`` bypass in ``main.py:auth_middleware`` and ``csrf.EXEMPT_PREFIXES``.
"""

import glob
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import audit
from . import orders as orders_mod
from . import settings_store as store
from . import throttle
from .database import get_db
from .models import (
    Category, Client, Job, KioskPin, Location, MobileSession, Order, Part,
    Receipt, Transaction,
)
from .util import finite as _finite


router = APIRouter(prefix="/mobile", tags=["mobile"])


TOKEN_LIFETIME = timedelta(hours=12)

# Receipts live under the existing /uploads mount so the web UI back-office
# (cookie-authed) can view them when reviewing a custom-line order.
RECEIPTS_DIR = os.path.join("data", "uploads", "receipts")
os.makedirs(RECEIPTS_DIR, exist_ok=True)
_RECEIPT_EXT = {"image/jpeg": ".jpg", "image/png": ".png"}
_MAX_RECEIPT_BYTES = 5 * 1024 * 1024  # 5 MB per the mobile spec

# Per-item catalog icons (mobile app). SVG is allowed here — unlike the web
# favicon/logo uploads — but ONLY because the GET route below serves them with
# a sandbox CSP + nosniff and the app references them as <img>, so an embedded
# script can never execute (no stored-XSS). Never inline these into HTML.
ITEM_ICON_DIR = os.path.join("data", "uploads", "item-icons")
os.makedirs(ITEM_ICON_DIR, exist_ok=True)
_ICON_EXT = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg"}
_MAX_ICON_BYTES = 256 * 1024  # ~256 KB per the spec
# Headers that neutralise a hostile SVG: sandbox blocks scripts even on direct
# navigation, nosniff pins the declared type. Long immutable cache (?v= busts it).
_ICON_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "public, max-age=2592000, immutable",
}
_ICON_MEDIA = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg"}

# ---- helpers ---------------------------------------------------------------


def _abs_url(request: Request, path: str) -> str:
    """Absolute URL for a served path, honouring the proxy's forwarded scheme/host
    (uvicorn runs with --proxy-headers) so links are https behind a TLS proxy."""
    return urljoin(str(request.base_url), path.lstrip("/"))


_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _hex_color_or_none(s: Optional[str]) -> Optional[str]:
    s = (s or "").strip()
    return s if _HEX_RE.match(s) else None


def _resolve_or_create_category(db: Session, name: Optional[str]) -> Optional[int]:
    """Map a category name to its id, creating a top-level category if it
    doesn't exist (case-insensitive). Blank name → uncategorised (None)."""
    nm = (name or "").strip()
    if not nm:
        return None
    existing = (db.query(Category)
                .filter(func.lower(Category.name) == nm.lower())
                .first())
    if existing is not None:
        return existing.id
    cat = Category(name=nm[:100])
    db.add(cat)
    db.flush()
    return cat.id

def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Format a naive-UTC or aware datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string to a naive-UTC datetime (matching how the rest
    of the app stores datetimes — UTC, no tzinfo). Returns None on garbage."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _tech_username(pin: KioskPin) -> str:
    """Stable identifier we record as ``Order.created_by`` and
    ``Transaction.scanned_by``. Falls back to ``tech-<id>`` so two PINs
    that left their kiosk_username at the default don't collide on
    ``recent_orders`` lookups (each PIN gets its own id-suffixed username
    only when the admin hasn't set one)."""
    name = (pin.kiosk_username or "").strip()
    if name and name != "kiosk":
        return name
    return f"tech-{pin.id}"


def _tech_display_name(pin: KioskPin) -> str:
    return (pin.label or "").strip() or (pin.kiosk_username or "").strip() or f"Tech {pin.id}"


def get_current_tech(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> KioskPin:
    """FastAPI dependency: validate the ``Authorization: Bearer …`` header
    against the mobile_sessions table and return the underlying KioskPin
    row. Raises 401 on missing / invalid / expired token, or if the
    backing PIN has been deactivated."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    session = db.query(MobileSession).filter(MobileSession.token == token).first()
    if session is None:
        raise HTTPException(status_code=401, detail="invalid_token")
    if session.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=401, detail="token_expired")
    pin = db.get(KioskPin, session.kiosk_pin_id)
    if pin is None or not pin.active:
        raise HTTPException(status_code=401, detail="tech_disabled")
    return pin


def get_inventory_admin(tech: KioskPin = Depends(get_current_tech)) -> KioskPin:
    """Like get_current_tech, but 403s unless the tech's PIN is flagged
    is_inventory_admin in the web admin UI. Gates the item create/edit/stock
    endpoints."""
    if not getattr(tech, "is_inventory_admin", False):
        raise HTTPException(status_code=403, detail="inventory_admin_required")
    return tech


# ---- 1. POST /mobile/auth/token --------------------------------------------

class AuthTokenIn(BaseModel):
    pin: Optional[str] = None
    badge_uid: Optional[str] = None


class TechOut(BaseModel):
    id: int
    name: str
    default_location_id: Optional[int] = None
    is_inventory_admin: bool = False


class AuthTokenOut(BaseModel):
    token: str
    expires_at: str
    tech: TechOut


@router.post("/auth/token", response_model=AuthTokenOut)
def auth_token(payload: AuthTokenIn, request: Request, db: Session = Depends(get_db)):
    pin_val = (payload.pin or "").strip()
    badge_val = (payload.badge_uid or "").strip()
    if not pin_val and not badge_val:
        raise HTTPException(status_code=401, detail="missing_credentials")

    # Brute-force throttle (shared with the web kiosk login). Without this the
    # mobile endpoint — outside the cookie-auth middleware and CSRF — let a
    # short PIN be guessed unboundedly.
    ip = throttle.client_ip(request)
    wait = throttle.retry_after(ip)
    if wait:
        raise HTTPException(status_code=429, detail="too_many_attempts",
                            headers={"Retry-After": str(wait)})

    matched: Optional[KioskPin] = None
    if pin_val:
        # Constant-time compare against every active PIN — mirrors the
        # web /kiosk/login flow so a per-row timing leak can't reveal
        # which slot the entered PIN matches.
        for row in db.query(KioskPin).filter(KioskPin.active == True).all():  # noqa: E712
            if hmac.compare_digest(pin_val, (row.pin or "").strip()):
                matched = row
    else:
        matched = (db.query(KioskPin)
                   .filter(KioskPin.active == True,  # noqa: E712
                           KioskPin.badge_uid == badge_val)
                   .first())

    if matched is None:
        lockout_min = store.get_int(db, "kiosk_lockout_minutes", 5) or 5
        throttle.record_failure(ip, lockout_min * 60)
        raise HTTPException(status_code=401, detail="invalid_credentials")
    throttle.clear(ip)

    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + TOKEN_LIFETIME
    db.add(MobileSession(token=token, kiosk_pin_id=matched.id, expires_at=expires_at))
    audit.record(db, {"username": _tech_username(matched)},
                 "mobile.login", "kiosk", matched.id,
                 f"Mobile token issued ({'PIN' if pin_val else 'badge'})")
    db.commit()
    return AuthTokenOut(
        token=token,
        expires_at=_iso_utc(expires_at),
        tech=TechOut(
            id=matched.id,
            name=_tech_display_name(matched),
            default_location_id=matched.location_id,
            is_inventory_admin=bool(matched.is_inventory_admin),
        ),
    )


# ---- 2. items: by-barcode / lookup / search --------------------------------

class ItemOut(BaseModel):
    id: int
    sku: str
    name: str
    category: str
    in_stock_at_location: int
    default_price_cents: int
    # Absolute URL to the item's custom icon (SVG/PNG), or null to fall back to
    # a generic icon. Served hardened by GET /mobile/items/<id>/icon.
    icon_url: Optional[str] = None


def _item_dto(db: Session, tech: KioskPin, part: Part, request: Request) -> ItemOut:
    """Render a Part as the wire shape. ``in_stock_at_location`` is the
    quantity at the tech's default location (or the part's aggregate
    quantity_on_hand when the tech has no default location pinned)."""
    loc_id = tech.location_id
    if loc_id:
        qty = orders_mod.stock_at(db, part.id, loc_id)
    else:
        qty = int(part.quantity_on_hand or 0)
    icon_url = _abs_url(request, part.icon_image) if (part.icon_image or "") else None
    return ItemOut(
        id=part.id,
        sku=part.barcode,
        name=part.name,
        category=(part.category.name if part.category else ""),
        in_stock_at_location=qty,
        default_price_cents=int(round(float(part.unit_price or 0) * 100)),
        icon_url=icon_url,
    )


@router.get("/items/by-barcode/{code}", response_model=ItemOut)
def item_by_barcode(
    code: str,
    request: Request,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Strict barcode-scan lookup. inv-keep stores the SKU as ``Part.barcode``
    (no separate sku column), so the spec's "fall through sku as a fallback"
    is the same column — we try exact, then case-insensitive exact, then
    404. The /items/lookup endpoint is the right place for fuzzy matching."""
    base = db.query(Part).filter(Part.active == True,  # noqa: E712
                                  Part.archived == False)  # noqa: E712
    part = base.filter(Part.barcode == code).first()
    if part is None:
        part = base.filter(func.lower(Part.barcode) == code.lower()).first()
    if part is None:
        raise HTTPException(status_code=404, detail="item_not_found")
    return _item_dto(db, tech, part, request)


class ItemsLookupOut(BaseModel):
    exact: Optional[ItemOut] = None
    candidates: List[ItemOut] = []


@router.get("/items/lookup", response_model=ItemsLookupOut)
def items_lookup(
    request: Request,
    q: str = "",
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Fuzzy lookup used by the scan path when the camera/HID read isn't
    a guaranteed catalog hit. Tries (in order): exact SKU/barcode match
    (case-sensitive, then case-insensitive), then a name prefix match,
    then a contains match. A single hit is returned as ``exact``;
    multiple → ``candidates``."""
    qv = (q or "").strip()
    if not qv:
        return ItemsLookupOut(exact=None, candidates=[])

    base = db.query(Part).filter(Part.active == True,  # noqa: E712
                                  Part.archived == False)  # noqa: E712

    # 1. Exact SKU/barcode (case-sensitive, then -insensitive).
    exact = base.filter(Part.barcode == qv).first()
    if exact is None:
        exact = base.filter(func.lower(Part.barcode) == qv.lower()).first()
    if exact is not None:
        return ItemsLookupOut(exact=_item_dto(db, tech, exact, request), candidates=[])

    # 2. Prefix match on name / barcode.
    pfx = f"{qv}%"
    rows = (base.filter(or_(Part.name.ilike(pfx), Part.barcode.ilike(pfx)))
            .order_by(Part.name).limit(10).all())

    # 3. Fall through to contains if prefix found nothing.
    if not rows:
        cnt = f"%{qv}%"
        rows = (base.filter(or_(Part.name.ilike(cnt), Part.barcode.ilike(cnt)))
                .order_by(Part.name).limit(10).all())

    if len(rows) == 1:
        return ItemsLookupOut(exact=_item_dto(db, tech, rows[0], request), candidates=[])
    return ItemsLookupOut(
        exact=None,
        candidates=[_item_dto(db, tech, r, request) for r in rows],
    )


class ItemsSearchOut(BaseModel):
    items: List[ItemOut]
    total: int
    has_more: bool


@router.get("/items/search", response_model=ItemsSearchOut)
def items_search(
    request: Request,
    q: str = "",
    category: str = "",
    limit: int = 20,
    offset: int = 0,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Paginated catalog browse. Searches name, SKU/barcode, and category
    name (case-insensitive contains). An optional ``category`` param restricts
    to items whose category name matches exactly (case-insensitive), combinable
    with ``q``. ``total`` is the unfiltered-by-page match count."""
    qv = (q or "").strip()
    cat = (category or "").strip()
    limit = max(1, min(100, int(limit or 20)))
    offset = max(0, int(offset or 0))

    base = (db.query(Part)
            .outerjoin(Category, Part.category_id == Category.id)
            .filter(Part.active == True,  # noqa: E712
                    Part.archived == False))  # noqa: E712
    if qv:
        like = f"%{qv}%"
        base = base.filter(or_(Part.name.ilike(like),
                               Part.barcode.ilike(like),
                               Category.name.ilike(like)))
    if cat:
        base = base.filter(func.lower(Category.name) == cat.lower())

    total = base.with_entities(func.count(func.distinct(Part.id))).scalar() or 0
    rows = base.order_by(Part.name).offset(offset).limit(limit).all()
    return ItemsSearchOut(
        items=[_item_dto(db, tech, p, request) for p in rows],
        total=int(total),
        has_more=(offset + len(rows)) < int(total),
    )


# ---- 1b. GET /mobile/items/categories --------------------------------------

class CategoryCountOut(BaseModel):
    name: str
    count: int


class CategoriesOut(BaseModel):
    categories: List[CategoryCountOut]


@router.get("/items/categories", response_model=CategoriesOut)
def items_categories(
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Category filter chips for the catalog: every category that has at least
    one active, non-archived item, with its item count. Sorted by count desc,
    then name asc. Uncategorised items are not a category and are excluded."""
    rows = (db.query(Category.name, func.count(Part.id))
            .join(Part, Part.category_id == Category.id)
            .filter(Part.active == True,  # noqa: E712
                    Part.archived == False)  # noqa: E712
            .group_by(Category.id)
            .having(func.count(Part.id) > 0)
            .all())
    out = sorted(((name, int(n)) for name, n in rows), key=lambda r: (-r[1], r[0].lower()))
    return CategoriesOut(categories=[CategoryCountOut(name=name, count=n) for name, n in out])


# ---- 1c. white-labeling (public — no bearer) -------------------------------

class WhitelabelOut(BaseModel):
    brand_name: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color_hex: Optional[str] = None
    accent_color_hex: Optional[str] = None


@router.get("/whitelabel", response_model=WhitelabelOut)
def whitelabel(request: Request, db: Session = Depends(get_db)):
    """Per-host branding for the app's theme + login screen. PUBLIC by design —
    no bearer token — so the login screen can be branded before sign-in. All
    fields nullable; the app falls back to defaults. inv-keep stores a single
    brand colour (brand_accent), mapped to primary; accent stays null."""
    brand_name = (store.get(db, "app_title") or "").strip() or None
    logo = (store.get(db, "brand_logo") or "").strip()
    logo_url = _abs_url(request, "/mobile/brand/logo") if logo else None
    primary = _hex_color_or_none(store.get(db, "brand_accent"))
    return WhitelabelOut(
        brand_name=brand_name,
        logo_url=logo_url,
        primary_color_hex=primary,
        accent_color_hex=None,
    )


@router.get("/brand/logo")
def brand_logo_file(db: Session = Depends(get_db)):
    """Serve the uploaded brand logo so the app can show it on the pre-auth
    login screen (the /uploads mount is cookie-auth-gated). PUBLIC. The logo is
    always a raster image — the web upload allowlist excludes SVG — so no
    sandbox CSP is needed here."""
    logo = (store.get(db, "brand_logo") or "").strip()
    if not logo:
        raise HTTPException(status_code=404, detail="no_logo")
    name = logo.split("?", 1)[0]  # strip the ?v= cache-buster
    if not name.startswith("/uploads/"):
        raise HTTPException(status_code=404, detail="no_logo")
    fname = name[len("/uploads/"):]
    if "/" in fname or ".." in fname or not fname:
        raise HTTPException(status_code=404, detail="no_logo")
    path = os.path.join("data", "uploads", fname)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="no_logo")
    ext = os.path.splitext(path)[1].lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "public, max-age=86400"})


# ---- 1d. item icons: serve (public) + upload (admin) -----------------------

@router.get("/items/{item_id}/icon")
def item_icon_file(item_id: int, db: Session = Depends(get_db)):
    """Serve an item's icon. PUBLIC so the app's image loader (no bearer) and
    cache can fetch it. Hardened headers (sandbox CSP + nosniff) neutralise a
    hostile SVG even on direct navigation; the app loads it as <img>."""
    part = db.get(Part, item_id)
    if part is None or not (part.icon_image or ""):
        raise HTTPException(status_code=404, detail="no_icon")
    matches = sorted(glob.glob(os.path.join(ITEM_ICON_DIR, f"{item_id}.*")))
    if not matches:
        raise HTTPException(status_code=404, detail="no_icon")
    path = matches[0]
    ext = os.path.splitext(path)[1].lower()
    media = _ICON_MEDIA.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media, headers=dict(_ICON_HEADERS))


@router.post("/items/{item_id}/icon", status_code=201)
async def upload_item_icon(
    item_id: int,
    request: Request,
    image: UploadFile = File(...),
    tech: KioskPin = Depends(get_inventory_admin),
    db: Session = Depends(get_db),
):
    """Upload a per-item icon (SVG / PNG / JPEG, ~256 KB). Admin only. Returns
    the icon_url that will appear in ItemDto.icon_url. SVG is allowed because
    the GET route above serves it sandboxed."""
    part = db.get(Part, item_id)
    if part is None or not part.active:
        raise HTTPException(status_code=404, detail="item_not_found")
    ctype = (image.content_type or "").lower()
    ext = _ICON_EXT.get(ctype)
    if not ext:
        raise HTTPException(status_code=415, detail="unsupported_icon_type")
    data = await image.read(_MAX_ICON_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="empty_image")
    if len(data) > _MAX_ICON_BYTES:
        raise HTTPException(status_code=413, detail="icon_too_large")
    for old in glob.glob(os.path.join(ITEM_ICON_DIR, f"{item_id}.*")):
        try:
            os.remove(old)
        except OSError:
            pass
    with open(os.path.join(ITEM_ICON_DIR, f"{item_id}{ext}"), "wb") as fh:
        fh.write(data)
    served = f"/mobile/items/{item_id}/icon?v={secrets.token_hex(4)}"
    part.icon_image = served
    audit.record(db, {"username": _tech_username(tech)}, "item.icon", "part", part.id,
                 f"Mobile icon uploaded ({ctype}, {len(data)} bytes)")
    db.commit()
    return {"icon_url": _abs_url(request, served)}


# ---- 1e. inventory management (admin only): create / patch / stock ----------

class ItemCreateIn(BaseModel):
    sku: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = None
    default_price_cents: int = Field(ge=0)
    starting_stock_at_location_id: Optional[int] = None
    starting_stock_qty: int = 0


@router.post("/items", status_code=201, response_model=ItemOut)
def create_item(
    payload: ItemCreateIn,
    request: Request,
    tech: KioskPin = Depends(get_inventory_admin),
    db: Session = Depends(get_db),
):
    """Create a catalog item from the app's Inventory screen. Admin only.
    Optionally seeds starting stock at a location."""
    sku = payload.sku.strip()
    if len(sku) > 128 or any(ord(ch) < 0x20 for ch in sku):
        raise HTTPException(status_code=400, detail={"error": "bad_sku"})
    if db.query(Part).filter(Part.barcode == sku).first() is not None:
        raise HTTPException(status_code=409, detail={"error": "sku_exists", "sku": sku})
    cat_id = _resolve_or_create_category(db, payload.category)
    part = Part(
        name=payload.name.strip()[:200],
        barcode=sku,
        type="bulk",
        unit_cost=0,
        unit_price=round(int(payload.default_price_cents) / 100, 2),
        category_id=cat_id,
        quantity_on_hand=0,
        active=True,
        archived=False,
    )
    db.add(part)
    db.flush()
    qty = max(0, int(payload.starting_stock_qty or 0))
    if qty and payload.starting_stock_at_location_id:
        loc = db.get(Location, payload.starting_stock_at_location_id)
        if loc is None or not loc.active or loc.archived:
            raise HTTPException(status_code=404, detail={"error": "location_not_found",
                                                         "location_id": payload.starting_stock_at_location_id})
        sl = orders_mod.ensure_stock_row(db, part.id, loc.id)
        sl.quantity += qty
        part.quantity_on_hand += qty
        audit.record(db, {"username": _tech_username(tech)}, "part.restock", "part", part.id,
                     f"+{qty} → {loc.name} (mobile create)")
    audit.record(db, {"username": _tech_username(tech)}, "item.create", "part", part.id,
                 f"Mobile item: {part.name} ({sku})")
    db.commit()
    return _item_dto(db, tech, part, request)


class ItemPatchIn(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    default_price_cents: Optional[int] = None


@router.patch("/items/{item_id}", response_model=ItemOut)
def patch_item(
    item_id: int,
    payload: ItemPatchIn,
    request: Request,
    tech: KioskPin = Depends(get_inventory_admin),
    db: Session = Depends(get_db),
):
    """Edit name / category / price of a catalog item. Admin only."""
    part = db.get(Part, item_id)
    if part is None or not part.active:
        raise HTTPException(status_code=404, detail="item_not_found")
    if payload.name is not None:
        nm = payload.name.strip()
        if not nm:
            raise HTTPException(status_code=422, detail={"error": "name_required"})
        part.name = nm[:200]
    if payload.category is not None:
        part.category_id = _resolve_or_create_category(db, payload.category)
    if payload.default_price_cents is not None:
        if int(payload.default_price_cents) < 0:
            raise HTTPException(status_code=422, detail={"error": "negative_price"})
        part.unit_price = round(int(payload.default_price_cents) / 100, 2)
    audit.record(db, {"username": _tech_username(tech)}, "item.edit", "part", part.id,
                 f"Mobile edit: {part.name}")
    db.commit()
    return _item_dto(db, tech, part, request)


class StockAdjustIn(BaseModel):
    delta: int
    location_id: int
    reason: Optional[str] = None


@router.post("/items/{item_id}/stock-adjust")
def stock_adjust(
    item_id: int,
    payload: StockAdjustIn,
    tech: KioskPin = Depends(get_inventory_admin),
    db: Session = Depends(get_db),
):
    """Adjust on-hand at a location by a signed delta, recording the reason +
    acting tech in the audit ledger. Admin only. Refuses an adjustment that
    would drive the location negative. Returns the new on-hand at that location."""
    part = db.get(Part, item_id)
    if part is None or not part.active:
        raise HTTPException(status_code=404, detail="item_not_found")
    loc = db.get(Location, payload.location_id)
    if loc is None or not loc.active or loc.archived:
        raise HTTPException(status_code=404, detail={"error": "location_not_found",
                                                     "location_id": payload.location_id})
    delta = int(payload.delta)
    if delta == 0:
        raise HTTPException(status_code=400, detail={"error": "zero_delta"})
    sl = orders_mod.ensure_stock_row(db, part.id, loc.id)
    new_qty = sl.quantity + delta
    if new_qty < 0:
        raise HTTPException(status_code=409, detail={"error": "insufficient_stock",
                                                     "available": int(sl.quantity)})
    sl.quantity = new_qty
    part.quantity_on_hand += delta
    reason = (payload.reason or "").strip()[:200]
    audit.record(db, {"username": _tech_username(tech)}, "part.stock_adjust", "part", part.id,
                 f"{'+' if delta >= 0 else ''}{delta} @ {loc.name} (now {new_qty})"
                 + (f" — {reason}" if reason else ""))
    db.commit()
    return {"new_qty": int(new_qty)}


# ---- 3. customers: search / jobs / by-card ---------------------------------

class CustomerOut(BaseModel):
    id: int
    name: str
    default_location_id: Optional[int] = None


def _customer_dto(c: Client) -> CustomerOut:
    return CustomerOut(id=c.id, name=c.name, default_location_id=None)


class CustomersSearchOut(BaseModel):
    customers: List[CustomerOut]
    total: int
    has_more: bool


@router.get("/customers/search", response_model=CustomersSearchOut)
def customers_search(
    q: str = "",
    limit: int = 20,
    offset: int = 0,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Paginated customer browse. Searches name + account reference
    (case-insensitive contains). Archived (walk-in) clients are
    excluded so they don't pollute the recurring-customer roster."""
    qv = (q or "").strip()
    limit = max(1, min(100, int(limit or 20)))
    offset = max(0, int(offset or 0))

    base = db.query(Client).filter(Client.active == True,  # noqa: E712
                                    Client.archived == False)  # noqa: E712
    if qv:
        like = f"%{qv}%"
        base = base.filter(or_(Client.name.ilike(like),
                               Client.reference.ilike(like)))

    total = base.count()
    rows = base.order_by(Client.name).offset(offset).limit(limit).all()
    return CustomersSearchOut(
        customers=[_customer_dto(c) for c in rows],
        total=int(total),
        has_more=(offset + len(rows)) < int(total),
    )


class JobOut(BaseModel):
    id: int
    name: str
    status: str
    created_at: str


def _job_dto(j: Job) -> JobOut:
    return JobOut(
        id=j.id,
        name=j.name,
        status="open" if j.active else "inactive",
        created_at=_iso_utc(j.created_at) or "",
    )


class JobsListOut(BaseModel):
    jobs: List[JobOut]


@router.get("/customers/{customer_id}/jobs", response_model=JobsListOut)
def customer_jobs(
    customer_id: int,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Jobs under a customer that a mobile cart can charge to. inv-keep
    has no "archived" flag on Job — we filter by ``active == True``
    (the closest mirror of the spec's "chargeable" rule)."""
    client = db.get(Client, customer_id)
    if client is None or client.archived:
        raise HTTPException(status_code=404, detail="customer_not_found")
    rows = (db.query(Job)
            .filter(Job.client_id == customer_id,
                    Job.active == True)  # noqa: E712
            .order_by(Job.name).all())
    return JobsListOut(jobs=[_job_dto(j) for j in rows])


class JobCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    note: Optional[str] = None


@router.post("/customers/{customer_id}/jobs", status_code=201, response_model=JobOut)
def create_customer_job(
    customer_id: int,
    payload: JobCreateIn,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Field-tech "start a new job on the fly" — creates an active Job
    under the named customer. Notes column stays compatible with the
    web UI's /jobs/add path."""
    client = db.get(Client, customer_id)
    if client is None or client.archived:
        raise HTTPException(status_code=404, detail="customer_not_found")
    job = Job(
        client_id=customer_id,
        name=payload.name.strip(),
        notes=(payload.note or "").strip(),
        active=True,
    )
    db.add(job)
    db.flush()
    audit.record(db, {"username": _tech_username(tech)}, "job.create", "job", job.id,
                 f"Mobile job: {job.name} (client #{customer_id})")
    db.commit()
    return _job_dto(job)


@router.get("/customers/by-card/{uid}", response_model=CustomerOut)
def customer_by_card(
    uid: str,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    if not uid:
        raise HTTPException(status_code=404, detail="card_not_found")
    client = (db.query(Client)
              .filter(Client.card_uid == uid,
                      Client.active == True)  # noqa: E712
              .first())
    if client is None:
        raise HTTPException(status_code=404, detail="card_not_found")
    # Client doesn't carry a per-row default location today; the device
    # falls back to the tech's default_location_id from /mobile/auth/token.
    return _customer_dto(client)


# ---- 4. GET /mobile/locations ----------------------------------------------

class LocationOut(BaseModel):
    id: int
    name: str
    is_default: bool


class LocationsListOut(BaseModel):
    locations: List[LocationOut]


@router.get("/locations", response_model=LocationsListOut)
def list_locations(
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Locations the tech can charge from. inv-keep doesn't carry
    per-tech location permissions (the web UI shows every active
    location to every signed-in user), so we return every active,
    non-archived location and flag the tech's default."""
    rows = (db.query(Location)
            .filter(Location.active == True,  # noqa: E712
                    Location.archived == False)  # noqa: E712
            .order_by(Location.name).all())
    default_id = tech.location_id
    return LocationsListOut(locations=[
        LocationOut(id=l.id, name=l.name,
                    is_default=(default_id is not None and l.id == default_id))
        for l in rows
    ])


# ---- 5. POST /mobile/receipts ----------------------------------------------

class ReceiptOut(BaseModel):
    receipt_id: str
    url: str


@router.post("/receipts", status_code=201, response_model=ReceiptOut)
async def upload_receipt(
    image: UploadFile = File(...),
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Upload an image of a paper receipt for a custom store-bought
    purchase. The returned ``receipt_id`` is referenced from a custom
    order line on POST /mobile/orders. JPEG / PNG only (no SVG — stored
    XSS via /uploads/), 5 MB cap.
    """
    ctype = (image.content_type or "").lower()
    ext = _RECEIPT_EXT.get(ctype)
    if not ext:
        raise HTTPException(status_code=415, detail="unsupported_image_type")
    # Read a hair over the limit so we can tell "exactly 5MB" from "5MB+1".
    data = await image.read(_MAX_RECEIPT_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="empty_image")
    if len(data) > _MAX_RECEIPT_BYTES:
        raise HTTPException(status_code=413, detail="image_too_large")
    receipt_id = "rcpt_" + secrets.token_hex(8)
    fname = f"{receipt_id}{ext}"
    with open(os.path.join(RECEIPTS_DIR, fname), "wb") as fh:
        fh.write(data)
    url = f"/uploads/receipts/{fname}"
    db.add(Receipt(receipt_id=receipt_id, kiosk_pin_id=tech.id, url=url,
                   content_type=ctype, size_bytes=len(data)))
    audit.record(db, {"username": _tech_username(tech)}, "receipt.upload",
                 "receipt", None, f"{receipt_id} ({len(data)} bytes)")
    db.commit()
    return ReceiptOut(receipt_id=receipt_id, url=url)


# ---- 6. POST /mobile/orders (catalog + custom lines + job_id) --------------

class OrderLineIn(BaseModel):
    # ``type`` defaults to "catalog" for backwards compat with v1.26.0
    # clients that only ever sent ``{item_id, qty}``.
    type: Optional[str] = None
    # Catalog line — references an existing Part.
    item_id: Optional[int] = None
    qty: int = Field(gt=0)
    # Custom line — store-bought item billed through to the client.
    # ``name`` + ``unit_price_cents`` are required for type="custom".
    name: Optional[str] = None
    unit_price_cents: Optional[int] = None
    receipt_id: Optional[str] = None


class OrderIn(BaseModel):
    client_action_id: str = Field(min_length=1, max_length=120)
    customer_id: int
    location_id: int
    # Optional: when supplied, must belong to the order's customer_id.
    job_id: Optional[int] = None
    captured_at: Optional[str] = None
    geo_lat: Optional[float] = None
    geo_lon: Optional[float] = None
    lines: List[OrderLineIn]
    note: Optional[str] = None
    # Escape hatch for a deliberate no-charge order (warranty swap, free item).
    # When false (default) a $0 total or a $0 client-supplied line is rejected.
    allow_zero_total: bool = False


class OrderOut(BaseModel):
    order_id: int
    order_number: str
    created_at: str
    idempotent_replay: bool


def _serialize_order(order: Order, replay: bool) -> OrderOut:
    when = order.submitted_at or order.created_at
    return OrderOut(
        order_id=order.id,
        order_number=order.number or "",
        created_at=_iso_utc(when) or "",
        idempotent_replay=replay,
    )


def _validate_line_shape(idx: int, ln: OrderLineIn) -> str:
    """Return the validated line type ("catalog" / "custom") or raise 422."""
    line_type = (ln.type or "catalog").lower()
    if line_type == "catalog":
        if not ln.item_id:
            raise HTTPException(status_code=422, detail=[{
                "loc": ["body", "lines", idx, "item_id"],
                "msg": "required for catalog lines",
            }])
        return "catalog"
    if line_type == "custom":
        if not (ln.name or "").strip():
            raise HTTPException(status_code=422, detail=[{
                "loc": ["body", "lines", idx, "name"],
                "msg": "required for custom lines",
            }])
        if ln.unit_price_cents is None:
            raise HTTPException(status_code=422, detail=[{
                "loc": ["body", "lines", idx, "unit_price_cents"],
                "msg": "required for custom lines",
            }])
        if int(ln.unit_price_cents) < 0:
            raise HTTPException(status_code=422, detail=[{
                "loc": ["body", "lines", idx, "unit_price_cents"],
                "msg": "must be >= 0",
            }])
        return "custom"
    raise HTTPException(status_code=422, detail=[{
        "loc": ["body", "lines", idx, "type"],
        "msg": "must be 'catalog' or 'custom'",
    }])


@router.post("/orders", status_code=201, response_model=OrderOut)
def create_order(
    payload: OrderIn,
    response: Response,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    tech_user = _tech_username(tech)
    cid = (payload.client_action_id or "").strip()

    # 1. Idempotent replay — (tech, client_action_id) already submitted?
    existing = (db.query(Order)
                .filter(Order.client_action_id == cid,
                        Order.created_by == tech_user)
                .first())
    if existing is not None:
        response.status_code = 200
        return _serialize_order(existing, True)

    if not payload.lines:
        raise HTTPException(status_code=422,
                            detail=[{"loc": ["body", "lines"], "msg": "must not be empty"}])

    client = db.get(Client, payload.customer_id)
    if client is None:
        raise HTTPException(status_code=404,
                            detail={"error": "customer_not_found",
                                    "customer_id": payload.customer_id})

    location = db.get(Location, payload.location_id)
    if location is None or not location.active or location.archived:
        raise HTTPException(status_code=404,
                            detail={"error": "location_not_found",
                                    "location_id": payload.location_id})

    # Job (optional) must belong to the same customer + still be active.
    job: Optional[Job] = None
    if payload.job_id:
        job = db.get(Job, payload.job_id)
        if job is None or not job.active or job.client_id != client.id:
            raise HTTPException(status_code=422, detail={
                "error": "job_mismatch",
                "job_id": payload.job_id,
                "customer_id": client.id,
            })

    # Pre-validate every line so we don't half-commit on a bad payload.
    line_types: List[str] = []
    catalog_parts: dict = {}
    receipt_ids: set = set()
    for idx, ln in enumerate(payload.lines):
        kind = _validate_line_shape(idx, ln)
        line_types.append(kind)
        if kind == "catalog":
            part = db.get(Part, ln.item_id)
            if part is None or not part.active:
                raise HTTPException(status_code=404,
                                    detail={"error": "item_not_found",
                                            "item_id": ln.item_id})
            catalog_parts[ln.item_id] = part
        elif kind == "custom" and ln.receipt_id:
            receipt_ids.add(ln.receipt_id)

    # Receipts must belong to this tech — same scope rule as the rest of
    # the mobile surface.
    if receipt_ids:
        owned = {r.receipt_id for r in
                 db.query(Receipt)
                 .filter(Receipt.receipt_id.in_(receipt_ids),
                         Receipt.kiosk_pin_id == tech.id).all()}
        missing = receipt_ids - owned
        if missing:
            raise HTTPException(status_code=422, detail={
                "error": "unknown_receipt",
                "receipt_ids": sorted(missing),
            })

    # Zero-total guard (#5) — server-side belt + suspenders. A catalog line's
    # price is the server's stored default, so a $0 catalog item is allowed
    # per-line; but a $0 *client-supplied* custom-line price, or a $0 order
    # total, is rejected unless allow_zero_total is set (intentional no-charge).
    if not payload.allow_zero_total:
        total_cents = 0
        for idx, ln in enumerate(payload.lines):
            if line_types[idx] == "catalog":
                part = catalog_parts[ln.item_id]
                price_cents = int(round(float(part.unit_price or 0) * 100))
            else:
                price_cents = int(ln.unit_price_cents or 0)
                if price_cents == 0:
                    raise HTTPException(status_code=400, detail={
                        "error": "zero_total",
                        "detail": "A custom line priced at $0 is not allowed; set allow_zero_total to override.",
                    })
            total_cents += price_cents * int(ln.qty)
        if total_cents == 0:
            raise HTTPException(status_code=400, detail={
                "error": "zero_total",
                "detail": "Order total is $0; set allow_zero_total to override.",
            })

    # Geo sanitisation — same NaN/Infinity guard as /api/cart/scan.
    lat, lng = payload.geo_lat, payload.geo_lon
    if not (_finite(lat) and -90 <= lat <= 90):
        lat = None
    if not (_finite(lng) and -180 <= lng <= 180):
        lng = None
    if lat is None or lng is None:
        lat = lng = None

    captured = _parse_iso(payload.captured_at)

    # Build the order in submitted state (no open-cart intermediate — the
    # device already has the cart). created_at carries the device's
    # captured-at when supplied so the audit trail reflects scan time, not
    # upload time.
    order = Order(
        status="submitted",
        created_by=tech_user,
        submitted_by=tech_user,
        customer_id=client.id,
        job_id=job.id if job else None,
        location_id=location.id,
        client_action_id=cid,
        submitted_at=datetime.utcnow(),
    )
    if captured is not None:
        order.created_at = captured
    db.add(order)
    # The (client_action_id, created_by) unique constraint closes the race the
    # SELECT-then-INSERT idempotency check above can't: two retries from a
    # flaky-signal device arriving together. If the partner request already
    # committed this action id, the flush raises — return its order as a
    # replay instead of creating a duplicate charge-out.
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = (db.query(Order)
                    .filter(Order.client_action_id == cid,
                            Order.created_by == tech_user)
                    .first())
        if existing is not None:
            response.status_code = 200
            return _serialize_order(existing, True)
        raise

    note = (payload.note or "").strip()[:500]
    for idx, ln in enumerate(payload.lines):
        kind = line_types[idx]
        qty = int(ln.qty)
        if kind == "catalog":
            part = catalog_parts[ln.item_id]
            sl = orders_mod.ensure_stock_row(db, part.id, location.id)
            if sl.quantity < qty:
                db.rollback()
                raise HTTPException(status_code=409,
                                    detail={"error": "insufficient_stock",
                                            "item_id": part.id,
                                            "available": int(sl.quantity)})
            sl.quantity -= qty
            part.quantity_on_hand -= qty
            unit_cost = part.unit_cost
            unit_price = part.unit_price
            line_receipt = None
            txn_note = note
        else:  # custom
            # Mirror /api/cart/custom: build an archived Part so the line
            # still flows through reports / audits / voids like every other
            # transaction. The Part name + price ARE the custom line's
            # display data — round-tripped via Transaction.part_id.
            part = Part(
                name=(ln.name or "").strip()[:200],
                description="",
                type="bulk",
                unit_cost=0,
                unit_price=round(int(ln.unit_price_cents) / 100, 2),
                quantity_on_hand=0,
                archived=True,
                barcode=f"CUSTOM-{uuid.uuid4().hex[:12].upper()}",
                barcode_generated=False,
                active=True,
            )
            db.add(part)
            db.flush()
            # Stamp a stock_levels row at zero so per-location ledgers stay
            # consistent (no decrement — we never had this stock).
            orders_mod.ensure_stock_row(db, part.id, location.id)
            unit_cost = 0
            unit_price = part.unit_price
            line_receipt = ln.receipt_id or None
            txn_note = (note + " | custom") if note else "custom"

        txn = Transaction(
            order_id=order.id,
            part_id=part.id,
            customer_id=client.id,
            job_id=order.job_id,
            location_id=location.id,
            quantity=qty,
            unit_cost_at_time=unit_cost,
            unit_price_at_time=unit_price,
            scanned_by=tech_user,
            note=txn_note,
            receipt_id=line_receipt,
            lat=lat, lng=lng,
        )
        db.add(txn)

    # Number assignment with retry on UNIQUE collision — same pattern as
    # /api/cart/submit.
    for _ in range(3):
        order.number = orders_mod.next_order_number(db)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            # The flush may have detached state; re-load and try again.
            order = (db.query(Order)
                     .filter(Order.client_action_id == cid,
                             Order.created_by == tech_user)
                     .first())
            if order is None:
                raise HTTPException(status_code=500, detail="number_collision")
    else:
        raise HTTPException(status_code=500, detail="number_collision")

    audit.record(db, {"username": tech_user}, "order.submit", "order", order.id,
                 f"{order.number}: mobile / {len(payload.lines)} line(s) → {client.name}")
    db.commit()
    return _serialize_order(order, False)


# ---- 7. GET /mobile/orders/recent ------------------------------------------

class RecentOrderOut(BaseModel):
    order_id: int
    order_number: str
    customer_name: str
    created_at: str
    line_count: int
    total_cents: int


class RecentOrdersOut(BaseModel):
    orders: List[RecentOrderOut]
    next_before: Optional[str] = None


def _lines_by_order(db: Session, order_ids: List[int]) -> dict:
    """One batched query → {order_id: [non-voided Transaction, ...]}."""
    out: dict = {}
    if order_ids:
        for ln in (db.query(Transaction)
                   .filter(Transaction.order_id.in_(order_ids),
                           Transaction.voided == False)  # noqa: E712
                   .all()):
            out.setdefault(ln.order_id, []).append(ln)
    return out


def _order_total_cents(lines) -> int:
    return sum(int(round(float(ln.unit_price_at_time or 0) * 100)) * ln.quantity
               for ln in lines)


def _order_row(o: Order, lines) -> RecentOrderOut:
    return RecentOrderOut(
        order_id=o.id,
        order_number=o.number or "",
        customer_name=o.client.name if o.client else "",
        created_at=_iso_utc(o.submitted_at or o.created_at) or "",
        line_count=len(lines),
        total_cents=_order_total_cents(lines),
    )


@router.get("/orders/recent", response_model=RecentOrdersOut)
def recent_orders(
    limit: int = 20,
    before: Optional[str] = None,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    limit = max(1, min(100, int(limit or 20)))
    tech_user = _tech_username(tech)
    q = (db.query(Order)
         .filter(Order.created_by == tech_user,
                 Order.status == "submitted")
         .order_by(desc(Order.submitted_at), desc(Order.id)))
    cutoff = _parse_iso(before)
    if cutoff is not None:
        q = q.filter(Order.submitted_at < cutoff)
    # Fetch one extra to know if a next page exists. Eager-load the client so
    # the loop below doesn't lazy-load o.client per order.
    rows = q.options(selectinload(Order.client)).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    lines_by_order = _lines_by_order(db, [o.id for o in rows])
    out = [_order_row(o, lines_by_order.get(o.id, [])) for o in rows]

    next_before = None
    if has_more and rows:
        anchor = rows[-1].submitted_at or rows[-1].created_at
        next_before = _iso_utc(anchor)
    return RecentOrdersOut(orders=out, next_before=next_before)


# ---- 8. GET /mobile/orders/zero-total (audit) ------------------------------

# Cap how far back the zero-total scan reaches in one page. $0 orders are rare
# (this is an audit list), so a generous cap keeps the endpoint bounded without
# a stored total column.
_ZERO_SCAN_CAP = 5000


@router.get("/orders/zero-total", response_model=RecentOrdersOut)
def zero_total_orders(
    limit: int = 20,
    before: Optional[str] = None,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    """Audit list of this tech's submitted orders whose total is $0 — the ones
    that slipped through before the client-side guard. Same shape + pagination
    as /orders/recent."""
    limit = max(1, min(100, int(limit or 20)))
    tech_user = _tech_username(tech)
    q = (db.query(Order)
         .filter(Order.created_by == tech_user,
                 Order.status == "submitted")
         .order_by(desc(Order.submitted_at), desc(Order.id)))
    cutoff = _parse_iso(before)
    if cutoff is not None:
        q = q.filter(Order.submitted_at < cutoff)
    candidates = q.options(selectinload(Order.client)).limit(_ZERO_SCAN_CAP).all()
    lines_by_order = _lines_by_order(db, [o.id for o in candidates])
    zeros = [o for o in candidates
             if _order_total_cents(lines_by_order.get(o.id, [])) == 0]
    has_more = len(zeros) > limit
    zeros = zeros[:limit]
    out = [_order_row(o, lines_by_order.get(o.id, [])) for o in zeros]

    next_before = None
    if has_more and zeros:
        anchor = zeros[-1].submitted_at or zeros[-1].created_at
        next_before = _iso_utc(anchor)
    return RecentOrdersOut(orders=out, next_before=next_before)

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

import hmac
import math
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit
from . import orders as orders_mod
from .database import get_db
from .models import (
    Client, KioskPin, Location, MobileSession, Order, Part, Transaction,
)


router = APIRouter(prefix="/mobile", tags=["mobile"])


TOKEN_LIFETIME = timedelta(hours=12)


# ---- helpers ---------------------------------------------------------------

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


def _finite(v) -> bool:
    if v is None:
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


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


# ---- 1. POST /mobile/auth/token --------------------------------------------

class AuthTokenIn(BaseModel):
    pin: Optional[str] = None
    badge_uid: Optional[str] = None


class TechOut(BaseModel):
    id: int
    name: str
    default_location_id: Optional[int] = None


class AuthTokenOut(BaseModel):
    token: str
    expires_at: str
    tech: TechOut


@router.post("/auth/token", response_model=AuthTokenOut)
def auth_token(payload: AuthTokenIn, db: Session = Depends(get_db)):
    pin_val = (payload.pin or "").strip()
    badge_val = (payload.badge_uid or "").strip()
    if not pin_val and not badge_val:
        raise HTTPException(status_code=401, detail="missing_credentials")

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
        raise HTTPException(status_code=401, detail="invalid_credentials")

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
        ),
    )


# ---- 2. GET /mobile/items/by-barcode/{code} --------------------------------

class ItemOut(BaseModel):
    id: int
    sku: str
    name: str
    category: str
    in_stock_at_location: int
    default_price_cents: int


@router.get("/items/by-barcode/{code}", response_model=ItemOut)
def item_by_barcode(
    code: str,
    tech: KioskPin = Depends(get_current_tech),
    db: Session = Depends(get_db),
):
    part = (db.query(Part)
            .filter(Part.barcode == code, Part.active == True)  # noqa: E712
            .first())
    if part is None:
        raise HTTPException(status_code=404, detail="item_not_found")
    loc_id = tech.location_id
    if loc_id:
        qty = orders_mod.stock_at(db, part.id, loc_id)
    else:
        qty = int(part.quantity_on_hand or 0)
    cat_name = part.category.name if part.category else ""
    price_cents = int(round(float(part.unit_price or 0) * 100))
    return ItemOut(
        id=part.id,
        sku=part.barcode,
        name=part.name,
        category=cat_name,
        in_stock_at_location=qty,
        default_price_cents=price_cents,
    )


# ---- 3. POST /mobile/orders ------------------------------------------------

class OrderLineIn(BaseModel):
    item_id: int
    qty: int = Field(gt=0)


class OrderIn(BaseModel):
    client_action_id: str = Field(min_length=1, max_length=120)
    customer_id: int
    location_id: int
    captured_at: Optional[str] = None
    geo_lat: Optional[float] = None
    geo_lon: Optional[float] = None
    lines: List[OrderLineIn]
    note: Optional[str] = None


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

    # Validate items up-front (404 on unknown is clearer than blowing up
    # mid-loop), then re-check stock atomically below.
    parts_by_id = {}
    for ln in payload.lines:
        part = db.get(Part, ln.item_id)
        if part is None or not part.active:
            raise HTTPException(status_code=404,
                                detail={"error": "item_not_found",
                                        "item_id": ln.item_id})
        parts_by_id[ln.item_id] = part

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
        location_id=location.id,
        client_action_id=cid,
        submitted_at=datetime.utcnow(),
    )
    if captured is not None:
        order.created_at = captured
    db.add(order)
    db.flush()

    note = (payload.note or "").strip()[:500]
    total_cents = 0
    for ln in payload.lines:
        part = parts_by_id[ln.item_id]
        qty = int(ln.qty)
        sl = orders_mod.ensure_stock_row(db, part.id, location.id)
        if sl.quantity < qty:
            db.rollback()
            raise HTTPException(status_code=409,
                                detail={"error": "insufficient_stock",
                                        "item_id": part.id,
                                        "available": int(sl.quantity)})
        sl.quantity -= qty
        part.quantity_on_hand -= qty
        txn = Transaction(
            order_id=order.id,
            part_id=part.id,
            customer_id=client.id,
            location_id=location.id,
            quantity=qty,
            unit_cost_at_time=part.unit_cost,
            unit_price_at_time=part.unit_price,
            scanned_by=tech_user,
            note=note,
            lat=lat, lng=lng,
        )
        db.add(txn)
        total_cents += int(round(float(part.unit_price or 0) * 100)) * qty

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


# ---- 4. GET /mobile/orders/recent ------------------------------------------

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
    # Fetch one extra to know if a next page exists.
    rows = q.limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    out: List[RecentOrderOut] = []
    for o in rows:
        lines = (db.query(Transaction)
                 .filter(Transaction.order_id == o.id,
                         Transaction.voided == False)  # noqa: E712
                 .all())
        total_cents = sum(
            int(round(float(ln.unit_price_at_time or 0) * 100)) * ln.quantity
            for ln in lines
        )
        out.append(RecentOrderOut(
            order_id=o.id,
            order_number=o.number or "",
            customer_name=o.client.name if o.client else "",
            created_at=_iso_utc(o.submitted_at or o.created_at) or "",
            line_count=len(lines),
            total_cents=total_cents,
        ))

    next_before = None
    if has_more and rows:
        anchor = rows[-1].submitted_at or rows[-1].created_at
        next_before = _iso_utc(anchor)
    return RecentOrdersOut(orders=out, next_before=next_before)


# ---- 5. GET /mobile/customers/by-card/{uid} --------------------------------

class CustomerOut(BaseModel):
    id: int
    name: str
    default_location_id: Optional[int] = None


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
    return CustomerOut(id=client.id, name=client.name, default_location_id=None)

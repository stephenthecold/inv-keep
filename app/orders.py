"""Cart / order helpers.

Mostly the order-number generator (ORD-YYYYMM-NNNN, per-month counter) and a
small utility for the "one open cart per user" rule.
"""

import re
from datetime import datetime

from sqlalchemy import func

from . import audit
from .models import Location, Order, StockLevel, Transaction, Transfer, TransferLine


_NUM_RE = re.compile(r"^ORD-(\d{6})-(\d+)$")


def next_order_number(db, now=None) -> str:
    """Generate the next ORD-YYYYMM-NNNN for the given month, scanning the max
    counter on existing submitted orders. Caller is responsible for committing
    inside the same transaction so two concurrent submits don't collide; on
    SQLite the single-writer model makes the race window vanishingly small."""
    now = now or datetime.utcnow()
    prefix = f"ORD-{now:%Y%m}"
    # Pull all numbers for this month and find the max counter we've assigned.
    existing = (
        db.query(Order.number)
        .filter(Order.number.like(f"{prefix}-%"))
        .all()
    )
    max_n = 0
    for (num,) in existing:
        m = _NUM_RE.match(num or "")
        if m and m.group(1) == f"{now:%Y%m}":
            try:
                max_n = max(max_n, int(m.group(2)))
            except ValueError:
                pass
    return f"{prefix}-{max_n + 1:04d}"


def open_cart_for(db, username: str):
    """Return the user's current open cart (or None). One open cart per user."""
    if not username:
        return None
    return (
        db.query(Order)
        .filter(Order.status == "open", Order.created_by == username)
        .order_by(Order.created_at.desc())
        .first()
    )


def cart_lines(db, order):
    """Non-voided transaction lines for a cart, oldest first (insertion order)."""
    if order is None:
        return []
    return (
        db.query(Transaction)
        .filter(Transaction.order_id == order.id, Transaction.voided == False)  # noqa: E712
        .order_by(Transaction.id.asc())
        .all()
    )


def cart_totals(lines):
    """Sum subtotals across the cart lines. Returns (charge, cost, margin)."""
    charge = sum(float(ln.unit_price_at_time) * ln.quantity for ln in lines)
    cost = sum(float(ln.unit_cost_at_time) * ln.quantity for ln in lines)
    return charge, cost, charge - cost


def stock_at(db, part_id: int, location_id: int) -> int:
    """Quantity of `part_id` currently at `location_id`. Returns 0 if there's
    no row yet — callers that want to write should use ``ensure_stock_row``."""
    row = (db.query(StockLevel)
           .filter(StockLevel.part_id == part_id,
                   StockLevel.location_id == location_id)
           .first())
    return row.quantity if row else 0


def ensure_stock_row(db, part_id: int, location_id: int) -> StockLevel:
    """Return the StockLevel row for (part, location), creating a zero row
    if it doesn't exist yet. Caller commits."""
    row = (db.query(StockLevel)
           .filter(StockLevel.part_id == part_id,
                   StockLevel.location_id == location_id)
           .first())
    if row is None:
        row = StockLevel(part_id=part_id, location_id=location_id, quantity=0)
        db.add(row)
        db.flush()
    return row


def set_stock_level(db, user, part, loc, quantity, note=""):
    """Set the absolute on-hand for `part` at `loc`, adjusting the part's
    aggregate quantity_on_hand by the delta so it stays equal to the sum of
    stock_levels, and recording one `part.stock_set` audit row. Returns the
    delta. Caller validates inputs and commits. Shared by the per-item
    stocktake and the bulk set-count action."""
    sl = ensure_stock_row(db, part.id, loc.id)
    prior = sl.quantity
    delta = quantity - prior
    sl.quantity = quantity
    part.quantity_on_hand += delta
    if delta > 0 and part.low_stock_alerted:
        part.low_stock_alerted = False
    suffix = f" — {note}" if note else ""
    audit.record(db, user, "part.stock_set", "part", part.id,
                 f"{loc.name}: {prior} → {quantity} (Δ {delta:+d}){suffix}")
    return delta


def complete_transfer(db, user, src, dst, lines, notes="", summary=None):
    """Write one completed Transfer moving `lines` — a list of
    `(part_id, qty)` — from `src` to `dst`: create the Transfer, decrement
    source / increment dest stock rows, add a TransferLine per part, and
    record one `transfer.complete` audit row. Caller validates stock
    sufficiency and commits. Returns the Transfer. Shared by /transfers/new,
    the per-item move, and the bulk move so transfer history stays uniform."""
    transfer = Transfer(
        from_location_id=src.id,
        to_location_id=dst.id,
        status="completed",
        created_by=user.get("username", "") if isinstance(user, dict) else (user or ""),
        notes=(notes or "").strip(),
        completed_at=datetime.utcnow(),
    )
    db.add(transfer)
    db.flush()
    for pid, qty in lines:
        src_sl = ensure_stock_row(db, pid, src.id)
        dst_sl = ensure_stock_row(db, pid, dst.id)
        src_sl.quantity -= qty
        dst_sl.quantity += qty
        db.add(TransferLine(transfer_id=transfer.id, part_id=pid, quantity=qty))
    audit.record(db, user, "transfer.complete", "transfer", transfer.id,
                 summary or f"{src.name} → {dst.name}: {len(lines)} line(s)")
    return transfer


def default_location_id(db) -> int | None:
    """Return the id of the first active, non-archived location. Used as the
    fallback when a cart hasn't been pointed at one yet."""
    row = (db.query(Location)
           .filter(Location.active == True, Location.archived == False)  # noqa: E712
           .order_by(Location.id.asc())
           .first())
    return row.id if row else None

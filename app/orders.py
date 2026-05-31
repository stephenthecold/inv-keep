"""Cart / order helpers.

Mostly the order-number generator (ORD-YYYYMM-NNNN, per-month counter) and a
small utility for the "one open cart per user" rule.
"""

import re
from datetime import datetime

from sqlalchemy import func

from .models import Order, Transaction


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

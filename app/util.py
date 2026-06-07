"""Small dependency-free helpers, safe to import from anywhere (including
mobile.py) without risking a circular import on app.main."""

import math


def finite(v) -> bool:
    """True if ``v`` is a finite real number. Guards against NaN / Infinity
    sneaking in via JSON — every comparison against NaN returns False, so a
    range check alone (e.g. ``-90 <= lat <= 90``) is bypassable without this."""
    if v is None:
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False

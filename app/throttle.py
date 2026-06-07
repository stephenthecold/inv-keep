"""Shared in-process brute-force throttle for PIN logins.

Used by both the web kiosk login (``/kiosk/login``) and the mobile token
endpoint (``/mobile/auth/token``) so the same short PIN can't be brute-forced
through whichever surface lacks a guard.

Two layers, both in-memory (fine for the single-process deployment; state
resets on restart):

1. **Per-IP** — N bad attempts from one client IP locks that IP for a cooldown.
2. **Global backstop** — a much higher threshold of bad attempts across *all*
   IPs within a rolling window also trips a short cooldown. This is what stops
   an attacker who rotates ``X-Forwarded-For`` on every request (giving each
   attempt a fresh per-IP bucket) from bypassing the per-IP lock entirely.
"""

import threading
import time

_LOCK = threading.Lock()

# ip -> (fail_count, locked_until_epoch)
_FAILS: dict = {}
# Generic sliding-window hit log for rate_limited(): key -> [hit_epochs].
_HITS: dict = {}
# Across all IPs: rolling fail counter + a cooldown deadline.
_GLOBAL = {"fails": 0, "until": 0.0, "last": 0.0}

PER_IP_MAX = 5            # bad attempts from one IP before it's locked
GLOBAL_MAX = 50          # bad attempts across all IPs in the window before a global lock
GLOBAL_WINDOW = 300.0    # seconds of inactivity that resets the global counter


def client_ip(request) -> str:
    """Best-effort client IP for throttle bucketing. Prefers the first
    X-Forwarded-For hop (the real client behind a proxy); falls back to the
    direct peer. Spoofable — which is exactly why the global backstop exists."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def retry_after(ip) -> int:
    """Seconds the caller must wait before another attempt, or 0 if clear."""
    now = time.time()
    with _LOCK:
        _, until = _FAILS.get(ip, (0, 0.0))
        wait = max(until, _GLOBAL["until"]) - now
    return int(wait) + 1 if wait > 0 else 0


def record_failure(ip, lockout_seconds: int) -> None:
    """Count one bad attempt for ``ip`` and the global backstop, applying a
    ``lockout_seconds`` cooldown to whichever threshold it crosses."""
    now = time.time()
    with _LOCK:
        fails, until = _FAILS.get(ip, (0, 0.0))
        fails += 1
        if fails >= PER_IP_MAX:
            until = now + lockout_seconds
            fails = 0
        _FAILS[ip] = (fails, until)

        # Global counter decays after a quiet window so honest, spread-out
        # typos across a busy shop don't slowly accumulate into a lockout.
        if now - _GLOBAL["last"] > GLOBAL_WINDOW:
            _GLOBAL["fails"] = 0
        _GLOBAL["last"] = now
        _GLOBAL["fails"] += 1
        if _GLOBAL["fails"] >= GLOBAL_MAX:
            _GLOBAL["until"] = now + lockout_seconds
            _GLOBAL["fails"] = 0

        # Opportunistic prune so the per-IP map can't grow without bound.
        if len(_FAILS) > 4096:
            for k in [k for k, (f, u) in _FAILS.items() if f == 0 and u < now]:
                _FAILS.pop(k, None)


def clear(ip) -> None:
    """Drop the per-IP failure record after a successful auth."""
    with _LOCK:
        _FAILS.pop(ip, None)


def rate_limited(key: str, max_hits: int, window: float) -> bool:
    """Generic sliding-window limiter, distinct from the PIN brute-force lock.

    Returns True (and records nothing) when ``key`` has already had
    ``max_hits`` hits within the trailing ``window`` seconds — i.e. THIS hit
    should be rejected. Otherwise records the hit and returns False. Used by the
    kiosk technician-verify endpoint (~10/min/IP) where every probe is a
    legitimate-looking lookup, so the hard PIN lockout would be too blunt."""
    now = time.time()
    with _LOCK:
        hits = [t for t in _HITS.get(key, ()) if now - t < window]
        if len(hits) >= max_hits:
            _HITS[key] = hits
            return True
        hits.append(now)
        _HITS[key] = hits
        # Opportunistic prune so the map can't grow without bound.
        if len(_HITS) > 4096:
            for k in [k for k, v in _HITS.items() if not v or now - v[-1] >= window]:
                _HITS.pop(k, None)
        return False

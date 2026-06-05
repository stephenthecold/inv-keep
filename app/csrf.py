"""CSRF protection — synchroniser-token pattern bound to the session.

A random token is minted once per session and stored under SESSION_KEY in the
SessionMiddleware-backed session cookie. State-changing requests must echo
that token back either in the X-CSRF-Token header (for JSON/AJAX) or in a
hidden ``_csrf`` form field (for plain HTML form POSTs).

This is needed primarily for ``forward`` auth mode, where the proxy attaches
the SSO cookie on every cross-site request without an app-managed cookie to
SameSite-pin; the CSRF token is the only thing the attacker can't read.

Implemented as a pure ASGI middleware (not BaseHTTPMiddleware) so that we
can read the request body, parse out the form field, and then replay the
body to the downstream app via a patched receive callable. With
BaseHTTPMiddleware the inner app sees the original receive, so any body we
consume in middleware is lost to the route handler.
"""

import hmac
import html
import secrets
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

SESSION_KEY = "_csrf"
HEADER = "X-CSRF-Token"
FORM_FIELD = "_csrf"

# Methods that never need CSRF (RFC 7231 safe set).
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Routes that legitimately receive cross-site POSTs we can't tokenize:
# - /auth/callback is the OIDC IdP redirecting the browser back here.
EXEMPT_PATHS = {"/auth/callback"}

# Path PREFIXES exempted from CSRF. The mobile API uses bearer tokens
# (no session cookie -> no CSRF surface) and is authenticated inside the
# router via ``mobile.get_current_tech``.
EXEMPT_PREFIXES = ("/mobile/",)


def issue(request) -> str:
    """Return the session's CSRF token, minting one on first use."""
    tok = request.session.get(SESSION_KEY)
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session[SESSION_KEY] = tok
    return tok


def _failure_response(path: str, referer: str = ""):
    if path.startswith("/api/"):
        return JSONResponse({"ok": False, "error": "csrf"}, status_code=403)
    # Send the user back to the page they came from so a fresh CSRF token is
    # minted and the form re-renders, rather than dead-ending here. Reject
    # anything that isn't an obvious same-origin path — Location header
    # smuggling and open redirects via Referer would otherwise be in play.
    safe_back = "/"
    if referer.startswith("/") and not referer.startswith("//"):
        safe_back = referer
    # The Referer string ultimately comes from the client; escape it before
    # interpolating into HTML attributes so a hostile referer can't break out.
    esc_back = html.escape(safe_back, quote=True)
    return HTMLResponse(
        "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<meta http-equiv='refresh' content='2;url={esc_back}'></head>"
        "<body style='font-family:system-ui;max-width:560px;margin:4rem auto;padding:0 1rem;color:#333'>"
        "<h2>Page expired</h2><p>The page sat too long and its CSRF token aged out — "
        "reloading you to a fresh copy.</p>"
        f"<p><a href='{esc_back}'>Tap here</a> if the page doesn't reload on its own.</p>"
        "</body></html>",
        status_code=403,
    )


class CSRFMiddleware:
    """Pure ASGI middleware. Must sit INSIDE SessionMiddleware so it can read
    ``scope['session']``, and OUTSIDE the route handler (or any other body
    consumer) so its body-replay reaches the handler intact."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")

        if (method in SAFE_METHODS
                or path in EXEMPT_PATHS
                or any(path.startswith(p) for p in EXEMPT_PREFIXES)):
            await self.app(scope, receive, send)
            return

        session = scope.get("session") or {}
        expected = session.get(SESSION_KEY) if isinstance(session, dict) else None

        # Header path first — cheap, no body parsing.
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        submitted = headers.get("x-csrf-token", "")

        # No header — drain & parse the body so form POSTs work.
        body = b""
        consumed = False
        if not submitted:
            ct = headers.get("content-type", "").lower()
            is_form = ct.startswith(("application/x-www-form-urlencoded", "multipart/form-data"))
            if is_form:
                while True:
                    msg = await receive()
                    body += msg.get("body", b"")
                    if not msg.get("more_body"):
                        break
                consumed = True
                if ct.startswith("application/x-www-form-urlencoded"):
                    qs = parse_qs(body.decode("utf-8", "replace"))
                    submitted = (qs.get(FORM_FIELD) or [""])[0]
                else:
                    # Multipart: hand off to Starlette's parser by building a
                    # transient Request that reads from a one-shot replay.
                    req = Request(scope, receive=_one_shot(body))
                    try:
                        form = await req.form()
                        submitted = str(form.get(FORM_FIELD, ""))
                    except Exception:
                        submitted = ""

        ok = (expected
              and submitted
              and hmac.compare_digest(str(submitted), str(expected)))
        if not ok:
            referer = headers.get("referer", "")
            back = ""
            if referer:
                # Strip scheme/host so the user only ever bounces same-origin.
                try:
                    from urllib.parse import urlparse
                    p = urlparse(referer)
                    back = p.path + (("?" + p.query) if p.query else "")
                except Exception:
                    back = ""
            response = _failure_response(path, back)
            await response(scope, receive, send)
            return

        # If we consumed the body, we must replay it to the inner app.
        if consumed:
            await self.app(scope, _one_shot(body), send)
        else:
            await self.app(scope, receive, send)


def _one_shot(body: bytes):
    """Build a one-shot receive() that emits ``body`` once, then disconnects."""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive

"""Authentication, fully driven by UI settings (stored in the DB).

Modes:
  none    -> no login (trusted network / testing)
  oidc    -> log in against any OpenID Connect provider (Authentik, Entra, Okta, …)
  forward -> trust authentication headers injected by a reverse proxy
             (defaults are Authentik's x-authentik-* names; adjust per proxy)

The env var DISABLE_AUTH=1 is a break-glass override that forces `none`, so a
broken OIDC config can never permanently lock you out.
"""

from authlib.integrations.starlette_client import OAuth

from . import rbac
from . import settings_store as store
from .config import settings


def effective_mode(db):
    if settings.disable_auth:
        return "none"
    return store.get(db, "auth_mode") or "none"


def build_oidc(db):
    """Construct an OAuth client from the current DB settings (built per flow)."""
    oauth = OAuth()
    oauth.register(
        name="idp",
        server_metadata_url=store.get(db, "oidc_discovery_url"),
        client_id=store.get(db, "oidc_client_id"),
        client_secret=store.get(db, "oidc_client_secret"),
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


def _kiosk_user(db, pin_id=None):
    """Synthetic auth dict for a PIN-authenticated kiosk session. Loads
    the live perm set from the Kiosk role in the DB so admin edits in
    /users#roles → Kiosk actually take effect; falls back to the
    minimum {view, checkout} floor if the role row is somehow missing.

    When ``pin_id`` is the id of an active KioskPin row, the row's
    per-station username + default location override the globals so each
    POS sees its own slice of /transactions and starts the cart on the
    right location.
    """
    from .models import KioskPin  # local import to keep auth import-light
    username = store.get(db, "kiosk_username") or "kiosk"
    location_id = ""
    pin_label = ""
    if pin_id:
        row = db.get(KioskPin, pin_id)
        if row is not None and row.active:
            username = (row.kiosk_username or "").strip() or username
            location_id = str(row.location_id) if row.location_id else ""
            pin_label = row.label or ""
    if not location_id:
        location_id = store.get(db, "kiosk_location_id") or ""
    role = rbac._role_by_name(db, "Kiosk")
    perms = rbac.perms_for_role(role) if role else {"view", "checkout"}
    return {
        "username": username,
        "email": "",
        "role": "Kiosk",
        "perms": perms,
        "is_admin": False,
        "is_kiosk": True,
        "kiosk_pin_id": pin_id or None,
        "kiosk_pin_label": pin_label,
        "kiosk_location_id": location_id,
    }


def _maybe_impersonate(request, db, user):
    """If the real user is an admin AND has set an impersonate role in the
    session, return a downgraded dict. Otherwise return ``user`` unchanged."""
    if not user or not user.get("is_admin"):
        return user
    target = (request.session.get("impersonate_role") or "").strip()
    if not target:
        return user
    role = rbac._role_by_name(db, target)
    if not role:
        return user
    return {
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "role": role.name,
        "perms": rbac.perms_for_role(role),
        "is_admin": bool(role.is_admin),
        "is_impersonating": True,
        "real_role": user.get("role", "Admin"),
    }


def resolve_user(request, db):
    """Return the auth dict (username/email/role/perms/is_admin) or None."""
    mode = effective_mode(db)

    if mode == "none":
        # Single-user / break-glass: full admin.
        return _maybe_impersonate(request, db, rbac.admin_dict("local"))

    if mode == "forward":
        header = store.get(db, "forward_auth_user_header") or "x-authentik-username"
        email_header = store.get(db, "forward_auth_email_header") or "x-authentik-email"
        groups_header = store.get(db, "forward_auth_groups_header") or "x-authentik-groups"
        username = request.headers.get(header)
        if not username:
            # Real proxy auth missed — but a kiosk PIN session may still be live.
            if request.session.get("kiosk") and store.get_bool(db, "kiosk_enabled"):
                return _kiosk_user(db, request.session.get("kiosk_pin_id"))
            return None
        email = request.headers.get(email_header, "")
        raw_groups = request.headers.get(groups_header, "")
        groups = [g.strip() for g in raw_groups.replace(";", ",").split(",") if g.strip()]
        return _maybe_impersonate(request, db, rbac.resolve_login(db, username, email, groups))

    if mode == "oidc":
        sess = request.session.get("user")
        if not sess:
            if request.session.get("kiosk") and store.get_bool(db, "kiosk_enabled"):
                return _kiosk_user(db, request.session.get("kiosk_pin_id"))
            return None
        return _maybe_impersonate(
            request, db,
            rbac.resolve_login(db, sess.get("username", ""), sess.get("email", ""), sess.get("groups", [])),
        )

    return None

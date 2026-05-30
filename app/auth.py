"""Authentication, fully driven by UI settings (stored in the DB).

Modes:
  none    -> no login (trusted network / testing)
  oidc    -> log in against Authentik (or any OpenID Connect provider)
  forward -> trust X-authentik-* headers injected by a reverse-proxy outpost

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


def resolve_user(request, db):
    """Return the auth dict (username/email/role/perms/is_admin) or None."""
    mode = effective_mode(db)

    if mode == "none":
        # Single-user / break-glass: full admin.
        return rbac.admin_dict("local")

    if mode == "forward":
        header = store.get(db, "forward_auth_user_header") or "x-authentik-username"
        email_header = store.get(db, "forward_auth_email_header") or "x-authentik-email"
        groups_header = store.get(db, "forward_auth_groups_header") or "x-authentik-groups"
        username = request.headers.get(header)
        if not username:
            return None
        email = request.headers.get(email_header, "")
        raw_groups = request.headers.get(groups_header, "")
        groups = [g.strip() for g in raw_groups.replace(";", ",").split(",") if g.strip()]
        return rbac.resolve_login(db, username, email, groups)

    if mode == "oidc":
        sess = request.session.get("user")
        if not sess:
            return None
        return rbac.resolve_login(db, sess.get("username", ""), sess.get("email", ""), sess.get("groups", []))

    return None

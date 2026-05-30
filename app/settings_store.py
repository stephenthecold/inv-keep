"""DB-backed, UI-editable settings with sane defaults.

Only the values needed to *bootstrap* the app (SESSION_SECRET, DATABASE_URL) and
the break-glass DISABLE_AUTH flag stay in the environment. Everything else —
including the auth mode and Authentik/OIDC config — lives here and is editable in
the Settings UI. The env AUTH_MODE / OIDC_* values are used only to seed the
defaults on first run.
"""

from .config import settings as env_settings
from .models import Setting

DEFAULTS = {
    "app_title": env_settings.app_title,
    "currency": env_settings.currency,
    "low_stock_threshold": "5",
    # Default label size preset key (see app/labels.py LABEL_SIZES)
    "label_size": "sheet",
    # White-label branding
    "brand_accent": "",        # hex colour, e.g. #2f81f7 (blank = default)
    "brand_logo": "",          # served path under /uploads, e.g. /uploads/logo.png
    "brand_emoji": "📦",       # shown when no logo image is set
    "brand_footer": "",        # optional footer text
    # Authentication (UI-managed). Seeded from env on first run.
    "auth_mode": env_settings.auth_mode,  # none | oidc | forward
    "oidc_discovery_url": env_settings.oidc_discovery_url,
    "oidc_client_id": env_settings.oidc_client_id,
    "oidc_client_secret": env_settings.oidc_client_secret,
    "oidc_redirect_url": env_settings.oidc_redirect_url,
    "forward_auth_user_header": env_settings.forward_auth_user_header,
    "forward_auth_email_header": env_settings.forward_auth_email_header,
    # Email
    "email_method": "none",  # none | smtp | oauth_microsoft | oauth_google
    "email_from": "",
    "email_from_name": "Inv-Keep",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_use_tls": "1",
    "oauth_client_id": "",
    "oauth_client_secret": "",
    "oauth_tenant": "common",  # Microsoft tenant id or "common"
    "oauth_refresh_token": "",
    "oauth_access_token": "",
    "oauth_token_expiry": "0",  # epoch seconds
    # Alerts
    "alert_low_stock_enabled": "0",
    "alert_low_stock_recipients": "",
    "alert_monthly_enabled": "0",
    "alert_monthly_day": "1",
    "alert_monthly_recipients": "",
    "alert_monthly_last_sent": "",  # YYYY-MM that was last emailed
}

SECRET_KEYS = {
    "smtp_password",
    "oauth_client_secret",
    "oauth_refresh_token",
    "oauth_access_token",
    "oidc_client_secret",
}


def get(db, key, default=None):
    row = db.get(Setting, key)
    if row is not None and row.value is not None:
        return row.value
    return DEFAULTS.get(key, "" if default is None else default)


def get_int(db, key, default=0):
    try:
        return int(get(db, key))
    except (TypeError, ValueError):
        return default


def get_bool(db, key):
    return get(db, key) in ("1", "true", "True", "on", "yes")


def set(db, key, value):
    row = db.get(Setting, key)
    if value is None:
        value = ""
    if row is None:
        db.add(Setting(key=key, value=str(value)))
    else:
        row.value = str(value)


def all_settings(db):
    """Merged dict of defaults + stored values (for templates)."""
    merged = dict(DEFAULTS)
    for row in db.query(Setting).all():
        merged[row.key] = row.value
    return merged

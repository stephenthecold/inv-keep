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
    "label_barcode_type": "code128",   # code128 | qr
    # Label content toggles + custom text (what prints on each label)
    "label_show_icon": "1",
    "label_show_name": "1",
    "label_show_code_text": "1",   # human-readable digits under the barcode
    "label_show_price": "0",
    "label_show_description": "0",
    "label_show_category": "0",
    "label_company_text": "",      # printed at the top of every label (e.g. company name)
    "label_extra_text": "",        # printed at the bottom of every label
    # Android TWA Digital Asset Links JSON (served at /.well-known/assetlinks.json)
    "android_asset_links": "",
    # White-label branding
    "brand_accent": "",        # hex colour, e.g. #2f81f7 (blank = default)
    "brand_logo": "",          # served path under /uploads, e.g. /uploads/logo.png
    "brand_emoji": "📦",       # shown when no logo image is set
    "brand_show_title": "1",   # show the app-title text next to the logo
    "brand_footer": "",        # optional footer text
    # Authentication (UI-managed). Seeded from env on first run.
    "auth_mode": env_settings.auth_mode,  # none | oidc | forward
    "oidc_discovery_url": env_settings.oidc_discovery_url,
    "oidc_client_id": env_settings.oidc_client_id,
    "oidc_client_secret": env_settings.oidc_client_secret,
    "oidc_redirect_url": env_settings.oidc_redirect_url,
    "forward_auth_user_header": env_settings.forward_auth_user_header,
    "forward_auth_email_header": env_settings.forward_auth_email_header,
    # RBAC (users / roles / group mapping)
    "rbac_default_role": "Admin",     # role for IdP users with no group match (Admin = permissive default)
    "rbac_admin_emails": "",          # comma-separated emails always granted Admin
    "rbac_auto_create": "1",          # auto-create a user record on first IdP login
    "oidc_groups_claim": "groups",    # claim holding the user's groups
    "oidc_group_role_map": "",        # lines "group = RoleName"
    "forward_auth_groups_header": "x-authentik-groups",
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
    "alert_monthly_hour": "6",
    "alert_monthly_recipients": "",
    "alert_monthly_last_sent": "",  # YYYY-MM that was last emailed
    "alert_weekly_enabled": "0",
    "alert_weekly_weekday": "0",    # 0=Mon … 6=Sun
    "alert_weekly_hour": "6",
    "alert_weekly_recipients": "",
    "alert_weekly_last_sent": "",
    "alert_daily_enabled": "0",
    "alert_daily_hour": "6",
    "alert_daily_recipients": "",
    "alert_daily_last_sent": "",
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

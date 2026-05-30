# Configuration reference

Inv-Keep is configured in two layers:

1. **Environment variables** — only what's needed to boot securely. Set in `.env`
   (Docker Compose reads it via `env_file`) or the process environment.
2. **In-app settings** — everything else, edited under **Settings** in the UI and
   stored in the database. The relevant env vars below are read **once** to seed
   the defaults on a brand-new database.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:////code/data/app.db` | SQLAlchemy URL. SQLite is the default; the file lives on the mounted `./data` volume. |
| `SESSION_SECRET` | _(change me)_ | Secret used to sign the login session cookie. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `DISABLE_AUTH` | `false` | **Break-glass.** If `1`/`true`, all authentication is bypassed regardless of UI settings. Use to recover from an OIDC lock-out, then unset. |
| `APP_TITLE` | `Inv-Keep` | Seed only: initial app title (then edit in Settings → General). |
| `CURRENCY` | `$` | Seed only: initial currency symbol. |
| `AUTH_MODE` | `none` | Seed only: initial auth mode (`none` / `oidc` / `forward`). |
| `OIDC_DISCOVERY_URL` | _(empty)_ | Seed only: OpenID Connect discovery URL. |
| `OIDC_CLIENT_ID` | _(empty)_ | Seed only: OIDC client ID. |
| `OIDC_CLIENT_SECRET` | _(empty)_ | Seed only: OIDC client secret. |
| `OIDC_REDIRECT_URL` | _(empty)_ | Seed only: redirect URL override (behind a proxy). |
| `FORWARD_AUTH_USER_HEADER` | `x-authentik-username` | Seed only: header carrying the username in forward-auth mode. |
| `FORWARD_AUTH_EMAIL_HEADER` | `x-authentik-email` | Seed only: header carrying the email in forward-auth mode. |

---

## In-app settings (Settings page → database)

### General
| Setting | Default | Notes |
|---|---|---|
| `app_title` | `Inv-Keep` | Shown in header, title bar, footer, PWA name. |
| `currency` | `$` | Symbol prefixed to all amounts. |
| `low_stock_threshold` | `5` | Global default; each item can override it. |

### Printing
| Setting | Default | Notes |
|---|---|---|
| `label_size` | `sheet` | Default label preset. Keys: `sheet`, `rollo-4x6`, `asset-57x32`, `50x25`, `ql-62x29`, `ql-62-cont`, `ptouch-24`, `ptouch-18`, `ptouch-12`. See [docs/PRINTING.md](docs/PRINTING.md). |

### White-label / Branding
| Setting | Default | Notes |
|---|---|---|
| `brand_accent` | _(empty)_ | Hex colour, e.g. `#16a34a`. Overrides the accent across the whole app (and PWA theme). |
| `brand_emoji` | `📦` | Shown in the header when no logo is uploaded. |
| `brand_logo` | _(empty)_ | Path to an uploaded logo (`/uploads/...`). Upload/remove in Settings. |
| `brand_footer` | _(empty)_ | Optional footer text. |

### Authentication
| Setting | Default | Notes |
|---|---|---|
| `auth_mode` | `none` | `none` / `oidc` / `forward`. |
| `oidc_discovery_url` / `oidc_client_id` / `oidc_client_secret` / `oidc_redirect_url` | _(empty)_ | OIDC (Authentik) settings. |
| `forward_auth_user_header` / `forward_auth_email_header` | `x-authentik-*` | Header names trusted in forward-auth mode. |

### Email
| Setting | Default | Notes |
|---|---|---|
| `email_method` | `none` | `none` / `smtp` / `oauth_microsoft` / `oauth_google`. |
| `email_from` / `email_from_name` | _(empty)_ / `Inv-Keep` | Sender identity. |
| `smtp_host` / `smtp_port` / `smtp_username` / `smtp_password` / `smtp_use_tls` | _(empty)_ / `587` / … / `1` | SMTP settings. |
| `oauth_client_id` / `oauth_client_secret` / `oauth_tenant` | _(empty)_ / `common` | OAuth2 app credentials (Microsoft/Google). |
| `oauth_refresh_token` / `oauth_access_token` / `oauth_token_expiry` | _(managed)_ | Stored automatically after **Connect mailbox**. |

### Alerts
| Setting | Default | Notes |
|---|---|---|
| `alert_low_stock_enabled` | `0` | Email when an item drops to/under its threshold. |
| `alert_low_stock_recipients` | _(empty)_ | Comma-separated recipients. |
| `alert_monthly_enabled` | `0` | Email the monthly report automatically. |
| `alert_monthly_day` | `1` | Day of month (1–28) to send. |
| `alert_monthly_recipients` | _(empty)_ | Comma-separated recipients. |
| `alert_monthly_last_sent` | _(managed)_ | Internal de-dupe marker (`YYYY-MM`). |

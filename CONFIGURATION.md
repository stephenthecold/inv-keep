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
| `HOSTNAME` | `localhost` | Public hostname (used by the SSL proxy and OIDC redirect URLs). |
| `APP_PORT` | `8000` | Host port for direct access → `http://HOSTNAME:APP_PORT`. |
| `ACME_EMAIL` | `admin@example.com` | Let's Encrypt contact email when the bundled SSL proxy is enabled. |
| `CADDY_CONFIG` | `./Caddyfile` | Which Caddy config the `ssl` profile mounts: `./Caddyfile` (Let's Encrypt) or `./Caddyfile.custom` (your own cert in `certs/`). |
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
| `label_size` | `sheet` | Default label preset, grouped by brand (Brother/DYMO/Zebra/Rollo). See [docs/PRINTING.md](docs/PRINTING.md). |
| `label_show_icon` / `label_show_name` / `label_show_code_text` | `1` / `1` / `1` | Toggle the item icon, name, and human-readable barcode digits on each label. |
| `label_show_price` / `label_show_description` / `label_show_category` | `0` | Optionally add the client price, description, or category to each label. |
| `label_company_text` | _(empty)_ | Header line printed on every label (e.g. company name). |
| `label_extra_text` | _(empty)_ | Footer line printed on every label. |
| `android_asset_links` | _(empty)_ | Digital Asset Links JSON served at `/.well-known/assetlinks.json` for the TWA APK. |

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

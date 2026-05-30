from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_title: str = "Inv-Keep"
    currency: str = "$"
    database_url: str = "sqlite:////code/data/app.db"
    session_secret: str = "change-me-generate-a-random-value"

    # Break-glass: if true, ALL auth is bypassed regardless of UI settings.
    # Use this to recover access if an OIDC misconfiguration locks you out.
    disable_auth: bool = False

    # none | oidc | forward  — only used to SEED the UI settings on first run.
    auth_mode: str = "none"

    oidc_discovery_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_url: str = ""

    forward_auth_user_header: str = "x-authentik-username"
    forward_auth_email_header: str = "x-authentik-email"


settings = Settings()

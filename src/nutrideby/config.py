from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql://nutrideby:nutrideby_dev@localhost:5432/nutrideby",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    crm_base_url: str | None = None
    crm_username: str | None = None
    crm_password: str | None = None
    crm_login_user_selector: str | None = None
    crm_login_password_selector: str | None = None
    crm_login_submit_selector: str | None = None

    deepseek_api_key: str | None = None
    deepseek_api_base: str = "https://api.deepseek.com"

    genai_agent_url: str | None = None
    genai_agent_access_key: str | None = None

    playwright_headless: bool = True
    playwright_storage_state: str | None = None

    # Dietbox: API JSON + site (fórmulas MVC — mesmo Bearer na prática)
    dietbox_api_base: str = "https://api.dietbox.me"
    dietbox_bearer_token: str | None = None
    dietbox_web_base: str = "https://dietbox.me"
    dietbox_web_locale: str = "pt-BR"

    # API leitura interna (Sprint 2) — se vazio, /v1/* fica sem auth (só para dev)
    nutrideby_api_key: str | None = None

    # Opcional: POST JSON quando ``dietbox_sync --smoke`` detectar HTTP 401 (Slack incoming webhook, etc.)
    nutrideby_smoke_alert_webhook_url: str | None = None

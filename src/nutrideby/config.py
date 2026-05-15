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

    # Cache L1 (Redis): embedding da query em /retrieve — reduz chamadas OpenAI em perguntas repetidas
    retrieve_embedding_cache_enabled: bool = Field(default=True)
    retrieve_embedding_cache_ttl_seconds: int = Field(
        default=604800,
        description="TTL do vector da query em Redis (default 7 dias).",
    )

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

    # DigitalOcean Spaces — data lake (JSON de análise; Postgres guarda só a URL)
    spaces_access_key_id: str | None = None
    spaces_secret_access_key: str | None = None
    spaces_bucket: str = "nutridebv2"
    spaces_region: str = "lon1"
    spaces_endpoint: str = "https://lon1.digitaloceanspaces.com"

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

    # Kiwify → URL no painel: POST …/hooks/kiwify/<este_segredo> (sem partilhar em público)
    kiwify_webhook_path_secret: str | None = None

    # Embeddings OpenAI-compatible (Plano B — ver docs/decisao-embeddings-vector-store.md)
    openai_api_key: str | None = None
    openai_api_base: str = "https://api.openai.com"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = Field(
        default="gpt-4o-mini",
        description="Modelo para /v1/patients/.../analyze quando use_genai=false ou GenAI indisponível.",
    )

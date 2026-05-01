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

    deepseek_api_key: str | None = None
    deepseek_api_base: str = "https://api.deepseek.com"

    # DigitalOcean GenAI — agente RAG; ver README e docs/execucao-plano-integracao.md
    genai_agent_url: str | None = None
    genai_agent_access_key: str | None = None

    playwright_headless: bool = True
    playwright_storage_state: str | None = None

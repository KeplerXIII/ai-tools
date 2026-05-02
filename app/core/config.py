from dataclasses import dataclass

from pydantic_settings import BaseSettings

from app.core.llm_task import LLMTask


@dataclass(frozen=True, slots=True)
class OpenAIEndpoint:
    base_url: str
    api_key: str


class Settings(BaseSettings):
    # --- app ---
    app_name: str = "AI Tools Service"
    app_version: str = "0.1.0"
    debug: bool = False

    # --- limits ---
    # HTTP-загрузка страницы и навигация Playwright при /extract (секунды)
    request_timeout: int = 45
    max_html_length: int = 10_000_000

    # --- OpenAI-compatible API (default for all tasks unless overridden below) ---
    openai_compat_base_url: str = "https://api.deepseek.com"
    openai_compat_api_key: str

    # --- per-task overrides (optional; unset inherits default above) ---
    openai_compat_base_url_summary: str | None = None
    openai_compat_api_key_summary: str | None = None

    openai_compat_base_url_summary_refine: str | None = None
    openai_compat_api_key_summary_refine: str | None = None

    openai_compat_base_url_translation: str | None = None
    openai_compat_api_key_translation: str | None = None

    openai_compat_base_url_tagging: str | None = None
    openai_compat_api_key_tagging: str | None = None

    openai_compat_base_url_entity_extraction: str | None = None
    openai_compat_api_key_entity_extraction: str | None = None

    # --- runtime ---
    llm_timeout: int = 120

    # --- database (async SQLAlchemy; URL вида postgresql+asyncpg://user:pass@host:5432/db) ---
    database_url: str

    # --- JWT ---
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # --- SQLAdmin session (если не задан — используется jwt_secret_key) ---
    admin_session_secret: str | None = None

    # --- models by task ---
    model_summary: str = "deepseek-v4-pro"
    model_summary_refine: str = "deepseek-v4-pro"
    model_translation: str = "deepseek-v4-pro"
    model_tagging: str = "deepseek-v4-pro"
    model_entity_extraction: str = "deepseek-v4-pro"

    def openai_endpoint_for(self, task: LLMTask) -> OpenAIEndpoint:
        suffix = task.value
        base = getattr(self, f"openai_compat_base_url_{suffix}", None) or self.openai_compat_base_url
        key = getattr(self, f"openai_compat_api_key_{suffix}", None) or self.openai_compat_api_key
        return OpenAIEndpoint(base_url=base, api_key=key)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

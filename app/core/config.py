from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- app ---
    app_name: str = "AI Tools Service"
    app_version: str = "0.1.0"
    debug: bool = False

    # --- limits ---
    request_timeout: int = 20
    max_html_length: int = 10_000_000

    # --- openai-compatible provider ---
    openai_compat_base_url: str = "http://172.20.0.1:11434/v1"
    openai_compat_api_key: str = "ollama"

    # --- openrouter ---
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_name: str = "ai-tools"
    openrouter_site_url: str | None = None

    # --- runtime ---
    llm_timeout: int = 120
    llm_provider: str = "openrouter"  # openrouter | openai_sdk

    # --- models by task ---
    model_summary: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    model_summary_refine: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    model_translation: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    model_tagging: str = "qwen2.5:3b-instruct"
    model_entity_extraction: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
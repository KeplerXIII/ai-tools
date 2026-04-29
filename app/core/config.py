from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- app ---
    app_name: str = "AI Tools Service"
    app_version: str = "0.1.0"
    debug: bool = False

    # --- limits ---
    request_timeout: int = 20
    max_html_length: int = 10_000_000

    # --- ollama / local ---
    ollama_base_url: str = "http://172.20.0.1:11434"
    llm_openai_url: str = "http://172.20.0.1:11434/v1"
    llm_openai_api_key: str = "ollama"

    # --- openrouter ---
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_name: str = "ai-tools"
    openrouter_site_url: str | None = None

    # --- endpoints ---
    llm_url: str = "http://172.20.0.1:11434/v1/chat/completions"
    ollama_url: str = "http://172.20.0.1:11434/api/chat"

    # --- runtime ---
    llm_timeout: int = 120

    # --- models ---
    llm_model: str = "qwen3:14b"
    translate_model: str = "translategemma:12b"
    light_model: str = "qwen2.5:3b-instruct"
    openrouter_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
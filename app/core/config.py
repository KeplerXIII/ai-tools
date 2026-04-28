from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AI Tools Service"
    app_version: str = "0.1.0"
    debug: bool = False

    request_timeout: int = 20
    max_html_length: int = 10000000

    # === OpenAI SDK (unified transport) ===
    llm_openai_url: str = "http://172.20.0.1:11434/v1"
    llm_openai_api_key: str = "ollama" #просто потому что на серваке в данный момент оллама
    
    # === OpenAI-compatible===
    llm_url: str = "http://172.20.0.1:11434/v1/chat/completions"

    # === Native Ollama ===
    ollama_url: str = "http://172.20.0.1:11434/api/chat"
    llm_timeout: int = 120

    # модели
    llm_model: str = "qwen3:14b"
    translate_model: str = "translategemma:12b"
    light_model: str = "qwen2.5:3b-instruct"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
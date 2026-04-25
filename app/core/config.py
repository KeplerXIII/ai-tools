from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "AI Tools Service"
    app_version: str = "0.1.0"
    debug: bool = False

    request_timeout: int = 20
    max_html_length: int = 200_000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
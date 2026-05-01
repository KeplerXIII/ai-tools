from functools import lru_cache

from app.core.config import settings
from app.domain.errors import ValidationError
from app.infrastructure.llm.openai_sdk_adapter import OpenAISDKLLMAdapter
from app.infrastructure.llm.openrouter_adapter import OpenRouterLLMAdapter
from app.ports.llm import LLMPort


@lru_cache(maxsize=1)
def get_llm_client() -> LLMPort:
    provider = settings.llm_provider.strip().lower()

    if provider == "openrouter":
        return OpenRouterLLMAdapter()

    if provider == "openai_sdk":
        return OpenAISDKLLMAdapter()

    raise ValidationError(
        f"Неизвестный llm_provider='{settings.llm_provider}'. "
        "Доступно: openrouter, openai_sdk."
    )

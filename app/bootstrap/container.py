from functools import lru_cache

from app.core.config import settings
from app.core.llm_task import LLMTask
from app.infrastructure.llm.clients.openai_sdk_client import openai_client_for_endpoint
from app.infrastructure.llm.openai_sdk_adapter import OpenAISDKLLMAdapter
from app.ports.llm import LLMPort


@lru_cache(maxsize=len(tuple(LLMTask)))
def get_llm_client(task: LLMTask) -> LLMPort:
    endpoint = settings.openai_endpoint_for(task)
    client = openai_client_for_endpoint(endpoint)
    return OpenAISDKLLMAdapter(client)

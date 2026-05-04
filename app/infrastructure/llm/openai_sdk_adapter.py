from collections.abc import AsyncIterator

from fastapi import HTTPException
from openai import AsyncOpenAI

from app.domain.errors import ExternalServiceError
from app.infrastructure.llm.clients.openai_sdk_client import achat
from app.ports.llm import LLMPort, LLMRequest


class OpenAISDKLLMAdapter(LLMPort):
    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    async def chat(self, request: LLMRequest) -> str | AsyncIterator[str]:
        try:
            return await achat(
                self._client,
                prompt=request.prompt,
                model=request.model,
                temperature=request.temperature,
                meta=request.meta or None,
                stream=request.stream,
                max_tokens=request.max_tokens,
            )
        except HTTPException as exc:
            raise ExternalServiceError(str(exc.detail)) from exc

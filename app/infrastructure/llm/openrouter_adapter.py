from typing import Generator

from fastapi import HTTPException

from app.domain.errors import ExternalServiceError
from app.infrastructure.llm.clients.openrouter_client import chat
from app.ports.llm import LLMPort, LLMRequest


class OpenRouterLLMAdapter(LLMPort):
    def chat(self, request: LLMRequest) -> str | Generator[str, None, None]:
        try:
            return chat(
                prompt=request.prompt,
                model=request.model,
                temperature=request.temperature,
                stream=request.stream,
                max_tokens=request.max_tokens,
                meta=request.meta or None,
            )
        except HTTPException as exc:
            raise ExternalServiceError(str(exc.detail)) from exc

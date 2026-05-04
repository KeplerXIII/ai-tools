from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class LLMRequest:
    prompt: str
    model: str
    temperature: float = 0
    stream: bool = False
    max_tokens: int | None = None
    meta: dict = field(default_factory=dict)


class LLMPort(Protocol):
    async def chat(self, request: LLMRequest) -> str | AsyncIterator[str]:
        ...

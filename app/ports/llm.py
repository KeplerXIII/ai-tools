from dataclasses import dataclass, field
from typing import Generator, Protocol


@dataclass(slots=True)
class LLMRequest:
    prompt: str
    model: str
    temperature: float = 0
    stream: bool = False
    max_tokens: int | None = None
    meta: dict = field(default_factory=dict)


class LLMPort(Protocol):
    def chat(self, request: LLMRequest) -> str | Generator[str, None, None]:
        ...

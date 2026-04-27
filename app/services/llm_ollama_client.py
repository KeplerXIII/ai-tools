import requests
from fastapi import HTTPException

from app.core.config import settings


def chat_structured(
    prompt: str,
    schema: dict,
    model: str,
    temperature: float = 0,
) -> dict:
    try:
        response = requests.post(
            settings.ollama_url,  # http://172.20.0.1:11434/api/chat
            json={
                "model": model,
                "stream": False,
                "format": schema,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "options": {
                    "temperature": temperature,
                },
            },
            timeout=settings.llm_timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama ошибка: {exc}",
        )

    try:
        content = response.json()["message"]["content"].strip()
    except (KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama некорректный ответ: {exc}",
        )

    # Ollama возвращает JSON как строку → парсим
    import json

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama вернула невалидный JSON: {exc}",
        )
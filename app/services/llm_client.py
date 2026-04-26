import requests
from fastapi import HTTPException

from app.core.config import settings


def chat(prompt: str, model: str, temperature: float = 0) -> str:
    try:
        response = requests.post(
            settings.llm_url,
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "temperature": temperature,
            },
            timeout=settings.llm_timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка обращения к LLM: {exc}",
        )

    try:
        return response.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Некорректный ответ LLM: {exc}",
        )

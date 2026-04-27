import time
import logging
import requests

from fastapi import HTTPException

from app.core.config import settings


logger = logging.getLogger("llm")


def chat(
    prompt: str,
    model: str,
    temperature: float = 0,
    meta: dict | None = None,
) -> str:
    start_time = time.time()

    logger.info(
        {
            "event": "llm_request",
            "model": model,
            #"prompt_preview": prompt[:300],
            "prompt_preview": "...",
            "prompt_chars": len(prompt),
            "temperature": temperature,
            "meta": meta,
        }
    )

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

        duration = time.time() - start_time
        response.raise_for_status()

    except requests.RequestException as exc:
        duration = time.time() - start_time

        logger.error(
            {
                "event": "llm_error",
                "model": model,
                "duration_sec": round(duration, 3),
                "prompt_chars": len(prompt),
                "temperature": temperature,
                "meta": meta,
                "error": str(exc),
            }
        )

        raise HTTPException(
            status_code=502,
            detail=f"Ошибка обращения к LLM: {exc}",
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        if not content or not content.strip():
            logger.error(
                {
                    "event": "llm_empty_response",
                    "model": model,
                    "duration_sec": round(duration, 3),
                    "prompt_chars": len(prompt),
                    "meta": meta,
                }
            )
            raise HTTPException(
                status_code=502,
                detail="LLM вернула пустой ответ",
            )

        content = content.strip()

    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.error(
            {
                "event": "llm_parse_error",
                "model": model,
                "duration_sec": round(duration, 3),
                "prompt_chars": len(prompt),
                "temperature": temperature,
                "meta": meta,
                "raw_response": response.text[:1000],
                "error": str(exc),
            }
        )

        raise HTTPException(
            status_code=502,
            detail=f"Некорректный ответ LLM: {exc}",
        )

    logger.info(
        {
            "event": "llm_success",
            "model": model,
            "duration_sec": round(duration, 3),
            "prompt_chars": len(prompt),
            "response_chars": len(content),
            "temperature": temperature,
            "meta": meta,
        }
    )

    return content
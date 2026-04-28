import time
import json
import logging
import requests

from typing import Generator
from fastapi import HTTPException

from app.core.config import settings


logger = logging.getLogger("llm")


def _build_options(
    temperature: float = 0,
    num_predict: int | None = None,
    num_gpu: int | None = None,
    options: dict | None = None,
) -> dict:
    result = {}

    if options:
        result.update(options)

    result["temperature"] = temperature

    if num_predict is not None:
        result["num_predict"] = num_predict

    if num_gpu is not None:
        result["num_gpu"] = num_gpu

    return result


def chat(
    prompt: str,
    model: str,
    temperature: float = 0,
    meta: dict | None = None,
    stream: bool = False,
    num_predict: int | None = None,
    num_gpu: int | None = None,
    options: dict | None = None,
) -> str | Generator[str, None, None]:
    if stream:
        return _chat_stream(
            prompt=prompt,
            model=model,
            temperature=temperature,
            meta=meta,
            num_predict=num_predict,
            num_gpu=num_gpu,
            options=options,
        )

    return _chat_full(
        prompt=prompt,
        model=model,
        temperature=temperature,
        meta=meta,
        num_predict=num_predict,
        num_gpu=num_gpu,
        options=options,
    )


def _chat_full(
    prompt: str,
    model: str,
    temperature: float = 0,
    meta: dict | None = None,
    num_predict: int | None = None,
    num_gpu: int | None = None,
    options: dict | None = None,
) -> str:
    start_time = time.time()

    request_options = _build_options(
        temperature=temperature,
        num_predict=num_predict,
        num_gpu=num_gpu,
        options=options,
    )

    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": request_options,
    }

    logger.info(
        {
            "event": "llm_request",
            "model": model,
            "prompt_preview": "...",
            "prompt_chars": len(prompt),
            "temperature": temperature,
            "num_predict": num_predict,
            "num_gpu": num_gpu,
            "stream": False,
            "meta": meta,
        }
    )

    try:
        response = requests.post(
            settings.llm_url,
            json=body,
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
                "num_predict": num_predict,
                "num_gpu": num_gpu,
                "stream": False,
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
            raise ValueError("empty content")

        content = content.strip()

    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.error(
            {
                "event": "llm_parse_error",
                "model": model,
                "duration_sec": round(duration, 3),
                "prompt_chars": len(prompt),
                "temperature": temperature,
                "num_predict": num_predict,
                "num_gpu": num_gpu,
                "stream": False,
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
            "num_predict": num_predict,
            "num_gpu": num_gpu,
            "stream": False,
            "meta": meta,
        }
    )

    return content


def _chat_stream(
    prompt: str,
    model: str,
    temperature: float = 0,
    meta: dict | None = None,
    num_predict: int | None = None,
    num_gpu: int | None = None,
    options: dict | None = None,
) -> Generator[str, None, None]:
    start_time = time.time()
    first_token_time = None
    total_chars = 0

    request_options = _build_options(
        temperature=temperature,
        num_predict=num_predict,
        num_gpu=num_gpu,
        options=options,
    )

    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": True,
        "options": request_options,
    }

    logger.info(
        {
            "event": "llm_stream_request",
            "model": model,
            "prompt_preview": "...",
            "prompt_chars": len(prompt),
            "temperature": temperature,
            "num_predict": num_predict,
            "num_gpu": num_gpu,
            "stream": True,
            "meta": meta,
        }
    )

    response = None

    try:
        response = requests.post(
            settings.llm_url,
            json=body,
            timeout=settings.llm_timeout,
            stream=True,
        )

        response.raise_for_status()

        for line in response.iter_lines():
            if not line:
                continue

            if line.startswith(b"data: "):
                line = line[len(b"data: "):]

            if line == b"[DONE]":
                break

            try:
                data = json.loads(line)
                delta = data["choices"][0]["delta"].get("content", "")

                if not delta:
                    continue

                if first_token_time is None:
                    first_token_time = time.time()

                    logger.info(
                        {
                            "event": "llm_stream_first_token",
                            "model": model,
                            "ttft_sec": round(first_token_time - start_time, 3),
                            "prompt_chars": len(prompt),
                            "temperature": temperature,
                            "num_predict": num_predict,
                            "num_gpu": num_gpu,
                            "meta": meta,
                        }
                    )

                total_chars += len(delta)
                yield delta

            except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
                continue

        duration = time.time() - start_time

        logger.info(
            {
                "event": "llm_stream_success",
                "model": model,
                "duration_sec": round(duration, 3),
                "ttft_sec": round(first_token_time - start_time, 3)
                if first_token_time
                else None,
                "prompt_chars": len(prompt),
                "response_chars": total_chars,
                "temperature": temperature,
                "num_predict": num_predict,
                "num_gpu": num_gpu,
                "stream": True,
                "meta": meta,
            }
        )

    except requests.RequestException as exc:
        duration = time.time() - start_time

        logger.error(
            {
                "event": "llm_stream_error",
                "model": model,
                "duration_sec": round(duration, 3),
                "prompt_chars": len(prompt),
                "temperature": temperature,
                "num_predict": num_predict,
                "num_gpu": num_gpu,
                "stream": True,
                "meta": meta,
                "error": str(exc),
            }
        )

        raise HTTPException(
            status_code=502,
            detail=f"Ошибка обращения к LLM stream: {exc}",
        )

    finally:
        if response is not None:
            response.close()
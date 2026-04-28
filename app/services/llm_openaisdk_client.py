import time
import logging

from typing import Generator
from fastapi import HTTPException
from openai import OpenAI, OpenAIError

from app.core.config import settings


logger = logging.getLogger("llm")


def _get_client() -> OpenAI:
    return OpenAI(
        base_url=settings.llm_openai_url,
        api_key=settings.llm_openai_api_key,
        timeout=settings.llm_timeout,
    )


def _build_extra_body(
    num_predict: int | None = None,
    num_gpu: int | None = None,
    options: dict | None = None,
) -> dict:
    extra_body = {}

    if options:
        extra_body.update(options)

    if num_predict is not None:
        extra_body["num_predict"] = num_predict

    if num_gpu is not None:
        extra_body["num_gpu"] = num_gpu

    return extra_body


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

    client = _get_client()

    extra_body = _build_extra_body(
        num_predict=num_predict,
        num_gpu=num_gpu,
        options=options,
    )

    logger.info(
        {
            "event": "llm_request",
            "transport": "openai_sdk",
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
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=num_predict,
            stream=False,
            extra_body=extra_body or None,
        )

        duration = time.time() - start_time
        content = completion.choices[0].message.content

        if not content or not content.strip():
            raise ValueError("empty content")

        content = content.strip()

    except (OpenAIError, ValueError, KeyError, IndexError, TypeError) as exc:
        duration = time.time() - start_time

        logger.error(
            {
                "event": "llm_error",
                "transport": "openai_sdk",
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

    logger.info(
        {
            "event": "llm_success",
            "transport": "openai_sdk",
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

    client = _get_client()

    extra_body = _build_extra_body(
        num_predict=num_predict,
        num_gpu=num_gpu,
        options=options,
    )

    logger.info(
        {
            "event": "llm_stream_request",
            "transport": "openai_sdk",
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

    try:
        stream_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=num_predict,
            stream=True,
            extra_body=extra_body or None,
        )

        for chunk in stream_response:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta.content or ""

            if not delta:
                continue

            if first_token_time is None:
                first_token_time = time.time()

                logger.info(
                    {
                        "event": "llm_stream_first_token",
                        "transport": "openai_sdk",
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

        duration = time.time() - start_time

        logger.info(
            {
                "event": "llm_stream_success",
                "transport": "openai_sdk",
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

    except (OpenAIError, ValueError, KeyError, IndexError, TypeError) as exc:
        duration = time.time() - start_time

        logger.error(
            {
                "event": "llm_stream_error",
                "transport": "openai_sdk",
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
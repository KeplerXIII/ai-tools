import logging
import time
from typing import Generator

from fastapi import HTTPException
from openai import OpenAI, OpenAIError

from app.core.config import settings

logger = logging.getLogger("openrouter_llm")


def _get_client() -> OpenAI:
    return OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        timeout=settings.llm_timeout,
    )


def _get_extra_headers() -> dict:
    headers = {}

    site_url = getattr(settings, "openrouter_site_url", None)
    site_name = getattr(settings, "openrouter_site_name", None)

    if site_url:
        headers["HTTP-Referer"] = site_url

    if site_name:
        headers["X-OpenRouter-Title"] = site_name

    return headers


def _get_completion_tokens_from_usage(usage) -> int | None:
    if not usage:
        return None

    completion_tokens = getattr(usage, "completion_tokens", None)

    if completion_tokens is None and isinstance(usage, dict):
        completion_tokens = usage.get("completion_tokens")

    try:
        return int(completion_tokens) if completion_tokens is not None else None
    except (TypeError, ValueError):
        return None


def _estimate_tokens_from_text(text: str) -> int:
    if not text:
        return 0

    return max(1, int(len(text) / 4))


def _build_metrics(
    start_time: float,
    end_time: float,
    first_token_time: float | None,
    completion_tokens: int | None,
    content: str,
) -> dict:
    duration = end_time - start_time

    ttft = None
    generation_sec = None
    tok_per_sec = None

    if first_token_time is not None:
        ttft = first_token_time - start_time
        generation_sec = max(0.0, end_time - first_token_time)

    tokens = completion_tokens

    if tokens is None:
        tokens = _estimate_tokens_from_text(content)

    if generation_sec and generation_sec > 0 and tokens:
        tok_per_sec = tokens / generation_sec

    return {
        "duration_sec": round(duration, 3),
        "ttft_sec": round(ttft, 3) if ttft is not None else None,
        "generation_sec": round(generation_sec, 3) if generation_sec is not None else None,
        "completion_tokens": tokens,
        "tok_per_sec": round(tok_per_sec, 1) if tok_per_sec is not None else None,
        "tokens_source": "usage" if completion_tokens is not None else "estimated",
    }


def chat(
    prompt: str,
    model: str,
    temperature: float = 0,
    meta: dict | None = None,
    stream: bool = False,
    max_tokens: int | None = None,
    extra_body: dict | None = None,
) -> str | Generator[str, None, None]:
    if stream:
        return _chat_stream(
            prompt=prompt,
            model=model,
            temperature=temperature,
            meta=meta,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )

    return _chat_full(
        prompt=prompt,
        model=model,
        temperature=temperature,
        meta=meta,
        max_tokens=max_tokens,
        extra_body=extra_body,
    )


def _chat_full(
    prompt: str,
    model: str,
    temperature: float = 0,
    meta: dict | None = None,
    max_tokens: int | None = None,
    extra_body: dict | None = None,
) -> str:
    start_time = time.perf_counter()

    client = _get_client()
    extra_headers = _get_extra_headers()

    logger.info(
        {
            "event": "openrouter_request",
            "transport": "openai_sdk",
            "provider": "openrouter",
            "model": model,
            "prompt_preview": "...",
            "prompt_chars": len(prompt),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "meta": meta,
        }
    )

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra_headers=extra_headers or None,
            extra_body=extra_body or None,
        )

        end_time = time.perf_counter()
        content = completion.choices[0].message.content

        if not content or not content.strip():
            raise ValueError("empty content")

        content = content.strip()
        completion_tokens = _get_completion_tokens_from_usage(getattr(completion, "usage", None))
        metrics = _build_metrics(
            start_time=start_time,
            end_time=end_time,
            first_token_time=None,
            completion_tokens=completion_tokens,
            content=content,
        )

    except (OpenAIError, ValueError, KeyError, IndexError, TypeError) as exc:
        duration = time.perf_counter() - start_time
        logger.error(
            {
                "event": "openrouter_error",
                "transport": "openai_sdk",
                "provider": "openrouter",
                "model": model,
                "duration_sec": round(duration, 3),
                "prompt_chars": len(prompt),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
                "meta": meta,
                "error": str(exc),
            }
        )
        raise HTTPException(status_code=502, detail=f"Ошибка обращения к OpenRouter: {exc}")

    logger.info(
        {
            "event": "openrouter_success",
            "transport": "openai_sdk",
            "provider": "openrouter",
            "model": model,
            **metrics,
            "prompt_chars": len(prompt),
            "response_chars": len(content),
            "temperature": temperature,
            "max_tokens": max_tokens,
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
    max_tokens: int | None = None,
    extra_body: dict | None = None,
) -> Generator[str, None, None]:
    start_time = time.perf_counter()
    first_token_time = None
    content_parts: list[str] = []
    completion_tokens: int | None = None

    client = _get_client()
    extra_headers = _get_extra_headers()

    logger.info(
        {
            "event": "openrouter_stream_request",
            "transport": "openai_sdk",
            "provider": "openrouter",
            "model": model,
            "prompt_preview": "...",
            "prompt_chars": len(prompt),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "meta": meta,
        }
    )

    try:
        stream_response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
            extra_headers=extra_headers or None,
            extra_body=extra_body or None,
        )

        for chunk in stream_response:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage_tokens = _get_completion_tokens_from_usage(chunk_usage)
                if usage_tokens is not None:
                    completion_tokens = usage_tokens

            if not getattr(chunk, "choices", None):
                continue

            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue

            if first_token_time is None:
                first_token_time = time.perf_counter()
                logger.info(
                    {
                        "event": "openrouter_stream_first_token",
                        "transport": "openai_sdk",
                        "provider": "openrouter",
                        "model": model,
                        "ttft_sec": round(first_token_time - start_time, 3),
                        "prompt_chars": len(prompt),
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "meta": meta,
                    }
                )

            content_parts.append(delta)
            yield delta

        end_time = time.perf_counter()
        content = "".join(content_parts).strip()
        metrics = _build_metrics(
            start_time=start_time,
            end_time=end_time,
            first_token_time=first_token_time,
            completion_tokens=completion_tokens,
            content=content,
        )

        logger.info(
            {
                "event": "openrouter_stream_success",
                "transport": "openai_sdk",
                "provider": "openrouter",
                "model": model,
                **metrics,
                "prompt_chars": len(prompt),
                "response_chars": len(content),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
                "meta": meta,
            }
        )

    except (OpenAIError, ValueError, KeyError, IndexError, TypeError) as exc:
        duration = time.perf_counter() - start_time
        logger.error(
            {
                "event": "openrouter_stream_error",
                "transport": "openai_sdk",
                "provider": "openrouter",
                "model": model,
                "duration_sec": round(duration, 3),
                "ttft_sec": round(first_token_time - start_time, 3) if first_token_time else None,
                "prompt_chars": len(prompt),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
                "meta": meta,
                "error": str(exc),
            }
        )
        raise HTTPException(status_code=502, detail=f"Ошибка обращения к OpenRouter stream: {exc}")

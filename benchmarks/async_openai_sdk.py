# benchmarks/async_openai_sdk.py

import asyncio
import logging
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.core.config import settings


logger = logging.getLogger("benchmark.async_openai_sdk")


BASE_URL = settings.llm_openai_url
API_KEY = settings.llm_openai_api_key or "ollama"

MODEL = "qwen3:14b"
TEMPERATURE = 0
MAX_TOKENS = 128

NUM_PARALLEL_TASKS = 3

DEBUG_CHUNKS = False


PROMPTS = [
    "Ответь одним коротким предложением: что такое RAG?",
    "Ответь одним коротким предложением: зачем нужен reranker в RAG?",
    "Ответь одним коротким предложением: чем embedding отличается от LLM?",
]


@dataclass
class BenchResult:
    task_id: int
    prompt: str
    duration: float
    ttft: float | None
    generation_sec: float | None
    tokens: int
    tok_per_sec: float | None
    response_chars: int
    response_preview: str


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if DEBUG_CHUNKS else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def estimate_tokens(text: str) -> int:
    if not text:
        return 0

    return max(1, int(len(text) / 4))


def extract_delta(chunk) -> str:
    if not getattr(chunk, "choices", None):
        return ""

    choice = chunk.choices[0]

    delta = getattr(choice, "delta", None)
    if delta:
        content = getattr(delta, "content", None)
        if content:
            return content

        reasoning_content = getattr(delta, "reasoning_content", None)
        if reasoning_content:
            return reasoning_content

    message = getattr(choice, "message", None)
    if message:
        content = getattr(message, "content", None)
        if content:
            return content

    return ""


async def run_one(
    client: AsyncOpenAI,
    task_id: int,
    prompt: str,
) -> BenchResult:
    start = time.time()
    first_token = None
    text = ""

    logger.info("task_start | task_id=%s | prompt=%r", task_id, prompt)

    stream = await client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=TEMPERATURE,
        stream=True,
    )

    async for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta.content or ""

        if not delta:
            continue

        if first_token is None:
            first_token = time.time()
            logger.info(
                "task_first_token | task_id=%s | ttft=%.2fs",
                task_id,
                first_token - start,
            )

        text += delta

    duration = time.time() - start
    ttft = (first_token - start) if first_token else None

    tokens = estimate_tokens(text)
    generation_sec = duration - ttft if ttft is not None else None
    tok_per_sec = (
        tokens / generation_sec
        if generation_sec and generation_sec > 0 and tokens > 0
        else None
    )

    logger.info(
        "task_done | task_id=%s | duration=%.2fs | ttft=%s | generation=%s | tokens=%s | tok/s=%s | chars=%s",
        task_id,
        duration,
        f"{ttft:.2f}s" if ttft is not None else "None",
        f"{generation_sec:.2f}s" if generation_sec is not None else "None",
        tokens,
        f"{tok_per_sec:.1f}" if tok_per_sec is not None else "None",
        len(text),
    )

    return BenchResult(
        task_id=task_id,
        prompt=prompt,
        duration=duration,
        ttft=ttft,
        generation_sec=generation_sec,
        tokens=tokens,
        tok_per_sec=tok_per_sec,
        response_chars=len(text),
        response_preview=text[:300],
    )


async def main() -> None:
    setup_logging()

    client = AsyncOpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout=120,
    )

    logger.info("=== ASYNC OPENAI SDK BENCHMARK ===")
    logger.info("base_url=%s", BASE_URL)
    logger.info("model=%s", MODEL)
    logger.info("parallel_tasks=%s", NUM_PARALLEL_TASKS)
    logger.info("temperature=%s", TEMPERATURE)
    logger.info("max_tokens=%s", MAX_TOKENS)

    wall_start = time.perf_counter()

    tasks = [
        asyncio.create_task(
            run_one(
                client=client,
                task_id=i + 1,
                prompt=PROMPTS[i % len(PROMPTS)],
            )
        )
        for i in range(NUM_PARALLEL_TASKS)
    ]

    results = await asyncio.gather(*tasks)

    wall_duration = time.perf_counter() - wall_start

    logger.info("=== RESULTS ===")

    for result in results:
        logger.info(
            (
                "result | task_id=%s | duration=%.2fs | ttft=%s | "
                "generation=%s | tokens_est=%s | tok_per_sec=%s | chars=%s | response=%r"
            ),
            result.task_id,
            result.duration,
            f"{result.ttft:.2f}s" if result.ttft is not None else "None",
            f"{result.generation_sec:.2f}s" if result.generation_sec is not None else "None",
            result.tokens,
            f"{result.tok_per_sec:.1f}" if result.tok_per_sec is not None else "None",
            result.response_chars,
            result.response_preview,
        )

    avg_duration = sum(r.duration for r in results) / len(results)

    valid_ttft = [r.ttft for r in results if r.ttft is not None]
    valid_gen = [r.generation_sec for r in results if r.generation_sec is not None]
    valid_toksec = [r.tok_per_sec for r in results if r.tok_per_sec is not None]

    avg_ttft = sum(valid_ttft) / len(valid_ttft) if valid_ttft else 0
    avg_gen = sum(valid_gen) / len(valid_gen) if valid_gen else 0
    avg_toksec = sum(valid_toksec) / len(valid_toksec) if valid_toksec else 0

    logger.info("=== SUMMARY ===")
    logger.info("wall_time=%.2fs", wall_duration)
    logger.info("sum_durations=%.2fs", sum(r.duration for r in results))
    logger.info("avg_duration=%.2fs", avg_duration)
    logger.info("avg_ttft=%.2fs", avg_ttft)
    logger.info("avg_generation=%.2fs", avg_gen)
    logger.info("avg_tok_per_sec=%.1f", avg_toksec)
    logger.info("total_tokens_est=%s", sum(r.tokens for r in results))
    logger.info("total_response_chars=%s", sum(r.response_chars for r in results))


if __name__ == "__main__":
    asyncio.run(main())
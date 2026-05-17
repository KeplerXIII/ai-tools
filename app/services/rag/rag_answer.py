"""RAG: retrieval + генерация ответа LLM + логирование."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap.container import get_llm_client
from app.core.config import settings
from app.core.llm_task import LLMTask
from app.domain.errors import ValidationError
from app.ports.llm import LLMRequest
from app.services.rag.pipeline import RetrievalPipeline, options_from_settings
from app.services.rag.prompt_builder import build_rag_prompt
from app.services.rag.query_log import log_rag_query
from app.services.rag.types import RagAnswer, RerankerKind, RetrievalFilters, RetrievalStrategy, RetrievedChunk


def _parse_strategy(value: str | None) -> RetrievalStrategy | None:
    if value is None:
        return None
    return RetrievalStrategy(value.strip().lower())


def _parse_reranker(value: str | None) -> RerankerKind | None:
    if value is None:
        return None
    return RerankerKind(value.strip().lower())


def _build_options(
    *,
    query: str,
    filters: RetrievalFilters | None,
    fetch_k: int | None,
    top_k: int | None,
    chunk_types: tuple[str, ...] | None,
    strategy: str | None,
    reranker: str | None,
    expand_query: bool | None,
    min_score: float | None = None,
    sources_k: int | None = None,
) -> "RetrievalOptions":
    overrides: dict = {}
    if min_score is not None and min_score > 0:
        overrides["min_similarity"] = min_score
    if sources_k is not None:
        overrides["sources_k"] = sources_k
    return options_from_settings(
        query=query,
        fetch_k=fetch_k,
        top_k=top_k,
        chunk_types=chunk_types,
        filters=filters or RetrievalFilters(),
        strategy=_parse_strategy(strategy),
        reranker=_parse_reranker(reranker),
        expand_query=expand_query,
        **overrides,
    )


async def retrieve_for_query(
    session: AsyncSession,
    *,
    query: str,
    filters: RetrievalFilters | None = None,
    fetch_k: int | None = None,
    top_k: int | None = None,
    chunk_types: tuple[str, ...] | None = None,
    strategy: str | None = None,
    reranker: str | None = None,
    expand_query: bool | None = None,
    min_score: float | None = None,
    sources_k: int | None = None,
    user_id: uuid.UUID | None = None,
    log_query: bool = True,
) -> tuple[tuple[RetrievedChunk, ...], int]:
    opts = _build_options(
        query=query,
        filters=filters,
        fetch_k=fetch_k,
        top_k=top_k,
        chunk_types=chunk_types,
        strategy=strategy,
        reranker=reranker,
        expand_query=expand_query,
        min_score=min_score,
        sources_k=sources_k,
    )
    pipeline = RetrievalPipeline()
    sources, _context, retrieval_ms, expanded = await pipeline.retrieve(session, opts)

    if log_query:
        await log_rag_query(
            session,
            user_id=user_id,
            options=opts,
            expanded_queries=expanded if len(expanded) > 1 else None,
            chunks=sources,
            retrieve_only=True,
            retrieval_ms=retrieval_ms,
            generation_ms=None,
        )
        await session.commit()

    return sources, retrieval_ms


async def answer_question(
    session: AsyncSession,
    *,
    query: str,
    filters: RetrievalFilters | None = None,
    fetch_k: int | None = None,
    top_k: int | None = None,
    chunk_types: tuple[str, ...] | None = None,
    strategy: str | None = None,
    reranker: str | None = None,
    expand_query: bool | None = None,
    min_score: float | None = None,
    sources_k: int | None = None,
    user_id: uuid.UUID | None = None,
    log_query: bool = True,
) -> RagAnswer:
    opts = _build_options(
        query=query,
        filters=filters,
        fetch_k=fetch_k,
        top_k=top_k,
        chunk_types=chunk_types,
        strategy=strategy,
        reranker=reranker,
        expand_query=expand_query,
        min_score=min_score,
        sources_k=sources_k,
    )
    pipeline = RetrievalPipeline()
    sources, context, retrieval_ms, expanded = await pipeline.retrieve(session, opts)

    gen_started = time.perf_counter()
    if not context:
        answer = (
            "В базе документов не найдено релевантных фрагментов по вашему запросу. "
            "Попробуйте переформулировать вопрос или ослабить фильтры."
        )
        generation_ms = int((time.perf_counter() - gen_started) * 1000)
        result = RagAnswer(
            answer=answer,
            sources=sources,
            context_sources=(),
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
        )
        if log_query:
            await log_rag_query(
                session,
                user_id=user_id,
                options=opts,
                expanded_queries=expanded if len(expanded) > 1 else None,
                chunks=sources,
                retrieve_only=False,
                retrieval_ms=retrieval_ms,
                generation_ms=generation_ms,
            )
            await session.commit()
        return result

    prompt = build_rag_prompt(query=query, chunks=context)
    llm = get_llm_client(LLMTask.RAG)
    raw = await llm.chat(
        LLMRequest(
            prompt=prompt,
            model=settings.model_rag,
            temperature=0.2,
            stream=False,
            meta={"tool": "rag", "chunk_count": len(context)},
        ),
    )
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError("Некорректный ответ LLM для RAG")

    generation_ms = int((time.perf_counter() - gen_started) * 1000)
    result = RagAnswer(
        answer=raw.strip(),
        sources=sources,
        context_sources=context,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
    )
    if log_query:
        await log_rag_query(
            session,
            user_id=user_id,
            options=opts,
            expanded_queries=expanded if len(expanded) > 1 else None,
            chunks=sources,
            retrieve_only=False,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
        )
        await session.commit()
    return result


async def answer_question_stream(
    session: AsyncSession,
    *,
    query: str,
    filters: RetrievalFilters | None = None,
    fetch_k: int | None = None,
    top_k: int | None = None,
    chunk_types: tuple[str, ...] | None = None,
    strategy: str | None = None,
    reranker: str | None = None,
    expand_query: bool | None = None,
    min_score: float | None = None,
    sources_k: int | None = None,
    user_id: uuid.UUID | None = None,
) -> tuple[
    tuple[RetrievedChunk, ...],
    tuple[RetrievedChunk, ...],
    int,
    AsyncIterator[str],
]:
    opts = _build_options(
        query=query,
        filters=filters,
        fetch_k=fetch_k,
        top_k=top_k,
        chunk_types=chunk_types,
        strategy=strategy,
        reranker=reranker,
        expand_query=expand_query,
        min_score=min_score,
        sources_k=sources_k,
    )
    pipeline = RetrievalPipeline()
    sources, context, retrieval_ms, expanded = await pipeline.retrieve(session, opts)

    if not context:
        async def _empty_stream() -> AsyncIterator[str]:
            yield (
                "В базе документов не найдено релевантных фрагментов по вашему запросу. "
                "Попробуйте переформулировать вопрос или ослабить фильтры."
            )

        await log_rag_query(
            session,
            user_id=user_id,
            options=opts,
            expanded_queries=expanded if len(expanded) > 1 else None,
            chunks=sources,
            retrieve_only=False,
            retrieval_ms=retrieval_ms,
            generation_ms=0,
        )
        await session.commit()
        return sources, (), retrieval_ms, _empty_stream()

    prompt = build_rag_prompt(query=query, chunks=context)
    llm = get_llm_client(LLMTask.RAG)
    stream = await llm.chat(
        LLMRequest(
            prompt=prompt,
            model=settings.model_rag,
            temperature=0.2,
            stream=True,
            meta={"tool": "rag", "chunk_count": len(context)},
        ),
    )
    if not hasattr(stream, "__aiter__"):
        raise ValidationError("Некорректный streaming-ответ LLM для RAG")

    async def _wrapped() -> AsyncIterator[str]:
        gen_started = time.perf_counter()
        try:
            async for part in stream:  # type: ignore[union-attr]
                if isinstance(part, str) and part:
                    yield part
        finally:
            from app.infrastructure.db.session import AsyncSessionLocal

            generation_ms = int((time.perf_counter() - gen_started) * 1000)
            async with AsyncSessionLocal() as log_session:
                await log_rag_query(
                    log_session,
                    user_id=user_id,
                    options=opts,
                    expanded_queries=expanded if len(expanded) > 1 else None,
                    chunks=sources,
                    retrieve_only=False,
                    retrieval_ms=retrieval_ms,
                    generation_ms=generation_ms,
                )
                await log_session.commit()

    return sources, context, retrieval_ms, _wrapped()

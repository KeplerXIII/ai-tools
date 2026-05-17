from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.error_mapping import map_app_error
from app.api.streaming_utils import coop_text_chunks, sse_data_event_bytes
from app.core.config import settings
from app.domain.errors import AppError
from app.infrastructure.db.models import RagQuery, User
from app.infrastructure.db.session import get_db
from app.schemas.rag import RagAskRequest, RagAskResponse, RagMetricsResponse, RagSourceSchema
from app.services.rag.rag_answer import answer_question, answer_question_stream, retrieve_for_query
from app.services.rag.types import RetrievedChunk

router = APIRouter(prefix="/rag", tags=["rag"])


def _filters_from_schema(payload: RagAskRequest):
    from app.services.rag.types import RetrievalFilters

    f = payload.filters
    return RetrievalFilters(
        fund_id=f.fund_id,
        environment_id=f.environment_id,
        source_id=f.source_id,
        tag_ids=tuple(f.tag_ids),
        category_ids=tuple(f.category_ids),
        entity_ids=tuple(f.entity_ids),
        published_from=f.published_from,
        published_to=f.published_to,
    )


def _chunk_types(payload: RagAskRequest) -> tuple[str, ...] | None:
    if payload.chunk_types is None:
        return None
    return tuple(payload.chunk_types)


def _score_from(chunk: RetrievedChunk) -> str:
    return "reranker" if chunk.backend == "rerank" else "retrieval"


def _source_schema(
    chunk: RetrievedChunk,
    *,
    citation_id: int | None = None,
) -> RagSourceSchema:
    return RagSourceSchema(
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        title=chunk.title,
        url=chunk.source_url,
        excerpt=chunk.content[:500] + ("…" if len(chunk.content) > 500 else ""),
        chunk_type=chunk.chunk_type,
        chunk_index=chunk.chunk_index,
        score=round(chunk.score, 6),
        rank=chunk.rank,
        score_from=_score_from(chunk),
        retrieval_scores={
            k: round(float(v), 6) for k, v in chunk.retrieval_scores.items()
        },
        citation_id=citation_id,
    )


def _pack_source_schemas(
    sources: tuple[RetrievedChunk, ...],
    context: tuple[RetrievedChunk, ...],
) -> tuple[list[RagSourceSchema], list[RagSourceSchema]]:
    cite_by_chunk = {c.chunk_id: c.rank for c in context}
    all_sources = [
        _source_schema(c, citation_id=cite_by_chunk.get(c.chunk_id)) for c in sources
    ]
    context_sources = [_source_schema(c, citation_id=c.rank) for c in context]
    return all_sources, context_sources


def _request_kwargs(payload: RagAskRequest, user: User):
    return {
        "query": payload.query,
        "filters": _filters_from_schema(payload),
        "fetch_k": payload.fetch_k,
        "top_k": payload.top_k,
        "sources_k": payload.sources_k,
        "chunk_types": _chunk_types(payload),
        "strategy": payload.retrieval_strategy,
        "reranker": payload.reranker,
        "expand_query": payload.expand_query,
        "min_score": payload.min_score,
        "user_id": user.id,
    }


@router.get("/metrics", response_model=RagMetricsResponse)
async def rag_metrics(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    total = await db.scalar(select(func.count()).select_from(RagQuery)) or 0
    from datetime import UTC, datetime, timedelta

    since = datetime.now(UTC) - timedelta(hours=24)
    last_24h = (
        await db.scalar(
            select(func.count()).select_from(RagQuery).where(RagQuery.created_at >= since),
        )
        or 0
    )
    avg_retrieval = await db.scalar(select(func.avg(RagQuery.retrieval_ms)))
    avg_generation = await db.scalar(
        select(func.avg(RagQuery.generation_ms)).where(RagQuery.generation_ms.is_not(None)),
    )
    empty_count = (
        await db.scalar(
            select(func.count())
            .select_from(RagQuery)
            .where(
                or_(
                    RagQuery.chunk_ids.is_(None),
                    text("chunk_ids::text = '[]'"),
                ),
            ),
        )
        or 0
    )
    empty_rate = (empty_count / total) if total else None

    return RagMetricsResponse(
        total_queries=int(total),
        queries_last_24h=int(last_24h),
        avg_retrieval_ms=float(avg_retrieval) if avg_retrieval is not None else None,
        avg_generation_ms=float(avg_generation) if avg_generation is not None else None,
        empty_context_rate=empty_rate,
    )


@router.post("/ask", response_model=RagAskResponse)
async def rag_ask(
    payload: RagAskRequest,
    retrieve_only: bool = Query(False, description="Только retrieval, без LLM"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Запрос пустой")

    kwargs = _request_kwargs(payload, user)

    try:
        if retrieve_only:
            chunks, retrieval_ms = await retrieve_for_query(db, **kwargs)
            all_src, _ctx = _pack_source_schemas(chunks, ())
            return RagAskResponse(
                answer=None,
                sources=all_src,
                context_sources=[],
                retrieval_ms=retrieval_ms,
                generation_ms=None,
                retrieval_strategy=payload.retrieval_strategy or settings.rag_retrieval_strategy,
                reranker=payload.reranker or settings.rag_reranker,
            )

        result = await answer_question(db, **kwargs)
    except AppError as exc:
        raise map_app_error(exc) from exc

    all_src, ctx_src = _pack_source_schemas(result.sources, result.context_sources)
    return RagAskResponse(
        answer=result.answer,
        sources=all_src,
        context_sources=ctx_src,
        retrieval_ms=result.retrieval_ms,
        generation_ms=result.generation_ms,
        retrieval_strategy=payload.retrieval_strategy or settings.rag_retrieval_strategy,
        reranker=payload.reranker or settings.rag_reranker,
    )


@router.post("/ask/stream")
async def rag_ask_stream(
    payload: RagAskRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Запрос пустой")

    kwargs = _request_kwargs(payload, user)

    try:
        sources, context, retrieval_ms, text_stream = await answer_question_stream(
            db, **kwargs,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    all_src, ctx_src = _pack_source_schemas(sources, context)
    meta = {
        "retrieval_ms": retrieval_ms,
        "sources": [s.model_dump(mode="json") for s in all_src],
        "context_sources": [s.model_dump(mode="json") for s in ctx_src],
        "retrieval_strategy": payload.retrieval_strategy or settings.rag_retrieval_strategy,
        "reranker": payload.reranker or settings.rag_reranker,
    }

    async def _event_stream():
        yield f"event: meta\ndata: {json.dumps(meta, ensure_ascii=False)}\n\n".encode()
        try:
            async for part in coop_text_chunks(text_stream):
                yield sse_data_event_bytes(part)
            yield b"data: [DONE]\n\n"
        except Exception as exc:
            msg = str(exc).replace("\n", " ").strip()
            yield f"event: error\ndata: {msg}\n\n".encode()

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-RAG-Retrieval-Ms": str(retrieval_ms),
        },
    )

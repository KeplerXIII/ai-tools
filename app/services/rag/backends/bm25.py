"""Лексический поиск Okapi BM25 по инвертированному индексу document_chunk_terms."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infrastructure.db.models import Document, DocumentChunk, DocumentChunkTerm
from app.services.rag.backends.document_title import document_display_title_column
from app.services.rag.backends.filters import apply_document_metadata_filters
from app.services.rag.bm25_index import fetch_bm25_corpus_stats
from app.services.rag.bm25_scoring import bm25_score_document, normalize_bm25_scores
from app.services.rag.bm25_tokenize import tokenize_for_bm25
from app.services.rag.types import RetrievalFilters, RetrievedChunk


class Bm25RetrievalBackend:
    name = "bm25"

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str,
        query_vector: list[float],
        fetch_k: int,
        chunk_types: tuple[str, ...],
        filters: RetrievalFilters,
    ) -> list[RetrievedChunk]:
        del query_vector
        query_terms = tokenize_for_bm25(query)
        if not query_terms or fetch_k < 1:
            return []

        corpus_size, avg_dl = await fetch_bm25_corpus_stats(session)
        if corpus_size == 0:
            return []

        term_df_rows = await session.execute(
            select(
                DocumentChunkTerm.term,
                func.count(func.distinct(DocumentChunkTerm.chunk_id)).label("df"),
            )
            .where(DocumentChunkTerm.term.in_(query_terms))
            .group_by(DocumentChunkTerm.term),
        )
        term_df = {row.term: int(row.df) for row in term_df_rows}

        candidates_stmt = (
            select(DocumentChunkTerm.chunk_id)
            .distinct()
            .join(DocumentChunk, DocumentChunk.id == DocumentChunkTerm.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunkTerm.term.in_(query_terms))
        )
        if chunk_types:
            candidates_stmt = candidates_stmt.where(DocumentChunk.chunk_type.in_(chunk_types))
        candidates_stmt = apply_document_metadata_filters(candidates_stmt, filters)
        candidate_ids = [row[0] for row in (await session.execute(candidates_stmt)).all()]
        if not candidate_ids:
            return []

        postings_rows = await session.execute(
            select(
                DocumentChunkTerm.chunk_id,
                DocumentChunkTerm.term,
                DocumentChunkTerm.tf,
            ).where(
                DocumentChunkTerm.chunk_id.in_(candidate_ids),
                DocumentChunkTerm.term.in_(query_terms),
            ),
        )
        term_tf_by_chunk: dict[uuid.UUID, dict[str, int]] = {}
        for row in postings_rows:
            term_tf_by_chunk.setdefault(row.chunk_id, {})[row.term] = int(row.tf)

        length_rows = await session.execute(
            select(
                DocumentChunkTerm.chunk_id,
                func.sum(DocumentChunkTerm.tf).label("dl"),
            )
            .where(DocumentChunkTerm.chunk_id.in_(candidate_ids))
            .group_by(DocumentChunkTerm.chunk_id),
        )
        doc_lengths = {row.chunk_id: int(row.dl) for row in length_rows}

        raw_scores: dict[uuid.UUID, float] = {}
        for chunk_id in candidate_ids:
            dl = doc_lengths.get(chunk_id, 0)
            tf_map = term_tf_by_chunk.get(chunk_id, {})
            raw_scores[chunk_id] = bm25_score_document(
                query_terms,
                term_tf=tf_map,
                doc_length=dl,
                term_df=term_df,
                corpus_size=corpus_size,
                avg_doc_length=avg_dl,
                k1=settings.rag_bm25_k1,
                b=settings.rag_bm25_b,
            )

        normalized = normalize_bm25_scores(raw_scores)
        ranked_ids = sorted(
            normalized.keys(),
            key=lambda cid: normalized[cid],
            reverse=True,
        )[:fetch_k]

        if not ranked_ids:
            return []

        meta_stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.document_id,
                DocumentChunk.chunk_type,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                document_display_title_column(),
                Document.source_url,
            )
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_(ranked_ids))
        )
        meta_by_id = {row.chunk_id: row for row in (await session.execute(meta_stmt)).all()}

        return [
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=meta.document_id,
                chunk_type=meta.chunk_type,
                chunk_index=meta.chunk_index,
                content=meta.content,
                title=meta.title,
                source_url=meta.source_url,
                distance=1.0 - normalized[chunk_id],
                score=normalized[chunk_id],
                backend=self.name,
            )
            for chunk_id in ranked_ids
            if (meta := meta_by_id.get(chunk_id)) is not None
        ]

    async def score_chunks(
        self,
        session: AsyncSession,
        *,
        query: str,
        chunk_ids: list[uuid.UUID],
        chunk_types: tuple[str, ...],
        filters: RetrievalFilters,
    ) -> dict[uuid.UUID, float]:
        """BM25 для chunk_id (нормализация внутри переданного набора)."""
        query_terms = tokenize_for_bm25(query)
        if not chunk_ids:
            return {}
        if not query_terms:
            return dict.fromkeys(chunk_ids, 0.0)

        corpus_size, avg_dl = await fetch_bm25_corpus_stats(session)
        if corpus_size == 0:
            return dict.fromkeys(chunk_ids, 0.0)

        term_df_rows = await session.execute(
            select(
                DocumentChunkTerm.term,
                func.count(func.distinct(DocumentChunkTerm.chunk_id)).label("df"),
            )
            .where(DocumentChunkTerm.term.in_(query_terms))
            .group_by(DocumentChunkTerm.term),
        )
        term_df = {row.term: int(row.df) for row in term_df_rows}

        postings_rows = await session.execute(
            select(
                DocumentChunkTerm.chunk_id,
                DocumentChunkTerm.term,
                DocumentChunkTerm.tf,
            ).where(
                DocumentChunkTerm.chunk_id.in_(chunk_ids),
                DocumentChunkTerm.term.in_(query_terms),
            ),
        )
        term_tf_by_chunk: dict[uuid.UUID, dict[str, int]] = {}
        for row in postings_rows:
            term_tf_by_chunk.setdefault(row.chunk_id, {})[row.term] = int(row.tf)

        length_rows = await session.execute(
            select(
                DocumentChunkTerm.chunk_id,
                func.sum(DocumentChunkTerm.tf).label("dl"),
            )
            .where(DocumentChunkTerm.chunk_id.in_(chunk_ids))
            .group_by(DocumentChunkTerm.chunk_id),
        )
        doc_lengths = {row.chunk_id: int(row.dl) for row in length_rows}

        raw_scores: dict[uuid.UUID, float] = {}
        for chunk_id in chunk_ids:
            dl = doc_lengths.get(chunk_id, 0)
            if dl <= 0:
                raw_scores[chunk_id] = 0.0
                continue
            raw_scores[chunk_id] = bm25_score_document(
                query_terms,
                term_tf=term_tf_by_chunk.get(chunk_id, {}),
                doc_length=dl,
                term_df=term_df,
                corpus_size=corpus_size,
                avg_doc_length=avg_dl,
                k1=settings.rag_bm25_k1,
                b=settings.rag_bm25_b,
            )

        normalized = normalize_bm25_scores(raw_scores)
        return {cid: normalized.get(cid, 0.0) for cid in chunk_ids}

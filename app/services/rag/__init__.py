"""RAG: retrieval pipeline, generation, расширения (reranker, hybrid) — см. docs/rag-roadmap.md."""

from app.services.rag.pipeline import RetrievalPipeline
from app.services.rag.rag_answer import answer_question, retrieve_for_query
from app.services.rag.types import RagAnswer, RetrievedChunk, RetrievalFilters

__all__ = [
    "RagAnswer",
    "RetrievalFilters",
    "RetrievalPipeline",
    "RetrievedChunk",
    "answer_question",
    "retrieve_for_query",
]

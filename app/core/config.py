from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.llm_task import LLMTask


@dataclass(frozen=True, slots=True)
class OpenAIEndpoint:
    base_url: str
    api_key: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    app_name: str = "AI Tools Service"
    app_version: str = "0.1.0"
    debug: bool = False

    # --- limits ---
    # HTTP-загрузка страницы и навигация Playwright при /extract (секунды)
    request_timeout: int = 45
    max_html_length: int = 10_000_000

    # --- OpenAI-compatible API (default for all tasks unless overridden below) ---
    openai_compat_base_url: str = "https://api.deepseek.com"
    openai_compat_api_key: str

    # --- per-task overrides (optional; unset inherits default above) ---
    openai_compat_base_url_summary: str | None = None
    openai_compat_api_key_summary: str | None = None

    openai_compat_base_url_summary_refine: str | None = None
    openai_compat_api_key_summary_refine: str | None = None

    openai_compat_base_url_translation: str | None = None
    openai_compat_api_key_translation: str | None = None

    openai_compat_base_url_tagging: str | None = None
    openai_compat_api_key_tagging: str | None = None

    openai_compat_base_url_entity_extraction: str | None = None
    openai_compat_api_key_entity_extraction: str | None = None

    openai_compat_base_url_categorization: str | None = None
    openai_compat_api_key_categorization: str | None = None

    openai_compat_base_url_rag: str | None = None
    openai_compat_api_key_rag: str | None = None

    # --- runtime ---
    llm_timeout: int = 120

    # --- embeddings (TEI OpenAI-compatible /v1/embeddings → pgvector bge-m3 = 1024) ---
    embedding_enabled: bool = True
    embedding_tei_base_url: str = "http://embedding-tei/v1"
    embedding_tei_api_key: str = "tei"
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_catalog_model_name: str = "bge-m3"
    # Явный путь к snapshot (…/snapshots/<rev>) или корень HF hub (…/hub) с models--*.
    embedding_tokenizer_local_path: str | None = None
    embedding_tokenizer_hub_root: str | None = None
    embedding_tokenizer_cache_dir: str | None = None
    embedding_tokenizer_local_files_only: bool = False
    embedding_chunk_tokens_original: int = 512
    embedding_chunk_overlap_tokens_original: int = 128
    embedding_chunk_tokens_translated: int = 512
    embedding_chunk_overlap_tokens_translated: int = 128
    embedding_chunk_tokens_annotation: int = 512
    embedding_chunk_overlap_tokens_annotation: int = 64
    embedding_timeout_sec: int = 120
    embedding_fail_open: bool = True

    # --- RAG (retrieval + generation; cosine HNSW в document_embeddings) ---
    rag_enabled: bool = True
    # vector | hybrid
    rag_retrieval_strategy: str = "vector"
    # none | cross_encoder (TEI rerank-tei /rerank или bi-encoder fallback)
    rag_reranker: str = "none"
    rag_fetch_k: int = 40
    rag_top_k: int = 12
    rag_max_chunks_per_document: int = 3
    rag_max_context_tokens: int = 6000
    rag_min_similarity: float | None = None
    rag_default_chunk_types: str = "translated,original,annotation"
    rag_hnsw_ef_search: int = 64
    rag_hnsw_m: int = 16
    rag_hnsw_ef_construction: int = 128
    rag_fts_config: str = "russian"
    rag_bm25_k1: float = 1.5
    rag_bm25_b: float = 0.75
    rag_bm25_index_on_embed: bool = True
    rag_rrf_k: int = 60
    # TEI rerank: базовый URL без /v1 (Docker: http://rerank-tei:80); пусто → только fallback
    rag_rerank_base_url: str | None = "http://rerank-tei:80"
    rag_rerank_model_name: str | None = "BAAI/bge-reranker-v2-m3"
    rag_rerank_timeout_sec: int = 60
    rag_rerank_bi_encoder_fallback: bool = True
    # TEI --max-client-batch-size (дефолт 32); больше пар в одном /rerank → HTTP 413
    rag_rerank_max_batch_size: int = 32
    rag_embedding_request_batch_size: int = 8
    rag_query_expansion: bool = False
    rag_query_expansion_count: int = 2

    # --- background processing (SAQ) ---
    saq_queue_url: str = "redis://localhost:6379/0"
    saq_translate_queue_name: str = "ai-tools-translate"
    saq_annotate_queue_name: str = "ai-tools-annotate"
    saq_categorize_queue_name: str = "ai-tools-categorize"
    saq_extractor_queue_name: str = "ai-tools-extractor"
    saq_tagger_queue_name: str = "ai-tools-tagger"
    saq_parse_queue_name: str = "ai-tools-parse"
    saq_translate_worker_concurrency: int = 1
    saq_annotate_worker_concurrency: int = 1
    saq_categorize_worker_concurrency: int = 5
    saq_extractor_worker_concurrency: int = 5
    saq_tagger_worker_concurrency: int = 5
    saq_parse_worker_concurrency: int = 1
    saq_translate_job_timeout_sec: int = 1800
    saq_annotate_job_timeout_sec: int = 1800
    saq_categorize_job_timeout_sec: int = 1800
    saq_extractor_job_timeout_sec: int = 1800
    saq_tagger_job_timeout_sec: int = 1800
    saq_parse_job_timeout_sec: int = 7200

    # --- documents ---
    document_lock_expire_minutes: int = 15

    # --- database (async SQLAlchemy; URL вида postgresql+asyncpg://user:pass@host:5432/db) ---
    database_url: str

    # --- JWT ---
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # --- SQLAdmin session (если не задан — используется jwt_secret_key) ---
    admin_session_secret: str | None = None

    # --- models by task ---
    model_summary: str = "deepseek-v4-pro"
    model_summary_refine: str = "deepseek-v4-pro"
    model_translation: str = "deepseek-v4-pro"
    model_tagging: str = "deepseek-v4-pro"
    model_entity_extraction: str = "deepseek-v4-pro"
    model_categorization: str = "deepseek-v4-pro"
    model_rag: str = "deepseek-v4-pro"

    def openai_endpoint_for(self, task: LLMTask) -> OpenAIEndpoint:
        suffix = task.value
        base = getattr(self, f"openai_compat_base_url_{suffix}", None) or self.openai_compat_base_url
        key = getattr(self, f"openai_compat_api_key_{suffix}", None) or self.openai_compat_api_key
        return OpenAIEndpoint(base_url=base, api_key=key)


settings = Settings()

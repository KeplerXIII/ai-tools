# RAG: план внедрения

Документ фиксирует шаги от **готового векторного индекса** до **полноценного RAG**. Источник правды по индексации — [`document-embeddings.md`](document-embeddings.md).

**Код:** `app/services/rag/`, `POST /api/v1/rag/ask`, UI `/rag`.

---

## Текущее состояние

| Компонент | Статус |
|-----------|--------|
| HNSW cosine + vector retrieval | ✅ |
| Hybrid FTS (`russian`) + RRF | ✅ |
| Cross-encoder rerank (TEI `/rerank` + bi-encoder fallback) | ✅ |
| Query expansion (multi-query) | ✅ опционально |
| API + stream + metrics + лог `rag_queries` | ✅ |
| UI «Вопрос по базе» | ✅ `/rag` |
| Parent–child chunks, agentic, eval | ❌ фаза 5 |

---

## Фазы 1–2 ✅

См. историю коммитов; критерии закрыты.

---

## Фаза 3 — Качество поиска ✅

| Улучшение | Статус | Реализация |
|-----------|--------|------------|
| **Hybrid FTS** | ✅ | `backends/lexical.py` (PostgreSQL `ts_rank_cd`), GIN `20260520_01` |
| **Hybrid BM25** | ✅ | `backends/bm25.py`, стратегия `hybrid_bm25` |
| **Hybrid all (vector+FTS+BM25)** | ✅ | стратегия `hybrid_all`, слияние **RRF** трёх списков |
| **Reranker** | ✅ | `rerank_client.py`, `CrossEncoderReranker`, `RAG_RERANKER=cross_encoder` |
| **Query expansion** | ✅ | `query_expansion.py`, `expand_query` в API/UI |
| **Multi-query** | ✅ | несколько подзапросов → RRF в `pipeline.py` |
| Parent–child chunks | ❌ | фаза 5 |

Конфиг: `RAG_RETRIEVAL_STRATEGY=hybrid`, `RAG_RERANK_BASE_URL`, `RAG_QUERY_EXPANSION=true`.

---

## Фаза 4 — UX и эксплуатация ✅

| Задача | Статус |
|--------|--------|
| Страница UI `/rag` | ✅ `ai-tools-ui/.../rag-qa/` |
| Streaming SSE | ✅ `POST /api/v1/rag/ask/stream` |
| Лог `rag_queries` | ✅ миграция `20260520_02`, `query_log.py` |
| Метрики | ✅ `GET /api/v1/rag/metrics` |

---

## Фаза 5 — Продвинутое

- [ ] Parent–child chunks
- [ ] Agentic RAG
- [ ] Eval pipeline
- [ ] Кэш эмбеддинга запроса

---

## Запуск

```bash
docker compose exec ai-tools uv run alembic upgrade head
# BM25-индекс для уже существующих чанков (один раз):
docker compose exec ai-tools uv run python -m app.cli.backfill_bm25_index
```

UI: http://127.0.0.1:8088/rag

```bash
curl -sS -X POST "http://127.0.0.1:8010/api/v1/rag/ask" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"…","retrieval_strategy":"hybrid","reranker":"cross_encoder"}'
```

TEI reranker: сервис `rerank-tei` в compose (`BAAI/bge-reranker-v2-m3`, порт **8090**), `RAG_RERANK_BASE_URL=http://rerank-tei:80`.

---

## Структура файлов

```
app/services/rag/
  backends/vector.py, lexical.py, filters.py
  pipeline.py, merge.py, rerankers.py
  query_expansion.py, query_log.py, rag_answer.py
app/infrastructure/llm/clients/rerank_client.py
app/infrastructure/db/models/rag_query.py
app/api/v1/endpoints/rag.py
ai-tools-ui/src/app/features/rag-qa/
alembic/versions/20260519_01_*.py … 20260520_02_*.py
```

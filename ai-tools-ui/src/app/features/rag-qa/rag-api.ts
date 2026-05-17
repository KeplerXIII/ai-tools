import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { AuthService } from '../../core/auth/auth.service';
import { firstValueFrom } from 'rxjs';

export interface RagFilters {
  fund_id?: string | null;
  environment_id?: string | null;
  source_id?: string | null;
  tag_ids?: string[];
  category_ids?: string[];
  entity_ids?: string[];
}

export interface RagAskRequest {
  query: string;
  top_k?: number | null;
  fetch_k?: number | null;
  sources_k?: number | null;
  chunk_types?: string[] | null;
  filters?: RagFilters;
  retrieval_strategy?: 'vector' | 'hybrid' | 'hybrid_bm25' | 'hybrid_all' | null;
  reranker?: 'none' | 'cross_encoder' | null;
  expand_query?: boolean | null;
  min_score?: number | null;
}

export interface RagSource {
  document_id: string;
  chunk_id: string;
  title: string;
  url: string | null;
  excerpt: string;
  chunk_type: string;
  chunk_index: number;
  score: number;
  rank: number;
  /** Источник score: reranker (cross-encoder) или retrieval */
  score_from?: 'reranker' | 'retrieval';
  /** До rerank: vector, lexical (FTS), bm25 */
  retrieval_scores?: Record<string, number>;
  citation_id?: number | null;
}

export interface RagAskResponse {
  answer: string | null;
  sources: RagSource[];
  context_sources?: RagSource[];
  retrieval_ms: number;
  generation_ms: number | null;
  retrieval_strategy?: string | null;
  reranker?: string | null;
}

export interface RagStreamMeta {
  retrieval_ms: number;
  sources: RagSource[];
  context_sources?: RagSource[];
  retrieval_strategy?: string;
  reranker?: string;
}

export interface RagMetrics {
  total_queries: number;
  queries_last_24h: number;
  avg_retrieval_ms: number | null;
  avg_generation_ms: number | null;
  empty_context_rate: number | null;
}

@Injectable({ providedIn: 'root' })
export class RagApi {
  private readonly baseUrl = '/api/v1/rag';

  constructor(
    private readonly http: HttpClient,
    private readonly auth: AuthService,
  ) {}

  ask(body: RagAskRequest, retrieveOnly = false): Promise<RagAskResponse> {
    const params = retrieveOnly ? '?retrieve_only=true' : '';
    return firstValueFrom(
      this.http.post<RagAskResponse>(`${this.baseUrl}/ask${params}`, body),
    );
  }

  metrics(): Promise<RagMetrics> {
    return firstValueFrom(this.http.get<RagMetrics>(`${this.baseUrl}/metrics`));
  }

  async askStream(
    body: RagAskRequest,
    handlers: {
      onMeta: (meta: RagStreamMeta) => void;
      onChunk: (text: string) => void;
    },
  ): Promise<void> {
    const token = this.auth.getToken();
    const response = await fetch(`${this.baseUrl}/ask/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`RAG stream: ${response.status}`);
    }
    if (!response.body) {
      throw new Error('Пустой streaming response');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let currentEvent = 'message';

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';

      for (const block of blocks) {
        const lines = block.split('\n');
        let eventType = currentEvent;
        const dataLines: string[] = [];
        let sawEventLine = false;
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventType = line.replace(/^event:\s?/, '').trim();
            sawEventLine = true;
          } else if (line.startsWith('data:')) {
            dataLines.push(line.replace(/^data:\s?/, ''));
          }
        }
        const data = dataLines.join('\n');
        if (sawEventLine) {
          currentEvent = eventType;
        }
        if (eventType === 'error') {
          currentEvent = 'message';
          throw new Error(data || 'Ошибка RAG stream');
        }
        if (eventType === 'meta' && data) {
          handlers.onMeta(JSON.parse(data) as RagStreamMeta);
          currentEvent = 'message';
          continue;
        }
        if (data === '[DONE]') {
          return;
        }
        if (data) {
          handlers.onChunk(data);
        }
      }
    }
  }
}

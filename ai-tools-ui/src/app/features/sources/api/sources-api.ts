import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { AuthService } from '../../../core/auth/auth.service';

export interface SourceListItem {
  source_id: string;
  name: string | null;
  url: string;
  rss_url: string | null;
  discovery_paths: string[];
  language_code: string;
  country_code: string | null;
  document_type_code: string;
  document_type_name: string;
  is_active: boolean;
  created_at: string;
  added_by_user_id: string;
  added_by_username: string;
  documents_total: number;
  documents_unprocessed: number;
  last_parse_created_total: number | null;
  last_parse_at: string | null;
}

export interface SourceListResponse {
  total: number;
  items: SourceListItem[];
  can_filter_by_all_users: boolean;
}

/** Тело POST /parsing/sources — совпадает с ``SourceCreateRequest`` на бэкенде. */
export interface SourceCreateRequestBody {
  url: string;
  name?: string | null;
  language_code?: string;
  country_code?: string | null;
  rss_url?: string | null;
  discovery_paths?: string[];
  document_type_code: string;
}

export interface SourceCreateResponse {
  source_id: string;
  url: string;
  name: string | null;
  language_code: string;
  country_code: string | null;
  rss_url: string | null;
  discovery_paths: string[];
  is_active: boolean;
  document_type_code: string;
  document_type_name: string;
}

export interface PostParseProcessingOptions {
  full_llm_pipeline: boolean;
  llm_tag_original?: boolean;
  llm_translate?: boolean;
  llm_extractor?: boolean;
  llm_tag_translated?: boolean;
  llm_annotate?: boolean;
  llm_categorize?: boolean;
  target_lang?: string;
  max_tags?: number;
}

export interface ParseSourceRequestBody {
  source_id: string;
  days?: number;
  /** По умолчанию true: не брать ссылки без даты и не сохранять без итоговой даты. */
  skip_undated?: boolean;
  post_parse?: PostParseProcessingOptions;
}

export interface ParseSourceDocumentItem {
  document_id: string;
  title: string;
  source_url: string | null;
  published_at: string | null;
  created_at: string;
}

export interface ParseSourceEnqueueResponse {
  parse_run_id: string;
  source_id: string;
  processing_job_id?: string | null;
  status: 'pending';
}

export interface ParseSourceRunResponse {
  parse_run_id: string;
  source_id: string;
  processing_job_id?: string | null;
  phase?: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed';
  found_total: number | null;
  created_total: number | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  existing_unprocessed_by_source: ParseSourceDocumentItem[];
  new_unprocessed_by_source: ParseSourceDocumentItem[];
}

/** Снимок из SSE ``/parse-runs/{id}/stream`` (поля ответа + ``snapshot_at``). */
export interface ParseSourceRunSnapshotPayload extends ParseSourceRunResponse {
  snapshot_at: string;
}

export interface ActiveParseRunItem {
  source_id: string;
  parse_run: ParseSourceRunResponse;
}

export interface ActiveParseRunsResponse {
  items: ActiveParseRunItem[];
}

export interface LanguageCatalogItem {
  code: string;
  name: string;
}

export interface CountryCatalogItem {
  code: string;
  name: string;
}

@Injectable({
  providedIn: 'root',
})
export class SourcesApi {
  constructor(
    private readonly http: HttpClient,
    private readonly auth: AuthService,
  ) {}

  getLanguagesCatalog(): Observable<LanguageCatalogItem[]> {
    return this.http.get<LanguageCatalogItem[]>('/api/v1/parsing/languages/catalog');
  }

  getCountriesCatalog(): Observable<CountryCatalogItem[]> {
    return this.http.get<CountryCatalogItem[]>('/api/v1/parsing/countries/catalog');
  }

  createSource(body: SourceCreateRequestBody): Observable<SourceCreateResponse> {
    return this.http.post<SourceCreateResponse>('/api/v1/parsing/sources', body);
  }

  /** POST возвращает 202 Accepted; разбор выполняется воркером ``ai-tools-parse-worker``. */
  parseSource(body: ParseSourceRequestBody): Observable<ParseSourceEnqueueResponse> {
    return this.http.post<ParseSourceEnqueueResponse>('/api/v1/parsing/sources/parse', body);
  }

  getParseRun(parseRunId: string): Observable<ParseSourceRunResponse> {
    return this.http.get<ParseSourceRunResponse>(
      `/api/v1/parsing/sources/parse-runs/${parseRunId}`,
    );
  }

  /** Незавершённые разборы по БД (pending/running), чтобы восстановить SSE после навигации. */
  listActiveSourceParseRuns(): Observable<ActiveParseRunsResponse> {
    return this.http.get<ActiveParseRunsResponse>('/api/v1/parsing/sources/active-parse-runs');
  }

  /** SSE: статус и фаза разбора до ``completed`` / ``failed``. */
  streamParseRun(parseRunId: string): Observable<ParseSourceRunSnapshotPayload> {
    return new Observable<ParseSourceRunSnapshotPayload>((observer) => {
      const token = this.auth.getToken();
      const controller = new AbortController();
      const url = `/api/v1/parsing/sources/parse-runs/${encodeURIComponent(parseRunId)}/stream`;

      fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok || !response.body) {
            throw new Error(`Ошибка SSE: ${response.status}`);
          }
          const reader = response.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let buffer = '';
          let eventName = 'message';
          let dataLines: string[] = [];

          const dispatchEvent = () => {
            if (eventName === 'heartbeat') {
              eventName = 'message';
              dataLines = [];
              return;
            }
            if (eventName === 'error') {
              observer.error(new Error(dataLines.join('\n') || 'Ошибка SSE stream'));
              return;
            }
            const payloadText = dataLines.join('\n').trim();
            if (!payloadText) {
              eventName = 'message';
              dataLines = [];
              return;
            }
            const looksLikeSnapshot =
              payloadText.includes('"snapshot_at"') && payloadText.includes('"parse_run_id"');
            const isSnapshot =
              eventName === 'snapshot' || (eventName === 'message' && looksLikeSnapshot);
            if (!isSnapshot) {
              eventName = 'message';
              dataLines = [];
              return;
            }
            try {
              const payload = JSON.parse(payloadText) as ParseSourceRunSnapshotPayload;
              observer.next(payload);
            } catch {
              observer.error(new Error('Некорректный JSON в SSE snapshot'));
            } finally {
              eventName = 'message';
              dataLines = [];
            }
          };

          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              if (dataLines.length > 0) {
                dispatchEvent();
              }
              observer.complete();
              break;
            }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split(/\r?\n/);
            buffer = lines.pop() ?? '';
            for (const line of lines) {
              const normalized = line.replace(/^\uFEFF/, '');
              if (normalized.trim() === '') {
                dispatchEvent();
                continue;
              }
              const trimmedStart = normalized.trimStart();
              if (/^event:/i.test(trimmedStart)) {
                eventName = trimmedStart.replace(/^event:/i, '').trim();
                continue;
              }
              if (/^data:/i.test(trimmedStart)) {
                dataLines.push(trimmedStart.replace(/^data:/i, '').trimStart());
              }
            }
          }
        })
        .catch((error: unknown) => {
          const fetchError = error as { name?: string };
          if (fetchError?.name !== 'AbortError') {
            observer.error(error);
          }
        });

      return () => controller.abort();
    });
  }

  listSources(addedByUserId?: string): Observable<SourceListResponse> {
    let params = new HttpParams();
    if (addedByUserId) {
      params = params.set('added_by_user_id', addedByUserId);
    }
    return this.http.get<SourceListResponse>('/api/v1/parsing/sources', { params });
  }
}

import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';

export interface ImageInfo {
  url: string;
  alt: string | null;
  title: string | null;
}

export interface DocumentEntityRef {
  id: string;
  name: string;
}

/** Совпадает с серверным DocumentTagItem (id + name). */
export type DocumentTagRef = DocumentEntityRef;

/** Назначенные категории документа (confidence, источник из prediction_sources). */
export interface DocumentCategoryRef {
  category_id: string;
  code: string;
  name: string;
  name_ru?: string | null;
  confidence: number;
  prediction_source_code: string;
  text_source?: 'original' | 'translated' | null;
}

export interface DocumentCategorizeResponse {
  ok?: boolean;
  document_id: string;
  categories: DocumentCategoryRef[];
}

export interface ExtractResponse {
  title: string | null;
  author: string | null;
  date: string | null;
  url: string | null;
  text: string;
  length: number;
  method: string;
  quality: string;
  needs_review: boolean;
  images: ImageInfo[];
  main_image: string | null;
  document_id?: string;
  from_cache?: boolean;
  version?: number;
  published_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  translated_content?: string | null;
  original_summary?: string | null;
  translated_summary?: string | null;
  original_summary_stale?: boolean;
  translated_summary_stale?: boolean;
  statuses?: {
    code: string;
    name_ru: string;
    description: string | null;
    assigned_at: string;
    assigned_by_id: string | null;
  }[];
  original_tags?: DocumentTagRef[];
  translated_tags?: DocumentTagRef[];
  entities_military_equipment?: DocumentEntityRef[];
  entities_manufacturers?: DocumentEntityRef[];
  entities_contracts?: DocumentEntityRef[];
  categories?: DocumentCategoryRef[];
}

export interface DocumentStatusCatalogItem {
  code: string;
  name_ru: string;
  description: string | null;
}

export interface DocumentStatusesResponse {
  document_id: string;
  statuses: {
    code: string;
    name_ru: string;
    description: string | null;
    assigned_at: string;
    assigned_by_id: string | null;
  }[];
}

export interface EntitiesResponse {
  document_id?: string;
  ok?: boolean;
  military_equipment: DocumentEntityRef[];
  manufacturers: DocumentEntityRef[];
  contracts: DocumentEntityRef[];
}

export interface DocumentTagsResponse {
  document_id: string;
  original_tags: DocumentTagRef[];
  translated_tags: DocumentTagRef[];
}

export interface TranslateResponse {
  source_lang: string;
  target_lang: string;
  translation: string;
}

export interface TranslateStreamResponse {
  source_lang: string | null;
  target_lang: string | null;
  translation: string;
}

export interface SummaryResponse {
  annotation: string;
}

@Injectable({
  providedIn: 'root',
})
export class ArticleParserApi {
  constructor(
    private http: HttpClient,
    private authService: AuthService,
  ) {}

  private getStreamHeaders(): HeadersInit {
    const token = this.authService.getToken();

    return {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }

  extractByUrl(url: string) {
    return this.http.post<ExtractResponse>('/api/v1/documents/extract-url', {
      url,
    });
  }

  extractEntities(documentId: string) {
    return this.http.post<EntitiesResponse>(`/api/v1/documents/${documentId}/entities`, {});
  }

  getDocumentEntities(documentId: string) {
    return this.http.get<EntitiesResponse>(`/api/v1/documents/${documentId}/entities`);
  }

  getEntityCatalog(documentId: string, entityTypeCode: string) {
    return this.http.get<DocumentEntityRef[]>(`/api/v1/documents/${documentId}/entities/catalog`, {
      params: { entity_type_code: entityTypeCode },
    });
  }

  assignDocumentEntity(documentId: string, entityId: string) {
    return this.http.post<{ ok?: boolean }>(`/api/v1/documents/${documentId}/entities/assign`, {
      entity_id: entityId,
    });
  }

  removeDocumentEntity(documentId: string, entityId: string) {
    return this.http.delete<{ ok?: boolean }>(`/api/v1/documents/${documentId}/entities/${entityId}`);
  }

  translateToRussian(documentId: string, text: string) {
    return this.http.post<TranslateResponse>(`/api/v1/documents/${documentId}/translate`, {
      text,
      target_lang: 'ru',
    });
  }

  translateToRussianStream(documentId: string): Observable<string> {
    return new Observable<string>((observer) => {
      const controller = new AbortController();

      fetch(`/api/v1/documents/${documentId}/translate/stream`, {
        method: 'POST',
        headers: this.getStreamHeaders(),
        body: JSON.stringify({
          target_lang: 'ru',
        }),
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok || !response.body) {
            throw new Error('Ошибка потокового перевода');
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let buffer = '';

          while (true) {
            const { value, done } = await reader.read();

            if (done) {
              observer.complete();
              break;
            }

            buffer += decoder.decode(value, { stream: true });

            const events = buffer.split('\n\n');
            buffer = events.pop() || '';

            for (const event of events) {
              const lines = event.split('\n');

              for (const line of lines) {
                if (line.startsWith('data: ')) {
                  const data = line.slice(6);

                  if (data === '[DONE]') {
                    observer.complete();
                    return;
                  }

                  observer.next(data);
                }

                if (line.startsWith('event: error')) {
                  observer.error(new Error('Ошибка потокового перевода'));
                  return;
                }
              }
            }
          }
        })
        .catch((error) => {
          if (error.name !== 'AbortError') {
            observer.error(error);
          }
        });

      return () => {
        controller.abort();
      };
    });
  }

  summarize(documentId: string, text: string) {
    return this.http.post<SummaryResponse>(`/api/v1/documents/${documentId}/summary/refine/stream`, {
      text,
    });
  }

  summarizeRefineStream(
    documentId: string,
    source: 'original' | 'translated' = 'translated',
    userInstruction = '',
    mode: 'add_context' | 'shorten' | 'fix_facts' = 'add_context',
  ): Observable<string> {
    return new Observable<string>((observer) => {
      const controller = new AbortController();

      fetch(`/api/v1/documents/${documentId}/summary/refine/stream`, {
        method: 'POST',
        headers: this.getStreamHeaders(),
        body: JSON.stringify({
          source,
          user_instruction: userInstruction,
          mode,
        }),
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok || !response.body) {
            throw new Error('Ошибка потокового уточнения аннотации');
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let buffer = '';

          while (true) {
            const { value, done } = await reader.read();

            if (done) {
              observer.complete();
              break;
            }

            buffer += decoder.decode(value, { stream: true });

            const events = buffer.split('\n\n');
            buffer = events.pop() || '';

            for (const event of events) {
              const lines = event.split('\n');

              for (const line of lines) {
                if (line.startsWith('data: ')) {
                  const data = line.slice(6);

                  if (data === '[DONE]') {
                    observer.complete();
                    return;
                  }

                  observer.next(data);
                }

                if (line.startsWith('event: error')) {
                  observer.error(new Error('Ошибка потокового уточнения аннотации'));
                  return;
                }
              }
            }
          }
        })
        .catch((error) => {
          if (error.name !== 'AbortError') {
            observer.error(error);
          }
        });

      return () => {
        controller.abort();
      };
    });
  }

  summarizeStream(documentId: string, source: 'original' | 'translated' = 'translated'): Observable<string> {
    return new Observable<string>((observer) => {
      const controller = new AbortController();

      fetch(`/api/v1/documents/${documentId}/summary/stream`, {
        method: 'POST',
        headers: this.getStreamHeaders(),
        body: JSON.stringify({ source }),
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok || !response.body) {
            throw new Error('Ошибка потокового формирования аннотации');
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let buffer = '';

          while (true) {
            const { value, done } = await reader.read();

            if (done) {
              observer.complete();
              break;
            }

            buffer += decoder.decode(value, { stream: true });

            const events = buffer.split('\n\n');
            buffer = events.pop() || '';

            for (const event of events) {
              const lines = event.split('\n');

              for (const line of lines) {
                if (line.startsWith('data: ')) {
                  const data = line.slice(6);

                  if (data === '[DONE]') {
                    observer.complete();
                    return;
                  }

                  observer.next(data);
                }

                if (line.startsWith('event: error')) {
                  observer.error(new Error('Ошибка потокового формирования аннотации'));
                  return;
                }
              }
            }
          }
        })
        .catch((error) => {
          if (error.name !== 'AbortError') {
            observer.error(error);
          }
        });

      return () => {
        controller.abort();
      };
    });
  }

  tagText(documentId: string, maxTags = 12, useTranslation = false) {
    return this.http.post<{ tags?: string[]; ok?: boolean }>(`/api/v1/documents/${documentId}/tags`, {
      max_tags: maxTags,
      use_translation: useTranslation,
    });
  }

  getDocumentTags(documentId: string) {
    return this.http.get<DocumentTagsResponse>(`/api/v1/documents/${documentId}/tags`);
  }

  getTagCatalog(documentId: string, languageScope: 'original' | 'translated') {
    return this.http.get<DocumentTagRef[]>(`/api/v1/documents/${documentId}/tags/catalog`, {
      params: { language_scope: languageScope },
    });
  }

  assignDocumentTag(documentId: string, tagId: string) {
    return this.http.post<{ ok?: boolean }>(`/api/v1/documents/${documentId}/tags/assign`, {
      tag_id: tagId,
    });
  }

  removeDocumentTag(documentId: string, tagId: string) {
    return this.http.delete<{ ok?: boolean }>(`/api/v1/documents/${documentId}/tags/${tagId}`);
  }

  getAvailableDocumentStatuses() {
    return this.http.get<DocumentStatusCatalogItem[]>('/api/v1/documents/statuses/catalog');
  }

  getDocumentStatuses(documentId: string) {
    return this.http.get<DocumentStatusesResponse>(`/api/v1/documents/${documentId}/statuses`);
  }

  assignDocumentStatus(documentId: string, code: string) {
    return this.http.post<{ ok?: boolean; document_id?: string; status_code?: string }>(
      `/api/v1/documents/${documentId}/statuses`,
      { code },
    );
  }

  removeDocumentStatus(documentId: string, code: string) {
    return this.http.delete<{ ok?: boolean; document_id?: string; status_code?: string }>(
      `/api/v1/documents/${documentId}/statuses/${encodeURIComponent(code)}`,
    );
  }

  getDocumentCategories(documentId: string) {
    return this.http.get<DocumentCategorizeResponse>(`/api/v1/documents/${documentId}/categories`);
  }

  categorizeDocument(documentId: string) {
    return this.http.post<DocumentCategorizeResponse>(`/api/v1/documents/${documentId}/categorize`, {});
  }

  getCategoryCatalog(documentId: string) {
    return this.http.get<DocumentEntityRef[]>(`/api/v1/documents/${documentId}/categories/catalog`);
  }

  assignDocumentCategory(documentId: string, categoryId: string) {
    return this.http.post<{ ok?: boolean }>(`/api/v1/documents/${documentId}/categories/assign`, {
      category_id: categoryId,
    });
  }

  removeDocumentCategory(documentId: string, categoryId: string) {
    return this.http.delete<{ ok?: boolean }>(`/api/v1/documents/${documentId}/categories/${categoryId}`);
  }
}

import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';

export interface ImageInfo {
  url: string;
  alt: string | null;
  title: string | null;
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
}

export interface EntitiesResponse {
  military_equipment: string[];
  manufacturers: string[];
  contracts: string[];
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

  extractEntities(text: string) {
    return this.http.post<EntitiesResponse>('/api/v1/documents/{id}/entities', {
      text,
    });
  }

  translateToRussian(text: string) {
    return this.http.post<TranslateResponse>('/api/v1/documents/{id}/translate', {
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

  summarize(text: string) {
    return this.http.post<SummaryResponse>('/api/v1/documents/${documentId}/summary/refine/stream', {
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

  tagText(text: string, maxTags = 12) {
    return this.http.post<{ tags: string[] }>('/api/v1/extract/tags', {
      text,
      max_tags: maxTags,
    });
  }
}

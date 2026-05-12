import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { AuthService } from '../../core/auth/auth.service';

export interface ProcessingJobRow {
  id: string;
  document_id: string | null;
  source_id: string | null;
  job_type: string;
  status: string;
  model_name: string | null;
  provider: string | null;
  batch_id: string | null;
  queue_name: string | null;
  queue_job_key: string | null;
  started_by_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  created_at: string | null;
}

export interface ProcessingCounters {
  documents_total: number;
  with_translations: number;
  with_annotations: number;
  categorized: number;
  with_entities: number;
  tagged_original_lang: number;
  tagged_translated_lang: number;
}

export interface ProcessingDashboardSnapshot {
  snapshot_at: string;
  jobs: ProcessingJobRow[];
  counters: ProcessingCounters;
}

export interface PurgeDocumentsResponse {
  ok: boolean;
  deleted_documents: number;
}

@Injectable({
  providedIn: 'root',
})
export class ProcessingDashboardApi {
  constructor(private readonly authService: AuthService) {}

  streamDashboard(): Observable<ProcessingDashboardSnapshot> {
    return new Observable<ProcessingDashboardSnapshot>((observer) => {
      const token = this.authService.getToken();
      const controller = new AbortController();

      fetch('/api/v1/processing/dashboard/stream', {
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

            const looksLikeSnapshotData = payloadText.includes('"snapshot_at"') && payloadText.includes('"counters"');
            const isSnapshotEvent = eventName === 'snapshot' || (eventName === 'message' && looksLikeSnapshotData);
            if (!isSnapshotEvent) {
              eventName = 'message';
              dataLines = [];
              return;
            }

            try {
              const payload = JSON.parse(payloadText) as ProcessingDashboardSnapshot;
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

  async purgeAllDocuments(): Promise<PurgeDocumentsResponse> {
    const token = this.authService.getToken();
    const response = await fetch('/api/v1/processing/debug/documents/purge', {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    if (!response.ok) {
      throw new Error(`Ошибка очистки документов: ${response.status}`);
    }
    return (await response.json()) as PurgeDocumentsResponse;
  }
}

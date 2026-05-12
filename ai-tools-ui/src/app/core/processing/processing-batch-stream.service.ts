import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { AuthService } from '../auth/auth.service';

export type ProcessingBatchKind = 'translate' | 'annotate' | 'categorize' | 'extractor' | 'tagger';

/** Снимок SSE ``/processing/batches/{id}/stream`` (совпадает с REST + ``snapshot_at`` / ``kind``). */
export interface ProcessingBatchStreamSnapshot {
  snapshot_at: string;
  kind: ProcessingBatchKind;
  ok: boolean;
  batch_id: string;
  scanned: number;
  enqueued: number;
  completed: number;
  failed: number;
  skipped: number;
  pending: number;
  done: boolean;
}

@Injectable({
  providedIn: 'root',
})
export class ProcessingBatchStreamApi {
  constructor(private readonly auth: AuthService) {}

  stream(batchId: string, kind: ProcessingBatchKind): Observable<ProcessingBatchStreamSnapshot> {
    const params = new URLSearchParams({ kind });
    const url = `/api/v1/processing/batches/${encodeURIComponent(batchId)}/stream?${params.toString()}`;

    return new Observable<ProcessingBatchStreamSnapshot>((observer) => {
      const token = this.auth.getToken();
      const controller = new AbortController();
      const outcome = { finalized: false };

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

          const dispatchEvent = (): void => {
            if (outcome.finalized) {
              return;
            }
            if (eventName === 'heartbeat') {
              eventName = 'message';
              dataLines = [];
              return;
            }
            if (eventName === 'error') {
              outcome.finalized = true;
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
              payloadText.includes('"snapshot_at"') && payloadText.includes('"batch_id"');
            const isSnapshot = eventName === 'snapshot' || (eventName === 'message' && looksLikeSnapshot);
            if (!isSnapshot) {
              eventName = 'message';
              dataLines = [];
              return;
            }
            try {
              const payload = JSON.parse(payloadText) as ProcessingBatchStreamSnapshot;
              observer.next(payload);
            } catch {
              outcome.finalized = true;
              observer.error(new Error('Некорректный JSON в SSE snapshot'));
              return;
            } finally {
              if (!outcome.finalized) {
                eventName = 'message';
                dataLines = [];
              }
            }
          };

          try {
            while (!outcome.finalized) {
              const { done, value } = await reader.read();
              if (outcome.finalized) {
                break;
              }
              if (done) {
                if (dataLines.length > 0) {
                  dispatchEvent();
                }
                if (!outcome.finalized) {
                  outcome.finalized = true;
                  observer.complete();
                }
                break;
              }
              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split(/\r?\n/);
              buffer = lines.pop() ?? '';
              for (const line of lines) {
                if (outcome.finalized) {
                  break;
                }
                const normalized = line.replace(/^\uFEFF/, '');
                if (normalized.trim() === '') {
                  dispatchEvent();
                  if (outcome.finalized) {
                    break;
                  }
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
          } finally {
            await reader.cancel().catch(() => undefined);
          }
        })
        .catch((error: unknown) => {
          const fetchError = error as { name?: string };
          if (fetchError?.name !== 'AbortError' && !outcome.finalized) {
            outcome.finalized = true;
            observer.error(error);
          }
        });

      return () => controller.abort();
    });
  }
}

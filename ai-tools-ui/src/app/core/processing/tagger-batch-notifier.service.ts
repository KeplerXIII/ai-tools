import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, OnDestroy } from '@angular/core';
import { BehaviorSubject, Subscription } from 'rxjs';

import { DocumentsApi, TaggerBatchStatusResponse } from '../../features/documents/documents-api';

import { GlobalToast } from './abstract-batch-toast-notifier.service';
import { ProcessingBatchStreamApi, ProcessingBatchStreamSnapshot } from './processing-batch-stream.service';

export type { GlobalToast };

type TaggerSource = 'original' | 'translated';

const RECONNECT_MS = 3000;
const TOAST_HIDE_MS = 9000;

@Injectable({
  providedIn: 'root',
})
export class TaggerBatchNotifierService implements OnDestroy {
  private readonly storageKeys: Record<TaggerSource, string> = {
    original: 'tagger_batch_original',
    translated: 'tagger_batch_translated',
  };
  private streamSubs: Partial<Record<TaggerSource, Subscription>> = {};
  private httpFallbackSubs: Partial<Record<TaggerSource, Subscription>> = {};
  private reconnectTimers: Partial<Record<TaggerSource, ReturnType<typeof setTimeout>>> = {};
  private trackedIds: Partial<Record<TaggerSource, string>> = {};
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly _toast = new BehaviorSubject<GlobalToast | null>(null);
  readonly toast$ = this._toast.asObservable();

  constructor(
    private readonly batchStream: ProcessingBatchStreamApi,
    private readonly documentsApi: DocumentsApi,
  ) {}

  ngOnDestroy(): void {
    (['original', 'translated'] as const).forEach((source) => {
      this.clearReconnect(source);
      this.streamSubs[source]?.unsubscribe();
      delete this.streamSubs[source];
      this.httpFallbackSubs[source]?.unsubscribe();
      delete this.httpFallbackSubs[source];
    });
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
      this.hideTimer = null;
    }
  }

  initFromStorage(): void {
    (['original', 'translated'] as const).forEach((source) => {
      const batchId = localStorage.getItem(this.storageKeys[source]);
      if (batchId) {
        this.startStream(source, batchId);
      }
    });
  }

  trackBatch(batchId: string, source: TaggerSource): void {
    localStorage.setItem(this.storageKeys[source], batchId);
    this.startStream(source, batchId);
  }

  stopTrackingByBatchId(batchId: string): boolean {
    const normalized = batchId.trim();
    if (!normalized) {
      return false;
    }
    let stopped = false;
    (['original', 'translated'] as const).forEach((source) => {
      const current = localStorage.getItem(this.storageKeys[source]);
      if (current === normalized) {
        this.stopTracking(source);
        stopped = true;
      }
    });
    return stopped;
  }

  dismissToast(): void {
    this._toast.next(null);
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
      this.hideTimer = null;
    }
  }

  private startStream(source: TaggerSource, batchId: string): void {
    this.clearReconnect(source);
    this.httpFallbackSubs[source]?.unsubscribe();
    delete this.httpFallbackSubs[source];
    this.streamSubs[source]?.unsubscribe();
    delete this.streamSubs[source];
    this.trackedIds[source] = batchId;
    this.streamSubs[source] = this.batchStream.stream(batchId, 'tagger').subscribe({
      next: (snap) => this.onSnapshot(source, snap),
      error: () => this.onTransportError(source),
      complete: () => this.onStreamComplete(source),
    });
  }

  private onSnapshot(source: TaggerSource, snap: ProcessingBatchStreamSnapshot): void {
    const { snapshot_at: _sa, kind: _k, ...rest } = snap;
    this.applyIfDone(source, rest as TaggerBatchStatusResponse);
  }

  private onStreamComplete(source: TaggerSource): void {
    const id = localStorage.getItem(this.storageKeys[source]);
    if (!id) {
      return;
    }
    this.httpFallbackSubs[source]?.unsubscribe();
    this.httpFallbackSubs[source] = this.documentsApi.getTaggerBatchStatus(id).subscribe({
      next: (s) => this.applyIfDone(source, s),
      error: (e: HttpErrorResponse) => {
        if (e.status === 404) {
          this.stopTracking(source);
        }
      },
    });
  }

  private applyIfDone(source: TaggerSource, status: TaggerBatchStatusResponse): void {
    if (!status.done) {
      return;
    }
    const sourceLabel = source === 'translated' ? 'перевод' : 'оригинал';
    const hasErrors = status.failed > 0;
    this._toast.next({
      kind: hasErrors ? 'error' : 'success',
      text: `Tagger (${sourceLabel}) завершен: готово ${status.completed}, ошибок ${status.failed}, пропущено ${status.skipped}`,
    });
    this.stopTracking(source);
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
    }
    this.hideTimer = setTimeout(() => {
      this._toast.next(null);
      this.hideTimer = null;
    }, TOAST_HIDE_MS);
  }

  private onTransportError(source: TaggerSource): void {
    const id = this.trackedIds[source] ?? localStorage.getItem(this.storageKeys[source]);
    if (!id) {
      return;
    }
    this.streamSubs[source]?.unsubscribe();
    delete this.streamSubs[source];
    this.httpFallbackSubs[source]?.unsubscribe();
    this.httpFallbackSubs[source] = this.documentsApi.getTaggerBatchStatus(id).subscribe({
      next: (s) => {
        if (s.done) {
          this.applyIfDone(source, s);
        } else {
          this.scheduleReconnect(source, id);
        }
      },
      error: (e: HttpErrorResponse) => {
        if (e.status === 404) {
          this.stopTracking(source);
        } else {
          this.scheduleReconnect(source, id);
        }
      },
    });
  }

  private scheduleReconnect(source: TaggerSource, batchId: string): void {
    this.clearReconnect(source);
    this.reconnectTimers[source] = setTimeout(() => {
      delete this.reconnectTimers[source];
      if (localStorage.getItem(this.storageKeys[source]) === batchId) {
        this.startStream(source, batchId);
      }
    }, RECONNECT_MS);
  }

  private clearReconnect(source: TaggerSource): void {
    const t = this.reconnectTimers[source];
    if (t) {
      clearTimeout(t);
      delete this.reconnectTimers[source];
    }
  }

  private stopTracking(source: TaggerSource): void {
    this.clearReconnect(source);
    this.streamSubs[source]?.unsubscribe();
    delete this.streamSubs[source];
    this.httpFallbackSubs[source]?.unsubscribe();
    delete this.httpFallbackSubs[source];
    delete this.trackedIds[source];
    localStorage.removeItem(this.storageKeys[source]);
  }
}

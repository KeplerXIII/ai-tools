import { Injectable } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { BehaviorSubject, Subscription, timer } from 'rxjs';

import { DocumentsApi } from '../../features/documents/documents-api';

type ToastKind = 'success' | 'error';

export interface GlobalToast {
  kind: ToastKind;
  text: string;
}

type TaggerSource = 'original' | 'translated';

@Injectable({
  providedIn: 'root',
})
export class TaggerBatchNotifierService {
  private readonly storageKeys: Record<TaggerSource, string> = {
    original: 'tagger_batch_original',
    translated: 'tagger_batch_translated',
  };
  private pollSubs: Partial<Record<TaggerSource, Subscription>> = {};
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly _toast = new BehaviorSubject<GlobalToast | null>(null);
  readonly toast$ = this._toast.asObservable();

  constructor(private readonly documentsApi: DocumentsApi) {}

  initFromStorage(): void {
    (['original', 'translated'] as const).forEach((source) => {
      const batchId = localStorage.getItem(this.storageKeys[source]);
      if (batchId) {
        this.startPolling(source, batchId);
      }
    });
  }

  trackBatch(batchId: string, source: TaggerSource): void {
    localStorage.setItem(this.storageKeys[source], batchId);
    this.startPolling(source, batchId);
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

  private startPolling(source: TaggerSource, batchId: string): void {
    this.pollSubs[source]?.unsubscribe();
    this.pollSubs[source] = timer(0, 5000).subscribe(() => {
      this.documentsApi.getTaggerBatchStatus(batchId).subscribe({
        next: (status) => this.handleStatus(source, status),
        error: (err: HttpErrorResponse) => {
          if (err.status === 404) {
            this.stopTracking(source);
          }
        },
      });
    });
  }

  private handleStatus(
    source: TaggerSource,
    status: {
      done: boolean;
      completed: number;
      failed: number;
      skipped: number;
    },
  ): void {
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
    }, 9000);
  }

  private stopTracking(source: TaggerSource): void {
    this.pollSubs[source]?.unsubscribe();
    delete this.pollSubs[source];
    localStorage.removeItem(this.storageKeys[source]);
  }
}

import { Injectable } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { BehaviorSubject, Subscription, timer } from 'rxjs';

import { DocumentsApi, TranslateMissingBatchStatusResponse } from '../../features/documents/documents-api';

type ToastKind = 'success' | 'error';

export interface GlobalToast {
  kind: ToastKind;
  text: string;
}

@Injectable({
  providedIn: 'root',
})
export class TranslateBatchNotifierService {
  private readonly storageKey = 'translate_missing_batch_id';
  private pollSub: Subscription | null = null;
  private hideTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly _toast = new BehaviorSubject<GlobalToast | null>(null);
  /** Async pipe в корневом компоненте запускает change detection при обновлении тоста. */
  readonly toast$ = this._toast.asObservable();

  constructor(private readonly documentsApi: DocumentsApi) {}

  initFromStorage(): void {
    const batchId = localStorage.getItem(this.storageKey);
    if (batchId) {
      this.startPolling(batchId);
    }
  }

  trackBatch(batchId: string): void {
    localStorage.setItem(this.storageKey, batchId);
    this.startPolling(batchId);
  }

  dismissToast(): void {
    this._toast.next(null);
    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
      this.hideTimer = null;
    }
  }

  private startPolling(batchId: string): void {
    this.pollSub?.unsubscribe();
    this.pollSub = timer(0, 5000).subscribe(() => {
      this.documentsApi.getTranslateMissingBatchStatus(batchId).subscribe({
        next: (status) => this.handleStatus(status),
        error: (err: HttpErrorResponse) => {
          if (err.status === 404) {
            this.stopTracking();
          }
        },
      });
    });
  }

  private handleStatus(status: TranslateMissingBatchStatusResponse): void {
    if (!status.done) {
      return;
    }

    const hasErrors = status.failed > 0;
    this._toast.next({
      kind: hasErrors ? 'error' : 'success',
      text: `Перевод завершен: переведено ${status.completed}, ошибок ${status.failed}, пропущено ${status.skipped}`,
    });
    this.stopTracking();

    if (this.hideTimer) {
      clearTimeout(this.hideTimer);
    }
    this.hideTimer = setTimeout(() => {
      this._toast.next(null);
      this.hideTimer = null;
    }, 9000);
  }

  private stopTracking(): void {
    this.pollSub?.unsubscribe();
    this.pollSub = null;
    localStorage.removeItem(this.storageKey);
  }
}
